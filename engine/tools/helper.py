"""Studio's helper child: ``python -B -m engine helper GAME`` (F47 ``04-technical.md`` §7.3,
§8; PR-F47-12, 13, 16; AC-F47-21).

Why this module exists: Studio never imports pygame (ADR-0008), but its settings previews must
come from the real renderer, JPEG and WebP thumbnails need pygame's decoders, and ▶ needs the
engine's audio loader. Spawning pygame per request costs about a second, so one long-lived
child does all three, and the 0.5 s preview target holds once it is warm.

- **Requests** (stdin, one ASCII JSON line each, at most ``HELPER_REQUEST_MAX`` bytes):
  ``{"v": 1, "op", "serial", ...}`` with ``op`` one of
  ``still`` (``kind`` ``textbox``/``title``, ``width`` ≤ 640, ``overlay`` bool: when true the
  line is followed by ``checker.encode_overlay``'s bytes for ``config.toml`` only),
  ``thumb`` (``ref`` an image ref, ``size`` ≤ ``HELPER_THUMB_MAX``),
  ``play`` (``ref`` under ``audio/``), ``stop``. A line that breaks the shape, or an overlay
  that does, ends the child with exit 2 (the stream can't be trusted after it); Studio
  starts a new one on its next request. EOF on stdin ends it with 0.
- **Replies** (stdout, F44's framing: ``REPORT_MARKER`` + ASCII JSON ≤ 1 MiB): ``ready`` once,
  then per request ``png`` (``data``: base64 PNG, which Tk's ``PhotoImage(data=…)`` reads as
  is, with ``width``/``height``), ``played`` (``seconds``, or null for a streamed track),
  ``stopped``, or ``failed`` (``reason``, through ``core/redact.echo``; never a path).
- **Stills**: ``load_config`` over the overlay (a config error is the reason), then one frame
  drawn by the real code onto a ``width`` × 9/16 surface (the canvas scales to it, as at any
  window size): ``render.textbox.TextboxView`` with a sample line over the title gradient,
  or ``ui.builtin.title_screen.TitleScreen`` on a ``ui.shell.GameShell`` whose ports are
  stand-ins (no story, no audio; the title shows New Game, Load, Settings, Quit).
- **Thumbnails**: ``AssetManager.read_image_bytes`` (``GamePaths`` and the engine's header
  size check), decoded from memory, shrunk to fit ``size`` keeping the aspect. Never cached
  here: Studio's ``ThumbCache`` keys them by size and modification time.
- **Sound**: ``audio.backend.open_device`` on the first ``play``, the F08 ``AudioReader`` and
  the backend's decode. One sound at a time: ``play`` stops the last; music streams.
- **Isolation**: the SDL video driver is always ``dummy`` (no window). Reports go to a
  duplicate of fd 1; fd 1 and ``sys.stdout`` point at the null device. No bytecode, no log
  handlers (stderr only for a bad request), no write roots: it writes nothing. It runs no
  author code: no story load, no plugins, no ``define``.

Imports ``core``, ``render``, ``ui``, ``audio`` (and ``runtime``, which they build on);
never ``app``, ``meta``, ``minigames``, ``persist``, or ``runtime.interpreter``
(``tests/test_import_rules.py``).
"""

import base64
import io
import json
import logging
import os
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from engine.audio.reading import AudioLog
from engine.core.constants import CONFIG_FILENAME, CONFIG_MAX_BYTES, MB
from engine.core.editorreport import (
    HELPER_OPS,
    HELPER_REQUEST_MAX,
    HELPER_STILL_KINDS,
    HELPER_STILL_MAX_WIDTH,
    HELPER_THUMB_MAX,
    OVERLAY_HEADER_MAX,
    REPORT_MARKER,
    REPORT_MAX_BYTES,
    REPORT_TEXT_MAX_CHARS,
    REPORT_VERSION,
)
from engine.core.errors import AssetTooLarge, UserFacingError
from engine.core.logsetup import ROOT_LOGGER
from engine.core.paths import GamePaths
from engine.core.redact import echo

EXIT_DONE = 0
EXIT_BAD_INPUT = 2
STILL_CACHE_BYTES = 128 * MB            # one AssetManager per still: fonts, frames, images
SAMPLE_NAME = "Hana"
SAMPLE_LINE = ("This is how your text box looks. The words appear here as the story is "
               "told, one line at a time.")
TITLE_ENTRIES = ("new_game", "load", "settings", "quit")
AUDIO_PREFIX = "audio/"
MUSIC_PREFIX = "audio/music/"

# Reasons (drafts for the narrative designer; shown after "Preview not available: " or
# "This sound can't be played: ").
NOT_A_PICTURE = "the picture can't be read (missing, too large, or not a PNG, JPEG, or WebP)"
TOO_BIG_REPLY = "the picture is too large to send"
NOT_A_SOUND = "the sound can't be read"
NO_DEVICE = "no sound device could be opened"


class BadRequest(ValueError):
    """A request line or overlay breaks the protocol: the child exits 2."""


class Failed(Exception):
    """A request that can't be done; its text is the ``failed`` reason."""


class ReasonLog(AudioLog):
    """Keeps the last W26/W29 text as the ``failed`` reason instead of logging it."""

    def __init__(self) -> None:
        super().__init__()
        self.reason: str | None = None

    def problem(self, kind: str, file: str, message: str, **_: object) -> None:
        self.reason = message


# --- Protocol --------------------------------------------------------------------------------

def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def encode_reply(event: dict) -> bytes:
    """One reply line, without its newline."""
    return REPORT_MARKER + _dumps({"v": REPORT_VERSION, **event}).encode("ascii")


def failed(serial: int, op: str, reason: str) -> dict:
    return {"event": "failed", "serial": serial, "op": op,
            "reason": echo(reason, REPORT_TEXT_MAX_CHARS)}


def _int(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def parse_request(line: bytes) -> dict:
    """A request line (without its newline) → its dict. Raises ``BadRequest``."""
    try:
        data = json.loads(line.decode("ascii"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise BadRequest("a request isn't ASCII JSON") from None
    if not isinstance(data, dict) or type(data.get("v")) is not int \
            or data["v"] != REPORT_VERSION:
        raise BadRequest("a request has the wrong version")
    op, serial = data.get("op"), data.get("serial")
    if op not in HELPER_OPS or not _int(serial, 0, 2 ** 53):
        raise BadRequest("a request has no known op or serial")
    if op == "still":
        if data.get("kind") not in HELPER_STILL_KINDS \
                or not _int(data.get("width"), 16, HELPER_STILL_MAX_WIDTH) \
                or type(data.get("overlay", False)) is not bool:
            raise BadRequest("a still request is malformed")
    elif op in ("thumb", "play"):
        if not isinstance(data.get("ref"), str) or not data["ref"]:
            raise BadRequest("a request has no ref")
        if op == "thumb" and not _int(data.get("size"), 8, HELPER_THUMB_MAX):
            raise BadRequest("a thumb request is malformed")
    return data


def read_config_overlay(stream: BinaryIO) -> bytes | None:
    """``checker.encode_overlay``'s bytes on ``stream`` → the ``config.toml`` bytes (None:
    the overlay lists no file). Only ``config.toml`` may be listed, within its cap; exactly
    the declared bytes are read. Raises ``BadRequest``."""
    line = stream.readline(OVERLAY_HEADER_MAX + 1)
    if not line.endswith(b"\n"):
        raise BadRequest("the overlay header is too long or has no line end")
    try:
        header = json.loads(line.decode("ascii"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise BadRequest("the overlay header isn't ASCII JSON") from None
    if not isinstance(header, dict) or type(header.get("v")) is not int \
            or header["v"] != REPORT_VERSION or not isinstance(header.get("files"), list) \
            or len(header["files"]) > 1:
        raise BadRequest("the overlay header is malformed")
    if not header["files"]:
        return None
    entry = header["files"][0]
    if not isinstance(entry, dict) or entry.get("ref") != CONFIG_FILENAME \
            or not _int(entry.get("size"), 0, CONFIG_MAX_BYTES):
        raise BadRequest("the overlay may hold only config.toml, within its cap")
    size = entry["size"]
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise BadRequest("the overlay ended before its declared size")
        data += chunk
    return bytes(data)


@dataclass(frozen=True)
class ConfigOverlayPaths(GamePaths):
    """``GamePaths`` that reads ``config.toml`` from ``config`` (Studio's unsaved text).
    Every other ref, and every listing, comes from disk. Nothing is ever written."""

    config: bytes = field(default=b"", compare=False)

    def read_file(self, ref: str, *, max_bytes: int, regular: bool = False) -> bytes:
        if ref != CONFIG_FILENAME:
            return super().read_file(ref, max_bytes=max_bytes, regular=regular)
        if len(self.config) > max_bytes:
            raise AssetTooLarge(ref, max_bytes)
        return self.config


# --- The work (pygame from here on, imported inside the functions) --------------------------

class Helper:
    """Answers requests for one game folder. ``handle`` never raises but ``BadRequest``."""

    def __init__(self, paths: GamePaths) -> None:
        import pygame

        self.paths = paths
        pygame.display.init()
        pygame.font.init()
        # A display mode, so images convert as in the game (convert_alpha needs one).
        self.screen = pygame.display.set_mode((1, 1), pygame.HIDDEN)
        self._mixer = None
        self._sound = None                  # the playing Sound or music bytes, kept alive
        self.warm_up()

    def warm_up(self) -> None:
        """One small still of each kind, so the first real one doesn't pay for the imports
        and the bundled fonts (about 0.4 s cold, 25–60 ms warm). A failure here is the
        first real request's to report."""
        for kind in HELPER_STILL_KINDS:
            try:
                self.still(kind, 64, None)
            except Exception:
                pass

    def handle(self, request: dict, stream: BinaryIO) -> dict:
        op, serial = request["op"], request["serial"]
        overlay = None
        if op == "still" and request.get("overlay", False):
            overlay = read_config_overlay(stream)       # BadRequest ends the child
        self.paths.invalidate_listings()                # files may have changed since
        try:
            if op == "still":
                return self._png(serial, op, self.still(request["kind"], request["width"],
                                                        overlay))
            if op == "thumb":
                return self._png(serial, op, self.thumb(request["ref"], request["size"]))
            if op == "play":
                seconds = self.play(request["ref"])
                return {"event": "played", "serial": serial, "seconds": seconds}
            self.stop_sound()
            return {"event": "stopped", "serial": serial}
        except Failed as error:
            return failed(serial, op, str(error))
        except Exception as error:                      # an engine bug: say so, keep going
            return failed(serial, op, f"{type(error).__name__}: {error}")

    def _png(self, serial: int, op: str, surface) -> dict:
        import pygame

        buffer = io.BytesIO()
        pygame.image.save(surface, buffer, "image.png")
        data = base64.b64encode(buffer.getvalue()).decode("ascii")
        event = {"event": "png", "serial": serial, "op": op, "width": surface.get_width(),
                 "height": surface.get_height(), "data": data}
        if len(REPORT_MARKER) + len(_dumps({"v": REPORT_VERSION, **event})) > REPORT_MAX_BYTES:
            return failed(serial, op, TOO_BIG_REPLY)
        return event

    # -- stills (§7.3) --

    def _assets(self, paths: GamePaths, config):
        from engine.core.timing import GameTime
        from engine.render.assets import AssetManager

        return AssetManager(paths, budget_bytes=STILL_CACHE_BYTES,
                            scale_filter=config.window.scale_filter, time=GameTime(),
                            format_source=lambda: self.screen)

    def still(self, kind: str, width: int, overlay: bytes | None):
        """One frame of ``kind`` drawn by the real code at ``width`` × 9/16 px."""
        import pygame

        from engine.core.config import load_config
        from engine.core.constants import CANVAS_SIZE
        from engine.core.geometry import Viewport
        from engine.render.canvas import Canvas, RenderQuality

        paths = self.paths if overlay is None else ConfigOverlayPaths(self.paths.root,
                                                                      config=overlay)
        result = load_config(paths)
        if result.errors:
            raise Failed(result.errors[0].message)
        config = result.config
        assets = self._assets(paths, config)
        canvas = Canvas(assets)
        cw, ch = CANVAS_SIZE
        height = max(1, round(width * ch / cw))
        frame = pygame.Surface((width, height))
        canvas.bind(frame, Viewport(cw, ch, width, height, 0, 0, width, height),
                    RenderQuality.FINAL)
        if kind == "textbox":
            draw_textbox_still(canvas, config, assets)
        else:
            draw_title_still(canvas, config, assets)
        return frame

    # -- thumbnails (§7.3) --

    def thumb(self, ref: str, size: int):
        import pygame

        from engine.core.config_schema import Config

        assets = self._assets(self.paths, Config())
        found = assets.read_image_bytes(ref)
        if found is None:
            raise Failed(NOT_A_PICTURE)
        data, hint, w, h = found
        try:
            image = pygame.image.load(io.BytesIO(data), hint)
        except (pygame.error, OSError, ValueError, MemoryError):
            raise Failed(NOT_A_PICTURE) from None
        k = min(1.0, size / max(w, h))
        out = (max(1, round(w * k)), max(1, round(h * k)))
        image = image.convert_alpha() if image.get_flags() & pygame.SRCALPHA \
            else image.convert(32, 0)
        return pygame.transform.smoothscale(image, out) if out != (w, h) else image

    # -- sound (§7.3) --

    def play(self, ref: str) -> float | None:
        from engine.audio.backend import DecodeError, DeviceError, open_device
        from engine.audio.reading import AudioReader

        if not ref.startswith(AUDIO_PREFIX):
            raise Failed(NOT_A_SOUND)
        self.stop_sound()
        if self._mixer is None:
            try:
                self._mixer = open_device()
            except DeviceError:
                raise Failed(NO_DEVICE) from None
        log = ReasonLog()
        reader = AudioReader(self.paths, log)
        file = ref[len(AUDIO_PREFIX):]
        music = ref.startswith(MUSIC_PREFIX)
        sniffed = reader.read_music(file) if music else reader.read_sound(file)
        if sniffed is None:
            raise Failed(log.reason or NOT_A_SOUND)
        try:
            if music:
                self._mixer.music_start(sniffed, loops=0, start=0.0, fade_ms=0)
                self._sound = sniffed
                return None
            sound = self._mixer.decode(sniffed)
        except DecodeError:
            raise Failed(NOT_A_SOUND) from None
        self._sound = sound
        self._mixer.channel_play(0, sound, 0)
        return round(self._mixer.sound_seconds(sound), 3)

    def stop_sound(self) -> None:
        if self._mixer is not None:
            self._mixer.channel_stop(0)
            self._mixer.music_stop()
        self._sound = None

    def close(self) -> None:
        self.stop_sound()
        if self._mixer is not None:
            self._mixer.shutdown()


def _textbox_faces(config, assets):
    """The textbox ``FaceSet`` as ``app/text_check.resolve_faces`` builds it, without its
    warnings: an author face that doesn't load falls back to the bundled one, the others
    are synthesized from ``text_font``."""
    from engine.render.text import Face, Synth
    from engine.render.textlayout import FaceSet, FaceSource

    theme = config.theme.textbox

    def usable(ref: str | None) -> str | None:
        return ref if ref is not None and assets.check(ref, "font") is None else None

    custom = usable(theme.text_font)
    faces = {Face.REGULAR: FaceSource(custom, Face.REGULAR)}
    for face, key, synth in ((Face.BOLD, "bold_font", Synth.BOLD),
                             (Face.ITALIC, "italic_font", Synth.ITALIC),
                             (Face.BOLD_ITALIC, "bold_italic_font", Synth.BOLD_ITALIC)):
        own = usable(getattr(theme, key))
        if own is not None:
            faces[face] = FaceSource(own, face)
        elif custom is not None:
            faces[face] = FaceSource(custom, face, synth)
        else:
            faces[face] = FaceSource(None, face)
    return FaceSet(faces)


def _image_ref(assets, ref: str | None) -> str | None:
    if ref is None or assets.check(ref, "image") is not None:
        return None
    return None if assets.image(ref).is_placeholder else ref


def draw_textbox_still(canvas, config, assets) -> None:
    """The ADV box as ``TextboxScreen._draw_box`` draws it, with the whole sample line shown
    and the line indicator, over the title's gradient."""
    from engine.render.text import Face
    from engine.render.textbox import TextboxView, box_geometry, rgb_hex
    from engine.render.textlayout import FaceSource, LayoutContext, LineLayout
    from engine.script.texttags import parse
    from engine.ui.builtin.title_screen import draw_title_gradient

    theme = config.theme.textbox
    faces = _textbox_faces(config, assets)
    name_face = faces.faces[Face.BOLD]
    if theme.name_tab.text_font is not None and \
            assets.check(theme.name_tab.text_font, "font") is None:
        name_face = FaceSource(theme.name_tab.text_font, Face.BOLD)
    view = TextboxView(assets, theme, name_face,
                       frame=_image_ref(assets, theme.frame_image),
                       tab_frame=_image_ref(assets, theme.name_tab.frame_image),
                       line_image=_image_ref(assets, theme.indicator.line_image),
                       page_image=_image_ref(assets, theme.indicator.page_image))
    draw_title_gradient(canvas, config.theme.title)
    geometry = box_geometry(theme, theme.text_size)
    view.draw_box(canvas, geometry)
    view.draw_tab(canvas, view.name_tab(SAMPLE_NAME, geometry), theme.name_tab.text_color)
    body = parse(SAMPLE_LINE, lambda offset: (1, offset + 1), lambda problem: None)
    ctx = LayoutContext(assets, faces, geometry.text_size, rgb_hex(theme.text_color),
                        geometry.area[2], geometry.area[3])
    page = LineLayout(body, ctx).page(0)
    shown = page.end_glyph
    view.draw_glyphs(canvas, page, 1, shown, geometry)
    view.draw_indicator(canvas, page, 1, shown, geometry, page_kind=False, bob=0.0)


def draw_title_still(canvas, config, assets) -> None:
    """``TitleScreen.draw`` on a ``GameShell`` with stand-in ports, faded in."""
    from engine.ui.builtin.title_screen import TitleScreen
    from engine.ui.menus import MenuEntry
    from engine.ui.screen import ScreenStack
    from engine.ui.shell import GameShell, ShellPorts
    from engine.ui.theme import resolve_theme, resolve_words

    quiet = logging.getLogger(ROOT_LOGGER + ".helper")
    theme = resolve_theme(config, assets, textbox_faces=_textbox_faces(config, assets),
                          log=quiet)
    ports = ShellPorts(stack=ScreenStack(), assets=assets, dev=False, config=config,
                       new_game=_nothing, in_game_screens=list, reset_in_game=_nothing,
                       request_quit=_nothing)
    shell = GameShell(ports, theme=theme, words=resolve_words(config.words, log=quiet))
    for entry_id in TITLE_ENTRIES:
        shell.menus.add("title", MenuEntry(entry_id, action=lambda context: None))
    title = TitleScreen(shell, fade_in=False)
    title.draw(canvas)


def _nothing() -> None:
    """A stand-in port: the still never starts a game, quits, or resets."""


# --- The command -----------------------------------------------------------------------------

def _quiet_logs() -> None:
    root = logging.getLogger(ROOT_LOGGER)
    root.handlers[:] = [logging.NullHandler()]
    root.propagate = False


def _isolate_stdout() -> BinaryIO:
    """The reply stream: a duplicate of fd 1; fd 1 and ``sys.stdout`` then point at the
    null device, so nothing else (SDL, pygame) can break a reply line."""
    sys.stdout.flush()
    out = os.fdopen(os.dup(1), "wb")
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 1)
    finally:
        os.close(devnull)
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    return out


def read_requests(stream: BinaryIO) -> Iterator[dict]:
    """Each request on ``stream`` until EOF. Raises ``BadRequest``."""
    while True:
        line = stream.readline(HELPER_REQUEST_MAX + 2)
        if not line:
            return
        if not line.endswith(b"\n"):
            raise BadRequest("a request line is too long or has no line end")
        body = line[:-1]
        body = body[:-1] if body.endswith(b"\r") else body
        if body:
            yield parse_request(body)


def helper_command(game_dir: Path) -> int:
    """``python -m engine helper GAME_DIR``: answers requests until stdin ends (0), or a
    request breaks the protocol (2, nothing more is answered)."""
    sys.dont_write_bytecode = True
    _quiet_logs()
    os.environ["SDL_VIDEODRIVER"] = "dummy"             # stills only: never a window
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    out = _isolate_stdout()

    def send(event: dict) -> None:
        out.write(encode_reply(event) + b"\n")
        out.flush()

    try:
        try:
            paths = GamePaths.for_game(game_dir)
        except UserFacingError as error:
            send(failed(0, "start", str(error)))
            return EXIT_DONE
        started = time.perf_counter()
        helper = Helper(paths)
        send({"event": "ready", "seconds": round(time.perf_counter() - started, 3)})
        stream = sys.stdin.buffer
        try:
            for request in read_requests(stream):
                send(helper.handle(request, stream))
        except BadRequest as error:
            sys.stderr.write(f"helper: {error}\n")
            return EXIT_BAD_INPUT
        finally:
            helper.close()
        return EXIT_DONE
    except (BrokenPipeError, OSError):
        return EXIT_DONE                                 # Studio went away
    finally:
        try:
            out.close()
        except OSError:
            pass


__all__ = ["BadRequest", "ConfigOverlayPaths", "Helper", "draw_textbox_still",
           "draw_title_still", "encode_reply", "helper_command", "parse_request",
           "read_config_overlay"]

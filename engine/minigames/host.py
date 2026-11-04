"""``MinigameHost``: one minigame session in the window (F23 ``04`` §7.3, §7.4, §7.6, §7.8;
``07`` I-1, I-8, I-11; ADR-0009 Decision 7).

Why this module exists: the runtime hands a minigame over as one ``StartMinigame`` command
and takes one ``MinigameDone`` back; everything between is presentation. The host owns that
middle: it builds the plugin's ``Context`` over a session ledger (requested changes never
touch the story until the runtime accepts them, invariant 5), runs every plugin call inside
the author-code guard (``_call``), draws the opening picture, puts a ``MinigameScreen`` in
the stack, and posts the result when the closing dissolve ends.

- **Start** (``start``, the router's ``StartMinigame`` handler, 04 §7.4): abandon any open
  session; unless restored or fades are off, draw the in-game screens offscreen (the "from"
  picture); ADV: ``textbox.clear()``; F15's ``stop_skip()``; build the ledger, the plugin's
  ``Pcg32`` (seeded with ``cmd.seed``), the ``Context``; instantiate, ``start(ctx)``,
  ``layout(area)``; draw the opening picture offscreen (backdrop, plugin, scope widgets at
  rest, frame); insert the screen above the bottom run of in-game screens; set the cue anchor
  and the thumbnail source. Then OPENING (a dissolve over ``minigame.fade_ms``) or, restored
  / reduced motion / 0 ms, RUNNING. F10's first focus (by the input kind that reached the
  minigame) is set when RUNNING begins, so neither the opening picture nor the fade-in shows
  a focus marker (03 "Focus").
- **Finish** (``ctx.finish``, Shift+F8's test outcome, Skip Game's skipped outcome): the
  result is frozen inside the call (E276); music released, the plugin's UI sounds stop over
  100 ms, CLOSING (a dissolve to the in-game screens, or a cut). At its end the screen goes
  and ``MinigameDone`` is posted, so the next line never starts under the dissolve. Shift+F8
  and Skip Game ask ``outcome_for`` first (F24 A3), then the declared outcome, and post that
  outcome's own changes only; the session's ledger is dropped (F25 G2).
- **Skip Game** (UI-F23-12): ``can_skip`` (the game menu's ``skip_minigame`` is listed only
  over a running skippable minigame), ``ask_skip`` (``confirm_skip_minigame``, No focused),
  ``skip`` (Yes: the game menu closes as Return does, then the dissolve out).
- **Theme** (04 §7.9, §12): ``[theme.minigame]`` (``minigame_look``; ``background_image``
  checked once, W64 and the gradient when unusable); the plugin's own tokens, words, and
  display title from ``ports.tables`` (``PluginTables``).
- **W162** (dev): ``frame_cost`` warns once per minigame name per session when a frame's
  ``update`` + ``draw`` took over 8 ms (the screen times them).
- **Abandon** (nothing posted): F14's landing listener, the shell's in-game reset (load, New
  Game, title), a ``Say`` while open, a new ``StartMinigame``, the error screen (the App's
  fatal hook and the screen's ``on_exit``). The screen goes, music is released, the plugin's
  UI sounds stop, the ledger is dropped.
- **Plugin calls** (``_call``, SEC-F23-06, -08): one guard entry; the return converted
  inside it; on an exception the failure text and the traceback are built inside the guard,
  each with a fresh budget (a looping ``__str__`` gives the "without Python's text" form).
  The watchdog gives E277; a ledger refusal F22's/F21's text at the plugin's line (P prefix);
  any other ``BaseException`` E275 at the script line (``ports.where(sid)``). The host logs the
  error with its traceback (area ``plugin``), abandons, then calls ``ports.fatal`` (I-11).
- **Text** (F52, API 1.4, 07 §3.2): a session whose plugin declares API 1.4 or later has
  ``text_api``; the screen then routes raw events to a focused ``TextField`` first, and the
  host owns one modal ``OnScreenKeyboard`` per session (``keyboard``), never in
  ``ctx.scope``. ``HostPorts.text`` (or the shell's ``text``) gives the clipboard and
  language. A plugin below 1.4 gets no router, and SDL text input stays on for it.
- **Ports.** ``HostPorts`` is everything the host needs of the App, so ``minigames`` never
  imports ``app`` (``app/minigames.py`` builds it); tests build it over F10's test shell.

``LedgerCodexPort`` is both the plugin's ``CodexPort`` (reads of the preview, requests to
the ledger, A9's ``title``) and F21's view port (entries, categories, read marks, pictures)
for ``ctx.codex_view``; every public method checks the thread (``ThreadBound``).
"""

import logging
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Final

import pygame

from engine.core.constants import CANVAS_SIZE
from engine.core.geometry import Viewport
from engine.core.logsetup import get_logger
from engine.core.minigame_types import Outcome
from engine.minigames.context import Context, PlayerSettings, ThreadBound
from engine.minigames import messages
from engine.minigames.registry import PluginClass
from engine.minigames.tables import PluginLook, PluginTables, engine_token
from engine.render.canvas import Canvas, RenderQuality
from engine.render.frames import dim
from engine.render.text import FontSpec
from engine.render.thumbnail import make_thumbnail
from engine.runtime import limits
from engine.runtime.codex import UnknownEntry, WrongKind
from engine.runtime.commands import MinigameDone, MinigameUsed, StartMinigame
from engine.runtime.dice import Pcg32, make_dice
from engine.runtime.errors import StoryError
from engine.runtime.guard import NO_GUARD
from engine.runtime.minigame import (MinigameLedger, RequestError, clean_text,
                                     codex_error_text, e276_result,
                                     e277_text, plugin_failure, plugin_file, plugin_line, thaw)
from engine.runtime.values import Unsaveable, freeze, kind_words
from engine.ui.builtin.codex_page import KINDS, CodexFilter, CodexView, PickAction
from engine.ui.focus import Box, FocusScope
from engine.ui.layouts import MG_CUE_DEFAULT, Frame, minigame_frame
from engine.ui.menu_screen import keyboard_services
from engine.ui.nav import InputKind
from engine.ui.osk import OnScreenKeyboard
from engine.ui.textrouting import TextRouter, TextServices
from engine.ui.theme import measure_with, w64_text

if TYPE_CHECKING:
    from engine.minigames.screen import MinigameScreen
    from engine.runtime.guard import AuthorCodeGuard
    from engine.ui.screen import Screen, ScreenStack

RGB = tuple[int, int, int]
UI_OWNER: Final = "minigame"            # F08 C4: the owner of a plugin's UI sounds and music
STOP_UI_FADE_S: Final = 0.1             # 04 §7.4: plugin sounds stop over 100 ms
HEADING_MAX: Final = 200                # SEC-F23-07: heading and title, code points
HINT_MAX: Final = 1_000
CONFIRM_MAX: Final = 1_000
CATEGORIES_MAX: Final = 24              # codex_view: at most 24 category names …
CATEGORY_CHARS: Final = 24              # … of at most 24 code points (F25 A6)
FONT_SIZE_MAX: Final = 400
CANVAS: Final = CANVAS_SIZE
SNAPSHOT_KEY: Final = "ui-backdrop"     # the budget entries of the fade pictures (04 §10)

_log = get_logger("plugin")


class Phase(Enum):
    OPENING = "opening"
    RUNNING = "running"
    CLOSING = "closing"
    CLOSED = "closed"


class PluginFailed(Exception):
    """A plugin call failed and the session is gone (the error screen is up): callers stop."""


# --- The minigame theme area ([theme.minigame], 04 §12) --------------------------------------------

@dataclass(frozen=True)
class MinigameLook:
    """``[theme.minigame]`` (04 §12) with its follows resolved: the gradient's colors default
    to ``title.fill_*``."""

    fade_ms: int = 300
    background_image: str | None = None
    fill_top_color: RGB = (255, 255, 255)
    fill_bottom_color: RGB = (255, 255, 255)
    stage_dim_opacity: float = 0.30
    hint_text_size: int = 24


def minigame_look(cfg: Any) -> MinigameLook:
    title = cfg.title
    area = cfg.minigame
    return MinigameLook(
        fade_ms=area.fade_ms, background_image=area.background_image,
        fill_top_color=area.fill_top_color or title.fill_top_color,
        fill_bottom_color=area.fill_bottom_color or title.fill_bottom_color,
        stage_dim_opacity=area.stage_dim_opacity, hint_text_size=area.hint.text_size)


# --- Ports ------------------------------------------------------------------------------------------

def _nothing(*args: object, **kwargs: object) -> None:
    return None


@dataclass
class HostPorts:
    """What the host uses of the App (``app/minigames.py``) or of a test (Host U).

    ``shell``: F10's ``MenuShell`` (stack, assets, theme, words, painter, ``play_ui``,
    ``dev``, ``reduce_motion``); ``notify``, ``confirm``, ``set_thumbnail_source`` are the
    shell's when it has them. ``lookup(name)`` gives the registry's ``PluginClass``;
    ``where(sid)`` the script file and line of a statement; ``fatal(error)`` shows the error
    screen; ``post`` queues a story event. ``check_meter``/``check_entry`` are F22's/F21's
    name checks; ``index()`` the story's ``CodexIndex``; ``is_read``/``mark_read``/
    ``picture``/``show_locked`` F21's view port; ``image(name)`` the stage's ``ImageRef`` for
    an image name. ``stage`` is the screen drawn under an ``over_stage`` minigame (default:
    the bottom in-game screen). ``tables``: the launch's ``PluginTables`` (``[theme.plugin]``,
    ``[words.plugin]``); None: the declarations alone (Host U)."""

    shell: Any
    lookup: Callable[[str], PluginClass | None]
    post: Callable[[object], None]
    where: Callable[[str], tuple[str | None, int | None]]
    fatal: Callable[[BaseException], None]
    check_meter: Callable[[str], object]
    check_entry: Callable[[str, str], object]
    index: Callable[[], Any]
    guard: "AuthorCodeGuard" = NO_GUARD
    image: Callable[[str], Any] | None = None
    is_read: Callable[[str], bool] = lambda name: False
    mark_read: Callable[[str], object] = _nothing
    picture: Callable[[str], object] = _nothing
    show_locked: bool = False
    audio: Any = None
    cue: Any = None
    stop_skip: Callable[[], None] | None = None
    textbox: Any = None
    stage: "Screen | None" = None
    settings: Callable[[], PlayerSettings] | None = None
    focused: Callable[[], bool] = lambda: True
    viewport: Callable[[], tuple[int, int] | None] = lambda: None
    tables: PluginTables | None = None
    text: TextServices | None = None               # F52: None → the shell's ``text``
    main_thread: int = field(default_factory=threading.get_ident)
    log: logging.Logger = _log

    @property
    def stack(self) -> "ScreenStack":
        return self.shell.stack

    @property
    def dev(self) -> bool:
        return bool(self.shell.dev)


# --- The ledger's ports ------------------------------------------------------------------------

class LedgerPoints:
    """``ctx.points``'s port: reads of the preview, requests to the ledger."""

    def __init__(self, ledger: MinigameLedger) -> None:
        self._ledger = ledger

    def get(self, name: str) -> int:
        return self._ledger.meter(name)

    def names(self) -> tuple[str, ...]:
        return self._ledger.meters()

    def highest(self) -> str:
        return self._ledger.highest()

    def add(self, name: str, n: int) -> int:
        return self._ledger.add(name, n)

    def set(self, name: str, n: int) -> int:
        return self._ledger.set(name, n)


class LedgerCodexPort(ThreadBound):
    """The plugin's codex port and F21's view port over one session's ledger (04 §4.3,
    §7.3; F25 A6, F27 A9). Every public method and property checks the thread."""

    __slots__ = ("_ledger", "_index", "_is_read", "_mark_read", "_picture", "_locked")

    def __init__(self, main: int, ledger: MinigameLedger, index: Any, *,
                 is_read: Callable[[str], bool], mark_read: Callable[[str], object],
                 picture: Callable[[str], object], show_locked: bool) -> None:
        super().__init__(main)
        self._ledger = ledger
        self._index = index
        self._is_read = is_read
        self._mark_read = mark_read
        self._picture = picture
        self._locked = bool(show_locked)

    # -- F21's view port --

    @property
    def show_locked(self):
        return self._locked

    def entries(self):
        return tuple(self._index)

    def categories(self):
        return tuple(self._index.categories)

    def is_read(self, name):
        return bool(self._is_read(name))

    def mark_read(self, name):
        self._mark_read(name)

    def picture(self, image):
        return self._picture(image)

    # -- reads of the preview (both ports) --

    def tips(self):
        return self._ledger.tips()

    def items(self):
        return self._ledger.items()

    def has(self, kind, name=None):
        return self._ledger.has(kind, name)

    # -- requests --

    def give(self, name):
        return self._ledger.give(name)

    def take(self, name):
        return self._ledger.take(name)

    def unlock_tip(self, name):
        return self._ledger.unlock_tip(name)

    def title(self, name):
        """(F27 A9) The declared title of an item or tip, held or not; reads no ledger."""
        if type(name) is not str:
            raise TypeError(f"an item or tip name must be text, not {kind_words(name)}")
        entry = self._index.get(name)
        if entry is None:
            raise UnknownEntry(name, "item", self._index.suggest(name, "item"))
        return entry.title


# --- Readers (theme and words) ------------------------------------------------------------------

class ThemePort:
    """``ctx.theme``: ``get("panel.text_color")`` reads an engine token (plain values only),
    and ``get("plugin.<own name>.<key>")`` the plugin's own; ``mine("card.back_color")`` a
    token the plugin declared, checked against ``[theme.plugin]`` and typed (``tables``)."""

    def __init__(self, cfg: Any, declared: Any, name: str | None = None) -> None:
        self._cfg = cfg
        self._declared = declared
        self._own = f"plugin.{name}." if name is not None else None

    def get(self, key):
        own = self._own
        if own is not None and type(key) is str and key.startswith(own) \
                and key[len(own):] in self._declared:
            return self._declared[key[len(own):]]
        return engine_token(self._cfg, key)

    def mine(self, key):
        if type(key) is not str or key not in self._declared:
            raise KeyError(f"this minigame declares no token {clean_text(str(key), 80)!r}")
        return self._declared[key]


class WordsPort:
    """``ctx.words``: ``get("yes")`` an engine word, ``mine("hint")`` a word the plugin
    declared, checked against ``[words.plugin]`` (``title`` is the display title)."""

    def __init__(self, words: Any, declared: Any, title: str) -> None:
        self._words = words
        self._declared = declared
        self._title = title

    def get(self, key):
        if type(key) is not str or key not in self._words.keys():
            raise KeyError(f"there is no word {clean_text(str(key), 80)!r}")
        return self._words.get(key)

    def mine(self, key):
        if key == "title":
            return self._title
        if type(key) is not str or key not in self._declared:
            raise KeyError(f"this minigame declares no word {clean_text(str(key), 80)!r}")
        return self._declared[key]


class _SilentMusic:
    """``ctx.music()`` without an audio service: every call does nothing."""

    active = False

    def play(self, file: str, *, loop: bool = True, fadein: float = 0.0,
             fadeout: float = 0.0, volume: int = 100) -> None:
        pass

    def stop(self, fadeout: float = 0.0) -> None:
        pass

    def position(self) -> None:
        return None

    def release(self) -> None:
        pass


# --- The session --------------------------------------------------------------------------------

@dataclass(eq=False)
class Session:
    """One running minigame (presentation-only state, 04 §3)."""

    cmd: StartMinigame
    entry: PluginClass
    look: MinigameLook
    ledger: MinigameLedger
    scope: FocusScope
    title: str
    own: PluginLook | None = None       # the plugin's checked tokens and words
    plugin: Any = None
    ctx: Context | None = None
    screen: "MinigameScreen | None" = None
    phase: Phase = Phase.OPENING
    t: float = 0.0                      # fade progress 0 → 1
    fade_s: float = 0.0
    from_pic: pygame.Surface | None = None
    opening: pygame.Surface | None = None
    thumb: pygame.Surface | None = None
    last: pygame.Surface | None = None
    stage_pic: pygame.Surface | None = None
    gradient: pygame.Surface | None = None
    heading_on: bool = False
    heading_text: str | None = None     # None: the display title
    hint_text: str = ""
    cue_point: tuple[float, float] | None = None
    frame: Frame | None = None
    area: Box = Box(0, 0, 0, 0)          # set by the first layout
    dirty: bool = True                  # the frame needs laying out again
    music: Any = None
    used: bool = False                  # MinigameUsed posted
    last_kind: InputKind = InputKind.KEYS
    finished: bool = False
    inserted: bool = False              # the screen is in the stack
    result: object = None
    changes: tuple = ()
    settings: PlayerSettings | None = None
    held: list = field(default_factory=list)       # budget entries held
    text_api: bool = False              # F52: the plugin declares API 1.4 or later
    keyboard: OnScreenKeyboard | None = None       # F52: host-owned, modal
    router: TextRouter | None = None

    @property
    def sig(self):
        return self.entry.sig


# --- The host -----------------------------------------------------------------------------------

class MinigameHost:
    """The router's ``StartMinigame`` handler and the owner of the one open session."""

    def __init__(self, ports: HostPorts) -> None:
        self.ports = ports
        self.session: Session | None = None
        self._depth = 0
        self.offscreen_draws = 0         # AC-F23-63's count of offscreen draws
        self.smoothscales = 0            # thumbnails made (one per session at most)
        self._tables: PluginTables | None = ports.tables
        self._slow_warned: set[str] = set()                  # W162: once per minigame name
        self._background: tuple[str, Any] | None = None      # (ref, ImageRef | None)
        self._missing_images: set[str] = set()               # gui_image's W64, once per ref

    # -- the shell's pieces --

    @property
    def shell(self) -> Any:
        return self.ports.shell

    def reduce_motion(self) -> bool:
        settings = self.ports.settings
        if settings is not None:
            return bool(settings().reduce_motion) or bool(self.shell.reduce_motion)
        return bool(self.shell.reduce_motion)

    def player_settings(self) -> PlayerSettings:
        settings = self.ports.settings
        if settings is not None:
            return settings()
        return PlayerSettings(text_scale=self.shell.painter.text_scale(),
                              reduce_motion=bool(self.shell.reduce_motion))

    def plugin_look(self, entry: PluginClass) -> PluginLook:
        """The plugin's checked tokens, words, and display title (``[theme.plugin]``,
        ``[words.plugin]``; without ``ports.tables``, its declarations alone)."""
        tables = self._tables
        if tables is None:
            empty: Any = {}
            tables = self._tables = PluginTables(empty, empty, self.shell.theme.cfg,
                                                 dev=False)
        return tables.look(entry)

    def background(self, look: MinigameLook) -> Any:
        """``minigame.background_image`` as an ``ImageRef``, checked once per ref; a missing
        or unusable one is None (the gradient) with one W64."""
        ref = look.background_image
        if ref is None:
            return None
        found = self._background
        if found is not None and found[0] == ref:
            return found[1]
        assets = self.shell.assets
        image = None
        problem = assets.check(ref, "image")
        if problem is not None:
            get_logger("ui").warning("%s", w64_text("minigame", "background_image", ref,
                                                    problem), extra={"code": "W64"})
        else:
            image = assets.image(ref)
            if image.is_placeholder:
                image = None
        self._background = (ref, image)
        return image

    def gui_image(self, s: Session, ref: str) -> Any:
        """``ctx.gui_image``: the ``ImageRef``, or None (W64 once per ref, dev runs)."""
        assets = self.shell.assets
        problem = assets.check(ref, "image")
        image = assets.image(ref) if problem is None else None
        if image is not None and not image.is_placeholder:
            return image
        if self.ports.dev and ref not in self._missing_images:
            self._missing_images.add(ref)
            self.ports.log.warning("%s", messages.w64_plugin_image(
                s.sig.name, ref, problem.kind if problem is not None else "unreadable",
                problem.suggestion if problem is not None else None), extra={"code": "W64"})
        return None

    # -- start (04 §7.4) --

    def start(self, cmd: StartMinigame) -> None:
        """The ``StartMinigame`` handler."""
        self.abandon()
        entry = self.ports.lookup(cmd.name)
        if entry is None:            # the runtime checks the name; a registry swap (F39)
            file, line = self.ports.where(cmd.sid)
            self.ports.fatal(StoryError(f"there is no minigame named {cmd.name!r} any more.",
                                        code="E270", file=file, line=line))
            return
        shell = self.shell
        look = minigame_look(shell.theme.cfg)
        fades = not cmd.restored and not self.reduce_motion() and look.fade_ms > 0
        size = self._size()
        from_pic = self._offscreen(size, self.draw_in_game) if fades else None
        textbox = self.ports.textbox
        if textbox is not None and not getattr(textbox, "nvl_on", False):
            textbox.clear()                                   # PR-F23-21 (ADV)
        if self.ports.stop_skip is not None:
            self.ports.stop_skip()                            # PR-F23-23
        sig = entry.sig
        ledger = MinigameLedger(cmd.base, check_meter=self.ports.check_meter,
                                check_entry=self.ports.check_entry, game=sig.name)
        scope = FocusScope(on_change=self._focus_sound)
        own = self.plugin_look(entry)
        s = Session(cmd, entry, look, ledger, scope, own.title, own)
        s.fade_s = look.fade_ms / 1000.0 if fades else 0.0
        s.from_pic = from_pic
        s.settings = self.player_settings()
        s.text_api = _minor(entry.api) >= 4                        # F52 (API 1.4)
        last = self.ports.stack.last_input
        s.last_kind = InputKind.MOUSE if last is InputKind.MOUSE else InputKind.KEYS
        self.session = s
        self._hold(s, from_pic)
        main = self.ports.main_thread
        core = Pcg32(ready=True)
        core.seed(cmd.seed)
        index = self.ports.index()
        codex = LedgerCodexPort(main, ledger, index, is_read=self.ports.is_read,
                                mark_read=self.ports.mark_read, picture=self.ports.picture,
                                show_locked=self.ports.show_locked)
        s.ctx = Context(main, port=_SessionPort(self, s), args=thaw(cmd.args),
                        points=LedgerPoints(ledger), codex=codex, dice=make_dice(core),
                        theme=ThemePort(shell.theme.cfg, own.tokens, sig.name),
                        words=WordsPort(shell.words, own.words, own.title),
                        scope=scope, painter=shell.painter, dev=self.ports.dev,
                        log=get_logger("plugin"), story=cmd.names)
        self.relayout(s, call_layout=False)                   # ctx.area is set in start
        try:
            s.plugin = self._call(entry.cls)
            self._call(s.plugin.start, s.ctx)
            self.relayout(s, call_layout=False)
            self._call(s.plugin.layout, s.area)
            self.relayout(s)
        except PluginFailed:
            return
        if s.entry.over_stage:
            s.stage_pic = self._offscreen(size, self._draw_stage)
            if s.stage_pic is not None:
                dim(s.stage_pic, shell.theme.cfg.menu.dim_color, look.stage_dim_opacity)
                self._hold(s, s.stage_pic)
        from engine.minigames.screen import MinigameScreen   # screen.py imports this module
        screen = MinigameScreen(self, s)
        s.screen = screen
        try:
            s.opening = self._offscreen(size, lambda canvas: screen.draw_running(canvas))
        except PluginFailed:
            return
        self._hold(s, s.opening)
        if self.session is not s:
            return
        self.ports.stack.insert_above_in_game(screen)
        s.inserted = True
        cue = self.ports.cue
        if cue is not None:
            cue.set_anchor(lambda: s.frame.cue if s.frame is not None else MG_CUE_DEFAULT)
        source = getattr(shell, "set_thumbnail_source", None)
        if source is not None:
            source(self.thumbnail)
        if s.fade_s <= 0:
            self._running(s)
        else:
            s.phase = Phase.OPENING
        if s.finished:
            self.begin_close(s)

    def _focus_sound(self, w: object) -> None:
        self.shell.play_ui(self.shell.theme.cfg.button.focus_sound)

    # -- frames --

    def relayout(self, s: Session, *, call_layout: bool = True) -> None:
        """The frame again after a heading/hint/cue/text-size change (04 §7.11); the plugin
        gets ``layout(area)`` when the content area moved (UI-F23-04)."""
        for _ in range(3):
            if not s.dirty:
                return
            s.dirty = False
            shell = self.shell
            cfg = shell.theme.cfg
            scale = shell.painter.text_scale()
            heading = (s.heading_text if s.heading_text is not None else s.title) \
                if s.heading_on else None
            assets = shell.assets
            s.frame = minigame_frame(
                scale, heading=heading, hint=s.hint_text or None,
                measure=measure_with(assets, shell.theme.font(s.look.hint_text_size)),
                heading_measure=measure_with(assets, shell.theme.font(
                    cfg.panel.heading.text_size, bold=True)),
                heading_size=cfg.panel.heading.text_size, hint_size=s.look.hint_text_size,
                cue_point=s.cue_point)
            area = s.frame.content
            moved = area != s.area
            s.area = area
            if moved and call_layout and s.plugin is not None:
                self._call(s.plugin.layout, area)

    def _size(self) -> tuple[int, int]:
        size = self.ports.viewport()
        if size is None or size[0] <= 0 or size[1] <= 0:
            return CANVAS
        return size

    def _offscreen(self, size: tuple[int, int],
                   draw: Callable[[Canvas], None]) -> pygame.Surface | None:
        """``draw`` on a new surface of ``size`` (device pixels of the viewport)."""
        w, h = size
        surface = pygame.Surface((w, h))
        surface.fill((0, 0, 0))
        canvas = Canvas(self.shell.assets)
        canvas.bind(surface, Viewport(CANVAS[0], CANVAS[1], w, h, 0, 0, w, h),
                    RenderQuality.FINAL)
        self.offscreen_draws += 1
        draw(canvas)
        return surface

    def in_game_run(self) -> list["Screen"]:
        """The bottom run of in-game screens (stage, say window, choices) under the
        minigame."""
        run = []
        session = self.session
        for screen in self.ports.stack:
            if not screen.in_game or (session is not None and screen is session.screen):
                break
            run.append(screen)
        return run

    def draw_in_game(self, canvas: Canvas) -> None:
        run = self.in_game_run()
        start = 0
        for index in range(len(run) - 1, -1, -1):
            if getattr(run[index], "opaque", False):
                start = index
                break
        for screen in run[start:]:
            screen.draw(canvas)

    def _draw_stage(self, canvas: Canvas) -> None:
        stage = self.ports.stage
        if stage is None:
            run = self.in_game_run()
            stage = run[0] if run else None
        if stage is not None:
            stage.draw(canvas)

    def _hold(self, s: Session, surface: pygame.Surface | None) -> None:
        """Count a session picture in the budget (``ui-backdrop`` entries, 04 §10)."""
        if surface is None:
            return
        cache = self.shell.assets.cache
        key = (SNAPSHOT_KEY, id(s), len(s.held))
        cache.hold(key)
        cache.put(key, surface, surface.get_width() * surface.get_height() * 4,
                  self.shell.assets.time.frame)
        s.held.append((key, surface))

    def _release(self, s: Session, surface: pygame.Surface | None) -> None:
        cache = self.shell.assets.cache
        for item in list(s.held):
            if surface is None or item[1] is surface:
                cache.release(item[0])
                cache.discard(item[0])
                s.held.remove(item)

    # -- phases --

    def _running(self, s: Session) -> None:
        """The fade-in ended (or there was none): RUNNING; the pictures of the dissolve go
        and the opening picture becomes its 320×180 thumbnail (I-8)."""
        s.phase = Phase.RUNNING
        s.t = 1.0
        scope = s.scope
        if scope.focused is None:                                     # F10's first focus
            target = scope.default()
            # F52 (07 §3.1): a text default is focused visibly whatever the input kind.
            if target is not None and (s.last_kind is InputKind.KEYS or target.takes_text):
                scope.focus(target, InputKind.KEYS, sound=False)
        if s.opening is not None:
            s.thumb = make_thumbnail(s.opening)
            self.smoothscales += 1
        self._release(s, s.from_pic)
        self._release(s, s.opening)
        s.from_pic = s.opening = None

    def snap(self, s: Session) -> None:
        """A fade ends at once (Esc, Start, F5, F9, Shift+F8, a resize)."""
        if s.phase is Phase.OPENING:
            self._running(s)
        elif s.phase is Phase.CLOSING:
            self.end_close(s)

    def advance(self, s: Session, dt: float) -> None:
        if s.phase in (Phase.OPENING, Phase.CLOSING):
            s.t += dt / s.fade_s if s.fade_s > 0 else 1.0
            if s.t >= 1.0 - 1e-9:
                self.snap(s)

    def thumbnail(self) -> pygame.Surface | None:
        """The shell's thumbnail source (04 §7.8): the opening picture's thumbnail while
        RUNNING or paused; None during fades and when closed (F11's normal capture)."""
        s = self.session
        if s is None or s.phase is not Phase.RUNNING:
            return None
        return s.thumb

    # -- the end --

    def finish_with(self, s: Session, result: object, changes: tuple) -> None:
        if s.finished:
            _log.debug("A minigame finished twice; the later result is ignored.")
            return
        s.finished = True
        s.result = result
        s.changes = changes

    def begin_close(self, s: Session) -> None:
        """04 §7.4 Finish: music released, plugin sounds out, CLOSING (or a cut)."""
        if s.phase in (Phase.CLOSING, Phase.CLOSED) or s.screen is None:
            return
        self._silence(s)
        cue = self.ports.cue
        if cue is not None:
            cue.set_anchor(None)
        self._release(s, s.from_pic)
        self._release(s, s.opening)
        s.from_pic = s.opening = None
        s.phase = Phase.CLOSING
        s.t = 0.0
        if self.reduce_motion() or s.look.fade_ms <= 0:     # every end dissolves (UI-F23-05)
            self.end_close(s)
        else:
            s.fade_s = s.look.fade_ms / 1000.0

    def end_close(self, s: Session) -> None:
        """At the end of CLOSING: the screen goes, then ``MinigameDone`` is posted."""
        if s.phase is Phase.CLOSED:
            return
        s.phase = Phase.CLOSED
        self._clear(s)
        cmd = s.cmd
        self.ports.post(MinigameDone(cmd.sid, cmd.run, s.result, s.changes))

    def abandon(self) -> None:
        """04 §7.4 Abandon: nothing is posted; the ledger is dropped."""
        s = self.session
        if s is None:
            return
        if s.phase is not Phase.CLOSED:
            s.phase = Phase.CLOSED
            self._silence(s)
        self._clear(s)

    def _silence(self, s: Session) -> None:
        music, s.music = s.music, None
        if music is not None:
            try:
                music.release()
            except Exception:
                _log.debug("The minigame's music couldn't be released", exc_info=True)
        audio = self.ports.audio
        if audio is not None:
            audio.stop_ui(STOP_UI_FADE_S, owner=UI_OWNER)

    def _clear(self, s: Session) -> None:
        if self.session is s:
            self.session = None
        if s.keyboard is not None:
            s.keyboard.close()
        if s.router is not None:
            s.router.repeat.stop()
        cue = self.ports.cue
        if cue is not None:
            cue.set_anchor(None)
        source = getattr(self.shell, "set_thumbnail_source", None)
        if source is not None:
            source(None)
        self._release(s, None)
        s.from_pic = s.opening = s.last = s.stage_pic = s.gradient = None
        screen = s.screen
        if screen is not None:
            self.ports.stack.remove(screen)

    # -- listeners --

    def on_say(self, cmd: object) -> None:
        """A ``Say`` while a session is open abandons it."""
        self.abandon()

    def on_landing(self) -> None:
        """F14's landing listener: a back step before any used input lands elsewhere."""
        s = self.session
        if s is not None and s.phase is not Phase.CLOSING:
            self.abandon()

    # -- F52 text --

    def text_services(self) -> TextServices:
        found = self.ports.text if self.ports.text is not None else getattr(
            self.shell, "text", None)
        return found if isinstance(found, TextServices) else TextServices()

    def keyboard(self, s: Session) -> OnScreenKeyboard:
        if s.keyboard is None:
            s.keyboard = OnScreenKeyboard(keyboard_services(self.shell, self.text_services()))
        return s.keyboard

    def router(self, s: Session) -> TextRouter:
        if s.router is None:
            s.router = TextRouter(read_clipboard=lambda: self.text_services().read_clipboard(),
                                  open_keyboard=lambda f: self.keyboard(s).open_for(f))
        return s.router

    # -- input bookkeeping --

    def note_used(self, s: Session) -> None:
        """The first used press-type input posts ``MinigameUsed`` once (04 §7.5)."""
        if not s.used:
            s.used = True
            self.ports.post(MinigameUsed(s.cmd.sid, s.cmd.run))

    def fixed_outcome(self, s: Session, kind: str) -> Outcome | None:
        """F24 A3: ``outcome_for(kind, …)`` on a fresh instance (inside the guard) first;
        None falls back to the declared ``test_outcome`` / ``skipped_outcome``."""
        sig = s.sig
        outcome: Outcome | None = None
        if sig.outcome is not None:
            outcome = self._call(sig.outcome, kind, thaw(s.cmd.args), s.cmd.names)
        if outcome is None:
            outcome = sig.test if kind == "test" else sig.skipped
        return outcome

    def _end_fixed(self, s: Session, outcome: Outcome) -> None:
        """Finish with a fixed outcome's own changes only: the session's ledger is dropped,
        so a change the plugin requested never lands (F25 G2)."""
        self.finish_with(s, outcome.result, tuple(outcome.changes))
        self.begin_close(s)

    def dev_end(self, s: Session) -> None:
        """Shift+F8 (dev): end with the test outcome, posting only its own changes; with
        none, the problem notice and nothing ends."""
        outcome = self.fixed_outcome(s, "test")
        if self.session is not s or s.finished:
            return
        notify = getattr(self.shell, "notify", None)
        if outcome is None:
            if notify is not None:
                notify(messages.dev_no_test_outcome(s.title), kind="problem")
            return
        if notify is not None:
            notify(messages.dev_ended(s.title))
        _log.info("Dev: minigame %s ended with its test outcome (Shift+F8)", s.sig.name)
        self._end_fixed(s, outcome)

    # -- Skip Game (UI-F23-12; 03 "Game menu during a minigame") --

    def can_skip(self) -> bool:
        """The game menu lists ``skip_minigame`` only over a running skippable minigame (not
        during its fades, never disabled)."""
        s = self.session
        return (s is not None and s.cmd.skippable and s.inserted and not s.finished
                and s.phase is Phase.RUNNING)

    def ask_skip(self, by: InputKind) -> None:
        """Skip Game: ``confirm_skip_minigame`` with No focused; No (Back, Esc) returns to the
        game menu with Skip Game focused (the confirm's opener)."""
        s = self.session
        if s is None or not self.can_skip():
            return
        shell = self.shell
        shell.confirm(shell.words.get("confirm_skip_minigame"), lambda: self.skip(s), by=by)

    def skip(self, s: Session) -> None:
        """Yes: the game menu closes as Return does, then the minigame dissolves out with
        its skipped outcome (no ``update`` in between: it is CLOSING at once, and its
        dissolve waits under the menu's fade). With no skipped outcome, the result None."""
        if self.session is not s or s.finished:
            return
        close = getattr(self.shell, "close_game_menu", None)
        if close is not None:
            close()
        try:
            outcome = self.fixed_outcome(s, "skipped")
        except PluginFailed:
            return
        if self.session is not s or s.finished:
            return
        _log.info("Minigame %s skipped from the game menu", s.sig.name)
        self._end_fixed(s, outcome if outcome is not None else Outcome(None))

    # -- W162 (dev): a slow plugin frame --

    def frame_cost(self, s: Session, seconds: float) -> None:
        """The plugin's ``update`` + ``draw`` of one frame took ``seconds``: over 8 ms, one
        W162 per minigame name per session (dev runs)."""
        ms = seconds * 1000.0
        name = s.sig.name
        if ms <= messages.W162_BUDGET_MS or not self.ports.dev or name in self._slow_warned:
            return
        self._slow_warned.add(name)
        self.ports.log.warning("%s", messages.w162_slow_frame(name, round(ms)),
                               extra={"code": "W162"})

    # -- plugin calls (04 §7.6) --

    def call(self, fn: Callable[..., Any], *args: Any,
             convert: Callable[[Any], Any] | None = None) -> Any:
        """A plugin call from the screen; then the frame settles, F10's first-focus rule
        applies when the call replaced the scope's groups and left nothing focused (F25/F26
        I-20: keys → the default widget, mouse → nothing), and a pending finish closes."""
        s = self.session
        groups = s.scope.groups if s is not None else None
        value = self._call(fn, *args, convert=convert)
        if s is not None and self.session is s:
            self.relayout(s)
            scope = s.scope
            if (s.phase is Phase.RUNNING and scope.groups is not groups
                    and scope.focused is None and s.last_kind is InputKind.KEYS):
                target = scope.default()
                if target is not None:
                    scope.focus(target, InputKind.KEYS, sound=False)
            if s.finished and s.inserted and s.phase in (Phase.OPENING, Phase.RUNNING):
                self.begin_close(s)
        return value

    def _call(self, fn: Callable[..., Any], *args: Any,
              convert: Callable[[Any], Any] | None = None) -> Any:
        if self._depth:
            value = fn(*args)
            return convert(value) if convert is not None else value
        s = self.session
        guard = self.ports.guard
        failure: StoryError | None = None
        caught: BaseException | None = None
        value = None
        self._depth += 1
        guard.enter()
        try:
            try:
                value = fn(*args)
                if convert is not None:
                    value = convert(value)
            except KeyboardInterrupt as e:
                caught = e
            except PluginFailed:
                raise
            except BaseException as e:              # noqa: BLE001 (SystemExit too: E275)
                try:
                    failure = self._failure(s, e)
                except KeyboardInterrupt as again:
                    caught = again
        finally:
            guard.exit()
            self._depth -= 1
        if caught is not None:
            if guard.consume_fired():
                failure = self._stuck(s, caught)
            else:                                   # the plugin raised it (AC-F23-44): E275
                failure = self._failure(s, caught)
        if failure is not None:
            self._fail(failure)
            raise PluginFailed
        return value

    def _text(self, fn: Callable[[], Any]) -> Any:
        """``fn()`` (plugin text: ``str(e)``, a traceback) inside the guard with a budget
        of its own; None when it raised or the watchdog stopped it (SEC-F23-08)."""
        guard = self.ports.guard
        guard.exit()
        guard.enter()
        try:
            return fn()
        except KeyboardInterrupt:
            if guard.consume_fired():
                return None
            raise
        except BaseException:                       # noqa: BLE001
            return None

    def _failure(self, s: Session | None, e: BaseException) -> StoryError:
        """The error for ``e`` from plugin code, built inside the guard."""
        game = s.sig.name if s is not None else "?"
        sig = s.sig if s is not None else None
        trace = self._text(lambda: "".join(traceback.format_exception(e)).rstrip("\n"))
        if type(trace) is not str:
            trace = "Traceback (most recent call last):\n" + "".join(
                traceback.format_tb(e.__traceback__)) + "(the error's text could not be read)"
        file, line = self._script_place(s)
        pfile, pline = plugin_line(e.__traceback__)
        if isinstance(e, RequestError):
            error = self._at_plugin(e.text, e.code, sig, pfile, pline, file, line)
        elif isinstance(e, (UnknownEntry, WrongKind)):
            error = self._at_plugin(codex_error_text(e), "E275", sig, pfile, pline, file, line)
        elif isinstance(e, _ResultRefused):
            error = StoryError(e.text, code="E276", file=file, line=line)
        else:
            text = self._text(lambda: plugin_failure(game, sig, e))
            if type(text) is not str:
                bare = Exception().with_traceback(e.__traceback__)
                text = plugin_failure(game, sig, bare)
            error = StoryError(text, code="E275", file=file, line=line)
        error.trace_text = trace                     # type: ignore[attr-defined]
        return error

    def _at_plugin(self, text: str, code: str, sig: Any, pfile: str | None,
                   pline: int | None, file: str | None, line: int | None) -> StoryError:
        """A request error at the plugin's line (P prefix); a bundled one at the script's."""
        if plugin_file(sig) is not None and pfile is not None:
            return StoryError(text, code=code, file=pfile, line=pline)
        return StoryError(text, code=code, file=file, line=line)

    def _script_place(self, s: Session | None) -> tuple[str | None, int | None]:
        if s is None:
            return None, None
        try:
            return self.ports.where(s.cmd.sid)
        except Exception:
            return None, None

    def _stuck(self, s: Session | None, e: BaseException) -> StoryError:
        sig = s.sig if s is not None else None
        pfile, pline = plugin_line(e.__traceback__)
        if plugin_file(sig) is None:
            pfile = pline = None
        elif pfile is None:
            pfile = plugin_file(sig)
        file, line = self._script_place(s)
        error = StoryError(e277_text(sig.name if sig is not None else "?",
                                     limits.AUTHOR_CODE_LIMIT_S, pfile, pline),
                           code="E277", file=file, line=line)
        trace = "".join(traceback.format_tb(e.__traceback__))
        error.trace_text = trace                                     # type: ignore[attr-defined]
        return error

    def _fail(self, error: StoryError) -> None:
        """Log the error with its traceback, abandon (I-11), then the error screen."""
        log = self.ports.log
        if log.isEnabledFor(logging.ERROR):
            record = log.makeRecord(log.name, logging.ERROR, __file__, 0, "%s",
                                    (error.format(),), None)
            record.exc_text = getattr(error, "trace_text", None) or None
            log.handle(record)
        error.logged = True
        self.abandon()
        self.ports.fatal(error)


def _minor(api: str) -> int:
    """The minor number of a checked ``"1.4"`` (0 when it can't be read)."""
    try:
        return int(api.split(".")[1])
    except (IndexError, ValueError):
        return 0


class _ResultRefused(Exception):
    """``ctx.finish`` got a result ``freeze`` refuses (E276, built inside the call)."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text


# --- The plugin's ContextPort ---------------------------------------------------------------------

def _exact_text(value: object, what: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{what} must be text, not {kind_words(value)}")
    return value


def _number(value: object) -> float:
    if type(value) not in (int, float) or value != value or value in (float("inf"),
                                                                       float("-inf")):
        raise TypeError("a point is two numbers, e.g. (300, 200)")
    return float(value)                             # type: ignore[arg-type]


class _SessionPort:
    """The host's side of one session's ``Context`` (the ``ContextPort``). Called only from
    plugin code, inside ``_call``, on the main thread (the Context checked it)."""

    def __init__(self, host: MinigameHost, session: Session) -> None:
        self._host = host
        self._s = session

    def settings(self) -> PlayerSettings:
        return self._host.player_settings()

    def area(self) -> Box:
        return self._s.area

    def image(self, name: object) -> Any:
        name = _exact_text(name, "an image name")
        resolve = self._host.ports.image
        if resolve is not None:
            return resolve(name)
        return self._host.shell.assets.image(name)

    def gui_image(self, ref: object) -> Any:
        """An image in the game folder, or None for a missing or unusable ref, with one W64
        per ref in dev runs (F24 ``07`` I-5, Q-c: the frame-image rule)."""
        return self._host.gui_image(self._s, _exact_text(ref, "an image file"))

    def font(self, ref: object, size: object) -> FontSpec:
        if type(size) is not int or not 1 <= size <= FONT_SIZE_MAX:
            raise TypeError(f"a font size is a whole number from 1 to {FONT_SIZE_MAX}")
        if ref is None:
            return self._host.shell.theme.font(size)
        ref = _exact_text(ref, "a font file")
        assets = self._host.shell.assets
        if assets.check(ref, "font") is not None:
            assets.font(ref, size)                  # the usual one log line, then the theme's
            return self._host.shell.theme.font(size)
        return FontSpec(ref, size)

    def play_sound(self, file: object, volume: object) -> None:
        file = _exact_text(file, "a sound file")
        if type(volume) is not int or not 0 <= volume <= 100:
            raise TypeError("a volume is a whole number from 0 to 100")
        audio = self._host.ports.audio
        if audio is not None:
            audio.play_ui(file, volume=volume, owner=UI_OWNER)

    def music(self) -> Any:
        s = self._s
        if s.music is None:
            audio = self._host.ports.audio
            s.music = audio.take_music(UI_OWNER) if audio is not None else _SilentMusic()
        return s.music

    def play_ui(self, token: object) -> None:
        token = _exact_text(token, "a sound token")
        s = self._s
        file = ThemePort(self._host.shell.theme.cfg, s.own.tokens if s.own is not None else {},
                         s.sig.name).get(token)
        if file is None:
            return
        audio = self._host.ports.audio
        if type(file) is str and audio is not None:
            audio.play_ui(file, owner=UI_OWNER)

    def heading(self, on: object, text: object) -> None:
        if type(on) is not bool:
            raise TypeError("heading(on) takes True or False")
        s = self._s
        s.heading_on = on
        if text is not None:
            s.heading_text = clean_text(_exact_text(text, "a heading"), HEADING_MAX)
        s.dirty = True

    def hint(self, text: object) -> None:
        s = self._s
        s.hint_text = "" if text is None else clean_text(_exact_text(text, "a hint"),
                                                         HINT_MAX)
        s.dirty = True

    def cue_point(self, at: object) -> None:
        s = self._s
        if at is None:
            s.cue_point = None
        else:
            if type(at) not in (tuple, list) or len(at) != 2:      # type: ignore[arg-type]
                raise TypeError("a point is two numbers, e.g. (300, 200)")
            s.cue_point = (_number(at[0]), _number(at[1]))         # type: ignore[index]
        s.dirty = True

    def confirm(self, word: object, on_yes: object, on_no: object) -> None:
        word = _exact_text(word, "a confirm's text")
        if not callable(on_yes) or (on_no is not None and not callable(on_no)):
            raise TypeError("confirm needs functions to call for Yes and No")
        host, s = self._host, self._s
        declared = s.own.words if s.own is not None else s.entry.words
        words = host.shell.words
        if word in declared:
            message = declared[word]
        elif word in words.keys():
            message = words.get(word)
        else:
            message = word
        message = clean_text(message, CONFIRM_MAX)

        def answer(fn: Callable[[], object]) -> Callable[[], None]:
            def run() -> None:
                if host.session is s:
                    try:
                        host.call(fn)
                    except PluginFailed:
                        pass
            return run

        confirm = getattr(host.shell, "confirm", None)
        if confirm is None:
            raise RuntimeError("no confirm dialog here")
        confirm(message, answer(on_yes), on_no=answer(on_no) if on_no is not None else None,
                by=s.last_kind)

    def codex_view(self, filter: object, pick: object) -> CodexView:
        if type(filter) is not CodexFilter:
            raise TypeError("codex_view needs filter=CodexFilter(...)")
        kinds = filter.kinds
        if not isinstance(kinds, (set, frozenset)) or not kinds \
                or not all(type(k) is str and k in KINDS for k in kinds):
            raise TypeError('a CodexFilter\'s kinds are "item" and/or "tip"')
        categories = filter.categories
        if categories is not None:
            if not isinstance(categories, (set, frozenset, tuple, list)) \
                    or len(categories) > CATEGORIES_MAX \
                    or not all(type(c) is str and len(c) <= CATEGORY_CHARS
                               for c in categories):
                raise TypeError(f"a CodexFilter has at most {CATEGORIES_MAX} categories, each "
                                f"text of at most {CATEGORY_CHARS} characters")
            categories = frozenset(categories)
        copy = CodexFilter(frozenset(kinds), categories)
        action = None
        if pick is not None:
            if type(pick) is not PickAction or not callable(pick.on_pick):
                raise TypeError("codex_view's pick must be a PickAction or None")
            action = PickAction(clean_text(_exact_text(pick.word, "a pick word"), HEADING_MAX),
                                pick.on_pick)
        s = self._s
        port = s.ctx.codex if s.ctx is not None else None
        target = port._port if port is not None else None             # the LedgerCodexPort
        return CodexView(target, ui=self._host.shell, filter=copy, pick=action,
                         scope=lambda: s.scope)

    def finish(self, result: object) -> None:
        s = self._s
        if s.finished:
            _log.debug("ctx.finish was called again; the later result is ignored.")
            return
        try:
            frozen = freeze(result)
        except Unsaveable as e:
            raise _ResultRefused(e276_result(s.sig.name, e, None, plugin_file(s.sig))) \
                from None
        except RecursionError:
            raise _ResultRefused(e276_result(s.sig.name, Unsaveable("too_deep", None),
                                             None, plugin_file(s.sig))) from None
        self._host.finish_with(s, frozen, s.ledger.changes)


__all__ = ["HostPorts", "LedgerCodexPort", "LedgerPoints", "MinigameHost", "MinigameLook",
           "Phase", "PluginFailed", "Session", "ThemePort", "UI_OWNER", "WordsPort",
           "minigame_look"]

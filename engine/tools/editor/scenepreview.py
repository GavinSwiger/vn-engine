"""A small picture of a scene's opening shot, above the Story map's side pane (2026-11-04).

Why this module exists: a box on the map says a scene's name, not what it looks like. When
the author clicks one, the side pane shows the stage as the player first sees it: the
background and the characters standing where the scene's lines put them before its first
line of text (or menu). It is drawn from the project's pictures in Studio, with no game
running, so it is a sketch, not the game's own frame:

- ``opening_stage(lines, lead)`` (pure): the scene's ``scene`` and ``show`` lines up to its
  first text, via ``stageat.stage_at``; each sprite's picture name, position and zoom.
- ``lead_in(name, links, scene_lines)`` (pure): a scene with no ``scene`` line keeps the
  stage of the scene that leads to it, so the first arrow in (a jump or a choice before a
  call) is followed back to its line, scene by scene, until one sets a background.
- ``ScenePreview``: a 16:9 canvas and a caption. The background covers the canvas (a
  colour picture is its colour); each character stands on its position (``left``,
  ``center``, ``right`` or ``[stage.positions]``), scaled as ``[stage] art_height`` says.
  The caption names the pictures, and the scene a carried-on background comes from.
- Studio UX 2.5: ``show(stage, line=N)`` is the stage at line N (``stagemoment``) under
  the heading ``AT LINE N``, with the text box (the line, the name in its colour) drawn in
  Tk at once and a small "sketch" badge. After ``REST_MS`` at rest the window's stage
  stills cache (``stagestills``) gives the game's own still, which replaces the sketch: a
  short settle under motion, a cut under Reduce motion. A failed still keeps the sketch.

PNG and GIF pictures load here; JPEG and WebP come from the helper child as thumbnails
(``helperhub``), and the picture is drawn again when one arrives. Imports the standard
library, ``tkinter`` and its own package; never pygame.
"""

from __future__ import annotations

import base64
import re
import tkinter as tk
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from tkinter import ttk
from typing import Any, Final

from engine.core.constants import BUILTIN_POSITIONS, CANVAS_SIZE
from engine.tools.editor import stageat
from engine.tools.editor.theme import THEME

STAGE_W, STAGE_H = CANVAS_SIZE
PREVIEW_W_PX: Final = 224                   # at 100 %; 16:9
PREVIEW_H_PX: Final = round(PREVIEW_W_PX * 9 / 16)
HEADING: Final = "OPENING SHOT"
CARRIED: Final = "Carries on from the scene before."
CARRIED_FROM: Final = "Background from {scene}."
LEAD_DEPTH: Final = 8                       # scenes followed back for a carried background
NO_STAGE: Final = "Nothing on stage yet: add a Background."
AT_LINE: Final = "AT LINE {line}"           # 2.5: the stage at the cursor's line
SKETCH: Final = "sketch"                    # the badge while Studio's own drawing shows
REST_MS: Final = 300                        # at rest this long: ask for the game's still
SETTLE_MS: Final = 160                      # the still settles in (none under Reduce motion)
STILL_OWNER: Final = "preview"              # this preview's asks in ``stagestills``
MISSING: Final = "No picture named {name}."
# A line the player reads or chooses at: the opening shot is the stage before it.
_TEXT = re.compile(r'^(?:[A-Za-z_]\w*\s+){0,3}"|^menu\b|^nvl\b')
# Words that end a picture's name on a ``scene``/``show`` line.
_STOP: Final = frozenset(("at", "behind", "onlayer", "zorder", "as", "with", "layer",
                          "zoom", "flip"))


@dataclass(frozen=True, slots=True)
class Sprite:
    image: str                  # the picture name, e.g. "hana happy"
    at: str | None = None       # a position name, or None (centre)
    x: float | None = None      # ``at <x>`` in canvas units
    zoom: float = 1.0


@dataclass(frozen=True, slots=True)
class Stage:
    background: str | None      # the picture name, or None (black, or carried on)
    carried: bool               # no ``scene`` line found: the stage before is unknown
    sprites: tuple[Sprite, ...] = ()
    came_from: str | None = None    # the scene a carried-on background was set in
    say: Any = None                 # 2.5: the text box's ``stagemoment.Say``, or None
    note: str | None = None         # 2.5: what the stage assumed (``BRANCH_NOTE``)


def opening_stage(lines: Iterable[str], lead: Sequence[str] = (),
                  came_from: str | None = None) -> Stage:
    """The stage before the first line of text in a scene's ``lines`` (its label line
    first, which is skipped), after ``lead`` (``lead_in``'s lines, set in ``came_from``)."""
    taken: list[str] = list(lead)
    own = len(taken)
    for line in list(lines)[1:]:
        code = line.split("#", 1)[0].strip()
        if _TEXT.match(code):
            break
        taken.append(line)
    stage = stageat.stage_at(taken)
    if any(code.split()[:1] == ["scene"] for code in stageat.stage_at(taken[own:])):
        came_from = None                    # the scene sets its own background
    background, carried = None, True
    sprites: dict[str, Sprite] = {}             # by tag: a later ``show`` replaces it
    for code in stage:
        words = code.split()
        if words[0] == "scene":
            carried = False
            name = _name(words[1:])
            background = name or None
        elif words[0] == "show":
            name = _name(words[1:])
            if name:
                tag = stageat._show_tag(words) or name
                sprites.pop(tag, None)
                sprites[tag] = _sprite(name, words)
    return Stage(background, carried, tuple(sprites.values()),
                 came_from if not carried else None)


def lead_in(name: str, links: Iterable[Any],
            scene_lines: Any) -> tuple[list[str], str | None]:
    """The lines that set the stage before scene ``name`` starts, oldest first, and the
    scene whose ``scene`` line they reach back to (None: none found). ``links`` are the
    story map's arrows (``src``, ``dst``, ``kind``, ``line``); ``scene_lines(name)`` gives a
    scene's lines and its label's line number, or None."""
    ins: dict[str, list[Any]] = {}
    for link in links:
        ins.setdefault(link.dst, []).append(link)
    out: list[list[str]] = []
    seen = {name}
    here = name
    for _ in range(LEAD_DEPTH):
        ways = sorted(ins.get(here, ()), key=lambda link: link.kind == "call")
        way = next((link for link in ways if link.src not in seen), None)
        if way is None:
            return [], None
        found = scene_lines(way.src)
        if found is None:
            return [], None
        lines, start = found
        part = lines[1:max(1, way.line - start)]       # up to the line that leads here
        out.insert(0, part)
        if any(code.split()[:1] == ["scene"] for code in stageat.stage_at(part)):
            return [line for chunk in out for line in chunk], way.src
        seen.add(way.src)
        here = way.src
    return [], None


def _name(words: Sequence[str]) -> str:
    out = []
    for word in words:
        if word in _STOP:
            break
        out.append(word)
    return " ".join(out)


def _sprite(name: str, words: Sequence[str]) -> Sprite:
    at, x, zoom = None, None, 1.0
    for index, word in enumerate(words[:-1]):
        following = words[index + 1].strip("(),")
        if word == "at":
            try:
                x = float(following)
            except ValueError:
                at = following
        elif word == "zoom":
            try:
                zoom = float(following)
            except ValueError:
                pass
    return Sprite(name, at, x, zoom)


def stage_settings(config_text: str) -> tuple[dict[str, tuple[float, float]], int]:
    """The positions (built-ins, then ``[stage.positions]``) and ``[stage] art_height``."""
    positions = dict(BUILTIN_POSITIONS)
    art_height = STAGE_H
    try:
        stage = tomllib.loads(config_text).get("stage", {})
    except (tomllib.TOMLDecodeError, RecursionError):
        return positions, art_height
    if isinstance(stage, dict):
        if isinstance(stage.get("art_height"), int) and stage["art_height"] > 0:
            art_height = stage["art_height"]
        table = stage.get("positions", {})
        for name, value in (table.items() if isinstance(table, dict) else ()):
            if isinstance(value, (int, float)):
                positions[name] = (float(value), float(STAGE_H))
            elif isinstance(value, list) and len(value) == 2 \
                    and all(isinstance(v, (int, float)) for v in value):
                positions[name] = (float(value[0]), float(value[1]))
    return positions, art_height


class ScenePreview:
    """The opening shot on ``parent`` for Studio window ``win`` (module docstring):
    ``frame`` holds the canvas and, beside it, the heading and the caption."""

    def __init__(self, parent: tk.Misc, win: Any, *, scale: float = 1.0,
                 font: Any = None) -> None:
        self.win = win
        self.w, self.h = round(PREVIEW_W_PX * scale), round(PREVIEW_H_PX * scale)
        self.frame = ttk.Frame(parent)
        self.canvas = tk.Canvas(self.frame, width=self.w, height=self.h, highlightthickness=1,
                                highlightbackground=THEME["widget.border"],
                                background=THEME["editor.background"], borderwidth=0)
        self.canvas.grid(row=0, column=0, rowspan=2, sticky="nw")
        gap = round(10 * scale)
        self.heading = ttk.Label(self.frame, text=HEADING, style="Header.TLabel")
        self.heading.grid(row=0, column=1, sticky="nw", padx=(gap, 0))
        self.caption = ttk.Label(self.frame, text="", justify="left",
                                 foreground=THEME["muted"], wraplength=round(160 * scale))
        if font is not None:
            self.caption.configure(font=font)
        self.caption.grid(row=1, column=1, sticky="nw", padx=(gap, 0))
        self.frame.columnconfigure(1, weight=1)
        self.frame.bind("<Configure>", lambda e: self.caption.configure(
            wraplength=max(60, e.width - self.w - gap * 2)), add="+")
        self.stage: Stage | None = None
        self.images: list[tk.PhotoImage] = []        # kept while drawn
        self._cache: dict[tuple[str, object, int], tk.PhotoImage | None] = {}
        self._loaders: dict[int, Any] = {}
        # 2.5: the line shown (None: the opening shot), the "sketch" badge, the game's
        # still once it replaced the sketch, and the rest timer that asks for it.
        self.line: int | None = None
        try:
            self._family = font.actual("family") if font is not None else "TkDefaultFont"
        except (AttributeError, tk.TclError):
            self._family = "TkDefaultFont"
        self.badge = tk.Label(self.canvas, text=SKETCH, background=THEME["editor.background"],
                              foreground=THEME["muted"],
                              font=(self._family, -max(9, round(10 * scale))),
                              borderwidth=0, padx=round(3 * scale), pady=0)
        self.still: tk.PhotoImage | None = None
        self.still_key: Any = None
        self._want: Any = None
        self._rest_id: str | None = None

    def show(self, stage: Stage | None, line: int | None = None) -> None:
        """Draw ``stage`` (None: nothing shown); ``line``: it is the stage at that line
        (2.5), else the opening shot. The game's still is asked for at rest."""
        self.stage, self.line = stage, line
        self.still = self.still_key = self._want = None
        self.redraw()
        self._cancel_rest()
        if stage is not None:
            try:
                # On the root, as Studio's other timers (a bench cancels them all there).
                self._rest_id = self.canvas._root().after(REST_MS, self._at_rest)
            except tk.TclError:
                pass

    def redraw(self) -> None:
        canvas, stage = self.canvas, self.stage
        canvas.delete("all")
        self.images = []
        self.heading.configure(text=HEADING if self.line is None
                               else AT_LINE.format(line=self.line))
        if stage is None:
            self.caption.configure(text="")
            self.badge.place_forget()
            return
        if self.still is not None:
            canvas.create_image(0, 0, image=self.still, anchor="nw")
            self.badge.place_forget()
        else:
            self.badge.place(x=2, y=2)
        assets = self._assets()
        notes: list[str] = []
        canvas.configure(background="#000000")
        if self.still is not None:
            pass
        elif stage.background is not None:
            color = assets.colors.get(_fold(stage.background)) if assets else None
            if color is not None:
                canvas.create_rectangle(0, 0, self.w + 2, self.h + 2, fill=color, width=0)
            elif not self._picture(stage.background, cover=True):
                notes.append(MISSING.format(name=stage.background))
        positions, art_height = stage_settings(self._config_text())
        for sprite in (stage.sprites if self.still is None else ()):
            x, y = positions.get(sprite.at or "center", positions["center"])
            if sprite.x is not None:
                x = sprite.x
            if not self._picture(sprite.image, at=(x * self.w / STAGE_W, y * self.h / STAGE_H),
                                 height=self.h / art_height * sprite.zoom):
                notes.append(MISSING.format(name=sprite.image))
        shown = [stage.background] if stage.background else []
        shown += [s.image + (f" ({s.at})" if s.at else "") for s in stage.sprites]
        lines = list(shown)
        if stage.came_from is not None:
            lines.append(CARRIED_FROM.format(scene=stage.came_from))
        elif stage.carried:
            lines.append(CARRIED)
        elif not shown:
            lines.append(NO_STAGE)
        if self.still is None and stage.say is not None:
            self._draw_say(stage.say, assets)
        if stage.note:
            lines.append(stage.note)
        self.caption.configure(text="\n".join(lines + notes))

    # -- 2.5: the text box, and the game's still at rest ------------------------------------

    def _draw_say(self, say: Any, assets: Any) -> None:
        """The text box as a sketch: a dark box over the lower part, the name in its
        colour above the line (narration: no name), the words cut to fit."""
        w, h, canvas = self.w, self.h, self.canvas
        pad = max(2, round(w * 0.02))
        top = round(h * 0.70)
        canvas.create_rectangle(pad, top, w - pad, h - pad, fill="#14141c",
                                outline=say.color or "#3c3c48", width=1)
        size = max(7, round(h * 0.065))
        y = top + pad
        if say.who:
            canvas.create_text(pad * 2, y, text=say.who, anchor="nw",
                               fill=say.color or "#e8e8f0",
                               font=(self._family, -size, "bold"))
            y += size + 2
        words = " ".join(getattr(say, "plain", say.text).split())
        room = max(8, round((w - pad * 4) / (size * 0.5)) * max(1, (h - pad - y) // (size + 2)))
        if len(words) > room:
            words = words[:room - 1].rstrip() + "…"
        canvas.create_text(pad * 2, y, text=words, anchor="nw", fill="#e8e8f0",
                           width=w - pad * 4, font=(self._family, -size))

    def _cancel_rest(self) -> None:
        if self._rest_id is not None:
            try:
                self.canvas._root().after_cancel(self._rest_id)
            except tk.TclError:
                pass
            self._rest_id = None

    def _at_rest(self) -> None:
        """At rest: the game's still from the cache, or asked for (only while shown)."""
        self._rest_id = None
        stage = self.stage
        try:
            if stage is None or not self.canvas.winfo_viewable():
                return
        except tk.TclError:                     # the window closed
            return
        try:
            from engine.tools.editor import stagestills as ss
            config = ss.config_of(self.win)
            key = ss.StillKey(ss.spec_of(stage, self._assets(), self.win.paths.root),
                              self.w, ss.look_of(config))
            stills = ss.stills_for(self.win)
        except Exception:  # noqa: BLE001  (no helper: the sketch stays)
            return
        self._want = key
        if stills.get(key) is not None:
            self._still_ready(key, stills.get(key))
            return
        stills.ask(STILL_OWNER, [key], config, self._still_ready)

    def _still_ready(self, key: Any, still: Any) -> None:
        if key != self._want or self.stage is None or not still.ok:
            return                              # moved on, or failed: the sketch stays
        from engine.tools.editor.stagestills import stills_for
        image = stills_for(self.win).photo(key, self.canvas)
        if image is None:
            return
        self.still, self.still_key = image, key
        self.redraw()
        self._settle()

    def _settle(self) -> None:
        """The still settles in from a veil (``SETTLE_MS``); a cut under Reduce motion."""
        motion = getattr(self.win, "motion", None)
        if motion is None:
            return
        veil = self.canvas.create_rectangle(0, 0, self.w + 2, self.h + 2, width=0,
                                            fill=THEME["editor.background"], stipple="gray50")

        def step(p: float) -> None:
            try:
                if p >= 1.0:
                    self.canvas.delete(veil)
                else:
                    self.canvas.itemconfigure(veil, stipple="gray50" if p < 0.5 else "gray25")
            except tk.TclError:
                pass

        motion.tween(("scene-preview-still", id(self)), SETTLE_MS, step)

    # -- pictures ----------------------------------------------------------------------------

    def _picture(self, name: str, *, cover: bool = False, at: tuple[float, float] = (0, 0),
                 height: float = 1.0) -> bool:
        """Draw picture ``name``: a background covering the canvas, else a sprite with its
        bottom centre at ``at``, ``height`` preview px per art px. False: no such file."""
        ref = self._ref_of(name)
        if ref is None:
            return False
        image = self._load(ref, cover=cover, factor=height)
        if image is None:
            return True                     # loading (a helper thumbnail) or can't show
        self.images.append(image)
        if cover:
            self.canvas.create_image(self.w // 2, self.h // 2, image=image, anchor="center")
        else:
            self.canvas.create_image(round(at[0]), round(at[1]), image=image, anchor="s")
        return True

    def _ref_of(self, name: str) -> str | None:
        assets = self._assets()
        if assets is None:
            return None
        folded = _fold(name)
        ref = assets.image_refs.get(folded)
        if ref is None:                     # ``show hana``: a picture of that character
            tag = folded.split(" ", 1)[0]
            found = sorted(r for n, r in assets.image_refs.items()
                           if n == tag or n.startswith(tag + " "))
            ref = found[0] if found else None
        return ref

    def _load(self, ref: str, *, cover: bool, factor: float) -> tk.PhotoImage | None:
        from engine.tools.editor.helperhub import file_stamp
        from engine.tools.editor.views import read_asset
        stamp = file_stamp(self.win.paths.root, ref)
        if not ref.lower().endswith((".png", ".gif")):
            size = self.w if cover else max(8, round(self.h * 1.2))
            return self._helper(ref, size)
        info = read_asset(self.win.paths, ref)
        if info.data is None or not info.width or not info.height:
            return None
        if cover:                           # the smallest step that still covers
            step = max(1, min(info.width // self.w, info.height // self.h))
        else:
            step = max(1, round(1 / factor)) if factor > 0 else 1
        key = (ref, stamp, step)
        if key not in self._cache:
            try:
                full = tk.PhotoImage(master=self.canvas,
                                     data=base64.b64encode(info.data).decode("ascii"))
                self._cache[key] = full if step == 1 else full.subsample(step)
            except tk.TclError:
                self._cache[key] = None
        return self._cache[key]

    def _helper(self, ref: str, size: int) -> tk.PhotoImage | None:
        from engine.tools.editor.helperhub import ThumbLoader
        loader = self._loaders.get(size)
        if loader is None:
            loader = self._loaders[size] = ThumbLoader(self.win, self.canvas, size,
                                                       lambda _ref: self.redraw())
        try:
            return loader.get(ref)
        except Exception:  # noqa: BLE001  (no helper: the sketch goes without it)
            return None

    def _assets(self) -> Any:
        story = getattr(self.win, "story", None)
        assets = getattr(story, "_form_assets", None)
        if assets is None and story is not None:
            try:
                assets = story.form_assets()
            except Exception:  # noqa: BLE001  (a preview never stops the map)
                return None
        return assets

    def _config_text(self) -> str:
        assets = self._assets()
        try:
            return assets._config_text() if assets is not None else ""
        except Exception:  # noqa: BLE001
            return ""


def _fold(name: str) -> str:
    return " ".join(name.split()).casefold()


__all__ = ["AT_LINE", "CARRIED", "CARRIED_FROM", "HEADING", "REST_MS", "SKETCH", "lead_in",
           "NO_STAGE", "ScenePreview", "Sprite", "Stage", "opening_stage", "stage_settings"]

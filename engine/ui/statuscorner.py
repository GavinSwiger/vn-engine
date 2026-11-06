"""``StatusCorner``: small always-on readouts in the stage's four corners (F61).

Why this module exists: meters first (F62), then a clock, a goal and a hotbar in later
phases, all need a small readout that stays on screen while the story is read, never covers
the text, and follows the game's colors. One shell-owned layer keeps their place, look,
spacing and visibility identical, so each system only says *what* to show and *where*.
Shared place names come from ``engine.core.skins`` (``CORNER_PLACES``).

It owns no game state: whoever adds items (F62 round 2) decides what is shown and saves it.
``GameShell`` builds one (``shell.corner``), updates it in ``update_layer`` and draws it in
``draw_layer`` after the scene captures (so it is never in a save thumbnail, scene picture,
or menu backdrop) and before the cue layer and the notices.

**API.** ``set_item(key, place, item)`` adds an item at the end of ``place``'s stack, or
replaces the item under ``key`` in its slot (a new place moves it to the end of that stack);
``remove_item(key)`` fades it out, then the stack closes up; ``clear()`` drops every item at
once. Keys are any hashable; places are ``CORNER_PLACES``. The shell never clears it: a load
restores before the in-game reset runs, so the owner clears and refills its own items.

**Item protocol** (``CornerItem``): a small object that measures and draws itself.

- ``measure(ctx) -> (w, h)``: its content size in canvas units, without the panel's padding,
  at ``ctx.size`` (the corner text size after the player's text scale). Keep ``w`` within
  ``ctx.max_width``.
- ``draw(canvas, box, ctx)``: draw the content inside ``box`` (canvas units, padding already
  taken off) at ``ctx.opacity``, with ``ctx.text`` and ``ctx.fill`` (both apply the opacity)
  and the colors in ``ctx.style``. ``ctx.place`` says which corner it is in (a right corner
  may right-align).
- Optional ``revision`` (int): bump it when the content changes size; the layout is cached
  on it, so an item without it is measured again only when the style or text size changes.

**Layout** (``corner_layout``, pure). Each item is a panel (``corner.fill_*``, border,
corners) of content + ``side_padding``/``top_padding`` on each side, its outer edge
``margin`` in from the canvas edge. Items stack inward from their corner in insertion order,
``gap`` apart: top corners downward, bottom corners upward. A panel never overlaps a
reserved area (``reserved_areas``: the say window with its name tab in ADV, the NVL text
column, the quick-menu pill, and F15/F14's indicator row at the top left): it jumps past it
(below it in a top corner, above it in a bottom corner). A top stack ends by the canvas's
middle; a bottom stack ends below its own side's top stack. An item that doesn't fit is not
drawn, nor are the ones after it in that corner (``overflow``).

**Visibility** (decided by the shell, ``GameShell.corner_shown``): only in game, with an
in-game screen on top (hidden under the game menu, its pages, confirms, fades, the title,
F30's fake crash), while the say window is drawn (hidden in hidden mode, with ``window
hide``, and between scenes with no box: the same rule as the quick menu), and not under an
opaque in-game screen (a running minigame). Shown in ADV and NVL. Showing and hiding the
whole layer is a cut, as the say window's hide is.

**Motion.** An added item fades in and a removed one fades out over ``corner.fade_ms``
(linear); under reduced motion both are cuts. Restacking is a cut. ``set_item`` and
``remove_item`` take ``fade=False`` for a cut (an owner refilling after a load). F62:
``pulse(key)`` sends one ring out from the item's panel in the accent color (a meter's rank
changed): over ``PULSE_S`` it grows from ``PULSE_RING`` to ``PULSE_RING + PULSE_GROW``
outside the panel (eased out) while it fades from full to nothing, on the same clock as the
fades (``update``), so it is frame-rate independent and a test can step it; none under
reduced motion.

**Sources** (F62): ``add_source(fn)``: ``fn()`` runs at the start of every ``update``, so an
owner can bring its items in line with the game state each frame (``app/meters.py``).

Colors follow the text box (``CORNER_FOLLOWS``) when unset, so every F49 scheme, imported
palette, and ``[theme.scheme]`` styles it; W67 checks ``corner.text_color`` and
``corner.accent_color`` on the fill (``app/ui_contrast.PAIRS``).
"""

from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Protocol

from engine.core.constants import CANVAS_SIZE
from engine.core.skins import CORNER_PLACES
from engine.render.frames import FrameSpec
from engine.render.text import FontSpec
from engine.ui.focus import Box
from engine.ui.layouts import Measure, pitch, scaled

if TYPE_CHECKING:
    from engine.core.config_schema import ThemeConfig
    from engine.render.canvas import Canvas
    from engine.ui.paint import Painter
    from engine.ui.theme import UiTheme

RGB = tuple[int, int, int]

CANVAS_W, CANVAS_H = CANVAS_SIZE
MIDDLE_Y: Final = CANVAS_H / 2            # a top stack ends by here
# ui-system §1: F15's skip/auto pill and F14's rewind tag sit topleft (24, 24), as tall as
# the quick-menu pill (``skip_auto.INDICATOR_TOPLEFT``, ``INDICATOR_EXTRA_H``); the row is
# reserved whether or not they show, so top-left items never jump when skipping starts.
INDICATOR_TOPLEFT: Final = (24, 24)
INDICATOR_ROW_W: Final = 320
INDICATOR_ROW_H: Final = 32               # used when there is no quick menu to measure
PULSE_S: Final = 0.4                      # F62: one rank-change pulse, in seconds
PULSE_RING: Final = 3                     # its ring's width and first gap, canvas units
PULSE_GROW: Final = 10                    # how much farther out the ring ends

# ``[theme.corner]`` tokens that follow another token when unset (W67 resolves them too).
CORNER_FOLLOWS: Final[Mapping[str, str]] = {
    "corner.fill_color": "textbox.fill_color",
    "corner.border_color": "textbox.border_color",
    "corner.text_color": "textbox.text_color",
    "corner.accent_color": "textbox.indicator.fill_color",
}
_EPSILON: Final = 1e-9


def corner_token(cfg: "ThemeConfig", path: str) -> object:
    """A ``corner.*`` token (or any theme token path) with ``CORNER_FOLLOWS`` resolved."""
    node: object = cfg
    for part in path.split("."):
        node = getattr(node, part)
    follows = CORNER_FOLLOWS.get(path)
    if node is None and follows is not None:
        return corner_token(cfg, follows)
    return node


# --- Style ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class CornerStyle:
    """``[theme.corner]`` resolved. ``font.size`` is the size at 100% text."""

    frame: FrameSpec = FrameSpec((0xFF, 0xF4, 0xF8), 0.90, (0xF0, 0xA0, 0xC0), 2, 12)
    font: FontSpec = FontSpec(None, 24)
    text_color: RGB = (0x3D, 0x2B, 0x36)
    accent_color: RGB = (0xA0, 0x28, 0x60)
    side_padding: int = 12
    top_padding: int = 8
    gap: int = 8
    margin: int = 24
    fade_ms: int = 150


def corner_style(theme: "UiTheme") -> CornerStyle:
    """The corner look of ``theme``: unset colors follow the text box."""
    cfg = theme.cfg
    c = cfg.corner

    def token(key: str):
        return corner_token(cfg, f"corner.{key}")

    frame = FrameSpec(token("fill_color"), c.fill_opacity, token("border_color"),
                      c.border_width, c.corner_radius)
    return CornerStyle(frame=frame, font=theme.font(c.text_size),
                       text_color=token("text_color"), accent_color=token("accent_color"),
                       side_padding=c.side_padding, top_padding=c.top_padding, gap=c.gap,
                       margin=c.margin, fade_ms=c.fade_ms)


# --- Items ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class CornerContext:
    """What an item measures and draws with (module docstring, "Item protocol")."""

    style: CornerStyle
    size: int                   # the corner text size after the player's text scale
    measure: Measure            # (text, size) -> width in canvas units, in ``style.font``
    place: str
    max_width: float            # the widest content that fits the corner
    opacity: float = 1.0

    @property
    def pitch(self) -> int:
        """One text line's height at ``size``."""
        return pitch(self.size)

    @property
    def font(self) -> FontSpec:
        return replace(self.style.font, size=self.size)

    def text(self, canvas: "Canvas", text: str, pos: tuple[float, float],
             color: RGB | None = None) -> None:
        """One line of ``text``, top-left at ``pos``, in ``color`` (default the corner text
        color) at this item's opacity."""
        draw_line(canvas, text, self.font, self.style.text_color if color is None else color,
                  pos, self.opacity)

    def fill(self, canvas: "Canvas", box: Box, color: RGB | None = None) -> None:
        """A plain rectangle in ``color`` (default the accent color) at this opacity."""
        if self.opacity <= 0.0:
            return
        rgb = self.style.accent_color if color is None else color
        alpha = round(255 * min(1.0, self.opacity))
        canvas.fill((*rgb, alpha) if alpha < 255 else tuple(rgb), (box.x, box.y, box.w, box.h))


class CornerItem(Protocol):
    """A readout in the status corner (module docstring, "Item protocol")."""

    def measure(self, ctx: CornerContext) -> tuple[float, float]: ...

    def draw(self, canvas: "Canvas", box: Box, ctx: CornerContext) -> None: ...


# --- Layout (pure) -------------------------------------------------------------------------

def _overlaps(a: Box, b: Box) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


def max_content_width(style: CornerStyle) -> float:
    """The widest content one item may have: a panel stays in its half of the canvas."""
    return CANVAS_W / 2 - style.margin - style.gap / 2 - 2 * style.side_padding


def corner_layout(stacks: Mapping[str, Sequence[tuple[Hashable, tuple[float, float]]]],
                  style: CornerStyle, reserved: Iterable[Box] = ()
                  ) -> dict[Hashable, Box | None]:
    """Each item's panel box (None: it doesn't fit). ``stacks`` maps a place to its items in
    order as ``(key, content size)``. Rules in the module docstring, "Layout"."""
    areas = tuple(reserved)
    pad_x, pad_y, gap, margin = style.side_padding, style.top_padding, style.gap, style.margin
    out: dict[Hashable, Box | None] = {}
    top_end = {"left": float(margin), "right": float(margin)}
    for place in ("top_left", "top_right", "bottom_left", "bottom_right"):
        side = "left" if place.endswith("left") else "right"
        top = place.startswith("top")
        y = float(margin) if top else float(CANVAS_H - margin)
        full = False
        for key, (cw, ch) in stacks.get(place, ()):
            w, h = cw + 2 * pad_x, ch + 2 * pad_y
            x = float(margin) if side == "left" else CANVAS_W - margin - w
            box = None if full else _place(x, y, w, h, top, areas, gap)
            if box is not None and (box.bottom > MIDDLE_Y if top
                                    else box.y < top_end[side]):
                box = None
            if box is None:
                full = True
            elif top:
                y = box.bottom + gap
                top_end[side] = y
            else:
                y = box.y - gap
            out[key] = box
    return out


def _place(x: float, y: float, w: float, h: float, top: bool, areas: Sequence[Box],
           gap: float) -> Box | None:
    """The panel at ``y`` (its top in a top corner, its bottom in a bottom one), moved past
    every reserved area it would overlap."""
    for _ in range(len(areas) + 1):
        box = Box(x, y, w, h) if top else Box(x, y - h, w, h)
        hit = next((a for a in areas if _overlaps(box, a)), None)
        if hit is None:
            return box
        y = hit.bottom + gap if top else hit.y - gap
    return None


def reserved_areas(textbox: object, quick_menu: object | None) -> list[Box]:
    """What the corner must never cover, in canvas units: the say window with its name tab
    (ADV) or the NVL text column, the quick-menu pill, and F15/F14's indicator row. Read
    duck-typed from F05's ``TextboxScreen`` and F10's ``QuickMenu``."""
    out: list[Box] = []
    row_h: float = INDICATOR_ROW_H
    found = quick_menu.shown() if quick_menu is not None else None    # type: ignore[attr-defined]
    if found is not None:
        pill = found.layout.pill
        out.append(Box(pill.x, pill.y, pill.w, pill.h))
        row_h = pill.h
    out.append(Box(*INDICATOR_TOPLEFT, INDICATOR_ROW_W, row_h))
    nvl = getattr(textbox, "nvl", None)
    if nvl is not None and getattr(nvl, "on", False):
        m = nvl.metrics
        out.append(Box(m.left, m.top, m.width, m.height))
    else:
        geometry = getattr(textbox, "geometry", None)
        if geometry is not None:
            x, y, w, h = geometry.box
            tab_top = getattr(textbox, "tab_top", None)
            top = min(y, tab_top()) if tab_top is not None else y
            out.append(Box(x, top, w, y + h - top))
    return out


# --- The layer -----------------------------------------------------------------------------

class _Entry:
    __slots__ = ("key", "place", "item", "phase", "t", "pulse")

    def __init__(self, key: Hashable, place: str, item: CornerItem) -> None:
        self.key = key
        self.place = place
        self.item = item
        self.phase = "in"           # "in", "shown", "out"
        self.t = 0.0                # seconds into "in" or "out"
        self.pulse = 0.0            # F62: seconds of pulse left


@dataclass(frozen=True)
class CornerView:
    """An item as drawn now (tests, F62)."""

    key: Hashable
    place: str
    box: Box | None             # None: it doesn't fit
    opacity: float
    pulse: float = 0.0          # F62: the ring's strength now, 1 (just pulsed) to 0
    spread: float = 0.0         # F62: the ring's gap outside the panel now, canvas units


class StatusCorner:
    """The four corner stacks (module docstring). ``style`` is a ``CornerStyle`` or a
    function giving the current one; ``measure`` gives a ``Measure`` for a font;
    ``text_scale`` F16's text scale; ``reduce_motion`` whether fades are cuts."""

    def __init__(self, style: CornerStyle | Callable[[], CornerStyle],
                 measure: Callable[[FontSpec], Measure], *,
                 text_scale: Callable[[], float] | None = None,
                 reduce_motion: Callable[[], bool] | None = None) -> None:
        self._style = style
        self._measure_for = measure
        self._measure: tuple[FontSpec, Measure] | None = None
        self._text_scale = text_scale
        self._reduce_motion = reduce_motion
        self._entries: list[_Entry] = []
        self._sizes: dict[Hashable, tuple[tuple, tuple[float, float]]] = {}
        self._sources: list[Callable[[], None]] = []

    # -- settings --

    @property
    def style(self) -> CornerStyle:
        style = self._style
        return style() if callable(style) else style

    def _fade_s(self, style: CornerStyle) -> float:
        if self._reduce_motion is not None and self._reduce_motion():
            return 0.0
        return style.fade_ms / 1000.0

    def _size(self, style: CornerStyle) -> int:
        scale = 1.0 if self._text_scale is None else self._text_scale()
        return scaled(style.font.size, scale)

    def _measure_of(self, style: CornerStyle) -> Measure:
        cached = self._measure
        if cached is None or cached[0] != style.font:
            cached = self._measure = (style.font, self._measure_for(style.font))
        return cached[1]

    # -- API --

    def set_item(self, key: Hashable, place: str, item: CornerItem, *,
                 fade: bool = True) -> None:
        """Show ``item`` under ``key`` at ``place`` (one of ``CORNER_PLACES``): a new key
        fades in at the end of that stack (``fade=False``: at once); a known key keeps its
        slot (a new place: the end of that stack) and, if it was fading out, comes back."""
        if place not in CORNER_PLACES:
            raise ValueError(f"corner place must be one of {', '.join(CORNER_PLACES)}, "
                             f"not {place!r}")
        found = self._find(key)
        if found is None:
            entry = _Entry(key, place, item)
            if not fade or self._fade_s(self.style) <= 0:
                entry.phase = "shown"
            self._entries.append(entry)
            return
        if found.place != place:
            self._entries.remove(found)
            self._entries.append(found)
            found.place = place
        if found.item is not item:
            found.item = item
            self._sizes.pop(key, None)
        if found.phase == "out":
            seconds = self._fade_s(self.style) if fade else 0.0
            opacity = 1.0 - found.t / seconds if seconds > 0 else 1.0
            found.phase, found.t = ("in", seconds * opacity) if seconds > 0 else ("shown", 0.0)

    def remove_item(self, key: Hashable, *, fade: bool = True) -> None:
        """Fade the item under ``key`` out (a cut under reduced motion or with
        ``fade=False``); nothing for an unknown key."""
        found = self._find(key)
        if found is None or (found.phase == "out" and fade):
            return
        seconds = self._fade_s(self.style) if fade else 0.0
        if seconds <= 0:
            self._drop(found)
            return
        opacity = found.t / seconds if found.phase == "in" else 1.0
        found.phase, found.t = "out", seconds * (1.0 - min(1.0, opacity))

    def pulse(self, key: Hashable) -> None:
        """F62: ring the item under ``key`` once (module docstring, "Motion"); nothing
        under reduced motion or for an unknown key."""
        found = self._find(key)
        if found is None or (self._reduce_motion is not None and self._reduce_motion()):
            return
        found.pulse = PULSE_S

    def add_source(self, fn: Callable[[], None]) -> None:
        """F62: ``fn()`` runs at the start of every ``update`` (module docstring)."""
        self._sources.append(fn)

    def clear(self) -> None:
        """Drop every item at once (the owner's reset)."""
        self._entries.clear()
        self._sizes.clear()

    def keys(self, place: str | None = None) -> tuple[Hashable, ...]:
        """The keys shown or fading, in stack order (one place, or all)."""
        return tuple(e.key for e in self._entries if place is None or e.place == place)

    def item(self, key: Hashable) -> CornerItem | None:
        found = self._find(key)
        return None if found is None else found.item

    def _find(self, key: Hashable) -> _Entry | None:
        return next((e for e in self._entries if e.key == key), None)

    def _drop(self, entry: _Entry) -> None:
        self._entries.remove(entry)
        self._sizes.pop(entry.key, None)

    # -- per frame --

    def update(self, dt: float) -> None:
        """Run the sources, then advance the fades and pulses by ``dt`` seconds; an item
        faded out leaves its stack."""
        for source in self._sources:
            source()
        fade = self._fade_s(self.style)
        dt = max(0.0, float(dt))
        for entry in list(self._entries):
            if entry.pulse > 0:
                entry.pulse = entry.pulse - dt
                if entry.pulse <= _EPSILON:
                    entry.pulse = 0.0
            if entry.phase == "in":
                entry.t += dt
                if fade <= 0 or entry.t >= fade - _EPSILON:
                    entry.phase, entry.t = "shown", 0.0
            elif entry.phase == "out":
                entry.t += dt
                if fade <= 0 or entry.t >= fade - _EPSILON:
                    self._drop(entry)

    @staticmethod
    def _pulse(entry: _Entry) -> tuple[float, float]:
        """The pulse ring now: (strength, gap outside the panel). It fades linearly from 1
        and moves out eased (fast, then settling) over ``PULSE_S``; (0, 0) when none."""
        if entry.pulse <= 0:
            return 0.0, 0.0
        progress = 1.0 - min(1.0, entry.pulse / PULSE_S)
        eased = 1.0 - (1.0 - progress) ** 2
        return 1.0 - progress, PULSE_RING + PULSE_GROW * eased

    def _opacity(self, entry: _Entry, fade: float) -> float:
        if entry.phase == "in":
            return 1.0 if fade <= 0 else min(1.0, entry.t / fade)
        if entry.phase == "out":
            return 0.0 if fade <= 0 else max(0.0, 1.0 - entry.t / fade)
        return 1.0

    def _context(self, style: CornerStyle, place: str, opacity: float = 1.0) -> CornerContext:
        return CornerContext(style, self._size(style), self._measure_of(style), place,
                             max_content_width(style), opacity)

    def _content_size(self, entry: _Entry, style: CornerStyle, size: int
                      ) -> tuple[float, float]:
        cache_key = (id(entry.item), getattr(entry.item, "revision", 0), size, style)
        cached = self._sizes.get(entry.key)
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        w, h = entry.item.measure(self._context(style, entry.place))
        found = (min(float(w), max_content_width(style)), float(h))
        self._sizes[entry.key] = (cache_key, found)
        return found

    def layout(self, reserved: Iterable[Box] = ()) -> dict[Hashable, Box | None]:
        """Each item's panel box now (None: it doesn't fit)."""
        style = self.style
        size = self._size(style)
        stacks: dict[str, list[tuple[Hashable, tuple[float, float]]]] = {}
        for entry in self._entries:
            stacks.setdefault(entry.place, []).append(
                (entry.key, self._content_size(entry, style, size)))
        return corner_layout(stacks, style, reserved)

    def views(self, reserved: Iterable[Box] = ()) -> tuple[CornerView, ...]:
        """Every item in stack order with its box and opacity."""
        boxes = self.layout(reserved)
        fade = self._fade_s(self.style)
        return tuple(CornerView(e.key, e.place, boxes.get(e.key), self._opacity(e, fade),
                                *self._pulse(e)) for e in self._entries)

    def overflow(self, reserved: Iterable[Box] = ()) -> tuple[Hashable, ...]:
        """The keys that don't fit their corner now (not drawn)."""
        boxes = self.layout(reserved)
        return tuple(key for key, box in boxes.items() if box is None)

    # -- drawing --

    def draw(self, canvas: "Canvas", painter: "Painter", *,
             reserved: Iterable[Box] = ()) -> None:
        """Each item that fits: its panel (``painter.shape``, cached), then its content
        inside the padding, both at its opacity."""
        if not self._entries:
            return
        style = self.style
        fade = self._fade_s(style)
        boxes = self.layout(reserved)
        painter.bind(canvas)
        for entry in self._entries:
            box = boxes.get(entry.key)
            opacity = self._opacity(entry, fade)
            if box is None or opacity <= 0.0:
                continue
            painter.shape(box, style.frame, alpha=opacity)
            pulse, spread = self._pulse(entry)
            if pulse > 0.0:                                     # F62: a rank changed
                frame = style.frame
                gap = round(spread)              # whole units: few cached ring shapes
                ring = FrameSpec(frame.fill_color, 0.0, style.accent_color, PULSE_RING,
                                 frame.corner_radius + gap)
                painter.shape(Box(box.x - gap, box.y - gap, box.w + 2 * gap,
                                  box.h + 2 * gap), ring, alpha=opacity * pulse)
            inner = Box(box.x + style.side_padding, box.y + style.top_padding,
                        box.w - 2 * style.side_padding, box.h - 2 * style.top_padding)
            entry.item.draw(canvas, inner, self._context(style, entry.place, opacity))


def draw_line(canvas: "Canvas", text: str, font: FontSpec, color: RGB,
              pos: tuple[float, float], opacity: float = 1.0) -> None:
    """One line, top-left at ``pos``: ``canvas.draw_text`` when opaque, else the cached
    rendered line blitted at ``opacity`` (as the notices draw theirs)."""
    if opacity <= 0.0 or not text:
        return
    if opacity >= 1.0:
        canvas.draw_text(text, font, color, pos)
        return
    raster = canvas.font_handle(font, max(1, round(font.size * canvas.scale)))
    rendered = canvas.assets.text_line(raster, text, color)
    surface = canvas.surface
    assert surface is not None
    previous = rendered.get_alpha()
    rendered.set_alpha(round(255 * opacity))
    try:
        surface.blit(rendered, canvas.px(*pos))
    finally:
        rendered.set_alpha(previous)


__all__ = ["CORNER_FOLLOWS", "CornerContext", "CornerItem", "CornerStyle", "CornerView",
           "StatusCorner", "corner_layout", "corner_style", "corner_token", "draw_line",
           "max_content_width", "reserved_areas"]

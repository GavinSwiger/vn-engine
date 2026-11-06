"""``NoticeLayer``: the one non-modal notice (toast) drawn over every screen (F11 ``04`` §7.9).

Why this module exists: "Quick saved.", a failed save or load, F12's persistent-data notices
(SEC-F12-12), F16's W70, and F37's achievements all need a short message that never takes
focus or input and never blocks play (ui-system §9 "Notice"). One component owned by the
shell (C2) keeps their look, timing, and stacking identical. It is not a screen: it is never
in the event path, so clicks, keys, and the wheel always reach the screens below, and it is
drawn by ``GameShell.draw_layer`` after the screens (so never in a scene picture, backdrop, or
thumbnail) and before the dev overlay.

Rules (03-ui "Notice (toast)", ui-system §5 and §9):

- **Text** is cleaned like a save's (``04`` §7.7): characters of category ``Cc``, ``Cf``
  (except ZWJ), ``Zl``, ``Zp`` removed, lone surrogates replaced by U+FFFD, then F05's
  ``render_safe``; cut to 1,000 code points.
- **Look**: a panel ``topright`` at (1256, 24), width = text + 40 (+ 18 for a problem),
  160 to ``notice.max_width``; text wraps at the panel's inner width, at most 4 lines, then
  "…"; height lines × pitch + 24. A problem has a 6-wide bar 12 inside the left edge.
- **Stack**: at most 3 shown, oldest at the top, each 8 below the one above, none ending
  below y 400. More wait in order (at most 10; past that the oldest waiting is dropped). A
  text equal to one shown or waiting restarts that one's time instead of adding another.
- **Timing**: fade in over ``notice.fade_ms`` (``ease_in_out``, sliding 24 units leftward),
  shown ``min(8000, duration_ms + 50 × (characters − 20))`` ms, fade out (``linear``); the
  shown time pauses while the window is unfocused and while the pointer is over that notice.
  Restacking moves over ``fade_ms`` (``ease_in_out``). Under reduced motion all three are
  cuts. While the top screen ``holds_notices`` (C7), new notices wait.
- **Icon** (F37 §5.1): ``notify(icon=)`` with an ``ImageRef`` puts it in a 48×48 box at the
  panel's inner left (top-aligned, 12 down; scaled to fit, never up, centred in the box), the
  text 12 after it, and the panel at least 48 + 24 tall; a shorter text block is centred
  against the icon. A placeholder (missing or unreadable picture) draws a 48×48 frame in the
  marker color instead. Without an icon the layout is unchanged.
- **Skin** (F65 round 3): ``notify(skin=)`` with a ``NoticeSkin`` (``ui/devicelook``: a
  pigeon's note, a phone's bubble) draws the panel with the skin's frame and text color and
  then its marks; the layout, timing and text are the same as without one.

Times are kept in seconds from ``update(dt)`` (the caller's clock), so tests drive it with a
fake clock. Text is measured with an injected ``layouts.Measure`` (reference metrics), so
layout tests use M20 and need no font.
"""

import math
import unicodedata
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Literal, Protocol

from engine.core.graphemes import graphemes
from engine.render.frames import FrameSpec
from engine.render.text import Face, FontSpec, Synth
from engine.render.textlayout import REPLACEMENT, render_safe
from engine.ui.focus import Box
from engine.ui.layouts import Measure, fit_message, pitch, scaled

if TYPE_CHECKING:
    from engine.render.assets import ImageRef
    from engine.render.canvas import Canvas
    from engine.ui.paint import Painter
    from engine.ui.theme import UiTheme

RGB = tuple[int, int, int]
Kind = Literal["info", "problem"]
Phase = Literal["in", "shown", "out", "gone"]

KINDS: Final = ("info", "problem")
NOTICE_RIGHT: Final = 1256          # the first notice is topright at (1256, 24)
NOTICE_TOP: Final = 24
NOTICE_LIMIT: Final = 400           # no notice ends below this y
NOTICE_GAP: Final = 8               # each next notice this far below the one above
NOTICE_MIN_WIDTH: Final = 160
PAD_X: Final = 20                   # text inset, left and right
PAD_Y: Final = 12                   # text inset, top and bottom
PROBLEM_EXTRA: Final = 18           # a problem's text starts at 38
ICON_SIZE: Final = 48               # F37: the notice icon's box
ICON_GAP: Final = 12                # from the icon to the text
ICON_RADIUS: Final = 8              # the placeholder frame's corners
BAR_WIDTH: Final = 6
BAR_INSET: Final = 12
MAX_LINES: Final = 4
MAX_SHOWN: Final = 3
MAX_WAITING: Final = 10
TEXT_MAX: Final = 1000              # code points kept after cleaning
SHOWN_CAP_MS: Final = 8000
PER_CHAR_MS: Final = 50
FREE_CHARS: Final = 20
SLIDE: Final = 24                   # units the fade-in slides leftward
ZWJ: Final = "‍"
_REMOVED_CATEGORIES: Final = frozenset({"Cc", "Cf", "Zl", "Zp"})
_EPSILON: Final = 1e-9


# --- Pure rules ----------------------------------------------------------------------------

def clean_text(text: str, limit: int = TEXT_MAX) -> str:
    """``04`` §7.7's render-safe cleaning, cut to ``limit`` code points: ``Cc``, ``Cf``
    (except ZWJ), ``Zl``, ``Zp`` removed; lone surrogates (``Cs``) become U+FFFD; then
    ``render_safe``. Stops reading once ``limit`` characters are kept."""
    if not isinstance(text, str):
        raise TypeError(f"notice text must be str, not {type(text).__name__}")
    kept: list[str] = []
    for char in text:
        if len(kept) >= limit:
            break
        category = unicodedata.category(char)
        if category == "Cs":
            kept.append(REPLACEMENT)
        elif category in _REMOVED_CATEGORIES and char != ZWJ:
            continue
        else:
            kept.append(char)
    return render_safe("".join(kept))


def shown_ms(chars: int, duration_ms: int = 1500) -> int:
    """ui-system §5 "Notice shown": ``min(8000, duration_ms + 50 × (chars − 20))``, never
    less than ``duration_ms``. An author's ``duration_ms`` above 8,000 (the token allows
    10,000) is kept as it is rather than cut to 8,000."""
    total = duration_ms + PER_CHAR_MS * max(0, chars - FREE_CHARS)
    return min(max(SHOWN_CAP_MS, duration_ms), total)


def ease_in_out(t: float) -> float:
    """ui-system §5: (1 − cos(πt)) / 2."""
    t = 0.0 if t <= 0.0 else 1.0 if t >= 1.0 else t
    return (1.0 - math.cos(math.pi * t)) / 2.0


def _leftover(seconds: float) -> float:
    """Time past a phase's end, carried into the next; rounding dust counts as none."""
    return seconds if seconds > _EPSILON else 0.0


def _ease_inverse(value: float) -> float:
    value = 0.0 if value <= 0.0 else 1.0 if value >= 1.0 else value
    return math.acos(1.0 - 2.0 * value) / math.pi


@dataclass(frozen=True)
class NoticePanel:
    """One notice's size and text, relative to its panel's top-left (canvas units)."""

    width: float
    height: float
    lines: tuple[str, ...]
    size: int                   # text size after the text scale
    pitch: int
    text_x: int                 # 20, or 38 for a problem (+ 60 with an icon)
    truncated: bool             # the last line ends in "…"
    bar: Box | None             # the problem bar, relative to the panel
    icon: Box | None = None     # F37: the icon box, relative to the panel
    text_y: float = PAD_Y       # the first line's top, relative to the panel


def notice_panel(text: str, kind: Kind, measure: Measure, *, size: int,
                 max_width: int = 560, icon: bool = False) -> NoticePanel:
    """03-ui's notice table: width = text + 40 (+ 18 for a problem), 160 to ``max_width``;
    the text wraps at the inner width in at most 4 lines, then "…"; height = lines × pitch
    + 24; the problem bar is 6 × (height − 24), 12 inside the left edge. ``icon`` (F37):
    the 48×48 icon box at the inner left, the text 60 further right, height at least 72,
    a text block shorter than the icon centred against it."""
    problem = kind == "problem"
    icon_x = PAD_X + (PROBLEM_EXTRA if problem else 0)
    text_x = icon_x + (ICON_SIZE + ICON_GAP if icon else 0)
    natural = measure(text, size) + text_x + PAD_X
    width = min(float(max_width), max(float(NOTICE_MIN_WIDTH), natural))
    fit = fit_message(text, width - text_x - PAD_X, size, measure, max_lines=MAX_LINES,
                      min_size=size)
    line_pitch = pitch(size)
    text_h = len(fit.lines) * line_pitch
    height = text_h + 2 * PAD_Y
    icon_box = None
    text_y: float = PAD_Y
    if icon:
        icon_box = Box(icon_x, PAD_Y, ICON_SIZE, ICON_SIZE)
        height = max(height, ICON_SIZE + 2 * PAD_Y)
        text_y = PAD_Y + max(0.0, (ICON_SIZE - text_h) / 2)
    bar = Box(BAR_INSET, PAD_Y, BAR_WIDTH, height - 2 * PAD_Y) if problem else None
    return NoticePanel(width, height, fit.lines, size, line_pitch, text_x, fit.truncated, bar,
                       icon_box, text_y)


# --- Style ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class NoticeStyle:
    """``[theme.notice]`` resolved: the colors that follow ``panel.*`` and the bar's
    ``button.marker.fill_color`` filled in. ``font.size`` is the size at 100% text."""

    frame: FrameSpec = FrameSpec((0xFF, 0xF4, 0xF8), 0.94, (0xF0, 0xA0, 0xC0), 2, 12, 24)
    image: "ImageRef | None" = None
    font: FontSpec = FontSpec(None, 24)
    text_color: RGB = (0x3D, 0x2B, 0x36)
    marker_color: RGB = (0xA0, 0x28, 0x60)
    max_width: int = 560
    duration_ms: int = 1500
    fade_ms: int = 200
    sound: str | None = None


def notice_style(theme: "UiTheme") -> NoticeStyle:
    """The notice look of ``theme`` (03-ui "Theme tokens": ``None`` follows ``panel.*``);
    ``notice.frame_image`` is the one ``resolve_theme`` checked (W64), or None."""
    c = theme.cfg
    n, p = c.notice, c.panel

    def pick(value, default):
        return default if value is None else value

    frame = FrameSpec(pick(n.fill_color, p.fill_color), pick(n.fill_opacity, p.fill_opacity),
                      pick(n.border_color, p.border_color), n.border_width, n.corner_radius,
                      n.frame_slice_width)
    return NoticeStyle(frame=frame, image=theme.frames.get("notice"),
                       font=theme.font(n.text_size), text_color=pick(n.text_color, p.text_color),
                       marker_color=pick(n.marker.fill_color, c.button.marker.fill_color),
                       max_width=n.max_width, duration_ms=n.duration_ms, fade_ms=n.fade_ms,
                       sound=n.sound)


# --- The layer -----------------------------------------------------------------------------

@dataclass(frozen=True)
class NoticeView:
    """A shown notice as drawn this frame (tests; F37's icon and its box on the canvas)."""

    text: str
    kind: Kind
    phase: Phase
    box: Box                    # where the panel is drawn (slide and restack included)
    opacity: float
    lines: tuple[str, ...]
    size: int
    shown_s: float              # its shown time
    elapsed_s: float            # time spent in the current phase
    icon: "ImageRef | None" = None
    icon_box: Box | None = None


class NoticeSkin(Protocol):
    """F65 round 3: a look for one notice (module docstring). A skin may also have
    ``italic`` (True: the text in italics: the bundled Italic face, or the game's own font
    slanted)."""

    text_color: RGB

    def frame(self, base: FrameSpec) -> FrameSpec: ...

    def decorate(self, canvas: "Canvas", painter: "Painter", box: Box,
                 opacity: float) -> None: ...


class _Notice:
    __slots__ = ("text", "kind", "icon", "skin", "chars", "phase", "t", "slide", "shown_s", "panel",
                 "panel_key", "y", "y_from", "y_to", "y_t")

    def __init__(self, text: str, kind: Kind, icon: "ImageRef | None" = None,
                 skin: NoticeSkin | None = None) -> None:
        self.text = text
        self.kind = kind
        self.icon = icon
        self.skin = skin
        self.chars = len(graphemes(text))
        self.phase: Phase = "in"
        self.t = 0.0
        self.slide = True
        self.shown_s = 0.0
        self.panel: NoticePanel | None = None
        self.panel_key: tuple | None = None
        self.y = self.y_from = self.y_to = float(NOTICE_TOP)
        self.y_t = 1.0


class NoticeLayer:
    """Queue, timing, stack, and drawing of notices. ``style`` is a ``NoticeStyle`` or a
    function giving the current one; ``measure`` measures text (reference metrics, canvas
    units) in the notice font; ``text_scale`` gives F16's text scale; ``reduce_motion``
    whether fades are cuts; ``play`` plays ``notice.sound`` when a notice appears."""

    def __init__(self, style: NoticeStyle | Callable[[], NoticeStyle], measure: Measure, *,
                 text_scale: Callable[[], float] | None = None,
                 reduce_motion: Callable[[], bool] | None = None,
                 play: Callable[[str | None], None] | None = None) -> None:
        self._style = style
        self._measure = measure
        self._text_scale = text_scale
        self._reduce_motion = reduce_motion
        self._play = play
        self._shown: list[_Notice] = []
        self._waiting: deque[_Notice] = deque()
        self.hold = False
        self.dropped = 0                    # waiting notices dropped past 10 (tests)

    # -- settings --

    @property
    def style(self) -> NoticeStyle:
        style = self._style
        return style() if callable(style) else style

    def _fade_s(self, style: NoticeStyle) -> float:
        if self._reduce_motion is not None and self._reduce_motion():
            return 0.0
        return style.fade_ms / 1000.0

    def _size(self, style: NoticeStyle) -> int:
        scale = 1.0 if self._text_scale is None else self._text_scale()
        return scaled(style.font.size, scale)

    # -- notify --

    def notify(self, text: str, *, kind: Kind = "info", hold: bool | None = None,
               icon: "ImageRef | None" = None, skin: NoticeSkin | None = None) -> None:
        """Show ``text`` (cleaned, cut to 1,000 code points). A text equal to one shown
        restarts its shown time (from a fade-out it fades back in, without the slide); equal
        to one waiting, nothing changes. Otherwise it waits in order, past 10 the oldest
        waiting is dropped, and it shows now if there is room and ``hold`` (the top screen's
        ``holds_notices``; None keeps the last value) is False. ``icon`` (F37): a picture
        drawn left of the text; ``skin`` (F65): its look (module docstring)."""
        if kind not in KINDS:
            raise ValueError(f"notice kind must be 'info' or 'problem', not {kind!r}")
        if hold is not None:
            self.hold = hold
        text = clean_text(text)
        for notice in self._shown:
            if notice.text == text:
                self._restart(notice)
                return
        if any(notice.text == text for notice in self._waiting):
            return
        self._waiting.append(_Notice(text, kind, icon, skin))
        while len(self._waiting) > MAX_WAITING:
            self._waiting.popleft()
            self.dropped += 1
        self._promote(self.style)

    def _restart(self, notice: _Notice) -> None:
        if notice.phase == "shown":
            notice.t = 0.0
        elif notice.phase == "out":
            fade = self._fade_s(self.style)
            opacity = 1.0 - notice.t / fade if fade > 0 else 1.0
            notice.phase = "in"
            notice.slide = False
            notice.t = fade * _ease_inverse(opacity)
        # "in": its shown time has not started yet.

    def clear(self) -> None:
        """Drop every notice, shown and waiting (``show_fatal_error``)."""
        self._shown.clear()
        self._waiting.clear()

    # -- per frame --

    def update(self, dt: float, *, focused: bool = True,
               pointer: tuple[float, float] | None = None, hold: bool | None = None) -> None:
        """Advance by ``dt`` seconds. Shown time runs only while ``focused`` and the
        ``pointer`` (canvas units, None when outside) is not over that notice; fades and
        restacking always run. ``hold``: the top screen's ``holds_notices`` (None: unchanged).
        A notice that leaves frees its place in this frame; waiting ones then show if they
        fit."""
        if hold is not None:
            self.hold = hold
        style = self.style
        fade = self._fade_s(style)
        dt = max(0.0, float(dt))
        changed = self._refresh_panels(style)
        for notice in self._shown:                      # restacking already under way
            if notice.y_t < 1.0:
                notice.y_t = 1.0 if fade <= 0 else min(1.0, notice.y_t + dt / fade)
                notice.y = notice.y_from + (notice.y_to - notice.y_from) * ease_in_out(
                    notice.y_t)
        for notice in self._shown:
            over = pointer is not None and self._box(notice, fade).contains(pointer)
            self._advance(notice, dt, fade, running=focused and not over)
        before = len(self._shown)
        self._shown = [notice for notice in self._shown if notice.phase != "gone"]
        if changed or len(self._shown) != before:
            self._retarget(fade)
        self._promote(style)

    def _advance(self, notice: _Notice, dt: float, fade: float, *, running: bool) -> None:
        remaining = dt
        while True:
            if notice.phase == "in":
                if fade > 0:
                    notice.t += remaining
                    if notice.t < fade - _EPSILON:
                        return
                    remaining = _leftover(notice.t - fade)
                notice.phase, notice.t = "shown", 0.0
            elif notice.phase == "shown":
                if not running:
                    return
                notice.t += remaining
                if notice.t < notice.shown_s - _EPSILON:
                    return
                remaining = _leftover(notice.t - notice.shown_s)
                notice.phase, notice.t = "out", 0.0
            elif notice.phase == "out":
                if fade > 0:
                    notice.t += remaining
                    if notice.t < fade - _EPSILON:
                        return
                notice.phase = "gone"
                return
            else:
                return

    def _refresh_panels(self, style: NoticeStyle) -> bool:
        """Lay out every notice for the current text size and width; True if any changed."""
        changed = False
        for notice in self._shown:
            changed = self._panel(notice, style) or changed
        return changed

    def _panel(self, notice: _Notice, style: NoticeStyle) -> bool:
        size = self._size(style)
        key = (size, style.max_width, style.font)
        if notice.panel is not None and notice.panel_key == key:
            return False
        notice.panel = notice_panel(notice.text, notice.kind, self._measure, size=size,
                                    max_width=style.max_width, icon=notice.icon is not None)
        notice.panel_key = key
        return True

    def _targets(self) -> list[float]:
        top = float(NOTICE_TOP)
        out = []
        for notice in self._shown:
            assert notice.panel is not None
            out.append(top)
            top += notice.panel.height + NOTICE_GAP
        return out

    def _retarget(self, fade: float) -> None:
        for notice, target in zip(self._shown, self._targets(), strict=True):
            if target == notice.y_to:
                continue
            if fade <= 0:
                notice.y = notice.y_from = notice.y_to = target
                notice.y_t = 1.0
            else:
                notice.y_from, notice.y_to, notice.y_t = notice.y, target, 0.0

    def _promote(self, style: NoticeStyle) -> None:
        """Show waiting notices in order while fewer than 3 are shown, the next one ends by
        y 400, and the top screen does not hold notices."""
        if self.hold:
            return
        while self._waiting and len(self._shown) < MAX_SHOWN:
            notice = self._waiting[0]
            self._panel(notice, style)
            assert notice.panel is not None
            targets = self._targets()
            top = float(NOTICE_TOP) if not self._shown else (
                targets[-1] + self._shown[-1].panel.height + NOTICE_GAP)  # type: ignore[union-attr]
            if top + notice.panel.height > NOTICE_LIMIT:
                return
            self._waiting.popleft()
            notice.y = notice.y_from = notice.y_to = top
            notice.y_t = 1.0
            notice.phase, notice.t, notice.slide = "in", 0.0, True
            notice.shown_s = shown_ms(notice.chars, style.duration_ms) / 1000.0
            self._shown.append(notice)
            if self._play is not None and style.sound is not None:
                self._play(style.sound)

    # -- geometry --

    def _opacity(self, notice: _Notice, fade: float) -> float:
        if notice.phase == "in":
            return 1.0 if fade <= 0 else ease_in_out(notice.t / fade)
        if notice.phase == "out":
            return 0.0 if fade <= 0 else max(0.0, 1.0 - notice.t / fade)
        return 1.0 if notice.phase == "shown" else 0.0

    def _box(self, notice: _Notice, fade: float) -> Box:
        panel = notice.panel
        assert panel is not None
        slide = 0.0
        if notice.phase == "in" and notice.slide and fade > 0:
            slide = SLIDE * (1.0 - ease_in_out(notice.t / fade))
        return Box(NOTICE_RIGHT - panel.width + slide, notice.y, panel.width, panel.height)

    def views(self) -> tuple[NoticeView, ...]:
        """The shown notices, top first, as they are drawn now."""
        fade = self._fade_s(self.style)
        out = []
        for notice in self._shown:
            panel = notice.panel
            assert panel is not None
            box = self._box(notice, fade)
            icon_box = None if panel.icon is None else panel.icon.moved(box.x, box.y)
            out.append(NoticeView(notice.text, notice.kind, notice.phase, box,
                                  self._opacity(notice, fade), panel.lines, panel.size,
                                  notice.shown_s, notice.t, notice.icon, icon_box))
        return tuple(out)

    def waiting(self) -> tuple[str, ...]:
        """The waiting texts, oldest first."""
        return tuple(notice.text for notice in self._waiting)

    def contains(self, pos: tuple[float, float]) -> bool:
        """Whether ``pos`` (canvas units) is over a shown notice."""
        fade = self._fade_s(self.style)
        return any(self._box(notice, fade).contains(pos) for notice in self._shown)

    # -- drawing --

    def draw(self, canvas: "Canvas", painter: "Painter") -> None:
        """Every shown notice, top first: the panel (``painter.shape``, cached), the
        problem bar, and the text lines, all at the notice's opacity."""
        if not self._shown:
            return
        style = self.style
        fade = self._fade_s(style)
        painter.bind(canvas)
        for notice in self._shown:
            opacity = self._opacity(notice, fade)
            if opacity <= 0.0:
                continue
            panel = notice.panel
            assert panel is not None
            box = self._box(notice, fade)
            skin = notice.skin
            if skin is None:
                painter.shape(box, style.frame, image=style.image, alpha=opacity)
            else:
                painter.shape(box, skin.frame(style.frame), alpha=opacity)
                skin.decorate(canvas, painter, box, opacity)
            if panel.bar is not None:
                bar = panel.bar
                canvas.fill((*style.marker_color, round(255 * opacity)),
                            (box.x + bar.x, box.y + bar.y, bar.w, bar.h))
            if panel.icon is not None and notice.icon is not None:
                icon = panel.icon.moved(box.x, box.y)
                if notice.icon.is_placeholder:
                    painter.shape(icon, FrameSpec(style.marker_color, 1.0,
                                                  corner_radius=ICON_RADIUS), alpha=opacity)
                else:
                    draw_fitted(canvas, notice.icon, icon, opacity)
            font = replace(style.font, size=panel.size)
            if getattr(skin, "italic", False):
                font = (replace(font, bundled=Face.ITALIC) if font.ref is None
                        else replace(font, synth=Synth.ITALIC))
            top = box.y + panel.text_y
            for index, line in enumerate(panel.lines):
                if line:
                    _draw_line(canvas, line, font,
                               style.text_color if skin is None else skin.text_color,
                               (box.x + panel.text_x, top + index * panel.pitch), opacity)


def fit_box(size: tuple[float, float], box: Box) -> Box:
    """``size`` scaled to fit ``box`` keeping its shape, never up, centred, in whole canvas
    units (F21's ``fit_picture`` rule)."""
    w, h = size
    if w <= 0 or h <= 0:
        return Box(box.x + box.w / 2, box.y + box.h / 2, 0, 0)
    s = min(1.0, box.w / w, box.h / h)
    tw, th = round(w * s), round(h * s)
    return Box(box.x + (box.w - tw) / 2, box.y + (box.h - th) / 2, tw, th)


def draw_fitted(canvas: "Canvas", image: "ImageRef", box: Box, opacity: float = 1.0) -> None:
    """``image`` fitted into ``box`` (``fit_box``) through the asset variant cache, at
    ``opacity`` (surface alpha on the cached variant, restored after). F37's notice icon
    and achievements page. A placeholder draws nothing (the caller draws its frame)."""
    if opacity <= 0.0 or image.is_placeholder:
        return
    target = fit_box(image.size, box)
    rect = canvas.rect_to_px((target.x, target.y, target.w, target.h))
    if rect.width <= 0 or rect.height <= 0:
        return
    surface, _offset = canvas.assets.variant(image, rect.size, canvas.quality)
    framebuffer = canvas.surface
    assert framebuffer is not None
    if opacity >= 1.0:
        framebuffer.blit(surface, rect.topleft)
        return
    previous = surface.get_alpha()
    surface.set_alpha(round(255 * opacity))
    try:
        framebuffer.blit(surface, rect.topleft)
    finally:
        surface.set_alpha(previous)


def _draw_line(canvas: "Canvas", text: str, font: FontSpec, color: RGB,
               pos: tuple[float, float], opacity: float) -> None:
    """One line, top-left at ``pos``: ``canvas.draw_text`` when opaque, else the cached
    rendered line blitted at ``opacity`` (surface alpha, restored after)."""
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


__all__ = ["ICON_GAP", "ICON_SIZE", "KINDS", "MAX_SHOWN", "MAX_WAITING", "NOTICE_LIMIT",
           "NOTICE_RIGHT", "NOTICE_TOP", "Kind", "NoticeLayer", "NoticePanel", "NoticeStyle",
           "NoticeSkin", "NoticeView", "clean_text", "draw_fitted", "ease_in_out", "fit_box", "notice_panel",
           "notice_style", "shown_ms"]

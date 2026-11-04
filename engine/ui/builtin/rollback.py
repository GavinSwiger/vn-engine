"""``RollbackKeys``: the player's way back and forward through the story (F14 ``04-technical.md``
§5.4, §7.7; ``07-architecture-review.md`` I-2, I-6, I-10; A6).

Why this module exists: rollback is a runtime feature (``StepBack``/``StepForward`` on the
interpreter), but its inputs are presentation: wheel notches, a touchpad's small scroll
amounts, Page Up/Down, the gamepad shoulders, and the quick menu's Back. ``RollbackKeys``
turns them into at most one posted event per frame and reads the driver's
``rollback_view()`` to know how far it can go. It never touches the story itself
(invariant 5).

- **Host.** An ``InGameOverlay`` on F05's ``TextboxScreen`` (after F10's and F11's, before
  F15's) and a say listener. F07's ``ChoiceScreen`` lets the wheel, Page Up/Down and the
  shoulders fall through (I-10), and the host passes ``frozen`` only while a screen that
  isn't in-game is on top (A6), so the wheel steps back over choices too.
- **Notches** (``handle_event``): back < 0 < forward. ``MOUSEWHEEL``: ``precise_y`` (else
  ``y``), positive = wheel up = back, added to a signed accumulator; each whole
  ``TOUCH_UNITS_PER_STEP`` is one notch and the remainder stays, so a mouse wheel's whole
  numbers count at once and a touchpad's fractions add up. A change of direction, or
  ``WHEEL_RESET_S`` with no wheel event, empties the accumulator; ``flipped`` is ignored.
  ``KEYDOWN`` Page Up/Down (not with Ctrl, Alt, Meta or GUI held; once per press: a repeat
  of a key still down does nothing) and ``CONTROLLERBUTTONDOWN`` left/right shoulder count
  one each. An input with notches is consumed only while rollback is on for the game
  (``view.shown``), and it first shows a hidden box (PR-F14-18).
- **Posting** (``update``, I-2): in the input frame's update, the frame's notches become
  one ``StepBack(min(want, back_room))`` or one ``StepForward(min(n, ahead))``; the driver
  runs it in the next frame's pump. Back past the room triggers the limit cue, and so does
  a ``refused`` count that went up since the last frame looked (a step that couldn't be
  restored; never compared right after posting). A frozen frame drops everything.
- **Cue.** ``cue`` is the ``LimitCue`` (below) the shell's cue layer updates and draws
  (layer 6, A3): ``trigger``, and ``end`` on a forward post, a new ``Say``, hidden mode,
  ``reset``, and a frozen frame. Its mark sits on ``textbox.cue_anchor()`` and its bump goes
  through ``textbox.set_bump`` (F05 A4; F17 answers both in NVL, I-8).
- **Rewind tag** (``draw``, layer 4, Could): while ``view.ahead > 0`` and ``[rollback]
  marker``, a pill at (24, 24), or 8 right of F15's pill (``skip_indicator``), with a
  double left triangle and ``ahead``; not in hidden mode. It is read in the draw, so it
  changes in the frame of each step, advance, or pick.

The driver is reached through ``RollbackStory`` (a ui-local Protocol, I-6), so ``ui`` imports
only ``runtime.commands`` of the runtime.
"""

import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Final, Protocol

import pygame

from engine.core.config_schema import ThemeConfig
from engine.render.effects import ease_in_out
from engine.render.frames import FrameSpec, build_frame, build_triangle
from engine.runtime.commands import RollbackView, Say, StepBack, StepForward
from engine.ui.focus import Box
from engine.ui.input import UiEvent
from engine.ui.theme import measure_with

if TYPE_CHECKING:
    from engine.render.assets import AssetManager
    from engine.render.canvas import Canvas
    from engine.ui.paint import Painter
    from engine.ui.theme import UiTheme

TOUCH_UNITS_PER_STEP: Final = 1.0        # wheel units per notch (04 §7.7; tuned by hand)
WHEEL_RESET_S: Final = 0.3               # the accumulator empties after this with no wheel
# The limit cue (03 "Motion and timing", "Screens and elements").
HOLD_S: Final = 0.4                      # full opacity after the last refused back
FADE_S: Final = 0.1                      # then out, linear (a cut under reduced motion)
BUMP_UP_S: Final = 0.08                  # the bump: 80 ms up, 120 ms back
BUMP_DOWN_S: Final = 0.12
MARK_SIZE: Final = (56, 28)
MARK_RADIUS: Final = 14
BAR_SIZE: Final = (20, 3)
GLYPH_GAP: Final = 3
TRIANGLE_SIZE: Final = (16, 10)
GLYPH_HEIGHT: Final = BAR_SIZE[1] + GLYPH_GAP + TRIANGLE_SIZE[1]     # 16
# The rewind tag (03 "Screens and elements", UI-F14-09).
TAG_TOPLEFT: Final = (24, 24)
TAG_GAP: Final = 8                       # right of F15's pill while that shows
TAG_EXTRA_H: Final = 8                   # height = quick_menu.text_size + 8
TAG_PAD: Final = 12                      # each side
TAG_TRIANGLE: Final = (10, 12)           # two, 2 apart: a 22×12 glyph
TAG_TRIANGLE_GAP: Final = 2
TAG_GLYPH_W: Final = 2 * TAG_TRIANGLE[0] + TAG_TRIANGLE_GAP
TAG_NUMBER_GAP: Final = 6
_DEFAULT_THEME: Final = ThemeConfig()
_EPS: Final = 1e-9
_BLOCKING_MODS: Final = (pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META
                         | pygame.KMOD_GUI)
_KEYS: Final = {pygame.K_PAGEUP: -1, pygame.K_PAGEDOWN: 1}
_BUTTONS: Final = {pygame.CONTROLLER_BUTTON_LEFTSHOULDER: -1,
                   pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: 1}


class RollbackStory(Protocol):
    """What ``RollbackKeys`` needs of the story driver (``RuntimeStoryDriver``)."""

    def rollback_view(self) -> RollbackView: ...

    def post(self, event: object) -> None: ...


class RollbackTextbox(Protocol):
    """What ``RollbackKeys`` needs of F05's ``TextboxScreen``."""

    @property
    def hidden(self) -> bool: ...

    def set_hidden(self, hidden: bool) -> None: ...


class CueTextbox(Protocol):
    """What ``LimitCue`` needs of F05's ``TextboxScreen`` (A4; F17 answers in NVL)."""

    @property
    def box_shown(self) -> bool: ...

    def cue_anchor(self) -> tuple[float, float]: ...

    def set_bump(self, dy: float) -> None: ...

    def reduce_motion(self) -> bool: ...


class TagShell(Protocol):
    """What the rewind tag needs of the shell: the theme, assets, and painter."""

    theme: "UiTheme"
    painter: "Painter"

    @property
    def assets(self) -> "AssetManager": ...


class LimitCue:
    """The limit cue (UI-F14-03 to 06; ``04`` §7.7 "Cue"), the shell's cue layer (layer 6,
    ``GameShell.set_cue_layer``).

    - ``trigger()`` (a back input that couldn't move): the mark shows from the next frame
      at opacity 1, held ``HOLD_S`` after the last trigger, then fades out over ``FADE_S``
      (under reduced motion it is cut at ``HOLD_S``). A trigger while it shows or leaves
      restores full opacity and restarts the hold; ``limit_sound`` plays only when the mark
      appears. ``t`` counts from the last trigger's frame (that frame adds no time).
    - **Bump**: the say window moves up ``rollback.bump_height`` and back (``BUMP_UP_S`` +
      ``BUMP_DOWN_S``, ``ease_in_out`` each way) through ``textbox.set_bump``, with the mark.
      A new one starts only at a trigger after the last one has ended, and never under
      reduced motion (the shell's flag or the textbox's), with ``bump_height`` 0, while the
      say window isn't drawn, or while ``set_anchor`` holds a point.
    - ``end()`` (a forward post, a new ``Say``, hidden mode, ``reset``, a frozen frame, and
      a covered game in ``update``): the mark is gone and the window at rest at once.
    - **Draw**: centered on ``textbox.cue_anchor()`` (or the ``set_anchor`` point) plus the
      bump: ``rollback.mark.image`` at its own size if usable, else the drawn 56×28 pill
      with the bar and up-triangle (one cached surface per device size), at the opacity.
    """

    def __init__(self, textbox: CueTextbox | None = None, *, theme: "UiTheme | None" = None,
                 play: Callable[[str | None], None] | None = None) -> None:
        self.textbox = textbox
        self.theme = theme
        self.play = play
        self.active = False              # the mark is up (appearing, held, or leaving)
        self.visible = False             # drawn this frame (not in the trigger's frame)
        self.triggers = 0
        self.t = 0.0                     # seconds since the last trigger
        self.opacity = 0.0
        self.bump_t: float | None = None # seconds into the running bump
        self.dy = 0.0                    # the bump's offset now (≤ 0)
        self._fresh = False              # a trigger came this frame: no time added
        self._appearing = False          # the mark shows from the next update
        self._want_bump = False
        self._reduce = False             # the shell's reduce motion, as last passed
        self._anchor: Callable[[], tuple[float, float]] | None = None
        self._surface: tuple[tuple, pygame.Surface] | None = None

    # -- settings --

    def _cfg(self) -> "ThemeConfig":
        return self.theme.cfg if self.theme is not None else _DEFAULT_THEME

    def restyle(self, theme: "UiTheme") -> None:
        """F49 (07 I-1): the current look's theme from now on (``GameShell``'s look
        listener, once per look change); the drawn mark is built again on its next draw."""
        self.theme = theme
        self._surface = None

    def _reduced(self) -> bool:
        textbox = self.textbox
        return self._reduce or (textbox is not None and bool(textbox.reduce_motion()))

    def set_anchor(self, fn: Callable[[], tuple[float, float]] | None) -> None:
        """F23 A4: while ``fn`` is set the mark is drawn at ``fn()`` with no bump (a running
        one ends); None returns to the textbox's anchor."""
        self._anchor = fn
        if fn is not None:
            self._stop_bump()

    # -- life --

    def trigger(self) -> None:
        self.triggers += 1
        self.t = 0.0
        self._fresh = True
        self._want_bump = True
        if not self.active:
            self.active = True
            self._appearing = True
            self.visible = False

    def end(self) -> None:
        self.active = False
        self.visible = False
        self._appearing = False
        self._want_bump = False
        self.opacity = 0.0
        self._stop_bump()

    def _stop_bump(self) -> None:
        self.bump_t = None
        if self.dy != 0.0:
            self.dy = 0.0
            if self.textbox is not None:
                self.textbox.set_bump(0.0)

    def update(self, dt: float, *, covered: bool, reduce_motion: bool) -> None:
        self._reduce = bool(reduce_motion)
        if covered:
            self.end()
            return
        if not self.active:
            return
        reduce = self._reduced()
        fresh, self._fresh = self._fresh, False
        if not fresh:
            self.t += dt
        if self._appearing and not fresh:
            self._appearing = False      # the frame after the trigger: the mark appears
            sound = self._cfg().rollback.limit_sound
            if sound is not None and self.play is not None:
                self.play(sound)
        # The mark: held, then leaving (a cut under reduced motion), then gone.
        t = self.t
        if t >= HOLD_S + FADE_S - _EPS or (reduce and t >= HOLD_S - _EPS):
            self.end()
            return
        self.opacity = 1.0 if t < HOLD_S else max(0.0, 1.0 - (t - HOLD_S) / FADE_S)
        self.visible = not self._appearing
        self._update_bump(dt, reduce)

    def _update_bump(self, dt: float, reduce: bool) -> None:
        textbox = self.textbox
        height = self._cfg().rollback.bump_height
        if reduce or height <= 0 or self._anchor is not None or textbox is None:
            self._want_bump = False
            self._stop_bump()
            return
        if self.bump_t is not None:
            self.bump_t += dt
            if self.bump_t >= BUMP_UP_S + BUMP_DOWN_S - _EPS:
                self._stop_bump()        # done: another may start from this frame
        want, self._want_bump = self._want_bump, False
        if want and self.bump_t is None and textbox.box_shown:
            self.bump_t = 0.0
        b = self.bump_t
        if b is None:
            return
        rise = ease_in_out(b / BUMP_UP_S) if b < BUMP_UP_S \
            else 1.0 - ease_in_out((b - BUMP_UP_S) / BUMP_DOWN_S)
        dy = -height * rise
        if dy != self.dy:
            self.dy = dy
            textbox.set_bump(dy)

    # -- drawing (the shell's draw_layer, only while the game isn't covered) --

    def anchor(self) -> tuple[float, float] | None:
        """The mark's center now (bump included), or None with no anchor."""
        if self._anchor is not None:
            return self._anchor()
        if self.textbox is None:
            return None
        x, y = self.textbox.cue_anchor()
        return x, y + self.dy

    def draw(self, canvas: "Canvas") -> None:
        if not (self.active and self.visible) or self.opacity <= 0.0:
            return
        point = self.anchor()
        if point is None:
            return
        alpha = max(0, min(255, round(255 * self.opacity)))
        image = self.theme.frames.get("rollback.mark") if self.theme is not None else None
        if image is not None and not image.is_placeholder:
            canvas.draw_image(image, point, anchor="center", alpha=alpha)
            return
        w, h = MARK_SIZE
        rect = canvas.rect_to_px((point[0] - w / 2, point[1] - h / 2, w, h))
        if rect.width <= 0 or rect.height <= 0 or canvas.surface is None:
            return
        surface = self.mark_surface(rect.size, canvas.scale)
        if alpha >= 255:
            canvas.surface.blit(surface, rect.topleft)
            return
        surface.set_alpha(alpha)
        try:
            canvas.surface.blit(surface, rect.topleft)
        finally:
            surface.set_alpha(None)

    def mark_surface(self, size: tuple[int, int], scale: float) -> pygame.Surface:
        """The drawn mark at ``size`` device pixels (``scale`` per canvas unit): the opaque
        pill (radius 14, border ``textbox.border_width``), a 20×3 bar, a 3 gap, and a 16×10
        up-triangle, the glyph 16 tall and centered. Cached for the last size and look."""
        cfg = self._cfg()
        mark = cfg.rollback.mark
        key = (size, scale, mark.fill_color, mark.border_color, mark.glyph_color,
               cfg.textbox.border_width)
        cached = self._surface
        if cached is not None and cached[0] == key:
            return cached[1]
        spec = FrameSpec(mark.fill_color, 1.0, mark.border_color, cfg.textbox.border_width,
                         MARK_RADIUS)
        surface = build_frame(spec, size, scale)
        w, h = MARK_SIZE
        top = (h - GLYPH_HEIGHT) / 2

        def px(v: float) -> int:
            return math.floor(v * scale + 0.5)

        bar_w, bar_h = BAR_SIZE
        bx = (w - bar_w) / 2
        bar = pygame.Rect(px(bx), px(top), px(bx + bar_w) - px(bx), px(top + bar_h) - px(top))
        surface.fill((*mark.glyph_color, 255), bar)
        tri_w, tri_h = TRIANGLE_SIZE
        tx, ty = (w - tri_w) / 2, top + bar_h + GLYPH_GAP
        tri = build_triangle((px(tx + tri_w) - px(tx), px(ty + tri_h) - px(ty)),
                             mark.glyph_color, direction="up")
        surface.blit(tri, (px(tx), px(ty)))
        self._surface = (key, surface)
        return surface


class RollbackKeys:
    """F14's ``InGameOverlay`` and say listener (module docstring). ``clock`` gives game
    time in seconds (the wheel accumulator's reset); by default the sum of the ``dt`` of
    every ``update``. ``shell`` (theme, assets, painter), ``marker`` (``[rollback]
    marker``), and ``skip_indicator`` (F15's ``indicator_right``, looked up when called)
    are the rewind tag's; with no ``shell`` no tag is drawn."""

    def __init__(self, story: RollbackStory, textbox: RollbackTextbox, *,
                 clock: Callable[[], float] | None = None,
                 cue: LimitCue | None = None, shell: TagShell | None = None,
                 marker: bool = True,
                 skip_indicator: Callable[[], float | None] | None = None) -> None:
        self.story = story
        self.textbox = textbox
        self.cue = cue if cue is not None else LimitCue()
        self.shell = shell
        self.marker = bool(marker)
        self.skip_indicator = skip_indicator
        self._tag_widths: dict[str, float] = {}
        self._clock = clock
        self._time = 0.0
        self.pending = 0                 # this frame's notches: back < 0 < forward
        self.accumulator = 0.0           # wheel units not yet a whole notch (signed)
        self._wheel_at: float | None = None
        self._down: set[tuple[int, int]] = set()    # (event type, key/button) held now
        self._refused: int | None = None # view.refused as the last update saw it

    def now(self) -> float:
        return self._clock() if self._clock is not None else self._time

    # -- input --

    def handle_event(self, event: UiEvent, *, box_shown: bool) -> bool:
        n = self._notches(event.raw)
        if n == 0 or not self.story.rollback_view().shown:
            return False
        textbox = self.textbox
        if textbox.hidden:
            textbox.set_hidden(False)    # PR-F14-18: the box and quick menu show first
        self.pending += n
        return True

    def request_back(self) -> None:
        """The quick menu's Back (a disabled entry gets no call): one back notch."""
        if self.story.rollback_view().shown:
            self.pending -= 1

    def _notches(self, raw: pygame.event.Event) -> int:
        kind = raw.type
        if kind == pygame.MOUSEWHEEL:
            return self._wheel(raw)
        if kind == pygame.KEYUP:
            self._down.discard((pygame.KEYDOWN, getattr(raw, "key", -1)))
            return 0
        if kind == pygame.CONTROLLERBUTTONUP:
            self._down.discard((pygame.CONTROLLERBUTTONDOWN, getattr(raw, "button", -1)))
            return 0
        if kind == pygame.KEYDOWN:
            key = getattr(raw, "key", -1)
            if key not in _KEYS or getattr(raw, "mod", 0) & _BLOCKING_MODS:
                return 0
            n = _KEYS[key]
        elif kind == pygame.CONTROLLERBUTTONDOWN:
            key = getattr(raw, "button", -1)
            if key not in _BUTTONS:
                return 0
            n = _BUTTONS[key]
        else:
            return 0
        held = (kind, key)
        if getattr(raw, "repeat", False) or held in self._down:
            return 0                     # OS key repeat: once per press
        self._down.add(held)
        return n

    def _wheel(self, raw: pygame.event.Event) -> int:
        y = getattr(raw, "precise_y", None)
        if y is None:
            y = getattr(raw, "y", 0)
        try:
            y = float(y)
        except (TypeError, ValueError):
            return 0
        if y != y or y in (float("inf"), float("-inf")) or y == 0.0:
            return 0
        now = self.now()
        acc = self.accumulator
        if (self._wheel_at is None or now - self._wheel_at > WHEEL_RESET_S + _EPS
                or acc * y < 0):
            acc = 0.0                    # a pause or a change of direction starts over
        self._wheel_at = now
        acc += y
        whole = int((abs(acc) + _EPS) // TOUCH_UNITS_PER_STEP)
        sign = 1 if acc > 0 else -1
        self.accumulator = acc - sign * whole * TOUCH_UNITS_PER_STEP
        return -sign * whole             # wheel up (positive) is back

    # -- per frame --

    def update(self, dt: float, *, frozen: bool) -> None:
        self._time += dt
        if frozen:
            self._clear()
            return
        if self.textbox.hidden:
            self.cue.end()               # UI-F14-06: hide (H) ends the cue
        story = self.story
        view = story.rollback_view()
        seen, self._refused = self._refused, view.refused
        if seen is not None and view.refused > seen:
            self.cue.trigger()           # I-2: a back the runtime refused, seen a frame later
        pending, self.pending = self.pending, 0
        if pending < 0:
            want = -pending
            ok = min(want, view.back_room)
            if ok:
                story.post(StepBack(ok))
            if ok < want:
                self.cue.trigger()
        elif pending > 0 and view.ahead:
            story.post(StepForward(min(pending, view.ahead)))
            self.cue.end()

    def on_say(self, cmd: Say) -> None:
        """A new line (a line-changing advance or a landing) ends the cue."""
        self.cue.end()

    def reset(self) -> None:
        """The shell's in-game reset (New Game, the title, a load): nothing pending."""
        self._clear()
        self._refused = None

    def _clear(self) -> None:
        self.pending = 0
        self.accumulator = 0.0
        self._wheel_at = None
        self._down.clear()
        self.cue.end()

    # -- the rewind tag (UI-F14-09; layer 4, captured like F15's pill, I-9) --

    def tag_box(self, ahead: int) -> Box | None:
        """The tag's pill for ``ahead`` steps, or None when it isn't drawn: no shell,
        ``[rollback] marker = false``, hidden mode, or at the newest step. At (24, 24), or 8
        right of F15's pill while that shows."""
        shell = self.shell
        if shell is None or not self.marker or ahead <= 0 or self.textbox.hidden:
            return None
        q = shell.theme.cfg.quick_menu
        text = str(ahead)
        width = self._tag_widths.get(text)
        if width is None:
            number = measure_with(shell.assets, shell.theme.font(q.text_size))(text, q.text_size)
            width = self._tag_widths[text] = (TAG_PAD + TAG_GLYPH_W + TAG_NUMBER_GAP + number
                                              + TAG_PAD)
        right = self.skip_indicator() if self.skip_indicator is not None else None
        x = TAG_TOPLEFT[0] if right is None else right + TAG_GAP
        return Box(x, TAG_TOPLEFT[1], width, q.text_size + TAG_EXTRA_H)

    def draw(self, canvas: "Canvas", *, box_shown: bool) -> None:
        ahead = self.story.rollback_view().ahead
        box = self.tag_box(ahead)
        if box is None:
            return
        shell = self.shell
        assert shell is not None
        q = shell.theme.cfg.quick_menu
        painter = shell.painter
        painter.bind(canvas)
        painter.shape(box, FrameSpec(q.fill_color, q.fill_opacity,
                                     border_color=q.on.border_color,
                                     border_width=q.on.border_width,
                                     corner_radius=q.corner_radius))
        color = q.focused.text_color
        _, cy = box.center
        tw, th = TAG_TRIANGLE
        x = box.x + TAG_PAD
        for dx in (0, tw + TAG_TRIANGLE_GAP):
            painter.triangle(Box(x + dx, cy - th / 2, tw, th), color, direction="left")
        canvas.draw_text(str(ahead), shell.theme.font(q.text_size), color,
                         (x + TAG_GLYPH_W + TAG_NUMBER_GAP, cy), anchor="midleft")


__all__ = ["BUMP_DOWN_S", "BUMP_UP_S", "FADE_S", "HOLD_S", "MARK_SIZE", "TOUCH_UNITS_PER_STEP",
           "WHEEL_RESET_S", "CueTextbox", "LimitCue", "RollbackKeys", "RollbackStory",
           "RollbackTextbox", "TagShell"]

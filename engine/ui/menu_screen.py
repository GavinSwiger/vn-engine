"""``MenuScreen``: the base of every F10 menu (focus, input, fades, backdrop, sounds, cursor).

Why this module exists: the title, game menu, confirm dialog, and sampler all take the same
inputs the same way (F10 ``04`` §7.3, ui-system §9) and open and close with the same fade
(§7.5). The rules live here once:

- **Input** (§7.3). Mouse, keys, and gamepad share one ``FocusScope``. Hover focuses; a mouse
  focus clears when the pointer leaves, a key focus stays. A click acts on the button-1
  release over the widget that took the press, so the click that opened a screen never acts
  in it. ``NavReader`` turns keys and buttons into ``Nav``; the first navigation input with
  nothing focused focuses the default without acting. Back plays ``ui.back_sound`` and calls
  ``back()``. A held direction on a slider, list, or grid repeats (``RepeatClock``). Mouse
  input no widget took (a press on no focusable widget, a wheel the widget under the
  pointer didn't use) goes to ``unused_mouse`` (F16 conflict 5; the game menu's pages). A
  group with a ``clip`` draws clipped to it (F16 conflict 4).
- **Text scale** (F16 Text size): a menu whose painter's ``text_scale()`` changed since its
  last layout calls ``rebuild()`` at its next update while top, so menus follow at once.
- **Sounds** (UI-F10-14) go through the shell's ``play_ui``: ``button.focus_sound`` on each
  focus change (not when focus clears or for the first focus at open), ``activate_sound`` on
  each activation, ``ui.back_sound`` on Back.
- **Fades** (§7.5). OPENING → OPEN → CLOSING → removed, over ``ui.fade_ms`` of game time while
  top, from the frame after the input; 0 under reduced motion. Any input finishes an opening
  fade and then acts; the first input during a closing fade finishes it and goes to the
  screen below. A fading screen with a backdrop draws "fade B": the scene opaque, the dim at
  ``opacity × a`` (two constant fills), then its content composed once into one panel-sized
  layer blitted at alpha ``a``. The layer is a view-owned buffer outside the memory budget
  (07 I-11), re-composed when a look changes and freed when the fade ends. Nothing
  viewport-sized ever gets ``set_alpha``.
- **Back to the opener.** ``push_child`` remembers the focused widget; when the child goes,
  it is focused again, drawn focused only if the closing input was a key or button.
- **Cursor** (PR-F10-13, I-13): hidden on a navigation input, shown on mouse motion and when
  the last ``MenuScreen`` leaves the stack.

The shell (``GameShell``, F10 step 6; a test shell before it) supplies the stack, assets,
theme, words, painter, dev flag, reduced motion, cursor, and ``play_ui`` (``MenuShell``).
"""

from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING, Final, Protocol

import pygame

from engine.render.canvas import Canvas
from engine.render.frames import dim
from engine.ui.backdrop import CapturedBackdrop
from engine.ui.focus import Box, FocusScope
from engine.ui.input import UiEvent
from engine.ui.nav import DIRECTIONS, PAGE_KEYS, InputKind, Nav, NavReader, RepeatClock
from engine.ui.screen import Screen, ScreenStack
from engine.ui.widgets import Look, Widget, clipped

if TYPE_CHECKING:
    from engine.render.assets import AssetManager
    from engine.ui.paint import Painter
    from engine.ui.theme import UiTheme, Words

PRESS_LOOK_S: Final = 0.1         # the pressed look after a key or button activation
_EPSILON: Final = 1e-9
_MOUSE_EVENTS = frozenset({pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                           pygame.MOUSEWHEEL})
# Events that count as input for finishing a fade (motion does not).
_INPUT_EVENTS = frozenset({pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                           pygame.MOUSEWHEEL, pygame.CONTROLLERBUTTONDOWN})


class Phase(Enum):
    OPENING = "opening"
    OPEN = "open"
    CLOSING = "closing"


class CursorKeeper:
    """Shows or hides the mouse pointer, calling pygame only on a change (PR-F10-13)."""

    def __init__(self, set_visible: Callable[[bool], object] | None = None) -> None:
        self._set_visible = set_visible if set_visible is not None else pygame.mouse.set_visible
        self.visible = True

    def show(self, visible: bool) -> None:
        if visible != self.visible:
            self.visible = visible
            self._set_visible(visible)


class MenuShell(Protocol):
    """What a ``MenuScreen`` needs from the shell (``GameShell``, or a test shell)."""

    stack: ScreenStack
    assets: "AssetManager"
    theme: "UiTheme"
    words: "Words"
    painter: "Painter"
    dev: bool
    reduce_motion: bool
    cursor: CursorKeeper

    def play_ui(self, token: str | None) -> None: ...


class _LayerCanvas(Canvas):
    """A canvas drawing onto ``layer``, whose top-left is device pixel ``origin`` of the real
    canvas: same scale and quality, positions shifted, so a screen draws its content into the
    fade layer with the same calls."""

    def __init__(self, base: Canvas, layer: pygame.Surface, origin: tuple[int, int]) -> None:
        super().__init__(base.assets)
        self.size = base.size
        self.viewport = base.viewport
        self.quality = base.quality
        self.final_scale = base.final_scale
        self.surface = layer
        self._origin = origin

    def px(self, x: float, y: float) -> tuple[int, int]:
        px, py = super().px(x, y)
        return px - self._origin[0], py - self._origin[1]


class MenuScreen(Screen):
    """The shared base: never ``in_game``; opaque once its backdrop is captured, or always
    when ``solid`` (it paints the whole canvas itself)."""

    in_game = False
    solid = False

    def __init__(self, shell: MenuShell, *, by: InputKind, fade: bool = True,
                 backdrop: CapturedBackdrop | None = None) -> None:
        self.shell = shell
        self.backdrop = backdrop
        self.opened_by = by
        self.scope = FocusScope(on_change=self._focus_changed)
        self.reader = NavReader()
        self.repeat = RepeatClock()
        fade_ms = 0 if (not fade or self.solid or shell.reduce_motion) \
            else shell.theme.cfg.ui.fade_ms
        self.fade_s = fade_ms / 1000.0
        self.phase = Phase.OPENING if self.fade_s > 0 else Phase.OPEN
        self.t = 0.0 if self.fade_s > 0 else 1.0
        self.pressed: Widget | None = None            # the widget a button-1 press is on
        self.pointer: tuple[int, int] | None = shell.stack.pointer
        self.input_kind = by                          # the kind of the event being handled
        self.revision = 0                             # bump to re-compose the fade layer
        self._fresh = True                            # skip one update after a phase starts
        self._key_press: Widget | None = None
        self._key_press_left = 0.0
        self._key_press_fresh = False
        self._then: Callable[[], None] | None = None
        self._closed_by: InputKind | None = None
        self._removed = False
        self._parent: MenuScreen | None = None
        self._opener: Widget | None = None
        self._layer: pygame.Surface | None = None
        self._layer_key: tuple | None = None
        self._page_press = False                      # unused_mouse took the button-1 press
        self.built = False
        self.build()
        self.built = True
        self._built_scale = self.painter.text_scale()
        if by is InputKind.KEYS:
            target = self.scope.default()
            if target is not None:
                self.scope.focus(target, InputKind.KEYS, sound=False)

    # -- for subclasses --

    @property
    def painter(self) -> "Painter":
        return self.shell.painter

    def build(self) -> None:
        """Lay out the widgets and set the scope's groups and default (again on a text-scale
        change)."""

    def draw_content(self, p: "Painter") -> None:
        """Draw panels, text, and widgets (on the canvas or into the fade layer)."""
        self.draw_widgets(p)

    def layer_box(self) -> Box:
        """The canvas box the content occupies (the fade layer's size): every widget's box."""
        boxes = [w.box for w in self.scope.widgets()]
        if not boxes:
            return Box(0, 0, 0, 0)
        x0 = min(b.x for b in boxes)
        y0 = min(b.y for b in boxes)
        return Box(x0, y0, max(b.right for b in boxes) - x0, max(b.bottom for b in boxes) - y0)

    def back(self) -> None:
        """BACK (Esc, right click, east): close by default."""
        self.close()

    def on_start(self) -> None:
        """Gamepad Start (the game menu closes; elsewhere nothing)."""

    def on_sampler(self) -> None:
        """Shift+F3 in dev runs (the title and game menu open the sampler)."""

    def on_update(self, dt: float) -> None:
        """Per-frame work while top and not closing."""

    def unused_nav(self, nav: Nav) -> bool:
        """A navigation press the focus scope didn't use (the game menu passes Page Up /
        Page Down to its page, F16 conflict 5). True: used. A used Page Up / Page Down
        repeats while held, through this method again."""
        return False

    def unused_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        """Mouse input no widget took (F16 conflict 5; the game menu passes it to its page
        inside the body slot): ``"down"``, a button-1 press on no focusable widget (True: the
        press is taken, and its ``"drag"`` and ``"up"`` come here too); ``"wheel"``, the
        wheel the widget under the pointer didn't use."""
        return False

    def rebuild(self) -> None:
        """Lay out again (``build``): the text scale changed (F16 Text size)."""
        self.build()

    # -- state --

    @property
    def opaque(self) -> bool:                                     # type: ignore[override]
        if self.backdrop is not None:
            return self.backdrop.ready and not self.backdrop.live
        return self.solid

    @property
    def alpha(self) -> float:
        """Fade progress as drawn: rising while opening, falling while closing."""
        if self.phase is Phase.OPENING:
            return min(1.0, self.t)
        if self.phase is Phase.CLOSING:
            return max(0.0, 1.0 - self.t)
        return 1.0

    def is_top(self) -> bool:
        return self.shell.stack.top is self

    def look_for(self, w: Widget) -> Look:
        """How ``w`` looks this frame: focused while it has visible focus; pressed while a
        mouse press on it is held over it, or for 100 ms after a key activation (top only)."""
        focused = self.scope.focused is w and self.scope.visible
        pressed = False
        if self.is_top():
            pressed = w is self._key_press or (
                w is self.pressed and self.pointer is not None and w.box.contains(self.pointer))
        return w.look(focused=focused, pressed=pressed)

    def draw_widgets(self, p: "Painter") -> None:
        """Every member widget; a group with a ``clip`` (F16's column) draws only its
        members that reach into the clip box, clipped to it."""
        for group in self.scope.groups:
            clip = group.clip
            if clip is None:
                for w in group.widgets:
                    w.draw(p, self.look_for(w))
                continue
            with clipped(p, clip):
                for w in group.widgets:
                    box = w.box
                    if box.bottom > clip.y and box.y < clip.bottom:
                        w.draw(p, self.look_for(w))

    # -- opening and closing --

    def close(self, *, then: Callable[[], None] | None = None) -> None:
        """Fade out, then leave the stack and run ``then``. Input during the fade finishes it."""
        if self.phase is Phase.CLOSING or self._removed:
            return
        self._then = then
        self._closed_by = self.input_kind
        if self.fade_s <= 0:
            self._finish_close()
            return
        a = self.alpha
        self.phase = Phase.CLOSING
        self.t = 1.0 - a
        self._fresh = True
        self._layer = None
        if self.backdrop is not None and self.backdrop.scene is None:
            self.backdrop.go_live()

    def push_child(self, child: "MenuScreen") -> None:
        """Push ``child``; when it goes, focus returns to the widget focused now."""
        self._opener = self.scope.focused
        child._parent = self
        self.shell.stack.push(child)

    def _finish_open(self) -> None:
        self.phase = Phase.OPEN
        self.t = 1.0
        self._layer = None
        if self.backdrop is not None:
            self.backdrop.drop_scene()

    def _finish_close(self) -> None:
        if self._removed:
            return
        self._removed = True
        self.phase = Phase.CLOSING
        self.t = 1.0
        self._remove_from_stack()
        then, self._then = self._then, None
        if then is not None:
            then()

    def _remove_from_stack(self) -> None:
        self.shell.stack.remove(self)

    def on_exit(self) -> None:
        self.repeat.stop()
        self.reader.reset()
        self.pressed = None
        self._page_press = False
        self._layer = None
        if self.backdrop is not None:
            self.backdrop.release()
        if self._parent is not None:
            self._parent._child_closed(self)
        if not any(isinstance(s, MenuScreen) for s in self.shell.stack):
            self.shell.cursor.show(True)

    def _child_closed(self, child: "MenuScreen") -> None:
        opener, self._opener = self._opener, None
        by = child._closed_by or InputKind.KEYS
        if opener is not None and self.scope.can_focus(opener):
            self.scope.focus(opener, by, sound=False, visible=by is InputKind.KEYS)

    # -- events --

    def handle_event(self, event: UiEvent) -> bool:
        """Every event is consumed: nothing reaches a screen below a menu (PR-F10-09)."""
        nav = self.reader.read(event, dev=self.shell.dev)
        released = self.reader.released(event)
        kind = event.type
        mouse = kind in _MOUSE_EVENTS
        self.input_kind = InputKind.MOUSE if mouse else InputKind.KEYS
        if event.canvas_pos is not None:
            self.pointer = event.canvas_pos if event.in_canvas else None
        is_input = nav is not None or kind in _INPUT_EVENTS
        if self.phase is Phase.CLOSING:
            if is_input and not self._removed:
                self._finish_close()
                self.shell.stack.handle_event(event)
            return True
        if self.phase is Phase.OPENING and is_input:
            self._finish_open()
        if kind == pygame.MOUSEMOTION:
            self.shell.cursor.show(True)
        if released is not None and released is self.repeat.nav:
            self.repeat.stop()
        if kind in (pygame.WINDOWFOCUSLOST, pygame.CONTROLLERDEVICEREMOVED):
            self.repeat.stop()                        # AC-F10-08, AC-F10-61
        if nav is not None:
            if not mouse:
                self.shell.cursor.show(False)
            self._on_nav(nav)
        elif kind == pygame.MOUSEMOTION:
            self._on_motion()
        elif kind == pygame.MOUSEBUTTONDOWN and getattr(event.raw, "button", 0) == 1:
            if event.in_canvas and event.canvas_pos is not None:
                self._on_down(event.canvas_pos)
        elif kind == pygame.MOUSEBUTTONUP and getattr(event.raw, "button", 0) == 1:
            self._on_up(event.canvas_pos if event.in_canvas else None)
        elif kind == pygame.MOUSEWHEEL:
            self._on_wheel(event)
        return True

    def _on_nav(self, nav: Nav) -> None:
        cfg = self.shell.theme.cfg
        if nav is Nav.BACK:
            self.shell.play_ui(cfg.ui.back_sound)
            self.back()
            return
        if nav is Nav.START:
            self.on_start()
            return
        if nav is Nav.SAMPLER:
            self.on_sampler()
            return
        scope = self.scope
        scope.refresh()
        target = scope.focused
        visible = target is not None and scope.visible
        will_activate = nav is Nav.ACTIVATE and visible
        used = scope.press(nav)
        if not used and self.unused_nav(nav):
            if nav in PAGE_KEYS:
                self.repeat.start(nav)
            return
        if will_activate and used:
            self._key_press = target
            self._key_press_left = PRESS_LOOK_S
            self._key_press_fresh = True
            self.shell.play_ui(self.activation_sound())
        elif used and visible and nav in DIRECTIONS and target is not None \
                and target.repeatable and scope.focused is target:
            self.repeat.start(nav)

    def _repeat_once(self, nav: Nav) -> bool:
        """One repeat of a held navigation: a page key goes to ``unused_nav``; a direction
        moves (the focused widget must be repeatable). False stops the repeat."""
        if nav in PAGE_KEYS:
            return self.unused_nav(nav)
        focused = self.scope.focused
        return focused is not None and focused.repeatable and self.scope.move(nav)

    def _on_motion(self) -> None:
        pos = self.pointer
        scope = self.scope
        if self._page_press:
            if pos is not None:
                self.unused_mouse("drag", pos)
            return                                   # a held page press keeps the focus
        if self.pressed is not None:
            if pos is not None:
                self.pressed.on_mouse("drag", pos)
            return                                   # a held press keeps the focus
        w = scope.widget_at(pos) if pos is not None else None
        if w is not None and scope.can_focus(w):
            if w is not scope.focused or not scope.visible:
                scope.focus(w, InputKind.MOUSE)
            w.on_mouse("hover", pos)
        elif scope.source is InputKind.MOUSE and scope.focused is not None:
            scope.clear()

    def _on_down(self, pos: tuple[int, int]) -> None:
        w = self.scope.widget_at(pos)
        if w is None or not self.scope.can_focus(w):
            self._page_press = self.unused_mouse("down", pos)
            return
        self.pressed = w
        self.scope.focus(w, InputKind.MOUSE)
        w.on_mouse("down", pos)

    def _on_up(self, pos: tuple[int, int] | None) -> None:
        at = pos if pos is not None else (-1.0e9, -1.0e9)
        if self._page_press:
            self._page_press = False
            self.unused_mouse("up", at)
            return
        w, self.pressed = self.pressed, None
        if w is None:
            return                                    # no press in this screen
        w.on_mouse("up", at)
        if w.accepts_click(at) and pos is not None:
            w.activate()
            self.shell.play_ui(self.activation_sound())

    def activation_sound(self) -> str | None:
        """The sound played after a widget's activation: ``button.activate_sound``. A
        screen that ignored the press returns None (F30's ``UsernameQuestion``)."""
        return self.shell.theme.cfg.button.activate_sound

    def _on_wheel(self, event: UiEvent) -> None:
        pos = event.canvas_pos if event.in_canvas else None
        if pos is None:
            pos = self.shell.stack.pointer
        if pos is None:
            return
        notches = int(getattr(event.raw, "y", 0))
        w = self.scope.widget_at(pos)
        if w is not None and w.enabled() and w.on_mouse("wheel", pos, notches=notches):
            return
        self.unused_mouse("wheel", pos, notches=notches)

    def _focus_changed(self, w: Widget) -> None:
        if self.repeat.nav is not None and not w.repeatable:
            self.repeat.stop()
        self.shell.play_ui(self.shell.theme.cfg.button.focus_sound)

    # -- frame --

    def update(self, dt: float, *, is_top: bool) -> None:
        if not is_top:
            self.repeat.stop()
            self._key_press = None                    # a covered menu shows no pressed look
            return
        fresh, self._fresh = self._fresh, False
        if self.phase is not Phase.OPEN and not fresh and self.fade_s > 0:
            self.t += dt / self.fade_s
        if self.phase is Phase.OPENING and self.t >= 1.0 - _EPSILON:
            self._finish_open()
        elif self.phase is Phase.CLOSING:
            if self.t >= 1.0 - _EPSILON:
                self._finish_close()
            return
        if self._key_press is not None:
            if self._key_press_fresh:
                self._key_press_fresh = False
            else:
                self._key_press_left -= dt
                if self._key_press_left <= _EPSILON:
                    self._key_press = None
        scale = self.painter.text_scale()
        if scale != self._built_scale:                # F16 Text size: menus at once
            self._built_scale = scale
            self.rebuild()
        nav = self.repeat.nav
        if nav is not None:
            for _ in range(self.repeat.tick(dt)):
                if not self._repeat_once(nav):
                    self.repeat.stop()
                    break
        self.scope.refresh()
        self.on_update(dt)

    def draw(self, canvas: Canvas) -> None:
        assert self.built, "a MenuScreen must build() before it is drawn"
        p = self.painter
        p.bind(canvas)
        a = self.alpha
        bd = self.backdrop
        if a >= 1.0:
            self._layer = None
            if bd is not None and (bd.capture(canvas, need_scene=False) or bd.live):
                bd.draw(canvas, 1.0)
            self.draw_content(p)
            return
        surface = canvas.surface
        assert surface is not None
        base: pygame.Surface = surface
        dim_base = False
        current = False
        if bd is not None:
            if bd.live:
                dim_base = True
            else:
                current = bd.capture(canvas, need_scene=True)
                if current and bd.dimmed is not None:
                    base = bd.dimmed
        layer_rect = self._compose(canvas, p, base, dim_base)
        if bd is not None and (current or bd.live):
            bd.draw(canvas, a)
        if layer_rect is not None and self._layer is not None:
            self._layer.set_alpha(round(255 * a))
            surface.blit(self._layer, layer_rect.topleft)

    def _compose(self, canvas: Canvas, p: "Painter", base: pygame.Surface,
                 dim_base: bool) -> pygame.Rect | None:
        """The fade layer: the fully dimmed backdrop under the content box with the content
        drawn on it, composed once per look (an opaque buffer blitted at alpha ``a``)."""
        surface = canvas.surface
        assert surface is not None
        box = self.layer_box()
        rect = canvas.rect_to_px((box.x, box.y, box.w, box.h)).clip(surface.get_rect())
        if rect.width <= 0 or rect.height <= 0:
            return None
        looks = tuple(self.look_for(w) for w in self.scope.widgets())
        key = (rect.topleft, rect.size, canvas.quality, self.revision, looks)
        if self._layer is not None and self._layer_key == key:
            return rect
        layer = base.subsurface(rect).copy()
        if dim_base and self.backdrop is not None:
            dim(layer, self.backdrop.color, self.backdrop.opacity)
        p.bind(_LayerCanvas(canvas, layer, rect.topleft))
        try:
            self.draw_content(p)
        finally:
            p.bind(canvas)
        self._layer, self._layer_key = layer, key
        return rect


__all__ = ["PRESS_LOOK_S", "CursorKeeper", "MenuScreen", "MenuShell", "Phase"]

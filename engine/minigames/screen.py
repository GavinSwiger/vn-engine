"""``MinigameScreen``: the minigame's place in the stack, its input routing, and its frame
(F23 ``03`` "States", "Interaction", "Motion and timing"; ``04`` §7.4, §7.6).

Why this module exists: a running minigame must behave like part of the game picture (the
story pumps under it, Esc, F5/F9, and the wheel reach the in-game overlays, a menu covers it)
while every other input goes to the plugin. The screen is ``in_game`` and opaque, sits
directly above the stage and the say window (``ScreenStack.insert_above_in_game``), and
decides per input, by 04 §7.6's table:

- **Fades** (OPENING, CLOSING): Esc, Start, F5, F9 (no Ctrl/Alt/Meta) snap the fade and then
  act (False); Shift+F8 (dev, fade-in only) snaps and ends with the test outcome; anything
  else is dropped (True, never "used").
- **RUNNING**: Esc, Start, F5, F9 → False (F10's ``GameMenuKeys``, F11's ``QuickKeys``);
  Shift+F8 → dev: the test outcome; release: nothing (True, never delivered). Everything else
  is **offered**: ``plugin.handle_event(PluginEvent(ui, nav))`` first (``nav`` from a
  ``NavReader`` with the ``"shoulders"`` extra, Esc removed, Backspace as Back), then, if it
  returned False, F10 routing to ``ctx.scope``'s widgets as ``MenuScreen`` does (navigation,
  hover focus and its clearing, button-1 press and release, the wheel to the enabled widget
  under the pointer). Unused: right click and east → False (the game menu), Backspace →
  True (nothing), the wheel, Page Up/Down, and LB/RB → False (F14's ``RollbackKeys``), the
  rest → True (H, A, Ctrl, Tab never reach F05/F15).
- **Used** (04 §7.5): a press-type input (key, mouse button, controller button, wheel notch,
  stick step) the plugin or a widget consumed posts ``MinigameUsed`` once; motion and
  releases never count.
- **Update**: the fade's clock while top; RUNNING: ``plugin.update(dt)`` only when top and
  the window has focus; the settings are polled each frame (``settings_changed`` and a new
  ``layout(area)`` on a change). Under any other screen nothing runs (pause, UI-F23-11).
- **Draw**: OPENING dissolves from the "from" picture to the opening picture; RUNNING draws
  the backdrop (the dimmed frozen stage, ``minigame.background_image`` scaled to cover, or
  the gradient), ``plugin.draw``, the scope's widgets (A4, each with its look), then the
  heading and hint (UI-F23-03); CLOSING draws the last frame once, then dissolves it over the
  live in-game screens below (not opaque).
- **W162** (dev): a RUNNING frame's ``plugin.update`` and ``plugin.draw`` are timed with
  ``perf_counter``; over 8 ms together, the host warns once per minigame name.
"""

from time import perf_counter
from typing import TYPE_CHECKING, Final

import pygame

from engine.core.constants import CANVAS_SIZE
from engine.minigames.api import PluginEvent
from engine.minigames.host import MinigameHost, Phase, PluginFailed, Session
from engine.ui.input import UiEvent
from engine.ui.layouts import pitch
from engine.ui.nav import DIRECTIONS, InputKind, Nav, NavReader, RepeatClock
from engine.ui.screen import Screen
from engine.ui.widgets import Look, Widget, clipped

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.ui.paint import Painter

PRESS_LOOK_S: Final = 0.1
CANVAS_W, CANVAS_H = CANVAS_SIZE
HEADING_PAD_X: Final = 20
HINT_PAD_Y: Final = 12
_BLOCKING_MODS: Final = pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META
_SNAP_KEYS: Final = frozenset({pygame.K_ESCAPE, pygame.K_F5, pygame.K_F9})
_PRESSES: Final = frozenset({pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN,
                             pygame.CONTROLLERBUTTONDOWN, pygame.MOUSEWHEEL})
_MOUSE: Final = frozenset({pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                           pygame.MOUSEWHEEL})
_ROLLBACK_KEYS: Final = frozenset({pygame.K_PAGEUP, pygame.K_PAGEDOWN})
_SHOULDERS: Final = frozenset({pygame.CONTROLLER_BUTTON_LEFTSHOULDER,
                               pygame.CONTROLLER_BUTTON_RIGHTSHOULDER})


def _mods(raw: pygame.event.Event) -> int:
    return int(getattr(raw, "mod", 0))


def is_snap_key(raw: pygame.event.Event) -> bool:
    """Esc, F5, F9 (no Ctrl, Alt, Meta), or gamepad Start: they act on the in-game screens."""
    if raw.type == pygame.KEYDOWN:
        return raw.key in _SNAP_KEYS and not _mods(raw) & _BLOCKING_MODS
    if raw.type == pygame.CONTROLLERBUTTONDOWN:
        return getattr(raw, "button", -1) == pygame.CONTROLLER_BUTTON_START
    return False


def is_dev_end(raw: pygame.event.Event) -> bool:
    """Shift+F8 (Shift only)."""
    if raw.type != pygame.KEYDOWN or raw.key != pygame.K_F8:
        return False
    mods = _mods(raw)
    return bool(mods & pygame.KMOD_SHIFT) and not mods & (_BLOCKING_MODS | pygame.KMOD_GUI)


def _is_rollback_input(raw: pygame.event.Event) -> bool:
    kind = raw.type
    if kind == pygame.MOUSEWHEEL:
        return True
    if kind == pygame.KEYDOWN:
        return raw.key in _ROLLBACK_KEYS
    if kind == pygame.CONTROLLERBUTTONDOWN:
        return getattr(raw, "button", -1) in _SHOULDERS
    return False


class MinigameScreen(Screen):
    """One session's screen (module docstring)."""

    in_game = True
    holds_notices = False

    def __init__(self, host: MinigameHost, session: Session) -> None:
        self.host = host
        self.s = session
        self.reader = NavReader(extras=frozenset({"shoulders"}))
        self.repeat = RepeatClock()
        self.pressed: Widget | None = None
        self.pointer: tuple[int, int] | None = None
        self._key_press: Widget | None = None
        self._key_press_left = 0.0
        self._cost = 0.0                      # this frame's plugin update time (W162)

    @property
    def opaque(self) -> bool:                                       # type: ignore[override]
        s = self.s
        return not (s.phase is Phase.CLOSING and s.last is not None)

    def _live(self) -> bool:
        return self.host.session is self.s

    def on_exit(self) -> None:
        """Taken out of the stack by someone else (a load, the title, the error screen):
        the session is abandoned."""
        self.repeat.stop()
        self.reader.reset()
        if self._live() and self.s.phase is not Phase.CLOSED:
            self.host.abandon()

    # -- input (04 §7.6) --

    def nav_of(self, event: UiEvent) -> Nav | None:
        """F10's ``Nav`` for the plugin: shoulders as Page keys, Esc never, Backspace Back."""
        raw = event.raw
        if raw.type == pygame.KEYDOWN:
            if raw.key == pygame.K_ESCAPE:
                self.reader.read(event, dev=False)                 # keep it interpreted once
                return None
            if raw.key == pygame.K_BACKSPACE and not _mods(raw) & (_BLOCKING_MODS
                                                                   | pygame.KMOD_GUI):
                return Nav.BACK
        return self.reader.read(event, dev=False)

    def handle_event(self, event: UiEvent) -> bool:
        s = self.s
        if not self._live():
            return False
        host = self.host
        raw = event.raw
        if event.canvas_pos is not None:
            self.pointer = event.canvas_pos if event.in_canvas else None
        if s.phase in (Phase.OPENING, Phase.CLOSING):
            if is_dev_end(raw):
                if s.phase is Phase.OPENING and host.ports.dev:
                    host.snap(s)
                    self._dev_end()
                return True
            if is_snap_key(raw):
                host.snap(s)
                return False
            return True
        if is_snap_key(raw):
            return False
        if is_dev_end(raw):
            if host.ports.dev:
                self._dev_end()
            return True
        kind = raw.type
        if kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                    pygame.MOUSEWHEEL) and not event.in_canvas:
            return True                                # the letterbox: ignored
        nav = self.nav_of(event)
        released = self.reader.released(event)
        if released is not None and released is self.repeat.nav:
            self.repeat.stop()
        press = kind in _PRESSES or (kind == pygame.CONTROLLERAXISMOTION and nav is not None)
        if press:
            s.last_kind = InputKind.MOUSE if kind in _MOUSE else InputKind.KEYS
        try:
            used = host.call(s.plugin.handle_event, PluginEvent(event, nav), convert=bool)
            if not used and self._live():
                used = bool(host.call(self._route, event, nav))
        except PluginFailed:
            return True
        if used and press and self._live():
            host.note_used(s)
        if used:
            return True
        if nav is Nav.BACK:
            return kind == pygame.KEYDOWN            # Backspace: nothing; right click, east: menu
        if _is_rollback_input(raw):
            return False
        return True

    def _dev_end(self) -> None:
        try:
            self.host.dev_end(self.s)
        except PluginFailed:
            pass

    # -- F10 routing to the scope's widgets (as MenuScreen), inside the plugin's call --

    def _route(self, event: UiEvent, nav: Nav | None) -> bool:
        kind = event.type
        if nav is not None:
            if nav in (Nav.BACK, Nav.START, Nav.SAMPLER):
                return False
            return self._on_nav(nav)
        if kind == pygame.MOUSEMOTION:
            self._on_motion()
            return False
        if kind == pygame.MOUSEBUTTONDOWN and getattr(event.raw, "button", 0) == 1:
            if event.in_canvas and event.canvas_pos is not None:
                return self._on_down(event.canvas_pos)
            return False
        if kind == pygame.MOUSEBUTTONUP and getattr(event.raw, "button", 0) == 1:
            self._on_up(event.canvas_pos if event.in_canvas else None)
            return False
        if kind == pygame.MOUSEWHEEL:
            return self._on_wheel(event)
        return False

    def _on_nav(self, nav: Nav) -> bool:
        shell = self.host.shell
        scope = self.s.scope
        scope.refresh()
        target = scope.focused
        visible = target is not None and scope.visible
        will_activate = nav is Nav.ACTIVATE and visible
        used = scope.press(nav)
        if will_activate and used:
            self._key_press = target
            self._key_press_left = PRESS_LOOK_S
            shell.play_ui(shell.theme.cfg.button.activate_sound)
        elif used and visible and nav in DIRECTIONS and target is not None \
                and target.repeatable and scope.focused is target:
            self.repeat.start(nav)
        return used

    def _on_motion(self) -> None:
        pos = self.pointer
        scope = self.s.scope
        if self.pressed is not None:
            if pos is not None:
                self.pressed.on_mouse("drag", pos)
            return
        w = scope.widget_at(pos) if pos is not None else None
        if w is not None and scope.can_focus(w):
            if w is not scope.focused or not scope.visible:
                scope.focus(w, InputKind.MOUSE)
            w.on_mouse("hover", pos)
        elif scope.source is InputKind.MOUSE and scope.focused is not None:
            scope.clear()

    def _on_down(self, pos: tuple[int, int]) -> bool:
        scope = self.s.scope
        w = scope.widget_at(pos)
        if w is None or not scope.can_focus(w):
            return False
        self.pressed = w
        scope.focus(w, InputKind.MOUSE)
        w.on_mouse("down", pos)
        return True

    def _on_up(self, pos: tuple[int, int] | None) -> None:
        at = pos if pos is not None else (-1.0e9, -1.0e9)
        w, self.pressed = self.pressed, None
        if w is None:
            return
        w.on_mouse("up", at)
        if w.accepts_click(at) and pos is not None:
            w.activate()
            shell = self.host.shell
            shell.play_ui(shell.theme.cfg.button.activate_sound)

    def _on_wheel(self, event: UiEvent) -> bool:
        pos = event.canvas_pos if event.in_canvas else None
        if pos is None:
            pos = self.pointer
        if pos is None:
            return False
        notches = int(getattr(event.raw, "y", 0))
        w = self.s.scope.widget_at(pos)
        return bool(w is not None and w.enabled() and w.on_mouse("wheel", pos, notches=notches))

    def _repeat_once(self, nav: Nav) -> bool:
        focused = self.s.scope.focused
        return focused is not None and focused.repeatable and self.s.scope.move(nav)

    # -- frame --

    def update(self, dt: float, *, is_top: bool) -> None:
        s = self.s
        if not self._live():
            return
        host = self.host
        if not is_top:
            self.repeat.stop()
            self._key_press = None
            return
        if s.phase in (Phase.OPENING, Phase.CLOSING):
            host.advance(s, dt)
            return
        if s.phase is not Phase.RUNNING or not host.ports.focused():
            return
        try:
            settings = host.player_settings()
            if settings != s.settings:
                rescaled = s.settings is None or settings.text_scale != s.settings.text_scale
                s.settings = settings
                if rescaled:
                    s.dirty = True
                host.call(s.plugin.settings_changed, settings)
            if not self._live():
                return
            began = perf_counter()
            host.call(s.plugin.update, dt)
            self._cost = perf_counter() - began
            if not self._live():
                return
            if self._key_press is not None:
                self._key_press_left -= dt
                if self._key_press_left <= 1e-9:
                    self._key_press = None
            nav = self.repeat.nav
            if nav is not None:
                for _ in range(self.repeat.tick(dt)):
                    if not host.call(self._repeat_once, nav):
                        self.repeat.stop()
                        break
            if self._live():
                s.scope.refresh()
        except PluginFailed:
            return

    def draw(self, canvas: "Canvas") -> None:
        s = self.s
        if not self._live():
            return
        host = self.host
        surface = canvas.surface
        assert surface is not None
        size = surface.get_size()
        if s.phase is Phase.OPENING:
            start, end = s.from_pic, s.opening
            if start is None or end is None or start.get_size() != size:
                host.snap(s)                           # a resize snaps the fade
            else:
                surface.blit(start, (0, 0))
                end.set_alpha(round(255 * max(0.0, min(1.0, s.t))))
                surface.blit(end, (0, 0))
                end.set_alpha(None)
                return
        if s.phase is Phase.CLOSING:
            last = s.last
            if last is not None and last.get_size() != size:
                host.end_close(s)
                return
            if last is None:
                self.draw_running(canvas)
                if self._live():
                    s.last = surface.copy()
                    host._hold(s, s.last)
                return
            last.set_alpha(round(255 * max(0.0, min(1.0, 1.0 - s.t))))
            surface.blit(last, (0, 0))
            last.set_alpha(None)
            return
        self.draw_running(canvas, timed=s.phase is Phase.RUNNING)

    def draw_running(self, canvas: "Canvas", *, timed: bool = False) -> None:
        """Backdrop, plugin, scope widgets, frame elements (the opening picture too).
        ``timed``: a RUNNING frame on screen, whose ``plugin.draw`` counts for W162."""
        s = self.s
        host = self.host
        self._backdrop(canvas)
        painter = host.shell.painter
        painter.bind(canvas)
        try:
            began = perf_counter()
            host.call(s.plugin.draw, canvas)
            if timed:
                cost, self._cost = self._cost + perf_counter() - began, 0.0
                host.frame_cost(s, cost)
            if s.phase is Phase.CLOSED:
                return
            painter.bind(canvas)
            host.call(self._draw_widgets, painter)
        except PluginFailed:
            return
        self._draw_frame(canvas, painter)

    def look_for(self, w: Widget) -> Look:
        scope = self.s.scope
        focused = scope.focused is w and scope.visible
        pressed = w is self._key_press or (
            w is self.pressed and self.pointer is not None and w.box.contains(self.pointer))
        return w.look(focused=focused, pressed=pressed)

    def _draw_widgets(self, p: "Painter") -> None:
        for group in self.s.scope.groups:
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

    def _backdrop(self, canvas: "Canvas") -> None:
        s = self.s
        surface = canvas.surface
        assert surface is not None
        size = surface.get_size()
        stage = s.stage_pic
        if stage is not None:
            if stage.get_size() == size:
                surface.blit(stage, (0, 0))
                return
            self.host._release(s, stage)               # resized: draw the stage again
            fresh = self.host._offscreen(size, self.host._draw_stage)
            from engine.render.frames import dim
            dim(fresh, self.host.shell.theme.cfg.menu.dim_color, s.look.stage_dim_opacity)
            self.host._hold(s, fresh)
            s.stage_pic = fresh
            surface.blit(fresh, (0, 0))
            return
        image = self.host.background(s.look)
        if image is not None:
            w, h = image.size
            k = max(CANVAS_W / w, CANVAS_H / h)          # cover the canvas, centred
            variant = canvas.assets.scaled(image, canvas.scale_x * k, canvas.scale_y * k,
                                           canvas.quality)
            surface.blit(variant, canvas.px((CANVAS_W - w * k) / 2, (CANVAS_H - h * k) / 2))
            return
        gradient = s.gradient
        if gradient is None or gradient.get_size() != size:
            gradient = s.gradient = _gradient(size, s.look.fill_top_color,
                                              s.look.fill_bottom_color)
        surface.blit(gradient, (0, 0))

    def _draw_frame(self, canvas: "Canvas", p: "Painter") -> None:
        s = self.s
        frame = s.frame
        if frame is None:
            return
        theme = self.host.shell.theme
        cfg = theme.cfg
        if frame.heading is not None and frame.heading_text:
            box = frame.heading
            p.panel(box)
            canvas.draw_text(frame.heading_text, theme.font(frame.heading_size, bold=True),
                             cfg.panel.heading.text_color,
                             (box.x + HEADING_PAD_X, box.y + box.h / 2), anchor="midleft")
        if frame.hint is not None and frame.hint_lines:
            box = frame.hint
            p.panel(box)
            size = frame.hint_size
            step = pitch(size)
            font = theme.font(size)
            for i, line in enumerate(frame.hint_lines):
                canvas.draw_text(line, font, cfg.panel.text_color,
                                 (box.x + box.w / 2, box.y + HINT_PAD_Y + i * step + step / 2),
                                 anchor="center")


def _gradient(size: tuple[int, int], top: tuple[int, int, int],
              bottom: tuple[int, int, int]) -> pygame.Surface:
    """A vertical ``top`` → ``bottom`` gradient filling ``size`` (UI-F23-01)."""
    w, h = size
    column = pygame.Surface((1, max(1, h)))
    span = max(1, h - 1)
    for y in range(max(1, h)):
        t = y / span
        column.set_at((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return pygame.transform.scale(column, (max(1, w), max(1, h)))


__all__ = ["MinigameScreen", "is_dev_end", "is_snap_key"]

"""``ChoiceController`` and ``ChoiceScreen``: a menu's choices on screen (F07
``04-technical.md`` §5.5, §7.6, §7.7; F10 C6–C8; 07 I-1 C5–C6, I-7, I-8).

Why this module exists: the runtime sends ``ShowMenu`` and waits for one ``Choose``
(invariant 5). The choices must appear exactly when the question (or the kept line) is fully
shown, never let a fast click from the question pick, and leave every input that isn't
theirs to the screens and overlays below, so F10's menus, F14, and F15 work over them.

- **Controller** (``app.choices``, built by ``app/choices.install_choices``): ``show`` is the
  ``ShowMenu`` handler. It closes any open menu, clears the textbox for a ``none`` line (its
  one ``clear()`` call; never in NVL, F17 C1: the page stays), and asks the textbox to hold
  its line (``wait_for_menu``); the textbox calls back from its first ``update`` as top screen with
  the line complete, and the controller pushes one ``ChoiceScreen`` then, directly above the
  textbox, drawn in that same frame. ``on_say`` (a say listener) closes an open menu: a
  restore, a new game. ``close`` removes the screen wherever it is (``ScreenStack.remove``;
  F10's ``reset_in_game`` calls it). ``pick`` closes the menu, tells the listeners, plays
  ``pick_sound``, and posts ``Choose(sid, key)``: an instant cut.
- **Listeners** (``MenuListener``, ``04`` §5.5; F15, F20, F25): ``menu_shown(cmd)`` in the
  screen's first drawn frame, ``focus_changed(key)`` on each focus change (never ``None``:
  focus is never cleared; not for motion over the focused button), ``picked(key)``.
- **Sounds** (UI-F07-04, 07 I-8): ``focus_sound`` on each focus change, ``pick_sound`` on a
  pick, through ``play`` (``App.audio.play_ui``, F08's UI pool; F07 doesn't own those
  channels). ``install_choices`` passes the tokens that passed W48, so a missing file is
  never played.
- **Area** (``ChoiceArea``): y 16 to the textbox's ``tab_top() − 16`` for a ``question`` or
  ``kept`` line, to ``floor()`` for ``none``; the last-resort fit ends at ``floor()`` (F10 C6:
  the quick menu's pill top − 4 while it can show, else 704; ``set_floor``). ``area`` is the
  one method that computes it. In NVL (F17 C1, ``07`` §3.2, I-2) the textbox's
  ``choice_area(fits)`` gives the area of steps 0–2, top-aligned under the page (or under a
  view plan of only the question or kept line); step 3 stays F07's own, centered.
- **Size**: s0 = ``choice.text_size`` (default the textbox's) × the player's text scale
  (``textbox.text_size()`` over ``[theme.textbox] text_size``), half up, 20–48. The layout is
  redone in the next frame when s0 or the area changes (a resize keeps it: canvas units).

**Screen input** (``04`` §7.7; F10 C7). Only ``KEYDOWN`` (never a repeat),
``MOUSEBUTTONDOWN``, ``CONTROLLERBUTTONDOWN``, and the left stick act:

| Input | Shown |
|---|---|
| mouse motion over a pickable button | focus it (returns False: motion goes on) |
| button 1 down on a pickable button | focus it; pick past the guard |
| Down/Up, D-pad, left stick | none focused → first/last pickable; else next/previous (wraps) |
| Return, keypad Enter, Space, gamepad A | none focused → focus the first; else pick (guard) |
| 1–6, keypad 1–6 | the nth pickable, past the guard |
| H (no Ctrl/Alt/Meta), button 2, gamepad Y | ``textbox.set_hidden(True)``: box and choices hide |

Every other event returns False: a press off the buttons, button 3, Esc, gamepad B, the
wheel, Ctrl, releases, and (F14 07 I-10) Page Up/Down and the shoulder buttons. The left
stick takes one step when ``LEFTY`` crosses ±16,384 outward and re-arms inside ±8,192
(F10's ``NavReader``, the one stick rule). Focus is never cleared; a press ignored by the
guard is not kept.

- **Guard**: ``elapsed`` grows by the frame's ``dt`` only while this screen is top, its first
  draw has happened, and the textbox isn't hidden, so time under F10's menus (or F11's
  load screen) or while hidden doesn't count; focus and the remaining guard wait there.
- **Hidden** (F10 C8): read from ``textbox.hidden`` every time, no copy. While hidden nothing
  is drawn and every event returns False, so the textbox's own rule shows the box again:
  button 1, Return, Space, H, button 2, and gamepad A or Y only show (no pick, no advance).
- **Fade** (UI-F07-03; 07 I-7): ``fade`` is this screen's own fade time in seconds, set from
  ``choice.fade_in_ms`` at open: 0 for a restored menu (F14 07 A5: no fade on
  ``ShowMenu.restored``; F14 may also set it). Alpha is ``min(1, (elapsed + 1/60) / fade)``,
  so the frame the line is fully shown already draws the choices; it is 1 with ``fade`` 0
  or while the player's reduce motion is on (read each frame). The guard doesn't wait for
  the fade.

**Timed menus** (F51 ``04-technical.md`` §7.3, §7.4; 07 I-2, I-5, I-6). A ``ShowMenu`` with
``seconds`` gets a ``ChoiceClock``. Each ``update`` reads the player's Timing assist
(``timing_level``, an App-injected port; F50's ``timing_limit``): under a limit the clock
counts the frame's ``dt`` while the guard would (top, drawn, not hidden) and the window has
focus (``window_focused``, App-injected, 07 I-5). When it runs out the screen picks
``ShowMenu.timeout`` through ``ChoiceController.pick`` (listeners, pick sound), bypassing
only the guard; a pick that doesn't close the menu (a future veto) leaves the clock fired
and the menu waiting for the player. A player's pick handled earlier in the frame wins: the
screen is no longer current, so ``pick`` ignores the timeout (PR-F51-07). Under a limit the
layout gets the countdown panel as its header (``render/choicetimer.panel_height`` at the
player's text scale), drawn after the buttons at the same alpha; hidden mode draws nothing.
``tick_sound`` (Could) plays when the number becomes 3, 2 or 1. Reading the past or "No
time limits": no panel and no timeout; every choice stays pickable.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

import pygame

from engine.core.logsetup import get_logger
from engine.render.choices import (
    AREA_MARGIN,
    AREA_TOP,
    LAST_BOTTOM,
    ChoiceArea,
    ChoiceLayout,
    ChoiceStackView,
    State,
    half_up,
    rgb_hex,
)
from engine.render.choicetimer import (TimerGeometry, TimerPanelView, number_size,
                                      panel_height, timer_colors)
from engine.render.textlayout import FaceSet
from engine.runtime.commands import Choose, Say, ShowMenu
from engine.ui.builtin.choice_clock import ChoiceClock
from engine.ui.input import UiEvent
from engine.ui.nav import Nav, NavReader
from engine.ui.screen import Screen, ScreenStack

if TYPE_CHECKING:
    from engine.core.config_schema import ChoiceTheme
    from engine.ui.looks import LookSource
    from engine.render.canvas import Canvas

GUARD_S: Final = 0.25                    # PR-F07-12: picks are ignored this long after open
_GUARD_EPS: Final = 1e-9                 # 250 steps of 1 ms count as 250 ms
FADE_LEAD_S: Final = 1 / 60              # 07 I-7: the open frame already draws at one frame's alpha
PICK_KEYS: Final = (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)
HIDE_BLOCKING_MODS: Final = (pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META
                             | pygame.KMOD_GUI)
NUMBER_KEYS: Final = {**{getattr(pygame, f"K_{n}"): n for n in range(1, 7)},
                      **{getattr(pygame, f"K_KP{n}"): n for n in range(1, 7)}}
MIN_SIZE: Final = 20
MAX_SIZE: Final = 48
TICK_NUMBERS: Final = (3, 2, 1)          # F51 PR-F51-20: tick_sound at these seconds left

_log = get_logger("choice")


class _Textbox(Protocol):
    """What F07 needs of F05's ``TextboxScreen``."""

    hidden: bool
    has_box: bool
    nvl_on: bool                     # F17: full-screen text is the mode

    def text_size(self) -> int: ...

    def choice_area(self, fits: Callable[[float, float], bool]
                    ) -> tuple[float, float] | None: ...

    def tab_top(self) -> float: ...

    def clear(self, *, hide: bool = True) -> None: ...

    def wait_for_menu(self, on_shown: Callable[[], None]) -> None: ...

    def set_hidden(self, hidden: bool) -> None: ...

    def reduce_motion(self) -> bool: ...


@dataclass(frozen=True)
class ChoiceLook:
    """F32's ``"choice"`` part of a look (``app/choices.choice_look``): the choice theme, the
    faces, the size base (the look's ``[theme.textbox] text_size``), the checked frame refs
    (None: the drawn button), and the sounds (None: silence)."""

    theme: "ChoiceTheme"
    faces: FaceSet
    base_text_size: int
    frame: str | None
    focused_frame: str | None
    focus_sound: str | None
    pick_sound: str | None
    tick_sound: str | None = None        # F51: ``choice.timer.tick_sound`` (None: silence)


class MenuListener(Protocol):
    """``04`` §5.5: F15 (skip stops at ``menu_shown``), F20, F25, sounds. Called on the
    presentation side; a listener posts nothing to the story."""

    def menu_shown(self, cmd: ShowMenu) -> None: ...

    def focus_changed(self, key: str | None) -> None: ...

    def picked(self, key: str) -> None: ...


class ChoiceController:
    """The launch's one menu presenter (``app.choices``). ``post`` sends an event to the
    story (``App.story.post``); ``assets`` and ``faces`` are the layout's fonts (the
    textbox's faces with ``choice.text_font`` as the regular face when it is usable);
    ``base_text_size`` is ``[theme.textbox] text_size``, the player's text scale's
    denominator. ``play`` plays a UI sound (``App.audio.play_ui``); ``focus_sound`` and
    ``pick_sound`` are the tokens that passed W48 (None: silence).

    F51: ``timing_level()`` is the player's Timing assist (the stored int; None: Normal),
    ``window_focused()`` whether the window has focus (None: always), ``tick_sound`` the
    checked ``choice.timer.tick_sound``; ``timer_view`` draws the countdown panel."""

    def __init__(self, stack: ScreenStack, textbox: _Textbox, *, theme: "ChoiceTheme",
                 assets: Any, faces: FaceSet, base_text_size: int,
                 post: Callable[[object], None], view: ChoiceStackView | None = None,
                 play: Callable[[str], None] | None = None, focus_sound: str | None = None,
                 pick_sound: str | None = None, tick_sound: str | None = None,
                 timing_level: Callable[[], int | str] | None = None,
                 window_focused: Callable[[], bool] | None = None,
                 timer_view: Any = None) -> None:
        self.stack = stack
        self.textbox = textbox
        self.theme = theme
        self.assets = assets
        self.faces = faces
        self.base_text_size = base_text_size
        self.post = post
        self.view = view if view is not None else ChoiceStackView(assets, theme)
        self.play = play
        self.focus_sound = focus_sound
        self.pick_sound = pick_sound
        self.tick_sound = tick_sound
        self._timing_level = timing_level
        self._window_focused = window_focused
        self.timer_view = timer_view if timer_view is not None else TimerPanelView(
            assets, theme, faces)
        self._timer_geometry: tuple[tuple, TimerGeometry] | None = None
        self.floor: Callable[[], float] = lambda: LAST_BOTTOM
        self.screen: ChoiceScreen | None = None
        self._listeners: list[MenuListener] = []
        self._pending: tuple[object, ShowMenu] | None = None
        self._layout_key: tuple | None = None
        self._layout: ChoiceLayout | None = None
        self._layout_cmd: ShowMenu | None = None
        self._looks: "LookSource | None" = None       # F32 (04 §6.5)
        self._look_rev = 0

    # -- seams --

    def add_listener(self, listener: MenuListener) -> None:
        """``04`` §5.5: ``listener`` hears every menu's first draw, focus changes, and pick."""
        self._listeners.append(listener)

    def set_floor(self, fn: Callable[[], float]) -> None:
        """F10 C6, I-3: the last-resort fit (and a ``none`` menu's area) ends at ``fn()``."""
        self.floor = fn

    def set_looks(self, looks: "LookSource") -> None:
        """F32 (04 §6.2 step 4, §6.5): the session's looks. When a menu is shown and the
        revision moved, the theme, faces, size base, view and sounds come from
        ``looks.part("choice")`` (a ``ChoiceLook``). A menu can't be open across a switch (the
        story waits on it; a restore sends the menu again)."""
        self._looks = looks
        self._look_rev = looks.revision

    def _sync_look(self) -> None:
        looks = self._looks
        if looks is None or looks.revision == self._look_rev:
            return
        self._look_rev = looks.revision
        part = looks.part("choice")
        assert isinstance(part, ChoiceLook)
        self.theme = part.theme
        self.faces = part.faces
        self.base_text_size = part.base_text_size
        self.view = ChoiceStackView(self.assets, part.theme, frame=part.frame,
                                    focused_frame=part.focused_frame)
        self.focus_sound = part.focus_sound
        self.pick_sound = part.pick_sound
        self.tick_sound = part.tick_sound
        self.timer_view = TimerPanelView(self.assets, part.theme, part.faces)
        self._timer_geometry = None
        self._layout = self._layout_key = self._layout_cmd = None

    def close(self) -> None:
        """Remove the open ``ChoiceScreen`` (wherever it is) and drop a menu waiting for its
        line; nothing when there is none."""
        self._pending = None
        screen, self.screen = self.screen, None
        if screen is not None:
            self.stack.remove(screen)

    # -- commands --

    def show(self, cmd: ShowMenu) -> None:
        """The ``ShowMenu`` handler (``04`` §7.6)."""
        if not 1 <= len(cmd.choices) <= 6 or all(c.locked for c in cmd.choices):
            raise AssertionError(f"a ShowMenu with {len(cmd.choices)} choices, none pickable")
        self.close()
        token = object()
        self._pending = (token, cmd)
        if cmd.line == "none" and not self.textbox.nvl_on:
            self.textbox.clear()                  # F17 C1: never in NVL (the page stays)
        self.textbox.wait_for_menu(lambda: self._open(token))

    def on_say(self, cmd: Say) -> None:
        """A say listener: any ``Say`` closes an open menu (restore, new game)."""
        self.close()

    def _open(self, token: object) -> None:
        pending = self._pending
        if pending is None or pending[0] is not token:
            _log.debug("A menu's line was shown after the menu closed; nothing opens")
            return
        self._pending = None
        self._sync_look()
        screen = ChoiceScreen(self, pending[1])
        self.screen = screen
        self.stack.push(screen)

    def pick(self, screen: "ChoiceScreen", key: str) -> None:
        """Close ``screen``'s menu, tell the listeners, play ``pick_sound``, and post the
        pick (an instant cut, UI-F07-03). F30's veto or text hook goes here."""
        if screen is not self.screen:
            return
        self.close()
        for listener in tuple(self._listeners):
            listener.picked(key)
        self._sound(self.pick_sound)
        self.post(Choose(screen.cmd.sid, key))

    # -- the screen's notes --

    def shown(self, screen: "ChoiceScreen") -> None:
        """``screen``'s first draw: ``menu_shown``."""
        for listener in tuple(self._listeners):
            listener.menu_shown(screen.cmd)

    def focus_changed(self, screen: "ChoiceScreen", key: str) -> None:
        """A new focus on ``screen``: ``focus_changed`` and ``focus_sound``."""
        for listener in tuple(self._listeners):
            listener.focus_changed(key)
        self._sound(self.focus_sound)

    def tick(self) -> None:
        """F51 (Could): ``tick_sound`` at 3, 2 and 1 seconds left."""
        self._sound(self.tick_sound)

    def _sound(self, token: str | None) -> None:
        if token is not None and self.play is not None:
            self.play(token)

    # -- F51: the clock's ports and the panel --

    def timing_level(self) -> int | str:
        """The player's Timing assist now (read every frame); Normal without a port."""
        if self._timing_level is None:
            return 0
        return self._timing_level()

    def window_focused(self) -> bool:
        """Whether the window has focus (07 I-5: from the App, not the textbox)."""
        return True if self._window_focused is None else bool(self._window_focused())

    def header_height(self) -> float:
        """The countdown panel's height at the player's text scale (``t + 12``)."""
        return float(panel_height(self.text_scale()))

    def timer_geometry(self, rect: tuple[float, float, float, float]) -> TimerGeometry:
        """The panel's boxes at ``rect`` (the layout's ``header_rect``), kept while the rect
        and the number's size stay."""
        size = number_size(self.text_scale())
        key = (rect, size)
        kept = self._timer_geometry
        if kept is None or kept[0] != key:
            kept = self._timer_geometry = (key, self.timer_view.geometry(rect, size))
        return kept[1]

    # -- motion --

    def fade_s(self, cmd: ShowMenu) -> float:
        """A new screen's fade time: ``choice.fade_in_ms``, or 0 for a restored menu (F14
        07 A5). Reduce motion is read each frame instead (``fade_off``)."""
        if cmd.restored:
            return 0.0
        return max(0, self.theme.fade_in_ms) / 1000

    def fade_off(self) -> bool:
        """The player's reduce motion (F16 ``TextSettings``, through the textbox)."""
        return bool(self.textbox.reduce_motion())

    # -- layout --

    def text_scale(self) -> float:
        """The player's text scale (F32 04 §6.5: the textbox's, measured on its layout
        look; else its text size over ``base_text_size``)."""
        text_scale = getattr(self.textbox, "text_scale", None)
        if text_scale is not None:
            return text_scale()
        return self.textbox.text_size() / self.base_text_size if self.base_text_size else 1.0

    def text_size(self) -> int:
        """s0: ``choice.text_size`` × the player's text scale, half up, 20–48."""
        base = self.theme.text_size if self.theme.text_size is not None \
            else self.base_text_size
        return max(MIN_SIZE, min(MAX_SIZE, half_up(base * self.text_scale())))

    def area(self, line: str, fits: Callable[[float, float], bool] | None = None
             ) -> ChoiceArea:
        """Where the stack goes for a menu whose textbox holds ``line``: the one place the
        area is computed (at open and at every re-layout check; never cached beyond
        ``layout``'s key). In NVL (F17 C1, 07 §3.2) the textbox's ``choice_area(fits)``
        gives ``(T, B)`` for steps 0–2, top-aligned; ``fits(t, b)`` is the menu's
        ``ChoiceLayout.fits``. Step 3 keeps F07's own area (``16..floor()``, centered)."""
        floor = self.floor()
        if self.textbox.nvl_on:
            if fits is None:
                raise AssertionError("an NVL choice area needs the menu's fit test")
            nvl = self.textbox.choice_area(fits)
            if nvl is not None:
                return ChoiceArea(nvl[0], nvl[1], floor, "top")
        if line == "none":
            return ChoiceArea(AREA_TOP, floor, floor)
        return ChoiceArea(AREA_TOP, self.textbox.tab_top() - AREA_MARGIN, floor)

    def layout(self, cmd: ShowMenu, header: float = 0.0) -> ChoiceLayout:
        """``cmd``'s layout now (kept until its size or area changes; a new area re-places
        the same measurements, ``ChoiceLayout.relaid``). ``header`` (F51): the countdown
        panel's height, 0 without one; a change is a ``relaid``."""
        size = self.text_size()
        layout = self._layout
        if layout is None or self._layout_cmd is not cmd or self._layout_key is None \
                or self._layout_key[0] != size:
            nvl = self.textbox.nvl_on
            theme = self.theme
            colors = [rgb_hex(theme.locked.text_color if c.locked else theme.text_color)
                      for c in cmd.choices]
            layout = ChoiceLayout([c.body for c in cmd.choices], assets=self.assets,
                                  faces=self.faces, theme=theme, text_size=size,
                                  area=ChoiceArea() if nvl else self.area(cmd.line),
                                  colors=colors, header=header)
        if layout.header != header:
            layout = layout.relaid(layout.area, header)
        area = self.area(cmd.line, layout.fits)
        if area != layout.area:
            layout = layout.relaid(area)
        self._layout, self._layout_key, self._layout_cmd = layout, (size, area), cmd
        return layout


class ChoiceScreen(Screen):
    """One open menu's buttons (``04`` §7.7), above the textbox."""

    opaque = False
    in_game = True

    def __init__(self, controller: ChoiceController, cmd: ShowMenu) -> None:
        self.controller = controller
        self.cmd = cmd
        self.pickable: tuple[int, ...] = tuple(i for i, c in enumerate(cmd.choices)
                                               if not c.locked)
        self.focus: int | None = None
        self.elapsed = 0.0
        self.started = False
        self.fade = controller.fade_s(cmd)       # seconds; per screen (F14 may set 0)
        self.clock = ChoiceClock(cmd.seconds)    # F51: presentation state, never saved
        self._number: int | None = None          # F51: the last number shown (tick sound)
        self.layout = controller.layout(cmd, self._header())
        self._stick = NavReader()                # the left stick only

    # -- state --

    @property
    def hidden(self) -> bool:
        """F10 C8: the textbox's hidden mode, read every time."""
        return bool(self.controller.textbox.hidden)

    @property
    def past_guard(self) -> bool:
        return self.elapsed + _GUARD_EPS >= GUARD_S

    def alpha(self) -> float:
        """The fade's alpha now (07 I-7)."""
        if self.fade <= 0 or self.controller.fade_off():
            return 1.0
        return min(1.0, (self.elapsed + FADE_LEAD_S) / self.fade)

    def states(self) -> list[State]:
        return ["locked" if c.locked else "focused" if i == self.focus else "normal"
                for i, c in enumerate(self.cmd.choices)]

    # -- Screen --

    def handle_event(self, event: UiEvent) -> bool:
        if self.hidden:
            return False                      # the textbox shows the box again (C8)
        raw = event.raw
        kind = raw.type
        if kind == pygame.MOUSEMOTION:
            index = self._pickable_at(event)
            if index is not None:
                self._focus(index)
            return False                      # C7: motion goes on
        if kind == pygame.MOUSEBUTTONDOWN:
            button = getattr(raw, "button", 0)
            if button == 2 and event.in_canvas:
                return self._hide()
            if button != 1:
                return False
            index = self._pickable_at(event)
            if index is None:
                return False                  # C7: off the buttons goes on (F05 ignores it)
            self._focus(index)
            if self.past_guard:
                self._pick(index)
            return True
        if kind == pygame.KEYDOWN:
            if getattr(raw, "repeat", False):
                return False
            return self._key(raw.key, getattr(raw, "mod", 0))
        if kind == pygame.CONTROLLERBUTTONDOWN:
            button = getattr(raw, "button", -1)
            if button == pygame.CONTROLLER_BUTTON_DPAD_DOWN:
                self._move(1)
                return True
            if button == pygame.CONTROLLER_BUTTON_DPAD_UP:
                self._move(-1)
                return True
            if button == pygame.CONTROLLER_BUTTON_A:
                self._activate()
                return True
            if button == pygame.CONTROLLER_BUTTON_Y:
                return self._hide()
            return False                      # B (F10), shoulders (F14), …
        if kind == pygame.CONTROLLERAXISMOTION:
            if getattr(raw, "axis", -1) != pygame.CONTROLLER_AXIS_LEFTY:
                return False
            nav = self._stick.read(event, dev=False)
            if nav is Nav.DOWN:
                self._move(1)
                return True
            if nav is Nav.UP:
                self._move(-1)
                return True
            return False
        return False                          # releases, wheel, …

    def _key(self, key: int, mods: int) -> bool:
        if key == pygame.K_DOWN:
            self._move(1)
            return True
        if key == pygame.K_UP:
            self._move(-1)
            return True
        if key in PICK_KEYS:
            self._activate()
            return True
        if mods & HIDE_BLOCKING_MODS:
            return False                      # Ctrl+H, Alt+1, … are not ours
        if key == pygame.K_h:
            return self._hide()
        n = NUMBER_KEYS.get(key)
        if n is not None and n <= len(self.pickable):
            if self.past_guard:
                self._pick(self.pickable[n - 1])
            return True
        return False                          # Esc, Ctrl, Page Up/Down, …

    def update(self, dt: float, *, is_top: bool) -> None:
        controller = self.controller
        usable = is_top and self.started and not self.hidden
        if usable:
            self.elapsed += dt
        level = controller.timing_level()
        if self.clock.tick(dt, level, counting=usable and controller.window_focused()):
            self._timeout()
            return
        self._tick_sound(level)
        self.layout = controller.layout(self.cmd, self._header())  # new only on a change

    def draw(self, canvas: "Canvas") -> None:
        if self.hidden:
            return
        if not self.started:
            self.started = True
            self.controller.shown(self)
        alpha = self.alpha()
        self.controller.view.draw(canvas, self.layout, self.states(), alpha=alpha)
        self._draw_timer(canvas, alpha)

    # -- F51: the countdown --

    def timed(self) -> bool:
        """Whether a countdown runs now: a time limit under the player's Timing assist."""
        return self.clock.limit(self.controller.timing_level()) is not None

    def _header(self) -> float:
        return self.controller.header_height() if self.timed() else 0.0

    def _draw_timer(self, canvas: "Canvas", alpha: float) -> None:
        rect = self.layout.header_rect
        controller = self.controller
        level = controller.timing_level()
        fraction = self.clock.fraction(level, reduce_motion=controller.fade_off())
        if rect is None or fraction is None:
            return
        controller.timer_view.draw(canvas, controller.timer_geometry(rect), fraction,
                                   self.clock.shown(level) or 0, timer_colors(controller.theme),
                                   alpha=alpha)

    def _tick_sound(self, level: int | str) -> None:
        number = self.clock.shown(level)
        previous, self._number = self._number, number
        if (number is not None and previous is not None and number != previous
                and number in TICK_NUMBERS):
            self.controller.tick()

    def _timeout(self) -> None:
        """Time ran out: pick ``ShowMenu.timeout`` as a click would, past the guard (07
        I-6: if the menu stays open, the clock stays fired and the player picks)."""
        key = self.cmd.timeout
        if key is not None and any(c.key == key and not c.locked for c in self.cmd.choices):
            self.controller.pick(self, key)

    # -- helpers --

    def _pickable_at(self, event: UiEvent) -> int | None:
        if not event.in_canvas or event.canvas_pos is None:
            return None                       # letterbox bars
        index = self.layout.hit(event.canvas_pos)
        if index is None or self.cmd.choices[index].locked:
            return None                       # locked buttons are never hit
        return index

    def _focus(self, index: int) -> None:
        if index == self.focus:
            return
        self.focus = index
        self.controller.focus_changed(self, self.cmd.choices[index].key)

    def _move(self, step: int) -> None:
        order = self.pickable
        if self.focus is None or self.focus not in order:
            self._focus(order[0] if step > 0 else order[-1])
        else:
            self._focus(order[(order.index(self.focus) + step) % len(order)])

    def _activate(self) -> None:
        """Return, keypad Enter, Space, gamepad A."""
        if self.focus is None:
            self._focus(self.pickable[0])
        elif self.past_guard:
            self._pick(self.focus)

    def _hide(self) -> bool:
        self.controller.textbox.set_hidden(True)
        return True

    def _pick(self, index: int) -> None:
        self.controller.pick(self, self.cmd.choices[index].key)


__all__ = ["FADE_LEAD_S", "GUARD_S", "PICK_KEYS", "ChoiceController", "ChoiceLook", "ChoiceScreen",
           "MenuListener"]

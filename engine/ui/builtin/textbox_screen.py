"""``TextboxScreen``: the say window, the in-game screen that shows each story line (F05
``04-technical.md`` §7.9; ``03-ui.md`` "States", "Interaction", "Motion and timing").

Why this module exists: a line types itself per grapheme, waits at ``{pause}`` and page ends,
and answers a press with "show the rest", "go on", or, once complete, exactly one
``Advance(sid)``. That is all presentation state (the line is the only checkpoint, §9), so
it lives here, rebuilt from each ``Say``. ``TextboxView`` (``render/textbox.py``) draws it.

- **show(cmd)** is the ``Say`` handler (``app/text_check.install_textbox`` registers it): a
  new layout at the current text size and a new ``Typewriter``, which runs at once, so the
  first glyph (or the whole first stop at instant speed) shows in the arrival frame; that
  frame's ``update`` adds no time. A restored line shows complete on its last page, and its
  ``{next}`` is ignored.
- **Input** (03 "Interaction"): left click in the canvas, Space, Enter, keypad Enter, and
  gamepad A advance; H (no Ctrl/Alt/Meta), middle click, and gamepad Y hide. While hidden,
  either only shows the box. Nothing else is F05's: overlays (F10 C5, ``add_overlay``) see
  every event first, also while hidden, and unconsumed input passes down (``in_game``).
- **update**: frozen while not top (a menu is open), hidden, or while the window lacks
  focus: no typing time and no bob. Focus is read from ``App.focused`` (set in the App's
  event phase), not from ``WINDOWFOCUS*`` events, which reach only the top screen (I-4); on
  focus gain typing resumes without a press (G8).
  ``{next}`` posts ``Advance`` in the frame after the line completed by itself, with no
  indicator. One page is laid out ahead per frame.
- **draw**: nothing before the first line, while hidden, or after ``clear()``; the box stays
  between lines. Glyphs go through the view's typed layer (``TextboxView.draw_typed``):
  each frame blits the glyphs drawn before at once and appends only the new ones.
- **Effect clock** (F29 ``04`` §7.4; ``07`` I-3, I-5, I-7): ``_fx_t``, presentation-only
  seconds that pose ``{shake}``, ``{wave}``, ``{glitch}`` glyphs. It holds while the story
  may not run (a game menu, a confirm, a fade: ``story_may_run()``, the overlays' rule),
  while hidden, while the window lacks focus, or while the box isn't shown, and keeps
  running under F07's choices (unlike typing). The frame after a ``show`` adds no time.
  ADV restarts it at 0 on each ``show`` (live or restored, so a reloaded or rolled-back
  line replays the same frames); a line's own later pages keep its time. The pose seed
  ``textfx.line_seed(sid)`` is computed once per ``show``. ``_draw_box`` passes
  ``FxTime(_fx_t, reduce_motion())`` and the seed to ``draw_typed``. In NVL the clock is
  page time (K2): it restarts at 0 in ``show_nvl`` and in a ``show`` whose line is the first
  row of the plan (it starts a page), so a line that settles keeps its pose; ``_draw_nvl``
  passes the same ``FxTime`` to ``NvlView.draw``, which seeds each row itself (``_fx_seed``
  is ADV-only).

``in_game`` is True (F10 C2–C3): the story runs while this screen is top. One
``TextboxScreen`` serves a launch (I-16); ``clear(hide=True)`` and ``set_hidden(False)``
reset it before a new game and on the way to the title (F10 I-8, ``menus.reset_in_game``).

Seams (``04`` §7.10): ``settings`` (``TextSettings``; F16 replaces it whole),
``hidden``/``set_hidden`` (F07, F09), ``clear(*, hide=True)`` (F07, F09),
``on_idle_advance`` (F09), ``add_overlay`` and ``has_box`` (F10); ``add_listener``
(``TypingListener``: F06 blips, F15 timers, F38), ``add_say_listener`` (F07, F13),
``press()``, ``complete_now()``, and ``shown_count()`` (F15), ``tab_top()`` and
``wait_for_menu(on_shown)`` (F07), ``cue_anchor()`` and ``set_bump(dy)`` (F14 A4: the limit
mark's point and the say window's bump; ``nvl_cue`` is F17's NVL branch).

**NVL** (F17 ``04`` §7.2): ``show_nvl`` (the ``NvlPage`` handler) sets the mode and the
page (``self.nvl``, an ``NvlPresenter``); ``show`` stays the one ``Say`` handler, and in NVL
lays the line out at the NVL text area (a row of the presenter's plan) instead of the box.
The current-line fields (``line``, ``layout``, ``typer``, ``_posted`` …) serve both modes,
so ``press``, ``complete_now``, ``shown_count``, ``{next}``, the listeners and the menu wait
are the same code. ``clear`` in NVL settles the line (its entry stays on the page); with
``hide`` the panel, page and quick menu wait hidden until the next ``Say``, ``NvlPage`` or
``wait_for_menu``. ``choice_area(fits)`` is F07's NVL choice area (F17 ``04`` §7.4, ``07``
§3.2): under the page, else under a view plan of only the last line (presentation only). ``box_shown``/``has_box`` mean "the panel is drawn" /
"the panel exists" in NVL, so the quick menu follows the panel. ``draw`` calls exactly one
of ``TextboxView`` (ADV) and ``NvlView`` (NVL), then the overlays. While NVL is shown,
``nvl_cue`` is the ``NvlView`` (F14 A4). ``reset_nvl`` is F17's in-game reset (ADV, empty
page; ``install_nvl``).

**Menu wait** (F07 ``04`` §5.3, C5): from ``wait_for_menu`` until the next ``show()`` or
``clear()``, the line never posts ``Advance`` (a press, ``{next}``, F15's auto), and no idle
advance runs. A press while the line types, at a ``{pause}``, or at a page break acts as
usual, with its indicator; a press on the complete line does nothing, and the complete line
has no indicator. ``on_shown`` runs once, from the first ``update(is_top=True)`` in which the
line is complete or there is no line (hidden or unfocused included), so F07's choices open
in the frame the line is fully shown, directly above this screen.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

import pygame

from engine.core.constants import TEXT_SIZE_RANGE
from engine.render.canvas import Canvas
from engine.render.nvl import NvlView
from engine.render.nvllayout import nvl_look
from engine.render.textbox import BoxGeometry, TextboxView, bob_offset, box_geometry, hex_rgb, \
    rgb_hex
from engine.render.textfx import FxTime, line_seed
from engine.render.textlayout import FaceSet, LayoutContext, LineLayout
from engine.render.typewriter import (
    Completed,
    PressResult,
    TypeEvent,
    TypeState,
    Typewriter,
    TypingListener,
    Waiting,
    deliver,
)
from engine.runtime.commands import Advance, NvlPage, Say
from engine.ui.builtin.nvl_page import NvlPresenter
from engine.ui.input import UiEvent
from engine.ui.screen import InGameOverlay, Screen
from engine.ui.shell import reduce_motion_of

if TYPE_CHECKING:
    from engine.core.config_schema import Config

ADVANCE_KEYS = (pygame.K_SPACE, pygame.K_RETURN, pygame.K_KP_ENTER)
HIDE_BLOCKING_MODS = pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META | pygame.KMOD_GUI


class _StoryPost(Protocol):
    def post(self, event: object) -> None: ...


class CueTarget(Protocol):
    """F14 A4's NVL branch (07 §3.4, I-8): what F17's NVL window answers while it is shown."""

    def cue_anchor(self) -> tuple[float, float]: ...

    def set_bump(self, dy: float) -> None: ...


CUE_INSET = 52                         # F14 03: the mark's center, in from the window's right


class _HasStory(Protocol):
    """What the textbox needs of the ``App`` (``ui`` never imports ``app``): the story to
    post ``Advance`` to, and ``focused``, whether the window has input focus (F11 C9; read
    each update, I-4)."""

    story: _StoryPost | None
    focused: bool


@dataclass
class TextSettings:
    """The player's text settings (F16 replaces the whole object). ``None`` = config:
    ``cps`` ``[textbox] cps``; ``instant`` False; ``text_size`` ``[theme.textbox]
    text_size`` (capped at 48, applied from the next line); ``reduce_motion`` the config's
    effects flag (the indicator stays at rest)."""

    cps: int | None = None
    instant: bool | None = None
    text_size: int | None = None
    reduce_motion: bool | None = None


class TextboxScreen(Screen):
    """The ``Say`` handler of the launch; posts ``Advance(sid)`` once per line."""

    opaque = False
    in_game = True

    def __init__(self, app: _HasStory, config: "Config", view: TextboxView,
                 faces: FaceSet, *, nvl_view: NvlView | None = None) -> None:
        self.app = app
        self.config = config
        self.view = view
        self.faces = faces
        look = nvl_look(config.theme)
        # F17: the NVL page and its view (install_textbox builds the view; by hand: here).
        self.nvl = NvlPresenter(view.assets, faces, look)
        self.nvl_view = nvl_view if nvl_view is not None else \
            NvlView.for_textbox(view, look, faces)
        self._wait_hidden = False      # F17: clear(hide=True) in NVL, until the next line
        self.settings = TextSettings()
        self.overlays: list[InGameOverlay] = []
        # F09: an advance input when no shown line awaits one (its Advance went out, or
        # after clear()). None: such input does nothing.
        self.on_idle_advance: Callable[[], None] | None = None
        self._listeners: list[TypingListener] = []
        self._say_listeners: list[Callable[[Say], None]] = []
        self.line: Say | None = None
        self.layout: LineLayout | None = None
        self.typer: Typewriter | None = None
        self.geometry: BoxGeometry = box_geometry(config.theme.textbox, self.text_size())
        self._hidden = False
        self._box_only = False         # clear(hide=False): the empty box stays drawn
        self._line_id = 0
        self._fresh = False            # the arrival frame adds no typing time
        self._posted = False           # Advance(sid) went out for this line
        self._auto = False             # {next}: the line completed by itself, no indicator
        self._auto_due: int | None = None
        self._updates = 0
        self._bob_t = 0.0
        self._fx_t = 0.0               # F29: the effect clock (04 §7.4), presentation only
        self._fx_fresh = False         # F29: the frame after a show adds no effect time
        self._fx_seed = 0              # F29: line_seed(sid) of the shown ADV line (07 I-3)
        self._laid_ahead = 0
        self._menu_wait = False        # F07: a menu waits under this line (wait_for_menu)
        self._on_menu_shown: Callable[[], None] | None = None
        self.bump = 0.0                # F14 A4: the say window's draw offset (y, canvas units)
        # F14 A4, NVL branch (I-8): F17 Step 2's mode switch sets this to its NVL window while
        # NVL is shown (None in ADV), so ``cue_anchor``/``set_bump`` answer for the panel.
        self.nvl_cue: CueTarget | None = None

    # -- settings --

    def cps(self) -> float:
        """The current typing speed in graphemes per second; 0 = instant."""
        settings = self.settings
        if settings.instant:
            return 0.0
        return float(settings.cps if settings.cps is not None else self.config.textbox.cps)

    def text_size(self) -> int:
        size = self.settings.text_size
        if size is None:
            size = self.config.theme.textbox.text_size
        return max(TEXT_SIZE_RANGE[0], min(TEXT_SIZE_RANGE[1], int(size)))

    def focused(self) -> bool:
        """Whether the window has input focus, as the ``App`` sees it (I-4)."""
        return bool(getattr(self.app, "focused", True))

    def reduce_motion(self) -> bool:
        flag = self.settings.reduce_motion
        return reduce_motion_of(self.config) if flag is None else bool(flag)

    def text_scale(self) -> float:
        """F16's text scale: the effective text size over ``[theme.textbox] text_size``
        (F17's NVL size is ``[theme.nvl] text_size`` times this)."""
        base = self.config.theme.textbox.text_size
        return self.text_size() / base if base else 1.0

    # -- seams --

    def add_overlay(self, overlay: InGameOverlay) -> None:
        """F10 C5: ``overlay`` gets events before the textbox, in the order added."""
        self.overlays.append(overlay)

    @property
    def hidden(self) -> bool:
        """The player's hidden mode (H), separate from ``clear``."""
        return self._hidden

    def set_hidden(self, hidden: bool) -> None:
        """Hide or show the box (H, F07, F09). On show the indicator starts at rest."""
        if self._hidden and not hidden:
            self._bob_t = 0.0
        self._hidden = bool(hidden)

    def add_listener(self, listener: TypingListener) -> None:
        """F06, F15, F38: ``listener`` gets the typing events of every line, in order, in the
        call that caused them (``show``, ``press``, ``complete_now``, or the frame's
        ``update``). A completing press gives one ``completed(True)`` and no
        ``glyph_shown``; a restored line gives one ``completed(True)``."""
        self._listeners.append(listener)

    def add_say_listener(self, fn: Callable[[Say], None]) -> None:
        """F07, F13: ``fn(cmd)`` for every ``Say`` shown, restored ones included, before the
        textbox lays it out."""
        self._say_listeners.append(fn)

    def complete_now(self) -> None:
        """F15 skip: show the line complete on its last page. Posts no ``Advance`` (a press
        then advances); nothing when there is no line or it is already complete."""
        typer = self.typer
        if typer is None or self.line is None:
            return
        typer.complete_all()
        self._events(typer.take_events(), in_update=False)

    def tab_top(self) -> float:
        """F07: the name tab's top y at the current text size, plate shown or not."""
        return self.view.tab_top(box_geometry(self.config.theme.textbox, self.text_size()))

    def cue_anchor(self) -> tuple[float, float]:
        """F14 A4: the limit mark's center, ``CUE_INSET`` in from the say window's right
        edge on its top edge (``(640 + width/2 − 52, box top)``, the box of the shown line's
        text size). In NVL (``nvl_cue`` set, F17): the panel's (right − 52, top)."""
        nvl = self.nvl_cue
        if nvl is not None:
            return nvl.cue_anchor()
        x, y, w, _ = self.geometry.box
        return x + w - CUE_INSET, y

    def set_bump(self, dy: float) -> None:
        """F14 A4: draw the box, name tab, text, and indicator ``dy`` units lower (the bump
        is negative: up); 0 = at rest. Overlays (quick menu, F15's pill, the rewind tag)
        and F07's choices never move. In NVL (``nvl_cue`` set): F17's panel and its text."""
        self.bump = float(dy)
        nvl = self.nvl_cue
        if nvl is not None:
            nvl.set_bump(dy)

    def wait_for_menu(self, on_shown: Callable[[], None]) -> None:
        """F07 (``04`` §5.3): hold the line for a menu until the next ``show()`` or
        ``clear()`` (see "Menu wait" above). A later call replaces ``on_shown``. In NVL the
        panel shows again (a ``clear(hide=True)`` before the menu ends here, F17 §7.2)."""
        self._wait_hidden = False
        self._menu_wait = True
        self._on_menu_shown = on_shown
        self._auto_due = None

    @property
    def menu_waiting(self) -> bool:
        """Whether a menu waits under the line (``wait_for_menu`` is in force)."""
        return self._menu_wait

    def clear(self, *, hide: bool = True) -> None:
        """Drop the shown line (text, tab, indicator). ``hide=True`` draws nothing;
        ``hide=False`` keeps the empty box. The next ``show`` draws normally. Ends a menu
        wait (F07 calls ``clear()`` before ``wait_for_menu``).

        In NVL (F17 ``04`` §7.2): the line settles instead (its entry stays on the page,
        no indicator, presses go to ``on_idle_advance``); ``hide=True`` also hides the
        panel, page and quick menu until the next ``Say`` or ``NvlPage``."""
        layout = self.layout
        self._drop_line()
        if self.nvl.on:
            self.nvl.settle(layout)
            self._wait_hidden = bool(hide)
        else:
            self._box_only = not hide

    def _drop_line(self) -> None:
        """F05's ``clear`` internals: no current line, no menu wait, nothing pending."""
        self._menu_wait = False
        self._on_menu_shown = None
        self.line = None
        self.layout = None
        self.typer = None
        self._box_only = False
        self._auto_due = None
        self.view.forget_line()
        self.nvl_view.forget_line()

    # -- F17: NVL --

    @property
    def nvl_on(self) -> bool:
        """Whether full-screen text (NVL) is the mode now."""
        return self.nvl.on

    def show_nvl(self, cmd: NvlPage) -> None:
        """The ``NvlPage`` handler: drop the current line in either mode, set the mode, and
        replace the page (a restore's record; live: empty). The panel shows at once in NVL
        (not wait-hidden); in ADV the box returns with the next line."""
        self._drop_line()
        self._wait_hidden = False
        self.nvl.set(cmd.on, cmd.lines, self.nvl.metrics_at(self.text_scale()))
        self.nvl_cue = self.nvl_view if cmd.on else None
        self.nvl_view.set_bump(self.bump if cmd.on else 0.0)
        self._fx_t = 0.0                           # F29: a new (or restored) page, page time
        self._fx_fresh = True

    def choice_area(self, fits: Callable[[float, float], bool]
                    ) -> tuple[float, float] | None:
        """F07's choice area (F17 ``04`` §5.4, §7.4; ``07`` §3.2): None in ADV (F07's own
        rule). In NVL ``(T, B)``: from 24 under the shown page (the area's top on an empty
        page) to the text area's bottom; when ``fits(T, B)`` is False and the page has
        rows, under a view plan of only its last line (the question or the kept line),
        which the panel then draws instead of the page until the next line or page."""
        if not self.nvl.on:
            return None
        return self.nvl.choice_area(fits)

    def reset_nvl(self) -> None:
        """F17's in-game reset (``install_nvl``, after F15's): ADV, an empty page, the panel
        not wait-hidden. New Game, the title, and a load start in ADV; a load's burst then
        sends the saved mode."""
        self.show_nvl(NvlPage(False))

    def shown_count(self) -> int:
        """F15: graphemes of the current line shown so far (0 with no line)."""
        return 0 if self.typer is None else self.typer.shown

    @property
    def box_shown(self) -> bool:
        """The say window is drawn: not hidden, and in ADV a line or the empty box; in NVL
        the panel, unless a ``clear(hide=True)`` waits for the next line (F17)."""
        return not self._hidden and self.has_box

    @property
    def has_box(self) -> bool:
        """F10 C6: the box has something to draw (a line, or the empty box), hidden mode
        aside. The quick menu's choice floor reads it, so choices laid out while hidden
        still stay above the pill once the box shows again. In NVL: the panel exists (it
        is not waiting hidden, F17)."""
        if self.nvl.on:
            return not self._wait_hidden
        return self.line is not None or self._box_only

    # -- the line --

    def show(self, cmd: Say) -> None:
        """The ``Say`` handler: ``cmd`` replaces the shown line (in NVL: joins the page)."""
        for fn in tuple(self._say_listeners):
            fn(cmd)
        if self.nvl.on:
            nvl = self.nvl
            self._wait_hidden = False
            entry = nvl.arrive(cmd, nvl.metrics_at(self.text_scale()), self.layout)
            layout = LineLayout(cmd.body, nvl.ctx_for(entry))
            self.nvl_view.forget_line()
            rows = nvl.plan.rows
            if rows and rows[0].entry == nvl.current:
                self._fx_t = 0.0                   # F29: the line starts a page (page time)
        else:
            theme = self.config.theme.textbox
            geometry = box_geometry(theme, self.text_size())
            ctx = LayoutContext(self.view.assets, self.faces, geometry.text_size,
                                rgb_hex(theme.text_color), geometry.area[2], geometry.area[3])
            layout = LineLayout(cmd.body, ctx)
            self.geometry = geometry
            self._fx_t = 0.0                       # F29: ADV line time starts again
            self._fx_seed = line_seed(cmd.sid)
        typer = Typewriter(layout, self.cps)
        self.line, self.layout, self.typer = cmd, layout, typer
        self._line_id += 1
        self._box_only = False
        self._posted = False
        self._auto = False
        self._auto_due = None
        self._laid_ahead = 0
        self._bob_t = 0.0
        self._menu_wait = False
        self._on_menu_shown = None
        self.view.forget_line()
        if cmd.restored:
            typer.complete_all()
            self._events(typer.take_events(), in_update=False)
        else:
            self._events(typer.run(), in_update=False)
        self._fresh = True
        self._fx_fresh = True

    def press(self) -> None:
        """An advance (the player; F15 auto uses the same path)."""
        typer = self.typer
        line = self.line
        if self._menu_wait:                        # F07: a menu waits; never an Advance
            if typer is not None and line is not None \
                    and typer.state is not TypeState.COMPLETE:
                typer.press()
                self._events(typer.take_events(), in_update=False)
            return
        if typer is None or line is None or self._posted:
            if self.on_idle_advance is not None:
                self.on_idle_advance()
            return
        result = typer.press()
        self._events(typer.take_events(), in_update=False)
        if result is PressResult.ADVANCE:
            self._post(line)

    def _post(self, line: Say) -> None:
        if self._posted or self._menu_wait:
            return
        self._posted = True
        self._auto_due = None
        story = self.app.story
        if story is not None:
            story.post(Advance(line.sid))

    def _events(self, events: list[TypeEvent], *, in_update: bool) -> None:
        """Bob restarts when an indicator appears; ``{next}`` schedules its advance; the
        typing listeners get every event."""
        line = self.line
        for event in events:
            if isinstance(event, (Waiting, Completed)):
                self._bob_t = 0.0
            if isinstance(event, Completed) and not event.by_press and line is not None \
                    and line.body.auto_next and not line.restored:
                self._auto = True
                # The frame after the one it completed in (show runs before that frame's
                # update; an update's own completion counts from that update).
                self._auto_due = self._updates + (1 if in_update else 2)
        if events and self._listeners:
            deliver(events, tuple(self._listeners))

    def indicator_kind(self) -> str | None:
        """``"line"``, ``"page"``, or None (typing, a timed pause, or a ``{next}`` line)."""
        typer = self.typer
        if typer is None or self._auto:
            return None
        state = typer.state
        if self._menu_wait and state is TypeState.COMPLETE:
            return None                            # F07: the choices answer this line
        if state is TypeState.WAIT_PAGE:
            return "page"
        if state in (TypeState.WAIT_CLICK, TypeState.COMPLETE):
            return "line"
        return None

    # -- Screen --

    def handle_event(self, event: UiEvent) -> bool:
        shown = self.box_shown
        for overlay in list(self.overlays):
            if overlay.handle_event(event, box_shown=shown):
                return True
        kind = self._input_kind(event)
        if kind is None:
            return False
        if self._hidden:
            self.set_hidden(False)                 # either input only shows the box
            return True
        if kind == "hide":
            if not self.has_box:
                return False
            self.set_hidden(True)
            return True
        if self.line is None and self.on_idle_advance is None:
            return False
        self.press()
        return True

    @staticmethod
    def _input_kind(event: UiEvent) -> str | None:
        raw = event.raw
        kind = raw.type
        if kind == pygame.MOUSEBUTTONDOWN:
            if not event.in_canvas:
                return None                        # letterbox bars
            button = getattr(raw, "button", 0)
            return "advance" if button == 1 else "hide" if button == 2 else None
        if kind == pygame.KEYDOWN:
            if getattr(raw, "repeat", False):
                return None
            key = raw.key
            if key in ADVANCE_KEYS:
                return "advance"
            if key == pygame.K_h and not getattr(raw, "mod", 0) & HIDE_BLOCKING_MODS:
                return "hide"
            return None
        if kind == pygame.CONTROLLERBUTTONDOWN:
            button = getattr(raw, "button", -1)
            if button == pygame.CONTROLLER_BUTTON_A:
                return "advance"
            if button == pygame.CONTROLLER_BUTTON_Y:
                return "hide"
        return None

    def update(self, dt: float, *, is_top: bool) -> None:
        # F14 A6 (F23 C2): overlays are frozen only while a screen that isn't in-game is on
        # top (a menu, a fade), not under F07's choices; an App wired by hand: not top.
        screens = getattr(self.app, "screens", None)
        frozen = not screens.story_may_run() if screens is not None else not is_top
        for overlay in self.overlays:
            overlay.update(dt, frozen=frozen)
        self._updates += 1
        # F29 (07 I-5): the effect clock holds as the overlays do, and while hidden, unfocused,
        # or with no box shown; it runs under F07's choices, where typing is frozen.
        step = 0.0 if self._fx_fresh else dt
        self._fx_fresh = False
        if not frozen and self.box_shown and self.focused():
            self._fx_t += step
        typer, line, layout = self.typer, self.line, self.layout
        if typer is None or line is None or layout is None:
            self._menu_shown(is_top)
            return
        if not is_top or self._hidden or not self.focused():
            self._menu_shown(is_top)
            return                                 # frozen: no time passes for the line
        step = 0.0 if self._fresh else dt
        self._fresh = False
        if self.indicator_kind() is not None and not self.reduce_motion():
            self._bob_t += step
        if self._auto_due is not None and self._updates >= self._auto_due:
            self._post(line)
        self._events(typer.tick(step), in_update=True)
        # One page laid out ahead per frame (PR-F05-27): the next page is ready to draw.
        ahead = typer.page + 1
        if self._laid_ahead < ahead and not layout.is_last(typer.page):
            layout.page(ahead)
            self._laid_ahead = ahead
        self._menu_shown(is_top)

    def _menu_shown(self, is_top: bool) -> None:
        """F07: run ``on_shown`` once the line is complete (or there is none) while top."""
        on_shown = self._on_menu_shown
        if on_shown is None or not is_top:
            return
        typer = self.typer
        if self.line is not None and typer is not None \
                and typer.state is not TypeState.COMPLETE:
            return
        self._on_menu_shown = None
        on_shown()

    def draw(self, canvas: Canvas) -> None:
        shown = self.box_shown
        if shown:
            if self.nvl.on:
                self._draw_nvl(canvas)
            else:
                self._draw_box(canvas)
        for overlay in self.overlays:
            overlay.draw(canvas, box_shown=shown)

    def _draw_nvl(self, canvas: Canvas) -> None:
        kind = self.indicator_kind() if self.line is not None else None
        bob = 0.0 if kind is None or self.reduce_motion() else bob_offset(self._bob_t)
        self.nvl_view.draw(canvas, self.nvl, typer=self.typer, line_id=self._line_id,
                           indicator=kind, bob=bob,
                           fx=FxTime(self._fx_t, self.reduce_motion()))

    def _draw_box(self, canvas: Canvas) -> None:
        view, geometry = self.view, self.geometry
        dy = self.bump
        if dy:                                     # F14: the limit cue's bump
            x, y, w, h = geometry.box
            ax, ay, aw, ah = geometry.area
            geometry = replace(geometry, box=(x, y + dy, w, h), area=(ax, ay + dy, aw, ah))
        view.draw_box(canvas, geometry)
        line, layout, typer = self.line, self.layout, self.typer
        if line is None or layout is None or typer is None:
            return
        if line.name:                              # None: narration; "": no name plate
            tab = view.name_tab(line.name, geometry)
            color = hex_rgb(line.name_color) if _is_hex(line.name_color) \
                else self.config.theme.textbox.name_tab.text_color
            view.draw_tab(canvas, tab, color)
        page = layout.page(typer.page)
        view.draw_typed(canvas, page, self._line_id, typer.shown, geometry,
                        fx=FxTime(self._fx_t, self.reduce_motion()), seed=self._fx_seed)
        kind = self.indicator_kind()
        if kind is not None:
            bob = 0.0 if self.reduce_motion() else bob_offset(self._bob_t)
            view.draw_indicator(canvas, page, self._line_id, typer.shown, geometry,
                                page_kind=kind == "page", bob=bob)


def _is_hex(color: str | None) -> bool:
    if color is None or len(color) != 7 or color[0] != "#":
        return False
    try:
        int(color[1:], 16)
    except ValueError:
        return False
    return True


__all__ = ["ADVANCE_KEYS", "CUE_INSET", "CueTarget", "TextSettings", "TextboxScreen"]

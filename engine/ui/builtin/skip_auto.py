"""``SkipAuto``: skip and auto-advance, the player's reading pace (F15 ``SPEC.md`` §2, §5;
``07-architecture-review.md`` I-1 to I-3, I-6, I-8).

Why this module exists: skip fast-forwards through lines and waits, and auto presses by
itself once a segment is fully shown. Both are presentation only (PR-F15-06): they act
solely through F05's ``press()``/``complete_now()`` and F09's ``finish_now()``/``press()``/
``drop_effects()``, so the story sees only the ``Advance`` and ``WaitDone`` a click-through
would post. Neither is in ``GameState`` or a save; a restored ``Say`` and ``reset()`` turn
both off.

``SkipAuto`` is one object in four roles, registered by ``app/skip_auto.py`` (step 3):
an ``InGameOverlay`` on the textbox (``add_overlay``), a ``TypingListener``
(``add_listener``), a say listener (``add_say_listener(skip_auto.on_say)``), and F07's
``MenuListener`` (``app.choices.add_listener``).

- **Clock** (``now``): the sum of ``dt`` over unfrozen frames (invariant 7: no wall clock).
  Frozen = the host is not top (a menu), ``textbox.hidden``, or the window lacks focus
  (``textbox.focused()``). A frozen frame ends skip and holds every auto timer.
- **Skip, each frame** (TR-F15-01): ``drop_effects()``, then at most one action: a stage
  wait → ``finish_now()``; an incomplete line → ``complete_now()``; else, once the complete
  line was drawn, ≥ 50 ms after skip's last line press → ``press()`` (once per line). Under
  ``stage.settings.reduce`` every action that can release a ``ShowStage`` (``finish_now``,
  ``press``) also waits ≥ 333 ms after the last stage change (I-2). It never presses while
  a menu waits under the line.
- **Skip ends** at ``menu_shown``, at an unseen line in seen mode (both keep that line's
  voice: ``set_skipping(False, resume=sid)``, I-3), on an advance input (consumed), Tab, the
  Ctrl release of held skip or another key going down while it is held (I-6), a restored
  ``Say``, ``reset()``, ``stop_skip()``, and any frozen frame.
- **Auto**: ``waiting``/``completed`` start the line timer with ``g`` = graphemes shown
  since the last stop; ``glyph_shown``/``pause_started`` stop it. It presses once
  ``(delay + per_char × g) × auto_scale`` has passed and (``wait_for_voice``) the line's own
  voice is silent (``voice_playing(sid)``). It never shortens a wait (I-1): a wait starting
  cancels the line timer, which presses only while ``stage.wait_kind is None``; in an
  untimed ``pause`` (``"click"``) it calls ``stage.press()`` after ``delay × auto_scale``.
  With skip on, skip acts; auto resumes after.
- **Settings** (I-8): ``settings`` is a ``SkipAutoSettings`` (F16 replaces it whole); a
  ``None`` field is the config value given to the constructor. Read every frame.
- **Indicator** (UI-F15-01): ``indicator`` (a ``SkipIndicator``, set by the install; None
  draws nothing) shows ``words.skip`` while skip is on, else ``words.auto`` while auto is,
  never while ``textbox.hidden``. ``indicator_right()`` is its right edge while shown (F14
  A6: the rewind tag goes 8 to its right).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol

import pygame

from engine.render.frames import FrameSpec
from engine.render.typewriter import WaitKind
from engine.runtime.commands import Say, ShowMenu
from engine.ui.builtin.textbox_screen import ADVANCE_KEYS
from engine.ui.focus import Box
from engine.ui.input import UiEvent
from engine.ui.menus import MenuEntry
from engine.ui.theme import measure_with

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.ui.shell import GameShell

SKIP_INTERVAL_S: Final = 0.05          # TR-F15-01: skip's Advances at least 50 ms apart
REDUCED_GAP_S: Final = 1 / 3           # TR-F15-01, I-2: ≤ 3 stage changes a second
# F15 07 I-7's fallback (v1 perf review): skip holds a line's press while the prefetcher is
# still decoding, at most this long per line, so the pictures ahead come from the cache
# instead of a decode inside a frame; a dropped prefetch can't stall skip.
PREFETCH_HOLD_MAX_S: Final = 0.25
AUTO_SCALE_RANGE: Final = (0.25, 4.0)  # PR-F15-07
DELAY_DEFAULT: Final = 1.0             # [auto] delay (I-5)
PER_CHAR_DEFAULT: Final = 0.04         # [auto] per_char (I-5)
INDICATOR_TOPLEFT: Final = (24, 24)    # UI-F15-01: ui-system §1's reserved corner
INDICATOR_EXTRA_H: Final = 8           # height = quick_menu.text_size + 8
_EPS: Final = 1e-9
_CTRL_KEYS: Final = (pygame.K_LCTRL, pygame.K_RCTRL)
# Tab and A act only with none of these (I-6); Ctrl starts held skip only with none of
# ``_OTHER_MODS``.
_BLOCKING_MODS: Final = pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META | pygame.KMOD_GUI
_OTHER_MODS: Final = pygame.KMOD_SHIFT | pygame.KMOD_ALT | pygame.KMOD_META | pygame.KMOD_GUI

SkipMode = Literal["off", "toggled", "held"]
WaitKindName = Literal["stage", "timed", "click"]


# --- Ports (what F15 needs of F05, F09, F08, F12; step 1 matches these names) -----------------

class SkipTextbox(Protocol):
    """F05's ``TextboxScreen``."""

    @property
    def hidden(self) -> bool: ...

    @property
    def menu_waiting(self) -> bool: ...

    def focused(self) -> bool: ...

    def press(self) -> None: ...

    def complete_now(self) -> None: ...

    def shown_count(self) -> int: ...


class _EffectSettings(Protocol):
    reduce: bool


class SkipStage(Protocol):
    """F09's ``StageScreen``: ``wait_kind`` ``"stage"`` (a ``with``), ``"timed"`` (a timed
    ``pause``), ``"click"`` (an untimed one), or None; ``changes`` counts non-restored
    ``show_stage`` calls; ``settings.reduce`` is the effective reduced-effects flag."""

    @property
    def wait_kind(self) -> WaitKindName | None: ...

    @property
    def changes(self) -> int: ...

    @property
    def settings(self) -> _EffectSettings: ...

    def press(self) -> None: ...

    def finish_now(self) -> None: ...

    def drop_effects(self) -> None: ...

    # ``prefetch_pending`` (optional, read with getattr): the prefetcher still has files
    # queued or a decode in flight (``StageView.prefetch_pending``, I-7).


class SeenStore(Protocol):
    """F12's ``PersistentStore`` (the run's)."""

    def is_seen(self, sid: str) -> bool: ...


class SkipAudio(Protocol):
    """F08's ``AudioService``. ``resume`` (I-3): replay the voice of line ``sid`` that was
    dropped while skipping, if nothing replaced it."""

    def set_skipping(self, on: bool, *, resume: str | None = None) -> None: ...

    def voice_playing(self, sid: str | None = None) -> bool: ...


@dataclass(frozen=True)
class SkipAutoSettings:
    """F16 (PR-F15-07, I-8): ``None`` = config. ``auto_scale`` multiplies the auto delay
    (larger is slower) and is clamped to 0.25–4."""

    skip_all: bool | None = None
    auto_scale: float | None = None
    auto_wait_voice: bool | None = None


class SkipIndicator:
    """UI-F15-01: the corner pill, ``topleft`` (24, 24), in the quick menu's on look. It takes
    no input and never moves (reduce motion changes nothing). The pill shape is cached by the
    shell's ``Painter`` per word width and device size, the text by the asset cache, so a
    frame is two blits."""

    def __init__(self, shell: "GameShell") -> None:
        self.shell = shell
        q = shell.theme.cfg.quick_menu
        self.font = shell.theme.font(q.text_size)
        self._measure = measure_with(shell.assets, self.font)
        self._boxes: dict[str, tuple[str, Box]] = {}     # word key → (text, pill)

    def pill(self, key: str) -> tuple[str, Box]:
        """The word of ``key`` (overrides, then ``[words]``) and its pill box."""
        text = self.shell.words.get(key)
        found = self._boxes.get(key)
        if found is None or found[0] != text:
            q = self.shell.theme.cfg.quick_menu
            width = self._measure(text, q.text_size) + 2 * q.side_padding
            x, y = INDICATOR_TOPLEFT
            found = (text, Box(x, y, width, q.text_size + INDICATOR_EXTRA_H))
            self._boxes[key] = found
        return found

    def draw(self, canvas: "Canvas", key: str) -> None:
        text, box = self.pill(key)
        q = self.shell.theme.cfg.quick_menu
        painter = self.shell.painter
        painter.bind(canvas)
        painter.shape(box, FrameSpec(q.on.fill_color, q.fill_opacity,
                                     border_color=q.on.border_color,
                                     border_width=q.on.border_width,
                                     corner_radius=q.corner_radius))
        canvas.draw_text(text, self.font, q.text_color, box.center, anchor="center")


class SkipAuto:
    """The launch's skip and auto controller (``App.skip_auto``)."""

    def __init__(self, textbox: SkipTextbox, stage: SkipStage, *,
                 store: SeenStore | None, audio: SkipAudio | None,
                 skip_all: bool = False, delay: float = DELAY_DEFAULT,
                 per_char: float = PER_CHAR_DEFAULT, wait_for_voice: bool = True,
                 get_mods: Callable[[], int] = pygame.key.get_mods) -> None:
        self.textbox = textbox
        self.stage = stage
        self.store = store
        self.audio = audio
        self.config_skip_all = bool(skip_all)
        self.config_delay = float(delay)
        self.config_per_char = float(per_char)
        self.config_wait_for_voice = bool(wait_for_voice)
        self.get_mods = get_mods
        self.settings = SkipAutoSettings()
        self.skip: SkipMode = "off"
        self.auto = False
        self.now = 0.0
        self.last_skip_advance = float("-inf")
        self.last_stage_change = float("-inf")
        self._changes = stage.changes
        self._clear_line(None)
        self._menu_open = False
        self._wait_start: float | None = None   # the current stage wait, as F15 saw it
        self.indicator: SkipIndicator | None = None

    # -- settings --

    def skip_all(self) -> bool:
        value = self.settings.skip_all
        return self.config_skip_all if value is None else bool(value)

    def auto_scale(self) -> float:
        value = self.settings.auto_scale
        if value is None:
            return 1.0
        low, high = AUTO_SCALE_RANGE
        return max(low, min(high, float(value)))

    def wait_for_voice(self) -> bool:
        value = self.settings.auto_wait_voice
        return self.config_wait_for_voice if value is None else bool(value)

    def auto_delay(self, graphemes: int) -> float:
        """PR-F15-05: the wait after a segment of ``graphemes`` is fully shown."""
        return (self.config_delay + self.config_per_char * graphemes) * self.auto_scale()

    # -- state --

    @property
    def skipping(self) -> bool:
        return self.skip != "off"

    def skip_enabled(self) -> bool:
        """PR-F15-04: skip may start (the quick menu's Skip is enabled): no menu open and,
        in seen mode, the shown line is seen."""
        if self._menu_open:
            return False
        sid = self._sid
        return self.skip_all() or sid is None or self._seen(sid)

    def start_skip(self, *, held: bool = False) -> bool:
        """Turn skip on (``held``: while Ctrl is down). False when it may not start; a
        held start while skip is toggled on keeps it toggled."""
        if self.skipping:
            return True
        if not self.skip_enabled() or self._frozen(False):
            return False
        self.skip = "held" if held else "toggled"
        if self.audio is not None:
            self.audio.set_skipping(True)
        return True

    def stop_skip(self) -> None:
        """End skip as a freeze does (also F23's seam). Auto is unchanged."""
        self._stop_skip(None)

    def toggle_skip(self) -> None:
        """Tab and the quick menu's Skip."""
        if self.skipping:
            self.stop_skip()
        else:
            self.start_skip()

    def set_auto(self, on: bool) -> None:
        timer = self._line_timer
        if on and not self.auto and timer is not None:
            self._line_timer = (self.now, timer[1])   # a shown segment waits from now
        self.auto = bool(on)

    def toggle_auto(self) -> None:
        """A and the quick menu's Auto."""
        self.set_auto(not self.auto)

    def reset(self) -> None:
        """New Game and the way back to the title (``add_in_game_reset``, I-4), F14's
        landings: both modes off and every timer dropped."""
        self.stop_skip()
        self.auto = False
        self._clear_line(None)
        self._menu_open = False
        self._wait_start = None

    def _stop_skip(self, resume: str | None) -> None:
        if not self.skipping:
            return
        self.skip = "off"
        if self.audio is None:
            return
        if resume is None:
            self.audio.set_skipping(False)
        else:
            self.audio.set_skipping(False, resume=resume)

    def _seen(self, sid: str) -> bool:
        return self.store is not None and self.store.is_seen(sid)

    def _clear_line(self, sid: str | None) -> None:
        self._sid = sid
        self._complete = False           # the line's completed event came
        self._line_drawn = False         # ... and the complete line was drawn since
        self._pressed = False            # skip pressed this line once
        self._held_since: float | None = None   # I-7: skip waits on the prefetch since
        self._shown_at_wait = 0
        self._line_timer: tuple[float, int] | None = None   # (start, graphemes)

    # -- say listener --

    def on_say(self, cmd: Say) -> None:
        """Every ``Say``, before the textbox lays it out (F05 ``add_say_listener``)."""
        self._clear_line(cmd.sid)
        self._menu_open = False
        if cmd.restored:
            self._stop_skip(None)
            self.auto = False
        elif self.skipping and not self.skip_all() and not self._seen(cmd.sid):
            self._stop_skip(cmd.sid)

    # -- TypingListener --

    def glyph_shown(self, index: int, grapheme: str) -> None:
        self._line_timer = None

    def pause_started(self, seconds: float) -> None:
        self._line_timer = None

    def waiting(self, kind: WaitKind) -> None:
        self._segment_shown()

    def completed(self, by_press: bool) -> None:
        self._complete = True
        self._segment_shown()

    def _segment_shown(self) -> None:
        shown = self.textbox.shown_count()
        self._line_timer = (self.now, max(0, shown - self._shown_at_wait))
        self._shown_at_wait = shown

    # -- MenuListener --

    def menu_shown(self, cmd: ShowMenu) -> None:
        self._menu_open = True
        self._stop_skip(self._sid)       # I-3: keep the voice of the line under the menu

    def focus_changed(self, key: str | None) -> None:
        pass

    def picked(self, key: str) -> None:
        self._menu_open = False

    # -- InGameOverlay --

    def handle_event(self, event: UiEvent, *, box_shown: bool) -> bool:
        raw = event.raw
        kind = raw.type
        if kind == pygame.KEYUP:
            if raw.key in _CTRL_KEYS and self.skip == "held":
                self.stop_skip()
            return False
        if kind == pygame.KEYDOWN and getattr(raw, "repeat", False):
            return False
        if self._is_advance(event):
            self._wait_start = None              # a player press may end the wait itself
            if self.skipping:
                self.stop_skip()
                return True                      # consumed: advances nothing
            return False
        if kind != pygame.KEYDOWN:
            return False
        key, mods = raw.key, getattr(raw, "mod", 0)
        if key in _CTRL_KEYS:
            if not self.skipping and not mods & _OTHER_MODS:
                return self.start_skip(held=True)
            return False
        if self.skip == "held":
            self.stop_skip()                     # I-6: another key while Ctrl is held
        if mods & _BLOCKING_MODS:
            return False
        if key == pygame.K_TAB:
            self.toggle_skip()
            return True
        if key == pygame.K_a:
            self.toggle_auto()
            return True
        return False

    @staticmethod
    def _is_advance(event: UiEvent) -> bool:
        raw = event.raw
        kind = raw.type
        if kind == pygame.MOUSEBUTTONDOWN:
            return event.in_canvas and getattr(raw, "button", 0) == 1
        if kind == pygame.KEYDOWN:
            return raw.key in ADVANCE_KEYS
        if kind == pygame.CONTROLLERBUTTONDOWN:
            return getattr(raw, "button", -1) == pygame.CONTROLLER_BUTTON_A
        return False

    def _frozen(self, frozen: bool) -> bool:
        textbox = self.textbox
        return frozen or textbox.hidden or not textbox.focused()

    def update(self, dt: float, *, frozen: bool) -> None:
        if self._frozen(frozen):
            self.stop_skip()
            return                               # the auto timers hold
        self.now += dt
        stage = self.stage
        changes = stage.changes
        if changes != self._changes:
            self._changes = changes
            self.last_stage_change = self.now
        wait = stage.wait_kind
        if wait is None:
            self._wait_start = None
        elif self._wait_start is None:
            self._wait_start = self.now
            self._line_timer = None              # I-1: a wait cancels the line timer
        if self.skip == "held" and not self.get_mods() & pygame.KMOD_CTRL:
            self.stop_skip()                     # I-6: a release under a menu never came
        if self.skipping:
            self._skip_step(wait)
        elif self.auto:
            self._auto_step(wait)

    def _skip_step(self, wait: WaitKindName | None) -> None:
        stage, textbox, now = self.stage, self.textbox, self.now
        stage.drop_effects()
        stage_ok = not stage.settings.reduce \
            or now - self.last_stage_change >= REDUCED_GAP_S - _EPS
        if wait is not None:
            if stage_ok:
                stage.finish_now()
            return
        if self._sid is None:
            return
        if not self._complete:
            textbox.complete_now()
            return
        if self._pressed or not self._line_drawn or self._menu_open \
                or textbox.menu_waiting or not stage_ok \
                or now - self.last_skip_advance < SKIP_INTERVAL_S - _EPS:
            return
        if getattr(stage, "prefetch_pending", False):            # I-7 (v1 perf review)
            held = self._held_since
            if held is None:
                self._held_since = held = now
            if now - held < PREFETCH_HOLD_MAX_S - _EPS:
                return
        self._pressed = True
        self.last_skip_advance = now
        textbox.press()

    def _auto_step(self, wait: WaitKindName | None) -> None:
        now = self.now
        if wait is not None:
            start = self._wait_start
            if wait == "click" and start is not None \
                    and now - start >= self.config_delay * self.auto_scale() - _EPS:
                self._wait_start = None
                self.stage.press()
            return
        timer = self._line_timer
        if timer is None or self._menu_open or self.textbox.menu_waiting:
            return
        start, graphemes = timer
        if now - start < self.auto_delay(graphemes) - _EPS:
            return
        audio, sid = self.audio, self._sid
        if self.wait_for_voice() and audio is not None and sid is not None \
                and audio.voice_playing(sid):
            return
        self._line_timer = None
        self.textbox.press()

    def draw(self, canvas: "Canvas", *, box_shown: bool) -> None:
        if self._complete and box_shown:
            self._line_drawn = True
        key = self._indicator_key()
        if key is not None:
            assert self.indicator is not None
            self.indicator.draw(canvas, key)

    def _indicator_key(self) -> str | None:
        """The word the corner pill shows now, or None when it isn't drawn."""
        if self.indicator is None or self.textbox.hidden:
            return None
        return "skip" if self.skipping else "auto" if self.auto else None

    def indicator_right(self) -> float | None:
        """F14 A6: the corner pill's right edge (canvas units) while it shows, else None
        (F14's rewind tag sits 8 to its right)."""
        key = self._indicator_key()
        if key is None:
            return None
        assert self.indicator is not None
        return self.indicator.pill(key)[1].right


def register_skip_auto(shell: "GameShell", skip_auto: SkipAuto) -> None:
    """PR-F15-04: the quick menu's on/off ``skip`` and ``auto`` (their places come from
    ``DEFAULT_ORDER``). Skip is disabled while it may not start (a menu open, or an unseen
    line in seen mode) and enabled while on, so a click can always end it."""
    def skip_enabled() -> bool:
        return skip_auto.skipping or skip_auto.skip_enabled()

    shell.menus.add("quick", MenuEntry("skip", action=lambda ctx: skip_auto.toggle_skip(),
                                       enabled=skip_enabled,
                                       on=lambda: skip_auto.skipping))
    shell.menus.add("quick", MenuEntry("auto", action=lambda ctx: skip_auto.toggle_auto(),
                                       on=lambda: skip_auto.auto))


__all__ = ["AUTO_SCALE_RANGE", "PREFETCH_HOLD_MAX_S", "REDUCED_GAP_S", "SKIP_INTERVAL_S",
           "SeenStore", "SkipAudio",
           "SkipAuto", "SkipAutoSettings", "SkipIndicator", "SkipStage", "SkipTextbox",
           "register_skip_auto"]

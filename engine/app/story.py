"""The story in the window: ``RuntimeStoryDriver`` and ``install_story`` (F03
``04-technical.md`` §5.3, §7.3).

Why this module exists: the runtime has no clock, entropy, or thread (invariant 7), and the
presentation never calls it directly (invariant 5). The driver is the ``StoryDriver`` the
``App`` pumps once per frame: it hands the frame's events to the interpreter, runs the story
for at most one short time slice, and returns the released commands, which the App's
router sends to their one handler each. It also supplies the seed of every new game.

``install_story`` is the one place that wires a launched story into the App, once per
launch (``app/loading.py`` calls it after the launch phase). Seams, one line each:
- F05 step 6 (C2 e): ``install_textbox`` builds the launch's ``TextboxScreen`` and registers
  ``Say`` → ``TextboxScreen.show``, after ``install_stage`` (F03's stand-in is gone).
- F10 (C9, I-2): ``install_ui`` here after the presentation installs, the installs that
  register menu entries after it, and ``shell.check_entries()`` (W66) last; ``StoryEnded``
  goes to the shell (``_story_ended``), after F12's ``persist.flush_soon()`` (F12 I-1).
- F04 step 5: ``install_stage`` builds the launch's ``StageScreen`` and registers the
  ``ShowStage`` and ``PrefetchImages`` handlers (F09 C6); step 7's ``ImagePrefetcher`` is
  built there and its ``stop`` is an ``App.add_shutdown`` hook. F09 step 2: it also
  registers ``StoryWait``, ``Shake``, and ``Flash``, and runs after ``install_textbox`` so it
  can set ``textbox.on_idle_advance = stage_screen.press``.
- F03 step 12: ``start_watchdog`` starts the launch's one ``Watchdog`` before the launch
  phase (``app/loading.py``: it guards every define), keeps it on ``app.watchdog``, and adds
  its ``stop`` to the App's shutdown hooks; it is the guard of the launch job and of the
  interpreter that ``install_story`` wires.
- F03 step 13: the ``--seed`` value arrives as ``fixed_seed``.
- F08 step 4 (I-8): ``install_audio`` registers ``App.audio``'s handlers for the nine audio
  commands (the service is built by the bootstrap). An App with no service (wired by hand)
  gets ``install_no_audio``'s handlers that do nothing, so its story still runs (the router
  raises on a command with no handler).
- F13 step 3 (I-6): ``install_history`` registers the History page and quick entry after
  ``install_ui`` and before ``check_entries``.
- F11 step 8 (``04`` §7.1): ``install_saves`` beside it sets ``App.saves`` (the ``save``
  writer client, the quick entries and F5/F9, the slot index).
- F18 step 3: ``install_chapters`` right after ``install_saves`` (``ChapterStarted`` →
  ``App.saves.request_autosave()``, the card painter on the stage, ``name_saves``, W111).
- F14 step 4 (``07`` §3.4 A6): ``install_rollback`` after ``install_saves`` and
  ``install_chapters``, before ``install_skip_auto`` (overlay order F10, F11, F14, F15): the
  ``RollbackKeys`` overlay, the quick menu's Back, F11's report and F15's landing listener
  on the driver (``add_report_listener``, ``add_landing_listener``).
- F15 step 3 (``07`` I-8): ``install_skip_auto`` sets ``App.skip_auto`` (skip, auto, the
  quick menu's Skip and Auto, the corner indicator), after the other entry installs.
- F17 step 2 (``07`` I-7; F14 ``07`` A6): ``install_textbox`` registers ``NvlPage →
  TextboxScreen.show_nvl``; ``install_nvl`` adds F17's in-game reset right after
  ``install_skip_auto`` (order ``install_saves``, ``install_rollback``,
  ``install_skip_auto``, ``install_nvl``), so it runs after F15's.
- F16 step 4 (``07`` I-11): ``install_settings_ui`` registers the Settings entries last,
  before ``check_entries`` (after F15's ``install_skip_auto``).
- F22 step 3 (``07`` I-1): ``install_points`` adds the meters' F3 overlay lines (dev runs).
- F21 step 3 (``07`` I-11): ``install_codex`` registers ``CodexAdded`` → a notice and the
  codex entries after ``install_nvl`` and before ``install_settings_ui``.
- F23 s4 (``04`` §2): ``install_minigames`` registers ``StartMinigame`` → the
  ``MinigameHost`` and its listeners, right after ``install_codex``.
- F20 s6 (``07`` I-12): ``install_flowchart`` sets ``App.flow`` (node states, jumps) right
  after ``install_minigames``, before ``install_settings_ui``; F20 s8's
  ``install_flowchart_page`` (the page's cache and its two entries) right after it.
- F30 s4 (``04`` §6.1, §6.2): ``install_fourthwall`` registers ``WindowTitle`` (the window's
  title bar) and ``FakeCrash`` (the fake error page over the stage's wait), and the title
  reset among the shell's in-game resets, right after ``install_nvl``.
- F32 s4 (``04`` §6.2): ``install_looks`` right after ``install_ui``: the shell's ``Looks``,
  W207/W67/W206, and the ``UiStyle``, ``UiBlocks``, ``DeleteSaves`` handlers.
- F34 W3 (``04`` §3, §7.3): ``install_extras`` (the title's Extras button, the launch's
  ``ThumbCache``) then ``install_gallery`` (the Gallery page's Extras row) right after
  ``install_flowchart_page``, before ``install_settings_ui``; F35–F37 add their Extras rows
  after them. Dev ``run --extras``: ``preview_all`` unlocks every Extras name in the memory
  store after every install, just before ``check_entries``. ``install_stage`` keeps the
  launch's ``ImagePrefetcher`` on ``app.prefetcher`` (the thumbnails use it on the title).
- F35 S2 (``SPEC.md`` §5.1, §5.2): ``install_music_room`` right after ``install_gallery``:
  the ``"track"`` kind (before ``preview_all``, 07 I-6), F08's ``on_track_started`` hook,
  and the Music Room's Extras row.
- F36 W3 (``04`` §3, §7.4): ``install_replays`` right after ``install_music_room``: the
  Endings and Scenes Extras rows, the shell's replay port, and dev ``run --replay``. The
  driver starts a replay (``start_replay(run)``: a seed as ``new_game``'s, the inbox
  cleared) and stops one (``stop_replay()``, only while it runs).
- F37 S2 (``SPEC.md`` §5.1, §5.3; F36 ``07`` I-13): ``install_achievements`` right after
  ``install_replays``: F12's unlock listener (the ``Achievement unlocked`` notice with its
  icon, then the platform hook), ``HookRunner.started`` once, and the Achievements Extras
  row. The ``"achievement"`` kind is the interpreter's.

The watchdog (§7.7; the thread rule of ``docs/architecture.md``, ``07`` §3.3): author code
runs only on the main thread, between ``guard.enter()`` and ``guard.exit()``. The watchdog's
one daemon thread only looks at its own counters under its lock and, when one author call
has run for ``AUTHOR_CODE_LIMIT_S``, interrupts the main thread with SIGINT. It never touches
``GameState``, the namespace, or the interpreter. Every catch layer (``Interpreter.run``,
``restore``, new game, ``LaunchJob.step``, the driver's ``pump``, and ``App.run`` last, I-8)
asks ``consume_fired()``: fired → E85m, otherwise a real Ctrl+C goes on to F01's interrupt
path (exit code 0).

Known limits: author code that catches ``KeyboardInterrupt`` itself defeats the watchdog
(trusted code, §7.7), and a single C call that never checks for signals (``10**10**9``)
can't be interrupted (``04`` §2). A blocking call such as ``time.sleep(30)`` is woken: the
interrupt is a real SIGINT to the main thread (``interrupt_main``), not only
``_thread.interrupt_main()``, which on Windows lets the sleep run to its end first.
"""

import _thread
import random
import secrets
import signal
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING

from engine import __version__
from engine.app.achievements import install_achievements
from engine.app.chapters import install_chapters
from engine.app.clockcorner import install_clock
from engine.app.checkroll import install_check_roll
from engine.app.choices import install_choices
from engine.app.codex import install_codex
from engine.app.inbox import install_inbox
from engine.app.extras import install_extras, preview_all
from engine.app.flowchart import install_flowchart
from engine.app.flowchart_ui import install_flowchart_page
from engine.app.fourthwall import install_fourthwall
from engine.app.gallery import install_gallery
from engine.app.history import install_history
from engine.app.looks import install_looks
from engine.app.menus import install_ui
from engine.app.minigames import install_minigames
from engine.app.musicroom import install_music_room
from engine.app.meters import install_meters
from engine.app.points import install_points
from engine.app.replays import install_replays
from engine.app.rollback import install_rollback
from engine.app.saves import install_saves
from engine.app.settings import install_settings_ui
from engine.app.skip_auto import install_skip_auto
from engine.core.logsetup import get_logger
from engine.core.redact import echo
from engine.render.effects import EffectLayer, EffectSettings, RefusalLog
from engine.render.glitch import GlitchLayer
from engine.render.prefetch import ImagePrefetcher
from engine.render.spriteanim import AnimSettings, SpriteAnimator
from engine.render.stage import StageView
from engine.app.text_check import install_nvl, install_sprite_anim, install_textbox
from engine.runtime import limits
from engine.runtime.commands import (AudioRestore, EndVoice, Event, Flash, Glitch,
                                     PlayMusic, PlaySound, PlayVoice, PrefetchImages,
                                     QueueMusic, RollbackView, Shake, ShowStage, StopMusic,
                                     StopSound, StopVoice, StoryEnded, StoryFailed, StoryWait)
from engine.runtime.errors import StoryError, log_error, timeout_error
from engine.runtime.images import BLACK, ImageIndex, SolidColor, look_frames
from engine.runtime.interpreter import Interpreter, RestoreOutcome, RestoreResult, Status
from engine.runtime.limits import RUN_CHUNK_STEPS, RUN_SLICE_S
from engine.runtime.state import GameState
from engine.ui.builtin.placeholder import PlaceholderScreen
from engine.ui.builtin.stage_screen import StageScreen

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.replay import ReplayRun

INBOX_MAX = 64                       # events queued between two pumps; extras are dropped
PUMP_MAX_COMMANDS = 256              # commands returned by one pump; the rest spill over
_NO_ROLLBACK = RollbackView(False, False, 0, 0, 0)       # F14: the view once FAILED

_log = get_logger("runtime")


def random_seed() -> int:
    """A fresh 64-bit seed for one new game (PR-F03-15)."""
    return secrets.randbits(64)


# --- Watchdog (§7.7) ------------------------------------------------------------------------

WATCHDOG_TICK_S = 0.25               # the thread looks at least every 0.25 s


def interrupt_main() -> None:
    """Interrupt the main thread the way a Ctrl+C does, so even a blocking call
    (``time.sleep``) wakes with ``KeyboardInterrupt``: on Windows ``signal.raise_signal``
    (the C handler sets the event the main thread's waits watch), elsewhere SIGINT sent to
    the main thread. Like ``_thread.interrupt_main()`` it does nothing unless SIGINT has a
    Python handler (F01 keeps ``signal.default_int_handler``), so it can never kill the
    process; if the signal can't be sent, ``_thread.interrupt_main()`` is the fallback."""
    if not callable(signal.getsignal(signal.SIGINT)):
        return
    try:
        if sys.platform == "win32":
            signal.raise_signal(signal.SIGINT)
        else:
            ident = threading.main_thread().ident
            assert ident is not None
            signal.pthread_kill(ident, signal.SIGINT)
    except (AttributeError, OSError, ValueError, AssertionError):
        _thread.interrupt_main()


class Watchdog:
    """The ``AuthorCodeGuard`` of the windowed game (§7.7): one daemon thread that interrupts
    author code once one call has run ``limits.AUTHOR_CODE_LIMIT_S`` without returning.

    ``enter``/``exit``/``consume_fired`` run on the main thread: per guarded call, two
    uncontended lock round-trips and one clock read (about 0.25 µs). Each ``enter`` starts a
    new call (``gen``) and notes when it started; the thread fires at most once per call and
    only while it is still active. It looks every ``tick`` seconds, or sooner when the
    running call reaches the limit first, so E85m shows within one OS timer step after the
    limit (5.0–5.05 s; §7.7's design gave 5.0–5.25 s, and polling alone came out at up to
    5.3 s on Windows, where a 0.25 s wait lasts up to 0.28 s). The thread touches only
    these counters (the thread rule); ``check`` is one look (tests call it on a fake
    clock)."""

    def __init__(self, *, clock: Callable[[], float] = time.perf_counter,
                 interrupt: Callable[[], None] = interrupt_main,
                 tick: float = WATCHDOG_TICK_S) -> None:
        self._clock = clock
        self._interrupt = interrupt
        self._tick = tick
        self._lock = threading.Lock()
        self._gen = 0                 # author calls entered so far
        self._started = 0.0           # when the latest call entered
        self._active = False          # that call is still running
        self._fired = False           # interrupted, and no catch layer has asked yet
        self._fired_gen = -1          # the call that was interrupted (once per call)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- AuthorCodeGuard (main thread) ------------------------------------------------------

    def enter(self) -> None:
        started = self._clock()
        with self._lock:
            self._gen += 1
            self._started = started
            self._active = True

    def exit(self) -> None:
        with self._lock:
            self._active = False

    def consume_fired(self) -> bool:
        """True once after the watchdog interrupted author code; the catch layer that gets
        True shows E85m, any other ``KeyboardInterrupt`` is a real Ctrl+C."""
        with self._lock:
            fired, self._fired = self._fired, False
            return fired

    # --- The thread ------------------------------------------------------------------------

    def check(self) -> bool:
        """One look: True when it interrupted the main thread just now."""
        with self._lock:
            if (not self._active or self._fired_gen == self._gen
                    or self._clock() - self._started < limits.AUTHOR_CODE_LIMIT_S):
                return False
            self._fired = True
            self._fired_gen = self._gen
        self._interrupt()             # outside the lock: the main thread may be waiting on it
        return True

    def next_look(self) -> float:
        """Seconds until the thread looks again: ``tick``, or less when the running call
        reaches the limit sooner."""
        with self._lock:
            if self._active and self._fired_gen != self._gen:
                left = self._started + limits.AUTHOR_CODE_LIMIT_S - self._clock()
                return max(0.0, min(self._tick, left))
        return self._tick

    def start(self) -> None:
        """Start the thread (once; a stopped watchdog is not restarted)."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="vn-watchdog",
                                            daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """End the thread (an ``App.add_shutdown`` hook); it never interrupts after this."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        stop = self._stop
        wait = self._tick
        while not stop.wait(wait):
            self.check()
            wait = self.next_look()


def start_watchdog(app: "App") -> Watchdog:
    """The launch's one ``Watchdog``: started, kept on ``app.watchdog`` (I-8: ``App.run``
    asks it last), and stopped by the App's shutdown hooks. Called by ``StoryLoadScreen``
    before the launch phase; a second call returns the same one. An App wired by hand
    with no ``add_shutdown`` gets a watchdog that is never started (it never fires)."""
    watchdog = getattr(app, "watchdog", None)
    if isinstance(watchdog, Watchdog):
        return watchdog
    watchdog = Watchdog()
    app.watchdog = watchdog
    add_shutdown = getattr(app, "add_shutdown", None)
    if add_shutdown is not None:                 # an App wired by hand (tests) may lack it
        add_shutdown(watchdog.stop)
        watchdog.start()
    return watchdog


def watchdog_timeout_error(app: "App") -> StoryError:
    """I-8: the error ``App.run`` shows when the watchdog's interrupt reached it past every
    other catch layer. With a story, E85m at its current statement (the story ends FAILED,
    logged once); during the launch phase, E85m with no place (logged here)."""
    driver = app.story
    if isinstance(driver, RuntimeStoryDriver):
        return driver.fail_timeout()
    error = timeout_error(None)
    log_error(_log, error)
    return error


class RuntimeStoryDriver:
    """Implements ``engine.app.dispatch.StoryDriver`` over one ``Interpreter``."""

    def __init__(self, interp: Interpreter, *, clock: Callable[[], float] = time.perf_counter,
                 seed_source: Callable[[], int] = random_seed,
                 fixed_seed: int | None = None) -> None:
        self.interp = interp
        self.fixed_seed = fixed_seed
        self._clock = clock
        self._seed_source = seed_source
        self._inbox: deque[Event] = deque()
        # F14 (04 §5.3, I-3): the timeline's counters at the last pump's end, and who hears
        # when they change: report listeners (landings and matches: F11 ``note_restore``),
        # then landing listeners (landings only: F15 ``reset``).
        timeline = interp.timeline
        self._landings = timeline.landings
        self._matches = timeline.matches
        self._report_listeners: list[Callable[[], None]] = []
        self._landing_listeners: list[Callable[[], None]] = []

    @property
    def status(self) -> Status:
        return self.interp.status

    def rollback_view(self) -> RollbackView:
        """F14 (04 §5.3, §7.6): Back's room and the steps ahead, O(1). All zero once the
        story FAILED (the error screen)."""
        interp = self.interp
        if interp.status is Status.FAILED:
            return _NO_ROLLBACK
        return interp.timeline.view(interp)

    def add_report_listener(self, fn: Callable[[], None]) -> None:
        """F14 → F11 (F18 ``07`` I-6): ``fn()`` once at the end of each pump in which a
        rollback landing or a matched arrival happened (``note_restore``), before the
        commands are dispatched and before ``saves.update``."""
        self._report_listeners.append(fn)

    def add_landing_listener(self, fn: Callable[[], None]) -> None:
        """F14 → F15: ``fn()`` once at the end of each pump in which a rollback landing
        happened (a back, or a forward chain's landing), after the report listeners; a
        matched click, skip, or auto arrival never calls it (``06`` G1)."""
        self._landing_listeners.append(fn)

    def _report(self) -> None:
        """I-3: the last thing ``pump`` does (a back landing leaves the story WAITING, so
        this sits outside the run block)."""
        timeline = self.interp.timeline
        landings, matches = timeline.landings, timeline.matches
        if landings == self._landings and matches == self._matches:
            return
        landed = landings != self._landings
        self._landings, self._matches = landings, matches
        for fn in tuple(self._report_listeners):
            fn()
        if landed:
            for fn in tuple(self._landing_listeners):
                fn()

    def post(self, event: object) -> None:
        """Queue ``event`` for the next pump; past ``INBOX_MAX`` it is dropped (DEBUG)."""
        if len(self._inbox) >= INBOX_MAX:
            _log.debug("Story event dropped: %d events are already waiting (%s)",
                       INBOX_MAX, type(event).__name__)
            return
        self._inbox.append(event)  # type: ignore[arg-type]

    def pump(self, max_commands: int = PUMP_MAX_COMMANDS) -> list[object]:
        """§7.3: post the queued events, then run the story for one slice of about
        ``RUN_SLICE_S`` (only while no released command waits), and return at most
        ``max_commands`` released commands, oldest first. F14 (04 §5.3): the story runs
        while ``interp.busy`` (RUNNING, or inside a forward chain, which may span pumps);
        then, last (I-3), the report and landing listeners hear of the pump's landings and
        matches."""
        interp = self.interp
        inbox = self._inbox
        while inbox:
            interp.post(inbox.popleft())
        if interp.busy and not interp.released:
            clock = self._clock
            deadline = clock() + RUN_SLICE_S
            try:
                while interp.busy:
                    interp.run(RUN_CHUNK_STEPS)
                    if clock() >= deadline:
                        break
            except KeyboardInterrupt:
                if not interp.guard.consume_fired():
                    raise                            # a real Ctrl+C: F01's interrupt path
                interp.fail_timeout()                # E85m at the current statement
        self._report()
        return interp.take_commands(max_commands)  # type: ignore[return-value]

    def consume_fired(self) -> bool:
        """I-8: True once if the story's guard (the watchdog) interrupted author code."""
        return self.interp.guard.consume_fired()

    def fail_timeout(self) -> StoryError:
        """I-8: end the story with E85m at its current statement (logged once) and return
        the error; the App shows it. Commands not yet taken are dropped."""
        error = self.interp.fail_timeout()
        self.interp.take_commands(1 << 30)
        return error

    def new_game(self) -> None:
        """Start the story from its first line; the seed is ``fixed_seed`` when set, else
        a fresh one from ``seed_source``. Events queued for the previous game are
        dropped."""
        seed = self.fixed_seed if self.fixed_seed is not None else self._seed_source()
        self._inbox.clear()
        self.interp.new_game(seed)

    def start_replay(self, run: "ReplayRun") -> None:
        """F36: a new game that is the replay ``run`` (``Interpreter.new_game(seed,
        replay=run)``), seeded and with the inbox cleared as ``new_game``. The caller has
        checked that ``run.scene`` is a label."""
        seed = self.fixed_seed if self.fixed_seed is not None else self._seed_source()
        self._inbox.clear()
        self.interp.new_game(seed, replay=run)

    def stop_replay(self) -> None:
        """F36: End Replay or the way back to Extras while the replay still runs
        (``Interpreter.stop_replay``: the store put back, nothing more released); events
        queued for it are dropped. Nothing once it has ended."""
        if self.interp.replay is None:
            return
        self._inbox.clear()
        self.interp.stop_replay()

    def checkpoint(self) -> GameState | None:
        """The last checkpoint (F11 saves, F14 rollback); None before the first line and
        after a failure."""
        return self.interp.checkpoint()

    def restore(self, state: GameState, *, use_hints: bool = False,
                check_only: bool = False, fresh_menu: bool = False) -> RestoreOutcome:
        """Go back to ``state`` (F11 load, F14 rollback, F39 reload); the line shows again
        at the next pump. Works in every status. On ``OK`` the events queued for the old
        position are dropped. Any other result changes nothing and never fails the running
        story: for ``DEFAULT_FAILED`` the error is already logged once (``error.logged``),
        and a load shows a notice, never the error screen (F11 C12).

        ``check_only`` (F11 C10) only checks the position: nothing changes, the queued
        events included, whatever the result. ``fresh_menu`` (F20 ``04`` §7.6): a jump,
        whose menu checks its conditions again (``Interpreter.restore``)."""
        outcome = self.interp.restore(state, use_hints=use_hints, check_only=check_only,
                                      fresh_menu=fresh_menu)
        if outcome.result is RestoreResult.OK and not check_only:
            self._inbox.clear()
        return outcome


def install_story(app: "App", interp: Interpreter, *, fixed_seed: int | None,
                  images: ImageIndex | None = None) -> RuntimeStoryDriver:
    """Once per launch: ``app.story`` becomes the driver, the router gets the one handler
    of each story command (``Say`` → ``TextboxScreen.show``, ``ShowMenu`` → F07's
    ``ChoiceController.show`` on ``app.choices``, ``ShowStage`` and ``PrefetchImages`` → the stage, ``StoryEnded`` → the shell's ``story_ended``, ``StoryFailed`` →
    ``app.show_fatal_error``, F01's error screen), and F10's ``install_ui`` sets
    ``app.shell``. ``images`` is the launch's ``ImageIndex`` (``LaunchResult.images``; None
    without a game folder: only the built-in ``black``). The caller then shows
    ``build_initial_screens(app)``: the title, or the first game with start options.
    The watchdog (§5.3) was started before the launch phase (``start_watchdog``) and is
    already ``interp.guard``."""
    driver = RuntimeStoryDriver(interp, fixed_seed=fixed_seed)
    app.story = driver
    router = app.router
    router.register(StoryEnded, lambda cmd: _story_ended(app, cmd))
    router.register(StoryFailed, lambda cmd: _story_failed(app, cmd.error))
    install_audio(app)                                       # F08: App.audio's handlers
    install_points(app, interp)                              # F22: meters on F3 (dev)
    # Presentation installs: install_ui needs them.
    textbox = install_textbox(app)                           # F05: Say → TextboxScreen.show
    install_stage(app, images if images is not None else builtin_images())   # after it (F09)
    install_choices(app, textbox)                            # F07: ShowMenu; app.choices
    shell = install_ui(app)                                  # F10 (C9): sets app.shell
    install_looks(app, interp)                               # F32 s4: right after install_ui
    # Installs that register menu entries (app.shell.menus.add) go here: F11, F13, F15, F16.
    install_history(app)                                     # F13 (I-6): History
    install_saves(app)                                       # F11 (04 §7.1): App.saves
    install_chapters(app)                                    # F18: card, chapter auto-save
    install_rollback(app)                                    # F14 (A6): after F11, before F15
    install_skip_auto(app)                                   # F15: App.skip_auto
    install_nvl(app)                                         # F17 (I-7): reset after F15's
    install_meters(app, interp)                              # F62: shown meters, corner
    install_clock(app, interp)                               # F63: clock corner, slot time
    install_fourthwall(app)                                  # F30: title bar, fake crash
    install_check_roll(app)                                  # F59: the dice of a check
    install_codex(app, interp, images)                       # F21 (I-11): notices, Codex
    install_inbox(app, interp, images)                       # F65: the Inbox, notices, open
    install_minigames(app, interp, images)                   # F23 s4: after F21, before F16
    install_flowchart(app, interp)                           # F20 (07 I-12): App.flow
    install_flowchart_page(app, interp)                      # F20 s8: page, entries
    install_extras(app)                                      # F34: Extras button, thumbnails
    install_gallery(app, interp, images)                     # F34: the Gallery page
    install_music_room(app, interp)                          # F35: the Music Room page
    install_replays(app, interp, images)                     # F36: Endings, Scenes, replays
    install_achievements(app, interp, images)                # F37: notice, hook, the page
    install_settings_ui(app)                                 # F16 (I-11): last entry install
    preview_all(app, interp.persistent)                      # F34: run --extras only
    shell.check_entries()                                    # W66, W68: always the last line
    return driver


# F08 §5.1: the nine audio commands.
AUDIO_COMMANDS: tuple[type, ...] = (PlayMusic, QueueMusic, StopMusic, PlaySound, StopSound,
                                    PlayVoice, EndVoice, StopVoice, AudioRestore)


def _no_audio(cmd: object) -> None:
    """The stand-in handler of an App with no audio service: the story plays silently."""


def install_no_audio(app: "App") -> None:
    """Register ``_no_audio`` for every audio command (an App with no ``AudioService``)."""
    for command_type in AUDIO_COMMANDS:
        app.router.register(command_type, _no_audio)


def install_audio(app: "App") -> None:
    """F08 I-8: ``App.audio`` registers its handler for each of the nine audio commands;
    without a service (``App.audio`` None or absent), ``install_no_audio``."""
    audio = getattr(app, "audio", None)
    if audio is None:
        install_no_audio(app)
    else:
        audio.register(app.router)


def builtin_images() -> ImageIndex:
    """The index of a story with no image scan: only the built-in ``black`` (SR-F04-05)."""
    return ImageIndex({BLACK: SolidColor((0, 0, 0))})


def install_stage(app: "App", index: ImageIndex) -> StageScreen:
    """F04 §5.4, F09 C6: build the launch's one ``StageView`` (from ``[stage]``,
    ``[theme.stage]``, ``[effects]``, and ``[theme.effects]``) and ``StageScreen``, keep the
    screen on ``app.stage_screen`` (the bottom of ``bootstrap.in_game_screens``), and
    register ``ShowStage → StageScreen.show_stage``, ``PrefetchImages →
    StageView.prefetch``, F09's ``StoryWait``, ``Shake``, ``Flash``, and F28's ``Glitch``
    (its ``GlitchLayer`` from ``[effects] glitch``/``glitch_size``). F38: one
    ``SpriteAnimator`` (``[animation]``, the index's frames, its own ``random.Random()``) on
    ``app.sprite_anim`` and the screen, fed by the textbox (``install_sprite_anim``). The launch's
    textbox (``install_textbox`` runs first) sends idle advances to ``StageScreen.press``.
    The view and the ``EffectLayer`` (``[effects]`` and ``[theme.effects]`` defaults) get
    the location formatter of W61/W62 (``ui`` and ``render`` import no ``script``);
    ``StageScreen.settings`` starts as ``[effects] reduce``. The launch's one ``ImagePrefetcher`` (§7.7) is stopped by ``App``'s
    shutdown hooks (``add_shutdown``)."""
    config = app.config
    prefetcher = ImagePrefetcher(app.assets)
    app.prefetcher = prefetcher                     # type: ignore[attr-defined]  # F34 thumbs
    add_shutdown = getattr(app, "add_shutdown", None)
    if add_shutdown is not None:
        add_shutdown(prefetcher.stop)
    effects = config.effects
    theme = config.theme
    locate = lambda sid: statement_location(app, sid)          # noqa: E731
    view = StageView(app.assets, index, art_height=config.stage.art_height,
                     positions=config.stage.positions,
                     empty_color=theme.stage.empty_color, prefetcher=prefetcher,
                     seconds={"dissolve": effects.dissolve, "fade": effects.fade,
                              "glitch": effects.glitch},             # F28 (07 I-10)
                     fade_color=theme.effects.fade_color, locate=locate)
    # F38: frames by name (the picture names built once); presentation entropy, never the
    # story's dice.
    frames = look_frames(index)
    view.frames_of = frames
    anim = SpriteAnimator(frames, random.Random(), AnimSettings.from_config(config.animation))
    app.sprite_anim = anim                                          # type: ignore[attr-defined]
    layer = EffectLayer(shake_seconds=effects.shake, shake_size=effects.shake_size,
                        flash_seconds=effects.flash, flash_color=theme.effects.flash_color,
                        empty_color=theme.stage.empty_color, refusals=RefusalLog(locate))
    # F28: ``[effects] glitch``/``glitch_size``; presentation entropy (04 §4.3).
    glitches = GlitchLayer(seconds=effects.glitch, size=effects.glitch_size,
                           refusals=layer.refusals, seed=time.monotonic_ns())
    # ``[effects] reduce``; F16 (step 3) replaces ``settings`` with config OR the player's.
    screen = StageScreen(app, view, effects=layer,
                         settings=EffectSettings(reduce=effects.reduce), glitches=glitches,
                         anim=anim)
    app.stage_screen = screen
    router = app.router
    router.register(ShowStage, screen.show_stage)
    router.register(PrefetchImages, view.prefetch)
    router.register(StoryWait, screen.start_wait)                     # F09
    router.register(Shake, screen.shake)
    router.register(Flash, screen.flash)
    router.register(Glitch, screen.glitch)                            # F28
    textbox = getattr(app, "textbox", None)
    if textbox is not None:
        textbox.on_idle_advance = screen.press
        install_sprite_anim(textbox, anim)                            # F38
    return screen


def statement_location(app: "App", sid: str) -> str:
    """F09 W61/W62's prefix: ``script/main.vns, line 6: `` for the statement ``sid`` of the
    running story, or "" when it has none (``Program.get``; ``app`` imports no ``script``)."""
    program = getattr(getattr(app.story, "interp", None), "program", None)
    stmt = program.get(sid) if program is not None else None
    if stmt is None:
        return ""
    return f"{echo(stmt.file.ref)}, line {stmt.line}: "


def _story_failed(app: "App", error: BaseException) -> None:
    """F01's error screen (exit code 1). A run-time ``StoryError`` was already logged by the
    interpreter with its script frames (§7.11), so the App doesn't log it again."""
    if getattr(error, "logged", False) is True:
        app.show_fatal_error(error, already_logged=True)
    else:
        app.show_fatal_error(error)


def _story_ended(app: "App", cmd: StoryEnded) -> None:
    """The story's end: F12's persistent data is written soon (F12 I-1; no ``App.persist``
    before F12), then F10's shell fades to the title (C9). Without a shell (an App wired by
    hand, as in tests) F01's placeholder replaces the stack (PR-F03-03)."""
    persist = getattr(app, "persist", None)
    if persist is not None:
        persist.flush_soon()
    shell = getattr(app, "shell", None)
    if shell is not None:
        shell.story_ended(cmd)
        return
    app.screens.replace_all([PlaceholderScreen(title=app.config.game.title,
                                               engine_version=__version__)])


__all__ = ["AUDIO_COMMANDS", "INBOX_MAX", "PUMP_MAX_COMMANDS", "WATCHDOG_TICK_S",
           "RuntimeStoryDriver", "Watchdog", "builtin_images", "install_audio",
           "install_no_audio", "install_stage", "install_story", "interrupt_main",
           "random_seed", "start_watchdog", "statement_location", "watchdog_timeout_error"]

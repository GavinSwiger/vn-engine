"""The frame loop: events, story, update, present, pacing, error mode, quitting, bench.

Why this module exists: every frame of every game runs through ``App.run``. It paces
frames with the limiter (PR-F01-46), keeps game time continuous across stalls, resizes,
and fullscreen toggles (PR-F01-47, 48, 66), handles the global keys (F11, Alt+Enter, F3;
Esc is left to F10, PR-F01-33), sleeps while minimized (PR-F01-50), skips frames while the
framebuffer is empty, and re-lays out the canvas on the very next frame after a size change
(PR-F01-23). Any exception in a frame switches to the error mode: the stack is replaced by
the ``ErrorScreen`` (PR-F01-41) and closing it exits with code 1. A ``KeyboardInterrupt``
is a Ctrl+C and ends the loop (exit code 0), unless the story's watchdog sent it (F03 I-8:
E85m on the error screen). Later features plug in
through the screen stack, the story driver and command router, quit guards, and shutdown
hooks (``add_shutdown``: run once in reverse order after the loop ends, each on its own, so
one failure never skips the rest; F04's prefetcher stop, F08's audio shutdown); they never
change the loop. Before the hooks, ``_close_writers`` gives every file writer owner one
quit deadline (F16's ``settings.submit_final``, F12's ``persist.close``, then F16's
``settings.wait_final``; F11's ``saves.submit_final`` after F16's submit and
``saves.wait_final`` after F16's wait; F20's ``flow.submit_final`` after F12's close and
``flow.wait_final`` after F11's wait), then stops ``App.writer``. The story is pumped
only while ``screens.story_may_run()`` (F10's story hold: never under a menu).

Metric definitions (ADR-0005): the frame interval is the time between consecutive returns
of ``FrameLimiter.wait()``; the frame work runs from that return to the return of the
frame's ``flip()`` (or to the end of the frame's work when nothing was presented).
``--bench SECONDS`` records both and logs the five bench lines (§7.5.3); it starts on the
first frame after the story has loaded (``loading`` False, F02 TR-F02-12).
"""

import gc
import sys
import time as _time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

import pygame

from engine import __version__
from engine.app import input as app_input
from engine.app.dispatch import CommandRouter, StoryDriver
from engine.core.config_schema import Config
from engine.core.constants import CANVAS_SIZE, RESIZE_SETTLE_S
from engine.core.errors import UserFacingError
from engine.core.geometry import Viewport
from engine.core.logsetup import LogSetup, get_logger, lifecycle
from engine.core.paths import GamePaths
from engine.core.redact import echo, redact
from engine.core.timing import BenchRecorder, FrameLimiter, RecentFrames
from engine.persist.writer import Writer
from engine.render import overlay
from engine.render.assets import AssetManager
from engine.render.canvas import Canvas, RenderQuality
from engine.render.window import WindowPort
from engine.ui.builtin.error import ErrorScreen
from engine.ui.screen import ScreenStack

if TYPE_CHECKING:
    from engine.app.editor_link import EditorLink
    from engine.audio.service import AudioService
    from engine.runtime.guard import AuthorCodeGuard
    from engine.core.startvalues import StartOptions
    from engine.script.program import Program
    from engine.ui.builtin.rollback import RollbackKeys
    from engine.ui.builtin.skip_auto import SkipAuto
    from engine.ui.builtin.stage_screen import StageScreen
    from engine.ui.builtin.textbox_screen import TextboxScreen
    from engine.persist.sync import PersistentSync
    from engine.app.settings import SettingsService
    from engine.app.flowchart import FlowService
    from engine.app.saves import SaveService
    from engine.minigames.registry import Registry
    from engine.ui.shell import GameShell

QuitGuard = Callable[[], bool]

MINIMIZED_WAIT_MS = 100                 # ≤ 10 wake-ups per second while minimized
MSG_EMPTY_FRAMEBUFFER = "Framebuffer is empty; frame skipped"
MSG_ENGINE_ERROR = "The game stopped because of an error inside the engine"
MSG_ERROR_SCREEN_FAILED = "The error screen could not be shown"
LOG_NOT_AVAILABLE_YET = "not available yet"
# F14 (07 I-11, AC-F14-35): while ``run`` runs, a full (generation 2) collection waits for
# at least this many generation 1 collections instead of CPython's 10. A full rollback
# timeline (AC-F14-35's bench) holds ~110,000 containers, so each full collection takes
# tens of ms (one long frame); at 10 one came every ~25 checkpoints, at 100 they are ten
# times rarer, so one wheel spin sees at most one. ``run`` restores the collector's
# thresholds when it ends. Generations 0 and 1 are unchanged, so cyclic garbage is still
# collected young.
GC_FULL_AFTER = 100

# Window events that end a minimized period (§7.8 step 2).
_UNMINIMIZE_EVENTS = (pygame.WINDOWRESTORED, pygame.WINDOWMAXIMIZED, pygame.WINDOWSHOWN,
                      pygame.WINDOWEXPOSED)

_log = get_logger("loop")
_app_log = get_logger("app")


def engine_error_message(error: BaseException) -> str:
    """The screen text for an exception that is not a ``UserFacingError`` (§7.12 step 1).
    ``echo`` redacts before it cuts to 120 characters (SEC-F01-11)."""
    return (f"Something went wrong inside the engine ({type(error).__name__}: "
            f"{echo(str(error))}). The log file has the details.")


def _guard_name(guard: QuitGuard) -> str:
    return getattr(guard, "__name__", None) or type(guard).__name__


class App:
    """One game session's loop (§7.5)."""

    def __init__(self, *, config: Config, paths: GamePaths | None, window: WindowPort,
                 assets: AssetManager, log: LogSetup | None, dev: bool,
                 bench_seconds: float | None,
                 clock: Callable[[], float] = _time.perf_counter,
                 limiter: FrameLimiter | None = None,
                 start: "StartOptions | None" = None,
                 editor_link: "EditorLink | None" = None,
                 seed: int | None = None, no_persistent: bool = False) -> None:
        self.config = config
        self.paths = paths
        self.window = window
        self.assets = assets
        self.log = log
        self.dev = dev                          # == not release (SEC-F01-20)
        self.bench_seconds = bench_seconds
        # F44: ``run --start``/``--set`` (session configuration, never saved), read by the
        # story load (``LoadOptions``) and, from F03 step 6, the Interpreter's new game.
        self.start = start
        # F03 step 13: ``run --seed N`` (dev runs only); every new game is seeded with N.
        # None: each new game gets a fresh seed (``story.random_seed``).
        self.seed = seed
        # F12: ``run --no-persistent`` (dev runs only): persistent data stays in memory.
        self.no_persistent = no_persistent
        # F12 step 6: the process's one file writer (ADR-0007; ``persist/writer.py``), shared
        # by F12's persistent data, F16's settings, and F11's saves. Its thread starts on the
        # first write. ``persist`` is F12's ``PersistentSync`` (``app/persistence.py``:
        # ``install_persistence``), None until the story's launch read is done.
        self.writer = Writer()
        self.persist: PersistentSync | None = None
        # F16: the player's settings (``app/settings.py``: ``SettingsService``), set by the
        # bootstrap at step 17; None headless and in Apps wired by hand.
        self.settings: SettingsService | None = None
        # F11: the saves (``app/saves.py``: ``SaveService``), set by ``install_saves`` from
        # ``install_story``; None before the story is installed and in Apps wired by hand.
        self.saves: SaveService | None = None
        # F20: the flowchart's node states and jumps (``app/flowchart.py``: ``FlowService``),
        # set by ``install_flowchart`` from ``install_story``; None headless, without a graph,
        # and before install. ``flow_listing`` is the launch listing ``StoryLoadScreen`` ran
        # after F12's read (07 A6), handed to ``install_flowchart`` once.
        self.flow: FlowService | None = None
        self.flow_listing: object | None = None
        # F20 s8: the Flowchart page's records and layout cache and its prewarm
        # (``app/flowchart_ui.py``: ``FlowPages``), set by ``install_flowchart_page``.
        self.flow_pages: object | None = None
        # F44: set with ``--report-to-editor``; reports "started" and fatal errors.
        self.editor_link = editor_link
        self.time = assets.time
        self.canvas = Canvas(assets)
        self.screens = ScreenStack()
        self.router = CommandRouter()
        self.story: StoryDriver | None = None   # F01: None. F03 sets it.
        # F03 step 12: the launch's watchdog (``story.start_watchdog``), asked last by
        # ``run`` when a ``KeyboardInterrupt`` reaches it (I-8). None with no story.
        self.watchdog: AuthorCodeGuard | None = None
        self.program: "Program | None" = None   # F02: the loaded story (StoryLoadScreen)
        self.loading = False                    # F02: True while the story loads
        # F23: the minigames the plugin phase registered (``StoryLoadScreen``, before F02's
        # load); None before it ends and in Apps wired by hand.
        self.minigames: "Registry | None" = None
        # F23 s4: the launch's ``MinigameHost`` (``app/minigames.install_minigames``).
        self.minigame_host: object | None = None
        # F10 C4: the ``GameShell`` (``ui/shell.py``), set once per launch by
        # ``app/menus.py: install_ui`` (from ``install_story``); None before the story is
        # installed and with no story (W01).
        self.shell: GameShell | None = None
        # F04: the launch's ``StageScreen`` (``story.install_stage``); F05: its one
        # ``TextboxScreen`` (``text_check.install_textbox``, I-16), the ``Say`` handler and
        # the host of F10's in-game overlays (C5). None until the story is installed.
        self.stage_screen: StageScreen | None = None
        self.textbox: TextboxScreen | None = None
        # F08 (§7.10, I-8): the ``AudioService``, built once by the bootstrap (before any
        # story: F10's title music). None headless and in Apps wired by hand. Its slots: raw
        # events first (``handle_raw``), ``update`` after dispatch every frame (error mode
        # and minimized wakes too), ``stop_story_audio`` on the error screen.
        self.audio: AudioService | None = None
        # F15 (07 I-8): the launch's ``SkipAuto`` (``app/skip_auto.install_skip_auto``, from
        # ``install_story``); F16 replaces its ``settings``. None headless and before install.
        self.skip_auto: SkipAuto | None = None
        # F14 (04 §5.3): the launch's ``RollbackKeys`` (``app/rollback.install_rollback``,
        # from ``install_story``). None headless and before install.
        self.rollback_keys: "RollbackKeys | None" = None
        # F14 (07 I-11): called once per frame after the story pump to free a few of the
        # states the rollback timeline dropped (``install_rollback``). None headless.
        self.rollback_release: Callable[[], object] | None = None
        # F05 04 §3.2 / F10 I-14: game controllers opened as they are plugged in.
        self.controllers = app_input.Controllers()
        self.recent = RecentFrames()
        self.viewport: Viewport | None = None
        self.exit_code = 0
        self.running = False
        self.minimized = False
        self.error_mode = False
        self.overlay_on = False
        # F22 (contract change 5, 07 I-10): engine callables returning extra F3 overlay lines
        # (``app/points.py``: the meters). Called only in dev runs, while the overlay is on,
        # and never in error mode.
        self.overlay_lines: list[Callable[[], Sequence[str]]] = []
        # F11 C9: whether the window has input focus (notice times pause while it hasn't).
        self.focused = True
        self.bench: BenchRecorder | None = None
        self._quit_guards: list[QuitGuard] = []
        self._shutdown: list[Callable[[], object]] = []
        # F23 (07 I-11): run first in ``show_fatal_error`` (the minigame host abandons an
        # open session there, its music holder included).
        self._fatal_hooks: list[Callable[[], object]] = []
        self._fatal_message: str | None = None
        self._clock = clock
        self._limiter = limiter if limiter is not None else FrameLimiter(
            config.engine.fps, clock=clock)
        self._letterbox = config.window.letterbox_color
        self._integer_scale = config.window.integer_scale
        self._bound_size: tuple[int, int] | None = None
        self._ever_bound = False
        self._settle_until = 0.0
        self._empty_logged = False
        self._ended_by_report = False

    # --- public API ---------------------------------------------------------------------------

    def run(self) -> int:
        """Run frames until a quit; return the exit code. The window is destroyed as soon
        as the loop ends."""
        # A startup error reported to the editor ended the session before the first frame.
        self.running = not self._ended_by_report
        self.assets.in_frame_loop = True
        self.controllers.start()           # pads already plugged in arrive as "added" events
        last_start: float | None = None
        skip_interval = True
        gc_thresholds = gc.get_threshold()                  # F14 (AC-F14-35): GC_FULL_AFTER
        gc.set_threshold(gc_thresholds[0], gc_thresholds[1],
                         max(gc_thresholds[2], GC_FULL_AFTER))
        try:
            while self.running:
                if self.minimized:                                       # PR-F01-50
                    event = pygame.event.wait(MINIMIZED_WAIT_MS)
                    if event.type != pygame.NOEVENT:
                        self.handle_raw(event)
                    self._update_persist()                   # F12 I-1: minimized wakes too
                    self._update_settings()                  # F16 I-14: minimized wakes too
                    self._update_saves()                     # F11 I-3: minimized wakes too
                    self._update_flow()                      # F20 A6: minimized wakes too
                    self._update_audio()                     # F08 I-4: each minimized wake
                    self._update_editor()                    # F39: minimized wakes too
                    if not self.minimized:
                        self._limiter.reset()
                        last_start = self._clock()
                        skip_interval = True
                    continue
                start = self._limiter.wait()                             # frame start
                # The bench measures from the first frame after the story load (TR-F02-12).
                if self.bench is None and self.bench_seconds and not self.loading:
                    self.bench = BenchRecorder(fps=self.config.engine.fps,
                                               seconds=self.bench_seconds, start=start)
                interval = None if (last_start is None or skip_interval) else start - last_start
                self.time.advance(None if last_start is None else start - last_start)
                last_start = start
                skip_interval = False
                flip_done = None
                try:
                    for event in pygame.event.get():
                        self.handle_raw(event)
                    if self.minimized:
                        # Minimized during this frame: draw nothing from now on (PR-F01-50).
                        self._update_persist()
                        self._update_settings()
                        self._update_saves()
                        self._update_flow()
                        self._update_audio()
                        self._update_editor()
                        continue
                    # F10 C3, the story hold: no pump while a menu (a screen that isn't
                    # in_game) is top, so no command is released and no checkpoint taken.
                    if (self.story is not None and not self.error_mode
                            and self.screens.story_may_run()):
                        for command in self.story.pump():
                            self.router.dispatch(command)
                    self._update_persist()                   # F12: after dispatch
                    self._update_settings()                  # F16: every mode
                    self._update_saves()                     # F11 C9: before audio
                    self._update_flow()                      # F20 (07 A6): after F11
                    self._update_audio()                     # F08: every frame, error mode too
                    self._update_editor()                    # F39: every frame, error mode too
                    if self.rollback_release is not None:    # F14 (07 I-11)
                        self.rollback_release()
                    self.screens.update(self.time.dt)
                    # F11 C9: the notice layer after the screens (never in error mode).
                    if self.shell is not None and not self.error_mode:
                        self.shell.update_layer(self.time.dt, focused=self.focused)
                    flip_done = self.present()
                except KeyboardInterrupt:
                    if not self._watchdog_fired():
                        raise                   # a real Ctrl+C: the interrupt path, exit 0
                except Exception as exc:
                    if self.error_mode:
                        self.fatal_fallback(exc)
                        break
                    try:
                        self.show_fatal_error(exc)
                    except Exception as screen_exc:          # the error screen itself fails
                        self.fatal_fallback(screen_exc)
                        break
                work = (flip_done if flip_done is not None else self._clock()) - start
                self.recent.record(interval or 0.0, work)
                if self.bench is not None:
                    if self.bench.done(start):
                        self._log_bench(self.bench)
                        self.request_quit(force=True)
                    else:
                        self.bench.record(start, interval, work)
        finally:
            gc.set_threshold(*gc_thresholds)
            self.running = False
            self.assets.in_frame_loop = False
            self.window.destroy()
            self._close_writers()           # F12: before the audio shutdown (a hook)
            self._run_shutdown()
        return self.exit_code

    def add_shutdown(self, fn: Callable[[], object]) -> None:
        """Run ``fn()`` once when ``run`` ends (after the window is gone), in reverse order
        of registration. A hook that raises is logged and the rest still run."""
        self._shutdown.append(fn)

    def add_fatal_hook(self, fn: Callable[[], object]) -> None:
        """F23 (``07`` I-11): ``fn()`` runs first in ``show_fatal_error``, each on its own (a
        hook that raises is logged at DEBUG and the error screen still shows)."""
        self._fatal_hooks.append(fn)

    def _close_writers(self) -> None:
        """Quit (``docs/architecture.md`` "Quit", ADR-0007): one writer deadline,
        ``CLOSE_WAIT_S`` from now, shared by every owner. F12's ``persist.close`` writes
        what is unwritten (past the deadline the final write is skipped with W52); then
        the writer stops (abandoned past the deadline; it can leave only a temp file)."""
        writer = self.writer
        until = writer.quit_deadline()
        settings = self.settings
        if settings is not None:                     # F16: submit first, never waits
            try:
                settings.submit_final()
            except Exception:
                _app_log.warning("A shutdown step failed: %s", "settings.submit_final",
                                 exc_info=True)
        saves = self.saves
        if saves is not None:                        # F11 (04 §7.8 step 5): submit encoded jobs
            try:
                saves.submit_final()
            except Exception:
                _app_log.warning("A shutdown step failed: %s", "saves.submit_final",
                                 exc_info=True)
        persist = self.persist
        if persist is not None:
            try:
                persist.close(until=until)
            except Exception:
                _app_log.warning("A shutdown step failed: %s", "persist.close", exc_info=True)
        flow = self.flow
        if flow is not None:                         # F20 (07 A6): after F11's and F12's
            try:
                flow.submit_final(until)
            except Exception:
                _app_log.warning("A shutdown step failed: %s", "flow.submit_final",
                                 exc_info=True)
        if settings is not None:                     # F16: then wait, same deadline
            try:
                settings.wait_final(until)
            except Exception:
                _app_log.warning("A shutdown step failed: %s", "settings.wait_final",
                                 exc_info=True)
        if saves is not None:                        # F11: wait, then W83 for the rest
            try:
                saves.wait_final(until)
            except Exception:
                _app_log.warning("A shutdown step failed: %s", "saves.wait_final",
                                 exc_info=True)
        if flow is not None:                         # F20: then its results
            try:
                flow.wait_final(until)
            except Exception:
                _app_log.warning("A shutdown step failed: %s", "flow.wait_final",
                                 exc_info=True)
        try:
            writer.stop(until)
        except Exception:
            _app_log.warning("A shutdown step failed: %s", "writer.stop", exc_info=True)

    def _run_shutdown(self) -> None:
        hooks, self._shutdown = self._shutdown, []
        for fn in reversed(hooks):
            try:
                fn()
            except Exception:
                _app_log.warning("A shutdown step failed: %s", _guard_name(fn), exc_info=True)

    def request_quit(self, *, force: bool = False) -> None:
        """§7.13: in error mode exit 1 (guards bypassed); otherwise ask each quit guard
        (unless ``force``) and exit 0 if none vetoes (PR-F01-32, 34)."""
        if self.error_mode:
            self._exit(1)
            return
        if not force:
            for guard in list(self._quit_guards):
                if not guard():
                    _app_log.debug("Quit vetoed by %s", _guard_name(guard))
                    return
        self._exit(0)

    def add_quit_guard(self, guard: QuitGuard) -> None:
        """F10/F11 seam: ``guard()`` returning False vetoes a player's quit."""
        self._quit_guards.append(guard)

    def remove_quit_guard(self, guard: QuitGuard) -> None:
        if guard in self._quit_guards:
            self._quit_guards.remove(guard)

    @property
    def quit_guards(self) -> tuple[QuitGuard, ...]:
        return tuple(self._quit_guards)

    def set_title(self, title: str) -> None:
        """The window title, applied before the next frame (PR-F01-15)."""
        self.window.title = title

    def set_fps_cap(self, fps: int) -> None:
        """F16 seam: change the frame-rate cap from the next frame."""
        self._limiter.set_fps(fps)

    # --- error mode (§7.12) -------------------------------------------------------------------

    def show_fatal_error(self, error: BaseException, *, already_logged: bool = False) -> None:
        """Replace every screen with the ErrorScreen; closing it exits with code 1.
        With ``--report-to-editor`` (F44), the error is reported first, and before the
        story has started the run ends with exit code 1 and no ErrorScreen.

        A ``UserFacingError`` shows its ``format()`` and is logged at ERROR without a
        traceback; anything else shows the short engine-error text and logs the full
        traceback. ``already_logged``: startup errors (config, game folder) were logged
        one record per error by the bootstrap.

        F12 (``04`` §7.7): persistent data is written first (``flush_now``, at most
        ``CLOSE_WAIT_S``), and a failure there never keeps the error screen away. F23
        (``07`` I-11): the fatal hooks (``add_fatal_hook``) run before anything else."""
        for hook in list(self._fatal_hooks):
            try:
                hook()
            except Exception:
                _app_log.debug("A step before the error screen failed: %s", _guard_name(hook),
                               exc_info=True)
        if self.persist is not None:
            try:
                self.persist.flush_now()
            except Exception:
                _app_log.debug("Persistent data couldn't be written before the error screen",
                               exc_info=True)
        if isinstance(error, UserFacingError):
            message = error.format()
            if not already_logged:
                _app_log.error("%s", message)
        else:
            message = engine_error_message(error)
            if not already_logged:
                _app_log.error(MSG_ENGINE_ERROR,
                               exc_info=(type(error), error, error.__traceback__))
        self._fatal_message = message
        self.error_mode = True
        self.story = None
        if self.shell is not None:
            self.shell.clear_notices()          # F11 C9 / I-10: no notice on the error screen
        if self.audio is not None:
            self.audio.stop_story_audio(0.5)    # F08 I-4 (PR-F08-30)
        if self.editor_link is not None and self.editor_link.fatal(error):
            # F44 I-7: before the story started, the editor shows the report instead of the
            # error screen. In error mode a forced quit exits with code 1, and run()'s
            # ``finally`` still runs.
            self.request_quit(force=True)
            self._ended_by_report = True
            return
        # F30 (C6, 04 §6.1 step 2): a story may have renamed the window; the real error
        # page always comes with the game's own title.
        self.set_title(self.config.game.title)
        log = self.log
        session = log.session if log is not None else None
        screen = ErrorScreen(
            message=message, game_title=self.config.game.title,
            game_version=self.config.game.version,
            log_display_path=session.display_path if session is not None
            else LOG_NOT_AVAILABLE_YET,
            tail=(lambda: list(log.tail)) if log is not None else (lambda: []),
            on_quit=lambda: self._exit(1), engine_version=__version__)
        self.screens.replace_all([screen], safe_exit=True)

    def fatal_fallback(self, error: BaseException) -> None:
        """The error screen itself failed (§7.12 step 7): log it, print the redacted
        message to stderr, show the system dialog, and exit with code 1."""
        _app_log.error(MSG_ERROR_SCREEN_FAILED, exc_info=(type(error), error,
                                                         error.__traceback__))
        message = self._fatal_message or engine_error_message(error)
        if sys.stderr is not None:
            try:
                print(redact(message), file=sys.stderr)
            except Exception:
                pass
        from engine.app.bootstrap import show_native_error
        show_native_error(f"{self.config.game.title} ran into a problem", message)
        self._exit(1)

    def _watchdog_fired(self) -> bool:
        """I-8 (F03 ``04`` §7.7): a ``KeyboardInterrupt`` reached the loop. If the watchdog
        sent it (author code ran ``AUTHOR_CODE_LIMIT_S`` and the interrupt landed past every
        other catch layer), show E85m on the error screen (exit code 1) and keep running;
        otherwise it is a real Ctrl+C (False)."""
        watchdog = self.watchdog
        if watchdog is None or not watchdog.consume_fired():
            return False
        if not self.error_mode:
            from engine.app.story import watchdog_timeout_error
            self.show_fatal_error(watchdog_timeout_error(self), already_logged=True)
        return True

    def _exit(self, code: int) -> None:
        self.exit_code = code
        self.running = False

    @property
    def clock(self) -> Callable[[], float]:
        """The App's monotonic clock (F08 I-4: the audio service's clock)."""
        return self._clock

    def _update_persist(self) -> None:
        """F12's update slot (``04`` §7.5, ``07`` I-1): after dispatch and before audio,
        also on minimized wakes, never in error mode (the error screen flushed it)."""
        if self.persist is not None and not self.error_mode:
            self.persist.update(self._clock())

    def _update_settings(self) -> None:
        """F16's update slot (``07`` I-14): after persistent data, before audio, in every
        mode (error mode and minimized wakes too), on the App clock."""
        if self.settings is not None:
            self.settings.update(self._clock())

    def _update_saves(self) -> None:
        """F11's update slot (``07`` I-3, C9): after settings, before audio, in every mode
        but error mode (minimized wakes and fades included); it slices its own work."""
        if self.saves is not None and not self.error_mode:
            self.saves.update(self.time.dt)

    def _update_flow(self) -> None:
        """F20's update slot (``07`` A6): right after F11's, in every mode but error mode
        (minimized wakes included), on the App clock; it slices its own work."""
        if self.flow is not None and not self.error_mode:
            self.flow.update(self._clock())
            pages = self.flow_pages
            if pages is not None:
                pages.update(self._clock())          # F20 s8 (07 A7): the layout prewarm

    def _update_audio(self) -> None:
        """F08's update slot (§7.10, I-4): after dispatch in every frame, in error mode,
        on the frame that minimizes the window, and on each minimized wake."""
        if self.audio is not None:
            self.audio.update(self._clock())

    def _update_editor(self) -> None:
        """F39's slot (``SPEC.md`` §5.1 step 3, §5.2): with ``--report-to-editor``, Studio's
        messages read since the last frame (one queue poll), in every mode: error mode and
        minimized wakes too, so a ``reload`` is always answered."""
        if self.editor_link is not None:
            self.editor_link.update(self)

    # --- events (§7.8)------------------------------------------------------------------------

    def handle_raw(self, event: pygame.event.Event) -> None:
        # F08: the audio service sees every raw event first and consumes only its own
        # (music end, audio device); focus and minimize events pass through.
        if self.audio is not None and self.audio.handle_event(event):
            return
        kind = event.type
        if kind == pygame.QUIT:
            self.request_quit()
            return
        if kind == pygame.WINDOWCLOSE:
            return                  # one window: SDL also sends QUIT
        if kind == pygame.WINDOWMINIMIZED:
            self.minimized = True
        elif kind in _UNMINIMIZE_EVENTS:
            self.minimized = False
        if kind == pygame.WINDOWFOCUSLOST:
            self.focused = False
        elif kind == pygame.WINDOWFOCUSGAINED:
            self.focused = True
        if kind in (pygame.WINDOWMAXIMIZED, pygame.WINDOWRESTORED, pygame.WINDOWSIZECHANGED):
            self.window.note_window_event(kind)
        if kind in (pygame.CONTROLLERDEVICEADDED, pygame.CONTROLLERDEVICEREMOVED):
            self.controllers.handle(event)      # the screens still see it (focus is kept)
        if kind == pygame.KEYDOWN:
            if app_input.is_fullscreen_hotkey(event):
                self.window.toggle_fullscreen()
                return
            if self.dev and app_input.is_overlay_hotkey(event):
                self.overlay_on = not self.overlay_on
                return
        self.screens.handle_event(app_input.translate(event, self.viewport, self.window))

    # --- present (§7.5.2) ---------------------------------------------------------------------

    def present(self) -> float | None:
        """Draw and flip one frame; return the time ``flip()`` returned, or None when the
        framebuffer is empty and the frame was skipped."""
        framebuffer = self.window.framebuffer()
        if framebuffer is None or framebuffer.get_width() == 0 or framebuffer.get_height() == 0:
            # Item 25: no viewport, no draw, no flip; re-bind when it has a size again.
            self._bound_size = None
            if not self._empty_logged:
                self._empty_logged = True
                _log.debug(MSG_EMPTY_FRAMEBUFFER)
            return None
        self._empty_logged = False
        size = framebuffer.get_size()
        # pygame-ce returns the same Surface object after a resize (S0 note 1), so only the
        # size can tell that the framebuffer changed.
        if size != self._bound_size:
            self.viewport = Viewport.compute(CANVAS_SIZE, size,
                                             integer_scale=self._integer_scale)
            if self._ever_bound:
                quality = RenderQuality.FAST
                self._settle_until = self._clock() + RESIZE_SETTLE_S
            else:
                quality = RenderQuality.FINAL
            self._ever_bound = True
            self._bound_size = size
        elif self.canvas.quality is RenderQuality.FAST and self._clock() >= self._settle_until:
            quality = RenderQuality.FINAL
        else:
            quality = self.canvas.quality
        # A new subsurface every frame: one taken before a resize must never be drawn into
        # (S0 note 2: that crashes the process).
        self.canvas.bind(framebuffer, self.viewport, quality)
        for rect in self.viewport.bar_rects():
            framebuffer.fill(self._letterbox, rect)
        if not any(getattr(screen, "opaque", False) for screen in self.screens):
            self.canvas.fill((0, 0, 0))
        self.screens.draw(self.canvas)
        # F11 C9: notices over every screen, under the dev overlay; none in error mode.
        if self.shell is not None and not self.error_mode:
            self.shell.draw_layer(self.canvas)
        if self.dev and self.overlay_on:
            lines = () if self.error_mode else [
                line for provider in self.overlay_lines for line in provider()]
            overlay.draw(self.canvas, self.recent, lines)
        self.window.flip()
        return self._clock()

    # --- bench (§7.5.3) -----------------------------------------------------------------------

    def _log_bench(self, bench: BenchRecorder) -> None:
        """The five bench lines: lifecycle INFO records in area ``loop``."""
        framebuffer = self.window.framebuffer()
        fb_w, fb_h = framebuffer.get_size() if framebuffer is not None else (0, 0)
        width, height = self.window.size
        mode = "fullscreen" if self.window.fullscreen else "windowed"
        description = f"{width}x{height} {mode} | framebuffer {fb_w}x{fb_h} px"
        for line in bench.log_lines(bench.result(), description):
            lifecycle(_log, "%s", line)

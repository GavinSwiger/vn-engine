"""``StoryLoadScreen``: the story loads inside the frame loop (F02 ``04-technical.md`` §7.9).

Why this module exists: a large story takes seconds to read and check, and a window that
stops pumping events for that long is "Not Responding" on Windows (PR-F02-39). So bootstrap
step 17 puts this screen on the stack, and each frame's ``update`` runs one slice of about
``SCRIPT_LOAD_SLICE_S`` of the ``StoryLoader``; between slices the App handles events, F11,
and quitting as usual. When the load is done, the result is logged once
(``report_load_result``) and the screen hands over:

- first, F23's **plugin phase** (``04-technical.md`` §7.10, I-12): ``PluginLoadJob`` loads the
  minigame plugins of the real ``game/minigames/`` in the same slices (one file read or one
  module run per step, under the launch's watchdog), in dev and release runs alike. Its
  inputs are ``GamePaths`` and constants only (SEC-F23-04 (a)). Its errors (E273, E274,
  E278; at most ``MAX_ERRORS``) stop the launch in one ``ScriptErrorGroup`` of their own,
  logged in area ``plugin`` (a traceback the loader already logged isn't logged again);
  otherwise ``app.minigames`` is the ``Registry`` and F02's ``StoryLoader`` is built with
  ``LoadOptions.minigames`` set to its signatures. Read-only tools never get here: they pass
  ``LoadOptions.minigames=None`` and run no plugin code (SEC-F23-04 (b));

- errors: ``app.show_fatal_error(ScriptErrorGroup)``, the F01 error screen;
- otherwise: ``app.program`` is set (None with no story, W01). A story then reads its
  persistent data (F12 ``04`` §7.4, ``app/persistence.py``): ``open_for_launch`` right
  after the load, then the ``ReadJob`` in the same slices, so the read runs after the load
  and before the first ``define``; F20's ``FlowListJob`` (the saves root's node files, when
  F12's data is WRITABLE and the story has a graph) follows in the same slices (``07`` A6).
  Then it goes through
  F03's **launch phase** (``04-technical.md`` §7.6): a ``LaunchJob`` sets every ``define``,
  sliced over frames with the load's deadline (the frame that finishes the load goes on
  with what is left of its slice; a later frame does at least one unit). Launch errors are
  logged (area ``runtime``) and shown as one ``ScriptErrorGroup``; ``module()`` asks the
  game folder through ``game_has`` (listings only, no file opened). F08's audio file
  check (W21, W22, W25, W31) gets ``audio_files`` and is logged in the ``script`` area,
  F04's image warnings in ``stage``, F12's W56 in ``persist``. Otherwise
  ``install_story`` wires an ``Interpreter`` into the App; it starts where ``app.start``
  says (F44 C1: ``--start``/``--set``), and F31's ``install_metafiles`` gives it the disk
  files port when the story has ``file`` lines. The launch's ``Watchdog`` (F03 step 12,
  ``story.start_watchdog``) starts before the first define and guards the launch job and
  the interpreter. Before ``install_story``, F12's ``install_persistence`` sets
  ``App.persist``, whose encoder is then warmed in the following slices (``warm``) before
  the hand-over. The ``Interpreter`` and ``install_story`` with the rest are two stages
  (``_install_slice``): each walks the whole story (25–35 ms at 1,000,000 words), so the
  second waits for a frame of its own when the slice has less left than the first took,
  and the first when it has less left than ``INSTALL_S_PER_STATEMENT`` per statement
  (AC-F02-63); a small story does both in the frame that finished the launch;
- in dev runs, F05's ``TextLaunchCheck`` (W40, W40b, W41, then F30's W189 and W190 scan;
  ``app/text_check.py``) then runs in the same slices, still with ``app.loading`` True, and
  logs its warnings when done;
- then the stack is replaced by ``on_ready(app)``, which bootstrap passes as
  ``build_initial_screens``: the one "what shows at launch" seam stays in bootstrap (I-2).

``app.loading`` is True from ``on_enter`` until the load and the launch phase are done or
the screen leaves the stack (``on_exit``, I-3: an engine error during a slice replaces it
with the error screen, and a ``--bench`` run must still start its recorder there). The
bench starts on the first frame with ``app.loading`` False (TR-F02-12).

Frame-loop notes (I-4): (a) the App doesn't update screens while minimized, so loading
pauses then; (b) one ``compile()`` of a hostile piece can't be interrupted, so a frame can
take about 1 s there (PR-F02-39 is for realistic stories); (c) ``draw`` uses only the canvas
it is given and keeps nothing of it (S0 note 2: a subsurface kept across a resize crashes
the process); loading reads no image, so S0 notes 3 and 4 don't apply; (d) the first
``update`` does no loader work, so the first frame presents black at once.

Loading indicator (F10 C10, UI-F10-08): once the screen has shown for
``LOADING_SHOW_S`` (game time since ``on_enter``), it draws the ``loading`` word and three
dots at the bottom right (1264, 708) in ``[theme.title.loading] text_color`` with the
bundled Noto Sans Regular (theme fonts are checked only at ``install_ui``). One dot at a time
is at full opacity, 300 ms each, left to right; under ``[effects] reduce`` all three are full
and still. A quick load never shows it.

This is the only ``engine.app`` module that imports ``engine.script`` (AC-F02-66); bootstrap
imports this module, never ``engine.script``, and this module never imports bootstrap.
"""

import dataclasses
import time
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType, SimpleNamespace
from typing import TYPE_CHECKING

from engine.app.flowchart import open_flow_listing
from engine.app.metafiles import install_metafiles
from engine.app.persistence import PersistentLaunch, install_persistence, open_for_launch
from engine.app.story import install_story, start_watchdog
from engine.app.text_check import TextLaunchCheck, text_launch_check
from engine.core.logsetup import get_logger
from engine.core.minigame_types import MinigameSig
from engine.core.paths import GamePaths
from engine.minigames.loader import PluginLoadJob, PluginLoadResult
from engine.persist.nodestates import FlowListJob
from engine.render.canvas import Canvas
from engine.runtime.audio_check import AUDIO_CHECK_CODES
# F45: lifted to runtime (the check child builds the same inputs); imported here for use
# and for the old import path.
from engine.runtime.gamesources import audio_files, game_has, image_source  # noqa: F401
from engine.runtime.interpreter import Interpreter
from engine.runtime.launch import LaunchJob, LaunchResult
from engine.script import LoadOptions, ScriptErrorGroup, StoryLoader, report_load_result
from engine.script.diagnostics import ScriptError
from engine.script.flowgraph import FlowOptions
from engine.script.limits import SCRIPT_LOAD_SLICE_S
from engine.script.messages import format_message
from engine.script.program import Program
from engine.ui.loading_indicator import LOADING_DOT_S, draw_loading_indicator
from engine.ui.screen import Screen
from engine.ui.shell import reduce_motion_of
from engine.ui.theme import Words

if TYPE_CHECKING:
    from engine.app.app import App

BACKGROUND = (0, 0, 0)                   # #000000 while loading (04 §5.3)
# The loading indicator (F10 03 "Title screen", UI-F10-08).
# Its drawing is ``ui/loading_indicator.py``'s, shared with F11's large loads (F11 I-5).
LOADING_SHOW_S = 1.0                     # shown only once loading passes 1,000 ms
# An install stage's first estimate (_install_slice): one whole-story walk measured about
# 0.25–0.35 µs per statement (101,082 statements at 1,000,000 words), with room to spare.
INSTALL_S_PER_STATEMENT = 0.4e-6

OnReady = Callable[["App"], Sequence[Screen]]
Signatures = Mapping[str, MinigameSig]


class PluginPhase:
    """F23's plugin phase (§7.10): the ``PluginLoadJob`` over ``paths`` (built at its first
    step, with the launch's watchdog as its guard), then ``make_loader(signatures)``, F02's
    ``StoryLoader`` with ``LoadOptions.minigames`` set."""

    def __init__(self, paths: GamePaths,
                 make_loader: Callable[[Signatures], StoryLoader]) -> None:
        self.paths = paths
        self.make_loader = make_loader
        self.job: PluginLoadJob | None = None


class StoryLoadScreen(Screen):
    """Runs ``loader`` one slice per frame, then the launch phase, then hands over (§7.9,
    F03 §7.6)."""

    opaque = True
    holds_notices = True                       # F11 C7: notices wait for the title or game

    def __init__(self, app: "App", loader: StoryLoader | None, *, on_ready: OnReady,
                 clock: Callable[[], float] = time.perf_counter,
                 plugins: PluginPhase | None = None) -> None:
        self.app = app
        self.loader = loader                       # None until the plugin phase builds it
        self.plugins = plugins                     # F23: None once done (or not run)
        self.minigames: Signatures | None = None   # F23: the plugin phase's signatures
        self.on_ready = on_ready
        self.finished = False
        self.job: LaunchJob | None = None          # F03: set once the load is clean
        self.launched: LaunchResult | None = None  # F03: done, the story's installs to do
        self.interp: Interpreter | None = None     # F03: made, not yet installed
        self._stage_s = 0.0                        # an install stage's cost (estimated, then
                                                   # the last one measured)
        self.text_check: TextLaunchCheck | None = None  # F05: dev, after the launch phase
        self.persistent: PersistentLaunch | None = None  # F12: the launch read (§7.4)
        self.warming = False                       # F12: App.persist's encoder warm-up
        self.flow_list: FlowListJob | None = None  # F20: the launch listing (07 A6)
        self.flow_checked = False
        self._program: Program | None = None
        self._clock = clock
        self._first_update = True
        self.elapsed = 0.0                         # game time since on_enter (C10)
        config = app.config
        self.loading_word = Words(config.words).get("loading")
        self.loading_color = config.theme.title.loading.text_color
        self.reduce_motion = reduce_motion_of(config)

    def on_enter(self) -> None:
        self.app.loading = True

    def on_exit(self) -> None:
        self.app.loading = False                                        # I-3

    def update(self, dt: float, *, is_top: bool) -> None:
        self.elapsed += dt
        if self.finished:
            return
        if self._first_update:                                          # I-4 (d)
            self._first_update = False
            return
        started = self._clock()
        if self.launched is not None or self.warming or self.text_check is not None:
            self._after_launch(started)
            return
        # The frame that finished the load goes on only with what is left of its slice; a
        # later frame always does at least one unit.
        deadline = started + SCRIPT_LOAD_SLICE_S
        budget = SCRIPT_LOAD_SLICE_S
        if self.plugins is not None:                # F23: before F02's load (I-12)
            if not self._plugin_slice(deadline):
                return
            # F02's load goes on with what is left of the slice (step(0.0) still moves).
            budget = max(0.0, deadline - self._clock())
        if self.job is None:
            fresh = self.persistent is None
            if fresh and not self._load_slice(budget):
                return
            if not self._read_slice(deadline, at_least_one=not fresh):
                return
        job = self.job
        assert job is not None
        while self._clock() < deadline:
            if job.step():
                if self._launched(job.result):     # on with what is left of the slice
                    self._after_launch(started, at_least_one=False)
                return

    def _plugin_slice(self, deadline: float) -> bool:
        """Steps of the plugin phase until ``deadline`` (at least one). When it is done,
        its errors go to the error screen, or F02's loader is built (True)."""
        phase = self.plugins
        assert phase is not None
        app = self.app
        if phase.job is None:
            # F03 step 12's watchdog guards every plugin top level too (§7.10 step 7).
            phase.job = PluginLoadJob(phase.paths, start_watchdog(app), dev=app.dev,
                                      log=get_logger("plugin"))
        job = phase.job
        while not job.step():
            if self._clock() >= deadline:
                return False
        result = job.result
        self.plugins = None
        if not result.ok:
            self.finished = True
            app.loading = False
            app.show_fatal_error(plugin_error_group(result), already_logged=True)
            return False
        app.minigames = result.registry
        self.minigames = result.signatures()
        self.loader = phase.make_loader(self.minigames)
        return True

    def _load_slice(self, budget: float = SCRIPT_LOAD_SLICE_S) -> bool:
        """One load slice. True once the load is clean and the persistent read is open;
        on errors or with no story the screen has already handed over."""
        loader = self.loader
        assert loader is not None
        if not loader.step(budget):
            return False
        app = self.app
        result = loader.result
        report_load_result(result, get_logger("script"))
        if result.errors or result.error_count:
            self.finished = True
            app.loading = False
            app.show_fatal_error(ScriptErrorGroup.from_result(result), already_logged=True)
            return False
        app.program = result.program               # None when there is no story (W01)
        if result.program is None:
            self._hand_over()                      # no Interpreter: F01's placeholder
            return False
        self._program = result.program
        # F12 §7.4 steps 1–4: where the data lives, and the read (stepped in _read_slice).
        paths = app.paths
        self.persistent = open_for_launch(
            result.program, game_root=paths.root if paths is not None else None,
            release=not app.dev, app_id=app.config.game.id,
            off=getattr(app, "no_persistent", False),
            memory_only=getattr(app, "playthrough_preview", None) is not None)
        return True

    def _read_slice(self, deadline: float, *, at_least_one: bool) -> bool:
        """Steps of the persistent read (F12 §7.4 step 5) until ``deadline``; once it is
        done, the launch job exists (True)."""
        persistent = self.persistent
        assert persistent is not None
        if not persistent.run_for(deadline, self._clock, at_least_one=at_least_one):
            return False
        program = self._program
        assert program is not None
        app = self.app
        if not self._list_slice(deadline):        # F20 (07 A6): before the launch phase
            return False
        paths = app.paths
        # F03 step 12: the watchdog guards every define, and later the interpreter.
        # F12 step 3a: the define lock and phase 2b run on the session's store.
        self.job = LaunchJob(program, guard=start_watchdog(app), dev=app.dev,
                             game_has=game_has(paths) if paths is not None else _nothing,
                             images=image_source(paths) if paths is not None else None,
                             game_root=paths.root if paths is not None else None,
                             persistent=persistent.store,
                             audio=(audio_files(paths, app.config.audio.loop_start)
                                    if paths is not None else None))
        return True

    def _list_slice(self, deadline: float) -> bool:
        """F20's launch listing (``04`` §7.5 "Launch", ``07`` A6): one ``FlowListJob`` of
        the saves root in the load's slices, after F12's read and before the launch phase,
        only when F12's data is WRITABLE and the story has a graph (else no file call). True
        once it is done (or not needed); ``install_flowchart`` takes it from
        ``App.flow_listing``."""
        if not self.flow_checked:
            self.flow_checked = True
            persistent = self.persistent
            assert persistent is not None
            self.flow_list = open_flow_listing(self.app, persistent.mode, self._program)
        job = self.flow_list
        if job is None:
            return True
        if not job.step(deadline, self._clock):
            return False
        self.app.flow_listing = job
        self.flow_list = None
        return True

    def _launched(self, result: LaunchResult) -> bool:
        """The launch phase is done: show its errors (False), or log its warnings and
        install persistent data (True; ``_after_launch`` then installs the story, warms,
        checks, and hands over)."""
        app = self.app
        log = get_logger("runtime")
        if result.namespace is None:
            self.finished = True
            report_load_result(_launch_report(result), log)
            app.loading = False
            app.show_fatal_error(ScriptErrorGroup(result.errors, result.error_count),
                                 already_logged=True)
            return False
        stage_log = get_logger("stage")
        persist_log = get_logger("persist")
        script_log = get_logger("script")
        # F12's W56, then F04's W10–W16, then F08's W21, W22, W25, W31, in order.
        for warning in result.warnings:
            log_to = (persist_log if warning.code == "W56" else
                      script_log if warning.code in AUDIO_CHECK_CODES else stage_log)
            log_to.warning("%s", warning.format())
        assert self._program is not None and self.persistent is not None
        # F12 §7.4 step 9: App.persist, before the story's installs (their notices).
        install_persistence(app, self.persistent)
        self.persistent = None                     # the sync owns the store now
        self.launched = result                     # the installs follow (_install_slice)
        self._stage_s = self._program.stats.statements * INSTALL_S_PER_STATEMENT
        return True

    def _install_slice(self, deadline: float, *, at_least_one: bool) -> bool:
        """The story's installs after the launch phase in two stages: the ``Interpreter``,
        then ``install_story`` and the rest. Each walks the whole story once (chapters,
        styles: about 25–35 ms each at 1,000,000 words), so a stage shares a frame with
        other work only when the slice has as much left as the last stage took (before the
        first: ``INSTALL_S_PER_STATEMENT`` per statement); a frame of its own does at least
        one (AC-F02-63). A small story does both at once. True once all are done."""
        result = self.launched
        program = self._program
        assert result is not None and result.namespace is not None and program is not None
        app = self.app
        if self.interp is None:
            began = self._clock()
            if not at_least_one and began + self._stage_s >= deadline:
                return False
            # F44 C1: --start/--set reach the new game (the load checked the label, E26b).
            # F12 step 3a: marks and step 3b on the same store the launch used.
            persist = app.persist
            assert persist is not None
            self.interp = Interpreter(
                program, result.namespace, guard=start_watchdog(app), dev=app.dev,
                start=app.start, show_locked=app.config.choice.show_locked,       # F07
                persistent=persist.store,
                rollback_steps=app.config.rollback.steps,                      # F14 (I-15)
                minigames=self.minigames or MappingProxyType({}))              # F23 I-12
            now = self._clock()
            self._stage_s = now - began
            if now + self._stage_s >= deadline:
                return False
        elif not at_least_one and self._clock() + self._stage_s >= deadline:
            return False
        interp = self.interp
        install_story(app, interp, fixed_seed=app.seed,        # F03 step 13: --seed
                      images=result.images)
        install_metafiles(app, interp)                         # F31 s4: the disk port
        # F05 §7.8: the dev text check runs in the next frames' slices.
        self.text_check = text_launch_check(app, program, result.namespace)
        self.launched = None
        self.interp = None
        self.warming = True
        return True

    def _after_launch(self, started: float, *, at_least_one: bool = True) -> None:
        """The story's installs (``_install_slice``), F12's encoder warm-up
        (``PersistentSync.warm``: a big store would otherwise take thousands of frames
        before its first write), then F05's text check, then the hand-over, in this frame's
        slice. A frame of its own does at least one unit."""
        if self.launched is not None:
            if not self._install_slice(started + SCRIPT_LOAD_SLICE_S,
                                       at_least_one=at_least_one):
                return
            at_least_one = False
        if self.warming:
            persist = self.app.persist
            left = started + SCRIPT_LOAD_SLICE_S - self._clock()
            if persist is not None:
                if not at_least_one and left <= 0:
                    return
                # The sync measures with its own clock.
                if not persist.warm(persist.clock() + max(0.0, left)):
                    return
            self.warming = False
            at_least_one = False
        if self.text_check is not None:
            self._text_slice(started, at_least_one=at_least_one)
            return
        self._hand_over()

    def _text_slice(self, started: float, *, at_least_one: bool = True) -> None:
        """One slice of the text check; hands over when it is done. A frame of its own does
        at least one step; the frame that finished the launch only what fits its slice. A
        step starts only when the slice has as much left as the last step took (a line step
        of a 1,000,000-word story takes up to about 40 ms; AC-F02-63)."""
        check = self.text_check
        assert check is not None
        deadline = started + SCRIPT_LOAD_SLICE_S
        last = 0.0                                 # a step starts only if one more fits
        while at_least_one or self._clock() + last < deadline:
            at_least_one = False
            began = self._clock()
            if check.step():
                break
            last = self._clock() - began
        else:
            return
        check.log()
        self.text_check = None
        self._hand_over()

    def _hand_over(self) -> None:
        self.finished = True
        app = self.app
        app.loading = False
        app.screens.replace_all(self.on_ready(app))
        if app.editor_link is not None:
            app.editor_link.story_started()        # F44 I-8: after build_initial_screens

    def draw(self, canvas: Canvas) -> None:
        canvas.fill(BACKGROUND)                    # the given canvas only, kept nowhere (I-4)
        if self.elapsed >= LOADING_SHOW_S - 1e-9:
            self._draw_indicator(canvas)

    def bright_dot(self) -> int | None:
        """The dot at full opacity now (0–2), or None when all three are (reduced motion)."""
        if self.reduce_motion:
            return None
        shown = max(0.0, self.elapsed - LOADING_SHOW_S)
        return int(shown / LOADING_DOT_S + 1e-9) % 3

    def _draw_indicator(self, canvas: Canvas) -> None:
        """The ``loading`` word and three dots, right-aligned to x 1264 above y 708."""
        draw_loading_indicator(canvas, self.loading_word, self.loading_color,
                               bright=self.bright_dot())


def _nothing(ref: str) -> bool:
    return False


def _launch_report(result: LaunchResult) -> SimpleNamespace:
    """Launch errors in the shape ``report_load_result`` logs (F02 §7.10.1): each error,
    then "…and N more problems" when some were left out."""
    return SimpleNamespace(errors=result.errors, error_count=result.error_count,
                           checks_skipped=False, warnings=(), todos=(), todo_count=0,
                           program=None)


def plugin_error_group(result: PluginLoadResult) -> ScriptErrorGroup:
    """The plugin phase's errors as one ``ScriptErrorGroup`` (§7.10 step 10: never mixed
    with script errors), each logged once in area ``plugin`` (one the loader logged with its
    traceback is not logged again), then E100 when some were left out."""
    log = get_logger("plugin")
    errors = []
    for problem in result.errors:
        error = ScriptError(problem.message, code=problem.code, file=problem.file,
                            line=problem.line)
        if not problem.logged:
            log.error("%s", error.format())
        errors.append(error)
    extra = result.error_count - len(errors)
    if extra > 0:
        log.error("%s", format_message("E100", (f"{extra:,}",)))
    return ScriptErrorGroup(errors, result.error_count)


def story_load_screen(app: "App", paths: GamePaths, *, on_ready: OnReady) -> StoryLoadScreen:
    """The load screen for bootstrap step 17 (I-2): F23's plugin phase over ``paths``, then
    a ``StoryLoader`` over ``paths`` that checks ``minigame`` lines against the registered
    signatures, keeps ``# TODO`` comments in dev runs (PR-F02-43), and checks the
    ``--start`` label and the ``--set`` names (E26b, E26c; F44 C2), then ``on_ready(app)``."""
    start = app.start
    # F04 §5.4: ``at`` may name the built-in and [stage.positions] names (E120);
    # config.stage.positions holds both (F04 I-19).
    positions = frozenset(app.config.stage.positions)
    flowchart = FlowOptions.from_config(app.config.flowchart)     # F20 07 I-1: load phase 6
    fallback = app.config.meta.username_fallback                  # F30 04 §4.1
    styles = frozenset(app.config.style)                          # F32 04 §5.1: E320
    if start is None:
        options = LoadOptions(collect_todos=app.dev, position_names=positions, dev=app.dev,
                              flowchart=flowchart, username_fallback=fallback,
                              style_names=styles)
    else:
        options = LoadOptions(collect_todos=app.dev, start=start.label,
                              start_names=tuple(name for name, _ in start.values),
                              position_names=positions, dev=app.dev, flowchart=flowchart,
                              username_fallback=fallback, style_names=styles)

    def make_loader(minigames: Signatures) -> StoryLoader:
        return StoryLoader(paths, dataclasses.replace(options, minigames=minigames))

    return StoryLoadScreen(app, None, on_ready=on_ready,
                           plugins=PluginPhase(paths, make_loader))

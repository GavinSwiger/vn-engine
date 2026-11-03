"""The interpreter: runs a ``Program`` one statement at a time and emits commands (F03
``04-technical.md`` §4.3, §5.2, §7.1–7.5).

Why this module exists: the story's flow (lines, ``$`` lines, ``if``, ``jump``, ``call``,
``return``) and the one checkpoint routine that snapshots the story at every shown line
live in one place, with no window, clock, entropy, or thread (invariant 7), so the same
code runs in the game and headless.

Extension points (one line each in the owning feature, no edits here):
- ``register_executor(NodeType, run, present=...)`` for a new statement; a node type
  registered with a presenter is a checkpoint type (``CHECKPOINT_TYPES``, I-7); ``check=``
  adds that type's restore position check (F11 C10, F07's pickable keys).
- ``register_event(EventType, handler)`` for a new event (F07 ``Choose``, F09 waits).
- ``take_checkpoint(stmt, cmd, attached=...)``: the one checkpoint routine (I-4, I-5).
- ``_hold`` and ``_release``: the one place commands are held and released (I-3).
- ``reset_steps()``: a wait (F09) starts the E45 step count again, as a line does.
- ``begin_wait(stmt, *, seconds, for_stage, then=None, make=StoryWait)``: the one
  non-checkpoint wait (F09; F18's chained waits, F23; F30's ``FakeCrash`` through ``make``). ``finish_wait()`` ends it as an accepted ``WaitDone`` does
  (F14's replay and live forward step reuse it), and ``defer(fn)`` is the deferred-step
  slot (F18 I-3, F23): ``run()`` calls ``fn`` as its next step.

F04's hooks live here (its ``04-technical.md`` §7.3, 07 I-1, I-2): ``interp.stage`` is the
stage, ``take_checkpoint`` flushes it first and holds ``PrefetchImages`` last, new game and
restore always send the stage, and ``Say`` applies a line's dialogue words. The stage
executors are in ``runtime/stage.py``, which sits below this module and is registered here.
F05's (its §7.3, 07 C2): ``say_command`` resolves the line's body (``runtime/text.py``),
``body_for`` is F43's seam, and a restore logs W46 only once it commits.
F08's (its §6.3, 07 I-1, I-2): ``interp.audio`` is the story's audio, ``_hold`` caps audio
commands per burst and ``_release`` adds the sync, new game and restore always send
``AudioRestore``, a voiced line holds ``PlayVoice`` through ``attached``, and its accepted
``Advance`` holds ``EndVoice``. The executors are in ``runtime/audio.py``, registered here.
F07's (its §5.2, §7.2–7.5; 07 I-1 C1–C4): ``interp.choices`` is the story's pick record and
waiting menu, ``kept_line`` the line a question-less menu keeps (the Say executor and question
menus set it, ``scene`` and new game clear it), ``menu_open`` the menu shown now, and
``show_locked`` ``[choice] show_locked``. ``Advance`` is accepted only while a ``Say`` waits.
The executor, presenter, position check, and ``Choose`` handler are ``runtime/menu.py``'s,
registered here.
F12's (its §7.2–7.3, 07 I-1, I-3): ``interp.persistent`` is the session's store (never story
state: no snapshot, restore, or new game touches it). ``author_calls`` counts every guard
entry (``_author``); ``take_checkpoint``'s step 3b, after the story-variable walk, calls
``check_in_place`` only when author code ran since the last check, and so does the story's
end before ``StoryEnded``. An accepted ``Advance`` marks its line seen; F07's ``on_choose``
marks the pick (and the question).
F13's (its SPEC §5, 07 I-3): ``interp.history`` is the history log (story state,
runtime-held like ``choices``). ``take_checkpoint`` step 2a adds the one ``Say`` of ``cmd``
or ``attached``; F07's ``on_choose`` adds each pick. New game empties it; restore sets it
from the state at its commit only, and never records (presenters don't take checkpoints).

F09's (its §4.2, §6.2; 07 I-3): ``flush_stage`` holds the pending ``Shake``/``Flash`` after
the ``ShowStage``; a ``with`` or ``pause`` waits through ``begin_wait`` (``StoryWait``, no
snapshot, steps reset); ``WaitDone`` resumes it, and ``Advance`` is ignored during one.
``scene_since_line`` (set by ``scene``, cleared at a checkpoint that shows a line) is the
wait's ``hide_box``. The pending effects, the wait, its ``then``, and the deferred step are
runtime-only: new game and restore's commit clear them (``_reset_runtime``); ``_wait_seq``
only counts up, so a late ``WaitDone`` never matches a later wait. ``checkpoint()`` during a
wait is the last line or choice.

F18's (its SPEC §5, 07 I-3, I-4): ``interp.chapter`` is the current chapter's name (story
state, runtime-held like ``choices``: the next checkpoint stores it, restore sets it at its
commit, new game clears it), ``interp.chapters`` the ``ChapterIndex``, and ``card_shown`` the
title card on screen (runtime-only, reset with the waits). The executor is
``runtime/chapters.py``'s, registered here.

F22's (its SPEC §5, 07 I-6, I-7, I-9): ``interp.points`` is the launch's one ``Points``, built
from ``Program.meters`` (story state, runtime-held like ``choices``): ``take_checkpoint``
stores its cached ``PointsState``; new game resets it before the first default; restore merges
the saved meters in step 3 and installs them inside step 4's transaction (``_roll_back`` puts
the old values back). ``G``'s ``points`` view is bound to it here. ``points_warned`` holds the
sids W120 has warned about (dev, once per line per session). Restore step 3 also drops, with
the define-drop WARNING, a saved variable whose name was reserved later
(``state.reserved_since_save``). The executor is ``runtime/points.py``'s, registered here.

F14's (its ``04`` §4, §6.3, §7.2, §7.3, §10; 07 §3.2, I-1, I-5, I-6): ``interp.rollback_state``
is the on/off flag (story state, runtime-held like ``choices``: the next checkpoint stores it,
restore sets it at its commit, new game turns it on), and ``interp.timeline`` the runtime-only
``Timeline`` (``rollback_steps``, the app's ``[rollback] steps``). ``take_checkpoint`` runs
step 4b (``timeline.record``) on the snapshot and holds ``attached`` and ``cmd`` after it, with
step 4c (``fix_menu`` at a matched menu) between. New game empties the timeline; every OK
restore that isn't a landing leaves exactly the restored step (G12); ``restore(...,
landing=True)`` (``StepBack`` only) keeps it and makes the restored step the current one.
Forward (``StepForward``, 04 §7.4) re-runs the script quietly: ``run`` chains the steps while
``timeline.replay`` > 0 (``_forward_once``, ``busy``), each checkpoint is a chain landing
(step 5r, ``_land_replay``), and only the last releases a burst, in the restore form. During
the re-run a story wait ends at once as an accepted ``WaitDone`` (``begin_wait``, 07 I-4) and
the story's end drops what was held. New game, restore's commit, and ``_land_replay`` reset
the runtime-only fields through one helper, ``_reset_runtime`` (07 I-5). Restore step 3 also
drops a saved variable named after a statement word added since F02 (``rollback``, in any
case). The executor and the ``StepBack``/``StepForward`` handlers are
``runtime/rollback.py``'s, registered here.

F17's (its ``04`` §4, §7.1; 07 A2, A3, I-3, I-6): ``interp.nvl`` is the text mode and page
record (story state, runtime-held like ``choices``). ``take_checkpoint`` step 2b adds the
checkpoint's one ``Say`` in NVL (``nvl.record_line``), sharing step 2a's ``plain()``; F07's
``on_choose`` starts a new page after a pick in NVL (``nvl.on_pick``). New game sets ADV and
an empty page and sends no ``NvlPage``; restore sets the record at its commit and always holds
``NvlPage(on, page)`` right after ``AudioRestore`` (``_hold_restored``, so back and forward
landings send it too). ``_w102_logged`` (runtime-only, per launch) keeps W102 to once per run.
F18's ``chapter`` ends no page (F17 07 §3.4). The executor is ``runtime/nvl.py``'s,
registered here.

F19's (its ``04`` §7.1–7.3; 07 I-1, I-12): ``interp.endings`` and ``interp.routes`` are the
ending and route indexes, built with the store's "ending"/"route" kinds and its
``persistent.endings``/``routes`` views by ``endings.register`` (per interpreter, safe to
repeat); ``routes_warned`` is W132's once-per-route set. ``end_story()`` is the one way an
executor ends the story (``Ending``, its card's hold). The ``Ending`` and ``Lock`` executors
are ``runtime/endings.py``'s, registered here; neither is a checkpoint type.

F21's (its ``04`` §7.1–7.4; 07 I-4, I-8): ``interp.codex`` is the launch's ``Codex``
(``runtime/codex.install``: the index, the store's "tip" and "codex_read" kinds, ``G``'s
``codex`` reader bound to it). Its held items are story state, runtime-held like ``points``:
``take_checkpoint`` stores its cached ``ItemsState``; new game empties it before the first
default; restore merges the saved items in step 3 and installs them inside step 4's
transaction (``_roll_back`` puts the old list back). Tips are store records, never story
state. A saved variable ``codex`` is dropped by step 3's ``reserved_since_save``. The
``CodexLock`` executor is ``runtime/codex.py``'s, registered here beside F19's (07 I-4); not a
checkpoint type.

F23's (its ``04`` §3, §4.2, §5.4, §7.5; 07 I-6, I-7, I-12, I-13): ``interp.minigames`` is the
launch's plugin signatures (``MinigameSig`` by name; the runtime holds no plugin object).
``minigame`` is a checkpoint type like the menu: ``runtime/minigame.py``'s executor,
presenter, position check (which may run the plugin's side-effect-free ``check_args`` in one
guard entry, 07 C6), and ``MinigameDone``/``MinigameUsed`` handlers, registered here. Its
runtime-only fields: ``minigame_wait`` (``_snapshot`` stores it at a ``Minigame``),
``minigame_run``, ``minigame_accepted``, and ``minigame_used``; ``_reset_runtime`` commits a
restored wait, counts ``minigame_run`` up, and clears the flags (07 I-7(a)). ``defer`` is the
slot the accepted result's apply step runs through (07 I-13).

F20's (its ``04`` §7.2–§7.4, §10; 07 §3.2, A3, I-8, I-13): ``interp.flow`` is the path of node
keys reached this playthrough (story state, runtime-held like ``history``: step 2c sets it,
restore sets it at its commit, new game empties it), ``interp.flowchart`` the launch's
``FlowRecorder`` and ``interp.flow_anchors`` the graph's anchors (an empty mapping without a
graph), both from ``flowchart.register``. ``run`` looks each statement up once before its
executor runs (``FlowRecorder.anchor``); ``flow_pending`` (runtime-only, at most 16) holds the
nodes reached since the last checkpoint, cleared by ``_reset_runtime``. ``take_checkpoint``
step 2c (after 2b, before the snapshot) turns them into the path and the edge records, and
step 4d (after F14's 4c) writes the store and keeps the snapshot as their state. The
``Flowchart`` executor is ``runtime/flowchart.py``'s, registered here. A jump (04 §7.6, 07
§3.3, I-2) is ``restore(..., fresh_menu=True)``: at a ``Menu`` only F07's saved-``waiting``
check is skipped, and step 5 builds ``waiting`` anew (``menu.fresh_waiting``) after the
defaults, inside the transaction.

F28's (its ``04`` §3, §6.1–§6.3; 07 I-17): ``interp.glitch`` is the lasting glitch set (story
state, runtime-held like ``stage``: the next checkpoint stores it, restore sets it at its
commit, new game empties it). Runtime-only: ``_glitch_shown`` (the set last sent),
``pending_glitch`` (the moment's bursts and stops, emptied by ``flush_stage``'s last step and
by ``_reset_runtime``), and ``glitch_warned`` (W184's statements, never reset).
``_hold_restored`` holds ``Glitch(restored=True)`` right after ``ShowStage(restored)`` when the
saved set isn't empty. The ``Effect`` executor is ``runtime/glitch.py``'s, registered here.

F30's (its ``04`` §4.2, §5.4, §6.1; 07 I-4, I-7): ``interp.window_title`` is the window title
(story state, runtime-held like ``glitch``: the next checkpoint stores it, restore commits the
saved one if the program writes it, new game sets None); ``_title_sent`` (runtime-only) is the
title last held, so a restore or landing holds ``WindowTitle`` iff it or the restored title
isn't None. ``_hold_restored`` holds it right after F28's ``Glitch``. ``begin_wait``'s ``make``
builds the wait command (``StoryWait``; F30's ``FakeCrash``). The ``TitleEffect`` and
``CrashEffect`` executors are ``runtime/fourthwall.py``'s, registered here.

F32's (its ``04`` §3, §5.2; 07 I-1): ``interp.ui`` is the ``ui style`` and the Save/Load blocks
(story state, runtime-held like F30's title: the next checkpoint stores it, restore commits the
saved one, a style the config no longer has dropped with W205, new game sets ``EMPTY_UI``);
``_ui_sent`` (runtime-only) is the state last held, so a restore or landing holds ``UiStyle``
and ``UiBlocks`` by 04 §4.3's rule. ``_hold_restored`` holds them right after F30's
``WindowTitle``. The ``UiStatement`` executor is ``runtime/ui.py``'s, registered here.

``restore`` (§7.5) is a transaction: it checks the state and fills missing defaults
before it changes anything, so every result but ``OK`` leaves the interpreter as it was.
``restore(..., check_only=True)`` (F11 C10) runs only its scheme and position checks.
"""

import logging
from collections import Counter, deque
from collections.abc import Callable, Iterable, KeysView, Mapping
from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import TypeVar

from engine.core.logsetup import get_logger
from engine.core.minigame_types import MinigameSig, StoryNames
from engine.core.startvalues import StartOptions
from engine.runtime import limits
from engine.runtime.character import Character
from engine.runtime import audio as audio_mod
from engine.runtime import chapters as chapters_mod
from engine.runtime import codex as codex_mod
from engine.runtime import endings as endings_mod
from engine.runtime import flowchart as flowchart_mod
from engine.runtime import fourthwall as fourthwall_mod
from engine.runtime import glitch as glitch_mod
from engine.runtime import menu as menu_mod
from engine.runtime import metafiles as metafiles_mod
from engine.runtime import minigame as minigame_mod
from engine.runtime import nvl as nvl_mod
from engine.runtime import points as points_mod
from engine.runtime import rollback as rollback_mod
from engine.runtime import stage as stage_mod
from engine.runtime import ui as ui_mod
from engine.runtime.audio import EMPTY_AUDIO, AudioBurst, AudioState
from engine.runtime import effects as effects_mod
from engine.runtime.chapters import ChapterIndex, ChapterState, chapter_state
from engine.runtime.codex import Codex
from engine.runtime.endings import EndingIndex, RouteIndex
from engine.runtime.flowchart import EMPTY_FLOW, FlowRecorder, FlowState
from engine.runtime.glitch import EMPTY_GLITCH, GlitchState, PendingGlitch
from engine.runtime.commands import (Advance, AudioRestore, Choose, Command, Event, Flash,
                                     Glitch, MinigameDone, MinigameUsed, NvlPage, PrefetchImages, Say, Shake, ShowMenu, ShowStage, StepBack,
                                     StepForward, StoryEnded, StoryFailed, StoryWait, TaggedText, TitleCard,
                                     WaitDone)
from engine.runtime.dice import Pcg32
from engine.runtime.errors import (StoryError, log_error, map_exception, persistent_error,
                                   short_value, timeout_error, unsaveable_message, where)
from engine.runtime.guard import NO_GUARD, AuthorCodeGuard
from engine.runtime.history import EMPTY_HISTORY, HistoryState
from engine.runtime.limits import LABEL_RING
from engine.runtime.menu import EMPTY_CHOICES, ChoiceState
from engine.runtime.minigame import MinigameState, MinigameWait
from engine.runtime.nvl import EMPTY_NVL, NvlState
from engine.runtime.namespace import (Running, dice_core, install_dice, persistent_store,
                                      running_slot)
from engine.runtime.persistent import PersistentError, PersistentStore
from engine.runtime.stage import EMPTY_STAGE, StageState
from engine.runtime.points import Points, PointsState
from engine.runtime.rollback import DEFAULT_DEPTH, ROLLBACK_ON, RollbackState, Timeline
from engine.runtime.state import GameState, ItemsState, reserved_since_save
from engine.runtime.text import resolve_body
from engine.runtime.ui import EMPTY_UI, UiState
from engine.runtime.values import Unsaveable, freeze, kind_words
from engine.script import nodes
from engine.script.diagnostics import ScriptWarning
from engine.script.messages import format_message
from engine.script.nodes import Call, Default, If, Jump, PythonLine, Return, Statement
from engine.script.audio import PlayAudio, QueueMusic, StopAudio, Voice
from engine.script.codex import CodexLock
from engine.script.flowchart import Flowchart
from engine.script.fourthwall import CrashEffect, TitleEffect
from engine.script.glitch import Effect
from engine.script import effects as effect_nodes
from engine.script.menu import Menu
from engine.script.metafiles import MetaFile
from engine.script.minigame import Minigame
from engine.script.nvl import Nvl
from engine.script.program import Program
from engine.script.points import PointsChange
from engine.script.rollback import Rollback
from engine.script.routes import Ending, Lock
from engine.script.stage import Hide, Scene, Show
from engine.script.ui import UiStatement
from engine.script.words import ENGINE_NAMES


class Status(Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    ENDED = "ended"
    FAILED = "failed"


class RestoreResult(Enum):
    """What ``Interpreter.restore`` did. Every result but ``OK`` changed nothing; with
    ``check_only`` nothing changes whatever the result (F11 C10)."""

    OK = "ok"
    POSITION_NOT_FOUND = "position_not_found"    # no such line or call (ADR-0006 lookup)
    SCHEME_MISMATCH = "scheme_mismatch"          # saved with another identity scheme
    # A missing default failed, the restored line can't be shown (E75, E75h), or a value a
    # default bound can't be saved (E85e); ``error`` says which. Never from ``check_only``.
    DEFAULT_FAILED = "default_failed"


@dataclass(frozen=True)
class RestoreOutcome:
    """The result of a restore; ``error`` is set only for ``DEFAULT_FAILED``.

    ``restore`` has already logged that error, once (ERROR, area ``runtime``, its saved text
    and exception text put through ``echo()``), and ``error.logged`` is True: no caller logs
    it again. The caller tells the player, and the story goes on unchanged. A load (F11 C12)
    shows a notice (``notice_load_failed``; the dev W82 carries only ``error.code``) and
    never the error screen (``show_fatal_error``), so a hostile save can't end the session
    (F11 ``04`` §7.6)."""

    result: RestoreResult
    error: StoryError | None = None


class Step(Enum):
    """What an executor did. ``CONTINUE``: go on to the successor. ``WAIT``: a checkpoint
    was taken. ``JUMPED``: the executor moved the cursor (or ended the story) itself."""

    CONTINUE = "continue"
    WAIT = "wait"
    JUMPED = "jumped"


Executor = Callable[["Interpreter", Statement], Step]
# F09/F18/F23: a step run by ``run()`` itself (a wait's ``then``, the deferred slot). None or
# CONTINUE: go on to the successor of ``current``.
DeferredStep = Callable[["Interpreter"], "Step | None"]
Presenter = Callable[["Interpreter", Statement, GameState], Command]
PositionCheck = Callable[["Interpreter", Statement, GameState], bool]
EventHandler = Callable[["Interpreter", Event], None]

EXECUTORS: dict[type, Executor] = {}
PRESENTERS: dict[type, Presenter] = {}
POSITION_CHECKS: dict[type, PositionCheck] = {}
# I-7: the checkpoint types are exactly the node types registered with a presenter (a live
# view, not a second list).
CHECKPOINT_TYPES: KeysView[type] = PRESENTERS.keys()
EVENT_HANDLERS: dict[type, EventHandler] = {}

_END = object()            # END_OF_LABEL (§7.1): behaves exactly like ``return``
_MISSING = object()
_T = TypeVar("_T")

# SR-F03-28's PR-F03-07 log line (INFO, ``runtime``, dev runs): file ref, end line, label.
UNCALLED_END = "%s, line %d: the story ended at the end of label \"%s\", which wasn't called."


def _count(n: int, noun: str) -> str:
    """``"1 default"``, ``"2 defaults"``, ``"0 defaults"``."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _truth(code, G: dict) -> bool:
    """A condition's value and its ``bool()``: both author code (``Interpreter._test``)."""
    return bool(eval(code, G))


def register_executor(node_type: type[Statement], run: Executor,
                      present: Presenter | None = None,
                      check: PositionCheck | None = None) -> None:
    """One executor per ``Statement`` subclass (``ValueError`` on a duplicate). ``present``
    is required for checkpoint statements: it rebuilds their command from state alone on
    restore. ``check`` (checkpoint statements only) is that type's part of restore step 2
    (F11 C10): False when the saved state can't wait at the statement (F07: no pickable key
    left), giving POSITION_NOT_FOUND. It runs for ``check_only`` too, so it must change
    nothing and run no author code; the one exception (F23 ``07`` C6) is the minigame's,
    which runs the plugin's side-effect-free ``check_args`` in one guard entry."""
    if node_type in EXECUTORS:
        raise ValueError(f"an executor for {node_type.__name__} is already registered")
    if check is not None and present is None:
        raise ValueError(f"a position check for {node_type.__name__} needs a presenter")
    EXECUTORS[node_type] = run
    if present is not None:
        PRESENTERS[node_type] = present
    if check is not None:
        POSITION_CHECKS[node_type] = check


def register_event(event_type: type[Event], handler: EventHandler) -> None:
    """One handler per ``Event`` subclass (``ValueError`` on a duplicate); ``post``
    dispatches through this table (I-7)."""
    if event_type in EVENT_HANDLERS:
        raise ValueError(f"a handler for {event_type.__name__} is already registered")
    EVENT_HANDLERS[event_type] = handler


class Interpreter:
    """Runs one story. ``G`` is the namespace from ``LaunchJob`` (defines set); the
    interpreter owns it from here on. Nothing here raises for an author error: those end
    as ``StoryFailed`` (status FAILED)."""

    def __init__(self, program: Program, G: dict, *, guard: AuthorCodeGuard = NO_GUARD,
                 dev: bool = False, log: logging.Logger | None = None,
                 start: StartOptions | None = None, show_locked: bool = False,
                 persistent: PersistentStore | None = None,
                 rollback_steps: int = DEFAULT_DEPTH,
                 minigames: Mapping[str, MinigameSig] = MappingProxyType({})) -> None:
        self.program = program
        self.G = G
        # F12: the store behind G's ``persistent`` (the launch's), else ``persistent``, else
        # an empty in-memory one. A different store from G's is a programmer error.
        bound = persistent_store(G)
        if persistent is not None and bound is not None and bound is not persistent:
            raise ValueError("G's persistent facade holds another store")
        store = persistent if persistent is not None else bound
        self.persistent: PersistentStore = (
            store if store is not None
            else PersistentStore(identity_scheme=program.identity_scheme))
        self.author_calls = 0                               # F12 I-1: every guard entry
        self._checked_calls = 0                             # author_calls at the last 3b
        self.guard = guard
        self.dev = dev
        self.log = log if log is not None else get_logger("runtime")
        self.start = start                                  # F44 C1; restore ignores it
        core = dice_core(G)
        self.core: Pcg32 = core if core is not None else install_dice(G)
        self.reserved = program.define_names | ENGINE_NAMES | {"__builtins__"}
        running = running_slot(G)
        self.running: Running = running if running is not None else Running()
        self.status = Status.IDLE
        self.current: Statement | None = None
        self.call_stack: list[Call] = []
        # SR-F03-26: steps since the last line (or wait), and the labels entered since then
        # as (step, label), newest last; E45 counts those of the last LABEL_RING steps.
        self.steps = 0
        self.entered: deque[tuple[int, str]] = deque(maxlen=LABEL_RING)
        self.recent_py: deque[PythonLine | Default] = deque(maxlen=LABEL_RING)
        self.last_checkpoint: GameState | None = None
        self._held: list[Command] = []
        self._released: deque[Command] = deque()
        self._successors: dict[int, tuple[object, int]] = {}
        # F04 (04 §4): the stage (story state), and runtime-only records of what was sent.
        self.stage: StageState = EMPTY_STAGE
        self._stage_shown: StageState | None = None         # None: send it with the next line
        self._last_prefetch: PrefetchImages | None = None
        self._words_logged: set[str] = set()                 # PR-F04-12: per session
        # F05 W46: warnings noted while a restore presents its line, logged at the commit.
        self._restore_warnings: list[ScriptWarning] = []
        # F08 (04 §6.3): the story's audio (story state), and the held burst's audio counts.
        self.audio: AudioState = EMPTY_AUDIO
        self._audio_burst = AudioBurst()
        # F07 (04 §4): the pick record and waiting menu (story state); runtime-only: the
        # line a question-less menu keeps, the menu shown now with its question's shown
        # text, and [choice] show_locked (from the app; headless: run_headless's argument).
        self.choices: ChoiceState = EMPTY_CHOICES
        self.kept_line: str | None = None
        self.menu_open: tuple[ShowMenu, str | None] | None = None
        self.show_locked = show_locked
        self._picks_capped = False                          # 07 I-8: one WARNING per run
        self._restore_attached: tuple[Command, ...] | None = None   # present_menu → commit
        self._restore_menu_open: tuple[ShowMenu, str | None] | None = None
        # F13 (SPEC §5): the history log (story state, runtime-held like ``choices``).
        self.history: HistoryState = EMPTY_HISTORY
        # F09 (04 §3, §6.2): runtime-only, neutral at every checkpoint, never saved. The
        # pending effects (the last of each wins), whether a ``scene`` ran since the last
        # line (a wait's ``hide_box``), the current wait and its ``then`` (F18), the
        # deferred step (F18 I-3, F23 ``defer``), and the memo of ``spec_for``. Wait ids only
        # count up (never reset), so a late ``WaitDone`` never matches a later wait.
        self.pending_shake: Shake | None = None
        self.pending_flash: Flash | None = None
        self.scene_since_line = False
        self._wait_seq = 0
        self.waiting_for: int | None = None
        self.wait_then: DeferredStep | None = None
        self._deferred: DeferredStep | None = None
        self.transition_specs: dict[str, object] = {}
        # F18 (SPEC §5, 07 I-4): the current chapter's name (story state, runtime-held like
        # ``choices``; the next checkpoint stores it), the chapter index (immutable), and,
        # runtime-only, the title card on screen (``flush_stage``; reset with the waits).
        # ``install`` also registers F12's "chapter" kind on the store (safe to repeat).
        self.chapter: str | None = None
        self.card_shown: TitleCard | None = None
        self.chapters: ChapterIndex
        chapters_mod.install(self)
        # F22 (SPEC §5, 07 I-6): the meters (story state, runtime-held like ``choices``), G's
        # ``points`` view bound to them, and W120's once-per-line set (runtime-only).
        self.points = Points(program.meters)
        points_mod.bind_view(G, self.points)
        self.points_warned: set[str] = set()
        # F14 (04 §4): the on/off flag (story state, runtime-held like ``choices``) and the
        # timeline (runtime-only, never saved; ``rollback_steps`` is ``[rollback] steps``).
        self.rollback_state: RollbackState = ROLLBACK_ON
        self.timeline = Timeline(rollback_steps)
        # F17 (04 §4): the text mode and page record (story state, runtime-held like
        # ``choices``), and W102's once-per-run flag (runtime-only, never reset).
        self.nvl: NvlState = EMPTY_NVL
        self._w102_logged = False
        # F19 (04 §7.3, 07 I-1): the ending and route indexes (immutable, rebuilt by
        # ``register``), the store's "ending" and "route" kinds and its two views, and
        # W132's once-per-route set (runtime-only, never reset).
        self.endings: EndingIndex
        self.routes: RouteIndex
        self.routes_warned: set[str] = set()
        endings_mod.register(self)
        # F21 (04 §7.3): the codex (held items are story state, runtime-held like ``points``;
        # tips are the store's), the store's "tip" and "codex_read" kinds, G's reader bound.
        self.codex: Codex = codex_mod.install(self)
        # F23 (04 §3, 07 I-12): the launch's plugin signatures (loaded before the runtime
        # starts; no plugin object), the story's declared names (F24 A2, built once), and,
        # runtime-only, the minigame waited at, its start count (only counts up), whether
        # its result was accepted or an input used, and step 2's verdict (07 I-6).
        self.minigames: Mapping[str, MinigameSig] = minigames
        self._story_names: StoryNames | None = None
        self.minigame_wait: MinigameWait | None = None
        self.minigame_run = 0
        self.minigame_accepted = False
        self.minigame_used = False
        self._minigame_checked: tuple[GameState, Statement, MinigameWait | None] | None = None
        # F20 (04 §7.2, 07 §3.2): the path (story state, runtime-held like ``history``), the
        # nodes reached since the last checkpoint (runtime-only), the recorder and the graph's
        # anchors (``register``: the store's two kinds with a graph; safe to repeat).
        self.flow: FlowState = EMPTY_FLOW
        self.flow_pending: list[int] = []
        self.flowchart: FlowRecorder
        self.flow_anchors: Mapping[str, tuple[int, ...]]
        flowchart_mod.register(self)
        # F28 (04 §3): the lasting glitch set (story state, runtime-held like ``stage``); the
        # set last sent and the moment's bursts and stops (runtime-only); W184's statements
        # (runtime-only, never reset, at most 1,000).
        self.glitch: GlitchState = EMPTY_GLITCH
        self._glitch_shown: GlitchState = EMPTY_GLITCH
        self.pending_glitch = PendingGlitch()
        self.glitch_warned: set[str] = set()
        # F30 (04 §3, §6.1): the window title (story state, runtime-held like ``glitch``;
        # None: ``[game] title``) and, runtime-only, the title last held (never reset by a
        # restore's commit: it is what the window shows).
        self.window_title: str | None = None
        self._title_sent: str | None = None
        # F32 (04 §3, §5.2): the style and blocks (story state, runtime-held like the title)
        # and, runtime-only, the state last held (never reset by a restore's commit).
        self.ui: UiState = EMPTY_UI
        self._ui_sent: UiState = EMPTY_UI
        # F31 (04 §4.2, 07 §3(b)): the files port (runtime-only, never saved or snapshotted);
        # an in-memory folder until ``metafiles.attach`` (headless ``files=``, the app's disk).
        self.files = metafiles_mod.MetaFiles(metafiles_mod.MemoryFolder())

    # --- Commands (I-3: the one place to hold and the one place to release) ------------

    def _hold(self, cmd: Command) -> None:
        """Hold ``cmd`` for the burst. F08 I-2: past ``AUDIO_BURST_MAX`` executor-held
        audio commands in one burst, the rest are dropped and ``_release`` sends one
        ``AudioRestore(audio, "sync")`` instead; the story state stays exact."""
        if type(cmd) in audio_mod.CAPPED and not self._audio_burst.admit():
            return
        self._held.append(cmd)

    def _release(self) -> None:
        """End of a burst: the held commands become visible to ``take_commands``."""
        burst = self._audio_burst
        if burst.sync:                                      # F08 I-2: after the last kept
            audio_mod.insert_sync(self._held, self.audio)
        burst.reset()
        self._released.extend(self._held)
        self._held.clear()

    def _drop_held(self) -> None:
        """Drop the burst held so far (new game, a failure, a restore's commit)."""
        self._held.clear()
        self._audio_burst.reset()

    def take_commands(self, max_commands: int) -> list[Command]:
        """Up to ``max_commands`` released commands, oldest first (§7.3)."""
        out: list[Command] = []
        released = self._released
        while released and len(out) < max_commands:
            out.append(released.popleft())
        return out

    @property
    def released(self) -> int:
        """How many released commands wait for ``take_commands``. The app driver runs no
        more story while any wait (§7.3), so a burst over its cap spills in order."""
        return len(self._released)

    def checkpoint(self) -> GameState | None:
        """The last checkpoint; None before the first line and always None once FAILED."""
        return None if self.status is Status.FAILED else self.last_checkpoint

    # --- New game (§7.5) ---------------------------------------------------------------

    def new_game(self, seed: int) -> None:
        """Start the story from its first line with fresh variables. A failing default ends
        as FAILED with ``StoryFailed`` released."""
        G = self.G
        for key in [k for k in G if k not in self.reserved]:
            del G[key]
        self.core.seed(seed)
        self.call_stack.clear()
        self.reset_steps()
        self.recent_py.clear()
        self._drop_held()
        self.last_checkpoint = None
        self.current = None
        # F04 §7.3: the first line always carries a ShowStage, so a previous game's stage
        # never stays on screen.
        self.stage = EMPTY_STAGE
        # F08 §6.3 insertion 3: silence, sent before any other command of the game.
        self.audio = EMPTY_AUDIO
        self._hold(AudioRestore(EMPTY_AUDIO, "new_game"))
        self.choices = EMPTY_CHOICES                        # F07 (04 §7.2): no picks
        self.history = EMPTY_HISTORY                        # F13 (07 I-3)
        self.chapter = None                                 # F18 (07 I-4)
        self.points.reset()                                 # F22 (07 I-6): before defaults
        self.codex.new_game()                               # F21 (04 §7.4): before defaults
        self.rollback_state = ROLLBACK_ON                   # F14 (04 §6.3)
        self.nvl = EMPTY_NVL                                # F17 (SR-F17-05): ADV, no NvlPage
        self.flow = EMPTY_FLOW                              # F20 (04 §7.2): no node reached
        self.glitch = EMPTY_GLITCH                          # F28 (04 §6.3): no glitch on
        self.window_title = None                            # F30 (04 §6.1): the game title,
        self._title_sent = None                             # applied by the shell's reset
        self.ui = EMPTY_UI                                  # F32 (04 §5.2): likewise, by
        self._ui_sent = EMPTY_UI                            # the shell's in-game reset
        # 07 I-5: nothing sent yet (F04: the stage goes with the first line; F07: no menu, no
        # kept line), no wait or effect (F09, F18); F14: the timeline empty (TR-F14-03).
        self._reset_runtime(stage_shown=None, kept_line=None, menu_open=None)
        self.timeline.reset(None)
        for default in self.program.defaults:
            try:
                self.running.set(default.file.ref, default.value)
                G[default.name] = freeze(self._eval(default.value.code))
            except KeyboardInterrupt as e:
                if not self.guard.consume_fired():
                    raise
                self._fail(timeout_error(default, e, prefix=default, program=self.program))
                return
            except BaseException as e:
                self._fail(self._map(e, default, prefix=default))
                return
        start = self.start
        if start is not None:                               # F44 C1 step 3b
            for name, value in start.values:
                G[name] = freeze(value)
        label = (start.label if start is not None else None) or "start"
        self.status = Status.RUNNING
        self.log.info("%s", self._new_game_line(seed, label))
        self._enter(label, count=False)

    def _new_game_line(self, seed: int, label: str) -> str:
        """SR-F03-28 (PR-F03-32): ``New game: seed 42, 2 defaults.``, the seed in dev runs
        only; with start options (F44 C1) ``, starting at "<label>", <n> start values``.
        A count of 1 takes the singular: ``1 default``, ``1 start value``."""
        parts = [f"seed {seed}"] if self.dev else []
        parts.append(_count(len(self.program.defaults), "default"))
        if self.start is not None:
            values = _count(len(self.start.values), "start value")
            parts.append(f'starting at "{label}", {values}')
        return "New game: " + ", ".join(parts) + "."

    # --- Running (§7.2) ----------------------------------------------------------------

    @property
    def busy(self) -> bool:
        """F14 (04 §5.2): the story has work to run: RUNNING, or WAITING inside a forward
        chain (``timeline.replay`` > 0: ``run`` takes the next forward step itself). The
        driver keeps calling ``run`` while this holds."""
        status = self.status
        return status is Status.RUNNING or (status is Status.WAITING
                                            and self.timeline.replay > 0)

    def run(self, max_steps: int) -> None:
        """Up to ``max_steps`` steps while RUNNING; stops at a checkpoint (WAITING), the end
        (ENDED), or a run-time error (FAILED). Never raises for author errors; re-raises
        ``KeyboardInterrupt`` unless the guard fired. F14 (04 §7.4): inside a forward chain
        a checkpoint that isn't the chain's last is passed with the next forward step
        (``_forward_once``), so the chain goes on across calls while ``busy``."""
        timeline = self.timeline
        while max_steps > 0:
            if self.status is Status.WAITING and timeline.replay > 0:
                self._forward_once()                        # F14: the chain's next step
            if self.status is not Status.RUNNING:
                break
            stmt = self.current
            deferred = self._deferred                       # F18 I-3 / F23: run it first
            if deferred is not None or type(stmt) not in CHECKPOINT_TYPES:
                if self.steps >= limits.STEP_LIMIT:         # a line never counts (§7.2)
                    self._fail(self._runaway(stmt))
                    return
                self.steps += 1
            try:
                if deferred is not None:
                    self._deferred = None
                    step = deferred(self)
                    if step is None or step is Step.CONTINUE:
                        self._next_after(stmt)
                else:
                    ids = self.flow_anchors.get(stmt.sid)   # F20 (04 §7.2): one per step
                    if ids is not None:
                        self.flowchart.anchor(self, ids)
                    if EXECUTORS[type(stmt)](self, stmt) is Step.CONTINUE:
                        self._next_after(stmt)
            except KeyboardInterrupt as e:
                if self.guard.consume_fired():
                    self._fail(timeout_error(stmt, e, program=self.program))
                    return
                raise
            except StoryError as e:
                self._fail(e)
                return
            except BaseException as e:                    # SystemExit included
                self._fail(self._map(e, stmt))
                return
            max_steps -= 1

    # --- Steps (SR-F03-26, §7.2) -------------------------------------------------------

    def reset_steps(self) -> None:
        """Start counting steps again: at every checkpoint, and (F09) at every wait. The
        labels entered so far are forgotten with them."""
        self.steps = 0
        self.entered.clear()

    # --- Waits that aren't checkpoints (F09 04 §6.2; F18 I-3; F23) ----------------------

    def begin_wait(self, stmt: Statement | None = None, *, seconds: float | None = None,
                   for_stage: bool = False, then: DeferredStep | None = None,
                   make: Callable[..., StoryWait] = StoryWait) -> Step:
        """Wait at ``stmt`` (default ``current``) with no checkpoint: the caller has flushed
        the stage (``flush_stage``). F12 I-3's in-place check runs first; then hold
        ``StoryWait(next id, …)``, set WAITING with ``waiting_for`` = that id, reset the
        steps (a paced wait isn't a runaway), and release the burst. No snapshot and no
        ``PrefetchImages``: ``checkpoint()`` stays the last line or choice. ``then`` (F18)
        runs as the next step of ``run()`` once the wait is accepted (``finish_wait``), and
        may wait again. Returns WAIT. ``make(wait_id, sid, seconds, for_stage, hide_box)``
        builds the held command (F30 07 I-4: ``partial(FakeCrash, body=...)``).

        F14 (04 §7.4, 07 I-4): during a quiet forward re-run (``timeline.replaying``) the
        wait ends at once, exactly as an accepted ``WaitDone``: the id is used up, the steps
        reset, nothing is held or released, and ``then`` runs as the next step (JUMPED: the
        story stays at ``stmt`` until it has); without one, CONTINUE (the successor)."""
        assert self.status is Status.RUNNING, "begin_wait while not running"
        stmt = self.current if stmt is None else stmt
        assert stmt is not None
        error = self._check_persistent(stmt)                # F12 I-3
        if error is not None:
            raise error
        if self.timeline.replaying:                         # F14 07 I-4
            self._wait_seq += 1
            self.current = stmt
            self.reset_steps()
            if then is not None:
                self.defer(then)
                return Step.JUMPED
            return Step.CONTINUE
        self._wait_seq += 1
        self._hold(make(self._wait_seq, stmt.sid, seconds, for_stage, self.scene_since_line))
        self.current = stmt
        self.waiting_for = self._wait_seq
        self.wait_then = then
        self.reset_steps()
        self.status = Status.WAITING
        self._release()
        return Step.WAIT

    def finish_wait(self) -> None:
        """End the current wait exactly as an accepted ``WaitDone`` does: RUNNING, and the
        wait's ``then`` (if any) runs as the next step of ``run()`` (``defer``), never here;
        without one the story moves to the successor of ``current`` (a block end crossed is
        a step, as for ``Advance``). F14's replay and live forward step call this too
        (F14 07 I-4), so nothing skips past a ``then``."""
        assert self.status is Status.WAITING and self.waiting_for is not None
        then = self.wait_then
        self.waiting_for = None
        self.wait_then = None
        self.status = Status.RUNNING
        if then is not None:
            self.defer(then)
            return
        current = self.current
        assert current is not None
        try:
            self._next_after(current)
        except StoryError as e:                             # E45 (only under a patched limit)
            self._fail(e)

    def defer(self, fn: DeferredStep) -> None:
        """The deferred-step slot (F18 I-3; F23's public ``defer``): ``run()`` calls
        ``fn(interp)`` as its next step, under the loop's error mapping and step count, then
        moves to the successor of ``current`` unless ``fn`` returned WAIT or JUMPED. One at
        a time."""
        assert self._deferred is None, "a deferred step is already pending"
        self._deferred = fn

    def _reset_runtime(self, *, stage_shown: StageState | None, kept_line: str | None,
                       menu_open: "tuple[ShowMenu, str | None] | None",
                       minigame_wait: MinigameWait | None = None,
                       glitch_shown: GlitchState = EMPTY_GLITCH) -> None:
        """The one reset of the runtime-only fields (F14 07 I-5), for new game, restore's
        commit, and F14 step 3's ``_land_replay``, so a rollback landing equals a load of
        that step; a later feature adds its own field here, once. F04: the stage last sent,
        no prefetch sent yet. F07: the kept line and the menu shown. F09 §6.2 item 3, F18
        I-3: no wait, no ``then``, no deferred step, no pending effect, no scene since the
        last line, no title card on screen (the restore burst's ``ShowStage`` has none);
        ``_wait_seq`` keeps counting, so a late ``WaitDone`` is ignored. F14: no wall
        pending and no forward chain (the timeline's states are the caller's). F14's
        ``_land_replay`` calls it too, so a forward landing equals a load of that step.
        F23 (07 I-7(a)): the wait committed (a restored minigame's, else None), with it one
        more ``minigame_run`` (the restore command carries it, so a late event never
        matches), and no accepted result or used input. F20 (07 A3): no node pending. F28
        (04 §6.3): ``glitch_shown`` is the set on screen (the restored one; empty on new
        game), and no burst or stop is pending."""
        self._stage_shown = stage_shown
        self._last_prefetch = None
        self.kept_line = kept_line
        self.menu_open = menu_open
        timeline = self.timeline
        timeline.block_pending = False
        timeline.replay = 0
        timeline.replaying = False
        self.waiting_for = None
        self.wait_then = None
        self._deferred = None
        self.card_shown = None
        self.pending_shake = None
        self.pending_flash = None
        self.scene_since_line = False
        self.minigame_wait = minigame_wait
        if minigame_wait is not None:
            self.minigame_run += 1
        self.minigame_accepted = False
        self.minigame_used = False
        self.flow_pending.clear()
        self._glitch_shown = glitch_shown
        self.pending_glitch.clear()

    def _step(self, at: Statement, line: int | None = None) -> None:
        """Count one more step taken inside a statement (a further condition, ``else``
        taken) or after it (an end of a block); instead of step ``STEP_LIMIT + 1``, raise
        E45 at ``at`` (``line``: its last line for an end of a block)."""
        if self.steps >= limits.STEP_LIMIT:
            raise self._runaway(at, line)
        self.steps += 1

    def fail_timeout(self) -> StoryError:
        """E85m at the current statement (the watchdog's interrupt reached the driver's pump
        or ``App.run``, past ``run``); FAILED with ``StoryFailed`` released. Returns the
        error."""
        error = timeout_error(self.current)
        self._fail(error)
        return error

    def _map(self, e: BaseException, stmt: Statement, *, prefix: Default | None = None
             ) -> StoryError:
        return map_exception(e, stmt, prefix=prefix, names=self.G, program=self.program,
                             guard=self.guard)

    def _fail(self, error: StoryError) -> None:
        """Drop the burst so far, log the error once (ERROR, ``runtime``, §7.11), and
        release only ``StoryFailed`` (PR-F03-22)."""
        self._drop_held()
        self._end_chain()                                   # F14: a re-run fails as live
        if isinstance(error, StoryError) and not error.logged:
            log_error(self.log, error)
        self.status = Status.FAILED
        self._hold(StoryFailed(error))
        self._release()

    # --- Events (I-7) -----------------------------------------------------------------

    def post(self, event: Event) -> None:
        """Dispatch ``event`` through ``EVENT_HANDLERS``; an unknown event is ignored."""
        handler = EVENT_HANDLERS.get(type(event))
        if handler is not None:
            handler(self, event)

    # --- Author code (§7.7) -----------------------------------------------------------

    def _author(self, run: Callable[..., _T], *args: object) -> _T:
        """The one guard-entry helper: every call into author code the interpreter makes
        (``$``, default, condition and its ``bool()``; F07's conditions) runs here, between
        ``guard.enter()`` and ``guard.exit()``, so the watchdog can interrupt it. F12 I-1
        counts ``author_calls`` here, at every guard entry."""
        guard = self.guard
        self.author_calls += 1
        guard.enter()
        try:
            return run(*args)
        finally:
            guard.exit()

    def _exec(self, code) -> None:
        self._author(exec, code, self.G)

    def _eval(self, code) -> object:
        return self._author(eval, code, self.G)

    def _test(self, code) -> bool:
        """A condition's truth: ``eval`` and the ``bool()`` of its value (an author
        ``__bool__`` may loop), both under the guard."""
        return self._author(_truth, code, self.G)

    # --- Cursor (§7.1) ----------------------------------------------------------------

    def _successor(self, stmt: Statement) -> tuple[object, int]:
        """The next statement after ``stmt`` (or ``_END``) and the block ends crossed."""
        key = id(stmt)
        found = self._successors.get(key)
        if found is not None:
            return found
        label, path, ends = stmt.label, stmt.path, 0
        at = self.program.at
        while True:
            nxt = at(label, path[:-1] + (path[-1] + 1,))
            if nxt is not None:
                found = (nxt, ends)
                break
            if len(path) == 1:
                found = (_END, ends + 1)
                break
            path = path[:-2]
            ends += 1
        self._successors[key] = found
        return found

    def _next_after(self, stmt: Statement) -> None:
        """Move to the successor of ``stmt``; the end of a label block is a ``return``."""
        nxt, ends = self._successor(stmt)
        for _ in range(ends):                               # each block end is a step
            self._step(stmt, stmt.end_line)
        if nxt is _END:
            if not self.call_stack and self.dev:
                self._log_uncalled_end(stmt)
            self._return()
        else:
            self.current = nxt  # type: ignore[assignment]

    def _enter(self, label: str, *, count: bool = True) -> None:
        if count:
            self.entered.append((self.steps, label))
        block = self.program.labels[label].block
        if block:
            self.current = block[0]
        else:
            self._return()

    def _return(self) -> None:
        """Pop to the successor of the ``Call``; an empty stack ends the story."""
        if not self.call_stack:
            self._end()
            return
        call = self.call_stack.pop()
        self.entered.append((self.steps, call.label))
        self._next_after(call)

    def _log_uncalled_end(self, last: Statement) -> None:
        """SR-F03-28 (PR-F03-07), dev runs: the story ends at the end of a label that wasn't
        called. The line is the ``end_line`` of the last statement run (where a ``jump``
        would go): the label block's last statement, or, when that is an ``if``, the last
        statement of the branch taken (an ``If``'s own ``end_line`` is its header's)."""
        self.log.info(UNCALLED_END, last.file.ref, last.end_line, last.label)

    def _end(self) -> None:
        """The story ends: F12 I-3 checks in-place persistent changes first (a failure is an
        ordinary ``StoryFailed``), then ``StoryEnded``. F14 (04 §7.4): a quiet re-run that
        ends drops what it held first, so ``StoryEnded`` comes alone."""
        at = self.current
        if at is not None:
            error = self._check_persistent(at)
            if error is not None:
                self._fail(error)
                return
        if self.timeline.replaying:
            self._drop_held()
            self._end_chain()
        self.status = Status.ENDED
        self.current = None
        self._hold(StoryEnded())
        self._release()

    def end_story(self) -> Step:
        """F19 (04 §5, 07 I-12): the one way an executor (or a wait's ``then``) ends the
        story: ``_end`` (F12's in-place check, F14's dropped holds while replaying,
        ``StoryEnded``, ENDED, ``current`` None). Returns JUMPED: there is no successor."""
        self._end()
        return Step.JUMPED

    # --- Checkpoints (§7.4) -----------------------------------------------------------

    def take_checkpoint(self, stmt: Statement, cmd: Command, *,
                        attached: tuple[Command, ...] = ()) -> None:
        """The one checkpoint routine; every checkpoint executor (F03 ``Say``, F07 menu)
        calls it. Burst order (I-4; F08 07 I-2): [F08 AudioRestore] [commands held on the
        way, in run order, F08 EndVoice included] [F04 ShowStage] ``attached`` (F08
        PlayVoice) ``cmd`` [F04 PrefetchImages]. Step 2a (F13) adds the one ``Say`` of
        ``cmd`` or ``attached`` (a line, or a menu's question) to ``history``; its
        ``plain()`` is passed in so F17's step 2b (in NVL, the same ``Say`` joins the page
        record) shares the one call (F17 I-6).

        F14 (07 §3.2, A2): step 4b keeps the snapshot in the timeline; step 4c (``fix_menu``)
        may lock a matched fixed menu's command, so ``attached`` and ``cmd`` are held after
        it (old step 2; the burst order is the same). A failure before 4b (E85e, F12's 3b)
        records nothing, and ``_fail`` drops what was held. Step 5r: inside a quiet forward
        re-run the checkpoint is a chain landing (``_land_replay``) instead of 5-6.

        F20 (04 §7.2, 07 A3): step 2c turns the nodes reached since the last checkpoint into
        the path (so the snapshot holds them) and their edge records; step 4d, after 4c,
        records them in the store and keeps the snapshot as their state. A failure before
        4b records nothing."""
        stage_mod.flush_stage(self)                        # 1. F04: ShowStage if changed
        say = cmd if type(cmd) is Say else next(            # 2a. F13: the one line shown
            (c for c in attached if type(c) is Say), None)
        if say is not None:
            spans = say.body.plain()
            self.history = self.history.add_line(say, spans=spans)
            nvl_mod.record_line(self, say, stmt, spans=spans)   # 2b. F17
            self.scene_since_line = False                   # F09: a line is shown
        arrived = (self.flowchart.flush(self)               # 2c. F20
                   if self.flow_pending else None)
        state = self._snapshot(stmt, self.call_stack)       # 3.-4. (may raise E85e)
        error = self._check_persistent(stmt)                # 3b. F12
        if error is not None:
            raise error
        timeline = self.timeline
        matched = timeline.record(state)                    # 4b. F14 (TR-F14-01)
        if matched and type(stmt) is Menu:                  # 4c. F14 (§7.5, 07 I-7)
            cmd = rollback_mod.fix_menu(self, stmt, cmd)  # type: ignore[arg-type]
        if arrived is not None:                             # 4d. F20 (07 A3)
            self.flowchart.record(arrived, state)
        for extra in attached:                              # 2. (after 4c, 07 §3.2)
            self._hold(extra)
        self._hold(cmd)
        if timeline.replaying:                              # 5r. F14 (§7.4)
            self._land_replay(stmt, state, matched)
            return
        timeline.shown = timeline.cursor
        self._settle(stmt, state)                           # 4.-6.

    # --- Forward (F14 04 §7.4; 07 I-4, I-5) ---------------------------------------------

    def _forward_once(self) -> None:
        """One forward step of a chain, from WAITING, with the same input as the first
        pass: a story wait (F09, F18's card) ends as an accepted ``WaitDone`` does
        (``finish_wait``, 07 I-4); a line takes ``Advance`` (``EndVoice``, the seen mark);
        a menu takes the remembered pick (F07's ``on_choose`` checks it is pickable). There
        is no branch for anything else (F23 A5: a minigame). A step that doesn't start
        (no remembered pick, or it isn't pickable now) ends the chain with no change."""
        t = self.timeline
        t.replaying = True
        current = self.current
        if self.waiting_for is not None:
            self.finish_wait()
        elif type(current) is nodes.Say:
            _on_advance(self, Advance(current.sid))
        elif type(current) is Menu:
            key = t.remembered_pick(current.sid)
            if key is not None:
                menu_mod.on_choose(self, Choose(current.sid, key))
        if self.status is not Status.RUNNING:
            self._end_chain()

    def _end_chain(self) -> None:
        """No forward chain any more: the current step is the one shown."""
        t = self.timeline
        t.replay = 0
        t.replaying = False
        t.shown = t.cursor

    def _land_replay(self, stmt: Statement, state: GameState, matched: bool) -> None:
        """Checkpoint step 5r (§7.4): a quiet re-run reached ``stmt``. What the run held
        (live music, one-shots, effects, transitions, the line itself) is dropped. While
        steps are left and the step matched the remembered one (and isn't a chain stop, F23
        A1), it settles with nothing released and ``run`` takes the next forward step.
        Otherwise this is the landing: the runtime-only fields are reset as a load's commit
        does (07 I-5, ``_reset_runtime`` with the presenter's menu), and the step is held
        in the restore form (``_hold_restored``), so it equals a load of that step."""
        t = self.timeline
        assert t.replaying, "_land_replay while not replaying"
        t.replay -= 1
        t.landings += 1
        self._drop_held()
        if (t.replay > 0 and matched and t.cursor < len(t.states) - 1
                and type(stmt) not in rollback_mod.CHAIN_STOPS):
            self._settle(stmt, state, release=False)        # intermediate: nothing released
            return
        self._end_chain()
        self._restore_warnings = []
        self._restore_attached = self._restore_menu_open = None
        cmd = PRESENTERS[type(stmt)](self, stmt, state)     # the restore form
        attached, menu_open = self._restore_attached, self._restore_menu_open
        self._restore_attached = self._restore_menu_open = None
        self._reset_runtime(stage_shown=state.stage,
                            kept_line=menu_mod.restored_kept_line(self, stmt, self.choices),
                            menu_open=menu_open, minigame_wait=state.minigame.waiting,
                            glitch_shown=state.glitch)
        for warning in self._restore_warnings:              # F05 W46, as a restore's
            self.log.warning("%s", warning.format())
        self._restore_warnings = []
        self._hold_restored(stmt, state, cmd, state, attached, landing=True)

    def _check_persistent(self, at: Statement) -> StoryError | None:
        """Step 3b (F12 ``04`` §7.2): when author code ran since the last check, the
        store's watched values are compared with their last checked form (E181, E183 for a
        change it can't keep). The error is at the newest ``$`` line or default whose names
        hold the value's name, else at ``at`` (F03's E85e attribution)."""
        if self.author_calls == self._checked_calls:
            return None
        self._checked_calls = self.author_calls
        try:
            self.persistent.check_in_place()
        except PersistentError as e:
            owner: Statement | Default = at
            line = None
            for candidate in reversed(self.recent_py):
                piece = candidate.py if isinstance(candidate, PythonLine) else candidate.value
                if piece.code is not None and e.name in piece.code.co_names:
                    owner, line = candidate, piece.line
                    break
            code, message = persistent_error(e, owner)
            return StoryError(message, code=code, **where(owner, line))
        return None

    def _snapshot(self, stmt: Statement, call_stack: list[Call], *,
                  stage: StageState | None = None,
                  audio: AudioState | None = None,
                  choices: ChoiceState | None = None,
                  history: HistoryState | None = None,
                  chapter: ChapterState | None = None,
                  points: PointsState | None = None,
                  rollback: RollbackState | None = None,
                  nvl: NvlState | None = None,
                  items: ItemsState | None = None,
                  minigame: MinigameState | None = None,
                  flow: FlowState | None = None,
                  glitch: GlitchState | None = None,
                  window_title: object = _MISSING,
                  ui: UiState | None = None) -> GameState:
        """Steps 3 and 4 of the checkpoint routine: the frozen state at ``stmt`` (may raise
        E85e). Changes nothing, so restore can build it inside its transaction (``stage``,
        ``audio``, F07's ``choices``, F13's ``history``, F18's ``chapter``, F22's ``points``,
        F14's ``rollback``, F17's ``nvl``, F21's ``items``, and F23's ``minigame``: the restored
        ones, which are committed only later; default ``self.stage``, ``self.audio``,
        ``self.choices``, ``self.history``, ``self.chapter``, ``self.points.state()``,
        ``self.rollback_state``, ``self.nvl``, ``self.codex.state()``, and the wait at a
        ``Minigame``; F20's ``flow``, default ``self.flow``; F28's ``glitch``, default
        ``self.glitch``; F30's ``window_title``, default ``self.window_title``, where None is a
        value; F32's ``ui``, default ``self.ui``). Nothing is copied but the
        variables: every other field is a frozen value shared with the live one (and the
        history's entries with every earlier state)."""
        variables = self._freeze_variables(stmt)            # 3. may raise E85e
        return GameState(                                   # 4.
            position=stmt.sid,
            position_at=(stmt.label, stmt.path),
            call_stack=tuple((c.sid, (c.label, c.path)) for c in call_stack),
            variables=MappingProxyType(variables),
            dice=self.core.state,
            identity_scheme=self.program.identity_scheme,
            stage=self.stage if stage is None else stage,   # F04
            audio=self.audio if audio is None else audio,   # F08
            choices=self.choices if choices is None else choices,   # F07
            history=self.history if history is None else history,   # F13
            chapter=chapter_state(self.chapter) if chapter is None else chapter,  # F18
            points=self.points.state() if points is None else points,             # F22
            rollback=self.rollback_state if rollback is None else rollback,       # F14
            nvl=self.nvl if nvl is None else nvl,                                 # F17
            items=self.codex.state() if items is None else items,                 # F21
            minigame=(minigame_mod.snapshot_state(self, stmt) if minigame is None  # F23
                      else minigame),
            flow=self.flow if flow is None else flow,                             # F20
            glitch=self.glitch if glitch is None else glitch,                     # F28
            window_title=(self.window_title if window_title is _MISSING           # F30
                          else window_title),                 # type: ignore[arg-type]
            ui=self.ui if ui is None else ui,                                     # F32
        )

    def _settle(self, stmt: Statement, state: GameState, *, release: bool = True) -> None:
        """Steps 4 (store) to 6 of the checkpoint routine: wait at ``stmt`` and release the
        burst (F14: not at a forward chain's intermediate landing, whose held commands the
        next landing drops)."""
        self.last_checkpoint = state
        prefetch = stage_mod.lookahead(self, stmt)          # 5. F04: only when it changed
        if prefetch is not None and prefetch != self._last_prefetch:
            self._hold(prefetch)
            self._last_prefetch = prefetch
        self.recent_py.clear()                              # 6.
        self.reset_steps()
        self.current = stmt
        self.status = Status.WAITING
        if release:
            self._release()

    # --- Restore (§7.5, §9.1; TR-F03-04) -----------------------------------------------

    def restore(self, state: GameState, *, use_hints: bool = False,
                check_only: bool = False, landing: bool = False,
                fresh_menu: bool = False) -> "RestoreOutcome":
        """Go back to ``state``: the waiting line is shown again (``restored=True``) and
        the story waits there. Allowed in every status; a mid-run restore drops the
        unfinished burst. Everything is checked, and missing defaults are filled, before
        anything changes: every result but ``OK`` leaves the interpreter exactly as it was.

        ``state`` comes from ``checkpoint()`` or ``GameState.from_json`` (which always runs
        first for data from outside the process). ``use_hints`` (F11's policy) lets a sid
        that no longer exists be found by its saved location. F44's ``start`` is ignored.

        ``check_only`` (F11 C10, TR-F11-06): run steps 1-2 only (the identity scheme, the
        positions, and every registered position check) and return OK, SCHEME_MISMATCH,
        or POSITION_NOT_FOUND. Nothing changes and nothing is logged, whatever the result.
        It runs no author code (but F23's guarded ``check_args``, 07 C6, whose verdict a
        full restore of the same state object reuses), so it can't see a ``default`` that
        would fail or a line that can't be shown: it is advisory, and the full restore is the transaction (a
        load's commit can still return any result, F11 I-1).

        DEFAULT_FAILED is logged here, once; see ``RestoreOutcome`` for what the caller
        does (a load shows a notice, never the error screen: F11 C12).

        F14: an OK restore leaves exactly the restored step in the timeline (G12, TR-F14-03:
        a load, an F20 jump, an F39 reload), unless ``landing``, which only ``on_step_back``
        passes, with a state the timeline keeps (never the driver): then the timeline stays,
        and that step becomes the current one, holding the new snapshot (04 §7.3).

        ``fresh_menu`` (F20 ``04`` §7.6, 07 §3.3; only the two jump paths pass it, never with
        ``landing``: ``ValueError``): at a ``Menu`` position F07's saved-``waiting`` check is
        skipped (every other check runs), and in step 5, after the defaults, the conditions
        run again (``menu.fresh_waiting``, under the guard): its ``waiting`` replaces the
        saved one for the presenter, the snapshot, and the commit. Any failure, E178 and the
        watchdog included, is DEFAULT_FAILED like a failing default: nothing changes.
        """
        if fresh_menu and landing:
            raise ValueError("restore: fresh_menu is for a jump, never a landing")
        found = self._check_position(state, use_hints, fresh_menu=fresh_menu)
        if type(found) is RestoreOutcome:
            return found
        if check_only:
            return RestoreOutcome(RestoreResult.OK)
        pos, call_stack = found  # type: ignore[misc]
        program = self.program
        # 3. Fresh copies of the saved variables; a name that is a define now, or that the
        # engine reserved since (F22 07 I-9; F14 07 I-1: a later statement word), is dropped.
        # F22: the saved meters merged. F21: the saved items merged (hidden names kept).
        define_names = program.define_names
        variables: dict[str, object] = {}
        dropped: list[str] = []
        for name, value in state.variables.items():
            if name in define_names or reserved_since_save(name):
                dropped.append(name)
            elif name not in self.reserved and not name.startswith("_"):
                variables[name] = freeze(value)
        points = self.points.merge(state.points)
        held = self.codex.merged(state.items)
        items = state.items if held == state.items.held else ItemsState(held)
        # 4. The transaction: G and dice change here, and only here until the commit.
        self._restore_warnings = []
        self._restore_attached = None                       # F07: set by present_menu
        self._restore_menu_open = None
        choices = menu_mod.restored_choices(pos, state)     # F07 step 6 (04 §7.5)
        G, core = self.G, self.core
        saved_vars = {k: v for k, v in G.items() if k not in self.reserved}
        saved_dice, saved_ready = core.state, core.ready
        saved_points = self.points.state()
        saved_items = self.codex.state()
        try:
            for key in saved_vars:
                del G[key]
            G.update(variables)
            core.state = state.dice
            core.ready = True
            self.points.install(points)                     # F22 (07 I-6): defaults see it
            self.codex.install(items)                       # F21 (04 §7.4): defaults see it
            # 5. Missing defaults, in order; each sees the restored values (SR-F03-04).
            error = self._fill_defaults()
            if error is None and fresh_menu and type(pos) is Menu:     # F20 (07 §3.3)
                state, error = self._fresh_menu(pos, state)
                choices = state.choices
            if error is None:
                # Presented and frozen before the commit, so a line that can't be shown
                # (E75, E75h) or a variable a default bound that can't be saved (E85e)
                # refuses the restore instead of failing the story half-restored.
                try:
                    cmd = PRESENTERS[type(pos)](self, pos, state)
                    ui, w205 = ui_mod.restored_ui(state.ui, program)    # F32 (04 §5.2)
                    snapshot = self._snapshot(pos, call_stack, stage=state.stage,
                                              audio=state.audio, choices=choices,
                                              history=state.history, chapter=state.chapter,
                                              points=points, rollback=state.rollback,
                                              nvl=state.nvl, items=items,
                                              minigame=minigame_mod.restored_state(
                                                  self, pos, state),     # F23 (07 I-7)
                                              flow=state.flow,           # F20 (07 §3.2)
                                              glitch=state.glitch,       # F28 (04 §6.3)
                                              window_title=fourthwall_mod.restored_title(
                                                  program, state),       # F30 (04 §6.1)
                                              ui=ui)                     # F32
                    if w205 is not None:                # logged only if the restore commits
                        self.note_restore_warning(ScriptWarning(w205, code="W205"))
                except StoryError as e:
                    error = e
                except Exception as e:          # noqa: BLE001 (saved values are untrusted)
                    error = self._map(e, pos)
        except BaseException:
            self._roll_back(saved_vars, saved_dice, saved_ready, saved_points, saved_items)
            raise                               # a real Ctrl+C: F01's interrupt path
        if error is not None:
            self._roll_back(saved_vars, saved_dice, saved_ready, saved_points, saved_items)
            self._restore_warnings = []
            self._restore_attached = self._restore_menu_open = None
            if not error.logged:
                log_error(self.log, error)
            return RestoreOutcome(RestoreResult.DEFAULT_FAILED, error)
        # 6. Commit: the restored position; the interrupted burst and counters are dropped.
        self.call_stack = call_stack
        self.current = pos
        self.steps = 0
        self.entered.clear()
        self.recent_py.clear()
        self._drop_held()
        self._released.clear()
        self.stage = state.stage                            # F04 (07 I-1, I-2)
        self.audio = state.audio                            # F08 (§6.3 insertion 3)
        self.choices = choices                              # F07 (04 §7.5 step 6)
        self.glitch = state.glitch                          # F28 (04 §6.3), as the stage
        # 07 I-5: F04 (the saved stage is sent below), F07, F09/F18, F14's wall and chain,
        # and F23's wait (the effective one, committed here, 07 I-7).
        self._reset_runtime(stage_shown=state.stage,
                            kept_line=menu_mod.restored_kept_line(self, pos, choices),
                            menu_open=self._restore_menu_open,
                            minigame_wait=snapshot.minigame.waiting,
                            glitch_shown=state.glitch)
        attached = self._restore_attached
        self._restore_attached = self._restore_menu_open = None
        # F13 I-3: history is set here, at the commit, and only here; the restore burst
        # (step 7) never runs checkpoint step 2a, so the line is not recorded again.
        self.history = state.history
        self.chapter = state.chapter.current                # F18 (07 I-4): at the commit only
        self.rollback_state = state.rollback                # F14 (04 §10): at the commit only
        self.nvl = state.nvl                                # F17 (04 §7.1): at the commit only
        self.flow = state.flow                              # F20 (07 §3.2): at the commit only
        if landing:                                         # F14 (04 §7.3): a back landing
            self.timeline.land(state, snapshot)
        else:                                               # F14 G12 (TR-F14-03)
            self.timeline.reset(snapshot)
        if dropped:
            self._log_dropped(dropped)
        for warning in self._restore_warnings:              # F05 W46 (07 G5)
            self.log.warning("%s", warning.format())
        self._restore_warnings = []
        self._hold_restored(pos, state, cmd, snapshot, attached, landing=landing)   # 7.
        return RestoreOutcome(RestoreResult.OK)

    def _fresh_menu(self, pos: Menu, state: GameState
                    ) -> tuple[GameState, StoryError | None]:
        """F20's restore step 5 at a menu (07 §3.3): ``state`` with ``waiting`` built anew
        from the restored values (``state'``), or the error that refuses the restore: E178,
        an author exception mapped at the menu, or E85m when the watchdog fired. A real
        Ctrl+C is re-raised (restore's ``except BaseException`` rolls back)."""
        try:
            waiting = menu_mod.fresh_waiting(self, pos, state)
        except KeyboardInterrupt as e:
            if not self.guard.consume_fired():
                raise
            return state, timeout_error(pos, e, program=self.program)
        except StoryError as e:
            return state, e
        except BaseException as e:                          # author code, as ``run`` maps it
            return state, self._map(e, pos)
        return replace(state, choices=ChoiceState(state.choices.picks, waiting)), None

    def _hold_restored(self, pos: Statement, state: GameState, cmd: Command,
                       snapshot: GameState, attached: tuple[Command, ...] | None, *,
                       landing: bool = False) -> None:
        """Restore step 7, the one place that holds a restore burst (F14 07 I-5: its
        landings reuse it; F17 I-3): [F08 AudioRestore] [F17 NvlPage(on, page)] [F04
        ShowStage(restored)] [F28 Glitch(restored), only when the saved set isn't empty] [F30
        WindowTitle, iff the restored or the shown title isn't None] [F32 UiStyle, iff the
        restored or the shown style isn't None] [F32 UiBlocks, iff either has a block] [F08
        PlayVoice(restored)] [F07
        Say(question or kept line, restored)] ``cmd`` [F04 PrefetchImages], then checkpoint
        steps 4-6. ``attached`` is what the presenter held (F07 ``present_menu``: the
        question's voice and ``Say``, or the kept line); None for a line, whose voice comes
        from ``cmd`` (F08 I-1).

        The saved stage is always sent, even when it equals the one on screen; no stage
        statement runs, so the stage can't fail a restore (F04 §7.3). Likewise the saved
        audio, which the presentation reconciles with what plays (F08 §7.6). ``landing``
        (F14): a rollback landing (back, or a forward chain's last), whose menu command
        ``fix_menu`` locks before it is held (04 §5.2, 07 I-7); a load's never is."""
        self._hold(AudioRestore(state.audio, "restore"))
        self._hold(NvlPage(state.nvl.on, state.nvl.page))  # F17: always, even in ADV
        self._hold(ShowStage(state.stage, restored=True))
        if state.glitch.on:                                 # F28 (04 §4.2, §6.3)
            self._hold(Glitch(state.glitch, restored=True))
        fourthwall_mod.hold_restored(self, state.window_title,     # F30 (04 §6.1): the
                                     snapshot.window_title)        # title_ok'd one, committed
        ui_mod.hold_restored(self, snapshot.ui)             # F32 (07 I-1): W205's, committed
        if attached is None:                                # F08 I-1: the line's voice
            attached = audio_mod.voice_attached(cmd)
        for extra in attached:                              # F07: present_menu's
            self._hold(extra)
        if landing and type(pos) is Menu:                   # F14 (§7.5, 07 I-7)
            cmd = rollback_mod.fix_menu(self, pos, cmd)  # type: ignore[arg-type]
        self._hold(cmd)
        self._settle(pos, snapshot)

    def _check_position(self, state: GameState, use_hints: bool, *, fresh_menu: bool = False
                        ) -> "tuple[Statement, list[Call]] | RestoreOutcome":
        """Restore steps 1-2, shared with ``check_only``: the statement to wait at and the
        call stack, or the outcome that refuses ``state``. Changes nothing. ``fresh_menu``
        (F20): a ``Menu``'s own check is skipped; its ``waiting`` is built in step 5."""
        # 1. The identity scheme (from_json checks only its type, I-6).
        scheme = state.identity_scheme
        if type(scheme) is not int or scheme != self.program.identity_scheme:
            return RestoreOutcome(RestoreResult.SCHEME_MISMATCH)
        # 2. Positions: only existing nodes of the right type (SEC-F02-10, ADR-0006), and
        # each checkpoint type's own check (F07: a pickable key is left).
        pos = self._find(state.position, state.position_at, use_hints, checkpoint=True)
        if pos is None:
            return RestoreOutcome(RestoreResult.POSITION_NOT_FOUND)
        check = POSITION_CHECKS.get(type(pos))
        if fresh_menu and type(pos) is Menu:
            check = None
        if check is not None and not check(self, pos, state):
            return RestoreOutcome(RestoreResult.POSITION_NOT_FOUND)
        call_stack: list[Call] = []
        for sid, hint in state.call_stack:
            call = self._find(sid, hint, use_hints, checkpoint=False)
            if call is None:
                return RestoreOutcome(RestoreResult.POSITION_NOT_FOUND)
            call_stack.append(call)  # type: ignore[arg-type]
        return pos, call_stack

    def note_restore_warning(self, warning: ScriptWarning) -> None:
        """F05 W46: a warning found while the restore presents its line; logged (WARNING,
        ``runtime``) only if the restore commits, after the commit's own warnings."""
        self._restore_warnings.append(warning)

    # --- Text (F05 §7.3; C2 (c)) -------------------------------------------------------

    def body_for(self, stmt: nodes.Say) -> TaggedText:
        """The parsed body the Say executor and presenter resolve: ``stmt.body``. F43
        replaces it (the translated line's body)."""
        return stmt.body

    def _find(self, sid: str, hint: object, use_hints: bool, *,
              checkpoint: bool) -> Statement | None:
        """The statement ``sid`` names, if it is a checkpoint type (``checkpoint``) or a
        ``Call``; with ``use_hints``, a missing sid may be found at its saved location under
        the same type rule. Saved data only selects existing nodes."""
        program = self.program
        stmt = program.get(sid)
        if stmt is None and use_hints and type(hint) is tuple and len(hint) == 2:
            stmt = program.at(hint[0], hint[1])
        if stmt is None:
            return None
        ok = type(stmt) in CHECKPOINT_TYPES if checkpoint else type(stmt) is Call
        return stmt if ok else None

    def _fill_defaults(self) -> StoryError | None:
        """Restore step 5: each default whose name ``G`` lacks, in order (the new-game
        loop, present names skipped). The first failure (E85 family with the default
        prefix, E85m when the watchdog fired) is returned; a real Ctrl+C is re-raised."""
        G = self.G
        for default in self.program.defaults:
            if default.name in G:
                continue
            try:
                self.running.set(default.file.ref, default.value)
                G[default.name] = freeze(self._eval(default.value.code))
            except KeyboardInterrupt as e:
                if not self.guard.consume_fired():
                    raise
                return timeout_error(default, e, prefix=default, program=self.program)
            except BaseException as e:
                return self._map(e, default, prefix=default)
        return None

    def _log_dropped(self, dropped: list[str]) -> None:
        """The define-drop WARNING (restore step 3): one line for the define names, one for
        names the engine reserved since the save (F22 07 I-9), one for statement words
        reserved since (F14 07 I-1)."""
        define_names = self.program.define_names
        defines = [n for n in dropped if n in define_names]
        reserved = [n for n in dropped if n not in define_names and n in ENGINE_NAMES]
        words = [n for n in dropped if n not in define_names and n not in ENGINE_NAMES]
        for names, what in ((defines, "a define"), (reserved, "a name the engine uses"),
                            (words, "a reserved word")):
            if names:
                self.log.warning("Restored state: %s %s %s in this version of the game, so the "
                                 "saved value was dropped.", ", ".join(f'"{n}"' for n in names),
                                 "is" if len(names) == 1 else "are", what)

    def _roll_back(self, saved_vars: dict[str, object], dice: int, ready: bool,
                   points: PointsState, items: ItemsState) -> None:
        """Undo restore step 4: ``G``'s story variables, the dice, (F22) the meters, and (F21)
        the held items as they were (the same objects). Changes a failing default made through objects held by
        defines stay (trusted author code, §7.5)."""
        G = self.G
        for key in [k for k in G if k not in self.reserved]:
            del G[key]
        G.update(saved_vars)
        self.core.state = dice
        self.core.ready = ready
        self.points.install(points)                         # F22
        self.codex.install(items)                           # F21

    def _freeze_variables(self, stmt: Statement) -> dict[str, object]:
        reserved = self.reserved
        out: dict[str, object] = {}
        for k, v in self.G.items():
            if k in reserved or k.startswith("_"):
                continue
            try:
                out[k] = freeze(v)
            except Unsaveable as e:
                raise self._unsaveable(k, e, stmt) from None
        return out

    def _unsaveable(self, name: str, exc: Unsaveable, stmt: Statement) -> StoryError:
        """E85e at the newest ``$`` line or default that names the variable, else at the
        checkpoint's line (§7.4 attribution)."""
        message = unsaveable_message(name, exc)
        for owner in reversed(self.recent_py):
            piece = owner.py if isinstance(owner, PythonLine) else owner.value
            if piece.code is not None and name in piece.code.co_names:
                return StoryError(message, code="E85e", **where(owner, piece.line))
        return StoryError(message, code="E85e", **where(stmt))

    # --- Limits (§7.2, SR-F03-26, SR-F03-27) -------------------------------------------

    def _runaway(self, stmt: Statement, line: int | None = None) -> StoryError:
        """E45 at ``stmt``: ``STEP_LIMIT`` steps without a line. Names the labels entered
        during the last ``LABEL_RING`` steps, up to 3, most often first, ties in reading
        order; with none (only under a patched limit), the label of ``stmt``."""
        since = self.steps - LABEL_RING
        counts = Counter(label for at, label in self.entered if at > since)
        if not counts:
            counts[stmt.label] = 1
        order = {name: i for i, name in enumerate(self.program.labels)}
        top = sorted(counts, key=lambda n: (-counts[n], order.get(n, len(order))))
        shown = tuple(top[:3])
        return StoryError(format_message("E45", (limits.STEP_LIMIT, shown,
                                                 len(top) - len(shown))),
                          code="E45", **where(stmt, line))

    def _too_deep(self, stmt: Statement) -> StoryError:
        """E45b at the ``call`` ``stmt``: ``CALL_DEPTH_MAX`` calls already wait to return.
        Names the label with the most waiting calls (the first called, on a tie)."""
        counts = Counter(c.target for c in self.call_stack)
        target, count = max(counts.items(), key=lambda item: item[1])
        return StoryError(format_message("E45b", (len(self.call_stack), count, target)),
                          code="E45b", **where(stmt))


# --- The Say command (F05 I-1: one helper for the executor and the presenter) -----------

def say_command(interp: Interpreter, stmt: nodes.Say, *, restored: bool = False) -> Say:
    """The ``Say`` for ``stmt`` from the story's current values (§7.2 steps 1, 3, and
    F05's 3b). Raises ``StoryError`` E75 (the speaker isn't a character), E75h
    (``name_from`` doesn't hold text), or F05's E170/E171 (a ``{var}`` that doesn't
    resolve; on restore that value shows as "" with W46 instead). ``speaker_tag`` (F04 I-3)
    is the Character's ``image_tag`` or the define name on every character line, None for
    narration. F08 fills ``voice``; F06 ``blip`` (the speaker's ``BlipSpec``, read from its
    slot, so no author method runs; None for narration and characters without ``blip``)."""
    speaker = stmt.speaker
    if speaker is None:
        body = resolve_body(interp, stmt, None, restoring=restored)     # 3b. F05
        return Say(stmt.sid, None, None, None, stmt.attributes, stmt.text, body=body,
                   voice=stmt.voice, restored=restored)
    G = interp.G
    c = G.get(speaker, _MISSING)
    if not isinstance(c, Character):
        kind = "no value" if c is _MISSING else kind_words(c)
        text = c if type(c) is str else None
        raise StoryError(format_message("E75", (speaker, kind, text)), code="E75",
                         **where(stmt))
    name = c.name
    if c.name_from is not None:
        v = G.get(c.name_from, _MISSING)
        if type(v) is not str:
            args: tuple = (speaker, c.name_from)
            if v is not _MISSING:
                plain = v is None or type(v) in (bool, int, float)
                args += (kind_words(v), short_value(v) if plain else "")
            raise StoryError(format_message("E75h", args), code="E75h", **where(stmt))
        name = v
    body = resolve_body(interp, stmt, c, restoring=restored)            # 3b. F05
    return Say(stmt.sid, speaker, name, c.color, stmt.attributes, stmt.text, body=body,
               voice=stmt.voice, speaker_tag=stage_mod.speaker_tag(c, speaker),
               restored=restored, blip=c.blip)                  # F06 I-7: the slot


# --- Executors (§6.1, §7.2) -------------------------------------------------------------

def _run_say(interp: Interpreter, stmt: nodes.Say) -> Step:
    cmd = say_command(interp, stmt)                         # 1. and 3. (E75, E75h)
    if stmt.speaker is not None:                            # 2. F04: dialogue words
        stage_mod.apply_dialogue_words(interp, stmt, interp.G[stmt.speaker])
    interp.take_checkpoint(stmt, cmd, attached=audio_mod.voice_attached(cmd))   # F08 I-1
    interp.kept_line = stmt.sid                             # F07 (04 §7.2)
    return Step.WAIT


def _present_say(interp: Interpreter, stmt: nodes.Say, state: GameState) -> Command:
    """Restore (step 9): the line again, from the restored values (F05: ``{var}`` from the
    restored variables, ``restoring=True``)."""
    return say_command(interp, stmt, restored=True)


def _run_python(interp: Interpreter, stmt: PythonLine) -> Step:
    interp.recent_py.append(stmt)
    interp.running.set(stmt.file.ref, stmt.py)
    interp._exec(stmt.py.code)
    return Step.CONTINUE


def _run_if(interp: Interpreter, stmt: If) -> Step:
    """One step per condition tested, and one for ``else`` taken (§6.1); ``run`` counted
    the first."""
    first = True
    for branch in stmt.branches:
        if first:
            first = False
        else:
            interp._step(stmt)
        if branch.condition is not None:
            interp.running.set(stmt.file.ref, branch.condition)
            if not interp._test(branch.condition.code):
                continue
        if branch.block:
            interp.current = branch.block[0]
            return Step.JUMPED
        return Step.CONTINUE
    return Step.CONTINUE


def _run_jump(interp: Interpreter, stmt: Jump) -> Step:
    interp._enter(stmt.target)
    return Step.JUMPED


def _run_call(interp: Interpreter, stmt: Call) -> Step:
    if len(interp.call_stack) >= limits.CALL_DEPTH_MAX:
        raise interp._too_deep(stmt)
    interp.call_stack.append(stmt)
    interp._enter(stmt.target)
    return Step.JUMPED


def _run_return(interp: Interpreter, stmt: Return) -> Step:
    interp._return()
    return Step.JUMPED


register_executor(nodes.Say, _run_say, present=_present_say)
register_executor(PythonLine, _run_python)
register_executor(If, _run_if)
register_executor(Jump, _run_jump)
register_executor(Call, _run_call)
register_executor(Return, _run_return)
# F04: the stage statements (runtime/stage.py; registered here, see the module docstring).
register_executor(Scene, stage_mod.run_scene)
register_executor(Show, stage_mod.run_show)
register_executor(Hide, stage_mod.run_hide)
# F08: the audio statements (runtime/audio.py; registered here, as the stage's).
register_executor(PlayAudio, audio_mod.run_play)
register_executor(QueueMusic, audio_mod.run_queue)
register_executor(StopAudio, audio_mod.run_stop)
register_executor(Voice, audio_mod.run_voice)
# F09: shake, flash, pause (runtime/effects.py; registered here, as the stage's). None is a
# checkpoint type.
register_executor(effect_nodes.Shake, effects_mod.run_shake)
register_executor(effect_nodes.Flash, effects_mod.run_flash)
register_executor(effect_nodes.Pause, effects_mod.run_pause)
# F07: the menu (runtime/menu.py; registered here, as the stage's). A checkpoint type (C1).
register_executor(Menu, menu_mod.run_menu, present=menu_mod.present_menu,
                  check=menu_mod.check_position)
# F18: chapter (runtime/chapters.py), registered once here, at import (F19 07 I-1). Not a
# checkpoint type: its card is three F09 waits chained with ``then``.
register_executor(nodes.Chapter, chapters_mod.run_chapter)
# F22: points <name> +=|-=|= <amount> (runtime/points.py). Not a checkpoint type.
register_executor(PointsChange, points_mod.run_points)
# F14 (04 §6.3): rollback block|off|on|fixed.
register_executor(Rollback, rollback_mod.run_rollback)
# F17 (04 §7.1): nvl on|off|clear (runtime/nvl.py). Not a checkpoint type.
register_executor(Nvl, nvl_mod.run_nvl)
# F19: ending and lock/unlock (runtime/endings.py), registered once here, at import (07 I-1).
# Neither is a checkpoint type (07 I-12).
register_executor(Ending, endings_mod.run_ending)
register_executor(Lock, endings_mod.run_lock)
# F21: lock/unlock tip|item (runtime/codex.py), beside F19's, once, at import (07 I-4). Not a
# checkpoint type.
register_executor(CodexLock, codex_mod.run_codex_lock)
# F23: minigame (runtime/minigame.py), a checkpoint type like the menu (04 §4.2, 07 I-6).
register_executor(Minigame, minigame_mod.run_minigame, present=minigame_mod.present_minigame,
                  check=minigame_mod.minigame_position_ok)
# F20 (04 §6.3): flowchart lines (runtime/flowchart.py), once, at import. Not a checkpoint
# type; scene, mark, and omit lines do nothing; forget forgets (no graph: nothing, 07 I-13).
register_executor(Flowchart, flowchart_mod.run_flowchart)
# F28 (04 §5.2): effect (runtime/glitch.py), once, at import. Not a checkpoint type.
register_executor(Effect, glitch_mod.run_effect)

# F30 (04 §5.4): ``effect window_title`` and ``effect crash`` (runtime/fourthwall.py). Neither is
# a checkpoint type; a crash is a story wait.
register_executor(TitleEffect, fourthwall_mod.run_title)
register_executor(CrashEffect, fourthwall_mod.run_crash)
# F32 (04 §5.2): ``ui`` lines (runtime/ui.py). Not a checkpoint type; each line is one step.
register_executor(UiStatement, ui_mod.run_ui)
# F31 (04 §5.4): ``file`` lines (runtime/metafiles.py). Not a checkpoint type; a write or
# delete sets the wall at the next checkpoint.
register_executor(MetaFile, metafiles_mod.run_file)


# --- Event handlers -----------------------------------------------------------------------

def _on_advance(interp: Interpreter, event: Advance) -> None:
    """Advance(sid): if WAITING at a line (F07 C2: only a ``Say``, never a menu) and ``sid``
    is the waiting line → RUNNING at its successor; else ignored (stale or duplicate). F08
    (§6.3 insertion 2) holds ``EndVoice`` for a voiced line; it is released with the next
    burst."""
    current = interp.current
    if (interp.status is not Status.WAITING or interp.waiting_for is not None
            or type(current) is not nodes.Say or event.sid != current.sid):
        return                                              # F09: ignored during a wait
    audio_mod.end_voice(interp, current)
    interp.persistent.mark_seen(current.sid)                # F12 (04 §7.3): a seen line
    interp.status = Status.RUNNING
    try:
        interp._next_after(current)                         # block ends crossed are steps
    except StoryError as e:                                 # E45 (only under a patched limit)
        interp._fail(e)


def _on_wait_done(interp: Interpreter, event: WaitDone) -> None:
    """F09 (04 §6.2 item 2): WaitDone(id) ends the current wait if ``id`` is its id
    (``finish_wait``); a stale, early, or duplicate one is ignored."""
    if (interp.status is Status.WAITING and interp.waiting_for is not None
            and event.wait_id == interp.waiting_for):
        interp.finish_wait()


register_event(Advance, _on_advance)
register_event(Choose, menu_mod.on_choose)                  # F07 (04 §7.4)
register_event(WaitDone, _on_wait_done)                     # F09
register_event(StepBack, rollback_mod.on_step_back)         # F14 (04 §7.3)
register_event(StepForward, rollback_mod.on_step_forward)   # F14 (04 §7.4)
register_event(MinigameDone, minigame_mod.on_minigame_done)  # F23 (04 §5.4)
register_event(MinigameUsed, minigame_mod.on_minigame_used)  # F23 (04 §7.5)


def story_variables(G: dict, reserved: Iterable[str]) -> dict[str, object]:
    """The story variables of ``G`` (not reserved, not ``_``-prefixed), for tests and
    tools."""
    reserved = frozenset(reserved)
    return {k: v for k, v in G.items() if k not in reserved and not k.startswith("_")}


__all__ = ["CHECKPOINT_TYPES", "DeferredStep", "EVENT_HANDLERS", "EXECUTORS", "Executor",
           "Interpreter", "POSITION_CHECKS", "PRESENTERS", "PositionCheck", "Presenter",
           "RestoreOutcome",
           "RestoreResult", "Status", "Step", "register_event", "register_executor",
           "say_command", "story_variables"]

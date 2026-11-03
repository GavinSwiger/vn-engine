"""The headless runner (F03 ``04-technical.md`` §5.4; PR-F03-28).

Why this module exists: tests, tools, and the determinism check play a story to its end
with no window, no clock, and no guard, through the same interpreter and executors as the
game. It takes a loaded ``Program``; it never opens a file.

F07 (its ``04-technical.md`` §5.4, PR-F07-22): at a menu the next input must be
``choose N`` (1-based among the pickable choices); when the inputs run out at a menu the run
ends normally (its last command is the ``ShowMenu``). An input that can't be used raises
``HeadlessInputError``, never another exception.

F12 (PR-F12-24): the run uses an in-memory ``PersistentStore``, never a file: the one given
(tests fill it, and see what the run left in it), else an empty one.

F09 (its ``04`` §6.2 item 4, C3; 07 I-3): a wait that isn't a checkpoint (``with``,
``pause``) is ended at once with ``WaitDone`` (``Interpreter.finish_wait``'s path), and uses
no input: inputs address only lines and choices. A story that waits ``WAIT_LIMIT`` times in
a row with no line or choice between (``label l:`` / ``pause 0.1`` / ``jump l``) would run
forever here, so the run stops with ``HeadlessWaitError`` naming the last wait.

F14 (its ``04`` §12; PR-F14-24, I-12, I-15): at a line or a menu the input may be ``back`` or
``back N`` (``StepBack``), and ``forward`` or ``forward N`` (``StepForward``: a quiet re-run,
run to its landing while the interpreter is ``busy``), N from 1 to 1,000 written without a
sign or leading zero. A step that can't move, or moves fewer than N steps, isn't an error, as
in the window. ``rollback_steps`` is ``[rollback] steps``.

F23 (its ``02`` §2.2, §4.2; ``04`` §5.4, §7.7; 07 I-12): ``minigames`` are the plugin
signatures (a caller that runs plugins loads them before the run, ``load_plugins``, and passes
``.signatures()`` here and to ``LoadOptions``); no plugin is started, updated, or drawn. At a
minigame the next input is looked at: ``finish <literal>[; change …]`` is consumed and
posted as its ``MinigameDone`` (parsed as data, never run: ``parse_finish``); ``back [N]`` is
consumed as at a menu; ``forward [N]`` is consumed and does nothing. Anything else, or no
input left, is not consumed: the plugin's ``outcome_for("test", …)`` (API 1.1, one guard
entry), else its test outcome, else ``HeadlessInputError`` E279 (``code == "E279"``). So a
minigame never shifts an input list. ``finish`` where no minigame waits is an error.

F20 (its ``04`` §7.6 "Headless"; 07 §3.5 G2; SEC-F20-13): ``flow`` is the ``FlowStates``
holder shared across runs like ``persistent`` (None: a fresh one for this run). The
recorder keeps its node states there and lists each arrival in ``reached`` and ``taken``. At
a line or a menu the input may be ``jump <node id>``: the id is length-checked
(``JUMP_ID_MAX``) first, then looked up by exact string in the graph's ``by_id`` (no
normalisation, never evaluated, no file name built), and the held state is restored with
``fresh_menu=True``, again with ``use_hints`` on POSITION_NOT_FOUND (the nearest point
accepted, as F11's confirm). No id, an unknown id, no state, or a refused state is a
``HeadlessInputError`` whose text passes ``echo()``. A jump releases what the windowed jump's
restore does (TR-F20-06) and reaches no node (PR-F20-07).

F32 (its ``04`` §2.2; 07 G1): a ``DeleteSaves`` (``ui delete saves``) deletes nothing here; each
one logs ``runtime.ui.DELETE_PREVIEW_TEXT`` once at INFO (the run's ``runtime`` logger).

F31 (its ``04`` §6.6, AC-F31-11, AC-F31-16): ``files`` is the run's meta files folder (a
``MemoryFolder``; None: a fresh empty one), never the disk. At a line or a menu the input may be
``player deletes <name>`` or ``player restores <name>`` (a ``META_NAME_RE`` name): it counts as
an input, doesn't advance, and changes the folder at once (a restore copies the original, or
``b""``). A name no ``file`` line uses is a ``HeadlessInputError`` (``H-input`` form
``meta_name``); any other text after ``player`` is H-input's usual form.

F36 (its ``04`` §7.3; PR-F36-04): a declared scene unlocks in ``persistent`` the first time the
run enters its label, as in the window. ``replay`` plays a scene replay instead of a new game:
a ``ReplayRun``, or a label (``replay.run_for``: a ``lock replay`` of it gives its ``to`` and
starting values). The store is sandboxed from the start; whatever way the run stops (the
replay's end, a failure, the inputs running out, ``max_lines``, an input error), the store is
put back before it returns, as the window's quit does.
"""

import re
import tokenize
from collections.abc import Iterable, Mapping
from types import MappingProxyType

from engine.core.errors import UserFacingError
from engine.core.minigame_types import CodexChange, MeterChange, MinigameSig, Outcome
from engine.core.paths import META_NAME_RE
from engine.core.startvalues import StartOptions, parse_literal
from engine.runtime import flowchart as flowchart_mod
from engine.runtime import minigame as minigame_mod
from engine.runtime.commands import (Advance, Choose, Command, DeleteSaves, Event, MinigameDone,
                                     StepBack, StepForward, StoryFailed, WaitDone)
from engine.runtime.errors import StoryError
from engine.runtime.flowchart import FlowStates
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter, RestoreResult, Status
from engine.runtime.launch import run_launch
from engine.runtime.metafiles import MemoryFolder, MetaFiles, attach
from engine.runtime.persistent import PersistentStore
from engine.runtime.points import UnknownMeter
from engine.runtime import replay as replay_mod
from engine.runtime.replay import ReplayRun
from engine.runtime.rollback import DEFAULT_DEPTH, DEPTH_MAX
from engine.runtime.ui import DELETE_PREVIEW_TEXT
from engine.runtime.values import freeze
from engine.script.diagnostics import ScriptErrorGroup
from engine.script.menu import Menu
from engine.script.minigame import Minigame
from engine.script.messages import format_message
from engine.script.program import Program

RUN_STEPS = 10_000
WAIT_LIMIT = 10_000                 # waits in a row with no line or choice (F09 07 I-3)
_ALL = 1 << 62
_CHOOSE_RE = re.compile(r"choose ([1-9][0-9]{0,2})")
_STEP_RE = re.compile(r"(back|forward)(?: ([1-9][0-9]{0,3}))?")   # F14: N checked ≤ 1,000
# F23 (04 §7.7): the finish input and its changes (ASCII only: no other digits or names;
# spaces and tabs only between the words, so a newline is never part of a change).
FINISH_MAX_CHARS = 10_000
FINISH_CHANGES_MAX = 100
_FINISH_RE = re.compile(r"finish(?:[ \t]+(.*))?", re.ASCII | re.DOTALL)
_NAME = r"([A-Za-z_][A-Za-z0-9_]{0,63})"
_POINTS_RE = re.compile(r"points[ \t]+" + _NAME + r"[ \t]*(\+=|-=|=)[ \t]*(-?\d{1,10})",
                        re.ASCII)
_UNLOCK_RE = re.compile(r"unlock[ \t]+(tip|item)[ \t]+" + _NAME, re.ASCII)
_LOCK_RE = re.compile(r"lock[ \t]+item[ \t]+" + _NAME, re.ASCII)
# F20 (04 §7.6, SEC-F20-13): ``jump <node id>``; the id is any text, length-checked first.
JUMP_ID_MAX = 1_200
_JUMP_RE = re.compile(r"jump(?: (.*))?", re.DOTALL)
# F31 (04 §6.6): the player changes a meta file.
_PLAYER_RE = re.compile(r"player (deletes|restores) (" + META_NAME_RE.pattern + ")", re.ASCII)


class HeadlessInputError(UserFacingError):
    """An input ``run_headless`` can't use at the place the story waits (F07 §5.4): a
    ``choose N`` out of range or away from a menu, ``advance`` at a menu, or something that
    is neither. ``commands`` are the commands released before that input."""

    def __init__(self, message: str, commands: list[Command], *,
                 code: str | None = None) -> None:
        super().__init__(message)
        self.commands = commands
        self.code = code                    # F23: "E279"; None for the uncoded F07 forms


class HeadlessWaitError(UserFacingError):
    """F09 07 I-3: ``WAIT_LIMIT`` waits in a row with no line or choice between them (a
    loop of pauses or transitions, which only a player can leave). Headless runs only; the
    message names the last wait. ``commands`` are the commands released so far."""

    def __init__(self, message: str, commands: list[Command]) -> None:
        super().__init__(message)
        self.commands = commands


def run_headless(program: Program, *, seed: int, inputs: Iterable[str] = (),
                 image_files: Iterable[str] = (), max_lines: int = 100_000,
                 start: StartOptions | None = None, dev: bool = False,
                 show_locked: bool = False,
                 persistent: PersistentStore | None = None,
                 rollback_steps: int = DEFAULT_DEPTH,
                 minigames: Mapping[str, MinigameSig] | None = None,
                 flow: FlowStates | None = None,
                 files: MemoryFolder | None = None,
                 replay: ReplayRun | str | None = None) -> list[Command]:
    """Launch (launch errors → one ``StoryFailed`` holding a ``ScriptErrorGroup``),
    ``new_game(seed)``, then ``run(10_000)`` in a loop. At each line the next input is used
    (``"advance"``; F07: ``"choose N"`` at a menu); once inputs run out, every line is
    advanced and the run ends at the first menu. Stops at the end, a failure, or after
    ``max_lines`` lines and choices. ``image_files`` (game-relative refs, e.g.
    ``images/hana/happy.png``)
    stand in for the game folder in F04's image scan (launch phase 4), so no directory is
    read. ``show_locked`` is ``[choice] show_locked``. Raises ``HeadlessInputError`` for an
    input that can't be used where the story waits. ``persistent`` is the session's store
    (F12; an empty in-memory one when None). F09: every wait that isn't a line or choice
    ends at once and uses no input; ``WAIT_LIMIT`` of them in a row raise
    ``HeadlessWaitError``. F14: ``back [N]``/``forward [N]`` at a line or menu;
    ``rollback_steps`` is ``[rollback] steps`` (0 to 1,000). F23: ``minigames`` are the
    plugins' signatures (None: none); see the module docstring for the inputs at a
    minigame. F20: ``flow`` is the node-state holder (None: a fresh one); ``jump <id>`` at a
    line or menu (module docstring). F31: ``files`` is the meta files folder (None: a fresh
    empty one); ``player deletes|restores <name>`` at a line or menu (module docstring).
    F36: ``replay`` (module docstring)."""
    if persistent is None:
        persistent = PersistentStore(identity_scheme=program.identity_scheme)
    launch = run_launch(program, dev=dev, images=ImageSource.from_files(image_files),
                        persistent=persistent)
    if launch.namespace is None:
        return [StoryFailed(ScriptErrorGroup(launch.errors, launch.error_count))]
    interp = Interpreter(program, launch.namespace, dev=dev, start=start,
                         show_locked=show_locked, persistent=persistent,
                         rollback_steps=rollback_steps,
                         minigames=MappingProxyType({}) if minigames is None else minigames)
    flowchart_mod.register(interp, states=FlowStates() if flow is None else flow)   # F20
    folder = MemoryFolder() if files is None else files                             # F31
    attach(interp, MetaFiles(folder))
    run = replay_mod.run_for(program, replay) if type(replay) is str else replay   # F36
    interp.new_game(seed, replay=run)
    try:
        return _play(interp, folder, inputs, max_lines)
    finally:
        if run is not None:                 # F36: a run stopping mid-replay quits it
            replay_mod.leave(interp)


def _play(interp: Interpreter, folder: MemoryFolder, inputs: Iterable[str],
          max_lines: int) -> list[Command]:
    """``run_headless``'s loop, from the new game to the end, a failure, the inputs running
    out at a menu, or ``max_lines``."""
    commands: list[Command] = []
    pending = _Inputs(inputs)
    number = 0
    lines = 0
    waits = 0
    while True:
        if interp.busy:                                     # F14: a forward chain too
            interp.run(RUN_STEPS)
        _take(interp, commands)
        if interp.busy:
            continue
        if interp.status is Status.WAITING and interp.waiting_for is not None:
            waits += 1                                      # F09: a wait ends at once
            if waits >= WAIT_LIMIT:
                at = interp.current
                raise HeadlessWaitError(format_message("H-waits", (
                    WAIT_LIMIT, at.file.ref, at.line)), list(commands))  # type: ignore[union-attr]
            interp.post(WaitDone(interp.waiting_for))
        elif interp.status is Status.WAITING:
            waits = 0
            lines += 1
            if lines >= max_lines:
                break
            current = interp.current
            if type(current) is Minigame:                   # F23 (04 §5.4)
                number = _at_minigame(interp, current, pending, number, commands)
                continue
            at_menu = type(current) is Menu
            answer = pending.next()
            if answer is None:
                if at_menu:
                    break                                   # inputs ran out at a menu
                answer = "advance"
            else:
                number += 1
                if type(answer) is str and _JUMP_RE.fullmatch(answer) is not None:
                    _jump(interp, answer, number, commands)  # F20 (04 §7.6)
                    continue
                player = _PLAYER_RE.fullmatch(answer) if type(answer) is str else None
                if player is not None:                      # F31 (04 §6.6)
                    _player(interp, folder, player, number, commands)
                    continue
            interp.post(_event(interp, current, at_menu, answer, number, commands))
        else:
            break
    _take(interp, commands)
    return commands


def _take(interp: Interpreter, commands: list[Command]) -> None:
    """The released commands onto ``commands``; F32: a ``DeleteSaves`` logs its INFO line."""
    taken = interp.take_commands(_ALL)
    for cmd in taken:
        if type(cmd) is DeleteSaves:
            interp.log.info("%s", DELETE_PREVIEW_TEXT)
    commands.extend(taken)


def _player(interp: Interpreter, folder: MemoryFolder, match: re.Match[str], number: int,
            commands: list[Command]) -> None:
    """F31's ``player deletes|restores <name>`` (04 §6.6): the folder changes at once; a name
    no ``file`` line uses is ``HeadlessInputError`` (H-input ``meta_name``)."""
    verb, name = match.group(1), match.group(2)
    if name not in interp.program.meta_files:
        raise HeadlessInputError(format_message("H-input", (number, match.group(0), "meta_name")),
                                 list(commands))
    if verb == "deletes":
        folder.player_deletes(name)
    else:
        folder.player_restores(name)


class _Inputs:
    """The input list, read one at a time; F23 looks at the next one before using it."""

    def __init__(self, inputs: Iterable[str]) -> None:
        self._it = iter(inputs)
        self._peeked: list[object] = []

    def peek(self) -> object:
        if not self._peeked:
            value = next(self._it, None)
            if value is None:
                return None
            self._peeked.append(value)
        return self._peeked[0]

    def next(self) -> object:
        if self._peeked:
            return self._peeked.pop()
        return next(self._it, None)


def _at_minigame(interp: Interpreter, current: Minigame, pending: _Inputs, number: int,
                 commands: list[Command]) -> int:
    """F23 (SR-F23-11): use the next input at the waiting minigame if it is ``finish``,
    ``back [N]``, or ``forward [N]``; else consume nothing and post the plugin's test outcome
    (or raise E279). Returns the input count."""
    answer = pending.peek()
    if type(answer) is str:
        if _FINISH_RE.fullmatch(answer) is not None:
            pending.next()
            number += 1
            outcome = parse_finish(interp, answer, number, commands)
            interp.post(MinigameDone(current.sid, interp.minigame_run, outcome.result,
                                     outcome.changes))
            return number
        step = _STEP_RE.fullmatch(answer)
        if step is not None and (step.group(2) is None or int(step.group(2)) <= DEPTH_MAX):
            pending.next()
            number += 1
            if step.group(1) == "back":
                interp.post(StepBack(1 if step.group(2) is None else int(step.group(2))))
            return number                                   # forward: consumed, nothing
    try:
        outcome = minigame_mod.headless_outcome(interp, current)
    except StoryError as error:                             # E275 at the line
        interp._fail(error)
        return number
    if outcome is None:
        ref, line = current.file.ref, current.line
        text = f"{ref}, line {line}: " + format_message("E279", (current.name,))
        raise HeadlessInputError(text, list(commands), code="E279")
    interp.post(MinigameDone(current.sid, interp.minigame_run, outcome.result,
                             outcome.changes))
    return number


def _jump(interp: Interpreter, text: str, number: int, commands: list[Command]) -> None:
    """F20's headless jump (04 §7.6, SEC-F20-13): restore the held state of the node named
    after ``jump`` with ``fresh_menu=True`` (with hints on POSITION_NOT_FOUND), or raise
    ``HeadlessInputError``. The id is length-checked before any lookup and matched only by
    exact string; it reaches a message (``H-jump``) only through ``echo()``."""
    def fail(form: str, node_id: str = "", reason: str = "") -> HeadlessInputError:
        return HeadlessInputError(format_message("H-jump", (form, number, node_id, reason,
                                                            JUMP_ID_MAX)), list(commands))

    node_id = text[5:]                                      # after "jump " ("" for "jump")
    if not node_id:
        raise fail("needs")
    if len(node_id) > JUMP_ID_MAX:
        raise fail("long")
    graph = interp.flowchart.graph
    if graph is None or graph.by_id.get(node_id) is None:
        raise fail("unknown", node_id)
    state = interp.flowchart.state(node_id)
    if state is None:
        raise fail("no_state", node_id)
    outcome = interp.restore(state, fresh_menu=True)
    if outcome.result is RestoreResult.POSITION_NOT_FOUND:
        outcome = interp.restore(state, use_hints=True, fresh_menu=True)
    if outcome.result is not RestoreResult.OK:
        reason = outcome.result.value
        if outcome.error is not None and outcome.error.code:
            reason += f" ({outcome.error.code})"
        raise fail("refused", node_id, reason)


def parse_finish(interp: Interpreter, text: str, number: int,
                 commands: list[Command]) -> Outcome:
    """``finish <literal>[; change …]`` as an ``Outcome`` (04 §7.7, SEC-F23-12): total, never
    evaluated; every mistake is a ``HeadlessInputError`` with 02 §4.2's text."""
    def fail(form: str, *args: object) -> HeadlessInputError:
        return HeadlessInputError(format_message("H-finish", (form, number, text, *args)),
                                  list(commands))

    if len(text) > FINISH_MAX_CHARS:                        # 1.
        raise fail("long")
    match = _FINISH_RE.fullmatch(text)
    body = match.group(1) if match is not None else None
    if body is None or not body.strip(" \t"):
        raise fail("needs")
    try:
        parts = _split_parts(body)                          # 2.
    except Exception:                                       # noqa: BLE001 (total, 04 §7.7)
        raise fail("value") from None
    if parts is None:
        raise fail("many")
    try:
        result = freeze(parse_literal(parts[0]))            # 3. (never evaluated)
    except Exception:                                       # noqa: BLE001 (total, 04 §7.7)
        raise fail("value") from None
    changes: list[MeterChange | CodexChange] = []
    for part in parts[1:]:                                  # 4.-5.
        change = _change(part.strip(" "))
        if change is None:
            raise fail("change")
        problem = _name_problem(interp, change)
        if problem is not None:
            raise fail("name", problem)
        changes.append(change)
    return Outcome(result, tuple(changes))


def _split_parts(body: str) -> list[str] | None:
    """``body`` cut at its top-level ``;`` (strings and brackets whole, ``tokenize``); None
    past ``FINISH_CHANGES_MAX`` changes. Raises ``tokenize``'s errors."""
    rows = body.split("\n")                 # the rows as fed to tokenize, so offsets match
    starts = [0]
    for text_line in rows[:-1]:
        starts.append(starts[-1] + len(text_line) + 1)
    cuts: list[int] = []
    depth = 0
    lines = iter([row + "\n" for row in rows[:-1]] + [rows[-1]])
    for tok in tokenize.generate_tokens(lambda: next(lines, "")):
        if tok.type != tokenize.OP:
            continue
        if tok.string in ("(", "[", "{"):
            depth += 1
        elif tok.string in (")", "]", "}"):
            depth -= 1
        elif tok.string == ";" and depth == 0:
            row, col = tok.start
            cuts.append(starts[row - 1] + col)
            if len(cuts) > FINISH_CHANGES_MAX:
                return None
    parts, at = [], 0
    for cut in cuts:
        parts.append(body[at:cut])
        at = cut + 1
    parts.append(body[at:])
    return parts


def _change(part: str) -> MeterChange | CodexChange | None:
    """One change (04 §7.7 step 4), or None: ASCII names and digits, |amount| ≤ 10**9."""
    found = _POINTS_RE.fullmatch(part)
    if found is not None:
        amount = int(found.group(3))
        if abs(amount) > minigame_mod.AMOUNT_MAX:
            return None
        return MeterChange(found.group(1), found.group(2), amount)  # type: ignore[arg-type]
    found = _UNLOCK_RE.fullmatch(part)
    if found is not None:
        verb = "unlock_tip" if found.group(1) == "tip" else "give"
        return CodexChange(verb, found.group(2))            # type: ignore[arg-type]
    found = _LOCK_RE.fullmatch(part)
    if found is not None:
        return CodexChange("take", found.group(1))
    return None


def _name_problem(interp: Interpreter, change: MeterChange | CodexChange) -> str | None:
    """F22's or F21's own text for a name the story doesn't declare (step 5), or None."""
    if type(change) is MeterChange:
        try:
            interp.points.spec(change.name)
        except UnknownMeter as e:
            return str(e)
        return None
    kind = "tip" if change.verb == "unlock_tip" else "item"
    index = interp.codex.index
    entry = index.get(change.name)
    if entry is None:
        return format_message("E253", ("unknown", kind, change.name,
                                       index.suggest(change.name, kind)))
    if entry.kind != kind:
        word = "lock" if change.verb == "take" else "unlock"
        return format_message("E253", ("kind", change.name, entry.kind, kind, word))
    return None


def _event(interp: Interpreter, current, at_menu: bool, answer: object, number: int,
           commands: list[Command]) -> Event:
    """The event for one input at the waiting statement, or ``HeadlessInputError``."""
    ref, line = current.file.ref, current.line
    if type(answer) is str and _FINISH_RE.fullmatch(answer) is not None:   # F23 (02 §4.2)
        where = "menu" if at_menu else "line"
        raise HeadlessInputError(format_message("H-finish", ("elsewhere", number, answer,
                                                             where, ref, line)),
                                 list(commands))
    if answer == "advance" and type(answer) is str:
        if at_menu:
            raise HeadlessInputError(format_message("H-advance-menu", (ref, line)),
                                     list(commands))
        return Advance(current.sid)
    step = _STEP_RE.fullmatch(answer) if type(answer) is str else None
    if step is not None:                                    # F14
        n = 1 if step.group(2) is None else int(step.group(2))
        if n <= DEPTH_MAX:
            return StepBack(n) if step.group(1) == "back" else StepForward(n)
    match = _CHOOSE_RE.fullmatch(answer) if type(answer) is str else None
    if match is None:
        text = answer if type(answer) is str else repr(answer)
        raise HeadlessInputError(format_message("H-input", (number, text)), list(commands))
    n = int(match.group(1))
    if not at_menu:
        raise HeadlessInputError(format_message("H-choose-line", (n, ref, line)),
                                 list(commands))
    pickable = interp.choices.waiting.pickable  # type: ignore[union-attr]
    if n > len(pickable):
        raise HeadlessInputError(format_message("H-choose-range", (n, ref, line,
                                                                   len(pickable))),
                                 list(commands))
    return Choose(current.sid, pickable[n - 1])


__all__ = ["FINISH_CHANGES_MAX", "FINISH_MAX_CHARS", "FlowStates", "HeadlessInputError",
           "HeadlessWaitError", "JUMP_ID_MAX", "WAIT_LIMIT", "parse_finish", "run_headless"]

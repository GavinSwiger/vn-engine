"""F03 step 9 — the checkpoint routine and snapshots (``04-technical.md`` §7.4, §7.5 step 7;
TR-F03-03, TR-F03-11; I-4, I-9). ACs: AC-F03-57 and AC-F03-84.

AC-84's test statement (the unbuilt word ``window``; it was ``pause`` until F09 built that
statement) is registered for the test only: the parser spec through
``scoped_registry`` and the executor and presenter through ``monkeypatch.setitem`` on the
interpreter's tables (``CHECKPOINT_TYPES`` is the live key view of ``PRESENTERS``).
"""

import dataclasses
import json
from dataclasses import dataclass

import pytest

from engine.app.dispatch import CommandRouter
from engine.runtime import interpreter as interp_mod
from engine.runtime.audio import EMPTY_AUDIO
from engine.runtime.commands import (Advance, AudioRestore, ChapterStarted, CodexAdded,
                                     Command, Event, FakeCrash, Flash, Glitch, MetaDelete, MetaWrite, NvlPage, PlayVoice, PrefetchImages, Say, Shake, ShowMenu,
                                     ShowStage, StartMinigame, StoryEnded, StoryFailed,
                                     StoryWait, UiBlocks, UiStyle, WindowTitle)
from engine.runtime.interpreter import (CHECKPOINT_TYPES, RestoreResult, Status, Step,
                                        register_executor)
from engine.runtime.state import GameState
from engine.script import nodes
from engine.script.lexer import TAIL_SCRIPT
from engine.script.menu import Menu
from engine.script.minigame import Minigame
from engine.script.statements import StatementSpec, register, scoped_registry
from tests.runtime.conftest import round_trip
from tests.runtime.stage_story import AUDIO_COMMANDS, example_minigames, load_example, no_audio
from tests.runtime.story import (advance, checkpoints, end_waits, launched, load_r, start,
                                 texts)


def take_all(interp) -> list:
    return interp.take_commands(1 << 30)


def at_text(interp, text: str) -> GameState:
    while getattr(interp.current, "text", None) != text:
        advance(interp)
    return interp.checkpoint()


# --- AC-F03-57 — snapshots don't change afterwards (TR-F03-03) -------------------------------

AC57_S = '$ deck = [1, [2]]⏎[4]"Mid."⏎[4]$ deck[1].append(3)⏎[4]$ deck.append(4)'


def test_ac_f03_57_snapshot_is_independent_of_G(tmp_path):
    interp = start(load_r(tmp_path, S=AC57_S))
    mid = at_text(interp, "Mid.")
    end = at_text(interp, "End.")
    assert mid.variables["deck"] == [1, [2]]
    assert end.variables["deck"] == [1, [2, 3], 4]
    with pytest.raises(TypeError):
        mid.variables["deck"] = 1  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        mid.dice = 1  # type: ignore[misc]


def test_ac_f03_57_restoring_twice_gives_equal_results(tmp_path):
    interp = start(load_r(tmp_path, S=AC57_S))
    mid = at_text(interp, "Mid.")
    frozen = json.dumps(mid.to_json(), ensure_ascii=True)
    runs = []
    for _ in range(2):
        take_all(interp)
        assert interp.restore(mid).result is RestoreResult.OK
        first_checkpoint = interp.checkpoint()
        first = take_all(interp)
        interp.G["deck"][1].append(99)                     # mutating G after a restore
        interp.G["deck"].append(98)
        assert mid.variables["deck"] == [1, [2]]
        interp.G["deck"][1].pop()
        interp.G["deck"].pop()
        advance(interp)
        runs.append((first_checkpoint, first, interp.checkpoint(), take_all(interp)))
    assert runs[0] == runs[1]
    assert runs[0][0] == mid
    assert json.dumps(mid.to_json(), ensure_ascii=True) == frozen


# --- I-9 — a retained snapshot after the command dispatch of a full headless run ------------

def test_i_9_a_retained_snapshot_is_unchanged_after_a_full_run():
    result = load_example()
    assert result.program is not None
    interp = start(result.program, seed=3, minigames=example_minigames())
    router = CommandRouter()
    shown = []
    router.register(Say, shown.append)
    router.register(StoryEnded, shown.append)
    router.register(StoryFailed, shown.append)
    router.register(ShowStage, shown.append)                # F04
    router.register(PrefetchImages, shown.append)
    router.register(ShowMenu, shown.append)                 # F07 (the example has menus)
    for kind in AUDIO_COMMANDS:                             # F08 (the example plays music)
        router.register(kind, shown.append)
    for kind in (StoryWait, Shake, Flash, ChapterStarted):  # F09, F18 (transitions, cards)
        router.register(kind, shown.append)
    router.register(NvlPage, shown.append)                  # F17 (the prologue's nvl lines)
    router.register(CodexAdded, shown.append)               # F21 (the example's codex)
    router.register(StartMinigame, shown.append)            # F24-4 (the example's poem)
    for kind in (MetaWrite, MetaDelete):                    # F31 s5 (the bonus scene)
        router.register(kind, shown.append)
    router.register(Glitch, shown.append)                   # F28 s6 (the bonus scene)
    router.register(WindowTitle, shown.append)              # F30 s6 (its crash: StoryWait)
    for kind in (UiStyle, UiBlocks):                        # F32 s6 (the bonus scene)
        router.register(kind, shown.append)
    end_waits(interp)                                       # F18: the prologue's card
    retained = []
    while interp.status is Status.WAITING:
        state = interp.checkpoint()
        retained.append((state, json.dumps(state.to_json(), ensure_ascii=True)))
        for cmd in take_all(interp):
            router.dispatch(cmd)
        advance(interp)
    for cmd in take_all(interp):
        router.dispatch(cmd)
    assert interp.status is Status.ENDED and type(shown[-1]) is StoryEnded
    assert len(retained) > 5
    for state, text in retained:
        assert json.dumps(state.to_json(), ensure_ascii=True) == text


# --- TR-F03-11 — a failing burst releases nothing of itself ----------------------------------

def test_tr_f03_11_a_failing_checkpoint_releases_only_story_failed(tmp_path):
    interp = start(load_r(tmp_path, S="$ visited = set()"))
    take_all(interp)
    advance(interp)
    commands = take_all(interp)
    assert [type(c) for c in commands] == [StoryFailed]
    assert commands[0].error.code == "E85e" and interp.checkpoint() is None


# --- AC-F03-84 — one checkpoint routine for every checkpoint type ----------------------------

@dataclass(slots=True, kw_only=True)
class Pause(nodes.Statement):
    def identity_key(self) -> tuple[str, ...]:
        return ("window",)


@dataclass(frozen=True, slots=True)
class Paused(Command):
    sid: str
    restored: bool = False


def _parse_pause(raw, ctx):
    if len(raw.tokens) != 1:
        ctx.error("E32", "window")
        return None
    return Pause(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column)


def _run_pause(interp, stmt):
    interp.take_checkpoint(stmt, Paused(stmt.sid))
    return Step.WAIT


def _present_pause(interp, stmt, state):
    return Paused(stmt.sid, restored=True)


@dataclass(frozen=True, slots=True)
class Resume(Event):
    sid: str


def _on_resume(interp, event):
    """The test type's own way on: F07 C2 accepts ``Advance`` only while a ``Say`` waits, so
    a new checkpoint type brings its event (as F07's ``Choose``)."""
    current = interp.current
    if interp.status is Status.WAITING and type(current) is Pause and event.sid == current.sid:
        interp.status = Status.RUNNING
        interp._next_after(current)


def resume(interp):
    interp.post(Resume(interp.current.sid))
    interp.run(10_000)


@pytest.fixture
def pause(monkeypatch):
    with scoped_registry():
        register(StatementSpec(word="window", placement="story", takes_block=False,
                               tail=TAIL_SCRIPT, parse=_parse_pause))
        monkeypatch.setitem(interp_mod.EXECUTORS, Pause, _run_pause)
        monkeypatch.setitem(interp_mod.PRESENTERS, Pause, _present_pause)
        monkeypatch.setitem(interp_mod.EVENT_HANDLERS, Resume, _on_resume)
        assert Pause in CHECKPOINT_TYPES
        yield


def test_ac_f03_84_a_new_checkpoint_type(tmp_path, pause):
    program = load_r(tmp_path, S="window")
    interp = start(program)
    take_all(interp)
    advance(interp)
    stmt = interp.current
    assert type(stmt) is Pause
    assert take_all(interp) == [Paused(stmt.sid)]
    assert interp.status is Status.WAITING and interp.steps == 0
    state = interp.checkpoint()
    assert state.position == stmt.sid and state.position_at == ("start", (1,))
    interp.post(Advance(stmt.sid))                  # F07 C2: Advance passes only a Say
    assert take_all(interp) == [] and interp.current is stmt
    resume(interp)
    assert texts(take_all(interp)) == ["End."]
    assert interp.restore(round_trip(state)).result is RestoreResult.OK
    # F04 (07 I-1): a restore always sends the saved stage before the line; F08 the saved
    # audio before that, and F17 the saved text mode right after it.
    assert take_all(interp) == [AudioRestore(state.audio, "restore"),
                                NvlPage(False),
                                ShowStage(state.stage, restored=True),
                                Paused(stmt.sid, restored=True)]
    assert interp.status is Status.WAITING and interp.checkpoint() == state
    resume(interp)
    assert texts(take_all(interp)) == ["End."]


def test_ac_f03_84_e85e_at_the_new_type(tmp_path, pause):
    interp = start(load_r(tmp_path, S="$ visited = set()⏎[4]window"))
    take_all(interp)
    advance(interp)
    (failed,) = take_all(interp)
    assert type(failed) is StoryFailed and failed.error.code == "E85e"
    assert failed.error.format() == (
        'script/main.vns, line 8: "visited" holds a set, which can\'t be saved. Use a list '
        'instead, e.g. $ visited = [].')


def test_ac_f03_84_bursts_with_f04s_stage(tmp_path):
    """AC-F03-84's bursts once F04 step 4 is built: a line's burst is ``[ShowStage?] Say``
    (the stage only when it changed, always with the first line), and a restore burst is
    ``[ShowStage(restored), Say(restored)]`` (F04 07 I-1; the F03-only ``[Say]`` form is
    gone). F08 step 3: the first burst starts with the new game's ``AudioRestore`` and a
    restore burst with the saved audio's. The example's own audio commands (``play music``
    before the first ``scene``) run in story order, so a live burst is checked without
    them (``no_audio``, which drops a voiced line's ``PlayVoice`` too). F08 step 12: a
    restore burst holds the restored line's ``PlayVoice`` (``restored=True``) right before
    its ``Say``. F09, F18: the commands of a line's story waits (``advance`` ends them) are
    left out, and a line whose moments ended in ``with`` or a card has one ``ShowStage``
    each: the last is the line's stage. F21: the example's ``CodexAdded`` (released with the
    next line's burst, before it) are left out too."""
    result = load_example()
    interp = start(result.program, seed=5, minigames=example_minigames())
    end_waits(interp)                                       # F18: the prologue's card
    states = []
    shown = None
    first = True
    while interp.status is Status.WAITING:
        if type(interp.current) is Minigame:                # F24-4, F25-4: no line
            assert [type(c) for c in take_all(interp)
                    if type(c) is not PrefetchImages] == [StartMinigame]
            advance(interp)
            continue
        burst = [c for c in take_all(interp)
                 if type(c) not in (PrefetchImages, StoryWait, Shake, Flash, ChapterStarted,
                                    CodexAdded, MetaWrite, MetaDelete,      # F31 s5
                                    Glitch,                                 # F28 s6
                                    WindowTitle, FakeCrash,                 # F30 s6
                                    UiStyle, UiBlocks)]                     # F32 s6
        if first:
            assert burst[0] == AudioRestore(EMPTY_AUDIO, "new_game")
            first = False
        burst = no_audio(burst)
        stages = [c for c in burst if type(c) is ShowStage]
        if shown is None or interp.stage != shown:
            assert burst[:len(stages)] == stages and stages[-1].stage == interp.stage
            assert stages[-1].card is None and not stages[-1].restored
            shown = interp.stage
            burst = burst[len(stages):]
        else:
            assert all(c.transition is not None or c.card is not None for c in stages)
            burst = [c for c in burst if type(c) is not ShowStage]
        # F17: the line after an nvl on/clear/off that changed the mode or page holds that
        # NvlPage first (the example's prologue).
        if burst and type(burst[0]) is NvlPage:
            burst = burst[1:]
        # F07: at a menu (the example's, each with a question) the burst ends ShowMenu.
        menu = [ShowMenu] if burst and type(burst[-1]) is ShowMenu else []
        assert [type(c) for c in burst] == [Say, *menu] and not burst[0].restored
        say = burst[0]
        voice = [PlayVoice(say.sid, say.voice, False)] if say.voice else []
        states.append((interp.checkpoint(), menu, voice))
        advance(interp)
    fresh = launched(result.program, minigames=example_minigames())
    assert any(voice for _, _, voice in states)                  # the example's voices
    for state, menu, voice in states:
        assert fresh.restore(round_trip(state)).result is RestoreResult.OK
        burst = [c for c in take_all(fresh) if type(c) is not PrefetchImages]
        titles = [c for c in burst if type(c) is WindowTitle]                     # F30 s6
        assert all(c == WindowTitle(state.window_title) for c in titles)
        burst = [c for c in burst if type(c) is not WindowTitle]
        styles = [c for c in burst if type(c) is UiStyle]                         # F32 s6
        assert all(c.name == state.ui.style for c in styles)
        burst = [c for c in burst if type(c) not in (UiStyle, UiBlocks)]
        restored = [dataclasses.replace(c, restored=True) for c in voice]
        glitch = [Glitch(state.glitch, restored=True)] if state.glitch.on else []   # F28 s6
        assert burst[3:3 + len(glitch)] == glitch
        del burst[3:3 + len(glitch)]
        assert [type(c) for c in burst] == [AudioRestore, NvlPage, ShowStage,
                                            *map(type, voice), Say, *menu]
        assert burst[0] == AudioRestore(state.audio, "restore")                  # F08
        assert burst[1] == NvlPage(state.nvl.on, state.nvl.page)                 # F17
        assert burst[3:3 + len(voice)] == restored
        assert burst[2] == ShowStage(state.stage, restored=True)
        assert burst[3 + len(voice)].restored
    # AC-F03-84 as amended by F07 (its 07 I-10): the menu is a checkpoint type too; and by
    # F23 (04 §17.1-1): the minigame.
    assert set(CHECKPOINT_TYPES) == {nodes.Say, Menu, Minigame}
    with pytest.raises(ValueError):
        register_executor(nodes.Say, lambda i, s: Step.WAIT)


def test_restore_burst_order_attached_seam(tmp_path):
    """I-4: ``take_checkpoint``'s ``attached`` commands come before the line; a restore
    burst is the saved audio (F08), the saved text mode (F17), the saved stage (F04), and
    then the presenter's command."""
    interp = start(load_r(tmp_path))
    state = interp.checkpoint()
    take_all(interp)
    stmt = interp.current
    marker = Paused("voice")
    cmd = interp_mod.say_command(interp, stmt)
    interp.take_checkpoint(stmt, cmd, attached=(marker,))
    assert take_all(interp) == [marker, cmd]
    assert interp.restore(state).result is RestoreResult.OK
    assert take_all(interp) == [AudioRestore(state.audio, "restore"),
                                NvlPage(False),
                                ShowStage(state.stage, restored=True),
                                dataclasses.replace(cmd, restored=True)]


def test_checkpoints_of_a_story_all_restore(tmp_path):
    program = load_r(tmp_path, S='$ x = [1]⏎[4]"A."⏎[4]$ x.append(2)⏎[4]"B."')
    states = checkpoints(start(program))
    interp = launched(program)
    for state in states:
        assert interp.restore(round_trip(state)).result is RestoreResult.OK
        assert interp.checkpoint() == state
        burst = interp.take_commands(5)
        assert burst[0] == AudioRestore(state.audio, "restore")        # F08
        assert burst[1] == NvlPage(False)                              # F17
        assert burst[2] == ShowStage(state.stage, restored=True)       # F04
        assert burst[3].sid == state.position
        interp.post(Advance(state.position))

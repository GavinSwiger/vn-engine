"""F18 step 1 — chapters at run time (``runtime/chapters.py``; the ``GameState.chapter`` field,
``flush_stage(card=)``, ``ShowStage.card``, ``ChapterStarted``): AC-F18-02, 03, 05, 08, the
launch codes of a chapter's ``with`` (AC-F18-01), and the runtime part of AC-F18-06 (restore
during the card)."""

import json

import pytest

from engine.core.paths import GamePaths
from engine.runtime import persistent as persistent_mod
from engine.runtime.chapters import EMPTY_CHAPTER, ChapterState
from engine.runtime.commands import (Advance, ChapterStarted, Say, ShowStage, StoryWait,
                                     TitleCard, TransitionSpec, WaitDone)
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.stage import StageState
from engine.runtime.state import GameState, StateInvalid
from engine.script.loader import load_story
from tests.runtime.effects_story import (bursts, launch_h, launched, run_h, story_game,
                                         take_all)

AC03 = ["scene bg sea", '"L1"', "scene bg river", 'chapter c "H" "T"', '"L2"']


def advance(interp) -> None:
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)


def finish_waits(interp) -> None:
    while interp.waiting_for is not None:
        interp.post(WaitDone(interp.waiting_for))
        interp.run(10_000)


def at_line(program, **kwargs):
    """New game, run to the first line."""
    interp = launched(program, **kwargs)
    interp.new_game(42)
    interp.run(10_000)
    assert interp.status is Status.WAITING
    return interp


# --- AC-F18-02 — the index -----------------------------------------------------------------

def test_ac02_index_in_include_order_then_line(tmp_path):
    script = tmp_path / "script"
    script.mkdir()
    (script / "main.vns").write_text(
        'include "part.vns"\nlabel start:\n    "A"\n    call part\n    if True:\n'
        '        chapter festival "Chapter 2" "The Lantern Festival"\n'
        '    chapter prologue "Prologue"\n', encoding="utf-8")
    (script / "part.vns").write_text('label part:\n    chapter river "By the River"\n'
                                     "    return\n", encoding="utf-8")
    program = load_story(GamePaths(tmp_path.resolve())).program
    index = launched(program).chapters
    assert [(c.name, c.label, c.sid) for c in index] == [
        ("festival", "start", program.at("start", (2, 0, 0)).sid),
        ("prologue", "start", program.at("start", (3,)).sid),
        ("river", "part", program.at("part", (0,)).sid)]
    assert len(index) == 3 and index.has("river") and index.get("river").title == "By the River"
    assert index.save_label("festival") == "Chapter 2: The Lantern Festival"
    assert index.save_label("prologue") == "Prologue"
    assert [index.save_label(n) for n in ("gone", None, 5)] == [None, None, None]
    assert not index.has(None) and index.get(["river"]) is None


# --- AC-F18-03 — the card's three waits, headless --------------------------------------------

def test_ac03_card_bursts_and_no_card(tmp_path):
    program = story_game(tmp_path / "card", AC03)
    sid = program.at("start", (3,)).sid
    river = StageState("bg river", ())
    fade = TransitionSpec(kind="fade", name="fade", sid=sid, seconds=None, color=None,
                          mask=None, soft=0.1, reverse=False, direction=None)
    out = bursts(run_h(program))
    assert out[1:4] == [
        [ChapterStarted("c", sid),
         ShowStage(river, transition=fade, card=TitleCard("c", "H", "T")),
         StoryWait(1, sid, None, True, True)],
        [StoryWait(2, sid, 3.0, False, True)],
        [ShowStage(river, transition=fade), StoryWait(3, sid, None, True, True)]]
    assert [c.text for c in out[4] if type(c) is Say] == ["L2"]
    # ``0`` seconds: no card, the stage cuts in with L2.
    program = story_game(tmp_path / "none",
                         [*AC03[:3], 'chapter c "H" "T" 0 with fade', AC03[4]])
    sid = program.at("start", (3,)).sid
    burst = bursts(run_h(program))[1]
    assert burst[:2] == [ChapterStarted("c", sid), ShowStage(StageState("bg river", ()))]
    assert type(burst[2]) is Say and burst[2].text == "L2"
    assert not [c for c in burst if type(c) is StoryWait]


def test_ac01_with_launch_codes(tmp_path):
    for i, (top, clause, code) in enumerate([("", "nosuch", "E190"),
                                             ("define notr = 3\n", "notr", "E191")]):
        program = story_game(tmp_path / str(i), [f'chapter c "T" with {clause}', '"L"'], top=top)
        errors = launch_h(program).errors
        assert [(e.code, e.line) for e in errors] == [(code, program.at("start", (0,)).line)]


# --- AC-F18-05 — GameState.chapter -----------------------------------------------------------

REFUSED = [{"current": 5}, {"current": ""}, {"current": "x" * 65}, {"current": "a b"},
           {"current": "a", "extra": 1}, {}, ["a"], "a"]


def test_ac05_game_state_chapter(tmp_path):
    # set at the next checkpoint, not before; older snapshots keep theirs; New Game clears
    program = story_game(tmp_path / "run",
                         ['"L1"', 'chapter a "A"', '"L2"', 'chapter b "B" 0', '"L3"'])
    interp = at_line(program)
    l1 = interp.checkpoint()
    advance(interp)
    assert interp.waiting_for is not None and interp.chapter == "a"
    assert interp.checkpoint() is l1 and l1.chapter == EMPTY_CHAPTER
    finish_waits(interp)
    l2 = interp.checkpoint()
    assert l2.chapter == ChapterState("a")
    advance(interp)
    assert interp.checkpoint().chapter == ChapterState("b") and l2.chapter == ChapterState("a")
    assert interp.restore(l2).result is RestoreResult.OK and interp.chapter == "a"
    interp.new_game(42)
    interp.run(10_000)
    assert interp.chapter is None and interp.checkpoint().chapter == EMPTY_CHAPTER
    # JSON round-trip, a pre-F18 save, an unknown name loads
    program = story_game(tmp_path / "json", ['chapter a "A" 0', '"L1"'])
    interp = at_line(program)
    data = interp.checkpoint().to_json()
    assert data["chapter"] == {"current": "a"}
    assert GameState.from_json(json.loads(json.dumps(data))) == interp.checkpoint()
    del data["chapter"]                                       # a save from before F18
    assert GameState.from_json(data).chapter == EMPTY_CHAPTER
    data["chapter"] = {"current": "gone"}                     # a renamed chapter loads
    state = GameState.from_json(data)
    assert interp.restore(state).result is RestoreResult.OK
    assert interp.chapter == "gone" and interp.chapters.save_label("gone") is None
    # hostile values: StateInvalid, no echo
    base = {"format": 1, "identity_scheme": 1, "position": {"sid": "s", "at": ["s", [0]]},
            "call_stack": [], "variables": {}, "dice": "0" * 16}
    for value in REFUSED:
        with pytest.raises(StateInvalid) as caught:
            GameState.from_json({**base, "chapter": value})
        assert caught.value.reason == "chapter" and "a b" not in str(caught.value), value
    longest = GameState.from_json({**base, "chapter": {"current": "x" * 64}})
    assert longest.chapter == ChapterState("x" * 64)


def test_restore_during_the_card(tmp_path):
    """AC-F18-06's runtime part: restoring in any phase draws no card and ignores the stale
    ``WaitDone``; advancing from the restored line plays the card again."""
    for phase in (0, 1, 2):
        program = story_game(tmp_path / str(phase), AC03)
        interp = at_line(program)
        l1 = interp.checkpoint()
        advance(interp)
        for _ in range(phase):
            interp.post(WaitDone(interp.waiting_for))
            interp.run(10_000)
        stale = interp.waiting_for
        take_all(interp)
        assert interp.restore(l1).result is RestoreResult.OK
        assert (interp.waiting_for, interp.wait_then, interp.card_shown) == (None, None, None)
        assert [c.card for c in take_all(interp) if type(c) is ShowStage] == [None]
        interp.post(WaitDone(stale))
        interp.run(10_000)
        assert interp.current.sid == l1.position and interp.waiting_for is None
        advance(interp)
        assert interp.card_shown == TitleCard("c", "H", "T"), phase


# --- AC-F18-08 — the "chapter" unlock kind --------------------------------------------------

def test_ac08_chapter_unlocks(tmp_path):
    program = story_game(tmp_path / "a", ['chapter c "T" 0', '"L"'])
    interp = at_line(program)
    store = interp.persistent
    assert store.take_new_unlocks() == (("chapter", "c"),)
    interp.new_game(42)
    interp.run(10_000)                                        # re-run: not new
    assert store.take_new_unlocks() == () and store.unlocked("chapter") == ("c",)
    store.clear()
    store.clear(progress=True)
    assert store.is_unlocked("chapter", "c")
    # unknown names give way in a full kind
    program = story_game(tmp_path / "b", ['chapter c "T" 0', '"L"'])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(persistent_mod, "UNLOCK_NAMES_MAX", 2)
        interp = launched(program)
        store = interp.persistent
        store.unlock("chapter", "old1")
        store.unlock("chapter", "old2")
        interp.new_game(42)
        interp.run(10_000)
        assert store.unlocked("chapter") == ("old2", "c")

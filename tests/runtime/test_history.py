"""F13 step 1 — record and save (``specs/F13-history-log/SPEC.md`` §2, §5;
``07-architecture-review.md`` I-2, I-3): AC-F13-01 (the record), AC-F13-02 (headless order),
AC-F13-03 (restore, rollback, hot reload, new game), AC-F13-04 (the JSON and hostile
``history``), with ``fuzz_state.py``'s F13 rows, and the snapshot-sharing guard (no per-line
copy: snapshots hold the live ``HistoryState``; each entry is built once and shared).
"""

import dataclasses
import json
import logging
import re
import time

import pytest

from engine.runtime import history as history_mod
from engine.runtime.commands import (BASE_STYLE, PauseMark, Say, Span, Style, TaggedText,
                                     WaitMark)
from engine.runtime.history import (EMPTY_HISTORY, HISTORY_MAX, NAME_MAX, REPLACEMENT,
                                    TEXT_MAX, HistoryEntry, HistoryState, voice_of)
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.menu import Pick
from engine.runtime.state import GameState, StateInvalid
from tests.runtime import fuzz_state
from tests.runtime.conftest import round_trip
from tests.runtime.menu_story import (ALL, F07, go, launched, load_text, play, sid_at)
from tests.runtime.story import advance, checkpoints, load_files, start

REASON = re.compile(r"^[a-z_]{1,40}$")
SID = "start/0123456789ab"
BOLD = Style(bold=True)
PAIR = chr(0xD800) + chr(0xDC00)          # two lone surrogates (JSON reads one character)


def say(*pieces, name: str | None = "Hana", sid: str = SID) -> Say:
    return Say(sid, "hana" if name else None, name, None, (), "", body=TaggedText(pieces))


def line(text: str, name: str = "", sid: str = SID) -> HistoryEntry:
    return HistoryEntry("line", sid, name, text)


def kinds(history: HistoryState) -> list[str]:
    return [e.kind for e in history.entries]


# --- AC-F13-01 — add_line and add_pick ----------------------------------------------------------

def test_ac01_a_line_records_its_name_and_plain_text():
    body = (Span("A ", BASE_STYLE), Span("crane", BOLD), PauseMark(1.0),
            Span("!\nGood ", BASE_STYLE), WaitMark(), Span("choice.", BASE_STYLE))
    h = EMPTY_HISTORY.add_line(say(*body))
    assert h.entries == (line("A crane!\nGood choice.", "Hana"),)
    assert EMPTY_HISTORY.entries == ()                          # the old state unchanged
    narration = h.add_line(say(Span("The river glows.", BASE_STYLE), name=None))
    no_plate = narration.add_line(say(Span("…", BASE_STYLE), name=""))
    assert [e.name for e in no_plate.entries] == ["Hana", "", ""]
    assert no_plate.entries[:2] == narration.entries and narration.entries[:1] == h.entries


def test_ac01_spans_given_by_the_caller_are_used():
    """Checkpoint steps 2a and 2b share one ``plain()`` call (F17 I-6)."""
    cmd = say(Span("ignored", BASE_STYLE))
    h = EMPTY_HISTORY.add_line(cmd, spans=(Span("x", BASE_STYLE), Span("y", BOLD)))
    assert h.entries[0].text == "xy"


def test_ac01_blank_text_and_i_2_a_blank_pick_add_nothing():
    """I-2: a choice whose shown text is blank (a ``{var}`` that resolves to "") never
    makes an entry, so every state the writer builds passes ``from_json``."""
    h = EMPTY_HISTORY.add_line(say(Span("x", BASE_STYLE)))
    for pieces in ((), (Span("", BASE_STYLE),), (Span("   ", BASE_STYLE),),
                   (Span(" \n\t", BOLD),), (PauseMark(1.0), WaitMark(), PauseMark(2.0))):
        assert h.add_line(say(*pieces)) is h, pieces
    for text in ("", "   ", "\n"):
        assert h.add_pick(Pick(SID, "0123456789ab", text, None)) is h, repr(text)


def test_ac01_a_pick_records_its_menu_and_text():
    h = EMPTY_HISTORY.add_pick(Pick(SID, "0123456789ab", "The paper crane", "Which?"))
    assert h.entries == (HistoryEntry("choice", SID, "", "The paper crane"),)


def test_ac01_text_and_names_are_cut_by_code_points():
    keep = "t" * (TEXT_MAX - 1) + "\U0001F3EE"                  # 2,000 code points, astral last
    h = EMPTY_HISTORY.add_line(say(Span(keep, BASE_STYLE), name="n" * NAME_MAX))
    assert h.entries[0].text == keep and h.entries[0].name == "n" * NAME_MAX
    h = EMPTY_HISTORY.add_line(say(Span("t" * (TEXT_MAX + 1), BASE_STYLE),
                                   name="n" * (NAME_MAX + 1)))
    entry = h.entries[0]
    assert entry.text == "t" * (TEXT_MAX - 1) + "…" and len(entry.text) == TEXT_MAX
    assert entry.name == "n" * (NAME_MAX - 1) + "…" and len(entry.name) == NAME_MAX
    pick = EMPTY_HISTORY.add_pick(Pick(SID, "0123456789ab", "p" * 1_000, None))
    assert pick.entries[0].text == "p" * 1_000


def test_ac01_the_251st_entry_drops_the_oldest():
    h = EMPTY_HISTORY
    states = []
    for i in range(HISTORY_MAX + 1):
        h = h.add_line(say(Span(f"line {i}", BASE_STYLE)))
        states.append(h)
    full = states[HISTORY_MAX - 1]
    assert len(full.entries) == HISTORY_MAX and full.entries[0].text == "line 0"
    assert len(h.entries) == HISTORY_MAX
    assert h.entries[0].text == "line 1" and h.entries[-1].text == f"line {HISTORY_MAX}"
    assert h.entries[:-1] == full.entries[1:]
    assert len(full.entries) == HISTORY_MAX and full.entries[0].text == "line 0"   # unchanged
    h = h.add_pick(Pick(SID, "0123456789ab", "pick", None))
    assert len(h.entries) == HISTORY_MAX and h.entries[0].text == "line 2"


def test_a_lone_surrogate_is_recorded_as_it_draws():
    """A ``{var}`` holding a lone high surrogate before a lone low one would read back as
    one character; the record holds U+FFFD for each, as they draw (AC-F13-09)."""
    h = EMPTY_HISTORY.add_line(say(Span("a" + PAIR + "b", BASE_STYLE), name=chr(0xDFFF)))
    assert h.entries[0].text == "a" + REPLACEMENT * 2 + "b"
    assert h.entries[0].name == REPLACEMENT
    assert h.save_problem() is None
    assert HistoryState.from_json(json.loads(json.dumps(h.to_json()))) == h


# --- AC-F13-02 — the headless order ---------------------------------------------------------------

STORY_02 = """define hana = Character("Hana")
default lantern = "crane"
label start:
    "The river glows."
    hana "I want {b}the {var=lantern}{/b}!{pause=0.5}\\nPlease?"
    menu:
        hana "Will you buy a lantern?"
        "The red one":
            $ lantern = "red"
        "The paper crane":
            $ lantern = "paper crane"
    hana "A {var=lantern}! Good choice."
    menu:
        "Walk home":
            $ lantern += "!"
        "Stay":
            $ lantern += "?"
    "The end."
    return
"""


def run_02(tmp_path):
    program = load_text(tmp_path, STORY_02).program
    assert program is not None
    interp, _ = play(program, "a a c2 a c1", to_end=False)
    return program, interp


def test_ac02_lines_questions_and_picks_in_story_order(tmp_path):
    program, interp = run_02(tmp_path)
    assert interp.status is Status.WAITING and interp.current.line == 18
    entries = interp.history.entries
    assert entries == (
        HistoryEntry("line", sid_at(program, 4), "", "The river glows."),
        HistoryEntry("line", sid_at(program, 5), "Hana", "I want the crane!\nPlease?"),
        HistoryEntry("line", sid_at(program, 6), "Hana", "Will you buy a lantern?"),
        HistoryEntry("choice", sid_at(program, 6), "", "The paper crane"),
        HistoryEntry("line", sid_at(program, 12), "Hana", "A paper crane! Good choice."),
        HistoryEntry("choice", sid_at(program, 13), "", "Walk home"),
        HistoryEntry("line", sid_at(program, 18), "", "The end."),
    )
    assert kinds(interp.history)[:6] == ["line", "line", "line", "choice", "line", "choice"]
    assert interp.checkpoint().history is interp.history
    # The question-less menu's kept line (12) is there once; and the run is deterministic.
    _, again = run_02(tmp_path / "again")
    assert again.history == interp.history
    assert json.dumps(again.checkpoint().to_json()) == json.dumps(interp.checkpoint().to_json())


def test_ac02_the_menu_checkpoint_holds_the_question_but_not_the_pick(tmp_path):
    program = load_text(tmp_path, STORY_02).program
    interp, _ = play(program, "a a", to_end=False)
    assert interp.current.line == 6
    state = interp.checkpoint()
    assert kinds(state.history) == ["line", "line", "line"]
    go(interp, "c1")
    assert kinds(interp.history) == ["line", "line", "line", "choice", "line"]
    assert interp.history.entries[3].text == "The red one"
    assert kinds(state.history) == ["line", "line", "line"]          # the snapshot unchanged


# --- AC-F13-03 — restore, rollback, hot reload, new game ------------------------------------

def test_ac03_a_hot_reload_re_present_records_nothing(tmp_path):
    """Until F39: ``restore(checkpoint())`` (07 "Testability")."""
    _, interp = run_02(tmp_path)
    state = interp.checkpoint()
    interp.take_commands(ALL)
    assert interp.restore(state).result is RestoreResult.OK
    assert interp.history == state.history and interp.history is state.history
    assert interp.checkpoint().history is state.history


def test_ac03_rollback_to_each_earlier_line_and_on_again(tmp_path):
    program = load_text(tmp_path, STORY_02).program
    interp, _ = play(program, "a a c2 a c1 a", to_end=True)
    assert interp.status is Status.ENDED
    fresh, _ = play(program, "", to_end=False)
    states = []
    for answer in ("a", "a", "c2", "a", "c1", "a"):
        states.append(fresh.checkpoint())
        go(fresh, answer)
    for i, state in enumerate(states):
        assert fresh.restore(state).result is RestoreResult.OK
        assert fresh.history is state.history
        assert len(fresh.history.entries) == len(state.history.entries)
    # back to the menu with a question, then a different pick: the old pick is gone
    menu = states[2]
    assert fresh.restore(menu).result is RestoreResult.OK
    go(fresh, "c1")
    assert [e.text for e in fresh.history.entries][3:] == ["The red one",
                                                            "A red! Good choice."]


def test_ac03_a_load_in_a_new_session(tmp_path):
    program, interp = run_02(tmp_path)
    state = interp.checkpoint()
    other = launched(program)
    assert other.restore(round_trip(state)).result is RestoreResult.OK
    assert other.history == state.history
    assert len(other.history.entries) == 7
    go(other, "a")
    assert other.status is Status.ENDED and other.history == state.history


def test_ac03_a_restore_at_a_question_records_it_once(tmp_path):
    program = load_text(tmp_path, STORY_02).program
    interp, _ = play(program, "a a", to_end=False)
    state = interp.checkpoint()
    other = launched(program)
    assert other.restore(round_trip(state)).result is RestoreResult.OK
    assert other.history == state.history and kinds(other.history) == ["line"] * 3
    go(other, "c2")
    assert kinds(other.history) == ["line", "line", "line", "choice", "line"]


def test_ac03_a_failed_restore_leaves_the_history(tmp_path):
    """Restore is all-or-nothing (TR-F03-04): history changes only at the commit."""
    program = load_files(tmp_path, {"main.vns": (
        'default a = 1\ndefault b = 10 // a\nlabel start:\n    "One."\n    "Two."\n')})
    interp = start(program)
    early = interp.checkpoint()
    advance(interp)
    before = interp.history
    assert len(before.entries) == 2
    broken = dataclasses.replace(early, variables={"a": 0})          # b is filled: 10 // 0
    assert interp.restore(broken).result is RestoreResult.DEFAULT_FAILED
    assert interp.history is before
    gone = dataclasses.replace(early, position="start/ffffffffffff")
    assert interp.restore(gone).result is RestoreResult.POSITION_NOT_FOUND
    assert interp.history is before
    assert interp.restore(early, check_only=True).result is RestoreResult.OK
    assert interp.history is before


def test_ac03_a_new_game_is_empty_also_after_returning_to_the_title(tmp_path):
    program, interp = run_02(tmp_path)
    assert interp.history.entries
    interp.new_game(42)                                 # the driver's New Game (title)
    assert interp.history is EMPTY_HISTORY
    interp.run(10_000)
    assert kinds(interp.history) == ["line"]
    assert interp.checkpoint().history.entries == (
        HistoryEntry("line", sid_at(program, 4), "", "The river glows."),)


def test_ac03_an_old_save_without_history_restores_empty_and_records_on(tmp_path):
    from tests.runtime.menu_story import load_m

    data = json.loads((F07 / "saves" / "pre_f07.json").read_text(encoding="ascii"))
    assert "history" not in data
    state = GameState.from_json(data)
    assert state.history is EMPTY_HISTORY
    program = load_m(tmp_path)
    interp = launched(program)
    interp.history = EMPTY_HISTORY.add_line(say(Span("other game", BASE_STYLE)))
    assert interp.restore(state).result is RestoreResult.OK
    assert interp.history is EMPTY_HISTORY
    go(interp, "a")                                       # to the menu with its question
    assert [e.text for e in interp.history.entries] == ["Will you buy a lantern?"]


# --- Snapshots share the history (no copy per line) --------------------------------------------

def test_snapshots_share_history_and_build_each_entry_once(tmp_path):
    """Guard for F03's 2 ms snapshot (AC-F03-76): ``_snapshot`` copies nothing of the
    history, and each entry object is built once and shared by every later state. Over 300
    lines (past the 250 cap) the snapshots hold exactly 300 distinct entry objects, and two
    neighbouring states share all but the newest (and the dropped) entry by identity."""
    program = load_files(tmp_path, {"main.vns": (
        "default n = 0\nlabel start:\n    $ n += 1\n    \"Line {var=n}.\"\n"
        "    if n < 300:\n        jump start\n")})
    interp = start(program)
    states = checkpoints(interp)
    assert len(states) == 300
    distinct = {id(e) for s in states for e in s.history.entries}
    assert len(distinct) == 300
    for older, newer in zip(states, states[1:]):
        kept = older.history.entries[-(HISTORY_MAX - 1):]
        assert all(a is b for a, b in zip(kept, newer.history.entries))
    assert states[-1].history.entries[0].text == "Line 51."
    assert interp.checkpoint().history is interp.history


def test_a_checkpoint_builds_one_history_state(tmp_path, monkeypatch):
    """Counts the ``HistoryState`` objects built: one per recorded line, none by the
    snapshot or by a restore."""
    built = []
    real_add = HistoryState._add

    def counting(self, entry):
        out = real_add(self, entry)
        built.append(out)
        return out

    monkeypatch.setattr(HistoryState, "_add", counting)
    program = load_text(tmp_path, STORY_02).program
    interp, _ = play(program, "a a c2 a c1", to_end=False)
    assert len(built) == 7 and interp.history is built[-1]
    state = interp.checkpoint()
    interp.restore(state)
    assert len(built) == 7


def test_recording_at_250_entries_is_cheap():
    """AC-F13-10's first half as a CI guard (dev limit 0.1 ms, mean of 1,000)."""
    h = EMPTY_HISTORY
    cmd = say(Span("x" * 150, BASE_STYLE))
    for _ in range(HISTORY_MAX):
        h = h.add_line(cmd)
    began = time.perf_counter()
    for _ in range(1_000):
        h.add_line(cmd)
    assert (time.perf_counter() - began) / 1_000 <= 0.000_1


# --- AC-F13-04 — the JSON form --------------------------------------------------------------------

def test_ac04_250_entries_round_trip_through_ensure_ascii():
    texts = ["Hanami 花見 \U0001F3EE\n" + "é" * i for i in range(HISTORY_MAX)]
    h = EMPTY_HISTORY
    for i, text in enumerate(texts):
        h = (h.add_pick(Pick(SID, "0123456789ab", text, None)) if i % 5 == 4
             else h.add_line(say(Span(text, BASE_STYLE), name="ハナ \U0001F338")))
    assert len(h.entries) == HISTORY_MAX
    dumped = json.dumps(h.to_json(), ensure_ascii=True)
    assert dumped.isascii()
    assert HistoryState.from_json(json.loads(dumped)) == h
    assert h.save_problem() is None


def test_ac04_the_state_key_round_trips(tmp_path):
    _, interp = run_02(tmp_path)
    state = interp.checkpoint()
    data = state.to_json()
    assert data["history"]["entries"][3] == {
        "kind": "choice", "sid": state.history.entries[3].sid, "name": "",
        "text": "The paper crane"}
    assert round_trip(state) == state and state.save_problem() is None
    assert round_trip(state).history == state.history
    assert dataclasses.replace(state, history=EMPTY_HISTORY) != state


def test_ac04_a_missing_key_gives_empty_history():
    for path in (F07 / "saves" / "bm.json", F07.parent / "F04" / "saves" / "pre_f04.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "history" not in data
        assert GameState.from_json(data).history is EMPTY_HISTORY
    assert GameState.from_json(json.loads(
        (F07 / "saves" / "bm.json").read_text(encoding="ascii"))).save_problem() is None


def check_rejected(name: str, caplog) -> None:
    data = json.loads((F07 / "saves" / "bm.json").read_text(encoding="ascii"))
    data["history"] = fuzz_state.history_row(name)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(StateInvalid) as caught:
            GameState.from_json(data)
    assert type(caught.value) is StateInvalid and caught.value.reason == "history"
    assert "ZZMARK" not in str(caught.value) and "ZZMARK" not in repr(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert not any("ZZMARK" in r.getMessage() for r in caplog.records)


def test_ac04_rows(caplog):
    """The base is accepted; one row of each kind (the default rows) is rejected; AC-F13-04's
    named list is all there (the rest of the rows, ``slow``, go further)."""
    assert kinds(HistoryState.from_json(fuzz_state.history_base())) == ["line", "line", "choice"]
    names = fuzz_state.history_rows(everything=False)
    assert [fuzz_state.HISTORY_ROWS[n][0] for n in names] == list(fuzz_state.HISTORY_KINDS)
    for name in names:
        check_rejected(name, caplog)
    assert {"251 entries", "extra key ZZMARK", "entry extra key ZZMARK", "no entries",
            "entry without kind", "kind 'x'", "sid 'ZZMARK'", "named choice", "name 201",
            "text empty", "text 2,001", "entry text true",
            "entry text str subclass"} <= fuzz_state.HISTORY_ROWS.keys()


@pytest.mark.slow
@pytest.mark.parametrize("name", [n for n in fuzz_state.history_rows(everything=True)
                                  if n not in fuzz_state.history_rows(everything=False)])
def test_ac04_rows_slow(name, caplog):
    check_rejected(name, caplog)


def test_ac04_the_limits_are_inclusive():
    base = fuzz_state.history_base()
    base["entries"][0].update(name="n" * NAME_MAX, text="t" * TEXT_MAX)
    base["entries"] = (base["entries"] * HISTORY_MAX)[:HISTORY_MAX]
    h = HistoryState.from_json(base)
    assert len(h.entries) == HISTORY_MAX and len(h.entries[0].text) == TEXT_MAX


def run_history_fuzz(count: int, seed: int, inflate: bool = False) -> int:
    """Mutated ``history`` values: ``StateInvalid`` (no input in its text) or a state that
    round-trips."""
    base = json.loads((F07 / "saves" / "bm.json").read_text(encoding="ascii"))
    accepted = 0
    for history in fuzz_state.mutations([fuzz_state.history_base()], count, seed, inflate):
        data = dict(base, history=history)
        try:
            state = GameState.from_json(data)
        except StateInvalid as error:
            assert REASON.match(error.reason) and "ZZMARK" not in str(error)
            continue
        accepted += 1
        assert round_trip(state) == state and state.save_problem() is None
    return accepted


def test_ac04_fuzz_ci():
    accepted = run_history_fuzz(300, seed=1304)
    assert 0 < accepted < 300


@pytest.mark.slow
def test_ac04_fuzz_full():
    run_history_fuzz(10_000, seed=130_400, inflate=True)


def test_save_problem_of_history(tmp_path):
    _, interp = run_02(tmp_path)
    state = interp.checkpoint()
    entry = state.history.entries[0]
    for bad in (dataclasses.replace(entry, sid="ZZMARK"),
                dataclasses.replace(entry, text=""),
                dataclasses.replace(entry, text="t" * (TEXT_MAX + 1)),
                dataclasses.replace(entry, kind="x"),
                dataclasses.replace(entry, kind="choice", name="Hana"),
                dataclasses.replace(entry, text=5)):
        bad_state = dataclasses.replace(state, history=HistoryState((bad,)))
        assert bad_state.save_problem() == "history", bad
    pair = dataclasses.replace(entry, text="a" + PAIR + "b")
    assert dataclasses.replace(state, history=HistoryState((pair,))).save_problem() \
        == "lone_surrogate"
    lone = dataclasses.replace(entry, name="a" + PAIR[0] + "b")
    assert dataclasses.replace(state, history=HistoryState((lone,))).save_problem() is None
    assert state.save_problem() is None


# --- I-4 — the voice port's rule -----------------------------------------------------------------

def test_voice_of_a_line_a_question_and_others(tmp_path):
    files = {"main.vns": (
        'define hana = Character("Hana")\nlabel start:\n    voice "v/one.ogg"\n'
        '    hana "One."\n    "Two."\n    menu:\n        voice "v/q.ogg"\n'
        '        hana "Which?"\n        "A":\n            "A."\n    menu:\n'
        '        "B":\n            "B."\n')}
    program = load_files(tmp_path, files)
    one, two = program.at("start", (1,)), program.at("start", (2,))
    menu, bare = program.at("start", (3,)), program.at("start", (4,))
    assert voice_of(program, one.sid) == "v/one.ogg"
    assert voice_of(program, two.sid) is None
    assert voice_of(program, menu.sid) == "v/q.ogg"
    assert voice_of(program, bare.sid) is None
    assert voice_of(program, "start/ffffffffffff") is None
    assert history_mod.voice_of is voice_of

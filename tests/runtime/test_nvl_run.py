"""F17 headless NVL: the commands of a run (``06-acceptance.md`` AC-F17-03), the page record
(AC-F17-04), the 32-line cap and W102 (AC-F17-05), the restore burst (AC-F17-08), and rollback
across a mode change, then forward (AC-F17-09). Template N and Run N as 06 §0.3, §0.4
(``tests/runtime/nvl_story.py``); restores go through ``Interpreter.restore`` (F03's
``driver.restore`` path)."""

import json
import logging

import pytest

from engine.runtime.commands import (Advance, AudioRestore, NvlLine, NvlPage, PlayVoice,
                                     PrefetchImages, Say, ShowMenu, ShowStage, Span, Style)
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.nvl import EMPTY_NVL, NvlState
from engine.runtime.state import GameState
from engine.script.messages import format_message
from tests.runtime.menu_story import inputs, launched
from tests.runtime.nvl_story import (F17, RUN_N_FULL, RUN_N_LINES, bursts, load_n, replay,
                                     shown, sid)

PLAIN = Style()


def _nvl(burst) -> list[NvlPage]:
    return [c for c in burst if type(c) is NvlPage]


def _round_trip(state: GameState) -> GameState:
    return GameState.from_json(json.loads(json.dumps(state.to_json(), ensure_ascii=True)))


# --- AC-F17-03 — commands of a run -------------------------------------------------------------

def test_ac_f17_03_commands_of_a_run(tmp_path):
    program = load_n(tmp_path / "n")
    interp, out, states = bursts(program)
    on, off = ("nvl", True, ()), ("nvl", False, ())
    assert [shown(b, program) for b in out] == [
        [("say", 6)], [on, ("say", 8)], [("say", 9)], [("say", 10)], [on, ("say", 12)],
        [("say", 14)], [("say", 15), ("menu",)], [on, ("say", 21)], [off, ("say", 23)]]
    # Every other command equals the run without lines 7, 11, 22.
    adv = load_n(tmp_path / "adv", drop=(7, 11, 22))
    _, plain, _ = bursts(adv)
    assert [[c for c in b if type(c) is not NvlPage] for b in out] == plain
    # nvl on while on: no NvlPage before line 12, and the page keeps L8–L10.
    on_on = load_n(tmp_path / "onon", replace={11: "    nvl on"})
    _, got, kept = bursts(on_on)
    assert not _nvl(got[4]) and [l.sid for l in kept[4].nvl.page] == [
        sid(on_on, n) for n in (8, 9, 10, 12)]
    # nvl off while off; nvl clear in ADV: no NvlPage at all, every record EMPTY_NVL.
    for row in ("    nvl off", "    nvl clear"):
        quiet = load_n(tmp_path / row.split()[-1], replace={7: row})
        _, got, records = bursts(quiet)
        assert not [c for b in got for c in _nvl(b)], row
        assert all(state.nvl is EMPTY_NVL for state in records), row
    # A new game: no NvlPage before line 6; interp.nvl is EMPTY_NVL.
    assert not _nvl(out[0]) and states[0].nvl is EMPTY_NVL
    interp.new_game(42)
    interp.run(10_000)
    assert interp.nvl is EMPTY_NVL and not _nvl(interp.take_commands(1 << 30))
    # An nvl line is never a checkpoint position.
    interp.post(Advance(sid(program, 6)))
    interp.run(1)                                           # one step: nvl on
    assert interp.status is Status.RUNNING and interp.nvl.on
    assert interp.checkpoint().position == sid(program, 6)


# --- AC-F17-04 — the page record ---------------------------------------------------------------

def _texts(state: GameState) -> list[str]:
    return ["".join(s.text for s in line.spans) for line in state.nvl.page]


def test_ac_f17_04_the_page_record(tmp_path):
    program = load_n(tmp_path / "n")
    _, _, states = bursts(program)
    at = dict(zip(RUN_N_LINES, states))
    L8 = NvlLine(sid(program, 8), "", None, (Span("The festival comes once a year.", PLAIN),))
    L9 = NvlLine(sid(program, 9), "Hana", "#A02860", (
        Span("You're thinking about ", PLAIN), Span("last year", Style(bold=True)),
        Span(" again.", PLAIN)))
    L10 = NvlLine(sid(program, 10), "", None, (
        Span("I didn't answer.", Style(italic=True, color="#1e4a9c")),))   # pause dropped
    L15 = NvlLine(sid(program, 15), "Hana", "#A02860", (Span("Will you open it?", PLAIN),))
    for line in (6, 23):
        assert at[line].nvl == EMPTY_NVL
    assert at[8].nvl == NvlState(True, (L8,))
    assert at[9].nvl == NvlState(True, (L8, L9))
    assert at[10].nvl == NvlState(True, (L8, L9, L10))
    l12 = "Three days later, a lantern came."
    assert _texts(at[12]) == [l12]
    assert _texts(at[14]) == [l12, "It was a letter."]                # recorded, as shown
    assert at[15].nvl.page[0] is at[12].nvl.page[0] and at[15].nvl.page[2] == L15
    assert at[15].variables["wish"] == "a letter"
    assert _texts(at[21]) == ["After the pick."] and at[21].nvl.on
    assert [l.sid for l in at[12].nvl.page + at[14].nvl.page[1:] + at[15].nvl.page[2:]] == [
        sid(program, n) for n in (12, 14, 15)]
    # An empty line is recorded with no spans.
    empty = load_n(tmp_path / "empty", replace={14: '    ""'})
    _, _, records = bursts(empty)
    assert records[5].nvl.page[-1] == NvlLine(sid(empty, 14), "", None, ())
    # A question-less menu records nothing new at the menu.
    bare = load_n(tmp_path / "bare", drop=(16,))
    _, _, records = bursts(bare)
    assert _texts(records[6]) == [l12, "It was a letter."]
    # scene in NVL leaves the page unchanged.
    scene = load_n(tmp_path / "scene", drop=(5,),
                   replace={9: '    hana "You\'re thinking about {b}last year{/b} again."'
                               '⏎[4]scene red'})
    _, _, records = bursts(scene)
    assert [l.sid for l in records[3].nvl.page] == [sid(scene, n) for n in (7, 8, 10)]
    # A pick in ADV holds no NvlPage.
    adv = load_n(tmp_path / "adv", drop=(7,))
    _, got, _ = bursts(adv)
    assert not [c for b in got for c in _nvl(b)]


# --- AC-F17-05 — the 32-line cap and W102 -------------------------------------------------------

def _many(k: int, *, again: int = 0) -> str:
    lines = "".join(f'⏎[4]"L{n}"' for n in range(1, k + 1))
    if again:
        lines += "⏎[4]nvl clear" + "".join(f'⏎[4]"M{n}"' for n in range(1, again + 1))
    return "label many:⏎[4]nvl on" + lines


def _w102_logs(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "have gone by" in r.getMessage()]


@pytest.mark.parametrize("k, again, dev", [(32, 0, True), (33, 0, True), (40, 0, True),
                                           (33, 33, True), (33, 0, False)])
def test_ac_f17_05_the_32_line_cap_and_w102(tmp_path, caplog, k, again, dev):
    program = load_n(tmp_path / "n", replace={6: "    jump many"}, T=_many(k, again=again))
    caplog.set_level(logging.INFO)
    interp, _, records = bursts(program, " ".join(["a"] * (k + again - 1)), dev=dev)
    last = [("".join(s.text for s in line.spans)) for line in records[-1].nvl.page]
    prefix, count = ("M", again) if again else ("L", k)
    first = max(1, count - 31)
    assert last == [f"{prefix}{n}" for n in range(first, count + 1)]
    logs = _w102_logs(caplog)
    if k == 32 or not dev:
        assert logs == []
        return
    line_33 = 26 + 33                                       # label many: is line 25
    assert logs == [f"script/main.vns, line {line_33}: " + format_message("W102", (33,))]


# --- AC-F17-08 — the restore burst --------------------------------------------------------------

_ORDER = (AudioRestore, NvlPage, ShowStage, PlayVoice, Say, ShowMenu, PrefetchImages)


def _check_burst(burst, state: GameState) -> None:
    kinds = [type(c) for c in burst]
    assert kinds.count(NvlPage) == 1
    assert kinds.index(NvlPage) == (1 if kinds[0] is AudioRestore else 0)
    assert [_ORDER.index(k) for k in kinds] == sorted(_ORDER.index(k) for k in kinds)
    (page,) = _nvl(burst)
    assert page == NvlPage(state.nvl.on, state.nvl.page)


def test_ac_f17_08_the_restore_burst(tmp_path):
    program = load_n(tmp_path / "n")
    interp, _, states = bursts(program)
    for state in states:
        fresh = launched(program)
        assert fresh.restore(_round_trip(state)).result is RestoreResult.OK
        burst = fresh.take_commands(1 << 30)
        _check_burst(burst, state)
        assert fresh.nvl == state.nvl and fresh.history == state.history
        assert fresh.checkpoint().history == state.history        # nothing recorded
    # line 6: NvlPage(False, ())
    six = launched(program)
    six.restore(states[0])
    assert _nvl(six.take_commands(1 << 30)) == [NvlPage(False, ())]
    # A save from before F17.
    data = json.loads((F17 / "saves" / "pre_f17.json").read_text(encoding="utf-8"))
    assert "nvl" not in data and data["format"] == 1
    old = launched(program)
    assert old.restore(GameState.from_json(data)).result is RestoreResult.OK
    assert _nvl(old.take_commands(1 << 30)) == [NvlPage(False, ())]
    # A recorded sid that no longer exists is sent as recorded.
    ghost = NvlLine("zz/000000000000", "", None, (Span("Gone.", PLAIN),))
    state = states[3]
    odd = GameState.from_json({**state.to_json(),
                               "nvl": NvlState(True, (ghost,) + state.nvl.page).to_json()})
    again = launched(program)
    assert again.restore(odd).result is RestoreResult.OK
    assert _nvl(again.take_commands(1 << 30))[0].lines[0] == ghost
    # A failed restore leaves interp.nvl unchanged.
    before = interp.nvl
    lost = GameState.from_json({**states[3].to_json(),
                                "position": {"sid": "start/000000000000", "at": ["x", [9]]}})
    assert interp.restore(lost).result is RestoreResult.POSITION_NOT_FOUND
    assert interp.nvl is before and interp.take_commands(1 << 30) == []


# --- AC-F17-09 — rollback across a mode change, then forward ------------------------------------

@pytest.mark.parametrize("line, after, expect", [
    (6, "a", (True, 8)),                    # before nvl on
    (10, "a", (True, 12)),                  # before nvl clear
    (15, "c1", (True, 21)),                 # at the menu
    (21, "a", (False, 23)),                 # after the pick
])
def test_ac_f17_09_rollback_across_a_mode_change_then_forward(tmp_path, line, after, expect):
    program = load_n(tmp_path / "n")
    interp, first, states = bursts(program)
    index = RUN_N_LINES.index(line)
    state = states[index]
    assert interp.restore(state).result is RestoreResult.OK
    interp.take_commands(1 << 30)
    assert interp.nvl == state.nvl
    if line == 6:
        assert interp.nvl is EMPTY_NVL
    rest = inputs(RUN_N_FULL)[index:]
    assert rest[0].startswith("choose") == (after == "c1")
    out, again = replay(interp, " ".join("c1" if r.startswith("choose") else "a"
                                         for r in rest))
    on, number = expect
    assert shown(out[0], program)[:2] == [("nvl", on, ()), ("say", number)]
    assert out == first[index + 1:]
    assert [s.to_json() for s in again] == [s.to_json() for s in states[index + 1:]]
    expected_page = {10: 3, 15: 3, 21: 1}.get(line)
    if expected_page is not None:
        assert len(state.nvl.page) == expected_page and state.nvl.on


# --- AC-F17-26 — history (F13) ------------------------------------------------------------------

def test_ac_f17_26_history_in_nvl_equals_adv(tmp_path):
    def entries(interp) -> list[tuple]:
        return [(e.kind, e.name, e.text) for e in interp.history.entries]

    nvl, _, states = bursts(load_n(tmp_path / "nvl"))
    adv, _, _ = bursts(load_n(tmp_path / "adv", drop=(7, 11, 22)))
    got = entries(nvl)
    assert got == entries(adv) and len(got) == 10
    assert got[0][2] == "Before." and got[-1][2] == "Back in the box."
    assert ("line", "Hana", "Will you open it?") in got
    assert any(kind != "line" and text == "Open it" for kind, _, text in got)
    # Restores record nothing (AC-F17-08's burst): restoring each state keeps its history.
    for state in states:
        fresh = launched(nvl.program)
        assert fresh.restore(state).result is RestoreResult.OK
        assert fresh.checkpoint().history == state.history
    # R14 '""': an empty line adds no entry (it still takes a page row, AC-F17-12 G).
    empty, _, at = bursts(load_n(tmp_path / "empty", replace={14: '    ""'}))
    assert len(entries(empty)) == 9 and "" not in [text for _, _, text in entries(empty)]
    page = at[RUN_N_LINES.index(14)].nvl.page
    assert len(page) == 2 and page[-1].spans == ()

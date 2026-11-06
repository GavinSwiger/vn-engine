"""The frozen version 1 saves load forever (v1 review M7; ``tests/persist/v1_saves.py`` says
how they were made, once).

``tests/fixtures/F11/v1/`` holds two saves of the version 1 story in ``v1/game/``. Every
build must read them OK, restore every field to the values asserted here, load them at their
lines, and play on from them. They are never regenerated: if this test fails, the change
broke version 1 saves. Fix the change (or add a migration), never the files or the values
below.
"""

import pytest

from engine.persist import saves
from engine.persist.saves import SlotId, SlotStatus
from engine.runtime.clock import ClockState
from engine.runtime.commands import Advance, MessageArrived, WaitDone
from engine.runtime.interpreter import RestoreResult
from engine.runtime.state import GameState
from engine.runtime.triggers import Armed
from tests.persist import v1_saves as v1

NAMES = sorted(v1.SAVES)


def _read(name: str) -> saves.FullRead:
    data = (v1.V1 / name).read_bytes()
    read = saves.parse_full(data, game_id=v1.GAME_ID)
    assert read.status is SlotStatus.OK and read.state is not None, (name, read.reason)
    return read


def _common(state: GameState) -> None:
    """What both saves hold: the parts made before "Evening."."""
    assert dict(state.variables) == {"visits": 1}
    items = state.items
    assert items.held == ("coin", "match", "key")
    assert [items.count_of(i) for i in range(3)] == [30, 2, 1]
    assert items.bar is True                                    # show hotbar
    hana = items.inbox[0]
    assert (hana.sender, hana.message, hana.contact, hana.device, hana.time) == (
        "hana", "invite", "Hana", "pigeon", "Day 1")
    assert [(ln.side, ln.name, ln.text) for ln in hana.lines] == [
        ("them", "Hana", "Meet me at the bridge.")]
    assert hana.ask == (("yes", "I will."), ("no", "Not this year.")) and hana.reply == "yes"
    assert dict(state.points) == {"logic": 3, "trust": 2}
    assert state.points.shown == ("logic", "trust")
    (pick,) = state.choices.picks
    assert (pick.text, pick.question) == ("The gate was locked.", "Admit it.")
    assert pick.roll is not None and (pick.roll.value, pick.roll.ok) == (3, False)
    assert any(e.kind == "choice" and e.text == "I will." for e in state.history.entries)


def test_the_files_are_version_1s():
    assert NAMES == sorted(p.name for p in v1.V1.glob("*.vnsave"))
    for name, (line, seq) in v1.SAVES.items():
        read = _read(name)
        meta = read.meta
        assert meta is not None and (meta.state_rev, meta.state_format) == (1, 1), name
        assert (meta.seq, meta.saved_at, meta.game, meta.game_version, meta.description) == (
            seq, v1.SAVED_AT, v1.GAME_ID, "1.0", line), name
        head = saves.classify_head((v1.V1 / name).read_bytes(),
                                   (v1.V1 / name).stat().st_size, SlotId("auto", 1),
                                   game_id=v1.GAME_ID, thumb=True)
        assert head.status is SlotStatus.OK and head.jpeg is None, name


def test_evening_restores_every_field():
    state = _read("evening.vnsave").state
    _common(state)
    assert len(state.items.inbox) == 1
    assert state.clock == ClockState(1, 1, True)                # day 1, the second part
    assert state.triggers.armed == (Armed("message:ren/late", 2),)   # waiting for day 2
    assert state.triggers.retired == frozenset()


def test_next_morning_restores_every_field():
    state = _read("next_morning.vnsave").state
    _common(state)
    assert state.clock == ClockState(2, 0, True)
    assert state.triggers.armed == () and state.triggers.retired == frozenset()
    ren = state.items.inbox[1]
    assert (ren.sender, ren.message, ren.contact, ren.time, ren.ask, ren.reply) == (
        "ren", "late", "Ren", "Day 2", (), "")
    assert [ln.text for ln in ren.lines] == ["Running late!"]


@pytest.mark.parametrize("name", NAMES)
def test_each_loads_at_its_line_and_plays_on(tmp_path, name):
    folder = tmp_path / "saves"
    folder.mkdir()
    slot = SlotId(1, 1)
    (folder / slot.file_name()).write_bytes((v1.V1 / name).read_bytes())
    read = saves.read_slot_full(folder, slot, game_id=v1.GAME_ID)
    assert read.status is SlotStatus.OK and read.state is not None, read.reason
    interp = v1.launched(v1.load_program())
    interp.new_game(1)
    interp.run(10_000)
    interp.take_commands(1 << 30)
    assert interp.restore(read.state, check_only=True).result is RestoreResult.OK
    assert interp.restore(read.state).result is RestoreResult.OK
    interp.run(10_000)
    interp.take_commands(1 << 30)
    assert v1.line_text(interp) == v1.SAVES[name][0]
    assert interp.checkpoint().to_json() == read.state.to_json()
    assert interp.codex.bar_shown() and interp.codex.deliveries() == read.state.items.inbox
    if name == "evening.vnsave":                    # the waiting message arrives on day 2
        interp.post(Advance(interp.current.sid))
        interp.run(10_000)
        commands = interp.take_commands(1 << 30)
        while interp.waiting_for is not None:       # the day card
            interp.post(WaitDone(interp.waiting_for))
            interp.run(10_000)
            commands += interp.take_commands(1 << 30)
        arrived = [c for c in commands if type(c) is MessageArrived]
        assert [c.contact for c in arrived] == ["ren"]
        assert v1.line_text(interp) == "Next morning."
        assert [d.message for d in interp.codex.deliveries()] == ["invite", "late"]

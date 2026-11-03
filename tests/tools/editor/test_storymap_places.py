"""The story map's places, routing, chips and map history, pure half (F46 ``06-acceptance.md``
AC-F46-24, AC-F46-26; ``04-technical.md`` §3.4, §6.8, §6.9). No Tk: drags and the window's
Ctrl+Z are step 4's window tests."""

import pytest

from engine.tools.editor.storymap import (
    BOX_HEIGHT, MAP_UNDO_STEPS, PLACE_TRIES, MapHistory, MapStep, RectHash, box_rect,
    chip_slot, edge_line, layout, map_undo, out_edges, place_free)

FESTIVAL = [("start", "festival", "jump", "f", 1), ("festival", "stall", "jump", "f", 2)]
NAMES = ["start", "festival", "stall", "side"]


def _at(m) -> dict[str, tuple[int, int]]:
    return {b.name: (b.x, b.y) for b in m.boxes}


def test_ac_f46_24_placing_boxes():
    placed = {"start": (0, 0), "festival": (220, 0)}
    m = layout(FESTIVAL, NAMES, places=placed)
    assert _at(m)["stall"] == (440, 0)                      # 220 px right of its linker
    assert _at(m)["side"] == (660, 0)                       # no linker: near its F45 cell
    assert m == layout(FESTIVAL, NAMES, places=placed)      # deterministic

    # (440, 0) taken by a placed box: the nearest free spot in 20 px rings.
    crowded = {**placed, "side": (440, 0)}
    m = layout(FESTIVAL, NAMES, places=crowded)
    assert _at(m) == {**crowded, "stall": (440, 60)}        # placed boxes never move
    assert place_free([(440, 0)], (440, 0)) == (440, 60)

    # No free spot in 2,000 tries: the row below the lowest box.
    grid = [(220 * c, 60 * r) for c in range(40) for r in range(40)]
    assert PLACE_TRIES == 2_000
    assert place_free(grid, (100, 100)) == (100, 39 * 60 + 60)
    assert place_free(grid, (100, 100)) == place_free(list(grid), (100, 100))

    # out_edges by target y; 2 edges leave a 40-high box at y0 + 13⅓ and y0 + 26⅔.
    fan = [("start", "low", "jump", "f", 1, "Go low", False),
           ("start", "high", "menu", "f", 2, "Go high", False)]
    m = layout(fan, ["start", "low", "high"],
               places={"start": (0, 100), "low": (1000, 120), "high": (1000, 100)})
    low, high = 0, 1                                        # edge indexes, link order
    assert out_edges(m, m.index_of("start")) == (high, low)
    assert BOX_HEIGHT == 40
    assert edge_line(m, high)[1] == pytest.approx(100 + 40 / 3)
    assert edge_line(m, low)[1] == pytest.approx(100 + 80 / 3)
    # The edges' chips meet at t = 0.5: the later edge (link order) takes 0.35.
    assert (m.edges[low].slot, m.edges[high].slot) == (0.5, 0.35)

    # The slot rule: the first of 0.5, 0.35, 0.65, 0.2, 0.8 overlapping nothing, else 0.5.
    line, size = (0, 0, 1000, 0), (40, 18)
    blocked: list[float] = []
    for t in (0.5, 0.35, 0.65, 0.2, 0.8):
        taken = RectHash(box_rect(1000 * b - 80, -20) for b in blocked)
        assert chip_slot(line, size, taken) == t
        blocked.append(t)
    assert chip_slot(line, size, RectHash(box_rect(1000 * b - 80, -20) for b in blocked)) == 0.5


class Record:
    """A fake open file: its change counter and spied text undo/redo."""

    def __init__(self) -> None:
        self.changes = 0
        self.calls: list[str] = []

    def edit_undo(self) -> None:
        self.calls.append("undo")
        self.changes += 1

    def edit_redo(self) -> None:
        self.calls.append("redo")
        self.changes += 1


def _edit(history: MapHistory, records: dict, *refs: str, title: str = "edit") -> None:
    for ref in refs:
        records[ref].changes += 1                           # the apply
    history.push(MapStep(title, {}, {}, tuple((r, records[r].changes) for r in refs)))


def _move(history: MapHistory) -> None:
    history.push(MapStep("move", {"river": (0, 0)}, {"river": (40, 20)}))


def _type(records: dict, ref: str) -> None:
    records[ref].changes += 1


CASES = {
    # sequence → (expected blocked refs, expected text undo calls per ref)
    "move": (lambda h, r: _move(h), (), {}),
    "form edit": (lambda h, r: _edit(h, r, "ch2.vns"), (), {"ch2.vns": ["undo"]}),
    "form edit, key": (lambda h, r: (_edit(h, r, "ch2.vns"), _type(r, "ch2.vns")),
                       ("ch2.vns",), {"ch2.vns": []}),
    "rename, key in one": (lambda h, r: (_edit(h, r, "main.vns", "ch2.vns"),
                                         _type(r, "main.vns")),
                           ("main.vns",), {"main.vns": [], "ch2.vns": []}),
    "edit, reload or text undo": (lambda h, r: (_edit(h, r, "ch2.vns"), _type(r, "ch2.vns")),
                                  ("ch2.vns",), {"ch2.vns": []}),
    "edit, close": (lambda h, r: (_edit(h, r, "ch2.vns"), r.update({"ch2.vns": None})),
                    ("ch2.vns",), {}),
}


@pytest.mark.parametrize("case", list(CASES))
def test_ac_f46_26_map_undo(case):
    run, blocked, calls = CASES[case]
    history, records = MapHistory(), {"main.vns": Record(), "ch2.vns": Record()}
    run(history, records)
    step = history.undo_step()
    done = map_undo(history, records)
    assert done.step == step and done.blocked == blocked
    assert {ref: rec.calls for ref, rec in records.items()
            if rec is not None and ref in calls} == calls
    assert all(not rec.calls for ref, rec in records.items() if rec and ref not in calls)
    if blocked:                                             # dropped; nothing restored
        assert done.places is None and history.undo_step() is None
        assert history.redo_step() is None
        return
    assert done.places == step.before                       # place restored
    redone = map_undo(history, records, redo=True)
    assert redone.places == step.after and not redone.blocked
    if step.files:                                          # redo calls edit_redo
        assert records["ch2.vns"].calls == ["undo", "redo"]

    # An undo, then a new step: the redo list is empty.
    map_undo(history, records)
    assert history.redo_step() is not None
    _move(history)
    assert history.redo_step() is None

    # 101 steps: 100 kept, oldest dropped.
    history = MapHistory()
    for i in range(MAP_UNDO_STEPS + 1):
        history.push(MapStep(f"move {i}", {}, {}))
    assert len(history) == 100 and MAP_UNDO_STEPS == 100
    titles = [map_undo(history, {}).step.title for _ in range(100)]
    assert titles[-1] == "move 1" and map_undo(history, {}).step is None

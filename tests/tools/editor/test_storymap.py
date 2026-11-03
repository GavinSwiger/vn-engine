"""The story map's layout, marks and navigation, pure half (F45 ``06-acceptance.md``
AC-F45-42, AC-F45-44, and AC-F45-43's keyboard rules; ``04-technical.md`` §7.7; ``07`` I-9).
No Tk: drawing, clicks and zoom are step 5's window tests."""

import pytest

import engine.script  # noqa: F401  registers every statement
from engine.core.paths import GamePaths
from engine.script import load_story
from engine.script.labelgraph import LabelLink, label_links
from engine.tools.editor.storymap import (
    COLUMN_STEP, ROW_STEP, Box, MapLayout, cycle_target, hidden_text, label_notes, layout,
    neighbour)

# S's scripts (06 §5), written here so these tests don't wait for the shared fixture.
S_MAIN = ('include "ch2.vns"\ndefine hana = Character("Hana")\ndefault trust = 0\n'
          'label start:\n    show hana happy\n    hana "Hi."\n    call club\n    jump bridge\n')
S_CH2 = ('label club:\n    menu:\n        "Go to the river":\n            jump river\n'
         '        "Stay":\n            "You stay."\n    return\nlabel bridge:\n'
         '    "The bridge."\nlabel river:\n    "The river."\nlabel side:\n    "Unreached."\n')


@pytest.fixture
def s_graph(tmp_path):
    """S's links and labels, as the check child builds them."""
    root = tmp_path / "my_game"
    (root / "script").mkdir(parents=True)
    (root / "config.toml").write_bytes(b'[game]\nid = "my_game"\ntitle = "My Game"\n')
    (root / "script" / "main.vns").write_bytes(S_MAIN.encode())
    (root / "script" / "ch2.vns").write_bytes(S_CH2.encode())
    program = load_story(GamePaths(root.resolve())).program
    links, _ = label_links(program, limit=50_000)
    labels = [(name, label.file.ref, label.line) for name, label in program.labels.items()]
    return links, labels


def _grid(m: MapLayout) -> dict[str, tuple[int, int, int, int]]:
    return {b.name: (b.column, b.row, b.x, b.y) for b in m.boxes}


def _chain(n: int) -> tuple[list[LabelLink], list[str]]:
    names = ["start"] + [f"l{i}" for i in range(1, n)]
    links = [LabelLink(a, b, "jump", "script/main.vns", i)
             for i, (a, b) in enumerate(zip(names, names[1:]))]
    return links, names


@pytest.mark.parametrize("size, cap", [(16, 15), pytest.param(1_600, 1_500,
                                                              marks=pytest.mark.slow)])
def test_ac_f45_42_story_map_layout(s_graph, size, cap):
    links, labels = s_graph
    m = layout(links, labels)
    assert _grid(m) == {
        "start": (0, 0, 0, 0), "club": (1, 0, 220, 0), "bridge": (1, 1, 220, 60),
        "river": (2, 0, 440, 0), "side": (3, 0, 660, 0)}
    assert [e.kind for e in m.edges] == ["call", "jump", "menu"]
    assert m == layout(links, labels)                                  # deterministic

    loop = [LabelLink("start", "b", "jump", "f", 1), LabelLink("b", "start", "jump", "f", 2),
            LabelLink("b", "b", "jump", "f", 3)]
    assert _grid(layout(loop, ["start", "b"])) == {"start": (0, 0, 0, 0),
                                                   "b": (1, 0, COLUMN_STEP, 0)}

    # The box cap keeps the first by (column, row) and draws no edge to a dropped box.
    chain, names = _chain(size)
    m = layout(chain, names, max_boxes=cap)
    assert [b.name for b in m.boxes] == names[:cap]
    assert hidden_text(m) == f"{size - cap} label{'s' if size - cap > 1 else ''} not shown"
    assert len(m.edges) == cap - 1 and all(e.dst < cap for e in m.edges)

    # neighbour on a 3×3 grid: each direction from the centre, None past an edge.
    m = MapLayout(tuple(Box(f"c{c}r{r}", None, None, c, r, COLUMN_STEP * c, ROW_STEP * r)
                        for c in range(3) for r in range(3)), (), 0, 600, 160)
    at = {(b.column, b.row): i for i, b in enumerate(m.boxes)}
    centre = at[1, 1]
    assert [neighbour(m, centre, d) for d in ("Left", "right", "up", "down")] == [
        at[0, 1], at[2, 1], at[1, 0], at[1, 2]]
    assert neighbour(m, at[2, 0], "right") is None and neighbour(m, at[0, 0], "up") is None
    assert m.boxes[centre].y == ROW_STEP


def test_ac_f45_43_keyboard_rules(s_graph):
    """The pure half of AC-F45-43's keys: Right from ``start`` reaches column 1, and Tab
    from ``start`` cycles ``club``, ``bridge``."""
    m = layout(*s_graph)
    start, club, bridge = (m.index_of(n) for n in ("start", "club", "bridge"))
    assert m.boxes[neighbour(m, start, "Right")].column == 1
    assert cycle_target(m, start, None) == club
    assert cycle_target(m, start, club) == bridge
    assert cycle_target(m, start, bridge) == club
    assert cycle_target(m, m.index_of("side"), None) is None


def test_ac_f45_44_story_map_marks(s_graph):
    links, labels = s_graph
    marks = {b.name: b.marks for b in layout(links, labels).boxes}
    assert marks == {"start": ("start",), "club": (), "bridge": ("ends",),
                     "river": ("ends",), "side": ("not reached", "ends")}
    shown = layout(links, labels, file="script/ch2.vns")
    assert [b.name for b in shown.boxes] == ["club", "bridge", "river", "side"]
    assert [e.kind for e in shown.edges] == ["menu"]

    # 07 I-9: a label only `call` reaches returns, so it doesn't end; one a jump also
    # reaches does.
    calls = [LabelLink("start", "shop", "call", "f", 1), LabelLink("start", "inn", "call", "f", 2),
             LabelLink("start", "inn", "jump", "f", 3)]
    marks = {b.name: b.marks for b in layout(calls, ["start", "shop", "inn"]).boxes}
    assert marks["shop"] == () and marks["inn"] == ("ends",)


def test_ac_f41_09_a_replay_scene_is_not_marked_not_reached(s_graph):
    """F41 P4: ``replay_scene`` rows (read by name) are starting points for "not reached";
    columns stay the distance from ``start``."""
    links, labels = s_graph
    links = [*links, LabelLink("side", "epilogue", "jump", "script/ch2.vns", 14),
             LabelLink("orphan", "epilogue", "call", "script/ch2.vns", 16)]
    labels = [*labels, ("epilogue", "script/ch2.vns", 15), ("orphan", "script/ch2.vns", 16)]
    names = {"replay_scene": [("side", "script/main.vns", 2), ("nowhere", "script/main.vns", 3)]}
    notes = label_notes(labels, names)
    assert {name for name, note in notes.items() if note.replay} == {"side"}
    plain, shown = layout(links, labels), layout(links, labels, notes=notes)
    marks = {b.name: b.marks for b in shown.boxes}
    assert marks["side"] == ("replay",)
    assert "not reached" not in marks["epilogue"]          # led to from a replay scene
    assert "not reached" in marks["orphan"]                # nothing leads here
    assert [(b.name, b.column, b.row) for b in shown.boxes] == \
        [(b.name, b.column, b.row) for b in plain.boxes]    # columns from start only
    assert {b.name: b.marks for b in plain.boxes}["side"] == ("not reached",)

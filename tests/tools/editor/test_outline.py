"""Studio kept current with F14–F27 (2026-11-02, user: keep Studio updated; ``06-acceptance.md``
AC-F45-51..55, 60): story-map notes, slot and minigame-argument completion, minigame Insert
snippets, the Outline tab, the check child's new name sources, and F20's ``flowchart``."""

import pytest

import engine.script  # noqa: F401  registers every statement and the docs table
from engine.script.pluginsigs import plugin_sigs
from engine.script.labelgraph import NOT_LINKS
from engine.script.statement_docs import docs_for
from engine.tools.editor.assist import candidates, completion_context, insert_menu
from engine.tools.editor.outline import outline
from engine.tools.editor.storymap import MARK_ENDING, label_notes, layout
from tests.tools.editor.canvas_counter import box_parts
from tests.tools.f45_games import check as run_check
from tests.tools.f45_games import studio as studio_s

LABELS = [("start", "script/main.vns", 4), ("river", "script/ch2.vns", 1),
          ("end", "script/ch2.vns", 8)]
NAMES = {
    "label": LABELS,
    "chapter": [("riverbank", "script/ch2.vns", 2)],
    "ending": [("good", "script/ch2.vns", 9)],
    "route": [("promise", "script/main.vns", 1)],
    "route_until": [("good", "script/main.vns", 1)],
    "tip": [("lanterns", "script/main.vns", 2)],
    "item": [("key", "script/main.vns", 3)],
    "category": [("Festival", "script/main.vns", 2)],
    "meter": [("trust", None, None)],
    "minigame": [("poem_game", None, None)],
    "minigame_arg": [("poem_game.words", None, 1), ("poem_game.rounds", None, None)],
    "minigame_use": [("poem_game", "script/ch2.vns", 3)],
    "flowchart_scene": [("By the River", "script/ch2.vns", 2)],
}


def test_ac_f45_51_story_map_notes():
    notes = label_notes(LABELS, NAMES)
    assert notes["river"].chapter == "riverbank" and notes["river"].minigames == ("poem_game",)
    assert notes["end"].endings == ("good",) and "start" not in notes
    m = layout([("start", "river", "jump", "script/main.vns", 5)], LABELS, notes=notes)
    end, river = m.boxes[m.index_of("end")], m.boxes[m.index_of("river")]
    assert MARK_ENDING in end.marks and MARK_ENDING not in river.marks
    assert (river.chapter, river.minigames) == ("riverbank", ("poem_game",))


@pytest.mark.parametrize(("line", "texts"), [
    ("unlock tip l", ["lanterns"]),
    ('lock route promise "P" until g', ["good"]),
    ("points t", ["trust"]),
    ("minigame po", ["poem_game"]),
    ("minigame poem_game ", ["rounds=", "words="]),
])
def test_ac_f45_52_slot_and_minigame_argument_completion(line, texts):
    ctx = completion_context(line, len(line))
    assert [c.text for c in candidates(ctx, NAMES)] == texts


def test_ac_f45_53_minigame_snippets_cover_required_arguments():
    from engine.minigames import bundled
    group = dict(insert_menu())["Minigames"]
    for plugin in (bundled.PoemGame, bundled.PresentEvidence, bundled.PhoneChat,
                   bundled.PuzzleRoom):
        required = [k for k, a in plugin.args.items() if repr(a) == "Arg()"]
        docs = [d for d in group if d.example.startswith(f"minigame {plugin.name} ")]
        assert len(docs) == 1, plugin.name
        assert all(f" {arg}=" in docs[0].example for arg in required), plugin.name


def test_ac_f45_54_outline_rows():
    rows = {r.text: r for r in outline(NAMES)}
    assert list(rows) == ["Chapters (1)", "Endings (1)", "Routes (1)", "Codex (2)",
                          "Meters (1)", "Minigames (1)", "Flowchart (1)", "Meta files (0)"]
    route = rows["Routes (1)"].children[0]
    assert (route.text, route.file, route.line) == ("promise", "script/main.vns", 1)
    assert [(c.text, c.file, c.line) for c in route.children] == [
        ("until good", "script/ch2.vns", 9)]
    festival = rows["Codex (2)"].children
    assert [(g.text, [c.text for c in g.children]) for g in festival] == [
        ("Festival (1)", ["tip lanterns"]), ("(no category) (1)", ["item key"])]


def test_ac_f45_55_check_child_story_names(tmp_path):
    game = studio_s(tmp_path)
    main = game / "script" / "main.vns"
    main.write_bytes(main.read_bytes().replace(
        b"label start:\n",
        b'lock route bridge "Bridge" until good\nlabel start:\n    chapter one "One"\n', 1)
        + b'label finale:\n    ending good "Good End" "Done"\n')
    names = dict(run_check(game).names)
    assert [(e.name, e.line) for e in names["chapter"]] == [("one", 6)]
    assert [e.name for e in names["ending"]] == ["good"]
    assert [(e.name, e.line) for e in names["route_until"]] == [("good", 4)]
    assert {e.name for e in names["minigame"]} >= {"poem_game", "puzzle_room"}
    assert "present_evidence.testimony" in {e.name for e in names["minigame_arg"]}
    text = 'class Mine:\n    name = "lantern_memory"\n    args = {"pairs": Arg(), "x": Arg(1)}\n'
    assert [(s.name, s.args) for s in plugin_sigs(text)] == [
        ("lantern_memory", (("pairs", True), ("x", False)))]


def test_ac_f45_60_flowchart_in_studio(tmp_path):
    assert [d.syntax for d in docs_for("flowchart")] == [
        'flowchart scene "title" [hidden] [no jump]', 'flowchart ["title"] [hidden] [no jump]',
        "flowchart omit", "flowchart forget [<label>]"]
    assert "flowchart" in NOT_LINKS
    line = "flowchart forget r"
    assert [c.text for c in candidates(completion_context(line, len(line)), NAMES)] == ["river"]
    (scenes,) = [r for r in outline(NAMES) if r.text == "Flowchart (1)"]
    assert [(c.text, c.file, c.line) for c in scenes.children] == [
        ("By the River", "script/ch2.vns", 2)]
    game = studio_s(tmp_path)
    main = game / "script" / "main.vns"
    main.write_bytes(main.read_bytes().replace(
        b"label start:\n", b'label start:\n    flowchart scene "Opening"\n', 1))
    names = dict(run_check(game).names)
    assert [(e.name, e.line) for e in names["flowchart_scene"]] == [("Opening", 5)]


def test_ac_f45_61_story_map_scene_titles():
    # F20 s2: a label's flowchart scene title rides on its story-map box (drawn after the
    # name, elided; the drawing row is in test_ac_f45_54_outline_tab_and_map_drawing).
    notes = label_notes(LABELS, NAMES)
    assert notes["river"].scene == "By the River" and notes["end"].scene is None
    m = layout([("start", "river", "jump", "script/main.vns", 5)], LABELS, notes=notes)
    assert m.boxes[m.index_of("river")].scene == "By the River"
    assert m.boxes[m.index_of("start")].scene is None


def test_ac_f45_71_flowchart_nodes_in_the_outline():
    from pathlib import Path
    game = Path(__file__).resolve().parents[3] / "game"
    nodes = dict(run_check(game).names)["flowchart_node"]
    rows = [(e.name, e.file) for e in nodes]
    assert rows[:3] == [("chapter Prologue", "script/main.vns"),
                        ("chapter Chapter 1: Wishes on the Water", "script/chapter1.vns"),
                        ("scene The Lantern Stall", "script/chapter1.vns")]
    assert ("choice How should the night end?", "script/routes/daichi.vns") in rows
    assert ("route Hana's Promise", "script/endings.vns") in rows
    assert ("scene The Promise (hidden, no jump)", "script/endings.vns") in rows
    assert ("ending True End: Hana's Promise (hidden)", "script/endings.vns") in rows
    (section,) = [r for r in outline({**NAMES, "flowchart_node": nodes})
                  if r.text.startswith("Flowchart")]
    assert section.text == f"Flowchart ({len(nodes)})"
    assert [(c.text, c.file, c.line) for c in section.children] == [
        (e.name, e.file, e.line) for e in nodes]


tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_window import studio, tab  # noqa: E402,F401


@pytest.mark.tk
def test_ac_f45_54_outline_tab_and_map_drawing(studio, studio_game, monkeypatch):
    ed = studio(studio_game, mapped=True)
    ed.story_map.set_pictures(False)                  # F45's boxes (3.1: "Compact")
    opened = []
    monkeypatch.setattr(ed.outline_view, "on_open", lambda f, n: opened.append((f, n)))
    ed.win.check_names = NAMES
    ed.press(ed.text, "<Control-Key-6>")                 # F47 W4: Game settings is Ctrl+4
    assert tab(ed) == "Outline"
    view = ed.outline_view
    assert "riverbank   script/ch2.vns:2" in view.texts()
    item = next(i for i, p in view.places.items() if p == ("script/ch2.vns", 9))
    view.tree.focus(item)
    view._open()
    assert opened == [("script/ch2.vns", 9)]
    ed.press(ed.text, "<Control-Key-2>")
    m, canvas = ed.story_map.layout, ed.map_canvas
    river = box_parts(ed.story_map, "river")
    assert "inner" in box_parts(ed.story_map, "end")
    assert canvas.itemcget(river["chapter"], "text") == "riverbank"
    # AC-F45-61: the scene title after the name, elided before the marks.
    shown = canvas.itemcget(river["scene"], "text")
    assert shown == "“By the River”" or (shown.startswith("“") and shown.endswith("…"))
    if m.boxes[m.index_of("river")].marks:
        assert canvas.bbox(river["scene"])[2] <= canvas.bbox(river["marks"])[0]
    assert "poem_game" in canvas.itemcget(river["minigame"], "text")

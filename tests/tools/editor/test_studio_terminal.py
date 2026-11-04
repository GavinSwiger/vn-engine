"""F56 step W2: the Terminal editor (Database ▸ Minigame data ▸ Terminals) and the Computer
terminal Minigame form, in a real Studio window: AC-F56-30, 31 (and AC-F56-28's + New)."""

import ast
from pathlib import Path

import pytest

from engine.minigames.bundled import terminal_rules
from engine.tools.editor import declplan, files, forms
from engine.tools.editor import minigamedata as mg

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from engine.tools.editor import minigameview as mv  # noqa: E402
from engine.tools.editor.terminalview import TerminalEditor  # noqa: E402
from tests.tools.editor.test_studio_database import helper  # noqa: E402,F401
from tests.tools.editor.test_studio_minigames import commit, open_minigames, text_of  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk

DB_REF = declplan.DATABASE_REF
DATA = '''
lock tip hana_password "Hana's notebook"
lock tip hana_diary "Hana's diary"
default hacked = False

define library_pc = {
    "prompt": "A:\\\\>",
    "commands": [
        {"command": "dir", "reply": "DIARY.TXT"},
        {"command": "login", "password": "lantern", "known_from": "hana_password", "reply": "Welcome."},
        {"command": "del grades.dat", "help": False, "ends": "goal", "reply": "1 file deleted."},
    ],
    }
'''
CALLS = '''
label library:
    minigame terminal data=library_pc screen="dark" into hacked
    return
'''


def pc_game(tmp_path: Path) -> Path:
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    db = game / "script" / "database.vns"
    db.write_text(db.read_text(encoding="utf-8") + DATA, encoding="utf-8")
    main = game / "script" / "main.vns"
    main.write_text(main.read_text(encoding="utf-8") + CALLS, encoding="utf-8")
    return game


def now(ed, name: str = "library_pc") -> dict:
    found = [ds for ds in mg.scan({DB_REF: text_of(ed, DB_REF)}) if ds.name == name]
    assert len(found) == 1
    return mg.value_of(mg.TERMINAL, found[0].model)


# --- AC-F56-30: the Terminal editor -------------------------------------------------------------

def test_ac_f56_30_terminal_editor(studio, tmp_path, helper, monkeypatch):
    ed = studio(pc_game(tmp_path), mapped=True)
    pane = open_minigames(ed)
    assert "Terminals" in [pane.tree.item(g, "text") for g in pane.tree.get_children()]
    pane.pick("library_pc")
    t = pane.editor
    assert isinstance(t, TerminalEditor)
    assert [t.tree.item(i, "values")[0] for i in t.tree.get_children()] == [
        "dir", "login", "del grades.dat"]
    assert [tuple(t.tree.item(i, "values")[1:]) for i in t.tree.get_children()] == [
        ("Always", "–"), ("Always", "–"), ("Never", "Goal")]
    commit(t.prompt, "C:\\>")
    assert now(ed)["prompt"] == "C:\\>"
    # The details of "login".
    t.selected = 1
    t.show_side()
    f = t.fields
    assert f["password"].var.get() == "lantern" and f["known_from"].var.get() == "hana_password"
    assert str(f["known_from"].widget.cget("state")) == "readonly"
    commit(f["reply"], "Welcome back, H. Sato.")
    assert now(ed)["commands"][1]["reply"] == "Welcome back, H. Sato."
    commit(t.fields["also"], "log in\nsign in")
    assert now(ed)["commands"][1]["also"] == ["log in", "sign in"]
    commit(t.fields["unlock"], "hana_diary")
    assert now(ed)["commands"][1]["unlock"] == "hana_diary"
    commit(t.fields["ends"], "Yes, goal not reached")
    assert now(ed)["commands"][1]["ends"] == "out"
    commit(t.fields["after"], "dir")
    assert now(ed)["commands"][1]["after"] == "dir"
    commit(t.fields["help"], "After a tip")
    assert now(ed)["commands"][1]["help"] in ("hana_password", "hana_diary")
    commit(t.fields["help"], "Never (secret)")
    assert now(ed)["commands"][1]["help"] is False
    commit(t.fields["password"], "")                       # no password: no tip for it
    assert "password" not in now(ed)["commands"][1] and "known_from" not in now(ed)["commands"][1]
    assert str(t.fields["known_from"].widget.cget("state")) == "disabled"
    # Add, reorder, remove.
    t.add()
    assert now(ed)["commands"][-1] == {"command": "new command"}
    t.move(-1)
    assert [c["command"] for c in now(ed)["commands"]][-2:] == ["new command", "del grades.dat"]
    t.remove()
    assert [c["command"] for c in now(ed)["commands"]] == ["dir", "login", "del grades.dat"]
    # A refused change stays on screen: "Not saved yet".
    text = text_of(ed, DB_REF)
    t.selected = 0
    t.show_side()
    commit(t.fields["command"], "help")
    assert t.pending and t.status.cget("text").startswith("Not saved yet: ")
    assert "built into the terminal" in t.status.cget("text") and text_of(ed, DB_REF) == text
    # + New: the starter (AC-F56-28).
    monkeypatch.setattr(mv, "ask_text", lambda *a, **k: ("my pc", False))
    store = mv.Store(ed.win)
    name = mv.new_data(ed.win, store, mg.TERMINAL)
    value = now(ed, name)
    assert value == {"welcome": "Type help to see what you can do.",
                     "commands": [{"command": "hello", "reply": "Hello."}]}
    assert terminal_rules.problem({"data": value}) is None


# --- AC-F56-31: the Computer terminal form -------------------------------------------------------

def test_ac_f56_31_terminal_form(studio, tmp_path, helper):
    ed = studio(pc_game(tmp_path), mapped=True)
    form = mv.MinigameDialog(ed.win, None)
    assert "Computer terminal" in form.game_box.cget("values")
    form.set_game("terminal")
    assert [f.label for f in form.form.fields] == ["Terminal", "Result", "Screen",
                                                   "Hide passwords"]
    assert list(form.widgets["data"].cget("values")) == ["library_pc"]
    assert list(form.widgets["result"].cget("values")) == [
        "Reached the goal (True or False)", "Details"]
    assert list(form.widgets["screen"].cget("values")) == ["Game colors", "Dark screen"]
    form.set("data", "library_pc")
    form.set("result", "Details")
    form.set("screen", "Dark screen")
    form.set("into", "hacked")
    form._changed()
    form._pick(0)
    line = form.result["line"]
    assert line == 'minigame terminal data=library_pc result="details" screen="dark" into hacked'
    edited = mv.MinigameDialog(ed.win, {"line": CALLS.split("\n")[2].strip()})
    assert edited.vars["screen"].get() == "Dark screen"
    args = {k: (ast.literal_eval(v) if k != "data" else None) for k, v in mg.read_call(line).args}
    assert terminal_rules.DEFAULTS.keys() >= {k for k in args if k != "data"}
    assert forms.missing_forms() == []

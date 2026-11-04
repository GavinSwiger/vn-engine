"""F55 step 3: Studio's Coded note form (AC-F55-14)."""

import ast

import pytest

from engine.minigames.bundled import cipher_rules
from engine.tools.editor import forms
from engine.tools.editor import minigamedata as mg

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from engine.tools.editor import minigameview as mv  # noqa: E402
from tests.tools.editor.test_studio_minigames import minigame_game  # noqa: E402
from tests.tools.editor.test_studio_database import helper  # noqa: E402,F401
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk

TIPS = '''
lock tip hana_code "Hana's notebook" in "Hana's code"
lock tip hana_letter "Hana's last letter"
'''


def test_ac_f55_14_coded_note_form(studio, tmp_path, helper):
    game = minigame_game(tmp_path)
    db = game / "script" / "database.vns"
    db.write_text(db.read_text(encoding="utf-8") + TIPS, encoding="utf-8")
    ed = studio(game, mapped=True)
    form = mv.MinigameDialog(ed.win, None)
    assert "Coded note" in form.game_box.cget("values")
    form.set_game("cipher_note")
    assert [f.label for f in form.form.fields] == [
        "Message", "Code", "Alphabet", "Shift by",
        "Swapped alphabet (empty: made from the message)", "Symbols",
        "Letters shown from the start", "Hints from tip category", "Tip unlocked when solved"]
    assert isinstance(form.widgets["message"], tk.Text)            # long text, 4 lines
    assert int(form.widgets["message"].cget("height")) == 4
    assert list(form.widgets["kind"].cget("values")) == ["Letter swap", "Shift", "Symbols"]
    assert list(form.widgets["hints"].cget("values")) == ["(none)", "Hana's code", "codex_tips"]
    assert list(form.widgets["tip"].cget("values")) == ["(none)", "hana_letter", "hana_code"]
    form.set("message", "MEET ME AT\nTHE OLD LANTERN STALL.")
    form.set("hints", "Hana's code")
    form.set("tip", "hana_letter")
    form.set("into", "poem_for")
    form._changed()
    form._pick(0)
    line = form.result["line"]
    assert line == ('minigame cipher_note message="MEET ME AT\\nTHE OLD LANTERN STALL." '
                    'hints="Hana\'s code" tip="hana_letter" into poem_for')
    args = {k: ast.literal_eval(v) for k, v in mg.read_call(line).args}
    assert cipher_rules.problem(args) is None                     # the game accepts it
    # Refusals show before OK, as the game words them.
    form = mv.MinigameDialog(ed.win, None)
    form.set_game("cipher_note")
    for name, text in (("message", "1234"), ("kind", "Shift"), ("shift", "40"),
                       ("revealed", "é")):
        form.set(name, text)
    form._changed()
    expected = cipher_rules.problem({"message": "1234"})
    assert form.line.cget("text") == expected
    for values, args in (
            ({"message": '"ABC"', "alphabet": '"AB C"'}, {"message": "ABC", "alphabet": "AB C"}),
            ({"message": '"ABC"', "kind": '"shift"', "shift": "40"},
             {"message": "ABC", "kind": "shift", "shift": 40}),
            ({"message": '"ABC"', "key": '"ABC"'}, {"message": "ABC", "key": "ABC"}),
            ({"message": '"ABC"', "kind": '"shift"', "revealed": '"A"'},
             {"message": "ABC", "kind": "shift", "revealed": "A"}),
            ({"message": '"ABC"', "revealed": '"é"'}, {"message": "ABC", "revealed": "é"}),
            ({"message": '""'}, {"message": ""})):
        assert mg.cipher_problem(values) == cipher_rules.problem(args), args
    assert forms.missing_forms() == []

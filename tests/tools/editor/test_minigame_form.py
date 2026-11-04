"""F53 step W3: Lock, Stay still and Hand game in Studio's Minigame form, in a real Studio
window on a new game: AC-F53-29 (the fields write and read the line), 30 (each label's
tooltip) and 32 (a code that doesn't fit the kind: the muted line and a refused OK)."""

import pytest

from engine.tools.editor import fieldhints
from engine.tools.editor import minigamedata as mg

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from engine.tools.editor import minigameview as mv  # noqa: E402
from engine.tools.editor.theme import THEME  # noqa: E402
from tests.tools.editor.test_studio_database import helper, sample_game  # noqa: E402,F401
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk

# game → [(arg, label, widget class name, shown default)]
FORMS = {
    "code_lock": [("kind", "Kind", "TCombobox", "keypad"), ("code", "Code", "TEntry", ""),
                  ("tries", "Tries allowed", "TSpinbox", "0"), ("hint", "Hint", "TEntry", ""),
                  ("hint_after", "Show the hint after", "TSpinbox", "3"),
                  ("leave", "Player can step back", "TCheckbutton", "True")],
    "stay_still": [("seconds", "Seconds", "TSpinbox", "10"),
                   ("line", "What they say", "TEntry", ""),
                   ("speaker", "Who says it", "TEntry", ""),
                   ("flinch_line", "What they say when you move", "TEntry", ""),
                   ("strict", "The first touch ends it", "TCheckbutton", "False"),
                   ("mouse", "Moving the mouse counts", "TCheckbutton", "False"),
                   ("ready", 'Show an "I\'m ready" button', "TCheckbutton", "True")],
    "hand_game": [("opponent", "Opponent's name", "TEntry", ""),
                  ("rounds", "Rounds", "TSpinbox", "3"),
                  ("mode", "How they play", "TCombobox", "fair")],
}
LINES = {
    "code_lock": ('minigame code_lock skippable code="0417" tries=3 '
                  'hint="The date on the diary." into safe_open',
                  {"code": "0417", "tries": "3", "hint": "The date on the diary.",
                   "into": "safe_open"}),
    "stay_still": ('minigame stay_still seconds=15 line="Don\'t touch anything. I\'ll know." '
                   'speaker="Monika" into flinches',
                   {"seconds": "15", "speaker": "Monika", "into": "flinches",
                    "line": "Don't touch anything. I'll know."}),
    "hand_game": ('minigame hand_game opponent="Hana" mode="cheat" into rps',
                  {"opponent": "Hana", "mode": "cheat", "into": "rps"}),
}


def _labels(dialog) -> dict[str, str]:
    """Each field's label text, by the field it labels (the grid's column 0)."""
    out = {}
    for child in dialog.grid.winfo_children():
        info = child.grid_info()
        if int(info.get("column", -1)) == 0 and child.winfo_class() == "TLabel":
            out[int(info["row"])] = str(child.cget("text"))
    return out


def test_ac_f53_29_quick_game_forms(studio, tmp_path, helper):
    ed = studio(sample_game(tmp_path), mapped=True)
    win = ed.win
    for game, fields in FORMS.items():
        dialog = mv.MinigameDialog(win, None)
        assert mg.game_title(game) in list(dialog.game_box.cget("values"))
        dialog.set_game(game)
        assert list(dialog.widgets) == [f[0] for f in fields] + ["into"], game
        labels = _labels(dialog)
        assert [labels[r] for r in range(len(fields))] == [f[1] for f in fields], game
        for name, _label, cls, shown in fields:
            widget = dialog.widgets[name]
            assert widget.winfo_class() == cls, (game, name)
            assert dialog.vars[name].get() == shown, (game, name)
        # Writing: the defaults are left out; reopening reads the line back.
        line, values = LINES[game]
        for name, text in values.items():
            dialog.set(name, text)
        dialog.skip_var.set(game == "code_lock")
        dialog._pick(0)
        assert dialog.result == {"line": line}, game
        again = mv.MinigameDialog(win, {"line": line})
        assert again.game == game
        for name, text in values.items():
            assert again.vars[name].get() == text, (game, name)
        again._pick(1)
    lock = mv.MinigameDialog(win, None)
    lock.set_game("code_lock")
    assert list(lock.widgets["kind"].cget("values")) == ["keypad", "dial"]
    assert str(lock.widgets["tries"].cget("to")) in ("99", "99.0")
    hand = mv.MinigameDialog(win, None)
    hand.set_game("hand_game")
    assert list(hand.widgets["mode"].cget("values")) == ["fair", "kind", "cheat", "sly"]


def test_ac_f53_30_label_tooltips(studio, tmp_path, helper):
    ed = studio(sample_game(tmp_path), mapped=True)
    for game in ("code_lock", "stay_still", "hand_game", "poem_game", "present_evidence",
                 "phone_chat", "puzzle_room", "heartbeat", "gift_giving"):
        dialog = mv.MinigameDialog(ed.win, None)
        dialog.set_game(game)
        fields = [f.name for f in mg.BUILTIN_FIELDS[game]]
        assert list(dialog.tips) == fields, game
        for name in fields:
            assert dialog.tips[name].text == fieldhints.minigame_hint(game, name), (game, name)
        dialog._pick(1)
    assert fieldhints.minigame_hint("code_lock", "code") == (
        "The code that opens it. Keypad: up to 12 digits. Dial: 3 to 6 digits or letters.")


def test_ac_f53_32_code_must_fit_the_kind(studio, tmp_path, helper, monkeypatch):
    errors: list[str] = []
    monkeypatch.setattr(mv, "show_error", lambda _parent, text: errors.append(text))
    ed = studio(sample_game(tmp_path), mapped=True)
    dialog = mv.MinigameDialog(ed.win, None)
    dialog.set_game("code_lock")
    assert str(dialog.line.cget("text")) == "Code is needed."     # required, as before
    dialog.set("code", "12a4")
    keypad = 'A keypad code is 1 to 12 digits from 0 to 9, but code is "12a4".'
    assert str(dialog.line.cget("text")) == keypad
    assert str(dialog.line.cget("foreground")) == THEME["muted"]
    dialog._pick(0)
    assert errors == [keypad] and dialog.result is None          # OK refused
    dialog.set("kind", "dial")
    dial = ('A dial code is 3 to 6 digits, or 3 to 6 letters from A to Z, but code is '
            '"12a4".')
    assert str(dialog.line.cget("text")) == dial
    dialog.set("code", "love")
    assert str(dialog.line.cget("text")) == 'minigame code_lock kind="dial" code="love"'
    assert str(dialog.line.cget("foreground")) == THEME["foreground"]
    dialog._pick(0)
    assert dialog.result == {"line": 'minigame code_lock kind="dial" code="love"'}

"""F52 step P1: the editing model (``ui/textedit.py``): AC-F52-06, 08, 09, 10, 11, 17."""

import ast
from pathlib import Path

import pytest

from engine.ui.textedit import Allowed, EditModel, Note

REPO = Path(__file__).resolve().parents[2]
FAMILY = "\U0001F468‍\U0001F469‍\U0001F467"      # one ZWJ grapheme
E_ACUTE = "é"                                         # e + combining acute


def test_pure_modules_import_no_pygame():
    for name in ("textedit", "kbpages", "textgeom"):
        path = REPO / "engine" / "ui" / f"{name}.py"
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        names += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not [n for n in names if n.split(".")[0] == "pygame"], name


# --- AC-F52-06: editing keys by grapheme ---------------------------------------------------------

@pytest.mark.parametrize(("start", "caret", "op", "text", "after_caret"), [
    (f"a{FAMILY}b", 2, "backspace", "ab", 1),
    (f"a{FAMILY}b", 1, "delete", "ab", 1),
    (f"x{E_ACUTE}y", 2, "backspace", "xy", 1),
    (f"x{E_ACUTE}y", 1, "delete", "xy", 1),
    (f"a{FAMILY}b", 1, "right", f"a{FAMILY}b", 2),
    (f"a{FAMILY}b", 2, "left", f"a{FAMILY}b", 1),
    ("abc", 0, "left", "abc", 0),                    # stays at the start
    ("abc", 3, "right", "abc", 3),                   # stays at the end
    ("abc", 2, "home", "abc", 0),
    ("abc", 0, "end", "abc", 3),
    ("abc", 0, "backspace", "abc", 0),
    ("abc", 3, "delete", "abc", 3),
])
def test_ac_f52_06_editing_keys_by_grapheme(start, caret, op, text, after_caret):
    m = EditModel(text=start)
    m.set_caret(caret)
    {"backspace": m.backspace, "delete": m.delete, "left": lambda: m.move(-1),
     "right": lambda: m.move(1), "home": m.home, "end": m.end}[op]()
    assert (m.text, m.caret) == (text, after_caret)
    # Typing a combining mark after its base joins it: one grapheme, caret after it.
    m = EditModel(text="")
    m.insert("e")
    m.insert("́")
    assert m.length == 1 and m.caret == 1


# --- AC-F52-08: max_length in graphemes, the 4× code-point cap -------------------------------------

@pytest.mark.parametrize(("max_length", "typed", "text", "note"), [
    (3, "abcd", "abc", Note.FULL),
    (3, "abc", "abc", None),
    (2, FAMILY * 2, FAMILY, Note.FULL),                # 5 code points each; cap 4 × 2 = 8
    (1, FAMILY, "", Note.FULL),                        # 5 code points > 4 × 1
    (2, "\U0001F600" * 3, "\U0001F600" * 2, Note.FULL),
    (3, "1a2345", "", Note.REFUSED),                   # digits below: the first note wins
])
def test_ac_f52_08_length_and_code_point_cap(max_length, typed, text, note):
    allowed = "digits" if typed == "1a2345" else "any"
    m = EditModel(max_length=max_length, allowed=allowed)
    assert m.insert(typed) is note
    assert m.text == (text or ("123" if allowed == "digits" else ""))
    for bad in (0, 201, 1.5, True):
        with pytest.raises(ValueError):
            EditModel(max_length=bad)


# --- AC-F52-09: presets and explicit strings ---------------------------------------------------------

@pytest.mark.parametrize(("allowed", "accepted", "refused"), [
    ("any", ["a", "Ж", "あ", "1", "!", " ", FAMILY], []),
    ("name", ["a", "Ж", "あ", "ア", " ", "-", "'", "’", ".", E_ACUTE], ["1", "!", "_"]),
    ("letters", ["a", "Ж", "α", "あ", " ", E_ACUTE], ["1", "-", "."]),
    ("digits", ["0", "9"], ["a", "１", " ", "-"]),
    ("letters_digits", ["a", "Ж", "7", " "], ["-", "!", "."]),
    ("ABCЖ", ["A", "Ж"], ["a", "D", "ж"]),
])
def test_ac_f52_09_presets_and_explicit(allowed, accepted, refused):
    a = Allowed(allowed)
    for g in accepted:
        assert a.accepts(g), (allowed, g)
        m = EditModel(allowed=allowed)
        assert m.insert(g) is None and m.text == g
    for g in refused:
        assert not a.accepts(g), (allowed, g)
        m = EditModel(allowed=allowed)
        assert m.insert(g) is Note.REFUSED and m.text == ""
    assert Allowed("AAB").chars == ("A", "B")


# --- AC-F52-10: cleaning -----------------------------------------------------------------------------

def test_ac_f52_10_cleaning():
    m = EditModel()
    m.insert("a\x00b​c d e‍e\x1bf")
    assert m.text == "abcde‍ef"
    m = EditModel()
    m.insert("x\ud800y")                       # a lone surrogate
    assert m.text == "x�y"
    m = EditModel()
    m.insert("a\tb")                           # Cc: a tab goes too
    assert m.text == "ab"
    m.set_text("q‮r")                      # set_text cleans as well
    assert m.text == "qr"


# --- AC-F52-11: case folding ----------------------------------------------------------------------

def test_ac_f52_11_case():
    m = EditModel(case="upper")
    m.insert("hana ß é")
    assert m.text == "HANA ß É"
    m = EditModel(case="lower")
    m.insert("ÀB")
    assert m.text == "àb"
    m = EditModel(case="upper", allowed="ABC")          # folded first, then checked
    assert m.insert("abd") is Note.REFUSED and m.text == "AB"
    with pytest.raises(ValueError):
        EditModel(case="title")


# --- AC-F52-17: the letter cell --------------------------------------------------------------------

def test_ac_f52_17_letter_cell():
    cell = EditModel(cell=True, allowed="ABC", case="upper")
    assert cell.max_length == 1
    cell.insert("b")
    assert cell.text == "B"
    cell.insert("c")                                    # typing replaces
    assert cell.text == "C"
    assert cell.insert("z") is Note.REFUSED and cell.text == "C"
    seen = []
    for _ in range(4):
        cell.turn(1)
        seen.append(cell.text)
    assert seen == ["", "A", "B", "C"]                  # through a blank, wrapping
    cell.turn(-1)
    assert cell.text == "B"
    cell.turn(-1)
    cell.turn(-1)
    assert cell.text == ""
    cell.turn(-1)
    assert cell.text == "C"                             # wraps backwards too
    assert cell.backspace() and cell.text == ""
    cell.insert("a")
    assert cell.delete() and cell.text == ""
    with pytest.raises(ValueError):
        EditModel(cell=True)                            # a cell needs an explicit string

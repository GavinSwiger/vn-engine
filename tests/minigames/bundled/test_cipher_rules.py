"""F55 step 1: the coded note's rules (``bundled/cipher_rules.py``): AC-F55-01 (the texts; E272
through the runtime is in ``test_cipher_note.py``), 02, 03, 10, 11 (the outcomes), 12 (the
W270 text; once and dev-only in ``test_cipher_note.py``)."""

import pytest

from engine.minigames.api import Outcome, StoryNames, unlock_tip
from engine.minigames.bundled import cipher_rules as rules

MSG = "MEET ME AT THE OLD LANTERN STALL."
STORY = StoryNames((), (), ("hana_code", "hana_letter"),
                   tip_categories=(("Hana's code", ("hana_code",)), ("codex_tips", ("x",))))
REFUSALS = [
    ({"message": "x" * 412}, "message must be text of 1 to 300 characters, but it has 412."),
    ({"message": ""}, "message must be text of 1 to 300 characters, but it is empty."),
    ({"message": "1234!"},
     "message has no letter of the alphabet, so there is nothing to decode."),
    ({"kind": "shfit"},
     'kind must be "letters", "shift" or "symbols", not "shfit". Did you mean "shift"?'),
    ({"kind": "rot13"}, 'kind must be "letters", "shift" or "symbols", not "rot13".'),
    ({"alphabet": "A" + "".join(chr(0x410 + i) for i in range(60))},
     "alphabet needs 2 to 60 different characters and no spaces, but it has 61."),
    ({"alphabet": "ABCA"},
     "alphabet needs 2 to 60 different characters and no spaces, but A is in it twice."),
    ({"alphabet": "AB CD"},
     "alphabet needs 2 to 60 different characters and no spaces, but it has a space."),
    ({"kind": "shift", "shift": 26},
     "shift must be a whole number from 1 to 25 (the alphabet has 26 letters), not 26."),
    ({"key": "BCDEFGHIJKLMNOPQRSTUVWXYZ"},
     "key must have 26 characters, one for each letter of the alphabet, but it has 25."),
    ({"key": "BCDEFGHIJKLMNOPRRSTUVWXYZA"},
     "key must use each letter of the alphabet once, but Q is missing."),
    ({"kind": "symbols", "key": "BCDEFGHIJKLMNOPQRSTUVWXYZA"},
     'key works only with kind="letters"; for symbols, the order of symbols is the key.'),
    ({"kind": "symbols", "symbols": "ΓΔΘΛΞΠΣΦΨΩБДЖЗИЙЛФЦЧ"},
     "symbols needs at least 26 different characters, one for each letter of the "
     "alphabet, but it has 20."),
    ({"revealed": "Eé"}, 'revealed can only hold letters of the alphabet, but "É" isn\'t one.'),
    ({"kind": "shift", "revealed": "E"},
     'revealed works only with kind="letters" or kind="symbols".'),
]


# --- AC-F55-01: every refusal ---------------------------------------------------------------

@pytest.mark.parametrize(("args", "reason"), REFUSALS)
def test_ac_f55_01_refusals(args, reason):
    assert rules.problem({"message": MSG, **args}) == reason
    assert rules.problem({"message": MSG}) is None
    assert rules.story_problem({"hints": "Hanas code"}, STORY) == (
        'hints names the tip category "Hanas code", but no tip is in it. Did you mean '
        '"Hana\'s code"?')
    assert rules.story_problem({"tip": "hana_leter"}, STORY) == (
        'tip "hana_leter" isn\'t a declared tip. Did you mean "hana_letter"?')
    assert rules.story_problem({"hints": "Hana's code", "tip": "hana_letter"}, STORY) is None


# --- AC-F55-02: the made key ----------------------------------------------------------------

def test_ac_f55_02_made_key():
    key = rules.make_key("letters", rules.ALPHABET, MSG)
    assert key == rules.make_key("letters", rules.ALPHABET, MSG)       # stable
    assert key == "QTYXZCJPMUSOIHNWVFBGLAEKDR"                          # the same everywhere
    from engine.runtime.dice import Pcg32                               # the engine's PCG32
    mine, theirs = rules._Pcg32(12345), Pcg32()
    theirs.seed(12345)
    assert [mine.below(1000) for _ in range(50)] == [theirs.below(1000) for _ in range(50)]
    assert sorted(key) == sorted(rules.ALPHABET)
    assert all(k != a for k, a in zip(key, rules.ALPHABET))              # no letter on itself
    assert key != rules.make_key("letters", rules.ALPHABET, MSG + "!")   # changes with it
    own = "BCDEFGHIJKLMNOPQRSTUVWXYZA"
    c = rules.cipher({"message": "ABC", "key": own})
    assert rules.encode(c) == "BCD"                                      # an explicit key
    for alphabet in ("AB", "ЖШЩ", "あいうえお"):
        made = rules.make_key("letters", alphabet, alphabet)
        assert all(k != a for k, a in zip(made, alphabet))


# --- AC-F55-03: encoding per kind -------------------------------------------------------------

def test_ac_f55_03_encoding():
    c = rules.cipher({"message": "Meet me, Hana ß!", "key": "BCDEFGHIJKLMNOPQRSTUVWXYZA"})
    assert c.message == "MEET ME, HANA ß!"                               # folded; ß kept
    assert rules.encode(c) == "NFFU NF, IBOB ß!"                          # untouched marks
    cyr = "АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    c = rules.cipher({"message": "яблоко", "kind": "shift", "alphabet": cyr, "shift": 3})
    assert rules.encode(c) == "ВДОСНС"                                    # Я wraps to В
    c = rules.cipher({"message": "BAD", "kind": "symbols"})
    assert rules.encode(c) == rules.SYMBOLS[1] + rules.SYMBOLS[0] + rules.SYMBOLS[3]
    assert rules.signs(c) == [rules.SYMBOLS[1], rules.SYMBOLS[0], rules.SYMBOLS[3]]


# --- AC-F55-10: layout --------------------------------------------------------------------------

@pytest.mark.parametrize(("size", "side", "columns", "lines"), [(28, 47, 18, 5), (42, 67, 13, 3)])
def test_ac_f55_10_layout(size, side, columns, lines):
    assert rules.cell_side(size) == side
    column = side + 4
    inner_w = rules.NOTE[2] - 2 * rules.NOTE_PAD
    assert int(inner_w // column) == columns
    line_h = rules.pitch(size) + 4 + side
    inner_h = rules.NOTE[3] - 2 * rules.NOTE_PAD
    assert rules.visible_lines(inner_h, line_h) == lines
    cols = rules.note_layout("AB CD\nE " + "F" * 30, "ABCDEF", column, inner_w)
    by = {c.index: c for c in cols}
    assert (by[0].x, by[1].x, by[3].x) == (0, column, 2.5 * column)    # a space: half
    assert by[6].line == 1 and by[6].x == 0                             # \n: a new line
    long_word = [c for c in cols if c.char == "F"]
    assert long_word[0].line == 2                                        # wrapped at the space
    assert long_word[columns].line == 3 and long_word[columns].x == 0    # broken at the end
    assert all(c.x + column <= inner_w + 1e-9 for c in cols)
    assert rules.note_layout("A.B", "AB", column, inner_w)[1].letter is False


# --- AC-F55-11: outcomes ----------------------------------------------------------------------

def test_ac_f55_11_outcomes():
    assert rules.fixed_outcome({"message": MSG, "tip": "hana_letter"}) == Outcome(
        True, (unlock_tip("hana_letter"),))
    assert rules.fixed_outcome({"message": MSG}) == Outcome(True)


# --- AC-F55-12: W270's text ------------------------------------------------------------------

def test_ac_f55_12_w270_text():
    assert rules.w270_text(["ж", "ш", "щ"]) == (
        "cipher_note: the game's fonts can't draw 3 characters of this note (ж, ш, щ), so "
        "they would show as boxes. Use a font that has them, or change the message, "
        "alphabet or symbols.")

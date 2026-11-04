"""The coded note's pure rules (F55 SPEC §2–§5).

Why this module exists: everything about ``cipher_note`` that needs no window lives here,
so it is tested directly and shared by the hooks (``check_args``, ``check_story``,
``outcome_for``) and the session (``cipher_note``):

- **Checks** (``problem``, ``story_problem``): §3's refusal texts, final.
- **The code.** ``letters``: each alphabet letter is swapped for another, never itself; with
  no ``key`` the swap is made from the message (``make_key``: a PCG32 seeded from the first
  8 bytes of SHA-256 of ``kind + "\\0" + alphabet + "\\0" + message``, a Fisher–Yates
  shuffle, and a letter left on itself swapped with its neighbour), so the same note gives
  the same key on every machine. ``shift``: every letter moves ``shift`` places, wrapping.
  ``symbols``: letter *i* is written as ``symbols[i]``.
- **The note.** ``upper`` (per character, when the result is one character), ``signs`` (each
  coded sign and the letter it stands for), and ``Board``: the player's guesses, one letter
  per sign, revealed signs fixed, and the solved check.
- **Layout** (``note_layout``): columns (cell side + 4), half a column for a space, words
  wrapped at spaces (a word longer than a line breaks at its end), ``\\n`` a new line.
- ``fixed_outcome``: test and skipped are ``True`` with ``tip`` unlocked. ``w270_text``.

The PCG32 here is the engine's (``runtime.dice.Pcg32``: XSH-RR, the reference increment),
written out because bundled rules import only the API and F10's kit.
Pure: no clock, no I/O, no story randomness.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from engine.minigames.api import Outcome, StoryNames, closest, unlock_tip
from engine.minigames.bundled.rule_text import kind_words, value_echo
from engine.ui.layouts import pitch

KINDS: Final = ("letters", "shift", "symbols")
ALPHABET: Final = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SYMBOLS: Final = "ΓΔΘΛΞΠΣΦΨΩБДЖЗИЙЛФЦЧШЩЪЫЬЭЮЯξψ"
MESSAGE_MAX: Final = 300
ALPHABET_RANGE: Final = (2, 60)
SYMBOLS_MAX: Final = 120
DEFAULTS: Final = {"kind": "letters", "alphabet": ALPHABET, "shift": 3, "key": None,
                   "symbols": SYMBOLS, "revealed": "", "hints": None, "tip": None}
REQUIRED_ARGS: Final = ("message",)

# Layout (§4.1), canvas units.
NOTE: Final = (24, 24, 976, 598)            # the note panel x 24–1000, y 24–622
NOTE_PAD: Final = 24
SIDE_X: Final = 1024
SIDE_W: Final = 232
SIDE_GAP: Final = 12
COLUMN_EXTRA: Final = 4                     # a column is the cell side + 4
SIGN_GAP: Final = 4                         # the cell 4 below the sign
LINE_GAP: Final = 16
CELL_MIN: Final = 40
CELL_PAD: Final = 8

_MASK32: Final = 0xFFFF_FFFF
_MASK64: Final = 0xFFFF_FFFF_FFFF_FFFF
_MULT: Final = 6364136223846793005
_INC: Final = 1442695040888963407
_LISTED: Final = 10


# --- PCG32 (the engine's runtime.dice.Pcg32) --------------------------------------------------

class _Pcg32:
    def __init__(self, seed: int) -> None:
        self.state = 0
        self.next32()
        self.state = (self.state + seed) & _MASK64
        self.next32()

    def next32(self) -> int:
        old = self.state
        self.state = (old * _MULT + _INC) & _MASK64
        shifted = (((old >> 18) ^ old) >> 27) & _MASK32
        rot = old >> 59
        return ((shifted >> rot) | (shifted << ((-rot) & 31))) & _MASK32

    def below(self, n: int) -> int:
        bits = n.bit_length()
        words = (bits + 31) // 32
        drop = 32 * words - bits
        while True:
            r = 0
            for _ in range(words):
                r = (r << 32) | self.next32()
            r >>= drop
            if r < n:
                return r


# --- Text ------------------------------------------------------------------------------------

def upper(text: str) -> str:
    """Each character upper-cased when that is one character (PR-F55-02)."""
    out = []
    for ch in text:
        up = ch.upper()
        out.append(up if len(up) == 1 else ch)
    return "".join(out)


def _distinct(text: str) -> list[str]:
    seen: list[str] = []
    for ch in text:
        if ch not in seen:
            seen.append(ch)
    return seen


# --- Checks (§3) -----------------------------------------------------------------------------

def _get(args: dict, name: str) -> object:
    return args.get(name, DEFAULTS.get(name))


def problem(args: dict) -> str | None:
    """The first refused argument's reason (§3's texts), or None. No side effects."""
    message = args.get("message")
    if type(message) is not str:
        return f"message must be text of 1 to 300 characters, but it is {kind_words(message)}."
    if message == "":
        return "message must be text of 1 to 300 characters, but it is empty."
    if len(message) > MESSAGE_MAX:
        return f"message must be text of 1 to 300 characters, but it has {len(message)}."
    kind = _get(args, "kind")
    if type(kind) is not str or kind not in KINDS:
        text = f'kind must be "letters", "shift" or "symbols", not {value_echo(kind)}.'
        near = closest(kind, KINDS) if type(kind) is str else None
        return text + (f' Did you mean "{near}"?' if near is not None else "")
    alphabet = _get(args, "alphabet")
    lo, hi = ALPHABET_RANGE
    head = f"alphabet needs {lo} to {hi} different characters and no spaces, but "
    if type(alphabet) is not str:
        return head + f"it is {kind_words(alphabet)}."
    if any(ch.isspace() for ch in alphabet):
        return head + "it has a space."
    if not lo <= len(alphabet) <= hi:
        return head + f"it has {len(alphabet)}."
    for ch in alphabet:
        if alphabet.count(ch) > 1:
            return head + f"{ch} is in it twice."
    if not any(ch in alphabet for ch in upper(message)):
        return "message has no letter of the alphabet, so there is nothing to decode."
    n = len(alphabet)
    if kind == "shift":
        shift = _get(args, "shift")
        if type(shift) is not int or not 1 <= shift <= n - 1:
            return (f"shift must be a whole number from 1 to {n - 1} (the alphabet has {n} "
                    f"letters), not {value_echo(shift)}.")
    key = _get(args, "key")
    if key is not None:
        if kind != "letters":
            return ('key works only with kind="letters"; for symbols, the order of symbols '
                    "is the key.")
        if type(key) is not str or len(key) != n:
            have = len(key) if type(key) is str else kind_words(key)
            return (f"key must have {n} characters, one for each letter of the alphabet, but "
                    f"it has {have}.")
        for ch in alphabet:
            if ch not in key:
                return f"key must use each letter of the alphabet once, but {ch} is missing."
    if kind == "symbols":
        symbols = _get(args, "symbols")
        if type(symbols) is str and len(symbols) > SYMBOLS_MAX:
            return (f"symbols can have at most {SYMBOLS_MAX} characters, but it has "
                    f"{len(symbols)}.")
        count = len(_distinct(symbols)) if type(symbols) is str else 0
        if count < n:
            return (f"symbols needs at least {n} different characters, one for each letter "
                    f"of the alphabet, but it has {count}.")
    revealed = _get(args, "revealed")
    if revealed is None:
        revealed = ""
    if type(revealed) is not str:
        return f"revealed can only hold letters of the alphabet, but it is {kind_words(revealed)}."
    if revealed:
        if kind == "shift":
            return 'revealed works only with kind="letters" or kind="symbols".'
        for ch in upper(revealed):
            if ch not in alphabet:
                return f'revealed can only hold letters of the alphabet, but "{ch}" isn\'t one.'
    for name in ("hints", "tip"):
        value = _get(args, name)
        if value is not None and (type(value) is not str or value == ""):
            what = "a tip category's name" if name == "hints" else "a tip's name"
            return f"{name} must be {what} or None, not {value_echo(value)}."
    return None


def story_problem(args: dict, story: StoryNames) -> str | None:
    """The tip category and tip names against the story's declarations (§3), or None."""
    hints = args.get("hints")
    if type(hints) is str:
        categories = {key: tips for key, tips in story.tip_categories}
        if not categories.get(hints):
            text = f'hints names the tip category "{hints}", but no tip is in it.'
            near = closest(hints, [k for k, tips in story.tip_categories if tips])
            return text + (f' Did you mean "{near}"?' if near is not None else "")
    tip = args.get("tip")
    if type(tip) is str and tip not in story.tips:
        near = closest(tip, story.tips)
        return (f'tip "{tip}" isn\'t a declared tip.'
                + (f' Did you mean "{near}"?' if near is not None else ""))
    return None


def fixed_outcome(args: dict) -> Outcome:
    """Test and skipped: solved (``True``), with ``tip`` unlocked."""
    tip = args.get("tip")
    return Outcome(True, (unlock_tip(tip),) if type(tip) is str else ())


# --- The code (§5) ---------------------------------------------------------------------------

def make_key(kind: str, alphabet: str, message: str) -> str:
    """The letter swap made from the message: the coded letter for each alphabet letter, in
    order; never a letter on itself (an alphabet of one letter can't swap)."""
    digest = hashlib.sha256((kind + "\0" + alphabet + "\0" + message).encode("utf-8")).digest()
    rng = _Pcg32(int.from_bytes(digest[:8], "big"))
    letters = list(alphabet)
    for i in range(len(letters) - 1, 0, -1):
        j = rng.below(i + 1)
        letters[i], letters[j] = letters[j], letters[i]
    n = len(letters)
    for i in range(n):
        if letters[i] == alphabet[i] and n > 1:
            k = (i + 1) % n
            letters[i], letters[k] = letters[k], letters[i]
    return "".join(letters)


@dataclass(frozen=True)
class Cipher:
    """A checked note: the upper-cased message, the alphabet, and how each letter is coded."""
    kind: str
    message: str
    alphabet: str
    coded: dict                     # plain letter → its sign
    shift: int = 0

    def sign(self, ch: str) -> str | None:
        """The sign written for ``ch`` (a plain character), or None (shown as written)."""
        return self.coded.get(ch)

    def letter_of(self, sign: str) -> str | None:
        for plain, coded in self.coded.items():
            if coded == sign:
                return plain
        return None


def cipher(args: dict) -> Cipher:
    """The note of checked ``args`` (``problem`` returned None)."""
    kind = _get(args, "kind")
    alphabet = _get(args, "alphabet")
    message = upper(args["message"])
    n = len(alphabet)
    if kind == "shift":
        shift = _get(args, "shift")
        coded = {alphabet[i]: alphabet[(i + shift) % n] for i in range(n)}
        return Cipher(kind, message, alphabet, coded, shift)
    if kind == "symbols":
        symbols = _distinct(_get(args, "symbols"))
        return Cipher(kind, message, alphabet, {alphabet[i]: symbols[i] for i in range(n)})
    key = _get(args, "key") or make_key(kind, alphabet, args["message"])
    return Cipher(kind, message, alphabet, {alphabet[i]: key[i] for i in range(n)})


def encode(c: Cipher) -> str:
    """The note as written: each alphabet letter coded, everything else as it is."""
    return "".join(c.sign(ch) or ch for ch in c.message)


def signs(c: Cipher) -> list[str]:
    """The distinct signs of the note, in reading order."""
    return _distinct([c.coded[ch] for ch in c.message if ch in c.coded])


class Board:
    """The player's guesses: sign → letter, one letter per sign (PR-F55-03). Revealed signs
    start right and never change. Shift: ``dial`` is the letter the first alphabet letter is
    written as (None: not set)."""

    def __init__(self, c: Cipher, revealed: str = "") -> None:
        self.c = c
        self.answer = {c.coded[p]: p for p in c.alphabet if p in c.message}
        self.fixed = {c.coded[p] for p in upper(revealed) if p in self.answer.values()
                      and c.kind != "shift"} if revealed else set()
        self.guesses: dict[str, str] = {s: self.answer[s] for s in self.fixed}
        self.dial: str | None = None

    def put(self, sign: str, letter: str) -> "set[str]":
        """``letter`` on ``sign``, taken off any other (unfixed) sign. The changed signs."""
        if sign in self.fixed:
            return set()
        changed = {sign}
        if letter:
            for other, held in list(self.guesses.items()):
                if held == letter and other != sign and other not in self.fixed:
                    del self.guesses[other]
                    changed.add(other)
            self.guesses[sign] = letter
        else:
            self.guesses.pop(sign, None)
        return changed

    def clear(self, sign: str) -> "set[str]":
        return self.put(sign, "")

    def guess(self, sign: str) -> str:
        return self.guesses.get(sign, "")

    def decoded(self, sign: str) -> str:
        """Shift kind: the letter ``sign`` reads as under the dial ("" before it is set)."""
        a = self.c.alphabet
        if self.dial is None or sign not in a or self.dial not in a:
            return ""
        return a[(a.index(sign) - a.index(self.dial)) % len(a)]

    def solved(self) -> bool:
        if self.c.kind == "shift":
            a = self.c.alphabet
            return self.dial is not None and a.index(self.dial) == self.c.shift
        return all(self.guesses.get(s) == p for s, p in self.answer.items())


# --- Layout (§4.1) ---------------------------------------------------------------------------

def cell_side(size: int) -> int:
    """F52's letter cell: max(40, pitch + 8) at the cells' (scaled) text size."""
    return max(CELL_MIN, pitch(size) + CELL_PAD)


@dataclass(frozen=True)
class Column:
    """One character of the note: its index in the message, the character, its line and its
    x offset from the line's start; ``letter`` when it has a cell."""
    index: int
    char: str
    line: int
    x: float
    letter: bool


def note_layout(message: str, alphabet: str, column: float, width: float) -> list[Column]:
    """Columns of ``column`` width (a space: half), lines ``width`` wide, words wrapped at
    spaces, a word longer than a line broken at its end, ``\\n`` a new line."""
    out: list[Column] = []
    line, x = 0, 0.0
    i, n = 0, len(message)
    while i < n:
        ch = message[i]
        if ch == "\n":
            line, x = line + 1, 0.0
            i += 1
            continue
        if ch == " ":
            if x > 0:
                x += column / 2
            i += 1
            continue
        j = i
        while j < n and message[j] not in " \n":
            j += 1
        word_w = (j - i) * column
        if x > 0 and x + word_w > width + 1e-9:
            line, x = line + 1, 0.0
        for k in range(i, j):
            if x > 0 and x + column > width + 1e-9:
                line, x = line + 1, 0.0
            out.append(Column(k, message[k], line, x, message[k] in alphabet))
            x += column
        i = j
    return out


def visible_lines(inner_h: float, line_h: float) -> int:
    """Lines that fit ``inner_h``: ``line_h`` each, 16 apart."""
    return max(1, int((inner_h + LINE_GAP) // (line_h + LINE_GAP)))


def w270_text(chars: Sequence[str]) -> str:
    """W270 (dev): characters of the note the game's fonts can't draw."""
    count = len(chars)
    shown = ", ".join(chars[:_LISTED]) + (", …" if count > _LISTED else "")
    noun = "character" if count == 1 else "characters"
    return (f"cipher_note: the game's fonts can't draw {count} {noun} of this note "
            f"({shown}), so they would show as boxes. Use a font that has them, or change the "
            "message, alphabet or symbols.")


__all__ = ["ALPHABET", "Board", "Cipher", "Column", "DEFAULTS", "KINDS", "SYMBOLS", "cell_side",
           "cipher", "encode", "fixed_outcome", "make_key", "note_layout", "problem", "signs",
           "story_problem", "upper", "visible_lines", "w270_text"]

"""The text field's editing model: text, caret, composition, limits (F52 ``04`` §3, P1).

Why this module exists: every text field (F52's ``TextField``, F55's letter cells, F56's
prompt line, ``ask_text``) edits the same way, and the rules are easiest to trust as pure
code with no pygame and no drawing:

- **Graphemes.** The caret is a grapheme index (``core/graphemes``), so Left, Right,
  Backspace and Delete never split a ZWJ emoji or an "e" and its combining accent. After
  every change the whole text is segmented again, so a combining mark typed after its base
  joins it.
- **Cleaning** (PR-F52-07): all input goes through F11's save-text rule
  (``runtime.minigame.clean_text``): controls, format characters except ZWJ, and line and
  paragraph separators go; a lone surrogate becomes U+FFFD.
- **Case** (PR-F52-08): ``"upper"``/``"lower"`` folds each added grapheme, unless the result
  is more than one grapheme ("ß" stays "ß").
- **Allowed** (§6.6): a preset or an explicit string; a refused grapheme isn't added and
  gives the REFUSED note.
- **Limits** (PR-F52-06): ``max_length`` graphemes (1–200), and never more than
  4 × ``max_length`` code points. Input that doesn't fit is cut at a grapheme boundary and
  gives the FULL note. With several notes, the first one wins.
- **Composition** (PR-F52-03): the IME's unfinished text sits at the caret, is neither
  counted nor checked, and is replaced by the commit (``insert``).
- **Paste** (PR-F52-09): the first 4,000 code points, then the first line, then as typed.
- **Letter cell** (PR-F52-13): one grapheme; typing replaces it; ``turn`` steps through a
  blank and then the explicit ``allowed`` characters in order, wrapping.
"""

import unicodedata
from collections.abc import Sequence
from enum import Enum
from typing import Final

from engine.core.graphemes import graphemes
from engine.runtime.minigame import clean_text

MAX_LENGTH_RANGE: Final = (1, 200)
DEFAULT_MAX_LENGTH: Final = 40
CODE_POINTS_PER_GRAPHEME: Final = 4         # the code-point cap: 4 × max_length
PASTE_MAX: Final = 4_000                    # code points read from the clipboard
COMPOSITION_MAX: Final = 200                # code points of IME composition kept
MASK: Final = "•"                      # "•", one per committed grapheme
PRESETS: Final = ("any", "name", "letters", "digits", "letters_digits")
CASES: Final = (None, "upper", "lower")
_INPUT_MAX: Final = 100_000                 # cleaning stops here (paste is cut earlier)
_NAME_MARKS: Final = frozenset(" -'’.")
_DIGITS: Final = frozenset("0123456789")


class Note(Enum):
    """A note shown under the field; the value is its ``[words]`` key (§8)."""
    FULL = "text_entry_full"
    REFUSED = "text_entry_refused"


def _letter_or_mark(char: str) -> bool:
    return unicodedata.category(char)[0] in ("L", "M")


class Allowed:
    """What a field accepts (§6.6): a preset name, or an explicit string of characters.
    ``accepts(g)`` checks one grapheme; ``chars`` is the explicit string's graphemes in
    order (None for a preset)."""

    __slots__ = ("preset", "chars", "_set")

    def __init__(self, spec: str = "any") -> None:
        if type(spec) is not str or not spec:
            raise ValueError("allowed must be a preset name or a non-empty string")
        if spec in PRESETS:
            self.preset: str | None = spec
            self.chars: tuple[str, ...] | None = None
            self._set: frozenset[str] = frozenset()
        else:
            self.preset = None
            seen: dict[str, None] = {}
            for g in graphemes(clean_text(spec, _INPUT_MAX)):
                seen.setdefault(g, None)
            if not seen:
                raise ValueError("allowed must hold at least one character")
            self.chars = tuple(seen)
            self._set = frozenset(seen)

    @property
    def explicit(self) -> bool:
        return self.preset is None

    def accepts(self, g: str) -> bool:
        if not g:
            return False
        preset = self.preset
        if preset is None:
            return g in self._set
        if preset == "any":
            return True
        if preset == "digits":
            return all(c in _DIGITS for c in g)
        if preset == "name":
            return all(_letter_or_mark(c) or c in _NAME_MARKS for c in g)
        if preset == "letters":
            return all(_letter_or_mark(c) or c == " " for c in g)
        return all(_letter_or_mark(c) or c in _DIGITS or c == " " for c in g)   # letters_digits

    def __repr__(self) -> str:
        return f"Allowed({self.preset!r})" if self.preset else f"Allowed({''.join(self.chars)!r})"


def fold(g: str, case: str | None) -> str:
    """``g`` in ``case`` when that is still one grapheme (PR-F52-08), else ``g``."""
    if case is None:
        return g
    folded = g.upper() if case == "upper" else g.lower()
    return folded if len(graphemes(folded)) == 1 else g


def first_line(text: str) -> str:
    """Everything before the first line break (``\\n``, ``\\r``, U+2028, U+2029, …)."""
    lines = text.splitlines()
    return lines[0] if lines else ""


class EditModel:
    """One field's text (module docstring). ``caret`` is a grapheme index into ``text``."""

    def __init__(self, *, text: str = "", max_length: int = DEFAULT_MAX_LENGTH,
                 allowed: "Allowed | str" = "any", case: str | None = None,
                 cell: bool = False) -> None:
        if type(max_length) is not int or not MAX_LENGTH_RANGE[0] <= max_length \
                <= MAX_LENGTH_RANGE[1]:
            raise ValueError(f"max_length must be a whole number from 1 to 200, "
                             f"not {max_length!r}")
        if case not in CASES:
            raise ValueError(f'case must be None, "upper" or "lower", not {case!r}')
        self.allowed = allowed if isinstance(allowed, Allowed) else Allowed(allowed)
        if cell and not self.allowed.explicit:
            raise ValueError("a letter cell needs an explicit allowed string")
        self.cell = cell
        self.max_length = 1 if cell else max_length
        self.case = case
        self._g: list[str] = []
        self.caret = 0
        self.composition = ""
        self.set_text(text)

    # -- reading --

    @property
    def text(self) -> str:
        return "".join(self._g)

    @property
    def length(self) -> int:
        """Committed graphemes."""
        return len(self._g)

    @property
    def composing(self) -> bool:
        return bool(self.composition)

    def graphemes(self) -> list[str]:
        return list(self._g)

    def display(self, *, mask: bool = False) -> tuple[str, str, str]:
        """(before the caret, composition, after the caret) as drawn: with ``mask`` each
        committed grapheme is "•"; the composition is never masked (PR-F52-10)."""
        before, after = self._g[:self.caret], self._g[self.caret:]
        if mask:
            return MASK * len(before), self.composition, MASK * len(after)
        return "".join(before), self.composition, "".join(after)

    # -- editing --

    def set_text(self, text: str) -> None:
        """Replace the text (the program's, not the player's): cleaned, folded, filtered and
        cut silently; the caret goes to the end; the composition is dropped."""
        self._g = []
        self.caret = 0
        self.composition = ""
        if text:
            self._add(text)
        self.caret = len(self._g)

    def insert(self, text: str) -> Note | None:
        """Typed text (a ``TEXTINPUT`` commit) at the caret; ends any composition. A cell's
        accepted grapheme replaces its letter. Returns the first note, or None."""
        self.composition = ""
        if self.cell:
            return self._replace_cell(text)
        return self._add(text)

    def paste(self, text: str) -> Note | None:
        """PR-F52-09: the first 4,000 code points, the first line, then as typed."""
        return self.insert(first_line(text[:PASTE_MAX]))

    def compose(self, text: str) -> None:
        """The IME's unfinished text (``TEXTEDITING``): shown at the caret, not counted."""
        self.composition = clean_text(text, COMPOSITION_MAX)

    def drop_composition(self) -> None:
        self.composition = ""

    def backspace(self) -> bool:
        """Remove the grapheme before the caret (a cell: clear it). True when it changed."""
        if self.cell:
            return self._clear_cell()
        if self.caret == 0:
            return False
        del self._g[self.caret - 1]
        self.caret -= 1
        self._resegment(self.caret)
        return True

    def delete(self) -> bool:
        """Remove the grapheme after the caret (a cell: clear it). True when it changed."""
        if self.cell:
            return self._clear_cell()
        if self.caret >= len(self._g):
            return False
        del self._g[self.caret]
        self._resegment(self.caret)
        return True

    def move(self, step: int) -> bool:
        """The caret by ``step`` graphemes, staying inside the text."""
        target = max(0, min(len(self._g), self.caret + step))
        moved = target != self.caret
        self.caret = target
        return moved

    def home(self) -> bool:
        moved = self.caret != 0
        self.caret = 0
        return moved

    def end(self) -> bool:
        moved = self.caret != len(self._g)
        self.caret = len(self._g)
        return moved

    def set_caret(self, index: int) -> None:
        self.caret = max(0, min(len(self._g), index))

    def turn(self, step: int) -> bool:
        """A cell's Up (``-1``) / Down (``+1``): through a blank, then ``allowed`` in order,
        wrapping. True when the letter changed (always, unless ``allowed`` is empty)."""
        if not self.cell:
            return False
        ring: Sequence[str] = ("", *(self.allowed.chars or ()))
        current = self.text
        index = ring.index(current) if current in ring else 0
        letter = ring[(index + step) % len(ring)]
        self._g = [letter] if letter else []
        self.caret = len(self._g)
        return letter != current

    # -- internals --

    def _clear_cell(self) -> bool:
        changed = bool(self._g)
        self._g = []
        self.caret = 0
        return changed

    def _replace_cell(self, text: str) -> Note | None:
        note: Note | None = None
        last: str | None = None
        for g in graphemes(clean_text(text, _INPUT_MAX)):
            g = fold(g, self.case)
            if not self.allowed.accepts(g):
                note = note or Note.REFUSED
                continue
            last = g
        if last is not None:
            self._g = [last]
            self.caret = 1
        return note

    def _add(self, text: str) -> Note | None:
        """Insert ``text``'s accepted graphemes at the caret, up to the limits."""
        note: Note | None = None
        cap = CODE_POINTS_PER_GRAPHEME * self.max_length
        before, after = self._g[:self.caret], self._g[self.caret:]
        for g in graphemes(clean_text(text, _INPUT_MAX)):
            g = fold(g, self.case)
            if not self.allowed.accepts(g):
                note = note or Note.REFUSED
                continue
            trial = graphemes("".join(before) + g)
            joined = graphemes("".join(trial) + "".join(after))
            if len(joined) > self.max_length or sum(map(len, joined)) > cap:
                note = note or Note.FULL
                break
            before = trial
        self._g = graphemes("".join(before) + "".join(after))
        self.caret = len(before)
        return note

    def _resegment(self, caret: int) -> None:
        """Segment again after a removal (a mark left alone may now join a neighbour)."""
        before = "".join(self._g[:caret])
        self._g = graphemes("".join(self._g))
        self.caret = min(len(self._g), len(graphemes(before)))


__all__ = ["CASES", "COMPOSITION_MAX", "DEFAULT_MAX_LENGTH", "MASK", "MAX_LENGTH_RANGE",
           "PASTE_MAX", "PRESETS", "Allowed", "EditModel", "Note", "first_line", "fold"]

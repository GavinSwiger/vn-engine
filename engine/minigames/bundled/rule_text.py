"""Text helpers shared by the bundled minigames' rules (F25 ``04`` §2, F25 ``07`` I-5).

Why this module exists: every bundled minigame (F24 poem, F25 present evidence, F26 phone,
F27) echoes author values in its refusal texts the same way and applies one rule to every
piece of author text it shows on one line. The helpers moved here from F24's ``poem_rules``
without changing their behavior, so F24's texts are unchanged.

- ``cut(text)``: 30 code points, then "…".
- ``quoted(text)``: cut, each line break or hidden character shown as a space, in double
  quotes.
- ``value_echo(v)``: an echoed argument value; text as ``quoted``, anything else as its
  ``repr``, cut.
- ``kind_words(v)``: "a dictionary", "a list", "text", "a whole number", "a decimal number",
  and True, False, and None as written (F24 ``04`` §5.1 step 1).
- ``hidden(ch)``: a line break or hidden character (F24 ``07`` I-8: ``Cc``, ``Cf`` except
  ZWJ, ``Cs``, ``Co``, ``Zl``, ``Zp``).
- ``line_problem(text, lo, hi, *, breaks=0)``: the shared text rule. It returns a form key
  (``LINE_FORMS``), never a sentence; each rules module maps the keys to its own sentences.
- F53 §3.4's shared refusal forms, also used by F54: ``whole_problem`` (N), ``flag_problem``
  (B), ``choice_problem`` (C, with the caller's did-you-mean), ``text_problem`` (T, from
  ``line_problem``'s keys), and ``fill(word, **values)`` (replaces each literal ``{key}``).

Pure: imports only the stdlib (AC-F25-01).
"""

import unicodedata
from collections.abc import Iterator
from typing import Final

ECHO_MAX: Final = 30                 # code points of an echoed word, name, or value
# F24 07 I-8: line breaks and hidden characters. ZWJ (U+200D) is allowed, so emoji sequences
# pass; RTL marks and soft hyphens (other Cf) are still refused.
_HIDDEN_CATEGORIES: Final = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})
_ZWJ: Final = "‍"
# line_problem's form keys, in the order they are tested (F25 07 I-5).
LINE_FORMS: Final = ("not text", "empty", "length", "breaks", "hidden", "edge")


def cut(text: str) -> str:
    """``text`` cut to 30 code points, then "…"."""
    return text if len(text) <= ECHO_MAX else text[:ECHO_MAX] + "…"


def hidden(ch: str) -> bool:
    """Whether one character is a line break or hidden character (F24 ``07`` I-8)."""
    return ch != _ZWJ and unicodedata.category(ch) in _HIDDEN_CATEGORIES


def _visible(text: str) -> str:
    """``text`` cut, with each line break or hidden character shown as a space."""
    text = cut(text)
    return "".join(" " if hidden(ch) else ch for ch in text)


def quoted(text: str) -> str:
    """An echoed text: cut, hidden characters shown as spaces, in double quotes."""
    return f'"{_visible(text)}"'


def _repr_pieces(v: object) -> Iterator[str]:
    t = type(v)
    if t is str:
        yield repr(v[:ECHO_MAX + 1])
    elif t is int:
        try:
            yield str(v)
        except ValueError:                   # more digits than Python will print
            yield "a very large number"
    elif t is list:
        yield "["
        for i, x in enumerate(v):           # type: ignore[arg-type]
            if i:
                yield ", "
            yield from _repr_pieces(x)
        yield "]"
    elif t is dict:
        yield "{"
        for i, (k, x) in enumerate(v.items()):   # type: ignore[union-attr]
            if i:
                yield ", "
            yield from _repr_pieces(k)
            yield ": "
            yield from _repr_pieces(x)
        yield "}"
    else:
        yield repr(v) if t in (float, bool) or v is None else f"a Python object ({t.__name__})"


def value_echo(v: object) -> str:
    """An echoed argument value: text in double quotes, anything else as its ``repr``;
    either cut to 30 code points plus "…". Large lists stop early."""
    if type(v) is str:
        return quoted(v)
    text, size = [], 0
    for piece in _repr_pieces(v):
        text.append(piece)
        size += len(piece)
        if size > ECHO_MAX:
            break
    return _visible("".join(text))


_KINDS: Final = {dict: "a dictionary", list: "a list", str: "text", int: "a whole number",
                 float: "a decimal number"}


def kind_words(v: object) -> str:
    """F24's kind words (04 §5.1 step 1); True, False, and None as written."""
    if type(v) is bool or v is None:
        return repr(v)
    return _KINDS.get(type(v), f"a Python object ({type(v).__name__})")


def line_problem(text: object, lo: int, hi: int, *, breaks: int = 0) -> str | None:
    """The shared text rule (F25 ``07`` I-5): the first form key that applies, or None.

    In order: ``"not text"`` (not exactly a ``str``); ``"empty"`` (``text == ""``);
    ``"length"`` (``len(text)`` outside ``lo..hi`` code points); ``"breaks"`` (more than
    ``breaks`` line feeds); ``"hidden"`` (``hidden(ch)`` on any character other than a line
    feed); ``"edge"`` (``text != text.strip()``: white space, a line break included, at
    either end). A text that is only white space gives ``"edge"``; a caller that wants
    "empty" for it tests ``text.strip() == ""`` first (F26 ``07`` I-1).

    The hidden test has a fast path: ``str.isprintable`` is False for every ``C*`` and
    ``Z*`` character but the space, so a printable text never reaches ``hidden``."""
    if type(text) is not str:
        return "not text"
    if text == "":
        return "empty"
    if not lo <= len(text) <= hi:
        return "length"
    if text.count("\n") > breaks:
        return "breaks"
    plain = text.replace("\n", "") if breaks else text
    if not plain.isprintable() and any(hidden(ch) for ch in plain):
        return "hidden"
    if text != text.strip():
        return "edge"
    return None


# --- F53 §3.4's shared refusal forms (N, B, C, T), reused by F54 ----------------------------

def whole_problem(arg: str, value: object, lo: int, hi: int, *,
                  lo_words: str | None = None) -> str | None:
    """N: ``{arg} must be a whole number from {lo} to {hi}, but it is {value}.`` when
    ``value`` isn't exactly an ``int`` in ``lo..hi`` (``True`` is refused). ``lo_words``
    replaces the written ``lo``, such as ``"0 (no limit)"``."""
    if type(value) is int and lo <= value <= hi:
        return None
    low = str(lo) if lo_words is None else lo_words
    return f"{arg} must be a whole number from {low} to {hi}, but it is {value_echo(value)}."


def flag_problem(arg: str, value: object) -> str | None:
    """B: ``{arg} must be True or False, but it is {value}.``"""
    if type(value) is bool:
        return None
    return f"{arg} must be True or False, but it is {value_echo(value)}."


def choice_words(choices: tuple[str, ...]) -> str:
    """``"a" or "b"``; ``"a", "b", or "c"`` (each in double quotes)."""
    quoted_all = [f'"{c}"' for c in choices]
    if len(quoted_all) <= 2:
        return " or ".join(quoted_all)
    return ", ".join(quoted_all[:-1]) + ", or " + quoted_all[-1]


def choice_problem(arg: str, value: object, choices: tuple[str, ...], *,
                   closest: str | None = None) -> str | None:
    """C: ``{arg} must be {choices}, but it is {value}.``, plus `` Did you mean "{x}"?``
    when the caller's ``closest`` suggestion (``api.closest``) is given."""
    if type(value) is str and value in choices:
        return None
    text = f"{arg} must be {choice_words(choices)}, but it is {value_echo(value)}."
    return text + (f' Did you mean "{closest}"?' if closest is not None else "")


def text_problem(arg: str, value: object, hi: int, *, required: bool = False) -> str | None:
    """T: ``line_problem(value, 1, hi)``'s key as F53 §3.4's sentence, or None. An optional
    argument may be None (``required`` False)."""
    if value is None and not required:
        return None
    key = line_problem(value, 1, hi)
    if key is None:
        return None
    if key == "not text":
        either = "" if required else ", or None"
        return f"{arg} must be text in quotes{either}, but it is {kind_words(value)}."
    if key == "empty":
        return f"{arg} is empty; it is 1 to {hi} characters on one line."
    if key == "length":
        size = len(value)                                    # type: ignore[arg-type]
        return f"{arg} is {size} characters long; it is 1 to {hi} characters on one line."
    if key in ("breaks", "hidden"):
        return (f"{arg} has a line break or hidden character; it is 1 to {hi} characters "
                "on one line.")
    return f"{arg} starts or ends with a space. Remove the space."


def fill(word: str, **values: object) -> str:
    """``word`` with each literal ``{key}`` replaced by ``str(value)``; other braces stay
    as written (an author's word may contain them)."""
    for key, value in values.items():
        word = word.replace("{" + key + "}", str(value))
    return word


__all__ = ["ECHO_MAX", "LINE_FORMS", "choice_problem", "choice_words", "cut", "fill",
           "flag_problem", "hidden", "kind_words", "line_problem", "quoted", "text_problem",
           "value_echo", "whole_problem"]

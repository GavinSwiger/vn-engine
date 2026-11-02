"""Text tags in dialogue and narration (F05 ``02-script.md`` §3.1–3.3, ``04-technical.md``
§4, §6.2).

``parse(text, origin, report)`` turns a line's text (after F02's escapes and joins) into an
immutable ``TaggedText``: styled ``Span``s and the marks ``VarMark`` (``{var=name}``),
``PauseMark`` (``{pause=0.6}``), and ``WaitMark`` (``{pause}``), with ``auto_next`` for
``{next}``. It is one pass with ``str.find("{")``; the current style is the top of a stack of
open style tags, and an inner color, size, or speed replaces the outer one (SR-F05-06).

The first mistake stops the parse: it is reported once, as E160–E167 at the column of its
tag's ``{`` (``origin`` maps a text offset to the source), and ``parse`` returns None. It
never raises for any text.

Choice text (F07 C9) will add ``parse(…, choice=True)``, which refuses the tags a choice
can't use with E175; the check belongs in ``_Parser.tag`` right after the name is known.

F29 (``04-technical.md`` §6): ``{shake}``, ``{wave}``, ``{glitch}`` are style tags that set
``Style.effect`` (E164's ``effect`` form, E297 for a different effect inside an open one), and
``on_glitch`` counts each outermost ``{glitch}`` for W185.

F30 (``04-technical.md`` §3, §4.1, §5.3): ``{username}`` and ``{username=var}`` are marks
(``NameMark``) that resolve to a ``Span`` holding the fallback word with ``Style.username``
set; only the textbox's layout draws the real name there. ``plain()`` turns such spans back
into plain text, ``plain(names=True)`` (F17's page record) keeps them. ``parse(…, crash=True)``
reads an ``effect crash`` message, which may hold only ``{var=…}``, ``{username}``, and
``{{`` (E301's ``tag`` form for any other known tag).

Headless and pure: imports ``core.graphemes`` and only ``script`` modules that import nothing
of ``nodes`` (``nodes`` imports this module for ``Say.body``).
"""

import keyword
import re
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Final

from engine.core.graphemes import iter_graphemes
from engine.script.messages import TAG_NAMES, format_message
from engine.script.suggest import suggest
from engine.script.words import canonical_name

INSTANT: Final = 0.0                     # Style.speed: the span shows at once
MAX_OPEN_STYLES: Final = 50              # SR-F05-06, E161
EFFECT_KINDS: Final = ("shake", "wave", "glitch")      # F29 04 §4
STRENGTHS: Final = ("small", "medium", "large")


@dataclass(frozen=True, slots=True)
class TextEffect:
    """F29 (``04`` §4): a span's motion, ``{shake}``, ``{wave}``, or ``{glitch}`` at one of
    three strengths. Built only from the fixed sets (the parser, the NVL record reader), so
    there is no check here."""

    kind: str                            # one of EFFECT_KINDS
    strength: str = "medium"             # one of STRENGTHS

    def key(self) -> str:
        """``"shake:large"``: the NVL page record's form (F29 07 §2.1)."""
        return f"{self.kind}:{self.strength}"


@dataclass(frozen=True, slots=True)
class Style:
    bold: bool = False
    italic: bool = False
    color: str | None = None             # "#rrggbb"; None = the line's base color
    size: float = 1.0                    # × text size
    speed: float = 1.0                   # × current speed; INSTANT = at once
    effect: TextEffect | None = None     # F29
    username: bool = False               # F30: a {username} span; text holds the fallback.
                                         # Last, so positional constructions stand.


BASE_STYLE: Final = Style()


@dataclass(frozen=True, slots=True)
class Span:
    """Shown text in one style. ``{{`` is already ``{``; may hold ``"\\n"``."""

    text: str
    style: Style


@dataclass(frozen=True, slots=True)
class VarMark:
    """``{var=name}`` in the parsed body; the Say executor replaces it with a ``Span``."""

    name: str
    style: Style


@dataclass(frozen=True, slots=True)
class NameMark:
    """F30 ``{username}`` / ``{username=var}`` in the parsed body; resolved to a ``Span`` with
    ``Style.username`` set, holding ``var``'s shown value or, when ``var`` is None,
    ``Program.username_fallback``."""

    var: str | None                      # canonical name, or None: the fallback word
    style: Style


@dataclass(frozen=True, slots=True)
class PauseMark:
    """``{pause=X}``: a timed pause of ``seconds``."""

    seconds: float


@dataclass(frozen=True, slots=True)
class WaitMark:
    """``{pause}``: wait for the player."""


Piece = Span | VarMark | NameMark | PauseMark | WaitMark


@dataclass(frozen=True, slots=True)
class TaggedText:
    """A line's body. Equal-style neighbouring spans are merged; empty spans are left out."""

    pieces: tuple[Piece, ...]
    auto_next: bool = False              # {next}

    def plain(self, *, names: bool = False) -> tuple[Span, ...]:
        """The styled text without timing (F13 history, F43): the spans, merged across the
        marks that separated them. F30: a ``{username}`` span becomes a plain span of the
        fallback word it holds, merged as usual; with ``names`` (F17's page record only) it
        is kept flagged and never merged with a neighbour."""
        out: list[Span] = []
        for piece in self.pieces:
            if isinstance(piece, Span):
                style = piece.style
                if style.username:
                    if names:
                        out.append(piece)
                        continue
                    if not piece.text:
                        continue
                    style = replace(style, username=False)
                    piece = Span(piece.text, style)
                if out and out[-1].style == style:
                    out[-1] = Span(out[-1].text + piece.text, style)
                else:
                    out.append(piece)
        return tuple(out)


EMPTY_TEXT: Final = TaggedText(())


@dataclass(frozen=True, slots=True)
class TagProblem:
    """One tag mistake: its code and message args, at the source line and column of the
    tag's ``{``."""

    code: str
    args: tuple
    line: int
    column: int

    def message(self) -> str:
        return format_message(self.code, self.args)


Origin = Callable[[int], tuple[int, int]]
Report = Callable[[TagProblem], None]
OnVar = Callable[[str, int, int], None]
OnGlitch = Callable[[int, str, int, int], None]    # F29: (graphemes, strength, line, column)


def origin_of(origins: Sequence[tuple[int, int, int]],
              default: tuple[int, int] = (1, 1)) -> Origin:
    """``origin(offset) -> (line, column)`` from a STRING token's ``origins`` (§6.1): the
    slice holding ``offset``, plus the distance into it. ``default`` serves an offset before
    the first slice (an empty text)."""
    starts = [start for start, _, _ in origins]

    def origin(offset: int) -> tuple[int, int]:
        index = bisect_right(starts, offset) - 1
        if index < 0:
            return default
        start, line, column = origins[index]
        return line, column + offset - start

    return origin


# --- Tag table (§3.1) -----------------------------------------------------------------------

TAGS: Final = frozenset(TAG_NAMES)
STYLE_TAGS: Final = frozenset(("b", "i", "color", "size", "speed", *EFFECT_KINDS))
USERNAME_TAG: Final = "username"         # F30
MARK_TAGS: Final = frozenset(("pause", "var", "next", USERNAME_TAG))
# F07 SR-F07-05: the tags a menu choice can't use (E175); the rest of TAGS it can. F29
# (SR-F29-04): choices show no text effects. F30: nor the player's name (E175's username
# form).
CHOICE_REFUSED: Final = frozenset(("pause", "speed", "size", "next", *EFFECT_KINDS,
                                   USERNAME_TAG))
# F30 (04 §5.2): the only tags an ``effect crash`` message may hold (E301's tag form).
CRASH_ALLOWED: Final = frozenset(("var", USERNAME_TAG))
_VALUE_TAGS = frozenset(("color", "size", "speed", "pause", "var", USERNAME_TAG,
                         *EFFECT_KINDS))
W185_GRAPHEMES: Final = 40               # F29 04 §6.2: more medium/large glitch graphemes warn

# SR-F05-04: unknown names that get a pointed E160 instead of a did-you-mean (F29 SR-F29-03:
# other engines' effect names point at shake, wave, glitch).
HINTS: Final = {
    "bold": "bold",
    "italic": "italic", "em": "italic",
    "w": "pause", "wait": "pause", "click": "pause", "p": "pause",
    "cps": "speed", "fast": "speed", "instant": "speed", "slow": "speed",
    "nw": "next", "nowait": "next",
    "jitter": "shake", "tremble": "shake", "shaky": "shake", "quake": "shake",
    "wavy": "wave", "sine": "wave", "ripple": "wave",
    "corrupt": "glitch", "glitched": "glitch", "zalgo": "glitch", "noise": "glitch",
    "u": "missing", "s": "missing", "font": "missing", "a": "missing",
}

RANGES: Final = {"pause": (0.1, 30.0), "speed": (0.1, 10.0), "size": (0.5, 2.0)}

_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}")
_HEX6_RE = re.compile(r"[0-9A-Fa-f]{6}")
_NUMBER_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_UNIT_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z%]+)")
_DOT_RE = re.compile(r"\.[0-9]+")
_QUOTES = "\"'“”‘’"
_BAD_RE = re.compile(rf"[\s{_QUOTES}:]")          # E162: space, line break, quote, ":"
_SPACE_QUOTE_RE = re.compile(rf"[\s{_QUOTES}]+")


def _e162(body: str, bad: str) -> tuple[str, str]:
    """E162's form (by the first refused character) and the tag as it should be written."""
    if bad.isspace():
        head, _, rest = body.partition(bad)
        if "=" not in body and head in _VALUE_TAGS and rest.strip():
            return "equals", _clean(head + "=" + rest)
        return "space", _clean(body)
    return ("colon" if bad == ":" else "quote"), _clean(body)


def _clean(body: str) -> str:
    fixed = _SPACE_QUOTE_RE.sub("", body)
    if "=" not in fixed:
        fixed = fixed.replace(":", "=", 1)
    return fixed.replace(":", "")


# --- The parser (§6.2) ----------------------------------------------------------------------

class _Parser:
    __slots__ = ("origin", "report", "on_var", "choice", "crash", "stack", "pieces", "buf",
                 "buf_style", "next_at", "on_glitch", "glitch_depth", "glitch_at",
                 "glitch_count", "glitch_largest")

    def __init__(self, origin: Origin, report: Report, on_var: OnVar | None,
                 choice: bool = False, on_glitch: OnGlitch | None = None,
                 crash: bool = False) -> None:
        self.origin = origin
        self.report = report
        self.on_var = on_var
        self.choice = choice
        self.crash = crash
        self.stack: list[tuple[str, Style]] = []
        self.pieces: list[Piece] = []
        self.buf: list[str] = []
        self.buf_style = BASE_STYLE
        self.next_at: int | None = None          # offset of {next}'s "{"
        # F29 W185 (04 §6.2): the outermost open {glitch}'s stack depth and "{" offset, its
        # medium/large non-space graphemes so far, and the largest strength counted.
        self.on_glitch = on_glitch
        self.glitch_depth = -1
        self.glitch_at = 0
        self.glitch_count = 0
        self.glitch_largest = ""

    def run(self, text: str) -> TaggedText | None:
        find = text.find
        length = len(text)
        i = 0
        while i < length:
            j = find("{", i)
            if j < 0:
                if not self.add(text[i:]):
                    return None
                break
            if j > i and not self.add(text[i:j]):
                return None
            if text.startswith("{{", j):
                if not self.add("{"):
                    return None
                i = j + 2
                continue
            close = find("}", j + 1)
            if close < 0:
                return self.fail("E161", ("open",), j)
            if find("{", j + 1, close) >= 0:
                return self.fail("E161", ("inside",), j)
            if close == j + 1:
                return self.fail("E161", ("empty",), j)
            if not self.tag(text[j + 1:close], j):
                return None
            i = close + 1
        self.end_glitch()
        self.flush()
        if not self.pieces and self.next_at is None:
            return EMPTY_TEXT
        return TaggedText(tuple(self.pieces), self.next_at is not None)

    # Helpers ---------------------------------------------------------------------------

    def fail(self, code: str, args: tuple, at: int) -> None:
        line, column = self.origin(at)
        self.report(TagProblem(code, args, line, column))
        return None

    @property
    def style(self) -> Style:
        return self.stack[-1][1] if self.stack else BASE_STYLE

    def add(self, text: str) -> bool:
        """Shown text in the current style. After ``{next}`` nothing may be shown (E167)."""
        if not text:
            return True
        if self.next_at is not None:
            self.fail("E167", ("last",), self.next_at)
            return False
        style = self.style
        if style != self.buf_style:
            self.flush()
            self.buf_style = style
        self.buf.append(text)
        effect = style.effect
        if self.glitch_depth >= 0 and effect is not None and effect.strength != "small":
            # W185 counts the non-space graphemes of medium and large glitch text.
            counted = sum(1 for g in iter_graphemes(text) if not g.isspace())
            if counted:
                self.glitch_count += counted
                if effect.strength == "large":
                    self.glitch_largest = "large"
                elif not self.glitch_largest:
                    self.glitch_largest = "medium"
        return True

    def end_glitch(self) -> None:
        """The outermost ``{glitch}`` closed (or the text ended): tell ``on_glitch`` when
        its count passes ``W185_GRAPHEMES``."""
        if self.glitch_depth < 0:
            return
        self.glitch_depth = -1
        if self.on_glitch is not None and self.glitch_count > W185_GRAPHEMES:
            self.on_glitch(self.glitch_count, self.glitch_largest, *self.origin(self.glitch_at))

    def flush(self) -> None:
        if self.buf:
            self.pieces.append(Span("".join(self.buf), self.buf_style))
            self.buf.clear()

    def mark(self, piece: Piece) -> bool:
        self.flush()
        self.pieces.append(piece)
        return True

    # Tags ------------------------------------------------------------------------------

    def tag(self, body: str, at: int) -> bool:
        bad = _BAD_RE.search(body)
        if bad is not None:
            self.fail("E162", _e162(body, bad.group()), at)
            return False
        close = body.startswith("/")
        name, eq, value = body[1 if close else 0:].partition("=")
        if name not in TAGS:
            self.unknown(body, close, name, eq, value, at)
            return False
        if not close and name == "speed" and value != "instant" and value.lower() == "instant":
            self.fail("E160", ("case", body, "speed=instant"), at)
            return False
        # F07 C9: with choice=True, refuse the tags a choice can't use here (E175).
        if self.choice and not close and name in CHOICE_REFUSED:
            self.fail("E175", (name,), at)
            return False
        # F30: an effect crash message holds only {var=…} and {username} (E301).
        if self.crash and name not in CRASH_ALLOWED:
            self.fail("E301", ("tag", name), at)
            return False
        if close:
            return self.close_tag(name, eq, at)
        if self.next_at is not None:
            self.fail("E167", ("twice",) if name == "next" else ("last",),
                      at if name == "next" else self.next_at)
            return False
        return self.open_tag(name, eq, value, at)

    def unknown(self, body: str, close: bool, name: str, eq: str, value: str,
                at: int) -> None:
        lower = name.lower()
        if lower in TAGS:
            fixed_value = "instant" if lower == "speed" and value.lower() == "instant" \
                else value
            self.fail("E160", ("case", body, ("/" if close else "") + lower + eq + fixed_value),
                      at)
        elif not name:
            self.fail("E160", ("list", body), at)
        elif lower in HINTS:
            kind = HINTS[lower]
            self.fail("E160", ("missing", name) if kind == "missing" else ("hint", name, kind),
                      at)
        else:
            suggestion = suggest(name, TAG_NAMES)
            self.fail("E160", ("list", name) if suggestion is None
                      else ("suggest", name, suggestion), at)

    def close_tag(self, name: str, eq: str, at: int) -> bool:
        if eq:
            self.fail("E163", ("close", name), at)
            return False
        stack = self.stack
        if name in MARK_TAGS:
            self.fail("E165", (name,), at)
            return False
        for index in range(len(stack) - 1, -1, -1):
            if stack[index][0] == name:
                break
        else:
            self.fail("E165", (name,), at)
            return False
        if index != len(stack) - 1:
            self.fail("E166", (name, stack[-1][0]), at)
            return False
        stack.pop()
        if len(stack) == self.glitch_depth:
            self.end_glitch()
        return True

    def open_tag(self, name: str, eq: str, value: str, at: int) -> bool:
        style = self.style
        if name in EFFECT_KINDS:                         # F29 04 §6.1
            if eq and value not in STRENGTHS:
                self.fail("E164", ("effect", name, value), at)
                return False
            outer = style.effect
            if outer is not None and outer.kind != name:
                self.fail("E297", (name, outer.kind), at)
                return False
            new = replace(style, effect=TextEffect(name, value or "medium"))
            if name == "glitch" and outer is None and len(self.stack) < MAX_OPEN_STYLES:
                self.glitch_depth = len(self.stack)
                self.glitch_at = at
                self.glitch_count = 0
                self.glitch_largest = ""
        elif name in ("b", "i", "next"):
            if eq:
                self.fail("E163", ("none", name), at)
                return False
            if name == "next":
                self.next_at = at
                return True
            new = replace(style, bold=True) if name == "b" else replace(style, italic=True)
        elif name == USERNAME_TAG:                       # F30 04 §5.3
            if not eq:
                return self.mark(NameMark(None, style))
            var = self.var_name(name, value, at)
            return var is not None and self.mark(NameMark(var, style))
        elif name == "pause":
            if not eq:
                return self.mark(WaitMark())
            if not value:
                self.fail("E163", ("needs", name), at)
                return False
            seconds = self.number(name, value, at)
            return seconds is not None and self.mark(PauseMark(seconds))
        elif not value:
            self.fail("E163", ("needs", name), at)
            return False
        elif name == "var":
            var = self.var_name(name, value, at)
            return var is not None and self.mark(VarMark(var, style))
        elif name == "color":
            if _COLOR_RE.fullmatch(value) is None:
                form = "hash" if _HEX6_RE.fullmatch(value) is not None else "color"
                self.fail("E164", (form, name, value), at)
                return False
            new = replace(style, color=value.lower())
        else:                                                        # size, speed
            if name == "speed" and value == "instant":
                number: float | None = INSTANT
            else:
                number = self.number(name, value, at)
            if number is None:
                return False
            new = replace(style, size=number) if name == "size" else replace(style, speed=number)
        if len(self.stack) >= MAX_OPEN_STYLES:
            self.fail("E161", ("deep",), at)
            return False
        self.stack.append((name, new))
        return True

    def var_name(self, name: str, value: str, at: int) -> str | None:
        """``{var=value}``'s (F30: ``{username=value}``'s) variable, canonical and told to
        ``on_var``; None with E163 (no value) or E164's ``var`` form reported."""
        if not value:
            self.fail("E163", ("needs", name), at)
            return None
        var = canonical_name(value)
        if not var.isidentifier() or keyword.iskeyword(var):
            self.fail("E164", ("var", name, value), at)
            return None
        if self.on_var is not None:
            self.on_var(var, *self.origin(at))
        return var

    def number(self, name: str, value: str, at: int) -> float | None:
        low, high = RANGES[name]
        if _NUMBER_RE.fullmatch(value) is not None:
            number = float(value)
            if low <= number <= high:
                return number
            self.fail("E164", ("range", name, value), at)
        elif (unit := _UNIT_RE.fullmatch(value)) is not None:
            self.fail("E164", ("unit", name, value, unit.group(1)), at)
        elif _DOT_RE.fullmatch(value) is not None:
            self.fail("E164", ("dot", name, value), at)
        else:
            self.fail("E164", ("range", name, value), at)
        return None


def parse(text: str, origin: Origin, report: Report, *,
          on_var: OnVar | None = None, choice: bool = False,
          on_glitch: OnGlitch | None = None, crash: bool = False) -> TaggedText | None:
    """The body of a line's ``text`` (SR-F05-01–15). ``origin(offset) -> (line, column)``
    places a tag's ``{``; ``report`` gets the one ``TagProblem`` when there is a mistake,
    and the result is then None. ``on_var(name, line, column)`` is told of each ``{var}``
    (W42, ``checks.py``). ``choice`` (F07 C9, SR-F07-05): the text of a menu choice, which
    appears all at once, so ``{pause}``, ``{speed}``, ``{size}``, ``{next}`` (and F29's
    effects) are E175. ``on_glitch(graphemes, strength, line, column)`` (F29 W185) is told
    of each outermost ``{glitch}`` whose medium and large non-space graphemes number more
    than ``W185_GRAPHEMES``, at its ``{``; ``strength`` is the largest counted. ``crash``
    (F30): an ``effect crash`` message, where any known tag but ``{var=…}`` and
    ``{username}`` is E301 (``CRASH_ALLOWED``)."""
    return _Parser(origin, report, on_var, choice, on_glitch, crash).run(text)


def has_username_tag(text: str) -> bool:
    """F30 E302: whether ``text`` (a title card's text, as written) holds a ``{username}`` or
    ``{username=…}`` tag; ``{{`` is a shown brace."""
    start = 0
    while (at := text.find("{", start)) >= 0:
        if text.startswith("{{", at):
            start = at + 2
            continue
        close = text.find("}", at + 1)
        if close < 0:
            return False
        if text[at + 1:close].partition("=")[0] == USERNAME_TAG:
            return True
        start = close + 1
    return False


__all__ = ["BASE_STYLE", "CHOICE_REFUSED", "CRASH_ALLOWED", "EFFECT_KINDS", "EMPTY_TEXT",
           "HINTS", "INSTANT", "MARK_TAGS", "MAX_OPEN_STYLES", "NameMark", "OnGlitch",
           "PauseMark", "Piece", "RANGES", "STRENGTHS", "STYLE_TAGS", "Span", "Style", "TAGS",
           "TagProblem", "TaggedText", "TextEffect", "USERNAME_TAG", "VarMark",
           "W185_GRAPHEMES", "WaitMark", "has_username_tag", "origin_of", "parse"]

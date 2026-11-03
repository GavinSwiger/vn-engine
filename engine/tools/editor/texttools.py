"""The Say form's text toolbar model (F47 design PR-F47-22, ``04-technical.md`` P2-C;
AC-F47-35).

Why this module exists: a game developer should never have to remember ``{color=#9a1c14}``
or where ``{/b}`` goes. The toolbar above Say's text field has a button per text tag
(Bold, Italic, Colour, Pause, Speed, Shake, Wave, Glitch, Player name, Variable, and under
"More" Size and Go on by itself); each puts its tag from ``script.tag_docs`` around the
selection, so a tag the engine gains is one ``TagDoc`` row plus one ``TextButton`` here (a
test fails when a tag has no button).

The text is Say's text as written between the quotes (``\\"``, ``{{`` and all). Every
function takes the text and a selection (``start``, ``end``: character offsets, as Tk's
``index`` gives them once counted) and gives back a ``TextEdit``: the new text, the new
selection, and the engine's own message when the result has a tag mistake (``problem``,
from ``texttags.parse``), so nothing here repeats the tag rules.

- ``apply(text, start, end, tag, value)``: a pair tag (``b``, ``color``, ``shake`` …) wraps
  the selection, or goes in empty with the caret between when nothing is selected. A mark
  (``pause``, ``var``, ``username``) goes in at the caret (the selection's end) and deletes
  nothing; ``next`` always goes at the very end, once. A selection edge inside a tag moves
  out of it, and a selection holding half of a pair grows to hold all of it, so wrapping
  never crosses tags (E166).
- ``toggle``: a pair tag already around exactly the selection comes off (a different
  value replaces it: Colour on red text picks the new colour); a selection inside a longer
  run splits the run when that tag is the innermost; otherwise ``apply``.
- ``active_tags(text, pos)``: the pair tags open at a position, outermost first, so the
  toolbar can show Bold pressed.
- ``strip_tags(text, start, end)``: "Clear formatting": takes off each pair whose words lie
  in the range (all of the text by default), open and close together, so the result never
  has half a pair, and the ``{pause}``/``{next}`` marks there. ``{var}``/``{username}``
  stay (they show words), and so do unknown tags (``{foo}``): they are the author's.
- ``preview(text)``: the one-line preview without tags: ``{var=x}`` shows ``[x]``,
  ``{username}`` ``[player name]``.

Pure: imports ``script.tag_docs``, ``script.texttags``, and the stdlib.
"""

from dataclasses import dataclass
from typing import Final

from engine.script.tag_docs import TagDoc, tag_doc
from engine.script.texttags import MARK_TAGS, STYLE_TAGS, TAGS, TagProblem, parse

# What a button asks for before it inserts its tag.
ASK_COLOUR: Final = "colour"         # a colour picker: "#rrggbb"
ASK_SECONDS: Final = "seconds"       # pause: empty (wait for a click) or 0.1 to 30
ASK_SPEED: Final = "speed"           # 0.1 to 10, or "instant"
ASK_SIZE: Final = "size"             # 0.5 to 2
ASK_STRENGTH: Final = "strength"     # empty (medium), small, medium, large
ASK_VARIABLE: Final = "variable"     # a story variable's name


@dataclass(frozen=True, slots=True)
class TextButton:
    """One toolbar button: its ``label``, the engine ``tag`` it puts in, what it ``ask``s
    for (None: nothing), the ``value`` it offers first, and whether it sits under More."""

    key: str
    label: str
    tag: str
    ask: str | None = None
    value: str | None = None
    more: bool = False

    @property
    def doc(self) -> TagDoc:
        """The tag's ``tag_docs`` row: its tooltip is ``summary``, Help is ``syntax``."""
        row = tag_doc(self.tag)
        assert row is not None, self.tag
        return row

    @property
    def pair(self) -> bool:
        """True when the tag wraps text (``{/tag}`` closes it)."""
        return self.tag in STYLE_TAGS


# The design's toolbar, in its order, then "More".
BUTTONS: Final[tuple[TextButton, ...]] = (
    TextButton("bold", "Bold", "b"),
    TextButton("italic", "Italic", "i"),
    TextButton("colour", "Colour", "color", ASK_COLOUR, "#9a1c14"),
    TextButton("pause", "Pause", "pause", ASK_SECONDS, "0.6"),
    TextButton("speed", "Speed", "speed", ASK_SPEED, "0.5"),
    TextButton("shake", "Shake", "shake", ASK_STRENGTH),
    TextButton("wave", "Wave", "wave", ASK_STRENGTH),
    TextButton("glitch", "Glitch", "glitch", ASK_STRENGTH),
    TextButton("player_name", "Player name", "username"),
    TextButton("variable", "Variable", "var", ASK_VARIABLE),
    TextButton("size", "Size", "size", ASK_SIZE, "1.5", more=True),
    TextButton("next", "Go on by itself", "next", more=True),
)
_TIMING_TAGS: Final = frozenset(("pause", "next"))
_BY_KEY: Final = {b.key: b for b in BUTTONS}
_BY_TAG: Final = {b.tag: b for b in BUTTONS}


def button(key: str) -> TextButton | None:
    return _BY_KEY.get(key)


def button_for_tag(tag: str) -> TextButton | None:
    return _BY_TAG.get(tag)


@dataclass(frozen=True, slots=True)
class TextEdit:
    """A toolbar action's result: the text, the selection to show, and the engine's tag
    message when the text now has a mistake (None: it parses)."""

    text: str
    start: int
    end: int
    problem: str | None = None


@dataclass(frozen=True, slots=True)
class ActiveTag:
    """A pair tag open at a position: ``{name=value}`` at ``[open_start, open_end)``, its
    ``{/name}`` at ``[close_start, close_end)`` (both the text's end when it is never
    closed: it closes at the end of the line)."""

    name: str
    value: str | None
    open_start: int
    open_end: int
    close_start: int
    close_end: int


# --- Reading tags ----------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Tag:
    start: int
    end: int
    name: str
    value: str | None
    closing: bool

    @property
    def known(self) -> bool:
        return self.name in TAGS


def _tags(text: str) -> list[_Tag]:
    """Every ``{…}`` tag, as the engine's parser finds them; ``{{`` is a shown brace and
    a ``{`` with no ``}`` (or another ``{`` first) is left as text."""
    out: list[_Tag] = []
    i = 0
    while (j := text.find("{", i)) >= 0:
        if text.startswith("{{", j):
            i = j + 2
            continue
        close = text.find("}", j + 1)
        if close < 0:
            break
        if text.find("{", j + 1, close) >= 0:
            i = j + 1
            continue
        body = text[j + 1:close]
        closing = body.startswith("/")
        name, eq, value = body[1 if closing else 0:].partition("=")
        out.append(_Tag(j, close + 1, name, value if eq else None, closing))
        i = close + 1
    return out


def _pairs(text: str) -> list[ActiveTag]:
    """Each known pair tag with its close (unclosed: the text's end), in opening order."""
    tags = _tags(text)
    stack: list[_Tag] = []
    found: list[tuple[_Tag, int, int]] = []
    for tag in tags:
        if not tag.known or tag.name not in STYLE_TAGS:
            continue
        if not tag.closing:
            stack.append(tag)
            continue
        for k in range(len(stack) - 1, -1, -1):
            if stack[k].name == tag.name:
                found.append((stack.pop(k), tag.start, tag.end))
                break
    found.extend((tag, len(text), len(text)) for tag in stack)
    found.sort(key=lambda f: f[0].start)
    return [ActiveTag(o.name, o.value, o.start, o.end, cs, ce) for o, cs, ce in found]


def active_tags(text: str, pos: int) -> tuple[ActiveTag, ...]:
    """The pair tags open at ``pos`` (between their open and close tags), outermost first."""
    return tuple(p for p in _pairs(text) if p.open_end <= pos <= p.close_start)


def problem(text: str) -> str | None:
    """The engine's message for the text's first tag mistake, or None."""
    found: list[TagProblem] = []
    parse(text, lambda at: (1, at + 1), found.append)
    return found[0].message() if found else None


def check_value(tag: str, value: str | None) -> str | None:
    """The engine's message when ``value`` can't go in ``tag`` (a colour without ``#``,
    a pause of 40 seconds, a variable name with a space), or None."""
    if tag not in TAGS:
        return f"{{{tag}}} isn't a text tag."
    if tag == "next":
        return problem("x" + tag_text(tag, value))
    probe = tag_text(tag, value) + "x" + (f"{{/{tag}}}" if tag in STYLE_TAGS else "")
    return problem(probe)


def tag_text(tag: str, value: str | None = None) -> str:
    """``{tag}`` or ``{tag=value}``."""
    return f"{{{tag}}}" if value is None or value == "" else f"{{{tag}={value}}}"


# --- Changing text ---------------------------------------------------------------------------

def _edit(text: str, start: int, end: int) -> TextEdit:
    return TextEdit(text, start, end, problem(text))


def _snap(text: str, start: int, end: int) -> tuple[int, int]:
    """The selection with no edge inside a tag or ``{{``, holding whole pairs only."""
    start, end = sorted((max(0, min(start, len(text))), max(0, min(end, len(text)))))
    for tag in _tags(text):
        if tag.start < start < tag.end:
            start = tag.start
        if tag.start < end < tag.end:
            end = tag.end
    i = 0
    while (j := text.find("{{", i)) >= 0:                   # a shown brace is one thing
        if start == j + 1:
            start = j
        if end == j + 1:
            end = j + 2
        i = j + 2
    if start == end:
        return start, end
    changed = True
    while changed:
        changed = False
        for pair in _pairs(text):
            if pair.close_start == len(text) and pair.close_end == len(text):
                continue                                     # never closed
            has_open = start <= pair.open_start and pair.open_end <= end
            has_close = start <= pair.close_start and pair.close_end <= end
            if has_open != has_close:
                start, end = min(start, pair.open_start), max(end, pair.close_end)
                changed = True
    return start, end


def apply(text: str, start: int, end: int, tag: str,
          value: str | None = None) -> TextEdit:
    """Put ``tag`` in: a pair tag around the selection, a mark at the caret (see the module
    docstring). ValueError for a name that isn't a tag."""
    if tag not in TAGS:
        raise ValueError(f"{{{tag}}} isn't a text tag.")
    opening = tag_text(tag, value)
    if tag == "next":
        if any(t.name == "next" and not t.closing for t in _tags(text)):
            return _edit(text, len(text), len(text))
        new = text + opening
        return _edit(new, len(new), len(new))
    if tag in MARK_TAGS:
        _, at = _snap(text, end, end)
        new = text[:at] + opening + text[at:]
        return _edit(new, at + len(opening), at + len(opening))
    start, end = _snap(text, start, end)
    closing = f"{{/{tag}}}"
    new = text[:start] + opening + text[start:end] + closing + text[end:]
    return _edit(new, start + len(opening), end + len(opening))


def unwrap(text: str, pair: ActiveTag) -> TextEdit:
    """``pair`` (from ``active_tags``) taken off; the selection is the text it held."""
    inner = text[pair.open_end:pair.close_start]
    new = text[:pair.open_start] + inner + text[pair.close_end:]
    return _edit(new, pair.open_start, pair.open_start + len(inner))


def toggle(text: str, start: int, end: int, tag: str,
           value: str | None = None) -> TextEdit:
    """A toolbar click: ``tag`` comes off the selection when it is already on it (or its
    value changes, when ``value`` differs), else goes on (``apply``)."""
    if tag not in STYLE_TAGS:
        return apply(text, start, end, tag, value)
    start, end = _snap(text, start, end)
    if start == end:
        return apply(text, start, end, tag, value)
    around = [p for p in _pairs(text)
              if p.name == tag and p.open_end <= start and end <= p.close_start]
    if not around:
        whole = [p for p in _pairs(text)
                 if p.name == tag and (p.open_start, p.close_end) == (start, end)]
        if not whole:
            return apply(text, start, end, tag, value)
        around = whole
        start, end = whole[0].open_end, whole[0].close_start
    pair = around[-1]
    if value and value != pair.value:
        if (pair.open_end, pair.close_start) == (start, end):
            opening = tag_text(tag, value)
            new = text[:pair.open_start] + opening + text[pair.open_end:]
            shift = len(opening) - (pair.open_end - pair.open_start)
            return _edit(new, start + shift, end + shift)
        return apply(text, start, end, tag, value)        # an inner colour wins
    if (pair.open_end, pair.close_start) == (start, end):
        return unwrap(text, pair)
    inner = [p for p in _pairs(text) if p.open_start >= pair.open_end
             and p.close_end <= pair.close_start
             and (p.open_end <= start <= p.close_start or p.open_end <= end <= p.close_start)]
    if inner:
        return TextEdit(text, start, end,
                        f"Select all of the {{{tag}}} text to take {{{tag}}} off.")
    opening = text[pair.open_start:pair.open_end]
    closing = f"{{/{tag}}}"
    head = closing if start > pair.open_end else ""
    tail = opening if end < pair.close_start else ""
    middle = text[start:end]
    new_text = (text[:pair.open_start] + (opening if head else "") +
                text[pair.open_end:start] + head + middle + tail + text[end:pair.close_start]
                + (closing if tail else "") + text[pair.close_end:])
    new_start = pair.open_start + (len(opening) if head else 0) + (start - pair.open_end) \
        + len(head)
    return _edit(new_text, new_start, new_start + len(middle))


def strip_tags(text: str, start: int = 0, end: int | None = None) -> TextEdit:
    """"Clear formatting": every pair tag whose words lie in ``[start, end)`` (all the text
    by default) taken off with its close, and every ``{pause}`` and ``{next}`` there;
    ``{var}`` and ``{username}`` stay, since they show words. The selection is the same
    words afterwards."""
    end = len(text) if end is None else end
    start, end = sorted((start, end))
    cut: list[tuple[int, int]] = []
    for tag in _tags(text):
        if tag.name in _TIMING_TAGS and not tag.closing \
                and start <= tag.start and tag.end <= end:
            cut.append((tag.start, tag.end))
    for pair in _pairs(text):
        closed = pair.close_end > pair.close_start
        if start <= pair.open_end and (pair.close_start <= end or not closed) and \
                pair.open_start < end:
            cut.append((pair.open_start, pair.open_end))
            if closed:
                cut.append((pair.close_start, pair.close_end))
    cut.sort()
    out: list[str] = []
    at = 0
    for a, b in cut:
        out.append(text[at:a])
        at = b
    out.append(text[at:])

    def moved(pos: int) -> int:
        return pos - sum(min(b, pos) - a for a, b in cut if a < pos)

    return _edit("".join(out), moved(start), moved(end))


def preview(text: str) -> str:
    """The text as one line without tags or escapes, for the preview under the field."""
    out: list[str] = []
    i = 0
    tags = {t.start: t for t in _tags(text)}
    while i < len(text):
        tag = tags.get(i)
        if tag is not None:
            if not tag.known:
                out.append(text[tag.start:tag.end])
            elif tag.name == "var" and tag.value:
                out.append(f"[{tag.value}]")
            elif tag.name == "username" and not tag.closing:
                out.append(f"[{tag.value}]" if tag.value else "[player name]")
            i = tag.end
            continue
        char = text[i]
        if char == "{" and text.startswith("{{", i):
            out.append("{")
            i += 2
        elif char == "\\" and i + 1 < len(text):
            following = text[i + 1]
            out.append(" " if following == "n" else following)
            i += 2
        else:
            out.append(" " if char in "\r\n" else char)
            i += 1
    return "".join(out)


__all__ = ["ASK_COLOUR", "ASK_SECONDS", "ASK_SIZE", "ASK_SPEED", "ASK_STRENGTH",
           "ASK_VARIABLE", "ActiveTag", "BUTTONS", "TextButton", "TextEdit", "active_tags",
           "apply", "button", "button_for_tag", "check_value", "preview", "problem",
           "strip_tags", "tag_text", "toggle", "unwrap"]

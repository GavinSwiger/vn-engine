"""Resolving a line's body (F05 ``04-technical.md`` §7.3; ``02-script.md`` §3.3, §3.4).

Why this module exists: a line's text is parsed once at load into an immutable
``TaggedText`` on the ``Say`` node, but what it shows depends on the story when the line
runs: each ``{var=name}`` becomes the variable's value as text, and the speaker's
``text_color``/``text_italic`` become the starting style. ``resolve_body`` does that for the
Say executor (step 3b, inside ``interpreter.say_command``, F05 I-1) and for the restore
presenter (``restoring=True``), so ``Say.body`` never holds a ``VarMark``.

F30 (``04-technical.md`` §5.4): each ``{username}`` becomes a ``Span`` of
``Program.username_fallback`` (``{username=var}``: the variable's shown value, by the same
rules) with ``Style.username`` set, kept even when empty and never merged. The runtime never
sees the player's name; only the textbox's layout draws it in that span's place.

At run time a name that doesn't exist is E170 and a value that isn't text or a number is
E171 (the story stops). On restore the variables were saved from the same burst that showed
the line, so the values are the shown ones; a value that no longer resolves (a patch removed
it) shows as empty text with one W46 WARNING (area ``runtime``), so text never fails a
restore. The warning is held by the interpreter and logged only when the restore commits.

I-3: ``format_value`` accepts only exact ``str``, ``int``, and ``float``, so no author
method (``__str__``, ``__format__``, a ``str`` subclass) runs here, outside the guard.
"""

import re
from collections.abc import Iterable
from dataclasses import replace
from typing import TYPE_CHECKING, Final

from engine.core.graphemes import iter_graphemes
from engine.runtime.character import Character
from engine.runtime.commands import NameMark, Span, Style, TaggedText, VarMark
from engine.runtime.errors import StoryError, where
from engine.runtime.values import kind_words
from engine.script import nodes
from engine.script.diagnostics import ScriptWarning
from engine.script.messages import format_message
from engine.script.suggest import suggest
from engine.script.words import ENGINE_NAMES

if TYPE_CHECKING:                                   # interpreter.py imports this module
    from engine.runtime.interpreter import Interpreter

VALUE_MAX_GRAPHEMES: Final = 200                    # SR-F05-19: more shows 199 and "…"
ELLIPSIS: Final = "…"

# SR-F05-19 / §7.3 step 2: each line break shows as one space ("\r\n" is one break).
_LINE_BREAK_RE = re.compile("\r\n|[\r\n\x85  ]")
_MISSING = object()
_MARKS: Final = (VarMark, NameMark)                 # the pieces resolve_tagged replaces


def format_value(v: object) -> str | None:
    """The shown text of a ``{var}`` value, or None if it isn't text or a number (E171).
    Text as is; a whole number with no separators; a decimal as Python writes it (``repr``).
    Line breaks become one space each; over 200 graphemes become the first 199 and "…"."""
    t = type(v)
    if t is str:
        text: str = v  # type: ignore[assignment]
    elif t is int:
        try:
            text = str(v)
        except ValueError:                          # longer than Python will print
            return None
    elif t is float:
        text = repr(v)
    else:
        return None
    if "\r" in text or "\n" in text or "\x85" in text or " " in text \
            or " " in text:
        text = _LINE_BREAK_RE.sub(" ", text)
    if len(text) <= VALUE_MAX_GRAPHEMES:            # no more clusters than code points
        return text
    kept: list[str] = []
    for cluster in iter_graphemes(text):
        if len(kept) == VALUE_MAX_GRAPHEMES:
            return "".join(kept[:VALUE_MAX_GRAPHEMES - 1]) + ELLIPSIS
        kept.append(cluster)
    return text


def resolve_body(interp: "Interpreter", stmt: nodes.Say, c: Character | None, *,
                 restoring: bool = False) -> TaggedText:
    """``stmt``'s body as shown now: every ``VarMark`` replaced by a ``Span`` of its value
    in the mark's style, and the speaker's ``text_color`` (spans with no color) and
    ``text_italic`` (every span) baked in; equal-style neighbours merged, empty spans left
    out. Raises ``StoryError`` E170/E171 at the line; with ``restoring``, such a value shows
    as "" and one W46 is noted for the restore to log."""
    color: str | None = None
    italic = False
    if c is not None:
        options = c.options
        written = options.get("text_color")
        color = written.lower() if type(written) is str else None
        italic = options.get("text_italic") is True
    return resolve_tagged(interp, interp.body_for(stmt), restoring=restoring, owner=stmt,
                          color=color, italic=italic)


def resolve_tagged(interp: "Interpreter", parsed: TaggedText, *, restoring: bool,
                   owner: nodes.Node, line: int | None = None, color: str | None = None,
                   italic: bool = False) -> TaggedText:
    """``parsed`` as shown now (``resolve_body``'s work for any tagged text; F07 C9's split
    for choice text): ``{var}`` values in, ``color``/``italic`` baked in as a speaker's
    text style. E170/E171 (or, ``restoring``, W46) are placed at ``owner`` and ``line``
    (default: the owner's line; F07: the menu and the choice's line)."""
    pieces = parsed.pieces
    if color is None and not italic and not any(type(p) in _MARKS for p in pieces):
        return parsed                               # nothing to resolve (the common line)
    styles: dict[Style, Style] = {}

    def based(style: Style) -> Style:
        out = styles.get(style)
        if out is None:
            out = style
            if color is not None and out.color is None:
                out = replace(out, color=color)
            if italic and not out.italic:
                out = replace(out, italic=True)
            styles[style] = out
        return out

    out: list = []
    for piece in pieces:
        kind = type(piece)
        if kind is VarMark:
            text = _shown(interp, owner, line, piece.name, restoring)
            if not text:
                continue
            piece = Span(text, piece.style)
            kind = Span
        elif kind is NameMark:
            # F30 (04 §5.4): a flagged span of the fallback word (or the variable's shown
            # value), kept even when empty and never merged; only the textbox's layout
            # draws the real name in its place.
            text = interp.program.username_fallback if piece.var is None \
                else _shown(interp, owner, line, piece.var, restoring)
            out.append(Span(text, replace(based(piece.style), username=True)))
            continue
        if kind is Span:
            style = based(piece.style)
            last = out[-1] if out else None
            if type(last) is Span and last.style == style:
                out[-1] = Span(last.text + piece.text, style)
            else:
                out.append(piece if style is piece.style else Span(piece.text, style))
        else:
            out.append(piece)
    return TaggedText(tuple(out), parsed.auto_next)


def _shown(interp: "Interpreter", owner: nodes.Node, line: int | None, name: str,
           restoring: bool) -> str:
    """§7.3 step 1: the shown text of ``{var=name}`` (F63: ``clock.date`` and the other
    ``{var=clock.<value>}`` names read the story clock)."""
    v = interp.G.get(name, _MISSING)
    if v is _MISSING and "." in name:
        from engine.runtime.clock import shown_value     # clock.py imports runtime modules
        try:
            v = interp._author(shown_value, interp, name)
        except Exception:                   # noqa: BLE001  (a game's own clock: E170)
            v = _MISSING
    if v is _MISSING:
        if restoring:
            _note_w46(interp, owner, line, name, missing=True)
            return ""
        message = format_message("E170", (name, suggest(name, _candidates(interp))))
        raise StoryError(message, code="E170", **where(owner, line))
    text = format_value(v)
    if text is None:
        if restoring:
            _note_w46(interp, owner, line, name, missing=False)
            return ""
        if Character in type(v).__mro__:
            args: tuple = (name, "a character", v.name_from)  # type: ignore[attr-defined]
        else:
            args = (name, kind_words(v))
        raise StoryError(format_message("E171", args), code="E171", **where(owner, line))
    return text


def _candidates(interp: "Interpreter") -> Iterable[str]:
    """E170's did-you-mean pool (SR-F03-35, as E85b, less what can't be shown as a value:
    engine names and built-ins): the story's variables, defaults, and defines."""
    program = interp.program
    names = {k for k in interp.G if type(k) is str and not k.startswith("_")}
    names |= set(program.default_names) | set(program.define_names)
    return names - set(ENGINE_NAMES)


def _note_w46(interp: "Interpreter", owner: nodes.Node, line: int | None, name: str, *,
              missing: bool) -> None:
    """G5: one W46 text for load, rollback, and hot reload."""
    interp.note_restore_warning(ScriptWarning(
        format_message("W46", (name, missing)), code="W46", file=owner.file.ref,
        line=owner.line if line is None else line))


__all__ = ["ELLIPSIS", "VALUE_MAX_GRAPHEMES", "format_value", "resolve_body", "resolve_tagged"]

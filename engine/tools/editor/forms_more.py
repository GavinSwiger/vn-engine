"""Studio's F47 command forms (F47 ``04-technical.md`` §3.1, §3.3; design §4.5, PR-F47-19).

Why this module exists: F46's ``forms.FORMS`` covers the first statements; F47 adds a form
for the rest, one phase at a time, so a non-programmer never has to type a statement. They
are ordinary ``forms.CommandForm``s: ``forms.all_forms()`` adds ``FORMS`` here to F46's (it
imports this module inside the function, as this one imports ``forms``), and the Events gate
(``forms.rows``) keeps a row only when the form writes back exactly what it read.

- P1: **Ending** (``ending <name> ["heading"] "title" [seconds] [with ...]``, AC-F47-23):
  the ending (picked from the check's ``ending`` names, or a new one), heading, title, how
  long the card stays, and F09's transition. Texts are shown as the player sees them: a
  ``{`` typed in the form is written ``{{`` (F18's card rule), and read back as ``{``.

Pure: no Tk.
"""

from typing import Final

from engine.script.nodes import Statement
from engine.script.routes import Ending
from engine.tools.editor.forms import (
    CommandForm, Field, Values, _NUMBER, _dot, _join, _secs, _tail, _tokens, _transition,
    _write_tail, quote)

ENDING_NO_CARD: Final = "no card"


def _card_text(text: str) -> str:
    """``text`` as a card line writes it: quoted, with ``{`` doubled."""
    return quote(text.replace("{", "{{"))


def _ending_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Ending) or not tokens or len(tokens) < 3 or tokens[0] != "ending" \
            or tokens[1].startswith('"'):
        return None
    texts = 2 if node.heading is not None else 1
    if not all(token.startswith('"') for token in tokens[2:2 + texts]):
        return None
    shown = [node.heading, node.title] if node.heading is not None else [node.title]
    if [_card_text(text) for text in shown] != tokens[2:2 + texts]:   # escapes we don't write
        return None
    rest = tokens[2 + texts:]
    hold = ""
    if rest and _NUMBER.fullmatch(rest[0]):
        if node.seconds is None:
            return None
        hold, rest = rest[0], rest[1:]
    elif node.seconds is not None:
        return None
    tail = _tail(rest, node, allow_at=False)
    if tail is None:
        return None
    return {"name": tokens[1], "heading": node.heading or "", "title": node.title,
            "hold": hold, "transition": tail["transition"], "seconds": tail["seconds"]}


def _ending_write(values: Values) -> str:
    heading = values.get("heading", "")
    return _join("ending", values["name"], _card_text(heading) if heading else "",
                 _card_text(values["title"]), values.get("hold", ""),
                 _write_tail(values, allow_at=False))


def _ending_summary(values: Values) -> str:
    hold = values.get("hold", "")
    card = ""
    if hold:
        try:
            card = ENDING_NO_CARD if float(hold) == 0 else _secs(hold)
        except ValueError:
            card = _secs(hold)
    title = values.get("title", "")
    heading = values.get("heading", "")
    return _dot(values.get("name", ""), f"{heading}: {title}" if heading else title, card,
                _transition(values))


FORMS: tuple[CommandForm, ...] = (
    CommandForm(
        "ending", "Ending", "Ending", (("ending", ""),), Ending,
        (Field("name", "Ending", "name", "ending"),
         Field("heading", "Heading", "text", optional=True),
         Field("title", "Title", "text"),
         Field("hold", "Card seconds", "number", optional=True),
         Field("transition", "Transition", "name", "transition", optional=True),
         Field("seconds", "Transition seconds", "number", optional=True)),
        _ending_read, _ending_write, _ending_summary),
)

__all__ = ["ENDING_NO_CARD", "FORMS"]

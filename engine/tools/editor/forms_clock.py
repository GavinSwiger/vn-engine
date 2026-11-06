"""Insert ▸ Time: the story clock form (F63 round 1; specs/F63-story-clock/SPEC.md).

Why this module exists: ``clock next``, ``clock next day`` and ``clock go to …`` move story
time (``script/clock.py``). One form covers the three: **Move** picks which, and for "go to"
**Day or date** (a number, or a date such as 31 October) and **Part of the day** say where.
The Events row says it in words ("next part of the day", "go to day 7, Evening").

Pure Python: ``engine.script`` and ``forms`` only; no Tk (ADR-0008). ``forms._line_forms``
imports this module inside the function, as this one imports ``forms``.
"""

from typing import Final

from engine.script.clock import ClockStep
from engine.script.nodes import Statement
from engine.tools.editor.forms import CommandForm, Field, Values, _tokens

MOVES: Final = ("next", "next day", "go to")
_SHOWN: Final = ("Next part of the day", "Next day", "Go to a day or a part of the day")
_ACTIONS: Final = {"next": "next", "next_day": "next day", "go": "go to"}


def _quote(text: str, *, bare_ok: bool) -> str:
    text = " ".join(text.split())
    return text if bare_ok and text.isidentifier() else f'"{text}"'


def _read(node: Statement, code: str) -> dict[str, str] | None:
    if not isinstance(node, ClockStep) or _tokens(code) is None:
        return None
    if node.written() != " ".join(_tokens(code) or ()):
        return None                                     # written another way: script row
    target = str(node.day) if node.day is not None else (node.text or "")
    return {"move": _ACTIONS[node.action], "target": target, "part": node.part or ""}


def _write(values: Values) -> str:
    move = values.get("move") or MOVES[0]
    if move != "go to":
        return f"clock {move}"
    target = values.get("target", "").strip()
    part = values.get("part", "").strip()
    words = ["clock go to"]
    if target.isdigit():
        words.append(f"day {int(target)}")
    elif target:
        words.append(_quote(target, bare_ok=False))
    if part:
        words.append(_quote(part, bare_ok=True))
    if not target and not part:
        words.append("day 1")
    return " ".join(words)


def _summary(values: Values) -> str:
    move = values.get("move") or MOVES[0]
    if move == "next":
        return "next part of the day"
    if move == "next day":
        return "next day"
    target = values.get("target", "").strip()
    part = values.get("part", "").strip()
    where = f"day {target}" if target.isdigit() else target
    return "go to " + ", ".join(p for p in (where, part) if p)


FORM: Final = CommandForm(
    "clock", "Time", "Time", (("clock", "clock next"), ("clock", "clock go to")), ClockStep,
    (Field("move", "Move", "pick", options=MOVES, shown=_SHOWN),
     Field("target", "Day or date (for Go to)", "text", optional=True),
     Field("part", "Part of the day (for Go to)", "text", optional=True)),
    _read, _write, _summary)

FORMS: Final[tuple[CommandForm, ...]] = (FORM,)

__all__ = ["FORM", "FORMS", "MOVES"]

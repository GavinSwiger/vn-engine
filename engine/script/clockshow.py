"""``show clock`` / ``hide clock``: the story clock in the status corner (F63 round 2,
specs/F63-story-clock/SPEC.md; proposal I-03 "Clock in the corner").

Why this module exists: a day-and-night story wants the player to see what day and part of
the day it is. ``show clock`` puts a small readout ("Day 4" over "Evening") in a corner of the
screen, where it updates as ``clock`` lines move time, and ``hide clock`` takes it away. The
corner is ``[calendar] place``, else the kit's, else the top right
(``storyclock.Calendar.place``). Whether it is shown is story state (``runtime/clock.py``'s
``ClockState.shown``), so saves, loads and going back keep it, as ``show meter`` does.

**Positional words** (ADR-0010 rule 2). ``clock`` is no new statement word here: ``show clock``
and ``hide clock`` are the clock form only when nothing else is on the line. Anything after
(``show clock at left``, ``show clock happy``, ``hide clock with dissolve``) is the picture
form, as before, so ``clock`` stays a free name for pictures. A game that has a picture
called ``clock`` gets W304 at launch for each bare ``show clock`` (``picture_warnings``),
which says how to show the picture instead.

Its Insert ▸ Time rows are in ``docs_table.py``, after the sprite rows (a plain ``show`` line's
help stays the sprite's).

``ClockShow`` is not a checkpoint and never branches: the story map and reach treat it as a
plain line.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

from engine.script import clock_messages
from engine.script.diagnostics import ScriptWarning
from engine.script.messages import TEMPLATES, format_message
from engine.script.nodes import Statement

WORD_CLOCK: Final = "clock"

TEMPLATES.update(clock_messages.TEMPLATES)        # W304 (clock.py adds the same table)


@dataclass(slots=True, kw_only=True)
class ClockShow(Statement):
    """``show clock`` (``shown`` True) or ``hide clock`` (False). Not a checkpoint."""

    shown: bool

    def identity_key(self) -> tuple[str, ...]:
        return (WORD_CLOCK, "show" if self.shown else "hide")

    def written(self) -> str:
        return f"{'show' if self.shown else 'hide'} {WORD_CLOCK}"


def is_clock_line(chunks: list[Any], colon: bool, is_word: str) -> bool:
    """Whether a ``show``/``hide`` line whose chunks after the word are ``chunks`` is the
    clock form: ``clock`` and nothing else (module docstring)."""
    return (len(chunks) == 1 and not colon and chunks[0].kind == is_word
            and chunks[0].text == WORD_CLOCK)


def parse_clock_line(raw: Any, word: str) -> ClockShow:
    return ClockShow(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                     shown=word == "show")


def picture_warnings(statements: Iterable[Statement], tags: Iterable[str]
                     ) -> list[ScriptWarning]:
    """W304 at each ``show clock`` / ``hide clock`` when the game has a picture whose tag is
    ``clock`` (``tags``: the image index's tags)."""
    if WORD_CLOCK not in set(tags):
        return []
    return [ScriptWarning(format_message("W304", (stmt.written(),)), code="W304",
                          file=stmt.file.ref, line=stmt.line)
            for stmt in statements if isinstance(stmt, ClockShow)]


__all__ = ["ClockShow", "WORD_CLOCK", "is_clock_line", "parse_clock_line",
           "picture_warnings"]

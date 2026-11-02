"""Chapters at run time (F18 SPEC §5; 07 I-2 to I-7).

Why this module exists: a ``chapter`` line marks where a part of the story begins. Running
it sets the current chapter (``interp.chapter``, stored by the next checkpoint in
``GameState.chapter``), records the chapter in F12's ``"chapter"`` unlock kind (which lasts
across playthroughs), and holds ``ChapterStarted`` (F11's auto-save request, ``app``). With
a card (``seconds`` > 0) it plays three ordinary F09 waits chained with ``begin_wait(...,
then=)``: the card comes in through the transition, holds, and goes out to the current
stage. None of them is a checkpoint, and the runtime reads no clock, so headless output
equals windowed output.

- ``ChapterIndex`` (``interp.chapters``): every chapter in include order, then line, built
  once from the ``Program`` (F20 reads it; F11's save label comes from ``save_label``).
- ``ChapterState`` is ``GameState.chapter``: ``{"current": null | "<name>"}``, always
  written, optional on read. ``from_json`` accepts exactly that key with ``null`` or a
  script-language §6 name of 1–64 code points; anything else is ``StateInvalid("chapter")``,
  never echoed.
  An unknown name is kept (the index gives None for it).
- ``play_card`` is the in and hold phases, shared with F19's ``ending`` (F19 ``07`` I-11);
  F18 passes ``card_out`` as ``after_hold``.

Layering (as ``menu.py``): ``state.py`` holds a ``ChapterState``, so this module sits below
the interpreter and imports it only when an executor runs. ``interpreter.py`` registers
``run_chapter`` once, at import (F19 ``07`` I-1), and registers the unlock kind per store
(``register_kind`` is safe to repeat). Pure (TR-F03-05): no file, clock, or randomness.
"""

import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.runtime.commands import ChapterStarted, TitleCard
from engine.runtime.stage import flush_stage
from engine.runtime.transitions import spec_for
from engine.script.effects import WithClause
from engine.script.limits import CHAPTER_NAME_MAX
from engine.script.nodes import Chapter

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.runtime.transitions import TransitionSpec
    from engine.script.program import Program

UNLOCK_KIND: Final = "chapter"          # F12 kind (``known`` = ``ChapterIndex.has``)
DEFAULT_HOLD: Final = 3.0               # seconds, when the line gives none
# The built-in ``fade`` at its ``[effects]`` length, for a card line with no ``with``.
_DEFAULT_WITH: Final = WithClause(name="fade", seconds=None, color=None, line=0, column=0)


# --- The state (GameState.chapter) ------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ChapterState:
    """``GameState.chapter``: ``current``, the name of the last ``chapter`` run (None before
    any). A lookup key only, never displayed."""

    current: str | None = None

    def to_json(self) -> dict[str, object]:
        return {"current": self.current}

    @staticmethod
    def from_json(obj: object) -> "ChapterState":
        """Validate untrusted ``obj``; ``StateInvalid("chapter")`` for anything but
        ``{"current": null | <1–64 code points of text>}``."""
        from engine.runtime.state import StateInvalid   # state.py imports this module
        if type(obj) is not dict or obj.keys() != {"current"}:
            raise StateInvalid("chapter")
        current = obj["current"]
        if current is None:
            return EMPTY_CHAPTER
        if not valid_chapter_name(current):
            raise StateInvalid("chapter")
        return ChapterState(current)


EMPTY_CHAPTER: Final = ChapterState()


def valid_chapter_name(name: object) -> bool:
    """A name a ``chapter`` line can have (script-language §6, 07 I-2): text of 1–64 code
    points that is an identifier in its canonical (NFKC) form."""
    return (type(name) is str and 0 < len(name) <= CHAPTER_NAME_MAX and name.isidentifier()
            and (name.isascii() or unicodedata.is_normalized("NFKC", name)))


def chapter_state(name: str | None) -> ChapterState:
    """The ``ChapterState`` a checkpoint stores for ``interp.chapter``."""
    return EMPTY_CHAPTER if name is None else ChapterState(name)


# --- The index (interp.chapters) ----------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ChapterInfo:
    """One ``chapter`` line: its name, texts as shown, sid, and label."""

    name: str
    heading: str | None
    title: str
    sid: str
    label: str


class ChapterIndex:
    """Every chapter of a ``Program`` in include order, then line (immutable). Lookups take
    any value and give None/False for anything that isn't a chapter's name."""

    __slots__ = ("_items", "_by_name")

    def __init__(self, items: tuple[ChapterInfo, ...]) -> None:
        self._items = items
        self._by_name = {info.name: info for info in items}

    @classmethod
    def build(cls, program: "Program") -> "ChapterIndex":
        found = [stmt for stmt in program.iter_statements() if type(stmt) is Chapter]
        found.sort(key=lambda s: (s.file.order, s.line))
        return cls(tuple(ChapterInfo(s.name, s.heading, s.title, s.sid, s.label)
                         for s in found))

    def get(self, name: object) -> ChapterInfo | None:
        return self._by_name.get(name) if type(name) is str else None

    def has(self, name: object) -> bool:
        return type(name) is str and name in self._by_name

    def __iter__(self) -> Iterator[ChapterInfo]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def save_label(self, name: object) -> str | None:
        """F11's save description: ``heading: title``, or ``title``; None for None or an
        unknown name."""
        info = self.get(name)
        if info is None:
            return None
        return info.title if info.heading is None else f"{info.heading}: {info.title}"


def install(interp: "Interpreter") -> None:
    """Per interpreter (F39 calls it again): the index, and F12's kind on its store."""
    interp.chapters = ChapterIndex.build(interp.program)
    interp.persistent.register_kind(UNLOCK_KIND, known=interp.chapters.has)


# --- The executor (SPEC §5) ----------------------------------------------------------------------

def card_transition(interp: "Interpreter", clause: WithClause | None,
                    sid: str) -> "TransitionSpec | None":
    """The card's transition, both ways: the line's ``with`` (memoized per sid by
    ``spec_for``), else the built-in ``fade`` at its ``[effects]`` length."""
    return spec_for(interp, _DEFAULT_WITH if clause is None else clause, sid)


def play_card(interp: "Interpreter", card: TitleCard, seconds: float | None,
              with_clause: WithClause | None, *,
              after_hold: Callable[["Interpreter"], "Step"]) -> "Step":
    """Executor steps 3–4 (shared with F19's ``ending``): the textbox hides
    (``scene_since_line``, ``kept_line`` cleared), the card comes in over the current stage
    through the transition (``flush_stage(card=)``, ``begin_wait(for_stage=True)``), then
    holds ``seconds`` (None: 3.0), then ``after_hold`` runs as the next step."""
    stmt = interp.current
    assert stmt is not None
    spec = card_transition(interp, with_clause, stmt.sid)
    hold = DEFAULT_HOLD if seconds is None else seconds
    interp.scene_since_line = True
    interp.kept_line = None
    flush_stage(interp, transition=spec, card=card)

    def _hold(i: "Interpreter") -> "Step":
        return i.begin_wait(seconds=hold, then=after_hold)

    return interp.begin_wait(stmt, for_stage=True, then=_hold)


def card_out(interp: "Interpreter") -> "Step":
    """Executor step 5: the card goes out through the same transition to the current stage
    (stage changes written since the last moment shown included), and the story waits until
    it is drawn; then it moves on to the line after the ``chapter``."""
    stmt = interp.current
    assert isinstance(stmt, Chapter)
    flush_stage(interp, transition=card_transition(interp, stmt.with_clause, stmt.sid))
    return interp.begin_wait(stmt, for_stage=True)


def run_chapter(interp: "Interpreter", stmt: Chapter) -> "Step":
    """Executor steps 1–2: current chapter, unlock, ``ChapterStarted``; ``seconds`` 0 shows
    no card and waits for nothing."""
    interp.chapter = stmt.name
    interp.persistent.unlock(UNLOCK_KIND, stmt.name)
    interp._hold(ChapterStarted(stmt.name, stmt.sid))
    if stmt.seconds == 0:
        from engine.runtime.interpreter import Step     # below the interpreter (docstring)
        return Step.CONTINUE
    card = TitleCard(stmt.name, stmt.heading, stmt.title)
    return play_card(interp, card, stmt.seconds, stmt.with_clause, after_hold=card_out)


__all__ = ["ChapterIndex", "ChapterInfo", "ChapterState", "DEFAULT_HOLD", "EMPTY_CHAPTER",
           "UNLOCK_KIND", "card_out", "card_transition", "chapter_state", "install",
           "play_card", "run_chapter", "valid_chapter_name"]

"""The history log's record (F13 ``SPEC.md`` §2, §5; ``07-architecture-review.md`` I-2–I-4).

Why this module exists: the lines read so far and the choices picked are a display record
(architecture "Display records") kept in ``GameState.history``, so saves carry it and a
restore or rollback trims it with no extra work. ``take_checkpoint`` step 2a records each
line taken at a checkpoint (``add_line``) and F07's ``on_choose`` each accepted pick
(``add_pick``); F59's roll adds its result as a nameless line (``add_note``); nothing else
records. Restore, load, rollback, and hot reload only set it
from the state, at the restore's commit (I-3).

Shared, never copied per line: ``HistoryState`` and ``HistoryEntry`` are frozen, and a new
line builds one entry and one tuple of at most ``HISTORY_MAX`` references (about 2 KB); the
entries themselves are shared by every later state, so a snapshot holds the live
``HistoryState`` as is.

Saved (SPEC §5): ``to_json``/``from_json`` are ``GameState``'s ``history`` key, always written
and optional on read (absent: ``EMPTY_HISTORY``). ``from_json`` checks counts first, then
exact keys and types; sids are checked by shape only, never resolved. Text is display only:
never parsed as markup and never read by story logic.

Layering: ``state.py`` imports this module, so ``Pick`` (``menu.py``) is imported only for
annotations (I-4). Pure: no file, clock, or randomness; no pygame.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from engine.runtime.menu import cut, sid_ok
from engine.script.menu import Menu
from engine.script.nodes import Say as SayNode

if TYPE_CHECKING:
    from engine.runtime.commands import Say, Span
    from engine.runtime.menu import Pick
    from engine.script.program import Program

HISTORY_MAX: Final = 250                # PR-F13-03: past this the oldest entry drops
TEXT_MAX: Final = 2_000                 # an entry's text, "…"-cut (code points)
NAME_MAX: Final = 200                   # a line's name, "…"-cut (code points)
REPLACEMENT: Final = "�"           # what a lone surrogate draws as (AC-F13-09)

Kind = Literal["line", "choice"]
_KINDS: Final = frozenset(("line", "choice"))
_KEYS: Final = frozenset(("entries",))
_ENTRY_KEYS: Final = frozenset(("kind", "sid", "name", "text"))
# Lone surrogates (any), and a high one right before a low one (a pair JSON reads as one).
_HIGH, _LOW, _END = chr(0xD800), chr(0xDC00), chr(0xDFFF)
_SURROGATE: Final = re.compile(f"[{_HIGH}-{_END}]")
_SURROGATE_PAIR: Final = re.compile(f"[{_HIGH}-{chr(0xDBFF)}][{_LOW}-{_END}]")


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """One row: a line (``sid`` the line's, a question's the menu's; ``name`` as shown,
    ``""`` for none) or a choice (``sid`` the menu's, ``name`` ``""``). ``text`` is the plain
    text as shown (1–``TEXT_MAX`` code points, ``\\n`` kept)."""

    kind: Kind
    sid: str
    name: str
    text: str


@dataclass(frozen=True, slots=True)
class HistoryState:
    """``GameState.history``: the entries in story order, oldest first, at most
    ``HISTORY_MAX``. Every ``add_*`` returns a new state (or ``self`` when nothing is
    recorded); the old one is unchanged."""

    entries: tuple[HistoryEntry, ...] = ()

    def add_line(self, say: "Say", *, spans: "Iterable[Span] | None" = None
                 ) -> "HistoryState":
        """``say``'s line as a new entry: its name (None or ``""``: no name) and the
        ``plain()`` span texts joined. ``spans`` is ``say.body.plain()`` when the caller
        already has it (checkpoint steps 2a and 2b share one call, F17 I-6). Blank text
        records nothing (I-2)."""
        if spans is None:
            spans = say.body.plain()
        text = "".join([span.text for span in spans])
        if not text or text.isspace():
            return self
        name = say.name or ""
        return self._add(HistoryEntry("line", say.sid, _shown(name, NAME_MAX),
                                      _shown(text, TEXT_MAX)))

    def add_pick(self, pick: "Pick") -> "HistoryState":
        """An accepted pick as a choice entry: the menu's sid and ``Pick.text``. A pick
        whose shown text is blank records nothing (I-2)."""
        text = pick.text
        if not text or text.isspace():
            return self
        return self._add(HistoryEntry("choice", pick.menu, "", _shown(text, TEXT_MAX)))

    def add_note(self, sid: str, text: str) -> "HistoryState":
        """F59: a nameless line the story didn't write (a check's roll, ``sid`` its
        statement's). Blank text records nothing."""
        if not text or text.isspace():
            return self
        return self._add(HistoryEntry("line", sid, "", _shown(text, TEXT_MAX)))

    def _add(self, entry: HistoryEntry) -> "HistoryState":
        entries = self.entries
        if len(entries) >= HISTORY_MAX:
            entries = entries[len(entries) - HISTORY_MAX + 1:]
        return HistoryState(entries + (entry,))

    def to_json(self) -> dict[str, object]:
        """``{"entries": [{"kind", "sid", "name", "text"}]}``, fresh plain values (always
        written)."""
        return {"entries": [{"kind": e.kind, "sid": e.sid, "name": e.name, "text": e.text}
                            for e in self.entries]}

    @staticmethod
    def from_json(obj: object) -> "HistoryState":
        """Validate an untrusted saved ``history`` value: at most ``HISTORY_MAX`` entries
        (counted before anything is built), exact key sets and types (a ``str`` subclass
        is refused), a known ``kind``, ADR-0006 sid shapes (never resolved), names at most
        ``NAME_MAX`` and ``""`` on a choice, text of 1–``TEXT_MAX`` code points. Raises
        ``StateInvalid("history")`` only; its text never holds any part of the input."""
        try:
            return _from_json(obj)
        except _Invalid:
            pass
        except Exception:                   # defensive: the contract is StateInvalid only
            pass
        from engine.runtime.state import StateInvalid   # state.py imports this module
        raise StateInvalid("history") from None

    def save_problem(self) -> str | None:
        """F11 C11 for this field: ``history`` if ``from_json`` would refuse this value's
        JSON, ``lone_surrogate`` if a text or name holds a lone high surrogate right before
        a lone low one (JSON reads the two back as one character); else None. Both only
        in a hand-built state: the writer keeps every limit and records no lone
        surrogate."""
        try:
            back = _from_json(self.to_json())
        except Exception:                   # _Invalid, or a hand-built value of a wrong type
            return "history"
        if back != self:
            return "history"
        joined = " ".join([t for e in self.entries for t in (e.name, e.text)])
        if not joined.isascii() and _SURROGATE_PAIR.search(joined):
            return "lone_surrogate"
        return None


EMPTY_HISTORY: Final = HistoryState()


def _shown(text: str, limit: int) -> str:
    """``text`` cut to ``limit`` code points with F07's ``cut``; a lone surrogate becomes
    U+FFFD, as it draws, so the saved text reads back equal (two halves of a pair written
    as escapes would read back as one character)."""
    text = cut(text, limit)
    if not text.isascii() and _SURROGATE.search(text):
        text = _SURROGATE.sub(REPLACEMENT, text)
    return text


class _Invalid(Exception):
    pass


def _from_json(obj: object) -> HistoryState:
    if type(obj) is not dict or obj.keys() != _KEYS:
        raise _Invalid
    raw = obj["entries"]
    if type(raw) is not list or len(raw) > HISTORY_MAX:
        raise _Invalid
    for entry in raw:                       # shapes first, before any value is read
        if type(entry) is not dict or entry.keys() != _ENTRY_KEYS:
            raise _Invalid
    out: list[HistoryEntry] = []
    for entry in raw:
        kind, sid, name, text = entry["kind"], entry["sid"], entry["name"], entry["text"]
        if type(kind) is not str or kind not in _KINDS or not sid_ok(sid):
            raise _Invalid
        if type(name) is not str or len(name) > NAME_MAX or (kind == "choice" and name):
            raise _Invalid
        if type(text) is not str or not 0 < len(text) <= TEXT_MAX:
            raise _Invalid
        out.append(HistoryEntry(kind, sid, name, text))   # type: ignore[arg-type]
    return HistoryState(tuple(out))


def voice_of(program: "Program", sid: str) -> str | None:
    """The voice file of entry ``sid`` (F13 step 3's ``voice_for`` port, I-4): a line's
    ``Say.voice``, or for a menu its question's (the field ``run_menu`` sends as the
    question's ``PlayVoice``); None for anything else or a sid that no longer resolves."""
    stmt = program.get(sid)
    if type(stmt) is Menu:
        stmt = stmt.question
    return stmt.voice if isinstance(stmt, SayNode) else None


__all__ = ["EMPTY_HISTORY", "HISTORY_MAX", "HistoryEntry", "HistoryState", "NAME_MAX",
           "TEXT_MAX", "voice_of"]

"""F31 meta files at run time (F31 ``04-technical.md`` §3, §4.2, §5.4, §6.5–§6.7, §8; ``07``
§3(b), I-4; run warnings W199, W200).

Why this module exists: a ``file`` line writes, deletes, checks, or reads a small file the
player can see beside the game, but the runtime never touches disk (invariant 9). So the
interpreter holds a **files port** (a "runtime port", 07 §3(b)): synchronous, bounded, never
raising, never saved. ``MemoryFolder`` is the default (headless runs, tests, ``vn check``,
Studio's check child); ``app/metafiles.py`` (F31 s4) attaches the disk port.

- **``MetaFiles``** (one per session, or per headless run) holds the port and the session's
  rules: at most ``META_CHANGES_MAX`` writes and deletes (then one W199), W200 once per name.
- **``run_file``** (04 §5.4): ``exists`` and ``read`` ask the port at once and set the ``into``
  variable before the next statement; they run in F14's forward re-runs too (they read again,
  PR-F31-15). ``write`` and ``delete`` always set ``timeline.block_pending`` first (C1: the
  next checkpoint is a wall, so back never crosses a change and no forward chain repeats one;
  the ``replaying`` test is a defence only), then, under the cap, call the port and hold
  ``MetaWrite``/``MetaDelete`` (records; the windowed handler pumps the disk port).
- **``decode_note``** (04 §6.5, SEC-F31-05(a)): strict UTF-8, one BOM dropped, line ends and
  U+2028/9 to ``\\n``, NFC, Cc (but ``\\n``, ``\\t``), Cf, and Cs removed, cut to
  ``META_READ_MAX_CHARS`` code points. The value only ever goes to ``G[target]``: never to a
  path, lookup, command field, exception, warning, or log line (SEC-F31-05(b), (c)).

No saved state: only the ``into`` variables reach ``GameState`` (04 §8). Pure: no file, clock,
randomness, pygame, ``os``, or ``engine.meta``; nothing here holds or logs a path or note text.
"""

import unicodedata
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple, Protocol

from engine.core.constants import META_CHANGES_MAX, META_READ_MAX_BYTES, META_READ_MAX_CHARS
from engine.core.paths import is_meta_name
from engine.runtime.commands import MetaDelete, MetaWrite
from engine.script.diagnostics import ScriptWarning
from engine.script.messages import format_message
from engine.script.metafiles import DELETE, EXISTS, READ, WRITE, MetaFile

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step

_EMPTY: Mapping[str, bytes] = MappingProxyType({})
_LINE_ENDS = ("\r", " ", " ")          # each becomes "\n" after "\r\n" (SEC-F31-05)
_KEPT_CONTROLS = frozenset("\n\t")
_DROPPED = frozenset(("Cc", "Cf", "Cs"))


class ReadAnswer(NamedTuple):
    """A port's answer to ``read``: the raw bytes (at most ``META_READ_MAX_BYTES``), or None
    for no text; ``reason`` a W200 form (``large``, ``not_file``, ``hard_link``), or None
    (missing, or read: silent)."""

    data: bytes | None
    reason: str | None


class FilesPort(Protocol):
    """The runtime's view of ``<game>/characters/`` (04 §4.2). Every method is synchronous,
    bounded, and never raises for anything the folder holds (07 I-4); a name the program
    doesn't use is a programmer error."""

    def exists(self, name: str) -> bool: ...
    def read(self, name: str) -> ReadAnswer: ...
    def write(self, name: str, text: bytes | None) -> None: ...     # None: copy the original
    def delete(self, name: str) -> None: ...


def _require(name: object) -> str:
    if not is_meta_name(name):
        raise ValueError("not a meta file name")              # never echoes the value
    return name  # type: ignore[return-value]


class MemoryFolder:
    """A ``FilesPort`` that never touches disk (04 §6.6): ``entries`` is what is "on disk";
    ``originals`` stand in for ``files/<name>`` (a missing one copies as ``b""``, D5). Changes
    are immediate (no overlay); ``read`` refuses over ``META_READ_MAX_BYTES`` as ``large``.
    Every name must pass ``is_meta_name`` (``ValueError``, the same allow-list rule)."""

    __slots__ = ("entries", "originals")

    def __init__(self, *, entries: Mapping[str, bytes] = _EMPTY,
                 originals: Mapping[str, bytes] = _EMPTY) -> None:
        self.entries: dict[str, bytes] = {_require(k): bytes(v) for k, v in entries.items()}
        self.originals: dict[str, bytes] = {_require(k): bytes(v)
                                            for k, v in originals.items()}

    def __repr__(self) -> str:
        return f"MemoryFolder({len(self.entries)} entries)"     # no names' bytes (SEC-F31-07)

    def exists(self, name: str) -> bool:
        return _require(name) in self.entries

    def read(self, name: str) -> ReadAnswer:
        data = self.entries.get(_require(name))
        if data is None:
            return ReadAnswer(None, None)
        if len(data) > META_READ_MAX_BYTES:
            return ReadAnswer(None, "large")
        return ReadAnswer(data, None)

    def write(self, name: str, text: bytes | None) -> None:
        name = _require(name)
        self.entries[name] = self.originals.get(name, b"") if text is None else bytes(text)

    def delete(self, name: str) -> None:
        self.entries.pop(_require(name), None)

    def player_deletes(self, name: str) -> None:
        """The player deleted the file (headless ``player deletes <name>``)."""
        self.delete(name)

    def player_restores(self, name: str) -> None:
        """The player put the original back (headless ``player restores <name>``)."""
        self.write(name, None)


class MetaFiles:
    """The session's files rules over ``port`` (04 §4.2): ``changes`` counts live writes and
    deletes (at most ``META_CHANGES_MAX``); W199 and W200 marks are session-only."""

    __slots__ = ("port", "changes", "_capped", "_w200")

    def __init__(self, port: FilesPort) -> None:
        self.port = port
        self.changes = 0
        self._capped = False
        self._w200: set[str] = set()

    def __repr__(self) -> str:
        return f"MetaFiles({type(self.port).__name__}, {self.changes} changes)"


def attach(interp: "Interpreter", files: MetaFiles) -> None:
    """Give ``interp`` its files (headless ``files=``; the app's disk port, F31 s4)."""
    interp.files = files


def decode_note(data: bytes) -> str | None:
    """A note the player may have typed, as inert text (04 §6.5; SEC-F31-05(a)); None when it
    isn't UTF-8."""
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    if text.startswith("﻿"):
        text = text[1:]
    text = text.replace("\r\n", "\n")
    for end in _LINE_ENDS:
        text = text.replace(end, "\n")
    text = unicodedata.normalize("NFC", text)
    text = "".join(ch for ch in text
                   if ch in _KEPT_CONTROLS or unicodedata.category(ch) not in _DROPPED)
    return text[:META_READ_MAX_CHARS]


def _warn(interp: "Interpreter", stmt: MetaFile, code: str, args: tuple) -> None:
    text = format_message(code, args)
    warning = ScriptWarning(text, code=code, file=stmt.file.ref, line=stmt.line)
    interp.log.warning("%s", warning.format())


def _read(interp: "Interpreter", files: MetaFiles, stmt: MetaFile) -> str | None:
    answer = files.port.read(stmt.name)
    reason = answer.reason
    value = None
    if answer.data is not None:
        value = decode_note(answer.data)
        if value is None:
            reason = "utf8"
    if reason is not None and stmt.name not in files._w200:
        files._w200.add(stmt.name)
        _warn(interp, stmt, "W200", (reason, stmt.name))
    return value


def _change(interp: "Interpreter", files: MetaFiles, stmt: MetaFile) -> None:
    timeline = interp.timeline
    timeline.block_pending = True                         # C1: always, capped or not
    if timeline.replaying:                                # unreachable (04 §8); a defence
        interp.log.debug("file %s %s: not repeated by a forward re-run", stmt.verb, stmt.name)
        return
    if files.changes >= META_CHANGES_MAX:
        if not files._capped:
            files._capped = True
            _warn(interp, stmt, "W199", ())
        return
    files.changes += 1
    if stmt.verb == WRITE:
        text = stmt.text
        files.port.write(stmt.name, None if text is None else text.encode("utf-8"))
        interp._hold(MetaWrite(stmt.name))
    else:
        files.port.delete(stmt.name)
        interp._hold(MetaDelete(stmt.name))


def run_file(interp: "Interpreter", stmt: MetaFile) -> "Step":
    """A ``file`` line (04 §5.4). Each line is one step; the ``into`` variable is set before
    the next statement."""
    from engine.runtime.interpreter import Step         # below the interpreter (docstring)
    assert stmt.name in interp.program.meta_files
    files = interp.files
    verb = stmt.verb
    if verb == EXISTS:
        interp.G[stmt.target] = bool(files.port.exists(stmt.name))      # type: ignore[index]
    elif verb == READ:
        interp.G[stmt.target] = _read(interp, files, stmt)              # type: ignore[index]
    elif verb in (WRITE, DELETE):
        _change(interp, files, stmt)
    return Step.CONTINUE


__all__ = ["FilesPort", "MemoryFolder", "MetaFiles", "ReadAnswer", "attach", "decode_note",
           "run_file"]

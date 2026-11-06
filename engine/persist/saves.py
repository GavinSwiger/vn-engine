"""Save files: slot names, the ``.vnsave`` format, the one strict reader, the sliced encoder,
rotation, ``seq``, and the slot index (F11 ``04-technical.md`` §4, §5.2, §7.2–§7.5, §8).

Why this module exists: every byte in the saves folder is untrusted (players share saves
online, edit them, plant links), so only this module turns save bytes into values, through
bounded steps, and every file the engine writes must pass this same reader whatever the folder
holds (SEC-F11-04, -07). It is pure: no pygame, no threads, no ``shutil``; file I/O goes
through ``core.safefile`` on the calling thread. Writing is the ``App.writer`` ``save``
client's job (F16 ``07`` §3): the encoder only makes the pieces.

**The file** (``<slot>.vnsave``), three compact ASCII JSON lines, each ending in ``\\n``::

    {"vnsave":2,"game":"paper-lanterns","seq":42,"saved_at":1793567040,"description":"…",
     "chapter":null,"game_version":"1.0","state_format":1,"state_rev":1,"thumb":24113,
     "state":201877}
    {"jpeg":"/9j/4AAQ…"}                                    (or {"jpeg":null})
    {"format":1,"identity_scheme":1,"position":{…},…}      (GameState.to_json(), unchanged)

``thumb`` and ``state`` are the byte lengths of lines 2 and 3 with their ``\\n``, so
``len(line 1) + 1 + thumb + state`` is the file size: a cut download, CRLF line ends, or junk
after line 3 is DAMAGED, never misparsed.

**Reading** (§7.5). Pages read the first ``HEAD_MAX`` bytes (lines 1–2, ≤ 136 KiB) with
``read_slot_head``; a load reads the whole file once with ``read_slot_full``. Both paths use
the same steps (``split_lines``, ``strict_loads`` with F12's hooks, the meta table) and catch
exactly ``RecursionError``, ``ValueError`` (with ``UnicodeDecodeError`` and
``JSONDecodeError``), ``MemoryError``, and ``OverflowError`` as DAMAGED; anything else is a
programmer error. ``vnsave`` is checked first: a later format is NEWER whatever else the file
holds. Then ``state_format`` and ``state_rev`` (``GameState``'s ``STATE_REVISION``): a higher
one is NEWER before line 3 is read, so a save from a later engine is never DAMAGED for a key
this one doesn't know. ``vnsave`` 1 (development saves, before ``state_rev``) still loads, as
revision 0. Only an OK head decodes line 2 (base64, then ``check_engine_jpeg``; SEC-F11-01, -02).
The full read pre-scans line 3's structure bytes before ``json.loads`` and validates it with
``GameState.from_json``.

**Statuses**: EMPTY (no entry), OK, DAMAGED (``cause`` ENTRY: not a regular file, unreadable,
over the size cap, nothing read; CONTENT: a regular file with bad bytes), NEWER, OTHER_GAME.
``reason`` is the dev reason word of W82 (``04`` §7.6), never file text.
"""

import base64
import json
import os
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

from engine.core import safefile
from engine.core.imageheader import check_engine_jpeg
from engine.core.paths import is_valid_app_id
from engine.core.safefile import ReadKind, Stamp
from engine.persist import fileformat, limits
from engine.runtime.state import STATE_FORMAT, STATE_REVISION, GameState, StateInvalid

SlotPage = Literal["auto", "quick"] | int              # int: 1 .. SAVE_PAGES_MAX
THUMB_SIZE = (320, 180)                                 # render/thumbnail.THUMB_SIZE
DESCRIPTION_LINE_MAX = 50                               # §7.2: a line's text, then "…"
SLOT_NAME_RE = re.compile(r"(auto|quick|page(?:[1-9][0-9]?|100))-[1-6]\.vnsave", re.ASCII)

# Exactly the meta keys, in the order the encoder writes them (``vnsave`` first, §4).
META_KEYS = ("vnsave", "game", "seq", "saved_at", "description", "chapter", "game_version",
             "state_format", "state_rev", "thumb", "state")
_META_KEY_SET = frozenset(META_KEYS)
_META_KEYS_V1 = _META_KEY_SET - {"state_rev"}          # ``vnsave`` 1: development saves
REVISION_MAX = 1_000_000                                # ``state_rev``'s range on read

# The parse and validation errors both readers turn into DAMAGED (§7.5; SEC-F11-06).
PARSE_ERRORS = (RecursionError, ValueError, MemoryError, OverflowError)

# W82 reason words (``04`` §7.6's table). Never contain file text.
REASON_GONE = "the file is gone"
REASON_UNREADABLE = "the file couldn't be read"
REASON_NOT_REGULAR = "not a regular file"
REASON_TOO_BIG = "over the size limit"
REASON_META = "meta line"
REASON_LENGTHS = "line lengths"
REASON_NOT_ASCII = "not ASCII"
REASON_STRUCTURE = "too much structure"
REASON_JSON = "not valid JSON"
REASON_OTHER_GAME = "it was made by a different game"
# TooLarge reasons (W83 ``too large (<reason>)``, §12); ``save_problem`` adds its own words.
TOO_LARGE_STATE = "state over 24 MiB"
TOO_LARGE_STRUCTURE = "too much structure"

# A later save format is recognized from the line's first bytes, before any parse (§4).
_NEWER_PREFIX = re.compile(rb'\{"vnsave":([0-9]{1,16})[,}]')
_THUMB_LINE = re.compile(rb'\{"jpeg":(?:null|"([A-Za-z0-9+/]*={0,2})")\}\n')
THUMB_LINE_RE = _THUMB_LINE                             # line 2's one pattern (F20 node files)
_STRUCTURE_BYTES = (b"{", b"[", b",", b":")
_DUMP_ARGS = {"ensure_ascii": True, "separators": (",", ":"), "allow_nan": False}
_JOIN_BYTES = 1 << 16                                   # encoder: small pieces joined to 64 KiB


def story_reason(reason: str) -> str:
    """W82's reason for a state ``GameState.from_json`` refuses."""
    return f"story state ({reason})"


def _format_reason(kind: str, n: int) -> str:
    shown = str(n) if n < 10**16 else "?"                # never a 4,300-digit echo
    return f"made with {kind} format {shown}"


# --- Slots -----------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SlotId:
    """One slot: ``page`` is ``"auto"``, ``"quick"``, or 1 … ``SAVE_PAGES_MAX``; ``n`` is
    1 … 6. Anything else raises ``ValueError`` (a programmer error, §12)."""

    page: SlotPage
    n: int

    def __post_init__(self) -> None:
        page = self.page
        named = type(page) is str and page in ("auto", "quick")
        numbered = type(page) is int and 1 <= page <= limits.SAVE_PAGES_MAX
        if not (named or numbered):
            raise ValueError(f"no save page {page!r}")
        if type(self.n) is not int or not 1 <= self.n <= limits.SLOTS_PER_PAGE:
            raise ValueError(f"no save slot {self.n!r}")

    def file_name(self) -> str:
        """``auto-2.vnsave``, ``quick-1.vnsave``, ``page3-6.vnsave``."""
        prefix = self.page if type(self.page) is str else f"page{self.page}"
        return f"{prefix}-{self.n}.vnsave"

    @staticmethod
    def from_name(name: str) -> "SlotId | None":
        """The slot a file name fully matching ``SLOT_NAME_RE`` (case-exact) names."""
        match = SLOT_NAME_RE.fullmatch(name) if type(name) is str else None
        if match is None:
            return None
        prefix = match[1]
        n = int(name[-len("1.vnsave")])
        return SlotId(prefix if prefix in ("auto", "quick") else int(prefix[4:]), n)


def page_slots(page: SlotPage) -> list[SlotId]:
    """The six slots of a page, in order."""
    return [SlotId(page, n) for n in range(1, limits.SLOTS_PER_PAGE + 1)]


def all_slots(pages: int) -> list[SlotId]:
    """Every slot the game shows: Auto, Quick, then pages 1 … ``pages`` (612 at 100)."""
    out = page_slots("auto") + page_slots("quick")
    for page in range(1, pages + 1):
        out.extend(page_slots(page))
    return out


def slot_order(slot: SlotId) -> tuple[int, int, int]:
    """A sort key: Auto, Quick, then pages in number order; slots by number."""
    if slot.page == "auto":
        return (0, 0, slot.n)
    if slot.page == "quick":
        return (1, 0, slot.n)
    return (2, int(slot.page), slot.n)


# --- Results ---------------------------------------------------------------------------------

class SlotStatus(Enum):
    EMPTY = "empty"
    OK = "ok"
    DAMAGED = "damaged"
    NEWER = "newer"
    OTHER_GAME = "other_game"


class Cause(Enum):
    """Why a slot is DAMAGED. Rotation reuses only CONTENT slots (SEC-F11-05)."""

    CONTENT = "content"      # a regular file was read and its bytes were bad
    ENTRY = "entry"          # not read: not a regular file, unreadable, over the size cap


@dataclass(frozen=True, slots=True)
class SaveMeta:
    """Line 1, validated (§4's table)."""

    seq: int
    saved_at: int
    description: str
    chapter: str | None
    game: str | None
    game_version: str
    state_format: int
    thumb_len: int
    state_len: int
    state_rev: int = 0                                  # 0: a ``vnsave`` 1 file


@dataclass(frozen=True, slots=True)
class SlotHead:
    """What a page knows of a slot from at most ``HEAD_MAX`` bytes. ``meta`` for OK, NEWER
    by ``state_format``, and OTHER_GAME; ``jpeg`` only for OK heads read with ``thumb=True``
    whose line 2 passed ``check_engine_jpeg``; ``reason`` is "" when OK."""

    slot: SlotId
    status: SlotStatus
    cause: Cause | None
    meta: SaveMeta | None
    jpeg: bytes | None
    stamp: Stamp | None
    reason: str


@dataclass(frozen=True, slots=True)
class FullRead:
    """A load's read: ``state`` only when OK."""

    status: SlotStatus
    cause: Cause | None
    meta: SaveMeta | None
    state: GameState | None
    reason: str


@dataclass(frozen=True, slots=True)
class TooLarge:
    """The encoder refused the state (W83 ``too large (<reason>)``)."""

    reason: str


@dataclass(frozen=True, slots=True)
class Lines:
    """``split_lines``' result: line 1 without its ``\\n``, and the ``(start, end)`` byte
    offsets of lines 2 and 3 with their ``\\n`` (None before the lengths are known)."""

    meta: bytes
    thumb: tuple[int, int] | None
    state: tuple[int, int] | None


# --- The one parser (SEC-F11-07) -------------------------------------------------------------

def strict_loads(line: bytes | memoryview) -> object:
    """The one parser of save bytes: an ASCII decode to ``str`` (``UnicodeDecodeError`` on
    any other byte), then F12's ``json.loads`` with the hooks refusing duplicate keys,
    NaN and Infinity, and ints over 4,300 digits (``fileformat.parse``, SEC-F12-01). Raises
    only the ``PARSE_ERRORS``."""
    return fileformat.parse(str(line, "ascii"))


def split_lines(data: bytes, size: int,
                lengths: tuple[int, int] | None = None) -> Lines | str:
    """The line boundaries both readers share (§7.5), or a reason word.

    Line 1 is the bytes before the first ``\\n``, which must lie within ``META_MAX``. With
    the meta's ``(thumb, state)`` lengths: ``len(line 1) + 1 + thumb + state == size`` (the
    ``fstat`` size), each declared boundary byte is ``\\n``, and line 2 holds no other
    ``\\n``. ``data`` may be only the file's first bytes (a page's head): boundaries are
    checked only for the bytes it holds."""
    end1 = data.find(b"\n", 0, limits.META_MAX)
    if end1 < 0:
        return REASON_META
    if lengths is None:
        return Lines(data[:end1], None, None)
    thumb, state = lengths
    start2 = end1 + 1
    end2 = start2 + thumb
    end3 = end2 + state
    have = len(data)
    if thumb < 1 or state < 1 or end3 != size or have > size:
        return REASON_LENGTHS
    if end2 <= have:
        if data[end2 - 1] != 0x0A or data.find(b"\n", start2, end2 - 1) >= 0:
            return REASON_LENGTHS
    elif data.find(b"\n", start2, have) >= 0:
        return REASON_LENGTHS
    if end3 <= have and data[end3 - 1] != 0x0A:
        return REASON_LENGTHS
    return Lines(data[:end1], (start2, end2), (end2, end3))


def _int_in(value: object, low: int, high: int | None = None) -> bool:
    return type(value) is int and low <= value and (high is None or value <= high)


def _text(value: object, cap: int) -> bool:
    return type(value) is str and len(value) <= cap


def meta_of(obj: object) -> SaveMeta | None:
    """Line 1 as ``SaveMeta`` if it has exactly §4's keys with their types and ranges: this
    ``vnsave`` with ``state_rev``, or ``vnsave`` 1 without it (read as revision 0)."""
    if type(obj) is not dict or type(obj.get("vnsave")) is not int:
        return None
    version = obj["vnsave"]
    if version == limits.SAVE_FORMAT and obj.keys() == _META_KEY_SET:
        rev = obj["state_rev"]
        if not _int_in(rev, 1, REVISION_MAX):
            return None
    elif version == 1 and obj.keys() == _META_KEYS_V1:
        rev = 0
    else:
        return None
    game, chapter = obj["game"], obj["chapter"]
    if not ((game is None or is_valid_app_id(game))
            and _int_in(obj["seq"], 1, limits.SEQ_MAX)
            and _int_in(obj["saved_at"], 0, limits.SAVED_AT_MAX)
            and _text(obj["description"], limits.DESCRIPTION_MAX)
            and (chapter is None or _text(chapter, limits.DESCRIPTION_MAX))
            and _text(obj["game_version"], limits.VERSION_MAX)
            and _int_in(obj["state_format"], 1)
            and _int_in(obj["thumb"], 1, limits.THUMB_LINE_MAX)
            and _int_in(obj["state"], 1, limits.STATE_MAX_BYTES)):
        return None
    return SaveMeta(seq=obj["seq"], saved_at=obj["saved_at"], description=obj["description"],
                    chapter=chapter, game=game, game_version=obj["game_version"],
                    state_format=obj["state_format"], thumb_len=obj["thumb"],
                    state_len=obj["state"], state_rev=rev)


@dataclass(frozen=True, slots=True)
class _Verdict:
    status: SlotStatus
    cause: Cause | None = None
    meta: SaveMeta | None = None
    reason: str = ""
    lines: Lines | None = None


def _damaged(reason: str, cause: Cause = Cause.CONTENT) -> _Verdict:
    return _Verdict(SlotStatus.DAMAGED, cause, None, reason)


def _classify(data: bytes, size: int, game_id: str | None) -> _Verdict:
    """Head steps 1–3 (§7.5), shared by both readers: the size cap, ``vnsave`` first, the
    meta table, NEWER and OTHER_GAME, then the line lengths and boundaries."""
    if size > limits.SAVE_FILE_MAX:
        return _damaged(REASON_TOO_BIG, Cause.ENTRY)
    prefix = _NEWER_PREFIX.match(data)
    if prefix is not None and int(prefix[1]) > limits.SAVE_FORMAT:
        return _Verdict(SlotStatus.NEWER, reason=_format_reason("save", int(prefix[1])))
    try:
        first = split_lines(data, size)
        if type(first) is str:
            return _damaged(first)
        obj = strict_loads(first.meta)
        version = obj.get("vnsave") if type(obj) is dict else None
        if type(version) is int and version > limits.SAVE_FORMAT:
            return _Verdict(SlotStatus.NEWER, reason=_format_reason("save", version))
        meta = meta_of(obj)
        if meta is None:
            return _damaged(REASON_META)
        lines = split_lines(data, size, (meta.thumb_len, meta.state_len))
    except PARSE_ERRORS:
        return _damaged(REASON_META)
    if type(lines) is str:
        return _damaged(lines)
    if meta.state_format > STATE_FORMAT:
        return _Verdict(SlotStatus.NEWER, None, meta,
                        _format_reason("state", meta.state_format), lines)
    if meta.state_rev > STATE_REVISION:
        return _Verdict(SlotStatus.NEWER, None, meta,
                        f"made with state revision {meta.state_rev}", lines)
    if meta.game is not None and game_id is not None and meta.game != game_id:
        return _Verdict(SlotStatus.OTHER_GAME, None, meta, REASON_OTHER_GAME, lines)
    return _Verdict(SlotStatus.OK, None, meta, "", lines)


def _thumbnail(data: bytes, span: tuple[int, int]) -> bytes | None:
    """Head step 4 (OK heads only): line 2 by a regex (no JSON parse), base64 with
    ``validate=True``, then ``check_engine_jpeg``. None means "No picture"."""
    start, end = span
    if end > len(data):
        return None
    match = _THUMB_LINE.fullmatch(data, start, end)
    if match is None or match[1] is None:
        return None
    try:
        jpeg = base64.b64decode(match[1], validate=True)
    except ValueError:                                  # binascii.Error: bad padding
        return None
    return jpeg if check_engine_jpeg(jpeg, THUMB_SIZE) else None


def classify_head(data: bytes, size: int, slot: SlotId, *, game_id: str | None, thumb: bool,
                  stamp: Stamp | None = None) -> SlotHead:
    """A page's verdict on a slot's first bytes (pure). ``size`` is the whole file's
    ``fstat`` size; ``thumb`` decodes line 2 of an OK head."""
    verdict = _classify(data, size, game_id)
    jpeg = None
    if thumb and verdict.status is SlotStatus.OK and verdict.lines is not None:
        assert verdict.lines.thumb is not None
        jpeg = _thumbnail(data, verdict.lines.thumb)
    return SlotHead(slot, verdict.status, verdict.cause, verdict.meta, jpeg, stamp,
                    verdict.reason)


def parse_full(data: bytes, *, game_id: str | None) -> FullRead:
    """A load's verdict on a whole file (pure): the head steps, then line 3: the structure
    pre-scan (``SAVE_PRESCAN_MAX``) before ``strict_loads``; ``format`` > ``STATE_FORMAT``
    → NEWER; ``GameState.from_json`` (``unknown_key`` → NEWER, other refusals → DAMAGED).
    Line 2 is never decoded here."""
    verdict = _classify(data, len(data), game_id)
    if verdict.status is not SlotStatus.OK:
        return FullRead(verdict.status, verdict.cause, verdict.meta, None, verdict.reason)
    assert verdict.lines is not None and verdict.lines.state is not None
    line = parse_state_line(data, verdict.lines.state)
    if line.status is SlotStatus.DAMAGED:
        return FullRead(SlotStatus.DAMAGED, Cause.CONTENT, None, None, line.reason)
    if line.status is SlotStatus.NEWER:
        return FullRead(SlotStatus.NEWER, None, verdict.meta, None, line.reason)
    return FullRead(SlotStatus.OK, None, verdict.meta, line.state, "")


@dataclass(frozen=True, slots=True)
class StateLine:
    """``parse_state_line``'s verdict: OK with ``state``, or DAMAGED or NEWER with a reason
    word (never file text)."""

    status: SlotStatus
    state: GameState | None
    reason: str


def parse_state_line(data: bytes, span: tuple[int, int]) -> StateLine:
    """Line 3 of a three-line file (pure). F11's ``parse_full`` and F20's ``parse_node``
    share it by identity (F20 A8). ``span`` is the line's ``(start, end)`` with its
    ``\\n``, as ``split_lines`` gives it. The structure pre-scan (``SAVE_PRESCAN_MAX``)
    runs before ``strict_loads``; ``format`` > ``STATE_FORMAT`` → NEWER;
    ``GameState.from_json`` (``unknown_key`` → NEWER, other refusals → DAMAGED)."""
    start, end = span
    end -= 1                                            # the "\n"
    if sum(data.count(c, start, end) for c in _STRUCTURE_BYTES) > limits.SAVE_PRESCAN_MAX:
        return StateLine(SlotStatus.DAMAGED, None, REASON_STRUCTURE)
    try:
        obj = strict_loads(memoryview(data)[start:end])
    except UnicodeDecodeError:
        return StateLine(SlotStatus.DAMAGED, None, REASON_NOT_ASCII)
    except PARSE_ERRORS:
        return StateLine(SlotStatus.DAMAGED, None, REASON_JSON)
    fmt = obj.get("format") if type(obj) is dict else None
    if type(fmt) is int and fmt > STATE_FORMAT:
        return StateLine(SlotStatus.NEWER, None, _format_reason("state", fmt))
    try:
        state = GameState.from_json(obj)
    except StateInvalid as error:
        status = SlotStatus.NEWER if error.reason == "unknown_key" else SlotStatus.DAMAGED
        return StateLine(status, None, story_reason(error.reason))
    except PARSE_ERRORS:
        return StateLine(SlotStatus.DAMAGED, None, story_reason("malformed"))
    return StateLine(SlotStatus.OK, state, "")


# --- Reading from the folder -----------------------------------------------------------------

def _entry_verdict(kind: ReadKind) -> _Verdict:
    if kind is ReadKind.MISSING:
        return _Verdict(SlotStatus.EMPTY, reason=REASON_GONE)
    if kind is ReadKind.NOT_REGULAR:
        return _damaged(REASON_NOT_REGULAR, Cause.ENTRY)
    if kind is ReadKind.TOO_LARGE:
        return _damaged(REASON_TOO_BIG, Cause.ENTRY)
    return _damaged(REASON_UNREADABLE, Cause.ENTRY)


def _size_first(path: Path) -> _Verdict | Stamp | None:
    """The entry's ``lstat``: EMPTY when missing, DAMAGED (ENTRY) over ``SAVE_FILE_MAX``
    with nothing read (a 4 GiB sparse file costs one ``lstat``); else its stamp, or None
    when ``lstat`` failed (the read then reports it)."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return _Verdict(SlotStatus.EMPTY, reason=REASON_GONE)
    except (OSError, ValueError):
        return None
    if st.st_size > limits.SAVE_FILE_MAX:
        return _damaged(REASON_TOO_BIG, Cause.ENTRY)
    return Stamp.of(st)


def _head(slot: SlotId, verdict: _Verdict, stamp: Stamp | None = None) -> SlotHead:
    reason = "" if verdict.status is SlotStatus.EMPTY else verdict.reason
    return SlotHead(slot, verdict.status, verdict.cause, verdict.meta, None, stamp, reason)


def read_slot_head(folder: Path, slot: SlotId, *, game_id: str | None, thumb: bool,
                   max_bytes: int | None = None) -> SlotHead:
    """A page's read of one slot: at most ``HEAD_MAX`` bytes (``max_bytes``: the index
    reads ``META_MAX``) through ``safefile.read_head`` (``lstat`` regular, no-follow open,
    ``fstat`` the same file), then ``classify_head``."""
    path = Path(folder) / slot.file_name()
    cap = limits.HEAD_MAX if max_bytes is None else max_bytes
    first = _size_first(path)
    if isinstance(first, _Verdict):
        return _head(slot, first)
    result = safefile.read_head(path, cap)
    if not result.ok:
        return _head(slot, _entry_verdict(result.kind), result.stamp)
    assert result.data is not None and result.stamp is not None
    if len(result.data) != min(result.stamp.size, cap):  # changed while it was read
        return _head(slot, _damaged(REASON_LENGTHS), result.stamp)
    return classify_head(result.data, result.stamp.size, slot, game_id=game_id, thumb=thumb,
                         stamp=result.stamp)


def read_slot_full(folder: Path, slot: SlotId, *, game_id: str | None) -> FullRead:
    """A load's read: the whole file once through ``safefile.read_regular`` (at most
    ``SAVE_FILE_MAX`` + 1 bytes; over the cap by ``lstat`` reads nothing), then
    ``parse_full``. One step (§11)."""
    path = Path(folder) / slot.file_name()
    first = _size_first(path)
    if isinstance(first, _Verdict):
        return FullRead(first.status, first.cause, None, None, first.reason)
    result = safefile.read_regular(path, limits.SAVE_FILE_MAX)
    if not result.ok:
        verdict = _entry_verdict(result.kind)
        return FullRead(verdict.status, verdict.cause, None, None, verdict.reason)
    assert result.data is not None and result.stamp is not None
    data, size = result.data, result.stamp.size
    del result
    if len(data) != size:                               # grew or shrank while it was read
        return FullRead(SlotStatus.DAMAGED, Cause.CONTENT, None, None, REASON_LENGTHS)
    return parse_full(data, game_id=game_id)


# --- Encoding (§7.3) -------------------------------------------------------------------------

def _dump(value: object) -> bytes:
    return json.dumps(value, **_DUMP_ARGS).encode("ascii")


def iter_pieces(obj: object, split_depth: int = 3) -> Iterator[bytes]:
    """``json.dumps(obj, ensure_ascii=True, separators=(",", ":"), allow_nan=False)`` in
    pieces (TR-F11-02). Non-empty dicts and lists above ``split_depth`` are written as
    ``{`` … ``}`` and ``[`` … ``]`` around their members: a member that is itself split
    gets a ``,"key":`` piece (the key through ``json.dumps``); runs of the other members
    are written by one ``json.dumps`` of the run (a list, or a dict of those pairs) without
    its brackets, so every key and value still goes through ``json.dumps``. Runs grow and
    shrink to keep pieces near 16–64 KiB (a unit of the encoder's slices). A dict with a key
    that isn't exactly ``str`` is dumped whole, so the joined bytes always equal the
    one-shot dump (and raise what it raises)."""
    if split_depth > 0 and _splittable(obj):
        yield from _split(obj, split_depth)                     # type: ignore[arg-type]
    else:
        yield _dump(obj)


def _splittable(obj: object) -> bool:
    if isinstance(obj, dict):
        return bool(obj) and all(type(k) is str for k in obj)
    return isinstance(obj, (list, tuple)) and bool(obj)


def _split(obj: dict | list | tuple, depth: int) -> Iterator[bytes]:
    is_dict = isinstance(obj, dict)
    yield b"{" if is_dict else b"["
    comma = b""
    run: list = []
    limit = 64
    for item in (obj.items() if is_dict else obj):          # type: ignore[union-attr]
        value = item[1] if is_dict else item
        if depth > 1 and _splittable(value):
            if run:
                yield comma + _run(run, is_dict)
                comma, run = b",", []
            head = comma + (_dump(item[0]) + b":" if is_dict else b"")
            if head:
                yield head
            comma = b","
            yield from _split(value, depth - 1)
            continue
        run.append(item)
        if len(run) >= limit:
            piece = _run(run, is_dict)
            yield comma + piece
            comma, run = b",", []
            if len(piece) < 16_384:
                limit = min(limit * 2, 4_096)
            elif len(piece) > 65_536:
                limit = max(limit // 2, 1)
    if run:
        yield comma + _run(run, is_dict)
    yield b"}" if is_dict else b"]"


def _run(run: list, is_dict: bool) -> bytes:
    """Members as ``json.dumps`` writes them inside their container: ``a,b`` / ``"k":v``."""
    return _dump(dict(run) if is_dict else run)[1:-1]


def count_structure(piece: bytes) -> int:
    """The pre-scan's count: ``{``, ``[``, ``,``, and ``:`` bytes (F12's rule)."""
    return fileformat.count_structure(piece)


def save_problem(state: GameState) -> str | None:
    """C11: F03's ``GameState.save_problem()``: a reason word (W83 ``too large (<word>)``)
    if the state, written and read back, wouldn't load equal (``from_json`` would refuse
    what ``take_checkpoint`` allowed, or a lone surrogate), else None."""
    return state.save_problem()


def thumb_line(jpeg: bytes | None) -> bytes:
    """Line 2: ``{"jpeg":"<base64>"}`` for bytes ``check_engine_jpeg`` accepts, else
    ``{"jpeg":null}`` (with its ``\\n``)."""
    if isinstance(jpeg, bytes) and check_engine_jpeg(jpeg, THUMB_SIZE):
        return b'{"jpeg":"' + base64.b64encode(jpeg) + b'"}\n'
    return b'{"jpeg":null}\n'


def _clamp(value: object, low: int, high: int) -> int:
    return min(max(value, low), high) if type(value) is int else low


def _cut(value: object, cap: int) -> str:
    return value[:cap] if type(value) is str else ""


class StateEncoder:
    """Makes one three-line file's pieces in slices on the main thread (§7.3), shared by
    F11's ``SaveEncoder`` and F20's ``NodeEncoder`` (F20 ``04`` §5): ``step(deadline,
    clock)`` does one unit of work, then more until ``clock()`` passes ``deadline``, and
    returns True when ``result`` is set: the pieces ``(line 1, line 2, *state pieces,
    b"\\n")`` or ``TooLarge``. Line 3 is ``iter_pieces`` of ``state.to_json()`` under the
    ``STATE_MAX_BYTES`` and ``SAVE_PRESCAN_MAX`` caps; line 1 is the subclass's
    ``meta_fields``, written by ``json.dumps(ensure_ascii=True)``.

    ``pieces_from``: a finished encoder of the same checkpoint object whose state pieces are
    reused (F5 held). ``structure`` is the running pre-scan count of line 3."""

    def __init__(self, state: GameState, *, jpeg: bytes | None = None,
                 pieces_from: "StateEncoder | None" = None) -> None:
        self.state = state
        self._jpeg = jpeg
        self.result: tuple[bytes, ...] | TooLarge | None = None
        self.state_pieces: tuple[bytes, ...] | None = None
        self.size = 0                                   # line 3 bytes so far, no "\n"
        self.structure = 0
        self.steps = 0
        self._chunks: list[bytes] = []
        self._buffer: list[bytes] = []
        self._buffered = 0
        self._pieces: Iterator[bytes] | None = None
        self._thumb: bytes | None = None
        if (pieces_from is not None and pieces_from.state is state
                and pieces_from.state_pieces is not None):
            self.state_pieces = pieces_from.state_pieces
            self.size = pieces_from.size
            self.structure = pieces_from.structure

    def step(self, deadline: float, clock: Callable[[], float]) -> bool:
        if self.result is not None:
            return True
        self.steps += 1
        while not self._unit():
            if clock() > deadline:
                return False
        return True

    def run(self) -> tuple[bytes, ...] | TooLarge:
        """Every step at once (the quit auto-save, tests)."""
        self.step(float("inf"), lambda: 0.0)
        assert self.result is not None
        return self.result

    def _unit(self) -> bool:
        """One unit of work; True when ``result`` is set."""
        if self._thumb is None:
            self._thumb = thumb_line(self._jpeg)
            return False
        if self.state_pieces is None and self._pieces is None:
            problem = save_problem(self.state)
            if problem is not None:
                return self._refuse(problem)
            self._pieces = iter_pieces(self.state.to_json())
            return False
        if self.state_pieces is None:
            assert self._pieces is not None
            piece = next(self._pieces, None)
            if piece is None:
                self._flush()
                if self.result is not None:
                    return True
                self.state_pieces = tuple(self._chunks)
                self._pieces = None
                return False
            self.size += len(piece)
            if self.size + 1 > limits.STATE_MAX_BYTES:
                return self._refuse(TOO_LARGE_STATE)
            self._buffer.append(piece)
            self._buffered += len(piece)
            if self._buffered >= _JOIN_BYTES:
                self._flush()
            return self.result is not None
        return self._finish()

    def _flush(self) -> None:
        if not self._buffer:
            return
        chunk = self._buffer[0] if len(self._buffer) == 1 else b"".join(self._buffer)
        self._buffer.clear()
        self._buffered = 0
        self.structure += count_structure(chunk)
        if self.structure > limits.SAVE_PRESCAN_MAX:
            self._refuse(TOO_LARGE_STRUCTURE)
            return
        self._chunks.append(chunk)

    def _refuse(self, reason: str) -> bool:
        self.result = TooLarge(reason)
        self._chunks.clear()
        self._buffer.clear()
        self._pieces = None
        return True

    def _finish(self) -> bool:
        assert self._thumb is not None and self.state_pieces is not None
        line1 = _dump(self.meta_fields(len(self._thumb), self.size + 1)) + b"\n"
        if len(line1) > limits.META_MAX:                # unreachable with §4's cuts
            return self._refuse(REASON_META)
        self.result = (line1, self._thumb, *self.state_pieces, b"\n")
        return True

    def meta_fields(self, thumb: int, state: int) -> dict[str, object]:
        """Line 1's object, keys in write order; ``thumb`` and ``state`` are the byte
        lengths of lines 2 and 3 with their ``\\n``."""
        raise NotImplementedError


class SaveEncoder(StateEncoder):
    """One save's pieces (§7.3). Every field of line 1 is clamped and cut to the reader's
    limits and every string is written by ``json.dumps(ensure_ascii=True)``, so every file
    this writes passes ``parse_full`` whatever the folder holds (SEC-F11-04, TR-F11-01)."""

    def __init__(self, state: GameState, *, seq: int, saved_at: int, description: str,
                 chapter: str | None, game: str | None, game_version: str,
                 jpeg: bytes | None, pieces_from: "StateEncoder | None" = None) -> None:
        super().__init__(state, jpeg=jpeg, pieces_from=pieces_from)
        self._fields = {
            "seq": _clamp(seq, 1, limits.SEQ_MAX),
            "saved_at": _clamp(saved_at, 0, limits.SAVED_AT_MAX),
            "description": _cut(description, limits.DESCRIPTION_MAX),
            "chapter": chapter[:limits.DESCRIPTION_MAX] if type(chapter) is str else None,
            "game": game if is_valid_app_id(game) else None,
            "game_version": _cut(game_version, limits.VERSION_MAX),
        }

    def meta_fields(self, thumb: int, state: int) -> dict[str, object]:
        fields = self._fields
        return {"vnsave": limits.SAVE_FORMAT, "game": fields["game"], "seq": fields["seq"],
                "saved_at": fields["saved_at"], "description": fields["description"],
                "chapter": fields["chapter"], "game_version": fields["game_version"],
                "state_format": STATE_FORMAT, "state_rev": STATE_REVISION, "thumb": thumb,
                "state": state}


def encode_save(state: GameState, **fields: object) -> tuple[bytes, ...] | TooLarge:
    """``SaveEncoder(state, **fields).run()``: every step at once."""
    return SaveEncoder(state, **fields).run()           # type: ignore[arg-type]


# --- Description (§7.2) ----------------------------------------------------------------------

def describe(state: GameState, chapter: str | None) -> str:
    """The slot's description: ``chapter`` (F18's provider) when it is a non-blank
    ``str``, cut to ``DESCRIPTION_MAX``; else the newest F13 history entry of kind ``line``
    as ``name: text`` (or ``text`` when ``name`` is ""), whitespace runs as one space,
    ``text`` cut to 50 code points plus "…"; else "" (no history, or F13 not built)."""
    if type(chapter) is str and chapter.strip():
        return chapter[:limits.DESCRIPTION_MAX]
    entries = getattr(getattr(state, "history", None), "entries", None) or ()
    for entry in reversed(entries):
        if getattr(entry, "kind", None) != "line":
            continue
        text = " ".join(str(entry.text).split())
        if len(text) > DESCRIPTION_LINE_MAX:
            text = text[:DESCRIPTION_LINE_MAX] + "…"
        name = " ".join(str(entry.name).split())
        return f"{name}: {text}" if name else text
    return ""


# --- Rotation, Newest, seq (§7.4; SEC-F11-04a, -05) ------------------------------------------

def _order_key(head: SlotHead, order: Mapping[SlotId, int] | None) -> tuple[int, int]:
    assert head.meta is not None
    return (head.meta.seq, (order or {}).get(head.slot, 0))


def rotation_target(heads: Sequence[SlotHead], *, skip: Iterable[SlotId] = (),
                    order: Mapping[SlotId, int] | None = None) -> int | None:
    """The slot number an Auto or Quick save goes to, given the page's six heads (re-read
    first): the first EMPTY; else the first DAMAGED with ``cause`` CONTENT; else the OK slot
    with the lowest (``seq``, session write order), ties to the lower number. Never NEWER,
    OTHER_GAME, DAMAGED by ENTRY, or a slot in ``skip`` (writes failed this session). None
    when nothing is left (``save_reason_slots``). ``order``: each slot's session write
    counter (files read from disk count 0)."""
    skipped = set(skip)
    usable = sorted((h for h in heads if h.slot not in skipped), key=lambda h: h.slot.n)
    for head in usable:
        if head.status is SlotStatus.EMPTY:
            return head.slot.n
    for head in usable:
        if head.status is SlotStatus.DAMAGED and head.cause is Cause.CONTENT:
            return head.slot.n
    ok = [h for h in usable if h.status is SlotStatus.OK and h.meta is not None]
    if not ok:
        return None
    return min(ok, key=lambda h: (_order_key(h, order), h.slot.n)).slot.n


def newest(heads: Iterable[SlotHead], *,
           order: Mapping[SlotId, int] | None = None) -> SlotId | None:
    """The OK slot with the highest (``seq``, session write order), ties to the lower slot
    number: the Newest tag, and Q.Load's target among quick slots."""
    ok = [h for h in heads if h.status is SlotStatus.OK and h.meta is not None]
    if not ok:
        return None
    best = max(ok, key=lambda h: (_order_key(h, order), -h.slot.n))
    return best.slot


def next_seq(heads: Iterable[SlotHead]) -> int:
    """``min(max(seq of OK heads) + 1, SEQ_MAX)``; 1 with none. DAMAGED, NEWER, and
    OTHER_GAME heads are ignored, and a hostile ``seq`` of 2⁵³ saturates there, so a
    written file always reads back (SEC-F11-04a)."""
    best = 0
    for head in heads:
        if head.status is SlotStatus.OK and head.meta is not None:
            best = max(best, head.meta.seq)
    return min(best + 1, limits.SEQ_MAX)


# --- The slot index (§7.4; SEC-F11-13) -------------------------------------------------------

class IndexJob:
    """Lists and reads the saves folder in slices: one ``os.scandir`` (at most
    ``INDEX_MAX_EXAMINED`` entries, links not followed, names fully matching
    ``SLOT_NAME_RE`` within ``pages``); if the cap is reached, the fixed slot names instead
    (junk can't hide saves). Then each listed slot's meta (``read_slot_head`` of
    ``META_MAX`` bytes, ``thumb=False``) per ``step`` until the deadline. ``heads`` holds
    every non-EMPTY slot read; ``finish()`` runs the rest at once (a save requested before
    the job ends).

    The scandir stays open across steps and one step lists at most
    ``INDEX_STEP_EXAMINED`` entries (F20 ``07`` I-4: the saves root may also hold 4,000
    node files, and listing 4,612 entries at once takes longer than ``SAVE_STEP_S``).
    ``close()`` (also on garbage collection) closes an unfinished listing."""

    def __init__(self, folder: Path, *, game_id: str | None, pages: int) -> None:
        self.folder = Path(folder)
        self.game_id = game_id
        self.pages = pages
        self.heads: dict[SlotId, SlotHead] = {}
        self.done = False
        self.fell_back = False
        self.examined = 0
        self.steps = 0
        self._todo: list[SlotId] | None = None
        self._next = 0
        self._scan: object | None = None                # the open scandir (context manager)
        self._entries: Iterator[os.DirEntry] | None = None
        self._found: list[SlotId] = []

    def step(self, deadline: float, clock: Callable[[], float]) -> bool:
        if self.done:
            return True
        self.steps += 1
        if self._todo is None:
            self._todo = self._list()
            if self._todo is None or clock() > deadline:
                return self._check_done()
        while self._next < len(self._todo):
            slot = self._todo[self._next]
            self._next += 1
            head = read_slot_head(self.folder, slot, game_id=self.game_id, thumb=False,
                                  max_bytes=limits.META_MAX)
            if head.status is not SlotStatus.EMPTY:
                self.heads[slot] = head
            if clock() >= deadline:                     # ≤ SAVE_STEP_S per frame
                break
        return self._check_done()

    def finish(self) -> dict[SlotId, SlotHead]:
        while not self.step(float("inf"), lambda: 0.0):
            pass
        return self.heads

    def close(self) -> None:
        """Close an unfinished listing (an abandoned job)."""
        scan = getattr(self, "_scan", None)
        self._scan, self._entries = None, None
        if scan is not None:
            try:
                scan.__exit__(None, None, None)         # type: ignore[attr-defined]
            except OSError:
                pass

    def __del__(self) -> None:
        self.close()

    def _check_done(self) -> bool:
        self.done = self._todo is not None and self._next >= len(self._todo)
        return self.done

    def _shown(self, slot: SlotId) -> bool:
        return type(slot.page) is str or slot.page <= self.pages

    def _list(self) -> list[SlotId] | None:
        """At most ``INDEX_STEP_EXAMINED`` more entries of the one listing; the slots to
        read once it is complete, else None. An ``OSError`` lists nothing."""
        cap = limits.INDEX_MAX_EXAMINED
        try:
            if self._entries is None:
                scan = os.scandir(self.folder)
                self._scan = scan
                self._entries = iter(scan.__enter__())
            entries = self._entries
            for _ in range(max(1, limits.INDEX_STEP_EXAMINED)):
                entry = next(entries, None)
                if entry is None:
                    break
                if self.examined >= cap:
                    self.fell_back = True
                    break
                self.examined += 1
                slot = SlotId.from_name(entry.name)
                if slot is not None and self._shown(slot):
                    self._found.append(slot)
            else:
                return None                             # more entries: the next step lists on
        except OSError:
            self.close()
            self._found = []
            return []
        self.close()
        found, self._found = self._found, []
        if self.fell_back:
            return all_slots(self.pages)
        return sorted(found, key=slot_order)


__all__ = ["Cause", "FullRead", "IndexJob", "Lines", "META_KEYS", "PARSE_ERRORS",
           "SLOT_NAME_RE", "SaveEncoder", "SaveMeta", "SlotHead", "SlotId", "SlotPage",
           "SlotStatus", "StateEncoder", "StateLine", "THUMB_LINE_RE", "THUMB_SIZE",
           "TooLarge", "all_slots", "classify_head", "count_structure", "describe",
           "encode_save", "iter_pieces", "meta_of", "newest", "next_seq", "page_slots",
           "parse_full", "parse_state_line", "read_slot_full", "read_slot_head",
           "rotation_target", "save_problem", "slot_order", "split_lines", "strict_loads",
           "thumb_line"]

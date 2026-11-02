"""Node-state files: the flowchart's jump points on disk (F20 ``04-technical.md`` §4, §5, §7.5
"One helper", "Launch", "Reading"; ``05-security.md`` SEC-F20-01, -05(c), -07, -08).

Why this module exists: each flowchart node the player reached keeps the story state at that
point in its own file in F11's saves root, so a Jump can load it later. Those files sit beside
the player's saves and are untrusted (shared, edited, planted), so every F20 file call goes
through one name-checking helper and every byte is read with F11's own parser. Pure: no
pygame, threads, ``shutil``, or clock; file I/O goes through ``core.safefile`` on the calling
thread, and writing is the ``App.writer`` ``flow`` client's job (``app/flowchart.py``).

**The file** (``node-<16 hex>.vnnode``; ``<16 hex>`` is ``node_key(id)``), three compact ASCII
JSON lines like F11's ``.vnsave``, each ending in ``\\n``::

    {"vnnode":1,"game":"paper-lanterns","node":"scene:stall","state_format":1,"thumb":14,"state":9071}
    {"jpeg":null}
    {"format":1,"identity_scheme":1,"position":{…},…,"flow":{"path":[…]}}

``thumb`` and ``state`` are the byte lengths of lines 2 and 3 with their ``\\n``. Line 2 is
reserved for a picture (PR-F20-30, not built): it must be exactly ``{"jpeg":null}``, matched by
F11's line-2 pattern and never decoded.

- ``NodeFolder`` is the one helper (SEC-F20-01(b)): it refuses, without a file call, any
  folder but its root and any name not fullmatching ``NODE_NAME_RE`` (or, for removal,
  ``NODE_TEMP_RE``). Names come only from ``node_file(id)`` or a listed name.
- ``NodeEncoder`` is F11's sliced encoder (``saves.StateEncoder``) with the node meta line,
  so every file it writes passes ``parse_node`` (TR-F20-04).
- ``parse_node`` reads with F11's own ``split_lines``, ``strict_loads``,
  ``parse_state_line``, and ``PARSE_ERRORS`` (shared objects, not copies; SEC-F20-07):
  ``vnnode`` first (a later one is NEWER whatever else the file holds), exactly the six meta
  keys, ``state_format``, ``game`` (SEC-F11-11), the line lengths, line 2, line 3, and then
  the state must belong to its node (SEC-F20-08): ``node`` is the requested id and the node's
  key is among the last ``FLOW_STATE_PATH_CHECK`` entries of ``state.flow.path``.
- ``read_node`` checks the root, reads one file with ``read_regular`` (no-follow, regular,
  ``fstat`` equal, ≤ ``SAVE_FILE_MAX``), and parses it. It runs only at a jump (TR-F20-09).
- ``FlowListJob`` is the launch listing: one ``safefile.list_regular`` of the root
  (≤ ``FLOW_SCAN_MAX`` entries, ≤ ``FLOW_LIST_STEP`` per step), regular entries only; node
  temps over ``TEMP_STALE_S`` old are listed for removal (SEC-F20-05(c)). F20 never calls
  ``remove_stale_temps``.

``NodeRead.reason`` is a dev reason word (W155), never file text.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from engine.core import safefile
from engine.core.paths import is_valid_app_id
from engine.core.safefile import ReadKind, ReadResult, RegularFile, RemoveKind
from engine.persist import limits
from engine.persist.saves import (PARSE_ERRORS, REASON_GONE, REASON_LENGTHS, REASON_META,
                                  REASON_OTHER_GAME, REASON_TOO_BIG, REASON_UNREADABLE,
                                  THUMB_LINE_RE, StateEncoder, TooLarge, parse_state_line,
                                  split_lines, strict_loads)
from engine.persist.saves import SlotStatus as _Line
from engine.persist.writer import FileWrite
from engine.runtime import limits as runtime_limits
from engine.runtime.state import STATE_FORMAT, GameState
from engine.runtime.flowchart import node_key       # the graph types via runtime (07 I-1)

NODE_NAME_RE = re.compile(r"node-[0-9a-f]{16}\.vnnode", re.ASCII)
NODE_TEMP_RE = safefile.temp_name_pattern(target_pattern=NODE_NAME_RE)
_LISTED_RE = re.compile(rf"(?:{NODE_NAME_RE.pattern})|(?:{NODE_TEMP_RE.pattern})", re.ASCII)

# Exactly the meta keys, in the order the encoder writes them (``vnnode`` first, 04 §4).
META_KEYS = ("vnnode", "game", "node", "state_format", "thumb", "state")
_META_KEY_SET = frozenset(META_KEYS)
_NEWER_PREFIX = re.compile(rb'\{"vnnode":([0-9]{1,16})[,}]')
_LIST_UNIT = 64                                         # entries per listing batch

# Reason words (W155 ``couldn't jump to <node>: <reason>``). Never file text.
REASON_ROOT = "the saves folder isn't usable"
REASON_THUMB = "picture line"
REASON_OTHER_NODE = "other node"


class NodeStatus(Enum):
    OK = "ok"
    MISSING = "missing"              # no regular file at the node's name (never read)
    UNREADABLE = "unreadable"        # an OSError on the file, or the root failed its check
    DAMAGED = "damaged"
    NEWER = "newer"
    OTHER_GAME = "other_game"


@dataclass(frozen=True, slots=True)
class NodeRead:
    """A jump's read: ``state`` only when OK; ``reason`` is "" when OK."""

    status: NodeStatus
    state: GameState | None
    reason: str


@dataclass(frozen=True, slots=True)
class NodeMeta:
    """Line 1, validated (04 §4)."""

    game: str | None
    node: str
    state_format: int
    thumb_len: int
    state_len: int


@dataclass(frozen=True, slots=True)
class FileInfo:
    """A listed node file: its size and its eviction order (``mtime_ns``)."""

    size: int
    order: int


def _format_reason(kind: str, n: int) -> str:
    shown = str(n) if n < 10**16 else "?"
    return f"made with {kind} format {shown}"


# --- Names ---------------------------------------------------------------------------------

def node_file(node_id: str) -> str:
    """``node-`` + ``node_key(node_id)`` + ``.vnnode``: the only way F20 makes a file name."""
    if type(node_id) is not str:
        raise TypeError("a node id must be a str")
    return f"node-{node_key(node_id)}.vnnode"


def is_node_name(name: object) -> bool:
    return type(name) is str and NODE_NAME_RE.fullmatch(name) is not None


def is_node_temp(name: object) -> bool:
    return type(name) is str and NODE_TEMP_RE.fullmatch(name) is not None


# --- The one helper (SEC-F20-01(b)) --------------------------------------------------------

class NodeFolder:
    """Every F20 file call goes through this: a folder other than ``root`` or a name that
    doesn't fullmatch ``NODE_NAME_RE`` (``NODE_TEMP_RE`` too, for ``accepts`` and
    ``remove``) is refused with ``ValueError`` before any file call. ``release`` is the
    run's mode, for ``check_root`` and the writer's job."""

    def __init__(self, root: Path, *, release: bool) -> None:
        if not isinstance(root, Path):
            raise TypeError("the root must be a Path")
        self.root = root
        self.release = release

    def __repr__(self) -> str:
        return "NodeFolder(<saves root>)"             # no path in logs (privacy)

    def check_root(self) -> bool:
        """The root is a real folder (``ensure_real_dir(create=False)``; dev: its own real
        path, F11's W81 rule). Run at launch and before each listing, jump read, and removal
        batch (SEC-F20-01(a))."""
        return safefile.ensure_real_dir(self.root, release=self.release, create=False)

    def accepts(self, folder: object, name: object) -> bool:
        """``folder`` is the root and ``name`` a node file or node temp name."""
        return (isinstance(folder, Path) and folder == self.root
                and (is_node_name(name) or is_node_temp(name)))

    def _require(self, name: object, *, temps: bool) -> Path:
        if not (is_node_name(name) or (temps and is_node_temp(name))):
            raise ValueError("not a node file name")
        return self.root / name                       # type: ignore[operator]

    def read(self, name: str) -> ReadResult:
        """``read_regular(root / name, SAVE_FILE_MAX)``: ``lstat`` regular, no-follow open,
        ``fstat`` the same file. A node temp is never read."""
        return safefile.read_regular(self._require(name, temps=False), limits.SAVE_FILE_MAX)

    def remove(self, name: str) -> RemoveKind:
        """``remove_file``: the entry itself, never a link's target or a real folder."""
        return safefile.remove_file(self._require(name, temps=True))

    def job(self, name: str, pieces: Iterable[bytes], *, token: int = 0) -> FileWrite:
        """The writer job for one node file (client ``flow``, ``root`` = the saves root)."""
        self._require(name, temps=False)
        return FileWrite(self.root, name, tuple(pieces), release=self.release, token=token)

    def listing(self) -> safefile.RegularListing:
        """The one bounded listing of the root: regular node files and node temps."""
        return safefile.list_regular(self.root, _LISTED_RE, max_examined=limits.FLOW_SCAN_MAX)


# --- Writing -------------------------------------------------------------------------------

class NodeEncoder(StateEncoder):
    """One node file's pieces in slices (F11's ``StateEncoder``: ``step(deadline, clock)``,
    ``run()``, ``result``: the pieces or ``TooLarge``). Line 1 is the node meta, line 2
    ``{"jpeg":null}``, line 3 ``state.to_json()`` under F11's caps. ``game`` that isn't a
    valid app id is written as null. A ``node_id`` that isn't a str of 1 to ``NODE_ID_MAX``
    code points is a programmer error (``ValueError``)."""

    def __init__(self, state: GameState, *, node_id: str, game: str | None) -> None:
        if type(node_id) is not str or not 1 <= len(node_id) <= limits.NODE_ID_MAX:
            raise ValueError("a node id is a str of 1 to NODE_ID_MAX code points")
        super().__init__(state, jpeg=None)
        self.node_id = node_id
        self.game = game if is_valid_app_id(game) else None

    def meta_fields(self, thumb: int, state: int) -> dict[str, object]:
        return {"vnnode": limits.NODE_FORMAT, "game": self.game, "node": self.node_id,
                "state_format": STATE_FORMAT, "thumb": thumb, "state": state}


# --- Reading (SEC-F20-07, -08) -------------------------------------------------------------

def _int_in(value: object, low: int, high: int | None = None) -> bool:
    return type(value) is int and low <= value and (high is None or value <= high)


def node_meta_of(obj: object) -> NodeMeta | None:
    """Line 1 as ``NodeMeta`` if it has exactly the six keys with their types and ranges."""
    if type(obj) is not dict or obj.keys() != _META_KEY_SET:
        return None
    game, node = obj["game"], obj["node"]
    if not (type(obj["vnnode"]) is int and obj["vnnode"] == limits.NODE_FORMAT
            and (game is None or is_valid_app_id(game))
            and type(node) is str and 1 <= len(node) <= limits.NODE_ID_MAX
            and _int_in(obj["state_format"], 1)
            and _int_in(obj["thumb"], 1, limits.THUMB_LINE_MAX)
            and _int_in(obj["state"], 1, limits.STATE_MAX_BYTES)):
        return None
    return NodeMeta(game=game, node=node, state_format=obj["state_format"],
                    thumb_len=obj["thumb"], state_len=obj["state"])


def _damaged(reason: str) -> NodeRead:
    return NodeRead(NodeStatus.DAMAGED, None, reason)


def _belongs(state: GameState, node_id: str) -> bool:
    """SEC-F20-08: the node's key is among the last ``FLOW_STATE_PATH_CHECK`` path entries."""
    flow = getattr(state, "flow", None)
    path = getattr(flow, "path", ())
    check = runtime_limits.FLOW_STATE_PATH_CHECK
    return check > 0 and node_key(node_id) in path[-check:]


def parse_node(data: bytes, *, node_id: str, game_id: str | None) -> NodeRead:
    """A jump's verdict on a whole node file (pure; 04 §7.5 "Reading"). ``node_id`` is the
    node the player chose; ``game_id`` the running game's ``[game] id``."""
    size = len(data)
    if size > limits.SAVE_FILE_MAX:
        return _damaged(REASON_TOO_BIG)
    prefix = _NEWER_PREFIX.match(data)
    if prefix is not None and int(prefix[1]) > limits.NODE_FORMAT:
        return NodeRead(NodeStatus.NEWER, None, _format_reason("node", int(prefix[1])))
    try:
        first = split_lines(data, size)
        if type(first) is str:
            return _damaged(first)
        obj = strict_loads(first.meta)
        version = obj.get("vnnode") if type(obj) is dict else None
        if type(version) is int and version > limits.NODE_FORMAT:
            return NodeRead(NodeStatus.NEWER, None, _format_reason("node", version))
        meta = node_meta_of(obj)
    except PARSE_ERRORS:
        return _damaged(REASON_META)
    if meta is None:
        return _damaged(REASON_META)
    if meta.state_format > STATE_FORMAT:
        return NodeRead(NodeStatus.NEWER, None, _format_reason("state", meta.state_format))
    if meta.game is not None and game_id is not None and meta.game != game_id:
        return NodeRead(NodeStatus.OTHER_GAME, None, REASON_OTHER_GAME)
    lines = split_lines(data, size, (meta.thumb_len, meta.state_len))
    if type(lines) is str:
        return _damaged(lines)
    assert lines.thumb is not None and lines.state is not None
    start, end = lines.thumb
    thumb = THUMB_LINE_RE.fullmatch(data, start, end)
    if thumb is None or thumb[1] is not None:          # a picture: not built (PR-F20-30)
        return _damaged(REASON_THUMB)
    line = parse_state_line(data, lines.state)
    if line.status is _Line.NEWER:
        return NodeRead(NodeStatus.NEWER, None, line.reason)
    if line.status is not _Line.OK:
        return _damaged(line.reason)
    assert line.state is not None
    if meta.node != node_id or not _belongs(line.state, node_id):
        return _damaged(REASON_OTHER_NODE)
    return NodeRead(NodeStatus.OK, line.state, "")


def read_node(folder: NodeFolder, node_id: str, *, game_id: str | None) -> NodeRead:
    """A jump's read of one node's file: the root check, ``NodeFolder.read`` of
    ``node_file(node_id)``, then ``parse_node``. A missing or non-regular entry is MISSING
    (never opened); over ``SAVE_FILE_MAX`` is DAMAGED with nothing read. One step of F11's
    load-read class (ADR-0005)."""
    name = node_file(node_id)
    if not folder.check_root():
        return NodeRead(NodeStatus.UNREADABLE, None, REASON_ROOT)
    result = folder.read(name)
    if result.kind in (ReadKind.MISSING, ReadKind.NOT_REGULAR):
        return NodeRead(NodeStatus.MISSING, None, REASON_GONE)
    if result.kind is ReadKind.TOO_LARGE:
        return _damaged(REASON_TOO_BIG)
    if not result.ok:
        return NodeRead(NodeStatus.UNREADABLE, None, REASON_UNREADABLE)
    assert result.data is not None and result.stamp is not None
    data, size = result.data, result.stamp.size
    del result
    if len(data) != size:                               # grew or shrank while it was read
        return _damaged(REASON_LENGTHS)
    return parse_node(data, node_id=node_id, game_id=game_id)


# --- The launch listing (04 §7.5 "Launch") -------------------------------------------------

class FlowListJob:
    """One bounded listing of the saves root in slices (``step(deadline, clock)``; True when
    done). The first step checks the root (``root_ok``; False: nothing is listed, and the
    service runs in memory mode). Each step looks at no more than ``FLOW_LIST_STEP`` entries
    and stops at ``deadline``; the whole listing at no more than ``FLOW_SCAN_MAX``.

    ``files``: every regular entry fullmatching ``NODE_NAME_RE`` → ``FileInfo(size,
    mtime_ns)``; the service splits them into current files and orphans by ``node_file``.
    ``stale_temps``: regular node temps over ``TEMP_STALE_S`` old at ``now`` (wall-clock
    seconds), to be removed under the per-frame bound. A non-regular entry is never listed.
    ``max_order`` is the highest listed ``mtime_ns`` (own writes order above it).
    ``close()`` ends an abandoned listing."""

    def __init__(self, folder: NodeFolder, *, now: float) -> None:
        self.folder = folder
        self.now = now
        self.files: dict[str, FileInfo] = {}
        self.stale_temps: list[str] = []
        self.root_ok: bool | None = None
        self.done = False
        self.steps = 0
        self.examined = 0
        self.most_in_a_step = 0                         # CI guard: ≤ FLOW_LIST_STEP
        self.capped = False
        self.max_order = 0
        self._listing: safefile.RegularListing | None = None

    def step(self, deadline: float, clock: Callable[[], float]) -> bool:
        if self.done:
            return True
        self.steps += 1
        if self._listing is None:
            self.root_ok = self.folder.check_root()
            if not self.root_ok:
                self.done = True
                return True
            self._listing = self.folder.listing()
        listing = self._listing
        start = listing.examined
        budget = max(1, limits.FLOW_LIST_STEP)
        while not listing.done:
            left = budget - (listing.examined - start)
            if left <= 0:
                break
            for found in listing.batch(min(_LIST_UNIT, left)):
                self._take(found)
            if clock() > deadline:
                break
        self.examined = listing.examined
        self.most_in_a_step = max(self.most_in_a_step, listing.examined - start)
        if listing.done:
            self.capped = listing.capped
            self.close()
            self.done = True
        return self.done

    def finish(self) -> None:
        """Every remaining step at once (tests; never in a frame)."""
        while not self.step(float("inf"), lambda: 0.0):
            pass

    def close(self) -> None:
        listing, self._listing = self._listing, None
        if listing is not None:
            listing.close()
        self.done = True                                # an abandoned listing never restarts

    def _take(self, found: RegularFile) -> None:
        name = found.name
        if NODE_NAME_RE.fullmatch(name):
            self.files[name] = FileInfo(found.size, found.mtime_ns)
            self.max_order = max(self.max_order, found.mtime_ns)
        elif NODE_TEMP_RE.fullmatch(name):
            if self.now - found.mtime_ns / 1e9 > limits.TEMP_STALE_S:
                self.stale_temps.append(name)


__all__ = ["FileInfo", "FlowListJob", "META_KEYS", "NODE_NAME_RE", "NODE_TEMP_RE",
           "NodeEncoder", "NodeFolder", "NodeMeta", "NodeRead", "NodeStatus", "REASON_OTHER_NODE",
           "REASON_ROOT", "REASON_THUMB", "TooLarge", "is_node_name", "is_node_temp",
           "node_file", "node_meta_of", "parse_node", "read_node"]

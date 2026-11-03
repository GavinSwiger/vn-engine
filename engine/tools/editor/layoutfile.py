"""Studio's story-map layout file, ``<game>/.studio/storymap.json`` (F46 ``04-technical.md``
§3.6, §6.10, §7; ADR-0008 Amendment 2; ``07`` §2.1, I-9).

Why this module exists: box places are Studio's own data, not the story's, so they live in a
small file beside the scripts that the game, the loader and the check child never read. Pure
Python, no Tk; the window owns the timer (``LAYOUT_SAVE_MS``) and the status line.

- ``read_layout`` returns the stored places, ``{}`` when there is no file (or no folder), or a
  ``LayoutProblem``. ``.studio`` and the file must ``lstat`` as a real folder and a regular
  file (no link, junction or reparse point, real path equal to the listed one); the bytes
  come from ``safefile.read_regular`` (≤ ``LAYOUT_MAX_BYTES``) and must be strict UTF-8 JSON
  with no ``NaN``/``Infinity``, ``studio_map == 1``, and ``boxes`` an object of at most
  ``LAYOUT_MAX_BOXES`` ``words.is_name`` keys, each ``[int, int]`` in ``0..LAYOUT_MAX_COORD``
  (``bool`` refused). Unknown top-level keys are ignored. Never raises.
- ``encode_layout`` is pure and deterministic: 04 §3.6's text, one box per line, keys by code
  point, UTF-8, LF and a final break. ``places`` is iterated in program order (the caller
  passes only existing labels); over the caps, ``keep_first`` (the shown boxes) go first,
  then the rest in ``places`` order, until the next box wouldn't fit.
- ``write_layout`` writes those bytes: ``safefile.ensure_real_dir`` on ``.studio`` (dev rule:
  one ``mkdir``, no links), the target missing or regular by ``lstat``, unchanged bytes
  skipped, then ``safefile.write_atomic`` with the stamp re-checked. A new file gets
  ``0o666 & ~umask`` and a replaced one keeps its mode (``07`` I-9). Never raises; nothing
  is deleted, renamed or made in the folder but the file and its temp (Amendment 2 (b)).

A ``LayoutProblem`` with ``link`` set means a link, junction or non-folder was found: the
caller stops writing for that window (04 §6.10 read step 4). Messages name no path.

Imports only ``engine.core``, ``engine.script`` and the standard library (ADR-0008).
"""

import json
import os
import stat
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from engine.core import safefile
from engine.script.words import is_name

LAYOUT_DIR: Final = ".studio"
LAYOUT_NAME: Final = "storymap.json"
LAYOUT_SAVE_MS: Final = 1_000           # written this long after the last place change
LAYOUT_MAX_BYTES: Final = 256 * 1024
LAYOUT_MAX_BOXES: Final = 10_000
LAYOUT_MAX_COORD: Final = 1_000_000
LAYOUT_VERSION: Final = 1

READ_TEXT: Final = ("The map layout file couldn't be read, so boxes were placed "
                    "automatically.")
WRITE_TEXT: Final = "The map layout file couldn't be saved."   # not in design §17.3 yet

_HEAD: Final = f'{{\n  "studio_map": {LAYOUT_VERSION},\n  "boxes": {{'.encode()
_EMPTY: Final = _HEAD + b"}\n}\n"
_TAIL: Final = b"\n  }\n}\n"


@dataclass(frozen=True, slots=True)
class LayoutProblem:
    """Why the layout file couldn't be read or written. ``text`` is the one status line;
    ``reason`` is a short word for tests and logs; ``link`` means writing must stop."""

    reason: str
    text: str = READ_TEXT
    link: bool = False


def _umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


# 07 I-9 (F45 I-7): a new file gets the mode a plain ``open`` would give it. Read once, at
# import, on the main thread (``os.umask`` is process-wide).
NEW_FILE_MODE: Final = 0o666 & ~_umask() if os.name == "posix" else None


def layout_path(root: Path) -> Path:
    return Path(root) / LAYOUT_DIR / LAYOUT_NAME


# --- Reading ---------------------------------------------------------------------------------

def _is_listed_path(path: Path) -> bool:
    """The real path is the listed one: no link anywhere above leads elsewhere."""
    return (os.path.normcase(os.path.realpath(path))
            == os.path.normcase(os.path.abspath(path)))


def _reject_constant(name: str) -> object:
    raise ValueError(name)


def read_layout(root: Path) -> dict[str, tuple[int, int]] | LayoutProblem:
    """The stored places, ``{}`` if the folder or the file is missing, else a
    ``LayoutProblem``. Never raises."""
    try:
        return _read(Path(root))
    except Exception:                    # a bug or an odd OS error: still the automatic layout
        return LayoutProblem("unreadable")


def _read(root: Path) -> dict[str, tuple[int, int]] | LayoutProblem:
    folder = root / LAYOUT_DIR
    if not os.path.lexists(folder):
        return {}
    # A real folder by lstat (no link, junction or reparse point) whose real path is itself.
    if not safefile.ensure_real_dir(folder, create=False):
        return LayoutProblem("folder not real", link=True)
    target = folder / LAYOUT_NAME
    kind = safefile.entry_kind(target)
    if kind is safefile.EntryKind.MISSING:
        return {}
    if kind is not safefile.EntryKind.REGULAR or not _is_listed_path(target):
        return LayoutProblem("file not regular", link=True)
    result = safefile.read_regular(target, LAYOUT_MAX_BYTES)
    if result.kind is safefile.ReadKind.MISSING:
        return {}
    if result.kind is safefile.ReadKind.NOT_REGULAR:
        return LayoutProblem("file not regular", link=True)
    if result.kind is safefile.ReadKind.TOO_LARGE:
        return LayoutProblem("too large")
    if not result.ok or result.data is None:
        return LayoutProblem("unreadable")
    return decode_layout(result.data)


def decode_layout(data: bytes) -> dict[str, tuple[int, int]] | LayoutProblem:
    """Validate the file's bytes field by field (04 §6.10 read steps 2–3)."""
    if len(data) > LAYOUT_MAX_BYTES:
        return LayoutProblem("too large")
    try:
        text = data.decode("utf-8", errors="strict")
        doc = json.loads(text, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return LayoutProblem("damaged")
    if not isinstance(doc, dict):
        return LayoutProblem("damaged")
    version = doc.get("studio_map")
    if type(version) is not int or version != LAYOUT_VERSION:
        return LayoutProblem("unknown version")
    boxes = doc.get("boxes")
    if not isinstance(boxes, dict):
        return LayoutProblem("damaged")
    if len(boxes) > LAYOUT_MAX_BOXES:
        return LayoutProblem("too many boxes")
    places: dict[str, tuple[int, int]] = {}
    for name, value in boxes.items():
        if not is_name(name):
            return LayoutProblem("damaged")
        if not isinstance(value, list) or len(value) != 2:
            return LayoutProblem("damaged")
        x, y = value
        if not (_coord(x) and _coord(y)):
            return LayoutProblem("damaged")
        places[name] = (x, y)
    return places


def _coord(value: object) -> bool:
    return type(value) is int and 0 <= value <= LAYOUT_MAX_COORD


# --- Encoding --------------------------------------------------------------------------------

def _clamp(value: int) -> int:
    return min(max(int(value), 0), LAYOUT_MAX_COORD)


def _line(name: str, place: tuple[int, int]) -> bytes:
    x, y = place
    return f'    "{name}": [{_clamp(x)}, {_clamp(y)}]'.encode()


def encode_layout(places: Mapping[str, tuple[int, int]],
                  keep_first: Sequence[str] = ()) -> bytes:
    """04 §3.6's bytes for ``places``. Names that aren't ``is_name`` are skipped and
    coordinates are clamped to ``0..LAYOUT_MAX_COORD``. Over ``LAYOUT_MAX_BOXES`` boxes or
    ``LAYOUT_MAX_BYTES`` bytes, ``keep_first`` names go first, then ``places`` order, until
    the next box doesn't fit. Pure and deterministic."""
    chosen: dict[str, bytes] = {}
    size = len(_HEAD) + len(_TAIL) - 1        # the last line has no comma
    for name in _order(places, keep_first):
        if len(chosen) >= LAYOUT_MAX_BOXES:
            break
        line = _line(name, places[name])
        if size + len(line) + 2 > LAYOUT_MAX_BYTES:   # "\n" before it and "," after it
            break
        chosen[name] = line
        size += len(line) + 2
    if not chosen:
        return _EMPTY
    body = b",\n".join(chosen[name] for name in sorted(chosen))
    return _HEAD + b"\n" + body + _TAIL


def _order(places: Mapping[str, tuple[int, int]], keep_first: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    order: list[str] = []
    for name in (*keep_first, *places):
        if name in seen or name not in places or not isinstance(name, str) or not is_name(name):
            continue
        seen.add(name)
        order.append(name)
    return order


# --- Writing ---------------------------------------------------------------------------------

def write_layout(root: Path, data: bytes) -> LayoutProblem | None:
    """Write ``data`` (from ``encode_layout``) to the layout file; None on success or when
    the file already holds these bytes. Never raises (04 §6.10 write steps 2–4)."""
    try:
        return _write(Path(root), bytes(data))
    except Exception:
        return LayoutProblem("write failed", WRITE_TEXT)


def _write(root: Path, data: bytes) -> LayoutProblem | None:
    if len(data) > LAYOUT_MAX_BYTES:
        return LayoutProblem("too large", WRITE_TEXT)
    folder = root / LAYOUT_DIR
    if not safefile.ensure_real_dir(folder):
        link = os.path.lexists(folder)        # a link, junction or file is in the way
        return LayoutProblem("folder not real" if link else "write failed", WRITE_TEXT,
                             link=link)
    target = folder / LAYOUT_NAME
    try:
        st = os.lstat(target)
    except FileNotFoundError:
        st = None
    if st is not None:
        if not safefile.is_regular(st) or not _is_listed_path(target):
            return LayoutProblem("file not regular", WRITE_TEXT, link=True)
        old = safefile.read_regular(target, LAYOUT_MAX_BYTES)
        if old.ok and old.data == data:
            return None
        mode: int | None = stat.S_IMODE(st.st_mode) if os.name == "posix" else None
        expected: safefile.Stamp | None = safefile.Stamp.of(st)
    else:
        mode, expected = NEW_FILE_MODE, None
    try:
        safefile.write_atomic(target, (data,), check=True, expected=expected, mode=mode,
                              replace_tries=1)
    except safefile.TargetChanged:
        return LayoutProblem("changed", WRITE_TEXT)
    except OSError:
        return LayoutProblem("write failed", WRITE_TEXT)
    return None

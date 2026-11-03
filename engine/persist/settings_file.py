"""The ``settings.json`` file: where it lives, the launch read, the parser, and the encoder
(F16 ``04-technical.md`` §4, §5.1, §7.1, §8; design §7; ``07`` G3, G4, G10, I-7, I-9, I-10).

Why this module exists: the settings file is untrusted (players edit and share it), so
reading it must never raise, stall, or echo its text, and a damaged file must cost only the
player's settings, never the game (PR-F16-22, 23). Writing must produce a file this same
reader accepts (TR-F16-01). The App's settings service (``app/settings.py``) logs W70–W75
from the ``LoadedSettings`` returned here; this module never logs.

The file (``format`` is ``FORMAT``, 4 since F43) is ASCII JSON, keys sorted at both levels,
``indent=2``::

    {
      "format": 4,
      "values": {
        "language": "ja",
        "music_volume": 40,
        "window_size": [1280, 720]
      }
    }

Only the keys the player changed are stored; each must pass ``settings_schema.check``.
Values are ints, booleans, the ``window_size`` pair, and (format 4, F43) ``language``, the
one text value: an ASCII language code such as ``"pt-BR"``, so the file stays ASCII. A
file of an older format (1–3) reads as current, with the keys it lacks absent (``language``
absent = not chosen yet); the next write gives it ``FORMAT``.

Parsing: at most ``MAX_FILE_BYTES``; strict UTF-8 (a BOM is not JSON); ``json.loads`` with
hooks refusing duplicate keys and NaN/Infinity, and turning integers of more than
``MAX_INT_DIGITS`` digits into a ``LongNumber`` marker (never converted); more than
``MAX_DEPTH`` nesting levels is refused too. Any of these → BAD "not valid JSON". Then
``format`` (an exact int) decides: above ``FORMAT`` → NEWER (known keys that pass are used;
never written this session); ``1 ≤ format ≤ FORMAT`` reads as current (I-7) and needs
exactly ``format`` and an object ``values``; anything else → BAD "not settings data".

The launch read (``read_settings``) never creates the folder, never reads through a linked
dev folder (G10), removes stale temp files, reads with ``safefile.read_regular``, and moves
a BAD file's entry to ``settings.bad.json`` with ``safefile.quarantine``. An unreadable file
is left in place and the file isn't written that session.
"""

import enum
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import accumulate, repeat
from operator import sub
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from engine.core import safefile
from engine.core.safefile import ReadKind
from engine.core.settings_schema import (
    FORMAT,
    KEYS,
    MAX_FILE_BYTES,
    MAX_INT_DIGITS,
    LongNumber,
    Problem,
    Value,
    check,
)
from engine.persist import location

LOG_AREA: Final = "setting"             # 07 G2: ``^[a-z]{1,7}$``
FOLDER_NAME: Final = "settings"
FILE_NAME: Final = "settings.json"
BAD_NAME: Final = "settings.bad.json"
TEMP_RE: Final = re.compile(r"\.settings\.json\.[0-9a-f]{8}\.tmp", re.ASCII)
MAX_DEPTH: Final = 1000                 # nesting levels; 1,001 is "not valid JSON"

# W70 reasons (design §5).
NOT_VALID_JSON: Final = "not valid JSON"
NOT_SETTINGS: Final = "not settings data"
OVER_CAP: Final = "over 64 KB"
NOT_REGULAR: Final = "not a regular file"
UNREADABLE: Final = "couldn't be read"
# W75 reasons for a session without a usable folder (04 §7.1 steps 2-3).
NO_PERMISSION: Final = "no permission"
FOLDER_IS_LINK: Final = "the folder is a link"


class Outcome(enum.Enum):
    OK = "ok"                    # read and used (problems and unknown keys aside)
    MISSING = "missing"          # no folder or no file: defaults, no warning
    BAD = "bad"                  # W70: defaults; quarantined if the rename worked
    NEWER = "newer"              # W73: known keys used; never written this session
    UNREADABLE = "unreadable"    # W70 "couldn't be read": left in place, never written
    NO_FILE = "no file"          # W74 / W75: session only, nothing read or written


@dataclass(frozen=True, slots=True)
class LoadedSettings:
    """The launch read's result.

    ``values`` holds only keys that passed ``check`` (``window_size`` as a tuple).
    ``bad_reason`` is W70's reason for BAD and UNREADABLE, and W75's reason for a NO_FILE
    session caused by the folder (None for W74 or a skipped read). ``problems`` are W71's,
    at most one per key, in ``KEYS`` order; ``unknown`` is W72's count. ``writable`` is
    False for NEWER, UNREADABLE, and NO_FILE. ``quarantined`` is True when a BAD file was
    moved to ``settings.bad.json`` (W70's ending, 07 G3)."""

    values: Mapping[str, Value]
    outcome: Outcome
    bad_reason: str | None = None
    problems: tuple[Problem, ...] = ()
    unknown: int = 0
    folder: Path | None = None
    writable: bool = True
    quarantined: bool = False

    @classmethod
    def no_file(cls, reason: str | None = None, *, folder: Path | None = None
                ) -> "LoadedSettings":
        """A session-only result: defaults, nothing read, never written."""
        return cls(_EMPTY, Outcome.NO_FILE, reason, folder=folder, writable=False)


_EMPTY: Mapping[str, Value] = MappingProxyType({})


# --- Where the file lives ---------------------------------------------------------------------

def settings_root(*, game_root: Path, release: bool, app_id: str | None) -> Path | None:
    """``<game>/settings`` in a dev run, ``user_data_dir(app_id)/settings`` in a release
    run; None without a usable id or base. Not created here."""
    return location.user_root(FOLDER_NAME, game_root=game_root, release=release,
                              app_id=app_id)


def display_file(folder: Path, *, game_root: Path | None) -> str:
    """``<file>`` in W70–W75: the environment-style path of ``settings.json``."""
    return location.display_file(folder, game_root=game_root, name=FILE_NAME)


def is_engine_name(name: str) -> bool:
    """True for the only names the engine creates in the settings folder."""
    return name in (FILE_NAME, BAD_NAME) or TEMP_RE.fullmatch(name) is not None


# --- Parsing ----------------------------------------------------------------------------------

_LONG = LongNumber()
_STRING_RE = re.compile(rb'"(?:[^"\\]|\\.)*"', re.DOTALL)
_NOT_BRACKETS = bytes(b for b in range(256) if b not in b"[]{}")
_BRACKET_STEP = bytes.maketrans(b"[{]}", b"\x02\x02\x00\x00")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out = dict(pairs)
    if len(out) != len(pairs):
        raise ValueError("duplicate key")
    return out


def _refuse_constant(name: str) -> None:
    raise ValueError("NaN and Infinity aren't allowed")


def _bounded_int(text: str) -> int | LongNumber:
    """A marker for more than ``MAX_INT_DIGITS`` digits, so a huge integer is never
    converted (Python's 4,300-digit limit is never reached)."""
    if len(text) - (text[:1] == "-") > MAX_INT_DIGITS:
        return _LONG
    return int(text)


def _too_deep(data: bytes) -> bool:
    """More than ``MAX_DEPTH`` nesting levels. Only called on text that parsed, so every
    string is closed and the string pattern scans once, left to right. C speed: strings
    are dropped, brackets kept and mapped to +1/-1, and the running sum's maximum taken."""
    if data.count(b"[") + data.count(b"{") <= MAX_DEPTH:
        return False
    steps = _STRING_RE.sub(b"", data).translate(None, _NOT_BRACKETS).translate(_BRACKET_STEP)
    return max(accumulate(map(sub, steps, repeat(1))), default=0) > MAX_DEPTH


def _bad(reason: str) -> LoadedSettings:
    return LoadedSettings(_EMPTY, Outcome.BAD, reason)


def _sort_values(raw: Mapping[str, Any]) -> tuple[Mapping[str, Value], tuple[Problem, ...], int]:
    kept: dict[str, Value] = {}
    problems: dict[str, Problem] = {}
    unknown = 0
    for key, value in raw.items():
        if key not in KEYS:
            unknown += 1
            continue
        problem = check(key, value)
        if problem is not None:
            problems[key] = problem
        else:
            kept[key] = tuple(value) if type(value) is list else value
    ordered = {key: kept[key] for key in KEYS if key in kept}
    return (MappingProxyType(ordered),
            tuple(problems[key] for key in KEYS if key in problems), unknown)


def parse_settings(data: bytes) -> LoadedSettings:
    """Classify and check ``data`` (04 §7.1 step 6). Pure; never raises for any bytes.
    ``folder`` is None; ``writable`` is False only for NEWER."""
    if len(data) > MAX_FILE_BYTES:
        return _bad(OVER_CAP)
    try:
        top = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates,
                         parse_constant=_refuse_constant, parse_int=_bounded_int)
    except (ValueError, RecursionError, OverflowError):
        return _bad(NOT_VALID_JSON)
    if _too_deep(data):
        return _bad(NOT_VALID_JSON)
    if type(top) is not dict or type(top.get("format")) is not int:
        return _bad(NOT_SETTINGS)
    version = top["format"]
    if version > FORMAT:
        raw = top.get("values")
        values, problems, unknown = _sort_values(raw if type(raw) is dict else {})
        return LoadedSettings(values, Outcome.NEWER, None, problems, unknown, writable=False)
    if version < 1 or top.keys() != {"format", "values"} or type(top["values"]) is not dict:
        return _bad(NOT_SETTINGS)
    values, problems, unknown = _sort_values(top["values"])
    return LoadedSettings(values, Outcome.OK, None, problems, unknown)


# --- The launch read --------------------------------------------------------------------------

def read_settings(folder: Path, *, release: bool = False) -> LoadedSettings:
    """The launch read (04 §7.1 steps 3–7). Never raises; never creates the folder.

    No folder → MISSING (writable: the writer creates it at the first write). A folder that
    isn't a real directory (a link or junction; in a dev run also one reached through a
    link) → NO_FILE "the folder is a link": nothing is read (G10). Then stale temp files
    are removed and ``settings.json`` read: missing → MISSING; an ``OSError`` → UNREADABLE
    (left in place, not writable); a link, directory, FIFO, or other entry → BAD "not a
    regular file"; over 64 KiB → BAD "over 64 KB"; else ``parse_settings``. A BAD file's
    entry is moved to ``settings.bad.json``; if that fails it stays, still writable, and
    the next write replaces it."""
    folder = Path(folder)
    try:
        present = safefile.current_stamp(folder) is not None
    except (OSError, ValueError):
        return LoadedSettings(_EMPTY, Outcome.UNREADABLE, UNREADABLE, folder=folder,
                              writable=False)
    if not present:
        return LoadedSettings(_EMPTY, Outcome.MISSING, folder=folder)
    if not safefile.ensure_real_dir(folder, release=release, create=False):
        return LoadedSettings.no_file(FOLDER_IS_LINK, folder=folder)
    safefile.remove_stale_temps(folder, FILE_NAME)
    target = folder / FILE_NAME
    result = safefile.read_regular(target, MAX_FILE_BYTES)
    if result.kind is ReadKind.MISSING:
        return LoadedSettings(_EMPTY, Outcome.MISSING, folder=folder)
    if result.kind is ReadKind.UNREADABLE:
        return LoadedSettings(_EMPTY, Outcome.UNREADABLE, UNREADABLE, folder=folder,
                              writable=False)
    if result.kind is ReadKind.NOT_REGULAR:
        loaded = _bad(NOT_REGULAR)
    elif result.kind is ReadKind.TOO_LARGE:
        loaded = _bad(OVER_CAP)
    else:
        assert result.data is not None
        loaded = parse_settings(result.data)
    moved = loaded.outcome is Outcome.BAD and safefile.quarantine(target, BAD_NAME)
    return LoadedSettings(loaded.values, loaded.outcome, loaded.bad_reason, loaded.problems,
                          loaded.unknown, folder=folder, writable=loaded.writable,
                          quarantined=moved)


# --- Writing ----------------------------------------------------------------------------------

def encode_settings(values: Mapping[str, Value]) -> bytes:
    """The file for ``values`` (TR-F16-01): ASCII, keys sorted at both levels, ``indent=2``
    (``json.dumps`` layout, except that ``window_size`` stays on one line as
    ``[1280, 720]``, as in 04 §4), and a final newline. ``ValueError`` for an unknown key
    or a value failing ``check`` (the service only stores checked values)."""
    lines: list[str] = []
    for key in sorted(values):
        value = values[key]
        if check(key, value) is not None:
            raise ValueError("not a valid settings value")
        shown = list(value) if isinstance(value, (list, tuple)) else value
        lines.append(f"    {json.dumps(key)}: {json.dumps(shown, allow_nan=False)}")
    body = "{\n" + ",\n".join(lines) + "\n  }" if lines else "{}"
    return f'{{\n  "format": {FORMAT},\n  "values": {body}\n}}\n'.encode("ascii")


__all__ = ["BAD_NAME", "FILE_NAME", "FOLDER_IS_LINK", "FOLDER_NAME", "LOG_AREA", "LoadedSettings",
           "MAX_DEPTH", "NOT_REGULAR", "NOT_SETTINGS", "NOT_VALID_JSON", "NO_PERMISSION",
           "OVER_CAP", "Outcome", "TEMP_RE", "UNREADABLE", "display_file", "encode_settings",
           "is_engine_name", "parse_settings", "read_settings", "settings_root"]

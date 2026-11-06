"""Studio's own per-game state, ``<game>/.studio/studio.json`` (F47 ``04-technical.md`` §3.1,
§8.4, §10; ADR-0008 Amendment 2 as widened for F47: "files Studio names in ``.studio/``").

Why this module exists: whether the Guide pane (and F48's Assistant pane) is open, whether
the author has played the game from Studio yet ("Play it", Guide step 7), and whether the
game was made from the sample story are Studio's data, not the story's. They live beside
``storymap.json`` and follow ``layoutfile``'s read and write safety rules. Pure Python, no
Tk.

- ``read_state`` returns a ``StudioState``: the defaults when the folder or the file is
  missing (04 §10), else the stored values. A damaged file (not strict UTF-8 JSON, ``NaN``,
  not an object, too large) gives a ``StateProblem``, and the caller uses the defaults.
  ``.studio`` and the file must ``lstat`` as a real folder and a regular file (no link,
  junction or reparse point); otherwise the ``StateProblem`` has ``link`` set and the caller
  stops writing. Known keys must be JSON booleans; a key that isn't keeps its default.
  ``celebrated`` (Studio UX 4.2) is a list of milestone words; anything else in it is
  dropped. Unknown keys are ignored. Never raises.
- ``encode_state`` is pure and deterministic: one key per line, in ``KEYS`` order, LF
  (``OPTIONAL_KEYS`` only when true, ``celebrated`` only when not empty, sorted).
- ``write_state`` writes those bytes as ``layoutfile.write_layout`` does: ``.studio`` made by
  ``safefile.ensure_real_dir``, the target missing or regular, unchanged bytes skipped, then
  ``safefile.write_atomic`` with the stamp re-checked. Never raises; nothing but the file and
  its temp is made in the folder.

Imports only ``engine.core`` and the standard library (ADR-0008).
"""

import json
import os
import stat
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Final

from engine.core import safefile

STATE_DIR: Final = ".studio"
STATE_NAME: Final = "studio.json"
STATE_MAX_BYTES: Final = 16 * 1024

READ_TEXT: Final = "Studio's settings for this game couldn't be read, so it uses its defaults."
WRITE_TEXT: Final = "Studio's settings for this game couldn't be saved."


@dataclass(frozen=True, slots=True)
class StudioState:
    """``guide_open``: the Guide pane is shown. ``played``: a Play reached the game window
    (Guide step 7; once true it stays true). ``sample``: made from the sample story, so the
    Guide counts only what the author adds to it (``guide.SAMPLE_BASELINE``)."""

    guide_open: bool = False
    played: bool = False
    sample: bool = False
    assistant_open: bool = False    # F48 (04 §10): the Assistant pane is shown
    follow_changes: bool = False    # F58 (ADR-0008 Am. 6 §4): the map scrolls to changes
    reduce_motion: bool = False     # F58: View ▸ Reduce motion (the glow is static)
    panes: dict | None = None       # docking.Layout.to_json(); None: Studio's usual layout
    tabs: dict | None = None        # tabchoice: {"hidden": [...]}; None: the usual tabs
    celebrated: tuple[str, ...] = ()    # Studio UX 4.2: milestones already shown, once each


KEYS: Final = tuple(f.name for f in fields(StudioState)
                    if f.name not in ("panes", "tabs", "celebrated"))
MILESTONE_MAX: Final = 16               # more words than Studio has milestones: ignored
MILESTONE_CHARS: Final = 24
# Written only when true (missing means false), so a game whose author never opened the
# Assistant pane keeps its bytes.
OPTIONAL_KEYS: Final = frozenset({"assistant_open", "follow_changes", "reduce_motion"})


@dataclass(frozen=True, slots=True)
class StateProblem:
    """Why the file couldn't be read or written. ``text`` is the one status line; ``reason``
    a short word for tests and logs; ``link`` means writing must stop for this window."""

    reason: str
    text: str = READ_TEXT
    link: bool = False


def _umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


# As layoutfile (07 I-9): a new file gets the mode a plain ``open`` would give it.
NEW_FILE_MODE: Final = 0o666 & ~_umask() if os.name == "posix" else None


def state_path(root: Path) -> Path:
    return Path(root) / STATE_DIR / STATE_NAME


def _is_listed_path(path: Path) -> bool:
    return (os.path.normcase(os.path.realpath(path))
            == os.path.normcase(os.path.abspath(path)))


def _reject_constant(name: str) -> object:
    raise ValueError(name)


# --- Reading ---------------------------------------------------------------------------------

def read_state(root: Path) -> StudioState | StateProblem:
    """The stored state, the defaults when the folder or file is missing, else a
    ``StateProblem``. Never raises."""
    try:
        return _read(Path(root))
    except Exception:                    # a bug or an odd OS error: the defaults
        return StateProblem("unreadable")


def _read(root: Path) -> StudioState | StateProblem:
    folder = root / STATE_DIR
    if not os.path.lexists(folder):
        return StudioState()
    if not safefile.ensure_real_dir(folder, create=False):
        return StateProblem("folder not real", link=True)
    target = folder / STATE_NAME
    kind = safefile.entry_kind(target)
    if kind is safefile.EntryKind.MISSING:
        return StudioState()
    if kind is not safefile.EntryKind.REGULAR or not _is_listed_path(target):
        return StateProblem("file not regular", link=True)
    result = safefile.read_regular(target, STATE_MAX_BYTES)
    if result.kind is safefile.ReadKind.MISSING:
        return StudioState()
    if result.kind is safefile.ReadKind.NOT_REGULAR:
        return StateProblem("file not regular", link=True)
    if result.kind is safefile.ReadKind.TOO_LARGE:
        return StateProblem("too large")
    if not result.ok or result.data is None:
        return StateProblem("unreadable")
    return decode_state(result.data)


def decode_state(data: bytes) -> StudioState | StateProblem:
    """Strict UTF-8 JSON, an object; each known key a boolean (else its default)."""
    if len(data) > STATE_MAX_BYTES:
        return StateProblem("too large")
    try:
        doc = json.loads(data.decode("utf-8", errors="strict"),
                         parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return StateProblem("damaged")
    if not isinstance(doc, dict):
        return StateProblem("damaged")
    panes, tabs = doc.get("panes"), doc.get("tabs")
    return StudioState(**{key: doc[key] for key in KEYS if type(doc.get(key)) is bool},
                       panes=panes if isinstance(panes, dict) else None,
                       tabs=tabs if isinstance(tabs, dict) else None,
                       celebrated=_milestones(doc.get("celebrated")))


def _milestones(value: object) -> tuple[str, ...]:
    """``celebrated``'s words: short identifiers only, sorted, without repeats."""
    if not isinstance(value, list):
        return ()
    words = {word for word in value[:MILESTONE_MAX] if isinstance(word, str)
             and 0 < len(word) <= MILESTONE_CHARS and word.isascii() and word.isidentifier()}
    return tuple(sorted(words))


# --- Encoding and writing --------------------------------------------------------------------

def encode_state(state: StudioState) -> bytes:
    rows = [f'  "{key}": {"true" if getattr(state, key) else "false"}'
            for key in KEYS if key not in OPTIONAL_KEYS or getattr(state, key)]
    if state.panes:                         # written only when the author moved a pane
        rows.append('  "panes": ' + json.dumps(state.panes, sort_keys=True,
                                               ensure_ascii=True))
    if state.tabs:                          # written only when the author hid or showed a tab
        rows.append('  "tabs": ' + json.dumps(state.tabs, sort_keys=True, ensure_ascii=True))
    celebrated = _milestones(list(state.celebrated))
    if celebrated:                          # written only once a milestone was shown
        rows.append('  "celebrated": ' + json.dumps(list(celebrated), ensure_ascii=True))
    return ("{\n" + ",\n".join(rows) + "\n}\n").encode("ascii")


def write_state(root: Path, state: StudioState) -> StateProblem | None:
    """Write ``state``; None on success or when the file already holds these bytes. Never
    raises."""
    try:
        return _write(Path(root), encode_state(state))
    except Exception:
        return StateProblem("write failed", WRITE_TEXT)


def _write(root: Path, data: bytes) -> StateProblem | None:
    folder = root / STATE_DIR
    if not safefile.ensure_real_dir(folder):
        link = os.path.lexists(folder)
        return StateProblem("folder not real" if link else "write failed", WRITE_TEXT,
                            link=link)
    target = folder / STATE_NAME
    try:
        st = os.lstat(target)
    except FileNotFoundError:
        st = None
    if st is not None:
        if not safefile.is_regular(st) or not _is_listed_path(target):
            return StateProblem("file not regular", WRITE_TEXT, link=True)
        old = safefile.read_regular(target, STATE_MAX_BYTES)
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
        return StateProblem("changed", WRITE_TEXT)
    except OSError:
        return StateProblem("write failed", WRITE_TEXT)
    return None


def with_change(root: Path, **changes: object) -> StateProblem | None:
    """Read, change ``changes`` (e.g. ``guide_open=False`` or ``played=True``) and write
    back. A damaged file is replaced from the defaults; a link stops the write."""
    current = read_state(root)
    if isinstance(current, StateProblem):
        if current.link:
            return replace(current, text=WRITE_TEXT)
        current = StudioState()
    return write_state(root, replace(current, **changes))


__all__ = ["KEYS", "OPTIONAL_KEYS", "STATE_DIR", "STATE_NAME", "StateProblem", "StudioState",
           "decode_state", "encode_state", "read_state", "state_path", "with_change",
           "write_state"]

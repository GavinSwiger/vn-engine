"""Game-folder containment, per-user folders, app ids, and display forms of paths.

Why this module exists: every file the engine reads from a game folder (config, icon,
images, fonts; later script includes and refs restored from save files) must stay inside
that folder, whatever the reference string or the folder's links say (invariant 9 (a),
SEC-F01-01..04). ``GamePaths.resolve`` / ``read_file`` are the one way to do that: refs are
checked by fixed syntax rules before any file-system call, paths are built only from names
returned by directory listings, and each directory is containment-checked before it is
listed. The module also owns the single ``app_id`` validator and the per-user folder rules
of ADR-0003, which ``persist`` (F11, F12) reuses without importing ``app``.

This is one of the two modules allowed to look up the home folder and the environment
variables that locate the ADR-0003 folders (SEC-F01-12, invariant 9 (c)). Their raw values
are only ever output through ``display_path`` or the redactor.
"""

import difflib
import os
import re
import stat
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from engine.core.constants import REF_MAX_CHARS, SEGMENT_MAX_CHARS, WRITE_ROOT_DIRNAMES
from engine.core.errors import (
    AssetMissing,
    AssetNotFile,
    AssetRefError,
    AssetTooLarge,
    AssetUnreadable,
    UserFacingError,
)
from engine.core.redact import echo, redact

# --- Reference syntax (PR-F01-55, SEC-F01-04; §7.7 step 1) -------------------------------

REASON_TOO_LONG = "paths can be at most 1,024 characters long"
REASON_EMPTY = "paths can't be empty"
REASON_CONTROL = "paths can't contain control characters"
REASON_OUTSIDE = ("paths must stay inside the game folder and use forward slashes, "
                  "e.g. images/bg/club.png")
REASON_SEGMENT_TOO_LONG = "each file or folder name can be at most 255 characters long"
REASON_TRAILING = "file and folder names can't end with a dot or a space"
REASON_WRITE_ROOT = "is a folder the game writes to"         # F31 SEC-F31-03(a)

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

# Windows device names, compared with str.casefold() on the part before the first dot.
_RESERVED_BASENAMES = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"com{c}" for c in "0123456789¹²³"}
    | {f"lpt{c}" for c in "0123456789¹²³"}
)


# The engine's write roots, compared with str.casefold() on a ref's first segment (F31).
_WRITE_ROOTS = frozenset(name.casefold() for name in WRITE_ROOT_DIRNAMES)


def check_ref(ref: str) -> None:
    """PR-F01-55 / SEC-F01-04 syntax rules (§7.7 step 1), then F31's write-root rule: a ref
    whose first segment casefolds to a ``WRITE_ROOT_DIRNAMES`` entry (``characters/``,
    ``saves/``, ``persistent/``, ``settings/``, ``logs/``) is refused (``REASON_WRITE_ROOT``;
    SEC-F31-03(a)), so no asset, config, or audio ref reaches a folder the game writes to.
    No file-system call. Raises AssetRefError with the reason text for the first rule
    broken."""
    _check_syntax(ref)
    first = ref.split("/", 1)[0]
    if first.casefold() in _WRITE_ROOTS:
        raise AssetRefError(ref, f'"{first}" {REASON_WRITE_ROOT}')


def _check_syntax(ref: str) -> None:
    """``check_ref`` without the write-root rule (``GamePaths.write_root`` only)."""
    if len(ref) > REF_MAX_CHARS:
        raise AssetRefError(ref, REASON_TOO_LONG)
    if ref == "":
        raise AssetRefError(ref, REASON_EMPTY)
    if _CONTROL_RE.search(ref):
        raise AssetRefError(ref, REASON_CONTROL)
    segments = ref.split("/")
    if "\\" in ref or ":" in ref or ref.startswith("/") or segments[0].startswith("~"):
        raise AssetRefError(ref, REASON_OUTSIDE)
    if any(seg in ("", ".", "..") for seg in segments):
        raise AssetRefError(ref, REASON_OUTSIDE)
    if any(len(seg) > SEGMENT_MAX_CHARS for seg in segments):
        raise AssetRefError(ref, REASON_SEGMENT_TOO_LONG)
    if any(seg.endswith((".", " ")) for seg in segments):
        raise AssetRefError(ref, REASON_TRAILING)
    for seg in segments:
        base = seg.split(".", 1)[0].rstrip(" .")
        if base.casefold() in _RESERVED_BASENAMES:
            raise AssetRefError(ref, f'"{base}" is a reserved file name on Windows')


def is_device_name(name: str) -> bool:
    """Whether Windows reads the file or folder name ``name`` as a device (``CON``,
    ``com¹.png``, ``nul .txt``): ``check_ref``'s reserved-name rule for one name. Public for
    F42's build names and copy walk (SEC-F42-06 f, -12). No file-system call."""
    base = name.split(".", 1)[0].rstrip(" .")
    return base.casefold() in _RESERVED_BASENAMES


# --- Meta file names (F31 04 §3, 07 I-1; SR-F31-02, SEC-F31-01) -------------------------

# The device names a meta file's base must not be: the ASCII entries of
# ``_RESERVED_BASENAMES`` the name pattern could otherwise match (``conin$`` and ``com¹``
# can't match it anyway). A meta name has exactly one dot, so its base is all before it.
# Public for the parser's E310 ``reserved`` form (F31 step 2).
META_RESERVED_BASES: tuple[str, ...] = tuple(sorted(
    base for base in _RESERVED_BASENAMES if re.fullmatch(r"[a-z0-9]+", base, re.ASCII)))
# Lower-case ASCII letters, digits, ``_`` and ``-`` (not first), a base of 1 to 32, then
# ``.chr`` or ``.txt``; never a Windows device name. Used with ``fullmatch`` everywhere: the
# parser, ``MetaFolder``, ``MemoryFolder``, and the writer's ``meta`` client (one rule).
META_NAME_RE = re.compile(r"(?!(?:" + "|".join(META_RESERVED_BASES) + r")\.)"
                          r"[a-z0-9][a-z0-9_-]{0,31}\.(?:chr|txt)", re.ASCII)


def is_meta_name(name: object) -> bool:
    """A str that ``META_NAME_RE`` matches whole (no file-system call)."""
    return type(name) is str and META_NAME_RE.fullmatch(name) is not None


# --- app ids (ADR-0003 §4, SEC-F01-16) ---------------------------------------------------

APP_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}", re.ASCII)
RESERVED_APP_IDS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{d}" for d in range(10)}
    | {f"lpt{d}" for d in range(10)}
)


def is_valid_app_id(value: object) -> bool:
    """The single app_id validator (SEC-F01-16 (a)): type(value) is str,
    APP_ID_RE.fullmatch(value) with APP_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}", re.ASCII),
    and value not in RESERVED_APP_IDS ({'con','prn','aux','nul','com0'..'com9','lpt0'..'lpt9'}).
    Never lower-cases, trims, or normalizes the value."""
    return (type(value) is str
            and APP_ID_RE.fullmatch(value) is not None
            and value not in RESERVED_APP_IDS)


def slugify(text: str) -> str:
    """Fallback app_id from a folder name: NFKD → drop non-ASCII → lower → runs of
    characters outside [a-z0-9] become '-' → strip '-' → cut to 40 → strip '-' again →
    '' becomes 'game' → a reserved result r becomes f'{r}-game'. Asserts
    is_valid_app_id(result)."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    slug = slug[:40].strip("-")
    if not slug:
        slug = "game"
    elif slug in RESERVED_APP_IDS:
        slug = f"{slug}-game"
    assert is_valid_app_id(slug), slug
    return slug


# --- Home, environment, and per-user folders (ADR-0003 §3, SEC-F01-17) -------------------

def home_dir() -> Path | None:
    """Path.home() if absolute, else None (never raises)."""
    try:
        home = Path.home()
    except (RuntimeError, KeyError, OSError):
        return None
    return home if home.is_absolute() else None


def _is_windows_absolute(value: str) -> bool:
    """An absolute drive path (``C:\\…``) or a UNC path (``\\\\server\\share…``)."""
    return bool(re.match(r"[A-Za-z]:[\\/]", value)
                or re.match(r"(?:\\\\|//)[^\\/]+[\\/][^\\/]+", value))


def _windows_env_dir(name: str) -> Path | None:
    """%APPDATA% / %LOCALAPPDATA% if set to an absolute drive or UNC path, else None."""
    value = os.environ.get(name, "")
    return Path(value) if value and _is_windows_absolute(value) else None


def _xdg_data_home() -> Path | None:
    """$XDG_DATA_HOME if set to an absolute path (XDG Base Directory spec), else None."""
    value = os.environ.get("XDG_DATA_HOME", "")
    if not value:
        return None
    absolute = _is_windows_absolute(value) if sys.platform == "win32" else value.startswith("/")
    return Path(value) if absolute else None


def _require_app_id(app_id: str) -> None:
    if not is_valid_app_id(app_id):
        raise ValueError(f"not a valid app id: {app_id!r}")


def user_data_dir(app_id: str) -> Path | None:
    """Windows %APPDATA%\\vn-engine\\<id>; macOS ~/Library/Application Support/vn-engine/<id>;
    other $XDG_DATA_HOME/vn-engine/<id> (only if absolute) else ~/.local/share/vn-engine/<id>.
    Raises ValueError if not is_valid_app_id(app_id). Returns None when no absolute base
    exists (the caller treats the folder as not writable). Never returns a relative path.
    Not created here."""
    _require_app_id(app_id)
    if sys.platform == "win32":
        base = _windows_env_dir("APPDATA")
    elif sys.platform == "darwin":
        home = home_dir()
        base = None if home is None else home / "Library" / "Application Support"
    else:
        base = _xdg_data_home()
        if base is None:
            home = home_dir()
            base = None if home is None else home / ".local" / "share"
    return None if base is None else base / "vn-engine" / app_id


def user_log_dir(app_id: str) -> Path | None:
    """Windows %LOCALAPPDATA%\\vn-engine\\<id>\\logs; elsewhere user_data_dir(app_id)/logs.
    Same ValueError / None rules."""
    _require_app_id(app_id)
    if sys.platform == "win32":
        base = _windows_env_dir("LOCALAPPDATA")
        return None if base is None else base / "vn-engine" / app_id / "logs"
    data = user_data_dir(app_id)
    return None if data is None else data / "logs"


def display_path(path: Path, *, game_root: Path | None) -> str:
    """The redacted display form (§7.10.6): '<game>/…', '%LOCALAPPDATA%\\…', '%APPDATA%\\…',
    '$XDG_DATA_HOME/…', '~/…', else str(path). The longest matching base wins."""
    bases: list[tuple[Path, str, str]] = []          # (base, token, separator)
    if game_root is not None:
        bases.append((game_root, "<game>", "/"))
    if sys.platform == "win32":
        for name in ("LOCALAPPDATA", "APPDATA"):
            base = _windows_env_dir(name)
            if base is not None:
                bases.append((base, f"%{name}%", "\\"))
    xdg = _xdg_data_home()
    if xdg is not None:
        bases.append((xdg, "$XDG_DATA_HOME", "/"))
    home = home_dir()
    if home is not None:
        bases.append((home, "~", "/"))

    best: tuple[int, str, str, tuple[str, ...]] | None = None
    for base, token, sep in bases:
        if path.is_relative_to(base):
            depth = len(base.parts)
            if best is None or depth > best[0]:
                best = (depth, token, sep, path.relative_to(base).parts)
    if best is None:
        return redact(str(path))
    _, token, sep, rest = best
    return sep.join((token, *rest))


def engine_root() -> Path:
    """Repo root (parent of engine/), or sys._MEIPASS when frozen."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent.parent


def engine_data_dir() -> Path:
    """engine_root()/'engine'/'data'."""
    return engine_root() / "engine" / "data"


def is_frozen() -> bool:
    """bool(getattr(sys, "frozen", False))."""
    return bool(getattr(sys, "frozen", False))


# --- The contained reader (invariant 9 (a); §7.7) ----------------------------------------

_GAME_FOLDER_HINT = "Check that the folder exists, or run: python -m engine run <folder>"


_SUGGESTION_MEMO_MAX = 256           # remembered "did you mean" answers per directory

# Entry kinds recorded from os.DirEntry when a directory is listed (no extra system call on
# Windows or on file systems that report d_type). Only _LINK entries are ever resolved.
# _SPECIAL (a FIFO, device, or socket) is listed as a file by ``list_dir`` (as before F23)
# and left out by ``list_real`` (F23 07 C5, I-5).
# Public (F42 07 I-3) so walkers outside this module classify entries the same way; the
# private names stay for this module and the tests that patch them.
ENTRY_FILE, ENTRY_DIR, ENTRY_LINK, ENTRY_SPECIAL = 0, 1, 2, 3
_FILE, _DIR, _LINK, _SPECIAL = ENTRY_FILE, ENTRY_DIR, ENTRY_LINK, ENTRY_SPECIAL
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def dir_entry_kind(entry: os.DirEntry) -> int:
    """_LINK for a symlink, a junction, or any other Windows reparse point (and for an entry
    whose type can't be read, so it is resolved and containment-checked like a link);
    otherwise _DIR, _FILE, or _SPECIAL without following anything."""
    try:
        if entry.is_symlink() or entry.is_junction():
            return _LINK
        if os.name == "nt" and entry.stat(follow_symlinks=False).st_file_attributes \
                & _REPARSE_POINT:
            return _LINK
        if entry.is_dir(follow_symlinks=False):
            return _DIR
        return _FILE if entry.is_file(follow_symlinks=False) else _SPECIAL
    except OSError:
        return _LINK


_entry_kind = dir_entry_kind        # private alias: this module calls it (tests patch it)


def is_listed_path(path: Path) -> bool:
    """The real path of ``path`` (built from listed names under a real folder) is ``path``
    itself (normcase): not a symlink, junction, or link reparse point, wherever it points.
    A reparse point that resolves to itself (a cloud placeholder, dedup) passes."""
    try:
        real = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    return os.path.normcase(str(real)) == os.path.normcase(str(path))


_is_listed_path = is_listed_path    # private alias: this module calls it


@dataclass(frozen=True)
class DirListing:
    """A contained directory listing (F02 04 §5.2): names in exact case, code-point sorted.
    Entries whose real path is outside the game folder are omitted, never named.

    ``list_real`` (F23 C5) also fills ``omitted``: the names it left out (links, wherever
    they point, and FIFOs, devices, and sockets), names only, never targets; ``special``
    is the part of ``omitted`` that isn't a link (W163's "isn't a regular file" form)."""
    files: tuple[str, ...]
    dirs: tuple[str, ...]
    omitted: tuple[str, ...] = ()
    special: tuple[str, ...] = ()


@dataclass(frozen=True)
class RealDir:
    """``real_dir``'s answer for a real folder: ``path`` is both its listed and real path."""
    ref: str
    path: Path


@dataclass(frozen=True)
class NotReal:
    """``real_dir``'s answer otherwise. ``kind``: "missing" (no entry with exactly that
    name; ``other_case`` is a listed name equal to the last segment up to case, e.g.
    ``Minigames``), "link" (a symlink, junction, link reparse point, or a real path that
    differs from the listed one), or "not_dir" (a file, FIFO, or device)."""
    kind: str
    other_case: str | None = None


@dataclass(frozen=True)
class WalkResult:
    """``walk_files`` output: game-relative refs, code-point sorted; ``truncated`` when the
    walk stopped at ``max_entries``."""
    refs: tuple[str, ...]
    truncated: bool


@dataclass(frozen=True)
class _Contents:
    """What ``list_dir`` reports for one directory, plus the real path of each listed
    folder (for ``walk_files``), in the same order as ``listing.dirs``."""
    listing: DirListing
    dir_paths: tuple[Path, ...]


@dataclass(frozen=True)
class _Listing:
    """One cached directory scan. Everything derived from it (suggestions, resolved
    subfolders, the contained contents) lives here, so ``invalidate_listings()`` is the
    only reset point."""
    exact: frozenset[str]
    folded: dict[str, list[str]]
    ordered: tuple[str, ...] = ()       # sorted names, for difflib
    suggestions: dict[str, str | None] = field(default_factory=dict, compare=False)
    kinds: dict[str, int] = field(default_factory=dict, compare=False)
    # name → real path of a subfolder already proven contained, a directory, and listed
    # (its own _Listing is cached). AC-F01-140 / F01 I-11: saves the strict resolve and
    # is_dir of every walked folder on repeated lookups. Bounded by the listing's size.
    subdirs: dict[str, Path] = field(default_factory=dict, compare=False)
    contents: list[_Contents] = field(default_factory=list, compare=False)  # 0 or 1 items
    real: list[DirListing] = field(default_factory=list, compare=False)     # list_real: 0 or 1

    def close_match(self, segment: str) -> str | None:
        """The closest listed name (difflib, cutoff 0.8), remembered for repeated misses
        (SEC-F01-05: a bad ref must stay cheap however often it is requested)."""
        if segment in self.suggestions:
            return self.suggestions[segment]
        close = difflib.get_close_matches(segment, self.ordered, 1, 0.8)
        found = close[0] if close else None
        if len(self.suggestions) < _SUGGESTION_MEMO_MAX:
            self.suggestions[segment] = found
        return found


@dataclass(frozen=True)
class GamePaths:
    """The resolved game folder and the only way to read files inside it.

    Standard subfolder names live in constants.GAME_SUBFOLDERS. There is no config_file
    field: config.toml is read through read_file("config.toml") like every other file.
    The log folder is not here: logsetup chooses it after config is loaded (§7.10.1).
    """

    root: Path               # Path(game_dir).resolve(strict=True); a directory
    _listings: dict[str, _Listing] = field(default_factory=dict, init=False,
                                           repr=False, compare=False)
    # The resolved root is fixed for the session, so its comparison form is computed once.
    _root_key: str = field(default="", init=False, repr=False, compare=False)
    _root_prefix: str = field(default="", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        key = os.path.normcase(str(self.root))
        object.__setattr__(self, "_root_key", key)
        object.__setattr__(self, "_root_prefix", key if key.endswith(os.sep) else key + os.sep)

    def contains(self, real: Path) -> bool:
        """``real.is_relative_to(self.root)`` for a resolved ``real``: the same
        case-normalized, whole-segment comparison, without building parent paths."""
        key = os.path.normcase(str(real))
        return key == self._root_key or key.startswith(self._root_prefix)

    @classmethod
    def for_game(cls, game_dir: Path) -> "GamePaths":
        """Resolve the root strictly. Raises UserFacingError (missing / not a folder) whose
        message shows display_path(game_dir.absolute(), game_root=None)."""
        game_dir = Path(game_dir)
        shown = echo(display_path(game_dir.absolute(), game_root=None))
        try:
            root = game_dir.resolve(strict=True)
        except (OSError, RuntimeError):
            raise UserFacingError(
                f'Can\'t find the game folder "{shown}". {_GAME_FOLDER_HINT}') from None
        if not root.is_dir():
            raise UserFacingError(f'"{shown}" is a file, not a folder. {_GAME_FOLDER_HINT}')
        return cls(root)

    def resolve(self, ref: str) -> Path:
        """check_ref, then the containment-before-listing walk (§7.7). Returns the real,
        contained path of an existing entry. Raises AssetRefError or AssetMissing.
        Never opens a file and never lists a directory outside the root."""
        return self._resolve_listed(ref)[1]

    def write_root(self, name: str) -> Path | None:
        """The real, contained path of the write root ``name`` (one of
        ``WRITE_ROOT_DIRNAMES``, else ``ValueError``), or None when it is missing, differs
        in letter case, or leaves the game folder. The only lookup ``check_ref``'s
        write-root rule doesn't apply to: F02's script-folder overlap check
        (SEC-F02-11, SEC-F31-03(b)). Never opens a file."""
        if type(name) is not str or name not in WRITE_ROOT_DIRNAMES:
            raise ValueError("not a write root name")
        try:
            return self._resolve_listed(name, write_root=True)[1]
        except (AssetMissing, AssetRefError):
            return None

    def _resolve_listed(self, ref: str, *, write_root: bool = False) -> tuple[Path, Path]:
        """``resolve`` that also returns the **listed** path of the last segment (its real
        parent folder plus the listed name): ``(listed, real)``. ``write_root``: only
        ``write_root``'s own lookup skips the write-root rule."""
        if write_root:
            _check_syntax(ref)
        else:
            check_ref(ref)
        segments = ref.split("/")
        last = len(segments) - 1
        cur = self.root                  # contained by definition
        walked: list[str] = []           # real names of the segments walked so far
        case_mismatch = False
        real = cur
        parent: _Listing | None = None   # listing that ``cur`` was just resolved from
        for index, seg in enumerate(segments):
            try:
                listing = self._listing(cur)
            except OSError:
                raise AssetMissing(ref, None) from None
            if parent is not None:
                # ``cur`` is contained, a directory, and now listed: remember it for the
                # lifetime of the parent's listing (I-11). Stored only after its own listing
                # is cached, so a cached folder never causes a new scan.
                parent.subdirs[walked[-1]] = cur
                parent = None
            if seg in listing.exact:
                name = seg
            else:
                same_folded = listing.folded.get(seg.casefold(), [])
                if len(same_folded) == 1:
                    name = same_folded[0]
                    case_mismatch = True
                else:
                    close = listing.close_match(seg)
                    suggestion = "/".join([*walked, close]) if close is not None else None
                    raise AssetMissing(ref, suggestion)
            if index < last:
                cached = listing.subdirs.get(name)
                if cached is not None:
                    walked.append(name)
                    cur = cached
                    continue
            candidate = cur / name       # built only from a listed name (SEC-F01-01 (a))
            try:
                real = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                raise AssetMissing(ref, None) from None
            if not self.contains(real):
                raise AssetRefError(ref, REASON_OUTSIDE)
            walked.append(name)
            if index < last:
                if not real.is_dir():
                    raise AssetMissing(ref, None)
                cur = real
                parent = listing
        # The final target is always resolved strictly and containment-checked above, so a
        # folder swapped for a link after it was cached is followed by that resolve and an
        # escape is still rejected (tests: test_paths_listing.py, I-11).
        if case_mismatch:
            raise AssetMissing(ref, "/".join(walked))
        return candidate, real

    def read_file(self, ref: str, *, max_bytes: int, regular: bool = False) -> bytes:
        """resolve(ref), then: not a regular file → AssetNotFile; st_size or bytes read
        > max_bytes → AssetTooLarge (reads at most max_bytes + 1 bytes); OSError →
        AssetUnreadable. The only way F01 reads a game-folder file (SEC-F01-01).

        ``regular=True`` (F23 C5, I-5; SEC-F23-01 (c)): at read time the **listed** path
        must be a regular file by ``lstat`` whose real path is itself, so a link swapped in
        after the listing (contained or not) is AssetNotFile and is never read. A reparse
        point that resolves to itself (a cloud placeholder) passes. POSIX still opens with
        ``O_NOFOLLOW | O_NONBLOCK``, so a FIFO or device can't hang the read."""
        real = self._regular_real(ref) if regular else self.resolve(ref)
        try:
            st = os.stat(real)
        except OSError:
            raise AssetUnreadable(ref) from None
        if not stat.S_ISREG(st.st_mode):
            raise AssetNotFile(ref)
        if st.st_size > max_bytes:
            raise AssetTooLarge(ref, max_bytes)
        try:
            with _open_regular(real) as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise AssetNotFile(ref)
                data = _read_bounded(stream, st.st_size, max_bytes + 1)
        except OSError:
            raise AssetUnreadable(ref) from None
        if len(data) > max_bytes:
            raise AssetTooLarge(ref, max_bytes)
        return data

    def file_size(self, ref: str) -> int:
        """The size of the regular file ``ref`` by ``os.stat``, with ``read_file(regular=True)``'s
        checks (the listed path is a regular file by ``lstat`` whose real path is itself,
        contained). Raises as ``read_file`` does; never opens the file (F31 E313)."""
        real = self._regular_real(ref)
        try:
            st = os.stat(real)
        except OSError:
            raise AssetUnreadable(ref) from None
        if not stat.S_ISREG(st.st_mode):
            raise AssetNotFile(ref)
        return st.st_size

    def _regular_real(self, ref: str) -> Path:
        """``read_file(regular=True)``'s entry check: the real path of ``ref`` when its
        listed path is a regular file by ``lstat`` and its real path is the path built from
        the listed names. AssetNotFile otherwise (AssetUnreadable when ``lstat`` fails)."""
        listed, real = self._resolve_listed(ref)
        # The path built from the listed names alone (nothing followed): a folder on the
        # way swapped for a link after the listing makes the real path differ too.
        built = self.root.joinpath(*ref.split("/"))
        try:
            lst = os.lstat(listed)
        except OSError:
            raise AssetUnreadable(ref) from None
        if (not stat.S_ISREG(lst.st_mode)
                or os.path.normcase(str(real)) != os.path.normcase(str(built))):
            raise AssetNotFile(ref)
        return real

    def display(self, path: Path) -> str:
        """display_path(path, game_root=self.root)."""
        return display_path(path, game_root=self.root)

    def list_dir(self, ref: str) -> DirListing | None:
        """resolve(ref) (check_ref + containment), then one cached listing. None if missing
        or not a directory; AssetRefError if it escapes. Entries whose real path is outside
        the root are omitted, never named (TR-F02-02)."""
        directory = self._resolve_dir(ref)
        if directory is None:
            return None
        contents = self._contents(directory)
        return None if contents is None else contents.listing

    def walk_files(self, ref: str, *, suffix: str, max_entries: int,
                   max_depth: int) -> WalkResult:
        """Breadth-first, list_dir rules, each real directory once (link loops end), suffix
        matched case-exactly, every listed entry counts toward max_entries. Opens no file.

        ``ref`` itself is depth 0; a folder at depth d is listed only if d <= max_depth.
        Entries are counted in each folder's code-point order (files and folders together);
        the walk stops with ``truncated=True`` at the first entry past ``max_entries``.
        A missing ``ref`` or a file gives no refs; an escaping one raises AssetRefError."""
        start = self._resolve_dir(ref)
        if start is None:
            return WalkResult((), False)
        visited = {os.path.normcase(str(start))}
        queue: list[tuple[str, Path, int]] = [(ref, start, 0)]
        refs: list[str] = []
        counted = 0
        truncated = False
        for prefix, directory, depth in queue:        # the list grows while it is read: BFS
            contents = self._contents(directory)
            if contents is None:
                continue
            listing = contents.listing
            subfolders = dict(zip(listing.dirs, contents.dir_paths))
            for name in sorted((*listing.files, *listing.dirs)):
                if counted >= max_entries:
                    truncated = True
                    break
                counted += 1
                real = subfolders.get(name)
                if real is None:
                    if name.endswith(suffix):
                        refs.append(f"{prefix}/{name}")
                elif depth < max_depth:
                    key = os.path.normcase(str(real))
                    if key not in visited:
                        visited.add(key)
                        queue.append((f"{prefix}/{name}", real, depth + 1))
            if truncated:
                break
        return WalkResult(tuple(sorted(refs)), truncated)

    def real_dir(self, ref: str) -> RealDir | NotReal:
        """F23 C5 (SEC-F23-01 (a)): ``ref`` names a real folder only if every segment is a
        listed directory with exactly that name (no case folding) that is not a symlink,
        junction, or link reparse point, and whose real path equals its listed path
        (normcase). ``resolve`` is not used, because it accepts contained links. A reparse
        point that resolves to its own path (a cloud placeholder) counts as a folder.
        AssetRefError (``check_ref``) propagates; nothing else is raised."""
        check_ref(ref)
        segments = ref.split("/")
        cur = self.root
        for index, seg in enumerate(segments):
            try:
                listing = self._listing(cur)
            except OSError:
                return NotReal("missing")
            if seg not in listing.exact:
                other = None
                if index == len(segments) - 1:
                    others = [n for n in listing.folded.get(seg.casefold(), []) if n != seg]
                    other = others[0] if others else None
                return NotReal("missing", other)
            kind = listing.kinds.get(seg, _LINK)
            path = cur / seg
            if kind in (_FILE, _SPECIAL):
                return NotReal("not_dir")
            if kind == _LINK:
                if not _is_listed_path(path):
                    return NotReal("link")
                if not path.is_dir():
                    return NotReal("not_dir")
            cur = path
        return RealDir(ref, cur)

    def list_real(self, ref: str) -> DirListing | None:
        """F23 C5 (SEC-F23-01 (b), (d)): the files and folders of the real folder ``ref``
        (``real_dir``) whose real path equals their listed path, wherever a link points,
        inside the game folder included (dev write roots hold outside data). FIFOs,
        devices, and sockets are left out; a reparse point that resolves to itself (a
        cloud placeholder, dedup) counts as a file or folder. Left-out names go in
        ``omitted`` (names only). None when ``ref`` is not a real folder. Uses the same
        listing cache as ``list_dir`` (``invalidate_listings`` clears both)."""
        found = self.real_dir(ref)
        if not isinstance(found, RealDir):
            return None
        directory = found.path
        try:
            listing = self._listing(directory)
        except OSError:
            return None
        if listing.real:
            return listing.real[0]
        files: list[str] = []
        dirs: list[str] = []
        omitted: list[str] = []
        special: list[str] = []
        for name in listing.ordered:
            kind = listing.kinds.get(name, _LINK)
            if kind == _FILE:
                files.append(name)
            elif kind == _DIR:
                dirs.append(name)
            elif kind == _SPECIAL:
                omitted.append(name)
                special.append(name)
            else:
                path = directory / name
                if not _is_listed_path(path):
                    omitted.append(name)
                    continue
                try:
                    mode = os.stat(path).st_mode
                except OSError:
                    omitted.append(name)
                    continue
                if stat.S_ISDIR(mode):
                    dirs.append(name)
                elif stat.S_ISREG(mode):
                    files.append(name)
                else:
                    omitted.append(name)
                    special.append(name)
        result = DirListing(tuple(files), tuple(dirs), tuple(omitted), tuple(special))
        listing.real.append(result)
        return result

    def invalidate_listings(self) -> None:
        """Forget cached directory listings and everything derived from them: suggestions,
        resolved folders (I-11), and list_dir contents (F39 hot-reload seam)."""
        self._listings.clear()

    def _resolve_dir(self, ref: str) -> Path | None:
        """The real, contained directory ``ref`` names, or None if it is missing (including
        a case mismatch) or not a directory. AssetRefError propagates."""
        try:
            real = self.resolve(ref)
        except AssetMissing:
            return None
        return real if real.is_dir() else None

    def _contents(self, directory: Path) -> _Contents | None:
        """The contained contents of ``directory`` (a real path proven under the root),
        computed once per cached listing. Only link entries are resolved; one whose real
        path is outside the root, or which can't be resolved, is left out."""
        try:
            listing = self._listing(directory)
        except OSError:
            return None
        if listing.contents:
            return listing.contents[0]
        files: list[str] = []
        dirs: list[tuple[str, Path]] = []
        for name in listing.ordered:
            kind = listing.kinds.get(name, _LINK)
            path = directory / name
            if kind == _FILE or kind == _SPECIAL:
                files.append(name)
            elif kind == _DIR:
                dirs.append((name, path))
            else:
                try:
                    real = path.resolve(strict=True)
                    if not self.contains(real):
                        continue
                    is_dir = real.is_dir()
                except (OSError, RuntimeError):
                    continue
                if is_dir:
                    dirs.append((name, real))
                else:
                    files.append(name)
        contents = _Contents(DirListing(tuple(files), tuple(name for name, _ in dirs)),
                             tuple(path for _, path in dirs))
        listing.contents.append(contents)
        return contents

    def _listing(self, directory: Path) -> _Listing:
        """The names in ``directory``, a real path already proven to be under the root."""
        key = str(directory)
        listing = self._listings.get(key)
        if listing is None:
            kinds: dict[str, int] = {}
            with os.scandir(directory) as entries:
                for entry in entries:
                    kinds[entry.name] = _entry_kind(entry)
            names = list(kinds)
            folded: dict[str, list[str]] = {}
            for name in names:
                folded.setdefault(name.casefold(), []).append(name)
            listing = _Listing(frozenset(names), folded, tuple(sorted(names)), kinds=kinds)
            self._listings[key] = listing
        return listing


_READ_CHUNK = 1 << 20


def _read_bounded(stream, expected: int, limit: int) -> bytes:
    """At most ``limit`` bytes. ``read(n)`` allocates ``n`` bytes up front, so asking for
    the 256 MiB limit on every image would reserve 256 MiB each time: read the size
    ``stat`` reported (plus one byte, to notice growth), then continue in 1 MiB chunks
    only if the file grew since."""
    data = stream.read(min(expected + 1, limit))
    if len(data) <= expected:
        return data
    parts = [data]
    total = len(data)
    while total < limit:
        chunk = stream.read(min(_READ_CHUNK, limit - total))
        if not chunk:
            break
        parts.append(chunk)
        total += len(chunk)
    return b"".join(parts)


def _open_regular(path: Path):
    """Open for binary reading without following a link or blocking on a FIFO (POSIX)."""
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        return os.fdopen(fd, "rb")
    return open(path, "rb")

"""Studio's project files: the tree model, and add, new script, rename, delete, and new game
(F45 ``04-technical.md`` §7.4, §7.5, §8; ADR-0008 Amendment 1; ``07`` I-7).

Pure Python, no Tk. Every operation returns its result or a ``Refusal`` (the one line Studio
shows); none raises for I/O. Each write re-runs the four checks of ``04`` §7.5 at the moment
it happens:

- **(F) Folder.** ``GamePaths.real_dir`` right after ``invalidate_listings``. Writes go only to
  ``RealDir.path / <validated name>``. A missing *group* folder is created with one
  ``os.mkdir``; never a subfolder. A folder that is a link, a junction or a file is refused
  (``04`` C-1).
- **(N) Name.** ``check_ref``, the group's suffix rule, and under ``images/`` every word of
  ``name_of``.
- **(C) Clash.** ``casefold()`` names against the folder's real listing (links and FIFOs
  included), on every OS.
- **(E) Existing file.** ``lstat``-regular, not a reparse point, and its real path is its
  listed path. A link or junction swapped in later is refused.

Writes go through ``safefile.write_atomic`` (exclusive temp, ``os.replace``); a new file gets
``0o666 & ~umask`` and a replaced file keeps its mode (``07`` I-7). Rename never replaces
(POSIX link-then-unlink, Windows ``os.rename``). Delete is ``recycle.to_recycle_bin`` (the
Recycle Bin; ``safefile.remove_file`` off Windows). Sources are read with
``safefile.read_regular``: never through a FIFO or device, never past the cap.
Messages name game refs and the source's file name only, never a path (``04`` §8.2).

Imports only ``engine.core``, ``engine.script`` and the standard library (ADR-0008).
"""

import errno
import json
import os
import stat
import string
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from engine.core import safefile
from engine.core.audiosniff import FORMAT_NAMES, matches, refused_signature
from engine.core.childcmd import engine_argv
from engine.core.constants import IMAGE_MAX_PIXELS, IMAGE_MAX_SIDE
from engine.core.errors import AssetMissing, AssetRefError
from engine.core.imageheader import image_dimensions
from engine.core.paths import (GamePaths, NotReal, RealDir, check_ref, engine_data_dir,
                               is_meta_name, slugify)
from engine.script.assetgroups import ASSET_GROUPS, CONFIG_REF, AssetGroup
from engine.script.imagenames import (
    CHARACTERS,
    DOT,
    HYPHEN,
    IMAGE_NAME_MAX_WORDS,
    SPACE,
    STAGE_WORD,
    STATEMENT_WORD,
    TOO_MANY_WORDS,
    NameProblem,
    image_suffix,
    name_of,
)
from engine.script.messages import format_message, show
from engine.script.metafiles import name_problem
from engine.script.source import decode_script
from engine.script.words import ROLE_LABEL, check_name, is_word_char
from engine.tools.editor import recycle

MAIN_REF = "script/main.vns"
SCRIPT_FOLDER = "script"
TREE_MAX_ENTRIES = 10_000            # files per group, and folders per group (§8.3)
TREE_MAX_DEPTH = 8                   # a group folder is depth 0
KEEP_BOTH_MAX = 10_000               # stem_2 … stem_10001 before giving up
STARTER_DIR = "starter"              # engine/data/starter
SAMPLE_DIR = "sample"                # engine/data/sample (F47 PR-F47-25)
TEMPLATE_SAMPLE = "sample"           # New game's "Start from" choices (F47 §6.4)
TEMPLATE_EMPTY = "empty"
TEMPLATES = ((TEMPLATE_SAMPLE, "A short sample story (recommended)"),
             (TEMPLATE_EMPTY, "An empty game"))
START_FROM = "Start from"
CONFIG_TEMPLATE = "config.toml.in"
AGENT_NOTES_DIR = "agent-notes"      # engine/data/agent-notes: AGENTS.md, CLAUDE.md
AGENT_NOTES = ("AGENTS.md", "CLAUDE.md")
SAMPLE_MAX_FILES = 64                # a template larger than this is a packaging mistake
SAMPLE_MAX_BYTES = 4 * 1024 * 1024

# --- Texts (design §6.3, edge cases; 04 C-1, C-2; G5, G6 wording chosen here) -----------

GAME_GONE = "The game folder can't be found."
MAIN_FIXED = "main.vns is where the story starts, so it can't be renamed or deleted here."
CONFIG_FIXED = "config.toml holds the game's settings, so it can't be renamed or deleted here."
FOLDER_FIXED = "Folders can't be renamed or deleted in Studio."
NOT_A_FOLDER = "`{folder}/` is a link or not a folder, so Studio won't add files there."
FOLDER_MISSING = "`{folder}/` can't be found."
NOT_OWN_FILE = "`{ref}` is a link or not a regular file, so Studio won't change it."
EXISTS = "`{ref}` already exists."
LOCKED = "Couldn't {verb} `{ref}`: the file is read-only or locked."
SYSTEM = "Couldn't {verb} `{ref}`: the system reported an error."
GONE = "Couldn't {verb} `{ref}`: the file was moved or deleted."
KEPT = "`{ref}` was kept: nothing was deleted."
# The Database's and the animation panel's Delete question for one file.
DELETE_FILE_ASK = ("Move {ref} to the Recycle Bin? You can restore it from there."
                   if recycle.AVAILABLE else
                   "Delete {ref} from the game folder? This can't be undone.")
CHANGED = "`{ref}` changed on disk after it was picked, so it wasn't replaced."
TRUST = "Minigames are Python code that the game runs. Only add code you trust."
NOT_REGULAR = "`{name}` is not a regular file."
CANT_READ = "`{name}` couldn't be read."
TOO_LARGE = "`{name}` is too large: {title} takes files up to {limit}."
TAKES = "`{name}`: {title} takes {kinds} files."
SAME_FOLDER = "`{name}` must be a file name in the same folder."
BAD_REF = "`{name}` can't be used as a file name: {reason}."
LABEL_NAME = "`{stem}` can't be a label name."
LABEL_FIX = "`{stem}` can't be a label name. Use `{fix}`."
IMAGE_NAME = "`{name}` can't be an image name ({why})."
IMAGE_OFFER = "`{name}` can't be an image name ({why}). Use `{offer}`?"
IMAGE_FOLDER = "`{folder}/` can't be part of an image name ({why})."
IMAGE_WORDS = "`{name}` would give an image name of more than {max} words."
META_NAME = "`{name}` can't be a meta file name ({why})."
META_OFFER = "`{name}` can't be a meta file name ({why}). Use `{offer}`?"
SHOW_LINE = "In the script: show {name}"
NEW_GAME_PARENT = "`{name}` can't be created there: its parent folder is missing or a link."
NEW_GAME_NOT_FOLDER = "`{name}` is a link or not a folder. Pick an empty or new folder."
NEW_GAME_NOT_EMPTY = "`{name}` isn't empty. Pick an empty or new folder."
NEW_GAME_FAILED = "Couldn't create the game in `{name}`: {reason}"

_REASON_LOCKED = "the file is read-only or locked."
_REASON_SYSTEM = "the system reported an error."

# How each name-rule reason reads in a dialog.
_WHY = {
    HYPHEN: "a hyphen",
    SPACE: "spaces",
    DOT: "an extra dot",
    CHARACTERS: "characters a name can't use",
    STATEMENT_WORD: "a statement word",
    STAGE_WORD: "a word show uses",
    TOO_MANY_WORDS: f"more than {IMAGE_NAME_MAX_WORDS} words",
}

# Format names for "Images takes PNG, JPEG, or WebP files." Unknown suffixes show upper-cased.
_KIND_NAMES = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WebP",
               ".ogg": "Ogg", ".opus": "Opus", ".flac": "FLAC", ".mp3": "MP3", ".wav": "WAV",
               ".ttf": "TTF", ".otf": "OTF", ".vns": ".vns", ".py": ".py", ".chr": ".chr",
               ".txt": ".txt"}
# F31: why a name in files/ isn't a meta file name (``metafiles.name_problem``'s forms).
_META_WHY = {"slash": "it must be a name in the files folder",
             "capitals": "use lowercase letters",
             "ending": "it must end in .chr or .txt",
             "reserved": "Windows keeps that name for itself",
             "long": "the part before .chr or .txt can be at most 32 characters",
             "chars": "use lowercase letters, digits, - or _"}

_LOCK_ERRNOS = (errno.EACCES, errno.EPERM, errno.EROFS)
_LINK_FALLBACK_ERRNOS = frozenset(
    code for code in (errno.EPERM, errno.EXDEV, getattr(errno, "ENOTSUP", None),
                      getattr(errno, "EOPNOTSUPP", None)) if code is not None)
_REPLACE_TRIES = 1                   # a locked file is reported at once, as F44's save does


def _umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


# 07 I-7: a new file gets the mode a plain ``open`` would give it. Read once, at import, on
# the main thread (``os.umask`` is process-wide).
NEW_FILE_MODE = 0o666 & ~_umask() if os.name == "posix" else None


@dataclass(frozen=True, slots=True)
class Refusal:
    """An operation that didn't happen; ``text`` is the whole line Studio shows."""
    text: str


# --- Small helpers --------------------------------------------------------------------------

def group_of(ref: str) -> AssetGroup | None:
    """The group whose folder is ``ref``'s first segment (exact case), or None."""
    head = ref.split("/", 1)[0]
    for group in ASSET_GROUPS:
        if group.folder == head:
            return group
    return None


def group_by_key(key: str) -> AssetGroup:
    for group in ASSET_GROUPS:
        if group.key == key:
            return group
    raise KeyError(key)


def root_present(paths: GamePaths) -> bool:
    """The game folder still exists as a folder."""
    try:
        return stat.S_ISDIR(os.stat(paths.root).st_mode)
    except (OSError, ValueError):
        return False


def takes(group: AssetGroup, name: str) -> bool:
    """``name`` has one of the group's suffixes: exact ``.vns`` for scripts (the loader
    matches it case-exactly), lower-cased for the others."""
    if group.kind == "script":
        return name.endswith(".vns") and len(name) > 4
    if group.kind in ("image", "gui_image"):
        return image_suffix(name) is not None
    dot = name.rfind(".")
    return dot > 0 and name[dot:].lower() in group.suffixes


def takes_text(group: AssetGroup) -> str:
    """``PNG, JPEG, or WebP`` for a group's suffixes."""
    kinds: list[str] = []
    for suffix in group.suffixes:
        kind = _KIND_NAMES.get(suffix, suffix.upper())
        if kind not in kinds:
            kinds.append(kind)
    if len(kinds) == 1:
        return kinds[0]
    if len(kinds) == 2:
        return f"{kinds[0]} or {kinds[1]}"
    return ", ".join(kinds[:-1]) + ", or " + kinds[-1]


def _limit_text(size: int) -> str:
    mib = size / (1 << 20)
    return f"{mib:g} MB" if mib >= 1 else f"{size:,} bytes"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _sort_key(name: str) -> tuple[str, str]:
    return name.casefold(), name


def _is_own_path(path: Path) -> bool:
    """The real path of ``path`` is ``path`` itself (normcase): no link anywhere on it."""
    try:
        real = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    return os.path.normcase(str(real)) == os.path.normcase(str(path))


def _is_real_dir(path: Path) -> bool:
    """``lstat`` shows a folder that is not a link, junction or reparse point."""
    try:
        st = os.lstat(path)
    except (OSError, ValueError):
        return False
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        return False
    if getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT",
                                                       0x400):
        return False
    return not os.path.isjunction(path)


def _failure(verb: str, ref: str, exc: OSError) -> Refusal:
    if isinstance(exc, PermissionError) or exc.errno in _LOCK_ERRNOS:
        return Refusal(LOCKED.format(verb=verb, ref=show(ref)))
    if isinstance(exc, FileNotFoundError):
        return Refusal(GONE.format(verb=verb, ref=show(ref)))
    return Refusal(SYSTEM.format(verb=verb, ref=show(ref)))


def _temp_token() -> str:
    """The temp file's random part (a seam: tests patch it)."""
    return safefile.temp_token()


def _before_act() -> None:
    """Called after the last check and right before a rename acts (a seam: tests inject a
    racing writer here, TR-F45-05)."""


# --- (F) (C) (E) ----------------------------------------------------------------------------

def _folder(paths: GamePaths, folder_ref: str, *, create: bool) -> RealDir | Refusal:
    """(F): the real folder ``folder_ref``, created first when it is a missing group folder
    and ``create`` is set."""
    if not root_present(paths):
        return Refusal(GAME_GONE)
    paths.invalidate_listings()
    shown = show(folder_ref)
    try:
        found = paths.real_dir(folder_ref)
    except AssetRefError:
        return Refusal(NOT_A_FOLDER.format(folder=shown))
    top = "/" not in folder_ref and group_of(folder_ref) is not None
    if (create and top and isinstance(found, NotReal) and found.kind == "missing"
            and found.other_case is None):
        try:
            os.mkdir(paths.root / folder_ref)
        except FileExistsError:
            pass
        except OSError as exc:
            return _failure("create", folder_ref + "/", exc)
        paths.invalidate_listings()
        found = paths.real_dir(folder_ref)
    if isinstance(found, RealDir):
        return found
    if found.kind == "missing" and found.other_case is None:
        return Refusal(FOLDER_MISSING.format(folder=shown))
    return Refusal(NOT_A_FOLDER.format(folder=shown))


def _folder_names(paths: GamePaths, folder: RealDir) -> tuple[str, ...] | None:
    """Every entry of a real folder: files, folders, and the links and FIFOs ``list_real``
    leaves out (they still take the name)."""
    listing = paths.list_real(folder.ref)
    if listing is None:
        return None
    return (*listing.files, *listing.dirs, *listing.omitted)


def _clash(names: Sequence[str], name: str, *, skip: str | None = None) -> str | None:
    """(C): the listed name equal to ``name`` up to case, leaving out ``skip``."""
    key = name.casefold()
    for listed in names:
        if listed != skip and listed.casefold() == key:
            return listed
    return None


def _existing(folder: RealDir, name: str, ref: str, verb: str) -> Path | Refusal:
    """(E): ``folder/name`` is a regular file whose real path is its listed path."""
    path = folder.path / name
    try:
        st = os.lstat(path)
    except OSError as exc:
        return _failure(verb, ref, exc)
    if not safefile.is_regular(st) or not _is_own_path(path):
        return Refusal(NOT_OWN_FILE.format(ref=show(ref)))
    return path


# --- Tree (§7.4, PR-F45-01) -----------------------------------------------------------------

NodeKind = Literal["group", "folder", "file", "config"]


@dataclass(eq=False)
class TreeNode:
    """One row of the project panel. ``ref`` is its game ref (a group's is its folder);
    ``count`` is the number of files below a group or folder."""
    ref: str
    name: str
    kind: NodeKind
    group: str = ""                              # AssetGroup.key; "" for config.toml
    children: list["TreeNode"] = field(default_factory=list)
    count: int = 0
    image_name: str | None = None                # images/ files that give a name
    name_problem: NameProblem | None = None      # images/ files that give none

    @property
    def is_file(self) -> bool:
        return self.kind in ("file", "config")


@dataclass(eq=False)
class ProjectTree:
    groups: tuple[TreeNode, ...]
    config: TreeNode
    truncated: bool = False                      # a group stopped at TREE_MAX_ENTRIES

    def nodes(self) -> list[TreeNode]:
        """Every node, depth first in display order."""
        found: list[TreeNode] = []
        stack = [self.config, *reversed(self.groups)]
        while stack:
            node = stack.pop()
            found.append(node)
            stack.extend(reversed(node.children))
        return found

    def find(self, ref: str) -> TreeNode | None:
        for node in self.nodes():
            if node.ref == ref:
                return node
        return None

    def file_refs(self, key: str) -> list[str]:
        """The file refs of group ``key`` in display order."""
        for group in self.groups:
            if group.group == key:
                return [node.ref for node in _walk(group) if node.kind == "file"]
        return []


def _walk(node: TreeNode) -> list[TreeNode]:
    found: list[TreeNode] = []
    stack = [node]
    while stack:
        current = stack.pop()
        found.append(current)
        stack.extend(reversed(current.children))
    return found


def project_tree(paths: GamePaths) -> ProjectTree | Refusal:
    """The panel's groups in ``ASSET_GROUPS`` order, then ``config.toml``. Each lists what
    the engine reads: ``list_dir`` entries (contained links included, O-3) with one of the
    group's suffixes, breadth first, at most ``TREE_MAX_ENTRIES`` files and folders per
    group and ``TREE_MAX_DEPTH`` folders deep. Files come before subfolders; ``main.vns``
    leads the Script group (F44's order). A missing or escaping group is empty."""
    if not root_present(paths):
        return Refusal(GAME_GONE)
    groups = []
    truncated = False
    for group in ASSET_GROUPS:
        node, cut = _group_node(paths, group)
        groups.append(node)
        truncated = truncated or cut
    config = TreeNode(CONFIG_REF, CONFIG_REF, "config")
    return ProjectTree(tuple(groups), config, truncated)


def _group_node(paths: GamePaths, group: AssetGroup) -> tuple[TreeNode, bool]:
    top = TreeNode(group.folder, group.title, "group", group.key)
    queue: list[tuple[TreeNode, int]] = [(top, 0)]
    folders: list[TreeNode] = [top]
    files_seen = folders_seen = 0
    truncated = False
    for parent, depth in queue:                   # grows while read: breadth first
        try:
            listing = paths.list_dir(parent.ref)
        except AssetRefError:
            listing = None
        if listing is None:
            continue
        names = sorted((n for n in listing.files if takes(group, n)), key=_sort_key)
        if parent.ref == SCRIPT_FOLDER and "main.vns" in names:
            names.remove("main.vns")
            names.insert(0, "main.vns")
        for name in names:
            if files_seen >= TREE_MAX_ENTRIES:
                truncated = True
                break
            files_seen += 1
            ref = f"{parent.ref}/{name}"
            leaf = TreeNode(ref, name, "file", group.key)
            if group.kind == "image":
                leaf.image_name, leaf.name_problem = name_of(ref)
            parent.children.append(leaf)
        if depth >= TREE_MAX_DEPTH:
            continue
        for name in sorted(listing.dirs, key=_sort_key):
            if folders_seen >= TREE_MAX_ENTRIES:
                truncated = True
                break
            folders_seen += 1
            folder = TreeNode(f"{parent.ref}/{name}", name, "folder", group.key)
            parent.children.append(folder)
            folders.append(folder)
            queue.append((folder, depth + 1))
    for folder in reversed(folders):              # children before parents
        folder.count = sum(1 if child.kind == "file" else child.count
                           for child in folder.children)
    return top, truncated


def reveal_target(paths: GamePaths, ref: str) -> tuple[Path, bool] | Refusal:
    """What the system's file manager shows for the project row ``ref``: ``(path, True)``
    selects a file in its folder; ``(path, False)`` opens a folder. A row that isn't on the
    disk (a group whose folder doesn't exist yet) opens its nearest folder that is, at
    worst the game folder. Only contained paths (``resolve``) are ever named."""
    if not root_present(paths):
        return Refusal(GAME_GONE)
    current = ref
    while current:
        try:
            path = paths.resolve(current)
        except (AssetMissing, AssetRefError):
            current = current.rpartition("/")[0]
            continue
        if path.is_dir():
            return path, False
        if path.is_file():
            return path, True
        current = current.rpartition("/")[0]
    return paths.root, False


# --- Add (§7.5 Add, PR-F45-02) --------------------------------------------------------------

AddChoice = Literal["new", "keep_both", "replace", "skip"]


@dataclass(frozen=True)
class AddPlan:
    """One picked file, planned for ``folder_ref``. ``label`` is the source's file name, the
    only part of its path ever shown. ``ok`` once there is no refusal and no name problem;
    ``clash`` (the listed name it collides with) then asks Keep both / Replace / Skip."""
    source: Path
    label: str
    group: AssetGroup
    folder_ref: str
    name: str
    real: Path | None = None
    size: int = 0
    refusal: str | None = None
    problem: str | None = None                   # image-name problem, with ``offer``
    offer: str | None = None
    clash: str | None = None
    clash_stamp: safefile.Stamp | None = None
    note: str | None = None                      # the minigame trust line
    folder_path: Path | None = None              # the real folder at plan time, if any

    @property
    def ref(self) -> str:
        return f"{self.folder_ref}/{self.name}"

    @property
    def ok(self) -> bool:
        return self.refusal is None and self.problem is None

    @property
    def image_name(self) -> str | None:
        if self.group.kind != "image":
            return None
        try:
            check_ref(self.ref)
        except AssetRefError:
            return None
        return name_of(self.ref)[0]

    @property
    def show_line(self) -> str | None:
        """``In the script: show hana smile`` for a name under ``images/``."""
        name = self.image_name
        return SHOW_LINE.format(name=name) if name is not None else None


@dataclass(frozen=True)
class AddOutcome:
    """``ref`` when the file was written; ``reason`` (one summary line) when it wasn't;
    neither for a file the author skipped."""
    label: str
    ref: str | None = None
    reason: str | None = None
    code: bool = False                           # a minigame .py was added


def plan_add(paths: GamePaths, group: AssetGroup | str, folder_ref: str,
             sources: Sequence[Path | str]) -> list[AddPlan]:
    """Plan copying ``sources`` into ``folder_ref`` (the group folder or a subfolder of it).
    Reads no file content: each source is resolved (a link to a file counts as that file)
    and must ``stat`` as a regular file within the group's cap, with a suffix the group
    takes and a name that passes (N). A bad image name gets ``word_problem``'s fix,
    lower-cased, as the offer. (C) records the clashing entry and its stamp."""
    if isinstance(group, str):
        group = group_by_key(group)
    if folder_ref != group.folder and not folder_ref.startswith(group.folder + "/"):
        raise ValueError(f"{folder_ref!r} is not in group {group.key!r}")
    folder_problem: str | None = None
    names: tuple[str, ...] = ()
    folder_path: Path | None = None
    if not root_present(paths):
        folder_problem = GAME_GONE
    else:
        paths.invalidate_listings()
        try:
            found = paths.real_dir(folder_ref)
        except AssetRefError:
            found = NotReal("link")
        if isinstance(found, RealDir):
            names = _folder_names(paths, found) or ()
            folder_path = found.path
        elif not (found.kind == "missing" and found.other_case is None
                  and folder_ref == group.folder):
            refusal = _folder(paths, folder_ref, create=False)
            folder_problem = refusal.text if isinstance(refusal, Refusal) else None
    plans = []
    for source in sources:
        source = Path(source)
        plan = AddPlan(source, source.name, group, folder_ref, source.name,
                       note=TRUST if group.kind == "code" else None, folder_path=folder_path)
        if folder_problem is not None:
            plans.append(replace(plan, refusal=folder_problem))
            continue
        plans.append(_plan_source(plan, names))
    return plans


def _plan_source(plan: AddPlan, names: Sequence[str]) -> AddPlan:
    label = show(plan.label)
    try:
        real = plan.source.resolve(strict=True)
        st = os.stat(real)
    except (OSError, RuntimeError, ValueError):
        return replace(plan, refusal=CANT_READ.format(name=label))
    if not stat.S_ISREG(st.st_mode):
        return replace(plan, refusal=NOT_REGULAR.format(name=label))
    group = plan.group
    if st.st_size > group.max_bytes:
        return replace(plan, refusal=TOO_LARGE.format(
            name=label, title=group.title, limit=_limit_text(group.max_bytes)))
    plan = replace(plan, real=real, size=st.st_size)
    return _plan_name(plan, plan.label, names, offer=True)


def _plan_name(plan: AddPlan, name: str, names: Sequence[str], *, offer: bool) -> AddPlan:
    """(N) and (C) for ``name``. With ``offer``, a fixable image-name problem becomes a
    question with the engine's fix; otherwise the problem stays (the author edits again)."""
    plan = replace(plan, name=name, refusal=None, problem=None, offer=None, clash=None,
                   clash_stamp=None)
    group = plan.group
    if "/" in name or "\\" in name or not name:
        return replace(plan, refusal=SAME_FOLDER.format(name=show(name)))
    if not takes(group, name):
        return replace(plan, refusal=TAKES.format(name=show(name), title=group.title,
                                                  kinds=takes_text(group)))
    try:
        check_ref(plan.ref)
    except AssetRefError as exc:
        return replace(plan, refusal=BAD_REF.format(name=show(name), reason=exc.reason))
    if group.kind == "image":
        problem = _image_problem(plan.ref, name)
        if problem is not None:
            text, fix = problem
            if fix is None:
                return replace(plan, refusal=text)
            question = IMAGE_OFFER.format(name=show(name), why=text, offer=show(fix))
            if not offer:
                question = IMAGE_NAME.format(name=show(name), why=text)
            return replace(plan, problem=question, offer=fix)
    if group.kind == "meta":
        problem = meta_problem(name)
        if problem is not None:
            why, fix = problem
            if fix is None or not offer:
                return replace(plan, refusal=META_NAME.format(name=show(name), why=why))
            return replace(plan, problem=META_OFFER.format(name=show(name), why=why,
                                                            offer=show(fix)), offer=fix)
    clash = _clash(names, name)
    if clash is not None:
        plan = replace(plan, clash=clash, clash_stamp=_stamp_of(plan, clash))
    return plan


def _stamp_of(plan: AddPlan, listed: str) -> safefile.Stamp | None:
    """The clashing entry's ``lstat`` stamp at plan time (Replace checks it again)."""
    if plan.folder_path is None:
        return None
    try:
        return safefile.current_stamp(plan.folder_path / listed)
    except OSError:
        return None


def meta_problem(name: str) -> tuple[str, str | None] | None:
    """F31 (the ``meta`` validator): (why, a fix or None) for a ``files/`` name that the game
    can't copy, or None when ``is_meta_name`` takes it. The fix is the name lower-cased, when
    that passes."""
    if is_meta_name(name):
        return None
    form = name_problem(name) or "chars"
    fix = name.lower()
    return _META_WHY.get(form, _META_WHY["chars"]), fix if is_meta_name(fix) else None


def _image_problem(ref: str, name: str) -> tuple[str, str | None] | None:
    """(why or the whole refusal, offered name) for a name under ``images/`` that gives no
    image name, or None. A fixable problem in the file's own word gives the fix lower-cased
    (and only if that fix passes in turn); a folder word or too many words can't be fixed
    here."""
    _, problem = name_of(ref)
    if problem is None:
        return None
    why = _WHY.get(problem.reason, problem.reason)
    if problem.reason == TOO_MANY_WORDS:
        return IMAGE_WORDS.format(name=show(name), max=IMAGE_NAME_MAX_WORDS), None
    if problem.folder:
        folder = ref.rsplit("/", 1)[0]
        return IMAGE_FOLDER.format(folder=show(folder), why=why), None
    fix = problem.rename.lower() if problem.rename is not None else None
    if fix is not None:
        fixed_ref = ref.rsplit("/", 1)[0] + "/" + fix
        try:
            check_ref(fixed_ref)
        except AssetRefError:
            fix = None
        else:
            if name_of(fixed_ref)[1] is not None:
                fix = None
    if fix is None:
        return IMAGE_NAME.format(name=show(name), why=why), None
    return why, fix


def rename_plan(paths: GamePaths, plan: AddPlan, name: str) -> AddPlan:
    """``plan`` with the name the author typed: (N) and (C) again, no new offer."""
    names: tuple[str, ...] = ()
    folder_path: Path | None = None
    if root_present(paths):
        paths.invalidate_listings()
        try:
            found = paths.real_dir(plan.folder_ref)
        except AssetRefError:
            found = None
        if isinstance(found, RealDir):
            names = _folder_names(paths, found) or ()
            folder_path = found.path
    return _plan_name(replace(plan, folder_path=folder_path), name, names, offer=False)


def run_add(paths: GamePaths, plan: AddPlan, choice: AddChoice) -> AddOutcome:
    """Copy one planned file (§7.5 Add, run steps 1–3). ``choice``: ``new`` (no clash was
    found), ``keep_both`` (``stem_2``, ``stem_3``, … until (C) passes), ``replace`` (write
    into the clashing entry's listed name, only if it is still the file that was planned:
    ``TargetChanged`` skips it), or ``skip``. Never raises for I/O."""
    if choice == "skip":
        return AddOutcome(plan.label)
    if plan.refusal is not None:
        return AddOutcome(plan.label, reason=plan.refusal)
    if plan.problem is not None or plan.real is None:
        return AddOutcome(plan.label, reason=plan.problem or CANT_READ.format(
            name=show(plan.label)))
    label = show(plan.label)
    group = plan.group
    read = safefile.read_regular(plan.real, group.max_bytes)
    if read.kind is safefile.ReadKind.NOT_REGULAR:
        return AddOutcome(plan.label, reason=NOT_REGULAR.format(name=label))
    if read.kind is safefile.ReadKind.TOO_LARGE:
        return AddOutcome(plan.label, reason=TOO_LARGE.format(
            name=label, title=group.title, limit=_limit_text(group.max_bytes)))
    if not read.ok or read.data is None:
        return AddOutcome(plan.label, reason=CANT_READ.format(name=label))
    data = read.data
    problem = content_problem(group, plan.label, plan.ref, data)
    if problem is not None:
        return AddOutcome(plan.label, reason=problem)
    folder = _folder(paths, plan.folder_ref, create=True)
    if isinstance(folder, Refusal):
        return AddOutcome(plan.label, reason=folder.text)
    names = _folder_names(paths, folder)
    if names is None:
        return AddOutcome(plan.label, reason=NOT_A_FOLDER.format(folder=show(plan.folder_ref)))
    expected: safefile.Stamp | None = None
    mode = NEW_FILE_MODE
    verb = "add"
    if choice == "replace":
        if plan.clash is None:
            return AddOutcome(plan.label, reason=CANT_READ.format(name=label))
        name = plan.clash
        ref = f"{plan.folder_ref}/{name}"
        target = _existing(folder, name, ref, "replace")
        if isinstance(target, Refusal):
            return AddOutcome(plan.label, reason=target.text)
        try:
            st = os.lstat(target)
        except OSError as exc:
            return AddOutcome(plan.label, reason=_failure("replace", ref, exc).text)
        expected = plan.clash_stamp if plan.clash_stamp is not None else \
            safefile.Stamp.of(st)
        mode = stat.S_IMODE(st.st_mode)
        verb = "replace"
    elif choice == "keep_both":
        found = _free_name(plan, names)
        if found is None:
            return AddOutcome(plan.label, reason=EXISTS.format(ref=show(plan.ref)))
        name = found
    else:
        name = plan.name
        if _clash(names, name) is not None:
            return AddOutcome(plan.label, reason=EXISTS.format(ref=show(plan.ref)))
    ref = f"{plan.folder_ref}/{name}"
    try:
        safefile.write_atomic(folder.path / name, (data,), check=True, expected=expected,
                              mode=mode, replace_tries=_REPLACE_TRIES, token=_temp_token)
    except safefile.TargetChanged:
        text = CHANGED if choice == "replace" else EXISTS
        return AddOutcome(plan.label, reason=text.format(ref=show(ref)))
    except OSError as exc:
        return AddOutcome(plan.label, reason=_failure(verb, ref, exc).text)
    return AddOutcome(plan.label, ref=ref, code=group.kind == "code")


def _free_name(plan: AddPlan, names: Sequence[str]) -> str | None:
    """Keep both: ``stem_2.ext``, ``stem_3.ext``, … that clashes with nothing and passes (N)."""
    dot = plan.name.rfind(".")
    stem, suffix = plan.name[:dot], plan.name[dot:]
    for number in range(2, KEEP_BOTH_MAX + 2):
        name = f"{stem}_{number}{suffix}"
        if _clash(names, name) is not None:
            continue
        try:
            check_ref(f"{plan.folder_ref}/{name}")
        except AssetRefError:
            return None
        return name
    return None


def content_problem(group: AssetGroup, label: str, ref: str, data: bytes) -> str | None:
    """Run step 2: the group's content check on the bytes read, keyed by ``group.kind``."""
    shown = show(label)
    kind = group.kind
    if kind in ("image", "gui_image"):
        found = image_dimensions(data)
        if found is None:
            return f"`{shown}` isn't a {takes_text(group)} image the engine can read."
        _, width, height = found
        if width > IMAGE_MAX_SIDE or height > IMAGE_MAX_SIDE:
            return (f"`{shown}` is {width:,}×{height:,} pixels; images can be at most "
                    f"{IMAGE_MAX_SIDE:,} pixels wide and high.")
        if width * height > IMAGE_MAX_PIXELS:
            return (f"`{shown}` has {width * height:,} pixels; images can have at most "
                    f"{IMAGE_MAX_PIXELS:,}.")
    elif kind == "audio":
        suffix = label[label.rfind("."):].lower()
        if refused_signature(data):
            return f"`{shown}` is a MIDI or tracker file, which the engine doesn't play."
        if not matches(data, suffix):
            name = FORMAT_NAMES.get(suffix, suffix.upper())
            return f"`{shown}` isn't really a{'n' if name[:1] in 'AEIOU' else ''} {name} file."
    elif kind == "script":
        decoded = decode_script(ref, data)
        if decoded.problem is not None:
            code, args, _line = decoded.problem
            return f"`{shown}`: {format_message(code, args)}"
    elif kind == "code":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return f"`{shown}` isn't saved as UTF-8 text."
    return None


def add_summary(outcomes: Sequence[AddOutcome]) -> str:
    """Design §6.3: ``Added 3 files.``, then ``1 file wasn't added:`` and a line each."""
    added = [o for o in outcomes if o.ref is not None]
    failed = [o for o in outcomes if o.reason is not None]
    lines = [f"Added {_plural(len(added), 'file')}." if added else "No files were added."]
    if failed:
        lines.append(f"1 file wasn't added:" if len(failed) == 1
                     else f"{len(failed)} files weren't added:")
        lines += [o.reason for o in failed if o.reason is not None]
    if any(o.code for o in added):
        lines.append(TRUST)
    return "\n".join(lines)


# --- New script file (§7.5 New script, PR-F45-04, C-2) -------------------------------------

def new_script(paths: GamePaths, folder_ref: str, name: str,
               text: str | None = None) -> str | Refusal:
    """Create ``folder_ref/name`` (under ``script/``) holding ``label <stem>:``, or ``text``
    when given (F47: the Database's ``database.vns``, whose stem needn't be a label name).
    Refuses a name that isn't a ``.vns`` file name, fails ``check_ref``, clashes up to case,
    or (without ``text``) whose stem isn't a label name."""
    if folder_ref != SCRIPT_FOLDER and not folder_ref.startswith(SCRIPT_FOLDER + "/"):
        raise ValueError(f"{folder_ref!r} is not under script/")
    group = group_by_key("script")
    if "/" in name or "\\" in name or not name:
        return Refusal(SAME_FOLDER.format(name=show(name)))
    if not takes(group, name):
        return Refusal(TAKES.format(name=show(name), title=group.title,
                                    kinds=takes_text(group)))
    ref = f"{folder_ref}/{name}"
    try:
        check_ref(ref)
    except AssetRefError as exc:
        return Refusal(BAD_REF.format(name=show(name), reason=exc.reason))
    stem = name[:-len(".vns")]
    problem = label_problem(stem) if text is None else None
    if problem is not None:
        return Refusal(problem)
    folder = _folder(paths, folder_ref, create=True)
    if isinstance(folder, Refusal):
        return folder
    names = _folder_names(paths, folder)
    if names is None or _clash(names, name) is not None:
        return Refusal(EXISTS.format(ref=show(ref)))
    try:
        body = f"label {stem}:\n" if text is None else text
        safefile.write_atomic(folder.path / name, (body.encode("utf-8"),),
                              check=True, expected=None, mode=NEW_FILE_MODE,
                              replace_tries=_REPLACE_TRIES, token=_temp_token)
    except safefile.TargetChanged:
        return Refusal(EXISTS.format(ref=show(ref)))
    except OSError as exc:
        return _failure("create", ref, exc)
    return ref


def ensure_folder(paths: GamePaths, folder_ref: str) -> Refusal | None:
    """Make ``folder_ref`` (a group folder, or one folder inside one: ``images/rin``) when it
    is missing, the group folder first (F47 PR-F47-11: the Database adds looks to
    ``images/<tag>/`` and sounds to ``audio/<folder>/``). None once the folder is there."""
    head, _, rest = folder_ref.partition("/")
    if group_of(head) is None or "/" in rest or "\\" in rest:
        raise ValueError(f"{folder_ref!r} is not a group folder or one folder inside one")
    top = _folder(paths, head, create=True)
    if isinstance(top, Refusal):
        return top
    if not rest:
        return None
    shown = show(folder_ref)
    try:
        check_ref(folder_ref)
        found = paths.real_dir(folder_ref)
    except AssetRefError:
        return Refusal(NOT_A_FOLDER.format(folder=shown))
    if isinstance(found, RealDir):
        return None
    if found.kind != "missing" or found.other_case is not None:
        return Refusal(NOT_A_FOLDER.format(folder=shown))
    try:
        os.mkdir(top.path / rest)
    except FileExistsError:
        pass
    except OSError as exc:
        return _failure("create", folder_ref + "/", exc)
    paths.invalidate_listings()
    return None


def label_problem(stem: str) -> str | None:
    """C-2: why a new script's stem can't be its label's name, with a fix when there is one."""
    if check_name(stem, ROLE_LABEL) is None:
        return None
    fix = "".join(c if is_word_char(c) else "_" for c in stem)
    if fix and fix[0].isdigit():
        fix = "ch_" + fix
    if check_name(fix, ROLE_LABEL) is not None:
        fix = "my_" + fix.lstrip("_")
    if fix != stem and check_name(fix, ROLE_LABEL) is None:
        return LABEL_FIX.format(stem=show(stem), fix=show(fix))
    return LABEL_NAME.format(stem=show(stem))


def include_line(ref: str) -> str:
    """``include "routes/kai.vns"`` for ``script/routes/kai.vns``."""
    return f'include "{ref[len(SCRIPT_FOLDER) + 1:]}"'


def include_position(text: str) -> int:
    """The 1-based line the new ``include`` goes on: after the last top-level ``include``
    line, or line 1 when there is none (§7.5 New script step 3)."""
    last = 0
    for number, line in enumerate(text.split("\n"), start=1):
        if line.startswith("include") and line[7:8] in (" ", "\t", '"'):
            last = number
    return last + 1


# --- Rename and delete (§7.5, PR-F45-05, TR-F45-05) ----------------------------------------

def fixed_reason(ref: str) -> str | None:
    """Why ``ref`` can't be renamed or deleted at all, or None."""
    if ref == MAIN_REF:
        return MAIN_FIXED
    if ref == CONFIG_REF:
        return CONFIG_FIXED
    return None


def rename_file(paths: GamePaths, ref: str, new_name: str) -> str | Refusal:
    """Rename the file ``ref`` to ``new_name`` in the same folder and return the new ref.
    Never replaces anything: (N), then (C) leaving out the file itself, then (E) on the
    source; POSIX links the new name (which fails on any existing entry) and unlinks the old
    one, Windows renames (which never replaces). A rename that only changes case uses
    ``os.rename``. The race between the check and the act is accepted (ADR-0008)."""
    fixed = fixed_reason(ref)
    if fixed is not None:
        return Refusal(fixed)
    group = group_of(ref)
    if group is None or "/" not in ref:
        return Refusal(FOLDER_FIXED)
    folder_ref, old_name = ref.rsplit("/", 1)
    if "/" in new_name or "\\" in new_name or not new_name:
        return Refusal(SAME_FOLDER.format(name=show(new_name)))
    if not takes(group, new_name):
        return Refusal(TAKES.format(name=show(new_name), title=group.title,
                                    kinds=takes_text(group)))
    new_ref = f"{folder_ref}/{new_name}"
    try:
        check_ref(new_ref)
    except AssetRefError as exc:
        return Refusal(BAD_REF.format(name=show(new_name), reason=exc.reason))
    if group.kind == "image":
        problem = _image_problem(new_ref, new_name)
        if problem is not None:
            text, fix = problem
            return Refusal(text if fix is None else IMAGE_NAME.format(name=show(new_name),
                                                                       why=text))
    if group.kind == "meta" and (meta := meta_problem(new_name)) is not None:
        return Refusal(META_NAME.format(name=show(new_name), why=meta[0]))
    if new_name == old_name:
        return new_ref
    folder = _folder(paths, folder_ref, create=False)
    if isinstance(folder, Refusal):
        return folder
    names = _folder_names(paths, folder)
    if names is None:
        return Refusal(NOT_A_FOLDER.format(folder=show(folder_ref)))
    if old_name not in names:
        return Refusal(GONE.format(verb="rename", ref=show(ref)))
    if _clash(names, new_name, skip=old_name) is not None:
        return Refusal(EXISTS.format(ref=show(new_ref)))
    source = _existing(folder, old_name, ref, "rename")
    if isinstance(source, Refusal):
        return source
    target = folder.path / new_name
    _before_act()
    try:
        _rename(source, target, case_only=old_name.casefold() == new_name.casefold(),
                recheck=lambda: _recheck_clash(paths, folder, new_name, old_name))
    except FileExistsError:
        return Refusal(EXISTS.format(ref=show(new_ref)))
    except OSError as exc:
        return _failure("rename", ref, exc)
    paths.invalidate_listings()
    return new_ref


def _recheck_clash(paths: GamePaths, folder: RealDir, new_name: str, old_name: str) -> bool:
    paths.invalidate_listings()
    names = _folder_names(paths, folder)
    return names is None or _clash(names, new_name, skip=old_name) is not None


def _rename(source: Path, target: Path, *, case_only: bool,
            recheck: Callable[[], bool]) -> None:
    """The act. Raises ``FileExistsError`` when the new name is taken."""
    if case_only or os.name == "nt":
        os.rename(source, target)               # Windows: never replaces an existing entry
        return
    try:
        os.link(source, target)                 # the source passed (E): a regular file
    except FileExistsError:
        raise
    except OSError as exc:
        if exc.errno not in _LINK_FALLBACK_ERRNOS:
            raise
        if recheck():                           # no hard links here: check (C) again
            raise FileExistsError(errno.EEXIST, "the new name is taken") from None
        os.rename(source, target)               # the accepted race (ADR-0008)
        return
    try:
        os.unlink(source)
    except OSError:
        try:
            os.unlink(target)                   # undo the link: the old name stays
        except OSError:
            pass
        raise


def image_name_of(ref: str) -> str | None:
    """The image name an ``images/…`` ref gives, or None (not an image, or a bad name)."""
    if not ref.startswith("images/") or image_suffix(ref.rsplit("/", 1)[-1]) is None:
        return None
    try:
        check_ref(ref)
    except AssetRefError:
        return None
    return name_of(ref)[0]


def show_hint(folder_ref: str, name: str) -> str | None:
    """``In the script: show hana smile`` for ``name`` in an ``images/`` folder, else None."""
    found = image_name_of(f"{folder_ref}/{name}")
    return SHOW_LINE.format(name=found) if found is not None else None


def rename_message(ref: str, new_name: str, *, unsaved: bool = False) -> str:
    """The rename confirmation (design §6.3; G6 for unsaved edits)."""
    folder = ref.rsplit("/", 1)[0]
    text = f"Rename `{show(ref)}` to `{show(new_name)}`?"
    old_image, new_image = image_name_of(ref), image_name_of(f"{folder}/{new_name}")
    if old_image is not None and new_image is not None:
        text += (f" The script calls it `{show(new_image)}` after this. Lines that use "
                 f"`{show(old_image)}` aren't changed.")
    elif ref.startswith(SCRIPT_FOLDER + "/"):
        text += " `include` lines that name it aren't changed."
    else:
        text += f" Lines that use `{show(ref)}` aren't changed."
    if unsaved:
        text += (f"\n\n`{show(ref)}` has unsaved changes. They stay in the editor and are "
                 "saved under the new name.")
    return text


def delete_message(ref: str, *, unsaved: bool = False) -> str:
    """The delete confirmation (design §6.3; G6 for unsaved edits): Move to the Recycle
    Bin on Windows, else a removal that can't be undone."""
    if recycle.AVAILABLE:
        text = f"Move `{show(ref)}` to the Recycle Bin? You can restore it from there."
    else:
        text = (f"Delete `{show(ref)}`? It is removed from the disk, not moved to the "
                "trash. This can't be undone.")
    if unsaved:
        text += f"\n\n`{show(ref)}` has unsaved changes, which will be lost."
    return text


def clash_message(ref: str) -> str:
    """The Keep both / Replace / Skip question (design §6.3)."""
    return EXISTS.format(ref=show(ref))


def delete_file(paths: GamePaths, ref: str) -> None | Refusal:
    """Delete the file ``ref`` after (E): to the Recycle Bin on Windows
    (``recycle.to_recycle_bin``), else from the disk. Only ``REMOVED`` counts as success."""
    fixed = fixed_reason(ref)
    if fixed is not None:
        return Refusal(fixed)
    group = group_of(ref)
    if group is None or "/" not in ref:
        return Refusal(FOLDER_FIXED)
    folder_ref, name = ref.rsplit("/", 1)
    folder = _folder(paths, folder_ref, create=False)
    if isinstance(folder, Refusal):
        return folder
    names = _folder_names(paths, folder)
    if names is None or name not in names:
        return Refusal(GONE.format(verb="delete", ref=show(ref)))
    target = _existing(folder, name, ref, "delete")
    if isinstance(target, Refusal):
        return target
    result = recycle.to_recycle_bin(target)
    paths.invalidate_listings()
    if result is recycle.KEPT:
        return Refusal(KEPT.format(ref=show(ref)))
    if result is safefile.RemoveKind.REMOVED:
        return None
    if result is safefile.RemoveKind.MISSING:
        return Refusal(GONE.format(verb="delete", ref=show(ref)))
    if result is safefile.RemoveKind.NOT_FILE_OR_LINK:
        return Refusal(NOT_OWN_FILE.format(ref=show(ref)))
    # NO_PERMISSION, or FAILED on a file (E) just saw as regular: a lock or a read-only disk.
    return Refusal(LOCKED.format(verb="delete", ref=show(ref)))


# --- New game (§7.5 New game, PR-F45-06) ----------------------------------------------------

def starter_dir() -> Path:
    return engine_data_dir() / STARTER_DIR


def starter_config(folder_name: str) -> bytes:
    """``config.toml`` for a new game named after its folder: ``id = slugify(name)`` and the
    title as a TOML basic string."""
    template = (starter_dir() / "config.toml.in").read_text(encoding="utf-8")
    title = json.dumps(folder_name, ensure_ascii=False).replace("\x7f", "\\u007f")
    text = string.Template(template).substitute(id=slugify(folder_name), title=title)
    return text.encode("utf-8")


def sample_dir() -> Path:
    return engine_data_dir() / SAMPLE_DIR


def _fill_config(template_dir: Path, folder_name: str) -> bytes:
    """``template_dir``'s ``config.toml.in`` with ``$id`` and ``$title`` filled in, as
    ``starter_config`` does."""
    template = (template_dir / CONFIG_TEMPLATE).read_text(encoding="utf-8")
    title = json.dumps(folder_name, ensure_ascii=False).replace("\x7f", "\\u007f")
    text = string.Template(template).substitute(id=slugify(folder_name), title=title)
    return text.encode("utf-8")


def agent_notes() -> dict[str, bytes]:
    """``AGENTS.md`` (how an AI agent works with the game) and ``CLAUDE.md`` (which imports
    it, for Claude Code) from ``engine/data/agent-notes/``; every new game gets both, and a
    build leaves them out (2026-11-04)."""
    folder = engine_data_dir() / AGENT_NOTES_DIR
    return {name: (folder / name).read_bytes() for name in AGENT_NOTES}


def template_files(template: str, folder_name: str) -> dict[str, bytes]:
    """Every file a new game from ``template`` gets, game ref → bytes, read before anything
    is created. ``TEMPLATE_EMPTY`` is the F45 starter (``config.toml``, ``script/main.vns``);
    ``TEMPLATE_SAMPLE`` is every regular file under ``engine/data/sample/`` (dot files and
    ``__pycache__`` skipped), with ``config.toml.in`` filled in as ``config.toml``. Both get
    ``agent_notes``. Raises ``ValueError`` for an unknown template and ``OSError`` when a
    file can't be read."""
    if template == TEMPLATE_EMPTY:
        return {CONFIG_REF: starter_config(folder_name),
                MAIN_REF: (starter_dir() / "script" / "main.vns").read_bytes(),
                **agent_notes()}
    if template != TEMPLATE_SAMPLE:
        raise ValueError(f"unknown template {template!r}")
    root = sample_dir()
    found: dict[str, bytes] = {CONFIG_REF: _fill_config(root, folder_name)}
    total = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue
        if not path.is_file() or rel.as_posix() == CONFIG_TEMPLATE:
            continue
        data = path.read_bytes()
        total += len(data)
        if len(found) >= SAMPLE_MAX_FILES or total > SAMPLE_MAX_BYTES:
            raise OSError(errno.EFBIG, "the sample template is too large")
        found[rel.as_posix()] = data
    if MAIN_REF not in found:
        raise OSError(errno.ENOENT, "the sample template has no script/main.vns")
    return {**found, **agent_notes()}


def new_game(folder: Path | str, template: str = TEMPLATE_SAMPLE) -> Path | Refusal:
    """Create a game in ``folder``: a missing folder whose parent is a real folder, or an
    empty real folder. Creates the group folders and ``template``'s files
    (``template_files``), each exclusively, plus the folders those files sit in
    (ADR-0008 Amendment 1, item 3; F47 PR-F47-25). Then Studio's ``.studio/studio.json``
    is written with the Guide open (F47 PR-F47-26); that file is best effort and its
    failure doesn't fail the new game. Nothing else is written. ``template`` is
    ``TEMPLATE_SAMPLE`` (the default, "A short sample story") or ``TEMPLATE_EMPTY``."""
    from engine.tools.editor import studiostate   # pure; imported here to keep files.py's head lean

    folder = Path(folder).absolute()
    name = show(folder.name)
    try:
        os.lstat(folder)
        exists = True
    except FileNotFoundError:
        exists = False
    except (OSError, ValueError):
        return Refusal(NEW_GAME_NOT_FOLDER.format(name=name))
    if exists:
        if not _is_real_dir(folder) or not _is_own_path(folder):
            return Refusal(NEW_GAME_NOT_FOLDER.format(name=name))
        try:
            with os.scandir(folder) as entries:
                if next(entries, None) is not None:
                    return Refusal(NEW_GAME_NOT_EMPTY.format(name=name))
        except OSError:
            return Refusal(NEW_GAME_NOT_FOLDER.format(name=name))
    else:
        parent = folder.parent
        if not _is_real_dir(parent) or not _is_own_path(parent):
            return Refusal(NEW_GAME_PARENT.format(name=name))
    try:
        contents = template_files(template, folder.name)
        if not exists:
            os.mkdir(folder)
        made: set[str] = set()
        for group in ASSET_GROUPS:
            os.mkdir(folder / group.folder)
            made.add(group.folder)
        for ref, data in contents.items():
            parts = ref.split("/")[:-1]
            for depth in range(1, len(parts) + 1):
                sub = "/".join(parts[:depth])
                if sub not in made:
                    os.mkdir(folder / sub)
                    made.add(sub)
            safefile.write_atomic(folder / ref, (data,), check=True, expected=None,
                                  mode=NEW_FILE_MODE, token=_temp_token)
    except (OSError, safefile.TargetChanged) as exc:
        locked = isinstance(exc, OSError) and (isinstance(exc, PermissionError)
                                               or exc.errno in _LOCK_ERRNOS)
        return Refusal(NEW_GAME_FAILED.format(
            name=name, reason=_REASON_LOCKED if locked else _REASON_SYSTEM))
    studiostate.write_state(folder, studiostate.StudioState(
        guide_open=True, sample=template == TEMPLATE_SAMPLE))
    return folder


def studio_argv(folder: Path) -> list[str]:
    """The command that opens Studio on ``folder`` in a new process."""
    return engine_argv("edit", str(folder))


__all__ = ["AddOutcome", "AddPlan", "GAME_GONE", "MAIN_FIXED", "ProjectTree", "Refusal",
           "START_FROM", "TEMPLATES", "TEMPLATE_EMPTY", "TEMPLATE_SAMPLE", "TreeNode",
           "add_summary", "content_problem", "delete_file", "ensure_folder", "fixed_reason",
           "group_of", "include_line", "include_position", "label_problem", "new_game",
           "new_script", "plan_add", "project_tree", "rename_file", "rename_plan",
           "root_present", "run_add", "sample_dir", "starter_config", "studio_argv", "takes",
           "takes_text", "template_files"]

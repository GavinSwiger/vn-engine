"""Studio's check child: ``python -m engine check GAME --report-to-editor`` (F45
``04-technical.md`` §4.3, §5, §7.1, §7.3, §8; ``07`` I-1).

Why this module exists: Studio shows the engine's own problems, a name index, and a label
graph while the author types, but Studio's process runs no author code and has no pygame
(ADR-0008). So a child process does the real work: ``load_config``, ``load_story``, and
(unless ``--no-launch``) the launch phase (``LaunchJob``), with no window and no writes. It
reports in F44's framing (``core/editorreport.py``): ``problems``, ``names``, ``graph``, then
one ``done``, each event split into lines of at most 1 MiB and 5,000 items.

- **Isolation** (§7.1 step 1). Reports go to a duplicate of fd 1; fd 1 and ``sys.stdout``
  point at the null device, so an author's ``print`` can't forge or break a report line. No
  bytecode is written (``-B`` and ``sys.dont_write_bytecode``), and the engine's loggers get
  a ``NullHandler``: no log file, no console records.
- **Overlay** (``--stdin-overlay``, §4.3, §7.3). Unsaved text arrives on stdin: a header
  line, then exact bytes. ``read_overlay`` checks every limit before reading the body, and
  any problem exits 2 before anything is checked. ``OverlayPaths`` serves an overlaid file
  only where ``GamePaths`` would serve the file on disk: an overlay can't reach outside or
  raise a cap, and adds a file only when its header entry says ``"new": true`` (F48 04
  §7.3: at most 8 plain ``script/….vns`` names, re-checked by ``check_added`` before
  anything is checked; served from memory, never opened or written).
- **When author code runs** (``07`` I-1). ``--no-launch`` skips the launch phase, so no
  ``define``, ``default``, or ``module()`` code runs; Studio passes it until the author's
  first Preview, Save, or Check in that window. The names that need launch values
  (``character``, defined transitions) are then not sent.
- **Not checked here** (``07`` I-8): ``app``-only launch checks (F05/F17's text check, F18's
  W111, F23's plugin load). They show on Preview.

- **Lint** (F41 ``04`` §7.3). When the story loaded with no error at all, ``tools/lint.py``'s
  findings (W237–W242) go to Studio as names rows (``unreached``, ``unused_*``), never as
  problem items. ``CheckJob.collect`` returns a run's results; ``run`` sends them, and
  ``lint_command`` prints them with the findings for editors and CI.

``NAME_SOURCES`` is the table later features extend: one row per name kind a statement doc
lists (``07`` O-2). A row returns ``(name, file, line)`` entries, or None when it has no
inputs; a row that raises is skipped, and its kind isn't sent.

Imports ``core``, ``script``, ``runtime`` and ``tools.lint`` only (never pygame, ``app``,
``render``, ``ui``, ``audio``, ``persist``, ``meta``, or ``minigames``;
``tests/test_import_rules.py``).
"""

import ast
import json
import logging
import os
import re
import stat
import sys
import time
import tomllib
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import BinaryIO, Final

from engine.core.config import KeyLocator, load_config
from engine.core.config_schema import Config
from engine.core.constants import CONFIG_FILENAME, CONFIG_MAX_BYTES, META_ORIGINALS_DIR
from engine.core.editorreport import (
    CHECK_EVENT_MAX_ITEMS,
    CHECK_KIND_RE,
    CHECK_MAX_LINKS,
    CHECK_MAX_NAMES,
    CHECK_MAX_PROBLEMS,
    CHECK_MAX_REACH,
    OVERLAY_HEADER_MAX,
    OVERLAY_MAX_BYTES,
    OVERLAY_MAX_FILES,
    OVERLAY_MAX_NEW,
    OVERLAY_READ_CHUNK,
    REPORT_MARKER,
    REPORT_MAX_BYTES,
    REPORT_TEXT_MAX_CHARS,
    REPORT_VERSION,
)
from engine.core.errors import (
    AssetMissing,
    AssetNotFile,
    AssetRefError,
    AssetTooLarge,
    AssetUnreadable,
    ConfigError,
    UserFacingError,
)
from engine.core.logsetup import ROOT_LOGGER
from engine.core.paths import GamePaths, RealDir, check_ref, is_meta_name, is_plain_name
from engine.core.redact import echo
from engine.runtime.character import Character
from engine.runtime.gamesources import audio_files, game_has, image_source
from engine.runtime.images import ImageIndex, build_index
from engine.runtime.launch import LaunchJob, LaunchResult
from engine.runtime.limits import IMAGE_SCAN_MAX_DEPTH
from engine.runtime.transitions import TransitionDef
from engine.script import LoadOptions, load_story
from engine.script.audio import PLAYABLE_EXTS, PlayAudio, QueueMusic, StopAudio, Voice
from engine.script.choicecheck import ChoiceCheck
from engine.script.codex import CodexLock
from engine.script.effects import BUILTIN_TRANSITION_NAMES, WithClause
from engine.script.points import PointsChange
from engine.script.routes import Lock
from engine.script.labelgraph import label_links
from engine.script.assetgroups import MINIGAME_FILE_MAX_BYTES
from engine.script.limits import SCRIPT_FILE_MAX_BYTES
from engine.script.flowchart import Flowchart
from engine.script.flowgraph import FlowNode, FlowOptions
from engine.script.glitch import EFFECT_STATEMENT_KINDS, WORD_OFF
from engine.script.metafiles import MetaFile
from engine.script.minigame import Minigame
from engine.script.nodes import Chapter, Define, PyCode, Say, Statement
from engine.script.pluginsigs import PluginSig, dict_keys, plugin_sigs
from engine.script.program import Program
from engine.script.spriteframes import frame_of
from engine.script.stage import At, Scene, Show
from engine.script.texttags import NameMark, TaggedText, VarMark
from engine.script.ui import DELETE as UI_DELETE
from engine.script.ui import FORMS as UI_FORMS
from engine.script.ui import SAVES as UI_SAVES
from engine.script.ui import STYLE as UI_STYLE
from engine.script.ui import UiStatement
from engine.tools.lint import LINT_KINDS, Finding, findings, rows_by_kind  # F41 P3 (07 I-9)

SCRIPT_PREFIX = "script/"
SCRIPT_SUFFIX = ".vns"
AUDIO_PREFIX = "audio/"
AUDIO_WALK_MAX_DEPTH = IMAGE_SCAN_MAX_DEPTH     # audio/ is walked as deep as images/ is

# Exit codes (04 §5).
EXIT_DONE = 0
EXIT_BAD_INPUT = 2

_KIND = re.compile(CHECK_KIND_RE)
_CONFIG_WHERE = re.compile(r"config\.toml, line (\d+): ")

Emit = Callable[[dict], None]
NameRow = tuple[str, str | None, int | None]           # (name, file, line) on the wire


# --- Overlay (04 §4.3, §7.1 step 2, §7.3) ----------------------------------------------------

class OverlayError(ValueError):
    """The stdin overlay breaks a rule; the child exits 2 before checking anything."""


def _overlay_cap(ref: str) -> int:
    return CONFIG_MAX_BYTES if ref == CONFIG_FILENAME else SCRIPT_FILE_MAX_BYTES


def _overlay_ref_ok(ref: object) -> bool:
    if not isinstance(ref, str):
        return False
    try:
        check_ref(ref)
    except AssetRefError:
        return False
    return ref == CONFIG_FILENAME or (ref.startswith(SCRIPT_PREFIX)
                                      and ref.endswith(SCRIPT_SUFFIX))


class Overlay(dict):
    """``read_overlay``'s answer: ``{ref: bytes}`` in header order, plus ``added``, the refs
    whose entry says ``"new": true`` (F48 04 §7.3): files the overlay adds."""

    def __init__(self, files: Iterable[tuple[str, bytes]] = (),
                 added: Iterable[str] = ()) -> None:
        super().__init__(files)
        self.added: frozenset[str] = frozenset(added)


def read_overlay(stream: BinaryIO) -> Overlay:
    """The overlay on ``stream``: ``{ref: bytes}`` in header order (``Overlay.added``: the
    new files). Raises ``OverlayError``.

    The header line is read with a limit of ``OVERLAY_HEADER_MAX`` + 1 bytes and checked
    whole (``v`` 1, at most 64 files, each ref ``config.toml`` or ``script/….vns`` and
    unique, each size an int within its file's cap, the total within 64 MiB; ``"new"``, if
    present, is ``true``, on at most ``OVERLAY_MAX_NEW`` ``script/….vns`` refs that pass
    ``is_plain_name``) before any of the body is read. The body is read in 1 MiB chunks,
    exactly the declared bytes, and must end there (EOF): at most the declared bytes plus
    one chunk are ever read."""
    line = stream.readline(OVERLAY_HEADER_MAX + 1)
    if not line.endswith(b"\n"):
        raise OverlayError("the overlay header is too long or has no line end")
    try:
        header = json.loads(line.decode("ascii"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise OverlayError("the overlay header isn't ASCII JSON") from None
    if not isinstance(header, dict) or type(header.get("v")) is not int \
            or header["v"] != REPORT_VERSION:
        raise OverlayError("the overlay header has the wrong version")
    files = header.get("files")
    if not isinstance(files, list) or len(files) > OVERLAY_MAX_FILES:
        raise OverlayError(f"the overlay must list at most {OVERLAY_MAX_FILES} files")
    sizes: dict[str, int] = {}
    added: list[str] = []
    total = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise OverlayError("an overlay entry isn't an object")
        ref, size = entry.get("ref"), entry.get("size")
        if not _overlay_ref_ok(ref):
            raise OverlayError("an overlay ref isn't config.toml or a script/….vns file")
        if ref in sizes:
            raise OverlayError("an overlay ref is listed twice")
        if "new" in entry:
            if entry["new"] is not True:
                raise OverlayError('an overlay "new" flag isn\'t true')
            if ref == CONFIG_FILENAME or not is_plain_name(ref):
                raise OverlayError("a new overlay file isn't a plain script/….vns name")
            added.append(ref)
            if len(added) > OVERLAY_MAX_NEW:
                raise OverlayError(f"the overlay may add at most {OVERLAY_MAX_NEW} files")
        if type(size) is not int or not 0 <= size <= _overlay_cap(ref):
            raise OverlayError("an overlay size isn't a whole number within its file's cap")
        total += size
        if total > OVERLAY_MAX_BYTES:
            raise OverlayError("the overlay is larger than 64 MB")
        sizes[ref] = size
    body = bytearray()
    while len(body) < total:
        chunk = stream.read(min(OVERLAY_READ_CHUNK, total - len(body)))
        if not chunk:
            raise OverlayError("the overlay ended before its declared size")
        body += chunk
    if stream.read(1):
        raise OverlayError("the overlay goes on past its declared size")
    overlay = Overlay(added=added)
    at = 0
    for ref, size in sizes.items():
        overlay[ref] = bytes(body[at:at + size])
        at += size
    return overlay


@dataclass(frozen=True)
class OverlayPaths(GamePaths):
    """``GamePaths`` that serves ``overlay``'s bytes for its refs (04 §7.3).

    ``read_file`` resolves the ref first, with the same errors as on disk, so an overlaid
    ref must exist, be listed, contained, and in exact case, and be a regular file; the
    overlay's bytes then stand in for the file's, under the reader's ``max_bytes``. Listings
    and every other file come from disk. Nothing is ever written.

    ``added`` (F48 04 §7.3, SEC-F48-02): overlay refs for files that don't exist yet. Once
    ``check_added`` has passed, each resolves to ``<parent real folder>/<name>`` (never
    opened), ``read_file`` and ``file_size`` serve it from memory, and ``list_dir`` and
    ``walk_files`` list it in its folder. No disk access touches it. An added ref never
    stands in for an existing file: ``check_added`` refuses one that exists."""

    overlay: Mapping[str, bytes] = field(default_factory=dict, compare=False)
    added: frozenset[str] = field(default_factory=frozenset, compare=False)

    def check_added(self) -> None:
        """SEC-F48-02 again, in the child, before anything is checked: each added ref is an
        overlay ``script/….vns`` ref with a plain name, its parent is a real folder under
        ``script/`` (``real_dir``), no entry of that folder (``list_real``, links and FIFOs
        included) and no other added ref equals it up to case, and ``resolve`` finds
        nothing there (``AssetMissing``). Raises ``OverlayError``; no file is opened."""
        folded: set[str] = set()
        for ref in sorted(self.added):
            if ref not in self.overlay or ref == CONFIG_FILENAME or not _overlay_ref_ok(ref) \
                    or not is_plain_name(ref):
                raise OverlayError("a new overlay file isn't a plain script/….vns name")
            if ref.casefold() in folded:
                raise OverlayError("two new overlay files differ only in letter case")
            folded.add(ref.casefold())
            parent, _, name = ref.rpartition("/")
            listing = GamePaths.list_real(self, parent) if self._added_parent(ref) else None
            if listing is None:
                raise OverlayError("a new overlay file's folder isn't a real folder in script/")
            key = name.casefold()
            if any(listed.casefold() == key
                   for listed in (*listing.files, *listing.dirs, *listing.omitted)):
                raise OverlayError("a new overlay file's name is taken in its folder")
            try:
                GamePaths.resolve(self, ref)
            except AssetMissing:
                continue
            except AssetRefError:
                raise OverlayError("a new overlay file's ref leaves the game folder") from None
            raise OverlayError("a new overlay file already exists")

    def _added_parent(self, ref: str) -> Path | None:
        """The real folder an added ref goes in (``real_dir``), or None when there is none
        under ``script/``."""
        parent = ref.rpartition("/")[0]
        if parent != SCRIPT_PREFIX.rstrip("/") and not parent.startswith(SCRIPT_PREFIX):
            return None
        try:
            found = self.real_dir(parent)
        except AssetRefError:
            return None
        return found.path if isinstance(found, RealDir) else None

    def resolve(self, ref: str) -> Path:
        if ref in self.added:
            parent = self._added_parent(ref)
            if parent is None:
                raise AssetMissing(ref, None)
            return parent / ref.rpartition("/")[2]
        return super().resolve(ref)

    def file_size(self, ref: str) -> int:
        if ref in self.added:
            self.resolve(ref)
            return len(self.overlay[ref])
        return super().file_size(ref)

    def _contents(self, directory: Path):
        """``GamePaths``' contents of ``directory`` (``list_dir``, ``walk_files``) with the
        added files whose parent is that folder."""
        contents = super()._contents(directory)
        if contents is None or not self.added:
            return contents
        key = os.path.normcase(str(directory))
        names = []
        for ref in self.added:
            parent = self._added_parent(ref)
            if parent is not None and os.path.normcase(str(parent)) == key:
                names.append(ref.rpartition("/")[2])
        if not names:
            return contents
        files = tuple(sorted({*contents.listing.files, *names}))
        return replace(contents, listing=replace(contents.listing, files=files))

    def read_file(self, ref: str, *, max_bytes: int, regular: bool = False) -> bytes:
        if ref in self.added:
            self.resolve(ref)
            data = self.overlay[ref]
            if len(data) > max_bytes:
                raise AssetTooLarge(ref, max_bytes)
            return data
        data = self.overlay.get(ref)
        if data is None:
            return super().read_file(ref, max_bytes=max_bytes, regular=regular)
        listed, real = self._resolve_listed(ref)
        try:
            if regular:
                built = self.root.joinpath(*ref.split("/"))
                if not stat.S_ISREG(os.lstat(listed).st_mode) or \
                        os.path.normcase(str(real)) != os.path.normcase(str(built)):
                    raise AssetNotFile(ref)
            if not stat.S_ISREG(os.stat(real).st_mode):
                raise AssetNotFile(ref)
        except OSError:
            raise AssetUnreadable(ref) from None
        if len(data) > max_bytes:
            raise AssetTooLarge(ref, max_bytes)
        return data


# --- Report lines (04 §4.3, §7.1 step 10) ----------------------------------------------------

def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def encode_event(event: dict) -> bytes:
    """One report line, without its newline: the marker and the event as ASCII JSON."""
    return REPORT_MARKER + _dumps(event).encode("ascii")


def chunk_event(event: str, items: Iterable[object], *, key: str = "items",
                **fields: object) -> Iterator[dict]:
    """``{"v": 1, "event": event, **fields, key: [...]}`` dicts holding ``items`` in order,
    each encoding to at most ``REPORT_MAX_BYTES`` and holding at most
    ``CHECK_EVENT_MAX_ITEMS`` items. Each item is encoded once, to measure it. Nothing is
    yielded for no items."""
    head = {"v": REPORT_VERSION, "event": event, **fields}
    base = len(REPORT_MARKER) + len(_dumps({**head, key: []}))
    chunk: list[object] = []
    size = base
    for item in items:
        width = len(_dumps(item)) + (1 if chunk else 0)
        if chunk and (size + width > REPORT_MAX_BYTES or len(chunk) >= CHECK_EVENT_MAX_ITEMS):
            yield {**head, key: chunk}
            chunk, size, width = [], base, width - 1
        chunk.append(item)
        size += width
    if chunk:
        yield {**head, key: chunk}


def _text(value: str) -> str:
    """Every string on the wire: redacted, escaped, and capped (04 §4.3)."""
    return echo(value, REPORT_TEXT_MAX_CHARS)


def _position(value: object) -> int | None:
    return value if type(value) is int and value >= 1 else None


def problem_item(severity: str, code: str, source: str, text: str, file: str | None,
                 line: int | None, column: int | None) -> dict:
    """One problem in its wire shape (``CheckItem``'s fields)."""
    return {"severity": severity, "code": code, "source": source, "text": _text(text),
            "file": None if file is None else _text(file), "line": _position(line),
            "column": _position(column)}


def _error_item(error: UserFacingError, source: str, severity: str = "error") -> dict:
    return problem_item(severity, getattr(error, "code", ""), source, error.message,
                        error.file, error.line, error.column)


def _config_warning(text: str) -> dict:
    """``load_config``'s warnings are whole texts (``config.toml, line 3: unknown key …``);
    the location becomes the item's file and line."""
    match = _CONFIG_WHERE.match(text)
    if match is not None:
        return problem_item("warning", "", "config", text[match.end():], CONFIG_FILENAME,
                            int(match.group(1)), None)
    if text.startswith(CONFIG_FILENAME + ": "):
        text = text[len(CONFIG_FILENAME) + 2:]
    return problem_item("warning", "", "config", text, CONFIG_FILENAME, None, None)


# --- Names (04 §7.1 steps 6 and 8) -----------------------------------------------------------

@dataclass(frozen=True)
class CheckContext:
    """What a ``NAME_SOURCES`` row may read. ``program`` is None when the script didn't load;
    ``launch`` is None when the launch phase didn't run (``--no-launch``, or no program).
    ``errors`` counts the run's errors (config, load and launch); ``lint`` holds the lint
    phase's findings, None when it didn't run (F41 ``04`` §7.3)."""

    paths: GamePaths
    config: Config
    program: Program | None
    launch: LaunchResult | None = None
    namespace: Mapping[str, object] | None = None
    errors: int = 0
    lint: tuple[Finding, ...] | None = None


def _where(node: object) -> tuple[str | None, int | None]:
    file = getattr(node, "file", None)
    return getattr(file, "ref", None), getattr(node, "line", None)


def _label_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    if ctx.program is None:
        return None
    return [(name, *_where(label)) for name, label in ctx.program.labels.items()]


def _image_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    if ctx.program is None:
        return None
    index: ImageIndex | None = ctx.launch.images if ctx.launch is not None else None
    if index is None:
        index = build_index(ctx.program, image_source(ctx.paths))
    declared = ctx.program.images or {}
    rows: list[NameRow] = []
    for name, _image in index.items():
        decl = declared.get(name)
        rows.append((name, *_where(decl)) if decl is not None else (name, None, None))
    return rows


def _sprite_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    """F28 (07 I-16): the sprite tags (``ImageIndex.tags``), for ``effect jitter <sprite>``."""
    if ctx.program is None:
        return None
    index: ImageIndex | None = ctx.launch.images if ctx.launch is not None else None
    if index is None:
        index = build_index(ctx.program, image_source(ctx.paths))
    return [(tag, None, None) for tag in sorted(index.tags)]


def _glitch_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    """F28 (07 I-16): ``effect``'s kind words (the whole table, F30's rows too) and ``off``."""
    return [(word, None, None) for word in (*EFFECT_STATEMENT_KINDS, WORD_OFF)]


def _ui_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    """F32 (07 I-10): what ``ui`` can change (style, saving, loading, delete)."""
    return [(word, None, None) for word in UI_FORMS]


def _style_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    """F32 (07 I-10): the ``[style.<name>]`` names of config.toml, then ``off``
    (``ui style <style>``)."""
    return [(name, None, None) for name in (*ctx.config.style, WORD_OFF)]


def _style_uses(ctx: CheckContext) -> Iterable[NameRow] | None:
    """F32 (AC-F32-25, the Outline "Looks"): each ``ui style <name>`` line's style, at its
    line (``ui style off`` is no style's use)."""
    if ctx.program is None:
        return None
    return [(s.style, *_where(s)) for s in _statements(ctx.program)
            if isinstance(s, UiStatement) and s.form == UI_STYLE and s.style is not None]


def _ui_delete_lines(ctx: CheckContext) -> Iterable[NameRow] | None:
    """F32 (AC-F32-25): each ``ui delete saves`` line, at its line (the Outline's and the
    story map's "deletes saves")."""
    if ctx.program is None:
        return None
    return [(UI_SAVES, *_where(s)) for s in _statements(ctx.program)
            if isinstance(s, UiStatement) and s.form == UI_DELETE]


def _playthrough_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    """F32 (AC-F32-25): each ``[playthrough.N]`` look's N, at its table's line of
    config.toml (no place when the file can't be read again)."""
    keys = sorted(ctx.config.playthrough)
    if not keys:
        return []
    try:
        text = ctx.paths.read_file(CONFIG_FILENAME, max_bytes=CONFIG_MAX_BYTES).decode(
            "utf-8-sig")
        locator: KeyLocator | None = KeyLocator(text)
    except (UserFacingError, AssetNotFile, AssetTooLarge, AssetUnreadable, ValueError):
        locator = None
    rows: list[NameRow] = []
    for key in keys:
        line = locator.line_of("playthrough", str(key)) if locator is not None else None
        rows.append((str(key), CONFIG_FILENAME if line is not None else None, line))
    return rows


def _defines_whose_value(ctx: CheckContext, kind: type) -> list[NameRow]:
    if ctx.program is None or ctx.namespace is None:
        return []
    return [(define.name, *_where(define)) for define in ctx.program.defines
            if isinstance(ctx.namespace.get(define.name), kind)]


def _character_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    if ctx.namespace is None:
        return None
    return _defines_whose_value(ctx, Character)


def _transition_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    builtin: list[NameRow] = [(name, None, None) for name in BUILTIN_TRANSITION_NAMES]
    return builtin + _defines_whose_value(ctx, TransitionDef)


def _position_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    return [(name, None, None) for name in ctx.config.stage.positions]


def _audio_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    """Every playable file under ``audio/``, named as a script writes it (relative to
    ``audio/``)."""
    refs: set[str] = set()
    for ext in sorted(PLAYABLE_EXTS):
        walk = ctx.paths.walk_files(AUDIO_PREFIX.rstrip("/"), suffix=ext,
                                    max_entries=CHECK_MAX_NAMES,
                                    max_depth=AUDIO_WALK_MAX_DEPTH)
        refs.update(walk.refs)
    return [(ref.removeprefix(AUDIO_PREFIX), None, None) for ref in sorted(refs)]


# --- Story names for the Outline tab and completion (2026-11-02, AC-F45-51..55) ---------------

BUNDLED_MINIGAMES = Path(__file__).resolve().parents[1] / "minigames" / "bundled"
MINIGAME_PREFIX = "minigames/"
MINIGAME_WALK_MAX_DEPTH = 3                     # F23's package depth


def _statements(program: Program) -> Iterator[Statement]:
    """Every statement in label order, then pre-order (iterative, like ``label_links``)."""
    for label in program.labels.values():
        stack: list[list[Statement]] = [list(reversed(label.block))]
        while stack:
            if not stack[-1]:
                stack.pop()
                continue
            stmt = stack[-1].pop()
            yield stmt
            for block in reversed(stmt.blocks()):
                stack.append(list(reversed(block)))


def _chapter_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    if ctx.program is None:
        return None
    return [(s.name, *_where(s)) for s in _statements(ctx.program) if isinstance(s, Chapter)]


def _ending_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    if ctx.program is None:
        return None
    return [(e.name, *_where(e)) for e in ctx.program.endings]


def _route_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    if ctx.program is None:
        return None
    return [(r.name, *_where(r)) for r in ctx.program.routes]


def _route_until_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    """One row per ``until`` ending, placed at its route's line (the Outline pairs them)."""
    if ctx.program is None:
        return None
    return [(ending, *_where(r)) for r in ctx.program.routes for ending in r.until]


def _codex_names(kind: str) -> Callable[[CheckContext], Iterable[NameRow] | None]:
    def rows(ctx: CheckContext) -> Iterable[NameRow] | None:
        if ctx.program is None:
            return None
        return [(e.name, e.file, e.line) for e in ctx.program.codex if e.kind == kind]
    return rows


def _category_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    """One row per codex entry: its category's text, placed at the entry's line."""
    if ctx.program is None:
        return None
    return [(e.category.text or e.category.word or "", e.file, e.line)
            for e in ctx.program.codex]


def _meter_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    if ctx.program is None:
        return None
    return [(m.name, None, None) for m in ctx.program.meters]


def _flowchart_scenes(ctx: CheckContext) -> Iterable[NameRow] | None:
    """F20: each ``flowchart scene`` title, at its mark's line (the label's first line)."""
    if ctx.program is None:
        return None
    return [(s.title or "", *_where(s)) for s in _statements(ctx.program)
            if isinstance(s, Flowchart) and s.form == "scene"]


_FLAGGED_KINDS = frozenset(("scene", "choice", "chapter"))   # where "no jump" is the author's


def flow_node_text(node: FlowNode) -> str:
    """One chart node as Studio's Outline lists it: its kind (a gate is a ``route``), its
    title (``Heading: Title`` when it has a heading), and the author's flags."""
    kind = "route" if node.kind == "gate" else node.kind
    title = " ".join(node.title or ())
    if node.heading:
        title = f"{node.heading}: {title}" if title else node.heading
    flags = [word for word, on in (("hidden", node.hidden),
                                   ("no jump", node.no_jump and node.kind in _FLAGGED_KINDS))
             if on]
    text = f"{kind} {title}".rstrip()
    return f"{text} ({', '.join(flags)})" if flags else text


def _flowchart_nodes(ctx: CheckContext) -> Iterable[NameRow] | None:
    """F20: every node of the flowchart in chart order (``flow_node_text``), at its point's
    line; None when the graph wasn't built (``[flowchart] enabled = false`` or errors)."""
    program = ctx.program
    graph = None if program is None else program.flowgraph
    if program is None or graph is None:
        return None
    return [(flow_node_text(n), *_where(program.get(n.anchor))) for n in graph.nodes]


def _minigame_uses(ctx: CheckContext) -> Iterable[NameRow] | None:
    if ctx.program is None:
        return None
    return [(s.name, *_where(s)) for s in _statements(ctx.program) if isinstance(s, Minigame)]


# --- F47 usage rows (04 §3.3, §7.1 step 5; AC-F47-15), widened by F41 P1 (F41 04 §7.1) ------
# Syntactic, so they are sent under --no-launch too. One row per (name, file, line): Studio's
# Database counts a name's distinct lines ("Used in N lines"). F41 counts every kind of use:
# the gallery's, codex's, replays' and achievements' pictures, music-room tracks, minigame
# arguments (and the defines they name), F38 frames of a used look, config.toml values, and
# code or text that names any other define (``define_use``).

USE_KINDS = ("character_use", "image_use", "audio_use", "variable_use",
             # F47 P2-D: meters, codex entries, routes, transitions, positions.
             "meter_use", "codex_use", "route_use", "transition_use", "position_use",
             # F41 P1: code or text that names a define that isn't a character or transition.
             "define_use")
_USE_MAX_DEPTH = 8          # nested node data walked per statement; nested literal/TOML data
# The last program's rows, with the launch's image index they were counted against.
_USES_CACHE: list[tuple[Program, ImageIndex | None, dict[str, list[NameRow]]]] = []
# ``"x" in <view>`` in code: which use row the view's names count for.
_IN_VIEWS = {("codex", "tips"): "codex_use", ("codex", "items"): "codex_use",
             ("persistent", "routes"): "route_use"}
_CHARACTER_CALL = frozenset(("Character",))
_TRANSITION_CALLS = frozenset(("Dissolve", "Fade", "Mask"))   # F09: a define read as one
_CONTAINERS = (ast.Dict, ast.List, ast.Tuple, ast.Set)


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _text_of(node: ast.AST) -> str | None:
    """A string constant's text, else None."""
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) \
        else None


def _view_of(node: ast.AST) -> tuple[str, str] | None:
    """``(owner, attr)`` of ``codex.tips``-like code, else None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id, node.attr
    return None


def _variable_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    """F47: each ``default`` (a story variable), at its line."""
    if ctx.program is None:
        return None
    return [(d.name, *_where(d)) for d in ctx.program.defaults]


def _python_tree(source: str, mode: str) -> ast.AST | None:
    try:
        return ast.parse(source, mode=mode)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None


def _call_of(value: PyCode, callees: frozenset[str]) -> ast.Call | None:
    """A define's value when it is a call of one of ``callees`` (read, never run)."""
    tree = _python_tree(value.source.strip(), "eval")
    body = getattr(tree, "body", None)
    if isinstance(body, ast.Call) and isinstance(body.func, ast.Name) \
            and body.func.id in callees:
        return body
    return None


def _character_call(define: Define) -> ast.Call | None:
    """A define's value when it is a ``Character(...)`` call (read, never run)."""
    return _call_of(define.value, _CHARACTER_CALL)


def _strings(tree: ast.AST) -> Iterator[str]:
    """Every string constant of a parsed value, in source order, inside at most
    ``_USE_MAX_DEPTH`` nested dicts, lists, tuples and sets."""
    stack: list[tuple[ast.AST, int]] = [(tree, 0)]
    while stack:
        node, depth = stack.pop()
        text = _text_of(node)
        if text is not None:
            yield text
            continue
        if isinstance(node, _CONTAINERS):
            depth += 1
            if depth > _USE_MAX_DEPTH:
                continue
        stack.extend((child, depth) for child in reversed(list(ast.iter_child_nodes(node))))


def _toml_strings(value: object, path: tuple[str, ...],
                  depth: int = 0) -> Iterator[tuple[tuple[str, ...], str]]:
    """Every string value of parsed TOML with its key path (a list's items: the list's
    path), at most ``_USE_MAX_DEPTH`` tables and arrays deep."""
    if isinstance(value, str):
        yield path, value
    elif depth < _USE_MAX_DEPTH and isinstance(value, dict):
        for key, item in value.items():
            yield from _toml_strings(item, (*path, str(key)), depth + 1)
    elif depth < _USE_MAX_DEPTH and isinstance(value, list):
        for item in value:
            yield from _toml_strings(item, path, depth + 1)


class _UseWalk:
    """Collects the use rows of one program: who speaks, what is shown, what plays, which
    story variables and defines code, conditions and ``{var=…}`` tags name and (F41 P1)
    what the declarations, minigame arguments and config.toml show or play.

    ``pictures`` are the image index's names (matched without case), ``sounds`` the files
    under ``audio/`` (named relative to it), ``config_text`` config.toml's text (None: not
    read)."""

    def __init__(self, program: Program, pictures: Iterable[str] = (),
                 sounds: Iterable[str] = (), config_text: str | None = None) -> None:
        self.rows: dict[str, dict[NameRow, None]] = {kind: {} for kind in USE_KINDS}
        self.variables = program.default_names
        self.pictures = frozenset(pictures)
        self.folded = {name.casefold(): name for name in sorted(self.pictures)}
        self.sounds = frozenset(sounds)
        self.characters: set[str] = set()
        self.image_tags: dict[str, str] = {}             # a character's image_tag= literal
        self.transitions = {define.name for define in program.defines
                            if _call_of(define.value, _TRANSITION_CALLS) is not None}
        self.defines = {define.name for define in program.defines}
        # What a minigame argument's names lead to (characters aren't data).
        self.values: dict[str, PyCode] = {d.name: d.value for d in program.defaults}
        self.values.update((d.name, d.value) for d in program.defines)
        for define in program.defines:
            call = _character_call(define)
            if call is None:
                continue
            self.characters.add(define.name)
            ref, line = _where(define)
            for keyword in call.keywords:
                text = _text_of(keyword.value)
                if text is None:
                    continue
                if keyword.arg == "blip":
                    self.add("audio_use", text, ref, line)
                elif keyword.arg == "name_from" and text in self.variables:
                    self.add("variable_use", text, ref, line)
                elif keyword.arg == "image_tag":
                    self.image_tags[define.name] = text
        for name in self.characters:
            self.values.pop(name, None)
        for stmt in _statements(program):
            self.node(stmt, stmt.file.ref, stmt.line, 0)
        for define in program.defines:                   # values name other defines
            self.python(define.value, define.file.ref, own=define.name)
        for default in program.defaults:
            self.python(default.value, default.file.ref, own=default.name)
        self.declarations(program)
        if config_text is not None:
            self.config(config_text)
        self.frames()

    def add(self, kind: str, name: str | None, ref: str | None, line: int | None) -> None:
        if name:
            self.rows[kind][(name, ref, line)] = None

    def name(self, name: str | None, ref: str, line: int) -> None:
        """A name in code or in a text tag: a story variable, a character, a transition or
        another define."""
        if name in self.variables:
            self.add("variable_use", name, ref, line)
        elif name in self.characters:
            self.add("character_use", name, ref, line)
        elif name in self.transitions:
            self.add("transition_use", name, ref, line)
        elif name in self.defines:
            self.add("define_use", name, ref, line)

    def media(self, text: str, ref: str | None, line: int | None) -> None:
        """A string that names a picture (any case) or a sound (with or without
        ``audio/``)."""
        picture = self.folded.get(text.casefold())
        if picture is not None:
            self.add("image_use", picture, ref, line)
        sound = text.removeprefix(AUDIO_PREFIX)
        if sound in self.sounds:
            self.add("audio_use", sound, ref, line)

    def python(self, py: PyCode, ref: str, own: str | None = None) -> None:
        tree = _python_tree(py.source, py.mode)
        if tree is not None:
            self.code(tree, ref, py.line, own)

    def code(self, tree: ast.AST, ref: str, line: int, own: str | None = None) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if node.id != own:
                    self.name(node.id, ref, line)
            elif isinstance(node, ast.Attribute) and _is_name(node.value, "points"):
                if node.attr != "highest":                           # points.highest(…)
                    self.add("meter_use", node.attr, ref, line)      # points.hana
            elif isinstance(node, ast.Subscript) and _is_name(node.value, "points"):
                self.add("meter_use", _text_of(node.slice), ref, line)  # points["hana"]
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and _is_name(node.func.value, "points") and node.func.attr == "highest":
                for arg in node.args:
                    self.add("meter_use", _text_of(arg), ref, line)
            elif isinstance(node, ast.Compare) and len(node.comparators) == 1:
                kind = _IN_VIEWS.get(_view_of(node.comparators[0]))
                if kind is not None:                         # "lanterns" in codex.tips
                    self.add(kind, _text_of(node.left), ref, line)

    def data(self, value: PyCode, ref: str, line: int) -> None:
        """F41 §7.1 item 3: the pictures and sounds a minigame argument names: its strings,
        and those of the defines and defaults it names (``room=shed``), followed at most
        ``_USE_MAX_DEPTH`` names deep, all at the argument's line."""
        todo: list[tuple[PyCode, int]] = [(value, 0)]
        seen: set[str] = set()
        while todo:
            code, hops = todo.pop()
            tree = _python_tree(code.source.strip(), "eval")
            if tree is None:
                continue
            for text in _strings(tree):
                self.media(text, ref, line)
            if hops >= _USE_MAX_DEPTH:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in self.values \
                        and node.id not in seen:
                    seen.add(node.id)
                    todo.append((self.values[node.id], hops + 1))

    def node(self, obj: object, ref: str, line: int, depth: int) -> None:
        if depth > _USE_MAX_DEPTH or obj is None or isinstance(obj, (str, int, float, bool)):
            return
        if isinstance(obj, PyCode):
            self.python(obj, ref)
            return
        if isinstance(obj, TaggedText):
            for piece in obj.pieces:
                if isinstance(piece, VarMark):
                    self.name(piece.name, ref, line)
                elif isinstance(piece, NameMark) and piece.var in self.variables:
                    self.add("variable_use", piece.var, ref, line)
            return
        if isinstance(obj, tuple):
            if obj and isinstance(obj[0], Statement):
                return                                   # a block: _statements walks it
            for item in obj:
                self.node(item, ref, line, depth + 1)
            return
        if not is_dataclass(obj) or isinstance(obj, type):
            return
        own = getattr(obj, "line", None)
        line = own if type(own) is int else line
        if isinstance(obj, Say):
            self.add("character_use", obj.speaker, ref, line)
            if obj.speaker and obj.attributes:
                tag = self.image_tags.get(obj.speaker, obj.speaker)
                self.add("image_use", " ".join((tag, *obj.attributes)), ref, line)
        elif isinstance(obj, (Scene, Show)):
            self.add("image_use", obj.image, ref, line)
        elif isinstance(obj, (PlayAudio, QueueMusic, StopAudio, Voice)):
            self.add("audio_use", obj.audio_file, ref, line)
        elif isinstance(obj, PointsChange):
            self.add("meter_use", obj.name, ref, line)
        elif isinstance(obj, ChoiceCheck):                   # F59: check <meter> on a choice
            self.add("meter_use", obj.meter, ref, line)
        elif isinstance(obj, CodexLock):
            self.add("codex_use", obj.name, ref, line)
        elif isinstance(obj, Lock) and obj.kind == "route":
            self.add("route_use", obj.name, ref, line)
        elif isinstance(obj, WithClause):
            self.add("transition_use", obj.name, ref, line)
        elif isinstance(obj, At):
            self.add("position_use", obj.name, ref, line)
        elif isinstance(obj, Minigame):
            if obj.target in self.variables:              # into <variable>
                self.add("variable_use", obj.target, ref, line)
            for arg in obj.args:
                self.data(arg.value, ref, arg.line)
        for item in fields(obj):
            if item.name not in ("file", "sid", "label", "path"):
                self.node(getattr(obj, item.name, None), ref, line, depth + 1)

    def declarations(self, program: Program) -> None:
        """F41 §7.1 item 2: what the gallery, codex, replays and achievements show (decision
        3: an achievement's icon), what the music room plays, the replays' starting values
        and the achievements' ``when`` code, each at its declaration's line."""
        for gallery in program.gallery:
            for picture in gallery.pictures:
                self.add("image_use", picture, gallery.file, gallery.line)
        for entry in program.codex:
            self.add("image_use", entry.image, entry.file, entry.line)
            for paragraph in entry.paragraphs:           # {var} tags, at the entry's line
                self.node(paragraph, entry.file, entry.line, 0)
        for replay in program.replays:
            self.add("image_use", replay.image, replay.file, replay.line)
            for name, _value in replay.values:
                if name in self.variables:
                    self.add("variable_use", name, replay.file, replay.line)
        for track in program.tracks:
            self.add("audio_use", track.file, track.script, track.line)
        for achievement in program.achievements:
            ref, line = _where(achievement)
            self.add("image_use", achievement.image, ref, line)
            tree = _python_tree(achievement.when.strip(), "eval") if achievement.when else None
            if tree is not None and ref is not None and line is not None:
                self.code(tree, ref, line)

    def config(self, text: str) -> None:
        """F41 §7.1 item 5: every config.toml string that names a picture or a sound, at
        its key's line (None when it can't be found)."""
        try:
            doc = tomllib.loads(text)
        except (tomllib.TOMLDecodeError, ValueError, RecursionError):
            return
        locator = KeyLocator(text)
        for path, value in _toml_strings(doc, ()):
            self.media(value, CONFIG_FILENAME, locator.line_of(*path))

    def frames(self) -> None:
        """F41 §7.1 item 4: an F38 blink or talking frame shares its look's places (a frame
        of an unused look stays unused)."""
        places: dict[str, list[tuple[str | None, int | None]]] = {}
        for name, ref, line in self.rows["image_use"]:
            places.setdefault(name.casefold(), []).append((ref, line))
        for name in sorted(self.pictures):
            frame = frame_of(name, self.pictures)
            if frame is not None:
                for ref, line in places.get(frame.look.casefold(), ()):
                    self.add("image_use", name, ref, line)


def _index_of(ctx: CheckContext) -> ImageIndex:
    """The launch's image index, else one built from the story and ``images/``."""
    index: ImageIndex | None = ctx.launch.images if ctx.launch is not None else None
    if index is None:
        assert ctx.program is not None
        index = build_index(ctx.program, image_source(ctx.paths))
    return index


def _config_text(ctx: CheckContext) -> str | None:
    """config.toml's text through ``ctx.paths`` (an overlay counts): ``""`` when the game
    has none (nothing to count, and no error), None when unreadable."""
    try:
        return ctx.paths.read_file(CONFIG_FILENAME, max_bytes=CONFIG_MAX_BYTES).decode(
            "utf-8-sig")
    except AssetMissing:
        return ""
    except (UserFacingError, AssetNotFile, AssetTooLarge, AssetUnreadable, AssetRefError,
            OSError, ValueError):
        return None


def _story_uses(ctx: CheckContext) -> dict[str, list[NameRow]]:
    program = ctx.program
    assert program is not None
    launched = ctx.launch.images if ctx.launch is not None else None
    if not _USES_CACHE or _USES_CACHE[0][0] is not program \
            or _USES_CACHE[0][1] is not launched:
        try:
            sounds = [name for name, _file, _line in _audio_names(ctx) or ()]
        except Exception:                                # no audio/ walk: no sound matches
            sounds = []
        walk = _UseWalk(program, _index_of(ctx).names, sounds, _config_text(ctx))
        _USES_CACHE[:] = [(program, launched,
                           {kind: list(rows) for kind, rows in walk.rows.items()})]
    return _USES_CACHE[0][2]


def _uses(kind: str) -> Callable[[CheckContext], Iterable[NameRow] | None]:
    def rows(ctx: CheckContext) -> Iterable[NameRow] | None:
        if ctx.program is None:
            return None
        return _story_uses(ctx)[kind]
    return rows


def _replay_scenes(ctx: CheckContext) -> Iterable[NameRow] | None:
    """F41 §7.1 item 7: each scene replay's label, at its declaration's line (the story
    map's and lint's starting points besides ``start``)."""
    if ctx.program is None:
        return None
    return [(replay.label, replay.file, replay.line) for replay in ctx.program.replays]


def _bundled_sigs() -> list[tuple[PluginSig, str | None]]:
    found: list[tuple[PluginSig, str | None]] = []
    for path in sorted(BUNDLED_MINIGAMES.glob("*.py")):
        text = path.read_text("utf-8")
        sibling = lambda module, name: dict_keys(  # noqa: E731
            (BUNDLED_MINIGAMES / f"{module}.py").read_text("utf-8")
            if (BUNDLED_MINIGAMES / f"{module}.py").is_file() else "", name)
        found.extend((sig, None) for sig in plugin_sigs(text, sibling))
    return found


def _game_sigs(paths: GamePaths) -> list[tuple[PluginSig, str | None]]:
    """``minigames/`` plugins, read as text (never run; F23 loads them only in ``app``)."""
    try:
        walk = paths.walk_files(MINIGAME_PREFIX.rstrip("/"), suffix=".py", max_entries=64,
                                max_depth=MINIGAME_WALK_MAX_DEPTH)
    except Exception:
        return []
    found: list[tuple[PluginSig, str | None]] = []
    for ref in walk.refs:
        try:
            text = paths.read_file(ref, max_bytes=MINIGAME_FILE_MAX_BYTES).decode("utf-8")
        except Exception:
            continue
        found.extend((sig, ref) for sig in plugin_sigs(text))
    return found


def _minigame_sigs(ctx: CheckContext) -> list[tuple[PluginSig, str | None]]:
    return _game_sigs(ctx.paths) + _bundled_sigs()


def _minigame_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    rows: dict[str, NameRow] = {}
    for sig, ref in _minigame_sigs(ctx):
        rows.setdefault(sig.name, (sig.name, ref, sig.line if ref is not None else None))
    return list(rows.values())


def _minigame_arg_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    """``<minigame>.<arg>`` rows; a required argument's row carries line 1 (Studio's
    ``assist`` lists required ones first)."""
    rows: dict[str, NameRow] = {}
    for sig, _ref in _minigame_sigs(ctx):
        for arg, required in sig.args:
            rows.setdefault(f"{sig.name}.{arg}", (f"{sig.name}.{arg}", None,
                                                  1 if required else None))
    return list(rows.values())


def _meta_file_uses(ctx: CheckContext) -> Iterable[NameRow] | None:
    """F31: each ``file`` line's name, at its line (reading order)."""
    if ctx.program is None:
        return None
    return [(s.name, *_where(s)) for s in _statements(ctx.program) if isinstance(s, MetaFile)]


def _meta_file_names(ctx: CheckContext) -> Iterable[NameRow] | None:
    """F31: every meta file name, once: a ``file`` line's at its first line, then each file
    in ``files/`` that ``is_meta_name`` takes (no place; ``Hana.chr`` and ``x.png`` aren't
    names). The folder is listed only (never read), through ``GamePaths``."""
    rows: dict[str, NameRow] = {}
    for row in _meta_file_uses(ctx) or ():
        rows.setdefault(row[0], row)
    listing = ctx.paths.list_real(META_ORIGINALS_DIR)
    for name in sorted(listing.files if listing is not None else ()):
        if is_meta_name(name):
            rows.setdefault(name, (name, None, None))
    return list(rows.values())


def _lint_phase(ctx: CheckContext) -> tuple[Finding, ...] | None:
    """F41 ``04`` §7.3 step 2: the lint findings of a story that loaded with no error at all
    (config, load or launch; decision 4), else None. Under ``--no-launch`` ``ctx.namespace``
    is None: no W238, and transitions are read from their literal calls."""
    program = ctx.program
    if program is None or ctx.errors:
        return None
    try:
        sounds = [name for name, _file, _line in _audio_names(ctx) or ()]
    except Exception:                                    # no audio/ walk: no sound findings
        sounds = []
    return findings(program, ctx.config, ctx.paths, _index_of(ctx), sounds, ctx.namespace,
                    _story_uses(ctx), _config_text(ctx))


def _lint_rows(kind: str) -> Callable[[CheckContext], Iterable[NameRow] | None]:
    """A lint kind's names rows (04 §7.3 step 3): not sent when lint didn't run, nor
    ``unused_character`` without launch values (PR-F41-01)."""
    def rows(ctx: CheckContext) -> Iterable[NameRow] | None:
        if ctx.lint is None:
            return None
        return rows_by_kind(ctx.lint, characters=ctx.namespace is not None).get(kind)
    return rows


NAME_SOURCES: dict[str, Callable[[CheckContext], Iterable[NameRow] | None]] = {
    "label": _label_names,
    "image": _image_names,
    "character": _character_names,
    "transition": _transition_names,
    "position": _position_names,
    "audio": _audio_names,
    "chapter": _chapter_names,              # F18
    "ending": _ending_names,                # F19
    "route": _route_names,                  # F19
    "route_until": _route_until_names,      # F19: an until ending, at its route's line
    "tip": _codex_names("tip"),             # F21
    "item": _codex_names("item"),           # F21
    "category": _category_names,            # F21: an entry's category, at the entry's line
    "meter": _meter_names,                  # F22
    "minigame": _minigame_names,            # F23: plugins that can be named
    "minigame_arg": _minigame_arg_names,    # F23: "<minigame>.<arg>"
    "minigame_use": _minigame_uses,         # F23: each minigame line in the story
    "flowchart_scene": _flowchart_scenes,   # F20: each scene mark's title, at its line
    "flowchart_node": _flowchart_nodes,     # F20 s9: every chart node, at its point's line
    "glitch": _glitch_names,                # F28: effect's kind words and off
    "ui": _ui_names,                        # F32: what ui changes
    "style": _style_names,                  # F32: config's style names and off
    "style_use": _style_uses,               # F32: each ui style <name> line
    "ui_delete": _ui_delete_lines,          # F32: each ui delete saves line
    "playthrough": _playthrough_names,      # F32: each [playthrough.N] look, at its table
    "sprite": _sprite_names,                # F28: sprite tags (effect jitter <sprite>)
    "variable": _variable_names,            # F47: each default, at its line
    "character_use": _uses("character_use"),   # F47: each line a character speaks or is named
    "image_use": _uses("image_use"),        # F47: each scene/show line (and say attributes)
    "audio_use": _uses("audio_use"),        # F47: each audio line, and Character blips
    "variable_use": _uses("variable_use"),  # F47: each line whose code or text names a default
    "meter_use": _uses("meter_use"),        # F47 P2: points changes and points.<n> in code
    "codex_use": _uses("codex_use"),        # F47 P2: lock/unlock tip|item, "n" in codex.tips
    "route_use": _uses("route_use"),        # F47 P2: lock/unlock route, "n" in persistent.routes
    "transition_use": _uses("transition_use"),  # F47 P2: each with clause's transition
    "position_use": _uses("position_use"),  # F47 P2: each show … at <position name>
    "define_use": _uses("define_use"),      # F41 P1: code or a text tag naming another define
    "replay_scene": _replay_scenes,         # F41 P1: each scene replay's label, at its line
    "meta_file": _meta_file_names,          # F31: names in file lines and files/ originals
    "meta_file_use": _meta_file_uses,       # F31: each file line's name, at its line
    # F41 P3: the lint findings, kind by kind (unreached, unused_*): Studio's Clean up reads
    # them; they never travel as problem items (PR-F45-08 holds).
    **{kind: _lint_rows(kind) for kind in LINT_KINDS},
}


# --- The check (04 §7.1 steps 3-10) ----------------------------------------------------------

SEVERITIES = ("error", "warning", "info")


@dataclass(frozen=True)
class CheckOutcome:
    """One check's results (F41 ``04`` §7.3 step 1): ``problems`` in engine order (all of
    them; the wire sends the first ``CHECK_MAX_PROBLEMS``), ``counts`` the true totals per
    severity (``error``, ``warning``, ``info``) and ``total`` their sum, the ``names`` rows
    by kind, the ``program`` (None: it didn't load), the run's ``seconds``, and the lint
    findings (None: lint didn't run). Lint findings are never in ``problems`` or the
    counts."""

    problems: list[dict]
    counts: dict[str, int]
    total: int
    names: dict[str, list[NameRow]]
    program: Program | None
    seconds: float
    lint: tuple[Finding, ...] | None = None


class CheckJob:
    """One check of ``paths``: config, load, launch (``launch=False``: skipped, 07 I-1),
    lint (F41), names, graph. ``run`` sends every event to ``emit`` as a dict, ``done``
    last; ``collect`` returns the results instead (the ``lint`` command)."""

    def __init__(self, paths: GamePaths, emit: Emit, *, launch: bool = True,
                 clock: Callable[[], float] = time.perf_counter) -> None:
        self.paths = paths
        self.emit = emit
        self.launch = launch
        self._clock = clock

    def run(self) -> None:
        outcome = self.collect()
        emit_results(self.emit, outcome.problems, outcome.total, outcome.names,
                     outcome.program, outcome.seconds)

    def collect(self) -> CheckOutcome:
        started = self._clock()
        paths = self.paths
        counts = dict.fromkeys(SEVERITIES, 0)
        try:
            GamePaths.for_game(paths.root)               # the folder is still there
        except UserFacingError as error:
            counts["error"] = 1
            return CheckOutcome([_error_item(error, "load")], counts, 1, {}, None,
                                self._clock() - started)
        problems: list[dict] = []

        config_result = load_config(paths)
        config = config_result.config
        for error in config_result.errors:
            problems.append(_config_item(error))
        problems += [_config_warning(text) for text in config_result.warnings]
        counts["error"] += len(config_result.errors)
        counts["warning"] += len(config_result.warnings)

        options = LoadOptions(collect_todos=True,
                              position_names=frozenset(config.stage.positions),
                              flowchart=FlowOptions.from_config(config.flowchart),   # F20
                              username_fallback=config.meta.username_fallback,       # F30
                              # F32: E320 as the game gives it; a broken config.toml (its
                              # errors are listed above) checks no style name.
                              style_names=None if config_result.errors
                              else frozenset(config.style))
        loaded = load_story(paths, options)
        problems += [_error_item(error, "load") for error in loaded.errors]
        problems += [_error_item(warning, "load", "warning") for warning in loaded.warnings]
        problems += [problem_item("info", "TODO", "load", todo.text, todo.file.ref, todo.line,
                                  None) for todo in loaded.todos]
        counts["error"] += max(loaded.error_count, len(loaded.errors))
        counts["warning"] += len(loaded.warnings)
        counts["info"] += max(loaded.todo_count, len(loaded.todos))
        program = loaded.program

        launch: LaunchResult | None = None
        namespace: Mapping[str, object] | None = None
        if program is not None and self.launch:
            job = LaunchJob(program, dev=True, game_has=game_has(paths),
                            images=image_source(paths), game_root=paths.root,
                            persistent=None,
                            audio=audio_files(paths, config.audio.loop_start))
            while not job.step():
                pass
            launch = job.result
            namespace = job.G
            problems += [_error_item(error, "launch") for error in launch.errors]
            problems += [_error_item(warning, "launch", "warning")
                         for warning in launch.warnings]
            counts["error"] += max(launch.error_count, len(launch.errors))
            counts["warning"] += len(launch.warnings)

        context = CheckContext(paths, config, program, launch, namespace, counts["error"])
        try:
            context = replace(context, lint=_lint_phase(context))
        except Exception:                                # a broken lint loses its kinds only
            pass
        names = self._names(context)
        return CheckOutcome(problems, counts, sum(counts.values()), names, program,
                            self._clock() - started, context.lint)

    def _names(self, context: CheckContext) -> dict[str, list[NameRow]]:
        names: dict[str, list[NameRow]] = {}
        for kind, source in NAME_SOURCES.items():
            if _KIND.fullmatch(kind) is None:
                continue
            try:
                rows = source(context)
                rows = None if rows is None else list(rows)
            except Exception:                            # a broken row loses its kind only
                rows = None
            if rows is not None:
                names[kind] = rows
        return names


def emit_results(emit: Emit, problems: list[dict], total: int,
                 names: Mapping[str, list[NameRow]], program: Program | None,
                 seconds: float) -> None:
    """The run's events (04 §7.1 step 10): problems, names kind by kind, the graph (only
    with a program), then ``done``. Items past the §4.3 totals are counted, not sent;
    ``done`` carries the true totals."""
    total = max(total, len(problems))
    for event in chunk_event("problems", problems[:CHECK_MAX_PROBLEMS]):
        emit(event)
    name_totals: dict[str, int] = {}
    for kind, rows in names.items():
        name_totals[kind] = len(rows)
        sent = ([_text(name), None if file is None else _text(file), _position(line)]
                for name, file, line in rows[:CHECK_MAX_NAMES])
        for event in chunk_event("names", sent, kind=kind):
            emit(event)
    link_total = 0
    if program is not None:
        links, link_total = label_links(program, limit=CHECK_MAX_LINKS)
        # F46 ``04`` §3.5: 7 items, the choice text (or null) and its condition flag last.
        sent_links = ([_text(link.src), _text(link.dst), link.kind, _text(link.file),
                       link.line, None if link.choice is None else _text(link.choice),
                       link.conditional] for link in links[:CHECK_MAX_LINKS])
        for event in chunk_event("graph", sent_links, key="links"):
            emit(event)
        try:
            rows = reach_rows(program)
        except Exception:                       # a fault here never costs the check
            rows = []
        for event in chunk_event("reach", ([_text(scene), kind, _text(text),
                                             None if file is None else _text(file),
                                             _position(line)]
                                            for scene, kind, text, file, line
                                            in rows[:CHECK_MAX_REACH])):
            emit(event)
    emit({"v": REPORT_VERSION, "event": "done", "loaded": program is not None,
          "problems": total, "seconds": round(max(seconds, 0.0), 3),
          "name_totals": name_totals, "link_total": link_total})


REACH_WAY: Final = "From {src}{choice}: {needs}"
REACH_NO_NEEDS: Final = "no condition"
REACH_NEVER: Final = " (never: {why})"
REACH_SET_IN: Final = "{text}, in {scene}"


def reach_rows(program: Program) -> list[tuple[str, str, str, str | None, int | None]]:
    """``script/reach.py``'s findings as ``reach`` rows (scene, kind, text, file, line): for
    each scene with a condition on a way in, every way in and the lines that set what they
    read; and a ``blocked`` row for a scene no playthrough can reach."""
    from engine.script import reach
    from engine.tools.lint import starts_of
    rows = []
    for scene, found in reach.analyze(program, starts_of(program)).items():
        label = program.labels.get(scene)
        if found.blocked is not None:
            rows.append((scene, "blocked", found.blocked,
                         label.file.ref if label else None, label.line if label else None))
        for way in found.ways:
            text = REACH_WAY.format(src=way.src,
                                    choice=f' ("{way.choice}")' if way.choice else "",
                                    needs=("needs " + " and ".join(way.needs)) if way.needs
                                    else REACH_NO_NEEDS)
            if not way.possible and way.why:
                text += REACH_NEVER.format(why=way.why)
            rows.append((scene, "way", text, way.file, way.line))
        for setter in found.setters:
            text = setter.text if setter.scene is None else REACH_SET_IN.format(
                text=setter.text, scene=setter.scene)
            rows.append((scene, "set", text, setter.file, setter.line))
    return rows


def _config_item(error: ConfigError) -> dict:
    return problem_item("error", "", "config", error.message, error.file or CONFIG_FILENAME,
                        error.line, error.column)


# --- The command (04 §5, §7.1 steps 1-2) -----------------------------------------------------

def _quiet_logs() -> None:
    """The engine's loggers write nowhere: no log file, no console records (§7.1 step 1)."""
    root = logging.getLogger(ROOT_LOGGER)
    root.handlers[:] = [logging.NullHandler()]
    root.propagate = False


def _isolate_stdout() -> BinaryIO:
    """The report stream: a duplicate of fd 1. Then fd 1 and ``sys.stdout`` point at the
    null device, so the author's ``print`` can't reach the report (§7.1 step 1)."""
    sys.stdout.flush()
    report = os.fdopen(os.dup(1), "wb")
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 1)
    finally:
        os.close(devnull)
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    return report


def _plain_line(event: dict) -> str | None:
    """Without ``--report-to-editor``: a readable line per problem and for ``done``."""
    if event["event"] == "problems":
        lines = []
        for item in event["items"]:
            where = item["file"] or ""
            if item["line"] is not None:
                where += f", line {item['line']}"
            head = " ".join(part for part in (item["severity"], item["code"]) if part)
            lines.append(f"{head} {where}: {item['text']}" if where else
                         f"{head}: {item['text']}")
        return "\n".join(lines)
    if event["event"] == "done":
        return (f"done: loaded {str(event['loaded']).lower()}, {event['problems']} "
                f"problem(s), {event['seconds']} s")
    return None


def check_command(game_dir: Path, *, report: bool, overlay: bool, launch: bool = True) -> int:
    """``python -m engine check GAME_DIR [--report-to-editor] [--stdin-overlay]
    [--no-launch]``: 0 after ``done``; 2 for a bad overlay (nothing is checked, nothing is
    written to stdout)."""
    sys.dont_write_bytecode = True
    _quiet_logs()
    files: dict[str, bytes] = {}
    if overlay:
        try:
            files = read_overlay(sys.stdin.buffer)
        except OverlayError as error:
            sys.stderr.write(f"check: {error}\n")
            return EXIT_BAD_INPUT
    out = _isolate_stdout() if report else None

    def emit(event: dict) -> None:
        if out is not None:
            out.write(encode_event(event) + b"\n")
        else:
            line = _plain_line(event)
            if line:
                print(line, flush=True)

    try:
        try:
            root = GamePaths.for_game(game_dir).root
        except UserFacingError as error:
            emit_results(emit, [_error_item(error, "load")], 1, {}, None, 0.0)
            return EXIT_DONE
        added = getattr(files, "added", frozenset())
        paths = OverlayPaths(root, overlay=files, added=added) if files else GamePaths(root)
        if isinstance(paths, OverlayPaths) and added:
            try:
                paths.check_added()                     # F48 SEC-F48-02, before any check
            except OverlayError as error:
                sys.stderr.write(f"check: {error}\n")
                return EXIT_BAD_INPUT
        CheckJob(paths, emit, launch=launch).run()
        return EXIT_DONE
    finally:
        if out is not None:
            out.flush()


# --- The lint command (F41 04 §7.3 step 5; PR-F41-08..11) ------------------------------------

EXIT_PROBLEMS = 1                       # errors (with --strict, warnings too)
LINT_SOURCE = "lint"
_SUMMARY_WORDS = (("error", "errors"), ("warning", "warnings"), ("note", "notes"))


def lint_item(finding: Finding) -> dict:
    """A finding as a ``lint`` item: a warning from ``source: "lint"`` at its place."""
    return problem_item("warning", finding.code, LINT_SOURCE, finding.text, finding.file,
                        finding.line, None)


def lint_line(item: dict) -> str:
    """``{file}:{line}:{column}: {severity} {code}: {text}`` (PR-F41-08): missing parts drop
    from the right, ``{file}: `` without a file, `` {code}`` without a code."""
    head = ""
    if item["file"] is not None:
        head = item["file"]
        if item["line"] is not None:
            head += f":{item['line']}"
            if item["column"] is not None:
                head += f":{item['column']}"
        head += ": "
    code = f" {item['code']}" if item["code"] else ""
    return f"{head}{item['severity']}{code}: {item['text']}"


def lint_summary(errors: int, warnings: int, notes: int) -> str:
    """``{n} errors, {n} warnings, {n} notes.`` (``1 error``, ``1 warning``, ``1 note``)."""
    return ", ".join(f"{n} {one if n == 1 else many}" for n, (one, many)
                     in zip((errors, warnings, notes), _SUMMARY_WORDS)) + "."


def lint_report(outcome: CheckOutcome, *, as_json: bool) -> tuple[bytes, int, int]:
    """The ``lint`` output of a check (UTF-8 text, or one ASCII JSON document), with its
    error and warning totals. Items: the problems, then each lint finding; the first
    ``CHECK_MAX_PROBLEMS`` are shown, the counts and ``more`` cover them all."""
    found = outcome.lint or ()
    items = outcome.problems + [lint_item(finding) for finding in found]
    shown = items[:CHECK_MAX_PROBLEMS]
    errors = outcome.counts["error"]
    warnings = outcome.counts["warning"] + len(found)
    notes = outcome.counts["info"]
    more = max(max(outcome.total, len(outcome.problems)) + len(found) - len(shown), 0)
    if as_json:
        text = json.dumps({"v": REPORT_VERSION, "items": shown, "errors": errors,
                           "warnings": warnings, "notes": notes, "more": more},
                          ensure_ascii=True)
        return (text + "\n").encode("ascii"), errors, warnings
    lines = [lint_line(item) for item in shown] + [lint_summary(errors, warnings, notes)]
    return ("\n".join(lines) + "\n").encode("utf-8"), errors, warnings


def lint_command(game_dir: Path, *, as_json: bool, strict: bool) -> int:
    """The engine side of ``python -m engine lint [GAME_DIR] [--json] [--strict]``: a full
    check (config, load, launch, lint) printed for editors and CI, paths relative to the
    game folder. Exit 0 when there are no errors, 1 with errors (with ``strict``, with
    warnings too), 2 when ``game_dir`` isn't a game folder (its message on stderr). Writes
    nothing in the game folder, and the author's ``print`` can't reach the output."""
    sys.dont_write_bytecode = True
    _quiet_logs()
    try:
        root = GamePaths.for_game(game_dir).root
    except UserFacingError as error:
        sys.stderr.write(f"{error.message}\n")
        return EXIT_BAD_INPUT
    out = _isolate_stdout()
    try:
        outcome = CheckJob(GamePaths(root), lambda event: None).collect()
        data, errors, warnings = lint_report(outcome, as_json=as_json)
        out.write(data)
    finally:
        out.flush()
    return EXIT_PROBLEMS if errors or (strict and warnings) else EXIT_DONE


__all__ = ["CheckContext", "CheckJob", "CheckOutcome", "NAME_SOURCES", "Overlay",
           "OverlayError", "OverlayPaths", "check_command", "chunk_event", "emit_results",
           "encode_event", "lint_command", "lint_item", "lint_line", "lint_report", "lint_summary",
           "problem_item", "read_overlay"]

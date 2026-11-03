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
  only where ``GamePaths`` would serve the file on disk: an overlay can't add a file, reach
  outside, or raise a cap.
- **When author code runs** (``07`` I-1). ``--no-launch`` skips the launch phase, so no
  ``define``, ``default``, or ``module()`` code runs; Studio passes it until the author's
  first Preview, Save, or Check in that window. The names that need launch values
  (``character``, defined transitions) are then not sent.
- **Not checked here** (``07`` I-8): ``app``-only launch checks (F05/F17's text check, F18's
  W111, F23's plugin load). They show on Preview.

``NAME_SOURCES`` is the table later features extend: one row per name kind a statement doc
lists (``07`` O-2). A row returns ``(name, file, line)`` entries, or None when it has no
inputs; a row that raises is skipped, and its kind isn't sent.

Imports ``core``, ``script``, and ``runtime`` only (never pygame, ``app``, ``render``,
``ui``, ``audio``, ``persist``, ``meta``, or ``minigames``; ``tests/test_import_rules.py``).
"""

import ast
import json
import logging
import os
import re
import stat
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import BinaryIO

from engine.core.config import load_config
from engine.core.config_schema import Config
from engine.core.constants import CONFIG_FILENAME, CONFIG_MAX_BYTES
from engine.core.editorreport import (
    CHECK_EVENT_MAX_ITEMS,
    CHECK_KIND_RE,
    CHECK_MAX_LINKS,
    CHECK_MAX_NAMES,
    CHECK_MAX_PROBLEMS,
    OVERLAY_HEADER_MAX,
    OVERLAY_MAX_BYTES,
    OVERLAY_MAX_FILES,
    OVERLAY_READ_CHUNK,
    REPORT_MARKER,
    REPORT_MAX_BYTES,
    REPORT_TEXT_MAX_CHARS,
    REPORT_VERSION,
)
from engine.core.errors import (
    AssetNotFile,
    AssetRefError,
    AssetTooLarge,
    AssetUnreadable,
    ConfigError,
    UserFacingError,
)
from engine.core.logsetup import ROOT_LOGGER
from engine.core.paths import GamePaths, check_ref
from engine.core.redact import echo
from engine.runtime.character import Character
from engine.runtime.gamesources import audio_files, game_has, image_source
from engine.runtime.images import ImageIndex, build_index
from engine.runtime.launch import LaunchJob, LaunchResult
from engine.runtime.limits import IMAGE_SCAN_MAX_DEPTH
from engine.runtime.transitions import TransitionDef
from engine.script import LoadOptions, load_story
from engine.script.audio import PLAYABLE_EXTS, PlayAudio, QueueMusic, StopAudio, Voice
from engine.script.effects import BUILTIN_TRANSITION_NAMES
from engine.script.labelgraph import label_links
from engine.script.assetgroups import MINIGAME_FILE_MAX_BYTES
from engine.script.limits import SCRIPT_FILE_MAX_BYTES
from engine.script.flowchart import Flowchart
from engine.script.flowgraph import FlowNode, FlowOptions
from engine.script.glitch import EFFECT_STATEMENT_KINDS, WORD_OFF
from engine.script.minigame import Minigame
from engine.script.nodes import Chapter, Define, PyCode, Say, Statement
from engine.script.pluginsigs import PluginSig, dict_keys, plugin_sigs
from engine.script.program import Program
from engine.script.stage import Scene, Show
from engine.script.texttags import NameMark, TaggedText, VarMark
from engine.script.ui import FORMS as UI_FORMS

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


def read_overlay(stream: BinaryIO) -> dict[str, bytes]:
    """The overlay on ``stream``: ``{ref: bytes}`` in header order. Raises ``OverlayError``.

    The header line is read with a limit of ``OVERLAY_HEADER_MAX`` + 1 bytes and checked
    whole (``v`` 1, at most 64 files, each ref ``config.toml`` or ``script/….vns`` and
    unique, each size an int within its file's cap, the total within 64 MiB) before any of
    the body is read. The body is read in 1 MiB chunks, exactly the declared bytes, and must
    end there (EOF): at most the declared bytes plus one chunk are ever read."""
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
    total = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise OverlayError("an overlay entry isn't an object")
        ref, size = entry.get("ref"), entry.get("size")
        if not _overlay_ref_ok(ref):
            raise OverlayError("an overlay ref isn't config.toml or a script/….vns file")
        if ref in sizes:
            raise OverlayError("an overlay ref is listed twice")
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
    overlay: dict[str, bytes] = {}
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
    and every other file come from disk. Nothing is ever written."""

    overlay: Mapping[str, bytes] = field(default_factory=dict, compare=False)

    def read_file(self, ref: str, *, max_bytes: int, regular: bool = False) -> bytes:
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
    ``launch`` is None when the launch phase didn't run (``--no-launch``, or no program)."""

    paths: GamePaths
    config: Config
    program: Program | None
    launch: LaunchResult | None = None
    namespace: Mapping[str, object] | None = None


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


# --- F47 usage rows (04 §3.3, §7.1 step 5; AC-F47-15) ----------------------------------------
# Syntactic, so they are sent under --no-launch too. One row per (name, file, line): Studio's
# Database counts a name's distinct lines ("Used in N lines").

USE_KINDS = ("character_use", "image_use", "audio_use", "variable_use")
_USE_MAX_DEPTH = 8                              # nested node data walked per statement
_USES_CACHE: list[tuple[Program, dict[str, list[NameRow]]]] = []   # the last program's rows


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


def _character_call(define: Define) -> ast.Call | None:
    """A define's value when it is a ``Character(...)`` call (read, never run)."""
    tree = _python_tree(define.value.source.strip(), "eval")
    body = getattr(tree, "body", None)
    if isinstance(body, ast.Call) and isinstance(body.func, ast.Name) \
            and body.func.id == "Character":
        return body
    return None


class _UseWalk:
    """Collects the use rows of one program: who speaks, what is shown, what plays, and which
    story variables code, conditions and ``{var=…}`` tags name."""

    def __init__(self, program: Program) -> None:
        self.rows: dict[str, dict[NameRow, None]] = {kind: {} for kind in USE_KINDS}
        self.variables = program.default_names
        self.characters: set[str] = set()
        for define in program.defines:
            call = _character_call(define)
            if call is None:
                continue
            self.characters.add(define.name)
            ref, line = _where(define)
            for keyword in call.keywords:
                value = keyword.value
                if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                    continue
                if keyword.arg == "blip":
                    self.add("audio_use", value.value, ref, line)
                elif keyword.arg == "name_from" and value.value in self.variables:
                    self.add("variable_use", value.value, ref, line)
        for stmt in _statements(program):
            self.node(stmt, stmt.file.ref, stmt.line, 0)

    def add(self, kind: str, name: str | None, ref: str | None, line: int | None) -> None:
        if name:
            self.rows[kind][(name, ref, line)] = None

    def python(self, py: PyCode, ref: str) -> None:
        tree = _python_tree(py.source, py.mode)
        if tree is None:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if node.id in self.variables:
                    self.add("variable_use", node.id, ref, py.line)
                elif node.id in self.characters:
                    self.add("character_use", node.id, ref, py.line)

    def node(self, obj: object, ref: str, line: int, depth: int) -> None:
        if depth > _USE_MAX_DEPTH or obj is None or isinstance(obj, (str, int, float, bool)):
            return
        if isinstance(obj, PyCode):
            self.python(obj, ref)
            return
        if isinstance(obj, TaggedText):
            for piece in obj.pieces:
                name = getattr(piece, "name", None) if isinstance(piece, VarMark) \
                    else getattr(piece, "var", None) if isinstance(piece, NameMark) else None
                if name in self.variables:
                    self.add("variable_use", name, ref, line)
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
                self.add("image_use", " ".join((obj.speaker, *obj.attributes)), ref, line)
        elif isinstance(obj, (Scene, Show)):
            self.add("image_use", obj.image, ref, line)
        elif isinstance(obj, (PlayAudio, QueueMusic, StopAudio, Voice)):
            self.add("audio_use", obj.audio_file, ref, line)
        for item in fields(obj):
            if item.name not in ("file", "sid", "label", "path"):
                self.node(getattr(obj, item.name, None), ref, line, depth + 1)


def _story_uses(program: Program) -> dict[str, list[NameRow]]:
    if not _USES_CACHE or _USES_CACHE[0][0] is not program:
        walk = _UseWalk(program)
        _USES_CACHE[:] = [(program, {kind: list(rows) for kind, rows in walk.rows.items()})]
    return _USES_CACHE[0][1]


def _uses(kind: str) -> Callable[[CheckContext], Iterable[NameRow] | None]:
    def rows(ctx: CheckContext) -> Iterable[NameRow] | None:
        if ctx.program is None:
            return None
        return _story_uses(ctx.program)[kind]
    return rows


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
    "sprite": _sprite_names,                # F28: sprite tags (effect jitter <sprite>)
    "variable": _variable_names,            # F47: each default, at its line
    "character_use": _uses("character_use"),   # F47: each line a character speaks or is named
    "image_use": _uses("image_use"),        # F47: each scene/show line (and say attributes)
    "audio_use": _uses("audio_use"),        # F47: each audio line, and Character blips
    "variable_use": _uses("variable_use"),  # F47: each line whose code or text names a default
}


# --- The check (04 §7.1 steps 3-10) ----------------------------------------------------------

class CheckJob:
    """One check of ``paths``: config, load, launch (``launch=False``: skipped, 07 I-1),
    names, graph; every event goes to ``emit`` as a dict, ``done`` last."""

    def __init__(self, paths: GamePaths, emit: Emit, *, launch: bool = True,
                 clock: Callable[[], float] = time.perf_counter) -> None:
        self.paths = paths
        self.emit = emit
        self.launch = launch
        self._clock = clock

    def run(self) -> None:
        started = self._clock()
        paths = self.paths
        try:
            GamePaths.for_game(paths.root)               # the folder is still there
        except UserFacingError as error:
            emit_results(self.emit, [_error_item(error, "load")], 1, {}, None,
                         self._clock() - started)
            return
        problems: list[dict] = []
        total = 0

        config_result = load_config(paths)
        config = config_result.config
        for error in config_result.errors:
            problems.append(_config_item(error))
        problems += [_config_warning(text) for text in config_result.warnings]
        total += len(config_result.errors) + len(config_result.warnings)

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
        total += (max(loaded.error_count, len(loaded.errors)) + len(loaded.warnings)
                  + max(loaded.todo_count, len(loaded.todos)))
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
            total += max(launch.error_count, len(launch.errors)) + len(launch.warnings)

        context = CheckContext(paths, config, program, launch, namespace)
        names = self._names(context)
        emit_results(self.emit, problems, total, names, program, self._clock() - started)

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
    emit({"v": REPORT_VERSION, "event": "done", "loaded": program is not None,
          "problems": total, "seconds": round(max(seconds, 0.0), 3),
          "name_totals": name_totals, "link_total": link_total})


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
        paths = OverlayPaths(root, overlay=files) if files else GamePaths(root)
        CheckJob(paths, emit, launch=launch).run()
        return EXIT_DONE
    finally:
        if out is not None:
            out.flush()


__all__ = ["CheckContext", "CheckJob", "NAME_SOURCES", "OverlayError", "OverlayPaths",
           "check_command", "chunk_event", "emit_results", "encode_event", "problem_item",
           "read_overlay"]

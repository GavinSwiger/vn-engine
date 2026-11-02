"""Loading a story: discovery, includes, limits, and the sliced load job (F02
``04-technical.md`` §7.1, §7.6.1, §7.6.2, §5.1, §7.9).

``StoryLoader`` wraps one generator, the load job. ``step(budget_s)`` advances it until about
``budget_s`` has passed (checked at yield points), so the frame loop stays responsive during a
long load; ``load_story`` runs it to the end in one go. The job yields after about every
``SCRIPT_YIELD_LINES`` physical lines (``parser.iter_parse_file``), after each file and each
include, between phases, and every ``IDENTITY_YIELD_ITEMS`` items in long loops. Nothing it
produces depends on how the work was sliced (TR-F02-08): the clock only sets slice
boundaries and ``LoadStats.seconds``.

Phases:

1. Discovery (§7.1): ``list_dir("script")`` (E08d / W01), the script-root overlap check
   (SEC-F02-11, E08e), ``walk_files`` (W02b), then ``script/main.vns`` (E05, E08–E09, W01).
2. Breadth-first reading (§7.6.1): pop a file, read and decode it, parse it in slices, then
   resolve its includes in line order (E91–E97, E05, E01a/E01b/E02). Files are deduplicated
   by real path; every file read must lie inside the real script folder. Story limits (E05b,
   E06, E06b–d, E07) stop reading.
3. W02 for ``.vns`` files that were not included (PR-F02-05).
4. The whole-game checks (``04`` §7.6.3, §7.6.4; ``checks.py``): E25/E47, deferred no-text
   lines, E26, E43 with its lazy scan, the start options (E26b/E26c), E70, define order
   (E48/E48b), F03's default checks (E47b, E47c, default order), and W04.
5. With no errors: identities and the ``Program`` (``program.iter_build_program``, step 8).
6. F20: with ``LoadOptions.flowchart`` enabled and no errors, the flowchart's graph
   (``flowgraph.FlowGraphJob``, ``04`` §7.1): ``Program.flowgraph``, E265 (no ``Program``
   then), and on a dev load W150–W153.

Every read goes through ``GamePaths.read_file``; every listing through ``list_dir`` /
``walk_files`` (invariant 9 (a)). Author Python is only compiled, never run.
"""

import contextlib
import gc
import math
import re
import time
from collections import deque
from dataclasses import replace
from collections.abc import Callable, Generator, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, NamedTuple

from engine.core.constants import BUILTIN_POSITIONS, WRITE_ROOT_DIRNAMES
from engine.core.errors import (
    AssetMissing,
    AssetNotFile,
    AssetRefError,
    AssetTooLarge,
    AssetUnreadable,
)
from engine.core.minigame_types import MinigameSig
from engine.core.paths import REASON_OUTSIDE, GamePaths, check_ref
from engine.script import limits
from engine.script.checks import SALVAGE_RE, CheckInput, CheckOutput, iter_checks
from engine.script.diagnostics import Diagnostic, DiagnosticSink, ScriptError, ScriptWarning
from engine.script.flowgraph import FlowGraphJob, FlowOptions
from engine.script.limits import IDENTITY_YIELD_ITEMS
from engine.script.messages import format_message
from engine.script.nodes import Define, Include, Node, ScriptFile
from engine.script.parser import iter_parse_file
from engine.script.program import LoadStats, Program, iter_build_program
from engine.script.pycheck import COMPILE_NAME
from engine.script.source import decode_script
from engine.script.statements import ParseContext
from engine.script.suggest import suggest
from engine.script.words import canonical_name

SCRIPT_DIR = "script"
MAIN_NAME = "main.vns"
MAIN_REF = f"{SCRIPT_DIR}/{MAIN_NAME}"
SCRIPT_SUFFIX = ".vns"

# The folders the script root must never overlap (SEC-F02-11, I-9): the one list in
# engine/core/constants.py (F31 SEC-F31-03), never literals here.
WRITE_ROOT_NAMES: tuple[str, ...] = WRITE_ROOT_DIRNAMES

# SR-F02-69: after one of these, E26, E43, and E70 are skipped and E99 ends the list.
CHECK_SKIPPING_CODES = frozenset((
    "E01b", "E02", "E05", "E05b", "E06", "E06b", "E06c", "E06d", "E07",
    "E08b", "E08c", "E08d", "E08e", "E91", "E92", "E93", "E94", "E97"))
# Story limits (§7.6.1): reading stops, and the whole-game checks run only E25/E47.
STORY_LIMIT_CODES = frozenset(("E05b", "E06", "E06b", "E06c", "E06d", "E07"))

# PR-F02-05 / Q-P2: a file whose case-folded name holds one of these as a whole run of
# letters (or whose stem ends in "~") is a backup and gets no W02.
_SKIPPED_WORDS = frozenset(("copy", "backup", "old", "draft"))
_LETTER_RUN_RE = re.compile(r"[^\W\d_]+")
# §7.6.2: names salvaged from an E01a file (``checks.SALVAGE_RE``), so jumps into it give no
# follow-on errors.


@dataclass(frozen=True)
class LoadOptions:
    """``collect_todos``: keep ``# TODO`` comments for the dev log (PR-F02-43). ``start``
    and ``start_names``: the ``--start`` label and the ``--set`` names (F44 C2), checked at
    load (E26b, E26c). F41 adds ``keep_partial`` (I-7). ``position_names``: the names
    ``at`` may use (F04 SR-F04-13, E120), ``left``, ``center``, ``right`` plus the keys of
    ``config.stage.positions``; any iterable of names, kept as a frozenset. ``dev`` (F19):
    a dev run's load, which also gives the dev-only load warnings (W130); a release run's
    load passes False. ``minigames`` (F23 ``04`` §5.3): the registered minigames' signatures
    by name, from the plugin phase; None (read-only tools, SEC-F23-04(b)) skips the two
    signature checks (E270's unknown name, E271's load forms). ``flowchart`` (F20 ``04``
    §7.1, A12): build the flowchart's graph (load phase 6) with these options; None (tools
    and tests that don't ask for one) or ``enabled = False`` builds none. The app and
    ``vn check`` pass ``FlowOptions.from_config(config.flowchart)``. ``username_fallback``
    (F30 ``04`` §4.1): ``[meta] username_fallback``, copied to ``Program.username_fallback``
    (what ``{username}`` holds in the story); the app and ``vn check`` pass it.
    ``style_names`` (F32 ``04`` §5.1): the ``[style.<name>]`` names ``ui style`` may use
    (E320), copied to ``Program.style_names`` (a restore's W205 check); None (tools and tests
    that read no config) skips E320. The app and ``vn check`` pass ``config.style``'s names."""

    collect_todos: bool = False
    start: str | None = None
    start_names: tuple[str, ...] = ()
    position_names: frozenset[str] = frozenset(BUILTIN_POSITIONS)
    dev: bool = True
    minigames: Mapping[str, MinigameSig] | None = None
    flowchart: FlowOptions | None = None
    username_fallback: str = "friend"                       # F30
    style_names: frozenset[str] | None = None               # F32

    def __post_init__(self) -> None:
        names = self.position_names
        if not isinstance(names, frozenset):
            object.__setattr__(self, "position_names", frozenset(names))
        styles = self.style_names
        if styles is not None and not isinstance(styles, frozenset):
            object.__setattr__(self, "style_names", frozenset(styles))


class Todo(NamedTuple):
    """One ``# TODO`` comment (SR-F02-13)."""

    file: ScriptFile
    line: int
    text: str


@dataclass(frozen=True)
class LoadResult:
    """The outcome of one load (``04`` §4.3). ``program`` is None on errors or with no
    story. ``errors`` are the first ``SCRIPT_MAX_ERRORS`` in sort order; ``error_count``
    counts every error found (E99 is not an error). ``todos`` keeps at most
    ``SCRIPT_TODO_LOG_LIMIT`` entries; ``todo_count`` counts them all."""

    program: Program | None
    no_story: bool
    error_count: int
    errors: tuple[ScriptError, ...]
    checks_skipped: bool
    warnings: tuple[ScriptWarning, ...]
    todos: tuple[Todo, ...]
    stats: LoadStats
    todo_count: int = 0


# --- The whole-game checks (checklist step 7) -------------------------------------------

def _iter_whole_game_checks(inp: CheckInput) -> Generator[None, None, CheckOutput]:
    """The whole-game checks (``checks.py``: ``04`` §7.6.3, §7.6.4, and F44's step 4b), run
    with ``yield from`` so they slice like the rest of the load. Errors go to ``inp.sink``;
    the result holds the define order and the W04 warnings."""
    return (yield from iter_checks(inp))


# --- Helpers ---------------------------------------------------------------------------

def is_skipped_name(ref: str) -> bool:
    """True for a backup-looking file that gets no W02 (PR-F02-05, Q-P2)."""
    name = ref.rsplit("/", 1)[-1]
    stem = name.removesuffix(SCRIPT_SUFFIX)
    if stem.endswith("~"):
        return True
    return any(run in _SKIPPED_WORDS for run in _LETTER_RUN_RE.findall(name.casefold()))


class _Lines:
    """Physical lines of one decoded file, looked up in increasing line order (include
    lines), without splitting the whole text."""

    __slots__ = ("_text", "_line", "_pos")

    def __init__(self, text: str) -> None:
        self._text = text
        self._line = 1
        self._pos = 0

    def get(self, number: int) -> str | None:
        text = self._text
        if number < self._line:
            self._line, self._pos = 1, 0
        while self._line < number:
            end = text.find("\n", self._pos)
            if end < 0:
                return None
            self._pos = end + 1
            self._line += 1
        end = text.find("\n", self._pos)
        return text[self._pos:] if end < 0 else text[self._pos:end]


@dataclass(slots=True)
class _Pending:
    """A file waiting in the reading queue, and the include that found it (read errors
    are reported on that line)."""

    file: ScriptFile
    written: str = ""
    data: bytes | None = None
    source_line: str | None = None                    # the include line, for the report


# --- The load job ----------------------------------------------------------------------

class _Job:
    def __init__(self, paths: GamePaths, options: LoadOptions,
                 clock: Callable[[], float]) -> None:
        self.paths = paths
        self.options = options
        self.clock = clock
        self.sink = DiagnosticSink()
        self.ctx: ParseContext | None = None
        self.warnings: list[ScriptWarning] = []       # W01, W02 and its summary
        self.walk_refs: tuple[str, ...] = ()
        self.walk_truncated = False
        self.script_real: Any = None                  # real path of script/ (a Path)
        self.checks_skipped = False
        self.limit_hit = False
        self.no_story = False
        self.started: float | None = None
        self.files: list[ScriptFile] = []             # read files, reading order
        self.nodes: list[Node] = []                   # their top-level nodes
        self.seen: dict[Any, ScriptFile] = {}         # real path → file (dedup, §7.6.1)
        self.next_order = 0
        self.total_bytes = 0
        self.unincluded: tuple[str, ...] = ()
        self.check_warnings: list[ScriptWarning] = []
        self.program: Program | None = None
        # Decoded text by file order, until finish() has filled in the source lines of
        # the reported errors raised after parsing (E25, E43, E70, …).
        self.texts: dict[int, str] = {}

    # Reporting ---------------------------------------------------------------------------

    def add(self, code: str, file: ScriptFile | None = None, line: int | None = None,
            args: tuple = (), *, whole_file: bool = False,
            source_line: str | None = None) -> None:
        if code in CHECK_SKIPPING_CODES:
            self.checks_skipped = True
        if code in STORY_LIMIT_CODES:
            self.limit_hit = True
        stmt = line if file is not None and not whole_file else None
        self.sink.add(Diagnostic(code, file, line, None, args, whole_file=whole_file,
                                 source_line=source_line, stmt=stmt))

    def warn(self, code: str, args: tuple = ()) -> None:
        self.warnings.append(ScriptWarning(format_message(code, args), code=code))

    def inside(self, real: Any) -> bool:
        """SEC-F02-11: the real path lies inside the real script folder."""
        return real == self.script_real or real.is_relative_to(self.script_real)

    # The job -----------------------------------------------------------------------------

    def run(self) -> Generator[None, None, LoadResult]:
        main = yield from self.discover()
        if main is not None:
            yield from self.read_all(main)
            if not self.limit_hit:
                yield from self.find_unincluded()
            check = yield from _iter_whole_game_checks(CheckInput(
                paths=self.paths, sink=self.sink, collected=self.ctx.collected,
                files=tuple(self.files), nodes=tuple(self.nodes),
                checks_skipped=self.checks_skipped, limit_hit=self.limit_hit,
                unincluded=self.unincluded, start=self.options.start,
                start_names=self.options.start_names, dev=self.options.dev,
                minigames=self.options.minigames))
            self.check_warnings = list(check.warnings)
            yield
            if self.sink.error_count == 0 and not self.checks_skipped:
                self.program = yield from iter_build_program(
                    self.files, self.nodes, defines=check.defines,
                    defaults=check.defaults, started=self.started, clock=self.clock,
                    persistent_reads=check.persistent_reads,                 # F12
                    persistent_writes=check.persistent_writes,
                    flow_marks=check.flow_marks,                              # F20
                    username_fallback=self.options.username_fallback,         # F30
                    style_names=self.options.style_names)                     # F32
                yield from self.flowgraph()
        return self.finish()

    def flowgraph(self) -> Generator[None, None, None]:
        """Load phase 6 (F20): the graph in slices of ``FLOW_STEP_UNITS`` work units."""
        options = self.options.flowchart
        if self.program is None or options is None or not options.enabled:
            return
        job = FlowGraphJob(self.program, options, self.sink, dev=self.options.dev)
        while not job.step():
            yield
        if job.result is None:                          # E265
            self.program = None
            return
        self.program = replace(self.program, flowgraph=job.result)
        self.check_warnings.extend(job.warnings)

    def discover(self) -> Generator[None, None, _Pending | None]:
        """§7.1 and the script-root check. Returns ``main.vns`` read, or None (stop)."""
        paths = self.paths
        try:
            listing = paths.list_dir(SCRIPT_DIR)
        except AssetRefError:
            self.add("E08d", args=(f"{SCRIPT_DIR}/",), whole_file=True)
            return None
        if listing is None:
            # Missing, a file, or "Script/" in the wrong letter case (F01 matches case).
            self.no_story = True
            self.warn("W01")
            return None
        try:
            script_real = paths.resolve(SCRIPT_DIR)
        except (AssetMissing, AssetRefError):          # changed since the listing
            self.no_story = True
            self.warn("W01")
            return None
        overlap = self.write_root_overlap(script_real)
        if overlap is not None:
            self.add("E08e", args=(overlap,), whole_file=True)
            return None
        self.script_real = script_real
        # AC-F02-35: compile()'s attempt to open its file name stays inside script/.
        self.ctx = ParseContext(sink=self.sink, collect_todos=self.options.collect_todos,
                                compile_name=str(script_real / COMPILE_NAME),
                                position_names=frozenset(
                                    canonical_name(n) for n in self.options.position_names),
                                style_names=self.options.style_names)           # F32
        yield
        walk = paths.walk_files(SCRIPT_DIR, suffix=SCRIPT_SUFFIX,
                                max_entries=limits.SCRIPT_WALK_MAX_ENTRIES,
                                max_depth=limits.SCRIPT_WALK_MAX_DEPTH)
        self.walk_refs = walk.refs
        self.walk_truncated = walk.truncated
        yield
        self.started = self.clock()
        main = ScriptFile(MAIN_REF, MAIN_NAME, 0)
        try:
            real = paths.resolve(MAIN_REF)
            if not self.inside(real):
                raise AssetRefError(MAIN_REF, REASON_OUTSIDE)
            data = paths.read_file(MAIN_REF, max_bytes=limits.SCRIPT_FILE_MAX_BYTES)
        except AssetMissing:
            self.main_missing(listing.files)
            return None
        except AssetRefError:
            self.add("E08d", whole_file=True)
            return None
        except AssetNotFile:
            self.add("E08c", whole_file=True)
            return None
        except AssetTooLarge:
            self.add("E05", main, args=(MAIN_REF,), whole_file=True)
            return None
        except AssetUnreadable:
            self.add("E08b", whole_file=True)
            return None
        self.seen[real] = main
        self.next_order = 1
        return _Pending(main, MAIN_NAME, data)

    def write_root_overlap(self, script_real: Any) -> str | None:
        """The first write root (``logs/``, ``saves/``, ``persistent/``, ``characters/``)
        that exists under the game root and lies inside, or contains, the script folder.
        ``GamePaths.write_root``, not ``resolve``: ``check_ref`` refuses write roots, so a
        resolve would always fail and the check would silently stop (SEC-F31-03(b))."""
        for name in WRITE_ROOT_NAMES:
            real = self.paths.write_root(name)
            if real is None:
                continue
            if real == script_real or real.is_relative_to(script_real) \
                    or script_real.is_relative_to(real):
                return name
        return None

    def main_missing(self, names: tuple[str, ...]) -> None:
        """E08 (a close name in ``script/``), E09 (other ``.vns`` files), or W01."""
        close = suggest(MAIN_NAME, [n for n in names if n.endswith(SCRIPT_SUFFIX)])
        if close is not None:
            self.add("E08", args=(close,), whole_file=True)
            return
        if not self.walk_refs:
            self.no_story = True
            self.warn("W01")
            return
        others = [ref.removeprefix(f"{SCRIPT_DIR}/") for ref in self.walk_refs]
        self.add("E09", args=(tuple(others[:limits.SCRIPT_E09_NAMES]), len(others)),
                 whole_file=True)

    # Reading -----------------------------------------------------------------------------

    def read_all(self, main: _Pending) -> Generator[None, None, None]:
        """The breadth-first reading of §7.6.1."""
        queue: deque[_Pending] = deque([main])
        while queue and not self.limit_hit:
            pending = queue.popleft()
            file = pending.file
            data = pending.data if pending.data is not None else self.read_include(pending)
            pending.data = None
            if data is None:
                yield
                continue
            self.total_bytes += len(data)
            if self.total_bytes > limits.SCRIPT_TOTAL_MAX_BYTES:
                self.add("E05b")
                break
            self.files.append(file)
            decoded = decode_script(file.ref, data)
            del data
            if decoded.problem is not None:
                code, args, line = decoded.problem
                if code == "E01a" and decoded.text is not None:
                    lines = _Lines(decoded.text)
                    self.add(code, file, line, args, source_line=lines.get(line or 1))
                    self.texts[file.order] = decoded.text
                    self.salvage(file, decoded.text)
                else:
                    self.add(code, file, None, args, whole_file=True)
                yield
                continue
            text = decoded.text
            assert text is not None
            self.texts[file.order] = text
            nodes = yield from self.parse(file, text)
            if nodes is None:
                break
            self.nodes.extend(nodes)
            yield
            lines = _Lines(text)
            for node in nodes:
                if isinstance(node, Include):
                    found = self.resolve_include(file, node, lines)
                    if found is not None:
                        queue.append(found)
                    if self.limit_hit:
                        break
                    yield

    def parse(self, file: ScriptFile, text: str) -> Generator[None, None, list[Node] | None]:
        """Parse one file in slices, checking the story totals at every slice and at the
        end. None when a total was passed (reading stops)."""
        ctx = self.ctx
        assert ctx is not None
        job = iter_parse_file(file, text, ctx)
        while True:
            try:
                next(job)
            except StopIteration as stop:
                nodes = stop.value
                break
            if self.over_totals():
                job.close()
                return None
            yield
        return None if self.over_totals() else nodes

    def over_totals(self) -> bool:
        """SEC-F02-03: E06b (statements), E06c (Python pieces), E06d (Python characters,
        ``len(PyCode.source)``, I-5), each reported once."""
        ctx = self.ctx
        assert ctx is not None
        if ctx.statement_count > limits.SCRIPT_MAX_STATEMENTS:
            self.add("E06b")
        if ctx.py_pieces > limits.SCRIPT_MAX_PY_PIECES:
            self.add("E06c")
        if ctx.py_chars > limits.SCRIPT_MAX_PY_CHARS:
            self.add("E06d")
        return self.limit_hit

    def salvage(self, file: ScriptFile, text: str) -> None:
        """§7.6.2: label and define names of an E01a file, from its replacement decode."""
        assert self.ctx is not None
        collected = self.ctx.collected
        line, pos = 1, 0
        for match in SALVAGE_RE.finditer(text):
            line += text.count("\n", pos, match.start())
            pos = match.start()
            label, define = match.groups()
            table = collected.label_defs if label is not None else collected.define_defs
            table.setdefault(canonical_name(label or define), []).append((file, line))

    def read_include(self, pending: _Pending) -> bytes | None:
        """Read a queued include; a problem is reported on the include line (or, for E05,
        as the whole-file error of the included file)."""
        file = pending.file
        assert file.included_by is not None
        parent, line = file.included_by
        written = pending.written
        source = pending.source_line
        try:
            return self.paths.read_file(file.ref, max_bytes=limits.SCRIPT_FILE_MAX_BYTES)
        except AssetTooLarge:
            self.add("E05", file, args=(file.ref,), whole_file=True)
        except AssetNotFile:
            if self.is_folder(file.ref):
                self.add("E94", parent, line, (written,), source_line=source)
            else:
                self.add("E97", parent, line, (written, file.ref), source_line=source)
        except AssetUnreadable:
            self.add("E97", parent, line, (written, file.ref), source_line=source)
        except AssetRefError:
            self.add("E92", parent, line, (written, None), source_line=source)
        except AssetMissing:
            self.add("E91", parent, line, (written, file.ref, None), source_line=source)
        return None

    def is_folder(self, ref: str) -> bool:
        try:
            return self.paths.list_dir(ref) is not None
        except AssetRefError:
            return False

    def ref_exists(self, ref: str) -> bool:
        try:
            self.paths.resolve(ref)
        except (AssetMissing, AssetRefError):
            return False
        return True

    def resolve_include(self, file: ScriptFile, node: Include,
                        lines: _Lines) -> _Pending | None:
        """§7.6.1 include resolution, first failure wins. Returns a new file to read, or
        None (already loaded, or an error was reported)."""
        path = node.path
        ref = f"{SCRIPT_DIR}/{path}"
        line = node.line

        def fail(code: str, *args: object) -> None:
            self.add(code, file, line, tuple(args), source_line=lines.get(line))

        try:
            check_ref(path)
        except AssetRefError as exc:
            fail("E92", path, None if exc.reason == REASON_OUTSIDE else exc.reason)
            return None
        if not path.endswith(SCRIPT_SUFFIX):
            if not path.lower().endswith(SCRIPT_SUFFIX) and self.is_folder(ref):
                fail("E94", path)
            else:
                fail("E93", path)
            return None
        try:
            real = self.paths.resolve(ref)
        except AssetMissing as exc:
            fail("E91", path, ref, self.missing_suggestion(path, ref, exc))
            return None
        except AssetRefError as exc:
            fail("E92", path, None if exc.reason == REASON_OUTSIDE else exc.reason)
            return None
        if not self.inside(real):
            fail("E92", path, None)
            return None
        known = self.seen.get(real)
        if known is not None:
            node.target = known
            return None
        if self.next_order >= limits.SCRIPT_MAX_FILES:
            self.add("E06")
            return None
        depth = file.depth + 1
        if depth > limits.SCRIPT_MAX_INCLUDE_DEPTH:
            self.add("E07", args=(ref,))
            return None
        new = ScriptFile(ref, path, self.next_order, depth, (file, line))
        self.next_order += 1
        self.seen[real] = new
        node.target = new
        return _Pending(new, path, source_line=lines.get(line))

    def missing_suggestion(self, path: str, ref: str, exc: AssetMissing) -> str | None:
        """E91's variants (§7.6.1): (a) ``script/…`` whose rest exists → None (the message
        then explains that paths start inside the script folder); (b) F01's suggestion when
        it differs only in letter case; (c) a close file name in the same folder; else
        None."""
        prefix = f"{SCRIPT_DIR}/"
        if path.startswith(prefix) and self.ref_exists(prefix + path.removeprefix(prefix)):
            return None
        found = exc.suggestion
        if found is not None and found.casefold() == ref.casefold():
            return found.removeprefix(prefix)
        parent, _, last = path.rpartition("/")
        try:
            listing = self.paths.list_dir(prefix + parent if parent else SCRIPT_DIR)
        except AssetRefError:
            listing = None
        if listing is None:
            return None
        close = suggest(last, listing.files)
        if close is None:
            return None
        return f"{parent}/{close}" if parent else close

    # After reading -----------------------------------------------------------------------

    def find_unincluded(self) -> Generator[None, None, None]:
        """The walked ``.vns`` files that were not loaded (by real path, inside the script
        folder), and W02 for the first ``SCRIPT_UNINCLUDED_WARN_LIMIT`` that don't look like
        backups, then one summary line (PR-F02-05). Logged also when the load has errors."""
        unincluded: list[str] = []
        for index, ref in enumerate(self.walk_refs, 1):
            if index % IDENTITY_YIELD_ITEMS == 0:
                yield
            try:
                real = self.paths.resolve(ref)
            except (AssetMissing, AssetRefError):
                continue
            if real in self.seen or not self.inside(real):
                continue
            unincluded.append(ref)
        self.unincluded = tuple(unincluded)
        warned = [ref for ref in unincluded if not is_skipped_name(ref)]
        cap = limits.SCRIPT_UNINCLUDED_WARN_LIMIT
        for ref in warned[:cap]:
            self.warn("W02", (ref,))
        if len(warned) > cap:
            self.warn("W02s", (len(warned) - cap,))

    def fill_source_lines(self) -> None:
        """The whole-game checks know a file and a line but not its text: give each
        reported line error without one its source line (AC-F02-43). ``kept()`` is in
        reading order, so one forward ``_Lines`` per file finds them all."""
        texts, self.texts = self.texts, {}
        lines: _Lines | None = None
        order = -1
        for diag in self.sink.kept():
            file = diag.file
            if (diag.source_line is not None or file is None or diag.whole_file
                    or not diag.line):
                continue
            if file.order != order:
                text = texts.get(file.order)
                lines = None if text is None else _Lines(text)
                order = file.order
            if lines is not None:
                diag.source_line = lines.get(diag.line)

    def finish(self) -> LoadResult:
        self.fill_source_lines()
        ctx = self.ctx
        warnings = list(self.warnings)
        if ctx is not None:
            warnings.extend(ctx.warnings.finish())
        if self.walk_truncated:
            warnings.append(ScriptWarning(format_message("W02b"), code="W02b"))
        warnings.extend(self.check_warnings)
        todos: tuple[Todo, ...] = ()
        todo_count = 0
        if ctx is not None:
            todos = tuple(Todo(*item) for item in ctx.collected.todos)
            todo_count = ctx.collected.todo_count
        program = self.program
        if program is not None:
            stats = program.stats
        else:
            seconds = 0.0 if self.started is None else max(0.0, self.clock() - self.started)
            stats = LoadStats(files=len(self.files), labels=0,
                              statements=ctx.statement_count if ctx is not None else 0,
                              words=0, seconds=seconds)
        return LoadResult(program=program, no_story=self.no_story,
                          error_count=self.sink.error_count, errors=self.sink.errors(),
                          checks_skipped=self.checks_skipped, warnings=tuple(warnings),
                          todos=todos, stats=stats, todo_count=todo_count)


# --- Public interface (§5.1) -------------------------------------------------------------

class StoryLoader:
    """A story load that runs in slices inside the frame loop (§7.9)."""

    def __init__(self, paths: GamePaths, options: LoadOptions = LoadOptions(), *,
                 clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._job = _Job(paths, options, clock)
        self._steps: Iterator[None] | None = self._job.run()
        self._result: LoadResult | None = None

    @property
    def done(self) -> bool:
        return self._result is not None

    @property
    def result(self) -> LoadResult:
        if self._result is None:
            raise AssertionError("the story load is not done; call step() until it is")
        return self._result

    @property
    def nodes(self) -> tuple[Node, ...]:
        """Every read file's top-level nodes in reading order (after ``done``; for tests
        and tools that need the ``Include`` nodes, which ``Program`` does not keep)."""
        self.result                                    # AssertionError before done
        return tuple(self._job.nodes)

    def step(self, budget_s: float) -> bool:
        """Advance until about ``budget_s`` seconds have passed (checked at yield points)
        or the load is done; returns ``done``. ``step(0.0)`` always makes progress, and
        results never depend on how the work was sliced.

        Two things keep a slice near ``budget_s`` (F02 Step 11, AC-F02-63):

        - Python's cyclic garbage collector is paused for the step (``_gc_paused``): a full
          collection over a large story's growing tree takes 50–150 ms, which would land
          inside a slice and stretch its frame past 0.1 s.
        - The slice ends early when the next unit of work, guessed as long as the last one,
          would end past the deadline: units (512 lines, a file, 2,000 items) take up to
          about 25 ms, so ending at the first yield past the deadline overshot by that
          much."""
        steps = self._steps
        if steps is None:
            return True
        clock = self._clock
        with _gc_paused():
            now = clock()
            deadline = now + budget_s
            while True:
                began = now
                try:
                    next(steps)
                except StopIteration as stop:
                    self._result = stop.value
                    self._steps = None
                    return True
                now = clock()
                if now + (now - began) >= deadline:
                    return False


@contextlib.contextmanager
def _gc_paused() -> Iterator[None]:
    """Pause the cyclic garbage collector for one ``step`` and restore it afterwards, also on
    an exception, so no state outlives the call: between slices the frame loop runs with the
    collector as it was (F02 Step 11, AC-F02-63).

    On the way out, the objects the step created are moved to the oldest generation without
    a collection (``gc.freeze()`` then ``gc.unfreeze()``, two constant-time list moves), so
    the next young collection doesn't scan them and they don't count toward the next full
    collection. Loading makes no cyclic garbage (measured: a load with the collector off
    leaves 0 unreachable objects, realistic and hostile corpora alike), so pausing costs no
    memory.

    ``gc.unfreeze()`` releases every frozen object, so the move runs only while nothing is
    frozen or the frozen set is the one this module saw at import: CPython 3.12's few hundred
    immortal start-up tuples, released harmlessly (CPython's own ``test_gc`` does the same).
    While anything else keeps objects frozen, the move is skipped. The collector is left
    alone when it was already off (the caller owns it)."""
    if not gc.isenabled():
        yield
        return
    gc.disable()
    try:
        yield
    finally:
        if gc.get_freeze_count() in (0, _FROZEN_AT_IMPORT):
            gc.freeze()
            gc.unfreeze()
        gc.enable()


_FROZEN_AT_IMPORT = gc.get_freeze_count()


def load_story(paths: GamePaths, options: LoadOptions = LoadOptions(), *,
               clock: Callable[[], float] = time.perf_counter) -> LoadResult:
    """Run a ``StoryLoader`` to completion. Never raises for any file content
    (PR-F02-35)."""
    loader = StoryLoader(paths, options, clock=clock)
    while not loader.step(math.inf):
        pass
    return loader.result


__all__ = ["CheckInput", "CheckOutput", "LoadOptions", "LoadResult", "StoryLoader", "Todo",
           "is_skipped_name", "load_story"]

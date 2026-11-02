"""Loading minigame plugins from the real ``game/minigames/`` (F23 ``04`` §7.10; ADR-0009).

Why this module exists: a plugin is Python from the game folder, so how it is found and
imported decides what code can run. ``PluginLoadJob`` reads only the real files of one real
folder through ``GamePaths`` (no link is followed, contained or not: SEC-F23-01), applies one
ASCII name rule on every OS (SEC-F23-02), and serves the sources it read to Python through
``PluginFinder``, a finder at ``sys.meta_path[0]`` that answers every ``_vn_minigames.*`` name
from memory and refuses unknown ones before any other finder runs (SEC-F23-03). Sources are
strict UTF-8 text compiled in memory with ``dont_inherit=True`` under ``<minigames/…>`` names;
``linecache`` is seeded from the text read, so tracebacks show lines without opening a file.
Nothing is written (no ``__pycache__``), and ``sys.path``, ``sys.path_hooks``, and
``sys.path_importer_cache`` are never touched.

The job's only inputs are ``GamePaths`` and constants (SEC-F23-04 (a)): no config key, save,
persistent value, script text, environment variable, or start option names, adds, or skips
a plugin. It runs on the main thread, one file read or one module run per ``step()``, before
F02's load (the plugin phase in ``app/loading.py``, step 3b). Every unit's top level and every
``register`` run inside the F03 guard, so the watchdog stops a stuck plugin.

Bounds: 64 units, 1 MiB per file, 64 files and depth 3 per package, 8 MiB of source, 256
registrations; over any of them is E273 G and nothing more loads.
"""

import hashlib
import importlib
import importlib.abc
import linecache
import logging
import re
import sys
import threading
import traceback
import types
from collections.abc import Generator, Mapping
from dataclasses import dataclass
from importlib.machinery import ModuleSpec
from types import TracebackType

from engine.core.errors import AssetMissing, AssetNotFile, AssetRefError, AssetTooLarge, \
    AssetUnreadable
from engine.core.logsetup import get_logger
from engine.core.minigame_types import MinigameSig
from engine.core.paths import DirListing, GamePaths, NotReal
from engine.core.redact import echo
from engine.minigames import api, bundled, messages
from engine.minigames.registry import (
    ENGINE_SOURCE,
    Collector,
    DeclarationError,
    PluginLoadError,
    Registry,
    name_problem,
)
from engine.runtime import limits
from engine.runtime.errors import python_text_allowed
from engine.runtime.guard import NO_GUARD, AuthorCodeGuard

PREFIX = "_vn_minigames"
FOLDER = "minigames"
MAX_UNITS = 64
MAX_FILE_BYTES = 1 << 20
MAX_TOTAL_BYTES = 8 << 20
MAX_PACKAGE_FILES = 64
MAX_PACKAGE_DEPTH = 3
MAX_ERRORS = 50

_BOM = b"\xef\xbb\xbf"
_BIDI_RE = re.compile("[‪-‮⁦-⁩]")
_NEWLINE_RE = re.compile(r"\r\n?|\n")
_SINGLE_QUOTED = re.compile(r"(?<!\w)'([^'\n]*)'(?!\w)")


# --- The import system (SEC-F23-03) -------------------------------------------------------------

@dataclass(frozen=True)
class Source:
    """One pre-read plugin module: its name under the prefix, its ``<minigames/…>`` origin
    (also the code filename and the ``linecache`` key), and its text."""
    module: str
    origin: str
    text: str
    package: bool


def _lines(text: str) -> list[str]:
    """``text`` split as Python reads a file (only ``\\n``, ``\\r\\n``, ``\\r`` end a line),
    each line ending in ``\\n``, as ``linecache`` stores them."""
    normal = _NEWLINE_RE.sub("\n", text)
    lines = [line + "\n" for line in normal.split("\n")]
    if normal.endswith("\n"):
        lines.pop()
    return lines


class PluginFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """The finder and loader of ``_vn_minigames.*`` (at ``sys.meta_path[0]``). Every spec
    has ``origin`` ``<minigames/…>``, ``cached`` None, and ``has_location`` False; packages
    have an empty ``submodule_search_locations``, so no ``__path__`` names a folder and the
    path finder never searches one."""

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}

    def add(self, source: Source) -> None:
        self._sources[source.module] = source
        linecache.cache[source.origin] = (len(source.text), None, _lines(source.text),
                                          source.origin)

    def modules_of(self, module: str) -> list[str]:
        return [name for name in self._sources
                if name == module or name.startswith(module + ".")]

    @staticmethod
    def _spec(name: str, loader: "PluginFinder", origin: str, package: bool) -> ModuleSpec:
        spec = ModuleSpec(name, loader, origin=origin, is_package=package)
        spec.has_location = False
        spec.cached = None
        if package:
            spec.submodule_search_locations = []
        return spec

    def find_spec(self, fullname, path=None, target=None):
        if fullname == PREFIX:
            return self._spec(PREFIX, self, "<minigames>", True)
        if not fullname.startswith(PREFIX + "."):
            return None
        source = self._sources.get(fullname)
        if source is None:
            # Raised, not None: no other finder may answer a name under the prefix.
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return self._spec(fullname, self, source.origin, source.package)

    def create_module(self, spec):
        return None

    def exec_module(self, module) -> None:
        source = self._sources.get(module.__name__)
        if source is None:                       # the root package: nothing to run
            return
        code = compile(source.text, source.origin, "exec", dont_inherit=True)
        exec(code, module.__dict__)


def install_import_system(finder: PluginFinder) -> None:
    """Forget an earlier load's ``_vn_minigames*`` modules and finder (F39's reload re-runs
    the loader), create the ``_vn_minigames`` package, and put ``finder`` first."""
    for name in [n for n in sys.modules if n == PREFIX or n.startswith(PREFIX + ".")]:
        del sys.modules[name]
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, PluginFinder)]
    sys.meta_path.insert(0, finder)
    root = types.ModuleType(PREFIX)
    root.__spec__ = PluginFinder._spec(PREFIX, finder, "<minigames>", True)
    root.__loader__ = finder
    root.__package__ = PREFIX
    root.__path__ = []
    sys.modules[PREFIX] = root


# --- Results -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PluginLoadResult:
    registry: Registry
    errors: tuple[PluginLoadError, ...]       # the first MAX_ERRORS, in the order found
    error_count: int

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def signatures(self) -> Mapping[str, MinigameSig]:
        return self.registry.signatures()


@dataclass(frozen=True)
class _Unit:
    ref: str            # "minigames/a.py" or "minigames/c/" (what messages show)
    path: str           # GamePaths ref: "minigames/a.py" or "minigames/c"
    module: str         # "_vn_minigames.a"
    package: bool


class _Stop(Exception):
    """A bound was crossed: nothing more loads."""


def _plugin_ref(filename: object) -> str | None:
    if type(filename) is str and filename.startswith("<minigames/") and filename.endswith(">"):
        return filename[1:-1]
    return None


def _last_plugin_frame(tb: TracebackType | None) -> tuple[str | None, int | None]:
    file = line = None
    while tb is not None:
        ref = _plugin_ref(tb.tb_frame.f_code.co_filename)
        if ref is not None:
            file, line = ref, tb.tb_lineno
        tb = tb.tb_next
    return file, line


# --- The job ---------------------------------------------------------------------------------------

class PluginLoadJob:
    """``step()`` does one unit of work (one file read or one module run) and returns True
    when done; ``result`` is then set. Its inputs are ``GamePaths``, the guard, ``dev``, and
    the log only (SEC-F23-04 (a))."""

    def __init__(self, paths: GamePaths, guard: AuthorCodeGuard = NO_GUARD, *, dev: bool,
                 log: logging.Logger | None = None) -> None:
        self.paths = paths
        self.guard = guard
        self.dev = dev
        self.log = log if log is not None else get_logger("plugin")
        self.registry = Registry(main_thread=threading.get_ident())
        self.finder = PluginFinder()
        self._errors: list[PluginLoadError] = []
        self._error_count = 0
        self._total_bytes = 0
        self._result: PluginLoadResult | None = None
        self._job = self._run()

    @property
    def result(self) -> PluginLoadResult:
        if self._result is None:
            raise AssertionError("the plugin phase is not done; call step() until it is")
        return self._result

    def step(self) -> bool:
        if self._result is not None:
            return True
        try:
            next(self._job)
            return False
        except StopIteration:
            pass
        api._set_registry(None)
        self._result = PluginLoadResult(self.registry, tuple(self._errors), self._error_count)
        return True

    def run(self) -> PluginLoadResult:
        """Step to the end (headless and tests)."""
        while not self.step():
            pass
        return self.result

    # --- Reporting ----------------------------------------------------------------------

    def _add(self, error: PluginLoadError) -> None:
        self._error_count += 1
        if len(self._errors) < MAX_ERRORS:
            self._errors.append(error)

    def _g(self, message: str, code: str = "E273") -> None:
        self._add(PluginLoadError(message, code=code))

    def _warn(self, code: str, text: str) -> None:
        if self.dev:
            self.log.warning("%s", text, extra={"code": code})

    def _log_trace(self, error: PluginLoadError, trace: str) -> None:
        """The error with its traceback (already formatted inside the guard) at ERROR: the
        error screen shows no traceback, the log has it."""
        if not self.log.isEnabledFor(logging.ERROR):
            return
        record = self.log.makeRecord(self.log.name, logging.ERROR, __file__, 0, "%s",
                                     (error.format(),), None)
        record.exc_text = trace
        self.log.handle(record)
        error.logged = True

    # --- The phase ----------------------------------------------------------------------

    def _run(self) -> Generator[None, None, None]:
        install_import_system(self.finder)
        api._set_registry(self.registry)
        yield
        try:
            for cls in bundled.BUNDLED:
                self._register_bundled(cls)
            yield
            units = yield from self._discover()
            if len(units) > MAX_UNITS:
                raise _Stop(messages.E273_BOUND)
            for unit in units:
                yield from self._load(unit)
        except _Stop as stop:
            self._g(str(stop))

    def _register_bundled(self, cls: type) -> None:
        with self.registry.collecting(ENGINE_SOURCE) as collector:
            try:
                api.register(cls)
            except DeclarationError as error:
                self._add(PluginLoadError(error.message, code=error.code))
                return
        self._commit(collector, None)

    def _omitted(self, base: str, listing: DirListing) -> None:
        for name in listing.omitted:
            ref = f"{base}/{name}"
            text = messages.w163_not_regular(ref) if name in listing.special \
                else messages.w163_link(ref)
            self._warn("W163", text)

    def _discover(self) -> Generator[None, None, list[_Unit]]:
        """§7.10 steps 1–2: the real folder, then its units in code-point order."""
        found = self.paths.real_dir(FOLDER)
        if isinstance(found, NotReal):
            if found.kind == "missing":
                if found.other_case is not None:
                    self._warn("W164", messages.w164_wrong_case(found.other_case))
            else:
                self._g(messages.E273_NOT_A_REAL_FOLDER)
            return []
        listing = self.paths.list_real(FOLDER)
        if listing is None:
            self._g(messages.E273_NOT_A_REAL_FOLDER)
            return []
        self._omitted(FOLDER, listing)
        files = set(listing.files)
        units: list[_Unit] = []
        for name in sorted((*listing.files, *listing.dirs)):
            if name.startswith(("_", ".")):
                continue                                     # __pycache__, _x.py: unread
            ref = f"{FOLDER}/{name}"
            if name in files:
                if not name.endswith(".py"):
                    continue                                 # .pyc, .pyd, .so, .zip, .pth
                stem = name[:-3]
                problem = name_problem(stem)
                if problem is not None:
                    self._g(messages.e273_reserved_file_name(ref) if problem == "reserved"
                            else messages.e273_bad_file_name(ref))
                    continue
                units.append(_Unit(ref, ref, f"{PREFIX}.{stem}", False))
            elif name_problem(name) is None:
                inner = self.paths.list_real(ref)
                if inner is None:
                    continue
                if "__init__.py" not in inner.files:
                    self._warn("W161", messages.w161_registers_nothing(ref + "/"))
                    continue
                units.append(_Unit(ref + "/", ref, f"{PREFIX}.{name}", True))
        yield
        return units

    def _package_files(self, unit: _Unit) -> list[tuple[str, str, bool]]:
        """(GamePaths ref, module, is package) of every source in a package, ``__init__``
        first in each folder (§7.10 step 3). Listing only; nothing is read here."""
        found: list[tuple[str, str, bool]] = []
        pending = [(unit.path, unit.module, 1)]
        while pending:
            path, module, depth = pending.pop(0)
            listing = self.paths.list_real(path)
            if listing is None or "__init__.py" not in listing.files:
                continue                                     # a sub-folder that isn't a package
            self._omitted(path, listing)
            found.append((f"{path}/__init__.py", module, True))
            files = set(listing.files)
            for name in sorted((*listing.files, *listing.dirs)):
                if name.startswith(("_", ".")):
                    continue
                ref = f"{path}/{name}"
                if name in files:
                    if not name.endswith(".py"):
                        continue
                    stem = name[:-3]
                    problem = name_problem(stem)
                    if problem is not None:
                        self._g(messages.e273_reserved_file_name(ref) if problem == "reserved"
                                else messages.e273_bad_file_name(ref))
                        return []
                    found.append((ref, f"{module}.{stem}", False))
                elif name_problem(name) is None:
                    if depth + 1 > MAX_PACKAGE_DEPTH:
                        raise _Stop(messages.e273_bound_package(unit.ref))
                    pending.append((ref, f"{module}.{name}", depth + 1))
            if len(found) > MAX_PACKAGE_FILES:
                raise _Stop(messages.e273_bound_package(unit.ref))
        return found

    def _read(self, ref: str) -> bytes | None:
        """One file through ``GamePaths`` (``regular=True``): read once; these bytes are the
        bytes compiled. A link or special file at read time is W163 (G1(a))."""
        try:
            data = self.paths.read_file(ref, max_bytes=MAX_FILE_BYTES, regular=True)
        except AssetNotFile:
            self._warn("W163", messages.w163_not_regular(ref))
            return None
        except AssetTooLarge:
            raise _Stop(messages.E273_BOUND) from None
        except (AssetUnreadable, AssetMissing, AssetRefError):
            self._g(messages.e273_unreadable(ref))
            return None
        self._total_bytes += len(data)
        if self._total_bytes > MAX_TOTAL_BYTES:
            raise _Stop(messages.E273_BOUND)
        return data

    def _decode(self, ref: str, data: bytes) -> str | None:
        """Strict UTF-8, a leading BOM dropped (SEC-F23-03 (e)); W165 for bidi controls."""
        try:
            text = data.removeprefix(_BOM).decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            self._g(messages.e273_not_utf8(ref))
            return None
        match = _BIDI_RE.search(text)
        if match is not None:
            line = len(_NEWLINE_RE.findall(text, 0, match.start())) + 1
            self._warn("W165", messages.w165_bidi(ref, line))
        return text

    def _load(self, unit: _Unit) -> Generator[None, None, None]:
        if unit.package:
            files = self._package_files(unit)
            if not files:
                return
        else:
            files = [(unit.path, unit.module, False)]
        digest = hashlib.sha256()
        size = 0
        sources: list[Source] = []
        for ref, module, package in files:
            data = self._read(ref)
            yield
            if data is None:
                return
            text = self._decode(ref, data)
            if text is None:
                return
            if unit.package:
                digest.update(ref.encode("utf-8") + b"\0")
            digest.update(data)
            size += len(data)
            sources.append(Source(module, f"<{ref}>", text, package))
        for source in sources:
            self.finder.add(source)
        collector = self._execute(unit)
        yield
        if collector is None:
            return
        apis = sorted({entry.api for entry in collector.entries}) or [messages.ENGINE_API]
        self.log.info("%s", messages.info_loaded(unit.ref, size, digest.hexdigest()[:12],
                                                 ", ".join(apis)))
        self._commit(collector, unit.ref)

    def _commit(self, collector: Collector, unit: str | None) -> None:
        if unit is not None and not collector.entries:
            self._warn("W161", messages.w161_registers_nothing(unit))
        for outcome in self.registry.commit(collector):
            if outcome.error is not None:
                self._add(outcome.error)
            elif outcome.replaced is not None and unit is not None:
                name = outcome.replaced.name
                self.log.info("%s", messages.info_replaced(unit, name))
                self._warn("W160", messages.w160_replaces(unit, name))

    # --- Running a unit's top level (§7.10 step 7) ---------------------------------------

    def _execute(self, unit: _Unit) -> Collector | None:
        """Import the unit's top module under the guard. Returns the collector on success;
        on failure adds the E273 form, logs the traceback, and forgets the unit's modules."""
        guard = self.guard
        error: BaseException | None = None
        with self.registry.collecting(unit.ref) as collector:
            try:
                guard.enter()
                try:
                    importlib.import_module(unit.module)
                finally:
                    guard.exit()
            except KeyboardInterrupt as e:
                if not guard.consume_fired():
                    raise
                error = e
            except BaseException as e:            # SystemExit from a plugin's top level too
                error = e
        if error is None and not collector.errors:
            return collector
        self._forget(unit)
        if self.registry.bound_hit:
            raise _Stop(messages.E273_BOUND_REGISTRATIONS)
        if error is None or isinstance(error, DeclarationError) and collector.errors:
            first = collector.errors[0]
            self._add(self._declaration_error(first, unit))
            return None
        trace = self._trace(error)
        problem = self._failure(error, unit)
        self._add(problem)
        self._log_trace(problem, trace)
        return None

    def _forget(self, unit: _Unit) -> None:
        for name in self.finder.modules_of(unit.module):
            sys.modules.pop(name, None)

    def _declaration_error(self, error: DeclarationError, unit: _Unit) -> PluginLoadError:
        file = error.file or unit.ref
        if error.whole:
            return PluginLoadError(error.message, code=error.code, file=file)
        return PluginLoadError(error.message, code=error.code, file=file, line=error.line)

    def _failure(self, e: BaseException, unit: _Unit) -> PluginLoadError:
        if isinstance(e, KeyboardInterrupt):
            file, line = _last_plugin_frame(e.__traceback__)
            return PluginLoadError(messages.e273_stuck(limits.AUTHOR_CODE_LIMIT_S),
                                   code="E273", file=file or unit.ref, line=line)
        if isinstance(e, SyntaxError):
            file = _plugin_ref(e.filename) or unit.ref
            line = e.lineno if type(e.lineno) is int else None
            detail = self._python_text(e.msg if type(e.msg) is str else None)
            return PluginLoadError(messages.e273_python_mistake(detail), code="E273",
                                   file=file, line=line)
        file, line = _last_plugin_frame(e.__traceback__)
        detail = self._python_text(self._str(e))
        return PluginLoadError(messages.e273_stopped(detail), code="E273",
                               file=file or unit.ref, line=line)

    def _guarded(self, fn):
        """Run ``fn`` (which may call plugin code: ``__str__``, ``__repr__``) under the guard.
        None when it raised or the watchdog stopped it (SEC-F23-08)."""
        guard = self.guard
        try:
            guard.enter()
            try:
                return fn()
            finally:
                guard.exit()
        except KeyboardInterrupt:
            if not guard.consume_fired():
                raise
            return None
        except Exception:
            return None

    def _str(self, e: BaseException) -> str | None:
        text = self._guarded(lambda: str(e))
        return text if type(text) is str else None

    def _trace(self, e: BaseException) -> str:
        """The full traceback, formatted inside the guard (a looping ``__str__`` is
        stopped); falls back to the frames alone."""
        text = self._guarded(lambda: "".join(traceback.format_exception(e)))
        if type(text) is str:
            return text.rstrip("\n")
        frames = "".join(traceback.format_tb(e.__traceback__))
        return f"Traceback (most recent call last):\n{frames}(the error's text could not be read)"

    @staticmethod
    def _python_text(text: str | None) -> str | None:
        """Python's own words, if SR-F03-32 lets them through (``'…'`` → ``"…"``)."""
        if text is None:
            return None
        text = text.strip()
        if not text or not python_text_allowed(text):
            return None
        return echo(_SINGLE_QUOTED.sub(r'"\1"', text)).rstrip(".")


def load_plugins(paths: GamePaths, guard: AuthorCodeGuard = NO_GUARD, *, dev: bool,
                 log: logging.Logger | None = None) -> PluginLoadResult:
    """Run the whole plugin phase at once (headless runs and tests)."""
    return PluginLoadJob(paths, guard, dev=dev, log=log).run()


__all__ = ["FOLDER", "MAX_ERRORS", "MAX_FILE_BYTES", "MAX_PACKAGE_DEPTH", "MAX_PACKAGE_FILES",
           "MAX_TOTAL_BYTES", "MAX_UNITS", "PREFIX", "PluginFinder", "PluginLoadJob",
           "PluginLoadResult", "Source", "install_import_system", "load_plugins"]

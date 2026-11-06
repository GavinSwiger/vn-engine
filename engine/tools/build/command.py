"""``python -m engine build [GAME_DIR] [--out FOLDER] [--zip] [--replace] [--report-to-editor]``:
the build's step machine (F42 ``04-technical.md`` §2, §7.1, §7.3; PR-F42-01, -11, -12, -13,
-16, -17, -22; ``07`` I-6).

Why this module exists: Studio's **Build game…** and the CLI make the same build, so the whole
build is one command run as a child; Studio only reads its report lines. Each step either
finishes or stops the build with one ``B_*`` key (``texts.FAILURES``), and *Save to* only ever
changes when everything succeeded.

**Preflight** (a failure writes nothing to *Save to*): the game folder; ``config.toml`` (with
errors, the check still runs so Problems list them, then ``B_CONFIG``); the Game ID
(``B_NO_ID``); the player runtime (``player.tool_status``: ready with Studio's bundled
player or a cached one; else, in a developer install, PyInstaller to make one, ``B_NO_TOOL``/
``B_TOOL_VERSION``; in Studio's app ``B_NO_RUNTIME``); *Save to* inside the game
folder, holding it, or inside ``<engine root>/engine`` (``B_OUT_INSIDE``, real paths both
ways); an earlier build there (``B_EXISTS`` without ``--replace``; anything else at that name
``B_NAME_TAKEN``); the plugin scan (``B_PLUGIN_IMPORT``); the icon (``BAD_ICON``); the walk
caps (``B_TOO_BIG``); free space, (game + 100 MB) × 2 with the zip (``B_NO_SPACE``). Last,
*Save to* is created if missing and its parent is a real folder (else ``B_NO_FOLDER``;
refused: ``B_CANT_WRITE``).

**Steps** (``build_step`` at each start; ``texts.steps``): check (``checkstep``; errors
``B_ERRORS``) → copy (``sweep_stale``, ``make_staging``, ``copy_game`` into
``<staging>/b/<folder>/game``, then F48's key scan, ``keyscan.scan``) → pack (F66: the
player runtime, ``runtime.ensure_runtime``, which in a developer install makes and caches one
first with PyInstaller as a child, a failure being ``B_PACK_FAILED`` with the redacted tail;
``runtime.copy_runtime`` into the folder with the exe renamed and the network binaries left
out unless a plugin may need them; then the game's icon and version resource on the exe,
``winres.set_resources``) → notices (the runtime's ``licenses/`` must be there and every
bundled DLL have a notice, else ``B_PACK_FAILED``; ``README.txt``,
``_internal/vn-build.json``) → zip (only with ``--zip``) → finish (``install_build``,
``build_done``). No step needs Python or PyInstaller when a runtime is ready.

Any failure, exception or Ctrl+C kills the running grandchild's tree, removes staging in a
``finally``, and reports ``build_failed {code, values, details}`` (``B_CRASHED`` for an
unexpected exception, traceback redacted) or, for Ctrl+C, ``CANCELLED``. Exit 0 built, 1 not
built, 2 when ``GAME_DIR`` isn't a game folder.

Report mode (``--report-to-editor``): one ``VN-EDITOR-REPORT`` line per event on stdout, the
check's ``problems``/``done`` relayed unchanged; event values are names relative to *Save to*
or the game folder, never full paths (SEC-F42-09). CLI: §6.3's lines, full paths on the done
lines.

Defaults (``07`` I-6, the same as Studio's): ``GAME_DIR`` as ``run``'s (the caller passes it);
``--out`` = ``<game parent>/builds`` (D6).

Child-only (the ``build`` handler imports it lazily): ``core``, ``tools.build`` and the
standard library.
"""

import collections
import json
import os
import shutil
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, TextIO

import engine
from engine.core.config import load_config
from engine.core.editorreport import (BUILD_MAX_DETAILS, BUILD_MAX_LEFT_OUT, REPORT_MARKER,
                                      REPORT_VERSION)
from engine.core.errors import UserFacingError
from engine.core.logsetup import redaction_roots
from engine.core.paths import GamePaths, engine_root
from engine.core.redact import RedactRoot
from engine.tools.build import (checkstep, keyscan, names, player, plugins, procs, runtime,
                                spec, texts, tree)
from engine.tools.build.texts import BuildStopped

EXIT_BUILT: Final = 0
EXIT_NOT_BUILT: Final = 1
EXIT_USAGE: Final = 2

BUILDS_FOLDER: Final = "builds"                  # D6: next to the game folder
SPACE_MARGIN: Final = 100 * 1024 * 1024          # PR-F42-22
BUILD_DIR: Final = "b"                           # <staging>/b/<folder>: short (LONG_PATHS)
GAME_DIR: Final = "game"
LICENSES_DIR: Final = player.LICENSES_DIR
README: Final = "README.txt"
RUNTIME_TOKEN: Final = "<runtime>"
IS_WINDOWS: Final = os.name == "nt"


# --- Seams for tests (the defaults are the real ones) ----------------------------------------

def _make_icon(game_root: Path, ref: str | None) -> bytes:
    from engine.tools.build import icon                 # pygame: only when building
    try:
        return icon.make_ico(icon.icon_png(game_root, ref))
    except icon.IconError:
        raise BuildStopped(texts.BAD_ICON) from None


def _unknown_dlls(dll_dirs: list[Path]) -> tuple[str, ...]:
    from engine.tools.build import licenses
    return licenses.unknown_dlls(dll_dirs)


def _set_resources(exe: Path, ico: bytes, version: bytes) -> None:
    from engine.tools.build import winres
    winres.set_resources(exe, ico, version)


def _write_zip(folder: Path, target: Path) -> tuple[int, int]:
    from engine.tools.build import zipout
    return zipout.write_zip(folder, target)


@dataclass
class BuildDeps:
    """Everything the step machine reaches outside itself; tests replace parts of it (a fake
    ``popen`` for the check child and a fake runtime above all)."""
    popen: Callable[..., object] | None = None
    tool_status: Callable[[], procs.ToolStatus] = player.tool_status
    get_runtime: Callable[..., Path] = runtime.ensure_runtime
    disk_free: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free
    kill_tree: Callable[[object], None] = procs.kill_tree
    make_icon: Callable[[Path, str | None], bytes] = _make_icon
    set_resources: Callable[[Path, bytes, bytes], None] = _set_resources
    unknown_dlls: Callable[[list[Path]], tuple[str, ...]] = _unknown_dlls
    write_zip: Callable[[Path, Path], tuple[int, int]] = _write_zip
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    engine_root: Callable[[], Path] = engine_root


# --- Reporting --------------------------------------------------------------------------------

class Reporter:
    """Writes the build's lines: report events (``report``) or the CLI's §6.3 lines."""

    def __init__(self, *, report: bool, out: TextIO | None = None,
                 err: TextIO | None = None) -> None:
        self.report = report
        self._out = out if out is not None else sys.stdout
        self._err = err if err is not None else sys.stderr

    # Report mode ------------------------------------------------------------------------
    def _write_raw(self, body: bytes) -> None:
        buffer = getattr(self._out, "buffer", None)
        if buffer is not None:
            self._out.flush()
            buffer.write(body + b"\n")
            buffer.flush()
        else:
            self._out.write(body.decode("ascii") + "\n")
            self._out.flush()

    def event(self, name: str, **fields: object) -> None:
        data = {"v": REPORT_VERSION, "event": name, **fields}
        body = REPORT_MARKER + json.dumps(data, ensure_ascii=True,
                                          separators=(",", ":")).encode("ascii")
        self._write_raw(body)

    def relay(self, body: bytes) -> None:
        """A check line, unchanged (report mode only)."""
        self._write_raw(body)

    # Both ------------------------------------------------------------------------------
    def print(self, line: str, *, err: bool = False) -> None:
        stream = self._err if err else self._out
        stream.write(line + "\n")
        stream.flush()

    def head(self, name: str, version: str) -> None:
        if not self.report:
            self.print(texts.CLI_HEAD.format(name=name, version=version))

    def step(self, i: int, m: int, key: str, *, files: int | None = None,
             size: int | None = None, staging: str | None = None) -> None:
        if self.report:
            self.event("build_step", i=i, m=m, key=key, files=files, bytes=size,
                       staging=staging)
        else:
            self.print(texts.cli_step_line(i, m, key, files=files, size=size))

    def failed(self, key: str, values: dict, details: list[str]) -> None:
        details = details[-BUILD_MAX_DETAILS:]
        if self.report:
            self.event("build_failed", code=key, values=values, details=details)
            return
        for line in texts.cli_failure_lines(key, **values):
            self.print(line, err=True)
        for line in details:
            self.print("  " + line, err=True)

    def cancelled(self, save_to_name: str) -> None:
        if not self.report:
            self.print(texts.CANCELLED.format(save_to=save_to_name), err=True)

    def done(self, result: "BuildResult") -> None:
        left = result.left_out
        if self.report:
            self.event("build_done", folder=result.folder, exe=result.exe,
                       files=result.files, bytes=result.bytes,
                       zip=None if result.zip_path is None else result.zip_path.name,
                       zip_bytes=result.zip_bytes, warnings=result.warnings,
                       left_out=[[item.ref, item.reason] for item in left[:BUILD_MAX_LEFT_OUT]],
                       left_out_total=len(left), long_paths=result.long_paths,
                       long_path_example=result.long_path_example,
                       keys=[[hit.ref, hit.line] for hit in result.keys])
            return
        self.print(texts.DONE)
        self.print(texts.CLI_DONE_FOLDER.format(path=result.folder_path,
                                                size=texts.format_size(result.bytes),
                                                files=texts.format_count(result.files)))
        if result.zip_path is not None:
            self.print(texts.CLI_DONE_ZIP.format(path=result.zip_path,
                                                 size=texts.format_size(result.zip_bytes or 0)))
        self.print(texts.share_text(result.exe, result.folder, result.zip_path is not None))
        self.print(texts.SMARTSCREEN)
        if result.warnings:
            self.print(texts.warnings_text(result.warnings).replace(
                texts.WARNINGS_WHERE, " They're listed above."))
        if left:
            self.print(texts.left_out_text(len(left)))
            for item in left:
                self.print("  " + item.line)
        if result.long_paths:
            self.print(texts.LONG_PATHS.format(n=texts.format_count(result.long_paths),
                                               ref=result.long_path_example))
        for hit in result.keys:
            self.print(texts.key_found_text(hit.ref, hit.line))


@dataclass
class BuildResult:
    folder: str
    exe: str
    folder_path: Path
    files: int = 0
    bytes: int = 0
    zip_path: Path | None = None
    zip_bytes: int | None = None
    warnings: int = 0
    left_out: list = field(default_factory=list)
    long_paths: int = 0
    long_path_example: str | None = None
    keys: list = field(default_factory=list)        # keyscan.KeyHit, ref and line only


# --- The step machine -------------------------------------------------------------------------

def _stopped(key: str, details: list[str], **values: object) -> BuildStopped:
    """``BuildStopped`` carrying detail lines (already redacted) for **Show details**."""
    stop = BuildStopped(key, **values)
    stop.details = details                                  # type: ignore[attr-defined]
    return stop


def default_out(game_dir: Path) -> Path:
    """D6 / ``07`` I-6: ``builds`` next to the game folder (as ``buildprefs`` defaults)."""
    return Path(os.path.abspath(game_dir)).parent / BUILDS_FOLDER


def _nearest_existing(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if os.path.isdir(candidate):
            return candidate
    return path


def _tree_size(folder: Path) -> tuple[int, int]:
    """(files, bytes) under ``folder``, links not followed."""
    files = total = 0
    for top, dirs, names_ in os.walk(folder, followlinks=False):
        for name in names_:
            try:
                total += os.lstat(os.path.join(top, name)).st_size
            except OSError:
                continue
            files += 1
    return files, total


class BuildJob:
    """One build of ``game_dir`` into ``out``; ``run()`` → exit code."""

    def __init__(self, game_dir: Path, *, out: Path | None, zip: bool, replace: bool,
                 reporter: Reporter, deps: BuildDeps) -> None:
        self.game_dir = Path(game_dir)
        self.out = out
        self.zip = zip
        self.replace = replace
        self.reporter = reporter
        self.deps = deps
        self.proc: object | None = None          # the running grandchild
        self.staging: tree.Staging | None = None
        self.save_to: Path | None = None
        self.root: Path | None = None
        self._roots: list[RedactRoot] = []

    # The run ---------------------------------------------------------------------------
    def run(self) -> int:
        try:
            self.root = GamePaths.for_game(self.game_dir).root
        except UserFacingError as error:
            self.reporter.print(f"build: {error.message}", err=True)
            return EXIT_USAGE
        out = self.out if self.out is not None else default_out(self.game_dir)
        self.save_to = Path(os.path.realpath(os.path.abspath(out)))
        try:
            self._steps()
            return EXIT_BUILT
        except BuildStopped as stop:
            self.reporter.failed(stop.key, dict(stop.values), list(getattr(stop, "details", [])))
            return EXIT_NOT_BUILT
        except KeyboardInterrupt:
            self.reporter.cancelled(self.save_to.name)
            return EXIT_NOT_BUILT
        except Exception:
            lines = traceback.format_exc().splitlines()
            self.reporter.failed("B_CRASHED", {}, self._redacted(lines))
            return EXIT_NOT_BUILT
        finally:
            self._stop_child()
            if self.staging is not None:
                self.staging.remove()
                self.staging = None

    def _stop_child(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None:
            self.deps.kill_tree(proc)

    def _redacted(self, lines: list[str]) -> list[str]:
        roots = list(self._roots)
        if not roots:
            roots = redaction_roots(game_root=self.root, game_dir_as_given=self.game_dir,
                                    engine_root=self.deps.engine_root())
            if self.save_to is not None:
                roots.append(RedactRoot(procs.SAVE_TO_TOKEN, str(self.save_to)))
        return procs.redacted_tail(lines, roots)

    def _steps(self) -> None:
        root, save_to = self.root, self.save_to
        assert root is not None and save_to is not None
        paths = GamePaths(root)
        config_result = load_config(paths)
        config = config_result.config
        title, version, app_id = config.game.title, config.game.version, config.game.id or ""
        folder = names.folder_name(title, version, app_id)
        exe = names.exe_name(title, app_id)
        m = len(texts.steps(self.zip))
        self.reporter.head(names.clean_name(title, app_id), version)

        if config_result.errors:                          # Problems list them, then stop
            self.reporter.step(1, m, texts.STEP_CHECK)
            self._check(root)
            raise BuildStopped("B_CONFIG")
        prep = self._preflight(root, save_to, config, folder, app_id)

        # 1. Check
        self.reporter.step(1, m, texts.STEP_CHECK)
        warnings = self._check(root)

        # 2. Copy
        tree.sweep_stale(save_to)
        try:
            self.staging = tree.make_staging(save_to, folder)
        except OSError:
            raise BuildStopped("B_CANT_WRITE", save_to=save_to.name) from None
        staging = self.staging.path
        self._roots = (redaction_roots(game_root=root, game_dir_as_given=self.game_dir,
                                       engine_root=self.deps.engine_root())
                       + procs.build_roots(save_to, staging))
        cache = player.cache_root()
        if cache is not None:
            self._roots.append(RedactRoot(RUNTIME_TOKEN, str(cache)))
        self.reporter.step(2, m, texts.STEP_COPY, files=prep.files, size=prep.bytes,
                           staging=self.staging.name)
        build_dir = staging / BUILD_DIR
        os.mkdir(build_dir)
        build_folder = build_dir / folder
        os.mkdir(build_folder)
        copied = tree.copy_game(root, build_folder / GAME_DIR, long_prefix=f"{folder}/game/")
        keys = keyscan.scan(build_folder / GAME_DIR)       # F48 SEC-F48-24: ref:line only

        # 3. Pack
        self.reporter.step(3, m, texts.STEP_PACK)
        self._pack(staging, build_folder, title=title, version=version, exe=exe,
                   ico=prep.ico, hidden=prep.hidden)

        # 4. Notices
        self.reporter.step(4, m, texts.STEP_NOTICES)
        self._notices(build_folder, title=title, version=version, exe=exe, app_id=app_id)

        # 5. Zip
        staged_zip = None
        i = 5
        if self.zip:
            self.reporter.step(i, m, texts.STEP_ZIP)
            staged_zip = build_dir / names.zip_name(folder)
            self.deps.write_zip(build_folder, staged_zip)   # a failure is B_CRASHED
            i += 1

        # 6. Finish
        self.reporter.step(i, m, texts.STEP_FINISH)
        files, size = _tree_size(build_folder)
        zip_bytes = os.lstat(staged_zip).st_size if staged_zip is not None else None
        if not self.replace and tree.find_earlier_build(save_to, folder,
                                                        with_zip=self.zip) is not None:
            raise BuildStopped("B_EXISTS", folder=folder, save_to=save_to.name)
        installed = tree.install_build(save_to, folder, build_folder, staged_zip)
        self.reporter.done(BuildResult(
            folder=folder, exe=exe, folder_path=installed.folder, files=files, bytes=size,
            zip_path=installed.zip, zip_bytes=zip_bytes, warnings=warnings,
            left_out=copied.left_out, long_paths=copied.long_paths,
            long_path_example=copied.long_path_example, keys=keys))

    # Preflight -------------------------------------------------------------------------
    @dataclass
    class _Prep:
        files: int
        bytes: int
        ico: bytes | None
        hidden: tuple[str, ...]

    def _preflight(self, root: Path, save_to: Path, config, folder: str,
                   app_id: str) -> "_Prep":
        if not app_id:
            raise BuildStopped("B_NO_ID", slug=names.use_slug(config.game.title))
        status = self.deps.tool_status()
        if status.key == "B_TOOL_VERSION":
            raise BuildStopped("B_TOOL_VERSION", x=status.found or "?", y=status.wanted)
        if status.key is not None:
            raise BuildStopped(status.key)
        engine_code = self.deps.engine_root() / "engine"
        if (tree.real_inside(save_to, root) or tree.real_inside(root, save_to)
                or tree.real_inside(save_to, engine_code)):
            raise BuildStopped("B_OUT_INSIDE", game=root.name)
        exists = os.path.lexists(save_to)
        if exists and not os.path.isdir(save_to):
            raise BuildStopped("B_NO_FOLDER", save_to=save_to.name)
        if not exists and not tree.is_real_dir(save_to.parent):
            raise BuildStopped("B_NO_FOLDER", save_to=save_to.name)
        if exists:
            earlier = tree.find_earlier_build(save_to, folder, with_zip=self.zip)
            if earlier is not None and not self.replace:
                raise BuildStopped("B_EXISTS", folder=folder, save_to=save_to.name)
        scan = plugins.scan_imports(root)
        if scan.foreign is not None:
            raise BuildStopped("B_PLUGIN_IMPORT", ref=scan.foreign.ref,
                               module=scan.foreign.module)
        ico = self.deps.make_icon(root, config.window.icon) if IS_WINDOWS else None
        found = tree.prescan(root, long_prefix=f"{folder}/game/")
        need = (found.bytes + SPACE_MARGIN) * (2 if self.zip else 1)
        free = self.deps.disk_free(_nearest_existing(save_to))
        if free < need:
            raise BuildStopped("B_NO_SPACE", need=texts.format_size(need),
                               free=texts.format_size(free))
        if not exists:
            try:
                os.mkdir(save_to)
            except OSError:
                raise BuildStopped("B_CANT_WRITE", save_to=save_to.name) from None
        return BuildJob._Prep(found.files, found.bytes, ico, scan.modules)

    # Steps -----------------------------------------------------------------------------
    def _started(self, proc: object) -> None:
        self.proc = proc

    def _check(self, root: Path) -> int:
        """Step 1; returns the warning count."""
        report = self.reporter
        outcome = checkstep.run_check(
            root, relay=report.relay if report.report else None,
            show=None if report.report else (lambda line: report.print(line)),
            started=self._started, popen=self.deps.popen)
        self.proc = None
        if not outcome.done:
            raise _stopped("B_CRASHED", self._redacted(outcome.tail))
        if outcome.config_errors:
            raise BuildStopped("B_CONFIG")
        if outcome.failed:
            raise BuildStopped("B_ERRORS", n=max(outcome.errors, 1))
        return outcome.warnings

    def _pack(self, staging: Path, build_folder: Path, *, title: str, version: str,
              exe: str, ico: bytes | None, hidden: tuple[str, ...]) -> None:
        """F66: copy the player runtime (made first in a developer install without one),
        then write the game's icon and version resource on its exe."""
        kwargs = {} if self.deps.popen is None else {"popen": self.deps.popen}
        try:
            source = self.deps.get_runtime(scratch=staging, started=self._started, **kwargs)
        except runtime.RuntimeBuildError as error:
            raise _stopped("B_PACK_FAILED", self._redacted(error.lines)) from None
        finally:
            self.proc = None
        runtime.copy_runtime(source, build_folder, exe,
                             keep_network=spec.needs_network(hidden))
        if ico is None:
            return
        from engine.tools.build import winres
        info = winres.version_info(title=title, version=version,
                                   file_version=names.file_version(version), exe_name=exe)
        try:
            self.deps.set_resources(build_folder / exe, ico, info)
        except winres.ResourceError as error:
            raise _stopped("B_PACK_FAILED", self._redacted([str(error)])) from None

    def _notices(self, build_folder: Path, *, title: str, version: str, exe: str,
                 app_id: str) -> None:
        internal = build_folder / spec.CONTENTS_DIR
        for needed in (internal, build_folder / LICENSES_DIR):
            if not tree.is_real_dir(needed):
                raise _stopped("B_PACK_FAILED", [f"{needed.name} is missing."])
        unknown = tuple(self.deps.unknown_dlls([internal, internal / "pygame"]))
        if unknown:
            raise _stopped("B_PACK_FAILED", [texts.NO_NOTICE.format(dll=dll) for dll in unknown])
        with open(build_folder / README, "xb") as stream:
            stream.write(texts.readme_bytes(name=title, version=version, exe=exe,
                                            app_id=app_id))
        built = self.deps.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(internal / tree.MARKER_NAME, "xb") as stream:
            stream.write(tree.marker_bytes(engine=engine.__version__, app_id=app_id,
                                           version=version, built=built))


def build_command(game_dir: Path, *, out: Path | None = None, zip: bool = False,
                  replace: bool = False, report: bool = False,
                  deps: BuildDeps | None = None, stdout: TextIO | None = None,
                  stderr: TextIO | None = None) -> int:
    """The ``build`` handler: build ``game_dir`` into ``out`` (default ``<game parent>/
    builds``). Exit 0 built, 1 not built, 2 not a game folder."""
    sys.dont_write_bytecode = True
    reporter = Reporter(report=report, out=stdout, err=stderr)
    return BuildJob(game_dir, out=out, zip=zip, replace=replace, reporter=reporter,
                    deps=deps or BuildDeps()).run()


__all__ = ["BuildDeps", "BuildJob", "BuildResult", "EXIT_BUILT", "EXIT_NOT_BUILT",
           "EXIT_USAGE", "Reporter", "build_command", "default_out"]

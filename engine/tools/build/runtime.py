"""Making and copying the player runtime (F66; F42 ``04`` §3.1).

Why this module exists: a build used to run PyInstaller for each game, which needs Python and
the build tool on the author's PC. But every game's exe is the same program
(``launcher_main``, ``_frozen_prelude``, running ``<exe folder>/game``); only the game folder,
the icon, the version resource and the names differ. So PyInstaller runs once to make the
*runtime*, a one-folder player with no game inside, and a build copies it (seconds, no
Python). Which runtime a build uses, and Build's readiness, are ``player``'s (shared with
Studio); this child-only module makes and copies one:

- ``build_player_runtime(out_dir)``: PyInstaller (a child, ``spec.spec_text``) makes
  ``<out_dir>/player.exe`` and ``_internal/``, then ``licenses/`` (``licenses.collect_notices``
  over the bundled DLLs; a DLL without a notice stops it) and ``vn-runtime.json`` (format,
  engine version, ``player.runtime_key``). Studio's app build calls it and ships the folder
  as ``<Studio app>/player/``.
- ``ensure_runtime(...)``: ``player.find_runtime()``, else (developer install only) make one
  into the cache first, so a developer install and Studio's app share one assembly path: the
  first build after an engine change takes a minute or so, later ones seconds.
- ``copy_runtime(runtime, dest, exe_name, keep_network=...)``: the copy into a build folder,
  ``player.exe`` renamed, ``vn-runtime.json`` left out, ``spec.NETWORK_BINARIES`` left out
  unless a plugin may need them.

Child-only; imports ``core``, its own package and the standard library.
"""

import collections
import json
import os
import secrets
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

import engine
from engine.core import paths
from engine.tools.build import player, procs, spec, tree
from engine.tools.build.player import (CACHE_DIR, LICENSES_DIR, META_NAME, PLAYER_EXE,
                                       PLAYER_STEM, RUNTIME_FORMAT)

ICON_FILE: Final = "icon.ico"
SPEC_FILE: Final = "player.spec"
WORK_SUFFIX: Final = ".work-"
STALE_TEMP_S: Final = 3600.0             # a cache temp older than this is a crashed build's
IS_WINDOWS: Final = os.name == "nt"


class RuntimeBuildError(Exception):
    """Making the runtime failed; ``lines`` are PyInstaller's last output lines (or the
    reason), not yet redacted."""

    def __init__(self, lines: list[str]) -> None:
        super().__init__("\n".join(lines[-3:]))
        self.lines = list(lines)


# --- Making one ------------------------------------------------------------------------------

def _engine_ico() -> bytes | None:
    if not IS_WINDOWS:
        return None
    from engine.tools.build import icon
    return icon.make_ico(icon.icon_png(Path("."), None))


def build_player_runtime(out_dir: Path, *, popen: Callable[..., object] | None = None,
                         started: Callable[[object], None] | None = None,
                         root: Path | None = None) -> Path:
    """Make the runtime in ``out_dir`` (which must not exist, or be an empty folder) and
    return it. PyInstaller runs as a child (``started`` is told the process, so a caller can
    kill its tree); its work folder sits beside ``out_dir`` and is removed. Raises
    ``RuntimeBuildError`` (PyInstaller failed, or a bundled DLL has no notice) and
    ``OSError``; on failure nothing is left in ``out_dir``."""
    from engine.tools.build import checkstep, licenses, texts

    out_dir = Path(os.path.abspath(out_dir))
    created = not os.path.lexists(out_dir)
    if not created and (not tree.is_real_dir(out_dir) or os.listdir(out_dir)):
        raise FileExistsError(f"{out_dir} isn't an empty folder")
    base = Path(root) if root is not None else paths.engine_root()
    work = out_dir.parent / f".{out_dir.name}{WORK_SUFFIX}{secrets.token_hex(4)}"
    os.makedirs(work)
    done = False
    try:
        spec_dir = work / procs.SPEC_DIR
        os.mkdir(spec_dir)
        ico = _engine_ico()
        icon_path = None
        if ico is not None:
            icon_path = spec_dir / ICON_FILE
            icon_path.write_bytes(ico)
        spec_file = spec_dir / SPEC_FILE
        spec_file.write_text(spec.spec_text(exe_stem=PLAYER_STEM, icon=icon_path, root=base),
                             encoding="utf-8")
        kwargs = {} if popen is None else {"popen": popen}
        proc = procs.spawn(spec.packer_argv(spec_file, work), **kwargs)
        if started is not None:
            started(proc)
        ring: collections.deque[str] = collections.deque(maxlen=procs.TAIL_LINES)
        try:
            for body in checkstep.read_lines(proc.stdout):
                ring.append(body.decode("utf-8", "replace"))
        finally:
            try:
                proc.stdout.close()
            except (OSError, ValueError):
                pass
        code = proc.wait()
        app = work / procs.DIST_DIR / spec.COLLECT_NAME
        exe = player.player_name()
        if code != 0 or not tree.is_real_dir(app) or not (app / exe).is_file():
            raise RuntimeBuildError(list(ring) or [f"PyInstaller stopped with code {code}."])
        os.makedirs(out_dir, exist_ok=True)
        for entry in sorted(os.listdir(app)):
            os.rename(app / entry, out_dir / entry)
        internal = out_dir / spec.CONTENTS_DIR
        notices = licenses.collect_notices([internal, internal / "pygame"])
        if notices.unknown_dlls:
            raise RuntimeBuildError([texts.NO_NOTICE.format(dll=dll)
                                     for dll in notices.unknown_dlls])
        licenses.write_notices(out_dir / LICENSES_DIR, notices)
        meta = {"format": RUNTIME_FORMAT, "engine": engine.__version__,
                "key": player.runtime_key(base), "exe": exe}
        with open(out_dir / META_NAME, "x", encoding="utf-8") as stream:
            stream.write(json.dumps(meta, indent=2) + "\n")
        done = True
        return out_dir
    finally:
        tree.remove_tree(work)
        if not done and os.path.lexists(out_dir):
            if created:
                tree.remove_tree(out_dir)
            else:
                for name in os.listdir(out_dir):
                    tree.remove_tree(out_dir / name)


def _prune(root: Path, keep: str) -> None:
    """Remove the cache's other runtimes, and its temps older than ``STALE_TEMP_S``;
    anything else there is left alone."""
    now = time.time()
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        path = root / name
        if name == keep:
            continue
        if name.startswith("."):
            try:
                if now - os.lstat(path).st_mtime < STALE_TEMP_S:
                    continue
            except OSError:
                continue
        elif player.read_meta(path) is None:
            continue
        tree.remove_tree(path)


def ensure_runtime(*, scratch: Path, popen: Callable[..., object] | None = None,
                   started: Callable[[object], None] | None = None) -> Path:
    """The runtime to copy: ``player.find_runtime()``, else a new one made in the cache (or,
    with no cache folder, in ``scratch``, a folder the caller removes). Raises
    ``RuntimeBuildError``."""
    found = player.find_runtime()
    if found is not None:
        return found
    if paths.is_frozen():
        raise RuntimeBuildError(["This copy of Studio is missing its player folder."])
    root = player.cache_root()
    if root is None:
        return build_player_runtime(Path(scratch) / CACHE_DIR, popen=popen, started=started)
    key = player.runtime_key()
    os.makedirs(root, exist_ok=True)
    name = key[:player.KEY_CHARS]
    temp = root / f".{name}.building-{secrets.token_hex(4)}"
    build_player_runtime(temp, popen=popen, started=started)
    final = root / name
    try:
        os.rename(temp, final)
    except OSError:
        tree.remove_tree(temp)
        meta = player.read_meta(final)
        if meta is None or meta["key"] != key:      # not another build's finished runtime
            raise
    _prune(root, name)
    return final


# --- Copying one into a build -----------------------------------------------------------------

def copy_runtime(runtime: Path, dest: Path, exe_name: str, *, keep_network: bool) -> None:
    """Copy ``runtime`` into the existing folder ``dest``: the player exe as ``exe_name``,
    no ``vn-runtime.json``, and no ``spec.NETWORK_BINARIES`` unless ``keep_network``. Links
    are skipped; files are created exclusively (``dest`` holds only ``game/``)."""
    runtime, dest = Path(runtime), Path(dest)
    exe = player.player_name()
    for folder, dirs, files in os.walk(runtime, followlinks=False):
        here = Path(folder)
        rel = here.relative_to(runtime)
        dirs[:] = sorted(d for d in dirs if not (here / d).is_symlink())
        for name in dirs:
            os.mkdir(dest / rel / name)
        for name in sorted(files):
            source = here / name
            if source.is_symlink():
                continue
            target = dest / rel / name
            if rel == Path("."):
                if name == META_NAME:
                    continue
                if name == exe:
                    target = dest / exe_name
            if rel == Path(spec.CONTENTS_DIR) and not keep_network \
                    and name.casefold() in spec.NETWORK_BINARIES:
                continue
            with open(source, "rb") as reader, open(target, "xb") as writer:
                shutil.copyfileobj(reader, writer, 1 << 20)


__all__ = ["PLAYER_EXE", "RuntimeBuildError", "build_player_runtime", "copy_runtime",
           "ensure_runtime"]

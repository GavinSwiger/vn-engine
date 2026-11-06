"""The PyInstaller spec of the player runtime (F42 ``04-technical.md`` §3.1, §7.4; SEC-F42-02,
-03, -04, -15; ``07`` I-5; F66).

Why this module exists: every built game runs the same frozen player (``launcher_main`` running
``<exe folder>/game``), so PyInstaller runs once to make that player, the *runtime*
(``runtime.build_player_runtime``), and builds only copy it (architect decision 3, kept as one
readable spec text):

- ``Analysis([<engine root>/main.py], pathex=[])``: the exe runs ``main.py``'s
  ``launcher_main``. ``hiddenimports`` = ``engine_modules()`` (every real ``engine``
  package and module except ``engine/tools`` and ``engine/data``, so engine modules imported
  by name are bundled) + ``stdlib_modules()`` (the whole standard library a build may ship,
  so any plugin's standard-library import works without a new PyInstaller run).
  ``excludes``: ``EXCLUDES`` (``engine.tools``, ``PyInstaller`` and the standard-library
  parts builds never ship, ``plugins.NOT_BUNDLED``: ``tkinter`` and the like).
  ``module_collection_mode``: ``PYGAME_COLLECTION``, pygame-ce as loose files (LGPL).
- ``datas``: only ``engine/data/fonts`` and ``engine/data/icon.png``, placed at
  ``engine/data/...`` inside the bundle so ``engine_data_dir()`` finds them under
  ``_MEIPASS`` (I-5). ``engine/data/starter/`` and ``engine/data/sample/`` never ship.
- ``EXE(console=False, upx=False, icon, contents_directory="_internal")`` and
  ``COLLECT(upx=False, name="app")``: one-folder mode, the stock bootloader, no UPX. Each
  build writes the game's own icon and version resource onto its copy of the exe
  (``winres``).
- No game-folder path is ever an input (SEC-F42-03).

The network and OpenSSL binaries (``NETWORK_BINARIES``) are in the runtime; a build leaves them
out unless a plugin may need them (``needs_network``, P8).

Every value is written with ``repr()``: PyInstaller evaluates the spec as Python.

``packer_argv(spec_file, work)`` is the packer's command: ``-E -B -m PyInstaller`` with
dist and work folders inside ``work`` (SEC-F42-04).

Imports ``core``, ``tools.build.procs``/``plugins`` and the standard library.
"""

import os
import sys
import sysconfig
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from engine.core.paths import engine_root
from engine.tools.build.plugins import NOT_BUNDLED
from engine.tools.build.procs import DIST_DIR, WORK_DIR

ENTRY_SCRIPT: Final = "main.py"
COLLECT_NAME: Final = "app"              # dist/app/* is moved into the build folder
CONTENTS_DIR: Final = "_internal"
EXCLUDES: Final = ("engine.tools", "PyInstaller", *sorted(NOT_BUNDLED))
# pygame-ce is LGPL 2.1: its Python modules ship as loose .pyc files in _internal/pygame,
# beside its .pyd modules and DLLs, not inside the exe's archive, so a player can replace
# the whole package with their own build (§6; notices/pygame-ce.txt says so).
PYGAME_COLLECTION: Final = {"pygame": "pyc"}
# Network and OpenSSL binaries the engine never uses at run time (P8): stdlib ``platform``
# (which ``engine.app.platform`` imports for the OS name) imports ``socket`` inside ``node()``,
# and ``hashlib`` imports the OpenSSL-backed ``_hashlib`` (libcrypto-3.dll, about 5 MB) when
# it can. The engine only calls ``platform.system()``/``release()``/``version()`` (``uname()``
# returns an empty node name without ``socket``) and ``hashlib.blake2b``/``sha256``, which
# come from Python's built-in ``_blake2``/``_sha2``. So a build leaves these files of
# ``_internal`` out (their modules then fail to import, which the engine expects), unless a
# plugin imports something that may need them (``NEEDS_NETWORK``), when they stay.
# ``_socket.pyd`` (85 KB) always stays: with the whole standard library in the runtime,
# PyInstaller's multiprocessing runtime hook imports ``socket`` at every start (F66).
NETWORK_BINARIES: Final = frozenset({"_hashlib.pyd", "_ssl.pyd", "libcrypto-3.dll",
                                     "libssl-3.dll"})
NEEDS_NETWORK: Final = frozenset({
    "asyncio", "concurrent", "email", "ftplib", "hashlib", "hmac", "http", "imaplib",
    "logging.handlers", "mailbox", "multiprocessing", "poplib", "secrets", "selectors",
    "smtplib", "socket", "socketserver", "ssl", "urllib", "uuid", "wsgiref", "xmlrpc"})
SKIPPED_PACKAGES: Final = frozenset({"tools", "data"})     # under engine/
SKIPPED_MODULES: Final = frozenset({"__main__"})           # the frozen exe runs main.py
# Standard-library names the runtime leaves out besides NOT_BUNDLED: CPython's own test
# extensions and demo modules (``_test*`` too), and test folders inside packages.
STDLIB_SKIPPED: Final = frozenset({"__hello__", "__phello__", "_ctypes_test", "xxlimited",
                                   "xxlimited_35", "xxsubtype", "antigravity", "this"})
STDLIB_TEST_DIRS: Final = frozenset({"test", "tests", "idle_test"})
MAX_VERSION_PART: Final = 0xFFFF


def engine_modules(root: Path | None = None) -> list[str]:
    """Dotted names of every real package (identifier name, ``__init__.py``) and module
    under ``<root>/engine`` except ``engine/tools`` and ``engine/data``; sorted. Links are not
    followed."""
    base = Path(root) if root is not None else engine_root()
    top = base / "engine"
    found: list[str] = []
    stack: list[tuple[Path, tuple[str, ...]]] = [(top, ("engine",))]
    while stack:
        folder, parts = stack.pop()
        if not (folder / "__init__.py").is_file():
            continue
        found.append(".".join(parts))
        try:
            with os.scandir(folder) as entries:
                listed = [(entry.name, entry.is_dir(follow_symlinks=False),
                           entry.is_file(follow_symlinks=False), entry.is_symlink())
                          for entry in entries]
        except OSError:
            continue
        for name, is_dir, is_file, is_link in listed:
            if is_link:
                continue
            if is_dir:
                if name.isidentifier() and not (len(parts) == 1 and name in SKIPPED_PACKAGES):
                    stack.append((folder / name, (*parts, name)))
            elif is_file and name.endswith(".py"):
                stem = name[:-3]
                if stem.isidentifier() and stem != "__init__" and stem not in SKIPPED_MODULES:
                    found.append(".".join((*parts, stem)))
    return sorted(found)


def version_numbers(file_version: str) -> tuple[int, int, int, int]:
    """``"1.2.0.0"`` → ``(1, 2, 0, 0)``; each part 0..65535 (``names.file_version`` makes
    the text). Raises ``ValueError``."""
    parts = file_version.split(".")
    if len(parts) != 4 or not all(part.isdigit() and part.isascii() for part in parts):
        raise ValueError(file_version)
    numbers = tuple(int(part) for part in parts)
    if any(number > MAX_VERSION_PART for number in numbers):
        raise ValueError(file_version)
    return numbers  # type: ignore[return-value]


def needs_network(hidden: Iterable[str] = ()) -> bool:
    """Whether a plugin module in ``hidden`` is (or is inside) one of ``NEEDS_NETWORK``: the
    build then keeps ``NETWORK_BINARIES``."""
    return any(name == wanted or name.startswith(wanted + ".")
               for name in hidden for wanted in NEEDS_NETWORK)


def _stdlib_name_ok(name: str) -> bool:
    return (name.isidentifier() and name not in NOT_BUNDLED and name not in STDLIB_SKIPPED
            and not name.startswith("_test"))


def stdlib_modules() -> list[str]:
    """Every standard-library module a build may ship, sorted: the top-level names in
    ``sys.stdlib_module_names`` (less ``NOT_BUNDLED``, ``STDLIB_SKIPPED`` and ``_test*``),
    plus each package's real submodules on disk (test folders and ``__main__`` left out).
    Names this platform lacks (``pwd``) are harmless: PyInstaller notes them and goes on."""
    stdlib = Path(sysconfig.get_paths()["stdlib"])
    found = {name for name in sys.stdlib_module_names if _stdlib_name_ok(name)}
    for top in sorted(found):
        package = stdlib / top
        if not (package / "__init__.py").is_file():
            continue
        stack = [(package, (top,))]
        while stack:
            folder, parts = stack.pop()
            try:
                with os.scandir(folder) as entries:
                    listed = [(entry.name, entry.is_dir(follow_symlinks=False),
                               entry.is_file(follow_symlinks=False)) for entry in entries]
            except OSError:
                continue
            for name, is_dir, is_file in listed:
                if is_dir and name.isidentifier() and name not in STDLIB_TEST_DIRS \
                        and (folder / name / "__init__.py").is_file():
                    found.add(".".join((*parts, name)))
                    stack.append((folder / name, (*parts, name)))
                elif is_file and name.endswith(".py"):
                    stem = name[:-3]
                    if stem.isidentifier() and stem not in ("__init__", "__main__"):
                        found.add(".".join((*parts, stem)))
    return sorted(found)


def spec_text(*, exe_stem: str, icon: Path | None, root: Path | None = None) -> str:
    """The runtime's spec for ``exe_stem`` (the exe name without ``.exe``); ``icon`` is an
    ``.ico`` in the work folder (None on platforms without one)."""
    base = Path(root) if root is not None else engine_root()
    data = base / "engine" / "data"
    hiddenimports = engine_modules(base) + stdlib_modules()
    datas = [(str(data / "fonts"), "engine/data/fonts"),
             (str(data / "icon.png"), "engine/data")]
    return (
        "# Generated by vn-engine's build (engine/tools/build/spec.py). Do not edit.\n"
        "a = Analysis(\n"
        f"    [{str(base / ENTRY_SCRIPT)!r}],\n"
        "    pathex=[],\n"
        "    binaries=[],\n"
        f"    datas={datas!r},\n"
        f"    hiddenimports={hiddenimports!r},\n"
        "    hookspath=[],\n"
        "    hooksconfig={},\n"
        "    runtime_hooks=[],\n"
        f"    excludes={list(EXCLUDES)!r},\n"
        "    noarchive=False,\n"
        f"    module_collection_mode={PYGAME_COLLECTION!r},\n"
        ")\n"
        "pyz = PYZ(a.pure)\n"
        "exe = EXE(\n"
        "    pyz,\n"
        "    a.scripts,\n"
        "    [],\n"
        "    exclude_binaries=True,\n"
        f"    name={exe_stem!r},\n"
        "    debug=False,\n"
        "    bootloader_ignore_signals=False,\n"
        "    strip=False,\n"
        "    upx=False,\n"
        "    console=False,\n"
        f"    icon={None if icon is None else str(icon)!r},\n"
        f"    contents_directory={CONTENTS_DIR!r},\n"
        ")\n"
        "coll = COLLECT(\n"
        "    exe,\n"
        "    a.binaries,\n"
        "    a.datas,\n"
        "    strip=False,\n"
        "    upx=False,\n"
        "    upx_exclude=[],\n"
        f"    name={COLLECT_NAME!r},\n"
        ")\n"
    )


def packer_argv(spec_file: Path, work: Path) -> list[str]:
    """``python -E -B -m PyInstaller`` on ``spec_file`` with dist and work in ``work``."""
    work = Path(work)
    return [sys.executable, "-E", "-B", "-m", "PyInstaller", "--noconfirm",
            "--log-level", "WARN", "--distpath", str(work / DIST_DIR),
            "--workpath", str(work / WORK_DIR), str(spec_file)]


__all__ = ["COLLECT_NAME", "CONTENTS_DIR", "ENTRY_SCRIPT", "EXCLUDES", "NEEDS_NETWORK",
           "NETWORK_BINARIES", "engine_modules", "needs_network", "packer_argv", "spec_text",
           "stdlib_modules", "version_numbers"]

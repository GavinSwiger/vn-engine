"""The PyInstaller spec and version file (F42 ``04-technical.md`` §3.1, §7.4; SEC-F42-02,
-03, -04, -15; ``07`` I-5).

Why this module exists: the build drives PyInstaller as a child from a generated spec
(architect decision 3), so what goes into the bundle is decided here, in one readable text:

- ``Analysis([<engine root>/main.py], pathex=[])``: the exe runs ``main.py``'s
  ``launcher_main``. ``hiddenimports`` = ``engine_modules()`` (every real ``engine``
  package and module except ``engine/tools`` and ``engine/data``, so engine modules imported
  by name are bundled) + the plugins' standard-library modules (``plugins.scan_imports``).
  ``excludes``: ``tkinter``, ``_tkinter``, ``engine.tools``, ``PyInstaller``.
- ``datas``: only ``engine/data/fonts`` and ``engine/data/icon.png``, placed at
  ``engine/data/...`` inside the bundle so ``engine_data_dir()`` finds them under
  ``_MEIPASS`` (I-5). ``engine/data/starter/`` and ``engine/data/sample/`` never ship.
- ``EXE(console=False, upx=False, icon, version, contents_directory="_internal")`` and
  ``COLLECT(upx=False, name="app")``: one-folder mode, the stock bootloader, no UPX.
- No game-folder path is ever an input: the icon and version file are written into staging
  first, and the game folder is copied separately (SEC-F42-03).

Every value is written with ``repr()``: PyInstaller evaluates both files as Python, so a title
like ``x'); import os #`` stays a string.

``packer_argv(spec_file, staging)`` is the packer's command: ``-E -B -m PyInstaller`` with
dist and work folders inside staging (SEC-F42-04).

Child-only; imports ``core``, ``tools.build.procs`` and the standard library.
"""

import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from engine.core.paths import engine_root
from engine.tools.build.procs import DIST_DIR, WORK_DIR

ENTRY_SCRIPT: Final = "main.py"
COLLECT_NAME: Final = "app"              # dist/app/* is moved into the build folder
CONTENTS_DIR: Final = "_internal"
EXCLUDES: Final = ("tkinter", "_tkinter", "engine.tools", "PyInstaller")
SKIPPED_PACKAGES: Final = frozenset({"tools", "data"})     # under engine/
SKIPPED_MODULES: Final = frozenset({"__main__"})           # the frozen exe runs main.py
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


def version_text(*, title: str, version: str, file_version: str, exe_name: str) -> str:
    """The Windows version resource (PR-F42-20): Product name and File description = title,
    Product version = the version text, File version = ``file_version`` (``1.2.0.0``),
    Original filename = the exe name."""
    numbers = version_numbers(file_version)
    strings = [("FileDescription", title), ("FileVersion", file_version),
               ("InternalName", exe_name.removesuffix(".exe")),
               ("OriginalFilename", exe_name), ("ProductName", title),
               ("ProductVersion", version)]
    table = ",\n".join(f"          StringStruct({key!r}, {value!r})" for key, value in strings)
    return (
        "# UTF-8\n"
        "# Generated by vn-engine's build (engine/tools/build/spec.py).\n"
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        f"    filevers={numbers!r},\n"
        f"    prodvers={numbers!r},\n"
        "    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable('040904B0', [\n"
        f"{table}])]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])])\n"
        "  ]\n"
        ")\n"
    )


def spec_text(*, exe_stem: str, icon: Path | None, version_file: Path | None,
              hidden: Iterable[str] = (), root: Path | None = None) -> str:
    """The spec for ``exe_stem`` (the exe name without ``.exe``). ``icon`` and
    ``version_file`` are files in staging (None on platforms without them); ``hidden`` the
    plugins' standard-library modules."""
    base = Path(root) if root is not None else engine_root()
    data = base / "engine" / "data"
    hiddenimports = engine_modules(base) + sorted(set(hidden))
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
        f"    version={None if version_file is None else str(version_file)!r},\n"
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


def packer_argv(spec_file: Path, staging: Path) -> list[str]:
    """``python -E -B -m PyInstaller`` on ``spec_file`` with dist and work in staging."""
    staging = Path(staging)
    return [sys.executable, "-E", "-B", "-m", "PyInstaller", "--noconfirm",
            "--log-level", "WARN", "--distpath", str(staging / DIST_DIR),
            "--workpath", str(staging / WORK_DIR), str(spec_file)]


__all__ = ["COLLECT_NAME", "CONTENTS_DIR", "ENTRY_SCRIPT", "EXCLUDES", "engine_modules",
           "packer_argv", "spec_text", "version_numbers", "version_text"]

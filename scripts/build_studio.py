"""Build the Studio app: ``vn-engine Studio/vn-engine Studio.exe``, for people with no Python.

Usage (from the repository, with the build tool installed: see requirements-build.txt)::

    .venv/Scripts/python.exe scripts/build_studio.py --out <folder> [--replace] [--no-player]

The result is ``<folder>/vn-engine Studio/``: a PyInstaller one-folder app (windowed, the
engine's icon) whose exe opens Studio (``studio.py`` → ``engine.__main__.studio_app_main``)
and, with ``--child COMMAND …``, runs ``python -m engine COMMAND …`` for Studio's children.
It holds the whole ``engine`` package (Studio, the check job, the helper, Build game), the
whole standard library (a game's Python minigame hooks may import any of it), Tk/Tcl,
pygame-ce, ``engine/data`` (fonts, New game's sample and starter), the guides
(``docs/*.md``) and the example game (``game/`` without what runs write), plus:

- the editor-build marker, the module ``core.paths.EDITOR_BUILD_MODULE``, written only into
  this build's staging folder (it is nowhere in the repository, so no player build can
  contain it): ``paths.is_editor_build()`` is true only in this app (I-15);
- ``licenses/``: the notices a built game ships (``engine.tools.build.licenses``) and Tcl/Tk's;
- ``player/``: the prebuilt player runtime Build game copies, from
  ``engine.tools.build.runtime.build_player_runtime`` (``paths.player_runtime_dir``).

Dev only: this script isn't part of the app. It never writes in the repository; staging is
a folder beside the output, removed at the end.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from engine.core.paths import EDITOR_BUILD_MODULE, EDITOR_BUILD_VALUE  # noqa: E402

APP_NAME = "vn-engine Studio"
ENTRY_SCRIPT = "studio.py"
CONTENTS_DIR = "_internal"
LICENSES_DIR = "licenses"
PLAYER_DIR = "player"
# Guides that aren't for game makers (the architecture hub links into the private specs).
DOCS_SKIPPED = frozenset({"architecture.md"})
# Third-party packages in a dev environment that the app must never carry.
EXCLUDES = ("PyInstaller", "pytest", "_pytest", "pip", "setuptools", "pkg_resources",
            "pygments", "colorama", "execnet", "pluggy", "iniconfig", "packaging",
            "altgraph", "pefile", "win32ctypes", "xdist")
STDLIB_SKIPPED = frozenset({"__hello__", "__phello__", "_ctypes_test", "xxlimited",
                            "xxlimited_35", "xxsubtype", "_xxsubinterpreters",
                            "_xxinterpchannels", "_testbuffer", "_testcapi",
                            "_testclinic", "_testimportmultiple", "_testinternalcapi",
                            "_testmultiphase", "_testsinglephase", "idlelib", "test",
                            "turtledemo", "ensurepip", "lib2to3", "venv", "antigravity",
                            "this", "pydoc_data"})
STDLIB_TEST_DIRS = frozenset({"test", "tests", "idle_test"})
TCL_NOTICE = "Tcl-Tk.txt"
TCL_DLLS = frozenset({"tcl86t.dll", "tk86t.dll", "zlib1.dll"})
TCL_HEADER = ("Tcl/Tk (tcl86t.dll, tk86t.dll and the tcl/tk script libraries in _internal)\n"
              "Source: https://www.tcl-lang.org/  License: BSD-style (below).\n\n")


def say(text: str) -> None:
    print(f"build_studio: {text}", flush=True)


# --- What goes in ------------------------------------------------------------------------

def engine_modules() -> list[str]:
    """Every real package and module under ``engine`` (tools included, data left out)."""
    found: list[str] = []
    top = REPO / "engine"
    stack = [(top, ("engine",))]
    while stack:
        folder, parts = stack.pop()
        if not (folder / "__init__.py").is_file():
            continue
        found.append(".".join(parts))
        for entry in sorted(os.scandir(folder), key=lambda e: e.name):
            if entry.is_symlink():
                continue
            if entry.is_dir() and entry.name.isidentifier() and entry.name != "data":
                stack.append((Path(entry.path), (*parts, entry.name)))
            elif entry.is_file() and entry.name.endswith(".py"):
                stem = entry.name[:-3]
                if stem.isidentifier() and stem != "__init__":
                    found.append(".".join((*parts, stem)))
    return sorted(found)


def stdlib_modules() -> list[str]:
    """The whole standard library a minigame hook may import: the top-level names in
    ``sys.stdlib_module_names`` and each package's submodules (tests left out)."""
    import sysconfig

    stdlib = Path(sysconfig.get_paths()["stdlib"])
    found = {name for name in sys.stdlib_module_names
             if name.isidentifier() and name not in STDLIB_SKIPPED
             and not name.startswith("_test")}
    for top in sorted(found):
        package = stdlib / top
        if not (package / "__init__.py").is_file():
            continue
        stack = [(package, (top,))]
        while stack:
            folder, parts = stack.pop()
            for entry in os.scandir(folder):
                name = entry.name
                if entry.is_dir() and name.isidentifier() and name not in STDLIB_TEST_DIRS \
                        and (Path(entry.path) / "__init__.py").is_file():
                    found.add(".".join((*parts, name)))
                    stack.append((Path(entry.path), (*parts, name)))
                elif entry.is_file() and name.endswith(".py"):
                    stem = name[:-3]
                    if stem.isidentifier() and stem not in ("__init__", "__main__"):
                        found.add(".".join((*parts, stem)))
    return sorted(found)


def write_marker(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / f"{EDITOR_BUILD_MODULE}.py").write_text(
        '"""The Studio app\'s editor-build marker (scripts/build_studio.py; '
        'engine.core.paths.is_editor_build)."""\n'
        f"EDITOR_BUILD = {EDITOR_BUILD_VALUE!r}\n", encoding="utf-8")
    return folder


def write_icon(path: Path) -> Path:
    from engine.tools.build.icon import make_ico

    path.write_bytes(make_ico((REPO / "engine" / "data" / "icon.png").read_bytes()))
    return path


def copy_docs(folder: Path) -> Path:
    folder.mkdir(parents=True)
    for source in sorted((REPO / "docs").glob("*.md")):
        if source.name not in DOCS_SKIPPED and source.is_file() and not source.is_symlink():
            shutil.copyfile(source, folder / source.name)
    return folder


def copy_game(folder: Path) -> Path:
    from engine.tools.editor.gamesfolder import copy_example

    copy_example(folder, source=REPO / "game")
    return folder


def spec_text(*, staging: Path, marker: Path, icon: Path, docs: Path, game: Path) -> str:
    datas = [(str(REPO / "engine" / "data"), "engine/data"), (str(docs), "docs"),
             (str(game), "game"),
             # Build game's licence notices (engine.tools.build.licenses.NOTICES_DIR).
             (str(REPO / "engine" / "tools" / "build" / "notices"),
              "engine/tools/build/notices")]
    hidden = [*engine_modules(), *stdlib_modules(), EDITOR_BUILD_MODULE]
    return (
        "# Generated by scripts/build_studio.py. Do not edit.\n"
        "a = Analysis(\n"
        f"    [{str(REPO / ENTRY_SCRIPT)!r}],\n"
        f"    pathex=[{str(REPO)!r}, {str(marker)!r}],\n"
        "    binaries=[],\n"
        f"    datas={datas!r},\n"
        f"    hiddenimports={hidden!r},\n"
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
        f"    name={APP_NAME!r},\n"
        "    debug=False,\n"
        "    bootloader_ignore_signals=False,\n"
        "    strip=False,\n"
        "    upx=False,\n"
        "    console=False,\n"
        f"    icon={str(icon)!r},\n"
        f"    contents_directory={CONTENTS_DIR!r},\n"
        ")\n"
        "coll = COLLECT(\n"
        "    exe,\n"
        "    a.binaries,\n"
        "    a.datas,\n"
        "    strip=False,\n"
        "    upx=False,\n"
        "    upx_exclude=[],\n"
        f"    name={APP_NAME!r},\n"
        ")\n"
    )


# --- Licences and the player ---------------------------------------------------------------

def tcl_license() -> str | None:
    base = Path(sys.base_prefix) / "tcl"
    for candidate in (base / "tcl8.6" / "license.terms", base / "tk8.6" / "license.terms"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    return None


def write_licenses(app: Path) -> None:
    from engine.tools.build.licenses import Notice, Notices, collect_notices, write_notices

    internal = app / CONTENTS_DIR
    notices = collect_notices(dll_dirs=[internal, internal / "pygame"])
    unknown = [dll for dll in notices.unknown_dlls if dll.casefold() not in TCL_DLLS]
    if unknown:
        raise SystemExit(f"build_studio: no licence notice for {', '.join(unknown)}")
    files = list(notices.files)
    if (internal / "tcl86t.dll").exists() or any(
            dll.casefold() in TCL_DLLS for dll in notices.unknown_dlls):
        body = tcl_license() or "See https://www.tcl-lang.org/software/tcltk/license.html\n"
        text = (TCL_HEADER + body).replace("\r\n", "\n").replace("\n", "\r\n")
        files.append(Notice(TCL_NOTICE, text.encode("utf-8")))
    write_notices(app / LICENSES_DIR, Notices(tuple(sorted(files, key=lambda n: n.name.casefold())),
                                              ()))


def add_player(app: Path, staging: Path) -> bool:
    """``player/`` from the build tool's prebuilt runtime; False when this engine has none
    yet (``engine.tools.build.runtime.build_player_runtime`` missing)."""
    try:
        from engine.tools.build.runtime import build_player_runtime
    except ImportError:
        say("WARNING: engine.tools.build.runtime.build_player_runtime isn't there yet; "
            "the app has no player/ (Build game will need it)")
        return False
    runtime = Path(build_player_runtime(staging / "player-out"))
    shutil.move(str(runtime), str(app / PLAYER_DIR))
    return True


def folder_size(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())


# --- Main ----------------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="scripts/build_studio.py",
                                     description="Build the vn-engine Studio app.")
    parser.add_argument("--out", required=True, metavar="FOLDER",
                        help=f"where to put the '{APP_NAME}' folder")
    parser.add_argument("--replace", action="store_true",
                        help=f"replace an earlier '{APP_NAME}' folder there")
    parser.add_argument("--no-player", action="store_true",
                        help="leave out the prebuilt player (faster; Build game won't work)")
    args = parser.parse_args(argv)
    out = Path(args.out).absolute()
    target = out / APP_NAME
    if target.exists() and not args.replace:
        parser.error(f"{target} exists (use --replace)")
    if REPO in out.parents or out == REPO:
        if (REPO / "engine") in out.parents or out.is_relative_to(REPO / "game"):
            parser.error("--out can't be inside engine/ or game/")
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    staging = Path(tempfile.mkdtemp(prefix=".studio-build-", dir=out))
    try:
        marker = write_marker(staging / "marker")
        icon = write_icon(staging / "icon.ico")
        docs = copy_docs(staging / "docs")
        game = copy_game(staging / "game")
        spec = staging / "studio.spec"
        spec.write_text(spec_text(staging=staging, marker=marker, icon=icon, docs=docs,
                                  game=game), encoding="utf-8")
        say("running PyInstaller (a few minutes)")
        subprocess.run([sys.executable, "-E", "-B", "-m", "PyInstaller", "--noconfirm",
                        "--log-level", "WARN", "--distpath", str(staging / "dist"),
                        "--workpath", str(staging / "work"), str(spec)],
                       cwd=str(staging), check=True)
        app = staging / "dist" / APP_NAME
        write_licenses(app)
        if not args.no_player:
            add_player(app, staging)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(app), str(target))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    size = folder_size(target)
    say(f"done in {time.monotonic() - started:.0f} s: {target} ({size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""F42 P8: real builds (``-m build``; AC-F42-03, -06, -07, -11, -12, -22, -31, -38, -40).

These tests run ``python -m engine build`` for real (PyInstaller as a child), then run the
built exe. They need the pinned PyInstaller for the running interpreter
(``python -m pip install --require-hashes -r requirements-build.txt``) and are skipped
unless asked for: ``VN_BUILD=1`` or ``-m build`` (tests/conftest.py). CI's Windows build job
runs them. Windows only for now (the build makes a Windows exe).

Two games are built once per module, each into its own temp folder (never the repo):

- a copy of the example game (``game/``) with ``id = "p8-example"``, ``version =
  "1.2-beta"`` (AC-F42-31) and a probe plugin, ``minigames/p8_probe.py``, that imports
  ``sqlite3`` (the engine never does, AC-F42-11) and, when ``VN_P8_PROBE`` names a file,
  writes what the built game saw there: ``sys.path``, ``_MEIPASS``, where ``json``,
  ``pygame`` and ``encodings`` came from, and the SQLite version;
- F47's sample story (``engine/data/sample/``), made the way Studio's **New game** makes it.

The exe always runs with SDL's dummy drivers and ``APPDATA``/``LOCALAPPDATA`` in a temp
folder, so nothing reaches the real profile. ``--bench 1`` plays the game for a 5 s
warm-up and 1 s of measured frames, then quits 0.
"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from engine.core.paths import engine_root
from engine.tools.build import licenses, names, procs
from tests.tools.build.leakscan import LeakScanner, needle_forms

pytestmark = [pytest.mark.build,
              pytest.mark.skipif(sys.platform != "win32", reason="the build makes a Windows exe")]

BUILD_TIMEOUT_S = 1800
RUN_TIMEOUT_S = 180
TITLE = "Example Visual Novel"
VERSION = "1.2-beta"
APP_ID = "p8-example"
PROBE_ENV = "VN_P8_PROBE"
LAYOUT = {"_internal", "game", "licenses", "README.txt"}

PROBE = '''"""P8 probe (tests/tools/build/test_real_build.py): a plugin using sqlite3."""
import json
import os
import sqlite3
import sys

from engine.minigames.api import Minigame, Outcome, register

_OUT = os.environ.get("VN_P8_PROBE")
if _OUT:
    with sqlite3.connect(":memory:") as _db:
        _version = _db.execute("select sqlite_version()").fetchone()[0]
    with open(_OUT, "w", encoding="utf-8") as _stream:
        json.dump({"sqlite": _version, "path": sys.path,
                   "meipass": getattr(sys, "_MEIPASS", None),
                   "files": [getattr(sys.modules.get(name), "__file__", None)
                             for name in ("json", "pygame", "encodings")]},
                  _stream)


@register
class P8Probe(Minigame):
    name = "p8_probe"
    test_outcome = Outcome(0, ())
'''


@dataclass
class Built:
    game: Path            # the game folder that was built
    save_to: Path
    folder: Path          # <save_to>/<folder name>
    exe: Path
    zip: Path
    output: str           # the build command's output


def _need_tool() -> None:
    status = procs.tool_status()
    if not status.ok:
        pytest.fail(f"PyInstaller {status.wanted} is not installed for {sys.executable} "
                    f"(found {status.found}); install it with: python -m pip install "
                    "--require-hashes -r requirements-build.txt")


def _build(game: Path, save_to: Path) -> Built:
    _need_tool()
    env = procs.child_env()
    env.pop(PROBE_ENV, None)
    done = subprocess.run(
        [sys.executable, "-m", "engine", "build", str(game), "--out", str(save_to), "--zip"],
        cwd=engine_root(), env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=BUILD_TIMEOUT_S)
    output = done.stdout + done.stderr
    assert done.returncode == 0, output
    folders = [entry for entry in save_to.iterdir() if entry.is_dir()]
    assert len(folders) == 1, output
    folder = folders[0]
    exes = sorted(folder.glob("*.exe"))
    assert len(exes) == 1, sorted(p.name for p in folder.iterdir())
    return Built(game, save_to, folder, exes[0], save_to / names.zip_name(folder.name), output)


@pytest.fixture(scope="module")
def example_build(tmp_path_factory) -> Built:
    base = tmp_path_factory.mktemp("p8example")
    game = base / "P8 Lanterns Q7x"
    shutil.copytree(engine_root() / "game", game,                 # never the real meta folder
                    ignore=shutil.ignore_patterns("__pycache__", "characters", "logs"))
    config = game / "config.toml"
    text = config.read_text(encoding="utf-8")
    text = text.replace('version = "0.1.0"', f'version = "{VERSION}"\nid = "{APP_ID}"', 1)
    config.write_text(text, encoding="utf-8")
    (game / "minigames" / "p8_probe.py").write_text(PROBE, encoding="utf-8")
    return _build(game, base / "P8 Builds Q7x")


@pytest.fixture(scope="module")
def sample_build(tmp_path_factory) -> Built:
    from engine.tools.editor import files

    base = tmp_path_factory.mktemp("p8sample")
    game = files.new_game(base / "P8 Sample Q7x", files.TEMPLATE_SAMPLE)
    assert isinstance(game, Path), game
    return _build(game, base / "P8 Sample Builds Q7x")


def _run(exe: Path, args: list[str], tmp: Path, *, cwd: Path | None = None,
         extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run the built exe with dummy SDL drivers and per-user folders under ``tmp``."""
    env = procs.child_env()
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        folder = tmp / "profile" / key
        folder.mkdir(parents=True, exist_ok=True)
        env[key] = str(folder)
    env.update(SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", SDL_DIRECTINPUT_ENABLED="0")
    env.pop(PROBE_ENV, None)
    env.update(extra_env or {})
    return subprocess.run([str(exe), *args], cwd=cwd or tmp, env=env, capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=RUN_TIMEOUT_S)


def _log_tail(tmp: Path) -> str:
    logs = sorted((tmp / "profile" / "LOCALAPPDATA").rglob("*.log"))
    return "\n".join(path.read_text(encoding="utf-8", errors="replace")[-3000:] for path in logs)


def _needles(built: Built) -> list[str]:
    home = Path.home()
    return needle_forms([home, engine_root(), built.game, built.save_to, sys.prefix,
                         sys.base_prefix, sys.exec_prefix], [home.name])


def _under(path: str, root: Path) -> bool:
    path = os.path.normcase(os.path.abspath(path))
    root_text = os.path.normcase(str(root))
    return path == root_text or path.startswith(root_text + os.sep)


# --- AC-F42-03 ---------------------------------------------------------------------------------

@pytest.mark.parametrize("which", ["example_build", "sample_build"])
def test_ac_f42_03_built_folder_layout_and_the_exe_runs_the_game(which, request, tmp_path):
    built: Built = request.getfixturevalue(which)
    assert {p.name for p in built.folder.iterdir()} == LAYOUT | {built.exe.name}
    assert (built.folder / "game" / "config.toml").is_file()
    assert (built.folder / "game" / "script").is_dir()
    with zipfile.ZipFile(built.zip) as archive:
        assert f"{built.folder.name}/{built.exe.name}" in archive.namelist()
    done = _run(built.exe, ["--bench", "1"], tmp_path)
    assert done.returncode == 0, _log_tail(tmp_path)


# --- AC-F42-06 ---------------------------------------------------------------------------------

def test_ac_f42_06_dev_options_and_commands_are_not_accepted_by_the_built_exe(
        example_build, tmp_path):
    rejected = [["--start", "x"], ["--set", "a=1"], ["--seed", "1"], ["--no-persistent"],
                ["--playthrough", "1"], ["--report-to-editor"], ["edit"], ["check"],
                ["build"], ["run"],
                # F39 (07 I-9): defined only on main()'s `run` in dev runs, never frozen.
                ["--resume-from-editor"], ["--window-at", "1,1"],
                # F47 P2-F: Studio's Try it, likewise dev runs only.
                ["--try-stdin"],
                # F34: the Extras preview, likewise dev runs only.
                ["--extras"],
                # F36: Studio's Play replay, likewise dev runs only.
                ["--replay", "x"],
                # F41 AC-F41-15: the lint command, likewise dev runs only.
                ["lint"]]
    codes = {" ".join(args): _run(example_build.exe, args, tmp_path).returncode
             for args in rejected}
    assert codes == {key: 2 for key in codes}


# --- AC-F42-07 ---------------------------------------------------------------------------------

def test_ac_f42_07_bundle_has_no_dev_tools_tk_starter_or_sample(example_build):
    internal = example_build.folder / "_internal"
    files = [p.relative_to(internal).as_posix().casefold() for p in internal.rglob("*")]
    scan = LeakScanner([]).file(example_build.exe)
    modules = {name.casefold() for name in scan.members}
    assert any(name.startswith("engine.app") for name in modules)      # the PYZ was read
    assert not [m for m in modules if m.startswith(("engine.tools", "tkinter", "_tkinter"))]
    # AC-F40-04: the developer console (engine/tools/console) is never packaged.
    assert not [m for m in modules if "console" in m.split(".")]
    assert not [f for f in files if f.startswith(("engine/tools", "engine/data/starter",
                                                  "engine/data/sample"))]
    assert {p.name for p in (internal / "engine" / "data").iterdir()} == {"fonts", "icon.png"}
    tk = ("tkinter", "_tkinter", "tcl", "tk", "_tcl_data", "_tk_data", "tcl86t.dll",
          "tk86t.dll", "_tkinter.pyd")
    assert not [f for f in files if any(part.startswith(tk) for part in f.split("/"))]
    # P8 (spec.NETWORK_EXCLUDES): no OpenSSL or sockets unless a plugin may need them.
    assert not [f for f in files if f in ("_hashlib.pyd", "_ssl.pyd", "_socket.pyd",
                                          "libcrypto-3.dll", "libssl-3.dll")]


# --- AC-F42-11 ---------------------------------------------------------------------------------

def test_ac_f42_11_a_plugin_using_a_stdlib_module_the_engine_does_not_loads(
        example_build, tmp_path):
    assert not [p for p in (engine_root() / "engine").rglob("*.py")
                if "import sqlite3" in p.read_text(encoding="utf-8")]
    probe = tmp_path / "probe.json"
    done = _run(example_build.exe, ["--bench", "1"], tmp_path,
                extra_env={PROBE_ENV: str(probe)})
    assert done.returncode == 0, _log_tail(tmp_path)
    seen = json.loads(probe.read_text(encoding="utf-8"))
    assert seen["sqlite"].count(".") == 2
    assert (example_build.folder / "_internal" / "_sqlite3.pyd").is_file()


# --- AC-F42-12 (SEC-F42-10) ---------------------------------------------------------------------

def test_ac_f42_12_no_author_path_or_name_anywhere_in_the_build(example_build):
    built = example_build
    canary_code = "run the game in the game folder next to"      # cli.py, inside the PYZ
    # AC-F40-35: the developer console's Code hint (tools/console/texts.py) is nowhere.
    console_needle = "one line of python, like a $ line"
    scanner = LeakScanner([*_needles(built), canary_code, TITLE.casefold(), console_needle])
    result = scanner.folder(built.folder)
    leaks = [(where, needle) for where, needle in result.hits
             if needle not in (canary_code, TITLE.casefold())]
    assert leaks == []
    # The scan sees inside archives: a compressed PYZ member and the UTF-16 version resource.
    assert [w for w, n in result.hits if n == canary_code and "!PYZ" in w]
    assert (built.exe.name, TITLE.casefold()) in result.hits
    assert result.archives.get("carchive") == 1 and result.archives.get("pyz") == 1
    assert result.archives.get("zip", 0) >= 1                      # base_library.zip
    assert result.co_filenames
    assert not [name for name in result.co_filenames
                if os.path.isabs(name) or ":" in name or name.startswith(("/", "\\"))]
    left_behind = [p.name for p in built.folder.rglob("*")
                   if p.name == "direct_url.json" or p.suffix in (".spec", ".toc")
                   or p.name.startswith(("warn-", "xref-"))]
    assert left_behind == []


# --- AC-F42-22 ---------------------------------------------------------------------------------

def test_ac_f42_22_licenses_cover_python_pygame_its_libraries_fonts_and_engine(example_build):
    internal = example_build.folder / "_internal"
    shipped = {p.name for p in (example_build.folder / "licenses").iterdir()}
    dlls = {p.name.casefold() for folder in (internal, internal / "pygame")
            for p in folder.glob("*.dll")}
    assert "sdl2.dll" in dlls
    assert not [dll for dll in dlls if dll not in licenses.DLL_NOTICES]
    wanted = {licenses.DLL_NOTICES[dll] for dll in dlls}
    wanted |= {"Python.txt", "pygame-ce.txt", "PyInstaller.txt", "OFL.txt", "vn-engine.txt"}
    assert wanted <= shipped
    licence_text = (example_build.folder / "licenses" / "pygame-ce.txt").read_bytes()
    assert b"GNU LESSER GENERAL PUBLIC LICENSE" in licence_text


# --- AC-F42-31 ---------------------------------------------------------------------------------

def _version_resource(exe: Path) -> tuple[tuple[int, ...], dict[str, str]]:
    version = ctypes.WinDLL("version")
    version.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
    version.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                            ctypes.c_uint32, ctypes.c_void_p]
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                       ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.POINTER(ctypes.c_uint)]
    size = version.GetFileVersionInfoSizeW(str(exe), None)
    assert size
    data = ctypes.create_string_buffer(size)
    assert version.GetFileVersionInfoW(str(exe), 0, size, data)
    pointer, length = ctypes.c_void_p(), ctypes.c_uint()
    assert version.VerQueryValueW(data, "\\", ctypes.byref(pointer), ctypes.byref(length))
    fixed = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32 * 13)).contents
    numbers = (fixed[2] >> 16, fixed[2] & 0xFFFF, fixed[3] >> 16, fixed[3] & 0xFFFF)
    strings = {}
    for key in ("ProductName", "FileDescription", "ProductVersion", "FileVersion",
                "OriginalFilename"):
        if version.VerQueryValueW(data, f"\\StringFileInfo\\040904B0\\{key}",
                                  ctypes.byref(pointer), ctypes.byref(length)):
            strings[key] = ctypes.wstring_at(pointer.value, length.value).rstrip("\0")
    return numbers, strings


def test_ac_f42_31_exe_version_resource_from_title_and_version(example_build):
    numbers, strings = _version_resource(example_build.exe)
    assert numbers == (1, 2, 0, 0)
    assert strings == {"ProductName": TITLE, "FileDescription": TITLE,
                       "ProductVersion": VERSION, "FileVersion": "1.2.0.0",
                       "OriginalFilename": example_build.exe.name}


# --- AC-F42-38 (SEC-F42-01, -02, -14) -----------------------------------------------------------

def _snapshot(root: Path) -> dict[str, tuple]:
    found = {}
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if rel == "game/characters" or rel.startswith("game/characters/"):
            continue
        info = path.lstat()
        found[rel] = (path.is_dir(), info.st_size, info.st_mtime_ns)
    return found


def _plant(folder: Path, sentinel: Path) -> None:
    """Shadow modules that write ``sentinel`` only when imported under their stdlib name
    (in ``minigames/`` the loader runs them as plugins ``_vn_minigames.<name>``, which is
    F23's normal behaviour, not shadowing), and junk DLLs."""
    folder.mkdir(parents=True, exist_ok=True)
    shadow = ("import os\n"
              f"if __name__ in ('json', 'pygame', 'encodings', 'engine'):\n"
              f"    open({str(sentinel)!r} + '.' + __name__ + '.txt', 'w').close()\n")
    (folder / "json.py").write_text(shadow, encoding="utf-8")
    (folder / "pygame.py").write_text(shadow, encoding="utf-8")
    (folder / "encodings").mkdir(exist_ok=True)
    (folder / "encodings" / "__init__.py").write_text(shadow, encoding="utf-8")
    for dll in ("SDL2.dll", "python312.dll"):
        (folder / dll).write_bytes(b"MZ not a real DLL\0" * 64)


def test_ac_f42_38_built_game_ignores_environment_and_planted_files(example_build, tmp_path):
    app = tmp_path / "Lanterns copy"
    shutil.copytree(example_build.folder, app)
    exe = app / example_build.exe.name
    sentinel = tmp_path / "SENTINEL"
    cwd = tmp_path / "cwd"
    evil = tmp_path / "evil"
    for folder in (app, app / "game", app / "game" / "minigames", cwd, evil):
        _plant(folder, sentinel)
    (evil / "engine").mkdir()
    (evil / "engine" / "__init__.py").write_text(
        f"open({str(sentinel)!r} + '.engine.txt', 'w').close()\n", encoding="utf-8")
    startup = evil / "startup.py"
    startup.write_text(f"open({str(sentinel)!r} + '.startup.txt', 'w').close()\n",
                       encoding="utf-8")
    before = _snapshot(app)
    probe = tmp_path / "probe.json"
    hostile = {"PYTHONPATH": str(evil), "PYTHONHOME": str(evil),
               "PYTHONSTARTUP": str(startup), "PYTHONINSPECT": "1",
               "PYTHONUSERBASE": str(evil), "PYTHONDEVMODE": "1", PROBE_ENV: str(probe)}

    done = _run(exe, ["--bench", "1"], tmp_path, cwd=cwd, extra_env=hostile)

    assert done.returncode == 0, _log_tail(tmp_path)
    assert sorted(p.name for p in tmp_path.glob("SENTINEL*")) == []
    seen = json.loads(probe.read_text(encoding="utf-8"))
    internal = app / "_internal"
    assert _under(seen["meipass"], internal)
    assert seen["path"] and [p for p in seen["path"] if not _under(p, internal)] == []
    assert [f for f in seen["files"] if f is not None and not _under(f, internal)] == []
    assert _snapshot(app) == before


# --- AC-F42-40 (Build row: SEC-F42-10 on the zip) ----------------------------------------------

def test_ac_f42_40_leak_scan_of_the_zip_finds_no_needle(example_build):
    built = example_build
    with zipfile.ZipFile(built.zip) as archive:
        entries = archive.namelist()
    assert f"{built.folder.name}/_internal/vn-build.json" in entries
    assert all(e.startswith(built.folder.name + "/") and "\\" not in e for e in entries)
    result = LeakScanner(_needles(built)).file(built.zip)
    assert result.hits == []
    assert result.archives.get("carchive") == 1 and result.archives.get("pyz") == 1

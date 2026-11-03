"""F42 P4: pins, tool status, children, spec (AC-F42-23, -24, -39 build side)."""

import ast
import importlib.metadata
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from engine.core.paths import engine_root
from engine.core.redact import RedactRoot
from engine.tools.build import procs, spec

REPO = Path(__file__).resolve().parents[3]
HASH_RE = re.compile(r"--hash=sha256:[0-9a-f]{64}")
# PyInstaller 6.22.3's requirements on Windows, and theirs (AC-F42-23 "transitive too").
CLOSURE = {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "packaging", "setuptools",
           "pefile", "pywin32-ctypes"}


def _requirement_entries():
    entries, current = [], ""
    for raw in (REPO / "requirements-build.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("--hash") \
            else raw.rstrip()
        if not line.strip():
            continue
        if line.endswith("\\"):
            current += line[:-1] + " "
            continue
        entries.append((current + line).strip())
        current = ""
    assert current == ""
    return entries


def test_ac_f42_23_build_requirements_are_pinned_and_only_run_as_a_child():
    pins = {}
    for entry in _requirement_entries():
        requirement = entry.split("--hash", 1)[0].split(";", 1)[0].strip()
        assert re.fullmatch(r"[a-z0-9][a-z0-9.\-]*==[0-9][A-Za-z0-9.+\-]*", requirement), entry
        tokens = [t for t in entry.split() if t.startswith("--hash")]
        assert tokens and all(HASH_RE.fullmatch(t) for t in tokens), entry
        name, version = requirement.split("==")
        pins[name] = version
    assert set(pins) == CLOSURE
    assert pins["pyinstaller"] == procs.PYINSTALLER_VERSION
    major, minor = (int(p) for p in procs.PYINSTALLER_VERSION.split(".")[:2])
    assert major == 6 and minor >= 20

    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["dependencies"] == ["pygame-ce>=2.5.2,<2.6"]

    importers = []
    for path in (REPO / "engine").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(n.split(".")[0] == "PyInstaller" for n in names):
                importers.append(path)
    assert importers == []          # tools/build runs it as a child; nothing imports it


def test_ac_f42_24_missing_or_wrong_version_tool():
    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    assert procs.tool_status(version=missing).key == "B_NO_TOOL"
    status = procs.tool_status(version=lambda name: "6.0.0")
    assert (status.key, status.found, status.wanted) == ("B_TOOL_VERSION", "6.0.0",
                                                         procs.PYINSTALLER_VERSION)
    assert procs.tool_status(version=lambda name: procs.PYINSTALLER_VERSION).ok
    assert "PyInstaller" not in sys.modules


def test_ac_f42_39_build_side_children_spec_and_redaction(tmp_path, monkeypatch):
    game = tmp_path / "game"
    (game / "pip").mkdir(parents=True)
    (game / "requirements-build.txt").write_text("evil==1\n", encoding="utf-8")
    save_to = tmp_path / "builds"
    staging = save_to / ".Paper Lanterns 0.1.0 Windows.building-0123abcd"
    monkeypatch.setenv("PYTHONPATH", str(game))
    monkeypatch.setenv("PYTHONSTARTUP", str(game / "x.py"))
    monkeypatch.chdir(game)

    calls = []
    procs.spawn(["python", "-E", "x"], popen=lambda argv, **kw: calls.append((argv, kw)))
    argv, kwargs = calls[0]
    assert argv == ["python", "-E", "x"] and kwargs["shell"] is False
    assert kwargs["cwd"] == str(engine_root())
    assert not [key for key in kwargs["env"] if key.upper().startswith("PYTHON")]

    install = procs.install_argv()
    assert install[1:4] == ["-E", "-m", "pip"]
    assert {"--require-hashes", "--only-binary=:all:", "--no-input"} <= set(install)
    assert install[-2:] == ["-r", str(engine_root() / "requirements-build.txt")]
    assert not {"-i", "--index-url", "--extra-index-url", "--trusted-host", "--find-links",
                "-f", "--user"} & set(install)

    spec_file = staging / "spec" / "game.spec"
    packer = spec.packer_argv(spec_file, staging)
    assert packer[1:5] == ["-E", "-B", "-m", "PyInstaller"]
    for flag in ("--distpath", "--workpath"):
        assert Path(packer[packer.index(flag) + 1]).is_relative_to(staging)
    text = spec.spec_text(exe_stem="Paper Lanterns", icon=staging / "spec" / "icon.ico",
                          version_file=staging / "spec" / "version.txt", hidden=["json"])
    for item in [*install, *packer, text]:
        assert str(game) not in item
    tree = ast.parse(text)                                # PyInstaller evaluates it
    calls_by_name = {n.func.id: n for n in ast.walk(tree)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    analysis = {k.arg: ast.literal_eval(k.value) for k in calls_by_name["Analysis"].keywords}
    assert analysis["pathex"] == []
    assert [dest for _, dest in analysis["datas"]] == ["engine/data/fonts", "engine/data"]
    assert {"tkinter", "engine.tools", "PyInstaller"} <= set(analysis["excludes"])
    hidden = analysis["hiddenimports"]
    assert "engine.core.paths" in hidden and "json" in hidden
    assert not [m for m in hidden if m.startswith(("engine.tools", "engine.data"))]
    exe = {k.arg: k.value for k in calls_by_name["EXE"].keywords}
    assert ast.literal_eval(exe["upx"]) is False and ast.literal_eval(exe["console"]) is False

    hostile = "x', 'y'); import os  #"
    version = spec.version_text(title=hostile, version="1.2-beta", file_version="1.2.0.0",
                                exe_name="x.exe")
    strings = [n.value for n in ast.walk(ast.parse(version)) if isinstance(n, ast.Constant)]
    assert hostile in strings and "1.2-beta" in strings
    assert not [n for n in ast.walk(ast.parse(version)) if isinstance(n, ast.Import)]

    home = Path.home()
    lines = [f"line {i}" for i in range(300)] + [
        f"WARNING: {staging / 'work' / 'app' / 'warn-app.txt'}",
        f"copying {save_to}\\x and {staging}", f"python at {home / 'AppData' / 'py'}"]
    roots = [*procs.build_roots(save_to, staging), RedactRoot("~", str(home))]
    tail = procs.redacted_tail(lines, roots)
    assert len(tail) == 200
    joined = "\n".join(tail)
    assert str(tmp_path) not in joined and str(home) not in joined
    assert "<work>" in joined and "<save-to>" in joined and "<staging>" in joined


def test_kill_tree_stops_a_child_and_its_grandchild():
    code = ("import subprocess, sys, time; "
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            "print(p.pid, flush=True); time.sleep(60)")
    proc = procs.spawn([sys.executable, "-c", code], stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL)
    grandchild = int(proc.stdout.readline())
    procs.kill_tree(proc)
    assert proc.poll() is not None
    proc.stdout.close()
    if sys.platform == "win32":
        listed = subprocess.run(["tasklist", "/FI", f"PID eq {grandchild}", "/NH"],
                                capture_output=True, text=True).stdout
        assert str(grandchild) not in listed
    else:
        import os
        import time
        for _ in range(50):
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("grandchild still running")

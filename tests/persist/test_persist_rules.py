"""AC-F12-43 — no code from the file; import rules (SEC-F12-01 (a, b); TR-F12-10 as narrowed by
``07`` I-5; design §7 "Never"). F12 checklist step 6.

AST checks over ``engine/persist/**``, ``runtime/persistent.py``, and ``core/safefile.py``,
plus ``app/persistence.py``'s own rule (``04`` §3: it reaches the file only through
``persist`` and ``core``). The subprocess half reads every default-tier hostile input under
an audit hook (``tests/persist/audit_read.py``; ``slow``: about 2 s)."""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "engine"
SCOPE = sorted((ENGINE / "persist").rglob("*.py")) + [ENGINE / "runtime" / "persistent.py",
                                                      ENGINE / "core" / "safefile.py"]
BANNED_MODULES = {"pickle", "marshal", "shelve", "importlib", "ctypes"}
BANNED_CALLS = {"eval", "exec", "compile", "__import__"}


def _imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "engine":
                found.extend((node.lineno, f"engine.{alias.name}") for alias in node.names)
            else:
                found.append((node.lineno, node.module))
    return found


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def test_ac43_no_code_loading_imports_or_calls():
    bad = []
    for path in SCOPE:
        for line, name in _imports(path):
            if name.split(".")[0] in BANNED_MODULES:
                bad.append(f"{_rel(path)}:{line}: imports {name}")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else (
                    func.attr if isinstance(func, ast.Attribute) else None)
                if name in BANNED_CALLS and not (isinstance(func, ast.Attribute)
                                                 and name == "compile"
                                                 and ast.unparse(func.value) == "re"):
                    bad.append(f"{_rel(path)}:{node.lineno}: calls {name}")
    assert bad == []


def test_ac43_the_store_has_no_clock_thread_or_file_api():
    """``07`` I-5: the ban on ``os``, ``io``, and ``pathlib`` applies to the store's module."""
    names = {name.split(".")[0] for _, name in _imports(ENGINE / "runtime" / "persistent.py")}
    assert names.isdisjoint({"time", "threading", "os", "io", "pathlib"})


def test_ac43_persist_has_no_pygame_and_only_the_writer_has_a_thread():
    threaded = []
    for path in sorted((ENGINE / "persist").rglob("*.py")) + [ENGINE / "runtime" / "persistent.py"]:
        names = {name.split(".")[0] for _, name in _imports(path)}
        assert "pygame" not in names, _rel(path)
        if names & {"threading", "_thread", "concurrent"}:
            threaded.append(_rel(path))
    assert threaded == ["engine/persist/writer.py"]


def test_app_persistence_uses_only_persist_core_and_the_store():
    for _, name in _imports(ENGINE / "app" / "persistence.py"):
        if name.startswith("engine."):
            assert name.startswith(("engine.persist", "engine.core", "engine.runtime.persistent",
                                    "engine.app.app")), name
        else:
            assert name.split(".")[0] in {"logging", "math", "collections", "dataclasses",
                                          "pathlib", "typing"}, name


@pytest.mark.slow                      # a subprocess reading 55 inputs: about 2 s
def test_ac43_reading_every_hostile_input_runs_no_code_and_opens_nothing_else():
    done = subprocess.run([sys.executable, "-m", "tests.persist.audit_read"], cwd=REPO,
                          capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stderr[-3000:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["rows"] >= 40
    assert result["events"] == []
    assert set(result["outcomes"].values()) <= {"writable", "read only"}

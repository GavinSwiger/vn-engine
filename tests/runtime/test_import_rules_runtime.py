"""TR-F03-05 / AC-F03-68 (import half): ``engine/runtime/`` imports none of the banned
modules and, from the engine, only ``engine.script`` and ``engine.core`` (ADR-0002).

``tests/test_import_rules.py`` (the full ADR-0002 table, AC-F01-49) also checks the engine
packages and pygame; this scan adds the AC's banned standard-library modules (``time``,
``random``, ``secrets``, ``threading``, ``_thread``, ``datetime``) and literal
``__import__``/``import_module`` calls.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "engine" / "runtime"
BANNED = frozenset(("pygame", "time", "random", "secrets", "threading", "_thread", "datetime"))
ENGINE_ALLOWED = ("engine.runtime", "engine.script", "engine.core")


def imported_modules(source: str, package: str) -> list[str]:
    """Every module an AST imports, absolute, including ``__import__("x")`` and
    ``importlib.import_module("x")`` with a literal name."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1])
                module = f"{base}.{module}" if module else base
            found.append(module)
            # ``from engine import render`` imports engine.render
            found.extend(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else "")
            arg = node.args[0]
            if name in ("__import__", "import_module") and isinstance(arg, ast.Constant) \
                    and isinstance(arg.value, str):
                found.append(arg.value)
    return found


def problems(module: str) -> str | None:
    top = module.split(".")[0]
    if top in BANNED:
        return f"banned module {module}"
    if top == "engine" and module != "engine" and not module.startswith(
            tuple(p + "." for p in ENGINE_ALLOWED) + ENGINE_ALLOWED):
        return f"engine package not allowed: {module}"
    return None


def runtime_files() -> list[Path]:
    return sorted(RUNTIME.rglob("*.py"))


def test_runtime_package_exists():
    assert (RUNTIME / "__init__.py").is_file()
    assert len(runtime_files()) >= 5


def test_runtime_imports_tr_f03_05():
    bad = [f"{path.relative_to(RUNTIME).as_posix()}: {problem}" for path in runtime_files()
           for problem in map(problems, imported_modules(path.read_text(encoding="utf-8"),
                                                         "engine.runtime")) if problem]
    assert bad == []


@pytest.mark.parametrize("source, bad", [
    ("import time", True),
    ("import time as t", True),
    ("from time import sleep", True),
    ("from datetime import datetime", True),
    ("import _thread", True),
    ("import pygame.display", True),
    ("import random", True),
    ("import secrets", True),
    ("import threading", True),
    ("__import__('time')", True),
    ("import importlib; importlib.import_module('random')", True),
    ("from engine.app import story", True),
    ("from engine import render", True),
    ("from .. import app", True),
    ("from ..ui import screen", True),
    ("import engine.persist", True),
    ("from engine.core.errors import UserFacingError", False),
    ("from engine.script.words import ENGINE_NAMES", False),
    ("from . import values", False),
    ("from .values import freeze", False),
    ("import math, json, re", False),
    ("import timeit", False),
])
def test_scanner_finds_bad_imports(source, bad):
    found = imported_modules(source, "engine.runtime")
    assert any(problems(m) for m in found) is bad


def test_runtime_imports_without_pygame():
    """AC-F03-68 (phase 1 half): every runtime module imports with pygame blocked."""
    names = sorted(p.stem for p in runtime_files() if p.stem != "__init__")
    # Plain import statements: the same imports through an ``__import__`` loop took twice
    # as long on Windows (0.43 s against 0.20 s per launch, measured in F02 Step 11).
    code = ("import sys; sys.modules['pygame'] = None\n"
            + "".join(f"import engine.runtime.{name}\n" for name in names)
            + "print('ok')")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=60, cwd=ROOT)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"

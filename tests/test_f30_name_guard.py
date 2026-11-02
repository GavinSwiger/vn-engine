"""F30 step 1 — AC-F30-07: tests never read the real login name (SEC-F30-11).

A static scan over ``tests/``: every test module that names ``username``, ``UsernameSource``,
or the test name applies the name guard (``tests/fakes/username.py``) at module level or
through its folder's ``conftest.py``; every ``UsernameSource(`` in tests passes ``read=``;
and nothing under ``tests/fixtures/F30/`` holds the test name or a flagged span with
anything but a fallback word. ``test_privacy_ast.py`` holds F01's
``test_runtime_identity_is_not_reported``, the one real read, so it is exempt."""

import ast
import getpass
import json
from pathlib import Path

import pytest

from tests.fakes.username import RealNameRead, no_real_username  # noqa: F401  (name guard)

TESTS = Path(__file__).resolve().parent
EXEMPT = {"test_privacy_ast.py"}
MARKERS = ("username", "UsernameSource", "Zq9Name")
FALLBACK_WORDS = {"friend", "pal"}
GUARD = "no_real_username"


def _applies_guard(source: str) -> bool:
    tree = ast.parse(source)
    for node in tree.body:                       # module level only
        if isinstance(node, ast.ImportFrom) and node.module == "tests.fakes.username" \
                and any(alias.name == GUARD for alias in node.names):
            return True
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets) \
                and GUARD in ast.unparse(node.value) and "usefixtures" in ast.unparse(node.value):
            return True
    return False


def _guarded_by_conftest(path: Path) -> bool:
    for folder in path.parents:
        conftest = folder / "conftest.py"
        if conftest.exists() and _applies_guard(conftest.read_text(encoding="utf-8")):
            return True
        if folder == TESTS:
            return False
    return False


def _flagged_texts(value) -> list[str]:
    if isinstance(value, dict):
        # A saved NVL span ({"text", "username": true}) or a canonical command's Span, whose
        # flag is in its "style" (F30 s3's golden).
        style = value.get("style")
        flagged = value.get("username") is True or (isinstance(style, dict)
                                                    and style.get("username") is True)
        found = [value.get("text")] if flagged else []
        return found + [t for k, v in value.items() if k != "style" for t in _flagged_texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in _flagged_texts(v)]
    return []


def test_ac_f30_07_tests_never_read_the_real_name():
    # The guard itself: a BaseException, so `except Exception` can't swallow it.
    assert not issubclass(RealNameRead, Exception)
    with pytest.raises(RealNameRead):
        getpass.getuser()

    unguarded, no_read, scanned = [], [], []
    for path in sorted(TESTS.rglob("*.py")):
        rel = path.relative_to(TESTS).as_posix()
        source = path.read_text(encoding="utf-8")
        is_test = path.name.startswith("test_")
        if is_test and path.name not in EXEMPT and any(m in source for m in MARKERS) \
                and not (_applies_guard(source) or _guarded_by_conftest(path)):
            unguarded.append(rel)
        elif is_test and any(m in source for m in MARKERS):
            scanned.append(rel)
        if "UsernameSource(" in source:
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Call) and ast.unparse(node.func).endswith(
                        "UsernameSource") and not any(k.arg == "read" for k in node.keywords):
                    no_read.append(f"{rel}:{node.lineno}")
    assert unguarded == []
    assert no_read == []
    assert {"meta/test_username.py", "core/test_config_meta.py"} <= set(scanned)

    fixtures = TESTS / "fixtures" / "F30"
    leaks, flagged = [], []
    for path in sorted(fixtures.rglob("*")):
        if not path.is_file() or path.suffix == ".pyc":
            continue
        data = path.read_bytes()
        if b"zq9name" in data.lower():
            leaks.append(path.name)
        if path.suffix == ".json":
            flagged += [t for t in _flagged_texts(json.loads(data)) if t not in FALLBACK_WORDS]
    assert leaks == [] and flagged == []

"""F48 step S1: ``core/redact.set_secret`` and ``KEY_SHAPE_RE`` (04 §3.3; SEC-F48-14;
07 I-3). A registered key becomes ``<key>`` in every ``redact()``/``echo()`` until its slot
is cleared; API-key-shaped text is masked always; only ``tools.assistant`` registers keys;
F48's ``core`` additions import nothing a network-free build leaves out."""

import ast
from pathlib import Path

import pytest

from engine.core import redact as r
from engine.core.paths import engine_root
from engine.tools.build.spec import NEEDS_NETWORK

ANT = "sk-ant-api03-Zq9" + "x" * 40
OAI = "sk-proj-" + "Ab1_-" * 8
LOCAL = "loc4lK3y!~value"          # a compatible server's key: any shape, matched exactly


def test_a_registered_secret_is_replaced_everywhere():
    r.install(r.Redactor((r.RedactRoot("<game>", "C:\\Games\\Lantern"),), home_name=None,
                         case_insensitive=True))
    r.set_secret("compatible http://localhost:8080", LOCAL)
    assert r.redact(f"401: bad key {LOCAL}.") == "401: bad key <key>."
    assert r.redact(f"C:\\Games\\Lantern\\{LOCAL}.txt") == "<game>\\<key>.txt"
    assert r.echo(f"x{LOCAL}y\n") == "x<key>y\\n"
    assert r.redact(LOCAL.upper()) == LOCAL.upper()             # exact, case-sensitive

    # Several slots at once; it survives install(); None or "" clears one slot only.
    r.set_secret("anthropic", ANT)
    r.install(r.Redactor((), home_name=None, case_insensitive=False))
    assert r.redact(f"{LOCAL} {ANT}") == "<key> <key>"
    r.set_secret("compatible http://localhost:8080", None)
    assert r.redact(LOCAL) == LOCAL
    assert r.redact(ANT) == "<key>"
    r.set_secret("anthropic", "")
    r.set_secret("anthropic", None)                             # clearing twice is fine
    assert r.redact(ANT) == "<key>"                             # still masked by its shape
    assert r._secret_re is None

    # Regex characters in a key are literal; a replaced slot forgets the old value.
    r.set_secret("openai", "a.b+(c)*d?")
    assert r.redact("a.b+(c)*d? axb+(c)*d?") == "<key> axb+(c)*d?"
    r.set_secret("openai", "another-key-1")
    assert r.redact("a.b+(c)*d?") == "a.b+(c)*d?"
    r.set_secret("openai", None)


@pytest.mark.parametrize("slot, value", [
    ("", "longenough"), (None, "longenough"), ("anthropic", "short7!"),
    ("anthropic", b"bytes-key-1"), ("anthropic", 12345678)])
def test_bad_secrets_are_refused(slot, value):
    with pytest.raises(ValueError):
        r.set_secret(slot, value)
    assert r._secret_re is None


@pytest.mark.parametrize("text, expected", [
    (f"key={ANT};", "key=<key>;"),
    (f'"{OAI}"', '"<key>"'),
    ("sk-ant-x\r\nX-Evil: 1", "<key>\r\nX-Evil: 1"),
    ("Bearer sk-" + "a" * 20, "Bearer <key>"),
    ("sk-" + "a" * 48 + "é", "<key>é"),
    ("(sk-proj-abc)", "(<key>)"),
    # Not key shapes: too short, inside a word, or no key character after the prefix.
    ("sk-" + "a" * 19, "sk-" + "a" * 19),
    ("task-ant-" + "a" * 30, "task-ant-" + "a" * 30),
    ("disk-" + "a" * 30, "disk-" + "a" * 30),
    ("the sk-ant-… prefix", "the sk-ant-… prefix"),
    ("", ""),
])
def test_key_shapes_are_masked_in_every_redact(text, expected):
    assert r.redact(text) == expected
    assert r.KEY_SHAPE_RE.pattern.count("sk-") == 1             # one constant, one shape


def test_only_tools_assistant_calls_set_secret():
    """07 I-3: no module outside ``engine/tools/assistant`` imports or calls ``set_secret``."""
    root = engine_root() / "engine"
    allowed = root / "tools" / "assistant"
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.is_relative_to(allowed) or path == root / "core" / "redact.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.Attribute):
                names = [node.attr]
            elif isinstance(node, ast.Name):
                names = [node.id]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names = [node.value]
            if "set_secret" in names:
                found.append(f"{path.relative_to(root).as_posix()}:{node.lineno}")
    assert found == []


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module)
    return roots


@pytest.mark.parametrize("module", ["core/redact.py", "core/paths.py"])
def test_f48_core_additions_import_no_network_module(module):
    """07 I-3: ``NEEDS_NETWORK`` (``hashlib`` included) stays out of the F48 ``core``
    modules, at module and function level, so a build without them still runs."""
    imported = _imported_roots(engine_root() / "engine" / module)
    assert {name for name in imported
            if any(name == bad or name.startswith(bad + ".") for bad in NEEDS_NETWORK)} == set()

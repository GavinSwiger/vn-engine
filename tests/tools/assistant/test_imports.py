"""F48 S2: the assistant package's own import rules (04 §3; the S2 half of AC-F48-01, which
W1 completes in ``tests/test_import_rules.py``)."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[3] / "engine" / "tools" / "assistant"
BANNED = ("tkinter", "pygame", "engine.runtime", "engine.app", "engine.meta",
          "engine.tools.check")
NETWORK = ("socket", "ssl", "http", "urllib")
EDITOR_ALLOWED = {"checker", "document", "scenes", "scriptedit", "files", "config_help", "cleanup",
                  "assist", "dbmodel", "declarations"}


def _imports(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path.name}: relative import"
            found.append(node.module or "")
            if node.module == "engine.tools.editor":
                found += [f"engine.tools.editor.{alias.name}" for alias in node.names]
    return found


def test_assistant_imports_follow_04_section_3():
    modules = sorted(PACKAGE.rglob("*.py"))
    assert modules
    for path in modules:
        in_providers = "providers" in path.relative_to(PACKAGE).parts
        for name in _imports(path):
            top = name.split(".")[0]
            assert not any(name == b or name.startswith(b + ".") for b in BANNED), \
                f"{path.name} imports {name}"
            if not in_providers:
                assert top not in NETWORK, f"{path.name} imports {name}"
            if name.startswith("engine.tools.editor."):
                assert name.split(".")[3] in EDITOR_ALLOWED, f"{path.name} imports {name}"
            if name.startswith("engine.tools.") and not name.startswith(
                    ("engine.tools.editor", "engine.tools.assistant", "engine.tools.build")):
                raise AssertionError(f"{path.name} imports {name}")
            if name.startswith("engine.tools.build"):
                assert name == "engine.tools.build.procs", f"{path.name} imports {name}"

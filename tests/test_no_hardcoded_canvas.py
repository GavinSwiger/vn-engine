"""The canvas size is defined in one place: AC-F01-48 (TR-F01-05, Q4)."""

import ast
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent / "engine"
ALLOWED = ENGINE / "core" / "constants.py"


def canvas_literals(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and type(node.value) in (int, float)
            and node.value in (1280, 720)]


def test_no_1280_or_720_outside_constants():
    found = {str(path.relative_to(ENGINE)): lines for path in sorted(ENGINE.rglob("*.py"))
             if path != ALLOWED and (lines := canvas_literals(path))}
    assert found == {}


def test_constants_defines_the_canvas():
    assert canvas_literals(ALLOWED)

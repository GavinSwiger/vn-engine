"""F17 ``script/nvl.py``: the ``nvl`` statement, its placement, and voice (``06-acceptance.md``
AC-F17-01). E210 and E211 (AC-F17-02) are rows of ``tests/fixtures/F02/messages/cases.toml``
(``feature = "F17"``), run by ``test_messages.py``. Template N is ``tests/fixtures/F17/
template/`` (06 §0.4)."""

from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script import load_story
from engine.script.diagnostics import ScriptError
from engine.script.menu import Menu
from engine.script.nodes import If, Say
from engine.script.nvl import Nvl
from tests.script.helpers import template_n

E174 = ("only choices can go directly in a menu, after one optional question line. Indent "
        "this line inside a choice, or move it above menu:.")


def _load(root: Path, **edit):
    script = root / "script"
    script.mkdir(parents=True)
    (root / "config.toml").write_text("", encoding="utf-8")
    (script / "main.vns").write_bytes(template_n(**edit).encode("utf-8"))
    return load_story(GamePaths(root.resolve()))


def _nvls(program) -> list[tuple[int, str, object]]:
    """Every ``Nvl`` in the program: (line, action, the statement holding its block)."""
    out = []

    def walk(block, owner):
        for stmt in block:
            if type(stmt) is Nvl:
                out.append((stmt.line, stmt.action, owner))
            for inner in stmt.blocks():
                walk(inner, stmt)

    for label in program.labels.values():
        walk(label.block, None)
    return sorted(out, key=lambda item: item[0])


def _say(program, text: str) -> Say:
    (found,) = [s for s in program.iter_statements() if type(s) is Say and s.text == text]
    return found


ROWS = [
    ("template", {}),
    ("comment", {"replace": {7: "    nvl on  # start the diary"}}),
    ("nested", {"replace": {7: "    if wish:⏎[8]nvl on",
                            18: '            $ wish = "opened"⏎[12]nvl clear'}}),
    ("in menu", {"replace": {16: "        nvl on"}}),
    ("voice", {"replace": {7: '    voice "v1.ogg"⏎[4]nvl on'}}),
    ("not reserved", {"T": "default clear = 1", "replace": {8: '    "{var=clear}"'}}),
]


@pytest.mark.parametrize("name, edit", ROWS, ids=[row[0] for row in ROWS])
def test_ac_f17_01_the_statement_its_placement_and_voice(tmp_path, name, edit):
    result = _load(tmp_path, **edit)
    codes = [e.code for e in result.errors]
    assert "E32" not in codes
    if name == "in menu":
        assert [(e.code, e.line, e.message) for e in result.errors] == [("E174", 16, E174)]
        assert isinstance(result.errors[0], ScriptError)
        return
    assert codes == [] and result.program is not None, [e.format() for e in result.errors]
    program = result.program
    nvls = _nvls(program)
    if name == "template":
        assert [(line, action) for line, action, _ in nvls] == [(7, "on"), (11, "clear"),
                                                                 (22, "off")]
        assert all(owner is None for _, _, owner in nvls)
        assert [s.identity_key() for s in program.iter_statements() if type(s) is Nvl] == [
            ("nvl", "on"), ("nvl", "clear"), ("nvl", "off")]
    elif name == "comment":
        assert nvls[0][:2] == (7, "on")
    elif name == "nested":
        (_, on, in_if), (_, clear, in_choice) = [n for n in nvls if n[0] in (8, 20)]
        assert (on, clear) == ("on", "clear")
        assert type(in_if) is If and type(in_choice) is Menu
    elif name == "voice":
        assert not [w for w in result.warnings if w.code.startswith("W2")]
        assert _say(program, "The festival comes once a year.").voice == "v1.ogg"
    elif name == "not reserved":
        assert "clear" in {d.name for d in program.defaults}
        assert [action for _, action, _ in nvls] == ["on", "clear", "off"]

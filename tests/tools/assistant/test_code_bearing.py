"""F48 step S5: model-written code never runs before the author acts (AC-F48-18; 04 §7.2;
SEC-F48-04 as amended in 05 §10; AB-04, AB-21)."""

from engine.script import statements
from engine.script.statement_docs import docs_for
from engine.tools.assistant import edits
from engine.tools.assistant.edits import CODE_NOTICE, NO_CODE_RUN, code_bearing
from engine.tools.assistant.tools import MODE_MCP, MODE_PANE, MODE_READ_ONLY, ToolBox
from engine.tools.editor.scriptedit import LineEdit
from tests.tools.assistant.assist_games import disk, pane, studio
from tests.tools.assistant.test_tools import Writer

MAIN = "script/main.vns"
CH2 = "script/ch2.vns"


def variants(sentinel) -> dict[str, list[dict]]:
    """AB-04's proposals, each writing ``sentinel`` if it ever ran."""
    code = f"open({str(sentinel)!r}, 'w')"
    return {
        "define": [{"file": MAIN, "old_text": "default trust = 0",
                    "new_text": f"default trust = 0\ndefine leak = {code}"}],
        "default": [{"file": MAIN, "old_text": "default trust = 0",
                     "new_text": f"default trust = {code}"}],
        "$": [{"file": CH2, "old_text": '    "The river."',
               "new_text": f'    "The river."\n    $ leak = {code}'}],
        "python block": [{"file": MAIN, "old_text": "default trust = 0",
                          "new_text": f"default trust = 0\npython:\n    leak = {code}"}],
        "new file and include": [
            {"file": "script/evil.vns", "old_text": "",
             "new_text": f'define leak = {code}\nlabel evil:\n    "Evil."\n'},
            {"file": MAIN, "old_text": 'include "ch2.vns"',
             "new_text": 'include "ch2.vns"\ninclude "evil.vns"'}],
    }


# --- AC-F48-18 (AB-04): no sentinel in the armed pane, MCP, or MCP --read-only ------------------

def test_ac18_code_in_a_proposal_never_runs_before_apply(tmp_path):
    sentinel = tmp_path / "ran.txt"
    for mode in ("armed pane", "mcp", "read-only"):
        game = studio(tmp_path, mode.replace(" ", "_"))
        if mode == "armed pane":
            box = ToolBox(pane(game, armed=True, runner="real"), MODE_PANE)
        else:
            box = ToolBox(disk(game, "real"), MODE_MCP if mode == "mcp" else MODE_READ_ONLY,
                          writer=Writer() if mode == "mcp" else None)
        for name, changes in variants(sentinel).items():
            shown = box.call("propose_edit", {"summary": name, "changes": changes})
            if name == "python block":          # not a statement: refused, never checked
                assert shown.is_error and "doesn't parse" in shown.text, shown.text
            else:
                assert not shown.is_error, (mode, name, shown.text)
                assert NO_CODE_RUN in shown.text and CODE_NOTICE in shown.text
            assert not sentinel.exists(), (mode, name)
        box.ws.checks.stop()
    # The control: the same define on disk, checked with the launch phase, does run.
    game = studio(tmp_path, "control")
    main = game / "script" / "main.vns"
    main.write_text(main.read_text(encoding="utf-8").replace(
        "default trust = 0", f"default trust = 0\ndefine leak = open({str(sentinel)!r}, 'w')"),
        encoding="utf-8")
    assert disk(game, "real").base_check().ok
    assert sentinel.exists()


# --- AC-F48-18 (AB-21): the registry table, failing closed -------------------------------------

BASE = ["label start:", '    "Hi."']


def _flagged(lines: list[str]) -> tuple[bool, bool]:
    """(code-bearing, parses cleanly) for ``lines`` added after BASE."""
    nodes, errors = edits._parse("script/t.vns", "\n".join(BASE + lines), ())
    return code_bearing("script/t.vns", BASE, [LineEdit(3, 2, tuple(lines))]), not errors


def test_ac18_every_statement_the_launch_or_python_evaluates_is_flagged():
    clean: set[str] = set()
    for word, spec in statements._REGISTRY.items():
        top = spec.placement in ("top", "either") and word != "label"
        python = spec.tail.startswith("py_")
        if not (top or python):
            continue
        fixtures: list[list[str]] = []
        for doc in docs_for(word):
            example = doc.example.split("\n")
            if top:
                fixtures.append(example)
                fixtures += [[line.strip()] for line in example
                             if line.strip().startswith(word + " ")]
            if python:
                fixtures.append(["    " + line for line in example])
        assert fixtures, word
        for lines in fixtures:
            flagged, parses = _flagged(lines)
            assert flagged, (word, lines)
            if parses:
                clean.add(word)
    # Every top-level declaration and Python-tailed statement with a standalone form was
    # flagged as parsed, not only by failing closed.
    assert {"default", "define", "if", "elif", "image", "include", "lock", "minigame",
            "points"} <= clean, clean


def test_ac18_a_parse_error_or_a_line_in_no_node_fails_closed(monkeypatch):
    say = [LineEdit(2, 2, ('    "Hello."',))]
    assert not code_bearing("script/t.vns", BASE, say)
    broken = ["label start:", '    "Hi."', "label other:", '    "unclosed']
    assert code_bearing("script/t.vns", broken, say)        # an error before/after the change
    monkeypatch.setattr(edits, "_parse", lambda ref, text, positions: ([], []))
    assert code_bearing("script/t.vns", BASE, say)          # a changed line in no node
    assert not code_bearing("script/t.vns", BASE, [LineEdit(2, 2, ("    # a note",))])

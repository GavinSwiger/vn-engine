"""F45's label graph (``06-acceptance.md`` AC-F45-04; TR-F45-07's label half is in
``test_statement_docs.py``; TR-F45-08).

S's two script files (``06`` §5) are written inline, so this test doesn't share the step 2
and 3 fixture folder.
"""

from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script import load_story
from engine.script.labelgraph import LabelLink, label_links
from engine.script.nodes import If, IfBranch, Jump, Label, ScriptFile
from engine.script.program import LoadStats, Program

S_MAIN = ('include "ch2.vns"\ndefine hana = Character("Hana")\ndefault trust = 0\n'
          'label start:\n    show hana happy\n    hana "Hi."\n    call club\n    jump bridge\n')
S_CH2 = ('label club:\n    menu:\n        "Go to the river":\n            jump river\n'
         '        "Stay":\n            "You stay."\n    return\nlabel bridge:\n'
         '    "The bridge."\nlabel river:\n    "The river."\nlabel side:\n    "Unreached."\n')


def _load(root: Path, files: dict[str, str]) -> Program:
    for name, text in files.items():
        path = root / "script" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    result = load_story(GamePaths(root.resolve()))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def _snapshot(program: Program) -> list:
    return [(name, label.block) for name, label in program.labels.items()] + [
        (type(s), s.sid, s.file.ref, s.line, getattr(s, "target", None))
        for s in program.iter_statements()]


def _plain(links: tuple[LabelLink, ...]) -> list[tuple]:
    return [(k.src, k.dst, k.kind, k.file, k.line, k.choice, k.conditional) for k in links]


def test_ac_f45_04_label_links(tmp_path):
    program = _load(tmp_path / "s", {"main.vns": S_MAIN, "ch2.vns": S_CH2})
    before = _snapshot(program)
    # F46 amendment (06 §2, A-F45-04): choice text and condition flag last.
    expected = [("start", "club", "call", "script/main.vns", 7, None, False),
                ("start", "bridge", "jump", "script/main.vns", 8, None, False),
                ("club", "river", "menu", "script/ch2.vns", 4, "Go to the river", False)]
    links, total = label_links(program, limit=50_000)
    assert (_plain(links), total) == (expected, 3)
    assert label_links(program, limit=50_000) == (links, total)
    links, total = label_links(program, limit=2)
    assert (_plain(links), total) == (expected[:2], 3)
    assert _snapshot(program) == before
    in_if = S_CH2.replace("            jump river\n",
                          "            if trust >= 0:\n                jump river\n")
    links, _ = label_links(_load(tmp_path / "if", {"main.vns": S_MAIN, "ch2.vns": in_if}),
                           limit=50_000)
    assert _plain(links)[2] == ("club", "river", "menu", "script/ch2.vns", 5,
                                "Go to the river", False)


def test_tr_f45_08_deep_nesting_needs_no_recursion():
    file = ScriptFile(ref="script/main.vns", include_path="main.vns", order=0)
    stmt = Jump(file=file, line=1101, end_line=1101, column=1, target="start")
    for depth in range(1_100, 0, -1):
        branch = IfBranch(keyword="if", condition=None, line=depth, column=1, block=(stmt,))
        stmt = If(file=file, line=depth, end_line=1101, column=1, branches=(branch,))
    label = Label(file=file, line=0, end_line=1101, column=1, name="start", block=(stmt,))
    program = Program(files=(file,), labels={"start": label}, defines=(),
                      stats=LoadStats(files=1, labels=1, statements=1101, words=0, seconds=0))
    links, total = label_links(program, limit=10)
    assert (_plain(links), total) == ([("start", "start", "jump", "script/main.vns", 1101,
                                        None, False)], 1)


@pytest.mark.slow
def test_tr_f45_08_a_parsed_100k_statement_story(tmp_path):
    lines = []
    for n in range(1_000):
        lines.append(f"label l{n}:")
        lines += [f'    "Line {k}."' for k in range(98)]
        lines.append(f"    jump l{(n + 1) % 1_000}")
    links, total = label_links(_load(tmp_path, {"main.vns": "label start:\n    jump l0\n"
                                                 + "\n".join(lines) + "\n"}), limit=50_000)
    assert total == len(links) == 1_001

"""F21 step 1 — the whole-game checks for the codex (``checks.py``'s ``_iter_codex``):
AC-F21-04 (E251, E254, ``Program.codex``) and AC-F21-06 (W140, W142). The message rows of
AC-F21-05 (E253) and AC-F21-07 (E255, E62, the clean loads) are in
``tests/fixtures/F02/messages/cases.toml``; AC-F21-07's "Run H ends" rows need the runtime
(F21 step 2, 07 I-5).
"""

import shutil
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script import codex, routes
from engine.script.codex import CodexCategory
from engine.script.loader import LoadOptions, load_story
from engine.script.statements import scoped_registry
from tests.fixtures.F21.gen_counts import counts_story
from tests.script.helpers import template_c

INCLUDES = Path(__file__).resolve().parents[1] / "fixtures" / "F21" / "includes"


@pytest.fixture
def words():
    with scoped_registry():
        routes.register_words()
        codex.register_words()
        yield


def _load(root: Path, files: dict[str, str] | None = None, *, dev: bool = False):
    script = root / "script"
    if files is None:
        shutil.copytree(INCLUDES / "script", script)
    else:
        script.mkdir(parents=True)
        for name, text in files.items():
            (script / name).write_text(text, encoding="utf-8")
    return load_story(GamePaths(root.resolve()), LoadOptions(dev=dev))


def _errors(result) -> list[tuple]:
    return [(e.code, e.file, e.line, e.message) for e in result.errors]


def _warnings(result) -> list[tuple]:
    return [(w.code, w.line, w.message) for w in result.warnings]


def test_ac04_duplicates_counts_and_order(words, tmp_path):
    twice = _load(tmp_path / "twice", {"main.vns": template_c(T='lock item lanterns "Again"')})
    assert _errors(twice) == [("E251", "script/main.vns", 12, 'there are two codex entries named '
                               '"lanterns": here and at script/main.vns, line 2. Give each tip '
                               "and item its own name.")]
    mixed = _load(tmp_path / "mixed",
                  {"main.vns": template_c(T='lock item lamp "L" in "Festival"')})
    assert _errors(mixed) == [("E251", "script/main.vns", 12, 'the category "Festival" holds '
                               "items here and tips at script/main.vns, line 2. Give items "
                               "their own category.")]
    main = (INCLUDES / "script" / "main.vns").read_text(encoding="utf-8")
    a = (INCLUDES / "script" / "a.vns").read_text(encoding="utf-8")
    b = (INCLUDES / "script" / "b.vns").read_text(encoding="utf-8")
    across = _load(tmp_path / "across", {"main.vns": main, "a.vns": a,
                                         "b.vns": b.replace("item coin", "item key")})
    assert _errors(across) == [("E251", "script/b.vns", 2, 'there are two codex entries named '
                                '"key": here and at script/a.vns, line 3. Give each tip and item '
                                "its own name.")]
    for name, text, expected in (
            ("tips", counts_story(tips=1001), "this story has 1,001 tips; the engine allows "
                                              "1,000."),
            ("items", counts_story(items=1001), "this story has 1,001 items; the engine allows "
                                                "1,000."),
            ("cats", counts_story(tips=25, categories=25), "this story has 25 codex categories; "
                                                           "the engine allows 24."),
            ("clean", counts_story(tips=1000, items=1000, categories=23), None)):
        found = _load(tmp_path / name, {"main.vns": text})
        assert _errors(found) == ([] if expected is None else [("E254", None, None, expected)])
    clean = found.program
    assert len(clean.codex) == 2000 and len(clean.codex_categories) == 24
    ok = _load(tmp_path / "includes")
    assert ok.errors == ()
    program = ok.program
    assert [(e.name, e.file, e.line) for e in program.codex] == [
        ("lanterns", "script/a.vns", 1), ("fireworks", "script/a.vns", 2),
        ("key", "script/a.vns", 3), ("moon", "script/b.vns", 1), ("coin", "script/b.vns", 2)]
    assert program.codex_categories == (
        CodexCategory("tip", "Festival", None), CodexCategory("item", None, "codex_items"),
        CodexCategory("tip", None, "codex_tips"), CodexCategory("item", "Things", None))
    assert [e.category for e in program.codex][2:4] == [program.codex_categories[1],
                                                         program.codex_categories[2]]


W142_LANTERNS = ("tip lanterns is declared, but no unlock tip lanterns line names it, so "
                 "players get it only if code unlocks it.")


def _w142(name: str) -> str:
    return W142_LANTERNS.replace("lanterns", name)


def test_ac06_w140_and_w142(words, tmp_path):
    # S takes two lines, so T starts at line 13 (06's "at 12" and "at 13" count S as one).
    S = "unlock tip lanterns⏎[4]unlock tip river_god"
    festival = ('the category "festival" differs from "Festival" (script/main.vns, line 2) only '
                "in capitals or spaces, so they show as two tabs. Use one spelling.")
    tales = ('the category "Old Tales" differs from "Old  Tales" (script/main.vns, line 13) '
             "only in capitals or spaces, so they show as two tabs. Use one spelling.")
    rows = [
        (None, []),
        ('lock tip lamp "L" in "festival"', [("W140", 13, festival), ("W142", 13, _w142("lamp"))]),
        ('lock tip a "A" in "Old  Tales"⏎lock tip b "B" in "Old Tales"',
         [("W142", 13, _w142("a")), ("W140", 14, tales), ("W142", 14, _w142("b"))]),
        ('lock tip a "A" in "Festival"', [("W142", 13, _w142("a"))]),
    ]
    for number, (T, expected) in enumerate(rows):
        found = _load(tmp_path / f"row{number}", {"main.vns": template_c(S=S, T=T)}, dev=True)
        assert found.errors == () and _warnings(found) == expected, T
    unused = _load(tmp_path / "unused", {"main.vns": template_c()}, dev=True)
    assert _warnings(unused) == [("W142", 2, W142_LANTERNS), ("W142", 5, _w142("river_god"))]
    release = _load(tmp_path / "release",
                    {"main.vns": template_c(T='lock tip lamp "L" in "festival"')})
    assert release.errors == () and release.warnings == ()

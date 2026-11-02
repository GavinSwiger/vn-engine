"""F23 s1 — the load checks against the plugins (AC-F23-03, ``checks.py``'s
``_iter_minigames``). The rows of AC-F23-03's table are rows of
``tests/fixtures/F02/messages/cases.toml`` (``feature = "F23"``); this file checks the AC's
last sentence: each problem joins the load's one ``ScriptErrorGroup`` with the other errors,
before any line is shown.
"""

import pytest

from engine.core.paths import GamePaths
from engine.script import ScriptErrorGroup, codex, minigame, routes
from engine.script.loader import LoadOptions, load_story
from engine.script.statements import scoped_registry
from tests.fixtures.F23.sigs import SIGS
from tests.script.helpers import template_g


@pytest.fixture
def words():
    with scoped_registry():
        routes.register_words()
        codex.register_words()
        minigame.register_words()
        yield


@pytest.mark.parametrize("line,code", [
    ("minigame lantern_memroy pairs=6", "E270"), ("minigame probe colour=1", "E271"),
    ("minigame probe pairs=6 into turn", "E270"), ("minigame probe pairs=points.hanna", "E233")])
def test_ac03_load_checks_join_the_one_error_group(words, tmp_path, line, code):
    script = tmp_path / "game" / "script"
    script.mkdir(parents=True)
    (script / "main.vns").write_text(template_g(S=line, T='include "other.vns"'),
                                     encoding="utf-8")
    (script / "other.vns").write_text("label other:\n    jmup start\n", encoding="utf-8")
    result = load_story(GamePaths((tmp_path / "game").resolve()),
                        LoadOptions(dev=False, minigames=SIGS))
    assert result.program is None
    assert [(e.code, e.file, e.line) for e in result.errors] == [
        (code, "script/main.vns", 9), ("E30a", "script/other.vns", 2)]
    group = ScriptErrorGroup.from_result(result)
    assert [e.code for e in group.errors] == [code, "E30a"] and group.total == 2

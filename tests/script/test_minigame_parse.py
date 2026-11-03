"""F23 s1 — the ``minigame`` statement parses (AC-F23-01). AC-F23-02's messages and
AC-F23-17's load rows are rows of ``tests/fixtures/F02/messages/cases.toml``.

The word is registered inside ``scoped_registry()`` until F23 s2 (F19 07 I-5), with F19's and
F21's words for template M's ``lock`` lines.
"""

from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script import codex, minigame, routes
from engine.script.identity import statement_hash
from engine.script.loader import LoadOptions, load_story
from engine.script.minigame import Minigame
from engine.script.statements import scoped_registry
from engine.script.words import STATEMENT_WORDS
from tests.fixtures.F23.sigs import SIGS
from tests.script.helpers import parse_text, template_g


@pytest.fixture
def words():
    with scoped_registry():
        routes.register_words()
        codex.register_words()
        minigame.register_words()
        yield


def _load(root: Path, text: str):
    script = root / "script"
    script.mkdir(parents=True)
    (script / "main.vns").write_text(text, encoding="utf-8")
    return load_story(GamePaths(root.resolve()), LoadOptions(dev=False, minigames=SIGS))


def _node(text: str) -> Minigame:
    parsed = parse_text(text)
    assert parsed.errors == [], [e.format() for e in parsed.errors]
    [node] = [n for n in parsed.nodes if getattr(n, "name", None) == "start"]
    return next(stmt for stmt in node.block if isinstance(stmt, Minigame))


ROWS = [
    ("minigame stargazing stars=5", "stargazing", False, [("stars", "5")], None),
    ("minigame stargazing stars=5 minutes=3 into found", "stargazing", False,
     [("stars", "5"), ("minutes", "3")], "found"),
    ("minigame stargazing skippable stars=night * 2 into found", "stargazing", True,
     [("stars", "night * 2")], "found"),
    ('minigame poem_game words=day_words + ["umbrella"] into poem_for', "poem_game", False,
     [("words", 'day_words + ["umbrella"]')], "poem_for"),
    ("minigame lantern_memory pairs=6 hints=points.hana >= 3 into turns", "lantern_memory",
     False, [("pairs", "6"), ("hints", "points.hana >= 3")], "turns"),
    ("minigame probe mode=into into turns", "probe", False, [("mode", "into")], "turns"),
    ("minigame probe pairs = 6", "probe", False, [("pairs", "6")], None),
    ('minigame probe words=["a",⏎        "b"] into turns', "probe", False,
     [("words", '["a",\n        "b"]')], "turns"),
    ('minigame probe label="x = 1 into y" into turns', "probe", False,
     [("label", '"x = 1 into y"')], "turns"),
    ("minigame probe f=(lambda a=1: a)", "probe", False, [("f", "(lambda a=1: a)")], None),
    ("minigame probe skippable=1", "probe", False, [("skippable", "1")], None),
    ("minigame probe pairs=6  # note", "probe", False, [("pairs", "6")], None),
]


def test_ac01_the_statement_parses(words, tmp_path):
    for row, name, skippable, args, target in ROWS:
        node = _node(template_g(S=row))
        assert (node.name, node.skippable, node.target) == (name, skippable, target), row
        assert [(a.name, a.value.source) for a in node.args] == args, row
        assert all(a.value.code is not None for a in node.args), row
    multi = _node(template_g(S=ROWS[7][0])).args[0]          # the value's first token
    assert (multi.line, multi.column) == (9, 26)
    assert (multi.value.line, multi.value.column) == (9, 26)

    # Identity: ("minigame", name, target or ""); arguments, skippable, fixed left out.
    plain = _node(template_g(S="minigame probe pairs=6 into turns"))
    other = _node(template_g(S="minigame probe skippable pairs=7 into turns"))
    assert plain.identity_key() == ("minigame", "probe", "turns") == other.identity_key()
    assert _node(template_g(S="minigame probe pairs=6")).identity_key() == \
        ("minigame", "probe", "")
    first = _load(tmp_path / "plain", template_g())
    fixed = _load(tmp_path / "fixed", template_g(S="rollback fixed⏎    minigame probe pairs=6 "
                                                   "into turns"))
    assert first.errors == () and fixed.errors == ()
    sid = f"start/{statement_hash(plain.identity_key())}"
    assert isinstance(first.program.get(sid), Minigame) and not first.program.get(sid).fixed
    assert fixed.program.get(sid).fixed

    # into and skippable stay names; no statement word is added (SR-F23-10).
    for number, extra in enumerate(("default into = 0", "default skippable = 0")):
        result = _load(tmp_path / f"name{number}", template_g(T=extra))
        assert result.errors == (), result.errors
    result = _load(tmp_path / "dollar", template_g(S="$ skippable = True"))
    assert result.errors == (), result.errors
    assert "minigame" in STATEMENT_WORDS and len(STATEMENT_WORDS) == 40     # F20, F32 ui, F34 cg

    # Placements: if/elif/else branches, a choice block, a called label.
    for number, s in enumerate((
            "if turns:⏎        minigame probe pairs=6⏎    elif found:⏎        minigame probe "
            "pairs=6⏎    else:⏎        minigame probe pairs=6",
            'menu:⏎        "Play":⏎            minigame probe pairs=6⏎        "Skip":⏎'
            '            "No."',
            "call game_label")):
        text = template_g(S=s, T="label game_label:⏎    minigame probe pairs=6⏎    return")
        result = _load(tmp_path / f"place{number}", text)
        assert result.errors == (), [e.format() for e in result.errors]

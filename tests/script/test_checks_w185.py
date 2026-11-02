"""F29 step 2 — W185, long glitch spans (``06-acceptance.md`` AC-F29-04; ``04-technical.md``
§6.2; 07 G7). Template X (F05 06 §0.4) with each row's S or D, loaded with and without
``--dev``; the records come from ``checks.py`` step 6e (spied), never from the parser."""

import pytest

from engine.script import checks
from engine.script.loader import LoadOptions, load_story
from engine.script.messages import format_message
from tests.runtime.menu_story import write_game
from tests.script.helpers import template_x

QUARTER, HALF = "medium", "large"

ROWS = [
    ("41", dict(S="{glitch}" + "a" * 41 + "{/glitch}"), [(7, 6, 41, QUARTER)]),
    ("40", dict(S="{glitch}" + "a" * 40), []),
    ("small", dict(S="{glitch=small}" + "a" * 100), []),
    ("two spans", dict(S="{glitch}" + "a" * 20 + "{/glitch}x{glitch}" + "a" * 21), []),
    ("spaces", dict(S="{glitch=large}" + "aaaa " * 16), [(7, 6, 64, HALF)]),
    ("small inside", dict(S="{glitch}" + "a" * 20 + "{glitch=small}" + "a" * 30 + "{/glitch}"
                          + "a" * 21), [(7, 6, 41, QUARTER)]),
    ("largest", dict(S="{glitch=small}" + "a" * 20 + "{glitch=large}" + "a" * 41),
     [(7, 6, 41, HALF)]),
    ("var", dict(S="{glitch}{var=player_name}" + "a" * 40), []),
    ("cjk", dict(S="{glitch}" + "紙" * 41), [(7, 6, 41, QUARTER)]),
    ("emoji", dict(S="{glitch}" + "👩‍👩‍👧" * 41), [(7, 6, 41, QUARTER)]),
    ("two lines", dict(D='"{glitch=large}' + "a" * 50 + '"⏎[4]"{glitch=large}' + "a" * 50
                       + '"'), [(7, 6, 50, HALF), (8, 6, 50, HALF)]),
]


@pytest.mark.parametrize("edit,expected", [row[1:] for row in ROWS],
                         ids=[row[0] for row in ROWS])
def test_ac_f29_04_w185_long_glitch_spans(edit, expected, tmp_path, monkeypatch):
    spied: list = []
    real = checks._w185

    def spy(collected):
        found = real(collected)
        spied.extend(found)
        return found

    monkeypatch.setattr(checks, "_w185", spy)
    paths = write_game(tmp_path / "game", template_x(**edit))
    result = load_story(paths, LoadOptions(dev=True))
    assert not result.errors and result.program is not None
    got = [w for w in result.warnings if w.code == "W185"]
    assert got == spied                                        # from step 6e only
    assert [(w.file, w.line, w.column, w.message) for w in got] == [
        ("script/main.vns", line, column, format_message("W185", (count, strength)))
        for line, column, count, strength in expected]
    if expected:
        share = "about half" if expected[0][3] == HALF else "about a quarter"
        assert f"has {expected[0][2]} characters glitching at medium or large, so {share} " \
               "of them" in got[0].message
    # The same load without --dev gives no W185.
    spied.clear()
    release = load_story(paths, LoadOptions(dev=False))
    assert [w for w in release.warnings if w.code == "W185"] == [] and spied == []

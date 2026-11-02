"""W42: a ``{var}`` name that no ``default`` or ``define`` sets (F05 step 2; ``02-script.md``
SR-F05-20, ``04-technical.md`` §6.3, 07 G3/G6).

AC-F05-05's launch column is the W42 rows of ``messages/cases.toml``; its run column (E170,
E171) belongs to F05 step 3. These are the whole-game rules around them: one warning per name
at its first use in reading order, a did-you-mean among defaults and defines, a capped list,
and LC places.
"""

import logging

import pytest

from engine.core.paths import GamePaths
from engine.script.limits import SCRIPT_W42_LIMIT
from engine.script.loader import load_story
from engine.script.report import report_load_result
from tests.script.helpers import expand, template_x


def load(tmp_path, main: str, **files: str):
    script = tmp_path / "game" / "script"
    script.mkdir(parents=True)
    (script / "main.vns").write_text(main, encoding="utf-8")
    for name, text in files.items():
        (script / f"{name}.vns").write_text(expand(text) + "\n", encoding="utf-8")
    return load_story(GamePaths((tmp_path / "game").resolve()))


def w42(result) -> list[tuple[str | None, int | None, int | None, str]]:
    return [(w.file, w.line, w.column, w.message) for w in result.warnings
            if w.code in ("W42", "W42s")]


@pytest.mark.parametrize("edit,expected", [
    # Set by a default, a define, or (F02) a define holding a Character: no warning.
    ({"S": "{var=player_name} has {var=wishes}."}, []),
    ({"S": "{var=hana}"}, []),
    ({"S": "{var=motto}", "T": 'define motto = "x"'}, []),
    # Unset: one warning at the tag's "{".
    ({"S": "Hi, {var=player_nmae}!"},
     [("script/main.vns", 7, 10, "{var=player_nmae} shows a variable that no default or define "
       "sets, so the story stops if this line runs before a $ line sets it. Did you mean "
       '"player_name"?')]),
    # Suggestions come from defines too, and are case-insensitive first (SR-F02-70).
    ({"S": "{var=Hana}"}, [("script/main.vns", 7, 6, None)]),
    # A name used on a line with its own error is not counted.
    ({"S": "{var=nope}{bogus}"}, None),
    # Dialogue lines count too.
    ({"D": 'hana "{i}{var=ghost}{/i}"'}, [("script/main.vns", 7, 14, None)]),
])
def test_w42_rows(tmp_path, edit, expected):
    result = load(tmp_path, template_x(**edit))
    if expected is None:
        assert [e.code for e in result.errors] == ["E160"] and w42(result) == []
        return
    assert result.errors == ()
    found = w42(result)
    assert [item[:3] for item in found] == [item[:3] for item in expected]
    for item, want in zip(found, expected):
        if want[3] is not None:
            assert item[3] == want[3]
    if edit.get("S") == "{var=Hana}":
        assert found[0][3].endswith('Did you mean "hana"?')


def test_w42_once_per_name_at_its_first_use_in_reading_order(tmp_path):
    main = template_x(D='"{var=b_name} {var=a_name}"', T='label later:⏎[4]"{var=a_name}"⏎'
                                                          '[4]"{var=c_name}"⏎include "two.vns"')
    result = load(tmp_path, main, two='label two:⏎[4]"{var=a_name}{var=d_name}"')
    assert [(f, line, col) for f, line, col, _ in w42(result)] == [
        ("script/main.vns", 7, 6), ("script/main.vns", 7, 19), ("script/main.vns", 11, 6),
        ("script/two.vns", 2, 18)]
    names = [m.split("}", 1)[0] for *_, m in w42(result)]
    assert names == ["{var=b_name", "{var=a_name", "{var=c_name", "{var=d_name"]


def test_w42_is_capped_with_one_summary(tmp_path):
    lines = "⏎".join(f'[4]"{{var=unset_{n:02}}}"' for n in range(SCRIPT_W42_LIMIT + 5))
    result = load(tmp_path, template_x(D='"x"⏎' + lines))
    found = w42(result)
    assert len(found) == SCRIPT_W42_LIMIT + 1
    assert all(item[3].startswith(f"{{var=unset_{n:02}}}") for n, item in enumerate(found[:-1]))
    assert found[-1] == (None, None, None,
                         "…and 5 more {var} names that no default or define sets.")


def test_w42_is_logged_with_its_place(tmp_path, caplog):
    result = load(tmp_path, template_x(S="{var=trsut}", T="default trust = 0"))
    caplog.set_level(logging.INFO, logger="test.w42")
    report_load_result(result, logging.getLogger("test.w42"))
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == ["script/main.vns, line 7, column 6: {var=trsut} shows a variable that "
                        "no default or define sets, so the story stops if this line runs "
                        'before a $ line sets it. Did you mean "trust"?']
    assert result.program is not None                      # a warning never stops the load

"""F62 round 1, the script side: ranks on a ``points`` line (E411–E414), change notices
(E415), ``points.rank`` checks (E233, E416, W290), and the positional ``ranks`` word."""

import pytest

from engine.script.points import PointsChange, PointsDecl, split_notice
from tests.runtime.menu_story import load_text
from tests.script.helpers import first_say, parse_text, template

RANKS = 'points hana 0 to 10 ranks "Stranger" 0 "Friend" 4 "Close" 8'


def test_ranks_parse_for_every_name():
    parsed = parse_text(template(T='points hana daichi 0 to 10 start 2 ranks "A" 0 "B" 5'))
    assert parsed.errors == []
    node = parsed.nodes[-1]
    assert type(node) is PointsDecl and node.ranks == (("A", 0), ("B", 5))
    assert [spec.ranks for spec in node.specs()] == [(("A", 0), ("B", 5))] * 2
    assert parse_text(template(T='points a ranks "{{x}}" 1')).nodes[-1].ranks == (("{x}", 1),)


def test_ranks_stays_free_as_a_meter_name():
    # positional: "ranks" starts the ranks only before a quoted label
    for row, names in (("points ranks 0 to 10", ("ranks",)), ("points a ranks", ("a", "ranks"))):
        parsed = parse_text(template(T=row))
        assert parsed.errors == [] and parsed.nodes[-1].names == names, row
    assert parse_text(template(S="$ ranks = 3")).errors == []


@pytest.mark.parametrize("row,code,part", [
    ("points a 0 to 10 ranks", "E411", "at least one label"),
    ("points a 0 to 10 ranks 3", "E411", "label in quotes"),
    ('points a 0 to 10 ranks "A" 0 "B"', "E411", 'the rank "B" needs the number'),
    ('points a 0 to 10 ranks "" 1', "E412", "empty"),
    ('points a 0 to 10 ranks "{b}A" 1', "E412", "plain text"),
    ('points a 0 to 10 ranks "' + "x" * 41 + '" 1', "E412", "keep it to 40"),
    ('points a 0 to 10 ranks "A" 0 "A" 3', "E412", "own label"),
    ('points a 0 to 10 ranks "A" 11', "E413", "outside the range 0 to 10"),
    ('points a 0 to 10 ranks "A" 5 "B" 5', "E413", "lowest to highest"),
    ('points a 0 to 10 ranks "A" 1.5', "E232", "whole numbers"),
    ("points rank", "E414", "points.rank"),
])
def test_rank_mistakes(row, code, part):
    parsed = parse_text(template(T=row))
    assert parsed.codes == [code] and part in parsed.messages[0], parsed.messages


def test_notices_parse_with_every_operator():
    for op in ("+=", "-=", "="):
        row = f'points a {op} bonus * 2 "Hana will remember that."  # note'
        node = first_say(parse_text(template(S=row)))
        assert type(node) is PointsChange and node.notice == "Hana will remember that."
        assert node.identity_key() == ("points", "a", op, "bonus * 2")
    assert first_say(parse_text(template(S="points a += 1"))).notice is None
    assert first_say(parse_text(template(S='points a += 1 "{{wink}}"'))).notice == "{wink}"


def test_split_notice_keeps_python_strings():
    assert split_notice('1 "x"') == ("1", "x")
    assert split_notice('f("a") "Nice."') == ('f("a")', "Nice.")
    assert split_notice('"a" "b"') is None              # one Python string, not a notice
    assert split_notice('x if y else "z"') is None
    assert split_notice("1 f\"x\"") is None


@pytest.mark.parametrize("row,part", [('points a += 1 ""', "empty"),
                                      ('points a += 1 "{b}x"', "plain text"),
                                      ('points a += 1 "' + "x" * 201 + '"', "keep it to 200")])
def test_notice_mistakes(row, part):
    parsed = parse_text(template(S=row))
    assert parsed.codes == ["E415"] and part in parsed.messages[0]


def _load(tmp_path, condition):
    text = (f'{RANKS}\npoints bare\nlabel start:\n    if {condition}:\n        "Hi."\n'
            '    "End."\n')
    return load_text(tmp_path, text)


@pytest.mark.parametrize("condition,code,part", [
    ('points.rank("hna") == "Close"', "E233", 'Did you mean "hana"?'),
    ('points.rank("bare") == "x"', "E416", "bare has none"),
])
def test_rank_use_errors(tmp_path, condition, code, part):
    result = _load(tmp_path, condition)
    assert [e.code for e in result.errors] == [code] and part in result.errors[0].message


def test_rank_comparison_warning(tmp_path):
    assert not _load(tmp_path / "ok", 'points.rank("hana") == "Close"').warnings
    result = _load(tmp_path / "typo", '"Closee" != points.rank("hana")')
    (warning,) = [w for w in result.warnings if w.code == "W290"]
    assert warning.line == 4 and 'Did you mean "Close"?' in warning.format()

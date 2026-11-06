"""F62 round 2, the script side: ``show meter`` / ``hide meter`` (positional ``meter``), E417,
E418, and the whole-game checks E233 and W291–W293 (specs/F62-visible-meters/SPEC.md)."""

from types import SimpleNamespace

import pytest

from engine.core.config_schema import MeterTable
from engine.script.loader import LoadOptions, load_story
from engine.script.showmeter import MeterShow
from engine.script.stage import Hide, Show
from tests.runtime.menu_story import load_text, write_game
from tests.script.helpers import first_say, parse_text, template


def _stmt(row):
    parsed = parse_text(template(S=row))
    return parsed, first_say(parsed)


@pytest.mark.parametrize("row,shown,names", [
    ("show meter hana", True, ("hana",)),
    ("show meter hana sanity", True, ("hana", "sanity")),
    ("hide meter hana", False, ("hana",)),
    ("hide meter hana sanity  # both", False, ("hana", "sanity")),
])
def test_the_meter_form(row, shown, names):
    parsed, node = _stmt(row)
    assert parsed.errors == [] and type(node) is MeterShow
    assert (node.shown, node.names) == (shown, names)
    assert node.identity_key() == ("meter", "show" if shown else "hide", *names)


@pytest.mark.parametrize("row,kind", [
    ("show meter", Show),                       # the picture tagged meter
    ("show meter happy at left", Show),         # a sprite modifier: the picture
    ("show meter 2", Show),
    ("hide meter", Hide),                       # the sprite tagged meter
])
def test_meter_stays_a_picture_and_a_name(row, kind):
    parsed, node = _stmt(row)
    assert parsed.errors == [] and type(node) is kind
    # and a variable, character or meter may be called meter
    assert parse_text(template(S="$ meter = 3")).errors == []
    assert parse_text(template(T="points meter 0 to 5")).errors == []


@pytest.mark.parametrize("row,code,part", [
    ('show meter "hana"', "E417", 'found "hana"'),
    ("show meter hana, sanity", "E417", "separated by spaces"),
    ("hide meter hana with dissolve", "E417", "only meter names"),
    ("show meter hana:", "E417", "no colon"),
    ("show meter hana hana", "E418", "names hana twice"),
    ("hide meter " + " ".join(f"m{i}" for i in range(9)), "E418", "at most 8"),
])
def test_mistakes(row, code, part):
    parsed, _ = _stmt(row)
    assert parsed.codes == [code] and part in parsed.messages[0], parsed.messages


TOP = "points hana 0 to 10\npoints coins\nlabel start:\n"


def _load(tmp_path, body, config=None):
    text = TOP + "".join(f"    {line}\n" for line in body)
    return load_story(write_game(tmp_path, text), LoadOptions(meter_config=config))


def test_unknown_meter_is_e233(tmp_path):
    result = _load(tmp_path, ["show meter hanna", '"Hi."'])
    assert [e.code for e in result.errors] == ["E233"]
    assert 'Did you mean "hana"?' in result.errors[0].message and result.errors[0].line == 4
    assert load_text(tmp_path / "ok", TOP + '    show meter hana\n    hide meter hana\n'
                     '    "Hi."\n').errors == ()


def _config(kit=None, **tables):
    return SimpleNamespace(theme=SimpleNamespace(kit=kit),
                           meter={k: MeterTable(**v, line=7) for k, v in tables.items()})


def test_w291_a_config_table_for_no_meter(tmp_path):
    result = _load(tmp_path, ['"Hi."'], _config(hanna={"look": "hearts"}, hana={}))
    (warning,) = [w for w in result.warnings if w.code == "W291"]
    assert warning.file == "config.toml" and warning.line == 7
    assert 'Did you mean "hana"?' in warning.message
    assert not [w for w in _load(tmp_path / "none", ['"Hi."']).warnings if w.code == "W291"]


def test_w292_a_ranged_look_on_a_meter_with_no_range(tmp_path):
    body = ["show meter coins hana", "show meter coins", '"Hi."']
    result = _load(tmp_path, body, _config(coins={"look": "pips"}))
    (warning,) = [w for w in result.warnings if w.code == "W292"]    # once per meter
    assert "coins is shown as pips" in warning.message and warning.line == 4
    as_number = _load(tmp_path / "n", body, _config(coins={"look": "number"}))
    assert not [w for w in as_number.warnings if w.code == "W292"]
    # the kit's look counts: mystery shows numbers
    assert not [w for w in _load(tmp_path / "k", body, _config("mystery")).warnings
                if w.code == "W292"]
    # without a config (tools): not checked
    assert not [w for w in _load(tmp_path / "c", body).warnings if w.code == "W292"]


def test_w293_a_meter_shown_as_a_picture(tmp_path):
    result = _load(tmp_path, ["show meter hana with dissolve", '"Hi."'])
    (warning,) = [w for w in result.warnings if w.code == "W293"]
    assert "write show meter hana" in warning.message

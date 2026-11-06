"""F64 round 2 at load: ``use <scene>`` on item declarations, ``show hotbar`` / ``hide hotbar``
(positional), W308 (``[hotbar] items``) and W309 (a picture called hotbar)."""

from types import SimpleNamespace

import pytest

from engine.core.config_schema import HotbarConfig
from engine.core.paths import GamePaths
from engine.script.hotbar import HotbarShow, picture_warnings
from engine.script.loader import LoadOptions, load_story
from engine.script.stage import Hide, Show
from tests.runtime.effects_story import write_game

SCENE = 'label drink_tea:\n    "Warm."\n    return\n'


def _load(tmp_path, top, body='    "x"\n', after=SCENE, config=None):
    root = write_game(tmp_path, f'{top}label start:\n{body}{after}')
    return load_story(GamePaths(root.resolve()), LoadOptions(meter_config=config))


@pytest.mark.parametrize("line, use", [
    ('lock item tea "Jasmine Tea" use drink_tea', "drink_tea"),
    ('lock item tea "Jasmine Tea" in "Things" use drink_tea count 3 price 2', "drink_tea"),
    ('lock item tea "Jasmine Tea" image tea cup use drink_tea', "drink_tea"),
    ('lock item tea "Jasmine Tea"', None),
])
def test_use_declared(tmp_path, line, use):
    result = _load(tmp_path, line + "\n")
    assert not result.errors, result.errors
    entry = next(e for e in result.program.codex if e.name == "tea")
    assert entry.use == use


@pytest.mark.parametrize("line, code, said", [
    ('lock tip tea "Tea" use drink_tea', "E437", "can't be used"),
    ('lock item tea "Tea" use', "E41", "use needs the name of a label"),
    ('lock item tea "Tea" use "drink_tea"', "E41b", "Write use drink_tea"),
    ('lock item tea "Tea" use drink_te', "E43", 'Did you mean "drink_tea"'),
])
def test_use_refused(tmp_path, line, code, said):
    result = _load(tmp_path, line + "\n")
    assert [e.code for e in result.errors][:1] == [code]
    assert said in result.errors[0].message


def _first(result, label="start"):
    return result.program.labels[label].block[0]


@pytest.mark.parametrize("line, kind, shown", [
    ("show hotbar", HotbarShow, True), ("hide hotbar", HotbarShow, False),
    ("show hotbar at left", Show, None), ("hide hotbar with dissolve", Hide, None),
])
def test_show_hide_hotbar_is_positional(tmp_path, line, kind, shown):
    result = _load(tmp_path, "", body=f"    {line}\n    \"x\"\n", after="")
    assert not result.errors, result.errors
    stmt = _first(result)
    assert type(stmt) is kind
    if shown is not None:
        assert stmt.shown is shown


def test_hotbar_stays_a_name(tmp_path):
    result = _load(tmp_path, 'define hotbar = Character("Hotbar")\ndefault use = 1\n',
                   body='    hotbar "Hi."\n    $ use += 1\n', after="")
    assert not result.errors, result.errors


def _config(*items):
    return SimpleNamespace(hotbar=HotbarConfig(items=tuple(items)), meter={})


def test_w308_hotbar_items(tmp_path):
    top = ('lock item tea "Tea" use drink_tea\nlock item key "Key"\n'
           'lock tip lore "Lore"\n')
    result = _load(tmp_path, top, body='    unlock tip lore\n    "x"\n',
                   config=_config("tea", "key", "lore", "te"))
    found = [w.message for w in result.warnings if w.code == "W308"]
    assert len(found) == 3
    assert "item key, which has no Use scene" in found[0]
    assert "tip lore" in found[1]
    assert 'Did you mean "tea"' in found[2]
    clean = _load(tmp_path, top, body='    unlock tip lore\n    "x"\n', config=_config("tea"))
    assert not [w for w in clean.warnings if w.code == "W308"]


def test_w309_picture_called_hotbar(tmp_path):
    result = _load(tmp_path, "", body="    show hotbar\n    \"x\"\n", after="")
    statements = list(result.program.iter_statements())
    assert picture_warnings(statements, ("bg",)) == []
    found = picture_warnings(statements, ("hotbar", "bg"))
    assert [w.code for w in found] == ["W309"] and "show hotbar at center" in found[0].message

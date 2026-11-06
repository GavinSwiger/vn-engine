"""v1 name freeze: each old spelling still works, read as its new name, with one W323 per
old spelling naming the new one; Studio writes only the new names (``script/renamed.py``,
``core/config.RENAMED``, ``tools/editor/tomlpatch``)."""

import tomllib

from engine.core.config import KeyLocator, _validate
from engine.runtime.inbox import deliveries_from_json
from engine.script.loader import LoadOptions, load_story
from engine.tools.editor import settingsmodel, tomlpatch
from engine.tools.editor.scriptedit import apply_lines
from tests.runtime.menu_story import write_game


def _config(text):
    config, warnings, errors = _validate(tomllib.loads(text), KeyLocator(text))
    assert not errors
    return config, warnings


def _w323(warnings):
    return [(w.file, w.line, w.message) for w in warnings if w.code == "W323"]


def _load(tmp_path, top, body, config=None):
    text = top + "label start:\n" + "".join(f"    {line}\n" for line in body) + '    "End."\n'
    return load_story(write_game(tmp_path, text), LoadOptions(meter_config=config))


def test_the_letters_look_is_read_as_letter_with_one_warning_per_spelling(tmp_path):
    top = 'lock contact hana "Hana" on letters\ndefine invite = "Hi."\n'
    result = _load(tmp_path, top, ["send invite from hana on letters", "open letters",
                                   "send invite from hana on letters"])
    assert not result.errors
    contact = result.program.contacts[0]
    assert contact.device == "letter"
    assert [w[1:] for w in _w323(result.warnings)] == [
        (1, "on letters is a spelling from before version 1. It still works for now, but "
            "write on letter instead."),
        (5, "open letters is a spelling from before version 1. It still works for now, but "
            "write open letter instead.")]


def test_a_send_line_keeps_its_sid_whichever_spelling_it_uses(tmp_path):
    def sid(look):
        top = f'lock contact hana "Hana"\ndefine invite = "Hi."\n'
        program = _load(tmp_path / look, top, [f"send invite from hana on {look}"]).program
        return next(s.sid for s in program.labels["start"].block if hasattr(s, "contact"))
    assert sid("letters") == sid("letter")


def test_a_saved_delivery_by_letters_reads_as_letter():
    saved = [{"key": "0123456789abcdef.1", "sid": "start/0123456789ab", "contact": "Hana",
              "time": "", "device": "letters", "lines": [["them", "Hana", "Hi."]]}]
    (delivery,) = deliveries_from_json(saved)
    assert delivery.device == "letter"


def test_device_letters_is_read_as_device_letter_and_the_new_table_wins():
    config, warnings = _config('[device.letters]\nname = "Post"\narrive_text = "Mail"\n'
                               '[device.letter]\narrive_text = "A letter"\n')
    assert config.device["letter"].name == "Post"
    assert config.device["letter"].arrive_text == "A letter"
    assert config.renamed == ((1, "[device.letters]", "[device.letter]"),)
    assert warnings == []


def test_the_check_warns_once_for_each_old_config_key(tmp_path):
    config, _ = _config('[device.letters]\nname = "Post"\n')
    result = _load(tmp_path, "", ['"Hi."'], config)
    assert _w323(result.warnings) == [
        ("config.toml", 1, "[device.letters] is a spelling from before version 1. It still "
                           "works for now, but write [device.letter] instead.")]


def test_studio_reads_the_old_table_at_its_new_name_and_moves_it_when_writing():
    text = '[device.letters]\nname = "Post"\narrive_text = "Mail"\n\n[device.phone]\nname = "Cell"'
    found = settingsmodel.values(text)
    assert found["device.letter.name"] == "Post"
    assert "device.letters.name" not in found
    plan = tomlpatch.plan_set(text, "device.letter", "name", "Postbox")
    assert (plan.section, plan.key, plan.value) == ("device.letter", "name", "Postbox")
    new = tomllib.loads("\n".join(apply_lines(text.split("\n"), plan.edits)))
    assert new == {"device": {"phone": {"name": "Cell"},
                              "letter": {"name": "Postbox", "arrive_text": "Mail"}}}


def test_theme_kit_is_read_as_game_kit_and_studio_moves_it():
    config, warnings = _config('[game]\ntitle = "x"\n\n[theme]\nkit = "horror"\n')
    assert config.game.kit == "horror" and warnings == []
    assert config.renamed == ((5, "[theme] kit", "[game] kit"),)
    text = '[game]\ntitle = "x"\n\n[theme]\nkit = "horror"\npreset = "noir"'
    assert settingsmodel.values(text)["game.kit"] == "horror"
    plan = tomlpatch.plan_set(text, "game", "kit", "mystery")
    new = "\n".join(apply_lines(text.split("\n"), plan.edits))
    assert tomllib.loads(new) == {"game": {"title": "x", "kit": "mystery"},
                                  "theme": {"preset": "noir"}}

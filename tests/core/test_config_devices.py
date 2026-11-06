"""F65 round 3: ``[device.<look>]`` in config.toml, and how its words win over the engine's
(``kits.device_words``) and name the Inbox (``kits.kit_words``)."""

from types import SimpleNamespace

import pytest

from engine.core.config import load_config
from engine.core.config_schema import DeviceTable
from engine.core.kits import DEVICE_LOOKS, arrive_text, device_look, device_words, kit_words
from engine.core.paths import GamePaths


@pytest.fixture
def load(tmp_path):
    count = iter(range(1000))

    def load_text(text: str):
        root = tmp_path / f"game{next(count)}"
        root.mkdir()
        (root / "config.toml").write_text(text, encoding="utf-8")
        return load_config(GamePaths.for_game(root))
    return load_text


def test_a_device_table_sets_name_notice_sound_line_and_reading(load):
    found = load('[device.pigeon]\nname = "Pigeon Post"\n'
                 'arrive_text = "A grey bird lands on the sill."\n'
                 'arrive_sound = "sfx/wings.ogg"\nheader_text = "By wing"\n'
                 'reading = "chat"\n')
    assert found.errors == [] and found.warnings == []
    table = found.config.device["pigeon"]
    assert (table.name, table.arrive_text, table.arrive_sound, table.header_text,
            table.reading, table.line) == ("Pigeon Post", "A grey bird lands on the sill.",
                                           "sfx/wings.ogg", "By wing", "chat", 1)
    assert load("").config.device == {}


def test_an_unknown_device_warns_with_a_did_you_mean_and_is_skipped(load):
    found = load('[device.pidgeon]\nname = "x"\n\n[device.fax]\nname = "y"\n')
    assert found.config.device == {}
    assert found.warnings == [
        "config.toml, line 1: unknown device [device.pidgeon] — did you mean "
        "[device.pigeon]?",
        "config.toml, line 4: unknown device [device.fax]. Use one of phone, letter, "
        "pigeon, radio, terminal, mind."]


def test_a_bad_value_is_an_error_and_its_key_stays_unset(load):
    found = load('[device.radio]\nreading = "song"\nname = "Ham radio"\n')
    assert [e.message for e in found.errors] == [
        '[device.radio] reading must be one of "letter", "chat", but found the text "song"']
    assert found.config.device["radio"].reading is None
    assert found.config.device["radio"].name == "Ham radio"
    assert load("[devices]\n").warnings[0].endswith("did you mean [device]?")


def config(kit=None, **tables):
    return SimpleNamespace(theme=SimpleNamespace(kit=kit), device=tables)


def test_config_words_win_over_the_engine_words_key_by_key():
    plain = device_words("pigeon")
    assert (plain.name, plain.sound, plain.letter) == ("Pigeon post", None, True)
    mine = device_words("pigeon", config(pigeon=DeviceTable(
        arrive_text="A grey bird lands on the sill.", arrive_sound="sfx/wings.ogg",
        reading="chat")))
    assert (mine.arrive, mine.via, mine.letter, mine.name, mine.sound) == (
        "A grey bird lands on the sill.", "Arrived by pigeon", False, "Pigeon post",
        "sfx/wings.ogg")
    assert device_words("phone", config(pigeon=DeviceTable(name="x"))) == device_words("phone")
    assert [device_words(look).name for look in DEVICE_LOOKS] == [
        "Phone", "Letters", "Pigeon post", "Radio", "Terminal", "Mind"]


def test_arrive_text_fills_only_the_name():
    words = device_words("phone", config(phone=DeviceTable(arrive_text="{name} {x} buzzes")))
    assert arrive_text(words, "Ren") == "Ren {x} buzzes"


def test_the_game_device_name_names_the_inbox_over_the_kit_title():
    assert kit_words(config("fantasy")) == {"inbox": "Pigeon post"}
    named = config("fantasy", pigeon=DeviceTable(name="Rookery"))
    assert device_look(named) == "pigeon"
    assert kit_words(named) == {"inbox": "Rookery"}
    assert kit_words(config(None, phone=DeviceTable(name="Pocket"))) == {"inbox": "Pocket"}
    assert kit_words(config(None, pigeon=DeviceTable(name="Rookery"))) == {}

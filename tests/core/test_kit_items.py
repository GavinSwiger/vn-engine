"""F64 round 1: each kit's ``items`` section (the bag's name, the money word) and
``bag_words``' precedence (v1: one rule for every renameable word): a ``[words]`` value
written in config.toml (even the default) > the kit > none."""

from types import MappingProxyType, SimpleNamespace

import pytest

from engine.core.config import load_config
from engine.core.config_schema import WordsConfig
from engine.core.constants import WORD_MAX_CHARS
from engine.core.kits import ITEMS_BAG, ITEMS_HOTBAR, ITEMS_MONEY, KITS, bag_words, hotbar_word
from engine.core.paths import GamePaths


@pytest.mark.parametrize("found", list(KITS.values()), ids=list(KITS))
def test_every_kit_names_its_bag(found):
    items = found.items
    assert isinstance(items, MappingProxyType) and set(items) == {ITEMS_BAG, ITEMS_MONEY,
                                                                   ITEMS_HOTBAR}
    assert items[ITEMS_HOTBAR].strip() and len(items[ITEMS_HOTBAR]) <= WORD_MAX_CHARS
    assert items[ITEMS_BAG].strip() and len(items[ITEMS_BAG]) <= WORD_MAX_CHARS
    assert len(items[ITEMS_MONEY]) <= WORD_MAX_CHARS


def _config(kit=None, **words):
    return SimpleNamespace(game=SimpleNamespace(kit=kit), words=WordsConfig(**words))


def test_bag_words_precedence():
    assert bag_words(_config()) == ("", "")
    assert bag_words(_config("fantasy")) == ("Satchel", "Gold")
    assert bag_words(_config("mystery")) == ("Evidence", "")
    assert bag_words(_config("scifi", money="Bits")) == ("Cargo", "Bits")
    assert bag_words(_config("cozy", codex_items=" Pack ", money="  ")) == ("Pack", "Coins")
    assert bag_words(_config("nope")) == ("", "")


def test_hotbar_word_precedence():
    assert hotbar_word(_config()) == ""
    assert hotbar_word(_config("fantasy")) == "Belt"
    assert hotbar_word(_config("horror", hotbar=" Sack ")) == "Sack"


def test_a_written_word_equal_to_the_default_still_wins(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[game]\nkit = "fantasy"\n\n[words]\ncodex_items = "Items"\nhotbar = "Hotbar"\n',
        encoding="utf-8")
    config = load_config(GamePaths.for_game(tmp_path)).config
    assert config.words.set_keys == {"codex_items", "hotbar"}
    assert bag_words(config) == ("Items", "Gold")
    assert hotbar_word(config) == "Hotbar"

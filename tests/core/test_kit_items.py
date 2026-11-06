"""F64 round 1: each kit's ``items`` section (the bag's name, the money word) and
``bag_words``' precedence: ``[codex] bag_word`` / ``money_word`` > the kit > none."""

from types import MappingProxyType, SimpleNamespace

import pytest

from engine.core.config_schema import BAG_WORD_MAX, CodexConfig
from engine.core.kits import ITEMS_BAG, ITEMS_MONEY, KITS, bag_words


@pytest.mark.parametrize("found", list(KITS.values()), ids=list(KITS))
def test_every_kit_names_its_bag(found):
    items = found.items
    assert isinstance(items, MappingProxyType) and set(items) == {ITEMS_BAG, ITEMS_MONEY}
    assert items[ITEMS_BAG].strip() and len(items[ITEMS_BAG]) <= BAG_WORD_MAX
    assert len(items[ITEMS_MONEY]) <= BAG_WORD_MAX


def _config(kit=None, **codex):
    return SimpleNamespace(theme=SimpleNamespace(kit=kit), codex=CodexConfig(**codex))


def test_bag_words_precedence():
    assert bag_words(_config()) == ("", "")
    assert bag_words(_config("fantasy")) == ("Satchel", "Gold")
    assert bag_words(_config("mystery")) == ("Evidence", "")
    assert bag_words(_config("scifi", money_word="Bits")) == ("Cargo", "Bits")
    assert bag_words(_config("cozy", bag_word=" Pack ", money_word="  ")) == ("Pack", "Coins")
    assert bag_words(_config("nope")) == ("", "")

"""F60 genre kits: the registry, ``[game] kit`` in config, ``kit_of`` and ``meter_look``
(specs/F60-genre-kits/SPEC.md)."""

import dataclasses
import re
from types import MappingProxyType, SimpleNamespace

import pytest

from engine.core import kits
from engine.core.config_schema import KitName, ThemeConfig
from engine.core.constants import STATEMENT_WORDS
from engine.core.kits import KITS, kit, kit_of, meter_label, meter_look
from engine.core.schemes import SCHEMES
from engine.core.skins import CORNER_PLACES, DEFAULT_CORNER_PLACE, DEFAULT_METER_LOOK, METER_LOOKS
from engine.core.storyclock import NAME_MAX, PARTS_MAX, calendar_of

KIT_LIST = ", ".join(f'"{key}"' for key in KITS)


def test_the_seven_kits_in_order():
    assert list(KITS) == ["romance", "horror", "mystery", "fantasy", "cozy", "scifi", "letters"]
    assert isinstance(KITS, MappingProxyType)
    assert kit("horror") is KITS["horror"] and kit("Horror") is None and kit("none") is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        KITS["cozy"].name = "x"                                        # type: ignore[misc]


@pytest.mark.parametrize("found", list(KITS.values()), ids=list(KITS))
def test_each_kit_is_well_formed(found):
    assert re.fullmatch(r"[a-z]+", found.id)
    assert found.name and len(found.name) <= 16
    # One line an author reads: a sentence, short enough for a card's detail.
    assert found.blurb.endswith(".") and len(found.blurb) <= 80 and "\n" not in found.blurb
    assert found.scheme in SCHEMES
    assert found.meters.look in METER_LOOKS and found.meters.place in CORNER_PLACES
    assert 2 <= len(found.meters.suggestions) <= 4
    names = [s.name for s in found.meters.suggestions]
    assert len(set(names)) == len(names)
    for s in found.meters.suggestions:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", s.name) and s.name not in STATEMENT_WORDS
        assert s.label and s.low < s.high and s.low <= s.start <= s.high
        ats = [at for _, at in s.ranks]
        assert ats == sorted(set(ats)), s.name                   # rising, as F62 checks
        assert all(label.strip() and s.low <= at <= s.high for label, at in s.ranks)
    # Reserved for later phases, empty and read-only for now.
    assert found.checks == {} and isinstance(found.checks, MappingProxyType)
    # F65: the Inbox page's name and the default device look.
    assert isinstance(found.messages, MappingProxyType)
    assert set(found.messages) == {kits.MESSAGES_TITLE, kits.MESSAGES_DEVICE}
    title = found.messages[kits.MESSAGES_TITLE]
    assert title == title.strip() and 0 < len(title) <= 16
    assert found.messages[kits.MESSAGES_DEVICE] in kits.DEVICE_LOOKS
    # F63: the clock's parts of the day and day wording, within [calendar]'s own limits.
    clock = found.clock
    assert clock is not None and 1 <= len(clock.parts) <= PARTS_MAX
    assert len(set(clock.parts)) == len(clock.parts)
    assert all(0 < len(part) <= NAME_MAX for part in clock.parts)
    calendar, problems = calendar_of(SimpleNamespace(game=SimpleNamespace(kit=found.id)))
    assert problems == [] and calendar.parts == clock.parts
    assert calendar.wording() == clock.day_text          # every field it uses is there


def test_the_genre_meters_from_the_proposal():
    def labels(id_):
        return [s.label for s in KITS[id_].meters.suggestions]
    assert labels("horror")[0] == "Sanity" and labels("romance")[0] == "Affection"
    assert {"Suspicion", "Credibility"} <= set(labels("mystery"))
    assert {"Renown", "Stamina"} <= set(labels("fantasy"))
    assert {"Mood", "Coins"} <= set(labels("cozy"))
    assert {"Hull", "Oxygen"} <= set(labels("scifi"))
    assert labels("letters")[0] == "Trust"
    sanity = KITS["horror"].meters.suggestions[0]
    assert (sanity.low, sanity.high, sanity.start) == (0, 100, 100) and sanity.ranks
    affection = KITS["romance"].meters.suggestions[0]
    assert [label for label, _ in affection.ranks] == ["Stranger", "Friend", "Close"]


def test_kit_name_lists_the_kits_by_name():
    names = KitName()
    assert names.options == tuple(KITS)
    assert names.labels["scifi"] == "Sci-fi"


def test_game_kit_in_config(load):
    result = load('[game]\nkit = "horror"\n')
    assert result.errors == [] and result.warnings == []
    assert result.config.game.kit == "horror"
    assert kit_of(result.config) is KITS["horror"]
    # A kit never sets the colors on its own: Studio offers its scheme separately.
    assert result.config.theme == ThemeConfig()
    assert kit_of(load("").config) is None


def test_unknown_and_wrong_kits_written_the_old_way(load):
    """``[theme] kit`` (before version 1) is read as ``[game] kit``, at its own line."""
    near = load('[theme]\n\nkit = "horor"\n')
    assert near.errors == [] and near.warnings == [
        'config.toml, line 3: unknown genre kit "horor" in [game] kit — did you mean '
        '"horror"?']
    assert near.config.game.kit is None and kit_of(near.config) is None
    assert load('[theme]\nkit = "Sci-fi"\n').warnings[0].endswith('did you mean "scifi"?')
    far = load('[theme]\nkit = "western"\n')
    assert far.errors == [] and far.warnings == [
        f'config.toml, line 2: unknown genre kit "western" in [game] kit. Use one of '
        f'{KIT_LIST}.']
    wrong = load("[theme]\nkit = 3\n")
    assert [e.format() for e in wrong.errors] == [
        f"config.toml, line 2: [game] kit must be one of {KIT_LIST}, but found 3"]
    assert wrong.warnings == []
    assert "\\x1b" in load('[theme]\nkit = "x\\u001b"\n').warnings[0]
    # With a preset beside it, both are read.
    both = load('[theme]\npreset = "noir"\nkit = "mystery"\n')
    assert both.warnings == [] and both.config.theme.preset == "noir"
    assert both.config.game.kit == "mystery"
    assert load('[game]\nkit = "western"\n').warnings == [
        f'config.toml, line 2: unknown genre kit "western" in [game] kit. Use one of '
        f'{KIT_LIST}.']


def _config(kit_id=None, meter=None):
    return SimpleNamespace(game=SimpleNamespace(kit=kit_id),
                           **({"meter": meter} if meter is not None else {}))


def test_meter_look_precedence():
    # No kit: the skins defaults, the label from the variable name.
    assert meter_look(_config(), "hana_love") == (DEFAULT_METER_LOOK, DEFAULT_CORNER_PLACE,
                                                  "Hana love")
    # A kit: its look and place; a suggestion's label for its own name.
    assert meter_look(_config("romance"), "affection") == ("hearts", "top_right", "Affection")
    assert meter_look(_config("romance"), "hana_love") == ("hearts", "top_right", "Hana love")
    assert meter_look(_config("western"), "x") == (DEFAULT_METER_LOOK, DEFAULT_CORNER_PLACE, "X")
    # [meter.<name>] (F62 round 2) wins over the kit, key by key.
    own = {"affection": SimpleNamespace(look="dial", place=None, label="Hana's heart")}
    assert meter_look(_config("romance", own), "affection") == ("dial", "top_right",
                                                                "Hana's heart")
    assert meter_look(_config("romance", own), "courage") == ("hearts", "top_right", "Courage")


def test_meter_look_on_a_real_config(load):
    config = load('[theme]\nkit = "scifi"\n').config
    assert meter_look(config, "oxygen") == ("dial", "top_left", "Oxygen")


def test_meter_label():
    assert meter_label("sanity") == "Sanity" and meter_label("hana_love") == "Hana love"
    assert meter_label("__x__") == "X"


def test_the_module_imports_only_core():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(kits.__file__).read_text(encoding="utf-8"))
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert all(m == "__future__" or not m.startswith("engine.") or m.startswith("engine.core")
               for m in modules)


def test_f65_messages_words_and_device_looks():
    """F65: each kit names the Inbox page and picks a device look; every look is some kit's;
    ``kit_words`` gives the page's word, and the device look falls back to the phone."""
    looks = {k.messages[kits.MESSAGES_DEVICE] for k in KITS.values()}
    assert looks == set(kits.DEVICE_LOOKS)
    letters = SimpleNamespace(game=SimpleNamespace(kit="letters"))
    assert kits.kit_words(letters) == {"inbox": "Letters"}
    assert kits.device_look(letters) == "letter"
    plain = SimpleNamespace(game=SimpleNamespace(kit=None))
    assert kits.kit_words(plain) == {} and kits.device_look(plain) == "phone"

"""``Character`` (F03 ``04-technical.md`` §7.10; SR-F03-11 to 17).

ACs: AC-F03-32 (the parts beyond its message table: the color as written, the option list
with F04's ``image_tag``), AC-F03-33 (a speaker only in an unreachable label), AC-F03-36 (the
character is unchanged after a refused change). The message rows of AC-F03-32, 33, 35, and
36 are in ``cases.toml`` (``test_messages_f03.py``).
"""

import pytest

from engine.runtime.character import (CHARACTER_OPTIONS, Character, CharacterFactory,
                                      CharacterLocked, CharacterOptionError)
from engine.runtime.commands import Say, StoryFailed
from engine.runtime.headless import run_headless
from engine.runtime.launch import run_launch
from tests.runtime.story import advance, load_files, load_r, start
from tests.script.helpers import template_r


def load_r_with(root, replace: dict[int, str], *, S: str | None = None,
                T: str | None = None):
    return load_files(root, {"main.vns": template_r(S=S, T=T, replace=replace)})


# --- AC-F03-32 ---------------------------------------------------------------------------------

def test_ac_f03_32_the_color_is_kept_as_written(tmp_path):
    program = load_r_with(tmp_path, {2: 'define daichi = Character("Daichi", color="#8FB3D9")'},
                          S='daichi "Yo."')
    commands = run_headless(program, seed=42)
    assert [(c.name, c.name_color) for c in commands if type(c) is Say][1] == ("Daichi",
                                                                               "#8FB3D9")


@pytest.mark.parametrize("R2, message", [
    ('define daichi = Character("Daichi", colour="#8fb3d9")',
     'Character has no option "colour". Did you mean "color"? Its options are blip, '
     "blip_every, blip_pitch, blip_volume, color, image_tag, name_from, text_color, and "
     "text_italic."),
    ('define daichi = Character("Daichi", sprite="d")',
     'Character has no option "sprite". Its options are blip, blip_every, blip_pitch, '
     "blip_volume, color, image_tag, name_from, text_color, and text_italic."),
    ('define daichi = Character(name="Daichi")',
     'Character has no option "name". Write the name first, in quotes: Character("Hana").'),
], ids=["suggest", "plain", "name"])
def test_ac_f03_32_option_lists_with_f04s_image_tag(tmp_path, R2, message):
    """F04 step 4 built ``image_tag``, F05 step 3 ``text_color`` and ``text_italic``, and
    F06 step 1 the four blip options: E75b lists nine (F04 02 §6; F05 07 I-2; AC-F06-01)."""
    (error,) = run_launch(load_r_with(tmp_path, {2: R2})).errors
    assert (error.code, error.line, error.message) == ("E75b", 2, message)


def test_ac_f03_32_image_tag_is_an_option_once_f04_is_built(tmp_path):
    assert set(CHARACTER_OPTIONS) == {"color", "name_from", "image_tag", "text_color",
                                      "text_italic",                     # F05 step 3
                                      "blip", "blip_every", "blip_pitch",
                                      "blip_volume"}                     # F06 step 1
    launch = run_launch(load_r_with(
        tmp_path, {2: 'define daichi = Character("Daichi", image_tag="d")'}))
    assert launch.errors == () and launch.namespace["daichi"].image_tag == "d"


# --- AC-F03-33 ---------------------------------------------------------------------------------

def test_ac_f03_33_a_speaker_in_an_unreachable_label_is_checked(tmp_path):
    program = load_r_with(tmp_path, {2: 'define daichi = "Daichi"'},
                          T='label never:⏎[4]daichi "Yo."⏎[4]return')
    result = run_launch(program)
    (error,) = result.errors
    assert (error.code, error.line) == ("E75", 2)
    assert error.message == ('"daichi" speaks in the story (script/main.vns, line 12), but its '
                             'define gives text, not a character. Write define daichi = '
                             'Character("Daichi").')


def test_e75_example_uses_a_capital_when_the_value_isnt_text(tmp_path):
    (error,) = run_launch(load_r_with(tmp_path, {2: 'define daichi = ""'},
                                      S='daichi "Yo."')).errors
    assert error.message.endswith('gives text, not a character. Write define daichi = '
                                  'Character("Daichi").')


# --- AC-F03-36 ---------------------------------------------------------------------------------

@pytest.mark.parametrize("S, name, color", [
    ('$ hana.color = "#fff000"', "hana", "#e8a0b4"),
    ("$ del daichi.color", "daichi", "#8fb3d9"),
], ids=["set", "del"])
def test_ac_f03_36_the_character_is_unchanged(tmp_path, S, name, color):
    interp = start(load_r(tmp_path, S=S))
    advance(interp)
    failed = [c for c in interp.take_commands(1 << 30) if type(c) is StoryFailed]
    assert failed and failed[-1].error.code == "E85c"
    assert interp.G[name].color == color


# --- Unit: the factory and the object ----------------------------------------------------------

def test_a_character_is_fixed_once_made():
    c = CharacterFactory(frozenset({"hana_name"}))(name_from="hana_name", color="#e8a0b4")
    assert isinstance(c, Character) and c.name is None and c.name_from == "hana_name"
    c._named("hana")
    c._named("other")                                     # first define wins
    for action in (lambda: setattr(c, "color", "#000000"), lambda: delattr(c, "name"),
                   lambda: setattr(c, "new", 1)):
        with pytest.raises(CharacterLocked) as caught:
            action()
        assert caught.value.code == "E85c"
        assert caught.value.message.startswith("hana's options are fixed")
    assert c.color == "#e8a0b4" and dict(c.options) == {"name_from": "hana_name",
                                                         "color": "#e8a0b4"}
    with pytest.raises(TypeError):
        c.options["color"] = "#000000"                    # type: ignore[index]


@pytest.mark.parametrize("args, opts, code", [
    ((), {}, "E75d"), (("A", "B"), {}, "E75d"), (("A",), {"name_from": "n"}, "E75d"),
    ((None,), {}, "E75e"), ((b"A",), {}, "E75e"), (("A",), {"name": "A"}, "E75b"),
    (("A",), {"colour": "#000000"}, "E75b"), (("A",), {"color": "#00000"}, "E75c"),
    (("A",), {"color": "#0000000"}, "E75c"), (("A",), {"color": "red"}, "E75c"),
    (("A",), {"color": None}, "E75c"), ((), {"name_from": 3}, "E75g"),
    ((), {"name_from": "nope"}, "E75f"),
])
def test_the_factory_refuses(args, opts, code):
    with pytest.raises(CharacterOptionError) as caught:
        CharacterFactory(frozenset({"n"}))(*args, **opts)
    assert caught.value.code == code and not caught.value.prefixed


def test_the_factory_accepts():
    make = CharacterFactory(frozenset({"n"}))
    assert make("").name == ""                            # "" shows no name plate
    assert make("A", color="#aBcDeF").color == "#aBcDeF"
    assert make(name_from="n").name_from == "n"
    assert repr(make) == "Character"


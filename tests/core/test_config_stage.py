"""``[stage]``, ``[stage.positions]``, ``[theme.stage]``, and the generic nested-table
validators ``Table`` and ``EntryMap`` (F04 §7.8, §12; I-5, I-6).

AC-F04-24. Values given as text are described the F01 way (``the text "1060"``, with the
quotes hint), as for every other key; see the F04 Step 1 report.
"""

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import pytest

from engine.core import config, config_schema, constants
from engine.core.config_schema import (
    Config,
    EntryMap,
    IntRange,
    StageConfig,
    Table,
    Validator,
    ValueProblem,
    spec,
    toml_key,
)
from engine.script import words

POSITION_VALUE = ("[stage.positions] stall_spot must be a number or [x, y] with numbers from "
                  "-1280 to 2560, but found ")
POSITION_NAME = ("[stage.positions] {} must be one word of letters, digits, and _, not a "
                 'number or statement word, but found "{}"')
ART_HEIGHT = "config.toml, line 2: [stage] art_height must be a whole number from 180 to 4320, but found "
BUILTINS = {"left": (320.0, 720.0), "center": (640.0, 720.0), "right": (960.0, 720.0)}


def messages(result) -> list[str]:
    return [error.format() for error in result.errors]


# --- Defaults and accepted values ---------------------------------------------------------

def test_no_stage_section_gives_defaults_and_only_the_builtin_positions(load):
    result = load(b"")
    assert result.errors == [] and result.warnings == []
    assert result.config.stage.art_height == 720
    assert dict(result.config.stage.positions) == BUILTINS
    assert result.config.theme.stage.empty_color == (0, 0, 0)
    assert result.config == Config()


def test_positions_map_numbers_and_pairs_and_may_redefine_builtins(load):
    result = load("[stage.positions]\nstall_spot = 1060\nhana_close = [560, 760]\nleft = 200\n")
    assert result.errors == [] and result.warnings == []
    assert dict(result.config.stage.positions) == {
        "left": (200.0, 720.0), "center": (640.0, 720.0), "right": (960.0, 720.0),
        "stall_spot": (1060.0, 720.0), "hana_close": (560.0, 760.0)}
    assert all(type(c) is float for xy in result.config.stage.positions.values() for c in xy)


def test_positions_are_read_only(load):
    positions = load("[stage.positions]\nstall_spot = 1060\n").config.stage.positions
    assert isinstance(positions, MappingProxyType)
    with pytest.raises(TypeError):
        positions["x"] = (0.0, 0.0)          # type: ignore[index]


@pytest.mark.parametrize("text", [
    '[theme.stage]\nempty_color = "#102030"\n',
    '[theme]\nstage = { empty_color = "#102030" }\n',
])
def test_both_theme_spellings_give_the_same_color(load, text):
    result = load(text)
    assert result.errors == [] and result.warnings == []
    assert result.config.theme.stage.empty_color == (16, 32, 48)


@pytest.mark.parametrize("value", [180, 4320])
def test_art_height_limits_are_accepted(load, value):
    result = load(f"[stage]\nart_height = {value}\n")
    assert result.errors == []
    assert result.config.stage.art_height == value


@pytest.mark.parametrize("text, xy", [
    ("-1280", (-1280.0, 720.0)), ("2560", (2560.0, 720.0)), ("-1280.0", (-1280.0, 720.0)),
    ("[-1280, 2560]", (-1280.0, 2560.0)), ("[0.5, -3]", (0.5, -3.0)),
])
def test_position_limits_are_accepted(load, text, xy):
    result = load(f"[stage.positions]\np = {text}\n")
    assert result.errors == []
    assert result.config.stage.positions["p"] == xy


def test_inline_positions_table_under_stage(load):
    result = load("[stage]\nart_height = 1080\npositions = { stall_spot = 1060 }\n")
    assert result.errors == []
    assert result.config.stage == StageConfig(1080, MappingProxyType(
        {**BUILTINS, "stall_spot": (1060.0, 720.0)}))


# --- Errors (AC-F04-24 rows) --------------------------------------------------------------

@pytest.mark.parametrize("value", ["1080.5", "179", "4321", "true"])
def test_bad_art_height(load, value):
    result = load(f"[stage]\nart_height = {value}\n")
    assert messages(result) == [ART_HEIGHT + value]
    assert result.loaded is False
    assert result.config.stage.art_height == 720


def test_quoted_position_number(load):
    text = '[stage]\nart_height = 720\n\n\n[stage.positions]\nstall_spot = "1060"\n'
    result = load(text)
    assert messages(result) == [
        "config.toml, line 6: " + POSITION_VALUE + 'the text "1060". Remove the quotes.']
    assert result.loaded is False
    assert dict(result.config.stage.positions) == BUILTINS


@pytest.mark.parametrize("value, found", [
    ("2561", "2561"), ("-1281", "-1281"), ("[1, 2, 3]", "a list"), ("[1]", "a list"),
    ("[1, 2561]", "a list"), ('[1, "2"]', "a list"), ("true", "true"), ("nan", "nan"),
    ("inf", "inf"), ("1" + "0" * 400, "1" + "0" * 38 + "…"), ("{ x = 1 }", "a section"),
])
def test_bad_position_values(load, value, found):
    result = load(f"[stage.positions]\nstall_spot = {value}\n")
    assert messages(result) == ["config.toml, line 2: " + POSITION_VALUE + found]


@pytest.mark.parametrize("key, label, found", [
    ('"stall spot"', '"stall spot"', "stall spot"),
    ("show", "show", "show"),
    ("zoom", "zoom", "zoom"),
    ("Layer", "Layer", "Layer"),          # lower() is checked
    ("SCENE", "SCENE", "SCENE"),
    ('"12"', "12", "12"),
    ("2nd", "2nd", "2nd"),
    ('"a-b"', "a-b", "a-b"),
    ('"ﬁne"', '"ﬁne"', "ﬁne"),          # not NFKC-normal
    ('"x\\ty"', '"x\\ty"', "x\\ty"),      # control characters are escaped
    ('""', '""', ""),
])
def test_bad_position_names(load, key, label, found):
    result = load(f"[stage.positions]\n\n{key} = 1060\n")
    assert messages(result) == ["config.toml, line 3: " + POSITION_NAME.format(label, found)]


def test_one_error_per_bad_entry_and_valid_entries_are_kept(load):
    result = load('[stage.positions]\nok = 1\n"bad name" = "bad value"\nshow = 5\nb = 99999\n'
                  "fine = [1, 2]\n")
    assert [error.line for error in result.errors] == [3, 4, 5]
    assert set(result.config.stage.positions) == set(BUILTINS) | {"ok", "fine"}


def test_names_not_reserved_elsewhere_are_accepted(load):
    result = load('[stage.positions]\nhana = 1\nlefty = 2\n_x = 3\nnarrator = 4\n"名前" = 5\n')
    assert result.errors == []
    assert {"hana", "lefty", "_x", "narrator", "名前"} <= set(result.config.stage.positions)


def test_long_names_are_cut_in_the_label_and_the_value(load):
    name = "n" * 300
    result = load(f'[stage.positions]\n"{name} x" = 1\n')
    shown = "n" * 39 + "…"
    assert messages(result) == [
        "config.toml, line 2: " + POSITION_NAME.format(f'"{shown}"', shown)]


def test_too_many_positions_give_one_error_quickly(load):
    text = "[stage.positions]\n" + "".join(f"p{i} = {i % 2000}\n" for i in range(1001))
    start = time.perf_counter()
    result = load(text)
    assert time.perf_counter() - start < 2.0
    assert messages(result) == [
        "config.toml, line 1: [stage] positions must have at most 1000 entries, but found 1001"]
    assert dict(result.config.stage.positions) == BUILTINS


def test_exactly_1000_positions_are_accepted(load):
    text = "[stage.positions]\n" + "".join(f"p{i} = 1\n" for i in range(1000))
    result = load(text)
    assert result.errors == []
    assert len(result.config.stage.positions) == 1000 + len(BUILTINS)


@pytest.mark.parametrize("text, message", [
    ("[stage]\npositions = 5\n",
     "config.toml, line 2: [stage] positions must be a section, but found 5"),
    ('[theme]\nstage = "x"\n',
     'config.toml, line 2: [theme] stage must be a section, but found the text "x"'),
    ('[theme.stage]\nempty_color = "red"\n',
     'config.toml, line 2: [theme.stage] empty_color must be a color written as "#RRGGBB", '
     'for example "#000000", but found the text "red"'),
    ('[theme]\nstage = { empty_color = 5 }\n',
     'config.toml, line 2: [theme.stage] empty_color must be a color written as "#RRGGBB", '
     'for example "#000000", but found 5'),
])
def test_nested_table_errors(load, text, message):
    assert messages(load(text)) == [message]


# --- Warnings -----------------------------------------------------------------------------

def test_misspelled_stage_key_warns_and_startup_continues(load):
    result = load("[stage]\nart_heigth = 1080\n")
    assert result.errors == []
    assert result.warnings == [
        'config.toml, line 2: unknown key [stage] art_heigth — did you mean "art_height"?']
    assert result.loaded is True
    assert result.config.stage.art_height == 720


def test_unknown_keys_in_theme_tables_warn(load):
    result = load('[theme.stage]\nempty_colour = "#000000"\n[theme.textbx]\nx = 1\n')
    assert result.errors == []
    assert result.warnings == [
        'config.toml, line 2: unknown key [theme.stage] empty_colour — did you mean '
        '"empty_color"?',
        'config.toml, line 3: unknown key [theme] textbx — did you mean "textbox"?',
    ]


def test_misspelled_stage_section_is_suggested(load):
    result = load("[stag]\nart_height = 1080\n")
    assert result.warnings == ["config.toml, line 1: unknown section [stag] — did you mean [stage]?"]


# --- The generic validators (I-6) ---------------------------------------------------------

class _Upper(Validator):
    """A key check that changes the stored key, as an F08-style check might."""
    expected = "upper-case letters"

    def check(self, value: object) -> object:
        if type(value) is str and value.isalpha() and value.isupper():
            return value.lower()
        raise ValueProblem


@dataclass(frozen=True)
class _Probe:
    sizes: Mapping[str, int] = field(
        default=MappingProxyType({}),
        metadata=spec(EntryMap(_Upper(), IntRange(1, 9), 3, label=lambda key: f"<{key}>")))
    inner: StageConfig = field(default_factory=StageConfig, metadata=spec(Table(StageConfig)))


@dataclass(frozen=True)
class _ProbeConfig(Config):
    probe: _Probe = field(default_factory=_Probe)


def test_entry_map_is_generic_with_a_label_formatter_and_tables_nest(load, monkeypatch):
    monkeypatch.setitem(config_schema.SECTIONS, "probe", _Probe)
    monkeypatch.setattr(config, "Config", _ProbeConfig)
    result = load("[probe.sizes]\nAB = 3\nab = 3\nCD = 10\n[probe.inner]\nart_height = 1\n"
                  "[probe.inner.positions]\nshow = 1\n")
    assert messages(result) == [
        'config.toml, line 3: [probe.sizes] <ab> must be upper-case letters, but found "ab"',
        "config.toml, line 4: [probe.sizes] <CD> must be a whole number from 1 to 9, "
        "but found 10",
        "config.toml, line 6: [probe.inner] art_height must be a whole number from 180 to "
        "4320, but found 1",
        "config.toml, line 8: [probe.inner.positions] show must be one word of letters, "
        'digits, and _, not a number or statement word, but found "show"',
    ]
    probe = result.config.probe
    assert dict(probe.sizes) == {"ab": 3}
    assert dict(probe.inner.positions) == BUILTINS


def test_entry_map_over_its_limit_reads_no_entry(load, monkeypatch):
    monkeypatch.setitem(config_schema.SECTIONS, "probe", _Probe)
    monkeypatch.setattr(config, "Config", _ProbeConfig)
    result = load("[probe]\nsizes = { AB = 1, CD = 2, EF = 3, GH = 4 }\n")
    assert messages(result) == [
        "config.toml, line 2: [probe] sizes must have at most 3 entries, but found 4"]
    assert dict(result.config.probe.sizes) == {}


@pytest.mark.parametrize("key, shown", [
    ("stall_spot", "stall_spot"), ("12", "12"), ("a-b", "a-b"), ("stall spot", '"stall spot"'),
    ("bgm/festival.ogg", '"bgm/festival.ogg"'), ("", '""'), ("é", '"é"'),
    ("a\nb", '"a\\nb"'), ("x" * 50, '"' + "x" * 39 + '…"'),
])
def test_toml_key_labels(key, shown):
    assert toml_key(key) == shown


# --- Constants and the word re-export (I-5) -----------------------------------------------

def test_stage_constants():
    assert constants.STAGE_COORD_RANGE == (-1280, 2560)
    assert constants.LAYER_RANGE == (-100, 100)
    assert constants.ZOOM_RANGE == (0.25, 4.0)
    assert constants.ART_HEIGHT_RANGE == (180, 4320)
    assert constants.STAGE_POSITIONS_MAX == 1000
    assert dict(constants.BUILTIN_POSITIONS) == BUILTINS
    assert isinstance(constants.BUILTIN_POSITIONS, MappingProxyType)


def test_words_reexports_the_same_objects():
    assert words.STATEMENT_WORDS is constants.STATEMENT_WORDS
    assert words.STAGE_WORDS is constants.STAGE_WORDS
    assert constants.STAGE_WORDS == {"layer", "zoom", "flip"}
    assert len(constants.STATEMENT_WORDS) == 40       # F14: rollback; F20: flowchart; F32: ui;
    #                                                   F34: cg no longer reserved
    assert constants.STATEMENT_WORDS - constants.STATEMENT_WORDS_F02 == {"rollback", "flowchart",
                                                                         "ui"}
    assert not constants.STAGE_WORDS & constants.STATEMENT_WORDS
    assert words.MODIFIER_WORDS == {"at", "as", "behind"}          # F02's set, unchanged (I-4)

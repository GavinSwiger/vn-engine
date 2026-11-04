"""F50 Timing assist, step 1 (SPEC §4, §7; 07 I-1, I-2, I-6): AC-F50-01 (the stored key and
``FORMAT`` 5), AC-F50-02 (``[effects] timing_assist`` as the starting value) and AC-F50-03
(``timing_limit``, the one rule)."""

import json
from pathlib import Path
from types import MappingProxyType

from engine.app.settings import SettingsService, bad_value_text, config_defaults
from engine.core.config_schema import Config, EffectsConfig
from engine.core.settings_schema import (
    FORMAT,
    KEYS,
    TIMING_LEVELS,
    TIMING_NORMAL,
    TIMING_OFF,
    TIMING_SLOWER,
    IntKey,
    check,
    timing_limit,
)
from engine.persist.settings_file import LoadedSettings, Outcome, parse_settings
from tests.fakes.fake_window import FakeWindow

LINE2 = "config.toml, line 2: "


def test_ac_f50_01_key_format_and_refused_values():
    assert KEYS["timing_assist"] == IntKey(0, 2) and FORMAT == 5
    assert list(KEYS)[-1] == "timing_assist"                          # 07 I-1: W71 order
    for value in (0, 1, 2):
        data = json.dumps({"format": 5, "values": {"timing_assist": value}}).encode()
        assert parse_settings(data).values == {"timing_assist": value}
    for value, word in ((3, "3"), (-1, "-1"), ("2", "text"), (True, "true"),
                        (1.0, "a decimal number")):
        problem = check("timing_assist", value)
        assert (problem.must, problem.found) == ("a whole number from 0 to 2", word), value
        assert bad_value_text("f", "timing_assist", problem.must, problem.found) == (
            f"settings in f: timing_assist must be a whole number from 0 to 2, but found "
            f"{word}, so the default is used.")
        data = json.dumps({"format": 5, "values": {"timing_assist": value}}).encode()
        loaded = parse_settings(data)
        assert loaded.values == {} and [p.key for p in loaded.problems] == ["timing_assist"]
        service = SettingsService(
            LoadedSettings(loaded.values, Outcome.OK, None, folder=None, writable=False),
            Config(effects=EffectsConfig(timing_assist="slower")), window=FakeWindow(),
            display_scale=1.0, writer=None, game_root=Path("."))
        assert service.value("timing_assist") == TIMING_SLOWER          # the config default


def test_ac_f50_02_config_starting_value_and_reset(load, tmp_path):
    for level, stored in (("normal", 0), ("slower", 1), ("off", 2)):
        result = load(f'[effects]\ntiming_assist = "{level}"\n')
        assert result.errors == [] and result.loaded, level
        assert config_defaults(result.config)["timing_assist"] == stored
    assert config_defaults(Config())["timing_assist"] == TIMING_NORMAL
    result = load('[effects]\ntiming_assist = "fast"\n')
    assert [e.format() for e in result.errors] == [
        LINE2 + '[effects] timing_assist must be one of "normal", "slower", "off", but found '
                'the text "fast"']
    assert result.loaded is False
    config = Config(effects=EffectsConfig(timing_assist="off"))
    service = SettingsService(
        LoadedSettings(MappingProxyType({"timing_assist": 0}), Outcome.OK, None,
                       folder=None, writable=False),
        config, window=FakeWindow(), display_scale=1.0, writer=None, game_root=tmp_path)
    assert service.value("timing_assist") == TIMING_NORMAL
    assert not service.locked("timing_assist")                         # never a lock
    service.set("timing_assist", TIMING_SLOWER)
    service.reset()
    assert service.value("timing_assist") == TIMING_OFF


def test_ac_f50_03_timing_limit_rule():
    assert TIMING_LEVELS == ("normal", "slower", "off")
    table = [((5, TIMING_NORMAL), 5.0), ((5, TIMING_SLOWER), 10.0), ((2.5, TIMING_SLOWER), 5.0),
             ((5, TIMING_OFF), None), ((5, 7), 5.0)]
    for (seconds, level), want in table:
        assert timing_limit(seconds, level) == want, (seconds, level)
        if level in (0, 1, 2):
            assert timing_limit(seconds, TIMING_LEVELS[level]) == want, (seconds, level)
    assert timing_limit(5, "fast") == 5.0 and timing_limit(5, True) == 5.0
    assert type(timing_limit(5, TIMING_NORMAL)) is float

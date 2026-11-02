"""F15 step 1 — AC-F15-14: ``[skip]`` and ``[auto]`` (F15 ``SPEC.md`` §5 with ``07`` I-5:
durations in seconds) and ``SkipAuto.settings`` over them (I-8). A bad value is one F01
``ConfigError`` (the launch stops) and the result keeps the default."""

from types import SimpleNamespace

from engine.core.config_schema import SECTIONS, AutoConfig, Config, SkipConfig
from engine.ui.builtin.skip_auto import SkipAuto, SkipAutoSettings

LINE2 = "config.toml, line 2: "


def test_ac14_config_defaults_errors_and_settings_over_config(load):
    config = Config()
    assert (config.skip, config.auto) == (SkipConfig(all=False), AutoConfig(
        delay=1.0, per_char=0.04, wait_for_voice=True))
    assert SECTIONS["skip"] is SkipConfig and SECTIONS["auto"] is AutoConfig
    for header, line, message in (
            ("[auto]", "delay = -1", "[auto] delay must be a number from 0 to 10, but found -1"),
            ("[auto]", "per_char = true",
             "[auto] per_char must be a number from 0 to 0.5, but found true"),
            ("[skip]", 'all = "x"', '[skip] all must be true or false, but found the text "x"')):
        result = load(f"{header}\n{line}\n")
        assert [e.format() for e in result.errors] == [LINE2 + message], line
        assert (result.config.skip, result.config.auto) == (SkipConfig(), AutoConfig())
    result = load("[skip]\nall = true\n[auto]\ndelay = 10\nper_char = 0.5\n"
                  "wait_for_voice = false\n")
    assert result.errors == [] and result.loaded
    assert result.config.auto == AutoConfig(delay=10.0, per_char=0.5, wait_for_voice=False)
    # Settings: None follows config, a value wins (read each frame), auto_scale clamps.
    stage = SimpleNamespace(changes=0)
    sa = SkipAuto(SimpleNamespace(), stage, store=None, audio=None, skip_all=True,
                  wait_for_voice=False)
    assert (sa.skip_all(), sa.wait_for_voice(), sa.auto_scale()) == (True, False, 1.0)
    sa.settings = SkipAutoSettings(skip_all=False, auto_wait_voice=True, auto_scale=10)
    assert (sa.skip_all(), sa.wait_for_voice(), sa.auto_scale()) == (False, True, 4.0)
    sa.settings = SkipAutoSettings(auto_scale=0.1)
    assert sa.auto_scale() == 0.25

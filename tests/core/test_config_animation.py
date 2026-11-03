"""F38 step 1 — AC-F38-09: ``[animation]`` (``SPEC.md`` §3): defaults, ranges, and F01's error
form for each key (one ``ConfigError``, the default kept); ``AnimSettings`` is built from it."""

import pytest

from engine.core.config_schema import SECTIONS, AnimationConfig, Config, key_doc
from engine.render.spriteanim import AnimSettings

LINE2 = "config.toml, line 2: "
CASES = [  # row, accepted value, or the error's text after "[animation] <key> must be "
    ("enabled = false", False, None),
    ('enabled = "no"', None, 'true or false, but found the text "no"'),
    ("blink_every = 1", 1.0, None),
    ("blink_every = 30", 30.0, None),
    ("blink_every = 0.5", None, "a number from 1 to 30, but found 0.5"),
    ("blink_every = 31", None, "a number from 1 to 30, but found 31"),
    ("blink_frame = 0.02", 0.02, None),
    ("blink_frame = 0.6", None, "a number from 0.02 to 0.5, but found 0.6"),
    ("talk_frame = 0.5", 0.5, None),
    ("talk_frame = 0.01", None, "a number from 0.03 to 0.5, but found 0.01"),
    ("talk_frame = true", None, "a number from 0.03 to 0.5, but found true"),
]


@pytest.mark.parametrize("row, value, problem", CASES, ids=[c[0] for c in CASES])
def test_ac_f38_09_animation_config(load, row, value, problem):
    assert SECTIONS["animation"] is AnimationConfig
    assert Config().animation == AnimationConfig(True, 4.0, 0.08, 0.1)
    assert AnimSettings.from_config(Config().animation) == AnimSettings()
    key = row.split(" ")[0]
    assert key_doc("animation", key) and key_doc("animation", "")
    result = load(f"[animation]\n{row}\n")
    if problem is None:
        assert result.errors == [] and getattr(result.config.animation, key) == value
    else:
        assert [e.format() for e in result.errors] == [
            f"{LINE2}[animation] {key} must be {problem}"]
        assert result.config.animation == AnimationConfig()

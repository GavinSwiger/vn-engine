"""F09 step 1 — ``[effects]`` and ``[theme.effects]`` (F09 ``04`` §12; AC-F09-38): the
defaults, each bad value stopping the launch with F01's config error shape (AC-F01-11)
naming the key, the range ends accepted, and an unknown key warning with a did-you-mean
(AC-F01-17)."""

from engine.core.config_schema import Config, EffectsConfig, EffectsTheme

LINE2 = "config.toml, line 2: "


def messages(result) -> list[str]:
    return [error.format() for error in result.errors]


def test_ac38_defaults():
    effects, theme = Config().effects, Config().theme.effects
    assert effects == EffectsConfig()
    assert (effects.dissolve, effects.fade, effects.shake, effects.shake_size, effects.flash,
            effects.reduce) == (0.5, 1.0, 0.5, "medium", 0.3, False)
    assert theme == EffectsTheme()
    assert (theme.flash_color, theme.fade_color) == ((0xFF, 0xFF, 0xFF), (0, 0, 0))


def test_ac38_no_section_gives_the_defaults(load):
    result = load('[game]\ntitle = "x"\n')
    assert result.errors == [] and result.loaded
    assert result.config.effects == EffectsConfig()
    assert result.config.theme.effects == EffectsTheme()


INVALID = [
    ("[effects]", 'dissolve = "fast"',
     '[effects] dissolve must be a number from 0 to 30, but found the text "fast"'),
    ("[effects]", "fade = 31", "[effects] fade must be a number from 0 to 30, but found 31"),
    ("[effects]", "shake = 0", "[effects] shake must be a number from 0.1 to 10, but found 0"),
    ("[effects]", "flash = 3", "[effects] flash must be a number from 0.1 to 2, but found 3"),
    ("[effects]", 'shake_size = "huge"',
     '[effects] shake_size must be one of "small", "medium", "large", but found the text '
     '"huge"'),
    ("[effects]", 'reduce = "yes"',
     '[effects] reduce must be true or false, but found the text "yes"'),
    ("[theme.effects]", 'flash_color = "#FFF"',
     '[theme.effects] flash_color must be a color written as "#RRGGBB", for example '
     '"#000000", but found the text "#FFF"'),
]


def test_ac38_invalid_values_stop_the_launch(load):
    for header, line, message in INVALID:
        result = load(f"{header}\n{line}\n")
        assert messages(result) == [LINE2 + message], line
        assert result.loaded is False, line


def test_ac38_range_ends_are_accepted(load):
    result = load('[effects]\ndissolve = 0\nfade = 30\nshake = 0.1\nflash = 2\n'
                  'shake_size = "large"\nreduce = true\n'
                  '[theme.effects]\nflash_color = "#ffe08a"\nfade_color = "#FFFFFF"\n')
    assert result.errors == [] and result.warnings == [] and result.loaded
    effects = result.config.effects
    assert (effects.dissolve, effects.fade, effects.shake, effects.flash) == (0.0, 30.0, 0.1, 2.0)
    assert effects.shake_size == "large" and effects.reduce is True
    assert result.config.theme.effects.flash_color == (0xFF, 0xE0, 0x8A)


def test_ac38_unknown_key_warns_with_a_suggestion(load):
    result = load("[effects]\ndissolv = 1\n")
    assert result.errors == [] and result.loaded
    assert result.warnings == [LINE2 + 'unknown key [effects] dissolv — did you mean '
                               '"dissolve"?']


# --- F28 step 1 — AC-F28-01: [effects] glitch and glitch_size (F28 04 §10, 07 I-10) ----------

F28_INVALID = [  # (line, the message after "config.toml, line 2: ")
    ('glitch_size = "huge"',
     '[effects] glitch_size must be one of "small", "medium", "large", but found the text '
     '"huge"'),
    ("glitch = 0.05", "[effects] glitch must be a number from 0.1 to 30, but found 0.05"),
    ("glitch = 31", "[effects] glitch must be a number from 0.1 to 30, but found 31"),
    ('glitch = "fast"',
     '[effects] glitch must be a number from 0.1 to 30, but found the text "fast"'),
    ('glitch_size = "Large"',
     '[effects] glitch_size must be one of "small", "medium", "large", but found the text '
     '"Large"'),
    ("glitch_size = 2",
     '[effects] glitch_size must be one of "small", "medium", "large", but found 2'),
]


def test_ac_f28_01_glitch_keys(load):
    """Defaults; each bad value stops the launch naming the key (AC-F01-11's shape); the
    range ends and a size are accepted; a misspelt key warns with a suggestion (AC-F01-17)."""
    effects = Config().effects
    assert (effects.glitch, effects.glitch_size) == (0.5, "medium")
    result = load('[game]\ntitle = "x"\n')
    assert result.errors == [] and result.config.effects == EffectsConfig()
    for line, message in F28_INVALID:
        result = load(f"[effects]\n{line}\n")
        assert messages(result) == [LINE2 + message], line
        assert result.loaded is False, line
    for text, value in (("glitch = 0.1", 0.1), ("glitch = 30", 30.0)):
        result = load(f"[effects]\n{text}\n")
        assert result.errors == [] and result.warnings == [] and result.loaded, text
        assert result.config.effects.glitch == value
    result = load('[effects]\nglitch_size = "small"\n')
    assert result.errors == [] and result.config.effects.glitch_size == "small"
    result = load('[effects]\nglitch_sise = "small"\n')
    assert result.errors == [] and result.loaded
    assert result.warnings == [LINE2 + 'unknown key [effects] glitch_sise — did you mean '
                               '"glitch_size"?']

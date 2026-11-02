"""``[audio]``, ``[audio.loop_start]``, and the validators ``Seconds`` and ``AudioFileKey``
(F08 §13 with 07 I-6; 02 §3.6, §5.2).

AC-F08-07. Values given as text are described the F01 way (``the text "0.5s"``, with the
quotes hint), as for every other key (F04 I-19); a bad ``[audio.loop_start]`` key keeps
``EntryMap``'s key form (``but found "…"``). The launch half (errors on the error screen,
in order) is F01's generic path (``tests/app/test_error_mode.py``).
"""

import dataclasses
from types import MappingProxyType

import pytest

from engine.core import constants
from engine.core.config import load_config
from engine.core.config_schema import (
    SECTIONS,
    AudioConfig,
    AudioFileKey,
    Config,
    EntryMap,
    Opacity,
    Seconds,
    ValueProblem,
    quoted_key,
    toml_key,
)

LINE2 = "config.toml, line 2: "
VOLUME = "[audio] {} must be a whole number from 0 to 100, but found "
FADE = "[audio] {} must be seconds from 0 to 60, but found "
BOOL = "[audio] {} must be true or false, but found "
LOOP_VALUE = '[audio.loop_start] "{}" must be seconds from 0 to 3600, but found '
LOOP_KEY = ('[audio.loop_start] "{0}" must be a file inside audio/ with its extension, '
            'e.g. "bgm/festival.ogg", but found "{0}"')

AC_FILE = """\
[audio]
music_volume = 0.7
music_fadeout = "0.5s"

[audio.loop_start]
"bgm/festival.ogg" = "0:08"
"audio/bgm/festival.ogg" = 8.0
"""

EXAMPLE = """\
[audio]
music_volume = 60

[audio.loop_start]
"bgm/festival.ogg" = 8.0          # the intro plays once; every repeat starts here
"""


def messages(result) -> list[str]:
    return [error.format() for error in result.errors]


# --- AC-F08-07: the four errors, in order --------------------------------------------------

def test_ac_f08_07_the_four_errors_in_line_order(load):
    result = load(AC_FILE)
    assert messages(result) == [
        "config.toml, line 2: [audio] music_volume must be a whole number from 0 to 100, "
        "but found 0.7",
        "config.toml, line 3: [audio] music_fadeout must be seconds from 0 to 60, "
        'but found the text "0.5s"',
        'config.toml, line 6: [audio.loop_start] "bgm/festival.ogg" must be seconds from 0 '
        'to 3600, but found the text "0:08"',
        'config.toml, line 7: [audio.loop_start] "audio/bgm/festival.ogg" must be a file '
        'inside audio/ with its extension, e.g. "bgm/festival.ogg", but found '
        '"audio/bgm/festival.ogg"',
    ]
    assert [error.line for error in result.errors] == [2, 3, 6, 7]
    assert all("\n" not in text for text in messages(result))
    assert result.loaded is False
    assert result.config.audio == AudioConfig()       # every bad value falls back


# --- Defaults (AC-F08-07 "And") ------------------------------------------------------------

def test_no_audio_section_gives_the_defaults(make_game):
    for paths in (make_game(None), make_game('[game]\ntitle = "x"\n')):
        audio = load_config(paths).config.audio
        assert audio == AudioConfig()
        assert (audio.master_volume, audio.music_volume, audio.sound_volume,
                audio.voice_volume) == (100, 70, 80, 100)
        assert (audio.music_fadein, audio.music_fadeout) == (0.0, 0.5)
        assert (audio.sound_fadein, audio.sound_fadeout) == (0.0, 0.0)
        assert (audio.restore_fadeout, audio.restore_fadein) == (0.5, 1.0)
        assert audio.play_unfocused is True and audio.play_minimized is True
        assert dict(audio.loop_start) == {}


def test_the_keys_are_those_of_02_section_3_6():
    keys = {f.name for f in dataclasses.fields(AudioConfig) if "validator" in f.metadata}
    assert keys == {f.name for f in dataclasses.fields(AudioConfig)}
    assert keys == {"master_volume", "music_volume", "sound_volume", "voice_volume",
                    "music_fadein", "music_fadeout", "sound_fadein", "sound_fadeout",
                    "restore_fadeout", "restore_fadein", "play_unfocused", "play_minimized",
                    "loop_start"}
    assert SECTIONS["audio"] is AudioConfig
    assert isinstance(Config().audio, AudioConfig)


def test_audio_config_and_its_loop_starts_are_read_only(load):
    audio = load(EXAMPLE).config.audio
    with pytest.raises(dataclasses.FrozenInstanceError):
        audio.music_volume = 1                       # type: ignore[misc]
    with pytest.raises(TypeError):
        audio.loop_start["bgm/x.ogg"] = 1.0          # type: ignore[index]
    with pytest.raises(TypeError):
        AudioConfig().loop_start["bgm/x.ogg"] = 1.0  # type: ignore[index]


# --- Accepted values -----------------------------------------------------------------------

def test_the_02_script_example_is_accepted(load):
    result = load(EXAMPLE)
    assert result.errors == [] and result.warnings == [] and result.loaded
    audio = result.config.audio
    assert audio.music_volume == 60
    assert dict(audio.loop_start) == {"bgm/festival.ogg": 8.0}
    assert type(audio.loop_start["bgm/festival.ogg"]) is float
    assert audio.master_volume == 100                 # untouched keys keep their defaults


ACCEPTED_ROWS = [
    ("master_volume = 0", "master_volume", 0),
    ("voice_volume = 100", "voice_volume", 100),
    ("sound_volume = 55", "sound_volume", 55),
    ("music_fadein = 0", "music_fadein", 0.0),
    ("music_fadeout = 60", "music_fadeout", 60.0),
    ("sound_fadein = 60.0", "sound_fadein", 60.0),
    ("sound_fadeout = 0.25", "sound_fadeout", 0.25),
    ("restore_fadeout = 0.0", "restore_fadeout", 0.0),
    ("restore_fadein = 2.5", "restore_fadein", 2.5),
    ("play_unfocused = false", "play_unfocused", False),
    ("play_minimized = false", "play_minimized", False),
    ("play_minimized = true", "play_minimized", True),
]


def test_accepted_values(load):
    for line, name, stored in ACCEPTED_ROWS:
        result = load(f"[audio]\n{line}\n")
        assert result.errors == [] and result.warnings == [], line
        value = getattr(result.config.audio, name)
        assert value == stored and type(value) is type(stored), line


LOOP_START_ROWS = [
    ('"bgm/festival.ogg"', "0", 0.0),
    ('"bgm/festival.ogg"', "3600", 3600.0),
    ('"bgm/festival.ogg"', "3600.0", 3600.0),
    ('"bgm/festival.ogg"', "12.5", 12.5),
    ('"theme.OPUS"', "1", 1.0),
    ("'bgm/a b/Ünï.flac'", "2", 2.0),
    ('"bgm/theme.m4a"', "3", 3.0),                    # any extension; W31 is later
    ('"~/a.ogg"', "4", 4.0),                          # audio/~/a.ogg stays inside audio/
]


def test_accepted_loop_starts(load):
    for key, value, stored in LOOP_START_ROWS:
        result = load(f"[audio.loop_start]\n{key} = {value}\n")
        assert result.errors == [] and result.warnings == [], key
        (file, point), = result.config.audio.loop_start.items()
        assert file == key.strip("\"'"), key
        assert point == stored and type(point) is float, key


def test_loop_starts_inline_and_as_a_dotted_key(load):
    for text in ('[audio]\nloop_start = { "bgm/a.ogg" = 1.5 }\n',
                 '[audio]\nloop_start."bgm/a.ogg" = 1.5\n'):
        result = load(text)
        assert result.errors == []
        assert dict(result.config.audio.loop_start) == {"bgm/a.ogg": 1.5}


def test_every_bad_entry_is_reported_and_good_entries_are_kept(load):
    result = load('[audio]\nmusic_volume = 101\nsound_volume = 10\n[audio.loop_start]\n'
                  '"bgm/a.ogg" = 1\n"bgm/b" = 2\n"bgm/c.ogg" = -1\n"bgm/d.ogg" = 4.5\n')
    assert [error.line for error in result.errors] == [2, 6, 7]
    audio = result.config.audio
    assert (audio.music_volume, audio.sound_volume) == (70, 10)
    assert dict(audio.loop_start) == {"bgm/a.ogg": 1.0, "bgm/d.ogg": 4.5}


# --- Errors (AC-F08-07 "Rejected with the same shapes", then edge cases) ---------------------

AC_ROWS = [
    ("[audio]", "master_volume = true", VOLUME.format("master_volume") + "true"),
    ("[audio]", "voice_volume = 101", VOLUME.format("voice_volume") + "101"),
    ("[audio]", "music_fadein = 61", FADE.format("music_fadein") + "61"),
    ("[audio]", "restore_fadein = -1", FADE.format("restore_fadein") + "-1"),
    ("[audio]", "sound_fadeout = true", FADE.format("sound_fadeout") + "true"),
    ("[audio]", 'play_minimized = "yes"', BOOL.format("play_minimized") + 'the text "yes"'),
    ("[audio.loop_start]", '"bgm\\\\festival.ogg" = 8.0', LOOP_KEY.format("bgm\\festival.ogg")),
    ("[audio.loop_start]", '"bgm/festival" = 8.0', LOOP_KEY.format("bgm/festival")),
]


def test_ac_f08_07_rejected_rows(load):
    for header, line, message in AC_ROWS:
        result = load(f"{header}\n{line}\n")
        assert messages(result) == [LINE2 + message], line
        assert result.loaded is False, line
        assert result.config == Config(), line


EDGE_ROWS = [
    ("[audio]", "music_volume = -1", VOLUME.format("music_volume") + "-1"),
    ("[audio]", "music_volume = 70.0", VOLUME.format("music_volume") + "70.0"),
    ("[audio]", 'music_volume = "70"',
     VOLUME.format("music_volume") + 'the text "70". Remove the quotes.'),
    ("[audio]", 'music_volume = "70%"', VOLUME.format("music_volume") + 'the text "70%"'),
    ("[audio]", 'music_volume = "0.7"', VOLUME.format("music_volume") + 'the text "0.7"'),
    ("[audio]", "music_fadein = 60.0001", FADE.format("music_fadein") + "60.0001"),
    ("[audio]", "music_fadein = -0.5", FADE.format("music_fadein") + "-0.5"),
    ("[audio]", "music_fadein = false", FADE.format("music_fadein") + "false"),
    ("[audio]", "music_fadein = nan", FADE.format("music_fadein") + "nan"),
    ("[audio]", "music_fadein = inf", FADE.format("music_fadein") + "inf"),
    ("[audio]", "music_fadein = -inf", FADE.format("music_fadein") + "-inf"),
    ("[audio]", "music_fadein = 1e400", FADE.format("music_fadein") + "inf"),
    ("[audio]", "music_fadein = 1" + "0" * 400, FADE.format("music_fadein") + "1" + "0" * 38 + "…"),
    ("[audio]", "music_fadein = [1.0]", FADE.format("music_fadein") + "a list"),
    ("[audio]", "music_fadein = 1979-05-27", FADE.format("music_fadein") + "a date or time"),
    ("[audio]", 'music_fadein = "1.5"',
     FADE.format("music_fadein") + 'the text "1.5". Remove the quotes.'),
    ("[audio]", 'music_fadein = "2"',
     FADE.format("music_fadein") + 'the text "2". Remove the quotes.'),
    ("[audio]", 'music_fadein = "90.0"', FADE.format("music_fadein") + 'the text "90.0"'),
    ("[audio]", 'music_fadein = "1.5s"', FADE.format("music_fadein") + 'the text "1.5s"'),
    ("[audio]", "play_unfocused = 1", BOOL.format("play_unfocused") + "1"),
    ("[audio]", 'play_unfocused = "false"',
     BOOL.format("play_unfocused") + 'the text "false". Remove the quotes.'),
    ("[audio]", "loop_start = 5", "[audio] loop_start must be a section, but found 5"),
    ("[audio]", 'loop_start = ["bgm/a.ogg"]',
     "[audio] loop_start must be a section, but found a list"),
    ("[audio.loop_start]", '"bgm/festival.ogg" = 3600.5',
     LOOP_VALUE.format("bgm/festival.ogg") + "3600.5"),
    ("[audio.loop_start]", '"bgm/festival.ogg" = -1', LOOP_VALUE.format("bgm/festival.ogg") + "-1"),
    ("[audio.loop_start]", '"bgm/festival.ogg" = true',
     LOOP_VALUE.format("bgm/festival.ogg") + "true"),
    ("[audio.loop_start]", '"bgm/festival.ogg" = nan', LOOP_VALUE.format("bgm/festival.ogg") + "nan"),
    ("[audio.loop_start]", '"bgm/festival.ogg" = "8.0"',
     LOOP_VALUE.format("bgm/festival.ogg") + 'the text "8.0". Remove the quotes.'),
    ("[audio.loop_start]", '"bgm/festival.ogg" = { a = 1 }',
     LOOP_VALUE.format("bgm/festival.ogg") + "a section"),
    ("[audio.loop_start]", '"Audio/bgm/a.ogg" = 1', LOOP_KEY.format("Audio/bgm/a.ogg")),
    ("[audio.loop_start]", '"AUDIO/a.ogg" = 1', LOOP_KEY.format("AUDIO/a.ogg")),
    ("[audio.loop_start]", '"audio/" = 1', LOOP_KEY.format("audio/")),
    ("[audio.loop_start]", '"../bgm/a.ogg" = 1', LOOP_KEY.format("../bgm/a.ogg")),
    ("[audio.loop_start]", '"/bgm/a.ogg" = 1', LOOP_KEY.format("/bgm/a.ogg")),
    ("[audio.loop_start]", '"C:/bgm/a.ogg" = 1', LOOP_KEY.format("C:/bgm/a.ogg")),
    ("[audio.loop_start]", '"bgm//a.ogg" = 1', LOOP_KEY.format("bgm//a.ogg")),
    ("[audio.loop_start]", '"./a.ogg" = 1', LOOP_KEY.format("./a.ogg")),
    ("[audio.loop_start]", '"bgm/con.ogg" = 1', LOOP_KEY.format("bgm/con.ogg")),
    ("[audio.loop_start]", '"bgm/a.ogg " = 1', LOOP_KEY.format("bgm/a.ogg ")),
    ("[audio.loop_start]", '"bgm/a.ogg." = 1', LOOP_KEY.format("bgm/a.ogg.")),
    ("[audio.loop_start]", '"bgm/.ogg" = 1', LOOP_KEY.format("bgm/.ogg")),
    ("[audio.loop_start]", '"bgm.d/festival" = 1', LOOP_KEY.format("bgm.d/festival")),
    ("[audio.loop_start]", '"bgm/" = 1', LOOP_KEY.format("bgm/")),
    ("[audio.loop_start]", '"" = 1', LOOP_KEY.format("")),
    ("[audio.loop_start]", "festival = 1", LOOP_KEY.format("festival")),   # quoted label
    # Unquoted, theme.ogg is a dotted key: an entry "theme" holding a table.
    ("[audio.loop_start]", "theme.ogg = 1", LOOP_KEY.format("theme")),
    ("[audio.loop_start]", '"a\\tb.ogg" = 1', LOOP_KEY.format("a\\tb.ogg")),
    ("[audio.loop_start]", '"' + "f" * 1100 + '.ogg" = 1', LOOP_KEY.format("f" * 39 + "…")),
    # The key is checked first: a bad key with a bad value is one message.
    ("[audio.loop_start]", '"bgm/festival" = "0:08"', LOOP_KEY.format("bgm/festival")),
]


def test_edge_case_errors(load):
    for header, line, message in EDGE_ROWS:
        result = load(f"{header}\n{line}\n")
        assert messages(result) == [LINE2 + message], line[:40]
        assert result.config == Config(), line[:40]


def test_too_many_loop_starts_is_one_error_and_none_are_read(load):
    limit = constants.AUDIO_LOOP_STARTS_MAX
    assert limit == 1000
    body = "".join(f'"bgm/t{i}.ogg" = {i}\n' for i in range(limit + 1))
    result = load("[audio.loop_start]\n" + body)
    assert messages(result) == [
        f"config.toml, line 1: [audio] loop_start must have at most {limit} entries, "
        f"but found {limit + 1}"]
    assert dict(result.config.audio.loop_start) == {}
    exactly = load("[audio.loop_start]\n" + "".join(
        f'"bgm/t{i}.ogg" = {i}\n' for i in range(limit)))
    assert exactly.errors == [] and len(exactly.config.audio.loop_start) == limit


# --- Warnings (SR-F08-22, AC-F01-17 form) -------------------------------------------------

UNKNOWN_KEY_ROWS = [
    ("[audio]\nmusik_volume = 50",
     LINE2 + 'unknown key [audio] musik_volume — did you mean "music_volume"?'),
    ("[audio]\nmusic_fade_in = 1.0",
     LINE2 + 'unknown key [audio] music_fade_in — did you mean "music_fadein"?'),
    ("[audio]\ncrossfade = 1.0", LINE2 + "unknown key [audio] crossfade"),
    ("[audio]\nloopstart = 1.0",
     LINE2 + 'unknown key [audio] loopstart — did you mean "loop_start"?'),
    ("[audo]\nmusic_volume = 50",
     "config.toml, line 1: unknown section [audo] — did you mean [audio]?"),
]


def test_unknown_keys_warn_and_the_game_starts(load):
    for text, warning in UNKNOWN_KEY_ROWS:
        result = load(text + "\n")
        assert result.errors == [] and result.loaded is True, text
        assert result.warnings == [warning], text
        assert result.config == Config(), text


# --- The validators and the label formatter ----------------------------------------------

def test_seconds_accepts_and_stores_floats():
    for value, stored in ((0, 0.0), (60, 60.0), (60.0, 60.0), (0.5, 0.5), (-0.0, 0.0),
                          (59.999, 59.999)):
        result = Seconds(0, 60).check(value)
        assert result == stored and type(result) is float, value


def test_seconds_refuses():
    for value in (True, False, -1, 61, 60.0001, -0.01, float("nan"), float("inf"),
                  float("-inf"), 10 ** 400, -(10 ** 400), "1.5", "1", None, [1.0], {"a": 1}):
        with pytest.raises(ValueProblem):
            Seconds(0, 60).check(value)
            print("accepted", repr(value))                # names the row that didn't raise


def test_seconds_phrase_and_range():
    assert Seconds(0, 60).expected == "seconds from 0 to 60"
    assert Seconds(0, 3600).expected == "seconds from 0 to 3600"
    assert Seconds(0, 3600).check(3600) == 3600.0
    assert constants.AUDIO_FADE_RANGE == (0, 60)
    assert constants.AUDIO_LOOP_START_RANGE == (0, 3600)
    assert constants.AUDIO_VOLUME_RANGE == (0, 100)


def test_audio_file_key_accepts_and_stores_as_written():
    for value in ("bgm/festival.ogg", "a.ogg", "x.OGG", "bgm/sub/t.opus", "bgm/a b/c.flac",
                  "v/h.mp3", "s.wav", "s.m4a", "s.mid", "bgm/a.b.ogg", "audiobgm/a.ogg",
                  "bgm/audio/a.ogg", "Ünï/köri.ogg"):
        assert AudioFileKey().check(value) == value


REFUSED_KEYS = [
    "audio/bgm/a.ogg", "Audio/a.ogg", "AUDIO/a.ogg", "aUdIo/x/y.ogg", "audio/",
    "bgm/festival", "festival", "bgm.d/festival", "bgm/.ogg", ".ogg", "bgm/",
    "bgm\\festival.ogg", "../a.ogg", "bgm/../a.ogg", "/a.ogg", "C:/a.ogg", "c:a.ogg",
    "bgm//a.ogg", "./a.ogg", "bgm/aux.ogg", "nul.ogg", "a.ogg ", "a.ogg.",
    "a\x00.ogg", "a\nb.ogg", "", "f" * 1100 + ".ogg", 5, None, b"a.ogg",
]


def test_audio_file_key_refuses():
    for value in REFUSED_KEYS:
        with pytest.raises(ValueProblem):
            AudioFileKey().check(value)
            print("accepted", repr(value))                # names the row that didn't raise


def test_audio_file_key_phrase():
    assert AudioFileKey.expected == 'a file inside audio/ with its extension, e.g. "bgm/festival.ogg"'


def test_loop_start_is_an_entry_map_with_the_quoted_label():
    field, = (f for f in dataclasses.fields(AudioConfig) if f.name == "loop_start")
    validator = field.metadata["validator"]
    assert isinstance(validator, EntryMap)
    assert validator.label is quoted_key
    assert isinstance(validator.key_check, AudioFileKey)
    assert isinstance(validator.value_validator, Seconds)
    assert validator.value_validator.expected == "seconds from 0 to 3600"
    assert validator.max_entries == 1000
    assert validator.base == MappingProxyType({})


def test_quoted_key_always_quotes():
    for key, label in [
    ("bgm/festival.ogg", '"bgm/festival.ogg"'),
    ("festival", '"festival"'),                       # quoted even when it could be bare
    ("a\tb", '"a\\tb"'),
    ("x" * 100, '"' + "x" * 39 + '…"'),
    ]:
        assert quoted_key(key) == label, key
    assert toml_key("festival") == "festival"         # the default formatter is unchanged


# --- The quotes hint for decimal numbers (F01 §7.2.3 step 6, extended for Seconds and Opacity)

def test_quoted_decimal_seconds_gets_the_quotes_hint(load):
    result = load('[audio]\nmusic_fadeout = "1.5"\n')
    assert messages(result) == [
        LINE2 + FADE.format("music_fadeout") + 'the text "1.5". Remove the quotes.']


def test_quoted_decimal_opacity_gets_the_quotes_hint(load):
    result = load('[theme.textbox]\nfill_opacity = "0.85"\n')
    assert messages(result) == [
        LINE2 + "[theme.textbox] fill_opacity must be a number from 0.0 to 1.0, such as 0.85 "
        'for 85%, but found the text "0.85". Remove the quotes.']
    assert Opacity().check(0.85) == 0.85


QUOTES_HINT_ROWS = [
    ('"0.5"', True), ('"+0.5"', True), ('"5e0"', True), ('"1.5E1"', True), ('"60.0"', True),
    ('"60.5"', False),                               # out of range unquoted, so no hint
    ('".5"', False), ('"5."', False), ('"1.5.2"', False), ('"1,5"', False),
    ('"nan"', False), ('"inf"', False), ('"1e400"', False), ('" 1.5"', False),
    ('"1_0.5"', False), ('"١.٥"', False), ('"0.' + "5" * 19 + '"', False),   # 21 characters
]


def test_decimal_quotes_hint_only_when_the_unquoted_number_is_valid(load):
    for text, hint in QUOTES_HINT_ROWS:
        result = load(f"[audio]\nmusic_fadein = {text}\n")
        text_message, = messages(result)
        assert text_message.endswith(". Remove the quotes.") is hint, text

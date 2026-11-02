"""The audio statements at load (F08 step 1; ``04-technical.md`` §6.1, §6.2): the nodes they
build, their identities, and the path-check order. ACs: AC-F08-01, 02, 03 (the message rows
themselves are the ``feature = "F08"`` rows of ``messages/cases.toml``, run by
``test_messages.py``).
"""

import pytest

from engine.core.config_schema import is_audio_ref
from engine.script import load_story
from engine.script.audio import (
    PLAYABLE_EXTS,
    PlayAudio,
    QueueMusic,
    StopAudio,
    Voice,
    file_problem,
    suffix,
)
from engine.script.identity import statement_hash
from engine.script.nodes import Say
from engine.script.statements import get_spec
from tests.script.helpers import message_at, parse_text, template_a

PLAY = {"loop": True, "volume": 100, "fadein": None, "fadeout": None, "restart": False,
        "start": None}


def only_node(row: str):
    """The node line 4 of template A gives, with S = ``row`` (no error)."""
    parsed = parse_text(template_a(S=row))
    assert parsed.messages == []
    block = parsed.labels["start"].block
    assert block[1].line == 4
    return block[1]


def fields(node, *names: str) -> dict:
    return {name: getattr(node, name) for name in names}


# --- AC-F08-01 -------------------------------------------------------------------------------

@pytest.mark.parametrize("row,kind,expected", [
    ('play music "bgm/festival.ogg"', PlayAudio,
     {"channel": "music", "audio_file": "bgm/festival.ogg", **PLAY}),
    ('play music "bgm/festival.ogg" volume 0 once fadeout 60 fadein 0 restart', PlayAudio,
     {**PLAY, "loop": False, "volume": 0, "fadein": 0.0, "fadeout": 60.0, "restart": True}),
    ('play music "bgm/festival.ogg" from 12.5', PlayAudio, {**PLAY, "start": 12.5}),
    ('play music "bgm/festival.ogg" from current', PlayAudio, {**PLAY, "start": "current"}),
    ('play music "bgm/festival.ogg" from 3600', PlayAudio, {**PLAY, "start": 3600.0}),
    ('play sound "sfx/rain.ogg" loop volume 100 fadein 3.0', PlayAudio,
     {"channel": "sound", "audio_file": "sfx/rain.ogg", **PLAY, "fadein": 3.0}),
    ('play sound "sfx/door.ogg"  # knock', PlayAudio,
     {"channel": "sound", **PLAY, "loop": False}),
    ('play music "bgm/Theme.OGG"', PlayAudio, {"audio_file": "bgm/Theme.OGG"}),
    ('play music "bgm/祭り🎆.ogg"', PlayAudio, {"audio_file": "bgm/祭り🎆.ogg"}),
    ('play sound "sfx/مطر.ogg"', PlayAudio, {"audio_file": "sfx/مطر.ogg"}),
    ('queue music "bgm/omen.ogg" once fadein 1.0 volume 50', QueueMusic,
     {"audio_file": "bgm/omen.ogg", "loop": False, "volume": 50, "fadein": 1.0}),
    ('queue music "bgm/omen.ogg"', QueueMusic,
     {"audio_file": "bgm/omen.ogg", "loop": True, "volume": 100, "fadein": None}),
    ("stop music", StopAudio, {"channel": "music", "audio_file": None, "fadeout": None}),
    ("stop sound fadeout 1.5", StopAudio, {"channel": "sound", "audio_file": None,
                                           "fadeout": 1.5}),
    ('stop sound "sfx/crowd.ogg"', StopAudio, {"channel": "sound",
                                               "audio_file": "sfx/crowd.ogg", "fadeout": None}),
    ("stop voice fadeout 0", StopAudio, {"channel": "voice", "audio_file": None,
                                         "fadeout": 0.0}),
    ('voice "voice/hana_014.ogg"', Voice, {"audio_file": "voice/hana_014.ogg"}),
])
def test_ac01_nodes(row, kind, expected):
    node = only_node(row)
    assert type(node) is kind
    assert fields(node, *expected) == expected
    assert (node.file.ref, node.line, node.column) == ("script/main.vns", 4, 5)


def test_ac01_options_in_any_order():
    first = only_node('play music "bgm/a.ogg" fadein 1.0 volume 40 once from 2')
    second = only_node('play music "bgm/a.ogg" from 2 once volume 40 fadein 1.0')
    assert fields(first, *PLAY) == fields(second, *PLAY) == {
        **PLAY, "loop": False, "volume": 40, "fadein": 1.0, "start": 2.0}


def test_ac01_minus_zero_is_zero():
    node = only_node('play music "bgm/a.ogg" fadein -0 volume 007')
    assert str(node.fadein) == "0.0" and node.volume == 7


def test_ac01_music_is_still_a_name():
    parsed = parse_text(template_a(S='music "La."', T='define music = Character("Music")'))
    assert parsed.messages == []
    say = parsed.labels["start"].block[1]
    assert isinstance(say, Say) and say.speaker == "music"


@pytest.mark.parametrize("row,key", [
    ('play music "bgm/festival.ogg"', ("play", "music", "bgm/festival.ogg")),
    ('play music "bgm/festival.ogg" volume 0 once fadeout 60 fadein 0 restart',
     ("play", "music", "bgm/festival.ogg")),
    ('play music "bgm/festival.ogg" from 12.5', ("play", "music", "bgm/festival.ogg")),
    ('play sound "sfx/rain.ogg" loop', ("play", "sound", "sfx/rain.ogg")),
    ('queue music "bgm/omen.ogg" once', ("queue", "bgm/omen.ogg")),
    ("stop sound fadeout 1.0", ("stop", "sound", "")),
    ('stop sound "sfx/crowd.ogg"', ("stop", "sound", "sfx/crowd.ogg")),
    ('voice "voice/hana_014.ogg"', ("voice", "voice/hana_014.ogg")),
])
def test_ac01_identity_keys(row, key):
    assert only_node(row).identity_key() == key


def _sids(paths) -> dict[int, str]:
    result = load_story(paths)
    assert result.program is not None, [e.format() for e in result.errors]
    return {stmt.line: stmt.sid for stmt in result.program.iter_statements()}


def test_ac01_sids_ignore_fades_volume_and_loop_and_the_voice(game):
    plain = _sids(game({"main.vns": template_a(S='play music "bgm/festival.ogg"')}))
    styled = _sids(game({"main.vns": template_a(
        S='play music "bgm/festival.ogg" volume 0 once fadeout 60 fadein 0 restart')}))
    other = _sids(game({"main.vns": template_a(S='play music "bgm/omen.ogg"')}))
    assert plain[4] == styled[4] != other[4]
    assert plain[4] == "start/" + statement_hash(("play", "music", "bgm/festival.ogg"))
    without = _sids(game({"main.vns": template_a(S='hana "Hi."')}))
    voiced = _sids(game({"main.vns": template_a(S='voice "voice/hana_014.ogg"⏎hana "Hi."')}))
    assert without[4] == voiced[5]                  # Say.voice isn't part of the identity


# --- AC-F08-02 -------------------------------------------------------------------------------

def test_ac02_two_bad_lines_give_two_errors_in_line_order():
    parsed = parse_text(template_a(S='play music "bgm/a.ogg" softly⏎stop music "x.ogg"'))
    assert [(e.code, e.line) for e in parsed.errors] == [("E146", 4), ("E148", 5)]


@pytest.mark.parametrize("row", [
    'play music "bgm/omen.ogg" crossfade', 'play music "bgm/omen.ogg" crossfade 1.0',
    'play music "bgm/omen.ogg" fadein 1.0 crossfade 2',
])
def test_ac02_crossfade_is_never_e146(row):
    assert parse_text(template_a(S=row)).codes == ["E148"]


@pytest.mark.parametrize("row,code", [
    ('play music "bgm/omen.ogg', "E54"),                       # the reader's error comes first
    ('play music "bgm/\\q.ogg"', "E52"),
    ('play music "bgm/omen.ogg" fadein 1.0 # a comment: with x', None),
    ('play music "bgm/omen.ogg" with', "E146"),
    ('play music "bgm/omen.ogg" fadein with', "E149"),
    ('play music "bgm/omen.ogg" fadein loop', "E149"),
    ('play music "bgm/omen.ogg" fadein slow', "E150"),
    ('play music "bgm/omen.ogg" from 12s', "E150"),
    ('play music "bgm/omen.ogg" from -1', "E150"),
    ('play music "bgm/omen.ogg" volume loud', "E151"),
    ('play music "bgm/omen.ogg" volume -5', "E151"),
    ('play music "bgm/omen.ogg" volume ' + "9" * 5000, "E151"),     # no int() of 5,000 digits
    ('play music "bgm/omen.ogg" fadein ' + "9" * 5000, "E150"),
    ('play music "bgm/omen.ogg" Loop', "E146"),
    ('play music ""', "E142"),
    ("play Music \"bgm/omen.ogg\"", "E140"),
    ("play fadein 1.0", "E140"),
    ("queue music fadein 1.0", "E142"),
    ('stop sound 5', "E146"),
    ('stop sound "sfx/a.ogg" volume 5', "E148"),
    ('voice "voice/a.ogg" "voice/b.ogg"', "E148"),
    ('voice "voice/a.ogg":', "E146"),
    ('voice voice/a.ogg', "E142"),
])
def test_ac02_other_inputs_give_one_error(row, code):
    parsed = parse_text(template_a(S=row))
    assert parsed.codes == ([] if code is None else [code]), parsed.messages


@pytest.mark.parametrize("row,message", [
    ('play music "bgm/omen.ogg" fadein slow',
     'fadein takes seconds from 0 to 60, e.g. fadein 2.0, but this has "slow".'),
    ('play music "bgm/omen.ogg" from 12s',
     'from takes seconds, e.g. from 90, but this has "12s". Numbers have no units.'),
    ('play music "bgm/omen.ogg" volume loud',
     'volume takes a whole number from 0 to 100 (a percentage), e.g. volume 50 for half, but '
     'this has "loud".'),
    ("play Music \"bgm/omen.ogg\"",
     '"Music" isn\'t a channel. Did you mean "music"? play takes music or sound.'),
    ('stop musc', '"musc" isn\'t a channel. Did you mean "music"? stop takes music, sound, or '
                  'voice.'),
    ('queue musik "bgm/a.ogg"', '"musik" isn\'t a channel. Did you mean "music"? queue takes '
                                'only music.'),
    ('play music "bgm/omen.ogg" Loop', 'play has no option "Loop". Options are lower case: loop.'),
    ('stop sound "sfx/a.ogg" with fade',
     "stop doesn't take with; transitions are for pictures. To fade, use fadeout 1.0."),
    ('play voice', 'voice lines aren\'t started with play. Put voice "voice/hana_014.ogg" on the '
                   'line above the line it voices.'),
])
def test_ac02_drafted_forms(row, message):
    parsed = parse_text(template_a(S=row))
    assert [message_at(e) for e in parsed.errors] == [("4", message)]


# --- AC-F08-03 -------------------------------------------------------------------------------

@pytest.mark.parametrize("file,code", [
    ("bgm/festival", "E145"), ("audio/bgm", "E145"), (".ogg", "E145"), ("bgm.d/x", "E145"),
    ("audio/bgm/festival.ogg", "E144"), ("AUDIO/bgm/festival.ogg", "E144"),
    ("Audio/x.ogg", "E144"), ("../x.ogg", "E143"), ("C:/x.ogg", "E143"), ("/x.ogg", "E143"),
    ("bgm//x.ogg", "E143"), ("bgm/con.ogg", "E143"), ("bgm/x.ogg.", "E143"),
    ("bgm/a\x01.ogg", "E143"),          # a script line can't hold it (E03 first); the rule can
    ("a" * 200 + "/" + "b" * 200 + "/" + "c" * 200 + "/" + "d" * 200 + "/" + "e" * 213 + ".ogg",
     "E143"),
    ("bgm/festival.ogg", None), ("bgm/Theme.OGG", None), ("audiox/a.ogg", None),
    ("bgm/theme.m4a", None), ("a" * 200 + "/" + "b" * 200 + "/" + "c" * 200 + "/" + "d" * 200
                              + "/" + "e" * 210 + ".ogg", None),
])
def test_ac03_file_problem_order_agrees_with_the_config_check(file, code):
    problem = file_problem(file)
    assert (problem[0] if problem else None) == code
    assert is_audio_ref(file) is (code is None)


def test_ac03_lengths():
    longest = "abcdefghi/" * 101 + "abcd.ogg"                     # 1,018: ref 1,024
    assert len(longest) == 1018 and file_problem(longest) is None
    assert file_problem(longest[:-4] + "e.ogg")[0] == "E143"      # 1,019: ref 1,025


def test_ac03_no_file_is_opened_or_listed_while_reading(game, opened):
    rows = ('play music "bgm/festival.ogg"⏎play sound "../x.ogg"', 'voice "voice/a.ogg"⏎"Hi."',
            'queue music "bgm/missing.ogg"⏎stop sound "sfx/crowd.ogg"')
    for row in rows:
        paths = game({"main.vns": template_a(S=row)})
        with opened() as events:
            load_story(paths)
        assert not [e for e in events if "audio" in e[1].replace("\\", "/").split("/")]


def test_suffix_and_playable_formats():
    assert PLAYABLE_EXTS == {".ogg", ".opus", ".flac", ".mp3", ".wav"}
    assert suffix("bgm/Theme.OGG") == ".ogg" and suffix("a.b/c") == "" and suffix(".ogg") == ""


def test_statements_are_registered_for_the_story():
    for word in ("play", "queue", "stop", "voice"):
        spec = get_spec(word)
        assert spec is not None and spec.placement == "story" and not spec.takes_block

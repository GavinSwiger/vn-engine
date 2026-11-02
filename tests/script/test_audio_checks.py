"""The audio load checks (F08 step 1; ``04-technical.md`` §6.2, ``audio_checks.py``): a voice
attaches to the line below it (W20), formats the engine can't play (W23), and looping MP3s
(W24). ACs: AC-F08-04, 05 (load half; the run half, no ``PlayVoice`` and silent playback, comes
with F08 steps 3 and 4). The message rows are in ``messages/cases.toml``.
"""

import pytest

from engine.script import load_story
from engine.script.audio import PlayAudio, QueueMusic, StopAudio, Voice
from engine.script.audio_checks import VOICE_TRANSPARENT, attach_voices, iter_attach_voices
from engine.script.codex import CodexLock
from engine.script.effects import Flash, Pause, Shake
from engine.script.fourthwall import CrashEffect, TitleEffect
from engine.script.glitch import Effect
from engine.script.limits import IDENTITY_YIELD_ITEMS, SCRIPT_AUDIO_WARN_LIMIT
from engine.script.messages import format_message
from engine.script.nodes import PythonLine, Say
from engine.script.nvl import Nvl
from engine.script.points import PointsChange
from engine.script.rollback import Rollback
from engine.script.routes import Ending, Lock
from engine.script.stage import Hide, Scene, Show
from tests.script.helpers import parse_text, template_a

W20_NONE = format_message("W20", ("none",))
W20_VOICE = format_message("W20", ("voice",))
W20_IF = format_message("W20", ("if",))


def load(game, S: str, T: str | None = None):
    result = load_story(game({"main.vns": template_a(S=S, T=T)}))
    assert result.program is not None, [e.format() for e in result.errors]
    return result


def voices(result) -> dict[int, str | None]:
    """Each line's voice, by line number."""
    return {stmt.line: stmt.voice for stmt in result.program.iter_statements()
            if isinstance(stmt, Say)}


def warned(result) -> list[tuple[str, int | None, str]]:
    return [(w.code, w.line, w.message) for w in result.warnings]


# --- AC-F08-04 -------------------------------------------------------------------------------

@pytest.mark.parametrize("row,expected", [
    ('voice "voice/hana_014.ogg"⏎hana "Hi."', {3: None, 5: "voice/hana_014.ogg", 6: None}),
    ('voice "voice/hana_014.ogg"⏎# note⏎$ a = 1⏎play sound "sfx/door.ogg"⏎'
     'queue music "bgm/omen.ogg"⏎stop voice⏎"Hi."', {3: None, 10: "voice/hana_014.ogg",
                                                     11: None}),
    ('voice "voice/hana_014.ogg"', {3: None, 5: "voice/hana_014.ogg"}),
    ('voice "voice/a.ogg"⏎scene bg river⏎show hana happy⏎hide hana⏎"Hi."',
     {3: None, 8: "voice/a.ogg", 9: None}),
])
def test_ac04_a_voice_attaches_to_the_line_below(game, row, expected):
    result = load(game, row)
    assert voices(result) == expected
    assert result.warnings == ()


@pytest.mark.parametrize("row,line,message,expected", [
    ('voice "voice/hana_014.ogg"⏎voice "voice/hana_015.ogg"⏎hana "Hi."', 4, W20_VOICE,
     {3: None, 6: "voice/hana_015.ogg", 7: None}),
    ('voice "voice/hana_014.ogg"⏎if True:⏎[8]hana "Hi."', 4, W20_IF,
     {3: None, 6: None, 7: None}),
    ('voice "voice/hana_014.ogg"⏎jump start', 4, W20_NONE, {3: None, 6: None}),
    ('voice "voice/hana_014.ogg"⏎call start', 4, W20_NONE, {3: None, 6: None}),
    ('voice "voice/hana_014.ogg"⏎return', 4, W20_NONE, {3: None, 6: None}),
    ('if True:⏎[8]voice "voice/hana_014.ogg"', 5, W20_NONE, {3: None, 6: None}),
])
def test_ac04_w20(game, row, line, message, expected):
    result = load(game, row)
    assert warned(result) == [("W20", line, message)]
    assert result.warnings[0].file == "script/main.vns"
    assert voices(result) == expected


def test_ac04_a_voice_never_reaches_into_or_out_of_a_block(game):
    result = load(game, 'if True:⏎[8]voice "voice/a.ogg"⏎[8]"In."⏎else:⏎'
                        '[8]voice "voice/b.ogg"')
    assert voices(result) == {3: None, 6: "voice/a.ogg", 9: None}
    assert warned(result) == [("W20", 8, W20_NONE)]


def test_ac04_voice_transparent_statements():
    assert VOICE_TRANSPARENT == {PythonLine, PlayAudio, QueueMusic, StopAudio, Scene, Show, Hide,
                                 Shake, Flash, Pause,            # F09 C10
                                 PointsChange,                   # F22 I-3
                                 Rollback,                       # F14 04 §2
                                 Nvl,                            # F17 04 §3
                                 Lock,                           # F19 04 §2 Q3
                                 CodexLock,                      # F21 04 §3
                                 Effect,                         # F28 SR-F28-04
                                 TitleEffect, CrashEffect}       # F30 04 §5.3
    assert Voice not in VOICE_TRANSPARENT and Say not in VOICE_TRANSPARENT
    assert Ending not in VOICE_TRANSPARENT


def test_ac04_menu_form_by_node_name():
    """F07's ``Menu`` node gets W20's menu form without a change here (07 G9)."""
    class Menu(PythonLine):
        pass

    from engine.script.audio_checks import _w20_form
    menu = Menu.__new__(Menu)
    assert _w20_form(menu) == "menu"
    # 02 §5.1 ("menu the same" as the if form) and AC-F07-01 (amended by F07, 07 I-10).
    assert format_message("W20", ("menu",)) == (
        "voice goes directly above a line, not above a menu. Put a voice inside each branch.")


def test_ac04_w20_menu_row(game):
    """AC-F08-04's W20 ``menu`` row (added by F07, its 07 I-10): a voice above ``menu:``."""
    result = load(game, 'voice "voice/hana_014.ogg"⏎menu:⏎[8]"Go":⏎[12]$ pass')
    assert warned(result) == [("W20", 4, format_message("W20", ("menu",)))]


def test_ac04_warnings_in_reading_order_capped_with_one_summary(game):
    rows = ["if True:⏎[8]voice \"voice/x.ogg\""]
    rows += ['voice "voice/a.ogg"⏎jump start' if i % 2 else 'play sound "sfx/a.wma"'
             for i in range(SCRIPT_AUDIO_WARN_LIMIT + 4)]
    result = load(game, "⏎".join(rows))
    records = [w for w in result.warnings if w.code in ("W20", "W23")]
    assert len(records) == SCRIPT_AUDIO_WARN_LIMIT
    lines = [w.line for w in records]
    assert lines == sorted(lines) and lines[0] == 5
    assert result.warnings[-1].code == "W20s"
    total = 1 + (SCRIPT_AUDIO_WARN_LIMIT + 4)
    assert result.warnings[-1].message == (
        f"…and {total - SCRIPT_AUDIO_WARN_LIMIT} more warnings about voices and audio files.")


def test_ac04_the_walk_yields_and_attaches_the_same_however_sliced():
    lines = ["label start:"] + ['    voice "voice/a.ogg"\n    "Hi."'] * (IDENTITY_YIELD_ITEMS + 5)
    parsed = parse_text("\n".join(lines) + "\n")
    job = iter_attach_voices(parsed.nodes)
    steps = 0
    while True:
        try:
            next(job)
            steps += 1
        except StopIteration as stop:
            assert stop.value == []
            break
    assert steps >= 2
    says = [s for s in parsed.labels["start"].block if isinstance(s, Say)]
    assert {s.voice for s in says} == {"voice/a.ogg"}
    assert attach_voices(parsed.nodes) == []


# --- AC-F08-05 -------------------------------------------------------------------------------

@pytest.mark.parametrize("row,args", [
    ('play music "bgm/theme.m4a"', ("bgm/theme.m4a", ".m4a")),
    ('play music "bgm/theme.aac"', ("bgm/theme.aac", ".aac")),
    ('play music "bgm/theme.WMA"', ("bgm/theme.WMA", ".wma")),
    ('play music "bgm/theme.mid"', ("bgm/theme.mid", ".mid")),
    ('play sound "sfx/door.aiff"', ("sfx/door.aiff", ".aiff")),
    ('queue music "bgm/a.xm"', ("bgm/a.xm", ".xm")),
    ('stop sound "sfx/door.aiff"', ("sfx/door.aiff", ".aiff")),
    ('voice "voice/a.m4a"⏎"Hi."', ("voice/a.m4a", ".m4a")),
])
def test_ac05_w23_keeps_the_statement(game, row, args):
    result = load(game, row)
    assert warned(result) == [("W23", 4, format_message("W23", args))]
    stmt = result.program.at("start", (1,))
    assert stmt.audio_file == args[0]                    # kept; it plays as silence


@pytest.mark.parametrize("ext", [".ogg", ".OGG", ".opus", ".flac", ".mp3", ".wav", ".Wav"])
def test_ac05_playable_formats_give_no_w23(game, ext):
    assert load(game, f'play sound "sfx/door{ext}"').warnings == ()


@pytest.mark.parametrize("row,message", [
    ('play music "bgm/festival.mp3"⏎queue music "bgm/omen.mp3"⏎play sound "sfx/rain.mp3" loop',
     "3 music files loop but are MP3: bgm/festival.mp3, bgm/omen.mp3, and 1 more. MP3 adds a "
     "short silence each time a track loops; convert them to .ogg for seamless loops."),
    ('play music "bgm/b.MP3"⏎play music "bgm/a.mp3"⏎play music "bgm/b.MP3"',
     "2 music files loop but are MP3: bgm/b.MP3 and bgm/a.mp3. MP3 adds a short silence each "
     "time a track loops; convert them to .ogg for seamless loops."),
    ('queue music "bgm/omen.mp3"',
     "1 music file loops but is MP3: bgm/omen.mp3. MP3 adds a short silence each time a track "
     "loops; convert it to .ogg for a seamless loop."),
    ('if True:⏎[8]play music "bgm/z.mp3"⏎play music "bgm/y.mp3"⏎play music "bgm/x.mp3"⏎'
     'play music "bgm/w.mp3"',
     "4 music files loop but are MP3: bgm/z.mp3, bgm/y.mp3, and 2 more. MP3 adds a short "
     "silence each time a track loops; convert them to .ogg for seamless loops."),
])
def test_ac05_w24_one_summary_in_order_of_first_use(game, row, message):
    result = load(game, row)
    assert warned(result) == [("W24", None, message)]
    assert result.warnings[0].file is None


@pytest.mark.parametrize("row", [
    'play music "bgm/festival.mp3" once⏎play sound "sfx/door.mp3"',
    'queue music "bgm/omen.mp3" once', 'stop sound "sfx/rain.mp3"', 'voice "v/a.mp3"⏎"Hi."',
])
def test_ac05_no_w24(game, row):
    assert load(game, row).warnings == ()

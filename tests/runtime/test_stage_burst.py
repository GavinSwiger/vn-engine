"""F04 step 4 — the stage in bursts, headless (F04 ``06-acceptance.md`` §1.2, §1.4, §1.5):
AC-F04-07 (``scene``, the empty stage, new game), 09 (``hide``), 10 (``as``), 11 (dialogue
words and ``speaker_tag``), 16 (one ``ShowStage`` per burst), 20 (restore shows the saved
stage), 22 (saves from before F04); the run-time half of PR-F04-12 (the dev INFO line; the
App half of AC-F04-12 is step 5); 07 I-2 (prefetch record); E135 (AC-F04-39's rows).

Every run is §0.2's run H (``stage_story.run_h``); stages are in §0.5's notation. These
tests are about the stage, so F08's audio commands (a new game's and a restore's
``AudioRestore``) are left out of what they compare (``no_audio``).
"""

import json
import logging
from pathlib import Path

import pytest

from engine.runtime import interpreter as interp_mod
from engine.runtime import stage as stage_mod
from engine.runtime.commands import (Advance, NvlPage, PrefetchImages, Say, ShowStage,
                                     StoryEnded, StoryFailed)
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.stage import EMPTY_STAGE
from engine.runtime.state import GameState
from engine.script.diagnostics import ScriptErrorGroup
from engine.script.stage import Hide, Scene, Show
from tests.runtime.stage_story import (F04, IMG, IMG_L, bursts, lanterns, launched, no_audio,
                                       stage, stages, story_game, template_game)
from tests.runtime.stage_story import run_h as _run_h
from tests.runtime.story import advance, load_files, sr_f03_28
from tests.script import message_cases


def take_all(interp) -> list:
    return no_audio(interp.take_commands(1 << 30))


def run_h(program, images=IMG, **kwargs) -> list:
    return no_audio(_run_h(program, images, **kwargs))


def play(interp) -> list:
    """Advance to the end, returning every command released on the way."""
    out = []
    while interp.status is Status.WAITING:
        advance(interp)
        out += take_all(interp)
    return out


def assert_burst_rule(commands) -> None:
    """AC-F04-16: at most one ``ShowStage`` per burst, followed in the same burst by a
    checkpoint command (a ``Say`` here), never by anything else first."""
    for burst in bursts(commands):
        kinds = [type(c) for c in burst]
        assert kinds.count(ShowStage) <= 1, kinds
        if ShowStage in kinds:
            assert kinds[kinds.index(ShowStage) + 1] is Say, kinds


# --- AC-F04-07 — scene and the empty stage ---------------------------------------------------

AC07 = {
    "first-line": (['"A."'], ["∅ |"]),
    "scene-clears": (["show hana happy", '"A."', "scene bg bridge", '"B."'],
                     ["∅ | hana happy@center", "bg bridge |"]),
    "scene-alone": (["scene bg bridge", "show hana happy", '"A."', "scene", '"B."'],
                    ["bg bridge | hana happy@center", "∅ |"]),
    "last-scene-wins": (["scene bg bridge", "scene bg river_night", '"A."'],
                        ["bg river_night |"]),
}


@pytest.mark.parametrize("lines, expected", AC07.values(), ids=AC07.keys())
def test_ac_f04_07_scene_and_the_empty_stage(tmp_path, lines, expected):
    cmds = run_h(story_game(tmp_path, lines))
    assert stages(cmds) == [stage(t) for t in expected]
    assert type(bursts(cmds)[0][0]) is ShowStage          # the first burst always has one
    assert_burst_rule(cmds)


def test_ac_f04_07_a_new_game_never_keeps_the_previous_stage(tmp_path):
    interp = launched(lanterns(tmp_path / "g"))
    interp.new_game(42)
    interp.run(10_000)
    for _ in range(7):                                    # to line 8 (bg dusk)
        advance(interp)
    assert interp.stage.background == "bg dusk"
    take_all(interp)
    interp.new_game(42)
    interp.run(10_000)
    first = take_all(interp)
    assert first[0] == ShowStage(stage("bg river_night | stall@stall_spot, hana happy@center"))
    assert [type(c) for c in first if type(c) is not PrefetchImages] == [ShowStage, Say]


# --- AC-F04-09 — hide -------------------------------------------------------------------------

def test_ac_f04_09_hide_a_tag_not_on_stage(tmp_path, caplog):
    with caplog.at_level(logging.DEBUG, logger="vn"):
        cmds = run_h(template_game(tmp_path, S="hide daichi"), dev=True)
    assert stages(cmds) == [stage("bg river_night | hana happy@center")]
    assert [r for r in caplog.records if r.levelno >= logging.INFO
            and r.name in ("vn.stage", "vn.runtime") and not sr_f03_28(r)] == []
    assert type(cmds[-1]) is StoryEnded


def test_ac_f04_09_hide_removes(tmp_path):
    cmds = run_h(template_game(tmp_path, S="hide hana"))
    assert stages(cmds) == [stage("bg river_night |")]


def test_ac_f04_09_hidden_and_shown_again_comes_to_the_front(tmp_path):
    cmds = run_h(story_game(tmp_path, ["show hana happy", "show stall", "hide hana",
                                       "show hana sad", '"A."']))
    assert stages(cmds) == [stage("∅ | stall@center, hana sad@center")]


# --- AC-F04-10 — as ---------------------------------------------------------------------------

def test_ac_f04_10_as(tmp_path):
    cmds = run_h(story_game(tmp_path, [
        "show student neutral as student_b at right", "show student neutral at left", '"A."',
        "show student as student_b at 1000", '"B."',
        "show student angry as student_b", '"C."']))
    assert stages(cmds) == [
        stage("∅ | student_b=student neutral@right, student neutral@left"),
        stage("∅ | student_b=student neutral@(1000), student neutral@left"),
        stage("∅ | student_b=student angry@(1000), student neutral@left")]
    assert type(stages(cmds)[1].sprites[0].at[0]) is int


# --- AC-F04-11 — expressions on dialogue lines ------------------------------------------------

KAITO = 'define kaito = Character("Kaito")'
# Each row's lines follow a narration line ("Before.") so the tested line isn't the game's
# first line, whose burst always carries the stage (AC-F04-07).
AC11 = {
    "words": ('hana pout "Hi."', "bg river_night | hana pout@center", "hana"),
    "no-words": ('hana "Hi."', None, "hana"),
    "narration": ('"Hi."', None, None),
    "image-tag": ('show daichi grin at right⏎[4]d sigh "Hi."',
                  "bg river_night | hana happy@center, daichi sigh@right", "daichi"),
    "off-stage": ('hide hana⏎[4]hana pout "Hi."', "bg river_night |", "hana"),
    "as-sprite": ('show student neutral as kaito⏎[4]kaito angry "Hi."',
                  "bg river_night | hana happy@center, kaito=student angry@center", "kaito"),
}


@pytest.mark.parametrize("lines, shown, tag", AC11.values(), ids=AC11.keys())
def test_ac_f04_11_expressions_on_dialogue_lines(tmp_path, lines, shown, tag):
    cmds = run_h(template_game(tmp_path, S='"Before."⏎[4]' + lines, T=KAITO))
    (hi,) = [b for b in bursts(cmds) if any(type(c) is Say and c.text == "Hi." for c in b)]
    say = next(c for c in hi if type(c) is Say)
    assert say.speaker_tag == tag
    shows = [c for c in hi if type(c) is ShowStage]
    if shown is None:
        assert shows == []
    else:
        assert shows == [ShowStage(stage(shown))]
        assert hi.index(shows[0]) < hi.index(say)              # TR-F04-01
        (end,) = [b for b in bursts(cmds) if any(type(c) is Say and c.text == "End." for c in b)]
        assert not any(type(c) is ShowStage for c in end)      # the change stays
    assert_burst_rule(cmds)


def test_ac_f04_11_the_change_stays_until_end(tmp_path):
    program = template_game(tmp_path, S='hana surprised "Hi."')
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    take_all(interp)
    advance(interp)
    assert interp.current.text == "End."
    assert interp.checkpoint().stage == stage("bg river_night | hana surprised@center")
    assert not any(type(c) is ShowStage for c in take_all(interp))


def test_i_3_speaker_tag_on_every_character_line(tmp_path):
    """07 I-3: ``image_tag`` or the define name on every character line, with or without
    words, on stage or not; None for narration. The restore presenter agrees."""
    program = template_game(tmp_path, S='d "One."⏎[4]d grin "Two."⏎[4]hana "Three."')
    cmds = run_h(program)
    assert [(c.text, c.speaker_tag) for c in cmds if type(c) is Say] == [
        ("One.", "daichi"), ("Two.", "daichi"), ("Three.", "hana"), ("End.", None)]
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    state = interp.checkpoint()
    assert interp.restore(state).result is RestoreResult.OK
    restored = [c for c in take_all(interp) if type(c) is Say]
    assert [(c.text, c.speaker_tag, c.restored) for c in restored[-1:]] == [
        ("One.", "daichi", True)]


# --- PR-F04-12 — words that changed nothing (run-time half of AC-F04-12) ---------------------

INFO_TEXT = ("script/main.vns, line {}: hana's words \"pout\" changed nothing, because hana "
             "isn't on stage.")


@pytest.mark.parametrize("dev", [True, False], ids=["dev", "release"])
def test_pr_f04_12_one_info_per_statement_per_session(tmp_path, caplog, dev):
    program = template_game(tmp_path, S='hide hana⏎[4]hana pout "Hi."⏎[4]hana pout "Hi."')
    interp = launched(program, dev=dev)
    with caplog.at_level(logging.DEBUG, logger="vn"):
        for _ in range(2):                                # new game twice, one session
            interp.new_game(42)
            interp.run(10_000)
            play(interp)
    infos = [r for r in caplog.records if r.name == "vn.stage"]
    if not dev:
        assert infos == []
        return
    assert [(r.levelno, r.getMessage()) for r in infos] == [
        (logging.INFO, INFO_TEXT.format(7)), (logging.INFO, INFO_TEXT.format(8))]


# --- AC-F04-16 — one ShowStage per burst, only when the stage changed ------------------------

def test_ac_f04_16_one_picture_per_burst(tmp_path):
    cmds = run_h(story_game(tmp_path, ["scene bg bridge", "show hana happy",
                                       "show daichi grin at right", "show stall at left",
                                       '"A."', '"B."']))
    first, second, end = bursts(cmds)
    assert first[0] == ShowStage(stage(
        "bg bridge | hana happy@center, daichi grin@right, stall@left"))
    assert type(first[1]) is Say and first[1].text == "A."
    assert not any(type(c) is ShowStage for c in second)
    assert end == [StoryEnded()]


def test_ac_f04_16_unflushed_changes_drop_with_the_story_end(tmp_path):
    cmds = run_h(story_game(tmp_path, ['"A."', "scene bg bridge"]))
    # The line's look-ahead names bg bridge (step 7); the change itself is never shown.
    assert [type(c) for c in cmds] == [ShowStage, Say, PrefetchImages, StoryEnded]
    assert stages(cmds) == [EMPTY_STAGE]


def test_ac_f04_16_a_failed_burst_shows_no_stage(tmp_path):
    cmds = run_h(story_game(tmp_path, ["show hana happy", "$ 1/0"]))
    assert [type(c) for c in cmds] == [StoryFailed]


def test_ac_f04_16_every_story_keeps_the_rule(tmp_path):
    games = [lanterns(tmp_path / "lanterns"), template_game(tmp_path / "template")]
    for i, (lines, _) in enumerate(AC07.values()):
        games.append(story_game(tmp_path / f"ac07-{i}", lines))
    for i, (lines, _, _) in enumerate(AC11.values()):
        games.append(template_game(tmp_path / f"ac11-{i}", S=lines, T=KAITO))
    for program in games:
        assert_burst_rule(run_h(program, IMG + IMG_L))


# --- AC-F04-20 — a restore shows the saved stage at once -------------------------------------

def lantern_lines(root: Path):
    """Play ``lanterns/`` to the end: each line's (round-tripped) checkpoint and the stage
    sequence from each line on."""
    program = lanterns(root)
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    states, per_line = [], []
    while interp.status is Status.WAITING:
        states.append(GameState.from_json(json.loads(json.dumps(interp.checkpoint().to_json()))))
        per_line.append(stages(take_all(interp)))
        advance(interp)
    return program, states, per_line


@pytest.fixture
def spies(monkeypatch):
    """Count every stage executor and ``apply_dialogue_words`` call."""
    calls = []
    for node, run in ((Scene, stage_mod.run_scene), (Show, stage_mod.run_show),
                      (Hide, stage_mod.run_hide)):
        monkeypatch.setitem(interp_mod.EXECUTORS, node,
                            lambda i, s, run=run: (calls.append(type(s)), run(i, s))[1])
    real = stage_mod.apply_dialogue_words
    monkeypatch.setattr(stage_mod, "apply_dialogue_words",
                        lambda *a: (calls.append("words"), real(*a))[1])
    return calls


def test_ac_f04_20_a_restore_shows_the_saved_stage(tmp_path, spies):
    program, states, per_line = lantern_lines(tmp_path / "g")
    assert len(states) == 9
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    for _ in range(8):                                    # played to line 9
        advance(interp)
    take_all(interp)
    for k, state in enumerate(states):
        spies.clear()
        assert interp.restore(state).result is RestoreResult.OK
        burst = take_all(interp)
        assert spies == []                                # no stage statement ran
        kinds = [type(c) for c in burst if type(c) is not PrefetchImages]
        assert kinds == [NvlPage, ShowStage, Say]                # F17 I-3: NvlPage first
        assert burst[1] == ShowStage(state.stage, restored=True)
        assert burst[2].restored and burst[2].sid == state.position
        # Rollback, then forward again: the same stage sequence as the first play.
        rest = play(interp)
        assert stages(rest) == [s for line in per_line[k + 1:] for s in line]
        assert_burst_rule(burst + rest)


def test_ac_f04_20_restore_into_a_fresh_launch(tmp_path, spies):
    program, states, per_line = lantern_lines(tmp_path / "a")
    fresh = launched(lanterns(tmp_path / "b"))            # save, quit, reload
    spies.clear()
    state = states[2]                                     # line 3
    assert fresh.restore(state).result is RestoreResult.OK
    burst = take_all(fresh)
    assert spies == []
    assert burst[:3] == [NvlPage(False), ShowStage(state.stage, restored=True), burst[2]]
    assert type(burst[2]) is Say and burst[2].restored
    assert stages(play(fresh)) == [s for line in per_line[3:] for s in line]


def test_ac_f04_20_restore_sends_the_stage_even_when_it_is_on_screen(tmp_path):
    program = template_game(tmp_path)
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    take_all(interp)
    state = interp.checkpoint()
    assert interp.restore(state).result is RestoreResult.OK
    assert take_all(interp)[:2] == [NvlPage(False), ShowStage(state.stage, restored=True)]
    # I-2: the restored stage counts as shown; nothing is re-sent at the next line.
    assert interp._stage_shown == state.stage and interp.stage == state.stage


# --- AC-F04-22 — saves from before F04 --------------------------------------------------------

def test_ac_f04_22_a_save_from_before_f04(tmp_path):
    data = json.loads((F04 / "saves" / "pre_f04.json").read_text(encoding="utf-8"))
    assert "stage" not in data and data["format"] == 1
    interp = launched(template_game(tmp_path))
    interp.new_game(42)
    interp.run(10_000)
    take_all(interp)
    assert interp.restore(GameState.from_json(data)).result is RestoreResult.OK
    assert interp.stage == EMPTY_STAGE
    burst = take_all(interp)
    assert burst[:2] == [NvlPage(False), ShowStage(EMPTY_STAGE, restored=True)]   # F17 I-3
    assert burst[2].text == "End." and burst[2].restored
    saved = interp.checkpoint().to_json()
    assert saved["stage"] == {"background": None, "sprites": []} and saved["format"] == 1


# --- 07 I-1, I-2 — the prefetch hint in the burst ---------------------------------------------

def test_i_1_prefetch_comes_last_and_only_when_it_changed(tmp_path, monkeypatch):
    hint = PrefetchImages(("bg bridge",), ())
    monkeypatch.setattr(stage_mod, "lookahead", lambda interp, start: hint)
    program = story_game(tmp_path, ['"A."', '"B."'])
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    assert take_all(interp)[-1] == hint                       # ShowStage, Say, PrefetchImages
    advance(interp)
    assert hint not in take_all(interp)                       # unchanged: not sent again
    state = interp.checkpoint()
    assert interp.restore(state).result is RestoreResult.OK
    assert [type(c) for c in take_all(interp)] == [NvlPage, ShowStage, Say,
                                                    PrefetchImages]               # I-2
    interp.new_game(42)
    interp.run(10_000)
    assert take_all(interp)[-1] == hint                       # new game resets it too


def test_flush_stage_holds_only_changes(tmp_path):
    interp = launched(story_game(tmp_path, ['"A."']))
    interp.new_game(42)
    assert stage_mod.flush_stage(interp) is True              # nothing shown since new game
    assert stage_mod.flush_stage(interp) is False
    interp.stage = stage("bg bridge |")
    assert stage_mod.flush_stage(interp) is True
    assert no_audio(interp._held) == [ShowStage(EMPTY_STAGE), ShowStage(stage("bg bridge |"))]


# --- E135 (AC-F04-39's rows; the W rows are step 6's) -----------------------------------------

E135_CASES = [c for c in message_cases.load_cases() if c.feature == "F04" and c.code == "E135"]


def test_e135_rows_exist():
    assert {c.id for c in E135_CASES} == {"F04-39-E135-kind", "F04-39-E135-words"}


@pytest.mark.parametrize("case", E135_CASES, ids=lambda c: c.id)
def test_e135(tmp_path, case):
    program = load_files(tmp_path, {"main.vns": message_cases.main_text(case)})
    commands = run_headless(program, seed=42, image_files=IMG)
    (failed,) = commands
    assert type(failed) is StoryFailed and type(failed.error) is ScriptErrorGroup
    (error,) = failed.error.errors
    message_cases.check_case(case, message_cases.Outcome([error], (), 1, False))
    assert error.format().startswith("script/main.vns, line 2: ")


@pytest.mark.parametrize("value, ok", [
    ('"daichi"', True), ('"Ünï"', True), ('"a_b2"', True), ('"zoom"', False), ('"show"', False),
    ('"a-b"', False), ('""', False), ("None", False), ("True", False), ('"x y"', False),
])
def test_image_tag_values(tmp_path, value, ok):
    from engine.runtime.launch import run_launch
    program = load_files(tmp_path, {"main.vns": f'define d = Character("D", image_tag={value})\n'
                                                 'label start:\n    d "Hi."\n'})
    launch = run_launch(program)
    assert (launch.namespace is not None) is ok
    if not ok:
        assert [e.code for e in launch.errors] == ["E135"]


def test_advance_unchanged_by_the_stage(tmp_path):
    """The stage never changes F03's flow: ``Advance`` still moves line by line."""
    program = story_game(tmp_path, ['"A."', "show hana happy", '"B."'])
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    sid = interp.current.sid
    interp.post(Advance(sid))
    interp.run(10_000)
    assert interp.current.text == "B." and interp.stage == stage("∅ | hana happy@center")

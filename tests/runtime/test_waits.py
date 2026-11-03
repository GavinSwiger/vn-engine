"""F09 step 1 — the story flow headless (``runtime/effects.py``, ``stage.flush_stage``,
``Interpreter.begin_wait``; F09 ``04-technical.md`` §6.1, §6.2): AC-F09-08 to AC-F09-15, the
headless golden with waits (06 §9 Step 1 milestone), and the wait seams later features build
on (F18 ``then``, F14 ``finish_wait``, F23 ``defer``; 07 I-3)."""

import dataclasses
import json

import pytest

from engine.runtime import headless as headless_mod
from engine.runtime import limits
from engine.runtime.commands import (Advance, AudioRestore, Choose, Flash, NvlPage,
                                     PrefetchImages, Say,
                                     Shake, ShowMenu, ShowStage, StoryEnded, StoryFailed,
                                     StoryWait, WaitDone)
from engine.runtime.headless import HeadlessWaitError, run_headless
from engine.runtime.interpreter import RestoreResult, Status, Step
from engine.runtime.stage import EMPTY_STAGE, StageState
from engine.runtime.state import GameState
from tests.runtime import effects_story
from tests.runtime import stage_story
from tests.runtime.effects_story import (IMG9, bursts, fixture, launched, of_type, run_h,
                                         run_to_wait, started, story_game, take_all,
                                         template_game)

WAITS_INPUTS = ["advance", "advance", "choose 1"]


def line_texts(burst) -> list[str]:
    return [c.text for c in burst if type(c) is Say]


def kinds(burst) -> list[str]:
    return [type(c).__name__ for c in burst]


def burst_after(commands, text: str):
    """The burst released after the line ``text`` was advanced."""
    out = bursts(commands)
    index = next(i for i, b in enumerate(out) if text in line_texts(b))
    return out[index + 1]


# --- AC-F09-08 — a with emits its transition and waits ------------------------------------------

AC08 = [
    # (T, S, (kind, name, seconds, color, mask, soft, reverse) or None for a cut)
    (None, "scene bg sea with fade", ("fade", "fade", None, None, None, 0.1, False)),
    (None, "show hana sad with dissolve 0.3", ("dissolve", "dissolve", 0.3, None, None, 0.1,
                                               False)),
    (None, 'scene bg sea with fade 0.4 "#ffe08a"', ("fade", "fade", 0.4, "#FFE08A", None, 0.1,
                                                    False)),
    (None, "show hana sad with slow_dissolve", ("dissolve", "slow_dissolve", 1.5, None, None,
                                                0.1, False)),
    (None, "show hana sad with slow_dissolve 0.4", ("dissolve", "slow_dissolve", 0.4, None,
                                                    None, 0.1, False)),
    (None, "scene bg sea with lantern", ("mask", "lantern", 1.2, None, "masks/iris.png", 0.1,
                                         False)),
    ('define wf = Fade(0.6, color="#ffffff")', "scene bg sea with wf 1.0",
     ("fade", "wf", 1.0, "#FFFFFF", None, 0.1, False)),
    (None, "show hana sad with cut", None),
    (None, "show hana sad with dissolve 0", None),
    ("define z = Dissolve(0)", "show hana sad with z", None),
]


def test_ac08_a_with_emits_its_transition_and_waits(tmp_path):
    for number, (T, S, expected) in enumerate(AC08):
        program = template_game(tmp_path / str(number), S=S, T=T)
        commands = run_h(program)
        first = bursts(commands)[0]
        show, wait = first[-2:]
        sid6 = program.labels["start"].block[1].sid
        assert type(show) is ShowStage and type(wait) is StoryWait, S
        assert wait == StoryWait(1, sid6, None, True, True), S
        assert not of_type(first, Say, PrefetchImages), S
        spec = show.transition
        if expected is None:
            assert spec is None, S
        else:
            assert (spec.kind, spec.name, spec.seconds, spec.color, spec.mask, spec.soft,
                    spec.reverse) == expected, S
            assert (spec.sid, spec.calm, spec.flashes) == (sid6, True, False), S
        assert type(commands[-1]) is StoryEnded, S


# --- AC-F09-09 — grouping: one picture per moment -----------------------------------------------

def _shown(burst) -> list[tuple]:
    out = []
    for c in burst:
        if type(c) is ShowStage:
            out.append(("show", c.stage, c.transition.kind if c.transition else None))
        elif type(c) is StoryWait:
            out.append(("wait", c.wait_id))
        elif type(c) is Say:
            out.append(("say", c.text))
    return out


def test_ac09_grouping():
    commands = run_h(fixture("group"))
    st = stage_story.stage
    assert [_shown(b) for b in bursts(commands)[:-1]] == [
        [("show", st("bg ember"), None), ("say", "A.")],
        [("show", st("bg river | hana happy@left, daichi grin@right"), "dissolve"), ("wait", 1)],
        [("show", st("bg river | hana sad@left, daichi grin@right"), None), ("say", "B.")],
        [("show", st("bg sea"), "fade"), ("wait", 2)],
        [("show", st("bg sea | hana happy@center"), "dissolve"), ("wait", 3)],
        [("show", st("bg sea | hana sad@center"), None), ("say", "C.")],
    ]
    assert type(commands[-1]) is StoryEnded
    river = [c.stage for c in of_type(commands, ShowStage) if c.stage.background == "bg river"]
    assert all(len(s.sprites) == 2 for s in river)


FIXTURES = [("group", ()), ("waits", WAITS_INPUTS), ("all", ())]


def test_ac09_one_show_stage_per_burst():
    for name, inputs in FIXTURES:
        commands = run_h(fixture(name), inputs=inputs)
        assert type(commands[-1]) is StoryEnded, name
        for burst in bursts(commands):
            assert len(of_type(burst, ShowStage)) <= 1, (name, kinds(burst))


# --- AC-F09-10 — an unchanged picture takes no time ---------------------------------------------

AC10 = [
    (["show hana happy", '"A."', "show hana happy with dissolve", '"B."'], ["Say"]),
    (["scene bg sea", '"A."', "scene bg sea with fade", '"B."'], ["Say"]),
    (["show hana happy", '"A."', "shake", "show hana happy with dissolve", '"B."'],
     ["Shake", "Say"]),
]


def test_ac10_an_unchanged_picture_takes_no_time(tmp_path):
    for number, (lines, expected) in enumerate(AC10):
        commands = run_h(story_game(tmp_path / str(number), lines))
        assert kinds(burst_after(commands, "A.")) == expected, lines


# --- AC-F09-11 — waits are not checkpoints or runaways ------------------------------------------

def test_ac11_only_the_current_wait_id_resumes():
    interp, _ = started(fixture("waits"))
    line = interp.current
    released = run_to_wait(interp)
    assert line_texts(released) == [] and interp.status is Status.WAITING
    assert interp.waiting_for == 1
    for event in (Advance(line.sid), WaitDone(0), WaitDone(2)):
        interp.post(event)
        interp.run(10_000)
        assert take_all(interp) == [] and interp.waiting_for == 1, event
    interp.post(WaitDone(1))
    interp.run(10_000)
    assert [type(c) for c in take_all(interp)] == [ShowStage, StoryWait]
    assert interp.waiting_for == 2


def test_ac11_ids_count_up_and_waits_take_no_input():
    commands = run_h(fixture("waits"), inputs=WAITS_INPUTS)
    assert [w.wait_id for w in of_type(commands, StoryWait)] == [1, 2, 3, 4]
    assert type(commands[-1]) is StoryEnded
    assert type(of_type(commands, ShowMenu)[0]) is ShowMenu


def _loop(tmp_path, body: list[str], count: int):
    return story_game(tmp_path, [f"if i < {count}:", "    $ i += 1", *[f"    {b}" for b in body],
                                 "    jump start", '"Done."'], top="default i = 0\n")


def test_ac11_a_wait_resets_the_step_count(tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "STEP_LIMIT", 1_000)
    commands = run_h(_loop(tmp_path / "a", ["pause 0.1"], 2_000))
    assert type(commands[-1]) is StoryEnded
    assert len(of_type(commands, StoryWait)) == 2_000
    failed = run_h(_loop(tmp_path / "b", [], 2_000))[-1]
    assert type(failed) is StoryFailed and failed.error.code == "E45"


@pytest.mark.slow
def test_ac11_a_wait_resets_the_full_step_count(tmp_path):
    """The full 100,000-step case (driven directly: run H stops a loop of waits, I-3)."""
    program = _loop(tmp_path / "a", ["pause 0.1"], 60_000)
    interp, _ = started(program)
    while interp.status is Status.WAITING:
        interp.post(WaitDone(interp.waiting_for) if interp.waiting_for is not None
                    else Advance(interp.current.sid))
        interp.run(10_000)
        take_all(interp)
    assert interp.status is Status.ENDED
    failed = run_h(_loop(tmp_path / "b", [], 60_000))[-1]
    assert type(failed) is StoryFailed and failed.error.code == "E45"


def test_i3_a_loop_of_waits_stops_the_headless_run(tmp_path, monkeypatch):
    monkeypatch.setattr(headless_mod, "WAIT_LIMIT", 200)
    program = story_game(tmp_path, ['"Start."', "jump l"],
                         after="label l:\n    pause 0.1\n    jump l\n")
    with pytest.raises(HeadlessWaitError) as caught:
        run_h(program)
    assert caught.value.args[0] == (
        "the story waited 200 times in a row with no line or choice, last at script/main.vns, "
        "line 6, so the headless run stopped. A loop of pauses and transitions only ends when "
        "a player leaves it.")
    assert len(of_type(caught.value.commands, StoryWait)) == 200


def test_i3_the_limit_is_10000_and_lines_reset_it(tmp_path):
    assert headless_mod.WAIT_LIMIT == 10_000
    commands = run_h(_loop(tmp_path, ["pause 0.1", '"Line."'], 300))
    assert type(commands[-1]) is StoryEnded


# --- AC-F09-12 — the textbox flag for each wait ------------------------------------------------

AC12 = [
    (["scene bg sea with fade"], [True]),
    (["show hana happy with dissolve"], [False]),
    (["scene bg sea", "show hana happy with dissolve"], [True]),
    (["scene bg sea with fade", "show hana happy with dissolve"], [True, True]),
    (["scene bg sea with fade", '"B."', "show hana happy with dissolve"], [True, False]),
    (["pause"], [False]),
    (["scene bg sea", "pause 1.0"], [True]),
]


def test_ac12_hide_box(tmp_path):
    for number, (rows, expected) in enumerate(AC12):
        commands = run_h(story_game(tmp_path / str(number),
                                    ["scene bg ember", '"A."', *rows, '"Z."']))
        assert [w.hide_box for w in of_type(commands, StoryWait)] == expected, rows


def test_ac12_the_first_statement(tmp_path):
    commands = run_h(story_game(tmp_path, ["scene bg sea with fade", '"A."']))
    assert [type(c) for c in commands[:3]] == [AudioRestore, ShowStage, StoryWait]
    assert commands[2].hide_box is True


def test_ac12_a_menu_question_resets_it(tmp_path):
    commands = run_h(story_game(tmp_path, [
        '"A."', "scene bg sea", "menu:", '    hana "Which?"', '    "This one.":',
        "        pause", '    "That one.":', "        pause"]), inputs=["advance", "choose 1"])
    (wait,) = of_type(commands, StoryWait)
    assert wait.hide_box is False


# --- AC-F09-13 — shake and flash commands -------------------------------------------------------

def _after_start(tmp_path, rows: list[str]):
    commands = run_h(story_game(tmp_path, ["scene bg ember", '"Start."', *rows]))
    return commands, bursts(commands)[1:]


def test_ac13_shake_before_a_line_with_options_and_the_last_wins(tmp_path):
    _, (burst, *_) = _after_start(tmp_path / "a", ["shake", '"A."'])
    assert burst[:2] == [Shake(None, None, None), burst[1]] and line_texts(burst) == ["A."]
    _, (burst, *_) = _after_start(tmp_path / "b", ["shake large horizontal 2.0", '"A."'])
    assert of_type(burst, Shake) == [Shake("large", "horizontal", 2.0)]
    commands, _ = _after_start(tmp_path / "c", ["shake small", "shake large", '"A."'])
    assert of_type(commands, Shake) == [Shake("large", None, None)]


def test_ac13_the_last_flash_wins(tmp_path):
    program = story_game(tmp_path, ["scene bg ember", '"Start."', "flash", "flash red 0.6",
                                    '"A."'])
    second = program.labels["start"].block[3].sid
    assert of_type(run_h(program), Flash) == [Flash("#FF0000", 0.6, second)]


def test_ac13_burst_order_at_a_line(tmp_path):
    _, (burst, *_) = _after_start(tmp_path, ["shake", "flash", "show hana sad", 'hana "A."'])
    assert kinds(burst)[:4] == ["ShowStage", "Shake", "Flash", "Say"]


def test_ac13_burst_order_at_a_with(tmp_path):
    _, (burst, line, *_) = _after_start(tmp_path, ["flash", "scene bg sea with fade", '"A."'])
    assert kinds(burst) == ["ShowStage", "Flash", "StoryWait"]
    assert line_texts(line) == ["A."] and not of_type(line, Flash, ShowStage)


def test_ac13_shake_then_pause(tmp_path):
    _, (burst, *_) = _after_start(tmp_path, ["shake", "pause 1.0"])
    assert kinds(burst) == ["Shake", "StoryWait"] and burst[1].seconds == 1.0


def test_ac13_a_flash_loop(tmp_path):
    program = story_game(tmp_path, ['"Start."', "jump again"], top="default i = 0\n",
                         after=("label again:\n    if i < 10000:\n        flash\n"
                                "        $ i += 1\n        jump again\n    \"A.\"\n"))
    commands = run_h(program)
    (burst,) = [b for b in bursts(commands) if "A." in line_texts(b)]
    assert len(of_type(commands, Flash)) == 1 and len(burst) <= 5


def test_ac13_effects_always_ride_a_moment():
    for name, inputs in FIXTURES:
        for burst in bursts(run_h(fixture(name), inputs=inputs)):
            if of_type(burst, Shake, Flash):
                assert of_type(burst, StoryWait, Say, ShowMenu), (name, kinds(burst))
                ends = [i for i, c in enumerate(burst) if type(c) in (StoryWait, Say, ShowMenu)]
                effects = [i for i, c in enumerate(burst) if type(c) in (Shake, Flash)]
                assert max(effects) < min(ends), name


# --- AC-F09-14 — pause commands -----------------------------------------------------------------

def test_ac14_a_timed_pause_shows_the_moment(tmp_path):
    _, (burst, *_) = _after_start(tmp_path, ["show hana sad", "pause 1.5"])
    show, wait = burst
    assert type(show) is ShowStage and show.transition is None
    assert (wait.seconds, wait.for_stage, wait.hide_box) == (1.5, False, False)


def test_ac14_an_untimed_pause(tmp_path):
    _, (burst, *_) = _after_start(tmp_path, ["pause", '"A."'])
    assert len(burst) == 1 and type(burst[0]) is StoryWait
    assert (burst[0].seconds, burst[0].for_stage) == (None, False)


# --- AC-F09-15 — not save points --------------------------------------------------------------

def _waits_at_each_wait():
    """Play waits/ step by step; yield (interp, the checkpoint object at the last line or
    choice, its JSON) at each of the 4 waits."""
    interp, _ = started(fixture("waits"))
    seen = 0
    while interp.status is Status.WAITING:
        if interp.waiting_for is not None:
            seen += 1
            yield interp
            interp.post(WaitDone(interp.waiting_for))
        elif type(interp.current) is ShowMenu or interp.choices.waiting is not None:
            interp.post(Choose(interp.current.sid, interp.choices.waiting.pickable[0]))
        else:
            interp.post(Advance(interp.current.sid))
        interp.run(10_000)
        take_all(interp)
    assert seen == 4 and interp.status is Status.ENDED


def test_ac15_the_checkpoint_during_a_wait_is_the_last_line_or_choice():
    interp, _ = started(fixture("waits"))
    last = interp.checkpoint()
    while interp.status is Status.WAITING:
        if interp.waiting_for is not None:
            assert interp.checkpoint() is last
            assert interp.checkpoint().to_json() == saved
            interp.post(WaitDone(interp.waiting_for))
        else:
            if interp.choices.waiting is not None:
                interp.post(Choose(interp.current.sid, interp.choices.waiting.pickable[0]))
            else:
                interp.post(Advance(interp.current.sid))
        interp.run(10_000)
        take_all(interp)
        if interp.waiting_for is None and interp.status is Status.WAITING:
            last = interp.checkpoint()
        saved = last.to_json() if last is not None else None
        if interp.waiting_for is not None:
            assert interp.checkpoint() is last


def test_ac15_game_state_has_no_new_field():
    # F09 adds none; F18's ``chapter``, F22's ``points``, F14's ``rollback`` and F17's ``nvl``
    # came later.
    assert [f.name for f in dataclasses.fields(GameState)] == [
        "position", "position_at", "call_stack", "variables", "dice", "identity_scheme",
        "stage", "audio", "choices", "history", "chapter", "points", "rollback", "nvl",
        "items", "minigame", "flow", "glitch",              # F21, F23, F20, F28
        "window_title", "ui"]                               # F30, F32


@pytest.mark.parametrize("wait", [1, 2, 3, 4])
def test_ac15_restore_during_a_wait(wait):
    for interp in _waits_at_each_wait():
        if interp.waiting_for != wait:
            continue
        state = interp.checkpoint()
        old = interp.waiting_for
        assert interp.restore(state).result is RestoreResult.OK
        burst = take_all(interp)
        assert type(burst[0]) is AudioRestore
        assert burst[1] == NvlPage(False)                            # F17 I-3
        assert burst[2] == ShowStage(state.stage, restored=True)
        assert burst[2].transition is None
        assert not of_type(burst, Shake, Flash, StoryWait)
        assert type([c for c in burst if type(c) is not PrefetchImages][-1]) in (Say, ShowMenu)
        assert interp.waiting_for is None and interp.pending_shake is None
        interp.post(WaitDone(old))
        interp.run(10_000)
        assert take_all(interp) == []
        return


def test_ac15_new_game_during_a_wait():
    for interp in _waits_at_each_wait():
        old = interp.waiting_for
        fresh, first = started(fixture("waits"))
        interp.new_game(42)
        interp.run(10_000)
        assert take_all(interp) == first
        assert interp.waiting_for is None and interp.scene_since_line is False
        interp.post(WaitDone(old))
        interp.run(10_000)
        assert take_all(interp) == []
        return


def test_ac15_a_save_from_f04_loads_and_continues(tmp_path):
    data = json.loads((stage_story.F04 / "saves" / "pre_f04.json").read_text(encoding="utf-8"))
    interp = stage_story.launched(stage_story.template_game(tmp_path))
    interp.new_game(42)
    interp.run(10_000)
    take_all(interp)
    assert interp.restore(GameState.from_json(data)).result is RestoreResult.OK
    burst = take_all(interp)
    assert [type(c) for c in burst] == [AudioRestore, NvlPage, ShowStage, Say]   # F17 I-3
    assert burst[2] == ShowStage(EMPTY_STAGE, restored=True) and burst[3].text == "End."
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    assert take_all(interp) == [StoryEnded()]


# --- The headless golden with waits (06 §9 Step 1 milestone) ------------------------------------

def test_the_headless_golden_with_waits():
    assert effects_story.GOLDEN.read_bytes() == effects_story.golden_text().encode("ascii"), (
        "regenerate with: .venv/Scripts/python -m tests.runtime.effects_story --write-golden")


def test_the_golden_has_every_wait_kind():
    commands = json.loads(effects_story.GOLDEN.read_text(encoding="ascii"))["commands"]
    waits = [c for c in commands if c["type"] == "StoryWait"]
    assert [w["wait_id"] for w in waits] == list(range(1, len(waits) + 1))
    assert {(w.get("seconds"), w["for_stage"]) for w in waits} == {
        (None, True), (1.0, False), (None, False)}
    names = {c["transition"]["name"] for c in commands
             if c["type"] == "ShowStage" and c.get("transition")}
    assert names == {"fade", "dissolve", "slow_dissolve", "lantern", "lantern_out"}


def test_windowed_driver_shape_equals_headless():
    """A driver that answers each wait one frame later (as StageScreen will) releases the
    same commands as run H."""
    program = fixture("all")
    expected = run_h(program)
    interp, out = started(program)
    while interp.status is Status.WAITING:
        if interp.waiting_for is not None:
            interp.post(WaitDone(interp.waiting_for))
        else:
            interp.post(Advance(interp.current.sid))
        for _ in range(3):
            interp.run(1)
            out += interp.take_commands(2)
        while interp.status is Status.RUNNING or interp.released:
            interp.run(10_000)
            out += interp.take_commands(2)
    assert out == expected


# --- Seams: then (F18), finish_wait (F14), defer (F23) -------------------------------------------

def test_then_runs_inside_run_and_may_wait_again(tmp_path):
    program = story_game(tmp_path, ["scene bg ember", '"A."', "scene bg sea", '"B."'])
    interp, _ = started(program)
    calls = []

    def second(i):
        calls.append(("second", i.status))
        return None

    def first(i):
        calls.append(("first", i.status))
        return i.begin_wait(seconds=2.0, then=second)

    interp.post(Advance(interp.current.sid))
    scene = interp.current                          # `scene bg sea`, as its executor would:
    assert interp.status is Status.RUNNING
    assert interp.begin_wait(scene, seconds=1.0, then=first) is Step.WAIT
    assert take_all(interp)[-1] == StoryWait(1, scene.sid, 1.0, False, False)
    interp.post(WaitDone(1))
    assert calls == [] and interp.status is Status.RUNNING      # never inside post
    interp.run(10_000)
    assert calls == [("first", Status.RUNNING)] and interp.waiting_for == 2
    assert take_all(interp) == [StoryWait(2, scene.sid, 2.0, False, False)]
    interp.finish_wait()                                       # F14's path: as WaitDone
    interp.run(10_000)
    assert calls[-1] == ("second", Status.RUNNING)
    assert line_texts(take_all(interp)) == ["B."]


def test_a_failing_then_fails_the_story_under_run(tmp_path):
    program = story_game(tmp_path, ['"A."', "pause", '"B."'])
    interp, _ = started(program)
    interp.post(Advance(interp.current.sid))
    interp.run(1)
    assert interp.waiting_for == 1
    take_all(interp)
    interp.wait_then = lambda i: 1 / 0
    interp.post(WaitDone(1))
    interp.run(10_000)
    (failed,) = take_all(interp)
    assert type(failed) is StoryFailed and interp.status is Status.FAILED


def test_defer_runs_next_then_the_successor(tmp_path):
    """F23's use: an accepted event at the waiting statement defers its apply step, which
    runs under run() before the statement's successor."""
    program = story_game(tmp_path, ['"A."', '"B."'])
    interp, _ = started(program)
    seen = []
    interp.status = Status.RUNNING                  # as F23's handler does, at line A
    interp.defer(lambda i: seen.append((i.current.text, i.status)) or None)
    assert seen == []
    interp.run(10_000)
    assert seen == [("A.", Status.RUNNING)] and interp.status is Status.WAITING
    assert interp.current.text == "B."
    interp.defer(lambda i: None)
    with pytest.raises(AssertionError):
        interp.defer(lambda i: None)


def test_restore_and_new_game_clear_the_wait_state(tmp_path):
    program = story_game(tmp_path, ['"A."', "shake", "flash", "pause", '"B."'])
    interp, _ = started(program)
    state = interp.checkpoint()
    interp.post(Advance(interp.current.sid))
    interp.run(1)
    interp.run(1)                                               # shake, flash pending
    assert interp.pending_shake is not None and interp.pending_flash is not None
    interp.wait_then = lambda i: None
    assert interp.restore(state).result is RestoreResult.OK
    assert (interp.pending_shake, interp.pending_flash, interp.waiting_for,
            interp.wait_then, interp._deferred) == (None, None, None, None, None)
    interp.new_game(42)
    assert interp.scene_since_line is False


def test_story_state_never_holds_the_wait(tmp_path):
    """No F09 state reaches GameState: a checkpoint after a wait equals one without it."""
    with_wait = run_headless(story_game(tmp_path / "a", ['"A."', "pause 1.0", '"B."']), seed=1,
                             image_files=IMG9)
    without = run_headless(story_game(tmp_path / "b", ['"A."', '"B."']), seed=1,
                           image_files=IMG9)
    assert [c for c in with_wait if type(c) is not StoryWait] == without


def test_stage_state_unchanged_by_with(tmp_path):
    interp, _ = started(story_game(tmp_path, ["scene bg sea with fade", '"A."']))
    assert interp.stage == StageState("bg sea")
    assert interp.waiting_for == 1
    assert interp.checkpoint() is None
    assert launched(story_game(tmp_path / "b", ['"A."'])).waiting_for is None

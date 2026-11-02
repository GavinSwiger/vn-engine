"""F03 step 10 — the step and call limits (``04-technical.md`` §7.2, §7.3, §12.2;
SR-F03-26, SR-F03-27): what counts as a step, E45 and its label list, E45b, and the window
during a runaway loop. AC-F03-10, 11, 12, 13.

Exact boundaries: ``STEP_LIMIT`` is read from ``engine.runtime.limits`` at run time, so the
rows patch it there; the ``runaway/`` fixtures (06 §5.2) run with the real limits (about
0.05 s each headless).
"""

import re
import time
from pathlib import Path

import pygame
import pytest

from engine.runtime import limits
from engine.runtime.commands import Advance, StoryEnded, StoryFailed
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Status
from engine.runtime.state import GameState
from tests.runtime.conftest import round_trip
from tests.runtime.story import FIXTURES, load_files, run_r, start, texts

E45_TAIL = ". Check the jumps there: every way around the loop needs a line or a way out."
E45B_TAIL = ". Did you mean jump? A call always comes back; jump goes to a label for good."


def runaway(name: str, **values: object) -> str:
    """``tests/fixtures/F03/runaway/<name>.vns`` with N or LIMIT substituted."""
    text = (FIXTURES / "runaway" / f"{name}.vns").read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace(key, str(value))
    return text


def play(root: Path, text: str, **kwargs) -> list:
    return run_headless(load_files(root, {"main.vns": text}), seed=42, **kwargs)


def failure(commands):
    """The one error of a run that "fails with" it (06 §0.5): ``StoryFailed`` comes last."""
    assert type(commands[-1]) is StoryFailed
    assert [type(c) for c in commands].count(StoryFailed) == 1
    return commands[-1].error


def ended(commands) -> bool:
    return type(commands[-1]) is StoryEnded and not any(type(c) is StoryFailed
                                                        for c in commands)


# --- AC-F03-10 — what counts as a step --------------------------------------------------------

# (S, T, steps, the line shown at L = steps, where E45 is at L = steps - 1). Where 06 gives
# no line for E45, the place is this build's: a step inside a statement is at that
# statement, an end of a block at the last line of the block's last statement.
STEP_ROWS = [
    ("⏎[4]".join(["$ a = 1"] * 6), None, 6, "End.", 13),
    ("if False:⏎[8]$ a = 1⏎[4]elif True:⏎[8]$ a = 2", None, 4, "End.", 11),
    ("if False:⏎[8]$ a = 1⏎[4]else:⏎[8]$ a = 2", None, 4, "End.", 11),
    ("if True:⏎[8]if False:⏎[12]$ a = 1⏎[8]$ b = 2", None, 4, "End.", 11),
    ("call c", "label c:⏎[4]$ z = 1", 3, "End.", 12),
    ("jump j", 'label j:⏎[4]"J."', 1, "J.", 8),
]
STEP_IDS = ["six-dollar-lines", "if-elif", "if-else", "nested-if", "call", "jump"]


@pytest.mark.parametrize("S, T, steps, shown, at", STEP_ROWS, ids=STEP_IDS)
def test_ac_f03_10_exactly_the_limit_shows_the_line(tmp_path, monkeypatch, S, T, steps,
                                                    shown, at):
    monkeypatch.setattr(limits, "STEP_LIMIT", steps)
    commands = run_r(tmp_path, S=S, T=T)
    assert ended(commands), commands[-1]
    assert texts(commands)[:2] == ["Start.", shown]


@pytest.mark.parametrize("S, T, steps, shown, at", STEP_ROWS, ids=STEP_IDS)
def test_ac_f03_10_one_step_fewer_fails_with_e45(tmp_path, monkeypatch, S, T, steps, shown,
                                                 at):
    monkeypatch.setattr(limits, "STEP_LIMIT", steps - 1)
    commands = run_r(tmp_path, S=S, T=T)
    error = failure(commands)
    assert error.code == "E45" and (error.file, error.line) == ("script/main.vns", at)
    assert texts(commands) == ["Start."]
    assert error.format().split(": ", 1)[1].startswith(f"the story ran {steps - 1:,} steps")


def test_ac_f03_10_count_fixture_exactly_100000_steps_then_a_line(tmp_path):
    assert limits.STEP_LIMIT == 100_000
    commands = play(tmp_path, runaway("count", N=33_333))
    assert ended(commands)
    assert texts(commands) == ["Start.", "Done."]


def test_ac_f03_10_count_fixture_step_100001_is_the_jump(tmp_path):
    commands = play(tmp_path, runaway("count", N=33_334))
    error = failure(commands)
    assert (error.code, error.line) == ("E45", 8)
    assert error.source_line == "jump spin"
    assert texts(commands) == ["Start."]


def test_steps_count_from_the_last_line_shown(tmp_path):
    # Two loops of 90,001 steps each, with a line between them: neither reaches the limit.
    text = ('label start:\n    "Start."\n    $ i = 0\n    call spin\n    "Mid."\n'
            '    $ i = 0\n    call spin\n    "Done."\n'
            "label spin:\n    $ i += 1\n    if i < 30000:\n        jump spin\n    return\n")
    commands = play(tmp_path, text)
    assert ended(commands) and texts(commands) == ["Start.", "Mid.", "Done."]


def test_a_line_resets_the_count_and_the_labels(tmp_path):
    interp = start(load_files(tmp_path, {"main.vns": runaway("depth", LIMIT=3)}))
    assert interp.status is Status.WAITING and interp.steps == 0
    assert list(interp.entered) == []
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    assert interp.current.text == "Deep." and interp.steps == 0
    assert list(interp.entered) == []
    # F09's seam: a wait starts the count again the same way.
    interp.steps = 5
    interp.entered.append((5, "r"))
    interp.reset_steps()
    assert interp.steps == 0 and list(interp.entered) == []


def test_steps_counted_on_the_advance_can_fail_too(tmp_path, monkeypatch):
    # The end of the if block after "Mid." is the first step after the line: with the
    # limit at 0 it fails on the advance itself, at the line's last line.
    interp = start(load_files(tmp_path, {"main.vns": (
        'label start:\n    "Start."\n    if True:\n        "Mid."\n    "End."\n')}))
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    assert interp.current.text == "Mid."
    interp.take_commands(10)
    monkeypatch.setattr(limits, "STEP_LIMIT", 0)
    interp.post(Advance(interp.current.sid))
    assert interp.status is Status.FAILED
    (cmd,) = interp.take_commands(10)
    assert type(cmd) is StoryFailed and (cmd.error.code, cmd.error.line) == ("E45", 4)


# --- AC-F03-11 — the endless-loop message ------------------------------------------------------

def test_ac_f03_11_shop_and_street(tmp_path):
    error = failure(play(tmp_path, runaway("shop")))
    assert (error.code, error.line) == ("E45", 7)
    assert error.format().split("\n")[0] == (
        'script/main.vns, line 7: the story ran 100,000 steps without showing a line, so it is '
        'probably stuck in a loop through the labels "shop" and "street". Check the jumps '
        "there: every way around the loop needs a line or a way out.")


def test_ac_f03_11_five_labels_name_three_and_more(tmp_path):
    names = "abcde"
    loop = "".join(f"label {a}:\n    jump {b}\n" for a, b in zip(names, names[1:] + "a"))
    error = failure(play(tmp_path, f'label start:\n    "Start."\n    jump a\n{loop}'))
    message = error.format().split("\n")[0]
    assert error.code == "E45"
    assert 'through the labels "a", "b", "c", and 2 more' + E45_TAIL in message
    assert re_names(message) == ["a", "b", "c"]


def test_ac_f03_11_one_label(tmp_path):
    error = failure(play(tmp_path, 'label start:\n    "Start."\n    jump spin\n'
                                   "label spin:\n    jump spin\n"))
    assert (error.code, error.line) == ("E45", 5)
    assert error.format().split("\n")[0].endswith(
        'stuck in a loop through the label "spin"' + E45_TAIL)


def test_ac_f03_11_ties_go_in_reading_order(tmp_path):
    # street is written first, although the loop enters shop first.
    text = ('label start:\n    "Start."\n    jump shop\nlabel street:\n    jump shop\n'
            "label shop:\n    jump street\n")
    error = failure(play(tmp_path, text))
    assert 'through the labels "street" and "shop".' in error.format()


def test_ac_f03_11_most_often_first(tmp_path):
    # Each round enters "rare" once and "hub" three times (twice by its own jump).
    text = ('label start:\n    "Start."\n    $ k = 0\n    jump rare\n'
            "label rare:\n    jump hub\n"
            "label hub:\n    $ k += 1\n    if k % 3:\n        jump hub\n    jump rare\n")
    error = failure(play(tmp_path, text))
    assert 'through the labels "hub" and "rare".' in error.format()


def test_e45_counts_only_the_labels_of_the_last_1000_steps(tmp_path):
    # "early" is entered only in the first steps after the line; the loop then runs on
    # through "spin" alone, so only "spin" is named.
    text = ('label start:\n    "Start."\n    jump early\nlabel early:\n    $ i = 0\n'
            "    jump spin\nlabel spin:\n    jump spin\n")
    error = failure(play(tmp_path, text))
    assert 'through the label "spin".' in error.format()


def test_e45_under_a_patched_limit_with_no_label_entered(tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "STEP_LIMIT", 1)
    error = failure(run_r(tmp_path, S="$ a = 1⏎[4]$ b = 2"))
    assert (error.code, error.line) == ("E45", 9)
    assert 'through the label "start"' in error.format()


def re_names(message: str) -> list[str]:
    return re.findall(r'"(\w+)"', message)


# --- AC-F03-12 — too many waiting calls ---------------------------------------------------------

def test_ac_f03_12_chat(tmp_path):
    error = failure(play(tmp_path, runaway("chat")))
    assert (error.code, error.line, error.source_line) == ("E45b", 7, "call chat")
    assert error.format().split("\n")[0] == (
        'script/main.vns, line 7: 1,000 calls are waiting to return, and 999 of them called '
        'label "chat". Did you mean jump? A call always comes back; jump goes to a label for '
        "good.")


def test_ac_f03_12_depth_1000_plays_to_the_end(tmp_path):
    commands = play(tmp_path, runaway("depth", LIMIT=1000))
    assert ended(commands)
    assert texts(commands) == ["Start.", *["Deep."] * 1000, "Back."]


def test_ac_f03_12_depth_1001_fails_at_the_call(tmp_path):
    error = failure(play(tmp_path, runaway("depth", LIMIT=1001)))
    assert (error.code, error.line, error.source_line) == ("E45b", 9, "call r")
    assert ', and 1,000 of them called label "r"' + E45B_TAIL in error.format()


def test_the_deepest_checkpoint_holds_1000_calls_and_round_trips(tmp_path):
    interp = start(load_files(tmp_path, {"main.vns": runaway("depth", LIMIT=1000)}))
    interp.post(Advance(interp.current.sid))
    interp.run(1_000_000)
    state = interp.checkpoint()
    assert interp.current.text == "Deep." and len(state.call_stack) == limits.CALL_DEPTH_MAX
    again = round_trip(state)
    assert isinstance(again, GameState) and again.call_stack == state.call_stack


# --- AC-F03-13 — the window stays usable during a runaway loop ----------------------------------

def _run_app(game: Path, on_frame) -> tuple[int, object, list[float], object]:
    """Run the real app (real clock and frame limiter, ``FakeWindow``) on ``game``; press
    Space once ``Start.`` is shown complete (F05: a press while typing only completes the
    line); ``on_frame(app, now)`` runs before every frame wait.
    Returns (exit code, app, every ``story.pump()`` duration, the window)."""
    from engine.app import bootstrap
    from engine.app.app import App
    from engine.app.loading import story_load_screen
    from engine.app.story import RuntimeStoryDriver
    from engine.core.config_schema import Config, TitleConfig
    from engine.core.constants import MB
    from engine.core.paths import GamePaths
    from engine.core.timing import GameTime
    from engine.render.assets import AssetManager
    from engine.ui.builtin.textbox_screen import TextboxScreen
    from tests.fakes.fake_window import FakeWindow
    from tests.fakes.loop import post_key

    pumps: list[float] = []
    real_pump = RuntimeStoryDriver.pump

    def pump(self, *args, **kwargs):
        t = time.perf_counter()
        try:
            return real_pump(self, *args, **kwargs)
        finally:
            pumps.append(time.perf_counter() - t)

    pygame.init()
    pygame.event.clear()
    try:
        window = FakeWindow()
        paths = GamePaths.for_game(game)
        assets = AssetManager(paths, budget_bytes=64 * MB, scale_filter="smooth",
                              time=GameTime(), format_source=window.framebuffer)
        # F10 step 6: no title, so the story starts at launch as before.
        app = App(config=Config(title=TitleConfig(enabled=False)), paths=paths,
                  window=window, assets=assets, log=None,
                  dev=True, bench_seconds=None)
        app.screens.replace_all([story_load_screen(
            app, paths, on_ready=bootstrap.build_initial_screens)])
        real_wait = app._limiter.wait
        pressed = []

        def wait():
            now = time.perf_counter()
            story = app.story
            if (not pressed and story is not None and story.status is Status.WAITING
                    and isinstance(app.screens.top, TextboxScreen)
                    and app.screens.top.indicator_kind() == "line"):
                post_key(pygame.K_SPACE)
                pressed.append(now)
            on_frame(app, now)
            return real_wait()

        app._limiter.wait = wait
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(RuntimeStoryDriver, "pump", pump)
            code = app.run()
    finally:
        pygame.quit()
    return code, app, pumps, window


def _shop_game(tmp_path: Path) -> Path:
    from tests.app.test_story_load_screen import make_game
    return make_game(tmp_path, {"main.vns": runaway("shop")})


@pytest.mark.display
def test_ac_f03_13_fullscreen_and_quit_during_the_loop(tmp_path, monkeypatch):
    # The reference machine runs 100,000 steps in about 1-2 s (04 §7.3); this one may finish
    # them before the 0.3 s mark, so the limit is raised to keep the loop running here.
    from tests.fakes.loop import post_key, post_quit

    monkeypatch.setattr(limits, "STEP_LIMIT", 100 * limits.STEP_LIMIT)
    marks: dict[str, float] = {}

    def on_frame(app, now):
        story = app.story
        if "loop" not in marks:
            if story is not None and story.status is Status.RUNNING and story.interp.steps:
                marks["loop"] = now
            return
        if "f11" not in marks and now - marks["loop"] >= 0.3:
            post_key(pygame.K_F11)
            marks["f11"] = now
            marks["f11_running"] = story.status is Status.RUNNING
        if "quit" not in marks and now - marks["loop"] >= 0.5:
            post_quit()
            post_quit()             # F10 step 7: the first close asks in game, the second quits
            marks["quit"] = now
            marks["quit_running"] = story.status is Status.RUNNING

    code, app, pumps, window = _run_app(_shop_game(tmp_path), on_frame)
    ended_at = time.perf_counter()
    assert code == 0
    assert marks["f11_running"] and marks["quit_running"]        # both during the loop
    assert window.calls.count("set_fullscreen") == 1
    assert ended_at - marks["quit"] < 1.0
    assert len(pumps) > 20 and max(pumps) <= 0.05, max(pumps)


@pytest.mark.display
def test_ac_f03_13_e45_reaches_the_error_screen(tmp_path):
    from engine.ui.builtin.error import ErrorScreen
    from tests.fakes.loop import post_quit

    marks: dict[str, float] = {}

    def on_frame(app, now):
        story = app.story
        if "loop" not in marks and story is not None and story.status is Status.RUNNING \
                and story.interp.steps:
            marks["loop"] = now
        if "error" not in marks and isinstance(app.screens.top, ErrorScreen):
            marks["error"] = now
            post_quit()
        if "loop" in marks and now - marks["loop"] > 12:
            post_quit()                                              # never hang the suite

    code, app, pumps, _ = _run_app(_shop_game(tmp_path), on_frame)
    assert "error" in marks and marks["error"] - marks["loop"] < 10.0
    assert code == 1
    assert "the story ran 100,000 steps without showing a line" in app.screens.top.message
    assert pumps and max(pumps) <= 0.05, max(pumps)

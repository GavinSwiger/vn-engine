"""F04 step 9 — the six-sprite bench and the no-hitch check (``04-technical.md`` §14 "Perf";
``06-acceptance.md`` §1.11, §5.4, D1): AC-F04-48 and AC-F04-49 (``perf``), plus CI guards.

**CI guards (every run, in process, ``scripted_app``, fake clock):** the generated bench
script is the AC's scene (a background and 6 sprites in every stage, a dialogue-line
expression, a move, a ``behind``); the harness's Advance makes exactly one stage change and
the stage composes exactly once per change (a count); the harness plays the example game
to its end with one compose per ``ShowStage``; the report's helpers read the engine's own
bench lines.

**Reference runs (``perf``; the ADR-0005 machine or a stand-in with integrated graphics and a
PassMark single-thread score ≤ 2,000, never CI).** Close other apps, mains power,
"Balanced" plan, a 1920×1080 display at 100%, then (Windows, from the project root)::

    .venv/Scripts/python tests/perf/gen_stage_bench.py --seed 1
    set SDL_VIDEODRIVER=windows
    set VN_PERF=1
    set VN_PASSMARK_ST=<the machine's PassMark single-thread score>
    .venv/Scripts/python -m pytest tests/perf/test_stage_bench.py -m perf -s -v

(``SDL_VIDEODRIVER=x11`` or ``cocoa`` elsewhere; the tests fail under the dummy driver.)
AC-F04-48 is four 600 s runs (about 41 minutes; the fullscreen ones take the screen) and
AC-F04-49 plays the example game at 5 s a line (about 2 minutes). The generator is run by the
test too when ``tests/perf/stage_bench/`` is missing. Attach the printed lines (machine,
versions, the five bench lines of each run, compose times, the long frames after each
change) to the F04 test report; ``docs/process/manual-F04.md`` lists the rest.
``VN_BENCH_SECONDS=N`` shortens AC-F04-48's runs for a trial; such a run is not a result.
"""

import os
import shutil
from pathlib import Path

import pygame
import pytest

from engine.core.timing import BenchRecorder
from engine.runtime.commands import Say, ShowStage
from engine.runtime.headless import run_headless
from engine.runtime.stage import EMPTY_STAGE
from tests.perf import gen_stage_bench as gen
from tests.perf.stage_bench_harness import (StageBenchHarness, bench_launch,
                                            check_bench_game, long_frames_after,
                                            machine_lines, parse_bench, report_lines,
                                            scripted_play)
from tests.runtime.stage_story import load_game
from tests.fakes.first_launch import answer_name_question
from tests.script.load_process import cpu_name

REPO = Path(__file__).resolve().parents[2]
SMALL = 5                                # the CI guards' image scale (240×400 sprites;
                                         # art_height 216, above its minimum of 180)
CHANGES_MAX = 120                        # D1: one Advance every 5 s for 600 s
WORK_P99_MAX_MS = 16.00                  # ADR-0005
LONG_PCT_MAX = 0.50
MEASURED_TOLERANCE_S = 0.05


def small_bench(root: Path) -> Path:
    return gen.generate(root, seed=1, scale=SMALL)


def copy_example(dest: Path) -> Path:
    """``game/`` without its logs, with the title skipped so the story starts at once."""
    shutil.copytree(REPO / "game", dest, ignore=shutil.ignore_patterns("logs", "characters"))
    with (dest / "config.toml").open("a", encoding="utf-8") as f:
        f.write("\n[title]\nenabled = false\n")
    answer_name_question(dest)               # F30 s6: no first-launch name question
    return dest


def example_run(game: Path) -> list:
    """The headless run of ``game`` (seed 1), its menus (F07) answered with the first
    choice, as the harness does."""
    from engine.core.paths import GamePaths
    from engine.script.loader import LoadOptions, load_story
    from tests.runtime.corpus import play
    from tests.runtime.stage_story import example_minigames, position_names

    # F24–F26: the example's minigames, ended with their test outcome as the harness does.
    minigames = example_minigames()
    result = load_story(GamePaths(game.resolve()),
                        LoadOptions(position_names=position_names(game), minigames=minigames))
    assert result.program is not None, [e.format() for e in result.errors]
    program = result.program
    return run_headless(program, seed=1, inputs=play(program, 1).inputs, minigames=minigames)


def headless_stages(game: Path) -> list:
    return [c.stage for c in example_run(game) if type(c) is ShowStage]


def presented(harness: StageBenchHarness) -> list:
    return [c.stage for c in harness.changes() if c.stage != EMPTY_STAGE]


# --- CI guards ------------------------------------------------------------------------------

def test_bench_script_is_the_scene_of_d1(tmp_path):
    """AC-F04-48's headless check on the generated script (sizes scaled by ``SMALL``)."""
    root = small_bench(tmp_path / "bench")
    assert check_bench_game(root, sprite_size=(240, 400), art_height=216) == []
    sprite = pygame.image.load(str(root / "images" / "aki" / "calm.png"))
    assert 0.40 <= gen.transparent_fraction(sprite) <= 0.50          # about 45% (06 §5.4)
    assert len(gen.image_refs()) == 14                               # 2 backgrounds, 12 sprites
    assert gen.config_text(fullscreen=True).count("fullscreen = true") == 1


@pytest.mark.display
def test_each_advance_is_one_stage_change_composed_once(tmp_path, user_roots, scripted_app):
    """The harness posts ``Advance(current sid)`` every period; each makes one stage change,
    and the stage composes once per change, never on the frames between (TR-F04-03)."""
    root = small_bench(tmp_path / "bench")
    harness = StageBenchHarness(advance_s=10 / 60)                   # every 10 frames
    assert scripted_play(scripted_app, root, harness, frames=60) == 0
    stages = presented(harness)                  # the empty stage before the game is not one
    assert harness.story_started is not None and harness.posts >= 5
    assert len(stages) == harness.posts + 1                          # the first, then one per post
    assert len(harness.composes) == len(harness.changes())           # once per change
    assert all(s.background is not None and len(s.sprites) == 6 for s in stages)
    assert harness.warnings == []


@pytest.mark.display
def test_harness_plays_the_example_game_to_its_end(tmp_path, user_roots, scripted_app):
    """AC-F04-49's harness on ``game/``: the story ends, and every ``ShowStage`` of the
    headless run is composed once, in order."""
    game = copy_example(tmp_path / "game")
    harness = StageBenchHarness(advance_s=3 / 60)                    # every 3 frames
    # F17: 45 waits; the story ends near frame 197 (F19's last menu, F21's codex lines).
    assert scripted_play(scripted_app, game, harness, frames=700) == 0
    assert harness.ended_at is not None
    assert presented(harness) == headless_stages(game)
    assert harness.warnings == []


def test_long_frames_after_counts_the_following_second():
    frames = [0.0, 0.016, 0.050, 0.066, 1.000, 1.040, 2.000, 2.016, 2.032, 2.200]
    # change at 0.016: 0.050 (34 ms) long, 1.000 (934 ms) long, 1.040 is past 1 s.
    # change at 2.000: 2.200 (168 ms) long.
    assert long_frames_after(frames, [0.016, 2.000]) == [2, 1]
    assert long_frames_after(frames, []) == []


def test_parse_bench_reads_the_engine_lines():
    recorder = BenchRecorder(fps=60, seconds=1.0, start=0.0, warmup_s=0.0)
    t = 0.0
    for i in range(61):
        recorder.record(t, None if i == 0 else 1 / 60, 0.004)
        t += 1 / 60
    recorder.done(t)
    lines = recorder.log_lines(recorder.result(), "1280x720 windowed | framebuffer 1280x720 px")
    parsed = parse_bench(lines)
    assert parsed["window"] == (1280, 720) and parsed["mode"] == "windowed"
    assert parsed["framebuffer"] == (1280, 720) and parsed["frames"] == 60
    assert parsed["work_p99"] == 4.0 and parsed["long_pct"] == 0.0
    assert parsed["cap_holds"] and parsed["verdict"] == "PASS"
    assert parsed["measured_s"] == round(recorder.result().measured_s, 2)


# --- AC-F04-48, AC-F04-49 (perf) -----------------------------------------------------------

@pytest.fixture(scope="module")
def bench_game():
    """``tests/perf/stage_bench/`` at seed 1 (generated if missing), checked headless before
    any run (AC-F04-48)."""
    root = gen.OUT
    stamp = root / gen.STAMP
    if not stamp.is_file() or stamp.read_text(encoding="utf-8") != gen.stamp(1, 1):
        gen.generate(root, seed=1)
    problems = check_bench_game(root, sprite_size=gen.SPRITE_SIZE, art_height=gen.ART_HEIGHT)
    assert problems == []
    yield root
    (root / "config.toml").write_text(gen.config_text(), encoding="utf-8", newline="\n")


def _report(title: str, harness: StageBenchHarness) -> None:
    print(f"\n== {title}")
    for line in machine_lines(cpu_name(), os.environ.get("VN_PASSMARK_ST"), harness.driver):
        print(line)
    for line in harness.bench_lines + report_lines(harness):
        print(line)
    for compose in harness.changes():
        print(f"  change at {compose.frame_start - harness.frames[0]:8.2f} s: compose "
              f"{compose.ms:.2f} ms at {compose.size[0]}x{compose.size[1]}")


@pytest.mark.perf
@pytest.mark.parametrize("fullscreen", [False, True], ids=["1280x720-windowed",
                                                           "1920x1080-fullscreen"])
@pytest.mark.parametrize("changing", [True, False], ids=["changing", "static"])
def test_ac_f04_48_six_sprites_at_60_fps(bench_game, real_display, user_roots, fullscreen,
                                         changing):
    seconds = float(os.environ.get("VN_BENCH_SECONDS", "600"))
    (bench_game / "config.toml").write_text(gen.config_text(fullscreen=fullscreen),
                                            encoding="utf-8", newline="\n")
    harness = StageBenchHarness(advance_s=5.0 if changing else None)
    code = bench_launch(bench_game, harness, seconds=seconds)
    _report(f"AC-F04-48 {'fullscreen' if fullscreen else 'windowed'} "
            f"{'changing' if changing else 'static'} ({seconds:.0f} s)", harness)
    assert code == 0 and harness.warnings == []
    bench = parse_bench(harness.bench_lines)
    if fullscreen:
        assert bench["mode"] == "fullscreen" and bench["framebuffer"] == (1920, 1080)
    else:
        assert bench["mode"] == "windowed" and bench["window"] == (1280, 720)
    changes = len(presented(harness))
    assert (2 <= changes <= CHANGES_MAX + 1) if changing else changes == 1
    assert abs(bench["measured_s"] - seconds) <= MEASURED_TOLERANCE_S
    assert bench["cap_holds"]
    assert bench["work_p99"] <= WORK_P99_MAX_MS
    assert bench["long_pct"] <= LONG_PCT_MAX


@pytest.mark.perf
def test_ac_f04_49_no_hitch_when_the_stage_changes(tmp_path, real_display, user_roots):
    """``game/`` (a copy, title skipped) at 1280×720 with the 5 s harness until it ends.
    With no title the session closes at the story's end, before the ``--bench`` window
    closes, so no bench lines are printed; the AC judges only the frames after each change.
    Every presented change is judged, also the ones a dialogue-line attribute makes (the AC
    names ``scene`` and ``show``; this is stricter)."""
    game = copy_example(tmp_path / "game")
    expected = headless_stages(game)
    lines = sum(1 for c in example_run(game) if type(c) is Say)
    harness = StageBenchHarness(advance_s=5.0)
    code = bench_launch(game, harness, seconds=5.0 * lines + 5.0)
    _report(f"AC-F04-49 example game, {lines} lines", harness)
    assert code == 0 and harness.warnings == []
    assert harness.ended_at is not None
    assert presented(harness) == expected
    assert harness.window == (1280, 720)
    assert max(harness.long_after_changes()) <= 1

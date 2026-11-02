"""F06 step 3 — blips on every line at 40 and 1,000 cps hold invariant 10 (AC-F06-13; ``07``
I-5). The games are F05's typing bench (``gen_text_bench.py``) with a blip for each of its
six speakers, ``blip_pitch=0.1``: three 0.1 s files and three 0.5 s ones (the longest that
still gets pitch variants), so each file's first blip is a cold miss that reads, decodes, and
resamples on the loader's worker while the line types. F05's harness presses every 2 s.

**CI guard (every run, in process, ``scripted_app``, fake clock, ``FakeMixer``):** the small
blip game at both speeds plays with no warning, and blips sound on channel 1 in more than one
pitch.

**Reference runs (``perf``, never CI)**, as F05's (``test_text_bench.py``'s docstring: the
machine, power plan, and display), with a sound device::

    set SDL_VIDEODRIVER=windows
    set VN_PERF=1
    set VN_PASSMARK_ST=<the machine's PassMark single-thread score>
    .venv/Scripts/python -m pytest tests/perf/test_blip_bench.py -m perf -s -v

Two 600 s ``--bench`` runs at 1280×720 windowed (about 21 minutes); ``VN_BENCH_SECONDS=N``
shortens them for a trial (not a result). The blip latency half of AC-F06-13 (a 0.1 s
file's first blip ≤ 50 ms after its glyph, cached ones within one buffer) is a manual
check: a recording of the run, the glyph's frame against the blip's onset.
"""

import os
import re
from pathlib import Path

import pytest

from engine.audio.limits import BLIP_CHANNEL
from tests.fixtures.F08.make_audio import example_blip
from tests.perf import gen_text_bench as gen
from tests.perf.stage_bench_harness import bench_launch, parse_bench
from tests.perf.test_text_bench import (LONG_PCT_MAX, MEASURED_TOLERANCE_S, SMALL,
                                        WORK_P99_MAX_MS, TextBenchHarness, _report, config_text,
                                        play, spy_textbox)

PITCH = 0.1
# Per speaker (gen.stage.TAGS order): (frequency Hz, seconds).
BLIPS = ((1046.5, 0.1), (196.0, 0.5), (659.25, 0.1), (293.66, 0.5), (880.0, 0.1),
         (130.81, 0.5))
_DEFINE = re.compile(r'^(define (\w+) = Character\(.*)\)$')


def blip_script(seed: int = 1) -> str:
    """F05's bench script with ``blip="blips/<tag>.wav", blip_pitch=0.1`` on each define."""
    def add(match: re.Match) -> str:
        return f'{match[1]}, blip="blips/{match[2]}.wav", blip_pitch={PITCH})'

    lines = [_DEFINE.sub(add, line) for line in gen.script_text(seed).splitlines()]
    assert sum("blip=" in line for line in lines) == len(gen.stage.TAGS)
    return "\n".join(lines) + "\n"


def blip_game(folder: Path, *, seed: int = 1, scale: int = 1) -> Path:
    """``folder``: F04's bench art, F05's script with blips, and six blip files; the speed
    is ``set_speed``'s."""
    gen.stage.generate(folder, seed=seed, scale=scale)
    (folder / "script" / "main.vns").write_text(blip_script(seed), encoding="utf-8",
                                                newline="\n")
    audio = folder / "audio" / "blips"
    audio.mkdir(parents=True, exist_ok=True)
    for tag, (freq, seconds) in zip(gen.stage.TAGS, BLIPS):
        (audio / f"{tag}.wav").write_bytes(
            example_blip(freq, seconds, decay=seconds / 5, overtone=2.0))
    return folder


def set_speed(game: Path, cps: int, *, scale: int = 1) -> Path:
    (game / "config.toml").write_text(config_text(cps, art_height=gen.stage.ART_HEIGHT // scale),
                                      encoding="utf-8", newline="\n")
    return game


# --- CI guard ---------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def small(tmp_path_factory) -> Path:
    return blip_game(tmp_path_factory.mktemp("blip_bench"), scale=SMALL)


@pytest.mark.display
@pytest.mark.parametrize("cps", gen.CPS)
def test_blip_bench_game_blips_with_no_warning(small, user_roots, scripted_app, cps):
    harness = TextBenchHarness(advance_s=None, press_s=0.5)
    game = set_speed(small, cps, scale=SMALL)
    assert play(scripted_app, game, harness, frames=100) == 0
    assert harness.warnings == []
    mixer = scripted_app.mixers[-1]
    played = [args[1] for _, _, args in mixer.actions("channel_play")
              if args[0] == BLIP_CHANNEL]
    assert len(played) >= 5 and len(set(played)) >= 2             # pitch variants


# --- AC-F06-13 (perf) -------------------------------------------------------------------------

@pytest.mark.perf
@pytest.mark.parametrize("cps", gen.CPS, ids=lambda cps: f"{cps}cps")
def test_ac_f06_13_blips_on_every_line_at_60_fps(tmp_path, real_display, user_roots, cps):
    game = set_speed(blip_game(tmp_path / "game"), cps)
    seconds = float(os.environ.get("VN_BENCH_SECONDS", "600"))
    harness = TextBenchHarness(advance_s=None)
    with pytest.MonkeyPatch.context() as mp, spy_textbox(harness, mp):
        code = bench_launch(game, harness, seconds=seconds)
    _report(f"AC-F06-13 blips, 1280x720 windowed {cps} cps ({seconds:.0f} s)", harness)
    assert code == 0 and harness.warnings == []
    bench = parse_bench(harness.bench_lines)
    assert bench["mode"] == "windowed" and bench["window"] == (1280, 720)
    assert harness.presses >= 2 and len(harness.said) >= 2
    assert abs(bench["measured_s"] - seconds) <= MEASURED_TOLERANCE_S
    assert bench["cap_holds"]
    assert bench["work_p99"] <= WORK_P99_MAX_MS
    assert bench["long_pct"] <= LONG_PCT_MAX

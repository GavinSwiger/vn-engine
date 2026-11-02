"""AC-F03-76: a snapshot (the checkpoint walk plus the ``GameState`` build) takes at most
2 ms (p95 over 500 runs after 50 warm-ups, ``gc`` enabled) on the reference machine (``perf``,
G16); CI records the median of 50 runs after 5 warm-ups and fails only above 10 ms.

Each run is the real checkpoint routine, ``Interpreter.take_checkpoint`` (04 §7.4 steps 1-6:
the F04 stage flush, the walk, the build, the lookahead, the release), on a launched story
waiting at its line with ``perf/gen_vars.py --n 1000 --seed 5`` added to ``G`` next to its
define, ``dice``, and the other engine names, and (F22 07 I-7) 200 declared meters. The
released commands are taken between runs, outside the timed part. (06-acceptance §4 lists ``tests/perf/test_runtime_perf.py`` for the
``perf`` rows; this AC stays here, and that file names it.)

The reference-machine run (ADR-0005: Intel Core i5-8250U, or a stand-in with a PassMark
single-thread score of at most 2,000)::

    set VN_PERF=1
    .venv/Scripts/python -m pytest tests/runtime/test_snapshot_perf.py -m perf -s
"""

import json
import statistics
import time

import pytest

from engine.runtime.interpreter import Interpreter, Status, say_command
from tests.fixtures.F03.perf.gen_vars import generate
from tests.runtime.story import load_files, start

WARMUP = 50
RUNS = 500
CI_WARMUP = 5          # the CI guard's median needs far fewer runs than the p95
CI_RUNS = 50
STORY = ('define hana = Character("Hana", color="#e8a0b4")\n'
         + "points " + " ".join(f"m{i}" for i in range(200)) + " 0 to 100\n"   # F22 I-7
         + 'label start:\n    hana "Line."\n')


@pytest.fixture(scope="module")
def waiting(tmp_path_factory) -> Interpreter:
    """The story waiting at its line, with the 1,000 benchmark variables in ``G``."""
    interp = start(load_files(tmp_path_factory.mktemp("snapshot"), {"main.vns": STORY}))
    assert interp.status is Status.WAITING
    interp.G.update(generate(1000, 5))
    interp.take_commands(1 << 30)
    return interp


def timings(interp: Interpreter, warmup: int = WARMUP, runs: int = RUNS) -> list[float]:
    stmt = interp.current
    cmd = say_command(interp, stmt)
    for _ in range(warmup):
        interp.take_checkpoint(stmt, cmd)
        interp.take_commands(1 << 30)
    out = []
    for _ in range(runs):
        began = time.perf_counter()
        interp.take_checkpoint(stmt, cmd)
        out.append(time.perf_counter() - began)
        interp.take_commands(1 << 30)
    assert interp.status is Status.WAITING
    return out


def test_fixture_shape(waiting):
    variables = generate(1000, 5)
    assert len(variables) == 1000
    assert abs(len(json.dumps(variables)) - 100 * 1024) <= 5 * 1024
    scalars = sum(type(v) not in (list, dict) for v in variables.values())
    assert 550 <= scalars <= 650                                    # 60% scalars by count
    waiting.take_checkpoint(waiting.current, say_command(waiting, waiting.current))
    waiting.take_commands(1 << 30)
    state = waiting.checkpoint()
    assert set(state.variables) == set(variables)    # the define and engine names left out
    assert dict(state.variables) == variables


def test_snapshot_ci_guard_ac_76(waiting):
    median = statistics.median(timings(waiting, CI_WARMUP, CI_RUNS))
    print(f"AC-F03-76 take_checkpoint median: {median * 1000:.3f} ms")
    assert median <= 0.010


@pytest.mark.perf
def test_snapshot_p95_ac_76(waiting):
    from tests.script.load_process import cpu_name

    times = sorted(timings(waiting))
    p95 = times[int(0.95 * len(times)) - 1]
    print(f"\nAC-F03-76 on {cpu_name()}: take_checkpoint p95 {p95 * 1000:.3f} ms, median "
          f"{statistics.median(times) * 1000:.3f} ms, max {times[-1] * 1000:.3f} ms")
    assert p95 <= 0.002

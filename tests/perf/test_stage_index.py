"""F04 step 9 — AC-F04-05: indexing 10,000 image files costs at most 1 s more at launch
(``06-acceptance.md`` §1.1; PR-F04-25, invariant 10).

**CI guard (every run):** the template game with 1,000 zero-byte ``.png`` files in 10 folders
of 100 goes through the launch's image scan and stage check (``LaunchJob`` phases 4 and 5,
as ``app/loading.py`` builds it). The scan is sliced (at least one step per folder), no step
takes longer than the AC's 0.1 s frame interval (a loose limit: a few ms here), and no file
under ``images/`` is opened.

**Reference run (``perf``; the ADR-0005 machine or a stand-in, never CI)**::

    set VN_PERF=1
    .venv/Scripts/python -m pytest tests/perf/test_stage_index.py -m perf -s -v

Any video driver will do (the dummy one included). Two games: the template plus 10,000
zero-byte ``.png`` files in 100 folders of 100, and the template with an empty ``images/``.
Each is launched with ``--bench 1`` six times, alternately; the first launch of each is
discarded and the median of the other five is taken. Launches run in process
(``bootstrap.launch`` with the real clock and frame limiter; test-review-F01/F02: one real
process launch at most), so the time runs from the ``launch()`` call, not process start, to
the first frame with the story installed and ``App.loading`` False; the interpreter start and
imports are the same for both games and drop out of the difference the AC judges. Attach the
printed lines to the F04 test report.
"""

import os
import statistics
import time
from pathlib import Path

import pytest

from engine.app.loading import image_source
from engine.core.paths import GamePaths
from engine.runtime.launch import LaunchJob
from tests.perf.stage_bench_harness import StageBenchHarness, bench_launch, machine_lines
from tests.runtime.stage_story import TEMPLATE_CONFIG, load_game
from tests.script.conftest import opened  # noqa: F401  (fixture)
from tests.script.helpers import template_s
from tests.script.load_process import cpu_name

STEP_MAX_S = 0.1                         # AC-F04-05: every frame interval during launch
EXTRA_MAX_S = 1.0                        # AC-F04-05: 10,000 files vs an empty images/
RUNS = 5                                 # after 1 discarded launch


def template_game(root: Path, files: int) -> Path:
    """Template S (06 §0.4) with ``files`` zero-byte PNGs in folders of 100."""
    (root / "script").mkdir(parents=True)
    (root / "script" / "main.vns").write_text(template_s(), encoding="utf-8", newline="\n")
    (root / "config.toml").write_text(TEMPLATE_CONFIG, encoding="utf-8", newline="\n")
    (root / "images").mkdir()
    for f in range(files // 100):
        folder = root / "images" / f"set{f:02}"
        folder.mkdir()
        for i in range(100):
            (folder / f"pic{i:02}.png").write_bytes(b"")
    return root


def images_opened(events, root: Path) -> list[str]:
    images = os.path.normcase(str((root / "images").resolve()))
    return [str(path) for event, path in events
            if event == "open" and isinstance(path, (str, bytes, os.PathLike))
            and os.path.normcase(os.fsdecode(path)).startswith(images)]


# --- CI guard -------------------------------------------------------------------------------

def test_ac_f04_05_scan_steps_stay_short_and_open_nothing(tmp_path, opened):  # noqa: F811
    root = template_game(tmp_path / "g", 1_000)
    paths = GamePaths(root.resolve())
    job = LaunchJob(load_game(root), images=image_source(paths), game_root=paths.root)
    steps = []
    with opened() as events:
        done = False
        while not done:
            started = time.perf_counter()
            done = job.step()
            steps.append(time.perf_counter() - started)
    result = job.result
    assert result.namespace is not None
    assert len(result.images.names) == 1_000 + 1                       # plus the built-in black
    assert len(steps) >= 10                                             # one folder per step
    assert max(steps) <= STEP_MAX_S, f"longest step {max(steps) * 1000:.1f} ms"
    assert images_opened(events, root) == []


# --- AC-F04-05 (perf) -----------------------------------------------------------------------

class _UntilReady(StageBenchHarness):
    """Ends the launch at the first frame with the story installed and loading over."""

    def __init__(self) -> None:
        super().__init__(advance_s=None)
        self.ready_at: float | None = None

    def on_frame(self, app, now: float) -> None:
        super().on_frame(app, now)
        if self.ready_at is None and app.story is not None and not app.loading:
            self.ready_at = now
            app.request_quit(force=True)


def _launch(root: Path, opened) -> tuple[float, float, list[str], str | None]:  # noqa: F811
    """One launch: (seconds to ready, longest frame interval before it, files opened under
    ``images/``, the video driver)."""
    harness = _UntilReady()
    with opened() as events:
        started = time.perf_counter()
        assert bench_launch(root, harness, seconds=1.0) == 0
    assert harness.ready_at is not None
    before = [t for t in harness.frames if t <= harness.ready_at]
    longest = max((b - a for a, b in zip(before, before[1:])), default=0.0)
    return harness.ready_at - started, longest, images_opened(events, root), harness.driver


@pytest.mark.perf
def test_ac_f04_05_indexing_ten_thousand_files(tmp_path, user_roots, opened):  # noqa: F811
    full = template_game(tmp_path / "full", 10_000)
    empty = template_game(tmp_path / "empty", 0)
    times: dict[Path, list[float]] = {full: [], empty: []}
    longest = 0.0
    for run in range(RUNS + 1):
        for root in (full, empty):
            seconds, interval, opens, driver = _launch(root, opened)
            assert opens == [], opens
            if run:                                                     # run 0 is discarded
                times[root].append(seconds)
                longest = max(longest, interval)
    full_s, empty_s = statistics.median(times[full]), statistics.median(times[empty])
    print("\n== AC-F04-05")
    for line in machine_lines(cpu_name(), os.environ.get("VN_PASSMARK_ST"), driver):
        print(line)
    print(f"10,000 files: median {full_s:.3f} s ({', '.join(f'{t:.3f}' for t in times[full])})")
    print(f"empty images/: median {empty_s:.3f} s "
          f"({', '.join(f'{t:.3f}' for t in times[empty])})")
    print(f"difference {full_s - empty_s:.3f} s; longest frame interval during launch "
          f"{longest * 1000:.1f} ms")
    assert full_s - empty_s <= EXTRA_MAX_S
    assert longest <= STEP_MAX_S

"""Loading in slices (F02 checklist step 6; ``04-technical.md`` §5.1, §7.9; AC-F02-61) and the
corpus generator ``gen_corpus.py`` (06 §5.10).

AC-F02-61 names the example game and ``compat/``: ``compat/`` is checked in ``test_compat.py``
(step 11); here the same property is checked on ``lanterns/``, ``includes/order1/``, a story
with errors and warnings, and the 50,000-word corpus.

Step 11 (AC-F02-63's frame gaps): a slice ends before a unit that would pass its deadline,
and ``step`` pauses Python's cyclic garbage collector inside the slice and restores it.
"""

import gc
import json
import math
import random
import shutil
import time
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script import LoadOptions, StoryLoader, load_story
from engine.script.loader import LoadResult
from tests.script.conftest import load_gen_corpus, write_tree
from tests.script.helpers import FIXTURES, dump, template


def snapshot(result: LoadResult) -> str:
    """Everything a load produces except the wall time: program dump (with sids), error
    texts, warnings, TODOs (06 §0.5)."""
    program = result.program
    data = {
        "errors": [e.format() for e in result.errors],
        "error_count": result.error_count,
        "checks_skipped": result.checks_skipped,
        "no_story": result.no_story,
        "warnings": [w.format() for w in result.warnings],
        "todos": [(t.file.ref, t.line, t.text) for t in result.todos],
        "todo_count": result.todo_count,
    }
    if program is not None:
        data["program"] = {
            "files": [f.ref for f in program.files],
            "labels": dump(list(program.labels.values())),
            "defines": dump(list(program.defines)),
            "stats": [program.stats.files, program.stats.labels, program.stats.statements,
                      program.stats.words],
        }
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def run(paths: GamePaths, budgets) -> tuple[LoadResult, int]:
    """Load with ``budgets`` (an iterator of step budgets); returns the result and the
    number of ``step`` calls."""
    loader = StoryLoader(paths, LoadOptions(collect_todos=True))
    steps = 0
    while not loader.step(next(budgets)):
        steps += 1
    return loader.result, steps + 1


def three_ways(root: Path) -> list[str]:
    paths = GamePaths(root.resolve())
    rng = random.Random(7)
    whole, _ = run(paths, iter(lambda: math.inf, None))
    zero, steps = run(paths, iter(lambda: 0.0, None))
    jitter, _ = run(paths, iter(lambda: rng.uniform(0, 0.01), None))
    assert steps > 1
    return [snapshot(whole), snapshot(zero), snapshot(jitter)]


def _copy(fixture: Path, tmp_path: Path) -> Path:
    shutil.copytree(fixture, tmp_path / "game" / "script")
    return tmp_path / "game"


@pytest.mark.parametrize("fixture", ["lanterns", "includes/order1"])
def test_ac61_fixtures_give_the_same_result_however_sliced(tmp_path, fixture):
    one, two, three = three_ways(_copy(FIXTURES / fixture, tmp_path))
    assert one == two == three
    assert '"program"' in one


def test_ac61_errors_and_warnings_are_the_same_however_sliced(tmp_path):
    root = tmp_path / "game"
    main = template(S='hana “Hi”⏎[4]# TODO tidy⏎[4]$ x = = 1⏎[4]$ y = "\\d"',
                    T='include "a.vns"⏎include "missing.vns"')
    write_tree(root / "script", {"main.vns": main, "a.vns": "label a:\n    retrun\n",
                                 "golden.vns": "# x\n"})
    one, two, three = three_ways(root)
    assert one == two == three
    data = json.loads(one)
    assert data["error_count"] >= 3 and data["warnings"] and data["todos"]


def test_ac61_corpus_gives_the_same_result_however_sliced(corpus):
    root = corpus("--words", "50000", "--files", "10", "--seed", "1")
    one, two, three = three_ways(root)
    assert one == two == three
    assert json.loads(one)["program"]["stats"][3] == 50_000


class FrozenClock:
    """A clock that never moves: ``step`` must still make progress."""

    def __call__(self) -> float:
        return 0.0


def test_ac61_step_zero_always_progresses_and_result_waits(tmp_path):
    root = _copy(FIXTURES / "lanterns", tmp_path)
    loader = StoryLoader(GamePaths(root.resolve()), clock=FrozenClock())
    with pytest.raises(AssertionError):
        loader.result
    calls = 0
    while not loader.step(0.0):
        calls += 1
        assert not loader.done
        with pytest.raises(AssertionError):
            loader.result
        assert calls < 10_000
    assert loader.done and loader.step(0.0) is True
    assert loader.result.program is not None
    assert calls >= 3          # discovery, files, includes, and the build each yield


def test_ac61_slices_are_short(corpus):
    """A slice ends at the first yield point past its budget (§7.9)."""
    paths = GamePaths(corpus("--words", "50000", "--files", "10", "--seed", "1").resolve())
    loader = StoryLoader(paths)
    longest = 0.0
    while True:
        start = time.perf_counter()
        done = loader.step(0.002)
        longest = max(longest, time.perf_counter() - start)
        if done:
            break
    assert longest < 0.25


class StepClock:
    """Each reading is ``tick`` seconds after the last."""

    def __init__(self, tick: float) -> None:
        self.now = 0.0
        self.tick = tick

    def __call__(self) -> float:
        self.now += self.tick
        return self.now


def _step_count(paths: GamePaths, budget: float, clock) -> int:
    loader = StoryLoader(paths, clock=clock)
    steps = 1
    while not loader.step(budget):
        steps += 1
    return steps


def test_a_slice_ends_before_a_unit_that_would_pass_its_deadline(tmp_path):
    """Step 11: with every unit taking 30 ms of a 50 ms budget, a second unit would end at
    60 ms, so each slice does one unit (the old rule did two and overshot by 10 ms)."""
    paths = GamePaths(_copy(FIXTURES / "lanterns", tmp_path).resolve())
    one_unit_each = _step_count(paths, 0.0, FrozenClock())
    assert _step_count(paths, 0.05, StepClock(0.03)) == one_unit_each
    # Units of 10 ms: a slice fits four (the fifth would end at 50 ms, the deadline).
    four = _step_count(paths, 0.05, StepClock(0.01))
    assert four == math.ceil(one_unit_each / 4) or four == math.ceil(one_unit_each / 4) + 1


# --- Step 11: the collector is paused inside a slice -------------------------------------

def _watching(loader: StoryLoader, seen: list[tuple[bool, int]], *, fail_at: int = -1):
    """Wrap the load job: record ``gc.isenabled()`` and the young-generation count at each
    unit; raise at unit ``fail_at``."""
    job = loader._steps

    def run():
        try:
            while True:
                next(job)
                seen.append((gc.isenabled(), gc.get_count()[0]))
                if len(seen) - 1 == fail_at:
                    raise RuntimeError("boom")
                yield
        except StopIteration as stop:
            return stop.value

    loader._steps = run()


def test_step_pauses_the_collector_and_restores_it(tmp_path):
    paths = GamePaths(_copy(FIXTURES / "lanterns", tmp_path).resolve())
    assert gc.isenabled()
    loader = StoryLoader(paths)
    seen: list[tuple[bool, int]] = []
    _watching(loader, seen)
    while not loader.step(0.0):
        assert gc.isenabled()
        # The step's new objects went to the oldest generation without a collection.
        assert gc.get_count()[0] < 50
    assert gc.isenabled()
    assert seen and all(enabled is False for enabled, _ in seen)
    assert loader.result.program is not None


def test_step_restores_the_collector_after_an_exception(tmp_path):
    paths = GamePaths(_copy(FIXTURES / "lanterns", tmp_path).resolve())
    loader = StoryLoader(paths)
    seen: list[tuple[bool, int]] = []
    _watching(loader, seen, fail_at=2)
    with pytest.raises(RuntimeError, match="boom"):
        while not loader.step(math.inf):
            pass
    assert gc.isenabled()


def test_step_leaves_a_collector_the_caller_turned_off_alone(tmp_path):
    paths = GamePaths(_copy(FIXTURES / "lanterns", tmp_path).resolve())
    gc.disable()
    try:
        result = load_story(paths)
        assert not gc.isenabled()
    finally:
        gc.enable()
    assert result.program is not None


def test_step_never_unfreezes_what_someone_else_froze(tmp_path):
    paths = GamePaths(_copy(FIXTURES / "lanterns", tmp_path).resolve())
    gc.freeze()
    try:
        frozen = gc.get_freeze_count()
        assert load_story(paths).program is not None
        assert gc.get_freeze_count() >= frozen
    finally:
        gc.unfreeze()
    assert gc.isenabled()


def test_ac61_reload_after_invalidate_sees_new_content(tmp_path):
    root = _copy(FIXTURES / "lanterns", tmp_path)
    paths = GamePaths(root.resolve())
    first = load_story(paths)
    assert first.program is not None
    (root / "script" / "extra.vns").write_text("label extra:\n    return\n", encoding="utf-8")
    main = root / "script" / "main.vns"
    main.write_text(main.read_text(encoding="utf-8") + 'include "extra.vns"\n',
                    encoding="utf-8")
    paths.invalidate_listings()
    second = load_story(paths)
    assert second.program is not None and "extra" in second.program.labels
    (root / "script" / "main.vns").write_bytes(b"\xff\xfe")
    paths.invalidate_listings()
    third = load_story(paths)
    assert third.program is None and third.errors[0].code == "E01b"


def test_ac61_loads_never_share_state(tmp_path):
    root = _copy(FIXTURES / "lanterns", tmp_path)
    paths = GamePaths(root.resolve())
    a, b = load_story(paths), load_story(paths)
    assert snapshot(a) == snapshot(b)
    assert a.program is not b.program


# --- gen_corpus.py (06 §5.10) ------------------------------------------------------------

def _generate(tmp_path: Path, name: str, *args: str) -> Path:
    out = tmp_path / name
    load_gen_corpus().main([*args, "--out", str(out)])
    return out


def test_corpus_is_deterministic_and_exact(tmp_path):
    args = ("--words", "20000", "--files", "4", "--seed", "3")
    one = _generate(tmp_path, "one", *args)
    two = _generate(tmp_path, "two", *args)
    for path in sorted((one / "script").rglob("*.vns")):
        data = path.read_bytes()
        assert data == (two / "script" / path.relative_to(one / "script")).read_bytes()
        assert b"\r" not in data and not data.startswith(b"\xef\xbb\xbf")
    info = json.loads((one / "corpus.json").read_text(encoding="utf-8"))
    assert info["words"] == 20_000 and info["files"] == 4
    result = load_story(GamePaths(one.resolve()))
    assert result.program is not None and result.errors == () and result.warnings == ()
    stats = result.program.stats
    assert (stats.words, stats.labels, stats.statements) == (
        info["words"], info["labels"], info["statements"])


def test_corpus_insert_changes_only_the_anchor_label(tmp_path):
    args = ("--words", "20000", "--files", "4", "--seed", "3")
    base = _generate(tmp_path, "base", *args)
    more = _generate(tmp_path, "more", *args, "--insert", "3")
    for path in sorted((base / "script").rglob("*.vns")):
        other = (more / "script" / path.relative_to(base / "script")).read_bytes()
        if path.name != "ch001.vns":
            assert other == path.read_bytes()
            continue
        before, after = path.read_text(encoding="utf-8"), other.decode("utf-8")
        added = [line for line in after.splitlines() if line not in before.splitlines()]
        assert len(added) == 3 and all("inserted line" in line for line in added)
    result = load_story(GamePaths(more.resolve()))
    assert result.program is not None and result.errors == ()


def test_corpus_refuses_a_used_folder(tmp_path):
    out = _generate(tmp_path, "used", "--hostile", "blank", "--n", "3")
    with pytest.raises(SystemExit):
        load_gen_corpus().main(["--hostile", "blank", "--n", "3", "--out", str(out)])


@pytest.mark.slow
def test_corpus_million_words_in_ten_seconds(tmp_path):
    start = time.perf_counter()
    out = _generate(tmp_path, "big", "--words", "1000000", "--files", "100", "--seed", "1")
    assert time.perf_counter() - start <= 10
    assert json.loads((out / "corpus.json").read_text(encoding="utf-8"))["words"] == 1_000_000

"""Abuse cases (F02 checklist step 11; ``05-security.md`` §6; ``04-technical.md`` §14).

Where each group of ``05`` §6 lives:

- A (includes and layout): ``test_includes.py``. B (files CPython might open) and C (Python
  resource limits): ``test_pycheck.py``, with the SEC-F02-12 AST scan and the
  ``exec``/``eval`` spy. E (Unicode): ``test_strings.py``, ``test_source.py``,
  ``test_messages.py``. F (messages): ``test_messages.py``. G (identity lookups):
  ``test_identity.py``.
- D (whole-story size) is here: every hostile shape of ``gen_corpus.py`` at a small size in
  every run, under abuse conditions Y (06 §0.5: a ``LoadResult``, no exception, no
  ``Traceback`` on stderr, no file opened outside ``<root>/script``, within 10 s); AC-F02-54
  (load time grows linearly; D2, D3 at 16 MiB; D7 at 100,000; D9 at full size; the regex
  check) under ``slow``; AC-F02-53 (D1, D4: within 60 s and 2 GiB in a fresh process) under
  ``perf``, for the reference machine (06 §0.3).

Also the slicing bound for lines that produce no statement (Step 6's note 8): a run of
blank, comment, or over-long lines yields to the frame loop like any other lines, and the
fast path for plain blank and comment lines (``StatementReader._quiet_run``) gives the same
result as reading them one by one.
"""

import logging
import math
import random
import re
import shutil
import sys
import time
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script import LoadOptions, StoryLoader, load_story
from engine.script import lexer
from engine.script.limits import SCRIPT_REPORT_MAX_RECORDS, SCRIPT_YIELD_LINES
from engine.script.loader import LoadResult
from engine.script.report import report_load_result
from tests.script.conftest import load_gen_corpus, write_tree
from tests.script.test_compat import program_dump
from tests.script.test_fuzz import snapshot

MIB = 1 << 20


def _hostile(out: Path, shape: str, *args: str) -> Path:
    load_gen_corpus().main(["--hostile", shape, *args, "--out", str(out)])
    return out


def inside_script(events: list[tuple[str, str]], root: Path) -> None:
    """Abuse conditions Y: no file opened outside ``<root>/script``, no folder listed
    outside ``<root>``."""
    script = (root / "script").resolve()
    for event, path in events:
        real = Path(path).resolve()
        if event == "open":
            assert real == script or real.is_relative_to(script), (event, path)
        else:
            assert real.is_relative_to(root.resolve()), (event, path)


def load_y(root: Path, opened, capfd, *, todos: bool = False,
           seconds: float = 10.0) -> LoadResult:
    """``load_story`` of ``root`` under abuse conditions Y."""
    with opened() as events:
        start = time.perf_counter()
        result = load_story(GamePaths(root.resolve()), LoadOptions(collect_todos=todos))
        took = time.perf_counter() - start
    assert isinstance(result, LoadResult)
    assert took <= seconds, took
    inside_script(events, root)
    assert "Traceback" not in capfd.readouterr().err
    return result


def codes(result: LoadResult) -> list[str]:
    return [e.code for e in result.errors]


def longest(result: LoadResult) -> int:
    return max((len(e.format()) for e in result.errors), default=0)


# --- Every hostile shape, small, in every run --------------------------------------------

def _clean(result: LoadResult) -> None:
    assert result.program is not None and result.errors == (), codes(result)


SMALL = {
    # shape: (generator arguments, check)
    "py-lines": (("--n", "2", "--mib", "0.02"), _clean),
    "narration": (("--n", "2", "--mib", "0.02"), _clean),
    "defines": (("--n", "2", "--mib", "0.02"), _clean),
    "py-total": (("--n", "2"), _clean),
    "todo": (("--mib", "0.02"), lambda r: (_clean(r), _todos_bounded(r))),
    "escape-warn": (("--mib", "0.02"), lambda r: (_clean(r), _w03_bounded(r))),
    "total-size": (("--n", "2", "--mib", "0.02"), _clean),
    "continuation": (("--n", "3000"), _clean),
    "blank": (("--n", "20000"), _clean),
    "cr-only": (("--n", "3000"), _clean),
    "long-line": (("--n", "12000"), lambda r: _one(r, "E16")),
    "define-cycle": (("--n", "500"), lambda r: _one(r, "E48")),
    "dup-labels": (("--n", "500"), lambda r: _one(r, "E25")),
    "nested-if": (("--n", "60"), lambda r: _one(r, "E15")),
    "bad-lines": (("--n", "3000"), lambda r: _bad_lines(r, 3000)),
    "many-files": (("--n", "30"), _clean),
    "chain": (("--n", "51"), lambda r: _one(r, "E07")),
    "long-labels": (("--n", "60"), lambda r: _all_e43(r)),
}


def _todos_bounded(result: LoadResult) -> None:
    assert len(result.todos) == 150 < result.todo_count                      # D2


def _w03_bounded(result: LoadResult) -> None:
    found = [w.code for w in result.warnings]
    assert found.count("W03") == 50 and found.count("W03b") == 1             # D3


def _one(result: LoadResult, code: str) -> None:
    assert codes(result) == [code] and result.error_count == 1, codes(result)
    assert longest(result) <= 1000


def _bad_lines(result: LoadResult, n: int) -> None:
    assert result.error_count == n and len(result.errors) == 50


def _all_e43(result: LoadResult) -> None:
    assert set(codes(result)) == {"E43"} and longest(result) <= 1000


def test_every_shape_has_a_small_case():
    assert set(SMALL) == set(load_gen_corpus().SHAPES)


@pytest.mark.parametrize("shape", sorted(SMALL))
def test_hostile_shapes_hold_abuse_conditions_y(shape, tmp_path, opened, capfd):
    args, check = SMALL[shape]
    root = _hostile(tmp_path / "game", shape, *args)
    check(load_y(root, opened, capfd, todos=shape == "todo"))


# --- D9: long names sharing a prefix ------------------------------------------------------

def _long_labels(script: Path, labels: int, *, per_file: int = 1800) -> list[str]:
    """``labels`` labels of 9,000 characters sharing an 8,990-character prefix, split over
    files of at most ``per_file`` labels (16 MiB is about 1,860 of them), and 50 jumps from
    ``start`` to names one character off (each different)."""
    prefix = "a" * 8990
    names = [f"{prefix}{i:010d}" for i in range(labels)]
    jumps = [f"{prefix}b{name[8991:]}" for name in names[:50]]
    files = [names[k:k + per_file] for k in range(0, labels, per_file)]
    refs = [f"l{k:03d}.vns" for k in range(len(files))]
    body = "".join(f"    jump {j}\n" for j in jumps)
    write_tree(script, {"main.vns": "".join(f'include "{r}"\n' for r in refs)
                        + "label start:\n" + body + "    return\n"})
    for ref, chunk in zip(refs, files):
        write_tree(script, {ref: "".join(f"label {n}:\n    return\n" for n in chunk)})
    return jumps


def test_d9_near_miss_jumps_to_long_names_give_one_e43_each(tmp_path, opened, capfd):
    root = tmp_path / "game"
    jumps = _long_labels(root / "script", 200, per_file=80)
    result = load_y(root, opened, capfd)
    assert codes(result) == ["E43"] * 50 and result.error_count == 50
    assert longest(result) <= 1000
    assert "Did you mean" not in " ".join(e.format() for e in result.errors)
    assert len(set(jumps)) == 50


@pytest.mark.slow
def test_ac54_d9_twenty_thousand_long_labels(tmp_path, opened, capfd):
    root = tmp_path / "game"
    _long_labels(root / "script", 20_000)
    result = load_y(root, opened, capfd, seconds=10.0)
    assert codes(result) == ["E43"] * 50 and result.error_count == 50
    assert longest(result) <= 1000


# --- Lines that produce no statement still yield (Step 6's note 8) ----------------------

RUNS = {
    "blank": "\n",
    "spaces": "   \t \n",
    "comment": "    # just a comment\n",
    "unicode-comment": "    # café — “quoted”\n",           # read line by line
    "unicode-blank": "  \u3000 \n",                             # read line by line
    "todo": "# TODO later\n",
    "long": "#" + "x" * 10_001 + "\n",                          # E16 each
}


@pytest.mark.parametrize("kind", sorted(RUNS))
def test_a_run_of_lines_without_statements_yields(kind, tmp_path):
    n = 20_000 if kind != "long" else 600
    root = tmp_path / "game"
    write_tree(root / "script", {"main.vns": "label start:\n" + RUNS[kind] * n + "    return\n"})
    loader = StoryLoader(GamePaths(root.resolve()), LoadOptions(collect_todos=True))
    steps = 1
    while not loader.step(0.0):
        steps += 1
    # Each unit of work reads at most 2 × SCRIPT_YIELD_LINES lines (a plain run is passed
    # over 512 lines at a time), so the run alone takes at least n / 1,024 steps.
    assert steps >= n // (2 * SCRIPT_YIELD_LINES)
    result = loader.result
    if kind == "long":
        assert result.error_count == n and set(codes(result)) == {"E16"}
    else:
        assert result.program is not None and result.errors == ()
        assert result.todo_count == (n if kind == "todo" else 0)


def _line_by_line(monkeypatch) -> None:
    """Turn the fast path off: no run is ever plain."""
    monkeypatch.setattr(lexer, "_QUIET_RUN_RE", re.compile(r"(?!)"))
    monkeypatch.setattr(lexer, "_QUIET_RUN_NO_TODO_RE", re.compile(r"(?!)"))


QUIET_PIECES = (
    "\n", "    \n", "\t\n", "# c\n", "    # c\n", "        # deeper\n", "\t\t# tabbed\n",
    "# TODO a\n", "    # todo: b\n", "  #TODO\n", "# todoist\n", "## todo\n", "# x # todo\n",
    "    # café\n", "  \u3000\n", "# \u202e bidi\n", "# zero\u200bwidth\n", "#\x0b\n",
    "# \x85 nel\n", "#" + "y" * 10_001 + "\n", "#" + "z" * 9_999 + "\n",
)
STATEMENTS = ('    "Hi."\n', "    if trust:\n", "        $ trust += 1\n", "    jump start\n",
              "label more:\n", "    hana \"Yo.\"\n", "    if x:\n")


def _random_story(rng: random.Random) -> str:
    lines = ["define hana = Character(\"H\")\n", "define trust = 1\n", "label start:\n"]
    for _ in range(rng.randint(5, 60)):
        if rng.random() < 0.6:
            piece = rng.choice(QUIET_PIECES)
            lines.append(piece * rng.choice((1, 1, 2, 3, 520 if len(piece) < 100 else 4)))
        else:
            lines.append(rng.choice(STATEMENTS))
    lines.append("    return\n")
    return "".join(lines)


@pytest.mark.parametrize("todos", [False, True])
def test_the_quiet_line_fast_path_changes_nothing(todos, tmp_path, monkeypatch):
    """Plain blank and comment lines passed over in runs give exactly what reading them
    one by one gives: errors and their messages (E12's comment suffix, E16, E03, E04),
    warnings, TODOs, the program, and the statement count."""
    rng = random.Random(20261102)
    options = LoadOptions(collect_todos=todos)
    for case in range(30):
        root = tmp_path / f"g{case}"
        write_tree(root / "script", {"main.vns": _random_story(rng)})
        fast = load_story(GamePaths(root.resolve()), options)
        with monkeypatch.context() as mp:
            _line_by_line(mp)
            slow = load_story(GamePaths(root.resolve()), options)
        assert snapshot(fast) == snapshot(slow), case
        assert [(t.line, t.text) for t in fast.todos] == [(t.line, t.text) for t in slow.todos]
        assert fast.todo_count == slow.todo_count
        if fast.program is not None:
            assert program_dump(fast.program) == program_dump(slow.program)


# --- AC-F02-54: load time grows linearly (slow) -------------------------------------------

def _best_of(root: Path, runs: int) -> tuple[float, LoadResult]:
    best, result = math.inf, None
    for _ in range(runs):
        start = time.perf_counter()
        result = load_story(GamePaths(root.resolve()))
        best = min(best, time.perf_counter() - start)
    assert result is not None
    return best, result


# Sizes chosen so the size-n load takes at least about 0.2 s on the dev machine (Ryzen 9
# 5900HX), where the 16 MiB file limit allows it. ``long-line`` (one line of at most 16 MiB)
# and ``nested-if`` (its input grows with n², since each level indents 4 more, so it is
# doubled in bytes: n and n·√2) can't reach that; they take the best of 5 instead of 3.
LINEAR = {
    # ID: (shape, n, 2n, runs, check)
    "D5-continuation": ("continuation", 100_000, 200_000, 3, _clean),
    "D6-blank": ("blank", 2_000_000, 4_000_000, 3, _clean),
    "D6-cr-only": ("cr-only", 50_000, 100_000, 3, _clean),
    "D6-long-line": ("long-line", 8_000_000, 16_000_000, 5, lambda r: _one(r, "E16")),
    "D7-define-cycle": ("define-cycle", 10_000, 20_000, 3, lambda r: _one(r, "E48")),
    "D8-dup-labels": ("dup-labels", 25_000, 50_000, 3, lambda r: _one(r, "E25")),
    "D10-nested-if": ("nested-if", 1_414, 2_000, 5, lambda r: _one(r, "E15")),
}


@pytest.mark.slow
@pytest.mark.parametrize("row", sorted(LINEAR))
def test_ac54_load_time_grows_linearly(row, tmp_path, opened, capfd):
    shape, n, n2, runs, check = LINEAR[row]
    small = _hostile(tmp_path / "n", shape, "--n", str(n))
    large = _hostile(tmp_path / "2n", shape, "--n", str(n2))
    check(load_y(small, opened, capfd))
    check(load_y(large, opened, capfd))
    t_n, _ = _best_of(small, runs)
    t_2n, _ = _best_of(large, runs)
    print(f"{row}: t(n) {t_n:.3f} s, t(2n) {t_2n:.3f} s, ratio {t_2n / t_n:.2f}")
    assert t_2n <= 2.5 * t_n, (t_n, t_2n)


@pytest.mark.slow
def test_ac54_d7_a_cycle_of_100000_defines_has_no_recursion_error(tmp_path, opened, capfd):
    assert sys.getrecursionlimit() == 1000
    root = _hostile(tmp_path / "game", "define-cycle", "--n", "100000")
    _one(load_y(root, opened, capfd, seconds=60.0), "E48")


@pytest.mark.slow
def test_ac54_d10_no_recursion_past_51_block_levels(tmp_path, monkeypatch):
    from engine.script import parser

    deepest = [0]
    real = parser._Parser.parse_block

    def parse_block(self, parent_w, block_w, depth, widths):
        deepest[0] = max(deepest[0], depth)
        return (yield from real(self, parent_w, block_w, depth, widths))

    monkeypatch.setattr(parser._Parser, "parse_block", parse_block)
    root = _hostile(tmp_path / "game", "nested-if", "--n", "2000")
    _one(load_story(GamePaths(root.resolve())), "E15")
    assert deepest[0] == 50                   # depth 0 is the file; the label's block is 1


# --- D2 and D3 at 16 MiB (slow) -----------------------------------------------------------

class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _report_records(result: LoadResult) -> list[logging.LogRecord]:
    logger = logging.getLogger("vn.test.abuse")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = _Capture()
    logger.addHandler(handler)
    try:
        report_load_result(result, logger)
    finally:
        logger.removeHandler(handler)
    return handler.records


@pytest.mark.slow
def test_ac54_d2_sixteen_mib_of_todos_in_a_dev_run(tmp_path, opened, capfd):
    root = _hostile(tmp_path / "game", "todo")
    result = load_y(root, opened, capfd, todos=True, seconds=60.0)
    _clean(result)
    assert len(result.todos) == 150 and result.todo_count > 1_000_000
    records = _report_records(result)
    assert len(records) <= 200 + 1
    assert sum(r.getMessage().endswith("more TODO comments.") for r in records) == 1


@pytest.mark.slow
def test_ac54_d3_sixteen_mib_of_escape_warnings(tmp_path, opened, capfd):
    root = _hostile(tmp_path / "game", "escape-warn")
    result = load_y(root, opened, capfd, seconds=60.0)
    found = [w.code for w in result.warnings]
    assert found.count("W03") <= 50 and found.count("W03b") <= 1
    assert codes(result) == ["E06c"]          # 1,100,000 pieces pass the 250,000 limit first
    assert len(_report_records(result)) <= SCRIPT_REPORT_MAX_RECORDS


# --- AC-F02-54's regex check (slow) -------------------------------------------------------

def _module_patterns() -> list[tuple[str, re.Pattern]]:
    import importlib
    import pkgutil

    import engine.script as package

    found = []
    for info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"engine.script.{info.name}")
        for name, value in vars(module).items():
            if isinstance(value, re.Pattern):
                found.append((f"{info.name}.{name}", value))
    return found


def _adversarial(n: int) -> dict[str, str]:
    return {"a": "a" * n, "a ": "a " * (n // 2), '"\\': '"\\' * (n // 2),
            "label": "label " + "a" * n}


def _time(pattern: re.Pattern, text: str) -> float:
    best = math.inf
    for _ in range(5):
        start = time.perf_counter()
        pattern.search(text)
        pattern.match(text)
        best = min(best, time.perf_counter() - start)
    return best


@pytest.mark.slow
def test_ac54_every_module_regex_is_linear():
    patterns = _module_patterns()
    assert len(patterns) >= 20
    slow = []
    for name, pattern in patterns:
        for kind in _adversarial(10):
            t_10k = _time(pattern, _adversarial(10_000)[kind])
            t_20k = _time(pattern, _adversarial(20_000)[kind])
            # Below 0.2 ms the ratio is timer noise; such a regex is linear enough.
            if t_10k > 0.010 or t_20k > 2.5 * max(t_10k, 0.0002):
                slow.append((name, kind, round(t_10k * 1000, 3), round(t_20k * 1000, 3)))
    assert slow == []


# --- AC-F02-53: worst-case stories in 60 s and 2 GiB (perf, reference machine) -----------

WORST = {
    # ID: (shape, generator arguments, expected error)
    "D1-py-lines": ("py-lines", ("--n", "16"), "E06c"),
    "D1-narration": ("narration", ("--n", "16"), "E06b"),
    "D1-defines": ("defines", ("--n", "16"), "E06c"),
    "D1-py-total": ("py-total", ("--n", "41"), "E06d"),
    "D4-total-size": ("total-size", ("--n", "16"), "E05b"),
}


@pytest.mark.perf
@pytest.mark.parametrize("row", sorted(WORST))
def test_ac53_worst_case_stories(row, tmp_path):
    from tests.script.load_process import cpu_name, run_once

    shape, args, code = WORST[row]
    root = _hostile(tmp_path / "game", shape, *args)
    try:
        data = run_once(root, timeout=300)
    finally:
        shutil.rmtree(root, ignore_errors=True)          # up to 256 MiB per corpus
    print(f"{row} on {cpu_name()}: {data['seconds']:.2f} s, peak "
          f"{data['peak_bytes'] / MIB:.0f} MiB, errors {data['error_codes']}")
    assert data["error_codes"][0] == code and data["error_count"] == 1
    assert "Traceback" not in data["stderr"]
    assert data["seconds"] <= 60.0
    assert data["peak_bytes"] <= 2 * 1024 * MIB

"""F29 ``render/textfx.py``: the pose functions are a fixed function (AC-F29-08) and carry the
motion numbers (AC-F29-09), with ``07`` I-3's ``line_seed`` and I-4's reduce-motion floor.
Unit tier: no pygame, no window; one pair of ``python -c`` subprocesses (AC-F29-08)."""

import ast
import builtins
import json
import math
import os
import random
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from engine.render import textfx
from engine.render.textfx import (
    GLITCH_P,
    SUBSTITUTES,
    FxTime,
    amplitude,
    glitch_pick,
    line_seed,
    mix32,
    shake_unit,
    still_minimum,
    wave_unit,
)
from engine.runtime.commands import TextEffect

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "fixtures" / "F29" / "textfx_golden.toml"


def _golden() -> dict:
    with GOLDEN.open("rb") as file:
        return tomllib.load(file)


def _evaluate(table: dict) -> dict:
    """Every golden row through the module, as plain JSON values."""
    return {
        "mix32": [mix32(r["x"]) for r in table["mix32"]],
        "shake_unit": [list(shake_unit(r["index"], r["t"], r["seed"]))
                       for r in table["shake_unit"]],
        "wave_unit": [wave_unit(r["index"], r["t"]) for r in table["wave_unit"]],
        "glitch_pick": [glitch_pick(r["index"], r["t"], r["seed"], r["p"], r["still"])
                        for r in table["glitch_pick"]],
        "line_seed": [line_seed(r["sid"]) for r in table["line_seed"]],
    }


_CHILD = """
import json, sys, tomllib
sys.path.insert(0, sys.argv[1])
from tests.render.test_textfx import _evaluate
with open(sys.argv[2], "rb") as f:
    table = tomllib.load(f)
print(json.dumps({"values": _evaluate(table), "probe": hash("ZZ-hash-probe")}))
"""


# --- AC-F29-08: poses are a fixed function ---------------------------------------------------

def _golden_rows():
    table = _golden()
    assert {name: len(rows) >= 12 for name, rows in table.items()} == dict.fromkeys(
        ("mix32", "shake_unit", "wave_unit", "glitch_pick", "line_seed"), True)
    got = _evaluate(table)
    assert got["mix32"] == [r["out"] for r in table["mix32"]]
    assert got["shake_unit"] == [[r["ux"], r["uy"]] for r in table["shake_unit"]]
    assert all(abs(a - r["out"]) <= 1e-12 for a, r in zip(got["wave_unit"],
                                                           table["wave_unit"], strict=True))
    assert got["glitch_pick"] == [r["out"] for r in table["glitch_pick"]]
    assert got["line_seed"] == [r["out"] for r in table["line_seed"]]
    # Anchors (06 AC-F29-08).
    assert [mix32(x) for x in (0, 1, 2, 0xFFFFFFFF, 2**32)] == [
        0, 1753845952, 3507691905, 1734902346, 0]
    # line_seed (07 I-3): 20 bits, distinct over the table, and any string (a lone surrogate
    # from a hand-edited save) gives a value; an NVL row's seed stays within 20 bits.
    seeds = got["line_seed"]
    assert len(set(seeds)) == len(seeds) and all(0 <= s <= textfx.SEED_MASK for s in seeds)
    assert 0 <= line_seed("start/\ud800x") <= textfx.SEED_MASK
    assert all((s ^ row) <= textfx.SEED_MASK for s in seeds for row in range(32))
    assert line_seed("start/e6db5068f584") != line_seed("start/e6db5068f585")


def _hash_seeds():
    """The same rows in two fresh processes under PYTHONHASHSEED 1 and 2. (``-I`` would
    ignore PYTHONHASHSEED, so the child runs with ``-s`` and inserts the repo path itself.)"""
    children = []
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": ""}
        children.append(subprocess.Popen(
            [sys.executable, "-s", "-c", _CHILD, str(REPO), str(GOLDEN)], cwd=REPO, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"))
    outs = []
    for child in children:
        out, err = child.communicate(timeout=60)
        assert child.returncode == 0, err
        outs.append(json.loads(out.strip().splitlines()[-1]))
    assert outs[0]["probe"] != outs[1]["probe"]          # the hash seed really differed
    here = json.loads(json.dumps(_evaluate(_golden())))
    assert outs[0]["values"] == outs[1]["values"] == here


def _no_randomness(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("textfx must not use random or hash()")

    sids = [f"start/{n:012x}" for n in range(10_000)]
    with monkeypatch.context() as patch:     # undone before pytest hashes its reports
        for name in ("random", "getrandbits", "randrange"):
            patch.setattr(random, name, refuse)
        patch.setattr(random.Random, "random", refuse)
        patch.setattr(builtins, "hash", refuse)
        for n in range(10_000):
            mix32(n * 2_654_435_761)
            shake_unit(n, n * 0.013, n % 7)
            wave_unit(n, n * 0.013)
            glitch_pick(n, n * 0.013, n % 7, 0.5, n % 2 == 0)
            line_seed(sids[n])
            still_minimum(((n, 0.1), (n + 1, 0.1)), n % 7)


def _ast_scan():
    tree = ast.parse((REPO / "engine/render/textfx.py").read_text(encoding="utf-8"))
    typing_only: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING":
            for inner in ast.walk(node):
                if isinstance(inner, ast.ImportFrom):
                    typing_only.add(inner.module)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert typing_only == {"engine.runtime.commands"}
    assert imported - typing_only == {"math", "dataclasses", "typing"}      # no pygame
    for ref in ("engine/render/textfx.py", "engine/render/textbox.py", "engine/render/nvl.py"):
        tree = ast.parse((REPO / ref).read_text(encoding="utf-8"))
        names = {alias.name.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.Import) for alias in node.names}
        names |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                  if isinstance(node, ast.ImportFrom)}
        assert "random" not in names, ref
        calls = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert "hash" not in calls, ref


@pytest.mark.parametrize("row", ["golden", "hash_seeds", "no_randomness", "ast_scan"])
def test_ac_f29_08_poses_are_a_fixed_function(row, monkeypatch):
    if row == "golden":
        _golden_rows()
    elif row == "hash_seeds":
        _hash_seeds()
    elif row == "no_randomness":
        _no_randomness(monkeypatch)
    else:
        _ast_scan()


# --- AC-F29-09: motion numbers ---------------------------------------------------------------

def _amplitudes():
    shake = [amplitude(TextEffect("shake", s), 28) for s in ("small", "medium", "large")]
    wave = [amplitude(TextEffect("wave", s), 28) for s in ("small", "medium", "large")]
    assert (shake, wave) == ([1.0, 2.0, 4.0], [2.0, 3.5, 6.0])
    large = TextEffect("wave", "large")
    assert [amplitude(large, size) for size in (56, 14, 42)] == [12.0, 3.0, 9.0]
    assert abs(amplitude(large, 96) - 20.571) <= 0.001
    assert [amplitude(TextEffect("glitch", s), 28) for s in ("small", "medium", "large")] \
        == [0.10, 0.25, 0.50] == list(GLITCH_P.values())
    with pytest.raises(KeyError):
        amplitude(TextEffect("shake", "huge"), 28)
    assert SUBSTITUTES == "!#$%&*+/<=>?@\\^_|~[]"
    assert len(set(SUBSTITUTES)) == len(SUBSTITUTES) == 20 and " " not in SUBSTITUTES


def _shake_sweep(indices: range, seconds: float):
    """Each component in [−1, 1); one value per 0.05 s step (grouped by the pinned
    ``floor(t / 0.05)``), and a new value at most 20 times a second."""
    for i in indices:
        by_step: dict[int, tuple[float, float]] = {}
        for k in range(round(seconds * 600) + 1):
            t = k / 600
            ux, uy = shake_unit(i, t, 0)
            assert -1 <= ux < 1 and -1 <= uy < 1
            assert by_step.setdefault(math.floor(t / 0.05), (ux, uy)) == (ux, uy), (i, t)
        assert len(by_step) <= round(seconds * 20) + 1


def _shake_statistics():
    units = {(i, step): shake_unit(i, step * 0.05 + 0.025, 0)[0]
             for i in range(101) for step in range(100)}
    xs = [units[i, s] for i in range(100) for s in range(100)]
    assert abs(sum(xs) / len(xs)) <= 0.02
    assert abs(sum(abs(x) > 0.5 for x in xs) / len(xs) - 0.5) <= 0.02
    ys = [units[i + 1, s] for i in range(100) for s in range(100)]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    var = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    assert abs(cov / var) <= 0.05


def _wave():
    for i in (0, 1, 7, 45, 2_399):
        for k in range(0, 361, 7):
            t = k / 60
            assert abs(wave_unit(i, t) - math.sin(2 * math.pi * t / 1.0 + 0.6 * i)) <= 1e-12


def _glitch_shares():
    pairs = [(i, k * 0.12) for i in range(100) for k in range(100)]
    for p in (0.1, 0.25, 0.5):
        picks = [glitch_pick(i, t, 0, p, False) for i, t in pairs]
        assert abs(sum(k != -1 for k in picks) / len(picks) - p) <= 0.02, p
        if p == 0.5:
            assert min(picks.count(k) for k in range(20)) >= 150


def _change_instant(i: int, lo: float, hi: float) -> float:
    """The instant in (lo, hi] where glyph ``i``'s pick changes, by bisection."""
    before = glitch_pick(i, lo, 0, 0.5, False)
    for _ in range(40):
        mid = (lo + hi) / 2
        if glitch_pick(i, mid, 0, 0.5, False) == before:
            lo = mid
        else:
            hi = mid
    return hi


def _glitch_rate():
    """i 0–45 over 0–6 s: at most one change in any 0.12 s window (≤ 8.3 a second), and the
    glyphs change at their own instants (each its own phase)."""
    phases = set()
    for i in range(46):
        picks = [glitch_pick(i, k / 600, 0, 0.5, False) for k in range(3601)]
        instants = [_change_instant(i, (k - 1) / 600, k / 600)
                    for k in range(1, 3601) if picks[k] != picks[k - 1]]
        assert instants, i
        assert all(b - a >= 0.12 - 1e-6 for a, b in zip(instants, instants[1:])), i
        phases.add(round(instants[0] % 0.12, 6))
    assert len(phases) >= 40


def _still():
    """``still`` freezes step 0 for every t; reduce motion's floor (07 I-4) for a run."""
    for seed in (0, 13):
        for p in (0.1, 0.25, 0.5):
            for i in range(46):
                frozen = glitch_pick(i, 0, seed, p, False)
                assert all(glitch_pick(i, k / 60, seed, p, True) == frozen
                           for k in range(361)), (seed, p, i)
    assert FxTime(1.5) == FxTime(1.5, False) and FxTime(0.0, True).still
    # I-4: a run with no step-0 symbol shows one, at the glyph with the smallest step-0 u,
    # SUBSTITUTES[int(v × 20)]; deterministic; ties to the earlier glyph.
    seed = 0
    quiet = [i for i in range(40) if glitch_pick(i, 0, seed, 0.1, True) == -1]
    run = [(i, 0.1) for i in quiet[:6]]
    hashed = {i: textfx.h(i, 0, textfx.SALT_GLITCH_PICK, seed) for i, _ in run}
    best = min(run, key=lambda r: (textfx.u(hashed[r[0]]), r[0]))[0]
    assert still_minimum(run, seed) == (best, int(textfx.v(hashed[best]) * 20))
    assert still_minimum(iter(run), seed) == still_minimum(run, seed)
    assert still_minimum([(5, 0.1), (5, 0.1)], seed)[0] == 5
    loud = next(i for i in range(200) if glitch_pick(i, 0, seed, 0.1, True) != -1)
    assert still_minimum(run + [(loud, 0.1)], seed) is None          # already shows one
    assert still_minimum(run[:1] + [(loud, 0.5)], seed) is None      # strength change, one run
    assert still_minimum([], seed) is None                           # spaces only: nothing


@pytest.mark.parametrize("row", [
    "amplitudes",
    "shake_sweep",
    pytest.param("shake_sweep_full", marks=pytest.mark.slow),
    "shake_statistics",
    "wave",
    "glitch_shares",
    "glitch_rate",
    "still",
])
def test_ac_f29_09_motion_numbers(row):
    if row == "amplitudes":
        _amplitudes()
    elif row == "shake_sweep":                    # the default tier: a slice of the sweep
        _shake_sweep(range(0, 200, 9), 6.0)
        _shake_sweep(range(200), 0.5)
    elif row == "shake_sweep_full":               # 06's whole sweep: i 0–199 over 0–6 s
        _shake_sweep(range(200), 6.0)
    elif row == "shake_statistics":
        _shake_statistics()
    elif row == "wave":
        _wave()
    elif row == "glitch_shares":
        _glitch_shares()
    elif row == "glitch_rate":
        _glitch_rate()
    else:
        _still()

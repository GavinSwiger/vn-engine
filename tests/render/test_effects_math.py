"""F09 step 4 — effect math and the flash limiter, no window (``06-acceptance.md`` §0.2 unit;
``04`` §6.7, §6.8). AC-F09-32, AC-F09-35; the reduced flash curve of AC-F09-37."""

import logging
import random

import pytest

from engine.render.effects import (EffectLayer, FlashLimiter, RefusalLog, W61_SIDS_MAX,
                                   flash_weight)
from engine.runtime.commands import Flash, Shake


# --- AC-F09-32 — shake offsets ----------------------------------------------------------------

def test_ac_f09_32_shake_offsets():
    rows = [  # (shake, layer kwargs, t, offset)
        (Shake(None, None, None), {}, [(0, (10, 7)), (0.06, (-8, -6)), (0.125, (-5, 7)),
                                       (0.175, (5, -6)), (0.2, (6, 4)), (0.5, (0, 0)),
                                       (0.7, (0, 0))]),
        (Shake("large", "horizontal", 2.0), {}, [(0, (24, 0)), (0.06, (-23, 0))]),
        (Shake("small", "vertical", 0.5), {}, [(0, (0, 6)), (0.31, (0, 2))]),
        (Shake(None, None, None), {"shake_size": "large"}, [(0, (19, 14))]),
    ]
    for cmd, kwargs, points in rows:
        layer = EffectLayer(**kwargs)
        layer.shake(cmd, 0)
        for t, expected in points:
            assert layer.offset_units(t, reduce=False) == expected, (cmd, t)
            assert layer.offset_units(t, reduce=True) == (0, 0)


def test_ac_f09_32_bounds_determinism_restart_and_clear():
    for cmd in (Shake(None, None, None), Shake("large", "horizontal", 2.0),
                Shake("small", "vertical", 10.0), Shake("medium", None, 0.1)):
        a, b = EffectLayer(), EffectLayer()
        a.shake(cmd, 0)
        b.shake(cmd, 0)
        size = {"small": 6, "medium": 12, "large": 24}[cmd.size or "medium"]
        seconds = cmd.seconds or 0.5
        for ms in range(0, int(seconds * 1000) + 50):
            t = ms / 1000
            off = a.offset_units(t, reduce=False)
            assert max(abs(off[0]), abs(off[1])) <= size
            assert off == b.offset_units(t, reduce=False)
    layer = EffectLayer()
    layer.shake(Shake(None, None, None), 0)
    layer.shake(Shake(None, None, None), 0.2)              # restarts from its own t = 0
    assert layer.offset_units(0.2, reduce=False) == (10, 7)
    layer.clear()
    assert layer.offset_units(0.25, reduce=False) == (0, 0)


# --- AC-F09-35 — the flash limiter -------------------------------------------------------------

def test_ac_f09_35_the_flash_limiter():
    rows = [
        (False, [0, 0.1, 0.2, 0.3], "TTTF"),
        (False, [0, 0.1, 0.2, 1.0], "TTTT"),
        (False, [0, 0.1, 0.2, 0.99, 1.05, 1.15], "TTTFTT"),
        (False, [0, 0, 0, 0, 0.5], "TTTFF"),
        (True, [0, 0.5, 1.0, 1.4, 2.0], "TFTFT"),
    ]
    for reduced, times, expected in rows:
        limiter = FlashLimiter()
        got = "".join("T" if limiter.admit(t, reduced=reduced) else "F" for t in times)
        assert got == expected, (reduced, times)


def test_ac_f09_35_random_sequences_never_exceed_the_limit():
    rng = random.Random(9)
    for n in range(10_000):
        reduced = n % 4 == 0
        limit = 1 if reduced else 3
        limiter = FlashLimiter()
        t, admitted = 0.0, []
        for _ in range(12):
            t += rng.choice((0.0, rng.random() * 0.6, rng.random() * 1.5, 1.0))
            if limiter.admit(t, reduced=reduced):
                admitted.append(t)
        for i in range(len(admitted) - limit):           # any limit+1 span ≥ 1 s
            assert admitted[i + limit] - admitted[i] >= 1.0


def test_withdraw_gives_a_count_back():
    limiter = FlashLimiter()
    assert all(limiter.admit(t, reduced=False) for t in (0, 0.1, 0.2))
    limiter.withdraw(0.1)
    limiter.withdraw(5.0)                                # unknown: ignored
    assert limiter.admit(0.3, reduced=False) and not limiter.admit(0.4, reduced=False)


# --- Flash weights (AC-F09-34's curve, AC-F09-37's reduced curve) ------------------------------

def test_flash_weights():
    assert flash_weight(0, 0.3, reduced=False) == 1.0
    assert flash_weight(0.15, 0.3, reduced=False) == pytest.approx(0.5)
    assert flash_weight(0.3, 0.3, reduced=False) == 0.0
    reduced = [(0, 0.0), (0.15, 0.25), (0.3, 0.5), (0.45, 0.25), (0.6, 0.0), (0.9, 0.0)]
    for t, w in reduced:
        assert flash_weight(t, 0.3, reduced=True) == pytest.approx(w)
    assert flash_weight(0.1, 0.1, reduced=True) < 0.5    # rises over max(0.3, T)
    assert flash_weight(0.3, 0.1, reduced=True) == pytest.approx(0.5)
    assert flash_weight(1.0, 1.0, reduced=True) == pytest.approx(0.5)
    assert flash_weight(2.0, 1.0, reduced=True) == 0.0
    assert max(flash_weight(ms / 1000, 2.0, reduced=True) for ms in range(4001)) <= 0.5


def test_a_flash_replaces_the_one_in_play_and_a_refused_one_nothing(caplog):
    layer, limiter = EffectLayer(), FlashLimiter()
    assert layer.flash(Flash(None, 1.0, "a"), 0, reduce=False, limiter=limiter)
    assert layer.flash(Flash("#000000", 1.0, "b"), 0.5, reduce=False, limiter=limiter)
    assert layer.flash_weight(0.5) == 1.0                # b replaced a, from its own t = 0
    assert layer.flash(Flash(None, 1.0, "c"), 0.6, reduce=False, limiter=limiter)
    with caplog.at_level(logging.WARNING):
        assert not layer.flash(Flash(None, 1.0, "d"), 0.7, reduce=False, limiter=limiter)
        assert not layer.flash(Flash(None, 1.0, "d"), 0.8, reduce=False, limiter=limiter)
    assert layer.flash_weight(0.7) == pytest.approx(0.9)  # c still plays
    assert [r.code for r in caplog.records] == ["W61"]   # once per statement


def test_w61_remembers_at_most_1000_statements(caplog):
    log = RefusalLog(lambda sid: f"script/main.vns, line {sid}: ")
    with caplog.at_level(logging.WARNING):
        for n in range(1500):
            log.refused(str(n), "x")
        log.refused("0", "x")
    assert len(log.logged) == W61_SIDS_MAX
    assert len(caplog.records) == W61_SIDS_MAX
    assert caplog.records[0].getMessage() == "script/main.vns, line 0: x"
    caplog.clear()                                       # F28 (07 §2.2): W182 shares the set
    log = RefusalLog()
    with caplog.at_level(logging.WARNING):
        log.refused("a", "y", code="W182")
        log.refused("a", "y")
    assert [(r.code, r.getMessage()) for r in caplog.records] == [("W182", "y")]

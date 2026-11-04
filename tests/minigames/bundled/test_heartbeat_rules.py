"""F57 step 1: Heartbeat's pure rules (SPEC §4–§6): AC-F57-01 (refusals), 02 (judging), 03
(Timing assist) and 05 (ring sizes)."""

import pytest

from engine.minigames.api import StoryNames
from engine.minigames.bundled import heartbeat_rules as rules
from engine.minigames.bundled.heartbeat_rules import Beats, make_plan, ring_size
from engine.minigames.context import PlayerSettings

STORY = StoryNames(("composure", "trust"), (), ())


def timed(level: str):
    return PlayerSettings(timing_assist=level).timed


def args(**more) -> dict:
    return {**rules.DEFAULTS, **more}


# --- AC-F57-01 ---------------------------------------------------------------------------------

REFUSED = [
    (dict(beats=3), "beats must be a whole number from 4 to 20, but it is 3."),
    (dict(beats=21), "beats must be a whole number from 4 to 20, but it is 21."),
    (dict(beats=8.0), "beats must be a whole number from 4 to 20, but it is 8.0."),
    (dict(beats=True), "beats must be a whole number from 4 to 20, but it is True."),
    (dict(bpm=39), "bpm must be a whole number from 40 to 120, but it is 39."),
    (dict(bpm=121), "bpm must be a whole number from 40 to 120, but it is 121."),
    (dict(window="loose"), 'window must be "tight", "normal" or "wide", but it is "loose".'),
    (dict(meter=3), "meter must be None or a meter's name, but it is 3."),
    (dict(cost=-1), "cost must be a whole number from 0 to 20, but it is -1."),
    (dict(cost=21), "cost must be a whole number from 0 to 20, but it is 21."),
    (dict(sound=5), 'sound must be None or a sound file in quotes, such as '
                    '"sfx/heartbeat.ogg", but it is 5.'),
    (dict(sound="a\nb"), 'sound must be None or a sound file in quotes, such as '
                         '"sfx/heartbeat.ogg", but it is "a b".'),
    (dict(sound="s" * 261), 'sound must be None or a sound file in quotes, such as '
                            '"sfx/heartbeat.ogg", but it is "' + "s" * 30 + '…".'),
]


def test_ac_f57_01_refusals_and_defaults():
    assert rules.DEFAULTS == {"beats": 8, "bpm": 60, "window": "normal", "meter": None,
                              "cost": 1, "sound": None}
    assert rules.problem({}) is None and rules.problem(args()) is None
    assert rules.story_problem(args(), STORY) is None
    for changed, text in REFUSED:
        assert rules.problem(args(**changed)) == text, changed
    assert rules.problem(args(beats=4, bpm=120, window="wide", cost=20, sound="s" * 260,
                              meter="composure")) is None
    assert rules.story_problem(args(meter="composure"), STORY) is None
    assert rules.story_problem(args(meter="composre"), STORY) == (
        'meter names "composre", which no points line declares. Did you mean "composure"?')
    assert rules.story_problem(args(meter="zzz"), STORY) == (
        'meter names "zzz", which no points line declares.')


# --- AC-F57-02 ---------------------------------------------------------------------------------

def _run(plan, presses, until):
    """Feed ``presses`` (times) and advances every 1/120 s up to ``until``; the first beat's
    judgement."""
    beats = Beats(8, plan)
    t, out = 0.0, []
    pending = sorted(presses)
    while t <= until:
        while pending and pending[0] <= t + 1e-12:
            found = beats.press(pending.pop(0))
            if found is not None:
                out.append(found)
        for event in beats.advance(t):
            if event[0] != "beat":
                out.append(event)
        t += 1 / 120
    return beats, out


@pytest.mark.parametrize("bpm, window, w", [(60, "normal", 0.25), (120, "wide", 0.2)])
def test_ac_f57_02_judging(bpm, window, w):
    plan = make_plan(args(bpm=bpm, window=window), timed("normal"))
    interval = 60 / bpm
    assert (plan.lead_in, plan.interval, plan.window, plan.wait) == (1.0, interval, w, False)
    b = 1.0 + interval                                # beat 1 (lead-in, one interval)
    assert Beats(8, plan).current.time == pytest.approx(b)
    assert Beats(8, plan).current.start == pytest.approx(1.0)
    after = b + interval / 2 - 0.01                    # past the window, before the next zone
    rows = [([b - w - 0.01], ("miss", 0)),             # too soon
            ([b - w], ("hit", 0)), ([b + w], ("hit", 0)),
            ([], ("miss", 0))]                         # no press: a miss at b + w
    for presses, first in rows:
        beats, out = _run(plan, presses, b + w + 0.05)
        assert out[:1] == [first], presses
        assert beats.marks[:1] == [first[0] == "hit"]
    beats, out = _run(plan, [b, b + 0.05], b + 0.1)   # two presses: the first counts
    assert out == [("hit", 0)] and beats.marks == [True]
    beats, out = _run(plan, [after], after + 0.01)    # after the window: nothing
    assert out == [("miss", 0)] and beats.marks == [False]
    beats = Beats(8, plan)
    assert beats.press(b - interval / 2 - 0.01) is None   # before the early zone: nothing
    # Beat k falls at lead-in + k × interval when nothing changes.
    beats = Beats(4, plan)
    times = []
    t = 0.0
    while not beats.done:
        for kind, k in beats.advance(t):
            if kind == "beat":
                times.append(t)
        t += 1 / 240
    assert [round(x, 2) for x in times] == [round(1 + k * interval, 2) for k in (1, 2, 3, 4)]
    assert beats.hits == 0 and beats.misses == 4


# --- AC-F57-03 ---------------------------------------------------------------------------------

def test_ac_f57_03_timing_assist():
    normal = make_plan(args(), timed("normal"))
    slower = make_plan(args(), timed("slower"))
    assert (slower.lead_in, slower.interval, slower.window) == (
        2 * normal.lead_in, 2 * normal.interval, 2 * normal.window)
    fast = make_plan(args(bpm=120, window="wide"), timed("slower"))
    assert fast.window == pytest.approx(0.4 * fast.interval)     # still ≤ 40 %
    wait = make_plan(args(), timed("off"))
    assert wait.wait and (wait.lead_in, wait.interval) == (1.0, 1.0)

    # No time limits: rings wait on the circle; early presses do nothing; a full score.
    beats = Beats(4, wait)
    assert beats.press(1.9) is None and beats.advance(60.0) == [("beat", 0)]
    assert beats.marks == [] and ring_size(60.0, beats.current, reduce=False) == 128
    assert beats.press(60.0) == ("hit", 0)
    assert beats.current.start == 60.0 and beats.current.time == 61.0   # closes from the press
    t = 61.0
    while not beats.done:
        beats.advance(t)
        beats.press(t + 5)
        t += 6
    assert beats.hits == 4 and beats.misses == 0

    # A change applies from the next beat whose ring hasn't started.
    beats = Beats(8, normal)
    assert beats.press(2.0) == ("hit", 0)              # beat 0 at 2.0
    assert beats.current.time == 3.0
    beats.set_plan(slower, 2.05)                       # beat 1 is already closing
    assert beats.current.time == 3.0
    assert beats.press(3.0) == ("hit", 1)
    assert beats.current.start == 3.0 and beats.current.time == 5.0   # beat 2: slower
    beats.set_plan(wait, 3.5)
    assert beats.current.time == 5.0 and not beats.current.wait      # closing: unchanged
    beats.advance(5.6)                                 # beat 2 missed (window 0.5)
    assert beats.marks == [True, True, False] and beats.current.wait  # beat 3 waits
    beats = Beats(8, normal)
    beats.set_plan(slower, 0.5)                        # during the lead-in: beat 0 changes
    assert (beats.current.start, beats.current.time) == (1.0, 3.0)


# --- AC-F57-05 ---------------------------------------------------------------------------------

def test_ac_f57_05_ring_sizes():
    beat = Beats(8, make_plan(args(), timed("normal"))).current     # 1.0 → 2.0, w 0.25
    assert [ring_size(t, beat, reduce=False) for t in (1.0, 1.5, 2.0)] == [384, 256, 128]
    assert ring_size(0.2, beat, reduce=False) == 384 and ring_size(2.2, beat, reduce=False) == 128
    # Reduce motion: three sizes only, at the approach's start, halfway to the window, and
    # the whole window.
    middle = (1.0 + 1.75) / 2
    samples = [1.0, 1.2, middle - 0.01, middle, 1.6, 1.75, 2.0, 2.25]
    sizes = [ring_size(t, beat, reduce=True) for t in samples]
    assert sizes == [384, 384, 384, 256, 256, 128, 128, 128]
    assert set(ring_size(1.0 + i / 100, beat, reduce=True) for i in range(130)) == {
        384, 256, 128}
    # A small area shrinks the start size, not below 256; the group stays centered.
    assert rules.layout((0, 0, 1280, 600), 8).top == 384
    small = rules.layout((0, 100, 1280, 380), 20)
    assert small.top == 316 and small.strip[2] == 572 and small.strip[3] == 40
    assert rules.layout((0, 0, 1280, 200), 8).top == 256
    assert ring_size(1.0, beat, reduce=False, top=316) == 316
    assert rules.drawn_size(255.9) == 256 and rules.drawn_size(130) == 128
    assert [rules.text_px(s) for s in (0.5, 1.0, 1.5, 2.0)] == [20, 24, 36, 36]

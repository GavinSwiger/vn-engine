"""F19 step 3 — rollback and endings (``ending_in_progress`` in F14's ``ROLLBACK_PAUSES``, F14
07 I-4's replayed ``then``): AC-F19-30 and AC-F19-31 (moved into step 3, 07 I-10). F19 adds no
code to ``runtime/rollback.py`` (07 I-2)."""

from engine.app.story import RuntimeStoryDriver
from engine.runtime import endings
from engine.runtime.commands import (Advance, Say, StepBack, StepForward, StoryEnded,
                                     WaitDone)
from engine.runtime.interpreter import Status
from engine.runtime.rollback import ROLLBACK_PAUSES
from tests.runtime.endings_story import launched, load_e, store_with
from tests.runtime.rollback_story import forward, lands_on


def _driver(program, store=None):
    interp = launched(program, store, rollback_steps=100)
    driver = RuntimeStoryDriver(interp, clock=lambda: 0.0, fixed_seed=42)
    driver.new_game()
    driver.pump(1 << 30)
    return interp, driver


def _advance(interp, driver) -> list:
    driver.post(Advance(interp.current.sid))
    return driver.pump(1 << 30)


def _refused(interp, driver) -> None:
    """Back and forward during the ending: back refused with the cue, nothing moves."""
    t = interp.timeline
    view = driver.rollback_view()
    assert not view.can_back and view.back_room == 0 and view.ahead == 0
    refused, state, cursor = t.refused, interp.checkpoint(), t.cursor
    driver.post(StepBack(1))
    assert driver.pump(1 << 30) == []
    assert t.refused == refused + 1 and interp.checkpoint() is state and t.cursor == cursor
    driver.post(StepForward(1))
    assert driver.pump(1 << 30) == [] and t.refused == refused + 1 and t.cursor == cursor


def test_ac30_no_rollback_once_the_ending_runs(tmp_path):
    assert ROLLBACK_PAUSES.count(endings.ending_in_progress) == 1
    program = load_e(tmp_path / "r")
    interp, driver = _driver(program)
    _advance(interp, driver)                                      # at "Before."
    assert interp.current.text == "Before." and not endings.ending_in_progress(interp)
    at_before = interp.checkpoint()
    driver.post(StepBack(1))
    driver.pump(1 << 30)
    assert interp.current.text == "Start."                        # control: back works here
    _advance(interp, driver)
    assert interp.checkpoint() == at_before

    seen_in_then: list[bool] = []
    real = interp.begin_wait

    def begin_wait(*args, **kwargs):
        if kwargs.get("seconds") is not None:                     # the hold, from the then
            seen_in_then.append(endings.ending_in_progress(interp))
        return real(*args, **kwargs)
    interp.begin_wait = begin_wait

    _advance(interp, driver)                                      # the card's in phase
    assert interp.waiting_for is not None and endings.ending_in_progress(interp)
    _refused(interp, driver)
    driver.post(WaitDone(interp.waiting_for))
    driver.pump(1 << 30)                                          # the hold
    assert seen_in_then == [True]
    assert interp.waiting_for is not None and endings.ending_in_progress(interp)
    _refused(interp, driver)
    driver.post(WaitDone(interp.waiting_for))
    assert driver.pump(1 << 30) == [StoryEnded()]
    assert not endings.ending_in_progress(interp) and interp.status is Status.ENDED
    # After StoryEnded: no room, and nothing moves. "No cue" is the app's: rollback inputs
    # don't act once the story-end fade has begun (AC-F14-20), so none is posted there.
    view = driver.rollback_view()
    assert not view.can_back and view.back_room == 0
    driver.post(StepBack(1))
    assert driver.pump(1 << 30) == [] and interp.status is Status.ENDED

    # seconds 0: StoryEnded at once, then no room and no cue.
    interp, driver = _driver(load_e(tmp_path / "zero",
                                    replace={9: '    ending sad "Sad End" "Paper Ashes" 0'}))
    _advance(interp, driver)
    assert _advance(interp, driver)[-1] == StoryEnded()
    assert not endings.ending_in_progress(interp) and not driver.rollback_view().can_back
    driver.post(StepBack(1))
    assert driver.pump(1 << 30) == [] and interp.status is Status.ENDED


def test_ac31_rolling_back_over_lock_unlock_and_into_an_ending(tmp_path):
    # Back over unlock route and lock ending, then forward: nothing undone, the same result.
    store = store_with(("sad", "good"))
    program = load_e(tmp_path / "a", S='"A."⏎[4]unlock route festival_night⏎[4]'
                                       'lock ending good⏎[4]"B."')
    interp, driver = _driver(program, store)
    _advance(interp, driver)
    _advance(interp, driver)
    assert interp.current.text == "B."
    at_b = interp.checkpoint()
    store.take_new_unlocks()
    driver.post(StepBack(1))
    driver.pump(1 << 30)
    assert interp.current.text == "A."
    assert store.unlocked("route") == ("festival_night",) and store.unlocked("ending") == (
        "sad",)
    results: list = []
    for method in ("unlock", "relock"):
        real = getattr(store, method)
        setattr(store, method, lambda kind, name, _r=real, **kw: results.append(
            _r(kind, name, **kw)) or results[-1])
    released = forward(interp, 1)
    assert lands_on(interp, released, at_b)
    assert results == [False, False] and store.take_new_unlocks() == ()

    # A quiet re-run that newly reaches an ending: it records it, and nothing after it runs.
    store = store_with()
    program = load_e(tmp_path / "b", S='"A."⏎[4]if "festival_night" in persistent.routes:'
                                       '⏎[8]ending early "Early" 2⏎[4]"B."⏎[4]'
                                       'unlock route festival_night⏎[4]"C."')
    interp, driver = _driver(program, store)
    for _ in range(3):
        _advance(interp, driver)
    assert interp.current.text == "C."
    driver.post(StepBack(2))
    driver.pump(1 << 30)
    assert interp.current.text == "A."
    driver.post(StepForward(1))
    released = driver.pump(1 << 30)
    assert released == [StoryEnded()]
    assert not [c for c in released if type(c) is Say]
    assert interp.status is Status.ENDED and interp.current is None
    assert store.unlocked("ending") == ("early",)
    t = interp.timeline
    assert t.replay == 0 and not t.replaying and not driver.rollback_view().can_back

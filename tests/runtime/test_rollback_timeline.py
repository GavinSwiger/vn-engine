"""F14 step 2 — the timeline (``runtime/rollback.py``: ``record``, ``view``, ``same_step``;
the interpreter's step 4b): AC-F14-01, AC-F14-06 (with 07 I-13's pause row and the ENDED and
FAILED rows of 04 §15's view table), and AC-F14-04's runtime depth rows."""

import pytest

from engine.runtime import rollback as rollback_mod
from engine.runtime.commands import RollbackView
from engine.runtime.interpreter import Interpreter, RestoreResult, Status
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import story_game, take_all
from tests.runtime.rollback_story import back, fixture, play_to, run_k, start, step
from tests.runtime.story import fingerprint


# --- AC-F14-01 — the checkpoint objects, and no more than depth + 1 -------------------------------

def test_ac01_the_timeline_holds_the_checkpoint_objects():
    walks: list[int] = []
    compares: list[int] = []
    real_walk, real_same = Interpreter._freeze_variables, rollback_mod.same_step
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Interpreter, "_freeze_variables",
                   lambda self, stmt: (walks.append(1), real_walk(self, stmt))[1])
        mp.setattr(rollback_mod, "same_step",
                   lambda a, b: (compares.append(1), real_same(a, b))[1])
        interp = start(fixture("steps"))
        t = interp.timeline
        for n in range(8):
            assert t.states[t.cursor] is interp.checkpoint() and len(t.states) == n + 1
            if n < 7:
                step(interp)
    assert len(walks) == 8 and compares == []
    interp, k = run_k("A", depth=3)
    t = interp.timeline
    sizes = [len(t.states)]
    for _ in range(7):
        step(interp)
        sizes.append(len(t.states))
    assert sizes == [1, 2, 3, 4, 4, 4, 4, 4] and t.cursor == 3 and t.shown == 3
    _, k = run_k("F")
    assert [s.position for s in t.states] == [k[x].position for x in ("D1", "D2", "S", "F")]
    zero, _ = run_k("F", depth=0)
    assert zero.timeline.states == [] and zero.timeline.cursor == -1
    assert zero.timeline.view(zero) == RollbackView(False, False, 0, 0, 0)
    before = fingerprint(zero)
    assert back(zero, 1) == [] and fingerprint(zero) == before
    assert zero.timeline.refused == 0


# --- AC-F14-06 — where back stops ----------------------------------------------------------------

def _loaded_at_c():
    interp, k = run_k("D2")
    assert interp.restore(round_trip(k["C"])).result is RestoreResult.OK
    take_all(interp)
    return interp


def _title_new_game():
    interp, _ = run_k("D2")
    interp.new_game(42)
    interp.run(10_000)
    take_all(interp)
    return interp


def _walls_at(text: str):
    def make():
        interp = start(fixture("walls"))
        play_to(interp, text)
        take_all(interp)
        return interp
    return make


def _depth_limit():
    interp, _ = run_k("F", depth=3)
    back(interp, 3)
    assert interp.current.text == "Wade one."
    return interp


def _paused():                                         # A2: a minigame_used-style pause
    interp, _ = run_k("D2")
    back(interp, 1)                                     # one step ahead, hidden by the pause
    rollback_mod.ROLLBACK_PAUSES.append(_PAUSE)
    return interp


def _ended():
    interp, _ = run_k("F")
    step(interp)
    take_all(interp)
    assert interp.status is Status.ENDED
    return interp


def _failed():
    interp, _ = run_k("C")
    interp.fail_timeout()
    take_all(interp)
    return interp


def _PAUSE(interp) -> bool:
    return True


def test_ac06_where_back_stops():
    starts = [lambda: run_k("A")[0], _loaded_at_c, _title_new_game, _walls_at("B1."),
              _walls_at("C1."), _walls_at("C2."), _depth_limit, _paused, _ended, _failed]
    try:
        for make in starts:
            interp = make()
            view = interp.timeline.view(interp)
            assert not view.can_back and view.back_room == 0, make
            assert make is not _paused or view.ahead == 0       # 07 I-13
            before, refused = fingerprint(interp), view.refused
            assert back(interp, 1) == [] and fingerprint(interp) == before, make
            assert interp.timeline.refused == refused + 1, make
    finally:
        if _PAUSE in rollback_mod.ROLLBACK_PAUSES:
            rollback_mod.ROLLBACK_PAUSES.remove(_PAUSE)


# --- AC-F14-04's runtime rows: the depth bound on a long linear story ----------------------------

@pytest.mark.slow
def test_ac04_depth_bound_on_linear_play(tmp_path):
    """The size row only (depth 1000): the default depth-100 run is in
    ``tests/app/test_rollback_install.py::test_ac04_rollback_steps``, the bound in AC-F14-01."""
    depth = 1000
    program = story_game(tmp_path, [f'"Line {i}."' for i in range(depth + 5)])
    interp = start(program, rollback_steps=depth)
    for _ in range(depth + 4):
        step(interp)
    t = interp.timeline
    assert len(t.states) == depth + 1 and t.view(interp).back_room == depth
    back(interp, depth)
    assert t.cursor == 0 and t.view(interp).back_room == 0
    back(interp, 1)
    assert t.refused == 1


# --- 07 I-11 — dropped states freed a few per frame (the App's deferred release) -----------------

def test_i11_deferred_release_queues_and_frees_a_few_per_call():
    interp, _ = run_k("F")
    states = interp.timeline.states[:4]                 # four different checkpoints
    assert len({id(s) for s in states}) == 4
    now = rollback_mod.Timeline(2)                       # the default: freed at once
    for s in states:
        now.record(s)
    assert len(now.states) == 3 and now.dropped == 0 and now.release() == 0
    t = rollback_mod.Timeline(2)
    t.defer_release = True
    for s in states:
        t.record(s)                                      # the depth trims the oldest
    assert t.states == states[1:] and t.dropped == 1
    t.reset(None)                                        # a drop before the queue is empty
    assert t.states == [] and t.dropped == 3             # bound: one full timeline (depth + 1)
    assert t.release(2) == 2 and t.dropped == 1
    t.record(states[0])
    t.drop_through(0)                                    # PR-F14-23's drop is queued too
    assert t.states == [] and t.cursor == -1 and t.dropped == 2
    assert t.release(None) == 2 and t.dropped == 0 and t.release() == 0

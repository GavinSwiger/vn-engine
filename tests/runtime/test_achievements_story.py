"""F37 S2: achievements in the interpreter (``Interpreter.__init__``'s ``register``,
``take_checkpoint`` step 2d and ``_end`` step 1, ``unlock achievement`` through F19's
``run_lock``): AC-F37-03 (the line), AC-F37-04 (headless) and AC-F37-14.

Story A: ``first_steps`` is given by a line (twice); ``river`` unlocks when ``seen_river``
is true (set after "Two."); ``done`` when the ``good`` ending is reached (at the story's
end); ``never`` is never true; ``oops`` raises ``NameError`` (W223)."""

import logging
import time

from engine.runtime import achievements as achievements_mod
from engine.runtime.achievements import ACHIEVEMENT_KIND
from engine.runtime.interpreter import Status
from engine.runtime.persistent import PersistentStore
from engine.script.messages import format_message
from tests.runtime.endings_story import launched
from tests.runtime.rollback_story import back, forward
from tests.runtime.story import advance, end_waits, load_files
from tests.script.message_cases import load_cases

STORY_A = '''default seen_river = False
lock achievement first_steps "First Steps" "Finish the prologue."
lock achievement river "River" when seen_river
lock achievement done "Done" hidden when "good" in persistent.endings
lock achievement never "Never" when seen_river and False
lock achievement oops "Oops" when missing_name > 1
label start:
    "One."
    unlock achievement first_steps
    "Two."
    unlock achievement first_steps
    $ seen_river = True
    "Three."
    ending good "Good End"
'''


def _shown(interp) -> str:
    return interp.current.text if interp.current is not None else ""   # type: ignore


def _held(store: PersistentStore) -> list[str]:
    return list(store.unlocked(ACHIEVEMENT_KIND))


def test_ac_f37_03_04_story_a(tmp_path, caplog):
    """AC-F37-03: ``unlock achievement`` records once (the second line adds nothing) and is
    kept. AC-F37-04: a ``when`` unlocks at the first checkpoint where it is true (before the
    snapshot), and at the story's end after an ``ending``; each checkpoint evaluates only the
    pending ones; a raising condition gives W223 once, is dropped, and the story goes on."""
    program = load_files(tmp_path, {"main.vns": STORY_A})
    assert [a.name for a in program.achievements] == ["first_steps", "river", "done", "never",
                                                      "oops"]
    store = PersistentStore(identity_scheme=program.identity_scheme)
    caplog.set_level(logging.WARNING, logger="vn.story")
    interp = launched(program, store)
    interp.new_game(42)
    interp.run(10_000)
    achievements = interp.achievements
    assert _shown(interp) == "One." and _held(store) == []
    # "One.": river, done, never, oops evaluated; oops fails and is dropped.
    assert achievements.evaluations == 4 and achievements.pending == ("river", "done", "never")
    advance(interp)
    assert _shown(interp) == "Two." and _held(store) == ["first_steps"]
    assert achievements.evaluations == 7
    assert store.take_new_unlocks() == (("achievement", "first_steps"),)
    advance(interp)                               # the second unlock line: nothing new
    assert _shown(interp) == "Three."
    assert sorted(_held(store)) == ["first_steps", "river"]
    assert store.take_new_unlocks() == (("achievement", "river"),)
    assert interp.checkpoint() is not None and achievements.evaluations == 10
    assert achievements.pending == ("done", "never")
    advance(interp)                               # the ending's card, then the end
    end_waits(interp)
    assert interp.status is Status.ENDED
    assert sorted(_held(store)) == ["done", "first_steps", "river"]
    assert store.take_new_unlocks() == (("ending", "good"), ("achievement", "done"))
    w223 = [r.getMessage() for r in caplog.records if getattr(r, "code", None) == "W223"]
    assert w223 == ["script/main.vns, line 6: " + format_message("W223", ("oops", "NameError"))]
    row = next(c for c in load_cases() if c.id == "F37-04-W223")
    assert row.expect["exact"] == format_message("W223", ("completionist", "NameError"))
    # New Game keeps them; a second playthrough evaluates only "never" (oops stays dropped).
    interp.new_game(43)
    interp.run(10_000)
    assert sorted(_held(store)) == ["done", "first_steps", "river"]
    assert achievements.pending == ("never",) and len(w223) == 1


def test_ac_f37_04_not_in_rollback_replay(tmp_path):
    """AC-F37-04: F14's quiet forward re-run checks no condition (07 I-14)."""
    program = load_files(tmp_path, {"main.vns": STORY_A})
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    advance(interp)
    advance(interp)
    assert _shown(interp) == "Three."
    back(interp, 2)
    assert _shown(interp) == "One."
    before = interp.achievements.evaluations
    forward(interp, 2)
    assert _shown(interp) == "Three."
    assert interp.achievements.evaluations == before


def test_ac_f37_14_64_pending_conditions_cost(tmp_path):
    """AC-F37-14 (Should): 64 pending simple conditions add at most 1 ms per checkpoint."""
    decls = "\n".join(f'lock achievement a{i} "A{i}" when count == {1000 + i}'
                      for i in range(64))
    program = load_files(tmp_path, {"main.vns": "default count = 0\n" + decls +
                                    '\nlabel start:\n    "One."\n'})
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    assert len(interp.achievements.pending) == 64
    best = float("inf")
    for _ in range(50):
        started = time.perf_counter()
        achievements_mod.check_pending(interp)
        best = min(best, time.perf_counter() - started)
    assert len(interp.achievements.pending) == 64
    assert best <= 0.001, f"{best * 1000:.3f} ms"

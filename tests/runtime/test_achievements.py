"""F37 step 1 (pure): ``runtime/achievements.py`` on fakes.

AC-F37-03 (the store half: the kind records once, is never revocable, survives New Game and
``_clear(progress=True)``, and F16's reset empties it; the ``unlock achievement`` line itself
goes through F19's ``run_lock`` in F37-S2, 07 I-12) and AC-F37-04's unit half
(``check_pending`` on a fake interpreter: first true check, only pending ones evaluated,
raising and watchdog conditions give W223 once and are dropped). AC-F37-04's headless rows
(checkpoints, story end after an ``ending``, never in replay) are F37-S2's.
"""

import logging
from types import SimpleNamespace

import pytest

from engine.runtime import achievements
from engine.runtime.achievements import ACHIEVEMENT_KIND, register
from engine.runtime.persistent import PersistentStore


def decl(name, title, *, when=None, hidden=False, line=1):
    return SimpleNamespace(name=name, title=title, description="", image=None, hidden=hidden,
                           when=when, line=line, file=SimpleNamespace(ref="database.vns"),
                           when_code=None if when is None else compile(when, "<when>", "eval"))


class Guard:
    """The watchdog seam: ``fire`` makes the next ``consume_fired`` True."""

    def __init__(self) -> None:
        self.fired = False
        self.entries = 0

    def enter(self) -> None:
        self.entries += 1

    def exit(self) -> None:
        pass

    def consume_fired(self) -> bool:
        fired, self.fired = self.fired, False
        return fired


class FakeInterp:
    """What ``register`` and ``check_pending`` read: program, persistent, ``_test``, guard."""

    def __init__(self, decls, store: PersistentStore | None = None) -> None:
        self.program = SimpleNamespace(achievements=list(decls))
        self.persistent = store or PersistentStore(identity_scheme=1)
        self.guard = Guard()
        self.G: dict = {"flag": False}
        self.tests: list[str] = []

    def _test(self, code) -> bool:
        self.guard.enter()
        try:
            self.tests.append(code.co_names[0])                      # one-name conditions
            if "stuck" in code.co_names:
                self.guard.fired = True
                raise KeyboardInterrupt
            return bool(eval(code, self.G))
        finally:
            self.guard.exit()


def test_ac_f37_03_the_kind_records_once_is_permanent_and_only_reset_clears_it():
    interp = FakeInterp([decl("first_steps", "First Steps"), decl("garden", "Secret Garden")])
    store = interp.persistent
    register(interp)
    register(interp)                                          # safe to repeat (F39)
    assert [i.name for i in interp.achievements.index] == ["first_steps", "garden"]
    assert interp.achievements.index.get("garden").identity == "achievement:garden"
    assert not store.is_revocable(ACHIEVEMENT_KIND)
    assert store.unlock(ACHIEVEMENT_KIND, "first_steps") is True     # the line (run_lock)
    assert store.unlock(ACHIEVEMENT_KIND, "first_steps") is False    # again: nothing
    assert store.take_new_unlocks() == ((ACHIEVEMENT_KIND, "first_steps"),)
    with pytest.raises(ValueError):
        store.relock(ACHIEVEMENT_KIND, "first_steps")                # relock refused
    assert store.unlocked(ACHIEVEMENT_KIND) == ("first_steps",)
    store.clear(progress=True)                                       # New Game / _clear
    assert store.is_unlocked(ACHIEVEMENT_KIND, "first_steps")
    assert [i.name for i in interp.achievements.index.unlocked(store)] == ["first_steps"]
    assert interp.achievements.index.has("garden") and not interp.achievements.index.has(3)
    store.reset()                                                    # F16
    assert store.unlocked(ACHIEVEMENT_KIND) == ()


def test_ac_f37_04_check_pending_unlocks_true_ones_and_drops_failing_ones(caplog):
    caplog.set_level(logging.WARNING, logger="vn.story")
    interp = FakeInterp([
        decl("first_steps", "First Steps"),                          # by a line only
        decl("flagged", "Flagged", when="flag", line=3),
        decl("typo", "Typo", when="flgg", line=4),
        decl("loop", "Loop", when="stuck", line=5),
        decl("given", "Given", when="flag", line=6),
    ])
    store = interp.persistent
    ach = register(interp)
    assert ach.pending == ("flagged", "typo", "loop", "given")
    assert achievements.check_pending(interp) == ()
    assert interp.tests == ["flag", "flgg", "stuck", "flag"]         # each pending once
    w223 = [r.getMessage() for r in caplog.records if getattr(r, "code", None) == "W223"]
    assert w223 == [
        "database.vns, line 4: achievement typo's when condition failed (NameError), so it "
        "isn't checked again until the game restarts.",
        "database.vns, line 5: achievement loop's when condition failed (it ran too long), so "
        "it isn't checked again until the game restarts."]
    assert ach.pending == ("flagged", "given")
    store.unlock(ACHIEVEMENT_KIND, "given")                          # given by a line meanwhile
    interp.tests.clear()
    interp.G["flag"] = True
    assert achievements.check_pending(interp) == ("flagged",)
    assert interp.tests == ["flag"]                                  # "given" not evaluated
    assert store.unlocked(ACHIEVEMENT_KIND) == ("given", "flagged")
    interp.tests.clear()
    assert achievements.check_pending(interp) == () and interp.tests == []
    assert len([r for r in caplog.records if getattr(r, "code", None) == "W223"]) == 2
    store.reset()                                   # F16: locked again; failed ones stay out
    assert ach.pending == ("flagged", "given")
    assert achievements.check_pending(interp) == ("flagged", "given")
    interp.guard.fired = False

    class CtrlC(FakeInterp):
        def _test(self, code) -> bool:
            raise KeyboardInterrupt                                  # not the watchdog

    real = CtrlC([decl("x", "X", when="flag")])
    register(real)
    with pytest.raises(KeyboardInterrupt):
        achievements.check_pending(real)

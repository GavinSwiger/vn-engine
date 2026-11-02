"""F19 step 3 — endings and routes in the story, headless (``runtime/endings.py``'s executors
and views; ``Interpreter.end_story``): AC-F19-09, 10, 11, 12, 14, 15, 18, 22, 24.

Run R is ``run_headless(program, seed=42, persistent=store)`` (``run_e``); Driver D is
``RuntimeStoryDriver`` with a fake clock (``drive``). AC-F19-23's windowed rows and the
``--no-persistent``/READ_ONLY sessions are step 4's."""

import logging

from engine.runtime.commands import (Advance, PrefetchImages, Say, ShowMenu, ShowStage,
                                     StoryEnded, StoryFailed, StoryWait, TitleCard,
                                     TransitionSpec)
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.values import freeze
from engine.script.messages import format_message
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import bursts
from tests.runtime.endings_story import (drive, ends, launched, load_e, run_e, started,
                                         store_with, walk)
from tests.persist.writer_support import base, game  # noqa: F401
from tests.runtime.story import end_waits, texts

FADE = dict(kind="fade", name="fade", seconds=None, color=None, mask=None, soft=0.1,
            reverse=False, direction=None)


def _after(commands, text: str) -> list:
    """The commands after the line ``text`` and its prefetch."""
    at = next(i for i, c in enumerate(commands) if type(c) is Say and c.text == text)
    rest = commands[at + 1:]
    while rest and type(rest[0]) is PrefetchImages:
        rest = rest[1:]
    return rest


def _ending_sid(program, name: str) -> str:
    return next(e.sid for e in program.endings if e.name == name)


# --- AC-F19-09 — the ending's commands ----------------------------------------------------------

def test_ac09_the_endings_commands(tmp_path):
    rows = [
        (None, 3.0, "fade", None, "Sad End"),
        ('[4]ending sad "Sad End" "Paper Ashes" 5 with dissolve 1.5', 5.0, "dissolve", 1.5,
         "Sad End"),
        ('[4]ending sad "Paper Ashes"', 3.0, "fade", None, None),
        ('[4]ending sad "Sad End" "Paper Ashes" 0', None, None, None, None),
    ]
    for n, (r9, hold, name, seconds, heading) in enumerate(rows):
        program = load_e(tmp_path / str(n), replace={9: r9} if r9 else None)
        sid = _ending_sid(program, "sad")
        seen: list = []

        def setup(interp):
            real = interp.persistent.unlock

            def spy(kind, name, **kw):
                result = real(kind, name, **kw)
                held = list(interp._held) + list(interp._released)
                seen.append((kind, name, result,
                             any(type(c) is ShowStage and c.card for c in held)))
                return result
            interp.persistent.unlock = spy

        interp, commands = drive(program, setup=setup)
        assert seen == [("ending", "sad", True, False)], r9
        out = bursts(_after(commands, "Before."))
        assert ends(commands, interp), r9
        assert not any(type(c) is ShowStage and c.card is None for c in _after(commands,
                                                                               "Before."))
        assert "ChapterStarted" not in {type(c).__name__ for c in commands}
        if hold is None:
            assert out == [[StoryEnded()]], r9
            continue
        assert len(out) == 3, (r9, out)
        stage, wait = out[0]
        assert stage.card == TitleCard("sad", heading, "Paper Ashes", kind="ending")
        if name == "fade":
            assert stage.transition == TransitionSpec(sid=sid, **FADE)
        else:
            assert (stage.transition.name, stage.transition.seconds) == (name, seconds)
        assert (type(wait), wait.sid, wait.for_stage, wait.hide_box, wait.seconds) == (
            StoryWait, sid, True, True, None)
        [hold_wait] = out[1]
        assert (hold_wait.seconds, hold_wait.for_stage, hold_wait.sid) == (hold, False, sid)
        assert out[2] == [StoryEnded()]


# --- AC-F19-10 — the story ends wherever the ending is ----------------------------------------

def test_ac10_the_story_ends_wherever_the_ending_is(tmp_path, caplog):
    def run(name, choices=(), **edit):
        store = store_with()
        program = load_e(tmp_path / name, **edit)
        interp, commands = drive(program, store, choices=choices)
        assert ends(commands, interp), name
        return texts(commands), store.unlocked("ending")

    assert run("call", S="call side", T='label side:⏎[4]"Side."⏎[4]ending side_end "Side"') == (
        ["Start.", "Side."], ("side_end",))
    menu = 'menu:⏎[8]"Leave":⏎[12]ending leave "Leave"⏎[8]"Stay":⏎[12]"Ok."'
    assert run("leave", (1,), S=menu) == (["Start."], ("leave",))
    assert run("stay", (2,), S=menu) == (["Start.", "Ok.", "Before."], ("sad",))
    warm = 'if trust > 0:⏎[8]ending warm "Warm"'
    assert run("cold", S=warm) == (["Start.", "Before."], ("sad",))
    assert run("warm", S=warm, replace={4: "default trust = 1"}) == (["Start."], ("warm",))
    with caplog.at_level(logging.WARNING):
        assert run("jump", S="jump promise") == (["Start.", "Promise."], ("true",))
    assert caplog.records == []

    # The same ending twice on one store: equal commands, nothing new the second time.
    program = load_e(tmp_path / "twice")
    store = store_with()
    first = run_e(program, store)
    assert store.take_new_unlocks() == (("ending", "sad"),)
    results = []
    real = store.unlock
    store.unlock = lambda kind, name, **kw: results.append(real(kind, name, **kw)) or results[-1]
    assert run_e(program, store) == first and results == [False]
    assert store.take_new_unlocks() == ()


# --- AC-F19-11 — lock and unlock at run time -----------------------------------------------------

def _plays(program, store):
    """Driver D's commands and the checkpoint at every line."""
    states: list = []
    interp, commands = drive(program, store, on_line=lambda i: states.append(i.checkpoint()))
    return interp, commands, states


def test_ac11_lock_and_unlock_at_run_time(tmp_path):
    _, base_commands, base_states = _plays(load_e(tmp_path / "base"), store_with())
    rows = [
        ((), (), 'unlock route festival_night⏎[4]if "festival_night" in persistent.routes:'
                 '⏎[8]"Open."', "unlock", True),
        ((), ("festival_night",), "unlock route festival_night", "unlock", False),
        ((), ("festival_night",), "lock route festival_night", "relock", True),
        (("sad", "good"), (), "lock ending good", "relock", True),
        (("sad",), (), "lock ending good", "relock", False),
    ]
    for n, (e, r, S, method, returned) in enumerate(rows):
        store = store_with(e, r)
        results: list = []
        real = getattr(store, method)

        def spy(kind, name, _real=real, **kw):
            before = store.version
            results.append((kind, name, _real(kind, name, **kw), store.version - before))
            return results[-1][2]
        setattr(store, method, spy)
        interp, commands, states = _plays(load_e(tmp_path / str(n), S=S), store)
        kind = "route" if "route" in S else "ending"
        name = "good" if kind == "ending" else "festival_night"
        assert results[0] == (kind, name, returned, 1 if returned else 0), S
        if n == 0:
            assert "Open." in texts(commands)
            assert store.unlocked("route") == ("festival_night",)
            assert store.take_new_unlocks()[-2] == ("route", "festival_night")
            continue
        assert commands == base_commands, S
        assert [s.position for s in states] == [s.position for s in base_states]
        assert [s.variables for s in states] == [s.variables for s in base_states]
        new = [u for u in store.take_new_unlocks() if u[0] == "route"]
        assert new == []
        if n == 2:
            assert store.unlocked("route") == ()
        if n == 3:
            assert store.unlocked("ending") == ("sad",)


# --- AC-F19-12 — W132 -----------------------------------------------------------------------------

def test_ac12_w132(tmp_path, caplog):
    program = load_e(tmp_path / "r", S="lock route promise⏎[4]lock route promise")
    text = ("script/main.vns, line 7: lock route promise has no effect while its until endings "
            "(sad, good) are reached. Lock one of those endings too, or remove until.")
    for e, dev, expected in ((("sad", "good"), True, [text]), (("sad",), True, []),
                             (("sad", "good"), False, [])):
        caplog.clear()
        store = store_with(e)
        with caplog.at_level(logging.WARNING):
            commands = run_e(program, store, dev=dev)
        assert ends(commands)
        found = [r for r in caplog.records if "lock route promise" in r.getMessage()]
        assert [r.getMessage() for r in found] == expected, (e, dev)
        assert all(r.name == "vn.story" for r in found)
        if expected:
            assert "promise" in store.get("routes")
    assert format_message("W132", ("promise", ("sad", "good"))) in text


# --- AC-F19-14 — reading persistent.endings and persistent.routes ----------------------------------

def test_ac14_reading_the_views(tmp_path):
    def play(e, S):
        interp, commands, states = _plays(load_e(tmp_path / S[:12].replace(" ", "_").replace(
            "$", "d").replace(".", "_").replace("=", "q"), S=S), store_with(e))
        assert ends(commands, interp), S
        return interp.G, states

    G, _ = play(("good", "sad"), "$ e = persistent.endings")
    assert G["e"] == ["good", "sad"] and type(G["e"]) is list
    G, states = play(("good", "sad"), '$ seen = persistent.endings⏎[4]$ seen.append("x")⏎[4]'
                                      "$ again = persistent.endings")
    assert G["again"] == ["good", "sad"]
    before = states[1]                                                 # at "Before."
    assert before.variables["seen"] == ["good", "sad", "x"]
    assert round_trip(before).variables["seen"] == ["good", "sad", "x"]
    G, _ = play(("sad", "good"), "$ a = persistent.routes⏎[4]$ b = persistent.routes")
    assert G["a"] == G["b"] == ["promise"] and G["a"] is not G["b"]
    G, _ = play(("sad", "old"), "$ n = len(persistent.endings)")
    assert G["n"] == 1

    # TR-F19-04: every read a new list that freeze accepts; changing it changes nothing.
    program = load_e(tmp_path / "unit")
    for e, r in (((), ()), (("sad",), ("festival_night",)), (("sad", "good", "zz"), ())):
        store = store_with(e, r)
        launched(program, store)
        for view in ("endings", "routes"):
            a, b = store.get(view), store.get(view)
            assert type(a) is list and a == b and a is not b
            freeze(a)
            a.append("x")
            assert store.get(view) == b


# --- AC-F19-15 — writes the load check can't see ---------------------------------------------------

def test_ac15_writes_the_load_check_cant_see(tmp_path):
    rows = [
        ('$ n = "endings"⏎[4]$ setattr(persistent, n, [])', ("change", "endings")),
        ('$ n = "routes"⏎[4]$ delattr(persistent, n)', ("change", "routes")),
    ]
    for n, (S, args) in enumerate(rows):
        store = store_with(("sad", "good"))
        commands = run_e(load_e(tmp_path / f"f{n}", S=S), store)
        failed = commands[-1]
        assert type(failed) is StoryFailed, S
        error = failed.error
        assert (error.code, error.line, error.message) == ("E245", 8, format_message("E245",
                                                                                      args))
        assert store.unlocked("ending") == ("sad", "good") and store.get("routes") == [
            "promise"]                              # unchanged (a seen mark is no change)
        assert store.values_snapshot() == {"playthrough": 0}       # F32's built-in only

    for n, S in enumerate(('$ getattr(persistent, "endings").append("x")⏎[4]'
                           "$ after = persistent.endings",
                           '$ e = persistent.endings⏎[4]$ e.append("x")⏎[4]'
                           "$ after = persistent.endings")):
        interp, commands = drive(load_e(tmp_path / f"ok{n}", S=S), store_with(("sad",)))
        assert ends(commands, interp) and interp.G["after"] == ["sad"], S

    commands = run_e(load_e(tmp_path / "define", T="define t = persistent.endings"))
    assert type(commands[-1]) is StoryFailed
    assert [e.code for e in commands[-1].error.errors] == ["E185"]
    interp, commands = drive(load_e(tmp_path / "lambda", T="define t = lambda: len("
                                    "persistent.endings)", S="$ k = t()"),
                             store_with(("sad", "good")))
    assert ends(commands, interp) and interp.G["k"] == 2


# --- AC-F19-18 — records outlive everything but lock and reset ---------------------------------------

def test_ac18_records_outlive_everything_but_lock_and_reset(tmp_path, game):
    def records(store):
        return store.unlocked("ending"), store.unlocked("route")

    for S in ("$ persistent._clear()", "$ persistent._clear(progress=True)"):
        store = store_with(("sad",), ("festival_night",))
        interp, commands = drive(load_e(tmp_path / str(len(S)), S=S), store)
        assert records(store) == (("sad",), ("festival_night",)), S
        assert ends(commands, interp)

    store = store_with(("sad",), ("festival_night",))
    launched(load_e(tmp_path / "reset"), store)
    store.unlock("route", "promise")
    store.reset()
    assert records(store) == ((), ()) and store._unlock_changed == {}

    # A restore (a load) of a checkpoint taken before ``unlock route promise`` ran; New Game.
    store = store_with(("sad",), ("festival_night",))
    states: list = []
    interp, _ = drive(load_e(tmp_path / "load", S="unlock route promise"), store,
                      on_line=lambda i: states.append(i.checkpoint()))
    assert interp.restore(round_trip(states[0])).result is RestoreResult.OK
    assert records(store) == (("sad",), ("festival_night", "promise"))
    interp.new_game(42)
    interp.run(10_000)
    assert records(store) == (("sad",), ("festival_night", "promise"))

    # lock ending sad, then at "Mid." restore the checkpoint at "Start.": sad stays forgotten.
    store = store_with(("sad",))
    interp = started(load_e(tmp_path / "mid", S='lock ending sad⏎[4]"Mid."'), store)
    at_start = interp.checkpoint()
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    assert interp.current.text == "Mid." and store.unlocked("ending") == ()
    assert interp.restore(at_start).result is RestoreResult.OK
    assert store.unlocked("ending") == ()

    # Harness Y with Driver D stopped in the card's hold: on disk within 2.0 s.
    from tests.persist.sync_support import Harness
    program = load_e(tmp_path / "disk")
    h = Harness(game / "persistent", game=game, program=program)
    interp = started(program, h.store)
    for _ in range(2):
        interp.post(Advance(interp.current.sid))
        interp.run(10_000)
        if interp.waiting_for is not None:
            break
    from engine.runtime.commands import WaitDone
    interp.post(WaitDone(interp.waiting_for))                 # the in phase ends: the hold
    interp.run(10_000)
    assert interp.status is Status.WAITING and interp.waiting_for is not None
    assert not any(type(c) is StoryEnded for c in interp.take_commands(1 << 30))
    h.ticks(2.0)
    assert h.disk()["unlocks"]["ending"] == ["sad"]
    end_waits(interp)
    assert interp.status is Status.ENDED


# --- AC-F19-22 — same story whatever the card does --------------------------------------------------

def _walk_runs(play):
    store = store_with()
    out = []
    for choice in (1, 2, 3):
        out.append((play(store, choice), store.unlocked("ending"), store.unlocked("route")))
    return out


def test_ac22_same_story_whatever_the_card_does():
    program = walk()

    def headless(store, choice):
        return run_e(program, store, inputs=["advance", f"choose {choice}"], show_locked=True)

    def driver(pumps):
        def play(store, choice):
            return drive(program, store, choices=(choice,), wait_pumps=pumps,
                         show_locked=True)[1]
        return play

    def finish_now(store, choice):
        """F09's ``finish_now`` (a press: ``finish_wait``) on each wait."""
        interp = started(program, store, show_locked=True)
        out = interp.take_commands(1 << 30)
        picks = iter((choice,))
        while interp.status is Status.WAITING:
            if interp.waiting_for is not None:
                interp.finish_wait()
            elif type(interp.current).__name__ == "Menu":
                from engine.runtime.commands import Choose
                n = next(picks)
                interp.post(Choose(interp.current.sid, interp.choices.waiting.pickable[n - 1]))
            else:
                interp.post(Advance(interp.current.sid))
            interp.run(10_000)
            out += interp.take_commands(1 << 30)
        return out

    expected = _walk_runs(headless)
    assert [r[1] for r in expected] == [("sad",), ("sad", "good"), ("true",)]
    for play in (driver(30), driver(0), finish_now):
        assert _walk_runs(play) == expected


# --- AC-F19-24 — the Paper Lanterns walkthrough ---------------------------------------------------

def test_ac24_the_paper_lanterns_walkthrough():
    program = walk()
    store = store_with()

    def run(inputs):
        commands = run_e(program, store, inputs=inputs, show_locked=True)
        [menu] = [c for c in commands if type(c) is ShowMenu]
        return commands, [c.locked for c in menu.choices]

    commands, locked = run(["advance", "choose 1"])
    assert ends(commands) and locked == [False, False, True]
    assert store.unlocked("ending") == ("sad",) and store.get("routes") == []
    assert store.take_new_unlocks() == (("ending", "sad"),)

    menu_states: list = []
    interp, commands = drive(program, store, choices=(2,), show_locked=True,
                             on_line=lambda i: menu_states.append(i.checkpoint()))
    assert ends(commands, interp)
    [menu] = [c for c in commands if type(c) is ShowMenu]
    assert [c.locked for c in menu.choices] == [False, False, True]
    assert store.unlocked("ending") == ("sad", "good") and store.get("routes") == ["promise"]
    store.take_new_unlocks()

    commands, locked = run(["advance", "choose 3"])
    assert ends(commands) and locked == [False, False, False]
    assert "You came." in texts(commands)
    assert store.unlocked("ending") == ("true",) and store.get("routes") == []
    assert store.get("playthrough") == 2
    assert store.take_new_unlocks() == (("ending", "true"),)

    commands, locked = run([])
    assert type(commands[-1]) is ShowMenu and locked == [False, False, True]

    # After run 3, load run 2's checkpoint at the menu: the store is unchanged.
    version, records = store.version, (store.unlocked("ending"), store.unlocked("route"))
    later = launched(program, store, show_locked=True)
    assert later.restore(round_trip(menu_states[1])).result is RestoreResult.OK
    assert (store.version, store.unlocked("ending"), store.unlocked("route")) == (
        version, *records)


# --- AC-F19-06's "Run R ends" rows (they needed the executors, step 3) ---------------------------

def test_ac06_reads_load_clean_and_run_to_the_end(tmp_path):
    from engine.core.paths import GamePaths
    from engine.script.loader import LoadOptions, load_story
    from tests.script.helpers import template_e

    rows = [("$ seen = persistent.endings", None),
            ('if "sad" in persistent.endings:⏎[8]"In."', None),
            ("$ n = len(persistent.routes)", None),
            ('$ c = persistent.endings.count("sad")', None),
            ('$ e = list(persistent.endings)⏎[4]$ e.append("x")', None),
            ("$ persistent.endings_seen = 1", None),
            ('$ persistent.flowers.append("rose")', "default persistent.flowers = []")]
    for n, (S, T) in enumerate(rows):
        root = tmp_path / str(n)
        (root / "script").mkdir(parents=True)
        (root / "script" / "main.vns").write_text(template_e(S=S, T=T), encoding="utf-8")
        result = load_story(GamePaths(root.resolve()), LoadOptions(dev=True))
        assert (result.errors, result.warnings) == ((), ()), (S, result.warnings)
        assert ends(run_e(result.program, store_with(("sad",)), dev=True)), S

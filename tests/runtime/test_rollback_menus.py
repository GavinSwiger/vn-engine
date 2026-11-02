"""F14 — author control and menus. Step 2: AC-F14-14 (``rollback block``) and AC-F14-15
(``rollback off``/``on``) on ``walls/`` and ``loop/``. Step 3: AC-F14-11 (picking again) and
AC-F14-13 (fixed menus, ``fix_menu``)."""

import json
from dataclasses import replace

from engine.runtime.commands import Advance, Choose, Say, ShowMenu
from engine.runtime.interpreter import RestoreResult
from engine.runtime.rollback import ROLLBACK_OFF
from engine.runtime.state import GameState
from tests.runtime.effects_story import take_all
from tests.runtime.rollback_story import (back, fixture, forward, lands_on, play_to, run_k,
                                          shown_text, start, step, where)
from tests.runtime.story import fingerprint


def _said(released) -> list[str]:
    return ["".join(s.text for s in c.body.plain()) for c in released if type(c) is Say]


def _walls(text: str, *, choice: int = 1):
    interp = start(fixture("walls"))
    play_to(interp, text, choice=choice)
    take_all(interp)
    return interp


def _room(interp) -> int:
    return interp.timeline.view(interp).back_room


# --- AC-F14-14 — rollback block ------------------------------------------------------------------

def test_ac14_block():
    assert _room(_walls("B1.")) == 0
    interp = _walls("B2.")
    assert _room(interp) == 1
    back(interp, 5)
    assert shown_text(interp) == "B1." and interp.timeline.refused == 1
    assert _room(_walls("T1.")) == 0                        # "Tell him?" can't be reached
    interp = _walls("A2.")                                  # sliced after the block
    interp.post(Advance(interp.current.sid))
    interp.run(1)
    assert interp.current.text == "B1." and not interp.timeline.view(interp).can_back
    interp = start(fixture("loop"))                         # loop/: a block in a loop
    seen = []
    while interp.current is not None and shown_text(interp) != "After.":
        seen.append((shown_text(interp), _room(interp)))
        if shown_text(interp).startswith("Pass"):
            assert interp.timeline.states[0] is interp.checkpoint()
        step(interp)
    seen.append((shown_text(interp), _room(interp)))
    assert seen == [("Before.", 0), ("Lead {var=i}.", 1), ("Pass {var=i}.", 0),
                    ("Lead {var=i}.", 1), ("Pass {var=i}.", 0), ("Lead {var=i}.", 1),
                    ("Pass {var=i}.", 0), ("After.", 1)]


# --- AC-F14-15 — rollback off and on -------------------------------------------------------------

def test_ac15_off_and_on():
    rows = [("C1.", False, 0), ("C2.", False, 0), ("D1.", False, 0), ("D2.", True, 1),
            ("D3.", True, 2)]
    for text, can_back, room in rows:
        interp = _walls(text)
        view = interp.timeline.view(interp)
        assert (view.can_back, view.back_room) == (can_back, room), text
    interp = _walls("D1.")
    assert interp.timeline.states[0] is interp.checkpoint()   # C1, C2 never reached again
    interp = _walls("C2.")                                    # a save at C2
    data = interp.checkpoint().to_json()
    assert data["rollback"] == {"enabled": False}
    fresh = start(fixture("walls"))
    loaded = GameState.from_json(json.loads(json.dumps(data)))
    assert fresh.restore(loaded).result is RestoreResult.OK
    assert fresh.rollback_state is ROLLBACK_OFF and not fresh.timeline.view(fresh).can_back
    step(fresh)                                             # rollback on, then D1: a wall
    assert shown_text(fresh) == "D1." and not fresh.timeline.view(fresh).can_back
    step(fresh)
    assert fresh.timeline.view(fresh).can_back


# --- AC-F14-11 — picking again at a rolled-back menu ----------------------------------------------

def _locks(released) -> list[bool]:
    return [s.locked for c in released if type(c) is ShowMenu for s in c.choices]


def test_ac11_picking_again():
    interp, k = run_k("F")                                   # K@F, back 4 to M
    back(interp, 4)
    assert where(interp, k) == "M" and interp.timeline.view(interp).ahead == 4
    step(interp, 1)                                          # the same pick
    assert where(interp, k) == "D1" and interp.timeline.view(interp).ahead == 3
    assert interp.choices.picks == k["D1"].choices.picks
    interp, k = run_k("F")                                   # another pick
    back(interp, 4)
    step(interp, 2)
    t = interp.timeline
    assert shown_text(interp) == "Call one." and t.view(interp).ahead == 0
    assert [p.text for p in interp.choices.picks] == ["Call for help"]
    texts = [e.text for e in interp.history.entries]
    assert "Call for help" in texts and "Wade one." not in texts and "Wade two." not in texts
    play_to(interp, "Last")
    assert _said(take_all(interp))[-1] == "Last call 1."
    seen = []
    while t.view(interp).can_back:
        back(interp, 1)
        seen.append(shown_text(interp))
    assert seen == ["Side.", "Call one.", "Which way?", "Three {var=r}.", "Two.", "One."]
    interp, k = run_k("F")                                   # forward: the remembered pick
    back(interp, 4)
    assert lands_on(interp, forward(interp, 1), k["D1"])


# --- AC-F14-13 — fixed menus ---------------------------------------------------------------------

def test_ac13_fixed_menus():
    for show_locked in (False, True):
        interp = start(fixture("walls"), show_locked=show_locked)
        play_to(interp, "Promise?")
        released = take_all(interp)
        menu = interp.current
        yes_no = [c.key for c in menu.choices]
        assert _locks(released) == [False, False]           # first time, live
        assert interp.choices.waiting.pickable == tuple(yes_no)
        step(interp, 1)                                     # Yes → Y1
        take_all(interp)
        released = back(interp, 1)                          # landed by StepBack
        assert _locks(released) == [False, True], show_locked
        assert interp.choices.waiting.pickable == (yes_no[0],)
        assert interp.menu_open[0].choices[1].locked
        before = fingerprint(interp)
        interp.post(Choose(menu.sid, yes_no[1]))            # No: refused by F07
        assert fingerprint(interp) == before
        data = interp.checkpoint().to_json()                # a save here: a normal menu
        assert data["choices"]["waiting"]["pickable"] == yes_no
        assert data["choices"]["waiting"]["locked"] == []
        fresh = start(fixture("walls"))
        assert fresh.restore(GameState.from_json(json.loads(json.dumps(data)))).result is \
            RestoreResult.OK
        assert _locks(take_all(fresh)) == [False, False]   # loaded: no remembered future
        assert len(forward(interp, 1)) > 0 and shown_text(interp) == "Y1."   # Yes kept
        assert interp.timeline.view(interp).ahead == 0
        back(interp, 2)                                     # D3, then StepForward
        assert shown_text(interp) == "D3."
        assert _locks(forward(interp, 1)) == [False, True], show_locked
        back(interp, 1)                                     # D3, then Advance
        step(interp)
        released = take_all(interp)
        assert [c.restored for c in released if type(c) is ShowMenu] == [False]
        assert _locks(released) == [False, True], show_locked
        interp.post(Choose(menu.sid, yes_no[0]))            # Choose(Yes) keeps the future
        interp.run(10_000)
        assert shown_text(interp) == "Y1." and interp.timeline.cursor == len(
            interp.timeline.states) - 1
    # The remembered pick isn't pickable now (a key the menu no longer offers): a normal
    # menu, and StepForward has no effect.
    t = interp.timeline
    y1 = t.states[t.cursor]
    last = y1.choices.picks[-1]
    t.states[t.cursor] = replace(y1, choices=replace(y1.choices, picks=y1.choices.picks[:-1] + (
        replace(last, choice="0123456789ab"),)))
    released = back(interp, 1)
    assert _locks(released) == [False, False]
    before = fingerprint(interp)
    assert forward(interp, 1) == [] and fingerprint(interp) == before
    assert interp.timeline.replay == 0

"""F14 — headless ``back [N]``/``forward [N]`` (04 §12, PR-F14-24; 07 I-12, I-15): AC-F14-27.
The input forms, the error text, ``back`` and ``forward``, and the equivalence with events
posted to the real ``RuntimeStoryDriver`` (step 4: it pumps while ``busy``) in chunks of 1, 64,
and unlimited, with its report and landing listeners (I-3)."""

import itertools

import pytest

from engine.app import story as story_mod
from engine.app.story import RuntimeStoryDriver
from engine.runtime import headless
from engine.runtime.commands import (Advance, Choose, MinigameDone, Say, ShowMenu, StepBack,
                                     StepForward, WaitDone)
from engine.runtime.headless import HeadlessInputError, run_headless
from engine.runtime.minigame import headless_outcome
from engine.script.minigame import Minigame
from engine.runtime.interpreter import Interpreter, Status
from engine.script.menu import Menu
from engine.script.messages import format_message
from tests.runtime import corpus
from tests.runtime.rollback_story import IMG14, fixture, launched


def _run(inputs, **kwargs):
    return run_headless(fixture("steps"), seed=42, inputs=inputs, image_files=IMG14, **kwargs)


def _shown(commands) -> list[tuple[str, bool]]:
    return [(c.text if type(c) is Say else "menu", c.restored) for c in commands
            if type(c) in (Say, ShowMenu)]


def _driven(interp: Interpreter, seed: int, inputs: list[str], chunk: int,
            monkeypatch) -> tuple[list, list[str]]:
    """``run_headless``'s rules through the real ``RuntimeStoryDriver``: events posted to it,
    ``RUN_CHUNK_STEPS`` = ``chunk``, and a fake clock (AC-F03-66) that passes the slice's
    deadline at every look, so each pump runs one chunk and a forward chain spans pumps
    (the driver pumps while ``busy``). Also returns the listener calls, in order."""
    monkeypatch.setattr(story_mod, "RUN_CHUNK_STEPS", chunk)
    ticks = itertools.count(0.0, story_mod.RUN_SLICE_S)
    driver = RuntimeStoryDriver(interp, clock=lambda: next(ticks), fixed_seed=seed)
    heard: list[str] = []
    driver.add_report_listener(lambda: heard.append("report"))
    driver.add_landing_listener(lambda: heard.append("landing"))
    driver.new_game()
    commands: list = []
    pending = iter(inputs)
    while True:
        commands += driver.pump(1 << 30)
        if interp.busy:
            continue
        if interp.status is not Status.WAITING:
            return commands, heard
        if interp.waiting_for is not None:
            driver.post(WaitDone(interp.waiting_for))
            continue
        current = interp.current
        if type(current) is Minigame:           # F25-4: run_headless's test outcome
            outcome = headless_outcome(interp, current)     # (F23 s6: it uses no input)
            driver.post(MinigameDone(current.sid, interp.minigame_run, outcome.result,
                                     outcome.changes))
            continue
        answer = next(pending, None)
        if answer is None:
            if type(current) is Menu:
                return commands, heard
            answer = "advance"
        word, _, n = answer.partition(" ")
        if word == "advance":
            driver.post(Advance(current.sid))
        elif word == "choose":
            driver.post(Choose(current.sid, interp.choices.waiting.pickable[int(n) - 1]))
        else:
            driver.post((StepBack if word == "back" else StepForward)(int(n or 1)))


def test_ac27_headless_back_and_forward(monkeypatch):
    a, b, c, m = ("One.", False), ("Two.", False), ("Three {var=r}.", False), ("Which way?", False)
    shown = _shown(_run(["advance", "advance", "back 2"]))
    assert shown[:8] == [a, b, c, ("One.", True), b, c, m, ("menu", False)]
    assert _shown(_run(["advance", "back"]))[:4] == [a, b, ("One.", True), b]
    shown = _shown(_run(["advance", "advance", "back 2", "forward"]))       # forward = 1
    assert shown[:6] == [a, b, c, ("One.", True), ("Two.", True), c]
    shown = _shown(_run(["advance", "advance", "back 2", "forward 2"]))
    assert shown[:6] == [a, b, c, ("One.", True), ("Three {var=r}.", True), m]
    for inputs in (["back"], ["back 1000"], ["forward"], ["forward 2"],      # can't move
                   ["advance", "forward 1000"]):
        assert _shown(_run(inputs))[:4] == [a, b, c, m], inputs
    assert _shown(_run(["back 3"], rollback_steps=0))[:2] == [a, b]
    for text in ("back 0", "back 1001", "back -1", "forward x", "back 3 4", "Back 1", "back 01",
                 "back  1", "forward 5000"):
        with pytest.raises(HeadlessInputError) as caught:
            _run(["advance", "advance", text])
        assert str(caught.value) == format_message("H-input", (3, text)), text
        assert _shown(caught.value.commands)[-1] == ("Three {var=r}.", False)
    assert format_message("H-input", (3, "back 0")) == (   # F23, F20, F31: finish, jump, player
        'input 3 "back 0" isn\'t advance, choose N, back N, forward N (N from 1 to 1000), '
        'jump and a box id, finish and a result, or player deletes or restores and a file name.')
    # choose 2 at a landed fixed menu (one pickable choice): F07's out-of-range error.
    with pytest.raises(HeadlessInputError) as caught:
        run_headless(fixture("walls"), seed=1, inputs=["advance"] * 9 + ["choose 1", "back 1",
                                                                         "choose 2"])
    promise = next(s for s in fixture("walls").labels["start"].block
                   if type(s) is Menu and s.question.text == "Promise?")
    assert str(caught.value) == format_message(
        "H-choose-range", (2, promise.file.ref, promise.line, 1))
    # Equivalence: run_headless and posted events in chunks of 1, 64, and unlimited.
    made: list[Interpreter] = []

    class Spied(Interpreter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr(headless, "Interpreter", Spied)
    rolls = ["advance", "back 2", "forward 1", "back 1", "choose 2", "advance", "advance",
             "advance"]
    example = corpus.example_program()
    images = corpus.example_images()
    for name, program, seed, inputs, files in (
            ("K", fixture("steps"), 42, ["advance"] * 3 + ["choose 1"] + rolls, IMG14),
            # F17 step 5: 7 more advances for the prologue's full-screen lines; F25-4: 1
            # more for Hana's map line; F23 s6: 2 more for the lantern game's lines; F31 s5:
            # 6 more for the bonus scene's lines.
            ("example", example, 1, ["advance"] * 27 + ["choose 1", "choose 1"] + rolls,
             images)):
        made.clear()
        expected = run_headless(program, seed=seed, inputs=inputs, image_files=files,
                                minigames=corpus.example_minigames())
        final = made[0].checkpoint()
        assert made[0].timeline.landings == 3, name                # back, forward, back
        for chunk in (1, 64, 1 << 30):
            interp = corpus.launched(program, files)
            commands, heard = _driven(interp, seed, inputs, chunk, monkeypatch)
            assert commands == expected, (name, chunk)
            assert interp.checkpoint() == final and interp.status is made[0].status
            # I-3: one report per pump that landed or matched, landings also to F15's list.
            assert heard.count("landing") == 3, (name, chunk)
            assert all(heard[i - 1] == "report" for i, h in enumerate(heard) if h == "landing")
        if name == "K":
            assert made[0].status is Status.ENDED and final.variables["path"] == "call"

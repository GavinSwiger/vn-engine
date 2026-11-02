"""F14 step 3 — forward (``on_step_forward``, ``run``'s chain, ``_forward_once``,
``_land_replay``; the ``begin_wait``/``_end`` replay rules, 07 I-4): AC-F14-08, AC-F14-09 (a,
b, d; (c) is ``corpus.py``'s document), AC-F14-10, AC-F14-12, AC-F14-24 (runtime rows; the
F13 page row is App R's, step 4) and AC-F14-25. The rows that check the forward landing's
``NvlPage`` move to F17 s3; the (F15) row of AC-F14-10 waits for F15."""

from pathlib import Path

import pytest

from engine.core.startvalues import StartOptions
from engine.runtime.commands import (Advance, AudioRestore, ChapterStarted, Choose, Flash,
                                     PlayMusic, PlaySound, Say, Shake, ShowStage, StepBack,
                                     StepForward, StoryEnded, StoryWait, WaitDone)
from engine.runtime.interpreter import Interpreter, Status
from engine.script.menu import Menu
from tests.runtime import corpus
from tests.runtime.effects_story import load_game, of_type, take_all
from tests.runtime.rollback_story import (F14, back, fixture, forward, lands_on, launched,
                                          play_to, restore_spy, run_k, shown_text,
                                          start, step, where)
from tests.runtime.story import end_waits, fingerprint


def _variant(root: Path, old: str, new: str) -> Interpreter:
    """Run K's script with one edit, started (at A)."""
    text = (F14 / "steps" / "script" / "main.vns").read_text(encoding="utf-8")
    assert old in text
    (root / "script").mkdir(parents=True)
    (root / "script" / "main.vns").write_text(text.replace(old, new, 1), encoding="utf-8")
    interp = launched(load_game(root))
    interp.new_game(42)
    interp.run(10_000)
    return interp


# K9 (06 §5): a fade transition, a pause, a shake, and a flash between C and M.
K9 = ("    menu:\n", "    scene river with fade\n    pause 1.0\n    shake\n    flash\n    menu:\n")


def _plain(say: Say) -> str:
    return "".join(span.text for span in say.body.plain())


def _said(commands) -> list[tuple[str, bool]]:
    return [(_plain(c), c.restored) for c in commands if type(c) is Say]


def _ahead(interp: Interpreter) -> int:
    return interp.timeline.view(interp).ahead


# --- AC-F14-08 — forward re-runs quietly and lands in the restore form -------------------------

def test_ac08_forward_lands_in_the_restore_form(tmp_path: Path):
    calls: list[bool] = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Interpreter, "restore", restore_spy(calls))
        for count, lands, ahead in ((1, "B", 4), (3, "M", 2), (9, "D2", 0)):
            interp, k = run_k("D2")
            back(interp, 5)
            assert _ahead(interp) == 5
            released = forward(interp, count)
            assert lands_on(interp, released, k[lands]), count       # exactly one burst
            assert _ahead(interp) == ahead and where(interp, k) == lands
            if lands == "M":                                         # no Say for B or C
                assert [text for text, _ in _said(released)] == ["Which way?"]
                released = forward(interp, 1)                        # M (landed) → D1
                assert lands_on(interp, released, k["D1"])
                assert [p.text for p in interp.choices.picks] == ["Wade in"]
        before = fingerprint(interp)                                 # D2, the newest
        assert forward(interp, 1) == [] and fingerprint(interp) == before
        interp, k = run_k("F")                                       # K@F, back 2 to D2
        back(interp, 2)
        released = forward(interp, 1)
        assert lands_on(interp, released, k["S"])
        restore = of_type(released, AudioRestore)
        assert [m.file for m in restore[0].state.music] == ["storm.ogg"]
        assert of_type(released, PlayMusic, PlaySound) == []
        # A chain running, sliced (driver chunk 1): a second StepForward is ignored.
        interp, k = run_k("D2")
        back(interp, 5)
        interp.post(StepForward(3))
        posted = False
        while interp.busy:
            interp.run(1)
            if not posted and interp.status is Status.WAITING:      # an intermediate landing
                assert interp.released == 0 and interp.timeline.replay == 2
                interp.post(StepForward(1))
                posted = True
        assert posted and lands_on(interp, take_all(interp), k["M"]) and _ahead(interp) == 2
        # (F09) K9: back from M to C, forward 1: no wait, effect, or transition released.
        interp = _variant(tmp_path / "k9", *K9)
        for _ in range(3):
            step(interp)
            end_waits(interp)
        m = interp.checkpoint()
        assert shown_text(interp) == "Which way?" and interp.timeline.cursor == 3
        take_all(interp)
        back(interp, 1)
        seq = interp._wait_seq
        released = forward(interp, 1)
        assert lands_on(interp, released, m)
        assert of_type(released, StoryWait, Shake, Flash) == []
        assert all(c.transition is None for c in of_type(released, ShowStage))
        assert interp._wait_seq == seq + 2                           # ids never repeat
    assert calls and all(calls)


# --- AC-F14-09 — same story forward, with the existing determinism harness ---------------------

def _roll_through(program, seed: int, images, picks) -> tuple[Interpreter, list]:
    """``corpus.play`` with AC-F14-09 (b)'s inputs added: ``back 3``, ``forward 3`` before
    every 5th line is advanced, and after every pick ``back 1`` and the same pick again.

    Persistent data isn't rolled back (PR-F14-22, AC-F14-25), so re-running a
    ``$ persistent…`` line can change the story on purpose (the example's
    ``persistent.festivals``). A step back never crosses a change of a persistent value:
    ``back 3`` becomes ``back N`` with N the steps since the last change, and the re-pick is
    left out when the pick changed one. Nor does it cross a minigame (F24-4: the example's
    poem ends with its test outcome, ``corpus.settle``), where ``forward`` stops (F23)."""
    interp = corpus.launched(program, images)
    interp.new_game(seed)
    interp.run(10_000)
    commands = take_all(interp)
    store = interp.persistent

    def go(event) -> None:
        interp.post(event)
        while interp.busy:
            interp.run(10_000)
        commands.extend(take_all(interp))

    def values() -> dict:
        return {name: store.peek(name) for name in store.names()}

    pending = iter(picks)
    lines = 0
    clean = -1                                      # steps since a persistent value changed
    last = values()
    poems = interp.minigame_run                     # or since a minigame ended
    while interp.status is Status.WAITING:
        if corpus.settle(interp):
            commands.extend(take_all(interp))
            continue
        now = values()
        clean = clean + 1 if now == last and interp.minigame_run == poems else 0
        last, poems = now, interp.minigame_run
        current = interp.current
        if type(current) is Menu:
            key = interp.choices.waiting.pickable[next(pending, 1) - 1]
            go(Choose(current.sid, key))
            end_waits(interp)
            commands.extend(take_all(interp))
            if interp.status is Status.WAITING and values() == last:
                go(StepBack(1))
                assert interp.current is current
                go(Choose(current.sid, key))
            continue
        lines += 1
        n = min(3, clean)
        if lines % 5 == 0 and n > 0:
            go(StepBack(n))
            go(StepForward(n))
            assert interp.current is current and interp.timeline.view(interp).ahead == 0
        go(Advance(current.sid))
    return interp, commands


def _live_lines(commands) -> list[Say]:
    """The ``Say``s shown live, a line shown again at once (a re-pick) counted once."""
    out: list[Say] = []
    for c in commands:
        if type(c) is Say and not c.restored and (not out or out[-1] != c):
            out.append(c)
    return out


def _final(interp: Interpreter) -> str:
    return corpus.dumps(corpus.run_document(corpus.Played(interp, [], []))["final"])


def _to_the_last_line(program, seed: int, images, picks
                      ) -> tuple[Interpreter, list, list]:
    """``corpus.play`` stopped at the story's last line, with each step's snapshot and the
    persistent values the store held there."""
    total = len(corpus.play(program, seed, images, picks).states)
    interp = corpus.launched(program, images)
    interp.new_game(seed)
    interp.run(10_000)
    store = interp.persistent
    pending = iter(picks)
    states: list = []
    values: list = []
    while True:
        corpus.settle(interp)
        states.append(interp.checkpoint())
        values.append({name: store.peek(name) for name in store.names()})
        if len(states) == total:
            return interp, states, values
        current = interp.current
        if type(current) is Menu:
            interp.post(Choose(current.sid,
                               interp.choices.waiting.pickable[next(pending, 1) - 1]))
        else:
            interp.post(Advance(current.sid))
        interp.run(10_000)


def _there_and_back(interp: Interpreter, states: list, values: list) -> None:
    """(d): back one step at a time to the earliest reachable step, then forward one at a
    time to the newest; every step's checkpoint is the first pass's, byte for byte.

    Persistent data isn't rolled back (PR-F14-22), and the example reads a value it writes
    (``persistent.festivals``), so before going forward the store's values are put back as
    they were at the earliest step: the re-run then has the first pass's inputs."""
    t = interp.timeline
    first = states[-len(t.states):]
    assert t.states[-1] is states[-1]
    for i in range(len(first) - 2, -1, -1):
        back(interp, 1)
        assert interp.checkpoint() == first[i]
        assert corpus.dumps(interp.checkpoint().to_json()) == corpus.dumps(first[i].to_json())
    assert not t.view(interp).can_back
    store = interp.persistent
    for name, value in values[-len(first)].items():
        if store.peek(name) != value:
            store.set(name, value)
    for i in range(1, len(first)):
        forward(interp, 1)
        assert interp.checkpoint() == first[i]
        assert corpus.dumps(interp.checkpoint().to_json()) == corpus.dumps(first[i].to_json())


def test_ac09_same_story_forward():
    # (a) Run K, seeds 42 and 7: back from M to B, then on to C by forward and by Advance.
    for seed in (42, 7):
        _, k = run_k("F", seed=seed)
        three = f"Three {k['C'].variables['r']}."
        for by in ("forward", "advance"):
            interp, _ = run_k("M", seed=seed)
            back(interp, 2)
            if by == "forward":
                released = forward(interp, 1)
            else:
                interp.post(Advance(interp.current.sid))
                interp.run(10_000)
                released = take_all(interp)
            assert _said(released) == [(three, by == "forward")], (seed, by)
            for _ in range(5):                                       # M, c1: D1, D2, S, F
                step(interp)
            assert corpus.dumps(interp.checkpoint().to_json()) == corpus.dumps(
                k["F"].to_json()), (seed, by)
    # (b) The example, seeds 1–5: back/forward and re-picks change nothing.
    program, images = corpus.example_program(), corpus.example_images()
    for seed in corpus.EXAMPLE_SEEDS:
        picks = corpus.EXAMPLE_PICKS[seed]
        played = corpus.play(program, seed, images, picks)
        interp, commands = _roll_through(program, seed, images, picks)
        assert interp.status is Status.ENDED and interp.timeline.landings >= 10, seed
        assert _final(interp) == _final(played.interp), seed
        assert _live_lines(commands) == _live_lines(played.commands), seed


@pytest.mark.slow
def test_ac09_the_success_measure(tmp_path: Path):
    """(d): example seeds 1–3 and the corpus ``realistic`` part, depth 100."""
    program, images = corpus.example_program(), corpus.example_images()
    for seed in (1, 2, 3):
        _there_and_back(*_to_the_last_line(program, seed, images, corpus.EXAMPLE_PICKS[seed]))
    realistic = corpus.load_part(corpus.make_corpus(tmp_path)["realistic"])
    _there_and_back(*_to_the_last_line(realistic, 1, (), ()))


# --- AC-F14-10 — clicking forward from a rolled-back step ---------------------------------------

def test_ac10_clicking_forward(tmp_path: Path):
    interp, k = run_k("D2")
    back(interp, 4)
    assert where(interp, k) == "B" and _ahead(interp) == 4
    marked: list[str] = []
    real_mark = interp.persistent.mark_seen
    interp.persistent.mark_seen = lambda sid: (marked.append(sid), real_mark(sid))[1]
    step(interp)                                                     # Advance: C live
    released = take_all(interp)
    says = of_type(released, Say)
    assert [s.restored for s in says] == [False] and _ahead(interp) == 3
    assert of_type(released[:released.index(says[0])], AudioRestore) == []
    assert interp.checkpoint() == k["C"] and marked == [k["B"].position]
    released = forward(interp, 1)                                    # M, the future kept
    assert lands_on(interp, released, k["M"]) and _ahead(interp) == 2
    step(interp)                                                     # Choose(c1): D1 live
    assert _said(take_all(interp)) == [("Wade one.", False)] and _ahead(interp) == 1
    interp, k = run_k("F")                                           # back 2 to D2, Advance
    back(interp, 2)
    step(interp)
    released = take_all(interp)
    assert [c.file for c in of_type(released, PlayMusic)] == ["storm.ogg"]
    assert [c.file for c in of_type(released, PlaySound)] == ["splash.ogg"]
    assert where(interp, k) == "S" and _ahead(interp) == 1
    # (F09) K9: back to C, Advance: the fade, pause, shake, and flash are released live.
    interp = _variant(tmp_path / "k9", *K9)
    kinds = []
    for again in (False, True):
        if again:
            back(interp, 1)
        else:
            step(interp)
            step(interp)
            take_all(interp)
        interp.post(Advance(interp.current.sid))
        interp.run(10_000)
        released = take_all(interp)
        while interp.waiting_for is not None:                       # as headless answers
            interp.post(WaitDone(interp.waiting_for))
            interp.run(10_000)
            released += take_all(interp)
        assert shown_text(interp) == "Which way?"
        kinds.append([(type(c).__name__, getattr(c, "transition", None) is not None)
                      for c in released if type(c) in (StoryWait, Shake, Flash, ShowStage)])
    assert kinds[0] == kinds[1] and len(kinds[0]) == 5             # fade, pause, M's burst
    # (F18) a chapter between B and C: click plays the card; wheel finishes it quietly.
    for by in ("advance", "forward"):
        interp = _variant(tmp_path / by, '    $ r = ', '    chapter river "By the River"\n'
                                                     '    $ r = ')
        step(interp)                                                 # B
        step(interp)                                                 # the card, then C
        end_waits(interp)
        c = interp.checkpoint()
        assert shown_text(interp).startswith("Three")
        take_all(interp)
        back(interp, 1)
        unlocks: list[bool] = []
        real_unlock = interp.persistent.unlock
        interp.persistent.unlock = lambda kind, name: (                     # type: ignore
            lambda new: (unlocks.append(new), new)[1])(real_unlock(kind, name))
        if by == "advance":
            interp.post(Advance(interp.current.sid))
            interp.run(10_000)
            released = take_all(interp)
            assert of_type(released, ChapterStarted) and of_type(released, StoryWait)
            assert any(s.card is not None for s in of_type(released, ShowStage))
            end_waits(interp)
            assert interp.checkpoint() == c
        else:
            released = forward(interp, 1)
            assert lands_on(interp, released, c)
            assert of_type(released, ChapterStarted, StoryWait) == []
        assert unlocks == [False], by


# --- AC-F14-12 — divergence drops the future and never shows a remembered step -----------------

def _diverge(label: str = "start", lines: int = 3) -> Interpreter:
    interp = start(fixture("diverge"),
                   start=None if label == "start" else StartOptions(label=label))
    for _ in range(lines - 1):
        step(interp)
    take_all(interp)
    return interp


def test_ac12_divergence():
    calls: list[bool] = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Interpreter, "restore", restore_spy(calls))
        for by in ("forward", "advance"):                            # P3: back 2 to P1
            interp = _diverge()
            assert interp.timeline.cursor == 2
            back(interp, 2)
            if by == "forward":
                released = forward(interp, 1)
                assert lands_on(interp, released, interp.checkpoint())
            else:
                step(interp)
                released = take_all(interp)
            assert interp.persistent.get("visits") == 2
            assert _said(released) == [("Again.", by == "forward")]
            assert _ahead(interp) == 0 and len(interp.timeline.states) == 2
        interp = _diverge("nxt")                                     # tick_nxt(): 1, then 2
        n2 = interp.timeline.states[1]
        back(interp, 2)
        released = forward(interp, 1)
        t = interp.timeline
        assert _ahead(interp) == 0 and len(t.states) == 2 and t.states[1] is not n2
        assert n2.variables["y"] == 1 and interp.checkpoint().variables["y"] == 2
        assert lands_on(interp, released, interp.checkpoint())
        interp = _diverge("loose")                                   # 1, then 1.0: a match
        l2 = interp.timeline.states[1]
        back(interp, 2)
        forward(interp, 1)
        assert _ahead(interp) == 1 and interp.timeline.states[1] is interp.checkpoint()
        assert type(l2.variables["x"]) is int and type(interp.checkpoint().variables["x"]) is float
        interp = _diverge("ends")                                    # the re-run ends
        back(interp, 2)
        assert forward(interp, 1) == [StoryEnded()]
        assert interp.status is Status.ENDED and not interp.busy
    assert calls and all(calls)


# --- AC-F14-24 — history follows the shown step ------------------------------------------------

def test_ac24_history_follows_the_shown_step():
    interp, k = run_k("D2")
    back(interp, 2)
    assert interp.history == k["M"].history
    forward(interp, 2)
    assert interp.history == k["D2"].history
    interp, k = run_k("F")                                           # AC-F14-11's re-pick
    back(interp, 4)
    step(interp, 2)
    play_to(interp, "Last")
    sids = {entry.sid for entry in interp.history.entries}
    assert k["D1"].position not in sids and k["D2"].position not in sids
    assert k["M"].position in sids


# --- AC-F14-25 — what is not rolled back -------------------------------------------------------

def test_ac25_what_is_not_rolled_back():
    for by in ("forward", "advance"):
        interp = _diverge(lines=2)                                   # at "First."
        store = interp.persistent
        assert store.get("visits") == 1 and interp.G["cfg"] == [1]
        version, size = store.version, store.values_bytes
        back(interp, 1)                                              # P1: no store write
        assert (store.version, store.values_bytes) == (version, size)
        assert interp.G["cfg"] == [1] and store.get("visits") == 1
        if by == "forward":
            forward(interp, 1)
        else:
            step(interp)
        assert store.get("visits") == 2 and interp.G["cfg"] == [1, 1], by
        assert shown_text(interp) == "Again."


# --- AC-F14-08, the F17 rows — forward lands on an NVL page (F17 s3) --------------------------

def test_ac08_forward_lands_on_an_nvl_page(tmp_path: Path):
    """F17 ``07`` I-3, F14 ``07`` §3.4: a forward landing is the load form, with
    ``NvlPage(on, page)`` right after ``AudioRestore``, and the real presentation shows the
    landed page complete (``show_nvl`` then the restored ``Say``). Run N full back to line 6
    (ADV), then forward across ``nvl on``, ``nvl clear`` and the pick."""
    from types import SimpleNamespace

    from engine.core.config_schema import Config
    from engine.render.textbox import TextboxView
    from engine.render.textlayout import BUNDLED_FACES
    from engine.render.typewriter import TypeState
    from engine.runtime.commands import NvlPage
    from engine.ui.builtin.textbox_screen import TextboxScreen
    from tests.fakes.fixed_font import FixedFontAssets
    from tests.runtime.menu_story import launched as launched_n
    from tests.runtime.nvl_story import RUN_N_LINES, bursts, load_n

    program = load_n(tmp_path / "n")
    interp, _, states = bursts(program)                     # at line 23, ADV

    def load_form_n(state):
        fresh = launched_n(program)
        assert fresh.restore(state).result.name == "OK"
        return take_all(fresh)

    config = Config()
    assets = FixedFontAssets()
    textbox = TextboxScreen(SimpleNamespace(story=None, focused=True), config,
                            TextboxView(assets, config.theme.textbox,
                                        BUNDLED_FACES.for_style(True, False)), BUNDLED_FACES)
    back(interp, len(states) - 1)                           # line 6 (index 0)
    at = 0
    for count, line in ((1, 8), (2, 10), (2, 14), (1, 15), (1, 21)):
        released = forward(interp, count)
        at += count
        state = states[at]
        assert RUN_N_LINES[at] == line
        assert released == load_form_n(state) and interp.checkpoint() == state, line
        pages = [c for c in released if type(c) is NvlPage]
        assert pages == [NvlPage(state.nvl.on, state.nvl.page)], line
        kinds = [type(c).__name__ for c in released]
        assert kinds.index("NvlPage") == kinds.index("AudioRestore") + 1, line
        for c in released:                                   # the presentation's side
            if type(c) is NvlPage:
                textbox.show_nvl(c)
            elif type(c) is Say:
                textbox.show(c)
        rows = [textbox.nvl.entries[r.entry].sid for r in textbox.nvl.rows()]
        assert textbox.typer.state is TypeState.COMPLETE, line     # complete on landing
        assert rows == [entry.sid for entry in state.nvl.page], line

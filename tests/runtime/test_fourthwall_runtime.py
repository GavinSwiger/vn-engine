"""F30 s3 — ``effect window_title`` and ``effect crash`` at run time (F30 ``06-acceptance.md``
AC-F30-14, AC-F30-15; ``04`` §4.2, §4.3, §5.4, §6.1, §8), Run H on Template W and ``walk/``
(``fourthwall_story.py``), and the step 3 headless golden (06 §9 Step 3 milestone)."""

import ast
import json

from engine.persist import saves
from engine.runtime import fourthwall
from engine.runtime.commands import (Advance, AudioRestore, FakeCrash, Flash, Glitch, NvlPage,
                                     Say, Shake, ShowStage, Span, StepBack, StepForward,
                                     StoryFailed, StoryWait, Style, WaitDone, WindowTitle)
from engine.runtime.headless import run_headless
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter, RestoreResult
from engine.runtime.launch import run_launch
from engine.runtime.state import GameState
from engine.script import fourthwall as script_fourthwall
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)
from tests.persist.save_support import make_save
from tests.runtime import corpus, glitch_story
from tests.runtime.effects_story import load_game, of_type, take_all, write_game
from tests.runtime.fourthwall_story import (F30, GOLDEN, golden_text, launched, run_h,
                                            template_w, walk)

FLAG = Style(username=True)
TRICKS = (WindowTitle, FakeCrash)


def _before_l7(commands) -> list:
    """What Run H released after "Hello." up to L7's ``Say``."""
    says = [i for i, c in enumerate(commands) if type(c) is Say]
    return commands[says[0] + 1:says[1] + 1]


def test_ac_f30_14_commands_and_burst_order(tmp_path):
    def row(n, S):
        return run_h(template_w(tmp_path / str(n), S=S))
    burst = _before_l7(row(1, 'effect window_title "Night"'))
    assert [type(c) for c in burst] == [WindowTitle, Say] and burst[0].title == "Night"
    assert _before_l7(row(2, "effect window_title off"))[0] == WindowTitle(None)
    both = _before_l7(row(3, 'effect window_title "Night"⏎effect off'))
    assert of_type(both, WindowTitle) == [WindowTitle("Night")]
    crash = _before_l7(row(4, "effect crash"))
    assert [type(c) for c in crash] == [FakeCrash, Say] and crash[0].body is None
    named = _before_l7(row(5, 'effect crash "Hi {username}"'))[0]
    assert named.body.pieces == (Span("Hi ", Style()), Span("friend", FLAG))
    assert (named.seconds, named.for_stage) == (None, False)
    assert isinstance(named, StoryWait)
    effects = _before_l7(row(6, "shake⏎flash⏎effect tear⏎effect crash"))
    assert [type(c) for c in effects] == [Shake, Flash, Glitch, FakeCrash, Say]
    failed = of_type(row(7, 'effect crash "{var=nope}"'), StoryFailed)
    assert [(e.error.code, e.error.line) for e in failed] == [("E170", 6)]

    # L7's Say and its history entry hold the fallback word.
    interp = launched(template_w(tmp_path / "h"))
    interp.new_game(42)
    interp.run(10_000)
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    assert interp.checkpoint().history.entries[-1].text == "I know who you are, friend."
    # The older corpora release neither command.
    example = corpus.example_program()
    assert not of_type(run_headless(example, seed=42, image_files=corpus.example_images()),
                       *TRICKS)
    assert not of_type(glitch_story.run_h(glitch_story.walk()), *TRICKS)
    assert not of_type(run_h(template_w(tmp_path / "plain")), *TRICKS)
    # Scans and imports.
    assert fourthwall.uses_crash(walk()) and not fourthwall.uses_crash(template_w(tmp_path / "u"))
    assert fourthwall.name_lines(template_w(tmp_path / "n")) == [("script/main.vns", 7)]
    for module in (script_fourthwall, fourthwall):
        tree = ast.parse(open(module.__file__, encoding="utf-8").read())
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not {m for m in names if m and m.split(".")[0] in ("pygame", "time", "random")
                    or m and m.startswith("engine.meta")}, module.__name__


def test_the_headless_golden_with_title_and_crash():
    assert GOLDEN.read_bytes() == golden_text().encode("ascii")
    kinds = [c["type"] for c in json.loads(GOLDEN.read_text(encoding="ascii"))["commands"]]
    assert {"WindowTitle", "FakeCrash"} <= set(kinds)


def _advance(interp) -> list:
    if interp.waiting_for is not None:
        interp.post(WaitDone(interp.waiting_for))
    else:
        interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    return take_all(interp)


def _loaded(program, state: GameState, interp=None) -> list:
    interp = launched(program) if interp is None else interp
    assert interp.restore(state).result is RestoreResult.OK
    return take_all(interp)


def test_ac_f30_15_saves_restores_rollback_and_endings(tmp_path):
    program = walk()
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    take_all(interp)
    w1 = interp.checkpoint()
    _advance(interp)
    w2 = interp.checkpoint()
    crash = _advance(interp)                                # W2 → the crash: no checkpoint
    assert type(crash[-1]) is FakeCrash and interp.checkpoint() is w2
    _advance(interp)
    w3 = interp.checkpoint()
    _advance(interp)
    w4 = interp.checkpoint()
    assert [s.window_title for s in (w1, w2, w3, w4)] == [None, "She is here", "She is here",
                                                          None]
    # Save at W2, load from the title (a fresh interpreter: live None).
    read = saves.parse_full(make_save(w2), game_id=None)
    burst = _loaded(program, read.state)
    assert [type(c) for c in burst[:5]] == [AudioRestore, NvlPage, ShowStage, WindowTitle, Say]
    assert burst[3] == WindowTitle("She is here") and burst[2].restored
    assert _loaded(walk(), read.state) == burst              # an F39 reload is a load
    assert saves.describe(read.state, None) == "Hana: I know who you are, friend."
    assert read.state.history.entries[-1].text == "I know who you are, friend."
    # A W1 save: from the title nothing; with the live title set, WindowTitle(None).
    assert not of_type(_loaded(program, w1), WindowTitle)
    live = launched(program)
    _loaded(program, w2, live)
    assert of_type(_loaded(program, w1, live), WindowTitle) == [WindowTitle(None)]
    # Rollback W4 → W3 → W2 → W1, then forward to W4: each landing under 04 §4.3's rule.
    for want in ([WindowTitle("She is here")], [WindowTitle("She is here")],
                 [WindowTitle(None)]):
        interp.post(StepBack(1))
        interp.run(10_000)
        landing = take_all(interp)
        assert of_type(landing, WindowTitle) == want and not of_type(landing, FakeCrash)
    interp.post(StepForward(1))                             # W1 → W2: the title comes back
    while interp.busy:
        interp.run(10_000)
    assert of_type(take_all(interp), WindowTitle) == [WindowTitle("She is here")]
    interp.post(StepForward(2))                             # W2 → W4, over the crash
    while interp.busy:
        interp.run(10_000)
    forward = take_all(interp)
    assert of_type(forward, WindowTitle) == [WindowTitle(None)]
    assert not of_type(forward, FakeCrash) and interp.checkpoint().window_title is None
    # The ending: none while no title is set; WindowTitle(None) before the card when one is.
    ending = _advance(interp)
    assert not of_type(ending, WindowTitle)
    text = (F30 / "walk" / "script" / "main.vns").read_text(encoding="utf-8")
    kept = load_game(write_game(tmp_path / "kept",
                                text.replace("    effect window_title off\n", "")))
    commands = run_h(kept)
    title_at = max(i for i, c in enumerate(commands) if c == WindowTitle(None))
    card_at = next(i for i, c in enumerate(commands) if type(c) is ShowStage and c.card)
    assert title_at < card_at
    # New game after W3: the first checkpoint has no title.
    interp.new_game(42)
    interp.run(10_000)
    assert interp.checkpoint().window_title is None and not of_type(take_all(interp),
                                                                    WindowTitle)
    # F11's pre-F30 saves (the example's): no title, no WindowTitle.
    example = corpus.example_program()
    for path in sorted((F30.parent / "F11" / "example_saves").glob("*.vnsave"))[:2]:
        old = saves.parse_full(path.read_bytes(), game_id=None)
        assert old.status is saves.SlotStatus.OK and old.state.window_title is None
        loader = Interpreter(example, run_launch(
            example, images=ImageSource.from_files(corpus.example_images())).namespace)
        assert not of_type(_loaded(example, old.state, loader), WindowTitle)
    # walk-nvl: a W2 save's restore burst carries the flagged span in its page record.
    nvl = launched(walk("walk-nvl"))
    nvl.new_game(42)
    nvl.run(10_000)
    _advance(nvl)
    page = of_type(_loaded(walk("walk-nvl"), nvl.checkpoint()), NvlPage)[0].lines
    assert page[1].spans == (Span("I know who you are, ", Style()), Span("friend", FLAG),
                             Span(".", Style()))

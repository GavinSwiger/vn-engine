"""F59 checks on choices at run time (SPEC §3): AC-F59-04 (the badge), 05 (the roll, the
same after a rollback and a load), 06 (one try), 07 (headless)."""

from engine.runtime.commands import Advance, Choose, Say, ShowMenu, StoryEnded
from engine.runtime.dice import Pcg32
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Interpreter, Status
from engine.script.choicecheck import passes
from engine.script.menu import Menu
from tests.runtime.conftest import round_trip
from tests.runtime.menu_story import ALL, launched, load_text

STORY = '''define hana = Character("Hana")
points logic 0 to 10 start 3
label start:
    menu:
        hana "Admit it."
        "The gate was locked." check logic hard:
            success:
                hana "How?"
            failure:
                hana "Nice story."
        "Train.":
            points logic += 4
    hana "Again."
    jump start
'''


def _program(tmp_path, text=STORY):
    result = load_text(tmp_path, text)
    assert not result.errors, [e.format() for e in result.errors]
    return result.program


def _menus(commands) -> list[ShowMenu]:
    return [c for c in commands if type(c) is ShowMenu]


def _lines(commands) -> list[str]:
    return ["".join(s.text for s in c.body.plain()) for c in commands if type(c) is Say]


def _at_menu(program, seed: int, **kwargs) -> Interpreter:
    interp = launched(program, **kwargs)
    interp.new_game(seed)
    interp.run(10_000)
    interp.take_commands(ALL)
    assert type(interp.current) is Menu and interp.status is Status.WAITING
    return interp


def _pick(interp: Interpreter, n: int) -> list[str]:
    menu = interp.current
    interp.post(Choose(menu.sid, menu.choices[n].key))
    interp.run(10_000)
    return _lines(interp.take_commands(ALL))


def _expected(interp: Interpreter, value: int) -> str:
    """What the roll from the interpreter's dice state now gives (``passes``)."""
    core = Pcg32(interp.core.state, ready=True)
    a, b = 1 + core.below(6), 1 + core.below(6)
    return "How?" if passes(a, b, value, 12) else "Nice story."


# --- AC-F59-04 — the badge -------------------------------------------------------------------

def test_ac04_badge_shows_the_odds_and_follows_the_meter(tmp_path):
    commands = run_headless(_program(tmp_path), seed=1, inputs=["choose 2", "advance"],
                            max_lines=4)
    first, second = _menus(commands)[:2]
    assert [(c.check, c.locked) for c in first.choices] == [
        ("[Logic · Hard · 28%]", False), (None, False)]
    assert second.choices[0].check == "[Logic · Hard · 83%]"            # logic 7: needs 5


# --- AC-F59-05 — the roll, deterministic ---------------------------------------------------------

def test_ac05_the_roll_uses_the_story_dice_and_replays(tmp_path):
    program = _program(tmp_path)
    seen = set()
    for seed in range(12):
        interp = _at_menu(program, seed)
        state = interp.checkpoint()
        want = _expected(interp, 3)
        assert _pick(interp, 0)[0] == want
        seen.add(want)
        back = launched(program)                         # a load: a JSON round trip
        assert back.restore(round_trip(state)).result.name == "OK"
        back.take_commands(ALL)
        assert _pick(back, 0)[0] == want
        assert interp.restore(state).result.name == "OK"  # going back to the menu
        interp.take_commands(ALL)
        assert _pick(interp, 0)[0] == want
    assert seen == {"How?", "Nice story."}


# --- AC-F59-06 — one try per playthrough ------------------------------------------------------------

def test_ac06_a_tried_check_is_hidden_or_locked_when_the_menu_comes_back(tmp_path):
    program = _program(tmp_path)
    for show_locked, locked in ((False, []), (True, ["The gate was locked."])):
        interp = _at_menu(program, 5, show_locked=show_locked)
        before = interp.checkpoint()
        _pick(interp, 0)
        while type(interp.current) is not Menu:          # the reply, then "Again."
            interp.post(Advance(interp.current.sid))
            interp.run(10_000)
        waiting = interp.checkpoint().choices.waiting
        texts = {c.key: c.text for c in interp.current.choices}
        assert [texts[k] for k in waiting.pickable] == ["Train."]
        assert [texts[k] for k in waiting.locked] == locked
        shown = _menus(interp.take_commands(ALL))[-1]
        assert [c.check for c in shown.choices if c.locked] == (
            ["[Logic · Hard · 28%]"] if show_locked else [])
        assert interp.restore(before).result.name == "OK"   # going back undoes the try
        assert len(interp.choices.waiting.pickable) == 2


# --- AC-F59-07 — headless -----------------------------------------------------------------------

def test_ac07_headless_run_through_a_checked_menu(tmp_path):
    text = STORY.replace("    hana \"Again.\"\n    jump start\n", "    hana \"Done.\"\n")
    commands = run_headless(_program(tmp_path, text), seed=42, inputs=["choose 1"])
    assert type(commands[-1]) is StoryEnded
    lines = _lines(commands)
    assert lines[0] == "Admit it." and lines[1] in ("How?", "Nice story.") and lines[-1] == "Done."

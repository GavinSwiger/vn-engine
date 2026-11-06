"""F64 present at a menu at run time (specs/F64-items/SPEC-present.md): the option shown or
left out, the pick and its reaction, saves, loads and going back, headless ``present``."""

import pytest

from engine.runtime.commands import Advance, Choose, Say, ShowMenu, StepBack, StepForward
from engine.runtime.headless import HeadlessInputError, run_headless
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.menu import ChoiceState, Pick
from engine.script.choicepresent import PRESENT_KEY
from engine.script.menu import Menu
from tests.runtime.conftest import round_trip
from tests.runtime.menu_story import ALL, launched, load_text

STORY = '''define hana = Character("Hana")
lock item red_lantern "Red Lantern"
lock item brass_key "Brass Key"
default open = True
label start:
    menu:
        hana "Anything?"
        "Nothing.":
            hana "Fine."
        present:
            else:
                hana "Never."
    unlock item red_lantern
    unlock item brass_key
    menu:
        hana "What's that in your hand?"
        "Nothing.":
            $ pass
        present if open:
            red_lantern:
                hana "You kept it!"
            else:
                hana "...Why?"
    hana "End."
'''


def _program(tmp_path, text=STORY):
    result = load_text(tmp_path, text)
    assert not result.errors, [e.format() for e in result.errors]
    return result.program


def _lines(commands) -> list[str]:
    return ["".join(s.text for s in c.body.plain()) for c in commands if type(c) is Say]


def _menus(commands) -> list[ShowMenu]:
    return [c for c in commands if type(c) is ShowMenu]


def _at_second_menu(program, **kwargs) -> Interpreter:
    interp = launched(program, **kwargs)
    interp.new_game(1)
    interp.run(10_000)
    menu = interp.current
    interp.post(Choose(menu.sid, menu.choices[0].key))
    interp.run(10_000)
    interp.post(Advance(interp.current.sid))              # "Fine."
    interp.run(10_000)
    interp.take_commands(ALL)
    assert type(interp.current) is Menu and interp.status is Status.WAITING
    assert interp.current.line == 15
    return interp


def _show(interp: Interpreter, item: str | None) -> list[str]:
    interp.post(Choose(interp.current.sid, PRESENT_KEY, item))
    interp.run(10_000)
    return _lines(interp.take_commands(ALL))


def test_the_option_is_left_out_or_locked_while_nothing_is_held(tmp_path):
    program = _program(tmp_path)
    first = _menus(run_headless(program, seed=1, inputs=[], max_lines=5))[0]
    assert [(c.present, c.locked) for c in first.choices] == [(False, False)]
    interp = launched(program, show_locked=True)
    interp.new_game(1)
    interp.run(10_000)
    shown = _menus(interp.take_commands(ALL))[0]
    assert [(c.key == PRESENT_KEY, c.present, c.locked) for c in shown.choices] == [
        (False, False, False), (True, True, True)]
    assert interp.choices.waiting.locked == (PRESENT_KEY,)


def test_the_option_follows_its_condition(tmp_path):
    program = _program(tmp_path, STORY.replace("default open = True", "default open = False"))
    commands = run_headless(program, seed=1, inputs=["choose 1", "advance"], max_lines=5)
    assert [c.present for c in _menus(commands)[-1].choices] == [False]


def test_a_shown_item_runs_its_reaction_and_is_kept_on_the_pick(tmp_path):
    program = _program(tmp_path)
    interp = _at_second_menu(program)
    assert interp.choices.waiting.pickable[-1] == PRESENT_KEY
    assert _show(interp, "red_lantern") == ["You kept it!"]
    pick = interp.choices.picks[-1]
    assert (pick.choice, pick.item, pick.text) == (PRESENT_KEY, "red_lantern", "Red Lantern")


def test_any_other_item_runs_else(tmp_path):
    interp = _at_second_menu(_program(tmp_path))
    assert _show(interp, "brass_key") == ["...Why?"]


@pytest.mark.parametrize("item", [None, "coin", 3, "x" * 200])
def test_a_present_pick_without_a_held_item_is_ignored(tmp_path, item):
    interp = _at_second_menu(_program(tmp_path))
    assert _show(interp, item) == []
    assert interp.status is Status.WAITING and type(interp.current) is Menu


def test_load_and_going_back_show_the_same(tmp_path):
    program = _program(tmp_path)
    interp = _at_second_menu(program)
    at_menu = interp.checkpoint()
    assert _show(interp, "red_lantern") == ["You kept it!"]
    after = interp.checkpoint()                          # at the reaction's line
    back = launched(program)
    assert back.restore(round_trip(after)).result.name == "OK"
    assert back.choices.picks[-1].item == "red_lantern"
    assert _lines(back.take_commands(ALL)) == ["You kept it!"]
    assert interp.restore(at_menu).result.name == "OK"   # going back to the menu
    interp.take_commands(ALL)
    assert _show(interp, "brass_key") == ["...Why?"]


def test_stepping_back_and_forward_shows_the_same_item_again(tmp_path):
    interp = _at_second_menu(_program(tmp_path))
    assert _show(interp, "brass_key") == ["...Why?"]
    interp.post(StepBack(1))
    interp.run(10_000)
    assert type(interp.current) is Menu
    interp.take_commands(ALL)
    interp.post(StepForward(1))
    interp.run(10_000)
    assert _lines(interp.take_commands(ALL)) == ["...Why?"]
    assert interp.choices.picks[-1].item == "brass_key"


def test_old_picks_load_and_bad_items_are_refused():
    old = {"picks": [{"menu": "start/0123456789ab", "choice": "0123456789ab", "text": "A",
                      "question": None}], "waiting": None}
    assert ChoiceState.from_json(old).picks[0].item is None
    new = ChoiceState((Pick("start/0123456789ab", PRESENT_KEY, "Red Lantern", None,
                            item="red_lantern"),))
    assert ChoiceState.from_json(new.to_json()) == new
    assert new.save_problem() is None
    for bad in ("", "no spaces", 3, "x" * 65):
        data = new.to_json()
        data["picks"][0]["item"] = bad
        with pytest.raises(Exception):
            ChoiceState.from_json(data)


def test_headless_present_and_its_mistakes(tmp_path):
    program = _program(tmp_path)
    lead = ["choose 1", "advance"]
    assert _lines(run_headless(program, seed=1, inputs=lead + ["present red_lantern",
                                                               "advance"]))[-2:] == [
        "You kept it!", "End."]
    for inputs, words in ((lead + ["choose 2"], "Write present <item>"),
                          (["present red_lantern"], "no present: option"),
                          (lead + ["present coin"], "doesn't hold coin"),
                          (["choose 1", "present red_lantern"], "no menu there")):
        with pytest.raises(HeadlessInputError) as caught:
            run_headless(program, seed=1, inputs=inputs)
        assert words in str(caught.value)

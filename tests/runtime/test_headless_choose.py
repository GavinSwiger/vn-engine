"""F07 step 1, headless picks (``04-technical.md`` §5.4; ``06-acceptance.md``): AC-F07-13."""

import pytest

from engine.core.errors import UserFacingError
from engine.core.redact import echo
from engine.runtime.commands import ShowMenu, StoryEnded
from engine.runtime.headless import HeadlessInputError, run_headless
from tests.runtime.menu_story import inputs, lines, load_m, play, run_m

RANGE = ("choose {n} at the menu at script/main.vns, line 6, but only {count} choices can be "
         "picked there.")


@pytest.fixture(scope="module")
def program(tmp_path_factory):
    return load_m(tmp_path_factory.mktemp("m"))


def failure(program, text: str, **kwargs) -> HeadlessInputError:
    with pytest.raises(HeadlessInputError) as caught:
        run_m(program, text, **kwargs)
    return caught.value


def test_ac13_runs_to_the_end(program):
    commands = run_m(program, "a c2")
    assert type(commands[-1]) is StoryEnded and lines(commands)[-1] == "After: crane."


def test_ac13_inputs_that_run_out_at_a_menu_end_the_run(program):
    commands = run_m(program, "a")
    assert type(commands[-1]) is ShowMenu


@pytest.mark.parametrize("n", [4, 999])
def test_ac13_choose_out_of_range(program, n):
    error = failure(program, f"a c{n}")
    assert error.message == RANGE.format(n=n, count=3) and error.format() == error.message


def test_ac13_range_counts_pickable_choices(tmp_path):
    error = failure(load_m(tmp_path, replace={2: "default coins = 1"}), "a c3")
    assert error.message == RANGE.format(n=3, count=2)


def test_ac13_advance_at_a_menu(program):
    assert failure(program, "a a").message == (
        "advance at the menu at script/main.vns, line 6, but a menu waits for a choice. "
        "Write choose N.")


def test_ac13_choose_at_a_line(program):
    assert failure(program, "c2").message == (
        "choose 2 at the line at script/main.vns, line 5, but there is no menu there.")


@pytest.mark.parametrize("bad", ["chose 2", "choose 0", "choose 01", "choose 1000",
                                 "choose -1", "Choose 2"])
def test_ac13_inputs_that_are_neither(program, bad):
    with pytest.raises(HeadlessInputError) as caught:
        run_headless(program, seed=42, inputs=["advance", bad])
    error = caught.value
    assert error.message == (f'input 2 "{bad}" isn\'t advance, choose N, back N, forward N '
                             '(N from 1 to 1000), jump and a box id, or finish and a result.')  # F14, F23, F20


def test_ac13_the_error_is_user_facing_with_the_commands_so_far(program):
    error = failure(program, "a c4")
    assert isinstance(error, UserFacingError)
    assert error.commands == run_m(program, "a")
    assert type(error.commands[-1]) is ShowMenu


def test_ac13_a_long_input_is_cut_by_echo(program):
    bad = "chose " + "x" * 300
    with pytest.raises(HeadlessInputError) as caught:
        run_headless(program, seed=42, inputs=["advance", bad])
    message = caught.value.message
    # F23 (02 §4.2, 07 §2.1): the shared catch-all names finish too.
    assert message == (f'input 2 "{echo(bad)}" isn\'t advance, choose N, back N, forward N '
                       '(N from 1 to 1000), jump and a box id, or finish and a result.')
    assert len(message) < 250                   # F23's catch-all +34 characters, F20's +19


def test_ac13_same_seed_same_inputs_same_picks(program):
    assert run_m(program, "a c2") == run_m(program, "a c2")
    first, _ = play(program, "a c2")
    second, _ = play(program, "a c2")
    assert first.choices == second.choices and len(first.choices.picks) == 1


def test_inputs_notation():
    assert inputs("a c2 c13 chose") == ["advance", "choose 2", "choose 13", "chose"]

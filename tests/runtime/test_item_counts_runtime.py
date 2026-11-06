"""F64 round 1 at run time: item counts (``unlock item coin 30``, ``lock item coin 5``),
``items.count`` / ``codex.count``, the purse, and saves from before F64 (specs/F64-items)."""

import pytest

from engine.runtime.commands import Advance, StepBack, StepForward, StoryFailed
from engine.runtime.interpreter import RestoreResult
from engine.runtime.state import EMPTY_ITEMS, GameState, ItemsState, StateInvalid
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import launched, story_game, take_all

ALL = 1 << 30
TOP = ('lock item coin "Coins" in "Purse" count 0 to 999 money\n'
       'lock item match "Matches" count 3\n'
       'lock item key "Brass Key"\n')


def _start(program):
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    return interp


def _advance(interp):
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    return take_all(interp)


def test_counts_add_take_and_clamp(tmp_path):
    lines = ["unlock item coin 30", "lock item coin 5", "unlock item key",
             "unlock item key 3", "unlock item match 10", "lock item match",
             '$ seen = [items.count("coin"), items.count("key"), items.count("match")]',
             "lock item coin 100",
             '$ seen.append(codex.count("coin"))',
             '$ held = codex.items',
             'hana "Done."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    variables = interp.checkpoint().variables
    assert variables["seen"] == [25, 1, 2, 0]           # match: 10 stops at 3, then 3 - 1
    assert variables["held"] == ["key", "match"]        # coin went at 0
    assert interp.codex.purse()[1] == 0


def test_conditions_read_counts(tmp_path):
    lines = ["unlock item coin 30",
             'if items.count("coin") >= 30:', '    $ rich = True',
             'if codex.count("key") == 0:', '    $ no_key = True', 'hana "Hi."']
    variables = _start(story_game(tmp_path, lines, top=TOP)).checkpoint().variables
    assert variables["rich"] is True and variables["no_key"] is True


def test_counts_save_load_and_roll_back(tmp_path):
    lines = ['hana "One."', "unlock item coin 30", 'hana "Two."', "lock item coin 5",
             'hana "Three."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    _advance(interp)
    two = interp.checkpoint()
    assert two.items == ItemsState(("coin",), (30,))
    assert two.items.to_json() == {"held": ["coin"], "counts": [30]}
    _advance(interp)
    assert interp.codex.count("coin") == 25
    interp.post(StepBack(1))
    interp.run(ALL)
    assert interp.codex.count("coin") == 30            # rollback restores the count
    interp.post(StepForward(1))
    interp.run(ALL)
    assert interp.codex.count("coin") == 25
    saved = round_trip(interp.checkpoint())
    other = launched(story_game(tmp_path, lines, top=TOP))
    assert other.restore(saved).result is RestoreResult.OK
    assert other.codex.count("coin") == 25 and other.codex.state() == saved.items


def test_old_saves_load_as_one_of_each(tmp_path):
    lines = ['hana "One."', "unlock item key", 'hana "Two."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    _advance(interp)
    data = interp.checkpoint().to_json()
    data["items"] = {"held": ["coin", "key"]}          # a save made before F64
    old = GameState.from_json(data)
    assert old.items == ItemsState(("coin", "key"))
    other = launched(story_game(tmp_path, lines, top=TOP))
    assert other.restore(old).result is RestoreResult.OK
    assert other.codex.count("coin") == 1 and other.codex.count("key") == 1


def test_restore_clamps_to_the_count_now(tmp_path):
    lines = ['hana "One."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    state = interp.checkpoint()
    data = state.to_json()
    data["items"] = {"held": ["key", "match", "gone"], "counts": [4, 9, 7]}
    other = launched(story_game(tmp_path, lines, top=TOP))
    assert other.restore(GameState.from_json(data)).result is RestoreResult.OK
    assert (other.codex.count("key"), other.codex.count("match")) == (1, 3)
    assert other.codex.state() == ItemsState(("key", "match", "gone"), (1, 3, 7))


@pytest.mark.parametrize("items", [
    {"held": ["a"], "counts": [0]}, {"held": ["a"], "counts": [True]},
    {"held": ["a", "b"], "counts": [2]}, {"held": ["a"], "counts": [1_000_000]},
    {"held": ["a"], "counts": "2"}, {"held": ["a"], "other": [1]}])
def test_bad_saved_counts_are_refused(items):
    with pytest.raises(StateInvalid):
        ItemsState.from_json(items)


def test_saved_counts_of_one_are_the_plain_shape():
    assert ItemsState.from_json({"held": ["a"], "counts": [1]}) == ItemsState(("a",))
    assert ItemsState.from_json({"held": [], "counts": []}) is EMPTY_ITEMS


def test_items_errors_at_run_time(tmp_path):
    for index, (code, start) in enumerate((
            ('$ x = items.count(who)', 'there is no item named "coinz". Did you mean "coin"?'),
            ('$ x = getattr(items, "to" + "tal")', "there is no items.total."),
            ('$ x = items.count(len(who))', "items.count needs an item's name in quotes"))):
        program = story_game(tmp_path / str(index), ['$ who = "coinz"', code, 'hana "x"'],
                             top=TOP)
        interp = _start(program)
        failed = take_all(interp)[-1]
        assert type(failed) is StoryFailed and failed.error.code in ("E440", "E441")
        assert failed.error.message.startswith(start), failed.error.message


def test_a_story_variable_named_items_is_left_alone(tmp_path):
    lines = ['$ items = ["lantern", "pen"]', 'unlock item coin 3',
             '$ n = items.count("pen")', '$ c = codex.count("coin")', 'hana "x"']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    variables = interp.checkpoint().variables
    assert variables["items"] == ["lantern", "pen"]
    assert variables["n"] == 1 and variables["c"] == 3


def test_items_is_not_saved_as_a_variable(tmp_path):
    interp = _start(story_game(tmp_path, ['hana "x"'], top=TOP))
    assert "items" not in interp.checkpoint().variables
    assert repr(interp.G["items"]) == "<items>"

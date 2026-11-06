"""F64 round 2 at run time: using an item (``use <scene>``, ``UseItem``), where it may start,
saves inside a use's scene, going back and forward over a use, and ``show hotbar`` /
``hide hotbar`` (specs/F64-items/SPEC.md "Round 2")."""

from engine.runtime import itemuse
from engine.runtime.commands import Advance, Say, StepBack, StepForward
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.itemuse import NO_ITEM, NOT_HELD, NOT_NOW, UseItem
from engine.runtime.state import EMPTY_ITEMS, ItemsState
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import launched, story_game, take_all

TOP = ('lock item tea "Jasmine Tea" count 0 to 9 use drink_tea\n'
       'lock item key "Brass Key"\n'
       'lock item map "Old Map" use read_map\n')
AFTER = ('label drink_tea:\n'
         '    lock item tea\n'
         '    $ warm = warm + 1\n'
         '    hana "Warmth spreads through your hands."\n'
         '    return\n'
         'label read_map:\n'
         '    $ looked = True\n'
         '    return\n')


def _game(tmp_path, lines):
    program = story_game(tmp_path, ["$ warm = 0", "$ looked = False", *lines], top=TOP,
                         after=AFTER)
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    take_all(interp)
    return interp


def _lines(cmds):
    return [c.body.plain()[0].text for c in cmds if type(c) is Say]


def _post(interp, event):
    interp.post(event)
    interp.run(10_000)
    return take_all(interp)


def _use(interp, name):
    return _post(interp, UseItem(name, interp.current.sid))


def test_use_runs_the_scene_between_lines(tmp_path):
    interp = _game(tmp_path, ["unlock item tea 3", 'hana "One."', 'hana "Two."'])
    assert itemuse.why_not(interp, "tea") is None
    out = _use(interp, "tea")
    assert _lines(out) == ["Warmth spreads through your hands."]
    assert interp.codex.count("tea") == 2 and interp.G["warm"] == 1
    assert itemuse.in_use(interp) and itemuse.why_not(interp, "tea") == NOT_NOW  # no nesting
    out = _post(interp, Advance(interp.current.sid))
    assert _lines(out) == ["Two."]                  # back after the line it was used at


def test_use_refused(tmp_path):
    interp = _game(tmp_path, ['hana "One."', "unlock item tea", "unlock item key",
                              "menu:", '    "Go":', '        hana "Gone."'])
    assert itemuse.why_not(interp, "tea") == NOT_HELD
    assert itemuse.why_not(interp, "key") == NO_ITEM          # no use scene
    assert itemuse.why_not(interp, "nothing") == NO_ITEM
    line = interp.current.sid
    assert _use(interp, "tea") == [] and interp.current.sid == line
    _post(interp, Advance(line))                              # now at the menu
    assert itemuse.why_not(interp, "tea") == NOT_NOW
    assert _post(interp, UseItem("tea", line)) == []
    assert interp.codex.count("tea") == 1


def test_stale_use_ignored(tmp_path):
    interp = _game(tmp_path, ["unlock item tea", 'hana "One."', 'hana "Two."'])
    first = interp.current.sid
    _post(interp, Advance(first))
    assert _post(interp, UseItem("tea", first)) == []
    assert interp.codex.count("tea") == 1


def test_use_not_during_a_pause(tmp_path):
    interp = _game(tmp_path, ["unlock item tea", "pause 2.0", 'hana "One."'])
    assert interp.waiting_for is not None and itemuse.why_not(interp, "tea") == NOT_NOW


def test_scene_without_lines_and_rollback(tmp_path):
    interp = _game(tmp_path, ["unlock item map", 'hana "One."', 'hana "Two."'])
    one = interp.checkpoint()
    out = _use(interp, "map")
    assert _lines(out) == ["Two."] and interp.G["looked"] is True
    _post(interp, StepBack(1))
    assert interp.current.sid == one.position and interp.G["looked"] is False
    _post(interp, StepForward(1))                   # the remembered use replays
    assert interp.G["looked"] is True and interp.status is Status.WAITING


def test_back_and_forward_over_a_use(tmp_path):
    interp = _game(tmp_path, ["unlock item tea 2", 'hana "One."', 'hana "Two."'])
    one = interp.checkpoint()
    _use(interp, "tea")
    inside = interp.checkpoint()
    assert inside.items == ItemsState(("tea",), ()) and len(inside.call_stack) == 1
    _post(interp, StepBack(1))
    assert interp.checkpoint().position == one.position
    assert interp.codex.count("tea") == 2 and not interp.call_stack
    _post(interp, StepForward(1))
    assert interp.checkpoint().position == inside.position
    assert interp.codex.count("tea") == 1 and interp.G["warm"] == 1
    out = _post(interp, Advance(interp.current.sid))
    assert _lines(out) == ["Two."]


def test_save_inside_a_use_loads_and_returns(tmp_path):
    interp = _game(tmp_path, ["unlock item tea 2", 'hana "One."', 'hana "Two."'])
    _use(interp, "tea")
    saved = round_trip(interp.checkpoint())
    other = _game(tmp_path, ["unlock item tea 2", 'hana "One."', 'hana "Two."'])
    assert other.restore(saved).result is RestoreResult.OK
    take_all(other)
    assert other.codex.count("tea") == 1 and itemuse.in_use(other)
    out = _post(other, Advance(other.current.sid))
    assert _lines(out) == ["Two."] and not other.call_stack


def test_show_and_hide_hotbar_saved(tmp_path):
    interp = _game(tmp_path, ["show hotbar", 'hana "One."', "hide hotbar", 'hana "Two."'])
    shown = interp.checkpoint()
    assert interp.codex.bar_shown() and shown.items.bar
    assert round_trip(shown).items == ItemsState((), (), True)
    assert shown.items.to_json() == {"held": [], "bar": True}
    _post(interp, Advance(interp.current.sid))
    assert not interp.codex.bar_shown() and interp.checkpoint().items is EMPTY_ITEMS
    _post(interp, StepBack(1))
    assert interp.codex.bar_shown()
    interp.new_game(1)
    assert not interp.codex.bar_shown()


def test_usable_items_in_bag_order(tmp_path):
    interp = _game(tmp_path, ["unlock item map", "unlock item key", "unlock item tea",
                              'hana "One."'])
    assert itemuse.usable_items(interp) == ("map", "tea")


def test_saved_use_frame_is_marked_and_checked(tmp_path):
    interp = _game(tmp_path, ["unlock item tea 2", 'hana "One."', 'hana "Two."'])
    line = interp.current.sid
    _use(interp, "tea")
    data = interp.checkpoint().to_json()
    assert data["call_stack"][0]["sid"] == line + itemuse.USE_FRAME
    data["call_stack"][0]["sid"] = line                        # unmarked: no Call there
    from engine.runtime.state import GameState
    assert interp.restore(GameState.from_json(data)).result is RestoreResult.POSITION_NOT_FOUND

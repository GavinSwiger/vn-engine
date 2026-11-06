"""F62 round 1 at run time: ``points.rank`` (derived from the value, so saves and rollback
need nothing new) and change notices (``MeterNotice``, held like F21's ``CodexAdded``)."""

from engine.runtime.commands import Advance, MeterNotice, StepBack, StepForward, StoryFailed
from engine.runtime.points import MeterSpec, Points
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import launched, story_game, take_all

ALL = 1 << 30
TOP = 'points hana 0 to 10 ranks "Stranger" 0 "Friend" 4 "Close" 8\npoints bare\n'


def _start(program):
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    return interp


def _advance(interp):
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    return take_all(interp)


def test_rank_is_derived_from_the_value():
    spec = MeterSpec("hana", 0, 10, 0, True, (("Friend", 4), ("Close", 8)))
    assert [spec.rank(v) for v in (0, 3, 4, 7, 8, 10)] == ["", "", "Friend", "Friend",
                                                            "Close", "Close"]
    points = Points((spec,))
    assert points.rank("hana") == ""
    points.add("hana", 9)
    assert points.rank("hana") == "Close"


def test_rank_in_conditions_and_python(tmp_path):
    lines = ['$ seen = [points.rank("hana")]', "points hana += 4",
             '$ seen.append(points.rank("hana"))',
             'if points.rank("hana") == "Friend":', '    $ friend = True', 'hana "Hi."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    variables = interp.checkpoint().variables
    assert variables["seen"] == ["Stranger", "Friend"] and variables["friend"] is True


def test_rank_run_time_errors(tmp_path):
    for index, (call, start) in enumerate((('"bare"', "points.rank needs a meter with ranks"),
                                           ('"hanna"', 'there is no meter named "hanna"'))):
        program = story_game(tmp_path / str(index), [f"$ who = {call}",
                                                     "$ x = points.rank(who)", 'hana "x"'],
                             top=TOP)
        interp = launched(program)
        interp.new_game(42)
        interp.run(10_000)
        failed = take_all(interp)[-1]
        assert type(failed) is StoryFailed and failed.error.code == "E236"
        assert failed.error.message.startswith(start), failed.error.message


def test_notice_is_held_when_the_line_runs(tmp_path):
    lines = ['hana "One."', 'points hana += 1 "Hana will remember that."',
             'points hana -= 1 "She frowns."', 'points bare = 3', 'hana "Two."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    assert not [c for c in take_all(interp) if type(c) is MeterNotice]
    shown = _advance(interp)
    notices = [c for c in shown if type(c) is MeterNotice]
    assert notices == [MeterNotice("hana", "Hana will remember that."),
                       MeterNotice("hana", "She frowns.")]
    # the notice comes before the next line is shown
    assert shown.index(notices[-1]) < len(shown) - 1


def test_rollback_and_saves_need_nothing_new(tmp_path):
    lines = ['hana "One."', 'points hana += 5 "Hana will remember that."', 'hana "Two."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    take_all(interp)
    _advance(interp)
    state = interp.checkpoint()
    assert dict(state.points)["hana"] == 5
    assert round_trip(state) == state                                     # rank isn't saved
    # back: the meter (and so the rank) goes back; forward again: the notice isn't repeated
    interp.post(StepBack(1))
    interp.run(10_000)
    take_all(interp)
    assert interp.points.rank("hana") == "Stranger"
    interp.post(StepForward(1))
    while interp.busy:
        interp.run(10_000)
    again = take_all(interp)
    assert interp.points.rank("hana") == "Friend"
    assert not [c for c in again if type(c) is MeterNotice]

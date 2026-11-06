"""F63 round 2: ``ui/clockitem.ClockItem`` (two rows, right-aligned in a right corner, cut to
fit), ``app/clockcorner.ClockCorner`` (follows ``show clock``, pulses on ``ClockChanged``, a
cut after a reset; F11's "Day 4, Evening") and the save description. Layout uses F05's M20
metrics (17 units per character at 24)."""

from dataclasses import replace
from types import SimpleNamespace

from engine.app.clockcorner import KEY, ClockCorner, _listener, install_clock, uses_clock
from engine.app.saves import SaveService
from engine.core.storyclock import Calendar
from engine.runtime import clock as clock_mod
from engine.runtime.clock import ClockState
from engine.runtime.commands import Advance
from engine.ui.clockitem import ELLIPSIS, ClockItem, ClockReading, fit
from engine.ui.statuscorner import CornerStyle
from tests.runtime.effects_story import launched, story_game, take_all
from tests.ui.test_statuscorner import corner, game_shell

S, P = 24, 34                               # the corner text size and its pitch


def ctx(place="top_left"):
    return corner(reduce=True)._context(CornerStyle(), place)


def test_two_rows_cut_to_fit():
    item = ClockItem(lambda: ClockReading("Night 3", "Witching hour"))
    c = ctx()
    assert item.rows(c) == (("Night 3", 7 * 17), ("Witching hour", 13 * 17))
    assert item.measure(c) == (13 * 17, 2 * P)
    narrow = ClockItem(lambda: ClockReading("Night 3", "Witching hour"), narrow=lambda: 120.0)
    text, width = narrow.rows(c)[1]
    assert text.endswith(ELLIPSIS) and width <= 120
    assert fit("abc", 10, lambda t: 17 * len(t)) == ELLIPSIS
    assert ClockItem(lambda: None).measure(c) == (0.0, 0.0)


def _program(tmp_path, lines):
    return replace(story_game(tmp_path, lines), calendar=Calendar(
        parts=("Dusk", "Midnight"), day_text="Night {day}", place="top_left", day_card=False))


def _owner(tmp_path, lines):
    interp = launched(_program(tmp_path, lines))
    interp.new_game(42)
    interp.run(10_000)
    take_all(interp)
    shell, textbox = game_shell()
    app = SimpleNamespace(shell=shell, textbox=textbox, saves=None)
    return interp, shell, ClockCorner(app, interp)


def _advance(interp):
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    take_all(interp)


def test_the_corner_follows_show_clock_and_pulses_on_a_change(tmp_path):
    interp, shell, owner = _owner(tmp_path, ['"One."', "show clock", '"Two."', "clock next",
                                             '"Three."', "hide clock", '"Four."'])
    listener = _listener(owner)
    clock_mod.listen(listener)
    try:
        layer = shell.corner
        owner.sync()
        assert KEY not in layer.keys()
        _advance(interp)                                    # show clock
        owner.sync()                                        # the first fill: a cut
        assert layer.keys("top_left") == (KEY,)
        assert layer.item(KEY).reading() == ClockReading("Night 1", "Dusk")
        _advance(interp)                                    # clock next: live, and a pulse
        assert layer.item(KEY).reading() == ClockReading("Night 1", "Midnight")
        assert owner._changed
        owner.sync()
        assert not owner._changed
        _advance(interp)                                    # hide clock
        owner.sync()
        assert KEY not in [v.key for v in layer.views() if v.opacity == 1.0]
        # a reset (New Game, a load) drops it at once and refills as a cut
        interp.clock = ClockState(4, 1, True)
        owner.reset()
        assert KEY not in layer.keys()
        owner.sync()
        assert layer.keys("top_left") == (KEY,)
        assert layer.item(KEY).reading() == ClockReading("Night 4", "Midnight")
    finally:
        clock_mod.unlisten(listener)


def test_save_slots_read_the_story_time(tmp_path):
    interp, _shell, owner = _owner(tmp_path, ['"One."', "clock next", '"Two."'])
    assert owner.moment(interp.checkpoint()) == "Night 1, Dusk"
    state = replace(interp.checkpoint(), clock=ClockState(4, 1))
    assert owner.moment(state) == "Night 4, Midnight"
    plain, _s, other = _owner(tmp_path / "plain", ['"One."'])
    assert not uses_clock(plain.program) and other.moment(plain.checkpoint()) is None
    service = SimpleNamespace(_clock_provider=owner.moment)
    assert SaveService._with_clock(service, state, "Hana: Hi.") == (
        "Night 4, Midnight · Hana: Hi.")
    assert SaveService._with_clock(service, state, "") == "Night 4, Midnight"
    service._clock_provider = None
    assert SaveService._with_clock(service, state, "Hana: Hi.") == "Hana: Hi."


def test_install_wires_the_source_reset_and_provider(tmp_path):
    interp = launched(_program(tmp_path, ['"One."']))
    shell, textbox = game_shell()
    provided = []
    saves = SimpleNamespace(set_clock_provider=provided.append)
    owner = install_clock(SimpleNamespace(shell=shell, textbox=textbox, saves=saves), interp)
    assert provided == [owner.moment]
    assert install_clock(SimpleNamespace(), interp) is None

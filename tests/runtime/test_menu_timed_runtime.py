"""F51 step S2, the runtime contract of timed menus (``04-technical.md`` §2 OQ-1, §7.2; 07
I-1, I-7): AC-F51-07 (``ShowMenu.seconds``/``timeout``), 08 (reading the past drops the
time; loads, jumps, replays and back-then-forward before a pick don't), 09 (a timeout pick
is an ordinary ``Choose``), 10 (saves are unchanged), 11 (headless has no clock).

Template M (``tests/runtime/menu_story``) with the menu on lines 6–10: "Yes" and the
timeout choice "...".
"""

import json

from engine.runtime.commands import Choose, ShowMenu
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import RestoreResult
from engine.runtime.replay import ReplayRun
from engine.runtime.state import GameState
from tests.runtime.effects_story import take_all
from tests.runtime.menu_story import K, go, inputs, launched, load_m, menus, play
from tests.runtime.rollback_story import back, forward

TIMED = ('menu time 5:⏎[8]hana "Will you?"⏎[8]"Yes":⏎[12]$ lantern = "red"⏎'
         '[8]"..." timeout:⏎[12]$ lantern = "silent"')
UNTIMED = ('menu:⏎[8]hana "Will you?"⏎[8]"Yes":⏎[12]$ lantern = "red"⏎'
           '[8]"...":⏎[12]$ lantern = "silent"')
SILENCE = K("...")


def _program(tmp_path, M=TIMED):
    return load_m(tmp_path, M=M)


def _last_menu(commands) -> ShowMenu:
    found = menus(commands)
    assert found, commands
    return found[-1]


def _at_menu(program):
    interp, commands = play(program, "a")
    return interp, _last_menu(commands)


# --- AC-F51-07 — the first reach ---------------------------------------------------------------

def test_ac07_first_reach_carries_seconds_and_timeout(tmp_path):
    interp, cmd = _at_menu(_program(tmp_path / "t"))
    assert (cmd.seconds, cmd.timeout) == (5.0, SILENCE)
    assert interp.menu_open[0] == cmd
    _, plain = _at_menu(_program(tmp_path / "u", UNTIMED))
    assert (plain.seconds, plain.timeout) == (None, None)
    _, template = _at_menu(load_m(tmp_path / "m"))
    assert (template.seconds, template.timeout) == (None, None)


# --- AC-F51-08 — reading the past, and the ways back to full time --------------------------------

def test_ac08_reading_the_past_drops_the_time_and_everything_else_restarts_it(tmp_path):
    program = _program(tmp_path)
    rows: dict[str, tuple] = {}

    interp, _ = play(program, "a c1", to_end=False)              # at "After", picked "Yes"
    landed = _last_menu(back(interp, 1))                           # back onto the menu
    rows["back landing"] = (landed.seconds, landed.timeout)
    assert interp.menu_open[0] == landed                           # 07 I-7: one command
    back(interp, 1)                                                # "Before."
    through = _last_menu(forward(interp, 1))                       # forward onto the menu
    rows["forward through"] = (through.seconds, through.timeout)
    assert interp.menu_open[0] == through

    interp, cmd = _at_menu(program)                                # a save at the menu
    data = json.loads(json.dumps(interp.checkpoint().to_json()))
    fresh = launched(program)
    assert fresh.restore(GameState.from_json(data)).result is RestoreResult.OK
    loaded = _last_menu(take_all(fresh))
    rows["load"] = (loaded.seconds, loaded.timeout)

    interp, _ = play(program, "a c1", to_end=False)                # a flowchart-style jump:
    menu_state = interp.timeline.states[1]                         # a kept snapshot restored
    assert interp.restore(menu_state).result is RestoreResult.OK
    jumped = _last_menu(take_all(interp))
    rows["jump"] = (jumped.seconds, jumped.timeout)

    replay = launched(program)
    replay.new_game(42, replay=ReplayRun("start"))
    replay.run(10_000)
    replay_cmds = take_all(replay) + go(replay, "a")
    rows["replay"] = (_last_menu(replay_cmds).seconds, _last_menu(replay_cmds).timeout)

    interp, _ = _at_menu(program)                                  # back before a pick
    back(interp, 1)
    again = _last_menu(forward(interp, 1))
    rows["back then forward, unpicked"] = (again.seconds, again.timeout)

    assert rows == {"back landing": (None, None), "forward through": (None, None),
                    "load": (5.0, SILENCE), "jump": (5.0, SILENCE), "replay": (5.0, SILENCE),
                    "back then forward, unpicked": (5.0, SILENCE)}


# --- AC-F51-09 — a timeout pick is a pick --------------------------------------------------------

def test_ac09_timeout_choose_equals_clicking_that_choice(tmp_path):
    program = _program(tmp_path)
    timed_out, cmd = _at_menu(program)
    timed_out.post(Choose(cmd.sid, cmd.timeout))                   # what the clock posts
    timed_out.run(10_000)
    clicked, _ = _at_menu(program)
    go(clicked, "c2")                                              # the player picks "..."
    assert timed_out.checkpoint().to_json() == clicked.checkpoint().to_json()
    assert timed_out.history.entries == clicked.history.entries
    assert [e.text for e in timed_out.history.entries[-2:]] == ["...", "After: silent."]
    assert timed_out.persistent.was_chosen(cmd.sid, SILENCE)
    assert clicked.persistent.was_chosen(cmd.sid, SILENCE)
    assert timed_out.G["lantern"] == "silent"


# --- AC-F51-10 — saves are unchanged -------------------------------------------------------------

def test_ac10_a_save_at_a_timed_menu_is_an_f07_save(tmp_path):
    timed, _ = _at_menu(_program(tmp_path / "t"))
    untimed, _ = _at_menu(_program(tmp_path / "u", UNTIMED))
    data = timed.checkpoint().to_json()
    assert data == untimed.checkpoint().to_json()                  # same sid and keys
    assert "seconds" not in json.dumps(data) and "timeout" not in json.dumps(data)
    fresh = launched(_program(tmp_path / "t"))
    assert fresh.restore(GameState.from_json(json.loads(json.dumps(data)))).result \
        is RestoreResult.OK
    assert _last_menu(take_all(fresh)).seconds == 5.0


# --- AC-F51-11 — headless has no clock -----------------------------------------------------------

def test_ac11_headless_waits_for_the_inputs_pick(tmp_path):
    program = _program(tmp_path)
    for budget in (10, 100_000):
        commands = run_headless(program, seed=42, inputs=inputs("a"), max_lines=budget)
        assert type(commands[-1]) is ShowMenu and commands[-1].seconds == 5.0
    commands = run_headless(program, seed=42, inputs=inputs("a c1"))
    assert "After: red." in [getattr(c, "body", None) and "".join(
        s.text for s in c.body.plain()) for c in commands]

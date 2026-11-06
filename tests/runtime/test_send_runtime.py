"""F65 round 2 at run time: ``send`` delivers through the trigger core's ``message`` kind
into one thread per contact with an arrival notice and an unread count, ``open`` is a story
wait, and both are story steps: saved, loaded, rolled back and re-run forward exactly; a round
1 save's per-chat rows load as each contact's thread (``runtime/send.py``,
``runtime/inbox.py``, ``Codex.inbox``)."""

import copy
import json
from dataclasses import replace

import pytest

from engine.core.storyclock import Calendar
from engine.runtime.commands import (Advance, MessageArrived, OpenInbox, StepBack,
                                     StepForward, StoryFailed, StoryWait, WaitDone)
from engine.runtime.errors import StoryError
from engine.runtime.inbox import (CHAT_KEY, Delivery, InboxLine, build_delivery,
                                  deliveries_from_json, deliveries_json, group_threads)
from engine.runtime.interpreter import Status
from engine.runtime.state import EMPTY_ITEMS, ItemsState, StateInvalid
from engine.runtime.triggers import EMPTY_TRIGGERS
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import launched, story_game, take_all

TOP = ('lock contact hana "Hana" on pigeon\nlock contact ren "Ren"\n'
       'define invite = ["Meet me at the bridge.", "Bring the red one.", {"me": "I will."}]\n'
       'define late = "Running late!"\n')


def _start(program, calendar=None):
    if calendar is not None:
        program = replace(program, calendar=calendar)
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    return interp


def _advance(interp):
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    return take_all(interp)


def _arrived(commands):
    return [c for c in commands if isinstance(c, MessageArrived)]


def test_send_delivers_a_message_into_the_contacts_thread(tmp_path):
    lines = ['"Morning."', "send invite from hana", '"Breakfast."', "send late from ren",
             "send late from ren on radio", '"Noon."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    take_all(interp)
    out = _advance(interp)
    (notice,) = _arrived(out)
    assert notice == MessageArrived("hana", "Hana", "pigeon", None, "hana")
    codex = interp.codex
    (delivery,) = codex.deliveries()
    assert (delivery.sender, delivery.message, delivery.contact, delivery.device,
            delivery.time) == ("hana", "invite", "Hana", "pigeon", "")
    assert [(ln.side, ln.name, ln.text) for ln in delivery.lines] == [
        ("them", "Hana", "Meet me at the bridge."), ("them", "Hana", "Bring the red one."),
        ("me", "", "I will.")]
    assert codex.unread() == 1 and codex.listed("chat") == ("hana",)
    # Nothing stays armed: the trigger fired at once, so the save is as before the core.
    assert interp.triggers == EMPTY_TRIGGERS and "triggers" not in interp.checkpoint().to_json()
    out = _advance(interp)
    assert [(n.contact, n.device) for n in _arrived(out)] == [("ren", ""), ("ren", "radio")]
    # Ren's thread is the newest; his two messages are one thread, oldest first.
    ren, hana = codex.inbox()
    assert (ren.key, ren.title, len(ren.parts), hana.key) == ("ren", "Ren", 2, "hana")
    assert [d.device for d in ren.parts] == ["", "radio"]
    assert codex.unread() == 3 and codex.thread_unread("ren") == 2
    # Reading marks every delivery of the thread (the page's mark_read), kept across a load.
    for d in ren.parts:
        assert codex.mark_delivery_read(d.key)
    assert codex.unread() == 1 and codex.thread_unread("ren") == 0


def test_the_date_comes_with_the_message_when_the_game_uses_the_clock(tmp_path):
    lines = ['"One."', "clock next day", "send late from ren", '"Two."']
    interp = _start(story_game(tmp_path, lines, top=TOP),
                    Calendar(parts=("Dusk", "Midnight"), day_text="Night {day}",
                             day_card=False))
    take_all(interp)
    _advance(interp)
    (delivery,) = interp.codex.deliveries()
    assert delivery.time == "Night 2"


def test_send_is_saved_rolled_back_and_rerun_forward_exactly(tmp_path):
    lines = ['"One."', "send invite from hana", '"Two."', "send late from ren", '"Three."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    take_all(interp)
    one = interp.checkpoint()
    _advance(interp)
    two = interp.checkpoint()
    _advance(interp)
    three = interp.checkpoint()
    assert len(three.items.inbox) == 2 and one.items == EMPTY_ITEMS
    # Going back before a send takes the message out; going forward brings it back with
    # no second notice (the quiet re-run's holds are dropped).
    take_all(interp)
    interp.post(StepBack(1))
    interp.run(10_000)
    take_all(interp)
    assert [t.key for t in interp.codex.inbox()] == ["hana"]
    interp.post(StepBack(1))
    interp.run(10_000)
    take_all(interp)
    assert interp.codex.deliveries() == ()
    interp.post(StepForward(2))
    while interp.busy:
        interp.run(10_000)
    out = take_all(interp)
    assert interp.checkpoint().items == three.items and not _arrived(out)
    # Saved exactly, from and message included; a load puts the threads back.
    assert round_trip(three) == three
    saved = three.to_json()["inbox"]
    assert [(d["from"], d["message"]) for d in saved] == [("hana", "invite"), ("ren", "late")]
    interp.restore(round_trip(two))
    interp.run(10_000)
    assert [t.key for t in interp.codex.inbox()] == ["hana"]
    interp.restore(round_trip(three))
    interp.run(10_000)
    assert [t.key for t in interp.codex.inbox()] == ["ren", "hana"]
    # New Game empties the Inbox.
    interp.new_game(1)
    assert interp.codex.deliveries() == () and interp.codex.unread() == 0


def test_open_is_a_story_wait_until_the_inbox_closes(tmp_path):
    lines = ['"One."', "send late from ren", "open pigeon", '"Two."', "open inbox", '"Three."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    take_all(interp)
    out = _advance(interp)
    (wait,) = [c for c in out if isinstance(c, OpenInbox)]
    assert isinstance(wait, StoryWait) and wait.look == "pigeon" and wait.seconds is None
    assert interp.status is Status.WAITING and interp.waiting_for == wait.wait_id
    before = interp.checkpoint()
    interp.post(WaitDone(wait.wait_id))
    interp.run(10_000)
    out = take_all(interp)
    assert interp.current.line == 10                     # "Two."
    # No checkpoint at open: while it waits, the last checkpoint is the line before it.
    assert before.position == interp.program.statements_in("start").__next__().sid
    (second,) = [c for c in _advance(interp) if isinstance(c, OpenInbox)]
    assert second.look is None


def test_a_message_that_goes_wrong_while_the_game_runs_is_e453(tmp_path):
    top = TOP + 'default note = "Hi."\n'
    lines = ['"One."', '$ note = {"a": 1}', "send note from ren", '"Two."']
    interp = _start(story_game(tmp_path, lines, top=top))
    take_all(interp)
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    assert interp.status is Status.FAILED
    (failed,) = [c for c in take_all(interp) if isinstance(c, StoryFailed)]
    error = failed.error
    assert isinstance(error, StoryError) and error.code == "E453"
    assert "message note must be text" in error.message and error.line == 10


def test_round_1_saves_load_as_threads_per_contact():
    # A round 1 save: two chats with Sayori and one with Natsuki, one row per chat.
    sid = "start/8dca50f2c35b"
    one = build_delivery(sid, (), "Sayori", "11:42 PM", "phone",
                         [("time", "", "11:42 PM"), ("them", "Sayori", "you awake?")])
    two = build_delivery("start/0123456789ab", (one,), "Natsuki", "", "phone",
                         [("them", "Natsuki", "hey")])
    three = build_delivery(sid, (one, two), "Sayori", "1 AM", "phone",
                           [("them", "Sayori", "still up?")])
    old = deliveries_json((one, two, three))
    assert all(set(d) == {"key", "sid", "contact", "time", "device", "lines"} for d in old)
    loaded = ItemsState.from_json({"held": [], "inbox": json.loads(json.dumps(old))}).inbox
    assert loaded == (one, two, three)
    sayori, natsuki = group_threads(loaded, {})
    assert (sayori.key, sayori.title, sayori.parts) == (CHAT_KEY + "Sayori", "Sayori",
                                                        (one, three))
    assert natsuki.parts == (two,)
    # A declared contact with that shown name takes the chats into its thread.
    (sayori,) = group_threads((one, three), {"sayori": "Sayori"})
    assert (sayori.key, sayori.sender, sayori.title) == ("sayori", "sayori", "Sayori")


def test_saved_from_and_message_are_checked():
    sent = Delivery("0" * 16 + ".1", "start/8dca50f2c35b", "Hana", "", "",
                    (InboxLine("them", "Hana", "Hi."),), "hana", "invite")
    good = deliveries_json((sent,))
    assert good[0]["from"] == "hana" and good[0]["device"] == ""
    assert deliveries_from_json(json.loads(json.dumps(good))) == (sent,)
    for key, value in (("from", ""), ("from", "a b"), ("message", 3), ("from", "x" * 65)):
        data = copy.deepcopy(good)
        data[0][key] = value
        with pytest.raises(StateInvalid):
            ItemsState.from_json({"held": [], "inbox": data})


def test_a_headless_run_passes_open_and_records_the_notice(tmp_path):
    from engine.runtime.headless import run_headless
    program = story_game(tmp_path, ["send invite from hana", "open inbox", '"End."'], top=TOP)
    commands = run_headless(program, seed=1)
    assert [c.contact for c in commands if isinstance(c, MessageArrived)] == ["hana"]
    assert [c.look for c in commands if isinstance(c, OpenInbox)] == [None]

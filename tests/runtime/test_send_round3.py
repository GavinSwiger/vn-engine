"""F65 round 3 at run time: ``send … after 1 day`` / ``after 2 scenes`` hold a message in the
trigger core until the story clock or the scene count gets there (one notice, on arrival, none
on a quiet re-run), and a message that ends with an ask waits for the player's reply in the
Inbox: a reply is a step of its own like a pick (History, rollback, forward), read by
``inbox.reply("invite")``; saves keep both and older saves load (``runtime/send.py``)."""

from dataclasses import replace

import pytest

from engine.core.storyclock import Calendar
from engine.runtime.commands import Advance, MessageArrived, StepBack, StepForward, WaitDone
from engine.runtime.inbox import deliveries_from_json, deliveries_json
from engine.runtime.interpreter import Status
from engine.runtime.send import ReplyMessage, can_reply, pending
from engine.runtime.state import GameState
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import launched, story_game, take_all

TOP = ('lock contact hana "Hana" on pigeon\nlock contact ren "Ren"\n'
       'define invite = ["Meet me at the bridge.", {"ask": "come", "yes": "I will.", '
       '"no": "Not this year."}]\n'
       'define late = "Running late!"\n')
CAL = Calendar(parts=("Day", "Night"), day_card=False)


def _start(program, calendar=CAL):
    interp = launched(replace(program, calendar=calendar))
    interp.new_game(42)
    interp.run(10_000)
    take_all(interp)
    return interp


def _advance(interp):
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    return take_all(interp)


def _arrived(commands):
    return [c for c in commands if isinstance(c, MessageArrived)]


def _forward(interp, n):
    interp.post(StepForward(n))
    while interp.busy:
        interp.run(10_000)
    return take_all(interp)


def _back(interp, n=1):
    interp.post(StepBack(n))
    interp.run(10_000)
    return take_all(interp)


def _say(interp):
    return interp.current.body.plain()[0].text if interp.current.body.plain() else ""


# --- Delays ------------------------------------------------------------------------------------

def test_after_days_waits_for_the_clock_and_notices_once(tmp_path):
    lines = ['"Morning."', "send late from ren after 1 day", '"Noon."', "clock next",
             '"Night."', "clock next", '"Next morning."', '"Later."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    out = _advance(interp)                                      # past the send: held
    assert not _arrived(out) and interp.codex.deliveries() == ()
    assert pending(interp) == ["late from ren: day 2"]
    held = interp.checkpoint()
    assert held.to_json()["triggers"]["armed"][0]["day"] == 2
    assert round_trip(held) == held
    out = _advance(interp)                                      # Night: still day 1
    assert not _arrived(out) and interp.codex.deliveries() == ()
    out = _advance(interp)                                      # day 2: it arrives
    (notice,) = _arrived(out)
    assert notice.contact == "ren"
    (delivery,) = interp.codex.deliveries()
    assert delivery.time == "Day 2" and pending(interp) == []
    arrived = interp.checkpoint()
    # Back before the day changed takes it out again; forward brings it back, no notice.
    _back(interp)
    assert interp.codex.deliveries() == () and pending(interp) == ["late from ren: day 2"]
    out = _forward(interp, 1)
    assert interp.checkpoint().items == arrived.items and not _arrived(out)
    assert interp.checkpoint().triggers == arrived.triggers
    # A load of the held step waits again and delivers on day 2 with its notice.
    interp.restore(round_trip(held))
    interp.run(10_000)
    take_all(interp)
    _advance(interp)
    out = _advance(interp)
    assert len(_arrived(out)) == 1 and len(interp.codex.deliveries()) == 1


def test_after_scenes_counts_scenes_entered(tmp_path):
    after = ('label two:\n    "Two."\n    jump three\n'
             'label three:\n    "Three."\n    jump four\n'
             'label four:\n    "Four."\n')
    lines = ["send late from ren after 2 scenes", '"One."', "jump two"]
    interp = _start(story_game(tmp_path, lines, top=TOP, after=after))
    assert pending(interp) == ["late from ren: in 2 scenes"]
    out = _advance(interp)                                      # into two: 1 left
    assert not _arrived(out) and pending(interp) == ["late from ren: in 1 scene"]
    out = _advance(interp)                                      # into three: it arrives
    assert len(_arrived(out)) == 1 and len(interp.codex.deliveries()) == 1
    three = interp.checkpoint()
    _back(interp, 2)
    assert interp.codex.deliveries() == ()
    out = _forward(interp, 2)
    assert not _arrived(out) and interp.checkpoint().items == three.items
    assert interp.checkpoint().triggers == three.triggers


def test_a_message_sent_without_after_still_arrives_at_once(tmp_path):
    interp = _start(story_game(tmp_path, ["send late from ren", '"One."'], top=TOP))
    assert len(interp.codex.deliveries()) == 1 and pending(interp) == []
    assert "triggers" not in interp.checkpoint().to_json()


# --- Replies -----------------------------------------------------------------------------------

READ = ['if inbox.reply("invite") == "yes":', '    "She will come."', "else:",
        '    "No answer yet."']


def test_a_reply_is_a_step_with_history_and_read_by_inbox_reply(tmp_path):
    lines = ["send invite from hana", '"One."', *READ]
    interp = _start(story_game(tmp_path, lines, top=TOP))
    (delivery,) = interp.codex.deliveries()
    assert delivery.ask == (("yes", "I will."), ("no", "Not this year.")) and delivery.waiting
    assert [ln.text for ln in delivery.lines] == ["Meet me at the bridge."]
    assert can_reply(interp)
    before = interp.checkpoint()
    cursor = interp.timeline.cursor
    interp.post(ReplyMessage(delivery.key, "maybe"))            # not an option: ignored
    interp.post(ReplyMessage("nope.1", "yes"))                  # no such delivery: ignored
    assert interp.checkpoint() is before
    interp.post(ReplyMessage(delivery.key, "yes"))
    take_all(interp)
    (picked,) = interp.codex.deliveries()
    assert picked.reply == "yes" and not picked.waiting and picked.reply_text() == "I will."
    after = interp.checkpoint()
    assert after is not before and after.position == before.position
    assert interp.timeline.cursor == cursor + 1
    assert after.history.entries[-1].kind == "choice"
    assert after.history.entries[-1].text == "I will."
    assert interp.status is Status.WAITING
    interp.post(ReplyMessage(delivery.key, "no"))               # answered: ignored
    assert interp.checkpoint() is after
    _advance(interp)
    assert "She will come." in str(interp.current.body)
    # Saved with the reply; a load reads it.
    assert round_trip(after) == after
    saved = after.to_json()["items"]["inbox"][0]
    assert saved["ask"] == [["yes", "I will."], ["no", "Not this year."]]
    assert saved["reply"] == "yes"
    # Back once: the same line, unanswered; forward gives the same reply again.
    _back(interp)
    assert interp.checkpoint().items == after.items
    _back(interp)
    assert interp.current.sid == before.position and interp.codex.deliveries()[0].waiting
    assert interp.history.entries[-1].kind != "choice"
    _forward(interp, 2)
    assert interp.codex.deliveries()[0].reply == "yes"
    assert "She will come." in str(interp.current.body)


def test_no_reply_reads_as_empty_and_the_story_goes_its_other_way(tmp_path):
    lines = ["send invite from hana", '"One."', *READ]
    interp = _start(story_game(tmp_path, lines, top=TOP))
    _advance(interp)
    assert "No answer yet." in str(interp.current.body)


def test_a_line_ask_and_a_list_ask_reply_with_their_text(tmp_path):
    top = TOP + 'define note = ["Tea?", {"ask": ["Yes please", "No thanks"]}]\n'
    lines = ['send late from ren ask "On my way." "Start without me."', "send note from hana",
             '"One."', '$ got = (inbox.reply("late"), inbox.reply("note"))', '"Two."']
    interp = _start(story_game(tmp_path, lines, top=top))
    late, note = interp.codex.deliveries()
    assert late.ask == (("On my way.", "On my way."), ("Start without me.", "Start without me."))
    interp.post(ReplyMessage(late.key, "Start without me."))
    interp.post(ReplyMessage(note.key, "Yes please"))
    _advance(interp)
    assert interp.G["got"] == ("Start without me.", "Yes please")


def test_a_reply_in_an_open_wait_joins_the_next_step_and_comes_back_forward(tmp_path):
    lines = ['"One."', "send invite from hana", "open pigeon", '"Two."', '"Three."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    out = _advance(interp)
    wait = next(c for c in out if hasattr(c, "wait_id"))
    assert interp.waiting_for == wait.wait_id and can_reply(interp)
    cursor = interp.timeline.cursor
    key = interp.codex.deliveries()[0].key
    interp.post(ReplyMessage(key, "no"))
    assert interp.timeline.cursor == cursor                     # no step of its own
    interp.post(WaitDone(wait.wait_id))
    interp.run(10_000)
    take_all(interp)
    two = interp.checkpoint()
    assert two.items.inbox[0].reply == "no"
    _advance(interp)
    _back(interp, 2)
    assert interp.codex.deliveries() == ()
    matches = interp.timeline.matches
    _forward(interp, 2)
    assert interp.codex.deliveries()[0].reply == "no"
    assert interp.timeline.matches == matches + 2               # the remembered path kept
    assert interp.timeline.cursor == len(interp.timeline.states) - 1


def test_no_reply_at_a_menu(tmp_path):
    lines = ["send invite from hana", "menu:", '    "Go":', '        "Went."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    assert not can_reply(interp)
    key = interp.codex.deliveries()[0].key
    interp.post(ReplyMessage(key, "yes"))
    assert interp.codex.deliveries()[0].waiting


def test_inbox_reply_needs_a_name_and_cant_be_changed(tmp_path):
    for line in ['$ x = inbox.reply(3)', '$ inbox.x = 1']:
        interp = _start(story_game(tmp_path, ['"One."', line, '"Two."'], top=TOP))
        _advance(interp)
        assert interp.status is Status.FAILED


def test_saved_ask_and_reply_are_checked_and_old_saves_load():
    good = [{"key": "0123456789abcdef.1", "sid": "start/0123456789ab", "contact": "Hana",
             "time": "", "device": "", "lines": [["them", "Hana", "Hi"]], "from": "hana",
             "message": "invite", "ask": [["yes", "I will."], ["no", "No."]], "reply": "no"}]
    (d,) = deliveries_from_json(good)
    assert d.reply == "no" and deliveries_json((d,)) == good
    old = [{k: v for k, v in good[0].items() if k not in ("ask", "reply")}]
    (d,) = deliveries_from_json(old)
    assert d.ask == () and d.reply == "" and deliveries_json((d,)) == old
    for bad in ({"reply": "maybe"}, {"ask": [], "reply": None}, {"ask": [["a", "x"], ["a", "y"]]},
                {"ask": [["a", "x"]] * 5}, {"ask": [["a", ""]]}):
        item = dict(good[0])
        item.pop("reply")
        item.update(bad)
        with pytest.raises(ValueError):
            deliveries_from_json([item])
    item = dict(old[0], reply="no")
    with pytest.raises(ValueError):
        deliveries_from_json([item])


def test_a_round_2_save_state_loads(tmp_path):
    lines = ["send late from ren", '"One."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    data = interp.checkpoint().to_json()
    assert "ask" not in data["items"]["inbox"][0]
    assert GameState.from_json(data) == interp.checkpoint()

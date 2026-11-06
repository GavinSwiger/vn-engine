"""A message waiting to arrive (``send … after``) survives a game update (F65; v1 review M6).

Its trigger is keyed by the contact and the message (``script/inbox.message_name``), not by
the ``send`` line's sid, so an update that edits the line keeps it; a key the update no
longer declares is adopted when it is a development save's sid or a shifted occurrence, and
otherwise kept (never dropped) with a WARNING."""

import logging
from dataclasses import replace

from engine.runtime.interpreter import RestoreResult
from engine.runtime.send import pending
from engine.runtime.triggers import Armed, TriggerState
from engine.script.inbox import SendStep, message_name
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import story_game
from tests.runtime.test_send_round3 import TOP, _advance, _arrived, _start

BEFORE = ['"Morning."', "send late from ren after 1 day", '"Noon."', "clock next",
          '"Night."', "clock next", '"Next morning."']


def _held(tmp_path, lines=BEFORE):
    """The story of ``lines`` at "Noon.", the message waiting (a saved state)."""
    interp = _start(story_game(tmp_path / "v1", lines, top=TOP))
    _advance(interp)
    assert pending(interp) == ["late from ren: day 2"]
    return interp, round_trip(interp.checkpoint())


def _loaded(tmp_path, lines, state):
    """A fresh interpreter of the updated story ``lines``, with ``state`` loaded."""
    interp = _start(story_game(tmp_path / "v2", lines, top=TOP))
    assert interp.restore(state).result is RestoreResult.OK
    interp.run(10_000)
    _ = interp.take_commands(1 << 30)
    return interp


def _sends(interp):
    return [s for s in interp.program.iter_statements() if isinstance(s, SendStep)]


def _arrives_on_day_2(interp):
    assert interp.codex.deliveries() == ()
    assert not _arrived(_advance(interp))                       # Night: still day 1
    (notice,) = _arrived(_advance(interp))                      # day 2
    assert notice.contact == "ren"
    (delivery,) = interp.codex.deliveries()
    assert (delivery.sender, delivery.message) == ("ren", "late")


def test_the_key_is_the_contact_and_message_not_the_sid(tmp_path):
    _, state = _held(tmp_path)
    (armed,) = state.triggers.armed
    assert armed.id == "message:ren/late" == "message:" + message_name("ren", "late")
    assert message_name("ren", "late", 3) == "ren/late~3"
    long = message_name("c" * 64, "m" * 64)
    assert len(long) == 80 and long != message_name("c" * 64, "m" * 63 + "n")


def test_a_pending_message_arrives_after_an_update_edits_its_line(tmp_path):
    first, state = _held(tmp_path)
    after = ['"Morning."', "send late from ren on pigeon after 2 days ask \"OK\"", '"Noon."',
             "clock next", '"Night."', "clock next", '"Next morning."']
    interp = _loaded(tmp_path, after, state)
    (old,), (new,) = _sends(first), _sends(interp)
    assert old.sid != new.sid                       # keyed by the sid, it would be lost
    assert interp.checkpoint().triggers == state.triggers
    assert pending(interp) == ["late from ren: day 2"]          # its saved moment
    _arrives_on_day_2(interp)


def test_a_development_save_keyed_by_the_sid_is_adopted(tmp_path):
    first, state = _held(tmp_path)
    (send,) = _sends(first)
    (armed,) = state.triggers.armed
    dev = replace(state, triggers=TriggerState((replace(armed, id=f"message:{send.sid}"),)))
    interp = _loaded(tmp_path, BEFORE, round_trip(dev))
    assert [a.id for a in interp.checkpoint().triggers.armed] == ["message:ren/late"]
    _arrives_on_day_2(interp)


def test_a_shifted_occurrence_is_adopted(tmp_path):
    first = _start(story_game(tmp_path / "v1", ['"Dawn."', "send late from ren", *BEFORE],
                              top=TOP))
    _advance(first)                                 # past the first send: delivered
    _advance(first)                                 # past the second: waiting
    assert pending(first) == ["late from ren: day 2"]
    first_state = round_trip(first.checkpoint())
    (armed,) = first_state.triggers.armed
    assert armed.id == "message:ren/late~2"
    interp = _loaded(tmp_path, BEFORE, first_state)             # the first send removed
    assert [a.id for a in interp.checkpoint().triggers.armed] == ["message:ren/late"]
    assert len(interp.codex.deliveries()) == 1                  # the first, delivered
    assert not _arrived(_advance(interp))
    assert len(_arrived(_advance(interp))) == 1 and len(interp.codex.deliveries()) == 2


def test_an_orphan_is_kept_and_logged_never_dropped(tmp_path, caplog):
    _, state = _held(tmp_path)
    gone = ['"Morning."', '"Noon."', "clock next", '"Night."', "clock next",
            '"Next morning."']
    with caplog.at_level(logging.WARNING):
        interp = _loaded(tmp_path, gone, state)
    assert interp.checkpoint().triggers == state.triggers       # still saved
    assert [r for r in caplog.records if "message:ren/late" in r.getMessage()]
    _advance(interp)
    _advance(interp)
    assert interp.codex.deliveries() == ()
    # A later update that sends it again: it arrives.
    back = _loaded(tmp_path / "again", BEFORE, round_trip(interp.checkpoint()))
    assert [a.id for a in back.checkpoint().triggers.armed] == ["message:ren/late"]
    assert isinstance(back.checkpoint().triggers.armed[0], Armed)

"""F65 round 1: codex kinds and chats you can reread, at run time (``core/codexkinds``,
``runtime/inbox``, ``Codex``'s threads, ``ItemsState.inbox``).

The F26 template (``tests/fixtures/F26/template``) plays its phone chat with the bundled
``PhoneChat`` signature; the chat's lines join History and the chat joins the Inbox, saved
and rolled back with the story, and a save from before F65 loads with an empty inbox."""

import copy
import json
from types import SimpleNamespace

import pytest

from engine.core import codexkinds
from engine.core.codexkinds import CodexKind, codex_kinds, page_kinds
from engine.runtime import inbox
from engine.runtime.inbox import (InboxLine, Delivery, build_delivery, kept, phone_lines,
                                  record_chat, deliveries_from_json, deliveries_json)
from engine.runtime.interpreter import RestoreResult
from engine.runtime.state import EMPTY_ITEMS, GameState, ItemsState, StateInvalid
from engine.script import codex as script_codex
from tests.minigames.bundled.test_phone_headless import LINE_P, _game
from tests.runtime.minigame_story import at_a, finish, said, to_line

CHAT = ["you awake?",
        {"ask": "awake", "yes": ["Yeah.", "good", {"time": "1 AM"}], "no": "Go to sleep.",
         "ignore": True},
        {"Natsuki": "hey both"},
        {"me": "hi"},
        {"ask": "walk", "sure": "Sure."},
        "bye"]
ARGS = {"chat": CHAT, "contact": "Sayori", "time": "11:42 PM"}


# --- Codex kinds ------------------------------------------------------------------------------

def test_codex_kinds_registry_describes_tips_items_and_chats():
    assert [k.name for k in codex_kinds()][:3] == ["tip", "item", "chat"]
    assert [k.name for k in page_kinds("codex")] == ["tip", "item"]
    assert [k.name for k in page_kinds("inbox")] == ["chat", "contact"]     # round 2
    tip, item, chat = codexkinds.TIP, codexkinds.ITEM, codexkinds.CHAT
    assert (tip.kept, tip.on_title, tip.order, tip.tab_word) == (True, True, "declared",
                                                                 "codex_tips")
    assert (item.kept, item.order, "count" in item.shows) == (False, "obtained", True)
    assert (chat.declared, chat.order, chat.kit_title) == (False, "newest",
                                                           ("messages", "title"))
    # The script's words and default tabs come from the declared kinds: unchanged.
    assert script_codex.KINDS == ("tip", "item")
    assert script_codex.DEFAULT_WORDS == {"tip": "codex_tips", "item": "codex_items"}
    with pytest.raises(ValueError):
        CodexKind("x", "x", "x", order="random")
    with pytest.raises(ValueError):
        CodexKind("x", "x", "x", shows=frozenset({"sound"}))
    # Registering again with the same name replaces (a reload is harmless).
    again = codexkinds.register_codex_kind(chat)
    assert again is chat and [k.name for k in codex_kinds()].count("chat") == 1


# --- The chat as the player saw it ------------------------------------------------------------

def test_phone_lines_follow_the_picks():
    contact, time, lines = phone_lines(ARGS, {"awake": "yes", "walk": "sure"})
    assert (contact, time) == ("Sayori", "11:42 PM")
    assert lines == [("time", "", "11:42 PM"), ("them", "Sayori", "you awake?"),
                     ("me", "", "Yeah."), ("them", "Sayori", "good"), ("time", "", "1 AM"),
                     ("them", "Natsuki", "hey both"), ("me", "", "hi"), ("me", "", "Sure."),
                     ("them", "Sayori", "bye")]
    # A plain reply; then an unreached ask ends the chat.
    assert phone_lines(ARGS, {"awake": "no", "walk": None})[2][2:5] == [
        ("me", "", "Go to sleep."), ("them", "Natsuki", "hey both"), ("me", "", "hi")]
    assert len(phone_lines(ARGS, {"awake": "no", "walk": None})[2]) == 5
    # Ignore ends it at the ask; so does a result that isn't a dict.
    for result in ({"awake": "ignore", "walk": None}, None, "x"):
        assert phone_lines(ARGS, result)[2] == [("time", "", "11:42 PM"),
                                                ("them", "Sayori", "you awake?")]


def test_build_thread_keys_limits_and_empty_chats():
    sid = "start/8dca50f2c35b"
    one = build_delivery(sid, (), "Sayori", "", "phone", [("them", "Sayori", "hi")])
    two = build_delivery(sid, (one,), "Sayori", "", "phone", [("them", "Sayori", "hi")])
    assert one.key.endswith(".1") and two.key.endswith(".2") and one.key[:16] == two.key[:16]
    other = build_delivery("start/0123456789ab", (one,), "S", "", "phone", [("me", "", "x")])
    assert other.key.endswith(".1") and other.key[:16] != one.key[:16]
    # Nothing shown but a time: no thread. Blank lines drop; long text is cut with "…".
    assert build_delivery(sid, (), "S", "1 AM", "phone", [("time", "", "1 AM")]) is None
    long = build_delivery(sid, (), "S", "", "phone", [("them", "S", "x" * 3000),
                                                    ("them", "S", "  "), ("me", "", "\ud800")])
    assert [len(ln.text) for ln in long.lines] == [inbox.TEXT_MAX, 1]
    assert long.lines[0].text.endswith("…") and long.lines[1].text == "�"
    # The oldest threads drop past the caps; the newest stays.
    many = tuple(build_delivery(sid, (), "S", "", "phone", [("me", "", "x")])
                 for _ in range(inbox.DELIVERIES_MAX + 3))
    assert kept(many) == many[3:]
    big = Delivery("0" * 16 + ".1", sid, "S", "", "phone",
                      (InboxLine("me", "", "x" * inbox.TEXT_MAX),) * 300)
    assert kept((big, big, one)) == (big, one) and kept((big,)) == (big,)


def test_saved_threads_refuse_anything_else():
    thread = build_delivery("start/8dca50f2c35b", (), "Sayori", "11:42 PM", "phone",
                          [("time", "", "11:42 PM"), ("them", "Sayori", "hi"), ("me", "", "yo")])
    good = deliveries_json((thread,))
    assert deliveries_from_json(json.loads(json.dumps(good))) == (thread,)
    state = ItemsState(inbox=(thread,))
    assert ItemsState.from_json({"held": [], "inbox": good}) == state   # a development save
    assert "inbox" not in state.to_json()                               # version 1: top level
    assert ItemsState.from_json({"held": []}) is EMPTY_ITEMS          # before F65
    assert "inbox" not in ItemsState(("key",)).to_json()

    def broken(fn):
        data = copy.deepcopy(good)
        fn(data)
        return {"held": [], "inbox": data}

    base = {"format": 1, "identity_scheme": 1, "position": {"sid": "s", "at": ["start", []]},
            "call_stack": [], "variables": {}, "dice": "0" * 16}
    assert GameState.from_json({**base, "inbox": good}).items == state
    with pytest.raises(StateInvalid):                               # never in both places
        GameState.from_json({**base, "inbox": good, "items": {"held": [], "inbox": good}})
    with pytest.raises(StateInvalid):
        GameState.from_json({**base, "inbox": broken(lambda d: d.clear())["inbox"]})

    for fn in (lambda d: d.clear(), lambda d: d[0].pop("time"),
               lambda d: d[0].__setitem__("extra", 1),
               lambda d: d[0].__setitem__("key", "nothex.1"),
               lambda d: d.append(copy.deepcopy(d[0])),                      # a key twice
               lambda d: d[0].__setitem__("sid", "no sid"),
               lambda d: d[0].__setitem__("lines", []),
               lambda d: d[0]["lines"].append(["shout", "", "x"]),
               lambda d: d[0]["lines"].append(["me", "", ""]),
               lambda d: d[0]["lines"].append(["me", "", "x" * (inbox.TEXT_MAX + 1)]),
               lambda d: d[0].__setitem__("device", 3),
               lambda d: d.extend(copy.deepcopy(d[0]) for _ in range(inbox.DELIVERIES_MAX))):
        with pytest.raises(StateInvalid):
            ItemsState.from_json(broken(fn))


def test_a_replacing_plugin_or_another_minigame_records_nothing():
    calls = []
    interp = SimpleNamespace(codex=SimpleNamespace(deliveries=lambda: (),
                                                   add_delivery=calls.append))
    wait = SimpleNamespace(args=ARGS)
    chat = SimpleNamespace(name="phone_chat", sid="start/8dca50f2c35b")
    mine = SimpleNamespace(source="minigames/my_phone.py")
    assert record_chat(interp, chat, mine, wait, {"awake": "yes"}) is None
    assert record_chat(interp, SimpleNamespace(name="poem_game", sid=chat.sid),
                       SimpleNamespace(source="engine"), wait, {}) is None
    assert record_chat(interp, chat, None, wait, {}) is None
    bad = SimpleNamespace(args={"chat": 3, "contact": "S"})
    assert record_chat(interp, chat, SimpleNamespace(source="engine"), bad, {}) is None
    assert calls == []


# --- In the story: History, the Inbox, saves and rollback ---------------------------------------

def test_a_finished_chat_joins_history_and_the_inbox_and_rolls_back(tmp_path):
    program, sigs = _game(tmp_path / "g")
    interp = at_a(program, sigs=sigs)
    to_line(interp, LINE_P)
    before = interp.checkpoint()
    assert before.items.inbox == () and interp.codex.listed("chat") == ()
    assert said(finish(interp, {"awake": "yes", "walk": "busy"})) == ["After."]
    after = interp.checkpoint()
    (thread,) = after.items.inbox
    assert (thread.contact, thread.time, thread.device, thread.sid) == (
        "Sayori", "11:42 PM", "phone", before.position)
    assert [(ln.side, ln.text) for ln in thread.lines][:4] == [
        ("time", "11:42 PM"), ("them", "you awake?"), ("them", "i can't sleep..."),
        ("me", "Yeah, what's up?")]
    rows = [(e.kind, e.name, e.text) for e in after.history.entries]
    assert rows[-8:] == [
        ("line", "Sayori", "you awake?"), ("line", "Sayori", "i can't sleep..."),
        ("choice", "", "Yeah, what's up?"), ("line", "Sayori", "nothing really"),
        ("line", "Sayori", "can we walk to school together tomorrow?"),
        ("choice", "", "I have to go early."), ("line", "Sayori", "yay!! see you then"),
        ("line", "", "After.")]
    assert interp.codex.listed("chat") == ("chat:Sayori",)          # round 2: per contact
    # Saved exactly; a save from before F65 loads with an empty inbox.
    data = json.loads(json.dumps(after.to_json()))
    assert GameState.from_json(data) == after
    assert "inbox" not in data["items"]                     # version 1: a top-level key
    old = copy.deepcopy(data)
    old.pop("inbox")
    assert GameState.from_json(old).items == EMPTY_ITEMS
    dev = copy.deepcopy(data)                               # a development save: in items
    dev["items"]["inbox"] = dev.pop("inbox")
    assert GameState.from_json(dev) == after
    # Rolled back: the chat's start has no thread; the later state brings it back.
    assert interp.restore(before).result is RestoreResult.OK
    assert interp.codex.deliveries() == () and interp.checkpoint().items.inbox == ()
    assert interp.restore(after).result is RestoreResult.OK
    assert interp.codex.deliveries() == (thread,)
    # Read marks are kept in the persistent store, so a load keeps them.
    assert not interp.codex.delivery_read(thread.key)
    assert interp.codex.mark_delivery_read(thread.key) and interp.codex.delivery_read(thread.key)
    assert not interp.codex.mark_delivery_read("0" * 16 + ".1")          # not in the inbox
    assert interp.restore(GameState.from_json(data)).result is RestoreResult.OK
    assert interp.codex.delivery_read(thread.key)
    # New Game empties the inbox.
    interp.new_game(1)
    assert interp.codex.deliveries() == ()


def test_a_second_play_of_the_chat_joins_the_contacts_thread(tmp_path):
    program, sigs = _game(tmp_path / "g")
    interp = at_a(program, sigs=sigs)
    to_line(interp, LINE_P)
    start = interp.checkpoint()
    finish(interp, {"awake": "ignore", "walk": None})
    first = interp.codex.deliveries()
    assert [ln.text for ln in first[0].lines] == ["11:42 PM", "you awake?", "i can't sleep..."]
    # Play it again by restoring its start while the thread is kept in a later state.
    later = interp.checkpoint()
    interp.restore(start)
    interp.codex.install(later.items)
    finish(interp, {"awake": "yes", "walk": "sure"})
    threads = interp.codex.deliveries()
    assert len(threads) == 2 and threads[0] == first[0]
    assert threads[1].key.endswith(".2")
    # Round 2: one thread per contact, the chats its history, oldest first.
    assert interp.codex.listed("chat") == ("chat:Sayori",)
    (sayori,) = interp.codex.inbox()
    assert sayori.parts == threads and sayori.title == "Sayori" and sayori.sender == ""
    assert interp.codex.unread() == 2 and interp.codex.thread_unread("chat:Sayori") == 2

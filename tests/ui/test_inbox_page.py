"""F65: the Inbox page (``ui/builtin/kind_page.KindPage`` over ``app/inbox``'s port), the kit's
word for it (``Words(kit=...)``), and its entries. Round 1: chats you can reread. Round 2: one
thread per contact worded by its device look, the unread count on the game menu's and the
quick menu's Inbox buttons, the arrival notice, and ``open``'s wait."""

from types import SimpleNamespace

from engine.app.inbox import AppInboxPort, install_inbox, thread_entry
from engine.core.config_schema import ThemeConfig, WordsConfig
from engine.runtime.commands import MessageArrived, OpenInbox, WaitDone
from engine.runtime.inbox import build_delivery, group_threads
from engine.script.inbox import SendStep
from engine.ui.builtin.codex_page import KINDS, CodexView
from engine.ui.builtin.kind_page import KindPage
from engine.ui.focus import Box, FocusScope
from engine.ui.menus import DEFAULT_ORDER, MenuEntry, badged
from engine.ui.theme import Words, plain_theme
from tests.fakes.fixed_font import FixedFontAssets

SLOT = Box(416, 112, 808, 552)
SID = "start/8dca50f2c35b"


def chat(contact, time, *lines, before=()):
    return build_delivery(SID, before, contact, time, "phone", list(lines))


def sent(contact, title, device, *lines, before=(), time=""):
    return build_delivery("start/0123456789ab", before, title, time, device, list(lines),
                          sender=contact, message="invite")


class FakeCodex:
    def __init__(self, deliveries=(), contacts=None):
        self._deliveries = tuple(deliveries)
        self.contacts = contacts or {}
        self.read: set[str] = set()

    def deliveries(self):
        return self._deliveries

    def inbox(self):
        return group_threads(self._deliveries, self.contacts)

    def listed(self, kind):
        return tuple(t.key for t in self.inbox()) if kind == "chat" else ()

    def thread_unread(self, key):
        thread = next((t for t in self.inbox() if t.key == key), None)
        return 0 if thread is None else sum(d.key not in self.read for d in thread.parts)

    def unread(self):
        return sum(d.key not in self.read for d in self._deliveries)

    def mark_delivery_read(self, key):
        self.read.add(key)
        return True


def page_for(codex, words=None, select=None):
    words = words or Words()
    ui = SimpleNamespace(theme=plain_theme(), words=words, assets=FixedFontAssets())
    port = AppInboxPort(lambda: codex, lambda: words.get("inbox_me"))
    host = SimpleNamespace(shell=ui, scope=FocusScope(),
                           painter=SimpleNamespace(text_scale=lambda: 1.0))
    page = KindPage(port, "inbox", select=select)
    host.scope.set_groups(page.build(host, SLOT))
    return page, port


def texts(entry):
    return [[(s.text, s.style.bold, s.style.italic) for s in p.pieces]
            for p in entry.paragraphs]


def test_the_inbox_lists_one_thread_per_contact_newest_first_with_unread_marks():
    one = chat("Sayori", "11:42 PM", ("time", "", "11:42 PM"), ("them", "Sayori", "you awake?"),
               ("me", "", "Yeah."))
    two = sent("hana", "Hana", "pigeon", ("them", "Hana", "Meet me at the bridge."),
               before=(one,))
    three = chat("Sayori", "", ("them", "Sayori", "hi"), before=(one, two))
    codex = FakeCodex((one, two, three), {"hana": "Hana"})
    page, port = page_for(codex)
    view = page.view
    assert page.heading == "inbox" and KINDS == frozenset({"tip", "item"})
    # Sayori's two chats are one thread, the most recent; Hana's letter is the other.
    assert [r.entry.title for r in view.rows()] == ["Sayori", "Hana"]
    # The newest is shown first, and showing it marks all its deliveries read.
    assert view.selected == "chat:Sayori" and codex.read == {one.key, three.key}
    assert not port.is_read("hana") and codex.unread() == 1
    # The detail: newest delivery first, each under how it came (a chat: its time).
    entry = thread_entry(codex.inbox()[0], "You")
    assert texts(entry) == [
        [("Sayori: ", True, False), ("hi", False, False)],
        [("11:42 PM", False, True)],
        [("Sayori: ", True, False), ("you awake?", False, False)],
        [("You: ", True, False), ("Yeah.", False, False)]]
    # open pigeon: the page opens on the thread it names.
    page, _ = page_for(FakeCodex((one, two, three), {"hana": "Hana"}), select="hana")
    assert page.view.selected == "hana"


def test_a_letter_look_reads_as_a_letter_and_a_chat_look_as_chat_lines():
    letter = sent("hana", "Hana", "pigeon", ("them", "Hana", "Meet me at the bridge."),
                  ("them", "Hana", "Bring the red one."), ("me", "", "I will."),
                  time="Day 3")
    (thread,) = group_threads((letter,), {"hana": "Hana"})
    assert texts(thread_entry(thread, "You", image="hana portrait")) == [
        [("Arrived by pigeon · Day 3", False, True)],
        [("Meet me at the bridge.", False, False)], [("Bring the red one.", False, False)],
        [("You: ", True, False), ("I will.", False, False)],
        [("— Hana", False, True)]]
    assert thread_entry(thread, "You", image="hana portrait").image == "hana portrait"
    # "" is the game's default look: the kit's (a phone here), as chat lines.
    text = sent("ren", "Ren", "", ("them", "Ren", "Running late!"))
    (thread,) = group_threads((text,), {"ren": "Ren"})
    assert texts(thread_entry(thread, "You")) == [
        [("Message", False, True)], [("Ren: ", True, False), ("Running late!", False, False)]]
    assert texts(thread_entry(thread, "You", default="letters"))[0] == [
        ("Letter", False, True)]


def test_the_codex_page_is_unchanged_by_the_inbox_kinds():
    # A view with the default filter never lists threads, even from a port that has them.
    codex = FakeCodex((chat("Sayori", "", ("them", "Sayori", "hi")),))
    port = AppInboxPort(lambda: codex, lambda: "You")
    ui = SimpleNamespace(theme=plain_theme(), words=Words(), assets=FixedFontAssets())
    view = CodexView(port, ui=ui)
    assert view.build(SLOT, 1.0) == [] and view.tabs == ()


def test_the_kit_names_the_inbox_unless_the_author_does():
    assert Words().get("inbox") == "Inbox" and Words().get("inbox_me") == "You"
    assert Words(kit={"inbox": "Letters"}).get("inbox") == "Letters"
    own = WordsConfig(inbox="Post")                                     # [words] always wins
    assert Words(own, kit={"inbox": "Letters"}).get("inbox") == "Post"


def _installed(codex, *, sends=False):
    added, notices, opened, posted, pressed = [], [], [], [], []
    shell = SimpleNamespace(
        words=Words(), replay=None,
        menus=SimpleNamespace(add=lambda menu, entry: added.append((menu, entry))),
        notify=lambda text, icon=None, skin=None: notices.append((text, icon)),
        open_game_menu=lambda by, page=None, on_closed=None: opened.append((page, on_closed))
        or object())
    routes = {}
    lines = [SendStep(file=None, line=1, end_line=1, column=1, message="invite",
                      contact="hana")] if sends else []
    program = SimpleNamespace(contacts=(), iter_statements=lambda: iter(lines))
    stage = SimpleNamespace(wait_id=None, start_wait=lambda cmd: setattr(stage, "wait_id",
                                                                         cmd.wait_id),
                            press=lambda: pressed.append(stage.wait_id))
    app = SimpleNamespace(
        shell=shell, config=SimpleNamespace(theme=ThemeConfig(), device={}),
        router=SimpleNamespace(register=lambda kind, fn: routes.__setitem__(kind, fn)),
        stage_screen=stage, skip_auto=SimpleNamespace(skipping=False), assets=None,
        story=SimpleNamespace(interp=SimpleNamespace(codex=codex, program=program),
                              post=posted.append))
    install_inbox(app, app.story.interp)
    return SimpleNamespace(added=added, notices=notices,
                           opened=opened, routes=routes, stage=stage, pressed=pressed,
                           posted=posted, app=app)


def test_the_menu_entries_show_with_the_unread_count():
    assert DEFAULT_ORDER["game"].index("inbox") == DEFAULT_ORDER["game"].index("codex") + 1
    assert DEFAULT_ORDER["quick"].index("inbox") == DEFAULT_ORDER["quick"].index("history") + 1
    codex = FakeCodex()
    got = _installed(codex)
    ((menu, entry),) = got.added                     # no send line: no quick-menu button
    assert (menu, entry.id) == ("game", "inbox") and not entry.visible()
    codex._deliveries = (chat("Sayori", "", ("them", "Sayori", "hi")),)
    assert entry.visible() and badged("Inbox", entry) == "Inbox (1)"
    codex.read = {codex._deliveries[0].key}
    assert badged("Inbox", entry) == "Inbox"
    assert badged("Inbox", MenuEntry("inbox")) == "Inbox"
    # A game with a send line: the game menu's entry shows from the start, and the quick
    # menu gets the button, which opens the game menu on the Inbox page.
    got = _installed(FakeCodex(), sends=True)
    entries = {menu: entry for menu, entry in got.added}
    assert set(entries) == {"game", "quick"} and entries["game"].visible()
    entries["quick"].action(SimpleNamespace(shell=got.app.shell, by="keys"))
    assert got.opened[-1][0] == "inbox"


def test_the_arrival_notice_is_worded_by_the_look():
    got = _installed(FakeCodex())
    notice = got.routes[MessageArrived]
    notice(MessageArrived("hana", "Hana", "pigeon"))
    notice(MessageArrived("ren", "Ren", ""))
    notice(MessageArrived("ren", "Ren", "radio"))
    assert [text for text, _ in got.notices] == [
        "A pigeon lands on the sill with a note from Hana.", "New message from Ren.",
        "The radio crackles. It's Ren."]
    got.app.shell.replay = object()                   # a scene replay: no notice
    notice(MessageArrived("ren", "Ren", ""))
    assert len(got.notices) == 3


def test_open_holds_the_story_until_the_menu_closes():
    hana = sent("hana", "Hana", "pigeon", ("them", "Hana", "Hi."))
    ren = sent("ren", "Ren", "", ("them", "Ren", "Yo."), before=(hana,))
    got = _installed(FakeCodex((hana, ren), {"hana": "Hana", "ren": "Ren"}))
    open_inbox = got.routes[OpenInbox]
    open_inbox(OpenInbox(7, SID, None, False, False, look="pigeon"))
    assert got.stage.wait_id == 7
    ((page, closed),) = got.opened
    assert page == "inbox" and got.pressed == []
    closed()                                          # the player closes the menu
    assert got.pressed == [7]
    # Skipping passes it; no stage (an App wired by hand) ends it at once.
    got.app.skip_auto.skipping = True
    open_inbox(OpenInbox(8, SID, None, False, False))
    assert len(got.opened) == 1
    got.app.stage_screen = None
    open_inbox(OpenInbox(9, SID, None, False, False))
    assert got.posted == [WaitDone(9)]

"""F65 round 1: the Inbox page (``ui/builtin/kind_page.KindPage`` over ``app/inbox``'s port),
the kit's word for it (``Words(kit=...)``), and the game menu's ``inbox`` entry."""

from types import SimpleNamespace

from engine.app.inbox import AppInboxPort, install_inbox, thread_entry
from engine.core.config_schema import WordsConfig
from engine.runtime.inbox import build_thread
from engine.ui.builtin.codex_page import KINDS, CodexView
from engine.ui.builtin.kind_page import KindPage
from engine.ui.focus import Box, FocusScope
from engine.ui.menus import DEFAULT_ORDER
from engine.ui.theme import Words, plain_theme
from tests.fakes.fixed_font import FixedFontAssets

SLOT = Box(416, 112, 808, 552)
SID = "start/8dca50f2c35b"


def thread(contact, time, *lines, before=()):
    return build_thread(SID, before, contact, time, "phone", list(lines))


class FakeCodex:
    def __init__(self, threads=()):
        self._threads = tuple(threads)
        self.read: set[str] = set()

    def threads(self):
        return self._threads

    def listed(self, kind):
        return tuple(t.key for t in reversed(self._threads)) if kind == "chat" else ()

    def thread_read(self, key):
        return key in self.read

    def mark_thread_read(self, key):
        self.read.add(key)
        return True


def page_for(codex, words=None):
    words = words or Words()
    ui = SimpleNamespace(theme=plain_theme(), words=words, assets=FixedFontAssets())
    port = AppInboxPort(lambda: codex, lambda: words.get("inbox_me"))
    host = SimpleNamespace(shell=ui, scope=FocusScope(),
                           painter=SimpleNamespace(text_scale=lambda: 1.0))
    page = KindPage(port, "inbox")
    host.scope.set_groups(page.build(host, SLOT))
    return page, port


def test_the_inbox_lists_threads_newest_first_with_unread_marks():
    one = thread("Sayori", "11:42 PM", ("time", "", "11:42 PM"), ("them", "Sayori", "you awake?"),
                 ("me", "", "Yeah."))
    two = thread("Hana", "", ("them", "Hana", "Meet me at the bridge."), before=(one,))
    codex = FakeCodex((one, two))
    page, port = page_for(codex)
    view = page.view
    assert page.heading == "inbox" and KINDS == frozenset({"tip", "item"})
    assert [r.entry.title for r in view.rows()] == ["Hana", "Sayori · 11:42 PM"]
    # The newest is shown first, and showing it marks it read; the other stays unread.
    assert view.selected == two.key and codex.read == {two.key}
    assert not port.is_read(one.key)
    # The detail: one paragraph per line, the name in bold, the player as "You"; the
    # opening time is in the title, later times are italic dividers.
    entry = thread_entry(one, "You")
    texts = [[(s.text, s.style.bold, s.style.italic) for s in p.pieces]
             for p in entry.paragraphs]
    assert texts == [[("Sayori: ", True, False), ("you awake?", False, False)],
                     [("You: ", True, False), ("Yeah.", False, False)]]
    later = thread("Sayori", "", ("them", "Sayori", "hi"), ("time", "", "1 AM"))
    assert [p.pieces[0].text for p in thread_entry(later, "You").paragraphs] == [
        "Sayori: ", "1 AM"]
    # A new thread shows on the next update (the view's signature includes the inbox).
    three = thread("Daichi", "", ("them", "Daichi", "Late again?"), before=(one, two))
    codex._threads = (one, two, three)
    view.update(0.016)
    assert [r.entry.title for r in view.rows()][0] == "Daichi"


def test_the_codex_page_is_unchanged_by_the_inbox_kind():
    # A view with the default filter never lists chats, even from a port that has them.
    codex = FakeCodex((thread("Sayori", "", ("them", "Sayori", "hi")),))
    port = AppInboxPort(lambda: codex, lambda: "You")
    ui = SimpleNamespace(theme=plain_theme(), words=Words(), assets=FixedFontAssets())
    view = CodexView(port, ui=ui)
    assert view.build(SLOT, 1.0) == [] and view.tabs == ()


def test_the_kit_names_the_inbox_unless_the_author_does():
    assert Words().get("inbox") == "Inbox" and Words().get("inbox_me") == "You"
    assert Words(kit={"inbox": "Letters"}).get("inbox") == "Letters"
    own = WordsConfig(inbox="Post")                                     # [words] always wins
    assert Words(own, kit={"inbox": "Letters"}).get("inbox") == "Post"


def test_the_game_menu_entry_shows_once_there_is_a_thread():
    assert DEFAULT_ORDER["game"].index("inbox") == DEFAULT_ORDER["game"].index("codex") + 1
    added = []
    codex = FakeCodex()
    shell = SimpleNamespace(words=Words(), menus=SimpleNamespace(
        add=lambda menu, entry: added.append((menu, entry))))
    app = SimpleNamespace(shell=shell, story=SimpleNamespace(interp=SimpleNamespace(
        codex=codex)))
    install_inbox(app, app.story.interp)
    ((menu, entry),) = added
    assert (menu, entry.id) == ("game", "inbox") and not entry.visible()
    codex._threads = (thread("Sayori", "", ("them", "Sayori", "hi")),)
    assert entry.visible()

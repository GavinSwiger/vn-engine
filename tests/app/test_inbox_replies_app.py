"""F65 round 3 in the App (App A, ``tests/fakes/text_app.py``): ``open pigeon`` opens the Inbox
on a letter that asks for a reply; its replies are buttons under the message, the thread has
the reply marker, picking one answers it (the player's line shows, the buttons go), and the
story reads the answer with ``inbox.reply`` once the menu closes. Also the reply view on its
own (``ui/builtin/inbox_reply``): no buttons without an ask, disabled while a reply can't
count."""

import os
from types import SimpleNamespace

import pygame
import pytest

from engine.app.inbox import AppInboxPort
from engine.runtime.inbox import build_delivery, group_threads
from engine.ui.builtin.codex_page import CodexFilter, CodexView
from engine.ui.builtin.inbox_reply import ReplyRow, reply_view
from engine.ui.focus import Box, FocusScope
from engine.ui.theme import Words, plain_theme
from tests.app.test_skip_auto_app import story
from tests.fakes.fixed_font import FixedFontAssets

SHOTS = os.environ.get("VN_INBOX_SHOTS")          # a folder: save the screenshot there
SLOT = Box(416, 112, 808, 552)

HEAD = ('lock contact hana "Hana" on pigeon\n'
        'define invite = ["Meet me at the bridge when the lanterns are lit.", '
        '"Bring the red one. You\'ll see why.", '
        '{"ask": "come", "yes": "I\'ll be there.", "no": "Not this year."}]\n')
BODY = ('    "Morning."\n'
        '    send invite from hana\n'
        '    open pigeon\n'
        '    if inbox.reply("invite") == "yes":\n'
        '        "She will be glad."\n'
        '    else:\n'
        '        "I left the letter on the table."\n')


class FakeCodex:
    def __init__(self, deliveries):
        self._deliveries = tuple(deliveries)

    def deliveries(self):
        return self._deliveries

    def inbox(self):
        return group_threads(self._deliveries, {"hana": "Hana"})

    def listed(self, kind):
        return tuple(t.key for t in self.inbox()) if kind == "chat" else ()

    def thread_unread(self, key):
        return 0

    def mark_delivery_read(self, key):
        return True


def _view(deliveries, *, can=True):
    words = Words()
    ui = SimpleNamespace(theme=plain_theme(), words=words, assets=FixedFontAssets())
    codex = FakeCodex(deliveries)
    port = AppInboxPort(lambda: codex, lambda: "You")
    posted = []
    port.post = posted.append
    port.can_reply = lambda: can                                    # type: ignore[method-assign]
    scope = FocusScope()
    view = reply_view(CodexView)(port, ui=ui, filter=CodexFilter(frozenset({"chat"})),
                                 scope=lambda: scope)
    scope.set_groups(view.build(SLOT, 1.0))
    return view, posted, codex


def _letter(ask=(("yes", "I'll be there."), ("no", "Not this year.")), reply=""):
    from dataclasses import replace
    found = build_delivery("start/0123456789ab", (), "Hana", "", "pigeon",
                           [("them", "Hana", "Meet me at the bridge.")], sender="hana",
                           message="invite", ask=ask)
    return replace(found, reply=reply)


def test_the_replies_are_buttons_under_the_message():
    view, posted, _codex = _view([_letter()])
    assert isinstance(view, ReplyRow) and view.selected == "hana"
    assert view.reply_options() == (("yes", "I'll be there."), ("no", "Not this year."))
    yes, no = view.reply_buttons[:2]
    assert (yes.label(), no.label()) == ("I'll be there.", "Not this year.")
    assert yes.box.y == no.box.y and yes.box.right < no.box.x
    assert view.layout.pick is not None and yes.box.x == view.layout.pick.x
    assert view._waiting("hana")
    no.activate()
    assert [(e.key, e.reply) for e in posted] == [(_letter().key, "no")]


def test_no_buttons_without_an_ask_or_once_answered_and_disabled_when_it_cant_count():
    for delivery in (_letter(ask=()), _letter(reply="yes")):
        view, _posted, _codex = _view([delivery])
        assert view.reply_options() == () and view.layout.pick is None
        assert not view._waiting("hana")
    view, posted, _codex = _view([_letter()], can=False)
    assert not view.reply_buttons[0].enabled()
    view.reply_buttons[0].activate()
    assert posted == []


def test_answering_lays_the_thread_out_again():
    view, _posted, codex = _view([_letter()])
    codex._deliveries = (_letter(reply="yes"),)
    view.update(0.016)
    assert view.groups_changed and view.reply_options() == ()
    assert view.layout.pick is None


@pytest.mark.display
def test_a_letter_asks_and_the_player_answers_in_the_inbox(tmp_path):
    pygame.init()
    pygame.event.clear()
    try:
        _play(tmp_path)
    finally:
        pygame.quit()


def _play(tmp_path):
    seen: dict[str, object] = {}
    s = story(tmp_path / "g", BODY, "[textbox]\ncps = 0\n", size=(1280, 720))
    main = s.paths.root / "script" / "main.vns"
    main.write_text(HEAD + main.read_text(encoding="utf-8"), encoding="utf-8")

    def view():
        for screen in reversed(list(s.app.screens)):
            page = getattr(screen, "page", None) or getattr(screen, "current_page", None)
            found = getattr(page, "view", None)
            if isinstance(found, ReplyRow):
                return found
        return None

    def script(s):
        yield from s.until_line("Morning.")
        s.key(pygame.K_RETURN)
        yield from s.until(lambda: view() is not None, limit=300)
        for _ in range(20):
            yield
        v = view()
        seen["options"] = v.reply_options()
        seen["enabled"] = v.reply_buttons[0].enabled()
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            pygame.image.save(s.fb, os.path.join(SHOTS, "inbox-reply-options.png"))
        v.reply_buttons[0].activate()
        for _ in range(5):
            yield
        seen["after"] = v.reply_options()
        seen["history"] = s.app.story.interp.history.entries[-1].text
        if SHOTS:
            pygame.image.save(s.fb, os.path.join(SHOTS, "inbox-reply-answered.png"))
        for _ in range(3):                    # Back leaves the page, then closes the menu
            if not any(type(x).__name__ == "GameMenuScreen" for x in s.app.screens):
                break
            s.key(pygame.K_ESCAPE)
            for _ in range(10):
                yield
        yield from s.until(lambda: s.line_text() in ("She will be glad.",
                                                      "I left the letter on the table."))
        seen["line"] = s.line_text()

    s.play(script)
    assert seen["options"] == (("yes", "I'll be there."), ("no", "Not this year."))
    assert seen["enabled"] is True
    assert seen["after"] == () and seen["history"] == "I'll be there."
    assert seen["line"] == "She will be glad."

"""``install_inbox``: the Inbox page in the game menu (F65 round 1, "Chats you can reread").

Why this module exists: a finished phone chat is kept as a thread of the codex's ``chat``
kind (``runtime/inbox.py``, story state in ``interp.codex``). This module shows those
threads on their own codex-kind page (``ui/builtin/kind_page.KindPage``), so the player can
reopen any finished chat from the game menu and read it again.

- ``AppInboxPort``: the page's ``CodexPort``. ``entries()`` turns each thread into a
  ``CodexEntry`` of kind ``chat`` (cached per threads tuple): the title is the contact (with
  the chat's opening time, "Sayori · 11:42 PM", so two chats with one contact differ), one
  paragraph per line: "Sayori: you awake?" with the name in bold, the player's own lines
  under ``[words] inbox_me`` ("You"), and time dividers in italics. ``listed("chat")`` is
  newest first; ``is_read``/``mark_read`` are the persistent Inbox read marks (unread rows
  show the codex's dot until opened).
- The game menu's ``inbox`` entry (after ``codex``), shown once the inbox has a thread. Its
  word, also the heading, is ``[words] inbox``, or the kit's ``messages`` title ("Letters")
  where the author left that word as is (``kits.kit_words``, applied in ``app/menus.py``).
"""

from typing import TYPE_CHECKING, Final

from engine.core.codexkinds import CHAT
from engine.runtime.codex import CodexCategory, CodexEntry
from engine.runtime.commands import Span, Style, TaggedText
from engine.ui.builtin.kind_page import KindPage
from engine.ui.menus import MenuEntry

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.codex import Codex
    from engine.runtime.inbox import InboxThread
    from engine.runtime.interpreter import Interpreter

CATEGORY: Final = CodexCategory(CHAT.name, None, CHAT.tab_word)     # type: ignore[arg-type]
BOLD: Final = Style(bold=True)
ITALIC: Final = Style(italic=True)
PLAIN: Final = Style()


def thread_entry(thread: "InboxThread", me: str) -> CodexEntry:
    """``thread`` as the page's entry (module docstring); ``me`` names the player's lines."""
    paragraphs = []
    for line in thread.lines:
        if line.side == "time":
            paragraphs.append(TaggedText((Span(line.text, ITALIC),)))
        else:
            name = me if line.side == "me" else line.name
            paragraphs.append(TaggedText((Span(f"{name}: ", BOLD), Span(line.text, PLAIN)))
                              if name else TaggedText((Span(line.text, PLAIN),)))
    title = f"{thread.contact} · {thread.time}" if thread.time else thread.contact
    return CodexEntry(thread.key, CHAT.name, title, CATEGORY, None,   # type: ignore[arg-type]
                      tuple(paragraphs), thread.sid, "", 0)


class AppInboxPort:
    """The Inbox page's ``CodexPort`` (module docstring). ``codex()`` gives the live
    ``interp.codex``; ``me()`` the player's name for their own lines."""

    show_locked = False

    def __init__(self, codex, me) -> None:
        self._codex = codex
        self._me = me
        self._made: tuple = ((), "", ())               # (threads, me, entries)

    @property
    def codex(self) -> "Codex":
        return self._codex()

    def entries(self) -> tuple[CodexEntry, ...]:
        threads, me = self.codex.threads(), self._me()
        made = self._made
        if made[0] is not threads or made[1] != me:
            made = self._made = (threads, me, tuple(thread_entry(t, me) for t in threads))
        return made[2]

    def categories(self) -> tuple[CodexCategory, ...]:
        return (CATEGORY,)

    def tips(self) -> tuple[str, ...]:
        return ()

    def items(self) -> tuple[str, ...]:
        return ()

    def listed(self, kind: str) -> tuple[str, ...]:
        return self.codex.listed(kind)

    def is_read(self, name: str) -> bool:
        return self.codex.thread_read(name)

    def mark_read(self, name: str) -> None:
        self.codex.mark_thread_read(name)

    def picture(self, image: str) -> None:
        return None


def install_inbox(app: "App", interp: "Interpreter") -> AppInboxPort:
    """The port and, with a shell, the game menu's ``inbox`` entry (module docstring)."""

    def codex() -> "Codex":
        story = getattr(app, "story", None)
        found = getattr(story, "interp", None)
        return (found if found is not None else interp).codex

    shell = getattr(app, "shell", None)
    port = AppInboxPort(codex, lambda: shell.words.get("inbox_me") if shell is not None
                        else "You")
    if shell is not None:
        shell.menus.add("game", MenuEntry(
            CHAT.page, page=lambda host: KindPage(port, CHAT.page),
            visible=lambda: bool(codex().threads())))
    return port


__all__ = ["AppInboxPort", "CATEGORY", "install_inbox", "thread_entry"]

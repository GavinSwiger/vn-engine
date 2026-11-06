"""``install_inbox``: the Inbox page, its buttons, the arrival notice and ``open`` (F65 round 1
"Chats you can reread"; round 2 "Contacts and send" and "Open on cue").

Why this module exists: finished phone chats and messages that contacts ``send`` are kept as
deliveries in the story state (``runtime/inbox.py``, ``interp.codex``). This module shows them
to the player: one thread per contact on the Inbox page (``ui/builtin/kind_page.KindPage``),
a notice when something arrives, the Inbox button in the quick menu, and the page the story
opens with ``open inbox`` / ``open pigeon``.

- ``AppInboxPort``: the page's ``CodexPort``. ``entries()`` turns each thread
  (``Codex.inbox()``, newest first) into a ``CodexEntry`` of kind ``chat`` (cached per
  threads tuple): the title is the contact's shown name, the picture the contact's, and the
  body holds the contact's deliveries, **newest first** so a new letter is what the page
  opens on. Each delivery starts with an italic line saying how it came ("Arrived by pigeon
  · Day 3", "Message", a chat's opening time), worded by its device look
  (``kits.device_words``; "" is the game's default, ``kits.device_look``: the kit's, else a
  phone). A letter look (letters, pigeon, mind) reads as a letter: the contact's lines as
  plain paragraphs, signed "— Hana"; a chat look (phone, radio, terminal) as "Hana: …".
  The player's own lines are under ``[words] inbox_me`` ("You"). Round 3: the port also
  says how each paragraph is drawn (``paragraph_looks``: its look and role, "via", "time",
  "them", "me", "sign"), and the page is an ``InboxView`` that draws each look its own way
  (a phone's bubbles, a letter's paper, …); a thought (``mind``) reads in italics. ``is_read`` is "every
  delivery read"; ``mark_read`` marks them all (the persistent kind ``inbox_read``), so the
  row's dot and the buttons' counts go when the thread is opened.
- The game menu's ``inbox`` entry (after ``codex``), shown once there is a delivery or when
  the game has a ``send`` line, and, in a game with a ``send`` line, the quick menu's
  ``inbox`` button (after History); both show the unread count, "Letters (2)"
  (``MenuEntry.badge``). Their word, also the heading, is ``[words] inbox``, or the kit's
  ``messages`` title where the author left that word as is (``kits.kit_words``).
- ``MessageArrived`` → the arrival notice, worded by the device look ("A pigeon lands on the
  sill with a note from Hana.", "New message from Ren."), with the contact's picture as its
  icon. Round 3: worded by ``[device.<look>]`` where set (``kits.device_words``), drawn in
  the look's skin (``ui/devicelook.notice_skin``), and its ``arrive_sound`` plays once as a
  UI sound (``audio.play_ui``: the sound volume), never while skipping. Like the codex's notices: none during a scene replay, none on a quiet re-run (the
  runtime drops its holds).
- ``OpenInbox`` (``open``'s story wait) → the stage holds the wait, then the game menu opens
  on the Inbox page at the newest thread (``open pigeon``: the newest that came by pigeon);
  when the menu closes, the wait ends and the story goes on. While skipping, it passes like
  a fake crash does (PR-F30-16); with no shell or stage, or nothing to show (no ``send``
  line and nothing arrived yet), it ends at once.
"""

from typing import TYPE_CHECKING, Final

from engine.core.codexkinds import CHAT
from engine.core.kits import arrive_text, device_look, device_words
from engine.runtime.codex import CodexCategory, CodexEntry
from engine.runtime.commands import MessageArrived, OpenInbox, Span, Style, TaggedText, WaitDone
from engine.runtime.images import ImageFile, SolidColor
from engine.runtime.send import uses_send
from engine.ui.builtin.inbox_view import InboxView, ParaLook
from engine.ui.builtin.kind_page import KindPage
from engine.ui.devicelook import notice_skin
from engine.ui.menus import MenuEntry
from engine.ui.nav import InputKind

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.codex import Codex
    from engine.runtime.images import ImageIndex
    from engine.runtime.inbox import ContactThread, Delivery
    from engine.runtime.interpreter import Interpreter

CATEGORY: Final = CodexCategory(CHAT.name, None, CHAT.tab_word)     # type: ignore[arg-type]
BOLD: Final = Style(bold=True)
ITALIC: Final = Style(italic=True)
PLAIN: Final = Style()
PAGE: Final = CHAT.page                                  # "inbox": the page and both buttons


def look_of(delivery: "Delivery", default: str) -> str:
    """The device look ``delivery`` came by ("" is the game's ``default``)."""
    return delivery.device or default


def _header(delivery: "Delivery", look: str, config: object = None) -> str:
    """The italic line above a delivery: how it came and when."""
    if not delivery.sender:                              # a finished phone chat (round 1)
        return delivery.time
    via = device_words(look, config).via
    return f"{via} · {delivery.time}" if delivery.time else via


def _part(delivery: "Delivery", me: str, look: str, contact: str, config: object = None
          ) -> list[tuple[TaggedText, str]]:
    """One delivery's paragraphs, each with its role for the look's drawing ("via",
    "time", "them", "me", "sign"; ``ui/builtin/inbox_view.ParaLook``). Round 3: a thought
    (``mind``) reads in italics."""
    out: list[tuple[TaggedText, str]] = []
    header = _header(delivery, look, config)
    if header:
        out.append((TaggedText((Span(header, ITALIC),)), "via"))
    lines = delivery.lines
    if lines and lines[0].side == "time" and lines[0].text == delivery.time:
        lines = lines[1:]                                # the header already says when
    letter = device_words(look, config).letter and bool(delivery.sender)
    plain = ITALIC if look == "mind" else PLAIN
    bold = Style(bold=True, italic=plain.italic)
    signed = False
    for line in lines:
        if line.side == "time":
            out.append((TaggedText((Span(line.text, ITALIC),)), "time"))
            continue
        name = me if line.side == "me" else line.name
        role = "me" if line.side == "me" else "them"
        if letter and line.side == "them" and line.name == contact:
            out.append((TaggedText((Span(line.text, plain),)), role))
            signed = True
            continue
        out.append((TaggedText((Span(f"{name}: ", bold), Span(line.text, plain)))
                    if name else TaggedText((Span(line.text, plain),)), role))
    if signed:
        out.append((TaggedText((Span(f"— {contact}", ITALIC),)), "sign"))
    return out


def thread_parts(thread: "ContactThread", me: str, *, default: str = "phone",
                 image: str | None = None, config: object = None
                 ) -> "tuple[CodexEntry, tuple[ParaLook, ...]]":
    """``thread`` as the page's entry (module docstring) and how each of its paragraphs
    is dressed (round 3); ``me`` names the player's lines, ``default`` is the game's device
    look, ``image`` the contact's picture name, ``config`` gives ``[device.*]``'s words."""
    paragraphs: list[TaggedText] = []
    looks: list[ParaLook] = []
    for delivery in reversed(thread.parts):
        look = look_of(delivery, default)
        part = _part(delivery, me, look, delivery.contact, config)
        for i, (text, role) in enumerate(part):
            paragraphs.append(text)
            looks.append(ParaLook(look, role, i == 0, i == len(part) - 1))
    newest = thread.newest
    entry = CodexEntry(thread.key, CHAT.name, thread.title, CATEGORY, image,  # type: ignore[arg-type]
                       tuple(paragraphs), newest.sid, "", 0)
    return entry, tuple(looks)


def thread_entry(thread: "ContactThread", me: str, *, default: str = "phone",
                 image: str | None = None, config: object = None) -> CodexEntry:
    """``thread`` as the page's entry (``thread_parts`` without the looks)."""
    return thread_parts(thread, me, default=default, image=image, config=config)[0]


class AppInboxPort:
    """The Inbox page's ``CodexPort`` (module docstring). ``codex()`` gives the live
    ``interp.codex``; ``me()`` the player's name for their own lines; ``default`` the game's
    device look; ``images()`` the contacts' picture names and the launch's ``ImageIndex``."""

    show_locked = False

    def __init__(self, codex, me, *, default: str = "phone", contacts=lambda: {},
                 images: "ImageIndex | None" = None, config: object = None) -> None:
        self._codex = codex
        self._me = me
        self.default = default
        self._contacts = contacts
        self.images = images
        self.config = config
        self._made: tuple = ((), "", (), {})           # (threads, me, entries, looks)

    @property
    def codex(self) -> "Codex":
        return self._codex()

    def entries(self) -> tuple[CodexEntry, ...]:
        threads, me = self.codex.inbox(), self._me()
        made = self._made
        if made[0] is not threads or made[1] != me:
            pictures = self._contacts()
            parts = [thread_parts(t, me, default=self.default, image=pictures.get(t.sender),
                                  config=self.config) for t in threads]
            made = self._made = (threads, me, tuple(entry for entry, _ in parts),
                                 {entry.name: looks for entry, looks in parts})
        return made[2]

    def paragraph_looks(self, name: str) -> "tuple[ParaLook, ...] | None":
        """Round 3: how each paragraph of entry ``name`` is drawn (``InboxView``)."""
        self.entries()
        return self._made[3].get(name)

    def categories(self) -> tuple[CodexCategory, ...]:
        return (CATEGORY,)

    def tips(self) -> tuple[str, ...]:
        return ()

    def items(self) -> tuple[str, ...]:
        return ()

    def listed(self, kind: str) -> tuple[str, ...]:
        return self.codex.listed(kind)

    def is_read(self, name: str) -> bool:
        return self.codex.thread_unread(name) == 0

    def mark_read(self, name: str) -> None:
        codex = self.codex
        for thread in codex.inbox():
            if thread.key == name:
                for delivery in thread.parts:
                    codex.mark_delivery_read(delivery.key)

    def picture(self, image: str) -> "str | tuple[int, int, int] | None":
        found = self.images.get(image) if self.images is not None else None
        if isinstance(found, ImageFile):
            return found.ref
        if isinstance(found, SolidColor):
            return found.rgb
        return None

    def newest(self, look: str | None) -> str | None:
        """The key of the newest thread (``look``: whose newest delivery came by it, else
        the newest of all), or None for an empty inbox."""
        threads = self.codex.inbox()
        if look is not None:
            for thread in threads:
                if any(look_of(d, self.default) == look for d in thread.parts):
                    return thread.key
        return threads[0].key if threads else None


def install_inbox(app: "App", interp: "Interpreter",
                  images: "ImageIndex | None" = None) -> AppInboxPort:
    """The port and, with a shell, the Inbox's game-menu and quick-menu entries, the
    ``MessageArrived`` notice and the ``OpenInbox`` handler (module docstring)."""

    def live() -> "Interpreter":
        story = getattr(app, "story", None)
        found = getattr(story, "interp", None)
        return found if found is not None else interp

    def codex() -> "Codex":
        return live().codex

    def pictures() -> dict[str, str]:
        return {c.name: c.image for c in getattr(live().program, "contacts", ())
                if c.image is not None}

    shell = getattr(app, "shell", None)
    port = AppInboxPort(codex, lambda: shell.words.get("inbox_me") if shell is not None
                        else "You", default=device_look(app.config), contacts=pictures,
                        images=images, config=app.config)
    sends = uses_send(interp.program)
    pending: list[str | None] = [None]                 # the thread ``open`` shows first

    def page(host) -> KindPage:
        select, pending[0] = pending[0], None
        return KindPage(port, PAGE, select=select, view=InboxView)

    def on_arrived(cmd: MessageArrived) -> None:
        if shell is None or getattr(shell, "replay", None) is not None:
            return
        look = cmd.device or port.default
        words = device_words(look, app.config)
        icon = None
        source = port.picture(cmd.image) if cmd.image is not None else None
        if isinstance(source, str):
            icon = app.assets.image(source)
        theme = getattr(shell, "theme", None)
        cfg = theme.cfg if theme is not None else app.config.theme
        shell.notify(arrive_text(words, cmd.title), icon=icon, skin=notice_skin(cfg, look))
        skip = getattr(app, "skip_auto", None)
        audio = getattr(app, "audio", None)
        if words.sound and audio is not None and not (skip is not None and skip.skipping):
            audio.play_ui(words.sound)                   # once, at the sound volume

    def open_inbox(cmd: OpenInbox) -> None:
        stage = getattr(app, "stage_screen", None)
        story = getattr(app, "story", None)
        if stage is None or shell is None:
            if story is not None:
                story.post(WaitDone(cmd.wait_id))
            return
        stage.start_wait(cmd)
        skip = getattr(app, "skip_auto", None)
        if skip is not None and skip.skipping:
            return                              # skip's next update passes it (PR-F30-16)

        def closed() -> None:
            if stage.wait_id == cmd.wait_id:
                stage.press()

        if not sends and not codex().deliveries():
            stage.press()                       # nothing to show: the story goes on
            return
        pending[0] = port.newest(cmd.look)
        menu = shell.open_game_menu(InputKind.KEYS, page=PAGE, on_closed=closed)
        if menu is None:
            pending[0] = None
            stage.press()

    app.router.register(MessageArrived, on_arrived)
    app.router.register(OpenInbox, open_inbox)
    if shell is not None:
        shell.menus.add("game", MenuEntry(
            PAGE, page=page, visible=lambda: sends or bool(codex().deliveries()),
            badge=lambda: codex().unread()))
        if sends:
            shell.menus.add("quick", MenuEntry(
                PAGE, action=lambda ctx: ctx.shell.open_game_menu(ctx.by, page=PAGE),
                badge=lambda: codex().unread()))
    return port


__all__ = ["AppInboxPort", "CATEGORY", "install_inbox", "look_of", "thread_entry",
           "thread_parts"]

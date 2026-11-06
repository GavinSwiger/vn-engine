"""Database ▸ Contacts, the pure half (F65 round 3, proposal I-09 "Studio contacts and
devices"; plan: specs/skins-contract.md, "Phases 2-4").

Why this module exists: someone who has never coded should set up a pen pal in a minute:
a contact (``lock contact hana "Hana" on pigeon image hana portrait``), the messages she
sends (a ``define`` in the phone chat's line format, written with the phone-chat step
editor) and where the story sends them (``send <message> from hana``). This module reads
those from the script texts; the widgets are ``dbcontacts``.

- ``send_lines(texts)``: every ``send … from …`` line in a scene, in story order
  (``SendLine``: file, line, message, contact, look, scene).
- ``contact_entries(decls, texts)``: the Contacts list (``dbmodel.Entry``), "used" by the
  send lines from each contact (the lines a removal would break).
- ``messages_of(contact, texts, sends)``: the messages under a contact: the ones sent from
  it, in the order they are first sent, then the ones not sent yet whose name starts with
  ``<contact>_`` (what **+ New message** makes).
- ``message_set(texts, name)``: a message as the phone-chat step editor's data set (a
  message of one text reads as one line from the contact).
- ``default_look(found)`` / ``look_choices(found)``: the device look a contact without
  ``on`` gets (the kit's, else a phone) and the Device look drop-down.
- ``preview(...)``: what the live preview draws (``ContactPreview``).

Pure Python: ``core``, ``engine.script`` and this package's pure modules; no Tk, no pygame
(ADR-0008).
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final

from engine.core.kits import DEVICE_LOOKS, device_words
from engine.script.inbox import message_problem, plain_value
from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from engine.tools.editor import kitmodel as km
from engine.tools.editor import metermodel as mm
from engine.tools.editor import minigamedata as mg

# --- Texts ------------------------------------------------------------------------------------

LOOK_NAMES: Final[Mapping[str, str]] = {
    "phone": "Phone", "letters": "Letters", "pigeon": "Pigeon post", "radio": "Radio",
    "terminal": "Terminal", "mind": "Mind (a voice in the head)"}
DEFAULT_KIT: Final = "Game default ({look}, from the {kit} kit)"
DEFAULT_PLAIN: Final = "Game default ({look})"
NO_MESSAGES: Final = "No messages yet"
NEWEST: Final = "Newest: {message}, sent in {scene}"
NOT_SENT_CAPTION: Final = "Not sent yet: {message}"
ARRIVES: Final = "Arrives as: “{notice}”"
SIGNED: Final = "— {name}"
FIRST_LINE: Final[Mapping[bool, str]] = {
    True: "I hope this finds you well. Write back soon.",
    False: "Hey! Are you there?"}

_SEND: Final = re.compile(
    r"[ \t]+send[ \t]+([^\W\d]\w*)[ \t]+from[ \t]+([^\W\d]\w*)"
    r"(?:[ \t]+on[ \t]+([^\W\d]\w*))?(?=[ \t#]|$)")
_LABEL: Final = re.compile(r"label[ \t]+([^\W\d]\w*)")
_DEFINE: Final = re.compile(r"(?:define|default)[ \t]+([^\W\d]\w*)[ \t]*=(.*)", re.DOTALL)
PREVIEW_LINES: Final = 8                 # the preview draws at most this many lines


# --- Device looks -----------------------------------------------------------------------------

def default_look(found: Mapping[str, object]) -> tuple[str, str | None]:
    """The look a contact without ``on`` comes by: ``(look, kit name)``: the kit's
    ``messages`` device, else a phone (kit name None)."""
    kit = mm.kit_in_use(found)
    if kit is not None:
        look = kit.messages.get("device")
        if look in DEVICE_LOOKS:
            return str(look), kit.name
    return DEVICE_LOOKS[0], None


def default_text(found: Mapping[str, object]) -> str:
    """"Game default (pigeon, from the Fantasy kit)", or "Game default (phone)"."""
    look, kit = default_look(found)
    return DEFAULT_KIT.format(look=look, kit=kit) if kit else DEFAULT_PLAIN.format(look=look)


def look_choices(found: Mapping[str, object]) -> list[tuple[object, str]]:
    """The Device look drop-down: the game's default first (None), then each look."""
    return [(None, default_text(found)),
            *((look, LOOK_NAMES.get(look, look.capitalize())) for look in DEVICE_LOOKS)]


def look_of(found: Mapping[str, object], values: Mapping[str, object] | None,
            override: str | None = None) -> str:
    """The look a message comes by: the send line's ``on``, else the contact's, else the
    game's default."""
    own = override or (values or {}).get("device")
    return str(own) if own in DEVICE_LOOKS else default_look(found)[0]


def arrives_text(look: str, title: str) -> str:
    """"Arrives as: “A pigeon lands on the sill with a note from Hana.”"."""
    return ARRIVES.format(notice=device_words(look).arrive.format(name=title))


# --- Send lines -------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SendLine:
    """One ``send <message> from <contact> [on <look>]`` line in scene ``scene``."""

    ref: str
    line: int
    message: str
    contact: str
    device: str | None
    scene: str | None


def send_lines(texts: Mapping[str, str]) -> tuple[SendLine, ...]:
    """Every send line in a scene (indented under a ``label``), in story order (include
    order, then line). Read from the text, so it works before the check has run."""
    out: list[SendLine] = []
    for ref in db.include_order(texts):
        scene: str | None = None
        for number, line in enumerate(texts.get(ref, "").split("\n"), start=1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line[:1].isspace():
                found = _LABEL.match(line)
                scene = found.group(1) if found else None
                continue
            match = _SEND.match(line)
            if match is None or scene is None:
                continue
            message, contact, device = match.groups()
            out.append(SendLine(ref, number, message, contact, device, scene))
    return tuple(out)


def where_text(send: SendLine) -> str:
    """"scene morning, story.vns line 12"."""
    return f"scene {send.scene}, {send.ref.rsplit('/', 1)[-1]} line {send.line}"


# --- Contacts ---------------------------------------------------------------------------------

def contact_entries(decls: Iterable[dec.Decl], texts: Mapping[str, str],
                    sends: Sequence[SendLine] | None = None) -> list[db.Entry]:
    """Contacts: every ``lock contact`` in story order (a name declared twice is listed
    once). ``uses``: the send lines from it."""
    sends = send_lines(texts) if sends is None else sends
    rank = {ref: i for i, ref in enumerate(db.include_order(texts))}
    out: list[db.Entry] = []
    seen: set[str] = set()
    for decl in sorted((d for d in decls if d.kind == dec.CONTACT),
                       key=lambda d: (rank.get(d.ref, len(rank)), d.ref, d.first)):
        if decl.name in seen:
            continue
        seen.add(decl.name)
        title = (decl.values or {}).get("title")
        uses = sum(1 for s in sends if s.contact == decl.name)
        out.append(db.Entry(dec.CONTACT, decl.name, title if isinstance(title, str) and title
                            else decl.name, decl.place, decl.values is not None, uses, decl))
    return out


def refusal(title: str, places: Sequence[SendLine]) -> str | None:
    """Why the contact can't be deleted (each place it sends from), or None."""
    if not places:
        return None
    where = "; ".join(where_text(s) for s in places[:5])
    more = f"; and {len(places) - 5} more" if len(places) > 5 else ""
    lines = "1 line" if len(places) == 1 else f"{len(places)} lines"
    return (f"{title} sends messages from {lines} ({where}{more}), so it can't be deleted "
            f"yet. Remove or change those Send lines first.")


# --- Messages ---------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Message:
    """A message under a contact: its define (``ref``/``first``; None: no define yet),
    its plain ``value`` (None: not plain, or missing) and the send lines that send it from
    this contact (``()``: not sent yet)."""

    name: str
    ref: str | None
    first: int | None
    value: object
    sends: tuple[SendLine, ...]


def _defines(texts: Mapping[str, str]) -> dict[str, tuple[str, int, bool, object]]:
    """Top-level define/default name → (ref, line, plain, value); the first one wins."""
    out: dict[str, tuple[str, int, bool, object]] = {}
    for ref in db.include_order(texts):
        for first, _last, lines in dec.statements(texts[ref]):
            match = _DEFINE.match("\n".join(lines))
            if match is None or match.group(1) in out:
                continue
            ok, value = plain_value(match.group(2))
            out[match.group(1)] = (ref, first, ok, value)
    return out


def is_message(value: object) -> bool:
    """A value ``send`` delivers, or will once replies are in (an ``ask`` line)."""
    found = message_problem(value)
    return found is None or found[0] == "ask"


def messages_of(contact: str, texts: Mapping[str, str],
                sends: Sequence[SendLine] | None = None) -> list[Message]:
    """The contact's messages: sent from it (first-sent order), then the unsent lists of
    lines named ``<contact>_…`` (what **+ New message** makes)."""
    sends = send_lines(texts) if sends is None else sends
    defines = _defines(texts)
    order: dict[str, list[SendLine]] = {}
    for send in sends:
        if send.contact == contact:
            order.setdefault(send.message, []).append(send)
    sent_anywhere = {s.message for s in sends}
    out: list[Message] = []
    for name, places in order.items():
        ref, first, ok, value = defines.get(name, (None, None, False, None))
        out.append(Message(name, ref, first, value if ok else None, tuple(places)))
    prefix = contact + "_"
    for name, (ref, first, ok, value) in defines.items():
        if name.startswith(prefix) and name not in sent_anywhere and ok \
                and type(value) is list and is_message(value):
            out.append(Message(name, ref, first, value, ()))
    return out


def newest(messages: Sequence[Message], sends: Sequence[SendLine]
           ) -> tuple[Message, SendLine | None] | None:
    """The message the preview shows: the last one sent in story order (``sends``, as
    ``send_lines`` gives them), else the last one not sent yet; None without messages."""
    order = {s: i for i, s in enumerate(sends)}
    sent = [(send, m) for m in messages for send in m.sends if send in order]
    if sent:
        send, message = max(sent, key=lambda pair: order[pair[0]])
        return message, send
    return (messages[-1], None) if messages else None


def first_text(value: object) -> str:
    """A message's first line from the contact (the list's short text)."""
    steps = [value] if type(value) is str else value if type(value) is list else []
    for step in steps:
        if type(step) is str:
            return " ".join(step.split())
        if type(step) is dict and len(step) == 1:
            ((key, text),) = step.items()
            if key not in ("me", "time") and type(text) is str:
                return " ".join(text.split())
    return ""


def message_set(texts: Mapping[str, str], name: str) -> mg.DataSet | None:
    """Message ``name`` as the phone-chat step editor's data set (one text reads as one
    line from the contact, and is written back as a list); None when there's no define."""
    found = mg.data_set(texts, name, mg.CHAT)
    if found is None or found.model is not None:
        return found
    ok, value = plain_value(_define_source(found.lines))
    if ok and type(value) is str:
        return replace(found, model=(mg.Step(mg.FROM_CONTACT, value),))
    return found


def _define_source(lines: Sequence[str]) -> str:
    match = _DEFINE.match("\n".join(lines))
    return match.group(2) if match else ""


def new_steps(letter: bool) -> tuple[mg.Step, ...]:
    """A new message's first line, for the author to change."""
    return (mg.Step(mg.FROM_CONTACT, FIRST_LINE[letter]),)


def message_name(contact: str, shown: str, taken: Iterable[str]) -> str:
    """A new message's script name: ``<contact>_<words>``, unique."""
    return mg.slug(f"{contact} {shown}", taken, "message")


def send_text(message: str, contact: str) -> str:
    return f"send {message} from {contact}"


# --- The preview ------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ContactPreview:
    """What the preview draws: ``colors`` (``kitmodel.KitCard``'s six: fill, text, border,
    accent, soft, track), the ``look``, ``letter`` (a signed letter, else chat bubbles),
    ``via`` ("Arrived by pigeon"), ``title`` (the contact's shown name), ``lines``
    (``(side, name, text)``: ``them``, ``me``, ``time``, ``ask``), and ``caption`` under it."""

    colors: tuple[str, str, str, str, str, str]
    look: str
    letter: bool
    via: str
    title: str
    lines: tuple[tuple[str, str, str], ...]
    caption: str


def preview_lines(value: object, title: str) -> tuple[tuple[str, str, str], ...]:
    """A message's lines as the Inbox reads them; a reply point (``ask``) as its replies."""
    steps = [value] if type(value) is str else value if type(value) is list else []
    out: list[tuple[str, str, str]] = []
    for step in steps:
        if type(step) is str:
            out.append(("them", title, step))
        elif type(step) is dict and "ask" in step:
            replies = [v if type(v) is str else v[0] for k, v in step.items()
                       if k not in ("ask", "ignore") and (type(v) is str or (
                           type(v) is list and v and type(v[0]) is str))]
            out.append(("ask", "", "  ·  ".join(str(r) for r in replies)))
        elif type(step) is dict and len(step) == 1:
            ((key, text),) = step.items()
            if type(text) is not str:
                continue
            side = key if key in ("me", "time") else "them"
            out.append((side, str(key) if side == "them" else "", text))
    return tuple(out[:PREVIEW_LINES])


def preview(found: Mapping[str, object], title: str, values: Mapping[str, object] | None,
            messages: Sequence[Message], sends: Sequence[SendLine]) -> ContactPreview:
    """The contact's newest message in its device look, in the game's color scheme."""
    colors = km.cards(found)[0].colors
    pick = newest(messages, sends)
    if pick is None:
        look = look_of(found, values)
        words = device_words(look)
        return ContactPreview(colors, look, words.letter, words.via, title, (),
                              NO_MESSAGES)
    message, send = pick
    look = look_of(found, values, send.device if send is not None else None)
    words = device_words(look)
    caption = NEWEST.format(message=message.name, scene=send.scene) if send is not None \
        else NOT_SENT_CAPTION.format(message=message.name)
    return ContactPreview(colors, look, words.letter, words.via, title,
                          preview_lines(message.value, title), caption)


__all__ = ["ARRIVES", "ContactPreview", "LOOK_NAMES", "Message", "NO_MESSAGES", "SIGNED",
           "SendLine", "arrives_text", "contact_entries", "default_look", "default_text",
           "first_text", "is_message", "look_choices", "look_of", "message_name",
           "message_set", "messages_of", "new_steps", "newest", "preview", "preview_lines",
           "refusal", "send_lines", "send_text", "where_text"]

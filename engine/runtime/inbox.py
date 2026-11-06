"""The Inbox's deliveries and threads: chats you can reread (F65 round 1) and messages sent by
contacts (round 2; plan: specs/skins-contract.md, "Phases 2-4", and proposal I-09 "Chats you
can reread", "Contacts and send").

Why this module exists: a phone chat (F26) used to run once and close, leaving nothing to
reread and nothing in History. Now, when a chat finishes, its lines go into History (F13) in
story order and the whole chat is kept as one **delivery**. Round 2's ``send`` (``runtime/
send.py``) adds a delivery for each message a contact sends. Deliveries are story state: they
live in ``GameState.items`` beside the held items (the codex's one store, ``Codex``), so
saves, loads and rollback replay them exactly, and a save from before F65 loads with an
empty inbox. The Inbox page lists **threads**, one per contact (the codex's ``chat`` kind,
``core/codexkinds.CHAT``), newest first: ``group_threads`` gathers the deliveries, so a
round 1 save's per-chat rows become each contact's history with no change to the save.

- ``InboxLine(side, name, text)``: one shown line: ``"them"`` (``name`` the sender),
  ``"me"`` (the player's message or picked reply), or ``"time"`` (a time divider).
- ``Delivery(key, sid, contact, time, device, lines, sender, message)``: one finished chat
  or one sent message. ``key`` is ``<blake2s of sid, 16 hex>.<n>`` (``n`` counts this line's
  deliveries in the playthrough), short and stable, so the read mark (persistent kind
  ``READ_KIND``, as the codex's own marks) of the first delivery at a line stays with it in
  later playthroughs. ``contact`` is the name shown when it arrived; ``sender`` the declared
  contact's script name ("" for a phone chat); ``message`` the define sent ("" for a chat);
  ``device`` the look it came by ("" for the game's default, which the app resolves from the
  kit; ``"phone"`` for a chat).
- Round 3: ``ask`` (the reply options a sent message ends with, ``(id, text)``, as they were
  when it arrived) and ``reply`` (the id the player picked; ``waiting`` until then, and
  ``answered`` makes the picked copy). Both saved only when set, so older saves load.
- ``ContactThread(key, sender, title, parts)``: one contact's deliveries, oldest first.
  ``group_threads(deliveries, titles)``: the threads, newest first (by their newest
  delivery). A delivery joins its ``sender``'s thread; a phone chat joins the declared
  contact whose shown name (or script name) is its contact, else a thread of its own per
  contact name (``key`` ``"chat:" + name``; a declared contact's key is its script name).
- ``record_chat(interp, m, sig, wait, result)``: ``runtime/minigame.apply``'s hook after a
  minigame's result is stored. For a bundled minigame (``sig.source == "engine"``) with a
  reader in ``CHAT_READERS`` (``phone_chat``), the reader turns the arguments and the result
  into the lines the player saw (the same walk as ``phone_rules`` and the session: a pick
  shows its reply and follow-ups; ``ignore`` or an unreached ask ends the chat). Each
  ``them`` line joins History as a named line and each ``me`` line as a choice row (time
  dividers don't); then the thread joins the inbox (``Codex.add_thread``). A game's own
  plugin that replaces ``phone_chat``, a bad argument, or an empty chat records nothing.
- ``deliveries_json`` / ``deliveries_from_json``: ``ItemsState``'s ``"inbox"`` key: written
  only when there is a delivery (``from`` and ``message`` only when not empty, so a chat is
  written as round 1 wrote it); read from untrusted data with exact keys, shapes and sizes
  (``StateInvalid("items")``, never echoing the input). Round 1 saves have no ``from`` or
  ``message`` and load as they are.

Limits: ``DELIVERIES_MAX`` deliveries and ``CHARS_MAX`` code points of text in all (the
oldest drop, ``kept``), ``LINES_MAX`` lines a delivery (the first ones kept), texts cut to
``TEXT_MAX`` and names to ``NAME_MAX`` code points (lone surrogates shown as U+FFFD). Pure:
no file, clock, or randomness; ``hashlib`` only for the key.
"""

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Final

from engine.core.kits import canonical_look

if TYPE_CHECKING:
    from engine.core.minigame_types import MinigameSig
    from engine.runtime.interpreter import Interpreter
    from engine.script.minigame import Minigame

DELIVERIES_MAX: Final = 1_000           # deliveries kept; past this the oldest drops
LINES_MAX: Final = 1_000                # lines a thread keeps (F26's TOTAL_MAX messages)
TEXT_MAX: Final = 2_000                 # a line's text (code points, "…"-cut)
NAME_MAX: Final = 200                   # a sender, contact, time or device (code points)
CHARS_MAX: Final = 1_000_000            # text kept in all threads; past this the oldest drop
READ_KIND: Final = "inbox_read"         # persistent unlock kind: threads opened on the page
SIDES: Final = frozenset({"them", "me", "time"})
PHONE: Final = "phone"                  # the device look of a phone chat
_KEY: Final = re.compile(r"[0-9a-f]{16}\.[1-9][0-9]{0,5}")
_KEYS: Final = frozenset({"key", "sid", "contact", "time", "device", "lines"})
_MORE: Final = frozenset({"from", "message", "ask", "reply"})   # rounds 2-3, when not empty
ASK_MAX: Final = 4                      # round 3: reply options a delivery keeps
REPLY_TEXT_MAX: Final = 80              # round 3: a reply's text (and a list reply's id)
ID_MAX: Final = 80                      # round 3: a reply's id
CHAT_KEY: Final = "chat:"               # the key prefix of an undeclared contact's thread
_SURROGATE: Final = re.compile("[\ud800-\udfff]")


@dataclass(frozen=True, slots=True)
class InboxLine:
    side: str                           # "them" | "me" | "time"
    name: str                           # the sender of a "them" line; "" otherwise
    text: str


@dataclass(frozen=True, slots=True)
class Delivery:
    key: str
    sid: str                            # the minigame or send line's sid (ADR-0006)
    contact: str                        # the name shown when it arrived
    time: str                           # the chat's opening time, a message's date ("": none)
    device: str                         # the look it came by ("": the game's default)
    lines: tuple[InboxLine, ...]
    sender: str = ""                    # round 2: the declared contact ("" for a chat)
    message: str = ""                   # round 2: the define sent ("" for a chat)
    ask: tuple[tuple[str, str], ...] = ()   # round 3: the reply options, (id, text)
    reply: str = ""                     # round 3: the id the player picked ("": none yet)

    @property
    def waiting(self) -> bool:
        """Round 3: it asks for a reply the player hasn't given yet."""
        return bool(self.ask) and not self.reply

    def reply_text(self) -> str:
        """The text of the picked reply ("" before one)."""
        return next((text for key, text in self.ask if key == self.reply), "")


@dataclass(frozen=True, slots=True)
class ContactThread:
    """One contact's thread on the Inbox page (module docstring)."""

    key: str                            # the contact's script name, or "chat:" + a name
    sender: str                         # the declared contact ("" for none)
    title: str                          # the name shown
    parts: tuple[Delivery, ...]         # oldest first

    @property
    def newest(self) -> Delivery:
        return self.parts[-1]


def shown(text: str, limit: int) -> str:
    """``text`` with lone surrogates as U+FFFD, cut to ``limit`` code points with "…"."""
    text = _SURROGATE.sub("�", text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def delivery_key(sid: str, threads: Sequence[Delivery]) -> str:
    """The next key for a delivery at ``sid`` (module docstring)."""
    base = hashlib.blake2s(sid.encode("utf-8", "surrogatepass"), digest_size=8).hexdigest()
    n = 1 + max((int(t.key.rpartition(".")[2]) for t in threads if t.sid == sid), default=0)
    return f"{base}.{min(n, 999_999)}"


def size(thread: Delivery) -> int:
    """The code points of text ``thread`` holds (``CHARS_MAX``)."""
    return sum(len(line.text) + len(line.name) for line in thread.lines)


def kept(threads: Sequence[Delivery]) -> tuple[Delivery, ...]:
    """``threads`` without the oldest ones past ``DELIVERIES_MAX`` or ``CHARS_MAX``; the
    newest is always kept."""
    out = list(threads[-DELIVERIES_MAX:])
    total = sum(map(size, out))
    while len(out) > 1 and total > CHARS_MAX:
        total -= size(out.pop(0))
    return tuple(out)


def group_threads(deliveries: Sequence[Delivery],
                  titles: Mapping[str, str]) -> tuple[ContactThread, ...]:
    """The Inbox's threads, newest first (module docstring). ``titles``: each declared
    contact's script name to its shown name, in declaration order."""
    by_title: dict[str, str] = {}
    for name, title in titles.items():
        by_title.setdefault(title, name)
    parts: dict[str, list[Delivery]] = {}
    for delivery in deliveries:
        sender = delivery.sender
        if not sender or sender not in titles:
            sender = by_title.get(delivery.contact) or (
                delivery.contact if delivery.contact in titles else "")
        key = sender or CHAT_KEY + delivery.contact
        parts.setdefault(key, []).append(delivery)
    order = {d.key: i for i, d in enumerate(deliveries)}
    threads = []
    for key, found in parts.items():
        sender = "" if key.startswith(CHAT_KEY) else key
        title = titles.get(sender) or found[-1].contact
        threads.append(ContactThread(key, sender, title, tuple(found)))
    threads.sort(key=lambda t: order[t.newest.key], reverse=True)
    return tuple(threads)


# --- Readers: a finished minigame's lines ------------------------------------------------------

Lines = tuple[str, str, list[tuple[str, str, str]]]       # contact, time, (side, name, text)


def _plain(step: object, contact: str) -> tuple[str, str, str]:
    if type(step) is str:
        return ("them", contact, step)
    ((key, value),) = step.items()                          # type: ignore[union-attr]
    if key == "time":
        return ("time", "", value)
    if key == "me":
        return ("me", "", value)
    return ("them", key, value)


def phone_lines(args: Mapping[str, object], result: object) -> Lines:
    """F26's chat as the player saw it, from its checked arguments and its result (a dict
    of ask id to the picked key, ``"ignore"``, or None)."""
    contact = args["contact"]
    time = args.get("time")
    picks = result if isinstance(result, Mapping) else {}
    lines: list[tuple[str, str, str]] = []
    if isinstance(time, str):
        lines.append(("time", "", time))
    for step in args["chat"]:                               # type: ignore[union-attr]
        if isinstance(step, Mapping) and "ask" in step:
            pick = picks.get(step["ask"])
            if type(pick) is not str or pick in ("ask", "ignore") or pick not in step:
                break                                       # ignored, or never reached
            reply = step[pick]
            if type(reply) is str:
                lines.append(("me", "", reply))
            else:
                lines.append(("me", "", reply[0]))          # type: ignore[index]
                lines.extend(_plain(s, contact) for s in reply[1:])  # type: ignore[index]
            continue
        lines.append(_plain(step, contact))
    return contact, time if isinstance(time, str) else "", lines   # type: ignore[return-value]


# Bundled minigames whose finished play becomes an Inbox thread: name -> (reader, device).
CHAT_READERS: Final[dict[str, tuple[Callable[[Mapping[str, object], object], Lines], str]]] = {
    "phone_chat": (phone_lines, PHONE),
}


def build_delivery(sid: str, threads: Sequence[Delivery], contact: str, time: str,
                   device: str, lines: Sequence[tuple[str, str, str]], *, sender: str = "",
                   message: str = "", ask: Sequence[tuple[str, str]] = ()) -> Delivery | None:
    """A delivery from a reader's lines (cut to the limits), or None when nothing shows."""
    out = tuple(InboxLine(side, shown(name, NAME_MAX), shown(text, TEXT_MAX))
                for side, name, text in lines[:LINES_MAX]
                if side in SIDES and type(text) is str and text.strip())
    if not any(line.side != "time" for line in out):
        return None
    return Delivery(delivery_key(sid, threads), sid, shown(contact, NAME_MAX),
                    shown(time, NAME_MAX), device, out, sender, message,
                    tuple((k, t) for k, t in ask[:ASK_MAX]))


def record_chat(interp: "Interpreter", m: "Minigame", sig: "MinigameSig | None",
                wait: object, result: object) -> Delivery | None:
    """``apply``'s hook (module docstring): History lines and the thread, or nothing."""
    if sig is None or sig.source != "engine" or m.name not in CHAT_READERS:
        return None
    args = getattr(wait, "args", None)
    if not isinstance(args, Mapping):
        return None
    reader, device = CHAT_READERS[m.name]
    try:
        contact, time, lines = reader(args, result)
    except Exception:                                       # checked args never get here
        return None
    codex = interp.codex
    thread = build_delivery(m.sid, codex.deliveries(), contact, time, device, lines)
    if thread is None:
        return None
    history = interp.history
    for line in thread.lines:
        if line.side != "time":
            history = history.add_message(m.sid, line.name, line.text, mine=line.side == "me")
    interp.history = history
    codex.add_delivery(thread)
    return thread


# --- Saved (ItemsState's "inbox") ---------------------------------------------------------------

def _delivery_json(t: Delivery) -> dict:
    out: dict = {"key": t.key, "sid": t.sid, "contact": t.contact, "time": t.time,
                 "device": t.device, "lines": [[ln.side, ln.name, ln.text] for ln in t.lines]}
    if t.sender:
        out["from"] = t.sender
    if t.message:
        out["message"] = t.message
    if t.ask:
        out["ask"] = [[key, text] for key, text in t.ask]
    if t.reply:
        out["reply"] = t.reply
    return out


def deliveries_json(threads: Sequence[Delivery]) -> list:
    return [_delivery_json(t) for t in threads]


def _text(value: object, lo: int, hi: int) -> bool:
    return type(value) is str and lo <= len(value) <= hi


def _saved_name(value: object) -> bool:
    """A saved ``from`` or ``message``: a script name (1 to 64 code points, no space)."""
    return type(value) is str and 0 < len(value) <= 64 and not any(
        c.isspace() or ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)


def _ask_from_json(item: dict) -> tuple[tuple[str, str], ...]:
    """Round 3: a saved ``ask`` (1 to ``ASK_MAX`` ``[id, text]`` pairs, ids and texts
    different) and ``reply`` (one of the ids; only with an ask). ``ValueError`` otherwise."""
    if "ask" not in item:
        if "reply" in item:
            raise ValueError("inbox")
        return ()
    raw = item["ask"]
    if type(raw) is not list or not 0 < len(raw) <= ASK_MAX:
        raise ValueError("inbox")
    ask: list[tuple[str, str]] = []
    for pair in raw:
        if (type(pair) is not list or len(pair) != 2 or not _text(pair[0], 1, ID_MAX)
                or not _text(pair[1], 1, REPLY_TEXT_MAX)):
            raise ValueError("inbox")
        ask.append((pair[0], pair[1]))
    if len({k for k, _ in ask}) != len(ask) or len({t for _, t in ask}) != len(ask):
        raise ValueError("inbox")
    if "reply" in item and item["reply"] not in {k for k, _ in ask}:
        raise ValueError("inbox")
    return tuple(ask)


def answered(delivery: Delivery, reply: str) -> Delivery:
    """Round 3: ``delivery`` with ``reply`` (one of its ids) picked."""
    from dataclasses import replace
    assert delivery.waiting and any(k == reply for k, _ in delivery.ask)
    return replace(delivery, reply=reply)


def deliveries_from_json(obj: object) -> tuple[Delivery, ...]:
    """Validate a saved ``"inbox"`` value; ``ValueError`` for anything else (the caller
    raises ``StateInvalid("items")``)."""
    from engine.runtime.menu import sid_ok
    if type(obj) is not list or not 0 < len(obj) <= DELIVERIES_MAX:
        raise ValueError("inbox")
    out: list[Delivery] = []
    keys: set[str] = set()
    for item in obj:
        if type(item) is not dict or not _KEYS <= item.keys() <= _KEYS | _MORE:
            raise ValueError("inbox")
        sender, message = item.get("from", ""), item.get("message", "")
        if ("from" in item and not _saved_name(sender)) \
                or ("message" in item and not _saved_name(message)):
            raise ValueError("inbox")
        key, sid, lines = item["key"], item["sid"], item["lines"]
        if type(key) is not str or not _KEY.fullmatch(key) or key in keys or not sid_ok(sid):
            raise ValueError("inbox")
        if not (_text(item["contact"], 0, NAME_MAX) and _text(item["time"], 0, NAME_MAX)
                and _text(item["device"], 0, NAME_MAX)):
            raise ValueError("inbox")
        if type(lines) is not list or not 0 < len(lines) <= LINES_MAX:
            raise ValueError("inbox")
        parsed = []
        for line in lines:
            if type(line) is not list or len(line) != 3 or line[0] not in SIDES \
                    or type(line[0]) is not str or not _text(line[1], 0, NAME_MAX) \
                    or not _text(line[2], 1, TEXT_MAX):
                raise ValueError("inbox")
            parsed.append(InboxLine(line[0], line[1], line[2]))
        ask = _ask_from_json(item)
        keys.add(key)
        out.append(Delivery(key, sid, item["contact"], item["time"],
                            canonical_look(item["device"]),           # v1: "letters"
                            tuple(parsed), sender, message, ask, item.get("reply", "")))
    if len(out) > 1 and sum(map(size, out)) > CHARS_MAX:
        raise ValueError("inbox")
    return tuple(out)


__all__ = ["CHARS_MAX", "CHAT_KEY", "CHAT_READERS", "ContactThread", "DELIVERIES_MAX",
           "Delivery", "InboxLine", "LINES_MAX", "answered", "NAME_MAX", "PHONE", "READ_KIND", "SIDES",
           "TEXT_MAX", "build_delivery", "deliveries_from_json", "deliveries_json",
           "delivery_key", "group_threads", "kept", "phone_lines", "record_chat", "shown",
           "size"]

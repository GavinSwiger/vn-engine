"""The Inbox's threads: chats you can reread (F65 round 1; plan: specs/skins-contract.md,
"Phases 2-4", and proposal I-09 "Chats you can reread").

Why this module exists: a phone chat (F26) used to run once and close, leaving nothing to
reread and nothing in History. Now, when a chat finishes, its lines go into History (F13) in
story order and the whole chat is kept as one **thread** of the codex's ``chat`` kind
(``core/codexkinds.CHAT``), listed on the Inbox page newest first. Threads are story state:
they live in ``GameState.items`` beside the held items (the codex's one store, ``Codex``),
so saves, loads and rollback replay them exactly, and a save from before F65 loads with an
empty inbox.

- ``InboxLine(side, name, text)``: one shown line: ``"them"`` (``name`` the sender),
  ``"me"`` (the player's message or picked reply), or ``"time"`` (a time divider).
- ``InboxThread(key, sid, contact, time, device, lines)``: one finished chat. ``key`` is
  ``<blake2s of sid, 16 hex>.<n>`` (``n`` counts this line's chats in the playthrough), short
  and stable, so the read mark (persistent kind ``READ_KIND``, as the codex's own marks) of
  the first chat at a line stays with it in later playthroughs.
- ``record_chat(interp, m, sig, wait, result)``: ``runtime/minigame.apply``'s hook after a
  minigame's result is stored. For a bundled minigame (``sig.source == "engine"``) with a
  reader in ``CHAT_READERS`` (``phone_chat``), the reader turns the arguments and the result
  into the lines the player saw (the same walk as ``phone_rules`` and the session: a pick
  shows its reply and follow-ups; ``ignore`` or an unreached ask ends the chat). Each
  ``them`` line joins History as a named line and each ``me`` line as a choice row (time
  dividers don't); then the thread joins the inbox (``Codex.add_thread``). A game's own
  plugin that replaces ``phone_chat``, a bad argument, or an empty chat records nothing.
- ``threads_json`` / ``threads_from_json``: ``ItemsState``'s ``"inbox"`` key: written only
  when there is a thread; read from untrusted data with exact keys, shapes and sizes
  (``StateInvalid("items")``, never echoing the input).

Limits: ``THREADS_MAX`` threads and ``CHARS_MAX`` code points of text in all (the oldest
threads drop, ``kept``), ``LINES_MAX`` lines a thread (the first ones kept), texts cut to ``TEXT_MAX`` and names to ``NAME_MAX`` code points (lone surrogates
shown as U+FFFD). Pure: no file, clock, or randomness; ``hashlib`` only for the key.
"""

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Final

if TYPE_CHECKING:
    from engine.core.minigame_types import MinigameSig
    from engine.runtime.interpreter import Interpreter
    from engine.script.minigame import Minigame

THREADS_MAX: Final = 100                # threads kept; past this the oldest drops
LINES_MAX: Final = 1_000                # lines a thread keeps (F26's TOTAL_MAX messages)
TEXT_MAX: Final = 2_000                 # a line's text (code points, "…"-cut)
NAME_MAX: Final = 200                   # a sender, contact, time or device (code points)
CHARS_MAX: Final = 1_000_000            # text kept in all threads; past this the oldest drop
READ_KIND: Final = "inbox_read"         # persistent unlock kind: threads opened on the page
SIDES: Final = frozenset({"them", "me", "time"})
PHONE: Final = "phone"                  # the device look of a phone chat
_KEY: Final = re.compile(r"[0-9a-f]{16}\.[1-9][0-9]{0,5}")
_THREAD_KEYS: Final = frozenset({"key", "sid", "contact", "time", "device", "lines"})
_SURROGATE: Final = re.compile("[\ud800-\udfff]")


@dataclass(frozen=True, slots=True)
class InboxLine:
    side: str                           # "them" | "me" | "time"
    name: str                           # the sender of a "them" line; "" otherwise
    text: str


@dataclass(frozen=True, slots=True)
class InboxThread:
    key: str
    sid: str                            # the minigame line's sid (ADR-0006)
    contact: str
    time: str                           # the chat's opening time ("" for none)
    device: str                         # the look it came from ("phone")
    lines: tuple[InboxLine, ...]


def shown(text: str, limit: int) -> str:
    """``text`` with lone surrogates as U+FFFD, cut to ``limit`` code points with "…"."""
    text = _SURROGATE.sub("�", text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def thread_key(sid: str, threads: Sequence[InboxThread]) -> str:
    """The next key for a chat at ``sid`` (module docstring)."""
    base = hashlib.blake2s(sid.encode("utf-8", "surrogatepass"), digest_size=8).hexdigest()
    n = 1 + max((int(t.key.rpartition(".")[2]) for t in threads if t.sid == sid), default=0)
    return f"{base}.{min(n, 999_999)}"


def size(thread: InboxThread) -> int:
    """The code points of text ``thread`` holds (``CHARS_MAX``)."""
    return sum(len(line.text) + len(line.name) for line in thread.lines)


def kept(threads: Sequence[InboxThread]) -> tuple[InboxThread, ...]:
    """``threads`` without the oldest ones past ``THREADS_MAX`` or ``CHARS_MAX``; the newest
    is always kept."""
    out = list(threads[-THREADS_MAX:])
    total = sum(map(size, out))
    while len(out) > 1 and total > CHARS_MAX:
        total -= size(out.pop(0))
    return tuple(out)


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


def build_thread(sid: str, threads: Sequence[InboxThread], contact: str, time: str,
                 device: str, lines: Sequence[tuple[str, str, str]]) -> InboxThread | None:
    """A thread from a reader's lines (cut to the limits), or None when nothing shows."""
    out = tuple(InboxLine(side, shown(name, NAME_MAX), shown(text, TEXT_MAX))
                for side, name, text in lines[:LINES_MAX]
                if side in SIDES and type(text) is str and text.strip())
    if not any(line.side != "time" for line in out):
        return None
    return InboxThread(thread_key(sid, threads), sid, shown(contact, NAME_MAX),
                       shown(time, NAME_MAX), device, out)


def record_chat(interp: "Interpreter", m: "Minigame", sig: "MinigameSig | None",
                wait: object, result: object) -> InboxThread | None:
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
    thread = build_thread(m.sid, codex.threads(), contact, time, device, lines)
    if thread is None:
        return None
    history = interp.history
    for line in thread.lines:
        if line.side != "time":
            history = history.add_message(m.sid, line.name, line.text, mine=line.side == "me")
    interp.history = history
    codex.add_thread(thread)
    return thread


# --- Saved (ItemsState's "inbox") ---------------------------------------------------------------

def threads_json(threads: Sequence[InboxThread]) -> list:
    return [{"key": t.key, "sid": t.sid, "contact": t.contact, "time": t.time,
             "device": t.device, "lines": [[ln.side, ln.name, ln.text] for ln in t.lines]}
            for t in threads]


def _text(value: object, lo: int, hi: int) -> bool:
    return type(value) is str and lo <= len(value) <= hi


def threads_from_json(obj: object) -> tuple[InboxThread, ...]:
    """Validate a saved ``"inbox"`` value; ``ValueError`` for anything else (the caller
    raises ``StateInvalid("items")``)."""
    from engine.runtime.menu import sid_ok
    if type(obj) is not list or not 0 < len(obj) <= THREADS_MAX:
        raise ValueError("inbox")
    out: list[InboxThread] = []
    keys: set[str] = set()
    for item in obj:
        if type(item) is not dict or item.keys() != _THREAD_KEYS:
            raise ValueError("inbox")
        key, sid, lines = item["key"], item["sid"], item["lines"]
        if type(key) is not str or not _KEY.fullmatch(key) or key in keys or not sid_ok(sid):
            raise ValueError("inbox")
        if not (_text(item["contact"], 0, NAME_MAX) and _text(item["time"], 0, NAME_MAX)
                and _text(item["device"], 1, NAME_MAX)):
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
        keys.add(key)
        out.append(InboxThread(key, sid, item["contact"], item["time"], item["device"],
                               tuple(parsed)))
    if len(out) > 1 and sum(map(size, out)) > CHARS_MAX:
        raise ValueError("inbox")
    return tuple(out)


__all__ = ["CHARS_MAX", "CHAT_READERS", "InboxLine", "InboxThread", "LINES_MAX", "NAME_MAX",
           "PHONE", "READ_KIND", "SIDES", "TEXT_MAX", "THREADS_MAX", "build_thread", "kept",
           "phone_lines", "record_chat", "shown", "size", "thread_key", "threads_from_json",
           "threads_json"]

"""Insert ▸ Messages: the Send and Open forms (F65 round 2, "Contacts and send" and "Open on
cue"; the script side is ``script/inbox.py``).

Why this module exists: ``send invite from hana`` and ``open inbox`` are story lines an
author inserts where a letter arrives and where the story stops to read it. **Send** has
the **Message** (a define the check child lists as a ``message`` name: text, or a list of
lines), the **Contact** (a ``lock contact`` name) and an optional **Look** that overrides
the contact's (``send … on pigeon``); round 3 adds **Arrives** (now, after some days or
after some scenes) with **How many**, and **Replies**, the answers the player can pick,
split with / (written as the line's ``ask "…" "…"``; a message whose define ends with an
ask keeps it there). **Open** has **Open at**: the Inbox's newest thread, or the newest
that came by one look. The Events row says it in words ("invite from hana, after 1 day,
replies: Yes / No", "the Inbox, newest by pigeon").

Pure Python: ``engine.script`` and ``forms`` only; no Tk (ADR-0008). ``forms._line_forms``
imports this module inside the function, as this one imports ``forms``.
"""

from typing import Final

from engine.script.inbox import (LOOKS, REPLIES_MAX, WORD_INBOX, OpenStep, SendStep,
                                 after_words, quote)
from engine.script.nodes import Statement
from engine.tools.editor.forms import CommandForm, Field, Values, _tokens

_LOOK_SHOWN: Final = ("Phone", "Letters", "Pigeon", "Radio", "Terminal", "Mind")
SEND_LOOKS: Final = ("", *LOOKS)
ARRIVES: Final = ("", "days", "scenes")
_ARRIVES_SHOWN: Final = ("Now", "After some days", "After some scenes")
REPLY_SPLIT: Final = "/"
OPEN_AT: Final = (WORD_INBOX, *LOOKS)


def _read_send(node: Statement, code: str) -> dict[str, str] | None:
    if not isinstance(node, SendStep) or _tokens(code) is None:
        return None
    if node.written() != " ".join(_tokens(code) or ()):
        return None                                     # written another way: script row
    count = node.after_days or node.after_scenes
    return {"message": node.message, "contact": node.contact, "look": node.device or "",
            "arrives": "days" if node.after_days else "scenes" if node.after_scenes else "",
            "after": str(count) if count else "",
            "replies": f" {REPLY_SPLIT} ".join(node.replies)}


def replies_of(text: str) -> tuple[str, ...]:
    """The Replies field as the line's replies: split at /, trimmed, empty ones and repeats
    dropped, at most ``REPLIES_MAX``, quotes and line breaks made plain."""
    out: list[str] = []
    for part in text.split(REPLY_SPLIT):
        reply = " ".join(part.replace('"', "'").split())[:80].strip()
        if reply and reply not in out:
            out.append(reply)
    return tuple(out[:REPLIES_MAX])


def _after(values: Values) -> tuple[int | None, int | None]:
    arrives = values.get("arrives", "").strip()
    if arrives not in ("days", "scenes"):
        return None, None
    written = values.get("after", "").strip()
    count = int(written) if written.isdigit() and len(written) <= 4 else 1
    count = max(1, count)
    return (count, None) if arrives == "days" else (None, count)


def _write_send(values: Values) -> str:
    message = values.get("message", "").strip() or "invite"
    contact = values.get("contact", "").strip() or "hana"
    look = values.get("look", "").strip()
    line = f"send {message} from {contact}" + (f" on {look}" if look else "")
    line += after_words(*_after(values))
    replies = replies_of(values.get("replies", ""))
    if replies:
        line += " ask" + "".join(f' "{quote(r)}"' for r in replies)
    return line


def _summary_send(values: Values) -> str:
    look = values.get("look", "").strip()
    text = f"{values.get('message', '').strip()} from {values.get('contact', '').strip()}"
    text += f", by {look}" if look else ""
    text += after_words(*_after(values)).replace(" after", ", after", 1)
    replies = replies_of(values.get("replies", ""))
    if replies:
        text += ", replies: " + f" {REPLY_SPLIT} ".join(replies)
    return text


SEND: Final = CommandForm(
    "send", "Send a message", "Send", (("send", "send"),), SendStep,
    (Field("message", "Message", "name", "message"),
     Field("contact", "Contact", "name", "contact"),
     Field("look", "Look (if not the contact's)", "pick", options=SEND_LOOKS,
           shown=("The contact's", *_LOOK_SHOWN), optional=True),
     Field("arrives", "Arrives", "pick", options=ARRIVES, shown=_ARRIVES_SHOWN,
           optional=True),
     Field("after", "How many (days or scenes)", "number", optional=True),
     Field("replies", "Replies (split with /)", "text", optional=True)),
    _read_send, _write_send, _summary_send)


def _read_open(node: Statement, code: str) -> dict[str, str] | None:
    if not isinstance(node, OpenStep) or _tokens(code) is None:
        return None
    if node.written() != " ".join(_tokens(code) or ()):
        return None
    return {"at": node.look or WORD_INBOX}


def _write_open(values: Values) -> str:
    at = values.get("at") or WORD_INBOX
    return f"open {at if at in OPEN_AT else WORD_INBOX}"


def _summary_open(values: Values) -> str:
    at = values.get("at") or WORD_INBOX
    return "the Inbox" if at == WORD_INBOX else f"the Inbox, newest by {at}"


OPEN: Final = CommandForm(
    "open", "Open the Inbox", "Open", (("open", "open"),), OpenStep,
    (Field("at", "Open at", "pick", options=OPEN_AT,
           shown=("The newest message", *(f"The newest by {s.lower()}" for s in _LOOK_SHOWN))),),
    _read_open, _write_open, _summary_open)

FORMS: Final[tuple[CommandForm, ...]] = (SEND, OPEN)

__all__ = ["ARRIVES", "FORMS", "OPEN", "OPEN_AT", "REPLY_SPLIT", "SEND", "SEND_LOOKS",
           "replies_of"]

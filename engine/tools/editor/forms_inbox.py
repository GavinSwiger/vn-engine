"""Insert ▸ Messages: the Send and Open forms (F65 round 2, "Contacts and send" and "Open on
cue"; the script side is ``script/inbox.py``).

Why this module exists: ``send invite from hana`` and ``open inbox`` are story lines an
author inserts where a letter arrives and where the story stops to read it. **Send** has
the **Message** (a define the check child lists as a ``message`` name: text, or a list of
lines), the **Contact** (a ``lock contact`` name) and an optional **Look** that overrides
the contact's (``send … on pigeon``). **Open** has **Open at**: the Inbox's newest thread,
or the newest that came by one look. The Events row says it in words ("invite from hana",
"the Inbox, newest by pigeon"). Database ▸ Contacts, which writes ``lock contact`` lines,
is round 3.

Pure Python: ``engine.script`` and ``forms`` only; no Tk (ADR-0008). ``forms._line_forms``
imports this module inside the function, as this one imports ``forms``.
"""

from typing import Final

from engine.script.inbox import LOOKS, WORD_INBOX, OpenStep, SendStep
from engine.script.nodes import Statement
from engine.tools.editor.forms import CommandForm, Field, Values, _tokens

_LOOK_SHOWN: Final = ("Phone", "Letters", "Pigeon", "Radio", "Terminal", "Mind")
SEND_LOOKS: Final = ("", *LOOKS)
OPEN_AT: Final = (WORD_INBOX, *LOOKS)


def _read_send(node: Statement, code: str) -> dict[str, str] | None:
    if not isinstance(node, SendStep) or _tokens(code) is None:
        return None
    if node.written() != " ".join(_tokens(code) or ()):
        return None                                     # written another way: script row
    return {"message": node.message, "contact": node.contact, "look": node.device or ""}


def _write_send(values: Values) -> str:
    message = values.get("message", "").strip() or "invite"
    contact = values.get("contact", "").strip() or "hana"
    look = values.get("look", "").strip()
    return f"send {message} from {contact}" + (f" on {look}" if look else "")


def _summary_send(values: Values) -> str:
    look = values.get("look", "").strip()
    text = f"{values.get('message', '').strip()} from {values.get('contact', '').strip()}"
    return text + (f", by {look}" if look else "")


SEND: Final = CommandForm(
    "send", "Send a message", "Send", (("send", "send"),), SendStep,
    (Field("message", "Message", "name", "message"),
     Field("contact", "Contact", "name", "contact"),
     Field("look", "Look (if not the contact's)", "pick", options=SEND_LOOKS,
           shown=("The contact's", *_LOOK_SHOWN), optional=True)),
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

__all__ = ["FORMS", "OPEN", "OPEN_AT", "SEND", "SEND_LOOKS"]

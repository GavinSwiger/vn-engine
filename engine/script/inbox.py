"""Contacts, ``send`` and ``open``: messages that arrive in the Inbox (F65 round 2, proposal
I-09 "Contacts and send" and "Open on cue"; plan: specs/skins-contract.md, "Phases 2-4").

Why this module exists: round 1 kept finished phone chats on an Inbox page. Epistolary
games need more: someone writes to the player while the story goes on, the letter waits
in the Inbox until it is read, and a scene can stop for it. Three lines do that:

- ``lock contact hana "Hana" [on pigeon] [image hana portrait]`` (top level) declares a
  **contact**: the name the script uses, the name the Inbox shows, the device look their
  messages come by (default: the kit's, else a phone), and a picture. A row of F19's
  ``lock`` table (``routes.LOCK_TARGETS``), so ``contact`` is a word only right after
  ``lock`` (ADR-0010 rule 2). ``ContactDecl``; ``Program.contacts``.
- ``send <message> from <contact> [on <look>]`` (in a scene) delivers the message to the
  contact's thread with an arrival notice. The message is a ``define`` (or ``default``):
  one text, or a list of lines in the phone chat's format (texts from the contact,
  ``{"me": …}`` for the player's own, ``{"time": …}`` for a divider, ``{"Ren": …}`` for
  someone else). Replies (``{"ask": …}``) come with round 3 (E452's ``ask`` form until then).
  ``SendStep``.
- ``open inbox`` / ``open <look>`` (in a scene) opens the Inbox at the newest thread (the
  newest that came by that look) and the story waits until the player closes it.
  ``OpenStep``.

**Positional words** (ADR-0010 rules 3 and 4). ``send`` and ``open`` are not reserved: a line
is the statement only when the word is its first and a name follows with no quoted text
(``send "On my way."`` stays dialogue by a character called send); ``send invite from
"Hana"`` is still read as ``send``, so the quotes get their own message. An unclaimed line
with no quoted text is E448 / E449, which names the other reading when the game defines a
character of that name. ``from``, ``on`` and ``inbox`` are words only in these places.

**Through the trigger core** (ADR-0011): each ``send`` line is one trigger of kind
``message`` (``collect``: name its sid, ``live=False``, ``once``, payload the line), armed by
the line and fired at once; round 3's ``after 1 day`` only adds timing to the same trigger.

**Checks.** Parse: E448 (``send``), E449 (``open``), E450 (``lock contact``; at most
``CONTACTS_MAX``, names unique, in ``check_story``). Whole game (``check_story``): E451 (a
contact no ``lock contact`` declares), E452 (a message no define or default declares, or a
define whose literal value isn't a message), W311 (``open <look>`` when nothing comes by that
look). Run time: E453 (``runtime/send.py``). ``SendStep`` and ``OpenStep`` never branch: the
story map and reach treat them as plain lines.
"""

import ast
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Final

from engine.script import inbox_messages
from engine.script.chapter import _shown
from engine.script.diagnostics import Diagnostic, ScriptWarning
from engine.script.identity import register_declaration, walk_block
from engine.script.lexer import NAME, STRING, RawStatement
from engine.script.messages import TEMPLATES, format_message
from engine.script.nodes import Default, Define, Label, Node, Statement
from engine.script.routes import LockTarget, register_target
from engine.script.stage import TEXT, WORD, _Chunk, _image_name, _written
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import (NoText, ParseContext, PositionalWord, StatementSpec,
                                      register_positional)
from engine.script.suggest import suggest
from engine.script.triggers import Trigger
from engine.script.words import canonical_name, check_name

TEMPLATES.update(inbox_messages.TEMPLATES)

WORD_SEND: Final = "send"
WORD_OPEN: Final = "open"
WORD_FROM: Final = "from"
WORD_ON: Final = "on"
WORD_IMAGE: Final = "image"
WORD_CONTACT: Final = "contact"
WORD_INBOX: Final = "inbox"
TRIGGER_KIND: Final = "message"          # the trigger core's kind for a send line
# The device looks (``core/kits.DEVICE_LOOKS``; script may import core, but the words are
# the script's, so they are listed once in ``inbox_messages``).
LOOKS: Final = inbox_messages.LOOKS
CONTACTS_MAX: Final = 200                # contacts in a game (E450 ``many``)
NAME_MAX: Final = 64                     # a contact's script name (code points)
TITLE_MAX: Final = 40                    # a contact's shown name (code points, as shown)
STEPS_MAX: Final = 200                   # lines in one message
TEXT_MAX: Final = 2_000                  # one line of a message (code points)
SENDER_MAX: Final = 40                   # another sender's name in a message
_LITERAL_MAX: Final = 200_000            # define sources the check reads as a literal


# --- Nodes ------------------------------------------------------------------------------------

@dataclass(slots=True, kw_only=True)
class ContactDecl(Node):
    """``lock contact <name> "Title" [on <look>] [image <picture>]`` at the top level. A
    declaration, sid ``"contact:" + name``. ``device`` None: the game's default look."""

    name: str
    title: str
    device: str | None = None
    image: str | None = None


@dataclass(slots=True, kw_only=True)
class SendStep(Statement):
    """``send <message> from <contact> [on <look>]``. Not a checkpoint; never branches."""

    message: str
    contact: str
    device: str | None = None

    def identity_key(self) -> tuple[str, ...]:
        return (WORD_SEND, self.message, self.contact, self.device or "")

    def written(self) -> str:
        """The line as Studio writes it back."""
        tail = f" on {self.device}" if self.device else ""
        return f"send {self.message} from {self.contact}{tail}"


@dataclass(slots=True, kw_only=True)
class OpenStep(Statement):
    """``open inbox`` / ``open <look>``: ``look`` None for ``inbox``. A story wait (no
    checkpoint) until the Inbox closes; never branches."""

    look: str | None = None

    def identity_key(self) -> tuple[str, ...]:
        return (WORD_OPEN, self.look or WORD_INBOX)

    def written(self) -> str:
        return f"open {self.look or WORD_INBOX}"


# --- Parsing: send and open -------------------------------------------------------------------

def _after(raw: RawStatement, index: int) -> str:
    """The source from token ``index`` to the end of the line ("" past the last token)."""
    tokens = raw.tokens
    if index >= len(tokens):
        return ""
    token = tokens[index]
    return raw.rest_from(token.line, token.column).rstrip().rstrip(":").rstrip()


def _name_ok(ctx: ParseContext, written: str) -> str | None:
    problem = check_name(written)
    if problem is not None:
        ctx.error(problem[0], *problem[1])
        return None
    return canonical_name(written)


def send_claims(raw: RawStatement) -> bool:
    """A ``send`` line is the statement when a name follows the word and the line has no
    quoted text, or when ``from`` is its third word (module docstring)."""
    tokens = raw.tokens
    if len(tokens) < 2 or tokens[1].kind != NAME:
        return False
    if len(tokens) > 2 and tokens[2].kind == NAME and tokens[2].text == WORD_FROM:
        return True
    return all(t.kind != STRING for t in tokens)


def open_claims(raw: RawStatement) -> bool:
    """An ``open`` line is the statement when a name follows the word and the line has no
    quoted text."""
    tokens = raw.tokens
    return len(tokens) >= 2 and tokens[1].kind == NAME and all(t.kind != STRING for t in tokens)


def parse_send(raw: RawStatement, ctx: ParseContext) -> SendStep | None:
    tokens = raw.tokens
    if raw.ends_with_colon:
        ctx.error("E448", "colon")
        return None
    message = _name_ok(ctx, tokens[1].text)
    if message is None:
        return None
    if len(tokens) < 3 or tokens[2].kind != NAME or tokens[2].text != WORD_FROM:
        ctx.error("E448", "from", message)
        return None
    if len(tokens) < 4:
        ctx.error("E448", "contact", "")
        return None
    if tokens[3].kind == STRING:
        ctx.error("E448", "quoted", " ".join(tokens[3].text.split()) or "hana")
        return None
    if tokens[3].kind != NAME:
        ctx.error("E448", "contact", _after(raw, 3))
        return None
    contact = _name_ok(ctx, tokens[3].text)
    if contact is None:
        return None
    device: str | None = None
    at = 4
    if len(tokens) > at and tokens[at].kind == NAME and tokens[at].text == WORD_ON:
        found = tokens[at + 1].text if len(tokens) > at + 1 else ""
        if found not in LOOKS:
            ctx.error("E448", "device", found, suggest(found, LOOKS) if found else None)
            return None
        device = found
        at += 2
    if len(tokens) > at:
        ctx.error("E448", "extra", _after(raw, at))
        return None
    return SendStep(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                    message=message, contact=contact, device=device)


def parse_open(raw: RawStatement, ctx: ParseContext) -> OpenStep | None:
    tokens = raw.tokens
    if raw.ends_with_colon:
        ctx.error("E449", "colon")
        return None
    target = tokens[1].text
    if target != WORD_INBOX and target not in LOOKS:
        ctx.error("E449", "target", target, suggest(target, (WORD_INBOX, *LOOKS)))
        return None
    if len(tokens) > 2:
        ctx.error("E449", "extra", _after(raw, 2))
        return None
    return OpenStep(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                    look=None if target == WORD_INBOX else target)


def _no_text(code: str, word: str, words: tuple[str, ...]):
    def no_text(item: NoText, defined: bool) -> Diagnostic:
        """ADR-0010 rule 4: a line starting with the word, no quoted text, not claimed."""
        rest = item.rest.split()
        found = rest[0] if rest else ""
        form = "speaker" if defined else "word"
        return Diagnostic(code, item.file, item.line, None,
                          (form, found, suggest(found, words) if found and words else None),
                          source_line=item.source_line, stmt=item.line)
    return no_text


SEND_SPEC: Final = StatementSpec(word=WORD_SEND, placement="story", takes_block=False,
                                 tail="script", parse=parse_send)
OPEN_SPEC: Final = StatementSpec(word=WORD_OPEN, placement="story", takes_block=False,
                                 tail="script", parse=parse_open)
register_positional(PositionalWord(SEND_SPEC, send_claims, _no_text("E448", WORD_SEND, ())))
register_positional(PositionalWord(OPEN_SPEC, open_claims,
                                   _no_text("E449", WORD_OPEN, (WORD_INBOX, *LOOKS))))


# --- Parsing: lock contact (a row of F19's lock table) ------------------------------------------

def _string(raw: RawStatement, chunk: _Chunk) -> str:
    return next((t.text for t in raw.tokens
                 if t.kind == STRING and (t.line, t.column) == (chunk.line, chunk.column)), "")


def _contact_top(raw: RawStatement, ctx: ParseContext, unlock: bool, chunks: list[_Chunk],
                 colon: bool) -> ContactDecl | None:
    """``lock contact <name> "Title" [on <look>] [image <picture>]`` (module docstring)."""
    if unlock:
        ctx.error("E450", "unlock")
        return None
    if len(chunks) < 2 or chunks[0].kind != WORD or chunks[1].kind != TEXT:
        ctx.error("E450", "need")
        return None
    name = _name_ok(ctx, chunks[0].text)
    if name is None:
        return None
    if len(name) > NAME_MAX:
        ctx.error("E450", "need")
        return None
    shown = _shown(_string(raw, chunks[1]))
    if shown is None:
        ctx.error("E450", "tags", name)
        return None
    title = " ".join(shown.split())
    if not title:
        ctx.error("E450", "empty", name)
        return None
    if len(title) > TITLE_MAX:
        ctx.error("E450", "long", name, len(title))
        return None
    device: str | None = None
    image: str | None = None
    seen: set[str] = set()
    at = 2
    while at < len(chunks):
        chunk = chunks[at]
        word = chunk.text if chunk.kind == WORD else ""
        if word not in (WORD_ON, WORD_IMAGE):
            ctx.error("E450", "left", _written(raw, chunks[at:]))
            return None
        if word in seen:
            ctx.error("E450", "twice", word)
            return None
        seen.add(word)
        if word == WORD_ON:
            found = chunks[at + 1].text if at + 1 < len(chunks) else ""
            if found not in LOOKS:
                ctx.error("E450", "look", found, None, suggest(found, LOOKS) if found else None)
                return None
            device = found
            at += 2
            continue
        stop = at + 1
        while stop < len(chunks) and not (chunks[stop].kind == WORD
                                          and chunks[stop].text == WORD_ON):
            stop += 1
        image = _image_name(ctx, WORD_IMAGE, raw, chunks[at + 1:stop])
        if image is None:
            return None
        at = stop
    if colon:
        ctx.error("E450", "colon")
        return None
    return ContactDecl(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                       name=name, title=title, device=device, image=image)


def _contact_block(raw: RawStatement, ctx: ParseContext, unlock: bool, chunks: list[_Chunk],
                   colon: bool) -> None:
    ctx.error("E450", "unlock" if unlock else "label")
    return None


CONTACT_TARGET: Final = LockTarget(WORD_CONTACT, _contact_top, _contact_block)
register_target(CONTACT_TARGET)
register_declaration(ContactDecl, lambda node: "contact:" + node.name)  # type: ignore[attr-defined]


# --- Messages: what a sent value may be -----------------------------------------------------------

def _kind(value: object) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True or False"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, dict):
        return "a dictionary"
    if isinstance(value, (tuple, set)):
        return "a tuple or set"
    return f"a {type(value).__name__}"


def _text_problem(text: object) -> str | None:
    if type(text) is not str:
        return f"isn't text; it is {_kind(text)}."
    if not text.strip():
        return "is empty."
    if len(text) > TEXT_MAX:
        return f"is {len(text):,} characters long; a line is at most {TEXT_MAX:,}."
    return None


def message_problem(value: object) -> tuple[str, object, str] | None:
    """Why ``value`` can't be sent (E452/E453's ``(form, where, detail)``), or None. A text,
    or a list of 1 to ``STEPS_MAX`` lines: a text from the contact, or a one-key dict:
    ``me``, ``time``, or another sender's name (1 to ``SENDER_MAX`` characters); an
    ``{"ask": …}`` is the ``ask`` form (round 3)."""
    if type(value) is str:
        found = _text_problem(value)
        return None if found is None else ("empty", 1, "") if not value.strip() \
            else ("line", 1, found)
    if type(value) is not list:
        return ("kind", 0, _kind(value))
    if not value:
        return ("empty", 0, "")
    if len(value) > STEPS_MAX:
        return ("steps", 0, f"{len(value):,}")
    for index, step in enumerate(value, start=1):
        if type(step) is str:
            found = _text_problem(step)
            if found is not None:
                return ("line", index, found)
            continue
        if type(step) is dict and "ask" in step:
            return ("ask", index, "")
        if type(step) is not dict or len(step) != 1:
            return ("step", index, _kind(step) if type(step) is not dict
                    else f"a dictionary with {len(step):,} keys")
        ((key, text),) = step.items()
        if type(key) is not str or not key.strip() or len(key) > SENDER_MAX \
                or key != key.strip():
            return ("line", index, f"is from a sender whose name isn't 1 to {SENDER_MAX} "
                                   "characters with no space at either end.")
        found = _text_problem(text)
        if found is not None:
            return ("line", index, found)
    return None


def message_lines(value: Any, contact: str) -> list[tuple[str, str, str]]:
    """A checked message (``message_problem`` is None) as Inbox lines ``(side, name,
    text)``: ``them`` with ``contact`` (or another sender), ``me``, or ``time``."""
    steps = [value] if type(value) is str else value
    out: list[tuple[str, str, str]] = []
    for step in steps:
        if type(step) is str:
            out.append(("them", contact, step))
            continue
        ((key, text),) = step.items()
        if key == "me":
            out.append(("me", "", text))
        elif key == "time":
            out.append(("time", "", text))
        else:
            out.append(("them", key, text))
    return out


# --- Whole-game checks ---------------------------------------------------------------------------

def _steps(nodes: Iterable[Node]) -> Iterator[Statement]:
    for node in nodes:
        if isinstance(node, Label):
            for stmt, _ in walk_block(node.block):
                if isinstance(stmt, (SendStep, OpenStep)):
                    yield stmt


class _NotPlain(Exception):
    pass


def _plain(node: ast.AST) -> object:
    """A plain value written in Python's syntax: text, numbers, True/False/None, lists,
    tuples, sets and dicts of them (read from the tree; nothing runs)."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_plain(x) for x in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_plain(x) for x in node.elts)
    if isinstance(node, ast.Set):
        return {_plain(x) for x in node.elts}
    if isinstance(node, ast.Dict):
        if any(k is None for k in node.keys):
            raise _NotPlain
        return {_plain(k): _plain(v) for k, v in zip(node.keys, node.values)}  # type: ignore[arg-type]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)             and isinstance(node.operand, ast.Constant)             and type(node.operand.value) in (int, float):
        return -node.operand.value
    raise _NotPlain


def plain_value(source: str) -> tuple[bool, object]:
    """``(True, value)`` when ``source`` is a plain value (``_plain``), else ``(False,
    None)``: how the check reads a message's define without running it."""
    if len(source) > _LITERAL_MAX:
        return False, None
    try:
        return True, _plain(ast.parse(source.strip(), mode="eval").body)
    except (_NotPlain, SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return False, None


def _literal(node: Define | Default) -> tuple[bool, object]:
    """The define's value when its source is a plain value; else it is checked when sent."""
    return plain_value(node.value.source)


def _has_phone_chat(nodes: Iterable[Node]) -> bool:
    from engine.script.minigame import Minigame
    return any(isinstance(stmt, Minigame) and stmt.name == "phone_chat"
               for node in nodes if isinstance(node, Label)
               for stmt, _ in walk_block(node.block))


def _kit_look(config: Any) -> str | None:
    from engine.core.kits import kit_of, MESSAGES_DEVICE
    found = kit_of(config) if config is not None else None
    look = found.messages.get(MESSAGES_DEVICE) if found is not None else None
    return look if isinstance(look, str) else None


def check_story(nodes: Iterable[Node], add: Callable[[Diagnostic], object],
                config: Any = None) -> list[ScriptWarning]:
    """E450's ``dup`` and ``many``, E451, E452 to ``add``; W311 returned (module docstring).
    ``config`` None (tools without one): no W311 (the kit's device is unknown)."""
    nodes = list(nodes)
    warnings: list[ScriptWarning] = []
    contacts: dict[str, ContactDecl] = {}
    for node in nodes:
        if not isinstance(node, ContactDecl):
            continue
        first = contacts.get(node.name)
        if first is not None:
            add(Diagnostic("E450", node.file, node.line, None, ("dup", node.name, first.line),
                           stmt=node.line))
        elif len(contacts) == CONTACTS_MAX:
            add(Diagnostic("E450", node.file, node.line, None,
                           ("many", "", CONTACTS_MAX), stmt=node.line))
        else:
            contacts[node.name] = node
    values: dict[str, Define | Default] = {}
    for node in nodes:
        if isinstance(node, (Define, Default)):
            values.setdefault(node.name, node)
    steps = list(_steps(nodes))
    checked: dict[str, tuple[str, object, str] | None] = {}
    default = _kit_look(config) or LOOKS[0]
    looks: set[str] = {c.device or default for c in contacts.values()}
    if _has_phone_chat(nodes):
        looks.add(LOOKS[0])                           # round 1: a finished phone chat
    for stmt in steps:
        if not isinstance(stmt, SendStep):
            continue
        if stmt.device:
            looks.add(stmt.device)
        if stmt.contact not in contacts:
            add(Diagnostic("E451", stmt.file, stmt.line, None,
                           (stmt.contact, suggest(stmt.contact, contacts), bool(contacts)),
                           stmt=stmt.line))
        declared = values.get(stmt.message)
        if declared is None:
            names = [n for n in values]
            add(Diagnostic("E452", stmt.file, stmt.line, None,
                           ("unknown", stmt.message, 0, "", suggest(stmt.message, names)),
                           stmt=stmt.line))
            continue
        if stmt.message not in checked:
            ok, value = _literal(declared)
            checked[stmt.message] = message_problem(value) if ok else None
        found = checked[stmt.message]
        if found is not None:
            form, where, detail = found
            add(Diagnostic("E452", declared.file, declared.line, None,
                           (form, stmt.message, where, detail, None), stmt=declared.line))
            checked[stmt.message] = None              # once per define
    if config is None:
        return warnings                               # the kit's look is unknown here
    for stmt in steps:
        if isinstance(stmt, OpenStep) and stmt.look is not None and stmt.look not in looks:
            warnings.append(ScriptWarning(format_message("W311", (stmt.look,)), code="W311",
                                          file=stmt.file.ref, line=stmt.line))
    return warnings


# --- The trigger core's "message" kind (ADR-0011) -------------------------------------------------

def collect(program: Any) -> Iterator[Trigger]:
    """Each ``send`` line as a trigger of kind ``message``: named by its sid, armed by the
    line (``live=False``), ``once``, the line as its payload. Round 3 adds ``after`` timing."""
    for stmt in program.iter_statements():
        if isinstance(stmt, SendStep):
            yield Trigger(TRIGGER_KIND, stmt.sid, stmt, once=True, live=False, payload=stmt)


def uses_send(program: Any) -> bool:
    """Whether the script has a ``send`` line (the quick menu's Inbox button)."""
    return any(isinstance(stmt, SendStep) for stmt in program.iter_statements())


# --- Studio docs (F45): Insert ▸ Messages, and the contact declaration ----------------------------

DOCS_HEADING: Final = "Messages"          # docs/script-language.md

for _doc in (
        StatementDoc(
            WORD_SEND, "Send a message", "Messages", "send <message> from <contact> [on <look>]",
            "Delivers a message to the Inbox, in the contact's thread, with a notice that it "
            "arrived. The message is a define: one text, or a list of lines.",
            "send invite from hana", DOCS_HEADING, "F65", fields=("invite", "hana")),
        StatementDoc(
            WORD_OPEN, "Open the Inbox", "Messages", "open inbox|<look>",
            "Opens the Inbox at the newest message, and the story waits until the player "
            "closes it. open pigeon opens it at the newest message that came by pigeon.",
            "open inbox", DOCS_HEADING, "F65", fields=("inbox",)),
        StatementDoc(
            "lock", "Contact", "Declarations",
            'lock contact <name> "shown name" [on <look>] [image <picture>]',
            "Declares someone who sends messages: the name the script uses, the name the "
            "Inbox shows, the device look their messages come by (phone, letters, pigeon, "
            "radio, terminal or mind) and their picture.",
            'lock contact ren "Ren" on pigeon', DOCS_HEADING, "F65", fields=("ren", "Ren")),
):
    register_doc(_doc)
del _doc


__all__ = ["CONTACTS_MAX", "CONTACT_TARGET", "ContactDecl", "DOCS_HEADING", "LOOKS",
           "OPEN_SPEC", "OpenStep", "SEND_SPEC", "STEPS_MAX", "SendStep", "TEXT_MAX",
           "TITLE_MAX", "TRIGGER_KIND", "WORD_INBOX", "check_story", "collect",
           "message_lines", "message_problem", "open_claims", "parse_open", "parse_send",
           "plain_value",
           "send_claims", "uses_send"]

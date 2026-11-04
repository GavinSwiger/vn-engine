"""The phone chat's pure rules (F26 ``04`` §3, §4.2, §5.1, §6.2, §6.5, §6.6).

Why this module exists: everything about a phone chat that can be decided without a window
lives here, so it can be tested directly and shared by the hooks (``check_args``,
``outcome_for``) and the playable session (F26-3): the argument checks R1–R14, parsing,
typing times, results, the fixed outcomes, the W176 text and its glyph test
(``glyph_chars``, ``glyph_missing``), and the phone and thread geometry.

Pure: no clock, no randomness, no I/O. Imports only ``engine.minigames.api``, the shared
``bundled.rule_text``, ``engine.ui.layouts`` (``wrap_text``, ``pitch``), and the stdlib
(AC-F26-01); ``glyph_missing`` takes its font by duck type, so ``pygame`` is a
``TYPE_CHECKING`` import only (``07`` I-2). The checks run on author values that F23 has
already frozen; they never raise and never change the arguments. Every refusal and W176
text is a draft for the narrative designer (F26 ``01`` §5.3, §5.4; ``07`` I-9).

Every author text goes through ``rule_text.line_problem`` (F26 ``07`` I-1, G4): edge white
space is refused everywhere, and a text that is only white space keeps each rule's "empty"
form.
"""

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from engine.minigames.api import Outcome
from engine.minigames.bundled.rule_text import cut, kind_words, line_problem, quoted, value_echo
from engine.render.text import missing_glyphs
from engine.ui.layouts import Measure, pitch, wrap_text

if TYPE_CHECKING:
    import pygame

STEPS_MAX, TOTAL_MAX, ASKS_MAX, OPTIONS_MAX, AFTER_MAX = 200, 1000, 20, 4, 20
MESSAGE_MAX, BREAKS_MAX, REPLY_MAX, NAME_MAX, TIME_MAX = 300, 4, 80, 40, 20
ID_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}", re.ASCII)
GAP_S, TYPE_MIN_S, TYPE_MAX_S = 0.5, 0.6, 2.0
GUARD_S, GUARD_EPSILON = 0.25, 1e-6           # F07's guard; inclusive boundary (F24 07 I-6)
IGNORE: Final = "ignore"
# Token ranges, clamped in start without a warning (04 §12).
BODY_WIDTH: Final = (360, 600)
HEADER_SIZE: Final = (24, 40)
MESSAGE_SIZE: Final = (24, 36)

_MESSAGE_RULE = (f"a message is 1 to {MESSAGE_MAX} characters with up to {BREAKS_MAX} line "
                 "breaks.")
_REPLY_RULE = f"a reply is 1 to {REPLY_MAX} characters on one line."
_STEP_KINDS = 'a message (text), a one-key dictionary such as {"me": "hi"}, or an ask'
_NAME_RULE = "letters, digits, and _."
_EDGE = "starts or ends with a space. Remove the space."

# Geometry (canvas units; 01 §6.1, 04 §6.5).
BODY_RADIUS, SCREEN_INSET, SCREEN_RADIUS = 40, 12, 28
BAR_PAD, HEADER_PAD, REPLY_ROOM, REPLY_MIN, EDGE = 8, 24, 120, 56, 16
BUBBLE_SHARE, BUBBLE_PAD_X, BUBBLE_PAD_Y, BUBBLE_RADIUS = 0.75, 12, 8, 18
GAP, GAP_CHANGE, NAME_GAP, TYPING_W = 8, 16, 4, 72

Rect = tuple[float, float, float, float]


# --- Data ------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Message:
    sender: str | None                         # None: the player ("me"); else contact or a name
    text: str


@dataclass(frozen=True, slots=True)
class TimeMark:
    text: str


@dataclass(frozen=True, slots=True)
class Typing:
    """The typing indicator's thread item."""
    sender: str


@dataclass(frozen=True, slots=True)
class Option:
    key: str
    text: str
    after: tuple[Message | TimeMark, ...]      # follow-ups, ≤ 20


@dataclass(frozen=True, slots=True)
class Ask:
    id: str
    options: tuple[Option, ...]                # written order = button order
    ignore: bool
    ignore_label: str | None                   # None → the words' "ignore"


Step = Message | TimeMark | Ask


@dataclass(frozen=True, slots=True)
class Chat:
    steps: tuple[Step, ...]
    contact: str
    time: str | None
    asks: tuple[str, ...]                      # ask ids, chat order
    group: bool                                # ≥ 2 distinct senders other than me (PR-F26-14)


@dataclass(frozen=True, slots=True)
class PhoneLayout:
    """The phone in canvas units; every rectangle is ``(x, y, w, h)``."""
    body: Rect
    screen: Rect
    bar: Rect
    header: Rect
    thread: Rect
    reply: Rect
    reply_cap: float


@dataclass(frozen=True, slots=True)
class Placed:
    """One thread item; ``y`` is the bubble's top from the content top (a name sits in the
    ``p(small) + 4`` above it)."""
    kind: Literal["them", "me", "time", "typing"]
    y: float
    x: float
    w: float
    h: float
    lines: tuple[str, ...]                     # wrapped text; () for typing
    name: str | None                           # sender label above (group, run start)
    sender: str | None                         # the item's sender (None: me or a divider)


# --- The checks (R1–R14) ---------------------------------------------------------------------

def _form(text: object, lo: int, hi: int, breaks: int = 0) -> str | None:
    """``rule_text.line_problem``, with only-white-space text as "empty" (07 I-1)."""
    if type(text) is str and text.strip() == "":
        return "empty"
    return line_problem(text, lo, hi, breaks=breaks)


def _message_problem(text: object, where: str) -> str | None:
    """R4."""
    form = _form(text, 1, MESSAGE_MAX, BREAKS_MAX)
    if form is None:
        return None
    if form == "not text":
        return f"the message in {where} isn't text; it is {kind_words(text)}."
    if form == "empty":
        return f"{where} is empty; {_MESSAGE_RULE}"
    if form == "length":
        size = len(text)                                       # type: ignore[arg-type]
        return f"{where} is {size:,} characters long; {_MESSAGE_RULE}"
    if form == "breaks":
        count = text.count("\n")                               # type: ignore[union-attr]
        return f"{where} has {count:,} line breaks; {_MESSAGE_RULE}"
    if form == "hidden":
        return f"{where} has a hidden or control character; {_MESSAGE_RULE}"
    return f"{where} starts or ends with a space or line break. Remove it."


def _sender_problem(sender: object, where: str) -> str | None:
    """R5."""
    form = _form(sender, 1, NAME_MAX)
    if form is None:
        return None
    if form == "edge":
        return f"{where} is from {quoted(sender)}, which {_EDGE}"   # type: ignore[arg-type]
    return (f"{where} is from {value_echo(sender)}, but a sender's name is 1 to {NAME_MAX} "
            "characters on one line.")


def _time_problem(text: object, where: str) -> str | None:
    """R6."""
    form = _form(text, 1, TIME_MAX)
    if form is None:
        return None
    if form == "edge":
        return f"the time in {where} is {quoted(text)}, which {_EDGE}"   # type: ignore[arg-type]
    return (f"the time in {where} is {value_echo(text)}, but a time is 1 to {TIME_MAX} "
            'characters on one line, such as "11:51 PM".')


def _plain_step_problem(step: object, where: str) -> str | None:
    """R3–R6 for a step that isn't an ask."""
    if type(step) is str:
        return _message_problem(step, where)
    if type(step) is dict and len(step) == 1:
        ((key, value),) = step.items()
        if key == "me":
            return _message_problem(value, where)
        if key == "time":
            return _time_problem(value, where)
        return _sender_problem(key, where) or _message_problem(value, where)
    kind = (f"a dictionary with {len(step):,} keys" if type(step) is dict  # type: ignore[arg-type]
            else kind_words(step))
    return f"{where} must be {_STEP_KINDS}, but it is {kind}."


def _reply_problem(key: str, value: object, ask_id: str) -> str | None:
    """R9 and R10 for one option. ``key`` and ``ask_id`` already passed ``ID_RE`` (ASCII
    letters, digits, _), so ``quoted`` would only ``cut`` them: ``cut`` keeps a printable
    chat off ``rule_text.hidden`` (AC-F26-24's fast path)."""
    said = f'reply "{cut(key)}" of ask "{cut(ask_id)}"'
    after: list | None = None
    if type(value) is str:
        text = value
    elif type(value) is list and value and type(value[0]) is str:
        text, after = value[0], value[1:]
    else:
        if type(value) is list:
            kind = "an empty list" if not value else \
                f"a list that starts with {kind_words(value[0])}"
        else:
            kind = kind_words(value)
        return (f"{said} must be its text, or a list of its text and what follows, but it is "
                f"{kind}.")
    form = _form(text, 1, REPLY_MAX)
    if form == "empty":
        return f"{said} is empty; {_REPLY_RULE}"
    if form == "length":
        return f"{said} is {len(text):,} characters long; {_REPLY_RULE}"
    if form in ("breaks", "hidden"):
        return f"{said} has a line break or hidden character; {_REPLY_RULE}"
    if form == "edge":
        return f"{said} {_EDGE}"
    if after is None:
        return None
    if len(after) > AFTER_MAX:
        return f"{said} is followed by {len(after):,} steps; the most is {AFTER_MAX}."
    for k, step in enumerate(after, start=1):
        if type(step) is dict and "ask" in step:
            return f"{said} is followed by an ask; put the next ask after this one in chat."
        found = _plain_step_problem(step, f"step {k} after {said}")
        if found is not None:
            return found
    return None


def _ignore_problem(value: object, ask_id: str) -> str | None:
    """R11. ``type is bool`` first, so 1 and 0 are refused."""
    if type(value) is bool:
        return None
    form = _form(value, 1, NAME_MAX)
    if form is None:
        return None
    if form == "edge":
        shown = quoted(value)                                  # type: ignore[arg-type]
        return f"ignore in ask {quoted(ask_id)} is {shown}, which {_EDGE}"
    return (f"ignore in ask {quoted(ask_id)} must be True, False, or a button label of 1 to "
            f"{NAME_MAX} characters, but it is {value_echo(value)}.")


def _ask_problem(step: dict, where: str, ids: list[str]) -> str | None:
    """R7–R11 for one top-level ask."""
    ask_id = step["ask"]
    if type(ask_id) is not str or ID_RE.fullmatch(ask_id) is None:
        return f"{where} asks {value_echo(ask_id)}, but an ask's name is {_NAME_RULE}"
    if ask_id in ids:
        return f"{where} asks {quoted(ask_id)} again; each ask needs its own name."
    ids.append(ask_id)
    options = [(key, value) for key, value in step.items() if key != "ask" and key != IGNORE]
    if not 1 <= len(options) <= OPTIONS_MAX:
        return (f"ask {quoted(ask_id)} has {len(options):,} replies; an ask has 1 to "
                f'{OPTIONS_MAX}, plus "ignore".')
    for key, _ in options:
        if type(key) is not str or ID_RE.fullmatch(key) is None:
            return (f"ask {quoted(ask_id)} has a reply named {value_echo(key)}; a reply's name "
                    f"is {_NAME_RULE}")
    for key, value in options:
        found = _reply_problem(key, value, ask_id)
        if found is not None:
            return found
    if IGNORE in step:
        return _ignore_problem(step[IGNORE], ask_id)
    return None


def _total(chat: list) -> int:
    """04 §5.1 step 2's lenient count: steps plus every list reply's follow-ups."""
    total = len(chat)
    for step in chat:
        if type(step) is dict and "ask" in step:
            for key, value in step.items():
                if key != "ask" and key != IGNORE and type(value) is list and value:
                    total += len(value) - 1
    return total


def problem(args: dict) -> str | None:
    """R1–R14 in F26 ``04`` §5.1's order: the first problem's reason, or None. No side
    effects; never raises for frozen values."""
    chat = args.get("chat")
    if type(chat) is not list:                                         # R1
        return ('chat must be a list of messages and asks, e.g. ["hi!", {"me": "hey"}], but '
                f"it is {kind_words(chat)}.")
    if not 1 <= len(chat) <= STEPS_MAX:                                # R2
        return f"chat must have 1 to {STEPS_MAX} steps, but it has {len(chat):,}."
    total = _total(chat)
    if total > TOTAL_MAX:
        return f"chat has {total:,} steps counting replies; the most is {TOTAL_MAX:,}."
    ids: list[str] = []
    for i, step in enumerate(chat, start=1):                           # R3–R11
        where = f"step {i}"
        if type(step) is dict and "ask" in step:
            found = _ask_problem(step, where, ids)
        else:
            found = _plain_step_problem(step, where)
        if found is not None:
            return found
    if len(ids) > ASKS_MAX:                                            # R12
        return f"chat has {len(ids):,} asks; a chat can have up to {ASKS_MAX}."
    contact = args.get("contact")                                      # R13
    form = _form(contact, 1, NAME_MAX)
    if form == "edge":
        return f"contact {quoted(contact)} {_EDGE}"                    # type: ignore[arg-type]
    if form is not None:
        return (f"contact must be a name of 1 to {NAME_MAX} characters on one line, but it is "
                f"{value_echo(contact)}.")
    time = args.get("time")                                            # R14
    form = None if time is None else _form(time, 1, TIME_MAX)
    if form == "edge":
        return f"time {quoted(time)} {_EDGE}"                          # type: ignore[arg-type]
    if form is not None:
        return (f'time must be text such as "11:42 PM" (1 to {TIME_MAX} characters on one '
                f"line), or None, but it is {value_echo(time)}.")
    return None


# --- Parsing, timing, results, and outcomes --------------------------------------------------

def _plain_step(step: str | dict, contact: str) -> Message | TimeMark:
    if type(step) is str:
        return Message(contact, step)
    ((key, value),) = step.items()
    if key == "time":
        return TimeMark(value)
    return Message(None if key == "me" else key, value)


def _ask(step: dict, contact: str) -> Ask:
    options = []
    for key, value in step.items():
        if key == "ask" or key == IGNORE:
            continue
        if type(value) is str:
            options.append(Option(key, value, ()))
        else:
            options.append(Option(key, value[0],
                                  tuple(_plain_step(s, contact) for s in value[1:])))
    ignore = step.get(IGNORE, False)
    return Ask(id=step["ask"], options=tuple(options), ignore=ignore is not False,
               ignore_label=ignore if type(ignore) is str else None)


def parse(args: dict) -> Chat:
    """The checked arguments as a ``Chat``. The arguments must pass ``problem``."""
    assert problem(args) is None, "parse() needs checked arguments"
    contact = args["contact"]
    steps = tuple(_ask(s, contact) if type(s) is dict and "ask" in s
                  else _plain_step(s, contact) for s in args["chat"])
    senders = set()
    for step in steps:
        for item in ((o for a in step.options for o in a.after) if isinstance(step, Ask)
                     else (step,)):
            if isinstance(item, Message) and item.sender is not None:
                senders.add(item.sender)
    return Chat(steps=steps, contact=contact, time=args.get("time"),
                asks=tuple(s.id for s in steps if isinstance(s, Ask)),
                group=len(senders) >= 2)


def typing_s(text: str) -> float:
    """The typing indicator's time for a message: clamp(0.4 + 0.025·n, 0.6, 2.0) seconds,
    n in code points (PR-F26-06)."""
    return min(max(0.4 + 0.025 * len(text), TYPE_MIN_S), TYPE_MAX_S)


def result_of(chat: Chat, picks: Mapping[str, str]) -> dict[str, str | None]:
    """The ``into`` value: every ask id in chat order, mapped to the picked key, "ignore",
    or None if not reached; ``{}`` with no asks (PR-F26-11)."""
    return {ask_id: picks.get(ask_id) for ask_id in chat.asks}


def fixed_outcome(kind: str, chat: Chat) -> Outcome:
    """``outcome_for``'s answer for ``"test"`` and ``"skipped"`` (04 §6.6): each ask's first
    option, never "ignore", and no changes. Never None."""
    if kind not in ("test", "skipped"):
        raise ValueError(f"unknown outcome kind {kind!r}")
    return Outcome({s.id: s.options[0].key for s in chat.steps if isinstance(s, Ask)}, ())


def w176_text(ch: str, where: str) -> str:
    """W176's text (01 §5.4; 04 §6.7): a character the message font can't draw, with the
    locator of its first use (``step 4``, ``reply "yes" of ask "awake"``, …)."""
    return (f'The phone chat\'s message font can\'t draw "{ch}" (U+{ord(ch):04X}), used in '
            f"{where}, so it shows as a box. Set plugin.phone_chat.message.text_font to a font "
            "that has it, or remove the character.")


# --- Missing glyphs (W176; 04 §6.7) ----------------------------------------------------------

GLYPH_CHARS_MAX: Final = 2_000          # the scan stops at this many distinct characters
_ZWJ: Final = "\u200d"
_SKIPPED: Final = frozenset({"Mn", "Me", "Cf"})


def glyph_chars(chat: Chat) -> list[tuple[str, str]]:
    """The distinct characters of every message, reply, and follow-up message, in chat order,
    each with its first locator (``step 4``, ``reply "yes" of ask "awake"``, ``step 1 after
    reply "yes" of ask "awake"``). White space, line breaks, ZWJ, and ``Mn``/``Me``/``Cf``
    characters are skipped; the list stops at 2,000 characters."""
    found: dict[str, str] = {}

    def add(text: str, where: str) -> bool:
        for ch in text:
            if ch in found or ch.isspace() or ch == _ZWJ \
                    or unicodedata.category(ch) in _SKIPPED:
                continue
            found[ch] = where
            if len(found) >= GLYPH_CHARS_MAX:
                return False
        return True

    for i, step in enumerate(chat.steps, start=1):
        if isinstance(step, Message):
            if not add(step.text, f"step {i}"):
                break
        elif isinstance(step, Ask):
            for option in step.options:
                said = f"reply {quoted(option.key)} of ask {quoted(step.id)}"
                if not add(option.text, said):
                    return list(found.items())
                for k, item in enumerate(option.after, start=1):
                    if isinstance(item, Message) and not add(item.text, f"step {k} after {said}"):
                        return list(found.items())
    return list(found.items())


# F52 (04 §3, 07 I-5): the glyph test now lives in ``render.text``; F26 keeps its name.
glyph_missing = missing_glyphs


# --- Geometry --------------------------------------------------------------------------------

def p(size: float) -> int:
    """Line pitch: round(1.4·size)."""
    return pitch(size)


def _rect(area: object) -> Rect:
    """An area as ``(x, y, w, h)``: a 4-tuple, or a ``Box``-like object."""
    if hasattr(area, "x"):
        return (area.x, area.y, area.w, area.h)       # type: ignore[attr-defined]
    x, y, w, h = area                                 # type: ignore[misc]
    return (x, y, w, h)


def phone_layout(area: object, *, s: int, bar_size: int, header_size: int, body_width: int,
                 reply_h: float | None) -> PhoneLayout:
    """The phone in F23's content ``area`` (04 §6.5). ``s`` is the scaled message size,
    ``bar_size`` the scaled bar size (24 at 100%), ``header_size`` the scaled header size;
    ``reply_h`` is the reply rows' total height, or None for the placeholder."""
    ax, ay, aw, ah = _rect(area)
    bw = min(aw, body_width + 8 * (s - 24))
    body = (ax + aw / 2 - bw / 2, ay, bw, ah)
    sx, sy, sw, sh = (body[0] + SCREEN_INSET, ay + SCREEN_INSET, bw - 2 * SCREEN_INSET,
                      ah - 2 * SCREEN_INSET)
    bar = (sx, sy, sw, p(bar_size) + BAR_PAD)
    header = (sx, sy + bar[3], sw, p(header_size) + HEADER_PAD)
    cap = sh - bar[3] - header[3] - REPLY_ROOM
    rh = max(REPLY_MIN, p(s) + 16) if reply_h is None else min(cap, reply_h)
    reply = (sx + EDGE, sy + sh - EDGE - rh, sw - 2 * EDGE, rh)
    top = header[1] + header[3] + EDGE
    thread = (sx + EDGE, top, sw - 2 * EDGE, reply[1] - EDGE - top)
    return PhoneLayout(body=body, screen=(sx, sy, sw, sh), bar=bar, header=header,
                       thread=thread, reply=reply, reply_cap=cap)


def thread_layout(items: Sequence[Message | TimeMark | Typing], width: float, *, s: int,
                  small: int, group: bool, measure: Measure,
                  start: tuple[Placed, ...] = ()) -> tuple[Placed, ...]:
    """The thread's items placed after ``start`` (append-only; 04 §6.5). ``width`` is the
    thread's width, ``s`` the message size, ``small`` the name and divider size; ``measure``
    is ``(text, size) → width`` in canvas units.

    Gaps: 8, or 16 at a sender change (me counts as a sender) and above and below a divider.
    A divider ends a sender's run, so in a group chat the next them bubble is named again.
    A bubble that replaces a typing item (laid out after the same ``start``) gets the item's
    y and name."""
    placed = list(start)
    tw = BUBBLE_SHARE * width - 2 * BUBBLE_PAD_X
    for item in items:
        prev = placed[-1] if placed else None
        if isinstance(item, TimeMark):
            top = 0 if prev is None else prev.y + prev.h + GAP_CHANGE
            w = min(width, measure(item.text, small))
            placed.append(Placed("time", top, (width - w) / 2, w, p(small), (item.text,),
                                 None, None))
            continue
        sender = item.sender
        kind = "typing" if isinstance(item, Typing) else ("me" if sender is None else "them")
        if prev is None:
            top = 0
        else:
            same = prev.kind != "time" and prev.sender == sender
            top = prev.y + prev.h + (GAP if same else GAP_CHANGE)
        name = None
        if group and kind != "me" and (prev is None or prev.kind in ("time", "me")
                                       or prev.sender != sender):
            name = sender
            top += p(small) + NAME_GAP
        if kind == "typing":
            placed.append(Placed("typing", top, 0, TYPING_W, p(s) + 2 * BUBBLE_PAD_Y, (),
                                 name, sender))
            continue
        lines = tuple(wrap_text(item.text, tw, s, measure))   # type: ignore[union-attr]
        w = max(measure(line, s) for line in lines) + 2 * BUBBLE_PAD_X
        h = len(lines) * p(s) + 2 * BUBBLE_PAD_Y
        x = 0 if kind == "them" else width - w
        placed.append(Placed(kind, top, x, w, h, lines, name, sender))  # type: ignore[arg-type]
    return tuple(placed)


def ease_in_out(t: float) -> float:
    """ui-system §5's ease: (1 − cos πt) / 2, for t clamped to 0–1."""
    t = min(max(t, 0.0), 1.0)
    return (1 - math.cos(math.pi * t)) / 2


__all__ = ["AFTER_MAX", "ASKS_MAX", "Ask", "BODY_WIDTH", "BREAKS_MAX", "Chat", "GAP_S",
           "GUARD_EPSILON", "GUARD_S", "HEADER_SIZE", "ID_RE", "IGNORE", "MESSAGE_MAX",
           "MESSAGE_SIZE", "Message", "NAME_MAX", "OPTIONS_MAX", "Option", "PhoneLayout",
           "Placed", "REPLY_MAX", "STEPS_MAX", "Step", "TIME_MAX", "TOTAL_MAX", "TYPE_MAX_S",
           "TYPE_MIN_S", "TimeMark", "Typing", "ease_in_out", "fixed_outcome", "glyph_chars",
           "glyph_missing", "p", "parse",
           "phone_layout", "problem", "result_of", "thread_layout", "typing_s", "w176_text"]

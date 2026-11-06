"""``send`` and ``open`` at run time (F65 round 2, "Contacts and send" and "Open on cue";
script side: ``script/inbox.py``; the Inbox's store: ``runtime/inbox.py``).

Why this module exists: a ``send`` line delivers a message to a contact's Inbox thread while
the story goes on, and an ``open`` line stops the story at the Inbox. Both are story steps:

- **send** goes through the trigger core (ADR-0011). The kind ``message`` is registered here
  (``collect``: one trigger per ``send`` line, named by its sid, armed only by its line,
  ``once``, with the line's ``after`` timing; ``on_fire`` delivers). ``run_send`` arms the
  line's trigger and, when it fits (always without ``after``), takes it and delivers at
  once: nothing stays armed, so the save is as before. With ``after 1 day`` / ``after 2
  parts`` / ``after 2 scenes`` it stays armed (saved in ``GameState.triggers``) until a
  clock change or a scene entered makes it fit; the message's value is read then, and the
  notice shows then (never on a quiet re-run). ``pending`` lists what waits, for the F3 overlay.
- **Delivering** (``deliver``) reads the message's variable now (a define, or a default the
  story changed), checks it (``script/inbox.message_problem``; a value a save can't keep or
  that isn't a message is the story error E453 at the ``send`` line), turns it into lines
  (``message_lines``), and adds one ``Delivery`` to the codex's store with the contact's
  shown name, the device (``send … on``, else the contact's ``on``, else "": the game's
  default, the app's to resolve from the kit), the date when the game uses the story clock,
  and the sender and message names. It is story state (``ItemsState.inbox``), so saves,
  loads, going back and the quiet forward re-run end where the first run did. Then it holds
  ``MessageArrived`` for the arrival notice (a quiet re-run's holds are dropped, so going
  forward again shows no second notice).
- **open** is a story wait with no checkpoint (``begin_wait(make=partial(OpenInbox, …))``,
  F30's fake crash's pattern): the app opens the Inbox page at the newest thread (or the
  newest that came by ``look``) and ends the wait when the player closes it. A quiet re-run
  ends it at once (``begin_wait``'s rule); a headless run ends it as any wait.

- **Replies** (round 3): a delivery may carry an ask (``Delivery.ask``). The Inbox page posts
  ``ReplyMessage(key, reply)``; ``on_reply`` takes it only while ``can_reply`` (the story
  waits at a line, or in an ``open`` wait) and records it as story state: the delivery
  answered and the reply as a History choice row. At a line it is a step of its own
  (``_reply_step``: the same line recorded again with the reply, as a pick is a step), so
  going back once takes it back and F14's forward re-run gives it again
  (``forward_reply``, from the remembered step). In an ``open`` wait it joins the next
  step, and the re-run gives it again at the ``open`` (``remembered_replies``). ``inbox``
  in author Python is ``InboxView`` (``bind_view``, as ``clock``): ``inbox.reply("invite")``.

``uses_send(program)`` is here so the app (which reaches ``engine.script`` only through
``loading.py``, 07 I-7) can ask whether to show the quick menu's Inbox button. Layering as
``clock.py``: below the interpreter, reaching it only through the ``interp`` it is given.
"""

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, Final

from engine.core.logsetup import get_logger
from engine.runtime import clock as clock_mod
from engine.runtime import triggers as triggers_mod
from engine.runtime.commands import Event, MessageArrived, OpenInbox
from engine.runtime.errors import AuthorRefusal, StoryError
from engine.runtime.inbox import Delivery, answered, build_delivery
from engine.runtime.stage import flush_stage
from engine.runtime.values import Unsaveable, freeze
from engine.script import nodes
from engine.script.inbox import (TRIGGER_KIND, WORD_INBOX, ContactDecl, OpenStep, SendStep,
                                 collect, message_ask, message_lines, message_problem)
from engine.script.inbox import uses_send as _uses_send
from engine.script.triggers import Trigger

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.runtime.state import GameState
    from engine.runtime.triggers import Fired

_log = get_logger("runtime")

_MISSING: Final = object()


def _cached(interp: "Interpreter") -> tuple[dict[str, ContactDecl], bool]:
    """The program's contacts by name and whether it uses the story clock, once per
    program (kept on the interpreter)."""
    program = interp.program
    found = getattr(interp, "_inbox_cache", None)
    if found is None or found[0] is not program:
        contacts = {c.name: c for c in getattr(program, "contacts", ())}
        found = (program, contacts, clock_mod.uses_clock(program))
        interp._inbox_cache = found                        # type: ignore[attr-defined]
    return found[1], found[2]


def _value(interp: "Interpreter", stmt: SendStep) -> Any:
    """The message's value now, checked (E453 at the ``send`` line otherwise)."""
    value = interp.G.get(stmt.message, _MISSING)
    if value is _MISSING:
        raise AuthorRefusal.of("E453", "missing", stmt.message)
    try:
        value = freeze(value)
    except Unsaveable as e:
        raise AuthorRefusal.of("E453", "unsaveable", stmt.message, 0, e.kind) from None
    found = message_problem(value)
    if found is not None:
        form, where, detail = found
        raise AuthorRefusal.of("E453", form, stmt.message, where, detail)
    return value


def deliver(interp: "Interpreter", stmt: SendStep) -> None:
    """One message into the contact's thread, and the arrival notice (module docstring)."""
    contacts, clocked = _cached(interp)
    contact = contacts.get(stmt.contact)
    title = contact.title if contact is not None else stmt.contact
    device = stmt.device or (contact.device if contact is not None else None) or ""
    value = _value(interp, stmt)
    when = ""
    if clocked:
        cal = clock_mod.calendar(interp)
        when = cal.date(clock_mod.now(interp).day)
    codex = interp.codex
    ask = tuple((r, r) for r in stmt.replies) or message_ask(value)
    delivery = build_delivery(stmt.sid, codex.deliveries(), title, when, device,
                              message_lines(value, title), sender=stmt.contact,
                              message=stmt.message, ask=ask)
    if delivery is None:                                  # checked: never empty
        return
    codex.add_delivery(delivery)
    interp._hold(MessageArrived(stmt.contact, title, device,
                                contact.image if contact is not None else None,
                                stmt.contact))


def run_send(interp: "Interpreter", stmt: SendStep) -> "Step":
    """``send <message> from <contact>``: arm the line's trigger, and deliver when it fits
    (module docstring): at once, or, with ``after``, when the trigger core fires it. Not a
    checkpoint."""
    from engine.runtime.interpreter import Step         # below the interpreter (docstring)
    trigger_id = f"{TRIGGER_KIND}:{stmt.sid}"
    triggers_mod.arm(interp, trigger_id)
    trigger = interp.trigger_table.by_id[trigger_id]    # type: ignore[attr-defined]
    found = triggers_mod.fits(interp, trigger)
    if found is not None:
        triggers_mod.take(interp, found)
        deliver(interp, stmt)
    return Step.CONTINUE


def _on_fire(interp: "Interpreter", fired: "Fired") -> None:
    """The kind's ``on_fire``: an armed message whose moment came (round 3's ``after``). A
    quiet re-run delivers it again without the notice (``_hold``'s rule)."""
    payload = fired.trigger.payload
    if isinstance(payload, SendStep):
        deliver(interp, payload)


def _collect(program: Any) -> "list[Trigger]":
    return list(collect(program))


def run_open(interp: "Interpreter", stmt: OpenStep) -> "Step":
    """``open inbox`` / ``open <look>``: the stage flushed, then an ``OpenInbox`` wait. In a
    quiet re-run the wait ends at once; the replies the player gave in it come back here
    (``remembered_replies``), so the next step matches the remembered one."""
    flush_stage(interp)
    if interp.timeline.replaying:
        for delivery, reply in remembered_replies(interp, None):
            _answer(interp, delivery, reply)
    return interp.begin_wait(stmt, seconds=None, for_stage=False,
                             make=partial(OpenInbox, look=stmt.look))


def pending(interp: "Interpreter") -> list[str]:
    """Round 3: the messages waiting to arrive, for the F3 overlay ("invite from hana: day
    3", "note from hana: day 4, Afternoon" for ``after N parts``, "late from ren: in 2
    scenes"), in the order they were sent."""
    table = getattr(interp, "trigger_table", None)
    out: list[str] = []
    for armed in interp.triggers.armed:
        trigger = table.by_id.get(armed.id) if table is not None else None
        stmt = trigger.payload if trigger is not None else None
        if not isinstance(stmt, SendStep):
            continue
        when = (f"day {armed.day}" if armed.day is not None
                else f"in {armed.scenes} scene{'' if armed.scenes == 1 else 's'}"
                if armed.scenes is not None else "now")
        if armed.day is not None and armed.part is not None:
            parts = clock_mod.calendar(interp).parts
            when += f", {parts[min(armed.part, len(parts) - 1)]}"
        out.append(f"{stmt.message} from {stmt.contact}: {when}")
    return out


# --- Replies (round 3, "Replies as choices") ----------------------------------------------------

@dataclass(frozen=True, slots=True)
class ReplyMessage(Event):
    """The player picked reply ``reply`` (an id of its ``ask``) to delivery ``key`` on the
    Inbox page. Ignored unless that delivery waits for a reply and ``can_reply``."""

    key: str
    reply: str


def can_reply(interp: "Interpreter") -> bool:
    """Whether a reply counts now: the story waits at a line for a click, or at an ``open``
    (its Inbox wait), with no forward re-run, minigame or menu. At a menu the player answers
    after picking (a reply is a choice of its own, so it doesn't share a step)."""
    from engine.runtime.interpreter import Status         # below the interpreter
    t = interp.timeline
    if (interp.status is not Status.WAITING or t.replaying or t.replay != 0
            or interp.minigame_wait is not None):
        return False
    current = interp.current
    if interp.waiting_for is None:
        return type(current) is nodes.Say
    return type(current) is OpenStep


def find_delivery(interp: "Interpreter", key: object) -> Delivery | None:
    return next((d for d in interp.codex.deliveries() if d.key == key), None) \
        if type(key) is str else None


def _answer(interp: "Interpreter", delivery: Delivery, reply: str) -> None:
    """The story state of a reply: the delivery answered, and the reply in History as a
    choice row."""
    picked = answered(delivery, reply)
    interp.codex.replace_delivery(picked)
    interp.history = interp.history.add_message(delivery.sid, "", picked.reply_text(),
                                                mine=True)


def on_reply(interp: "Interpreter", event: ReplyMessage) -> None:
    """``ReplyMessage``: answer the delivery when it waits for a reply, the reply is one of
    its options and ``can_reply``; else nothing (logged). At a line the reply is a step of
    its own, like a pick (``_reply_step``): going back once takes it back at the same line,
    going forward gives it again. In an ``open`` wait it joins the next step."""
    delivery = find_delivery(interp, event.key)
    if delivery is None or not delivery.waiting:
        _log.debug("Reply ignored: no message waits for a reply there.")
        return
    if type(event.reply) is not str or all(k != event.reply for k, _ in delivery.ask):
        _log.debug("Reply ignored: it isn't one of the message's replies.")
        return
    if not can_reply(interp):
        _log.debug("Reply ignored: the story can't take a reply now.")
        return
    _answer(interp, delivery, event.reply)
    current = interp.current
    if interp.waiting_for is None and type(current) is nodes.Say:
        _reply_step(interp, current)


def _reply_step(interp: "Interpreter", say: nodes.Say) -> "Step":
    """Record the line ``say`` again as a step that holds the reply (no line shown again,
    nothing added to History but the reply). In a quiet re-run it is the chain's landing
    (``_land_replay``) like any checkpoint."""
    from engine.runtime.interpreter import Step         # below the interpreter
    try:
        state = interp._snapshot(say, interp.call_stack)
    except StoryError as e:                              # E85e: a value a save can't keep
        interp._fail(e)
        return Step.WAIT
    timeline = interp.timeline
    matched = timeline.record(state)
    if timeline.replaying:
        interp._land_replay(say, state, matched)
        return Step.WAIT
    timeline.shown = timeline.cursor
    interp._settle(say, state)
    return Step.WAIT


def remembered_replies(interp: "Interpreter", at: str | None
                       ) -> list[tuple[Delivery, str]]:
    """The replies the remembered next step holds that the story doesn't yet: deliveries
    here that wait for a reply and that step answered. ``at``: only when that step is at
    the line ``at`` (a reply's own step); None: any step (an ``open`` wait)."""
    t = interp.timeline
    nxt = t.cursor + 1
    if t.cursor < 0 or nxt >= len(t.states):
        return []
    state: "GameState" = t.states[nxt]
    if at is not None and state.position != at:
        return []
    picked = {d.key: d.reply for d in state.items.inbox if d.reply}
    if not picked:
        return []
    return [(d, picked[d.key]) for d in interp.codex.deliveries()
            if d.waiting and d.key in picked and any(k == picked[d.key] for k, _ in d.ask)]


def forward_reply(interp: "Interpreter", say: nodes.Say) -> bool:
    """F14's forward re-run at ``say``: when the remembered next step is a reply given at
    this line, give it again and record that step (True); else False (the re-run clicks)."""
    found = remembered_replies(interp, say.sid)
    if not found:
        return False
    from engine.runtime.interpreter import Status       # below the interpreter
    for delivery, reply in found:
        _answer(interp, delivery, reply)
    interp.status = Status.RUNNING
    interp.defer(partial(_reply_step, say=say))
    return True


class InboxView:
    """``inbox`` in author Python (round 3): ``inbox.reply("invite")`` is the id of the
    reply the player picked to the newest message ``invite`` they answered (a list ask's
    text; a named ask's key), "" before any. Reads only: a write is E454, and so is a
    name that isn't text. A game's own ``inbox`` hides it (``bind_view``)."""

    __slots__ = ("_interp",)

    def __init__(self, interp: "Interpreter | None" = None) -> None:
        object.__setattr__(self, "_interp", interp)

    def reply(self, message: object) -> str:
        if type(message) is not str:
            raise AuthorRefusal.of("E454", "name", _kind_of(message))
        interp = object.__getattribute__(self, "_interp")
        if interp is None:
            return ""
        for delivery in reversed(interp.codex.deliveries()):
            if delivery.message == message and delivery.reply:
                return delivery.reply
        return ""

    def __setattr__(self, name: str, value: object) -> None:
        raise AuthorRefusal.of("E454", "write")

    def __delattr__(self, name: str) -> None:
        raise AuthorRefusal.of("E454", "write")

    def __repr__(self) -> str:
        return "inbox"


def _kind_of(value: object) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True or False"
    if isinstance(value, (int, float)):
        return "a number"
    return f"a {type(value).__name__}"


def bind_view(G: dict, interp: "Interpreter") -> None:
    """Put the ``inbox`` view in ``G``'s builtins (as ``clock``: never a story variable,
    never saved, and a game's own ``inbox`` hides it)."""
    builtins: Any = G.get("__builtins__")
    if isinstance(builtins, dict):
        builtins[WORD_INBOX] = InboxView(interp)


def uses_send(program: Any) -> bool:
    """Whether the script has a ``send`` line (the quick menu's Inbox button)."""
    return _uses_send(program)


triggers_mod.register_kind(TRIGGER_KIND, collect=_collect, on_fire=_on_fire)


__all__ = ["InboxView", "ReplyMessage", "bind_view", "can_reply", "deliver", "find_delivery",
           "forward_reply", "on_reply", "pending", "remembered_replies", "run_open",
           "run_send", "uses_send"]

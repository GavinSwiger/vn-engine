"""``send`` and ``open`` at run time (F65 round 2, "Contacts and send" and "Open on cue";
script side: ``script/inbox.py``; the Inbox's store: ``runtime/inbox.py``).

Why this module exists: a ``send`` line delivers a message to a contact's Inbox thread while
the story goes on, and an ``open`` line stops the story at the Inbox. Both are story steps:

- **send** goes through the trigger core (ADR-0011) from the start, so round 3's delays add
  timing, not plumbing. The kind ``message`` is registered here (``collect``: one trigger per
  ``send`` line, named by its sid, armed only by its line, ``once``; ``on_fire`` delivers).
  ``run_send`` arms the line's trigger and, when it fits (always, until round 3's ``after``),
  takes it and delivers at once: nothing stays armed, so the save is as before.
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

``uses_send(program)`` is here so the app (which reaches ``engine.script`` only through
``loading.py``, 07 I-7) can ask whether to show the quick menu's Inbox button. Layering as
``clock.py``: below the interpreter, reaching it only through the ``interp`` it is given.
"""

from functools import partial
from typing import TYPE_CHECKING, Any, Final

from engine.runtime import clock as clock_mod
from engine.runtime import triggers as triggers_mod
from engine.runtime.commands import MessageArrived, OpenInbox
from engine.runtime.errors import AuthorRefusal
from engine.runtime.inbox import build_delivery
from engine.runtime.stage import flush_stage
from engine.runtime.values import Unsaveable, freeze
from engine.script.inbox import (TRIGGER_KIND, ContactDecl, OpenStep, SendStep, collect,
                                 message_lines, message_problem)
from engine.script.inbox import uses_send as _uses_send
from engine.script.triggers import Trigger

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.runtime.triggers import Fired

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
    delivery = build_delivery(stmt.sid, codex.deliveries(), title, when, device,
                              message_lines(value, title), sender=stmt.contact,
                              message=stmt.message)
    if delivery is None:                                  # checked: never empty
        return
    codex.add_delivery(delivery)
    interp._hold(MessageArrived(stmt.contact, title, device,
                                contact.image if contact is not None else None,
                                stmt.contact))


def run_send(interp: "Interpreter", stmt: SendStep) -> "Step":
    """``send <message> from <contact>``: arm the line's trigger, and deliver when it fits
    (module docstring). Not a checkpoint."""
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
    """The kind's ``on_fire``: an armed message whose moment came (round 3's delays)."""
    payload = fired.trigger.payload
    if isinstance(payload, SendStep):
        deliver(interp, payload)


def _collect(program: Any) -> "list[Trigger]":
    return list(collect(program))


def run_open(interp: "Interpreter", stmt: OpenStep) -> "Step":
    """``open inbox`` / ``open <look>``: the stage flushed, then an ``OpenInbox`` wait."""
    flush_stage(interp)
    return interp.begin_wait(stmt, seconds=None, for_stage=False,
                             make=partial(OpenInbox, look=stmt.look))


def uses_send(program: Any) -> bool:
    """Whether the script has a ``send`` line (the quick menu's Inbox button)."""
    return _uses_send(program)


triggers_mod.register_kind(TRIGGER_KIND, collect=_collect, on_fire=_on_fire)


__all__ = ["deliver", "run_open", "run_send", "uses_send"]

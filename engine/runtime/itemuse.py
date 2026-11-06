"""Using an item: the Use button and the hotbar at run time (F64 round 2, specs/F64-items/SPEC.md
"Round 2: Use and the hotbar"; proposal I-12 "Use button", I-13 "Hotbar").

Why this module exists: ``lock item tea "Jasmine Tea" use drink_tea`` gives an item a scene to
run when the player uses it, from the bag's Use button or a hotbar slot. A scene that could
start at any moment would break menus, minigames and timed waits, so a use is **a call between
lines**, and only where the rule below allows it. The presentation only asks (``UseItem``);
this module decides and runs it, so saves and going back stay exact.

**The rule** (``why_not``). A use starts only while the story waits for a click at a line
(a ``Say`` checkpoint: ADV or NVL), and never

- at a menu (F07, F64's ``present:`` included), a minigame (F23), a pause or another timed
  wait (F09 ``pause``, F18's chapter card, F30's fake crash), during a forward re-run (F14),
- inside another use's scene (uses don't nest), or past the call depth limit;

and only for an item that is held and has a ``use`` scene. The app adds one rule of its own
(``app/hotbar.py``): the line must be shown in full (not typing, not stopped at a ``{w}``).
An author who wants an item to work only in some places checks in the scene itself, e.g.
``if not in_cellar:`` / ``"Not here."`` / ``return``.

**The call.** The waiting line counts as read (as a click: its voice ends, F12's seen mark),
the line itself goes on the call stack as the return point, and the story enters the scene;
its ``return`` (or its end) comes back to the line *after* the one the player was reading.
So a use is one more step of the story: the checkpoints inside the scene are ordinary steps,
going back from the scene's first line lands on the line where the item was used, and the
item counts, variables and meters it changed are saved with each step. A save made inside the
scene holds the line in its call stack, its sid marked with ``USE_FRAME`` (``frame_sid``), so
a restore accepts a line there only as a use's (``find_frame``; any other call stack entry
must still be a ``Call``, as F03's position checks say). Using
an item takes nothing by itself: the scene does that with ``lock item tea``.

**Going forward again** (F14). The timeline remembers which step a use led to
(``Timeline.note_use``); a forward re-run at that line uses the same item again instead of
clicking (``forward_use``), so the remembered future replays exactly.

``HotbarShow``'s executor (``run_hotbar_show``) sets ``Codex.set_bar``; the app's corner
follows it (``app/hotbar.py``).

Layering as ``points.py``: below the interpreter, importing it only inside functions.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.core.logsetup import get_logger
from engine.runtime import limits
from engine.runtime.commands import Event
from engine.script import nodes
from engine.script.codex import WORD_ITEM

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.script.hotbar import HotbarShow

_log = get_logger("runtime")

# ``why_not``'s reasons.
NO_ITEM: Final = "item"        # not a declared item with a use scene (or the scene is gone)
NOT_HELD: Final = "held"       # the player doesn't hold it
NOT_NOW: Final = "now"         # the story isn't waiting at a line (the rule)
USE_FRAME: Final = "!use"      # a saved call stack entry that is a use's line (no sid has !)


@dataclass(frozen=True, slots=True)
class UseItem(Event):
    """The player used item ``name`` (the bag's Use button, a hotbar slot) while reading line
    ``sid``. Ignored unless that line is still the waiting one and ``why_not`` allows it."""

    name: str
    sid: str


def frame_sid(entry: nodes.Statement) -> str:
    """A call stack entry's saved sid: a ``Call``'s own, a use's line's marked."""
    return entry.sid + USE_FRAME if type(entry) is nodes.Say else entry.sid


def is_frame(sid: str) -> bool:
    return sid.endswith(USE_FRAME)


def find_frame(interp: "Interpreter", sid: str, hint: object,
               use_hints: bool) -> nodes.Say | None:
    """The line a saved use frame names (its sid, else with ``use_hints`` its location), or
    None when that is no line now. Saved data only selects existing lines."""
    program = interp.program
    stmt = program.get(sid[:-len(USE_FRAME)])
    if stmt is None and use_hints and type(hint) is tuple and len(hint) == 2:
        stmt = program.at(hint[0], hint[1])
    return stmt if type(stmt) is nodes.Say else None


def scene_of(interp: "Interpreter", name: object) -> str | None:
    """The scene item ``name`` runs when used, or None (no such item, no ``use``, or a scene
    that is no label now)."""
    entry = interp.codex.index.get(name)
    if entry is None or entry.kind != WORD_ITEM:
        return None
    scene = getattr(entry, "use", None)
    return scene if scene is not None and scene in interp.program.labels else None


def in_use(interp: "Interpreter") -> bool:
    """A use's scene is running: a line is on the call stack (only a use puts one there)."""
    return any(type(entry) is nodes.Say for entry in interp.call_stack)


def story_allows(interp: "Interpreter") -> bool:
    """The rule's story half (module docstring): waiting for a click at a line, no wait, no
    forward re-run, not inside a use, room on the call stack."""
    from engine.runtime.interpreter import Status       # below the interpreter
    return (interp.status is Status.WAITING and interp.waiting_for is None
            and type(interp.current) is nodes.Say and interp.timeline.replay == 0
            and not interp.timeline.replaying and interp.minigame_wait is None
            and len(interp.call_stack) < limits.CALL_DEPTH_MAX and not in_use(interp))


def why_not(interp: "Interpreter", name: object) -> str | None:
    """None when item ``name`` can be used now; else ``NO_ITEM``, ``NOT_HELD`` or
    ``NOT_NOW``, in that order."""
    if scene_of(interp, name) is None:
        return NO_ITEM
    if not interp.codex.has(name):
        return NOT_HELD
    return None if story_allows(interp) else NOT_NOW


def usable_items(interp: "Interpreter") -> tuple[str, ...]:
    """The held items with a use scene, in bag order (the hotbar's automatic slots)."""
    return tuple(name for name in interp.codex.items() if scene_of(interp, name) is not None)


def _start(interp: "Interpreter", say: nodes.Say, name: str) -> None:
    """The call (module docstring): the line read, the line as the return point, the
    scene entered; the timeline told which step this use leads to."""
    from engine.runtime import audio as audio_mod
    from engine.runtime.interpreter import Status
    from engine.runtime.errors import StoryError
    scene = scene_of(interp, name)
    assert scene is not None
    audio_mod.end_voice(interp, say)
    interp.persistent.mark_seen(say.sid)
    interp.status = Status.RUNNING
    interp.timeline.note_use(name)
    interp.call_stack.append(say)                           # type: ignore[arg-type]
    _log.debug("Using item %s: calling %s.", name, scene)
    try:
        interp._enter(scene)
    except StoryError as e:                                 # E45 (only under a patched limit)
        interp._fail(e)


def on_use_item(interp: "Interpreter", event: UseItem) -> None:
    """``UseItem``: start the use when the line is still the waiting one and the rule allows
    it; else nothing (stale, or refused: the app already told the player)."""
    current = interp.current
    if type(current) is not nodes.Say or event.sid != current.sid:
        return
    reason = why_not(interp, event.name)
    if reason is not None:
        _log.debug("Use of %r refused (%s).", event.name, reason)
        return
    _start(interp, current, event.name)


def forward_use(interp: "Interpreter", say: nodes.Say) -> bool:
    """F14's forward re-run at ``say``: when the remembered next step came from using an
    item here, use it again (True); else False (the re-run clicks)."""
    name = interp.timeline.remembered_use()
    if name is None or scene_of(interp, name) is None or not interp.codex.has(name):
        return False
    _start(interp, say, name)
    return True


def run_hotbar_show(interp: "Interpreter", stmt: "HotbarShow") -> "Step":
    """``show hotbar`` / ``hide hotbar``: story state, saved with the items. Not a
    checkpoint."""
    from engine.runtime.interpreter import Step
    interp.codex.set_bar(stmt.shown)
    return Step.CONTINUE


__all__ = ["NOT_HELD", "NOT_NOW", "NO_ITEM", "USE_FRAME", "UseItem", "find_frame",
           "forward_use", "frame_sid", "in_use", "is_frame",
           "on_use_item", "run_hotbar_show", "scene_of", "story_allows", "usable_items",
           "why_not"]

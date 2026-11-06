"""Menus at run time (F07 ``04-technical.md`` §4, §5.2, §7.2–7.5).

Why this module exists: a menu is one checkpoint (C1). Reaching it checks every choice's
condition once, top to bottom, under the guard; resolves the shown texts; and takes the
menu's checkpoint with its question's ``Say`` attached, so the snapshot holds exactly what
the player sees and a restore never re-evaluates a condition (``dice`` never re-rolls). A
``Choose`` with a pickable key records the pick in ``GameState.choices`` and runs the
choice's block. ``choices.picks`` is a shared contract (F07 ``07`` §3): readers key on
``(menu, choice)``; it is bounded, rolled back with the state, and never story state. An
accepted ``Choose`` also marks F12's persistent records (``mark_chosen``, and ``mark_seen``
of the menu's sid when it has a question), which last across playthroughs, and adds the
pick to F13's history (``interp.history``) after its question's line, and in NVL starts a
new page (F17's ``on_pick``, right after it).

F59 (its SPEC §3): a checked choice's ``ShownChoice.check`` is its badge, from the meter's
value as the menu shows (and as it is restored). Once picked (its key in ``picks`` for this
menu) it is left out or locked like a false condition: one try per playthrough. ``run_check``
is ``CheckRoll``'s executor: two dice from the story's ``dice`` generator right after the
pick, so a load or going back and picking again rolls the same.

F20 (its ``04`` §7.6, 07 §3.3, I-2): a jump restores at a menu with ``fresh_waiting``, which
checks the conditions again through the same loop as ``run_menu`` (``_evaluate``); F11 loads
and F14's landings keep presenting the saved ``waiting``.

Saved (04 §4, §10): ``ChoiceState.to_json``/``from_json`` are ``GameState``'s ``choices``
key, always written and optional on read (absent: ``EMPTY_CHOICES``). ``from_json`` checks
shapes only; restore matches the keys against the ``Program`` (``check_position``).

Layering (as ``stage.py`` and ``audio.py``): ``state.py`` holds a ``ChoiceState``, so this
module sits below the interpreter and never imports it at load time; ``interpreter.py``
registers ``run_menu``/``present_menu``/``check_position`` and ``on_choose``. Pure
(TR-F03-05): no file, clock, or randomness. Log area ``choice`` (07 I-11).
"""

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from engine.core.logsetup import get_logger
from engine.runtime import audio as audio_mod
from engine.runtime import nvl as nvl_mod
from engine.runtime import stage as stage_mod
from engine.runtime.commands import (Choose, Command, EndVoice, ShowMenu, ShownChoice,
                                     TaggedText)
from engine.runtime.commands import Say as SayCommand
from engine.runtime.errors import StoryError, where
from engine.runtime.limits import POSITION_MAX_CHARS
from engine.runtime.text import resolve_tagged
from engine.script.choicecheck import CheckRoll, badge, passes
from engine.script.menu import Choice, Menu
from engine.script.messages import format_message
from engine.script.minigame import Minigame
from engine.script.nodes import Say as SayNode

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.runtime.state import GameState

PICKS_MAX: Final = 10_000              # TR-F07-08: past this the oldest pick drops
PICK_TEXT_MAX: Final = 1_000           # Pick.text, "…"-cut
PICK_QUESTION_MAX: Final = 2_000       # Pick.question, "…"-cut
ELLIPSIS: Final = "…"

_log = get_logger("choice")


# --- The state (04 §4) ------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Pick:
    """One pick, in story order: the menu's sid, the choice's key, and the texts as shown
    (plain: styles dropped, ``{var}`` values baked in, cut with "…")."""

    menu: str
    choice: str
    text: str
    question: str | None


@dataclass(frozen=True, slots=True)
class MenuWait:
    """The menu a checkpoint waits at: its pickable keys (1–6) and locked keys (0–5) in
    script order, and ``kept``, the sid of the line kept under a question-less menu (a
    ``Say``, or a ``Menu`` with a question; None: the textbox is hidden)."""

    pickable: tuple[str, ...]
    locked: tuple[str, ...]
    kept: str | None


@dataclass(frozen=True, slots=True)
class ChoiceState:
    """``GameState.choices``. ``waiting`` is set only in a checkpoint at a ``Menu``. A new
    ``picks`` tuple is built only on a pick; checkpoints between picks share it."""

    picks: tuple[Pick, ...] = ()
    waiting: MenuWait | None = None

    def to_json(self) -> dict[str, object]:
        """``{"picks": [{"menu", "choice", "text", "question"}], "waiting": null |
        {"pickable", "locked", "kept"}}``, fresh plain values (always written, 04 §4)."""
        waiting = self.waiting
        return {
            "picks": [{"menu": p.menu, "choice": p.choice, "text": p.text,
                       "question": p.question} for p in self.picks],
            "waiting": None if waiting is None else {
                "pickable": list(waiting.pickable), "locked": list(waiting.locked),
                "kept": waiting.kept},
        }

    @staticmethod
    def from_json(obj: object) -> "ChoiceState":
        """Validate an untrusted saved ``choices`` value (04 §8 items 3, 4): exact key sets
        and types, lengths, sid and key shapes, ``pickable`` 1–6 unique keys, ``locked``
        0–5 unique keys disjoint from it. Raises ``StateInvalid("choices")`` only; its text
        never holds any part of the input. Keys are matched against the ``Program`` only at
        restore (step 2), never here."""
        try:
            return _choices_from_json(obj)
        except _Invalid:
            pass
        except Exception:                   # defensive: the contract is StateInvalid only
            pass
        from engine.runtime.state import StateInvalid   # state.py imports this module
        raise StateInvalid("choices") from None

    def save_problem(self) -> str | None:
        """F11 C11 for this field: ``choices`` if ``from_json`` would refuse this value's
        JSON (only a hand-built state: ``on_choose`` and ``run_menu`` keep every limit),
        ``lone_surrogate`` if a shown text (``{var}`` values baked in) wouldn't read back
        equal; else None."""
        try:
            back = _choices_from_json(self.to_json())
        except Exception:                   # _Invalid, or a hand-built value of a wrong type
            return "choices"
        if back != self:
            return "choices"
        texts = [p.text for p in self.picks]
        texts += [p.question for p in self.picks if p.question is not None]
        joined = " ".join(texts)            # a space never forms a pair between two texts
        if not joined.isascii() and _SURROGATE_PAIR.search(joined):
            return "lone_surrogate"
        return None


EMPTY_CHOICES: Final = ChoiceState()


# --- The JSON form (04 §4, §8 items 3–4) ------------------------------------------------------

_CHOICES_KEYS: Final = frozenset(("picks", "waiting"))
_PICK_KEYS: Final = frozenset(("menu", "choice", "text", "question"))
_WAIT_KEYS: Final = frozenset(("pickable", "locked", "kept"))
# ADR-0006: a statement's sid is "<label>/<12 hex>" or "<label>/<12 hex>~<n>"; a choice's key
# (Addendum 1) is "<12 hex>" or "<12 hex>~<n>". Every saved sid and key has this shape.
_SID_SHAPE: Final = re.compile(r"[^/]+/[0-9a-f]{12}(?:~[1-9][0-9]{0,8})?")
_KEY_SHAPE: Final = re.compile(r"[0-9a-f]{12}(?:~[1-9][0-9]{0,8})?")
_SURROGATE_PAIR: Final = re.compile(r"[\ud800-\udbff][\udc00-\udfff]")
MENU_CHOICES_MAX: Final = 6             # E173: a menu has at most six choices


class _Invalid(Exception):
    pass


def sid_ok(value: object) -> bool:
    """Whether a saved sid is well formed: F03 §9.1's position rule (``str``, at most
    ``POSITION_MAX_CHARS``) and ADR-0006's shape (also F13's history entries)."""
    return (type(value) is str and len(value) <= POSITION_MAX_CHARS
            and _SID_SHAPE.fullmatch(value) is not None)


def _sid(value: object) -> str:
    """A saved sid (``sid_ok``)."""
    if not sid_ok(value):
        raise _Invalid
    return value  # type: ignore[return-value]


def _keys(value: object, low: int, high: int) -> tuple[str, ...]:
    """A saved list of ``low``–``high`` distinct choice keys."""
    if type(value) is not list or not low <= len(value) <= high:
        raise _Invalid
    for key in value:
        if type(key) is not str or not _KEY_SHAPE.fullmatch(key):
            raise _Invalid
    if len(set(value)) != len(value):
        raise _Invalid
    return tuple(value)


def _choices_from_json(obj: object) -> ChoiceState:
    if type(obj) is not dict or obj.keys() != _CHOICES_KEYS:
        raise _Invalid
    raw_picks, raw_wait = obj["picks"], obj["waiting"]
    if type(raw_picks) is not list or len(raw_picks) > PICKS_MAX:
        raise _Invalid
    for entry in raw_picks:                 # shapes first, before any value is read
        if type(entry) is not dict or entry.keys() != _PICK_KEYS:
            raise _Invalid
    picks: list[Pick] = []
    for entry in raw_picks:
        choice, text, question = entry["choice"], entry["text"], entry["question"]
        if type(choice) is not str or not _KEY_SHAPE.fullmatch(choice):
            raise _Invalid
        if type(text) is not str or len(text) > PICK_TEXT_MAX:
            raise _Invalid
        if question is not None and (type(question) is not str
                                     or len(question) > PICK_QUESTION_MAX):
            raise _Invalid
        picks.append(Pick(_sid(entry["menu"]), choice, text, question))
    waiting = None
    if raw_wait is not None:
        if type(raw_wait) is not dict or raw_wait.keys() != _WAIT_KEYS:
            raise _Invalid
        pickable = _keys(raw_wait["pickable"], 1, MENU_CHOICES_MAX)
        locked = _keys(raw_wait["locked"], 0, MENU_CHOICES_MAX - 1)
        if len(pickable) + len(locked) > MENU_CHOICES_MAX or not set(pickable).isdisjoint(locked):
            raise _Invalid
        kept = raw_wait["kept"]
        waiting = MenuWait(pickable, locked, None if kept is None else _sid(kept))
    return ChoiceState(tuple(picks), waiting)


def plain_text(body: TaggedText) -> str:
    """A resolved body's text, styles dropped (``TaggedText.plain``)."""
    return "".join(span.text for span in body.plain())


def cut(text: str, limit: int) -> str:
    """``text`` at most ``limit`` characters: longer ends in "…"."""
    return text if len(text) <= limit else text[:limit - 1] + ELLIPSIS


# --- Reaching a menu (04 §7.3) --------------------------------------------------------------------

def run_menu(interp: "Interpreter", stmt: Menu) -> "Step":
    """Steps 1–8 of 04 §7.3: conditions once (E178 when nothing is pickable), the
    question's ``Say`` (F04 words, F05 body, F08 voice), the shown bodies, then the menu's
    one checkpoint. No author code runs after the conditions, so the snapshot holds the
    shown values."""
    from engine.runtime.interpreter import Step, say_command  # below the interpreter

    pickable, locked = _evaluate(interp, stmt, interp.choices.picks)  # 1.-2.
    question = stmt.question
    attached: tuple[Command, ...] = ()
    say: SayCommand | None = None
    if question is not None:                                        # 3.
        say = say_command(interp, question)
        if question.speaker is not None:
            stage_mod.apply_dialogue_words(interp, question, interp.G[question.speaker])
        attached = audio_mod.voice_attached(say) + (say,)
    shown = _shown(interp, stmt, pickable, locked, restoring=False)  # 4.
    kept = interp.kept_line
    line = "question" if question is not None else ("kept" if kept is not None else "none")
    cmd = ShowMenu(stmt.sid, shown, line, seconds=stmt.time,        # 5. F51
                   timeout=_timeout_key(stmt))
    interp.choices = replace(interp.choices, waiting=MenuWait(      # 6.
        tuple(c.key for c in pickable), tuple(c.key for c in locked),
        None if question is not None else kept))
    interp.menu_open = (cmd, plain_text(say.body) if say is not None else None)
    interp.take_checkpoint(stmt, cmd, attached=attached)            # 7.
    if question is not None:                                        # 8.
        interp.kept_line = stmt.sid
    return Step.WAIT


def _timeout_key(stmt: Menu) -> str | None:
    """F51 (04 §7.2): the key of the choice time running out picks, or None when the menu
    has no time limit. That choice has no ``if`` (E370), so it is always shown and
    pickable."""
    if stmt.time is None:
        return None
    return next((choice.key for choice in stmt.choices if choice.timeout), None)


def _evaluate(interp: "Interpreter", stmt: Menu,
              picks: tuple[Pick, ...]) -> tuple[list[Choice], list[Choice]]:
    """Steps 1–2 of 04 §7.3, the one condition loop (F20 07 I-2: ``run_menu`` and
    ``fresh_waiting``): each condition once, top to bottom, under the guard; a false one's
    choice is locked with ``show_locked``, else left out. Nothing pickable is E178 at the
    menu. Returns (pickable, locked) in script order; author exceptions propagate. F59: a
    checked choice already in ``picks`` for this menu counts as a false condition."""
    pickable: list[Choice] = []
    locked: list[Choice] = []
    tried = _tried(stmt, picks) if any(c.check is not None for c in stmt.choices) else ()
    for choice in stmt.choices:
        if choice.check is not None and choice.key in tried:
            if interp.show_locked:
                locked.append(choice)
            continue
        condition = choice.condition
        if condition is not None:
            interp.running.set(stmt.file.ref, condition)
            if not interp._test(condition.code):
                if interp.show_locked:
                    locked.append(choice)
                continue
        pickable.append(choice)
    if not pickable:
        raise StoryError(format_message("E178", (bool(locked),)), code="E178", **where(stmt))
    return pickable, locked


def _tried(stmt: Menu, picks: tuple[Pick, ...]) -> frozenset[str]:
    """F59: the keys picked at this menu so far in this playthrough."""
    sid = stmt.sid
    return frozenset(pick.choice for pick in picks if pick.menu == sid)


def _badge(interp: "Interpreter", choice: Choice) -> str | None:
    """F59: a checked choice's badge from the meter's value now (None: not checked, or the
    meter is gone after a reload)."""
    check = choice.check
    if check is None:
        return None
    try:
        value = interp.points.get(check.meter)
    except KeyError:
        return None
    return badge(check.meter, value, check.difficulty)


def run_check(interp: "Interpreter", stmt: CheckRoll) -> "Step":
    """F59: roll two dice from the story's generator, add the meter, and enter the success
    or the failure lines. Dev runs log the roll."""
    from engine.runtime.interpreter import Step  # below the interpreter

    check = stmt.check
    value = interp.points.get(check.meter)
    core = interp.core
    a = 1 + core.below(6)
    b = 1 + core.below(6)
    ok = passes(a, b, value, check.difficulty)
    if interp.dev:
        _log.info("Check %s %s at %s, line %s: rolled %s + %s, + %s = %s: %s.", check.meter,
                  check.written, stmt.file.ref, check.line, a, b, value, a + b + value,
                  "success" if ok else "failure")
    block = stmt.branches[0 if ok else 1].block
    if block:
        interp.current = block[0]
        return Step.JUMPED
    return Step.CONTINUE


def _shown(interp: "Interpreter", stmt: Menu, pickable: list[Choice], locked: list[Choice],
           *, restoring: bool) -> tuple[ShownChoice, ...]:
    """The shown choices in script order, bodies resolved (E170/E171 at the choice's
    line; restoring, W46 instead)."""
    unlocked = {id(c) for c in pickable}
    shut = {id(c) for c in locked}
    out = []
    for choice in stmt.choices:
        if id(choice) in unlocked or id(choice) in shut:
            body = resolve_tagged(interp, choice.body, restoring=restoring, owner=stmt,
                                  line=choice.line)
            out.append(ShownChoice(choice.key, body, id(choice) in shut,
                                   _badge(interp, choice)))
    return tuple(out)


# --- A pick (04 §7.4) ----------------------------------------------------------------------------------

def on_choose(interp: "Interpreter", event: Choose) -> None:
    """A ``Choose`` for the waiting menu and one of its pickable keys records the pick and
    runs the choice's block; anything else is ignored with one DEBUG record (TR-F07-02:
    the interpreter and ``checkpoint()`` stay as they were)."""
    from engine.runtime.interpreter import Status  # below the interpreter

    current = interp.current
    waiting = interp.choices.waiting
    if (interp.status is not Status.WAITING or type(current) is not Menu
            or type(event.sid) is not str or event.sid != current.sid or waiting is None):
        _log.debug("Choose ignored: no menu %s is waiting.", _shown_sid(event.sid))
        return
    key = event.choice
    if type(key) is not str or key not in waiting.pickable:
        _log.debug("Choose ignored: the menu waiting has no pickable choice %s.",
                   _shown_sid(key))
        return
    choice = next(c for c in current.choices if c.key == key)
    cmd, question = interp.menu_open if interp.menu_open is not None else (None, None)
    text = ""
    if cmd is not None:
        text = next((plain_text(s.body) for s in cmd.choices if s.key == key), "")
    pick = Pick(current.sid, key, cut(text, PICK_TEXT_MAX),
                None if question is None else cut(question, PICK_QUESTION_MAX))
    picks = interp.choices.picks + (pick,)
    if len(picks) > PICKS_MAX:
        picks = picks[-PICKS_MAX:]
        if not interp._picks_capped:                    # 07 I-8: once per Interpreter
            interp._picks_capped = True
            _log.warning("The record of picks holds %s entries, so the oldest are dropped "
                         "from now on.", f"{PICKS_MAX:,}")
    interp.choices = ChoiceState(picks, None)
    interp.history = interp.history.add_pick(pick)      # F13: after the question's entry
    nvl_mod.on_pick(interp)                             # F17 (04 §7.1): a new page in NVL
    interp.menu_open = None
    store = interp.persistent                           # F12 (04 §7.3): the choice mark,
    store.mark_chosen(current.sid, key)                 # and the question as a seen line
    if current.question is not None:
        store.mark_seen(current.sid)
    if current.question is not None and current.question.voice is not None:
        interp._hold(EndVoice(current.sid))             # F08: as an accepted Advance
    interp.status = Status.RUNNING
    if choice.block:
        interp.current = choice.block[0]
    else:                                               # never from a load (E12)
        interp._next_after(current)


def _shown_sid(value: object) -> str:
    """A received value for a DEBUG record: its type only unless it is a short string
    (an event can come from anywhere)."""
    if type(value) is str and len(value) <= 64:
        return f'"{value}"'
    return f"of type {type(value).__name__}"


# --- Restore (04 §7.5) ------------------------------------------------------------------------------------

def _clean(stmt: Menu, waiting: MenuWait) -> MenuWait:
    """``waiting`` with the keys the menu no longer has dropped, in its script order
    (07 I-6: ``picks`` is never cleaned)."""
    pickable = set(waiting.pickable)
    locked = set(waiting.locked)
    keys = [c.key for c in stmt.choices]
    return MenuWait(tuple(k for k in keys if k in pickable),
                    tuple(k for k in keys if k in locked), waiting.kept)


def check_position(interp: "Interpreter", stmt: Menu, state: "GameState") -> bool:
    """Restore step 2 for a ``Menu``: the state waits at a menu and at least one of its
    pickable keys names a current choice (TR-F07-06). Changes nothing, runs no author
    code."""
    choices = getattr(state, "choices", None)
    waiting = getattr(choices, "waiting", None)
    if type(waiting) is not MenuWait:
        return False
    return bool(_clean(stmt, waiting).pickable)


def restored_choices(stmt: object, state: "GameState") -> ChoiceState:
    """Restore step 6: the saved choices at a menu (keys that vanished dropped), else with
    ``waiting`` None."""
    choices = state.choices
    if type(stmt) is Menu and choices.waiting is not None:
        return ChoiceState(choices.picks, _clean(stmt, choices.waiting))
    return choices if choices.waiting is None else ChoiceState(choices.picks, None)


def restored_kept_line(interp: "Interpreter", stmt: object, choices: ChoiceState) -> str | None:
    """04 §7.2's restore row: a ``Say``'s sid; a ``Menu``'s own sid with a question, else
    its ``waiting.kept``. F23 (07 I-7(b)): None at a ``Minigame``, which keeps no line (the
    host clears the textbox)."""
    if type(stmt) is Minigame:
        return None
    if type(stmt) is Menu:
        if stmt.question is not None:
            return stmt.sid
        waiting = choices.waiting
        return waiting.kept if waiting is not None else None
    return getattr(stmt, "sid", None)


def fresh_waiting(interp: "Interpreter", stmt: Menu, state: "GameState") -> MenuWait:
    """F20's jump (its ``04`` §7.6 step 3, 07 §3.3, I-2): the menu's ``waiting`` built anew
    from the restored values (``restore(..., fresh_menu=True)`` step 5, after the defaults):
    the conditions as ``run_menu`` checks them (``_evaluate``: E178, or an author exception,
    propagates), and the saved ``kept`` only for a question-less menu whose ``kept`` names a
    ``Say`` or a ``Menu`` with a question (else None, never presented). Sets no field."""
    pickable, locked = _evaluate(interp, stmt, state.choices.picks)
    kept: str | None = None
    saved = getattr(state.choices, "waiting", None)
    if stmt.question is None and type(saved) is MenuWait and saved.kept is not None:
        line = interp.program.get(saved.kept)
        if isinstance(line, SayNode) or (type(line) is Menu and line.question is not None):
            kept = saved.kept
    return MenuWait(tuple(c.key for c in pickable), tuple(c.key for c in locked), kept)


def present_menu(interp: "Interpreter", stmt: Menu, state: "GameState") -> ShowMenu:
    """Restore step 7: the saved shown choices in current script order, conditions not
    evaluated, bodies from the restored values (W46, never an error). The question (and
    its voice), or the kept line (never voiced), is held through
    ``interp._restore_attached``. Changes no story state: the restore commits it."""
    from engine.runtime.interpreter import say_command  # below the interpreter

    waiting = _clean(stmt, state.choices.waiting)  # type: ignore[arg-type]
    by_key = {c.key: c for c in stmt.choices}
    pickable = [by_key[k] for k in waiting.pickable]
    locked = [by_key[k] for k in waiting.locked]
    shown = _shown(interp, stmt, pickable, locked, restoring=True)
    attached: tuple[Command, ...] = ()
    question: str | None = None
    if stmt.question is not None:
        say = say_command(interp, stmt.question, restored=True)
        attached = audio_mod.voice_attached(say) + (say,)
        question = plain_text(say.body)
        line = "question"
    else:
        kept = interp.program.get(waiting.kept)
        if type(kept) is Menu and kept.question is not None:
            kept = kept.question
        if isinstance(kept, SayNode):
            say = say_command(interp, kept, restored=True)
            attached = (replace(say, voice=None),)
            line = "kept"
        else:
            line = "none"
    cmd = ShowMenu(stmt.sid, shown, line, restored=True,  # type: ignore[arg-type]
                   seconds=stmt.time, timeout=_timeout_key(stmt))     # F51: full time
    interp._restore_attached = attached
    interp._restore_menu_open = (cmd, question)
    return cmd


__all__ = ["ChoiceState", "ELLIPSIS", "EMPTY_CHOICES", "MENU_CHOICES_MAX", "MenuWait",
           "PICKS_MAX",
           "PICK_QUESTION_MAX", "PICK_TEXT_MAX", "Pick", "check_position", "cut",
           "fresh_waiting", "on_choose", "plain_text", "present_menu", "restored_choices",
           "restored_kept_line", "run_check", "run_menu", "sid_ok"]

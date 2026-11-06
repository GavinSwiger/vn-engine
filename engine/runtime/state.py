"""``GameState``: one checkpoint of the story, and its JSON form (F03 ``04-technical.md`` §4.2,
§9, §9.1; architecture.md "GameState" and "Persistence formats").

Why this module exists: everything that affects the story lives in one plain-data value
(invariants 1 and 2) that F11 saves, F14 keeps for rollback, and F39 rebuilds from.

**Read-only by contract.** A ``GameState`` is frozen and ``variables`` is a read-only
mapping, but the lists and dicts inside it are not copied on access. Never mutate them: a
consumer that needs a copy uses ``to_json()`` (which copies). ``restore`` copies out again.

**Format.** ``STATE_FORMAT`` stays 1 while every change is a new optional field with a
default. Each later feature adds one field here (F04 ``stage``, F08 ``audio``, ...): a
frozen dataclass with ``to_json``/``from_json``, a default for older states, one key in
``_OPTIONAL_KEYS``, and one line in ``to_json``/``from_json``. There is no registry. A
change that isn't additive bumps ``STATE_FORMAT`` and adds a migration here.
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from itertools import chain
from types import MappingProxyType
from typing import Final

from engine.core.constants import WINDOW_TITLE_MAX
from engine.runtime.audio import EMPTY_AUDIO, AudioState
from engine.runtime.chapters import EMPTY_CHAPTER, ChapterState
from engine.runtime.clock import EMPTY_CLOCK, ClockState, clock_json
from engine.runtime.flowchart import EMPTY_FLOW, FlowState
from engine.runtime.glitch import EMPTY_GLITCH, GlitchState
from engine.runtime.history import EMPTY_HISTORY, HistoryState
from engine.runtime.inbox import Delivery, deliveries_from_json, deliveries_json
from engine.runtime.limits import (CALL_DEPTH_MAX, HINT_MAX_PATH, INT_LIMIT,
                                   POSITION_MAX_CHARS, STATE_MAX_DEPTH, STATE_MAX_ITEMS,
                                   STATE_MAX_NAMES, STATE_NAME_MAX_CHARS)
from engine.runtime.menu import EMPTY_CHOICES, ChoiceState
from engine.runtime.minigame import EMPTY_MINIGAME, MinigameState
from engine.runtime.nvl import EMPTY_NVL, NvlState
from engine.runtime.points import EMPTY_POINTS, PointsState, saved_name_ok
from engine.runtime.rollback import ROLLBACK_ON, RollbackState
from engine.runtime.stage import EMPTY_STAGE, StageInvalid, StageState
from engine.runtime.triggers import EMPTY_TRIGGERS, TriggerState, triggers_json
from engine.runtime.ui import EMPTY_UI, UiState
from engine.runtime.values import (Unsaveable, Value, freeze_untrusted, new_item_budget,
                                   plain_copy, same_value)
from engine.script.identity import IDENTITY_SCHEME
from engine.script.words import (ENGINE_NAMES, PYTHON_KEYWORDS, STATEMENT_WORDS,
                                 STATEMENT_WORDS_F02)

STATE_FORMAT: Final = 1

Hint = tuple[str, tuple[int, ...]]          # ADR-0006 StmtLocation hint: (label, path)

_REQUIRED_KEYS: Final = frozenset(("format", "identity_scheme", "position", "call_stack",
                                   "variables", "dice"))
_OPTIONAL_KEYS: Final = frozenset(("stage", "audio", "choices", "history", "chapter",
                                   "points", "rollback", "nvl", "items", "minigame", "flow",
                                   "glitch", "window_title", "ui_style", "save_block",
                                   "load_block", "clock", "triggers"))
# later features: one key each (F04, F08, F07, F13, F18, F22, F14, F17, F21, F23, F20, F28,
# F30); F32's ``ui`` is three keys (its 04 §3, C6)
ITEMS_HELD_MAX: Final = 1_000               # F21: names in a saved ``items`` (declared + hidden)
ITEM_COUNT_SAVED_MAX: Final = 999_999       # F64: the most of one item a save may hold
# F03's engine names, frozen here (F22 07 I-9, F14 07 I-1): a name the engine reserves after a
# save was made never makes that save unreadable, so from_json never reads the live
# ``ENGINE_NAMES``. Restore step 3 drops a saved name that is reserved now.
_SAVED_ENGINE_NAMES: Final = frozenset(("Character", "dice", "module", "persistent", "engine",
                                        "narrator"))
# The statement words reserved after F02 (F14 07 I-1: ``rollback``). ``_valid_name`` never
# reads statement words, so a saved variable with one of these names loads; restore drops it.
_LATER_STATEMENT_WORDS: Final = STATEMENT_WORDS - STATEMENT_WORDS_F02
_SID_KEYS: Final = frozenset(("sid", "at"))
_DICE_HEX = re.compile(r"[0-9a-f]{16}")
# A lone high surrogate right before a lone low one: JSON reads the two back as one
# character. Any other lone surrogate round-trips as an escape.
_SURROGATE_PAIR = re.compile(r"[\ud800-\udbff][\udc00-\udfff]")
_SCALAR_TYPES: Final = frozenset((type(None), bool, int, float))
_VALUE_TYPES: Final = _SCALAR_TYPES | {str, list, dict}
# isinstance as a C callable for filter(); a frozen value has an exact type, so it is the
# type test (a subclass is refused before, by the kinds check).
_IS_STR, _IS_LIST, _IS_DICT = (str.__instancecheck__, list.__instancecheck__,
                               dict.__instancecheck__)


class StateInvalid(Exception):
    """A state that ``from_json`` refuses (§9.1). ``reason`` is a fixed word matching
    ``^[a-z_]{1,40}$``; neither it nor the text ever contains any part of the input.
    ``unknown_key`` is the one F11 shows as "made by a newer version"."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"the story state is not valid ({reason})")
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ItemsState:
    """``GameState.items`` (F21 ``04`` §4, §10): the held item names in the order obtained,
    declared and hidden ones (a name the script no longer declares as an item). Built only by
    ``runtime/codex.Codex`` and ``from_json``. JSON ``{"held": [name, …]}``.

    F64: ``counts`` holds how many of each held name (parallel to ``held``, each at least 1);
    ``()`` means one of each. JSON adds ``"counts": [n, …]`` only when some count isn't 1, so
    a save from before F64 (no ``counts``) loads as one of each held item.

    F64 round 2: ``bar`` is whether ``show hotbar`` put the hotbar on screen; JSON adds
    ``"bar": true`` only then, so older saves load with it hidden.

    F65: ``inbox`` holds the Inbox's deliveries (finished chats and, round 2, sent messages),
    oldest first (``runtime/inbox.py``); JSON adds ``"inbox": [...]`` only when there is one,
    so older saves load with an empty inbox."""

    held: tuple[str, ...] = ()
    counts: tuple[int, ...] = ()
    bar: bool = False
    inbox: "tuple[Delivery, ...]" = ()

    def count_of(self, index: int) -> int:
        return self.counts[index] if self.counts else 1

    def to_json(self) -> dict[str, Value]:
        out: dict[str, Value] = {"held": list(self.held)}
        if self.counts and any(n != 1 for n in self.counts):
            out["counts"] = list(self.counts)
        if self.bar:
            out["bar"] = True
        if self.inbox:
            out["inbox"] = deliveries_json(self.inbox)
        return out

    @staticmethod
    def from_json(obj: object) -> "ItemsState":
        """Validate untrusted ``obj``: exactly ``{"held": [...]}`` with at most
        ``ITEMS_HELD_MAX`` different names, each ``points.saved_name_ok`` (F22's saved-name
        check, shared: no live word set, F21 07 I-8). Anything else is
        ``StateInvalid("items")``, never echoing the input."""
        if type(obj) is not dict or not {"held"} <= obj.keys() <= {"held", "counts", "bar",
                                                                   "inbox"}:
            raise StateInvalid("items")
        held = obj["held"]
        if type(held) is not list or len(held) > ITEMS_HELD_MAX:
            raise StateInvalid("items")
        if not all(map(saved_name_ok, held)) or len(set(held)) != len(held):
            raise StateInvalid("items")
        counts: tuple[int, ...] = ()
        if "counts" in obj:                 # F64; absent (an older save): one of each
            found = obj["counts"]
            if type(found) is not list or len(found) != len(held) or not all(
                    type(n) is int and 1 <= n <= ITEM_COUNT_SAVED_MAX for n in found):
                raise StateInvalid("items")
            if any(n != 1 for n in found):
                counts = tuple(found)
        bar = obj.get("bar", False)         # F64 round 2: only ever written as true
        if bar is not True and "bar" in obj:
            raise StateInvalid("items")
        inbox: tuple[Delivery, ...] = ()
        if "inbox" in obj:                  # F65; absent (an older save): no threads
            try:
                inbox = deliveries_from_json(obj["inbox"])
            except Exception:
                raise StateInvalid("items") from None
        if not held and not bar and not inbox:
            return EMPTY_ITEMS
        return ItemsState(tuple(held), counts, bar, inbox)


EMPTY_ITEMS: Final = ItemsState()


@dataclass(frozen=True, slots=True, eq=False)
class GameState:
    """A checkpoint. Built only by ``take_checkpoint`` (from frozen copies) or by
    ``from_json`` (validated). Never mutated; restore copies out of it.

    Nested values in ``variables`` are **read-only by contract** (see the module docstring).
    Equality is field-wise, comparing values by value and exact type at every level.
    """

    position: str                           # sid of the waiting checkpoint statement
    position_at: Hint                       # hint, never trusted
    call_stack: tuple[tuple[str, Hint], ...]  # (Call sid, hint), outermost first
    variables: Mapping[str, Value]          # MappingProxyType over a private dict
    dice: int                               # PCG32 state, 0 <= dice < 2**64
    identity_scheme: int = IDENTITY_SCHEME   # ADR-0006; from_json keeps the saved value
    # Later features add one field each here, with a default.
    stage: StageState = EMPTY_STAGE         # F04 (04 §4.1, §9): EMPTY_STAGE before F04
    audio: AudioState = EMPTY_AUDIO         # F08 (04 §4, §10): silence before F08
    choices: ChoiceState = EMPTY_CHOICES    # F07 (04 §4, §10): no picks before F07
    history: HistoryState = EMPTY_HISTORY   # F13 (SPEC §5): no history before F13
    chapter: ChapterState = EMPTY_CHAPTER   # F18 (SPEC §5): no chapter before F18
    points: PointsState = EMPTY_POINTS      # F22 (SPEC §5): every meter at its start
    rollback: RollbackState = ROLLBACK_ON   # F14 (04 §4): rollback on before F14
    nvl: NvlState = EMPTY_NVL               # F17 (04 §4): ADV, empty page, before F17
    items: ItemsState = EMPTY_ITEMS         # F21 (04 §4): no items held before F21
    minigame: MinigameState = EMPTY_MINIGAME  # F23 (04 §3): no minigame waits before F23
    flow: FlowState = EMPTY_FLOW            # F20 (04 §4): no node reached before F20
    glitch: GlitchState = EMPTY_GLITCH      # F28 (04 §3): no lasting glitch before F28
    window_title: str | None = None         # F30 (04 §3): None is ``[game] title``
    ui: UiState = EMPTY_UI                  # F32 (04 §3): no style, nothing blocked
    clock: ClockState = EMPTY_CLOCK         # F63: the calendar's start (runtime/clock.py)
    triggers: TriggerState = EMPTY_TRIGGERS  # F65 trigger core: none armed or retired

    def __post_init__(self) -> None:
        if type(self.variables) is dict:    # a builder's private dict
            object.__setattr__(self, "variables", MappingProxyType(self.variables))

    def __eq__(self, other: object) -> bool:
        if type(other) is not GameState:
            return NotImplemented
        for field in fields(self):
            a = getattr(self, field.name)
            b = getattr(other, field.name)
            if field.name == "variables":
                if len(a) != len(b) or any(k not in b or not same_value(x, b[k])
                                           for k, x in a.items()):
                    return False
            elif a != b:
                return False
        return True

    __hash__ = None  # type: ignore[assignment]

    def to_json(self) -> dict[str, object]:
        """The ``format`` 1 JSON object (plain dicts and lists, fresh copies). Writers use
        ``json.dumps(..., ensure_ascii=True)``; ``dice`` is 16 lowercase hex digits."""
        return {
            "format": STATE_FORMAT,
            "identity_scheme": self.identity_scheme,
            "position": _sid_json(self.position, self.position_at),
            "call_stack": [_sid_json(sid, at) for sid, at in self.call_stack],
            "variables": {k: plain_copy(v) for k, v in self.variables.items()},
            "dice": f"{self.dice:016x}",
            "stage": self.stage.to_json(),                      # F04: always written
            "audio": self.audio.to_json(),                      # F08: always written
            "choices": self.choices.to_json(),                  # F07: always written
            "history": self.history.to_json(),                  # F13: always written
            "chapter": self.chapter.to_json(),                  # F18: always written
            "points": self.points.to_json(),                    # F22: always written
            "rollback": self.rollback.to_json(),                # F14: always written
            "nvl": self.nvl.to_json(),                          # F17: always written
            "items": self.items.to_json(),                      # F21: always written
            "minigame": self.minigame.to_json(),                # F23: always written
            "flow": self.flow.to_json(),                        # F20: always written
            "glitch": self.glitch.to_json(),                    # F28: always written
        } | _title_json(self.window_title) | self.ui.to_json() \
            | clock_json(self.clock) | triggers_json(self.triggers)   # F30, F32, F63, F65:
                                                                    # only when set

    def save_problem(self) -> str | None:
        """F11 C11: a reason word (``^[a-z_]{1,40}$``) if this state, written out and read
        back, would not come back equal, else None. That is what ``take_checkpoint`` allows
        but ``from_json`` refuses (§9.1): over ``STATE_MAX_NAMES`` variables
        (``too_many_names``), a name ``_valid_name`` refuses (``variable_name``), a sid
        or hint over its limit (``position``, ``call_stack``, ``call_stack_too_deep``,
        ``hint``), over ``STATE_MAX_ITEMS`` list and dict members (``too_many_items``).
        Also ``lone_surrogate``: a string holding a lone high surrogate right before a
        lone low one, since JSON reads ``"\\ud800\\udc00"`` back as one character.
        Any other lone surrogate round-trips as an escape and is saveable. A value
        ``freeze`` refuses (only in a hand-built state) is ``variable_value``.

        A later field whose ``from_json`` refuses something a checkpoint can hold adds that
        check here. ``stage`` needs none: its names come from the parsed script. ``audio``
        (F08) is ``AudioState.save_problem``: ``audio`` for what its ``from_json`` refuses
        (counts, lengths, types, a repeated loop file), ``lone_surrogate`` for a file.
        ``choices`` (F07) is ``ChoiceState.save_problem``: ``choices`` for what its
        ``from_json`` refuses, ``lone_surrogate`` for a pick's shown text. ``history``
        (F13) is ``HistoryState.save_problem``: ``history`` for what its ``from_json``
        refuses or doesn't read back equal (only a hand-built state: the writer cuts to the
        limits and records a lone surrogate as U+FFFD). ``chapter`` (F18) needs none: its
        name comes from the parsed script, which bounds it as ``from_json`` does (07 I-2).
        ``points`` (F22) needs none: declared names are bounded at load, hidden ones come from
        a validated save, values are clamped, and restore keeps at most 1,000 names.
        ``rollback`` (F14) needs none: it is one of two constants. ``nvl`` (F17) is
        ``NvlState.save_problem``: ``nvl`` for what its ``from_json`` refuses or doesn't read
        back equal (only a hand-built state: ``line_of`` keeps every limit),
        ``lone_surrogate`` for a recorded name or span text. ``items`` (F21) needs none:
        declared names are bounded at load, hidden ones come from a validated save, and
        ``Codex`` keeps at most ``ITEMS_HELD_MAX`` names. ``minigame`` (F23) is
        ``MinigameState.save_problem``: ``minigame`` for a shape its ``from_json`` refuses
        (only a hand-built state); its argument values join the variables' walk, so they
        count in the ``STATE_MAX_ITEMS`` total (04 §3). ``flow`` (F20) needs none: its keys
        are graph node keys and step 2c keeps at most ``FLOW_PATH_MAX`` (F20 07 §3.2).
        ``glitch`` (F28) needs none: its kinds and sizes come from the parsed script, its tags
        from the stage's, and ``GlitchState`` keeps one entry per key (04 §6.3).
        ``window_title`` (F30) needs none: it is a ``TitleEffect``'s text, bounded at load
        (a lone surrogate round-trips as an escape). ``ui`` (F32) is ``UiState.save_problem``:
        ``ui_style`` for a style name ``from_json`` refuses (only a load given no style names
        lets one through); its reasons are bounded at load.

        Changes nothing. The value walk goes one nesting level at a time with C-level
        passes, so its Python work is per level, not per value: about 6-40 ms at 600,000
        members on the development machine, by shape (many small containers cost most;
        ``tests/runtime/test_save_problem.py`` prints them)."""
        variables = self.variables
        if len(variables) > STATE_MAX_NAMES:
            return "too_many_names"
        stack = self.call_stack
        if len(stack) > CALL_DEPTH_MAX:
            return "call_stack_too_deep"
        problem = _position_problem(self.position, self.position_at, "position")
        if problem is not None:
            return problem
        for sid, at in stack:
            problem = _position_problem(sid, at, "call_stack")
            if problem is not None:
                return problem
        problem = self.audio.save_problem()                 # F08
        if problem is not None:
            return problem
        problem = self.choices.save_problem()               # F07
        if problem is not None:
            return problem
        problem = self.history.save_problem()               # F13
        if problem is not None:
            return problem
        problem = self.nvl.save_problem()                   # F17
        if problem is not None:
            return problem
        problem = self.minigame.save_problem()              # F23
        if problem is not None:
            return problem
        problem = self.ui.save_problem()                    # F32
        if problem is not None:
            return problem
        if not _names_valid(variables.keys()):
            return "variable_name"
        return _values_problem(list(variables.values()) + self.minigame.values())

    @staticmethod
    def from_json(obj: object) -> "GameState":
        """Validate untrusted ``obj`` (as ``json.loads`` gives it) and build a state that
        shares nothing with it. Raises ``StateInvalid`` only, never echoing the input.
        ``identity_scheme`` is checked by type; ``restore`` compares it and looks the
        positions up (§9.1)."""
        try:
            return _from_json(obj)
        except StateInvalid:
            raise
        except Exception:                   # defensive: the contract is StateInvalid only
            raise StateInvalid("malformed") from None


def reserved_since_save(name: str) -> bool:
    """Whether a saved variable's name was reserved after saves could hold it (F22 07 I-9):
    an engine name F03 didn't have (F09's ``Dissolve``…, F22's ``points``), or a statement
    word added after F02, in any case (F14 07 I-1: ``rollback``, ``Rollback``). ``from_json``
    never refuses such a name; restore step 3 drops it with the define-drop WARNING."""
    return ((name in ENGINE_NAMES and name not in _SAVED_ENGINE_NAMES)
            or name.lower() in _LATER_STATEMENT_WORDS)


def _title_json(title: str | None) -> dict[str, object]:
    """F30 (04 §1.1 Q1): ``{"window_title": title}`` only when a title is set, so a state
    with none writes exactly what it wrote before F30."""
    return {} if title is None else {"window_title": title}


def _sid_json(sid: str, at: Hint) -> dict[str, object]:
    return {"sid": sid, "at": [at[0], list(at[1])]}


def _from_json(obj: object) -> GameState:
    if type(obj) is not dict:
        raise StateInvalid("not_an_object")
    for key in obj:
        if type(key) is not str:
            raise StateInvalid("unknown_key")
    keys = obj.keys()
    if not keys <= (_REQUIRED_KEYS | _OPTIONAL_KEYS):
        raise StateInvalid("unknown_key")
    if not _REQUIRED_KEYS <= keys:
        raise StateInvalid("missing_key")

    fmt = obj["format"]
    if type(fmt) is not int or fmt != STATE_FORMAT:
        raise StateInvalid("format")
    scheme = obj["identity_scheme"]
    if type(scheme) is not int or abs(scheme) >= INT_LIMIT:
        raise StateInvalid("identity_scheme")

    position, position_at = _sid_entry(obj["position"], "position")
    stack = obj["call_stack"]
    if type(stack) is not list:
        raise StateInvalid("call_stack")
    if len(stack) > CALL_DEPTH_MAX:
        raise StateInvalid("call_stack_too_deep")
    call_stack = tuple(_sid_entry(entry, "call_stack") for entry in stack)

    budget = new_item_budget()              # shared by the variables and F23's arguments
    variables = _variables(obj["variables"], budget)

    dice = obj["dice"]
    if type(dice) is not str or len(dice) != 16 or not _DICE_HEX.fullmatch(dice):
        raise StateInvalid("dice")

    stage = EMPTY_STAGE                     # F04 §9: a state from before F04 has no stage
    if "stage" in obj:
        try:
            stage = StageState.from_json(obj["stage"])
        except StageInvalid:
            raise StateInvalid("stage") from None

    audio = EMPTY_AUDIO                     # F08 §10: a state from before F08 is silent
    if "audio" in obj:
        audio = AudioState.from_json(obj["audio"])          # StateInvalid("audio") only

    choices = EMPTY_CHOICES                 # F07 §10: a state from before F07 has no picks
    if "choices" in obj:
        choices = ChoiceState.from_json(obj["choices"])     # StateInvalid("choices") only

    history = EMPTY_HISTORY                 # F13: a state from before F13 has no history
    if "history" in obj:
        history = HistoryState.from_json(obj["history"])    # StateInvalid("history") only

    chapter = EMPTY_CHAPTER                 # F18: a state from before F18 has no chapter
    if "chapter" in obj:
        chapter = ChapterState.from_json(obj["chapter"])    # StateInvalid("chapter") only

    points = EMPTY_POINTS                   # F22: a state from before F22 has no meters
    if "points" in obj:
        points = PointsState.from_json(obj["points"])       # StateInvalid("points") only

    rollback = ROLLBACK_ON                  # F14: a state from before F14 has rollback on
    if "rollback" in obj:
        rollback = RollbackState.from_json(obj["rollback"])  # StateInvalid("rollback") only

    nvl = EMPTY_NVL                         # F17: a state from before F17 is in ADV
    if "nvl" in obj:
        nvl = NvlState.from_json(obj["nvl"])                # StateInvalid("nvl") only

    items = EMPTY_ITEMS                     # F21: a state from before F21 holds no items
    if "items" in obj:
        items = ItemsState.from_json(obj["items"])          # StateInvalid("items") only

    minigame = EMPTY_MINIGAME               # F23: a state from before F23 waits at none
    if "minigame" in obj:                   # StateInvalid("minigame") only
        minigame = MinigameState.from_json(obj["minigame"], budget)

    flow = EMPTY_FLOW                       # F20: a state from before F20 reached no node
    if "flow" in obj:
        flow = FlowState.from_json(obj["flow"])             # StateInvalid("flow") only

    glitch = EMPTY_GLITCH                   # F28: a state from before F28 has no glitch on
    if "glitch" in obj:                     # StateInvalid("glitch") only; jitter of a sprite
        glitch = GlitchState.from_json(obj["glitch"]).on_stage(stage)   # not on stage drops

    window_title = obj.get("window_title")  # F30: absent or null is None (the game title)
    if window_title is not None and (type(window_title) is not str
                                     or len(window_title) > WINDOW_TITLE_MAX):
        raise StateInvalid("window_title")      # the program-literal rule is restore's

    clock = EMPTY_CLOCK                     # F63: a state from before F63 is at the start
    if "clock" in obj:
        clock = ClockState.from_json(obj["clock"])          # StateInvalid("clock") only

    triggers = EMPTY_TRIGGERS               # F65: a state from before the trigger core
    if "triggers" in obj:                   # StateInvalid("triggers") only
        triggers = TriggerState.from_json(obj["triggers"])

    ui = UiState.from_json(obj)             # F32: absent keys are EMPTY_UI; StateInvalid with
                                            # the key's name only
    return GameState(position=position, position_at=position_at, call_stack=call_stack,
                     variables=MappingProxyType(variables), dice=int(dice, 16),
                     identity_scheme=scheme, stage=stage, audio=audio, choices=choices,
                     history=history, chapter=chapter, points=points, rollback=rollback,
                     nvl=nvl, items=items, minigame=minigame, flow=flow, glitch=glitch,
                     window_title=window_title, ui=ui, clock=clock, triggers=triggers)


def _sid_entry(entry: object, reason: str) -> tuple[str, Hint]:
    """``{"sid": str, "at": [label, [int, ...]]}`` -> ``(sid, (label, path))``."""
    if type(entry) is not dict or entry.keys() != _SID_KEYS:
        raise StateInvalid(reason)
    sid = entry["sid"]
    if type(sid) is not str or len(sid) > POSITION_MAX_CHARS:
        raise StateInvalid(reason)
    at = entry["at"]
    if type(at) is not list or len(at) != 2:
        raise StateInvalid("hint")
    label, path = at
    if type(label) is not str or len(label) > POSITION_MAX_CHARS:
        raise StateInvalid("hint")
    if type(path) is not list or len(path) > HINT_MAX_PATH:
        raise StateInvalid("hint")
    for step in path:
        if type(step) is not int or abs(step) >= INT_LIMIT:   # every int must dump again
            raise StateInvalid("hint")
    return sid, (label, tuple(path))


def _variables(raw: object, budget: list[int]) -> dict[str, Value]:
    if type(raw) is not dict:
        raise StateInvalid("variables")
    if len(raw) > STATE_MAX_NAMES:
        raise StateInvalid("too_many_names")
    out: dict[str, Value] = {}
    for name, value in raw.items():
        if not _valid_name(name):
            raise StateInvalid("variable_name")
        try:
            out[name] = freeze_untrusted(value, budget)
        except Unsaveable as error:
            reason = "too_many_items" if error.reason == "too_many" else "variable_value"
            raise StateInvalid(reason) from None
    return out


def _position_problem(sid: object, at: object, reason: str) -> str | None:
    """``save_problem`` for one ``(sid, hint)``: what ``_sid_entry`` would refuse, and a
    surrogate (a sid or label always comes from the program, so this is a guard)."""
    try:
        label, path = at                                # type: ignore[misc]
        if type(sid) is not str or len(sid) > POSITION_MAX_CHARS:
            return reason
        if (type(label) is not str or len(label) > POSITION_MAX_CHARS
                or len(path) > HINT_MAX_PATH
                or not all(type(step) is int and abs(step) < INT_LIMIT for step in path)):
            return "hint"
    except (TypeError, ValueError):
        return "hint"
    if _SURROGATE_PAIR.search(sid) or _SURROGATE_PAIR.search(label):
        return "lone_surrogate"
    return None


def _names_valid(names: Iterable[object]) -> bool:
    """``_valid_name`` for every name. ASCII names (NFKC by definition) take C-level passes
    over all of them at once; otherwise each name is checked on its own."""
    names = list(names)
    if not names:
        return True
    try:
        text = "\n".join(names)                         # type: ignore[arg-type]
    except TypeError:                                   # a name that isn't str
        return False
    if text.isascii():
        return (all(map(str.isidentifier, names))      # none empty or holding "\n"
                and not text.startswith("_") and "\n_" not in text
                and max(map(len, names)) <= STATE_NAME_MAX_CHARS
                and PYTHON_KEYWORDS.isdisjoint(names)
                and _SAVED_ENGINE_NAMES.isdisjoint(names))
    return all(map(_valid_name, names))


def _has_surrogate(texts: Iterable[str]) -> bool:
    """Whether any of ``texts`` (exact ``str``) holds a lone high surrogate right before a
    lone low one. Joined by a space, so two strings never form a pair between them."""
    text = " ".join(texts)
    return not text.isascii() and _SURROGATE_PAIR.search(text) is not None


def _values_problem(items: list) -> str | None:
    """``save_problem``'s walk of the variables' values, one nesting level at a time.
    Every pass over a level (kinds, strings, containers, member counts, dict keys) runs in
    C, so the Python work is per level and per kind, never per value. Containers past
    ``STATE_MAX_DEPTH`` (or a cycle), which ``freeze`` already refuses, are
    ``variable_value`` here only in a hand-built state."""
    members = 0
    depth = 0
    while items:
        kinds = set(map(type, items))
        if not kinds <= _VALUE_TYPES:
            return "variable_value"
        if kinds <= _SCALAR_TYPES:
            return None
        single = len(kinds) == 1
        if str in kinds and _has_surrogate(items if single else filter(_IS_STR, items)):
            return "lone_surrogate"
        lists: list = []
        dicts: list = []
        if list in kinds:
            lists = items if single else list(filter(_IS_LIST, items))
            members += sum(map(len, lists))
        if dict in kinds:
            dicts = items if single else list(filter(_IS_DICT, items))
            members += sum(map(len, dicts))
        if members > STATE_MAX_ITEMS:
            return "too_many_items"
        if depth >= STATE_MAX_DEPTH and (lists or dicts):
            return "variable_value"
        depth += 1
        if dicts:
            try:
                if _has_surrogate(set().union(*dicts)):     # the keys, each once
                    return "lone_surrogate"
            except TypeError:                           # a key that isn't str
                return "variable_value"
        if len(lists) == 1 and not dicts:
            items = lists[0]                            # one container: no copy
        else:
            items = list(chain(chain.from_iterable(lists),
                               chain.from_iterable(map(dict.values, dicts))))
    return None


def _valid_name(name: object) -> bool:
    """A name an author could have bound with a ``$`` line (§9.1). Hiding a built-in
    (``len``) is allowed; define names are dropped later, at restore."""
    return (type(name) is str
            and 0 < len(name) <= STATE_NAME_MAX_CHARS
            and not name.startswith("_")
            and name.isidentifier()
            and name not in PYTHON_KEYWORDS
            and name not in _SAVED_ENGINE_NAMES
            and unicodedata.is_normalized("NFKC", name))

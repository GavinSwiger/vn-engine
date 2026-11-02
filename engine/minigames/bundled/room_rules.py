"""The puzzle room's pure rules (F27 ``04`` §3, §4.2, §5.1, §6.2–§6.7; ``07`` I-3, I-5).

Why this module exists: everything about a puzzle room that can be decided without a window
lives here, so it can be tested directly and shared by the hooks (``check_args``,
``check_story``, ``outcome_for``) and the playable session (F27-3): the argument checks
R1–R14, parsing, the shown set, activation, combine, results, the fixed outcome, the W179 and
W180 texts, and the geometry of the buttons, picker, ring, tag, and images.

Pure: no clock, no randomness, no I/O. Imports only ``engine.minigames.api``, the shared
``bundled.rule_text``, ``engine.core.constants`` (``CANVAS_SIZE``: the canvas is defined in one
place, AC-F01-48), and the stdlib, with ``ui.layouts.Measure`` only for type checking
(AC-F27-01). The checks run on author values that F23 has already frozen; they never raise
and never change the arguments. Every refusal and warning text is a draft for the narrative
designer (F27 ``01`` §5.3, §5.4; ``04`` §5.1's † forms; ``07`` I-9).

**Held takes (07 G6, I-3, and the project's decision).** A take hotspot whose item the
player already holds is hidden, counts as spent for every ``after`` that names it, and joins
``gone`` in the run's result (``run_gone``), so it stays gone if the script later takes the
item away.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.core.constants import CANVAS_SIZE
from engine.minigames.api import Outcome, StoryNames, closest
from engine.minigames.bundled.rule_text import (kind_words, line_problem, quoted,
                                                value_echo)

if TYPE_CHECKING:
    from engine.ui.layouts import Measure

HOTSPOTS: Final = range(1, 41)
RECIPES_MAX, USE_MAX, GONE_MAX = 40, 8, 40
KEY_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}", re.ASCII)      # fullmatch
ROOM_KEYS: Final = ("background", "hotspots", "combine")
FIELDS: Final = ("rect", "label", "look", "take", "use", "nope", "exit", "after", "image")
CANVAS: Final = CANVAS_SIZE                         # the canvas (AC-F01-48: one definition)
RECT_MIN, NAME_MAX, LABEL_MAX, CAPTION_MAX = 32, 64, 40, 80
RING_GAP, RING_LINE, SHADOW_LINE = 4, 3, 2          # the ring's outer edge is rect + 7
TAG_GAP, TAG_PAD, TAG_SIZE = 8, (12, 6), 24
ITEMS_W, PUT_AWAY_X, PUT_AWAY_W, PUT_AWAY_PAD, ROW_W = 200, 216, (200, 480), 48, 696
PICKER_W, PICKER_INSET, BACK_W = 840, 16, 180       # F25's picker numbers (a local copy)
VIEW_MIN: Final = (640, 400)
HINT_X, HINT_W, HINT_GAP, HINT_BOTTOM = 140, 1000, 16, 696   # F23's widest hint bar
WARN_LIST = 3
REACH_PASSES_MAX = 81                               # 40 spots + 40 recipes + 1 (04 §6.7)
ITEM = "{item}"

Box4 = tuple[float, float, float, float]            # canvas units: (x, y, w, h)

_KEY_RULE = "use letters, digits, and _, starting with a letter."
_IMAGE_RULE = f"an image name is 1 to {NAME_MAX} characters on one line."
_LABEL_RULE = f"a label is 1 to {LABEL_MAX} characters on one line."
_CAPTION_RULE = f"a caption is 1 to {CAPTION_MAX} characters on one line."
_EDGE = "starts or ends with a space. Remove the space."
_COMBINE_RULE = ('combine must map each made item to two different items, e.g. '
                 '{"magnet_string": ["magnet", "string"]}, with at most '
                 f"{RECIPES_MAX} recipes.")
_STATE_RULE = "state must be None or the room's last result"


# --- Data ------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Spot:
    key: str
    rect: tuple[int, int, int, int]
    label: str
    look: str | None
    nope: str | None
    take: str | None
    use: tuple[str, ...]                     # () when absent
    exit: bool
    after: str | None
    image: str | None

    @property
    def spendable(self) -> bool:
        """Only a take or use hotspot is ever spent (enters ``gone``)."""
        return self.take is not None or bool(self.use)


@dataclass(frozen=True, slots=True)
class Room:
    background: str
    spots: tuple[Spot, ...]                  # room order
    combine: tuple[tuple[str, frozenset[str]], ...]   # (made, {a, b}), written order
    first_exit: str

    def spot(self, key: str) -> Spot:
        for s in self.spots:
            if s.key == key:
                return s
        raise KeyError(key)


@dataclass(frozen=True, slots=True)
class Caption:
    """A hint-bar caption: the author's ``text``, or the ``word`` (``"need_item"`` or
    ``"no_use"``); exactly one is set."""
    text: str | None
    word: str | None


@dataclass(frozen=True, slots=True)
class Finish:
    """The run ends with ``result``; ``give`` is a take's item (a ledger request)."""
    result: dict
    give: str | None


@dataclass(frozen=True, slots=True)
class RoomLayout:
    items: Box4
    put_away: Box4
    row: Box4                                # the widest row (Items + the widest Put away)


@dataclass(frozen=True, slots=True)
class PickerLayout:
    backing: Box4
    view: Box4                               # the CodexView's box
    back: Box4


# --- The checks (R1–R14) ---------------------------------------------------------------------

def _hint(text: str, written: object, names: Iterable[str]) -> str:
    hint = closest(written, names) if type(written) is str else None   # type: ignore[arg-type]
    return text + (f' Did you mean "{hint}"?' if hint is not None else "")


def _echo(key: object) -> str:
    """A key or name in a reason: quoted text, anything else as its value."""
    return quoted(key) if type(key) is str else value_echo(key)


def _form(text: object, lo: int, hi: int) -> str | None:
    """``rule_text.line_problem`` (no line breaks allowed), with only-white-space text as
    "empty" (F26 ``07`` I-1)."""
    if type(text) is str and text.strip() == "":
        return "empty"
    return line_problem(text, lo, hi)


def _text_problem(said: str, text: object, lo: int, hi: int, rule: str,
                  kind: str) -> str | None:
    """A one-line text's forms: ``kind`` for a value that isn't text, then the shared
    endings (empty, length, breaks, hidden, edge)."""
    form = _form(text, lo, hi)
    if form is None:
        return None
    if form == "not text":
        return kind
    if form == "empty":
        return f"{said} is empty; {rule}"
    if form == "length":
        return f"{said} is {len(text):,} characters long; {rule}"   # type: ignore[arg-type]
    if form == "breaks":
        return f"{said} has a line break; {rule}"
    if form == "hidden":
        return f"{said} has a hidden character; {rule}"
    return f"{said} {_EDGE}"


def _room_keys_problem(room: object) -> str | None:
    """R1."""
    if type(room) is not dict:
        return ('room must be a dictionary with "background" and "hotspots", but it is '
                f"{kind_words(room)}.")
    for key in room:
        if key not in ROOM_KEYS:
            return _hint(f"room has {_echo(key)}, which isn't background, hotspots, or "
                         "combine.", key, ROOM_KEYS)
    for key in ("background", "hotspots"):
        if key not in room:
            return f'room has no "{key}".'
    return None


def _background_problem(background: object) -> str | None:
    """R2."""
    return _text_problem(
        "background", background, 1, NAME_MAX, _IMAGE_RULE,
        'background must be an image name such as "bg attic", but it is '
        f"{value_echo(background)}.")


def _hotspots_problem(hotspots: object) -> str | None:
    """R3."""
    if type(hotspots) is not dict:
        return (f"hotspots must be a dictionary of 1 to {HOTSPOTS[-1]} hotspots, but it is "
                f"{kind_words(hotspots)}.")
    if len(hotspots) not in HOTSPOTS:
        return (f"hotspots must be a dictionary of 1 to {HOTSPOTS[-1]} hotspots, but it has "
                f"{len(hotspots):,}.")
    for key in hotspots:
        if type(key) is not str or KEY_RE.fullmatch(key) is None:
            return f"{_echo(key)} can't be a hotspot name; {_KEY_RULE}"
    return None


def _spendable(spot: object) -> bool:
    return type(spot) is dict and ("take" in spot or "use" in spot)


def _rect_ok(rect: object) -> bool:
    if type(rect) is not list or len(rect) != 4 or any(type(v) is not int for v in rect):
        return False
    x, y, w, h = rect
    return (w >= RECT_MIN and h >= RECT_MIN and x >= 0 and y >= 0 and x + w <= CANVAS[0]
            and y + h <= CANVAS[1])


def _use_ok(use: object) -> bool:
    if type(use) is str:
        return True
    return (type(use) is list and 1 <= len(use) <= USE_MAX
            and all(type(name) is str for name in use))


def _spot_problem(key: str, spot: object, hotspots: dict) -> str | None:
    """R4–R11 for one hotspot, in that order."""
    name = quoted(key)
    if type(spot) is not dict:                                            # R4
        return f"hotspot {name} must be a dictionary of fields, but it is {value_echo(spot)}."
    for field in spot:
        if field not in FIELDS:
            return _hint(f"hotspot {name} has {_echo(field)}, which isn't a hotspot field.",
                         field, FIELDS)
    for field in ("rect", "label"):
        if field not in spot:
            return f'hotspot {name} has no "{field}".'
    rect = spot["rect"]                                                   # R5
    if not _rect_ok(rect):
        return (f"the rect of {name} must be [x, y, width, height] in whole numbers, at least "
                f"{RECT_MIN} × {RECT_MIN} and inside {CANVAS[0]} × {CANVAS[1]}, but it is "
                f"{value_echo(rect)}.")
    for field, hi, rule in (("label", LABEL_MAX, _LABEL_RULE),               # R6
                            ("look", CAPTION_MAX, _CAPTION_RULE),
                            ("nope", CAPTION_MAX, _CAPTION_RULE)):
        if field not in spot:
            continue
        said = f"the {field} of {name}"
        found = _text_problem(said, spot[field], 1, hi, rule,
                              f"{said} is {kind_words(spot[field])}, not text; {rule}")
        if found is not None:
            return found
    does = [f for f in ("take", "use") if f in spot] + (                  # R7
        ["exit"] if spot.get("exit") is True else [])
    if len(does) > 1:
        return (f"hotspot {name} has both {does[0]} and {does[1]}; a hotspot does one of "
                "take, use, or exit.")
    if "look" in spot and does and does[0] in ("take", "exit"):
        return (f"hotspot {name} has both look and {does[0]}; a hotspot that takes or leaves "
                "ends the run at once, so it has no look.")
    if "nope" in spot and "use" not in spot:
        return (f"hotspot {name} has nope but no use; nope is the caption for a wrong item, "
                "so it needs use.")
    if "take" in spot and type(spot["take"]) is not str:                  # R8
        return f"the take of {name} must be an item name, but it is {value_echo(spot['take'])}."
    if "use" in spot and not _use_ok(spot["use"]):
        return (f"the use of {name} must be an item name or a list of 1 to {USE_MAX} item "
                f"names, but it is {value_echo(spot['use'])}.")
    if "after" in spot:                                                   # R9
        after = spot["after"]
        if type(after) is not str or after not in hotspots:
            return _hint(f"hotspot {name} comes after {_echo(after)}, which isn't in hotspots.",
                         after, hotspots)
        if not _spendable(hotspots[after]):
            return (f"hotspot {name} comes after {quoted(after)}, which has no take or use, so "
                    "it is never spent.")
    if "image" in spot:                                                   # R10
        image = spot["image"]
        said = f"the image of {name}"
        found = _text_problem(said, image, 1, NAME_MAX, _IMAGE_RULE,
                              f'{said} must be an image name such as "attic key", but it is '
                              f"{value_echo(image)}.")
        if found is not None:
            return found
    if "exit" in spot and type(spot["exit"]) is not bool:                 # R11
        return f"the exit of {name} must be True or False, but it is {value_echo(spot['exit'])}."
    return None


def _cycle(hotspots: dict) -> list[str] | None:
    """R9′: the first ``after`` cycle, starting at its first hotspot in room order, or None.
    Each chain is followed at most 40 steps (every ``after`` names a hotspot by now)."""
    for start in hotspots:
        chain, key = [start], hotspots[start].get("after")
        for _ in range(HOTSPOTS[-1]):
            if key is None or key == start:
                break
            chain.append(key)
            key = hotspots[key].get("after")
        if key == start:
            return chain
    return None


def _cycle_text(chain: Sequence[str]) -> str:
    if len(chain) == 1:
        return f"hotspot {quoted(chain[0])} comes after itself, so it can never be shown."
    if len(chain) == 2:
        return (f"hotspots {quoted(chain[0])} and {quoted(chain[1])} come after each other, "
                "so neither can be shown.")
    names = ", ".join(quoted(k) for k in chain[:WARN_LIST])
    more = f", and {len(chain) - WARN_LIST} more" if len(chain) > WARN_LIST else ""
    return f"hotspots {names}{more} come after each other in a circle, so none can be shown."


def _combine_problem(combine: object) -> str | None:
    """R12."""
    if type(combine) is not dict or len(combine) > RECIPES_MAX:
        return _COMBINE_RULE
    seen: dict[frozenset[str], list[str]] = {}
    for made, pair in combine.items():
        if (type(made) is not str or type(pair) is not list or len(pair) != 2
                or any(type(name) is not str for name in pair) or pair[0] == pair[1]):
            return _COMBINE_RULE
        if made in pair:
            return f"combine makes {quoted(made)} from itself."
        both = frozenset(pair)
        if both in seen:
            first = seen[both]
            return f"combine lists {quoted(first[0])} and {quoted(first[1])} twice."
        seen[both] = pair
    return None


def _state_problem(state: object) -> str | None:
    """R13."""
    if state is None:
        return None
    if type(state) is not dict:
        return f"{_STATE_RULE}, but it is {kind_words(state)}."
    if "gone" not in state:
        return f'{_STATE_RULE}, but it has no "gone".'
    gone = state["gone"]
    if (type(gone) is not list or len(gone) > GONE_MAX
            or any(type(name) is not str for name in gone)):
        return (f'{_STATE_RULE}, whose "gone" is a list of up to {GONE_MAX} hotspot names, but '
                f'its "gone" is {value_echo(gone)}.')
    return None


def room_problem(room: object) -> str | None:
    """R1–R12 on ``room`` alone: the first problem's reason, or None."""
    found = _room_keys_problem(room)
    if found is not None:
        return found
    assert type(room) is dict
    found = _background_problem(room["background"]) or _hotspots_problem(room["hotspots"])
    if found is not None:
        return found
    hotspots = room["hotspots"]
    for key, spot in hotspots.items():
        found = _spot_problem(key, spot, hotspots)
        if found is not None:
            return found
    chain = _cycle(hotspots)
    if chain is not None:
        return _cycle_text(chain)
    if not any(spot.get("exit") is True for spot in hotspots.values()):     # R11′
        return 'room has no hotspot with "exit": True, so it can\'t be left.'
    if "combine" in room:
        return _combine_problem(room["combine"])
    return None


def problem(args: dict) -> str | None:
    """R1–R13 in F27 ``04`` §5.1's order (within a rule, written order): the first problem's
    reason, or None. No side effects; never raises for frozen values."""
    return room_problem(args.get("room")) or _state_problem(args.get("state"))


def _names(value: object) -> tuple[object, ...]:
    if type(value) is str:
        return (value,)
    if type(value) is list:
        return tuple(value)
    return ()


def _story_names(room: dict) -> Iterable[tuple[str, object]]:
    """(locator, name) for R14, in its order: each hotspot's take, then its use names; then
    each recipe's made item, then its pair. Lenient on unchecked rooms."""
    hotspots = room.get("hotspots")
    if type(hotspots) is dict:
        for key, spot in hotspots.items():
            if type(spot) is not dict:
                continue
            if "take" in spot:
                yield f"the take of {_echo(key)} is", spot["take"]
            for name in _names(spot.get("use")):
                yield f"the use of {_echo(key)} is", name
    combine = room.get("combine")
    if type(combine) is dict:
        for made, pair in combine.items():
            yield "combine makes", made
            for name in _names(pair):
                yield f"the recipe for {_echo(made)} uses", name


def story_problem(args: dict, story: StoryNames) -> str | None:
    """R14 against the story's declared names: the first problem's reason, or None. Meant
    for arguments that pass ``problem``; never raises for others."""
    room = args.get("room")
    if type(room) is not dict:
        return None
    for said, name in _story_names(room):
        if type(name) is not str:
            continue
        if name in story.tips:
            return f"{said} {quoted(name)}, which is a tip; only items can be held."
        if name not in story.items:
            return _hint(f"{said} {quoted(name)}, but there is no item named {quoted(name)}.",
                         name, story.items)
    return None


# --- Parsing, the shown set, activation, and results -----------------------------------------

def parse(room: dict) -> Room:
    """The checked room as a ``Room``. The room must pass R1–R12 (an engine bug otherwise)."""
    assert room_problem(room) is None, "parse() needs a checked room"
    spots = []
    for key, f in room["hotspots"].items():
        x, y, w, h = f["rect"]
        spots.append(Spot(key=key, rect=(x, y, w, h), label=f["label"], look=f.get("look"),
                          nope=f.get("nope"), take=f.get("take"),
                          use=tuple(_names(f.get("use"))),        # type: ignore[arg-type]
                          exit=f.get("exit") is True, after=f.get("after"),
                          image=f.get("image")))
    combine = tuple((made, frozenset(pair)) for made, pair in room.get("combine", {}).items())
    first_exit = next(s.key for s in spots if s.exit)
    return Room(background=room["background"], spots=tuple(spots), combine=combine,
                first_exit=first_exit)


def _ordered(room: Room, keys: Iterable[str]) -> tuple[str, ...]:
    wanted = set(keys)
    return tuple(s.key for s in room.spots if s.key in wanted)


def known_gone(room: Room, state: object) -> tuple[str, ...]:
    """``state``'s ``gone`` ∩ the spendable keys, in room order, once each; ``()`` for None
    (PR-F27-10). Unknown and non-spendable names are dropped."""
    if type(state) is not dict or type(state.get("gone")) is not list:
        return ()
    gone = {name for name in state["gone"] if type(name) is str}
    return tuple(s.key for s in room.spots if s.spendable and s.key in gone)


def held_takes(room: Room, held: Iterable[str]) -> tuple[str, ...]:
    """The take hotspots whose item is held, in room order: hidden, and spent for ``after``
    (07 G6)."""
    have = set(held)
    return tuple(s.key for s in room.spots if s.take is not None and s.take in have)


def run_gone(room: Room, state: object, held: Iterable[str]) -> tuple[str, ...]:
    """A run's ``gone``: ``known_gone`` plus the held takes, in room order (the main
    session's G6 decision: a held take is reported as gone, so it stays gone if the script
    later takes its item). The session passes this to ``activate`` and ``result_of``."""
    return _ordered(room, (*known_gone(room, state), *held_takes(room, held)))


def shown(room: Room, gone: Iterable[str], held: Iterable[str]) -> tuple[str, ...]:
    """The shown hotspots in room order (PR-F27-05, 07 I-3): not in ``gone``; ``after`` None,
    or in ``gone``, or a take hotspot whose item is held; a take's item not held."""
    have = set(held)
    spent = set(gone) | set(held_takes(room, have))
    return tuple(s.key for s in room.spots
                 if s.key not in spent and (s.after is None or s.after in spent))


def result_of(room: Room, action: str, hotspot: str | None, item: str | None,
              gone: Iterable[str], spent: str | None = None) -> dict:
    """The ``into`` value: ``{"action", "hotspot", "item", "gone"}``, with ``gone`` the room-
    ordered union of ``gone`` and ``spent`` (PR-F27-09)."""
    keys = (*gone, spent) if spent is not None else tuple(gone)
    return {"action": action, "hotspot": hotspot, "item": item,
            "gone": list(_ordered(room, keys))}


def activate(room: Room, key: str, selected: str | None,
             gone: Iterable[str]) -> Caption | Finish:
    """Activating a shown hotspot, with or without a selected item (04 §6.2; Q-d: with a
    selection, every hotspot is a use target)."""
    s = room.spot(key)
    gone = tuple(gone)
    if selected is None:
        if s.take is not None:
            return Finish(result_of(room, "take", key, s.take, gone, spent=key), give=s.take)
        if s.use:
            return Caption(s.look, None) if s.look is not None else Caption(None, "need_item")
        if s.look is not None:
            return Caption(s.look, None)
        return Finish(result_of(room, "exit" if s.exit else "click", key, None, gone), None)
    if selected in s.use:
        return Finish(result_of(room, "use", key, selected, gone, spent=key), None)
    return Caption(s.nope, None) if s.nope is not None else Caption(None, "no_use")


def combine_pair(room: Room, a: str, b: str) -> str | None:
    """The item ``a`` and ``b`` make together (order ignored), or None."""
    if a == b:
        return None
    pair = frozenset((a, b))
    for made, needs in room.combine:
        if needs == pair:
            return made
    return None


def fixed_outcome(room: Room, gone: Iterable[str]) -> Outcome:
    """``outcome_for``'s answer for ``"test"`` and ``"skipped"`` (04 §6.4, TR-F27-03): leave
    by the first exit in room order, shown or not, with no changes. Never None."""
    return Outcome({"action": "exit", "hotspot": room.first_exit, "item": None,
                    "gone": list(_ordered(room, gone))}, ())


# --- W179 and W180 (texts; the session logs them in dev, F27-3) ------------------------------

def reach(room: Room, gone: Iterable[str],
          held: Iterable[str]) -> tuple[frozenset[str], frozenset[str]]:
    """W179's optimistic fixpoint (04 §6.7, 07 I-3): (spent hotspots, reachable items). It
    starts from ``gone``, the held takes, and the held items, then repeatedly spends every
    reachable take (adding its item) and every use with a reachable item, and makes every
    recipe whose pair is reachable. Uses never consume. At most 81 passes."""
    items = set(held)
    spent = set(gone) | set(held_takes(room, items))
    for passes in range(1, REACH_PASSES_MAX + 1):
        before = (len(spent), len(items))
        for s in room.spots:
            if s.key in spent or (s.after is not None and s.after not in spent):
                continue
            if s.take is not None:
                spent.add(s.key)
                items.add(s.take)
            elif s.use and items.intersection(s.use):
                spent.add(s.key)
        for made, pair in room.combine:
            if pair <= items:
                items.add(made)
        if (len(spent), len(items)) == before:
            return frozenset(spent), frozenset(items)
    raise AssertionError("reach() did not settle within 81 passes")


def w179_text(room: Room, gone: Iterable[str], held: Iterable[str]) -> str | None:
    """W179's text (01 §5.4; one form, 07 G6), or None when some exit can be shown. It lists
    the reachable, unspent use hotspots in room order: the first 3 as ``key (item, item)``,
    then "and N more". A blocked exit's ``after`` chain always ends at one (07 G6)."""
    spent, _ = reach(room, gone, held)
    if any(s.exit and (s.after is None or s.after in spent) for s in room.spots):
        return None
    stuck = [s for s in room.spots if s.use and s.key not in spent
             and (s.after is None or s.after in spent)]
    assert stuck, "a blocked exit's after chain ends at a reachable use hotspot"
    listed = ", ".join(f"{s.key} ({', '.join(s.use)})" for s in stuck[:WARN_LIST])
    if len(stuck) > WARN_LIST:
        listed += f", and {len(stuck) - WARN_LIST} more"
    return (f"puzzle_room in {quoted(room.background)} can't be left: nothing the player has "
            f"or can find works on {listed}. Give the player one of those items, or change the "
            "room.")


def _overlap(a: Box4, b: Box4) -> float:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(w, 0) * max(h, 0)


def hint_band(area: object) -> Box4:
    """The widest hint bar F23 draws below ``area`` (04 §6.7)."""
    _, ay, _, ah = _rect(area)
    top = ay + ah + HINT_GAP
    return (HINT_X, top, HINT_W, HINT_BOTTOM - top)


def w180_texts(room: Room, keys: Iterable[str], *, row: Box4,
               area: object) -> tuple[str, ...]:
    """W180's texts (04 §6.7), one per shown hotspot in ``keys`` whose rect is more than half
    under the button ``row`` or the widest hint bar, in room order."""
    hint = hint_band(area)
    wanted = set(keys)
    found = []
    for s in room.spots:
        if s.key not in wanted:
            continue
        x, y, w, h = s.rect
        if _overlap(s.rect, row) + _overlap(s.rect, hint) > w * h / 2:
            found.append(f"puzzle_room in {quoted(room.background)}: the hotspot "
                         f"{quoted(s.key)} is mostly under the Items row or the hint at this "
                         "text size. Move it, or make it bigger.")
    return tuple(found)


# --- Geometry --------------------------------------------------------------------------------

def _rect(area: object) -> Box4:
    """An area as ``(x, y, w, h)``: a 4-tuple, or a ``Box``-like object."""
    if hasattr(area, "x"):
        return (area.x, area.y, area.w, area.h)       # type: ignore[attr-defined]
    x, y, w, h = area                                 # type: ignore[misc]
    return (x, y, w, h)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(v, hi))


def room_layout(area: object, *, button_h: float, put_away_w: float) -> RoomLayout:
    """Room mode's buttons in F23's content ``area`` (04 §6.6): Items 200 wide at the
    area's topleft, Put away 216 to its right, and the widest row (696) the tag and W180
    keep clear of. Hotspots are canvas units and never move."""
    ax, ay, aw, ah = _rect(area)
    assert ROW_W <= aw and button_h <= ah, "the button row doesn't fit the area"
    return RoomLayout(items=(ax, ay, ITEMS_W, button_h),
                      put_away=(ax + PUT_AWAY_X, ay, put_away_w, button_h),
                      row=(ax, ay, ROW_W, button_h))


def picker_layout(area: object, *, button_h: float) -> PickerLayout:
    """Picker mode in F23's content ``area`` (F25's numbers, 04 §6.6): the backing panel,
    840 wide and centered; the view inset by 16 (at least 640×400); Back at the bottom
    left."""
    ax, ay, aw, ah = _rect(area)
    backing = (ax + (aw - PICKER_W) / 2, ay, PICKER_W, ah)
    view = (backing[0] + PICKER_INSET, ay + PICKER_INSET, PICKER_W - 2 * PICKER_INSET,
            ah - 2 * PICKER_INSET)
    assert view[2] >= VIEW_MIN[0] and view[3] >= VIEW_MIN[1], "the picker is too small"
    return PickerLayout(backing=backing, view=view,
                        back=(ax, ay + ah - button_h, BACK_W, button_h))


def put_away_label(word: str, title: str, *, size: int, measure: "Measure",
                   cut_to_width: Callable[[str, float, int, "Measure"], str]) -> tuple[str, float]:
    """Put away's (label, width) (04 §6.6, UI-F27-05). ``word`` is the ``put_away`` word,
    ``{item}`` replaced by ``title`` with ``str.replace``. The width is the label + 48,
    clamped to 200–480; when that doesn't fit 480, only the title is cut (with
    ``cut_to_width``, F10's ``layouts.cut_to_width``, passed in so this module stays free
    of ``ui``) and the width is 480."""
    full = word.replace(ITEM, title)
    w = measure(full, size) + PUT_AWAY_PAD
    lo, hi = PUT_AWAY_W
    if w <= hi:
        return full, _clamp(w, lo, hi)
    room_for_title = hi - PUT_AWAY_PAD - measure(word.replace(ITEM, ""), size)
    return word.replace(ITEM, cut_to_width(title, room_for_title, size, measure)), hi


def _band(outer: Box4, t: float) -> tuple[Box4, Box4, Box4, Box4]:
    """``outer`` minus ``outer`` shrunk by ``t``: top, bottom, left, right (disjoint)."""
    x, y, w, h = outer
    return ((x, y, w, t), (x, y + h - t, w, t), (x, y + t, t, h - 2 * t),
            (x + w - t, y + t, t, h - 2 * t))


def _grow(rect: Sequence[float], by: float) -> Box4:
    x, y, w, h = rect
    return (x - by, y - by, w + 2 * by, h + 2 * by)


def ring_rects(rect: Sequence[float]) -> tuple[tuple[Box4, ...], tuple[Box4, ...]]:
    """The ring (01 §6.1, 04 §6.6): ``R`` is ``rect`` grown by 4; the color is a 3-unit band
    just outside ``R``, the shadow a 2-unit band just inside it. (color ×4, shadow ×4), 8
    fills, since there is no line primitive."""
    return (_band(_grow(rect, RING_GAP + RING_LINE), RING_LINE),
            _band(_grow(rect, RING_GAP), SHADOW_LINE))


def tag_box(rect: Sequence[float], w: float, h: float, *, row_bottom: float,
            area: object) -> Box4:
    """The tag's box (04 §6.6, 07 I-5): ``w``×``h`` (the session wraps the label and passes
    the widest line + 24 and ``lines × pitch + 12``). Above the ring's outer box, else below
    it, else inside it; never above ``row_bottom + 8`` or past the area. "Below" is also kept
    under the row, so a spot under the buttons still gets its tag below them (AC-F27-17's
    corner spots)."""
    ax, ay, aw, ah = _rect(area)
    ox, oy, ow, oh = _grow(rect, RING_GAP + RING_LINE)
    x = _clamp(ox + ow / 2 - w / 2, ax, ax + aw - w)
    y = oy - TAG_GAP - h
    if y < row_bottom + TAG_GAP:
        y = max(oy + oh + TAG_GAP, row_bottom + TAG_GAP)
    if y + h > ay + ah:
        y = _clamp(oy + TAG_GAP, row_bottom + TAG_GAP, ay + ah - h)
    return (x, y, w, h)


def cover_box(size: tuple[int, int]) -> Box4:
    """F04's cover of the 1280×720 canvas: scaled to fill it, centered, cropped by the
    canvas."""
    w, h = max(size[0], 1), max(size[1], 1)
    k = max(CANVAS[0] / w, CANVAS[1] / h)
    return ((CANVAS[0] - w * k) / 2, (CANVAS[1] - h * k) / 2, w * k, h * k)


def fit_box(size: tuple[int, int], rect: Sequence[float]) -> Box4:
    """An image fitted into ``rect``: scaled to fit, centered, never cropped."""
    rx, ry, rw, rh = rect
    w, h = max(size[0], 1), max(size[1], 1)
    k = min(rw / w, rh / h)
    return (rx + (rw - w * k) / 2, ry + (rh - h * k) / 2, w * k, h * k)


__all__ = ["CANVAS", "CAPTION_MAX", "FIELDS", "GONE_MAX", "HOTSPOTS", "KEY_RE", "LABEL_MAX",
           "NAME_MAX", "RECIPES_MAX", "RECT_MIN", "ROOM_KEYS", "TAG_PAD", "TAG_SIZE",
           "USE_MAX", "Caption", "Finish", "PickerLayout", "Room", "RoomLayout", "Spot",
           "activate", "combine_pair", "cover_box", "fit_box", "fixed_outcome", "held_takes",
           "hint_band", "known_gone", "parse", "picker_layout", "problem", "put_away_label",
           "reach", "result_of", "ring_rects", "room_layout", "room_problem", "run_gone",
           "shown", "story_problem", "tag_box", "w179_text", "w180_texts"]

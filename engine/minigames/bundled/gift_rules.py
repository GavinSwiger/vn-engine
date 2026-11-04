"""Gift giving's pure rules (F54 SPEC §3, §4.1, §5).

Why this module exists: the gift table's checks, the reaction a gift gets, the outcomes and
the card's layout can all be decided without a window, so the hooks and the session share one
copy and Studio's mirror (``minigamedata``, ADR-0008) is tested against it case by case:

- **Checks.** ``problem(args)``: G1–G15 (``check_args``), in table order, characters and items
  in written order, the first problem only, never raising, never changing ``args``.
  ``story_problem(args, story)``: G16–G18 (``check_story``) against the declared items,
  meters and item categories.
- **Play.** ``parse`` → ``GiftTable``; ``reaction_for(table, to, item)``: the item's row, else
  the character's ``"*"`` row, else neutral with 0 points and no line. ``givable`` lists the
  held items the picker shows; ``w285_text`` is the dev warning when it is empty.
- **Outcomes.** ``fixed_outcome``: test and skipped give ``"neutral"`` (``result="reaction"``)
  or None (``result="item"``), with no changes.
- **Look.** ``picker_layout`` (F25's numbers) and ``card_layout``.

Pure: no clock, no randomness, no I/O. Imports only ``engine.minigames.api``,
``bundled.rule_text`` and the stdlib.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from engine.minigames.api import Outcome, StoryNames, closest
from engine.minigames.bundled.rule_text import (choice_problem, flag_problem, kind_words,
                                                quoted, text_problem, value_echo)

REACTIONS: Final = ("loved", "liked", "neutral", "disliked")
RESULTS: Final = ("reaction", "item")
CHARACTERS_MAX: Final = 32
GIFTS_MAX: Final = 200
POINTS: Final = (-10, 10)
LINE_MAX: Final = 160
SPEAKER_MAX: Final = 24
CATEGORIES_MAX: Final = 24
CATEGORY_MAX: Final = 24
ANY: Final = "*"
NAMES_SHOWN: Final = 3                # G11 lists this many characters, then "and N more"
NAME_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}", re.ASCII)
DEFAULTS: Final = {"gifts": None, "to": None, "speaker": None, "categories": None,
                   "use_up": True, "leave": True, "result": "reaction"}
REQUIRED: Final = ("gifts", "to")
EXAMPLE: Final = '{"hana": {"red_lantern": ["loved", 3]}}'

Rect = tuple[float, float, float, float]


# --- The checks (G1–G15) ---------------------------------------------------------------------

def _name(key: object) -> bool:
    return type(key) is str and NAME_RE.fullmatch(key) is not None


def _gift_problem(c: str, i: str, row: object) -> str | None:
    where = f"the gift {quoted(i)} for {quoted(c)}"
    if type(row) is not list:                                                    # G7
        return (f'{where} must be a list such as ["loved", 3, "Thank you!"], but it is '
                f"{kind_words(row)}.")
    if len(row) not in (2, 3):
        return (f'{where} must be a list such as ["loved", 3, "Thank you!"], but it has '
                f"{len(row)} parts.")
    reaction = row[0]
    if type(reaction) is not str or reaction not in REACTIONS:                   # G8
        hint = closest(reaction, REACTIONS)
        return (f"{where} has the reaction {value_echo(reaction)}; a reaction is \"loved\", "
                '"liked", "neutral", or "disliked".'
                + (f' Did you mean "{hint}"?' if hint is not None else ""))
    points = row[1]
    if type(points) is not int or not POINTS[0] <= points <= POINTS[1]:          # G9
        return (f"{where} gives {value_echo(points)} points; points are a whole number from "
                "-10 to 10.")
    if len(row) == 3:                                                            # G10
        return text_problem(f"the line for {quoted(i)} ({c})", row[2], LINE_MAX, required=True)
    return None


def _table_problem(gifts: object) -> str | None:
    if type(gifts) is not dict:                                                  # G1
        return (f"gifts must be a dictionary of characters and their gifts, such as {EXAMPLE}, "
                f"but it is {kind_words(gifts)}.")
    if not 1 <= len(gifts) <= CHARACTERS_MAX:                                    # G2
        return f"gifts has {len(gifts)} characters; it can have 1 to {CHARACTERS_MAX}."
    for c, rows in gifts.items():
        if not _name(c):                                                         # G3
            return (f"{value_echo(c) if type(c) is str else quoted(str(c))} can't be a "
                    "character in gifts; write it as points names a meter: letters, digits, "
                    "and _.")
        if type(rows) is not dict:                                               # G4
            return (f"the gifts for {quoted(c)} must be a dictionary of items and reactions, "
                    f"but they are {kind_words(rows)}.")
        if len(rows) > GIFTS_MAX + (ANY in rows):                                # G5
            return f"{quoted(c)} has {len(rows)} gifts; a character can have up to {GIFTS_MAX}."
        for i, row in rows.items():
            if not (i == ANY or _name(i)):                                       # G6
                shown = value_echo(i) if type(i) is str else quoted(str(i))
                return (f"{shown} in the gifts for {quoted(c)} can't be an item name; write an "
                        'item\'s name, or "*" for any other gift.')
            found = _gift_problem(c, i, row)
            if found is not None:
                return found
    return None


def _names_list(names: Sequence[str]) -> str:
    shown = ", ".join(quoted(n) for n in names[:NAMES_SHOWN])
    more = len(names) - NAMES_SHOWN
    return shown + (f", and {more} more" if more > 0 else "")


def problem(args: dict) -> str | None:
    """The first refused argument's reason (G1–G15), or None."""
    gifts = args.get("gifts")
    found = _table_problem(gifts)
    if found is not None:
        return found
    to = args.get("to")
    names = list(gifts)                                                         # type: ignore
    if type(to) is not str or to not in gifts:                                   # G11
        hint = closest(to, names)
        return (f"to must be one of the characters in gifts ({_names_list(names)}), but it is "
                f"{value_echo(to)}." + (f' Did you mean "{hint}"?' if hint is not None else ""))
    found = text_problem("speaker", args.get("speaker"), SPEAKER_MAX)            # G12
    if found is not None:
        return found
    categories = args.get("categories")                                          # G13
    if categories is not None:
        if type(categories) is not list or not 1 <= len(categories) <= CATEGORIES_MAX:
            return ("categories must be a list of 1 to 24 item category names, such as "
                    f'["Gifts"], or None, but it is {kind_words(categories)}.')
        for n, name in enumerate(categories, start=1):
            found = text_problem(f"category {n} in categories", name, CATEGORY_MAX,
                                 required=True)
            if found is not None:
                return found
    result = args.get("result", DEFAULTS["result"])
    return (flag_problem("use_up", args.get("use_up", True))                     # G14
            or flag_problem("leave", args.get("leave", True))
            or choice_problem("result", result, RESULTS,                         # G15
                              closest=closest(result, RESULTS)))


def story_problem(args: dict, story: StoryNames) -> str | None:
    """G16–G18 against the story's declared names, or None. Meant for arguments that pass
    ``problem``; never raises for others."""
    gifts = args.get("gifts")
    if type(gifts) is not dict:
        return None
    for c, rows in gifts.items():                                                # G16
        if type(rows) is not dict:
            continue
        for i in rows:
            if type(i) is str and i != ANY and i not in story.items:
                hint = closest(i, story.items)
                return (f"the gifts for {quoted(str(c))} name the item {quoted(i)}, but there is "
                        f"no item named {quoted(i)}."
                        + (f' Did you mean "{hint}"?' if hint is not None else ""))
    for c, rows in gifts.items():                                                # G17
        if type(rows) is not dict or c in story.meters:
            continue
        if any(type(row) is list and len(row) > 1 and row[1] != 0 for row in rows.values()):
            return (f"the gifts for {quoted(str(c))} give points, but there is no meter named "
                    f"{quoted(str(c))}. Declare it with points {c}, or set its points to 0.")
    categories = args.get("categories")                                          # G18
    if type(categories) is list:
        keys = [key for key, _ in story.item_categories]
        for name in categories:
            if type(name) is str and name not in keys:
                hint = closest(name, keys)
                return (f"there is no item category {quoted(name)}."
                        + (f' Did you mean "{hint}"?' if hint is not None else ""))
    return None


# --- Play ------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Gift:
    reaction: str
    points: int
    line: str | None


NEUTRAL: Final = Gift("neutral", 0, None)
GiftTable = dict[str, dict[str, Gift]]


def parse(args: dict) -> GiftTable:
    """The checked ``gifts`` as a table of ``Gift``s."""
    return {c: {i: Gift(row[0], row[1], row[2] if len(row) == 3 else None)
                for i, row in rows.items()}
            for c, rows in args["gifts"].items()}


def reaction_for(table: GiftTable, to: str, item: str) -> Gift:
    """The item's row for ``to``, else ``to``'s ``"*"`` row, else neutral, 0, no line."""
    rows = table.get(to, {})
    return rows.get(item) or rows.get(ANY) or NEUTRAL


def speaker_of(args: dict) -> str:
    """``speaker``, or ``to`` with a capital first letter."""
    speaker = args.get("speaker")
    if type(speaker) is str:
        return speaker
    to = str(args.get("to") or "")
    return to[:1].upper() + to[1:]


def givable(held: Sequence[str], categories: Sequence[str] | None,
            story: StoryNames) -> tuple[str, ...]:
    """The held items the picker lists: those in ``categories``, or every held item."""
    if categories is None:
        return tuple(held)
    wanted = frozenset(categories)
    home = {name: key for key, names in story.item_categories for name in names}
    return tuple(name for name in held if home.get(name) in wanted)


def w285_text(to: str) -> str:
    return (f"gift_giving to {quoted(to)}: the player holds no item the picker can show, so the "
            'game says "You have nothing to give." and the result is None.')


def fixed_outcome(args: dict) -> Outcome:
    """Test and skipped: neutral (or None for ``result="item"``), nothing given or taken."""
    return Outcome(None if args.get("result", DEFAULTS["result"]) == "item" else "neutral")


def clamp_size(value: object, default: int, lo: int, hi: int) -> int:
    if type(value) is not int:
        return default
    return min(hi, max(lo, value))


# --- Look ------------------------------------------------------------------------------------

BACKING_W, VIEW_INSET = 840, 16       # F25's picker numbers
BACK_W: Final = 180
CARD_W, CARD_PAD, CARD_GAP = 800, 24, 8
CONTINUE_W: Final = 200
LINE_TEXT: Final = (28, 24, 40)       # line.text_size: default, lo, hi
VERDICT_TEXT: Final = 24
LINES_MAX: Final = 3


@dataclass(frozen=True, slots=True)
class PickerLayout:
    backing: Rect
    view: Rect
    back: Rect


def picker_layout(area: Sequence[float], *, button_h: float) -> PickerLayout:
    """F25's picker (``present_rules.picker_layout``): the codex view in an 840-wide backing
    panel, inset 16; Not now at the content area's bottom left."""
    ax, ay, aw, ah = (float(v) for v in area)
    bw = min(float(BACKING_W), aw)
    backing = (ax + (aw - bw) / 2, ay, bw, ah)
    view = (backing[0] + VIEW_INSET, ay + VIEW_INSET, bw - 2 * VIEW_INSET, ah - 2 * VIEW_INSET)
    return PickerLayout(backing, view, (ax, ay + ah - button_h, float(BACK_W), float(button_h)))


@dataclass(frozen=True, slots=True)
class CardLayout:
    panel: Rect
    name: Rect
    line: Rect
    verdict: Rect
    cont: Rect


def card_layout(area: Sequence[float], *, name_h: float, line_h: float, verdict_h: float,
                button_h: float) -> CardLayout:
    """The reaction card, 800 wide and centered: the speaker, the line, the verdict, and
    Continue at the bottom right."""
    ax, ay, aw, ah = (float(v) for v in area)
    w = min(float(CARD_W), aw)
    inner = w - 2 * CARD_PAD
    parts = [h for h in (name_h, line_h, verdict_h) if h > 0]
    h = 2 * CARD_PAD + sum(parts) + CARD_GAP * len(parts) + button_h
    x, y = ax + (aw - w) / 2, ay + max(0.0, (ah - h) / 2)
    top = y + CARD_PAD
    name = (x + CARD_PAD, top, inner, name_h)
    top += name_h + (CARD_GAP if name_h else 0)
    line = (x + CARD_PAD, top, inner, line_h)
    top += line_h + (CARD_GAP if line_h else 0)
    verdict = (x + CARD_PAD, top, inner, verdict_h)
    top += verdict_h + (CARD_GAP if verdict_h else 0)
    cont = (x + w - CARD_PAD - CONTINUE_W, top, float(CONTINUE_W), float(button_h))
    return CardLayout((x, y, w, h), name, line, verdict, cont)


__all__ = ["ANY", "CardLayout", "DEFAULTS", "Gift", "GiftTable", "NEUTRAL", "PickerLayout",
           "REACTIONS", "RESULTS", "card_layout", "clamp_size", "fixed_outcome", "givable",
           "parse", "picker_layout", "problem", "reaction_for", "speaker_of", "story_problem",
           "w285_text"]

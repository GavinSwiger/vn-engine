"""The cross-examination's pure rules (F25 ``04`` §4.2, §5.1, §6.1–§6.6).

Why this module exists: everything about a cross-examination that can be decided without a
window lives here, so it can be tested directly and shared by the hooks (``check_args``,
``check_story``, ``outcome_for``) and the playable session (F25-3): the argument checks
R1–R14, parsing, judging, results, the fixed outcome, what the picker can present, the W173
texts, and the geometry of both modes and the penalty bar.

Pure: no clock, no randomness, no I/O. Imports only ``engine.minigames.api``, the shared
``bundled.rule_text``, and the stdlib (AC-F25-01). The checks run on author values that F23
has already frozen; they never raise and never change the arguments. Every refusal and W173
text is a draft for the narrative designer (F25 ``01`` §5.3, §5.4).
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from engine.minigames.api import Outcome, StoryNames, closest
from engine.minigames.bundled.rule_text import (kind_words, line_problem, quoted,
                                                value_echo)

STATEMENTS: Final = range(1, 13)
TEXT_MAX, KEY_MAX, SPEAKER_MAX, CATEGORY_MAX = 120, 32, 24, 24
ANSWERS: Final = range(1, 13)
ANSWER_ITEMS: Final = range(1, 9)
CATEGORIES: Final = range(1, 25)
PENALTY_MAX: Final = range(1, 21)
DEFAULTS: Final = {"at": None, "speaker": None, "press": True, "evidence": None,
                   "penalty": None, "penalty_max": 5, "cost": 1}
KEY_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,31}", re.ASCII)
# The loss display (01 §6.2, §6.4): hatch, shrink, hold; reduced motion holds for 500 ms.
LOSS_HATCH_S, LOSS_SHRINK_S, LOSS_HOLD_S, REDUCED_HOLD_S = 0.5, 0.3, 0.2, 0.5
LOSS_S: Final = 1.0
EPSILON: Final = 1e-6                # F24 07 I-6's inclusive boundary under float sums
W173_NAMES: Final = 3                # form 1 names up to 3 items, then "and N more"
_TEXT_RULE = f"a statement is 1 to {TEXT_MAX} characters on one line."
_CATEGORY_RULE = f"a category name is 1 to {CATEGORY_MAX} characters on one line."

# Layout (canvas units; 01 §6.1, 04 §6.6).
BOX_MAX_W, BOX_PAD, NAME_GAP, BUTTONS_GAP = 1000, 24, 8, 16
BUTTON_W, BUTTON_SPACING = 226, 16
PANEL_W, PANEL_PAD, PANEL_LABEL_GAP, BAR_X, BAR_W, BAR_H = 432, 16, 8, 20, 392, 24
NOTCH_W, NOTCHES_UP_TO = 2, 10
BACKING_W, VIEW_INSET, VIEW_MIN = 840, 16, (640, 400)
BACK_W = 180

Rect = tuple[float, float, float, float]


# --- Data ------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Testimony:
    """Checked arguments, parsed once in ``start`` or by ``outcome_for``."""
    keys: tuple[str, ...]                    # testimony order
    texts: tuple[str, ...]
    answer: tuple[tuple[str, tuple[str, ...]], ...]   # statement → items, written order
    start: int                               # index of ``at``; 0 for None
    speaker: str | None
    press: bool
    evidence: tuple[str, ...] | None         # written order
    penalty: str | None
    penalty_max: int
    cost: int


@dataclass(frozen=True, slots=True)
class TestimonyLayout:
    """Testimony mode in canvas units; rectangles are ``(x, y, w, h)``, anchors ``(x, y)``."""
    panel: Rect | None                       # None without ``penalty``
    label_at: tuple[float, float]            # the bar label's topleft
    value_at: tuple[float, float]            # the "<value> / <max>" topright
    bar: Rect
    box: Rect
    name_at: tuple[float, float]             # the speaker's topleft
    count_at: tuple[float, float]            # the "<n> / <count>" topright
    statement: Rect                          # 3 statement lines
    buttons: tuple[Rect, ...]                # present buttons, left to right


@dataclass(frozen=True, slots=True)
class PickerLayout:
    backing: Rect
    view: Rect                               # the CodexView's box
    back: Rect


# --- The checks (R1–R14) ---------------------------------------------------------------------

def _hint(text: str, written: object, names: Sequence[str]) -> str:
    hint = closest(written, names) if type(written) is str else None
    return text + (f' Did you mean "{hint}"?' if hint is not None else "")


def _key_echo(key: object) -> str:
    return quoted(key) if type(key) is str else value_echo(key)


def _items(value: object) -> tuple[object, ...]:
    """An answer value's names: a single name, or the list's entries."""
    if type(value) is str:
        return (value,)
    if type(value) is list:
        return tuple(value)
    return ()


def _whole(v: object, allowed: range) -> bool:
    return type(v) is int and v in allowed


def _text_problem(key: str, text: object) -> str | None:
    """R3: a statement's text, with ``rule_text.line_problem``'s forms."""
    form = line_problem(text, 1, TEXT_MAX)
    if form is None:
        return None
    said = f"the statement {quoted(key)}"
    if form == "not text":
        return f"{said} is {kind_words(text)}, not text; {_TEXT_RULE}"
    if form == "empty":
        return f"{said} is empty; {_TEXT_RULE}"
    if form == "length":
        return f"{said} is {len(text):,} characters long; {_TEXT_RULE}"   # type: ignore[arg-type]
    if form in ("breaks", "hidden"):
        return f"{said} has a line break or hidden character; {_TEXT_RULE}"
    return f"{said} starts or ends with a space. Remove the space."


def _testimony_problem(testimony: object) -> str | None:
    """R1–R3."""
    if type(testimony) is not dict:
        return ('testimony must be a dictionary of statements, e.g. {"gate": "The gate was '
                f'locked."}}, but it is {kind_words(testimony)}.')
    if len(testimony) not in STATEMENTS:
        return (f"testimony has {len(testimony):,} statements; a testimony has 1 to "
                f"{STATEMENTS[-1]}.")
    for key in testimony:
        if type(key) is not str or KEY_RE.fullmatch(key) is None:
            return (f"{_key_echo(key)} can't be a statement key; use letters, digits, and _, "
                    "starting with a letter.")
    for key, text in testimony.items():
        found = _text_problem(key, text)
        if found is not None:
            return found
    return None


def _answer_problem(answer: object, keys: Sequence[str]) -> str | None:
    """R4–R6."""
    if type(answer) is not dict:
        return ("answer must be a dictionary of statements and items, e.g. "
                f'{{"gate": "brass_key"}}, but it is {kind_words(answer)}.')
    if len(answer) not in ANSWERS:
        return (f"answer names {len(answer):,} statements; an answer names 1 to "
                f"{ANSWERS[-1]}.")
    for key in answer:
        if key not in keys:
            return _hint(f"answer names the statement {_key_echo(key)}, which isn't in "
                         "testimony.", key, keys)
    for key, value in answer.items():
        if type(value) is str or (type(value) is list and len(value) in ANSWER_ITEMS
                                  and all(type(name) is str for name in value)):
            continue
        return (f"the answer for {quoted(key)} must be an item name or a list of 1 to "
                f"{ANSWER_ITEMS[-1]} item names, but it is {value_echo(value)}.")
    return None


def _speaker_problem(speaker: object) -> str | None:
    """R8."""
    if speaker is None:
        return None
    form = line_problem(speaker, 1, SPEAKER_MAX)
    if form is None:
        return None
    if form == "edge":
        return (f"speaker {quoted(speaker)} starts or ends with a space. "  # type: ignore[arg-type]
                "Remove the space.")
    return (f"speaker must be None or a name of 1 to {SPEAKER_MAX} characters on one line, "
            f"but it is {value_echo(speaker)}.")


def _evidence_problem(evidence: object) -> str | None:
    """R10."""
    if evidence is None:
        return None
    if type(evidence) is not list:
        return (f"evidence must be None or a list of 1 to {CATEGORIES[-1]} category names, "
                f'e.g. ["Evidence"], but it is {value_echo(evidence)}.')
    if len(evidence) not in CATEGORIES:
        return (f"evidence lists {len(evidence):,} categories; it takes 1 to "
                f"{CATEGORIES[-1]}.")
    for category in evidence:
        form = line_problem(category, 1, CATEGORY_MAX)
        if form == "edge":
            return (f"evidence names the category {quoted(category)}, which starts or ends "
                    "with a space. Remove the space.")
        if form is not None:
            return f"evidence names the category {value_echo(category)}; {_CATEGORY_RULE}"
    return None


def _penalty_problem(args: dict) -> str | None:
    """R11, its three forms."""
    penalty = args.get("penalty", DEFAULTS["penalty"])
    if penalty is not None and type(penalty) is not str:
        return f"penalty must be None or a meter's name, but it is {value_echo(penalty)}."
    top = args.get("penalty_max", DEFAULTS["penalty_max"])
    if not _whole(top, PENALTY_MAX):
        return (f"penalty_max must be a whole number from 1 to {PENALTY_MAX[-1]}, but it is "
                f"{value_echo(top)}.")
    cost = args.get("cost", DEFAULTS["cost"])
    if not _whole(cost, range(top + 1)):
        return (f"cost must be a whole number from 0 to penalty_max ({top}), but it is "
                f"{value_echo(cost)}.")
    return None


def problem(args: dict) -> str | None:
    """R1–R11 in F25 ``04`` §5.1's order (within a rule, written order): the first problem's
    reason, or None. No side effects; never raises for frozen values."""
    testimony = args.get("testimony")
    found = _testimony_problem(testimony)
    if found is not None:
        return found
    keys = tuple(testimony)                  # type: ignore[arg-type]
    found = _answer_problem(args.get("answer"), keys)
    if found is not None:
        return found
    at = args.get("at", DEFAULTS["at"])
    if at is not None and at not in keys:
        return _hint(f"at must be None or a statement in testimony, but it is "
                     f"{value_echo(at)}.", at, keys)
    found = _speaker_problem(args.get("speaker", DEFAULTS["speaker"]))
    if found is not None:
        return found
    press = args.get("press", DEFAULTS["press"])
    if type(press) is not bool:
        return f"press must be True or False, but it is {value_echo(press)}."
    return _evidence_problem(args.get("evidence", DEFAULTS["evidence"])) or \
        _penalty_problem(args)


def _answer_pairs(args: dict) -> list[tuple[object, object]]:
    """(statement key, item name) for every answer item, in written order; lenient."""
    answer = args.get("answer")
    if type(answer) is not dict:
        return []
    return [(key, name) for key, value in answer.items() for name in _items(value)]


def story_problem(args: dict, story: StoryNames) -> str | None:
    """R12–R14 against the story's declared names: the first problem's reason, or None.
    Meant for arguments that pass ``problem``; never raises for others."""
    pairs = _answer_pairs(args)
    for key, name in pairs:                  # R12
        if type(name) is not str:
            continue
        if name in story.tips:
            return (f"the answer for {_key_echo(key)} is {quoted(name)}, which is a tip; only "
                    "items can be presented.")
        if name not in story.items:
            return _hint(f"the answer for {_key_echo(key)} is {quoted(name)}, but there is no "
                         f"item named {quoted(name)}.", name, story.items)
    penalty = args.get("penalty", DEFAULTS["penalty"])
    if type(penalty) is str and penalty not in story.meters:      # R13
        return _hint(f"penalty is {quoted(penalty)}, but there is no meter named "
                     f"{quoted(penalty)}.", penalty, story.meters)
    evidence = args.get("evidence", DEFAULTS["evidence"])
    if type(evidence) is not list:
        return None
    categories = [key for key, _ in story.item_categories]
    for category in evidence:                # R14, form 1
        if type(category) is str and category not in categories:
            return _hint(f"evidence names the category {quoted(category)}, but no item is in "
                         "a category by that name.", category, categories)
    home = {name: key for key, names in story.item_categories for name in names}
    for key, name in pairs:                  # R14, form 2 (F25 07 I-11, C1)
        category = home.get(name) if type(name) is str else None
        if category is not None and category not in evidence:
            return (f"the answer for {_key_echo(key)} is {quoted(name)}, which is in "
                    f"{quoted(category)}, not in evidence, so it can never be presented.")
    return None


# --- Parsing, judging, and outcomes ----------------------------------------------------------

def parse(args: dict) -> Testimony:
    """The checked arguments as a ``Testimony``. The arguments must pass ``problem``."""
    assert problem(args) is None, "parse() needs checked arguments"
    get = args.get
    keys = tuple(args["testimony"])
    at = get("at", DEFAULTS["at"])
    evidence = get("evidence", DEFAULTS["evidence"])
    return Testimony(
        keys=keys, texts=tuple(args["testimony"].values()),
        answer=tuple((key, tuple(_items(value))) for key, value in args["answer"].items()),
        start=0 if at is None else keys.index(at),
        speaker=get("speaker", DEFAULTS["speaker"]), press=get("press", DEFAULTS["press"]),
        evidence=None if evidence is None else tuple(evidence),
        penalty=get("penalty", DEFAULTS["penalty"]),
        penalty_max=get("penalty_max", DEFAULTS["penalty_max"]),
        cost=get("cost", DEFAULTS["cost"]))


def judge(t: Testimony, statement: int, item: str) -> bool:
    """Whether ``item`` contradicts statement number ``statement`` (an index into
    ``t.keys``)."""
    return item in dict(t.answer).get(t.keys[statement], ())


def result_of(t: Testimony, statement: int, item: str | None) -> dict:
    """The ``into`` value: a press when ``item`` is None, else a judged present."""
    if item is None:
        return {"action": "press", "statement": t.keys[statement], "evidence": None,
                "correct": False}
    return {"action": "present", "statement": t.keys[statement], "evidence": item,
            "correct": judge(t, statement, item)}


def fixed_outcome(t: Testimony) -> Outcome:
    """``outcome_for``'s answer for both kinds (F25 ``04`` §6.4, TR-F25-03): the correct
    present of the first answered statement in testimony order, with its first item, and no
    changes. ``answer`` is never empty (R4), so this never returns None."""
    answer = dict(t.answer)
    for index, key in enumerate(t.keys):
        if key in answer:
            return Outcome(result_of(t, index, answer[key][0]), ())
    raise AssertionError("a checked answer names a testimony statement")


# --- W173 ------------------------------------------------------------------------------------

def presentable(t: Testimony, held: Sequence[str], story: StoryNames) -> tuple[str, ...]:
    """The held items the picker lists, in ``held``'s order: those in ``evidence``'s
    categories, or every held item when ``evidence`` is None."""
    if t.evidence is None:
        return tuple(held)
    wanted = frozenset(t.evidence)
    home = {name: key for key, names in story.item_categories for name in names}
    return tuple(name for name in held if home.get(name) in wanted)


def w173_text(t: Testimony, held: Sequence[str], story: StoryNames) -> str | None:
    """W173's text (F25 ``01`` §5.4, ``04`` §6.1 step 5), or None. Form 2: the picker would
    be empty. Form 1: it would list none of the answer's items."""
    allowed = presentable(t, held, story)
    if not allowed:
        where = ("any category" if t.evidence is None
                 else " or ".join(quoted(category) for category in t.evidence))
        return (f"present_evidence has no evidence to show: the player holds no items in "
                f"{where}. Unlock one before this line, or change evidence.")
    names = list(dict.fromkeys(name for _, items in t.answer for name in items))
    if set(names) & set(allowed):
        return None
    shown = ", ".join(names[:W173_NAMES])
    if len(names) > W173_NAMES:
        shown += f", and {len(names) - W173_NAMES} more"
    return (f"present_evidence can't be won here: the player holds none of the answer's items "
            f"({shown}). Unlock one before this line, or change answer.")


# --- Geometry --------------------------------------------------------------------------------

def _rect(area: object) -> Rect:
    """An area as ``(x, y, w, h)``: a 4-tuple, or a ``Box``-like object."""
    if hasattr(area, "x"):
        return (area.x, area.y, area.w, area.h)       # type: ignore[attr-defined]
    x, y, w, h = area                                 # type: ignore[misc]
    return (x, y, w, h)


def testimony_layout(area: object, *, label_pitch: float, name_pitch: float,
                     statement_pitch: float, button_h: float, n_buttons: int,
                     penalty: bool) -> TestimonyLayout:
    """Testimony mode in F23's content ``area`` (F25 ``04`` §6.6). The pitches are the
    scaled fonts' line sizes; ``button_h`` is F10's button height at the text scale."""
    assert 1 <= n_buttons <= 4
    ax, ay, aw, ah = _rect(area)
    w = min(BOX_MAX_W, aw)
    h = (BOX_PAD + name_pitch + NAME_GAP + 3 * statement_pitch + BUTTONS_GAP + button_h
         + BOX_PAD)
    box = (ax + (aw - w) / 2, ay + ah - h, w, h)
    bx, by, _, _ = box
    statement = (bx + BOX_PAD, by + BOX_PAD + name_pitch + NAME_GAP, w - 2 * BOX_PAD,
                 3 * statement_pitch)
    row_w = n_buttons * BUTTON_W + (n_buttons - 1) * BUTTON_SPACING
    left = bx + (w - row_w) / 2
    top = by + h - BOX_PAD - button_h
    buttons = tuple((left + i * (BUTTON_W + BUTTON_SPACING), top, BUTTON_W, button_h)
                    for i in range(n_buttons))
    panel_h = PANEL_PAD + label_pitch + PANEL_LABEL_GAP + BAR_H + PANEL_PAD
    panel = (ax, ay, PANEL_W, panel_h)
    bar = (ax + BAR_X, ay + PANEL_PAD + label_pitch + PANEL_LABEL_GAP, BAR_W, BAR_H)
    if penalty:
        assert by >= ay + panel_h, "the testimony box overlaps the penalty panel"
    return TestimonyLayout(
        panel=panel if penalty else None, label_at=(ax + BAR_X, ay + PANEL_PAD),
        value_at=(ax + BAR_X + BAR_W, ay + PANEL_PAD), bar=bar, box=box,
        name_at=(bx + BOX_PAD, by + BOX_PAD), count_at=(bx + w - BOX_PAD, by + BOX_PAD),
        statement=statement, buttons=buttons)


def picker_layout(area: object, *, button_h: float) -> PickerLayout:
    """Picker mode in F23's content ``area`` (F25 ``04`` §6.6): the backing panel, 840 wide
    and centered; the view inset by 16 (at least 640×400); Back at the bottom left."""
    ax, ay, aw, ah = _rect(area)
    backing = (ax + (aw - BACKING_W) / 2, ay, BACKING_W, ah)
    view = (backing[0] + VIEW_INSET, ay + VIEW_INSET, BACKING_W - 2 * VIEW_INSET,
            ah - 2 * VIEW_INSET)
    assert view[2] >= VIEW_MIN[0] and view[3] >= VIEW_MIN[1], "the picker is too small"
    return PickerLayout(backing=backing, view=view,
                        back=(ax, ay + ah - button_h, BACK_W, button_h))


def bar_geometry(bar: Rect, value: float, penalty_max: int) -> tuple[Rect, tuple[Rect, ...]]:
    """(fill box, notch boxes); value clamped to 0–penalty_max; notches only when ≤ 10.
    A notch is 2 wide, centered on each interior unit boundary (``penalty_max − 1``)."""
    x, y, w, h = bar
    shown = min(max(value, 0), penalty_max)
    fill = (x, y, w * shown / penalty_max, h)
    if penalty_max > NOTCHES_UP_TO:
        return fill, ()
    step = w / penalty_max
    return fill, tuple((x + k * step - NOTCH_W / 2, y, NOTCH_W, h)
                       for k in range(1, penalty_max))


def hatch_rects(seg: Rect, *, line: float = 3, gap: float = 8) -> tuple[Rect, ...]:
    """The loss hatch over ``seg``: diagonal lines ``gap`` apart, each drawn as ``line`` ×
    ``line`` blocks stepped up and to the right; only whole blocks inside ``seg`` (Canvas and
    Painter have no line primitive). At most about (w + h) / gap × h / line blocks."""
    x, y, w, h = seg
    if w < line or h < line:
        return ()
    rows = int(h // line)
    right, bottom = x + w, y + h
    rects = []
    start = x - rows * line
    k = 0
    while start + k * gap < right:
        sx = start + k * gap
        for i in range(rows):
            bx = sx + i * line
            if bx >= x and bx + line <= right:
                rects.append((bx, bottom - (i + 1) * line, line, line))
        k += 1
    return tuple(rects)


def ease_in_out(t: float) -> float:
    """ui-system §5's ease: (1 − cos πt) / 2, for t clamped to 0–1."""
    t = min(max(t, 0.0), 1.0)
    return (1 - math.cos(math.pi * t)) / 2


__all__ = ["ANSWERS", "ANSWER_ITEMS", "CATEGORIES", "CATEGORY_MAX", "DEFAULTS", "EPSILON",
           "KEY_MAX", "KEY_RE", "LOSS_HATCH_S", "LOSS_HOLD_S", "LOSS_S", "LOSS_SHRINK_S",
           "PENALTY_MAX", "PickerLayout", "REDUCED_HOLD_S", "SPEAKER_MAX", "STATEMENTS",
           "TEXT_MAX", "Testimony", "TestimonyLayout", "bar_geometry", "ease_in_out",
           "fixed_outcome", "hatch_rects", "judge", "parse", "picker_layout", "presentable",
           "problem", "result_of", "story_problem", "testimony_layout", "w173_text"]

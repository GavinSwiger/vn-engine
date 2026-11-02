"""The poem game's pure rules (F24 ``04`` §4.2, §5.1, §6.2–§6.5).

Why this module exists: everything about a poem that can be decided without a window lives
here, so it can be tested directly and shared by the hooks (``check_args``,
``check_story``, ``outcome_for``) and the playable session (F24-3): the argument checks
R1–R13, parsing, scoring, results and meter changes, the fixed test and skipped outcomes,
page draws, the double-press guard, and the page geometry.

Pure: no clock, no randomness of its own (``new_page`` takes ``ctx.random.shuffle``), no
I/O. Imports only ``engine.minigames.api``, the shared ``bundled.rule_text`` (the echo
helpers and the text rule, moved there unchanged by F25 ``07`` I-5), and the stdlib
(AC-F24-01). The checks run on author values that F23 has already frozen; they never raise
and never change the arguments. Every refusal text is a draft for the narrative designer
(F24 ``01`` §5.3).
"""

import math
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from engine.minigames.api import MeterChange, Outcome, add_points, closest
from engine.minigames.bundled.rule_text import (ECHO_MAX, kind_words, line_problem, quoted,
                                                value_echo)

RESULTS: Final = ("winner", "totals", "words")
WORDS_MAX, WORD_MAX, NAMES_MAX, SCORE_MAX = 2000, 24, 16, 99
ROUNDS: Final = range(1, 51)
PAGE_WORDS: Final = range(2, 13)
NAME_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}", re.ASCII)   # F22 meter names
DEFAULTS: Final = {"rounds": 20, "page_words": 10, "to_points": True, "result": "winner"}
PICK_GUARD_S: Final = 0.2            # PR-F24-16: picks this soon after a page change wait
GUARD_EPSILON: Final = 1e-6          # F24 07 I-6: the boundary is inclusive under float sums
LINE_PITCH: Final = 1.4              # ui-system: a line's pitch is round(1.4 × size)
_WORD_RULE = "a word is 1 to 24 characters on one line."


# --- Data ------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Entry:
    word: str
    scores: tuple[tuple[str, int], ...]      # written order; shorthand → ((name, 1),); zeros kept


@dataclass(frozen=True, slots=True)
class Poem:
    """Checked arguments, parsed once in ``start`` or by ``outcome_for``."""
    entries: tuple[Entry, ...]               # list order
    rounds: int
    page_words: int
    to_points: bool
    result: str
    stickers: bool = False


@dataclass(frozen=True, slots=True)
class PageLayout:
    """The page geometry in canvas units; rectangles are plain ``(x, y, w, h)`` tuples."""
    page: tuple[float, float, float, float]
    margin_x: float
    rules: tuple[float, ...]                 # y of each 1-unit rule
    counter_at: tuple[float, float]          # the counter's topright anchor
    cells: tuple[tuple[float, float, float, float], ...]   # one per slot, column-wide
    label_width: float                       # column width − 64


# --- The checks (R1–R13) ---------------------------------------------------------------------

def _word_problem(word: object) -> str | None:
    """R3, its four forms: empty, too long, line break or hidden character, space at an end
    (``rule_text.line_problem``'s keys)."""
    form = line_problem(word, 1, WORD_MAX)
    if form is None:
        return None
    if form == "not text":                   # frozen dict keys are text; defensive only
        return f"the word {value_echo(word)} isn't text; {_WORD_RULE}"
    if form == "empty":
        return f'the word "" is empty; {_WORD_RULE}'
    if form == "length":
        return f"{quoted(word)} is {len(word):,} characters long; {_WORD_RULE}"
    if form in ("breaks", "hidden"):
        return f"the word {quoted(word)} has a line break or hidden character; {_WORD_RULE}"
    return f"the word {quoted(word)} starts or ends with a space. Remove the space."


def _name_problem(word: str, name: object) -> str | None:
    if type(name) is str and NAME_RE.fullmatch(name) is not None:
        return None
    shown = quoted(name) if type(name) is str else value_echo(name)
    return f"{quoted(word)} scores toward {shown}, which can't be a meter name."


def _scores_problem(word: str, scores: object) -> str | None:
    """R5–R7 for one word's scores."""
    if type(scores) is str:
        return _name_problem(word, scores)
    if type(scores) is not dict:
        return (f'the scores for {quoted(word)} must be a dictionary such as {{"sayori": 3}}, '
                f"or one meter's name, but they are {kind_words(scores)}.")
    if len(scores) > NAMES_MAX:
        return (f"{quoted(word)} scores toward {len(scores):,} meters; a word can score "
                f"toward up to {NAMES_MAX}.")
    for name, score in scores.items():
        problem = _name_problem(word, name)
        if problem is not None:
            return problem
        if type(score) is not int or not 0 <= score <= SCORE_MAX:
            return (f"{quoted(word)} gives {name} {value_echo(score)}; a score is a whole number "
                    f"from 0 to {SCORE_MAX}.")
    return None


def _whole(v: object, allowed: range) -> bool:
    return type(v) is int and v in allowed


def problem(args: dict) -> str | None:
    """R1–R12 in F24 ``01`` §5.3's order: the first problem's reason, or None. No side
    effects; never raises for frozen values."""
    words = args.get("words")
    if type(words) is not dict:
        return ("words must be a dictionary of words and their scores, e.g. "
                f'{{"sunshine": {{"sayori": 3}}}}, but it is {kind_words(words)}.')
    if len(words) > WORDS_MAX:
        return f"words has {len(words):,} words; the poem game takes up to {WORDS_MAX:,}."
    seen: dict[str, str] = {}
    for word, scores in words.items():
        found = _word_problem(word)
        if found is not None:
            return found
        folded = word.casefold()
        earlier = seen.get(folded)
        if earlier is not None:
            return f"{quoted(earlier)} and {quoted(word)} are the same word. Keep one."
        seen[folded] = word
        found = _scores_problem(word, scores)
        if found is not None:
            return found
    rounds = args.get("rounds", DEFAULTS["rounds"])
    if not _whole(rounds, ROUNDS):
        return f"rounds must be a whole number from 1 to 50, but it is {value_echo(rounds)}."
    page_words = args.get("page_words", DEFAULTS["page_words"])
    if not _whole(page_words, PAGE_WORDS):
        return ("page_words must be a whole number from 2 to 12, but it is "
                f"{value_echo(page_words)}.")
    need = rounds + page_words - 1
    if len(words) < need:
        return (f"{rounds} rounds of {page_words} words need at least {need:,} words, but "
                f"words has {len(words):,}. Add words, or lower rounds or page_words.")
    to_points = args.get("to_points", DEFAULTS["to_points"])
    if type(to_points) is not bool:
        return f"to_points must be True or False, but it is {value_echo(to_points)}."
    result = args.get("result", DEFAULTS["result"])
    if type(result) is not str or result not in RESULTS:
        text = (f'result must be "winner", "totals", or "words", but it is '
                f"{value_echo(result)}.")
        hint = closest(result, RESULTS) if type(result) is str else None
        return text + (f' Did you mean "{hint}"?' if hint is not None else "")
    return None


def _named(scores: object) -> Iterator[str]:
    if type(scores) is str:
        yield scores
    elif type(scores) is dict:
        yield from (name for name in scores if type(name) is str)


def meter_problem(args: dict, meters: Sequence[str]) -> str | None:
    """R13: the first name, by word in list order and name in written order, that isn't a
    declared meter, with F22's did-you-mean (``closest``). Meant for arguments that pass
    ``problem``; never raises for others."""
    words = args.get("words")
    if type(words) is not dict:
        return None
    declared = frozenset(meters)
    for word, scores in words.items():
        for name in _named(scores):
            if name not in declared:
                text = (f"{quoted(word) if type(word) is str else value_echo(word)} scores "
                        f"toward {quoted(name)}, but there is no meter named {quoted(name)}.")
                hint = closest(name, meters)
                return text + (f' Did you mean "{hint}"?' if hint is not None else "")
    return None


# --- Parsing, scoring, and outcomes ----------------------------------------------------------

def parse(args: dict) -> Poem:
    """The checked arguments as a ``Poem``. The arguments must pass ``problem``."""
    assert problem(args) is None, "parse() needs checked arguments"
    entries = []
    for word, scores in args["words"].items():
        pairs = ((scores, 1),) if type(scores) is str else tuple(scores.items())
        entries.append(Entry(word, pairs))
    get = args.get
    return Poem(tuple(entries), get("rounds", DEFAULTS["rounds"]),
                get("page_words", DEFAULTS["page_words"]),
                get("to_points", DEFAULTS["to_points"]), get("result", DEFAULTS["result"]))


def named_meters(poem: Poem, declared: Sequence[str]) -> tuple[str, ...]:
    """Meters named anywhere in the list (zeros included), in declaration order."""
    named = {name for entry in poem.entries for name, _ in entry.scores}
    return tuple(m for m in declared if m in named)


def score(poem: Poem, picked: Sequence[int], meters: Sequence[str]) -> dict[str, int]:
    """The totals of ``picked`` (entry indices) for each of ``meters``, in their order."""
    totals = dict.fromkeys(meters, 0)
    for index in picked:
        for name, points in poem.entries[index].scores:
            totals[name] += points
    return totals


def result_of(poem: Poem, picked: Sequence[int], totals: dict[str, int]) -> object:
    """The ``into`` value: the winner (first declared on a tie; None when all are 0), the
    totals dictionary, or the picked words in pick order."""
    if poem.result == "totals":
        return dict(totals)
    if poem.result == "words":
        return [poem.entries[index].word for index in picked]
    winner, best = None, 0
    for name, total in totals.items():
        if total > best:
            winner, best = name, total
    return winner


def changes_of(poem: Poem, totals: dict[str, int]) -> tuple[MeterChange, ...]:
    """One ``+=`` per meter with a total above 0, in the totals' (declaration) order."""
    if not poem.to_points:
        return ()
    return tuple(add_points(name, total) for name, total in totals.items() if total > 0)


def fixed_outcome(kind: str, poem: Poem, declared: Sequence[str]) -> Outcome:
    """``outcome_for``'s answer (F24 ``04`` §6.4): ``"test"`` scores the first ``rounds``
    words in list order; ``"skipped"`` is the result shape with zero totals and no changes."""
    meters = named_meters(poem, declared)
    if kind == "test":
        picked = range(poem.rounds)
        totals = score(poem, picked, meters)
        return Outcome(result_of(poem, picked, totals), changes_of(poem, totals))
    if kind == "skipped":
        return Outcome(result_of(poem, (), dict.fromkeys(meters, 0)), ())
    raise ValueError(f"unknown outcome kind {kind!r}")


# --- Playing ---------------------------------------------------------------------------------

def new_page(remaining: list[int], page_words: int,
             shuffle: Callable[[list], list]) -> list[int]:
    """The next page: one ``shuffle`` of a copy of ``remaining`` (TR-F24-01), cut to
    ``page_words``. ``remaining`` is not changed."""
    assert len(remaining) >= page_words, "a page needs page_words remaining words"
    return list(shuffle(list(remaining))[:page_words])


def pick_ignored(since_change: float) -> bool:
    """PR-F24-16: a pick this soon after a page change is ignored. ``since_change`` sums the
    frames' ``dt`` (``inf`` before the first pick); 12 frames of 1/60 s count as 200 ms."""
    return since_change < PICK_GUARD_S - GUARD_EPSILON


def scaled(size: int, scale: float) -> int:
    """A token text size at F16's text scale (0.5 rounds up, as ``ui.layouts.scaled``)."""
    return max(1, math.floor(size * scale + 0.5))


def line_pitch(size: int) -> int:
    """The line pitch of text at ``size``: ui-system's round(1.4 × size), the rule F23's
    frame and every F10 layout use (45 at 32, 67 at 48; AC-F24-12, 13)."""
    return round(LINE_PITCH * size)


def clamp_size(value: object, lo: int, hi: int, default: int) -> int:
    """A token number clamped to ``lo``–``hi`` (C3: API 1.0 tokens have no declared range);
    anything that isn't a number gives ``default``."""
    if type(value) not in (int, float) or value != value:
        return default
    return max(lo, min(hi, round(value)))


def page_layout(area: tuple[float, float, float, float], *, max_width: float, n: int,
                pitch: float, counter_h: float = 0.0) -> PageLayout:
    """The page in F23's content ``area`` for ``n`` slots (F24 ``04`` §6.5, ``07`` I-7).
    ``pitch`` is the word font's line size and ``counter_h`` the counter's, both scaled; the
    rows start below the counter's line box."""
    assert n >= 1
    ax, ay, aw, ah = area
    pw = min(max_width, aw)
    page = (ax + (aw - pw) / 2, ay + 8, pw, ah - 16)
    px, py, _, ph = page
    right, page_bottom = px + pw, py + ph
    margin_x = px + 72
    col = (right - margin_x) / 2
    rows = math.ceil(n / 2)
    counter_at = (right - 32, py + 24)
    top, bottom = py + 80, page_bottom - 24
    floor = max(top, counter_at[1] + counter_h)
    h = min(max(48, pitch + 8), (bottom - floor) / rows)
    block_y = max(floor, top + (bottom - top - rows * h) / 2)
    cells = []
    for i in range(n):
        column, row = (0, i) if i < rows else (1, i - rows)
        cells.append((margin_x + column * col, block_y + row * h, col, h))
    base = block_y + h - 6
    first = math.ceil((py + 64 - base) / h)
    last = math.floor((page_bottom - 8 - base) / h)
    rules = tuple(base + k * h for k in range(first, last + 1))
    return PageLayout(page=page, margin_x=margin_x, rules=rules, counter_at=counter_at,
                      cells=tuple(cells), label_width=col - 64)


__all__ = ["DEFAULTS", "ECHO_MAX", "Entry", "NAMES_MAX", "NAME_RE", "PAGE_WORDS",
           "LINE_PITCH", "PICK_GUARD_S", "PageLayout", "Poem", "RESULTS", "ROUNDS", "SCORE_MAX",
           "WORDS_MAX", "WORD_MAX", "changes_of", "clamp_size", "fixed_outcome", "line_pitch",
           "meter_problem", "named_meters", "new_page", "page_layout", "parse", "pick_ignored",
           "problem", "result_of", "scaled", "score"]

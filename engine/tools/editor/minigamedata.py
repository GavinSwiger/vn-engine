"""Studio's minigame setup data: the bundled minigames' ``define`` literals as models, and
the Minigame form's fields (F47 ``01-design.md`` §4.6, PR-F47-23, PR-F47-24; ``04`` §3.1,
P2-E; AC-F47-42, 43, 44, 46).

Why this module exists: the poem words, the cross-examination's testimony and answer, the
phone chat and the puzzle room are Python literals in a ``define`` (``docs/minigames.md``),
which a non-programmer can't be asked to type. Studio shows a setup panel per game instead;
this module turns each literal into a model the panel edits and writes the model back as a
plan, like the Database's (``declplan``). Pure: no Tk, no pygame, never runs author code
(``ast.literal_eval`` only; plugins are read with ``ast``).

- **Reading.** ``scan(texts)`` finds every top-level ``define`` whose value is a literal and
  that is a minigame's data: named by a ``minigame`` line's argument (``USE_KINDS``), else by
  its shape (``DataSet.guessed``). ``DataSet.model`` is the panel's model, or None when the
  literal is written in a way the panel can't hold (Studio offers **Edit as script**).
  Kinds: ``POEM`` (``PoemWords``), ``TESTIMONY`` and ``ANSWER`` (put together as one
  ``Evidence`` by ``evidence_of``), ``CHAT`` (a tuple of ``Step``/``AskStep``), ``ROOM``
  (``Room``).
- **Round trip.** A write whose model equals the one read changes nothing (``None``), so
  an unchanged ``define`` stays byte-identical. A changed one is rewritten as a whole in the
  layout ``docs/minigames.md`` uses (``define_lines``; the docs' examples come back
  unchanged), keeping each word's meter order, each hotspot's field order and the
  shorthand ``"yuri"`` while its row isn't edited. Comments inside a rewritten literal are
  lost (``DataSet.comments`` lets Studio say so first).
- **Writing.** ``plan_edit``, ``plan_evidence`` and ``plan_new`` return a ``DataPlan``: a
  ``scriptedit.Plan`` (one ``FilePlan`` per file, so one undo step per file) with line
  guards; ``verify`` re-checks it against the live texts right before it is applied and
  reads the written values back. A model with a problem (``problem``) is refused with the
  problem's text, so Studio never writes data the game would refuse.
- **Checks.** ``problem(kind, model)`` mirrors the bundled rules modules' data checks
  (``engine/minigames/bundled/*_rules.py``, which Studio may not import; ADR-0008).
  ``tests/tools/editor/test_minigamedata.py`` compares them case by case.
- **Minigame form.** ``form_fields(game, plugin_texts)``: the fields of a ``minigame`` line
  from the plugin's declared args (bundled: ``BUILTIN_FIELDS``, compared with the real
  plugins by the tests; a game's own plugin: read from its source). Required args pick a
  data set (``data_choices``), optional ones show their default, ``into`` picks a variable.
  ``read_call`` / ``call_line`` read and write the line; ``call_from_form`` builds it from
  the form's values, leaving out arguments still at their default, and refuses what
  ``form_problem`` sees (F53: a Lock code that doesn't fit its kind). The fields' hints are
  ``fieldhints.MINIGAME_HINTS`` (one table for every game).
"""

import ast
import io
import json
import keyword
import re
import tokenize
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

from engine.core.constants import CANVAS_SIZE
from engine.script.pluginsigs import plugin_sigs
from engine.tools.editor import declarations as dec
from engine.tools.editor.declplan import (BAD_NAME, DATABASE_HEADER, DATABASE_REF, NAME_CLASH,
                                          NO_MAIN, includes_database, problems)
from engine.tools.editor.files import MAIN_REF, include_line, include_position
from engine.tools.editor.forms import code_of
from engine.tools.editor.scriptedit import STALE, FilePlan, LineEdit, Plan, Refuse, apply_lines

# --- Kinds and tables --------------------------------------------------------------------------

POEM: Final = "poem"
TESTIMONY: Final = "testimony"
ANSWER: Final = "answer"
CHAT: Final = "chat"
ROOM: Final = "room"
GIFTS: Final = "gifts"                # F54
KINDS: Final = (POEM, TESTIMONY, ANSWER, CHAT, ROOM, GIFTS)
KIND_TITLES: Final[Mapping[str, str]] = {
    POEM: "Poem words", TESTIMONY: "Evidence", ANSWER: "Evidence answer",
    CHAT: "Phone chat", ROOM: "Puzzle room", GIFTS: "Gift table"}
# (minigame, argument) → the kind of data set it takes.
USE_KINDS: Final[Mapping[tuple[str, str], str]] = {
    ("poem_game", "words"): POEM, ("present_evidence", "testimony"): TESTIMONY,
    ("present_evidence", "answer"): ANSWER, ("phone_chat", "chat"): CHAT,
    ("puzzle_room", "room"): ROOM, ("gift_giving", "gifts"): GIFTS}
BUNDLED: Final = ("poem_game", "present_evidence", "phone_chat", "puzzle_room", "heartbeat",
                  "code_lock", "stay_still", "hand_game", "gift_giving")

INDENT: Final = "    "               # docs/minigames.md's layout: one level, closer indented
LINE_MAX: Final = 100                 # an answer, an ask or combine stays on one line up to this

# The bundled rules' limits (mirrored; the tests compare them with the rules modules).
WORDS_MAX, WORD_MAX, NAMES_MAX, SCORE_MAX = 2000, 24, 16, 99
WORDS_MIN: Final = 2                  # 1 round of 2 words; the check compares rounds
POINTS_PICK: Final = range(0, 4)      # the table's spinner (01 §4.6); typed values to 99 read
STATEMENTS_MAX, STATEMENT_KEY_MAX, STATEMENT_MAX, ANSWER_ITEMS_MAX = 12, 32, 120, 8
STEPS_MAX, TOTAL_MAX, ASKS_MAX, REPLIES_MAX, AFTER_MAX = 200, 1000, 20, 4, 20
MESSAGE_MAX, BREAKS_MAX, REPLY_MAX, SENDER_MAX, TIME_MAX = 300, 4, 80, 40, 20
HOTSPOTS_MAX, RECIPES_MAX, USE_MAX = 40, 40, 8
RECT_MIN, IMAGE_MAX, LABEL_MAX, CAPTION_MAX = 32, 64, 40, 80
CANVAS: Final = CANVAS_SIZE
METER_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}", re.ASCII)
STATEMENT_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,31}", re.ASCII)
CHAT_ID_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}", re.ASCII)
HOTSPOT_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}", re.ASCII)
ROOM_KEYS: Final = ("background", "hotspots", "combine")
FIELDS: Final = ("rect", "label", "look", "take", "use", "nope", "exit", "after", "image")
IGNORE: Final = "ignore"

# Step kinds (the chat panel's "Add" menu, 01 §4.6).
FROM_CONTACT: Final = "contact"
FROM_ME: Final = "me"
FROM_OTHER: Final = "other"
TIME: Final = "time"
ASK: Final = "ask"
STEP_TITLES: Final[Mapping[str, str]] = {
    FROM_CONTACT: "Message from contact", FROM_ME: "Message from me",
    FROM_OTHER: "Message from someone else", TIME: "Time", ASK: "Reply point"}
DONT_REPLY: Final = "Don't reply"

# --- Texts (Studio's; drafts for the narrative designer) ---------------------------------------

CHANGED: Final = "Change {title} {name}"
ADDED: Final = "Add {title} {name}"
TEXT_RULE: Final = "{what} must be 1 to {hi} characters on one line, with no space at either end."
MESSAGE_RULE: Final = (f"{{what}} must be 1 to {MESSAGE_MAX} characters, with up to "
                       f"{BREAKS_MAX} line breaks and no space at either end.")
NAME_RULE: Final = "{what} can only use letters, digits and _, and must start with a letter."
TOO_MANY: Final = "{what} can have at most {most}."
TOO_FEW: Final = "{what} needs at least {least}."
SAME_TWICE: Final = "{what} is used twice. Each one needs its own name."
POINTS_RULE: Final = f"Points must be a whole number from 0 to {SCORE_MAX}."
NO_ANSWER: Final = "Pick the item that contradicts at least one statement."
ANSWER_GONE: Final = "The answer names {key}, which isn't one of the statements."
FOLLOW_ASK: Final = "A reply's follow-up can't be another reply point."
RECT_RULE: Final = (f"The area of {{name}} must be at least {RECT_MIN} × {RECT_MIN} and inside "
                    f"{CANVAS[0]} × {CANVAS[1]}.")
DOES_ONE: Final = "{name} can pick up an item, wait for an item, or leave, but only one of them."
LOOK_NOT: Final = "{name} picks something up or leaves at once, so it has no text to show."
NOPE_NEEDS_USE: Final = "{name} has a wrong-item text but waits for no item."
AFTER_GONE: Final = "{name} appears after {after}, which isn't a hotspot."
AFTER_NEVER: Final = "{name} appears after {after}, which is never picked up or used."
AFTER_CIRCLE: Final = "{name} appears after itself in a circle, so it never shows."
NO_EXIT: Final = "The room needs a way out: a hotspot that leaves."
COMBINE_RULE: Final = "{made} must be made from two different items, not from itself."
COMBINE_TWICE: Final = "Two recipes use {a} and {b}."
NEEDED: Final = "{label} is needed."
INTO_LABEL: Final = "Result goes to"
# F54 (gift_rules' limits and G texts, mirrored: ADR-0008).
ANY_GIFT: Final = "*"
REACTIONS: Final = ("loved", "liked", "neutral", "disliked")
REACTION_TITLES: Final[Mapping[str, str]] = {r: r.capitalize() for r in REACTIONS}
CHARACTERS_MAX: Final = 32
GIFTS_MAX: Final = 200
GIFT_POINTS: Final = (-10, 10)
GIFT_LINE_MAX: Final = 160


# --- Models ------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PoemWord:
    """One row of the poem table: the word and its points per meter, in written order.
    ``short``: written as a meter's name alone (``"yuri"``: 1 point), kept while the row
    is unchanged."""

    word: str
    scores: tuple[tuple[str, int], ...] = ()
    short: bool = False


@dataclass(frozen=True, slots=True)
class PoemWords:
    words: tuple[PoemWord, ...] = ()


@dataclass(frozen=True, slots=True)
class Statement:
    """One testimony line: its key (the story's name for it), the witness's text, and
    the items that contradict it (the answer)."""

    key: str
    text: str
    items: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Evidence:
    """A testimony and its answer. ``stray``: answer rows that name no statement, kept so
    nothing is lost (``problem`` reports them)."""

    statements: tuple[Statement, ...] = ()
    stray: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class Step:
    """A chat step that isn't a reply point: ``kind`` is ``FROM_CONTACT``, ``FROM_ME``,
    ``FROM_OTHER`` (``sender`` is the name) or ``TIME``."""

    kind: str
    text: str
    sender: str = ""


@dataclass(frozen=True, slots=True)
class Reply:
    """One button of a reply point: its key (the story's name for it), its text, and the
    steps that follow it."""

    key: str
    text: str
    follow: tuple[Step, ...] = ()


@dataclass(frozen=True, slots=True)
class AskStep:
    """A reply point. ``ignore``: None (no "Don't reply" button), True/False as written, or
    the button's own words."""

    name: str
    replies: tuple[Reply, ...] = ()
    ignore: bool | str | None = None

    kind = ASK


ChatStep = Step | AskStep


@dataclass(frozen=True, slots=True)
class Hotspot:
    """One hotspot: ``rect`` is ``(x, y, width, height)`` in screen units (1280 × 720);
    ``use`` the items that work here; ``exit`` None when not written. ``order``: the
    fields as written, kept when it is written back."""

    name: str
    rect: tuple[int, int, int, int]
    label: str
    look: str | None = None
    take: str | None = None
    use: tuple[str, ...] = ()
    nope: str | None = None
    exit: bool | None = None
    after: str | None = None
    image: str | None = None
    order: tuple[str, ...] = field(default=(), compare=False)


@dataclass(frozen=True, slots=True)
class Room:
    background: str
    hotspots: tuple[Hotspot, ...] = ()
    combine: tuple[tuple[str, str, str], ...] = ()     # (made, first item, second item)


@dataclass(frozen=True, slots=True)
class GiftRow:
    """One gift (F54): the item's name (``ANY_GIFT``, "*": any other gift), the reaction,
    the points, and the line (None: not written)."""

    item: str
    reaction: str
    points: int
    line: str | None = None


@dataclass(frozen=True, slots=True)
class GiftSection:
    """One character's gifts, in written order."""

    character: str
    rows: tuple[GiftRow, ...] = ()

    @property
    def any_row(self) -> GiftRow | None:
        return next((r for r in self.rows if r.item == ANY_GIFT), None)


@dataclass(frozen=True, slots=True)
class GiftTable:
    sections: tuple[GiftSection, ...] = ()


@dataclass(frozen=True, slots=True)
class DataSet:
    """A minigame's data ``define``: lines ``first``..``last`` of ``ref``. ``model`` is
    None when the panel can't hold how it is written. ``used``: the (minigame, argument)
    pairs that name it; ``guessed``: its kind comes from its shape, not a ``minigame`` line;
    ``comments``: it has comments, which a rewrite drops."""

    kind: str
    name: str
    ref: str
    first: int
    last: int
    lines: tuple[str, ...]
    model: object
    used: tuple[tuple[str, str], ...] = ()
    guessed: bool = False
    comments: bool = False


# --- Literals ----------------------------------------------------------------------------------

def _s(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def literal(value: object) -> str:
    """``value`` as script text: double-quoted strings, ``True``/``False``/``None``."""
    if value is None or type(value) is bool or type(value) is int:
        return repr(value)
    if type(value) is str:
        return _s(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_s(k)}: {literal(v)}" for k, v in value.items()) + "}"
    raise ValueError(f"no literal for {type(value).__name__}")


def _literal_value(source: str) -> tuple[bool, object]:
    try:
        return True, ast.literal_eval(ast.parse(source.strip(), mode="eval").body)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None


def _has_comment(source: str) -> bool:
    try:
        return any(t.type == tokenize.COMMENT
                   for t in tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        return False


def _ordered(value: object) -> object:
    """``value`` with every dict as a list of its items, so equality includes key order."""
    if isinstance(value, dict):
        return [("dict",)] + [(k, _ordered(v)) for k, v in value.items()]
    if isinstance(value, list):
        return [_ordered(v) for v in value]
    return (type(value).__name__, value)


# --- Readers: value → model (None: not this shape) ---------------------------------------------

def _read_poem(value: object) -> PoemWords | None:
    if type(value) is not dict:
        return None
    words = []
    for word, scores in value.items():
        if type(word) is not str:
            return None
        if type(scores) is str:
            words.append(PoemWord(word, ((scores, 1),), True))
        elif type(scores) is dict and all(type(k) is str and type(v) is int
                                          for k, v in scores.items()):
            words.append(PoemWord(word, tuple(scores.items())))
        else:
            return None
    return PoemWords(tuple(words))


def _items(value: object) -> tuple[str, ...] | None:
    if type(value) is str:
        return (value,)
    if type(value) is list and all(type(v) is str for v in value):
        return tuple(value)
    return None


def _read_testimony(value: object) -> tuple[tuple[str, str], ...] | None:
    if type(value) is not dict or not all(type(k) is str and type(v) is str
                                          for k, v in value.items()):
        return None
    return tuple(value.items())


def _read_answer(value: object) -> tuple[tuple[str, tuple[str, ...]], ...] | None:
    if type(value) is not dict:
        return None
    out = []
    for key, items in value.items():
        names = _items(items)
        if type(key) is not str or not names:
            return None
        out.append((key, names))
    return tuple(out)


def _read_plain(step: object) -> Step | None:
    if type(step) is str:
        return Step(FROM_CONTACT, step)
    if type(step) is not dict or len(step) != 1 or ASK in step:
        return None
    ((key, text),) = step.items()
    if type(key) is not str or type(text) is not str:
        return None
    if key == FROM_ME:
        return Step(FROM_ME, text)
    if key == TIME:
        return Step(TIME, text)
    return Step(FROM_OTHER, text, key)


def _read_ask(step: dict) -> AskStep | None:
    name = step[ASK]
    if type(name) is not str:
        return None
    replies, ignore = [], None
    for key, value in step.items():
        if key == ASK:
            continue
        if key == IGNORE:
            if type(value) not in (bool, str):
                return None
            ignore = value
            continue
        if type(key) is not str:
            return None
        if type(value) is str:
            replies.append(Reply(key, value))
        elif type(value) is list and value and type(value[0]) is str:
            follow = [_read_plain(s) for s in value[1:]]
            if any(s is None for s in follow):
                return None
            replies.append(Reply(key, value[0], tuple(follow)))   # type: ignore[arg-type]
        else:
            return None
    return AskStep(name, tuple(replies), ignore)


def _read_chat(value: object) -> tuple[ChatStep, ...] | None:
    if type(value) is not list:
        return None
    steps: list[ChatStep] = []
    for step in value:
        read = _read_ask(step) if type(step) is dict and ASK in step else _read_plain(step)
        if read is None:
            return None
        steps.append(read)
    return tuple(steps)


def _read_spot(name: object, spot: object) -> Hotspot | None:
    if type(name) is not str or type(spot) is not dict:
        return None
    if any(f not in FIELDS for f in spot) or "rect" not in spot or "label" not in spot:
        return None
    rect, label = spot["rect"], spot["label"]
    if type(rect) is not list or len(rect) != 4 or any(type(v) is not int for v in rect) \
            or type(label) is not str:
        return None
    texts = {}
    for field in ("look", "take", "nope", "after", "image"):
        if field in spot:
            if type(spot[field]) is not str:
                return None
            texts[field] = spot[field]
    use: tuple[str, ...] = ()
    if "use" in spot:
        names = _items(spot["use"])
        if names is None:
            return None
        use = names
    exit_ = spot.get("exit")
    if "exit" in spot and type(exit_) is not bool:
        return None
    return Hotspot(name, tuple(rect), label, use=use, exit=exit_,   # type: ignore[arg-type]
                   order=tuple(spot), **texts)


def _read_room(value: object) -> Room | None:
    if type(value) is not dict or any(k not in ROOM_KEYS for k in value) \
            or type(value.get("background")) is not str or type(value.get("hotspots")) is not dict:
        return None
    spots = [_read_spot(k, v) for k, v in value["hotspots"].items()]
    if any(s is None for s in spots):
        return None
    combine = []
    raw = value.get("combine", {})
    if type(raw) is not dict:
        return None
    for made, pair in raw.items():
        if type(made) is not str or type(pair) is not list or len(pair) != 2 \
                or any(type(v) is not str for v in pair):
            return None
        combine.append((made, pair[0], pair[1]))
    return Room(value["background"], tuple(spots), tuple(combine))   # type: ignore[arg-type]


def _gift_row(item: object, row: object) -> GiftRow | None:
    if type(item) is not str or type(row) is not list or len(row) not in (2, 3):
        return None
    if type(row[0]) is not str or type(row[1]) is not int:
        return None
    if len(row) == 3 and type(row[2]) is not str:
        return None
    return GiftRow(item, row[0], row[1], row[2] if len(row) == 3 else None)


def _read_gifts(value: object) -> GiftTable | None:
    """F54's gift table: characters → items → ``[reaction, points]`` or ``[reaction,
    points, line]`` (texts and a whole number); else None."""
    if type(value) is not dict:
        return None
    sections = []
    for character, rows in value.items():
        if type(character) is not str or type(rows) is not dict:
            return None
        out = [_gift_row(item, row) for item, row in rows.items()]
        if any(r is None for r in out):
            return None
        sections.append(GiftSection(character, tuple(out)))       # type: ignore[arg-type]
    return GiftTable(tuple(sections))


READERS: Final = {POEM: _read_poem, TESTIMONY: _read_testimony, ANSWER: _read_answer,
                  CHAT: _read_chat, ROOM: _read_room, GIFTS: _read_gifts}


def read_value(kind: str, value: object) -> object:
    """The ``kind`` model of a literal value, or None when it isn't that shape."""
    return READERS[kind](value)


# --- Writers: model → value and lines ----------------------------------------------------------

def _poem_value(model: PoemWords) -> dict:
    out: dict = {}
    for row in model.words:
        if row.short and len(row.scores) == 1 and row.scores[0][1] == 1:
            out[row.word] = row.scores[0][0]
        else:
            out[row.word] = dict(row.scores)
    return out


def _step_value(step: Step) -> object:
    if step.kind == FROM_CONTACT:
        return step.text
    if step.kind == FROM_ME:
        return {FROM_ME: step.text}
    if step.kind == TIME:
        return {TIME: step.text}
    return {step.sender: step.text}


def _ask_value(ask: AskStep) -> dict:
    out: dict = {ASK: ask.name}
    for reply in ask.replies:
        out[reply.key] = ([reply.text, *(_step_value(s) for s in reply.follow)]
                          if reply.follow else reply.text)
    if ask.ignore is not None:
        out[IGNORE] = ask.ignore
    return out


def _chat_value(model: Sequence[ChatStep]) -> list:
    return [_ask_value(s) if isinstance(s, AskStep) else _step_value(s) for s in model]


def _spot_value(spot: Hotspot) -> dict:
    have = {"rect": list(spot.rect), "label": spot.label}
    for field in ("look", "take", "nope", "after", "image"):
        if getattr(spot, field) is not None:
            have[field] = getattr(spot, field)
    if spot.use:
        have["use"] = spot.use[0] if len(spot.use) == 1 else list(spot.use)
    if spot.exit is not None:
        have["exit"] = spot.exit
    order = [f for f in spot.order if f in have] + [f for f in FIELDS if f not in spot.order]
    return {f: have[f] for f in order if f in have}


def _room_value(model: Room) -> dict:
    out: dict = {"background": model.background,
                 "hotspots": {s.name: _spot_value(s) for s in model.hotspots}}
    if model.combine:
        out["combine"] = {made: [a, b] for made, a, b in model.combine}
    return out


def _gift_value(row: GiftRow) -> list:
    return [row.reaction, row.points] + ([row.line] if row.line is not None else [])


def _gifts_value(model: GiftTable) -> dict:
    return {s.character: {r.item: _gift_value(r) for r in s.rows} for s in model.sections}


def evidence_values(model: Evidence) -> tuple[dict, dict]:
    """The testimony and answer values of ``model``."""
    testimony = {s.key: s.text for s in model.statements}
    answer = {s.key: (s.items[0] if len(s.items) == 1 else list(s.items))
              for s in model.statements if s.items}
    for key, items in model.stray:
        answer.setdefault(key, items[0] if len(items) == 1 else list(items))
    return testimony, answer


def value_of(kind: str, model: object) -> object:
    """The literal value of a ``kind`` model."""
    if kind == POEM:
        return _poem_value(model)                                # type: ignore[arg-type]
    if kind == TESTIMONY:
        return dict(model)                                       # type: ignore[arg-type]
    if kind == ANSWER:
        return {k: (v[0] if len(v) == 1 else list(v)) for k, v in model}  # type: ignore
    if kind == CHAT:
        return _chat_value(model)                                # type: ignore[arg-type]
    if kind == GIFTS:
        return _gifts_value(model)                               # type: ignore[arg-type]
    return _room_value(model)                                    # type: ignore[arg-type]


def _block(open_line: str, items: Sequence[Sequence[str]], close: str,
           close_indent: str = INDENT) -> list[str]:
    """``open_line``, each item's lines indented one level with a comma after its last
    line, then ``close`` (indented, as docs/minigames.md lays a ``define`` out)."""
    if not items:
        return [open_line + close]
    out = [open_line]
    for item in items:
        lines = [INDENT + line for line in item]
        lines[-1] += ","
        out.extend(lines)
    out.append(close_indent + close)
    return out


def _reply_value(reply: Reply) -> object:
    return [reply.text, *(_step_value(s) for s in reply.follow)] if reply.follow else reply.text


def _ask_lines(ask: AskStep) -> list[str]:
    """One line when it fits and no reply has follow-ups (no "Don't reply"); else the
    docs' layout: ``{"ask": "name",``, then one reply per line, ``}`` on the last."""
    one = literal(_ask_value(ask))
    if ask.ignore is None and not any(r.follow for r in ask.replies) \
            and len(INDENT) + len(one) + 1 <= LINE_MAX:
        return [one]
    rest = [f"{_s(r.key)}: {literal(_reply_value(r))}" for r in ask.replies]
    if ask.ignore is not None:
        rest.append(f"{_s(IGNORE)}: {literal(ask.ignore)}")
    if not rest:
        return [one]
    return [f"{{{_s(ASK)}: {_s(ask.name)},"] + [
        INDENT + part + ("}" if k == len(rest) - 1 else ",") for k, part in enumerate(rest)]


def _room_lines(name: str, room: Room) -> list[str]:
    width = max((len(_s(s.name)) + 1 for s in room.hotspots), default=0)
    spots = [[f"{(_s(s.name) + ':').ljust(width)} {literal(_spot_value(s))}"]
             for s in room.hotspots]
    items: list[list[str]] = [[f'"background": {_s(room.background)}'],
                              _block('"hotspots": {', spots, "}", "")]
    if room.combine:
        combine = {made: [a, b] for made, a, b in room.combine}
        one = f'"combine": {literal(combine)}'
        if len(INDENT) + len(one) + 1 <= LINE_MAX:
            items.append([one])
        else:
            items.append(_block('"combine": {', [[f"{_s(m)}: {literal(p)}"]
                                                 for m, p in combine.items()], "}", ""))
    return _block(f"define {name} = {{", items, "}")


def define_lines(kind: str, name: str, model: object) -> list[str]:
    """The ``define`` of a ``kind`` model as docs/minigames.md lays it out: one word,
    statement, step or hotspot per line, the closing bracket indented."""
    head = f"define {name} = "
    if kind == POEM:
        rows = [[f"{_s(w)}: {literal(v)}"] for w, v in _poem_value(model).items()]  # type: ignore
        return _block(head + "{", rows, "}")
    if kind == TESTIMONY:
        return _block(head + "{", [[f"{_s(k)}: {_s(t)}"] for k, t in model], "}")  # type: ignore
    if kind == ANSWER:
        value = value_of(ANSWER, model)
        one = head + literal(value)
        if len(one) <= LINE_MAX:
            return [one]
        return _block(head + "{", [[f"{_s(k)}: {literal(v)}"]
                                   for k, v in value.items()], "}")   # type: ignore[union-attr]
    if kind == CHAT:
        items = [_ask_lines(s) if isinstance(s, AskStep) else [literal(_step_value(s))]
                 for s in model]                                     # type: ignore[union-attr]
        return _block(head + "[", items, "]")
    if kind == GIFTS:
        items = [_block(f"{_s(s.character)}: {{",
                        [[f"{_s(r.item)}: {literal(_gift_value(r))}"] for r in s.rows], "}")
                 for s in model.sections]                            # type: ignore[union-attr]
        return _block(head + "{", items, "}")
    return _room_lines(name, model)                                  # type: ignore[arg-type]


# --- Editing helpers for the panels ------------------------------------------------------------

def poem_meters(model: PoemWords, declared: Iterable[str] = ()) -> tuple[str, ...]:
    """The poem table's columns: the story's meters (``points``), then any other name the
    words score toward, in first-written order."""
    out = dict.fromkeys(declared)
    for row in model.words:
        out.update(dict.fromkeys(m for m, _ in row.scores))
    return tuple(out)


def poem_points(row: PoemWord, meter: str) -> int:
    return dict(row.scores).get(meter, 0)


def poem_set(row: PoemWord, meter: str, points: int) -> PoemWord:
    """``row`` with ``points`` for ``meter`` (0 removes it); the same row when unchanged."""
    current = dict(row.scores)
    if current.get(meter, 0) == points:
        return row
    if points == 0:
        scores = tuple((m, p) for m, p in row.scores if m != meter)
    elif meter in current:
        scores = tuple((m, points if m == meter else p) for m, p in row.scores)
    else:
        scores = row.scores + ((meter, points),)
    return PoemWord(row.word, scores)


def slug(text: str, taken: Iterable[str], fallback: str = "line") -> str:
    """A story name made from ``text``: up to three words, lowercase letters, digits and
    ``_``, starting with a letter, made unique with ``_2``, ``_3``…"""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", plain.lower())[:3]
    base = "_".join(words)[:24] or fallback
    if not base[0].isalpha():
        base = f"{fallback}_{base}"[:24]
    used = {t.casefold() for t in taken}
    name, n = base, 2
    while name.casefold() in used or keyword.iskeyword(name):
        name, n = f"{base}_{n}", n + 1
    return name


def clamp_rect(rect: Sequence[float]) -> tuple[int, int, int, int]:
    """A rectangle drawn on the room canvas as a valid hotspot area: whole numbers, at least
    ``RECT_MIN`` square, inside the 1280 × 720 screen (a negative size is flipped)."""
    x, y, w, h = (round(v) for v in rect)
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    w = min(max(w, RECT_MIN), CANVAS[0])
    h = min(max(h, RECT_MIN), CANVAS[1])
    x = min(max(x, 0), CANVAS[0] - w)
    y = min(max(y, 0), CANVAS[1] - h)
    return x, y, w, h


def evidence_of(testimony: Sequence[tuple[str, str]],
                answer: Sequence[tuple[str, tuple[str, ...]]] | None) -> Evidence:
    """One ``Evidence`` from a testimony model and its answer model (None: no answer yet)."""
    found = dict(answer or ())
    keys = {k for k, _ in testimony}
    return Evidence(tuple(Statement(k, t, tuple(found.get(k, ()))) for k, t in testimony),
                    tuple((k, v) for k, v in (answer or ()) if k not in keys))


# --- Checks (mirroring the bundled rules' data checks) -----------------------------------------

def _hidden(ch: str) -> bool:
    return ch != "‍" and unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Zl", "Zp")


def _line_ok(text: object, hi: int, breaks: int = 0) -> bool:
    if type(text) is not str or text.strip() == "" or len(text) > hi:
        return False
    if text.count("\n") > breaks:
        return False
    if any(_hidden(ch) for ch in text.replace("\n", "")):
        return False
    return text == text.strip()


def _text(what: str, text: object, hi: int) -> str | None:
    return None if _line_ok(text, hi) else TEXT_RULE.format(what=what, hi=hi)


def _poem_problem(model: PoemWords) -> str | None:
    if len(model.words) < WORDS_MIN:
        return TOO_FEW.format(what="A word list", least=f"{WORDS_MIN} words")
    if len(model.words) > WORDS_MAX:
        return TOO_MANY.format(what="A word list", most=f"{WORDS_MAX:,} words")
    seen: set[str] = set()
    for row in model.words:
        found = _text(f'The word "{row.word}"', row.word, WORD_MAX)
        if found:
            return found
        if row.word.casefold() in seen:
            return SAME_TWICE.format(what=f'The word "{row.word}"')
        seen.add(row.word.casefold())
        if len(row.scores) > NAMES_MAX:
            return TOO_MANY.format(what=f'"{row.word}"', most=f"{NAMES_MAX} meters")
        for meter, points in row.scores:
            if METER_RE.fullmatch(meter) is None:
                return NAME_RULE.format(what=f'The meter "{meter}"')
            if type(points) is not int or not 0 <= points <= SCORE_MAX:
                return POINTS_RULE
    return None


def _evidence_problem(model: Evidence) -> str | None:
    if not model.statements:
        return TOO_FEW.format(what="A testimony", least="one statement")
    if len(model.statements) > STATEMENTS_MAX:
        return TOO_MANY.format(what="A testimony", most=f"{STATEMENTS_MAX} statements")
    keys = [s.key for s in model.statements]
    for s in model.statements:
        if STATEMENT_RE.fullmatch(s.key) is None:
            return NAME_RULE.format(what=f'The statement name "{s.key}"')
    if len(set(keys)) != len(keys):
        return SAME_TWICE.format(what="A statement name")
    for s in model.statements:
        found = _text(f'The statement "{s.key}"', s.text, STATEMENT_MAX)
        if found:
            return found
    if model.stray:
        return ANSWER_GONE.format(key=f'"{model.stray[0][0]}"')
    answered = [s for s in model.statements if s.items]
    if not answered:
        return NO_ANSWER
    for s in answered:
        if len(s.items) > ANSWER_ITEMS_MAX:
            return TOO_MANY.format(what=f'"{s.key}"', most=f"{ANSWER_ITEMS_MAX} items")
    return None


def _step_problem(step: Step, where: str) -> str | None:
    if step.kind == TIME:
        return _text(f"The time in {where}", step.text, TIME_MAX)
    if step.kind == FROM_OTHER:
        found = _text(f"The sender in {where}", step.sender, SENDER_MAX)
        if found:
            return found
    if not _line_ok(step.text, MESSAGE_MAX, BREAKS_MAX):
        return MESSAGE_RULE.format(what=f"The message in {where}")
    return None


def _chat_problem(model: Sequence[ChatStep]) -> str | None:
    if not model:
        return TOO_FEW.format(what="A chat", least="one step")
    if len(model) > STEPS_MAX:
        return TOO_MANY.format(what="A chat", most=f"{STEPS_MAX} steps")
    total = len(model) + sum(len(r.follow) for s in model if isinstance(s, AskStep)
                             for r in s.replies)
    if total > TOTAL_MAX:
        return TOO_MANY.format(what="A chat", most=f"{TOTAL_MAX:,} steps counting replies")
    names: list[str] = []
    for i, step in enumerate(model, start=1):
        where = f"step {i}"
        if not isinstance(step, AskStep):
            found = _step_problem(step, where)
            if found:
                return found
            continue
        if CHAT_ID_RE.fullmatch(step.name) is None:
            return NAME_RULE.format(what=f"The reply point name in {where}")
        if step.name in names:
            return SAME_TWICE.format(what=f'The reply point name "{step.name}"')
        names.append(step.name)
        if not 1 <= len(step.replies) <= REPLIES_MAX:
            return (TOO_FEW.format(what=f"The reply point in {where}", least="one reply")
                    if not step.replies else
                    TOO_MANY.format(what=f"The reply point in {where}",
                                    most=f"{REPLIES_MAX} replies"))
        keys = [r.key for r in step.replies]
        for reply in step.replies:
            if CHAT_ID_RE.fullmatch(reply.key) is None or reply.key in (ASK, IGNORE):
                return NAME_RULE.format(what=f'The reply name "{reply.key}"')
        if len(set(keys)) != len(keys):
            return SAME_TWICE.format(what="A reply name")
        for reply in step.replies:
            found = _text(f'The reply "{reply.key}"', reply.text, REPLY_MAX)
            if found:
                return found
            if len(reply.follow) > AFTER_MAX:
                return TOO_MANY.format(what=f'The reply "{reply.key}"',
                                       most=f"{AFTER_MAX} follow-up steps")
            for k, after in enumerate(reply.follow, start=1):
                if isinstance(after, AskStep):
                    return FOLLOW_ASK
                found = _step_problem(after, f'follow-up {k} of "{reply.key}"')
                if found:
                    return found
        if type(step.ignore) is str:
            found = _text(f'The "{DONT_REPLY}" button', step.ignore, SENDER_MAX)
            if found:
                return found
    if len(names) > ASKS_MAX:
        return TOO_MANY.format(what="A chat", most=f"{ASKS_MAX} reply points")
    return None


def _rect_ok(rect: Sequence[int]) -> bool:
    if len(rect) != 4 or any(type(v) is not int for v in rect):
        return False
    x, y, w, h = rect
    return w >= RECT_MIN and h >= RECT_MIN and x >= 0 and y >= 0 \
        and x + w <= CANVAS[0] and y + h <= CANVAS[1]


def _spot_problem(spot: Hotspot, spots: Mapping[str, Hotspot]) -> str | None:
    name = f'"{spot.name}"'
    if not _rect_ok(spot.rect):
        return RECT_RULE.format(name=name)
    for what, text, hi in (("label", spot.label, LABEL_MAX), ("look", spot.look, CAPTION_MAX),
                           ("nope", spot.nope, CAPTION_MAX)):
        if text is not None:
            found = _text(f"The {what} of {name}", text, hi)
            if found:
                return found
    does = [f for f, on in (("take", spot.take is not None), ("use", bool(spot.use)),
                            ("exit", spot.exit is True)) if on]
    if len(does) > 1:
        return DOES_ONE.format(name=name)
    if spot.look is not None and does and does[0] in ("take", "exit"):
        return LOOK_NOT.format(name=name)
    if spot.nope is not None and not spot.use:
        return NOPE_NEEDS_USE.format(name=name)
    if len(spot.use) > USE_MAX:
        return TOO_MANY.format(what=name, most=f"{USE_MAX} items that work")
    if spot.after is not None:
        other = spots.get(spot.after)
        if other is None:
            return AFTER_GONE.format(name=name, after=f'"{spot.after}"')
        if other.take is None and not other.use:
            return AFTER_NEVER.format(name=name, after=f'"{spot.after}"')
    if spot.image is not None:
        return _text(f"The picture of {name}", spot.image, IMAGE_MAX)
    return None


def _room_problem(model: Room) -> str | None:
    found = _text("The background", model.background, IMAGE_MAX)
    if found:
        return found
    if not model.hotspots:
        return TOO_FEW.format(what="A room", least="one hotspot")
    if len(model.hotspots) > HOTSPOTS_MAX:
        return TOO_MANY.format(what="A room", most=f"{HOTSPOTS_MAX} hotspots")
    spots: dict[str, Hotspot] = {}
    for spot in model.hotspots:
        if HOTSPOT_RE.fullmatch(spot.name) is None:
            return NAME_RULE.format(what=f'The hotspot name "{spot.name}"')
        if spot.name in spots:
            return SAME_TWICE.format(what=f'The hotspot name "{spot.name}"')
        spots[spot.name] = spot
    for spot in model.hotspots:
        found = _spot_problem(spot, spots)
        if found:
            return found
    for spot in model.hotspots:
        key, steps = spot.after, 0
        while key is not None and key != spot.name and steps < HOTSPOTS_MAX:
            key, steps = spots[key].after, steps + 1
        if key == spot.name:
            return AFTER_CIRCLE.format(name=f'"{spot.name}"')
    if not any(s.exit is True for s in model.hotspots):
        return NO_EXIT
    if len(model.combine) > RECIPES_MAX:
        return TOO_MANY.format(what="A room", most=f"{RECIPES_MAX} recipes")
    seen: set[frozenset[str]] = set()
    made_seen: set[str] = set()
    for made, a, b in model.combine:
        if a == b or made in (a, b):
            return COMBINE_RULE.format(made=f'"{made}"')
        if frozenset((a, b)) in seen:
            return COMBINE_TWICE.format(a=f'"{a}"', b=f'"{b}"')
        if made in made_seen:
            return SAME_TWICE.format(what=f'The recipe for "{made}"')
        seen.add(frozenset((a, b)))
        made_seen.add(made)
    return None


def _gift_echo(text: str) -> str:
    cut = text if len(text) <= 30 else text[:30] + "…"
    return '"' + "".join(" " if _hidden(ch) else ch for ch in cut) + '"'


def _gift_line_problem(what: str, line: str) -> str | None:
    """``rule_text.text_problem`` (T, 160) for a gift's line."""
    rule = f"it is 1 to {GIFT_LINE_MAX} characters on one line."
    if line == "":
        return f"{what} is empty; {rule}"
    if len(line) > GIFT_LINE_MAX:
        return f"{what} is {len(line)} characters long; {rule}"
    if any(_hidden(ch) for ch in line):
        return f"{what} has a line break or hidden character; {rule}"
    if line != line.strip():
        return f"{what} starts or ends with a space. Remove the space."
    return None


def _gift_row_problem(c: str, r: GiftRow) -> str | None:
    if r.item != ANY_GIFT and METER_RE.fullmatch(r.item) is None:
        return (f"{_gift_echo(r.item)} in the gifts for {_gift_echo(c)} can't be an item "
                'name; write an item\'s name, or "*" for any other gift.')
    where = f"the gift {_gift_echo(r.item)} for {_gift_echo(c)}"
    if r.reaction not in REACTIONS:
        return (f"{where} has the reaction {_gift_echo(r.reaction)}; a reaction is "
                '"loved", "liked", "neutral", or "disliked".')
    if not GIFT_POINTS[0] <= r.points <= GIFT_POINTS[1]:
        return f"{where} gives {r.points} points; points are a whole number from -10 to 10."
    if r.line is not None:
        return _gift_line_problem(f"the line for {_gift_echo(r.item)} ({c})", r.line)
    return None


def _gifts_problem(model: GiftTable) -> str | None:
    """``gift_rules``' data checks (G2, G3, G5, G6, G8–G10), in its words; a name written
    twice (which a dictionary can't hold) is refused too."""
    sections = model.sections
    if not 1 <= len(sections) <= CHARACTERS_MAX:
        return f"gifts has {len(sections)} characters; it can have 1 to {CHARACTERS_MAX}."
    seen: set[str] = set()
    for s in sections:
        c = s.character
        if METER_RE.fullmatch(c) is None:
            return (f"{_gift_echo(c)} can't be a character in gifts; write it as points names "
                    "a meter: letters, digits, and _.")
        if c in seen:
            return SAME_TWICE.format(what=f"The character {_gift_echo(c)}")
        seen.add(c)
        if len(s.rows) > GIFTS_MAX + (s.any_row is not None):
            return (f"{_gift_echo(c)} has {len(s.rows)} gifts; a character can have up to "
                    f"{GIFTS_MAX}.")
        items: set[str] = set()
        for r in s.rows:
            found = _gift_row_problem(c, r)
            if found is not None:
                return found
            if r.item in items:
                return SAME_TWICE.format(
                    what=f"The gift {_gift_echo(r.item)} for {_gift_echo(c)}")
            items.add(r.item)
    return None


def gift_set_any(section: GiftSection, reaction: str, points: int,
                 line: str | None) -> GiftSection:
    """``section`` with its "Any other gift" row set: written only when it differs from
    Neutral, 0 and no line (F54 §4.2); a new one goes first."""
    plain = reaction == "neutral" and points == 0 and not line
    at = next((i for i, r in enumerate(section.rows) if r.item == ANY_GIFT), 0)
    rows = [r for r in section.rows if r.item != ANY_GIFT]
    if not plain:
        rows.insert(min(at, len(rows)), GiftRow(ANY_GIFT, reaction, points, line or None))
    return GiftSection(section.character, tuple(rows))


def problem(kind: str, model: object) -> str | None:
    """The first problem the game would refuse ``model`` for (Studio's words), or None.
    ``kind`` ``TESTIMONY`` takes an ``Evidence``. Data only: a poem's word count against
    ``rounds`` and names the story must declare are the check's."""
    if kind == POEM:
        return _poem_problem(model)                                  # type: ignore[arg-type]
    if kind in (TESTIMONY, ANSWER):
        return _evidence_problem(model)                              # type: ignore[arg-type]
    if kind == CHAT:
        return _chat_problem(model)                                  # type: ignore[arg-type]
    if kind == GIFTS:
        return _gifts_problem(model)                                 # type: ignore[arg-type]
    return _room_problem(model)                                      # type: ignore[arg-type]


# --- The minigame line -------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Call:
    """A one-line ``minigame`` statement: ``args`` are ``(name, value as written)`` in
    written order; ``comment`` the trailing comment with its spaces."""

    game: str
    args: tuple[tuple[str, str], ...] = ()
    skippable: bool = False
    into: str | None = None
    indent: str = INDENT
    comment: str = ""


_MINIGAME = re.compile(r"minigame(?=[ \t])")


def _tokens(source: str) -> list[tokenize.TokenInfo] | None:
    skip = (tokenize.NL, tokenize.NEWLINE, tokenize.ENDMARKER, tokenize.INDENT,
            tokenize.DEDENT, tokenize.COMMENT)
    try:
        return [t for t in tokenize.generate_tokens(io.StringIO(source).readline)
                if t.type not in skip]
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return None


def read_call(line: str) -> Call | None:
    """The ``minigame`` line ``line`` (one physical line), or None when it isn't one or is
    written in a way the form can't hold."""
    code, comment = code_of([line])
    indent = line[:len(line) - len(line.lstrip(" \t"))]
    if not _MINIGAME.match(code):
        return None
    rest = code[len("minigame"):].lstrip(" 	")
    toks = _tokens(rest)
    if not toks or toks[0].type != tokenize.NAME or any(t.start[0] != 1 for t in toks):
        return None
    game, i, skippable = toks[0].string, 1, False
    if i < len(toks) and toks[i].string == "skippable" and \
            (i + 1 == len(toks) or toks[i + 1].string != "="):
        skippable, i = True, 2
    depth, top = 0, []
    for k, tok in enumerate(toks):
        if tok.type == tokenize.OP and tok.string in "([{":
            depth += 1
        elif tok.type == tokenize.OP and tok.string in ")]}":
            depth -= 1
        elif depth == 0:
            top.append(k)
    into, end = None, len(toks)
    if len(toks) - i >= 2 and toks[-2].string == "into" and toks[-1].type == tokenize.NAME \
            and len(toks) - 2 in top and toks[-3].string != "=":
        into, end = toks[-1].string, len(toks) - 2
    starts = [k for k in top if i <= k < end - 1 and toks[k].type == tokenize.NAME
              and toks[k + 1].string == "="]
    if (starts and starts[0] != i) or (not starts and i != end):
        return None
    args = []
    for n, k in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else end
        if stop <= k + 2:
            return None
        first = toks[k + 2].start[1]
        last = toks[stop].start[1] if stop < len(toks) else len(rest)
        args.append((toks[k].string, rest[first:last].strip()))
    if len({name for name, _ in args}) != len(args):
        return None
    return Call(game, tuple(args), skippable, into, indent, comment)


def call_line(call: Call) -> str:
    """The ``minigame`` line for ``call``."""
    words = [f"{call.indent}minigame {call.game}"]
    if call.skippable:
        words.append("skippable")
    words.extend(f"{name}={value}" for name, value in call.args)
    if call.into:
        words.extend(("into", call.into))
    return " ".join(words) + call.comment


def calls(texts: Mapping[str, str]) -> list[tuple[str, int, Call]]:
    """``(ref, line, call)`` for every one-line ``minigame`` statement in ``texts``."""
    out = []
    for ref, text in texts.items():
        for number, line in enumerate(text.split("\n"), start=1):
            if "minigame" in line and line.lstrip(" \t").startswith("minigame"):
                call = read_call(line)
                if call is not None:
                    out.append((ref, number, call))
    return out


_NAME_VALUE = re.compile(r"[^\W\d]\w*")


def uses(texts: Mapping[str, str]) -> dict[str, tuple[tuple[str, str], ...]]:
    """Data set name → the (minigame, argument) pairs that pass it (a bare name, or names
    joined with ``|`` for poem words)."""
    out: dict[str, dict[tuple[str, str], None]] = {}
    for _ref, _line, call in calls(texts):
        for arg, value in call.args:
            for part in value.split("|"):
                name = part.strip()
                if _NAME_VALUE.fullmatch(name):
                    out.setdefault(name, {})[(call.game, arg)] = None
    return {name: tuple(pairs) for name, pairs in out.items()}


def answer_name(testimony: str, texts: Mapping[str, str]) -> str | None:
    """The answer a ``present_evidence`` line passes with testimony ``testimony``."""
    for _ref, _line, call in calls(texts):
        args = dict(call.args)
        if call.game == "present_evidence" and args.get("testimony") == testimony \
                and _NAME_VALUE.fullmatch(args.get("answer", "")):
            return args["answer"]
    return None


# --- Scanning ----------------------------------------------------------------------------------

_DEFINE = re.compile(r"define[ \t]+([^\W\d]\w*)[ \t]*=(.*)", re.DOTALL)


def _guess(value: object) -> str | None:
    """A kind from the shape alone, for data no ``minigame`` line names yet."""
    if type(value) is list:
        if any(type(s) is dict for s in value) and _read_chat(value) is not None:
            return CHAT
        return None
    if type(value) is not dict or not value:
        return None
    if "hotspots" in value and _read_room(value) is not None:
        return ROOM
    if all(type(v) is dict for v in value.values()) and any(
            type(row) is list and row and row[0] in REACTIONS
            for v in value.values() for row in v.values()) and _read_gifts(value) is not None:
        return GIFTS
    values = list(value.values())
    if any(type(v) is dict for v in values) and _read_poem(value) is not None:
        return POEM
    if all(type(v) is str for v in values) and any(" " in v for v in values) \
            and all(type(k) is str and STATEMENT_RE.fullmatch(k) for k in value):
        return TESTIMONY
    return None


def scan(texts: Mapping[str, str]) -> tuple[DataSet, ...]:
    """Every minigame data ``define`` in ``texts`` (ref → editor text), in file order."""
    used = uses(texts)
    out = []
    for ref, text in texts.items():
        for first, last, lines in dec.statements(text):
            match = _DEFINE.match("\n".join(lines))
            if match is None:
                continue
            name, source = match.groups()
            ok, value = _literal_value(source)
            if not ok:
                continue
            pairs = used.get(name, ())
            kinds = [USE_KINDS[p] for p in pairs if p in USE_KINDS]
            kind, guessed = (kinds[0], False) if kinds else (_guess(value), True)
            if kind is None:
                continue
            model = read_value(kind, value)
            if model is None and guessed:
                continue
            out.append(DataSet(kind, name, ref, first, last, tuple(lines), model, pairs,
                               guessed, _has_comment(source)))
    return tuple(out)


def data_set(texts: Mapping[str, str], name: str, kind: str) -> DataSet | None:
    """The top-level ``define name`` in ``texts`` read as ``kind`` (``model`` None when it
    isn't that shape), whether or not a ``minigame`` line names it yet: a new evidence's
    answer, which ``scan`` can't tell from its shape (F47 W8)."""
    found = None
    for ref, text in texts.items():
        for first, last, lines in dec.statements(text):
            match = _DEFINE.match("\n".join(lines))
            if match is None or match.group(1) != name:
                continue
            if found is not None:
                return None                     # declared twice: the check's to report
            ok, value = _literal_value(match.group(2))
            found = DataSet(kind, name, ref, first, last, tuple(lines),
                            read_value(kind, value) if ok else None,
                            tuple(uses(texts).get(name, ())), True,
                            ok and _has_comment(match.group(2)))
    return found


def answer_for(testimony: DataSet, texts: Mapping[str, str]) -> DataSet | None:
    """The answer that goes with ``testimony``: the one a ``present_evidence`` line passes
    with it; else the only answer-shaped ``define`` whose statements are all the
    testimony's; else ``<testimony>_answer`` (F47 W8)."""
    name = answer_name(testimony.name, texts)
    if name is None:
        keys = {k for k, _ in testimony.model or ()}            # type: ignore[union-attr]
        found = []
        for text in texts.values():
            for _first, _last, lines in dec.statements(text):
                match = _DEFINE.match("\n".join(lines))
                if match is None or match.group(1) == testimony.name:
                    continue
                ok, value = _literal_value(match.group(2))
                model = _read_answer(value) if ok else None
                if model and {k for k, _ in model} <= keys:
                    found.append(match.group(1))
        name = found[0] if len(found) == 1 else f"{testimony.name}_answer"
    return data_set(texts, name, ANSWER)


def _value_at(text: str, name: str) -> list[object]:
    """The literal values of every top-level ``define name`` in ``text``."""
    found = []
    for _first, _last, lines in dec.statements(text):
        match = _DEFINE.match("\n".join(lines))
        if match is not None and match.group(1) == name:
            ok, value = _literal_value(match.group(2))
            found.append(value if ok else ValueError)
    return found


# --- Plans -------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DataPlan:
    """A data write. ``plan`` is applied as usual (one undo step per ``FilePlan``);
    ``guards`` are ``(ref, line, text)`` that must still hold and ``sizes`` ``(ref, line
    count)``; ``create`` is ``DATABASE_REF`` when that file must first be created holding
    ``declplan.DATABASE_TEXT``. ``writes``: ``(ref, name, value)`` that ``verify`` reads
    back."""

    plan: Plan
    guards: tuple[tuple[str, int, str], ...]
    sizes: tuple[tuple[str, int], ...]
    create: str | None
    writes: tuple[tuple[str, str, object], ...]


def _current(ds: DataSet, texts: Mapping[str, str]) -> list[str] | None:
    text = texts.get(ds.ref)
    if text is None:
        return None
    lines = text.split("\n")
    if ds.last > len(lines) or tuple(lines[ds.first - 1:ds.last]) != ds.lines:
        return None
    return lines


def _edits(changes: Sequence[tuple[DataSet, list[str]]], texts: Mapping[str, str],
           title: str) -> DataPlan | Refuse:
    by_ref: dict[str, list[LineEdit]] = {}
    guards: list[tuple[str, int, str]] = []
    writes = []
    for ds, new in changes:
        if _current(ds, texts) is None:
            return Refuse(STALE)
        by_ref.setdefault(ds.ref, []).append(LineEdit(ds.first, ds.last, tuple(new)))
        guards.extend((ds.ref, ds.first + k, line) for k, line in enumerate(ds.lines))
        writes.append((ds.ref, ds.name, _new_value(new)))
    files = tuple(FilePlan(ref, (), tuple(edits)) for ref, edits in by_ref.items())
    return DataPlan(Plan(title, files), tuple(guards), (), None, tuple(writes))


def _new_value(lines: Sequence[str]) -> object:
    match = _DEFINE.match("\n".join(lines))
    assert match is not None
    ok, value = _literal_value(match.group(2))
    if not ok:
        raise ValueError("unwritable")
    return value


def _title(template: str, kind: str, name: str) -> str:
    return template.format(title=KIND_TITLES[kind].lower(), name=name)


def plan_edit(ds: DataSet, model: object, texts: Mapping[str, str]
              ) -> DataPlan | Refuse | None:
    """Rewrite data set ``ds`` (``POEM``, ``CHAT`` or ``ROOM``; evidence: ``plan_evidence``)
    with ``model``. None: the model is the one read, so nothing is written."""
    if ds.model is not None and model == ds.model:
        return None
    found = problem(ds.kind, model)
    if found is not None:
        return Refuse(found)
    return _edits([(ds, define_lines(ds.kind, ds.name, model))], texts,
                  _title(CHANGED, ds.kind, ds.name))


def plan_evidence(testimony: DataSet, answer: DataSet | None, model: Evidence,
                  texts: Mapping[str, str], new_answer: str | None = None
                  ) -> DataPlan | Refuse | None:
    """Rewrite the testimony and its answer from ``model``: only the ``define`` whose
    values changed. With no ``answer`` data set yet, the answer is added after the
    testimony, named ``new_answer`` (else ``<testimony>_answer``)."""
    found = problem(TESTIMONY, model)
    if found is not None:
        return Refuse(found)
    t_value, a_value = evidence_values(model)
    t_model = _read_testimony(t_value)
    a_model = _read_answer(a_value)
    changes: list[tuple[DataSet, list[str]]] = []
    if t_model != testimony.model:
        changes.append((testimony, define_lines(TESTIMONY, testimony.name, t_model)))
    if answer is not None:
        if answer.model is None or dict(a_model or ()) != dict(answer.model):  # type: ignore
            changes.append((answer, define_lines(ANSWER, answer.name, a_model)))
    title = _title(CHANGED, TESTIMONY, testimony.name)
    if answer is None:
        name = new_answer or f"{testimony.name}_answer"
        refusal = _name_refusal(name, texts)
        if refusal is not None:
            return refusal
        new = define_lines(ANSWER, name, a_model)
        lines = _current(testimony, texts)
        if lines is None:
            return Refuse(STALE)
        plan = _edits(changes, texts, title) if changes else DataPlan(
            Plan(title, ()), (), (), None, ())
        if isinstance(plan, Refuse):
            return plan
        edits = {f.ref: list(f.edits) for f in plan.plan.files}
        at = testimony.last + 1
        edits.setdefault(testimony.ref, []).append(LineEdit(at, at - 1, tuple(new)))
        files = tuple(FilePlan(ref, (), tuple(e)) for ref, e in edits.items())
        guards = plan.guards + tuple((testimony.ref, testimony.first + k, line)
                                     for k, line in enumerate(testimony.lines))
        return DataPlan(Plan(title, files), tuple(dict.fromkeys(guards)),
                        ((testimony.ref, len(lines)),), None,
                        plan.writes + ((testimony.ref, name, _new_value(new)),))
    if not changes:
        return None
    return _edits(changes, texts, title)


def _name_refusal(name: str, texts: Mapping[str, str]) -> Refuse | None:
    if dec.name_problem(name, dec.DEFINE):
        return Refuse(BAD_NAME.format(name=name))
    taken = {n.casefold() for n in dec.taken_names(dec.scan(texts), dec.DEFINE)}
    if name.casefold() in taken:
        return Refuse(NAME_CLASH.format(name=name))
    return None


def plan_new(kind: str, name: str, model: object, texts: Mapping[str, str],
             answer: str | None = None) -> DataPlan | Refuse:
    """Add a data set at the end of ``database.vns`` (with ``include "database.vns"`` in
    ``main.vns`` when no script has one). For evidence, ``kind`` is ``TESTIMONY``, ``model``
    an ``Evidence`` and ``answer`` the answer's name (else ``<name>_answer``)."""
    found = problem(kind, model)
    if found is not None:
        return Refuse(found)
    if kind in (TESTIMONY, ANSWER):
        answer = answer or f"{name}_answer"
        t_value, a_value = evidence_values(model)                    # type: ignore[arg-type]
        blocks = [(name, define_lines(TESTIMONY, name, _read_testimony(t_value))),
                  (answer, define_lines(ANSWER, answer, _read_answer(a_value)))]
    else:
        blocks = [(name, define_lines(kind, name, model))]
    for block_name, _ in blocks:
        refusal = _name_refusal(block_name, texts)
        if refusal is not None:
            return refusal
    if len({n.casefold() for n, _ in blocks}) != len(blocks):
        return Refuse(NAME_CLASH.format(name=blocks[-1][0]))
    db_text = texts.get(DATABASE_REF)
    create = None
    if db_text is None:
        db_text, create = DATABASE_HEADER, DATABASE_REF
    lines = db_text.split("\n")
    new: list[str] = []
    for _, block in blocks:
        new.extend([""] + block)
    guards: list[tuple[str, int, str]] = []
    if lines == [""]:
        edit = LineEdit(1, 1, tuple(new[1:] + [""]))
        guards.append((DATABASE_REF, 1, ""))
    elif lines[-1] == "":
        at = len(lines)
        if at < 2 or lines[at - 2].strip() == "":
            new = new[1:]
        edit = LineEdit(at, at - 1, tuple(new))
        guards.append((DATABASE_REF, at, ""))
    else:
        at = len(lines) + 1
        edit = LineEdit(at, at - 1, tuple(new))
        guards.append((DATABASE_REF, at - 1, lines[-1]))
    sizes = [(DATABASE_REF, len(lines))]
    files = [FilePlan(DATABASE_REF, (), (edit,))]
    if not includes_database(texts):
        main = texts.get(MAIN_REF)
        if main is None:
            return Refuse(NO_MAIN)
        main_lines = main.split("\n")
        pos = include_position(main)
        files.append(FilePlan(MAIN_REF, (), (
            LineEdit(pos, pos - 1, (include_line(DATABASE_REF),)),)))
        sizes.append((MAIN_REF, len(main_lines)))
        if pos > 1:
            guards.append((MAIN_REF, pos - 1, main_lines[pos - 2]))
    writes = tuple((DATABASE_REF, n, _new_value(b)) for n, b in blocks)
    return DataPlan(Plan(_title(ADDED, kind, name), tuple(files)), tuple(guards),
                    tuple(sizes), create, writes)


def verify(data_plan: DataPlan, texts: Mapping[str, str]) -> bool:
    """True when ``data_plan`` still fits ``texts`` (guards and sizes), adds no parse
    problem, and each written ``define`` reads back as the planned value (key order
    included). Never raises."""
    try:
        sizes = dict(data_plan.sizes)
        after: dict[str, str] = {}
        for file_plan in data_plan.plan.files:
            text = texts.get(file_plan.ref)
            if text is None:
                return False
            lines = text.split("\n")
            if file_plan.ref in sizes and len(lines) != sizes[file_plan.ref]:
                return False
            for ref, line, want in data_plan.guards:
                if ref == file_plan.ref and (line > len(lines) or lines[line - 1] != want):
                    return False
            new = "\n".join(apply_lines(lines, file_plan.edits))
            if problems(file_plan.ref, new) - problems(file_plan.ref, text):
                return False
            after[file_plan.ref] = new
        for ref, name, value in data_plan.writes:
            found = _value_at(after.get(ref, ""), name)
            if len(found) != 1 or _ordered(found[0]) != _ordered(value):
                return False
        return True
    except Exception:          # a planner bug must never reach the text (TR-F46-03)
        return False


# --- The Minigame form (PR-F47-24) -------------------------------------------------------------

DATA: Final = "data"            # pick a data set (or type a value)
NUMBER: Final = "number"
TOGGLE: Final = "toggle"
CHOICE: Final = "choice"
TEXT: Final = "text"            # a quoted text, or None
METER: Final = "meter"
VARIABLE: Final = "variable"
VALUE: Final = "value"          # any value, written as script
SOUND: Final = "sound"          # F57: a sound file under audio/ (quoted), or None
NO_DEFAULT: Final = object()
NO_PLUGINS: Final[Mapping[str, str]] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class ArgField:
    """One field of the Minigame form. ``default`` is the declared default (``NO_DEFAULT``:
    required, or not a literal) and ``default_text`` how it is written; ``data_kind`` the
    kind of data set a ``DATA`` field lists (None: any)."""

    name: str
    label: str
    required: bool
    widget: str
    default: object = NO_DEFAULT
    data_kind: str | None = None
    lo: int | None = None
    hi: int | None = None
    choices: tuple[str, ...] = ()

    @property
    def default_text(self) -> str:
        return "" if self.default is NO_DEFAULT else literal(self.default)


@dataclass(frozen=True, slots=True)
class GameForm:
    game: str
    fields: tuple[ArgField, ...]
    into: ArgField


_INTO: Final = ArgField("into", INTO_LABEL, False, VARIABLE, None)


def _f(name: str, label: str, widget: str, default: object = NO_DEFAULT, **more: object
       ) -> ArgField:
    return ArgField(name, label, default is NO_DEFAULT, widget, default, **more)  # type: ignore


BUILTIN_FIELDS: Final[Mapping[str, tuple[ArgField, ...]]] = {
    "poem_game": (
        _f("words", "Word list", DATA, data_kind=POEM),
        _f("rounds", "Words in the poem", NUMBER, 20, lo=1, hi=50),
        _f("page_words", "Words on each page", NUMBER, 10, lo=2, hi=12),
        _f("to_points", "Add the scores to the meters", TOGGLE, True),
        _f("result", "Result", CHOICE, "winner", choices=("winner", "totals", "words"))),
    "present_evidence": (
        _f("testimony", "Testimony", DATA, data_kind=TESTIMONY),
        _f("answer", "Answer", DATA, data_kind=ANSWER),
        _f("at", "Start at statement", VALUE, None),
        _f("speaker", "Speaker", TEXT, None),
        _f("press", "Show Press", TOGGLE, True),
        _f("evidence", "Item categories", VALUE, None),
        _f("penalty", "Meter a wrong item lowers", METER, None),
        _f("penalty_max", "Meter's top", NUMBER, 5, lo=1, hi=20),
        _f("cost", "A wrong item costs", NUMBER, 1, lo=0, hi=20)),
    "phone_chat": (
        _f("chat", "Chat", DATA, data_kind=CHAT),
        _f("contact", "Contact", TEXT),
        _f("time", "First time", TEXT, None)),
    "puzzle_room": (
        _f("room", "Room", DATA, data_kind=ROOM),
        _f("state", "Where the player left it", VARIABLE, None)),
    "heartbeat": (                                                      # F57 §7
        _f("beats", "Beats", NUMBER, 8, lo=4, hi=20),
        _f("bpm", "Beats a minute", NUMBER, 60, lo=40, hi=120),
        _f("window", "How forgiving", CHOICE, "normal", choices=("tight", "normal", "wide")),
        _f("meter", "Meter a miss lowers", METER, None),
        _f("cost", "A miss costs", NUMBER, 1, lo=0, hi=20),
        _f("sound", "Beat sound", SOUND, None)),
    "code_lock": (                                                      # F53 §5
        _f("kind", "Kind", CHOICE, "keypad", choices=("keypad", "dial")),
        _f("code", "Code", TEXT),
        _f("tries", "Tries allowed", NUMBER, 0, lo=0, hi=99),
        _f("hint", "Hint", TEXT, None),
        _f("hint_after", "Show the hint after", NUMBER, 3, lo=0, hi=99),
        _f("leave", "Player can step back", TOGGLE, True)),
    "stay_still": (
        _f("seconds", "Seconds", NUMBER, 10, lo=3, hi=120),
        _f("line", "What they say", TEXT, None),
        _f("speaker", "Who says it", TEXT, None),
        _f("flinch_line", "What they say when you move", TEXT, None),
        _f("strict", "The first touch ends it", TOGGLE, False),
        _f("mouse", "Moving the mouse counts", TOGGLE, False),
        _f("ready", "Show an \"I'm ready\" button", TOGGLE, True)),
    "hand_game": (
        _f("opponent", "Opponent's name", TEXT),
        _f("rounds", "Rounds", NUMBER, 3, lo=1, hi=9),
        _f("mode", "How they play", CHOICE, "fair", choices=("fair", "kind", "cheat", "sly"))),
    "gift_giving": (                                                    # F54 §4.2
        _f("gifts", "Gift table", DATA, data_kind=GIFTS),
        _f("to", "Gift for", METER),
        _f("speaker", "Name shown", TEXT, None),
        _f("categories", "Item categories", VALUE, None),
        _f("use_up", "The gift is used up", TOGGLE, True),
        _f("leave", "Player can say Not now", TOGGLE, True),
        _f("result", "Result", CHOICE, "reaction", choices=("reaction", "item"))),
}

# F53 §5: Lock's code must fit its kind (L3/L4 of ``lock_rules``, which Studio may not import,
# ADR-0008; ``test_minigamedata`` compares them). ASCII sets, as the rules use.
_DIGITS: Final = frozenset("0123456789")
_LETTERS: Final = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
ECHO_MAX: Final = 30


def _echo(text: str) -> str:
    """``rule_text.quoted``'s echo: cut to 30 code points and "…", in double quotes."""
    cut = text if len(text) <= ECHO_MAX else text[:ECHO_MAX] + "…"
    return '"' + "".join(" " if _hidden(ch) else ch for ch in cut) + '"'


def _literal_text(text: str) -> str | None:
    """A field's script text as the text it writes, or None (empty, None, an expression)."""
    try:
        value = ast.literal_eval(text.strip()) if text.strip() else None
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None
    return value if isinstance(value, str) else None


def code_problem(kind: str, code: str) -> str | None:
    """L3/L4 as the Minigame form shows them (the first letter capitalised), or None."""
    if kind == "keypad":
        if 1 <= len(code) <= 12 and set(code) <= _DIGITS:
            return None
        return f"A keypad code is 1 to 12 digits from 0 to 9, but code is {_echo(code)}."
    if kind == "dial":
        if 3 <= len(code) <= 6 and (set(code) <= _DIGITS or set(code) <= _LETTERS):
            return None
        return ("A dial code is 3 to 6 digits, or 3 to 6 letters from A to Z, but code is "
                f"{_echo(code)}.")
    return None


def form_problem(game: str, values: Mapping[str, str]) -> str | None:
    """A problem the Minigame form can see before OK (F53 §5's form check): Lock's code that
    doesn't fit its kind. Expressions and empty values are left to the game."""
    if game != "code_lock":
        return None
    code = _literal_text(values.get("code", ""))
    kind_text = values.get("kind", "").strip()
    kind = _literal_text(kind_text) if kind_text else "keypad"
    if code is None or kind is None:
        return None
    return code_problem(kind, code)


def _label(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _plugin_defaults(text: str, game: str) -> dict[str, object]:
    """Arg name → literal default of the minigame class ``game`` in ``text`` (``NO_DEFAULT``
    for a default that isn't a literal)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return {}
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        attrs = {s.targets[0].id: s.value for s in cls.body
                 if isinstance(s, ast.Assign) and len(s.targets) == 1
                 and isinstance(s.targets[0], ast.Name)}
        name = attrs.get("name")
        if not (isinstance(name, ast.Constant) and name.value == game):
            continue
        args = attrs.get("args")
        out: dict[str, object] = {}
        if isinstance(args, ast.Dict):
            for key, item in zip(args.keys, args.values):
                if isinstance(key, ast.Constant) and isinstance(item, ast.Call):
                    for kw in item.keywords:
                        if kw.arg == "default":
                            try:
                                out[key.value] = ast.literal_eval(kw.value)
                            except (ValueError, TypeError, SyntaxError, RecursionError):
                                out[key.value] = NO_DEFAULT
                    if item.args:
                        try:
                            out[key.value] = ast.literal_eval(item.args[0])
                        except (ValueError, TypeError, SyntaxError, RecursionError):
                            out[key.value] = NO_DEFAULT
        return out
    return {}


def _plugin_field(name: str, required: bool, default: object) -> ArgField:
    if required:
        return ArgField(name, _label(name), True, DATA)
    widget = {bool: TOGGLE, int: NUMBER, str: TEXT}.get(type(default), VALUE)
    return ArgField(name, _label(name), False, widget, default)


def games(plugin_texts: Mapping[str, str] = NO_PLUGINS) -> tuple[str, ...]:
    """Installed minigames: the bundled ones, then the game's plugins (ref → source)."""
    out = dict.fromkeys(BUNDLED)
    for text in plugin_texts.values():
        out.update(dict.fromkeys(sig.name for sig in plugin_sigs(text)))
    return tuple(out)


def form_fields(game: str, plugin_texts: Mapping[str, str] = NO_PLUGINS) -> GameForm | None:
    """The Minigame form for ``game``: one field per declared argument, in declared order,
    and ``into``. None when no installed plugin has that name."""
    if game in BUILTIN_FIELDS:
        return GameForm(game, BUILTIN_FIELDS[game], _INTO)
    for text in plugin_texts.values():
        for sig in plugin_sigs(text):
            if sig.name == game:
                defaults = _plugin_defaults(text, game)
                return GameForm(game, tuple(
                    _plugin_field(arg, required, defaults.get(arg, NO_DEFAULT))
                    for arg, required in sig.args), _INTO)
    return None


def data_choices(field: ArgField, sets: Iterable[DataSet]) -> tuple[str, ...]:
    """The data sets a ``DATA`` field offers: those of its kind (any kind for a plugin's)."""
    if field.widget != DATA:
        return ()
    return tuple(ds.name for ds in sets
                 if field.data_kind is None or ds.kind == field.data_kind)


def form_values(form: GameForm, call: Call | None) -> dict[str, str]:
    """Each field's text: as written on the line, else its default's."""
    written = dict(call.args) if call is not None else {}
    out = {f.name: written.get(f.name, f.default_text) for f in form.fields}
    out[form.into.name] = (call.into or "") if call is not None else ""
    return out


def call_from_form(form: GameForm, values: Mapping[str, str], *, skippable: bool = False,
                   old: Call | None = None) -> Call | Refuse:
    """The line's ``Call`` from the form: arguments in declared order, a value still at its
    default left out (unless the old line wrote it), ``into`` from ``values["into"]``.
    Refused when a required argument is empty."""
    old_args = dict(old.args) if old is not None else {}
    args = []
    for f in form.fields:
        text = values.get(f.name, "").strip()
        if not text:
            if f.required:
                return Refuse(NEEDED.format(label=f.label))
            continue
        if not f.required and text == f.default_text and f.name not in old_args:
            continue
        args.append((f.name, text))
    known = {f.name for f in form.fields}
    args.extend((k, v) for k, v in old_args.items() if k not in known)
    found = form_problem(form.game, values)
    if found is not None:
        return Refuse(found)
    into = values.get(form.into.name, "").strip() or None
    if into is not None and _NAME_VALUE.fullmatch(into) is None:
        return Refuse(NAME_RULE.format(what=INTO_LABEL))
    return Call(form.game, tuple(args), skippable, into,
                old.indent if old else INDENT, old.comment if old else "")


# --- The Events row (F47 W8) -------------------------------------------------------------------

MINIGAME_FORM: Final = "minigame"
GAME_TITLES: Final[Mapping[str, str]] = {
    "poem_game": "Poem", "present_evidence": "Present evidence",
    "phone_chat": "Phone chat", "puzzle_room": "Puzzle room", "heartbeat": "Heartbeat",
    "code_lock": "Lock", "stay_still": "Stay still", "hand_game": "Hand game",
    "gift_giving": "Gift giving"}


def game_title(game: str) -> str:
    """A minigame as the author sees it: the bundled ones by title, a plugin by its name."""
    return GAME_TITLES.get(game, game)


def _row_read(node: object, code: str) -> dict[str, str] | None:
    from engine.script.minigame import Minigame
    if not isinstance(node, Minigame) or read_call(code) is None:
        return None
    return {"line": code.strip()}


def _shown(text: str | None) -> str:
    """An argument's script text as a row shows it: a text unquoted, else as written."""
    if text is None:
        return ""
    found = _literal_text(text)
    return found if found is not None else text.strip()


def _arg_summary(game: str, args: Mapping[str, str]) -> str | None:
    """F53 §5: the key setting of a game with no data (Lock's code, Stay still's seconds,
    Hand game's opponent and mode), or None for the others."""
    if game == "code_lock":
        return _shown(args.get("code"))
    if game == "stay_still":
        return f"{_shown(args.get('seconds', '10'))} s"
    if game == "hand_game":
        return f"{_shown(args.get('opponent'))}, {_shown(args.get('mode', repr('fair')))}"
    return None


def _row_summary(values: Mapping[str, str]) -> str:
    call = read_call(values.get("line", ""))
    if call is None:
        return values.get("line", "")
    data = [v for k, v in call.args if (call.game, k) in USE_KINDS or k == "words"]
    own = _arg_summary(call.game, dict(call.args))
    if own is not None:
        data = [own]
    parts = [game_title(call.game), *dict.fromkeys(data)]
    text = " · ".join(parts)
    return f"{text} → {call.into}" if call.into else text


def _row_form() -> object:
    """The Minigame ``CommandForm`` (its dialog is ``minigameview``'s: the fields depend on
    the game). Values: ``{"line": <the line without indent or comment>}``."""
    from engine.script.minigame import Minigame
    from engine.tools.editor.forms import CommandForm
    return CommandForm(MINIGAME_FORM, "Minigame", "Minigame", (("minigame", ""),), Minigame,
                       (), _row_read, lambda v: v["line"], _row_summary)


FORM: Final = _row_form()


__all__ = [
    "ADDED", "ANSWER", "ASK", "AskStep", "ArgField", "BUILTIN_FIELDS", "BUNDLED", "CANVAS",
    "CHANGED", "CHAT", "CHOICE", "Call", "ChatStep", "DATA", "DONT_REPLY", "DataPlan",
    "DataSet", "Evidence", "FIELDS", "FROM_CONTACT", "FROM_ME", "FROM_OTHER", "GameForm",
    "Hotspot", "INTO_LABEL", "KINDS", "KIND_TITLES", "METER", "NEEDED", "NO_DEFAULT",
    "NUMBER", "POEM", "SOUND", "POINTS_PICK", "PoemWord", "PoemWords", "RECT_MIN", "ROOM", "Reply",
    "Room", "STEP_TITLES", "Statement", "Step", "TESTIMONY", "TEXT", "TIME", "TOGGLE",
    "USE_KINDS", "VALUE", "VARIABLE", "answer_name", "call_from_form", "call_line", "calls",
    "clamp_rect", "code_problem", "data_choices", "define_lines", "form_problem",
    "evidence_of", "evidence_values", "ANY_GIFT", "GIFTS", "GiftRow", "GiftSection",
    "GiftTable", "REACTIONS", "REACTION_TITLES", "gift_set_any",
    "FORM", "GAME_TITLES", "MINIGAME_FORM", "answer_for", "data_set", "game_title",
    "form_fields", "form_values", "games", "literal", "plan_edit", "plan_evidence",
    "plan_new", "poem_meters", "poem_points", "poem_set", "problem", "read_call",
    "read_value", "scan", "slug", "uses", "value_of", "verify"]

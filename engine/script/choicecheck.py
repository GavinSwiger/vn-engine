"""Checks on choices (F59 SPEC): ``"text" check <meter> <difficulty>:`` with ``success:`` and
``failure:`` lines under it.

Why this module exists: a checked choice needs its own small grammar (the check on the choice
line, two branch blocks under it), a node the interpreter rolls at, and the odds rule the
runtime, the choice screen and Studio all agree on. The rule is pure (no dice, no state), so
Studio shows the same odds the player will see.

- ``ChoiceCheck``: the check on a choice line (``Choice.check``), outside the choice's key.
- ``CheckRoll``: the one statement of a checked choice's block. ``blocks()`` is (success,
  failure), so every walk (paths, sids, the story map, reach) sees both like an if/else.
- ``passes``/``success_count``/``odds``: two six-sided dice plus the meter's value reach the
  difficulty; double six always succeeds, double one always fails.
- ``parse_check`` (E408) and ``parse_check_block`` (E409; E12's ``success``/``failure``
  forms) are called by ``script/menu.py``. An unknown meter is F22's E233 (``checks.py``).
"""

from collections.abc import Generator, Sequence
from dataclasses import dataclass
from typing import Final

from engine.script.diagnostics import Diagnostic
from engine.script.lexer import COLON, HEAD_WORD, NAME, RANK_BLOCK, RawStatement, Token
from engine.script.limits import SCRIPT_MAX_BLOCK_DEPTH
from engine.script.nodes import Statement
from engine.script.statements import ParseContext
from engine.script.words import canonical_name, is_name

WORD_CHECK: Final = "check"
WORD_SUCCESS: Final = "success"
WORD_FAILURE: Final = "failure"
BRANCH_WORDS: Final = (WORD_SUCCESS, WORD_FAILURE)
# The tiers, lowest first: a word an author may write, and the badge word for a number.
TIERS: Final = (("trivial", 6), ("easy", 8), ("medium", 10), ("hard", 12), ("heroic", 14),
                ("legendary", 16), ("impossible", 18))
TIER_VALUES: Final = dict(TIERS)
DIFFICULTY_MIN: Final = 1
DIFFICULTY_MAX: Final = 99
_FOUND_MAX: Final = 30


@dataclass(frozen=True, slots=True)
class ChoiceCheck:
    """``check <meter> <difficulty>`` on a choice line: the canonical meter name, the
    difficulty as a number, and the difficulty as written (a tier word or digits)."""

    meter: str
    difficulty: int
    written: str
    line: int
    column: int


@dataclass(slots=True, kw_only=True)
class CheckBranch:
    """``success:`` or ``failure:`` under a checked choice (``line`` is its own line)."""

    keyword: str
    line: int
    column: int
    block: tuple[Statement, ...] = ()


@dataclass(slots=True, kw_only=True)
class CheckRoll(Statement):
    """The only statement of a checked choice's block, on its ``success:`` line. Running it
    rolls the story dice and enters ``branches[0]`` (success) or ``branches[1]`` (failure)."""

    check: ChoiceCheck
    branches: tuple[CheckBranch, ...] = ()

    def identity_key(self) -> tuple[str, ...]:
        return ("check", self.check.meter, str(self.check.difficulty))

    def blocks(self) -> tuple[tuple[Statement, ...], ...]:
        return tuple(branch.block for branch in self.branches)


# --- The rule -----------------------------------------------------------------------------------

def passes(a: int, b: int, value: int, difficulty: int) -> bool:
    """Whether dice ``a`` and ``b`` (1–6) plus ``value`` pass ``difficulty``."""
    if a == b == 6:
        return True
    if a == b == 1:
        return False
    return a + b + value >= difficulty


def success_count(value: int, difficulty: int) -> int:
    """How many of the 36 rolls pass (1 to 35)."""
    return sum(passes(a, b, value, difficulty) for a in range(1, 7) for b in range(1, 7))


def odds(value: int, difficulty: int) -> int:
    """The chance to pass as a whole percent (3 to 97), rounded half up."""
    return (success_count(value, difficulty) * 200 + 36) // 72


def tier(difficulty: int) -> str:
    """The badge word: the highest tier at or below ``difficulty`` (below 6: Trivial)."""
    word = TIERS[0][0]
    for name, at in TIERS:
        if difficulty >= at:
            word = name
    return word.capitalize()


def meter_title(name: str) -> str:
    """A meter's name as the badge shows it: ``street_smarts`` → ``Street smarts``."""
    text = name.replace("_", " ").strip() or name
    return text[:1].upper() + text[1:]


def badge(meter: str, value: int, difficulty: int) -> str:
    """``[Logic · Medium · 58%]``."""
    return f"[{meter_title(meter)} · {tier(difficulty)} · {odds(value, difficulty)}%]"


def parse_difficulty(text: str) -> int | None:
    """A tier word (any case) or a whole number from 1 to 99 as digits; else None."""
    word = text.strip().lower()
    if word in TIER_VALUES:
        return TIER_VALUES[word]
    if word.isascii() and word.isdigit() and len(word) <= 3:
        value = int(word)
        if DIFFICULTY_MIN <= value <= DIFFICULTY_MAX:
            return value
    return None


def check_code(meter: str, written: str) -> str:
    """The script text of a check (Studio writes it): ``check logic medium``."""
    return f"{WORD_CHECK} {meter} {written}"


# --- Parsing (called by script/menu.py) -----------------------------------------------------------

def _found(raw: RawStatement, token: Token) -> str:
    rest = raw.rest_from(token.line, token.column)
    if rest.endswith(":"):
        rest = rest[:-1].rstrip()
    return rest[:_FOUND_MAX] or token.text


def parse_check(raw: RawStatement, ctx: ParseContext, words: Sequence[Token]) -> ChoiceCheck | None:
    """``words`` start with ``check`` and end before the ``:`` (or the ``if``). E408 on a
    mistake (None)."""
    first = words[0]
    if len(words) == 1:
        ctx.error("E408", "empty")
        return None
    meter = words[1]
    if meter.kind != NAME or not is_name(meter.text) or meter.text[:1].isdigit():
        ctx.error("E408", "meter", _found(raw, meter))
        return None
    name = canonical_name(meter.text)
    if len(words) == 2:
        ctx.error("E408", "missing", name)
        return None
    level = words[2]
    difficulty = parse_difficulty(level.text) if level.kind == NAME else None
    if difficulty is None:
        ctx.error("E408", "bad", _found(raw, level))
        return None
    if len(words) > 3:
        extra = words[3]
        if extra.kind == NAME and extra.text == "retry":
            ctx.error("E408", "retry")
        else:
            ctx.error("E408", "left", f"{name} {level.text}", _found(raw, extra))
        return None
    return ChoiceCheck(name, difficulty, level.text, first.line, first.column)


def _branch_word(raw: RawStatement) -> str | None:
    """``success`` or ``failure`` when the line is exactly that word and ``:``."""
    tokens = raw.tokens
    if (raw.head == HEAD_WORD and raw.word in BRANCH_WORDS and raw.py is None
            and len(tokens) == 2 and tokens[1].kind == COLON):
        return raw.word
    return None


def _no_node(raw: RawStatement, ctx: ParseContext) -> None:
    return None


def parse_check_block(api, line: RawStatement, after: RawStatement | None, depth: int,
                      widths: tuple[int, ...], check: ChoiceCheck
                      ) -> Generator[None, None, CheckRoll | None]:
    """The lines under a checked choice (``line``; ``after`` the next statement, deeper or
    not): ``success:`` then ``failure:``, each with a block. ``depth`` is the choice block's
    depth. E409 for anything else, or at the choice for a missing branch (only when no line
    under it had one); the node is None unless both branches are there."""
    ctx = api.ctx
    w = line.width
    found: dict[str, CheckBranch] = {}
    bad = False                          # an E409 at a line under it: no "missing" too
    if after is not None and after.width > w:
        block_w = after.width
        phantom: int | None = None
        while True:
            sub = yield from api.peek()
            if sub is None or sub.width <= w:
                break
            phantom = api.check_width(sub, block_w, phantom, widths)
            api.reader.next()
            ctx.statement_count += 1
            nxt = yield from api.peek()
            deeper = nxt is not None and nxt.width > sub.width
            word = _branch_word(sub)
            if word is None or word in found or (word == WORD_SUCCESS and found):
                form = ("other" if word is None else "twice" if word in found else "order")
                sub.error("E409", (form, word or ""))
                bad = True
                api.parse_line(sub, depth, _no_node)
                if deeper:
                    yield from api.skip_deeper(sub.width, quiet=True)
                continue
            api.parse_line(sub, depth, _no_node)
            branch = CheckBranch(keyword=word, line=sub.line, column=sub.column)
            found[word] = branch
            if not deeper:
                api.empty_block(sub, word, nxt)
            elif depth + 1 > SCRIPT_MAX_BLOCK_DEPTH:
                nxt.error("E15", rank=RANK_BLOCK)
                yield from api.skip_deeper(sub.width, quiet=False)
            else:
                block = yield from api.parse_block(sub.width, nxt.width, depth + 1,
                                                   widths + (nxt.width,))
                branch.block = tuple(s for s in block if isinstance(s, Statement))
            if api.due():
                yield
    missing = [word for word in BRANCH_WORDS if word not in found]
    if missing and bad:
        return None
    if missing:
        ctx.sink.add(Diagnostic("E409", api.file, line.line, None, ("missing", missing[0]),
                                source_line=line.texts.get(line.line), stmt=line.line))
        return None
    success = found[WORD_SUCCESS]
    return CheckRoll(file=line.file, line=success.line, end_line=success.line,
                     column=success.column, check=check,
                     branches=(success, found[WORD_FAILURE]))


__all__ = ["BRANCH_WORDS", "CheckBranch", "CheckRoll", "ChoiceCheck", "DIFFICULTY_MAX",
           "DIFFICULTY_MIN", "TIERS", "TIER_VALUES", "WORD_CHECK", "badge", "check_code",
           "meter_title", "odds", "parse_check", "parse_check_block", "parse_difficulty",
           "passes", "success_count", "tier"]

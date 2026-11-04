"""Hand game's pure rules (F53 ``01`` §3.3, §3.4, §3.5, §4.3; ``04`` §3.4, §3.5).

Why this module exists: who wins a round, what the opponent's hand is in each mode, when the
match ends and its result can all be decided without a window, so the hooks and the session
share one copy and the tests drive it directly:

- **Checks.** ``problem(args)``: H1–H3 in table order, the first problem only.
- **Hands.** ``beats(h)`` (the hand that beats ``h``), ``loses_to(h)`` (the hand ``h``
  beats), ``outcome(player, her)`` from the player's side.
- **Her hand.** ``her_hand(mode, fair, player, score, rounds)``: ``fair`` is the round's
  ``ctx.random.pick`` (drawn before the player picks, in every mode). ``kind`` swaps in the
  hand that loses whenever the fair one would leave the player unable to finish ahead
  (wins + rounds left ≤ losses), so ``kind`` always ends ``"won"``; ``cheat`` shows the fair
  hand and switches to the winning one when it would lose; ``sly`` shows the winning one at
  once.
- **The match.** ``Score``, ``finished`` (no rounds left, or a lead bigger than the rounds
  left), ``result_of`` ("won", "lost", "draw"), ``fixed_outcome`` (test and skipped).
- **Look.** ``hand_layout`` (every rectangle inside the content area) and ``shake_offset``.

Pure: no clock, no randomness, no I/O. Imports only ``engine.minigames.api``,
``bundled.rule_text`` and the stdlib.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final

from engine.minigames.api import Outcome, closest
from engine.minigames.bundled.rule_text import choice_problem, text_problem, whole_problem

HANDS: Final = ("rock", "paper", "scissors")
MODES: Final = ("fair", "kind", "cheat", "sly")
ROUNDS: Final = (1, 9)
NAME_MAX: Final = 24
DEFAULTS: Final = {"opponent": None, "rounds": 3, "mode": "fair"}
REQUIRED: Final = ("opponent",)
_BEATS: Final = {"rock": "paper", "paper": "scissors", "scissors": "rock"}
_LOSES_TO: Final = {v: k for k, v in _BEATS.items()}

SWITCH_S: Final = 0.6                 # cheat: her hand switches this long after the reveal
SHAKE_S, SHAKE_UNITS = 0.2, 6         # the switch shakes her card ±6 for 0.2 s
EPSILON: Final = 1e-9

# Sizes (01 §4.3), canvas units at 100 % text.
CARD: Final = (320, 220)
CARD_GAP: Final = 80
HAND_BUTTON_W: Final = 200
BUTTON_GAP: Final = 24
GAPS: Final = (16, 4)
SCORE_TEXT, ROUND_TEXT, CAPTION_TEXT, NAME_TEXT = 32, 24, 24, 24
HAND_TEXT: Final = (48, 32, 64)       # hand.text_size: default, lo, hi
CARD_PAD: Final = 16

Rect = tuple[float, float, float, float]


def problem(args: dict) -> str | None:
    """The first refused argument's reason (H1–H3), or None."""
    mode = args.get("mode", DEFAULTS["mode"])
    return (text_problem("opponent", args.get("opponent"), NAME_MAX, required=True)
            or whole_problem("rounds", args.get("rounds", DEFAULTS["rounds"]), *ROUNDS)
            or choice_problem("mode", mode, MODES, closest=closest(mode, MODES)))


def beats(hand: str) -> str:
    """The hand that beats ``hand``."""
    return _BEATS[hand]


def loses_to(hand: str) -> str:
    """The hand that ``hand`` beats."""
    return _LOSES_TO[hand]


def outcome(player: str, her: str) -> str:
    """``"win"``, ``"lose"`` or ``"draw"`` for the player."""
    if player == her:
        return "draw"
    return "win" if loses_to(player) == her else "lose"


@dataclass(frozen=True, slots=True)
class Score:
    wins: int = 0
    losses: int = 0
    draws: int = 0

    @property
    def played(self) -> int:
        return self.wins + self.losses + self.draws

    def after(self, result: str) -> "Score":
        if result == "win":
            return replace(self, wins=self.wins + 1)
        if result == "lose":
            return replace(self, losses=self.losses + 1)
        return replace(self, draws=self.draws + 1)


@dataclass(frozen=True, slots=True)
class Hand:
    """Her hand this round: ``shown`` at the reveal, ``final`` after any switch."""
    shown: str
    final: str

    @property
    def switched(self) -> bool:
        return self.shown != self.final


def her_hand(mode: str, fair: str, player: str, score: Score, rounds: int) -> Hand:
    """Her hand for this round (module docstring)."""
    if mode == "kind":
        after = score.after(outcome(player, fair))
        if after.wins + (rounds - after.played) <= after.losses:
            return Hand(loses_to(player), loses_to(player))
        return Hand(fair, fair)
    if mode in ("cheat", "sly") and outcome(player, fair) == "win":
        winning = beats(player)
        return Hand(fair if mode == "cheat" else winning, winning)
    return Hand(fair, fair)


def finished(score: Score, rounds: int) -> bool:
    """No rounds left, or one side's lead is more than the rounds left."""
    left = rounds - score.played
    return left <= 0 or abs(score.wins - score.losses) > left


def result_of(score: Score) -> str:
    if score.wins > score.losses:
        return "won"
    return "lost" if score.wins < score.losses else "draw"


def fixed_outcome(kind: str, args: dict) -> Outcome:
    """Test: ``"won"`` (fair, kind) or ``"lost"`` (cheat, sly); skipped: ``"draw"``."""
    if kind == "skipped":
        return Outcome("draw")
    return Outcome("lost" if args.get("mode", DEFAULTS["mode"]) in ("cheat", "sly")
                   else "won")


def shake_offset(t: float) -> float:
    if t < 0 or t >= SHAKE_S:
        return 0.0
    return SHAKE_UNITS * math.sin(6 * math.pi * t / SHAKE_S) * (1 - t / SHAKE_S)


def clamp_size(value: object, default: int, lo: int, hi: int) -> int:
    if type(value) is not int:
        return default
    return min(hi, max(lo, value))


@dataclass(frozen=True, slots=True)
class HandLayout:
    score: Rect                   # the score line, then the round line beside it
    cards: tuple[Rect, Rect]      # yours, hers
    caption: Rect                 # up to two lines
    hands: tuple[Rect, Rect, Rect]
    single: Rect                  # Next round or Continue
    gap: int


def hand_layout(area: Sequence[float], *, score_h: float, caption_h: float,
                button_h: int) -> HandLayout:
    """The score line, the two cards (320 × 220, 80 apart), the caption and the buttons,
    stacked and centered; gaps of 16, else 4."""
    x, y, w, h = (float(v) for v in area)
    for gap in GAPS:
        total = score_h + gap + CARD[1] + gap + caption_h + gap + button_h
        if total <= h:
            break
    top = y + max(0.0, (h - total) / 2)
    cx = x + w / 2
    row_w = 2 * CARD[0] + CARD_GAP
    score = (cx - row_w / 2, top, float(row_w), float(score_h))
    cy = top + score_h + gap
    cards = ((cx - row_w / 2, cy, float(CARD[0]), float(CARD[1])),
             (cx + CARD_GAP / 2, cy, float(CARD[0]), float(CARD[1])))
    caption = (cx - row_w / 2, cy + CARD[1] + gap, float(row_w), float(caption_h))
    by = caption[1] + caption_h + gap
    hands_w = 3 * HAND_BUTTON_W + 2 * BUTTON_GAP
    hands = tuple((cx - hands_w / 2 + i * (HAND_BUTTON_W + BUTTON_GAP), by,
                   float(HAND_BUTTON_W), float(button_h)) for i in range(3))
    single = (cx - HAND_BUTTON_W / 2 - 20, by, float(HAND_BUTTON_W + 40), float(button_h))
    return HandLayout(score, cards, caption, hands, single, gap)    # type: ignore[arg-type]


__all__ = ["DEFAULTS", "HANDS", "Hand", "HandLayout", "MODES", "Score", "beats", "clamp_size",
           "finished", "fixed_outcome", "hand_layout", "her_hand", "loses_to", "outcome",
           "problem", "result_of", "shake_offset"]

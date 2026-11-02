"""AC-F05-03's fuzz generator for ``texttags.parse`` (F05 ``06-acceptance.md`` §5).

Standard library only; imports nothing from ``engine``. Each case is a line text of 0–10,000
characters built from ``{ } = /``, tag names (real, misspelled, upper case, other engines'),
values (good, out of range, with units, quoted), text with escaped characters (``"``,
``\\``, a line break), spaces, and Unicode (accents, combining marks, emoji, CJK, right-to-
left letters), and the source line that holds it: ``    "<escaped text>"``, so the text
starts at column 6. ``origins`` maps the text back to that line like a STRING token's
(``(text_offset, line, column)`` per slice; an escape is a slice of its own).

Half the cases are well formed (only good tags, nested properly), and half of those get one
random edit, so errors also appear deep inside long texts.

    python tests/fixtures/F05/fuzz_texttags.py --seed 1 [--count 2000]

prints one JSON object per case (``text``, ``source``, ``origins``). Deterministic: the same
seed gives the same cases on every OS (randomness only from ``random.Random(seed)``).
"""

import argparse
import json
import random
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass

LINE = 7                      # template X's line 7
FIRST_COLUMN = 6              # '    "' then the text
MAX_TEXT = 10_000

NAMES = ["b", "i", "color", "size", "speed", "pause", "var", "next",
         "B", "Color", "colour", "bold", "italic", "em", "w", "p", "cps", "nw", "shake", "blink",
         "", "/", "b!", "pausee", "INSTANT", "instant", "név", "色",
         "wave", "glitch", "Shake", "jitter", "zalgo"]           # F29 AC-F29-02
VALUES = ["", "#e05050", "#E05050", "#e0505", "e05050", "red", "0.5", "1", "30", "45", ".5",
          "0.5s", "50%", "2x", "-1", "+1", "0", "10", "instant", "INSTANT", "player_name",
          "hana.name", "wishes+1", "名前", "1" * 400, '"#e05050"', "a b", "x:y",
          "small", "medium", "large", "Large"]                   # F29 AC-F29-02
WORDS = ["Hello", "the lantern", "moved", "...", "—", "café", "é", "日本語の文",
         "😀", "👍🏽", "🇯🇵", "שלום", "مرحبا", "한국어", " ", "  ", "\t", "!", "?", "}", "}}", "{{",
         '"', "\\", "\n", "=", "/", ":"]


@dataclass(frozen=True)
class Case:
    text: str
    source: str
    origins: tuple[tuple[int, int, int], ...]


def _tag(rng: random.Random) -> str:
    roll = rng.random()
    if roll < 0.08:
        return "{" + rng.choice(["{", "}", "=", "/", ""]) * rng.randint(0, 3)
    close = "/" if rng.random() < 0.3 else ""
    name = rng.choice(NAMES)
    value = ""
    if rng.random() < 0.45:
        value = "=" + rng.choice(VALUES)
    end = "}" if rng.random() < 0.97 else ""
    return "{" + close + name + value + end


GOOD_OPEN = ["{b}", "{i}", "{color=#e05050}", "{color=#1E4A9C}", "{size=1.5}", "{size=0.5}",
             "{speed=2}", "{speed=instant}"]
GOOD_MARKS = ["{pause}", "{pause=0.6}", "{pause=30}", "{var=player_name}", "{var=名前}"]


def _well_formed(rng: random.Random, size: int) -> str:
    """Text whose tags are all good (style tags closed innermost first, at most 50 open),
    ending in ``{next}`` now and then; cut to ``size`` only between pieces."""
    parts: list[str] = []
    stack: list[str] = []
    length = 0
    while length < size:
        roll = rng.random()
        if roll < 0.15 and len(stack) < 50:
            piece = rng.choice(GOOD_OPEN)
            stack.append(piece[1:piece.find("=") if "=" in piece else -1])
        elif roll < 0.3 and stack:
            piece = "{/" + stack.pop() + "}"
        elif roll < 0.4:
            piece = rng.choice(GOOD_MARKS)
        else:
            piece = rng.choice(WORDS)
        parts.append(piece)
        length += len(piece)
    if rng.random() < 0.2:
        parts.append("{next}")
    if rng.random() < 0.5:
        parts.extend("{/" + name + "}" for name in reversed(stack))
    return "".join(parts)


def _mutate(rng: random.Random, text: str) -> str:
    """One random edit: a character from ``{ } = / :`` or a space inserted or replacing."""
    if not text:
        return text
    at = rng.randrange(len(text))
    char = rng.choice("{}=/: ")
    return text[:at] + char + text[at + (rng.random() < 0.5):]


def _text(rng: random.Random) -> str:
    size = rng.choice([rng.randint(0, 40), rng.randint(0, 400), rng.randint(0, MAX_TEXT)])
    if rng.random() < 0.5:
        text = _well_formed(rng, size)
        if rng.random() < 0.5:
            text = _mutate(rng, text)
        return text[:MAX_TEXT] if len(text) > MAX_TEXT else text
    parts: list[str] = []
    length = 0
    tag_share = rng.choice([0.1, 0.4, 0.8])
    while length < size:
        piece = _tag(rng) if rng.random() < tag_share else rng.choice(WORDS)
        parts.append(piece)
        length += len(piece)
    return "".join(parts)[:size]


_ESCAPES = {'"': '\\"', "\\": "\\\\", "\n": "\\n"}
_ESCAPE_RE = re.compile(r'["\\\n]')


def encode(text: str) -> tuple[str, tuple[tuple[int, int, int], ...]]:
    """The source line of ``text`` and its origins."""
    out = ['    "']
    column = FIRST_COLUMN
    origins: list[tuple[int, int, int]] = []
    position = 0
    for match in _ESCAPE_RE.finditer(text):
        at = match.start()
        if at > position:
            origins.append((position, LINE, column))
            out.append(text[position:at])
            column += at - position
        escape = _ESCAPES[match.group()]
        origins.append((at, LINE, column))
        out.append(escape)
        column += len(escape)
        position = at + 1
    if position < len(text):
        origins.append((position, LINE, column))
        out.append(text[position:])
    out.append('"')
    return "".join(out), tuple(origins)


def cases(seed: int, count: int) -> Iterator[Case]:
    rng = random.Random(seed)
    for _ in range(count):
        text = _text(rng)
        source, origins = encode(text)
        yield Case(text, source, origins)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--count", type=int, default=2000)
    args = parser.parse_args(argv)
    for case in cases(args.seed, args.count):
        print(json.dumps({"text": case.text, "source": case.source,
                          "origins": case.origins}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

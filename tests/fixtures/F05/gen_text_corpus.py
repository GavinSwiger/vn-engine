"""The F05 text corpus (``06-acceptance.md`` §5; AC-F05-14, AC-F05-33): seeded dialogue and
narration lines of 0 to 10,000 characters as written, mixing prose, long words, CJK runs,
emoji, ``\\n``, every tag (``{size}`` in 10% of the lines), ``{{``, and ``{var}`` names that
all have a ``default``.

    .venv/Scripts/python tests/fixtures/F05/gen_text_corpus.py --seed 1 --lines 2000 --out DIR

writes a game folder (``config.toml`` with the title off, ``script/main.vns``). Tests import
``script_text`` or ``write_game``. Pure: no engine import, so the script runs on its own.
Most lines are short and a few are long (70% up to 200 characters, 20% up to 1,000, 10% up
to 10,000), as in a real story; every tag is closed in order, so the story loads.
"""

import argparse
import random
import sys
from pathlib import Path

MAX_CHARS = 10_000                       # SR-F02-22, tags counted as written
WORDS = ("the", "lantern", "drifted", "past", "us", "and", "river", "festival", "wish",
         "paper", "light", "Hana", "said", "nothing", "for", "a", "while", "upstream",
         "bridge", "rail", "quiet", "slowly", "turned", "once", "again", "we", "watched")
LONG_WORDS = ("Donaudampfschifffahrtsgesellschaft", "supercalifragilisticexpialidocious",
              "x" * 60, "lantern-lit-riverbank-festival-night")
CJK = ("提灯が川を流れていく", "你好世界", "한국어 문장", "灯籠流し")
EMOJI = ("😀", "🏮", "👩‍👩‍👧", "🇯🇵", "é", "ñ")
COLORS = ("#9a1c14", "#1e4a9c")
DEFAULTS = (('player_name', '"Ren"'), ("wishes", "3"), ("ratio", "0.5"),
            ("empty", '""'), ("motto", '"' + "a wish " * 40 + '"'))
SPEAKERS = (None, None, None, None, None, None, None, "hana", "hana", "thought")


def _target(rng: random.Random) -> int:
    roll = rng.random()
    if roll < 0.7:
        return rng.randrange(0, 201)
    if roll < 0.9:
        return rng.randrange(200, 1001)
    return rng.randrange(1000, MAX_CHARS - 200)


def line_text(rng: random.Random) -> str:
    """One line's text as written between the quotes (escapes included)."""
    target = _target(rng)
    sized = rng.random() < 0.1
    out: list[str] = []
    length = 0
    open_tags: list[str] = []
    while length < target:
        roll = rng.random()
        if roll < 0.55:
            piece = rng.choice(WORDS) + " "
        elif roll < 0.6:
            piece = rng.choice(LONG_WORDS) + " "
        elif roll < 0.65:
            piece = rng.choice(CJK)
        elif roll < 0.7:
            piece = rng.choice(EMOJI)
        elif roll < 0.73:
            piece = "\\n"
        elif roll < 0.75:
            piece = "{{"
        elif roll < 0.78:
            piece = rng.choice(("{pause=0.3}", "{pause}"))
        elif roll < 0.82:
            piece = "{var=" + rng.choice(DEFAULTS)[0] + "} "
        elif roll < 0.92 and len(open_tags) < 4:
            name = rng.choice(("b", "i", "color", "speed") + (("size",) if sized else ()))
            opening = {"b": "{b}", "i": "{i}", "color": "{color=" + rng.choice(COLORS) + "}",
                       "speed": "{speed=" + rng.choice(("0.5", "2", "instant")) + "}",
                       "size": "{size=" + rng.choice(("0.5", "1.5", "2")) + "}"}[name]
            piece = opening
            open_tags.append(name)
        elif open_tags:
            piece = "{/" + open_tags.pop() + "}"
        else:
            continue
        out.append(piece)
        length += len(piece)
    if sized and not any(p.startswith("{size=") for p in out):
        out.insert(0, "{size=1.5}")
        open_tags.insert(0, "size")
    text = "".join(out)
    closing = "".join("{/" + name + "}" for name in reversed(open_tags))
    if rng.random() < 0.05:
        closing = "{next}" + closing
    return text + closing


def corpus_lines(seed: int = 1, lines: int = 2000) -> list[tuple[str | None, str]]:
    """(speaker or None, text as written) for each line."""
    rng = random.Random(seed)
    return [(rng.choice(SPEAKERS), line_text(rng)) for _ in range(lines)]


def script_text(seed: int = 1, lines: int = 2000) -> str:
    out = ["# The F05 text corpus, written by tests/fixtures/F05/gen_text_corpus.py.",
           'define hana = Character("Hana", color="#b03070")',
           'define thought = Character("", text_color="#1e4a9c", text_italic=True)',
           *(f"default {name} = {value}" for name, value in DEFAULTS),
           "label start:"]
    for speaker, text in corpus_lines(seed, lines):
        out.append(f'    {speaker + " " if speaker else ""}"{text}"')
    return "\n".join(out) + "\n"


def write_game(out: Path, *, seed: int = 1, lines: int = 2000) -> Path:
    (out / "script").mkdir(parents=True, exist_ok=True)
    (out / "script" / "main.vns").write_bytes(script_text(seed, lines).encode("utf-8"))
    (out / "config.toml").write_text('[game]\ntitle = "F05 text corpus"\n\n'
                                     "[title]\nenabled = false\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--lines", type=int, default=2000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    write_game(args.out, seed=args.seed, lines=args.lines)
    print(f"Wrote {args.out} (seed {args.seed}, {args.lines} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

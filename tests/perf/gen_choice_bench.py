"""Write the F07 choice bench game (``06-acceptance.md`` §5, AC-F07-43; ``04-technical.md``
§11, §15 "Perf"): F04's six-sprite bench scene with a looping menu of six two-line choices.

    .venv/Scripts/python tests/perf/gen_choice_bench.py --seed 1            # tests/perf/choice_bench/
    .venv/Scripts/python tests/perf/gen_choice_bench.py --seed 1 --scale 5  # small art (CI guards)

The output is gitignored: ``gen_stage_bench.py``'s art, ``config.toml`` (``art_height``,
the title off, ``[textbox] cps = 0`` so each question is shown at once), and
``script/main.vns``: one F04 bench scene (``scene`` plus six ``show``), then ``label talk``
with one menu: a question spoken by one of the six characters and six choices of exactly
60 characters of English prose, each ``jump talk`` (it loops forever). Each choice needs
exactly two lines at the default choice size (28) and text width (720 units): words are
drawn until the next would pass 60 characters, the last word is padded with "." to 60, and a
text is kept only when it is wider than 760 px in the bundled Noto Sans Regular at 28 px
(surely over one line) and wraps into two lines at 700 (a margin for kerning). The F07
harness (``test_choice_perf.py``) moves the focus every frame and picks every 2 s.

Only pygame and ``gen_stage_bench`` are needed (no ``engine`` import), so the script runs on
its own.
"""

import argparse
import random
import sys
from pathlib import Path

import pygame

try:
    from tests.perf import gen_stage_bench as stage
except ImportError:                            # run as a script: the folder is on sys.path
    import gen_stage_bench as stage            # type: ignore[no-redef]

OUT = Path(__file__).resolve().parent / "choice_bench"
FONTS = Path(__file__).resolve().parents[2] / "engine" / "data" / "fonts"
CHOICES = 6
CHOICE_CHARS = 60
TEXT_SIZE = 28
ONE_LINE_PX = 760                              # wider than this: surely two lines at 720
WRAP_WIDTH = 700                               # and within two lines with a margin
QUESTION = "Where should we go next?"
WORDS = ("the", "lanterns", "drifted", "past", "us", "on", "the", "river", "while", "the",
         "festival", "music", "carried", "over", "the", "water", "and", "nobody", "said",
         "anything", "for", "a", "long", "time", "because", "every", "wish", "was", "already",
         "written", "down", "somewhere", "upstream", "near", "the", "old", "bridge")


def _font() -> pygame.font.Font:
    pygame.font.init()
    return pygame.font.Font(str(FONTS / "NotoSans-Regular.ttf"), TEXT_SIZE)


def _lines(text: str, font: pygame.font.Font, width: int) -> int:
    """Lines of the greedy word wrap (F05's layout: a word goes on the line if it fits)."""
    space = font.size(" ")[0]
    lines, x = 1, 0
    for word in text.split(" "):
        w = font.size(word)[0]
        if x > 0 and x + space + w > width:
            lines, x = lines + 1, w
        else:
            x += (space if x > 0 else 0) + w
    return lines


def choice_text(rng: random.Random, font: pygame.font.Font) -> str:
    """One choice: 60 characters of prose that need exactly two lines."""
    while True:
        words: list[str] = []
        count = -1
        while True:
            word = rng.choice(WORDS)
            if count + 1 + len(word) > CHOICE_CHARS:
                break
            words.append(word)
            count += 1 + len(word)
        words[-1] += "." * (CHOICE_CHARS - count)
        text = " ".join(words)
        text = text[0].upper() + text[1:]
        if font.size(text)[0] > ONE_LINE_PX and _lines(text, font, WRAP_WIDTH) == 2:
            return text


def choice_texts(seed: int = 1) -> list[str]:
    rng = random.Random(seed)
    font = _font()
    out: list[str] = []
    while len(out) < CHOICES:
        text = choice_text(rng, font)
        if text not in out:
            out.append(text)
    return out


def script_text(seed: int = 1) -> str:
    tags = stage.TAGS
    out = ["# The F07 choice bench (06-acceptance.md §5), written by "
           "tests/perf/gen_choice_bench.py.",
           *(f'define {tag} = Character("{stage.NAMES[tag]}")' for tag in tags),
           "label start:",
           f"    scene bg {stage.BACKGROUNDS[0]}",
           *(f"    show {tag} {stage.EXPRESSIONS[0]} at {x}" for tag, x in zip(tags, stage.XS)),
           "    jump talk",
           "label talk:",
           "    menu:",
           f'        {tags[0]} "{QUESTION}"']
    for text in choice_texts(seed):
        out += [f'        "{text}":', "            jump talk"]
    return "\n".join(out) + "\n"


def config_text(*, fullscreen: bool = False, size: tuple[int, int] | None = None,
                art_height: int = stage.ART_HEIGHT) -> str:
    window = f"[window]\nfullscreen = {'true' if fullscreen else 'false'}\n"
    if size is not None:
        window += f"width = {size[0]}\nheight = {size[1]}\n"
    return ("# The F07 choice bench (tests/perf/gen_choice_bench.py).\n"
            '[game]\ntitle = "F07 choice bench"\nid = "f07-choice-bench"\n\n'
            "[title]\nenabled = false\n\n"
            "[textbox]\ncps = 0\n\n"
            f"[stage]\nart_height = {art_height}\n\n" + window)


def generate(out: Path, *, seed: int = 1, scale: int = 1) -> Path:
    """Write the bench game to ``out`` (files are overwritten) and return ``out``."""
    stage.generate(out, seed=seed, scale=scale)            # art, stamp, and its script
    (out / "script" / "main.vns").write_text(script_text(seed), encoding="utf-8", newline="\n")
    (out / "config.toml").write_text(config_text(art_height=stage.ART_HEIGHT // scale),
                                     encoding="utf-8", newline="\n")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    generate(args.out, seed=args.seed, scale=args.scale)
    print(f"Wrote {args.out} (seed {args.seed}, scale {args.scale})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

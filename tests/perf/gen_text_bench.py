"""Write the F05 typing bench games (``06-acceptance.md`` §5, AC-F05-44, 45; ``04-technical.md``
§15 "Perf"): F04's six-sprite bench scene with a looping script of full-page lines.

    .venv/Scripts/python tests/perf/gen_text_bench.py --seed 1            # tests/perf/text_bench/
    .venv/Scripts/python tests/perf/gen_text_bench.py --seed 1 --scale 4  # small art (CI guards)

The output is gitignored: ``text_bench/cps40/`` and ``text_bench/cps1000/``, the same game at
``[textbox] cps = 40`` and ``cps = 1000``. Each holds ``gen_stage_bench.py``'s art (the
images of the second folder are hard links to the first's where the file system allows,
copies otherwise), ``config.toml`` with ``art_height`` and the title off, and
``script/main.vns``: one F04 bench scene (``scene`` plus six ``show``), then ``label talk``
with ``LINES`` lines and ``jump talk`` (it loops forever). Every line is spoken by one of the
six characters (one name tab), has one ``{b}``, one ``{i}``, and one ``{color=#9a1c14}``
run, and fills exactly three lines of the box at text size 28: words are added while the
greedy wrap, measured with the bundled Noto Sans faces at 28 px against 900 of the 920-unit
text area (a margin for kerning), stays within three lines. The F05 harness auto-presses
every 2 s, so at 40 cps each line is cut short by a completing press, and at 1,000 cps it
types out in about 0.2 s.

Only pygame and ``gen_stage_bench`` are needed (no ``engine`` import), so the script runs on
its own.
"""

import argparse
import os
import random
import shutil
import sys
from pathlib import Path

import pygame

try:
    from tests.perf import gen_stage_bench as stage
except ImportError:                            # run as a script: the folder is on sys.path
    import gen_stage_bench as stage            # type: ignore[no-redef]

OUT = Path(__file__).resolve().parent / "text_bench"
FONTS = Path(__file__).resolve().parents[2] / "engine" / "data" / "fonts"
CPS = (40, 1000)
LINES = 12
TEXT_SIZE = 28
WRAP_WIDTH = 900                               # of the 920-unit text area (UI-F05-01)
NAME_COLORS = ("#b03070", "#3a6aa8", "#1e4a9c", "#9a1c14", "#5a3a8a", "#2a6a3a")
TAG_COLOR = "#9a1c14"
WORDS = ("the", "lanterns", "drifted", "past", "us", "on", "the", "river", "while", "the",
         "festival", "music", "carried", "over", "the", "water", "and", "nobody", "said",
         "anything", "for", "a", "long", "time", "because", "every", "wish", "was", "already",
         "written", "down", "somewhere", "upstream", "near", "the", "old", "bridge")


class Faces:
    """The bundled Regular, Bold, and Italic faces at ``TEXT_SIZE`` px (the reference size)."""

    def __init__(self) -> None:
        pygame.font.init()
        self.regular = pygame.font.Font(str(FONTS / "NotoSans-Regular.ttf"), TEXT_SIZE)
        self.bold = pygame.font.Font(str(FONTS / "NotoSans-Bold.ttf"), TEXT_SIZE)
        self.italic = pygame.font.Font(str(FONTS / "NotoSans-Italic.ttf"), TEXT_SIZE)

    def width(self, word: str, style: str) -> int:
        font = {"b": self.bold, "i": self.italic}.get(style, self.regular)
        return font.size(word)[0]


def _line_count(words: list[tuple[str, str]], faces: Faces) -> int:
    """Lines of the greedy wrap (as F05's layout: a word goes on the line if it fits)."""
    space = faces.width(" ", "")
    lines, x = 1, 0.0
    for word, style in words:
        w = faces.width(word, style)
        if x > 0 and x + space + w > WRAP_WIDTH:
            lines, x = lines + 1, w
        else:
            x += (space if x > 0 else 0) + w
    return lines


def line_text(rng: random.Random, faces: Faces) -> str:
    """One full-page line: three wrapped lines, with one bold, one italic, and one colored
    run of 1 to 3 words each, in that order and apart."""
    words: list[tuple[str, str]] = []
    plan = ["", "b", "", "i", "", "c", ""]
    runs = [rng.randint(1, 4), rng.randint(1, 3), rng.randint(2, 5), rng.randint(1, 3),
            rng.randint(2, 5), rng.randint(1, 3), 10_000]
    for style, count in zip(plan, runs):
        for _ in range(count):
            candidate = words + [(rng.choice(WORDS), style)]     # "c" measures as Regular
            if _line_count(candidate, faces) > 3:
                return _written(words)
            words = candidate
    raise AssertionError("unreachable: the last run is unbounded")


def _written(words: list[tuple[str, str]]) -> str:
    out, current = [], ""
    for word, style in words:
        if style != current:
            if current:
                out[-1] += _close(current)
            if style:
                word = _open(style) + word
            current = style
        out.append(word)
    if current:
        out[-1] += _close(current)
    text = " ".join(out)
    text = text[0].upper() + text[1:] if text and text[0].isalpha() else text
    assert all(tag in text for tag in ("{b}", "{i}", "{color=")), text
    return text + "."


def _open(style: str) -> str:
    return {"b": "{b}", "i": "{i}", "c": "{color=" + TAG_COLOR + "}"}[style]


def _close(style: str) -> str:
    return {"b": "{/b}", "i": "{/i}", "c": "{/color}"}[style]


def script_text(seed: int = 1) -> str:
    rng = random.Random(seed)
    faces = Faces()
    tags = stage.TAGS
    out = ["# The F05 typing bench (06-acceptance.md §5), written by tests/perf/gen_text_bench.py.",
           *(f'define {tag} = Character("{stage.NAMES[tag]}", color="{color}")'
             for tag, color in zip(tags, NAME_COLORS)),
           "label start:",
           f"    scene bg {stage.BACKGROUNDS[0]}",
           *(f"    show {tag} {stage.EXPRESSIONS[0]} at {x}" for tag, x in zip(tags, stage.XS)),
           "    jump talk",
           "label talk:"]
    for k in range(LINES):
        out.append(f'    {tags[k % len(tags)]} "{line_text(rng, faces)}"')
    out.append("    jump talk")
    return "\n".join(out) + "\n"


def config_text(cps: int, *, art_height: int = stage.ART_HEIGHT) -> str:
    return ("# The F05 typing bench (tests/perf/gen_text_bench.py).\n"
            f'[game]\ntitle = "F05 typing bench"\nid = "f05-text-bench-{cps}"\n\n'
            "[title]\nenabled = false\n\n"
            f"[textbox]\ncps = {cps}\n\n"
            f"[stage]\nart_height = {art_height}\n")


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def generate(out: Path, *, seed: int = 1, scale: int = 1) -> tuple[Path, ...]:
    """Write ``out/cps40`` and ``out/cps1000`` and return them."""
    first = out / f"cps{CPS[0]}"
    stage.generate(first, seed=seed, scale=scale)          # art, stamp, and its config
    script = script_text(seed)
    folders = []
    for cps in CPS:
        folder = out / f"cps{cps}"
        if folder != first:
            for ref in stage.image_refs():
                _link_or_copy(first / ref, folder / ref)
        (folder / "script").mkdir(parents=True, exist_ok=True)
        (folder / "script" / "main.vns").write_text(script, encoding="utf-8", newline="\n")
        (folder / "config.toml").write_text(config_text(cps, art_height=stage.ART_HEIGHT // scale),
                                            encoding="utf-8", newline="\n")
        (folder / stage.STAMP).write_text(stage.stamp(seed, scale), encoding="utf-8")
        folders.append(folder)
    return tuple(folders)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    for folder in generate(args.out, seed=args.seed, scale=args.scale):
        print(f"Wrote {folder} (seed {args.seed}, scale {args.scale})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

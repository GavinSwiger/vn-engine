"""Write the F04 six-sprite bench game (``06-acceptance.md`` §5.4, D1; ``04-technical.md``
§14 "Perf"): the PR-F04-20 scene that AC-F04-48 measures.

    .venv/Scripts/python tests/perf/gen_stage_bench.py --seed 1            # tests/perf/stage_bench/
    .venv/Scripts/python tests/perf/gen_stage_bench.py --seed 1 --out DIR  # another folder

The output is gitignored and is about 110 MB: two 1920×1080 noise backgrounds and 12 sprites
of 1200×2000 RGBA (six tags × two expressions), each about 45% transparent with anti-aliased
edges (the silhouette is drawn at half size and smooth-scaled up), noisy so it decodes and
blends at a realistic cost. ``config.toml`` sets ``art_height = 1080`` and skips the title
(the game starts at once). ``script/main.vns`` alternates two scenes, each a ``scene`` plus
six ``show``\\ s at x = 160, 352, 544, 736, 928, 1120, with a line that changes an expression on
the dialogue line, one that moves a sprite, and one that puts a sprite ``behind`` another,
then ``jump start`` (it loops forever). Every line changes the stage, so the 5 s
auto-advance harness (``stage_bench_harness.py``) makes one stage change per Advance.

``--scale N`` divides every image size and ``art_height`` by N (the layout on the canvas is
the same); the CI guards use a small scale, the AC uses 1. Only pygame is needed: no
``engine`` or ``tests`` import, so the script runs on its own.
"""

import argparse
import random
import sys
from pathlib import Path

import pygame

OUT = Path(__file__).resolve().parent / "stage_bench"
STAMP = "stamp.txt"                       # "seed 1 scale 1": what the folder holds

BG_SIZE = (1920, 1080)
SPRITE_SIZE = (1200, 2000)
ART_HEIGHT = 1080
XS = (160, 352, 544, 736, 928, 1120)      # 06 §5.4
TAGS = ("aki", "ben", "cho", "dai", "eri", "fumi")
NAMES = {"aki": "Aki", "ben": "Ben", "cho": "Cho", "dai": "Dai", "eri": "Eri",
         "fumi": "Fumi"}
EXPRESSIONS = ("calm", "smile")
BACKGROUNDS = ("plaza", "street")
MOVER, MOVE_X = "cho", (600, 480)         # one sprite moves in each scene
BEHIND = ("eri", "ben")                   # eri goes behind ben in each scene

TINTS = ((255, 200, 180), (180, 220, 255), (200, 255, 190), (255, 240, 170),
         (230, 190, 255), (190, 255, 245))


def script_text() -> str:
    """The bench story: two scenes of four lines, then ``jump start``."""
    out = ["# The F04 bench scene (06-acceptance.md §5.4), written by tests/perf/gen_stage_bench.py.",
           *(f'define {tag} = Character("{NAMES[tag]}")' for tag in TAGS),
           "label start:"]
    for n, (bg, expr, other, move_x) in enumerate(zip(BACKGROUNDS, EXPRESSIONS,
                                                      reversed(EXPRESSIONS), MOVE_X), 1):
        out.append(f"    scene bg {bg}")
        out += [f"    show {tag} {expr} at {x}" for tag, x in zip(TAGS, XS)]
        out.append(f'    "Scene {n}: six on the stage."')
        out.append(f'    {TAGS[0]} {other} "A new face on the dialogue line."')
        out.append(f"    show {MOVER} at {move_x}")
        out.append(f'    "{NAMES[MOVER]} moves."')
        out.append(f"    show {BEHIND[0]} behind {BEHIND[1]}")
        out.append(f'    "{NAMES[BEHIND[0]]} steps behind {NAMES[BEHIND[1]]}."')
    out.append("    jump start")
    return "\n".join(out) + "\n"


def config_text(*, fullscreen: bool = False, art_height: int = ART_HEIGHT) -> str:
    return (
        "# The F04 bench game (tests/perf/gen_stage_bench.py).\n"
        '[game]\ntitle = "F04 stage bench"\nid = "f04-stage-bench"\n\n'
        "[title]\nenabled = false\n\n"
        f"[window]\nfullscreen = {'true' if fullscreen else 'false'}\n\n"
        f"[stage]\nart_height = {art_height}\n")


def image_refs() -> list[str]:
    """Every image file of the bench game, game-relative."""
    return ([f"images/bg/{bg}.png" for bg in BACKGROUNDS]
            + [f"images/{tag}/{expr}.png" for tag in TAGS for expr in EXPRESSIONS])


def background(rnd: random.Random, size: tuple[int, int], tint) -> pygame.Surface:
    w, h = size
    surface = pygame.image.frombytes(rnd.randbytes(w * h * 3), size, "RGB")
    surface.fill(tint, special_flags=pygame.BLEND_RGB_MULT)
    return surface


def sprite(rnd: random.Random, size: tuple[int, int], tint) -> pygame.Surface:
    """Noise inside a head-and-body silhouette, about 45% of the pixels fully transparent,
    with soft (anti-aliased) edges."""
    w, h = size
    out = pygame.Surface(size, pygame.SRCALPHA, 32)
    out.blit(pygame.image.frombytes(rnd.randbytes(w * h * 3), size, "RGB"), (0, 0))
    out.fill((*tint, 255), special_flags=pygame.BLEND_RGBA_MULT)
    half = (max(1, w // 2), max(1, h // 2))
    mask = pygame.Surface(half, pygame.SRCALPHA, 32)
    mask.fill((255, 255, 255, 0))
    hw, hh = half
    white = (255, 255, 255, 255)
    pygame.draw.circle(mask, white, (hw // 2, round(hh * 0.165)), round(hw * 0.217))
    pygame.draw.rect(mask, white, (round(hw / 6), round(hh * 0.28), round(hw * 2 / 3),
                                   hh - round(hh * 0.28)), border_radius=round(hw * 0.2))
    out.blit(pygame.transform.smoothscale(mask, size), (0, 0),
             special_flags=pygame.BLEND_RGBA_MULT)
    return out


def transparent_fraction(surface: pygame.Surface) -> float:
    """The share of fully transparent pixels."""
    w, h = surface.get_size()
    return 1.0 - pygame.mask.from_surface(surface, 1).count() / (w * h)


def generate(out: Path, *, seed: int = 1, scale: int = 1) -> Path:
    """Write the bench game to ``out`` (files are overwritten) and return ``out``."""
    rnd = random.Random(seed)
    bg_size = (BG_SIZE[0] // scale, BG_SIZE[1] // scale)
    sprite_size = (SPRITE_SIZE[0] // scale, SPRITE_SIZE[1] // scale)
    (out / "script").mkdir(parents=True, exist_ok=True)
    (out / "script" / "main.vns").write_text(script_text(), encoding="utf-8", newline="\n")
    (out / "config.toml").write_text(config_text(art_height=ART_HEIGHT // scale),
                                     encoding="utf-8", newline="\n")
    for i, name in enumerate(BACKGROUNDS):
        path = out / "images" / "bg" / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(background(rnd, bg_size, TINTS[i]), str(path))
    for i, tag in enumerate(TAGS):
        for j, expr in enumerate(EXPRESSIONS):
            path = out / "images" / tag / f"{expr}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            pygame.image.save(sprite(rnd, sprite_size, TINTS[(i + j) % len(TINTS)]),
                              str(path))
    (out / STAMP).write_text(stamp(seed, scale), encoding="utf-8")
    return out


def stamp(seed: int, scale: int) -> str:
    return f"seed {seed} scale {scale}\n"


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

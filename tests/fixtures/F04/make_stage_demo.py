"""Write a tiny game that shows F04's stage (build step 5 milestone) into a folder:

    .venv/Scripts/python tests/fixtures/F04/make_stage_demo.py <folder>
    .venv/Scripts/python -m engine run <folder>

The example game in ``game/`` has its own art since F04 build step 8
(``make_example_art.py``); this demo shows more of the stage, with generated art: two
backgrounds, two characters with expressions (transparent around the
figure), a solid-color ``image`` declaration, author positions, layers, zoom and flip, and
one missing image (the placeholder). Only pygame is needed; nothing is written outside
``<folder>``.
"""

import sys
from pathlib import Path

import pygame

SCRIPT = '''\
define hana = Character("Hana", color="#b03070")
define d = Character("Daichi", color="#3a6aa8", image_tag="daichi")
image bg dusk = "#2b2140"

label start:
    scene bg river
    "A background image fills the whole window, at any window size."
    show hana happy
    "Hana appears at center: her feet stand on the bottom edge."
    show hana at left
    show daichi grin at right
    d "Daichi steps in at right, while Hana moves to the left."
    hana sad "Words on a dialogue line change her expression in the same frame."
    show railing layer 10
    "The railing is on layer 10, so it is always in front."
    show hana at stall_spot zoom 1.3 flip on
    hana happy "stall_spot comes from config.toml; zoom and flip scale and mirror her."
    scene bg dusk
    show hana happy
    show daichi sigh behind hana at 760
    "scene cleared the stage. bg dusk is a plain color declared with image."
    show ghost at 640
    "ghost has no image file, so a placeholder shows where it would be."
    hide ghost
    "That's the stage. Press Esc for the game menu."
'''

CONFIG = '''\
[game]
title = "Stage demo"

[stage.positions]
stall_spot = 980
'''


def _background(size, top, bottom, accents) -> pygame.Surface:
    width, height = size
    surface = pygame.Surface(size)
    for y in range(height):
        t = y / (height - 1)
        surface.fill([round(a + (b - a) * t) for a, b in zip(top, bottom)], (0, y, width, 1))
    for x, y, r, color in accents:
        pygame.draw.circle(surface, color, (x, y), r)
    return surface


def _figure(body, face, mouth: str) -> pygame.Surface:
    """A 300×600 figure on a transparent background, with a face that shows the
    expression."""
    surface = pygame.Surface((300, 600), pygame.SRCALPHA)
    surface.fill((0, 0, 0, 0))
    pygame.draw.ellipse(surface, body, (40, 200, 220, 420))
    pygame.draw.circle(surface, face, (150, 120), 95)
    pygame.draw.circle(surface, (40, 30, 30), (115, 105), 10)
    pygame.draw.circle(surface, (40, 30, 30), (185, 105), 10)
    if mouth == "happy":
        pygame.draw.arc(surface, (120, 40, 40), (105, 110, 90, 60), 3.4, 6.0, 6)
    elif mouth == "sad":
        pygame.draw.arc(surface, (120, 40, 40), (105, 150, 90, 50), 0.3, 2.8, 6)
    else:
        pygame.draw.line(surface, (120, 40, 40), (115, 160), (185, 160), 6)
    return surface


def _railing() -> pygame.Surface:
    surface = pygame.Surface((1280, 160), pygame.SRCALPHA)
    surface.fill((0, 0, 0, 0))
    surface.fill((90, 60, 40), (0, 20, 1280, 18))
    for x in range(20, 1280, 80):
        surface.fill((90, 60, 40), (x, 20, 14, 140))
    return surface


def write_demo(root: Path) -> None:
    pygame.init()
    try:
        images = {
            "images/bg/river.png": _background(
                (1920, 1080), (20, 30, 70), (60, 90, 120),
                [(300 + 260 * k, 180 + 40 * (k % 3), 18, (255, 200, 120)) for k in range(6)]),
            "images/hana/happy.png": _figure((230, 140, 170), (250, 220, 200), "happy"),
            "images/hana/sad.png": _figure((230, 140, 170), (250, 220, 200), "sad"),
            "images/daichi/grin.png": _figure((110, 150, 210), (240, 210, 190), "happy"),
            "images/daichi/sigh.png": _figure((110, 150, 210), (240, 210, 190), "flat"),
            "images/railing.png": _railing(),
        }
        for ref, surface in images.items():
            path = root / ref
            path.parent.mkdir(parents=True, exist_ok=True)
            pygame.image.save(surface, str(path))
    finally:
        pygame.quit()
    (root / "script").mkdir(parents=True, exist_ok=True)
    (root / "script" / "main.vns").write_text(SCRIPT, encoding="utf-8")
    (root / "config.toml").write_text(CONFIG, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: make_stage_demo.py <folder>")
    write_demo(Path(sys.argv[1]))
    print(f"Written. Run it with: python -m engine run {sys.argv[1]}")

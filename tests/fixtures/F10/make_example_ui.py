"""Draw the title art, logo, and button frame of the example game *Paper Lanterns* (F10 build
step 9, PR-F10-42) into ``game/gui/``:

    .venv/Scripts/python tests/fixtures/F10/make_example_ui.py            # game/
    .venv/Scripts/python tests/fixtures/F10/make_example_ui.py <folder>   # another game

Everything is drawn here with pygame, so the art is original and can be redrawn after a
change. The background reuses the drawing helpers of F04's ``make_example_art.py`` (sky
gradients, glows, paper lanterns), so the title matches the story's two backgrounds. Shapes
are drawn at twice the size and smooth-scaled down. Nothing is random but the stars, which
use a fixed seed. Only ``<folder>/gui/`` is written; ``game/config.toml`` names the files:

- ``gui/title_bg.png`` 1280×720: lanterns rising over the river at night. The left third,
  under the logo and the buttons, is kept quiet and dark.
- ``gui/logo.png`` 560×200 (the title's logo box, so it is never scaled up): "Paper
  Lanterns" in the bundled Noto Sans Bold, cream with a plum outline, beside a lantern. The
  words are drawn into the picture, so the image needs no font at run time.
- ``gui/button.png`` 72×72, a nine-slice for the default ``frame_slice_width = 24``: warm
  paper with a lantern-red border and a thin gold line. The edges are the same all along, so
  they stretch cleanly; the dark default ``button.text_color`` reads on it (the focused,
  pressed, and disabled looks stay the drawn ones).

``UI`` lists every file; ``tests/app/test_ui_flow.py`` (AC-F10-70) checks that ``game/gui/``
holds them.
"""

import math
import random
import sys
from collections.abc import Callable
from pathlib import Path

if __package__ in (None, ""):                # run as a script: make ``tests`` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pygame

from tests.fixtures.F04 import make_example_art as art

REPO = Path(__file__).resolve().parents[3]
GAME = REPO / "game"
BOLD_FONT = REPO / "engine" / "data" / "fonts" / "NotoSans-Bold.ttf"
SS = art.SS                                   # drawn at 2× and smooth-scaled down
BG_SIZE = (1280, 720)
LOGO_SIZE = (560, 200)                        # the title's logo box at 100% text
BUTTON_SIZE = (72, 72)
SLICE = 24                                    # [theme.button] frame_slice_width default

PLUM = (74, 48, 64)                           # F04's outline color
CREAM = (255, 244, 228)
PAPER = (255, 246, 232)
LANTERN_RED = (192, 72, 88)
GOLD = (224, 172, 92)

Color = tuple[int, int, int]


# --- Title background -----------------------------------------------------------------------

def _sky_lantern(surface: pygame.Surface, x: float, y: float, size: float,
                 paper: Color) -> None:
    """A rising sky lantern: a glowing paper body, wider at the top, a dark rim below."""
    art._glow(surface, (x, y), size * 3.0, (255, 196, 130), 90)
    top, bottom = size * 0.9, size * 0.62
    h = size * 1.5
    body = [(x - top, y - h / 2), (x + top, y - h / 2), (x + bottom, y + h / 2),
            (x - bottom, y + h / 2)]
    pygame.draw.polygon(surface, paper, body)
    pygame.draw.ellipse(surface, (255, 238, 196),
                        (x - top * 0.45, y - h * 0.15, top * 0.9, h * 0.5))
    pygame.draw.rect(surface, (110, 70, 72), (x - bottom, y + h / 2 - 2, 2 * bottom, 6))


def title_bg() -> pygame.Surface:
    """Night over the river: a deep sky warming toward the horizon, far hills, the water
    with the lanterns' light on it, and lanterns rising on the right."""
    w, h = BG_SIZE[0] * SS, BG_SIZE[1] * SS
    s = pygame.Surface((w, h))
    horizon = int(h * 0.68)
    art._gradient(s, (0, 0, w, horizon), [(0.0, (22, 20, 52)), (0.5, (62, 46, 104)),
                                          (0.85, (150, 92, 140)), (1.0, (214, 136, 150))])
    stars = random.Random(10)
    for _ in range(110):
        x, y = stars.uniform(0, w), stars.uniform(0, horizon * 0.6)
        pygame.draw.circle(s, (255, 244, 230), (x, y), stars.choice((2, 2, 3, 4)))
    art._glow(s, (w * 0.74, horizon - 40), 700, (255, 210, 170), 130)
    pygame.draw.polygon(s, (88, 60, 112),
                        art._hills(w, horizon - 50, [(34, 300, 0.9), (18, 110, 2.1)],
                                   horizon + 30))
    pygame.draw.polygon(s, (58, 42, 86),
                        art._hills(w, horizon - 14, [(22, 210, 0.2), (10, 70, 1.4)],
                                   horizon + 30))
    art._gradient(s, (0, horizon, w, h - horizon), [(0.0, (110, 76, 128)),
                                                    (0.5, (54, 40, 88)), (1.0, (26, 22, 52))])
    for k in range(10):                                       # light on the water
        y = horizon + 50 + k * k * 8
        x0 = w * 0.74 - 260 + (k % 3) * 60
        pygame.draw.line(s, (232, 176, 170), (x0, y), (x0 + 240 - k * 16, y), 6)
    lanterns = random.Random(3)
    for _ in range(26):                                       # small ones, far away
        x = lanterns.uniform(w * 0.46, w * 0.98)
        y = lanterns.uniform(h * 0.08, horizon - 60)
        _sky_lantern(s, x, y, lanterns.uniform(7, 13), (255, 206, 150))
    for x, y, size in ((0.60, 0.36, 26), (0.83, 0.24, 34), (0.93, 0.50, 22),
                       (0.70, 0.12, 18), (0.53, 0.56, 16)):   # near ones
        _sky_lantern(s, w * x, h * y, size, (255, 214, 160))
    for k, (x, y) in enumerate([(0.58, 0.80), (0.70, 0.76), (0.82, 0.83), (0.94, 0.78)]):
        lx, ly = w * x, h * y                                 # floating on the river
        pygame.draw.line(s, (255, 206, 150), (lx, ly + 22), (lx, ly + 70), 6)
        art._lantern(s, lx, ly, 18 + (k % 2) * 5, (255, 190, 140))
    bank = [(0, h), (0, h * 0.90), (w * 0.18, h * 0.88), (w * 0.42, h * 0.91),
            (w * 0.66, h * 0.93), (w, h * 0.92), (w, h)]
    pygame.draw.polygon(s, (24, 20, 44), bank)
    for x in range(0, int(w * 0.5), 26):                     # grass on the near bank
        base = h * 0.90
        pygame.draw.line(s, (36, 30, 60), (x, base + 10), (x + 10, base - 24 - (x * 7) % 30), 5)
    return s


# --- Logo -----------------------------------------------------------------------------------

def _fit_font(text: str, width: int, start: int) -> pygame.font.Font:
    size = start
    while True:
        font = pygame.font.Font(str(BOLD_FONT), size)
        if font.size(text)[0] <= width or size <= 20:
            return font
        size -= 2


def _outlined(text: str, font: pygame.font.Font, fill: Color, outline: Color,
              thickness: int) -> pygame.Surface:
    """``text`` in ``fill`` with an ``outline`` of ``thickness`` pixels all round."""
    face = font.render(text, True, fill)
    edge = font.render(text, True, outline)
    w, h = face.get_size()
    out = pygame.Surface((w + 2 * thickness, h + 2 * thickness), pygame.SRCALPHA)
    out.fill((*outline, 0))
    for step in range(16):
        angle = step * math.pi / 8
        out.blit(edge, (thickness + round(thickness * math.cos(angle)),
                        thickness + round(thickness * math.sin(angle))))
    out.blit(face, (thickness, thickness))
    return out


def logo() -> pygame.Surface:
    """"Paper Lanterns" beside a hanging lantern, on a transparent ground."""
    w, h = LOGO_SIZE[0] * SS, LOGO_SIZE[1] * SS
    s = art._layer((w, h), (*PLUM, 0))
    lantern_x, cy = 152, h // 2               # its glow (radius 147) stays inside the picture
    pygame.draw.line(s, PLUM, (lantern_x, 24), (lantern_x, cy - 70), 8)
    art._lantern(s, lantern_x, cy, 46, (255, 168, 150), hanging=True)
    text = "Paper Lanterns"
    left = 236
    font = _fit_font(text, w - left - 24, 150)
    words = _outlined(text, font, CREAM, PLUM, 10)
    shadow = _outlined(text, font, (20, 14, 30), (20, 14, 30), 10)
    shadow.set_alpha(110)
    y = cy - words.get_height() // 2
    s.blit(shadow, (left + 6, y + 8))
    s.blit(words, (left, y))
    return s


# --- Button frame ---------------------------------------------------------------------------

def button() -> pygame.Surface:
    """Warm paper, a lantern-red border, and a thin gold line inside it. Every edge is the
    same along its length, so the nine-slice stretches it without seams."""
    w, h = BUTTON_SIZE[0] * SS, BUTTON_SIZE[1] * SS
    s = art._layer((w, h), (*LANTERN_RED, 0))
    pygame.draw.rect(s, LANTERN_RED, (0, 0, w, h), 0, 14 * SS)
    pygame.draw.rect(s, PAPER, (3 * SS, 3 * SS, w - 6 * SS, h - 6 * SS), 0, 11 * SS)
    pygame.draw.rect(s, GOLD, (7 * SS, 7 * SS, w - 14 * SS, h - 14 * SS), SS, 7 * SS)
    return s


# --- The files ------------------------------------------------------------------------------

UI: dict[str, tuple[Callable[[], pygame.Surface], tuple[int, int]]] = {
    "gui/title_bg.png": (title_bg, BG_SIZE),
    "gui/logo.png": (logo, LOGO_SIZE),
    "gui/button.png": (button, BUTTON_SIZE),
}


def write_ui(game: Path) -> list[Path]:
    """Draw every file of ``UI`` under ``game`` and return the paths written."""
    pygame.init()
    written = []
    try:
        for ref, (draw, size) in UI.items():
            path = game / ref
            art._save(draw(), size, path)
            written.append(path)
    finally:
        pygame.quit()
    return written


if __name__ == "__main__":
    if len(sys.argv) > 2:
        sys.exit("usage: make_example_ui.py [game folder]")
    root = Path(sys.argv[1]) if len(sys.argv) == 2 else GAME
    for path in write_ui(root):
        print(f"{path.stat().st_size:>8,}  {path}")

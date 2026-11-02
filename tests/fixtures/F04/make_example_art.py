"""Draw the art of the example game *Paper Lanterns* (F04 build step 8, PR-F04-26) into
``game/images/``:

    .venv/Scripts/python tests/fixtures/F04/make_example_art.py            # game/
    .venv/Scripts/python tests/fixtures/F04/make_example_art.py <folder>   # another game

Everything is drawn here with pygame, so the art is original and can be redrawn after a
change: two 1280×720 backgrounds, the sprites of Hana and Daichi (400×680, drawn for the
default ``art_height = 720``), one PNG per expression the script uses, and (F21 step 5) the
codex picture of the paper lantern item (640×360, ``images/items/lantern.png``: the codex
page scales it down to its 448×200 box). Shapes are drawn at
twice the size and smooth-scaled down, which gives soft edges. Nothing is random but the
stars, which use a fixed seed. Only ``<folder>/images/`` is written.

``ART`` lists every file; ``tests/runtime/test_example_game_stage.py`` checks that
``game/images/`` holds exactly these files.
"""

import math
import random
import sys
from collections.abc import Callable
from pathlib import Path

import pygame

GAME = Path(__file__).resolve().parents[3] / "game"
SS = 2                                   # drawn at 2× and smooth-scaled down
BG_SIZE = (1280, 720)
SPRITE_SIZE = (400, 680)
ITEM_SIZE = (640, 360)                   # F21: a codex picture, 16:9

OUTLINE = (74, 48, 64)
SKIN = (253, 228, 214)
WHITE = (255, 250, 252)
MOUTH = (176, 72, 96)
BLUSH = (255, 150, 170)

Color = tuple[int, int, int]
Point = tuple[float, float]


# --- Helpers ------------------------------------------------------------------------------

def _layer(size: tuple[int, int], fill: tuple[int, int, int, int] = (*OUTLINE, 0)
           ) -> pygame.Surface:
    """A transparent surface; its clear pixels carry the outline color, so smooth-scaling
    fades edges toward the outline instead of toward black."""
    surface = pygame.Surface(size, pygame.SRCALPHA)
    surface.fill(fill)
    return surface


def _poly(surface: pygame.Surface, color, points, outline: int = 6) -> None:
    pygame.draw.polygon(surface, color, points)
    if outline:
        pygame.draw.polygon(surface, OUTLINE, points, outline)


def _ellipse(surface: pygame.Surface, color, rect, outline: int = 6) -> None:
    pygame.draw.ellipse(surface, color, rect)
    if outline:
        pygame.draw.ellipse(surface, OUTLINE, rect, outline)


def _clip_to(surface: pygame.Surface, points) -> None:
    """Keep only the part of ``surface`` inside the polygon ``points``."""
    mask = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    mask.fill((255, 255, 255, 0))
    pygame.draw.polygon(mask, (255, 255, 255, 255), points)
    surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)


def _glow(surface: pygame.Surface, center: Point, radius: float, color: Color,
          strength: int = 140) -> None:
    """A soft radial light, strongest in the middle."""
    r = int(radius)
    glow = pygame.Surface((2 * r + 2, 2 * r + 2), pygame.SRCALPHA)
    glow.fill((*color, 0))
    for step in range(r, 0, -2):
        alpha = round(strength * (1 - step / r) ** 2)
        pygame.draw.circle(glow, (*color, alpha), (r + 1, r + 1), step)
    surface.blit(glow, (center[0] - r - 1, center[1] - r - 1))


def _gradient(surface: pygame.Surface, rect, stops: list[tuple[float, Color]]) -> None:
    """Vertical gradient through ``stops`` ((0..1 position, color), ascending)."""
    x, y, w, h = rect
    for row in range(h):
        t = row / max(1, h - 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                k = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                color = [round(a + (b - a) * k) for a, b in zip(c0, c1)]
                break
        surface.fill(color, (x, y + row, w, 1))


def _hills(width: int, base: float, waves: list[tuple[float, float, float]],
           bottom: int) -> list[Point]:
    """A skyline of summed sine waves (amplitude, wavelength, phase) above ``base``."""
    points = [(0, bottom)]
    for x in range(0, width + 1, 16):
        y = base - sum(a * math.sin(x / length + phase) for a, length, phase in waves)
        points.append((x, y))
    points.append((width, bottom))
    return points


def _lantern(surface: pygame.Surface, x: float, y: float, size: float, paper: Color,
             *, hanging: bool = False) -> None:
    """A round paper lantern with a warm glow; ``hanging`` adds a cap and a cord."""
    _glow(surface, (x, y), size * 3.2, (255, 200, 140), 110)
    w, h = size * 1.6, size * 2.0
    rect = pygame.Rect(0, 0, w, h)
    rect.center = (round(x), round(y))
    pygame.draw.ellipse(surface, paper, rect)
    for k in (-0.25, 0.25):
        pygame.draw.line(surface, tuple(max(0, c - 40) for c in paper),
                         (x + k * w, y - h * 0.42), (x + k * w, y + h * 0.42), max(2, SS))
    pygame.draw.ellipse(surface, (255, 236, 200),
                        (x - w * 0.18, y - h * 0.2, w * 0.36, h * 0.4))
    if hanging:
        pygame.draw.rect(surface, (70, 50, 60), (x - w * 0.22, y - h * 0.58, w * 0.44, h * 0.14))
        pygame.draw.rect(surface, (70, 50, 60), (x - w * 0.22, y + h * 0.46, w * 0.44, h * 0.12))


def _save(surface: pygame.Surface, size: tuple[int, int], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(pygame.transform.smoothscale(surface, size), str(path))


# --- Backgrounds --------------------------------------------------------------------------

def river_dusk() -> pygame.Surface:
    """The riverbank at dusk: a pink sky, hills, lanterns on a string and on the water."""
    w, h = BG_SIZE[0] * SS, BG_SIZE[1] * SS
    s = pygame.Surface((w, h))
    horizon = int(h * 0.60)
    _gradient(s, (0, 0, w, horizon), [(0.0, (104, 88, 156)), (0.55, (214, 150, 186)),
                                      (1.0, (255, 206, 184))])
    _glow(s, (w * 0.68, horizon - 20), 520, (255, 226, 190), 150)
    pygame.draw.polygon(s, (170, 136, 178),
                        _hills(w, horizon - 70, [(46, 260, 0.4), (28, 120, 1.7)], horizon + 40))
    pygame.draw.polygon(s, (128, 100, 150),
                        _hills(w, horizon - 18, [(30, 190, 2.2), (14, 80, 0.3)], horizon + 40))
    _gradient(s, (0, horizon, w, h - horizon), [(0.0, (196, 150, 190)), (0.4, (130, 104, 166)),
                                                (1.0, (84, 68, 124))])
    for k in range(9):                                       # light on the water
        y = horizon + 40 + k * k * 9
        x0 = w * 0.68 - 300 + (k % 3) * 70
        pygame.draw.line(s, (232, 184, 206), (x0, y), (x0 + 260 - k * 18, y), 6)
    bank = [(0, h), (0, h * 0.86), (w * 0.22, h * 0.83), (w * 0.5, h * 0.85),
            (w * 0.78, h * 0.82), (w, h * 0.84), (w, h)]
    pygame.draw.polygon(s, (92, 78, 112), bank)
    for k, (x, y) in enumerate([(0.12, 0.74), (0.3, 0.70), (0.47, 0.77), (0.62, 0.69),
                                (0.84, 0.73), (0.93, 0.66), (0.22, 0.65)]):
        lx, ly = w * x, h * y
        pygame.draw.line(s, (255, 214, 160), (lx, ly + 30), (lx, ly + 90), 8)  # reflection
        _lantern(s, lx, ly, 22 + (k % 3) * 4, (255, 196, 140))
    # A string of festival lanterns across the top.
    cord = [(x, 90 + 0.00012 * (x - w / 2) ** 2 * -1 + 140) for x in range(0, w + 1, 20)]
    pygame.draw.lines(s, (70, 50, 60), False, cord, 5)
    for k, x in enumerate(range(160, w, 300)):
        y = 90 - 0.00012 * (x - w / 2) ** 2 + 140
        paper = (255, 150, 170) if k % 2 else (255, 214, 150)
        pygame.draw.line(s, (70, 50, 60), (x, y), (x, y + 40), 4)
        _lantern(s, x, y + 90, 40, paper, hanging=True)
    return s


def bridge_night() -> pygame.Surface:
    """The footbridge at night: stars, a moon, lanterns drifting below, the railing."""
    w, h = BG_SIZE[0] * SS, BG_SIZE[1] * SS
    s = pygame.Surface((w, h))
    horizon = int(h * 0.50)
    _gradient(s, (0, 0, w, horizon), [(0.0, (30, 26, 64)), (0.7, (70, 54, 112)),
                                      (1.0, (122, 88, 140))])
    stars = random.Random(7)
    for _ in range(140):
        x, y = stars.uniform(0, w), stars.uniform(0, horizon * 0.85)
        pygame.draw.circle(s, (255, 244, 230), (x, y), stars.choice((2, 3, 3, 4)))
    _glow(s, (w * 0.9, h * 0.14), 300, (255, 240, 220), 120)
    pygame.draw.circle(s, (255, 246, 228), (w * 0.9, h * 0.14), 84)
    pygame.draw.circle(s, (236, 222, 214), (w * 0.9 + 26, h * 0.14 - 18), 18)
    pygame.draw.polygon(s, (52, 42, 86),
                        _hills(w, horizon - 30, [(26, 300, 1.0), (12, 90, 0.2)], horizon + 20))
    for k in range(40):                                      # far town lights
        x = (k * 157) % w
        pygame.draw.circle(s, (255, 214, 150), (x, horizon - 10 - (k * 37) % 30), 3)
    _gradient(s, (0, horizon, w, h - horizon), [(0.0, (64, 52, 104)), (1.0, (28, 24, 56))])
    for k, (x, y) in enumerate([(0.08, 0.58), (0.2, 0.62), (0.33, 0.56), (0.45, 0.6),
                                (0.58, 0.55), (0.7, 0.61), (0.86, 0.57), (0.95, 0.63)]):
        lx, ly = w * x, h * y
        pygame.draw.line(s, (255, 200, 150), (lx, ly + 18), (lx, ly + 60), 6)
        _lantern(s, lx, ly, 12 + (k % 3) * 3, (255, 190, 140))
    wood, dark = (126, 88, 84), (84, 58, 64)
    top, low, deck = int(h * 0.66), int(h * 0.76), int(h * 0.84)
    pygame.draw.rect(s, dark, (0, deck, w, h - deck))
    for x in range(-40, w, 200):                             # deck planks
        pygame.draw.line(s, (70, 48, 56), (x, deck), (x - 120, h), 4)
    for x in range(120, w, 420):                             # posts
        pygame.draw.rect(s, wood, (x - 22, top - 40, 44, deck - top + 40))
        pygame.draw.rect(s, OUTLINE, (x - 22, top - 40, 44, deck - top + 40), 4)
        pygame.draw.rect(s, (150, 108, 100), (x - 30, top - 54, 60, 18))
    for y, thick in ((top, 30), (low, 18)):
        pygame.draw.rect(s, wood, (0, y, w, thick))
        pygame.draw.line(s, OUTLINE, (0, y), (w, y), 4)
        pygame.draw.line(s, OUTLINE, (0, y + thick), (w, y + thick), 4)
    for k, x in enumerate(range(120, w, 840)):               # lanterns on the posts
        _lantern(s, x, top - 120, 34, (255, 150, 170) if k % 2 else (255, 210, 150),
                 hanging=True)
    return s


# --- Characters ---------------------------------------------------------------------------

def _eye(s: pygame.Surface, cx: float, cy: float, kind: str, iris: Color, side: int) -> None:
    """One eye; ``side`` is -1 (her right, the viewer's left) or 1."""
    if kind == "closed":                                     # ^ : laughing
        pygame.draw.arc(s, OUTLINE, (cx - 34, cy - 22, 68, 54), 0.35, math.pi - 0.35, 9)
        return
    if kind == "wide":
        _ellipse(s, WHITE, (cx - 34, cy - 46, 68, 92), 5)
        _ellipse(s, iris, (cx - 22, cy - 26, 44, 56), 0)
        pygame.draw.ellipse(s, OUTLINE, (cx - 12, cy - 12, 24, 30))
        pygame.draw.circle(s, WHITE, (cx - 8, cy - 14), 8)
        pygame.draw.line(s, OUTLINE, (cx - 36, cy - 50), (cx + 36, cy - 52), 8)
        return
    _ellipse(s, iris, (cx - 28, cy - 34, 56, 72), 0)
    pygame.draw.ellipse(s, tuple(c // 2 for c in iris), (cx - 14, cy - 12, 28, 40))
    pygame.draw.circle(s, WHITE, (cx - 10, cy - 16), 10)
    pygame.draw.circle(s, WHITE, (cx + 11, cy + 18), 5)
    if kind == "half":                                       # heavy lids: unimpressed
        s.fill(SKIN, (cx - 40, cy - 52, 80, 40))
        pygame.draw.line(s, OUTLINE, (cx - 36, cy - 12), (cx + 36, cy - 12), 9)
    elif kind == "down":                                     # sad: lids sloping outward
        s.fill(SKIN, (cx - 40, cy - 54, 80, 26))
        inner, outer = (cx - side * 34, cy - 30), (cx + side * 36, cy - 18)
        pygame.draw.line(s, OUTLINE, inner, outer, 9)
    else:
        pygame.draw.line(s, OUTLINE, (cx - 36, cy - 34), (cx + 34, cy - 38), 9)
        pygame.draw.line(s, OUTLINE, (cx + side * 34, cy - 36), (cx + side * 44, cy - 44), 6)


def _brow(s: pygame.Surface, cx: float, y: float, kind: str, side: int) -> None:
    inner, outer = cx - side * 26, cx + side * 30
    lift = {"soft": (0, 0), "raised": (-16, -16), "cross": (12, -6), "worried": (-12, 6),
            "flat": (0, 0)}[kind]
    pygame.draw.line(s, OUTLINE, (inner, y + lift[0]), (outer, y + lift[1] + (4 if kind == "soft"
                                                                               else 0)), 7)


def _mouth(s: pygame.Surface, cx: float, cy: float, kind: str) -> None:
    if kind == "smile":
        pygame.draw.arc(s, OUTLINE, (cx - 32, cy - 26, 64, 44), math.pi + 0.5,
                        2 * math.pi - 0.5, 6)
    elif kind in ("open", "grin"):
        a, b = (40, 34) if kind == "open" else (52, 30)
        points = [(cx + a * math.cos(t / 20 * math.pi), cy - 6 + b * math.sin(t / 20 * math.pi))
                  for t in range(21)]
        _poly(s, MOUTH, points, 5)
        pygame.draw.ellipse(s, (240, 140, 160), (cx - a * 0.45, cy + b * 0.35, a * 0.9, b * 0.5))
        pygame.draw.line(s, OUTLINE, (cx - a, cy - 6), (cx + a, cy - 6), 5)
    elif kind == "o":
        _ellipse(s, MOUTH, (cx - 16, cy - 18, 32, 40), 5)
    elif kind == "pout":
        pygame.draw.arc(s, OUTLINE, (cx - 18, cy - 4, 36, 26), 0.3, math.pi - 0.3, 6)
    elif kind == "frown":
        pygame.draw.arc(s, OUTLINE, (cx - 26, cy - 2, 52, 34), 0.45, math.pi - 0.45, 6)
    else:                                                    # flat
        pygame.draw.line(s, OUTLINE, (cx - 22, cy + 4), (cx + 26, cy), 6)


def _face(s: pygame.Surface, face: dict, iris: Color, top: float) -> None:
    eye_y, mouth_y = top + 210, top + 290
    if face.get("blush"):
        blush = _layer(s.get_size(), (*BLUSH, 0))
        for x in (300, 500):
            pygame.draw.ellipse(blush, (*BLUSH, 110), (x - 40, eye_y + 30, 80, 34))
        s.blit(blush, (0, 0))
    for side, x in ((-1, 335), (1, 465)):
        _eye(s, x, eye_y, face["eyes"], iris, side)
        _brow(s, x, eye_y - 62, face["brows"], side)
    _mouth(s, 400, mouth_y, face["mouth"])
    if face.get("tear"):
        _ellipse(s, (190, 220, 255), (462, eye_y + 40, 16, 26), 3)
    if face.get("sweat"):
        _poly(s, (200, 228, 255), [(560, top + 120), (546, top + 156), (574, top + 156)], 4)


def _figure(*, hair: Color, cloth: Color, trim: Color, obi: Color, iris: Color, face: dict,
            long_hair: bool, top: float, broad: int) -> pygame.Surface:
    """A standing figure in a yukata, 800×1360 (2×); ``top`` is the top of the head."""
    w, h = SPRITE_SIZE[0] * SS, SPRITE_SIZE[1] * SS
    s = _layer((w, h))
    chin = top + 360
    if long_hair:
        _poly(s, hair, [(212, top + 140), (588, top + 140), (640, top + 700), (560, top + 760),
                        (400, top + 720), (240, top + 760), (160, top + 700)])
    shoulder = chin + 40
    body = [(262 - broad, shoulder), (538 + broad, shoulder), (626 + broad, shoulder + 90),
            (690 + broad, shoulder + 450), (582 + broad, shoulder + 470), (566, h + 10),
            (234, h + 10), (218 - broad, shoulder + 470), (110 - broad, shoulder + 450),
            (174 - broad, shoulder + 90)]
    cloth_layer = _layer((w, h))
    pygame.draw.polygon(cloth_layer, cloth, body)
    if long_hair:                                            # small flowers
        for k in range(26):
            x, y = 140 + (k * 173) % 540, shoulder + 60 + (k * 97) % (h - shoulder)
            for a in range(5):
                pygame.draw.circle(cloth_layer, trim, (x + 13 * math.cos(a * 1.257),
                                                       y + 13 * math.sin(a * 1.257)), 9)
            pygame.draw.circle(cloth_layer, (255, 226, 150), (x, y), 6)
    else:                                                    # stripes
        for x in range(60, w, 64):
            pygame.draw.line(cloth_layer, trim, (x, shoulder), (x - 30, h), 8)
    _clip_to(cloth_layer, body)
    s.blit(cloth_layer, (0, 0))
    pygame.draw.polygon(s, OUTLINE, body, 6)
    for side in (-1, 1):                                     # sleeve folds
        x = 400 + side * (205 + broad)
        pygame.draw.line(s, OUTLINE, (x, shoulder + 130), (x + side * 10, shoulder + 440), 5)
    _poly(s, SKIN, [(362, top + 300), (438, top + 300), (444, shoulder + 30),
                    (356, shoulder + 30)], 5)                # neck
    v = [(330, shoulder - 4), (470, shoulder - 4), (400, shoulder + 190)]
    _poly(s, SKIN, v, 0)
    pygame.draw.line(s, WHITE, v[0], v[2], 22)               # collar, left over right
    pygame.draw.line(s, WHITE, v[1], (406, shoulder + 180), 22)
    pygame.draw.line(s, OUTLINE, (316, shoulder - 4), (396, shoulder + 200), 5)
    pygame.draw.line(s, OUTLINE, (484, shoulder - 4), (404, shoulder + 196), 5)
    waist = shoulder + 220
    _poly(s, obi, [(214 - broad // 2, waist), (586 + broad // 2, waist),
                   (590 + broad // 2, waist + 112), (210 - broad // 2, waist + 112)], 6)
    pygame.draw.line(s, trim, (214, waist + 56), (586, waist + 56), 8)
    if long_hair:                                            # a bow at her side
        _poly(s, obi, [(560, waist + 56), (650, waist - 10), (660, waist + 110)], 5)
        _poly(s, obi, [(560, waist + 56), (620, waist + 170), (580, waist + 190)], 5)
    _ellipse(s, SKIN, (232, top, 336, 370), 6)               # face
    _poly(s, hair, [(226, top + 150), (240, top + 40), (330, top - 30), (470, top - 30),
                    (560, top + 40), (574, top + 150), (520, top + 70), (480, top + 130),
                    (430, top + 66), (380, top + 136), (330, top + 70), (290, top + 140)])
    for side in (-1, 1):                                     # side locks
        x0 = 400 + side * 170
        length = 300 if long_hair else 160
        _poly(s, hair, [(x0, top + 50), (x0 - side * 40, top + 120),
                        (x0 - side * 30, top + length), (x0 + side * 14, top + length + 40),
                        (x0 + side * 12, top + 110)])
    if long_hair:                                            # a flower pin
        for a in range(5):
            _ellipse(s, (255, 170, 196), (520 + 22 * math.cos(a * 1.257) - 16,
                                          top + 20 + 22 * math.sin(a * 1.257) - 16, 32, 32), 4)
        pygame.draw.circle(s, (255, 226, 150), (520, top + 20), 10)
    _face(s, face, iris, top)
    return s


HANA = dict(hair=(122, 74, 92), cloth=(250, 196, 212), trim=(255, 242, 246),
            obi=(196, 74, 120), iris=(150, 70, 110), long_hair=True, top=150, broad=0)
DAICHI = dict(hair=(52, 50, 78), cloth=(86, 112, 168), trim=(116, 144, 198),
              obi=(220, 204, 176), iris=(60, 82, 132), long_hair=False, top=96, broad=26)

FACES = {
    "hana happy": dict(eyes="closed", brows="soft", mouth="open", blush=True),
    "hana surprised": dict(eyes="wide", brows="raised", mouth="o"),
    "hana pout": dict(eyes="half", brows="cross", mouth="pout", blush=True),
    "hana sad": dict(eyes="down", brows="worried", mouth="frown", tear=True),
    "daichi smile": dict(eyes="open", brows="soft", mouth="smile"),
    "daichi grin": dict(eyes="closed", brows="raised", mouth="grin"),
    "daichi sigh": dict(eyes="half", brows="flat", mouth="flat", sweat=True),
}


def item_lantern() -> pygame.Surface:
    """F21's codex picture: the red paper lantern from the stall, lit, on a dusk backdrop."""
    w, h = ITEM_SIZE[0] * SS, ITEM_SIZE[1] * SS
    s = pygame.Surface((w, h))
    _gradient(s, (0, 0, w, h), [(0.0, (74, 56, 104)), (0.6, (150, 98, 140)),
                                (1.0, (214, 150, 170))])
    _glow(s, (w / 2, h * 0.52), 520, (255, 210, 160), 170)
    pygame.draw.line(s, (70, 50, 60), (w / 2, 0), (w / 2, h * 0.2), 8)          # the cord
    _lantern(s, w / 2, h * 0.52, 190, (214, 52, 64), hanging=True)
    return s


def _sprite(name: str) -> Callable[[], pygame.Surface]:
    tag = name.split()[0]
    return lambda: _figure(**(HANA if tag == "hana" else DAICHI), face=FACES[name])


# --- The files ----------------------------------------------------------------------------

ART: dict[str, tuple[Callable[[], pygame.Surface], tuple[int, int]]] = {
    "images/bg/river_dusk.png": (river_dusk, BG_SIZE),
    "images/bg/bridge_night.png": (bridge_night, BG_SIZE),
    **{f"images/{name.replace(' ', '/')}.png": (_sprite(name), SPRITE_SIZE) for name in FACES},
    "images/items/lantern.png": (item_lantern, ITEM_SIZE),                  # F21
}


def write_art(game: Path) -> list[Path]:
    """Draw every file of ``ART`` under ``game`` and return the paths written."""
    pygame.init()
    written = []
    try:
        for ref, (draw, size) in ART.items():
            path = game / ref
            _save(draw(), size, path)
            written.append(path)
    finally:
        pygame.quit()
    return written


if __name__ == "__main__":
    if len(sys.argv) > 2:
        sys.exit("usage: make_example_art.py [game folder]")
    root = Path(sys.argv[1]) if len(sys.argv) == 2 else GAME
    for path in write_art(root):
        print(f"{path.stat().st_size:>8,}  {path}")

"""F10's ``gui/`` images and the unreadable font (06-acceptance §5), generated into a game copy.

The tests call ``generate(game_root)`` on a temporary copy of ``template_min/`` (launches
write ``logs/`` into the game folder, so the committed fixture is never launched in place).
Run ``python tests/fixtures/F10/gen_ui_images.py <game folder>`` to write them by hand.

Images are solid opaque fills drawn with pygame (no display needed):
- ``gui/title_bg.png`` 1280×720 (40, 120, 200); ``gui/title_wide.png`` 1280×400, the same color;
- ``gui/logo.png`` 800×200 (250, 200, 0); ``gui/logo_small.png`` 200×100, the same color;
- ``gui/button.png`` 72×72 nine-slice for slice 24: corners (255, 0, 0), edges (0, 255, 0),
  center (0, 0, 255);
- ``gui/bad.png``: a PNG cut after 40 bytes; ``gui/huge_header.png``: a valid PNG header
  claiming 40,000×40,000;
- ``fonts/Lora.ttf``: 100 random bytes (``random.Random(1)``).
"""

import random
import struct
import sys
import zlib
from pathlib import Path

TITLE_BG = (40, 120, 200)
LOGO = (250, 200, 0)
CORNER, EDGE, CENTER = (255, 0, 0), (0, 255, 0), (0, 0, 255)
SLICE = 24


def _solid(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> None:
    import pygame

    surface = pygame.Surface(size)
    surface.fill(color)
    pygame.image.save(surface, str(path))


def _nine_slice(path: Path) -> None:
    import pygame

    surface = pygame.Surface((3 * SLICE, 3 * SLICE))
    surface.fill(EDGE)
    for x in (0, 2 * SLICE):
        for y in (0, 2 * SLICE):
            surface.fill(CORNER, (x, y, SLICE, SLICE))
    surface.fill(CENTER, (SLICE, SLICE, SLICE, SLICE))
    pygame.image.save(surface, str(path))


def _png_header(width: int, height: int) -> bytes:
    """A PNG signature and IHDR chunk (8-bit RGB) with a correct CRC, then one empty IEND."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    out = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk
    out += struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
    return out + struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))


def generate(root: Path) -> Path:
    """Write the images and the bad font into game folder ``root``; returns ``root``."""
    gui = root / "gui"
    fonts = root / "fonts"
    gui.mkdir(parents=True, exist_ok=True)
    fonts.mkdir(parents=True, exist_ok=True)
    _solid(gui / "title_bg.png", (1280, 720), TITLE_BG)
    _solid(gui / "title_wide.png", (1280, 400), TITLE_BG)
    _solid(gui / "logo.png", (800, 200), LOGO)
    _solid(gui / "logo_small.png", (200, 100), LOGO)
    _nine_slice(gui / "button.png")
    (gui / "bad.png").write_bytes((gui / "logo.png").read_bytes()[:40])
    (gui / "huge_header.png").write_bytes(_png_header(40_000, 40_000))
    (fonts / "Lora.ttf").write_bytes(random.Random(1).randbytes(100))
    return root


if __name__ == "__main__":
    generate(Path(sys.argv[1]))

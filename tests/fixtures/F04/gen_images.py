"""Deterministic test images for F04's render tests (``06-acceptance.md`` §5.2), written by
pygame at test time into a game folder under ``tmp_path`` (never committed).

- ``edge_marked(w, h)``: 8-pixel bands, top ``#FF0000``, bottom ``#00FF00``, left
  ``#0000FF``, right ``#FFFF00`` (top and bottom drawn last), the rest ``#808080``.
- ``block(w, h, color)``: one opaque color.
- ``half_and_half(w, h)``: left half ``#FF0000``, right half ``#0000FF``.
- ``quadrants(w, h)``: four colors, ``QUADRANT_COLORS`` top-left, top-right, bottom-left,
  bottom-right.
- ``header_only(w, h)``: a PNG signature and IHDR declaring ``w``×``h`` and nothing else.
- ``png_bytes(surface)``: the surface as a PNG, written with zlib level 1. About 2.5 times
  faster than ``pygame.image.save`` for the 4K and 8K images (test-review-F04.md); SDL_image
  decodes it to the same pixels.
"""

import struct
import zlib
from pathlib import Path

import pygame

RED = (0xFF, 0x00, 0x00)
GREEN = (0x00, 0xFF, 0x00)
BLUE = (0x00, 0x00, 0xFF)
YELLOW = (0xFF, 0xFF, 0x00)
GRAY = (0x80, 0x80, 0x80)
BAND = 8
QUADRANT_COLORS = ((0xFF, 0x00, 0x00), (0x00, 0xFF, 0x00), (0x00, 0x00, 0xFF),
                   (0xFF, 0xFF, 0x00))


def edge_marked(width: int, height: int) -> pygame.Surface:
    surface = pygame.Surface((width, height))
    surface.fill(GRAY)
    surface.fill(BLUE, (0, 0, BAND, height))
    surface.fill(YELLOW, (width - BAND, 0, BAND, height))
    surface.fill(RED, (0, 0, width, BAND))
    surface.fill(GREEN, (0, height - BAND, width, BAND))
    return surface


def block(width: int, height: int, color: tuple[int, int, int]) -> pygame.Surface:
    surface = pygame.Surface((width, height))
    surface.fill(color)
    return surface


def half_and_half(width: int, height: int) -> pygame.Surface:
    surface = pygame.Surface((width, height))
    surface.fill(RED, (0, 0, width // 2, height))
    surface.fill(BLUE, (width // 2, 0, width - width // 2, height))
    return surface


def quadrants(width: int, height: int) -> pygame.Surface:
    surface = pygame.Surface((width, height))
    half_w, half_h = width // 2, height // 2
    tl, tr, bl, br = QUADRANT_COLORS
    surface.fill(tl, (0, 0, half_w, half_h))
    surface.fill(tr, (half_w, 0, width - half_w, half_h))
    surface.fill(bl, (0, half_h, half_w, height - half_h))
    surface.fill(br, (half_w, half_h, width - half_w, height - half_h))
    return surface


def header_only(width: int, height: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk
            + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF))


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def png_bytes(surface: pygame.Surface) -> bytes:
    """An 8-bit RGB (or RGBA, for a per-pixel-alpha surface) PNG, filter 0, zlib level 1."""
    width, height = surface.get_size()
    alpha = bool(surface.get_flags() & pygame.SRCALPHA)
    mode, color_type, depth = ("RGBA", 6, 4) if alpha else ("RGB", 2, 3)
    raw = pygame.image.tobytes(surface, mode)
    stride = width * depth
    rows = b"".join(b"\x00" + raw[i:i + stride] for i in range(0, len(raw), stride))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(rows, 1)) + _chunk(b"IEND", b""))


def ref_of(name: str) -> str:
    """The file an image name comes from: ``hana happy`` → ``images/hana/happy.png``."""
    return "images/" + name.replace(" ", "/") + ".png"


def write(root: Path, images: dict[str, "pygame.Surface | bytes"]) -> None:
    """Save each ``ref → surface`` (or raw bytes) under ``root``."""
    for ref, image in images.items():
        path = root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image if isinstance(image, bytes) else png_bytes(image))

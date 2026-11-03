"""The exe's icon: a PNG made into a Windows ``.ico`` (F42 ``04-technical.md`` §3.1, PR-F42-08,
architect decision 6).

Why this module exists: Windows shows an exe's icon from an ``.ico`` resource, but authors
make PNGs (``[window] icon``). The build converts the PNG once, in the build child, with
pygame-ce (already the engine's one dependency; no new runtime dependency) and a stdlib ICO
writer, so the author never makes an ``.ico`` by hand.

- ``icon_png(game_root, ref)``: the PNG bytes to use. ``ref`` None (no ``[window] icon``) →
  the engine's ``engine/data/icon.png``; else the game file, read through ``GamePaths``
  (``check_ref``, contained, regular, at most ``ICON_MAX_BYTES``). Any problem raises
  ``IconError`` (``BAD_ICON``).
- ``make_ico(png)``: decodes the PNG (it must start with the PNG signature and be at least
  16×16), fits it to a square with transparent padding (centred), ``smoothscale``\\ s it to
  16, 32, 48 and 256 px and writes one PNG-compressed entry per size behind a standard ICO
  header (Windows Vista and later read PNG entries). Raises ``IconError`` for a bad image.

No display is opened: only ``pygame.image`` and ``pygame.transform`` on plain surfaces.

The only ``tools/build`` module that imports pygame (``04`` §3.4). Child-only.
"""

import io
import os
import struct
from pathlib import Path
from typing import Final

from engine.core.errors import EngineError
from engine.core.paths import GamePaths, engine_data_dir
from engine.tools.build.texts import BAD_ICON

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")   # no banner on a report stream
import pygame  # noqa: E402

SIZES: Final = (16, 32, 48, 256)
MIN_SIDE: Final = 16
ICON_MAX_BYTES: Final = 16 << 20
PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
ENGINE_ICON: Final = "icon.png"          # in engine/data


class IconError(Exception):
    """The icon can't be used; ``key`` is always ``BAD_ICON``."""

    key = BAD_ICON


def icon_png(game_root: Path, ref: str | None) -> bytes:
    """The PNG for the exe: the game's ``ref`` or, when None, the engine icon."""
    if ref is None:
        path = engine_data_dir() / ENGINE_ICON
        try:
            return path.read_bytes()
        except OSError as exc:
            raise IconError(ENGINE_ICON) from exc
    try:
        return GamePaths.for_game(Path(game_root)).read_file(ref, max_bytes=ICON_MAX_BYTES,
                                                             regular=True)
    except (EngineError, OSError) as exc:     # bad ref, missing, not a file, too big…
        raise IconError(ref) from exc


def make_ico(png: bytes) -> bytes:
    """The ``.ico`` bytes for ``png``; raises ``IconError``."""
    if not png.startswith(PNG_SIGNATURE):
        raise IconError("not a PNG")
    try:
        image = pygame.image.load(io.BytesIO(png), "icon.png")
    except (pygame.error, ValueError, OSError, MemoryError) as exc:
        raise IconError("unreadable") from exc
    width, height = image.get_size()
    if width < MIN_SIDE or height < MIN_SIDE:
        raise IconError("too small")
    side = max(width, height)
    square = pygame.Surface((side, side), pygame.SRCALPHA, 32)
    square.fill((0, 0, 0, 0))
    square.blit(image, ((side - width) // 2, (side - height) // 2))
    entries = [(size, _png_bytes(pygame.transform.smoothscale(square, (size, size))))
               for size in SIZES]
    return ico_bytes(entries)


def _png_bytes(surface: "pygame.Surface") -> bytes:
    buffer = io.BytesIO()
    pygame.image.save(surface, buffer, "icon.png")
    return buffer.getvalue()


def ico_bytes(entries: list[tuple[int, bytes]]) -> bytes:
    """An ICO file of PNG entries ``(side, png bytes)``: ICONDIR (6 bytes), one 16-byte
    ICONDIRENTRY each (a side of 256 is written as 0), then the images in order."""
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = len(header) + 16 * len(entries)
    directory, images = [], []
    for side, data in entries:
        dim = 0 if side >= 256 else side
        directory.append(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset))
        images.append(data)
        offset += len(data)
    return header + b"".join(directory) + b"".join(images)


__all__ = ["BAD_ICON", "ICON_MAX_BYTES", "IconError", "SIZES", "icon_png", "ico_bytes",
           "make_ico"]

"""Save thumbnails: shrink a captured scene, encode it as a baseline JPEG, decode it back.

Why this module exists: a save file's line 2 holds a 320×180 picture of the scene (F11
``04`` §4, §5.3). ``persist`` imports no pygame, so the picture is coded here, in ``render``,
and the bytes are handed over. A thumbnail read back from a save file is untrusted input:
``decode_jpeg`` only ever decodes bytes that ``core.imageheader.check_engine_jpeg`` accepts
(the whole structure the engine's own encoder writes, SEC-F11-01), only from memory through
``BytesIO`` and never from a path (SEC-F11-02), and re-checks the decoded size.

Cost on the dev machine (F11 ``04`` §11): the shrink is 0.6–3.7 ms (720p–4K, once per
capture); the encode 0.18–0.30 ms and the decode 0.15–0.45 ms; 5–45 KB per picture.
"""

import io

import pygame

from engine.core.imageheader import check_engine_jpeg

THUMB_SIZE = (320, 180)
_NAMEHINT = "t.jpg"         # selects the JPEG writer; the reader still sniffs (hence the check)
_DEPTH = 24


def make_thumbnail(scene: pygame.Surface) -> pygame.Surface:
    """A new 320×180, 24-bit surface: ``scene`` smooth-scaled to fill it (stretched if its
    aspect isn't 16:9). Per-pixel alpha is composited over black. An empty ``scene`` gives
    a black thumbnail. ``scene`` is not changed."""
    thumb = pygame.Surface(THUMB_SIZE, 0, _DEPTH)
    thumb.fill((0, 0, 0))
    width, height = scene.get_size()
    if width == 0 or height == 0:
        return thumb
    source = scene
    if scene.get_bitsize() not in (24, 32):          # smoothscale takes 24- or 32-bit only
        source = pygame.Surface((width, height), 0, _DEPTH)
        source.blit(scene, (0, 0))
    thumb.blit(pygame.transform.smoothscale(source, THUMB_SIZE), (0, 0))
    return thumb


def encode_jpeg(thumb: pygame.Surface) -> bytes | None:
    """``thumb`` (320×180) as JPEG bytes from pygame's encoder, or None if it isn't
    320×180, the encoder fails, or ``check_engine_jpeg`` doesn't accept the result (over
    96 KiB, or the rare entropy bytes spelling ``<svg``): the save then holds no picture
    and its slot shows the placeholder (PR-F11-19)."""
    if thumb.get_size() != THUMB_SIZE:
        return None
    buffer = io.BytesIO()
    try:
        pygame.image.save(thumb, buffer, _NAMEHINT)
    except (pygame.error, OSError, ValueError, MemoryError):
        return None
    data = buffer.getvalue()
    return data if check_engine_jpeg(data, THUMB_SIZE) else None


def decode_jpeg(data: bytes) -> pygame.Surface | None:
    """The 320×180 picture in ``data``, or None (the slot shows the placeholder).

    ``data`` must pass ``check_engine_jpeg`` before pygame sees a byte, so SDL_image can
    only pick its JPEG decoder; it is decoded from memory (``BytesIO``), never a path, and
    a result of any other size is dropped. Never raises for bad bytes."""
    if not check_engine_jpeg(data, THUMB_SIZE):
        return None
    try:
        picture = pygame.image.load(io.BytesIO(data), _NAMEHINT)
    except (pygame.error, OSError, ValueError, MemoryError):
        return None
    if picture.get_size() != THUMB_SIZE:
        return None
    return picture

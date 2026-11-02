"""Image format and size from header bytes, without decoding.

Why this module exists: an 800-byte PNG can declare 60000×60000 pixels and make SDL
allocate gigabytes (SEC-F01-06). The asset loader checks the declared size here before
decoding. *Why ``core``:* it is pure byte parsing with no pygame, and F11 must validate
save-thumbnail headers from ``persist``, which cannot import ``render``.

The parser only reads fixed offsets and walks JPEG segments forward, so it runs in time
linear in ``len(data)`` and never raises for malformed input.

``check_engine_jpeg`` (F11 C16, SEC-F11-01) is stricter: a save thumbnail is accepted only
if its whole structure is the one the engine's own JPEG encoder writes. A header walk that
stops at the frame is not enough: SDL_image picks a decoder by sniffing, and a "JPEG" whose
segments run past the end fails ``IMG_isJPG`` and falls through to ``IMG_isSVG``, which
finds a ``<svg`` comment and rasterizes it at its declared 8000×8000 (reproduced on
pygame-ce 2.5.8 / SDL_image 2.8). Every string the check accepts walks cleanly from SOI to
EOI the way ``IMG_isJPG`` walks it, so detection can only pick JPEG and the decode gives
the checked size or ``pygame.error``.
"""

import re
import struct
from typing import Literal

ImageFormat = Literal["png", "jpeg", "webp"]

# F11 ``04`` §13 ``THUMB_MAX_BYTES`` (96 KiB): the largest thumbnail ``check_engine_jpeg``
# accepts. The engine's encoder writes 5–45 KB at 320×180 (noise is the worst case).
ENGINE_JPEG_MAX_BYTES = 98_304

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# JPEG start-of-frame markers that carry the image size (not DHT 0xC4, JPG 0xC8, DAC 0xCC).
_JPEG_SOF = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                       0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})


def image_dimensions(data: bytes) -> tuple[ImageFormat, int, int] | None:
    """Format and size from header bytes only (§7.11.2). None if the bytes are not a
    recognizable PNG/JPEG/WebP header. Runs in time linear in len(data); never decodes."""
    result = _png(data) or _jpeg(data) or _webp(data)
    if result is None:
        return None
    _, width, height = result
    if width == 0 or height == 0:
        return None
    return result


def _png(data: bytes) -> tuple[ImageFormat, int, int] | None:
    if data[:8] != _PNG_SIGNATURE or data[12:16] != b"IHDR" or len(data) < 24:
        return None
    width, height = struct.unpack(">II", data[16:24])
    return "png", width, height


def _jpeg(data: bytes) -> tuple[ImageFormat, int, int] | None:
    if data[:2] != b"\xff\xd8":
        return None
    n = len(data)
    i = 2
    while i < n:
        if data[i] != 0xFF:
            return None
        while i < n and data[i] == 0xFF:      # fill bytes
            i += 1
        if i >= n:
            return None
        marker = data[i]
        i += 1
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:   # standalone, no length
            continue
        if marker in (0xD9, 0xDA):                       # end of image / scan before a SOF
            return None
        if i + 2 > n:
            return None
        (length,) = struct.unpack(">H", data[i:i + 2])
        if length < 2:
            return None
        if marker in _JPEG_SOF:
            # Segment: length (2 bytes), precision (1 byte), height, width (2 bytes each).
            if i + 7 > n:
                return None
            height, width = struct.unpack(">HH", data[i + 3:i + 7])
            return "jpeg", width, height
        i += length
    return None


def _webp(data: bytes) -> tuple[ImageFormat, int, int] | None:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8 ":
        if len(data) < 30 or data[23:26] != b"\x9d\x01\x2a":
            return None
        width, height = struct.unpack("<HH", data[26:30])
        return "webp", width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L":
        if len(data) < 25 or data[20] != 0x2F:
            return None
        (bits,) = struct.unpack("<I", data[21:25])
        return "webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        if len(data) < 30:
            return None
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return "webp", width, height
    return None


# --- Engine thumbnails (F11 C16, SEC-F11-01) ---------------------------------------------

_SOI_APP0 = b"\xff\xd8\xff\xe0"
_JFIF = b"JFIF\x00"
_SOF0 = 0xC0
_SOS = 0xDA
_EOI = 0xD9
# Segments allowed around the frame header: APP0–APP15, COM, DQT, DHT, DRI.
_TABLE_SEGMENTS = frozenset(range(0xE0, 0xF0)) | {0xFE, 0xDB, 0xC4, 0xDD}
_SVG = re.compile(rb"<svg", re.IGNORECASE)


def check_engine_jpeg(data: bytes, size: tuple[int, int]) -> bool:
    """True only for a baseline JPEG of exactly ``size`` (width, height) laid out the way
    the engine's encoder writes one (measured: APP0, DQT×2, SOF0, DHT×4, SOS, EOI):

    (a) SOI, then an APP0 ``JFIF`` segment first;
    (b) before the scan only APPn, COM, DQT, DHT, DRI and the frame, each with a length
        ≥ 2 that ends inside the data, and no fill bytes between them;
    (c) exactly one frame: SOF0, precision 8, exactly ``size``, 1 or 3 components;
    (d) exactly one scan (SOS inside the data), covering every component, baseline
        spectral range 0–63, no successive approximation;
    (e) after it only entropy bytes, ``FF 00``, ``FF D0``–``D7``, and ``FF`` fill, with
        EOI as the last two bytes;
    (f) at most ``ENGINE_JPEG_MAX_BYTES`` bytes; and, as a backstop, no ``<svg`` in any
        letter case anywhere.

    Linear in ``len(data)``; never raises (anything but ``bytes``/``bytearray`` is
    refused)."""
    if not isinstance(data, (bytes, bytearray)) or len(data) > ENGINE_JPEG_MAX_BYTES:
        return False
    if not _engine_jpeg_structure(data, size):
        return False
    return _SVG.search(data) is None


def _engine_jpeg_structure(data: bytes | bytearray, size: tuple[int, int]) -> bool:
    """``check_engine_jpeg``'s (a)–(e) without the size cap and the ``<svg`` backstop."""
    n = len(data)
    if data[:4] != _SOI_APP0:
        return False
    i = 2
    components = 0
    while True:
        if i + 4 > n or data[i] != 0xFF:
            return False
        marker = data[i + 1]
        length = (data[i + 2] << 8) | data[i + 3]
        end = i + 2 + length
        if length < 2 or end > n:
            return False
        body = i + 4
        if i == 2:
            if length < 2 + len(_JFIF) or data[body:body + len(_JFIF)] != _JFIF:
                return False
        elif marker == _SOF0:
            if components:
                return False
            components = _frame_components(data, body, length, size)
            if not components:
                return False
        elif marker == _SOS:
            return (components > 0 and _scan_header_ok(data, body, length, components)
                    and _entropy_ok(data, end))
        elif marker not in _TABLE_SEGMENTS:
            return False
        i = end


def _frame_components(data: bytes | bytearray, body: int, length: int,
                      size: tuple[int, int]) -> int:
    """The SOF0 segment's component count (1 or 3) if it is 8-bit and exactly ``size``;
    0 otherwise. The segment lies inside the data (checked by the caller)."""
    if length < 8:
        return 0
    precision = data[body]
    height = (data[body + 1] << 8) | data[body + 2]
    width = (data[body + 3] << 8) | data[body + 4]
    components = data[body + 5]
    if precision != 8 or (width, height) != tuple(size) or components not in (1, 3):
        return 0
    if length != 8 + 3 * components:
        return 0
    return components


def _scan_header_ok(data: bytes | bytearray, body: int, length: int, components: int) -> bool:
    """One baseline scan over every component: Ns = the frame's count, Ss 0, Se 63, Ah/Al 0."""
    if length < 6 or data[body] != components or length != 6 + 2 * components:
        return False
    tail = body + 1 + 2 * components
    return data[tail] == 0 and data[tail + 1] == 63 and data[tail + 2] == 0


def _entropy_ok(data: bytes | bytearray, start: int) -> bool:
    """From ``start`` to the end: entropy bytes, ``FF 00``, ``FF D0``–``D7``, ``FF`` fill,
    and EOI exactly as the last two bytes. Jumps from one ``FF`` to the next."""
    n = len(data)
    i = start
    while True:
        k = data.find(b"\xff", i)
        if k < 0:
            return False                        # no EOI
        m = k + 1
        while m < n and data[m] == 0xFF:        # fill
            m += 1
        if m >= n:
            return False
        code = data[m]
        if code == _EOI:
            return m == n - 1
        if code != 0x00 and not 0xD0 <= code <= 0xD7:
            return False                        # any other marker: a second SOS, DHT, SOF…
        i = m + 1

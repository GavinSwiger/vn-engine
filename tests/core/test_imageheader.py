"""Image format and size from header bytes (SEC-F01-06, §7.11.2), incl. abuse B1–B3.

The size *limits* are applied by the asset loader (Step 7); this module only reads headers.
"""

import struct
import time
import zlib

import pytest

from engine.core.constants import IMAGE_MAX_PIXELS, IMAGE_MAX_SIDE
from engine.core.imageheader import image_dimensions


def png_header(width: int, height: int) -> bytes:
    """A PNG signature and IHDR chunk with a valid CRC (enough for the header check)."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk
            + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF))


def jpeg_header(width: int, height: int, *, sof: int = 0xC0, extra: bytes = b"") -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof_segment = (bytes([0xFF, sof]) + struct.pack(">HBHHB", 11, 8, height, width, 1)
                   + b"\x01\x11\x00")
    return b"\xff\xd8" + app0 + extra + sof_segment + b"\xff\xda"


def riff(chunk: bytes, payload: bytes) -> bytes:
    body = b"WEBP" + chunk + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", len(body)) + body


def webp_vp8(width: int, height: int) -> bytes:
    payload = b"\x00\x00\x00" + b"\x9d\x01\x2a" + struct.pack("<HH", width, height)
    return riff(b"VP8 ", payload)


def webp_vp8l(width: int, height: int) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    return riff(b"VP8L", b"\x2f" + struct.pack("<I", bits))


def webp_vp8x(width: int, height: int) -> bytes:
    payload = b"\x10\x00\x00\x00" + (width - 1).to_bytes(3, "little") \
        + (height - 1).to_bytes(3, "little")
    return riff(b"VP8X", payload)


@pytest.mark.parametrize("data, expected", [
    (png_header(64, 32), ("png", 64, 32)),
    (png_header(16384, 1), ("png", 16384, 1)),
    (png_header(60000, 60000), ("png", 60000, 60000)),
    (jpeg_header(640, 480), ("jpeg", 640, 480)),
    (jpeg_header(65500, 65500), ("jpeg", 65500, 65500)),
    (jpeg_header(300, 200, sof=0xC2), ("jpeg", 300, 200)),
    (webp_vp8(64, 64), ("webp", 64, 64)),
    (webp_vp8l(64, 32), ("webp", 64, 32)),
    (webp_vp8x(16384, 16384), ("webp", 16384, 16384)),
])
def test_recognized_headers(data, expected):
    assert image_dimensions(data) == expected


def test_jpeg_walk_skips_fill_bytes_standalone_markers_and_tables():
    dht = b"\xff\xc4" + struct.pack(">H", 4) + b"\x00\x00"           # not a SOF
    extra = b"\xff\xff\xff" + b"\xff\xd0" + dht
    assert image_dimensions(jpeg_header(120, 80, extra=extra)) == ("jpeg", 120, 80)


@pytest.mark.parametrize("data", [
    b"", b"not an image", b"\x89PNG\r\n\x1a\n", png_header(0, 10), png_header(10, 0),
    png_header(64, 64)[:20],
    b"\xff\xd8", b"\xff\xd8\xff\xd9", b"\xff\xd8\xff\xda\x00\x02",
    b"\xff\xd8\xff\xe0\x00\x01", b"\xff\xd8\x00\x00", jpeg_header(64, 64)[:-8],
    b"RIFF\x00\x00\x00\x00WEBPVP8 ", riff(b"VP8 ", b"\x00" * 10),
    riff(b"VP8L", b"\x00" * 5), riff(b"ABCD", b"\x00" * 10),
    b"GIF89a\x10\x00\x10\x00", b"BM" + b"\x00" * 30,
])
def test_unrecognized_or_malformed_headers(data):
    assert image_dimensions(data) is None


def test_limits_are_the_documented_numbers():
    assert IMAGE_MAX_SIDE == 16_384
    assert IMAGE_MAX_PIXELS == 64_000_000


@pytest.mark.parametrize("data", [
    b"\xff\xd8" + b"\xff" * 2_000_000,
    b"\xff\xd8" + (b"\xff\xe1\x00\x02") * 500_000,
    b"\xff\xd8" + b"\xff\xd0" * 1_000_000,
])
def test_large_inputs_take_linear_time(data):
    start = time.perf_counter()
    assert image_dimensions(data) is None
    assert time.perf_counter() - start < 2.0

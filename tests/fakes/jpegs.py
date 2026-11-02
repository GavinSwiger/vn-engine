"""JPEG byte builders for F11's thumbnail checks (SEC-F11-01, abuse group C).

Real thumbnails come from pygame's own encoder (the structure ``check_engine_jpeg`` pins);
the hostile ones are built by splitting a real one into its segments and changing one
thing. ``svg_confusion`` is the security review's reproduction byte for byte: a 421-byte
"JPEG" whose COM segment holds an SVG and whose last segment runs past the end, which
SDL_image decodes as an 8000×8000 SVG.
"""

import io
import random
import struct

import pygame

THUMB = (320, 180)
SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


def engine_jpeg(kind: str = "flat", size: tuple[int, int] = THUMB, *, seed: int = 1) -> bytes:
    """pygame's JPEG of a ``size`` picture: ``flat`` (one colour, smallest), ``noise``
    (random pixels, largest), or ``bands`` (a few colour stripes)."""
    width, height = size
    if kind == "noise":
        pixels = random.Random(seed).randbytes(width * height * 3)
        surface = pygame.image.frombuffer(pixels, size, "RGB").copy()
    else:
        surface = pygame.Surface(size, 0, 24)
        surface.fill((10, 200, 30))
        if kind == "bands":
            for i, colour in enumerate(((200, 30, 30), (30, 30, 200), (240, 240, 240))):
                surface.fill(colour, (0, i * height // 4, width, height // 8))
    buffer = io.BytesIO()
    pygame.image.save(surface, buffer, "t.jpg")
    return buffer.getvalue()


def segment(marker: int, body: bytes) -> bytes:
    """``FF <marker>``, a big-endian length (body + 2), and ``body``."""
    return bytes((0xFF, marker)) + struct.pack(">H", len(body) + 2) + body


def split(data: bytes) -> tuple[list[bytes], bytes]:
    """A well-formed JPEG as its segments from after SOI through SOS (each whole, marker
    included) and the rest (entropy data and EOI)."""
    assert data[:2] == SOI
    segments = []
    i = 2
    while True:
        marker = data[i + 1]
        (length,) = struct.unpack(">H", data[i + 2:i + 4])
        segments.append(data[i:i + 2 + length])
        i += 2 + length
        if marker == 0xDA:
            return segments, data[i:]


def join(segments: list[bytes], tail: bytes) -> bytes:
    return SOI + b"".join(segments) + tail


def markers(data: bytes) -> list[int]:
    """The marker codes of ``split``'s segments, in order."""
    return [seg[1] for seg in split(data)[0]]


def insert_after_app0(data: bytes, *extra: bytes) -> bytes:
    segments, tail = split(data)
    return join([segments[0], *extra, *segments[1:]], tail)


def replace_marker(data: bytes, old: int, new_segment: bytes) -> bytes:
    """``data`` with its first segment of marker ``old`` replaced by ``new_segment``."""
    segments, tail = split(data)
    index = next(i for i, seg in enumerate(segments) if seg[1] == old)
    segments[index] = new_segment
    return join(segments, tail)


def sof(width: int, height: int, *, components: int = 3, precision: int = 8,
        marker: int = 0xC0) -> bytes:
    """A frame header like pygame's (component 1 sampled 2×2, the others 1×1)."""
    specs = [bytes((1, 0x22, 0)), bytes((2, 0x11, 1)), bytes((3, 0x11, 1)),
             bytes((4, 0x11, 1))][:components]
    body = struct.pack(">BHHB", precision, height, width, components) + b"".join(specs)
    return segment(marker, body)


def sos(components: int = 3, *, ss: int = 0, se: int = 63, ahal: int = 0) -> bytes:
    specs = [bytes((1, 0x00)), bytes((2, 0x11)), bytes((3, 0x11)), bytes((4, 0x11))]
    return segment(0xDA, bytes((components,)) + b"".join(specs[:components])
                   + bytes((ss, se, ahal)))


def com(text: bytes) -> bytes:
    return segment(0xFE, text)


def pad_to(data: bytes, total: int) -> bytes:
    """``data`` grown to exactly ``total`` bytes with COM segments of spaces after APP0."""
    need = total - len(data)
    assert need == 0 or need >= 4
    extra = []
    while need:
        take = min(need, 65537)
        if 0 < need - take < 4:
            take -= 4
        extra.append(com(b" " * (take - 4)))
        need -= take
    out = insert_after_app0(data, *extra) if extra else data
    assert len(out) == total
    return out


def svg_confusion(side: int = 8000) -> bytes:
    """The security review's reproduction (05 §2 "Decoder format confusion"; scratchpad
    ``sec/svg_confuse.py``): SOI, a COM holding an SVG ``side``×``side``, SOF0 320×180,
    then a DQT whose length runs past the end. 421 bytes."""
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{side}' height='{side}'>"
           f"<rect width='{side}' height='{side}' fill='red'/></svg>").encode()
    body = svg + b" " * (0x180 - 2 - len(svg))
    comment = b"\xff\xfe" + struct.pack(">H", len(body) + 2) + body
    frame = (b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 180, 320, 3)
             + bytes([1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1]))
    bad = b"\xff\xdb" + struct.pack(">H", 0xFFFF) + b"\x00" * 10
    return SOI + comment + frame + bad


SVG_COMMENT = com(b"<svg xmlns='http://www.w3.org/2000/svg' width='8000' height='8000'>"
                  b"<rect width='8000' height='8000' fill='red'/></svg>" + b" " * 200)

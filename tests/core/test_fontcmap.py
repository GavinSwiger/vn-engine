"""F43 P2: which characters a font file has (``core/fontcmap``; 04 §3, §4 answer 1).

No AC of its own (AC-F43-20 and W252 build on it): formats 12 and 4 read from the bundled
Noto Sans and checked against a per-code-point reference decoder, hand-built subtables for
the edge cases, the subtable order, collections, and malformed or truncated files.
"""

import random
import struct
from pathlib import Path

import pytest

from engine.core.fontcmap import MAX_GROUPS, Coverage, read_coverage

FONTS = Path(__file__).resolve().parents[2] / "engine" / "data" / "fonts"
REGULAR = (FONTS / "NotoSans-Regular.ttf").read_bytes()


# --- Builders and a slow reference decoder ------------------------------------------------------

def format_4(segments: list[tuple[int, int, int, list[int] | None]]) -> bytes:
    """A format-4 subtable from (start, end, delta, glyphs or None) segments; the
    terminating 0xFFFF segment is added."""
    segments = [*segments, (0xFFFF, 0xFFFF, 1, None)]
    n = len(segments)
    arrays: list[int] = []
    offsets = []
    for i, (start, end, _, glyphs) in enumerate(segments):
        if glyphs is None:
            offsets.append(0)
            continue
        assert len(glyphs) == end - start + 1
        offsets.append(2 * (n - i) + 2 * len(arrays))     # from its own idRangeOffset word
        arrays.extend(glyphs)
    body = struct.pack(f">{n}H", *(s[1] for s in segments)) + b"\0\0"
    body += struct.pack(f">{n}H", *(s[0] for s in segments))
    body += struct.pack(f">{n}H", *((s[2] & 0xFFFF) for s in segments))
    body += struct.pack(f">{n}H", *offsets) + struct.pack(f">{len(arrays)}H", *arrays)
    return struct.pack(">HHHHHHH", 4, 14 + len(body), 0, 2 * n, 0, 0, 0) + body


def format_12(groups: list[tuple[int, int, int]]) -> bytes:
    body = b"".join(struct.pack(">III", *g) for g in groups)
    return struct.pack(">HHIII", 12, 0, 16 + len(body), 0, len(groups)) + body


def sfnt(subtables: list[tuple[tuple[int, int], bytes]], base: int = 0,
         version: bytes = b"\x00\x01\x00\x00") -> bytes:
    """A font with one table, ``cmap``, holding ``subtables``; offsets as if the font
    started at ``base`` in its file (a collection)."""
    head = 4 + 8 * len(subtables)
    records, blobs = b"", b""
    for (platform, encoding), blob in subtables:
        records += struct.pack(">HHI", platform, encoding, head + len(blobs))
        blobs += blob
    cmap = struct.pack(">HH", 0, len(subtables)) + records + blobs
    directory = version + struct.pack(">HHHH", 1, 16, 0, 0)
    offset = base + len(directory) + 16
    return directory + struct.pack(">4sIII", b"cmap", 0, offset, len(cmap)) + cmap


def cmap_subtables(data: bytes) -> tuple[int, dict[tuple[int, int], int]]:
    (count,) = struct.unpack_from(">H", data, 4)
    for i in range(count):
        tag, _, offset, _ = struct.unpack_from(">4sIII", data, 12 + 16 * i)
        if tag == b"cmap":
            (records,) = struct.unpack_from(">H", data, offset + 2)
            found = {}
            for j in range(records):
                p, e, sub = struct.unpack_from(">HHI", data, offset + 4 + 8 * j)
                found[(p, e)] = offset + sub
            return offset, found
    raise AssertionError("no cmap")


def reference_format_4(data: bytes, at: int) -> set[int]:
    """Every BMP code point mapped to a glyph, one code point at a time (the spec's text)."""
    (seg_x2,) = struct.unpack_from(">H", data, at + 6)
    n = seg_x2 // 2
    ends = struct.unpack_from(f">{n}H", data, at + 14)
    starts = struct.unpack_from(f">{n}H", data, at + 16 + seg_x2)
    deltas = struct.unpack_from(f">{n}H", data, at + 16 + 2 * seg_x2)
    offsets_at = at + 16 + 3 * seg_x2
    covered = set()
    for i in range(n):
        offset = struct.unpack_from(">H", data, offsets_at + 2 * i)[0]
        for c in range(starts[i], ends[i] + 1):
            if offset == 0:
                glyph = (c + deltas[i]) & 0xFFFF
            else:
                (glyph,) = struct.unpack_from(
                    ">H", data, offsets_at + 2 * i + offset + 2 * (c - starts[i]))
                glyph = (glyph + deltas[i]) & 0xFFFF if glyph else 0
            if glyph:
                covered.add(c)
    return covered


def reference_format_12(data: bytes, at: int) -> set[int]:
    (groups,) = struct.unpack_from(">I", data, at + 12)
    covered = set()
    for g in range(groups):
        first, last, glyph = struct.unpack_from(">III", data, at + 16 + 12 * g)
        covered.update(c for c in range(first, last + 1) if glyph + (c - first))
    return covered


def code_points(coverage: Coverage) -> set[int]:
    return {c for first, last in coverage.ranges() for c in range(first, last + 1)}


def demote(data: bytes, *keys: tuple[int, int]) -> bytes:
    """``data`` with the encoding records ``keys`` renamed to Macintosh (1, 0), so the
    reader skips them."""
    out = bytearray(data)
    offset, _ = cmap_subtables(data)
    (records,) = struct.unpack_from(">H", data, offset + 2)
    for j in range(records):
        at = offset + 4 + 8 * j
        if struct.unpack_from(">HH", data, at) in keys:
            struct.pack_into(">HH", out, at, 1, 0)
    return bytes(out)


# --- The bundled font -------------------------------------------------------------------------

def test_bundled_font_format_12():
    _, subtables = cmap_subtables(REGULAR)
    assert struct.unpack_from(">H", REGULAR, subtables[(3, 10)])[0] == 12
    coverage = read_coverage(REGULAR)
    assert coverage is not None
    assert code_points(coverage) == reference_format_12(REGULAR, subtables[(3, 10)])
    assert coverage.code_points == len(code_points(coverage)) > 2500
    for char in "Aé€ЖΩ ":
        assert coverage.has(ord(char)), char
    for cp in (0x65E5, 0xAC00, 0xE000, 0x10FFFF, 0x1F600, -1):    # 日, 가, private, emoji
        assert not coverage.has(cp), hex(cp)
    assert coverage.covers("é") and coverage.covers("A‍") \
        and coverage.covers("A️")                              # ZWJ, VS ignored
    assert not coverage.covers("日本") and not coverage.covers("A日")
    for name in ("Bold", "Italic", "BoldItalic"):
        assert read_coverage((FONTS / f"NotoSans-{name}.ttf").read_bytes()).has(ord("A"))


def test_bundled_font_format_4_matches_format_12_in_the_bmp():
    bmp_only = demote(REGULAR, (3, 10), (0, 4))
    _, subtables = cmap_subtables(bmp_only)
    assert struct.unpack_from(">H", bmp_only, subtables[(3, 1)])[0] == 4
    coverage = read_coverage(bmp_only)
    assert code_points(coverage) == reference_format_4(bmp_only, subtables[(3, 1)])
    full = read_coverage(REGULAR)
    assert code_points(coverage) == {c for c in code_points(full) if c <= 0xFFFF}
    assert read_coverage(bytearray(bmp_only)).code_points == coverage.code_points
    assert read_coverage(memoryview(bmp_only)).code_points == coverage.code_points


# --- Hand-built subtables -------------------------------------------------------------------

def test_format_4_edge_cases():
    table = format_4([
        (0x20, 0x7E, -29, None),                 # deltas: all real
        (0x100, 0x104, 0, [5, 0, 7, 0, 9]),      # glyph array with holes
        (0x200, 0x203, 0x10000 - 12, [12, 13, 0, 14]),   # 12 + delta wraps to glyph 0
        (0x300, 0x302, 0x10000 - 0x301, None),   # 0x301 + delta == 0: only that code
        (0x400, 0x3FF, 0, None),                 # start > end: skipped
    ])
    data = sfnt([((3, 1), table)])
    coverage = read_coverage(data)
    assert list(coverage.ranges()) == [(0x20, 0x7E), (0x100, 0x100), (0x102, 0x102),
                                       (0x104, 0x104), (0x201, 0x201), (0x203, 0x203),
                                       (0x300, 0x300), (0x302, 0x302)]
    assert code_points(coverage) == reference_format_4(data, cmap_subtables(data)[1][(3, 1)])


def test_format_12_edge_cases():
    groups = [(0x41, 0x43, 0), (0x44, 0x50, 10),       # glyph 0 drops 0x41 only; adjacent
              (0x1F600, 0x1F64F, 100), (0x60, 0x62, 3),    # out of order
              (0x70, 0x6F, 5), (0x10FFF0, 0x7FFFFFFF, 9)]  # empty; clipped to Unicode
    coverage = read_coverage(sfnt([((3, 10), format_12(groups))]))
    assert list(coverage.ranges()) == [(0x42, 0x50), (0x60, 0x62), (0x1F600, 0x1F64F),
                                       (0x10FFF0, 0x10FFFF)]
    merged = Coverage.from_ranges([(5, 9), (1, 3), (4, 4), (20, 10), (30, 31)])
    assert list(merged.ranges()) == [(1, 9), (30, 31)] and merged.code_points == 11


SUBTABLE_ORDER = [
    # subtables, expected first covered code point
    ([((3, 1), format_4([(0x41, 0x41, 1, None)])),
      ((3, 10), format_12([(0x1F600, 0x1F600, 1)]))], 0x1F600),        # (3,10) first
    ([((0, 3), format_4([(0x42, 0x42, 1, None)])),
      ((3, 1), format_4([(0x41, 0x41, 1, None)]))], 0x41),             # (3,1) > (0,3)
    ([((0, 4), format_12([(0x43, 0x43, 1)])),
      ((3, 1), format_4([(0x41, 0x41, 1, None)]))], 0x43),             # (0,4) > (3,1)
    ([((3, 10), struct.pack(">HH", 14, 0) + b"\0" * 12),
      ((3, 1), format_4([(0x41, 0x41, 1, None)]))], 0x41),             # format 14: next
    ([((3, 0), format_4([(0xF020, 0xF0FF, 1, None)]))], None),          # symbol font only
    ([((1, 0), struct.pack(">HHH", 0, 262, 0) + bytes(256))], None),   # Mac format 0 only
]


@pytest.mark.parametrize("subtables, first", SUBTABLE_ORDER)
def test_subtable_order(subtables, first):
    coverage = read_coverage(sfnt(subtables))
    assert (None if coverage is None else next(coverage.ranges())[0]) == first


def test_collection_reads_its_first_face():
    groups = [(0x3042, 0x3093, 1)]
    face = sfnt([((3, 10), format_12(groups))], base=16, version=b"OTTO")
    collection = b"ttcf" + struct.pack(">HHII", 1, 0, 1, 16) + face
    assert list(read_coverage(collection).ranges()) == [(0x3042, 0x3093)]
    assert read_coverage(b"ttcf" + struct.pack(">HHI", 1, 0, 0)) is None     # no faces


# --- Malformed and truncated files ----------------------------------------------------------

def test_malformed_and_truncated_files_give_none_and_never_raise():
    offset, subtables = cmap_subtables(REGULAR)
    sub12 = subtables[(3, 10)]
    cases = [b"", b"\0", b"OTTO", b"not a font at all", b"wOFF" + REGULAR[4:],
             REGULAR[:12], REGULAR[:offset + 20], REGULAR[:sub12 + 100]]
    huge_tables = bytearray(REGULAR)
    struct.pack_into(">H", huge_tables, 4, 5000)
    huge_groups = bytearray(REGULAR)
    struct.pack_into(">I", huge_groups, sub12 + 12, MAX_GROUPS + 1)
    past_end = bytearray(REGULAR)
    struct.pack_into(">I", past_end, sub12 + 12, 1_000_000 // 12)
    bad_offset = sfnt([((3, 1), format_4([(0x41, 0x41, 1, None)]))])
    bad_offset = bad_offset[:36] + struct.pack(">I", 0xFFFFFFF0) + bad_offset[40:]
    for data in (*cases, huge_tables, bad_offset):
        assert read_coverage(bytes(data)) is None
    bmp = code_points(read_coverage(demote(REGULAR, (3, 10), (0, 4))))
    for data in (past_end, huge_groups):        # a bad format 12: the format-4 subtable
        assert code_points(read_coverage(bytes(data))) == bmp
    # Cut anywhere, or bytes flipped inside cmap: None or a Coverage, never an exception.
    rng = random.Random(43)
    for cut in [*range(0, 64), *rng.sample(range(len(REGULAR)), 200)]:
        result = read_coverage(REGULAR[:cut])
        assert result is None or isinstance(result, Coverage)
    for _ in range(300):
        data = bytearray(REGULAR)
        for _ in range(rng.randint(1, 8)):
            data[rng.randrange(offset, offset + 4000)] = rng.randrange(256)
        result = read_coverage(bytes(data))
        assert result is None or isinstance(result, Coverage)
    garbage = rng.randbytes(4000)
    for prefix in (b"\x00\x01\x00\x00", b"OTTO", b"ttcf", b"true"):
        result = read_coverage(prefix + garbage)
        assert result is None or isinstance(result, Coverage)

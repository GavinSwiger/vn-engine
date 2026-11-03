"""Which characters a font file has: a bounded reader of the TrueType/OpenType ``cmap`` table
(F43 ``04`` §3, §4 answer 1; PR-F43-13).

Why this module exists: pygame-ce 2.5.8's ``Font.metrics`` returns ``.notdef`` metrics for a
missing character, so the font fallback chain (``render/fontchain``), ``check``'s W252 and
Studio's font notice can't ask pygame whether a font has a letter. They read the font's own
character map instead. ``core`` because render, ``check`` and Studio all need it, and Studio
and ``check`` may not import pygame.

What it reads: the table directory (``sfnt`` 1.0, ``OTTO``, ``true``; a ``ttcf`` collection's
first face, the one pygame opens) and the ``cmap`` table only. Of its subtables, the first in
the order (3,10) > (0,4) > (3,1) > (0,3) whose format is 4 or 12 is used. A code point is
covered when it maps to a glyph other than 0 (``.notdef``).

Bounds (§8 item 3): ≤ 1,024 tables, ≤ 1,024 encoding records, ≤ 32,767 format-4 segments,
≤ 200,000 format-12 groups; every offset and length is checked against the data. Anything
else (another format, a symbol font, a truncated or malformed file, not a font at all) gives
None, which callers read as "covers everything" (today's behaviour). ``read_coverage`` never
raises on bad bytes. It costs about 1–5 ms per file; callers keep the result per file.

Standard library only.
"""

import struct
import sys
from array import array
from bisect import bisect_right
from collections.abc import Iterable, Iterator
from typing import Final

MAX_TABLES: Final = 1024
MAX_ENCODING_RECORDS: Final = 1024
MAX_SEGMENTS: Final = 32767
MAX_GROUPS: Final = 200_000
MAX_CODE_POINT: Final = 0x10FFFF

# (platform, encoding) in preference order: Unicode full repertoire first, then BMP.
SUBTABLE_ORDER: Final = ((3, 10), (0, 4), (3, 1), (0, 3))

_SFNT_VERSIONS: Final = (b"\x00\x01\x00\x00", b"OTTO", b"true")
_COLLECTION: Final = b"ttcf"
_CMAP: Final = b"cmap"
_LITTLE: Final = sys.byteorder == "little"

# Code points a font never needs a glyph for (``covers`` skips them): ZWNJ, ZWJ, and the
# variation selectors.
_IGNORABLE_RANGES: Final = ((0x200C, 0x200D), (0xFE00, 0xFE0F), (0xE0100, 0xE01EF))


class Coverage:
    """The code points a font has, as sorted, disjoint, non-adjacent inclusive ranges in two
    ``array('I')`` (4 bytes per range end; ≤ about 0.5 MB for a CJK font)."""

    __slots__ = ("_starts", "_ends", "_count")

    def __init__(self, starts: array, ends: array) -> None:
        self._starts = starts
        self._ends = ends
        self._count = sum(e - s + 1 for s, e in zip(starts, ends))

    @classmethod
    def from_ranges(cls, ranges: Iterable[tuple[int, int]]) -> "Coverage":
        """A coverage of inclusive ``(first, last)`` ranges in any order (overlaps merge;
        empty and out-of-Unicode parts drop). For tests and fakes."""
        starts, ends = _merge(sorted(ranges))
        return cls(starts, ends)

    def has(self, code_point: int) -> bool:
        """Whether the font maps ``code_point`` to a real glyph."""
        i = bisect_right(self._starts, code_point) - 1
        return i >= 0 and code_point <= self._ends[i]

    def covers(self, text: str) -> bool:
        """Whether the font has every code point of ``text`` (a grapheme), ignoring ZWJ,
        ZWNJ and variation selectors."""
        for char in text:
            cp = ord(char)
            if not self.has(cp) and not _ignorable(cp):
                return False
        return True

    def ranges(self) -> Iterator[tuple[int, int]]:
        """The inclusive ranges, in order."""
        return zip(self._starts, self._ends)

    @property
    def code_points(self) -> int:
        """How many code points are covered."""
        return self._count

    def __len__(self) -> int:
        """The number of ranges."""
        return len(self._starts)

    def __repr__(self) -> str:
        return f"Coverage({len(self)} ranges, {self._count} code points)"


def read_coverage(data: bytes | bytearray | memoryview) -> Coverage | None:
    """The coverage of the font file ``data``, or None when it can't be read (see the
    module docstring). Never raises on bad bytes."""
    try:
        cmap = _find_cmap(data if isinstance(data, bytes) else bytes(data))
        if cmap is None:
            return None
        found = _read_cmap(*cmap)
        if found is None:
            return None
        return Coverage(*found)
    except (struct.error, ValueError, IndexError, OverflowError, TypeError, MemoryError):
        return None


# --- Table directory --------------------------------------------------------------------------

def _find_cmap(data: bytes) -> tuple[bytes, int, int] | None:
    """(data, offset, length) of the ``cmap`` table of the file's first face."""
    base = 0
    tag = data[:4]
    if tag == _COLLECTION:
        (count,) = struct.unpack_from(">I", data, 8)
        if count < 1:
            return None
        (base,) = struct.unpack_from(">I", data, 12)
        tag = data[base:base + 4]
    if tag not in _SFNT_VERSIONS:
        return None
    (tables,) = struct.unpack_from(">H", data, base + 4)
    if tables > MAX_TABLES:
        return None
    for i in range(tables):
        name, _, offset, length = struct.unpack_from(">4sIII", data, base + 12 + 16 * i)
        if name == _CMAP:
            if offset + length > len(data) or length < 4:
                return None
            return data, offset, length
    return None


def _read_cmap(data: bytes, offset: int, length: int) -> tuple[array, array] | None:
    end = offset + length
    _, records = struct.unpack_from(">HH", data, offset)
    if records > MAX_ENCODING_RECORDS or offset + 4 + 8 * records > end:
        return None
    subtables: dict[tuple[int, int], int] = {}
    for i in range(records):
        platform, encoding, sub = struct.unpack_from(">HHI", data, offset + 4 + 8 * i)
        subtables.setdefault((platform, encoding), sub)
    for key in SUBTABLE_ORDER:
        sub = subtables.get(key)
        if sub is None or offset + sub + 2 > end:
            continue
        start = offset + sub
        (fmt,) = struct.unpack_from(">H", data, start)
        if fmt == 4:
            ranges = _format_4(data, start, end)
        elif fmt == 12:
            ranges = _format_12(data, start, end)
        else:
            continue
        if ranges is not None:
            return ranges
    return None


# --- Format 4: segment mapping to delta values (BMP) -------------------------------------------

def _format_4(data: bytes, start: int, end: int) -> tuple[array, array] | None:
    if start + 14 > end:
        return None
    (seg_x2,) = struct.unpack_from(">H", data, start + 6)
    segments = seg_x2 // 2
    if segments < 1 or segments > MAX_SEGMENTS:
        return None
    ends_at = start + 14
    starts_at = ends_at + seg_x2 + 2                 # reservedPad
    deltas_at = starts_at + seg_x2
    offsets_at = deltas_at + seg_x2
    if offsets_at + seg_x2 > end:
        return None
    seg_ends = _u16_array(data, ends_at, segments)
    seg_starts = _u16_array(data, starts_at, segments)
    deltas = _u16_array(data, deltas_at, segments)
    offsets = _u16_array(data, offsets_at, segments)
    ranges: list[tuple[int, int]] = []
    for i in range(segments):
        first, last, delta, range_offset = seg_starts[i], seg_ends[i], deltas[i], offsets[i]
        if first > last:
            continue
        if range_offset == 0:
            missing = (-delta) & 0xFFFF                  # the one code mapping to glyph 0
            if first <= missing <= last:
                ranges.append((first, missing - 1))
                ranges.append((missing + 1, last))
            else:
                ranges.append((first, last))
            continue
        # glyphIdArray slice: idRangeOffset is a byte offset from its own word.
        at = offsets_at + 2 * i + range_offset
        count = last - first + 1
        if at + 2 * count > end:
            count = max(0, (end - at) // 2)              # a short array: keep what's there
        if count == 0:
            continue
        # A code is missing when its entry is 0 or entry + delta wraps to 0. Those are rare,
        # so find them with bytes.find rather than a loop per code point.
        raw = data[at:at + 2 * count]
        holes = _positions(raw, 0)
        if delta:
            holes |= _positions(raw, (-delta) & 0xFFFF)
        run = first
        for k in sorted(holes):
            ranges.append((run, first + k - 1))
            run = first + k + 1
        ranges.append((run, first + count - 1))
    ranges.sort()
    return _merge(ranges)


# --- Format 12: segmented coverage (full Unicode) ----------------------------------------------

def _format_12(data: bytes, start: int, end: int) -> tuple[array, array] | None:
    if start + 16 > end:
        return None
    (groups,) = struct.unpack_from(">I", data, start + 12)
    if groups > MAX_GROUPS or start + 16 + 12 * groups > end:
        return None
    values = array("I")
    values.frombytes(data[start + 16:start + 16 + 12 * groups])
    if _LITTLE:
        values.byteswap()
    # Fonts store groups sorted (the spec requires it): merge in one pass, and fall back to
    # sort-and-merge only for a file that doesn't.
    starts, ends = array("I"), array("I")
    run_first = run_last = -2
    for first, last, glyph in zip(values[0::3], values[1::3], values[2::3]):
        if glyph == 0:
            first += 1                               # only ``first`` maps to .notdef
        if last > MAX_CODE_POINT:
            last = MAX_CODE_POINT
        if first > last:
            continue
        if first <= run_last:
            return _merge_unsorted(values)
        if first == run_last + 1:
            run_last = last
            continue
        if run_first >= 0:
            starts.append(run_first)
            ends.append(run_last)
        run_first, run_last = first, last
    if run_first >= 0:
        starts.append(run_first)
        ends.append(run_last)
    return starts, ends


def _merge_unsorted(values: array) -> tuple[array, array]:
    """Format-12 groups (first, last, glyph triples) in any order → merged ranges."""
    ranges = [(first + (glyph == 0), last)
              for first, last, glyph in zip(values[0::3], values[1::3], values[2::3])]
    ranges.sort()
    return _merge(ranges)


# --- Helpers ------------------------------------------------------------------------------------

def _u16_array(data: bytes, at: int, count: int) -> array:
    values = array("H")
    values.frombytes(data[at:at + 2 * count])
    if _LITTLE:
        values.byteswap()
    return values


def _positions(raw: bytes, value: int) -> set[int]:
    """The indexes of the big-endian u16 ``value`` in ``raw`` (2-byte aligned)."""
    needle = struct.pack(">H", value)
    found = set()
    i = raw.find(needle)
    while i >= 0:
        if i % 2 == 0:
            found.add(i // 2)
            i = raw.find(needle, i + 2)
        else:
            i = raw.find(needle, i + 1)
    return found


def _merge(ranges: Iterable[tuple[int, int]]) -> tuple[array, array]:
    """Sorted ranges → merged ``(starts, ends)``, clipped to Unicode; empty ones drop."""
    starts, ends = array("I"), array("I")
    for first, last in ranges:
        if first < 0:
            first = 0
        if last > MAX_CODE_POINT:
            last = MAX_CODE_POINT
        if first > last:
            continue
        if ends and first <= ends[-1] + 1:
            if last > ends[-1]:
                ends[-1] = last
        else:
            starts.append(first)
            ends.append(last)
    return starts, ends


def _ignorable(cp: int) -> bool:
    return any(low <= cp <= high for low, high in _IGNORABLE_RANGES)

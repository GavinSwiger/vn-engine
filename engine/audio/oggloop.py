"""Loop points: ``LOOPSTART``/``LOOPLENGTH`` comments written into an Ogg Vorbis or Opus file's
header, and the session's tag cache (F08 ``04-technical.md`` §7.5, §7.7; ``02`` SR-F08-09, 23,
W28, W31; ``07`` I-9; AC-F08-23, 24).

Why this module exists: ``[audio.loop_start]`` gives a file a loop point (the first pass plays
from 0, every later pass from the loop point). SDL_mixer's Ogg Vorbis and Opus music decoders
already loop sample-exact between ``LOOPSTART`` and ``LOOPSTART + LOOPLENGTH`` when the stream
plays with ``loops=-1`` (they seek inside the decoder, in the audio thread, so there is no
gap, unlike a queue transition, which waits for the next 512-frame buffer). So instead of
seeking from Python, the engine hands SDL the file's bytes with those two comments added:

1. Page 0 gives Vorbis (with its rate) or Opus (48,000 Hz, with ``pre_skip``). Total samples
   = the last page's granule, minus ``pre_skip`` for Opus. A start at or past the total is
   W28 and a plain loop.
2. The header packets (Vorbis: comment and setup; Opus: ``OpusTags``) are reassembled from
   pages 1…k, which must end on a page boundary. Every ``LOOP*`` comment is removed, and
   ``LOOPSTART`` and ``LOOPLENGTH = total − start`` are added.
3. They are laced again into the **same k pages**, keeping each page's header fields (so
   page numbers and every later page stay as they are), and only those pages' CRCs are
   recomputed (polynomial 0x04C11DB7). If more room would be needed, or the file is
   malformed (a bad CRC, a header that shares its last page with audio, …), the result is
   W31's run form and a plain loop. Later pages are copied unchanged.
4. ``LoopPoints`` caches the verdict per file for the session: only the rewritten header
   pages, or the W31/W28 verdict (I-9), never the whole file. Other formats with a loop
   start loop from the start (C4); their W31 was given at launch, so at run there is no
   further record.

Effects use the same verdict (SR-F08-23: the loop point belongs to the file): a looping
effect plays its whole sound once and then a second Sound, the decoded samples from the loop
point on, queued on its channel (``effects.py``).

Pure: bytes in, bytes out; no pygame.
"""

import hashlib
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from engine.audio.reading import AUDIO_FOLDER, AudioLog, suffix
from engine.audio.sniff import Sniffed, ogg_last_granule, sniff
from engine.core.redact import echo

OGG_CRC_POLY: Final = 0x04C11DB7
OPUS_RATE: Final = 48_000
LOOP_EXTS: Final = frozenset((".ogg", ".opus"))
_HEADER = 27                         # bytes of a page header before its segment table
_MAX_SEGMENTS = 255
_HEADER_PAGES_MAX = 16               # header packets spread over more pages: malformed


def _crc_table() -> tuple[int, ...]:
    table = []
    for byte in range(256):
        crc = byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ OGG_CRC_POLY) if crc & 0x8000_0000 else crc << 1
        table.append(crc & 0xFFFF_FFFF)
    return tuple(table)


_CRC_TABLE: Final = _crc_table()


def ogg_crc(page: bytes) -> int:
    """The Ogg page checksum of ``page`` (its CRC field must already be zero): CRC-32 with
    polynomial 0x04C11DB7, not reflected, initial value 0, no final xor."""
    crc = 0
    table = _CRC_TABLE
    for byte in page:
        crc = ((crc << 8) & 0xFFFF_FFFF) ^ table[(crc >> 24) ^ byte]
    return crc


# --- Pages -----------------------------------------------------------------------------------

class Malformed(Exception):
    """The file isn't an Ogg stream this module can rewrite (W31's run form)."""


@dataclass(frozen=True, slots=True)
class Page:
    """One Ogg page at ``offset``: its fixed header fields, segment table, and body."""

    offset: int
    fixed: bytes                     # the 27 header bytes (CRC included)
    lacing: bytes
    body: bytes

    @property
    def end(self) -> int:
        return self.offset + _HEADER + len(self.lacing) + len(self.body)

    @property
    def flags(self) -> int:
        return self.fixed[5]

    @property
    def serial(self) -> int:
        return int.from_bytes(self.fixed[14:18], "little")

    @property
    def sequence(self) -> int:
        return int.from_bytes(self.fixed[18:22], "little")


def read_page(data: bytes, at: int) -> Page:
    """The page at ``at``, its CRC checked; raises ``Malformed``."""
    if data[at:at + 4] != b"OggS" or len(data) < at + _HEADER or data[at + 4] != 0:
        raise Malformed("no page")
    count = data[at + 26]
    lacing = data[at + _HEADER:at + _HEADER + count]
    body_at = at + _HEADER + count
    size = sum(lacing)
    if len(lacing) != count or len(data) < body_at + size:
        raise Malformed("short page")
    page = Page(at, data[at:at + _HEADER], lacing, data[body_at:body_at + size])
    if build_page(page.fixed, page.lacing, page.body) != data[at:page.end]:
        raise Malformed("bad CRC")
    return page


def build_page(fixed: bytes, lacing: bytes, body: bytes) -> bytes:
    """A page from its header fields (``fixed``; segment count and CRC are rewritten), its
    segment table, and its body, with a fresh CRC."""
    head = bytearray(fixed[:22]) + b"\0\0\0\0" + bytes([len(lacing)])
    raw = bytes(head) + lacing + body
    crc = ogg_crc(raw)
    return raw[:22] + struct.pack("<I", crc) + raw[26:]


def _packets(pages: list[Page]) -> list[bytes]:
    """The whole packets laced into ``pages`` (which must end on a packet boundary)."""
    packets: list[bytes] = []
    current = bytearray()
    for page in pages:
        at = 0
        for value in page.lacing:
            current += page.body[at:at + value]
            at += value
            if value < 255:
                packets.append(bytes(current))
                current = bytearray()
    if current:
        raise Malformed("the header ends inside a packet")
    return packets


def _lacing(packet: bytes) -> list[int]:
    return [255] * (len(packet) // 255) + [len(packet) % 255]


# --- Comments ----------------------------------------------------------------------------------

def _rewrite_comments(packet: bytes, magic: bytes, tags: list[bytes]) -> bytes:
    """``packet`` (a Vorbis comment header or ``OpusTags``) without its ``LOOP*`` comments
    and with ``tags`` appended; anything after the comment list (Vorbis's framing bit,
    Opus's binary suffix) is kept."""
    if not packet.startswith(magic):
        raise Malformed("no comment header")
    at = len(magic)

    def u32() -> int:
        nonlocal at
        if at + 4 > len(packet):
            raise Malformed("short comment header")
        value = int.from_bytes(packet[at:at + 4], "little")
        at += 4
        return value

    vendor_len = u32()
    vendor = packet[at:at + vendor_len]
    at += vendor_len
    if len(vendor) != vendor_len:
        raise Malformed("short vendor")
    count = u32()
    kept: list[bytes] = []
    for _ in range(count):
        size = u32()
        comment = packet[at:at + size]
        at += size
        if len(comment) != size:
            raise Malformed("short comment")
        if not comment.split(b"=", 1)[0].upper().startswith(b"LOOP"):
            kept.append(comment)
    tail = packet[at:]
    if magic == b"\x03vorbis" and (not tail or not tail[0] & 1):
        raise Malformed("no framing bit")
    out = bytearray(magic) + struct.pack("<I", vendor_len) + vendor
    out += struct.pack("<I", len(kept) + len(tags))
    for comment in kept + tags:
        out += struct.pack("<I", len(comment)) + comment
    return bytes(out + tail)


# --- add_loop_tags -----------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Tagged:
    """The rewritten header pages: ``header`` replaces the file's first ``header_end``
    bytes. ``start``/``total`` are samples at ``rate``."""

    header: bytes
    header_end: int
    start: int
    total: int
    rate: int

    @property
    def seconds(self) -> float:
        """The loop start in seconds."""
        return self.start / self.rate

    def apply(self, data: bytes) -> bytes:
        return self.header + data[self.header_end:]


@dataclass(frozen=True, slots=True)
class PastEnd:
    """W28: the loop start is at or past the track's end (``seconds`` long)."""

    seconds: float


@dataclass(frozen=True, slots=True)
class NoRoom:
    """W31's run form: the header can't take the tags, or the file is malformed."""

    reason: str


LoopTags = Tagged | PastEnd | NoRoom


def add_loop_tags(data: bytes, start: float) -> LoopTags:
    """§7.5: ``data`` (an Ogg Vorbis or Opus file) with ``LOOPSTART``/``LOOPLENGTH`` set for a
    loop from ``start`` seconds to the end. Never raises."""
    try:
        return _add_loop_tags(data, start)
    except Malformed as error:
        return NoRoom(str(error))
    except (IndexError, ValueError, struct.error) as error:     # defensive: still a verdict
        return NoRoom(type(error).__name__)


def _add_loop_tags(data: bytes, start: float) -> LoopTags:
    first = read_page(data, 0)
    if not first.flags & 0x02 or len(first.lacing) != 1 or first.lacing[0] == 255:
        raise Malformed("page 0 isn't one identification packet")
    ident = first.body
    if ident.startswith(b"\x01vorbis") and len(ident) >= 16:
        rate = int.from_bytes(ident[12:16], "little")
        magic, wanted, pre_skip = b"\x03vorbis", 2, 0
    elif ident.startswith(b"OpusHead") and len(ident) >= 12:
        rate = OPUS_RATE
        magic, wanted = b"OpusTags", 1
        pre_skip = int.from_bytes(ident[10:12], "little")
    else:
        raise Malformed("neither Vorbis nor Opus")
    if rate <= 0:
        raise Malformed("no rate")
    granule = ogg_last_granule(data)
    if granule is None:
        raise Malformed("no granule")
    total = max(0, granule - pre_skip)
    begin = round(start * rate)
    if begin >= total:
        return PastEnd(total / rate)

    # Pages 1…k hold the header packets and must end on a packet boundary.
    pages: list[Page] = []
    at = first.end
    count = 0
    while count < wanted:
        if len(pages) >= _HEADER_PAGES_MAX:
            raise Malformed("header too long")
        page = read_page(data, at)
        if page.serial != first.serial or page.sequence != first.sequence + 1 + len(pages):
            raise Malformed("not the next page of the stream")
        if not pages and page.flags & 0x01:
            raise Malformed("page 1 continues a packet")
        pages.append(page)
        count += sum(1 for value in page.lacing if value < 255)
        at = page.end
    if count != wanted or pages[-1].lacing[-1] == 255:
        raise Malformed("the header shares its last page")
    packets = _packets(pages)
    tags = [b"LOOPSTART=%d" % begin, b"LOOPLENGTH=%d" % (total - begin)]
    packets[0] = _rewrite_comments(packets[0], magic, tags)

    # Lace into the same pages: each keeps its segment count where it can; the change in
    # size goes to (or comes from) the earliest pages with room.
    lacing = [value for packet in packets for value in _lacing(packet)]
    body = b"".join(packets)
    counts = [len(page.lacing) for page in pages]
    delta = len(lacing) - sum(counts)
    for index in range(len(counts)):
        if delta > 0:
            take = min(delta, _MAX_SEGMENTS - counts[index])
        else:
            take = -min(-delta, counts[index] - 1)
        counts[index] += take
        delta -= take
    if delta:
        return NoRoom("no room")
    out = bytearray(data[:first.end])
    seg = pos = 0
    for index, (page, n) in enumerate(zip(pages, counts, strict=True)):
        own = bytes(lacing[seg:seg + n])
        continued = index > 0 and lacing[seg - 1] == 255
        if continued != bool(page.flags & 0x01):
            return NoRoom("the pages' continuation flags would change")
        size = sum(own)
        out += build_page(page.fixed, own, body[pos:pos + size])
        seg += n
        pos += size
    return Tagged(bytes(out), at, begin, total, rate)


# --- The tag cache (§7.5 step 4, I-9) --------------------------------------------------------

def _seconds_text(value: float) -> str:
    """A config value as the author wrote it: ``95``, ``4.5``."""
    text = repr(float(value))
    return text[:-2] if text.endswith(".0") else text


def _mss(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def w28_text(file: str, start: float, length: float) -> str:
    """W28 (``02`` §5.4): the loop point is at or past the end of the track."""
    end = _mss(length)
    return (f'[audio.loop_start] "{echo(file)}" = {_seconds_text(start)} is past the end of '
            f"the track ({end}), so it loops from the start. Use a time before {end}.")


def w31_run_text(file: str) -> str:
    """W31's run form (``02`` §5.4): the header has no room for the loop tags."""
    return (f"{echo(AUDIO_FOLDER + file)} can't use its loop point because the file's header "
            f"has no room for the loop tags, so it loops from the start. Export it again as "
            f"{echo(suffix(file))}.")


@dataclass(frozen=True, slots=True)
class _Entry:
    """A cached verdict for one file's bytes (identified by size and header digest)."""

    size: int
    digest: bytes
    tags: Tagged | None


class LoopPoints:
    """The session's loop points: ``starts`` is ``[audio.loop_start]`` (file as written ->
    seconds). ``music(file, data)`` is ``MusicPlayer``'s ``loop_point``; ``sound_start``
    gives an effect the same loop point. Each verdict is logged once per path (W28, W31)
    and cached per file: the rewritten header pages or None, never the file (I-9). At most
    one entry per ``[audio.loop_start]`` key, so the cache is bounded by the config."""

    def __init__(self, starts: Mapping[str, float], log: AudioLog) -> None:
        self.starts = dict(starts)
        self.log = log
        self._cache: dict[str, _Entry] = {}

    def tags(self, file: str, data: Sniffed) -> Tagged | None:
        """The loop tags for ``file`` (None: it loops from the start)."""
        start = self.starts.get(file)
        if start is None or start <= 0.0 or data.ext not in LOOP_EXTS:
            return None                  # no loop point, or C4 (W31 was given at launch)
        raw = data.data
        digest = hashlib.blake2b(raw[:65_536], digest_size=16).digest()
        entry = self._cache.get(file)
        if entry is None or entry.size != len(raw) or entry.digest != digest:
            verdict = add_loop_tags(raw, start)
            if isinstance(verdict, PastEnd):
                self.log.problem("loop_past_end", file,
                                 w28_text(file, start, verdict.seconds), code="W28")
            elif isinstance(verdict, NoRoom):
                self.log.problem("loop_no_room", file, w31_run_text(file), code="W31")
            entry = _Entry(len(raw), digest, verdict if isinstance(verdict, Tagged) else None)
            self._cache[file] = entry
        return entry.tags

    def music(self, file: str, data: Sniffed) -> tuple[Sniffed, float] | None:
        """``MusicPlayer.loop_point``: the bytes to play (the tags added) and the loop start
        in seconds, or None (a plain loop)."""
        tags = self.tags(file, data)
        if tags is None:
            return None
        tagged = sniff(tags.apply(data.data), data.ext)
        return None if tagged is None else (tagged, tags.seconds)

    def sound_start(self, file: str, data: Sniffed) -> float | None:
        """An effect's loop start in seconds (the same verdict as the music's), or None."""
        tags = self.tags(file, data)
        return None if tags is None else tags.seconds


__all__ = ["LOOP_EXTS", "LoopPoints", "LoopTags", "Malformed", "NoRoom", "OGG_CRC_POLY",
           "Page", "PastEnd", "Tagged", "add_loop_tags", "build_page", "ogg_crc", "read_page",
           "w28_text", "w31_run_text"]

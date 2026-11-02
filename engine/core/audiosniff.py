"""Content sniffing before any decode (F08 ``04-technical.md`` §7.4 steps 3–4, §8 items 3, 5;
TR-F08-04; AC-F08-35, 36, 37).

Why this module exists: ``pygame.mixer.Sound`` takes no type hint, so SDL_mixer picks the
decoder from the content: a MIDI file or a tracker module renamed to ``.ogg`` would reach a
MIDI or tracker decoder (``06`` §0.6 item 3). For effects and voice the sniff is therefore the
only barrier: the bytes at offset 0 must match the file's extension, and MIDI and tracker
signatures are refused whatever the extension. ``sniff`` returns a ``Sniffed`` value, the only
thing ``MixerBackend.decode`` accepts, so no unsniffed bytes can reach SDL.

``declared_seconds`` reads the length a file declares (Ogg last granule, FLAC STREAMINFO, WAV
``data`` size) so an effect over ``SOUND_MAX_SECONDS`` is refused before its decode. A file
that lies about its length can still force a large decode; only game or mod content can do
that, and it is trusted (§8 item 3).

Pure: bytes in, values out; stdlib only. Lifted from ``audio/sniff.py`` (F45 ``04`` Q5), so
Studio (``tools/editor``, which may import only ``core`` and ``script``) checks an added file
with the same code the mixer trusts; ``audio/sniff.py`` re-exports every name, so ``Sniffed``
stays one class.
"""

from typing import Final

# The playable extensions (``script/audio.py`` ``PLAYABLE_EXTS``; ``audio`` may not import
# ``script``, so tests check the two agree) and the format each names in W26.
FORMAT_NAMES: Final[dict[str, str]] = {
    ".ogg": "Ogg Vorbis",
    ".opus": "Opus",
    ".flac": "FLAC",
    ".mp3": "MP3",
    ".wav": "WAV",
}

_OGG_HEADER = 27                     # bytes of an Ogg page header before its segment table
_OGG_TAIL_SEARCH = 65_536 + 1_024    # the last page starts within this many bytes of the end
_OGG_PAGE_TRIES = 32                 # pages looked at from the end for a granule position
_OPUS_RATE = 48_000
_MOD_MAGICS = (b"M.K.", b"M!K!", b"FLT4")
_token = object()                    # only ``sniff`` builds a ``Sniffed``


class Sniffed:
    """Bytes ``sniff`` accepted for extension ``ext``: the only input of
    ``MixerBackend.decode`` (AC-F08-36's guard object)."""

    __slots__ = ("data", "ext")

    def __init__(self, data: bytes, ext: str, token: object) -> None:
        if token is not _token:
            raise TypeError("Sniffed values come only from sniff()")
        self.data = data
        self.ext = ext


def refused_signature(data: bytes) -> bool:
    """MIDI (``MThd``, ``RIFF…RMID``) or a tracker module (XM, IT, S3M, MOD), whatever the
    extension (§7.4 step 3)."""
    return (data[:4] == b"MThd"
            or (data[:4] == b"RIFF" and data[8:12] == b"RMID")
            or data[:16] == b"Extended Module:"
            or data[:4] == b"IMPM"
            or data[44:48] == b"SCRM"
            or data[1080:1084] in _MOD_MAGICS)


def _ogg_first_packet(data: bytes) -> bytes:
    """The start of the first packet of the first Ogg page (b"" if there is none)."""
    if len(data) < _OGG_HEADER or data[:4] != b"OggS":
        return b""
    segments = data[26]
    start = _OGG_HEADER + segments
    size = sum(data[_OGG_HEADER:start])
    return data[start:start + size] if len(data) >= start else b""


def _is_mp3(data: bytes) -> bool:
    """``ID3`` or an MPEG audio frame sync whose version and layer are not reserved."""
    if data[:3] == b"ID3":
        return True
    if len(data) < 2 or data[0] != 0xFF or data[1] & 0xE0 != 0xE0:
        return False
    return (data[1] >> 3) & 0b11 != 0b01 and (data[1] >> 1) & 0b11 != 0b00


def matches(data: bytes, ext: str) -> bool:
    """True if ``data`` starts as a file of extension ``ext`` should (§7.4 step 3). An
    Opus stream in an ``.ogg`` file doesn't match: the music hint ``ogg`` refuses it."""
    if ext == ".ogg":
        return _ogg_first_packet(data).startswith(b"\x01vorbis")
    if ext == ".opus":
        return _ogg_first_packet(data).startswith(b"OpusHead")
    if ext == ".flac":
        return data[:4] == b"fLaC"
    if ext == ".wav":
        return data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    if ext == ".mp3":
        return _is_mp3(data)
    return False


def sniff(data: bytes, ext: str) -> Sniffed | None:
    """``Sniffed`` if ``data`` is what extension ``ext`` (lower case, with the dot) says and
    carries no refused signature; None otherwise (the caller logs W26 "isn't really")."""
    if ext not in FORMAT_NAMES or refused_signature(data) or not matches(data, ext):
        return None
    return Sniffed(data, ext, _token)


# --- Declared length (§7.4 step 4) -------------------------------------------------------------

def _ogg_last_granule(data: bytes) -> int | None:
    """The granule position of the last Ogg page that has one, or None."""
    end = len(data)
    floor = max(0, end - _OGG_TAIL_SEARCH)
    for _ in range(_OGG_PAGE_TRIES):
        at = data.rfind(b"OggS", floor, end)
        if at < 0:
            return None
        if at + _OGG_HEADER <= len(data) and data[at + 4] == 0:
            granule = int.from_bytes(data[at + 6:at + 14], "little", signed=True)
            if granule >= 0:
                return granule
        end = at
    return None


def ogg_last_granule(data: bytes) -> int | None:
    """The granule position of the last Ogg page that has one (``oggloop``'s total)."""
    return _ogg_last_granule(data)


def _ogg_seconds(data: bytes, ext: str) -> float | None:
    packet = _ogg_first_packet(data)
    granule = _ogg_last_granule(data)
    if granule is None:
        return None
    if ext == ".opus":
        pre_skip = int.from_bytes(packet[10:12], "little") if len(packet) >= 12 else 0
        return max(0, granule - pre_skip) / _OPUS_RATE
    rate = int.from_bytes(packet[12:16], "little") if len(packet) >= 16 else 0
    return granule / rate if rate > 0 else None


def _flac_seconds(data: bytes) -> float | None:
    """From STREAMINFO, the first metadata block: 20-bit rate, 36-bit total samples."""
    if len(data) < 42 or data[4] & 0x7F != 0:
        return None
    bits = int.from_bytes(data[18:26], "big")
    rate = bits >> 44
    total = bits & ((1 << 36) - 1)
    return total / rate if rate > 0 and total > 0 else None


def _wav_seconds(data: bytes, *, clamp: bool = True) -> float | None:
    """The ``data`` chunk's size (``clamp``: no more than the bytes present) over ``fmt``'s
    byte rate."""
    byte_rate = 0
    at = 12
    while at + 8 <= len(data):
        chunk = data[at:at + 4]
        size = int.from_bytes(data[at + 4:at + 8], "little")
        body = at + 8
        if chunk == b"fmt " and size >= 12:
            byte_rate = int.from_bytes(data[body + 8:body + 12], "little")
        elif chunk == b"data":
            present = min(size, len(data) - body) if clamp else size
            return present / byte_rate if byte_rate > 0 else None
        at = body + size + (size & 1)
    return None


def declared_seconds(sniffed: Sniffed, *, header: bool = False) -> float | None:
    """The length the file declares, in seconds; None when unknown (MP3, or a header the
    reader doesn't find). A WAV's ``data`` size counts only the bytes present unless
    ``header`` (a music track's known length for W27: a cut file declares more)."""
    data, ext = sniffed.data, sniffed.ext
    if ext in (".ogg", ".opus"):
        return _ogg_seconds(data, ext)
    if ext == ".flac":
        return _flac_seconds(data)
    if ext == ".wav":
        return _wav_seconds(data, clamp=not header)
    return None


__all__ = ["FORMAT_NAMES", "Sniffed", "declared_seconds", "matches", "ogg_last_granule",
           "refused_signature", "sniff"]

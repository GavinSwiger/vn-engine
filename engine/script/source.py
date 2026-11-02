"""Decoding a script file and walking its physical lines (F02 ``04-technical.md`` §7.2).

``decode_script`` turns the bytes of one ``.vns`` file into text with ``"\\n"`` line ends, or
reports the one whole-file problem (E01a, E01b, E02; SR-F02-05/06). ``LineCursor`` yields the
physical lines lazily with a one-line peek, so a 16 MB file of empty lines never becomes a
16-million-item list. Control and line-separator characters (SR-F02-08, E03/E04) are found
by one regex pass over the whole text and handed out per line, at most one per line.
"""

import re
from dataclasses import dataclass

# Binary signatures (§7.2): PNG, JPEG, GIF, ZIP, PDF, gzip, RIFF, Ogg, ID3, FLAC, 7z, RAR, ELF.
_SIGNATURES: tuple[bytes, ...] = (
    b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"PK\x03\x04", b"%PDF-",
    b"\x1f\x8b", b"RIFF", b"OggS", b"ID3", b"fLaC", b"7z\xbc\xaf\x27\x1c", b"Rar!\x1a\x07",
    b"\x7fELF",
)
_UTF32_BOMS = (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
_UTF8_BOM = b"\xef\xbb\xbf"

# SR-F02-08: C0/C1 controls other than tab (CR and LF are line ends by now), U+2028, U+2029.
CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f  ]")
# E04 characters; every other CONTROL_RE match is E03.
SEPARATORS = frozenset("\x85  ")


@dataclass(frozen=True, slots=True)
class Decoded:
    """The result of ``decode_script``.

    ``text`` has ``"\\n"`` line ends. ``problem`` is ``(code, args, line)`` for the one
    whole-file problem, else None. After E01a, ``text`` is the ``errors="replace"`` decode,
    kept only for name salvage (§7.6.2); after E01b/E02 it is None.
    """

    text: str | None
    problem: tuple[str, tuple, int | None] | None = None


def _line_of(data: bytes, end: int) -> int:
    """1 + the number of line ends (LF, CR, CRLF) in ``data[:end]``."""
    head = data[:end]
    return 1 + head.count(b"\n") + head.count(b"\r") - head.count(b"\r\n")


def normalize_line_ends(text: str) -> str:
    """CRLF and CR become LF (SR-F02-07)."""
    if "\r" not in text:
        return text
    return text.replace("\r\n", "\n").replace("\r", "\n")


def decode_script(ref: str, data: bytes) -> Decoded:
    """Decode one script file (first match wins, §7.2). Never raises."""
    if data.startswith(_UTF32_BOMS):
        return Decoded(None, ("E01b", (ref, "UTF-32"), None))
    if data.startswith(_UTF16_BOMS):
        return Decoded(None, ("E01b", (ref, "UTF-16"), None))
    if data.startswith(_SIGNATURES) or b"\x00" in data:
        return Decoded(None, ("E02", (ref,), None))
    if data.startswith(_UTF8_BOM):
        data = data[len(_UTF8_BOM):]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        salvage = normalize_line_ends(data.decode("utf-8", errors="replace"))
        return Decoded(salvage, ("E01a", (), _line_of(data, exc.start)))
    return Decoded(normalize_line_ends(text))


@dataclass(frozen=True, slots=True)
class PhysicalLine:
    """One physical line: 1-based number, text without its line end, and the first
    SR-F02-08 character in it as ``(column, char)`` or None."""

    number: int
    text: str
    control: tuple[int, str] | None = None


class LineCursor:
    """Physical lines of decoded text, one at a time, with a one-line peek."""

    __slots__ = ("_text", "_pos", "_number", "_peeked", "_controls", "_control")

    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0
        self._number = 0
        self._peeked: PhysicalLine | None = None
        self._controls = CONTROL_RE.finditer(text)
        self._control = next(self._controls, None)

    @property
    def lines_read(self) -> int:
        """How many physical lines have been produced (peeked ones included)."""
        return self._number

    @property
    def text(self) -> str:
        return self._text

    def free_position(self) -> int | None:
        """Where the next unread line starts, or None while a line is peeked."""
        return None if self._peeked is not None else self._pos

    def skip_to(self, end: int) -> int:
        """Pass over the whole lines from ``free_position()`` to ``end`` (just after a line
        end) without producing them; returns how many. The caller makes sure they hold no
        SR-F02-08 character (the control matches before the next line are dropped lazily by
        ``_read``)."""
        count = self._text.count("\n", self._pos, end)
        self._pos = end
        self._number += count
        return count

    def _read(self) -> PhysicalLine | None:
        text = self._text
        start = self._pos
        if start >= len(text):
            return None
        end = text.find("\n", start)
        if end < 0:
            end = len(text)
        self._pos = end + 1
        self._number += 1
        control = None
        match = self._control
        while match is not None and match.start() < start:
            match = next(self._controls, None)
        if match is not None and match.start() < end:
            control = (match.start() - start + 1, match.group())
            while match is not None and match.start() < end:
                match = next(self._controls, None)
        self._control = match
        return PhysicalLine(self._number, text[start:end], control)

    def peek(self) -> PhysicalLine | None:
        if self._peeked is None:
            self._peeked = self._read()
        return self._peeked

    def next(self) -> PhysicalLine | None:
        line = self.peek()
        self._peeked = None
        return line

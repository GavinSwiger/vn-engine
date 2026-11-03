"""F42 SEC-F42-10: the leak scan of a real build (AC-F42-12, AC-F42-40's Build row).

A plain byte search of the build folder misses what PyInstaller compresses, so this scan
opens every archive it meets, at any depth, and decompresses every member:

- the exe's appended package (PyInstaller's CArchive, found by its ``MEI\\014\\013\\012\\013\\016``
  cookie): each entry inflated; the embedded PYZ opened in turn;
- the PYZ: each module inflated and unmarshalled;
- ``base_library.zip`` and any other zip (the output zip too): each member inflated; a
  ``.pyc`` member unmarshalled past its 16-byte header.

Every unmarshalled code object is walked (nested ``co_consts`` too) and each ``co_filename``
collected and checked. Every byte string (raw files, inflated members) is searched,
case-insensitively, for each needle in UTF-8 and UTF-16LE, in SEC-F01-10 (b)'s forms: as
written, with ``/`` separators, and with doubled ``\\\\`` separators.

The formats are read here with the standard library only (``struct``, ``zlib``,
``marshal``, ``zipfile``), not with PyInstaller's own readers, so a reader bug in the
packer can't hide a leak from its own scan.
"""

import io
import marshal
import os
import struct
import types
import zipfile
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

COOKIE_MAGIC = b"MEI\014\013\012\013\016"
COOKIE_FORMAT = "!8sIIII64s"
COOKIE_SIZE = struct.calcsize(COOKIE_FORMAT)
TOC_ENTRY_FORMAT = "!IIIIBc"
TOC_ENTRY_SIZE = struct.calcsize(TOC_ENTRY_FORMAT)
PYZ_MAGIC = b"PYZ\0"
PYC_HEADER = 16
MAX_DEPTH = 4
SHORTEST_NAME = 4        # a shorter user name would match random bytes; its paths still count


@dataclass
class ScanResult:
    hits: list[tuple[str, str]] = field(default_factory=list)     # (where, needle)
    co_filenames: set[str] = field(default_factory=set)
    blobs: int = 0             # byte strings searched
    archives: dict[str, int] = field(default_factory=dict)        # kind -> how many opened
    code_objects: int = 0
    members: set[str] = field(default_factory=set)               # CArchive and PYZ names


def needle_forms(paths: Iterable[str | os.PathLike], words: Iterable[str] = ()) -> list[str]:
    """Each path as written, with ``/``, with ``\\\\``; each word as is. Lowercase, unique."""
    found: set[str] = set()
    for path in paths:
        text = os.fspath(path).rstrip("\\/")
        if not text:
            continue
        for form in (text, text.replace("\\", "/"), text.replace("\\", "\\\\")):
            found.add(form.casefold())
    for word in words:
        if len(word) >= SHORTEST_NAME:
            found.add(word.casefold())
    return sorted(found)


class LeakScanner:
    def __init__(self, needles: Iterable[str]) -> None:
        self.needles = list(needles)
        self._encoded = [(needle, needle.encode("utf-8"), needle.encode("utf-16-le"))
                         for needle in self.needles]
        self.result = ScanResult()

    # Byte search ---------------------------------------------------------------------
    def _search(self, where: str, data: bytes) -> None:
        self.result.blobs += 1
        low = data.lower()           # ASCII letters only: enough for paths and names
        for needle, utf8, utf16 in self._encoded:
            if utf8 in low or utf16 in low:
                self.result.hits.append((where, needle))

    # Code objects -------------------------------------------------------------------
    def _code(self, where: str, code: object) -> None:
        stack = [code]
        while stack:
            item = stack.pop()
            if not isinstance(item, types.CodeType):
                continue
            self.result.code_objects += 1
            name = item.co_filename
            self.result.co_filenames.add(name)
            low = name.casefold()
            for needle in self.needles:
                if needle in low:
                    self.result.hits.append((f"{where} co_filename {name!r}", needle))
            stack.extend(const for const in item.co_consts if isinstance(const, types.CodeType))

    def _unmarshal(self, where: str, data: bytes) -> None:
        try:
            value = marshal.loads(data)
        except (ValueError, EOFError, TypeError):
            return
        self._code(where, value)

    def _opened(self, kind: str) -> None:
        self.result.archives[kind] = self.result.archives.get(kind, 0) + 1

    # Archives -----------------------------------------------------------------------
    def blob(self, where: str, data: bytes, depth: int = 0) -> None:
        """Search ``data``, then open it if it is an archive this scan knows."""
        self._search(where, data)
        if depth >= MAX_DEPTH:
            return
        name = where.rsplit("/", 1)[-1].casefold()
        if name.endswith(".pyc") and len(data) > PYC_HEADER:
            self._unmarshal(where, data[PYC_HEADER:])
        if data[:4] == b"PK\x03\x04":
            self._zip(where, data, depth)
        elif data[:2] == b"MZ" and COOKIE_MAGIC in data[-(1 << 16):]:
            self._carchive(where, data, depth)
        elif data[:4] == PYZ_MAGIC:
            self._pyz(where, data, depth)

    def _zip(self, where: str, data: bytes, depth: int) -> None:
        self._opened("zip")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if not info.is_dir():
                    self.blob(f"{where}!{info.filename}", archive.read(info), depth + 1)

    def _carchive(self, where: str, data: bytes, depth: int) -> None:
        self._opened("carchive")
        cookie = data.rfind(COOKIE_MAGIC)
        _, length, toc_offset, toc_length, _, _ = struct.unpack(
            COOKIE_FORMAT, data[cookie:cookie + COOKIE_SIZE])
        start = cookie + COOKIE_SIZE - length
        toc = data[start + toc_offset:start + toc_offset + toc_length]
        pos = 0
        while pos < len(toc):
            entry_len, offset, size, _, compressed, typecode = struct.unpack(
                TOC_ENTRY_FORMAT, toc[pos:pos + TOC_ENTRY_SIZE])
            name = toc[pos + TOC_ENTRY_SIZE:pos + entry_len].rstrip(b"\0").decode("utf-8")
            pos += entry_len
            self.result.members.add(name)
            self._search(f"{where}!toc:{name}", name.encode("utf-8"))
            raw = data[start + offset:start + offset + size]
            body = zlib.decompress(raw) if compressed else raw
            inner = f"{where}!{name}"
            if typecode in (b"s", b"m", b"M"):
                self._unmarshal(inner, body)
            self.blob(inner, body, depth + 1)

    def _pyz(self, where: str, data: bytes, depth: int) -> None:
        self._opened("pyz")
        (toc_offset,) = struct.unpack("!i", data[8:12])
        toc = dict(marshal.loads(data[toc_offset:]))
        for name, (typecode, offset, length) in toc.items():
            inner = f"{where}!{name}"
            self.result.members.add(name)
            self._search(f"{where}!toc:{name}", name.encode("utf-8"))
            if length == 0:
                continue
            body = zlib.decompress(data[offset:offset + length])
            self._search(inner, body)
            if typecode in (0, 1):                     # module, package
                self._unmarshal(inner, body)

    # Entry points -------------------------------------------------------------------
    def folder(self, root: Path) -> ScanResult:
        """Every regular file under ``root`` (links not followed), archives opened."""
        root = Path(root)
        for top, dirs, files in os.walk(root, followlinks=False):
            dirs.sort()
            for name in sorted(files):
                path = Path(top) / name
                rel = path.relative_to(root).as_posix()
                self._search(f"name:{rel}", rel.encode("utf-8"))
                self.blob(rel, path.read_bytes())
        return self.result

    def file(self, path: Path) -> ScanResult:
        self.blob(Path(path).name, Path(path).read_bytes())
        return self.result


__all__ = ["LeakScanner", "ScanResult", "needle_forms"]

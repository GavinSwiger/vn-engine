"""The build's ``licenses/`` folder (F42 ``04-technical.md`` §3.1, PR-F42-14, D4, architect
decision 7).

Why this module exists: a built game ships Python, pygame-ce, the libraries pygame-ce's wheel
bundles as DLLs, PyInstaller's bootloader and the Noto fonts, and each of their licenses asks
for its notice to travel with the program. The wheel ships no notices for its DLLs, so they
are checked in here, one file per library, keyed by DLL name (``DLL_NOTICES``).

``collect_notices(dll_dirs=None)`` returns a ``Notices``: the files for ``licenses/`` as
``Notice(name, data)`` (UTF-8, CRLF) and ``unknown_dlls``, any DLL that has no notice (the
build must not ship it silently; a pygame-ce bump that adds a DLL fails ``DLL_NOTICES``'s
test until a notice is added). ``dll_dirs`` are the folders whose DLLs ship: PyInstaller 6
puts pygame-ce's DLLs both in ``_internal/pygame`` and (as dependencies) in ``_internal``
beside Python's own, so P5 passes both. The default is the installed pygame-ce folder, found
with ``importlib.util.find_spec`` (pygame is not imported). Python's own DLLs
(``python312.dll``, the VC runtime, OpenSSL, libffi, SQLite) map to ``Python.txt``: Python's
``LICENSE.txt`` holds their notices.

One file per package:
- ``vn-engine.txt``: the engine's own notice, for players: the engine's copyright, that the
  game uses it under the vn-engine Game Terms (``GAME-TERMS.txt`` at the repository root)
  and that it may not be taken out of the game.
- ``Python.txt``: a short header, then Python's ``LICENSE.txt`` from ``sys.base_prefix``
  (Windows layout) or the standard library folder (POSIX).
- ``pygame-ce.txt``: a header (where it ships, the source, that players may replace it with
  their own build, LGPL 2.1 §6), then the wheel's ``LGPL.txt``. The whole package ships as
  loose files in ``_internal/pygame`` (``spec.PYGAME_COLLECTION``), so it is replaceable.
- ``PyInstaller.txt``: a header, then PyInstaller's ``COPYING.txt`` from its installed
  distribution (read with ``importlib.metadata``; PyInstaller is never imported).
- ``OFL.txt``: ``engine/data/fonts/OFL.txt`` (the Noto fonts).
- one file per bundled library: ``SDL2.txt``, ``FreeType.txt``, ``libpng.txt`` and so on.

When an installed full text can't be found, the header alone ships: it names the license and
links its full text.

Child-only; imports ``core`` and the standard library.
"""

import importlib.metadata
import importlib.util
import os
import sys
import sysconfig
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from engine.core.paths import engine_data_dir

NOTICES_DIR: Final = Path(__file__).resolve().parent / "notices"
ENGINE_NOTICE: Final = "vn-engine.txt"
MAX_TEXT_BYTES: Final = 1 << 20

# DLL file name (casefold) → notice file in notices/. One notice per library package.
DLL_NOTICES: Final = {
    "sdl2.dll": "SDL2.txt",
    "sdl2_image.dll": "SDL2_image.txt",
    "sdl2_mixer.dll": "SDL2_mixer.txt",
    "sdl2_ttf.dll": "SDL2_ttf.txt",
    "freetype.dll": "FreeType.txt",
    "libjpeg-62.dll": "libjpeg-turbo.txt",
    "libogg-0.dll": "libogg.txt",
    "libopus-0.dll": "libopus.txt",
    "libopusfile-0.dll": "libopusfile.txt",
    "libpng16-16.dll": "libpng.txt",
    "libtiff-5.dll": "libtiff.txt",
    "libwavpack-1.dll": "wavpack.txt",
    "libwebp-7.dll": "libwebp.txt",
    "libwebpdemux-2.dll": "libwebp.txt",
    "libxmp.dll": "libxmp.txt",
    "portmidi.dll": "portmidi.txt",
    # Python's own (its LICENSE.txt covers them):
    "python3.dll": "Python.txt",
    "python312.dll": "Python.txt",
    "vcruntime140.dll": "Python.txt",
    "vcruntime140_1.dll": "Python.txt",
    "libcrypto-3.dll": "Python.txt",
    "libssl-3.dll": "Python.txt",
    "libffi-8.dll": "Python.txt",
    "sqlite3.dll": "Python.txt",
}


@dataclass(frozen=True, slots=True)
class Notice:
    name: str            # file name inside licenses/
    data: bytes          # UTF-8, CRLF


@dataclass(frozen=True, slots=True)
class Notices:
    files: tuple[Notice, ...]
    unknown_dlls: tuple[str, ...] = ()


def collect_notices(dll_dirs: Iterable[Path] | None = None) -> Notices:
    """Every notice for ``licenses/``, sorted by name; see the module docstring."""
    pygame_dir = installed_pygame_dir()
    folders = [Path(f) for f in dll_dirs] if dll_dirs is not None else [pygame_dir]
    lgpl = pygame_dir / "docs" / "generated" / "LGPL.txt" if pygame_dir else None
    texts: dict[str, str] = {
        ENGINE_NOTICE: _notice(ENGINE_NOTICE),
        "Python.txt": _joined(_notice("Python.txt"), _read_text(python_license())),
        "pygame-ce.txt": _joined(_notice("pygame-ce.txt"), _read_text(lgpl)),
        "PyInstaller.txt": _joined(_notice("PyInstaller.txt"), _pyinstaller_copying()),
        "OFL.txt": _read_text(engine_data_dir() / "fonts" / "OFL.txt") or "",
    }
    unknown: list[str] = []
    for dll in sorted({dll for folder in folders for dll in bundled_dlls(folder)}):
        name = DLL_NOTICES.get(dll.casefold())
        if name is None:
            unknown.append(dll)
        elif name not in texts:
            texts[name] = _notice(name)
    files = tuple(Notice(name, _crlf(text).encode("utf-8"))
                  for name, text in sorted(texts.items(), key=lambda item: item[0].casefold())
                  if text)
    return Notices(files, tuple(sorted(unknown)))


def unknown_dlls(dll_dirs: Iterable[Path]) -> tuple[str, ...]:
    """The DLLs directly in ``dll_dirs`` with no notice in ``DLL_NOTICES``, sorted. Reads
    names only, so a build from Studio's app (no installed Python) checks its copy too."""
    found = {dll for folder in dll_dirs for dll in bundled_dlls(Path(folder))}
    return tuple(sorted(dll for dll in found if dll.casefold() not in DLL_NOTICES))


def write_notices(folder: Path, notices: Notices) -> None:
    """Create ``folder`` (it must not exist) and write every notice by exclusive create."""
    folder = Path(folder)
    os.mkdir(folder)
    for notice in notices.files:
        with open(folder / notice.name, "xb") as stream:
            stream.write(notice.data)


def installed_pygame_dir() -> Path | None:
    """The installed pygame-ce package folder, without importing pygame."""
    try:
        spec = importlib.util.find_spec("pygame")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(list(spec.submodule_search_locations)[0])


def bundled_dlls(folder: Path | None) -> list[str]:
    """The ``.dll`` file names directly in ``folder``."""
    if folder is None:
        return []
    try:
        with os.scandir(folder) as entries:
            return sorted(entry.name for entry in entries
                          if entry.name.casefold().endswith(".dll")
                          and entry.is_file(follow_symlinks=False))
    except OSError:
        return []


def python_license() -> Path:
    """Python's ``LICENSE.txt``: beside the interpreter on Windows, in the standard library
    folder on POSIX."""
    beside = Path(sys.base_prefix) / "LICENSE.txt"
    if beside.is_file():
        return beside
    return Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt"


def _pyinstaller_copying() -> str | None:
    try:
        dist = importlib.metadata.distribution("pyinstaller")
    except importlib.metadata.PackageNotFoundError:
        return None
    for file in dist.files or ():
        if file.name.casefold() == "copying.txt" and ".dist-info" in str(file.parent):
            try:
                path = Path(str(file.locate()))
            except (OSError, ValueError, NotImplementedError):
                continue
            return _read_text(path)
    return None


def _notice(name: str) -> str:
    return (NOTICES_DIR / name).read_text(encoding="utf-8")


def _read_text(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        with open(path, "rb") as stream:
            data = stream.read(MAX_TEXT_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_TEXT_BYTES:
        return None
    return data.decode("utf-8", errors="replace")


def _joined(header: str, body: str | None) -> str:
    if not body:
        return header
    return header.rstrip("\n") + "\n\n" + "-" * 72 + "\n\n" + body


def _crlf(text: str) -> str:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "\r\n")


__all__ = ["DLL_NOTICES", "ENGINE_NOTICE", "NOTICES_DIR", "Notice", "Notices",
           "bundled_dlls", "collect_notices", "installed_pygame_dir", "python_license",
           "unknown_dlls", "write_notices"]

"""The game's icon and version resource on a copy of the player exe, without PyInstaller (F66;
F42 PR-F42-08, -20).

Why this module exists: builds copy one prebuilt player (``runtime``) instead of running
PyInstaller, so the per-game parts PyInstaller used to write, the exe's icon and its version
resource, are written here with the Windows resource API through ``ctypes``
(``BeginUpdateResourceW`` / ``UpdateResourceW`` / ``EndUpdateResourceW``). That works in
Studio's frozen app with no Python or build tool installed.

- ``version_info(...)``: the ``VS_VERSIONINFO`` bytes (PR-F42-20): Product name and File
  description = title, Product version = the version text, File version = ``1.2.0.0``,
  Internal name and Original filename from the exe name; US English, Unicode (``040904B0``).
- ``group_icon(ico)``: an ``.ico`` (``icon.make_ico``) split into ``RT_ICON`` images and the
  ``RT_GROUP_ICON`` directory that names them by ID.
- ``set_resources(exe, ico, version)``: PyInstaller's bootloader reads its archive (the PKG)
  from data appended after the PE image (the *overlay*), which the resource API doesn't
  keep. So the overlay is cut off first (it must end in PyInstaller's cookie), every
  existing ``RT_ICON``, ``RT_GROUP_ICON`` and ``RT_VERSION`` entry is deleted and the new
  ones added (the manifest and anything else stay), the overlay is appended again, and the
  PE checksum is recomputed (``MapFileAndCheckSumW``) as PyInstaller does. Any failure
  raises ``ResourceError``.

Windows only (``set_resources``); the byte builders are plain Python. Child-only; imports the
standard library and ``tools.build.spec``.
"""

import os
import struct
import time
from pathlib import Path
from typing import Final

from engine.tools.build.spec import version_numbers

RT_ICON: Final = 3
RT_GROUP_ICON: Final = 14
RT_VERSION: Final = 16
LANG_NEUTRAL: Final = 0
LANG_EN_US: Final = 0x0409
CODEPAGE_UNICODE: Final = 1200
STRING_TABLE: Final = "040904B0"
GROUP_ID: Final = 1
VERSION_ID: Final = 1
# PyInstaller's CArchive cookie magic: the overlay must end with a cookie that starts with it.
PKG_MAGIC: Final = b"MEI\014\013\012\013\016"
COOKIE_SEARCH: Final = 4096
RETRIES: Final = 20                    # antivirus may hold a fresh exe open for a moment
RETRY_WAIT_S: Final = 0.25
_LOAD_AS_DATAFILE: Final = 0x00000002 | 0x00000020   # DATAFILE | IMAGE_RESOURCE


class ResourceError(Exception):
    """The exe's resources couldn't be written; the message is for **Show details**."""


# --- Bytes ------------------------------------------------------------------------------------

def _node(key: str, value: bytes = b"", *, text: bool, value_length: int,
          children: tuple[bytes, ...] = ()) -> bytes:
    """One version-resource node: ``wLength``, ``wValueLength``, ``wType``, the key (UTF-16,
    NUL), padding to 32 bits, the value, then each child padded to 32 bits. ``wLength``
    leaves out padding after the node itself."""
    body = (key + "\0").encode("utf-16-le")
    body += b"\0" * (-(6 + len(body)) % 4) + value
    for child in children:
        body += b"\0" * (-(6 + len(body)) % 4) + child
    return struct.pack("<HHH", 6 + len(body), value_length, 1 if text else 0) + body


def _string(key: str, value: str) -> bytes:
    data = (value + "\0").encode("utf-16-le")
    return _node(key, data, text=True, value_length=len(data) // 2)


def version_info(*, title: str, version: str, file_version: str, exe_name: str) -> bytes:
    """The ``VS_VERSIONINFO`` resource; ``file_version`` is ``names.file_version``'s text
    (``ValueError`` when it isn't four numbers of at most 65535)."""
    numbers = version_numbers(file_version)
    ms, ls = (numbers[0] << 16) | numbers[1], (numbers[2] << 16) | numbers[3]
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x00010000, ms, ls, ms, ls, 0x3F, 0, 0x40004,
                        1, 0, 0, 0)
    strings = [("FileDescription", title), ("FileVersion", file_version),
               ("InternalName", exe_name.removesuffix(".exe")),
               ("OriginalFilename", exe_name), ("ProductName", title),
               ("ProductVersion", version)]
    table = _node(STRING_TABLE, text=True, value_length=0,
                  children=tuple(_string(key, value) for key, value in strings))
    string_info = _node("StringFileInfo", text=True, value_length=0, children=(table,))
    translation = _node("Translation", struct.pack("<HH", LANG_EN_US, CODEPAGE_UNICODE),
                        text=False, value_length=4)
    var_info = _node("VarFileInfo", text=True, value_length=0, children=(translation,))
    return _node("VS_VERSION_INFO", fixed, text=False, value_length=len(fixed),
                 children=(string_info, var_info))


def group_icon(ico: bytes, first_id: int = 1) -> tuple[bytes, list[tuple[int, bytes]]]:
    """``(RT_GROUP_ICON data, [(RT_ICON id, image bytes)])`` for an ``.ico`` file.
    Raises ``ResourceError`` for a malformed one."""
    try:
        reserved, kind, count = struct.unpack_from("<HHH", ico, 0)
        if reserved != 0 or kind != 1 or not 1 <= count <= 64:
            raise ValueError("not an icon file")
        group = struct.pack("<HHH", 0, 1, count)
        images = []
        for index in range(count):
            entry = ico[6 + 16 * index: 6 + 16 * (index + 1)]
            size, offset = struct.unpack_from("<II", entry, 8)
            data = ico[offset: offset + size]
            if len(entry) != 16 or len(data) != size or size == 0:
                raise ValueError("an image is cut short")
            group += entry[:12] + struct.pack("<H", first_id + index)
            images.append((first_id + index, data))
    except (struct.error, ValueError) as error:
        raise ResourceError(f"The icon couldn't be read: {error}.") from None
    return group, images


def overlay_start(image: bytes) -> int:
    """Where the PE image's sections end (the overlay starts there). Raises
    ``ResourceError`` when ``image`` isn't a PE file."""
    try:
        if image[:2] != b"MZ":
            raise ValueError
        pe = struct.unpack_from("<I", image, 0x3C)[0]
        if image[pe:pe + 4] != b"PE\0\0":
            raise ValueError
        sections, optional = struct.unpack_from("<H12xH", image, pe + 6)
        table = pe + 24 + optional
        end = 0
        for index in range(sections):
            raw_size, raw_pointer = struct.unpack_from("<II", image, table + 40 * index + 16)
            if raw_size:
                end = max(end, raw_pointer + raw_size)
    except (struct.error, ValueError):
        raise ResourceError("The player exe isn't a Windows program.") from None
    if not 0 < end <= len(image):
        raise ResourceError("The player exe isn't a Windows program.")
    return end


def _checksum_offset(image: bytes) -> int:
    pe = struct.unpack_from("<I", image, 0x3C)[0]
    return pe + 24 + 64                      # OptionalHeader.CheckSum (PE32 and PE32+)


# --- Windows ----------------------------------------------------------------------------------

def _api():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    imagehlp = ctypes.WinDLL("imagehlp", use_last_error=True)
    kernel32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    kernel32.LoadLibraryExW.restype = wintypes.HMODULE
    kernel32.FreeLibrary.argtypes = [wintypes.HMODULE]
    kernel32.FreeLibrary.restype = wintypes.BOOL
    names_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p,
                                    ctypes.c_void_p, ctypes.c_void_p)
    langs_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p,
                                    ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p)
    kernel32.EnumResourceNamesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, names_proc,
                                            ctypes.c_void_p]
    kernel32.EnumResourceNamesW.restype = wintypes.BOOL
    kernel32.EnumResourceLanguagesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p,
                                                ctypes.c_void_p, langs_proc, ctypes.c_void_p]
    kernel32.EnumResourceLanguagesW.restype = wintypes.BOOL
    kernel32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    kernel32.BeginUpdateResourceW.restype = wintypes.HANDLE
    kernel32.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                         wintypes.WORD, ctypes.c_void_p, wintypes.DWORD]
    kernel32.UpdateResourceW.restype = wintypes.BOOL
    kernel32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    kernel32.EndUpdateResourceW.restype = wintypes.BOOL
    imagehlp.MapFileAndCheckSumW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD),
                                             ctypes.POINTER(wintypes.DWORD)]
    imagehlp.MapFileAndCheckSumW.restype = wintypes.DWORD
    return ctypes, wintypes, kernel32, imagehlp, names_proc, langs_proc


def _fail(ctypes, what: str) -> ResourceError:
    code = ctypes.get_last_error()
    return ResourceError(f"Windows couldn't {what} (error {code}: "
                         f"{ctypes.FormatError(code).strip()}).")


def list_resources(exe: Path, types: tuple[int, ...]) -> list[tuple[int, int | str, int]]:
    """``(type, name, language)`` of each resource of ``types`` in ``exe`` (Windows)."""
    ctypes, _, kernel32, _, names_proc, langs_proc = _api()
    module = kernel32.LoadLibraryExW(str(exe), None, _LOAD_AS_DATAFILE)
    if not module:
        raise _fail(ctypes, "read the player exe")
    found: list[tuple[int, int | str, int]] = []
    try:
        for kind in types:
            names: list[int | str] = []

            def on_name(_module, _type, name, _param, names=names):
                names.append(name if name is not None and name <= 0xFFFF
                             else ctypes.wstring_at(name))
                return True

            name_callback = names_proc(on_name)
            kernel32.EnumResourceNamesW(module, kind, name_callback, None)   # none: FALSE
            for name in names:
                def on_lang(_module, _type, _name, lang, _param, name=name, kind=kind):
                    found.append((kind, name, lang))
                    return True

                lang_callback = langs_proc(on_lang)
                kernel32.EnumResourceLanguagesW(module, kind, name, lang_callback, None)
    finally:
        kernel32.FreeLibrary(module)
    return found


def _retry(action):
    for attempt in range(RETRIES):
        try:
            return action()
        except (ResourceError, PermissionError):
            if attempt == RETRIES - 1:
                raise
            time.sleep(RETRY_WAIT_S)
    return None


def _update(exe: Path, deletes, adds) -> None:
    ctypes, _, kernel32, *_ = _api()
    handle = kernel32.BeginUpdateResourceW(str(exe), False)
    if not handle:
        raise _fail(ctypes, "open the player exe for its icon")
    try:
        for kind, name, lang in deletes:
            if not kernel32.UpdateResourceW(handle, kind, name, lang, None, 0):
                raise _fail(ctypes, "remove the player's own icon")
        for kind, name, lang, data in adds:
            buffer = ctypes.create_string_buffer(data, len(data))
            if not kernel32.UpdateResourceW(handle, kind, name, lang, buffer, len(data)):
                raise _fail(ctypes, "add the game's icon")
    except BaseException:
        kernel32.EndUpdateResourceW(handle, True)          # discard
        raise
    if not kernel32.EndUpdateResourceW(handle, False):
        raise _fail(ctypes, "write the game's icon")


def _fix_checksum(exe: Path) -> None:
    ctypes, wintypes, _, imagehlp, *_ = _api()
    header, checksum = wintypes.DWORD(), wintypes.DWORD()
    if imagehlp.MapFileAndCheckSumW(str(exe), ctypes.byref(header), ctypes.byref(checksum)):
        raise ResourceError("Windows couldn't checksum the game's exe.")
    with open(exe, "r+b") as stream:
        head = stream.read(4096)
        stream.seek(_checksum_offset(head))
        stream.write(struct.pack("<I", checksum.value))


def set_resources(exe: Path, ico: bytes, version: bytes) -> None:
    """Replace ``exe``'s icon with ``ico`` and its version resource with ``version`` (a
    ``version_info`` result), keeping PyInstaller's appended archive. Windows only; raises
    ``ResourceError``."""
    exe = Path(exe)
    group, images = group_icon(ico)
    try:
        data = exe.read_bytes()
    except OSError as error:
        raise ResourceError(f"The player exe couldn't be read: {error.strerror}.") from None
    end = overlay_start(data)
    overlay = data[end:]
    if PKG_MAGIC not in overlay[-COOKIE_SEARCH:]:
        raise ResourceError("The player exe has no packed engine after it.")
    try:
        with open(exe, "r+b") as stream:
            stream.truncate(end)
    except OSError as error:
        raise ResourceError(f"The game's exe couldn't be changed: {error.strerror}.") from None
    deletes = _retry(lambda: list_resources(exe, (RT_GROUP_ICON, RT_ICON, RT_VERSION)))
    adds = [(RT_ICON, ident, LANG_NEUTRAL, image) for ident, image in images]
    adds.append((RT_GROUP_ICON, GROUP_ID, LANG_NEUTRAL, group))
    adds.append((RT_VERSION, VERSION_ID, LANG_EN_US, version))
    _retry(lambda: _update(exe, deletes, adds))
    with open(exe, "ab") as stream:
        stream.write(overlay)
    _fix_checksum(exe)
    if os.path.getsize(exe) < len(overlay):
        raise ResourceError("The game's exe came out too short.")


__all__ = ["RT_GROUP_ICON", "RT_ICON", "RT_VERSION", "ResourceError", "group_icon",
           "list_resources", "overlay_start", "set_resources", "version_info"]

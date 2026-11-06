"""F66: the game's icon and version resource written onto an exe without PyInstaller
(``winres``), on a copy of a small real exe with a PyInstaller-like appended archive."""

import ctypes
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from engine.tools.build import icon, winres

windows = pytest.mark.skipif(sys.platform != "win32", reason="the Windows resource API")
OVERLAY = b"PKG archive bytes " * 64 + winres.PKG_MAGIC + b"cookie tail"


def small_exe(tmp_path: Path) -> Path:
    """A copy of the base interpreter's ``python.exe`` (about 100 KB) without its signature,
    with ``OVERLAY`` appended as PyInstaller appends its archive."""
    source = Path(sys.base_prefix) / "python.exe"
    data = bytearray(source.read_bytes())
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    magic = struct.unpack_from("<H", data, pe + 24)[0]
    security = pe + 24 + (112 if magic == 0x20B else 96) + 4 * 8      # data directory 4
    offset, size = struct.unpack_from("<II", data, security)
    if size:
        del data[offset:]
        struct.pack_into("<II", data, security, 0, 0)
    exe = tmp_path / "My Game.exe"
    exe.write_bytes(bytes(data) + OVERLAY)
    return exe


def read_version(exe: Path) -> tuple[tuple[int, ...], dict[str, str]]:
    version = ctypes.WinDLL("version")
    size = version.GetFileVersionInfoSizeW(str(exe), None)
    data = ctypes.create_string_buffer(size)
    assert version.GetFileVersionInfoW(str(exe), 0, size, data)
    pointer, length = ctypes.c_void_p(), ctypes.c_uint()
    assert version.VerQueryValueW(data, "\\", ctypes.byref(pointer), ctypes.byref(length))
    fixed = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32 * 13)).contents
    numbers = (fixed[2] >> 16, fixed[2] & 0xFFFF, fixed[3] >> 16, fixed[3] & 0xFFFF)
    strings = {}
    for key in ("ProductName", "FileDescription", "ProductVersion", "FileVersion",
                "OriginalFilename", "InternalName"):
        if version.VerQueryValueW(data, "\\StringFileInfo\\040904B0\\" + key,
                                  ctypes.byref(pointer), ctypes.byref(length)):
            strings[key] = ctypes.wstring_at(pointer.value, length.value).rstrip("\0")
    return numbers, strings


def resource_bytes(exe: Path, kind: int, name: int) -> bytes:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LoadLibraryExW.restype = ctypes.c_void_p
    kernel32.FindResourceW.restype = ctypes.c_void_p
    kernel32.FindResourceW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    kernel32.LoadResource.restype = ctypes.c_void_p
    kernel32.LoadResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.LockResource.restype = ctypes.c_void_p
    kernel32.LockResource.argtypes = [ctypes.c_void_p]
    kernel32.SizeofResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
    module = kernel32.LoadLibraryExW(str(exe), None, 0x22)
    try:
        found = kernel32.FindResourceW(module, name, kind)
        size = kernel32.SizeofResource(module, found)
        return ctypes.string_at(kernel32.LockResource(kernel32.LoadResource(module, found)),
                                size)
    finally:
        kernel32.FreeLibrary(module)


@windows
def test_icon_and_version_on_a_copy_keep_the_appended_archive_and_the_exe_runs(tmp_path):
    exe = small_exe(tmp_path)
    before = winres.list_resources(exe, (winres.RT_ICON, winres.RT_GROUP_ICON,
                                         winres.RT_VERSION))
    assert any(kind == winres.RT_VERSION for kind, _, _ in before)     # python.exe's own
    ico = icon.make_ico(icon.icon_png(tmp_path, None))
    info = winres.version_info(title="Paper Lanterns", version="1.2-beta",
                               file_version="1.2.0.0", exe_name=exe.name)

    winres.set_resources(exe, ico, info)

    data = exe.read_bytes()
    assert data.endswith(OVERLAY)                                      # the archive is kept
    assert winres.overlay_start(data) == len(data) - len(OVERLAY)
    after = winres.list_resources(exe, (winres.RT_ICON, winres.RT_GROUP_ICON,
                                        winres.RT_VERSION))
    group, images = winres.group_icon(ico)
    assert sorted(after) == sorted([(winres.RT_ICON, ident, 0) for ident, _ in images]
                                   + [(winres.RT_GROUP_ICON, 1, 0),
                                      (winres.RT_VERSION, 1, winres.LANG_EN_US)])
    assert resource_bytes(exe, winres.RT_GROUP_ICON, 1) == group
    assert resource_bytes(exe, winres.RT_ICON, images[-1][0]) == images[-1][1]
    assert len(images) == len(icon.SIZES)
    assert read_version(exe) == ((1, 2, 0, 0), {
        "ProductName": "Paper Lanterns", "FileDescription": "Paper Lanterns",
        "ProductVersion": "1.2-beta", "FileVersion": "1.2.0.0",
        "OriginalFilename": "My Game.exe", "InternalName": "My Game"})
    header, checksum = ctypes.c_uint32(), ctypes.c_uint32()
    assert ctypes.WinDLL("imagehlp").MapFileAndCheckSumW(
        str(exe), ctypes.byref(header), ctypes.byref(checksum)) == 0
    assert header.value == checksum.value                              # checksum rewritten

    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    env["PYTHONHOME"] = sys.base_prefix
    env["PATH"] = sys.base_prefix + os.pathsep + env.get("PATH", "")   # python312.dll
    done = subprocess.run([str(exe), "-I", "-c", "print(6 * 7)"], env=env,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout.strip() == "42", done.stderr


@windows
def test_an_exe_without_the_archive_or_not_an_exe_is_refused(tmp_path):
    exe = small_exe(tmp_path)
    exe.write_bytes(exe.read_bytes()[:-len(OVERLAY)])
    ico = icon.make_ico(icon.icon_png(tmp_path, None))
    info = winres.version_info(title="x", version="1", file_version="1.0.0.0",
                               exe_name="x.exe")
    with pytest.raises(winres.ResourceError, match="packed engine"):
        winres.set_resources(exe, ico, info)
    other = tmp_path / "notes.exe"
    other.write_bytes(b"not a program")
    with pytest.raises(winres.ResourceError, match="Windows program"):
        winres.set_resources(other, ico, info)


def test_version_info_layout_and_bad_icons():
    info = winres.version_info(title="Ünïcode ✓", version="2.0", file_version="2.0.0.0",
                               exe_name="Ünïcode ✓.exe")
    length, value_length, kind = struct.unpack_from("<HHH", info, 0)
    assert length == len(info) and value_length == 52 and kind == 0
    assert info[6:6 + 32] == "VS_VERSION_INFO\0".encode("utf-16-le")
    assert struct.unpack_from("<I", info, 40)[0] == 0xFEEF04BD           # 32-bit aligned
    assert "Ünïcode ✓".encode("utf-16-le") in info
    with pytest.raises(ValueError):
        winres.version_info(title="x", version="1", file_version="70000.0.0.0",
                            exe_name="x.exe")
    for bad in (b"", b"\0\0\2\0\1\0", b"\0\0\1\0\1\0" + b"\0" * 16):
        with pytest.raises(winres.ResourceError):
            winres.group_icon(bad)

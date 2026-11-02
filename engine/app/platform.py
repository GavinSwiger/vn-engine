"""The read-only OS queries the engine may make (invariant 9 (c) allow-list).

Why this module exists: the window must open at a sensible size on high-DPI and small
screens (PR-F01-17, PR-F01-20), and the log header names the displays and the OS
(PR-F01-38). Those answers come from the OS, and every OS call is a privacy and supply-chain
surface, so they are all here and nowhere else: system DPI, the primary work area, each
display's resolution and scale, the OS name and version, and the free space under a write
root (F20 ``07`` I-6: ``free_bytes``, for the flowchart's free-space floor; never logged).
Nothing here asks for a host, user, or device name (SEC-F01-12).

On Windows the calls go through ``ctypes`` with ``user32`` and ``shcore`` loaded from
System32 only (``LOAD_LIBRARY_SEARCH_SYSTEM32``), never ``kernel32`` and never
``ctypes.windll`` (which uses the default DLL search order), and every foreign function
has ``argtypes`` and ``restype`` declared before it is called (SEC-F01-18). Any failure
gives a neutral default and at most one DEBUG line per function per session; startup
always proceeds.

The module name shadows the stdlib ``platform`` only for relative imports. All engine
imports are absolute, so ``import platform`` below reaches the stdlib module.
"""

import ctypes
import platform
import shutil
import sys
from collections.abc import Callable

from engine.core.logsetup import get_logger

LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800
SPI_GETWORKAREA = 0x0030
MDT_EFFECTIVE_DPI = 0
BASE_DPI = 96

_FAILURES = (OSError, AttributeError, ValueError)
_log = get_logger("app")
_noted: set[str] = set()


def system_display_scale() -> float:
    """Windows: ``GetDpiForSystem() / 96`` (1.0 at 100 %, 1.5 at 150 %). Elsewhere, and on
    any failure or a zero DPI, 1.0."""
    if sys.platform != "win32":
        return 1.0
    try:
        wintypes = _wintypes()
        get_dpi = _function(_load("user32"), "GetDpiForSystem", [], wintypes.UINT)
        dpi = int(get_dpi())
        if dpi <= 0:
            raise ValueError("GetDpiForSystem returned 0")
        return dpi / BASE_DPI
    except _FAILURES as exc:
        _note("system_display_scale", exc)
        return 1.0


def primary_work_area() -> tuple[int, int] | None:
    """Windows: the size of the primary display's work area (the screen minus the
    taskbar), from ``SystemParametersInfoW(SPI_GETWORKAREA)``. Elsewhere, and on any
    failure, None (the caller then estimates)."""
    if sys.platform != "win32":
        return None
    try:
        wintypes = _wintypes()
        query = _function(_load("user32"), "SystemParametersInfoW",
                          [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT],
                          wintypes.BOOL)
        rect = wintypes.RECT()
        if not query(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            raise ValueError("SystemParametersInfoW returned 0")
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width <= 0 or height <= 0:
            raise ValueError("empty work area")
        return width, height
    except _FAILURES as exc:
        _note("primary_work_area", exc)
        return None


def displays_info() -> list[str]:
    """One ``"<w>x<h> @ <pct>%"`` entry per display (``@ n/a`` when the scale is unknown),
    e.g. ``["2560x1440 @ 150%", "1920x1080 @ 100%"]``. Index, resolution, and scale only:
    no device or monitor names.

    Windows: ``EnumDisplayMonitors`` + ``GetMonitorInfoW`` (``rcMonitor``) and shcore's
    ``GetDpiForMonitor(MDT_EFFECTIVE_DPI)``. Elsewhere, or if user32 fails:
    ``pygame.display.get_desktop_sizes()`` with ``n/a``.
    """
    if sys.platform == "win32":
        try:
            entries = _windows_displays()
            if entries:
                return entries
            raise ValueError("no displays enumerated")
        except _FAILURES as exc:
            _note("displays_info", exc)
    return [f"{w}x{h} @ n/a" for w, h in _desktop_sizes()]


def os_description() -> str:
    """OS name and version for header line 1, e.g. ``Windows 11 10.0.26200``. No host or
    user names."""
    system = platform.system() or "unknown OS"
    if system == "Windows":
        return f"Windows {platform.release()} {platform.version()}"
    if system == "Darwin":
        return f"macOS {platform.mac_ver()[0]}".rstrip()
    return f"{system} {platform.release()}".rstrip()


def free_bytes(root: object) -> int | None:
    """F20 (``07`` I-6, SEC-F20-06): the free bytes on the volume of ``root``, a write root
    the engine owns (the saves folder), from ``shutil.disk_usage``; None on any failure.
    A write-root query, not an identity one; the caller never logs the value or the path."""
    try:
        return int(shutil.disk_usage(root).free)          # type: ignore[arg-type]
    except (OSError, TypeError, ValueError):
        return None


# --- internals -------------------------------------------------------------------------------

def _wintypes():
    from ctypes import wintypes
    return wintypes


def _load(name: str):
    """``user32`` or ``shcore``, from System32 only (SEC-F01-18)."""
    assert name in ("user32", "shcore"), name
    return ctypes.WinDLL(name, winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)


def _function(dll, name: str, argtypes: list, restype) -> Callable:
    """The foreign function ``name`` with its signature declared before any call."""
    function = getattr(dll, name)
    function.argtypes = argtypes
    function.restype = restype
    return function


def _windows_displays() -> list[str]:
    wintypes = _wintypes()

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32 = _load("user32")
    monitor_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    enum_monitors = _function(user32, "EnumDisplayMonitors",
                              [wintypes.HDC, ctypes.POINTER(wintypes.RECT), monitor_proc,
                               wintypes.LPARAM], wintypes.BOOL)
    monitor_info = _function(user32, "GetMonitorInfoW",
                             [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)], wintypes.BOOL)
    dpi_for_monitor = None
    try:
        dpi_for_monitor = _function(
            _load("shcore"), "GetDpiForMonitor",
            [wintypes.HMONITOR, ctypes.c_int, ctypes.POINTER(wintypes.UINT),
             ctypes.POINTER(wintypes.UINT)], ctypes.c_long)
    except _FAILURES as exc:
        _note("displays_info (shcore)", exc)

    entries: list[str] = []

    def on_monitor(hmonitor, _hdc, _rect, _data):
        try:
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if not monitor_info(hmonitor, ctypes.byref(info)):
                return True
            rect = info.rcMonitor
            size = f"{rect.right - rect.left}x{rect.bottom - rect.top}"
            scale = "n/a"
            if dpi_for_monitor is not None:
                dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
                result = dpi_for_monitor(hmonitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x),
                                         ctypes.byref(dpi_y))
                if result == 0 and dpi_x.value > 0:
                    scale = f"{round(dpi_x.value * 100 / BASE_DPI)}%"
            entries.append(f"{size} @ {scale}")
        except BaseException:          # never let an exception cross the C callback
            pass
        return True

    if not enum_monitors(None, None, monitor_proc(on_monitor), 0):
        raise ValueError("EnumDisplayMonitors returned 0")
    return entries


def _desktop_sizes() -> list[tuple[int, int]]:
    try:
        import pygame
        return [tuple(size) for size in pygame.display.get_desktop_sizes()]
    except Exception as exc:              # display not initialized, no pygame, …
        _note("desktop sizes", exc)
        return []


def _note(function: str, exc: BaseException) -> None:
    """At most one DEBUG line per function per session; only the exception type."""
    if function in _noted:
        return
    _noted.add(function)
    _log.debug("%s is not available (%s); using the neutral default", function,
               type(exc).__name__)

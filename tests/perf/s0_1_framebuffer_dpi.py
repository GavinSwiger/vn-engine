"""S0-1 (AC-F01-116): Windows framebuffer is pixel-sized.

Run once per Windows display scale (100% / 125% / 150%):
    .venv/Scripts/python tests/perf/s0_1_framebuffer_dpi.py
Pass: window.size == get_surface().get_size() == GetClientRect size == (1600, 900).
`--no-env` repeats without SDL_WINDOWS_DPI_AWARENESS (informational only).
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

USE_ENV = "--no-env" not in sys.argv
if USE_ENV:
    os.environ["SDL_WINDOWS_DPI_AWARENESS"] = "permonitorv2"  # before importing pygame

import pygame  # noqa: E402

import s0_common  # noqa: E402

TITLE = "vn-engine S0-1 framebuffer probe"
REQ = (1600, 900)


def main() -> int:
    s0_common.print_json("versions", s0_common.versions())
    s0_common.print_json("monitors", s0_common.windows_monitors())
    print(f"SDL_WINDOWS_DPI_AWARENESS={os.environ.get('SDL_WINDOWS_DPI_AWARENESS')!r}")
    pygame.init()
    win = pygame.Window(TITLE, size=REQ, allow_high_dpi=True)
    for _ in range(10):
        pygame.event.pump()
    fb = win.get_surface()
    fb.fill((32, 32, 32))
    win.flip()
    pygame.event.pump()

    user32 = ctypes.WinDLL("user32", winmode=s0_common.LOAD_LIBRARY_SEARCH_SYSTEM32)
    user32.FindWindowW.restype = wintypes.HWND
    hwnd = user32.FindWindowW(None, TITLE)
    rc = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    client = (rc.right - rc.left, rc.bottom - rc.top)
    user32.GetDpiForWindow.restype = wintypes.UINT
    win_dpi = user32.GetDpiForWindow(hwnd)
    user32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
    user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    ctx = user32.GetWindowDpiAwarenessContext(hwnd)
    awareness = user32.GetAwarenessFromDpiAwarenessContext(ctx)  # 0 unaware, 1 system, 2 per-monitor
    v2 = bool(user32.AreDpiAwarenessContextsEqual(ctypes.c_void_p(ctx), ctypes.c_void_p(-4)))

    sizes = {
        "requested": REQ,
        "window.size": tuple(win.size),
        "get_surface().get_size()": fb.get_size(),
        "GetClientRect": client,
        "GetDpiForWindow": win_dpi,
        "awareness (0 unaware/1 system/2 per-monitor)": awareness,
        "is PER_MONITOR_AWARE_V2": v2,
        "fb bitsize/masks": (fb.get_bitsize(), fb.get_masks()),
    }
    s0_common.print_json("S0-1", sizes)
    ok = tuple(win.size) == fb.get_size() == client == REQ
    print(f"S0-1 RESULT: {'PASS' if ok else 'FAIL'} at {round(win_dpi * 100 / 96)}% window DPI")
    win.destroy()
    pygame.quit()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""S0-5 (AC-F01-120): pygame.scrap with only a pygame.Window (no display.set_mode).

    .venv/Scripts/python tests/perf/s0_5_clipboard.py

NOTE: this overwrites the OS clipboard with the harmless text "vn-engine S0".
Steps: pygame.scrap.init(); pygame.scrap.put_text("vn-engine S0"); read the OS clipboard
(Windows: PowerShell Get-Clipboard; macOS: pbpaste). Records "works" or "fails" + error text.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import warnings

os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")

import pygame  # noqa: E402

import s0_common  # noqa: E402

TEXT = "vn-engine S0"


def read_os_clipboard() -> str:
    if sys.platform == "win32":
        cmd = ["powershell", "-NoProfile", "-Command", "Get-Clipboard"]
    elif sys.platform == "darwin":
        cmd = ["pbpaste"]
    else:
        cmd = ["xclip", "-o", "-selection", "clipboard"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.rstrip("\r\n")


def main() -> int:
    s0_common.print_json("versions", s0_common.versions())
    pygame.init()
    win = pygame.Window("vn-engine S0-5", size=(640, 360), allow_high_dpi=True)
    pygame.event.pump()
    win.get_surface().fill((32, 32, 32))
    win.flip()
    assert pygame.display.get_surface() is None, "set_mode must never have been called"

    steps: dict = {}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            pygame.scrap.init()
            steps["scrap.init()"] = "ok"
        except Exception as exc:  # noqa: BLE001
            steps["scrap.init()"] = f"raised {exc!r}"
        try:
            steps["scrap.get_init()"] = pygame.scrap.get_init()
        except Exception as exc:  # noqa: BLE001
            steps["scrap.get_init()"] = f"raised {exc!r}"
        try:
            pygame.scrap.put_text(TEXT)
            steps["scrap.put_text()"] = "ok"
        except Exception as exc:  # noqa: BLE001
            steps["scrap.put_text()"] = f"raised {exc!r}"
        try:
            steps["scrap.get_text()"] = pygame.scrap.get_text()
        except Exception as exc:  # noqa: BLE001
            steps["scrap.get_text()"] = f"raised {exc!r}"
        steps["warnings"] = [f"{w.category.__name__}: {w.message}" for w in caught]

    pygame.event.pump()
    time.sleep(0.2)
    os_text = read_os_clipboard()
    steps["OS clipboard (Get-Clipboard/pbpaste)"] = os_text
    works = os_text == TEXT
    s0_common.print_json("S0-5", steps)
    print(f"S0-5 RESULT: {'works' if works else 'fails'} "
          f"(OS clipboard now contains {os_text!r}; this script put {TEXT!r} on it)")
    win.destroy()
    pygame.quit()
    # Informational: does the text survive the window/pygame shutting down?
    print(f"after pygame.quit(): OS clipboard = {read_os_clipboard()!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

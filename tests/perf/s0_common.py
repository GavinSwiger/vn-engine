"""Spike S0 shared helpers (throwaway; see specs/F01-project-skeleton 04-technical §15).

Standalone: must not import from `engine/`. Imported by the other s0_*.py scripts, which
are run directly (`.venv/Scripts/python tests/perf/s0_xxx.py`), so this file is on sys.path.
"""

from __future__ import annotations

import ctypes
import json
import math
import platform
import subprocess
import sys
from ctypes import wintypes


def nearest_rank(xs: list[float], p: float) -> float:
    """ADR-0005 / 04-technical §7.5.3: sorted(xs)[ceil(p/100 * n) - 1]."""
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[max(0, math.ceil(p / 100.0 * len(s)) - 1)]


def summarize_ms(xs_s: list[float]) -> dict[str, float]:
    """Seconds in, ms (2 dp) out: p50/p95/p99/max."""
    ms = [x * 1000.0 for x in xs_s]
    return {
        "n": len(ms),
        "p50": round(nearest_rank(ms, 50), 2),
        "p95": round(nearest_rank(ms, 95), 2),
        "p99": round(nearest_rank(ms, 99), 2),
        "max": round(max(ms), 2) if ms else float("nan"),
    }


def versions() -> dict[str, str]:
    import pygame  # noqa: PLC0415  (imported late so callers can set SDL env vars first)

    return {
        "python": platform.python_version(),
        "python_build": sys.version.replace("\n", " "),
        "pygame_ce": pygame.version.ver,
        "sdl_linked": ".".join(map(str, pygame.get_sdl_version(linked=True))),
        "sdl_compiled": ".".join(map(str, pygame.get_sdl_version(linked=False))),
        "os": platform.platform(),
    }


# --- Windows display info (ctypes, user32/shcore from System32 only) ------------------------

LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class DEVMODEW(ctypes.Structure):
    # Only the fields we need are named; the rest is padding up to the documented size.
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", wintypes.LONG),
        ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("_rest", ctypes.c_byte * 64),
    ]


def windows_monitors() -> list[dict]:
    """Per monitor: rect, work area, effective DPI / scale %, refresh rate, primary flag."""
    if sys.platform != "win32":
        return []
    user32 = ctypes.WinDLL("user32", winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)
    shcore = ctypes.WinDLL("shcore", winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)
    out: list[dict] = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
    )

    def cb(hmon, _hdc, _rect, _lp):
        try:
            mi = MONITORINFOEXW()
            mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
            user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
            dx, dy = wintypes.UINT(), wintypes.UINT()
            shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy))  # MDT_EFFECTIVE_DPI
            dm = DEVMODEW()
            dm.dmSize = ctypes.sizeof(DEVMODEW)
            user32.EnumDisplaySettingsW(mi.szDevice, -1, ctypes.byref(dm))  # ENUM_CURRENT_SETTINGS
            r, w = mi.rcMonitor, mi.rcWork
            out.append(
                {
                    "device": mi.szDevice,
                    "primary": bool(mi.dwFlags & 1),
                    "rect": (r.left, r.top, r.right - r.left, r.bottom - r.top),
                    "work": (w.left, w.top, w.right - w.left, w.bottom - w.top),
                    "dpi": dx.value,
                    "scale_pct": round(dx.value * 100 / 96),
                    "hz": dm.dmDisplayFrequency,
                }
            )
        except Exception as exc:  # noqa: BLE001
            out.append({"error": repr(exc)})
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    return out


def cim_machine_info() -> dict:
    """CPU / GPU / RAM / power via PowerShell Get-CimInstance (Windows only)."""
    if sys.platform != "win32":
        return {}
    ps = (
        "$c=Get-CimInstance Win32_Processor|Select-Object -First 1 Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed;"
        "$g=@(Get-CimInstance Win32_VideoController|Select-Object Name,DriverVersion);"
        "$m=Get-CimInstance Win32_ComputerSystem|Select-Object Manufacturer,Model,TotalPhysicalMemory;"
        "$o=Get-CimInstance Win32_OperatingSystem|Select-Object Caption,Version,BuildNumber;"
        "$b=@(Get-CimInstance Win32_Battery|Select-Object BatteryStatus,EstimatedChargeRemaining);"
        "$p=(powercfg /getactivescheme) -join ' ';"
        "@{cpu=$c;gpus=$g;system=$m;os=$o;battery=$b;power_scheme=$p}|ConvertTo-Json -Depth 4 -Compress"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60
        )
        return json.loads(r.stdout)
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)}


def print_json(label: str, obj) -> None:
    print(f"{label}: {json.dumps(obj, ensure_ascii=False, default=str)}", flush=True)


if __name__ == "__main__":
    print_json("monitors", windows_monitors())
    print_json("machine", cim_machine_info())
    print_json("versions", versions())

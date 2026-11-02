"""One story load in a fresh process, for the ``perf`` rows (06-acceptance.md §0.5 "Load
time"; AC-F02-53, 69, 70). Stdlib and ``engine.script`` only.

    .venv/Scripts/python -m tests.script.load_process GAME_ROOT [--todos]

Imports first, then times ``load_story()`` alone (wall clock), and prints one JSON line:
``seconds``, ``peak_bytes`` (the process's peak working set: Windows
``PeakWorkingSetSize``, elsewhere ``ru_maxrss``), ``loaded``, ``error_codes`` (in order),
``error_count``, ``warning_codes``, ``todos``, ``todo_count``, ``words``, ``statements``.
``measure(root, runs)`` runs it ``runs + 1`` times and drops the first (06 §0.5: the median of
5 processes after 1 discarded run). ``cpu_name()`` names the CPU for the test report.
"""

import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def peak_memory_bytes() -> int:
    """The peak working set (resident set) of this process so far."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.K32GetProcessMemoryInfo.argtypes = (wintypes.HANDLE,
                                                     ctypes.POINTER(Counters), wintypes.DWORD)
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        if not kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(),
                                                ctypes.byref(counters), counters.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return int(counters.PeakWorkingSetSize)
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def cpu_name() -> str:
    if sys.platform == "win32":
        import winreg

        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def run_once(root: Path, *, todos: bool = False, timeout: float = 600) -> dict:
    """``load_story`` of ``root`` in a fresh process; the parsed JSON line."""
    args = [sys.executable, "-m", "tests.script.load_process", str(root)]
    if todos:
        args.append("--todos")
    done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=ROOT,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if done.returncode != 0:
        raise AssertionError(f"load process failed ({done.returncode}):\n{done.stderr}")
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    data = json.loads(lines[-1])
    data["stderr"] = done.stderr
    return data


def measure(root: Path, runs: int = 5) -> tuple[float, list[dict]]:
    """The median load time of ``runs`` fresh processes after one discarded run."""
    run_once(root)
    results = [run_once(root) for _ in range(runs)]
    return statistics.median(r["seconds"] for r in results), results


def main(argv: list[str]) -> int:
    from engine.core.paths import GamePaths
    from engine.script import LoadOptions, load_story

    root = Path(argv[0])
    options = LoadOptions(collect_todos="--todos" in argv[1:])
    paths = GamePaths(root.resolve())
    start = time.perf_counter()
    result = load_story(paths, options)
    seconds = time.perf_counter() - start
    stats = result.stats
    print(json.dumps({
        "seconds": seconds,
        "peak_bytes": peak_memory_bytes(),
        "loaded": result.program is not None,
        "error_codes": [e.code for e in result.errors],
        "error_count": result.error_count,
        "warning_codes": [w.code for w in result.warnings],
        "todos": len(result.todos),
        "todo_count": result.todo_count,
        "words": stats.words,
        "statements": stats.statements,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

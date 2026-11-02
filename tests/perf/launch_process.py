"""One launch phase in a fresh process, for AC-F03-79 (``perf``). Stdlib and ``engine`` only.

    .venv/Scripts/python -m tests.perf.launch_process GAME_ROOT

Imports, loads the story, and starts the watchdog first (not timed), then times the whole
launch phase as the game runs it (``engine/app/loading.py``): ``LaunchJob`` built with the
watchdog guard, ``game_has``, and the image source, stepped until done. Prints one JSON line:
``seconds``, ``defines``, ``errors``, ``warnings``. ``measure(root, runs)`` runs it
``runs + 1`` times and drops the first (the median of 5 processes, as F02's load time).
"""

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_once(root: Path, *, timeout: float = 120) -> dict:
    done = subprocess.run([sys.executable, "-m", "tests.perf.launch_process", str(root)],
                          capture_output=True, text=True, timeout=timeout, cwd=ROOT,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if done.returncode != 0:
        raise AssertionError(f"launch process failed ({done.returncode}):\n{done.stderr}")
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    return json.loads(lines[-1])


def measure(root: Path, runs: int = 5) -> tuple[float, list[dict]]:
    """The median launch time of ``runs`` fresh processes after one discarded run."""
    run_once(root)
    results = [run_once(root) for _ in range(runs)]
    return statistics.median(r["seconds"] for r in results), results


def main(argv: list[str]) -> int:
    from engine.app.loading import game_has, image_source
    from engine.app.story import Watchdog
    from engine.core.paths import GamePaths
    from engine.runtime.launch import LaunchJob
    from engine.script import load_story

    paths = GamePaths(Path(argv[0]).resolve())
    result = load_story(paths)
    if result.program is None:
        print(json.dumps({"error": [e.format() for e in result.errors]}))
        return 1
    program = result.program
    watchdog = Watchdog()
    watchdog.start()
    try:
        start = time.perf_counter()
        job = LaunchJob(program, guard=watchdog, dev=True, game_has=game_has(paths),
                        images=image_source(paths), game_root=paths.root)
        while not job.step():
            pass
        seconds = time.perf_counter() - start
    finally:
        watchdog.stop()
    launched = job.result
    print(json.dumps({
        "seconds": seconds,
        "defines": len(program.defines),
        "errors": [e.format() for e in launched.errors],
        "warnings": [w.format() for w in launched.warnings],
        "launched": launched.namespace is not None,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

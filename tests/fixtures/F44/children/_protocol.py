"""Shared by the fake preview children (F44 ``06-acceptance.md`` §4 ``children/``): write
report lines the way ``--report-to-editor`` does (``04`` §3). Standard library only; each
child runs as ``python <child>.py``, so this folder is on its ``sys.path``."""

import json
import sys
import time

MARKER = b"VN-EDITOR-REPORT "


def raw(data: bytes) -> None:
    """Write bytes to stdout and flush."""
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def report(obj: object) -> None:
    """One report line: the marker, ASCII JSON, a newline."""
    raw(MARKER + json.dumps(obj, ensure_ascii=True).encode("ascii") + b"\n")


def started() -> None:
    report({"v": 1, "event": "started"})


def error(phase: str, items: list[dict], head: str | None = None,
          tail: list[str] | None = None) -> None:
    report({"v": 1, "event": "error", "phase": phase, "head": head, "items": items,
            "tail": tail or []})


def wait(seconds: float = 60.0) -> None:
    """Stay alive (until killed, or ``seconds`` so a leaked child ends by itself)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(0.05)

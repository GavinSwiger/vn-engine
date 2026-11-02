"""Shared by the fake check children (F45 ``06-acceptance.md`` §5 ``children/``): write
check report lines the way ``python -m engine check --report-to-editor`` does (``04`` §4.3).
Standard library only; each child runs as ``python <child>.py``, so this folder is on its
``sys.path``."""

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


def problem(text: str, line: int = 1) -> dict:
    return {"severity": "error", "code": "E43", "source": "load", "text": text,
            "file": "script/main.vns", "line": line, "column": 5}


def problems(items: list[dict]) -> None:
    report({"v": 1, "event": "problems", "items": items})


def names(kind: str, items: list[list]) -> None:
    report({"v": 1, "event": "names", "kind": kind, "items": items})


def graph(links: list[list]) -> None:
    report({"v": 1, "event": "graph", "links": links})


def done(problem_count: int, loaded: bool = True) -> None:
    report({"v": 1, "event": "done", "loaded": loaded, "problems": problem_count,
            "seconds": 0.5})


def standard_run(pause: float = 0.0) -> None:
    """One problem, one label name, one link, (a pause), then ``done``."""
    problems([problem("first")])
    names("label", [["start", "script/main.vns", 1]])
    graph([["start", "end", "jump", "script/main.vns", 2]])
    if pause:
        time.sleep(pause)
    done(1)


def wait(seconds: float = 60.0) -> None:
    """Stay alive (until killed, or ``seconds`` so a leaked child ends by itself)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(0.05)

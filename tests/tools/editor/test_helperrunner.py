"""F47 P1-E: ``HelperRunner``'s protocol against a fake child (``04`` §7.3; pure, no
pygame). The real child is ``tests/tools/test_helper.py`` (AC-F47-21)."""

import base64
import io
import json
import os
import queue
import time

from engine.core.editorreport import HELPER_REPLY_TIMEOUT_S, REPORT_MARKER
from engine.tools.editor.helperrunner import (
    HELPER_STOPPED,
    HELPER_TOO_SLOW,
    THUMBS_IN_FLIGHT,
    HelperRunner,
    decode_helper_line,
)

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 8).decode("ascii")


class FakeStdin:
    """Collects what the runner writes; ``requests`` yields each JSON line (overlay bytes
    after a still are kept in ``overlays``)."""

    def __init__(self) -> None:
        self.buffer = b""
        self.lines: "queue.SimpleQueue[dict]" = queue.SimpleQueue()
        self.overlays: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        line, _, rest = data.partition(b"\n")
        request = json.loads(line)
        if rest:
            self.overlays.append(rest)
        self.lines.put(request)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class FakeProc:
    def __init__(self) -> None:
        read, write = os.pipe()
        self.stdout = io.open(read, "rb")
        self._out = io.open(write, "wb")
        self.stdin = FakeStdin()
        self.returncode = None

    def reply(self, **event) -> None:
        self._out.write(REPORT_MARKER + json.dumps({"v": 1, **event}).encode("ascii") + b"\n")
        self._out.flush()

    def die(self) -> None:
        self.returncode = 1
        self._out.close()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode

    def terminate(self) -> None:
        self.die() if self.returncode is None else None

    kill = terminate


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def until(runner, predicate, events, seconds=5.0):
    """Poll until ``predicate(events)`` holds (the reader threads are real)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        events.extend(runner.poll())
        if predicate(events):
            return events
        time.sleep(0.005)
    raise AssertionError(f"timed out; events so far: {events}")


def take(runner, proc: FakeProc, events: list) -> dict:
    """The next request ``proc`` gets, polling ``runner`` (into ``events``) meanwhile."""
    end = time.monotonic() + 5
    while time.monotonic() < end:
        try:
            return proc.stdin.lines.get(timeout=0.005)
        except queue.Empty:
            events.extend(runner.poll())
    raise AssertionError("no request came")


def test_runner_protocol_with_a_fake_child(tmp_path):
    procs: list[FakeProc] = []

    def popen(argv, **kwargs):
        assert argv[-2:] == ["helper", str(tmp_path)] and kwargs["stdin"] is not None
        procs.append(FakeProc())
        return procs[-1]

    clock = Clock()
    runner = HelperRunner(tmp_path, popen=popen, clock=clock)
    events: list = []

    # Newest wins per still kind: s2 waits behind s1, s3 replaces it; s1's reply is dropped.
    s1 = runner.still("textbox", 640, b'[game]\ntitle = "A"\n')
    s2 = runner.still("textbox", 640, None)
    s3 = runner.still("textbox", 320, b"")
    assert s1 < s2 < s3 and runner.busy
    until(runner, lambda e: procs, events)
    proc = procs[0]
    first = take(runner, proc, events)
    assert first == {"v": 1, "op": "still", "serial": s1, "kind": "textbox", "width": 640,
                     "overlay": True}
    assert proc.stdin.overlays[0].endswith(b'\n[game]\ntitle = "A"\n')
    proc.reply(event="png", serial=s1, op="still", width=640, height=360, data=PNG)
    assert take(runner, proc, events)["serial"] == s3                       # s2 was never sent
    proc.reply(event="png", serial=s3, op="still", width=320, height=180, data=PNG)
    until(runner, lambda e: e, events)
    assert [(e.serial, e.ok, e.width, e.kind) for e in events] == [(s3, True, 320, "textbox")]

    # Thumbnails: asked once per (ref, size, stamp), cached with failures, <= 8 in flight.
    events.clear()
    refs = [f"images/bg/{n}.jpg" for n in range(THUMBS_IN_FLIGHT + 1)]
    assert all(runner.thumb(ref, 96, stamp=(1, 1)) is None for ref in refs)
    assert runner.thumb(refs[0], 96, stamp=(1, 1)) is None   # asked, not asked again
    sent = [take(runner, proc, events) for _ in range(THUMBS_IN_FLIGHT)]
    assert proc.stdin.lines.empty()
    for request in sent[1:]:
        proc.reply(event="png", serial=request["serial"], op="thumb", width=96, height=54,
                   data=PNG)
    proc.reply(event="failed", serial=sent[0]["serial"], op="thumb", reason="damaged")
    last = take(runner, proc, events)                                        # the ninth, once one answered
    assert last["ref"] == refs[-1]
    proc.reply(event="png", serial=last["serial"], op="thumb", width=96, height=54, data=PNG)
    until(runner, lambda e: len(e) == len(refs), events)
    cached = runner.thumb(refs[1], 96, stamp=(1, 1))
    assert cached is not None and cached.ok and cached.ref == refs[1] and cached.data == PNG
    assert runner.thumb(refs[0], 96, stamp=(1, 1)).reason == "damaged"
    assert runner.thumb(refs[1], 96, stamp=(2, 1)) is None   # the file changed: asked again
    take(runner, proc, events)

    # A crash fails what is in flight; the next request starts a new child.
    events.clear()
    played = runner.play("audio/sound/chime.ogg")
    assert take(runner, proc, events)["op"] == "play"
    proc.die()
    until(runner, lambda e: any(x.op == "play" for x in e), events)
    lost = [e for e in events if e.op == "play"]
    assert [(e.serial, e.ok, e.reason) for e in lost] == [(played, False, HELPER_STOPPED)]
    assert not runner.alive and runner.stop_sound() is None  # nothing plays: nothing sent
    again = runner.play("audio/sound/chime.ogg")
    until(runner, lambda e: len(procs) == 2, events)
    second = procs[1]
    assert take(runner, second, events) == {"v": 1, "op": "play", "serial": again,
                            "ref": "audio/sound/chime.ogg"}
    second.reply(event="played", serial=again, seconds=0.8)
    events.clear()
    until(runner, lambda e: e, events)
    assert (events[0].op, events[0].ok, events[0].seconds) == ("play", True, 0.8)

    # No answer in time: killed, the request fails, and Studio keeps going.
    events.clear()
    slow = runner.still("title", 640, None)
    take(runner, second, events)
    clock.now += HELPER_REPLY_TIMEOUT_S
    until(runner, lambda e: e, events)
    assert [(e.serial, e.ok, e.reason) for e in events] == [(slow, False, HELPER_TOO_SLOW)]
    assert second.returncode is not None and not runner.alive
    runner.stop()


def test_reply_lines_are_checked():
    def line(**event):
        return REPORT_MARKER + json.dumps({"v": 1, **event}).encode("ascii")

    good = line(event="png", serial=3, op="thumb", width=96, height=54, data=PNG)
    assert decode_helper_line(good)[1]["data"] == PNG
    not_png = base64.b64encode(b"<svg/>").decode("ascii")
    for bad in (line(event="png", serial=3, op="thumb", width=96, height=54, data=not_png),
                line(event="png", serial=3, op="thumb", width=999, height=54, data=PNG),
                line(event="png", serial=3, op="still", width=96, height=54, data="%%"),
                line(event="played", serial=-1, seconds=1),
                line(event="played", serial=1, seconds=float("inf")),
                line(event="failed", serial=1, reason="x" * 10_001),
                line(event="boom", serial=1),
                b"VN-EDITOR-REPORT not json"):
        assert decode_helper_line(bad) is None, bad

"""F40 P3: Studio's side of the console channel (``04`` §7.5, ``05`` SEC-F40-06, -09).

No AC of its own (W2 tests AC-F40-30..33 and -38 with the wiring): small unit checks of the
message lines, the event decoding (``preview.decode_report``), the display text, and the
request tracker."""

import json
import logging
import sys
import time

from engine.core.editorreport import REPORT_MARKER
from engine.tools.editor import consoleclient as cc
from engine.tools.editor.preview import CONSOLE, PreviewRunner, PreviewState, decode_report


def event(**fields) -> dict:
    return {"v": 1, "event": "console", "do": "set", "ok": True, "text": "trust is now 5.",
            **fields}


def values_event(**fields) -> dict:
    return event(**{"do": "values", "text": "", "story": True, "values": [["trust", "5"]],
                    "left_out": 0, **fields})


def report(obj: dict) -> bytes:
    return REPORT_MARKER + json.dumps(obj, separators=(",", ":")).encode("ascii")


def test_message_lines_carry_values_and_labels_only():
    assert cc.open_line() == b'{"v":1,"msg":"console","do":"open"}\n'
    assert cc.values_line() == b'{"v":1,"msg":"console","do":"values"}\n'
    assert cc.jump_line("festival_end") == \
        b'{"v":1,"msg":"console","do":"jump","label":"festival_end"}\n'
    assert json.loads(cc.set_line("hana", '"Hana é"')) == \
        {"v": 1, "msg": "console", "do": "set", "name": "hana", "value": '"Hana é"'}
    assert cc.set_line("hana", '"é"').isascii()
    for bad in ("", "x" * 1_025, None, 3):
        assert cc.jump_line(bad) is None
    for name, value in (("", "1"), ("n" * 256, "1"), ("n", 1), ("n", None),
                        ("n", "v" * 4_100)):                     # the last: over 4 KiB
        assert cc.set_line(name, value) is None


def test_console_events_decode_with_exact_keys_and_types():
    assert decode_report(report(event())) == \
        (CONSOLE, cc.ConsoleEvent("set", True, "trust is now 5."))
    _, got = decode_report(report(values_event()))
    assert got == cc.ConsoleEvent("values", True, "", True, (("trust", "5"),), 0)
    bad = [
        event(do="eval"), event(ok=1), event(text=None), event(text="t" * 2_001),
        event(extra=1), {k: v for k, v in event().items() if k != "ok"},
        event(story=True),                                       # values keys on a set
        values_event(story=None), values_event(left_out=-1), values_event(left_out=True),
        values_event(values={"trust": "5"}), values_event(values=[["trust"]]),
        values_event(values=[["trust", 5]]), values_event(values=[["t" * 256, "5"]]),
        values_event(values=[["trust", "v" * 201]]),
        values_event(values=[["n", "1"]] * 1_001),
        {k: v for k, v in values_event().items() if k != "left_out"},
    ]
    for obj in bad:
        assert decode_report(report(obj)) is None, obj


def test_shown_escapes_and_cuts_forged_text():
    forged = "\x1b[2J‮gnp.exe\n\ud800" + "A" * 10_000
    text = cc.shown(forged)
    assert len(text) == 200 and text.endswith("…")
    assert text.startswith("\\x1b[2J\\u202egnp.exe\\n�")
    assert not any(c in text for c in "\x1b‮\n\ud800")
    assert cc.shown("Jumped to festival.") == "Jumped to festival."
    assert cc.shown(None) == ""                                  # type: ignore[arg-type]
    assert cc.status_text(cc.ConsoleEvent("jump", True, "Jumped to \x07x.")) == \
        "Console: Jumped to \\x07x."


def test_tracker_acts_only_on_outstanding_requests(caplog):
    now = [10.0]
    tracker = cc.ConsoleTracker(clock=lambda: now[0])
    forged = cc.ConsoleEvent("jump", True, "Jumped to x.")
    with caplog.at_level(logging.DEBUG):
        assert tracker.receive(forged) is None                   # nothing asked: ignored
        tracker.sent("jump")
        assert tracker.waiting("jump")
        answer = tracker.receive(forged)
        assert answer == cc.ConsoleAnswer("jump", True, "Console: Jumped to x.")
        assert tracker.receive(forged) is None                   # one answer per request
        tracker.sent("values")
        got = tracker.receive(cc.ConsoleEvent(
            "values", True, "", True, (("trust", "\x1b5"), ("ghost", "1")), 3),
            known={"trust"})
        assert got == cc.ConsoleAnswer("values", True, None, True, {"trust": "\\x1b5"}, 3)
        tracker.sent("set")
        now[0] += 1.9
        assert tracker.overdue() == []
        now[0] += 0.2
        assert tracker.overdue() == ["set"] and not tracker.waiting("set")
        assert tracker.receive(cc.ConsoleEvent("set", True, "late")) is None
        tracker.sent("open")
        tracker.clear()
        assert tracker.overdue() == [] and not tracker.waiting("open")
    assert caplog.records == []                                  # logs no field


def test_the_runner_passes_console_events_on():
    lines = [{"v": 1, "event": "started"}, event(), event(ok="yes"),
             values_event(values=[["a", "1"]])]
    script = "import sys\n" + "".join(
        f"sys.stdout.buffer.write({report(obj) + chr(10).encode()!r})\n" for obj in lines)
    runner = PreviewRunner(forward=lambda line: None)
    try:
        runner.start([sys.executable, "-c", script])
        end = time.monotonic() + 15
        seen = []
        while time.monotonic() < end:
            seen += [e.state for e in runner.poll()]
            if PreviewState.CLOSED in seen:
                break
            time.sleep(0.02)
        assert PreviewState.CLOSED in seen
        assert runner.console_events() == [
            cc.ConsoleEvent("set", True, "trust is now 5."),
            cc.ConsoleEvent("values", True, "", True, (("a", "1"),), 0)]
        assert runner.console_events() == []
    finally:
        runner.stop(timeout_s=1.0)
        proc = runner.process
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(5)

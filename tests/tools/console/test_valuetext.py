"""F40 P2: the console's bounded value text and its answer to Studio (``04`` §7.4, §7.5;
``05`` SEC-F40-05, -07). AC-F40-22, AC-F40-28, AC-F40-37."""

import json
import time

from engine.core.editorreport import REPORT_MARKER, REPORT_MAX_BYTES
from engine.tools.console.answer import console_event
from engine.tools.console.valuetext import (
    CANT_SHOW,
    CODE_MAX,
    ROW_MAX,
    VALUES_MAX,
    TextBatch,
    value_text,
)

BS = "\\"
HOME = f"C:{BS}Users{BS}Mia{BS}Documents{BS}game"           # a profile path, as text


def guard(calls: list):
    """A stand-in for P1's ``guarded``: one call, every exception absorbed (a watchdog stop
    arrives as ``KeyboardInterrupt``)."""
    def call(fn):
        calls.append(fn)
        try:
            fn()
        except BaseException:
            pass
    return call


class Raises:
    def __repr__(self):
        raise RuntimeError("boom")


class Loops:
    """A ``__repr__`` that never returns: the watchdog stops it (simulated)."""

    tried = 0

    def __repr__(self):
        Loops.tried += 1
        raise KeyboardInterrupt


class Shown:
    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return self.text


def decode(line: bytes) -> dict:
    assert line.startswith(REPORT_MARKER) and line.isascii()
    return json.loads(line[len(REPORT_MARKER):])


def test_ac_f40_22_unshowable_repr():
    """A value whose ``repr`` raises or loops shows ``<can't show this value>``; a looping
    one stops the batch, so the others show it too, after one guarded call."""
    calls = []
    assert value_text(Raises(), ROW_MAX, guard(calls)) == CANT_SHOW
    assert value_text([1, Raises()], ROW_MAX, guard(calls)) == f"[1, {CANT_SHOW}]"
    Loops.tried = 0
    batch = TextBatch()
    for value in (Loops(), Shown("fine"), [Loops()]):
        batch.add(value, ROW_MAX)
    calls.clear()
    assert batch.texts(guard(calls)) == [CANT_SHOW, CANT_SHOW, f"[{CANT_SHOW}]"]
    assert len(calls) == 1 and Loops.tried == 1                 # the stop ended the batch
    assert value_text(Shown("ok"), ROW_MAX) == CANT_SHOW        # no guard: no author code


def test_ac_f40_28_values_answer():
    """``values`` answers at most 1,000 names with value texts of at most 200 characters,
    redacted, in one event; the rest are counted."""
    batch = TextBatch()
    names = [f"v{i}" for i in range(1_200)]
    for i in range(1_200):
        batch.add({"path": HOME, "n": i, "pad": "x" * 500}, VALUES_MAX)
    texts = batch.texts()
    line = console_event("values", True, "", story=True, values=list(zip(names, texts)))
    assert b"\n" not in line and len(line) <= REPORT_MAX_BYTES
    event = decode(line)
    assert event.keys() == {"v", "event", "do", "ok", "text", "story", "values", "left_out"}
    assert (event["v"], event["event"], event["do"], event["ok"], event["story"]) == \
        (1, "console", "values", True, True)
    assert len(event["values"]) == 1_000 and event["left_out"] == 200
    assert [name for name, _ in event["values"]] == names[:1_000]
    for _, text in event["values"]:
        assert len(text) <= 200 and "Mia" not in text and "<user>" in text
    # Other kinds carry only the text, redacted and cut to 2,000.
    jump = decode(console_event("jump", False, f"no scene at {HOME} " + "y" * 3_000))
    assert jump.keys() == {"v", "event", "do", "ok", "text"}
    assert len(jump["text"]) == 2_000 and "Mia" not in jump["text"]
    assert decode(console_event("values", True, "", story=False))["values"] == []


def test_ac_f40_37_value_table():
    """05 §5's value table: each text within its cap, plain values within 50 ms with no
    author code; author ``repr``s in at most one guarded call per batch; controls and bidi
    escaped; the home path redacted; a 1,000-name non-ASCII answer fits with a count."""
    itself = [1]
    itself.append(itself)
    deep = leaf = []
    for _ in range(200):
        leaf.append([])
        leaf = leaf[0]
    big = list(range(10_000_000))
    rows = [
        # (value, what the text must contain)
        (itself, "[1, …]"),
        (deep, "[" * 100 + "…"),
        (big, "[0, 1, 2, 3"),
        ("s" * 1_000_000, "'sss"),
        (10 ** 5000, CANT_SHOW),
        ("\x1b[31mred", BS + "x1b[31mred"),
        ("‮evil", BS + "u202eevil"),
        ("one\ntwo", "one" + BS + "ntwo"),
        (HOME, "<user>"),
        ({"k": (1,), "s": {2}, "f": frozenset(), "n": None, "b": True, "x": 2.5},
         "{'k': (1,), 's': {2}, 'f': frozenset(), 'n': None, 'b': True, 'x': 2.5}"),
    ]
    for cap in (ROW_MAX, VALUES_MAX, CODE_MAX):
        for value, expected in rows:
            start = time.perf_counter()
            text = value_text(value, cap)                       # no guard: plain only
            elapsed = time.perf_counter() - start
            assert len(text) <= cap and elapsed < 0.05, (cap, expected, len(text), elapsed)
            assert expected[:cap - 1] in text, (cap, expected, text)
            assert "Mia" not in text and "\x1b" not in text and "‮" not in text
            assert "\n" not in text
    assert value_text(deep, CODE_MAX) == "[" * 100 + "…" + "]" * 100

    # Author objects: escaped, redacted, cut; one guarded call for the whole batch.
    hostile = Shown("\x1b[2J‮" + HOME + "!" * 5_000)
    batch = TextBatch()
    for i in range(1_000):
        batch.add([i, hostile, Raises()], ROW_MAX)
    calls = []
    texts = batch.texts(guard(calls))
    assert len(calls) == 1 and len(texts) == 1_000
    for text in texts:
        assert len(text) <= ROW_MAX and text.endswith("…")
        assert "\x1b" not in text and "‮" not in text and "Mia" not in text
        assert BS + "x1b[2J" + BS + "u202e" in text
    Loops.tried = 0
    loops = TextBatch()
    for _ in range(1_000):
        loops.add(Loops(), VALUES_MAX)
    calls.clear()
    assert set(loops.texts(guard(calls))) == {CANT_SHOW}
    assert len(calls) == 1 and Loops.tried == 1                 # 5 s at most, not 83 min
    plain = TextBatch()
    plain.add(big, ROW_MAX)
    assert not plain.needs_call
    calls.clear()
    plain.texts(guard(calls))
    assert calls == []                                          # nothing to call for

    # 1,000 names of 255 non-BMP characters with 200-character non-ASCII texts: ASCII
    # escaping makes that about 5 MB, so trailing values are dropped and counted.
    values = [(f"\U0001F600{i:04d}" * 51, "é\U0001F600" * 100) for i in range(1_000)]
    line = console_event("values", True, "", story=True, values=values)
    assert len(line) <= REPORT_MAX_BYTES
    event = decode(line)
    kept = len(event["values"])
    assert 0 < kept < 1_000 and event["left_out"] == 1_000 - kept
    assert event["values"][0] == [values[0][0], values[0][1]]

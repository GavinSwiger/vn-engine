"""F40 P2: the ``console`` stdin message on F39's channel (``04`` §7.5, ``05`` SEC-F40-06).

The parse half of AC-F40-38's channel table (W2 owns the AC): only the shape is checked
here, exact keys per ``do``, exact ``str`` fields within their lengths; whether a name or
label exists is the console's refusal (P4/W1). Nothing read is logged or echoed."""

import io
import json
import logging

import pytest

from engine.app import hot_reload as hr
from engine.app.hot_reload import ConsoleRequest

SECRET = "zz-console-secret-zz"


def line(obj: object) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode("ascii")


def msg(do: str, **fields: object) -> bytes:
    return line({"v": 1, "msg": "console", "do": do, **fields})


DEEP = "[" * 2_000 + "]" * 2_000

ROWS = [
    # Accepted shapes (the console checks names and labels; values go to parse_literal).
    (msg("open"), ConsoleRequest("open")),
    (msg("values"), ConsoleRequest("values")),
    (msg("jump", label="riverbank"), ConsoleRequest("jump", label="riverbank")),
    (msg("jump", label="riverbank~1"), ConsoleRequest("jump", label="riverbank~1")),
    (msg("jump", label="x" * 1_024), ConsoleRequest("jump", label="x" * 1_024)),
    (msg("set", name="trust", value="5"), ConsoleRequest("set", name="trust", value="5")),
    (msg("set", name="trust", value=""), ConsoleRequest("set", name="trust", value="")),
    (msg("set", name="__builtins__", value="1"),
     ConsoleRequest("set", name="__builtins__", value="1")),
    (msg("set", name="\ud800", value="1"), ConsoleRequest("set", name="\ud800", value="1")),
    (msg("set", name="trust", value="__import__('os').system('x')"),
     ConsoleRequest("set", name="trust", value="__import__('os').system('x')")),
    (msg("set", name="trust", value=DEEP[:3_000]),
     ConsoleRequest("set", name="trust", value=DEEP[:3_000])),
    (b'{"v":1,"msg":"console","do":"set","name":"h\\u00e9","value":"\\"\\u00e9\\""}',
     ConsoleRequest("set", name="hé", value='"é"')),
    # Dropped: version, kind, keys, types, lengths, encoding, duplicates.
    (line({"v": True, "msg": "console", "do": "open"}), None),
    (line({"v": "1", "msg": "console", "do": "open"}), None),
    (line({"v": 2, "msg": "console", "do": "open"}), None),
    (msg("eval", code="1"), None),
    (msg("OPEN"), None),
    (line({"v": 1, "msg": "console"}), None),
    (line({"v": 1, "msg": "console", "do": None}), None),
    (msg("open", label="x"), None),
    (msg("values", name="trust"), None),
    (msg("jump"), None),
    (msg("jump", label="a", name="b"), None),
    (msg("set", name="trust"), None),
    (msg("set", value="1"), None),
    (msg("set", name="trust", value="1", code="1"), None),
    *[(msg("jump", label=bad), None) for bad in (1, 1.5, ["a"], {"a": 1}, None, True, "")],
    *[(msg("set", name=bad, value="1"), None)
      for bad in (1, ["a"], {"a": 1}, None, True, "", "n" * 256)],
    *[(msg("set", name="trust", value=bad), None)
      for bad in (5, 5.0, [1, 2], {"a": 1}, None, True)],
    (msg("jump", label="x" * 1_025), None),
    (msg("jump", label="x" * 2_000), None),
    (msg("set", name="trust", value="v" * 4_100), None),                # over 4 KiB
    ('{"v":1,"msg":"console","do":"jump","label":"café"}'.encode(), None),  # non-ASCII
    (b'{"v":1,"msg":"console","do":"open","do":"open"}', None),         # duplicate key
    (b'{"v":1,"msg":"console","do":"values","do":"open"}', None),
    (b'{"v":1,"msg":"console","do":"jump","label":"a","label":"b"}', None),
    (b'{"v":1,"msg":"console","do":"open"', None),                      # bad JSON
    (b'["console"]', None),
]


@pytest.mark.parametrize("data, expected", ROWS)
def test_console_message_shapes(data, expected):
    assert hr.parse_message(data) == expected


def test_console_messages_reach_only_the_console(capsys, caplog):
    """Read from stdin in order with F39's messages; ``handle_messages`` hands each to the
    ``console`` callback, never in error mode or with no callback; nothing is logged."""
    data = b"\n".join([msg("jump", label=SECRET), line({"v": 1, "msg": "held", "errors": 1}),
                       msg("set", name=SECRET, value=SECRET), msg("eval", code=SECRET),
                       msg("set", name=SECRET * 20, value="1"), msg("values"), b""])
    with caplog.at_level(logging.DEBUG):
        reader = hr.StdinReader(io.BufferedReader(io.BytesIO(data))).start()
        reader.join(5)
        messages = reader.poll()
        assert messages == [ConsoleRequest("jump", label=SECRET), hr.Held(1),
                            ConsoleRequest("set", name=SECRET, value=SECRET),
                            ConsoleRequest("values")]
        got, shown = [], []
        asked = hr.handle_messages(messages, error_mode=False, console=got.append,
                                   notify=lambda text, kind: shown.append(text),
                                   reload=lambda: None)
        assert not asked and got == [m for m in messages if type(m) is ConsoleRequest]
        assert len(shown) == 1
        got.clear()
        hr.handle_messages(messages, error_mode=True, console=got.append,
                           notify=lambda text, kind: None, reload=lambda: None)
        assert got == []                                        # error mode: dropped
        hr.handle_messages(messages, error_mode=False, notify=lambda text, kind: None,
                           reload=lambda: None)                 # no console: dropped
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err
    assert not any(SECRET in record.getMessage() for record in caplog.records)

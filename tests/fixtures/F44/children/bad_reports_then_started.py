"""Fake preview child: the AC-F44-11 report lines the editor must drop, then a valid
``started``, then exit 0. Each bad line would change the state if it were accepted (most are
error reports), so the expected states are only Starting → Running → Closed."""

import json

import _protocol

MARKER = _protocol.MARKER
ITEM = {"text": "script/main.vns, line 1: boom.", "file": "script/main.vns", "line": 1,
        "column": None}


def error(**changes):
    obj = {"v": 1, "event": "error", "phase": "start", "head": None, "items": [ITEM],
           "tail": []}
    obj.update(changes)
    return obj


_protocol.raw(MARKER + b"{not json\n")                                       # invalid JSON
_protocol.report({"v": 2, "event": "started"})                               # "v": 2
_protocol.report({"v": 1, "event": "bogus"})                                 # unknown event
_protocol.report(error(items=[ITEM] * 61))                                   # 61 items
_protocol.report(error(phase="run", items=[dict(ITEM, text="z" * 10_001)]))  # text too long
# Over 1 MiB, though every field keeps its own limit (60 items and 60 tail lines of 10,000).
big = json.dumps(error(phase="run", items=[dict(ITEM, text="a" * 10_000)] * 60,
                       tail=["t" * 10_000] * 60)).encode("ascii")
_protocol.raw(MARKER + big + b"\n")                                          # over 1 MiB
_protocol.raw(MARKER + json.dumps(error(phase="run", head="日"),
                                  ensure_ascii=False).encode("utf-8") + b"\n")  # non-ASCII
_protocol.started()

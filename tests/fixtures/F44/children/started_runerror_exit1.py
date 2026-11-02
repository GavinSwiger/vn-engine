"""Fake preview child: ``started``, then a run-time error report (its error screen shows),
then exit 1 a moment later."""

import time

import _protocol

_protocol.started()
_protocol.error("run", [{
    "text": "script/chapter2.vns, line 7, column 5: dividing by zero isn't possible.",
    "file": "script/chapter2.vns", "line": 7, "column": 5}])
time.sleep(0.2)
raise SystemExit(1)

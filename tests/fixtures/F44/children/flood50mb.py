"""Fake preview child: ``started``, then 50 MB of output in 1 KB lines, then waits (the
editor must stay responsive, forward the lines, and store none of them)."""

import _protocol

_protocol.started()
LINE = b"x" * 1023 + b"\n"
CHUNK = LINE * 64                               # 64 KB per write
for _ in range(50 * 1024 * 1024 // len(CHUNK)):
    _protocol.raw(CHUNK)
_protocol.wait()

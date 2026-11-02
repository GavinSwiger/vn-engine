"""Fake preview child: 5 MB with no line break, then a newline and a valid ``started``
line, then waits. The long line is discarded and the preview ends up running."""

import _protocol

for _ in range(80):
    _protocol.raw(b"y" * 65536)                 # 5 MB in all
_protocol.raw(b"\n")
_protocol.started()
_protocol.wait()

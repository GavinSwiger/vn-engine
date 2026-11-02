"""Fake preview child: an ordinary UTF-8 output line (an author's ``print``), then
``started``, then exit 0. The line must reach the editor's stdout unchanged."""

import _protocol

_protocol.raw("hello 日本\n".encode("utf-8"))
_protocol.started()

"""Fake check child: a problems line, then exits 0 without ``done``."""

import _protocol

_protocol.problems([_protocol.problem("never applied")])

"""Fake check child: problems, names, graph, a 0.3 s pause, then ``done``; exits 0."""

import _protocol

_protocol.standard_run(pause=0.3)

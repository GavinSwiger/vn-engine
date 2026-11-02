"""Fake check child that never reads stdin: a whole run, then exits 0."""

import _protocol

_protocol.standard_run()

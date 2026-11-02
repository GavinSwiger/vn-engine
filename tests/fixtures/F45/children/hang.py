"""Fake check child that hangs after one problems line (up to 60 s). On POSIX it ignores
SIGTERM, so only a kill ends it."""

import signal

import _protocol

if hasattr(signal, "SIGKILL"):                  # POSIX
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
_protocol.problems([_protocol.problem("never applied")])
_protocol.wait()

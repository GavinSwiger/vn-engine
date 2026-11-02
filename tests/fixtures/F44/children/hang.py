"""Fake preview child that hangs: ``started`` (unless ``--silent``), then waits up to 60 s.
On POSIX it ignores SIGTERM, so only a kill ends it."""

import signal
import sys

import _protocol

if hasattr(signal, "SIGKILL"):                  # POSIX
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if "--silent" not in sys.argv:
    _protocol.started()
_protocol.wait()

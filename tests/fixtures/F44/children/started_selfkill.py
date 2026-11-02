"""Fake preview child: ``started``, then killed: SIGKILL on POSIX, ``TerminateProcess`` on
Windows (``os.kill`` with any other signal number)."""

import os
import signal

import _protocol

_protocol.started()
os.kill(os.getpid(), getattr(signal, "SIGKILL", signal.SIGTERM))
_protocol.wait()

"""Fake preview child (AC-F44-30's ``crash``): ``started``, then exit 3 with no report."""

import time

import _protocol

_protocol.started()
time.sleep(0.2)
raise SystemExit(3)

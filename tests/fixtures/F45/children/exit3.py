"""Fake check child: a whole run, ``done`` included, is never written; exits 3."""

import sys

import _protocol

_protocol.problems([_protocol.problem("never applied")])
sys.exit(3)

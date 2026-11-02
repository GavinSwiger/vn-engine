"""Fake check child: 1,001 valid problems (one past ``CHECK_MAX_PROBLEMS``), then ``done``."""

import _protocol

items = [_protocol.problem(f"problem {n}") for n in range(1_001)]
_protocol.problems(items[:500])
_protocol.problems(items[500:])
_protocol.done(1_001)

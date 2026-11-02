"""Fixtures for the F12 persist tests (06-acceptance §0.2, §0.3).

``slow`` tests (real 32 MiB inputs, 1,000,000 seen lines, the full fuzz) and ``perf`` tests
are skipped unless ``VN_SLOW=1`` / ``VN_PERF=1`` is set or ``-m`` names them (the rule is in
``tests/conftest.py``).
"""

import logging

import pytest


class Warnings(list):
    """``(code, message)`` of every record logged to area ``persist``."""

    def codes(self) -> list[str]:
        return [code for code, _ in self]

    def of(self, code: str) -> list[str]:
        return [message for c, message in self if c == code]


class _Recorder(logging.Handler):
    def __init__(self, out: Warnings) -> None:
        super().__init__(logging.DEBUG)
        self.out = out

    def emit(self, record: logging.LogRecord) -> None:
        self.out.append((getattr(record, "code", None), record.getMessage()))


@pytest.fixture
def warnings() -> Warnings:
    """Records of the ``vn.persist`` logger (the store's default log)."""
    out = Warnings()
    logger = logging.getLogger("vn.persist")
    handler = _Recorder(out)
    old_level, old_disabled = logger.level, logger.disabled
    logger.setLevel(logging.DEBUG)
    logger.disabled = False
    logger.addHandler(handler)
    yield out
    logger.removeHandler(handler)
    logger.setLevel(old_level)
    logger.disabled = old_disabled

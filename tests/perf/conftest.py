"""Shared setup of the ``tests/perf`` tests (the ``s0_*.py`` spike scripts are not tests).

``slow`` and ``perf`` tests are skipped unless ``VN_SLOW=1`` / ``VN_PERF=1`` is set or ``-m``
names the marker (``tests/conftest.py``). ``perf`` tests are for the ADR-0005
reference machine or a recorded stand-in, never CI (F02 06-acceptance §0.3). The ``corpus``
fixture is ``tests/script``'s (a cached ``gen_corpus.py`` corpus). ``real_display`` fails a
bench run (F04, F05) started under SDL's dummy driver.
"""

import os

import pytest

from tests.script.conftest import corpus  # noqa: F401  (the shared, cached corpus fixture)


@pytest.fixture
def real_display():
    driver = os.environ.get("SDL_VIDEODRIVER", "")
    assert driver != "dummy", ("the bench needs a real display: set SDL_VIDEODRIVER "
                               "(windows, x11, cocoa) before running perf tests")

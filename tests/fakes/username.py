"""The name guard (F30 SEC-F30-11, ``06`` §0.3): tests never read the real login name.

Every F30 test module (any test source naming ``username``, ``UsernameSource``, or the
test name) imports the autouse fixture at module level::

    from tests.fakes.username import no_real_username  # noqa: F401  (name guard)

It patches ``getpass.getuser`` to raise ``RealNameRead``, a ``BaseException`` subclass, so
``read_login_name``'s ``except Exception`` can't swallow it and any real read fails the test.
Tests hand ``UsernameSource`` a fake ``read`` instead (``reader``). F01's
``test_runtime_identity_is_not_reported`` stays the only automated real read
(``tests/test_f30_name_guard.py`` checks both rules).
"""

import getpass
from collections.abc import Callable

import pytest

Z = "Zq9Name"                                   # 06 §0.3 "Names"
Z32 = Z + "Ｗ" * 25                         # 32 graphemes, wide


class RealNameRead(BaseException):
    """Raised by the patched ``getpass.getuser``: a test tried to read the real name."""


def _refuse(*args, **kwargs):
    raise RealNameRead("a test called getpass.getuser(); pass a fake read= instead")


@pytest.fixture(autouse=True)
def no_real_username(monkeypatch, tmp_path_factory):
    # pytest names its base temp folder after the user ("pytest-of-<user>") on first use;
    # make it before the patch so ``tmp_path`` works. That is pytest's read, once per
    # session, not the engine's, and nothing of it reaches the code under test.
    tmp_path_factory.getbasetemp()
    monkeypatch.setattr(getpass, "getuser", _refuse)
    yield


def reader(value: "str | None | BaseException" = Z) -> Callable[[], str | None]:
    """A fake ``read`` that returns ``value`` (or raises it) and counts its calls in
    ``.calls``."""

    def read() -> str | None:
        read.calls += 1
        if isinstance(value, BaseException):
            raise value
        return value

    read.calls = 0
    return read

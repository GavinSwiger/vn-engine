"""CommandRouter and the story seam: AC-F01-92 (the App part is in test_app_loop.py)."""

import pytest

from engine.app.dispatch import CommandRouter, UnhandledCommandError


class A:
    pass


class B(A):
    pass


def test_dispatch_calls_the_handler_for_the_type():
    router = CommandRouter()
    seen = []
    router.register(A, lambda c: seen.append(("A", c)))
    command = A()
    router.dispatch(command)
    assert seen == [("A", command)]


def test_a_subclass_falls_back_to_its_base_handler_until_it_has_its_own():
    router = CommandRouter()
    seen = []
    router.register(A, lambda c: seen.append("A"))
    router.dispatch(B())
    router.register(B, lambda c: seen.append("B"))
    router.dispatch(B())
    router.dispatch(A())
    assert seen == ["A", "B", "A"]


def test_a_second_registration_raises():
    router = CommandRouter()
    router.register(A, lambda c: None)
    with pytest.raises(ValueError):
        router.register(A, lambda c: None)


def test_unregistered_type_raises_and_unregister_works():
    router = CommandRouter()
    with pytest.raises(UnhandledCommandError):
        router.dispatch(A())
    router.register(A, lambda c: None)
    router.unregister(A)
    with pytest.raises(UnhandledCommandError):
        router.dispatch(A())
    router.register(A, lambda c: None)          # allowed again after unregister

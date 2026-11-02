"""The guard around every call into author Python (F03 ``04-technical.md`` §5.2, §7.7).

Why this module exists: the watchdog lives in ``app`` (it needs a thread and a clock, which
``runtime`` never imports, invariant 7), but the interpreter and the launch phase must tell
it when author code starts and stops. This Protocol is that seam; ``NO_GUARD`` is used
headless and in tests, where nothing interrupts author code. The windowed game's guard is
``engine.app.story.Watchdog`` (step 12). In the interpreter every guard entry goes through
the one helper ``Interpreter._author`` (where F12 I-1 counts ``author_calls``).

Contract for every caller: ``enter()`` right before the author call, ``exit()`` in a
``finally``; a ``KeyboardInterrupt`` caught around it asks ``consume_fired()``: True → E85m,
False → re-raise (a real Ctrl+C).
"""

from typing import Protocol


class AuthorCodeGuard(Protocol):
    def enter(self) -> None:
        """Author code is about to run (arms the watchdog)."""

    def exit(self) -> None:
        """Author code finished or raised (disarms the watchdog)."""

    def consume_fired(self) -> bool:
        """True once if the watchdog interrupted author code since the last call."""


class _NoGuard:
    """A guard that never fires."""

    __slots__ = ()

    def enter(self) -> None:
        pass

    def exit(self) -> None:
        pass

    def consume_fired(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "NO_GUARD"


NO_GUARD: AuthorCodeGuard = _NoGuard()

__all__ = ["NO_GUARD", "AuthorCodeGuard"]

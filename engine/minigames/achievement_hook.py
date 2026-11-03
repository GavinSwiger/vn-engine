"""The achievement platform hook (F37 ``SPEC.md`` §5.3, PR-F37-06; API 1.2).

Why this module exists: a game sold on a store (Steam and the like) wants each achievement
told to that store, but the engine itself never uses the network (F42) and must work the
same without any store. So the store is a **plugin seam**: a file in ``game/minigames/``
(loaded by F23's loader, trusted code, ADR-0009) calls ``api.register_achievement_hook``
with an object whose methods the engine calls:

- ``started(unlocked: tuple[str, ...])`` (optional): once, after the persistent read, with
  the names already recorded;
- ``unlocked(name: str)``: once per new unlock, after its notice.

``AchievementHook`` is what registration keeps: the unit that registered it and the two
bound methods, looked up **once**, inside the loader's guard, so no plugin attribute lookup
runs later. ``HookRunner`` (F37-S2's ``app/achievements.py`` owns one per launch; windowed
runs only) makes the calls on the main thread, each between ``guard.enter()`` and
``guard.exit()`` and timed with the injected clock:

- an exception (or the watchdog) turns the hook **off** for the rest of the session with
  W225's failure form; nothing else changes (achievements are still kept locally);
- a call over 0.1 s logs W225's slow form, once per session.

W225's texts are in ``minigames/messages.py`` (``minigames`` never imports ``script``); they
print only the method name, the exception's type name, and the seconds. Pure apart from the
clock it is given: no file, thread, or network.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from engine.core.logsetup import get_logger
from engine.minigames import messages
from engine.runtime.guard import NO_GUARD, AuthorCodeGuard

SLOW_S: Final = 0.1                 # a hook call over this logs W225's slow form (once)
UNLOCKED: Final = "unlocked"
STARTED: Final = "started"

_log = get_logger("plugin")


@dataclass(frozen=True)
class AchievementHook:
    """A registered hook: the plugin unit (``minigames/x.py``) and its bound methods."""

    unit: str
    unlocked: Callable[[str], object]
    started: Callable[[tuple[str, ...]], object] | None = None


class HookRunner:
    """Calls one hook (or none) for one session (module docstring). ``clock`` gives seconds
    (``time.perf_counter`` by default); ``guard`` is the app's watchdog guard."""

    def __init__(self, hook: AchievementHook | None, *, guard: AuthorCodeGuard = NO_GUARD,
                 clock: Callable[[], float] = time.perf_counter, log=None) -> None:
        self.hook = hook
        self.guard = guard
        self.clock = clock
        self.log = log if log is not None else _log
        self.off = False                    # W225 failure given: no more calls
        self._started = False
        self._slow_warned = False

    @property
    def active(self) -> bool:
        return self.hook is not None and not self.off

    def started(self, unlocked: tuple[str, ...]) -> None:
        """``hook.started(unlocked)``, once per session (a hook without it: nothing)."""
        if self._started:
            return
        self._started = True
        hook = self.hook
        if hook is not None and hook.started is not None and not self.off:
            self._call(STARTED, hook.started, tuple(unlocked))

    def unlocked(self, name: str) -> None:
        """``hook.unlocked(name)`` for one new unlock (F37-S2 calls it after the notice)."""
        hook = self.hook
        if hook is not None and not self.off:
            self._call(UNLOCKED, hook.unlocked, name)

    def _call(self, method: str, fn: Callable[[object], object], arg: object) -> None:
        guard = self.guard
        start = self.clock()
        try:
            guard.enter()
            try:
                fn(arg)
            finally:
                guard.exit()
        except KeyboardInterrupt:
            if not guard.consume_fired():
                raise
            self._fail(method, messages.W225_TOO_LONG)
            return
        except Exception as exc:            # plugin code: the hook goes off, the game goes on
            self._fail(method, type(exc).__name__)
            return
        seconds = self.clock() - start
        if seconds > SLOW_S and not self._slow_warned:
            self._slow_warned = True
            self.log.warning("%s", messages.w225_slow(method, seconds),
                             extra={"code": "W225"})

    def _fail(self, method: str, reason: str) -> None:
        self.off = True
        self.log.warning("%s", messages.w225_failed(method, reason), extra={"code": "W225"})


__all__ = ["AchievementHook", "HookRunner", "SLOW_S", "STARTED", "UNLOCKED"]

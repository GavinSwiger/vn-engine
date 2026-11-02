"""A fake clock and a scripted frame limiter for driving ``App.run`` frame by frame.

``ScriptedLimiter.wait()`` advances the fake clock by one frame period (or a scripted
step) and then runs the actions scheduled for that frame number, before the App reads the
frame's events. An action that posts ``pygame.QUIT`` ends the loop after that frame.

``quit_at(n)`` closes the window in frame ``n`` and again in every later frame the loop is
still running: F10's quit guard asks first while a story is in progress, and a second close
quits at once (``04`` §7.7.6), so a run in the middle of a game ends one frame later.
"""

from collections import defaultdict
from collections.abc import Callable

import pygame


class FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class ScriptedLimiter:
    """Stands in for ``FrameLimiter``; frame numbers start at 1."""

    def __init__(self, clock: FakeClock, fps: int = 60, *, max_frames: int = 10_000) -> None:
        self.clock = clock
        self.period = 1.0 / fps
        self.frame = 0
        self.max_frames = max_frames
        self.resets = 0
        self.steps: dict[int, float] = {}
        self.actions: dict[int, list[Callable[[], None]]] = defaultdict(list)
        self.quit_from: int | None = None

    def at(self, frame: int, action: Callable[[], None]) -> "ScriptedLimiter":
        self.actions[frame].append(action)
        return self

    def quit_at(self, frame: int) -> "ScriptedLimiter":
        """Close the window in ``frame`` and in every later frame."""
        self.quit_from = frame if self.quit_from is None else min(self.quit_from, frame)
        return self

    def wait(self) -> float:
        self.frame += 1
        self.clock.now += self.steps.get(self.frame, self.period)
        for action in self.actions.get(self.frame, ()):
            action()
        if self.frame >= self.max_frames or (self.quit_from is not None
                                             and self.frame >= self.quit_from):
            post_quit()
        return self.clock.now

    def reset(self) -> None:
        self.resets += 1

    def set_fps(self, fps: int) -> None:
        self.period = 1.0 / fps


def post_quit() -> None:
    pygame.event.post(pygame.event.Event(pygame.QUIT))


def post_key(key: int, mod: int = 0) -> None:
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod, unicode="",
                                         scancode=0))

"""Host U for F53's quick minigames (Lock, Stay still, Hand game) and F54's Gift giving: F23's
``MinigameHost`` on F10's unit canvas (``tests.minigames.host_u``), with the game's class in
the registry (added when the bundled list doesn't have it yet), and helpers to open a session
that records ``ctx.finish`` and to type keys with their text."""

import dataclasses

import pygame

from engine.minigames import api
from engine.ui.input import UiEvent
from tests.fakes.ui_shell import UiHarness
from tests.minigames.host_u import HostU, load_plugins

H = UiHarness


def world(game, cls, **kwargs) -> HostU:
    """A Host U world whose registry has ``cls`` (a bundled class, unit "engine")."""
    registry = load_plugins(game, dev=kwargs.get("dev", True))
    if cls.name not in registry:
        registry.add(api.declarations(cls, "engine"))
    return HostU(game, registry=registry, **kwargs)


def open_game(w: HostU, name: str, args: dict, *, skippable: bool = False, **command):
    """A fresh session (no fade) with ``args``; ``g.finishes`` records ``ctx.finish``."""
    w.posted.clear()
    w.audio.calls.clear()
    cmd = dataclasses.replace(w.command(name, args, **command), skippable=skippable)
    w.host.start(cmd)
    assert not w.fatal, [f.format() for f in w.fatal]
    g = w.session.plugin
    port = w.session.ctx._port
    real = port.finish
    g.finishes = []

    def finish(result):
        g.finishes.append(result)
        return real(result)

    port.finish = finish
    return g


def tap(key: int, *, text: str = "", mod: int = 0) -> tuple[UiEvent, UiEvent]:
    """A key press and release; ``text`` is the press's ``unicode``."""
    down = UiEvent(pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod, unicode=text), None,
                   False)
    return down, H.key(key, up=True)


def typed(ch: str) -> tuple[UiEvent, UiEvent]:
    """The key for one ASCII digit or letter, with its text."""
    key = getattr(pygame, f"K_{ch.lower()}")
    return tap(key, text=ch)


def pad(button: int) -> tuple[UiEvent, UiEvent]:
    return H.pad(button), H.pad(button, up=True)


def done_after(w: HostU, limit: int = 600):
    """Frames until the session posts ``MinigameDone``; returns it."""
    for _ in range(limit):
        found = w.done()
        if found:
            return found[-1]
        w.frame()
    raise AssertionError("the game didn't finish")

"""Host R (F27 ``06`` §0.2): F23's Host U pieces (``MinigameHost`` and ``MinigameScreen`` on
F10's unit canvas: SDL dummy, offscreen 1280×720, default theme with F10's button sounds,
100% text, fake clock 1/60 s, an Audio spy, a post sink, a ``fatal`` recorder) with
``PuzzleRoom``'s signature from ``BUNDLED`` (no Loader L), a real F21 ``CodexView`` over
``LedgerCodexPort`` on Template R's codex, the fixture images (``tests/fixtures/F27/images``,
read by the host's ``image`` port), dev on.

``open`` starts a fresh session (a cut, ``restored``, unless a row needs the fade) at given
args and held items, reached by keys unless ``by`` says otherwise; ``g.finishes`` records each
``ctx.finish`` and ``w.images`` each ``ctx.image`` name.
"""

import dataclasses
import threading
from types import MappingProxyType

import pygame

from engine.core.config_schema import ThemeConfig
from engine.core.paths import GamePaths
from engine.minigames import api
from engine.minigames.bundled import BUNDLED
from engine.minigames.bundled.puzzle_room import PuzzleRoom
from engine.minigames.host import HostPorts, MinigameHost, Phase
from engine.minigames.registry import Registry
from engine.runtime.codex import CodexIndex
from engine.runtime.commands import MinigameBase, MinigameDone, StartMinigame
from engine.runtime.minigame import entry_check
from engine.runtime.points import Points
from engine.ui.nav import InputKind
from tests.fakes.ui_shell import SolidScreen, UiHarness
from tests.fixtures.F27 import rooms
from tests.minigames.host_u import ITEMS, TIPS, AudioSpy, CueSpy, HostShell, entry
from tests.render.conftest import make_assets

H = UiHarness
SID = "main.vns:10"
WHERE = ("script/main.vns", 10)
ACTIVATE = "sfx/activate.ogg"
ENTRY = api.declarations(next(c for c in BUNDLED if c is PuzzleRoom), "engine")
INDEX = CodexIndex(tuple(entry(name, "item", rooms.TITLES[name]) for name in rooms.ITEMS)
                   + (entry("lanterns", "tip", "Paper Lanterns"),), (ITEMS, TIPS))
POINTS = Points(())


def _sounds() -> ThemeConfig:
    cfg = ThemeConfig()
    return dataclasses.replace(cfg, button=dataclasses.replace(
        cfg.button, focus_sound="sfx/focus.ogg", activate_sound=ACTIVATE))


SOUNDS = _sounds()


class HostR:
    """One Host R world (module docstring)."""

    def __init__(self, *, cfg=SOUNDS, dev=True, reduce_motion=False, config=None,
                 tables=None, entry=ENTRY, index=INDEX) -> None:
        self.registry = Registry(main_thread=threading.get_ident())
        self.registry.add(entry)
        self.assets = make_assets(GamePaths.for_game(rooms.HERE))
        self.shell = HostShell(dev=dev, reduce_motion=reduce_motion, cfg=cfg,
                               assets=self.assets, config=config)
        self.ui = UiHarness(self.shell)
        self.shell.stack.push(SolidScreen((200, 200, 200)))
        self.posted: list = []
        self.fatal: list = []
        self.images: list[str] = []

        def image(name: str):
            self.images.append(name)
            return self.assets.image(rooms.image_file(name))

        self.ports = HostPorts(
            shell=self.shell, lookup=self.registry.get, post=self.posted.append,
            where=lambda sid: WHERE, fatal=self.fatal.append, check_meter=POINTS.spec,
            check_entry=entry_check(index), index=lambda: index, image=image,
            audio=AudioSpy(), cue=CueSpy(), viewport=lambda: (1280, 720), tables=tables,
            main_thread=self.registry.main_thread)
        self.host = MinigameHost(self.ports)

    def command(self, args, held=(), *, seed=42, restored=True, run=1,
                skippable=False) -> StartMinigame:
        base = MinigameBase((), tuple(held), ())
        return StartMinigame(SID, run, "puzzle_room", MappingProxyType(dict(args)), seed, base,
                             skippable, restored, rooms.STORY)

    def open(self, args, held=(), *, by=InputKind.KEYS, cmd=None, frame=True,
             **kwargs) -> PuzzleRoom:
        """A fresh session; with ``frame`` one frame runs (the first update)."""
        self.posted.clear()
        self.images.clear()
        self.shell.stack.last_input = by
        self.host.start(cmd if cmd is not None else self.command(args, held, **kwargs))
        assert not self.fatal, [getattr(f, "format", lambda: f)() for f in self.fatal]
        g = self.session.plugin
        port = self.session.ctx._port
        real = port.finish
        g.finishes = []

        def finish(result):
            g.finishes.append(result)
            return real(result)

        port.finish = finish
        if frame:
            self.frame()
        return g

    def stage(self, name: str, **kwargs) -> PuzzleRoom:
        args, held = rooms.stage(name)
        return self.open(args, held, **kwargs)

    # -- frames --

    def frame(self, *events):
        return self.ui.frame(*events)

    def frames(self, n: int):
        return self.ui.frames(n)

    def px(self, x, y):
        return self.ui.px(x, y)

    @property
    def session(self):
        return self.host.session

    @property
    def scope(self):
        return self.host.session.scope

    @property
    def changes(self) -> tuple:
        """The session ledger's requests so far."""
        return tuple(self.session.ledger.changes)

    def done(self) -> list[MinigameDone]:
        return [e for e in self.posted if isinstance(e, MinigameDone)]

    def used(self) -> list:
        return [e for e in self.posted if type(e).__name__ == "MinigameUsed"]

    def hint(self) -> str:
        return self.session.hint_text

    def running(self) -> bool:
        return self.session is not None and self.session.phase is Phase.RUNNING


def tap(key: int, mod: int = 0) -> tuple:
    return H.key(key, mod), H.key(key, mod, up=True)


def pad(button: int) -> tuple:
    return H.pad(button), H.pad(button, up=True)


def click(pos, button: int = 1) -> tuple:
    return H.down(pos, button), H.up(pos, button)


ENTER, BACKSPACE, TAB = tap(pygame.K_RETURN), tap(pygame.K_BACKSPACE), tap(pygame.K_TAB)
UP, DOWN, LEFT, RIGHT = (tap(k) for k in (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT,
                                          pygame.K_RIGHT))
PAGE_UP, PAGE_DOWN = tap(pygame.K_PAGEUP), tap(pygame.K_PAGEDOWN)
SOUTH, EAST = pad(pygame.CONTROLLER_BUTTON_A), pad(pygame.CONTROLLER_BUTTON_B)
LB, RB = pad(pygame.CONTROLLER_BUTTON_LEFTSHOULDER), pad(pygame.CONTROLLER_BUTTON_RIGHTSHOULDER)
D_UP, D_DOWN, D_LEFT, D_RIGHT = (pad(b) for b in (
    pygame.CONTROLLER_BUTTON_DPAD_UP, pygame.CONTROLLER_BUTTON_DPAD_DOWN,
    pygame.CONTROLLER_BUTTON_DPAD_LEFT, pygame.CONTROLLER_BUTTON_DPAD_RIGHT))


__all__ = ["ACTIVATE", "BACKSPACE", "DOWN", "D_DOWN", "D_LEFT", "D_RIGHT", "D_UP", "EAST",
           "ENTER", "ENTRY", "H", "INDEX", "LB", "LEFT", "PAGE_DOWN", "PAGE_UP", "RB", "RIGHT",
           "SOUNDS", "SOUTH", "TAB", "UP", "HostR", "click", "pad", "tap"]

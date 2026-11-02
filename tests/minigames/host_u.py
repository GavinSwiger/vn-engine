"""Host U (F23 ``06`` §0.3): ``MinigameHost`` and ``MinigameScreen`` on F10's unit canvas (SDL
dummy, offscreen 1280×720, default theme) over a fake in-game screen, with fake ports: a post
sink, ``where(sid)`` → ``("script/main.vns", 9)``, a ``fatal`` recorder, F10's real confirm
screen, an Audio spy, and a cue spy. The plugins are the Probe and Bare (§5), loaded by
Loader L into the test's game folder (the ``import_sandbox`` fixture restores the import
state). Template M's story: meter ``hana`` 0–10, items ``paper_lantern`` and ``coin``, tips
``lanterns`` and ``moon``."""

import sys
from pathlib import Path
from types import MappingProxyType

from engine.core.minigame_types import StoryNames
from engine.core.paths import GamePaths
from engine.minigames.host import HostPorts, MinigameHost
from engine.minigames.loader import PluginLoadJob
from engine.runtime.codex import CodexIndex
from engine.runtime.commands import MeterView, MinigameBase, StartMinigame
from engine.runtime.guard import NO_GUARD
from engine.runtime.minigame import entry_check
from engine.runtime.points import Points
from engine.script.codex import CodexCategory, CodexEntry
from engine.script.points import MeterSpec
from engine.ui.builtin.confirm import ConfirmScreen
from tests.fakes.ui_shell import SolidScreen, TestShell, UiHarness
from tests.minigames.conftest import FIXTURES, write

SID = "main.vns:9"
WHERE = ("script/main.vns", 9)
ITEMS = CodexCategory("item", None, "codex_items")
TIPS = CodexCategory("tip", None, "codex_tips")


def entry(name: str, kind: str, title: str) -> CodexEntry:
    return CodexEntry(name, kind, title, ITEMS if kind == "item" else TIPS, None, (), "s",
                      "script/main.vns", 1)


INDEX = CodexIndex((entry("paper_lantern", "item", "Paper Lantern"),
                    entry("lanterns", "tip", "Paper Lanterns"),
                    entry("coin", "item", "Old Coin"), entry("moon", "tip", "The Moon")),
                   (ITEMS, TIPS))
POINTS = Points((MeterSpec("hana", 0, 10, 0, True),))
NAMES = StoryNames(("hana",), ("paper_lantern", "coin"), ("lanterns", "moon"),
                   (("codex_items", ("paper_lantern", "coin")),))


class HostShell(TestShell):
    """F10's test shell plus what the host asks of ``GameShell``: notices, the confirm,
    and the thumbnail source slot."""

    __test__ = False

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.notices: list[tuple[str, str]] = []
        self.source = None

    def notify(self, text: str, *, kind: str = "info") -> None:
        self.notices.append((kind, text))

    def confirm(self, message, on_yes, *, on_no=None, yes="yes", no="no", by):
        screen = ConfirmScreen(self, message, on_yes, on_no, yes=yes, no=no, by=by)
        self.stack.push(screen)
        return screen

    def set_thumbnail_source(self, fn) -> None:
        self.source = fn


class AudioSpy:
    """F08's ``AudioService`` as the host uses it."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def take_music(self, owner: str):
        self.calls.append(("take_music", owner))
        spy = self

        class Handle:
            def play(self, file, *, loop=True, fadein=0.0, fadeout=0.0, volume=100):
                spy.calls.append(("play", file))

            def stop(self, fadeout=0.0):
                spy.calls.append(("stop", fadeout))

            def release(self):
                spy.calls.append(("release",))

        return Handle()

    def play_ui(self, file: str, *, volume: int = 100, owner: str | None = None) -> None:
        self.calls.append(("play_ui", file, volume, owner))

    def stop_ui(self, fadeout: float, *, owner: str) -> None:
        self.calls.append(("stop_ui", fadeout, owner))


class CueSpy:
    def __init__(self) -> None:
        self.fn = None
        self.sets: list[object] = []

    def set_anchor(self, fn) -> None:
        self.fn = fn
        self.sets.append(fn)


def load_plugins(game: Path, *, dev: bool = True, guard=NO_GUARD, names=("probe", "bare")):
    for name in names:
        write(game, f"minigames/{name}.py", (FIXTURES / f"{name}.py").read_bytes())
    result = PluginLoadJob(GamePaths.for_game(game), guard, dev=dev).run()
    assert result.ok, [e.format() for e in result.errors]
    return result.registry


class HostU:
    """One Host U world. ``start`` sends a ``StartMinigame``; ``frame`` runs one frame."""

    def __init__(self, game: Path, *, dev: bool = True, guard=NO_GUARD, reduce_motion=False,
                 registry=None, focused=True, cfg=None, config=None, tables=None) -> None:
        self.registry = registry if registry is not None else load_plugins(game, dev=dev,
                                                                           guard=guard)
        self.shell = HostShell(dev=dev, reduce_motion=reduce_motion, cfg=cfg, config=config)
        self.ui = UiHarness(self.shell)
        self.scene = SolidScreen((200, 200, 200))
        self.shell.stack.push(self.scene)
        self.posted: list[object] = []
        self.fatal: list[BaseException] = []
        self.audio = AudioSpy()
        self.cue = CueSpy()
        self.focused = focused
        self.read: list[str] = []
        self.ports = HostPorts(
            shell=self.shell, lookup=self.registry.get, post=self.posted.append,
            where=lambda sid: WHERE, fatal=self.fatal.append,
            check_meter=POINTS.spec, check_entry=entry_check(INDEX), index=lambda: INDEX,
            guard=guard, mark_read=self.read.append, audio=self.audio, cue=self.cue,
            focused=lambda: self.focused, viewport=lambda: (1280, 720), tables=tables,
            main_thread=self.registry.main_thread)
        self.host = MinigameHost(self.ports)

    # -- the plugin --

    @property
    def behavior(self):
        cls = self.registry.get("probe").cls
        return sys.modules[cls.__module__].behavior

    @property
    def session(self):
        return self.host.session

    @property
    def screen(self):
        s = self.host.session
        return None if s is None else s.screen

    # -- driving --

    def command(self, name: str = "probe", args=None, *, restored: bool = True, run: int = 1,
                meters=((("hana", 0, 0, 10)),), items=(), tips=()) -> StartMinigame:
        args = {"pairs": 6, "hints": False, "label": ""} if args is None else args
        base = MinigameBase(tuple(MeterView(*m) for m in meters), tuple(items), tuple(tips))
        return StartMinigame(SID, run, name, MappingProxyType(dict(args)), 12345, base, False,
                             restored, NAMES)

    def start(self, name: str = "probe", args=None, **kwargs) -> StartMinigame:
        cmd = self.command(name, args, **kwargs)
        self.host.start(cmd)
        return cmd

    def frame(self, *events):
        return self.ui.frame(*events)

    def frames(self, n: int):
        return self.ui.frames(n)

    def done(self):
        from engine.runtime.commands import MinigameDone
        return [e for e in self.posted if isinstance(e, MinigameDone)]

    def used(self):
        from engine.runtime.commands import MinigameUsed
        return [e for e in self.posted if isinstance(e, MinigameUsed)]

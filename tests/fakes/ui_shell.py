"""A test shell for F10 screens before ``GameShell`` exists (F10 SPEC step 4: "a test shell").

``TestShell`` provides what ``MenuScreen`` needs (``engine.ui.menu_screen.MenuShell``): a real
``ScreenStack``, an ``AssetManager`` without a game folder, the default theme and words, one
``Painter``, ``dev``, ``reduce_motion``, a recording cursor, and ``play_ui`` recording each
sound token. ``UiHarness`` runs frames as ``App`` does (events, ``update(1/60)``, ``draw`` on a
1280×720 canvas, or another window size) and builds synthetic ``UiEvent``s.
"""

import pygame

from engine.core.config_schema import Config, ThemeConfig
from engine.core.geometry import Viewport
from engine.render.canvas import Canvas, RenderQuality
from engine.ui.focus import Box, FocusGroup
from engine.ui.input import UiEvent
from engine.ui.menu_screen import CursorKeeper, MenuScreen
from engine.ui.paint import Painter
from engine.ui.screen import Screen, ScreenStack
from engine.ui.theme import UiTheme, Words, plain_theme
from engine.ui.widgets import Button
from tests.render.conftest import make_assets

DT = 1 / 60
CANVAS = (1280, 720)


class TestShell:
    __test__ = False                       # not a pytest class

    def __init__(self, *, assets=None, theme: UiTheme | None = None, dev: bool = True,
                 reduce_motion: bool = False, cfg: ThemeConfig | None = None,
                 config: Config | None = None) -> None:
        self.stack = ScreenStack()
        self.assets = assets if assets is not None else make_assets(None)
        self.config = config or Config()
        self.theme = theme or plain_theme(cfg if cfg is not None else self.config.theme)
        self.words = Words(self.config.words)
        self.painter = Painter(self.theme)
        self.dev = dev
        self.reduce_motion = reduce_motion
        self.cursor_calls: list[bool] = []
        self.cursor = CursorKeeper(self.cursor_calls.append)
        self.sounds: list[str | None] = []

    def play_ui(self, token: str | None) -> None:
        self.sounds.append(token)


class UiHarness:
    """Frames and events for a ``TestShell``'s stack, drawn on a real canvas."""

    def __init__(self, shell: TestShell, *, window: tuple[int, int] = CANVAS) -> None:
        self.shell = shell
        self.canvas = Canvas(shell.assets)
        self.resize(window)

    def resize(self, window: tuple[int, int],
               quality: RenderQuality = RenderQuality.FINAL) -> None:
        self.window = window
        self.framebuffer = pygame.Surface(window)
        self.viewport = Viewport.compute(CANVAS, window)
        self.quality = quality

    # -- frames --

    def frame(self, *events: UiEvent, background=(0, 0, 0)) -> pygame.Surface:
        """One frame: events, update, draw. Returns the framebuffer."""
        for event in events:
            self.shell.stack.handle_event(event)
        self.shell.assets.time.advance(DT if self.shell.assets.time.frame else None)
        self.shell.stack.update(DT)
        self.framebuffer.fill(background)
        self.canvas.bind(self.framebuffer, self.viewport, self.quality)
        self.shell.stack.draw(self.canvas)
        return self.framebuffer

    def frames(self, n: int, background=(0, 0, 0)) -> pygame.Surface:
        for _ in range(n):
            self.frame(background=background)
        return self.framebuffer

    def px(self, x: float, y: float) -> tuple[int, int, int]:
        """The framebuffer color at canvas point (x, y)."""
        dx, dy = self.canvas.px(x, y)
        return tuple(self.framebuffer.get_at((dx + self.viewport.x, dy + self.viewport.y)))[:3]

    # -- events (canvas units; the window position equals the canvas position at 1280×720) --

    @staticmethod
    def key(key: int, mod: int = 0, *, up: bool = False) -> UiEvent:
        kind = pygame.KEYUP if up else pygame.KEYDOWN
        return UiEvent(pygame.event.Event(kind, key=key, mod=mod), None, False)

    @staticmethod
    def pad(button: int, *, up: bool = False) -> UiEvent:
        kind = pygame.CONTROLLERBUTTONUP if up else pygame.CONTROLLERBUTTONDOWN
        return UiEvent(pygame.event.Event(kind, button=button, instance_id=0), None, False)

    @staticmethod
    def motion(pos, *, in_canvas: bool = True) -> UiEvent:
        pos = (round(pos[0]), round(pos[1]))
        return UiEvent(pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(0, 0, 0)),
                       pos if in_canvas else None, in_canvas)

    @staticmethod
    def down(pos, button: int = 1, *, in_canvas: bool = True) -> UiEvent:
        pos = (round(pos[0]), round(pos[1]))
        return UiEvent(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button),
                       pos if in_canvas else None, in_canvas)

    @staticmethod
    def up(pos, button: int = 1, *, in_canvas: bool = True) -> UiEvent:
        pos = (round(pos[0]), round(pos[1]))
        return UiEvent(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=button),
                       pos if in_canvas else None, in_canvas)

    @staticmethod
    def wheel(pos, y: int) -> UiEvent:
        pos = (round(pos[0]), round(pos[1]))
        return UiEvent(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=y, flipped=False), pos, True)

    def click(self, pos) -> None:
        """Button-1 down and up at ``pos`` in one frame."""
        self.frame(self.down(pos), self.up(pos))


class ColumnMenu(MenuScreen):
    """A test ``MenuScreen``: one column of buttons B1..Bn at (100, 100 + 68·i, 320, 56),
    default B1, each counting its activations; ``disabled`` holds 0-based indices. Records
    every event it receives in ``received``; ``on_activate[i]`` runs after B(i+1)'s count."""

    def __init__(self, shell, *, by, n: int = 3, disabled=(), fade: bool = True,
                 backdrop=None) -> None:
        self.counts = [0] * n
        self.received: list = []
        self.on_activate: dict[int, object] = {}
        self.buttons = [
            Button(lambda i=i: f"B{i + 1}", lambda i=i: self.hit(i),
                   enabled=(lambda: False) if i in disabled else None)
            for i in range(n)]
        super().__init__(shell, by=by, fade=fade, backdrop=backdrop)

    def hit(self, i: int) -> None:
        self.counts[i] += 1
        action = self.on_activate.get(i)
        if action is not None:
            action()

    def box(self, i: int) -> Box:
        return Box(100, 100 + 68 * i, 320, 56)

    def center(self, i: int) -> tuple[float, float]:
        return self.box(i).center

    def build(self) -> None:
        for i, button in enumerate(self.buttons):
            button.box = self.box(i)
        self.scope.set_groups([FocusGroup(self.buttons, column=True)])
        self.scope.default_widget = self.buttons[0]

    def handle_event(self, event) -> bool:
        self.received.append(event)
        return super().handle_event(event)


class SolidScreen(Screen):
    """An in-game stand-in that fills the canvas with ``color`` (the "scene" under menus)."""

    in_game = True

    def __init__(self, color=(200, 200, 200)) -> None:
        self.color = color
        self.draws = 0
        self.received: list = []

    def draw(self, canvas) -> None:
        self.draws += 1
        canvas.fill(self.color)

    def handle_event(self, event) -> bool:
        self.received.append(event)
        return False

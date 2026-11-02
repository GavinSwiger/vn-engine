"""Build an ``App`` around a ``FakeWindow`` and a scripted limiter, plus a drawing test screen."""

from collections.abc import Callable

from engine.app.app import App
from engine.core.config_schema import Config, WindowConfig
from engine.core.constants import MB
from engine.core.paths import GamePaths
from engine.core.timing import GameTime
from engine.render.assets import AssetManager
from engine.render.canvas import Canvas
from tests.fakes.fake_window import FakeWindow
from tests.fakes.loop import FakeClock, ScriptedLimiter

LETTERBOX = (0x12, 0x34, 0x56)


def make_app(window: FakeWindow, *, config: Config | None = None, fps: int = 60,
             cache_mb: int = 512, paths: GamePaths | None = None,
             scale_filter: str = "smooth") -> tuple[App, ScriptedLimiter]:
    config = config or Config(window=WindowConfig(letterbox_color=LETTERBOX))
    clock = FakeClock()
    limiter = ScriptedLimiter(clock, fps)
    assets = AssetManager(paths, budget_bytes=cache_mb * MB, scale_filter=scale_filter,
                          time=GameTime(), format_source=window.framebuffer)
    app = App(config=config, paths=paths, window=window, assets=assets, log=None, dev=True,
              bench_seconds=None, clock=clock, limiter=limiter)
    return app, limiter


class DrawingScreens:
    """Stands in for the Step 8 screen stack: one opaque screen that calls ``draw`` with
    the canvas and the frame number every frame."""

    opaque = True

    def __init__(self, draw: Callable[[Canvas, int], None]) -> None:
        self._draw = draw
        self.frames = 0

    def __iter__(self):
        return iter([self])

    def update(self, dt: float) -> None:
        pass

    def draw(self, canvas: Canvas) -> None:
        self.frames += 1
        self._draw(canvas, self.frames)

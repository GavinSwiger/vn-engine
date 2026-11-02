"""App A for F05 (``06-acceptance.md`` §0.2): the real ``App`` loop on a ``FakeWindow``, a fake
clock stepping exactly 1/60 s per frame, the game started through ``install_story`` (via the
story load screen), and input injected as pygame events in the event phase.

A test is a generator ``script(session)``: the session advances it once per frame, before the
frame's events are read, so whatever it posts arrives in that frame, and after each ``yield``
the framebuffer still holds the frame presented last. ``Session.play`` runs the loop until
the script returns (or ``last`` frames pass).

Game folders are written to ``tmp_path`` from the F05 template (``tests/fixtures/F05/
template``, §0.4) with ``S``/``T``/``D`` substitutions, so the fixture folder never gets a
``logs/``.
"""

import shutil
from collections.abc import Callable, Generator
from pathlib import Path

import pygame

from engine.app import bootstrap
from engine.app.app import App
from engine.app.loading import story_load_screen
from engine.core.config import load_config
from engine.core.constants import MB
from engine.core.paths import GamePaths
from engine.core.timing import GameTime
from engine.render.assets import AssetManager
from engine.runtime.commands import Advance, Say
from tests.fakes.fake_window import FakeWindow
from tests.fakes.loop import FakeClock, ScriptedLimiter

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "tests" / "fixtures" / "F05" / "template"
NO_TITLE = "[title]\nenabled = false\n"


def make_text_game(root: Path, *, S: str = "x", D: str | None = None, T: str = "",
                   config: str = "", script: str | None = None) -> Path:
    """Template X (§0.4) in ``root``: ``S`` is line 7's text, ``D`` (when given) replaces
    line 7 with a whole statement, ``T`` goes on line 9; ``⏎`` starts a new line. ``script``
    replaces the whole script. The title is off so the story starts at launch."""
    shutil.copytree(TEMPLATE, root)
    main = root / "script" / "main.vns"
    if script is None:
        text = main.read_text(encoding="utf-8")
        line7 = f"    {D}" if D is not None else f'    "{S}"'
        text = text.replace('    "<S>"', line7.replace("⏎", "\n")).replace(
            "<T>", T.replace("⏎", "\n"))
    else:
        text = script
    main.write_text(text, encoding="utf-8")
    (root / "config.toml").write_text(NO_TITLE + config, encoding="utf-8")
    return root


class Session:
    """One App A run. ``posted`` records every ``Advance`` the textbox posts, with its frame;
    ``said`` every ``Say`` the textbox receives, with its frame."""

    def __init__(self, root: Path, *, size: tuple[int, int] = (1280, 720), dev: bool = True
                 ) -> None:
        self.paths = GamePaths.for_game(root)
        config = load_config(self.paths).config
        self.window = FakeWindow(size)
        self.clock = FakeClock()
        self.limiter = ScriptedLimiter(self.clock)
        self.assets = AssetManager(self.paths, budget_bytes=256 * MB, scale_filter="smooth",
                                   time=GameTime(), format_source=self.window.framebuffer)
        self.app = App(config=config, paths=self.paths, window=self.window,
                       assets=self.assets, log=None, dev=dev, bench_seconds=None,
                       clock=self.clock, limiter=self.limiter)
        self.app.screens.replace_all([story_load_screen(
            self.app, self.paths, on_ready=bootstrap.build_initial_screens)])
        self.posted: list[tuple[int, Advance]] = []
        self.said: list[tuple[int, Say]] = []

    # -- running --

    def play(self, script: Callable[["Session"], Generator], *, last: int = 2000) -> int:
        gen = script(self)
        done = []

        def step() -> None:
            install_spies()
            if done:
                return
            try:
                next(gen)
            except StopIteration:
                done.append(True)
                self.app.request_quit(force=True)

        for frame in range(1, last):
            self.limiter.at(frame, step)
        self.limiter.at(last, lambda: self.app.request_quit(force=True))
        real_post = None

        def install_spies() -> None:
            nonlocal real_post
            story = self.app.story
            textbox = self.app.textbox
            if story is None or textbox is None or real_post is not None:
                return
            real_post = story.post

            def post(event):
                if isinstance(event, Advance):
                    self.posted.append((self.frame, event))
                real_post(event)

            story.post = post
            real_show = textbox.show

            def show(cmd):
                self.said.append((self.frame, cmd))
                real_show(cmd)

            self.app.router._handlers[Say] = show

        code = self.app.run()
        assert done, "the script did not finish"
        return code

    # -- state --

    @property
    def frame(self) -> int:
        return self.limiter.frame

    @property
    def textbox(self):
        return self.app.textbox

    @property
    def fb(self) -> pygame.Surface:
        return self.window.framebuffer()

    def px(self, x: int, y: int) -> tuple[int, int, int]:
        """The last presented frame's color at window pixel (x, y)."""
        return tuple(self.fb.get_at((x, y)))[:3]

    def snapshot(self) -> bytes:
        return pygame.image.tobytes(self.fb, "RGB")

    # -- input (posted now, read in this frame's event phase) --

    @staticmethod
    def key(key: int, mod: int = 0) -> None:
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod, unicode="",
                                             scancode=0))

    @staticmethod
    def key_up(key: int) -> None:
        pygame.event.post(pygame.event.Event(pygame.KEYUP, key=key, mod=0, unicode="",
                                             scancode=0))

    @staticmethod
    def mouse(pos: tuple[int, int], button: int = 1, *, up: bool = False) -> None:
        kind = pygame.MOUSEBUTTONUP if up else pygame.MOUSEBUTTONDOWN
        pygame.event.post(pygame.event.Event(kind, pos=pos, button=button, touch=False))

    @staticmethod
    def event(kind: int, **attrs) -> None:
        pygame.event.post(pygame.event.Event(kind, **attrs))

    # -- waiting --

    def until(self, predicate: Callable[[], bool], limit: int = 600) -> Generator:
        """Yield frames until ``predicate()`` holds (checked before each yield)."""
        for _ in range(limit):
            if predicate():
                return
            yield
        raise AssertionError("condition not reached")

    def line_text(self) -> str | None:
        textbox = self.app.textbox
        return None if textbox is None or textbox.line is None else textbox.line.text

    def until_line(self, text: str, limit: int = 600) -> Generator:
        yield from self.until(lambda: self.line_text() == text, limit)


__all__ = ["Session", "make_text_game"]

"""PlaceholderScreen (§7.16): AC-F01-97 and the AC-F01-37 bar/canvas pixels."""

import shutil
from pathlib import Path

import pytest

from engine import __version__
from engine.core.config import load_config
from engine.core.config_schema import Config, WindowConfig
from engine.core.paths import GamePaths
from engine.ui.builtin.placeholder import PlaceholderScreen
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import make_app

pytestmark = pytest.mark.display

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "F01"
BG = (0x20, 0x20, 0x20)


def fixture_config(tmp_path: Path, *, game: str | None = None,
                   config_file: str | None = None) -> Config:
    root = tmp_path / "game"
    if game is not None:
        shutil.copytree(FIXTURES / "games" / game, root, ignore=shutil.ignore_patterns("logs"))
    else:
        root.mkdir(parents=True)
        shutil.copy(FIXTURES / "config" / config_file, root / "config.toml")
    result = load_config(GamePaths.for_game(root))
    assert result.errors == []
    return result.config


def run_placeholder(config: Config, size, probes=(), frames: int = 1):
    window = FakeWindow(size, probe_points=probes)
    app, limiter = make_app(window, config=config)
    app.screens.push(PlaceholderScreen(title=config.game.title, engine_version=__version__))
    limiter.quit_at(frames)
    assert app.run() == 0
    return window


def test_placeholder_layout(tmp_path, monkeypatch):
    config = fixture_config(tmp_path, game="minimal")
    with spy_draw_text(monkeypatch) as calls:
        window = run_placeholder(config, (1280, 720), [(5, 5), (1275, 5), (5, 715)])
    for point in [(5, 5), (1275, 5), (5, 715)]:
        assert window.flips[0].probes[point] == BG
    title = next(c for c in calls if c.text == "Fixture Game")
    assert title.font.ref is None and title.font.size == 48
    assert title.color == (224, 224, 224)
    assert title.options["max_width"] == 1120 and title.options["max_lines"] == 2
    assert title.options["align"] == "center"
    x, y, w, h = title.bounds
    assert abs(x + w / 2 - 640) <= 1 and abs(y + h / 2 - 360) <= 1
    version = next(c for c in calls if __version__ in c.text)
    assert "9.9.9" not in version.text
    assert version.font.ref is None and version.font.size == 20
    assert version.color == (160, 160, 160)
    assert version.options["anchor"] == "bottomright" and version.pos == (1264, 704)


def test_default_letterbox_differs_from_the_canvas(tmp_path):
    config = fixture_config(tmp_path, game="minimal")
    window = run_placeholder(config, (1920, 1200), [(960, 30), (100, 600)])
    assert window.flips[0].probes[(960, 30)] == (0, 0, 0)
    assert window.flips[0].probes[(100, 600)] == BG


@pytest.mark.parametrize("config_file", ["long_title.toml", "long_word_title.toml"])
def test_long_titles_use_two_lines(tmp_path, monkeypatch, config_file):
    config = fixture_config(tmp_path, config_file=config_file)
    with spy_draw_text(monkeypatch) as calls:
        window = run_placeholder(config, (1280, 720))
    title = next(c for c in calls if c.font.size == 48)
    x, y, w, h = title.bounds
    assert 80 <= x and x + w <= 1200
    surface = window.framebuffer()
    for px in list(range(0, 80)) + list(range(1201, 1280)):
        for py in range(0, 600, 7):
            assert tuple(surface.get_at((px, py)))[:3] == BG, (px, py)


def test_long_title_lines_end_with_an_ellipsis(tmp_path):
    from engine.render.canvas import Canvas
    from engine.render.text import FontSpec
    from tests.render.conftest import make_assets

    for config_file in ("long_title.toml", "long_word_title.toml"):
        config = fixture_config(tmp_path / config_file, config_file=config_file)
        canvas = Canvas(make_assets(None))
        lines = canvas.layout_lines(config.game.title, FontSpec(None, 48), 1120, 2)
        assert len(lines) == 2 and lines[1].endswith("…")


# --- AC-F01-37: rendered bars and canvas ---------------------------------------------------

@pytest.mark.parametrize("size, bars, canvas", [
    ((1920, 1200), [(960, 30), (960, 59), (960, 1140), (960, 1199)],
     [(960, 60), (0, 60), (1919, 1139)]),
    ((2560, 1080), [(319, 540), (2240, 540)], [(320, 0), (2239, 1079)]),
])
def test_rendered_bars_and_canvas(size, bars, canvas):
    config = Config(window=WindowConfig(letterbox_color=(0x12, 0x34, 0x56)))
    window = run_placeholder(config, size, bars + canvas)
    probes = window.flips[0].probes
    for point in bars:
        assert probes[point] == (0x12, 0x34, 0x56), point
    for point in canvas:
        assert probes[point] == BG, point


# --- AC-F01-157 (d): a live resize of the placeholder creates no font size or text line ---------

def test_resize_settle_on_the_placeholder_adds_no_font_or_text():
    window = FakeWindow((1920, 1080))
    app, limiter = make_app(window, fps=20)                  # frames 50 ms apart
    app.screens.push(PlaceholderScreen(title="Fixture Game", engine_version=__version__))
    sizes = [(1000 + 23 * i, 600 + 11 * i) for i in range(30)]
    marks = {}

    def keys():
        return {k for k in app.assets.cache.keys() if k[0] in ("font", "text")}

    limiter.at(3, lambda: marks.update(before=keys()))
    for index, size in enumerate(sizes):
        limiter.at(3 + index, lambda s=size: window.resize(*s))
    last = 3 + len(sizes) - 1
    limiter.at(last + 1, lambda: marks.update(after=keys()))
    limiter.at(last + 6, lambda: marks.update(final=keys()))   # 0.25 s later: FINAL again
    limiter.quit_at(last + 6)
    app.run()
    assert marks["after"] == marks["before"]
    new_fonts = {k for k in marks["final"] - marks["after"] if k[0] == "font"}
    assert len(new_fonts) <= 2                                # two FontSpecs are drawn

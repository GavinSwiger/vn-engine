"""F22 step 3: the meters on the F3 overlay (AC-F22-08; UI-F22-01, 07 I-10)."""

import re

import pygame
import pytest

from engine.app.points import install_points
from engine.render import overlay
from engine.ui.builtin.placeholder import PlaceholderScreen
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import make_app
from tests.runtime.effects_story import launched, story_game

pytestmark = pytest.mark.display

FPS = r"\d+ FPS \| \d+\.\d ms"


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def interp_for(root, top: str, *, start: bool = True):
    interp = launched(story_game(root, ['hana "Hi."'], top=top))
    if start:
        interp.new_game(42)
        interp.run(10_000)
    return interp


def overlay_frames(monkeypatch, interp, *, dev=True, on=True, extra=None, at=None, frames=4):
    """The overlay's text per flip (frame number → texts, top to bottom)."""
    window = FakeWindow()
    app, limiter = make_app(window)
    app.dev, app.overlay_on = dev, on
    app.screens.push(PlaceholderScreen(title="Test", engine_version="0.1.0"))
    install_points(app, interp)
    if extra is not None:
        app.overlay_lines.append(extra)
    for frame, fn in (at or {}).items():
        limiter.at(frame, fn)
    seen: dict[int, list[str]] = {}
    with spy_draw_text(monkeypatch) as calls:
        def on_flip(w):
            mine = [c for c in calls if c.font == overlay.FONT and c.pos[0] == 8]
            assert [c.pos[1] for c in mine] == sorted(c.pos[1] for c in mine)
            seen[len(w.flips)] = [c.text for c in mine]
            calls.clear()

        window.on_flip = on_flip
        limiter.quit_at(frames)
        app.run()
    return app, seen


def test_ac08_overlay_lists_meters(monkeypatch, tmp_path):
    # Dev, on: the FPS line, then one line per meter; the range only when declared; a change
    # shows on the next frame.
    interp = interp_for(tmp_path / "two", "points hana 0 to 10 start 3\npoints daichi\n")
    _, seen = overlay_frames(monkeypatch, interp,
                             at={3: lambda: interp.points.add("hana", 2)})
    for frame, (hana, daichi) in ((1, ("hana 3 (0-10)", "daichi 0")),
                                  (2, ("hana 3 (0-10)", "daichi 0")),
                                  (3, ("hana 5 (0-10)", "daichi 0"))):
        fps, *rest = seen[frame]
        assert re.fullmatch(FPS, fps) and rest == [hana, daichi], seen[frame]

    # 15 meters: 12 lines, then "+3 more".
    names = [f"m{i}" for i in range(15)]
    interp = interp_for(tmp_path / "many", "points " + " ".join(names) + "\n")
    _, seen = overlay_frames(monkeypatch, interp, frames=2)
    assert seen[1][1:] == [f"m{i} 0" for i in range(12)] + ["+3 more"]

    # No meters, or no game yet: the FPS line only.
    for interp in (interp_for(tmp_path / "none", ""),
                   interp_for(tmp_path / "idle", "points hana\n", start=False)):
        _, seen = overlay_frames(monkeypatch, interp, frames=2)
        assert len(seen[1]) == 1 and re.fullmatch(FPS, seen[1][0])

    # Off, or a release run: no provider is ever called (release adds none).
    for dev, on in ((True, False), (False, True)):
        called = []
        interp = interp_for(tmp_path / f"{dev}{on}", "points a\n")
        app, seen = overlay_frames(monkeypatch, interp, dev=dev, on=on,
                                   extra=lambda: called.append(1) or ["x"])
        assert called == [] and all(texts == [] for texts in seen.values())
        assert len(app.overlay_lines) == (2 if dev else 1)          # the spy, + meters in dev


def test_f62_rank_on_the_overlay_and_the_notice_handler(monkeypatch, tmp_path):
    # A meter with ranks shows its rank ("-" below the first).
    interp = interp_for(tmp_path / "ranks", 'points hana 0 to 10 ranks "Friend" 4\n')
    _, seen = overlay_frames(monkeypatch, interp, frames=3,
                             at={2: lambda: interp.points.add("hana", 5)})
    assert seen[1][1:] == ["hana 0 (0-10) -"] and seen[2][1:] == ["hana 5 (0-10) Friend"]
    # MeterNotice → shell.notify, in every launch (none before the shell exists).
    from engine.runtime.commands import MeterNotice
    for dev in (True, False):
        app, _ = make_app(FakeWindow())
        app.dev = dev
        install_points(app, interp)
        app.router.dispatch(MeterNotice("hana", "Hana will remember that."))   # no shell yet
        told = []
        app.shell = type("Shell", (), {"notify": lambda self, text: told.append(text)})()
        app.router.dispatch(MeterNotice("hana", "Hana will remember that."))
        assert told == ["Hana will remember that."]

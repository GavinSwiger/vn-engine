"""``App.add_shutdown``: hooks run once after ``run`` ends, in reverse order, each on its own;
and F04's ``ImagePrefetcher`` (built by ``install_stage``) is stopped there."""

import logging

import pygame
import pytest

from tests.app.test_stage_wiring import Played, make_game
from tests.fixtures.F04 import gen_images as gen


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def test_the_prefetchers_thread_is_stopped_after_run(tmp_path):
    root = make_game(tmp_path / "g", 'label start:\n    "One."\n    scene bg room\n'
                     '    "Two."\n', {"images/bg/room.png": gen.block(1280, 720, gen.GREEN)})
    threads = []

    def note(p: Played) -> None:
        stage = getattr(p.app, "stage_screen", None)
        worker = stage.view.prefetcher.worker if stage is not None else None
        if worker is not None and worker not in threads:
            threads.append(worker)

    played = Played(root, last=30, on_frame=note)
    assert played.code == 0
    assert threads, "the look-ahead never started the decode thread"
    assert all(not t.is_alive() for t in threads)
    assert played.app.stage_screen.view.prefetcher.worker is None


def test_hooks_run_in_reverse_order_and_a_failure_skips_none(tmp_path, caplog):
    root = make_game(tmp_path / "g", 'label start:\n    "One."\n')
    calls: list[str] = []

    def failing() -> None:
        calls.append("failing")
        raise RuntimeError("boom")

    def on_frame(p: Played) -> None:
        if not calls and p.limiter.frame == 1:
            p.app.add_shutdown(lambda: calls.append("first"))
            p.app.add_shutdown(failing)
            p.app.add_shutdown(lambda: calls.append("last"))
            calls.append("added")

    with caplog.at_level(logging.WARNING, logger="vn"):
        played = Played(root, last=5, on_frame=on_frame)
    assert played.code == 0
    assert calls == ["added", "last", "failing", "first"]
    assert any("shutdown step failed" in r.getMessage() for r in caplog.records)

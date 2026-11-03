"""F47 P1-E: the real helper child through Studio's ``HelperRunner`` (``04`` §7.3, §8, §11).
AC-F47-21. One subprocess run; the runner's protocol edges are in
``tests/tools/editor/test_helperrunner.py`` with a fake child."""

import base64
import os
import shutil
import time
from pathlib import Path

import pytest

import engine.__main__ as engine_main
from engine.app import cli
from engine.tools.editor.helperrunner import HelperRunner
from tests.tools.f45_games import studio

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _tree(game: Path) -> dict:
    return {path.relative_to(game).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in sorted(game.rglob("*")) if path.is_file()}


def _wait(runner: HelperRunner, count: int, seconds: float = 30.0) -> list:
    events: list = []
    end = time.monotonic() + seconds
    while len(events) < count and time.monotonic() < end:
        events.extend(runner.poll())
        time.sleep(0.01)
    assert len(events) >= count, events
    return events


def _png(reply) -> bytes:
    data = base64.b64decode(reply.data, validate=True)
    assert data.startswith(PNG_SIGNATURE)
    return data


def test_ac_f47_21_jpeg_and_webp_thumbnails_come_from_the_helper_cached(tmp_path):
    game = studio(tmp_path)
    shutil.copy(FIXTURES / "F01" / "games" / "assets" / "images" / "lossy.webp",
                game / "images" / "bg" / "dusk.webp")
    (game / "audio" / "sound").mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "docgame" / "audio" / "sfx" / "chime.wav",
                game / "audio" / "sound" / "chime.wav")
    before = _tree(game)
    runner = HelperRunner(game)
    try:
        # JPEG and WebP thumbnails: asked once, answered by the child, then cached.
        jpeg, webp = "images/bg/photo.jpg", "images/bg/dusk.webp"
        assert runner.thumb(jpeg, 96) is None and runner.thumb(webp, 96) is None
        assert runner.thumb(jpeg, 96) is None                    # in flight: not asked again
        started = time.perf_counter()
        replies = {reply.ref: reply for reply in _wait(runner, 2)}
        first_seconds = time.perf_counter() - started            # includes the child's start
        for ref in (jpeg, webp):
            reply = replies[ref]
            assert reply.ok and reply.op == "thumb", reply
            assert max(reply.width, reply.height) <= 96
            _png(reply)
        assert runner.thumb(jpeg, 96) is replies[jpeg] and not runner.busy
        # A changed file is asked again; a missing one fails with a reason, also cached.
        assert _tree(game) == before
        os.utime(game / "images" / "bg" / "photo.jpg", ns=(1, 1))
        before = _tree(game)
        assert runner.thumb(jpeg, 96) is None
        assert runner.thumb("images/bg/none.jpg", 96) is None
        again = {reply.ref: reply for reply in _wait(runner, 2)}
        assert again[jpeg].ok and not again["images/bg/none.jpg"].ok
        assert again["images/bg/none.jpg"].reason
        assert runner.thumb("images/bg/none.jpg", 96) is again["images/bg/none.jpg"]

        # The same child draws stills from unsaved config text and plays sounds.
        started = time.perf_counter()
        runner.still("textbox", 640, b'[theme.textbox]\ntext_size = 32\n')
        (still,) = _wait(runner, 1)
        still_seconds = time.perf_counter() - started
        assert (still.ok, still.width, still.height, still.kind) == (True, 640, 360, "textbox")
        _png(still)
        runner.still("title", 320, b"[game\n")
        (broken,) = _wait(runner, 1)
        assert not broken.ok and broken.reason and str(game) not in broken.reason
        runner.play("audio/sound/chime.wav")
        (played,) = _wait(runner, 1)
        assert played.ok and played.op == "play" and played.seconds > 0
        runner.stop_sound()
        (stopped,) = _wait(runner, 1)
        assert stopped.ok and stopped.op == "stop"
        print(f"first thumbnails {first_seconds:.3f} s (cold start), "
              f"warm still {still_seconds:.3f} s")
        process = runner.process
    finally:
        runner.stop()
    assert process is not None and process.returncode == 0
    assert _tree(game) == before                                 # writes nothing
    with pytest.raises(SystemExit) as refused:                   # dev runs only
        cli.main(["helper", str(game), "--release"], helper=engine_main._helper)
    assert refused.value.code == 2

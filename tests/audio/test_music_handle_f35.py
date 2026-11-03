"""F35 step 1 — F08's ``MusicHandle`` options for the music room: AC-F35-05 (``play(start=)``,
``length()``) on Service S (FakeMixer, fake clock)."""

import pytest

from tests.audio.conftest import make_service
from tests.fakes.fake_mixer import ogg_bytes

LONG, OMEN = "bgm/long.ogg", "bgm/omen.ogg"                 # 60 s, 3 s


def test_ac05_play_start_and_length(tmp_path):
    s = make_service(tmp_path)
    s.add(LONG, ogg_bytes(60.0, salt=b"long"), 60.0)
    handle = s.service.take_music("music_room")
    assert handle.length() is None                          # nothing read yet

    handle.play(LONG, start=12.0, fadeout=0.0)
    starts = [args for _t, name, args in s.mixer.calls if name == "music_start"]
    assert starts[-1][:3] == (LONG, -1, 12.0)
    assert handle.length() == pytest.approx(60.0)           # read: its header's length
    s.run(0.5)
    assert handle.position() == pytest.approx(12.5, abs=0.02)

    handle.play(LONG, start=0.0, fadeout=0.0)               # start= restarts the same track
    assert handle.position() == pytest.approx(0.0, abs=0.02)
    s.run(0.5)
    handle.play(LONG, fadeout=0.0)                          # no start: it goes on (SR-F08-07)
    s.run(0.5)
    assert handle.position() == pytest.approx(1.0, abs=0.02)

    handle.stop(fadeout=0.0)                                # silent: no length
    assert handle.length() is None and handle.position() is None

    handle.play(OMEN, fadeout=0.0)
    assert handle.length() == pytest.approx(3.0)
    handle.release()                                        # inert: None, plays nothing
    assert handle.length() is None
    handle.play(LONG, start=5.0)
    handle.stop(None)
    assert not s.service.music_taken()

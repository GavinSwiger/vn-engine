"""Broken files and restored paths on Service S (F08 ``06`` §1.5; ``04`` §7.4, §12; ``02``
§5.4 W26, W29): AC-F08-37 (broken and oversized files play as silence, one W26 each) and
AC-F08-39 (paths from a restored state, W29). The effect rows of AC-37 that step 4 could run
are in ``test_reading.py``; these add music and voice, the did-you-mean (F01's suggestion,
``04`` §7.4), the unreadable file, and the restore paths."""

import logging
import os
import sys
from pathlib import Path

import pytest

from engine.audio.limits import MUSIC_MAX_BYTES, SOUND_MAX_BYTES
from engine.core.paths import REASON_OUTSIDE, REASON_TOO_LONG, GamePaths
from engine.runtime.audio import AudioState, MusicEntry, SoundLoop
from engine.runtime.commands import AudioRestore, PlayMusic, PlaySound, PlayVoice, Say
from tests.audio.conftest import make_service
from tests.fakes.fake_mixer import flac_bytes, ogg_bytes, wav_bytes

AUDIO_LOG = "vn.audio"
FESTIVAL, RAIN = "bgm/festival.ogg", "sfx/rain.ogg"


def PM(file) -> PlayMusic:
    return PlayMusic(file, True, 100, None, None, False, None, False)


def play(channel: str, file: str):
    if channel == "music":
        return PM(file)
    if channel == "voice":
        return PlayVoice("s1", file, False)
    return PlaySound(file, False, 100, None)


def records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == AUDIO_LOG]


def silent(s) -> bool:
    return s.mixer.music_name() is None and not s.mixer.busy_channels()


@pytest.fixture
def s(tmp_path):
    return make_service(tmp_path)


@pytest.fixture
def audio_log(caplog):
    caplog.set_level(logging.DEBUG, logger=AUDIO_LOG)
    return caplog


@pytest.fixture
def reads(monkeypatch):
    """Every ``GamePaths.read_file`` call as ``(ref, max_bytes)``."""
    seen: list[tuple[str, int]] = []
    real = GamePaths.read_file

    def spy(self, ref, *, max_bytes):
        seen.append((ref, max_bytes))
        return real(self, ref, max_bytes=max_bytes)

    monkeypatch.setattr(GamePaths, "read_file", spy)
    return seen


# --- AC-F08-37 — Broken and oversized files play as silence (W26) ---------------------------------

CHANNELS = ("music", "sound", "voice")


def services(tmp_path):
    """``(channel, a fresh Service S)`` for music, sound, and voice."""
    for channel in CHANNELS:
        (tmp_path / channel).mkdir()
        yield channel, make_service(tmp_path / channel)


def test_ac_f08_37_a_missing_file_is_w26_with_did_you_mean_when_one_is_close(tmp_path,
                                                                             audio_log):
    close = {"music": ("bgm/festval.ogg", "bgm/festival.ogg"),
             "sound": ("sfx/rian.ogg", "sfx/rain.ogg"),
             "voice": ("voice/hana_14.ogg", "voice/hana_014.ogg")}
    for channel, s in services(tmp_path):
        audio_log.clear()
        file, suggestion = close[channel]
        s.feed(play(channel, file))
        assert audio_log.messages == [f'audio/{file} is missing, so it plays as silence. Did '
                                      f'you mean "{suggestion}"?'], channel
        assert records(audio_log)[0].levelname == "WARNING", channel
        assert records(audio_log)[0].code == "W26", channel
        s.feed(play(channel, "bgm/zzqx.ogg"))                  # nothing close
        assert audio_log.messages[1:] == ["audio/bgm/zzqx.ogg is missing, so it plays as "
                                          "silence."], channel
        assert silent(s), channel


def _hold_unreadable(path: Path):
    """Keep ``path`` unreadable until the returned function is called: Windows holds it open
    with share mode 0; POSIX sets mode 000."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                         wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                         wintypes.HANDLE)
        handle = kernel32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
        assert handle not in (None, wintypes.HANDLE(-1).value), ctypes.get_last_error()
        return lambda: kernel32.CloseHandle(wintypes.HANDLE(handle))
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file")
    path.chmod(0)
    return lambda: path.chmod(0o644)


def test_ac_f08_37_an_unreadable_file(tmp_path, audio_log):
    files = {"music": FESTIVAL, "sound": RAIN, "voice": "voice/hana_014.ogg"}
    for channel, s in services(tmp_path):
        audio_log.clear()
        file = files[channel]
        release = _hold_unreadable(s.root / "audio" / file)
        try:
            s.feed(play(channel, file))
        finally:
            release()
        assert audio_log.messages == [f"audio/{file} couldn't be read, so it plays as silence. "
                                      f"Check that another program isn't locking it."], channel
        assert silent(s), channel


def test_ac_f08_37_garbage_after_a_valid_header(tmp_path, audio_log):
    for channel, s in services(tmp_path):
        audio_log.clear()
        s.add("broken/garbage.ogg", ogg_bytes(3.0, salt=os.urandom(64)), 3.0)
        s.mixer.fail_decode.add("broken/garbage.ogg")        # SDL refuses what follows
        s.feed(play(channel, "broken/garbage.ogg"))
        s.feed(play(channel, "broken/garbage.ogg"))
        assert audio_log.messages == ["audio/broken/garbage.ogg can't be played: it is damaged "
                                      "or isn't really an Ogg Vorbis file. Export it again as "
                                      ".ogg."], channel
        assert silent(s), channel


def test_ac_f08_37_an_oversized_file(tmp_path, audio_log, reads):
    limits = {"music": MUSIC_MAX_BYTES, "sound": SOUND_MAX_BYTES, "voice": SOUND_MAX_BYTES}
    for channel, s in services(tmp_path):
        audio_log.clear()
        reads.clear()
        limit, file = limits[channel], "big/huge.ogg"
        path = s.root / "audio" / file
        path.parent.mkdir(parents=True)
        with path.open("wb") as out:
            out.write(ogg_bytes(1.0))
            out.truncate(limit + 1)                          # sparse where it can be
        s.feed(play(channel, file))
        assert reads == [("audio/" + file, limit)], channel
        [message] = audio_log.messages
        assert "audio/" + file in message and "silence" in message, channel
        assert s.mixer.actions("decode", "music_start") == [] and silent(s), channel


def test_ac_f08_37_effects_and_voices_declaring_over_600_s(tmp_path, audio_log):
    for channel in ("sound", "voice"):
        for name, data, plays in (("long_601s.ogg", ogg_bytes(601.0), False),
                                  ("long_601s.flac", flac_bytes(601.0), False),
                                  ("long_601s.wav", wav_bytes(601.0, rate=100), False),
                                  ("long_600s.ogg", ogg_bytes(600.0), True)):
            (tmp_path / f"{channel}_{name}").mkdir()
            s = make_service(tmp_path / f"{channel}_{name}")
            audio_log.clear()
            s.add("broken/" + name, data, 600.0)
            s.feed(play(channel, "broken/" + name))
            assert bool(s.mixer.actions("decode")) is plays, (channel, name)
            assert bool(s.mixer.actions("channel_play")) is plays, (channel, name)
            if not plays:
                [message] = audio_log.messages
                assert "audio/broken/" + name in message and "silence" in message, name


def test_ac_f08_37_the_same_missing_path_logs_once_across_restores(s, audio_log):
    for _ in range(3):
        s.feed(PM("bgm/zzqx.ogg"))
    s.feed(AudioRestore(AudioState((MusicEntry("bgm/zzqx.ogg", True, 100),)), "restore"))
    s.feed(AudioRestore(AudioState((MusicEntry("bgm/zzqx.ogg", True, 100),)), "restore"))
    s.feed(PM("bgm/zzqx.ogg"))
    assert audio_log.messages == ["audio/bgm/zzqx.ogg is missing, so it plays as silence."]


def test_ac_f08_37_the_story_never_waits_for_a_broken_file(tmp_path):
    """The headless twin: the runtime never opens a file, so the line after a missing
    track is released with it, in the same pump."""
    from tests.runtime.story import advance, load_files, start
    from tests.script.helpers import template_a

    program = load_files(tmp_path, {"main.vns": template_a(
        S='play music "bgm/festval.ogg"⏎"Next."')})
    interp = start(program)
    interp.take_commands(1 << 30)
    advance(interp)
    burst = interp.take_commands(1 << 30)
    assert [type(c) for c in burst if type(c) in (PlayMusic, Say)] == [PlayMusic, Say]


# --- AC-F08-39 — Paths from a restored state (W29) ------------------------------------------------

def restored(music=(), sounds=()) -> AudioRestore:
    return AudioRestore(AudioState(tuple(MusicEntry(f, True, 100) for f in music),
                                   tuple(SoundLoop(f, 40) for f in sounds)), "restore")


def test_ac_f08_39_a_missing_restored_track(s, audio_log):
    s.feed(restored(["bgm/old_theme.ogg"], [RAIN]))
    assert audio_log.messages == ["A restored game plays audio/bgm/old_theme.ogg, which is "
                                  "missing, so the music is silent."]
    assert records(audio_log)[0].levelname == "WARNING"
    assert records(audio_log)[0].code == "W29"
    assert {s.mixer.name_on(c) for c in s.mixer.busy_channels()} == {RAIN}   # the rest plays


def test_ac_f08_39_a_missing_restored_effect(s, audio_log):
    s.feed(restored([FESTIVAL], ["sfx/gone.ogg"]))
    assert audio_log.messages == ["A restored game plays audio/sfx/gone.ogg, which is "
                                  "missing, so the effect is silent."]
    assert s.mixer.music_name() == FESTIVAL


def test_ac_f08_39_a_path_leaving_the_game_folder(s, audio_log, monkeypatch):
    touched: list[str] = []
    for name in ("scandir", "stat", "open"):
        real = getattr(os, name)

        def spy(path, *args, _real=real, **kwargs):
            touched.append(os.fspath(path) if not isinstance(path, int) else "")
            return _real(path, *args, **kwargs)

        monkeypatch.setattr(os, name, spy)
    s.feed(restored(["../../ZZMARK.ogg"], [RAIN]))
    [record] = records(audio_log)
    assert record.levelname == "ERROR" and record.code == "W29"
    assert record.getMessage() == (f'Asset path "audio/../../ZZMARK.ogg" is not allowed: '
                                   f'{REASON_OUTSIDE}, so the music is silent.')
    root = str(s.root.resolve())
    assert all(os.path.normcase(p).startswith(os.path.normcase(root)) for p in touched if p)
    assert {s.mixer.name_on(c) for c in s.mixer.busy_channels()} == {RAIN}


def test_ac_f08_39_a_path_too_long(s, audio_log):
    file = "/".join(["a" * 200] * 5) + "/" + "b" * 15 + ".ogg"
    assert len(file) == 1_024 and len("audio/" + file) == 1_030
    s.feed(restored([file]))
    [record] = records(audio_log)
    assert record.levelname == "ERROR"
    assert record.getMessage().startswith('Asset path "audio/')
    assert record.getMessage().endswith(f"is not allowed: {REASON_TOO_LONG}, so the music is "
                                        f"silent.")


def test_ac_f08_39_an_extension_the_engine_cant_play(s, audio_log, reads):
    s.feed(restored(["bgm/x.mid"], ["sfx/x.mid"]))
    assert reads == []
    assert [m for m in audio_log.messages if m.startswith("A restored game plays audio/bgm/x.mid")]
    assert [m for m in audio_log.messages if m.startswith("A restored game plays audio/sfx/x.mid")]
    assert all(r.code == "W29" for r in records(audio_log))


def test_ac_f08_39_the_story_continues(s, audio_log):
    s.feed(restored(["bgm/old_theme.ogg"]), PM(FESTIVAL))      # nothing raised on the way
    assert s.mixer.music_name() == FESTIVAL

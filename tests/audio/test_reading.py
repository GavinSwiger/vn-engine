"""Reading effect files: W26/W29 once per path, the log cap, sizes and lengths (F08 ``04``
§7.4, §8; the effect rows of AC-F08-37 and 40 that step 4 can run). Content that isn't its
extension (AC-F08-35) is ``test_sniff.py``'s, and lengths over 600 s ``test_messages.py``'s,
each as music, effect, and voice."""

import logging

import pytest

from engine.audio.limits import SOUND_MAX_BYTES
from engine.audio.reading import MSG_TOO_MANY_AUDIO_PROBLEMS, AudioLog
from engine.runtime.commands import PlaySound
from tests.audio.conftest import make_service
from tests.fakes.fake_mixer import ogg_bytes

AUDIO_LOG = "vn.audio"


def shot(file: str) -> PlaySound:
    return PlaySound(file, False, 100, None)


def records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == AUDIO_LOG]


@pytest.fixture
def audio_caplog(caplog):
    caplog.set_level(logging.DEBUG, logger=AUDIO_LOG)
    return caplog


def test_missing_file_is_silent_and_logged_once(service_s, audio_caplog):
    s = service_s
    for _ in range(5):
        s.feed(shot("sfx/zzqx.ogg"))
    assert s.mixer.calls == []
    got = records(audio_caplog)
    assert [r.getMessage() for r in got] == [
        "audio/sfx/zzqx.ogg is missing, so it plays as silence."]
    assert got[0].levelno == logging.WARNING and got[0].code == "W26"


def test_missing_file_with_a_case_suggestion(service_s, audio_caplog):
    service_s.feed(shot("sfx/Door.ogg"))
    assert [r.getMessage() for r in records(audio_caplog)] == [
        'audio/sfx/Door.ogg is missing, so it plays as silence. Did you mean "sfx/door.ogg"?']


def test_a_decode_failure_is_w26_once_and_not_read_again(service_s, audio_caplog):
    s = service_s
    s.mixer.fail_decode.add("sfx/door.ogg")
    s.feed(shot("sfx/door.ogg"), shot("sfx/door.ogg"))
    assert len(s.mixer.actions("decode")) == 1
    assert not s.mixer.actions("channel_play")
    assert [r.getMessage() for r in records(audio_caplog)] == [
        "audio/sfx/door.ogg can't be played: it is damaged or isn't really an Ogg Vorbis "
        "file. Export it again as .ogg."]


def test_an_effect_over_8_mb_is_silent(tmp_path, audio_caplog):
    s = make_service(tmp_path)
    big = ogg_bytes(1.0).ljust(SOUND_MAX_BYTES + 1, b"\0")
    s.add("sfx/big.ogg", big, 1.0)
    s.feed(shot("sfx/big.ogg"))
    assert not s.mixer.actions("decode", "channel_play")
    message = records(audio_caplog)[0].getMessage()
    assert "audio/sfx/big.ogg" in message and "silence" in message


def test_an_unplayable_extension_is_silent_with_no_message(service_s, audio_caplog):
    service_s.feed(shot("sfx/theme.m4a"), shot("sfx/theme.mid"))
    assert service_s.mixer.calls == []
    assert records(audio_caplog) == []


def test_a_path_leaving_the_game_folder_is_w29_error(service_s, audio_caplog):
    service_s.feed(shot("../../ZZMARK.ogg"))
    got = records(audio_caplog)
    assert len(got) == 1 and got[0].levelno == logging.ERROR and got[0].code == "W29"
    assert got[0].getMessage().startswith('Asset path "audio/../../ZZMARK.ogg" is not allowed: ')
    assert got[0].getMessage().endswith(", so the effect is silent.")
    assert service_s.mixer.calls == []


def test_no_game_folder_means_every_file_is_missing(tmp_path, audio_caplog):
    s = make_service(tmp_path, paths=False)
    s.feed(shot("sfx/door.ogg"))
    assert s.mixer.calls == []
    assert records(audio_caplog)[0].getMessage() == (
        "audio/sfx/door.ogg is missing, so it plays as silence.")


def test_names_are_echoed(service_s, audio_caplog):
    """Through ``echo()``: escaped and cut to 120 characters (AC-F08-40)."""
    long_name = "sfx/" + chr(0x645) * 210 + ".ogg"               # right-to-left
    service_s.feed(shot(long_name), shot("sfx/" + chr(27) + "[31mred.ogg"))
    missing, blocked = (r.getMessage() for r in records(audio_caplog))
    assert len(missing.split(" is missing")[0]) <= 120
    assert chr(27) not in blocked and chr(92) + "x1b[31m" in blocked


def test_the_log_cap_is_1000_paths_then_one_summary(audio_caplog):
    log = AudioLog(logging.getLogger(AUDIO_LOG))
    for index in range(1_001):
        log.problem("missing", f"sfx/{index}.ogg", f"m{index}")
    log.problem("missing", "sfx/0.ogg", "again")             # already logged: nothing
    log.problem("damaged", "sfx/0.ogg", "other kind")         # a known path: still logged
    log.problem("missing", "sfx/late.ogg", "late")            # over the cap: nothing
    got = [r.getMessage() for r in records(audio_caplog)]
    assert got[:1_000] == [f"m{index}" for index in range(1_000)]
    assert got[1_000:] == [MSG_TOO_MANY_AUDIO_PROBLEMS, "other kind"]

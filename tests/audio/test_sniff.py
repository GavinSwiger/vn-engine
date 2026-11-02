"""Content sniffing and declared lengths (F08 ``04`` §7.4 steps 3–4; the sniff half of
AC-F08-35 and AC-F08-37's length rows, on synthetic bytes; AC-F08-35 itself on Service
S: the ``broken/`` rows played as music, effect, and voice)."""

import logging
import struct

import pytest

from engine.audio.sniff import FORMAT_NAMES, Sniffed, declared_seconds, sniff
from engine.runtime.commands import PlayMusic, PlaySound, PlayVoice
from engine.script.audio import PLAYABLE_EXTS
from tests.audio.conftest import make_service
from tests.fakes.fake_mixer import flac_bytes, mp3_bytes, ogg_bytes, opus_bytes, wav_bytes
from tests.fixtures.F08.make_audio import broken_files

MIDI = b"MThd\0\0\0\x06\0\x01\0\x02\x01\xe0" + b"MTrk" + b"\0" * 32
RMID = b"RIFF" + struct.pack("<I", 4 + len(MIDI)) + b"RMID" + b"data" + MIDI
XM = b"Extended Module: song" + b"\0" * 400
IT = b"IMPM" + b"\0" * 400
S3M = b"song".ljust(44, b"\0") + b"SCRM" + b"\0" * 64
MOD = b"song".ljust(1080, b"\0") + b"M.K." + b"\0" * 64
MOD_ID3 = b"ID3 song".ljust(1080, b"\0") + b"M!K!" + b"\0" * 64
AVI = b"RIFF" + struct.pack("<I", 100) + b"AVI " + b"\0" * 100
OGG = ogg_bytes(1.0)
OPUS = opus_bytes(1.0)
WAV = wav_bytes(0.5)
FLAC = flac_bytes(1.0)
MP3 = mp3_bytes()


def test_format_names_cover_exactly_the_playable_extensions():
    assert set(FORMAT_NAMES) == set(PLAYABLE_EXTS)


def test_valid_files_pass():
    for data, ext in ((OGG, ".ogg"), (OPUS, ".opus"), (FLAC, ".flac"), (WAV, ".wav"),
                      (MP3, ".mp3"), (b"ID3\x04\0\0\0\0\0\0" + MP3, ".mp3")):
        sniffed = sniff(data, ext)
        assert isinstance(sniffed, Sniffed), (ext, data[:4])
        assert sniffed.data is data and sniffed.ext == ext


REFUSED = [
    ("midi_as.ogg", MIDI, ".ogg"), ("midi_as.mp3", MIDI, ".mp3"), ("midi_as.wav", MIDI, ".wav"),
    ("rmid.wav", RMID, ".wav"),
    ("xm_as.wav", XM, ".wav"), ("xm_as.ogg", XM, ".ogg"),
    ("it_as.ogg", IT, ".ogg"), ("s3m_as.wav", S3M, ".wav"),
    ("mod_as.mp3", MOD, ".mp3"), ("mod_id3.mp3", MOD_ID3, ".mp3"),
    ("wav_as.ogg", WAV, ".ogg"), ("ogg_as.wav", OGG, ".wav"), ("flac_as.mp3", FLAC, ".mp3"),
    ("opus_as.ogg", OPUS, ".ogg"), ("vorbis_as.opus", OGG, ".opus"),
    ("riff_avi.wav", AVI, ".wav"),
    ("empty.ogg", b"", ".ogg"), ("ogg3.ogg", b"Ogg", ".ogg"), ("short.mp3", b"\xff", ".mp3"),
    ("reserved_layer.mp3", b"\xff\xf9" + b"\0" * 10, ".mp3"),
    ("m4a", b"\0\0\0\x20ftypM4A ", ".m4a"),
]


def test_mismatches_and_refused_signatures_are_refused():
    for name, data, ext in REFUSED:
        assert sniff(data, ext) is None, name


def test_a_mod_signature_is_refused_whatever_the_rest():
    """A MOD at offset 1080 behind a valid WAV header is still refused (§7.4: whatever the
    extension)."""
    data = WAV[:1080] + b"FLT4" + WAV[1084:]
    assert sniff(data, ".wav") is None


def test_sniffed_values_come_only_from_sniff():
    with pytest.raises(TypeError):
        Sniffed(b"OggS", ".ogg", object())


def test_declared_seconds():
    for data, ext, seconds in ((ogg_bytes(601.0), ".ogg", 601.0),
                               (ogg_bytes(600.0), ".ogg", 600.0),
                               (ogg_bytes(2.0, rate=44_100), ".ogg", 2.0),
                               (opus_bytes(3.5), ".opus", 3.5),
                               (flac_bytes(601.0), ".flac", 601.0),
                               (wav_bytes(1.0), ".wav", 1.0)):
        sniffed = sniff(data, ext)
        assert sniffed is not None, (ext, seconds)
        assert declared_seconds(sniffed) == pytest.approx(seconds, abs=1e-6), (ext, seconds)


def test_declared_seconds_of_a_wav_counts_only_the_bytes_present():
    """A ``data`` size larger than the file (a streaming writer's placeholder) counts the
    bytes really there."""
    sniffed = sniff(wav_bytes(1.0, data_size=0xFFFF_FFFF), ".wav")
    assert declared_seconds(sniffed) == pytest.approx(1.0)


def test_declared_seconds_unknown():
    assert declared_seconds(sniff(MP3, ".mp3")) is None
    no_granule = OGG[:OGG.rfind(b"OggS")]           # only the header pages (granule 0)
    assert declared_seconds(sniff(no_granule, ".ogg")) == 0.0


# --- AC-F08-35: played as music, effect, and voice on Service S ----------------------------

NOT_REALLY = "can't be played: it is damaged or isn't really"


def play_as(channel: str, file: str) -> object:
    if channel == "music":
        return PlayMusic(file, True, 100, None, None, False, None, False)
    if channel == "sound":
        return PlaySound(file, False, 100, None)
    return PlayVoice("s1", file, False)


def test_ac_f08_35_broken_content_is_never_decoded_and_valid_files_play(tmp_path, caplog):
    """As music, effect, and voice (a Service S each): each ``broken/`` row (and I-13(f)'s
    Opus in ``.ogg``) logs the W26 "isn't really" form once, and FakeMixer's ``decode`` and
    ``music_start`` are never called for it; then every valid format plays with no record."""
    rows = broken_files()
    valid = {"ok/a.ogg": OGG, "ok/b.opus": OPUS, "ok/c.flac": FLAC, "ok/d.wav": WAV,
             "ok/e.mp3": b"ID3\x04\0\0\0\0\0\0" + MP3, "ok/f.mp3": mp3_bytes(b"f")}
    caplog.set_level(logging.WARNING, logger="vn.audio")
    for channel in ("music", "sound", "voice"):
        (tmp_path / channel).mkdir()
        s = make_service(tmp_path / channel)
        caplog.clear()
        for name, data in rows.items():
            s.add(f"broken/{name}", data)
        for file, data in valid.items():
            s.add(file, data, 1.0)
        for name in rows:
            s.feed(play_as(channel, f"broken/{name}"), play_as(channel, f"broken/{name}"))
        assert not s.mixer.actions("decode", "music_start", "music_arm", "channel_play")
        records = [r for r in caplog.records if r.name == "vn.audio"]
        assert len(records) == len(rows), channel
        for name, record in zip(rows, records, strict=True):
            message = record.getMessage()
            assert record.code == "W26" and record.levelno == logging.WARNING, channel
            assert message.startswith(f"audio/broken/{name} {NOT_REALLY} "), message
            kind = {".ogg": "an Ogg Vorbis file", ".wav": "a WAV file"}.get(name[-4:])
            if kind is not None:
                assert message == (f"audio/broken/{name} can't be played: it is damaged or "
                                   f"isn't really {kind}. Export it again as {name[-4:]}.")
        caplog.clear()
        for file in valid:
            s.feed(play_as(channel, file))
            s.advance(1.5)
        played = s.mixer.actions("music_start" if channel == "music" else "decode")
        assert [c[2][0] for c in played] == list(valid), channel
        assert [r for r in caplog.records if r.name == "vn.audio"] == [], channel

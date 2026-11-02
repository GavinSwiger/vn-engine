"""F06 step 2, the audio seam (``SPEC.md`` §5; ``07`` I-3 to I-6): ``pitch.resample``
(AC-F06-07), the loader's blip variants and ``pending_blip`` (AC-F06-08), ``play_blip`` on
channel 1 next to ``play_ui`` on 2–4 (AC-F06-10; ``play_ui``'s own rows are AC-F08-52 in
``test_reconcile.py``), and broken blip files (AC-F06-12, service rows). Service S with the
``BlipMixer`` (``conftest.py``); ``threaded`` gives the loader its worker."""

import logging
import threading
from array import array

import pytest

import engine.audio.loader as loader_mod
from engine.audio.backend import NullMixer
from engine.audio.limits import BLIP_CHANNEL
from engine.audio.loader import WORKER_NAME, BlipSounds
from engine.audio.pitch import BLIP_STEPS, resample, speed
from engine.audio.volume import amp, quantize
from engine.core.constants import ENTRY_OVERHEAD
from engine.core.paths import GamePaths
from engine.script.messages import format_message
from tests.audio.conftest import RATE, make_service
from tests.audio.test_device import added, without_a_device
from tests.fakes.fake_mixer import mp3_bytes, ogg_bytes

HANA = "blips/hana.ogg"           # 0.1 s
LONG = "blips/long.ogg"           # 0.6 s: too long for a pitch (W49)
LOW = "blips/low.ogg"             # 0.2 s
WAIT_S = 5.0


def add_blips(s) -> None:
    for index, (file, seconds) in enumerate(((HANA, 0.1), (LONG, 0.6), (LOW, 0.2))):
        s.add(file, ogg_bytes(seconds, salt=b"blip%d" % index), seconds)


@pytest.fixture
def s(tmp_path):
    s = make_service(tmp_path)
    add_blips(s)
    return s


@pytest.fixture
def threaded(tmp_path):
    """A Service S with the loader's worker; ``gate`` holds every decode until set, and
    ``entered`` is set when one has started."""
    s = make_service(tmp_path, threaded=True)
    add_blips(s)
    s.gate = threading.Event()
    s.gate.set()
    s.entered = threading.Event()

    def hook(name: str) -> None:
        s.entered.set()
        s.gate.wait(WAIT_S)

    s.mixer.decode_hook = hook
    yield s
    s.gate.set()
    s.service.shutdown()


@pytest.fixture
def reads():
    """Every ``GamePaths.read_file`` of an ``audio/`` file, by ref."""
    seen: list[str] = []
    real = GamePaths.read_file

    def spy(self, ref, *args, **kwargs):
        seen.append(ref)
        return real(self, ref, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(GamePaths, "read_file", spy)
        yield seen


def blips(s) -> list[tuple]:
    """Channel 1's actions: ``(name, args)``."""
    return [(name, args) for _, name, args in s.mixer.actions("channel_stop", "channel_volume",
                                                              "channel_play")
            if args[0] == BLIP_CHANNEL]


def on_blip_channel(s):
    playing = s.mixer.playing.get(BLIP_CHANNEL)
    return playing.sound if playing is not None else None


def variants(s, file: str, spread: float) -> BlipSounds:
    entry = s.cache.get(("blip", file, spread), s.frame)
    assert isinstance(entry, BlipSounds)
    return entry


# --- AC-F06-07 — resample ----------------------------------------------------------------------

def frames(count: int, frame_bytes: int) -> bytes:
    """``count`` distinct frames: stereo ``(k, -k)``, mono ``k``."""
    if frame_bytes == 4:
        return array("h", [v for k in range(count) for v in (k, -k)]).tobytes()
    return array("h", range(count)).tobytes()


def test_ac_f06_07_resample():
    raw = frames(100, 4)
    assert resample(raw, 1.0) == raw                                  # ratio 1 is the identity
    n = 1_001
    for frame_bytes in (4, 2):                                        # stereo, mono
        for ratio in (0.9, 1.1):
            out = array("h", resample(frames(n, frame_bytes), ratio, frame_bytes))
            width = frame_bytes // 2
            got = [tuple(out[k * width:(k + 1) * width]) for k in range(len(out) // width)]
            picked = [int(k * ratio) for k in range(int(n / ratio))]
            # frames are picked whole: L/R pairs stay together
            assert got == [(j, -j) if width == 2 else (j,) for j in picked], (frame_bytes, ratio)
    with pytest.raises(AssertionError):                               # a partial frame fails
        resample(frames(10, 4)[:-2], 1.1)


# --- AC-F06-08 — the loader's variants and pending_blip -----------------------------------------

@pytest.mark.parametrize("worker", [False, True], ids=["fallback", "worker"])
def test_ac_f06_08_a_miss_reads_once_and_one_ticket_yields_five_sounds(tmp_path, reads, worker):
    s = make_service(tmp_path, threaded=worker)
    add_blips(s)
    try:
        for step in (-2, 1, 2):
            s.service.play_blip(HANA, spread=0.2, step=step)
        s.decoded()
        assert reads == ["audio/" + HANA] and s.mixer.decoded == [HANA]
        entry = variants(s, HANA, 0.2)
        n = round(0.1 * RATE)
        assert [one.seconds for one in entry.sounds] == [
            int(n / speed(0.2, step)) / RATE if step else 0.1 for step in BLIP_STEPS]
        assert s.cache.cost(("blip", HANA, 0.2)) == int(
            sum(one.seconds for one in entry.sounds) * 192_000) + ENTRY_OVERHEAD
        assert on_blip_channel(s) == entry.pick(2)
        assert len([b for b in blips(s) if b[0] == "channel_play"]) == (1 if worker else 3)
        if worker:                                   # ADR-0007: built on the worker, played on main
            built = {thread for name, thread in s.mixer.threads
                     if name in ("decode", "sound_raw", "sound_from_raw")}
            played = {thread for name, thread in s.mixer.threads if name.startswith("channel")}
            assert built == {WORKER_NAME} and played == {threading.main_thread().name}
    finally:
        s.service.shutdown()


@pytest.mark.parametrize("age, plays", [(0.05, True), (0.06, False)])
def test_ac_f06_08_a_decoded_blip_plays_only_if_asked_for_at_most_50_ms_ago(threaded, age,
                                                                          plays):
    s = threaded
    s.gate.clear()
    s.service.play_blip(HANA, spread=0.1)
    s.clock.now += age
    s.gate.set()
    s.decoded()
    assert (on_blip_channel(s) is not None) is plays
    assert s.service.blip.pending is None


def test_ac_f06_08_only_the_newest_pending_blip_plays(threaded):
    s = threaded
    s.gate.clear()
    s.service.play_blip(LOW, spread=0.1)
    s.service.play_blip(HANA, spread=0.1, step=-1)
    ticket = s.service.blip.pending.ticket
    s.service.play_blip(HANA, spread=0.1, step=1, volume=50)
    assert s.service.blip.pending.ticket is ticket                # same key: no second ticket
    s.gate.set()
    s.decoded()
    assert s.mixer.decoded == [LOW, HANA]                         # LOW still cached, not played
    assert [b for b in blips(s) if b[0] == "channel_play"] == [
        ("channel_play", (BLIP_CHANNEL, variants(s, HANA, 0.1).pick(1).name, 0))]
    assert s.mixer.volumes[BLIP_CHANNEL] == quantize(amp(100, 80, 50))


def test_ac_f06_08_a_long_pitched_blip_plays_unpitched_with_w49_once(s, caplog):
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        for _ in range(50):
            s.service.play_blip(LONG, spread=0.3, step=2)
    entry = variants(s, LONG, 0.3)
    assert entry.too_long and entry.sounds == (on_blip_channel(s),)
    assert caplog.messages == [format_message("W49", (LONG, 0.6))]
    assert [r.code for r in caplog.records] == ["W49"]


def test_spread_0_plays_the_files_sound_and_builds_no_variants(s):
    """I-6: the ``("snd", file)`` entry an effect of the same file would use."""
    s.service.play_blip(HANA, step=2)
    assert on_blip_channel(s).name == HANA
    assert [key for key in s.cache.keys() if key[0] == "blip"] == []
    assert s.mixer.actions("sound_raw", "sound_from_raw") == []


def test_ac_f06_08_a_mono_reopen_drops_blips_and_rebuilds_them_mono(threaded):
    """I-3: a reopen (here ``set_mono``, waiting for the decode that holds the lock) drops the
    ``("blip", …)`` entries, the pending blip, and the result decoded for the old mixer; the
    next blip is built from 2-byte frames."""
    s = threaded
    s.service.play_blip(HANA, spread=0.2)
    s.decoded()
    s.gate.clear()
    s.entered.clear()
    s.service.play_blip(LOW, spread=0.2)
    assert s.entered.wait(WAIT_S)
    s.service.set_mono(True)                                    # the decode holds the lock
    assert s.mixer.actions("reopen") == []
    s.gate.set()
    s.service.loader.wait(WAIT_S)
    s.advance(0.0)                                              # reopen, then drop the result
    assert [args for _, _, args in s.mixer.actions("reopen")] == [(1,)]
    assert [key for key in s.cache.keys() if key[0] == "blip"] == []
    assert s.service.blip.pending is None and on_blip_channel(s) is None
    sizes: list[int] = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(loader_mod, "resample",
                      lambda raw, ratio, frame_bytes: sizes.append(frame_bytes)
                      or resample(raw, ratio, frame_bytes))
        s.service.play_blip(HANA, spread=0.2, step=-2)
        s.decoded()
    assert sizes == [2] * 4
    assert on_blip_channel(s).seconds == int(round(0.1 * RATE) / speed(0.2, -2)) / RATE


def test_a_late_device_open_drops_the_null_mixers_blips(tmp_path, caplog):
    """Step 12: blips on ``NullMixer`` are silent and quiet; once a device opens, they are
    decoded again for it."""
    s, _ = without_a_device(tmp_path)
    add_blips(s)
    with caplog.at_level(logging.DEBUG, logger="vn.audio"):
        s.service.play_blip(HANA, spread=0.1)
    assert caplog.records == [] and isinstance(s.service.backend, NullMixer)
    s.service.handle_event(added())
    s.advance(0.5)
    assert s.service.backend is s.mixer
    s.service.play_blip(HANA, spread=0.1, step=1)
    assert on_blip_channel(s) == variants(s, HANA, 0.1).pick(1)


# --- AC-F06-10 — channel 1, volume ------------------------------------------------------------

def test_ac_f06_10_a_blip_stops_channel_1_then_plays_at_the_sound_volume(s):
    s.service.play_blip(HANA, volume=60)
    s.service.set_volumes(100, 70, 50, 100)
    s.service.play_blip(HANA, volume=60)
    assert [name for name, _ in blips(s)] == ["channel_stop", "channel_volume",
                                               "channel_play"] * 2
    assert [args for name, args in blips(s) if name != "channel_volume"] == [
        (BLIP_CHANNEL,), (BLIP_CHANNEL, HANA, 0)] * 2
    assert [args[1] for name, args in blips(s) if name == "channel_volume"] == [
        quantize(amp(100, 80, 60)), quantize(amp(100, 50, 60))]


def test_a_blip_is_held_while_it_plays_and_skipped_while_skipping(s):
    s.service.play_blip(HANA, spread=0.1)
    assert s.cache._holds == {("blip", HANA, 0.1): 1}
    s.advance(0.2)                                              # the blip ended
    assert s.cache._holds == {}
    s.service.set_skipping(True)
    s.mixer.calls.clear()
    s.service.play_blip(HANA, spread=0.1)
    assert blips(s) == []


# --- AC-F06-12 — broken files, service rows -----------------------------------------------------

@pytest.mark.parametrize("data, message", [
    (None, "audio/blips/x.ogg is missing, so it plays as silence."),
    (mp3_bytes(), "audio/blips/x.ogg can't be played: it is damaged or isn't really an Ogg "
                  "Vorbis file. Export it again as .ogg."),
    (b"", "audio/blips/x.ogg can't be played: it is damaged or isn't really an Ogg Vorbis "
          "file. Export it again as .ogg."),
], ids=["missing", "mp3", "empty"])
def test_ac_f06_12_a_broken_blip_is_read_once_w26_once_and_silent(s, reads, caplog, data,
                                                                  message):
    if data is not None:
        s.add("blips/x.ogg", data)
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        for step in range(100):
            s.service.play_blip("blips/x.ogg", spread=0.1, step=step % 5 - 2)
            s.advance(0.04)
    assert caplog.messages == [message] and reads == ["audio/blips/x.ogg"]
    assert blips(s) == []

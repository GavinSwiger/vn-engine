"""AC-F08-24 — writing loop tags, W28 and W31 (F08 ``04-technical.md`` §7.5; ``02`` SR-F08-09,
23; ``07`` I-9), and the service's use of them on Service S: music plays the tagged bytes with
``loops=-1``, and a looping effect plays its whole sound once with its tail queued, the tail
queued again on each pass (the unit half of AC-F08-23's "the same file played as
``play sound … loop`` uses the same loop point").

Fixtures (``tests/fixtures/F08/make_audio.py``, built at test time): there is no Ogg encoder in
the repo, so ``intro_vorbis`` is pygame-ce's ``house_lo.ogg`` with its rate field set to
48,000 Hz (78,331 samples, 1.632 s) and ``intro_opus`` is ``house_lo.opus`` (341,036 samples
after its 312-sample pre-skip, 7.105 s). The Vorbis rows therefore use a loop start of 0.5 s
(``LOOPSTART=24000``) instead of 4.0 s; the Opus row uses 4.0 s (``LOOPSTART=192000``) as
written. ``existing_tags``, ``tagfull``, ``two_page_header``, and ``malformed`` are
``intro_vorbis`` with rewritten header pages; ``long_72s`` declares 1,087 Hz (72.06 s)."""

import logging
import struct

import pytest

from engine.audio import oggloop
from engine.audio.loader import TAIL_MIN_S, LoopedSound, sound_key
from engine.audio.oggloop import (NoRoom, PastEnd, Tagged, add_loop_tags, build_page, ogg_crc,
                                  read_page, w28_text, w31_run_text)
from engine.audio.reading import AudioLog
from engine.audio.sniff import sniff
from engine.core.config_schema import AudioConfig
from engine.runtime.commands import PlayMusic, PlaySound, PlayVoice, StopSound
from tests.audio.conftest import make_service
from tests.fakes.fake_mixer import mp3_bytes, ogg_bytes
from tests.fixtures.F08 import make_audio as fx

FESTIVAL = "bgm/festival.ogg"
INTRO = "loops/intro_vorbis.ogg"
INTRO_FRAMES = 78_331
LS = 0.5                                        # the Vorbis stand-in's loop start (24,000)


def PM(file, *, loop=True, fadeout=None, restart=False) -> PlayMusic:
    return PlayMusic(file, loop, 100, None, fadeout, restart, None, False)


@pytest.fixture(scope="module")
def intro() -> bytes:
    return fx.intro_vorbis()


# --- add_loop_tags ---------------------------------------------------------------------------

def test_the_crc_is_ogg_s():
    assert ogg_crc(b"") == 0
    assert ogg_crc(b"OggS") == fx._crc32_ogg(b"OggS")
    page = fx.ogg_pages(fx.intro_vorbis())[1]
    raw = page[0][:22] + b"\0\0\0\0" + page[0][26:] + page[1] + page[2]
    assert ogg_crc(raw) == struct.unpack("<I", page[0][22:26])[0]


def test_ac_f08_24_vorbis_gets_exactly_one_of_each_tag(intro):
    tags = add_loop_tags(intro, LS)
    assert isinstance(tags, Tagged)
    assert (tags.start, tags.total, tags.rate) == (24_000, INTRO_FRAMES, 48_000)
    out = tags.apply(intro)
    loops = [c for c in fx.vorbis_comments(out) if c.upper().startswith(b"LOOP")]
    assert loops == [b"LOOPSTART=24000", b"LOOPLENGTH=%d" % (INTRO_FRAMES - 24_000)]
    old, new = fx.ogg_pages(intro), fx.ogg_pages(out)
    assert len(new) == len(old)                                   # page count unchanged
    k = fx.header_page_count(intro)
    for before, after in zip(old[:k + 1], new[:k + 1]):
        assert after[0][:22] == before[0][:22]                    # fields, except the CRC
        crc = struct.unpack("<I", after[0][22:26])[0]
        assert crc == fx._crc32_ogg(after[0][:22] + b"\0\0\0\0" + after[0][26:]
                                    + after[1] + after[2])
    assert new[k + 1:] == old[k + 1:]                             # later pages identical
    assert out[tags.header_end + len(out) - len(intro):] == intro[tags.header_end:]
    assert len(tags.header) < 4_096                               # I-9: header pages only


def test_ac_f08_24_existing_loop_tags_are_replaced():
    tags = add_loop_tags(fx.existing_tags(), LS)
    assert isinstance(tags, Tagged)
    comments = fx.vorbis_comments(tags.apply(fx.existing_tags()))
    assert comments == [b"TITLE=house", b"LOOPSTART=24000",
                        b"LOOPLENGTH=%d" % (INTRO_FRAMES - 24_000)]


def test_ac_f08_24_opus_counts_without_the_pre_skip():
    data = fx.intro_opus()
    last = struct.unpack("<q", data[data.rfind(b"OggS") + 6:data.rfind(b"OggS") + 14])[0]
    tags = add_loop_tags(data, 4.0)
    assert isinstance(tags, Tagged)
    assert tags.total == last - 312 == 341_036
    loops = [c for c in fx.opus_comments(tags.apply(data)) if c.startswith(b"LOOP")]
    assert loops == [b"LOOPSTART=192000", b"LOOPLENGTH=149036"]
    assert sniff(tags.apply(data), ".opus") is not None


def test_ac_f08_24_a_start_past_the_end_is_past_end():
    verdict = add_loop_tags(fx.long_72s(), 95)
    assert isinstance(verdict, PastEnd) and int(verdict.seconds) == 72
    assert isinstance(add_loop_tags(fx.intro_vorbis(), INTRO_FRAMES / 48_000), PastEnd)


def test_ac_f08_24_a_full_header_has_no_room():
    data = fx.tagfull()
    pages = fx.ogg_pages(data)
    assert len(pages[1][1]) == 255 and pages[1][1][-1] < 255      # the comment fills page 1
    assert isinstance(add_loop_tags(data, LS), NoRoom)


def test_a_header_over_two_pages_keeps_its_continuation():
    data = fx.two_page_header()
    tags = add_loop_tags(data, LS)
    assert isinstance(tags, Tagged)
    old, new = fx.ogg_pages(data), fx.ogg_pages(tags.apply(data))
    assert len(new) == len(old)
    assert [p[0][5] for p in new[:3]] == [p[0][5] for p in old[:3]] == [2, 0, 1]
    assert len(new[1][1]) == 255 and len(new[2][2]) == len(old[2][2]) + 39   # page 2 grew
    assert fx.vorbis_comments(tags.apply(data))[1:] == [
        b"LOOPSTART=24000", b"LOOPLENGTH=%d" % (INTRO_FRAMES - 24_000)]


def test_ac_f08_24_malformed_files_are_no_room_and_never_raise():
    for row, data in (("bad_crc", fx.malformed()), ("empty", b""), ("magic", b"OggS"),
                      ("zeros", b"OggS" + b"\0" * 40), ("no_comment", ogg_bytes(5.0)),
                      ("junk", b"x" * 100), ("cut", fx.intro_vorbis()[:200]),
                      ("cut_opus", fx.intro_opus()[:120])):
        assert isinstance(add_loop_tags(data, LS), (NoRoom, PastEnd)), row


def test_read_page_checks_the_crc(intro):
    page = read_page(intro, 0)
    assert build_page(page.fixed, page.lacing, page.body) == intro[:page.end]
    with pytest.raises(oggloop.Malformed):
        read_page(fx.malformed(), page.end)


# --- Messages ----------------------------------------------------------------------------------

def test_w28_and_w31_texts():
    assert w28_text(FESTIVAL, 95.0, 72.06) == (
        '[audio.loop_start] "bgm/festival.ogg" = 95 is past the end of the track (1:12), so '
        "it loops from the start. Use a time before 1:12.")
    assert w28_text(FESTIVAL, 4.25, 3.0).startswith('[audio.loop_start] "bgm/festival.ogg" = '
                                                    "4.25 is past the end of the track (0:03)")
    assert w31_run_text(FESTIVAL) == (
        "audio/bgm/festival.ogg can't use its loop point because the file's header has no "
        "room for the loop tags, so it loops from the start. Export it again as .ogg.")
    assert w31_run_text("bgm/x.opus").endswith("Export it again as .opus.")


# --- The tag cache (LoopPoints) ----------------------------------------------------------------

def test_the_cache_keeps_one_verdict_per_file(intro, monkeypatch):
    calls = []
    real = oggloop.add_loop_tags
    monkeypatch.setattr(oggloop, "add_loop_tags",
                        lambda data, start: calls.append(start) or real(data, start))
    points = oggloop.LoopPoints({INTRO: LS}, AudioLog())
    data = sniff(intro, ".ogg")
    first = points.music(INTRO, data)
    second = points.music(INTRO, data)
    assert calls == [LS]
    assert first is not None and second is not None
    assert first[1] == second[1] == pytest.approx(LS)
    assert first[0].data == second[0].data
    assert points.sound_start(INTRO, data) == pytest.approx(LS)
    (entry,) = points._cache.values()
    assert entry.tags is not None and len(entry.tags.header) < len(intro) // 4     # I-9
    assert points.music("loops/other.ogg", data) is None                # no loop point
    changed = sniff(fx.existing_tags(), ".ogg")
    points.music(INTRO, changed)                                        # the file changed
    assert calls == [LS, LS]


def test_a_zero_loop_start_and_other_formats_are_plain_loops(intro):
    points = oggloop.LoopPoints({INTRO: 0.0, "bgm/a.wav": 3.0}, AudioLog())
    assert points.music(INTRO, sniff(intro, ".ogg")) is None
    assert points.music("bgm/a.wav", sniff(fx.tone_wav(4.0), ".wav")) is None


# --- Music on Service S --------------------------------------------------------------------------

def loop_service(tmp_path, file, data, start, seconds):
    s = make_service(tmp_path, AudioConfig(loop_start={file: start}))
    s.add(file, data, seconds)
    return s


def test_ac_f08_24_music_plays_the_tagged_bytes_natively(tmp_path, intro):
    s = loop_service(tmp_path, INTRO, intro, LS, INTRO_FRAMES / 48_000)
    tags = add_loop_tags(intro, LS)
    s.mixer.register(tags.apply(intro), "intro+tags", INTRO_FRAMES / 48_000)
    s.feed(PM(INTRO))
    assert s.mixer.actions("music_start")[0][2][:3] == ("intro+tags", -1, 0.0)
    assert s.service.music.current.loop_pt == pytest.approx(LS)
    s.run(2.0)                                     # one pass (1.632 s), then 0.368 s of loop
    assert s.service.music.position(s.clock()) == pytest.approx(LS + 0.368, abs=0.02)


def test_ac_f08_24_once_plays_the_file_as_it_is(tmp_path, intro):
    s = loop_service(tmp_path, INTRO, intro, LS, INTRO_FRAMES / 48_000)
    s.feed(PM(INTRO, loop=False))
    assert s.mixer.actions("music_start")[0][2][:2] == (INTRO, 0)


def test_ac_f08_24_w28_is_logged_and_the_track_loops_from_the_start(tmp_path, caplog):
    s = loop_service(tmp_path, FESTIVAL, fx.long_72s(), 95.0, 72.06)
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        s.feed(PM(FESTIVAL))
    assert caplog.messages == [
        '[audio.loop_start] "bgm/festival.ogg" = 95 is past the end of the track (1:12), so '
        "it loops from the start. Use a time before 1:12."]
    assert caplog.records[0].code == "W28"
    assert s.mixer.actions("music_start")[0][2][:2] == (FESTIVAL, -1)       # a plain loop
    assert s.service.music.current.loop_pt is None


def test_ac_f08_24_w31_is_logged_once_and_the_track_loops_from_the_start(tmp_path, caplog):
    for row, data in (("tagfull", fx.tagfull()), ("malformed", fx.malformed())):
        (tmp_path / row).mkdir()
        caplog.clear()
        s = loop_service(tmp_path / row, FESTIVAL, data, LS, 1.632)
        with caplog.at_level(logging.WARNING, logger="vn.audio"):
            for _ in range(3):
                s.feed(PM(FESTIVAL, fadeout=0, restart=True))
        assert caplog.messages == [
            "audio/bgm/festival.ogg can't use its loop point because the file's header has no "
            "room for the loop tags, so it loops from the start. Export it again as .ogg."], row
        assert caplog.records[0].code == "W31", row
        assert [c[2][:2] for c in s.mixer.actions("music_start")] == [(FESTIVAL, -1)] * 3, row


def test_ac_f08_24_an_mp3_with_a_loop_point_is_a_plain_loop_with_no_record(tmp_path, caplog):
    s = loop_service(tmp_path, "bgm/festival.mp3", mp3_bytes(b"f"), 8.0, 12.0)
    with caplog.at_level(logging.DEBUG, logger="vn.audio"):
        s.feed(PM("bgm/festival.mp3"))
    assert caplog.records == []
    assert s.mixer.actions("music_start")[0][2][:2] == ("bgm/festival.mp3", 0)  # pass by pass
    assert s.service.music.current.loop_pt is None


# --- Effects on Service S (AC-F08-23's sound half, unit) ---------------------------------------

def test_a_looping_effect_plays_once_then_its_tail_each_pass(tmp_path, intro):
    s = loop_service(tmp_path, INTRO, intro, LS, INTRO_FRAMES / 48_000)
    s.feed(PlaySound(INTRO, True, 100, None))
    (play,) = s.mixer.actions("channel_play")
    channel = play[2][0]
    assert play[2] == (channel, INTRO, 0)                         # the whole file, once
    assert s.mixer.actions("channel_queue")[0][2] == (channel, INTRO + "#tail")
    assert s.mixer.actions("sound_tail")[0][2] == (INTRO, pytest.approx(LS))
    sound = s.cache.get(sound_key(INTRO), 0)
    assert isinstance(sound, LoopedSound)
    tail = sound.tail.seconds
    assert tail >= TAIL_MIN_S
    s.run(INTRO_FRAMES / 48_000 + 2.5 * tail, step=0.05)
    assert len(s.mixer.actions("channel_queue")) == 4             # the first, then one a pass
    assert s.mixer.name_on(channel) == INTRO + "#tail"
    assert s.mixer.queued_on(channel) == INTRO + "#tail"
    s.feed(StopSound(None, 0))
    assert s.mixer.name_on(channel) is None and s.mixer.queued_on(channel) is None


def test_a_one_shot_and_a_voice_of_a_looped_file_play_the_whole_sound(tmp_path, intro):
    s = loop_service(tmp_path, INTRO, intro, LS, INTRO_FRAMES / 48_000)
    s.feed(PlaySound(INTRO, True, 100, None), PlaySound(INTRO, False, 100, None),
           PlayVoice("s1", INTRO, False))
    plays = [c[2] for c in s.mixer.actions("channel_play")]
    assert [p[1:] for p in plays] == [(INTRO, 0), (INTRO, 0), (INTRO, 0)]
    assert len(s.mixer.actions("channel_queue")) == 1             # only the loop's
    assert len(s.mixer.actions("sound_tail")) == 1                # decoded and cut once


def test_a_tail_that_cant_be_cut_loops_from_the_start(tmp_path, intro):
    s = loop_service(tmp_path, INTRO, intro, LS, 0.4)             # decodes shorter than 0.5
    s.feed(PlaySound(INTRO, True, 100, None))
    assert s.mixer.actions("channel_play")[0][2][1:] == (INTRO, -1)
    assert s.mixer.actions("channel_queue") == []


def test_a_loop_whose_tail_ran_out_starts_it_again(tmp_path, intro):
    s = loop_service(tmp_path, INTRO, intro, LS, INTRO_FRAMES / 48_000)
    s.feed(PlaySound(INTRO, True, 100, None))
    channel = s.mixer.actions("channel_play")[0][2][0]
    s.advance(20.0)                                  # one frame after a 20 s stall
    assert s.mixer.actions("channel_play")[-1][2] == (channel, INTRO + "#tail", 0)
    assert s.mixer.queued_on(channel) is None
    s.advance(0.01)
    assert s.mixer.queued_on(channel) == INTRO + "#tail"
    assert channel in s.service.effects.slots

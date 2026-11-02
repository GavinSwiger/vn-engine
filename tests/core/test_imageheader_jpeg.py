"""``check_engine_jpeg`` (F11 C16, SEC-F11-01; abuse group C, the byte-level rows).

The check accepts only the whole structure pygame-ce's encoder writes: SOI, APP0 JFIF,
tables, one SOF0 of exactly the size, one baseline SOS, entropy data, EOI last, at most
96 KiB, and no ``<svg``. The decode side (SDL_image picks JPEG for every accepted string)
is in ``tests/render/test_thumbnail.py``."""

import random
import time

import pytest

from engine.core import imageheader
from engine.core.imageheader import ENGINE_JPEG_MAX_BYTES, check_engine_jpeg
from tests.fakes import jpegs
from tests.fakes.jpegs import THUMB

structure = imageheader._engine_jpeg_structure


@pytest.fixture(scope="module")
def flat() -> bytes:
    return jpegs.engine_jpeg("flat")


@pytest.fixture(scope="module")
def noise() -> bytes:
    return jpegs.engine_jpeg("noise")


# --- Accepted: what the engine writes ---------------------------------------------------------

def test_the_constant_is_thumb_max_bytes():
    assert ENGINE_JPEG_MAX_BYTES == 98_304 == 96 * 1024


@pytest.mark.parametrize("kind", ["flat", "bands", "noise"])
def test_the_engines_own_thumbnails_are_accepted(kind):
    data = jpegs.engine_jpeg(kind)
    assert check_engine_jpeg(data, THUMB)
    assert check_engine_jpeg(bytearray(data), THUMB)


def test_the_measured_encoder_structure(flat):
    """APP0, DQT×2, SOF0, DHT×4, SOS (the pinned wheel; a change here means re-measuring)."""
    assert jpegs.markers(flat) == [0xE0, 0xDB, 0xDB, 0xC0, 0xC4, 0xC4, 0xC4, 0xC4, 0xDA]
    assert flat.endswith(jpegs.EOI)


def test_only_the_given_size_is_accepted(flat):
    assert not check_engine_jpeg(flat, (180, 320))
    assert not check_engine_jpeg(flat, (320, 181))
    assert not check_engine_jpeg(jpegs.engine_jpeg("flat", (320, 181)), THUMB)
    assert not check_engine_jpeg(jpegs.engine_jpeg("flat", (640, 360)), THUMB)
    assert check_engine_jpeg(jpegs.engine_jpeg("flat", (64, 36)), (64, 36))


def test_a_one_component_frame_and_other_table_segments_are_accepted(flat):
    segments, tail = jpegs.split(flat)
    grey = [segments[0], segments[1], jpegs.sof(320, 180, components=1), segments[4],
            jpegs.sos(1)]
    assert check_engine_jpeg(jpegs.join(grey, tail), THUMB)
    dri = jpegs.segment(0xDD, b"\x00\x10")
    app1 = jpegs.segment(0xE1, b"Exif\x00\x00")
    assert check_engine_jpeg(jpegs.insert_after_app0(flat, dri, app1, jpegs.com(b"hi")),
                             THUMB)


def test_restart_markers_and_fill_in_the_scan_are_accepted(flat):
    body, eoi = flat[:-2], flat[-2:]
    rst = b"".join(bytes((0xFF, 0xD0 + i % 8)) for i in range(1000))
    assert check_engine_jpeg(body + rst + eoi, THUMB)            # group C: 1,000 RSTs
    assert check_engine_jpeg(body + b"\xff\xff\xff" + eoi, THUMB)   # fill before EOI
    assert check_engine_jpeg(body + b"\xff\xff\x00\x12" + eoi, THUMB)


def test_exactly_96_kib_is_accepted_and_one_more_byte_is_not(flat):
    assert check_engine_jpeg(jpegs.pad_to(flat, ENGINE_JPEG_MAX_BYTES), THUMB)
    over = jpegs.pad_to(flat, ENGINE_JPEG_MAX_BYTES + 1)
    assert structure(over, THUMB)
    assert not check_engine_jpeg(over, THUMB)


# --- Refused: the SVG confusion and the backstop ----------------------------------------------

def test_the_svg_confusion_reproduction_is_refused():
    data = jpegs.svg_confusion(8000)
    assert len(data) == 421
    # F01's header walk stops at the frame and reports a 320×180 JPEG (why C16 is needed).
    assert imageheader.image_dimensions(data) == ("jpeg", 320, 180)
    assert not structure(data, THUMB)          # refused by structure, not only the backstop
    assert not check_engine_jpeg(data, THUMB)


def test_the_reproduction_completed_with_a_scan_but_no_tables_is_refused_by_the_backstop():
    data = jpegs.svg_confusion(8000)
    walk = (data[:2] + jpegs.segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
            + data[2:388] + jpegs.sof(320, 180) + jpegs.sos(3) + b"\x12\x34" * 10
            + jpegs.EOI)
    assert structure(walk, THUMB)
    assert not check_engine_jpeg(walk, THUMB)


@pytest.mark.parametrize("marker", [0xFE, 0xE1, 0xEF])
@pytest.mark.parametrize("text", [b"<svg width='16384' height='16384'>", b"<SVG>", b"x<sVg"])
def test_svg_anywhere_is_refused_even_in_a_valid_structure(flat, marker, text):
    data = jpegs.insert_after_app0(flat, jpegs.segment(marker, text))
    assert structure(data, THUMB)
    assert not check_engine_jpeg(data, THUMB)


def test_svg_in_the_entropy_data_is_refused(flat):
    data = flat[:-2] + b"<svg" + flat[-2:]
    assert structure(data, THUMB)
    assert not check_engine_jpeg(data, THUMB)


# --- Refused: structure (group C) -------------------------------------------------------------

def _app0_first_rows(flat):
    segments, tail = jpegs.split(flat)
    yield "no APP0", jpegs.join(segments[1:], tail)
    yield "DQT before APP0", jpegs.join([segments[1], segments[0], *segments[2:]], tail)
    yield "JFXX", jpegs.replace_marker(flat, 0xE0, jpegs.segment(0xE0, b"JFXX\x00" + b"\0" * 9))
    yield "APP0 too short", jpegs.replace_marker(flat, 0xE0, jpegs.segment(0xE0, b"JFI"))
    yield "ftyp at offset 4", flat[:4] + b"ftyp" + flat[8:]
    yield "GIF8 first", b"GIF8" + flat[4:]


def _frame_rows(flat):
    two = jpegs.insert_after_app0(flat, jpegs.sof(320, 180))
    yield "two SOF0", two
    yield "SOF2 progressive", jpegs.replace_marker(flat, 0xC0, jpegs.sof(320, 180, marker=0xC2))
    yield "SOF1 extended", jpegs.replace_marker(flat, 0xC0, jpegs.sof(320, 180, marker=0xC1))
    yield "SOF3 lossless", jpegs.replace_marker(flat, 0xC0, jpegs.sof(320, 180, marker=0xC3))
    yield "SOF9 arithmetic", jpegs.replace_marker(flat, 0xC0, jpegs.sof(320, 180, marker=0xC9))
    yield "4 components", jpegs.replace_marker(flat, 0xC0, jpegs.sof(320, 180, components=4))
    yield "2 components", jpegs.replace_marker(flat, 0xC0, jpegs.sof(320, 180, components=2))
    yield "precision 12", jpegs.replace_marker(flat, 0xC0, jpegs.sof(320, 180, precision=12))
    yield "height 0 (DNL)", jpegs.replace_marker(flat, 0xC0, jpegs.sof(320, 0))
    yield "320x181", jpegs.replace_marker(flat, 0xC0, jpegs.sof(320, 181))
    yield "65535x65535", jpegs.replace_marker(flat, 0xC0, jpegs.sof(65535, 65535))
    yield "frame length off", jpegs.replace_marker(
        flat, 0xC0, jpegs.sof(320, 180)[:-3] + b"")
    segments, tail = jpegs.split(flat)
    yield "no frame", jpegs.join([s for s in segments if s[1] != 0xC0], tail)
    yield "SOS before SOF", jpegs.join([segments[0], segments[-1], *segments[1:-1]], tail)


def _scan_rows(flat):
    yield "progressive scan", jpegs.replace_marker(flat, 0xDA, jpegs.sos(3, ss=0, se=0))
    yield "successive approx", jpegs.replace_marker(flat, 0xDA, jpegs.sos(3, ahal=0x10))
    yield "scan of one of three", jpegs.replace_marker(flat, 0xDA, jpegs.sos(1))
    segments, tail = jpegs.split(flat)
    yield "second SOS", flat[:-2] + segments[-1] + b"\x12\x34" + flat[-2:]
    yield "DHT inside the scan", flat[:-2] + segments[4] + flat[-2:]
    yield "DNL in the scan", flat[:-2] + jpegs.segment(0xDC, b"\x00\xb4") + flat[-2:]
    yield "TEM in the scan", flat[:-2] + b"\xff\x01" + flat[-2:]
    yield "no EOI", flat[:-2]
    yield "EOI then junk", flat + b"\x00"
    yield "EOI then a second image", flat + flat
    yield "EOI in the middle", flat[:-2] + b"\xff\xd9\x12\x34" + flat[-2:]
    yield "ends in fill", flat[:-2] + b"\xff\xff"
    yield "trailing lone FF", flat + b"\xff"


def _segment_rows(flat):
    segments, tail = jpegs.split(flat)
    yield "fill between segments", jpegs.join([segments[0], b"\xff", *segments[1:]], tail)
    yield "segment length 0", jpegs.insert_after_app0(flat, b"\xff\xfe\x00\x00")
    yield "segment length 1", jpegs.insert_after_app0(flat, b"\xff\xfe\x00\x01")
    yield "standalone RST in the header", jpegs.insert_after_app0(flat, b"\xff\xd0")
    yield "EOI before the scan", jpegs.insert_after_app0(flat, b"\xff\xd9")
    yield "DAC (arithmetic tables)", jpegs.insert_after_app0(flat, jpegs.segment(0xCC, b"\0\0"))
    yield "JPG extension marker", jpegs.insert_after_app0(flat, jpegs.segment(0xF0, b"\0\0"))
    yield "garbage between segments", jpegs.join([segments[0], b"\x00", *segments[1:]], tail)
    yield "SOS running past the end", jpegs.join(segments[:-1], b"") + b"\xff\xda\x00\x40\x03"
    yield "DQT running past the end", jpegs.join(segments[:1], b"") + b"\xff\xdb\xff\xff\x00"


ROWS = [*(("app0",) + r for r in _app0_first_rows(jpegs.engine_jpeg("flat"))),
        *(("frame",) + r for r in _frame_rows(jpegs.engine_jpeg("flat"))),
        *(("scan",) + r for r in _scan_rows(jpegs.engine_jpeg("flat"))),
        *(("segment",) + r for r in _segment_rows(jpegs.engine_jpeg("flat")))]


@pytest.mark.parametrize("group,name,data", ROWS, ids=[f"{g}-{n}" for g, n, _ in ROWS])
def test_group_c_structure_rows_are_refused(group, name, data):
    assert not check_engine_jpeg(data, THUMB), name
    assert not structure(data, THUMB), name


def test_every_truncation_is_refused(flat):
    for cut in range(len(flat)):
        assert not check_engine_jpeg(flat[:cut], THUMB), cut


@pytest.mark.parametrize("value", [None, "", "\xff\xd8", 0, memoryview(b"\xff\xd8"), [255, 216],
                                   b"", b"\xff", b"\xff\xd8", b"\xff\xd8\xff\xe0"])
def test_odd_inputs_are_refused_without_raising(value):
    assert check_engine_jpeg(value, THUMB) is False


def test_random_mutations_never_raise(flat, noise):
    rng = random.Random(11)
    for base in (flat, noise[:3000] + noise[-2:]):
        for _ in range(1500):
            data = bytearray(base)
            for _ in range(rng.randint(1, 4)):
                op = rng.random()
                at = rng.randrange(len(data))
                if op < 0.6:
                    data[at] = rng.randrange(256)
                elif op < 0.8:
                    del data[at:at + rng.randint(1, 8)]
                else:
                    data[at:at] = bytes((0xFF, rng.randrange(256)))
            assert check_engine_jpeg(bytes(data), THUMB) in (True, False)


def test_the_worst_case_input_is_checked_in_linear_time(flat):
    """96 KiB that keeps the check busiest: ``FF 00`` pairs, ``FF D0`` pairs, then fill."""
    room = ENGINE_JPEG_MAX_BYTES - len(flat)
    for filler in (b"\xff\x00", b"\xff\xd3", b"\xff"):
        data = flat[:-2] + (filler * room)[:room - room % len(filler)] + flat[-2:]
        assert len(data) <= ENGINE_JPEG_MAX_BYTES
        started = time.perf_counter()
        assert check_engine_jpeg(data, THUMB)
        assert time.perf_counter() - started < 0.5

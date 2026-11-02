"""``render/thumbnail.py`` (F11 ``04`` §5.3, §7.5 step 5, §11; SEC-F11-01, SEC-F11-02;
abuse group C, the decode rows; AC-F11-17's unit layer).

``make_thumbnail`` shrinks a scene to 320×180 24-bit; ``encode_jpeg`` writes a baseline JPEG
that ``check_engine_jpeg`` accepts; ``decode_jpeg`` decodes only accepted bytes, from
``BytesIO``, and re-checks the size. The property SEC-F11-01 relies on is tested against
the pinned wheel: for bytes the structure check accepts, SDL_image picks its JPEG decoder,
whatever ``<svg``, ``ftyp``, or ``GIF8`` bytes appear inside."""

import ast
import io
import random
from pathlib import Path

import pygame
import pytest

from engine.core import imageheader
from engine.core.imageheader import ENGINE_JPEG_MAX_BYTES, check_engine_jpeg
from engine.render import thumbnail
from engine.render.thumbnail import THUMB_SIZE, decode_jpeg, encode_jpeg, make_thumbnail
from tests.fakes import jpegs

THUMBNAIL_PATH = Path(thumbnail.__file__)
RED = (220, 20, 20)


def scene(size, *, depth: int = 32, flags: int = 0, colour=RED) -> pygame.Surface:
    surface = pygame.Surface(size, flags, depth)
    surface.fill(colour)
    return surface


def close_to(actual, expected, tolerance: int = 12) -> bool:
    return all(abs(a - e) <= tolerance for a, e in zip(actual[:3], expected[:3]))


class LoadSpy:
    """Counts ``pygame.image.load`` calls (then makes them)."""

    def __init__(self, patch) -> None:
        self.calls = 0
        real = pygame.image.load

        def load(*args, **kwargs):
            self.calls += 1
            return real(*args, **kwargs)
        patch.setattr(thumbnail.pygame.image, "load", load)


# --- make_thumbnail ---------------------------------------------------------------------------

def test_any_scene_becomes_a_320x180_24_bit_thumbnail():
    for size in [(1280, 720), (1920, 1080), (3840, 2160), (320, 180), (100, 50), (1, 1),
                 (1024, 768)]:
        for depth in (24, 32):
            source = scene(size, depth=depth)
            thumb = make_thumbnail(source)
            assert thumb.get_size() == THUMB_SIZE, (size, depth)
            assert thumb.get_bitsize() == 24, (size, depth)
            assert close_to(thumb.get_at((160, 90)), RED), (size, depth)
            assert close_to(source.get_at((0, 0)), RED), (size, depth)   # the scene is unchanged


def test_the_picture_is_shrunk_not_cropped():
    source = scene((1280, 720), colour=(0, 0, 255))
    source.fill(RED, (0, 0, 640, 720))                         # left half red
    thumb = make_thumbnail(source)
    assert close_to(thumb.get_at((40, 90)), RED)
    assert close_to(thumb.get_at((280, 90)), (0, 0, 255))


def test_an_alpha_scene_an_8_bit_scene_and_a_subsurface_work():
    alpha = scene((640, 360), flags=pygame.SRCALPHA, colour=(*RED, 255))
    assert close_to(make_thumbnail(alpha).get_at((10, 10)), RED)
    clear = scene((640, 360), flags=pygame.SRCALPHA, colour=(255, 255, 255, 0))
    assert close_to(make_thumbnail(clear).get_at((10, 10)), (0, 0, 0))   # over black
    eight = pygame.Surface((640, 360), 0, 8)
    eight.fill((255, 255, 255))
    thumb = make_thumbnail(eight)
    assert thumb.get_bitsize() == 24 and thumb.get_size() == THUMB_SIZE
    frame = scene((1920, 1200))
    view = frame.subsurface((0, 60, 1920, 1080))
    assert make_thumbnail(view).get_size() == THUMB_SIZE


@pytest.mark.parametrize("size", [(0, 0), (0, 10), (10, 0)])
def test_an_empty_scene_gives_a_black_thumbnail(size):
    thumb = make_thumbnail(pygame.Surface(size))
    assert thumb.get_size() == THUMB_SIZE
    assert tuple(thumb.get_at((0, 0)))[:3] == (0, 0, 0)


# --- encode_jpeg ------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["flat", "bands", "noise"])
def test_encode_gives_bytes_the_check_accepts(kind):
    data = jpegs.engine_jpeg(kind)
    surface = pygame.image.load(io.BytesIO(data), "t.jpg")
    encoded = encode_jpeg(make_thumbnail(surface))
    assert encoded is not None
    assert check_engine_jpeg(encoded, THUMB_SIZE)
    assert len(encoded) <= ENGINE_JPEG_MAX_BYTES
    assert jpegs.markers(encoded) == [0xE0, 0xDB, 0xDB, 0xC0, 0xC4, 0xC4, 0xC4, 0xC4, 0xDA]


def test_noise_the_largest_picture_fits_well_under_the_cap():
    rng = random.Random(5)
    pixels = rng.randbytes(320 * 180 * 3)
    thumb = pygame.image.frombuffer(pixels, THUMB_SIZE, "RGB").copy()
    encoded = encode_jpeg(thumb)
    assert encoded is not None and len(encoded) < ENGINE_JPEG_MAX_BYTES // 2


@pytest.mark.parametrize("size", [(321, 180), (320, 181), (640, 360), (1, 1)])
def test_encode_refuses_a_surface_that_is_not_320x180(size):
    assert encode_jpeg(scene(size)) is None


def test_encode_gives_none_when_the_encoder_fails(monkeypatch):
    def fail(*_args, **_kwargs):
        raise pygame.error("no JPEG support")
    with monkeypatch.context() as patch:
        patch.setattr(thumbnail.pygame.image, "save", fail)
        assert encode_jpeg(scene(THUMB_SIZE, depth=24)) is None


def test_encode_gives_none_when_the_check_refuses(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(thumbnail, "check_engine_jpeg", lambda data, size: False)
        assert encode_jpeg(scene(THUMB_SIZE, depth=24)) is None


# --- decode_jpeg: round trip -------------------------------------------------------------------

def test_round_trip_keeps_the_picture():
    source = scene((1280, 720), colour=(0, 0, 255))
    source.fill(RED, (0, 0, 640, 720))
    picture = decode_jpeg(encode_jpeg(make_thumbnail(source)))
    assert picture is not None and picture.get_size() == THUMB_SIZE
    assert close_to(picture.get_at((40, 90)), RED, 24)
    assert close_to(picture.get_at((280, 90)), (0, 0, 255), 24)


def test_decode_accepts_bytearray_and_padding_up_to_the_cap():
    data = jpegs.engine_jpeg("bands")
    assert decode_jpeg(bytearray(data)).get_size() == THUMB_SIZE
    padded = jpegs.pad_to(data, ENGINE_JPEG_MAX_BYTES)
    assert decode_jpeg(padded).get_size() == THUMB_SIZE


# --- decode_jpeg: refused before pygame sees a byte (SEC-F11-01, -02) -------------------------

def _refused_rows():
    flat = jpegs.engine_jpeg("flat")
    yield "svg confusion 8000", jpegs.svg_confusion(8000)
    yield "svg confusion 16384", jpegs.svg_confusion(16384)
    yield "real JPEG with an svg comment", jpegs.insert_after_app0(flat, jpegs.SVG_COMMENT)
    yield "svg in APP1", jpegs.insert_after_app0(flat, jpegs.segment(0xE1, b"<svg>"))
    yield "ftyp at offset 4", flat[:4] + b"ftyp" + flat[8:]
    yield "truncated at half", flat[:len(flat) // 2]
    yield "no EOI", flat[:-2]
    yield "oversized by one byte", jpegs.pad_to(flat, ENGINE_JPEG_MAX_BYTES + 1)
    yield "progressive (SOF2)", jpegs.replace_marker(flat, 0xC0, jpegs.sof(320, 180,
                                                                            marker=0xC2))
    yield "progressive scan", jpegs.replace_marker(flat, 0xDA, jpegs.sos(3, se=0))
    yield "wrong size 320x181", jpegs.engine_jpeg("flat", (320, 181))
    yield "wrong size 640x360", jpegs.engine_jpeg("flat", (640, 360))
    yield "two frames", jpegs.insert_after_app0(flat, jpegs.sof(320, 180))
    yield "4 components", jpegs.replace_marker(flat, 0xC0, jpegs.sof(320, 180, components=4))
    yield "PNG", b"\x89PNG\r\n\x1a\n" + b"\0" * 64
    yield "GIF", b"GIF89a" + b"\0" * 64
    yield "empty", b""


REFUSED = list(_refused_rows())


@pytest.mark.parametrize("name,data", REFUSED, ids=[name for name, _ in REFUSED])
def test_group_c_bytes_are_refused_without_a_decode(monkeypatch, name, data):
    with monkeypatch.context() as patch:
        spy = LoadSpy(patch)
        assert decode_jpeg(data) is None, name
    assert spy.calls == 0, name


def test_truncated_input_is_refused():
    data = jpegs.engine_jpeg("flat")
    for cut in range(0, 1589, 97):
        assert decode_jpeg(data[:cut]) is None, cut


@pytest.mark.parametrize("value", [None, "text", 7, memoryview(b"\xff\xd8")])
def test_non_bytes_are_refused(value):
    assert decode_jpeg(value) is None


# --- decode_jpeg: accepted bytes that still fail -----------------------------------------------

def test_a_structure_without_tables_gives_none_from_the_decoder(monkeypatch):
    app0 = jpegs.segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    data = (jpegs.SOI + app0 + jpegs.sof(320, 180) + jpegs.sos(3) + b"\x12\x34" * 10
            + jpegs.EOI)
    assert check_engine_jpeg(data, THUMB_SIZE)
    with monkeypatch.context() as patch:
        spy = LoadSpy(patch)
        assert decode_jpeg(data) is None
    assert spy.calls == 1


@pytest.mark.parametrize("error", [pygame.error("bad"), MemoryError(), ValueError("x"),
                                   OSError("io")])
def test_decoder_errors_give_none(monkeypatch, error):
    def fail(*_args, **_kwargs):
        raise error
    with monkeypatch.context() as patch:
        patch.setattr(thumbnail.pygame.image, "load", fail)
        assert decode_jpeg(jpegs.engine_jpeg("flat")) is None


def test_the_decoded_size_is_checked_again(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(thumbnail.pygame.image, "load",
                      lambda *_a, **_k: pygame.Surface((8000, 8000 // 16)))
        assert decode_jpeg(jpegs.engine_jpeg("flat")) is None


def test_decode_reads_from_bytesio_never_a_path(monkeypatch):
    seen = []
    real = pygame.image.load
    with monkeypatch.context() as patch:
        patch.setattr(thumbnail.pygame.image, "load",
                      lambda source, *rest: seen.append((source, rest)) or real(source, *rest))
        assert decode_jpeg(jpegs.engine_jpeg("flat")) is not None
    ((source, rest),) = seen
    assert isinstance(source, io.BytesIO)
    assert rest == ("t.jpg",)


# --- The property behind the check (pinned wheel) ----------------------------------------------

@pytest.mark.parametrize("inside", [jpegs.SVG_COMMENT,
                                    jpegs.segment(0xE1, b"<svg width='16384' height='16384'>"),
                                    jpegs.com(b"\0\0\0\x18ftypavif\0\0\0\0avifmif1"),
                                    jpegs.com(b"GIF89a\x40\x1f\x40\x1f")])
def test_a_real_jpeg_with_foreign_magic_inside_still_decodes_as_its_jpeg(inside):
    """SEC-F11-01's property: bytes the whole-structure check accepts reach only the JPEG
    decoder. A real thumbnail carrying an SVG (or AVIF, GIF) inside decodes as the same
    320×180 JPEG, never as the 8000×8000 SVG it names. (``check_engine_jpeg`` also refuses
    ``<svg`` as a backstop, so the engine never decodes the first two at all.)"""
    original = jpegs.engine_jpeg("bands")
    data = jpegs.insert_after_app0(original, inside)
    assert imageheader._engine_jpeg_structure(data, THUMB_SIZE)
    picture = pygame.image.load(io.BytesIO(data), "t.jpg")
    expected = pygame.image.load(io.BytesIO(original), "t.jpg")
    assert picture.get_size() == THUMB_SIZE
    assert pygame.image.tobytes(picture, "RGB") == pygame.image.tobytes(expected, "RGB")
    if b"<svg" in inside:
        assert decode_jpeg(data) is None          # the backstop
    else:
        assert decode_jpeg(data).get_size() == THUMB_SIZE


def test_random_mutations_decode_as_320x180_or_none():
    """Every mutation the check accepts decodes to 320×180 (libjpeg tolerates corrupt
    entropy data) or gives None; nothing raises and nothing else comes back."""
    rng = random.Random(23)
    base = jpegs.engine_jpeg("bands")
    accepted = 0
    for _ in range(300):
        data = bytearray(base)
        for _ in range(rng.randint(1, 3)):
            at = rng.randrange(2, len(data))
            data[at] = rng.randrange(256)
        data = bytes(data)
        picture = decode_jpeg(data)
        if check_engine_jpeg(data, THUMB_SIZE):
            accepted += 1
        else:
            assert picture is None
        assert picture is None or picture.get_size() == THUMB_SIZE
    assert accepted > 50                       # most entropy-byte changes stay accepted


# --- Imports and calls (SEC-F11-07a: SEC-F12-01's bans cover render/thumbnail.py) -----------

def test_thumbnail_imports_and_calls():
    tree = ast.parse(THUMBNAIL_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported == {"io", "pygame", "engine.core.imageheader"}
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not called & {"eval", "exec", "compile", "__import__", "open"}
    loads = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "load"]
    assert len(loads) == 1
    (argument, *_) = loads[0].args
    assert ast.unparse(argument) == "io.BytesIO(data)"

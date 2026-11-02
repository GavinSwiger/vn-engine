"""AssetManager: formats, problems and placeholders, caching, the one memory budget.

AC-F01-45 (scaled variants), 46 (pixel filter), 98 (bundled font), 100 (links, asset part),
101 (blocked refs), 102 (missing placeholder), 103 (corrupt/unreadable), 104 (formats), 105
(case suggestions), 106 (loaded once), 108 (budget from config), 109 (preload and hold), 138
(NFC/NFD), 140 (bounded bad-ref cost), 142 (size checked before decoding), 157 (text and
fonts in the budget), 161 (budget in MiB), 166 (asset part: echo cut to 120), and the
``icon_surface`` table of §7.11.7 (AC-F01-22, 23, 139 unit parts).
"""

import logging
import os
import struct
import sys
import unicodedata
import zlib
from pathlib import Path

import pygame
import pytest

from engine.core.constants import FONT_OBJECT_COST, MB
from engine.core.paths import GamePaths, engine_data_dir
from engine.render import assets as assets_module
from engine.render.assets import DEFAULT, MSG_TOO_MANY_PROBLEMS
from engine.render.canvas import RenderQuality
from engine.render.text import FontSpec
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import DrawingScreens, make_app
from tests.fixtures.F04 import gen_images as gen
from tests.render.conftest import FIXTURES, asset_lines, copy_game, make_assets

pytestmark = pytest.mark.display

SLASH = "paths must stay inside the game folder and use forward slashes, e.g. images/bg/club.png"
DAMAGED = "(file is damaged or not a PNG, JPEG, or WebP image)"
NOTO = engine_data_dir() / "fonts" / "NotoSans-Regular.ttf"
OVER_BUDGET_64 = "Asset cache is over its 64 MB limit because all cached assets are in use"


@pytest.fixture(autouse=True)
def _debug_logs(caplog):
    caplog.set_level(logging.DEBUG, logger="vn")


@pytest.fixture
def read_spy(assets_game, monkeypatch):
    """Every ref passed to GamePaths.read_file."""
    reads: list[str] = []
    real = GamePaths.read_file

    def spy(self, ref, *, max_bytes):
        reads.append(ref)
        return real(self, ref, max_bytes=max_bytes)

    monkeypatch.setattr(GamePaths, "read_file", spy)
    return reads


# --- AC-F01-161 / 108: the budget -----------------------------------------------------------

def test_budget_is_cache_mb_mebibytes(assets_game):
    assert make_assets(assets_game, cache_mb=64).cache.budget_bytes == 67_108_864
    assert make_assets(assets_game, cache_mb=512).cache.budget_bytes == 536_870_912


# --- AC-F01-104: formats ----------------------------------------------------------------------

def test_supported_formats_load(assets, read_spy, caplog):
    rgba = assets.image("images/rgba.png")
    assert not rgba.is_placeholder and rgba.size == (64, 64)
    surface = assets.surface(rgba)
    assert surface.get_at((0, 0)).a == 0
    assert tuple(surface.get_at((63, 0))) == (0x33, 0x66, 0xCC, 255)
    lossless = assets.surface(assets.image("images/lossless.webp"))
    assert lossless.get_at((0, 0)).a == 0
    for ref in ("images/photo.jpg", "images/lossy.webp", "images/UPPER.PNG"):
        image = assets.image(ref)
        assert not image.is_placeholder, ref
    assert [line for line in asset_lines(caplog) if line[0] != "DEBUG"] == []


@pytest.mark.parametrize("ref", ["images/anim.gif", "images/bitmap.bmp"])
def test_unsupported_formats_are_not_read(assets, read_spy, caplog, ref):
    image = assets.image(ref)
    assert image.is_placeholder
    warnings = [m for level, m in asset_lines(caplog) if level == "WARNING"]
    assert len(warnings) == 1 and ref in warnings[0] and "unsupported image format" in warnings[0]
    assert ref not in read_spy


def test_converted_alpha_images_blend_and_opaque_ones_match_the_framebuffer(assets):
    surface = assets.surface(assets.image("images/rgba.png"))
    target = pygame.Surface((64, 64))
    target.fill((255, 0, 0))
    target.blit(surface, (0, 0))
    assert target.get_at((0, 0))[:3] == (255, 0, 0)          # S0 note 4: really blends
    photo = assets.surface(assets.image("images/photo.jpg"))
    assert photo.get_bytesize() == 4


@pytest.mark.parametrize("ref", ["fonts/test.ttf", "fonts/test.otf"])
def test_font_files_load_and_render(assets, ref, caplog):
    handle = assets.font(ref, 20)
    assert handle.key == ("font", ref, 20)
    assert handle.font.size("Hello")[0] > 0
    assert [line for line in asset_lines(caplog) if line[0] != "DEBUG"] == []


# --- AC-F01-102 / 103 / 106: placeholders and problems ------------------------------------------

def test_missing_image_placeholder(assets, caplog):
    images = [assets.image("images/bg/none.png") for _ in range(3)]
    for image in images:
        assert image.is_placeholder and image.size == (256, 256)
    surface = assets.surface(images[0])
    assert surface.get_size() == (256, 256)
    colors = {(255, 0, 255), (0, 0, 0)}
    a, b, c = (surface.get_at(p)[:3] for p in ((16, 16), (48, 16), (16, 48)))
    assert a in colors and b in colors and c in colors and a != b
    assert any(surface.get_at((x, y))[:3] == (255, 255, 255)
               for x in range(256) for y in range(100, 156))
    warnings = [m for level, m in asset_lines(caplog) if level != "DEBUG"]
    assert len(warnings) == 1 and warnings[0].startswith("images/bg/none.png not found")
    assert images[0].label == "images/bg/none.png"


def test_missing_image_keeps_the_app_presenting(assets_game):
    window = FakeWindow()
    app, limiter = make_app(window, paths=assets_game)
    app.screens = DrawingScreens(
        lambda canvas, n: canvas.draw_image(app.assets.image("images/bg/none.png"), (0, 0)))
    limiter.quit_at(10)
    assert app.run() == 0
    assert len(window.flips) == 10


@pytest.mark.parametrize("ref, message", [
    ("images/corrupt.png", f"could not read image images/corrupt.png {DAMAGED}"),
    ("images/truncated.png", f"could not read image images/truncated.png {DAMAGED}"),
    ("images/empty.png", f"could not read image images/empty.png {DAMAGED}"),
    ("images/dir.png", "images/dir.png is not a file"),
])
def test_corrupt_or_unreadable_images(assets, caplog, ref, message):
    for _ in range(2):
        assert assets.image(ref).is_placeholder
    assert [(level, m) for level, m in asset_lines(caplog) if level != "DEBUG"] == \
        [("WARNING", message)]


@pytest.mark.skipif(sys.platform == "win32", reason="mode 000 does not block reads on Windows")
def test_unreadable_image(assets_game, caplog):
    locked = assets_game.root / "images" / "locked.png"
    locked.write_bytes((assets_game.root / "images" / "rgba.png").read_bytes())
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("running with permission to read mode-000 files")
        assert make_assets(assets_game).image("images/locked.png").is_placeholder
        assert ("WARNING", "could not read images/locked.png") in asset_lines(caplog)
    finally:
        locked.chmod(0o644)


def test_loaded_once_and_reused(assets, read_spy):
    first = assets.image("images/bg/club.png")
    second = assets.image("images/bg/club.png")
    assert read_spy.count("images/bg/club.png") == 1
    assert assets.surface(first) is assets.surface(second)
    assets.cache.discard(("img", "images/bg/club.png"))
    assets.image("images/bg/club.png")
    assert read_spy.count("images/bg/club.png") == 2


# --- AC-F01-105 / 138: case-exact matching and Unicode normalization -------------------------

def test_case_mismatch_suggestions(assets, caplog):
    assets.image("images/BG/Club.png")
    assets.image("images/bg/Lantern_Street.png")
    assets.image("images/bg/clob.png")
    warnings = [m for level, m in asset_lines(caplog) if level == "WARNING"]
    assert warnings[0] == "images/BG/Club.png not found — did you mean images/bg/club.png?"
    assert "did you mean images/bg/lantern_street.png?" in warnings[1]
    assert "did you mean images/bg/club.png?" in warnings[2]


@pytest.mark.parametrize("on_disk, requested", [("NFD", "NFC"), ("NFC", "NFD")])
def test_unicode_normalization_never_escapes(tmp_path, caplog, on_disk, requested):
    root = tmp_path / "game"
    (root / "images").mkdir(parents=True)
    name = unicodedata.normalize(on_disk, "\u00e9") + ".png"
    surface = pygame.Surface((4, 4))
    pygame.image.save(surface, str(root / "images" / name))
    assets = make_assets(GamePaths.for_game(root))
    image = assets.image("images/" + unicodedata.normalize(requested, "\u00e9") + ".png")
    if image.is_placeholder:
        warnings = [m for level, m in asset_lines(caplog) if level == "WARNING"]
        assert len(warnings) == 1 and "not found" in warnings[0]


# --- AC-F01-101 / 166: blocked references ----------------------------------------------------

def test_blocked_reference_shows_a_placeholder(assets, read_spy, caplog):
    images = [assets.image("../secret.png") for _ in range(3)]
    assert all(image.is_placeholder for image in images)
    assert images[0].label == "blocked path: ../secret.png"
    assert asset_lines(caplog) == [
        ("ERROR", f'Asset path "../secret.png" is not allowed: {SLASH}')]
    handle = assets.font("../f.ttf", 20)
    assert handle.key == ("font", DEFAULT, 20)
    errors = [m for level, m in asset_lines(caplog) if level == "ERROR"]
    assert len(errors) == 2 and errors[1] == f'Asset path "../f.ttf" is not allowed: {SLASH}'


def test_long_refs_are_echoed_to_120_characters(assets, caplog):
    missing = "images/" + "/".join(["m" * 95] * 3) + "xx.png"
    assert len(missing) == 300
    assets.image(missing)
    blocked = "../" + "b" * 293 + ".png"
    image = assets.image(blocked)
    lines = asset_lines(caplog)
    assert lines[0] == ("WARNING", missing[:119] + "… not found")
    assert lines[1] == ("ERROR", f'Asset path "{blocked[:119]}…" is not allowed: {SLASH}')
    assert image.label == f"blocked path: {blocked[:119]}…"


# --- AC-F01-100: links out of the game folder (asset part) --------------------------------------

def _link_or_skip(link: Path, target: Path, *, directory: bool) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this system does not allow creating symlinks ({exc.__class__.__name__})")


def _outside(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes((FIXTURES / "games" / "assets" / "images" /
                                         "rgba.png").read_bytes())
    (outside / "taxes_2025.png").write_bytes(b"x")
    return outside


def _assert_blocked(tmp_path, assets, ref, caplog, monkeypatch, outside):
    scanned = []
    real_scandir = os.scandir
    monkeypatch.setattr(os, "scandir", lambda p=".": scanned.append(str(p)) or real_scandir(p))
    image = assets.image(ref)
    assert image.is_placeholder and image.label == f"blocked path: {ref}"
    text = " ".join(m for _, m in asset_lines(caplog))
    assert f'Asset path "{ref}" is not allowed: {SLASH}' in text
    assert "taxes_2025" not in text and "taxes_2025" not in image.label
    assert not [p for p in scanned if Path(p).resolve().is_relative_to(outside.resolve())]


def test_file_and_directory_symlinks_out_are_blocked(tmp_path, caplog, monkeypatch):
    root = copy_game("assets", tmp_path / "game")
    outside = _outside(tmp_path)
    _link_or_skip(root / "images" / "out.png", outside / "secret.png", directory=False)
    _link_or_skip(root / "images" / "ext", outside, directory=True)
    assets = make_assets(GamePaths.for_game(root))
    _assert_blocked(tmp_path, assets, "images/out.png", caplog, monkeypatch, outside)
    _assert_blocked(tmp_path, assets, "images/ext/taxes.png", caplog, monkeypatch, outside)


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
def test_junction_out_is_blocked(tmp_path, caplog, monkeypatch):
    import _winapi
    root = copy_game("assets", tmp_path / "game")
    outside = _outside(tmp_path)
    _winapi.CreateJunction(str(outside), str(root / "images" / "j"))
    assets = make_assets(GamePaths.for_game(root))
    _assert_blocked(tmp_path, assets, "images/j/secret.png", caplog, monkeypatch, outside)


# --- AC-F01-142: image size is checked before decoding ----------------------------------------

def _png_header(width: int, height: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk
            + struct.pack(">I", zlib.crc32(chunk)) + bytes(64))


def _jpeg_header(width: int, height: int) -> bytes:
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + sof + bytes(64)


def _webp_vp8x(width: int, height: int) -> bytes:
    payload = b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") \
        + (height - 1).to_bytes(3, "little")
    chunk = b"VP8X" + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk


def test_size_bombs_are_rejected_without_decoding(tmp_path, caplog, monkeypatch):
    root = tmp_path / "game"
    (root / "images").mkdir(parents=True)
    (root / "images" / "bomb.png").write_bytes(_png_header(60000, 60000))
    (root / "images" / "bomb.jpg").write_bytes(_jpeg_header(65500, 65500))
    (root / "images" / "bomb.webp").write_bytes(_webp_vp8x(16384, 16384))
    pygame.image.save(pygame.Surface((16384, 1)), str(root / "images" / "wide.png"))
    loads = []
    real_load = pygame.image.load
    monkeypatch.setattr(pygame.image, "load",
                        lambda *a, **k: loads.append(a) or real_load(*a, **k))
    assets = make_assets(GamePaths.for_game(root))
    before = _peak_memory()
    for name, size in (("bomb.png", "60000x60000"), ("bomb.jpg", "65500x65500"),
                       ("bomb.webp", "16384x16384")):
        assert assets.image(f"images/{name}").is_placeholder
    assert _peak_memory() - before < 100 * MB
    assert loads == []
    warnings = [m for level, m in asset_lines(caplog) if level == "WARNING"]
    assert warnings == [
        f"image too large: images/{name} is {size} (limit 16384 px per side and 64 megapixels)"
        for name, size in (("bomb.png", "60000x60000"), ("bomb.jpg", "65500x65500"),
                           ("bomb.webp", "16384x16384"))]
    assert not assets.image("images/wide.png").is_placeholder


# --- AC-F01-108: a 7680×4320 image with cache_mb = 64 --------------------------------------------

@pytest.fixture(scope="module")
def big_png(tmp_path_factory) -> bytes:
    """Written with zlib level 1 (``gen_images.png_bytes``): 0.3 s, not ``image.save``'s 0.8 s."""
    pygame.init()
    surface = pygame.Surface((7680, 4320))
    surface.fill((10, 20, 30))
    return gen.png_bytes(surface)


def test_big_image_over_a_small_budget(tmp_path, caplog, big_png):
    root = copy_game("assets", tmp_path / "game")
    (root / "images" / "big.png").write_bytes(big_png)
    window = FakeWindow((1280, 720), probe_points=[(5, 5)])
    app, limiter = make_app(window, cache_mb=64, paths=GamePaths.for_game(root))
    assert app.assets.cache.budget_bytes == 67_108_864
    app.screens = DrawingScreens(
        lambda canvas, n: canvas.draw_image(app.assets.image("images/big.png"), (0, 0)))
    limiter.quit_at(5)
    assert app.run() == 0
    assert len(window.flips) == 5 and window.flips[-1].probes[(5, 5)] == (10, 20, 30)
    warnings = [m for level, m in asset_lines(caplog) if level == "WARNING"]
    assert warnings == [OVER_BUDGET_64]


def test_seventy_megapixel_cap_allows_7680x4320(tmp_path, big_png):
    root = tmp_path / "game"
    (root / "images").mkdir(parents=True)
    (root / "images" / "big.png").write_bytes(big_png)
    image = make_assets(GamePaths.for_game(root)).image("images/big.png")
    assert not image.is_placeholder and image.size == (7680, 4320)


# --- AC-F01-45 / 46: scaled variants ------------------------------------------------------------

def test_scaled_variants(tmp_path, monkeypatch):
    root = tmp_path / "game"
    (root / "images").mkdir(parents=True)
    pygame.image.save(pygame.Surface((300, 200)), str(root / "images" / "src.png"))
    assets = make_assets(GamePaths.for_game(root))
    image = assets.image("images/src.png")
    smooth_calls = []
    real_smooth = pygame.transform.smoothscale
    monkeypatch.setattr(pygame.transform, "smoothscale",
                        lambda s, size: smooth_calls.append(size) or real_smooth(s, size))
    assert assets.scaled(image, 1.0, 1.0, RenderQuality.FINAL) is assets.surface(image)
    entries = len(assets.cache)
    variant = assets.scaled(image, 1.5, 1.5, RenderQuality.FINAL)
    assert variant.get_size() == (450, 300) and smooth_calls == [(450, 300)]
    assert len(assets.cache) == entries + 1
    fast = assets.scaled(image, 1.5, 1.5, RenderQuality.FAST)
    assert fast.get_size() == (450, 300) and len(assets.cache) == entries + 1
    assert smooth_calls == [(450, 300)]
    assert assets.scaled(image, 0.5, 0.5, RenderQuality.FINAL).get_size() == (150, 100)
    assert assets.scaled(image, 0.001, 0.001, RenderQuality.FINAL).get_size() == (1, 1)
    calls_before = len(smooth_calls)
    assert assets.scaled(image, 1.5, 1.5, RenderQuality.FINAL) is variant
    assert len(smooth_calls) == calls_before


@pytest.mark.parametrize("scale_filter, exact", [("pixel", True), ("smooth", False)])
def test_pixel_filter(assets_game, scale_filter, exact):
    assets = make_assets(assets_game, scale_filter=scale_filter)
    variant = assets.scaled(assets.image("images/checker2.png"), 2.0, 2.0, RenderQuality.FINAL)
    pixels = {variant.get_at((x, y))[:3] for x in range(4) for y in range(4)}
    if exact:
        assert pixels <= {(0, 0, 0), (255, 255, 255)}
    else:
        assert pixels - {(0, 0, 0), (255, 255, 255)}


# --- AC-F01-109: preload and hold -----------------------------------------------------------------

def test_preload_and_hold(assets_game, read_spy):
    refs = ["images/bg/club.png", "images/rgba.png"]
    assets = make_assets(assets_game)
    assets.preload(refs)
    assert sorted(read_spy) == sorted(refs)
    for frame in range(1, 6):
        assets.time.frame = frame
        for ref in refs:
            assets.image(ref)
    assert sorted(read_spy) == sorted(refs)

    small = make_assets(assets_game, budget_bytes=2 * MB)          # club.png alone is 3.5 MB
    hold = small.hold(refs)
    for frame in range(10, 110):
        small.time.frame = frame
        small.text_line(small.font(None, 20), f"line {frame}", (255, 255, 255))
        assert ("img", refs[0]) in small.cache and ("img", refs[1]) in small.cache
    hold.release()
    small.time.frame = 200
    small.text_line(small.font(None, 20), "after release", (255, 255, 255))
    assert ("img", refs[0]) not in small.cache


# --- AC-F01-98 / 164: the bundled font ------------------------------------------------------------

def test_bundled_font_covers_latin(assets):
    assert (engine_data_dir() / "fonts" / "OFL.txt").stat().st_size > 0
    font = pygame.font.Font(str(NOTO), 20)
    code_points = [*range(0x20, 0x7F), *range(0xA0, 0x100), *range(0x100, 0x180)]
    assert len(code_points) == 319
    for cp in code_points:
        assert font.metrics(chr(cp))[0] is not None, hex(cp)
    handle = assets.font(None, 20)
    assert handle.key == ("font", DEFAULT, 20)
    assert assets.cache.cost(("fontfile", DEFAULT)) == NOTO.stat().st_size


def test_missing_and_corrupt_fonts_fall_back_once(assets, read_spy, caplog):
    default = assets.font(None, 20)
    for ref in ("fonts/Nope.ttf", "fonts/corrupt.ttf"):
        for _ in range(3):
            handle = assets.font(ref, 20)
            assert handle is default
    warnings = [m for level, m in asset_lines(caplog) if level == "WARNING"]
    assert len(warnings) == 2
    assert warnings[0].startswith("fonts/Nope.ttf not found")
    assert warnings[1].startswith("could not read font fonts/corrupt.ttf")
    assert read_spy.count("fonts/corrupt.ttf") == 1


def test_unicode_paths_load(tmp_path):
    root = copy_game("unicode", tmp_path / "My Games" / "José" / "マイゲーム")
    assets = make_assets(GamePaths.for_game(root))
    image = assets.image("images/背景/é.png")
    assert not image.is_placeholder and image.size == (64, 32)
    serif = assets.font("fonts/フォント.ttf", 20)
    assert serif.key[1] == "fonts/フォント.ttf"
    assert serif.font.size("Hello") != assets.font(None, 20).font.size("Hello")


# --- AC-F01-157: text and fonts count toward the budget ---------------------------------------

LINES = (FIXTURES / "text" / "lines300.txt").read_text(encoding="utf-8").splitlines()


def _text_keys(assets):
    return [key for key in assets.cache.keys() if key[0] == "text"]


def test_text_lines_stay_within_the_budget(tmp_path):
    window = FakeWindow((3840, 2160))
    app, limiter = make_app(window, cache_mb=64)
    costs_ok = []

    def draw(canvas, n):
        canvas.draw_text(LINES[(n - 1) % 300], FontSpec(None, 28), (255, 255, 255), (80, 300))
        cache = app.assets.cache
        costs_ok.append(cache.total_cost <= 67_108_864 and all(
            cache.cost(key) == _surface_area(cache, key) * 4 + 256 for key in _text_keys(app.assets)))

    app.screens = DrawingScreens(draw)
    limiter.quit_at(300)
    assert app.run() == 0
    assert len(costs_ok) == 300 and all(costs_ok)
    assert len(_text_keys(app.assets)) < 300


def _surface_area(cache, key):
    surface = cache._entries[key].value
    return surface.get_width() * surface.get_height()


def test_all_lines_in_one_frame_go_over_budget_once(caplog):
    window = FakeWindow((3840, 2160))
    app, limiter = make_app(window, cache_mb=64)

    def draw(canvas, n):
        for line in LINES:
            canvas.draw_text(line, FontSpec(None, 28), (255, 255, 255), (80, 300))

    app.screens = DrawingScreens(draw)
    limiter.quit_at(2)
    app.run()
    assert app.assets.cache.over_budget
    assert [m for _, m in asset_lines(caplog)].count(OVER_BUDGET_64) == 1


def test_font_file_is_charged_once(assets):
    for size in range(10, 20):
        assets.font(None, size)
    keys = assets.cache.keys()
    assert [key for key in keys if key[0] == "fontfile"] == [("fontfile", DEFAULT)]
    assert assets.cache.cost(("fontfile", DEFAULT)) == NOTO.stat().st_size
    font_keys = [key for key in keys if key[0] == "font"]
    assert len(font_keys) == 10
    assert all(assets.cache.cost(key) == FONT_OBJECT_COST == 262_144 for key in font_keys)


def test_resize_settle_creates_no_new_font_or_text(tmp_path):
    window = FakeWindow((1920, 1080))
    app, limiter = make_app(window, fps=20)              # frames 50 ms apart
    spec = FontSpec(None, 48)
    snapshots = {}

    def keys():
        return {key for key in app.assets.cache.keys() if key[0] in ("font", "text")}

    app.screens = DrawingScreens(
        lambda canvas, n: canvas.draw_text("Fixture Game", spec, (224, 224, 224), (640, 360),
                                           anchor="center"))
    limiter.at(3, lambda: snapshots.update(before=keys()))
    for step in range(30):
        limiter.at(3 + step, lambda s=step: window.resize(1000 + 37 * s, 600 + 13 * s))
    limiter.at(33, lambda: snapshots.update(after=keys()))
    limiter.quit_at(40)
    app.run()
    assert snapshots["after"] == snapshots["before"]
    new_fonts = {key for key in keys() - snapshots["before"] if key[0] == "font"}
    assert len(new_fonts) <= 1


# --- AC-F01-140: bad references have a bounded cost ----------------------------------------------

def _peak_memory() -> int:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        get_info = kernel32.K32GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        get_info.restype = wintypes.BOOL
        assert get_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return counters.PeakWorkingSetSize
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


@pytest.mark.parametrize("count", [10_000, pytest.param(100_000, marks=pytest.mark.slow)])
def test_missing_refs_have_a_bounded_cost(assets, caplog, count):
    """AC-F01-140. 10,000 refs already pass every bound (4,096 failed refs, 1,000 warn-once
    keys); the AC's 100,000 (about 4 s) runs in the ``slow`` tier."""
    caplog.set_level(logging.WARNING, logger="vn")
    before = _peak_memory()
    for _ in range(2):
        for n in range(count):
            assert assets.image(f"images/missing/{n}.png").is_placeholder
    assert len(assets._placeholders) <= 64
    assert len(assets._failed) <= 4096
    assert len(assets._problem_keys) <= 1000
    lines = asset_lines(caplog)
    assert len(lines) <= 1001
    assert lines[-1] == ("WARNING", MSG_TOO_MANY_PROBLEMS)
    assert [m for _, m in lines].count(MSG_TOO_MANY_PROBLEMS) == 1
    assert _peak_memory() - before <= 64 * MB


# --- window icon (§7.11.7; AC-F01-22, 23, 139 unit parts) -----------------------------------

def _engine_icon_pixels(surface) -> bytes:
    return pygame.image.tobytes(surface, "RGBA")


@pytest.fixture
def engine_icon():
    return _engine_icon_pixels(pygame.image.load(str(engine_data_dir() / "icon.png")))


@pytest.mark.parametrize("ref", ["gui/lantern.png", "gui/UPPER.PNG"])
def test_custom_icon(assets, ref, caplog):
    surface = assets.icon_surface(ref)
    expected = (255, 0, 0) if ref == "gui/lantern.png" else (0, 255, 0)
    assert surface.get_at((32, 32))[:3] == expected
    assert [line for line in asset_lines(caplog) if line[0] != "DEBUG"] == []


@pytest.mark.parametrize("ref, level, message, read", [
    (None, None, None, False),
    ("gui/icon.jpg", "WARNING",
     'Window icon "gui/icon.jpg" must be a PNG file — using the engine icon', False),
    ("", "WARNING", 'Window icon "" must be a PNG file — using the engine icon', False),
    ("../x.jpg", "WARNING",
     'Window icon "../x.jpg" must be a PNG file — using the engine icon', False),
    ("../x.png", "ERROR",
     f'Asset path "../x.png" is not allowed: {SLASH} — using the engine icon', False),
    ("C:/icon.png", "ERROR",
     f'Asset path "C:/icon.png" is not allowed: {SLASH} — using the engine icon', False),
    ("gui/con.png", "ERROR",
     'Asset path "gui/con.png" is not allowed: "con" is a reserved file name on Windows'
     ' — using the engine icon', False),
    ("gui/missing.png", "WARNING",
     "Window icon gui/missing.png could not be used (not found) — using the engine icon",
     False),
    ("gui/corrupt.png", "WARNING", "Window icon gui/corrupt.png could not be used (", True),
    ("gui/Lantern.png", "WARNING", "Window icon gui/Lantern.png could not be used (not found"
     " — did you mean gui/lantern.png?) — using the engine icon", False),
])
def test_icon_problems_use_the_engine_icon(assets, caplog, engine_icon, monkeypatch,
                                           ref, level, message, read):
    reads = []
    real = GamePaths.read_file

    def spy(self, path_ref, *, max_bytes):
        data = real(self, path_ref, max_bytes=max_bytes)
        reads.append(path_ref)
        return data

    monkeypatch.setattr(GamePaths, "read_file", spy)
    surface = assets.icon_surface(ref)
    assert _engine_icon_pixels(surface) == engine_icon
    lines = [line for line in asset_lines(caplog) if line[0] != "DEBUG"]
    if level is None:
        assert lines == []
    else:
        assert len(lines) == 1 and lines[0][0] == level
        assert lines[0][1].startswith(message) and lines[0][1].endswith(
            "— using the engine icon")
    assert (ref in reads) is read


def test_engine_icon_is_256_square():
    icon = pygame.image.load(str(engine_data_dir() / "icon.png"))
    assert icon.get_size() == (256, 256)
    assert icon.get_flags() & pygame.SRCALPHA


def test_module_reads_game_files_only_through_read_file():
    source = Path(assets_module.__file__).read_text(encoding="utf-8")
    assert "open(" not in source
    assert source.count("read_bytes()") == 2       # the two trusted engine files

"""The bundled Noto Sans faces and the F05 font API (F05 `04` §5.3, §7.6, §18.1).

AC-F05-42: Bold, Italic, and Bold Italic sit next to Regular (hashes: tests/test_supply_chain.py)
and the error screen still requests only Regular. Unit rows for ``AssetManager.font(…,
bundled=, synth=)`` and ``check()``. AC-F05-10 and AC-F05-31 (the FaceSet table and the
drawn faces) join this file at F05 step 6.
"""

import logging

import pygame
import pytest

from engine.core.constants import FONT_OBJECT_COST
from engine.core.paths import GamePaths, engine_data_dir
from engine.render.assets import (
    BUNDLED_FILES,
    BUNDLED_NAMES,
    DEFAULT,
    AssetManager,
    AssetProblem,
    Face,
    Synth,
)
from engine.render.placeholder import PLACEHOLDER_SIZE
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import make_app
from tests.render.conftest import asset_lines, make_assets

pytestmark = pytest.mark.display

FONTS = engine_data_dir() / "fonts"
TEXT = "The quick brown fox jumps over the lazy dog"


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


def problems(caplog) -> list[tuple[str, str]]:
    return [(level, message) for level, message in asset_lines(caplog)
            if level in ("WARNING", "ERROR")]


# --- AC-F05-42: the bundled faces ----------------------------------------------------------------

def test_the_four_faces_sit_next_to_regular():
    for face, file in BUNDLED_FILES.items():
        assert (engine_data_dir() / file).is_file(), face
        assert (engine_data_dir() / file).parent == FONTS
    assert (FONTS / "OFL.txt").is_file() and (FONTS / "SOURCE.txt").is_file()


@pytest.mark.parametrize("face", list(Face))
def test_each_bundled_face_loads_under_its_own_name(assets, face):
    handle = assets.font(None, 28, bundled=face)
    assert handle.key == ("font", BUNDLED_NAMES[face], 28)
    assert assets.cache.cost(("fontfile", BUNDLED_NAMES[face])) == \
        (engine_data_dir() / BUNDLED_FILES[face]).stat().st_size
    # The real face, unsynthesized: it measures as the file opened directly.
    direct = pygame.font.Font(str(engine_data_dir() / BUNDLED_FILES[face]), 28)
    assert handle.font.size(TEXT) == direct.size(TEXT)
    for cp in (0x41, 0xE9, 0x17E, 0x3A9, 0x416):      # Latin, Latin-1, Ext-A, Greek, Cyrillic
        assert handle.font.metrics(chr(cp))[0] is not None, (face, hex(cp))


def test_bundled_faces_differ_from_regular(assets):
    widths = {face: assets.font(None, 28, bundled=face).font.size(TEXT)[0] for face in Face}
    assert widths[Face.BOLD] > widths[Face.REGULAR]
    assert widths[Face.BOLD_ITALIC] > widths[Face.ITALIC]
    regular = pygame.font.Font(str(FONTS / "NotoSans-Regular.ttf"), 28)
    assert widths[Face.REGULAR] == regular.size(TEXT)[0]
    italic = assets.font(None, 28, bundled=Face.ITALIC).font.render("l", True, (0, 0, 0))
    upright = assets.font(None, 28).font.render("l", True, (0, 0, 0))
    assert italic.get_bounding_rect() != upright.get_bounding_rect()


def test_default_call_is_still_regular(assets):
    assert assets.font(None, 20) is assets.font(None, 20, bundled=Face.REGULAR)
    assert assets.font(None, 20).key == ("font", DEFAULT, 20)


def test_error_screen_requests_only_regular(monkeypatch):
    """AC-F05-42: the error screen keeps the bundled Regular (ADR-0004)."""
    calls: list[tuple] = []
    real = AssetManager.font

    def spy(self, ref, size_px, *, bundled=Face.REGULAR, synth=Synth.NONE):
        calls.append((ref, bundled, synth))
        return real(self, ref, size_px, bundled=bundled, synth=synth)

    monkeypatch.setattr(AssetManager, "font", spy)
    app, limiter = make_app(FakeWindow((1280, 720)))
    app.show_fatal_error(RuntimeError("boom"))
    limiter.quit_at(1)
    app.run()
    assert calls
    assert set(calls) == {(None, Face.REGULAR, Synth.NONE)}
    file_keys = {key for key in app.assets.cache.keys() if key[0] == "fontfile"}
    assert file_keys == {("fontfile", DEFAULT)}


# --- font(…, synth=) -------------------------------------------------------------------------------

@pytest.mark.parametrize("synth, bold, italic", [
    (Synth.BOLD, True, False), (Synth.ITALIC, False, True), (Synth.BOLD_ITALIC, True, True)])
def test_synthetic_styles_use_their_own_font_object(assets, synth, bold, italic):
    plain = assets.font("fonts/test.ttf", 28)
    styled = assets.font("fonts/test.ttf", 28, synth=synth)
    assert styled.key == ("font", "fonts/test.ttf", 28, synth)
    assert styled.font is not plain.font
    assert (styled.font.bold, styled.font.italic) == (bold, italic)
    assert not plain.font.bold and not plain.font.italic          # never set on a shared font
    assert assets.font("fonts/test.ttf", 28, synth=synth) is styled
    assert assets.cache.cost(styled.key) == FONT_OBJECT_COST


def test_synthetic_bold_measures_wider(assets):
    plain = assets.font("fonts/test.ttf", 28).font.size(TEXT)[0]
    bold = assets.font("fonts/test.ttf", 28, synth=Synth.BOLD).font.size(TEXT)[0]
    assert bold > plain


def test_synthetic_styles_share_the_file_charge(assets, read_spy):
    for synth in Synth:
        assets.font("fonts/test.ttf", 28, synth=synth)
    assert read_spy.count("fonts/test.ttf") == 1
    file_keys = [key for key in assets.cache.keys() if key[0] == "fontfile"]
    assert file_keys == [("fontfile", "fonts/test.ttf")]


def test_synth_never_applies_to_a_bundled_face(assets):
    handle = assets.font(None, 28, bundled=Face.BOLD, synth=Synth.ITALIC)
    assert handle is assets.font(None, 28, bundled=Face.BOLD)
    assert handle.key == ("font", BUNDLED_NAMES[Face.BOLD], 28)


@pytest.mark.parametrize("ref", ["fonts/Nope.ttf", "fonts/corrupt.ttf"])
def test_a_broken_author_font_falls_back_to_the_requested_bundled_face(assets, caplog, ref):
    handle = assets.font(ref, 28, bundled=Face.BOLD, synth=Synth.BOLD)
    assert handle is assets.font(None, 28, bundled=Face.BOLD)   # the real face, unsynthesized
    assert assets.font(ref, 28, bundled=Face.ITALIC) is assets.font(None, 28,
                                                                   bundled=Face.ITALIC)
    assert len(problems(caplog)) == 1


def test_evicting_a_synthetic_style_releases_the_file(tmp_path):
    from tests.render.conftest import copy_game
    game = GamePaths.for_game(copy_game("assets", tmp_path / "assets"))
    assets = make_assets(game, budget_bytes=4 * 1024 * 1024)
    assets.font("fonts/test.ttf", 28, synth=Synth.BOLD)
    for frame in range(1, 40):
        assets.time.frame = frame
        assets.font(None, 10 + frame)
    assert ("font", "fonts/test.ttf", 28, Synth.BOLD) not in assets.cache
    assert ("fontfile", "fonts/test.ttf") not in assets.cache


# --- check() -------------------------------------------------------------------------------------

def test_check_accepts_good_files_and_never_logs(assets, caplog):
    assert assets.check("fonts/test.ttf", "font") is None
    assert assets.check("fonts/test.otf", "font") is None
    assert assets.check("gui/lantern.png", "image") is None
    assert asset_lines(caplog) == []


@pytest.mark.parametrize("ref, kind, expected", [
    ("fonts/Nope.ttf", "font", AssetProblem("missing", None)),
    ("FONTS/TEST.TTF", "font", AssetProblem("missing", "fonts/test.ttf")),
    ("fonts/corrupt.ttf", "font", AssetProblem("unreadable", None)),
    ("fonts/test.woff", "font", AssetProblem("unreadable", None)),
    ("gui/textbox.png", "image", AssetProblem("missing", None)),
    ("gui/upper.png", "image", AssetProblem("missing", "gui/UPPER.PNG")),
    ("gui/corrupt.png", "image", AssetProblem("unreadable", None)),
    ("gui/frame.gif", "image", AssetProblem("unreadable", None)),
])
def test_check_reports_problems_without_logging(assets, caplog, ref, kind, expected):
    assert assets.check(ref, kind) == expected
    assert asset_lines(caplog) == []


def test_check_reports_a_blocked_ref_as_unreadable(assets, caplog):
    assert assets.check("../x.ttf", "font") == AssetProblem("unreadable", None)
    assert asset_lines(caplog) == []


def test_check_needs_a_game_folder(caplog):
    assets = make_assets(None)
    assert assets.check("fonts/test.ttf", "font") == AssetProblem("missing", None)
    assert asset_lines(caplog) == []


def test_check_results_are_cached(assets, read_spy):
    assert assets.check("fonts/test.ttf", "font") is None
    assert assets.check("fonts/test.ttf", "font") is None
    assets.font("fonts/test.ttf", 28)
    assets.font("fonts/test.ttf", 28, synth=Synth.BOLD)
    assert assets.check("fonts/corrupt.ttf", "font") == AssetProblem("unreadable", None)
    assert assets.check("fonts/corrupt.ttf", "font") == AssetProblem("unreadable", None)
    assert assets.check("gui/lantern.png", "image") is None
    assert assets.check("gui/lantern.png", "image") is None
    assert not assets.image("gui/lantern.png").is_placeholder
    assert read_spy == ["fonts/test.ttf", "fonts/corrupt.ttf", "gui/lantern.png"]


def test_check_leaves_no_problem_record_behind(assets, caplog):
    """A failed check doesn't silence a later font() call's own warning (I-5 keeps FaceSet
    from making that call)."""
    assert assets.check("fonts/Nope.ttf", "font") is not None
    assets.font("fonts/Nope.ttf", 20)
    assert [m for _, m in problems(caplog)][0].startswith("fonts/Nope.ttf not found")


def test_a_failed_image_check_still_gives_a_placeholder(assets):
    assert assets.check("gui/textbox.png", "image") is not None
    image = assets.image("gui/textbox.png")
    assert image.is_placeholder and image.size == PLACEHOLDER_SIZE


def test_check_rejects_other_kinds(assets):
    with pytest.raises(ValueError):
        assets.check("fonts/test.ttf", "sound")  # type: ignore[arg-type]

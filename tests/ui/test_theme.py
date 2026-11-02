"""``ui/theme.py`` (F10 ``04`` §7.10 steps 1–3 and 5): the styles the painter gets from the
tokens, the UI faces and their fallback, W64 (fonts and images), W65 (empty words), and W68
(cut words, dev only). W67 and AC-F10-17's contrast table use F05's contrast function, so
they are ``tests/app/test_ui_contrast.py`` (``ui`` can't import ``app``)."""

import dataclasses
import logging

import pygame
import pytest

from engine.core.config_schema import (
    ButtonTheme,
    Config,
    MenuTheme,
    ThemeConfig,
    TitleTheme,
    UiAreaTheme,
    WordsConfig,
)
from engine.core.geometry import Viewport
from engine.core.paths import GamePaths
from engine.render.assets import Face, Synth
from engine.render.canvas import Canvas, RenderQuality
from engine.render.frames import FrameSpec
from engine.render.text import FontSpec
from engine.render.textlayout import BUNDLED_FACES, FaceSet, FaceSource
from engine.ui.theme import (
    Words,
    label_cuts,
    plain_theme,
    resolve_theme,
    resolve_words,
    ui_faces,
    warn_label_cuts,
)
from tests.render.conftest import copy_game, make_assets

pytestmark = pytest.mark.display

CFG = ThemeConfig()


def ui_records(caplog, code=None):
    return [r for r in caplog.records if r.name == "vn.ui"
            and (code is None or getattr(r, "code", None) == code)]


def config_with(**areas) -> Config:
    theme = dataclasses.replace(ThemeConfig(), **areas)
    return dataclasses.replace(Config(), theme=theme)


@pytest.fixture
def game(tmp_path):
    return GamePaths.for_game(copy_game("assets", tmp_path / "game"))


# --- Styles ---------------------------------------------------------------------------------

def test_button_styles_follow_the_tokens():
    theme = plain_theme()
    b = CFG.button
    normal = theme.style("button", "normal")
    assert normal.frame == FrameSpec(b.fill_color, 0.9, b.border_color, 2, 12, 24)
    assert normal.font == FontSpec(None, 28) and normal.text_color == b.text_color
    focused = theme.style("button", "focused").frame
    assert (focused.fill_color, focused.border_color, focused.border_width) == \
        (b.focused.fill_color, b.focused.border_color, 4)
    pressed = theme.style("button", "pressed").frame
    assert (pressed.fill_color, pressed.border_width) == (b.pressed.fill_color, 4)
    selected = theme.style("button", "selected").frame
    assert (selected.fill_color, selected.border_color, selected.border_width) == \
        (b.focused.fill_color, b.border_color, 2)
    disabled = theme.style("button", "disabled")
    assert disabled.frame.border_width == 0 and disabled.text_color == b.disabled.text_color
    assert normal.marker_color == b.marker.fill_color


def test_row_styles():
    theme = plain_theme()
    for area in ("toggle", "slider", "list"):
        assert theme.style(area, "normal").frame is None
        assert theme.style(area, "focused").frame == theme.style("button", "focused").frame
        assert theme.style(area, "normal").text_color == CFG.panel.text_color
    assert theme.style("toggle", "normal").color("track") == CFG.toggle.track_color
    assert theme.style("slider", "normal").color("thumb") == CFG.slider.thumb_color
    assert theme.style("list", "disabled").font.bundled is Face.ITALIC
    assert theme.style("list.empty", "normal").text_color == CFG.list.empty.text_color


def test_heading_uses_the_bold_face():
    theme = plain_theme()
    heading = theme.style("panel.heading", "normal")
    assert heading.font == FontSpec(None, 32, Face.BOLD)
    assert heading.text_color == CFG.panel.heading.text_color


def test_quick_menu_layout_uses_the_textbox_strip():
    theme = plain_theme()

    def m20(text, size):
        return len(text) * round(20 * size / 28)

    assert theme.quick_menu_layout(["Hide", "Menu"], m20).pill.y == 690
    cfg = dataclasses.replace(CFG, textbox=dataclasses.replace(CFG.textbox, bottom_gap=28))
    pill = plain_theme(cfg).quick_menu_layout(["Hide", "Menu"], m20).pill
    assert (pill.y, pill.bottom) == (692, 720)          # strip 28: the pill sits on the edge


# --- Faces -----------------------------------------------------------------------------------

def test_faces_fall_back_to_the_textbox():
    textbox = FaceSet({Face.REGULAR: FaceSource("fonts/t.ttf", Face.REGULAR),
                       Face.BOLD: FaceSource("fonts/b.ttf", Face.BOLD),
                       Face.ITALIC: FaceSource("fonts/t.ttf", Face.ITALIC, Synth.ITALIC),
                       Face.BOLD_ITALIC: FaceSource("fonts/b.ttf", Face.BOLD_ITALIC,
                                                    Synth.ITALIC)})
    assert ui_faces(None, None, textbox) == textbox
    faces = ui_faces("fonts/u.ttf", None, textbox).faces
    assert faces[Face.REGULAR] == FaceSource("fonts/u.ttf", Face.REGULAR)
    assert faces[Face.BOLD] == FaceSource("fonts/b.ttf", Face.BOLD)
    assert ui_faces(None, None) == BUNDLED_FACES


def test_resolve_uses_good_fonts(game, caplog):
    assets = make_assets(game)
    config = config_with(ui=dataclasses.replace(UiAreaTheme(), text_font="fonts/test.ttf"))
    theme = resolve_theme(config, assets)
    assert theme.style("button", "normal").font == FontSpec("fonts/test.ttf", 28)
    assert ui_records(caplog) == []


# --- W64 -------------------------------------------------------------------------------------

def test_w64_unreadable_font(game, caplog):
    assets = make_assets(game)
    config = config_with(ui=dataclasses.replace(UiAreaTheme(), text_font="fonts/corrupt.ttf"))
    theme = resolve_theme(config, assets)
    (record,) = ui_records(caplog, "W64")
    assert record.getMessage() == ('config.toml: [theme.ui] text_font "fonts/corrupt.ttf" '
                                   "couldn't be read as a font, so the text box font is used.")
    assert theme.faces == BUNDLED_FACES


def test_w64_missing_frame_with_a_suggestion(game, caplog):
    assets = make_assets(game)
    config = config_with(button=dataclasses.replace(ButtonTheme(), frame_image="gui/upper.png"))
    theme = resolve_theme(config, assets)
    (record,) = ui_records(caplog, "W64")
    assert record.levelno == logging.WARNING
    assert record.getMessage() == ('config.toml: [theme.button] frame_image "gui/upper.png" '
                                   "doesn't exist, so the drawn button is used. Did you mean "
                                   '"gui/UPPER.PNG"?')
    assert theme.frames["button"] is None
    assert theme.style("button", "normal").image is None


def test_w64_nested_frame_and_logo_and_background(game, caplog):
    assets = make_assets(game)
    focused = dataclasses.replace(ButtonTheme().focused, frame_image="gui/corrupt.png")
    config = config_with(
        button=dataclasses.replace(ButtonTheme(), focused=focused),
        title=dataclasses.replace(TitleTheme(), logo_image="gui/logo.png",
                                  background_image="gui/none.png"))
    theme = resolve_theme(config, assets)
    messages = [r.getMessage() for r in ui_records(caplog, "W64")]
    assert messages == [
        'config.toml: [theme.button.focused] frame_image "gui/corrupt.png" couldn\'t be read '
        "as an image, so the drawn button is used.",
        'config.toml: [theme.title] logo_image "gui/logo.png" doesn\'t exist, so the game\'s '
        "title is shown as text.",
        'config.toml: [theme.title] background_image "gui/none.png" doesn\'t exist, so the '
        "plain title background is used.",
    ]
    assert theme.logo is None and theme.background is None


def test_good_images_are_loaded(game, caplog):
    assets = make_assets(game)
    config = config_with(button=dataclasses.replace(ButtonTheme(), frame_image="gui/lantern.png"))
    theme = resolve_theme(config, assets)
    image = theme.frames["button"]
    assert image is not None and not image.is_placeholder
    assert theme.style("button", "normal").image is image
    assert theme.style("button", "focused").image is None
    assert ui_records(caplog) == []


# --- W65 --------------------------------------------------------------------------------------

def test_w65_empty_words_keep_their_default(caplog):
    words = resolve_words(WordsConfig(new_game="   ", quit=""))
    messages = [r.getMessage() for r in ui_records(caplog, "W65")]
    assert messages[0] == ('config.toml: [words] new_game is empty, so "New Game" is shown. '
                           'Write the words to show, e.g. new_game = "Begin".')
    assert messages[1].startswith('config.toml: [words] quit is empty, so "Quit" is shown.')
    assert words.get("new_game") == "New Game" and words.get("quit") == "Quit"


def test_words_override_and_return_key():
    words = Words(WordsConfig(return_="Back"), override=lambda k: "Begin" if k == "new_game"
                  else None)
    assert words.get("new_game") == "Begin" and words.get("return") == "Back"
    with pytest.raises(KeyError):
        words.get("nonexistent")


# --- W68 --------------------------------------------------------------------------------------

def test_w68_cut_words_dev_only(caplog):
    assets = make_assets(None)
    theme = plain_theme()
    words = Words(WordsConfig(main_menu="Return to the main title screen"))
    assert warn_label_cuts(theme, words, assets, dev=False) == []
    assert ui_records(caplog) == []
    cuts = warn_label_cuts(theme, words, assets, dev=True)
    assert [(c.key, c.place) for c in cuts] == [("main_menu", "game")]
    (record,) = ui_records(caplog, "W68")
    text = record.getMessage()
    assert text.startswith('config.toml: [words] main_menu "Return to the main title screen" '
                           "doesn't fit its button at text size 28, so it shows as \"")
    assert text.endswith('…". Use fewer words, or widen the button with [theme.menu] '
                         "button_width.")
    assert cuts[0].shown.endswith("…")


def test_w68_message_and_quick_menu_forms():
    assets = make_assets(None)
    words = Words(WordsConfig(confirm_quit="x " * 500, hide="Hide everything on the screen "
                              "now please, all of it, every last bit of it" * 3))
    cuts = label_cuts(plain_theme(), words, assets)
    places = {(c.key, c.place) for c in cuts}
    assert ("confirm_quit", "message") in places and ("hide", "quick") in places


def test_w68_default_words_fit():
    assert label_cuts(plain_theme(), Words(), make_assets(None)) == []


def test_wider_buttons_fit_longer_words():
    words = Words(WordsConfig(main_menu="Return to the main title screen"))
    wide = dataclasses.replace(CFG, menu=dataclasses.replace(MenuTheme(), button_width=312),
                               button=dataclasses.replace(ButtonTheme(), side_padding=24))
    cuts = label_cuts(plain_theme(wide), words, make_assets(None))
    narrow = label_cuts(plain_theme(), words, make_assets(None))
    assert len(cuts) <= len(narrow)


def test_bundled_bold_reaches_the_canvas():
    """The known gap of F05 step 4: a style asking for the bundled Bold face gets it."""
    assets = make_assets(None)
    canvas = Canvas(assets)
    framebuffer = pygame.Surface((1280, 720))
    canvas.bind(framebuffer, Viewport.compute((1280, 720), (1280, 720)), RenderQuality.FINAL)
    canvas.draw_text("Title", plain_theme().font(32, bold=True), (0, 0, 0), (0, 0))
    assert ("font", "<default-bold>", 32) in assets.cache


# --- AC-F10-66 — paths, sizes, and identity ---------------------------------------------------

def _f10_game(tmp_path, config: str):
    import shutil
    from pathlib import Path

    from tests.fixtures.F10.gen_ui_images import generate

    template = Path(__file__).resolve().parents[1] / "fixtures" / "F10" / "template_min"
    root = Path(shutil.copytree(template, tmp_path / "game"))
    generate(root)
    with (root / "config.toml").open("a", encoding="utf-8") as f:
        f.write("\n" + config + "\n")
    return root


def _resolved(root, caplog):
    from engine.core.config import load_config

    paths = GamePaths.for_game(root)
    loaded = load_config(paths)
    assert loaded.errors == [], [e.format() for e in loaded.errors]
    with caplog.at_level(logging.DEBUG, logger="vn"):
        return resolve_theme(loaded.config, make_assets(paths))


@pytest.mark.parametrize("table, key, value", [
    ("button", "frame_image", "../out.png"),
    ("button", "frame_image", "C:/out/out.png"),
    ("button", "frame_image", "/out/out.png"),
    ("title", "logo_image", "gui/../../out.png"),
], ids=["dotdot", "drive", "absolute", "inner-dotdot"])
def test_ac66_refs_out_of_the_game_are_config_errors(tmp_path, table, key, value):
    from engine.core.config import load_config

    root = _f10_game(tmp_path, f'[theme.{table}]\n{key} = "{value}"')
    errors = [e.format() for e in load_config(GamePaths.for_game(root)).errors]
    assert len(errors) == 1 and f"[theme.{table}] {key} must be an image in gui/" in errors[0]


def test_ac66_a_logo_through_a_link_out_of_the_game_is_blocked(tmp_path, caplog, monkeypatch):
    import os

    from engine.core.paths import GamePaths as Paths

    outside = tmp_path / "outside"
    outside.mkdir()
    pygame.image.save(pygame.Surface((10, 10)), str(outside / "logo.png"))
    root = _f10_game(tmp_path, '[theme.title]\nlogo_image = "gui/out/logo.png"')
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(outside), str(root / "gui" / "out"))
        else:
            os.symlink(outside, root / "gui" / "out", target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory links not permitted here: {exc}")
    returned = []
    real = Paths.read_file

    def read_file(self, ref, **kwargs):
        data = real(self, ref, **kwargs)              # raises before reading a blocked ref
        returned.append(ref)
        return data

    monkeypatch.setattr(Paths, "read_file", read_file)
    theme = _resolved(root, caplog)
    assert theme.logo is None                         # the title shows its text
    assert "gui/out/logo.png" not in returned         # never read
    (w64,) = ui_records(caplog, "W64")
    assert w64.getMessage().startswith('config.toml: [theme.title] logo_image "gui/out/logo.png"')


def test_ac66_a_huge_header_logo_is_refused_before_decoding(tmp_path, caplog, monkeypatch):
    root = _f10_game(tmp_path, '[theme.title]\nlogo_image = "gui/huge_header.png"')
    decoded = []
    real_load = pygame.image.load

    def load(source, *args):
        decoded.append(args)
        return real_load(source, *args)

    monkeypatch.setattr(pygame.image, "load", load)
    theme = _resolved(root, caplog)
    assert theme.logo is None and decoded == []       # F01's header check: never decoded
    (w64,) = ui_records(caplog, "W64")                # the one line (assets.check is silent)
    assert w64.getMessage() == ('config.toml: [theme.title] logo_image "gui/huge_header.png" '
                                "couldn't be read as an image, so the game's title is shown "
                                "as text.")


def test_ac66_a_300_character_missing_path_is_cut_in_w64(tmp_path, caplog):
    ref = "gui/" + "abcdefghi/" * 29 + "xy.png"
    assert len(ref) == 300
    root = _f10_game(tmp_path, f'[theme.button]\nframe_image = "{ref}"')
    theme = _resolved(root, caplog)
    assert theme.frames["button"] is None
    (w64,) = ui_records(caplog, "W64")
    text = w64.getMessage()
    assert ref not in text and "…" in text            # echo() cut the value (AC-F01-166)
    assert text.startswith('config.toml: [theme.button] frame_image "gui/abcdefghi/')


def test_ac66_log_lines_pass_privacy_check_p(tmp_path, caplog):
    from pathlib import Path

    from tests.fakes.privacy import check_p

    root = _f10_game(tmp_path, '[theme.button]\nframe_image = "gui/buton.png"\n'
                     '[theme.title]\nlogo_image = "gui/huge_header.png"\n'
                     '[words]\nquit = "  "')
    _resolved(root, caplog)
    texts = [r.getMessage() for r in caplog.records]
    assert any(getattr(r, "code", "") == "W64" for r in caplog.records)
    check_p(texts, home=Path.home(), game=root)

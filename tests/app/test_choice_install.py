"""F07 steps 2 and 4 — ``install_choices``, the default look's contrast (AC-F07-23 with 07
I-3's locked row; F10 C6 and I-8 with the real controller), the ``[theme.choice]`` tokens on
screen with W43/W44 (AC-F07-37; the invalid rows are ``tests/core/test_config_choice.py``),
and the launch warnings W47 and W48 (AC-F07-39).

AC-F07-23 uses F05's contrast function (``app/text_check``) with fills composited at their
opacity over pure black and pure white, ± 0.01. The install rows run App A on Template M.
W47's table rows run F05's ``TextLaunchCheck`` with the M20 font injected (36 graphemes per
720-unit line at 28, 51 at 20); one App A launch per mode checks the record's log area and
that release runs skip it.
"""

import logging

import pygame
import pytest

from engine.app.menus import reset_in_game
from engine.app.text_check import BLACK, WHITE, composite, contrast_ratio
from engine.core.config_schema import ChoiceTheme
from engine.runtime.commands import ShowMenu
from engine.ui.builtin.choice_screen import ChoiceController, ChoiceScreen
from tests.fakes.text_app import Session, make_text_game
from tests.script.helpers import template_m

T = ChoiceTheme()


@pytest.mark.parametrize("fg, fill, opacity, black, white, need", [
    (T.text_color, T.fill_color, T.fill_opacity, 9.81, 12.32, 4.5),
    (T.text_color, T.focused.fill_color, T.fill_opacity, 8.08, 10.31, 4.5),
    (T.marker.fill_color, T.focused.fill_color, T.fill_opacity, 4.35, 5.55, 3.0),
    (T.locked.text_color, T.fill_color, T.locked.fill_opacity, 4.52, 5.68, 4.5),   # I-3
])
def test_ac23_default_contrast(fg, fill, opacity, black, white, need):
    over_black = contrast_ratio(fg, composite(fill, opacity, BLACK))
    over_white = contrast_ratio(fg, composite(fill, opacity, WHITE))
    assert over_black == pytest.approx(black, abs=0.01)
    assert over_white == pytest.approx(white, abs=0.01)
    assert min(over_black, over_white) >= need


@pytest.fixture
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


@pytest.mark.display
def test_install_wires_the_controller_before_f10(tmp_path, pygame_ready):
    root = make_text_game(tmp_path / "game", script=template_m(), config="[textbox]\ncps = 0\n")
    s = Session(root)
    seen = {}

    def script(s):
        yield from s.until(lambda: s.app.story is not None and s.textbox is not None)
        app = s.app
        c = app.choices
        seen["controller"] = isinstance(c, ChoiceController)
        seen["handler"] = app.router._handlers[ShowMenu] == c.show
        seen["floor"] = c.floor == app.shell.quick_menu.floor          # F10 C6, I-3
        yield from s.until_line("Before.")
        s.key(pygame.K_SPACE)
        yield from s.until(lambda: c.screen is not None)
        seen["area"] = c.area("question")
        seen["textbox_faces"] = c.faces is s.textbox.faces
        reset_in_game(app)                                              # F10 I-8
        seen["after_reset"] = [type(x) for x in app.screens]
        seen["screen"] = c.screen

    s.play(script)
    assert seen["controller"] and seen["handler"] and seen["floor"]
    assert (seen["area"].bottom, seen["area"].last_bottom) == (446, 686)
    assert seen["textbox_faces"]
    assert ChoiceScreen not in seen["after_reset"] and seen["screen"] is None


# --- F07 step 4: the [theme.choice] tokens on screen (AC-F07-37) ---------------------------------
# App A on Template M over ``scene black``; F05's built ``tab_top`` is 462, so B = 446 and the
# default tops are 131, 202, 273 (``tests/ui/test_choice_screen.py``).

PINK = (0xF0, 0xA0, 0xC0)
BERRY = (0xA0, 0x28, 0x60)
FILL = (0xE6, 0xDC, 0xDF)                 # #FFF4F8 at 0.90 over black


def choice_game(tmp_path, config: str = "", **edit):
    edit.setdefault("S", "scene black")
    return make_text_game(tmp_path / "game", script=template_m(**edit),
                          config="[textbox]\ncps = 0\n" + config)


def frame_png(root) -> None:
    """AC-F05-32's PNG: 96 × 96, green, a blue center, red 24 × 24 corners."""
    image = pygame.Surface((96, 96))
    image.fill((0, 255, 0))
    image.fill((0, 0, 255), (24, 24, 48, 48))
    for x, y in ((0, 0), (72, 0), (0, 72), (72, 72)):
        image.fill((255, 0, 0), (x, y, 24, 24))
    (root / "gui").mkdir(exist_ok=True)
    pygame.image.save(image, str(root / "gui" / "choice.png"))


def at_menu(probe, *, keys=()):
    """A script: wait for the choices and past the fade, press ``keys``, then ``probe(s)``."""
    def script(s):
        yield from s.until(lambda: getattr(s.app, "choices", None) is not None
                           and s.app.choices.screen is not None)
        for _ in range(10):
            yield
        for k in keys:
            s.key(k)
            yield
        yield
        probe(s)
    return script


def warnings_of(caplog, *names: str) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING and r.name in names]


def near(a, b, tol=2) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b))


@pytest.mark.display
def test_ac37_valid_tokens_show(tmp_path, pygame_ready):
    root = choice_game(tmp_path, '[theme.choice]\nfill_color = "#000000"\nfill_opacity = 1.0\n'
                       'gap = 0\n[theme.choice.focused]\nborder_width = 8\n')
    seen = {}

    def probe(s):
        seen["tops"] = s.app.choices.screen.layout.tops
        seen["fill"] = s.px(300, 231)
        seen["y"] = [s.px(640, y) for y in (142, 143)]
        seen["focused"] = [s.px(x, 160) for x in range(240, 249)]

    Session(root).play(at_menu(probe, keys=(pygame.K_DOWN,)))
    assert seen["tops"] == (143, 202, 261)             # gap 0: the AC's 142, 201, 260 + 1
    assert seen["fill"] == BLACK                        # fill #000000 at 1.0
    assert seen["y"][0] == BLACK and near(seen["y"][1], BERRY, 1)   # button 1 is focused
    assert all(near(c, BERRY, 1) for c in seen["focused"][:8])  # focused border 8: x 240–247
    assert seen["focused"][8] == (0xFF, 0xD6, 0xE8)            # the focused fill at 1.0


@pytest.mark.display
def test_ac37_width(tmp_path, pygame_ready):
    root = choice_game(tmp_path, '[theme.choice]\nwidth = 400\n')
    seen = {}

    def probe(s):
        rect = s.app.choices.screen.layout.buttons[0].rect
        seen["rect"] = (rect[0], rect[0] + rect[2])
        y = round(rect[1] + rect[3] / 2)
        seen["x"] = [s.px(x, y) for x in (439, 440, 839, 840)]

    Session(root).play(at_menu(probe))
    assert seen["rect"] == (440, 840)
    assert seen["x"][0] == BLACK and seen["x"][3] == BLACK
    assert near(seen["x"][1], PINK, 1) and near(seen["x"][2], PINK, 1)


@pytest.mark.display
def test_ac37_a_frame_image_replaces_fill_and_border(tmp_path, pygame_ready, caplog):
    root = choice_game(tmp_path, '[theme.choice]\nframe_image = "gui/choice.png"\n'
                       'fill_opacity = 1.0\n')
    frame_png(root)
    seen = {}

    def probe(s):
        seen["corner"] = s.px(250, 136)                 # button 1: y 131–190
        seen["edges"] = [s.px(640, 135), s.px(241, 160)]
        seen["center"] = s.px(640, 160)

    with caplog.at_level(logging.WARNING):
        Session(root).play(at_menu(probe))
    # The 48-pixel center is smoothscaled down to 11 rows, so its blue blends a little.
    assert near(seen["corner"], (255, 0, 0), 3) and near(seen["center"], (0, 0, 255), 10)
    assert all(near(c, (0, 255, 0), 3) for c in seen["edges"])   # no drawn border or fill
    assert warnings_of(caplog, "vn.text") == []


@pytest.mark.display
def test_ac37_w43_w44_a_missing_frame_and_white_text(tmp_path, pygame_ready, caplog):
    root = choice_game(tmp_path, '[theme.choice]\nframe_image = "gui/choice.png"\n'
                       'text_color = "#FFFFFF"\n')
    seen = {}

    def probe(s):
        seen["border"] = s.px(240, 160)
        seen["fill"] = s.px(300, 160)

    with caplog.at_level(logging.WARNING):
        Session(root).play(at_menu(probe))
    assert near(seen["border"], PINK, 1) and near(seen["fill"], FILL, 1)   # the drawn button
    assert warnings_of(caplog, "vn.text") == [
        'config.toml: [theme.choice] frame_image "gui/choice.png" doesn\'t exist, so the drawn '
        'button is used.',
        "config.toml: [theme.choice] text_color #ffffff on fill_color #fff4f8 at fill_opacity "
        "0.9 gives 1.0:1 over a white picture; text needs at least 4.5:1. Raise fill_opacity "
        "or pick colors further apart."]


@pytest.mark.display
def test_ac37_w44_is_dev_only_and_w43_is_not(tmp_path, pygame_ready, caplog):
    root = choice_game(tmp_path, '[theme.choice]\ntext_color = "#FFFFFF"\n'
                       'text_font = "fonts/none.ttf"\n'
                       '[theme.choice.focused]\nframe_image = "gui/f.png"\n')
    with caplog.at_level(logging.WARNING):
        Session(root, dev=False).play(at_menu(lambda s: None))
    assert warnings_of(caplog, "vn.text") == [
        'config.toml: [theme.choice] text_font "fonts/none.ttf" doesn\'t exist, so the text '
        "box's font is used.",
        'config.toml: [theme.choice] focused.frame_image "gui/f.png" doesn\'t exist, so the '
        'drawn button is used.']


def test_w44_checks_the_focused_fill_and_the_locked_text():
    from engine.app.choices import choice_colors_warnings
    from engine.core.config_schema import ChoiceFocusedTheme, ChoiceLockedTheme

    assert choice_colors_warnings(ChoiceTheme()) == []
    dark = ChoiceTheme(focused=ChoiceFocusedTheme(fill_color=(0x30, 0x20, 0x28)))
    assert [w.split(" gives")[0] for w in choice_colors_warnings(dark)] == [
        "config.toml: [theme.choice] text_color #3d2b36 on focused.fill_color #302028 at "
        "fill_opacity 0.9"]
    pale = ChoiceTheme(locked=ChoiceLockedTheme(text_color=(0xD0, 0xC8, 0xCC)))
    assert [w.split(" gives")[0] for w in choice_colors_warnings(pale)] == [
        "config.toml: [theme.choice] locked.text_color #d0c8cc on fill_color #fff4f8 at "
        "locked.fill_opacity 0.9"]
    framed = ChoiceTheme(frame_image="gui/a.png", text_color=(255, 255, 255),
                         focused=ChoiceFocusedTheme(frame_image="gui/b.png"))
    assert choice_colors_warnings(framed) == []


# --- AC-F07-39 — W47 and W48 ---------------------------------------------------------------------

def w47_check(tmp_path, choice: str, *, size: int | None = None, question: str = ""):
    """The records of F05's check on Template M with ``M: menu:⏎[8]"<c>":⏎[12]$ pass`` (the
    choice on line 7, or 8 after a ``question``), M20 injected, ``[theme.choice] text_size``
    ``size``."""
    from engine.app.text_check import TextLaunchCheck
    from engine.core.config_schema import TextboxTheme
    from engine.render.textlayout import BUNDLED_FACES
    from engine.runtime.launch import run_launch
    from tests.fakes.fixed_font import FixedFontAssets
    from tests.runtime.menu_story import load_m

    head = f"menu:⏎[8]{question}⏎" if question else "menu:⏎"
    program = load_m(tmp_path / "game", M=f'{head}[8]"{choice}":⏎[12]$ pass')
    launch = run_launch(program)
    assert launch.namespace is not None
    return TextLaunchCheck(program, launch.namespace, assets=FixedFontAssets(),
                           faces=BUNDLED_FACES, theme=TextboxTheme(),
                           choice_theme=ChoiceTheme(text_size=size)).run()


def w47(lines: int, size: int = 28, line: int = 7) -> str:
    if lines == 2:
        tail = (f"this choice needs 2 lines at text size {size}. Choices are easiest to read on "
                "one line, about 50 characters.")
    else:
        tail = (f"this choice needs {lines} lines at text size {size}, but a choice shows at "
                'most 2, so the end is cut with "…". Shorten it.')
    return f"script/main.vns, line {line}: {tail}"


@pytest.mark.parametrize("choice, size, expected", [
    ("a" * 36, None, []),
    ("a" * 37, None, [w47(2)]),
    ("a" * 72, None, [w47(2)]),
    ("a" * 73, None, [w47(3)]),
    ("a" * 200, None, [w47(6)]),
    ("a" * 52, 20, [w47(2, 20)]),
    ("a" * 51, 20, []),
    ("Two\\nlines", None, [w47(2)]),
    ("{var=lantern}" + "a" * 32, None, []),             # "none" + 32: 36 graphemes
    ("{var=lantern}" + "a" * 33, None, [w47(2)]),
], ids=["a36", "a37", "a72", "a73", "a200", "a52-at-20", "a51-at-20", "break", "var-1",
        "var-2"])
def test_ac39_w47(tmp_path, choice, size, expected):
    assert w47_check(tmp_path, choice, size=size) == tuple(expected)


def test_w47_is_capped_at_20_records_then_one_summary(tmp_path):
    """F07 step 5: like W40 (20, then W40b), 25 long choices give 20 W47 records and one
    line counting the other 5, all in area ``choice``."""
    from engine.app.text_check import W47_MAX_CHOICES, TextLaunchCheck, w47_more
    from engine.core.config_schema import TextboxTheme
    from engine.render.textlayout import BUNDLED_FACES
    from engine.runtime.launch import run_launch
    from tests.fakes.fixed_font import FixedFontAssets
    from tests.runtime.menu_story import load_text

    long = "a" * 40                                         # 2 lines in M20 (36 per line)
    menus = "".join("    menu:\n" + "".join(f'        "{long}{m}{k}":\n            $ pass\n'
                                             for k in range(5))
                    for m in range(5))
    result = load_text(tmp_path / "game", "label start:\n" + menus + "    return\n")
    assert result.program is not None, [e.format() for e in result.errors]
    launch = run_launch(result.program)
    out = TextLaunchCheck(result.program, launch.namespace, assets=FixedFontAssets(),
                          faces=BUNDLED_FACES, theme=TextboxTheme(),
                          choice_theme=ChoiceTheme()).run()
    assert W47_MAX_CHOICES == 20 and len(out) == 21
    assert all("this choice needs 2 lines" in w for w in out[:20])
    assert out[20] == w47_more(5) == "…and 5 more choices need more than one line."


def test_ac39_a_question_that_needs_two_boxes_gets_w40_at_its_line(tmp_path):
    out = w47_check(tmp_path, "a", question='hana "' + "b " * 100 + '"')
    assert out == ("script/main.vns, line 7: this line needs 2 text boxes at text size 28, so "
                   "the player clicks once partway through. To choose where it breaks, split "
                   "it into two lines.",)


W48 = ['config.toml: [theme.choice] focus_sound "nothing.ogg" doesn\'t exist, so no sound '
       'plays.',
       'config.toml: [theme.choice] pick_sound "pik.ogg" doesn\'t exist, so no sound plays. '
       'Did you mean "pick.ogg"?']


@pytest.mark.display
@pytest.mark.parametrize("dev", [True, False], ids=["dev", "release"])
def test_ac39_w47_is_dev_only_and_w48_always_warns_and_never_plays(tmp_path, pygame_ready,
                                                                   caplog, dev):
    """One launch per mode: an ``a200`` choice and two missing sounds (``audio/pick.ogg``
    exists; W48 only looks the file up, so its bytes don't matter). W47, logged in area
    ``choice``, only in dev; W48 in both; no ``play_ui`` for a warned token."""
    root = choice_game(tmp_path, '[theme.choice]\npick_sound = "pik.ogg"\n'
                       'focus_sound = "nothing.ogg"\n',
                       M='menu:⏎[8]"' + "a" * 200 + '":⏎[12]$ pass')
    (root / "audio").mkdir()
    (root / "audio" / "pick.ogg").write_bytes(b"OggS")
    played: list[str] = []
    seen = {}

    def script(s):
        yield from s.until(lambda: getattr(s.app, "choices", None) is not None
                           and s.app.choices.screen is not None)
        c = s.app.choices
        seen["tokens"] = (c.focus_sound, c.pick_sound)
        c.play = played.append
        for _ in range(20):
            yield
        s.key(pygame.K_DOWN)
        yield
        s.key(pygame.K_RETURN)
        yield
        yield
        seen["closed"] = c.screen is None

    with caplog.at_level(logging.WARNING):
        Session(root, dev=dev).play(script)
    found = warnings_of(caplog, "vn.choice")
    w47s = [w for w in found if w.startswith("script/")]
    assert [w for w in found if not w.startswith("script/")] == W48
    if dev:
        assert len(w47s) == 1 and w47s[0].startswith(
            "script/main.vns, line 7: this choice needs ")
        assert w47s[0].endswith('but a choice shows at most 2, so the end is cut with "…". '
                                "Shorten it.")
    else:
        assert w47s == []
    assert warnings_of(caplog, "vn.text") == []
    assert seen["tokens"] == (None, None) and played == [] and seen["closed"]

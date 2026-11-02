"""F07 step 4 — the launch texts: W47 and W48 (design §5.3; AC-F07-39 with 07 I-4 O1, I-9)
and the ``[theme.choice]`` forms of F05's W43 and W44 (design §5.3 "Fonts and frame images
under ``[theme.choice]`` use W43's shape; colors use W44's"; 07 I-5: "drawn button").
Drafts for the narrative designer; F05's own forms must not change (``test_messages.py``).
W47's and W48's exact texts are asserted at launch by ``tests/app/test_choice_install.py``
(``test_ac39_w47``, ``W48``), so only the W43/W44 choice forms are here."""

import pytest

from engine.script.messages import format_message

CHOICE = "config.toml: [theme.choice] "


@pytest.mark.parametrize("args, expected", [
    (("frame_image", "gui/choice.png", "missing", None, False, "choice"),
     CHOICE + 'frame_image "gui/choice.png" doesn\'t exist, so the drawn button is used.'),
    (("focused.frame_image", "gui/choic.png", "missing", "gui/choice.png", False, "choice"),
     CHOICE + 'focused.frame_image "gui/choic.png" doesn\'t exist, so the drawn button is '
              'used. Did you mean "gui/choice.png"?'),
    (("frame_image", "gui/choice.png", "unreadable", None, False, "choice"),
     CHOICE + 'frame_image "gui/choice.png" couldn\'t be read as an image, so the drawn button '
              'is used. Export it again as .png.'),
    (("text_font", "fonts/x.ttf", "missing", None, False, "choice"),
     CHOICE + 'text_font "fonts/x.ttf" doesn\'t exist, so the text box\'s font is used.'),
    (("text_font", "fonts/x.ttf", "unreadable", None, False, "choice"),
     CHOICE + 'text_font "fonts/x.ttf" couldn\'t be read as a font, so the text box\'s font '
              'is used. Export it again as .ttf or .otf.'),
])
def test_w43_choice_forms(args, expected):
    assert format_message("W43", args) == expected


@pytest.mark.parametrize("args, expected", [
    (("#ffffff", "#fff4f8", 0.9, 1.09, "white", "choice"),
     CHOICE + "text_color #ffffff on fill_color #fff4f8 at fill_opacity 0.9 gives 1.0:1 over "
              "a white picture; text needs at least 4.5:1. Raise fill_opacity or pick colors "
              "further apart."),
    (("#ffffff", "#ffd6e8", 0.9, 1.3, "white", "choice", "text_color", "focused.fill_color"),
     CHOICE + "text_color #ffffff on focused.fill_color #ffd6e8 at fill_opacity 0.9 gives "
              "1.3:1 over a white picture; text needs at least 4.5:1. Raise fill_opacity or "
              "pick colors further apart."),
    (("#c0c0c0", "#fff4f8", 0.9, 1.7, "white", "choice", "locked.text_color", "fill_color",
      "locked.fill_opacity"),
     CHOICE + "locked.text_color #c0c0c0 on fill_color #fff4f8 at locked.fill_opacity 0.9 "
              "gives 1.7:1 over a white picture; text needs at least 4.5:1. Raise "
              "locked.fill_opacity or pick colors further apart."),
])
def test_w44_choice_forms(args, expected):
    assert format_message("W44", args) == expected


def test_f05_forms_are_unchanged():
    assert format_message("W43", ("frame_image", "gui/textbox.png", "missing")) == (
        'config.toml: [theme.textbox] frame_image "gui/textbox.png" doesn\'t exist, so the '
        'drawn box is used.')
    assert format_message("W44", ("#d0c0c8", "#3a2a3f", 0.4, 1.3, "white")).startswith(
        "config.toml: [theme.textbox] text_color #d0c0c8 on fill_color #3a2a3f at "
        "fill_opacity 0.4 gives 1.3:1")

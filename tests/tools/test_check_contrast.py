"""First-game fixes (2026-11-06): W41 reaches ``engine check`` and Studio's Problems (the
check child works it out after the launch phase with ``runtime/textcontrast``), and Studio's
new-character color reads on the game's name plate in its color scheme
(``tools/editor/namecolors``)."""

from engine.core.config_schema import NameTabTheme
from engine.core.paths import GamePaths
from engine.runtime.textcontrast import box_contrast, hex_rgb
from engine.tools.check import CheckJob
from engine.tools.editor import namecolors
from tests.runtime.menu_story import write_game

STORY = '''define mika = Character("Mika", color="#e0a040")
define hana = Character("Hana", color="#b03070")
define mika2 = mika

label start:
    mika "Hi."
    hana "Hello."
'''


def test_an_unreadable_name_color_is_a_check_warning_at_its_define(tmp_path):
    write_game(tmp_path, STORY)
    outcome = CheckJob(GamePaths.for_game(tmp_path), lambda event: None).collect()
    found = [p for p in outcome.problems if p["code"] == "W41"]
    assert [(p["severity"], p["file"], p["line"]) for p in found] == [
        ("warning", "script/main.vns", 1)]                 # once: the alias doesn't repeat it
    assert found[0]["text"] == (
        "mika's name color #e0a040 is hard to read on the name plate (1.9:1; names need at "
        "least 3:1). Pick a color further from the plate's #ffe6f0.")
    assert outcome.counts["warning"] == len([p for p in outcome.problems
                                             if p["severity"] == "warning"])


def test_the_scheme_decides_and_a_dark_plate_reads_the_light_color(tmp_path):
    config = '[theme.textbox.name_tab]\nfill_color = "#202030"\n'
    write_game(tmp_path, STORY.replace("#b03070", "#101010"), config)
    outcome = CheckJob(GamePaths.for_game(tmp_path), lambda event: None).collect()
    assert [p["text"].split("'")[0] for p in outcome.problems if p["code"] == "W41"] == [
        "hana"]


def test_new_character_colors_reach_3_to_1_on_the_plate(tmp_path):
    from engine.tools.editor.database import NEW_COLORS
    plates = [(NameTabTheme().fill_color, 1.0), ((0x20, 0x20, 0x30), 1.0),
              ((0x80, 0x80, 0x80), 0.9), ((0xEA, 0xDB, 0xCF), 0.85)]
    for fill, opacity in plates:
        for color in NEW_COLORS:
            picked = namecolors.readable(color, fill, opacity)
            ratio, _ = box_contrast(hex_rgb(picked), fill, opacity)     # the game's W41 rule
            assert ratio >= 3.0, (color, fill, opacity, picked)
    assert namecolors.readable("#d05050", NameTabTheme().fill_color, 1.0) == "#d05050"
    assert namecolors.readable("#e0a040", NameTabTheme().fill_color, 1.0) == "#a87830"


def test_the_plate_comes_from_the_open_config_text(tmp_path):
    write_game(tmp_path, STORY, '[theme]\npreset = "rose_garden"\n')
    saved = namecolors.plate_of(tmp_path, None)
    assert saved != (NameTabTheme().fill_color, NameTabTheme().fill_opacity)
    typed = namecolors.plate_of(tmp_path, b'[theme.textbox.name_tab]\nfill_color = "#102030"\n')
    assert typed == ((0x10, 0x20, 0x30), 1.0)
    assert namecolors.plate_of(tmp_path, b"[theme\n") == (NameTabTheme().fill_color, 1.0)

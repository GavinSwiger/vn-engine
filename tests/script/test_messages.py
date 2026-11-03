"""Messages (F02 checklist steps 1 and 9): every template formats, stays within its limits,
escapes hidden characters, and uses no banned word (PR-F02-31); the step 9 codes match the
``02`` §5 examples; the rows of ``messages/cases.toml`` (06 §5.2) hold, and their output is
the AC-F02-50 golden file ``expected.txt``. ACs: AC-F02-38, 40 (parse parts), 50."""

import builtins
import re

import pytest

from engine.script.messages import (
    TEMPLATES,
    codepoint,
    format_message,
    lookalike_suffix,
    mixed_script,
    show,
    show_name,
)
from tests.fakes.banned_words import BANNED_ANY, BANNED_CASED
from tests.script import message_cases
from tests.script.helpers import parse_text, template

SAMPLE_ARGS = {
    "E01b": ("script/a.vns", "UTF-16"), "E02": ("script/a.vns",), "E03": ("\x07",),
    "E03b": ("‮", True), "E04": (" ",), "E05": ("script/a.vns",), "E10": ("\t",),
    "E11": (" ",), "E12": ("if", True), "E14": ((0, 4, 8), " "), "E21": ("start", True),
    "E23": ("(route)",), "E24": ("inner",), "E30a": ("jmup", "jump"),
    "E30b": ("The", "The lanterns were lit."), "E30d": ("1.",), "E31": ("Jump",),
    "E31b": ("if", "trust >= 3"), "E32": ("show",), "E32b": ("at",), "E36": (22,),
    "E37": (22,), "E38": ("trust < 2",), "E39": ("if",), "E41": ("jump",),
    "E41b": ("jump", "bridge"), "E42": ("jump", "and run"), "E44": ("home",), "E50": ("“",),
    "E52": ("\\q",), "E53": ('hi" to me."',), "E60": ("scene", "a name"), "E61": ("class",),
    "E62": ("narrator",), "E63": ("_intro",), "E64": ("chapter-2",),
    "E64b": ("hanaㅤ", "ㅤ"), "E71": ("hana", "Hello."), "E72": ("(sad)", "hana"),
    "E73": (5, "hana"), "E80": ("x",), "E81": ("x",), "E82": ("x",), "E83": ("jump",),
    "E86": ("exec",), "E86b": ("value",), "W03": ("x",), "W03b": ("12",), "E49": (None,),
    "E95": ("chapter2.vns",), "E100": (14,),
    # Step 9: loader, whole-game, and reporting codes.
    "E07": ("script/deep/z.vns",), "E08": ("Main.vns",), "E08d": ("script/",),
    "E08e": ("characters",), "E09": (("chapter1.vns", "intro.vns"), 5),
    "W02": ("script/chapter3.vns",), "W02s": (12,), "W04": ("hаna", "Cyrillic"),
    "W04s": (7,), "E25": ("rooftop", (("script/chapter2.vns", 12),)),
    "E43": ("chapter_2", "chapter2"), "E47": ("hana", (("script/main.vns", 5),)),
    "E48": (("a", "b"), (("script/b.vns", 9),)), "E48b": ("trust",), "E70": ("hnaa", "hana"),
    "E91": ("chapter2.vns", "script/chapter2.vns", "Chapter2.vns"), "E92": ("../secret.vns",),
    "E93": ("notes.txt",), "E94": ("routes",), "E97": ("chapter2.vns", "script/chapter2.vns"),
    # F44 C2 (drafted in step 7): the start options.
    "E26b": ("club_poen", "club_poem"), "E26c": ("sayo_point", False, "sayo_points"),
    # F03 step 4: default.
    "E46b": ("trust = 0",), "E47b": ("trust", ("script/main.vns", 4)),
    "E47c": ("trust", ("script/main.vns", 4), False),
    # F03 step 7: the run codes (engine/runtime/errors.py fills them in).
    "E85": ("this Python", "list index out of range"), "E85b": ("trsut", "trust"),
    "E85c": ("text", "uper", "upper"), "E85d": ("add", "text", "a whole number"),
    "E85e": ("kind", "visited", None, "a set"), "E85f": ("this $ line", "sys.exit()"),
    "E85j": ("roll", "order", "", "", 0, ("6", "1")), "E85m": ("this Python",),
    "E85n": ("input",),
    # F03 step 10: the step and call limits.
    "E45": (100_000, ("shop", "street")), "E45b": (1000, 999, "chat"),
    # F03 step 8: the launch codes and E75h.
    "E75": ("daichi", "text", "Daichi", ("script/chapter1.vns", 20)),
    "E75b": ("colour", ("color", "name_from"), "color"), "E75c": ("#e8a0b",),
    "E75d": ("count", 2), "E75e": ("a whole number",), "E75f": ("hana_nmae", "hana_name"),
    "E75h": ("hana", "hana_name", "a whole number", "3"), "E85k": ("opening",),
    "E85l": ("bonus", "trust"), "E89": ("maths", "math"), "E89c": ("game", "helpers"),
    # F03 step 11: the $ binding codes.
    "E87": ("wish_cost", ("script/main.vns", 6), "300"), "E88": ("os", "os", "os.path"),
    "W05": ("deck",),
    # F05 step 2: tags, {var}, and the textbox's launch and run texts.
    "E160": ("suggest", "colour", "color"), "E161": ("open",), "E162": ("space", "b"),
    "E163": ("needs", "color"), "E164": ("range", "pause", "45"), "E165": ("b",),
    "E166": ("b", "i"), "E167": ("last",), "E168": ("text_color",), "E169": ("{b}Hana{/b}",),
    "E170": ("trsut", "trust"), "E171": ("visited", "a list"), "W40": (2, 28), "W40b": (12,),
    "W41": ("name", "hana", "#f4d0dc", 1.2, "#ffe6f0"), "W42": ("player_nmae", "player_name"),
    "W42s": (5,), "W43": ("text_font", "fonts/Lora.ttf", "unreadable"),
    # F04 step 2: the stage load codes.
    "E110": ("left", "right", "at left", "at"), "E111": ("at",), "E112": ("show",),
    "E113": ("at",), "E114": ("at",), "E115": ("with dissolve",),
    "E116": ("words", "hana", "hide hana happy"),
    "E117": ("file", "show", "hana/happy.png", "hana happy"),
    "E119": ("at", "at left", "hana", "hana"), "E120": ("rigth", "right"),
    "E121": ("2600", "too far right"), "E122": ("units", "400px"), "E123": ("150",),
    "E124": ("10",), "E126": ("a b c d e f", 6), "E127": ("statement", "call"),
    "E132": ("color", "#fff"), "E133": ("bg dusk", ("script/main.vns", 8)),
    "W44": ("#d0c0c8", "#3a2a3f", 0.4, 1.3, "white"), "W45": ("bold",), "W46": ("wishes",),
    # F08 step 1: the audio load codes.
    "E140": ("unknown", "play", "musc", "music"), "E141": ("play", "voice", "v/a.ogg"),
    "E142": ("quotes", "play music", "festival.ogg"),
    "E143": ("../x.ogg", "paths can't be empty"), "E144": ("audio/bgm/a.ogg",),
    "E145": ("bgm/festival",), "E146": ("unknown", "play", "fadin", "fadein"),
    "E147": ("clash", "loop", "once"), "E148": ("queue_start", "restart"),
    "E149": ("fadein",), "E150": ("units", "fadein", "2s"), "E151": ("percent", "50"),
    # F12 step 3a: persistent data in the story.
    "E180": ("hana_rememebrs", "hana_remembers"), "E181": ("kind", "persistent.v", "a set"),
    "E182": ("set", "_secret"), "E183": ("bytes", 1_363_196),
    "E184": ("dotted", "persistent.a.b"), "E185": ("title", "cleared", '"Again?"'),
    "W56": ("hana_rememebrs", "hana_remembers"),
    # F06 step 1: the blip options and the long pitched blip.
    "E179": ("blip_pitch", "2"), "W49": ("blips/hana.ogg", 1.4),
}

_BANNED_CASED = BANNED_CASED          # tests/fakes/banned_words.py (shared with F03 and F44)
_BANNED_ANY = BANNED_ANY
_EXCEPTIONS = {name for name, value in vars(builtins).items()
               if isinstance(value, type) and issubclass(value, BaseException)}


@pytest.mark.parametrize("code", sorted(TEMPLATES))
def test_every_template_formats_cleanly(code):
    text = format_message(code, SAMPLE_ARGS.get(code, ()))
    assert text and len(text) <= 1000
    assert not _BANNED_CASED.search(text) and not _BANNED_ANY.search(text)
    # W62 and W183 name the drawing failure's type on purpose (F09 07 I-9, F28 04 D7:
    # "(MemoryError)").
    assert not set(re.findall(r"\w+", text)) & _EXCEPTIONS or code in ("W62", "W183")
    for char in ("‮", "ㅤ", "\x07", " "):
        assert char not in text


def test_show_escapes_hidden_characters_and_cuts():
    assert show("hanaㅤ") == "hana\\u3164"
    assert show("b\U000e0100") == "b\\U000e0100"
    assert show("a‮b") == "a\\u202eb"
    assert len(show("x" * 500)) == 120


def test_codepoint():
    assert codepoint("‮") == "U+202E" and codepoint("\U000e0100") == "U+E0100"


def test_messages_are_cut_to_1000_characters():
    assert len(format_message("E30b", ("x", "y" * 5000))) <= 1000


def test_python_texts_get_a_final_full_stop():
    assert format_message("E80", ("x",)) == "this Python has a mistake: x."
    assert format_message("E80", ("x?",)) == "this Python has a mistake: x?"
    assert format_message("E80", ("x…",)) == "this Python has a mistake: x…"


# --- Step 9 codes against the 02 §5 examples -------------------------------------------------

MAIN = "script/main.vns"
_CANT_READ = ("couldn't be read. Check that another program isn't locking it and that you "
              "have permission to read it.")


@pytest.mark.parametrize("code,args,expected", [
    ("E07", ("script/deep/z.vns",),
     "The includes from script/main.vns to script/deep/z.vns chain more than 50 files, which "
     "is the limit. Include z.vns from a file nearer main.vns."),
    ("E07", ("script/c/f51.vns",),                                        # AC-F02-51
     "The includes from script/main.vns to script/c/f51.vns chain more than 50 files, which "
     "is the limit. Include f51.vns from a file nearer main.vns."),
    ("E08", ("Main.vns",),
     'script/main.vns doesn\'t exist. Did you mean "Main.vns"? Rename it to main.vns; the '
     "story always begins there."),
    ("E08b", (), f"script/main.vns {_CANT_READ}"),
    ("E08c", (), "script/main.vns is a folder. The story must begin in a file named main.vns."),
    ("E08d", (), "script/main.vns points to a place outside the game folder, which is not "
                 "allowed. Keep the story files in the game's script folder."),
    ("E08d", ("script/",), "script/ points to a place outside the game folder, which is not "
                           "allowed. Keep the story files in the game's script folder."),
    ("E09", (("chapter1.vns", "intro.vns", "routes/a.vns", "routes/b.vns", "x.vns", "y.vns",
              "z.vns"),),                                                  # AC-F02-06
     "script/main.vns doesn't exist, but script/ has other .vns files: chapter1.vns, "
     "intro.vns, routes/a.vns, routes/b.vns, x.vns, and 2 more. Rename the file where your "
     "story begins to main.vns."),
    ("E09", (("chapter1.vns", "intro.vns"), 5),
     "script/main.vns doesn't exist, but script/ has other .vns files: chapter1.vns, "
     "intro.vns, and 3 more. Rename the file where your story begins to main.vns."),
    ("W02", ("script/chapter3.vns",),
     'script/chapter3.vns is not included, so it is not part of the game. Add include '
     '"chapter3.vns" to a file that is.'),
    ("W02", ("script/routes/x.vns",),                                      # AC-F02-07
     'script/routes/x.vns is not included, so it is not part of the game. Add include '
     '"routes/x.vns" to a file that is.'),
    ("W02s", (12,), "…and 12 more .vns files are not included."),
    ("W02b", (), "script/ holds more than 10,000 files and folders, so only the first ones were "
                 "checked for files that aren't included."),
    ("E25", ("rooftop", (("script/chapter2.vns", 12),)),
     'there is already a label named "rooftop" in script/chapter2.vns, line 12. Rename one of '
     "them."),
    ("E26", (), 'The story has no label named "start". Add label start: to script/main.vns. '
                "The story begins there."),
    ("E26", ("Start", (MAIN, 4)),
     'The story has no label named "start". Did you mean "Start" (script/main.vns, line 4)?'),
    ("E43", ("chapter_2", "chapter2"),
     'there is no label named "chapter_2". Did you mean "chapter2"?'),
    ("E43", ("chapter3", None, "script/chapter3.vns"),
     'there is no label named "chapter3" in the game. It is defined in script/chapter3.vns, '
     'which is not included. Add include "chapter3.vns".'),
    ("E43", ("epilouge",),
     'there is no label named "epilouge". Check the spelling, or add that label.'),
    ("E43", ("epilouge", None, None, MAIN, (("script/a.vns", 30),), 2),
     'there is no label named "epilouge". It is also used at script/a.vns, line 30, and 2 more '
     "places. Check the spelling, or add that label."),
    ("W04", ("hаna", "Cyrillic"),
     'the name "h\\u0430na" mixes Latin and Cyrillic letters, so it can look like another '
     "name. Type every letter in one alphabet."),
    ("W04s", (7,), "…and 7 more names mix alphabets."),
    ("E70", ("hnaa", "hana"), 'no character named "hnaa". Did you mean "hana"?'),
    ("E70", ("kaito",), 'no character named "kaito". Check the spelling, or define it.'),
    ("E70", ("kaito", None, MAIN, ((MAIN, 60),), 4),
     'no character named "kaito". It is also used at line 60, and 4 more places. Check the '
     "spelling, or define it."),
    ("E47", ("hana", ((MAIN, 5),)),
     '"hana" is already defined in script/main.vns, line 5. Remove or rename one.'),
    ("E48", (("a", "b"), (("script/b.vns", 9),)),
     "define a uses b, and b uses a (script/b.vns, line 9), so neither can be set first. "
     "Change one so it doesn't use the other."),
    ("E48b", ("trust",), "define trust uses itself, so it can't be set. Write its value "
                         "without using trust."),
    ("E91", ("chapter2.vns", "script/chapter2.vns", "Chapter2.vns"),
     'can\'t include "chapter2.vns" because script/chapter2.vns doesn\'t exist. Did you mean '
     '"Chapter2.vns"?'),
    ("E92", ("../secret.vns",),
     'can\'t include "../secret.vns": paths must stay inside the script folder and use forward '
     "slashes, e.g. routes/hana.vns."),
    ("E92", ("con.vns", '"con" is a reserved file name on Windows'),       # AC-F02-03
     'can\'t include "con.vns": "con" is a reserved file name on Windows'),
    ("E93", ("notes.txt",), 'can\'t include "notes.txt": only .vns files can be included.'),
    ("E93", ("ch2.VNS",),
     'can\'t include "ch2.VNS": only .vns files can be included. Use lower case.'),
    ("E94", ("routes",), 'can\'t include "routes": that is a folder. Include each .vns file in '
                         "it."),
    ("E97", ("chapter2.vns", "script/chapter2.vns"),
     f'can\'t include "chapter2.vns" because script/chapter2.vns {_CANT_READ}'),
])
def test_step9_codes_match_the_02_examples(code, args, expected):
    assert format_message(code, args) == expected


# --- F05 step 2: the launch and run texts against F05 02 §5.2, §5.4 and 06 -----------------
# (E160–E167 and W42 are checked as cases.toml rows; these codes are raised by F05 steps 3,
# 6, and 7, which only format them.)

_THEME = "config.toml: [theme.textbox] "


@pytest.mark.parametrize("code,args,expected", [
    ("E168", ("text_color",), 'text_color must be a color: # and six digits or letters a to '
                              'f, e.g. text_color="#9ec5ff".'),
    ("E168", ("text_italic", '"yes"'),
     'text_italic is True or False, e.g. text_italic=True, but this has "yes".'),
    ("E169", ("{b}Hana{/b}",),
     'character names are shown exactly as written, so "{b}Hana{/b}" would show its braces. '
     'Write Character("Hana"); the name\'s color is color="…".'),
    ("E170", ("trsut", "trust"),
     '{var=trsut} shows a variable that doesn\'t exist. Did you mean "trust"?'),
    ("E170", ("met_daichi",),
     "{var=met_daichi} shows a variable that doesn't exist yet. Add default met_daichi = … at "
     "the top level so it always has a value."),
    ("E171", ("visited", "a list"),
     "{var=visited} can show text or a number, but visited holds a list. Store the text to "
     "show in its own variable."),
    ("E171", ("hana", "a character"),
     "{var=hana} can show text or a number, but hana is a character. To show her name, show "
     "the variable her name_from names, e.g. {var=hana_name}."),
    ("W40", (2, 28),
     "this line needs 2 text boxes at text size 28, so the player clicks once partway "
     "through. To choose where it breaks, split it into two lines."),
    ("W40", (3, 28),
     "this line needs 3 text boxes at text size 28, so the player clicks 2 times partway "
     "through. To choose where it breaks, split it into two lines."),
    ("W40b", (5,), "…and 5 more lines need more than one text box."),
    ("W41", ("name", "grey", "#a0a0a0", 2.2, "#ffe6f0"),
     "grey's name color #a0a0a0 is hard to read on the name plate (2.2:1; names need at least "
     "3:1). Pick a color further from the plate's #ffe6f0."),
    ("W41", ("text", "t2", "#b0a0b0", 3.3, "white", "#3a2a3f"),
     "t2's text_color #b0a0b0 is hard to read on the text box (3.3:1 over a white picture; "
     "text needs at least 4.5:1). Pick a lighter color, or raise fill_opacity under "
     "[theme.textbox] in config.toml."),
    ("W42", ("trsut", "trust"),
     "{var=trsut} shows a variable that no default or define sets, so the story stops if this "
     'line runs before a $ line sets it. Did you mean "trust"?'),
    ("W42", ("met_daichi",),
     "{var=met_daichi} shows a variable that no default or define sets, so the story stops if "
     'this line runs before a $ line sets it. Add default met_daichi = "" at the top level.'),
    ("W43", ("text_font", "fonts/Lora-Regulr.ttf", "missing", "fonts/Lora-Regular.ttf"),
     _THEME + 'text_font "fonts/Lora-Regulr.ttf" doesn\'t exist, so the built-in font is '
     'used. Did you mean "fonts/Lora-Regular.ttf"?'),
    ("W43", ("text_font", "fonts/Lora.ttf", "unreadable"),
     _THEME + 'text_font "fonts/Lora.ttf" couldn\'t be read as a font, so the built-in font '
     "is used. Export it again as .ttf or .otf."),
    ("W43", ("frame_image", "gui/textbox.png", "missing"),
     _THEME + 'frame_image "gui/textbox.png" doesn\'t exist, so the drawn box is used.'),
    ("W44", ("#d0c0c8", "#3a2a3f", 0.4, 1.3, "white"),
     _THEME + "text_color #d0c0c8 on fill_color #3a2a3f at fill_opacity 0.4 gives 1.3:1 over "
     "a white picture; text needs at least 4.5:1. Raise fill_opacity or pick colors further "
     "apart."),
    ("W45", ("bold",),
     _THEME + "text_font is set but bold_font isn't, so bold text is made by thickening your "
     "font. Add bold_font for a real bold face."),
    ("W45", ("italic",),
     _THEME + "text_font is set but italic_font isn't, so italic text is made by slanting "
     "your font. Add italic_font for a real italic face."),
])
def test_f05_launch_and_run_texts(code, args, expected):
    assert format_message(code, args) == expected


@pytest.mark.parametrize("code,args,contains", [
    ("E168", ("text_italic", "1"), "text_italic is True or False"),
    ("E169", ("Hana}",), 'Write Character("Hana")'),
    ("E171", ("flag", "True or False"), "{var=flag} can show text or a number, but flag holds"),
    ("E171", ("flag", "nothing (None)"), "{var=flag} can show text or a number, but flag holds"),
    ("E171", ("hana", "a character", "hana_name2"), "e.g. {var=hana_name2}."),
    ("W41", ("text", "t", "#000000", 4.47, "black"), "(4.4:1 over a black picture"),  # G1
    ("W41", ("text", "t", "#000000", 3.3, "black"), "Pick a lighter color"),
    ("W44", ("#3d2b36", "#fff4f8", 0.6, 4.3, "black"), "gives 4.3:1 over a black picture"),
    ("W43", ("bold_font", "fonts/nope.ttf", "missing", None, True),
     "doesn't exist, so bold text is made by thickening your text_font."),        # G4
    ("W43", ("frame_image", "gui/box.png", "unreadable"), "so the drawn box is used."),
    ("W46", ("shrine",), "{var=shrine} no longer exists in this version of the game, so it "
                         "shows as empty text. Add default shrine = … at the top level"),
    ("W46", ("shrine", False), "{var=shrine} no longer holds text or a number"),   # G5
    ("W42s", (3,), "…and 3 more {var} names that no default or define sets."),
])
def test_f05_drafted_and_open_forms(code, args, contains):
    assert contains in format_message(code, args)


def test_e91_variants():
    prefix = format_message("E91", ("script/chapter2.vns", "script/script/chapter2.vns"))
    assert prefix.endswith("doesn't exist. Paths start inside the script folder, so write "
                           'include "chapter2.vns".')
    plain = format_message("E91", ("nothing.vns", "script/nothing.vns"))
    assert plain.startswith('can\'t include "nothing.vns" because script/nothing.vns doesn\'t '
                            "exist.")


def test_lists_of_places_show_three_then_a_count():
    places = tuple(("script/a.vns", n) for n in range(1, 10_001))
    e25 = format_message("E25", ("bridge", places))
    assert e25 == ('there are other labels named "bridge" in script/a.vns, line 1, script/a.vns, '
                   "line 2, script/a.vns, line 3, and 9,997 more places. Rename all but one.")
    e43 = format_message("E43", ("x", None, None, MAIN, places[:500]))
    assert e43.count("script/a.vns") == 3 and "and 497 more places" in e43
    cycle = tuple(f"d{i}" for i in range(1000))
    e48 = format_message("E48", (cycle, places[:999]))
    assert e48.startswith("define d0 uses d1, d1 uses d2, d2 uses d3, and 997 more (")
    assert "and 996 more places" in e48 and len(e48) <= 1000
    three = format_message("E48", (("a", "b", "c"), ((MAIN, 10), (MAIN, 11))))
    assert "a uses b, b uses c, and c uses a" in three


def test_long_names_are_cut_and_messages_bounded():
    name = "n" * 9000
    for code, args in [("E25", (name, ((MAIN, 7), (MAIN, 8)))), ("E43", (name, name[:-1])),
                       ("E60", (name, "a label name")), ("E70", (name,)),
                       ("E47", (name, ((MAIN, 1),))), ("E48", ((name, name + "x"), ((MAIN, 2),)))]:
        text = format_message(code, args)
        assert len(text) <= 1000
        assert max(len(run) for run in re.findall(r"n+", text)) <= 119


def test_lookalike_suffix_and_mixed_names():
    assert lookalike_suffix("stаrt", "start") == (
        ' "st\\u0430rt" has U+0430 CYRILLIC SMALL LETTER A where "start" has a.')
    assert lookalike_suffix("Start", "start") == ""
    assert lookalike_suffix("stark", "start") == ""
    e26 = format_message("E26", ("stаrt", (MAIN, 3)))
    assert 'Did you mean "st\\u0430rt"' in e26                            # AC-F02-47
    assert e26.endswith(' "st\\u0430rt" has U+0430 CYRILLIC SMALL LETTER A where "start" has a.')
    e70 = format_message("E70", ("hаna", "hana"))
    assert e70 == ('no character named "h\\u0430na". Did you mean "hana"? "hana" has a where '
                   '"h\\u0430na" has U+0430 CYRILLIC SMALL LETTER A.')
    assert mixed_script("hаna") == "Cyrillic" and mixed_script("lοve") == "Greek"
    assert mixed_script("привет") is None and mixed_script("日本") is None
    assert mixed_script("café") is None
    assert show_name("привет") == "привет" and show_name("始まり") == "始まり"


# --- messages/cases.toml and expected.txt (AC-F02-50) -----------------------------------------

CASES = message_cases.load_cases()
RUNNABLE = [case for case in CASES if case.runnable]
_KNOWN_EDIT = {"S", "D", "T", "R", "M", "text", "gen", "prefix_hex", "F", "files", "template",
               "config"}


def test_cases_are_well_formed():
    ids = [case.id for case in CASES]
    assert len(ids) == len(set(ids))
    for case in CASES:
        assert case.needs in ("parse", "load"), case.id
        assert case.feature in ("F02", "F03", "F04", "F05", "F06", "F07", "F08", "F09", "F12",
                                "F14", "F17", "F18", "F19", "F20", "F21", "F22", "F23",
                                "F28", "F29", "F30", "F31", "F32", "F34", "F35", "F36"), case.id
        assert case.ac.startswith(f"AC-{case.feature}-"), case.id
        assert case.time in ("load", "launch", "run"), case.id
        assert case.feature != "F02" or case.time == "load", case.id
        assert "D" not in case.edit or case.feature in ("F05", "F29"), case.id
        assert "M" not in case.edit or case.feature == "F07", case.id
        assert "config" not in case.edit or case.feature == "F17", case.id
        assert case.code == "-" or case.code in TEMPLATES, case.id
        assert set(case.edit) <= _KNOWN_EDIT, case.id
        assert "gen" not in case.edit or case.edit["gen"] in message_cases.GENERATORS
        assert set(case.expect) <= {"exact", "contains", "starts", "ends"}, case.id
        assert all(code in TEMPLATES for code in case.also), case.id
        message_cases.parse_where(case.where)
        assert not any(mark in str(case) for mark in message_cases.PLACEHOLDERS), case.id
    # Every AC named by 06 §5.2 has rows.
    acs = {case.ac for case in CASES}
    for number in (3, 6, 8, 10, 11, 12, 17, 19, 20, 22, 23, 24, 25, 26, 27, 28, 29, 32, 34, 47):
        assert f"AC-F02-{number:02}" in acs
    assert "AC-F03-17" in acs                                    # F03 step 4
    assert {"AC-F05-01", "AC-F05-02", "AC-F05-05"} <= acs        # F05 step 2
    assert "AC-F04-38" in acs                                    # F04 step 2
    assert {f"AC-F08-0{n}" for n in range(1, 6)} <= acs         # F08 step 1
    assert {f"AC-F07-0{n}" for n in (1, 2, 3, 4, 8)} <= acs      # F07 step 1
    assert "AC-F12-05" in acs                                    # F12 step 3a
    assert {"AC-F22-01", "AC-F22-02"} <= acs                     # F22 step 1
    assert "AC-F14-16" in acs                                    # F14 step 1
    assert {"AC-F17-02", "AC-F17-05", "AC-F17-29", "AC-F17-30"} <= acs   # F17 step 1
    assert {f"AC-F19-0{n}" for n in range(3, 8)} <= acs         # F19 step 1
    assert {f"AC-F21-0{n}" for n in (2, 3, 5, 7)} <= acs         # F21 step 1
    assert {"AC-F23-02", "AC-F23-03"} <= acs                     # F23 s1
    assert {"AC-F29-02", "AC-F29-03", "AC-F29-04"} <= acs        # F29 step 2
    assert {"AC-F28-06", "AC-F28-07", "AC-F28-08"} <= acs        # F28 s2
    assert {"AC-F30-08", "AC-F30-09", "AC-F30-10"} <= acs        # F30 s2
    assert "AC-F32-06" in acs                                    # F32 s2
    assert "AC-F31-09" in acs                                    # F31 s2
    assert {f"AC-F34-0{n}" for n in range(2, 6)} <= acs          # F34 W1
    assert {"AC-F35-01", "AC-F35-02"} <= acs                     # F35 S2
    assert {f"AC-F36-0{n}" for n in range(2, 7)} <= acs          # F36 W1


def test_every_template_code_with_a_row_is_covered():
    raised_by_parser = {"E03", "E03b", "E04", "E10", "E10c", "E11", "E12", "E13", "E14", "E15",
                        "E16", "E20", "E21", "E22", "E23", "E23b", "E24", "E30a", "E30b", "E30d",
                        "E31", "E31b", "E32", "E32b", "E33", "E34", "E35", "E36", "E37", "E38",
                        "E38b", "E39", "E40", "E41", "E41b", "E42", "E44", "E46", "E49", "E50",
                        "E51", "E52", "E53", "E54", "E54b", "E60", "E61", "E62", "E63", "E64",
                        "E64b", "E71", "E72", "E73", "E74", "E80", "E81", "E82", "E90", "E95",
                        "E96", "W03", "W03b"}
    assert raised_by_parser <= {case.code for case in RUNNABLE}


_OUTCOMES: dict[str, message_cases.Outcome] = {}
_RUN_CASE = message_cases.run_case      # unpatched: the golden test patches it


def _outcome(case: message_cases.Case) -> message_cases.Outcome:
    """Each row is loaded once per session: ``test_case``, the golden file, and AC-F02-38
    read the same outcome (a load is deterministic; AC-F02-55 checks that)."""
    if case.id not in _OUTCOMES:
        _OUTCOMES[case.id] = _RUN_CASE(case)
    return _OUTCOMES[case.id]


@pytest.mark.parametrize("case", RUNNABLE, ids=lambda case: case.id)
def test_case(case):
    message_cases.check_case(case, _outcome(case))


def test_golden_file_is_byte_identical():
    expected = message_cases.EXPECTED_PATH.read_bytes()
    assert b"\r" not in expected
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(message_cases, "run_case", _outcome)
        golden = message_cases.golden_text(CASES)
    assert golden.encode("utf-8") == expected, (
        "regenerate with: .venv/Scripts/python -m tests.script.message_cases --write")


# --- AC-F02-38: message shape, banned words, no paths ---------------------------------------

_LINE_RE = re.compile(r"^script/\S.*\.vns, line [1-9][0-9]*(, column [1-9][0-9]*)?: \S")
_PATH_RE = re.compile(r"<game>|[A-Za-z]:[\\/]|\\\\[A-Za-z0-9]|(?:^|\s)/\w")
_PLACE_LISTS = {"E25", "E43", "E47", "E48", "E70", "E47b", "E47c"}   # E47b/c: F03


def _outputs():
    for case in RUNNABLE:
        outcome = _outcome(case)
        yield from outcome.errors
        yield from outcome.warnings


def test_ac38_every_message_has_the_shape_and_no_banned_word():
    seen = 0
    for item in _outputs():
        seen += 1
        text = item.format()
        if item.line is not None:
            assert _LINE_RE.match(text), text
            assert item.file not in item.message or item.code in _PLACE_LISTS, text   # (d)
        elif item.message.startswith("script/"):
            assert ", line " not in text.split(":", 1)[0], text                       # whole-file
        else:
            assert item.message[:1].isupper() or item.message.startswith("…"), text   # game
        assert not _BANNED_CASED.search(text) and not _BANNED_ANY.search(text), text
        assert not set(re.findall(r"\w+", text)) & _EXCEPTIONS, text
        # AC-F02-03's E92 rows echo the path the author wrote ("C:/x.vns", "/etc/x.vns");
        # (c) is about paths the engine adds, so the quoted include path is left out.
        assert not _PATH_RE.search(_INCLUDE_PATH_RE.sub('include ""', text)), text
    assert seen >= len(RUNNABLE) - 20


_INCLUDE_PATH_RE = re.compile(r'include "[^"]*"')


# --- AC-F02-40, parse parts: one mistake, one message ----------------------------------------

@pytest.mark.parametrize("text,code", [
    (template(replace={3: "label start"}), "E21"),
    (template(S='"never closed⏎[12]deeper one⏎[12]deeper two'), "E54"),
    ('label start:\n    "A."\n' + '\t"B."\n' * 31, "E10"),
])
def test_ac40_one_mistake_gives_one_error(text, code):
    parsed = parse_text(text)
    assert parsed.codes == [code], parsed.messages

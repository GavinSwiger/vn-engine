"""AC-F04-51: the language reference's "Backgrounds and sprites" section and the UI system's
stage entries (F04 ``06-acceptance.md`` §1.12). The review step (a newcomer can show a
background and two characters from the section alone) is the reviewer's."""

import dataclasses
import re
from pathlib import Path

import pytest

from tests.fakes.username import no_real_username  # noqa: F401  (name guard)

REPO = Path(__file__).resolve().parents[1]
LANGUAGE = REPO / "docs" / "script-language.md"
UI = REPO / "docs" / "ui-system.md"
F04_SCRIPT = REPO / "specs" / "F04-stage-sprites" / "02-script.md"


def _section(text: str, title: str) -> str:
    heading = re.search(rf"^## \d+\. {re.escape(title)}\s*$", text, re.M)
    assert heading is not None, title
    following = re.search(r"^## ", text[heading.end():], re.M)
    end = heading.end() + following.start() if following else len(text)
    return text[heading.start():end]


def _code_blocks(section: str) -> str:
    return "\n".join(re.findall(r"^```[a-z]*\n(.*?)^```", section, re.M | re.S))


# Topic → a pattern one of the section's code blocks must hold.
TOPICS = {
    "images/ folder": r"images/hana/happy\.png",
    "art_height": r"^\[stage\]\nart_height = \d+",
    "scene": r"^\s+scene bg \w+",
    "show": r"^\s+show hana happy$",
    "hide": r"^\s+hide \w+",
    "image": r'^image bg \w+ = "#[0-9a-f]{6}"',
    "at name": r"show .* at left",
    "at number": r"show .* at -?\d+",
    "at x y": r"show .* at \d+ \d+",
    "[stage.positions]": r"^\[stage\.positions\]\n\w+ = ",
    "as": r"show .* as \w+",
    "behind": r"show .* behind \w+",
    "layer": r"show .* layer \d+",
    "zoom": r"show .* zoom [\d.]+",
    "flip": r"show .* flip on",
    "dialogue-line words": r'^\s+hana pout "',
    "image_tag": r'Character\(.*image_tag="\w+"\)',
    "with": r"^\s+(scene|show|hide) .* with dissolve",
}


def _messages(code: str) -> list[str]:
    """The quoted texts of ``02-script.md`` §5's row for ``code``."""
    if not F04_SCRIPT.exists():                  # specs/ is kept out of the repository
        pytest.skip("the spec files aren't in this checkout")
    row = next(line for line in F04_SCRIPT.read_text(encoding="utf-8").splitlines()
               if line.startswith(f"| {code} "))
    return re.findall(r"`([^`]+)`", row.split("|")[3])


def test_ac_f04_51_backgrounds_and_sprites_section():
    text = LANGUAGE.read_text(encoding="utf-8")
    section = _section(text, "Backgrounds and sprites")
    code = _code_blocks(section)
    missing = [topic for topic, pattern in TOPICS.items() if not re.search(pattern, code, re.M)]
    assert missing == []
    for message_code in ("W12", "E120", "E121", "E122"):
        quoted = _messages(message_code)
        assert quoted, message_code
        for message in quoted:
            assert f"`{message}`" in section, (message_code, message)
    assert "(proposed, F04)" not in text


def test_ac_f04_51_ui_system_stage_entries():
    text = UI.read_text(encoding="utf-8")
    assert re.search(r"^\| `stage\.empty_color` \| color \|", text, re.M)
    for color in ("#202020", "#FF00FF", "#000000", "#FFFFFF"):
        assert color in text, color
    assert "proposed, F04" not in text


# --- AC-F05-48: "Dialogue text" and the textbox tokens --------------------------------------------

F05_SCRIPT = REPO / "specs" / "F05-adv-textbox" / "02-script.md"
F05_TAGS = ("{b}", "{/b}", "{i}", "{/i}", "{color=", "{/color}", "{size=", "{/size}", "{speed=",
            "{speed=instant}", "{/speed}", "{pause=", "{pause}", "{var=", "{next}", "{{")
F05_KEYS = ("[textbox]", "cps", "[theme.textbox]", "text_font", "bold_font", "italic_font",
            "bold_italic_font", "text_size", "text_color", "fill_color", "fill_opacity",
            "frame_image", "[theme.textbox.name_tab]")


# F05's E160 forms that F29 (and F30's username) changed in messages.py: the list now names
# shake, wave, glitch, and username, and "shake" is a tag, not a missing one.
F29_SUPERSEDED = ('there is no tag "blink". The tags are b, i, color, size, speed, pause, var, '
                  'and next.', 'there is no tag "shake" in this engine version.')


def _f05_messages(code: str) -> list[str]:
    """The full quoted texts of F05 ``02-script.md`` §5's row for ``code`` (parts such as
    `` `i` `` and W40's "needs 3 text boxes …" are left out)."""
    if not F05_SCRIPT.exists():                  # specs/ is kept out of the repository
        pytest.skip("the spec files aren't in this checkout")
    row = next(line for line in F05_SCRIPT.read_text(encoding="utf-8").splitlines()
               if line.startswith(f"| {code} "))
    return [q for q in re.findall(r"`([^`]+)`", row.split("|")[3])
            if len(q) >= 12 and not q.startswith(("…", "needs "))]


def test_ac_f05_48_dialogue_text_section():
    text = LANGUAGE.read_text(encoding="utf-8")
    assert "(proposed, F05)" not in text
    section = _section(text, "Dialogue text")
    assert [tag for tag in F05_TAGS if tag not in section] == []
    assert [key for key in F05_KEYS if key not in section] == []
    assert "text_italic" in section
    for code in ("E160", "E161", "E162", "E163", "E164", "E165", "E166", "E167", "W40"):
        quoted = _f05_messages(code)
        assert quoted, code
        for message in quoted:
            if message in F29_SUPERSEDED:          # AC-F29-19 checks the engine's words
                continue
            assert f"`{message}`" in section, (code, message)
    assert re.search(r"color carries meaning.*make those words bold", section, re.S)


def _token_rows(text: str) -> dict[str, str]:
    return {m.group(1): m.group(0) for m in re.finditer(r"^\| `(textbox\.[\w.]+)` \|.*$", text,
                                                        re.M)}


def _default_words(value: object) -> tuple[str, ...]:
    """How a token's default may be written in its row."""
    if isinstance(value, tuple):
        return ('"#{:02X}{:02X}{:02X}"'.format(*value),)
    if isinstance(value, float):
        return (f"{value:.2f}", f"{value:g}", f"{value:.1f}")
    if value is None:
        return ("none", "bundled", "`textbox.")
    return (str(value),)


def test_ac_f05_48_ui_system_textbox_tokens():
    from dataclasses import fields

    from engine.core.config_schema import IndicatorTheme, NameTabTheme, TextboxTheme

    text = UI.read_text(encoding="utf-8")
    assert "proposed, F05" not in text
    rows = _token_rows(text)
    for prefix, table in (("textbox.", TextboxTheme()), ("textbox.name_tab.", NameTabTheme()),
                          ("textbox.indicator.", IndicatorTheme())):
        for f in fields(table):
            value = getattr(table, f.name)
            if isinstance(value, (NameTabTheme, IndicatorTheme)):
                continue
            row = rows.get(prefix + f.name)
            assert row is not None, prefix + f.name
            assert any(word in row for word in _default_words(value)), (row, value)
    conventions = _section(text, "Text")
    for words in ("Line pitch", "Contrast over art", "4.5:1", "3:1", "Continue indicators",
                  "W41", "W44"):
        assert words in conventions, words


# --- AC-F05-47: the example game uses the feature, each with a comment above its first use ----

EXAMPLE = REPO / "game"
F05_FEATURES = {
    "{b}": r"\{b\}",
    "{color=…}": r"\{color=#[0-9a-f]{6}\}",
    "{pause=…}": r"\{pause=[\d.]+\}",
    "{pause}": r"\{pause\}",
    "{speed=…}": r"\{speed=[\d.]+\}",
    "{{": r"\{\{",
}


def _example_lines() -> list[tuple[str, int, list[str]]]:
    """(file, line number, the file's lines) of every line, in reading order."""
    main = (EXAMPLE / "script" / "main.vns").read_text(encoding="utf-8")
    refs = ["script/main.vns", *(f"script/{ref}" for ref in
                                 re.findall(r'^include "([^"]+)"$', main, re.M))]
    out = []
    for ref in refs:
        lines = (EXAMPLE / ref).read_text(encoding="utf-8").splitlines()
        out += [(ref, number, lines) for number in range(1, len(lines) + 1)]
    return out


def test_ac_f05_47_the_example_game_uses_the_textbox():
    found = {}
    narration = dialogue = False
    for ref, number, lines in _example_lines():
        line = lines[number - 1]
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if re.fullmatch(r'"[^"].*', stripped):
            narration = True
        if re.fullmatch(r'(hana|daichi)( \w+)* ".*', stripped):
            dialogue = True
        for feature, pattern in F05_FEATURES.items():
            if feature not in found and '"' in line and re.search(pattern, line):
                found[feature] = (ref, number, lines)
    assert narration and dialogue
    assert sorted(found) == sorted(F05_FEATURES)
    for feature, (ref, number, lines) in found.items():
        above = next(text for text in reversed(lines[:number - 1]) if text.strip())
        assert above.lstrip().startswith("#"), (feature, ref, number)
    main = (EXAMPLE / "script" / "main.vns").read_text(encoding="utf-8")
    assert re.search(r'Character\(name_from="(\w+)"', main)          # a name that changes


def test_ac_f12_48_persistent_in_story_variables_and_run_time_errors():
    """AC-F12-48: section 9 documents persistent data (not proposed), section 18 lists
    E180–E185 and W56 and no longer E85h, and the seam docstrings say results are
    untrusted."""
    from engine.runtime.persistent import PersistentStore

    text = LANGUAGE.read_text(encoding="utf-8")
    assert "proposed, F12" not in text
    variables = _section(text, "Story variables")
    for words in ("### persistent", "default persistent.", "persistent._clear()",
                  "progress=True", "1 MB", "10,000 names", "--no-persistent",
                  "Players can edit and share the file", "`eval` or `exec`", "file name"):
        assert words in variables, words
    assert "persistent.endings" not in variables and "persistent.routes" not in variables
    errors = _section(text, "Run-time errors")
    assert "E85h" not in errors
    for code in ("E180", "E181", "E182", "E183", "E184", "E185", "W56"):
        assert re.search(rf"^\| {code} \|", errors, re.M), code
    peek = PersistentStore.peek.__doc__ or ""
    unlocked = PersistentStore.unlocked.__doc__ or ""
    assert "untrusted" in peek and "lookup keys" in unlocked and "never paths" in unlocked


def test_ac_f12_47_the_example_game_uses_persistent_data():
    main = (EXAMPLE / "script" / "main.vns").read_text(encoding="utf-8")
    bridge = (EXAMPLE / "script" / "routes" / "daichi.vns").read_text(encoding="utf-8")
    assert re.search(r"^default persistent\.festivals = 0$", main, re.M)
    assert re.search(r"^    if persistent\.festivals > 0:$", bridge, re.M)
    assert re.search(r"^    \$ persistent\.festivals \+= 1$", bridge, re.M)


# --- AC-F10-69: "Menus and theme" and the UI system --------------------------------------------

F10_TOKENS = REPO / "tests" / "fixtures" / "F10" / "tokens.csv"


def test_ac_f10_69_menus_and_theme_section():
    """Every row of AC-F10-20's tokens file, and every ``[words]``, ``[title]``, and
    ``[quick_menu]`` key of F10, with its default; how to replace the title art, logo,
    music, and button words; I-4's strip rule. The review step (reading the section as a
    newcomer) is the reviewer's."""
    import csv
    from dataclasses import fields

    from engine.core.config_schema import QuickMenuConfig, TitleConfig, WordsConfig
    from engine.ui.theme import F10_ENTRY_WORDS

    section = _section(LANGUAGE.read_text(encoding="utf-8"), "Menus and theme")
    rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| `([\w.\[\] ]+)` \|.*$", section,
                                                        re.M)}
    with F10_TOKENS.open(encoding="utf-8", newline="") as f:
        tokens = list(csv.DictReader(f))
    assert len(tokens) == 89
    for token in tokens:
        row = rows.get(token["key"])
        assert row is not None, token["key"]
        assert token["default"] in row, (row, token["default"])
        if token["min"]:
            assert f"{token['min']}–{token['max']}" in row, row
    words = {f.metadata.get("key") or f.name: f.default for f in fields(WordsConfig)}
    f10_words = [key for key in words if key in _F10_WORDS]
    assert len(f10_words) == 20
    for key in f10_words:
        assert f'"{words[key]}"' in rows.get(key, ""), key
    for table, config in (("title", TitleConfig()), ("quick_menu", QuickMenuConfig())):
        for f in fields(config):
            row = rows.get(f"[{table}] {f.name}")
            assert row is not None, (table, f.name)
            default = getattr(config, f.name)
            assert (str(default).lower() if isinstance(default, bool) else "not set") in row
    assert set(F10_ENTRY_WORDS["title"]) <= set(words)
    for words_in_text in ("background_image", "logo_image", "music", "frame_image",
                          "nine-slice", "new_game = \"Begin\"", "shorter than 28",
                          "Shift+F3"):
        assert words_in_text in section, words_in_text


_F10_WORDS = ("new_game", "load", "settings", "extras", "help", "quit", "return", "history",
              "save", "main_menu", "yes", "no", "hide", "menu", "on", "off", "loading",
              "list_empty", "confirm_main_menu", "confirm_quit")


def test_ac_f10_69_ui_system_has_no_f10_proposals():
    text = UI.read_text(encoding="utf-8")
    assert "proposed, F10" not in text
    quick = next(line for line in text.splitlines() if line.startswith("| Quick-menu strip |"))
    for words in ("`textbox.bottom_gap`", "y 690–718", "y 688–720", "686", "684"):
        assert words in quick, words


# --- AC-F07-44: "menu (choices)" and the UI system's layer 5 ---------------------------------

def _subsection(text: str, title: str) -> str:
    """A ``### title`` subsection, up to the next ``###`` or ``##`` heading."""
    heading = re.search(rf"^### {re.escape(title)}\s*$", text, re.M)
    assert heading is not None, title
    following = re.search(r"^##", text[heading.end():], re.M)
    end = heading.end() + following.start() if following else len(text)
    return text[heading.start():end]


def _same_shape(text: str) -> str:
    """Numbers and plain tags (``{pause}``, ``{speed}``) masked: one row may stand for a
    family (``this menu has 7 choices`` and ``8 choices``; E175 for each tag)."""
    return re.sub(r"\{\w+\}", "{tag}", re.sub(r"\d+", "#", text))


def test_ac_f07_44_the_menu_section():
    """The section isn't proposed, nor the reserved word; it holds every F07 row's text of
    ``cases.toml`` (``exact`` or ``starts``; masked as ``_same_shape``) and the engine's
    ``[choice] show_locked`` error (SR-F07-09's, as F01's config check words it)."""
    import tempfile

    from engine.core.config import load_config
    from engine.core.paths import GamePaths
    from tests.script import message_cases

    text = LANGUAGE.read_text(encoding="utf-8")
    assert "proposed, F07" not in text
    assert re.search(r"^\| `menu` \| available \|$", text, re.M)
    section = _subsection(text, "menu (choices)")
    shaped = _same_shape(section)
    rows = [c for c in message_cases.load_cases() if c.feature == "F07"]
    assert len(rows) >= 25
    missing = []
    for row in rows:
        for kind in ("exact", "starts"):
            message = row.expect.get(kind)
            if message and _same_shape(message) not in shaped:
                missing.append((row.id, message))
    assert missing == []
    with tempfile.TemporaryDirectory() as tmp:
        game = Path(tmp)
        (game / "config.toml").write_text('[game]\ntitle = "x"\n\n\n\n[choice]\n'
                                          'show_locked = "yes"\n', encoding="utf-8")
        (error,) = load_config(GamePaths.for_game(game)).errors
    message = error.format()
    assert message.startswith("config.toml, line 7: [choice] show_locked must be true or "
                              'false, but found'), message
    assert f"`{message}`" in section
    for words in ("[choice]", "show_locked", "[theme.choice]", "docs/ui-system.md",
                  'if not asked_', "jump talk", "$ pass"):
        assert words in section, words


def test_ac_f07_44_ui_system_layer_5_and_choice_tokens():
    from dataclasses import fields

    from engine.core.config_schema import (ChoiceFocusedTheme, ChoiceLockedTheme,
                                           ChoiceMarkerTheme, ChoiceTheme)

    text = UI.read_text(encoding="utf-8")
    assert "proposed, F07" not in text
    layer = next(line for line in text.splitlines() if line.startswith("| 5 | Choices |"))
    assert "reserved" not in layer and "| F07 |" in layer
    rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| `(choice\.[\w.]+)` \|.*$", text,
                                                        re.M)}
    tables = (ChoiceFocusedTheme, ChoiceMarkerTheme, ChoiceLockedTheme)
    for prefix, table in (("choice.", ChoiceTheme()), ("choice.focused.", ChoiceFocusedTheme()),
                          ("choice.marker.", ChoiceMarkerTheme()),
                          ("choice.locked.", ChoiceLockedTheme())):
        for f in fields(table):
            value = getattr(table, f.name)
            if isinstance(value, tables):
                continue
            row = rows.get(prefix + f.name)
            assert row is not None, prefix + f.name
            assert any(word in row for word in _default_words(value)), (row, value)
    assert "0.90" in rows["choice.locked.fill_opacity"]                 # 07 I-3, not 0.60


# --- AC-F08-58: "Music and sound" and its common errors ---------------------------------------

F08_SCRIPT = REPO / "specs" / "F08-audio" / "02-script.md"
F08_CODES = [f"E{n}" for n in range(140, 152)] + [f"W{n}" for n in range(20, 32)]


def _f08_first_message(code: str) -> str:
    """The first sentence of the first message in F08 ``02-script.md`` §5's row for
    ``code`` (up to its first ". ", "? ", "…", or "<")."""
    if not F08_SCRIPT.exists():                  # specs/ is kept out of the repository
        pytest.skip("the spec files aren't in this checkout")
    row = next(line for line in F08_SCRIPT.read_text(encoding="utf-8").splitlines()
               if line.startswith(f"| {code} "))
    message = re.findall(r"`([^`]+)`", row.split("|")[3])[0]
    return re.split(r"\. |\? |…|<", message)[0]


def test_ac_f08_58_music_and_sound_section():
    text = LANGUAGE.read_text(encoding="utf-8")
    section = _section(text, "Music and sound")
    assert "proposed" not in section and "(F08)" not in section
    code = _code_blocks(section)
    for pattern in (r'^\s+play music "[^"]+" fadein', r'^\s+play sound "[^"]+" loop',
                    r"^\s+queue music ", r"^\s+stop music fadeout 0$", r"^\s+stop sound",
                    r"^\s+stop voice$", r'^\s+voice "', r"^\[audio\]$",
                    r"^\[audio\.loop_start\]$"):
        assert re.search(pattern, code, re.M), pattern
    for words in ("Ogg Vorbis", "MP3", "LUFS", "**Saving and loading.**", "LICENSES.txt"):
        assert words in section, words
    errors = _section(text, "Common errors")
    audio = errors[errors.index("### Audio\n"):errors.index("### Text tags\n")]
    for code_ in F08_CODES:
        first = _f08_first_message(code_)
        assert len(first) >= 15, (code_, first)
        assert first in audio, (code_, first)
    assert "#13-music-and-sound" in text and "13. Music and sound" in text


# --- AC-F09-44, AC-F09-45: transitions and effects in the example game and the references -----

# Feature → a pattern its first use matches (a whole line). The grouped moment (≥ 2 stage
# lines before one ``with``) is found by ``_first_f09_uses`` itself.
F09_FEATURES = {
    "with dissolve": r"\s+(scene|show|hide) .* with dissolve",
    "with dissolve <n>": r"\s+(scene|show|hide|chapter) .* with dissolve [\d.]+",
    "with fade": r"\s+(scene|show|hide) .* with fade( .+)?",
    "with cut": r"\s+(scene|show|hide) .* with cut",
    "shake": r"\s+shake( .+)?",
    "flash": r"\s+flash( .+)?",
    "pause": r"\s+pause( [\d.]+)?",
    "Mask define": r'define \w+ = Mask\("[^"]+".*\)',
}
_STAGE_LINE = re.compile(r"\s+(scene|show|hide) ")


def _first_f09_uses() -> dict[str, tuple[str, int, list[str]]]:
    found: dict[str, tuple[str, int, list[str]]] = {}
    group: list[int] = []                     # stage lines since the last other statement
    for ref, number, lines in _example_lines():
        line = lines[number - 1]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        for feature, pattern in F09_FEATURES.items():
            if feature not in found and re.fullmatch(pattern, line):
                found[feature] = (ref, number, lines)
        if not _STAGE_LINE.match(line):
            group = []
        elif " with " in line:
            if group and "grouped moment" not in found:
                found["grouped moment"] = (ref, group[0], lines)
            group = []
        else:
            group.append(number)
    return found


def test_ac_f09_44_the_example_game_uses_every_transition_and_effect():
    """Each F09 feature with a ``#`` comment above its first use; one ``Mask`` define whose
    file is gray, ≤ 640×360, and in ``masks/LICENSES.txt``; the game loads and launches with
    no warning, its transition check included (W60). The headless runs with no warning are
    AC-F03-80's; the window runs (the ``--dev`` launch, the harness to the end, no W60–W62)
    are ``test_example_game_runs_without_warnings`` and
    ``test_harness_plays_the_example_game_to_its_end``; the goldens, ``test_determinism.py``."""
    import hashlib

    import pygame

    from engine.runtime.images import ImageSource
    from engine.runtime.launch import run_launch
    from engine.runtime.transitions import check_transitions
    from tests.runtime import corpus
    from tests.runtime.stage_story import load_example

    uses = _first_f09_uses()
    assert sorted(uses) == sorted([*F09_FEATURES, "grouped moment"])
    for feature, (ref, number, lines) in uses.items():
        above = next(text for text in reversed(lines[:number - 1]) if text.strip())
        assert above.lstrip().startswith("#"), (feature, ref, number)
    masks = [lines[number - 1] for _, number, lines in _example_lines()
             if "= Mask(" in lines[number - 1]]
    assert len(masks) == 1
    file = re.search(r'Mask\("([^"]+)"', masks[0]).group(1)
    image = pygame.image.load(str(EXAMPLE / file))
    assert image.get_width() <= 640 and image.get_height() <= 360
    rgb = pygame.image.tobytes(image, "RGB")
    assert rgb[0::3] == rgb[1::3] == rgb[2::3]                       # gray: read exactly
    record = (EXAMPLE / "masks" / "LICENSES.txt").read_text(encoding="utf-8")
    entry = record[record.index(f"File: {file.removeprefix('masks/')}\n"):]
    assert "License: CC0 1.0" in entry
    assert hashlib.sha256((EXAMPLE / file).read_bytes()).hexdigest() in entry

    result = load_example()
    assert result.program is not None and result.errors == () and result.warnings == ()
    launch = run_launch(result.program, images=ImageSource.from_files(corpus.example_images()))
    assert launch.namespace is not None and launch.warnings == ()
    errors, warnings = check_transitions(
        result.program, launch.namespace, locate=lambda ref: ((EXAMPLE / ref).is_file(), None))
    assert errors == [] and warnings == []


# Each F09 code → the forms the reference shows (``format_message`` arguments). The section's
# table holds exactly these codes, in this order: no W63, no ``Transition`` row (07 C1).
F09_MESSAGES: dict[str, list[tuple]] = {
    "E190": [("disolve", "dissolve"), ("swirl", None, ("lantern", "slow_dissolve"))],
    "E191": [()],
    "E192": [(), ("units", "0.5", "0.5s"), ("dot", "", ".5")],
    "E193": [(), ("name", "pink")],
    "E194": [(), ("color", "dissolve"), ("twice", "fade", "lengths"),
             ("left", "slowly", "dissolve"), ("launch", "lantern", "mask")],
    "E195": [(), ("length", "30", False), ("twice", "sizes")],
    "E196": [(), ("twice", "colors")],
    "E197": [()],
    "E198": [()],
    "E199": [(), ("seconds", "Dissolve", "-1"), ("soft", "2"), ("type", "masks/iris.gif")],
    "W60": [("masks/iris.png", "lantern", "masks/iris.webp")],
    "W61": [(), ("fade",)],
    "W62": [("dissolve", "MemoryError")],
}


def _hex(rgb: tuple[int, int, int]) -> str:
    return '"#{:02X}{:02X}{:02X}"'.format(*rgb)


def test_ac_f09_45_transitions_section_and_ui_system_rows():
    """``script-language.md``: the section covers SR-F09-01..09 (code and words), its
    message table equals ``messages.py``, it has the flash-or-shake advice, the gray
    640×360 mask advice, and ``[effects]``'s defaults; §12's "for the moment" note and W14
    are gone; Reserved words and Common errors are updated. ``ui-system.md``: the
    ``effects.*`` tokens, the 01 §6.2 timing rows, the flash limit and reduced versions, and
    layer 2, each marked "(proposed, F09)" until sign-off (07 I-10)."""
    from dataclasses import fields

    from engine.core.config_schema import EffectsConfig, EffectsTheme
    from engine.script.messages import format_message

    text = LANGUAGE.read_text(encoding="utf-8")
    section = _section(text, "Transitions and effects")
    assert re.findall(r"^\| ([EW]\d+) \|", section, re.M) == list(F09_MESSAGES)
    for code, forms in F09_MESSAGES.items():
        row = re.search(rf"^\| {code} \|.*$", section, re.M).group(0)
        for args in forms:
            assert f"`{format_message(code, args)}`" in row, (code, args)
    assert not re.search(r"^\| `Transition", section, re.M)
    code = _code_blocks(section)
    for pattern in (r"^\s+scene .* with fade$", r"^\s+show .* with dissolve [\d.]+$",
                    r"^\s+hide .* with dissolve$", r"with fade [\d.]+ white$",
                    r'with fade [\d.]+ "#[0-9a-f]{6}"$', r"with cut$",
                    r"^\s+show \w+ \w+ at \w+ with fade$",      # a grouped moment
                    r"^\s+shake$", r"^\s+shake large$", r"^\s+shake small horizontal [\d.]+$",
                    r"^\s+flash$", r"^\s+flash red$", r'^\s+flash "#[0-9a-f]{6}" [\d.]+$',
                    r"^\s+pause [\d.]+$", r"^\s+pause$", r"^define \w+ = Dissolve\(",
                    r'^define \w+ = Fade\([\d.]+, color="#', r'^define \w+ = Mask\("',
                    r"reverse=True\)$", r"^\[effects\]$", r"^\[theme\.effects\]$"):
        assert re.search(pattern, code, re.M), pattern
    for f in fields(EffectsConfig):
        if f.name in ("glitch", "glitch_size"):     # F28's keys: its step 6 documents them
            continue
        value = getattr(EffectsConfig(), f.name)
        shown = (str(value).lower() if isinstance(value, bool)
                 else f'"{value}"' if isinstance(value, str) else str(value))
        assert re.search(rf"^{f.name} = {re.escape(shown)}(\s|$)", code, re.M), f.name
    for f in fields(EffectsTheme):
        assert f"{f.name} = {_hex(getattr(EffectsTheme(), f.name))}" in code, f.name
    for words in ("never shows more than 3 flashes in any one second",
                  "Reduce motion and flashing", "Don't let a flash or shake carry the story",
                  "no bigger than 640×360", "approximate formula", "plays as a `dissolve`",
                  "`Transition` is kept for a later version", "can't be redefined",
                  "One moment, one transition", "The story waits", "finishes the transition"):
        assert words in section, words
    assert "for the moment the picture changes instantly" not in text
    assert "aren't available yet in this engine version, so this line" not in text   # W14
    assert re.search(r"^\| `with` `shake` `flash` `pause` \| available \|$", text, re.M)
    assert "#16-transitions-and-effects" in text
    assert "### Transitions and effects" in _section(text, "Common errors")

    ui = UI.read_text(encoding="utf-8")
    for f in fields(EffectsTheme):
        color = _hex(getattr(EffectsTheme(), f.name))
        assert re.search(rf"^\| `effects\.{f.name}` \| color \| `{color}` \|", ui, re.M), f.name
    timings = _section(ui, "Standard timings")
    for name in ("`cut`", "`dissolve`", "`fade`", "`Mask`", "`shake`", "`flash`",
                 "Reduced flash"):
        assert re.search(rf"^\| {re.escape(name)} \(proposed, F09\) \|", timings, re.M), name
    reduced = timings[timings.index("### Reduced motion and flashing"):]
    for words in ("3 flashes in any 1-second period", "fade-type transition under 1 s",
                  "fades of\n1 s or more", "W61", "at most 50%"):
        assert words in reduced, words
    layer = next(line for line in ui.splitlines() if line.startswith("| 2 | Stage effects |"))
    assert "**Shake** (proposed, F09)" in layer and "**Flash** (proposed, F09)" in layer


# --- AC-F11-67: the "Saves" section and the UI system's notice ---------------------------------

def test_ac_f11_67_saves_section_and_ui_system_notice():
    """``script-language.md`` "Saves": the dev and release folders, testing with
    ``--release`` and ``[game] id``, ``default``, keeping labels, the nearest-point
    question, every ``[saves]`` key with ``autosave_interval = 300  # 5 minutes``, that
    builds leave out ``saves/``, SEC-F11-12's four points, the 32 save words, and W80–W83.
    ``ui-system.md``: §9's Notice and the ``save``/``notice`` tokens are no longer
    proposed. The review step (finding where saves live and how to keep them working in
    under 5 minutes) is the reviewer's."""
    from dataclasses import fields

    from engine.core.config_schema import SavesConfig
    from tests.core.test_config_f11 import F11_WORDS

    text = LANGUAGE.read_text(encoding="utf-8")
    assert "17. Saves ·" in text
    section = _section(text, "Saves")
    blocks = re.findall(r"^ *```[a-z]*\n(.*?)^ *```", section, re.M | re.S)
    code = "\n".join(line.strip() for block in blocks for line in block.splitlines())
    for words in ("`saves/` in the game folder", "the player's own folder",
                  r"%APPDATA%\vn-engine\<id>\saves", "vn-engine/<id>/saves",
                  "python main.py --release", "A release needs `[game] id`",
                  "Give every new variable a `default`", "Keep label names",
                  "Continue from the nearest point?",
                  "This save no longer fits the story and can't be loaded.",
                  "Builds leave out `saves/`",
                  # SEC-F11-12
                  "A shared save can start the story at any line or menu, with any values",
                  "`default` runs on the restored values",
                  "Never build a file name from a story variable",
                  "Never put values from the player's computer in a story variable"):
        assert words in section, words
    assert re.search(r'^id = "[a-z0-9-]+"$', code, re.M)
    assert re.search(r"^default \w+ = False +# new in version", code, re.M)
    assert re.search(r"^\[saves\]$", code, re.M)
    assert re.search(r"^autosave_interval = 300  # 5 minutes$", code, re.M)
    for f in fields(SavesConfig):
        default = getattr(SavesConfig(), f.name)
        shown = str(default).lower() if isinstance(default, bool) else str(default)
        assert re.search(rf"^{f.name} = {shown}(\s|$)", code, re.M), f.name
        assert re.search(rf"^\| `\[saves\] {f.name}` \| `{shown}` \|", section, re.M), f.name
    for key, default in F11_WORDS.items():
        assert re.search(rf'^\| `{key}` \| "{re.escape(default)}" \|$', section, re.M), key
    assert re.findall(r"^\| (W8\d) \|", section, re.M) == ["W80", "W81", "W82", "W83"]
    assert "saving is off: a release run needs [game] id in config.toml" in section
    assert "(#22-run-time-errors)" in text and "(#21-run-time-errors)" not in text   # F14 s6

    ui = UI.read_text(encoding="utf-8")
    assert "proposed, F11" not in ui
    assert re.search(r"^### Notice\s*$", ui, re.M)
    assert "**Save / load and notices.**" in ui
    for token in ("save.text_size", "save.load_fade_ms", "notice.max_width", "notice.sound"):
        assert re.search(rf"^\| `{re.escape(token)}`", ui, re.M), token


# --- AC-F14-17: the "Rollback" section, the UI system's rollback entries, the example -------

# A prelude for the section's story blocks: the two characters they speak with. A block with
# no ``label start:`` gets an empty one, so it loads as a game of its own.
_ROLLBACK_PRELUDE = 'define hana = Character("Hana")\ndefine daichi = Character("Daichi")\n\n'
# Each F14 code → the ``format_message`` arguments of the forms the section shows.
F14_MESSAGES: dict[str, list[tuple]] = {
    "E200": [()],
    "E201": [("of", "off"), ("back", None)],
    "E202": [("off", "now")],
    "E203": [()],
    "E204": [("say", 31), ("nothing", None)],
    "W90": [("bridge", "position")],
}


def test_ac_f14_17_rollback_docs_and_example(tmp_path, caplog):
    """``script-language.md`` "Rollback": what is and isn't rolled back, the persistent
    counter counted twice with its fixes, ``block``/``off``/``on``/``fixed`` with a scare,
    ``[rollback] steps``, E200–E204 and W90 as ``messages.py`` words them; every code block
    loads (story blocks with no error or warning, the TOML block with no config error); the
    reserved words list ``rollback`` as available. ``ui-system.md``: layer 6, the six
    ``rollback.*`` tokens with ``RollbackTheme``'s defaults, and ``words.back``, none
    proposed. ``game/script`` has exactly one ``rollback block``, a ``#`` comment on the line
    above, and the example plays headless (seeds 1–5, waits ended by ``corpus.play``) with
    no WARNING record."""
    import logging
    from dataclasses import fields

    from engine.core.config import load_config
    from engine.core.config_schema import RollbackConfig, RollbackMarkTheme, RollbackTheme
    from engine.runtime.commands import StoryEnded
    from engine.runtime.headless import run_headless
    from engine.runtime.launch import run_launch
    from engine.script.messages import format_message
    from tests.runtime import corpus
    from tests.runtime.menu_story import load_text, write_game
    from tests.runtime.stage_story import load_example

    text = LANGUAGE.read_text(encoding="utf-8")
    assert "proposed, F14" not in text
    section = _section(text, "Rollback")
    flat = " ".join(section.split())
    for words in ("`persistent` data", "Which lines were read and which choices were picked",
                  "The player's settings", "`define` values", "Going forward runs the story "
                  "again", "twice", "Set a value instead of adding to one",
                  "Block rollback right after it", "**A scare**", "`[rollback] steps`",
                  "`rollback block`", "`rollback off`", "`rollback on`", "`rollback fixed`"):
        assert words in flat, words
    assert re.findall(r"^\| ([EW]\d+) \|", section, re.M) == list(F14_MESSAGES)
    for code, forms in F14_MESSAGES.items():
        row = re.search(rf"^\| {code} \|.*$", section, re.M).group(0)
        for args in forms:
            assert f"`{format_message(code, args)}`" in row, (code, args)
    blocks = re.findall(r"^```([a-z]*)\n(.*?)^```", section, re.M | re.S)
    code = "\n".join(body for _, body in blocks)
    for pattern in (r"^    \$ persistent\.count \+= 1\n    \"", r"^    \$ persistent\.count \+= "
                    r"1\n    rollback block$", r"^    flash .*\n(    .*\n)*    rollback block$",
                    r"^            rollback block$", r"^    rollback off$", r"^    rollback on$",
                    r"^    rollback fixed\n    menu:$", r"^\[rollback\]$", r"^steps = 100 ",
                    r"^marker = true "):
        assert re.search(pattern, code, re.M), pattern
    stories = [body for lang, body in blocks if lang == ""]
    assert len(stories) == 6
    for number, body in enumerate(stories):
        story = _ROLLBACK_PRELUDE + body
        if "label start:" not in body:
            story += "\nlabel start:\n    return\n"
        result = load_text(tmp_path / f"story{number}", story)
        assert result.errors == () and result.warnings == (), (body, result.errors,
                                                               result.warnings)
        launch = run_launch(result.program)
        assert launch.namespace is not None and launch.warnings == (), body
    (toml,) = [body for lang, body in blocks if lang == "toml"]
    loaded = load_config(write_game(tmp_path / "config", "label start:\n    return\n", toml))
    assert loaded.errors == []
    assert loaded.config.rollback == RollbackConfig()
    assert re.search(r"^\| `rollback` \| available \|$", text, re.M)
    assert "These 40 words" in text and "(#22-run-time-errors)" in text      # F20: flowchart

    ui = UI.read_text(encoding="utf-8")
    assert "proposed, F14" not in ui
    layer = next(line for line in ui.splitlines() if line.startswith("| 6 | In-game cues |"))
    assert "| F14 |" in layer and "set_cue_layer" in layer and "limit mark" in layer
    rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| `(rollback\.[\w.]+)` \|.*$", ui,
                                                        re.M)}
    for prefix, table in (("rollback.", RollbackTheme()), ("rollback.mark.",
                                                          RollbackMarkTheme())):
        for f in fields(table):
            value = getattr(table, f.name)
            if isinstance(value, RollbackMarkTheme):
                continue
            row = rows.get(prefix + f.name)
            assert row is not None, prefix + f.name
            assert any(word in row for word in _default_words(value)), (row, value)
    assert len(rows) == 6 and "6 (0–12)" in rows["rollback.bump_height"]
    assert '`words.back`, "Back"' in ui

    uses = [(ref, number, lines) for ref, number, lines in _example_lines()
            if lines[number - 1].strip() == "rollback block"]
    assert len(uses) == 1
    ref, number, lines = uses[0]
    assert lines[number - 2].lstrip().startswith("#"), (ref, number)
    result = load_example()
    assert result.program is not None and result.errors == () and result.warnings == ()
    images = corpus.example_images()
    caplog.set_level(logging.DEBUG)
    for seed in corpus.EXAMPLE_SEEDS:
        inputs = corpus.play(result.program, seed, images).inputs
        commands = run_headless(result.program, seed=seed, image_files=images, inputs=inputs,
                                minigames=corpus.example_minigames())
        assert commands[-1] == StoryEnded(), seed
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


# --- AC-F17-37: "nvl (full-screen text)", the UI system's nvl rows, the example's prologue ----

# Each F17 code → the ``format_message`` arguments of the forms the section shows.
F17_MESSAGES: dict[str, list[tuple]] = {
    "E210": [("needs",), ("unknown", "of", "off"), ("case", "on")],
    "E211": [("extra", "on", "now"), ("with", "on", "with dissolve"), ("colon", "on")],
    "W101": [(2, 28)],
    "W102": [(33,)],
    "W100": [("theme", "text_color", "#A0A0A0", 1.72, "black", "#FFF4F8", 0.85),
             ("character", "rin", "#C060A0", 2.54)],
}
# The ten [theme.nvl] tokens → the words their ui-system row shows: default, then range.
F17_TOKENS = {
    "nvl.fill_color": ("`textbox.fill_color`", '"#FFF4F8"'),
    "nvl.fill_opacity": ("0.85", "(0.5–1.0)"),
    "nvl.width": ("920", "(640–1200)"),
    "nvl.top_gap": ("64", "(24–200)"),
    "nvl.bottom_gap": ("72", "(40–200)"),
    "nvl.line_gap": ("20", "(0–80)"),
    "nvl.text_size": ("`textbox.text_size`", "(20–48)"),
    "nvl.text_color": ("`textbox.text_color`",),
    "nvl.name.text_color": ("`textbox.name_tab.text_color`",),
    "nvl.indicator.fill_color": ("`textbox.indicator.fill_color`",),
}


def _nvl_launch_warnings(root: Path, caplog) -> list[str]:
    """Every WARNING (or worse) record of a dev App A launch of ``root``, up to the title
    (the text launch check, with W100 and W101, runs while the story loads)."""
    import logging

    import pygame

    from tests.fakes.text_app import Session

    pygame.init()
    try:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            s = Session(root, dev=True)

            def script(s):
                yield from s.until(lambda: s.frame > 2 and not s.app.loading
                                   and type(s.app.screens.top).__name__ == "TitleScreen")
                yield

            assert s.play(script) == 0
    finally:
        pygame.quit()
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.display
def test_ac_f17_37_nvl_docs_and_example(tmp_path, caplog):
    """``script-language.md``: the "nvl (full-screen text)" section, not proposed, with the
    statements, automatic pages, long lines, menus (top-aligned under the page, the
    question-only page, a new page after a pick), placement, transitions, ``chapter``,
    saves, the 32 lines, ``[theme.nvl]``, the file-order rule, and E210, E211, W100, W101,
    W102 as ``messages.py`` words them; its story block loads and launches with no error or
    warning and its TOML block sets ``[theme.nvl]``; ``nvl`` is available; Common errors has
    the rows; Studio's ``nvl`` doc points at the heading. ``ui-system.md``: the NVL say
    window, layer 3's panel, and the ten ``nvl.*`` tokens with defaults and ranges.
    ``game/``: one ``nvl on``, ``nvl clear``, and ``nvl off``, each under a comment; seeds
    1–5 run 6–10 lines between the first ``NvlPage(on)`` and the next ``NvlPage(off)``; a dev
    launch logs no WARNING."""
    import shutil

    from engine.core.config import load_config
    from engine.runtime.commands import NvlPage, Say
    from engine.runtime.launch import run_launch
    from engine.script.messages import format_message
    from engine.script.statement_docs import all_docs
    from tests.runtime import corpus
    from tests.runtime.menu_story import load_text, write_game

    text = LANGUAGE.read_text(encoding="utf-8")
    assert "proposed, F17" not in text
    section = _subsection(text, "nvl (full-screen text)")
    flat = " ".join(section.split())
    for words in ("`nvl on` switches to **full-screen text**", "`nvl off` goes back to the text "
                  "box", "`nvl clear` starts a new, empty page", "Pages fill up by themselves",
                  "too long for a whole page", "choices sit just under it, lined up from the "
                  "top", "the page shows only the question with the choices under it",
                  "the next line starts a new page", "not directly under `menu:`",
                  "`nvl on with dissolve` is an error", "A `scene` never clears the page",
                  "write `nvl clear` after the `chapter` line", "Every game starts with the "
                  "text box", "rolling back shows the page as it was", "its last 32 lines",
                  "`[theme.nvl]`", "the nearest `nvl on` or `nvl off` above it in the same "
                  "label", "every label starts with the text box"):
        assert words in flat, words
    for code, forms in F17_MESSAGES.items():
        for args in forms:
            assert f"`{format_message(code, args)}`" in section, (code, args)
    blocks = re.findall(r"^```([a-z]*)\n(.*?)^```", section, re.M | re.S)
    (story,) = [body for lang, body in blocks if lang == ""]
    result = load_text(tmp_path / "story", 'define hana = Character("Hana", color="#A02860")\n'
                       "label start:\n" + story + "    return\n")
    assert result.errors == () and result.warnings == (), (result.errors, result.warnings)
    launch = run_launch(result.program)
    assert launch.namespace is not None and launch.warnings == ()
    (toml,) = [body for lang, body in blocks if lang == "toml"]
    loaded = load_config(write_game(tmp_path / "config", "label start:\n    return\n", toml))
    assert loaded.errors == []
    nvl = loaded.config.theme.nvl
    assert (nvl.fill_color, nvl.fill_opacity, nvl.text_color) == ((0x3A, 0x2A, 0x3F), 0.9,
                                                                   (0xFF, 0xF4, 0xF8))
    for key in ("fill_color", "fill_opacity", "width", "top_gap", "bottom_gap", "line_gap",
                "text_size", "text_color", "name.text_color", "indicator.fill_color"):
        assert re.search(rf"^\| `{re.escape(key)}` \|", section, re.M), key
    assert re.search(r"^\| `nvl` \| available \|$", text, re.M)
    errors = _subsection(text, "Full-screen text")
    for start in ("nvl needs on, off, or clear", "nvl on takes nothing else",
                  "full-screen text appears instantly", "this full-screen line needs 2 pages",
                  "33 lines have gone by", "config.toml: [theme.nvl] text_color",
                  "rin's color #C060A0"):
        assert f"`{start}" in errors, start
    (doc,) = [d for d in all_docs() if d.key == "nvl"]
    assert doc.docs == "nvl (full-screen text)"

    ui = UI.read_text(encoding="utf-8")
    assert "proposed, F17" not in ui and "F17 (reserved)" not in ui
    layer = next(line for line in ui.splitlines() if line.startswith("| 3 | Say window |"))
    assert "F17" in layer and "NVL panel" in layer and "Never both" in layer
    assert any(line.startswith("| Say window (NVL, full-screen text) |")
               for line in ui.splitlines())
    rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| `(nvl\.[\w.]+)` \|.*$", ui,
                                                        re.M)}
    assert sorted(rows) == sorted(F17_TOKENS)
    for token, words in F17_TOKENS.items():
        for word in words:
            assert word in rows[token], (token, word)

    lines = [(ref, number, all_lines) for ref, number, all_lines in _example_lines()
             if all_lines[number - 1].strip().startswith("nvl ")]
    assert [all_lines[number - 1].strip() for _, number, all_lines in lines] == [
        "nvl on", "nvl clear", "nvl off"]
    for ref, number, all_lines in lines:
        assert all_lines[number - 2].lstrip().startswith("#"), (ref, number)
    program = corpus.example_program()
    images = corpus.example_images()
    for seed in corpus.EXAMPLE_SEEDS:
        commands = corpus.play(program, seed, images, corpus.EXAMPLE_PICKS[seed]).commands
        start = next(i for i, c in enumerate(commands) if type(c) is NvlPage and c.on)
        end = next(i for i, c in enumerate(commands) if i > start and type(c) is NvlPage
                   and not c.on)
        assert 6 <= sum(type(c) is Say for c in commands[start:end]) <= 10, seed
    game = Path(shutil.copytree(EXAMPLE, tmp_path / "game",
                                ignore=shutil.ignore_patterns("logs", "saves", "persistent",
                                                              "settings", "characters")))
    assert _nvl_launch_warnings(game, caplog) == []


# --- AC-F19-34: "ending, lock route, unlock route", the reserved words, no author views -------

# Each F19 code → the ``format_message`` arguments of the forms the section quotes in full.
F19_MESSAGES: dict[str, list[tuple]] = {
    "E240": [("need",), ("top",)],
    "E241": [("ending", "good", ("script/story.vns", 40))],
    "E242": [("long", "title", 140, 120), ("45",)],
    "E243": [("label", "promis", "promise"), ("until", "god", "good"), ("twice", "good"),
             ("many", 40, 32)],
    "E244": [("ending", "god", "good"), ("unlock_ending",)],
    "E245": [("change", "endings"), ("default", "endings")],
    "E246": [("ending", 1204, 1000)],
    "W130": [()],
    "W131": [("endings", 2)],
    "W132": [("promise", ("sad", "good"))],
}
# An author value named like a view: a default, an assignment (plain, augmented, or to an
# item), del, a literal setattr/delattr, or a mutator call (bindings.MUTATORS, dunders).
_VIEW = r"persistent\.(?:endings|routes)\b"


def _view_writes() -> re.Pattern:
    from engine.script.bindings import MUTATORS

    mutators = "|".join(sorted(map(re.escape, MUTATORS)))
    return re.compile(rf"default\s+{_VIEW}|\bdel\s+{_VIEW}"
                      rf"|{_VIEW}\s*(?:\[[^\]\n]*\])?\s*(?:[-+*/%&|^@]|//|\*\*|<<|>>)?=(?!=)"
                      rf"|{_VIEW}\.(?:{mutators}|__\w+__)\("
                      r"|(?:set|del)attr\(\s*persistent\s*,\s*['\"](?:endings|routes)['\"]")


def test_ac_f19_34_routes_and_endings_docs(tmp_path):
    """``script-language.md`` section 7's "ending, lock route, unlock route": not proposed,
    with 01 §5.1's ending, §5.2's ``lock route … until``, §5.4's reads and menu, the rules
    (card, ``until``, ``lock ending``, ``show_locked``, read-only views, what never changes
    them), and E240–E246, W130–W132 as ``messages.py`` words them; every code block loads
    in dev and launches with no error or warning (a ``label start:`` and a stub label for
    each missing ``jump`` target added). Reserved words list ``ending`` ``lock`` ``unlock``
    as available, the docs table points at the heading, and no file in ``docs/``, ``game/``,
    or ``tests/fixtures/`` writes ``persistent.endings`` or ``persistent.routes`` (except
    F02's E245 message cases, whose subject they are)."""
    from engine.runtime.launch import run_launch
    from engine.script import load_story
    from engine.script.loader import LoadOptions
    from engine.script.messages import format_message
    from engine.script.statement_docs import all_docs
    from tests.runtime.menu_story import write_game

    text = LANGUAGE.read_text(encoding="utf-8")
    assert "proposed, F19" not in text
    section = _subsection(text, "ending, lock route, unlock route")
    flat = " ".join(section.split())
    for words in ("ends the story", "remembers the ending across playthroughs",
                  "for 3 seconds", "`0` shows no card", "inside a `call`", "**above** it",
                  "`[theme.chapter]`", "quitting during the card keeps it",
                  "Add `until sad, good`", "**`unlock route name`** opens a route for good",
                  "**`lock ending name`** makes the game forget an ending",
                  "doesn't stop a `jump` into a locked route", "`show_locked = true`",
                  "but not change or give a `default`", "never change endings or routes",
                  '"delete persistent data"'):
        assert words in flat, words
    for code, forms in F19_MESSAGES.items():
        for args in forms:
            assert f"`{format_message(code, args)}`" in section, (code, args)
    blocks = re.findall(r"^```([a-z]*)\n(.*?)^```", section, re.M | re.S)
    code = "\n".join(body for _, body in blocks)
    for pattern in (r'^label river_end:\n    hana "Maybe next year\."\n'
                    r'    ending sad "Sad End" "Paper Ashes"$',
                    r'^lock route promise "Hana\'s Promise" until sad, good$',
                    r'^    if "sad" in persistent\.endings:$',
                    r'^        "Wait at the bridge" if "promise" in persistent\.routes:$',
                    r"^    if len\(persistent\.endings\) >= 3:$",
                    r"^    lock ending sad$", r'^    ending true "True End" "Hana\'s Promise"$'):
        assert re.search(pattern, code, re.M), pattern
    assert len(blocks) == 2 and all(lang == "" for lang, _ in blocks)
    for number, (_, body) in enumerate(blocks):
        story = 'define hana = Character("Hana")\n\n' + body
        if "label start:" not in body:
            story += "\nlabel start:\n    return\n"
        for target in sorted(set(re.findall(r"^\s+jump (\w+)$", body, re.M))):
            if not re.search(rf"^label {target}:", body, re.M):
                story += f"\nlabel {target}:\n    return\n"
        result = load_story(write_game(tmp_path / f"story{number}", story),
                            LoadOptions(dev=True))
        assert result.errors == () and result.warnings == (), (body, result.errors,
                                                               result.warnings)
        launch = run_launch(result.program, dev=True)
        assert launch.namespace is not None and launch.warnings == (), body
    assert re.search(r"^\| `ending` `lock` `unlock` \| available \|$", text, re.M)
    docs = {d.docs for d in all_docs() if d.feature == "F19"}
    assert docs == {"ending, lock route, unlock route"}

    writes = _view_writes()
    assert writes.search('$ persistent.endings.append("sad")')       # the pattern finds one
    assert not writes.search('if "sad" in persistent.endings:')
    skip = REPO / "tests" / "fixtures" / "F02" / "messages"
    found = []
    for root in ("docs", "game", "tests/fixtures"):
        for path in sorted((REPO / root).rglob("*")):
            if (not path.is_file() or skip in path.parents
                    or path.suffix not in (".md", ".vns", ".toml", ".txt", ".py")):
                continue
            for match in writes.finditer(path.read_text(encoding="utf-8", errors="replace")):
                found.append((path.relative_to(REPO).as_posix(), match.group(0)))
    assert found == []


# --- AC-F21-39: "lock tip, lock item, unlock (codex)", reserved words, ui-system rows ----------

F21_HEADING = "lock tip, lock item, unlock (codex)"
# The first form of E250–E256 and W141 (format_message's defaults; E253 and E255 with their
# did-you-mean), as the section quotes them.
F21_MESSAGES: dict[str, tuple] = {
    "E250": (), "E251": (), "E252": (), "E253": ("unknown", "tip", "lantern", "lanterns"),
    "E254": (), "E255": ("unknown", "itmes", "items"), "E256": (), "W141": (),
}


def test_ac_f21_39_codex_docs(tmp_path):
    """``script-language.md`` section 7's codex section: not proposed, with the walkthrough's
    declarations (06 §5 ``walk/``), 01 §5.3's reads, the rules (tips kept, items per
    playthrough, ``codex.tips``/``codex.items``, ``[codex]``, the tokens and words), and the
    first form of E250–E256 and W141; its code blocks together load in dev and launch with no
    error or warning (``define`` lines and a ``label start:`` added, and the item's picture
    given). Reserved words say ``tip`` and ``item`` aren't reserved and ``codex`` is an engine
    name; F21's docs-table rows point at the heading; ``ui-system.md`` §3 has the three
    ``codex`` tokens."""
    from engine.runtime.images import ImageSource
    from engine.runtime.launch import run_launch
    from engine.script import load_story
    from engine.script.loader import LoadOptions
    from engine.script.messages import format_message
    from engine.script.statement_docs import all_docs
    from tests.runtime.menu_story import write_game

    text = LANGUAGE.read_text(encoding="utf-8")
    assert "proposed, F21" not in text
    section = _subsection(text, F21_HEADING)
    flat = " ".join(section.split())
    for words in ("**Tips are kept across playthroughs.**",
                  "**Items belong to this playthrough.**", "**`codex.tips`**",
                  "**`codex.items`**", "**`lock item name`** takes an item away",
                  "`[codex] notify`", "`[codex] show_locked`", "`codex.new.fill_color`",
                  "`codex.locked.text_color`", "`codex.image_height`", "`codex_empty`",
                  "after History", "`[title] entries`"):
        assert words in flat, words
    for code, args in F21_MESSAGES.items():
        assert format_message(code, args) in section, code
    blocks = re.findall(r"^```([a-z]*)\n(.*?)^```", section, re.M | re.S)
    assert len(blocks) == 2 and all(lang == "" for lang, _ in blocks)
    code = "\n".join(body for _, body in blocks)
    walk = (REPO / "tests" / "fixtures" / "F21" / "walk" / "script" / "main.vns").read_text(
        encoding="utf-8")
    declarations = [line for line in walk.splitlines()
                    if line.startswith("lock ") or line.startswith('    "')][:6]
    assert len(declarations) == 6 and "\n".join(declarations) in code
    for pattern in (r'^    if "red_lantern" in codex\.items:$',
                    r'^        "Ask about the river god" if "river_god" in codex\.tips:$',
                    r"^    unlock item red_lantern$", r"^    unlock tip lanterns$",
                    r"^    lock item red_lantern$"):
        assert re.search(pattern, code, re.M), pattern
    story = ('define hana = Character("Hana")\ndefine daichi = Character("Daichi")\n'
             'define thought = Character("")\n\n' + code + "\nlabel start:\n    jump stall\n")
    result = load_story(write_game(tmp_path / "codex", story), LoadOptions(dev=True))
    assert result.errors == () and result.warnings == (), (result.errors, result.warnings)
    launch = run_launch(result.program, dev=True,
                        images=ImageSource.from_files(("images/items/red_lantern.png",)))
    assert launch.namespace is not None and launch.warnings == (), launch.warnings
    reserved = " ".join(_section(text, "Reserved words").split())
    assert "`tip` and `item` aren't reserved" in reserved
    assert "`codex`, like `dice` and `points`, is an engine name" in reserved
    assert {d.docs for d in all_docs() if d.feature == "F21"} == {F21_HEADING}
    tokens = UI.read_text(encoding="utf-8")
    for token in ("codex.new.fill_color", "codex.locked.text_color", "codex.image_height"):
        assert re.search(rf"^\| `{re.escape(token)}` \| ", tokens, re.M), token
    assert "proposed, F21" not in tokens


# --- AC-F24-19: the poem game in docs/minigames.md, its tokens in ui-system.md ----------------

MINIGAMES = REPO / "docs" / "minigames.md"
_W29 = {f"w{i:02}": "yuri" for i in range(29)}
# R1–R13 → arguments whose first problem it is (the forms the section's table shows).
F24_REFUSALS: dict[str, list[dict]] = {
    "R1": [{"words": ["sunshine"]}],
    "R2": [{"words": {f"w{i}": "yuri" for i in range(2400)}}],
    "R3": [{"words": {"cherry blossoms in spring": "yuri", **_W29}},
           {"words": {"": "yuri", **_W29}}, {"words": {"a\nb": "yuri", **_W29}},
           {"words": {"rain ": "yuri", **_W29}}],
    "R4": [{"words": {"Rain": "yuri", "rain": "yuri", **_W29}}],
    "R5": [{"words": {"sunshine": ["sayori"], **_W29}}],
    "R6": [{"words": {"sunshine": {"Sayori!": 3}, **_W29}},
           {"words": {"sunshine": {f"m{i}": 1 for i in range(20)}, **_W29}}],
    "R7": [{"words": {"sunshine": {"sayori": 1.5}, **_W29}}],
    "R8": [{"rounds": 0}],
    "R9": [{"page_words": 20}],
    "R10": [{"words": {f"w{i}": "yuri" for i in range(12)}}],
    "R11": [{"to_points": "yes"}],
    "R12": [{"result": "winer"}],
    "R13": [{"words": {"sunshine": {"sayory": 3}, **_W29}}],
}


def _poem_reason(change: dict) -> str:
    from engine.minigames.bundled import poem_rules

    args = {"words": _W29, **poem_rules.DEFAULTS, **change}
    found = poem_rules.problem(args) or poem_rules.meter_problem(
        args, ("sayori", "natsuki", "yuri"))
    assert found is not None, change
    return found


def test_ac_f24_19_poem_game_docs(tmp_path):
    """``docs/minigames.md``'s "Poem game", not proposed: the ``define`` template, 01 §5.1's
    arguments (with ``PoemGame``'s defaults), R1–R13 as ``poem_rules`` words them, each with
    a fix, E272's one-argument form, the testing sentence ("first" ``rounds`` words), the
    saved list, the G5 notes, and the API 1.1 notes. Its code blocks together load in dev
    with the bundled minigames, launch, and play headless with no error or warning, with the
    outcome the section says (``"sayori"``). ``ui-system.md`` lists the ten
    ``plugin.poem_game`` tokens and their clamped ranges."""
    import tomllib

    from engine.minigames.bundled.poem_game import TOKENS, PoemGame
    from engine.runtime.commands import Say
    from engine.runtime.headless import run_headless
    from engine.runtime.launch import run_launch
    from engine.script import load_story
    from engine.script.loader import LoadOptions
    from engine.script.messages import format_message
    from tests.runtime.menu_story import write_game
    from tests.runtime.stage_story import example_minigames

    text = MINIGAMES.read_text(encoding="utf-8")
    heading = re.search(r"^## Poem game\s*$", text, re.M)
    assert heading is not None
    following = re.search(r"^## ", text[heading.end():], re.M)
    section = text[heading.start():heading.end() + following.start() if following else None]
    assert "proposed" not in section
    flat = " ".join(section.split())
    for words in ("picks the first `rounds` words of the list, in the order you wrote them",
                  "A save made at a poem keeps its own copy of the word list",
                  "`a | b` puts the words of `a` first",
                  "Python keeps only the second one, and no warning tells you",
                  "`rounds + page_words - 1`", "`check_story(self, args, story)`",
                  "`outcome_for(self, kind, args, story)`", '`api = "1.0"` never has them',
                  "`closest(written, names)`", "`[theme.plugin.poem_game]`",
                  "`[words.plugin.poem_game]`"):
        assert words in flat, words
    for name, spec in PoemGame.args.items():                    # 01 §5.1's table
        shown = f'"{spec.default}"' if type(spec.default) is str else repr(spec.default)
        default = "none (you must give it)" if name == "words" else f"`{shown}`"
        assert re.search(rf"^\| `{name}` \| {re.escape(default)} \|", section, re.M), name
    for number, changes in F24_REFUSALS.items():
        rows = re.findall(rf"^\| {number} \| `([^|]+)` \| ([^|]+) \|$", section, re.M)
        assert [reason for reason, _ in rows] == [_poem_reason(c) for c in changes], number
        assert all(len(fix.strip()) > 10 for _, fix in rows), number
    one = format_message("E272", ("plugin", "poem_game", "words", "day1_words",
                                  _poem_reason(F24_REFUSALS["R7"][0])))
    assert f"`{one}`" in section and "`poem_game can't use these arguments:`" in section

    blocks = re.findall(r"^```([a-z]*)\n(.*?)^```", section, re.M | re.S)
    assert [lang for lang, _ in blocks] == ["", "", "toml"]
    words = tomllib.loads(blocks[2][1])["words"]["plugin"]["poem_game"]
    assert words == PoemGame.words
    story = (blocks[0][1] + "\n" + blocks[1][1]
             + "\nlabel start:\n    call day1_poem\n    call day2_poem\n    return\n")
    sigs = example_minigames()
    result = load_story(write_game(tmp_path / "poem", story),
                        LoadOptions(dev=True, minigames=sigs))
    assert result.errors == () and result.warnings == (), (result.errors, result.warnings)
    launch = run_launch(result.program, dev=True)
    assert launch.namespace is not None and launch.warnings == ()
    commands = run_headless(result.program, seed=1, dev=True, minigames=sigs)
    assert type(commands[-1]).__name__ == "StoryEnded", commands[-1]
    assert "Sayori clapped before I had finished reading it out." in [
        c.text for c in commands if type(c) is Say]

    tokens = UI.read_text(encoding="utf-8")
    for token in TOKENS:
        assert re.search(rf"^\| `plugin\.poem_game\.{re.escape(token)}` \| ", tokens, re.M), token
    for limits in ("800 (560–1232)", "32 (24–48)", "28 (24–40)"):
        assert limits in tokens, limits


# --- AC-F25-21: present evidence in docs/minigames.md, its tokens in ui-system.md -------------

_SAYS = {"after_dark": "Nobody went near the shrine after dark.",
         "gate": "The gate was locked all night. I checked it myself.",
         "priest": "Only the priest has a key to that gate."}
# R1–R14 → the changes to 01 §5.2's line whose first problem it is (the table's forms).
F25_REFUSALS: dict[str, list[dict]] = {
    "R1": [{"testimony": ["Nobody went near the shrine."]},
           {"testimony": {f"s{i}": "Yes." for i in range(15)}}],
    "R2": [{"testimony": {"the gate": "Locked."}}],
    "R3": [{"testimony": {"gate": "W" * 140}}, {"testimony": {"gate": ""}},
           {"testimony": {"gate": "Locked\nall night."}}, {"testimony": {"gate": "Locked. "}}],
    "R4": [{"answer": "brass_key"}],
    "R5": [{"answer": {"gat": "brass_key"}}],
    "R6": [{"answer": {"gate": 3}}],
    "R7": [{"at": "gat"}],
    "R8": [{"speaker": 7}],
    "R9": [{"press": "yes"}],
    "R10": [{"evidence": "Evidence"}],
    "R11": [{"penalty": 3}, {"penalty_max": 0}, {"cost": 6}],
    "R12": [{"answer": {"gate": "brass_kye"}}, {"answer": {"gate": "lanterns"}}],
    "R13": [{"penalty": "credibilty"}],
    "R14": [{"evidence": ["Evidnce"]},
            {"evidence": ["Evidence"], "answer": {"gate": "shrine_photo"}}],
}


def _present_reason(change: dict) -> str:
    from engine.core.minigame_types import StoryNames
    from engine.minigames.bundled import present_rules

    story = StoryNames(meters=("credibility",),
                       items=("brass_key", "festival_map", "shrine_photo"), tips=("lanterns",),
                       item_categories=(("Evidence", ("brass_key", "festival_map")),
                                        ("Photos", ("shrine_photo",))))
    args = {"testimony": _SAYS, "answer": {"gate": "brass_key"}, **present_rules.DEFAULTS,
            "speaker": "Daichi", "penalty": "credibility", **change}
    found = present_rules.problem(args) or present_rules.story_problem(args, story)
    assert found is not None, change
    return found


def test_ac_f25_21_present_evidence_docs(tmp_path):
    """``docs/minigames.md``'s "Present evidence", not proposed: 01 §5.2's loop, §5.1's
    arguments (with ``PresentEvidence``'s defaults), R1–R14 as ``present_rules`` words them,
    each with a fix, E272's "these arguments" form (G9), the testing line ("first" statement
    with an answer), and the advice to set ``penalty_max`` to the meter's top. Its story block
    loads in dev with the bundled minigames, launches, and plays headless with no error or
    warning to the breakthrough the section names; its TOML blocks are the plugin's sounds
    and words. ``ui-system.md`` lists every ``plugin.present_evidence`` token."""
    import tomllib

    from engine.minigames.bundled.present_evidence import TOKENS, PresentEvidence
    from engine.runtime.commands import Say
    from engine.runtime.headless import run_headless
    from engine.runtime.launch import run_launch
    from engine.script import load_story
    from engine.script.loader import LoadOptions
    from engine.script.messages import format_message
    from tests.runtime.menu_story import write_game
    from tests.runtime.stage_story import example_minigames

    text = MINIGAMES.read_text(encoding="utf-8")
    heading = re.search(r"^## Present evidence\s*$", text, re.M)
    assert heading is not None
    following = re.search(r"^## ", text[heading.end():], re.M)
    section = text[heading.start():heading.end() + following.start() if following else None]
    assert "proposed" not in section
    flat = " ".join(section.split())
    for words in ("presents the right item on the first statement that has an answer",
                  "Set `penalty_max` to the meter's top", "Shift+F8 in a test run, and Skip "
                  "Game, do the same", "`[theme.plugin.present_evidence]`",
                  "`[words.plugin.present_evidence]`", "W173",
                  "`$ stmt = shown[\"statement\"]` and `at=stmt`"):
        assert words in flat, words
    for name, spec in PresentEvidence.args.items():             # 01 §5.1's table
        default = ("none (you must give it)" if name in ("testimony", "answer")
                   else f"`{spec.default!r}`")
        assert re.search(rf"^\| `{name}` \| {re.escape(default)} \|", section, re.M), name
    for number, changes in F25_REFUSALS.items():
        rows = re.findall(rf"^\| {number} \| `([^|]+)` \| ([^|]+) \|$", section, re.M)
        assert [reason for reason, _ in rows] == [_present_reason(c) for c in changes], number
        assert all(len(fix.strip()) > 10 for _, fix in rows), number
    one = format_message("E272", ("plugin_all", "present_evidence",
                                  _present_reason(F25_REFUSALS["R12"][0])))
    assert f"`{one}`" in section and "`present_evidence can't use these arguments:`" in section

    blocks = re.findall(r"^```([a-z]*)\n(.*?)^```", section, re.M | re.S)
    assert [lang for lang, _ in blocks] == ["", "toml", "toml"]
    sounds = tomllib.loads(blocks[1][1])["theme"]["plugin"]["present_evidence"]
    assert set(sounds) == {"press_sound", "present_sound"} <= set(TOKENS)
    words = tomllib.loads(blocks[2][1])["words"]["plugin"]["present_evidence"]
    assert words == PresentEvidence.words
    story = blocks[0][1] + "\nlabel start:\n    call trial\n    return\n"
    sigs = example_minigames()
    result = load_story(write_game(tmp_path / "present", story),
                        LoadOptions(dev=True, minigames=sigs))
    assert result.errors == () and result.warnings == (), (result.errors, result.warnings)
    launch = run_launch(result.program, dev=True)
    assert launch.namespace is not None and launch.warnings == ()
    commands = run_headless(result.program, seed=1, dev=True, minigames=sigs)
    assert type(commands[-1]).__name__ == "StoryEnded", commands[-1]
    assert "Objection! The key was outside the gate all along." in [
        c.text for c in commands if type(c) is Say]

    tokens = UI.read_text(encoding="utf-8")
    for token in TOKENS:
        assert re.search(rf"^\| `plugin\.present_evidence\.{re.escape(token)}` \| ", tokens,
                         re.M), token
    assert "| 28 (24–40) | The statement," in tokens


# --- AC-F26-22: the phone chat in docs/minigames.md, its tokens in ui-system.md ---------------

def _late(at: int | None = None, value: object = None, **reply: object) -> list:
    """Template C's ``late_chat`` with step ``at`` (from 1) replaced, or ask ``awake``'s
    replies changed (``reply``)."""
    import copy

    from tests.fixtures.F26.chats import LATE_CHAT
    chat = copy.deepcopy(LATE_CHAT)
    if at is not None:
        chat[at - 1] = value
    chat[2].update(reply)
    return chat


# R1–R14 → arguments whose first problem it is (the forms the section's table shows).
F26_REFUSALS: dict[str, list[dict]] = {
    "R1": [{"chat": {"you awake?": 1}}],
    "R2": [{"chat": ["hi"] * 240},
           {"chat": [{"ask": f"a{n}", **{k: ["R", *["f"] * 5] for k in "wxyz"}}
                     for n in range(50)]}],
    "R3": [{"chat": _late(4, ["11:51 PM"])}, {"chat": _late(4, {"time": "1 AM", "me": "hi"})}],
    "R4": [{"chat": _late(1, "w" * 320)}, {"chat": _late(1, "")},
           {"chat": _late(1, "a" + "\n" * 5 + "b")}, {"chat": _late(1, "you\tawake?")},
           {"chat": _late(1, "you awake? ")}, {"chat": _late(1, {"me": 3})}],
    "R5": [{"chat": _late(1, {"": "hi"})}, {"chat": _late(1, {"Natsuki ": "hi"})}],
    "R6": [{"chat": _late(4, {"time": ""})}],
    "R7": [{"chat": _late(3, {"ask": "stay up?", "yes": "Yes"})},
           {"chat": _late() + [{"ask": "awake", "yes": "Yes"}]}],
    "R8": [{"chat": _late(3, {"ask": "awake", **{k: k for k in "abcde"}})},
           {"chat": _late(3, {"ask": "awake", "say yes": "Yes"})}],
    "R9": [{"chat": _late(yes=3)}, {"chat": _late(yes="w" * 95)},
           {"chat": _late(yes="Yeah,\nwhat's up?")}],
    "R10": [{"chat": _late(yes=["Yeah", {"ask": "x", "a": "A"}])},
            {"chat": _late(yes=["Yeah"] + ["ok"] * 25)}],
    "R11": [{"chat": _late(ignore="")}],
    "R12": [{"chat": [{"ask": f"a{n}", "x": "X"} for n in range(25)]}],
    "R13": [{"contact": 3}, {"contact": " Sayori"}],
    "R14": [{"time": 2342}],
}


def _phone_reason(change: dict) -> str:
    from engine.minigames.bundled import phone_rules
    from tests.fixtures.F26.chats import LATE

    found = phone_rules.problem({**LATE, **change})
    assert found is not None, change
    return found


def test_ac_f26_22_phone_chat_docs(tmp_path):
    """``docs/minigames.md``'s "Phone chat", not proposed: the step table, the ``define``
    template, the arguments (with ``PhoneChat``'s defaults), R1–R14 as ``phone_rules`` words
    them, each with a fix, E272's "these arguments" form (G2), deeper branches as two
    ``minigame`` lines, and the testing sentence ("first reply", ``finish``, "list the neutral
    reply first"). Its story blocks together load in dev with the bundled minigames, launch,
    and play headless with no error or warning to the line the first replies lead to; its
    TOML blocks are tokens and the plugin's words. ``ui-system.md`` lists every
    ``plugin.phone_chat`` token and its clamped ranges."""
    import tomllib

    from engine.minigames.bundled.phone_chat import TOKENS, PhoneChat
    from engine.runtime.commands import Say, StartMinigame
    from engine.runtime.headless import run_headless
    from engine.runtime.launch import run_launch
    from engine.script import load_story
    from engine.script.loader import LoadOptions
    from engine.script.messages import format_message
    from tests.runtime.menu_story import write_game
    from tests.runtime.stage_story import example_minigames

    text = MINIGAMES.read_text(encoding="utf-8")
    heading = re.search(r"^## Phone chat\s*$", text, re.M)
    assert heading is not None
    following = re.search(r"^## ", text[heading.end():], re.M)
    section = text[heading.start():heading.end() + following.start() if following else None]
    assert "proposed" not in section
    flat = " ".join(section.split())
    for words in ("picks the first reply of every ask", "give it with `finish`",
                  "list the neutral reply first", "**Deeper branches.**",
                  "start a second chat inside the `if`", "`[theme.plugin.phone_chat]`",
                  "`[words.plugin.phone_chat]`", "W176", "Saving during a chat saves its start"):
        assert words in flat, words
    for step in ('`"you awake?"`', '`{"me": "On my way."}`', '`{"time": "11:51 PM"}`',
                 '`{"ask": "walk"'):
        assert re.search(rf"^\| {re.escape(step)}", section, re.M), step
    for name, spec in PhoneChat.args.items():
        default = ("none (you must give it)" if name in ("chat", "contact")
                   else f"`{spec.default!r}`")
        assert re.search(rf"^\| `{name}` \| {re.escape(default)} \|", section, re.M), name
    for number, changes in F26_REFUSALS.items():
        rows = re.findall(rf"^\| {number} \| `([^|]+)` \| ([^|]+) \|$", section, re.M)
        assert [reason for reason, _ in rows] == [_phone_reason(c) for c in changes], number
        assert all(len(fix.strip()) > 10 for _, fix in rows), number
    one = format_message("E272", ("plugin_all", "phone_chat",
                                  _phone_reason(F26_REFUSALS["R9"][1])))
    assert f"`{one}`" in section and "`phone_chat can't use these arguments:`" in section

    blocks = re.findall(r"^```([a-z]*)\n(.*?)^```", section, re.M | re.S)
    assert [lang for lang, _ in blocks] == ["", "", "toml", "toml"]
    theme = tomllib.loads(blocks[2][1])["theme"]["plugin"]["phone_chat"]
    assert {f"{part}.{key}" for part, keys in theme.items() for key in keys} <= set(TOKENS)
    assert tomllib.loads(blocks[3][1])["words"]["plugin"]["phone_chat"] == PhoneChat.words
    story = (blocks[0][1] + "\n" + blocks[1][1]
             + "\nlabel start:\n    call night_texts\n    call walk_texts\n    return\n")
    sigs = example_minigames()
    result = load_story(write_game(tmp_path / "phone", story),
                        LoadOptions(dev=True, minigames=sigs))
    assert result.errors == () and result.warnings == (), (result.errors, result.warnings)
    launch = run_launch(result.program, dev=True)
    assert launch.namespace is not None and launch.warnings == ()
    commands = run_headless(result.program, seed=1, dev=True, minigames=sigs)
    assert type(commands[-1]).__name__ == "StoryEnded", commands[-1]
    assert [c.name for c in commands if type(c) is StartMinigame] == ["phone_chat"] * 2
    assert "I set my alarm ten minutes early." in [c.text for c in commands if type(c) is Say]

    tokens = UI.read_text(encoding="utf-8")
    for token in TOKENS:
        assert re.search(rf"^\| `plugin\.phone_chat\.{re.escape(token)}` \| ", tokens,
                         re.M), token
    for limits in ("420 (360–600)", "28 (24–40)", "24 (24–36)"):
        assert f"| {limits} | " in tokens, limits


# --- AC-F20-70: "flowchart (the story map)", reserved words, ui-system tokens and words -------

F20_HEADING = "flowchart (the story map)"
# Each F20 code → the ``format_message`` arguments of the forms the section quotes in full.
F20_MESSAGES: dict[str, list[tuple]] = {
    "E260": [(), ("scene_title",)], "E261": [(), ("top",)], "E262": [(), ("chapter",)],
    "E263": [(), ("tags",)], "E264": [()], "E265": [()], "W150": [()], "W151": [()],
    "W152": [()], "W153": [()],
}


def test_ac_f20_70_flowchart_docs(tmp_path):
    """``script-language.md`` section 7's "flowchart (the story map)": not proposed, with what
    is a box by default, scene and menu marks, ``omit``, ``hidden``, ``no jump``, forget per
    label, what a jump keeps and resets, the four ``[flowchart]`` keys, SEC-F20-16's notes,
    and E260–E265, W150–W155 as worded; its code blocks together load in dev with no error
    or warning (definitions, a start, and stub endings added) and launch clean. Reserved
    words list ``flowchart``; F20's docs-table rows point at the heading; ``ui-system.md``
    lists the ``flowchart`` tokens and the 18 words, none proposed."""
    from engine.core.config_schema import FlowchartConfig, FlowchartTheme, WordsConfig
    from engine.runtime.launch import run_launch
    from engine.script import load_story
    from engine.script.flowgraph import FlowOptions
    from engine.script.loader import LoadOptions
    from engine.script.messages import format_message
    from engine.script.statement_docs import all_docs
    from tests.runtime.menu_story import write_game

    text = LANGUAGE.read_text(encoding="utf-8")
    assert "proposed, F20" not in text
    section = _subsection(text, F20_HEADING)
    flat = " ".join(section.split())
    for words in ("every `chapter` and every `ending`", "a menu whose choices lead to different "
                  "boxes", "**`flowchart scene \"Title\"`**", "**`flowchart omit`**",
                  "**`hidden`**", "**`no jump`**", "**`flowchart forget stall`** forgets only "
                  "the boxes written in label `stall`", "**A jump**", "It keeps everything "
                  "the game remembers across playthroughs", "conditions run again",
                  "**Jump points are files.**", "**Delete progress** in Settings and "
                  "`flowchart forget` delete them; deleting saves doesn't"):
        assert words in flat, words
    for key in dataclasses.fields(FlowchartConfig):
        assert f"`[flowchart] {key.name}`" in section, key.name
    for code, forms in F20_MESSAGES.items():
        for args in forms:
            assert f"`{format_message(code, args)}`" in section, (code, args)
    for dev in (format_message("W154", ("scene:stall",)),
                format_message("W155", ("scene:stall", "no state is kept for it"))):
        assert f"`{dev}`" in section, dev
    blocks = re.findall(r"^```([a-z]*)\n(.*?)^```", section, re.M | re.S)
    assert len(blocks) == 2 and all(lang == "" for lang, _ in blocks)
    story = ('define hana = Character("Hana")\ndefine daichi = Character("Daichi")\n'
             "default coins = 2\n\n" + "\n".join(body for _, body in blocks)
             + '\nlabel start:\n    "Welcome."\n    jump festival\n'
             + 'label river:\n    ending sad "Sad End" "Paper Ashes"\n'
             + 'label shrine:\n    ending good "Good End" "Lanterns Rising"\n')
    result = load_story(write_game(tmp_path / "flow", story),
                        LoadOptions(dev=True, flowchart=FlowOptions()))
    assert result.errors == () and result.warnings == (), (result.errors, result.warnings)
    assert {n.id for n in result.program.flowgraph.nodes} >= {
        "scene:stall", "scene:promise", "chapter:festival", "ending:true"}
    launch = run_launch(result.program, dev=True)
    assert launch.namespace is not None and launch.warnings == ()
    assert re.search(r"^\| `flowchart` \| available \|$", text, re.M)
    assert {d.docs for d in all_docs() if d.feature == "F20"} == {F20_HEADING}

    tokens = UI.read_text(encoding="utf-8")
    assert "proposed, F20" not in tokens
    for f in dataclasses.fields(FlowchartTheme):
        assert re.search(rf"^\| `flowchart\.{f.name}[`.]", tokens, re.M) or \
            f"`.{f.name}.`" in tokens, f.name
    for name in (f.name for f in dataclasses.fields(WordsConfig) if f.name.startswith("flowchart")):
        assert f"`{name}`" in tokens, name


# --- AC-F27-23: the puzzle room in docs/minigames.md, its tokens in ui-system.md --------------

def _room_args(**change: object) -> dict:
    """The section's attic (Template R's, the hook moved) as arguments, with ``change`` keys
    ``"<hotspot>.<field>"`` replaced in a hotspot, ``"-<hotspot>"`` dropped, or a top-level
    ``room`` key or ``state`` replaced."""
    import copy

    from tests.fixtures.F27 import rooms
    room = rooms.room()
    room["hotspots"]["hook"]["rect"] = [300, 260, 64, 96]
    for side in ("string", "vent", "glint"):             # above the hint at 150% (W180)
        room["hotspots"][side]["rect"][1] = {"string": 470, "vent": 440, "glint": 460}[side]
    args = {"room": room, "state": None}
    for key, value in change.items():
        if key == "state":
            args["state"] = value
        elif key == "room":
            args["room"] = value
        elif key.startswith("-"):
            del room["hotspots"][key[1:]]
        elif "." in key:
            spot, field = key.split(".")
            room["hotspots"][spot][field] = value
        else:
            room[key] = value
    return copy.deepcopy(args)


def _f27_refusals() -> dict[str, list[dict]]:
    """R1–R14 → arguments whose first problem it is (the forms the section's table shows)."""
    base = _room_args()["room"]
    renamed = {**base, "hotspots": {"coat hook": base["hotspots"]["hook"], **base["hotspots"]}}
    many = {f"s{i}": {"rect": [0, 0, 32, 32], "label": "x", "exit": True} for i in range(45)}
    return {
        "R1": [_room_args(room={"background": base["background"], "hotspot": {}}),
               _room_args(room=[1])],
        "R2": [_room_args(background=3)],
        "R3": [_room_args(hotspots=many), _room_args(room=renamed)],
        "R4": [_room_args(**{"hook.takes": "rusty_key"})],
        "R5": [_room_args(**{"hook.rect": [300, 260]})],
        "R6": [_room_args(**{"window.look": "w" * 95}), _room_args(**{"hook.label": ""})],
        "R7": [_room_args(**{"drawer.take": "magnet"}), _room_args(**{"hook.look": "A hook."}),
               _room_args(**{"window.nope": "No."})],
        "R8": [_room_args(**{"drawer.use": 3})],
        "R9": [_room_args(**{"magnet.after": "drawr"}), _room_args(**{"magnet.after": "window"})],
        "R10": [_room_args(**{"hook.image": True})],
        "R11": [_room_args(**{"out.exit": "yes"}), _room_args(**{"-out": None})],
        "R12": [_room_args(combine={"magnet_string": "magnet"}),
                _room_args(combine={"magnet_string": ["magnet", "string"],
                                    "x": ["string", "magnet"]})],
        "R13": [_room_args(state=[]), _room_args(state={"gone": "hook"})],
        "R14": [_room_args(**{"hook.take": "rusty_kye"}), _room_args(**{"hook.take": "lanterns"})],
    }


def _room_reason(args: dict) -> str:
    from engine.minigames.bundled import room_rules
    from tests.fixtures.F27 import rooms

    found = room_rules.problem(args) or room_rules.story_problem(args, rooms.STORY)
    assert found is not None, args
    return found


def test_ac_f27_23_puzzle_room_docs(tmp_path):
    """``docs/minigames.md``'s "Puzzle room", not proposed: 01 §5.2's template (the hook out of
    the door), the ``state`` loop, ``lock item`` after a use, the arguments (with
    ``PuzzleRoom``'s defaults), R1–R14 as ``room_rules`` words them, each with a fix, E272's
    "these arguments" form, W179's limit and W180's widest hint, spent use spots returning
    without ``state``, spacing advice with Tab and RB, and the testing sentence ("first exit",
    ``finish``). Its story block loads with Template R's images and names in dev, launches,
    and plays headless with no error or warning to the hallway; its TOML blocks are tokens and
    the plugin's words. ``ui-system.md`` lists every ``plugin.puzzle_room`` token."""
    import ast
    import tomllib

    from engine.minigames.bundled.puzzle_room import TOKENS, PuzzleRoom
    from engine.runtime.commands import Say, StartMinigame
    from engine.runtime.headless import run_headless
    from engine.runtime.launch import run_launch
    from engine.script import load_story
    from engine.script.loader import LoadOptions
    from engine.script.messages import format_message
    from tests.runtime.menu_story import write_game
    from tests.runtime.stage_story import example_minigames

    text = MINIGAMES.read_text(encoding="utf-8")
    heading = re.search(r"^## Puzzle room\s*$", text, re.M)
    assert heading is not None
    following = re.search(r"^## ", text[heading.end():], re.M)
    section = text[heading.start():heading.end() + following.start() if following else None]
    assert "proposed" not in section
    flat = " ".join(section.split())
    for words in ("leaves by the first exit in room order", "give it with `finish`",
                  "Write `lock item` after a use", "**Pass `state` back.**",
                  "every spent `use` hotspot comes back",
                  "**an item your script gives the player later is invisible to it**",
                  "The check uses the widest hint the screen can show",
                  "**Leave room between hotspots.**", "Tab, Page Down, and the gamepad's RB",
                  "the later one in room order gets the click", "W179", "W180",
                  "`[theme.plugin.puzzle_room]`", "`[words.plugin.puzzle_room]`",
                  "Saving in a room saves its start"):
        assert words in flat, words
    for name, spec in PuzzleRoom.args.items():
        default = "none (you must give it)" if name == "room" else f"`{spec.default!r}`"
        assert re.search(rf"^\| `{name}` \| {re.escape(default)} \|", section, re.M), name
    for number, changes in _f27_refusals().items():
        rows = re.findall(rf"^\| {number} \| `([^|]+)` \| ([^|]+) \|$", section, re.M)
        assert [reason for reason, _ in rows] == [_room_reason(c) for c in changes], number
        assert all(len(fix.strip()) > 10 for _, fix in rows), number
    one = format_message("E272", ("plugin_all", "puzzle_room",
                                  _room_reason(_f27_refusals()["R4"][0])))
    assert f"`{one}`" in section and "`puzzle_room can't use these arguments:`" in section

    blocks = re.findall(r"^```([a-z]*)\n(.*?)^```", section, re.M | re.S)
    assert [lang for lang, _ in blocks] == ["", "toml", "toml"]
    theme = tomllib.loads(blocks[1][1])["theme"]["plugin"]["puzzle_room"]
    assert {f"{part}.{key}" for part, keys in theme.items() for key in keys} <= set(TOKENS)
    assert tomllib.loads(blocks[2][1])["words"]["plugin"]["puzzle_room"] == PuzzleRoom.words
    attic = re.search(r"^define attic = (\{.*?^    \})$", blocks[0][1], re.M | re.S)
    assert attic is not None
    assert {"room": ast.literal_eval(attic.group(1)), "state": None} == \
        _room_args()
    story = blocks[0][1] + "\nlabel start:\n    jump attic_room\n"
    sigs = example_minigames()
    result = load_story(write_game(tmp_path / "room", story),
                        LoadOptions(dev=True, minigames=sigs))
    assert result.errors == () and result.warnings == (), (result.errors, result.warnings)
    launch = run_launch(result.program, dev=True)
    assert launch.namespace is not None and launch.warnings == ()
    commands = run_headless(result.program, seed=1, dev=True, minigames=sigs)
    assert type(commands[-1]).__name__ == "StoryEnded", commands[-1]
    assert [c.name for c in commands if type(c) is StartMinigame] == ["puzzle_room"]
    assert "The hallway was even colder than the attic." in [
        c.text for c in commands if type(c) is Say]

    tokens = UI.read_text(encoding="utf-8")
    for token in TOKENS:
        assert re.search(rf"^\| `plugin\.puzzle_room\.{re.escape(token)}` \| ", tokens,
                         re.M), token


# --- AC-F23-61: the minigame line, the plugin guide, and the minigame tokens ------------------

F23_POINTS = (
    "**A plugin is a program.**", "**`ctx.args` can come from a save.**",
    "which has no side effects", "**Never build file paths or `eval` from arguments.**",
    "**Use `ctx.log`**", "**Keep the player's computer out of results, titles, and logs.**",
    "**Make no API calls from your own threads.**", "**Honour `reduce_motion`.**",
    "**Use relative imports in packages.**")


def test_ac_f23_61_minigame_docs(tmp_path):
    """``script-language.md``'s ``minigame`` section (not proposed) loads with SIGS, and the
    E272–E279 rows are there; ``docs/minigames.md``'s "Writing a minigame" shows the whole
    example plugin (``game/minigames/lantern_memory.py``, which AC-F23-62 loads with Loader L
    and plays in Host U by keyboard), states each SEC-F23-15 point, and its "Saves" has the
    save sentence; ``ui-system.md`` lists the ``minigame`` tokens, the ``plugin`` area, and
    the two words; F23's docs-table rows point at the heading."""
    from engine.script import load_story
    from engine.script.loader import LoadOptions
    from engine.script.statement_docs import all_docs
    from tests.fixtures.F23.sigs import SIGS
    from tests.runtime.menu_story import write_game

    text = LANGUAGE.read_text(encoding="utf-8")
    assert "proposed, F23" not in text
    section = _subsection(text, "minigame")
    code = _code_blocks(section)
    assert "minigame lantern_memory pairs=6 into turns" in code
    story = 'define hana = Character("Hana")\n' + code + "\nlabel start:\n    jump lantern_stall\n"
    result = load_story(write_game(tmp_path / "mg", story), LoadOptions(dev=True, minigames=SIGS))
    assert result.errors == () and result.warnings == (), (result.errors, result.warnings)
    for code_ in ("E272", "E273", "E274", "E275", "E276", "E277", "E278", "E279"):
        assert f"| {code_} |" in text or f"({code_})" in section, code_
    assert "| `minigame` | available |" in _section(text, "Reserved words")
    assert {d.docs for d in all_docs() if d.key == "minigame"} == {"minigame"}

    guide = MINIGAMES.read_text(encoding="utf-8")
    assert "proposed" not in guide
    writing = guide[guide.index("\n## Writing a minigame"):guide.index("\n## Plugin reference")]
    plugin = (REPO / "game" / "minigames" / "lantern_memory.py").read_text(encoding="utf-8")
    assert f"```python\n{plugin}```" in writing
    flat = " ".join(writing.split())
    for point in F23_POINTS:
        assert point in flat, point
    saves = " ".join(_subsection(guide, "Saves").split())
    assert "a save can restart any minigame with any arguments its plugin accepts" in saves

    ui = UI.read_text(encoding="utf-8")
    assert "proposed, F23" not in ui
    for token in ("minigame.fade_ms", "minigame.background_image", "minigame.stage_dim_opacity",
                  "minigame.hint.text_size"):
        assert re.search(rf"^\| `{re.escape(token)}` \| ", ui, re.M), token
    assert "`plugin`" in ui and "`skip_minigame`" in ui and "`confirm_skip_minigame`" in ui


# --- AC-F31-28: the "Meta files" section ----------------------------------------------------

# Each F31 code -> the format_message arguments of the forms the section quotes in full.
F31_MESSAGES: dict[str, list[tuple]] = {
    "E309": [(), ("unknown", "delte", "delete"), ("left", "delete", "now"), ("block",)],
    "E310": [(), ("capitals", "Hana.chr"), ("variable", "name")],
    "E311": [()],
    "E312": [(), ("no_default", "hana_her", "hana_here"), ("define", "hana"),
             ("one_name", "exists", "persistent.hana")],
    "E313": [(), ("large", "hana.chr")],
    "E314": [()],
    "E315": [()],
    "W196": [()],
    "W197": [()],
    "W198": [(), ("full", "write", "read_me.txt"), ("other", "write", "read_me.txt")],
    "W199": [()],
    "W200": [(), ("utf8", "answer.txt")],
}
F31_POINTS = (
    "is replaced or deleted", "content warning", "run programs, change system settings, or "
    "move files outside the game folder", "can reach any file", "`files/` goes with it and "
    "your own `characters/` folder never does", "blocks rollback by itself",
    "A new game puts the files back", "read-only folder", "another program may be using it",
    "reach the disk only after you start the game again")


def test_ac_f31_28_meta_files_docs(tmp_path):
    """``script-language.md``'s "Meta files" (not proposed): the four forms, the folder and
    name rules, once-only and the rollback block, read-only installs, the new-game pattern,
    SEC-F31-09's five points, hot reload and W198's lock form; E309-E315 and W196-W200 rows
    as ``messages.py`` words them; each code block loads in a copy of the doc game (its
    ``files/`` holds the originals) and launches with no error or warning. Rollback's table
    has the meta files row; ``file`` is available in Reserved words; the four help rows
    point at the heading."""
    import shutil

    from engine.core.paths import GamePaths
    from engine.runtime.launch import run_launch
    from engine.script import load_story
    from engine.script.messages import format_message
    from engine.script.statement_docs import all_docs

    text = LANGUAGE.read_text(encoding="utf-8")
    assert "proposed, F31" not in text
    section = _section(text, "Meta files")
    assert "proposed" not in section
    flat = " ".join(section.split())
    for verb in ("write", "delete", "exists", "read"):
        assert f"`file {verb} " in flat, verb
    for words in ("file write", "content warning", "characters/", "lowercase letters",
                  "`.chr` or `.txt`", "at most 32 names", *F31_POINTS):
        assert words in flat, words
    assert re.findall(r"^\| ([EW]\d+) \|", section, re.M) == list(F31_MESSAGES)
    for code, forms in F31_MESSAGES.items():
        row = re.search(rf"^\| {code} \|.*$", section, re.M).group(0)
        for args in forms:
            assert f"`{format_message(code, args)}`" in row, (code, args)

    blocks = re.findall(r"^```[a-z]*\n(.*?)^```", section, re.M | re.S)
    assert blocks and "file read" in blocks[0]
    docgame = REPO / "tests" / "fixtures" / "docgame"
    for number, body in enumerate(blocks):
        game = tmp_path / f"game{number}"
        shutil.copytree(docgame, game)
        assert (game / "files" / "hana.chr").is_file()
        story = 'define hana = Character("Hana")\n' + body
        if "label start:" not in body:
            story += "\nlabel start:\n    return\n"
        (game / "script" / "main.vns").write_bytes(story.encode("utf-8"))
        (game / "script" / "chapter2.vns").unlink()              # included only by main.vns
        result = load_story(GamePaths.for_game(game))
        assert result.errors == () and result.warnings == (), (body, result.errors,
                                                               result.warnings)
        launch = run_launch(result.program)
        assert launch.namespace is not None and launch.warnings == (), body

    rollback = " ".join(_subsection(text, "What is and isn't rolled back").split())
    assert ("| | Meta files: `file write` and `file delete` never run twice; each one blocks "
            "rollback |") in rollback
    assert "| `file` | available |" in _section(text, "Reserved words")
    assert {d.docs for d in all_docs() if d.key == "file"} == {"Meta files"}
    guide = (REPO / "docs" / "meta-files.md").read_text(encoding="utf-8")
    assert "script-language.md#23-meta-files" in guide and "W198" in guide


# --- AC-F28-28: "Glitch effects" and the UI system's glitch rows -------------------------------

# Each F28 code → the forms the reference shows (``format_message`` arguments), in order.
F28_MESSAGES: dict[str, list[tuple]] = {
    "E294": [(), ("kind", "wobble", None), ("hint", "corrupt"), ("empty",), ("tag",),
             ("notag", "static", "hana"), ("length", "tear", "45"), ("units", "0.5", "0.5s"),
             ("dot", ".5"), ("twice", "tear", "sizes"), ("both", "static"),
             ("onoff", "static"), ("off_args", "tear"), ("left", "slowly", "tear"),
             ("left", "now", None)],
    "W182": [(), ("transition",)],
    "W183": [()],
    "W184": [(), ("daichi", ())],
}


def test_ac_f28_28_glitch_effects_docs(tmp_path):
    """``script-language.md``'s "Glitch effects" (not proposed) covers SR-F28-01..06, the
    sizes, bursts against ``on``/``off``, ``with glitch``, F29's ``{glitch}`` tag, the flash
    limit and ``reduce``, the meaning and Mask advice; E294 and W182-W184 rows as
    ``messages.py`` words them; each story block loads and launches in a copy of the doc game
    with no error or warning. Reserved words lists ``effect`` and its glitch words; the two
    Help entries point at the heading. ``ui-system.md``: layer 2's glitches, the timing rows,
    and the reduced-motion rows."""
    import shutil

    from engine.core.paths import GamePaths
    from engine.runtime.launch import run_launch
    from engine.script import load_story
    from engine.script.glitch import DOCS, HEADING
    from engine.script.messages import format_message

    text = LANGUAGE.read_text(encoding="utf-8")
    section = _section(text, "Glitch effects")
    assert "proposed" not in section
    flat = " ".join(section.split())
    for words in ("{glitch}…{/glitch}", "flash", "reduce", "`effect off` on its own",
                  "only `jitter` takes one", "in any order and each at most once",
                  "`small`, `medium` (the default), or `large`", "starts with whatever is shown",
                  "16 / 40 / 96", "2 / 6 / 12", "15% / 30% / 50%", "4 / 10 / 24",
                  "**burst**", "**lasts**", "`define glitch = …` is an error (E198)",
                  "`default static = 0` still works", "a line or a sound that carries its meaning",
                  "Don't stack `static` with a `Mask` transition", "Reduce motion and flashing",
                  "3 flashes a second", "glitch = 0.5", 'glitch_size = "medium"'):
        assert words in flat, words
    assert re.findall(r"^\| ([EW]\d+) \|", section, re.M) == list(F28_MESSAGES)
    for code, forms in F28_MESSAGES.items():
        row = re.search(rf"^\| {code} \|.*$", section, re.M).group(0)
        for args in forms:
            assert f"`{format_message(code, args)}`" in row, (code, args)

    blocks = re.findall(r"^```\n(.*?)^```", section, re.M | re.S)       # the story blocks
    assert len(blocks) == 2 and "effect jitter hana large on" in blocks[0]
    docgame = REPO / "tests" / "fixtures" / "docgame"
    for number, body in enumerate(blocks):
        game = tmp_path / f"game{number}"
        shutil.copytree(docgame, game)
        story = 'define hana = Character("Hana")\n'
        story += body if "label start:" in body else "label start:\n" + body
        (game / "script" / "main.vns").write_bytes(story.encode("utf-8"))
        (game / "script" / "chapter2.vns").unlink()              # included only by main.vns
        result = load_story(GamePaths.for_game(game))
        assert result.errors == () and result.warnings == (), (body, result.errors,
                                                               result.warnings)
        launch = run_launch(result.program)
        assert launch.namespace is not None and launch.warnings == (), body

    words = _section(text, "Reserved words")
    assert "| `effect` | available |" in words
    assert all(f"`{kind}`" in words for kind in ("tear", "colorshift", "static", "jitter"))
    assert "#24-glitch-effects" in _section(text, "Transitions and effects")
    assert "at the end of Glitch effects" in _section(text, "Common errors")
    assert f"### {HEADING}" in text and {doc.docs for doc in DOCS} == {HEADING}

    ui = UI.read_text(encoding="utf-8")
    layer = next(line for line in ui.splitlines() if line.startswith("| 2 | Stage effects |"))
    assert "F28 (reserved)" not in layer and "**Glitches** (F28)" in layer
    timings = _section(ui, "Standard timings")
    for name in ("`tear`", "`colorshift`", "`static`", "`jitter`", "Glitch burst",
                 "`with glitch`", "Reduced `static`", "Reduced `colorshift`"):
        assert re.search(rf"^\| {re.escape(name)} \(F28\) \|", timings, re.M), name
    reduced = " ".join(timings[timings.index("### Reduced motion and flashing"):].split())
    for words in ("**Glitch effects (F28).**", "red never flashes", "W182",
                  "tear and jitter draw nothing", "one still noise frame",
                  "`with glitch` plays as a dissolve"):
        assert words in reduced, words


# --- AC-F29-19, AC-F29-20: "Text effects" and the example game's effect lines -----------------

# Each F29 code → the forms the reference quotes in full (``format_message`` arguments).
F29_MESSAGES: dict[str, list[tuple]] = {
    "E160": [("list", "blink"), ("missing", "font"), ("hint", "jitter", "shake"),
             ("hint", "wavy", "wave"), ("hint", "zalgo", "glitch")],
    "E164": [("effect", "shake", "2"), ("effect", "wave", "")],
    "E297": [()],
    "W185": [(), (64, "large")],
    "E175": [("shake",)],
}


def test_ac_f29_19_text_effects_docs(tmp_path):
    """``script-language.md``'s "Text effects" part of Dialogue text (not proposed): design
    §5.4's points (the three tags and strengths, one effect at a time, History, the
    crawl-then-slam recipe, Reduce motion, offsets not clipped, fonts without the symbols);
    the tag table lists the three; the E160, E164, E297, W185 (and E175) forms as
    ``messages.py`` words them, with F05's stale E160 forms gone; each code block loads and
    launches in a copy of the doc game with no error or warning. The three tags' Help rows
    link to the part."""
    import shutil

    from engine.core.paths import GamePaths
    from engine.runtime.launch import run_launch
    from engine.script import load_story
    from engine.script.messages import format_message
    from engine.script.tag_docs import TEXT_EFFECTS_HEADING, tag_doc

    text = LANGUAGE.read_text(encoding="utf-8")
    assert "proposed, F29" not in text
    chapter = _section(text, "Dialogue text")
    part = _subsection(chapter, TEXT_EFFECTS_HEADING)
    assert "proposed" not in part
    flat = " ".join(part.split())
    for words in ("one effect at a time", "History", "Reduce motion", "`small`, `medium` (the "
                  "default), or `large`", "{speed=0.2}", "{speed=instant}", "{pause=0.8}",
                  "don't let an effect carry the story on its own", "Nothing is clipped",
                  "missing-letter box", "{glitch=small}"):
        assert words in flat, words
    for tag in ("shake", "wave", "glitch"):
        assert re.search(rf"^\| `\{{{tag}\}}…\{{/{tag}\}}` \|", _subsection(chapter, "Text tags"),
                         re.M), tag
        assert tag_doc(tag).docs == TEXT_EFFECTS_HEADING
    for code, forms in F29_MESSAGES.items():
        for args in forms:
            assert f"`{format_message(code, args)}`" in text, (code, args)
    for stale in F29_SUPERSEDED:
        assert stale not in text, stale

    blocks = re.findall(r"^```\n(.*?)^```", part, re.M | re.S)
    assert len(blocks) == 2 and "{glitch=large}" in blocks[0]
    docgame = REPO / "tests" / "fixtures" / "docgame"
    for number, body in enumerate(blocks):
        game = tmp_path / f"game{number}"
        shutil.copytree(docgame, game)
        story = 'define hana = Character("Hana")\n'
        story += body if "label start:" in body else "label start:\n" + body
        (game / "script" / "main.vns").write_bytes(story.encode("utf-8"))
        (game / "script" / "chapter2.vns").unlink()              # included only by main.vns
        result = load_story(GamePaths.for_game(game))
        assert result.errors == () and result.warnings == (), (body, result.errors,
                                                               result.warnings)
        launch = run_launch(result.program)
        assert launch.namespace is not None and launch.warnings == (), body


def test_ac_f29_20_the_example_game_uses_each_text_effect(tmp_path, caplog):
    """``game/`` has one line with each of ``{shake}``, ``{wave}``, ``{glitch}``, under a
    comment with the reduce-motion advice; its dev load has no warning (no W185); Run R
    (seeds 1–5, AC-F05-47's walkthroughs) shows each effect in every run. The ``--dev``
    launch with no WARNING is AC-F05-47's (``tests/app/test_text_check.py``)."""
    import logging
    import shutil

    from engine.core.paths import GamePaths
    from engine.runtime.commands import Say, StoryEnded
    from engine.runtime.headless import run_headless
    from engine.script import LoadOptions, load_story
    from engine.script.texttags import Span
    from tests.runtime.corpus import EXAMPLE_PICKS, example_minigames, play
    from tests.runtime.stage_story import position_names

    uses: dict[str, list[tuple[str, int]]] = {"shake": [], "wave": [], "glitch": []}
    for ref, number, lines in _example_lines():
        line = lines[number - 1]
        if line.strip().startswith("#"):
            continue
        for tag in uses:
            if re.search(rf"\{{{tag}(=\w+)?\}}", line):
                uses[tag].append((ref, number))
    assert all(len(found) == 1 for found in uses.values()), uses
    advice = False
    for tag, [(ref, number)] in uses.items():
        lines = (EXAMPLE / ref).read_text(encoding="utf-8").splitlines()
        assert lines[number - 2].lstrip().startswith("#"), (tag, ref, number)
        k = number - 2
        while k >= 0 and lines[k].lstrip().startswith("#"):
            advice = advice or "Reduce" in lines[k] or "motion" in lines[k]
            k -= 1
    assert advice

    root = tmp_path / "game"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("logs", "characters"))
    result = load_story(GamePaths.for_game(root), LoadOptions(
        position_names=position_names(root), minigames=example_minigames()))  # dev load
    assert result.errors == () and result.warnings == (), (result.errors, result.warnings)
    program = result.program
    images = tuple(sorted(p.relative_to(root).as_posix()
                          for p in (root / "images").rglob("*") if p.is_file()))
    with caplog.at_level(logging.DEBUG):
        for seed in range(1, 6):
            inputs = play(program, seed, images, EXAMPLE_PICKS[seed]).inputs
            commands = run_headless(program, seed=seed, image_files=images, dev=True,
                                    inputs=inputs, minigames=example_minigames())
            assert commands[-1] == StoryEnded(), seed
            shown = {p.style.effect.kind for c in commands if type(c) is Say
                     for p in c.body.pieces if type(p) is Span and p.style.effect is not None}
            assert shown == set(uses), (seed, shown)
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


# --- AC-F30-38: "Fourth-wall tricks", the Saves rule, and the UI system's crash note --------

# Each F30 code → the forms the reference quotes (``format_message`` arguments), in order.
F30_MESSAGES: dict[str, list[tuple]] = {
    "E300": [(), ("long", 140), ("tags",), ("left", "slowly")],
    "E301": [(), ("long", 2400), ("tag", "b")],
    "E302": [(), ("title_card",)],
    "W188": [()],
    "W189": [(), ("W189s",)],
    "W190": [(), ("W190s",)],
}


def test_ac_f30_38_fourth_wall_tricks_docs(tmp_path):
    """``script-language.md``'s "Fourth-wall tricks" (not proposed) covers SR-F30-01..05
    (the title, the crash and its message rules, ``{username}`` and where it may go, the
    fallback variable form); the title is saved and the name never is; the content-warning
    advice; the hint must say how to continue; no OS stop screens or phone numbers. It and
    "Saves" give SEC-F30-12's rule for ``$`` code. E300-E302, W188, W189 (and W190) rows
    quote ``messages.py``; each story block loads and launches in a copy of the doc game
    with no error or warning. ``ui-system.md`` has the fake crash under "Screens above"."""
    import shutil

    from engine.core.paths import GamePaths
    from engine.runtime.launch import run_launch
    from engine.script import load_story
    from engine.script.fourthwall import HEADING
    from engine.script.messages import format_message

    text = LANGUAGE.read_text(encoding="utf-8")
    section = _section(text, HEADING)
    assert "proposed" not in section
    flat = " ".join(section.split())
    for words in ("{username}", "content warning", "getpass", "effect crash",
                  "`effect window_title off`", "at most 100 characters", "`\\n` for a new line",
                  "only `{username}`, `{var=…}`, and `{{`", "**The title is part of the story.**",
                  "**The name is never saved.**", "History, saves", "Save pictures leave out",
                  "**The hint must tell players how to continue.**",
                  "**Don't imitate the computer's own stop screens**", "phone number",
                  "`{username=player_name}`", "Not in** a choice (E175)",
                  "content warning, then the name question, then the title",
                  "for its first half second (0.5 s)", "**Reset settings** turns it off, and "
                  "the question comes back at the next launch", "Label fake error screens",
                  "goes into saves, history, and persistent data",
                  "username = true", 'username_fallback = "friend"'):
        assert words in flat, words
    for code, forms in F30_MESSAGES.items():
        row = re.search(rf"^\| {code} \|.*$", section, re.M).group(0)
        for args in forms:
            shown = (format_message(args[0]) if args and args[0].startswith(("W189s", "W190s"))
                     else format_message(code, args))
            assert f"`{shown}`" in row, (code, args)

    blocks = re.findall(r"^```\n(.*?)^```", section, re.M | re.S)
    assert len(blocks) == 1 and "{username}" in blocks[0] and "effect crash" in blocks[0]
    game = tmp_path / "game"
    shutil.copytree(REPO / "tests" / "fixtures" / "docgame", game)
    story = 'define hana = Character("Hana")\n' + blocks[0]
    (game / "script" / "main.vns").write_bytes(story.encode("utf-8"))
    (game / "script" / "chapter2.vns").unlink()                  # included only by main.vns
    result = load_story(GamePaths.for_game(game))
    assert result.errors == () and result.warnings == (), (result.errors, result.warnings)
    launch = run_launch(result.program)
    assert launch.namespace is not None and launch.warnings == ()

    saves = " ".join(_section(text, "Saves").split())
    for words in ("`$` code can read the player's identity", "getpass",
                  "puts it into saves, history, and persistent data", "Use `{username}` instead"):
        assert words in saves, words
    assert "#25-fourth-wall-tricks" in _section(text, "Statements")
    assert "`{username}`" in _subsection(_section(text, "Dialogue text"), "Text tags")
    warning = " ".join(_subsection(text, "Content warning").split())
    assert "fourth-wall tricks" in warning and "the name question comes right after" in warning

    ui = " ".join(_section(UI.read_text(encoding="utf-8"), "Layers (z-order)").split())
    assert "The **fake crash screen** (F30, `effect crash`)" in ui

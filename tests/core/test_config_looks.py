"""F32 step 1: ``[style.<name>]`` and ``[playthrough.N]``, the two words, and their config
Help descriptions (F32 ``06-acceptance.md`` AC-F32-01, 02; ``04`` §6.1, §10).

Template U's ``config.toml`` is ``tests/fixtures/F32/template/config.toml``.
"""

from pathlib import Path

import pytest

from engine.core.config_schema import (LOOK_SECTIONS, SECTION_DOCS, WORD_DOCS, Config,
                                       LookTable, PlaythroughTableKeys, config_fields, key_doc)
from engine.core.constants import STATEMENT_WORDS
from engine.tools.editor.config_help import config_help, section_paths
from tests.fakes.username import no_real_username  # noqa: F401

TEMPLATE_U = (Path(__file__).parents[1] / "fixtures" / "F32" / "template"
              / "config.toml").read_text(encoding="utf-8")
NAME = ("isn't a usable style name. Use lower-case letters, digits, and _, starting with a "
        "letter, up to 32 characters, and not off.")
STYLE_AREA = ("isn't something a style can change. A style can change textbox, choice, nvl, "
              "and quick_menu.")
PLAY_AREA = ("isn't something a playthrough look can change. It can change title; use a style "
             "for the rest.")
REFUSED = "can't be changed by a style."
L1, L2 = "config.toml, line 1: ", "config.toml, line 2: "

# (edit, errors, warnings); every row is a whole config.toml.
ROWS = {
    **{f"name-{name[:8]}": (f"[style.{name}]\n", [f"{L1}[style.{name}] {NAME}"], [])
       for name in ("Ashes", "off", "ui", "menu", "a" * 33)},
    **{f"n-{n}": (f"[playthrough.{n}]\n",
                  [f"{L1}[playthrough.{n}] must be a whole number from 0 to 99."], [])
       for n in ("two", "100", "01", "-1")},
    "n-0-99": ("[playthrough.0]\n[playthrough.99]\n", [], []),
    "33-styles": ("".join(f"[style.s{i}]\n" for i in range(33)),
                  [f"{L1}there are 33 [style] tables, but at most 32 are allowed."], []),
    "17-tables": ("".join(f"[playthrough.{i}]\n" for i in range(17)),
                  [f"{L1}there are 17 [playthrough] tables, but at most 16 are allowed."], []),
    "area-panel": ('[style.ashes.theme.panel]\nfill_color = "#000000"\n',
                   [f"{L1}[style.ashes.theme.panel] {STYLE_AREA}"], []),
    "area-title": ('[style.ashes.theme.title]\nfill_color = "#000000"\n',
                   [f"{L1}[style.ashes.theme.title] {STYLE_AREA}"], []),
    "area-play": ('[playthrough.2.theme.textbox]\nfill_color = "#000000"\n',
                  [f"{L1}[playthrough.2.theme.textbox] {PLAY_AREA}"], []),
    **{f"word-{key}": (f'[style.ashes.words]\n{key} = "x"\n',
                       [f"{L2}[style.ashes.words] {key} {REFUSED} " + (
                           "Minigame words come only from [words.plugin]." if key == "plugin"
                           else "Fake-crash and user-name words come only from [words].")], [])
       for key in ("fake_crash_hint", "settings_username", "ask_username", "plugin")},
    "value": ('[style.ashes.theme.textbox]\nfill_color = "red"\n',
              [L2 + '[style.ashes.theme.textbox] fill_color must be a color "#RRGGBB", but '
               'found the text "red"'], []),
    "unknown": ('[style.ashes.theme.textbox]\nfill_colr = "#000000"\n[style.ashes]\n'
                'title_entries = ["quit"]\n[style.ashes.words]\nsav = "x"\n', [],
                [L2 + 'unknown key [style.ashes.theme.textbox] fill_colr — did you mean '
                 '"fill_color"?', "config.toml, line 4: unknown key [style.ashes] title_entries",
                 'config.toml, line 6: unknown key [style.ashes.words] sav — did you mean '
                 '"save"?']),
    "words": (f'[words]\nsaving_off = ""\nloading_off = "{"a" * 201}"\n',
              ["config.toml, line 3: [words] loading_off must be text of at most 200 "
               'characters, but found the text "' + "a" * 39 + '…"'], []),
}


@pytest.mark.parametrize("row", ["template-u", *ROWS])
def test_ac_f32_01_style_and_playthrough_tables(load, row):
    if row == "template-u":
        result = load(TEMPLATE_U)
        assert result.errors == [] and result.warnings == []
        style, play = result.config.style, result.config.playthrough
        assert list(style) == ["ashes", "calm"] and list(play) == [2]
        assert dict(style["calm"].tokens) == {"textbox.frame_image": "gui/frame_calm.png",
                                              "choice.fill_color": (0x33, 0x44, 0x55)}
        assert dict(style["ashes"].words) == {"save": "Keep", "saving_off": "Not now."}
        assert play[2] == LookTable(
            {"title.background_image": "gui/title_ashes.png", "title.music": "title_quiet.ogg"},
            {"new_game": "Again?", "history": "Before", "menu": "Pause"},
            ("new_game", "settings", "quit"), 7)
        with pytest.raises(TypeError):
            style["ashes"].tokens["textbox.fill_color"] = (0, 0, 0)     # read-only
        with pytest.raises(TypeError):
            play[3] = play[2]
        assert Config().style == {} and Config().playthrough == {}
        return
    if row == "name-ui" and "ui" not in STATEMENT_WORDS:
        pytest.skip("F32 step 2 reserves ui")
    text, errors, warnings = ROWS[row]
    result = load(text)
    assert [error.format() for error in result.errors] == errors
    assert result.warnings == warnings
    if row == "n-0-99":
        assert list(result.config.playthrough) == [0, 99]
    if row == "unknown":                                    # not read
        ashes = result.config.style["ashes"]
        assert (dict(ashes.tokens), dict(ashes.words), ashes.title_entries) == ({}, {}, None)
    if row == "words":                       # "" loads (F10's W65 at install keeps the default)
        assert result.config.words.saving_off == ""
        assert result.config.words.loading_off == "Loading is turned off here."
        assert Config().words.saving_off == "Saving is turned off here."


def test_ac_f32_02_config_docs_for_help(load):
    assert SECTION_DOCS["style"] and SECTION_DOCS["playthrough"]
    assert WORD_DOCS["saving_off"] and WORD_DOCS["loading_off"]
    assert config_fields(PlaythroughTableKeys)["title_entries"].metadata["doc"]
    for look, base in [("style.ashes.theme.textbox", "theme.textbox"),
                       ("playthrough.2.theme.title", "theme.title"),
                       ("style.ashes.words", "words")]:
        key = {"theme.textbox": "fill_color", "theme.title": "music", "words": "save"}[base]
        assert key_doc(look, key) == key_doc(base, key) != ""
    # Every key of Template U's config, look tables included, has a description.
    result = load(TEMPLATE_U)
    assert result.errors == []
    paths = [("game", "id"), ("theme.textbox", "fill_color"), ("playthrough.2", "title_entries"),
             ("playthrough.2.theme.title", "background_image"),
             ("playthrough.2.theme.title", "music"), ("playthrough.2.words", "new_game"),
             ("playthrough.2.words", "history"), ("playthrough.2.words", "menu"),
             ("style.ashes.theme.textbox", "text_size"), ("style.ashes.words", "saving_off"),
             ("style.calm.theme.textbox", "frame_image"), ("style.calm.theme.choice",
                                                           "fill_color")]
    assert [p for p in paths if not key_doc(*p)] == []
    sections = ["style", "playthrough", "style.ashes", "playthrough.2", "style.ashes.theme",
                "style.ashes.theme.textbox", "playthrough.2.words"]
    assert [s for s in sections if not key_doc(s, "")] == []
    assert all(key_doc(f"{name}.x", key) for name, cls in LOOK_SECTIONS.items()
               for key in config_fields(cls))
    # Studio's config Help reads the same rows inside a look table.
    assert {"style", "playthrough"} <= set(section_paths())
    assert config_help('fill_color = "#000000"', "style.ashes.theme.textbox").summary == \
        key_doc("theme.textbox", "fill_color")
    assert config_help("[playthrough.2]", None).summary == SECTION_DOCS["playthrough"]

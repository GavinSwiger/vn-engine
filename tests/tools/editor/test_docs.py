"""AC-F44-37 (amended, F45) and AC-F45-48: the Studio docs page, ``docs/scene-editor.md``
(PR-F44-20, PR-F45-24, F45 ``04`` §8.5, ``07`` I-1, I-8, I-10). The review step (a first-time
author can open Studio and preview a scene from the page alone) is the reviewer's."""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PAGE = REPO / "docs" / "scene-editor.md"
LANGUAGE = REPO / "docs" / "script-language.md"
SCRIPT = REPO / "game" / "script"

MAX_WORDS = 1_000                       # F45 07 I-10 (was 400, PR-F44-20)
RTL_SENTENCE = ("The editor shows right-to-left text in typing order. Check how it looks in "
                "the preview.")         # 03 §7, word for word
RUN_LINE = re.compile(r"^python -m engine run game --start (\w+)((?: --set \"[^\"]+\")+)$", re.M)


def _text() -> str:
    return PAGE.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """The page with line breaks inside paragraphs joined, for sentence checks."""
    return re.sub(r"\s+", " ", text)


def _game_names(keyword: str) -> set[str]:
    pattern = re.compile(rf"^{keyword} (\w+)", re.M)
    return {match.group(1)
            for path in SCRIPT.rglob("*.vns")
            for match in pattern.finditer(path.read_text(encoding="utf-8"))}


def test_ac_f44_37_page_is_short():
    assert len(_text().split()) <= MAX_WORDS


def test_ac_f44_37_page_covers_the_editor():
    flat = _flat(_text())
    for needed in ("python -m engine edit", "F5", "**▶ Play**", "Shift+F5", "**Start values**",
                   "**▶ Play this scene**", "**■ Stop**", "**Play options…**",
                   "**Play as a new player**",
                   "**Problems**", RTL_SENTENCE, "E26b", "E26c"):
        assert needed in flat, needed


def test_ac_f44_37_page_covers_the_documented_limits():
    flat = _flat(_text())
    assert re.search(r"only reached by `call` ends the preview at its `return`", flat)
    assert re.search(r"A default that uses another default, .* uses the original", flat)
    assert "Previews are normal dev runs" in flat
    assert re.search(r"On macOS, F5 and F6 may need Fn", flat)


def test_ac_f44_37_run_example_uses_the_example_game():
    match = RUN_LINE.search(_text())
    assert match is not None
    label, sets = match.group(1), match.group(2)
    assert label in _game_names("label")
    pairs = re.findall(r'--set "(\w+)=([^"]+)"', sets)
    assert pairs
    defaults = _game_names("default")
    assert [name for name, _ in pairs if name not in defaults] == []
    assert any(re.fullmatch(r"'[^']*'", value) for _, value in pairs)   # the quoting form


def test_ac_f44_37_start_values_example_uses_the_example_game():
    block = re.search(r"\*\*Start values\*\* box.*?^```\n(.*?)^```", _text(), re.M | re.S)
    assert block is not None
    names = re.findall(r"^(\w+) = ", block.group(1), re.M)
    assert names
    assert set(names) <= _game_names("default")


def test_ac_f44_37_page_is_linked_from_the_language_reference():
    assert "(scene-editor.md)" in LANGUAGE.read_text(encoding="utf-8")


# --- F45: the Studio page (AC-F45-48) -------------------------------------------------------

# AC-F45-46's keys, each named in the page's key list.
STUDIO_KEYS = ("Ctrl+O", "Ctrl+N", "Ctrl+Shift+O", "F2", "Delete", "Ctrl+S", "Ctrl+Shift+S",
               "Ctrl+Space", "Ctrl+G", "Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "F5", "Shift+F5", "Ctrl+F2", "F7",
               "F6", "Shift+F6", "Ctrl+=", "Ctrl+-", "Ctrl+0")


def _section(heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", _text(), re.M | re.S)
    assert match is not None, heading
    return _flat(match.group(1))


def test_ac_f45_48_page_covers_studio():
    flat = _flat(_text())
    for needed in ("Add files…", "**Keep both**", "**Replace**", "**Skip**",
                   "New script file", "**Rename**", "New game…", "F7 (**Check now**)",
                   "**Problems**", "`E`", "`W`", "Show warnings", "Ctrl+Space", "**Insert**",
                   "**Help**", "**Story map**", "(Ctrl+2)", "Ctrl+= and Ctrl+-", "out of date",
                   "Find scene", "(Ctrl+G)", "Delete** is permanent", "screen-reader"):
        assert needed in flat, needed


def test_ac_f45_48_page_states_the_trust_rules():
    from engine.tools.editor import files

    flat = _flat(_text())
    assert files.TRUST in flat                                  # the minigame trust line
    # 04 §8.5 as decided by 07 I-1: opening runs no game code; the first act does.
    assert re.search(r"Until your first Preview, Save, or Check now in a window, checks only "
                     r"read your files", flat)
    assert re.search(r"After that, checks also run your `define` and `default` lines", flat)


def test_ac_f45_48_page_names_the_preview_only_checks():
    """07 I-8: the app-only checks (text, W111, minigame loading) are "shown on Preview"."""
    flat = _flat(_text())
    match = re.search(r"shown on Preview only: ([^.]*)\.", flat)
    assert match is not None
    for needed in ("text warnings", "W111", "minigames"):
        assert needed in match.group(1), needed


def test_ac_f45_48_page_matches_the_built_texts():
    from engine.core.editorreport import CHECK_DEBOUNCE_MS
    from engine.tools.editor import storymap

    flat = _flat(_text())
    assert f"{CHECK_DEBOUNCE_MS / 1000:g} seconds after you stop typing" in flat
    for mark in (storymap.MARK_START, storymap.MARK_NOT_REACHED, storymap.MARK_ENDS):
        assert f"`{mark}`" in flat, mark


def test_ac_f45_48_page_names_the_window_texts():
    """The menu, button and tab names the page uses are the window's own (no window is
    built: only the module's texts and its menu code are read)."""
    import inspect

    pytest.importorskip("tkinter")
    window = pytest.importorskip("engine.tools.editor.window")
    flat = _flat(_text())
    for name in (window.ADD_BUTTON, *window.CLASH_BUTTONS, window.SHOW_WARNINGS,
                 window.TAB_EDITOR, window.TAB_MAP, window.TAB_ASSET,
                 window.START_VALUES_HEADING, window.PROBLEMS_HEADING):
        assert name in flat, name
    menus = inspect.getsource(window.EditorWindow.menu_table)     # studiomenus' table
    for name in ("New game…", "New script file", "Rename", "Delete", "Check now"):
        assert f'Item("{name}' in menus and name in flat, name
    assert "FIND_SCENE_MENU" in menus and "Find scene" in flat


def test_ac_f45_48_key_list_holds_every_studio_key():
    keys = _section("Keys")
    for key in STUDIO_KEYS:
        assert re.search(rf"(?<![\w+]){re.escape(key)}(?![\w=+-])", keys), key


def test_ac_f45_48_page_tells_builders_about_register_doc():
    flat = _flat(_text())
    assert "register_doc(StatementDoc(" in flat
    test = re.search(r"`(tests/[\w/]+\.py)`", flat)
    assert test is not None and (REPO / test.group(1)).is_file()


# --- AC-F46-44: the story map page -----------------------------------------------------------

STORY_PAGE = REPO / "docs" / "story-map.md"


def test_ac_f46_44_the_story_map_page():
    from engine.tools.editor import forms, scriptedit

    flat = _flat(STORY_PAGE.read_text(encoding="utf-8"))
    assert "(story-map.md)" in _text()                      # scene-editor.md links to it
    for needed in ("drag", "Alt+arrows", "Ctrl+J", "**Make a choice**", "F2",
                   "double-click empty space", "Ctrl+Shift+N", "**Events**", "Ctrl+E",
                   "**Insert…**", "**Script** row", f"`{forms.NOTHING}`", "Alt+Up",
                   "Alt+Down", "Ctrl+Z on the map", "Undo blocked", "**Rename scene:**",
                   "Python code that names the scene", scriptedit.RENAME_SAVES,
                   "`.studio/storymap.json`", "The game never reads it",
                   "version control is your choice", "screen-reader", "**Change target…:**",
                   "**Delete scene:**", "**New file…**", "**Play from this scene:**"):
        assert needed in flat, needed
    assert "proposed" not in flat

"""``ui/menus.py``: the entry registry and ``UiOverrides`` (F10 ``04`` §5.4, §7.11; ``07``
"The entry registry and overrides"). AC-F10-47's unit rows, and W66's drafted texts (G1, G7).

The title-screen row of AC-F10-47 (art and music changing while the title shows) and "every
override leaves ``checkpoint()`` unchanged" run in ``tests/ui/test_title.py`` and
``tests/app/test_ui_flow.py``. No display: the registry is pure Python.
"""

import pytest

from engine.ui.menus import DEFAULT_ORDER, KEEP, MenuEntry, MenuRegistry, UiOverrides, join_names
from engine.ui.shell import w66_empty_text, w66_text


def ids(entries) -> list[str]:
    return [e.id for e in entries]


def test_default_order_table():
    assert DEFAULT_ORDER["title"] == ("new_game", "load", "flowchart", "settings", "extras",
                                      "codex", "help", "quit")            # F21 s3, F20 s8
    assert DEFAULT_ORDER["game"] == ("return", "skip_minigame", "history", "codex",
                                     "flowchart", "save", "load", "settings", "help",
                                     "main_menu", "quit")                 # F23, F20 s8
    assert DEFAULT_ORDER["quick"][-2:] == ("hide", "menu")


# --- AC-F10-47 ----------------------------------------------------------------------------

def test_shown_follows_the_default_order_not_the_registration_order():
    registry = MenuRegistry()
    for entry_id in ("quit", "save", "return", "main_menu"):
        registry.add("game", MenuEntry(entry_id))
    assert ids(registry.shown("game")) == ["return", "save", "main_menu", "quit"]


def test_invisible_and_hidden_entries_are_omitted():
    overrides = UiOverrides()
    registry = MenuRegistry(overrides=overrides)
    registry.add("game", MenuEntry("return"))
    registry.add("game", MenuEntry("history", visible=lambda: False))
    registry.add("game", MenuEntry("save"))
    assert ids(registry.shown("game")) == ["return", "save"]
    overrides.set_hidden("game", "save", True)
    assert ids(registry.shown("game")) == ["return"]
    overrides.set_hidden("game", "save", None)
    assert ids(registry.shown("game")) == ["return", "save"]


def test_the_author_list_orders_and_filters():
    registry = MenuRegistry(entries={"quick": ("menu", "hide")})
    registry.add("quick", MenuEntry("hide"))
    registry.add("quick", MenuEntry("menu"))
    assert ids(registry.shown("quick")) == ["menu", "hide"]
    title = MenuRegistry(entries={"title": ("quit", "load", "new_game")})
    title.add("title", MenuEntry("new_game"))
    title.add("title", MenuEntry("quit"))
    assert ids(title.shown("title")) == ["quit", "new_game"]     # "load" isn't registered


def test_an_empty_author_list_shows_the_defaults():
    registry = MenuRegistry(entries={"title": ()})
    registry.add("title", MenuEntry("quit"))
    registry.add("title", MenuEntry("new_game"))
    assert ids(registry.shown("title")) == ["new_game", "quit"]


def test_unknown_and_duplicate_ids_fail_at_install():
    registry = MenuRegistry()
    with pytest.raises(AssertionError):
        registry.add("game", MenuEntry("bogus"))
    registry.add("game", MenuEntry("quit"))
    with pytest.raises(AssertionError):
        registry.add("game", MenuEntry("quit"))
    with pytest.raises(AssertionError):
        registry.add("title", MenuEntry("main_menu"))          # a game id, not a title id
    with pytest.raises(AssertionError):
        registry.add("nope", MenuEntry("quit"))                 # type: ignore[arg-type]


def test_overrides_words_hidden_look_and_clear():
    overrides = UiOverrides()
    start = overrides.revision
    overrides.set_word("quit", "Leave")
    assert overrides.word("quit") == "Leave" and overrides.revision == start + 1
    overrides.set_word("quit", None)
    assert overrides.word("quit") is None
    overrides.set_hidden("title", "quit", True)
    overrides.set_title_look(background="gui/title_bg.png", music="other.ogg")
    assert overrides.title_look("background") == "gui/title_bg.png"
    assert overrides.title_look("music") == "other.ogg" and overrides.title_look("logo") is None
    overrides.set_title_look(logo="gui/logo.png", background=KEEP)
    assert overrides.title_look("background") == "gui/title_bg.png"
    overrides.set_word("new_game", "Begin")
    before = overrides.revision
    overrides.clear()
    assert overrides.revision == before + 1
    assert overrides.word("new_game") is None and overrides.hidden("title", "quit") is None
    assert all(overrides.title_look(part) is None for part in ("background", "logo", "music"))


@pytest.mark.parametrize("call", [
    lambda o: o.set_word("nope", "x"),
    lambda o: o.set_word("quit", "x" * 201),                    # [words] limit: 200
    lambda o: o.set_hidden("game", "bogus", True),
    lambda o: o.set_title_look(background="images/bg.png"),     # not in gui/
    lambda o: o.set_title_look(music="audio/title.ogg"),        # relative to audio/ (I-5)
    lambda o: o.set_title_look(music="../x.ogg"),
    lambda o: o.set_title_look(logo="gui/logo.png", music="title"),
])
def test_bad_overrides_are_refused_and_change_nothing(call):
    overrides = UiOverrides()
    with pytest.raises(ValueError):
        call(overrides)
    assert overrides.revision == 0 and overrides.title_look("logo") is None


def test_a_long_message_word_is_accepted():
    overrides = UiOverrides()
    overrides.set_word("confirm_quit", "x" * 1000)
    with pytest.raises(ValueError):
        overrides.set_word("confirm_quit", "x" * 1001)


# --- W66's drafted texts (G1, G7; 03-ui "Warnings") ------------------------------------------

def test_w66_quick_menu_text_is_03s():
    assert w66_text("quick_menu", "quick", "hied", ["hide", "menu"]) == (
        'config.toml: [quick_menu] entries has "hied", which isn\'t a quick-menu button. '
        'Did you mean "hide"? The buttons are hide and menu.')


def test_w66_title_form_and_list_join():
    text = w66_text("title", "title", "new_gam", ["new_game", "load", "quit"])
    assert text.startswith('config.toml: [title] entries has "new_gam"')
    assert 'Did you mean "new_game"?' in text
    assert text.endswith("The buttons are new_game, load, and quit.")
    assert "Did you mean" not in w66_text("title", "title", "xyz", ["new_game", "quit"])


def test_w66_empty_list_form():
    assert w66_empty_text("title", ["new_game", "quit"]) == (
        "config.toml: [title] entries is empty, so the default buttons are shown: new_game "
        'and quit. List the buttons to show, e.g. entries = ["new_game", "quit"].')


def test_join_names():
    assert join_names(["a"]) == "a"
    assert join_names(["a", "b"]) == "a and b"
    assert join_names(["a", "b", "c"]) == "a, b, and c"

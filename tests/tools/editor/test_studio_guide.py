"""F47 W6: New game's Start from, the Guide pane and the plain-words audit (``01-design.md``
PR-F47-25, PR-F47-26, §6.4; ``04-technical.md`` §3.2, §7.4, §16 W6): AC-F47-25 (Tk half:
the pane ticks from check data, Show me opens each place, open/closed is remembered per game)
and AC-F47-26 (the new texts are §6.4's, in plain words, on theme roles).

The game is made through File ▸ New game… with its real Start from dialog (answered from an
``after`` callback); the folder picker and the new Studio process are faked. Checks are the
headless check's real results, applied as Studio applies a finished check."""

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import (
    database,
    fileactions,
    files,
    formdialogs,
    guide,
    guidepane,
    playbar,
    studiostate,
)
from engine.tools.editor.checker import CheckEvent, CheckResult, CheckState
from engine.tools.editor.preview import PreviewEvent, PreviewState
from tests.tools.editor.conftest import patch_studio
from tests.tools.editor.test_scriptedit import BANNED as F46_BANNED
from tests.tools.f45_games import check

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401  (fixture)

pytestmark = pytest.mark.tk

STEPS = ["Name your game", "Add a character", "Add a background", "Write your first scene",
         "Add a choice", "Add an ending", "Play it"]


def apply_check(ed, game: Path) -> None:
    result = replace(check(game), serial=ed.win.edit_serial)
    ed.win.apply_check_events([CheckEvent(CheckState.DONE, result.serial, result)])
    ed.root.update()


def ticked(ed) -> list[int]:
    return [row.number for row in ed.win.guide_pane.rows if row.done]


def focused(ed, widget) -> bool:
    """``widget`` holds (or gets back) the window's keyboard focus; true without the OS
    focus too (two Studio windows are open here)."""
    ed.root.update()
    return str(ed.root.tk.call("focus", "-lastfor", ed.root)) == str(widget)


def state_of(game: Path) -> dict:
    return json.loads((game / ".studio" / "studio.json").read_text(encoding="utf-8"))


def append(ed, ref: str, text: str) -> None:
    """Type ``text`` at the end of ``ref``'s open document (as the author would)."""
    widget = ed.win.record_for(ref).widget
    widget.insert("end-1c", text)


def new_game_from_menu(ed, tmp_path: Path, monkeypatch) -> tuple[Path, list[dict]]:
    """File ▸ New game…: read the real Start from dialog, keep its first choice, go on."""
    seen: list[dict] = []
    folder = tmp_path / "night_ferry"
    patch_studio(monkeypatch, "ask_directory", lambda parent: folder)
    launched: list[Path] = []
    patch_studio(monkeypatch, "launch_studio", lambda path: launched.append(path))

    def answer(tries: int = 100) -> None:
        dialog = next((w for w in ed.root.winfo_children() if isinstance(w, tk.Toplevel)
                       and w.winfo_exists() and hasattr(w, "ask_buttons")), None)
        if dialog is None:                  # not up yet (a slow machine): look again
            if tries:
                ed.root.after(50, answer, tries - 1)
            return
        try:
            read(dialog)
        finally:
            if dialog.winfo_exists():       # never leave a modal dialog waiting
                dialog.ask_buttons[0].event_generate("<Return>")

    def read(dialog) -> None:
        texts = []

        def walk(widget) -> None:
            for child in widget.winfo_children():
                try:
                    texts.append(str(child.cget("text")))
                except tk.TclError:
                    pass
                walk(child)

        walk(dialog)
        buttons = dialog.ask_buttons
        seen.append({"title": dialog.title(), "texts": [t for t in texts if t],
                     "choices": [str(b.cget("value")) for b in buttons],
                     "chosen": str(buttons[0].cget("variable")) and
                     dialog.getvar(str(buttons[0].cget("variable"))),
                     "focus": str(dialog.tk.call("focus", "-lastfor", dialog))
                     == str(buttons[0])})

    ed.root.after(100, answer)
    ed.win.file_menu.invoke(ed.win.file_menu.index("New game…"))
    assert launched == [folder]
    return folder, seen


def test_ac_f47_25_the_guide_pane_ticks_shows_me_each_place_and_is_remembered(
        studio, tmp_path, monkeypatch):
    # New game…: Start from, the sample story first and chosen; then the folder.
    first = files.new_game(tmp_path / "first", template=files.TEMPLATE_EMPTY)
    assert isinstance(first, Path)
    opener = studio(first, mapped=True)
    game, seen = new_game_from_menu(opener, tmp_path, monkeypatch)
    assert seen[0]["title"] == "New game"
    assert seen[0]["choices"] == ["sample", "empty"]
    assert seen[0]["chosen"] == "sample" and seen[0]["focus"]
    shown = seen[0]["texts"]
    assert shown[:2] == ["Start from", "A short sample story (recommended)"]
    assert "An empty game" in shown and "Choose a folder…" in shown
    assert (game / "script" / "database.vns").is_file()            # the sample, not empty
    assert state_of(game) == {"guide_open": True, "played": False, "sample": True}

    # A new game opens with the Guide shown; the sample already ticks 4 and 5.
    ed = studio(game, mapped=True)
    win, pane = ed.win, ed.win.guide_pane
    assert win.guide_open() and pane.frame.winfo_ismapped()
    assert str(win.play_bar.guide_button.cget("style")) == "Secondary.TButton"
    assert pane.frame.winfo_x() > win.vpane.winfo_x()               # right of the tabs
    apply_check(ed, game)
    assert [str(r.label.cget("text")) for r in pane.step_rows] == STEPS
    assert ticked(ed) == [4, 5]
    assert pane.texts()[:4] == ["Guide", "Your first game", "2 of 7 done",
                                guidepane.INTRO]
    assert guidepane.STEP_HINTS["name"] in pane.texts()            # the next step's hint
    assert str(pane.step_rows[0].button.cget("style")) == "Secondary.TButton"
    assert not pane.done_card.winfo_manager()

    # Show me opens each place, with its New button (or field, or form) focused.
    def show_me(number: int) -> None:
        pane.step_rows[number - 1].button.invoke()
        ed.root.update()

    show_me(1)
    if any(tab.name == "settings" for tab in win.tabs):            # Game settings (W4)
        assert win.current_tab() == "settings"
        assert win.settings.page.key == "game"
    else:                                                           # before W4: the title
        assert win.current is win.files[CONFIG_REF]
        assert win.text.get("insert linestart", "insert lineend").startswith("title")
    for number, category in ((2, "character"), (3, "picture")):
        show_me(number)
        assert win.current_tab() == "database" and win.database.category == category
        assert focused(ed, win.database.new_button)
    show_me(4)
    assert win.current_tab() == "map" and win._side_open and win.side_tab == "events"
    assert win.story.key[0] == "start" and focused(ed, win.events_view.tree)
    forms_opened: list[str] = []
    monkeypatch.setattr(formdialogs, "pick_insert",
                        lambda *a, **k: pytest.fail("Show me skips the picker"))
    monkeypatch.setattr(formdialogs, "edit_choice",
                        lambda *a, **k: forms_opened.append("choice"))
    show_me(5)                                                      # the Choice form opens
    assert forms_opened == ["choice"] and win.story.key[0] == "start"
    asked: list[str] = []
    monkeypatch.setattr(win.story, "insert",
                        lambda index=None, doc=None: asked.append(doc.key))
    show_me(6)
    assert asked == ["ending"]
    show_me(7)
    assert focused(ed, win.play_bar.play_button)
    assert not win.dirty_files()                                   # Show me changed nothing

    # The author's own work ticks 1, 2, 3 and 6 after the next check (unsaved edits too
    # for the title and the character, read from the open documents).
    title = win.record_for(CONFIG_REF).widget
    line = title.search('title = "night_ferry"', "1.0")
    title.replace(f"{line} linestart", f"{line} lineend", 'title = "Night Ferry"')
    append(ed, "script/database.vns", '\ndefine rin = Character("Rin")\n'
                                      'image bg pier = "#336699"\n')
    append(ed, "script/main.vns", '\nlabel epilogue:\n    ending good "Good End"\n')
    win.save_all()
    apply_check(ed, game)
    assert ticked(ed) == [1, 2, 3, 4, 5, 6]
    assert "6 of 7 done" in pane.texts() and guidepane.STEP_HINTS["play"] in pane.texts()
    # A check that didn't load keeps the last ticks.
    bad = CheckResult(problems=(), problem_total=1, names={}, links=(), loaded=False,
                      serial=win.edit_serial, seconds=0.1)
    win.apply_check_events([CheckEvent(CheckState.DONE, bad.serial, bad)])
    assert ticked(ed) == [1, 2, 3, 4, 5, 6]

    # Play reaching the game window ticks 7: every step is done.
    win.apply_events([PreviewEvent(PreviewState.RUNNING)])
    ed.root.update()
    assert ticked(ed) == list(range(1, 8)) and state_of(game)["played"] is True
    assert pane.done_card.winfo_manager() and guide.DONE_TEXT in pane.texts()

    # ? Guide and Help ▸ Your first game hide and show it; remembered per game.
    win.play_bar.guide_button.invoke()
    ed.root.update()
    assert not win.guide_open() and state_of(game)["guide_open"] is False
    help_menu = win.help_menu
    help_menu.invoke(help_menu.index("Your first game"))
    assert win.guide_open() and state_of(game)["guide_open"] is True
    pane.close_button.invoke()                                      # ✕ in its header
    assert not win.guide_open() and state_of(game)["guide_open"] is False
    again = studio(game)
    assert not again.win.guide_open() and not again.win.guide_shown
    assert opener.win.guide_open() and not opener.win._guide_sample  # an empty new game too
    (game / ".studio" / "studio.json").unlink()
    assert not studio(game).win.guide_open()                        # no studio.json: closed


def test_ac_f47_26_new_texts_are_the_design_s_in_plain_words(studio, tmp_path):
    # §6.4 verbatim.
    assert [spec.text for spec in guide.STEPS] == STEPS
    assert guide.DONE_TEXT == "Your game runs from start to an ending. Well done!"
    assert files.START_FROM == "Start from"
    assert [label for _key, label in files.TEMPLATES] == [
        "A short sample story (recommended)", "An empty game"]
    assert [playbar.TIP_PLAY, playbar.TIP_SCENE, playbar.TIP_STOP] == [
        "Play from the start (Shift+F5)", "Play from the selected scene (F5)",
        "Stop the game (Ctrl+F2)"]
    assert (playbar.OPTIONS_TITLE, playbar.START_VALUES_HEADING, playbar.FRESH) == (
        "Play options", "Start values",
        "Play as a new player (forget what earlier playthroughs remember)")

    # Plain words: F46's banned words, plus file names and programmer words, in every new
    # F47 text (the Guide as shown, too). `quoted names` and {placeholders} are values.
    banned = re.compile(F46_BANNED.pattern + r"|(?<!\w)(toml|json|vns|python|boolean|bool|"
                        r"string|integer|float|syntax|parse|statement|argument|function|"
                        r"true|false|null)(?!\w)|\.(toml|json|vns|py|png|wav|ogg)\b",
                        re.IGNORECASE)
    # The Guide and New game speak to a first-time author: not even "script" or "code".
    first_time = re.compile(banned.pattern + r"|(?<!\w)(script|code|file|folder name)(?!\w)",
                            re.IGNORECASE)

    def strings(module, names=None) -> list[str]:
        found = []
        for name, value in vars(module).items():
            if not name.isupper() or (names is not None and not name.startswith(names)):
                continue
            values = value.values() if isinstance(value, dict) else [value]
            found += [v for v in values if isinstance(v, str)]
        return found

    game = files.new_game(tmp_path / "plain")
    ed = studio(game)
    apply_check(ed, game)
    guide_texts = [spec.text for spec in guide.STEPS] + [guide.DONE_TEXT, guide.GUIDE_TITLE]
    guide_texts += [label for _key, label in files.TEMPLATES] + [files.START_FROM]
    guide_texts += strings(guidepane, ("GUIDE_HEADING", "SHOW_ME", "TIP_", "INTRO",
                                       "PROGRESS", "STEP_HINTS"))
    guide_texts += strings(fileactions, ("NEW_GAME", "TEMPLATE_HINTS"))
    guide_texts += ed.win.guide_pane.texts()
    # The other new F47 texts so far: the Play bar, Studio's own state, the Database's
    # sentences (its "script name" rows are §6.2's).
    other = strings(playbar) + [studiostate.READ_TEXT, studiostate.WRITE_TEXT]
    other += [t for t in strings(database) if " " in t]
    assert len(guide_texts) > 30 and len(other) > 40
    for texts, words in ((guide_texts, first_time), (other, banned)):
        for text in texts:
            plain = re.sub(r"`[^`]*`|\{[^}]*\}", "", text)
            assert not words.search(plain), text

    # Theme roles only: no colour of its own in the Guide pane or the Start from dialog.
    for module in (guidepane, fileactions):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{6}\b", source), module.__name__

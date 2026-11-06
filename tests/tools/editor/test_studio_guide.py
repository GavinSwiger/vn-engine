"""F47 W6: New game's Start from, the Guide pane (its five chapters) and the plain-words
audit (``01-design.md`` PR-F47-25, PR-F47-26, §6.4; ``04-technical.md`` §3.2, §7.4, §16 W6): AC-F47-25 (Tk half:
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
    dbmore,
    fileactions,
    files,
    formdialogs,
    guide,
    guidepane,
    guidereader,
    guides,
    playbar,
    studiostate,
)
from engine.tools.editor.checker import CheckEvent, CheckItem, CheckResult, CheckState
from engine.tools.editor.preview import PreviewEvent, PreviewState
from tests.tools.editor.conftest import patch_studio
from tests.tools.editor.test_scriptedit import BANNED as F46_BANNED
from tests.tools.f45_games import check

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401  (fixture)

pytestmark = pytest.mark.tk

FIRST = ["Play the sample", "Name your game", "Add a character", "Give them pictures",
         "Add a background", "Write your first scene", "Add a choice", "Add an ending",
         "Play to an ending"]


def apply_check(ed, game: Path) -> None:
    result = replace(check(game), serial=ed.win.edit_serial)
    ed.win.apply_check_events([CheckEvent(CheckState.DONE, result.serial, result)])
    ed.root.update()


def ticked(ed) -> list[str]:
    """The ticked steps' keys, chapter by chapter."""
    return [row.key for row in ed.win.guide_pane.rows if row.done]


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
                # Next, as its button does: a made-up Return key goes to whichever window
                # has the keyboard, which may be another test's when they run in parallel.
                dialog.ask_pick(0)

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

    # A new game opens with the Guide shown, chapter 1 open, and nothing ticked: the
    # sample's own characters, choice and endings aren't the author's (FRICTION 7).
    ed = studio(game, mapped=True)
    win, pane = ed.win, ed.win.guide_pane
    assert win.guide_open() and pane.frame.winfo_ismapped()
    assert str(win.play_bar.guide_button.cget("style")) == "Secondary.TButton"
    assert pane.frame.winfo_x() > win.vpane.winfo_x()               # right of the tabs
    apply_check(ed, game)
    one = pane.blocks[0]
    assert [str(r.label.cget("text")) for r in one.step_rows] == FIRST
    assert ticked(ed) == []
    texts = pane.texts()
    assert texts[:7] == ["Guide", guidepane.INTRO, guidepane.OPEN_DOC,
                         "▾ 1. Your first game", "0 of 9", FIRST[0],
                         guidepane.STEP_HINTS["play_sample"]]
    assert "▸ 2. Make it yours" in texts and "▸ 4. Bigger games (optional)" in texts
    assert "Name your game" in texts and "Change it in a choice" not in texts   # closed
    assert str(one.step_rows[0].button.cget("style")) == "Step.Secondary.TButton"
    assert not one.done_card.winfo_manager()
    # Picking another step (a click on its text) shows its hint and Read more.
    one.step_rows[2].label.event_generate("<Button-1>")
    ed.root.update()
    assert one.step_rows[2].hint_shown and not one.step_rows[0].hint_shown
    # Chapters open and close from their heading.
    pane.blocks[1].head.invoke()
    assert "Pick a kit" in pane.texts() and pane.blocks[1].body.winfo_manager()
    pane.blocks[1].head.invoke()
    assert not pane.blocks[1].body.winfo_manager()

    # Show me opens each place, with its New button (or field, or form) focused.
    def show_me(number: int, block: int = 0) -> None:
        pane.blocks[block].step_rows[number - 1].button.invoke()
        ed.root.update()

    shown: list = []                                    # ▶ Play's ▾ (Play from the start)
    more = win.play_bar.more_button
    monkeypatch.setattr(more.tooltip, "show", lambda: shown.append("tip"))
    monkeypatch.setattr(more, "focus_set", lambda: shown.append("focus"))
    show_me(1)
    assert shown[:1] == ["focus"] and (shown == ["focus", "tip"] or not ed.root.winfo_viewable())
    show_me(2)
    if any(tab.name == "settings" for tab in win.tabs):            # Game settings (W4)
        assert win.current_tab() == "settings"
        assert win.settings.page.key == "game"
    else:                                                           # before W4: the title
        assert win.current is win.files[CONFIG_REF]
    for number, category in ((3, "character"), (4, "character"), (5, "picture")):
        show_me(number)
        assert win.current_tab() == "database" and win.database.category == category
        assert focused(ed, win.database.new_button)
    show_me(6)
    assert win.current_tab() == "map" and win._side_open and win.side_tab == "events"
    assert win.story.key[0] == "start" and focused(ed, win.events_view.tree)
    forms_opened: list[str] = []
    monkeypatch.setattr(formdialogs, "pick_insert",
                        lambda *a, **k: pytest.fail("Show me skips the picker"))
    monkeypatch.setattr(formdialogs, "edit_choice",
                        lambda *a, **k: forms_opened.append("choice"))
    show_me(7)                                                      # the Choice form opens
    assert forms_opened == ["choice"] and win.story.key[0] == "start"
    asked: list[str] = []
    monkeypatch.setattr(win.story, "insert",
                        lambda index=None, doc=None: asked.append(doc.key))
    show_me(8)
    assert asked == ["ending"]
    assert not win.dirty_files()                                   # Show me changed nothing
    # What Show me opened doesn't tick: the stage it drew at a line isn't the author's look.
    win.guide_mark(guide.STAGE_VIEWED)
    assert guide.STAGE_VIEWED not in win._guide_marks

    # The author's own work ticks after the next check (unsaved edits too).
    title = win.record_for(CONFIG_REF).widget
    line = title.search('title = "night_ferry"', "1.0")
    title.replace(f"{line} linestart", f"{line} lineend", 'title = "Night Ferry"')
    append(ed, "script/database.vns", '\ndefine rin = Character("Rin")\n'
                                      'image rin happy = "#aa3355"\n'
                                      'image bg pier = "#336699"\n')
    main = win.record_for("script/main.vns").widget
    start = main.search("label start:", "1.0")
    main.insert(f"{start} lineend", '\n    rin "We made it."')
    append(ed, "script/main.vns", '\nlabel epilogue:\n    menu:\n        "Stay":\n'
                                  '            ending good "Good End"\n'
                                  '        "Go":\n            jump start\n')
    win.save_all()
    apply_check(ed, game)
    assert ticked(ed) == ["name", "character", "looks", "background", "scene", "choice",
                          "ending"]
    assert "7 of 9" in pane.texts()
    # A check that didn't load keeps the last ticks.
    bad = CheckResult(problems=(), problem_total=1, names={}, links=(), loaded=False,
                      serial=win.edit_serial, seconds=0.1)
    win.apply_check_events([CheckEvent(CheckState.DONE, bad.serial, bad)])
    assert len(ticked(ed)) == 7

    # Play reaching the game window ticks Play the sample; an ending it reaches, the last
    # step: chapter 1 is done, shows its done text, and chapter 2 opens.
    win.apply_events([PreviewEvent(PreviewState.RUNNING)])
    ed.root.update()
    assert "play_sample" in ticked(ed) and state_of(game)["played"] is True
    win._guide_game_event("ending", {"id": "lantern", "title": "Wishes"})   # the sample's
    assert "play" not in ticked(ed)
    win._guide_game_event("ending", {"id": "good", "title": "Good End"})
    ed.root.update()
    assert state_of(game)["reached"] == ["good", "lantern"]
    assert pane.chapters[0].done and pane.chapters[1].current
    texts = pane.texts()
    assert guide.DONE_TEXT not in texts                            # chapter 1 closed itself
    assert "▸ 1. Your first game" in texts and "Done" in texts
    assert "▾ 2. Make it yours" in texts and guidepane.STEP_HINTS["kit"] in texts
    pane.blocks[0].head.invoke()
    assert guide.DONE_TEXT in pane.texts()                         # its done card

    # What Studio sees happen ticks too, once Show me's moment is over; kept per game.
    win._guide_quiet_until = 0.0
    win.guide_mark(guide.STAGE_VIEWED)
    assert "stage" in ticked(ed) and "stage_viewed" in state_of(game)["guide"]
    # A check with an error, then one without: Fix a problem ticks.
    error = CheckItem("error", "E43", "load", "there is no label named x", "script/main.vns", 1)
    win.refresh_guide(replace(check(game), problems=(error,)))
    win.refresh_guide(check(game))
    assert "fix_problem" in ticked(ed)

    # Bigger games can be skipped and brought back; remembered per game.
    four = pane.blocks[3]
    four.head.invoke()
    four.skip_link.invoke()
    ed.root.update()
    assert pane.chapters[3].skipped and "skip_bigger" in state_of(game)["guide"]
    assert "Skipped" in pane.texts() and guidepane.UNSKIP in pane.texts()
    four.skip_link.invoke()
    assert not pane.chapters[3].skipped

    # Read more opens the beginner's guide at that step's heading, inside Studio.
    row = pane.blocks[1].step_rows[0]
    row.more.invoke()
    ed.root.update()
    reader = win._guide_reader
    assert reader.window.winfo_exists() and reader.window.title() == "Beginner's guide"
    top = reader.text.index("@0,0")
    assert reader.text.get(top, f"{top} lineend") == row.spec.section
    reader.close()

    # Hidden, the Guide doesn't read checks; shown again, it reads the last one.
    win.play_bar.guide_button.invoke()
    ed.root.update()
    assert not win.guide_open() and state_of(game)["guide_open"] is False
    append(ed, "script/database.vns", '\ndefault helped = False\n')
    win.save_all()
    apply_check(ed, game)
    assert win._guide_stale and "variable" not in ticked(ed)
    help_menu = win.help_menu                                      # Help ▸ Guide checklist
    help_menu.invoke(help_menu.index("Guide checklist"))
    assert win.guide_open() and state_of(game)["guide_open"] is True
    assert "variable" in ticked(ed) and not win._guide_stale
    assert win.guides_menu.entrycget(0, "label") == "Beginner's guide"   # FRICTION 10
    # Help ▸ Guides opens each guide in the same reader inside Studio, never another app.
    monkeypatch.setattr(guides, "open_path", lambda path: pytest.fail(f"viewer: {path}"))
    win.guides_menu.invoke(1)                                      # Script language
    ed.root.update()
    reader = win._guide_reader
    assert reader.window.winfo_exists() and reader.window.title() == "Script language"
    assert reader.path.name == "script-language.md" and reader.text.get("1.0", "end").strip()
    win.guides_menu.invoke(0)                                      # back to the beginner's
    ed.root.update()
    assert not reader.window and win._guide_reader.window.title() == "Beginner's guide"
    win._guide_reader.close()
    pane.close_button.invoke()                                      # ✕ in its header
    assert not win.guide_open() and state_of(game)["guide_open"] is False
    again = studio(game)
    assert not again.win.guide_open() and not again.win.guide_shown
    assert again.win._guide_marks >= {"stage_viewed", "error_seen", "error_fixed"}
    assert opener.win.guide_open() and not opener.win._guide_sample  # an empty new game too
    assert [r.key for r in opener.win.guide_rows()][0] == "name"     # no sample to play
    (game / ".studio" / "studio.json").unlink()
    assert not studio(game).win.guide_open()                        # no studio.json: closed


def test_ac_f47_26_new_texts_are_the_design_s_in_plain_words(studio, tmp_path):
    # §6.4 verbatim, as the walkthrough widened it.
    assert [spec.text for spec in guide.STEPS] == FIRST
    assert guide.DONE_TEXT == "Your game runs from start to an ending. Well done!"
    assert files.START_FROM == "Start from"
    assert [label for _key, label in files.TEMPLATES] == [
        "A short sample story (recommended)", "An empty game"]
    assert [playbar.TIP_PLAY, playbar.TIP_START, playbar.TIP_SCENE, playbar.TIP_STOP] == [
        "Play from the scene named beside it (F5)", "Play from the start (Shift+F5)",
        "Play from the selected scene (F5)",
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
    # The Guide and New game speak to a first-time author: not even "script" or "code"
    # (a File menu entry's own name aside).
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
    guide_texts = [guide.DONE_TEXT, guide.GUIDE_TITLE, guide.DOC_TITLE]
    for chapter in guide.CHAPTERS:
        guide_texts += [chapter.title, chapter.done_text]
        guide_texts += [text for step in chapter.steps for text in (step.text, step.hint)]
    guide_texts += [label for _key, label in files.TEMPLATES] + [files.START_FROM]
    guide_texts += strings(guidepane, ("GUIDE_HEADING", "SHOW_ME", "TIP_", "INTRO",
                                       "PROGRESS", "STEP_HINTS", "READ_", "OPEN_DOC", "SKIP",
                                       "UNSKIP", "OPTIONAL", "DONE_WORD"))
    guide_texts += strings(fileactions, ("NEW_GAME", "TEMPLATE_HINTS"))
    for block in ed.win.guide_pane.blocks:                          # every chapter as shown
        block.head.invoke()
    guide_texts += ed.win.guide_pane.texts()
    # The other new F47 texts so far: the Play bar, Studio's own state, the Database's
    # sentences (its "script name" rows are §6.2's).
    other = strings(playbar) + [studiostate.READ_TEXT, studiostate.WRITE_TEXT]
    other += [t for t in strings(database) if " " in t]
    other += [t for t in strings(dbmore) if " " in t]           # W7's P2 categories
    assert len(guide_texts) > 150 and len(other) > 40
    for texts, words in ((guide_texts, first_time), (other, banned)):
        for text in texts:
            plain = re.sub(r"`[^`]*`|\{[^}]*\}|File ▸ [^,.]*", "", text)
            assert not words.search(plain), text

    # Theme roles only: no colour of its own in the Guide pane or the Start from dialog.
    for module in (guidepane, fileactions, guidereader):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{6}\b", source), module.__name__

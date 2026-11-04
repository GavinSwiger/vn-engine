"""F48 step W5: a card's Apply, Undo, Stale and Ask again in the Studio window
(``01-design.md`` §6.3, PR-F48-23, -29; ``04-technical.md`` §7.4; SEC-F48-12):
AC-F48-47 (one undo step per file, files unsaved, the check requested; an unopened file
opens; a new file goes through New script file), -48 (a changed scene is Stale; Ask again
sends §6.3's message), -49 (no file on disk changes during a chat until the author saves,
except a new file made empty) and -56 (card Undo while every file holds the applied text;
refused otherwise). No network: the model is a ``FakeTransport``; the keychain is a dict;
the pane's checks are a scripted runner."""

from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.tools.assistant import prefs as prefs_store
from engine.tools.assistant.edits import propose
from engine.tools.assistant.providers import ANTHROPIC, ANTHROPIC_ORIGIN
from engine.tools.editor import aisettings, document
from engine.tools.editor.assistpane import (
    APPLIED,
    APPLIED_MANY,
    ASK_AGAIN_TEXT,
    STALE,
    UNDO_REFUSED,
    UNDONE,
)
from tests.tools.assistant.assist_games import FakeRunner, service
from tests.tools.assistant.assist_games import pane as pane_workspace
from tests.tools.assistant.fake_models import anthropic_stream, reply, text_block, tool_block
from tests.tools.editor.ai_fakes import ANTHROPIC_KEY, services, wait_for
from tests.tools.f45_games import studio as make_game

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401  (fixture)

pytestmark = pytest.mark.tk

CH2 = "script/ch2.vns"
MAIN = "script/main.vns"
EXTRA = "script/extra.vns"
EXTRA_TEXT = 'label extra:\n    "A new scene."'


@pytest.fixture
def ai(tmp_path, monkeypatch, user_roots):
    """``ai(**kwargs)`` → (services, backend, transports) installed as
    ``aisettings.SERVICES``; ``consent=True`` records Anthropic consent first."""
    def install(*, consent: bool = False, **kwargs):
        made = services(tmp_path, **kwargs)
        monkeypatch.setattr(aisettings, "SERVICES", made[0])
        if consent:
            prefs_store.save(prefs_store.Prefs(consent=((ANTHROPIC, ANTHROPIC_ORIGIN),)),
                             made[0].folder)
        return made
    return install


def open_pane(ed):
    win = ed.win
    if not win.assistant_shown:
        win.toggle_assistant()
    session = aisettings.session_for(win)
    wait_for(ed.root, lambda: session.key_known)
    return win.assist_pane


def send(ed, text: str) -> None:
    pane = ed.win.assist_pane
    pane.set_input(text)
    pane.send_button.invoke()
    wait_for(ed.root, lambda: ed.win.assist_run is None)


def text_of(ed, ref: str) -> str:
    return ed.win.files[ref].widget.get("1.0", "end-1c")


def opened(game: Path, ref: str) -> str:
    """``ref``'s text as Studio opens it."""
    return document.open_document(GamePaths.for_game(game), ref).text


def disk(game: Path) -> dict[str, bytes]:
    """Every file under the game folder except Studio's own ``.studio/`` (the layout and
    state files it writes as the author works)."""
    return {p.relative_to(game).as_posix(): p.read_bytes() for p in game.rglob("*")
            if p.is_file() and ".studio" not in p.relative_to(game).parts}


def two_files(game: Path, texts: dict[str, str] | None = None):
    return propose(pane_workspace(game, texts), {"summary": "Bridge and a hello", "changes": [
        {"file": CH2, "old_text": "jump river", "new_text": "jump bridge"},
        {"file": MAIN, "old_text": 'hana "Hi."', "new_text": 'hana "Hello."'}]})


def river(game: Path, texts: dict[str, str] | None = None):
    return propose(pane_workspace(game, texts), {"summary": "A wider river", "changes": [
        {"file": CH2, "old_text": '    "The river."', "new_text": '    "The wide river."'}]})


def new_file(game: Path):
    return propose(pane_workspace(game), {"summary": "Add a scene", "changes": [
        {"file": EXTRA, "old_text": "", "new_text": EXTRA_TEXT},
        {"file": MAIN, "old_text": 'include "ch2.vns"',
         "new_text": 'include "ch2.vns"\ninclude "extra.vns"'}]})


# --- AC-F48-47: Apply ---------------------------------------------------------------------------

def test_ac_f48_47_apply_one_undo_step_per_file_unsaved_and_checked(studio, tmp_path, ai):
    ai()
    game = make_game(tmp_path)
    before = disk(game)
    ed = studio(game, mapped=True)
    win = ed.win
    pane = open_pane(ed)
    assert win.current.ref == MAIN and CH2 not in win.files       # ch2.vns isn't open
    original = {MAIN: text_of(ed, MAIN)}
    card = pane.add_card(two_files(game))
    win._cancel_debounce()
    card.buttons["apply"].invoke()
    ed.root.update()
    # The unopened file opened (not shown); both changed, unsaved, the check scheduled.
    assert CH2 in win.files and win.current.ref == MAIN
    assert "jump bridge" in text_of(ed, CH2) and 'hana "Hello."' in text_of(ed, MAIN)
    assert win.files[CH2].dirty and win.files[MAIN].dirty
    assert win._debounce_id is not None
    assert card.state == "applied" and card.texts()[-3:] == [
        APPLIED_MANY.format(n=2), "Show", "Undo"]
    assert APPLIED_MANY == "Applied to {n} files. Undo in each file, or use Undo here."
    assert disk(game) == before                                   # nothing written
    # One undo step per file: one Ctrl+Z in each editor takes the whole change back.
    win.files[MAIN].widget.edit_undo()
    assert text_of(ed, MAIN) == original[MAIN]
    win.files[CH2].widget.edit_undo()
    assert text_of(ed, CH2) == opened(game, CH2)
    # A one-file card says so; a second Apply (Ctrl+Enter on the card) does nothing.
    one = pane.add_card(river(game))
    one.buttons["apply"].invoke()
    assert one.texts()[-3] == APPLIED == "Applied. Ctrl+Z in the editor undoes it."
    applied = text_of(ed, CH2)
    pane.on_card("apply", one)
    assert text_of(ed, CH2) == applied and applied.count("The wide river.") == 1


def test_ac_f48_47_a_new_file_goes_through_new_script_file(studio, tmp_path, ai,
                                                         monkeypatch):
    ai()
    game = make_game(tmp_path)
    before = disk(game)
    ed = studio(game, mapped=True)
    win = ed.win
    pane = open_pane(ed)
    made = []
    from engine.tools.editor import files
    real = files.new_script
    monkeypatch.setattr(files, "new_script", lambda *a, **k: made.append((a[1:], k))
                        or real(*a, **k))
    card = pane.add_card(new_file(game))
    card.buttons["apply"].invoke()
    ed.root.update()
    # F45's New script file made it empty; its text is in the editor, unsaved.
    assert made == [(("script", "extra.vns"), {"text": ""})]
    assert (game / EXTRA).read_bytes() == b""
    assert EXTRA in win.refs and text_of(ed, EXTRA) == EXTRA_TEXT and win.files[EXTRA].dirty
    assert 'include "extra.vns"' in text_of(ed, MAIN) and win.files[MAIN].dirty
    assert card.created == (EXTRA,) and card.texts()[-3] == APPLIED_MANY.format(n=2)
    after = disk(game)
    assert after.pop(EXTRA) == b"" and after == before            # only the empty file
    # Show now opens the made file in the editor.
    card.buttons["show"].invoke()
    assert win.current.ref == EXTRA
    # Saving writes the text (the author's act).
    assert win.save_all()
    assert (game / EXTRA).read_text(encoding="utf-8").startswith("label extra:")


# --- AC-F48-48: Stale and Ask again -------------------------------------------------------------

def test_ac_f48_48_a_changed_scene_is_stale_and_ask_again_sends(studio, tmp_path, ai,
                                                              monkeypatch):
    made, backend, transports = ai(keys={"anthropic": ANTHROPIC_KEY}, consent=True)
    game = make_game(tmp_path)
    ed = studio(game, mapped=True)
    win = ed.win
    win.assist_checks = service(game, FakeRunner())
    pane = open_pane(ed)
    card = pane.add_card(river(game))
    # The author changes the river scene: Apply refuses and changes nothing.
    win.open_file(CH2)
    widget = win.files[CH2].widget
    widget.insert("11.end", " Cold.")
    edited = text_of(ed, CH2)
    changes = win.files[CH2].changes
    card.buttons["apply"].invoke()
    assert text_of(ed, CH2) == edited and win.files[CH2].changes == changes
    assert card.state == "stale"
    assert card.texts()[-3:] == [STALE, "Discard", "Ask again"]
    assert STALE == ("This file changed after the assistant wrote this change, so nothing "
                     "was changed.")
    # An edit in another scene only moves the change: it still applies, in the right place.
    moved = pane.add_card(propose(pane_workspace(game, {CH2: edited}), {
        "summary": "Louder", "changes": [
            {"file": CH2, "old_text": '"The bridge."', "new_text": '"The loud bridge."'}]}))
    widget.insert("1.end", "\n    pass")
    moved.buttons["apply"].invoke()
    assert moved.state == "applied"
    assert widget.get("10.0", "10.end") == '    "The loud bridge."'
    # Ask again sends §6.3's message with the current editor texts; the typed input stays.
    snapshots = []
    real = win.assist_snapshot
    monkeypatch.setattr(win, "assist_snapshot", lambda: snapshots.append(real()) or
                        snapshots[-1])
    pane.set_input("my draft")
    transports.queue(reply(anthropic_stream(text_block(0, "I'll read it again."))))
    card.buttons["ask_again"].invoke()
    wait_for(ed.root, lambda: win.assist_run is None)
    assert ASK_AGAIN_TEXT == "The file changed. Read it again and propose the change again."
    assert "YOU\n" + ASK_AGAIN_TEXT + "\nASSISTANT\n" in pane.transcript_text()
    assert ASK_AGAIN_TEXT.encode() in transports.requests[0].body
    assert snapshots[0].texts[CH2] == text_of(ed, CH2)            # the current file state
    assert pane.input_text() == "my draft"
    assert card.texts()[-1] == "Discard"                          # asked once


# --- AC-F48-49: nothing on disk changes until the author saves ----------------------------------

def test_ac_f48_49_a_chat_changes_no_file_until_the_author_saves(studio, tmp_path, ai):
    made, backend, transports = ai(keys={"anthropic": ANTHROPIC_KEY}, consent=True)
    game = make_game(tmp_path)
    before = disk(game)
    ed = studio(game, mapped=True)
    win = ed.win
    win.assist_checks = service(game, FakeRunner())
    open_pane(ed)
    transports.queue(
        reply(anthropic_stream(
            text_block(0, "Two changes."),
            tool_block(1, "t1", "read_script", {"file": CH2}),
            tool_block(2, "t2", "propose_edit", {"summary": "Go to the bridge", "changes": [
                {"file": CH2, "old_text": "jump river", "new_text": "jump bridge"}]}),
            tool_block(3, "t3", "propose_edit", {"summary": "Add a scene", "changes": [
                {"file": EXTRA, "old_text": "", "new_text": EXTRA_TEXT},
                {"file": MAIN, "old_text": 'include "ch2.vns"',
                 "new_text": 'include "ch2.vns"\ninclude "extra.vns"'}]}),
            stop="tool_use")),
        reply(anthropic_stream(text_block(0, "See the cards."))))
    send(ed, "Send them to the bridge and add a scene.")
    assert [c.title for c in win.assist_cards] == ["Go to the bridge", "Add a scene"]
    assert disk(game) == before                                   # proposing writes nothing
    for card in win.assist_cards:
        card.buttons["apply"].invoke()
    ed.root.update()
    assert [c.state for c in win.assist_cards] == ["applied", "applied"]
    after = disk(game)
    assert after.pop(EXTRA) == b"" and after == before            # only the new file, empty
    assert {r.ref for r in win.dirty_files()} == {CH2, MAIN, EXTRA}
    assert win.save_all()
    saved = disk(game)
    assert b"jump bridge" in saved[CH2] and b'include "extra.vns"' in saved[MAIN]
    assert saved[EXTRA].decode("utf-8").startswith("label extra:")


# --- AC-F48-56: card Undo -----------------------------------------------------------------------

def test_ac_f48_56_undo_restores_the_files_and_deletes_a_made_one(studio, tmp_path, ai):
    ai()
    game = make_game(tmp_path)
    before = disk(game)
    ed = studio(game, mapped=True)
    win = ed.win
    pane = open_pane(ed)
    main_text = text_of(ed, MAIN)
    card = pane.add_card(new_file(game))
    card.buttons["apply"].invoke()
    assert (game / EXTRA).exists()
    card.buttons["undo"].invoke()
    ed.root.update()
    assert text_of(ed, MAIN) == main_text
    assert not (game / EXTRA).exists() and EXTRA not in win.refs and EXTRA not in win.files
    assert disk(game) == before
    assert card.state == "open" and card.texts()[-4:] == [UNDONE, "Apply", "Show", "Discard"]
    # Applied again, then saved: Undo still deletes the file (it holds the applied text).
    card.buttons["apply"].invoke()
    assert win.save_all() and (game / EXTRA).read_bytes() != b""
    card.buttons["undo"].invoke()
    assert not (game / EXTRA).exists() and card.state == "open"
    # Two files, one unchanged since: the card's tokens.
    card = pane.add_card(two_files(game, {MAIN: text_of(ed, MAIN)}))
    card.buttons["apply"].invoke()
    ch2 = text_of(ed, CH2)
    card.buttons["undo"].invoke()
    assert "jump river" in text_of(ed, CH2) and 'hana "Hi."' in text_of(ed, MAIN)
    assert card.texts()[-4] == UNDONE


def test_ac_f48_56_undo_is_refused_once_a_file_changed(studio, tmp_path, ai):
    ai()
    game = make_game(tmp_path)
    ed = studio(game, mapped=True)
    win = ed.win
    pane = open_pane(ed)
    # Typing in one file after Apply: refused, nothing undone.
    card = pane.add_card(two_files(game))
    card.buttons["apply"].invoke()
    win.files[MAIN].widget.insert("end-1c", "\n# note")
    changed = {ref: text_of(ed, ref) for ref in (MAIN, CH2)}
    card.buttons["undo"].invoke()
    assert {ref: text_of(ed, ref) for ref in (MAIN, CH2)} == changed
    assert card.texts()[-2:] == [UNDO_REFUSED, "Show"]
    assert UNDO_REFUSED == ("A file changed since, so Undo here can't run. Use Ctrl+Z in the "
                            "editor.")
    pane.on_card("undo", card)                                  # it stays refused
    assert {ref: text_of(ed, ref) for ref in (MAIN, CH2)} == changed
    # A Ctrl+Z in the editor counts as a change too.
    one = pane.add_card(river(game, {CH2: text_of(ed, CH2)}))
    one.buttons["apply"].invoke()
    win.files[CH2].widget.edit_undo()
    one.buttons["undo"].invoke()
    assert one.texts()[-2] == UNDO_REFUSED
    # A made file whose disk text changed outside Studio isn't deleted.
    made = pane.add_card(new_file(game))
    made.buttons["apply"].invoke()
    (game / EXTRA).write_text("label other:\n", encoding="utf-8")
    made.buttons["undo"].invoke()
    assert (game / EXTRA).read_text(encoding="utf-8") == "label other:\n"
    assert made.texts()[-2] == UNDO_REFUSED and EXTRA in win.files

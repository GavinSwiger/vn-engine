"""F48 step W4: the Assistant pane in the Studio window (``01-design.md`` §6.1, §6.3, §6.6,
PR-F48-14, -19 to -21, -24, -27; ``04-technical.md`` §3.2, §7.7; SEC-F48-12, -20, -21;
``07`` I-7): AC-F48-30 (toggle, the shared column, ``assistant_open`` per game), -31 (no
key: the empty state, no network), -44 (Stop/Esc keep "(stopped)"; the 50 ms poll never
blocks), -46 (cards from the plan), -53 (model text stays text), and the consent-first and
window-close rows. No network: the model is a ``FakeTransport``; the keychain is a dict;
the pane's checks are a scripted runner."""

import json
import threading
import time

import pytest

from engine.tools.assistant import prefs as prefs_store
from engine.tools.assistant.edits import CODE_NOTICE, NO_CODE_RUN, propose
from engine.tools.assistant.providers import ANTHROPIC, ANTHROPIC_ORIGIN
from engine.tools.assistant.providers.transport import FakeReply, TransportError
from engine.tools.assistant.reference import build_reference
from engine.tools.editor import aisettings, assistpane, playbar, studiostate
from engine.tools.editor.assistpane import CARD_LINES
from tests.tools.assistant.assist_games import FakeRunner, service
from tests.tools.assistant.assist_games import pane as pane_workspace
from tests.tools.assistant.fake_models import anthropic_stream, reply, text_block, tool_block
from tests.tools.editor.ai_fakes import ANTHROPIC_KEY, services, wait_for
from tests.tools.f45_games import studio as make_game

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401  (fixture)

pytestmark = pytest.mark.tk

CH2 = "script/ch2.vns"


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


def open_pane(ed) -> assistpane.AssistPane:
    win = ed.win
    if not win.assistant_shown:
        win.toggle_assistant()
    session = aisettings.session_for(win)
    wait_for(ed.root, lambda: session.key_known)
    return win.assist_pane


def send(ed, text: str, *, wait: bool = True) -> None:
    pane = ed.win.assist_pane
    pane.set_input(text)
    pane.send_button.invoke()
    if wait:
        wait_for(ed.root, lambda: ed.win.assist_run is None)


def state_bytes(game) -> bytes:
    return (game / ".studio" / "studio.json").read_bytes()


# --- AC-F48-30: toggling, the shared column, remembered per game -------------------------------

def test_ac_f48_30_toggle_share_the_column_and_remember(studio, tmp_path, ai):
    made, backend, transports = ai()
    game = make_game(tmp_path)
    ed = studio(game, mapped=True)
    win = ed.win
    assert not win.assistant_open() and not win.guide_open()
    # The Play bar's AI Assistant, left of ? Guide.
    bar = win.play_bar
    assert bar.assistant_button.cget("text") == playbar.ASSISTANT == "AI Assistant"
    assert bar.buttons.index(bar.assistant_button) == bar.buttons.index(bar.guide_button) - 1
    assert bar.assistant_button.winfo_x() < bar.guide_button.winfo_x()
    bar.assistant_button.invoke()
    ed.root.update()
    assert win.assistant_open() and str(bar.assistant_button.cget("style")) == \
        "Secondary.TButton"
    assert json.loads(state_bytes(game))["assistant_open"] is True
    # Ctrl+Shift+A hides it, from the editor (its Ctrl+A is select-all) and elsewhere.
    win.text.focus_force()
    ed.root.update()
    win.text.event_generate("<Control-Shift-A>")
    ed.root.update()
    assert not win.assistant_open()
    win.tree.focus_force()
    ed.root.update()
    win.tree.event_generate("<Control-Shift-A>")
    ed.root.update()
    assert win.assistant_open()
    assert ed.root.focus_get() is win.assist_pane.input           # it focuses the input
    # The Guide takes the column: opening it hides the pane, and back.
    bar.guide_button.invoke()
    ed.root.update()
    assert win.guide_open() and not win.assistant_open()
    view = win.view_menu
    view.invoke(view.index("AI Assistant"))
    ed.root.update()
    assert win.assistant_open() and not win.guide_open()
    state = studiostate.read_state(game)
    assert state.assistant_open is True and state.guide_open is False
    # Remembered per game: a new window opens with the pane shown.
    again = studio(game, mapped=True)
    assert again.win.assistant_open() and not again.win.guide_open()
    view = again.win.view_menu
    assert again.win.view_menu.entrycget(view.index("AI Assistant"), "accelerator") == \
        "Ctrl+Shift+A"
    view.invoke(view.index("AI Assistant"))
    assert studiostate.read_state(game).assistant_open is False
    # A game whose author never opened the pane keeps studio.json as F47 wrote it.
    other = make_game(tmp_path, "other")
    studio(other).win.toggle_guide()
    assert b"assistant_open" not in state_bytes(other)
    assert transports.made == []


def test_ac_f48_30_f6_reaches_the_pane_after_help(studio, tmp_path, ai):
    ai()
    ed = studio(make_game(tmp_path), mapped=True)
    win = ed.win
    win.help_text.focus_force()
    ed.root.update()
    win.cycle_focus(1)
    assert ed.root.focus_get() is win.tree                       # closed: Help → Project
    open_pane(ed)
    win.help_text.focus_force()
    ed.root.update()
    win.cycle_focus(1)
    assert ed.root.focus_get() is win.assist_pane.input
    win.cycle_focus(1)
    assert ed.root.focus_get() is win.tree
    win.assist_pane.send_button.focus_force()
    ed.root.update()
    win.cycle_focus(-1)
    assert ed.root.focus_get() is win.help_text


# --- AC-F48-31: no key ---------------------------------------------------------------------------

def test_ac_f48_31_no_key_shows_the_empty_state_and_sends_nothing(studio, tmp_path, ai,
                                                                  monkeypatch):
    made, backend, transports = ai()
    keystores = []
    real = made.keys
    made.keys = lambda: keystores.append(1) or real()
    ed = studio(make_game(tmp_path), mapped=True)
    assert keystores == [] and backend.calls == []        # nothing read before the pane opens
    pane = open_pane(ed)
    assert pane.is_empty_state()
    assert pane.texts() == ["AI ASSISTANT", "New chat", "Claude · claude-sonnet-5-5",
                            assistpane.EMPTY_TEXT, "Set up AI…", assistpane.EMPTY_MCP,
                            "Connect an AI app…", "Send", "This chat: 0 tokens"]
    # [Set up AI…] opens Studio settings ▸ AI; [Connect an AI app…] the connect dialog.
    pane.set_up_button.invoke()
    assert ed.win.ai_settings is not None and ed.win.ai_settings.alive
    ed.win.ai_settings.close()
    pane.connect_button.invoke()
    assert ed.win.connect_dialog is not None
    ed.win.connect_dialog.close()
    # Send with no key: §6.6's text and [Open settings]; nothing goes out.
    asked = []
    monkeypatch.setattr(aisettings, "ask_consent", lambda *a, **k: asked.append(a) or True)
    send(ed, "Add a choice.")
    assert aisettings.provider_errors.NO_KEY in pane.transcript_text()
    buttons = [c for c in pane.transcript.winfo_children() if c.winfo_class() == "TButton"]
    assert [b.cget("text") for b in buttons] == ["Open settings"]
    assert transports.made == [] and asked == []
    assert pane.input_text() == "Add a choice."                  # the text is kept



def test_the_claude_plan_is_set_up_when_claude_code_is_installed(studio, tmp_path, ai,
                                                                  monkeypatch):
    """With Claude Code (the author's plan) there is no key: the chat shows when the
    program is installed, and else the empty state says only that (2026-11-04)."""
    from engine.tools.assistant.providers import CLAUDE_CODE, claudecode
    made, _backend, _transports = ai()
    prefs_store.save(prefs_store.Prefs(provider=CLAUDE_CODE), made.folder)
    monkeypatch.setattr(claudecode, "find_claude", lambda which=None: "C:/bin/claude.exe")
    ed = studio(make_game(tmp_path), mapped=True)
    win = ed.win
    win.toggle_assistant()
    ed.root.update()
    pane = win.assist_pane
    assert not pane.is_empty_state()
    assert assistpane.EMPTY_TEXT not in pane.texts()
    monkeypatch.setattr(claudecode, "find_claude", lambda which=None: None)
    win.assist_new_chat()
    ed.root.update()
    assert pane.is_empty_state()
    assert claudecode.NOT_INSTALLED in pane.texts() and "Set up AI…" in pane.texts()
    assert "Connect an AI app…" not in pane.texts()

# --- Consent first; the Sent line from the tool record ------------------------------------------

def test_consent_first_then_the_answer_and_the_sent_line(studio, tmp_path, ai, monkeypatch):
    made, backend, transports = ai(keys={"anthropic": ANTHROPIC_KEY})
    game = make_game(tmp_path)
    ed = studio(game, mapped=True)
    ed.win.assist_checks = service(game, FakeRunner())
    pane = open_pane(ed)
    assert not pane.is_empty_state()
    answers = [False, True]
    monkeypatch.setattr(aisettings, "ask_consent", lambda *a, **k: answers.pop(0))
    send(ed, "What happens at the river?")
    assert transports.made == [] and pane.input_text() == "What happens at the river?"
    assert not pane.has_content()
    transports.queue(reply(anthropic_stream(text_block(0, "The river is quiet."))))
    send(ed, "What happens at the river?")
    assert answers == [] and len(transports.requests) == 1
    request = transports.requests[0]
    assert request.endpoint.host == "api.anthropic.com"
    text = pane.transcript_text()
    assert text.startswith("YOU\nWhat happens at the river?\nASSISTANT\nSent: reference, "
                           "summary, ")
    assert "The river is quiet." in text and "↑ 170 (50 cached) ↓ 7" in text
    assert pane.footer.cget("text") == "This chat: 132 tokens"
    assert pane.sent_line() == "" and pane.input_text() == ""
    assert ANTHROPIC_KEY not in text
    # Consent was recorded: the next Send doesn't ask.
    transports.queue(reply(anthropic_stream(text_block(0, "Still quiet."))))
    send(ed, "And now?")
    assert len(transports.requests) == 2


# --- AC-F48-44: Stop/Esc, and the Tk thread never waits ------------------------------------------

def _blocking_stream(transports, first: bytes, rest: bytes) -> threading.Event:
    """The model answers ``first``, then waits until the run is cancelled (its next read
    fails as a socket shut down by ``cancel`` would)."""
    reads = []
    reached = threading.Event()

    def on_read(response) -> None:
        reads.append(1)
        if len(reads) == 2:
            reached.set()
            end = time.monotonic() + 20
            while not response._transport.cancelled and time.monotonic() < end:
                time.sleep(0.01)
            raise TransportError(TransportError.CANCELLED)      # as a shut-down socket

    transports.on_read = on_read
    transports.queue(FakeReply(200, {}, [first, rest]))
    return reached


def _split_stream(text: str) -> tuple[bytes, bytes]:
    data = anthropic_stream(text_block(0, text))
    cut = data.index(b"content_block_stop")
    return data[:cut], data[cut:]


def test_ac_f48_44_esc_stops_and_keeps_the_partial_answer(studio, tmp_path, ai):
    made, backend, transports = ai(keys={"anthropic": ANTHROPIC_KEY}, consent=True)
    game = make_game(tmp_path)
    ed = studio(game, mapped=True)
    ed.win.assist_checks = service(game, FakeRunner())
    pane = open_pane(ed)
    _blocking_stream(transports, *_split_stream("Partial answer about the river"))
    send(ed, "Tell me about the river.", wait=False)
    assert pane.send_button.cget("text") == "Stop"
    wait_for(ed.root, lambda: "Partial answer" in pane.transcript_text())
    started = time.perf_counter()
    pane.input.focus_force()
    pane.input.event_generate("<Escape>")
    assert time.perf_counter() - started < 0.05                 # Stop never blocks
    wait_for(ed.root, lambda: ed.win.assist_run is None)
    text = pane.transcript_text()
    assert "Partial answer about the river\n(stopped)\n" in text
    assert pane.send_button.cget("text") == "Send" and pane.status_label.cget("text") == ""
    assert max(ed.win.assist_poll_times) < 0.05
    # The Stop button does the same.
    _blocking_stream(transports, *_split_stream("Second partial"))
    send(ed, "Again.", wait=False)
    wait_for(ed.root, lambda: "Second partial" in pane.transcript_text())
    pane.send_button.invoke()
    wait_for(ed.root, lambda: ed.win.assist_run is None)
    assert pane.transcript_text().count("(stopped)") == 2


def test_ac_f48_44_a_large_streamed_answer_keeps_each_poll_short(studio, tmp_path, ai):
    made, backend, transports = ai(keys={"anthropic": ANTHROPIC_KEY}, consent=True)
    game = make_game(tmp_path)
    ed = studio(game, mapped=True)
    ed.win.assist_checks = service(game, FakeRunner())
    pane = open_pane(ed)
    lines = [f"Line {n}: see script/ch2.vns:{n % 12 + 1} and ```code {n}```" for n in
             range(2500)]
    answer = "\n".join(lines) + "x" * 20_000                     # and one long unbroken run
    transports.queue(reply(anthropic_stream(text_block(0, answer))))
    # A socket read lets go of the GIL; a FakeTransport read doesn't, and then (on Windows,
    # whose timed waits tick at 15.6 ms) every Tk call would wait a tick for the worker.
    transports.on_read = lambda _response: time.sleep(0.0005)
    build_reference()                   # built once per process (the pane warms it on open)
    send(ed, "Write a lot.")
    assert pane.transcript_text().count("Line ") == 2500
    assert len(ed.win.assist_poll_times) > 10                    # it took many polls
    assert max(ed.win.assist_poll_times) < 0.05, max(ed.win.assist_poll_times)


# --- AC-F48-46: cards from the plan ---------------------------------------------------------------

def test_ac_f48_46_cards_show_the_plan(studio, tmp_path, ai):
    ai()
    game = make_game(tmp_path)
    ed = studio(game, mapped=True)
    pane = open_pane(ed)
    ws = pane_workspace(game)
    plain = propose(ws, {"summary": "Go to the bridge", "changes": [
        {"file": CH2, "old_text": "jump river", "new_text": "jump bridge"}]})
    card = pane.add_card(plain)
    ed.root.update()
    shown = card.texts()
    assert shown[0] == "Go to the bridge"
    assert shown[1] == "script/ch2.vns  +1 −1"                  # file, +N −M from the plan
    rows = card.files[0].shown_rows()
    assert rows == list(plain.files[0].diff)
    assert [r[0] for r in rows] == [" ", " ", " ", "-", "+", " ", " ", " "]
    tags = {row[0]: card.files[0].text.tag_names(f"{i + 1}.0") for i, row in enumerate(rows)}
    assert "remove" in tags["-"] and "add" in tags["+"] and "context" in tags[" "]
    assert "No new problems." in shown and CODE_NOTICE not in shown
    assert shown[-3:] == ["Apply", "Show", "Discard"]
    assert str(card.buttons["apply"].cget("style")) == "TButton"   # the pane's one primary
    # Show: the file at its first change.
    card.buttons["show"].invoke()
    assert ed.win.current.ref == CH2 and ed.win.text.index("insert").startswith("4.")
    # Discard collapses the card.
    card.buttons["discard"].invoke()
    assert card.texts() == ["Discarded: Go to the bridge"]
    # A code-bearing change shows §6.3's code texts, the notice above the buttons.
    code = propose(ws, {"summary": "Count the bridge", "changes": [
        {"file": CH2, "old_text": '    "The bridge."',
         "new_text": '    $ trust += 1\n    "The bridge."'}]})
    card = pane.add_card(code)
    shown = card.texts()
    assert NO_CODE_RUN in shown and shown.index(CODE_NOTICE) == len(shown) - 4
    assert card.notice is not None and card.notice.cget("text") == CODE_NOTICE
    # A new file of 20 lines folds at 12, with visible escapes; Show all unfolds it.
    body = "\n".join(["label extra:"] + [f'    "Line {n} ‮ evil"' for n in range(19)])
    new = propose(ws, {"summary": "Add a scene", "changes": [
        {"file": "script/extra.vns", "old_text": "", "new_text": body}]})
    card = pane.add_card(new)
    part = card.files[0]
    assert card.texts()[1] == "script/extra.vns (new file)  +20 −0"
    assert len(part.shown_rows()) == CARD_LINES == 12
    assert part.more.cget("text") == "Show all 20 lines"
    assert "\\u202e" in part.shown_rows()[1] and "‮" not in "".join(part.shown_rows())
    part.more.invoke()
    assert len(part.shown_rows()) == 20 and not part.more.winfo_manager()
    # Show on a new file: a read-only view, nothing written.
    card.buttons["show"].invoke()
    view = ed.win.assist_new_view
    assert view.title() == "script/extra.vns (new file)"
    assert not (game / "script" / "extra.vns").exists()
    view.destroy()


def test_ac_f48_46_a_card_from_the_model_in_a_chat(studio, tmp_path, ai):
    made, backend, transports = ai(keys={"anthropic": ANTHROPIC_KEY}, consent=True)
    game = make_game(tmp_path)
    before = (game / "script" / "ch2.vns").read_bytes()
    ed = studio(game, mapped=True)
    ed.win.assist_checks = service(game, FakeRunner())
    pane = open_pane(ed)
    transports.queue(
        reply(anthropic_stream(text_block(0, "I'll change it."),
                               tool_block(1, "t1", "propose_edit", {
                                   "summary": "Go to the bridge", "changes": [
                                       {"file": CH2, "old_text": "jump river",
                                        "new_text": "jump bridge"}]}), stop="tool_use")),
        reply(anthropic_stream(text_block(0, "See the card."))))
    send(ed, "Go to the bridge instead.")
    assert [c.title for c in ed.win.assist_cards] == ["Go to the bridge"]
    text = pane.transcript_text()
    assert "· Checked the change: no new problems" in text
    assert text.index("I'll change it.") < text.index("· Checked") < text.index("See the card.")
    assert "script/ch2.vns lines" in pane.transcript_text().split("\n")[3]   # the Sent line
    assert (game / "script" / "ch2.vns").read_bytes() == before     # nothing written
    assert ed.win.files.get(CH2) is None or not ed.win.files[CH2].dirty


# --- AC-F48-53: model text stays text -------------------------------------------------------------

def test_ac_f48_53_model_text_is_plain_text(studio, tmp_path, ai):
    ai()
    game = make_game(tmp_path)
    ed = studio(game, mapped=True)
    pane = open_pane(ed)
    assert CH2 in ed.win.refs
    pane.start_exchange("Look.")
    for piece in ("See ![x](http://evil.example/a.png) and <img src=\"http://evil.example/b\">",
                  " and [go](javascript:alert(1)) \x1b[31mred\x1b[0m.\nPlaces: ../x.vns:3, ",
                  "script/unlisted.vns:4, script/ch2.vns:2 and ch2.vns:", "9.\n```\n",
                  "label start: script/ch2.vns:5\n```\nEnd ‮.\n"):
        pane.answer_text(piece)
    pane.finish(stopped=False, usage="Usage not reported.")
    text = pane.transcript_text()
    assert "![x](http://evil.example/a.png)" in text and '<img src="http://evil.example/b">' in text
    assert "javascript:alert(1)" in text and "\\u001b[31mred\\u001b[0m" in text
    assert "\x1b" not in text and "‮" not in text and "End \\u202e." in text
    # Only listed files link; ../x.vns and unlisted ones stay text; code isn't linked.
    assert sorted(pane.links().values()) == [(CH2, 2), (CH2, 9)]
    for name, (ref, line) in pane.links().items():
        ranges = pane.transcript.tag_ranges(name)
        assert pane.transcript.get(ranges[0], ranges[1]) in (f"{ref}:{line}", f"ch2.vns:{line}")
    fence = text.index("label start:")
    assert "code" in pane.transcript.tag_names(pane.transcript.index(f"1.0+{fence}c"))
    # A listed link opens the place in the editor; nothing else is ever opened.
    name = next(n for n, target in pane.links().items() if target == (CH2, 9))
    pane.click_link(name)
    assert ed.win.current.ref == CH2 and ed.win.text.index("insert").startswith("9.")
    # A 10 KB U+202E card title is escaped and cut at 120.
    ws = pane_workspace(game)
    proposal = propose(ws, {"summary": "Go", "changes": [
        {"file": CH2, "old_text": "jump river", "new_text": "jump bridge"}]})
    from dataclasses import replace
    card = pane.add_card(replace(proposal, summary="‮" * 10_000))
    assert len(card.title) <= 120 and "‮" not in card.title and card.title.startswith("\\u202e")


# --- 07 I-7: closing the window stops both check children -----------------------------------------

def test_i7_closing_the_window_stops_the_run_and_both_checks(studio, tmp_path, ai):
    made, backend, transports = ai(keys={"anthropic": ANTHROPIC_KEY}, consent=True)
    game = make_game(tmp_path)
    ed = studio(game, mapped=True)
    runner = FakeRunner()
    ed.win.assist_checks = service(game, runner)
    pane = open_pane(ed)
    reached = _blocking_stream(transports, *_split_stream("Thinking about it"))
    send(ed, "Think.", wait=False)
    wait_for(ed.root, reached.is_set)
    run = ed.win.assist_run
    ed.win.close()
    assert transports.made[-1].cancelled and run.cancelled.is_set()
    assert runner.stopped >= 1 and ed.checks.stopped
    run.join(10)
    assert not run.is_alive()

"""F48 step W3: File ▸ Studio settings… ▸ AI and the consent dialog (``01-design.md`` §6.2,
§6.4, PR-F48-15 to -17, -19, -33; ``04-technical.md`` §3.2, §7.5; SEC-F48-13, -16, -21):
AC-F48-32 (fields, provider texts, model defaults, the address row, limit ranges, Test
connection's "Connected." and §6.6 texts) and AC-F48-40 (consent per provider and origin;
Cancel sends nothing; the loopback wording). No network: every connection is a
``FakeTransport``; the keychain is a dict; the per-user folder is under ``tmp_path``."""

import json

import pytest

from engine.tools.assistant import keystore
from engine.tools.assistant.providers import errors as provider_errors
from engine.tools.assistant import prefs as prefs_store
from engine.tools.assistant.providers import (
    ANTHROPIC, ANTHROPIC_ORIGIN, COMPATIBLE, OPENAI, PROVIDER_LABELS, errors)
from engine.tools.assistant.providers.transport import FakeReply, TransportError
from engine.tools.editor import aisettings
from tests.tools.editor.ai_fakes import (
    ANTHROPIC_KEY, OPENAI_KEY, models_reply, services, status_reply, wait_for)
from tests.tools.f45_games import studio as make_game

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401  (fixture)

pytestmark = pytest.mark.tk


@pytest.fixture
def ai(tmp_path, monkeypatch, user_roots):
    """``ai(**services kwargs)`` → (services, backend, transports), installed as the
    default ``aisettings.SERVICES``."""
    def install(**kwargs):
        made = services(tmp_path, **kwargs)
        monkeypatch.setattr(aisettings, "SERVICES", made[0])
        return made
    return install


def open_page(ed):
    menu = ed.win.file_menu
    menu.invoke(menu.index(aisettings.MENU))
    page = ed.win.ai_settings
    wait_for(ed.root, lambda: not page.background.pending)
    return page


def settle(ed, page) -> None:
    wait_for(ed.root, lambda: not page.background.pending)


def pick_provider(ed, page, provider: str) -> None:
    page.provider_var.set(PROVIDER_LABELS[provider])
    page.apply_provider()
    settle(ed, page)


def shown(widget) -> bool:
    return bool(widget.winfo_manager())


def saved_prefs(made) -> dict:
    return json.loads((made.folder / prefs_store.PREFS_NAME).read_text(encoding="ascii"))


# --- AC-F48-32: the fields ---------------------------------------------------------------------

def test_ac_f48_32_fields_texts_defaults_and_ranges(studio, tmp_path, ai):
    made, backend, transports = ai(environ={"ANTHROPIC_API_KEY": ANTHROPIC_KEY})
    ed = studio(make_game(tmp_path), mapped=True)
    # Ctrl+, opens the page; File ▸ Studio settings… raises the open one.
    ed.win.text.focus_force()
    ed.win.text.event_generate("<Control-comma>")
    ed.root.update()
    page = ed.win.ai_settings
    assert page is not None and page.alive and page.dialog.title() == aisettings.TITLE
    assert open_page(ed) is page
    # Provider texts (§6.2) and the Anthropic defaults; no address row.
    assert list(page.provider_box.cget("values")) == [
        "Anthropic (Claude)", "OpenAI (ChatGPT)", "OpenAI-compatible (Ollama, LM Studio, …)"]
    assert page.provider_var.get() == "Anthropic (Claude)"
    assert page.model_var.get() == "claude-sonnet-5-5"
    assert list(page.model_box.cget("values"))[:2] == ["claude-sonnet-5-5", "claude-opus-5-5"]
    assert not shown(page.address_entry) and not shown(page.model_hint)
    assert page.key_status.cget("text") == keystore.NO_KEY
    assert page.key_var.get() == "" and str(page.key_entry.cget("show")) == "•"
    # PR-F48-33: the variable is offered (its own provider only).
    assert shown(page.env_box)
    assert page.env_box.cget("text") == "Use the key from ANTHROPIC_API_KEY"
    for text in ("Provider", "Model", "API key", "Paste", "Remove", "Test connection",
                 "Stop a request after", "steps", "Chat token limit",
                 aisettings.STEPS_HINT, aisettings.TOKEN_HINT):
        assert text in page.texts()
    # OpenAI: gpt-5 by default (prefs.DEFAULT_MODELS), no offer without its variable.
    pick_provider(ed, page, OPENAI)
    assert page.model_var.get() == "gpt-5" == prefs_store.DEFAULT_MODELS[OPENAI]
    assert not shown(page.address_entry) and not shown(page.env_box)
    # Compatible: the address row and its hints show; no model until Test connection.
    pick_provider(ed, page, COMPATIBLE)
    assert shown(page.address_entry) and shown(page.address_hint) and shown(page.model_hint)
    assert page.address_var.get() == "http://localhost:11434/v1"
    assert page.model_hint.cget("text") == "Test the connection to list the server's models."
    assert page.key_hint.cget("text") == "Leave empty if your server doesn't need a key."
    assert page.key_status.cget("text") == "No key saved for http://localhost:11434."
    assert page.model_var.get() == ""
    # Limits clamp into their ranges; text that isn't a number goes back.
    for typed, steps in (("99", 50), ("0", 1), ("seven", 1), ("20", 20)):
        page.steps_var.set(typed)
        page.apply_steps()
        assert page.steps_var.get() == str(steps) and page.prefs.steps == steps
    for typed, limit in (("5", 10_000), ("99,999,999", 10_000_000), ("250000", 250_000)):
        page.tokens_var.set(typed)
        page.apply_tokens()
        assert page.prefs.token_limit == limit
    # A bad model id is refused; a good one is kept per provider.
    pick_provider(ed, page, ANTHROPIC)
    page.model_var.set("claude opus")
    page.apply_model()
    assert page.model_var.get() == "claude-sonnet-5-5"
    page.model_var.set("claude-opus-5-5")
    page.model_box.event_generate("<<ComboboxSelected>>")
    saved = saved_prefs(made)
    assert saved["provider"] == ANTHROPIC and saved["models"][ANTHROPIC] == "claude-opus-5-5"
    assert saved["steps"] == 20 and saved["token_limit"] == 250_000
    page.close()
    assert ed.win.ai_settings is None
    assert transports.made == []                 # nothing reached a network
    assert not any(json.dumps(saved).count(text) for text in (ANTHROPIC_KEY, OPENAI_KEY))


def test_ac_f48_32_key_paste_remove_and_origin_binding(studio, tmp_path, ai, monkeypatch):
    made, backend, transports = ai()
    ed = studio(make_game(tmp_path), mapped=True)
    page = open_page(ed)
    # A key that isn't one is refused before any keychain call, and never echoed.
    ed.root.clipboard_clear()
    ed.root.clipboard_append("sk-ant-x\r\nX-Evil: 1")
    page.paste_button.invoke()
    settle(ed, page)
    assert page.key_status.cget("text") == keystore.BAD_SHAPE
    assert backend.calls == [("read", "anthropic")]
    # Paste saves to the keychain; the field shows dots and the last 4 only.
    ed.root.clipboard_clear()
    ed.root.clipboard_append(f"  {ANTHROPIC_KEY}\n")
    page.paste_button.invoke()
    settle(ed, page)
    assert backend.keys == {"anthropic": ANTHROPIC_KEY}
    assert page.key_status.cget("text") == keystore.SAVED_WINDOWS
    assert page.key_var.get() == "•" * 14 + " 6789"
    assert "readonly" in page.key_entry.state()
    assert ed.win.ai.key.origin == ANTHROPIC_ORIGIN
    # OpenAI has its own slot: a key typed there is saved on Enter.
    pick_provider(ed, page, OPENAI)
    assert page.key_status.cget("text") == keystore.NO_KEY and page.key_var.get() == ""
    page.key_var.set(OPENAI_KEY)
    page.key_entry.focus_force()
    ed.root.update()
    page.key_entry.event_generate("<Return>")
    settle(ed, page)
    assert backend.keys["openai"] == OPENAI_KEY and page.key_var.get().endswith(" cdef")
    # Compatible: a new address has no key ("No key saved for {origin}.").
    pick_provider(ed, page, COMPATIBLE)
    page.address_var.set("https://x.example/v1")
    page.apply_address()
    settle(ed, page)
    assert page.key_status.cget("text") == "No key saved for https://x.example:443."
    assert ed.win.ai.key is None
    # A refused address keeps the saved one and says why.
    page.address_var.set("http://10.0.0.5/v1")
    page.apply_address()
    assert page.address_status.cget("text") == errors.PLAIN_HTTP
    assert page.prefs.address == "https://x.example/v1"
    # Remove asks first (Cancel keeps the key), then clears the keychain entry.
    pick_provider(ed, page, ANTHROPIC)
    asked = []
    answers = [1, 0]

    def fake_ask(parent, message, buttons, *, escape, default=0, icon=None):
        asked.append((message, tuple(buttons), escape, default))
        return answers.pop(0)

    monkeypatch.setattr(aisettings.dialogs, "ask", fake_ask)
    page.remove_button.invoke()
    settle(ed, page)
    assert backend.keys.get("anthropic") == ANTHROPIC_KEY
    page.remove_button.invoke()
    settle(ed, page)
    assert asked[0] == ("Remove the saved API key?", ("Remove", "Cancel"), 1, 1)
    assert "anthropic" not in backend.keys
    assert page.key_status.cget("text") == keystore.NO_KEY and page.key_var.get() == ""
    assert transports.made == []
    page.close()


# --- AC-F48-32: Test connection ----------------------------------------------------------------

TEST_TABLE = [
    (models_reply("claude-sonnet-5-5", "claude-x-1"), "Connected."),
    (status_reply(401), "Anthropic didn't accept the API key. Check it in Studio settings ▸ AI."),
    (status_reply(403), "This API key can't use claude-sonnet-5-5. Pick another model or check "
                        "your Anthropic account."),
    (status_reply(404, {"error": {"type": "not_found_error", "message": "model"}}),
     "Anthropic has no model named claude-sonnet-5-5. Pick another in Studio settings ▸ AI."),
    (status_reply(429, headers={"retry-after": "20"}),
     "Anthropic is limiting requests right now. Try again in 20 s."),
    (status_reply(529), "Anthropic is busy right now. Try again in a minute."),
    (FakeReply(error=TransportError(TransportError.CONNECT)),
     "Couldn't reach api.anthropic.com. Check your internet connection."),
    (FakeReply(error=TransportError(TransportError.TLS)),
     "Couldn't make a secure connection to api.anthropic.com."),
    (FakeReply(302, {"location": "http://other/"}, [b""]), None),
]


def test_ac_f48_32_test_connection_texts(studio, tmp_path, ai):
    made, backend, transports = ai(keys={"anthropic": ANTHROPIC_KEY})
    ed = studio(make_game(tmp_path), mapped=True)
    page = open_page(ed)
    for reply, text in TEST_TABLE:
        transports.queue(reply)
        page.test_button.invoke()
        settle(ed, page)
        shown_text = page.test_status.cget("text")
        if text is None:                          # a redirect is an error, never followed
            assert shown_text.startswith("Anthropic returned an error:"), shown_text
        else:
            assert shown_text == text
        assert ANTHROPIC_KEY not in shown_text
    # One fresh provider (and transport) per Test; each sent one GET to the models list.
    assert len(transports.made) == len(TEST_TABLE)
    assert all(len(t.requests) == 1 for t in transports.made[:6])
    first = transports.made[0].requests[0]
    assert first.method == "GET" and first.endpoint.host == "api.anthropic.com"
    # The first Test filled the model list from the server's answer.
    assert "claude-x-1" in page.model_box.cget("values")
    # No key: §6.6's text and nothing sent.
    page.remove_button.state(["!disabled"])
    backend.keys.clear()
    page.load_key()
    settle(ed, page)
    page.test_button.invoke()
    settle(ed, page)
    assert page.test_status.cget("text") == provider_errors.NO_KEY
    assert transports.made[-1].requests == []
    # A compatible server on this computer: no key needed; the loopback wording.
    pick_provider(ed, page, COMPATIBLE)
    transports.queue(FakeReply(error=TransportError(TransportError.CONNECT)))
    page.test_button.invoke()
    settle(ed, page)
    assert page.test_status.cget("text") == "Couldn't reach localhost:11434. Is the server running?"
    transports.queue(models_reply("llama3.2", "qwen3"))
    page.test_button.invoke()
    settle(ed, page)
    assert page.test_status.cget("text") == "Connected."
    assert list(page.model_box.cget("values")) == ["llama3.2", "qwen3"]
    assert all("authorization" not in {k.lower() for k, _ in r.headers}
               for r in transports.made[-1].requests)
    page.close()


# --- AC-F48-40: consent -----------------------------------------------------------------------

def test_ac_f48_40_consent_per_provider_and_origin(studio, tmp_path, ai, monkeypatch):
    made, backend, transports = ai()
    ed = studio(make_game(tmp_path), mapped=True)
    session = aisettings.session_for(ed.win)
    asked = []
    answers = [False, True]

    def fake_ask(parent, title, message, *, fonts=None):
        asked.append((title, message))
        return answers.pop(0)

    monkeypatch.setattr(aisettings, "ask_consent", fake_ask)
    target = session.target()
    assert (target.provider, target.origin) == (ANTHROPIC, ANTHROPIC_ORIGIN)
    # Cancel: nothing recorded, so nothing may be sent.
    assert aisettings.ensure_consent(session, ed.root, target) is False
    assert not session.prefs.consented(ANTHROPIC, ANTHROPIC_ORIGIN)
    assert not (made.folder / prefs_store.PREFS_NAME).exists()
    # Send: recorded per user (provider, origin); not asked again.
    assert aisettings.ensure_consent(session, ed.root, target) is True
    assert aisettings.ensure_consent(session, ed.root, target) is True
    assert len(asked) == 2
    assert saved_prefs(made)["consent"] == [[ANTHROPIC, ANTHROPIC_ORIGIN]]
    title, message = asked[0]
    assert title == "Send parts of your game to Anthropic?"
    assert message.startswith("To help you, the assistant sends parts of this game to "
                              "Anthropic (api.anthropic.com): the open script file around")
    assert "Anthropic handles this under its own terms." in message
    assert message.endswith("Each answer lists what was sent. Studio never changes a file "
                             "until you click Apply.")
    # Another origin asks again; a server on this computer gets its own wording.
    session.save(prefs_store.Prefs(provider=COMPATIBLE, consent=session.prefs.consent))
    local = session.target()
    assert local.loopback and local.origin == "http://localhost:11434"
    answers.append(True)
    assert aisettings.ensure_consent(session, ed.root, local) is True
    title, message = asked[-1]
    assert title == "Send parts of your game to localhost:11434?"
    assert message.startswith("To help you, the assistant sends parts of this game to the "
                              "server at localhost:11434 on this computer: ")
    assert "own terms" not in message
    assert saved_prefs(made)["consent"] == [[ANTHROPIC, ANTHROPIC_ORIGIN],
                                            [COMPATIBLE, "http://localhost:11434"]]
    assert transports.made == []


def test_ac_f48_40_the_consent_dialog_send_and_cancel(studio, tmp_path, ai):
    ai()
    ed = studio(make_game(tmp_path), mapped=True)
    title, message = aisettings.consent_texts(aisettings.session_for(ed.win).target())

    def press(label: str | None) -> None:
        for child in ed.root.winfo_children():
            if isinstance(child, tk.Toplevel) and child.title() == title:
                if label is None:
                    child.event_generate("<Escape>")
                    return
                for button in _buttons(child):
                    if button.cget("text") == label:
                        button.invoke()
                        return
        ed.root.after(20, lambda: press(label))

    ed.root.after(50, lambda: press("Send"))
    assert aisettings.ask_consent(ed.root, title, message, fonts=ed.win.fonts) is True
    ed.root.after(50, lambda: press("Cancel"))
    assert aisettings.ask_consent(ed.root, title, message) is False
    ed.root.after(50, lambda: press(None))
    assert aisettings.ask_consent(ed.root, title, message) is False


def _buttons(widget):
    for child in widget.winfo_children():
        if child.winfo_class() == "TButton":
            yield child
        yield from _buttons(child)


def test_a_key_for_the_wrong_place_is_named_before_it_is_saved():
    mismatch = aisettings.key_mismatch
    assert mismatch("anthropic", "sk-ant-admin01-abc") == aisettings.KEY_ADMIN
    assert mismatch("anthropic", "sk-proj-abc") == aisettings.KEY_LOOKS_OPENAI
    assert mismatch("openai", "sk-ant-api03-abc") == aisettings.KEY_LOOKS_ANTHROPIC
    assert mismatch("anthropic", "sk-ant-api03-abc") is None
    assert mismatch("openai", "sk-proj-abc") is None
    assert mismatch("compatible", "sk-ant-admin01-abc") is None

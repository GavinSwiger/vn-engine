"""File ▸ Studio settings… ▸ AI and the consent dialog (F48 ``01-design.md`` §6.2, §6.4,
PR-F48-15 to -17, -19, -33; ``04-technical.md`` §3.2, §7.5; ``05-security.md`` SEC-F48-13,
-14, -16, -21; AC-F48-32, -40).

Why this module exists: the Assistant pane sends parts of the game, with the author's own
API key, to the provider the author picked. Only the author may pick it, so the settings are
per user (``assistant.prefs``) and the key lives in the OS keychain (``assistant.keystore``),
never in a game folder. This page is where both are set, and the consent dialog is where the
author agrees, once per provider and origin, before anything is sent.

- ``AiSession`` (``win.ai``, made by ``session_for(win)``): the window's settings, the key
  for the current provider and origin (a ``keystore.BoundKey``, bound to that origin:
  SEC-F48-16), and the seams (``AiServices``: key store, prefs folder, transport, the
  environment). The pane and this page share it.
- ``target_for(prefs)``: the provider, its origin (``scheme://host:port`` with the port
  written, the form ``keystore.slot_for`` wants), its §6.6 name, host and loopback flag, or
  the address's refusal text.
- ``open_ai_settings(win)``: the page (non-blocking modal, like Build game; the open one is
  raised). Fields apply on focus-out or Enter. Every keystore call and Test connection run
  off the Tk thread (``Background``); Test connection makes a fresh provider each time.
- ``ask_consent`` / ``ensure_consent``: §6.4. Cancel sends nothing; Send records consent for
  (provider, origin) in the per-user prefs.

The key is shown only as dots and its last 4 characters (``BoundKey.masked``); the entry
masks what is typed, its selection copies the dots, and the typed text is cleared as soon as
it is saved. No logging here.

Imports ``tkinter``, ``core``, its own package and ``tools.assistant`` (a Tk module: the
import-rule exception for Studio's Tk modules; the assistant never imports these).
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from queue import Empty, SimpleQueue
from tkinter import ttk
from typing import Any

from engine.tools.assistant import keystore
from engine.tools.assistant import prefs as prefs_store
from engine.tools.assistant.keystore import BoundKey, KeyResult, KeyStore, Slot
from engine.tools.assistant.prefs import Prefs
from engine.tools.assistant.providers import (
    ANTHROPIC,
    ANTHROPIC_ADDRESS,
    COMPATIBLE,
    CONNECTED,
    OPENAI,
    OPENAI_ADDRESS,
    PROVIDER_IDS,
    PROVIDER_LABELS,
    PROVIDER_NAMES,
    make_provider,
    suggested_models,
)
from engine.tools.assistant.providers import errors as provider_errors
from engine.tools.editor import dialogs
from engine.tools.editor.theme import THEME, dark_title_bar, scale_of

# --- Texts (01 §6.2, §6.4, final) --------------------------------------------------------------

MENU = "Studio settings…"
TITLE = "Studio settings"
HEADING = "STUDIO SETTINGS"
PAGE_AI = "AI"
PAGE_TITLE = "AI assistant"
PROVIDER = "Provider"
MODEL = "Model"
API_KEY = "API key"
SERVER_ADDRESS = "Server address"
PASTE = "Paste"
REMOVE = "Remove"
TEST = "Test connection"
STEPS_BEFORE = "Stop a request after"
STEPS_AFTER = "steps"
TOKEN_LIMIT = "Chat token limit"
CLOSE = "Close"
MODEL_HINT_COMPATIBLE = "Test the connection to list the server's models."
KEY_HINT_COMPATIBLE = "Leave empty if your server doesn't need a key."
ADDRESS_HINT = "Ollama: http://localhost:11434/v1 · LM Studio: http://localhost:1234/v1"
STEPS_HINT = ("How many times the assistant may look something up or check a change before "
              "it stops.")
TOKEN_HINT = "A new chat starts from zero."
REMOVE_ASK = "Remove the saved API key?"
REMOVE_BUTTONS = (REMOVE, "Cancel")

CONSENT_TITLE = "Send parts of your game to {provider}?"
CONSENT_PARTS = ("the open script file around the cursor, the lines you select, the current "
                 "problems, and any script file or config.toml it asks to read. Pictures and "
                 "sounds are never sent, but their file names may be.")
CONSENT_BODY = ("To help you, the assistant sends parts of this game to {provider} ({host}): "
                + CONSENT_PARTS + " {provider} handles this under its own terms. Requests use "
                "your API key and your account.")
CONSENT_BODY_LOCAL = ("To help you, the assistant sends parts of this game to the server at "
                      "{host} on this computer: " + CONSENT_PARTS
                      + " Requests use your API key and your account.")
CONSENT_AFTER = "Each answer lists what was sent. Studio never changes a file until you click Apply."
CONSENT_BUTTONS = ("Send", "Cancel")

# --- Look (px at 100 %) ------------------------------------------------------------------------

PAGE_LIST_PX = 140                      # §6.2: the page list's width
FORM_PX = 460
PADDING = dialogs.PADDING
ROW_GAP = 10
POLL_MS = 50                            # Background's poll, as the pane's (04 §7.7)
CONSENT_WRAP = 440


# --- Seams and the session ---------------------------------------------------------------------

@dataclass
class AiServices:
    """Where keys, settings and connections come from. ``keys`` makes the key store (once
    per session); ``folder`` is the per-user prefs folder (None: ``studio_user_dir()``);
    ``transport`` makes one transport per provider (None: a new ``HttpTransport``);
    ``environ`` is read for the key variables (None: ``os.environ``). Tests pass fakes."""

    keys: Callable[[], KeyStore] = KeyStore.default
    folder: Path | None = None
    transport: Callable[[], Any] | None = None
    environ: Mapping[str, str] | None = None


SERVICES = AiServices()                 # the default; tests replace it


@dataclass(frozen=True)
class Target:
    """Where requests for ``provider`` go: its ``origin`` (``scheme://host:port``), §6.6's
    ``name``, the ``host`` to show and whether it is on this computer; ``error`` is the
    address's refusal text (then ``origin`` is None)."""

    provider: str
    origin: str | None
    name: str
    host: str
    loopback: bool = False
    error: str | None = None


def target_for(prefs: Prefs) -> Target:
    """The current provider's ``Target`` (a compatible server's from the saved address)."""
    from engine.tools.assistant.providers.transport import parse_address
    provider = prefs.provider
    address = {ANTHROPIC: ANTHROPIC_ADDRESS, OPENAI: OPENAI_ADDRESS}.get(provider,
                                                                        prefs.address)
    try:
        endpoint = parse_address(address)
    except provider_errors.AddressError as exc:
        return Target(provider, None, PROVIDER_NAMES.get(provider, ""), "", error=exc.text)
    origin = keystore.FIXED_ORIGINS.get(provider, endpoint.origin)
    return Target(provider, origin, PROVIDER_NAMES.get(provider, endpoint.display_host),
                  endpoint.display_host, endpoint.loopback)


def slot_of(target: Target) -> Slot | None:
    """The key slot for ``target`` (None when its address is refused)."""
    if target.origin is None:
        return None
    try:
        return keystore.slot_for(target.provider, target.origin)
    except ValueError:
        return None


class Background:
    """Blocking work (keychain calls, Test connection) on a daemon thread; ``done(value)``
    runs on the Tk thread, from a ``POLL_MS`` poll. ``work`` must not raise (a raise is
    dropped). ``pending`` counts the jobs not yet answered."""

    def __init__(self, widget: tk.Misc) -> None:
        self.widget = widget
        self.pending = 0
        self.closed = False
        self._answers: SimpleQueue = SimpleQueue()
        self._after: str | None = None

    def run(self, work: Callable[[], Any], done: Callable[[Any], object]) -> None:
        self.pending += 1

        def body() -> None:
            try:
                value = work()
            except Exception:              # noqa: BLE001  (a bug: nothing to show)
                self._answers.put((None, None))
                return
            self._answers.put((done, value))

        threading.Thread(target=body, name="studio-ai", daemon=True).start()
        self._schedule()

    def _schedule(self) -> None:
        if self._after is None and not self.closed:
            try:
                self._after = self.widget.after(POLL_MS, self._poll)
            except tk.TclError:
                self.closed = True

    def _poll(self) -> None:
        self._after = None
        if self.closed:
            return
        while True:
            try:
                done, value = self._answers.get_nowait()
            except Empty:
                break
            self.pending -= 1
            if done is not None:
                done(value)
            if self.closed:
                return
        if self.pending:
            self._schedule()

    def close(self) -> None:
        self.closed = True
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None


class AiSession:
    """One window's AI settings, key and seams (``win.ai``). ``key`` and ``key_text`` belong
    to ``key_slot``; ``listeners`` run on the Tk thread after a setting or the key changes.
    Keystore calls block (up to 15 s): call ``resolve_key``, ``save_key`` and ``clear_key``
    off the Tk thread only (one at a time)."""

    def __init__(self, services: AiServices | None = None) -> None:
        self.services = services if services is not None else SERVICES
        self.prefs = prefs_store.load(self.services.folder)
        self.key: BoundKey | None = None
        self.key_slot: Slot | None = None
        self.key_text = ""
        self.key_known = False              # key/key_text answer key_slot (a load finished)
        self.listeners: list[Callable[[], object]] = []
        self._store: KeyStore | None = None
        self._lock = threading.Lock()
        self._key_lock = threading.Lock()       # one keystore call at a time

    # -- settings ---------------------------------------------------------------------------

    def reload(self) -> Prefs:
        self.prefs = prefs_store.load(self.services.folder)
        return self.prefs

    def save(self, prefs: Prefs) -> None:
        """Keep and write ``prefs`` (the session keeps them even if the write fails)."""
        self.prefs = prefs
        prefs_store.save(prefs, self.services.folder)
        self.changed()

    def changed(self) -> None:
        for listener in list(self.listeners):
            listener()

    def target(self) -> Target:
        return target_for(self.prefs)

    # -- keys (off the Tk thread) -----------------------------------------------------------

    def store(self) -> KeyStore:
        with self._lock:
            if self._store is None:
                self._store = self.services.keys()
            return self._store

    def resolve_key(self, slot: Slot, use_env: bool) -> KeyResult:
        """The saved key for ``slot``; with none saved and ``use_env``, the provider's key
        variable (PR-F48-33, its own provider only)."""
        with self._key_lock:
            found = self.store().load(slot)
        if found.key is None and use_env and slot.provider in keystore.ENV_VARS:
            env = keystore.env_key(slot.provider, self.services.environ)
            if env is not None:
                return KeyResult(True, found.text, env, keystore.WHERE_ENV)
        return found

    def save_key(self, slot: Slot, text: str) -> KeyResult:
        with self._key_lock:
            return self.store().save(slot, text)

    def clear_key(self, slot: Slot) -> KeyResult:
        with self._key_lock:
            return self.store().clear(slot)

    def set_key(self, slot: Slot | None, result: KeyResult | None) -> None:
        """Tk thread: the answer of a load, save or remove for ``slot``."""
        self.key_slot = slot
        self.key = result.key if result is not None else None
        self.key_text = result.text if result is not None else ""
        self.key_known = result is not None
        self.changed()

    def env_offer(self, provider: str) -> str | None:
        """The variable to offer ("Use the key from {VARIABLE}"), when it holds a key."""
        return keystore.env_variable(provider, self.services.environ)

    # -- providers --------------------------------------------------------------------------

    def provider(self, *, key: BoundKey | None = None):
        """A fresh provider for the current settings (one per Send and per Test
        connection: a cancel lasts for its transport's life). ``AddressError`` for a refused
        compatible address."""
        prefs = self.prefs
        transport = self.services.transport() if self.services.transport else None
        return make_provider(prefs.provider, model=prefs.model() or "", key=key,
                             address=prefs.address, transport=transport)


def session_for(win: Any) -> AiSession:
    """``win.ai``, made on first use."""
    session = getattr(win, "ai", None)
    if session is None:
        session = win.ai = AiSession()
    return session


def check_connection(session: AiSession, key: BoundKey | None) -> tuple[bool, str, list[str]]:
    """Test connection (off the Tk thread): a fresh provider's ``list_models()``. Returns
    (ok, "Connected." or §6.6's text, model ids)."""
    try:
        provider = session.provider(key=key)
    except provider_errors.AddressError as exc:
        return False, exc.text, []
    try:
        models = provider.list_models()
    except provider_errors.ProviderError as exc:
        return False, exc.text, []
    except provider_errors.KeyMismatchError as exc:
        return False, exc.text, []
    finally:
        try:
            provider.transport.close()
        except Exception:                   # noqa: BLE001  (FakeTransport has no close)
            pass
    return True, CONNECTED, models


# --- The consent dialog (§6.4) -----------------------------------------------------------------

def consent_texts(target: Target) -> tuple[str, str]:
    """§6.4's title and message for ``target`` (a server on this computer: its own words,
    without the terms sentence)."""
    title = CONSENT_TITLE.format(provider=target.name)
    if target.loopback:
        body = CONSENT_BODY_LOCAL.format(host=target.host)
    else:
        body = CONSENT_BODY.format(provider=target.name, host=target.host)
    return title, body + "\n\n" + CONSENT_AFTER


def ask_consent(parent: tk.Misc, title: str, message: str, *, fonts: dict | None = None) -> bool:
    """The modal consent question: **Send** (primary) or **Cancel** (Esc, the close box)."""
    dialog = dialogs._dialog(parent)
    dialog.title(title)
    answer = [False]

    def pick(index: int) -> None:
        answer[0] = index == 0
        dialog.destroy()

    body, scale = dialogs._body(dialog)
    wrap = round(CONSENT_WRAP * scale)
    heading = ttk.Label(body, text=title, style="Dialog.TLabel", wraplength=wrap,
                        justify="left")
    if fonts is not None:
        heading.configure(font=fonts["bodyStrong"], foreground=THEME["strongForeground"])
    heading.pack(anchor="w")
    for index, paragraph in enumerate(message.split("\n\n")):
        ttk.Label(body, text=paragraph, style="Dialog.TLabel", wraplength=wrap,
                  justify="left").pack(anchor="w", pady=(round((12 if index else 8) * scale),
                                                         0))
    buttons = dialogs._buttons(dialog, body, CONSENT_BUTTONS, pick, default=0)
    dialog.bind("<Escape>", lambda _e: pick(1))
    dialog.protocol("WM_DELETE_WINDOW", lambda: pick(1))
    dialogs._run(parent, dialog, buttons[0])
    return answer[0]


def ensure_consent(session: AiSession, parent: tk.Misc, target: Target, *,
                   ask: Callable[..., bool] | None = None, fonts: dict | None = None) -> bool:
    """True when the author agreed to send to (provider, origin): already, or now through
    §6.4's dialog (recorded in the per-user prefs). False: nothing may be sent."""
    if target.origin is None:
        return False
    if session.prefs.consented(target.provider, target.origin):
        return True
    title, message = consent_texts(target)
    if not (ask or ask_consent)(parent, title, message, fonts=fonts):
        return False
    granted = prefs_store.grant_consent(target.provider, target.origin, session.services.folder)
    # The grant loaded the file again: keep this session's own (maybe unsaved) values.
    session.prefs = replace(session.prefs, consent=granted.consent)
    return True


# --- The settings page (§6.2) ------------------------------------------------------------------

def open_ai_settings(win: Any) -> "AiSettingsDialog | None":
    """File ▸ Studio settings… (Ctrl+,): the page (the open one is raised)."""
    if getattr(win, "closed", False):
        return None
    dialog = getattr(win, "ai_settings", None)
    if dialog is not None and dialog.alive:
        dialog.dialog.lift()
        return dialog
    dialog = win.ai_settings = AiSettingsDialog(win)
    dialog.show()
    return dialog


def _int_text(value: int) -> str:
    return str(value)


def _styles(root: tk.Misc, fonts: dict) -> None:
    style = ttk.Style(root)
    back = THEME["widget.background"]
    style.configure("AiCaption.TLabel", background=back, foreground=THEME["muted"],
                    font=fonts["caption"])
    style.configure("AiStrong.TLabel", background=back,
                    foreground=THEME["strongForeground"], font=fonts["bodyStrong"])
    style.configure("AiPage.TLabel", background=THEME["list.activeSelection"],
                    foreground=THEME["list.activeSelectionForeground"], font=fonts["body"])
    style.configure("AiError.TLabel", background=back, foreground=THEME["marker.error"],
                    font=fonts["small"])


class AiSettingsDialog:
    """The settings page over ``win``. Widgets tests use: ``provider_box``, ``model_box``,
    ``key_entry``, ``paste_button``, ``remove_button``, ``key_status``, ``env_box``,
    ``address_entry``, ``address_status``, ``test_button``, ``test_status``,
    ``steps_entry``, ``tokens_entry``, ``close_button``; ``background`` runs the keystore
    and Test connection work."""

    def __init__(self, win: Any) -> None:
        self.win = win
        self.alive = True
        self.session = session_for(win)
        self.session.reload()
        dialog = self.dialog = dialogs._dialog(win.root)
        dialog.title(TITLE)
        self.scale = scale_of(dialog)
        self.fonts = win.fonts
        _styles(dialog, self.fonts)
        self.background = Background(dialog)
        self._models: dict[str, list[str]] = {}       # provider -> ids Test connection found
        self._test_serial = 0
        px = self.px
        body = ttk.Frame(dialog, padding=px(PADDING), style="Dialog.TFrame")
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=HEADING, style="AiCaption.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, px(12)))
        pages = ttk.Frame(body, style="Dialog.TFrame", width=px(PAGE_LIST_PX))
        pages.grid(row=1, column=0, sticky="nw")
        ttk.Frame(pages, width=px(PAGE_LIST_PX), height=0, style="Dialog.TFrame").pack()
        self.page_label = ttk.Label(pages, text=PAGE_AI, style="AiPage.TLabel",
                                    padding=(px(12), px(4)))
        self.page_label.pack(anchor="w", fill="x", padx=(0, px(16)))
        form = self.form = ttk.Frame(body, style="Dialog.TFrame")
        form.grid(row=1, column=1, sticky="nsew")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text=PAGE_TITLE, style="AiStrong.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, px(ROW_GAP)))
        wrap = px(FORM_PX - 140)
        # Provider.
        self._label(PROVIDER, 1)
        self.provider_var = tk.StringVar(dialog)
        self.provider_box = ttk.Combobox(form, textvariable=self.provider_var, state="readonly",
                                         values=[PROVIDER_LABELS[p] for p in PROVIDER_IDS],
                                         width=40)
        self.provider_box.grid(row=1, column=1, columnspan=2, sticky="ew")
        self.provider_box.bind("<<ComboboxSelected>>", lambda _e: self.apply_provider())
        # Model.
        self._label(MODEL, 2)
        self.model_var = tk.StringVar(dialog)
        self.model_box = ttk.Combobox(form, textvariable=self.model_var, width=40)
        self.model_box.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(px(ROW_GAP), 0))
        self.model_box.bind("<<ComboboxSelected>>", lambda _e: self.apply_model())
        self._applies(self.model_box, self.apply_model)
        self.model_hint = self._hint(form, MODEL_HINT_COMPATIBLE, wrap)
        self.model_hint.grid(row=3, column=1, columnspan=2, sticky="w")
        # API key.
        self._label(API_KEY, 4)
        key_row = ttk.Frame(form, style="Dialog.TFrame")
        key_row.grid(row=4, column=1, columnspan=2, sticky="ew", pady=(px(ROW_GAP), 0))
        key_row.columnconfigure(0, weight=1)
        self.key_var = tk.StringVar(dialog)
        self.key_entry = ttk.Entry(key_row, textvariable=self.key_var, show="•", width=24)
        self.key_entry.grid(row=0, column=0, sticky="ew")
        self._applies(self.key_entry, self.apply_typed_key)
        self.paste_button = self._button(key_row, PASTE, self.paste_key)
        self.paste_button.grid(row=0, column=1, padx=(px(8), 0))
        self.remove_button = self._button(key_row, REMOVE, self.remove_key)
        self.remove_button.grid(row=0, column=2, padx=(px(8), 0))
        self.key_status = self._hint(form, "", wrap)
        self.key_status.grid(row=5, column=1, columnspan=2, sticky="w")
        self.env_var = tk.BooleanVar(dialog, value=False)
        self.env_box = ttk.Checkbutton(form, text="", variable=self.env_var,
                                       command=self.apply_env, style="Dialog.TCheckbutton")
        self.env_box.grid(row=6, column=1, columnspan=2, sticky="w")
        self.key_hint = self._hint(form, KEY_HINT_COMPATIBLE, wrap)
        self.key_hint.grid(row=7, column=1, columnspan=2, sticky="w")
        # Server address (compatible only).
        self.address_label = self._label(SERVER_ADDRESS, 8)
        self.address_var = tk.StringVar(dialog)
        self.address_entry = ttk.Entry(form, textvariable=self.address_var, width=40)
        self.address_entry.grid(row=8, column=1, columnspan=2, sticky="ew",
                                pady=(px(ROW_GAP), 0))
        self._applies(self.address_entry, self.apply_address)
        self.address_hint = self._hint(form, ADDRESS_HINT, wrap)
        self.address_hint.grid(row=9, column=1, columnspan=2, sticky="w")
        self.address_status = ttk.Label(form, text="", style="AiError.TLabel", wraplength=wrap,
                                        justify="left")
        self.address_status.grid(row=10, column=1, columnspan=2, sticky="w")
        # Test connection.
        test_row = ttk.Frame(form, style="Dialog.TFrame")
        test_row.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(px(ROW_GAP + 4), 0))
        self.test_button = self._button(test_row, TEST, self.test)
        self.test_button.pack(side="left")
        self.test_status = ttk.Label(test_row, text="", style="Dialog.TLabel",
                                     wraplength=px(FORM_PX - 150), justify="left")
        self.test_status.pack(side="left", padx=(px(12), 0))
        # Steps and the token limit.
        steps_row = ttk.Frame(form, style="Dialog.TFrame")
        steps_row.grid(row=12, column=0, columnspan=3, sticky="w", pady=(px(ROW_GAP + 4), 0))
        ttk.Label(steps_row, text=STEPS_BEFORE, style="Dialog.TLabel").pack(side="left")
        self.steps_var = tk.StringVar(dialog)
        self.steps_entry = ttk.Entry(steps_row, textvariable=self.steps_var, width=5)
        self.steps_entry.pack(side="left", padx=px(8))
        ttk.Label(steps_row, text=STEPS_AFTER, style="Dialog.TLabel").pack(side="left")
        self._applies(self.steps_entry, self.apply_steps)
        self._hint(form, STEPS_HINT, px(FORM_PX)).grid(row=13, column=0, columnspan=3,
                                                       sticky="w")
        tokens_row = ttk.Frame(form, style="Dialog.TFrame")
        tokens_row.grid(row=14, column=0, columnspan=3, sticky="w", pady=(px(ROW_GAP), 0))
        ttk.Label(tokens_row, text=TOKEN_LIMIT, style="Dialog.TLabel").pack(side="left")
        self.tokens_var = tk.StringVar(dialog)
        self.tokens_entry = ttk.Entry(tokens_row, textvariable=self.tokens_var, width=10)
        self.tokens_entry.pack(side="left", padx=px(8))
        self._applies(self.tokens_entry, self.apply_tokens)
        self._hint(form, TOKEN_HINT, px(FORM_PX)).grid(row=15, column=0, columnspan=3,
                                                       sticky="w")
        buttons = ttk.Frame(body, style="Dialog.TFrame")
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(px(PADDING), 0))
        self.close_button = self._button(buttons, CLOSE, self.close, primary=True)
        self.close_button.pack(side="right")
        dialog.bind("<Escape>", lambda _e: self.close())
        dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()

    # --- Helpers -------------------------------------------------------------------------------

    def px(self, value: float) -> int:
        return round(value * self.scale)

    def _label(self, text: str, row: int) -> ttk.Label:
        label = ttk.Label(self.form, text=text, style="Dialog.TLabel")
        label.grid(row=row, column=0, sticky="w", padx=(0, self.px(16)),
                   pady=(self.px(ROW_GAP) if row > 1 else 0, 0))
        return label

    def _hint(self, parent: tk.Misc, text: str, wrap: int) -> ttk.Label:
        return ttk.Label(parent, text=text, style="Dialog.Hint.TLabel", wraplength=wrap,
                         justify="left")

    def _button(self, parent: tk.Misc, text: str, command: Callable[[], object], *,
                primary: bool = False) -> ttk.Button:
        zero = max(1, self.fonts["body"].measure("0"))
        button = ttk.Button(parent, text=text, command=command,
                            width=-max(1, -(-self.px(dialogs.BUTTON_MIN_WIDTH) // zero)),
                            style="TButton" if primary else "Secondary.TButton")
        for key in ("<Return>", "<KP_Enter>"):
            button.bind(key, lambda _e, b=button: (b.invoke(), "break")[1])
        return button

    @staticmethod
    def _applies(widget: tk.Widget, apply: Callable[[], object]) -> None:
        """A field applies on focus-out and on Enter (§6.2)."""
        widget.bind("<FocusOut>", lambda _e: apply(), add="+")
        for key in ("<Return>", "<KP_Enter>"):
            widget.bind(key, lambda _e: (apply(), "break")[1])

    @staticmethod
    def _show(widget: tk.Widget, shown: bool) -> None:
        if shown:
            widget.grid()
        else:
            widget.grid_remove()

    # --- State ---------------------------------------------------------------------------------

    @property
    def prefs(self) -> Prefs:
        return self.session.prefs

    def provider_id(self) -> str:
        return self.prefs.provider

    def model_choices(self, provider: str) -> list[str]:
        """The model list: §6.2's suggestions, the saved model, then what Test connection
        found."""
        found: list[str] = []
        for model in (*suggested_models(provider), self.prefs.model(provider),
                      *self._models.get(provider, ())):
            if model and model not in found:
                found.append(model)
        return found

    def refresh(self) -> None:
        """Show the saved settings; load the key for the current provider and origin."""
        prefs = self.prefs
        provider = prefs.provider
        self.provider_var.set(PROVIDER_LABELS[provider])
        self.model_box.configure(values=self.model_choices(provider))
        self.model_var.set(prefs.model(provider))
        compatible = provider == COMPATIBLE
        for widget in (self.model_hint, self.key_hint, self.address_label, self.address_entry,
                       self.address_hint, self.address_status):
            self._show(widget, compatible)
        self.address_var.set(prefs.address)
        self.address_status.configure(text="")
        self.steps_var.set(_int_text(prefs.steps))
        self.tokens_var.set(_int_text(prefs.token_limit))
        self.test_status.configure(text="")
        self.load_key()

    def _target_and_slot(self) -> tuple[Target, Slot | None]:
        target = self.session.target()
        return target, slot_of(target)

    def load_key(self) -> None:
        """Load the key for the current slot off the Tk thread (the field shows nothing and
        is off until it answers)."""
        target, slot = self._target_and_slot()
        if target.error is not None:
            self.address_status.configure(text=target.error)
        self.key_var.set("")
        self.key_status.configure(text="")
        if slot is None:
            self.session.set_key(None, None)
            self._show_key()
            return
        use_env = slot.provider in self.prefs.env
        self._set_key_buttons(False)
        self.background.run(lambda: self.session.resolve_key(slot, use_env),
                            lambda result, s=slot: self._key_loaded(s, result))

    def _key_loaded(self, slot: Slot, result: KeyResult) -> None:
        if not self.alive:
            return
        if self._target_and_slot()[1] != slot:
            return                              # the provider or address changed meanwhile
        self.session.set_key(slot, result)
        self._show_key()

    def _set_key_buttons(self, on: bool) -> None:
        for widget in (self.paste_button, self.remove_button, self.key_entry):
            widget.state(["!disabled"] if on else ["disabled"])

    def _show_key(self) -> None:
        """The key field: the saved key's dots and last 4, else an empty masked entry."""
        session = self.session
        key = session.key if session.key_slot == self._target_and_slot()[1] else None
        slot = self._target_and_slot()[1]
        self._set_key_buttons(slot is not None)
        saved = key is not None and key.where != keystore.WHERE_ENV
        self.key_entry.configure(show="" if saved else "•")
        self.key_var.set(key.masked if saved else "")
        if saved:
            self.key_entry.state(["readonly"])
        else:
            self.key_entry.state(["!readonly"])
        self.remove_button.state(["!disabled"] if saved else ["disabled"])
        self.key_status.configure(text=session.key_text if slot is not None else "")
        offer = session.env_offer(self.provider_id()) if slot is not None else None
        if offer is not None and not saved:
            self.env_box.configure(text=keystore.ENV_OFFER.format(variable=offer))
            self.env_var.set(self.provider_id() in self.prefs.env)
            self.env_box.grid()
        else:
            self.env_box.grid_remove()

    # --- Fields --------------------------------------------------------------------------------

    def apply_provider(self) -> None:
        labels = {PROVIDER_LABELS[p]: p for p in PROVIDER_IDS}
        provider = labels.get(self.provider_var.get())
        if provider is None or provider == self.prefs.provider:
            return
        self.session.save(replace(self.prefs, provider=provider))
        self.refresh()

    def apply_model(self) -> None:
        model = self.model_var.get().strip()
        provider = self.prefs.provider
        if model == self.prefs.model(provider):
            return
        if not prefs_store.model_ok(model):
            self.model_var.set(self.prefs.model(provider))
            return
        self.session.save(self.prefs.with_model(provider, model))
        self.model_var.set(model)

    def apply_address(self) -> None:
        text = self.address_var.get().strip()
        if text == self.prefs.address:
            return
        from engine.tools.assistant.providers.transport import parse_address
        if not prefs_store.address_ok(text):
            self.address_status.configure(text=provider_errors.BAD_ADDRESS)
            return
        try:
            parse_address(text)
        except provider_errors.AddressError as exc:
            self.address_status.configure(text=exc.text)
            return
        self.address_status.configure(text="")
        self.session.save(replace(self.prefs, address=text))
        self.test_status.configure(text="")
        self.load_key()                         # a new origin has its own key, or none

    def _int_field(self, var: tk.StringVar, low: int, high: int, current: int) -> int | None:
        text = var.get().strip().replace(",", "").replace("_", "")
        try:
            value = int(text)
        except ValueError:
            var.set(_int_text(current))
            return None
        value = min(high, max(low, value))
        var.set(_int_text(value))
        return value if value != current else None

    def apply_steps(self) -> None:
        value = self._int_field(self.steps_var, prefs_store.STEPS_MIN, prefs_store.STEPS_MAX,
                                self.prefs.steps)
        if value is not None:
            self.session.save(replace(self.prefs, steps=value))

    def apply_tokens(self) -> None:
        value = self._int_field(self.tokens_var, prefs_store.TOKEN_LIMIT_MIN,
                                prefs_store.TOKEN_LIMIT_MAX, self.prefs.token_limit)
        if value is not None:
            self.session.save(replace(self.prefs, token_limit=value))

    def apply_env(self) -> None:
        provider = self.provider_id()
        if provider not in keystore.ENV_VARS:
            return
        self.session.save(self.prefs.with_env(provider, bool(self.env_var.get())))
        self.load_key()

    # --- The key -------------------------------------------------------------------------------

    def apply_typed_key(self) -> None:
        """A key typed into the empty field is saved on Enter or focus-out."""
        if "readonly" in self.key_entry.state() or "disabled" in self.key_entry.state():
            return
        text = self.key_var.get()
        if not text.strip():
            return
        self.key_var.set("")                    # the typed key leaves the field at once
        self.save_key(text)

    def paste_key(self) -> None:
        """**Paste**: the clipboard, read once and at most 4 KiB (SEC-F48-13 (a)), saved."""
        try:
            text = self.dialog.clipboard_get()
        except tk.TclError:
            return
        text = text[:keystore.PASTE_MAX_CHARS + 1]
        self.save_key(text)

    def save_key(self, text: str) -> None:
        _target, slot = self._target_and_slot()
        if slot is None:
            return
        if keystore.check_key(text) is None:    # refused before any child sees it
            self.key_status.configure(text=keystore.BAD_SHAPE)
            return
        self._set_key_buttons(False)
        self.background.run(lambda: self.session.save_key(slot, text),
                            lambda result, s=slot: self._key_saved(s, result))

    def _key_saved(self, slot: Slot, result: KeyResult) -> None:
        if not self.alive:
            return
        if result.ok:
            self.session.set_key(slot, result)
            self._show_key()
        else:
            self._show_key()
            self.key_status.configure(text=result.text)

    def remove_key(self) -> None:
        """**Remove**, after "Remove the saved API key?" (Cancel is the default)."""
        _target, slot = self._target_and_slot()
        if slot is None or self.session.key is None:
            return
        choice = dialogs.ask(self.dialog, REMOVE_ASK, REMOVE_BUTTONS, escape=1, default=1)
        self._grab()
        if choice != 0 or not self.alive:
            return
        self._set_key_buttons(False)
        self.background.run(lambda: self.session.clear_key(slot),
                            lambda result, s=slot: self._key_removed(s, result))

    def _key_removed(self, slot: Slot, result: KeyResult) -> None:
        if not self.alive:
            return
        if result.ok:
            self.session.set_key(slot, KeyResult(True, result.text))
            self._show_key()
        else:
            self._show_key()
            self.key_status.configure(text=result.text)

    # --- Test connection -----------------------------------------------------------------------

    def test(self) -> None:
        """Test connection: a fresh provider's model list, off the Tk thread."""
        self.apply_model()
        self.apply_address()
        target, slot = self._target_and_slot()
        if target.error is not None:
            self.test_status.configure(text=target.error)
            return
        key = self.session.key if self.session.key_slot == slot else None
        self._test_serial += 1
        serial = self._test_serial
        provider = self.prefs.provider
        self.test_status.configure(text="")
        self.test_button.state(["disabled"])
        self.background.run(lambda: check_connection(self.session, key),
                            lambda answer: self._tested(serial, provider, answer))

    def _tested(self, serial: int, provider: str, answer: tuple[bool, str, list[str]]) -> None:
        if not self.alive or serial != self._test_serial:
            return
        self.test_button.state(["!disabled"])
        ok, text, models = answer
        self.test_status.configure(text=text)
        if ok and provider == self.prefs.provider:
            self._models[provider] = list(models)
            self.model_box.configure(values=self.model_choices(provider))

    # --- Showing and closing -------------------------------------------------------------------

    def texts(self) -> list[str]:
        """What the page shows, top to bottom (tests read it)."""
        out = [HEADING, PAGE_AI, PAGE_TITLE]

        def walk(widget: tk.Misc) -> None:
            for child in widget.winfo_children():
                if not child.winfo_manager():
                    continue
                if isinstance(child, (ttk.Label, ttk.Button, ttk.Checkbutton)):
                    text = str(child.cget("text"))
                    if text:
                        out.append(text)
                walk(child)
        walk(self.form)
        return out

    def _apply_fields(self) -> None:
        for apply in (self.apply_model, self.apply_address, self.apply_steps,
                      self.apply_tokens, self.apply_typed_key):
            apply()

    def _grab(self) -> None:
        if not self.alive:
            return
        try:
            self.dialog.grab_set()
        except tk.TclError:
            pass

    def close(self) -> None:
        if not self.alive:
            return
        try:
            self._apply_fields()
        except tk.TclError:
            pass
        self.alive = False
        self.background.close()
        try:
            self.dialog.grab_release()
        except tk.TclError:
            pass
        self.dialog.destroy()
        if getattr(self.win, "ai_settings", None) is self:
            self.win.ai_settings = None
        self.session.changed()

    def show(self) -> None:
        """Map the page, centered and modal (no waiting: Close ends it)."""
        d = self.dialog
        dialogs._center(d, self.win.root.winfo_toplevel())
        d.deiconify()
        dark_title_bar(d)
        self.provider_box.focus_set()
        self._grab()


__all__ = ["AiServices", "AiSession", "AiSettingsDialog", "Background", "CONSENT_AFTER",
           "CONSENT_BODY", "CONSENT_BODY_LOCAL", "CONSENT_BUTTONS", "CONSENT_TITLE", "MENU",
           "SERVICES", "Target", "ask_consent", "consent_texts", "ensure_consent",
           "check_connection", "open_ai_settings", "session_for", "slot_of", "target_for"]

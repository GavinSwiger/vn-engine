"""F48 step W6: the key-leak sweep (AC-F48-35, AB-11; SEC-F48-13 (b), -14, -22).

One Studio session with a known key (``NEEDLE``: not an API-key shape, so only the
redactor's registered secret can hide it) goes through Studio settings ▸ AI (a keychain
child that fails echoing the key on stderr, then a save), Test connection (a 401 and a 400
whose bodies echo the key, then "Connected."), a Send with tool calls and a card (Apply),
error paths (a 401 echoing the key in a chat, an ``http.client`` header exception inside
the real transport), a Tk callback exception, a thread exception and a crash report
holding the key, the Connect dialog's Copy buttons, and the check, preview, helper and
keychain children, with the key also in ``ANTHROPIC_API_KEY``. Then the needle must be in
none of: log records, stdout and stderr (tracebacks included), UI texts, request URLs or
bodies (only in the auth header), the clipboard after every Copy, child argv and env, and
any file under the test's folder (the game, ``.studio/``, ``studio.json``, the per-user
prefs ``assistant.json``). No network: the model is a ``FakeTransport`` (and one real
``HttpTransport`` over a connection that never opens a socket)."""

import http.client
import logging
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from engine.core.logsetup import RedactingFormatter
from engine.core.redact import KEY_SHAPE_RE, KEY_TOKEN, echo
from engine.tools.assistant import keystore
from engine.tools.assistant.keystore import FileStore, KeyStore, MacBackend
from engine.tools.assistant.providers import errors
from engine.tools.assistant.providers.transport import (
    HttpTransport, StaticResolver, TransportError)
from engine.tools.assistant.workspace import CheckService
from engine.tools.editor import aisettings, helperhub, install_error_hooks
from engine.tools.editor.checker import CheckRunner
from engine.tools.editor.connectdialog import open_connect_dialog
from engine.tools.editor.helperrunner import HelperRunner
from engine.tools.editor.preview import PreviewRunner
from tests.tools.assistant.fake_models import anthropic_stream, reply, text_block, tool_block
from tests.tools.editor.ai_fakes import Transports, models_reply, status_reply, wait_for
from tests.tools.f45_games import studio as make_game

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401  (fixture)

pytestmark = pytest.mark.tk

NEEDLE = "zq9Needle_4f9a8b7c6d5e3a21"       # a key that isn't key-shaped (SEC-F48-14)
CH2 = "script/ch2.vns"


# --- Spies ---------------------------------------------------------------------------------

class FakeSecurity:
    """``/usr/bin/security`` behind ``keystore.run_child``'s ``subprocess.run``: the first
    write fails with the key on stderr (AB-11), later ones store it. ``runs`` records
    (argv, env, stdin) of each child."""

    def __init__(self) -> None:
        self.keys: dict[str, str] = {}
        self.runs: list[tuple[list[str], dict, bytes]] = []
        self.fail_next_write = True

    def __call__(self, argv, *, input=b"", env=None, **_kwargs):
        self.runs.append((list(argv), dict(env or {}), input or b""))
        if argv[1:] == ["-i"]:
            found = re.search(r'-a "([^"]+)" -w "([^"]+)"', input.decode("ascii"))
            assert found is not None
            if self.fail_next_write:
                self.fail_next_write = False
                return subprocess.CompletedProcess(
                    argv, 1, b"", f"security: the item {found.group(2)} was refused\n".encode())
            self.keys[found.group(1)] = found.group(2)
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        slot = argv[argv.index("-a") + 1]
        if argv[1] == "find-generic-password":
            if slot in self.keys:
                return subprocess.CompletedProcess(argv, 0, (self.keys[slot] + "\n").encode(),
                                                   b"")
            return subprocess.CompletedProcess(argv, keystore.MAC_NOT_FOUND, b"", b"")
        self.keys.pop(slot, None)
        return subprocess.CompletedProcess(argv, 0, b"", b"")


class PopenSpy:
    """A ``popen`` seam that records each child's argv and env and refuses to start it."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.lock = threading.Lock()

    def __call__(self, argv, **kwargs):
        with self.lock:
            self.calls.append(([str(part) for part in argv], dict(kwargs.get("env") or {})))
        raise OSError("the test doesn't start children")


class Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class DummySock:
    def settimeout(self, _value) -> None:
        pass

    def close(self) -> None:
        pass

    def shutdown(self, _how) -> None:
        pass


class HeaderFails(http.client.HTTPSConnection):
    """Connects without a socket; ``putheader`` raises as ``http.client`` does for a bad
    header value, quoting the value (the key)."""

    def connect(self) -> None:
        self.sock = DummySock()

    def putheader(self, header, *values) -> None:
        if header.lower() in ("x-api-key", "authorization"):
            raise ValueError(f"Invalid header value {values[0]!r}")
        super().putheader(header, *values)


class HeaderFailing(HttpTransport):
    """The real transport, over a ``HeaderFails`` connection."""

    def _connection(self, endpoint):
        return HeaderFails(endpoint.host, endpoint.port, timeout=self.connect_timeout,
                           context=self.context), False


# --- Helpers -------------------------------------------------------------------------------

def ui_texts(root: tk.Misc) -> list[str]:
    """Every text a widget under ``root`` shows: labels, buttons, entries, text boxes,
    lists, combobox values, menus and window titles."""
    out: list[str] = []
    stack = [root]
    while stack:
        widget = stack.pop()
        stack.extend(widget.winfo_children())
        for read in (lambda w: w.cget("text"), lambda w: w.get("1.0", "end"),
                     lambda w: w.get(), lambda w: w.get(0, "end"),
                     lambda w: w.cget("values"), lambda w: w.title()):
            try:
                out.append(str(read(widget)))
            except (tk.TclError, TypeError, AttributeError):
                pass
        if isinstance(widget, tk.Menu):
            last = widget.index("end")
            for index in range(0 if last is None else last + 1):
                try:
                    out.append(str(widget.entrycget(index, "label")))
                except tk.TclError:
                    pass
    return out


def files_with(folder: Path, needle: str) -> list[str]:
    forms = (needle.encode("ascii"), needle.encode("utf-16-le"))
    return [p.relative_to(folder).as_posix() for p in folder.rglob("*")
            if p.is_file() and any(form in p.read_bytes() for form in forms)]


def clipboard(root: tk.Misc) -> str:
    try:
        return root.clipboard_get()
    except tk.TclError:
        return ""


def forget_needle() -> None:
    """The session registered ``NEEDLE`` with the process-wide redactor; clear its slots."""
    from engine.core import redact
    for slot, value in list(redact._secrets.items()):
        if value == NEEDLE:
            redact.set_secret(slot, None)


def boom() -> None:
    raise RuntimeError(f"a callback saw {NEEDLE}")


# --- AC-F48-35 ------------------------------------------------------------------------------

def test_ac_f48_35_the_key_reaches_nothing_but_its_header(studio, tmp_path, monkeypatch,
                                                          user_roots, capfd):
    assert not KEY_SHAPE_RE.search(NEEDLE) and keystore.check_key(NEEDLE) == NEEDLE
    monkeypatch.setenv("ANTHROPIC_API_KEY", NEEDLE)             # children must drop it
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)       # restored after the test
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    records = Records()
    vn = logging.getLogger("vn")
    monkeypatch.setattr(vn, "level", logging.DEBUG)
    logging.getLogger().addHandler(records)
    security = FakeSecurity()
    monkeypatch.setattr(keystore.subprocess, "run", security)
    spy = PopenSpy()
    monkeypatch.setattr(helperhub, "make_runner", lambda game: HelperRunner(game, popen=spy))
    prefs_folder = tmp_path / "studio"
    prefs_folder.mkdir()
    local = tmp_path / "studio-local"
    local.mkdir()
    transports = Transports()
    holder = [transports]
    services = aisettings.AiServices(
        keys=lambda: KeyStore(MacBackend(), FileStore(folder=lambda: local)),
        folder=prefs_folder, transport=lambda: holder[0](), environ={})
    monkeypatch.setattr(aisettings, "SERVICES", services)
    monkeypatch.setattr(aisettings, "ask_consent", lambda *a, **k: True)
    game = make_game(tmp_path)
    try:
        ed = studio(game, mapped=True)
        win = ed.win
        root = ed.root
        install_error_hooks(root)
        win.runner = PreviewRunner(popen=spy)
        win.check_runner = CheckRunner(game, popen=spy)
        shown: list[str] = []

        # 1. Studio settings ▸ AI: the keychain child fails echoing the key, then saves.
        menu = win.file_menu
        menu.invoke(menu.index(aisettings.MENU))
        page = win.ai_settings

        def settle() -> None:
            wait_for(root, lambda: not page.background.pending)

        settle()
        for _attempt in range(2):
            page.key_var.set(NEEDLE)
            page.key_entry.focus_force()
            root.update()
            page.key_entry.event_generate("<Return>")
            settle()
            shown += ui_texts(page.dialog)
        assert security.keys == {"anthropic": NEEDLE}
        assert f"security: the item {KEY_TOKEN} was refused" in " | ".join(shown)
        assert page.key_var.get().endswith(NEEDLE[-4:]) and NEEDLE not in page.key_var.get()

        # 2. Test connection: bodies echoing the key, then Connected.
        echo_body = {"error": {"type": "invalid_request_error",
                               "message": f"bad key {NEEDLE} sent"}}
        for answer in (status_reply(401, echo_body), status_reply(400, echo_body),
                       models_reply("claude-sonnet-5-5")):
            transports.queue(answer)
            page.test_button.invoke()
            settle()
            shown += ui_texts(page.dialog)
        assert page.test_status.cget("text") == "Connected."
        assert any(t.startswith("Anthropic returned an error:") for t in shown)
        page.close()

        # 3. A Send with tool calls and a card; the pane's check child is spied too.
        win.assist_checks = CheckService(game, runner=CheckRunner(game, popen=spy))
        win.toggle_assistant()
        wait_for(root, lambda: aisettings.session_for(win).key_known)
        pane = win.assist_pane
        transports.queue(
            reply(anthropic_stream(
                text_block(0, "Reading."),
                tool_block(1, "t1", "read_script", {"file": CH2}),
                tool_block(2, "t2", "propose_edit", {"summary": "Go to the bridge", "changes": [
                    {"file": CH2, "old_text": "jump river", "new_text": "jump bridge"}]}),
                stop="tool_use")),
            reply(anthropic_stream(text_block(0, "See the card."))))

        def send(text: str) -> None:
            pane.set_input(text)
            pane.send_button.invoke()
            wait_for(root, lambda: win.assist_run is None)

        send("Send them to the bridge.")
        assert [c.title for c in win.assist_cards] == ["Go to the bridge"]
        win.assist_cards[0].buttons["apply"].invoke()
        assert win.assist_cards[0].state == "applied"

        # 4. Error paths: a 401 echoing the key; an http.client header exception.
        transports.queue(status_reply(401, echo_body))
        send("Again.")
        assert errors.BAD_KEY.format(provider="Anthropic") in pane.transcript_text()
        holder[0] = lambda: HeaderFailing(resolver=StaticResolver(["192.0.2.1"]), proxies=dict)
        send("Once more.")
        holder[0] = transports
        assert pane.transcript_text().rstrip().endswith(
            errors.from_transport(TransportError(TransportError.PROTOCOL), provider="Anthropic",
                                  host="api.anthropic.com", loopback=False).text)
        shown += ui_texts(root)

        # 5. A Tk callback exception, a thread's and a crash report, each holding the key.
        root.after(0, boom)
        root.update()
        thread = threading.Thread(target=boom, name="leaky")
        thread.start()
        thread.join()
        try:
            boom()
        except RuntimeError:
            sys.excepthook(*sys.exc_info())

        # 6. Connect an AI app…: the clipboard after every Copy.
        dialog = open_connect_dialog(win)
        copied = []
        for index in range(len(dialog.copies)):
            dialog.copy(index)
            copied.append(clipboard(root))
        shown += ui_texts(dialog.dialog)
        dialog.close()

        # 7. The check, preview and helper children (the key is in os.environ).
        win.check_now()
        win.play_from_start()
        helperhub.hub_for(win).runner.thumb("images/bg/room.png", 64)
        wait_for(root, lambda: {"check", "run", "helper"} <= {part for argv, _ in spy.calls
                                                              for part in argv}, timeout=20)
        shown += ui_texts(root) + [text for *_, text in ed.dialogs]
        echoed = echo(f"the key is {NEEDLE}")
        win.close()
    finally:
        logging.getLogger().removeHandler(records)
        forget_needle()
    out, err = capfd.readouterr()

    # Logs: raw records and as Studio's formatter writes them.
    formatter = RedactingFormatter()
    for record in records.records:
        assert NEEDLE not in record.getMessage(), record.getMessage()
        assert NEEDLE not in formatter.format(record)
    # stdout, stderr: the three tracebacks are there, masked.
    assert NEEDLE not in out and NEEDLE not in err
    assert err.count("Exception in Tkinter callback") == 1
    assert "Exception in thread leaky" in err and err.count(f"a callback saw {KEY_TOKEN}") == 3
    # UI texts, echo().
    assert not [text for text in shown if NEEDLE in text]
    assert NEEDLE not in echoed and KEY_TOKEN in echoed
    # Requests: the key only in its header, never in a URL or a body.
    assert len(transports.requests) >= 5
    for request in transports.requests:
        assert NEEDLE not in request.target and NEEDLE.encode() not in (request.body or b"")
        assert [name for name, value in request.headers if NEEDLE in value] == ["x-api-key"]
    # The clipboard after every Copy.
    assert copied and not [text for text in copied if NEEDLE in text]
    # Children: argv and env (the keychain child gets the key on stdin only).
    assert len(spy.calls) >= 4, [argv for argv, _env in spy.calls]
    for argv, env in spy.calls + [(argv, env) for argv, env, _ in security.runs]:
        assert not [part for part in argv if NEEDLE in part], argv
        assert not [name for name, value in env.items() if NEEDLE in value], argv
        assert "ANTHROPIC_API_KEY" not in {name.upper() for name in env}
    assert [NEEDLE in stdin.decode() for _argv, _env, stdin in security.runs].count(True) == 2
    # Files: the game (``.studio/``, ``studio.json``), the per-user prefs, everything else.
    assert (game / ".studio").is_dir() and (prefs_folder / "assistant.json").is_file()
    assert files_with(tmp_path, NEEDLE) == []


def test_ac_f48_35_studio_installs_the_redacting_hooks(tmp_path, monkeypatch, capfd):
    """``run_editor`` (``python -m engine edit``) sends Tk callback, thread and uncaught
    exceptions through ``redact()`` before the window opens."""
    import engine.tools.editor as editor
    from engine.core import redact
    from engine.tools.editor import window

    made = []

    class FakeTk:
        def __init__(self) -> None:
            made.append(self)

        def mainloop(self) -> None:
            pass

        def destroy(self) -> None:
            pass

    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(tk, "Tk", FakeTk)
    monkeypatch.setattr(window, "EditorWindow", lambda root, paths: None)
    redact.set_secret("w6 test", NEEDLE)
    try:
        assert editor.run_editor(make_game(tmp_path)) == 0
        root = made[0]
        for report in (lambda info: root.report_callback_exception(*info),
                       lambda info: sys.excepthook(*info)):
            try:
                boom()
            except RuntimeError:
                report(sys.exc_info())
    finally:
        redact.set_secret("w6 test", None)
    err = capfd.readouterr().err
    assert NEEDLE not in err and err.count(f"a callback saw {KEY_TOKEN}") == 2
    assert err.startswith(editor.TK_CALLBACK_HEAD)

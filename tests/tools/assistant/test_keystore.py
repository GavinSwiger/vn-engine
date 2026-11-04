"""F48 step S7: the keystore (04 §7.5; 05 SEC-F48-13, -14, -15 as amended in §10, -16;
01 §6.2): AC-F48-33 (AB-12), AC-F48-34 (AB-10), AC-F48-60.

Every OS backend is faked: the macOS and Linux children through the ``run`` seam, Windows
Credential Manager through a fake ``advapi32``. The one real Credential Manager round trip
is ``manual`` and runs only with ``VN_KEYCHAIN=1``."""

import ast
import ctypes
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from engine.core import redact
from engine.core.paths import engine_root
from engine.tools.assistant import keystore as ks
from engine.tools.build import procs
from tests.core.test_safefile import Patched, link_dir

KEY = "sk-ant-api03-" + "Zq9_x-" * 7 + "3f9a"
OTHER = "sk-proj-" + "Ab1_-" * 8 + "Q7w2"
PLAIN = "loc4lK3y!~value"          # a compatible server's key: any shape
ANT = ks.slot_for(ks.ANTHROPIC)
LOCAL = ks.slot_for(ks.COMPATIBLE, "http://localhost:11434")
ENGINE = engine_root() / "engine"


@pytest.fixture(autouse=True)
def forget_secrets():
    yield
    for slot in list(redact._secrets):
        redact.set_secret(slot, None)


class Spy:
    """A ``run`` seam: records (argv, stdin) and answers from a script of ChildResults."""

    def __init__(self, *answers: ks.ChildResult) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, argv, stdin_text=""):
        self.calls.append((list(argv), stdin_text))
        return self.answers.pop(0) if self.answers else ks.ChildResult(0)


def files_in(folder: Path) -> list[str]:
    return sorted(os.listdir(folder)) if folder.exists() else []


@pytest.fixture
def user_dir(tmp_path) -> Path:
    folder = tmp_path / "local" / "_studio"
    folder.mkdir(parents=True)
    return folder


def store_with(backend, user_dir: Path, *, posix: bool = False) -> ks.KeyStore:
    return ks.KeyStore(backend, ks.FileStore(folder=lambda: user_dir, posix=posix))


# --- AC-F48-34 (AB-10): the shape rule ---------------------------------------------------------

@pytest.mark.parametrize("text", [
    "sk-ant-x\r\nX-Evil: 1", "sk-ant-inner space-key", "k" * 10 * 1024, "sk-ant-ключ-12345",
    "", "   ", "short", 'sk-ant-"quoted"-key', "sk-ant-back\\slash", "sk-ant-tab\there",
    "sk-ant-nul\x00here", "k" * 513, None, 12345678])
def test_ac_f48_34_bad_keys_are_refused_and_never_quoted(text, user_dir):
    backend = Spy()
    store = store_with(ks.SecretToolBackend("/usr/bin/secret-tool", run=backend), user_dir)
    assert ks.check_key(text) is None
    slot = ks.slot_for(ks.ANTHROPIC)
    result = store.save(slot, text)
    assert result == ks.KeyResult(False, ks.BAD_SHAPE)
    assert backend.calls == [] and files_in(user_dir) == []            # nothing sent anywhere
    assert redact._secrets == {}
    if isinstance(text, str) and len(text) > 3:
        assert text.strip() not in result.text


def test_ac_f48_34_good_keys_are_stripped_and_kept_whole():
    assert ks.check_key(f"  {KEY}\r\n") == KEY
    assert ks.check_key("x" * 8) == "x" * 8 and ks.check_key("x" * 512) == "x" * 512
    assert ks.check_key(" " * 4000 + KEY) == KEY
    assert ks.check_key(" " * 4097 + KEY) is None                      # paste cap: 4 KiB


def test_bound_key_shows_only_its_last_4_and_refuses_other_origins():
    key = ks.BoundKey(KEY, ks.ANTHROPIC, ks.FIXED_ORIGINS[ks.ANTHROPIC])
    for shown in (repr(key), str(key), f"{key}", repr([key])):
        assert KEY not in shown and KEY[:-4] not in shown and "…3f9a" in shown
    assert key.last4 == "3f9a" and key.masked.endswith(" 3f9a") and KEY not in key.masked
    assert key.check_origin("https://api.anthropic.com:443") == KEY
    for origin in ("https://api.openai.com:443", "https://api.anthropic.com:8443",
                   "http://api.anthropic.com:443", "https://evil.example:443"):
        with pytest.raises(ks.KeyOriginError):
            key.check_origin(origin)


def test_slots_bind_keys_to_their_origin():
    """SEC-F48-16: Anthropic and OpenAI keys keep their fixed origin whatever address is
    given; a compatible key is per exact origin."""
    assert ks.slot_for(ks.ANTHROPIC, "http://evil:80") == ANT
    assert ANT.origin == "https://api.anthropic.com:443" and ANT.name == "anthropic"
    assert ks.slot_for(ks.OPENAI).origin == "https://api.openai.com:443"
    assert LOCAL.name == "compatible http://localhost:11434"
    assert ks.slot_for(ks.COMPATIBLE, "http://localhost:1234") != LOCAL
    assert LOCAL.file_name != ks.slot_for(ks.COMPATIBLE, "http://localhost:1234").file_name
    assert len({ANT.file_name, LOCAL.file_name, ks.slot_for(ks.OPENAI).file_name}) == 3
    assert ANT.file_name.startswith("key-") and len(ANT.file_name) == len("key-") + 16 + 4
    for bad in (None, "", "localhost:11434", "ftp://x:21", "http://x", "http://x:0",
                'http://"x":80', "http://x y:80", "http://[::1]", "http://a:99999"):
        with pytest.raises(ValueError):
            ks.slot_for(ks.COMPATIBLE, bad)
    with pytest.raises(ValueError):
        ks.slot_for("gemini")
    assert ks.origin_ok("http://[::1]:11434") and ks.origin_ok("http://127.0.0.1:1234")


# --- AC-F48-33 (AB-12): backends -------------------------------------------------------------------

def test_ac_f48_33_linux_key_only_on_stdin_and_registered_before_the_child(user_dir):
    seen_masked = []
    spy = Spy()

    def run(argv, stdin_text=""):
        seen_masked.append(redact.redact(f"echo {PLAIN}"))
        return spy(argv, stdin_text)

    store = store_with(ks.SecretToolBackend("/usr/bin/secret-tool", run=run), user_dir)
    plain = store.save(LOCAL, PLAIN)                    # no key shape: only set_secret masks it
    assert plain.ok and seen_masked == ["echo <key>"]   # registered before the child ran
    assert spy.calls[0][1] == PLAIN and redact.redact(PLAIN) == "<key>"
    spy.calls.clear()
    result = store.save(ANT, f" {KEY} ")
    assert result.ok and result.text == ks.SAVED_KEYRING and result.where == ks.WHERE_KEYCHAIN
    (argv, stdin), = spy.calls
    assert argv[:2] == ["/usr/bin/secret-tool", "store"] and stdin == KEY
    assert not any(KEY in part for part in argv)
    assert argv[-4:] == ["service", ks.SERVICE, "account", "anthropic"]
    assert repr(result.key) and result.key.origin == ANT.origin
    assert redact.redact(KEY) == "<key>"
    assert files_in(user_dir) == []

    spy.answers = [ks.ChildResult(0, KEY.encode())]
    loaded = store.load(ANT)
    assert loaded.ok and loaded.key.value == KEY and loaded.text == ks.SAVED_KEYRING
    assert spy.calls[-1] == (["/usr/bin/secret-tool", "lookup", "service", ks.SERVICE,
                              "account", "anthropic"], "")
    spy.answers = [ks.ChildResult(1)]                        # lookup: no such item
    assert store.load(ANT) == ks.KeyResult(True, ks.NO_KEY)


def test_ac_f48_33_macos_key_only_on_stdin_and_read_back(user_dir):
    spy = Spy(ks.ChildResult(0), ks.ChildResult(0, (KEY + "\n").encode()))
    store = store_with(ks.MacBackend(run=spy), user_dir)
    result = store.save(LOCAL, KEY)
    assert result.ok and result.text == ks.SAVED_MACOS
    (add_argv, add_stdin), (find_argv, find_stdin) = spy.calls
    assert add_argv == ["/usr/bin/security", "-i"]
    assert add_stdin == (f'add-generic-password -U -s "{ks.SERVICE}" '
                         f'-a "compatible http://localhost:11434" -w "{KEY}"\n')
    assert find_argv == ["/usr/bin/security", "find-generic-password", "-s", ks.SERVICE,
                         "-a", "compatible http://localhost:11434", "-w"] and find_stdin == ""
    assert not any(KEY in part for argv, _ in spy.calls for part in argv)
    # security -i that echoes the key in its error text: the reason shows <key>.
    spy = Spy(ks.ChildResult(1, b"", f'add-generic-password -w "{KEY}": failed'.encode()))
    result = store_with(ks.MacBackend(run=spy), user_dir).save(LOCAL, KEY)
    assert not result.ok and KEY not in result.text and "<key>" in result.text
    assert result.text.startswith("Your keychain didn't save the key: ")
    # Not found / delete.
    spy = Spy(ks.ChildResult(ks.MAC_NOT_FOUND), ks.ChildResult(ks.MAC_NOT_FOUND))
    store = store_with(ks.MacBackend(run=spy), user_dir)
    assert store.load(LOCAL).text == "No key saved for http://localhost:11434."
    assert store.clear(LOCAL).ok
    assert spy.calls[-1][0][:2] == ["/usr/bin/security", "delete-generic-password"]


class FakeAdvapi:
    """``advapi32`` with the four functions, keeping credentials in a dict."""

    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}
        self.written: list[dict] = []
        self.freed = 0
        self.error = 0
        self._keep: list = []

        def write(cred_ref, flags):
            cred = cred_ref._obj
            blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            self.written.append({"Type": cred.Type, "Persist": cred.Persist,
                                 "TargetName": cred.TargetName, "blob": blob,
                                 "flags": flags})
            self.saved[cred.TargetName] = blob
            return 1

        def read(target, kind, flags, out_ref):
            if target not in self.saved:
                self.error = ks.ERROR_NOT_FOUND
                return 0
            blob = self.saved[target]
            buffer = (ctypes.c_ubyte * max(len(blob), 1)).from_buffer_copy(blob or b"\0")
            cred = ks.CREDENTIALW()
            cred.CredentialBlobSize = len(blob)
            cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
            self._keep += [buffer, cred]
            out_ref._obj.contents = cred
            return 1

        def delete(target, kind, flags):
            if self.saved.pop(target, None) is None:
                self.error = ks.ERROR_NOT_FOUND
                return 0
            return 1

        def free(pointer):
            self.freed += 1

        self.CredWriteW, self.CredReadW, self.CredDeleteW, self.CredFree = (
            write, read, delete, free)


def test_ac_f48_33_windows_persists_local_machine_and_frees_every_read(user_dir):
    dll = FakeAdvapi()
    backend = ks.WindowsBackend(load=lambda: dll, last_error=lambda: dll.error)
    store = store_with(backend, user_dir)
    result = store.save(ANT, KEY)
    assert result.ok and result.text == ks.SAVED_WINDOWS
    (written,) = dll.written
    assert written["Persist"] == ks.CRED_PERSIST_LOCAL_MACHINE == 2          # not ENTERPRISE
    assert written["Type"] == ks.CRED_TYPE_GENERIC and written["flags"] == 0
    assert written["TargetName"] == "vn-engine-studio/anthropic" and written["blob"] == KEY.encode()
    assert dll.CredWriteW.argtypes and dll.CredFree.restype is None          # typed first
    assert store.load(ANT).key.value == KEY and dll.freed == 1
    dll.saved["vn-engine-studio/anthropic"] = b"k" * (ks.BLOB_MAX_BYTES + 1)
    too_big = store.load(ANT)
    assert not too_big.ok and too_big.text.startswith("Couldn't read the key from your keychain")
    assert dll.freed == 2
    assert store.clear(ANT).ok and store.load(ANT) == ks.KeyResult(True, ks.NO_KEY)
    assert files_in(user_dir) == []


def test_advapi32_loads_from_system32_only(monkeypatch):
    seen = []
    monkeypatch.setattr(ks.ctypes, "WinDLL", lambda *a, **kw: seen.append((a, kw)),
                        raising=False)
    ks.load_advapi32()
    assert seen == [(("advapi32",), {"use_last_error": True, "winmode": 0x800})]
    assert isinstance(ks.detect_backend("win32"), ks.WindowsBackend)


@pytest.mark.parametrize("answer", [
    ks.ChildResult(None, timed_out=True),
    ks.ChildResult(1, b"", b"Prompt dismissed by the user"),
    ks.ChildResult(1, b"", b"Cannot create an item in a locked collection"),
    ks.ChildResult(1, b"x", b"org.freedesktop.DBus.Error.ServiceUnknown"),   # stdout: no
    ks.ChildResult(None, error="Permission denied"),
], ids=["timeout", "denied", "locked", "stdout", "no-start"])
def test_ac_f48_33_a_failing_keyring_refuses_and_writes_no_file(answer, user_dir):
    spy = Spy(answer)
    result = store_with(ks.SecretToolBackend("/usr/bin/secret-tool", run=spy),
                        user_dir).save(ANT, KEY)
    assert not result.ok and result.key is None
    assert result.text.startswith("Your keychain didn't save the key: ")
    assert result.text.endswith(". Nothing was saved.") and KEY not in result.text
    if answer.timed_out:
        assert ks.R_TIMEOUT in result.text
    assert files_in(user_dir) == []


@pytest.mark.parametrize("stderr", [
    b"secret-tool: The name org.freedesktop.secrets was not provided by any .service files "
    b"(org.freedesktop.DBus.Error.ServiceUnknown)",
    b"secret-tool: Cannot autolaunch D-Bus without X11 $DISPLAY",
    b"secret-tool: Could not connect: No such file or directory"])
def test_ac_f48_33_no_secret_service_uses_the_private_file(stderr, user_dir, monkeypatch):
    modes = []
    real_write = ks.safefile.write_atomic

    def spy_write(target, pieces, **kwargs):
        modes.append(kwargs.get("mode"))
        return real_write(target, pieces, **kwargs)

    monkeypatch.setattr(ks.safefile, "write_atomic", spy_write)
    spy = Spy(ks.ChildResult(1, b"", stderr))
    store = store_with(ks.SecretToolBackend("/usr/bin/secret-tool", run=spy), user_dir)
    result = store.save(ANT, KEY)
    assert result.ok and result.where == ks.WHERE_FILE and result.text == ks.SAVED_FILE
    assert modes == [0o600] and files_in(user_dir) == [ANT.file_name]
    assert (user_dir / ANT.file_name).read_bytes() == KEY.encode()
    spy.answers = [ks.ChildResult(1, b"", stderr)]
    assert store.load(ANT).key.value == KEY
    # Remove clears both: the keyring entry and the file.
    spy.answers = [ks.ChildResult(0)]
    assert store.clear(ANT) == ks.KeyResult(True, ks.NO_KEY)
    assert spy.calls[-1][0][1] == "clear" and files_in(user_dir) == []
    assert redact.redact(KEY) == "<key>"                     # still a key shape
    assert "anthropic" not in redact._secrets


def test_ac_f48_33_no_keychain_at_all_and_a_link_at_the_files_name(user_dir, tmp_path):
    assert ks.detect_backend("linux", which=lambda *a, **k: None) is None
    assert ks.detect_backend("darwin", exists=lambda p: False) is None
    assert isinstance(ks.detect_backend("darwin", exists=lambda p: p == "/usr/bin/security"),
                      ks.MacBackend)
    store = store_with(None, user_dir)
    assert store.save(ANT, KEY).where == ks.WHERE_FILE
    assert store.clear(ANT).ok and files_in(user_dir) == []
    target = tmp_path / "elsewhere"
    target.mkdir()
    link_dir(user_dir / ANT.file_name, target)
    refused = store.save(ANT, KEY)
    assert not refused.ok and ks.R_FILE_LINK in refused.text
    assert os.listdir(target) == []
    assert not store.load(ANT).ok


def test_ac_f48_33_the_file_and_folder_must_be_owner_only_on_posix(user_dir, monkeypatch):
    """0600 in a 0700 folder: group or other bits on either are refused (POSIX rules, with
    the modes faked so the test runs on every OS)."""
    real_lstat = os.lstat
    modes = {user_dir: 0o40700}

    def fake_lstat(path, *args, **kwargs):
        st = real_lstat(path, *args, **kwargs)
        mode = modes.get(Path(path))
        return Patched(st, st_mode=mode) if mode is not None else st

    monkeypatch.setattr(ks.os, "lstat", fake_lstat)
    monkeypatch.setattr(ks.safefile, "is_regular", lambda st: stat.S_ISREG(st.st_mode))
    store = store_with(None, user_dir, posix=True)
    assert store.save(ANT, KEY).ok
    modes[user_dir / ANT.file_name] = 0o100600
    assert store.load(ANT).key.value == KEY
    modes[user_dir / ANT.file_name] = 0o100644
    assert ks.R_FILE_OPEN in store.load(ANT).text
    modes[user_dir] = 0o40755
    assert ks.R_FOLDER_OPEN in store.save(ANT, KEY).text
    assert ks.R_FOLDER_OPEN in store.load(ANT).text


def test_secret_tool_is_looked_up_in_fixed_folders_only():
    asked = []
    found = ks.find_secret_tool(lambda name, path: asked.append((name, path)) or
                                "/usr/bin/secret-tool")
    assert found == "/usr/bin/secret-tool"
    assert asked == [("secret-tool", os.pathsep.join(("/usr/bin", "/bin", "/usr/local/bin")))]
    assert ks.find_secret_tool(lambda name, path: "secret-tool") is None    # relative: no


def test_keystore_children_run_in_c_locale_without_key_variables(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("openai_api_key", OTHER)
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    seen = []

    def fake_run(argv, **kwargs):
        seen.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, b"out", b"")

    monkeypatch.setattr(ks.subprocess, "run", fake_run)
    assert ks.run_child(["/usr/bin/secret-tool", "store"], KEY) == ks.ChildResult(0, b"out")
    (argv, kwargs), = seen
    env = kwargs["env"]
    assert argv == ["/usr/bin/secret-tool", "store"] and kwargs["input"] == KEY.encode()
    assert kwargs["shell"] is False and kwargs["timeout"] == 15
    assert kwargs["cwd"] == str(engine_root())
    assert env["LC_ALL"] == "C" and env["LANG"] == "C"
    assert not {k.upper() for k in env} & procs.PROVIDER_KEY_VARS
    assert KEY not in env.values() and OTHER not in env.values()

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 15)

    monkeypatch.setattr(ks.subprocess, "run", timeout)
    assert ks.run_child(["x"]).timed_out


def test_a_read_failure_gives_the_read_text_and_a_bad_value_is_no_key(user_dir):
    spy = Spy(ks.ChildResult(1, b"", b"Cannot get secret of a locked object"),
              ks.ChildResult(0, "ключ".encode()))
    store = store_with(ks.SecretToolBackend("/usr/bin/secret-tool", run=spy), user_dir)
    failed = store.load(ANT)
    assert not failed.ok and failed.text == (
        "Couldn't read the key from your keychain: Cannot get secret of a locked object.")
    assert store.load(ANT).text == ks.READ_FAILED.format(reason=ks.R_NOT_A_KEY)


# --- AC-F48-60: environment-variable keys ------------------------------------------------------------

def test_ac_f48_60_an_environment_key_serves_only_its_own_provider():
    env = {"ANTHROPIC_API_KEY": KEY, "OPENAI_API_KEY": "bad key with spaces"}
    assert ks.env_variable(ks.ANTHROPIC, env) == "ANTHROPIC_API_KEY"
    assert ks.env_variable(ks.OPENAI, env) is None
    assert ks.env_variable(ks.COMPATIBLE, env) is None
    assert ks.ENV_OFFER.format(variable="ANTHROPIC_API_KEY") == (
        "Use the key from ANTHROPIC_API_KEY")
    key = ks.env_key(ks.ANTHROPIC, env)
    assert key.value == KEY and key.where == ks.WHERE_ENV
    assert key.origin == "https://api.anthropic.com:443"
    with pytest.raises(ks.KeyOriginError):
        key.check_origin("https://api.openai.com:443")
    assert redact.redact(f"x {KEY} y") == "x <key> y"
    assert ks.env_key(ks.OPENAI, env) is None
    assert ks.env_key(ks.COMPATIBLE, {"OPENAI_API_KEY": OTHER, "ANTHROPIC_API_KEY": KEY}) is None
    assert ks.env_key(ks.OPENAI, {"ANTHROPIC_API_KEY": KEY}) is None
    assert ks.env_key(ks.OPENAI, {"OPENAI_API_KEY": OTHER}).origin == (
        "https://api.openai.com:443")


def _names_and_calls(path: Path) -> tuple[set[str], set[str]]:
    strings, calls = set(), set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.add(node.value)
        if isinstance(node, ast.Attribute):
            calls.add(node.attr)
    return strings, calls


def test_key_variables_and_keychains_are_reached_only_from_keystore():
    """07 9(c), PR-F48-33: the key variables are named only in ``keystore.py`` (and
    ``procs.PROVIDER_KEY_VARS``, which drops them), and the keychain programs and
    ``Cred*`` functions only in ``keystore.py``."""
    variables = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}
    keychain = {"advapi32", "/usr/bin/security", "secret-tool", "CredWriteW", "CredReadW",
                "CredDeleteW", "CredFree"}
    found: dict[str, set[str]] = {}
    for path in sorted(ENGINE.rglob("*.py")):
        strings, attrs = _names_and_calls(path)
        hits = {s for s in strings for name in variables | keychain if name in s
                and (name in variables or s == name or s.startswith(name))}
        hits |= attrs & keychain
        if hits:
            found[path.relative_to(ENGINE).as_posix()] = hits
    assert set(found) <= {"tools/assistant/keystore.py", "tools/build/procs.py"}
    assert found.get("tools/build/procs.py", set()) <= variables


@pytest.mark.manual
@pytest.mark.skipif(sys.platform != "win32" or os.environ.get("VN_KEYCHAIN") != "1",
                    reason="the real Credential Manager: set VN_KEYCHAIN=1 on Windows")
def test_manual_windows_credential_manager_round_trip():
    slot = ks.slot_for(ks.COMPATIBLE, "http://localhost:59999")
    store = ks.KeyStore(ks.WindowsBackend())
    try:
        assert store.save(slot, KEY).ok
        assert store.load(slot).key.value == KEY
    finally:
        assert store.clear(slot).ok
    assert store.load(slot).key is None

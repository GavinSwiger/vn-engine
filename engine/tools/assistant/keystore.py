"""Where Studio keeps the author's API keys (F48 ``04-technical.md`` §7.5; ``05-security.md``
SEC-F48-13, -14, -15 as amended in §10, -16; ``01-design.md`` §6.2, PR-F48-16, -17, -33).

Why this module exists: a key is money. It must live in the OS keychain, reach nothing a
program or a person could read by accident, and go only to the place it was saved for. This
is the one module that touches a keychain or reads the key variables (07 9(c)).

- **Shape** (SEC-F48-13 (a)): ``check_key`` strips surrounding whitespace and accepts 8–512
  printable ASCII characters with no space, quote, backslash or control character, so a key
  can't inject a header line or break the macOS ``security -i`` command. A paste is read at
  most ``PASTE_MAX_CHARS``.
- **Slots** (SEC-F48-16): ``anthropic`` and ``openai`` are bound to their fixed origins;
  ``compatible <origin>`` to the exact origin (``scheme://host:port``) it was saved for.
  ``BoundKey`` carries the value with its provider and origin; its ``repr`` shows only the
  last 4 characters, and ``check_origin`` refuses any other origin.
- **Backends** (SEC-F48-15): Windows Credential Manager through ``ctypes`` (``advapi32``
  from System32 only, typed ``CredWriteW``/``CredReadW``/``CredDeleteW``/``CredFree``,
  ``CRED_TYPE_GENERIC``, ``CRED_PERSIST_LOCAL_MACHINE``); macOS ``/usr/bin/security`` (the
  key on stdin to ``security -i``, never in argv); Linux ``secret-tool`` found in fixed
  folders (the key on stdin). Every child gets a list argv, no shell, ``cwd=engine_root()``,
  ``procs.without_keys()`` with ``LC_ALL=C`` and ``LANG=C``, 15 s, stdout ≤ 4 KiB, and its
  stderr becomes an ``echo``-ed reason.
- **No keychain** (SEC-F48-15 (e), 05 §10): only Linux without ``secret-tool``, Linux whose
  ``secret-tool`` exits nonzero with empty stdout and a D-Bus "no service" marker on stderr,
  or macOS without ``/usr/bin/security``. Then, and only then, ``FileStore`` keeps the key in
  ``studio_user_dir(local=True)/key-<16 hex>.txt`` (0600 in a 0700 folder; a link, or group
  or other bits, refused). A timeout, a locked keyring or a denied prompt is a failure:
  §6.2's refused text, nothing saved.
- **Redaction** (SEC-F48-14, amended): each key is registered with ``redact.set_secret``
  before the first keystore child that receives it, and when it is loaded; Remove clears it.
- ``env_key`` (PR-F48-33): ``ANTHROPIC_API_KEY``/``OPENAI_API_KEY``, each for its own
  provider only. Read nowhere else in the engine.

No logging here: nothing about a key is worth a log line.
"""

import ctypes
import hashlib
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from engine.core import safefile
from engine.core.paths import engine_root, studio_user_dir
from engine.core.redact import echo, set_secret
from engine.tools.build.procs import without_keys

# --- Providers, slots and the shape rule -------------------------------------------------------

ANTHROPIC: Final = "anthropic"
OPENAI: Final = "openai"
COMPATIBLE: Final = "compatible"
PROVIDERS: Final = (ANTHROPIC, OPENAI, COMPATIBLE)
FIXED_ORIGINS: Final = {ANTHROPIC: "https://api.anthropic.com:443",
                        OPENAI: "https://api.openai.com:443"}
ENV_VARS: Final = {ANTHROPIC: "ANTHROPIC_API_KEY", OPENAI: "OPENAI_API_KEY"}

KEY_MIN_CHARS: Final = 8
KEY_MAX_CHARS: Final = 512
PASTE_MAX_CHARS: Final = 4096           # SEC-F48-13 (a): the clipboard is read at most 4 KiB
ORIGIN_MAX_CHARS: Final = 300
_KEY_BANNED: Final = frozenset(" \"'\\`")

SERVICE: Final = "vn-engine-studio"     # keychain service; Windows targets are SERVICE/<slot>
CHILD_TIMEOUT_S: Final = 15
CHILD_STDOUT_MAX: Final = 4096
FILE_MAX_BYTES: Final = 4096
FILE_MODE: Final = 0o600
BLOB_MAX_BYTES: Final = 2560            # CRED_MAX_CREDENTIAL_BLOB_SIZE

WHERE_KEYCHAIN: Final = "keychain"
WHERE_FILE: Final = "file"
WHERE_ENV: Final = "environment"

# §6.2 texts.
SAVED_WINDOWS: Final = "Saved in Windows Credential Manager."
SAVED_MACOS: Final = "Saved in your macOS Keychain."
SAVED_KEYRING: Final = "Saved in your system keyring."
SAVED_FILE: Final = ("Saved in a file in your user folder, because this computer has no "
                     "keyring.")
NO_KEY: Final = "No key saved."
NO_KEY_FOR: Final = "No key saved for {origin}."
BAD_SHAPE: Final = "Couldn't save the key: it has characters an API key can't have."
SAVE_FAILED: Final = "Your keychain didn't save the key: {reason}. Nothing was saved."
READ_FAILED: Final = "Couldn't read the key from your keychain: {reason}."
REMOVE_FAILED: Final = "Couldn't remove the key from your keychain: {reason}."  # 04 delta
ENV_OFFER: Final = "Use the key from {variable}"                                # PR-F48-33

# Reasons (each shown inside one of the texts above).
R_TIMEOUT: Final = "it didn't answer within 15 seconds"
R_TOO_MUCH: Final = "it answered with too much text"
R_NOT_A_KEY: Final = "the saved value isn't an API key"
R_NO_FOLDER: Final = "this computer has no keyring and Studio's user folder can't be used"
R_FOLDER_OPEN: Final = "Studio's user folder can be read by other users"
R_FILE_LINK: Final = "something other than a plain file is at the key file's name"
R_FILE_OPEN: Final = "the key file can be read by other users"
R_FILE_FAILED: Final = "the key file couldn't be written"
R_FILE_UNREADABLE: Final = "the key file couldn't be read"
R_NOT_SAVED: Final = "it didn't keep the key"

# 05 §10: Linux "no Secret Service" markers (stable under LC_ALL=C).
NO_SERVICE_MARKERS: Final = ("org.freedesktop.DBus.Error.ServiceUnknown",
                             "Cannot autolaunch", "Could not connect")
SECRET_TOOL_DIRS: Final = ("/usr/bin", "/bin", "/usr/local/bin")
SECURITY_PATH: Final = "/usr/bin/security"
MAC_NOT_FOUND: Final = 44               # errSecItemNotFound as security's exit status


class KeyOriginError(ValueError):
    """A key was about to go to an origin other than the one it was saved for (SEC-F48-16)."""


def check_key(text: object) -> str | None:
    """The key in ``text`` with surrounding whitespace removed, or None when it isn't one:
    8–512 printable ASCII characters, no space, quote, backtick or backslash (SEC-F48-13 (a)).
    A text over ``PASTE_MAX_CHARS`` is refused before it is looked at."""
    if type(text) is not str or len(text) > PASTE_MAX_CHARS:
        return None
    key = text.strip(" \t\r\n")
    if not KEY_MIN_CHARS <= len(key) <= KEY_MAX_CHARS:
        return None
    if any(not "\x21" <= char <= "\x7e" or char in _KEY_BANNED for char in key):
        return None
    return key


def origin_ok(origin: object) -> bool:
    """``scheme://host:port`` as the transport writes an origin: http(s), an ASCII host name,
    a dotted IPv4 literal or a bracketed IPv6 literal, and a port 1–65535."""
    if type(origin) is not str or len(origin) > ORIGIN_MAX_CHARS:
        return False
    scheme, sep, rest = origin.partition("://")
    if not sep or scheme not in ("http", "https"):
        return False
    host, colon, port = rest.rpartition(":")
    if not colon or not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535 \
            or len(port) > 5:
        return False
    if host.startswith("[") and host.endswith("]"):
        inner = host[1:-1]
        return bool(inner) and all(c in "0123456789abcdefABCDEF:." for c in inner)
    return bool(host) and host.isascii() and all(
        c.isalnum() or c in ".-" for c in host) and not host.startswith((".", "-"))


@dataclass(frozen=True)
class Slot:
    """One saved key's place: a provider and the origin it is bound to."""

    provider: str
    origin: str

    @property
    def name(self) -> str:
        """``anthropic``, ``openai`` or ``compatible <origin>`` (the redactor slot too)."""
        return self.provider if self.provider != COMPATIBLE else f"{COMPATIBLE} {self.origin}"

    @property
    def target(self) -> str:
        """The Windows Credential Manager target name."""
        return f"{SERVICE}/{self.name}"

    @property
    def file_name(self) -> str:
        """The fallback file's name (ADR-0003: ``key-<16 hex>.txt``)."""
        digest = hashlib.sha256(self.name.encode("utf-8")).hexdigest()[:16]
        return f"key-{digest}.txt"


def slot_for(provider: str, origin: str | None = None) -> Slot:
    """The slot for ``provider``. Anthropic and OpenAI always use their fixed origin (a given
    ``origin`` is ignored, so an address change can't carry their key); a compatible server
    needs its ``origin``. ``ValueError`` for an unknown provider or a malformed origin."""
    if provider in FIXED_ORIGINS:
        return Slot(provider, FIXED_ORIGINS[provider])
    if provider != COMPATIBLE:
        raise ValueError("unknown provider")
    if not origin_ok(origin):
        raise ValueError("a compatible server's origin is scheme://host:port")
    return Slot(COMPATIBLE, origin)                                     # type: ignore[arg-type]


@dataclass(frozen=True, repr=False)
class BoundKey:
    """A key with the provider and origin it was saved for (SEC-F48-16). Only ``last4``
    ever shows: ``repr`` and ``str`` hide the rest."""

    value: str
    provider: str
    origin: str
    where: str = WHERE_KEYCHAIN         # WHERE_KEYCHAIN, WHERE_FILE or WHERE_ENV

    @property
    def last4(self) -> str:
        return self.value[-4:]

    @property
    def masked(self) -> str:
        """§6.2's field: dots, then the last 4 characters."""
        return "•" * 14 + " " + self.last4

    def check_origin(self, origin: str) -> str:
        """The value, for a request to ``origin``; ``KeyOriginError`` for any other origin."""
        if origin != self.origin:
            raise KeyOriginError("this key was saved for another server")
        return self.value

    def __repr__(self) -> str:
        return (f"BoundKey(provider={self.provider!r}, origin={self.origin!r}, "
                f"key='…{self.last4}', where={self.where!r})")

    __str__ = __repr__


def _register(slot_name: str, value: str | None) -> None:
    """``redact.set_secret``; keys always pass ``check_key``, so never under 8 characters."""
    set_secret(slot_name, value)


# --- Children ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class ChildResult:
    """A keystore child's end: exit ``code`` (None when it didn't run or timed out)."""

    code: int | None
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False
    error: str | None = None            # why it didn't start


def child_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """``procs.without_keys`` plus ``LC_ALL=C`` and ``LANG=C`` (05 §10: stable markers)."""
    env = without_keys(base)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    return env


def run_child(argv: Sequence[str], stdin_text: str = "") -> ChildResult:
    """Run one keystore child (SEC-F48-15 (d)): ``stdin_text`` is the only way a key reaches
    it."""
    try:
        done = subprocess.run([str(part) for part in argv], input=stdin_text.encode("ascii"),
                              capture_output=True, cwd=str(engine_root()), env=child_env(),
                              timeout=CHILD_TIMEOUT_S, shell=False)
    except subprocess.TimeoutExpired:
        return ChildResult(None, timed_out=True)
    except (OSError, ValueError) as exc:
        return ChildResult(None, error=getattr(exc, "strerror", None) or type(exc).__name__)
    return ChildResult(done.returncode, done.stdout or b"", done.stderr or b"")


Runner = Callable[[Sequence[str], str], ChildResult]


def _reason(result: ChildResult) -> str:
    """Why a child failed, as one redacted, escaped line (the key is registered by now)."""
    if result.timed_out:
        return R_TIMEOUT
    if result.error is not None:
        return echo(result.error, 200)
    lines = [line.strip() for line in result.stderr.decode("utf-8", "replace").splitlines()]
    text = next((line for line in lines if line), "")
    if text:
        return echo(text, 200)
    return f"it stopped with exit status {result.code}"


def _no_service(result: ChildResult) -> bool:
    """05 §10: "no keychain" only on a nonzero exit, empty stdout and a D-Bus marker."""
    if result.timed_out or result.code in (None, 0) or result.stdout.strip():
        return False
    stderr = result.stderr.decode("utf-8", "replace")
    return any(marker in stderr for marker in NO_SERVICE_MARKERS)


# --- Backend outcomes -------------------------------------------------------------------------

OK: Final = "ok"
NOT_FOUND: Final = "not found"
NO_KEYCHAIN: Final = "no keychain"
FAILED: Final = "failed"


@dataclass(frozen=True)
class Outcome:
    kind: str                           # OK, NOT_FOUND, NO_KEYCHAIN, FAILED
    value: str | None = None            # read: the key
    reason: str = ""                    # FAILED: shown inside §6.2's text


def _key_outcome(raw: bytes) -> Outcome:
    """A read value → OK with the key, or FAILED when it isn't a key."""
    if len(raw) > CHILD_STDOUT_MAX:
        return Outcome(FAILED, reason=R_TOO_MUCH)
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return Outcome(FAILED, reason=R_NOT_A_KEY)
    key = check_key(text)
    return Outcome(OK, key) if key is not None else Outcome(FAILED, reason=R_NOT_A_KEY)


class SecretToolBackend:
    """Linux Secret Service through ``secret-tool`` (SEC-F48-15 (c))."""

    saved_text = SAVED_KEYRING

    def __init__(self, path: str, *, run: Runner = run_child) -> None:
        self.path = path
        self._run = run

    def _attrs(self, slot: Slot) -> list[str]:
        return ["service", SERVICE, "account", slot.name]

    def _failure(self, result: ChildResult) -> Outcome:
        if _no_service(result):
            return Outcome(NO_KEYCHAIN)
        return Outcome(FAILED, reason=_reason(result))

    def write(self, slot: Slot, key: str) -> Outcome:
        result = self._run([self.path, "store", "--label=vn-engine Studio API key",
                            *self._attrs(slot)], key)
        return Outcome(OK) if result.code == 0 else self._failure(result)

    def read(self, slot: Slot) -> Outcome:
        result = self._run([self.path, "lookup", *self._attrs(slot)], "")
        if result.code == 0:
            return _key_outcome(result.stdout.strip())
        if (result.code == 1 and not result.stdout.strip() and not result.stderr.strip()):
            return Outcome(NOT_FOUND)                    # lookup's "no such item"
        return self._failure(result)

    def delete(self, slot: Slot) -> Outcome:
        result = self._run([self.path, "clear", *self._attrs(slot)], "")
        if result.code == 0:
            return Outcome(OK)
        if result.code == 1 and not result.stderr.strip():
            return Outcome(NOT_FOUND)
        return self._failure(result)


class MacBackend:
    """macOS Keychain through ``/usr/bin/security`` (SEC-F48-15 (b)). Writes go through
    ``security -i`` with the command on stdin, so the key is never in argv; a write is read
    back before it counts."""

    saved_text = SAVED_MACOS

    def __init__(self, path: str = SECURITY_PATH, *, run: Runner = run_child) -> None:
        self.path = path
        self._run = run

    def write(self, slot: Slot, key: str) -> Outcome:
        # The shape rule keeps quotes, backslashes and spaces out of the key; an origin has
        # none either, so double quotes are enough for ``security -i``'s line parser.
        command = (f'add-generic-password -U -s "{SERVICE}" -a "{slot.name}" '
                   f'-w "{key}"\n')
        result = self._run([self.path, "-i"], command)
        if result.code != 0 or result.stderr.strip():
            return Outcome(FAILED, reason=_reason(result))
        back = self.read(slot)
        if back.kind != OK or back.value != key:
            return Outcome(FAILED, reason=back.reason or R_NOT_SAVED)
        return Outcome(OK)

    def read(self, slot: Slot) -> Outcome:
        result = self._run([self.path, "find-generic-password", "-s", SERVICE,
                            "-a", slot.name, "-w"], "")
        if result.code == 0:
            return _key_outcome(result.stdout.strip())
        if result.code == MAC_NOT_FOUND:
            return Outcome(NOT_FOUND)
        return Outcome(FAILED, reason=_reason(result))

    def delete(self, slot: Slot) -> Outcome:
        result = self._run([self.path, "delete-generic-password", "-s", SERVICE,
                            "-a", slot.name], "")
        if result.code == 0:
            return Outcome(OK)
        if result.code == MAC_NOT_FOUND:
            return Outcome(NOT_FOUND)
        return Outcome(FAILED, reason=_reason(result))


# --- Windows Credential Manager (SEC-F48-15 (a); SEC-F01-18) -----------------------------------

LOAD_LIBRARY_SEARCH_SYSTEM32: Final = 0x00000800
CRED_TYPE_GENERIC: Final = 1
CRED_PERSIST_LOCAL_MACHINE: Final = 2
ERROR_NOT_FOUND: Final = 1168
_DWORD = ctypes.c_uint32


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", _DWORD), ("dwHighDateTime", _DWORD)]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [("Flags", _DWORD), ("Type", _DWORD), ("TargetName", ctypes.c_wchar_p),
                ("Comment", ctypes.c_wchar_p), ("LastWritten", FILETIME),
                ("CredentialBlobSize", _DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", _DWORD), ("AttributeCount", _DWORD),
                ("Attributes", ctypes.c_void_p), ("TargetAlias", ctypes.c_wchar_p),
                ("UserName", ctypes.c_wchar_p)]


def load_advapi32():
    """``advapi32`` from System32 only, never by the default search order (SEC-F01-18)."""
    return ctypes.WinDLL("advapi32", use_last_error=True,      # type: ignore[attr-defined]
                         winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)


def _windows_error(code: int) -> str:
    formatter = getattr(ctypes, "FormatError", None)
    text = ""
    if formatter is not None:
        try:
            text = formatter(code).strip()
        except (OSError, ValueError):
            text = ""
    return echo(f"{text} (error {code})" if text else f"Windows error {code}", 200)


class WindowsBackend:
    """Windows Credential Manager: generic credentials, persisted on this computer only
    (``CRED_PERSIST_LOCAL_MACHINE``; ``ENTERPRISE`` would roam). The four functions have
    their ``argtypes`` and ``restype`` declared before any call, and ``CredFree`` follows
    every successful read."""

    saved_text = SAVED_WINDOWS

    def __init__(self, *, load: Callable[[], object] = load_advapi32,
                 last_error: Callable[[], int] | None = None) -> None:
        self._load = load
        self._last_error = last_error if last_error is not None else (
            getattr(ctypes, "get_last_error", lambda: 0))
        self._api: dict[str, Callable] | None = None

    def _functions(self) -> dict[str, Callable]:
        if self._api is None:
            dll = self._load()
            pointer = ctypes.POINTER(CREDENTIALW)
            signatures = {
                "CredWriteW": ([pointer, _DWORD], ctypes.c_int),
                "CredReadW": ([ctypes.c_wchar_p, _DWORD, _DWORD, ctypes.POINTER(pointer)],
                              ctypes.c_int),
                "CredDeleteW": ([ctypes.c_wchar_p, _DWORD, _DWORD], ctypes.c_int),
                "CredFree": ([ctypes.c_void_p], None)}
            api = {}
            for name, (argtypes, restype) in signatures.items():
                function = getattr(dll, name)
                function.argtypes = argtypes
                function.restype = restype
                api[name] = function
            self._api = api
        return self._api

    def _call(self, action: Callable[[dict[str, Callable]], Outcome]) -> Outcome:
        try:
            return action(self._functions())
        except (OSError, AttributeError, ValueError, TypeError) as exc:
            return Outcome(FAILED, reason=echo(type(exc).__name__, 200))

    def write(self, slot: Slot, key: str) -> Outcome:
        def action(api: dict[str, Callable]) -> Outcome:
            blob = key.encode("ascii")
            buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
            cred = CREDENTIALW()
            cred.Type = CRED_TYPE_GENERIC
            cred.TargetName = slot.target
            cred.CredentialBlobSize = len(blob)
            cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
            cred.Persist = CRED_PERSIST_LOCAL_MACHINE
            cred.UserName = SERVICE
            try:
                ok = api["CredWriteW"](ctypes.byref(cred), 0)
            finally:
                ctypes.memset(buffer, 0, len(blob))
            if not ok:
                return Outcome(FAILED, reason=_windows_error(self._last_error()))
            return Outcome(OK)
        return self._call(action)

    def read(self, slot: Slot) -> Outcome:
        def action(api: dict[str, Callable]) -> Outcome:
            found = ctypes.POINTER(CREDENTIALW)()
            if not api["CredReadW"](slot.target, CRED_TYPE_GENERIC, 0, ctypes.byref(found)):
                code = self._last_error()
                if code == ERROR_NOT_FOUND:
                    return Outcome(NOT_FOUND)
                return Outcome(FAILED, reason=_windows_error(code))
            try:
                size = int(found.contents.CredentialBlobSize)
                if size > BLOB_MAX_BYTES:
                    return Outcome(FAILED, reason=R_TOO_MUCH)
                raw = ctypes.string_at(found.contents.CredentialBlob, size) if size else b""
            finally:
                api["CredFree"](found)
            return _key_outcome(raw)
        return self._call(action)

    def delete(self, slot: Slot) -> Outcome:
        def action(api: dict[str, Callable]) -> Outcome:
            if api["CredDeleteW"](slot.target, CRED_TYPE_GENERIC, 0):
                return Outcome(OK)
            code = self._last_error()
            if code == ERROR_NOT_FOUND:
                return Outcome(NOT_FOUND)
            return Outcome(FAILED, reason=_windows_error(code))
        return self._call(action)


Backend = SecretToolBackend | MacBackend | WindowsBackend


def find_secret_tool(which: Callable[..., str | None] = shutil.which) -> str | None:
    """``secret-tool`` in ``SECRET_TOOL_DIRS`` only (never the inherited ``PATH``)."""
    found = which("secret-tool", path=os.pathsep.join(SECRET_TOOL_DIRS))
    return found if found and os.path.isabs(found) else None


def detect_backend(platform: str = sys.platform, *, run: Runner = run_child,
                   which: Callable[..., str | None] = shutil.which,
                   exists: Callable[[str], bool] = os.path.isfile) -> Backend | None:
    """This computer's keychain, or None when it has none (SEC-F48-15 (e))."""
    if platform == "win32":
        return WindowsBackend()
    if platform == "darwin":
        return MacBackend(run=run) if exists(SECURITY_PATH) else None
    path = find_secret_tool(which)
    return SecretToolBackend(path, run=run) if path is not None else None


# --- The fallback file (SEC-F48-15 (f)) ----------------------------------------------------------

class FileStore:
    """``key-<16 hex>.txt`` in the non-roaming Studio folder, for a computer with no keychain.
    POSIX: the folder must have no group or other bits, the file is written 0600, and a file
    with group or other bits is refused. Everywhere: a link or any non-regular entry at the
    name is refused, never followed."""

    def __init__(self, *, folder: Callable[[], Path | None] | None = None,
                 posix: bool = safefile.IS_POSIX) -> None:
        self._folder = folder if folder is not None else (lambda: studio_user_dir(local=True))
        self.posix = posix

    def _place(self, slot: Slot) -> tuple[Path | None, str]:
        folder = self._folder()
        if folder is None:
            return None, R_NO_FOLDER
        if self.posix:
            try:
                if stat.S_IMODE(os.lstat(folder).st_mode) & 0o077:
                    return None, R_FOLDER_OPEN
            except OSError:
                return None, R_NO_FOLDER
        return Path(folder) / slot.file_name, ""

    def _entry_problem(self, path: Path) -> str | None:
        """None when ``path`` is missing or a private regular file; else the reason."""
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            return None
        except OSError:
            return R_FILE_UNREADABLE
        if not safefile.is_regular(st):
            return R_FILE_LINK
        if self.posix and stat.S_IMODE(st.st_mode) & 0o077:
            return R_FILE_OPEN
        return None

    def write(self, slot: Slot, key: str) -> Outcome:
        path, why = self._place(slot)
        if path is None:
            return Outcome(FAILED, reason=why)
        problem = self._entry_problem(path)
        if problem is not None:
            return Outcome(FAILED, reason=problem)
        try:
            safefile.write_atomic(path, [key.encode("ascii")], mode=FILE_MODE)
        except OSError:
            return Outcome(FAILED, reason=R_FILE_FAILED)
        return Outcome(OK)

    def read(self, slot: Slot) -> Outcome:
        path, why = self._place(slot)
        if path is None:
            return Outcome(FAILED, reason=why)
        problem = self._entry_problem(path)
        if problem is not None:
            return Outcome(FAILED, reason=problem)
        result = safefile.read_regular(path, FILE_MAX_BYTES)
        if result.kind is safefile.ReadKind.MISSING:
            return Outcome(NOT_FOUND)
        if result.kind is safefile.ReadKind.NOT_REGULAR:
            return Outcome(FAILED, reason=R_FILE_LINK)
        if not result.ok or result.data is None:
            return Outcome(FAILED, reason=R_FILE_UNREADABLE)
        return _key_outcome(result.data.strip())

    def delete(self, slot: Slot) -> Outcome:
        folder = self._folder()
        if folder is None:
            return Outcome(NOT_FOUND)
        removed = safefile.remove_file(Path(folder) / slot.file_name)
        if removed is safefile.RemoveKind.REMOVED:
            return Outcome(OK)
        if removed is safefile.RemoveKind.MISSING:
            return Outcome(NOT_FOUND)
        return Outcome(FAILED, reason=removed.value)


# --- The store ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class KeyResult:
    """What a save, load or clear did. ``text`` is the settings page's status line (§6.2):
    where the key is saved, "No key saved.", or a refused/failed text. ``key`` only when a key
    is in hand; ``where`` is ``WHERE_KEYCHAIN``, ``WHERE_FILE`` or None."""

    ok: bool
    text: str
    key: BoundKey | None = None
    where: str | None = None


def no_key_text(slot: Slot) -> str:
    """§6.2: "No key saved." (compatible: "No key saved for {origin}.")."""
    if slot.provider == COMPATIBLE:
        return NO_KEY_FOR.format(origin=echo(slot.origin, 200))
    return NO_KEY


class KeyStore:
    """Save, load and remove keys per slot. ``backend`` None means this computer has no
    keychain, and only then is ``files`` used (``detect_backend`` decides; tests pass fakes).
    """

    def __init__(self, backend: Backend | None, files: FileStore | None = None) -> None:
        self.backend = backend
        self.files = files if files is not None else FileStore()

    @classmethod
    def default(cls) -> "KeyStore":
        return cls(detect_backend())

    @property
    def saved_text(self) -> str:
        return self.backend.saved_text if self.backend is not None else SAVED_FILE

    def _bound(self, slot: Slot, value: str, where: str) -> BoundKey:
        _register(slot.name, value)
        return BoundKey(value, slot.provider, slot.origin, where)

    def save(self, slot: Slot, text: str) -> KeyResult:
        """Check the shape, register the key with the redactor, then store it: the keychain,
        or the file only when there is no keychain. A refused or failed save keeps nothing.
        """
        key = check_key(text)
        if key is None:
            return KeyResult(False, BAD_SHAPE)
        pending = slot.name + " (saving)"
        _register(pending, key)                    # before any child sees it (05 §10)
        where = WHERE_KEYCHAIN
        outcome = (self.backend.write(slot, key) if self.backend is not None
                   else Outcome(NO_KEYCHAIN))
        if outcome.kind == NO_KEYCHAIN:
            where = WHERE_FILE
            outcome = self.files.write(slot, key)
        if outcome.kind != OK:
            return KeyResult(False, SAVE_FAILED.format(reason=outcome.reason or R_NOT_SAVED))
        if where == WHERE_KEYCHAIN:
            self.files.delete(slot)                # no stale copy in a file
        bound = self._bound(slot, key, where)
        _register(pending, None)
        text_out = self.saved_text if where == WHERE_KEYCHAIN else SAVED_FILE
        return KeyResult(True, text_out, bound, where)

    def load(self, slot: Slot) -> KeyResult:
        """The saved key for ``slot`` (registered with the redactor), or none; a key deleted
        outside Studio is simply no key (01 §4.4)."""
        where = WHERE_KEYCHAIN
        outcome = self.backend.read(slot) if self.backend is not None else Outcome(NO_KEYCHAIN)
        if outcome.kind == NO_KEYCHAIN:
            where = WHERE_FILE
            outcome = self.files.read(slot)
        if outcome.kind == NOT_FOUND:
            return KeyResult(True, no_key_text(slot))
        if outcome.kind != OK or outcome.value is None:
            return KeyResult(False, READ_FAILED.format(reason=outcome.reason or R_NOT_A_KEY))
        text_out = self.saved_text if where == WHERE_KEYCHAIN else SAVED_FILE
        return KeyResult(True, text_out, self._bound(slot, outcome.value, where), where)

    def clear(self, slot: Slot) -> KeyResult:
        """**Remove**: the keychain entry and any fallback file (SEC-F48-15 (g)); the
        redactor forgets the key."""
        reasons = []
        if self.backend is not None:
            outcome = self.backend.delete(slot)
            if outcome.kind == FAILED:
                reasons.append(outcome.reason)
        outcome = self.files.delete(slot)
        if outcome.kind == FAILED:
            reasons.append(outcome.reason)
        _register(slot.name, None)
        if reasons:
            return KeyResult(False, REMOVE_FAILED.format(reason=reasons[0]))
        return KeyResult(True, no_key_text(slot))


# --- Environment variables (PR-F48-33) -------------------------------------------------------------

def env_variable(provider: str, environ: Mapping[str, str] | None = None) -> str | None:
    """The variable's name when it holds a key for ``provider`` (Anthropic or OpenAI only),
    for §6.2's "Use the key from {VARIABLE}" offer; else None."""
    name = ENV_VARS.get(provider)
    if name is None:
        return None
    source = os.environ if environ is None else environ
    return name if check_key(source.get(name, "")) is not None else None


def env_key(provider: str, environ: Mapping[str, str] | None = None) -> BoundKey | None:
    """The key from ``ANTHROPIC_API_KEY``/``OPENAI_API_KEY``, bound to that provider's own
    origin only (SEC-F48-16), and registered with the redactor; None when unset or not a
    key. A compatible server never gets one."""
    name = ENV_VARS.get(provider)
    if name is None:
        return None
    source = os.environ if environ is None else environ
    key = check_key(source.get(name, ""))
    if key is None:
        return None
    _register(f"{provider} {WHERE_ENV}", key)
    return BoundKey(key, provider, FIXED_ORIGINS[provider], WHERE_ENV)


__all__ = ["ANTHROPIC", "BAD_SHAPE", "BoundKey", "COMPATIBLE", "CREDENTIALW",
           "CRED_PERSIST_LOCAL_MACHINE", "CRED_TYPE_GENERIC", "ChildResult", "ENV_OFFER",
           "ENV_VARS", "FIXED_ORIGINS", "FileStore", "KeyOriginError",
           "KeyResult", "KeyStore", "MacBackend", "NO_KEY", "NO_KEY_FOR",
           "NO_SERVICE_MARKERS", "OPENAI", "Outcome", "PASTE_MAX_CHARS", "PROVIDERS",
           "READ_FAILED", "REMOVE_FAILED", "SAVED_FILE", "SAVED_KEYRING", "SAVED_MACOS",
           "SAVED_WINDOWS", "SAVE_FAILED", "SERVICE", "SecretToolBackend", "Slot",
           "WHERE_ENV", "WHERE_FILE", "WHERE_KEYCHAIN", "WindowsBackend", "check_key",
           "child_env", "detect_backend", "env_key", "env_variable", "find_secret_tool",
           "load_advapi32", "no_key_text", "origin_ok", "run_child", "slot_for"]

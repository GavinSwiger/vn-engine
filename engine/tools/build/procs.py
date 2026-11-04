"""Starting and stopping the build's children (F42 ``04-technical.md`` §3.1, §7.3, §8;
SEC-F42-04, -05, -09).

Why this module exists: the build runs three kinds of child (the check, PyInstaller, and
Studio's **Install build tool** pip run), and each must start the same safe way: from an
argument list (no shell), in ``engine_root()`` (never the game folder or *Save to*, so no
planted ``pip/`` or ``json.py`` is imported), with ``PYTHON*`` variables removed. Cancel must
stop a child and everything it started. Shared by the build child and Studio (stdlib and
``core`` only).

- ``PYINSTALLER_VERSION``: the one pinned version (``requirements-build.txt``; a test ties
  them together).
- ``child_env()``: the environment without any ``PYTHON*`` variable or provider key
  (``PROVIDER_KEY_VARS``, F48 SEC-F48-22). ``without_keys()``: without the provider keys
  only (Studio's check, preview and helper children, which keep ``PYTHON*``).
- ``spawn(argv)``: ``Popen`` with the rules above; on Windows no console window
  (``CREATE_NO_WINDOW``), on POSIX a new session so ``kill_tree`` reaches grandchildren.
- ``kill_tree(proc)``: Windows ``%SystemRoot%\\System32\\taskkill.exe /T /F /PID``; POSIX
  ``killpg(SIGKILL)``. Then waits for the child. Never raises.
- ``tool_status()``: is the pinned PyInstaller installed? Read with ``importlib.metadata``;
  PyInstaller is never imported (SEC-F42-05). ``ToolStatus.key`` is None, ``B_NO_TOOL`` or
  ``B_TOOL_VERSION`` (values ``found``, ``wanted`` for the message's ``<x>``/``<y>``).
- ``install_argv()``: the only pip command (§8): ``-E -m pip install --require-hashes
  --only-binary=:all: --no-input --disable-pip-version-check -r <engine root>/
  requirements-build.txt``; no index or trusted-host option, never elevated.
- ``SPEC_DIR``, ``DIST_DIR``, ``WORK_DIR``: the packer's folders inside staging
  (``spec.packer_argv`` uses them).
- ``redacted_tail(lines, roots)``: the last 200 lines with every root replaced by its token,
  then the installed redactor, then controls escaped (``B_PACK_FAILED`` details, pip output).
  ``build_roots(save_to, staging)`` gives the build's extra roots (SEC-F42-09).
"""

import importlib.metadata
import os
import signal
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from engine.core.paths import engine_root
from engine.core.redact import RedactRoot, Redactor, escape_controls, redact

PYINSTALLER_VERSION: Final = "6.22.3"
PACKAGE: Final = "pyinstaller"
REQUIREMENTS: Final = "requirements-build.txt"
TAIL_LINES: Final = 200
KILL_WAIT_S: Final = 5.0
IS_WINDOWS: Final = os.name == "nt"

# Report tokens for the build's own folders (SEC-F42-09).
SAVE_TO_TOKEN: Final = "<save-to>"
STAGING_TOKEN: Final = "<staging>"
WORK_TOKEN: Final = "<work>"
WORK_DIR: Final = "work"                 # inside staging (spec, dist and work folders)
DIST_DIR: Final = "dist"
SPEC_DIR: Final = "spec"


# F48 (SEC-F48-22, 07 I-4): the AI providers' key variables. No child Studio or the build
# starts inherits them (compared in upper case: Windows names are case-insensitive), so a
# checked or previewed game's code can't read them. Defence in depth.
PROVIDER_KEY_VARS: Final = frozenset({"ANTHROPIC_API_KEY", "OPENAI_API_KEY"})


def without_keys(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """A copy of ``base`` (default ``os.environ``) without ``PROVIDER_KEY_VARS``, any case."""
    source = os.environ if base is None else base
    return {key: value for key, value in source.items()
            if key.upper() not in PROVIDER_KEY_VARS}


def child_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """A copy of ``base`` (default ``os.environ``) without ``PYTHON*`` keys or
    ``PROVIDER_KEY_VARS``, any case."""
    return {key: value for key, value in without_keys(base).items()
            if not key.upper().startswith("PYTHON")}


def spawn(argv: Sequence[str], *, popen: Callable[..., subprocess.Popen] = subprocess.Popen,
          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
          stderr=subprocess.STDOUT) -> subprocess.Popen:
    """Start ``argv`` (a list, no shell) in ``engine_root()`` with ``child_env()``."""
    kwargs: dict = {"cwd": str(engine_root()), "env": child_env(), "stdin": stdin,
                    "stdout": stdout, "stderr": stderr, "shell": False}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    return popen([str(part) for part in argv], **kwargs)


def taskkill_path() -> str:
    root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or r"C:\Windows"
    return os.path.join(root, "System32", "taskkill.exe")


def kill_tree(proc: subprocess.Popen, *,
              run: Callable[..., object] = subprocess.run) -> None:
    """Stop ``proc`` and every process it started, then wait for it (at most
    ``KILL_WAIT_S`` per step). Never raises."""
    if proc.poll() is None:
        try:
            if IS_WINDOWS:
                run([taskkill_path(), "/T", "/F", "/PID", str(proc.pid)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=KILL_WAIT_S,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        proc.wait(KILL_WAIT_S)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(KILL_WAIT_S)
        except (OSError, subprocess.SubprocessError):
            pass


@dataclass(frozen=True, slots=True)
class ToolStatus:
    key: str | None                  # None (ready), "B_NO_TOOL", "B_TOOL_VERSION"
    found: str | None = None         # the installed version, if any
    wanted: str = PYINSTALLER_VERSION

    @property
    def ok(self) -> bool:
        return self.key is None


def tool_status(*, version: Callable[[str], str] = importlib.metadata.version) -> ToolStatus:
    """Whether the pinned PyInstaller is installed for this interpreter (no import)."""
    try:
        found = version(PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        return ToolStatus("B_NO_TOOL")
    except Exception:                  # a damaged installation counts as missing
        return ToolStatus("B_NO_TOOL")
    if found != PYINSTALLER_VERSION:
        return ToolStatus("B_TOOL_VERSION", found)
    return ToolStatus(None, found)


def requirements_path() -> Path:
    return engine_root() / REQUIREMENTS


def install_argv() -> list[str]:
    return [sys.executable, "-E", "-m", "pip", "install", "--require-hashes",
            "--only-binary=:all:", "--no-input", "--disable-pip-version-check",
            "-r", str(requirements_path())]


def build_roots(save_to: Path, staging: Path) -> list[RedactRoot]:
    """The build's own folders as redaction roots (the longest wins in ``Redactor``)."""
    staging = Path(staging)
    return [RedactRoot(SAVE_TO_TOKEN, str(save_to)), RedactRoot(STAGING_TOKEN, str(staging)),
            RedactRoot(WORK_TOKEN, str(staging / WORK_DIR))]


def redacted_tail(lines: Iterable[str], roots: Sequence[RedactRoot],
                  limit: int = TAIL_LINES) -> list[str]:
    """The last ``limit`` lines, each with ``roots`` replaced (the caller passes every root
    it knows: logsetup's and ``build_roots``), then ``redact()``, then controls escaped."""
    tail = list(lines)[-limit:] if limit > 0 else []
    own = Redactor(roots, home_name=None, case_insensitive=sys.platform in ("win32", "darwin"))
    return [escape_controls(redact(own(line.rstrip("\r\n")))) for line in tail]


__all__ = ["DIST_DIR", "PROVIDER_KEY_VARS", "PYINSTALLER_VERSION", "REQUIREMENTS",
           "SAVE_TO_TOKEN", "SPEC_DIR", "STAGING_TOKEN", "TAIL_LINES", "ToolStatus", "WORK_DIR",
           "WORK_TOKEN", "build_roots", "child_env", "install_argv", "kill_tree",
           "redacted_tail", "requirements_path", "spawn", "taskkill_path", "tool_status",
           "without_keys"]

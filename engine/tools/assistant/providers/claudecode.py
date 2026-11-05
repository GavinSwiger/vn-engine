"""The pane on the author's own Claude Code (provider ``claude_code``): each Send runs the
installed ``claude`` program headless, signed in with the author's Claude plan.

Why this module exists: a Claude Pro or Max plan can't be used by a third-party app's own
requests, but the author's own Claude Code can do the work and show it in the pane. Studio
never sees the login: Claude Code keeps it. For each Send:

- ``LocalMcp``: the pane's tools (``ToolBox`` in ``MODE_PANE`` over the run's snapshot, so
  ``propose_edit`` makes a card and nothing is written) served as MCP over HTTP on 127.0.0.1,
  on a free port, for this run only. Every request must carry the run's random bearer token
  and a loopback Host header (no DNS rebinding); a body is capped as the stdio server's line.
- ``ClaudeCodeRun``: ``ChatRun``'s events and ending, with the model loop replaced by one
  ``claude -p`` child: the prompt on stdin (never on the command line), stream-json on
  stdout, only this run's server (``--strict-mcp-config``), no built-in tools (``--tools
  ""``), and the chat's Claude Code session resumed on later Sends. The API key variables
  (``keystore.ENV_VARS``) and ``ANTHROPIC_AUTH_TOKEN`` are left out of the child's
  environment, so it uses the plan.
- ``check(model)``: Test connection, a one-word request.

Logs the status, step count and duration only, as ``chat``.
"""

import hmac
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

from engine.core.paths import GamePaths
from engine.tools.assistant.chat import (
    ANSWER_MAX_CHARS, NOT_RUN_LIMIT, NOT_RUN_STOPPED, STATUS_DONE, STATUS_FAILED,
    STATUS_STEP_LIMIT, STATUS_STOPPED, Activity, Chat, ChatRun, SentUpdate, TextDelta, Working,
    activity_text, sent_text)
from engine.tools.assistant.context import chat_summary, request_block, studio_context
from engine.tools.assistant.keystore import ENV_VARS
from engine.tools.assistant.mcp import LINE_MAX_BYTES, Server
from engine.tools.assistant.providers import CLAUDE_CODE, CONNECTED, errors
from engine.tools.assistant.providers.base import AssistantTurn, Usage, UserTurn
from engine.tools.assistant.reference import PRIMER
from engine.tools.assistant.refs import one_line
from engine.tools.assistant.textout import ToolText
from engine.tools.assistant.workspace import CheckService, Snapshot

log = logging.getLogger("vn.assistant")

NAME: Final = "Claude Code"
SERVER: Final = "vn"
MODELS: Final = ("sonnet", "opus", "haiku")
NOT_INSTALLED: Final = ("Claude Code isn't installed on this computer. Install it from "
                        "claude.com/claude-code and sign in, then try again.")
NOT_SIGNED_IN: Final = ("Claude Code isn't signed in. Open a terminal, run claude, and sign in "
                        "with your Claude account.")
UNSAFE: Final = ("Studio can't start Claude Code safely with this game's folder name. Use "
                 "Claude Code in a terminal instead.")
BAD_MODEL: Final = "Pick a Claude Code model such as sonnet or opus in Studio settings ▸ AI."
FAILED: Final = "Claude Code stopped: {reason}"
NO_ANSWER: Final = "it ended without an answer"
# Claude Code's own instructions for the pane (on the command line: no cmd.exe specials).
PANE_NOTE: Final = ("You are working inside the AI Assistant pane of vn-engine Studio. "
                    "propose_edit and propose_settings show each change to the author as a card they "
                    "can apply. "
                    "You cannot change files yourself. Keep answers short and plain.")
TEST_PROMPT: Final = "Reply with the single word OK."
CHILD_TIMEOUT_S: Final = 120                # Test connection only
STDERR_KEEP: Final = 8 * 1024
_MODEL_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-\[\]]{0,63}")
# cmd.exe reads these even inside quotes, so a .cmd launcher can't take them safely.
_CMD_SPECIAL: Final = frozenset('%^&|<>!"\n\r')
_DROPPED_ENV: Final = (*ENV_VARS.values(), "ANTHROPIC_AUTH_TOKEN")
_SIGN_IN_MARKS: Final = ("/login", "not logged in", "invalid api key", "please log in",
                         "oauth token", "authentication")


# --- The child ---------------------------------------------------------------------------------

def find_claude(which: Callable[[str], str | None] = shutil.which) -> str | None:
    return which("claude")


def command(claude: str, config: str, model: str, session: str | None) -> list[str]:
    """The ``claude -p`` argument list for one Send (the prompt goes on stdin)."""
    argv = [claude, "-p", "--output-format", "stream-json", "--verbose",
            "--include-partial-messages", "--strict-mcp-config", "--mcp-config", config,
            "--tools", "", "--allowedTools", f"mcp__{SERVER}",
            # Not the game's CLAUDE.md / AGENTS.md: the pane's own note covers it, and every
            # step would re-read it (2026-11-04).
            "--setting-sources", "user", "--append-system-prompt", PANE_NOTE, "--model", model]
    return argv + ["--resume", session] if session else argv


def unsafe(argv: list[str]) -> bool:
    """A ``.cmd``/``.bat`` launcher runs through cmd.exe: refuse arguments it would read."""
    return argv[0].lower().endswith((".cmd", ".bat")) and any(
        char in _CMD_SPECIAL for arg in argv[1:] for char in arg)


def child_env() -> dict[str, str]:
    """The child's environment: Studio's, without an API key, so Claude Code uses the plan."""
    return {name: value for name, value in os.environ.items()
            if name.upper() not in _DROPPED_ENV}


def _flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def kill(proc: Any) -> None:
    """End the child and what it started (on Windows the .cmd launcher's node child too)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                       creationflags=_flags(), check=False)
    else:
        proc.kill()


def failure_text(said: str) -> tuple[str, str]:
    """(text, kind) for Claude Code's own error message."""
    low = said.lower()
    if any(mark in low for mark in _SIGN_IN_MARKS):
        return NOT_SIGNED_IN, "key"
    return FAILED.format(reason=one_line(said, 200) if said.strip() else NO_ANSWER), "other"


def check(model: str, *, which: Callable[[str], str | None] = shutil.which,
          run: Callable[..., Any] = subprocess.run) -> tuple[bool, str, list[str]]:
    """Test connection: Claude Code answers one word. Returns (ok, text, model choices)."""
    claude = find_claude(which)
    if claude is None:
        return False, NOT_INSTALLED, []
    if not _MODEL_RE.fullmatch(model or ""):
        return False, BAD_MODEL, []
    argv = [claude, "-p", "--output-format", "json", "--tools", "", "--strict-mcp-config",
            "--model", model]
    if unsafe(argv):
        return False, UNSAFE, []
    try:
        done = run(argv, input=TEST_PROMPT.encode(), capture_output=True, env=child_env(),
                   timeout=CHILD_TIMEOUT_S, creationflags=_flags())
    except (OSError, subprocess.SubprocessError) as exc:
        return False, FAILED.format(reason=type(exc).__name__), []
    out = done.stdout.decode("utf-8", "replace")
    try:
        answer = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
    except ValueError:
        answer = {}
    if done.returncode == 0 and isinstance(answer, dict) and not answer.get("is_error"):
        return True, CONNECTED, list(MODELS)
    said = (answer.get("result") if isinstance(answer, dict) else None) or \
        done.stderr.decode("utf-8", "replace") or out
    return False, failure_text(str(said))[0], []


# --- The run's MCP server -----------------------------------------------------------------------

class LocalMcp:
    """The pane's tools over MCP's HTTP transport on 127.0.0.1 for one run (``start``/
    ``stop``). One request is handled at a time, as on stdio."""

    def __init__(self, toolbox: Any) -> None:
        self.server = Server(toolbox, PRIMER)
        self.token = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: object) -> None:    # nothing about requests is logged
                pass

            def _reply(self, status: int, body: bytes = b"") -> None:
                self.send_response(status)
                if body:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_POST(self) -> None:                       # noqa: N802  (http.server)
                if not outer.allowed(self.headers.get("Host", ""),
                                     self.headers.get("Authorization", "")):
                    self.close_connection = True
                    self._reply(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    self.close_connection = True
                    self._reply(411)
                    return
                if not 0 < length <= LINE_MAX_BYTES:
                    self.close_connection = True
                    self._reply(413)
                    return
                body = self.rfile.read(length)
                with outer._lock:
                    answer = outer.server.handle(body)
                if answer is None:
                    self._reply(202)
                else:
                    self._reply(200, answer.rstrip(b"\n"))

            def do_GET(self) -> None:                        # noqa: N802  (no server stream)
                self._reply(405)

            do_DELETE = do_GET

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.handle_error = lambda *_args: None   # a dropped connection prints nothing
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True,
                                        name="assistant-mcp-http")

    def allowed(self, host: str, auth: str) -> bool:
        return host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}") and \
            hmac.compare_digest(auth.encode(), f"Bearer {self.token}".encode())

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    def config(self) -> dict:
        """Claude Code's ``--mcp-config`` for this server."""
        return {"mcpServers": {SERVER: {"type": "http", "url": self.url,
                                        "headers": {"Authorization": f"Bearer {self.token}"}}}}

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class _Reporting:
    """The run's ``ToolBox`` as the server sees it: each call is a step, with the pane's
    activity line and Sent update, and the step limit and Stop applied."""

    def __init__(self, run: "ClaudeCodeRun") -> None:
        self.run = run
        self.names = run.toolbox.names
        self.specs = run.toolbox.specs

    def call(self, name: object, args: object) -> ToolText:
        run = self.run
        if run.cancelled.is_set():
            return ToolText.error(NOT_RUN_STOPPED)
        if run.steps >= run.chat.steps:
            run.limit = True
            return ToolText.error(NOT_RUN_LIMIT)
        run.steps += 1
        run._post(Working(run.steps))
        run._proposal_seen = None
        out = run.toolbox.call(name, args)
        run._sent(out.sent)
        run._post(Activity(activity_text(str(name), out, run._proposal_seen), out.is_error))
        return out


# --- The run ----------------------------------------------------------------------------------

class ClaudeCodeRun(ChatRun):
    """One Send through Claude Code. Same events and ``Done`` as ``ChatRun``; the chat's
    Claude Code session id is kept on ``chat.claude_session`` for the next Send."""

    def __init__(self, chat: Chat, *, model: str, paths: GamePaths, snapshot: Snapshot,
                 request: str, checks: CheckService | None = None,
                 events: Any = None, which: Callable[[str], str | None] = shutil.which,
                 popen: Callable[..., Any] = subprocess.Popen) -> None:
        handle = SimpleNamespace(id=CLAUDE_CODE, name=NAME)
        super().__init__(chat, handle, paths=paths, snapshot=snapshot,  # type: ignore[arg-type]
                         request=request, checks=checks, events=events)
        self.model = model
        self.root = Path(paths.root)
        self.limit = False
        self._which = which
        self._popen = popen
        self._proc: Any = None
        self._text: list[str] = []

    def cancel(self) -> None:
        """Stop/Esc: never blocks."""
        self.cancelled.set()
        proc = self._proc
        if proc is not None:
            threading.Thread(target=kill, args=(proc,), daemon=True).start()

    def _run(self) -> None:
        chat = self.chat
        blocked = chat.blocked()
        if blocked is not None:
            self._finish(STATUS_FAILED, blocked, "token_limit")
            return
        claude = find_claude(self._which)
        if claude is None:
            self._finish(STATUS_FAILED, NOT_INSTALLED, "claude_code")
            return
        if not _MODEL_RE.fullmatch(self.model or ""):
            self._finish(STATUS_FAILED, BAD_MODEL, "model")
            return
        chat.running = True
        first = getattr(chat, "claude_session", None) is None
        if chat.summary is None:
            chat.summary = chat_summary(self.toolbox)
        context = studio_context(self.workspace)
        self.selection = context.selection
        self.sent = chat.summary.sent.merge(context.sent)
        self._post(SentUpdate(sent_text(self.sent, selection=self.selection)))
        blocks = ((chat.summary.text,) if first else ()) + (
            context.text, request_block(self.request))
        server = LocalMcp(_Reporting(self))
        fd, config = tempfile.mkstemp(prefix="vn-assist-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(server.config(), out)
            argv = command(claude, config, self.model, getattr(chat, "claude_session", None))
            if unsafe(argv):
                self._finish(STATUS_FAILED, UNSAFE, "claude_code")
                return
            chat.messages.append(UserTurn(blocks, summary=first))
            server.start()
            self._post(Working(1))
            self._child(argv, "\n\n".join(blocks))
        finally:
            server.stop()
            try:
                os.unlink(config)
            except OSError:
                pass

    def _child(self, argv: list[str], prompt: str) -> None:
        chat = self.chat
        try:
            proc = self._proc = self._popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(self.root), env=child_env(), creationflags=_flags())
        except OSError as exc:
            self._finish(STATUS_FAILED, FAILED.format(reason=type(exc).__name__), "claude_code")
            return
        if self.cancelled.is_set():
            kill(proc)
        stderr: list[bytes] = []
        reader = threading.Thread(target=lambda: stderr.append(proc.stderr.read()), daemon=True)
        reader.start()
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
        result: dict | None = None
        too_long = False
        for raw in proc.stdout:
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            kind = message.get("type")
            if kind == "system" and message.get("subtype") == "init" and \
                    isinstance(message.get("session_id"), str):
                chat.claude_session = message["session_id"]
            elif kind == "stream_event":
                if not self._stream_event(message.get("event")):
                    too_long = True
                    kill(proc)
                    break
            elif kind == "result":
                result = message
        proc.wait()
        reader.join(5)
        said_err = b"".join(stderr)[-STDERR_KEEP:].decode("utf-8", "replace")
        text = "".join(self._text)
        if self.cancelled.is_set():
            if text:
                chat.messages.append(AssistantTurn(text))
            self._finish(STATUS_STOPPED)
            return
        if too_long:
            chat.messages.append(AssistantTurn(text))
            self._finish(STATUS_FAILED, errors.ANSWER_TOO_LONG, "too_long")
            return
        if result is not None:
            self._count(result.get("usage"))
            if isinstance(result.get("session_id"), str):
                chat.claude_session = result["session_id"]
        if result is not None and not result.get("is_error") and proc.returncode == 0:
            chat.messages.append(AssistantTurn(text or str(result.get("result") or "")))
            if not text and result.get("result"):
                self._post(TextDelta(str(result["result"])))
            if self.limit:
                self._finish(STATUS_STEP_LIMIT, errors.STEP_LIMIT.format(n=chat.steps),
                             "step_limit")
            else:
                self._finish(STATUS_DONE)
            return
        said = str(result.get("result") or "") if result is not None else ""
        if not said:
            lines = [line for line in said_err.splitlines() if line.strip()]
            said = lines[-1] if lines else ""
        if "no conversation found" in said.lower():
            chat.claude_session = None              # the next Send starts a new session
        if text:
            chat.messages.append(AssistantTurn(text))
        message, kind = failure_text(said)
        self._finish(STATUS_FAILED, message, "key" if kind == "key" else "claude_code")

    def _stream_event(self, event: object) -> bool:
        """One partial-message event; False once the answer is too long."""
        if not isinstance(event, dict):
            return True
        if event.get("type") == "message_start":
            self._length(event.get("message"))
            return True
        if event.get("type") == "content_block_start":
            block = event.get("content_block")
            if isinstance(block, dict) and block.get("type") == "text" and self._text and \
                    not self._text[-1].endswith("\n"):
                return self._say("\n\n")
            return True
        delta = event.get("delta") if event.get("type") == "content_block_delta" else None
        if isinstance(delta, dict) and delta.get("type") == "text_delta":
            return self._say(str(delta.get("text", "")))
        return True

    def _say(self, text: str) -> bool:
        if not text:
            return True
        self._chars += len(text)
        if self._chars > ANSWER_MAX_CHARS:
            return False
        self._text.append(text)
        self._post(TextDelta(text))
        return True

    def _length(self, message: object) -> None:
        """A step's start: the tokens it reads are the chat's size."""
        usage = message.get("usage") if isinstance(message, dict) else None
        if isinstance(usage, dict):
            sizes = [usage.get(name) for name in (
                "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
            self.chat.length = sum(n for n in sizes if type(n) is int and n >= 0)

    def _count(self, usage: object) -> None:
        if not isinstance(usage, dict):
            return

        def number(name: str) -> int:
            value = usage.get(name)
            return value if type(value) is int and value >= 0 else 0

        used = Usage(number("input_tokens"), number("cache_creation_input_tokens"),
                     number("cache_read_input_tokens"), number("output_tokens"), True)
        self.usage = self.usage + used
        self.chat.usage = self.chat.usage + used
        self.chat.total += used.counted


__all__ = ["BAD_MODEL", "ClaudeCodeRun", "FAILED", "LocalMcp", "MODELS", "NAME",
           "NOT_INSTALLED", "NOT_SIGNED_IN", "PANE_NOTE", "UNSAFE", "check", "command",
           "child_env", "failure_text", "find_claude", "unsafe"]

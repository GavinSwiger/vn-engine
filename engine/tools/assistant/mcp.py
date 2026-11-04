"""The MCP server: the assistant's tools over stdio for Claude Code, Claude Desktop and other
MCP apps (F48 ``04-technical.md`` §7.6; ``05-security.md`` SEC-F48-03, SEC-F48-05 to -08,
§10 "§7.6"; 01 PR-F48-09 to -12, §4.2, §10; ADR-0008 Amendment 5; ``07`` I-10).

Why this module exists: an MCP app starts ``python -P -m engine assist-mcp <game>`` and talks
JSON-RPC 2.0 to it, one JSON message per line on stdin and stdout. Stdout must carry only the
server's own messages, and the input comes from a model, so the protocol is written by hand
(01 §8 D5) with every bound explicit.

- ``serve(game_dir, read_only, launch)`` first keeps a private, non-inheritable duplicate of
  fd 1 for the protocol, then points fd 1 and ``sys.stdout`` at stderr (SEC-F48-06), and
  only then imports the tool layer: a ``print`` anywhere later, an import-time one included,
  lands on stderr. Logs (method, tool, milliseconds, error kind; never arguments, file text
  or results) go to stderr through the redactor. The only children are ``CheckRunner``'s
  (stdin a pipe or the null device, stdout a pipe, stderr the null device), so none inherits
  fd 0 or 1.
- ``Server.handle(line)`` answers one line (requests are handled one at a time). A line is
  read with ``readline(4 MiB + 1)``: an overlong one gets -32600 and the rest of it is
  discarded. Strict UTF-8 and ``json.loads`` with duplicate keys, ``NaN`` and ``Infinity``
  refused; a decode, value or recursion error is -32700; a batch (array) or a request whose
  ``id`` isn't a string or a non-``bool`` integer is -32600; ``params`` must be an object
  (-32602); an unknown method is -32601. Tool faults, bad tool arguments included, are
  ``isError`` results. After any fault the server keeps serving.
- ``initialize`` answers the client's protocol version when it is in ``SUPPORTED``, else the
  newest; it offers ``{"tools": {}}`` and ``instructions`` = ``PRIMER``. ``--read-only``
  leaves ``apply_edit`` and ``undo_apply`` out of ``tools/list`` (and refuses them). The
  server sends no requests to the client.

This module imports only the standard library at its top, and never ``providers/`` (07 §2.10).
"""

import json
import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, Final

SUPPORTED: Final = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
LINE_MAX_BYTES: Final = 4 * 1024 * 1024
SERVER_NAME: Final = "vn-engine"
SERVER_VERSION: Final = "1"
JSONRPC: Final = "2.0"

PARSE_ERROR: Final = -32700
INVALID_REQUEST: Final = -32600
METHOD_NOT_FOUND: Final = -32601
INVALID_PARAMS: Final = -32602
INTERNAL_ERROR: Final = -32603

MESSAGES: Final = {
    PARSE_ERROR: "Parse error", INVALID_REQUEST: "Invalid Request",
    METHOD_NOT_FOUND: "Method not found", INVALID_PARAMS: "Invalid params",
    INTERNAL_ERROR: "Internal error"}
LINE_TOO_LONG: Final = "The message is longer than 4 MiB."

log = logging.getLogger("vn.assistant.mcp")


class _Fault(Exception):
    """A JSON-RPC error for the request ``id`` (None: unknown)."""

    def __init__(self, code: int, request_id: object = None, data: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.request_id = request_id
        self.data = data


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    found: dict = {}
    for key, value in pairs:
        if key in found:
            raise ValueError("duplicate key")
        found[key] = value
    return found


def _no_constant(name: str) -> object:
    raise ValueError(f"{name} is not JSON")


def decode(line: bytes) -> object:
    """One message's JSON (``_Fault(PARSE_ERROR)`` for anything that isn't strict JSON)."""
    try:
        text = line.decode("utf-8")
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except (ValueError, RecursionError, MemoryError):
        raise _Fault(PARSE_ERROR) from None


def encode(message: dict) -> bytes:
    """One outgoing line: ASCII JSON (every other character escaped) and a newline."""
    return json.dumps(message, ensure_ascii=True, separators=(",", ":"),
                      allow_nan=False).encode("ascii") + b"\n"


def _error(code: int, request_id: object, data: str | None = None) -> dict:
    body: dict = {"code": code, "message": MESSAGES[code]}
    if data is not None:
        body["data"] = data
    return {"jsonrpc": JSONRPC, "id": request_id, "error": body}


def _is_id(value: object) -> bool:
    return type(value) is str or type(value) is int


class Server:
    """Answers MCP messages for one ``ToolBox``."""

    def __init__(self, toolbox, primer: str) -> None:
        self.toolbox = toolbox
        self.primer = primer
        self.tool_names = frozenset(toolbox.names)

    def handle(self, line: bytes) -> bytes | None:
        """The answer to one line (without its newline), or None (a notification)."""
        started = time.perf_counter()
        method, tool, kind = "-", "-", "ok"
        try:
            message = decode(line)
            if type(message) is not dict:
                raise _Fault(INVALID_REQUEST)
            is_request = "id" in message
            request_id = message.get("id")
            if is_request and not _is_id(request_id):
                raise _Fault(INVALID_REQUEST)
            if message.get("jsonrpc") != JSONRPC or type(message.get("method")) is not str:
                raise _Fault(INVALID_REQUEST, request_id if is_request else None)
            method = message["method"] if message["method"] in _METHODS else "unknown"
            params = message.get("params", {})
            if type(params) is not dict:
                raise _Fault(INVALID_PARAMS, request_id)
            if not is_request:
                return None                    # notifications/initialized, cancelled, …
            answer = _METHODS.get(message["method"])
            if answer is None:
                raise _Fault(METHOD_NOT_FOUND, request_id)
            if method == "tools/call":
                tool = params.get("name") if params.get("name") in self.tool_names else "unknown"
            result = answer(self, params, request_id)
            if method == "tools/call" and result.get("isError"):
                kind = "tool error"
            return encode({"jsonrpc": JSONRPC, "id": request_id, "result": result})
        except _Fault as fault:
            kind = MESSAGES[fault.code]
            return encode(_error(fault.code, fault.request_id, fault.data))
        except Exception as exc:               # never ends the server
            kind = type(exc).__name__
            return encode(_error(INTERNAL_ERROR, None))
        finally:
            log.info("%s %s %d ms %s", method, tool,
                     int((time.perf_counter() - started) * 1000), kind)

    # -- methods -----------------------------------------------------------------------------

    def _initialize(self, params: dict, request_id: object) -> dict:
        asked = params.get("protocolVersion")
        version = asked if type(asked) is str and asked in SUPPORTED else SUPPORTED[0]
        return {"protocolVersion": version, "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": self.primer}

    def _ping(self, params: dict, request_id: object) -> dict:
        return {}

    def _tools_list(self, params: dict, request_id: object) -> dict:
        return {"tools": list(self.toolbox.specs)}

    def _tools_call(self, params: dict, request_id: object) -> dict:
        name = params.get("name")
        if type(name) is not str:
            raise _Fault(INVALID_PARAMS, request_id)
        args = params.get("arguments", {})
        result = self.toolbox.call(name, args)
        return {"content": [{"type": "text", "text": result.text}],
                "isError": result.is_error}


_METHODS: Final[dict[str, Callable[[Server, dict, object], dict]]] = {
    "initialize": Server._initialize,
    "ping": Server._ping,
    "tools/list": Server._tools_list,
    "tools/call": Server._tools_call,
    "notifications/initialized": Server._ping,
    "notifications/cancelled": Server._ping,
}


def read_line(stream: BinaryIO) -> bytes | None:
    """The next line without its line break; None at the end. An overlong line raises
    ``_Fault(INVALID_REQUEST)`` after the rest of it was read and dropped."""
    line = stream.readline(LINE_MAX_BYTES + 1)
    if not line:
        return None
    if len(line) > LINE_MAX_BYTES and not line.endswith(b"\n"):
        while line and not line.endswith(b"\n"):
            line = stream.readline(LINE_MAX_BYTES + 1)
        raise _Fault(INVALID_REQUEST, None, LINE_TOO_LONG)
    return line.rstrip(b"\r\n")


def run(server: Server, stdin: BinaryIO, stdout: BinaryIO) -> None:
    """Answer every line of ``stdin`` on ``stdout`` until the end of input."""
    while True:
        try:
            line = read_line(stdin)
        except _Fault as fault:
            stdout.write(encode(_error(fault.code, None, fault.data)))
            stdout.flush()
            continue
        if line is None:
            return
        if not line.strip():
            continue
        answer = server.handle(line)
        if answer is not None:
            stdout.write(answer)
            stdout.flush()


def _take_stdout() -> BinaryIO:
    """SEC-F48-06: the protocol keeps a private, non-inheritable duplicate of fd 1; fd 1 and
    ``sys.stdout`` then point at stderr, so any later write to stdout goes there."""
    protocol = os.dup(1)
    os.set_inheritable(protocol, False)
    try:
        os.dup2(2, 1)
    except OSError:                            # no usable stderr: fd 1 goes nowhere
        null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null, 1)
        os.close(null)
    sys.stdout = sys.stderr if sys.stderr is not None else open(os.devnull, "w")
    try:
        os.set_inheritable(0, False)          # children get pipes or the null device anyway
    except OSError:
        pass
    return os.fdopen(protocol, "wb", buffering=0)


class _Redacting(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        from engine.core.redact import echo
        return echo(super().format(record), 500)


def serve(game_dir: Path, read_only: bool = False, launch: bool = True) -> int:
    """Serve the game at ``game_dir`` over stdin/stdout until stdin ends. ``read_only``:
    no ``apply_edit``/``undo_apply``; ``launch`` False (``--no-launch``): every check is
    name-only. Returns the exit status."""
    stdout = _take_stdout()
    stdin = sys.stdin.buffer
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_Redacting("assist-mcp: %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    # The tool layer, imported only now: nothing it prints can reach the protocol stream.
    from engine.core.errors import UserFacingError
    from engine.core.paths import GamePaths
    from engine.tools.assistant.diskapply import ProposalStore
    from engine.tools.assistant.reference import PRIMER
    from engine.tools.assistant.tools import MODE_MCP, MODE_READ_ONLY, ToolBox
    from engine.tools.assistant.workspace import DiskWorkspace, install_redaction
    try:
        paths = GamePaths.for_game(Path(game_dir))
    except UserFacingError as exc:
        log.error("%s", exc.message)
        return 2
    install_redaction(paths)
    workspace = DiskWorkspace(paths, launch=launch)
    writer = None if read_only else ProposalStore(workspace)
    toolbox = ToolBox(workspace, MODE_READ_ONLY if read_only else MODE_MCP, writer=writer)
    try:
        run(Server(toolbox, PRIMER), stdin, stdout)
    finally:
        workspace.checks.stop()
    return 0


__all__ = ["INTERNAL_ERROR", "INVALID_PARAMS", "INVALID_REQUEST", "LINE_MAX_BYTES",
           "METHOD_NOT_FOUND", "PARSE_ERROR", "SUPPORTED", "Server", "decode", "encode",
           "read_line", "run", "serve"]

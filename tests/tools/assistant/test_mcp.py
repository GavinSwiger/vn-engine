"""F48 steps S5 and W1: the MCP server (AC-F48-19 to 22, 24, 26, 27; 04 §7.6; SEC-F48-05 to
-08; 05 §10 "§7.6"; 07 I-10). The subprocess tests start the server with 01 §6.5's own
command, ``python -P -m engine assist-mcp <game>`` with ``PYTHONPATH`` the engine folder
only."""

import io
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from engine import __main__ as entry
from engine.app import cli
from engine.core.paths import engine_root
from engine.tools.assistant.mcp import (
    INVALID_PARAMS, INVALID_REQUEST, LINE_MAX_BYTES, METHOD_NOT_FOUND, PARSE_ERROR, SUPPORTED,
    Server, run)
from engine.tools.assistant.reference import PRIMER
from engine.tools.assistant.tools import (
    MODE_MCP, MODE_READ_ONLY, TOOL_SPECS, ToolBox, WRITE_TOOLS)
from engine.tools.assistant.workspace import CheckService
from engine.tools.editor import files
from engine.tools.editor.checker import CheckRunner, check_argv
from tests.tools.assistant.assist_games import disk, studio

ENGINE_ROOT = engine_root()
# AB-07's import-time ``print`` row (07 I-10): a ``sitecustomize`` on an extra path prints
# NOISE as the server imports its tool layer, after ``__main__``, ``cli`` and ``serve`` began.
NOISE = '{"jsonrpc":"2.0","id":1,"result":{"forged":true}}'
NOISY_SITE = f"""import importlib.abc, sys


class _Noisy(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "engine.tools.assistant.tools":
            print({NOISE!r})
        return None


sys.meta_path.insert(0, _Noisy())
"""


# --- A client over a real server process ------------------------------------------------------

def sample_game(tmp_path: Path) -> Path:
    made = files.new_game(tmp_path / "Lantern Night")
    assert not isinstance(made, files.Refusal), made
    return Path(made)


class Client:
    """``python -P -m engine assist-mcp GAME`` in a child, as 01 §6.5 starts it:
    one JSON-RPC line out, one line back. ``site``: an extra path after the engine's."""

    def __init__(self, game: Path, *flags: str, cwd: Path | None = None,
                 tmp: Path | None = None, site: Path | None = None) -> None:
        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith("PYTHON")}
        env["PYTHONPATH"] = str(ENGINE_ROOT) + (os.pathsep + str(site) if site else "")
        self.err_path = (tmp or game.parent) / f"stderr-{os.getpid()}-{id(self)}.txt"
        self.err = self.err_path.open("wb")
        self.proc = subprocess.Popen(
            [sys.executable, "-P", "-m", "engine", "assist-mcp", str(game), *flags],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.err,
            cwd=str(cwd or ENGINE_ROOT), env=env)
        self.lines: list[bytes] = []
        self.count = 0

    def send(self, raw: bytes) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(raw + b"\n")
        self.proc.stdin.flush()

    def receive(self) -> dict:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        assert line.endswith(b"\n"), (line, self.stderr())
        self.lines.append(line)
        return json.loads(line)

    def request(self, method: str, params: dict | None = None) -> dict:
        self.count += 1
        message = {"jsonrpc": "2.0", "id": self.count, "method": method}
        if params is not None:
            message["params"] = params
        self.send(json.dumps(message).encode("utf-8"))
        answer = self.receive()
        assert answer["id"] == self.count, answer
        return answer

    def tool(self, name: str, arguments: dict | None = None) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})["result"]

    def close(self) -> int:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.close()
        rest = self.proc.stdout.read()
        code = self.proc.wait(60)
        self.err.close()
        assert rest == b"", rest
        return code

    def stderr(self) -> str:
        if not self.err.closed:
            self.err.flush()
        return self.err_path.read_text(encoding="utf-8", errors="replace")


def all_protocol(lines: list[bytes]) -> None:
    for line in lines:
        message = json.loads(line)
        assert message["jsonrpc"] == "2.0" and ("result" in message or "error" in message)


# --- AC-F48-19: initialize, tools, ping over stdio ----------------------------------------------

def test_ac19_the_server_answers_over_stdio_with_only_jsonrpc_lines(tmp_path):
    game = sample_game(tmp_path)
    client = Client(game)
    try:
        init = client.request("initialize", {"protocolVersion": "2025-06-18",
                                             "capabilities": {},
                                             "clientInfo": {"name": "test", "version": "1"}})
        assert init["result"] == {"protocolVersion": "2025-06-18",
                                  "capabilities": {"tools": {}},
                                  "serverInfo": {"name": "vn-engine", "version": "1"},
                                  "instructions": PRIMER}
        client.send(b'{"jsonrpc":"2.0","method":"notifications/initialized"}')
        assert client.request("ping")["result"] == {}
        listed = client.request("tools/list")["result"]["tools"]
        assert listed == json.loads(json.dumps(list(TOOL_SPECS)))
        read = client.tool("read_script", {"file": "script/main.vns", "last_line": 2})
        assert read["isError"] is False
        assert read["content"][0]["type"] == "text"
        assert "script/main.vns, lines 1–2:" in read["content"][0]["text"]
        newer = client.request("initialize", {"protocolVersion": "2099-01-01"})
        assert newer["result"]["protocolVersion"] == SUPPORTED[0] == "2025-11-25"
    finally:
        assert client.close() == 0
    all_protocol(client.lines)
    assert "initialize - " in client.stderr()            # logs go to stderr


# --- AC-F48-20: protocol faults and tool faults -------------------------------------------------

def test_ac20_faults_are_answered_and_the_server_keeps_serving(tmp_path):
    game = studio(tmp_path)
    server = Server(ToolBox(disk(game), MODE_MCP), PRIMER)
    deep = (b'{"jsonrpc":"2.0","id":3,"method":"ping","params":{"a":' + b"[" * 100_000
            + b"]" * 100_000 + b"}}")
    lines = [
        b"x" * (LINE_MAX_BYTES + 1),
        b'[{"jsonrpc":"2.0","id":1,"method":"ping"}]',
        deep,
        b'{"jsonrpc":"2.0","id":true,"method":"ping"}',
        b'{"jsonrpc":"2.0","id":5,"id":6,"method":"ping"}',
        b'{"jsonrpc":"2.0","id":7,"method":"ping","note":"\xff"}',
        b'{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"rm_rf"}}',
        b'{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"read_script",'
        b'"arguments":["script/main.vns"]}}',
        b'{"jsonrpc":"2.0","id":10,"method":"sampling/createMessage"}',
        b'{"jsonrpc":"2.0","id":11,"method":"ping","params":[1]}',
        b'{"jsonrpc":"2.0","id":12,"method":"ping","params":{"x":NaN}}',
        b'{"jsonrpc":"2.0","id":13,"method":"tools/call","params":{"name":7}}',
        b'{"jsonrpc":"2.0","id":14,"method":"ping"}',
    ]
    stdout = io.BytesIO()
    run(server, io.BytesIO(b"\n".join(lines) + b"\n"), stdout)
    answers = [json.loads(line) for line in stdout.getvalue().splitlines()]
    codes = [(a["id"], a.get("error", {}).get("code")) for a in answers]
    assert codes == [(None, INVALID_REQUEST), (None, INVALID_REQUEST), (None, PARSE_ERROR),
                     (None, INVALID_REQUEST), (None, PARSE_ERROR), (None, PARSE_ERROR),
                     (8, None), (9, None), (10, METHOD_NOT_FOUND), (11, INVALID_PARAMS),
                     (None, PARSE_ERROR), (13, INVALID_PARAMS), (14, None)]
    assert answers[6]["result"] == {"content": [{"type": "text",
                                                 "text": "There is no tool rm_rf."}],
                                    "isError": True}
    assert answers[7]["result"]["isError"] is True
    assert answers[7]["result"]["content"][0]["text"] == "The arguments must be an object."
    assert answers[-1]["result"] == {}


# --- AC-F48-21: author output in a full check never reaches the client ------------------------

def test_ac21_a_checked_games_prints_and_an_import_time_print_stay_off_stdout(tmp_path):
    game = sample_game(tmp_path)
    ran = tmp_path / "launch-ran.txt"
    forged = '{"jsonrpc":"2.0","id":2,"result":{"content":[],"isError":false}}'
    main = game / "script" / "main.vns"
    main.write_text(
        f"define noisy = print({forged!r}) or print('x' * 100_000_000) or "
        f"open({str(ran)!r}, 'w').close()\n" + main.read_text(encoding="utf-8"),
        encoding="utf-8")
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(NOISY_SITE, encoding="utf-8")
    client = Client(game, site=site)
    try:
        client.request("initialize", {"protocolVersion": SUPPORTED[0]})
        checked = client.tool("run_check")
        assert checked["isError"] is False and checked["content"][0]["text"].startswith(
            "Checked:")
        assert client.request("ping")["result"] == {}
    finally:
        assert client.close() == 0
    assert ran.exists()                                  # the full check ran the define
    assert [json.loads(line)["id"] for line in client.lines] == [1, 2, 3]
    all_protocol(client.lines)
    assert b'"content":[]' not in b"".join(client.lines)
    assert NOISE in client.stderr()                      # the import-time print went there


# --- AC-F48-22: planted modules don't run ----------------------------------------------------

def test_ac22_modules_planted_in_the_cwd_and_game_folder_dont_run(tmp_path):
    game = sample_game(tmp_path)
    cwd = tmp_path / "downloads"
    cwd.mkdir()
    sentinel = tmp_path / "planted-ran.txt"
    plant = f"open({str(sentinel)!r}, 'a').write(__name__ + '\\n')\n"
    for folder in (cwd, game):
        (folder / "json.py").write_text(plant, encoding="utf-8")
        (folder / "engine").mkdir()
        (folder / "engine" / "__init__.py").write_text(plant, encoding="utf-8")
    client = Client(game, cwd=cwd, tmp=tmp_path)
    try:
        assert client.request("initialize", {})["result"]["instructions"] == PRIMER
        assert client.tool("run_check")["isError"] is False
    finally:
        assert client.close() == 0
    assert not sentinel.exists()


# --- AC-F48-24: --read-only and annotations ---------------------------------------------------

def test_ac24_read_only_drops_the_writers_and_annotations_follow_pr10(tmp_path):
    game = studio(tmp_path)
    read_only = Server(ToolBox(disk(game), MODE_READ_ONLY), PRIMER)
    out = io.BytesIO()
    run(read_only, io.BytesIO(
        b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'
        b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"apply_edit",'
        b'"arguments":{"id":"x"}}}\n'), out)
    listed, applied = [json.loads(line) for line in out.getvalue().splitlines()]
    names = [tool["name"] for tool in listed["result"]["tools"]]
    assert not set(WRITE_TOOLS) & set(names) and len(names) == len(TOOL_SPECS) - 2
    assert applied["result"]["isError"] is True
    assert applied["result"]["content"][0]["text"] == "There is no tool apply_edit."
    for spec in TOOL_SPECS:
        hints = spec["annotations"]
        if spec["name"] in WRITE_TOOLS:
            assert hints["destructiveHint"] is True and hints["readOnlyHint"] is False
        else:
            assert hints["readOnlyHint"] is True and hints["destructiveHint"] is False


# --- AC-F48-26: full checks by default; --no-launch reaches every child ------------------------

@pytest.mark.parametrize("launch", [True, False])
def test_ac26_disk_checks_are_full_unless_no_launch(tmp_path, launch):
    game = studio(tmp_path)
    argvs: list[list[str]] = []

    def spy(game_dir, *, overlay=True, launch=True):
        argvs.append(check_argv(game_dir, overlay=overlay, launch=launch))
        return [sys.executable, "-c", "pass"]           # ends at once: no done line
    workspace = disk(game, launch=launch)
    workspace.checks = CheckService(game, runner=CheckRunner(game, argv=spy))
    box = ToolBox(workspace, MODE_MCP)
    box.call("run_check", {})
    box.call("project_summary", {})
    box.call("propose_edit", {"summary": "s", "changes": [{
        "file": "script/ch2.vns", "old_text": "jump river", "new_text": "jump bridge"}]})
    assert len(argvs) >= 3
    assert all(("--no-launch" in argv) is not launch for argv in argvs), argvs


# --- AC-F48-27: dev runs only ------------------------------------------------------------------

def test_ac27_assist_mcp_is_dev_only(tmp_path, monkeypatch, capsys):
    """``assist-mcp --release`` is a usage error (exit 2); a frozen parser has no
    ``assist-mcp``; ``GAME_DIR`` defaults as ``lint``'s and a relative one resolves against
    the CWD; the flags reach the handler; ``_assist_mcp`` imports the server only when
    called and hands ``serve`` the folder and flags."""
    calls = []

    def handler(game_dir, **kwargs):
        calls.append((game_dir, kwargs))
        return 0

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["assist-mcp", "--release"], assist_mcp=handler)
    assert exit_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.rstrip().endswith("error: assist-mcp is only available in dev runs")
    assert cli.ASSIST_MCP_DEV_ONLY == "assist-mcp is only available in dev runs"
    monkeypatch.chdir(tmp_path)
    assert cli.main(["assist-mcp"], assist_mcp=handler) == 0
    assert cli.main(["assist-mcp", "mygame", "--read-only", "--no-launch"],
                    assist_mcp=handler) == 0
    assert calls == [(ENGINE_ROOT / "game", {"read_only": False, "launch": True}),
                     (tmp_path / "mygame", {"read_only": True, "launch": False})]
    assert capsys.readouterr().out == ""                 # 07 I-10: stdout stays empty
    served = []
    stub = types.ModuleType("engine.tools.assistant.mcp")
    stub.serve = lambda game_dir, **kw: served.append((game_dir, kw)) or 5
    monkeypatch.setitem(sys.modules, "engine.tools.assistant.mcp", stub)
    assert entry._assist_mcp(str(tmp_path), read_only=True, launch=False) == 5
    assert served == [(tmp_path, {"read_only": True, "launch": False})]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["assist-mcp"], assist_mcp=handler)
    assert exit_info.value.code == 2
    assert "invalid choice: 'assist-mcp'" in capsys.readouterr().err
    assert len(calls) == 2

"""The pane on the author's own Claude Code (``providers.claudecode``): the command line, the
run's local MCP server, and one run over a fake ``claude`` child."""

import io
import json
import urllib.request

import pytest

from engine.tools.assistant.chat import Activity, CardEvent, Chat, Done, TextDelta
from engine.tools.assistant.providers import claudecode as cc
from engine.tools.assistant.workspace import Snapshot
from engine.core.paths import GamePaths
from tests.tools.f45_games import studio as make_game


def test_the_command_keeps_the_prompt_off_the_command_line():
    argv = cc.command("claude", "cfg.json", "sonnet", None)
    assert argv[:2] == ["claude", "-p"] and "--strict-mcp-config" in argv
    assert argv[argv.index("--tools") + 1] == "" and "--resume" not in argv
    assert argv[argv.index("--setting-sources") + 1] == "user"     # not the game's CLAUDE.md
    assert argv[argv.index("--allowedTools") + 1] == "mcp__vn"
    assert cc.command("claude", "cfg.json", "sonnet", "abc")[-2:] == ["--resume", "abc"]
    assert not cc.unsafe(argv) and not cc.unsafe(["claude.cmd", *argv[1:]])
    assert cc.unsafe(["claude.cmd", "-p", "a&b"]) and not cc.unsafe(["claude.exe", "a&b"])


def test_the_child_gets_no_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-x")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "t")
    env = cc.child_env()
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env


def test_failure_texts():
    assert cc.failure_text("Invalid API key · Please run /login") == (cc.NOT_SIGNED_IN, "key")
    text, kind = cc.failure_text("Usage limit reached")
    assert kind == "other" and "Usage limit reached" in text
    assert cc.failure_text("")[0] == cc.FAILED.format(reason=cc.NO_ANSWER)
    assert cc.check("sonnet", which=lambda _n: None) == (False, cc.NOT_INSTALLED, [])


class _Tools:
    names = ("project_summary",)
    specs = ({"name": "project_summary", "description": "d",
              "inputSchema": {"type": "object"}},)

    def call(self, name, args):
        from engine.tools.assistant.textout import ToolText
        return ToolText.error("nope")


def _post(server, body, headers):
    request = urllib.request.Request(server.url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def test_the_local_server_wants_its_token():
    server = cc.LocalMcp(_Tools())
    server.start()
    try:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        auth = {"Authorization": f"Bearer {server.token}", "Content-Type": "application/json"}
        assert _post(server, body, {"Content-Type": "application/json"})[0] == 403
        assert _post(server, body, {"Authorization": "Bearer wrong"})[0] == 403
        status, answer = _post(server, body, auth)
        assert status == 200
        assert json.loads(answer)["result"]["tools"][0]["name"] == "project_summary"
        note = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
        assert _post(server, note, auth)[0] == 202
        assert server.config()["mcpServers"]["vn"]["url"] == server.url
    finally:
        server.stop()


class _Child:
    """A fake ``claude -p``: answers with fixed stream-json lines."""

    def __init__(self, lines, code=0):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(b"".join(json.dumps(line).encode() + b"\n" for line in lines))
        self.stderr = io.BytesIO(b"")
        self.returncode = code
        self.pid = 1

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode


def _run(tmp_path, lines, code=0, chat=None):
    game = make_game(tmp_path)
    chat = chat or Chat()
    made = []

    def popen(argv, **kwargs):
        made.append((argv, kwargs))
        return _Child(lines, code)

    run = cc.ClaudeCodeRun(chat, model="sonnet", paths=GamePaths.for_game(game),
                           snapshot=Snapshot({}, {}), request="Hi",
                           which=lambda _n: "claude", popen=popen)
    run.run()
    events = []
    while not run.events.empty():
        events.append(run.events.get())
    return chat, made, events


def test_a_run_streams_text_and_keeps_the_session(tmp_path):
    def delta(text):
        return {"type": "stream_event", "event": {
            "type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}}

    chat, made, events = _run(tmp_path, [
        {"type": "system", "subtype": "init", "session_id": "s1"},
        {"type": "stream_event", "event": {"type": "message_start", "message": {"usage": {
            "input_tokens": 10, "cache_read_input_tokens": 5,
            "cache_creation_input_tokens": 0}}}},
        delta("Hello "), delta("there."),
        {"type": "result", "subtype": "success", "is_error": False, "result": "Hello there.",
         "session_id": "s1", "usage": {"input_tokens": 10, "cache_read_input_tokens": 5,
                                       "cache_creation_input_tokens": 0, "output_tokens": 3}}])
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Hello there."
    done = events[-1]
    assert isinstance(done, Done) and done.status == "done" and done.usage.total == 18
    # A re-read from the cache counts a tenth; the step's start gives the chat's size.
    assert chat.claude_session == "s1" and chat.total == 14 and chat.length == 15
    argv, kwargs = made[0]
    assert "--resume" not in argv and "ANTHROPIC_API_KEY" not in kwargs["env"]
    # The next Send resumes the session.
    _chat, made, _events = _run(tmp_path / "again", [], chat=chat)
    assert made[0][0][-2:] == ["--resume", "s1"]


def test_a_sign_in_failure_offers_settings(tmp_path):
    _chat, _made, events = _run(tmp_path, [
        {"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}],
        code=1)
    done = events[-1]
    assert done.status == "failed" and done.message == cc.NOT_SIGNED_IN and done.kind == "key"


def test_claude_code_missing(tmp_path):
    game = make_game(tmp_path)
    run = cc.ClaudeCodeRun(Chat(), model="sonnet", paths=GamePaths.for_game(game),
                           snapshot=Snapshot({}, {}), request="Hi", which=lambda _n: None)
    run.run()
    assert run.done.message == cc.NOT_INSTALLED


def test_tool_calls_become_steps_and_cards(tmp_path):
    """A call through the run's server is a step with the pane's activity line; a
    ``propose_edit`` becomes a card and writes nothing."""
    game = make_game(tmp_path)
    run = cc.ClaudeCodeRun(Chat(), model="sonnet", paths=GamePaths.for_game(game),
                           snapshot=Snapshot({}, {}), request="Hi", which=lambda _n: "claude")
    tools = cc._Reporting(run)
    before = {p: p.read_bytes() for p in game.rglob("*.vns")}
    script = sorted(before)[0].relative_to(game).as_posix()
    out = tools.call("read_script", {"file": script})
    assert not out.is_error and run.steps == 1
    events = []
    while not run.events.empty():
        events.append(run.events.get())
    assert any(isinstance(e, Activity) for e in events)
    tools.call("propose_edit", {"summary": "x", "changes": []})
    assert {p: p.read_bytes() for p in game.rglob("*.vns")} == before
    run.chat.steps = run.steps
    assert tools.call("read_script", {"file": script}).is_error and run.limit


@pytest.mark.parametrize("model", ["", "bad model", "a;b"])
def test_odd_models_are_refused(model):
    assert cc.check(model, which=lambda _n: "claude") == (False, cc.BAD_MODEL, [])

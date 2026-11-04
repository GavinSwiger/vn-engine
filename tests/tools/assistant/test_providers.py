"""F48 step S8: the Anthropic and Chat Completions providers (AC-F48-38 chat and Test
connection, AC-F48-39, AC-F48-43, AC-F48-52, AC-F48-54; 01 §7.4; SEC-F48-13 (b), -16, -19)."""

import json

import pytest

from engine.tools.assistant.providers import (
    ANTHROPIC, COMPATIBLE, OPENAI, PROVIDER_IDS, make_provider, suggested_models)
from engine.tools.assistant.providers import errors
from engine.tools.assistant.providers.anthropic import (
    API_VERSION, FALLBACK_BETA, AnthropicProvider)
from engine.tools.assistant.providers.base import (
    STOP_END, STOP_LENGTH, STOP_REFUSAL, STOP_TOOLS, AssistantTurn, ToolCall, ToolResult,
    ToolResults, Usage, UserTurn)
from engine.tools.assistant.providers.errors import KeyMismatchError, ProviderError
from engine.tools.assistant.providers.transport import FakeReply, TransportError
from engine.tools.assistant.reference import build_reference
from engine.tools.assistant.tools import TOOL_SPECS, WRITE_TOOLS
from tests.tools.assistant.fake_models import (
    ANTHROPIC_KEY, OPENAI_KEY, Key, anthropic_stream, body, chunk, openai_key, openai_stream,
    provider, reply, sse, text_block, thinking_block, tool_block)

SYSTEM = build_reference()
FIRST = [UserTurn(("PROJECT SUMMARY…", "STUDIO CONTEXT…", "Add a choice."), summary=True)]


def run(made, messages=FIRST):
    seen: list = []
    turn = made.stream(SYSTEM, messages, seen.append)
    return turn, seen


# --- AC-F48-43: stream fixtures decode --------------------------------------------------------

def test_ac43_anthropic_text_tool_input_usage_and_stop():
    stream = anthropic_stream(thinking_block(0, "", "sig-abc"), text_block(1, "I'll read it."),
                              tool_block(2, "toolu_1", "scene", {"label": "club"}, pieces=5),
                              stop="tool_use")
    made, transport = provider(ANTHROPIC, reply(stream))
    turn, seen = run(made)
    assert turn.text == "I'll read it."
    assert turn.stop == STOP_TOOLS
    assert turn.calls == (ToolCall("toolu_1", "scene", {"label": "club"}, '{"label": "club"}'),)
    assert turn.usage == Usage(100, 20, 50, 7, True)
    assert [e.kind for e in seen] == ["text", "call"]
    native = turn.message.native[1]
    assert [b["type"] for b in native] == ["thinking", "text", "tool_use"]
    assert native[0]["signature"] == "sig-abc"
    request = transport.requests[0]
    assert (request.method, request.target) == ("POST", "/v1/messages")
    assert request.header("x-api-key") == ANTHROPIC_KEY
    assert request.header("anthropic-version") == API_VERSION
    assert request.header("anthropic-beta") == FALLBACK_BETA
    assert request.header("authorization") is None
    assert ANTHROPIC_KEY.encode() not in request.body and ANTHROPIC_KEY not in request.target


@pytest.mark.parametrize("reason, stop", [("end_turn", STOP_END), ("max_tokens", STOP_LENGTH),
                                          ("refusal", STOP_REFUSAL),
                                          ("stop_sequence", STOP_END)])
def test_ac43_anthropic_stop_reasons(reason, stop):
    made, _ = provider(ANTHROPIC, reply(anthropic_stream(text_block(0, "x"), stop=reason)))
    turn, _ = run(made)
    assert turn.stop == stop
    assert turn.calls == ()
    assert (turn.message is None) == (stop == STOP_REFUSAL)


def test_ac43_anthropic_error_event_and_malformed_streams():
    error = sse(("message_start", {"type": "message_start", "message": {"usage": {}}}),
                ("error", {"type": "error", "error": {"type": "overloaded_error",
                                                      "message": "Overloaded"}}))
    made, _ = provider(ANTHROPIC, reply(error))
    with pytest.raises(ProviderError) as caught:
        run(made)
    assert caught.value.text == errors.BUSY.format(provider="Anthropic")
    malformed = errors.MALFORMED.format(provider="Anthropic")
    for data in (b"data: {not json\n\n", b"event: message_start\ndata: [1]\n\n",
                 anthropic_stream(text_block(0, "x"))[:-40],          # no message_stop
                 sse(("content_block_delta", {"type": "content_block_delta", "index": 3,
                                              "delta": {"type": "text_delta", "text": "x"}}))):
        made, _ = provider(ANTHROPIC, reply(data))
        with pytest.raises(ProviderError) as caught:
            run(made)
        assert caught.value.text == malformed


def test_ac43_openai_content_tool_calls_by_index_usage_and_done():
    stream = openai_stream("Hello there", [("call_a", "scene", {"label": "club"}),
                                            ("call_b", "story_map", {})],
                           usage={"prompt_tokens": 900, "completion_tokens": 40,
                                  "prompt_tokens_details": {"cached_tokens": 600}})
    made, transport = provider(OPENAI, reply(stream))
    turn, seen = run(made)
    assert turn.text == "Hello there"
    assert turn.stop == STOP_TOOLS
    assert [(c.id, c.name, c.args) for c in turn.calls] == [
        ("call_a", "scene", {"label": "club"}), ("call_b", "story_map", {})]
    assert turn.usage == Usage(300, 0, 600, 40, True)
    assert [e.kind for e in seen] == ["text", "text", "call", "call"]
    request = transport.requests[0]
    assert request.target == "/v1/chat/completions"
    assert request.header("authorization") == f"Bearer {OPENAI_KEY}"
    sent = body(request)
    assert sent["stream_options"] == {"include_usage": True}
    assert "temperature" not in sent and "max_tokens" not in sent


def test_ac43_openai_finish_reasons_and_malformed():
    made, _ = provider(OPENAI, reply(openai_stream("cut", finish="length")))
    assert run(made)[0].stop == STOP_LENGTH
    made, _ = provider(OPENAI, reply(openai_stream("no", finish="content_filter")))
    assert run(made)[0].stop == STOP_REFUSAL
    for data in (sse(chunk({"content": "x"})),                       # ended with no finish
                 sse(("", "{bad")), sse(("", {"choices": {"0": 1}}))):
        made, _ = provider(OPENAI, reply(data))
        with pytest.raises(ProviderError) as caught:
            run(made)
        assert caught.value.text == errors.MALFORMED.format(provider="OpenAI")
    error = sse(("", {"error": {"message": "boom", "type": "server_error"}}))
    made, _ = provider(OPENAI, reply(error))
    with pytest.raises(ProviderError) as caught:
        run(made)
    assert caught.value.text == errors.OTHER.format(provider="OpenAI", message="boom")


# --- AC-F48-50 (provider half): a compatible server without usage -------------------------------

def test_compatible_server_without_usage_reports_none_and_resends_without_stream_options():
    refused = FakeReply(400, {}, [json.dumps({"error": {
        "message": "unknown field: stream_options"}}).encode()])
    made, transport = provider(COMPATIBLE, refused, reply(openai_stream("Hi")),
                               reply(openai_stream("Again")),
                               address="http://localhost:1234/v1", model="qwen")
    turn, _ = run(made)
    assert (turn.text, turn.usage.reported) == ("Hi", False)
    assert [("stream_options" in body(r)) for r in transport.requests] == [True, False]
    run(made)
    assert "stream_options" not in body(transport.requests[2])
    assert all(r.header("authorization") is None for r in transport.requests)
    assert made.name == "localhost:1234"


# --- AC-F48-52: the cached prefix is byte-identical ------------------------------------------

def _prefix(raw: bytes) -> bytes:
    return raw[:raw.index(b'"messages":')]


def test_ac52_anthropic_requests_share_bytes_up_to_the_conversation():
    first = anthropic_stream(tool_block(0, "toolu_1", "story_map", {}), stop="tool_use")
    made, transport = provider(ANTHROPIC, reply(first), reply(anthropic_stream(text_block(0, "ok"))))
    turn, _ = run(made)
    chat = [*FIRST, turn.message, ToolResults((ToolResult("toolu_1", "map"),))]
    run(made, chat)
    one, two = (body(r) for r in transport.requests)
    raw_one, raw_two = (r.body for r in transport.requests)
    assert _prefix(raw_one) == _prefix(raw_two)
    assert one["tools"] == two["tools"]
    assert [t["name"] for t in one["tools"]] == [s["name"] for s in TOOL_SPECS
                                                if s["name"] not in WRITE_TOOLS]
    assert all(t["eager_input_streaming"] is True for t in one["tools"])
    assert one["system"] == [{"type": "text", "text": SYSTEM,
                              "cache_control": {"type": "ephemeral"}}]
    # The summary data block opens the first user message with its own breakpoint, and the
    # first message renders the same in both requests apart from the moving last breakpoint.
    summary = one["messages"][0]["content"][0]
    assert summary == {"type": "text", "text": "PROJECT SUMMARY…",
                       "cache_control": {"type": "ephemeral"}}
    assert two["messages"][0]["content"][0] == summary
    assert one["messages"][0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in two["messages"][0]["content"][-1]
    assert two["messages"][1]["content"] == [dict(b) for b in turn.message.native[1]]
    assert two["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    marks = raw_two.count(b'"cache_control"')
    assert marks <= 4
    # Context and game text only in user messages; the system block is engine text.
    assert all(m["role"] in ("user", "assistant") for m in two["messages"])
    assert "STUDIO CONTEXT" not in json.dumps(one["system"])
    for banned in ("temperature", "top_p", "top_k", "thinking"):
        assert banned not in one


def test_ac52_openai_prefix_and_neutral_replay():
    made, transport = provider(OPENAI, reply(openai_stream("a")), reply(openai_stream("b")))
    run(made)
    chat = [*FIRST, AssistantTurn("", (ToolCall("call_1", "scene", {"label": "x"},
                                                '{"label":"x"}'),)),
            ToolResults((ToolResult("call_1", "lines", False),))]
    run(made, chat)
    raw_one, raw_two = (r.body for r in transport.requests)
    one, two = body(transport.requests[0]), body(transport.requests[1])
    assert raw_two.startswith(raw_one[:raw_one.index(b'"stream":')].rsplit(b"]}", 1)[0])
    assert one["messages"][0] == {"role": "system", "content": SYSTEM}
    assert one["messages"][1]["content"].startswith("PROJECT SUMMARY…\n\nSTUDIO CONTEXT…")
    assert two["messages"][2] == {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function",
         "function": {"name": "scene", "arguments": '{"label":"x"}'}}]}
    assert two["messages"][3] == {"role": "tool", "tool_call_id": "call_1", "content": "lines"}


def test_anthropic_replays_after_a_fallback_and_from_neutral_turns():
    fallback = [("content_block_start", {"type": "content_block_start", "index": 2,
                                         "content_block": {"type": "fallback",
                                                           "from": {"model": "a"},
                                                           "to": {"model": "b"}}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 2})]
    stream = anthropic_stream(thinking_block(0, "", "s1"), text_block(1, "Part. "), fallback,
                              thinking_block(3, "", "s2"), text_block(4, "Rest."),
                              tool_block(5, "toolu_9", "story_map", {}), stop="tool_use")
    made, transport = provider(ANTHROPIC, reply(stream), reply(anthropic_stream(text_block(0, "k"))))
    turn, _ = run(made)
    assert [b["type"] for b in turn.message.native[1]] == ["text", "thinking", "text",
                                                           "tool_use"]
    assert turn.text == "Part. Rest."
    assert [c.id for c in turn.calls] == ["toolu_9"]
    neutral = AssistantTurn("Said.", (ToolCall("call_x", "scene", None, "{bad"),))
    run(made, [*FIRST, neutral, ToolResults((ToolResult("call_x", "", True),))])
    sent = body(transport.requests[1])["messages"]
    assert sent[1]["content"] == [{"type": "text", "text": "Said."},
                                  {"type": "tool_use", "id": "call_x", "name": "scene",
                                   "input": {}}]
    assert sent[2]["content"][0]["is_error"] is True
    assert sent[2]["content"][0]["content"] == "(no text)"


# --- AC-F48-54: hostile streams end at a cap (AB-16) -----------------------------------------

def test_ac54_ten_thousand_tool_calls_stop_at_sixteen():
    blocks = [tool_block(i, f"t{i}", "story_map", {}) for i in range(10_000)]
    made, _ = provider(ANTHROPIC, reply(anthropic_stream(*blocks, stop="tool_use")))
    with pytest.raises(ProviderError) as caught:
        run(made)
    assert caught.value.kind == "malformed"
    calls = [("c%d" % i, "story_map", {}) for i in range(10_000)]
    made, _ = provider(OPENAI, reply(openai_stream(calls=calls[:40])))
    with pytest.raises(ProviderError):
        run(made)


def test_ac54_fifty_mb_of_tool_arguments_stop_at_one_mib():
    part = sse(("content_block_delta", {"type": "content_block_delta", "index": 0,
                                        "delta": {"type": "input_json_delta",
                                                  "partial_json": "x" * (512 * 1024)}}))
    head = sse(("message_start", {"type": "message_start", "message": {"usage": {}}}),
               ("content_block_start", {"type": "content_block_start", "index": 0,
                                        "content_block": {"type": "tool_use", "id": "t",
                                                          "name": "scene", "input": {}}}))
    made, transport = provider(ANTHROPIC, FakeReply(200, {}, [head] + [part] * 100))
    reads: list = []
    transport.on_read = reads.append
    with pytest.raises(ProviderError) as caught:
        run(made)
    assert caught.value.kind == "malformed"
    assert len(reads) < 70                     # stopped near 1 MiB, not after 50 MB


@pytest.mark.parametrize("bad", ["1e999", -5, True, 10**10, 1.5])
def test_ac54_bad_usage_counts_are_ignored(bad):
    stream = anthropic_stream(text_block(0, "x"),
                              usage={"input_tokens": bad, "output_tokens": bad}, output=bad)
    made, _ = provider(ANTHROPIC, reply(stream))
    assert run(made)[0].usage == Usage()


def test_ac54_lone_surrogate_and_invalid_utf8_are_malformed():
    for data in (b'event: x\ndata: {"type":"content_block_delta","index":0,'
                 b'"delta":{"type":"text_delta","text":"\\ud800"}}\n\n',
                 b"event: x\ndata: \xff\n\n"):
        made, _ = provider(ANTHROPIC, reply(data))
        with pytest.raises(ProviderError) as caught:
            run(made)
        assert caught.value.text == errors.MALFORMED.format(provider="Anthropic")


def test_ac54_model_lists_are_capped_and_escaped():
    ids = [{"id": f"model-\u202e{i}"} for i in range(100_000)]
    made, _ = provider(OPENAI, reply(json.dumps({"data": ids}).encode()))
    with pytest.raises(ProviderError) as caught:
        made.list_models()                                       # over 1 MiB
    assert caught.value.kind == "malformed"
    ids = [{"id": f"m\u202e{i}"} for i in range(5_000)] + [{"id": 7}, {"id": "x" * 500}]
    made, transport = provider(ANTHROPIC, reply(json.dumps({"data": ids}).encode()))
    found = made.list_models()
    assert len(found) == 1_000
    assert found[0] == "m\\u202e0"
    assert transport.requests[0].target == "/v1/models?limit=1000"
    assert transport.requests[0].method == "GET"


# --- AC-F48-38: a redirect on Test connection and on a chat --------------------------------------

def test_ac38_a_302_is_an_error_on_test_connection_and_on_a_chat():
    moved = FakeReply(302, {"Location": "http://other/"}, [b""])
    for kind in PROVIDER_IDS:
        made, transport = provider(kind, moved, moved, address="https://llm.example.org/v1")
        with pytest.raises(ProviderError) as caught:
            made.list_models()
        text = errors.OTHER.format(provider=made.name,
                                   message=errors.REDIRECT.format(status=302))
        assert caught.value.text == text
        with pytest.raises(ProviderError) as caught:
            run(made)
        assert caught.value.text == text
        assert len(transport.requests) == 2
        assert all(r.endpoint.host != "other" for r in transport.requests)


# --- AC-F48-39: a key goes only to its own origin (AB-15) ---------------------------------------

def test_ac39_keys_stay_with_their_origin():
    key = openai_key()
    made, transport = provider(COMPATIBLE, reply(openai_stream("x")), key=None,
                               address="https://x.example/v1", model="m")
    run(made)
    assert transport.requests[0].header("authorization") is None
    # The OpenAI key handed to a compatible server, or a key for another origin, is never sent.
    for wrong_kind, wrong_key in ((COMPATIBLE, key),
                                  (COMPATIBLE, Key("k" * 20, COMPATIBLE, "https://y.example:443")),
                                  (ANTHROPIC, key), (OPENAI, Key(OPENAI_KEY, OPENAI,
                                                                 "https://evil.example:443"))):
        made, transport = provider(wrong_kind, reply(openai_stream("x")), key=wrong_key,
                                   address="https://x.example/v1", model="m")
        with pytest.raises(KeyMismatchError):
            run(made)
        with pytest.raises(KeyMismatchError):
            made.list_models()
        assert transport.requests == []
    made, transport = provider(OPENAI, reply(openai_stream("x")), key=key)
    run(made)
    assert transport.requests[0].header("authorization") == f"Bearer {OPENAI_KEY}"
    compatible_key = Key("local-key-123456", COMPATIBLE, "https://x.example:443")
    made, transport = provider(COMPATIBLE, reply(openai_stream("x")), key=compatible_key,
                               address="https://x.example/v1", model="m")
    run(made)
    assert transport.requests[0].header("authorization") == "Bearer local-key-123456"


def test_no_key_and_transport_failures_are_provider_texts():
    made, transport = provider(ANTHROPIC, key=None)
    made.key = None
    with pytest.raises(ProviderError) as caught:
        run(made)
    assert caught.value.text == errors.NO_KEY
    assert transport.requests == []
    made, _ = provider(COMPATIBLE, FakeReply(error=TransportError(TransportError.CONNECT)),
                       address="http://localhost:11434/v1", model="m")
    with pytest.raises(ProviderError) as caught:
        made.list_models()
    assert caught.value.text == errors.NETWORK_LOCAL.format(host="localhost:11434")
    made, _ = provider(ANTHROPIC, FakeReply(401, {}, [json.dumps({"error": {
        "type": "authentication_error", "message": f"bad key {ANTHROPIC_KEY}"}}).encode()]))
    with pytest.raises(ProviderError) as caught:
        run(made)
    assert caught.value.text == errors.BAD_KEY.format(provider="Anthropic")


def test_factory_and_suggested_models():
    assert isinstance(make_provider(ANTHROPIC, model="claude-opus-5-5"), AnthropicProvider)
    assert suggested_models(ANTHROPIC) == ("claude-sonnet-5-5", "claude-opus-5-5")
    assert suggested_models(OPENAI)[0] == "gpt-5"
    assert suggested_models(COMPATIBLE) == ()
    with pytest.raises(errors.AddressError):
        make_provider(COMPATIBLE, model="m", address="http://evil.example/v1")
    opus = make_provider(ANTHROPIC, model="claude-haiku-4-5", key=None)
    assert b"fallbacks" not in opus.request_body(SYSTEM, FIRST)

"""Helpers for the F48 provider and chat tests: scripted Anthropic and Chat Completions
streams for ``FakeTransport``, and a key with the ``BoundKey`` shape."""

import json
from dataclasses import dataclass

from engine.tools.assistant.providers import (
    ANTHROPIC, ANTHROPIC_ORIGIN, OPENAI, OPENAI_ORIGIN, make_provider)
from engine.tools.assistant.providers.transport import FakeReply, FakeTransport

ANTHROPIC_KEY = "sk-ant-api03-test-key-0123456789"
OPENAI_KEY = "sk-proj-test-key-0123456789abcdef"


@dataclass(frozen=True)
class Key:
    value: str
    provider: str
    origin: str


def anthropic_key() -> Key:
    return Key(ANTHROPIC_KEY, ANTHROPIC, ANTHROPIC_ORIGIN)


def openai_key() -> Key:
    return Key(OPENAI_KEY, OPENAI, OPENAI_ORIGIN)


def sse(*events: tuple[str, object]) -> bytes:
    """``(event name, data)`` pairs as SSE bytes (data JSON-encoded unless a str)."""
    out = []
    for name, data in events:
        text = data if isinstance(data, str) else json.dumps(data)
        out.append((f"event: {name}\n" if name else "") + f"data: {text}\n\n")
    return "".join(out).encode("utf-8")


def text_block(index: int, text: str) -> list[tuple[str, object]]:
    return [("content_block_start", {"type": "content_block_start", "index": index,
                                     "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": index,
                                     "delta": {"type": "text_delta", "text": text}}),
            ("content_block_stop", {"type": "content_block_stop", "index": index})]


def tool_block(index: int, call_id: str, name: str, args: object,
               pieces: int = 2) -> list[tuple[str, object]]:
    raw = args if isinstance(args, str) else json.dumps(args)
    size = max(1, len(raw) // pieces + 1)
    parts = [raw[i:i + size] for i in range(0, len(raw), size)] or [""]
    events: list[tuple[str, object]] = [
        ("content_block_start", {"type": "content_block_start", "index": index,
                                 "content_block": {"type": "tool_use", "id": call_id,
                                                   "name": name, "input": {}}})]
    events += [("content_block_delta", {"type": "content_block_delta", "index": index,
                                        "delta": {"type": "input_json_delta",
                                                  "partial_json": part}}) for part in parts]
    events.append(("content_block_stop", {"type": "content_block_stop", "index": index}))
    return events


def thinking_block(index: int, thinking: str, signature: str) -> list[tuple[str, object]]:
    return [("content_block_start", {"type": "content_block_start", "index": index,
                                     "content_block": {"type": "thinking", "thinking": "",
                                                       "signature": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": index,
                                     "delta": {"type": "thinking_delta", "thinking": thinking}}),
            ("content_block_delta", {"type": "content_block_delta", "index": index,
                                     "delta": {"type": "signature_delta",
                                               "signature": signature}}),
            ("content_block_stop", {"type": "content_block_stop", "index": index})]


def anthropic_stream(*blocks: list[tuple[str, object]], stop: str = "end_turn",
                     usage: dict | None = None, output: object = 7) -> bytes:
    start_usage = usage if usage is not None else {
        "input_tokens": 100, "cache_creation_input_tokens": 20, "cache_read_input_tokens": 50,
        "output_tokens": 1}
    events: list[tuple[str, object]] = [
        ("message_start", {"type": "message_start",
                           "message": {"id": "msg_1", "type": "message", "role": "assistant",
                                       "content": [], "usage": start_usage}}),
        ("ping", {"type": "ping"})]
    for block in blocks:
        events += block
    events += [("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop},
                                  "usage": {"output_tokens": output}}),
               ("message_stop", {"type": "message_stop"})]
    return sse(*events)


def chunk(delta: dict | None = None, finish: str | None = None, usage: dict | None = None,
          choices: bool = True) -> tuple[str, object]:
    data: dict = {"id": "c1", "object": "chat.completion.chunk",
                  "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]
                  if choices else []}
    if usage is not None:
        data["usage"] = usage
    return ("", data)


def openai_stream(text: str = "", calls: list[tuple[str, str, object]] = (),
                  finish: str | None = None, usage: dict | None = None) -> bytes:
    events = [chunk({"role": "assistant", "content": ""})]
    if text:
        events += [chunk({"content": text[:3]}), chunk({"content": text[3:]})]
    for index, (call_id, name, args) in enumerate(calls):
        raw = json.dumps(args)
        events.append(chunk({"tool_calls": [{"index": index, "id": call_id, "type": "function",
                                             "function": {"name": name, "arguments": ""}}]}))
        half = len(raw) // 2
        for part in (raw[:half], raw[half:]):
            events.append(chunk({"tool_calls": [{"index": index,
                                                 "function": {"arguments": part}}]}))
    events.append(chunk({}, finish or ("tool_calls" if calls else "stop")))
    if usage is not None:
        events.append(chunk(usage=usage, choices=False))
    events.append(("", "[DONE]"))
    return sse(*events)


def reply(body: bytes, status: int = 200, headers: dict | None = None) -> FakeReply:
    return FakeReply(status, headers or {}, [body[i:i + 97] for i in range(0, len(body), 97)])


def provider(kind: str = ANTHROPIC, *replies: FakeReply, key=None, model: str | None = None,
             address: str | None = None):
    """A provider over a ``FakeTransport`` answering ``replies`` in order."""
    if key is None:
        key = anthropic_key() if kind == ANTHROPIC else openai_key() if kind == OPENAI else None
    transport = FakeTransport(*replies)
    made = make_provider(kind, model=model or ("claude-sonnet-5-5" if kind == ANTHROPIC
                                              else "gpt-5"),
                         key=key, address=address, transport=transport)
    return made, transport


def body(request) -> dict:
    return json.loads(request.body.decode("utf-8"))

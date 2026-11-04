"""Anthropic's Messages API, streamed (F48 ``04-technical.md`` §3.1, §7.7; 01 §7.4,
PR-F48-24, PR-F48-26; ``05-security.md`` SEC-F48-09 (c), SEC-F48-13 (b), SEC-F48-19).

Why this module exists: the pane talks to Claude with raw HTTP (no SDK: no new
dependencies), so the request layout, the stream events and the replay rules live here.

**Request** (01 §7.4; laid out for prompt caching, which matches the rendered prefix
tools → system → messages byte for byte):
- ``tools``: the pane's tools in ``TOOL_SPECS`` order, each with ``eager_input_streaming``
  (arguments stream as they are written; ``parse_args`` validates them strictly).
- ``system``: one block, ``build_reference()`` (the primer, then the language reference),
  with a ``cache_control`` breakpoint. Engine text only, the same for every game.
- ``messages``: the chat's first user message opens with the project-summary data block
  (its own breakpoint), so game content never sits in a system block; each user message
  carries the Studio context; the last message's last block gets the third breakpoint, so
  each tool step reads the steps before it from the cache.
- No ``thinking`` field: Claude Sonnet 5.5 and Claude Opus 5.5 run adaptive thinking by
  default, and their thinking blocks (with signatures) are replayed unchanged.
- Server-side refusal fallbacks (``fallbacks: "default"``, beta
  ``server-side-fallback-2026-07-01``) for the models that take them; a fallback's switch
  point is a ``fallback`` block, and only what follows the last one is replayed whole.
- ``anthropic-version: 2026-10-21``; no ``temperature``/``top_p``/``top_k``.

**Stream**: ``message_start`` (usage), ``content_block_start/delta/stop`` (text, thinking
and signature, tool-input JSON), ``message_delta`` (stop reason, usage), ``message_stop``,
``ping``, ``error``. Usage: input + cache writes + cache reads are "in", cache reads
"cached".
"""

from collections.abc import Callable, Sequence
from typing import Final

from engine.tools.assistant.providers import ANTHROPIC, errors
from engine.tools.assistant.providers.base import (
    BLOCKS_MAX, CALL_ARGS_MAX_BYTES, CALLS_MAX, EVENT_CALL, EVENT_TEXT, STOP_END, STOP_LENGTH,
    STOP_REFUSAL, STOP_TOOLS, AssistantTurn, Message, Provider, StreamEvent, ToolCall,
    ToolResults, Turn, Usage, UserTurn, count, dumps, is_anthropic, parse_args, text_of)
from engine.tools.assistant.providers.sse import SseError, SseEvent, loads
from engine.tools.assistant.tools import MODE_PANE, specs_for

API_VERSION: Final = "2026-10-21"
DEFAULT_MODEL: Final = "claude-sonnet-5-5"
MODELS: Final = ("claude-sonnet-5-5", "claude-opus-5-5")
MAX_TOKENS: Final = 32_000
FALLBACK_BETA: Final = "server-side-fallback-2026-07-01"
# Models that take ``fallbacks: "default"`` on the Claude API (Claude Haiku 5.5 has no
# server-side fallback; older models predate it).
FALLBACK_MODELS: Final = frozenset({"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5",
                                    "claude-fable-5-1", "claude-fable-5"})
CACHE: Final = {"type": "ephemeral"}
EMPTY_RESULT: Final = "(no text)"
_REPLAYED: Final = frozenset({"text", "thinking", "redacted_thinking", "tool_use"})


def tools_json() -> list[dict]:
    """The pane's tools in Messages API form (fresh copies, fixed order)."""
    return [{"name": spec["name"], "description": spec["description"],
             "input_schema": spec["inputSchema"], "eager_input_streaming": True}
            for spec in specs_for(MODE_PANE)]


def _text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def _assistant_content(message: AssistantTurn) -> list[dict]:
    if is_anthropic(message):
        assert message.native is not None
        return [dict(block) for block in message.native[1]]      # type: ignore[union-attr]
    content: list[dict] = [_text_block(message.text)] if message.text else []
    for call in message.calls:
        args = call.args if isinstance(call.args, dict) else {}
        content.append({"type": "tool_use", "id": call.id, "name": call.name, "input": args})
    return content


def render_messages(messages: Sequence[Message]) -> list[dict]:
    """The chat as Messages API ``messages`` with 01 §7.4's breakpoints."""
    rendered: list[dict] = []
    for message in messages:
        if isinstance(message, UserTurn):
            content = [_text_block(block) for block in message.blocks if block]
            if message.summary and content:
                content[0]["cache_control"] = dict(CACHE)
            rendered.append({"role": "user", "content": content})
        elif isinstance(message, AssistantTurn):
            content = _assistant_content(message)
            if content:
                rendered.append({"role": "assistant", "content": content})
        elif isinstance(message, ToolResults):
            results = []
            for result in message.results:
                block = {"type": "tool_result", "tool_use_id": result.call_id,
                         "content": result.text or EMPTY_RESULT}
                if result.is_error:
                    block["is_error"] = True
                results.append(block)
            rendered.append({"role": "user", "content": results})
    if rendered and rendered[-1]["content"]:
        last = rendered[-1]["content"][-1]
        if "cache_control" not in last:
            last["cache_control"] = dict(CACHE)
    return rendered


class AnthropicProvider(Provider):
    id = ANTHROPIC
    API_PATH = "/messages"
    MODELS_PATH = "/models?limit=1000"

    def _fallbacks(self) -> bool:
        return self.model in FALLBACK_MODELS

    def _headers(self, key: str | None, *, stream: bool) -> list[tuple[str, str]]:
        assert key is not None
        headers = [("x-api-key", key), ("anthropic-version", API_VERSION)]
        if stream:
            headers += [("content-type", "application/json"), ("accept", "text/event-stream")]
            if self._fallbacks():
                headers.append(("anthropic-beta", FALLBACK_BETA))
        return headers

    def request_body(self, system: str, messages: Sequence[Message]) -> bytes:
        body: dict = {"model": self.model, "max_tokens": MAX_TOKENS, "stream": True,
                      "tools": tools_json(),
                      "system": [{"type": "text", "text": system, "cache_control": dict(CACHE)}],
                      "messages": render_messages(messages)}
        if self._fallbacks():
            body["fallbacks"] = "default"
        return dumps(body)

    # -- the stream ----------------------------------------------------------------------------

    def _decode(self, events: Callable[[], list[SseEvent]],
                on_event: Callable[[StreamEvent], None]) -> Turn:
        state = _Message(self)
        while not state.stopped:
            batch = events()
            if not batch:
                raise errors.malformed(self.name)             # ended before message_stop
            for event in batch:
                state.event(event, on_event)
                if state.stopped:
                    break
        return state.turn()


class _Message:
    """One streamed message being put together."""

    def __init__(self, provider: AnthropicProvider) -> None:
        self.provider = provider
        self.blocks: dict[int, dict] = {}
        self.args: dict[int, list[str]] = {}
        self.arg_sizes: dict[int, int] = {}
        self.calls: dict[int, ToolCall] = {}
        self.text: list[str] = []
        self.stop_reason: str | None = None
        self.usage = Usage()
        self.stopped = False

    def _bad(self) -> errors.ProviderError:
        return errors.malformed(self.provider.name)

    def _usage(self, raw: object, *, start: bool) -> None:
        if not isinstance(raw, dict):
            return
        found = {name: count(raw.get(name)) for name in (
            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
            "output_tokens")}
        if not any(value is not None for value in found.values()):
            return
        old = self.usage
        self.usage = Usage(
            found["input_tokens"] if found["input_tokens"] is not None else old.input,
            found["cache_creation_input_tokens"]
            if found["cache_creation_input_tokens"] is not None else old.cache_write,
            found["cache_read_input_tokens"]
            if found["cache_read_input_tokens"] is not None else old.cache_read,
            found["output_tokens"] if found["output_tokens"] is not None else old.output,
            True)

    def event(self, event: SseEvent, on_event: Callable[[StreamEvent], None]) -> None:
        try:
            data = loads(event.data)
        except SseError:
            raise self._bad() from None
        if not isinstance(data, dict):
            raise self._bad()
        kind = data.get("type")
        if kind == "message_start":
            message = data.get("message")
            if not isinstance(message, dict):
                raise self._bad()
            self._usage(message.get("usage"), start=True)
        elif kind == "content_block_start":
            self._start(data)
        elif kind == "content_block_delta":
            self._delta(data, on_event)
        elif kind == "content_block_stop":
            self._stop(data, on_event)
        elif kind == "message_delta":
            delta = data.get("delta")
            if isinstance(delta, dict) and type(delta.get("stop_reason")) is str:
                self.stop_reason = delta["stop_reason"]
            self._usage(data.get("usage"), start=False)
        elif kind == "message_stop":
            self.stopped = True
        elif kind == "error":
            raise errors.from_error_object(data, provider=self.provider.name,
                                           model=self.provider.model,
                                           secret=self.provider._secret())
        # ping and unknown events: ignored (counted by the decoder's byte cap)

    def _index(self, data: dict) -> int:
        index = data.get("index")
        if type(index) is not int or not 0 <= index < BLOCKS_MAX:
            raise self._bad()
        return index

    def _start(self, data: dict) -> None:
        index = self._index(data)
        block = data.get("content_block")
        if not isinstance(block, dict) or index in self.blocks:
            raise self._bad()
        kind = block.get("type")
        if kind == "text":
            self.blocks[index] = {"type": "text", "text": text_of(block.get("text"))}
        elif kind == "thinking":
            self.blocks[index] = {"type": "thinking", "thinking": text_of(block.get("thinking")),
                                  "signature": text_of(block.get("signature"))}
        elif kind == "tool_use":
            call_id, name = block.get("id"), block.get("name")
            if type(call_id) is not str or type(name) is not str or not call_id:
                raise self._bad()
            if sum(1 for b in self.blocks.values() if b.get("type") == "tool_use") >= CALLS_MAX:
                raise self._bad()                          # more than 16 calls in a step
            self.blocks[index] = {"type": "tool_use", "id": call_id, "name": name, "input": {}}
            self.args[index] = []
            self.arg_sizes[index] = 0
        else:                                             # redacted_thinking, fallback, …
            self.blocks[index] = dict(block)

    def _delta(self, data: dict, on_event: Callable[[StreamEvent], None]) -> None:
        index = self._index(data)
        block = self.blocks.get(index)
        delta = data.get("delta")
        if block is None or not isinstance(delta, dict):
            raise self._bad()
        kind = delta.get("type")
        if kind == "text_delta" and block["type"] == "text":
            text = delta.get("text")
            if type(text) is not str:
                raise self._bad()
            block["text"] += text
            self.text.append(text)
            if text:
                on_event(StreamEvent(EVENT_TEXT, text))
        elif kind == "thinking_delta" and block["type"] == "thinking":
            block["thinking"] += text_of(delta.get("thinking"))
        elif kind == "signature_delta" and block["type"] == "thinking":
            block["signature"] += text_of(delta.get("signature"))
        elif kind == "input_json_delta" and block["type"] == "tool_use":
            part = delta.get("partial_json")
            if type(part) is not str:
                raise self._bad()
            self.arg_sizes[index] += len(part.encode("utf-8", "surrogatepass"))
            if self.arg_sizes[index] > CALL_ARGS_MAX_BYTES:
                raise self._bad()
            self.args[index].append(part)

    def _stop(self, data: dict, on_event: Callable[[StreamEvent], None]) -> None:
        index = self._index(data)
        block = self.blocks.get(index)
        if block is None:
            raise self._bad()
        if block["type"] == "tool_use" and index not in self.calls:
            raw = "".join(self.args.pop(index, []))
            args = parse_args(raw)
            block["input"] = args if isinstance(args, dict) else {}
            call = ToolCall(block["id"], block["name"], args, raw)
            self.calls[index] = call
            on_event(StreamEvent(EVENT_CALL, call=call))

    def turn(self) -> Turn:
        order = sorted(self.blocks)
        fallbacks = [i for i in order if self.blocks[i].get("type") == "fallback"]
        boundary = fallbacks[-1] if fallbacks else -1
        content: list[dict] = []
        calls: list[ToolCall] = []
        for index in order:
            block = self.blocks[index]
            kind = block.get("type")
            if kind not in _REPLAYED or (index < boundary and kind != "text"):
                continue                     # before a fallback: only text goes back
            if kind == "text" and not block["text"]:
                continue
            content.append(block)
            if kind == "tool_use" and index in self.calls:
                calls.append(self.calls[index])
        text = "".join(block["text"] for block in content if block["type"] == "text")
        reason = self.stop_reason
        if reason == "refusal":
            return Turn(text, (), STOP_REFUSAL, self.usage, None)
        if reason == "max_tokens":
            stop = STOP_LENGTH
        elif reason == "tool_use" and calls:
            stop = STOP_TOOLS
        else:
            stop = STOP_END
        message = AssistantTurn(text, tuple(calls), (ANTHROPIC, tuple(content))) \
            if content else None
        return Turn(text, tuple(calls) if stop == STOP_TOOLS else (), stop, self.usage,
                    message)


__all__ = ["API_VERSION", "AnthropicProvider", "DEFAULT_MODEL", "FALLBACK_BETA",
           "FALLBACK_MODELS", "MAX_TOKENS", "MODELS", "render_messages", "tools_json"]

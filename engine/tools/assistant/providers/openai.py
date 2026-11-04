"""OpenAI's Chat Completions API, streamed; it also serves OpenAI-compatible servers (Ollama,
LM Studio) (F48 ``04-technical.md`` §3.1, §7.7; 01 §7.4, PR-F48-24, PR-F48-26, AC-F48-50;
``05-security.md`` SEC-F48-13 (b), SEC-F48-16, SEC-F48-19).

Why this module exists: OpenAI and the local servers share one wire format, so one class
speaks it; only the endpoint, the key and the provider name differ.

**Request** (same order as Anthropic's, for automatic prefix caching): ``tools`` (the pane's
tools as functions), then ``messages``: a ``system`` message holding ``build_reference()``,
then the chat (user messages join their blocks, the summary data block first). ``stream``
with ``stream_options.include_usage``; a server answering 400 that names
``stream_options`` gets the request once more without it, and this provider leaves it out
from then on. No ``temperature``, no ``max_tokens``. A compatible server without a key gets
no auth header (AC-F48-39).

**Stream**: ``data:`` chunks of ``choices[0].delta`` (``content``; ``tool_calls`` by
``index``, the id and name in the first fragment, ``arguments`` in pieces),
``finish_reason``, a final ``usage`` chunk (``prompt_tokens`` includes
``prompt_tokens_details.cached_tokens``), then ``data: [DONE]``. A server that sends no
usage gives ``Usage(reported=False)``: "Usage not reported." (01 §6.1).
"""

from collections.abc import Callable, Sequence
from typing import Final

from engine.tools.assistant.providers import COMPATIBLE, OPENAI, errors
from engine.tools.assistant.providers.base import (
    CALL_ARGS_MAX_BYTES, CALLS_MAX, EVENT_CALL, EVENT_TEXT, STOP_END, STOP_LENGTH, STOP_REFUSAL,
    STOP_TOOLS, AssistantTurn, Message, Provider, StreamEvent, ToolCall, ToolResults, Turn,
    Usage, UserTurn, count, dumps, parse_args)
from engine.tools.assistant.providers.errors import ProviderError
from engine.tools.assistant.providers.sse import SseError, SseEvent, loads
from engine.tools.assistant.providers.transport import Response
from engine.tools.assistant.tools import MODE_PANE, specs_for

# 01 §8 D6: the OpenAI default is named at build time (prefs.DEFAULT_MODELS, S7); the list
# fills from the server after Test connection.
DEFAULT_MODEL: Final = "gpt-5"
MODELS: Final = ("gpt-5", "gpt-5-mini")
DONE: Final = "[DONE]"
BLOCK_SEPARATOR: Final = "\n\n"
STREAM_OPTIONS: Final = "stream_options"
EMPTY_RESULT: Final = "(no text)"


def tools_json() -> list[dict]:
    """The pane's tools as Chat Completions functions (fresh copies, fixed order)."""
    return [{"type": "function",
             "function": {"name": spec["name"], "description": spec["description"],
                          "parameters": spec["inputSchema"]}}
            for spec in specs_for(MODE_PANE)]


def render_messages(system: str, messages: Sequence[Message]) -> list[dict]:
    rendered: list[dict] = [{"role": "system", "content": system}]
    for message in messages:
        if isinstance(message, UserTurn):
            rendered.append({"role": "user",
                             "content": BLOCK_SEPARATOR.join(b for b in message.blocks if b)})
        elif isinstance(message, AssistantTurn):
            if not message.text and not message.calls:
                continue
            entry: dict = {"role": "assistant", "content": message.text or None}
            if message.calls:
                entry["tool_calls"] = [
                    {"id": call.id, "type": "function",
                     "function": {"name": call.name,
                                  "arguments": call.raw if call.raw else "{}"}}
                    for call in message.calls]
            rendered.append(entry)
        elif isinstance(message, ToolResults):
            for result in message.results:
                rendered.append({"role": "tool", "tool_call_id": result.call_id,
                                 "content": result.text or EMPTY_RESULT})
    return rendered


class OpenAIProvider(Provider):
    """OpenAI (``id`` ``openai``) or a compatible server (``compatible``)."""

    API_PATH = "/chat/completions"
    MODELS_PATH = "/models"

    def __init__(self, *args, provider_id: str = OPENAI, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.id = provider_id
        self.usage_option = True          # False once a server refused stream_options

    def _headers(self, key: str | None, *, stream: bool) -> list[tuple[str, str]]:
        headers = [("authorization", f"Bearer {key}")] if key is not None else []
        if stream:
            headers += [("content-type", "application/json"), ("accept", "text/event-stream")]
        return headers

    def request_body(self, system: str, messages: Sequence[Message]) -> bytes:
        body: dict = {"model": self.model, "tools": tools_json(),
                      "messages": render_messages(system, messages), "stream": True}
        if self.usage_option:
            body[STREAM_OPTIONS] = {"include_usage": True}
        return dumps(body)

    def _send_step(self, system: str, messages: Sequence[Message]) -> Response:
        try:
            return super()._send_step(system, messages)
        except ProviderError as exc:
            if exc.status != 400 or not self.usage_option or STREAM_OPTIONS not in exc.text:
                raise
        self.usage_option = False
        return super()._send_step(system, messages)

    # -- the stream ----------------------------------------------------------------------------

    def _decode(self, events: Callable[[], list[SseEvent]],
                on_event: Callable[[StreamEvent], None]) -> Turn:
        state = _Completion(self)
        while not state.done:
            batch = events()
            if not batch:
                if state.finish is None:
                    raise errors.malformed(self.name)     # ended before any finish
                break
            for event in batch:
                state.event(event, on_event)
                if state.done:
                    break
        return state.turn(on_event)


class _Completion:
    def __init__(self, provider: OpenAIProvider) -> None:
        self.provider = provider
        self.text: list[str] = []
        self.calls: dict[int, dict] = {}
        self.finish: str | None = None
        self.usage = Usage()
        self.done = False

    def _bad(self) -> ProviderError:
        return errors.malformed(self.provider.name)

    def event(self, event: SseEvent, on_event: Callable[[StreamEvent], None]) -> None:
        if event.data.strip() == DONE:
            self.done = True
            return
        try:
            data = loads(event.data)
        except SseError:
            raise self._bad() from None
        if not isinstance(data, dict):
            raise self._bad()
        if "error" in data and data["error"] is not None:
            raise errors.from_error_object(data, provider=self.provider.name,
                                           model=self.provider.model,
                                           secret=self.provider._secret())
        usage = data.get("usage")
        if isinstance(usage, dict):
            self._usage(usage)
        choices = data.get("choices")
        if choices is None:
            return
        if not isinstance(choices, list):
            raise self._bad()
        for choice in choices:
            if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                self._delta(delta, on_event)
            if type(choice.get("finish_reason")) is str:
                self.finish = choice["finish_reason"]

    def _usage(self, usage: dict) -> None:
        prompt = count(usage.get("prompt_tokens"))
        output = count(usage.get("completion_tokens"))
        details = usage.get("prompt_tokens_details")
        cached = count(details.get("cached_tokens")) if isinstance(details, dict) else None
        if prompt is None and output is None:
            return
        cached = min(cached or 0, prompt or 0)
        self.usage = Usage((prompt or 0) - cached, 0, cached, output or 0, True)

    def _delta(self, delta: dict, on_event: Callable[[StreamEvent], None]) -> None:
        content = delta.get("content")
        if content is not None:
            if type(content) is not str:
                raise self._bad()
            if content:
                self.text.append(content)
                on_event(StreamEvent(EVENT_TEXT, content))
        calls = delta.get("tool_calls")
        if calls is None:
            return
        if not isinstance(calls, list):
            raise self._bad()
        for part in calls:
            if not isinstance(part, dict):
                raise self._bad()
            index = part.get("index")
            if index is None:                 # some servers send whole calls without one
                known = [i for i, c in self.calls.items() if c["id"] == part.get("id")]
                index = known[0] if known else len(self.calls) if part.get("id") \
                    else max(self.calls, default=0)
            if type(index) is not int or not 0 <= index < CALLS_MAX:
                raise self._bad()                          # past 16 calls in a step
            call = self.calls.setdefault(index, {"id": "", "name": "", "args": [], "size": 0})
            if type(part.get("id")) is str and part["id"]:
                call["id"] = part["id"]
            function = part.get("function")
            if isinstance(function, dict):
                if type(function.get("name")) is str and function["name"]:
                    call["name"] = function["name"]
                arguments = function.get("arguments")
                if arguments is not None:
                    if type(arguments) is not str:
                        raise self._bad()
                    call["size"] += len(arguments.encode("utf-8", "surrogatepass"))
                    if call["size"] > CALL_ARGS_MAX_BYTES:
                        raise self._bad()
                    call["args"].append(arguments)

    def turn(self, on_event: Callable[[StreamEvent], None]) -> Turn:
        calls: list[ToolCall] = []
        for index in sorted(self.calls):
            found = self.calls[index]
            if not found["name"]:
                raise self._bad()
            raw = "".join(found["args"])
            call = ToolCall(found["id"] or f"call_{index}", found["name"], parse_args(raw), raw)
            calls.append(call)
            on_event(StreamEvent(EVENT_CALL, call=call))
        text = "".join(self.text)
        finish = self.finish
        if finish == "content_filter":
            return Turn(text, (), STOP_REFUSAL, self.usage, None)
        if finish == "length":
            stop = STOP_LENGTH
        elif calls:
            stop = STOP_TOOLS                 # "tool_calls", or "stop" from some servers
        else:
            stop = STOP_END
        message = AssistantTurn(text, tuple(calls)) if text or calls else None
        return Turn(text, tuple(calls) if stop == STOP_TOOLS else (), stop, self.usage,
                    message)


__all__ = ["COMPATIBLE", "DEFAULT_MODEL", "MODELS", "OpenAIProvider", "render_messages",
           "tools_json"]

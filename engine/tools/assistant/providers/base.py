"""What every provider shares: the chat's messages, stream events, usage, and the request
plumbing (F48 ``04-technical.md`` §3.1, §7.7; 01 §7.4, PR-F48-24; ``05-security.md``
SEC-F48-13 (b), SEC-F48-16, SEC-F48-19).

Why this module exists: a chat is kept in one provider-neutral form, so a step's request can
be rendered for Anthropic or for Chat Completions from the same messages, and every provider
reads its stream under the same caps:

- ``UserTurn`` (the summary data block, the Studio context and the author's request),
  ``AssistantTurn`` (text, tool calls, and the provider's own content for an exact replay),
  ``ToolResults``. Messages are only ever appended, so each request's prefix is
  byte-identical to the last (prompt caching; Anthropic's thinking-block binding).
- ``Provider.stream(system, messages, on_event)`` runs one model step and returns a ``Turn``;
  text arrives through ``on_event`` as ``StreamEvent``s. ``Provider.list_models()`` is Test
  connection.
- Caps (SEC-F48-19): at most 16 tool calls per step, each call's arguments at most 1 MiB, a
  model list at most 1 MiB and 1,000 ids of at most 200 characters (escaped). A usage count
  is used only if it is an ``int`` from 0 to 10⁹.
- Before any byte is sent, the key's provider and origin must equal the endpoint's
  (SEC-F48-16), else ``KeyMismatchError``; the key goes only into the auth header.
"""

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final

from engine.tools.assistant.providers import ANTHROPIC, COMPATIBLE, PROVIDER_NAMES, KeyLike
from engine.tools.assistant.providers import errors
from engine.tools.assistant.providers.errors import (
    ERROR_BODY_MAX_BYTES, NO_KEY, KeyMismatchError, ProviderError, TransportError)
from engine.tools.assistant.providers.sse import SseDecoder, SseError, SseEvent, loads
from engine.tools.assistant.providers.transport import (
    READ_CHUNK_BYTES, Endpoint, Request, Response, Transport, read_body)
from engine.tools.assistant.refs import visible

log = logging.getLogger("vn.assistant")

CALLS_MAX: Final = 16                     # tool calls in one step (SEC-F48-19)
CALL_ARGS_MAX_BYTES: Final = 1024 * 1024
MODEL_LIST_MAX_BYTES: Final = 1024 * 1024
MODEL_IDS_MAX: Final = 1_000
MODEL_ID_MAX_CHARS: Final = 200
USAGE_MAX: Final = 10**9
BLOCKS_MAX: Final = 1_000                 # content blocks in one Anthropic message

STOP_END: Final = "end"
STOP_TOOLS: Final = "tools"
STOP_LENGTH: Final = "length"
STOP_REFUSAL: Final = "refusal"


# --- Messages ---------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool call: ``args`` is the parsed JSON object, or None when ``raw`` wasn't valid
    JSON (the call then gets an error result); ``raw`` is the arguments as streamed."""

    id: str
    name: str
    args: object
    raw: str = ""

    @property
    def bad(self) -> bool:
        return self.args is None


@dataclass(frozen=True, slots=True)
class UserTurn:
    """The author's message: text blocks in order. ``summary``: the first block is the
    chat-start project summary (a data block with its own cache breakpoint)."""

    blocks: tuple[str, ...]
    summary: bool = False


@dataclass(frozen=True, slots=True)
class AssistantTurn:
    """The model's message. ``native`` is ``(provider id, content)`` for an exact replay to
    the same provider (Anthropic's thinking and signature blocks), else None."""

    text: str
    calls: tuple[ToolCall, ...] = ()
    native: tuple[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    text: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ToolResults:
    results: tuple[ToolResult, ...]


Message = UserTurn | AssistantTurn | ToolResults


# --- Stream results ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Usage:
    """Tokens of one step or a sum. "In" = ``input`` + ``cache_write`` + ``cache_read``;
    "cached" = ``cache_read`` (01 §7.4). ``reported``: the server sent any count."""

    input: int = 0
    cache_write: int = 0
    cache_read: int = 0
    output: int = 0
    reported: bool = False

    @property
    def total_in(self) -> int:
        return self.input + self.cache_write + self.cache_read

    @property
    def total(self) -> int:
        return self.total_in + self.output

    @property
    def counted(self) -> int:
        """What a chat's total and limit count: a re-read from the prompt cache counts a
        tenth, as it is billed. Every step re-reads the whole chat, so counting re-reads in
        full made a 31,000-token chat read as 510,000 and trip the limit (2026-11-04)."""
        return self.input + self.cache_write + self.output + -(-self.cache_read // 10)

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.input + other.input, self.cache_write + other.cache_write,
                     self.cache_read + other.cache_read, self.output + other.output,
                     self.reported or other.reported)


def count(value: object) -> int | None:
    """A usage count: an ``int`` (not bool) from 0 to 10⁹, else None (ignored)."""
    return value if type(value) is int and 0 <= value <= USAGE_MAX else None


EVENT_TEXT: Final = "text"
EVENT_CALL: Final = "call"


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """What a provider reports while it streams: answer text, or a finished tool call."""

    kind: str
    text: str = ""
    call: ToolCall | None = None


@dataclass(frozen=True, slots=True)
class Turn:
    """One finished model step. ``calls`` are the ones to run (none unless ``stop`` is
    ``STOP_TOOLS``); ``message`` is what the chat appends."""

    text: str
    calls: tuple[ToolCall, ...]
    stop: str
    usage: Usage
    message: AssistantTurn | None = field(default=None)


# --- Providers --------------------------------------------------------------------------------

def dumps(body: object) -> bytes:
    """Request JSON: deterministic, compact, UTF-8 (equal messages give equal bytes)."""
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class Provider:
    """One provider at one endpoint with one model. Subclasses give ``_headers``,
    ``request_body``, ``_decode`` and the model-list path."""

    id: str = ""
    API_PATH: str = ""
    MODELS_PATH: str = ""

    def __init__(self, endpoint: Endpoint, model: str, key: KeyLike | None,
                 transport: Transport, *, origin: str | None = None) -> None:
        self.endpoint = endpoint
        self.model = model
        self.key = key
        self.transport = transport
        # The origin a key for this provider is bound to (the fixed ones, or the address's).
        self.origin = origin if origin is not None else endpoint.origin

    @property
    def name(self) -> str:
        """01 §6.6's {provider}: "Anthropic", "OpenAI", or a compatible server's host."""
        return PROVIDER_NAMES.get(self.id, self.endpoint.display_host)

    # -- the key -------------------------------------------------------------------------------

    def _key_value(self) -> str | None:
        """The key for this request: SEC-F48-16's check, before anything is sent."""
        key = self.key
        if key is None:
            if self.id == COMPATIBLE:
                return None
            raise ProviderError(NO_KEY, "no_key")
        if key.provider != self.id or key.origin != self.origin \
                or self.endpoint.origin != self.origin:
            raise KeyMismatchError(errors.KEY_ELSEWHERE)
        return key.value

    def _secret(self) -> str | None:
        return self.key.value if self.key is not None else None

    def _headers(self, key: str | None, *, stream: bool) -> list[tuple[str, str]]:
        raise NotImplementedError

    # -- sending -------------------------------------------------------------------------------

    def _failure(self, exc: BaseException) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, TransportError):
            return errors.from_transport(exc, provider=self.name,
                                         host=self.endpoint.display_host,
                                         loopback=self.endpoint.loopback)
        return errors.malformed(self.name)

    def _open(self, method: str, target: str, body: bytes | None, *,
              stream: bool) -> Response:
        """Send; a non-200 status (3xx included) becomes its ``ProviderError``."""
        key = self._key_value()
        request = Request(method, self.endpoint, target,
                          tuple(self._headers(key, stream=stream)), body)
        started = time.monotonic()
        try:
            response = self.transport.open(request)
        except TransportError as exc:
            log.info("assistant %s: %s failed (%s)", self.id, method, exc.kind)
            raise self._failure(exc) from None
        if response.status != 200:
            try:
                data, _ = read_body(response, ERROR_BODY_MAX_BYTES)
            except TransportError:
                data = b""
            finally:
                response.close()
            log.info("assistant %s: status %d after %.1f s", self.id, response.status,
                     time.monotonic() - started)
            raise errors.from_status(response.status, data, response.headers,
                                     provider=self.name, model=self.model,
                                     secret=self._secret())
        return response

    def events(self, response: Response) -> "Callable[[], list[SseEvent]]":
        """A reader of the response's SSE events: each call returns the next batch, an
        empty list at the end."""
        decoder = SseDecoder()
        done = [False]

        def more() -> list[SseEvent]:
            while not done[0]:
                chunk = response.read(READ_CHUNK_BYTES)
                if not chunk:
                    done[0] = True
                    return decoder.finish()
                found = decoder.feed(chunk)
                if found:
                    return found
            return []
        return more

    def stream(self, system: str, messages: Sequence[Message],
               on_event: Callable[[StreamEvent], None]) -> Turn:
        """One model step: send, then decode the stream. ``ProviderError`` for every
        failure (cancel included, kind ``cancelled``); exceptions ``on_event`` raises pass
        through after the response is closed."""
        response = self._send_step(system, messages)
        try:
            return self._decode(self.events(response), on_event)
        except (TransportError, SseError) as exc:
            raise self._failure(exc) from None
        finally:
            response.close()

    def _send_step(self, system: str, messages: Sequence[Message]) -> Response:
        return self._open("POST", self.endpoint.target(self.API_PATH),
                          self.request_body(system, messages), stream=True)

    def request_body(self, system: str, messages: Sequence[Message]) -> bytes:
        raise NotImplementedError

    def _decode(self, events: Callable[[], list[SseEvent]],
                on_event: Callable[[StreamEvent], None]) -> Turn:
        raise NotImplementedError

    # -- model lists (Test connection) --------------------------------------------------------

    def _models_target(self) -> str:
        return self.endpoint.target(self.MODELS_PATH)

    def list_models(self) -> list[str]:
        """The server's model ids (escaped, at most 1,000); ``ProviderError`` otherwise."""
        response = self._open("GET", self._models_target(), None, stream=False)
        try:
            data, more = read_body(response, MODEL_LIST_MAX_BYTES)
        except TransportError as exc:
            raise self._failure(exc) from None
        finally:
            response.close()
        if more:
            raise errors.malformed(self.name)
        try:
            found = loads(data.decode("utf-8"))
        except (SseError, UnicodeDecodeError):
            raise errors.malformed(self.name) from None
        rows = found.get("data") if isinstance(found, dict) else None
        if not isinstance(rows, list):
            raise errors.malformed(self.name)
        ids: list[str] = []
        seen: set[str] = set()
        for row in rows:
            model = row.get("id") if isinstance(row, dict) else None
            if type(model) is not str or not model:
                continue
            shown = visible(model)[:MODEL_ID_MAX_CHARS]
            if shown not in seen:
                seen.add(shown)
                ids.append(shown)
            if len(ids) >= MODEL_IDS_MAX:
                break
        return ids


def parse_args(raw: str) -> object:
    """A tool call's arguments: the JSON object, or None (bad JSON or not an object)."""
    if not raw.strip():
        return {}
    try:
        value = loads(raw)
    except SseError:
        return None
    return value if isinstance(value, dict) else None


def text_of(value: object) -> str:
    """A streamed string field, or "" (a wrong type is the caller's malformed case)."""
    return value if type(value) is str else ""


def is_anthropic(message: AssistantTurn) -> bool:
    return message.native is not None and message.native[0] == ANTHROPIC


__all__ = ["AssistantTurn", "BLOCKS_MAX", "CALLS_MAX", "CALL_ARGS_MAX_BYTES", "EVENT_CALL",
           "EVENT_TEXT", "MODEL_IDS_MAX", "MODEL_ID_MAX_CHARS", "MODEL_LIST_MAX_BYTES",
           "Message", "Provider", "STOP_END", "STOP_LENGTH", "STOP_REFUSAL", "STOP_TOOLS",
           "StreamEvent", "ToolCall", "ToolResult", "ToolResults", "Turn", "USAGE_MAX",
           "Usage", "UserTurn", "count", "dumps", "is_anthropic", "parse_args", "text_of"]

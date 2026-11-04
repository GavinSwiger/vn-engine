"""What the author reads when a request fails (F48 ``04-technical.md`` §3.1, §7.5; 01 §6.6,
§4.4, PR-F48-25, PR-F48-30; ``05-security.md`` SEC-F48-13, -14, -19).

Why this module exists: a provider, a proxy or a local server can fail in many ways, and the
author should see one plain sentence that says what to do, never a stack trace, a raw body or
the key. Every failure becomes a ``ProviderError`` whose ``text`` is one of 01 §6.6's texts.

- ``from_status(status, body, headers, …)``: an HTTP status with its (≤ 64 KiB) error body.
  Any 3xx is an error (no redirect is ever followed, SEC-F48-18). Credit and too-long bodies
  are recognised by their error type, code or message, whatever the status.
- ``from_error_object(obj, …)``: a provider's JSON error (a body, or an SSE ``error`` event).
- ``from_transport(exc, …)``: a ``TransportError`` (network, TLS, idle, deadline…).
- "Other" texts quote the provider's message through ``echo()`` (redaction, key shapes,
  escapes, 300 characters), after removing the key's own value (SEC-F48-14).

``TransportError`` and ``AddressError`` are defined here so ``transport`` can raise them and
this module needs nothing that opens a socket.
"""

import json
import math
from collections.abc import Mapping
from typing import Final

from engine.core.redact import KEY_TOKEN, echo

# --- 01 §6.6 texts ----------------------------------------------------------------------------

NO_KEY: Final = ("Add an API key in Studio settings ▸ AI first, or use your Claude plan "
                 "through Help ▸ Connect an AI app.")
BAD_KEY: Final = "{provider} didn't accept the API key. Check it in Studio settings ▸ AI."
# An Admin API key (sk-ant-admin…) manages an organization and can't send messages.
NOT_A_CHAT_KEY: Final = ("This is an Admin key, which can't send messages. Make a regular API "
                         "key under API keys in the Claude Console, then paste it in Studio "
                         "settings ▸ AI.")
FORBIDDEN: Final = ("This API key can't use {model}. Pick another model or check your "
                    "{provider} account.")
NO_MODEL: Final = "{provider} has no model named {model}. Pick another in Studio settings ▸ AI."
LIMITED: Final = "{provider} is limiting requests right now. Try again in {seconds} s."
LIMITED_NO_HINT: Final = "{provider} is limiting requests right now. Try again in a minute."
BUSY: Final = "{provider} is busy right now. Try again in a minute."
CREDIT: Final = ("Your {provider} account is out of API credit, which is separate from a "
                 "chat plan. Add credit on {provider}'s website, then try again.")
# Added for Anthropic: a Claude plan works through Claude Code or Claude Desktop instead.
CREDIT_PLAN: Final = " Or use your Claude plan: Help ▸ Connect an AI app."
CLAUDE_PROVIDER: Final = "Anthropic"
NETWORK: Final = "Couldn't reach {host}. Check your internet connection."
NETWORK_LOCAL: Final = "Couldn't reach {host}. Is the server running?"
TLS: Final = "Couldn't make a secure connection to {host}."
IDLE: Final = "{provider} stopped answering. Try again."
TOO_LARGE: Final = "This chat is too long for {model}. Start a new chat."
TOKEN_LIMIT: Final = ("This chat has used {n} tokens, your limit. Start a new chat or raise "
                      "the limit in Studio settings ▸ AI.")
STEP_LIMIT: Final = 'Stopped after {n} steps. Send "continue" to let it go on.'
PLAIN_HTTP: Final = "Use an https:// address. Only a server on this computer may use http://."
LOCALHOST_NOT_LOCAL: Final = ("localhost on this computer points somewhere else, so Studio "
                              "won't send to it.")
OTHER: Final = "{provider} returned an error: {message}"
OTHER_MAX_CHARS: Final = 300
MALFORMED: Final = "{provider} sent an answer Studio couldn't read."      # 01 §4.4
WAITING: Final = "Waiting {seconds} s for {provider}…"                   # PR-F48-30

# --- Texts 01 doesn't name (S6/S8 deltas; build-notes) ------------------------------------------

BAD_ADDRESS: Final = ("That server address can't be used. Type a full address such as "
                      "http://localhost:11434/v1.")
DEADLINE: Final = "The answer took longer than 10 minutes, so Studio stopped it."
ANSWER_TOO_LONG: Final = "The answer reached Studio's length limit, so it stopped there."
REFUSED: Final = "{provider} declined to answer this request."
CUT_OFF: Final = "The answer reached its length limit before it was done."
KEY_ELSEWHERE: Final = ("Studio didn't send the request: the saved key belongs to another "
                        "server.")
REQUEST_FAILED: Final = "Studio couldn't send the request to {provider}."
REDIRECT: Final = "a redirect (HTTP {status}), which Studio doesn't follow"
HTTP_STATUS: Final = "HTTP {status}"

# PR-F48-30: the one automatic retry waits at most this long.
RETRY_MAX_S: Final = 30.0
ERROR_BODY_MAX_BYTES: Final = 64 * 1024


# --- Exceptions -------------------------------------------------------------------------------

class TransportError(Exception):
    """A request that failed below HTTP. ``kind`` is one of the class constants; the
    exception carries no text from the network or the key."""

    CONNECT: Final = "connect"         # DNS, refused, unreachable, a proxy's non-200 CONNECT
    TLS: Final = "tls"
    IDLE: Final = "idle"               # no data for the idle timeout
    DEADLINE: Final = "deadline"       # the 10-minute stream deadline
    CANCELLED: Final = "cancelled"
    LOCALHOST: Final = "localhost"     # localhost resolved off this computer
    HEADER: Final = "header"           # a header value Studio refused to send
    PROTOCOL: Final = "protocol"       # a reply that isn't HTTP

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class AddressError(ValueError):
    """A server address refused by ``parse_address``; ``text`` is the author's text."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text


class KeyMismatchError(RuntimeError):
    """A key whose provider or origin isn't the endpoint's (SEC-F48-16). Nothing was sent."""

    text = KEY_ELSEWHERE


class ProviderError(Exception):
    """A failed request: ``text`` is what the author reads; ``kind`` names the case;
    ``retry_after`` is the server's hint in seconds, if any."""

    def __init__(self, text: str, kind: str, *, status: int | None = None,
                 retry_after: float | None = None) -> None:
        super().__init__(text)
        self.text = text
        self.kind = kind
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        """PR-F48-30: 429, 503 or 529 with a hint of at most 30 s."""
        return (self.kind in ("limited", "busy") and self.retry_after is not None
                and self.retry_after <= RETRY_MAX_S)


# --- Helpers ----------------------------------------------------------------------------------

def scrub(text: str, secret: str | None) -> str:
    """``text`` without ``secret`` (the key in use), before ``echo`` masks the rest."""
    if secret and len(secret) >= 4:
        text = text.replace(secret, KEY_TOKEN)
    return text


def other(provider: str, message: str, *, secret: str | None = None,
          status: int | None = None) -> ProviderError:
    shown = echo(scrub(message, secret), OTHER_MAX_CHARS)
    return ProviderError(OTHER.format(provider=provider, message=shown), "other", status=status)


def malformed(provider: str) -> ProviderError:
    return ProviderError(MALFORMED.format(provider=provider), "malformed")


def seconds_text(seconds: float) -> str:
    return f"{max(1, math.ceil(seconds)):,}"


def retry_after(headers: Mapping[str, str]) -> float | None:
    """The ``retry-after`` hint in seconds (or ``retry-after-ms``), 0 to 3,600; else None."""
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            value = float(raw.strip()) * scale
        except ValueError:
            continue
        if math.isfinite(value) and 0 <= value <= 3600:
            return value
    return None


def _error_fields(obj: object) -> tuple[str, str, str]:
    """(type, code, message) of an Anthropic or OpenAI error object; "" where missing."""
    err = obj.get("error") if isinstance(obj, dict) else None
    if isinstance(err, str):
        return "", "", err
    if not isinstance(err, dict):
        err = obj if isinstance(obj, dict) else {}
    found = []
    for key in ("type", "code", "message"):
        value = err.get(key)
        found.append(value if type(value) is str else "")
    return found[0], found[1], found[2]


def _has(message: str, *needles: str) -> bool:
    low = message.lower()
    return any(needle in low for needle in needles)


def classify(status: int | None, kind: str, code: str, message: str, *, provider: str,
             model: str, retry: float | None = None, secret: str | None = None) -> ProviderError:
    """The error for a status (None for a stream ``error`` event) and an error's fields."""
    names = {"provider": provider, "model": echo(model, 120)}
    if status is not None and 300 <= status < 400:
        return other(provider, REDIRECT.format(status=status), status=status)
    if (status == 402 or kind == "billing_error" or code == "insufficient_quota"
            or _has(message, "credit balance", "insufficient_quota", "exceeded your current quota")):
        text = CREDIT.format(**names) + (CREDIT_PLAN if provider == CLAUDE_PROVIDER else "")
        return ProviderError(text, "credit", status=status)
    if (status == 413 or kind == "request_too_large" or code == "context_length_exceeded"
            or _has(message, "prompt is too long", "context length", "context window",
                    "maximum context", "too many tokens")):
        return ProviderError(TOO_LARGE.format(**names), "too_large", status=status)
    if _has(message, "not scoped to a workspace"):
        return ProviderError(NOT_A_CHAT_KEY, "key", status=status)
    if status == 401 or kind == "authentication_error" or code == "invalid_api_key":
        return ProviderError(BAD_KEY.format(**names), "key", status=status)
    if status == 403 or kind == "permission_error":
        return ProviderError(FORBIDDEN.format(**names), "forbidden", status=status)
    if status == 404 or kind == "not_found_error" or code == "model_not_found":
        return ProviderError(NO_MODEL.format(**names), "model", status=status)
    if status == 429 or kind == "rate_limit_error" or code == "rate_limit_exceeded":
        text = (LIMITED.format(seconds=seconds_text(retry), **names) if retry is not None
                else LIMITED_NO_HINT.format(**names))
        return ProviderError(text, "limited", status=status, retry_after=retry)
    if status in (503, 529) or kind == "overloaded_error":
        return ProviderError(BUSY.format(**names), "busy", status=status, retry_after=retry)
    if message:
        return other(provider, message, secret=secret, status=status)
    return other(provider, HTTP_STATUS.format(status=status) if status else kind or "error",
                 secret=secret, status=status)


def _body_object(body: bytes) -> object:
    try:
        return json.loads(body[:ERROR_BODY_MAX_BYTES].decode("utf-8"))
    except (ValueError, RecursionError):
        return None


def from_status(status: int, body: bytes, headers: Mapping[str, str], *, provider: str,
                model: str, secret: str | None = None) -> ProviderError:
    """An HTTP error status (anything but 200; 3xx included) and its body."""
    obj = _body_object(body)
    kind, code, message = _error_fields(obj)
    if obj is None and body and not 300 <= status < 400:
        message = body[:ERROR_BODY_MAX_BYTES].decode("utf-8", "replace")
    return classify(status, kind, code, message, provider=provider, model=model,
                    retry=retry_after(headers), secret=secret)


def from_error_object(obj: object, *, provider: str, model: str,
                      secret: str | None = None) -> ProviderError:
    """A provider error sent inside a stream (Anthropic's ``error`` event)."""
    kind, code, message = _error_fields(obj)
    return classify(None, kind, code, message, provider=provider, model=model, secret=secret)


def from_transport(exc: TransportError, *, provider: str, host: str,
                   loopback: bool) -> ProviderError:
    """A transport failure. ``cancelled`` is an error too; the chat shows "(stopped)"."""
    kind = exc.kind
    if kind == TransportError.TLS:
        return ProviderError(TLS.format(host=host), "tls")
    if kind == TransportError.IDLE:
        return ProviderError(IDLE.format(provider=provider), "idle")
    if kind == TransportError.DEADLINE:
        return ProviderError(DEADLINE, "deadline")
    if kind == TransportError.LOCALHOST:
        return ProviderError(LOCALHOST_NOT_LOCAL, "local")
    if kind == TransportError.CANCELLED:
        return ProviderError("", "cancelled")
    if kind == TransportError.HEADER:
        return ProviderError(REQUEST_FAILED.format(provider=provider), "request")
    if kind == TransportError.PROTOCOL:
        return malformed(provider)
    text = NETWORK_LOCAL if loopback else NETWORK
    return ProviderError(text.format(host=host), "network")


__all__ = ["ANSWER_TOO_LONG", "AddressError", "BAD_ADDRESS", "BAD_KEY", "BUSY", "CREDIT",
           "CUT_OFF", "DEADLINE", "ERROR_BODY_MAX_BYTES", "FORBIDDEN", "IDLE", "KEY_ELSEWHERE",
           "KeyMismatchError", "LIMITED", "LIMITED_NO_HINT", "LOCALHOST_NOT_LOCAL", "MALFORMED",
           "NETWORK", "NETWORK_LOCAL", "NO_KEY", "NO_MODEL", "OTHER", "OTHER_MAX_CHARS",
           "PLAIN_HTTP", "ProviderError", "REDIRECT", "REFUSED", "REQUEST_FAILED", "RETRY_MAX_S",
           "STEP_LIMIT", "TLS", "TOKEN_LIMIT", "TOO_LARGE", "TransportError", "WAITING",
           "classify", "from_error_object", "from_status", "from_transport", "malformed",
           "other", "retry_after", "scrub", "seconds_text"]

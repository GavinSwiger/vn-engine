"""F48 step S6: provider and network failures → 01 §6.6's texts (AC-F48-51; PR-F48-25,
PR-F48-30; SEC-F48-14)."""

import json

import pytest

from engine.core import redact
from engine.tools.assistant.providers import errors
from engine.tools.assistant.providers.errors import TransportError

P = {"provider": "Anthropic", "model": "claude-sonnet-5-5"}


def body(kind: str = "", message: str = "", code: str = "") -> bytes:
    err = {"type": kind, "message": message}
    if code:
        err["code"] = code
    return json.dumps({"type": "error", "error": err}).encode()


@pytest.mark.parametrize("status, data, headers, text, kind", [
    (401, body("authentication_error", "invalid x-api-key"), {},
     errors.BAD_KEY.format(**P), "key"),
    (403, body("permission_error", "no"), {}, errors.FORBIDDEN.format(**P), "forbidden"),
    (400, body("invalid_request_error", "This API key is not scoped to a workspace"), {},
     errors.NOT_A_CHAT_KEY, "key"),
    (404, body("not_found_error", "model: x"), {}, errors.NO_MODEL.format(**P), "model"),
    (404, json.dumps({"error": {"message": "nope", "code": "model_not_found"}}).encode(), {},
     errors.NO_MODEL.format(**P), "model"),
    (429, body("rate_limit_error", "slow"), {"retry-after": "12"},
     errors.LIMITED.format(seconds="12", **P), "limited"),
    (429, body("rate_limit_error", "slow"), {"retry-after-ms": "1500"},
     errors.LIMITED.format(seconds="2", **P), "limited"),
    (429, body("rate_limit_error", "slow"), {}, errors.LIMITED_NO_HINT.format(**P), "limited"),
    (429, body("rate_limit_error"), {"retry-after": "soon"}, errors.LIMITED_NO_HINT.format(**P),
     "limited"),
    (503, b"Service Unavailable", {}, errors.BUSY.format(**P), "busy"),
    (529, body("overloaded_error", "Overloaded"), {}, errors.BUSY.format(**P), "busy"),
    (400, body("invalid_request_error", "Your credit balance is too low to access the API."),
     {}, errors.CREDIT.format(**P), "credit"),
    (402, body("billing_error", "pay"), {}, errors.CREDIT.format(**P), "credit"),
    (429, json.dumps({"error": {"message": "You exceeded your current quota",
                                "type": "insufficient_quota",
                                "code": "insufficient_quota"}}).encode(),
     {"retry-after": "1"}, errors.CREDIT.format(**P), "credit"),
    (413, body("request_too_large", "big"), {}, errors.TOO_LARGE.format(**P), "too_large"),
    (400, body("invalid_request_error", "prompt is too long: 1200000 tokens > 1000000"), {},
     errors.TOO_LARGE.format(**P), "too_large"),
    (400, json.dumps({"error": {"message": "This model's maximum context length is 128000",
                                "code": "context_length_exceeded"}}).encode(), {},
     errors.TOO_LARGE.format(**P), "too_large"),
    (302, b"", {"location": "http://other/"},
     errors.OTHER.format(provider="Anthropic", message=errors.REDIRECT.format(status=302)),
     "other"),
    (500, body("api_error", "Internal server error"), {},
     errors.OTHER.format(provider="Anthropic", message="Internal server error"), "other"),
    (502, b"", {}, errors.OTHER.format(provider="Anthropic", message="HTTP 502"), "other"),
])
def test_ac51_status_table(status, data, headers, text, kind):
    failure = errors.from_status(status, data, headers, **P)
    assert (failure.text, failure.kind, failure.status) == (text, kind, status)


def test_ac51_other_texts_mask_keys_and_stay_one_short_line():
    key = "abcdefgh-my-own-key-1234"
    redact.set_secret("test-errors", "zzzz-registered-secret-zzzz")
    try:
        data = body("invalid_request_error",
                    f"bad key {key} sk-ant-api03-abcdef zzzz-registered-secret-zzzz\n"
                    "‮" + "x" * 1000)
        failure = errors.from_status(400, data, {}, secret=key, **P)
    finally:
        redact.set_secret("test-errors", None)
    shown = failure.text
    assert key not in shown and "sk-ant-api03" not in shown and "registered" not in shown
    assert shown.count(redact.KEY_TOKEN) == 3
    assert "\n" not in shown and "‮" not in shown
    assert len(shown) <= len(errors.OTHER.format(provider="Anthropic", message="")) + 300


@pytest.mark.parametrize("kind, loopback, text", [
    (TransportError.CONNECT, False, errors.NETWORK.format(host="api.anthropic.com")),
    (TransportError.CONNECT, True, errors.NETWORK_LOCAL.format(host="api.anthropic.com")),
    (TransportError.TLS, False, errors.TLS.format(host="api.anthropic.com")),
    (TransportError.IDLE, False, errors.IDLE.format(provider="Anthropic")),
    (TransportError.DEADLINE, False, errors.DEADLINE),
    (TransportError.LOCALHOST, True, errors.LOCALHOST_NOT_LOCAL),
    (TransportError.PROTOCOL, False, errors.MALFORMED.format(provider="Anthropic")),
    (TransportError.HEADER, False, errors.REQUEST_FAILED.format(provider="Anthropic")),
])
def test_ac51_transport_table(kind, loopback, text):
    failure = errors.from_transport(TransportError(kind), provider="Anthropic",
                                    host="api.anthropic.com", loopback=loopback)
    assert failure.text == text


def test_stream_error_events_and_retry_rule():
    busy = errors.from_error_object({"type": "error", "error": {"type": "overloaded_error",
                                                                "message": "Overloaded"}}, **P)
    assert busy.text == errors.BUSY.format(**P)
    assert not busy.retryable                              # no hint inside a stream
    assert errors.from_status(429, b"", {"retry-after": "30"}, **P).retryable
    assert not errors.from_status(429, b"", {"retry-after": "31"}, **P).retryable
    assert errors.from_status(529, b"", {"retry-after": "2"}, **P).retryable
    assert not errors.from_status(401, b"", {"retry-after": "2"}, **P).retryable
    assert errors.from_error_object("junk", **P).text.startswith("Anthropic returned an error")

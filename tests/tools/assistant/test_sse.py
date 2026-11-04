"""F48 step S6: the byte-bounded SSE decoder and strict JSON (AC-F48-43's framing, AC-F48-54;
SEC-F48-19, AB-16). Provider event decoding is in ``test_providers.py`` (S8)."""

import json
import tracemalloc

import pytest

from engine.tools.assistant.providers.sse import (
    SSE_LINE_MAX_BYTES, SseDecoder, SseError, SseEvent, loads)

ANTHROPIC = (
    b"event: message_start\n"
    b'data: {"type":"message_start","message":{"id":"msg_1","usage":{"input_tokens":5}}}\n\n'
    b"event: ping\ndata: {\"type\": \"ping\"}\n\n"
    b"event: content_block_delta\n"
    b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hi"}}\n\n'
    b"event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n")
OPENAI = (b'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}\n\n'
          b": keep-alive\n\n"
          b"data: [DONE]\n\n")


def decode(data: bytes, size: int) -> list[SseEvent]:
    decoder = SseDecoder()
    events = []
    for start in range(0, len(data), size):
        events += decoder.feed(data[start:start + size])
    return events + decoder.finish()


@pytest.mark.parametrize("size", [1, 2, 7, 1000])
def test_ac43_fixtures_decode_whatever_the_chunking(size):
    events = decode(ANTHROPIC, size)
    assert [e.event for e in events] == ["message_start", "ping", "content_block_delta",
                                         "message_stop"]
    assert json.loads(events[2].data)["delta"]["text"] == "Hi"
    assert decode(OPENAI, size) == [
        SseEvent("", '{"choices":[{"index":0,"delta":{"content":"Hi"}}]}'),
        SseEvent("", "[DONE]")]
    crlf = ANTHROPIC.replace(b"\n", b"\r\n")
    assert decode(crlf, size) == decode(ANTHROPIC, 1000)
    cr = OPENAI.replace(b"\n", b"\r")
    assert decode(cr, size) == decode(OPENAI, 1000)


def test_multi_line_data_comments_and_an_unterminated_last_event():
    data = b"\xef\xbb\xbfevent:e\ndata:a\ndata: b\nid: 7\nretry: 5\n\n:c\n\ndata: tail"
    assert decode(data, 3) == [SseEvent("e", "a\nb"), SseEvent("", "tail")]


def test_ac54_one_100_mb_line_stops_at_the_line_cap_with_bounded_memory():
    decoder = SseDecoder()
    chunk = b"x" * (256 * 1024)
    tracemalloc.start()
    with pytest.raises(SseError):
        for _ in range(400):                      # up to 100 MiB
            decoder.feed(chunk)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert decoder.total <= SSE_LINE_MAX_BYTES + len(chunk)
    assert peak < 8 * 1024 * 1024


def test_ac54_endless_pings_stop_at_the_stream_cap():
    decoder = SseDecoder(total_max=1024 * 1024)
    ping = b"event: ping\ndata: {\"type\": \"ping\"}\n\n"
    with pytest.raises(SseError) as caught:
        for _ in range(1_000_000):
            decoder.feed(ping)
    assert caught.value.reason == "stream too large"


def test_ac54_event_data_cap_and_invalid_utf8():
    decoder = SseDecoder(data_max=1000)
    with pytest.raises(SseError):
        for _ in range(20):
            decoder.feed(b"data: " + b"y" * 100 + b"\n")
    with pytest.raises(SseError) as caught:
        SseDecoder().feed(b"data: \xff\xfe\n\n")
    assert caught.value.reason == "not UTF-8"


@pytest.mark.parametrize("text", [
    "[" * 100_000 + "]" * 100_000,
    '{"a": NaN}',
    '{"a": Infinity}',
    '"\\ud800"',
    '{"\\udc00": 1}',
    '{"a": ["ok", {"b": "x\\ud83d"}]}',
    "{",
    "",
])
def test_ac54_strict_json_refuses(text):
    with pytest.raises(SseError):
        loads(text)


def test_strict_json_keeps_valid_pairs_and_big_numbers():
    assert loads('{"t": "\\ud83d\\ude00", "n": 1e999}') == {"t": "😀", "n": float("inf")}

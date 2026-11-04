"""F48 step S6: the strict transport (AC-F48-37, AC-F48-38; 04 §7.5 "Transport";
SEC-F48-17, SEC-F48-18 with 05 §10's CONNECT clauses; 07 9(c)).

The servers here listen on 127.0.0.1 only; nothing reaches another machine."""

import ast
import socket
import ssl
import threading
import time
from pathlib import Path

import pytest

from engine.tools.assistant.providers import errors
from engine.tools.assistant.providers.errors import TransportError
from engine.tools.assistant.providers.transport import (
    Endpoint, FakeReply, FakeTransport, HttpTransport, Proxy, Request, StaticResolver,
    parse_address, proxy_for, read_body, tls_context)

PACKAGE = Path(__file__).resolve().parents[3] / "engine" / "tools" / "assistant"


class LocalServer:
    """A one-thread TCP server on 127.0.0.1: ``handler(conn, data_so_far)`` runs per
    connection after the request head arrives; ``connections`` counts accepts and
    ``received`` keeps each connection's bytes."""

    def __init__(self, handler) -> None:
        self.handler = handler
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.connections = 0
        self.received: list[bytes] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        self.sock.settimeout(0.1)
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            self.connections += 1
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn: socket.socket) -> None:
        conn.settimeout(5)
        data = b""
        try:
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            self.received.append(data)
            self.handler(conn, data)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def close(self) -> None:
        self._stop.set()
        self.sock.close()
        self._thread.join(2)


@pytest.fixture
def servers():
    made: list[LocalServer] = []

    def make(handler) -> LocalServer:
        server = LocalServer(handler)
        made.append(server)
        return server

    yield make
    for server in made:
        server.close()


def reply(body: bytes = b"ok", status: str = "200 OK", extra: str = ""):
    def handler(conn, _data):
        conn.sendall(f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\n{extra}"
                     f"Connection: close\r\n\r\n".encode() + body)
    return handler


def stall(conn, _data):
    conn.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n")
    time.sleep(3)


def get(endpoint: Endpoint, target: str = "/x", **headers) -> Request:
    return Request("GET", endpoint, target, tuple(headers.items()))


# --- AC-F48-37: the address table (AB-13) -------------------------------------------------------

@pytest.mark.parametrize("address, text", [
    ("http://localhost.evil.com", errors.PLAIN_HTTP),
    ("http://127.0.0.1@evil.com", errors.BAD_ADDRESS),
    ("http://u:p@localhost", errors.BAD_ADDRESS),
    ("http://0.0.0.0", errors.PLAIN_HTTP),
    ("http://[::ffff:127.0.0.1]", errors.PLAIN_HTTP),
    ("http://127.1", errors.PLAIN_HTTP),
    ("http://LOCALHOST.", errors.PLAIN_HTTP),
    ("http://10.0.0.5", errors.PLAIN_HTTP),
    ("http://example.com/v1", errors.PLAIN_HTTP),
    ("ftp://x", errors.PLAIN_HTTP),
    ("file:///etc/passwd", errors.PLAIN_HTTP),
    ("https://x#y", errors.BAD_ADDRESS),
    ("https://x/v1?key=1", errors.BAD_ADDRESS),
    ("https://" + "a" * 2_990 + ".com", errors.BAD_ADDRESS),
    ("https://exa mple.com", errors.BAD_ADDRESS),
    ("https://example.com/‮v1", errors.BAD_ADDRESS),
    ("https://éxample.com", errors.BAD_ADDRESS),
    ("http://localhost:99999", errors.BAD_ADDRESS),
    ("http://[::1%1]:80", errors.BAD_ADDRESS),
    ("", errors.BAD_ADDRESS),
    (None, errors.BAD_ADDRESS),
])
def test_ac37_refused_addresses(address, text):
    with pytest.raises(errors.AddressError) as caught:
        parse_address(address)
    assert caught.value.text == text


@pytest.mark.parametrize("address, origin, loopback", [
    ("http://localhost:11434/v1", "http://localhost:11434", True),
    ("http://LOCALHOST:1234/v1/", "http://localhost:1234", True),
    ("http://127.0.0.1:8080", "http://127.0.0.1:8080", True),
    ("http://127.255.0.9/v1", "http://127.255.0.9:80", True),
    ("http://[::1]:1234/v1", "http://[::1]:1234", True),
    ("https://api.anthropic.com/v1", "https://api.anthropic.com:443", False),
    ("https://llm.example.org:8443/api/v1", "https://llm.example.org:8443", False),
])
def test_ac37_allowed_addresses(address, origin, loopback):
    endpoint = parse_address(address)
    assert endpoint.origin == origin
    assert endpoint.loopback is loopback
    assert not endpoint.path.endswith("/")


def test_ac37_localhost_resolving_off_this_computer_is_refused(servers):
    server = servers(reply())
    for answer in (["93.184.216.34"], ["127.0.0.1", "10.0.0.5"], ["::ffff:127.0.0.1"], []):
        resolver = StaticResolver(answer)
        transport = HttpTransport(resolver=resolver)
        with pytest.raises(TransportError) as caught:
            transport.open(get(Endpoint("http", "localhost", server.port)))
        assert caught.value.kind == TransportError.LOCALHOST
        assert resolver.calls == [("localhost", server.port)]
    assert server.connections == 0
    assert errors.from_transport(TransportError(TransportError.LOCALHOST), provider="x",
                                 host="localhost", loopback=True).text \
        == errors.LOCALHOST_NOT_LOCAL


def test_ac37_localhost_connects_by_address_with_its_host_header(servers):
    server = servers(reply(b"hi"))
    resolver = StaticResolver(["127.0.0.1", "::1"])
    transport = HttpTransport(resolver=resolver)
    response = transport.open(get(parse_address(f"http://localhost:{server.port}/v1"),
                                  "/v1/models"))
    assert (response.status, read_body(response, 100)) == (200, (b"hi", False))
    response.close()
    head = server.received[0].decode()
    assert head.startswith("GET /v1/models HTTP/1.1\r\n")
    assert f"\r\nHost: localhost:{server.port}\r\n" in head
    assert head.count("Host:") == 1
    assert resolver.calls == [("localhost", server.port)]


def test_ac37_tls_context_verifies():
    context = tls_context()
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert HttpTransport().context.check_hostname is True


def _calls_and_names(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, (ast.ImportFrom, ast.Import)):
            found.update(alias.name for alias in node.names)
    return found


def test_sec18_no_unverified_tls_debug_output_or_opener_in_the_package():
    """SEC-F48-14/-18 (AST): no unverified context, no ``check_hostname = False``, no
    ``http.client`` debug level, no ``urlopen`` or opener; ``getaddrinfo`` and the proxy
    settings only in ``transport.py`` (07 9(c))."""
    for path in sorted(PACKAGE.rglob("*.py")):
        names = _calls_and_names(path)
        text = path.read_text(encoding="utf-8")
        for banned in ("_create_unverified_context", "CERT_NONE", "set_debuglevel",
                       "debuglevel", "urlopen", "build_opener", "OpenerDirector",
                       "HTTPRedirectHandler"):
            assert banned not in names, f"{path.name} uses {banned}"
        assert "check_hostname = False" not in text and "check_hostname=False" not in text
        if path.name != "transport.py":
            for only_here in ("getaddrinfo", "getproxies", "proxy_bypass"):
                assert only_here not in names, f"{path.name} uses {only_here}"


# --- AC-F48-38: no redirect is followed; loopback skips the proxy (AB-14) ----------------------

def test_ac38_a_302_is_returned_not_followed(servers):
    other = servers(reply(b"other"))
    first = servers(reply(b"", "302 Found",
                          f"Location: http://127.0.0.1:{other.port}/\r\n"))
    transport = HttpTransport()
    response = transport.open(Request("POST", parse_address(f"http://127.0.0.1:{first.port}"),
                                      "/v1/chat/completions",
                                      (("Authorization", "Bearer sk-test-123456789"),), b"{}"))
    assert response.status == 302
    body, _ = read_body(response, 1000)
    response.close()
    failure = errors.from_status(302, body, response.headers, provider="Example", model="m")
    assert failure.text == errors.OTHER.format(
        provider="Example", message=errors.REDIRECT.format(status=302))
    time.sleep(0.2)
    assert first.connections == 1
    assert other.connections == 0


def test_ac38_loopback_skips_the_proxy(servers, monkeypatch):
    proxy = servers(reply(b"from the proxy"))
    target = servers(reply(b"direct"))
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, f"http://127.0.0.1:{proxy.port}")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    for address in (f"http://127.0.0.1:{target.port}", f"http://localhost:{target.port}"):
        transport = HttpTransport(resolver=StaticResolver(["127.0.0.1"]))
        response = transport.open(get(parse_address(address)))
        assert read_body(response, 100) == (b"direct", False)
        response.close()
    assert proxy.connections == 0
    assert target.connections == 2


# --- CONNECT tunnels (05 §10) -------------------------------------------------------------------

def test_proxy_settings_give_only_a_connect_tunnel():
    remote = parse_address("https://api.anthropic.com/v1")
    found = proxy_for(remote, proxies=lambda: {"https": "http://al%40x:p%3Ass@proxy.lan:3128"},
                      bypass=lambda host: False)
    assert found == Proxy("proxy.lan", 3128, "Basic YWxAeDpwOnNz")
    assert "p:ss" not in repr(found) and "YWx" not in repr(found)
    assert proxy_for(remote, proxies=lambda: {"https": "proxy.lan:8080"},
                     bypass=lambda host: False) == Proxy("proxy.lan", 8080)
    for url in ("socks5://proxy.lan:1080", "https://proxy.lan:443", "", "http://"):
        assert proxy_for(remote, proxies=lambda: {"https": url}, bypass=lambda h: False) is None
    assert proxy_for(remote, proxies=lambda: {"http": "http://p:1"}, bypass=lambda h: False) \
        is None
    assert proxy_for(remote, proxies=lambda: {"https": "http://p:1"}, bypass=lambda h: True) \
        is None
    local = parse_address("http://localhost:1234")

    def never():
        raise AssertionError("loopback read the proxy settings")
    assert proxy_for(local, proxies=never, bypass=never) is None


def test_connect_carries_only_proxy_authorization_and_a_refusal_is_an_error(servers):
    proxy = servers(reply(b"", "407 Proxy Authentication Required"))
    transport = HttpTransport(proxies=lambda: {"https": f"http://al:secret@127.0.0.1:{proxy.port}"},
                              bypass=lambda host: False)
    request = Request("POST", parse_address("https://api.anthropic.com/v1"), "/v1/messages",
                      (("x-api-key", "sk-ant-api03-abcdefghijklmnop"),
                       ("anthropic-version", "2026-10-21")), b"{}")
    with pytest.raises(TransportError) as caught:
        transport.open(request)
    assert caught.value.kind == TransportError.CONNECT
    head = proxy.received[0].decode()
    assert head.startswith("CONNECT api.anthropic.com:443 HTTP/1.1\r\n")
    names = {line.split(":", 1)[0].lower() for line in head.split("\r\n")[1:] if line}
    assert names == {"host", "proxy-authorization"}
    assert "sk-ant" not in head and "anthropic-version" not in head
    failure = errors.from_transport(caught.value, provider="Anthropic",
                                    host="api.anthropic.com", loopback=False)
    assert failure.text == errors.NETWORK.format(host="api.anthropic.com")
    assert "secret" not in failure.text


# --- Timeouts, deadline, cancel -----------------------------------------------------------------

def test_idle_timeout_and_deadline(servers):
    server = servers(stall)
    transport = HttpTransport(idle_timeout=0.3)
    response = transport.open(get(parse_address(f"http://127.0.0.1:{server.port}")))
    assert response.read() == b"hello"
    started = time.monotonic()
    with pytest.raises(TransportError) as caught:
        response.read()
    assert caught.value.kind == TransportError.IDLE
    assert time.monotonic() - started < 2.5
    response.close()

    now = [0.0]
    transport = HttpTransport(clock=lambda: now[0], deadline=600)
    response = transport.open(get(parse_address(f"http://127.0.0.1:{server.port}")))
    now[0] = 600.0
    with pytest.raises(TransportError) as caught:
        response.read()
    assert caught.value.kind == TransportError.DEADLINE
    response.close()


def test_cancel_from_another_thread_ends_a_blocked_read(servers):
    server = servers(stall)
    transport = HttpTransport()
    response = transport.open(get(parse_address(f"http://127.0.0.1:{server.port}")))
    assert response.read() == b"hello"
    timer = threading.Timer(0.2, transport.cancel)
    timer.start()
    started = time.monotonic()
    with pytest.raises(TransportError) as caught:
        response.read()
    assert caught.value.kind == TransportError.CANCELLED
    assert time.monotonic() - started < 2
    with pytest.raises(TransportError):
        transport.open(get(parse_address(f"http://127.0.0.1:{server.port}")))


def test_refused_connection_and_bad_headers(servers):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with pytest.raises(TransportError) as caught:
        HttpTransport().open(get(parse_address(f"http://127.0.0.1:{port}")))
    assert caught.value.kind == TransportError.CONNECT
    server = servers(reply())
    endpoint = parse_address(f"http://127.0.0.1:{server.port}")
    for headers in ((("x-api-key", "sk-ant-x\r\nX-Evil: 1"),), (("Bad Name", "v"),),
                    (("x-api-key", "kéy"),)):
        for transport in (HttpTransport(), FakeTransport(FakeReply())):
            with pytest.raises(TransportError) as caught:
                transport.open(Request("GET", endpoint, "/x", headers))
            assert caught.value.kind == TransportError.HEADER
    assert server.connections == 0


def test_read_body_caps_and_fake_transport_records():
    fake = FakeTransport(FakeReply(200, {"Retry-After": "3"}, [b"a" * 70_000, b"b" * 70_000]))
    request = get(parse_address("https://api.openai.com/v1"), "/v1/models",
                  Authorization="Bearer k")
    response = fake.open(request)
    assert response.headers == {"retry-after": "3"}
    body, more = read_body(response, 100_000)
    assert (len(body), more) == (100_000, True)
    assert fake.requests == [request]
    assert request.header("authorization") == "Bearer k"
    assert "Bearer" not in repr(request)
    with pytest.raises(AssertionError):
        fake.open(request)

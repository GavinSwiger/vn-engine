"""One strict HTTP transport (F48 ``04-technical.md`` §7.5 "Transport"; 01 PR-F48-18;
``05-security.md`` SEC-F48-17, SEC-F48-18 with §10's CONNECT clauses, SEC-F48-19; 07 I-1,
9(c)).

Why this module exists: the author's key must reach only the server it was saved for.
``urllib.request`` follows a 302 from POST to GET keeping the auth header (also https →
http) and sends loopback traffic through ``HTTP_PROXY``, so requests go through
``http.client`` here, under these rules:

- ``parse_address``: ``urlsplit``, at most 2,048 printable ASCII characters, no userinfo,
  query or fragment. ``https`` may go to any host; ``http`` only to exactly ``localhost``, a
  full dotted 127.0.0.0/8 literal or ``::1`` (never ``0.0.0.0``, ``127.1``, ``localhost.``
  or an IPv4-mapped form).
- ``localhost`` is resolved once through the ``Resolver`` seam; every address must be
  loopback, and the request connects to the first by address with ``Host: localhost:<port>``,
  so a hosts file or resolver can't move it off this computer.
- TLS is ``ssl.create_default_context()`` (hostname checks, certificate checks) with TLS 1.2
  or higher. There is no unverified context anywhere in the package (a test checks).
- An https proxy (``getproxies``/``proxy_bypass``, the environment and, on Windows, the
  registry) is used only as a CONNECT tunnel: CONNECT carries at most
  ``Proxy-Authorization``, TLS checks the provider's host name end to end, a non-200
  CONNECT is an error, and the proxy's credentials reach no text or log. Proxy kinds
  ``http.client`` can't tunnel (``socks5://``, ``https://``) are ignored, never used in plain.
  Loopback never uses a proxy.
- 30 s to connect, then 60 s idle per read, and a 10-minute deadline per response.
- No redirect is ever followed: a 3xx comes back as a status, which ``errors`` makes an error.
- ``cancel()`` sets a flag and shuts the socket down (on Windows, where that doesn't wake a
  blocked ``recv``, it also closes the handle), which never blocks; the reading thread then
  gets ``TransportError(CANCELLED)``.

Only this module reads proxy settings and calls ``getaddrinfo("localhost")`` (9(c)).
``FakeTransport`` and ``StaticResolver`` let every test run without a network.
"""

import http.client
import ipaddress
import re
import socket
import ssl
import sys
import threading
import time
from base64 import b64encode
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol
from urllib.parse import unquote, urlsplit
from urllib.request import getproxies, proxy_bypass

from engine.tools.assistant.providers.errors import (
    BAD_ADDRESS,
    PLAIN_HTTP,
    AddressError,
    TransportError,
)

CONNECT_TIMEOUT_S: Final = 30.0
IDLE_TIMEOUT_S: Final = 60.0
STREAM_DEADLINE_S: Final = 600.0
ADDRESS_MAX_CHARS: Final = 2_048
READ_CHUNK_BYTES: Final = 64 * 1024
LOCALHOST: Final = "localhost"
_HOST_RE: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
                             r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*")
_TOKEN_RE: Final = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_PATH_RE: Final = re.compile(r"[\x21-\x7e]*")


# --- Addresses --------------------------------------------------------------------------------

def _loopback_literal(host: str) -> bool:
    """A full dotted IPv4 literal in 127.0.0.0/8, or exactly ``::1``."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv4Address):
        return host.count(".") == 3 and ip in ipaddress.IPv4Network("127.0.0.0/8")
    return ip == ipaddress.IPv6Address("::1") and ip.scope_id is None


@dataclass(frozen=True, slots=True)
class Endpoint:
    """A checked server address: ``host`` lower-case (IPv6 without brackets), ``path`` the
    base path with no final ``/`` (``/v1``), or ``""``."""

    scheme: str
    host: str
    port: int
    path: str = ""

    @property
    def loopback(self) -> bool:
        return self.host == LOCALHOST or _loopback_literal(self.host)

    @property
    def pinned(self) -> bool:
        """``localhost``: resolved once and connected by address."""
        return self.host == LOCALHOST

    @property
    def _url_host(self) -> str:
        return f"[{self.host}]" if ":" in self.host else self.host

    @property
    def origin(self) -> str:
        """``scheme://host:port`` (SEC-F48-16's binding; the port always written)."""
        return f"{self.scheme}://{self._url_host}:{self.port}"

    @property
    def display_host(self) -> str:
        """The host for texts: with the port unless it is the scheme's default."""
        default = 443 if self.scheme == "https" else 80
        return self._url_host if self.port == default else f"{self._url_host}:{self.port}"

    def target(self, sub: str) -> str:
        """The request path for ``sub`` (``/messages`` → ``/v1/messages``)."""
        return self.path + sub


def parse_address(text: object) -> Endpoint:
    """A server address as an ``Endpoint``; ``AddressError`` (01 §6.6's text) otherwise."""
    if type(text) is not str or not text or len(text) > ADDRESS_MAX_CHARS:
        raise AddressError(BAD_ADDRESS)
    if any(not 0x21 <= ord(char) <= 0x7E for char in text):
        raise AddressError(BAD_ADDRESS)        # controls, spaces, non-ASCII
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise AddressError(BAD_ADDRESS) from None
    scheme = parts.scheme.lower()
    if scheme not in ("https", "http"):
        raise AddressError(PLAIN_HTTP)
    netloc = parts.netloc
    if (not netloc or "@" in netloc or "#" in text or "?" in text or "%" in netloc
            or not _PATH_RE.fullmatch(parts.path)
            or (parts.path and not parts.path.startswith("/"))):
        raise AddressError(BAD_ADDRESS)
    host = parts.hostname or ""
    literal = True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        literal = False
    if netloc.startswith("[") and (not literal or ":" not in host):
        raise AddressError(BAD_ADDRESS)
    if not literal and not _HOST_RE.fullmatch(host):
        raise AddressError(PLAIN_HTTP if scheme == "http" else BAD_ADDRESS)
    if port == 0:
        raise AddressError(BAD_ADDRESS)
    if scheme == "http" and host != LOCALHOST and not _loopback_literal(host):
        raise AddressError(PLAIN_HTTP)
    if port is None:
        port = 443 if scheme == "https" else 80
    return Endpoint(scheme, host, port, parts.path.rstrip("/"))


# --- Resolver seam ----------------------------------------------------------------------------

class Resolver(Protocol):
    def resolve(self, host: str, port: int) -> Sequence[str]:
        """The addresses ``host`` resolves to, in the system's order."""
        ...


class SystemResolver:
    """``getaddrinfo`` (9(c): only for ``localhost``, only here)."""

    def resolve(self, host: str, port: int) -> Sequence[str]:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return [str(info[4][0]) for info in infos]


@dataclass
class StaticResolver:
    """A test resolver: fixed answers, every call recorded."""

    addresses: Sequence[str] = ("127.0.0.1",)
    calls: list[tuple[str, int]] = field(default_factory=list)

    def resolve(self, host: str, port: int) -> Sequence[str]:
        self.calls.append((host, port))
        return list(self.addresses)


def local_addresses(resolver: Resolver, port: int) -> list[str]:
    """``localhost``'s addresses, all loopback; ``TransportError(LOCALHOST)`` otherwise."""
    try:
        found = [address.split("%", 1)[0] for address in resolver.resolve(LOCALHOST, port)]
    except OSError:
        raise TransportError(TransportError.CONNECT) from None
    if not found or not all(_loopback_literal(address) for address in found):
        raise TransportError(TransportError.LOCALHOST)
    return found


# --- Proxies ----------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Proxy:
    """An http proxy to tunnel through. ``auth`` is the ``Proxy-Authorization`` value; it
    never appears in ``repr``."""

    host: str
    port: int
    auth: str | None = field(default=None, repr=False)


def proxy_for(endpoint: Endpoint, *,
              proxies: Callable[[], Mapping[str, str]] = getproxies,
              bypass: Callable[[str], object] = proxy_bypass) -> Proxy | None:
    """The CONNECT proxy for an https ``endpoint``, or None (loopback, bypassed, unset, or a
    kind ``http.client`` can't tunnel)."""
    if endpoint.loopback or endpoint.scheme != "https":
        return None
    try:
        url = proxies().get("https")
        if not url or bypass(endpoint.host):
            return None
        if "://" not in url:
            url = "http://" + url
        parts = urlsplit(url)
        if parts.scheme.lower() != "http" or not parts.hostname:
            return None
        port = parts.port or 80
    except (ValueError, OSError, TypeError, AttributeError):
        return None
    auth = None
    if parts.username is not None:
        pair = f"{unquote(parts.username)}:{unquote(parts.password or '')}"
        auth = "Basic " + b64encode(pair.encode("utf-8")).decode("ascii")
    return Proxy(parts.hostname, port, auth)


# --- Requests and responses -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Request:
    """One request. ``target`` is the path (``Endpoint.target``); ``headers`` are the
    provider's (auth included) and are never logged or shown."""

    method: str
    endpoint: Endpoint
    target: str
    headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    body: bytes | None = field(default=None, repr=False)

    def header(self, name: str) -> str | None:
        low = name.lower()
        return next((value for key, value in self.headers if key.lower() == low), None)


class Response(Protocol):
    status: int
    headers: Mapping[str, str]          # lower-case names, first value

    def read(self, limit: int = READ_CHUNK_BYTES) -> bytes:
        """Up to ``limit`` bytes as they arrive; ``b""`` at the end. ``TransportError``
        on idle, deadline, cancel or a broken connection."""
        ...

    def close(self) -> None: ...


class Transport(Protocol):
    def open(self, request: Request) -> Response: ...

    def cancel(self) -> None: ...


def read_body(response: Response, limit: int) -> tuple[bytes, bool]:
    """The whole body up to ``limit`` bytes, and whether there was more (then it stops)."""
    data = bytearray()
    while True:
        chunk = response.read(READ_CHUNK_BYTES)
        if not chunk:
            return bytes(data), False
        data += chunk
        if len(data) > limit:
            return bytes(data[:limit]), True


def _check_request(request: Request) -> None:
    if request.method not in ("GET", "POST") or not _PATH_RE.fullmatch(request.target) \
            or not request.target.startswith("/"):
        raise TransportError(TransportError.HEADER)
    for name, value in request.headers:
        if (type(name) is not str or type(value) is not str or not _TOKEN_RE.fullmatch(name)
                or any(not 0x20 <= ord(char) <= 0x7E for char in value)):
            raise TransportError(TransportError.HEADER)


class _PinnedHTTPS(http.client.HTTPSConnection):
    """TLS to an address, checking the certificate against ``server_name``."""

    def __init__(self, address: str, port: int, server_name: str, context: ssl.SSLContext,
                 timeout: float) -> None:
        super().__init__(address, port, timeout=timeout, context=context)
        self._server_name = server_name
        self._ctx = context

    def connect(self) -> None:
        http.client.HTTPConnection.connect(self)
        self.sock = self._ctx.wrap_socket(self.sock, server_hostname=self._server_name)


def tls_context() -> ssl.SSLContext:
    """The one TLS context: the system's trust store, hostname checks, TLS ≥ 1.2."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class HttpResponse:
    """A ``Response`` over ``http.client``."""

    def __init__(self, raw: http.client.HTTPResponse, transport: "HttpTransport",
                 deadline: float) -> None:
        self._raw = raw
        self._transport = transport
        self._deadline = deadline
        self.status = raw.status
        headers: dict[str, str] = {}
        for name, value in raw.getheaders():
            headers.setdefault(name.lower(), value)
        self.headers = headers

    def read(self, limit: int = READ_CHUNK_BYTES) -> bytes:
        transport = self._transport
        if transport.cancelled:
            raise TransportError(TransportError.CANCELLED)
        if transport.clock() >= self._deadline:
            raise TransportError(TransportError.DEADLINE)
        try:
            return self._raw.read1(limit)
        except BaseException as exc:          # noqa: BLE001 (mapped below, never shown)
            raise transport.map_error(exc) from None

    def close(self) -> None:
        try:
            self._raw.close()
        except OSError:
            pass
        self._transport.close()


class HttpTransport:
    """``http.client`` under 04 §7.5's rules. One request at a time; ``cancel`` may come
    from another thread and lasts for the transport's life (one transport per chat request
    or connection test)."""

    def __init__(self, *, resolver: Resolver | None = None,
                 proxies: Callable[[], Mapping[str, str]] = getproxies,
                 bypass: Callable[[str], object] = proxy_bypass,
                 context: ssl.SSLContext | None = None,
                 connect_timeout: float = CONNECT_TIMEOUT_S,
                 idle_timeout: float = IDLE_TIMEOUT_S,
                 deadline: float = STREAM_DEADLINE_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.resolver = resolver if resolver is not None else SystemResolver()
        self._proxies = proxies
        self._bypass = bypass
        self.context = context if context is not None else tls_context()
        self.connect_timeout = connect_timeout
        self.idle_timeout = idle_timeout
        self.deadline = deadline
        self.clock = clock
        self.cancelled = False
        self._lock = threading.Lock()
        self._conn: http.client.HTTPConnection | None = None
        # The connected socket, kept apart from ``_conn.sock``: ``http.client`` drops that
        # reference when the response takes the connection over.
        self._sock: socket.socket | None = None

    # -- errors ------------------------------------------------------------------------------

    def map_error(self, exc: BaseException) -> TransportError:
        """Any failure while connecting or reading, as a ``TransportError``."""
        if isinstance(exc, TransportError):
            return exc
        if self.cancelled:
            return TransportError(TransportError.CANCELLED)
        if isinstance(exc, (ssl.SSLError, ssl.CertificateError)):
            return TransportError(TransportError.TLS)
        if isinstance(exc, (socket.timeout, TimeoutError)):
            return TransportError(TransportError.IDLE)
        if isinstance(exc, (http.client.HTTPException, ValueError, UnicodeError)):
            return TransportError(TransportError.PROTOCOL)
        if isinstance(exc, (OSError, EOFError)):
            return TransportError(TransportError.CONNECT)
        raise exc                                         # KeyboardInterrupt and the like

    # -- connecting --------------------------------------------------------------------------

    def _connection(self, endpoint: Endpoint) -> tuple[http.client.HTTPConnection, bool]:
        """(connection, pinned): pinned connections send ``Host: localhost:<port>``."""
        timeout = self.connect_timeout
        https = endpoint.scheme == "https"
        if endpoint.pinned:
            address = local_addresses(self.resolver, endpoint.port)[0]
            if https:
                return _PinnedHTTPS(address, endpoint.port, LOCALHOST, self.context,
                                    timeout), True
            return http.client.HTTPConnection(address, endpoint.port, timeout=timeout), True
        if endpoint.loopback:
            if https:
                return http.client.HTTPSConnection(endpoint.host, endpoint.port,
                                                   timeout=timeout, context=self.context), False
            return http.client.HTTPConnection(endpoint.host, endpoint.port,
                                              timeout=timeout), False
        if not https:                                     # parse_address refuses this
            raise TransportError(TransportError.CONNECT)
        proxy = proxy_for(endpoint, proxies=self._proxies, bypass=self._bypass)
        if proxy is None:
            return http.client.HTTPSConnection(endpoint.host, endpoint.port, timeout=timeout,
                                               context=self.context), False
        conn = http.client.HTTPSConnection(proxy.host, proxy.port, timeout=timeout,
                                           context=self.context)
        conn.set_tunnel(endpoint.host, endpoint.port,
                        headers={"Proxy-Authorization": proxy.auth} if proxy.auth else None)
        return conn, False

    def open(self, request: Request) -> HttpResponse:
        """Send ``request`` and return its response (any status: 3xx is not followed)."""
        _check_request(request)
        if self.cancelled:
            raise TransportError(TransportError.CANCELLED)
        self.close()
        conn, pinned = self._connection(request.endpoint)
        with self._lock:
            self._conn = conn
        try:
            conn.connect()
        except BaseException as exc:          # noqa: BLE001 (mapped, never shown)
            self.close()
            failed = self.map_error(exc)
            if failed.kind == TransportError.IDLE:          # no answer while connecting
                failed = TransportError(TransportError.CONNECT)
            raise failed from None
        try:
            if self.cancelled:
                raise TransportError(TransportError.CANCELLED)
            assert conn.sock is not None
            with self._lock:
                self._sock = conn.sock
            conn.sock.settimeout(self.idle_timeout)
            conn.putrequest(request.method, request.target, skip_host=pinned,
                            skip_accept_encoding=True)
            if pinned:
                conn.putheader("Host", f"{LOCALHOST}:{request.endpoint.port}")
            for name, value in request.headers:
                conn.putheader(name, value)
            if request.body is not None:
                conn.putheader("Content-Length", str(len(request.body)))
            conn.endheaders(request.body)
            raw = conn.getresponse()
        except BaseException as exc:          # noqa: BLE001 (mapped, never shown)
            self.close()
            raise self.map_error(exc) from None
        return HttpResponse(raw, self, self.clock() + self.deadline)

    def cancel(self) -> None:
        """Stop the request now: set the flag and shut the socket down (never blocks). On
        Windows a shutdown doesn't wake a blocked ``recv``, so the handle is also detached
        from its socket object (which then reads as closed) and closed."""
        self.cancelled = True
        with self._lock:
            sock, self._sock = self._sock, None
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        if sys.platform == "win32":
            try:
                socket.close(sock.detach())
            except (OSError, ValueError):
                pass

    def close(self) -> None:
        with self._lock:
            conn, self._conn, self._sock = self._conn, None, None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass


# --- Fakes for tests --------------------------------------------------------------------------

@dataclass
class FakeReply:
    """One scripted answer: ``status``, ``headers`` and body ``chunks``; ``error`` raised by
    ``open`` instead; ``fail`` raised by ``read`` after the chunks."""

    status: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)
    chunks: Sequence[bytes] = ()
    error: TransportError | None = None
    fail: TransportError | None = None


class FakeResponse:
    def __init__(self, reply: FakeReply, transport: "FakeTransport") -> None:
        self.status = reply.status
        self.headers = {name.lower(): value for name, value in reply.headers.items()}
        self._chunks = list(reply.chunks)
        self._fail = reply.fail
        self._transport = transport
        self.closed = False

    def read(self, limit: int = READ_CHUNK_BYTES) -> bytes:
        if self._transport.cancelled:
            raise TransportError(TransportError.CANCELLED)
        if not self._chunks:
            if self._fail is not None:
                raise self._fail
            return b""
        chunk = self._chunks[0]
        if len(chunk) > limit:
            self._chunks[0] = chunk[limit:]
            chunk = chunk[:limit]
        else:
            self._chunks.pop(0)
        if self._transport.on_read is not None:
            self._transport.on_read(self)
        return chunk

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    """A ``Transport`` answering from ``replies`` in order (or a callable of the request).
    ``requests`` records every request; nothing touches a socket."""

    def __init__(self, *replies: FakeReply | Callable[[Request], FakeReply]) -> None:
        self._replies = list(replies)
        self.requests: list[Request] = []
        self.cancelled = False
        self.on_read: Callable[[FakeResponse], None] | None = None

    def open(self, request: Request) -> FakeResponse:
        _check_request(request)
        if self.cancelled:
            raise TransportError(TransportError.CANCELLED)
        self.requests.append(request)
        if not self._replies:
            raise AssertionError("FakeTransport has no reply for this request")
        reply = self._replies.pop(0)
        if callable(reply):
            reply = reply(request)
        if reply.error is not None:
            raise reply.error
        return FakeResponse(reply, self)

    def cancel(self) -> None:
        self.cancelled = True


__all__ = ["ADDRESS_MAX_CHARS", "CONNECT_TIMEOUT_S", "Endpoint", "FakeReply", "FakeResponse",
           "FakeTransport", "HttpResponse", "HttpTransport", "IDLE_TIMEOUT_S", "LOCALHOST",
           "Proxy", "READ_CHUNK_BYTES", "Request", "Resolver", "Response", "STREAM_DEADLINE_S",
           "StaticResolver", "SystemResolver", "Transport", "local_addresses", "parse_address",
           "proxy_for", "read_body", "tls_context"]

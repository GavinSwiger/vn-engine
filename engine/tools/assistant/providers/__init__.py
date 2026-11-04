"""The assistant's AI providers: the engine's only network code (F48 ``04-technical.md``
§3.1, §7.5, §7.7; ``05-security.md`` SEC-F48-13, -16 to -19; ADR-0008 Amendment 5).

Why this package exists: Studio's Assistant pane sends requests to Anthropic, OpenAI or an
OpenAI-compatible server on the author's own computer, with the author's key. Everything
that touches a socket lives here, behind one strict transport, so the rules that keep the
key with its own server (no redirects, verified TLS, loopback-only plain http, CONNECT-only
proxies) hold in one place.

- ``transport``: ``Endpoint``, ``parse_address``, ``HttpTransport`` (``http.client``) and
  the ``Transport``/``Resolver`` seams, with ``FakeTransport`` for tests.
- ``sse``: the byte-bounded server-sent-events decoder and strict JSON (SEC-F48-19).
- ``errors``: a status, error body or transport failure → 01 §6.6's text.
- ``base``: the chat's provider-neutral messages, ``StreamEvent``, ``Usage``, ``Turn`` and
  the ``Provider`` plumbing (key binding, caps, model lists).
- ``anthropic``, ``openai``: request bodies (01 §7.4), stream events, model lists.
- ``make_provider(provider_id, model=, key=, address=, transport=)`` here builds one.

Only this package imports ``socket``, ``ssl``, ``http`` or ``urllib`` (AC-F48-01), and from
``urllib.request`` only ``getproxies``/``proxy_bypass`` (in ``transport``, with
``getaddrinfo("localhost")``: invariant 9(c)). ``mcp`` never imports this package.

This module holds the names every provider shares; it imports nothing that opens a socket.
"""

from typing import Final, Protocol

ANTHROPIC: Final = "anthropic"
OPENAI: Final = "openai"
COMPATIBLE: Final = "compatible"
PROVIDER_IDS: Final = (ANTHROPIC, OPENAI, COMPATIBLE)

# 01 §6.2's provider field.
PROVIDER_LABELS: Final = {
    ANTHROPIC: "Anthropic (Claude)",
    OPENAI: "OpenAI (ChatGPT)",
    COMPATIBLE: "OpenAI-compatible (Ollama, LM Studio, …)",
}
# The {provider} of 01 §6.6's texts and the consent title. A compatible server is named by
# its host (``Endpoint.display_host``), which the provider object fills in.
PROVIDER_NAMES: Final = {ANTHROPIC: "Anthropic", OPENAI: "OpenAI"}

# The fixed origins keys are bound to (SEC-F48-16; 04 §7.5).
ANTHROPIC_ADDRESS: Final = "https://api.anthropic.com/v1"
OPENAI_ADDRESS: Final = "https://api.openai.com/v1"
ANTHROPIC_ORIGIN: Final = "https://api.anthropic.com:443"
OPENAI_ORIGIN: Final = "https://api.openai.com:443"
COMPATIBLE_DEFAULT_ADDRESS: Final = "http://localhost:11434/v1"

CONNECTED: Final = "Connected."


# The pane's model line, "{name} · {model}" (01 §6.1); a compatible server shows its host.
PANE_NAMES: Final = {ANTHROPIC: "Claude", OPENAI: "ChatGPT"}


class KeyLike(Protocol):
    """What a provider needs of a key: ``keystore.BoundKey`` (S7) has this shape. ``value``
    goes only into the provider's auth header (SEC-F48-13 (b)); ``provider`` and ``origin``
    must equal the endpoint's (SEC-F48-16)."""

    @property
    def value(self) -> str: ...

    @property
    def provider(self) -> str: ...

    @property
    def origin(self) -> str: ...


def make_provider(provider_id: str, *, model: str, key: KeyLike | None = None,
                  address: str | None = None, transport=None):
    """The provider for ``provider_id`` (``base.Provider``). Anthropic and OpenAI use their
    fixed addresses; a compatible server uses ``address`` (``errors.AddressError`` if
    refused). ``transport`` defaults to a new ``HttpTransport`` (one per request run).
    Imported here, so importing this package opens no socket module."""
    from engine.tools.assistant.providers.transport import HttpTransport, parse_address
    transport = transport if transport is not None else HttpTransport()
    if provider_id == ANTHROPIC:
        from engine.tools.assistant.providers.anthropic import AnthropicProvider
        return AnthropicProvider(parse_address(ANTHROPIC_ADDRESS), model, key, transport,
                                 origin=ANTHROPIC_ORIGIN)
    from engine.tools.assistant.providers.openai import OpenAIProvider
    if provider_id == OPENAI:
        return OpenAIProvider(parse_address(OPENAI_ADDRESS), model, key, transport,
                              origin=OPENAI_ORIGIN, provider_id=OPENAI)
    if provider_id == COMPATIBLE:
        return OpenAIProvider(parse_address(address), model, key, transport,
                              provider_id=COMPATIBLE)
    raise ValueError(f"unknown provider {provider_id!r}")


def suggested_models(provider_id: str) -> tuple[str, ...]:
    """§6.2's model choices before Test connection fills the list (compatible: none)."""
    if provider_id == ANTHROPIC:
        from engine.tools.assistant.providers.anthropic import MODELS
        return MODELS
    if provider_id == OPENAI:
        from engine.tools.assistant.providers.openai import MODELS as OPENAI_MODELS
        return OPENAI_MODELS
    return ()


__all__ = ["ANTHROPIC", "ANTHROPIC_ADDRESS", "ANTHROPIC_ORIGIN", "COMPATIBLE",
           "COMPATIBLE_DEFAULT_ADDRESS", "CONNECTED", "KeyLike", "OPENAI", "OPENAI_ADDRESS",
           "OPENAI_ORIGIN", "PANE_NAMES", "PROVIDER_IDS", "PROVIDER_LABELS", "PROVIDER_NAMES",
           "make_provider", "suggested_models"]

"""The assistant's per-user settings and consent (F48 ``04-technical.md`` §7.5, §10;
``05-security.md`` SEC-F48-17's last point, SEC-F48-21; ``01-design.md`` §6.2, §6.4,
PR-F48-17, -19; ADR-0003: ``studio_user_dir()/assistant.json``).

Why this module exists: provider, address and model decide where the author's game text
and key go, so only the author may set them. They live in one per-user file, never in a
game folder (``.studio/`` and ``config.toml`` are someone else's when the game is), and
every value is checked when read and again at use.

- ``Prefs`` (frozen): ``provider``, ``models`` (per provider), ``address`` (the compatible
  server's), ``steps`` (1–50, default 12), ``token_limit`` (10,000–10,000,000, default
  500,000), ``consent`` ((provider, origin) pairs, at most 64, newest last) and ``env``
  (providers whose key comes from the environment variable, PR-F48-33).
- ``load(folder=None)``: ``read_regular`` ≤ 64 KiB, strict UTF-8 JSON with duplicate keys
  refused. A missing, unreadable, oversize, malformed or newer (``v`` ≠ 1) file gives the
  defaults, and is left as it is until a setting changes. Inside a good file, a field of the
  wrong type or out of range takes its default; unknown keys are ignored.
- ``save(prefs, folder=None)``: ``write_atomic`` (mode 0600) into ``studio_user_dir()``;
  ``studio_user_dir`` removes stale temps (ADR-0003 §5). False when no folder can be used.
- Consent (SEC-F48-21): ``prefs.consented(provider, origin)``; ``grant_consent`` records one
  and saves. A new provider or origin asks again.

The address is kept as text here (no URL parsing outside ``providers/``); the transport's
``parse_address`` refuses a bad one at every use (SEC-F48-17).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Final

from engine.core import safefile
from engine.core.paths import is_plain_name, studio_user_dir
from engine.tools.assistant.keystore import ANTHROPIC, OPENAI, origin_ok
from engine.tools.assistant.keystore import PROVIDERS as KEY_PROVIDERS
from engine.tools.assistant.providers import CLAUDE_CODE

PREFS_NAME: Final = "assistant.json"
PREFS_VERSION: Final = 1
PREFS_MAX_BYTES: Final = 64 * 1024
PREFS_MODE: Final = 0o600
CONSENT_MAX: Final = 64

DEFAULT_PROVIDER: Final = ANTHROPIC
DEFAULT_ADDRESS: Final = "http://localhost:11434/v1"
# 01 §6.2 (Anthropic) and §8 D6 (OpenAI: named at build time; the list fills after Test
# connection). A compatible server has no default: its list names one.
# The providers a setting may name: those with keys, and Claude Code (no key).
PROVIDERS: Final = (*KEY_PROVIDERS, CLAUDE_CODE)
DEFAULT_MODELS: Final = MappingProxyType({ANTHROPIC: "claude-sonnet-5-5", OPENAI: "gpt-5",
                                          CLAUDE_CODE: "sonnet"})
ANTHROPIC_MODELS: Final = ("claude-sonnet-5-5", "claude-opus-5-5")
STEPS_DEFAULT: Final = 12
STEPS_MIN: Final = 1
STEPS_MAX: Final = 50
TOKEN_LIMIT_DEFAULT: Final = 500_000
TOKEN_LIMIT_MIN: Final = 10_000
TOKEN_LIMIT_MAX: Final = 10_000_000
ADDRESS_MAX_CHARS: Final = 2048
MODEL_MAX_CHARS: Final = 200


def model_ok(value: object) -> bool:
    """A model id: 1–200 printable ASCII characters, no space, quote or backslash."""
    return (type(value) is str and 0 < len(value) <= MODEL_MAX_CHARS
            and all("\x21" <= c <= "\x7e" and c not in "\"'\\`" for c in value))


def address_ok(value: object) -> bool:
    """Text that may be an address: at most 2,048 characters, no control, format or
    separator character. ``providers.transport.parse_address`` decides at use."""
    return (type(value) is str and 0 < len(value) <= ADDRESS_MAX_CHARS
            and is_plain_name(value) and value.isprintable())


def _int_in(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


@dataclass(frozen=True)
class Prefs:
    """One user's assistant settings. Change with ``replace`` or the ``with_*`` methods."""

    provider: str = DEFAULT_PROVIDER
    models: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    address: str = DEFAULT_ADDRESS
    steps: int = STEPS_DEFAULT
    token_limit: int = TOKEN_LIMIT_DEFAULT
    consent: tuple[tuple[str, str], ...] = ()
    env: frozenset[str] = frozenset()

    def model(self, provider: str | None = None) -> str:
        """The model for ``provider`` (default: the current one); "" when none is set."""
        return self.models.get(provider or self.provider, "")

    def with_model(self, provider: str, model: str) -> "Prefs":
        if provider not in PROVIDERS or not model_ok(model):
            raise ValueError("not a provider and model id")
        return replace(self, models={**self.models, provider: model})

    def consented(self, provider: str, origin: str) -> bool:
        """The author agreed to send to ``provider`` at ``origin`` (§6.4)."""
        return (provider, origin) in self.consent

    def with_consent(self, provider: str, origin: str) -> "Prefs":
        """Record consent for (``provider``, ``origin``), newest last; the oldest pair goes
        past ``CONSENT_MAX``."""
        if provider not in PROVIDERS or not origin_ok(origin):
            raise ValueError("not a provider and origin")
        pairs = [pair for pair in self.consent if pair != (provider, origin)]
        pairs.append((provider, origin))
        return replace(self, consent=tuple(pairs[-CONSENT_MAX:]))

    def with_env(self, provider: str, on: bool) -> "Prefs":
        """Use (or stop using) ``provider``'s key variable (PR-F48-33)."""
        if provider not in (ANTHROPIC, OPENAI):
            raise ValueError("only Anthropic and OpenAI keys come from a variable")
        return replace(self, env=self.env | {provider} if on else self.env - {provider})

    def to_json(self) -> bytes:
        data = {"v": PREFS_VERSION, "provider": self.provider,
                "models": {p: m for p, m in sorted(self.models.items()) if p in PROVIDERS},
                "address": self.address, "steps": self.steps,
                "token_limit": self.token_limit,
                "consent": [list(pair) for pair in self.consent],
                "env": sorted(self.env)}
        return (json.dumps(data, ensure_ascii=True, indent=2) + "\n").encode("ascii")


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _value in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key")
    return dict(pairs)


def parse(data: bytes) -> Prefs:
    """``Prefs`` from a file's bytes (see the module notes); never raises."""
    if len(data) > PREFS_MAX_BYTES:
        return Prefs()
    try:
        raw = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (ValueError, RecursionError):
        return Prefs()
    if not isinstance(raw, dict) or type(raw.get("v")) is not int \
            or raw.get("v") != PREFS_VERSION:
        return Prefs()
    defaults = Prefs()
    provider = raw.get("provider")
    models = dict(DEFAULT_MODELS)
    found = raw.get("models")
    if isinstance(found, dict):
        models.update({p: m for p, m in found.items() if p in PROVIDERS and model_ok(m)})
    consent: list[tuple[str, str]] = []
    pairs = raw.get("consent")
    if isinstance(pairs, list):
        for pair in pairs[-CONSENT_MAX:]:
            if (isinstance(pair, list) and len(pair) == 2 and pair[0] in PROVIDERS
                    and origin_ok(pair[1]) and (pair[0], pair[1]) not in consent):
                consent.append((pair[0], pair[1]))
    env = raw.get("env")
    return Prefs(
        provider=provider if provider in PROVIDERS else defaults.provider,
        models=models,
        address=raw["address"] if address_ok(raw.get("address")) else defaults.address,
        steps=raw["steps"] if _int_in(raw.get("steps"), STEPS_MIN, STEPS_MAX)
        else defaults.steps,
        token_limit=raw["token_limit"] if _int_in(raw.get("token_limit"), TOKEN_LIMIT_MIN,
                                                  TOKEN_LIMIT_MAX) else defaults.token_limit,
        consent=tuple(consent),
        env=frozenset(p for p in env if p in (ANTHROPIC, OPENAI))
        if isinstance(env, list) and all(type(p) is str for p in env) else frozenset())


def _folder(folder: Path | None) -> Path | None:
    return folder if folder is not None else studio_user_dir()


def load(folder: Path | None = None) -> Prefs:
    """The user's settings from ``folder`` (default ``studio_user_dir()``), or the defaults.
    Nothing in a game folder is read."""
    place = _folder(folder)
    if place is None:
        return Prefs()
    result = safefile.read_regular(Path(place) / PREFS_NAME, PREFS_MAX_BYTES)
    if not result.ok or result.data is None:
        return Prefs()
    return parse(result.data)


def save(prefs: Prefs, folder: Path | None = None) -> bool:
    """Write ``prefs`` atomically; False when the folder can't be used or the write fails."""
    place = _folder(folder)
    if place is None:
        return False
    try:
        safefile.write_atomic(Path(place) / PREFS_NAME, [prefs.to_json()], mode=PREFS_MODE)
    except OSError:
        return False
    return True


def grant_consent(provider: str, origin: str, folder: Path | None = None) -> Prefs:
    """§6.4 **Send**: record consent for (``provider``, ``origin``) on the latest settings
    and save them. Returns the new settings (consent holds for this session even when the
    save fails)."""
    prefs = load(folder).with_consent(provider, origin)
    save(prefs, folder)
    return prefs


__all__ = ["ANTHROPIC_MODELS", "CONSENT_MAX", "DEFAULT_ADDRESS", "DEFAULT_MODELS",
           "DEFAULT_PROVIDER", "PREFS_MAX_BYTES", "PREFS_NAME", "PREFS_VERSION", "Prefs",
           "STEPS_DEFAULT", "STEPS_MAX", "STEPS_MIN", "TOKEN_LIMIT_DEFAULT",
           "TOKEN_LIMIT_MAX", "TOKEN_LIMIT_MIN", "address_ok", "grant_consent", "load",
           "model_ok", "parse", "save"]

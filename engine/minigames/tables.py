"""A minigame's own tokens and words: ``[theme.plugin]`` and ``[words.plugin]`` checked
against what each plugin declares (F23 ``04`` §7.9; ``03`` "Theme tokens"; UI-F23-15;
SEC-F23-07).

Why this module exists: ``config.toml`` is read before the plugins load, so ``config.py``
stores these two tables raw (``RawPluginTable``: values as written, with their lines) and
checks only their bounds. Once the registry is known, ``install_minigames`` builds one
``PluginTables``, which checks each registered minigame's table:

- **Tokens.** A declared token ``"<element>.<property>"`` takes the validator its property's
  suffix names (ui-system §3: ``_color``, ``_opacity``, ``_font``, ``_size``, lengths,
  ``_image``, ``_sound``, ``music``, ``_ms``; any other property keeps the type of its
  default). A configured value that passes is used; a bad one keeps the default and logs
  config's invalid-value text (area ``config``). The default itself may be a value or
  another token's name (an engine token such as ``"panel.heading.text_color"``, or
  ``"plugin.<name>.<key>"``), which it then follows. ``mine`` gives the **typed** value
  (``(r, g, b)``, a float, an int, a ref, or None for an empty ref).
- **Words.** ``Text(max_chars=200)``, then SEC-F23-07's clean. ``title`` is always a word:
  ``[words.plugin.<name>] title``, else the declared title, else the name. A blank word
  keeps its default.
- **Unknown** keys and minigame names: config's unknown-key / unknown-section warning with
  did-you-mean (area ``config``, dev runs only).

``engine_token`` is ``ctx.theme.get``'s reader of the engine's own tokens (plain values only).
"""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from engine.core.config import did_you_mean, value_problem_text
from engine.core.config_schema import (
    AudioRef,
    FontRef,
    GuiImageRef,
    HexColor,
    IntRange,
    Opacity,
    RawPluginTable,
    RawValue,
    Text,
    Validator,
    ValueProblem,
)
from engine.core.constants import CONFIG_FILENAME, WORD_MAX_CHARS
from engine.core.errors import ConfigError
from engine.core.logsetup import get_logger
from engine.core.redact import echo
from engine.runtime.minigame import clean_text

_log = get_logger("config")

TITLE_KEY: Final = "title"
TITLE_MAX: Final = 200                     # SEC-F23-07: a title, code points
FONT_SIZE_RANGE: Final = (1, 400)          # as ctx.font's sizes
LENGTH_RANGE: Final = (0, 7680)            # canvas units; plugins clamp to their own ranges
MS_RANGE: Final = (0, 60_000)
_LENGTH_SUFFIXES: Final = ("_width", "_height", "_padding", "_gap", "_radius")
_REF_SUFFIXES: Final = ("_font", "_image", "_sound")
_WORD: Final = Text(max_chars=WORD_MAX_CHARS)
_PLAIN: Final = (str, int, float, bool, type(None))
_FOLLOW_DEPTH: Final = 8                   # a chain of token names, at most


class _SameType(Validator):
    """A token whose suffix names no type keeps the type of its default (a bool stays a
    bool; an int default also takes a whole number only)."""

    _PHRASES = {bool: "true or false", int: "a whole number", float: "a number", str: "text"}

    def __init__(self, kind: type) -> None:
        self.kind = kind
        self.expected = self._PHRASES.get(kind, "text")

    def check(self, value: object) -> object:
        if type(value) is self.kind:
            return value
        if self.kind is float and type(value) is int:
            return float(value)
        raise ValueProblem


def token_validator(key: str, default: object) -> Validator:
    """The validator of a declared token by its property's suffix (ui-system §3)."""
    prop = key.rsplit(".", 1)[-1]
    if prop.endswith("_color"):
        return HexColor('a color like "#RRGGBB"')
    if prop.endswith("_opacity"):
        return Opacity()
    if prop.endswith("_font"):
        return FontRef()
    if prop.endswith("_size"):
        return IntRange(*FONT_SIZE_RANGE)
    if prop.endswith(_LENGTH_SUFFIXES):
        return IntRange(*LENGTH_RANGE)
    if prop.endswith("_image"):
        return GuiImageRef()
    if prop.endswith("_sound") or prop == "music":
        return AudioRef()
    if prop.endswith("_ms"):
        return IntRange(*MS_RANGE)
    return _SameType(type(default))


def _is_ref(key: str) -> bool:
    prop = key.rsplit(".", 1)[-1]
    return prop.endswith(_REF_SUFFIXES) or prop == "music"


def engine_token(cfg: Any, key: object) -> object:
    """The engine token ``key`` (``"panel.text_color"``) of the theme ``cfg``: plain values
    and int tuples only. KeyError for anything else."""
    if type(key) is not str or not key:
        raise KeyError("a theme token is text such as \"panel.text_color\"")
    node: object = cfg
    for part in key.split("."):
        fields = getattr(node, "__dataclass_fields__", None)
        if not part.isidentifier() or part.startswith("_") or fields is None \
                or part not in fields:
            raise KeyError(f"there is no theme token {clean_text(key, 80)!r}")
        node = getattr(node, part)
    if type(node) in _PLAIN:
        return node
    if type(node) is tuple and all(type(v) is int for v in node):
        return node
    raise KeyError(f"{clean_text(key, 80)!r} is a table, not a token")


@dataclass(frozen=True)
class PluginLook:
    """One minigame's checked tokens (typed) and words (cleaned), and its display title."""
    tokens: Mapping[str, object]
    words: Mapping[str, str]
    title: str


class PluginTables:
    """``[theme.plugin]`` and ``[words.plugin]`` for one launch (module docstring).
    ``look(entry)`` is worked out once per registered entry; ``check(entries)`` does every
    entry at install, so the warnings come then."""

    def __init__(self, theme: Mapping[str, RawPluginTable], words: Mapping[str, RawPluginTable],
                 cfg: Any, *, dev: bool, log: logging.Logger = _log) -> None:
        self._theme = theme
        self._words = words
        self._cfg = cfg
        self._dev = dev
        self._log = log
        self._looks: dict[str, tuple[object, PluginLook]] = {}

    def check(self, entries: Iterable[Any]) -> None:
        """Every registered entry's tables; then the minigame names no entry has (dev)."""
        entries = list(entries)
        for entry in entries:
            self.look(entry)
        if not self._dev:
            return
        names = [entry.name for entry in entries]
        for area, tables in (("theme", self._theme), ("words", self._words)):
            for name, table in tables.items():
                if name not in names:
                    message = (f"{_where(table.line)}: unknown section "
                               f"[{area}.plugin.{echo(name)}]")
                    close = did_you_mean(name, names)
                    if close is not None:
                        message += f" — did you mean [{area}.plugin.{close}]?"
                    self._log.warning("%s", message)

    def look(self, entry: Any) -> PluginLook:
        found = self._looks.get(entry.name)
        if found is not None and found[0] is entry:
            return found[1]
        tokens = self._tokens(entry)
        words = self._plugin_words(entry)
        title = words.get(TITLE_KEY) or clean_text(entry.sig.title, TITLE_MAX) or entry.name
        look = PluginLook(tokens, words, title)
        self._looks[entry.name] = (entry, look)
        return look

    # -- tokens --

    def _tokens(self, entry: Any) -> Mapping[str, object]:
        name = entry.name
        declared: Mapping[str, object] = entry.tokens
        table = self._theme.get(name)
        configured: dict[str, object] = {}
        if table is not None:
            for key, raw in table.values.items():
                default = declared.get(key, _MISSING)
                if default is _MISSING:
                    self._unknown(f"theme.plugin.{name}", key, declared, raw)
                    continue
                validator = token_validator(key, default)
                try:
                    validator.check(raw.value)
                except ValueProblem:
                    self._bad(f"theme.plugin.{name}", key, validator, raw)
                    continue
                configured[key] = raw.value
        resolved: dict[str, object] = {}
        for key in declared:
            resolved[key] = self._token(name, key, declared, configured, 0)
        return MappingProxyType(resolved)

    def _token(self, name: str, key: str, declared: Mapping[str, object],
               configured: Mapping[str, object], depth: int) -> object:
        default = declared[key]
        validator = token_validator(key, default)
        if key in configured:
            return validator.check(configured[key])
        if default == "" and _is_ref(key):
            return None
        try:
            return validator.check(default)
        except ValueProblem:
            pass
        if type(default) is str and depth < _FOLLOW_DEPTH:      # another token's name
            own = f"plugin.{name}."
            if default.startswith(own) and default[len(own):] in declared:
                return self._token(name, default[len(own):], declared, configured, depth + 1)
            try:
                return engine_token(self._cfg, default)
            except KeyError:
                pass
        self._log.debug("minigame %s: token %s keeps its declared default %r", name, key,
                        default)
        return default

    # -- words --

    def _plugin_words(self, entry: Any) -> Mapping[str, str]:
        name = entry.name
        declared: Mapping[str, str] = entry.words
        words = {key: clean_text(value, WORD_MAX_CHARS) for key, value in declared.items()}
        table = self._words.get(name)
        if table is not None:
            known = list(declared) + ([TITLE_KEY] if TITLE_KEY not in declared else [])
            for key, raw in table.values.items():
                if key not in known:
                    self._unknown(f"words.plugin.{name}", key, known, raw)
                    continue
                try:
                    _WORD.check(raw.value)
                except ValueProblem:
                    self._bad(f"words.plugin.{name}", key, _WORD, raw)
                    continue
                text = clean_text(raw.value, WORD_MAX_CHARS)       # type: ignore[arg-type]
                if text.strip():
                    words[key] = text
        title = words.get(TITLE_KEY)
        if title is not None and not title.strip():
            del words[TITLE_KEY]
        return MappingProxyType(words)

    # -- warnings --

    def _bad(self, label: str, key: str, validator: Validator, raw: RawValue) -> None:
        """Config's invalid-value text; the default is kept (always logged)."""
        section, prop = _split(label, key)
        error = ConfigError(value_problem_text(f"[{section}] {prop}", validator, raw.value)
                            + ", so the default is used", file=CONFIG_FILENAME, line=raw.line)
        self._log.warning("%s", error.format())

    def _unknown(self, label: str, key: str, known: Iterable[str], raw: RawValue) -> None:
        """Config's unknown-key text with did-you-mean (dev runs only)."""
        if not self._dev:
            return
        section, prop = _split(label, key)
        message = f"{_where(raw.line)}: unknown key [{section}] {echo(prop)}"
        known = list(known)
        element = key.rpartition(".")[0]
        same = [k.rpartition(".")[2] for k in known if k.rpartition(".")[0] == element]
        close = did_you_mean(prop, same) if same else did_you_mean(key, known)
        if close is not None:
            message += f' — did you mean "{close}"?'
        self._log.warning("%s", message)


_MISSING: Final = object()


def _split(label: str, key: str) -> tuple[str, str]:
    """``("theme.plugin.probe", "card.back_color")`` → ``("theme.plugin.probe.card",
    "back_color")``, as config.toml writes it."""
    element, _, prop = key.rpartition(".")
    return (f"{label}.{element}" if element else label), prop


def _where(line: int | None) -> str:
    return f"{CONFIG_FILENAME}, line {line}" if line is not None else CONFIG_FILENAME


__all__ = ["PluginLook", "PluginTables", "engine_token", "token_validator"]

"""The current look: ``[theme]``/``[words]`` with at most two sparse layers (F32 ``04`` §4.1).

Why this module exists: F32 lets the look change while the game runs. A ``[playthrough.N]``
table restyles the title for players past playthrough N, and a ``[style.<name>]`` table
restyles the in-game areas while ``ui style <name>`` is on. Screens keep references to their
theme, so a look is never changed in place. Each combination ``(playthrough N, style)`` is
its own ``Look``, built the first time it becomes current and then cached for the session.
``Looks.revision`` goes up whenever the key changes, and a screen compares that one integer
per frame.

- ``apply_tokens`` lays a table's dotted tokens over a ``ThemeConfig`` and rebuilds only the
  tables they name (``dataclasses.replace``). Every other table stays the same object.
- A ``Look`` holds the full ``ThemeConfig`` (in a ``UiTheme`` with the base faces, the base
  frames updated by the frame tokens the layers set, and the base title pictures), the merged
  words (playthrough, then style over them), the playthrough's ``title_entries``, and the
  screen parts built from it on first use (``add_part``/``part``).
- A look whose layers set no token reuses the base ``UiTheme`` object (07 I-2).

Building reads no file. Every look ref was checked at launch, and the ``image`` callable
given by the app returns held images (04 §6.2). Pure Python, with no display needed: this
module imports no pygame itself (07 I-6) and nothing from ``engine.app``.
"""

import dataclasses
from bisect import bisect_right
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from engine.core.config_schema import LookTable, ThemeConfig, config_fields
from engine.core.logsetup import get_logger
from engine.core.redact import echo
from engine.ui.theme import FRAME_TOKENS, UiTheme

if TYPE_CHECKING:
    from engine.render.assets import ImageRef
    from engine.ui.menus import UiOverrides

_log = get_logger("ui")

LookKey = tuple[int | None, str | None]          # (playthrough table N, style name)


def apply_tokens(base: ThemeConfig, tokens: Mapping[str, object]) -> ThemeConfig:
    """``base`` with each dotted token path (``"textbox.name_tab.text_size"``) set. Only the
    tables on those paths are rebuilt; with no tokens, ``base`` itself. A path the schema
    doesn't have is a programming error (config validation never makes one)."""
    if not tokens:
        return base
    return _replace(base, [(path.split("."), value) for path, value in tokens.items()])


def _replace(node: object, items: list[tuple[list[str], object]]) -> object:
    fields = config_fields(type(node))
    changes: dict[str, object] = {}
    nested: dict[str, list[tuple[list[str], object]]] = {}
    for parts, value in items:
        head = parts[0]
        assert head in fields, f"no theme token {head!r} in {type(node).__name__}"
        if len(parts) == 1:
            changes[fields[head].name] = value
        else:
            nested.setdefault(head, []).append((parts[1:], value))
    for head, inner in nested.items():
        name = fields[head].name
        child = getattr(node, name)
        assert dataclasses.is_dataclass(child), f"{head!r} is not a table"
        changes[name] = _replace(child, inner)
    return dataclasses.replace(node, **changes)


@dataclass(frozen=True)
class Look:
    """One combination of layers, built once per key (04 §3)."""
    key: LookKey
    theme: UiTheme                         # full ThemeConfig with both layers
    words: Mapping[str, str]               # playthrough words, then style words over them
    title_entries: tuple[str, ...] | None
    parts: dict[str, object] = field(default_factory=dict, compare=False, repr=False)


class LookSource(Protocol):
    """What a screen needs from ``Looks``: the revision to compare and its built part."""
    revision: int

    def part(self, name: str) -> object: ...


class Looks:
    """The current look of one session: key ``(playthrough N, style)``, a cache of built
    ``Look``s, and ``revision`` (+1 on every key change)."""

    def __init__(self, base: UiTheme, *, styles: Mapping[str, LookTable],
                 playthroughs: Mapping[int, LookTable], overrides: "UiOverrides",
                 image: Callable[[str], "ImageRef | None"]) -> None:
        self.base = base
        self.styles = styles
        self.playthroughs = playthroughs
        self.overrides = overrides
        self.image = image
        self.revision = 0
        self._tables = sorted(playthroughs)
        self._cache: dict[LookKey, Look] = {}
        self._builders: dict[str, Callable[[ThemeConfig], object]] = {}
        self._current = self._look((None, None))

    @property
    def key(self) -> LookKey:
        return self._current.key

    def current(self) -> Look:
        return self._current

    def choose(self, playthrough: int) -> None:
        """The playthrough look for ``playthrough``: the table with the largest N ≤ it, or
        none (also for a negative number). The style is kept."""
        at = bisect_right(self._tables, playthrough) if playthrough >= 0 else 0
        self._set((self._tables[at - 1] if at else None, self.key[1]))

    def set_style(self, name: str | None) -> None:
        """Make the style ``name`` current (None: off). A name the config doesn't have is
        off, with one DEBUG line (a restore already warned with W205)."""
        if name is not None and name not in self.styles:
            _log.debug("ui style: there is no style %s, so the normal look is used",
                       echo(name))
            name = None
        self._set((self.key[0], name))

    def word(self, key: str) -> str | None:
        """``Words``' override hook: F10's ``UiOverrides`` first, then the current look's
        words (style over playthrough); None gives ``[words]``."""
        found = self.overrides.word(key)
        return found if found is not None else self._current.words.get(key)

    def title_entries(self) -> tuple[str, ...] | None:
        return self._current.title_entries

    def add_part(self, name: str, build: Callable[[ThemeConfig], object]) -> None:
        """Register how a screen part (``"textbox"``, ``"choice"``) is built from a look's
        ``ThemeConfig``; it must be pure (no file reads)."""
        self._builders[name] = build

    def part(self, name: str) -> object:
        """The current look's part ``name``, built once per ``Look``."""
        assert name in self._builders, f"no look part {name!r} was added"
        parts = self._current.parts
        if name not in parts:
            parts[name] = self._builders[name](self._current.theme.cfg)
        return parts[name]

    def look(self, key: LookKey) -> Look:
        """The ``Look`` of ``key``, built or cached, without making it current (F32 s4: the
        launch's W67 rows check one look per table)."""
        return self._look(key)

    # -- building --

    def _set(self, key: LookKey) -> None:
        if key != self._current.key:
            self._current = self._look(key)
            self.revision += 1

    def _look(self, key: LookKey) -> Look:
        found = self._cache.get(key)
        if found is None:
            found = self._cache[key] = self._build(key)
        return found

    def _build(self, key: LookKey) -> Look:
        play = self.playthroughs.get(key[0]) if key[0] is not None else None
        style = self.styles.get(key[1]) if key[1] is not None else None
        tokens: dict[str, object] = {}
        words: dict[str, str] = {}
        for table in (play, style):                # playthrough first, the style over it
            if table is not None:
                tokens.update(table.tokens)
                words.update((k, v) for k, v in table.words.items() if v.strip())
        entries = play.title_entries if play is not None else None
        return Look(key, self._theme(tokens), MappingProxyType(words), entries)

    def _theme(self, tokens: Mapping[str, object]) -> UiTheme:
        base = self.base
        if not tokens:
            return base                            # 07 I-2: the base object itself
        frames = dict(base.frames)
        for name, (table, key) in FRAME_TOKENS.items():
            ref = tokens.get(f"{table}.{key}")
            if ref is not None:
                frames[name] = self.image(ref)
        # A new UiTheme, never ``replace``: its style cache must not be shared.
        return UiTheme(apply_tokens(base.cfg, tokens), base.faces, frames, base.logo,
                       base.background)


__all__ = ["Look", "LookKey", "LookSource", "Looks", "apply_tokens"]

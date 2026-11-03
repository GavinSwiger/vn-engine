"""``ScenesPage``: the Extras screen's Scenes page (F36 ``01-design.md`` §6.2, PR-F36-06 and
07; ``04-technical.md`` §3, §7.5).

Why this module exists: the player watches a scene the author marked for replay again. The
page turns the declared replays into F34's ``TileGrid`` tiles and starts a replay when one
is activated. It reads the story only through a ``ScenesPort`` (``app/replays.py``'s,
F36-W3), so ``ui`` never imports ``script``, ``runtime`` or ``persist``.

- **Tiles**: one per declared replay in script order, keyed by its label. An unlocked
  replay shows its picture captioned with its title; a locked one is a ``???`` tile
  (``ending_locked``, the design's one locked word, shared with the Endings page), always
  shown (no viewer, no count badge). The picture
  (PR-F36-07): the replay's ``image``, else its ``tile_picture`` (the first ``scene``
  picture in the label's own lines, found by W1's ``build_replays``), each through
  ``port.picture(name)``; else None, F34's empty tile look. A change of the replays or the
  unlocked labels (``update``) makes the tiles again; the focused tile stays (by key).
- **Activate** (a click, Enter, gamepad A) on an unlocked tile: ``port.start(label, by)``,
  ``by`` the input that picked it (W3 starts the replay and later comes back focused on it).
- ``nav_extras`` ``shoulders``: the bumpers turn pages. ``widget_for(label)``: the tile of
  replay ``label`` (W3's ``open_extras(focus=)``).

Words: ``replays`` (the heading), ``ending_locked`` (``WORD_DEFAULTS`` until F36-W3 adds
them to ``[words]``).
"""

from collections.abc import Collection, Hashable, Sequence
from typing import TYPE_CHECKING, Final, Protocol

from engine.ui.builtin.tile_grid import Picture, Tile, TileGrid, word_or
from engine.ui.focus import Box, FocusGroup
from engine.ui.menus import MenuPageBase
from engine.ui.nav import InputKind

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.ui.menus import PageHost
    from engine.ui.nav import Nav
    from engine.ui.paint import Painter
    from engine.ui.thumbs import ThumbCache
    from engine.ui.widgets import Widget

HEADING: Final = "replays"
LOCKED_WORD: Final = "ending_locked"
WORD_DEFAULTS: Final[dict[str, str]] = {"replays": "Scenes", "ending_locked": "???"}


class ReplayLike(Protocol):
    """A replay as the port gives it (W1's ``script/replay.py`` ``ReplayEntry`` fits):
    ``image`` and ``tile_picture`` are picture names (e.g. "cg river"), or None."""

    @property
    def label(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def image(self) -> str | None: ...

    @property
    def tile_picture(self) -> str | None: ...


class ScenesPort(Protocol):
    """What the page reads (04 §3, §7.5): every declared replay in script order, the
    unlocked labels (F12 kind ``"replay"``), a picture's source (a file ref, a solid colour,
    or None), the launch's ``ThumbCache``, and ``start``, which starts the replay of
    ``label``, ``by`` the input that picked it."""

    thumbs: "ThumbCache"

    def replays(self) -> Sequence[ReplayLike]: ...

    def unlocked(self) -> Collection[str]: ...

    def picture(self, name: str) -> Picture: ...

    def start(self, label: str, by: InputKind) -> None: ...


def replay_picture(port: ScenesPort, replay: ReplayLike) -> Picture:
    """PR-F36-07: ``image``, else ``tile_picture``, else None (the empty look)."""
    name = replay.image or replay.tile_picture
    return port.picture(name) if name else None


def scene_tiles(port: ScenesPort) -> tuple[Tile, ...]:
    """One tile per replay in the port's order (module docstring)."""
    unlocked = set(port.unlocked())
    return tuple(Tile(r.label, replay_picture(port, r), r.title) if r.label in unlocked
                 else Tile(r.label, locked=True) for r in port.replays())


class ScenesPage(MenuPageBase):
    """The ``replays`` page of the Extras screen (module docstring)."""

    heading = HEADING
    nav_extras = frozenset({"shoulders"})

    def __init__(self, port: ScenesPort) -> None:
        self.port = port
        self.host: "PageHost | None" = None
        self.grid: TileGrid | None = None
        self._signature: tuple | None = None

    # -- MenuPage --

    def build(self, host: "PageHost", body: Box) -> list[FocusGroup]:
        self.host = host
        grid = self.grid
        if grid is None:
            shell = host.shell
            grid = self.grid = TileGrid(
                ui=shell, thumbs=self.port.thumbs, on_activate=self._start,
                scope=lambda: host.scope,
                locked_word=lambda: word_or(shell.words, LOCKED_WORD,
                                            WORD_DEFAULTS[LOCKED_WORD]),
                changed=self._changed)
            self._refresh()
        return grid.build(body, host.painter.text_scale())

    def update(self, dt: float) -> None:
        grid = self.grid
        if grid is None:
            return
        if self._now() != self._signature:
            self._refresh()
        grid.update(dt)
        if grid.groups_changed and self.host is not None:
            self.host.rebuild()

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        if self.grid is not None:
            self.grid.draw(canvas, p)

    def on_nav(self, d: "Nav") -> bool:
        return self.grid.on_nav(d) if self.grid is not None else False

    def on_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        return self.grid.on_mouse(kind, pos, notches=notches) if self.grid is not None \
            else False

    def default_widget(self) -> "Widget | None":
        return self.grid.default_widget() if self.grid is not None else None

    def widget_for(self, key: Hashable) -> "Widget | None":
        """The tile of replay ``key`` (its page shown), or None when it is locked or gone."""
        return self.grid.widget_for(key) if self.grid is not None else None

    # -- internals --

    def _now(self) -> tuple:
        return tuple(self.port.replays()), frozenset(self.port.unlocked())

    def _refresh(self) -> None:
        self._signature = self._now()
        if self.grid is not None:
            self.grid.set_tiles(scene_tiles(self.port))

    def _changed(self) -> None:
        host = self.host
        if host is not None and hasattr(host, "revision"):
            host.revision += 1                                 # re-compose a fade layer

    def _start(self, tile: Tile) -> None:
        if tile.locked:
            return
        scope = self.host.scope if self.host is not None else None
        by = scope.source if scope is not None and scope.source is not None else InputKind.KEYS
        self.port.start(str(tile.key), by)


__all__ = ["HEADING", "ReplayLike", "ScenesPage", "ScenesPort", "WORD_DEFAULTS",
           "replay_picture", "scene_tiles"]

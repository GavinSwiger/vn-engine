"""``GalleryPage``: the Extras screen's Gallery page (F34 ``01-design.md`` §6.2, PR-F34-12 to
15; ``04-technical.md`` §3, §7.2, §7.5).

Why this module exists: the player looks again at the special pictures (CGs) seen so far.
The page turns the gallery's entries into F34's ``TileGrid`` tiles and opens the full-screen
``GalleryViewer`` on one. It reads the story only through a ``GalleryPort``
(``app/gallery.py``'s ``AppGalleryPort``, F34-W3), so ``ui`` never imports ``script`` or
``persist``.

- **Tiles** (§7.2): one per entry in gallery order. An entry is unlocked when any of its
  pictures is (the entry picture, then its versions, in declaration order); its tile shows
  the first unlocked picture, captioned with the entry's title, with the count badge for 2+
  unlocked pictures. A locked entry is a ``???`` tile (``gallery_locked``), or left out when
  ``show_locked`` is False, the order kept. A change of the unlocked names (``update``)
  makes the tiles again.
- **Viewer** (§7.5): activating a tile opens the viewer on every unlocked picture in
  gallery order (entries in order, each entry's unlocked pictures in order), at the tile's
  first one. On close, the page turns to the tile of the last picture shown and focuses it.
- ``nav_extras`` ``shoulders``: the bumpers turn pages. ``widget_for(key)``: the tile of
  entry ``key`` (W3's ``open_extras(focus=)``).

Words: ``gallery`` (the heading), ``gallery_locked`` ("???" until the config has it).
"""

from collections.abc import Collection, Hashable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from engine.ui.builtin.gallery_viewer import GalleryViewer, ViewerPicture
from engine.ui.builtin.tile_grid import Picture, Tile, TileGrid, word_or
from engine.ui.focus import Box, FocusGroup
from engine.ui.menus import MenuPageBase
from engine.ui.nav import InputKind, Nav

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.ui.menus import PageHost
    from engine.ui.paint import Painter
    from engine.ui.thumbs import ThumbCache
    from engine.ui.widgets import Widget

HEADING: Final = "gallery"
LOCKED_WORD: Final = "gallery_locked"
LOCKED_DEFAULT: Final = "???"


class GalleryEntryLike(Protocol):
    """An entry as the port gives it (``script/gallery.py``'s ``GalleryEntry`` fits)."""

    picture: str                       # the entry picture's name, e.g. "cg river"
    title: str
    versions: tuple[str, ...]


class GalleryPort(Protocol):
    """What the page reads (04 §3): every entry in gallery order, the unlocked gallery
    names, a picture's source (a file ref, a solid colour, or None), ``show_locked``, and the
    launch's ``ThumbCache``."""

    show_locked: bool
    thumbs: "ThumbCache"

    def entries(self) -> Sequence[GalleryEntryLike]: ...

    def unlocked(self) -> Collection[str]: ...

    def picture(self, name: str) -> Picture: ...


@dataclass(frozen=True)
class GalleryModel:
    """The page's tiles and the viewer's picture list, made from the port."""

    tiles: tuple[Tile, ...]
    pictures: tuple[tuple[str, str], ...]          # (entry picture, picture name), in order


def entry_pictures(entry: GalleryEntryLike, unlocked: Collection[str]) -> list[str]:
    """``entry``'s unlocked pictures: the entry picture, then its versions, in order."""
    return [name for name in (entry.picture, *entry.versions) if name in unlocked]


def gallery_model(port: GalleryPort) -> GalleryModel:
    """04 §7.2 (module docstring)."""
    unlocked = set(port.unlocked())
    show_locked = bool(port.show_locked)
    tiles: list[Tile] = []
    pictures: list[tuple[str, str]] = []
    for entry in port.entries():
        names = entry_pictures(entry, unlocked)
        if names:
            tiles.append(Tile(entry.picture, port.picture(names[0]), entry.title,
                              count=len(names)))
            pictures.extend((entry.picture, name) for name in names)
        elif show_locked:
            tiles.append(Tile(entry.picture, locked=True))
    return GalleryModel(tuple(tiles), tuple(pictures))


class GalleryPage(MenuPageBase):
    """The ``gallery`` page of the Extras screen (module docstring)."""

    heading = HEADING
    nav_extras = frozenset({"shoulders"})

    def __init__(self, port: GalleryPort) -> None:
        self.port = port
        self.host: "PageHost | None" = None
        self.grid: TileGrid | None = None
        self.model = GalleryModel((), ())
        self.viewer: GalleryViewer | None = None
        self._signature: frozenset[str] | None = None

    # -- MenuPage --

    def build(self, host: "PageHost", body: Box) -> list[FocusGroup]:
        self.host = host
        grid = self.grid
        if grid is None:
            shell = host.shell
            grid = self.grid = TileGrid(
                ui=shell, thumbs=self.port.thumbs, on_activate=self._open,
                scope=lambda: host.scope,
                locked_word=lambda: word_or(shell.words, LOCKED_WORD, LOCKED_DEFAULT),
                changed=self._changed)
            self._refresh()
        return grid.build(body, host.painter.text_scale())

    def update(self, dt: float) -> None:
        grid = self.grid
        if grid is None:
            return
        if frozenset(self.port.unlocked()) != self._signature:
            self._refresh()
        grid.update(dt)
        if grid.groups_changed and self.host is not None:
            self.host.rebuild()

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        if self.grid is not None:
            self.grid.draw(canvas, p)

    def on_nav(self, d: Nav) -> bool:
        return self.grid.on_nav(d) if self.grid is not None else False

    def on_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        return self.grid.on_mouse(kind, pos, notches=notches) if self.grid is not None \
            else False

    def default_widget(self) -> "Widget | None":
        return self.grid.default_widget() if self.grid is not None else None

    def widget_for(self, key: Hashable) -> "Widget | None":
        """The tile of entry ``key`` (its page shown), or None when it is locked or gone."""
        return self.grid.widget_for(key) if self.grid is not None else None

    # -- internals --

    def _refresh(self) -> None:
        self._signature = frozenset(self.port.unlocked())
        self.model = gallery_model(self.port)
        if self.grid is not None:
            self.grid.set_tiles(self.model.tiles)

    def _changed(self) -> None:
        host = self.host
        if host is not None and hasattr(host, "revision"):
            host.revision += 1                                 # re-compose a fade layer

    def viewer_pictures(self, key: Hashable) -> tuple[list[ViewerPicture], int]:
        """Every unlocked picture in gallery order, and the index of ``key``'s first."""
        port = self.port
        found = [ViewerPicture(entry, port.picture(name)) for entry, name in self.model.pictures]
        start = next((i for i, (entry, _name) in enumerate(self.model.pictures) if entry == key),
                     0)
        return found, start

    def _open(self, tile: Tile) -> None:
        host = self.host
        if host is None:
            return
        pictures, start = self.viewer_pictures(tile.key)
        if not pictures:
            return
        by = getattr(host, "input_kind", InputKind.KEYS)
        viewer = GalleryViewer(host.shell, by=by if isinstance(by, InputKind) else InputKind.KEYS,
                               pictures=pictures, start=start, on_close=self._viewer_closed,
                               thumbs=self.port.thumbs)
        self.viewer = viewer
        push = getattr(host, "push_child", None)
        if push is not None:
            push(viewer)
        else:
            host.shell.stack.push(viewer)

    def _viewer_closed(self, key: Hashable, by: InputKind) -> None:
        self.viewer = None
        if self.grid is not None and not self.grid.focus_key(key, by):
            self.grid.widget_for(key)          # at least show its page


__all__ = ["GalleryEntryLike", "GalleryModel", "GalleryPage", "GalleryPort", "entry_pictures",
           "gallery_model"]

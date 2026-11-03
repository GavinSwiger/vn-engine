"""``install_gallery``: F34's Gallery page wired into one launch (F34 ``04-technical.md``
§3, §7.2, §7.3, §7.6).

Why this module exists: the Gallery page (``ui/builtin/gallery_page.py``) reads the story
only through a ``GalleryPort``, because ``ui`` never imports ``script`` or ``persist``.
``AppGalleryPort`` is that port over the running story:

- ``entries()``: ``Program.gallery`` (``script/gallery.py``'s ``GalleryEntry``: picture,
  title, versions), read from the live interpreter through ``app.story`` on every call, so
  F39's reload is followed (§7.6).
- ``unlocked()``: ``runtime/gallery.unlocked(program, store)``, the declared pictures the
  F12 store holds (names the script no longer declares stay hidden). Kept until the store's
  unlocks or the program change, since the page asks every frame.
- ``picture(name)``: an ``ImageFile``'s ref or a ``SolidColor``'s RGB from the launch's
  ``ImageIndex``. A name with no picture (F04's W12 at launch) gives the file ref it would
  have (``images/cg/storm.png`` for ``cg storm``), which F04 draws as its placeholder in the
  tile and the viewer.
- ``show_locked`` is ``[gallery] show_locked``; ``thumbs`` the launch's one ``ThumbCache``
  (``app/extras.py``).

One ``add_extras_page`` row: id ``gallery``, shown once any gallery picture is unlocked,
kind ``"gallery"``, names ``preview_names(program)`` (dev ``run --extras``).

This module imports ``engine.script`` only for type checking.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from engine.app.extras import add_extras_page
from engine.runtime.gallery import GALLERY_KIND, preview_names, unlocked
from engine.runtime.images import IMAGES_DIR, ImageFile, SolidColor
from engine.ui.builtin.gallery_page import HEADING, GalleryPage
from engine.ui.menus import MenuEntry

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.images import ImageIndex
    from engine.runtime.interpreter import Interpreter
    from engine.script.gallery import GalleryEntry
    from engine.ui.thumbs import ThumbCache

MISSING_SUFFIX = ".png"


def missing_ref(name: str) -> str:
    """The file a picture name with no picture would come from (``cg storm`` →
    ``images/cg/storm.png``): F04 draws its placeholder for it."""
    return f"{IMAGES_DIR}/{'/'.join(name.split())}{MISSING_SUFFIX}"


class AppGalleryPort:
    """The page's ``GalleryPort`` (module docstring)."""

    def __init__(self, interp: "Callable[[], Interpreter]", images: "ImageIndex | None", *,
                 show_locked: bool, thumbs: "ThumbCache") -> None:
        self._interp = interp
        self.images = images
        self.show_locked = show_locked
        self.thumbs = thumbs
        self._kept: tuple[object, int, tuple[str, ...]] | None = None

    def entries(self) -> "tuple[GalleryEntry, ...]":
        return self._interp().program.gallery

    def unlocked(self) -> tuple[str, ...]:
        interp = self._interp()
        program, store = interp.program, interp.persistent
        kept = self._kept
        if kept is not None and kept[0] is program and kept[1] == store.unlocks_gen:
            return kept[2]
        names = unlocked(program, store)
        self._kept = (program, store.unlocks_gen, names)
        return names

    def picture(self, name: str) -> "str | tuple[int, int, int]":
        found = self.images.get(name) if self.images is not None else None
        if isinstance(found, ImageFile):
            return found.ref
        if isinstance(found, SolidColor):
            return found.rgb
        return missing_ref(name)


def install_gallery(app: "App", interp: "Interpreter",
                    images: "ImageIndex | None" = None) -> AppGalleryPort:
    """The Gallery page's port and its one Extras row (module docstring). After
    ``install_extras``."""

    def live() -> "Interpreter":
        story = getattr(app, "story", None)
        found = getattr(story, "interp", None)
        return found if found is not None else interp

    port = AppGalleryPort(live, images, show_locked=app.config.gallery.show_locked,
                          thumbs=app.extras.thumbs)                 # type: ignore[attr-defined]
    add_extras_page(app, MenuEntry(HEADING, page=lambda host: GalleryPage(port),
                                   visible=lambda: bool(port.unlocked())),
                    kind=GALLERY_KIND, names=lambda: preview_names(live().program))
    return port


__all__ = ["AppGalleryPort", "install_gallery", "missing_ref"]

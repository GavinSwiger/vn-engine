"""The Extras host: the title's one **Extras** button and the pages that join it (F34
``04-technical.md`` §3, §7.3, §7.4; F34–F37 ``07-architecture-review.md`` I-3, I-4).

Why this module exists: the gallery (F34), the endings list and scene replay (F36), the
music room (F35), and achievements (F37) are all things a player looks at again from the
title. Each would otherwise need its own title button and its own screen; instead they are
pages of one **Extras** screen (``GameMenuScreen`` filled from the ``extras`` menu,
``GameShell.open_extras``), and each feature joins it with one call:

    add_extras_page(app, MenuEntry("gallery", page=..., visible=...),
                    kind="gallery", names=lambda: every_gallery_name)

- ``entry``: a ``MenuEntry`` of the ``extras`` menu with ``page=`` (the page) and
  ``visible=`` (True once something on that page is unlocked; D6: no empty pages). Its id is
  one of ``DEFAULT_ORDER["extras"]``, which also fixes the page order: Gallery, Endings,
  Scenes, Music room, Achievements (07 I-4: no config key).
- ``kind`` and ``names()``: the page's F12 unlock kind and every name the story declares
  for it. They serve only the dev preview (``preview_all``).

``install_extras(app)`` (once per windowed launch, ``install_story``, before the pages'
installs) registers the title's ``extras`` button, shown while any Extras page shows (F32's
hide and ``[title] entries`` apply as to any title button), and makes the launch's one
``ThumbCache`` (``app.extras.thumbs``), which the pages' ports hand to their tile grids. It
pumps the launch's ``ImagePrefetcher`` (``app.prefetcher``) only in mode TITLE, so the
stage and the cache never both pump it in one frame (I-3).

Dev ``run --extras PAGE`` (``app.extras_page``): the launch opens persistent data in
MEMORY before any install (I-4; ``bootstrap`` sets ``no_persistent``), the shell shows the
title with Extras open on PAGE over it (``ShellPorts.extras_page``), and ``preview_all``,
after every install, unlocks each page's ``names()`` quietly in that memory store, so every
Extras page is full and nothing is written.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final

from engine.core.logsetup import get_logger
from engine.ui.menus import DEFAULT_ORDER, MenuEntry
from engine.ui.shell import Mode
from engine.ui.thumbs import ThumbCache

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.persistent import PersistentStore
    from engine.ui.menus import EntryContext

_log = get_logger("app")

EXTRAS_PAGES: Final = DEFAULT_ORDER["extras"]     # run --extras PAGE accepts these
EXTRAS_DEFAULT_PAGE: Final = "gallery"


@dataclass(frozen=True)
class ExtrasRow:
    """One Extras page as added: its entry, its unlock kind, and its declared names."""

    entry: MenuEntry
    kind: str
    names: Callable[[], Iterable[str]]


@dataclass
class ExtrasHost:
    """``app.extras``: the rows added so far and the launch's thumbnail cache."""

    thumbs: ThumbCache
    rows: list[ExtrasRow] = field(default_factory=list)


def install_extras(app: "App") -> ExtrasHost:
    """The title's ``extras`` button and ``app.extras`` (module docstring). Needs
    ``app.shell``; with ``app.extras_page`` set (``run --extras``), the shell's
    ``extras_page`` port too."""
    shell = app.shell
    assert shell is not None, "install_extras needs the shell (install_ui runs first)"
    thumbs = ThumbCache(app.assets, getattr(app, "prefetcher", None),
                        can_pump=lambda: shell.mode is Mode.TITLE)        # 07 I-3
    host = ExtrasHost(thumbs)
    app.extras = host                                               # type: ignore[attr-defined]

    def open_extras(ctx: "EntryContext") -> None:
        ctx.shell.open_extras(by=ctx.by)

    shell.menus.add("title", MenuEntry(
        "extras", action=open_extras, visible=lambda: bool(shell.menus.shown("extras"))))
    page = getattr(app, "extras_page", None)
    if page is not None:
        shell.ports = replace(shell.ports, extras_page=page)
    return host


def add_extras_page(app: "App", entry: MenuEntry, *, kind: str,
                    names: Callable[[], Iterable[str]]) -> None:
    """Add one Extras page (module docstring): ``entry`` joins the ``extras`` menu, and
    ``kind``/``names`` are kept for the dev preview. Once per page id, after
    ``install_extras``."""
    host = getattr(app, "extras", None)
    assert isinstance(host, ExtrasHost), "add_extras_page needs install_extras first"
    assert entry.page is not None, f"the Extras entry {entry.id!r} needs a page"
    app.shell.menus.add("extras", entry)
    host.rows.append(ExtrasRow(entry, kind, names))


def preview_all(app: "App", store: "PersistentStore") -> int:
    """Dev ``run --extras``: unlock every name of every Extras page quietly in ``store``
    (the launch's MEMORY store), after every install. Nothing without ``app.extras_page``.
    Returns how many names were new."""
    host = getattr(app, "extras", None)
    if getattr(app, "extras_page", None) is None or not isinstance(host, ExtrasHost):
        return 0
    added = 0
    for row in host.rows:
        for name in row.names():
            try:
                added += store.unlock(row.kind, name, quiet=True)
            except ValueError:                      # a kind not registered, a bad name
                _log.debug("run --extras: %s %r was not unlocked", row.kind, name)
    return added


__all__ = ["EXTRAS_DEFAULT_PAGE", "EXTRAS_PAGES", "ExtrasHost", "ExtrasRow", "add_extras_page",
           "install_extras", "preview_all"]

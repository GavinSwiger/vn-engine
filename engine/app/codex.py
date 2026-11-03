"""``install_codex``: F21's notices and codex page wired into one launch (F21
``04-technical.md`` §3, §7.6–7.9; ``07-architecture-review.md`` I-2, I-11, I-13).

Why this module exists: the runtime holds a ``CodexAdded`` for each new tip or item, and the
page needs the story's entries, tips, items, read marks, and pictures, but ``ui`` never
imports ``engine.app`` and the runtime never reads config. So, once per windowed launch
(``install_story``, after ``install_nvl`` and before ``install_settings_ui``):

- ``CodexAdded`` → ``shell.notify("<word>: <title>")`` with ``codex_new_tip`` or
  ``codex_new_item`` (06 D5), when ``[codex] notify`` is true, the shell exists, and no
  scene replay runs (F36: the tip is put back when it ends, so it isn't announced). The
  handler is always registered (the router raises on a command with none); headless runs
  release the same command and show nothing (06 D3).
- ``AppCodexPort``: the page's ``CodexPort`` over ``interp.codex`` (read through the story
  driver each call, so F39's reload is followed) and the launch's ``ImageIndex``.
  ``mark_read`` is the one presentation write to the store (§7.7, I-13), made while a menu
  holds the story.
- Two menu entries (§7.8): ``game`` ``codex`` (shown when the story declares any entry) and
  ``title`` ``codex`` (shown when a tip is unlocked; ``ui/menus.OPT_IN`` keeps it off the
  title unless ``[title] entries`` lists it). Their callables run no author code.

This module imports ``engine.script`` only for type checking (TR-F21-06).
"""

from typing import TYPE_CHECKING

from engine.runtime.commands import CodexAdded
from engine.runtime.images import ImageFile, SolidColor
from engine.ui.builtin.codex_page import HEADING, CodexPage
from engine.ui.menus import MenuEntry

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.codex import Codex, CodexCategory, CodexEntry
    from engine.runtime.images import ImageIndex
    from engine.runtime.interpreter import Interpreter


class AppCodexPort:
    """The page's ``CodexPort`` (``ui/builtin/codex_page.py``). ``codex()`` gives the live
    ``interp.codex``; ``images`` is the launch's ``ImageIndex`` (None: no pictures)."""

    def __init__(self, codex, images: "ImageIndex | None", *, show_locked: bool) -> None:
        self._codex = codex
        self.images = images
        self.show_locked = show_locked

    @property
    def codex(self) -> "Codex":
        return self._codex()

    def entries(self) -> "tuple[CodexEntry, ...]":
        return tuple(self.codex.index)

    def categories(self) -> "tuple[CodexCategory, ...]":
        return self.codex.index.categories

    def tips(self) -> tuple[str, ...]:
        return self.codex.tips()

    def items(self) -> tuple[str, ...]:
        return self.codex.items()

    def is_read(self, name: str) -> bool:
        return self.codex.is_read(name)

    def mark_read(self, name: str) -> None:
        self.codex.mark_read(name)

    def picture(self, image: str) -> "str | tuple[int, int, int] | None":
        """§7.9: an ``ImageFile``'s ref, a ``SolidColor``'s RGB, or None (no such name)."""
        found = self.images.get(image) if self.images is not None else None
        if isinstance(found, ImageFile):
            return found.ref
        if isinstance(found, SolidColor):
            return found.rgb
        return None


def notice_text(words, cmd: CodexAdded) -> str:
    """06 D5: ``<word>: <title>`` (the title is the script's plain text)."""
    return f"{words.get('codex_new_' + cmd.kind)}: {cmd.title}"


def install_codex(app: "App", interp: "Interpreter",
                  images: "ImageIndex | None" = None) -> AppCodexPort:
    """Register the ``CodexAdded`` handler and, with a shell, the two codex entries
    (module docstring). Returns the port."""

    def codex() -> "Codex":
        story = getattr(app, "story", None)
        live = getattr(story, "interp", None)
        return (live if live is not None else interp).codex

    def on_added(cmd: CodexAdded) -> None:
        shell = getattr(app, "shell", None)
        if shell is None or not app.config.codex.notify:
            return
        if getattr(shell, "replay", None) is not None:
            return                      # F36 (04 decision 9): a replay's tip isn't kept
        shell.notify(notice_text(shell.words, cmd))

    app.router.register(CodexAdded, on_added)
    port = AppCodexPort(codex, images, show_locked=app.config.codex.show_locked)
    shell = getattr(app, "shell", None)
    if shell is not None:
        shell.menus.add("game", MenuEntry(
            HEADING, page=lambda host: CodexPage(port, from_title=False),
            visible=lambda: len(codex().index) > 0))
        shell.menus.add("title", MenuEntry(
            HEADING, page=lambda host: CodexPage(port, from_title=True),
            visible=lambda: bool(codex().tips())))
    return port


__all__ = ["AppCodexPort", "install_codex", "notice_text"]

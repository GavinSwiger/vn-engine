"""``KindPage``: the game-menu page of codex kinds listed on a page of their own (F65 round 1,
"Codex kinds"; the Inbox is the first).

Why this module exists: a codex kind (``core/codexkinds``) names the page that lists it.
Tips and items share the ``codex`` page (``codex_page.CodexPage``); every other page is this
one, the same ``CodexView`` (list, unread dots, detail panel, keys and mouse) filtered to
the kinds registered on that page. So a later kind (contacts, goals, thoughts) needs a
description, a port that lists it, and ``KindPage(port, "<page>")`` in a ``MenuEntry``.

- ``heading`` is the page name, a ``[words]`` key (``inbox``); a kit can fill that word in
  (``kits.kit_words``: "Messages", "Letters") where the author left it at its default.
- No purse, no pick or Use button, never opened from the title screen.
"""

from typing import TYPE_CHECKING

from engine.core.codexkinds import page_kinds
from engine.ui.builtin.codex_page import CodexFilter, CodexPage, CodexPort, CodexView

if TYPE_CHECKING:
    from engine.ui.focus import Box, FocusGroup
    from engine.ui.menus import PageHost


class KindPage(CodexPage):
    """The page ``page`` (module docstring)."""

    def __init__(self, port: CodexPort, page: str) -> None:
        super().__init__(port, from_title=False)
        self.heading = page
        self.filter = CodexFilter(frozenset(k.name for k in page_kinds(page)))

    def build(self, host: "PageHost", body: "Box") -> "list[FocusGroup]":
        self.host = host
        if self.view is None:
            self.view = CodexView(self.port, ui=host.shell, filter=self.filter,
                                  scope=lambda: host.scope)
        return self.view.build(body, host.painter.text_scale())


__all__ = ["KindPage"]

"""``ReplyRow``: the Inbox page's reply buttons and reply marker (F65 round 3, "Replies as
choices"; the story side is ``runtime/send.py``).

Why this module exists: a sent message can end with an ask (``{"ask": ["I'll be there.",
"Not this year."]}``). The player answers in the Inbox at their own pace, so the page needs
the replies as buttons under the message and a mark on each thread that still waits for an
answer. This is a mixin for any ``CodexView`` (the Inbox's own view draws each device look,
``inbox_view.InboxView``; ``reply_view(base)`` makes the class the page shows), so it works
whatever draws the messages:

- **The port** says what to offer (all optional; a port without them shows no buttons):
  ``reply_options(name)`` the ``(id, text)`` replies of entry ``name``'s newest message that
  waits for a reply (() for none), ``can_reply()`` whether a reply counts now (the story
  waits at a line or an ``open``; ``runtime/send.can_reply``), and ``reply(name, id)``,
  which posts it. ``reply_waiting(name)`` marks the row.
- **Buttons.** Up to ``REPLIES_MAX`` (4) buttons share the row under the detail panel (the
  codex's pick row, ``codex_layout(pick=True)``), one per reply, in the message's order,
  each labelled with its text (cut with "…" when it doesn't fit). They are one focus group,
  shown only while the selected thread waits for a reply, and disabled while a reply
  can't count (at a choice menu: answer after picking). Pressing one posts the reply; the
  thread then shows it as the player's line and the buttons go (``update`` notices the
  options changed, lays the entry out again and asks the host to build again).
- **The marker.** A thread that waits for a reply has a ring (in the unread dot's color)
  left of where the unread dot goes, so an answered thread and an unanswered one differ at
  a glance even once both are read.

Pure UI: no runtime import; the port is the only way in.
"""

from functools import partial
from typing import TYPE_CHECKING, Any, Final

from engine.ui.builtin.codex_page import CodexView, new_dot_color
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import CODEX_DOT, CODEX_DOT_INSET, CODEX_GAP, CODEX_TITLE_LINES
from engine.ui.nav import Nav
from engine.ui.widgets import Button

if TYPE_CHECKING:
    from engine.ui.paint import Painter
    from engine.ui.widgets import Look, Widget

REPLIES_MAX: Final = 4                  # script/inbox.REPLIES_MAX (the UI imports no script)
MARK_GAP: Final = 6                     # between the reply ring and the unread dot
_PICK_ROW: Final = object()             # stands in for a PickAction while laying out


class ReplyRow:
    """Mixin for a ``CodexView`` subclass (module docstring). Put it first in the bases."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)                       # type: ignore[call-arg]
        self.reply_buttons = [Button(partial(self._reply_label, i), partial(self._reply, i),
                                     enabled=self._can_reply) for i in range(REPLIES_MAX)]
        self._replies_shown: tuple | None = None

    # -- the port --

    def reply_options(self) -> tuple[tuple[str, str], ...]:
        """The selected entry's replies, ``(id, text)`` (() for none)."""
        view: Any = self
        options = getattr(view.port, "reply_options", None)
        name = view.selected
        if options is None or name is None:
            return ()
        return tuple(options(name))[:REPLIES_MAX]

    def _reply_label(self, index: int) -> str:
        options = self.reply_options()
        return options[index][1] if index < len(options) else ""

    def _can_reply(self) -> bool:
        can = getattr(getattr(self, "port", None), "can_reply", None)
        return can is not None and bool(can())

    def _reply(self, index: int) -> None:
        view: Any = self
        options = self.reply_options()
        if index < len(options) and self._can_reply():
            view.port.reply(view.selected, options[index][0])

    def _waiting(self, name: str) -> bool:
        waiting = getattr(getattr(self, "port", None), "reply_waiting", None)
        return waiting is not None and bool(waiting(name))

    # -- CodexView's hooks --

    def _groups(self) -> list[FocusGroup]:
        groups = super()._groups()                              # type: ignore[misc]
        options = self.reply_options()
        self._replies_shown = options
        if options and getattr(self, "tabs", ()):
            groups.append(FocusGroup(self.reply_buttons[:len(options)]))
        return groups

    def update(self, dt: float) -> None:
        super().update(dt)                                      # type: ignore[misc]
        options = self.reply_options()
        if self._replies_shown is not None and options != self._replies_shown:
            view: Any = self
            view._refresh()                                     # the entry's new lines
            view.groups_changed = True

    def _layout_for(self, entry: Any, title_lines: int = CODEX_TITLE_LINES) -> Any:
        """The base layout, with the pick row when ``entry`` waits for a reply."""
        view: Any = self
        port_options = getattr(view.port, "reply_options", None)
        wants = (entry is not None and view.pick is None and port_options is not None
                 and bool(port_options(entry.name)))
        if not wants:
            return super()._layout_for(entry, title_lines)      # type: ignore[misc]
        view.pick = _PICK_ROW
        try:
            return super()._layout_for(entry, title_lines)      # type: ignore[misc]
        finally:
            view.pick = None

    def _place(self, layout: Any) -> None:
        super()._place(layout)                                  # type: ignore[misc]
        row = layout.pick
        options = self.reply_options()
        if row is None or not options:
            return
        n = len(options)
        width = (row.w - CODEX_GAP * (n - 1)) / n
        for i, button in enumerate(self.reply_buttons[:n]):
            button.box = Box(row.x + i * (width + CODEX_GAP), row.y, width, row.h)

    def _route(self, w: "Widget | None", nav: Nav) -> bool:
        if w is not None and w in self.reply_buttons and nav is Nav.ACTIVATE:
            w.activate()                                        # type: ignore[attr-defined]
            return True
        return super()._route(w, nav)                           # type: ignore[misc]

    def _draw_row(self, p: "Painter", index: int, box: Box, look: "Look") -> None:
        super()._draw_row(p, index, box, look)                  # type: ignore[misc]
        view: Any = self
        rows = view.rows()
        if not 0 <= index < len(rows) or rows[index].locked:
            return
        if self._waiting(rows[index].entry.name):
            r = CODEX_DOT / 2
            cx = box.right - CODEX_DOT_INSET - CODEX_DOT - MARK_GAP - r
            cy = box.y + box.h / 2
            p.ellipse(Box(cx - r, cy - r, CODEX_DOT, CODEX_DOT), new_dot_color(view.cfg),
                      ring=max(1.5, CODEX_DOT / 5))


def reply_view(base: type[CodexView] = CodexView) -> type[CodexView]:
    """``base`` with the reply buttons and marker (``ReplyRow`` first in its bases)."""
    return type(f"Reply{base.__name__}", (ReplyRow, base), {})   # type: ignore[return-value]


__all__ = ["MARK_GAP", "REPLIES_MAX", "ReplyRow", "reply_view"]

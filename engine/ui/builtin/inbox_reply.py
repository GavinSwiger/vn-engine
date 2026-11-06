"""``ReplyRow``: the Inbox page's reply buttons and reply marker (F65 round 3, "Replies as
choices"; the story side is ``runtime/send.py``).

Why this module exists: a sent message can end with an ask (``{"ask": ["I'll be there.",
"Not this year."]}``). The player answers in the Inbox at their own pace, so the page needs
the replies as buttons under the message and a mark on each thread that still waits for an
answer. This is a mixin for any ``CodexView`` (the Inbox's own view draws each device look,
``inbox_view.InboxView``; ``reply_view(base)`` makes the class the page shows), so it works
whatever draws the messages:

- **The port** says what to offer (all optional; a port without them shows no buttons):
  ``reply_asks(name)`` each message of entry ``name`` that waits for a reply, as a
  ``ReplyAsk`` (the body paragraph it ends on, its key and its ``(id, text)`` replies);
  a port with only ``reply_options(name)`` (the newest waiting message's replies) gets
  them under the last paragraph. ``can_reply()`` says whether a reply counts now (the
  story waits at a line or an ``open``; ``runtime/send.can_reply``), and ``reply(name, id,
  key)`` posts it. ``reply_waiting(name)`` marks the row.
- **Buttons.** Every message that waits for a reply has its own buttons right under it, in
  the scrolling body: room is kept under the paragraph it ends on (``_Body.extra``), and
  the buttons move with the body's scroll and show only inside it. Up to ``REPLIES_MAX``
  (4) per message, in the message's order, side by side; two to a row when the body is too
  narrow for each to be ``REPLY_MIN_W`` wide. A reply's text wraps to two lines inside its
  button; past two the second line ends with "…", and while the button is focused the
  whole text shows in a tip above the buttons. Each row is one focus group (after the
  body's), disabled while a reply can't count (at a choice menu: answer after picking),
  and a focused button scrolls into view. Pressing one posts that message's reply; the
  thread then shows it as the player's line and its buttons go (``update`` notices the
  asks changed, lays the entry out again and asks the host to build again).
- **The marker.** A thread that waits for a reply has a ring (in the unread dot's color)
  left of where the unread dot goes, so an answered thread and an unanswered one differ at
  a glance even once both are read.

Pure UI: no runtime import; the port is the only way in.
"""

import dataclasses
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from engine.render.text import text_width
from engine.ui.builtin.codex_page import CodexView, new_dot_color
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import (CODEX_DOT, CODEX_DOT_INSET, cut_to_width, pitch, scaled,
                               wrap_text)
from engine.ui.nav import Nav
from engine.ui.paint import frame_state
from engine.ui.widgets import Button

if TYPE_CHECKING:
    from engine.ui.paint import Painter
    from engine.ui.widgets import Look, Widget

REPLIES_MAX: Final = 4                  # script/inbox.REPLIES_MAX (the UI imports no script)
MARK_GAP: Final = 6                     # between the reply ring and the unread dot
REPLY_GAP: Final = 10                   # message to buttons, button to button
REPLY_MIN_W: Final = 180                # narrower than this: two buttons to a row
LABEL_LINES: Final = 2                  # a reply's text wraps to this many lines
LABEL_PAD: Final = 8                    # above and below a two-line label
TIP_PAD: Final = 8


@dataclass(frozen=True)
class ReplyAsk:
    """One message that waits for a reply: ``at`` the body paragraph it ends on, ``key`` the
    delivery's key ("" when the port gives only ``reply_options``), ``options`` its
    ``(id, text)`` replies."""

    at: int
    key: str
    options: tuple[tuple[str, str], ...]


def _columns(n: int, width: float) -> int:
    """How many of ``n`` buttons share a row ``width`` wide."""
    if n <= 2 or (width - REPLY_GAP * (n - 1)) / n >= REPLY_MIN_W:
        return max(1, n)
    return 2


def _label_lines(p: "Painter", text: str, width: float, state: str
                 ) -> tuple[list[str], Any, int, bool]:
    """``text`` in the button font, wrapped to ``width`` on at most ``LABEL_LINES`` lines
    (the last cut with "…"): the lines, the font, its pitch and whether it was cut."""
    style = p.style("button", state)
    size = p.scaled_size(style.font.size)
    canvas = p.canvas

    def measure(part: str, at: int) -> float:
        return text_width(canvas.font_handle(style.font, at).font, part)

    lines = wrap_text(text, max(1.0, width), size, measure) or [text]
    cut = len(lines) > LABEL_LINES
    if cut:
        rest = " ".join(lines[LABEL_LINES - 1:])
        lines = [*lines[:LABEL_LINES - 1], cut_to_width(rest, max(1.0, width), size, measure)]
    elif lines and measure(lines[-1], size) > width:
        lines[-1] = cut_to_width(lines[-1], max(1.0, width), size, measure)
        cut = True
    return lines, dataclasses.replace(style.font, size=size), pitch(size), cut


class ReplyButton(Button):
    """A reply: its text wrapped to two lines; cut, the whole text in a tip while focused."""

    def __init__(self, text: str, action: Any, *, enabled: Any, where: Any) -> None:
        super().__init__(lambda: text, action, enabled=enabled)
        self.text = text
        self.where = where                  # () -> (its message's buttons, the body's box)

    def draw(self, p: "Painter", look: "Look") -> None:
        state = frame_state(look)
        p.widget_frame(self.box, self.area, look)
        style = p.style(self.area, state)
        width = self.box.w - 2 * style.side_padding
        lines, font, pt, cut = _label_lines(p, self.text, width, state)
        cx = self.box.x + self.box.w / 2
        top = self.box.y + (self.box.h - pt * len(lines)) / 2
        for i, line in enumerate(lines):
            p.canvas.draw_text(line, font, style.text_color, (cx, top + i * pt + pt / 2),
                               anchor="center")
        if cut and look.state in ("focused", "pressed"):
            self._tip(p, font, pt)

    def _tip(self, p: "Painter", font: Any, pt: int) -> None:
        """The whole text in a panel over the message, above its buttons (below them when
        there is no room above)."""
        block, view = self.where()
        canvas = p.canvas

        def measure(part: str, at: int) -> float:
            return text_width(canvas.font_handle(font, at).font, part)

        lines = wrap_text(self.text, max(1.0, block.w - 2 * TIP_PAD), font.size, measure) \
            or [self.text]
        h = len(lines) * pt + 2 * TIP_PAD
        y = block.y - REPLY_GAP - h
        if y < view.y:
            y = block.bottom + REPLY_GAP
        box = Box(block.x, y, block.w, h)
        p.panel(box)
        color = p.style("panel").text_color
        for i, line in enumerate(lines):
            canvas.draw_text(line, font, color,
                             (box.x + TIP_PAD, box.y + TIP_PAD + i * pt + pt / 2),
                             anchor="midleft")


class ReplyRow:
    """Mixin for a ``CodexView`` subclass (module docstring). Put it first in the bases."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)                       # type: ignore[call-arg]
        self.reply_rows: list[tuple[ReplyAsk, list[ReplyButton]]] = []
        self._asks_shown: tuple[ReplyAsk, ...] | None = None
        self._reply_width = 0.0

    # -- the port --

    def asks_of(self, name: str | None) -> tuple[ReplyAsk, ...]:
        """Entry ``name``'s messages that wait for a reply (module docstring)."""
        view: Any = self
        port = view.port
        if name is None:
            return ()
        get = getattr(port, "reply_asks", None)
        if get is not None:
            return tuple(ReplyAsk(a.at, a.key, tuple(a.options)[:REPLIES_MAX])
                         for a in get(name) if a.options)
        options = getattr(port, "reply_options", None)
        found = tuple(options(name))[:REPLIES_MAX] if options is not None else ()
        entry = next((r.entry for r in view.rows() if r.entry.name == name), None)
        if not found or entry is None or not entry.paragraphs:
            return ()
        return (ReplyAsk(len(entry.paragraphs) - 1, "", found),)

    def reply_asks(self) -> tuple[ReplyAsk, ...]:
        view: Any = self
        return self.asks_of(view.selected)

    def reply_options(self) -> tuple[tuple[str, str], ...]:
        """The first (newest) waiting message's replies, ``(id, text)`` (() for none)."""
        asks = self.reply_asks()
        return asks[0].options if asks else ()

    @property
    def reply_buttons(self) -> list[ReplyButton]:
        """Every reply button shown, top to bottom."""
        return [b for _ask, buttons in self.reply_rows for b in buttons]

    def _can_reply(self) -> bool:
        can = getattr(getattr(self, "port", None), "can_reply", None)
        return can is not None and bool(can())

    def _reply(self, ask: ReplyAsk, reply: str) -> None:
        view: Any = self
        if self._can_reply() and view.selected is not None:
            if ask.key:
                view.port.reply(view.selected, reply, ask.key)
            else:
                view.port.reply(view.selected, reply)

    def _waiting(self, name: str) -> bool:
        waiting = getattr(getattr(self, "port", None), "reply_waiting", None)
        return waiting is not None and bool(waiting(name))

    # -- room and places --

    def _block_height(self, n: int, width: float) -> int:
        view: Any = self
        size = scaled(view.cfg.button.text_size, view.scale)
        one = max(view.cfg.button.height, LABEL_LINES * pitch(size) + 2 * LABEL_PAD)
        rows = math.ceil(n / _columns(n, width))
        return rows * one + (rows - 1) * REPLY_GAP

    def _paragraphs(self, entry: Any, width: float) -> Any:
        """The base body, with room under each paragraph a waiting message ends on."""
        body = super()._paragraphs(entry, width)                # type: ignore[misc]
        self._reply_width = width
        want = {a.at: REPLY_GAP + self._block_height(len(a.options), width)
                for a in self.asks_of(entry.name) if 0 <= a.at < len(body.heights)}
        if want != body.extra:
            for i in set(want) | set(body.extra):
                body.heights[i] += want.get(i, 0) - body.extra.get(i, 0)
            body.extra = want
        return body

    def _reply_block(self, ask: ReplyAsk) -> Box:
        """Where ``ask``'s buttons go on the canvas at the body's scroll."""
        view: Any = self
        body, detail = view.body, view._detail.body
        if not 0 <= ask.at < len(detail.heights):
            return Box(0, 0, 0, 0)
        row = body.row_box(ask.at)
        extra = detail.extra.get(ask.at, 0)
        h = extra - REPLY_GAP
        bottom = row.bottom - (detail.gap(ask.at) - extra)
        return Box(row.x, bottom - h, row.w, h)

    def _place_replies(self) -> None:
        for ask, buttons in self.reply_rows:
            block = self._reply_block(ask)
            n = len(buttons)
            cols = _columns(n, self._reply_width)
            rows = math.ceil(n / cols)
            h = (block.h - (rows - 1) * REPLY_GAP) / rows
            w = (block.w - REPLY_GAP * (cols - 1)) / cols
            for i, button in enumerate(buttons):
                r, c = divmod(i, cols)
                button.box = Box(block.x + c * (w + REPLY_GAP), block.y + r * (h + REPLY_GAP),
                                 w, h)

    def _show_focused(self) -> None:
        """A focused reply button scrolls into the body's view."""
        view: Any = self
        scope = view._scope()
        focused = getattr(scope, "focused", None)
        for ask, buttons in self.reply_rows:
            if any(b is focused for b in buttons):
                block = self._reply_block(ask)
                body = view.body
                top = block.y - body.box.y + body.scroll
                body._scroll_into_view(top, top + block.h)
                return

    def _sync_rows(self) -> None:
        asks = self.reply_asks()
        if tuple(ask for ask, _b in self.reply_rows) == asks:
            return
        self.reply_rows = [(ask, [ReplyButton(text, lambda a=ask, k=key: self._reply(a, k),
                                              enabled=self._can_reply,
                                              where=lambda a=ask: (self._reply_block(a),
                                                                   self.body.box))
                                  for key, text in ask.options]) for ask in asks]

    # -- CodexView's hooks --

    def _show(self, entry: Any) -> None:
        super()._show(entry)                                    # type: ignore[misc]
        self._sync_rows()
        self._place_replies()

    def _groups(self) -> list[FocusGroup]:
        groups = super()._groups()                              # type: ignore[misc]
        self._sync_rows()
        self._asks_shown = self.reply_asks()
        self._place_replies()
        view: Any = self
        if self.reply_rows and getattr(view, "tabs", ()):
            clip = view.body.box
            for ask, buttons in self.reply_rows:
                cols = _columns(len(buttons), self._reply_width)
                for start in range(0, len(buttons), cols):
                    groups.append(FocusGroup(buttons[start:start + cols], clip=clip))
        return groups

    def update(self, dt: float) -> None:
        super().update(dt)                                      # type: ignore[misc]
        asks = self.reply_asks()
        view: Any = self
        if self._asks_shown is not None and asks != self._asks_shown:
            view._refresh()                                     # the entry's new lines
            view.groups_changed = True
        self._show_focused()
        self._place_replies()

    def _route(self, w: "Widget | None", nav: Nav) -> bool:
        if w is not None and nav is Nav.ACTIVATE and any(w is b for b in self.reply_buttons):
            w.activate()
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


__all__ = ["MARK_GAP", "REPLIES_MAX", "REPLY_GAP", "ReplyAsk", "ReplyButton", "ReplyRow",
           "reply_view"]

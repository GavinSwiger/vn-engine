"""``EndingsPage``: the Extras screen's Endings page (F36 ``01-design.md`` §6.1 UI-F36-01 to
03, PR-F36-01 and 02; ``04-technical.md`` §3, §7.5).

Why this module exists: the player sees which endings they have reached and how many are
left, and can watch a reached one again (a replay of the label the ending is in). The page
reads the story only through an ``EndingsPort`` (``app/replays.py``'s, F36-W3), so ``ui``
never imports ``script``, ``runtime`` or ``persist``, and it tests with fakes.

- **Rows** (``endings_rows``, pure): every ending in script order (F19's ``EndingIndex``
  order, as the port gives it). A reached one shows its heading and title; the rest show
  ``ending_locked`` and are disabled (never focused, never activated). A change of the
  endings, the reached names, or ``replay_on`` (``update``) makes the rows again; the
  focused ending stays focused (by name).
- **Count line**: ``endings_count`` + ": 2 / 5" (reached declared endings / all endings).
- **Layout** (``endings_layout``, pure; §6.1 at 100 % text in F10's body slot (416, 112,
  808×552)): the count line (416, 112, 808×40) in ``panel.text_*``; the list
  (416, 164, 808×500), rows ``max(list.row_height, pitch + 16)`` at ``button.text_size``.
  A reached row: the heading at x + 16 in ``panel.heading.text_color``, cut with "…" to
  232; the title at x + 264 in ``button.text_color`` (x + 16 with no heading), cut to the
  space left; ``ending_replay`` right-aligned 16 inside the row (the row already stops at the
  scrollbar lane) in ``button.marker.fill_color``, only while ``replay_on``. A locked row:
  ``ending_locked`` at x + 16 in ``button.disabled.text_color``. At F16's larger text the
  count line grows to its text's pitch and the list starts 12 below it (UI-F36-03); rows
  re-pitch and the focused row is scrolled back into view on every build.
- **Input** (UI-F36-02): F10's ``ScrollList`` keys, wheel (anywhere in the slot) and
  scrollbar. Click or Activate on a reached row calls ``port.start(name, by)`` while
  ``replay_on`` (otherwise nothing). Opened by keys, the first reached row is focused.
- ``widget_for(name)``: the list with ``name``'s row focused and in view, for W3's
  ``open_extras(focus=)`` after a replay; None for a locked or unknown ending.

Theme: existing tokens only. Words: ``endings`` (the heading), ``endings_count``,
``ending_locked``, ``ending_replay`` (``WORD_DEFAULTS`` until F36-W3 adds them to
``[words]``).
"""

from collections import OrderedDict
from collections.abc import Collection, Hashable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from engine.ui.builtin.tile_grid import word_or
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import (
    BUTTON_TEXT_SIZE,
    LIST_ROW_HEIGHT,
    PAGE_BODY,
    PANEL_TEXT_SIZE,
    cut_to_width,
    pitch,
    scaled,
)
from engine.ui.menus import MenuPageBase
from engine.ui.nav import InputKind
from engine.ui.theme import measure_with
from engine.ui.widgets import ListRow, Look, ScrollList

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.ui.menus import PageHost
    from engine.ui.paint import Painter
    from engine.ui.widgets import Widget

HEADING: Final = "endings"
WORD_DEFAULTS: Final[dict[str, str]] = {
    "endings": "Endings", "endings_count": "Endings reached", "ending_locked": "???",
    "ending_replay": "Replay",
}

# Layout (§6.1), canvas units at 100 % text.
COUNT_HEIGHT: Final = 40              # the count line's box (grows to its pitch at larger text)
LIST_GAP: Final = 12                  # count line → list
ROW_PAD: Final = 16                   # a row is pitch + 16 tall at least
HEADING_X: Final = 16
HEADING_W: Final = 232
TITLE_X: Final = 264
REPLAY_RIGHT: Final = 16              # "Replay" ends this far inside the row
TITLE_GAP: Final = 16                 # the title is cut this far before "Replay"
CUT_CACHE: Final = 512


# --- Seams ---------------------------------------------------------------------------------

class EndingLike(Protocol):
    """An ending as the port gives it (``runtime/endings.py``'s ``EndingInfo`` fits)."""

    @property
    def name(self) -> str: ...

    @property
    def heading(self) -> str | None: ...

    @property
    def title(self) -> str: ...


class EndingsPort(Protocol):
    """What the page reads (04 §3, §7.5): every ending in script order, the reached ending
    names, whether reached endings can be replayed (``[endings] replay``), and ``start``,
    which starts the replay of ending ``name`` (W3: the label it is in), ``by`` the input
    that picked it (for the focus when Extras comes back)."""

    @property
    def replay_on(self) -> bool: ...

    def endings(self) -> Sequence[EndingLike]: ...

    def reached(self) -> Collection[str]: ...

    def start(self, name: str, by: InputKind) -> None: ...


@dataclass(frozen=True)
class EndingRow:
    """One row as drawn: the ending's name, its heading and title (shown only when
    reached)."""

    name: str
    heading: str | None
    title: str
    reached: bool


def endings_rows(port: EndingsPort) -> tuple[EndingRow, ...]:
    """Every ending in the port's order, reached or not (module docstring)."""
    reached = set(port.reached())
    return tuple(EndingRow(e.name, e.heading or None, e.title, e.name in reached)
                 for e in port.endings())


def count_text(label: str, rows: Sequence[EndingRow]) -> str:
    """``label`` + ": reached / all", e.g. "Endings reached: 2 / 5"."""
    return f"{label}: {sum(r.reached for r in rows)} / {len(rows)}"


@dataclass(frozen=True)
class EndingsLayout:
    count: Box
    count_size: int
    list: Box
    row_height: int
    text_size: int                    # the rows' text size now


def endings_layout(body: Box = PAGE_BODY, text_scale: float = 1.0, *,
                   row_min: int = LIST_ROW_HEIGHT, text_size: int = BUTTON_TEXT_SIZE,
                   count_size: int = PANEL_TEXT_SIZE) -> EndingsLayout:
    """§6.1 (pure; module docstring)."""
    count_now = scaled(count_size, text_scale)
    count_h = max(COUNT_HEIGHT, pitch(count_now))
    count = Box(body.x, body.y, body.w, count_h)
    top = count.bottom + LIST_GAP
    size = scaled(text_size, text_scale)
    return EndingsLayout(count, count_now, Box(body.x, top, body.w, max(0.0, body.bottom - top)),
                         max(row_min, pitch(size) + ROW_PAD), size)


# --- The page ------------------------------------------------------------------------------

class EndingsPage(MenuPageBase):
    """The ``endings`` page of the Extras screen (module docstring)."""

    heading = HEADING

    def __init__(self, port: EndingsPort) -> None:
        self.port = port
        self.host: "PageHost | None" = None
        self.rows: tuple[EndingRow, ...] = ()
        self.list_rows: list[ListRow] = []
        self.replay_on = False
        self.layout = endings_layout()
        self._signature: tuple | None = None
        self._cuts: OrderedDict[tuple, str] = OrderedDict()
        self.list = ScrollList(lambda: self.list_rows, self._activate, draw_row=self._draw_row,
                               enabled=lambda: any(r.reached for r in self.rows))
        self._refresh()

    # -- MenuPage --

    def build(self, host: "PageHost", body: Box) -> list[FocusGroup]:
        self.host = host
        cfg = host.shell.theme.cfg
        self.layout = endings_layout(body, host.painter.text_scale(),
                                     row_min=cfg.list.row_height, text_size=cfg.button.text_size,
                                     count_size=cfg.panel.text_size)
        self._refresh()
        lst = self.list
        lst.box = self.layout.list
        lst.row_height = self.layout.row_height
        index = lst.focus_row
        if not (0 <= index < len(self.rows) and self.rows[index].reached):
            index = self._first_reached()
        if index is not None:
            lst.focus_index(index)                 # re-pitched rows: the focus stays in view
        return [FocusGroup([lst])]

    def update(self, dt: float) -> None:
        self._refresh()

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        """The count line (the host draws the list)."""
        host = self.host
        if host is None:
            return
        shell = host.shell
        cfg = shell.theme.cfg
        box = self.layout.count
        text = count_text(self._word("endings_count"), self.rows)
        canvas.draw_text(text, shell.theme.font(self.layout.count_size),
                         tuple(cfg.panel.text_color), (box.x, box.y + box.h / 2),
                         anchor="midleft")

    def on_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        """The wheel anywhere in the slot scrolls the list."""
        return kind == "wheel" and self.list.on_mouse("wheel", pos, notches=notches)

    def default_widget(self) -> "Widget | None":
        return self.list if self._first_reached() is not None else None

    def widget_for(self, key: Hashable) -> "Widget | None":
        """The list with ending ``key``'s row focused and in view; None when it is locked
        or unknown."""
        index = next((i for i, r in enumerate(self.rows) if r.name == key and r.reached), None)
        if index is None:
            return None
        self.list.focus_index(index)
        return self.list

    # -- reads (tests and draw) --

    def row_texts(self, index: int) -> tuple[str | None, str, str | None]:
        """Row ``index``'s heading, title and replay word as drawn (uncut); a locked row is
        (None, ``ending_locked``, None)."""
        row = self.rows[index]
        if not row.reached:
            return None, self._word("ending_locked"), None
        return row.heading, row.title, self._word("ending_replay") if self.replay_on else None

    # -- internals --

    def _word(self, key: str) -> str:
        host = self.host
        return word_or(host.shell.words, key, WORD_DEFAULTS[key]) if host is not None \
            else WORD_DEFAULTS[key]

    def _first_reached(self) -> int | None:
        return next((i for i, r in enumerate(self.rows) if r.reached), None)

    def _refresh(self) -> None:
        port = self.port
        endings = tuple(port.endings())
        reached = frozenset(port.reached())
        replay_on = bool(port.replay_on)
        signature = (endings, reached, replay_on)
        if signature == self._signature:
            return
        old = self.rows
        focus = self.list.focus_row
        focused = old[focus].name if 0 <= focus < len(old) else None
        self._signature = signature
        self.replay_on = replay_on
        self.rows = endings_rows(port)
        self.list_rows = [ListRow(r.title if r.reached else "", r.reached) for r in self.rows]
        index = next((i for i, r in enumerate(self.rows) if r.name == focused and r.reached),
                     None)
        if index is None:
            index = self._first_reached()
        self.list.focus_row = index if index is not None else 0

    def _activate(self, index: int) -> None:
        if not (self.replay_on and 0 <= index < len(self.rows) and self.rows[index].reached):
            return
        scope = self.host.scope if self.host is not None else None
        by = scope.source if scope is not None and scope.source is not None else InputKind.KEYS
        self.port.start(self.rows[index].name, by)

    def _cut(self, text: str, width: float, size: int) -> str:
        key = (text, round(width, 3), size)
        found = self._cuts.get(key)
        if found is not None:
            self._cuts.move_to_end(key)
            return found
        assert self.host is not None
        shell = self.host.shell
        found = cut_to_width(text, max(1.0, width), size,
                             measure_with(shell.assets, shell.theme.font(size)))
        self._cuts[key] = found
        if len(self._cuts) > CUT_CACHE:
            self._cuts.popitem(last=False)
        return found

    def _draw_row(self, p: "Painter", index: int, box: Box, look: Look) -> None:
        host = self.host
        if host is None or not 0 <= index < len(self.rows):
            return
        shell = host.shell
        cfg = shell.theme.cfg
        canvas = p.canvas
        size = self.layout.text_size
        font = shell.theme.font(size)
        cy = box.y + box.h / 2
        heading, title, replay = self.row_texts(index)
        if not self.rows[index].reached:
            canvas.draw_text(title, font, tuple(cfg.button.disabled.text_color),
                             (box.x + HEADING_X, cy), anchor="midleft")
            return
        title_x = box.x + HEADING_X
        if heading:
            canvas.draw_text(self._cut(heading, HEADING_W, size), font,
                             tuple(cfg.panel.heading.text_color), (title_x, cy),
                             anchor="midleft")
            title_x = box.x + TITLE_X
        right = box.right - REPLAY_RIGHT
        if replay is not None:
            bounds = canvas.draw_text(replay, font, tuple(cfg.button.marker.fill_color),
                                      (right, cy), anchor="midright")
            right -= bounds[2] + TITLE_GAP
        canvas.draw_text(self._cut(title, right - title_x, size), font,
                         tuple(cfg.button.text_color), (title_x, cy), anchor="midleft")


__all__ = ["EndingLike", "EndingRow", "EndingsLayout", "EndingsPage", "EndingsPort", "HEADING",
           "WORD_DEFAULTS", "count_text", "endings_layout", "endings_rows"]

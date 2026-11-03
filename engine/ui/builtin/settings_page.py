"""``SettingsPage``: the player's settings, a page of the game menu and of the title (F16
``01-design.md`` §6; ``04-technical.md`` §5.6, §7.4; ``07-architecture-review.md`` I-8).

Why this module exists: one page holds every setting (text, sound, display, the reduce
motion switch, Reset settings, Delete progress), and every change applies at once with no
Apply step (PR-F16-01, 02). The page reaches the settings only through ``SettingsPort``
(``app/settings.py``'s ``SettingsService`` implements it), so ``ui`` never imports
``engine.app`` or ``engine.persist`` (TR-F16-05).

- **Rows** (design §6.1), in four groups under headings that are never focused: Display
  (Fullscreen, Reduce motion), Text (Text speed, Text size, Auto-advance wait and its voice
  toggle, Skip unread text), Sound (four volumes, Text blips, Let voices finish, the two
  background toggles, Mono audio), Data (Reset settings; Delete progress on the title only).
  Each widget is built once per page; a layout only moves its box, so the focus scope keeps
  focus across a rebuild.
- **Text speed** is ``Slider(10, 210, step=10)``: 210 is Instant, stored as ``text_cps`` 0.
  A config value outside 10–200 shows the nearest end and applies until the player moves
  the slider. Reduce motion shows the effective flag (config OR player) and is disabled while
  ``[effects] reduce`` locks it on.
- **Column** (``SettingsColumn``, OQ-3): content ``y`` from 0; a heading is ``H_b`` tall with
  16 above it (not the first), rows are ``H_b`` (toggles, buttons) or a slider row tall, 8
  apart. Taller than the body slot (552), rows are 788 wide and a 20-wide lane shows at the
  right; else 808. The group is one non-wrapping ``FocusGroup`` clipped to the body slot
  (I-8; F16 conflict 4), so Down on the last row stays and the pointer never finds a row
  outside the slot.
- **Scrolling** (design §6.3): a row focused by keys scrolls just into view (a group's first
  row with its heading); the wheel scrolls 60 × text scale per notch anywhere in the slot,
  even over a slider; Page Up / Page Down scroll 552 − ``H_b`` and focus the first fully
  visible row; the lane works as F10's list scrollbar. The pointer never scrolls.
- **Text size**: the host lays out again when the text scale changes (``MenuScreen``); the
  page then recaptures the game menu's backdrop (in game only) and keeps the focused row in
  view. No motion and no timers of its own (UI-F16-05).
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Literal, Protocol

from engine.core.settings_schema import KEYS, IntKey, Value
from engine.render.frames import FrameSpec
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import (
    SCROLLBAR_LANE,
    SCROLLBAR_MIN_THUMB,
    button_height,
    slider_row_height,
)
from engine.ui.menus import EntryContext, MenuEntry, MenuPageBase
from engine.ui.nav import InputKind, Nav
from engine.ui.paint import HEADING_AREA
from engine.ui.widgets import SCROLL_RADIUS, SCROLL_TRACK, Button, Slider, Toggle, Widget, clipped

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.ui.menus import PageHost
    from engine.ui.paint import Painter
    from engine.ui.shell import GameShell

HEADING: Final = "settings"          # the [words] key of the heading and of the three entries
ROW_GAP: Final = 8
HEADING_GAP: Final = 16              # extra space above every heading but the first
BUTTON_INSET: Final = 32             # Reset / Delete progress: 400 wide at column x 32
BUTTON_WIDTH: Final = 400
WHEEL_STEP: Final = 60               # per notch, times the text scale
INSTANT: Final = 210                 # Text speed's right end: Instant (stored text_cps 0)
CPS_RANGE: Final = (10, 200)
SLIDER_STEPS: Final = {"text_size_pct": 10, "auto_scale_pct": 25, "master_volume": 5,
                       "music_volume": 5, "sound_volume": 5, "voice_volume": 5}
PERCENT_KEYS: Final = frozenset({"text_size_pct", "auto_scale_pct"})

Progress = Literal["hidden", "disabled", "enabled"]


class SettingsPort(Protocol):
    """What the page reads and changes (``SettingsService``, 04 §5.2)."""

    def value(self, key: str) -> Value: ...

    def is_default(self, key: str) -> bool: ...

    def set(self, key: str, value: Value) -> None: ...

    def reset(self) -> None: ...

    def locked(self, key: str) -> bool: ...

    def progress(self) -> Progress: ...

    def delete_progress(self) -> None: ...


# The column: (heading word, rows), each row (its [words] key, the setting it shows, kind).
RowKind = Literal["toggle", "slider", "button"]
GROUPS: Final[tuple[tuple[str, tuple[tuple[str, str, RowKind], ...]], ...]] = (
    ("settings_display", (("fullscreen", "fullscreen", "toggle"),
                          ("reduce_motion", "reduce_motion", "toggle"))),
    ("settings_text", (("text_speed", "text_cps", "slider"),
                       ("text_size", "text_size_pct", "slider"),
                       ("auto_wait", "auto_scale_pct", "slider"),
                       ("auto_voice", "auto_wait_voice", "toggle"),
                       ("skip_unread", "skip_all", "toggle"))),
    ("settings_sound", (("master_volume", "master_volume", "slider"),
                        ("music_volume", "music_volume", "slider"),
                        ("sound_volume", "sound_volume", "slider"),
                        ("voice_volume", "voice_volume", "slider"),
                        ("text_blips", "text_blips", "toggle"),
                        ("voice_sustain", "voice_sustain", "toggle"),
                        ("audio_unfocused", "audio_unfocused", "toggle"),
                        ("audio_minimized", "audio_minimized", "toggle"),
                        ("mono", "mono", "toggle"))),
    ("settings_data", (("settings_username", "username_use", "toggle"),      # F30
                       ("settings_crash_label", "crash_label", "toggle"),     # F30
                       ("reset_settings", "", "button"),
                       ("delete_progress", "", "button"))),
)


# F30 (04 §6.7): rows shown only when the port's ``row_shown`` says so (hidden without it).
RULED_ROWS: Final = frozenset({"settings_username", "settings_crash_label"})


@dataclass
class _Item:
    """One heading (``widget`` None) or row of the column; ``y``/``h`` in content units.
    ``top`` is where the row is shown from when focused by keys: its heading's top for a
    group's first row, else its own."""

    word: str
    widget: Widget | None
    button: bool = False
    y: float = 0.0
    h: float = 0.0
    top: float = 0.0


class SettingsColumn:
    """The page's scrolling column (04 §7.4): the items, their content positions, the
    scroll, and the lane. Kept in this module until a second user moves it to ``ui/``."""

    def __init__(self, items: list[_Item], view: Box) -> None:
        self.items = items
        self.view = view
        self.scroll = 0.0
        self.content = 0.0
        self.width = view.w
        self.button_h = 0.0
        self._grab: tuple[float, float] | None = None      # (pointer y, scroll) at grab

    def lay_out(self, view: Box, button_h: float, slider_h: float) -> None:
        """Content positions at this text scale, then the boxes at the current scroll."""
        self.view = view
        self.button_h = button_h
        y = 0.0
        heading_top = 0.0
        first_row = False
        for index, item in enumerate(self.items):
            if item.widget is None:
                if index:
                    y += ROW_GAP + HEADING_GAP
                item.y, item.h, item.top = y, button_h, y
                heading_top, first_row = y, True
            else:
                y += ROW_GAP
                item.y = y
                item.h = slider_h if isinstance(item.widget, Slider) else button_h
                item.top = heading_top if first_row else y
                first_row = False
            y += item.h
        self.content = y
        self.width = view.w - SCROLLBAR_LANE if self.overflows() else view.w
        self.clamp()
        self.place()

    def overflows(self) -> bool:
        return self.content > self.view.h

    def max_scroll(self) -> float:
        return max(0.0, self.content - self.view.h)

    def clamp(self) -> None:
        self.scroll = min(self.max_scroll(), max(0.0, self.scroll))

    def place(self) -> None:
        """Every row's box at the current scroll (rows out of view keep real boxes)."""
        view = self.view
        for item in self.items:
            w = item.widget
            if w is None:
                continue
            x = view.x + (BUTTON_INSET if item.button else 0)
            width = BUTTON_WIDTH if item.button else self.width
            w.box = Box(x, view.y + item.y - self.scroll, width, item.h)

    def scroll_to(self, scroll: float) -> bool:
        """Scroll (clamped) and re-box; True when the scroll changed."""
        before = self.scroll
        self.scroll = scroll
        self.clamp()
        if self.scroll == before:
            return False
        self.place()
        return True

    def reveal(self, item: _Item) -> bool:
        """Scroll just enough to show ``[top, bottom)`` of ``item`` (heading included)."""
        top, bottom = item.top, item.y + item.h
        if top < self.scroll:
            return self.scroll_to(top)
        if bottom > self.scroll + self.view.h:
            return self.scroll_to(bottom - self.view.h)
        return False

    def page_step(self) -> float:
        return self.view.h - self.button_h

    def first_visible(self, can_focus: Callable[[Widget], bool]) -> Widget | None:
        """The first focusable row wholly inside the view."""
        end = self.scroll + self.view.h
        for item in self.items:
            w = item.widget
            if w is not None and item.y >= self.scroll and item.y + item.h <= end \
                    and can_focus(w):
                return w
        return None

    # -- the lane (F10's list scrollbar math) --

    def lane_box(self) -> Box | None:
        if not self.overflows():
            return None
        v = self.view
        return Box(v.right - SCROLLBAR_LANE, v.y, SCROLLBAR_LANE, v.h)

    def thumb_box(self) -> Box | None:
        lane = self.lane_box()
        if lane is None:
            return None
        track = self.view.h
        height = min(track, max(SCROLLBAR_MIN_THUMB, track * track / self.content))
        top = 0.0 if self.max_scroll() == 0 else self.scroll / self.max_scroll() * (track - height)
        return Box(lane.x, lane.y + top, lane.w, height)

    def press(self, pos: tuple[float, float]) -> bool:
        """A press in the lane: above or below the thumb pages, on it grabs it."""
        self._grab = None
        lane, thumb = self.lane_box(), self.thumb_box()
        if lane is None or thumb is None or not lane.contains(pos):
            return False
        if pos[1] < thumb.y:
            self.scroll_to(self.scroll - self.page_step())
        elif pos[1] >= thumb.bottom:
            self.scroll_to(self.scroll + self.page_step())
        else:
            self._grab = (pos[1], self.scroll)
        return True

    def drag(self, pos: tuple[float, float]) -> bool:
        if self._grab is None:
            return False
        thumb = self.thumb_box()
        free = self.view.h - (thumb.h if thumb is not None else 0)
        if free <= 0:
            return False
        grab_y, grab_scroll = self._grab
        self.scroll_to(grab_scroll + (pos[1] - grab_y) / free * self.max_scroll())
        return True

    def release(self) -> None:
        self._grab = None


class SettingsPage(MenuPageBase):
    """The ``settings`` page (``MenuPage``). ``title``: opened from the title, so the Data
    group also shows Delete progress."""

    heading = HEADING

    def __init__(self, host: "PageHost", port: SettingsPort, *, title: bool) -> None:
        self.host = host
        self.port = port
        self.title = title
        self.widgets: dict[str, Widget] = {}
        items: list[_Item] = []
        for heading, rows in GROUPS:
            items.append(_Item(heading, None))
            for word, key, kind in rows:
                if word == "delete_progress" and not title:
                    continue
                row_shown = getattr(port, "row_shown", None)            # F30 (04 §6.7)
                if not (row_shown(word) if row_shown is not None else word not in RULED_ROWS):
                    continue
                widget = self._widget(word, key, kind)
                self.widgets[word] = widget
                items.append(_Item(word, widget, button=kind == "button"))
        self.column = SettingsColumn(items, Box(0, 0, 0, 0))
        self._built_scale: float | None = None
        self._seen: Widget | None = None

    # -- widgets --

    def _word(self, key: str) -> Callable[[], str]:
        words = self.host.shell.words
        return lambda: words.get(key)

    def _state_word(self, on: bool) -> str:
        return self.host.shell.words.get("on" if on else "off")

    def _widget(self, word: str, key: str, kind: RowKind) -> Widget:
        port = self.port
        label = self._word(word)
        if word == "settings_username":         # F30: on is 2 (allowed); off stores 1
            return Toggle(label, lambda: port.value(key) == 2,
                          lambda on: port.set(key, 2 if on else 1),
                          state_word=self._state_word)
        if word == "reduce_motion":
            return Toggle(label, self._reduce_shown, lambda on: port.set(key, on),
                          enabled=lambda: not port.locked(key), state_word=self._state_word)
        if kind == "toggle":
            return Toggle(label, lambda: bool(port.value(key)), lambda on: port.set(key, on),
                          state_word=self._state_word)
        if word == "text_speed":
            return Slider(label, CPS_RANGE[0], INSTANT, self._speed, self._set_speed,
                          step=10, value_text=self._speed_text)
        if kind == "slider":
            spec = KEYS[key]
            assert isinstance(spec, IntKey)
            text = (lambda v: f"{v}%") if key in PERCENT_KEYS else str
            return Slider(label, spec.lo, spec.hi, lambda: int(port.value(key)),  # type: ignore
                          lambda v: port.set(key, v), step=SLIDER_STEPS[key], value_text=text)
        if word == "reset_settings":
            return Button(label, lambda: self._ask("confirm_reset_settings", port.reset))
        return Button(label, lambda: self._ask("confirm_delete_progress", port.delete_progress),
                      enabled=lambda: port.progress() == "enabled")

    def _reduce_shown(self) -> bool:
        """The effective flag: ``[effects] reduce`` (locked on) OR the player's value."""
        port = self.port
        return port.locked("reduce_motion") or bool(port.value("reduce_motion"))

    def _speed(self) -> int:
        cps = self.port.value("text_cps")
        assert type(cps) is int
        return INSTANT if cps == 0 else min(CPS_RANGE[1], max(CPS_RANGE[0], cps))

    def _set_speed(self, v: int) -> None:
        self.port.set("text_cps", 0 if v > CPS_RANGE[1] else v)

    def _speed_text(self, v: int) -> str:
        return self.host.shell.words.get("text_instant") if v > CPS_RANGE[1] else str(v)

    def _ask(self, message: str, on_yes: Callable[[], None]) -> None:
        """F10's Yes/No dialog, No focused; focus returns to the button after."""
        shell = self.host.shell
        by = getattr(self.host, "input_kind", None)
        shell.confirm(shell.words.get(message), on_yes,
                      by=by if isinstance(by, InputKind) else InputKind.KEYS)

    # -- MenuPage --

    def build(self, host: "PageHost", body: Box) -> list[FocusGroup]:
        self.host = host
        cfg = host.shell.theme.cfg
        scale = host.painter.text_scale()
        size = cfg.panel.text_size
        column = self.column
        column.lay_out(body, button_height(size, scale=scale, minimum=cfg.button.height),
                       slider_row_height(size, scale=scale))
        rescaled = self._built_scale is not None and scale != self._built_scale
        self._built_scale = scale
        if rescaled:
            self._rescaled()
        rows = [item.widget for item in column.items if item.widget is not None]
        return [FocusGroup(rows, clip=body)]

    def _rescaled(self) -> None:
        """Text size changed: the game menu's backdrop is captured again (in game only;
        the line under it keeps its size) and the focused row stays in view."""
        from engine.ui.shell import Mode                   # lazily: shell imports the menus

        shell = self.host.shell
        if getattr(shell, "mode", None) is Mode.GAME:
            menu = shell.game_menu()
            if menu is not None:
                menu.refresh_backdrop()
        focused = self.host.scope.focused
        item = self._item_of(focused)
        if item is not None:
            self.column.reveal(item)

    def default_widget(self) -> Widget | None:
        return self.widgets["fullscreen"]

    def update(self, dt: float) -> None:
        """A row newly focused by keys scrolls just into view (the pointer never scrolls)."""
        scope = self.host.scope
        focused = scope.focused
        if focused is self._seen:
            return
        self._seen = focused
        item = self._item_of(focused)
        if item is not None and scope.source is InputKind.KEYS and self.column.reveal(item):
            self._moved()

    def on_nav(self, d: Nav) -> bool:
        """Page Up / Page Down: scroll 552 − ``H_b`` and focus the first fully visible row."""
        if d not in (Nav.PAGE_UP, Nav.PAGE_DOWN):
            return False
        column = self.column
        step = column.page_step()
        if column.scroll_to(column.scroll + (step if d is Nav.PAGE_DOWN else -step)):
            self._moved()
        scope = self.host.scope
        target = column.first_visible(scope.can_focus)
        if target is not None:
            scope.focus(target, InputKind.KEYS)
            self._seen = target                          # already in view: no reveal
        return True

    def on_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        """The wheel anywhere in the slot (60 × text scale per notch, never a value), and
        the lane: presses page or grab the thumb, which drags."""
        column = self.column
        if kind == "wheel":
            step = WHEEL_STEP * self.host.painter.text_scale()
            moved = column.scroll_to(column.scroll - notches * step)
        elif kind == "down":
            before = column.scroll
            if not column.press(pos):
                return False
            moved = column.scroll != before
        elif kind == "drag":
            before = column.scroll
            if not column.drag(pos):
                return False
            moved = column.scroll != before
        elif kind == "up":
            column.release()
            return True
        else:
            return False
        if moved:
            self._moved()
        return True

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        """The headings in view and the lane; the rows are the host's scope widgets, drawn
        clipped to the body slot (``FocusGroup.clip``)."""
        column = self.column
        view = column.view
        panel = p.style("panel")
        heading = p.style(HEADING_AREA)
        font = replace(heading.font, size=p.scaled_size(panel.font.size))
        words = self.host.shell.words
        end = column.scroll + view.h
        with clipped(p, view):
            for item in column.items:
                if item.widget is not None or item.y + item.h <= column.scroll or item.y >= end:
                    continue
                cy = view.y + item.y - column.scroll + item.h / 2
                canvas.draw_text(words.get(item.word), font, heading.text_color,
                                 (view.x, cy), anchor="midleft")
            lane, thumb = column.lane_box(), column.thumb_box()
            if lane is not None and thumb is not None:
                style = p.style("list", "normal")
                x = lane.x + (lane.w - SCROLL_TRACK) / 2
                p.shape(Box(x, lane.y, SCROLL_TRACK, lane.h),
                        FrameSpec(style.color("scrollbar_track"), 1.0,
                                  corner_radius=SCROLL_RADIUS))
                p.shape(Box(x, thumb.y, SCROLL_TRACK, thumb.h),
                        FrameSpec(style.color("scrollbar"), 1.0, corner_radius=SCROLL_RADIUS))

    # -- helpers --

    def _item_of(self, w: Widget | None) -> _Item | None:
        if w is None:
            return None
        return next((item for item in self.column.items if item.widget is w), None)

    def _moved(self) -> None:
        """The column scrolled: a fading host composes its layer again."""
        host = self.host
        if hasattr(host, "revision"):
            host.revision += 1                          # type: ignore[attr-defined]


# --- Entries ------------------------------------------------------------------------------------

def open_settings_from_quick(shell: "GameShell", by: InputKind) -> None:
    """The quick menu's Settings (04 OQ-7): the game menu opens with this page open; by the
    mouse nothing is focused, by keys the page's first row. Back returns to the sidebar.
    With a menu already open (or not in game) nothing happens."""
    if shell.game_menu() is not None:
        return
    shell.open_game_menu(by)
    menu = shell.game_menu()
    if menu is None:
        return
    if not any(e.id == HEADING and e.page is not None for e in menu.entries):
        return                                            # hidden from the game menu (F32)
    menu.open_page(HEADING)
    page = menu.page
    if by is InputKind.KEYS and page is not None:
        target = page.default_widget()
        if menu.scope.can_focus(target):
            assert target is not None
            menu.scope.focus(target, by, sound=False)


def register_settings(shell: "GameShell", port: SettingsPort) -> None:
    """The three ``settings`` entries: the title's page (through ``open_title_page``, with
    Delete progress), the game menu's page, and the quick menu's entry."""
    shell.menus.add("title", MenuEntry(HEADING, page=lambda host: SettingsPage(
        host, port, title=True)))
    shell.menus.add("game", MenuEntry(HEADING, page=lambda host: SettingsPage(
        host, port, title=False)))
    shell.menus.add("quick", MenuEntry(HEADING, action=_quick))


def _quick(ctx: EntryContext) -> None:
    open_settings_from_quick(ctx.shell, ctx.by)


__all__ = ["GROUPS", "INSTANT", "RULED_ROWS", "SettingsColumn", "SettingsPage", "SettingsPort",
           "open_settings_from_quick", "register_settings"]

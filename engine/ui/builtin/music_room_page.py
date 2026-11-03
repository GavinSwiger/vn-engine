"""``MusicRoomPage``: the Extras screen's Music Room (F35 ``SPEC.md`` §2 PR-F35-03 to 05, 08;
§5.3).

Why this module exists: the player listens again to the game's soundtrack from the title.
The page lists every declared track in declaration order (a closed one as ``???``, never
focused) and plays the picked one on the music stream with Previous, Play/Pause, Next and
a Play all / Repeat track mode. It reads the story only through a ``MusicRoomPort``
(``app/musicroom.py``'s, F35 step 2), so ``ui`` never imports ``script``, ``runtime`` or
``audio``, and it tests with fakes.

- **Player** (``RoomPlayer``, pure): picking a row plays it from the start (``play(start=0)``,
  so the same track starts again); a switch fades the playing track (the title music at
  first) over ``SWITCH_FADE_S``. Pause keeps ``position()`` and stops over ``PAUSE_FADE_S``;
  resume plays from that point with a ``PAUSE_FADE_S`` fade-in. Previous / Next go to the
  nearest open track, wrapping. *Play all* plays with ``loop=False``: ``position()`` turning
  None after a start is the end, and the next open track plays (one open track: it plays
  again). *Repeat track* plays with ``loop=True``. Switching the mode doesn't touch what
  plays: a once track ending in Repeat mode starts again (looping from then on), and a
  looping track wrapping in Play all mode counts as its end. A track that plays less than
  ``SHORT_PLAY_S`` (missing, unreadable, no audio device) counts toward a stop: after more
  such ends in a row than there are open tracks, the room goes quiet (bar at 0:00) until
  the player acts, so a room of missing files never spins.
- **Volume**: the stream's level is the player's Music (and Master) volume (F08's music
  gain); the page has no slider and plays at relative volume 100.
- **Hand-off**: the port's ``handle()`` is the title's music handle (step 2). ``closed()``
  (Back, another Extras entry, the menu closing) fades the room's track out over
  ``[audio] music_fadeout`` (``stop(None)``) when the room played one, then calls the port's
  ``leave()``. A released (inert) handle or None (no audio) is fine everywhere.
- **Layout** (``music_room_layout``, pure; §5.3 at 100 % text in F10's body slot): the list
  (416, 112, 808×360) with rows ``list_row_height`` high (48; taller at F16's larger text),
  the number 16 and the title 72 inside the row (cut with "…"); the now-playing title or
  ``music_pick`` (24) at y 504; the progress bar (416, 548, 640×8, radius 4) with the time
  right-aligned at x 1224 (20): ``1:12 / 2:41``, or ``1:12`` with no length; four 188×56
  buttons 16 apart at y 584. The rows below the list are laid out from the slot's bottom,
  so at 150 % text the taller buttons and lines push the list's bottom up.
- **Input**: Up/Down in the list (closed rows skipped), Down from the last row to
  Play/Pause, Left/Right among the buttons; Enter or a click on a row plays it; Page Up /
  Page Down and the gamepad shoulders (``nav_extras``) are Previous / Next; the wheel
  scrolls the list. No seek bar, no shuffle. Only the bar moves, so reduced motion changes
  nothing.

Frame cost: one ``position()`` and one ``length()`` read per ``update``; ``draw`` uses them.

Theme (existing tokens): ``list.*`` (rows, dividers, scrollbar), ``button.*`` (buttons, row
text), ``button.marker.fill_color`` (the playing row's 6-wide bar), ``button.disabled.
text_color`` (closed rows), ``panel.text_color`` (now playing, time), ``slider.track_color``
/ ``slider.fill_color`` (the bar). Words: ``music_room`` (the heading), ``music_play``,
``music_pause``, ``music_previous``, ``music_next``, ``music_play_all``,
``music_repeat_one``, ``music_locked``, ``music_pick`` (``WORD_DEFAULTS`` until step 2 adds
them to ``[words]``).
"""

from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from engine.render.frames import FrameSpec
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import (
    BUTTON_HEIGHT,
    BUTTON_TEXT_SIZE,
    LIST_ROW_HEIGHT,
    PAGE_BODY,
    PANEL_TEXT_SIZE,
    button_height,
    cut_to_width,
    list_row_height,
    pitch,
    scaled,
)
from engine.ui.menus import MenuPageBase
from engine.ui.nav import InputKind, Nav
from engine.ui.theme import measure_with
from engine.ui.widgets import DIVIDER, Button, ListRow, Look, ScrollList

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.ui.focus import FocusScope
    from engine.ui.menus import PageHost
    from engine.ui.paint import Painter
    from engine.ui.theme import UiTheme, Words
    from engine.ui.widgets import Widget

HEADING: Final = "music_room"
WORD_DEFAULTS: Final[dict[str, str]] = {
    "music_room": "Music Room", "music_play": "Play", "music_pause": "Pause",
    "music_previous": "Previous", "music_next": "Next", "music_play_all": "Play all",
    "music_repeat_one": "Repeat track", "music_locked": "???",
    "music_pick": "Pick a track to play.",
}

# Playback (module docstring).
SWITCH_FADE_S: Final = 0.2            # a pick, Previous, Next: the playing track fades out
PAUSE_FADE_S: Final = 0.2             # pause fades out, resume fades in (§5.3)
SETTLE_SLACK_S: Final = 0.1           # after a switch's fade, position() is the new track's
SHORT_PLAY_S: Final = 1.0             # a track ending sooner counts toward the quiet stop
WRAP_S: Final = 0.5                   # a looping track's position falling this far: a pass end

# Layout (§5.3), canvas units at 100 % text.
NUMBER_X: Final = 16                  # a row's number, from the row's left
TITLE_X: Final = 72                   # a row's title
TITLE_RIGHT: Final = 16               # the title is cut this far inside the row's right
MARKER_W: Final = 6                   # the playing row's bar
NOW_SIZE: Final = 24                  # the now-playing line's text size
TIME_SIZE: Final = 20                 # the time's text size
BAR: Final = (640, 8)
BAR_RADIUS: Final = 4
BUTTON_W: Final = 188
BUTTON_GAP: Final = 16
BUTTONS_BOTTOM_GAP: Final = 24        # the buttons end this far above the slot's bottom
BAR_ABOVE_BUTTONS: Final = 36         # the bar's top is this far above the buttons' top
NOW_ABOVE_BAR: Final = 10             # the now-playing line ends this far above the bar
LIST_ABOVE_NOW: Final = 32            # the list ends this far above the now-playing line
CUT_CACHE: Final = 512                # cut titles kept (text, width, size, bold)


# --- Seams ---------------------------------------------------------------------------------------

class TrackLike(Protocol):
    """A track as the port gives it (``runtime/musicroom.py``'s ``TrackInfo`` fits)."""

    @property
    def name(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def file(self) -> str: ...


class MusicHandleLike(Protocol):
    """What the page uses of F08's ``MusicHandle`` (inert once released: every call does
    nothing and the reads give None)."""

    def play(self, file: str, *, loop: bool = True, fadein: float = 0.0,
             fadeout: float = 0.5, volume: int = 100,
             start: float | None = None) -> None: ...

    def stop(self, fadeout: float | None = 0.5) -> None: ...

    def position(self) -> float | None: ...

    def length(self) -> float | None: ...


class MusicRoomPort(Protocol):
    """What the page reads (§5.1): every declared track in declaration order, whether one
    is open, the music handle (None: no audio), and ``leave()`` (the title music returns)."""

    def tracks(self) -> Sequence[TrackLike]: ...

    def is_open(self, name: str) -> bool: ...

    def handle(self) -> MusicHandleLike | None: ...

    def leave(self) -> None: ...


class MusicRoomUi(Protocol):
    """What the page draws with (``GameShell`` has all three)."""

    theme: "UiTheme"
    words: "Words"
    assets: Any


def word(words: "Words", key: str) -> str:
    """``words.get(key)``, or ``WORD_DEFAULTS[key]`` before ``[words]`` has it."""
    try:
        return words.get(key)
    except KeyError:
        return WORD_DEFAULTS[key]


def time_text(position: float, length: float | None) -> str:
    """``m:ss / m:ss``, or ``m:ss`` with no length (whole seconds, rounded down)."""
    def mss(seconds: float) -> str:
        whole = max(0, int(seconds))
        return f"{whole // 60}:{whole % 60:02d}"
    return mss(position) if length is None else f"{mss(position)} / {mss(length)}"


# --- The player ---------------------------------------------------------------------------------

class RoomPlayer:
    """The room's playback over a ``MusicRoomPort`` (module docstring "Player"). Indices
    are into ``port.tracks()``."""

    def __init__(self, port: MusicRoomPort) -> None:
        self.port = port
        self.current: int | None = None       # the track playing, paused, or quiet
        self.paused = False
        self.quiet = False                    # stopped after short plays (module docstring)
        self.repeat = False                   # False: Play all; True: Repeat track
        self.played = False                   # the room played a track since it opened
        self.shown = 0.0                      # the position drawn this frame
        self.shown_length: float | None = None
        self._from = 0.0                      # the offset the current start began at
        self._reach = 0.0                     # the furthest position seen since that start
        self._last: float | None = None       # last frame's position (wrap check)
        self._settle = 0.0                    # seconds until position() is the new track's
        self._short = 0                       # short ends in a row

    # -- reads --

    def tracks(self) -> Sequence[TrackLike]:
        return self.port.tracks()

    def open_indices(self) -> list[int]:
        is_open = self.port.is_open
        return [i for i, t in enumerate(self.tracks()) if is_open(t.name)]

    def any_open(self) -> bool:
        is_open = self.port.is_open
        return any(is_open(t.name) for t in self.tracks())

    @property
    def playing(self) -> bool:
        return self.current is not None and not self.paused and not self.quiet

    # -- actions --

    def pick(self, index: int) -> bool:
        """Play track ``index`` from the start (False: not an open track)."""
        tracks = self.tracks()
        if not 0 <= index < len(tracks) or not self.port.is_open(tracks[index].name):
            return False
        self._short = 0
        self._start(index, 0.0)
        return True

    def toggle(self) -> None:
        """Play/Pause: pause, resume, start the quiet track again, or (nothing picked) play
        the first open track."""
        if self.current is None or not self._is_open(self.current):
            found = self.open_indices()
            if found:
                self.pick(found[0])
            return
        if self.quiet:
            self.pick(self.current)
        elif self.paused:
            self._short = 0
            self._start(self.current, self.shown, fadein=PAUSE_FADE_S, fadeout=0.0)
        else:
            self.shown = self._position_now()
            self.paused = True
            handle = self.port.handle()
            if handle is not None:
                handle.stop(PAUSE_FADE_S)

    def next(self) -> bool:
        return self._step(1)

    def previous(self) -> bool:
        return self._step(-1)

    def toggle_mode(self) -> None:
        """Play all ↔ Repeat track; what plays goes on (module docstring)."""
        self.repeat = not self.repeat

    def leave(self) -> None:
        """The page closed: the room's track fades over ``music_fadeout`` (when it played
        one); the state starts afresh."""
        if self.played:
            handle = self.port.handle()
            if handle is not None:
                handle.stop(None)
        self.current = None
        self.paused = self.quiet = self.played = False
        self.shown, self.shown_length = 0.0, None
        self._settle = 0.0
        self._short = 0

    # -- frames --

    def update(self, dt: float) -> None:
        """One ``position()`` read: the shown time, and the end of a track."""
        if self.current is None or self.paused or self.quiet:
            return
        handle = self.port.handle()
        if handle is None:
            self.shown, self.shown_length = self._from, None
            return
        if self._settle > 0.0:
            self._settle = max(0.0, self._settle - dt)
            if self._settle > 0.0:
                return                         # the switch's fade: still the old track
        position = handle.position()
        if position is None:
            self._ended()
            return
        last = self._last
        if not self.repeat and last is not None and position < last - WRAP_S:
            self._ended()                                  # a looping track's pass ended
            return
        self._last = position
        self._reach = max(self._reach, position)
        self.shown = position
        self.shown_length = handle.length()

    def _position_now(self) -> float:
        if self._settle > 0.0:
            return self._from
        handle = self.port.handle()
        position = handle.position() if handle is not None else None
        return self.shown if position is None else position

    # -- internals --

    def _is_open(self, index: int) -> bool:
        tracks = self.tracks()
        return 0 <= index < len(tracks) and self.port.is_open(tracks[index].name)

    def _step(self, step: int) -> bool:
        found = self.open_indices()
        if not found:
            return False
        cur = self.current
        if cur is None:
            target = found[0] if step > 0 else found[-1]
        else:
            later = [i for i in found if (i - cur) * step > 0]
            target = (min(later, key=lambda i: abs(i - cur)) if later
                      else (found[0] if step > 0 else found[-1]))
        return self.pick(target)

    def _start(self, index: int, start: float, *, fadein: float = 0.0,
               fadeout: float = SWITCH_FADE_S) -> None:
        tracks = self.tracks()
        self.current = index
        self.paused = self.quiet = False
        self.played = True
        self._from = self._reach = self.shown = start
        self._last = None
        handle = self.port.handle()
        self.shown_length = None
        if handle is None:
            return
        handle.play(tracks[index].file, loop=self.repeat, fadein=fadein, fadeout=fadeout,
                    start=start)
        self._settle = fadeout + SETTLE_SLACK_S

    def _ended(self) -> None:
        """The current track ended (or never played): Repeat plays it again, Play all the
        next open track; too many short plays in a row and the room goes quiet."""
        assert self.current is not None
        self._short = self._short + 1 if self._reach - self._from < SHORT_PLAY_S else 0
        found = self.open_indices()
        if not found or self._short > len(found):
            self.quiet = True
            self.shown, self.shown_length = 0.0, None
            return
        cur = self.current
        if self.repeat and cur in found:
            target = cur
        else:
            later = [i for i in found if i > cur]
            target = later[0] if later else found[0]
        self._start(target, 0.0, fadeout=0.0)


# --- Layout --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class MusicRoomLayout:
    """``music_room_layout``'s boxes (canvas units)."""

    list: Box
    row_height: int
    now_playing: Box                  # one line of ``now_size`` text
    now_size: int
    bar: Box
    time_right: float                 # the time's right edge (centred on the bar)
    time_size: int
    buttons: tuple[Box, Box, Box, Box]  # Previous, Play/Pause, Next, mode


def music_room_layout(body: Box = PAGE_BODY, text_scale: float = 1.0, *,
                      row_min: int = LIST_ROW_HEIGHT, row_text_size: int = PANEL_TEXT_SIZE,
                      button_text_size: int = BUTTON_TEXT_SIZE,
                      button_min: int = BUTTON_HEIGHT) -> MusicRoomLayout:
    """§5.3 (pure). From the slot's bottom: the buttons (H_b tall, 24 above it), the bar 36
    above them, the now-playing line 10 above the bar, the list down to 32 above that."""
    h_b = button_height(button_text_size, scale=text_scale, minimum=button_min)
    top = body.bottom - BUTTONS_BOTTOM_GAP - h_b
    buttons = tuple(Box(body.x + i * (BUTTON_W + BUTTON_GAP), top, BUTTON_W, h_b)
                    for i in range(4))
    bar = Box(body.x, top - BAR_ABOVE_BUTTONS, *BAR)
    now_size = scaled(NOW_SIZE, text_scale)
    now_h = pitch(now_size)
    now = Box(body.x, bar.y - NOW_ABOVE_BAR - now_h, body.w, now_h)
    lst = Box(body.x, body.y, body.w, max(0.0, now.y - LIST_ABOVE_NOW - body.y))
    return MusicRoomLayout(lst, list_row_height(row_text_size, scale=text_scale,
                                                minimum=row_min),
                           now, now_size, bar, body.right, scaled(TIME_SIZE, text_scale),
                           buttons)  # type: ignore[arg-type]


# --- Widgets -------------------------------------------------------------------------------------

class _TrackList(ScrollList):
    """The track rows: closed rows are disabled (never focused); Page keys are left to the
    page (Previous / Next); Down from the last open row goes to Play/Pause."""

    def __init__(self, page: "MusicRoomPage") -> None:
        self.page = page
        super().__init__(lambda: page.rows, page._row_activated, draw_row=page._draw_row,
                         enabled=lambda: any(row.enabled for row in page.rows))

    def on_nav(self, d: Nav) -> bool:
        if d in (Nav.PAGE_UP, Nav.PAGE_DOWN):
            return False
        used = super().on_nav(d)
        if not used and d is Nav.DOWN:
            return self.page._focus(self.page.play_button)
        return used


# --- The page ------------------------------------------------------------------------------------

class MusicRoomPage(MenuPageBase):
    """The ``music_room`` page of the Extras screen (module docstring). ``ui`` (default: the
    host's shell) gives the theme, words and assets."""

    heading = HEADING
    nav_extras = frozenset({"shoulders"})

    def __init__(self, port: MusicRoomPort, *, ui: MusicRoomUi | None = None) -> None:
        self.port = port
        self.ui = ui
        self.player = RoomPlayer(port)
        self.host: "PageHost | None" = None
        self.scope: "Callable[[], FocusScope | None]" = lambda: None
        self.layout = music_room_layout()
        self.scale = 1.0
        self.rows: list[ListRow] = []
        self._cuts: OrderedDict[tuple, str] = OrderedDict()
        self.list = _TrackList(self)
        enabled = self.player.any_open
        self.previous_button = Button(lambda: self._word("music_previous"), self.player.previous,
                                      enabled=enabled)
        self.play_button = Button(
            lambda: self._word("music_pause" if self.player.playing else "music_play"),
            self.player.toggle, enabled=enabled)
        self.next_button = Button(lambda: self._word("music_next"), self.player.next,
                                  enabled=enabled)
        self.mode_button = Button(
            lambda: self._word("music_repeat_one" if self.player.repeat else "music_play_all"),
            self.player.toggle_mode, enabled=enabled)

    @property
    def buttons(self) -> tuple[Button, Button, Button, Button]:
        return self.previous_button, self.play_button, self.next_button, self.mode_button

    # -- MenuPage --

    def build(self, host: "PageHost", body: Box) -> list[FocusGroup]:
        self.host = host
        if self.ui is None:
            self.ui = host.shell
        self.scope = lambda: host.scope
        self.port.handle()                       # opening the page takes the music (step 2)
        return self.lay_out(body, host.painter.text_scale())

    def lay_out(self, body: Box, text_scale: float) -> list[FocusGroup]:
        """Place the widgets in ``body`` at ``text_scale``; the focus groups."""
        assert self.ui is not None
        self.scale = text_scale
        cfg = self.ui.theme.cfg
        layout = self.layout = music_room_layout(
            body, text_scale, row_min=cfg.list.row_height, row_text_size=cfg.button.text_size,
            button_text_size=cfg.button.text_size, button_min=cfg.button.height)
        self._refresh_rows()
        lst = self.list
        lst.box = layout.list
        lst.row_height = layout.row_height
        cur = self.player.current
        start = cur if cur is not None and self._row_open(cur) else next(
            (i for i, row in enumerate(self.rows) if row.enabled), 0)
        lst.focus_index(start)
        for button, box in zip(self.buttons, layout.buttons):
            button.box = box
        return [FocusGroup([lst]), FocusGroup(list(self.buttons))]

    def update(self, dt: float) -> None:
        self._refresh_rows()
        self.player.update(dt)

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        """The now-playing line, the bar, and the time (the host draws the widgets)."""
        ui = self.ui
        if ui is None:
            return
        cfg = ui.theme.cfg
        layout = self.layout
        player = self.player
        tracks = player.tracks()
        cur = player.current
        title = (tracks[cur].title if cur is not None and 0 <= cur < len(tracks)
                 else self._word("music_pick"))
        font = ui.theme.font(layout.now_size)
        text = self._cut(title, layout.now_playing.w, layout.now_size, False)
        canvas.draw_text(text, font, cfg.panel.text_color,
                         (layout.now_playing.x, layout.now_playing.y))
        bar = layout.bar
        p.shape(bar, FrameSpec(tuple(cfg.slider.track_color), 1.0,  # type: ignore[arg-type]
                               corner_radius=BAR_RADIUS))
        fill = self.bar_fill()
        if fill > 0.0:
            p.shape(Box(bar.x, bar.y, max(1.0, round(bar.w * fill)), bar.h),
                    FrameSpec(tuple(cfg.slider.fill_color), 1.0,  # type: ignore[arg-type]
                              corner_radius=BAR_RADIUS))
        if cur is not None:
            canvas.draw_text(self.time(), ui.theme.font(layout.time_size), cfg.panel.text_color,
                             (layout.time_right, bar.y + bar.h / 2), anchor="midright")

    def closed(self) -> None:
        self.player.leave()
        self.port.leave()

    def on_nav(self, d: Nav) -> bool:
        if d is Nav.PAGE_UP:
            self.player.previous()
            return True
        if d is Nav.PAGE_DOWN:
            self.player.next()
            return True
        return False

    def default_widget(self) -> "Widget | None":
        if self.list.enabled():
            return self.list
        return None

    # -- reads (tests and draw) --

    def time(self) -> str:
        """The time as drawn: ``m:ss / m:ss`` or ``m:ss``."""
        return time_text(self.player.shown, self.player.shown_length)

    def bar_fill(self) -> float:
        """The bar's filled share, 0–1 (0 without a length)."""
        length = self.player.shown_length
        if self.player.current is None or not length or length <= 0:
            return 0.0
        return min(1.0, max(0.0, self.player.shown / length))

    def row_texts(self, index: int) -> tuple[str, str]:
        """Row ``index``'s number and title as drawn: ``music_locked`` for a closed one, else
        the title cut with "…" to the row's width − 88 (bold for the playing row)."""
        if not self._row_open(index):
            return str(index + 1), self._word("music_locked")
        title = self.player.tracks()[index].title
        assert self.ui is not None
        size = scaled(self.ui.theme.cfg.button.text_size, self.scale)
        width = self.list.rows_width() - TITLE_X - TITLE_RIGHT
        return str(index + 1), self._cut(title, width, size, index == self.player.current)

    # -- internals --

    def _word(self, key: str) -> str:
        return word(self.ui.words, key) if self.ui is not None else WORD_DEFAULTS[key]

    def _refresh_rows(self) -> None:
        is_open = self.port.is_open
        rows = [ListRow(t.title, bool(is_open(t.name))) for t in self.port.tracks()]
        if rows != self.rows:
            self.rows = rows

    def _row_open(self, index: int) -> bool:
        return 0 <= index < len(self.rows) and self.rows[index].enabled

    def _row_activated(self, index: int) -> None:
        self.player.pick(index)

    def _focus(self, widget: "Widget") -> bool:
        scope = self.scope()
        return scope is not None and scope.focus(widget, InputKind.KEYS)

    def _cut(self, text: str, width: float, size: int, bold: bool) -> str:
        key = (text, round(width, 3), size, bold)
        found = self._cuts.get(key)
        if found is not None:
            self._cuts.move_to_end(key)
            return found
        assert self.ui is not None
        found = cut_to_width(text, max(1.0, width), size,
                             measure_with(self.ui.assets, self.ui.theme.font(size, bold=bold)))
        self._cuts[key] = found
        if len(self._cuts) > CUT_CACHE:
            self._cuts.popitem(last=False)
        return found

    def _draw_row(self, p: "Painter", index: int, box: Box, look: Look) -> None:
        ui = self.ui
        if ui is None or not 0 <= index < len(self.rows):
            return
        cfg = ui.theme.cfg
        canvas = p.canvas
        cy = box.y + box.h / 2
        size = scaled(cfg.button.text_size, self.scale)
        number, title = self.row_texts(index)
        if not self.rows[index].enabled:
            color = tuple(cfg.button.disabled.text_color)
            font = ui.theme.font(size)
            canvas.draw_text(number, font, color, (box.x + NUMBER_X, cy), anchor="midleft")
            canvas.draw_text(title, font, color, (box.x + TITLE_X, cy), anchor="midleft")
            return
        playing = index == self.player.current
        if playing:
            p.rect(Box(box.x, box.y, MARKER_W, box.h - DIVIDER),
                   tuple(cfg.button.marker.fill_color))  # type: ignore[arg-type]
        font = ui.theme.font(size, bold=playing)
        color = tuple(cfg.button.text_color)
        canvas.draw_text(number, ui.theme.font(size), color, (box.x + NUMBER_X, cy),
                         anchor="midleft")
        canvas.draw_text(title, font, color, (box.x + TITLE_X, cy), anchor="midleft")


__all__ = ["HEADING", "MusicHandleLike", "MusicRoomLayout", "MusicRoomPage", "MusicRoomPort",
           "MusicRoomUi", "RoomPlayer", "TrackLike", "WORD_DEFAULTS", "music_room_layout",
           "time_text", "word"]

"""``AchievementsPage``: the Extras screen's Achievements page (F37 ``SPEC.md`` §5.2,
PR-F37-05).

Why this module exists: the player sees every achievement of the game, which ones they have,
and how many: ``Unlocked: 3 / 12`` over a list in declaration order. The page reads the story
only through an ``AchievementsPort`` (F37-S2's ``app/achievements.py``; fakes in tests), so
``ui`` never imports ``script`` or ``persist``. Under F34's dev ``run --extras`` the port
reports every achievement as unlocked.

- **Model** (``achievements_model``): one row per achievement, in order. ``unlocked``: its
  title, description, and icon in ``text_color``. ``locked``: the same, the icon at 35%
  opacity and the text in ``button.disabled.text_color``. ``hidden`` (hidden and locked):
  ``achievement_hidden`` and ``achievement_hidden_text`` beside a 64×64 frame
  (``button.disabled.track_color``, radius 8) with a ``?``. No icon: the frame, filled
  ``button.marker.fill_color`` when unlocked. A hidden achievement once unlocked shows its
  real title and description. No dates.
- **Layout** (``achievements_layout``, body slot 416, 112, 808×552): the progress line at
  (416, 112), 24 tall; the list at (416, 152, 808×512). A row is ``max(104, d_y +
  pitch(d) + d + 6)`` tall, with ``t`` and ``d`` the title (24) and description (20) sizes at
  the text scale and ``d_y = 16 + pitch(t)`` the description's top (50 at 100%): 104 at
  100%, taller with the text size. Icon 64×64 at (x + 16, y + 20), scaled to fit, never up;
  the title bold at (x + 96, y + 16), cut with "…"; the description at (x + 96, y + d_y),
  at most 2 lines, then "…". Texts are 676 wide (the row minus the scrollbar lane, always
  kept free, and 16 on the right).
- **Input**: the list (F10's ``ScrollList`` with equal variable rows) takes focus only to
  scroll: Up/Down, Page Up/Down, Home/End, and the wheel. Activating a row does nothing. No
  motion.

Words (F37-S2 adds them to ``WordsConfig``; until then, and for a config without them, the
defaults in ``WORDS``): ``achievements`` (the heading), ``achievement_unlocked`` (the notice
``Achievement unlocked: <Title>``, ``unlocked_notice_text``), ``achievements_progress``,
``achievement_hidden``, ``achievement_hidden_text``.
"""

import dataclasses
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol

from engine.render.frames import FrameSpec
from engine.render.text import FontSpec
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import Measure, cut_to_width, fit_message, pitch, scaled
from engine.ui.menus import MenuPageBase
from engine.ui.nav import Nav
from engine.ui.notice import draw_fitted, fit_box
from engine.ui.paint import HEADING_AREA
from engine.ui.theme import measure_with
from engine.ui.widgets import ListRow, Look, ScrollList

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.ui.menus import PageHost
    from engine.ui.paint import Painter
    from engine.ui.widgets import Widget

RGB = tuple[int, int, int]
RowState = Literal["unlocked", "locked", "hidden"]

HEADING: Final = "achievements"
WORDS: Final[dict[str, str]] = {               # F37 §5.1's five words and their defaults
    "achievements": "Achievements",
    "achievement_unlocked": "Achievement unlocked",
    "achievements_progress": "Unlocked",
    "achievement_hidden": "Hidden achievement",
    "achievement_hidden_text": "Keep playing to unlock it.",
}

BODY: Final = Box(416, 112, 808, 552)
PROGRESS_H: Final = 24
LIST_TOP: Final = 40                    # the list starts 40 below the body (y 152)
ROW_MIN: Final = 104
ROW_PAD_BOTTOM: Final = 6
ICON: Final = 64
ICON_X: Final = 16
ICON_Y: Final = 20
ICON_RADIUS: Final = 8
TEXT_X: Final = 96
TITLE_Y: Final = 16
TITLE_SIZE: Final = 24
DESC_SIZE: Final = 20
DESC_LINES: Final = 2
SCROLL_LANE: Final = 20
TEXT_W: Final = BODY.w - SCROLL_LANE - TEXT_X - 16       # 676
LOCKED_OPACITY: Final = 0.35
HIDDEN_MARK: Final = "?"


# --- Words -----------------------------------------------------------------------------------

def word(words: object, key: str) -> str:
    """``words.get(key)``, or ``WORDS[key]`` while the config has no such word."""
    get = getattr(words, "get", None)
    if get is not None:
        try:
            found = get(key)
        except KeyError:
            found = None
        if type(found) is str:
            return found
    return WORDS[key]


def progress_text(words: object, unlocked: int, total: int) -> str:
    """``Unlocked: 3 / 12``."""
    return f"{word(words, 'achievements_progress')}: {unlocked} / {total}"


def unlocked_notice_text(words: object, title: str) -> str:
    """The notice ``Achievement unlocked: First Steps`` (F37-S2 shows it with the icon)."""
    return f"{word(words, 'achievement_unlocked')}: {title}"


# --- The port and the model ----------------------------------------------------------------------

class AchievementLike(Protocol):
    """An achievement as the port gives it (``runtime/achievements.AchievementInfo`` fits)."""

    name: str
    title: str
    description: str
    image: str | None
    hidden: bool


class AchievementsPort(Protocol):
    """What the page reads: every achievement in declaration order, the unlocked names (all
    of them under ``run --extras``), and an icon's source: a file ref, a solid colour, or
    None (no picture: the frame)."""

    def achievements(self) -> Sequence[AchievementLike]: ...

    def unlocked(self) -> Collection[str]: ...

    def icon(self, image: str) -> "str | RGB | None": ...


@dataclass(frozen=True)
class AchievementRow:
    """One row as shown: its state, the texts before fitting, and the icon's image name
    (None: the frame)."""

    name: str
    state: RowState
    title: str
    description: str
    image: str | None


@dataclass(frozen=True)
class AchievementsModel:
    rows: tuple[AchievementRow, ...]
    unlocked: int
    total: int


def achievements_model(port: AchievementsPort, words: object) -> AchievementsModel:
    """The module docstring's model."""
    held = set(port.unlocked())
    rows: list[AchievementRow] = []
    count = 0
    for item in port.achievements():
        if item.name in held:
            count += 1
            rows.append(AchievementRow(item.name, "unlocked", item.title, item.description,
                                       item.image))
        elif item.hidden:
            rows.append(AchievementRow(item.name, "hidden", word(words, "achievement_hidden"),
                                       word(words, "achievement_hidden_text"), None))
        else:
            rows.append(AchievementRow(item.name, "locked", item.title, item.description,
                                       item.image))
    return AchievementsModel(tuple(rows), count, len(rows))


# --- Layout ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class AchievementsLayout:
    progress: Box
    list: Box
    row_h: int
    title_size: int
    desc_size: int
    title_y: int
    desc_y: int


def achievements_layout(scale: float = 1.0, body: Box = BODY) -> AchievementsLayout:
    """The module docstring's layout at text scale ``scale``."""
    t = scaled(TITLE_SIZE, scale)
    d = scaled(DESC_SIZE, scale)
    desc_y = TITLE_Y + pitch(t)
    row_h = max(ROW_MIN, desc_y + (DESC_LINES - 1) * pitch(d) + d + ROW_PAD_BOTTOM)
    return AchievementsLayout(Box(body.x, body.y, body.w, PROGRESS_H),
                              Box(body.x, body.y + LIST_TOP, body.w, body.h - LIST_TOP),
                              row_h, t, d, TITLE_Y, desc_y)


@dataclass(frozen=True)
class FittedRow:
    title: str
    lines: tuple[str, ...]


def fit_row(row: AchievementRow, layout: AchievementsLayout, title_measure: Measure,
            desc_measure: Measure) -> FittedRow:
    """The title cut to ``TEXT_W`` with "…"; the description in at most 2 lines, then
    "…" ("" : no lines)."""
    title = cut_to_width(row.title, TEXT_W, layout.title_size, title_measure)
    lines: tuple[str, ...] = ()
    if row.description:
        lines = fit_message(row.description, TEXT_W, layout.desc_size, desc_measure,
                            max_lines=DESC_LINES, min_size=layout.desc_size).lines
    return FittedRow(title, lines)


# --- The page ----------------------------------------------------------------------------------

class AchievementsPage(MenuPageBase):
    """The ``achievements`` page of the Extras screen (module docstring). ``measures``:
    (title, description) ``Measure``s for tests (M20); by default the theme's fonts."""

    heading = HEADING

    def __init__(self, port: AchievementsPort, *,
                 measures: tuple[Measure, Measure] | None = None) -> None:
        self.port = port
        self.host: "PageHost | None" = None
        self.model = AchievementsModel((), 0, 0)
        self.layout = achievements_layout()
        self.fitted: list[FittedRow] = []
        self._measures = measures
        self._signature: frozenset[str] | None = None
        self._fonts: tuple[FontSpec, FontSpec] | None = None
        self._list_rows: list[ListRow] = []
        self.list = ScrollList(lambda: self._list_rows, self._activate,
                               heights=lambda _i: self.layout.row_h,
                               pitch=lambda: pitch(self.layout.desc_size),
                               draw_row=self._draw_row)

    # -- MenuPage --

    def build(self, host: "PageHost", body: Box) -> list[FocusGroup]:
        self.host = host
        p = host.painter
        self.layout = achievements_layout(p.text_scale(), body)
        self.list.box = self.layout.list
        title_font = p.style(HEADING_AREA).font
        desc_font = p.style("panel").font
        self._fonts = (dataclasses.replace(title_font, size=self.layout.title_size),
                       dataclasses.replace(desc_font, size=self.layout.desc_size))
        if self._measures is None:
            assets = host.shell.assets
            self._title_measure = measure_with(assets, title_font)
            self._desc_measure = measure_with(assets, desc_font)
        else:
            self._title_measure, self._desc_measure = self._measures
        self._refresh()
        return [FocusGroup([self.list], column=True)]

    def update(self, dt: float) -> None:
        if self.host is not None and frozenset(self.port.unlocked()) != self._signature:
            self._refresh()

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        """The progress line (the list is a scope widget, drawn by the menu)."""
        box = self.layout.progress
        words = self.host.shell.words if self.host is not None else None
        p.text(progress_text(words, self.model.unlocked, self.model.total),
               (box.x, box.y + box.h / 2), area="panel", anchor="midleft",
               max_width=box.w)

    def on_nav(self, d: Nav) -> bool:
        """Page Up / Page Down the list didn't use (focus elsewhere): scroll it."""
        if d in (Nav.PAGE_UP, Nav.PAGE_DOWN):
            return self.list.on_nav(d)
        return False

    def on_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        """The wheel anywhere in the body (the progress line too) scrolls the list."""
        if kind == "wheel":
            return self.list.on_mouse("wheel", self.list.box.center, notches=notches)
        return False

    def default_widget(self) -> "Widget | None":
        return self.list if self._list_rows else None

    # -- internals --

    def _refresh(self) -> None:
        self._signature = frozenset(self.port.unlocked())
        words = self.host.shell.words if self.host is not None else None
        self.model = achievements_model(self.port, words)
        self.fitted = [fit_row(row, self.layout, self._title_measure, self._desc_measure)
                       for row in self.model.rows]
        if len(self._list_rows) != len(self.fitted):
            self._list_rows = [ListRow("")] * len(self.fitted)
        self.list.heights_changed()

    def _activate(self, index: int) -> None:
        """Rows take focus only to scroll: no action."""

    def _colors(self) -> tuple[RGB, RGB, RGB, RGB]:
        """(text, disabled text, disabled track, marker fill) from the theme."""
        assert self.host is not None
        cfg = self.host.shell.theme.cfg
        return (tuple(cfg.panel.text_color), tuple(cfg.button.disabled.text_color),  # type: ignore
                tuple(cfg.button.disabled.track_color),
                tuple(cfg.button.marker.fill_color))

    def _draw_row(self, p: "Painter", index: int, box: Box, look: Look) -> None:
        if not 0 <= index < len(self.fitted) or self._fonts is None:
            return
        row = self.model.rows[index]
        fitted = self.fitted[index]
        layout = self.layout
        text, disabled, track, marker = self._colors()
        color = text if row.state == "unlocked" else disabled
        canvas = p.canvas
        icon = Box(box.x + ICON_X, box.y + ICON_Y, ICON, ICON)
        self._draw_icon(p, row, icon, track, marker)
        title_font, desc_font = self._fonts
        x = box.x + TEXT_X
        canvas.draw_text(fitted.title, title_font, color, (x, box.y + layout.title_y))
        line_pitch = pitch(layout.desc_size)
        for i, line in enumerate(fitted.lines):
            if line:
                canvas.draw_text(line, desc_font, color,
                                 (x, box.y + layout.desc_y + i * line_pitch))

    def _draw_icon(self, p: "Painter", row: AchievementRow, box: Box, track: RGB,
                   marker: RGB) -> None:
        """The icon, the frame (no picture or a placeholder), or the hidden ``?`` frame."""
        frame = FrameSpec(marker if row.state == "unlocked" else track, 1.0,
                          corner_radius=ICON_RADIUS)
        if row.state == "hidden":
            p.shape(box, frame)
            assert self._fonts is not None
            p.canvas.draw_text(HIDDEN_MARK, self._fonts[0], self._colors()[1], box.center,
                               anchor="center")
            return
        opacity = 1.0 if row.state == "unlocked" else LOCKED_OPACITY
        found = self.port.icon(row.image) if row.image is not None else None
        if isinstance(found, str):
            assert self.host is not None
            ref = self.host.shell.assets.image(found)
            if not ref.is_placeholder:
                draw_fitted(p.canvas, ref, box, opacity)
                return
            found = None                                    # F01 logged it once
        if found is None:
            p.shape(box, frame)
            return
        target = fit_box((ICON, ICON), box)
        p.canvas.fill((*tuple(found)[:3], round(255 * opacity)),
                      (target.x, target.y, target.w, target.h))


__all__ = ["AchievementLike", "AchievementRow", "AchievementsLayout", "AchievementsModel",
           "AchievementsPage", "AchievementsPort", "FittedRow", "HEADING", "TEXT_W", "WORDS",
           "achievements_layout", "achievements_model", "fit_row", "progress_text",
           "unlocked_notice_text", "word"]

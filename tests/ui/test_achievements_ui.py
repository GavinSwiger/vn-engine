"""F37 step 1 (pure): the notice icon (``ui/notice.py``) and the Achievements page
(``ui/builtin/achievements_page.py``) on fakes.

AC-F37-06: the notice layout with an icon (width, height, text x and y, the icon box) and
the icon drawn (a real picture fitted, never up; a placeholder's frame); without an icon the
panel is F11's (F11's own layout rows in ``test_notice.py`` run unchanged).
AC-F37-07: the page's progress text and its unlocked, locked, hidden-locked, and no-icon
rows, at 100% and 150% text, with M20 metrics for the fitting; then the page drawn by a
test host. The Extras entry and scrolling in the App (AC-F37-08) are F37-S2's.
"""

from dataclasses import dataclass

import pygame

from engine.core.geometry import Viewport
from engine.core.paths import GamePaths
from engine.render.canvas import Canvas, RenderQuality
from engine.ui.builtin.achievements_page import (
    TEXT_W,
    AchievementsPage,
    achievements_layout,
    achievements_model,
    fit_row,
    progress_text,
    unlocked_notice_text,
)
from engine.ui.focus import Box
from engine.ui.nav import Nav
from engine.ui.notice import NoticeLayer, NoticeStyle, notice_panel, notice_style
from engine.ui.paint import Painter
from engine.ui.theme import Words, measure_with, plain_theme
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.fixed_font import FixedFont
from tests.fakes.ui_shell import TestShell
from tests.render.conftest import make_assets

GREEN = (20, 200, 60)
BLUE = (30, 60, 220)
STAGE = (40, 90, 160)
BERRY = (0xA0, 0x28, 0x60)


def m20(text: str, size: int) -> float:
    return FixedFont(size).size(text)[0]


def icon_game(tmp_path, size=(32, 32), color=GREEN) -> GamePaths:
    root = tmp_path / "game"
    (root / "images").mkdir(parents=True)
    surface = pygame.Surface(size)
    surface.fill(color)
    pygame.image.save(surface, str(root / "images" / "icon.png"))
    return GamePaths.for_game(root)


def close(a, b, tol=3) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b))


# --- AC-F37-06 ---------------------------------------------------------------------------------

def test_ac_f37_06_notice_layout_and_drawing_with_an_icon(tmp_path):
    plain = notice_panel("Quick saved.", "info", m20, size=24)
    assert notice_panel("Quick saved.", "info", m20, size=24, icon=False) == plain
    assert (plain.width, plain.height, plain.text_x, plain.text_y, plain.icon) == (
        244, 58, 20, 12, None)
    short = notice_panel("Got it", "info", m20, size=24, icon=True)      # 6 × 17 = 102
    assert (short.width, short.height, short.text_x) == (102 + 80 + 20, 72, 80)
    assert short.icon == Box(20, 12, 48, 48) and short.text_y == 12 + (48 - 34) / 2
    text = unlocked_notice_text(Words(), "First Steps")
    assert text == "Achievement unlocked: First Steps"
    long = notice_panel(text, "info", m20, size=24, icon=True)           # 561 + 100 > 560
    assert (long.width, len(long.lines), long.height, long.text_y) == (560, 2, 92, 12)
    assert all(m20(line, 24) <= 560 - 100 for line in long.lines)
    problem = notice_panel("Got it", "problem", m20, size=24, icon=True)
    assert problem.icon == Box(38, 12, 48, 48) and problem.text_x == 98

    layer = NoticeLayer(NoticeStyle(), m20, reduce_motion=lambda: True)
    layer.notify("Got it", icon=None)
    layer.update(0.0)
    (view,) = layer.views()
    assert view.icon_box is None and view.box.h == 58

    assets = make_assets(icon_game(tmp_path))
    theme = plain_theme()
    style = notice_style(theme)
    layer = NoticeLayer(style, measure_with(assets, style.font), reduce_motion=lambda: True)
    picture = assets.image("images/icon.png")
    missing = assets.image("images/none.png")
    assert missing.is_placeholder and not picture.is_placeholder
    layer.notify("Achievement unlocked: First Steps", icon=picture)
    layer.notify("Achievement unlocked: Secret Garden", icon=missing)
    layer.update(0.0)
    first, second = layer.views()
    assert first.icon is picture and first.icon_box == Box(first.box.x + 20, 36, 48, 48)
    assert second.icon_box.y == second.box.y + 12 and first.box.h == second.box.h == 72
    canvas = Canvas(assets)
    framebuffer = pygame.Surface((1280, 720))
    framebuffer.fill(STAGE)
    canvas.bind(framebuffer, Viewport.compute((1280, 720), (1280, 720)), RenderQuality.FINAL)
    layer.draw(canvas, Painter(theme))

    def px(x, y):
        return tuple(framebuffer.get_at((round(x), round(y))))[:3]

    box = first.icon_box                                          # 32×32 centred, never up
    assert px(box.x + 24, box.y + 24) == GREEN
    assert px(box.x + 9, box.y + 9) == GREEN and px(box.x + 6, box.y + 6) != GREEN
    box = second.icon_box                                         # placeholder: the frame
    assert close(px(box.x + 24, box.y + 24), BERRY)


# --- AC-F37-07 ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class Ach:
    name: str
    title: str
    description: str = ""
    image: str | None = None
    hidden: bool = False


class Port:
    def __init__(self, items, unlocked, icons) -> None:
        self.items = items
        self.held = set(unlocked)
        self.icons = icons

    def achievements(self):
        return self.items

    def unlocked(self):
        return self.held

    def icon(self, image):
        return self.icons.get(image)


LONG = "Find the hidden garden behind the old shrine " * 6
ITEMS = (Ach("first_steps", "First Steps", "Finish the prologue.", "achievements first"),
         Ach("garden", "Secret Garden", "Find the hidden garden.", "achievements garden",
             hidden=True),
         Ach("completionist", "Completionist " * 6, LONG, "achievements first"),
         Ach("plain", "Plain"),
         Ach("solid", "Solid", "", "achievements blue"))


class Host:
    def __init__(self, shell) -> None:
        self.shell = shell
        self.painter = shell.painter
        self.rebuilt = 0

    @property
    def scope(self):
        return None

    def rebuild(self) -> None:
        self.rebuilt += 1

    def close_menu(self) -> None:
        pass


def test_ac_f37_07_page_progress_rows_and_text_size(tmp_path, monkeypatch):
    icons = {"achievements first": "images/icon.png", "achievements blue": BLUE}
    port = Port(ITEMS, {"first_steps", "plain"}, icons)
    model = achievements_model(port, Words())
    assert progress_text(Words(), model.unlocked, model.total) == "Unlocked: 2 / 5"
    assert [(r.state, r.title) for r in model.rows] == [
        ("unlocked", "First Steps"), ("hidden", "Hidden achievement"),
        ("locked", "Completionist " * 6), ("unlocked", "Plain"), ("locked", "Solid")]
    hidden = model.rows[1]
    assert (hidden.description, hidden.image) == ("Keep playing to unlock it.", None)
    port.held.add("garden")                          # unlocked: its real texts (edge case)
    assert achievements_model(port, Words()).rows[1].title == "Secret Garden"
    port.held.discard("garden")

    at100 = achievements_layout(1.0)
    assert (at100.progress, at100.list) == (Box(416, 112, 808, 24), Box(416, 152, 808, 512))
    assert (at100.row_h, at100.title_size, at100.desc_size, at100.desc_y) == (104, 24, 20, 50)
    at150 = achievements_layout(1.5)
    assert (at150.row_h, at150.title_size, at150.desc_size, at150.desc_y) == (144, 36, 30, 66)
    for layout in (at100, at150):
        fitted = fit_row(model.rows[2], layout, m20, m20)
        assert fitted.title.endswith("…") and m20(fitted.title, layout.title_size) <= TEXT_W
        assert len(fitted.lines) == 2 and fitted.lines[-1].endswith("…")
        assert all(m20(line, layout.desc_size) <= TEXT_W for line in fitted.lines)
        assert fit_row(model.rows[3], layout, m20, m20).lines == ()

    shell = TestShell(assets=make_assets(icon_game(tmp_path)))
    host = Host(shell)
    page = AchievementsPage(port, measures=(m20, m20))
    (group,) = page.build(host, Box(416, 112, 808, 552))
    assert page.list.box == Box(416, 152, 808, 512) and page.default_widget() is page.list
    assert [page.list.row_box(i).h for i in range(5)] == [104] * 5
    canvas = Canvas(shell.assets)
    framebuffer = pygame.Surface((1280, 720))
    framebuffer.fill(STAGE)
    canvas.bind(framebuffer, Viewport.compute((1280, 720), (1280, 720)), RenderQuality.FINAL)
    shell.painter.bind(canvas)
    cfg = shell.theme.cfg
    with spy_draw_text(monkeypatch) as calls:
        page.draw(canvas, shell.painter)
        for i in page.list.visible_range():
            page._draw_row(shell.painter, i, page.list.row_box(i), None)
    drawn = {c.text: c for c in calls}
    assert "Unlocked: 2 / 5" in drawn and drawn["?"].options.get("anchor") == "center"
    assert drawn["First Steps"].color == tuple(cfg.panel.text_color)
    assert drawn["First Steps"].pos == (416 + 96, 152 + 16)
    assert drawn["Finish the prologue."].pos == (416 + 96, 152 + 50)
    assert drawn["Hidden achievement"].color == tuple(cfg.button.disabled.text_color)
    assert "Secret Garden" not in drawn and "Find the hidden garden." not in drawn

    def px(x, y):
        return tuple(framebuffer.get_at((round(x), round(y))))[:3]

    first = page.list.row_box(0)                     # the 32×32 icon centred in 64×64
    assert px(first.x + 16 + 32, first.y + 20 + 32) == GREEN
    third = page.list.row_box(2)                     # locked: 35% over what is under it
    assert px(third.x + 48, third.y + 52) not in (GREEN, STAGE)
    plain = page.list.row_box(3)                     # no icon, unlocked: the marker frame
    assert close(px(plain.x + 48, plain.y + 52), tuple(cfg.button.marker.fill_color))
    hidden_row = page.list.row_box(1)                # the hidden frame
    assert close(px(hidden_row.x + 20, hidden_row.y + 24),
                 tuple(cfg.button.disabled.track_color))

    assert page.on_mouse("wheel", (420, 120), notches=-1) and page.list.scroll > 0
    page.list.scroll = 0.0
    assert page.on_nav(Nav.PAGE_DOWN) and page.list.scroll > 0
    page.list.activate()                             # no action
    shell.painter.set_text_scale(lambda: 1.5)
    page.build(host, Box(416, 112, 808, 552))
    assert page.list.row_box(0).h == 144

"""F20 s8 in the real app (06 §0.5: one App F session, module-scoped by design): Template L
launched in process (``scripted_app``: fake clock, hidden window, dev, unthreaded writer) with
the title on and ``[saves] autosave_quit = true``.

Rows: AC-F20-56's in-app rows (the title entry hidden on a first run and shown once a node
can be jumped to; the game entry shown for Template L; the page opens from the sidebar) and
AC-F20-30's page rows (in game: ``flowchart_confirm_autosave`` with No focused, No returns
focus to the node, Yes jumps and closes the menus; from the title: no confirm, the jump goes at
once). The service side of AC-F20-30 (the Auto save before the commit) is in
``test_flow_jump_app.py``.
"""

import shutil
from pathlib import Path

import pygame
import pytest

from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.builtin.flowchart_page import FlowchartPage
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.menus import EntryContext
from engine.ui.nav import InputKind, Nav
from engine.ui.shell import Mode
from tests.app.test_saves_service import launch, line_text, play, unthreaded, wait
from tests.fakes.loop import post_key

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]

TEMPLATE = Path(__file__).resolve().parents[1] / "fixtures" / "F20" / "template"
CONFIG = """[game]
id = "f20-template"

[textbox]
cps = 0

[saves]
autosave_quit = true

[theme.ui]
fade_ms = 0

[theme.save]
load_fade_ms = 0
"""
LINE12 = "Daichi waves from the stall."
LINE19 = "Come on, the good spots are filling up."
STALL = "scene:stall"


def test_flow_page_in_the_app(tmp_path, scripted_app, unthreaded):
    game = tmp_path / "game"
    shutil.copytree(TEMPLATE, game)
    (game / "config.toml").write_text(CONFIG, encoding="utf-8")

    def shown(app, menu: str) -> list[str]:
        return [e.id for e in app.shell.menus.shown(menu)]

    def script(app, out):
        yield from wait(lambda: isinstance(app.screens.top, TitleScreen))
        words = app.shell.words
        out["first_title"] = "flowchart" in shown(app, "title")
        app.shell.menus.entry("title", "new_game").action(
            EntryContext(app.shell, InputKind.KEYS))
        yield from wait(lambda: line_text(app) is not None)
        out["game_entry"] = "flowchart" in shown(app, "game")
        while line_text(app) != LINE19:                 # past the stall's checkpoint
            post_key(pygame.K_SPACE)
            for _ in range(3):
                yield
        yield from wait(lambda: app.flow.can_jump(STALL))
        # In game: open the page from the game menu.
        post_key(pygame.K_ESCAPE)
        yield from wait(lambda: app.shell.game_menu() is not None)
        menu = app.shell.game_menu()
        menu.open_page("flowchart")
        page = menu.page
        out["page"] = isinstance(page, FlowchartPage) and page.port.in_game
        graph = app.flow.recorder().graph
        stall = graph.by_id[STALL]
        out["here"] = page.chart.selected == stall
        menu.scope.focus(page.chart, InputKind.KEYS)
        yield
        page.chart.select(stall)
        menu.scope.press(Nav.ACTIVATE)
        yield
        confirm = app.screens.top
        out["confirm"] = (isinstance(confirm, ConfirmScreen) and confirm.message,
                          words.get("flowchart_confirm_autosave"),
                          confirm.scope.focused is confirm.no_button)
        post_key(pygame.K_ESCAPE)                        # No
        yield from wait(lambda: app.screens.top is menu)
        yield
        out["after_no"] = (menu.page is page, menu.scope.focused is page.chart,
                           line_text(app))
        menu.scope.press(Nav.ACTIVATE)
        yield
        app.screens.top.yes_button.activate()
        yield from wait(lambda: line_text(app) == LINE12 and app.shell.game_menu() is None)
        out["jumped"] = True
        # From the title: the entry shows, and a jump needs no confirm.
        app.shell.return_to_title()
        yield from wait(lambda: isinstance(app.screens.top, TitleScreen))
        out["later_title"] = "flowchart" in shown(app, "title")
        app.shell.open_title_page("flowchart", InputKind.KEYS)
        yield
        title_menu = app.shell.game_menu()
        title_page = title_menu.page
        out["title_page"] = (isinstance(title_page, FlowchartPage), title_page.port.in_game,
                             title_page.chart.here())
        title_page.chart.select(stall)
        title_menu.scope.focus(title_page.chart, InputKind.KEYS)
        title_menu.scope.press(Nav.ACTIVATE)
        yield
        out["no_confirm"] = not isinstance(app.screens.top, ConfirmScreen)
        yield from wait(lambda: line_text(app) == LINE12 and app.shell.mode is Mode.GAME)
        out["title_jump"] = True

    out = play(scripted_app, script, last=1500)
    assert launch(game) == 0
    assert out["first_title"] is False and out["game_entry"] is True
    assert out["page"] is True and out["here"] is True
    message, autosave, no_first = out["confirm"]
    assert message == autosave and no_first
    assert out["after_no"] == (True, True, LINE19)
    assert out.get("jumped") is True
    assert out["later_title"] is True
    assert out["title_page"] == (True, False, None)
    assert out["no_confirm"] is True and out.get("title_jump") is True

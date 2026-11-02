"""F16 step 4, the App side: ``install_settings_ui`` (``07`` I-11, I-13; F16 conflict 12),
``SettingsService.progress`` / ``delete_progress`` (``04`` §7.7; AC-F16-26, 29 service
half), and the project's window-size rule (the windowed size is stored at quit only
when the player resized the window; AC-F16-19). The page itself is
``tests/ui/test_settings_page.py``.
"""

from types import MappingProxyType, SimpleNamespace

import pygame
import pytest

from engine.app.settings import NOTICE_TEXT, SettingsService, install_settings_ui
from engine.core.config_schema import Config
from engine.persist.settings_file import LoadedSettings, Outcome
from engine.persist.sync import MEMORY, READ_ONLY, WRITABLE
from engine.ui.builtin.settings_page import SettingsPage
from engine.ui.menu_screen import CursorKeeper
from engine.ui.nav import InputKind
from engine.ui.screen import ScreenStack
from engine.ui.shell import GameShell, ShellPorts
from engine.ui.theme import Words, plain_theme
from tests.fakes.fake_window import FakeWindow
from tests.render.conftest import make_assets

pytestmark = pytest.mark.display


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    yield
    pygame.quit()


def service(tmp_path, values=None, *, window=None, notices=()) -> SettingsService:
    folder = tmp_path / "game" / "settings"
    loaded = LoadedSettings(MappingProxyType(dict(values or {})), Outcome.OK, None,
                            folder=folder, writable=True)
    return SettingsService(loaded, Config(), window=window or FakeWindow(), clock=lambda: 0.0,
                           game_root=tmp_path / "game", notices=notices)


def shell() -> GameShell:
    config = Config()
    ports = ShellPorts(stack=ScreenStack(), assets=make_assets(None), dev=True, config=config,
                       new_game=lambda: None, in_game_screens=lambda: [],
                       reset_in_game=lambda: None, request_quit=lambda: None)
    return GameShell(ports, theme=plain_theme(config.theme), words=Words(config.words),
                     cursor=CursorKeeper(lambda v: None))


class Store:
    def __init__(self) -> None:
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1


def test_install_settings_ui_registers_entries_text_scale_and_notice(tmp_path):
    settings = service(tmp_path, notices=(NOTICE_TEXT,))
    app = SimpleNamespace(settings=settings, shell=shell(),
                          persist=SimpleNamespace(mode=WRITABLE, store=Store()))
    notices: list[tuple] = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(app.shell, "notify", lambda text, kind="info": notices.append((text, kind)))
        install_settings_ui(app)
        install_settings_ui(SimpleNamespace(settings=settings, shell=None))    # no shell
    menus = app.shell.menus
    for menu in ("title", "game", "quick"):
        assert menus.entry(menu, "settings") is not None, menu
    title_page = menus.entry("title", "settings").page
    assert title_page is not None and menus.entry("quick", "settings").action is not None
    assert notices == [("Your settings couldn't be read, so the defaults are used.",
                        "problem")]
    assert settings.take_notices() == []                              # drained once
    painter = app.shell.painter
    assert painter.text_scale() == 1.0
    for pct, size in ((110, 31), (130, 36), (150, 42)):
        settings.set("text_size_pct", pct)
        assert painter.text_scale() == size / 28
    assert settings.persist is app.persist

    bare = SimpleNamespace(settings=None, shell=shell())
    install_settings_ui(bare)                                         # headless: nothing
    assert bare.shell.menus.entry("game", "settings") is None


def test_progress_follows_persistent_data_and_delete_resets_the_store(tmp_path):
    settings = service(tmp_path)
    store = Store()
    for persist, state in ((None, "disabled"),
                           (SimpleNamespace(mode=READ_ONLY, store=store), "disabled"),
                           (SimpleNamespace(mode=MEMORY, store=store), "enabled"),
                           (SimpleNamespace(mode=WRITABLE, store=store), "enabled")):
        settings.persist = persist
        assert settings.progress() == state
        settings.delete_progress()
    assert store.resets == 2 and settings.stored == {}


def test_window_size_is_stored_only_after_the_player_resized(tmp_path):
    fitted = FakeWindow((1280, 720))                                  # stored size fitted down
    kept = service(tmp_path, {"window_size": (1600, 900)}, window=fitted)
    kept.submit_final()
    assert kept.stored == {"window_size": (1600, 900)}
    resized = FakeWindow((1280, 720))
    changed = service(tmp_path, window=resized)
    resized.user_resize(1500, 800)
    changed.submit_final()
    assert changed.stored == {"window_size": (1500, 800)}
    started = FakeWindow(start_fullscreen=True, initial_size_for_restore=(1164, 655))
    untouched = service(tmp_path, window=started)
    untouched.submit_final()                                          # never windowed
    assert "window_size" not in untouched.stored


def test_title_page_from_install_has_delete_progress(tmp_path):
    settings = service(tmp_path)
    app = SimpleNamespace(settings=settings, shell=shell(), persist=None)
    install_settings_ui(app)
    app.shell.open_title_page("settings", InputKind.KEYS)
    page = app.shell.game_menu().page
    assert isinstance(page, SettingsPage) and page.title
    delete = page.widgets["delete_progress"]
    assert not delete.enabled()                                       # no App.persist
    fullscreen = page.widgets["fullscreen"]
    fullscreen.activate()
    assert settings.value("fullscreen") is True and settings.window.fullscreen

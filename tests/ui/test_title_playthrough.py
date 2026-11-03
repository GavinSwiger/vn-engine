"""F32 step 4: the title in a playthrough look (``06-acceptance.md`` AC-F32-14; ``04`` §6.4).
Also AC-F10-47's title-look row, moved here when F32 removed ``UiOverrides.set_title_look``
(main decision 2): a ``[playthrough.0]`` table with that art and music.

``LookRig`` is ``test_title.py``'s ``Rig`` with ``install_looks`` between ``install_ui`` and
``check_entries`` (as ``install_story`` does), a fake interpreter whose persistent store holds
``persistent.playthrough``, and a story program with no ``ui`` lines.
``tests/app/test_looks_install.py`` uses it too.
"""

import pygame
import pytest

from engine.app.looks import install_looks
from engine.app.menus import install_ui
from engine.app.text_check import install_textbox
from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.runtime.persistent import Missing
from engine.ui.menu_screen import CursorKeeper
from engine.ui.menus import UiOverrides
from tests.fakes.audio_spy import AudioSpy
from tests.fakes.ui_shell import UiHarness
from tests.render.conftest import make_assets
from tests.ui.test_title import FADE_IN_FRAMES, FakeApp, close, make_game

BG = (40, 120, 200)                      # gui/title_bg.png (F10's generated art)


class FakeStore:
    def __init__(self, values: dict) -> None:
        self.values = values

    def peek(self, name: str):
        return self.values.get(name, Missing)


class FakeProgram:
    def __init__(self, statements=()) -> None:
        self.statements = list(statements)

    def iter_statements(self):
        return iter(self.statements)


class FakeInterp:
    def __init__(self, values: dict, statements=()) -> None:
        self.persistent = FakeStore(values)
        self.program = FakeProgram(statements)


class LookApp(FakeApp):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.shutdown: list = []

    def add_shutdown(self, fn) -> None:
        self.shutdown.append(fn)


class LookRig:
    """A launched title with F32's looks."""

    def __init__(self, tmp_path, config: str = "", *, playthrough: object = 0,
                 dev: bool = True, audio=None, statements=(), saves=None,
                 before_looks=None) -> None:
        root = make_game(tmp_path, config, art=True)
        paths = GamePaths.for_game(root)
        loaded = load_config(paths)
        assert not loaded.errors, [e.format() for e in loaded.errors]
        self.assets = make_assets(paths)
        if before_looks is not None:
            before_looks(self.assets)
        self.app = LookApp(loaded.config, self.assets, dev=dev, audio=audio)
        if saves is not None:
            self.app.saves = saves
        install_textbox(self.app)
        self.shell = install_ui(self.app)
        self.shell.cursor = CursorKeeper(lambda visible: None)
        self.values = {} if playthrough is None else {"playthrough": playthrough}
        self.interp = FakeInterp(self.values, statements)
        self.looks = install_looks(self.app, self.interp)
        self.shell.check_entries()
        self.h = UiHarness(self.shell)
        self.app.screens.replace_all(self.shell.initial_screens())

    @property
    def title(self):
        return self.app.screens.top

    def frame(self, *events):
        return self.h.frame(*events)

    def frames(self, n: int):
        return self.h.frames(n)

    def px(self, x, y):
        return self.h.px(x, y)


LOOK2 = ('[playthrough.2]\ntitle_entries = ["quit", "new_game"]\n'
         '[playthrough.2.theme.title]\nbackground_image = "gui/title_bg.png"\n'
         'music = "title_quiet.ogg"\n'
         '[playthrough.2.words]\nnew_game = "Again?"\nhistory = "Before"\nmenu = "Pause"\n'
         '[theme.title]\nmusic = "title.ogg"\n')


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    yield
    pygame.quit()


# --- AC-F32-14 — the title, the warning, and menus in a playthrough look ----------------------

def test_ac_f32_14_the_title_in_playthrough_look_2(tmp_path):
    audio = AudioSpy()
    rig = LookRig(tmp_path, LOOK2, playthrough=2, audio=audio)
    assert rig.looks.key == (2, None)
    rig.frames(FADE_IN_FRAMES + 1)
    title = rig.title
    assert [b.label() for b in title.buttons] == ["Quit", "Again?"]
    assert close(rig.px(1000, 600), BG)                          # the look's cover picture
    assert audio.calls[:2] == [("take_music", "title"), ("play", "title_quiet.ogg", True, 0.0)]
    # G4: the same file already playing on the handle keeps playing (no stop, no restart).
    calls = len(audio.calls)
    rig.shell.title_entered()
    assert ("stop", 0.5) not in audio.calls[calls:]
    assert not any(c[0] == "take_music" for c in audio.calls[calls:])
    # The look's words reach every menu (game menu's history, the quick menu's menu).
    assert rig.shell.words.get("history") == "Before"
    assert rig.shell.words.get("menu") == "Pause"
    # Stored 0: the base look, its music and buttons.
    audio0 = AudioSpy()
    rig0 = LookRig(tmp_path / "zero", LOOK2, playthrough=0, audio=audio0)
    rig0.frames(FADE_IN_FRAMES + 1)
    assert rig0.looks.key == (None, None) and rig0.shell.theme is rig0.shell.base_theme
    assert [b.label() for b in rig0.title.buttons] == ["New Game", "Quit"]
    assert audio0.calls[:2] == [("take_music", "title"), ("play", "title.ogg", True, 0.0)]
    # UiOverrides lost its title look (main decision 2).
    assert not any(hasattr(UiOverrides, name) for name in ("set_title_look", "title_look"))
    import engine.ui.menus as menus
    assert not hasattr(menus, "KEEP") and not hasattr(menus, "TITLE_LOOK_PARTS")
    # AC-F10-47's title-look row: a [playthrough.0] table with that art and music.
    audio_p0 = AudioSpy()
    rig_p0 = LookRig(tmp_path / "p0", '[playthrough.0.theme.title]\n'
                     'background_image = "gui/title_bg.png"\nmusic = "other.ogg"\n',
                     playthrough=0, audio=audio_p0)
    rig_p0.frames(FADE_IN_FRAMES + 1)
    assert close(rig_p0.px(1000, 600), BG)
    assert audio_p0.calls[:2] == [("take_music", "title"), ("play", "other.ogg", True, 0.0)]

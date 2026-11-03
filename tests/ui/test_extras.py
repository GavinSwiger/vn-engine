"""F34 W3 — the Extras host and the gallery in the game: AC-F34-06, 16, 17 and 07 I-3.

The title is test_title's ``Rig`` (``install_ui`` over a small fake App); ``install_extras``
and ``add_extras_page`` (``app/extras.py``) are called on it as ``install_story`` does, then
the title is shown again. The Gallery rows use the real ``install_gallery`` over a fake
interpreter: a loaded ``Program`` and a real ``PersistentStore`` with the ``"gallery"``
kind registered (``runtime/gallery.register``)."""

from types import SimpleNamespace

import pygame

from engine.app.extras import add_extras_page, install_extras
from engine.app.gallery import install_gallery, missing_ref
from engine.runtime import gallery as gallery_mod
from engine.runtime.persistent import PersistentStore
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.gallery_viewer import GalleryViewer
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.focus import Box, FocusGroup
from engine.ui.menus import MenuEntry, MenuPageBase
from engine.ui.nav import InputKind
from engine.ui.shell import Mode
from engine.ui.widgets import Button
from tests.fakes.ui_shell import UiHarness as H
from tests.runtime.stage_story import story_game
from tests.runtime.test_stage_check import launch
from tests.ui.test_title import FADE_IN_FRAMES, Rig

FADE = 9                                       # ui.fade_ms 150 at 60 fps
EXTRA_WORDS = {"endings": "Endings", "music_room": "Music room"}   # F35/F36 add theirs


class Page(MenuPageBase):
    """One button; ``widget_for("tile")`` is that button."""

    heading = "gallery"

    def __init__(self, name: str) -> None:
        self.name = name
        self.button = Button(lambda: self.name, lambda: None)
        self.closes = 0

    def build(self, host, body: Box) -> list[FocusGroup]:
        self.button.box = Box(body.x, body.y, 300, 56)
        return [FocusGroup([self.button])]

    def widget_for(self, key):
        return self.button if key == "tile" else None

    def closed(self) -> None:
        self.closes += 1


def rig_with(tmp_path, config: str = "") -> Rig:
    rig = Rig(tmp_path, config)
    install_extras(rig.app)
    words = rig.shell.words
    base = words.override
    words.override = lambda key: EXTRA_WORDS.get(key) or base(key)
    return rig


def retitle(rig: Rig) -> TitleScreen:
    rig.app.screens.replace_all(rig.shell.initial_screens())
    rig.frames(FADE_IN_FRAMES + 1)
    return rig.title


def labels(screen) -> list[str]:
    return [b.label() for b in screen.buttons]


def gallery_story(tmp_path, top: str):
    """A loaded program with ``top`` (gallery lines) and the fake interpreter over it."""
    program = story_game(tmp_path / "story", ['"Hello."'], top=top)
    store = PersistentStore(identity_scheme=1)
    interp = SimpleNamespace(program=program, persistent=store)
    gallery_mod.register(interp)                       # as Interpreter.__init__
    return program, interp


# --- AC-F34-06 — a gallery picture with no file ------------------------------------------------

def test_ac_f34_06_missing_picture_warns_once_and_shows_the_placeholder(tmp_path):
    """``cg storm`` has no file: one F04 W12 at launch, at the declaration; its tile's
    thumbnail and the viewer show F04's placeholder."""
    top = 'lock gallery cg storm "Storm"\nlock gallery cg festival "Festival"\n'
    program, interp = gallery_story(tmp_path, top)
    result = launch(program, ["images/cg/festival.png"])
    w12 = [w for w in result.warnings if w.code == "W12"]
    assert len(w12) == 1 and '"cg storm"' in w12[0].message
    assert (w12[0].file, w12[0].line) == ("script/main.vns", 3)
    rig = rig_with(tmp_path / "title")
    port = install_gallery(rig.app, interp, result.images)
    assert port.picture("cg storm") == missing_ref("cg storm") == "images/cg/storm.png"
    interp.persistent.unlock("gallery", "cg storm")
    retitle(rig)
    screen = rig.shell.open_extras(by=InputKind.KEYS)
    rig.frames(FADE + 4)                                # the thumbnail, one per frame
    ref = "images/cg/storm.png"
    assert rig.app.extras.thumbs.ready(ref) and rig.assets.image(ref).is_placeholder
    assert screen.scope.focused is screen.page.widget_for("cg storm")
    rig.frame(H.key(pygame.K_RETURN))
    viewer = rig.app.screens.top
    assert isinstance(viewer, GalleryViewer) and viewer.current.key == "cg storm"
    assert viewer._current.is_placeholder


# --- AC-F34-16 — the title's Extras button -----------------------------------------------------

def test_ac_f34_16_extras_shows_once_something_is_unlocked(tmp_path):
    """Hidden on a first run, shown after one gallery unlock; F32's hide and ``[title]
    entries`` apply as to any title button."""
    top = 'lock gallery cg festival "Festival"\n'
    cases = [("", None, ["New Game", "Extras", "Quit"]),
             ('[title]\nentries = ["new_game", "quit"]', None, ["New Game", "Quit"]),
             ('[title]\nentries = ["extras", "quit"]', None, ["Extras", "Quit"]),
             ("", True, ["New Game", "Quit"])]
    for i, (config, hidden, after) in enumerate(cases):
        program, interp = gallery_story(tmp_path / str(i), top)
        rig = rig_with(tmp_path / str(i) / "title", config)
        install_gallery(rig.app, interp)
        if hidden is not None:
            rig.shell.overrides.set_hidden("title", "extras", hidden)
        before = labels(retitle(rig))
        assert "Extras" not in before, i
        interp.persistent.unlock("gallery", "cg festival")
        assert labels(retitle(rig)) == after, i


# --- AC-F34-17 — the Extras screen -------------------------------------------------------------

def test_ac_f34_17_extras_screen_pages_order_and_back(tmp_path):
    """Return plus the shown entries in ``extras`` order (whatever order they joined in),
    the first shown page open (or the one asked for), ``focus=`` on a page's widget, Back
    and Return to the title with Extras focused, and nothing outside the title."""
    rig = rig_with(tmp_path)
    shown = {"music_room": True, "gallery": True, "endings": False}
    pages: dict[str, Page] = {}

    def entry(name):
        def page(host):
            pages[name] = Page(name)
            return pages[name]
        return MenuEntry(name, page=page, visible=lambda: shown[name])

    for name in ("music_room", "endings", "gallery"):
        add_extras_page(rig.app, entry(name), kind=name, names=lambda: ())
    title = retitle(rig)
    assert labels(title) == ["New Game", "Extras", "Quit"]
    rig.frame(H.key(pygame.K_DOWN))
    rig.frame(H.key(pygame.K_DOWN))                     # Extras focused
    rig.frame(H.key(pygame.K_RETURN))
    screen = rig.app.screens.top
    assert isinstance(screen, GameMenuScreen) and screen.menu == "extras"
    assert labels(screen) == ["Return", "Gallery", "Music room"]
    assert screen.page_id == "gallery" and screen.from_title
    rig.frames(FADE + 1)
    rig.frame(H.key(pygame.K_ESCAPE))                   # Back
    rig.frames(FADE + 1)
    assert rig.stack == [title] and pages["gallery"].closes == 1
    assert title.scope.focused is title.buttons[1] and title.scope.visible   # Extras
    shown["gallery"] = False                            # the first shown page opens
    screen = rig.shell.open_extras(by=InputKind.MOUSE)
    assert labels(screen) == ["Return", "Music room"] and screen.page_id == "music_room"
    rig.frames(FADE + 1)
    rig.h.click(screen.buttons[0].box.center)           # Return
    rig.frames(FADE + 1)
    assert rig.stack == [title]
    shown["gallery"] = True
    screen = rig.shell.open_extras("music_room", by=InputKind.KEYS, focus="tile")
    assert screen.page_id == "music_room"
    assert screen.scope.focused is pages["music_room"].button and screen.scope.visible
    rig.frames(FADE + 1)
    rig.frame(H.key(pygame.K_ESCAPE))
    rig.frames(FADE + 1)
    rig.shell.mode = Mode.GAME                           # only on the title
    assert rig.shell.open_extras(by=InputKind.KEYS) is None and rig.stack == [title]


# --- 07 I-3 — the thumbnails pump the prefetcher only on the title ----------------------------

def test_i3_thumbnails_pump_the_prefetcher_only_on_the_title(tmp_path):
    """The stage pumps the launch's prefetcher only while it is updated (in game); the
    Extras ``ThumbCache`` only in mode TITLE: never both in one frame."""
    rig = Rig(tmp_path)
    pumps: list[Mode] = []
    rig.app.prefetcher = SimpleNamespace(pending=False, request=lambda wanted: None,
                                         pump=lambda: pumps.append(rig.shell.mode))
    thumbs = install_extras(rig.app).thumbs
    assert thumbs.prefetcher is rig.app.prefetcher
    thumbs.pump_prefetcher()
    rig.shell.start_new_game()
    rig.frames(FADE_IN_FRAMES + 12)
    assert rig.shell.mode is Mode.GAME
    thumbs.pump_prefetcher()
    assert pumps == [Mode.TITLE]

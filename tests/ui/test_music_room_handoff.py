"""F35 S2 — the Music Room in the game: AC-F35-08 (the title music hand-off) and F34–F37
``07-architecture-review.md`` I-5 (a replay's cut and a quit while the room is open).

The title is test_title's ``Rig`` over F08's Service S (``tests/audio/conftest.py``: the real
``AudioService`` on a FakeMixer and a fake clock); ``install_extras`` and the real
``install_music_room`` (``app/musicroom.py``) run on it as ``install_story`` does, over a fake
interpreter (a loaded ``Program`` and a real ``PersistentStore``). The title plays
``bgm/shrine_steps.ogg``; the room's tracks are ``bgm/omen.ogg`` (``open``) and
``bgm/festival.ogg``. A second Extras page (``gallery``, one button) stands for "another
Extras entry". F36's replay start isn't built yet: New Game from under the open room takes
the same path (``leave_title``, then the cut that closes the Extras screen)."""

from types import SimpleNamespace

import pygame

from engine.app.extras import add_extras_page, install_extras
from engine.app.musicroom import install_music_room
from engine.runtime.persistent import PersistentStore
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.music_room_page import MusicRoomPage
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.menus import MenuEntry
from engine.ui.nav import InputKind
from engine.ui.shell import Mode
from tests.audio.conftest import make_service
from tests.fakes.ui_shell import UiHarness as H
from tests.runtime.stage_story import story_game
from tests.ui.test_extras import Page
from tests.ui.test_title import FADE_IN_FRAMES, Rig

FADE = 9                                       # ui.fade_ms 150 at 60 fps
TITLE, OMEN, FESTIVAL = "bgm/shrine_steps.ogg", "bgm/omen.ogg", "bgm/festival.ogg"
TOP = (f'lock track omen "Omen" file "{OMEN}" open\n'
       f'lock track festival "Festival Night" file "{FESTIVAL}"\n')


def room(tmp_path, *, title_music: bool = True, top: str = TOP):
    """Service S, the title rig with Extras (the Music Room and a ``gallery`` page), and
    the port; the title shown and its music started."""
    (tmp_path / "audio").mkdir(parents=True)
    s = make_service(tmp_path / "audio", threaded=False)
    config = f'[theme.title]\nmusic = "{TITLE}"' if title_music else ""
    rig = Rig(tmp_path / "title", config, audio=s.service)
    install_extras(rig.app)
    program = story_game(tmp_path / "story", [f'play music "{FESTIVAL}"', '"Hello."'], top=top)
    interp = SimpleNamespace(program=program, persistent=PersistentStore(identity_scheme=1))
    port = install_music_room(rig.app, interp)
    add_extras_page(rig.app, MenuEntry("gallery", page=lambda host: Page("gallery"),
                                       visible=lambda: True), kind="gallery", names=lambda: ())
    rig.frames(FADE_IN_FRAMES + 1)
    s.run(0.2)
    return s, rig, port


def names(s) -> list[str]:
    """Every ``music_start``'s file, in order."""
    return [args[0] for _t, name, args in s.mixer.calls if name == "music_start"]


def open_room(rig) -> tuple[GameMenuScreen, MusicRoomPage]:
    screen = rig.shell.open_extras("music_room", by=InputKind.KEYS)
    rig.frames(FADE + 1)
    assert screen.page_id == "music_room" and isinstance(screen.page, MusicRoomPage)
    return screen, screen.page


def back(rig) -> None:
    rig.frame(H.key(pygame.K_ESCAPE))
    rig.frames(FADE + 1)


# --- AC-F35-08 ---------------------------------------------------------------------------------

def test_ac08_the_room_borrows_the_title_music_and_gives_it_back(tmp_path):
    s, rig, port = room(tmp_path)
    assert names(s) == [TITLE]
    title_handle = rig.shell._music
    screen, page = open_room(rig)
    assert port.handle().inner is title_handle and s.service._taker is title_handle
    s.run(0.5)
    back(rig)                                       # nothing played: the title music goes on
    s.run(1.0)
    assert names(s) == [TITLE] and rig.shell._music is title_handle

    screen, page = open_room(rig)
    assert page.player.pick(0)                      # Omen, from the start
    s.run(1.0)
    assert names(s)[-1] == OMEN
    back(rig)                                       # Back: out over music_fadeout, title again
    s.run(1.0)
    assert names(s)[-2:] == [OMEN, TITLE] and s.service._taker is title_handle
    assert isinstance(rig.app.screens.top, TitleScreen)

    screen, page = open_room(rig)                   # another Extras entry closes the room
    page.player.pick(0)
    s.run(0.5)
    screen.open_page("gallery")
    s.run(1.0)
    assert names(s)[-2:] == [OMEN, TITLE] and screen.page_id == "gallery"

    s2, rig2, port2 = room(tmp_path / "quiet", title_music=False)
    assert names(s2) == [] and s2.service._taker is None
    screen, page = open_room(rig2)
    held = port2.handle().inner
    assert s2.service._taker is held and held.owner == "title"
    page.player.pick(0)
    s2.run(0.5)
    back(rig2)                                      # no title music: the handle is released
    assert s2.service._taker is None and rig2.shell._music is None and not held.active


# --- 07 I-5 ------------------------------------------------------------------------------------

def test_i5_a_cut_or_a_quit_with_the_room_open_never_brings_the_title_music_back(tmp_path):
    s, rig, port = room(tmp_path)
    screen, page = open_room(rig)
    page.player.pick(0)
    s.run(0.5)
    takes: list[str] = []
    take = s.service.take_music
    s.service.take_music = lambda owner: (takes.append(owner), take(owner))[1]
    rig.shell.start_new_game()                      # the title goes; the cut closes Extras
    rig.frames(FADE + 3)
    assert rig.shell.mode is Mode.GAME and screen not in list(rig.app.screens)
    assert takes == [] and s.service._taker is None and rig.shell._music is None
    s.run(1.0)
    assert names(s)[-1] == OMEN                     # no title start after the room's track

    s2, rig2, port2 = room(tmp_path / "quit")
    screen, page = open_room(rig2)
    page.player.pick(1 if port2.is_open("festival") else 0)
    s2.run(0.5)
    assert rig2.shell.quit_guard() is True          # on the title: quits at once
    s2.service.shutdown()
    before = names(s2)
    page.closed()                                   # a late close after the device went
    page.closed()                                   # twice: the handle is inert by now
    s2.run(0.5)
    assert names(s2) == before

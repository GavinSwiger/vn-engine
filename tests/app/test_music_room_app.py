"""F35 S2 — the Music Room in Extras: AC-F35-09 (the entry shows once a track is open, and
dev ``run --extras music_room``) and AC-F35-14 (no audio device).

AC-F35-09's first half is the title rig of ``tests/ui/test_music_room_handoff.py`` (Service S,
no title music): the story's ``play music`` reaches F08's ``on_track_started`` through the real
service. The second half and AC-F35-14 are App A (F12's in-process launch, ``scripted_app``):
the CLI parsed and the game started in this process, the page driven from a frame hook."""

import os

import pygame
import pytest

from engine.app import cli
from engine.audio import backend as audio_backend
from engine.audio.backend import open_backend as REAL_OPEN_BACKEND   # before any session's fake
from engine.persist.location import FILE_NAME
from engine.persist.sync import MEMORY
from engine.runtime.commands import PlayMusic
from engine.runtime.musicroom import TRACK_KIND
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.music_room_page import MusicRoomPage
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.nav import InputKind
from tests.app.test_persistence_app import _festivals_file, game_of
from tests.ui.test_music_room_handoff import FESTIVAL, TOP, open_room, room

pytestmark = pytest.mark.display

UNHEARD = (f'lock track festival "Festival Night" file "{FESTIVAL}"\n'
           'lock track credits "Paper Lanterns" file "bgm/omen.ogg" until good\n'
           'label fin:\n    ending good "Good"\n')
GAME = ('lock track festival "Festival Night" file "music/festival.ogg"\n'
        'lock track credits "Paper Lanterns" file "music/credits.ogg" until good\n'
        'lock track theme "Main Theme" file "music/theme.ogg" open\n'
        'label start:\n    play music "music/festival.ogg"\n    "Start."\n'
        '    ending good "Good"\n')


def shown(rig) -> list[str]:
    return [e.id for e in rig.shell.menus.shown("extras")]


def test_ac09_the_entry_shows_once_a_track_is_open_and_run_extras(tmp_path, user_roots,
                                                                   scripted_app):
    # No track open: no Music Room entry (the gallery page still shows).
    pygame.init()
    s, rig, port = room(tmp_path / "heard", title_music=False, top=UNHEARD)
    store = port._interp().persistent
    assert shown(rig) == ["gallery"]
    s.feed(PlayMusic(FESTIVAL, True, 100, None, None, False, None, False))
    s.run(0.2)                                      # the story started it: heard for good
    assert store.unlocked(TRACK_KIND) == ("festival",) and shown(rig) == ["gallery", "music_room"]
    screen, page = open_room(rig)
    assert [page.row_texts(i) for i in range(2)] == [("1", "Festival Night"), ("2", "???")]
    store.register_kind("ending", revocable=True)   # as the Interpreter does (F19)
    assert not port.is_open("credits")
    store.unlock("ending", "good")                  # until good: open while it is reached
    assert port.is_open("credits")
    # An open track: the entry shows from the start.
    s2, rig2, port2 = room(tmp_path / "open", title_music=False, top=TOP)
    assert shown(rig2) == ["gallery", "music_room"]
    assert rig2.shell.open_extras("music_room", by=InputKind.KEYS).page_id == "music_room"
    pygame.quit()

    # run --extras music_room: every track open, nothing written.
    game = game_of(tmp_path / "game", GAME)
    data = _festivals_file(game)
    path = game / "persistent" / FILE_NAME
    stamp = os.stat(path).st_mtime_ns
    found: dict = {}

    def look(app):
        top = app.screens.top
        if found or app.loading or app.persist is None or not isinstance(top, GameMenuScreen):
            return
        page = top.page
        found.update(mode=app.persist.mode, page=top.page_id, kind=type(page),
                     stack=[type(s) for s in app.screens],
                     open=[page.port.is_open(t.name) for t in page.port.tracks()],
                     rows=[page.row_texts(i)[1] for i in range(3)])

    for frame in range(2, 60):
        scripted_app.at(frame, look)
    scripted_app.quit_frame = 60
    assert cli.main(["run", str(game), "--extras", "music_room"]) == 0
    assert found == {"mode": MEMORY, "page": "music_room", "kind": MusicRoomPage,
                     "stack": [TitleScreen, GameMenuScreen], "open": [True, True, True],
                     "rows": ["Festival Night", "Paper Lanterns", "Main Theme"]}
    assert path.read_bytes() == data and os.stat(path).st_mtime_ns == stamp


@pytest.mark.mixer
def test_ac14_no_audio_device_the_room_works_silently(tmp_path, user_roots, scripted_app,
                                                      monkeypatch):
    from engine.audio.backend import NullMixer

    game = game_of(tmp_path, GAME)
    monkeypatch.setenv("SDL_AUDIODRIVER", "f08_none")
    monkeypatch.setattr(audio_backend, "open_backend", REAL_OPEN_BACKEND)
    found: dict = {}

    def look(app):
        top = app.screens.top
        if found or app.loading or not isinstance(top, GameMenuScreen) \
                or not isinstance(top.page, MusicRoomPage):
            return
        page, player = top.page, top.page.player
        steps = [player.pick(0), player.current]
        player.toggle()                             # pause
        steps.append(player.paused)
        player.toggle()                             # resume
        steps.append(player.paused)
        steps += [player.next(), player.current, player.previous(), player.current]
        player.toggle_mode()
        steps.append(player.repeat)
        for _ in range(5):
            page.update(1 / 60)
        found.update(backend=type(app.audio.backend), steps=steps, fill=page.bar_fill(),
                     length=page.port.handle().length())
        top.close_page()                            # leave: no title music to give back

    for frame in range(2, 60):
        scripted_app.at(frame, look)
    scripted_app.quit_frame = 60
    assert cli.main(["run", str(game), "--extras", "music_room"]) == 0
    assert found == {"backend": NullMixer, "fill": 0.0, "length": None,
                     "steps": [True, 0, True, False, True, 1, True, 0, True]}

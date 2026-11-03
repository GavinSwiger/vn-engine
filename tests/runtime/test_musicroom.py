"""F35 step 1 — the music room's tracks at run time (``runtime/musicroom.py``): AC-F35-03
(``heard`` records a default-rule track once, through F08's ``on_track_started``) and
AC-F35-04 (``is_open``).

Tracks are plain declaration stand-ins (step 2 parses ``lock track``); AC-03 drives F08's
Service S (FakeMixer, fake clock) so the story/holder split and a restore are F08's own."""

from dataclasses import dataclass

from engine.runtime.audio import AudioState, MusicEntry
from engine.runtime.commands import AudioRestore, PlayMusic, QueueMusic
from engine.runtime.endings import ENDING_KIND
from engine.runtime.musicroom import TRACK_KIND, TrackIndex, heard, register
from engine.runtime.persistent import PersistentStore
from tests.audio.conftest import make_service

FESTIVAL, OMEN, SHRINE = "bgm/festival.ogg", "bgm/omen.ogg", "bgm/shrine_steps.ogg"


@dataclass(frozen=True)
class Decl:
    name: str
    title: str
    file: str
    open: bool = False
    until: tuple[str, ...] = ()


@dataclass(frozen=True)
class Program:
    tracks: tuple[Decl, ...]


PROGRAM = Program((
    Decl("main_theme", "Main Theme", SHRINE, open=True),
    Decl("festival", "Festival Night", FESTIVAL),
    Decl("credits", "Paper Lanterns", OMEN, until=("good", "true")),
    Decl("rain", "Rain", "bgm/rain.ogg"),
))


def PM(file: str) -> PlayMusic:
    return PlayMusic(file, True, 100, None, None, False, None, False)


def test_ac03_heard_records_default_rule_tracks_once(tmp_path):
    store = PersistentStore.with_data(unlocks={ENDING_KIND: ["good", "true"]})
    index = register(store, PROGRAM)
    assert [t.name for t in index] == ["main_theme", "festival", "credits", "rain"]

    # The function itself: unlock True then False; other rules and files record nothing.
    assert heard(store, index, FESTIVAL) is True
    assert heard(store, index, FESTIVAL) is False
    for file in (SHRINE, OMEN, "bgm/unknown.ogg", "BGM/festival.ogg"):
        assert heard(store, index, file) is False, file
    assert store.unlocked(TRACK_KIND) == ("festival",)
    assert not store.is_revocable(TRACK_KIND)
    store.reset()                                           # F16 "delete persistent data"
    assert store.unlocked(TRACK_KIND) == ()

    # Through F08: a holder's track records nothing; the story's play / queue / restore do.
    s = make_service(tmp_path)
    s.add("bgm/rain.ogg", (tmp_path / "game" / "audio" / "sfx" / "rain.ogg").read_bytes(), 2.0)
    s.service.on_track_started = lambda file: heard(store, index, file)
    handle = s.service.take_music("music_room")
    handle.play(FESTIVAL, fadeout=0.0)
    s.run(0.2)
    assert store.unlocked(TRACK_KIND) == ()
    handle.release()
    s.feed(AudioRestore(AudioState((MusicEntry(FESTIVAL, True, 100),)), "restore"))
    s.run(1.5)
    # A restored save's music: here the holder's own file, still fading, which the story
    # now plays (F08's same-track rule continues it; still a story start).
    assert store.unlocked(TRACK_KIND) == ("festival",)
    s.feed(PM(OMEN), QueueMusic("bgm/rain.ogg", True, 100, None))
    s.run(4.5)                                              # omen (3 s, until) → rain
    assert store.unlocked(TRACK_KIND) == ("festival", "rain")
    assert [n for k, n in store.take_new_unlocks() if k == TRACK_KIND] == ["festival", "rain"]

    # A track added in an update: only its known name counts; F39's second register.
    again = register(store, Program(PROGRAM.tracks[:2]))
    assert again.has("festival") and not again.has("rain") and not again.has(3)


def test_ac04_is_open_table():
    rows = [  # (heard, endings, relock ending, open: main_theme, festival, credits, rain)
        ((), (), None, (True, False, False, False)),
        (("festival",), (), None, (True, True, False, False)),
        ((), ("good",), None, (True, False, False, False)),
        ((), ("good", "true"), None, (True, False, True, False)),
        ((), ("true", "good", "sad"), None, (True, False, True, False)),
        ((), ("good", "true"), "true", (True, False, False, False)),
        (("credits", "main_theme", "rain"), (), None, (True, False, False, True)),
    ]
    for tracks, endings, relock, expected in rows:
        store = PersistentStore.with_data(unlocks={TRACK_KIND: list(tracks),
                                                   ENDING_KIND: list(endings)})
        store.register_kind(ENDING_KIND, revocable=True)
        index = register(store, PROGRAM)
        if relock is not None:
            assert store.relock(ENDING_KIND, relock)        # lock ending closes it again
        row = (tracks, endings, relock)
        got = tuple(index.is_open(store, name)
                    for name in ("main_theme", "festival", "credits", "rain"))
        assert got == expected, row
        assert tuple(index.is_open(store, info) for info in index) == expected, row
        assert [t.name for t in index.open_tracks(store)] == [
            name for name, ok in zip(("main_theme", "festival", "credits", "rain"),
                                     expected) if ok], row
        assert not index.is_open(store, "nope") and not index.is_open(store, 3)  # type: ignore
    other = TrackIndex.build(PROGRAM)                       # another index's info: not ours
    store = PersistentStore.with_data()
    assert not register(store, PROGRAM).is_open(store, other.get("main_theme"))  # type: ignore

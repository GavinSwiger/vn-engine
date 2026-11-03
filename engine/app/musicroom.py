"""``install_music_room``: F35's Music Room wired into one launch (F35 ``SPEC.md`` §2
PR-F35-02, 03, 05, 06; §5.1, §5.2; F34–F37 ``07-architecture-review.md`` I-5, I-6).

Why this module exists: the Music Room page (``ui/builtin/music_room_page.py``) reads the
story only through a ``MusicRoomPort``, because ``ui`` never imports ``script``, ``runtime``
or ``audio``. ``AppMusicRoomPort`` is that port over the running story and the shell:

- ``tracks()`` / ``is_open(name)``: ``Program.tracks`` as ``runtime/musicroom.py``'s
  ``TrackIndex``, read from the live interpreter through ``app.story`` on every call, so
  F39's reload is followed (a new program registers the ``"track"`` kind again, with its own
  ``known``). Under dev ``run --extras`` every track counts as open (PR-F35-06).
- ``handle()``: the title's music handle (``GameShell.room_music``), taken once per opening
  of the page and kept until ``leave()``. It is wrapped so the port knows whether the room
  played anything; a released (inert) handle is fine everywhere (07 I-5).
- ``leave()``: the page closed. When the room played a track (or the title has no music of
  its own) the shell's ``resume_title_music`` gives the stream back: the title track starts
  again, or the handle is released. It does nothing once the title is going (a replay's cut,
  a quit; I-5). When the room played nothing the title music simply goes on.

``install_music_room(app, interp)`` (``install_story``, after ``install_extras`` and the
gallery, before ``install_settings_ui``): registers the ``"track"`` kind (``register``:
``known`` = the declared names, ``replay_keeps``; before F34's ``preview_all``, I-6), sets
F08's ``AudioService.on_track_started`` to ``heard`` (the story started a file: each
default-rule track of it opens for good), and adds the one Extras row: id ``music_room``,
shown once a track is open, kind ``"track"``, names every declared track.

This module imports ``engine.script`` only for type checking.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from engine.app.extras import add_extras_page
from engine.runtime.musicroom import TRACK_KIND, TrackIndex, TrackInfo, heard, register
from engine.ui.builtin.music_room_page import HEADING, MusicRoomPage
from engine.ui.menus import MenuEntry

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.interpreter import Interpreter
    from engine.ui.shell import GameShell


class RoomHandle:
    """The shell's music handle as the page uses it, noting whether the room played."""

    __slots__ = ("inner", "played")

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.played = False

    def play(self, file: str, *, loop: bool = True, fadein: float = 0.0,
             fadeout: float = 0.5, volume: int = 100, start: float | None = None) -> None:
        self.played = True
        self.inner.play(file, loop=loop, fadein=fadein, fadeout=fadeout, volume=volume,
                        start=start)

    def stop(self, fadeout: float | None = 0.5) -> None:
        self.inner.stop(fadeout=fadeout)

    def position(self) -> float | None:
        return self.inner.position()

    def length(self) -> float | None:
        return self.inner.length()


class AppMusicRoomPort:
    """The page's ``MusicRoomPort`` (module docstring)."""

    def __init__(self, interp: "Callable[[], Interpreter]", shell: "GameShell", *,
                 all_open: bool = False) -> None:
        self._interp = interp
        self._shell = shell
        self.all_open = all_open
        self._index: TrackIndex | None = None
        self._program: object = None
        self._handle: RoomHandle | None = None
        self._open: tuple[object, int, tuple[TrackInfo, ...]] | None = None

    def index(self) -> TrackIndex:
        """The live program's index; a new program (F39) registers the kind again."""
        interp = self._interp()
        if self._index is None or interp.program is not self._program:
            self._index = register(interp.persistent, interp.program)
            self._program = interp.program
        return self._index

    def tracks(self) -> tuple[TrackInfo, ...]:
        return tuple(self.index())

    def is_open(self, name: str) -> bool:
        index = self.index()
        if self.all_open:
            return index.has(name)
        return index.is_open(self._interp().persistent, name)

    def open_tracks(self) -> tuple[TrackInfo, ...]:
        """The open tracks in order; kept until the store's unlocks or the program change
        (the Extras entry asks every frame)."""
        index = self.index()
        if self.all_open:
            return tuple(index)
        store = self._interp().persistent
        kept = self._open
        if kept is not None and kept[0] is index and kept[1] == store.unlocks_gen:
            return kept[2]
        found = index.open_tracks(store)
        self._open = (index, store.unlocks_gen, found)
        return found

    def heard(self, file: str) -> bool:
        """F08's ``on_track_started``: the story started ``file``."""
        return heard(self._interp().persistent, self.index(), file)

    def handle(self) -> RoomHandle | None:
        if self._handle is None:
            inner = self._shell.room_music()
            if inner is None:
                return None
            self._handle = RoomHandle(inner)
        return self._handle

    def leave(self) -> None:
        handle, self._handle = self._handle, None
        played = handle is not None and handle.played
        if played or self._shell.title_music_file() is None:
            self._shell.resume_title_music()


def install_music_room(app: "App", interp: "Interpreter") -> AppMusicRoomPort:
    """The Music Room's port, the ``"track"`` kind, the heard hook and its one Extras row
    (module docstring). After ``install_extras``, before ``preview_all``."""

    def live() -> "Interpreter":
        story = getattr(app, "story", None)
        found = getattr(story, "interp", None)
        return found if found is not None else interp

    port = AppMusicRoomPort(live, app.shell,                       # type: ignore[arg-type]
                            all_open=getattr(app, "extras_page", None) is not None)
    port.index()                                                    # registers "track" (I-6)
    audio = getattr(app, "audio", None)
    if audio is not None:
        audio.on_track_started = port.heard
    add_extras_page(app, MenuEntry(HEADING, page=lambda host: MusicRoomPage(port),
                                   visible=lambda: bool(port.open_tracks())),
                    kind=TRACK_KIND, names=lambda: [t.name for t in port.index()])
    return port


__all__ = ["AppMusicRoomPort", "RoomHandle", "install_music_room"]

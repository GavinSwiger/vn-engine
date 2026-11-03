"""One helper child per Studio window, shared by its pages (F47 ``04-technical.md`` §3.1, §7.3,
§11; PR-F47-12, PR-F47-13; AC-F47-12, 21).

Why this module exists: the Database plays sounds and shows thumbnails, Game settings asks
for stills, and the form pickers do both, but a window runs one ``HelperRunner`` (one warm
child, joined to the window's poll loop with ``win.join_runner``). ``hub_for(win)`` makes it
on first use; pages ``listen`` for the replies of the ops they asked for.

- **Sounds.** ``play(ref, owner)`` plays one sound at a time; ``stop_sound`` stops it
  (switching tab, file or category). ``playing`` is the ref playing (None after a stop, a
  failure or the sound's end); listeners hear ``("play", reply)``.
- **Thumbnails.** ``ThumbLoader`` gives a ``tk.PhotoImage`` per (ref, size): a PNG or GIF is
  decoded in-process (``views.read_asset``, subsampled to fit), anything else (JPEG, WebP)
  comes from the helper, cached by its ``ThumbCache`` (file size and modification time).

``make_runner`` is the factory tests replace with a fake (``helperrunner.HelperRunnerLike``).
Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engine.tools.editor.helperrunner import HelperReply, HelperRunner, file_stamp
from engine.tools.editor.views import read_asset, thumbnail_step

CANT_PLAY = "This sound can't be played: {reason}"
PLAYING = "Playing {name}…"


def make_runner(game_dir: Path) -> Any:
    """The window's helper runner (tests replace this)."""
    return HelperRunner(game_dir)


class HelperHub:
    """The window's helper runner and who listens to its replies."""

    def __init__(self, win: Any) -> None:
        self.win = win
        self.runner = make_runner(win.paths.root)
        self.listeners: list[Callable[[HelperReply], object]] = []
        self.playing: str | None = None
        self._play_serial: int | None = None
        self._ends_at: float | None = None
        win.join_runner(self.runner, self._on_events)

    def listen(self, callback: Callable[[HelperReply], object]) -> None:
        self.listeners.append(callback)

    def _on_events(self, events: list) -> None:
        for reply in events:
            if not isinstance(reply, HelperReply):
                continue
            if reply.op in ("play", "stop") and reply.serial == self._play_serial:
                if reply.op == "play" and reply.ok:
                    seconds = reply.seconds
                    self._ends_at = None if seconds is None else time.monotonic() + seconds
                else:
                    self.playing = None
            for callback in list(self.listeners):
                callback(reply)
        if self.playing is not None and self._ends_at is not None \
                and time.monotonic() >= self._ends_at:
            self.playing = None                     # the sound ended by itself
            self._ends_at = None
            for callback in list(self.listeners):
                callback(HelperReply("ended", -1, True))

    def play(self, ref: str) -> int:
        """Play ``ref`` (``audio/…``); any other sound stops."""
        self.playing = ref
        self._ends_at = None
        self._play_serial = self.runner.play(ref)
        return self._play_serial

    def stop_sound(self) -> None:
        """Stop the playing sound (nothing is sent when nothing can be playing)."""
        if self.playing is None and self._play_serial is None:
            return
        self.playing = None
        self._ends_at = None
        serial = self.runner.stop_sound()
        if serial is not None:
            self._play_serial = serial


def hub_for(win: Any) -> HelperHub:
    """The window's ``HelperHub``, made on first use."""
    hub = getattr(win, "helper_hub", None)
    if hub is None:
        hub = win.helper_hub = HelperHub(win)
    return hub


class ThumbLoader:
    """``tk.PhotoImage`` thumbnails fitting ``size`` px for image refs (module docstring).
    ``get(ref)`` returns the image, or None while the helper works on it (then
    ``on_ready(ref)`` runs when it arrives) or when the file can't be shown."""

    def __init__(self, win: Any, master: tk.Misc, size: int,
                 on_ready: Callable[[str], object]) -> None:
        self.win = win
        self.master = master
        self.size = size
        self.on_ready = on_ready
        self.cache: dict[tuple[str, object], tk.PhotoImage | None] = {}
        self._listening = False

    def get(self, ref: str) -> tk.PhotoImage | None:
        stamp = file_stamp(self.win.paths.root, ref)
        key = (ref, stamp)
        if key in self.cache:
            return self.cache[key]
        lower = ref.lower()
        if lower.endswith((".png", ".gif")):
            image = self._local(ref)
            self.cache[key] = image
            return image
        hub = hub_for(self.win)
        if not self._listening:
            hub.listen(self._reply)
            self._listening = True
        reply = hub.runner.thumb(ref, self.size)
        if reply is None:
            return None
        image = self._decode(reply)
        self.cache[key] = image
        return image

    def _local(self, ref: str) -> tk.PhotoImage | None:
        info = read_asset(self.win.paths, ref)
        if info.data is None or info.width is None or info.height is None:
            return None
        import base64
        try:
            full = tk.PhotoImage(master=self.master,
                                 data=base64.b64encode(info.data).decode("ascii"))
        except tk.TclError:
            return None
        step = thumbnail_step(info.width, info.height, (self.size, self.size))
        return full if step == 1 else full.subsample(step)

    def _decode(self, reply: HelperReply) -> tk.PhotoImage | None:
        if not reply.ok or not reply.data:
            return None
        try:
            return tk.PhotoImage(master=self.master, data=reply.data)
        except tk.TclError:
            return None

    def _reply(self, reply: HelperReply) -> None:
        if reply.op != "thumb" or reply.ref is None:
            return
        stamp = file_stamp(self.win.paths.root, reply.ref)
        self.cache[(reply.ref, stamp)] = self._decode(reply)
        self.on_ready(reply.ref)


__all__ = ["CANT_PLAY", "HelperHub", "PLAYING", "ThumbLoader", "hub_for", "make_runner"]

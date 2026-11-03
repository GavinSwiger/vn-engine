"""``AudioService``: the one owner of what the player hears (F08 ``04-technical.md`` §5.2, §7.1,
§7.6, §7.8, §7.10; ``07`` I-4, I-8; ``docs/architecture.md`` "Audio").

Why this module exists: the runtime only holds audio commands in a line's burst (invariant
5); this service obeys them through one handler each, keeps its own model of what is audible,
and drives SDL_mixer only through a ``MixerBackend`` (``PygameMixer``, or ``NullMixer`` with
W30 when there is no device; a fake in tests). It is ``App.audio``, built once at bootstrap
because F10's title music comes before any story (I-8); headless runs never build it.
``app``'s ``install_audio`` calls ``register`` (``audio`` never imports ``app``, I-8, so the
router is typed by the one method used). Main thread only; the clock is the App's.

Built so far: story effects (step 4: ``PlaySound``, ``StopSound``; ``effects.py``), music
(step 5: ``PlayMusic``, ``QueueMusic``, ``StopMusic``; ``music.py``), voice on channel 0
(step 6: ``PlayVoice``, ``EndVoice``, ``StopVoice``, ``voice_playing``,
``set_voice_sustain``), and step 7: ``AudioRestore`` (reconcile, §7.6: music, effects, and
voice), skip (``set_skipping``: fades capped at 0.2 s, skipped one-shots and voices
ignored), the background rules (``set_background`` and the focus and minimize events, §7.8),
and the seams ``play_ui`` (UI channels 2–4), ``replay_voice`` and ``stop_replay`` (F13;
``stop_replay`` came with step 12, F13 ``07`` I-5), ``take_music``,
``on_track_started``, ``stop_story_audio``, and ``set_volumes``. Step 9: effects, voice
lines, and UI sounds decode on the ``SoundLoader``'s worker (§7.3, I-5); ``update`` plays
each finished decode first, and ``shutdown`` waits at most 1 s for it and closes the mixer
only under the loader's lock. Step 10: loop points (``oggloop.LoopPoints``, the session's tag
cache over ``[audio.loop_start]``): music plays the file with ``LOOPSTART``/``LOOPLENGTH``
written into its header and loops natively; a looping effect queues its tail; ``from`` and
``from current`` (``PlayMusic.start``/``from_current``) restart the track at that position
after the old one's fade-out. Step 11: device loss and ``set_mono`` (below). F06 step 2:
``play_blip`` on channel 1 (``effects.BlipChannel``; pitch variants built by the loader's
worker); a reopen drops the blip playing, the pending one, and the ``("blip", …)`` entries.
F23's audio seam (``07`` C4, I-4): ``play_ui(owner=)`` and ``stop_ui(fadeout, *, owner)``,
which fades only that owner's UI sounds. F15 (``07`` I-3): ``set_skipping(False,
resume=sid)`` plays the voice of line ``sid`` that skipping held back. F35 (music room):
``MusicHandle.play(start=)`` starts a track again at an offset, ``length()`` reads the
playing track's length, and ``stop(None)`` fades over ``[audio] music_fadeout``.

**Device loss** (§7.9; R3, R5; PR-F08-18, 19): an ``AUDIODEVICEREMOVED`` or ``ADDED`` event
for an output device (``iscapture == 0``; pygame doesn't say which device is ours) sets
``reopen_at = clock + 0.5``, so a burst of events gives one reopen. The first ``update`` past
it reopens the device under the loader's lock (I-5: never under a decode; when a decode holds
the lock for ``REOPEN_LOCK_WAIT_S`` the next frame tries again), bumps ``mixer_gen`` (a result
decoded for the old mixer never plays), drops every sound and the ``("snd", …)`` and
``("blip", …)`` cache entries, and rebuilds: the music at its position (taken before the
reopen) and the story's loops; one-shots, the voice, UI sounds, and blips are dropped. If no
device opens, the service goes on with ``NullMixer`` and one W30 "stopped working"; story
commands keep updating the model (``story_music``, ``story_sounds``), and only an ``ADDED``
event retries; when it opens, the story's looping track starts with the restore fade-in (a
``take_music`` holder's looping track instead) and the story's loops restart. A game that
started with no device (``NullMixer`` from ``open_backend``) tries to open one on each
``ADDED`` event, debounced the same way (step 12, ``open_device``): when one opens it plays as
after a lost device comes back; when none does it stays silent with no second W30.
``set_mono`` (F16, PR-F08-32) reopens the device the same way with 1 output channel (2 when
off).

**Takeover** (§7.1): ``take_music`` fades the story's music out over ``restore_fadeout`` and
gives the stream to the holder. While it is taken, story commands only update the story's
music sequence (as ``AudioState.music``); ``release()`` reconciles the stream to it with the
restore fades (§7.6), so the story's looping track comes back.

**Time** (§7.8): the service's timers (ramps, watchdogs, the pass-end switch) run on the
App's monotonic clock minus the time audio spent paused, never on ``GameTime``, which stops
while the window is minimized. While paused, service time stands still, so a ramp paused
halfway ends as late as the pause lasted, as the audio it shapes does.

**Background** (§7.8, PR-F08-25, 26): ``handle_event`` watches the window's focus and
minimize events without consuming them. Audio pauses (``pause_all``) when the window is
unfocused and ``play_unfocused`` is off, or minimized and ``play_minimized`` is off, and
resumes when neither holds. Both are on by default (``[audio]``; F16's settings win through
``set_background``), so by default nothing pauses. A sound started while paused is paused
again at once (SDL plays a new sound even after a pause).
"""

import time
from collections.abc import Callable
from typing import Any, Protocol

from engine.audio.backend import (W30_STOPPED, DeviceError, MixerBackend, NullMixer,
                                  device_change, open_backend, open_device, window_change)
from engine.audio.effects import BlipChannel, EffectSlots, UiPool, VoiceChannel
from engine.audio.limits import REOPEN_DEBOUNCE_S
from engine.audio.loader import STOP_WAIT_S, SoundLoader
from engine.audio.music import MusicPlayer, Track
from engine.audio.oggloop import LoopPoints
from engine.audio.reading import AudioLog, AudioReader
from engine.audio.volume import Volumes, curve
from engine.core.config_schema import AudioConfig
from engine.core.logsetup import get_logger
from engine.core.lru import SizedLru
from engine.core.paths import GamePaths
from engine.runtime.audio import MusicEntry
from engine.runtime.commands import (AudioRestore, EndVoice, PlayMusic, PlaySound, PlayVoice,
                                     QueueMusic, StopMusic, StopSound, StopVoice)
from engine.runtime.limits import MUSIC_SEQUENCE_MAX

STORY_AUDIO_FADEOUT_S = 0.5           # stop_story_audio's default (PR-F08-30)
HANDLE_FADEOUT_S = 0.5                # MusicHandle.play/stop's default fade-out
UI_VOLUME_DEFAULT = 100               # play_ui's default relative volume
REOPEN_LOCK_WAIT_S = 0.1              # a reopen waits this long for a decode, then next frame

_log = get_logger("audio")


class CommandRegistry(Protocol):
    """What ``register`` needs of ``app``'s ``CommandRouter`` (I-8: no ``app`` import)."""

    def register(self, command_type: type, handler: Callable[[Any], None]) -> None: ...


class MusicHandle:
    """A screen's hold on the music stream (``take_music``; F10's title, F23, F35). Inert
    once released or replaced by a newer ``take_music``."""

    def __init__(self, service: "AudioService", owner: str) -> None:
        self._service = service
        self.owner = owner
        self._looping: tuple[str, int] | None = None   # the looping track it plays (step 11)

    @property
    def active(self) -> bool:
        return self._service._taker is self and not self._service._closed

    def play(self, file: str, *, loop: bool = True, fadein: float = 0.0,
             fadeout: float = HANDLE_FADEOUT_S, volume: int = 100,
             start: float | None = None) -> None:
        """Play ``file`` (inside ``audio/``) on the stream: the playing track fades out over
        ``fadeout``, then this one fades in over ``fadein``. The same file with the same
        ``loop`` continues (SR-F08-07) unless ``start`` is given (F35): then it starts again
        at ``start`` seconds (0.0: from the beginning), as ``play music … from`` does. A
        missing file is the W26 log line and silence."""
        if not self.active:
            return
        self._looping = (file, volume) if loop else None
        service = self._service
        music = service.music
        track = Track(file, loop, volume, music.resolve_fadein(fadein),
                      start=max(0.0, start or 0.0), story=False)
        music.play(track, fadeout=music.resolve_fadeout(fadeout), restart=start is not None,
                   ramp=None, now=service.now())
        service._repause()

    def stop(self, fadeout: float | None = HANDLE_FADEOUT_S) -> None:
        """Fade the holder's track out over ``fadeout`` (None: ``[audio] music_fadeout``)."""
        if self.active:
            self._looping = None
            music = self._service.music
            music.stop(music.resolve_fadeout(fadeout), self._service.now())

    def _resume(self) -> None:
        """The device is back after a loss (step 11): its looping track starts again."""
        looping = self._looping
        if looping is not None:
            self.play(looping[0], loop=True, fadein=self._service.cfg.restore_fadein,
                      fadeout=0.0, volume=looping[1])

    def position(self) -> float | None:
        """The holder's track position in seconds; None when silent or not the holder."""
        if not self.active:
            return None
        return self._service.music.position(self._service.now())

    def length(self) -> float | None:
        """F35: the length in seconds of the track playing on the stream, once it is read
        (its header's); None before anything plays, when silent, for a header with no length
        (MP3), or not the holder. While a fade-out runs it is still the fading track's."""
        if not self.active:
            return None
        current = self._service.music.current
        return None if current is None else current.length

    def release(self) -> None:
        """The holder is done: the story's music comes back (reconcile, §7.6)."""
        if self.active:
            self._service._release_music()


class AudioService:
    """``App.audio``. ``paths``: the game folder (None: every file is missing); ``cache``: the
    App's shared ``SizedLru`` (``assets.cache``); ``cfg``: ``[audio]``; ``backend``: None
    opens the device (``open_backend``); ``clock``: the App's monotonic clock; ``frame``: the
    App's ``GameTime.frame`` for the cache's recency (I-4); ``loader_threaded``: None
    decodes on the worker when ``LOADER_THREADED`` and the backend's decode is worth it
    (tests pass True or False); ``open_device``: opens a first device when the game started
    without one and one is plugged in (step 12; ``DeviceError`` when none opens)."""

    def __init__(self, paths: GamePaths | None, cache: SizedLru, cfg: AudioConfig, *,
                 backend: MixerBackend | None = None,
                 clock: Callable[[], float] = time.perf_counter,
                 frame: Callable[[], int] = lambda: 0,
                 loader_threaded: bool | None = None,
                 open_device: Callable[[int], MixerBackend] = open_device) -> None:
        self.backend: MixerBackend = backend if backend is not None else open_backend()
        self._open_device = open_device
        self.cfg = cfg
        self.cache = cache
        self.log = AudioLog()
        self.reader = AudioReader(paths, self.log)
        self.volumes = Volumes(cfg.master_volume, cfg.music_volume, cfg.sound_volume,
                               cfg.voice_volume)
        self._clock = clock
        self.loops = LoopPoints(cfg.loop_start, self.log)
        self.loader = SoundLoader(self.backend, self.reader, cache, frame=frame,
                                  threaded=loader_threaded, loop_start=self.loops.sound_start)
        self.effects = EffectSlots(self.backend, self.reader, cache, self.loader,
                                   sound_gain=lambda: self.volumes.sound_gain(),
                                   default_fadein=cfg.sound_fadein,
                                   default_fadeout=cfg.sound_fadeout)
        self.voice = VoiceChannel(self.backend, self.reader, cache, self.loader,
                                  voice_gain=lambda: self.volumes.voice_gain())
        self.pool = UiPool(self.backend, self.reader, cache, self.loader,
                           sound_gain=lambda: self.volumes.sound_gain())
        self.blip = BlipChannel(self.backend, self.reader, cache, self.loader,
                                sound_gain=lambda: self.volumes.sound_gain())
        self.music = MusicPlayer(self.backend, self.reader,
                                 music_gain=lambda: curve(self.volumes.master)
                                 * curve(self.volumes.music),
                                 default_fadein=cfg.music_fadein,
                                 default_fadeout=cfg.music_fadeout,
                                 loop_point=self.loops.music,
                                 on_start=self._track_started)
        self.on_track_started: Callable[[str], None] | None = None      # F35 (PR-F08-29)
        self.story_music: tuple[MusicEntry, ...] = ()   # the story's sequence (takeover)
        self.story_sounds: dict[str, int] = {}          # the story's loops: file -> volume
        # Device loss and mono (step 11, §7.9): the backend a reopen opens again (None: the
        # game started with no device), whether it is lost (``backend`` is then a
        # NullMixer), and when the debounced reopen is due (the App's clock).
        self._device: MixerBackend | None = None if self.backend.silent else self.backend
        self.device_lost = False
        self.mono = False
        self._reopen_at: float | None = None
        self.skipping = False
        # Background (§7.8): the policy (F16's two settings) and the window's state.
        self.play_unfocused = cfg.play_unfocused
        self.play_minimized = cfg.play_minimized
        self.unfocused = False
        self.minimized = False
        self.paused = False
        self._paused_since: float | None = None   # clock time the pause began
        self._paused_total = 0.0                  # clock seconds spent paused before it
        self._taker: MusicHandle | None = None
        self._closed = False

    # --- wiring ----------------------------------------------------------------------------

    def register(self, router: CommandRegistry) -> None:
        """One handler for each of the nine audio commands (``install_audio``)."""
        router.register(PlaySound, self._play_sound)
        router.register(StopSound, self._stop_sound)
        router.register(PlayMusic, self._play_music)
        router.register(QueueMusic, self._queue_music)
        router.register(StopMusic, self._stop_music)
        router.register(AudioRestore, self._restore)
        router.register(PlayVoice, self._play_voice)
        router.register(EndVoice, self._end_voice)
        router.register(StopVoice, self._stop_voice)

    def now(self) -> float:
        """The service's time (§7.8): the App's clock minus the time spent paused."""
        return self._service_time(self._clock())

    def _service_time(self, clock_now: float) -> float:
        if self._paused_since is not None:
            clock_now = min(clock_now, self._paused_since)
        return clock_now - self._paused_total

    # --- frame slots (§7.10; 07 §2.10 item 1) ------------------------------------------------

    def handle_event(self, raw: object) -> bool:
        """Sees every raw pygame event first; True consumes it. Consumes music-end events
        and audio-device events (§7.9: an output device's schedules the reopen, 0.5 s after
        the last one; while the device is lost, or there was none at the start, only ``ADDED``
does); watches focus and
        minimize events without consuming them (§7.8)."""
        if self.backend.is_music_end(raw):
            if not self._closed:
                self.music.on_end_event(self.now())
            return True
        device = device_change(raw)
        if device is not None:
            what, capture = device
            if not capture and not self._closed and (
                    what == "added" or (self._device is not None and not self.device_lost)):
                self._reopen_at = self._clock() + REOPEN_DEBOUNCE_S
            return True
        change = window_change(raw)
        if change is not None:
            what, on = change
            if what == "unfocused":
                self.unfocused = on
            else:
                self.minimized = on
            self._apply_pause()
        return False

    def update(self, now: float) -> None:
        """Every frame after the commands are dispatched, in error mode too, and on each
        minimized wake (I-4): the decodes that finished start playing (I-5: only here, on the
        main thread), the music's watchdogs and ramps, the effects' and the voice's ramps,
        and ended effects, voices, UI sounds, and blips free their channels. ``now`` is the App's
        clock; the service subtracts the paused time. A reopen that is due runs first
        (§7.9)."""
        if self._closed:
            return
        if self._reopen_at is not None and now >= self._reopen_at:
            self._reopen(now)
        now = self._service_time(now)
        if self.loader.update(now):
            self._repause()
        self.music.update(now)
        self.effects.update(now)
        self.voice.update(now)
        self.pool.update(now)
        self.blip.update()

    def shutdown(self, timeout: float = STOP_WAIT_S) -> None:
        """``App.run``'s end (a shutdown hook): stop everything and close the device. Safe
        to call twice. The decode worker gets at most ``timeout`` seconds (AC-F08-51); the
        device is closed only under the loader's lock (I-5), so when a decode still runs
        past that, the mixer is left to process exit instead of being closed under it."""
        if self._closed:
            return
        self._closed = True
        self._taker = None
        started = time.perf_counter()
        ended = self.loader.shutdown(timeout)
        self.music.shutdown()
        self.effects.shutdown()
        self.voice.shutdown()
        self.pool.shutdown()
        self.blip.shutdown()
        left = timeout - (time.perf_counter() - started) if ended else 0.0
        if not self.loader.acquire(left):
            _log.debug("a sound was still decoding at shutdown; the mixer is left open")
            return
        try:
            self.backend.shutdown()
        finally:
            self.loader.lock.release()

    # --- seams (§5.2) ----------------------------------------------------------------------

    def play_ui(self, file: str, *, volume: int = UI_VOLUME_DEFAULT,
                owner: str | None = None) -> None:
        """F10/F07/F11 UI sounds (PR-F08-28a): ``file`` (inside ``audio/``) plays once on a
        UI channel 2–4 at ``amp(master, sound, volume)``. Never story state; skip, restore,
        and ``stop_story_audio`` leave it alone. A missing file is the W26 log line and
        silence. ``owner`` (F23 ``07`` C4: ``"minigame"`` for a plugin's one-shots; None,
        the engine's sounds) is what ``stop_ui`` stops by."""
        if self._closed:
            return
        self.pool.play(file, volume, self.now(), owner)
        self._repause()

    def stop_ui(self, fadeout: float, *, owner: str) -> None:
        """F23 (``07`` C4, I-4): ``owner``'s UI sounds ramp to silence over ``fadeout``
        seconds (0: at once) with the engine ramp, then stop; its sounds still decoding never
        play. Every other sound in the pool (the engine's, another owner's) plays on, and
        channel 1 (F06's blips) is never touched. No owner-less form: it would cut the
        engine's own sounds."""
        if not self._closed:
            self.pool.stop(owner, fadeout, self.now())

    def play_blip(self, file: str, *, volume: int = 100, spread: float = 0.0,
                  step: int = 0) -> None:
        """F06 (SPEC §5): one blip of ``file`` (inside ``audio/``) on channel 1, stopping
        the one still sounding, at ``amp(master, sound, volume)``. With ``spread`` > 0 it
        plays variant ``step`` (−2…2, speed ``1 + spread·step/2``). Nothing while skipping.
        A blip not yet decoded plays when it is, if asked for at most 50 ms before; a file
        that is silent (W26) is not read again. Main thread, about 20 µs when cached."""
        if self._closed:
            return
        self.blip.play(file, volume, spread, step, self.now())
        self._repause()

    def replay_voice(self, file: str) -> None:
        """F13's history (PR-F08-28b): ``file`` (inside ``audio/``) plays once on the voice
        channel, replacing any voice. It belongs to no line (``voice_playing(sid)`` is false
        for every line), so no line's advance stops it, and it plays while skipping too."""
        if self._closed:
            return
        self.voice.play(None, file, False, self.now(), replay=True)
        self._repause()

    def stop_replay(self) -> None:
        """F13's history page closed (F13 ``07`` I-5): a ``replay_voice`` that is playing, or
        still decoding, stops at once. A line's voice is left alone, and so is a voice that
        started after the replay."""
        if not self._closed and self.voice.replay:
            self.voice.stop(0.0, self.now())

    def stop_story_audio(self, fadeout: float = STORY_AUDIO_FADEOUT_S) -> None:
        """The story's audio fades out over ``fadeout`` and its target is silence (story
        end, the error screen, F10's return to the title; PR-F08-30). Music a
        ``take_music`` holder plays is not the story's and keeps playing; UI sounds on the
        pool keep playing."""
        if self._closed:
            return
        now = self.now()
        self.story_music = ()
        self.story_sounds = {}
        if self._taker is None:
            self.music.stop(max(0.0, fadeout), now)
        self.effects.stop(None, fadeout, now)
        self.voice.stop(max(0.0, fadeout), now)

    def set_skipping(self, on: bool, *, resume: str | None = None) -> None:
        """F15 (PR-F08-24): while skipping, one-shot effects and the voices of skipped lines
        don't play (a restored line's voice still does), and every music and effect fade —
        restore fades too — is capped at 0.2 s; music and looping effects follow the story,
        so when skipping stops what plays matches the line's state. Starting to skip stops
        a voice that is playing (or still decoding), at once.

        ``resume`` (F15 ``07`` I-3; only with ``on`` False): skip stopped on line ``resume``
        (an unseen line, or a menu's line), so that line keeps its voice: the last
        ``PlayVoice`` ignored while skipping plays now if its sid is ``resume`` and no
        ``PlayVoice``, ``EndVoice``, ``StopVoice``, ``AudioRestore``, or
        ``stop_story_audio`` came after it. Without it (a player's stop) nothing plays."""
        on = bool(on)
        was = self.skipping
        self.skipping = on
        self.music.skipping = on
        self.effects.skipping = on
        self.voice.skipping = on
        self.blip.skipping = on
        if on:
            if not was and not self._closed:
                self.voice.stop(0.0, self.now())
        elif resume is not None and not self._closed:
            self.voice.resume(resume, self.now())
            self._repause()
        else:
            self.voice.skipped = None

    def set_volumes(self, master: int, music: int, sound: int, voice: int) -> None:
        """F16: the four volume settings (0–100); every playing sound gets its new level in
        this call (AC-F08-30)."""
        self.volumes = Volumes(master, music, sound, voice)
        if not self._closed:
            now = self.now()
            self.music.apply_volume(now)
            self.effects.apply_volumes(now)
            self.voice.apply_volume(now)
            self.pool.apply_volumes(now)

    def set_background(self, unfocused: bool, minimized: bool) -> None:
        """F16's "audio when unfocused" and "audio when minimized" (PR-F08-26): whether audio
        keeps playing while the window is unfocused / minimized. Turning one off while that
        holds pauses at once; turning it on resumes."""
        self.play_unfocused = bool(unfocused)
        self.play_minimized = bool(minimized)
        self._apply_pause()

    def set_mono(self, on: bool) -> None:
        """F16 (PR-F08-32, off by default): the device reopens with 1 output channel (2 when
        off) and plays on as after a device reopen (§7.9): the music at its position, the
        story's loops again; one-shots, the voice, UI sounds, and blips are dropped. Without a
        device it applies at the next reopen."""
        on = bool(on)
        if on == self.mono:
            return
        self.mono = on
        if self._closed or self._device is None or self.device_lost:
            return
        clock_now = self._clock()
        if not self._reopen(clock_now):
            self._reopen_at = clock_now      # a decode holds the lock: the next frame

    def voice_playing(self, sid: str | None = None) -> bool:
        """F05, F06, F13, F15: whether a voice is audible now (``sid``: the voice of that
        line, as on ``Say``). False after it ends, is stopped, or the service closed."""
        return not self._closed and self.voice.playing(sid)

    def set_voice_sustain(self, on: bool) -> None:
        """F16 (PR-F08-31, off by default): a voice plays on after its line is advanced,
        until the next voice or ``stop voice``. Applies from the next ``EndVoice``."""
        self.voice.sustain = on

    def take_music(self, owner: str) -> MusicHandle:
        """F10's title, F23, F35 (PR-F08-28c): the story's music fades out over
        ``restore_fadeout`` and the stream is the holder's until ``release()``. A second
        ``take_music`` replaces the holder; the old handle becomes inert."""
        first = self._taker is None
        handle = MusicHandle(self, owner)
        self._taker = handle
        if first and not self._closed:
            self.music.stop(self.music.resolve_fadeout(self.cfg.restore_fadeout), self.now())
        return handle

    def music_taken(self) -> bool:
        return self._taker is not None

    # --- background (§7.8) -----------------------------------------------------------------

    def _apply_pause(self) -> None:
        paused = ((self.unfocused and not self.play_unfocused)
                  or (self.minimized and not self.play_minimized))
        if paused == self.paused or self._closed:
            return
        self.paused = paused
        self.music.paused = paused
        clock_now = self._clock()
        if paused:
            self._paused_since = clock_now
            self.backend.pause_all()
        else:
            since, self._paused_since = self._paused_since, None
            if since is not None:
                self._paused_total += max(0.0, clock_now - since)
            self.backend.resume_all()

    def _repause(self) -> None:
        """Something may have started while paused: SDL plays it, so pause it too."""
        if self.paused and not self._closed:
            self.backend.pause_all()

    # --- device loss and mono (§7.9) ---------------------------------------------------------

    def _reopen(self, clock_now: float) -> bool:
        """§7.9 steps 1–3 (and ``set_mono``; with no device yet, ``open_device`` instead of
        the reopen). False: a decode held the loader's lock for ``REOPEN_LOCK_WAIT_S``; the
        caller tries again on the next frame."""
        device = self._device
        channels = 1 if self.mono else 2
        now = self._service_time(clock_now)
        lost = self.device_lost or device is None
        position = None if lost else self.music.position(now)   # before the stream is gone
        if not self.loader.acquire(REOPEN_LOCK_WAIT_S):
            return False
        self._reopen_at = None
        try:                                        # 1. under the lock (I-5, R3)
            if device is None:                      # started without one (step 12)
                device = self._open_device(channels)
            else:
                device.reopen(channels)
            opened = True
        except DeviceError:
            opened = False
        finally:
            self.loader.lock.release()
        if self._device is None:
            if not opened:
                return True                         # still none: silent, no second W30
            self._device = device
        self.loader.bump_gen()                      # 2. old decodes never play
        self.effects.shutdown()                     # every sound went with the old mixer
        self.voice.shutdown()
        self.pool.shutdown()
        self.blip.shutdown()
        self.loader.discard_sounds()
        if not opened:
            self.music.shutdown()
            self._use(NullMixer())
            self.device_lost = True
            if not lost:                            # one W30 per loss, not per retry
                _log.warning("%s", W30_STOPPED, extra={"code": "W30"})
            return True
        assert device is not None
        self._use(device)
        self.device_lost = False
        if lost:                                    # 3. the music again: from the model
            self.music.shutdown()
            if self._taker is None:
                self._reconcile_music(self.cfg.restore_fadein, 0.0, restored=False)
            else:
                self._taker._resume()
        else:                                       # 3. the music at its position
            self.music.rebuild(position, now)
        self.effects.restart_loops(list(self.story_sounds.items()), now)
        self._repause()
        return True

    def _use(self, backend: MixerBackend) -> None:
        """Every part drives ``backend`` from now on (NullMixer, or the device again)."""
        self.backend = backend
        self.music.backend = backend
        self.effects.backend = backend
        self.voice.backend = backend
        self.pool.backend = backend
        self.blip.backend = backend
        self.loader.set_backend(backend)

    # --- handlers --------------------------------------------------------------------------

    def _play_sound(self, cmd: PlaySound) -> None:
        if cmd.loop:
            self.story_sounds[cmd.file] = cmd.volume
        if not self._closed:
            self.effects.play(cmd, self.now())
            self._repause()

    def _stop_sound(self, cmd: StopSound) -> None:
        if cmd.file is None:
            self.story_sounds = {}
        else:
            self.story_sounds.pop(cmd.file, None)
        if not self._closed:
            self.effects.stop(cmd.file, cmd.fadeout, self.now())

    def _play_voice(self, cmd: PlayVoice) -> None:
        if not self._closed:
            self.voice.play(cmd.sid, cmd.file, cmd.restored, self.now())
            self._repause()

    def _end_voice(self, cmd: EndVoice) -> None:
        if not self._closed:
            self.voice.end(cmd.sid)

    def _stop_voice(self, cmd: StopVoice) -> None:
        if not self._closed:
            self.voice.stop(cmd.fadeout, self.now())

    def _play_music(self, cmd: PlayMusic) -> None:
        self.story_music = (MusicEntry(cmd.file, cmd.loop, cmd.volume),)
        if self._closed or self._taker is not None:
            return
        music = self.music
        track = Track(cmd.file, cmd.loop, cmd.volume, music.resolve_fadein(cmd.fadein),
                      start=cmd.start or 0.0, from_current=cmd.from_current)
        music.play(track, fadeout=music.resolve_fadeout(cmd.fadeout),
                   restart=cmd.restart or cmd.from_current or cmd.start is not None,
                   ramp=None if cmd.fadein is None else music.resolve_fadein(cmd.fadein),
                   now=self.now())
        self._repause()

    def _queue_music(self, cmd: QueueMusic) -> None:
        story = self.story_music
        if story:
            last = story[-1]
            story = story[:-1] + (MusicEntry(last.file, False, last.volume),)
        self.story_music = (story + (MusicEntry(cmd.file, cmd.loop, cmd.volume),)
                            )[-MUSIC_SEQUENCE_MAX:]
        if self._closed or self._taker is not None:
            return
        music = self.music
        music.queue_track(Track(cmd.file, cmd.loop, cmd.volume,
                                music.resolve_fadein(cmd.fadein)), self.now())
        self._repause()

    def _stop_music(self, cmd: StopMusic) -> None:
        self.story_music = ()
        if self._closed or self._taker is not None:
            return
        self.music.stop(self.music.resolve_fadeout(cmd.fadeout), self.now())

    def _restore(self, cmd: AudioRestore) -> None:
        """§7.6: what is audible becomes ``cmd.state``. Music: the sequence's looping track
        (step 1–2; only the model during a takeover). Effects: the state's loops are kept,
        started, or faded out, and one-shots fade out (step 3). Voice: it fades out; the
        restored line's ``PlayVoice(restored=True)`` follows in the burst (step 4). Fades:
        ``restore_fadeout``/``restore_fadein``, the music's and effects' capped at 0.2 s
        while skipping (PR-F08-24 caps music and effects; AC-F08-47 keeps the voice's
        500 ms fade with skipping on). A ``sync``
        (the burst cap dropped commands, F03 insertion 4) uses the play defaults and keeps
        the burst's one-shots and the voice, which belong to the line being shown."""
        self.story_music = cmd.state.music
        self.story_sounds = {entry.file: entry.volume for entry in cmd.state.sounds}
        if self._closed:
            return
        now = self.now()
        cfg = self.cfg
        sync = cmd.reason == "sync"
        effects = self.effects
        if sync:
            effects.reconcile(cmd.state.sounds, fadein=effects.default_fadein,
                              fadeout=effects.default_fadeout, now=now, keep_oneshots=True)
        else:
            effects.reconcile(cmd.state.sounds, fadein=cfg.restore_fadein,
                              fadeout=cfg.restore_fadeout, now=now,
                              restored=cmd.reason == "restore")
            self.voice.stop(cfg.restore_fadeout, now)        # not capped: AC-F08-47
        if self._taker is None:
            if sync:
                self._reconcile_music(None, None, restored=False)
            else:
                self._reconcile_music(cfg.restore_fadein, cfg.restore_fadeout,
                                      restored=cmd.reason == "restore")
        self._repause()

    def _reconcile_music(self, fadein: float | None, fadeout: float | None, *,
                         restored: bool) -> None:
        """§7.6 steps 1–2: ``want`` is the sequence's looping track (the last). The same
        track playing is kept, its volume ramped over the fade-in; else the stream
        switches to ``want``, or stops."""
        music = self.music
        now = self.now()
        want = next((entry for entry in self.story_music if entry.loop), None)
        out = music.resolve_fadeout(fadeout)
        if want is None:
            music.stop(out, now)
            return
        inn = music.resolve_fadein(fadein)
        music.play(Track(want.file, True, want.volume, inn, restored=restored), fadeout=out,
                   restart=False, ramp=inn, now=now)

    def _release_music(self) -> None:
        self._taker = None
        if not self._closed:
            self._reconcile_music(self.cfg.restore_fadein, self.cfg.restore_fadeout,
                                  restored=False)
            self._repause()

    def _track_started(self, track: Track) -> None:
        """A story track started (a first start or a queue transition): F35's hook."""
        callback = self.on_track_started
        if track.story and callback is not None:
            callback(track.file)


__all__ = ["AudioService", "CommandRegistry", "HANDLE_FADEOUT_S", "MusicHandle",
           "REOPEN_LOCK_WAIT_S", "STORY_AUDIO_FADEOUT_S", "UI_VOLUME_DEFAULT"]

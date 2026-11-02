"""The music stream: ``MusicPlayer`` (F08 ``04-technical.md`` §7.1, §7.7, §7.8; TR-F08-02, 03,
06; AC-F08-16 to 22, 38).

Why this module exists: SDL_mixer has one music stream, a one-slot queue, and native fades
that can't be cancelled, and ``load``/``play`` block while a fade-out runs (1.1 s for a 1 s
fade). The story's music needs more: a fade-out then the next track, the same-track rule, a
queue of any length where only the last track loops, gapless pass ends, and robustness
against stale or lost end events. This player keeps the model and drives the stream through
``MixerBackend``'s ``music_*`` calls only:

- **One stream, never blocked.** A new track starts only once nothing is busy: after
  ``music_stop`` (a hard cut) or on the end event of a fade-out (``pending``). The backend's
  ``music_start`` itself calls ``stop()`` and drains end events before ``load`` and ``play``
  (TR-F08-02).
- **Loops are native** (``loops=-1``) for every looping track whose length is known (Ogg,
  Opus, FLAC, WAV), with or without a loop point: SDL_mixer loops those sample-exact. A queue
  transition is not: on pygame-ce 2.5.8 / SDL_mixer 2.8.2 the queued track starts in the
  next 512-frame buffer, after 1–512 frames of silence (measured, ``test_gapless.py``), so
  ``04`` §7.1's pass-by-pass loop would click on every pass. Pass by pass (one SDL play per
  pass, the current track re-armed in the slot) remains only for tracks of unknown length
  (MP3, which W24 already warns about), and a track queued after a native loop switches at
  its pass end (§7.7) or, in the same burst as its ``play``, restarts it once.
- **The slot** (``armed``) holds what plays next: the first queued track; else the current
  track again when it loops pass by pass; else ``SILENT_WAV``, a 1-sample WAV, because
  pygame has no "unqueue".
- **End events** move the model only when the backend agrees: a fade-out ends when nothing is
  busy; a transition is real only when the backend's position was reset since the pass began
  (or the pass's known length has elapsed), so an event posted before a ``music_start`` and
  seen after it changes nothing. A **watchdog** covers lost events: PLAYING but not busy for
  0.5 s is an end; FADING_OUT for the fade + 1 s is a ``music_stop``.
- **Loop points** (F08 step 10, ``oggloop.LoopPoints.music`` as ``loop_point``): the track's
  bytes carry ``LOOPSTART``/``LOOPLENGTH``, so SDL_mixer plays the first pass from 0 and
  every later pass from the loop point, sample-exact (measured: 0 frames at the loop point,
  ``test_loop_points.py``); a once play ignores the tags.
- **Device reopen** (F08 step 11, §7.9): ``rebuild`` starts the playing track again at its
  position on the new device, its queue armed again; a fade-out under way is over.

Volume: the stream's level is ``quantize(c(master) · c(music) · gain)``, where ``gain`` is the
track's ``curve(volume)``, ramped in Python over a same-track ``fadein`` (fades in and out
are native). Times are the service's clock (§7.8), never ``GameTime``. Main thread only.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Final

from engine.audio.backend import DecodeError, MixerBackend
from engine.audio.limits import SAME_BURST_S, SKIP_FADE_CAP_S, SWITCH_LEAD_S
from engine.audio.reading import AUDIO_FOLDER, AudioReader, suffix, w26_not_really
from engine.audio.sniff import Sniffed, declared_seconds, sniff
from engine.audio.volume import curve, quantize
from engine.core.redact import echo

WATCHDOG_S: Final = 0.5               # PLAYING, not busy, no end event: handled as an end
STUCK_FADE_SLACK_S: Final = 1.0       # FADING_OUT this long past the fade: music_stop
SAME_TRACK_FADEIN_S: Final = 0.05     # a same-track restart during a fade-out (§7.1 rule 1)
LATE_SWITCH_FADE_S: Final = 0.05      # §7.7: the pass end was already passed
DAMAGED_SLACK_S: Final = 1.0          # W27: a track that ends this much before its length
_RESET_S: Final = 0.05                # the stream position fell this far behind: a transition
_LENGTH_SLACK_S: Final = 0.25         # or the pass's known length (nearly) elapsed


def _silent_wav() -> bytes:
    """A 48,000 Hz stereo 16-bit WAV of one silent frame."""
    fmt = ((1).to_bytes(2, "little") + (2).to_bytes(2, "little")
           + (48_000).to_bytes(4, "little") + (192_000).to_bytes(4, "little")
           + (4).to_bytes(2, "little") + (16).to_bytes(2, "little"))
    data = b"\0" * 4
    body = (b"WAVE" + b"fmt " + len(fmt).to_bytes(4, "little") + fmt
            + b"data" + len(data).to_bytes(4, "little") + data)
    return b"RIFF" + len(body).to_bytes(4, "little") + body


SILENT_WAV_BYTES: Final = _silent_wav()
SILENT_WAV: Final[Sniffed] = sniff(SILENT_WAV_BYTES, ".wav")       # type: ignore[assignment]


def w27_damaged(file: str, seconds: float) -> str:
    """W27 (``02`` §5.4): the time is m:ss, rounded down."""
    whole = max(0, int(seconds))
    return (f"{echo(AUDIO_FOLDER + file)} is damaged {whole // 60}:{whole % 60:02d} in, so it "
            f"stopped there. Export it again as {echo(suffix(file))}.")


class Phase(Enum):
    SILENT = "silent"
    PLAYING = "playing"
    FADING_OUT = "fading_out"


@dataclass(slots=True, eq=False)
class Track:
    """One track of the music sequence. ``loop`` and ``volume`` as written (the same-track
    rule compares the written ``loop``; only the last track of the sequence really loops);
    ``fadein`` resolved; ``start`` the offset of its first pass; ``from_current``: the
    offset is the old track's position when this one starts. ``story``: a story track (not a
    ``take_music`` holder's), reported to ``on_track_started``; ``restored``: from a
    restore (W29). ``data``, ``length``, ``loop_pt`` are filled when it is read."""

    file: str
    loop: bool
    volume: int
    fadein: float = 0.0
    start: float = 0.0
    from_current: bool = False
    story: bool = True
    restored: bool = False
    data: Sniffed | None = None
    length: float | None = None
    loop_pt: float | None = None


class Armed(Enum):
    """What ``music_arm`` put in SDL's slot."""

    TRACK = "track"           # queue[0]
    PASS = "pass"             # the current track again (pass by pass)
    SILENT = "silent"         # SILENT_WAV


LoopPoint = Callable[[str, Sniffed], tuple[Sniffed, float] | None]


class MusicPlayer:
    """The music half of ``AudioService``. ``music_gain``: ``c(master) · c(music)`` now;
    ``default_fadein``/``default_fadeout``: ``[audio] music_fadein``/``music_fadeout``;
    ``loop_point(file, data)``: the bytes to play and the loop start for a looping track
    with a loop point, or None (F08 step 10); ``on_start(track)``: a track
    started (a first start or a transition to a queued track, not a new pass)."""

    def __init__(self, backend: MixerBackend, reader: AudioReader, *,
                 music_gain: Callable[[], float], default_fadein: float,
                 default_fadeout: float, loop_point: LoopPoint | None = None,
                 on_start: Callable[[Track], None] | None = None) -> None:
        self.backend = backend
        self.reader = reader
        self._music_gain = music_gain
        self.default_fadein = default_fadein
        self.default_fadeout = default_fadeout
        self.loop_point = loop_point
        self._on_start = on_start
        self.skipping = False                # F15 (step 7): fades capped at 0.2 s
        self.paused = False                  # step 7 (background): the watchdog waits
        self.phase = Phase.SILENT
        self.current: Track | None = None
        self.armed: Armed | None = None
        self.armed_track: Track | None = None
        self.queue: list[Track] = []
        self.pending: Track | None = None
        self.switch_at: float | None = None  # §7.7: raw position of the pass end to switch at
        self._started_at = 0.0               # when ``current`` was music_start-ed
        self._pass_t0 = 0.0                  # when the current pass began (service time)
        self._pass_offset = 0.0              # the position the current pass began at
        self._loops_native = False           # current plays with loops=-1 (loop point)
        self._fade_end = 0.0                 # FADING_OUT: the fade's expected end
        self._fade_deadline = 0.0            # FADING_OUT: the stuck-fade watchdog
        self._not_busy_since: float | None = None
        self._last_pos = 0.0                 # the old track's position (``from current``)
        self._gain_from = 0.0
        self._gain_to = 0.0
        self._gain_t0 = 0.0
        self._gain_dur = 0.0
        self._sent = -1.0

    # --- fades -----------------------------------------------------------------------------

    def resolve_fadein(self, fade: float | None) -> float:
        return self._cap(self.default_fadein if fade is None else fade)

    def resolve_fadeout(self, fade: float | None) -> float:
        return self._cap(self.default_fadeout if fade is None else fade)

    def _cap(self, fade: float) -> float:
        fade = max(0.0, fade)
        return min(fade, SKIP_FADE_CAP_S) if self.skipping else fade

    # --- commands --------------------------------------------------------------------------

    def play(self, track: Track, *, fadeout: float, restart: bool, ramp: float | None,
             now: float) -> None:
        """§7.1 ``PlayMusic``: the sequence becomes ``track``. ``fadeout`` resolved;
        ``ramp``: a same-track volume change's fade (None: at once)."""
        self.queue.clear()
        self.switch_at = None
        current = self.current
        if (current is not None and self.phase is not Phase.SILENT and not restart
                and current.file == track.file and current.loop == track.loop):
            self._same_track(current, track, ramp, now)
            return
        if self.phase is Phase.SILENT:
            self._last_pos = 0.0                            # ``from current`` of silence
            self._start(track, now)
        elif self.phase is Phase.PLAYING:
            if fadeout <= 0.0:
                self._last_pos = self._position_or_zero(now)
                self.backend.music_stop()
                self._start(track, now)
            else:
                self.pending = track
                self._begin_fadeout(fadeout, now)
        else:                                               # FADING_OUT
            self.pending = track
            if fadeout < self._fade_end - now:
                if fadeout <= 0.0:
                    self._last_pos = self._position_or_zero(now)
                    self.backend.music_stop()
                    self._fade_done(now)
                else:
                    self._begin_fadeout(fadeout, now)

    def queue_track(self, track: Track, now: float) -> None:
        """§7.1 ``QueueMusic``: ``track`` goes to the end of the sequence."""
        if self.phase is Phase.SILENT:
            self._start(track, now)
            return
        if self.phase is Phase.FADING_OUT:
            if self.pending is None:
                self.pending = track
            else:
                self.queue.append(track)
            return
        current = self.current
        before = self.queue[-1] if self.queue else current
        self.queue.append(track)
        if before is current and current is not None:
            if not self._loops_native:
                self._arm_next(now)                          # once, or pass by pass
            elif now - self._started_at <= SAME_BURST_S:     # same burst as its play
                self.backend.music_stop()
                restart = Track(current.file, current.loop, current.volume, current.fadein,
                                start=current.start, story=current.story,
                                restored=current.restored, data=current.data,
                                length=current.length, loop_pt=current.loop_pt)
                self._start(restart, now, notify=False)
            else:
                self.switch_at = self._next_pass_end(now)
        elif before is self.armed_track and before is not None and self._native(before):
            self._arm_next(now)                              # armed to loop: now once

    def stop(self, fadeout: float, now: float) -> None:
        """§7.1 ``StopMusic``: the queue and the pending track are dropped; the music fades
        out over ``fadeout`` (0: at once). Stopping silence does nothing."""
        self.queue.clear()
        self.pending = None
        self.switch_at = None
        if self.phase is Phase.SILENT:
            return
        if fadeout <= 0.0:
            self.backend.music_stop()
            self._go_silent()
        elif self.phase is Phase.PLAYING or fadeout < self._fade_end - now:
            self._begin_fadeout(fadeout, now)

    # --- events and frames -------------------------------------------------------------------

    def on_end_event(self, now: float) -> None:
        """A music-end event (§7.1 "End event"); stale ones change nothing."""
        if self.phase is Phase.SILENT:
            return
        busy = self.backend.music_busy()
        if self.phase is Phase.FADING_OUT:
            if not busy:
                self._fade_done(now)
            return
        if not busy:
            self._ended(now, now)
            return
        pos = self.backend.music_pos_ms() / 1000.0
        if not self._transitioned(pos, now):
            return                                           # posted before this pass began
        ended_at = now - max(0.0, pos)
        if self.armed in (Armed.TRACK, Armed.PASS):
            self._transition(ended_at, now)
        else:
            self._ended(ended_at, now)                       # SILENT_WAV took the slot

    def update(self, now: float) -> None:
        """Every frame: the volume ramp, the watchdogs, and the §7.7 pass-end switch."""
        if self.phase is Phase.SILENT:
            return
        self._send_volume(now)
        if self.phase is Phase.FADING_OUT:
            if now >= self._fade_deadline:
                self._last_pos = self._position_or_zero(now)
                self.backend.music_stop()
                self._fade_done(now)
            return
        if self.backend.music_busy():
            self._not_busy_since = None
            if self.switch_at is not None:
                self._check_switch(now)
            return
        if self.paused:
            self._not_busy_since = None
        elif self._not_busy_since is None:
            self._not_busy_since = now
        elif now - self._not_busy_since >= WATCHDOG_S - 1e-9:
            self._ended(self._not_busy_since, now)

    def apply_volume(self, now: float) -> None:
        """The volume settings changed: the stream gets its new level now."""
        if self.phase is not Phase.SILENT:
            self._send_volume(now)

    def position(self, now: float) -> float | None:
        """The current track's position in seconds (§7.7), None when silent. Loop-point
        tracks of known length wrap into their loop."""
        if self.phase is Phase.SILENT or self.current is None:
            return None
        raw = self._raw_position(now)
        track = self.current
        start = track.loop_pt or 0.0
        if self._loops_native and track.length is not None and raw >= track.length > start:
            return start + (raw - track.length) % (track.length - start)
        return raw

    def _position_or_zero(self, now: float) -> float:
        position = self.position(now)
        return 0.0 if position is None else position

    def is_playing(self) -> bool:
        """Music is playing or fading out (not silent)."""
        return self.phase is not Phase.SILENT

    def shutdown(self) -> None:
        """Forget everything (the backend closes itself, or a reopen lost the stream)."""
        self.queue.clear()
        self.pending = None
        self._go_silent()

    def rebuild(self, position: float | None, now: float) -> None:
        """§7.9 step 3: the device was reopened and the stream is gone. A playing track
        starts again at ``position`` (taken before the reopen) with no fade, and the queue
        is armed again: with a queue it plays once to its end and the next track follows
        with no gap (so a §7.7 switch is no longer needed). A fade-out under way is over:
        the pending track starts, else silence."""
        if self.phase is Phase.SILENT:
            return
        if self.phase is Phase.FADING_OUT:
            self._fade_done(now)
            return
        current = self.current
        assert current is not None
        again = Track(current.file, current.loop, current.volume, 0.0,
                      start=max(0.0, position or 0.0), story=current.story,
                      data=current.data, length=current.length, loop_pt=current.loop_pt)
        self._go_silent(keep_queue=True)
        self._start(again, now, notify=False)

    # --- internals: starting and ending ----------------------------------------------------

    def _same_track(self, current: Track, track: Track, ramp: float | None,
                    now: float) -> None:
        """§7.1 rule 1 (SR-F08-07): it continues; the volume applies over ``ramp``."""
        self.pending = None
        current.volume = track.volume
        current.story = track.story
        if self.phase is Phase.FADING_OUT:
            # An SDL fade can't be cancelled: restart where it is with a short fade-in.
            pos = self._position_or_zero(now)
            if current.length is not None and pos >= current.length:
                pos = 0.0
            self.backend.music_stop()
            again = Track(current.file, current.loop, track.volume, SAME_TRACK_FADEIN_S,
                          start=pos, story=track.story, restored=track.restored,
                          data=current.data, length=current.length, loop_pt=current.loop_pt)
            self._start(again, now, notify=False)
            return
        self._arm_next(now)
        self._ramp(curve(track.volume), ramp if ramp is not None and ramp > 0.0 else 0.0, now)
        self._send_volume(now)

    def _start(self, track: Track | None, now: float, *, notify: bool = True) -> None:
        """§7.1 ``start``: play ``track`` now; a track that can't be read or decoded is
        skipped (logged once) for the next queued one, else silence."""
        old_pos = self._last_pos
        while track is not None:
            if self._load(track):
                start = old_pos if track.from_current else track.start
                if track.length is not None and start >= track.length:
                    start = 0.0
                if self.backend.music_busy():
                    self.backend.music_stop()
                self.current = track
                loops = -1 if self._loops(track) and self._native(track) else 0
                self._ramp(curve(track.volume), 0.0, now)
                self._sent = -1.0
                self._send_volume(now)
                try:
                    start = self.backend.music_start(track.data, loops=loops,
                                                     start=max(0.0, start),
                                                     fade_ms=round(track.fadein * 1000))
                except DecodeError:
                    self._failed(track)
                else:
                    self.phase = Phase.PLAYING
                    self._loops_native = loops < 0
                    self._started_at = self._pass_t0 = now
                    self._pass_offset = start
                    self._not_busy_since = None
                    self.armed = self.armed_track = None
                    self._arm_next(now)
                    if notify and self._on_start is not None:
                        self._on_start(track)
                    return
            track = self.queue.pop(0) if self.queue else None
        self._go_silent()

    def _load(self, track: Track) -> bool:
        """Read and sniff ``track`` (once); False: it plays as silence (logged)."""
        if track.data is not None:
            return True
        data = self.reader.read_music(track.file, restored=track.restored)
        if data is None:
            return False
        track.length = declared_seconds(data, header=True)
        if track.loop and self.loop_point is not None:
            tagged = self.loop_point(track.file, data)
            if tagged is not None:
                data, track.loop_pt = tagged
        track.data = data
        return True

    def _failed(self, track: Track) -> None:
        """SDL refused bytes the sniff accepted: W26 "isn't really", never read again."""
        self.reader.log.problem("damaged", track.file, w26_not_really(track.file))
        self.reader.mark_failed(track.file)
        track.data = None

    @staticmethod
    def _native(track: Track) -> bool:
        """A looping ``track`` loops in SDL (``loops=-1``): its pass end is known."""
        return track.loop_pt is not None or track.length is not None

    def _loops(self, track: Track) -> bool:
        """Whether ``track`` really loops: it is the last of the sequence and was written
        ``loop`` (SR-F08-15)."""
        if not track.loop:
            return False
        if track is self.current:
            return not self.queue
        return bool(self.queue) and track is self.queue[-1]

    def _arm_next(self, now: float) -> None:
        """§7.1 ``arm_next``: the slot gets ``queue[0]``, else ``current`` again (pass by
        pass), else ``SILENT_WAV``. A queued track that can't be read is skipped."""
        while self.queue:
            nxt = self.queue[0]
            if self._load(nxt):
                loops = -1 if self._loops(nxt) and self._native(nxt) else 0
                try:
                    self.backend.music_arm(nxt.data, loops=loops)
                except DecodeError:
                    self._failed(nxt)
                else:
                    self.armed, self.armed_track = Armed.TRACK, nxt
                    return
            self.queue.pop(0)
        current = self.current
        if (current is not None and current.data is not None and self._loops(current)
                and not self._loops_native):
            try:                                 # a known length loops natively from pass 2
                self.backend.music_arm(current.data,
                                       loops=-1 if self._native(current) else 0)
            except DecodeError:
                pass
            else:
                self.armed, self.armed_track = Armed.PASS, current
                return
        self.backend.music_arm(SILENT_WAV, loops=0)
        self.armed, self.armed_track = Armed.SILENT, None

    def _begin_fadeout(self, fadeout: float, now: float) -> None:
        self.backend.music_fadeout(max(1, round(fadeout * 1000)))
        self.backend.music_arm(SILENT_WAV, loops=0)
        self.armed, self.armed_track = Armed.SILENT, None
        self.phase = Phase.FADING_OUT
        self._fade_end = now + fadeout
        self._fade_deadline = self._fade_end + STUCK_FADE_SLACK_S

    def _fade_done(self, now: float) -> None:
        """A fade-out ended: the pending track starts, or silence."""
        if self.current is not None:
            self._last_pos = self._position_or_zero(now)
        pending, self.pending = self.pending, None
        self._go_silent(keep_queue=True)
        if pending is not None:
            self._start(pending, now)
        else:
            self.queue.clear()

    def _transition(self, ended_at: float, now: float) -> None:
        """The armed track started in SDL with no gap."""
        self._check_damaged(ended_at)
        kind, nxt = self.armed, self.armed_track
        self.armed = self.armed_track = None
        self._pass_t0 = ended_at
        self._pass_offset = 0.0
        self._not_busy_since = None
        if kind is Armed.TRACK and nxt is not None:
            if self.queue and self.queue[0] is nxt:
                self.queue.pop(0)
            self.current = nxt
            self._started_at = ended_at
            self._loops_native = self._loops(nxt) and self._native(nxt)
            self._ramp(curve(nxt.volume), 0.0, now)
            self._send_volume(now)
            self._arm_next(now)
            if self._on_start is not None:
                self._on_start(nxt)
            return
        if self.current is not None and self._native(self.current):
            self._loops_native = True                        # armed with loops=-1
        self._arm_next(now)                                  # a new pass of the same track

    def _ended(self, ended_at: float, now: float) -> None:
        """The stream stopped by itself: the next queued track starts, or silence."""
        self._check_damaged(ended_at)
        if self.current is not None:
            self._last_pos = self._position_or_zero(ended_at)
        self._go_silent(keep_queue=True)
        if self.queue:
            self._start(self.queue.pop(0), now)

    def _go_silent(self, *, keep_queue: bool = False) -> None:
        self.phase = Phase.SILENT
        self.current = None
        self.armed = self.armed_track = None
        self.switch_at = None
        self._loops_native = False
        self._not_busy_since = None
        if not keep_queue:
            self.queue.clear()

    def _check_damaged(self, ended_at: float) -> None:
        """W27 (best effort): a pass that ended more than 1 s before the track's known
        length."""
        track = self.current
        if track is None or track.length is None or self._loops_native:
            return
        if self.backend.silent:
            return                    # NullMixer: the stream is never busy (step 11)
        played = self._pass_offset + (ended_at - self._pass_t0)
        if played < track.length - DAMAGED_SLACK_S:
            self.reader.log.problem("partway", track.file, w27_damaged(track.file, played),
                                    code="W27")

    def _transitioned(self, pos: float, now: float) -> bool:
        """True if the stream moved on since the current pass began: its position (reset
        by every transition) is behind the time the pass has run, or the pass's known
        length has elapsed. A stale event, posted before a ``music_start``, is neither."""
        elapsed = now - self._pass_t0
        if pos < 0.0 or elapsed - pos >= _RESET_S:
            return True
        track = self.current
        if track is not None and track.length is not None and not self._loops_native:
            return elapsed >= track.length - self._pass_offset - _LENGTH_SLACK_S
        return False

    # --- internals: position and the pass-end switch (§7.7) ----------------------------

    def _raw_position(self, now: float) -> float:
        """``start offset + music_pos_ms() / 1000`` (unwrapped); the time since the pass
        began when the backend has no position."""
        ms = self.backend.music_pos_ms() if self.backend.music_busy() else -1
        if ms >= 0:
            return self._pass_offset + ms / 1000.0
        return self._pass_offset + max(0.0, now - self._pass_t0)

    def _next_pass_end(self, now: float) -> float:
        track = self.current
        raw = self._raw_position(now)
        if track is None or track.length is None:
            return raw
        if raw < track.length:
            return track.length
        span = max(1e-3, track.length - (track.loop_pt or 0.0))
        return track.length + math.ceil((raw - track.length) / span) * span

    def _check_switch(self, now: float) -> None:
        raw = self._raw_position(now)
        target = self.switch_at
        if target is None or raw < target - SWITCH_LEAD_S:
            return
        remaining = target - raw
        fade = remaining if remaining >= LATE_SWITCH_FADE_S else LATE_SWITCH_FADE_S
        self.switch_at = None
        self.pending = self.queue.pop(0) if self.queue else None
        self._begin_fadeout(fade, now)

    # --- internals: volume ---------------------------------------------------------------

    def _gain(self, now: float) -> float:
        if self._gain_dur <= 0.0 or now >= self._gain_t0 + self._gain_dur:
            return self._gain_to
        if now <= self._gain_t0:
            return self._gain_from
        return (self._gain_from
                + (self._gain_to - self._gain_from) * (now - self._gain_t0) / self._gain_dur)

    def _ramp(self, to: float, dur: float, now: float) -> None:
        self._gain_from = self._gain(now)
        self._gain_to = to
        self._gain_t0 = now
        self._gain_dur = max(0.0, dur)

    def _send_volume(self, now: float) -> None:
        level = quantize(self._music_gain() * self._gain(now))
        if level != self._sent:
            self._sent = level
            self.backend.music_volume(level)


__all__ = ["Armed", "MusicPlayer", "Phase", "SILENT_WAV", "SILENT_WAV_BYTES", "Track",
           "WATCHDOG_S", "w27_damaged"]

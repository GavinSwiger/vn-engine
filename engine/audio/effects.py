"""Story sound effects and voice: the 16 effect slots, the voice channel, the UI pool, the
blip channel, and their volume ramps (F08 ``04-technical.md`` §7.2, §7.6 steps 3–4, §5.2
``play_ui``; G1; ``07`` I-10, I-13(a); AC-F08-26, 28, 29, 45, 47, 48, 52; F06 ``SPEC.md`` §5,
``07`` I-3, I-4, I-6; AC-F06-08, 10, 12).

Why this module exists: ``play sound`` overlaps effects on channels 5–20; a loop that is
already playing only changes its volume; when every channel is busy the oldest one-shot gives
way, and when all 16 loop the new effect is dropped with one WARNING. Fades are Python
volume ramps set on every ``update``, never SDL channel fades, because SDL overwrites a
channel's volume during its own fade and a settings change would be lost (G1). A ramp is
kept as the effect's own gain (0 to ``curve(volume)``); the level sent to the backend is
``quantize(c(master) · c(sound) · gain)``, recomputed from the current settings, so a volume
change applies at the next update even mid-fade. A fade-out ramps to 0 and then
``channel_stop`` (I-13(a): AC-26's ``channel_fadeout(c, n)``).

A line's voice plays once on channel 0 (``VoiceChannel``): the next voice replaces it, its
line's advance (``EndVoice``) stops it unless voice sustain is on, and ``stop voice`` ramps it
out the same way an effect fades.

Step 7: a restore (``reconcile``) keeps the effects that loop in the restored state (only
their volume ramps to the new level), fades every other effect out, and starts the target
loops that aren't playing with a fade-in; the voice fades out and the restored line's
``PlayVoice(restored=True)`` follows. While F15 skips (``skipping``), one-shot effects and
unrestored voices are ignored and every effect fade is capped at ``SKIP_FADE_CAP_S``.
``UiPool`` plays F10/F07/F11 UI sounds on the UI channels 2–4 (``play_ui``): once each, at
``amp(master, sound, volume)``, the oldest giving way when all three are busy; it never
touches a story channel and no story command touches it. A UI sound still being decoded is
a ``UiRequest``. Each sound has an ``owner`` (None: the engine's; ``"minigame"``: F23's
plugin one-shots), and ``stop`` (``stop_ui``, F23 ``07`` C4, I-4) ramps only that owner's
sounds out and cancels only its decodes.

``BlipChannel`` plays F06's blips on channel 1 (``play_blip``): a new blip stops the one
still sounding, at ``amp(master, sound, volume)``; nothing while skipping. A blip with a
spread plays one of its pitch variants (``BlipSounds``, key ``("blip", file, spread)``),
one without plays the file's ``("snd", file)`` Sound (I-6). A miss asks the loader once:
the request waits as ``pending`` (one; a newer ask replaces it, and a newer ask of the same
key makes no second read or ticket) and plays when the decode is ready if its newest ask is
at most ``BLIP_STALE_S`` old. A blip path that turned out silent (missing, unreadable,
damaged) is not read again in the session (I-4). The entry is held while it plays.

Decoded sounds come from the ``SoundLoader`` (step 9, §7.3 with I-5): a cache hit plays at
once; otherwise the file is read and sniffed now, decoded on the loader's worker, and plays
from the service's ``update`` (the ramp's ``t0`` is when it starts). Until then it is a
``Pending`` entry: a ``stop sound`` or restore cancels it (it never plays), a second
``play sound … loop`` of the same file only changes its volume, and a pending voice counts as
playing for ``voice_playing``, so an auto-advance waits for it. With the loader's fallback
(``LOADER_THREADED = False``, or a backend whose decode costs nothing) the answer comes in
the same call and every sound plays when its command arrives, as before step 9. The loader
charges each Sound to the App's ``SizedLru`` as ``("snd", file)`` with cost
``length_s × 192,000 + ENTRY_OVERHEAD``; it is held while it plays. Main thread only.

Loop points (step 10, SR-F08-09, 23): a looping effect whose file has a loop point arrives as
a ``LoopedSound``. It plays the whole sound once (``loops=0``) with the tail (the samples from
the loop point on) in the channel's queue; SDL_mixer starts a queued sound in the same buffer,
with no gap, but only once, so ``update`` queues the tail again each time it starts (the
tail lasts at least ``TAIL_MIN_S``, far longer than a frame). A one-shot of that file, a voice,
or a UI sound plays the whole sound.
"""

from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from engine.audio.backend import MixerBackend
from engine.audio.limits import (BLIP_CHANNEL, BLIP_STALE_S, EFFECT_CHANNELS, FAILED_FILES_MAX,
                                 SKIP_FADE_CAP_S, UI_CHANNELS, VOICE_CHANNEL)
from engine.audio.loader import (SOUND_KEY, BlipSounds, Key, LoopedSound, SoundLoader, Ticket,
                                 blip_key, sound_key, whole)
from engine.audio.reading import AUDIO_FOLDER, AudioReader
from engine.audio.volume import curve, quantize
from engine.core.lru import SizedLru
from engine.core.redact import echo
from engine.runtime.audio import SoundLoop
from engine.runtime.commands import PlaySound


def drop_text(file: str) -> str:
    """The WARNING for an effect dropped because 16 loops play (draft, ``06`` G4)."""
    return (f"{echo(AUDIO_FOLDER + file)} wasn't played, because {len(EFFECT_CHANNELS)} "
            f"looping effects are already playing. Stop one with stop sound first.")


@dataclass(eq=False, slots=True)
class Pending:
    """A story effect whose sound the loader is still decoding (§7.3): it starts with
    these settings when the decode is ready, unless its ticket is cancelled first."""

    file: str
    loop: bool
    volume: int
    fade: float
    ticket: Ticket | None = None

    @property
    def waiting(self) -> bool:
        return self.ticket is not None and self.ticket.waiting

    def cancel(self) -> None:
        if self.ticket is not None:
            self.ticket.cancel()


@dataclass(slots=True)
class Slot:
    """One story effect on its channel. ``gain`` ramps from ``gain_from`` to ``gain_to``
    over ``dur`` seconds from ``t0``; ``stopping``: the channel stops when it reaches 0."""

    channel: int
    file: str
    loop: bool
    volume: int
    seq: int
    gain_from: float
    gain_to: float
    t0: float
    dur: float
    stopping: bool = False
    sent: float = -1.0                     # the level last sent to the backend
    tail: Any = None                       # a loop point's tail, queued again each pass
    owner: str | None = None               # a UI sound's owner (``stop_ui``, F23 I-4)

    def gain(self, now: float) -> float:
        if self.dur <= 0.0 or now >= self.t0 + self.dur:
            return self.gain_to
        if now <= self.t0:
            return self.gain_from
        return self.gain_from + (self.gain_to - self.gain_from) * (now - self.t0) / self.dur

    def ramping(self, now: float) -> bool:
        return self.dur > 0.0 and now < self.t0 + self.dur

    def ramp(self, now: float, to: float, dur: float) -> None:
        """Start a ramp from the gain at ``now`` to ``to`` over ``dur`` (0: at once)."""
        self.gain_from = self.gain(now)
        self.gain_to = to
        self.t0 = now
        self.dur = max(0.0, dur)


class EffectSlots:
    """The story effects on channels 5–20 (``EFFECT_CHANNELS``), and those still being
    decoded (``pending``, oldest first)."""

    def __init__(self, backend: MixerBackend, reader: AudioReader, cache: SizedLru,
                 loader: SoundLoader, *, sound_gain: Callable[[], float],
                 default_fadein: float, default_fadeout: float) -> None:
        self.backend = backend
        self.reader = reader
        self.cache = cache
        self.loader = loader
        self._sound_gain = sound_gain
        self.default_fadein = default_fadein
        self.default_fadeout = default_fadeout
        self.slots: dict[int, Slot] = {}
        self.pending: list[Pending] = []
        self.skipping = False                      # F15 (set_skipping): see ``play``
        self._seq = 0

    @property
    def active(self) -> bool:
        """Whether any story effect plays or is being decoded."""
        return bool(self.slots) or any(entry.waiting for entry in self.pending)

    def cap(self, fade: float) -> float:
        """A fade in seconds, capped at ``SKIP_FADE_CAP_S`` while skipping (PR-F08-24)."""
        fade = max(0.0, fade)
        return min(fade, SKIP_FADE_CAP_S) if self.skipping else fade

    # --- commands --------------------------------------------------------------------------

    def play(self, cmd: PlaySound, now: float) -> None:
        """§7.2 ``PlaySound``. While skipping a one-shot is ignored (no backend call) and a
        loop's fade is capped."""
        if cmd.loop:
            fade = self.cap(cmd.fadein) if cmd.fadein is not None else None
            if self._keep_loop(cmd.file, cmd.volume, fade, now):
                return                             # already looping: only its volume changes
        elif self.skipping:
            return
        fade = self.cap(cmd.fadein if cmd.fadein is not None else self.default_fadein)
        self._start(cmd.file, cmd.loop, cmd.volume, fade, now)

    def stop(self, file: str | None, fadeout: float | None, now: float) -> None:
        """§7.2 ``StopSound``: every story effect (``file`` None) or those of ``file``
        stop at once (fade 0) or ramp out over the fade; those still being decoded are
        cancelled and never play (AC-F08-27). The pool is untouched."""
        fade = self.cap(fadeout if fadeout is not None else self.default_fadeout)
        for slot in sorted(self.slots.values(), key=lambda s: s.seq):
            if file is None or slot.file == file:
                self._fade_out(slot, fade, now)
        for entry in list(self.pending):
            if file is None or entry.file == file:
                self._cancel(entry)

    def reconcile(self, loops: tuple[SoundLoop, ...], *, fadein: float, fadeout: float,
                  now: float, keep_oneshots: bool = False, restored: bool = False) -> None:
        """§7.6 step 3 (``AudioRestore``): the effects become ``loops``. A loop already
        playing its file is kept and its volume ramps to the new level over ``fadein``;
        every other effect fades out over ``fadeout`` (one-shots too, unless
        ``keep_oneshots``: a ``sync`` keeps the burst's one-shots); the target loops not
        playing start with a fade-in over ``fadein``. ``restored``: a missing file is W29.
        Fades are capped while skipping. An effect still being decoded counts as playing:
        a target loop keeps it (it starts at the new level, fading in over ``fadein``);
        every other one is cancelled."""
        fadein, fadeout = self.cap(fadein), self.cap(fadeout)
        target = {entry.file: entry.volume for entry in loops}
        kept: set[str] = set()
        for slot in sorted(self.slots.values(), key=lambda s: s.seq):
            if (slot.loop and slot.file in target and slot.file not in kept
                    and self.backend.channel_busy(slot.channel)):
                kept.add(slot.file)
                self._set_volume(slot, target[slot.file], fadein, now)
            elif slot.loop or not keep_oneshots:
                self._fade_out(slot, fadeout, now)
        for waiting in list(self.pending):
            if waiting.loop and waiting.file in target and waiting.file not in kept:
                kept.add(waiting.file)
                waiting.volume = target[waiting.file]
                waiting.fade = fadein
            elif waiting.loop or not keep_oneshots:
                self._cancel(waiting)
        for entry in loops:
            if entry.file not in kept:
                self._start(entry.file, True, entry.volume, fadein, now, restored=restored)

    def update(self, now: float) -> None:
        """Advance the ramps, stop the effects whose fade-out ended, and free the slots
        whose channel went idle (releasing their cache holds). O(16). (The loader's
        ``update`` ran first: decodes that finished have started.)"""
        if self.pending:
            self.pending = [entry for entry in self.pending if entry.waiting]
        backend = self.backend
        for channel, slot in list(self.slots.items()):
            if slot.stopping and not slot.ramping(now):
                backend.channel_stop(channel)
                self._free(channel)
                continue
            self._send(slot, now)
            if not backend.channel_busy(channel):
                if slot.tail is not None:                      # a frame came too late:
                    backend.channel_play(channel, slot.tail, 0)    # the loop goes on
                    continue
                self._free(channel)
            elif slot.tail is not None and not backend.channel_queued(channel):
                backend.channel_queue(channel, slot.tail)      # the next pass of the loop

    def apply_volumes(self, now: float) -> None:
        """The settings changed: every effect gets its new level now (AC-F08-30)."""
        for slot in self.slots.values():
            self._send(slot, now)

    def restart_loops(self, loops: Iterable[tuple[str, int]], now: float) -> None:
        """§7.9 step 3: after a device reopen (every slot was dropped), the story's loops
        ``(file, volume)`` start again at their level, with no fade."""
        for file, volume in loops:
            self._start(file, True, volume, 0.0, now)

    def shutdown(self) -> None:
        """Forget every slot and release its cache hold, and cancel every decode still
        pending (the backend closes itself, or a reopen took its sounds)."""
        for entry in list(self.pending):
            self._cancel(entry)
        for channel in list(self.slots):
            self._free(channel)

    # --- internals -------------------------------------------------------------------------

    def _keep_loop(self, file: str, volume: int, fade: float | None, now: float) -> bool:
        """If ``file`` already loops in a slot: its volume ramps to ``volume`` over
        ``fade`` (a fade-out under way is called off) and True. If it is a loop still being
        decoded: it will start at ``volume`` (fading in over ``fade`` when given) and
        True."""
        for channel, slot in list(self.slots.items()):
            if slot.loop and slot.file == file:
                if self.backend.channel_busy(channel):
                    self._set_volume(slot, volume, fade or 0.0, now)
                    return True
                self._free(channel)
        for entry in self.pending:
            if entry.loop and entry.file == file and entry.waiting:
                entry.volume = volume
                if fade is not None:
                    entry.fade = fade
                return True
        return False

    def _set_volume(self, slot: Slot, volume: int, fade: float, now: float) -> None:
        slot.volume = volume
        slot.stopping = False
        slot.ramp(now, curve(volume), fade)
        self._send(slot, now)

    def _fade_out(self, slot: Slot, fade: float, now: float) -> None:
        """At once (``fade`` 0), or a ramp to 0 and then ``channel_stop`` (I-13(a))."""
        if fade <= 0.0:
            self.backend.channel_stop(slot.channel)
            self._free(slot.channel)
        else:
            slot.stopping = True
            slot.ramp(now, 0.0, fade)

    def _start(self, file: str, loop: bool, volume: int, fade: float, now: float, *,
               restored: bool = False) -> None:
        """Ask the loader for ``file``; it plays when the sound is ready (at once for a
        cache hit or without the worker), else waits in ``pending``."""
        entry = Pending(file, loop, volume, fade)
        ticket = self.loader.load(file, lambda sound, at: self._ready(entry, sound, at), now,
                                  restored=restored)
        if ticket.waiting:
            entry.ticket = ticket
            self.pending.append(entry)

    def _ready(self, entry: Pending, sound: Any | None, now: float) -> None:
        """The loader's answer for ``entry``: None is silence (logged once)."""
        self._forget(entry)
        if sound is not None:
            self._place(entry.file, entry.loop, entry.volume, entry.fade, sound, now)

    def _cancel(self, entry: Pending) -> None:
        entry.cancel()
        self._forget(entry)

    def _forget(self, entry: Pending) -> None:
        for index, other in enumerate(self.pending):
            if other is entry:
                del self.pending[index]
                return

    def _place(self, file: str, loop: bool, volume: int, fade: float, sound: Any,
               now: float) -> None:
        """Play ``sound`` on a free channel (or the oldest one-shot's), from 0 when it fades
        in (the ramp starts now); dropped with one WARNING when all 16 channels loop."""
        channel = self._pick()
        if channel is None:
            self.reader.log.problem("dropped", file, drop_text(file), code=None)
            return
        target = curve(volume)
        self._seq += 1
        slot = Slot(channel, file, loop, volume, self._seq,
                    gain_from=0.0 if fade > 0.0 else target, gain_to=target, t0=now,
                    dur=fade if fade > 0.0 else 0.0)
        self.slots[channel] = slot
        self.cache.hold(sound_key(file))
        self._send(slot, now)
        if loop and isinstance(sound, LoopedSound):
            slot.tail = sound.tail                 # once from 0, then from the loop point
            self.backend.channel_play(channel, sound.sound, 0)
            self.backend.channel_queue(channel, sound.tail)
        else:
            self.backend.channel_play(channel, whole(sound), -1 if loop else 0)

    def _pick(self) -> int | None:
        """A channel for a new effect: a free one; else one whose sound ended; else the
        oldest effect fading out; else the oldest one-shot (stopped first). None when all
        16 loop."""
        slots = self.slots
        for channel in EFFECT_CHANNELS:
            if channel not in slots:
                return channel
        by_age = sorted(slots.values(), key=lambda s: s.seq)
        for slot in by_age:
            if not self.backend.channel_busy(slot.channel):
                self._free(slot.channel)
                return slot.channel
        victim = next((s for s in by_age if s.stopping), None) \
            or next((s for s in by_age if not s.loop), None)
        if victim is None:
            return None
        self.backend.channel_stop(victim.channel)
        self._free(victim.channel)
        return victim.channel

    def _send(self, slot: Slot, now: float) -> None:
        level = quantize(self._sound_gain() * slot.gain(now))
        if level != slot.sent:
            slot.sent = level
            self.backend.channel_volume(slot.channel, level)

    def _free(self, channel: int) -> None:
        slot = self.slots.pop(channel, None)
        if slot is not None:
            self.cache.release(sound_key(slot.file))


class VoiceChannel:
    """The voice line on channel 0 (§7.2 voice; PR-F08-04, 31; AC-F08-28, 29). One voice at a
    time, played once (``loops=0``), never queued. ``sid`` is the line it voices, so a late
    ``EndVoice`` of an earlier line does nothing. ``sustain`` (F16's setting, off by default)
    lets a voice play on past its line's advance until the next voice or ``stop voice``.
    ``skipping`` is set by step 7's ``set_skipping``: a skipped line's voice doesn't play,
    a restored one does. The level is ``amp(master, voice, 100)`` times the stop ramp.
    While the loader decodes the voice (``pending``), it counts as playing for its line."""

    def __init__(self, backend: MixerBackend, reader: AudioReader, cache: SizedLru,
                 loader: SoundLoader, *, voice_gain: Callable[[], float]) -> None:
        self.backend = backend
        self.reader = reader
        self.cache = cache
        self.loader = loader
        self._voice_gain = voice_gain
        self.slot: Slot | None = None           # the voice playing, or fading out
        self.pending: Ticket | None = None      # the voice being decoded
        self.sid: str | None = None             # the line it voices (playing or pending)
        self.sustain = False
        self.skipping = False
        self.replay = False                     # it is F13's replay (playing or pending)
        # The last voice ignored while skipping, (sid, file), until any other voice, an
        # ``EndVoice``, or a stop (``stop voice``, a restore, ``stop_story_audio``): what
        # ``resume`` may play when skip ends on its line (F15 ``07`` I-3).
        self.skipped: tuple[str, str] | None = None
        self._seq = 0

    def play(self, sid: str | None, file: str, restored: bool, now: float, *,
             replay: bool = False) -> None:
        """``PlayVoice``: the voice playing stops (always, even when the new file turns out
        to be silent), then ``file`` plays once. ``replay``: F13's ``replay_voice`` (no line,
        ``sid`` None; it plays while skipping too). While skipping, an unrestored line's
        voice is only remembered (``skipped``)."""
        if self.skipping and not restored and not replay:
            if sid is not None:
                self.skipped = (sid, file)
            return
        self.skipped = None
        self._cancel_pending()
        self._stop_now()
        self.sid = sid
        self.replay = replay
        ticket = self.loader.load(file, lambda sound, at: self._ready(file, sound, at), now,
                                  what="voice", restored=restored)
        if ticket.waiting:
            self.pending = ticket

    def _ready(self, file: str, sound: Any | None, now: float) -> None:
        """The loader's answer for the pending voice: None is silence (logged once)."""
        self.pending = None
        if sound is None:
            if self.slot is None:
                self.sid = None
            return
        self._seq += 1
        self.slot = Slot(VOICE_CHANNEL, file, False, 100, self._seq, gain_from=1.0,
                         gain_to=1.0, t0=now, dur=0.0)
        self.cache.hold(sound_key(file))
        self._send(now)
        self.backend.channel_play(VOICE_CHANNEL, whole(sound), 0)

    def resume(self, sid: str, now: float) -> None:
        """Skip ended on line ``sid`` (F15 ``07`` I-3): the voice ignored while skipping
        plays if it is that line's and nothing came after it. Call with ``skipping`` off."""
        skipped, self.skipped = self.skipped, None
        if skipped is not None and skipped[0] == sid:
            self.play(sid, skipped[1], False, now)

    def end(self, sid: str) -> None:
        """``EndVoice``: line ``sid`` was advanced; its voice stops unless sustain is on."""
        self.skipped = None
        if self.sid == sid and not self.sustain:
            if self.pending is not None:
                self._cancel_pending()
                if self.slot is None:
                    self.sid = None
            if self.slot is not None:
                self._stop_now()

    def stop(self, fadeout: float | None, now: float) -> None:
        """``stop voice`` (default fade 0) and ``stop_story_audio``: at once, or a ramp to
        0 over ``fadeout`` and then ``channel_stop`` (I-13(a)). A voice still being decoded
        never plays. Silence: nothing. A voice ignored while skipping is forgotten."""
        self.skipped = None
        if self.pending is not None:
            self._cancel_pending()
            if self.slot is None:
                self.sid = None
        slot = self.slot
        if slot is None:
            return
        fade = fadeout if fadeout is not None else 0.0
        if fade <= 0.0:
            self._stop_now()
        else:
            slot.stopping = True
            slot.ramp(now, 0.0, fade)

    def playing(self, sid: str | None = None) -> bool:
        """Whether a voice is audible now (``sid``: the voice of that line). A voice the
        loader is still decoding counts: it is about to start, and an auto-advance must
        wait for it (F05, F06)."""
        if self.pending is not None and self.pending.waiting:
            return sid is None or self.sid == sid
        if self.slot is None or not self.backend.channel_busy(VOICE_CHANNEL):
            return False
        return sid is None or self.sid == sid

    def update(self, now: float) -> None:
        """Advance the stop ramp; a voice that ended frees its cache hold."""
        if self.pending is not None and not self.pending.waiting:
            self.pending = None                 # cancelled by the loader (a reopen)
            if self.slot is None:
                self.sid = None
        slot = self.slot
        if slot is None:
            return
        if slot.stopping and not slot.ramping(now):
            self._stop_now()
            return
        self._send(now)
        if not self.backend.channel_busy(VOICE_CHANNEL):
            self._free()

    def apply_volume(self, now: float) -> None:
        """The settings changed: the voice gets its new level now (AC-F08-30)."""
        if self.slot is not None:
            self._send(now)

    def shutdown(self) -> None:
        self._cancel_pending()
        self._free()

    def _cancel_pending(self) -> None:
        ticket, self.pending = self.pending, None
        if ticket is not None:
            ticket.cancel()

    def _stop_now(self) -> None:
        self.backend.channel_stop(VOICE_CHANNEL)
        self._free()

    def _send(self, now: float) -> None:
        slot = self.slot
        assert slot is not None
        level = quantize(self._voice_gain() * slot.gain(now))
        if level != slot.sent:
            slot.sent = level
            self.backend.channel_volume(VOICE_CHANNEL, level)

    def _free(self) -> None:
        slot, self.slot, self.sid = self.slot, None, None
        self.replay = False
        if slot is not None:
            self.cache.release(sound_key(slot.file))


@dataclass(eq=False, slots=True)
class UiRequest:
    """A UI sound the loader is still decoding: it plays with ``volume`` when ready,
    unless its ticket is cancelled first (``stop`` of its ``owner``)."""

    file: str
    volume: int
    owner: str | None = None
    ticket: Ticket | None = None

    @property
    def waiting(self) -> bool:
        return self.ticket is not None and self.ticket.waiting


class UiPool:
    """UI sounds on the UI channels 2–4 (``UI_CHANNELS``; ``play_ui``, PR-F08-28a): F10, F07,
    and F11 UI sounds (channel 1 is F06's blips, ``BlipChannel``). Each plays once at
    ``amp(master, sound, volume)``; a free channel is taken first, else the oldest sound
    gives way (one fading out first). Never story audio: no story command, restore, skip,
    or ``stop_story_audio`` touches it. A sound not yet decoded plays when the loader has it
    (``pending``). ``stop(owner, ...)`` fades only ``owner``'s sounds with the engine ramp
    (G1), as ``EffectSlots`` does; channel 1 (F06's blips) is never touched."""

    def __init__(self, backend: MixerBackend, reader: AudioReader, cache: SizedLru,
                 loader: SoundLoader, *, sound_gain: Callable[[], float],
                 channels: range = UI_CHANNELS) -> None:
        self.backend = backend
        self.reader = reader
        self.cache = cache
        self.loader = loader
        self._sound_gain = sound_gain
        self.channels = channels
        self.slots: dict[int, Slot] = {}
        self.pending: list[UiRequest] = []
        self._seq = 0

    def play(self, file: str, volume: int, now: float, owner: str | None = None) -> None:
        request = UiRequest(file, volume, owner)
        ticket = self.loader.load(file, lambda sound, at: self._ready(request, sound, at), now)
        if ticket.waiting:
            request.ticket = ticket
            self.pending.append(request)

    def _ready(self, request: UiRequest, sound: Any | None, now: float) -> None:
        if sound is None:
            return                                 # silence; logged once by the reader
        channel = self._pick()
        self._seq += 1
        volume = request.volume
        target = curve(max(0, min(100, volume)))
        slot = Slot(channel, request.file, False, volume, self._seq, gain_from=target,
                    gain_to=target, t0=now, dur=0.0, owner=request.owner)
        self.slots[channel] = slot
        self.cache.hold(sound_key(request.file))
        self._send(slot, now)
        self.backend.channel_play(channel, whole(sound), 0)

    def stop(self, owner: str | None, fadeout: float, now: float) -> None:
        """``stop_ui``: ``owner``'s sounds stop at once (``fadeout`` 0) or ramp to 0 over
        ``fadeout`` and then ``channel_stop``; its decodes still pending are cancelled and
        never play. Other owners' sounds are untouched."""
        fade = max(0.0, fadeout)
        for slot in sorted(self.slots.values(), key=lambda s: s.seq):
            if slot.owner != owner:
                continue
            if fade <= 0.0:
                self.backend.channel_stop(slot.channel)
                self._free(slot.channel)
            else:
                slot.stopping = True
                slot.ramp(now, 0.0, fade)
        kept = []
        for request in self.pending:
            if request.owner != owner:
                kept.append(request)
            elif request.ticket is not None:
                request.ticket.cancel()
        self.pending = kept

    def update(self, now: float) -> None:
        """Advance the stop ramps, stop the sounds whose fade-out ended, and free the
        channels (and cache holds) of sounds that ended."""
        if self.pending:
            self.pending = [request for request in self.pending if request.waiting]
        backend = self.backend
        for channel, slot in list(self.slots.items()):
            if slot.stopping and not slot.ramping(now):
                backend.channel_stop(channel)
                self._free(channel)
                continue
            self._send(slot, now)
            if not backend.channel_busy(channel):
                self._free(channel)

    def apply_volumes(self, now: float) -> None:
        for slot in self.slots.values():
            self._send(slot, now)

    def shutdown(self) -> None:
        for request in self.pending:
            if request.ticket is not None:
                request.ticket.cancel()
        self.pending = []
        for channel in list(self.slots):
            self._free(channel)

    def _pick(self) -> int:
        for channel in self.channels:
            slot = self.slots.get(channel)
            if slot is None:
                return channel
            if not self.backend.channel_busy(channel):
                self._free(channel)
                return channel
        by_age = sorted(self.slots.values(), key=lambda s: s.seq)
        oldest = next((s for s in by_age if s.stopping), by_age[0])
        self.backend.channel_stop(oldest.channel)
        self._free(oldest.channel)
        return oldest.channel

    def _send(self, slot: Slot, now: float) -> None:
        level = quantize(self._sound_gain() * slot.gain(now))
        if level != slot.sent:
            slot.sent = level
            self.backend.channel_volume(slot.channel, level)

    def _free(self, channel: int) -> None:
        slot = self.slots.pop(channel, None)
        if slot is not None:
            self.cache.release(sound_key(slot.file))


class BlipRequest:
    """The newest blip asked for while its sound is being decoded (``pending_blip``)."""

    __slots__ = ("file", "spread", "volume", "step", "at", "ticket")

    def __init__(self, file: str, spread: float, volume: int, step: int, at: float) -> None:
        self.file = file
        self.spread = spread
        self.volume = volume
        self.step = step
        self.at = at                               # service time of the newest ask
        self.ticket: Ticket | None = None

    @property
    def waiting(self) -> bool:
        return self.ticket is not None and self.ticket.waiting


class BlipChannel:
    """F06's blips on channel 1 (``BLIP_CHANNEL``; ``play_blip``, SPEC §5). One blip at a
    time, played once; ``playing`` is the cache key held while it sounds. ``skipping`` is
    set by the service's ``set_skipping``."""

    def __init__(self, backend: MixerBackend, reader: AudioReader, cache: SizedLru,
                 loader: SoundLoader, *, sound_gain: Callable[[], float]) -> None:
        self.backend = backend
        self.reader = reader
        self.cache = cache
        self.loader = loader
        self._sound_gain = sound_gain
        self.pending: BlipRequest | None = None
        self.playing: Key | None = None
        self.skipping = False
        self._failed: OrderedDict[str, None] = OrderedDict()

    def failed(self, file: str) -> bool:
        """Whether ``file`` was silent as a blip this session: it is not read again (I-4)."""
        return file in self._failed

    def play(self, file: str, volume: int, spread: float, step: int, now: float) -> None:
        """A blip of ``file``: at once from the cache, else when its decode is ready."""
        if self.skipping or file in self._failed:
            return
        pending = self.pending
        if pending is not None:
            if pending.file == file and pending.spread == spread and pending.waiting:
                pending.volume, pending.step, pending.at = volume, step, now
                return                             # its key is in flight: no second read
            self._drop_pending()
        request = BlipRequest(file, spread, volume, step, now)
        ticket = self.loader.load(file, lambda sound, at: self._ready(request, sound, at), now,
                                  what="blip", spread=spread)
        if ticket.waiting:
            request.ticket = ticket
            self.pending = request

    def update(self) -> None:
        """A blip that ended releases its cache hold; a request whose ticket a reopen
        cancelled is forgotten."""
        if self.pending is not None and not self.pending.waiting:
            self.pending = None
        if self.playing is not None and not self.backend.channel_busy(BLIP_CHANNEL):
            self._release()

    def shutdown(self) -> None:
        """Forget the pending request and the blip playing (a reopen took its sound)."""
        self._drop_pending()
        self._release()

    def _ready(self, request: BlipRequest, sound: Any | None, now: float) -> None:
        """The loader's answer (at once for a hit, else from its ``update``): None is
        silence, logged once by the reader, and the path is not read again."""
        if self.pending is request:
            self.pending = None
        if sound is None:
            self._failed[request.file] = None
            while len(self._failed) > FAILED_FILES_MAX:
                self._failed.popitem(last=False)
            return
        if now - request.at > BLIP_STALE_S:
            return                                 # its glyph is long gone
        backend = self.backend
        backend.channel_stop(BLIP_CHANNEL)         # a new blip stops the last
        self._release()
        key = blip_key(request.file, request.spread)
        self.cache.hold(key)
        self.playing = key
        level = quantize(self._sound_gain() * curve(max(0, min(100, request.volume))))
        backend.channel_volume(BLIP_CHANNEL, level)
        played = sound.pick(request.step) if isinstance(sound, BlipSounds) else whole(sound)
        backend.channel_play(BLIP_CHANNEL, played, 0)

    def _drop_pending(self) -> None:
        request, self.pending = self.pending, None
        if request is not None and request.ticket is not None:
            request.ticket.cancel()

    def _release(self) -> None:
        key, self.playing = self.playing, None
        if key is not None:
            self.cache.release(key)


__all__ = ["BlipChannel", "BlipRequest", "EffectSlots", "Pending", "SOUND_KEY", "Slot",
           "UiPool", "UiRequest", "VoiceChannel", "drop_text", "sound_key"]

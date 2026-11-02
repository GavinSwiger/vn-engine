"""The story's audio: ``AudioState`` and the audio statements' executors (F08
``04-technical.md`` §4, §5.1, §6.3, §9, §10; ``07`` I-1 to I-3, I-11).

Why this module exists: the music sequence and the looping effects are part of the story, so
they live in ``GameState`` as one small frozen value of names and numbers (no positions,
fades, one-shots, voice, or volume settings: those are presentation, rebuilt from commands).
A save, a rollback, or a reload then plays the right music without re-running a line
(PR-F08-21, 22). The executors change ``interp.audio`` and hold one command each; nothing
is played here. The commands reach the presentation with the next line's burst.

Layering (as ``runtime/stage.py``): ``state.py`` and ``commands.py`` use ``AudioState``, and
the interpreter calls ``voice_attached``, ``end_voice``, ``AudioBurst``, and ``insert_sync``,
so this module sits below the interpreter and never imports it at load time. The four
executors are registered by ``interpreter.py``; they take ``Step`` from it when they run.

Pure (TR-F03-05, PR-F08-21): no file, clock, device, thread, or randomness. The files are
only names; the presentation reads them (F08 step 4 on).
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.runtime.commands import (AudioRestore, Command, EndVoice, PlayMusic, PlaySound,
                                     PlayVoice, QueueMusic, StopMusic, StopSound, StopVoice)
from engine.runtime.limits import (AUDIO_BURST_MAX, AUDIO_FILE_MAX_CHARS, MUSIC_SEQUENCE_MAX,
                                   ONESHOTS_PER_BURST, SOUND_LOOPS_MAX)
from engine.script import audio as nodes_audio
from engine.script.messages import format_message
from engine.script.nodes import Say as SayNode

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.script.nodes import Statement

_MUSIC_KEYS: Final = frozenset(("file", "loop", "volume"))
_SOUND_KEYS: Final = frozenset(("file", "volume"))
_AUDIO_KEYS: Final = frozenset(("music", "sounds"))       # I-3: "sounds", not "loops"
_VOLUME_RANGE: Final = (0, 100)
# As state.py: a lone high surrogate right before a lone low one reads back as one character.
_SURROGATE_PAIR = re.compile(r"[\ud800-\udbff][\udc00-\udfff]")


# --- The state (04 §4) ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MusicEntry:
    """One track of the music sequence. ``file`` as written, relative to ``audio/``;
    ``loop`` is the effective setting (queuing a track ends the loop of the one before it,
    SR-F08-15); ``volume`` 0–100 as written."""

    file: str
    loop: bool
    volume: int

    def to_json(self) -> dict[str, object]:
        return {"file": self.file, "loop": self.loop, "volume": self.volume}


@dataclass(frozen=True, slots=True)
class SoundLoop:
    """One looping effect: ``play sound "<file>" loop``."""

    file: str
    volume: int

    def to_json(self) -> dict[str, object]:
        return {"file": self.file, "volume": self.volume}


@dataclass(frozen=True, slots=True)
class AudioState:
    """The story's audio. ``music``: the playing track first, then the queue; ``()`` is
    silence; at most ``MUSIC_SEQUENCE_MAX``. ``sounds``: looping effects in start order,
    files unique, at most ``SOUND_LOOPS_MAX``. A restore plays the first looping track."""

    music: tuple[MusicEntry, ...] = ()
    sounds: tuple[SoundLoop, ...] = ()

    def to_json(self) -> dict[str, object]:
        """``{"music": [{"file", "loop", "volume"}], "sounds": [{"file", "volume"}]}``,
        fresh plain values (always written, F08 §10)."""
        return {"music": [entry.to_json() for entry in self.music],
                "sounds": [loop.to_json() for loop in self.sounds]}

    @staticmethod
    def from_json(obj: object) -> "AudioState":
        """Validate an untrusted saved ``audio`` value (§6.3): shapes, counts, and lengths
        are checked before any value is read or anything is built. Raises
        ``StateInvalid("audio")`` only; its text never holds any part of the input. Path
        *rules* are not checked: a bad path plays as missing with W29 (PR-F08-15)."""
        try:
            return _audio_from_json(obj)
        except _Invalid:
            pass
        except Exception:                   # defensive: the contract is StateInvalid only
            pass
        from engine.runtime.state import StateInvalid   # state.py imports this module
        raise StateInvalid("audio") from None

    def save_problem(self) -> str | None:
        """F11 C11 for this field: ``audio`` if ``from_json`` would refuse this state's JSON
        (only a hand-built state: the executors keep every limit, and script files are at
        most ``REF_MAX_CHARS``), ``lone_surrogate`` if a file wouldn't read back equal;
        else None. At most 80 entries, so it is cheap."""
        try:
            back = _audio_from_json(self.to_json())
        except Exception:                   # _Invalid, or a hand-built value of a wrong type
            return "audio"
        if back != self:
            return "audio"
        files = " ".join(e.file for e in (*self.music, *self.sounds))
        if not files.isascii() and _SURROGATE_PAIR.search(files):
            return "lone_surrogate"
        return None


EMPTY_AUDIO: Final = AudioState()


class _Invalid(Exception):
    pass


def _file(value: object) -> str:
    if type(value) is not str or not 0 < len(value) <= AUDIO_FILE_MAX_CHARS:
        raise _Invalid
    return value


def _volume(value: object) -> int:
    if type(value) is not int or not _VOLUME_RANGE[0] <= value <= _VOLUME_RANGE[1]:
        raise _Invalid
    return value


def _audio_from_json(obj: object) -> AudioState:
    if type(obj) is not dict or obj.keys() != _AUDIO_KEYS:
        raise _Invalid
    music, sounds = obj["music"], obj["sounds"]
    if (type(music) is not list or len(music) > MUSIC_SEQUENCE_MAX
            or type(sounds) is not list or len(sounds) > SOUND_LOOPS_MAX):
        raise _Invalid
    for entries, keys in ((music, _MUSIC_KEYS), (sounds, _SOUND_KEYS)):
        for entry in entries:               # shapes first, before any value is read
            if type(entry) is not dict or entry.keys() != keys:
                raise _Invalid
    tracks: list[MusicEntry] = []
    for entry in music:
        loop = entry["loop"]
        if type(loop) is not bool:
            raise _Invalid
        tracks.append(MusicEntry(_file(entry["file"]), loop, _volume(entry["volume"])))
    loops: list[SoundLoop] = []
    seen: set[str] = set()
    for entry in sounds:
        file = _file(entry["file"])
        if file in seen:                    # exact: files differing only in case are two
            raise _Invalid
        seen.add(file)
        loops.append(SoundLoop(file, _volume(entry["volume"])))
    return AudioState(tuple(tracks), tuple(loops))


# --- Bursts (07 I-2) -----------------------------------------------------------------------------

# The commands the executors hold, which the burst cap counts. ``PlayVoice``, ``EndVoice``,
# and ``AudioRestore`` are never dropped.
CAPPED: Final = frozenset((PlayMusic, QueueMusic, StopMusic, PlaySound, StopSound, StopVoice))


class AudioBurst:
    """The audio counters of the burst being held (``Interpreter._audio_burst``). Reset
    whenever the held commands are released or dropped."""

    __slots__ = ("held", "oneshots", "sync", "oneshots_logged")

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.held = 0                   # CAPPED commands kept
        self.oneshots = 0               # one-shot PlaySound kept (ONESHOTS_PER_BURST)
        self.sync = False               # a CAPPED command was dropped: send the state
        self.oneshots_logged = False

    def admit(self) -> bool:
        """Whether one more ``CAPPED`` command may be held (``Interpreter._hold``)."""
        if self.held >= AUDIO_BURST_MAX:
            self.sync = True
            return False
        self.held += 1
        return True


def insert_sync(held: list[Command], audio: AudioState) -> None:
    """``_release`` when ``AudioBurst.sync``: one ``AudioRestore(audio, "sync")`` right
    after the last kept ``CAPPED`` command (I-2), so the presentation ends the burst with
    the exact story state. Nothing when none is held (the burst was dropped)."""
    for i in range(len(held) - 1, -1, -1):
        if type(held[i]) in CAPPED:
            held.insert(i + 1, AudioRestore(audio, "sync"))
            return


# --- Voice (F03 07 C5; F08 07 I-1) ---------------------------------------------------------------

def voice_attached(cmd: Command) -> tuple[Command, ...]:
    """``take_checkpoint``'s ``attached`` for a checkpoint command: its ``PlayVoice`` when
    the line has a voice (``Say.voice``, filled from the node), else nothing. A restore
    holds the same with ``restored=True`` (the command's own flag)."""
    voice = getattr(cmd, "voice", None)
    if voice is None:
        return ()
    return (PlayVoice(cmd.sid, voice, cmd.restored),)       # type: ignore[attr-defined]


def end_voice(interp: "Interpreter", waiting: "Statement") -> None:
    """An accepted ``Advance`` of ``waiting``: hold ``EndVoice`` if it is a voiced line. It
    is released with the next burst (normally in the same frame); if that burst fails,
    ``StoryFailed``'s handler stops story audio (07 I-4)."""
    voice = getattr(waiting, "voice", None) if type(waiting) is SayNode else None
    if voice is not None:
        interp._hold(EndVoice(waiting.sid))


# --- Executors (04 §6.3; registered by interpreter.py) -------------------------------------------

def _continue() -> "Step":
    from engine.runtime.interpreter import Step     # below the interpreter (module docstring)
    return Step.CONTINUE


def run_play(interp: "Interpreter", stmt: nodes_audio.PlayAudio) -> "Step":
    """``play music`` replaces the sequence; ``play sound … loop`` adds or updates a loop
    (a 17th is refused with one WARNING and plays nothing); a one-shot changes no state and
    is held up to ``ONESHOTS_PER_BURST`` per burst (then dropped, one DEBUG record)."""
    audio = interp.audio
    file = stmt.audio_file
    if stmt.channel == "music":
        start = stmt.start
        current = start == "current"
        interp.audio = AudioState((MusicEntry(file, stmt.loop, stmt.volume),), audio.sounds)
        interp._hold(PlayMusic(file, stmt.loop, stmt.volume, stmt.fadein, stmt.fadeout,
                               stmt.restart or start is not None,      # SR-F08-12
                               None if current else start, current))  # type: ignore[arg-type]
        return _continue()
    if stmt.loop:
        sounds = audio.sounds
        loop = SoundLoop(file, stmt.volume)
        for i, other in enumerate(sounds):
            if other.file == file:                  # same file: its volume changes
                sounds = sounds[:i] + (loop,) + sounds[i + 1:]
                break
        else:
            if len(sounds) >= SOUND_LOOPS_MAX:
                interp.log.warning("%s, line %d: %s", stmt.file.ref, stmt.line,
                                   format_message("W-sound-loops", (file, SOUND_LOOPS_MAX)))
                return _continue()
            sounds = sounds + (loop,)
        interp.audio = AudioState(audio.music, sounds)
        interp._hold(PlaySound(file, True, stmt.volume, stmt.fadein))
        return _continue()
    burst = interp._audio_burst
    if burst.oneshots >= ONESHOTS_PER_BURST:
        if not burst.oneshots_logged:
            burst.oneshots_logged = True
            interp.log.debug("%s, line %d: more than %d one-shot sounds in one burst; the "
                             "rest are dropped.", stmt.file.ref, stmt.line, ONESHOTS_PER_BURST)
        return _continue()
    burst.oneshots += 1
    interp._hold(PlaySound(file, False, stmt.volume, stmt.fadein))
    return _continue()


def run_queue(interp: "Interpreter", stmt: nodes_audio.QueueMusic) -> "Step":
    """``queue music``: appended; the track before it stops looping (SR-F08-15). Past
    ``MUSIC_SEQUENCE_MAX`` the oldest entries go, which never changes the restore target
    (the first looping entry is the last one)."""
    audio = interp.audio
    entry = MusicEntry(stmt.audio_file, stmt.loop, stmt.volume)
    music = audio.music
    if music:
        last = music[-1]
        music = music[:-1] + (MusicEntry(last.file, False, last.volume), entry)
        if len(music) > MUSIC_SEQUENCE_MAX:
            music = music[-MUSIC_SEQUENCE_MAX:]
    else:
        music = (entry,)
    interp.audio = AudioState(music, audio.sounds)
    interp._hold(QueueMusic(stmt.audio_file, stmt.loop, stmt.volume, stmt.fadein))
    return _continue()


def run_stop(interp: "Interpreter", stmt: nodes_audio.StopAudio) -> "Step":
    """``stop music`` clears the sequence; ``stop sound`` every loop, or the one named;
    ``stop voice`` changes no state."""
    audio = interp.audio
    channel = stmt.channel
    if channel == "music":
        if audio.music:
            interp.audio = AudioState((), audio.sounds)
        interp._hold(StopMusic(stmt.fadeout))
    elif channel == "sound":
        file = stmt.audio_file
        sounds = () if file is None else tuple(s for s in audio.sounds if s.file != file)
        if sounds != audio.sounds:
            interp.audio = AudioState(audio.music, sounds)
        interp._hold(StopSound(file, stmt.fadeout))
    else:
        interp._hold(StopVoice(stmt.fadeout))
    return _continue()


def run_voice(interp: "Interpreter", stmt: nodes_audio.Voice) -> "Step":
    """``voice``: nothing at run time (SR-F08-20); the line below carries the file."""
    return _continue()


__all__ = ["AudioBurst", "AudioState", "CAPPED", "EMPTY_AUDIO", "MusicEntry", "SoundLoop",
           "end_voice", "insert_sync", "run_play", "run_queue", "run_stop", "run_voice",
           "voice_attached"]

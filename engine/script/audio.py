"""The audio statements ``play``, ``queue``, ``stop``, and ``voice`` (F08 ``04-technical.md``
§6.1, §6.2; ``02-script.md`` §3.1–3.5; load codes E140–E151).

Why this module exists: it turns audio lines into small nodes that hold the file as written
(relative to ``audio/``) and the options as numbers, so the runtime can change the story's
audio state and the launch check can look the files up. Every check that needs only the
line itself is made here, at load: the channel, the file's quotes and path rules
(SR-F08-01/02: E145, then E144, then F01's ``check_ref`` as E143), and each option. No
file is opened or listed. The checks that look across lines (W20, W23, W24) are in
``audio_checks.py``; the files themselves are looked up at launch (W21, W22, W25).

A line is read as *chunks* over F02's script tokens, like F04's stage lines: tokens that
touch are one chunk (``2.0``, ``-1``, ``50%``, ``1:30``), quoted text is one chunk holding
its value. A chunk is a WORD (one name), a NUMBER (``-?digits[.digits]``), TEXT, or OTHER.
Options come in any order, each once (SR-F08-05); the first problem on the line is its one
error. A trailing ``:`` is E146 when nothing else is wrong.
"""

import re
from dataclasses import dataclass
from typing import Literal

from engine.core.constants import AUDIO_FADE_RANGE, AUDIO_VOLUME_RANGE
from engine.core.errors import AssetRefError
from engine.core.paths import check_ref
from engine.script.lexer import COLON, FWCOLON, NAME, STRING, TAIL_SCRIPT, RawStatement
from engine.script.nodes import Statement
from engine.script.statements import ParseContext, StatementSpec, register
from engine.script.suggest import suggest

# SR-F08-02 (PR-F08-14's outcome): the extensions the engine plays, matched lower-cased.
PLAYABLE_EXTS: frozenset[str] = frozenset((".ogg", ".opus", ".flac", ".mp3", ".wav"))
AUDIO_FOLDER = "audio/"
FROM_RANGE = (0, 3600)                           # SR-F08-12: ``from`` seconds

# The option words of SR-F08-05 (and ``crossfade``, recognized for E148, SR-F08-13).
VALUE_OPTIONS = frozenset(("fadein", "fadeout", "volume", "from"))
FLAG_OPTIONS = frozenset(("loop", "once", "restart"))
OPTION_WORDS = VALUE_OPTIONS | FLAG_OPTIONS | {"crossfade"}

# What each statement lists in E146 (in the order 02 §5.1 gives for play).
STATEMENT_OPTIONS: dict[str, tuple[str, ...]] = {
    "play": ("fadein", "fadeout", "volume", "loop", "once", "restart", "from"),
    "queue": ("fadein", "volume", "loop", "once"),
    "stop": ("fadeout",),
    "voice": (),
}
# The channels each statement takes (E140's "takes" part).
STATEMENT_CHANNELS: dict[str, tuple[str, ...]] = {
    "play": ("music", "sound"), "queue": ("music",), "stop": ("music", "sound", "voice")}
CHANNELS = frozenset(("music", "sound", "voice"))

# Chunk kinds.
WORD = "word"
NUMBER = "number"
TEXT = "string"
OTHER = "other"

_NUMBER_RE = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
_UNITS_RE = re.compile(r"-?[0-9]+(?:\.[0-9]+)?[^\W\d_]+")
_PERCENT_RE = re.compile(r"(-?[0-9]+(?:\.[0-9]+)?)%")


# --- Nodes (04 §6.1) -------------------------------------------------------------------------

@dataclass(slots=True, kw_only=True)
class PlayAudio(Statement):
    """``play music|sound "<file>" [options]`` (SR-F08-05–13). ``audio_file`` is the file
    as written, relative to ``audio/`` (named so because ``Node.file`` is the script file).
    ``fadein``/``fadeout`` are None when the line doesn't give them (the config default
    applies at run); ``start`` is ``from``'s value, which implies a restart (SR-F08-12)."""

    channel: Literal["music", "sound"]
    audio_file: str
    loop: bool                                   # music: True unless once; sound: loop given
    volume: int = 100
    fadein: float | None = None
    fadeout: float | None = None
    restart: bool = False
    start: float | Literal["current"] | None = None

    def identity_key(self) -> tuple[str, ...]:
        return ("play", self.channel, self.audio_file)


@dataclass(slots=True, kw_only=True)
class QueueMusic(Statement):
    """``queue music "<file>" [options]`` (SR-F08-14–16). ``loop`` is as written (True
    unless ``once``); only the last track of the sequence really loops (SR-F08-15)."""

    audio_file: str
    loop: bool = True
    volume: int = 100
    fadein: float | None = None

    def identity_key(self) -> tuple[str, ...]:
        return ("queue", self.audio_file)


@dataclass(slots=True, kw_only=True)
class StopAudio(Statement):
    """``stop music|sound|voice ["<file>"] [fadeout N]`` (SR-F08-17–18b). Only ``stop
    sound`` has a file (PR-F08-34)."""

    channel: Literal["music", "sound", "voice"]
    audio_file: str | None = None
    fadeout: float | None = None

    def identity_key(self) -> tuple[str, ...]:
        return ("stop", self.channel, self.audio_file or "")


@dataclass(slots=True, kw_only=True)
class Voice(Statement):
    """``voice "<file>"`` (SR-F08-19–21): does nothing when run; ``audio_checks`` attaches
    the file to the line below as ``Say.voice``."""

    audio_file: str

    def identity_key(self) -> tuple[str, ...]:
        return ("voice", self.audio_file)


AUDIO_NODES: tuple[type[Statement], ...] = (PlayAudio, QueueMusic, StopAudio, Voice)


# --- Files (SR-F08-01, 02) -------------------------------------------------------------------

def suffix(file: str) -> str:
    """The lower-cased extension of the last segment, ``""`` if none (as F01's
    ``AssetManager`` and ``config_schema.is_audio_ref`` read it)."""
    name = file.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def audio_ref(file: str) -> str:
    """The game-folder ref of a file as written: ``"audio/" + file``."""
    return AUDIO_FOLDER + file


def file_problem(file: str) -> tuple[str, tuple] | None:
    """The load error of a file as written, as ``(code, args)``, or None (04 §6.2, in this
    order): no extension → E145; starts with ``audio/`` in any case → E144;
    ``check_ref("audio/" + file)`` refuses it → E143 with F01's reason. No file-system call.
    Agrees with ``engine.core.config_schema.is_audio_ref`` (the config side of 07 I-6)."""
    if suffix(file) == "":
        return "E145", (file,)
    if file[:len(AUDIO_FOLDER)].casefold() == AUDIO_FOLDER:
        return "E144", (file,)
    try:
        check_ref(audio_ref(file))
    except AssetRefError as exc:
        return "E143", (file, exc.reason)
    return None


def is_playable(file: str) -> bool:
    """True if the file's extension is one the engine plays (else W23 at load)."""
    return suffix(file) in PLAYABLE_EXTS


# --- Chunks ------------------------------------------------------------------------------------

@dataclass(slots=True)
class _Chunk:
    kind: str
    text: str                                    # as written; TEXT: the value (no quotes)
    line: int
    column: int
    end: int                                     # the column just after the chunk


def _chunks(raw: RawStatement) -> tuple[list[_Chunk], bool]:
    """The chunks after the statement word, and whether a trailing ``:`` was set aside."""
    tokens = list(raw.tokens[1:])
    colon = bool(tokens) and tokens[-1].kind in (COLON, FWCOLON) and raw.ends_with_colon
    if colon:
        tokens.pop()
    chunks: list[_Chunk] = []
    current: list = []

    def close() -> None:
        if current:
            text = "".join(t.text for t in current)
            first, last = current[0], current[-1]
            if _NUMBER_RE.fullmatch(text):
                kind = NUMBER
            elif len(current) == 1 and first.kind == NAME:
                kind = WORD
            else:
                kind = OTHER
            chunks.append(_Chunk(kind, text, first.line, first.column,
                                 last.column + len(last.text)))
            current.clear()

    for token in tokens:
        if token.kind == STRING:
            close()
            chunks.append(_Chunk(TEXT, token.text, token.line, token.column, token.column))
            continue
        if current and (token.line != current[-1].line
                        or token.column != current[-1].column + len(current[-1].text)):
            close()
        current.append(token)
    close()
    return chunks, colon


def _written(raw: RawStatement, chunks: list[_Chunk]) -> str:
    """The source text covering ``chunks`` (none of them TEXT), as written."""
    first, last = chunks[0], chunks[-1]
    if first.line == last.line:
        return raw.texts.get(first.line, "")[first.column - 1:last.end - 1]
    return " ".join(c.text for c in chunks)


def _is_option(chunk: _Chunk) -> bool:
    return chunk.kind == WORD and (chunk.text in OPTION_WORDS or chunk.text == "with")


# --- Reading a line (SR-F08-05) --------------------------------------------------------------

class _Line:
    """One audio line being read; every method returns None (or False) with the error
    pending on the statement."""

    def __init__(self, raw: RawStatement, ctx: ParseContext, chunks: list[_Chunk]) -> None:
        self.raw = raw
        self.ctx = ctx
        self.word = raw.word
        self.chunks = chunks
        self.channel: str | None = None

    @property
    def name(self) -> str:
        """The statement as messages name it: ``play sound``, ``queue music``, ``voice``."""
        return self.word if self.channel is None else f"{self.word} {self.channel}"

    def error(self, code: str, *args: object) -> None:
        self.ctx.error(code, *args)

    def channel_word(self) -> str | None:
        """E140/E141: the channel, the first chunk."""
        word = self.word
        first = self.chunks[0] if self.chunks else None
        if first is None or first.kind != WORD or _is_option(first):
            self.error("E140", "needs", word)
            return None
        text = first.text
        if text not in STATEMENT_CHANNELS[word]:
            if text in CHANNELS:                 # play voice, queue sound, queue voice
                following = self.chunks[1] if len(self.chunks) > 1 else None
                file = following.text if following is not None and following.kind == TEXT \
                    else None
                self.error("E141", word, text, file)
            else:
                self.error("E140", "unknown", word, text,
                           suggest(text, STATEMENT_CHANNELS[word]))
            return None
        self.channel = text
        return text

    def file(self, rest: list[_Chunk], *, optional: bool = False) -> str | None:
        """E142–E145: the file, the first chunk of ``rest``. With ``optional`` (``stop
        sound``) a missing file is ``""``."""
        first = rest[0] if rest else None
        if first is None or _is_option(first):
            if optional:
                return ""
            self.error("E142", "needs", self.name)
            return None
        if first.kind != TEXT:
            if optional and (first.kind == NUMBER or not ("/" in first.text
                                                          or "." in first.text)):
                return ""                        # not a file: E146 reads it with the options
            self.error("E142", "quotes", self.name, _written(self.raw, [first]))
            return None
        if first.text == "":
            self.error("E142", "needs", self.name)
            return None
        problem = file_problem(first.text)
        if problem is not None:
            self.error(problem[0], *problem[1])
            return None
        return first.text

    def options(self, rest: list[_Chunk], after: str, last: str) -> dict[str, object] | None:
        """The options in ``rest`` (SR-F08-05): E146–E151. ``after`` is what the line has
        before them as written and ``last`` what it is (``"file"``, ``"channel"``), for
        E146's left-over form."""
        given: dict[str, object] = {}
        index = 0
        while index < len(rest):
            chunk = rest[index]
            if self.word == "voice":
                self.error("E148", "voice")
                return None
            if chunk.kind != WORD:
                self.left_over(rest, index, after, last)
                return None
            word = chunk.text
            if word == "with":
                self.error("E146", "with", self.word)
                return None
            if word not in OPTION_WORDS:
                if word.lower() in OPTION_WORDS:
                    self.error("E146", "case", self.word, word, word.lower())
                else:
                    options = STATEMENT_OPTIONS[self.word]
                    self.error("E146", "unknown", self.word, word, suggest(word, options))
                return None
            refused = self.refused(word)
            if refused is not None:
                self.error("E148", *refused)
                return None
            if word in given:
                self.error("E147", "twice", word)
                return None
            other = {"loop": "once", "once": "loop"}.get(word)
            if other is not None and other in given:
                self.error("E147", "clash", other, word)
                return None
            if word in FLAG_OPTIONS:
                given[word] = True
                after = last = word
                index += 1
                continue
            value_chunk = rest[index + 1] if index + 1 < len(rest) else None
            if value_chunk is None or _is_option(value_chunk):
                self.error("E149", word)
                return None
            value = self.value(word, value_chunk)
            if value is None:
                return None
            given[word] = value
            after = f"{word} {self.shown(value_chunk)}"
            last = word
            index += 2
        return given

    def shown(self, chunk: _Chunk) -> str:
        return f'"{chunk.text}"' if chunk.kind == TEXT else _written(self.raw, [chunk])

    def left_over(self, rest: list[_Chunk], index: int, after: str, last: str) -> None:
        """E146: chunks no option takes, up to the next option word."""
        stop = index
        while stop < len(rest) and not _is_option(rest[stop]):
            stop += 1
        run = rest[index:stop]
        if len(run) == 1 and run[0].kind == TEXT:
            self.error("E146", "second_file", self.word, run[0].text)
            return
        written = " ".join(self.shown(c) for c in run) if any(c.kind == TEXT for c in run) \
            else _written(self.raw, run)
        self.error("E146", "left", written, after, last, self.word)

    def refused(self, option: str) -> tuple | None:
        """E148's form when this statement or channel doesn't take ``option``."""
        word, channel = self.word, self.channel
        if word == "stop":
            return None if option == "fadeout" else ("stop", channel)
        if word == "queue":
            if option == "fadeout":
                return ("queue_fadeout",)
            if option in ("restart", "from", "crossfade"):
                return ("queue_start", option)
            return None
        if option == "crossfade":
            return ("crossfade",)
        if channel == "sound" and option in ("fadeout", "restart", "from"):
            return ("sound_" + option,)
        return None

    def value(self, option: str, chunk: _Chunk) -> object | None:
        """The value of ``option`` (E150, E151)."""
        text = chunk.text
        quoted = chunk.kind != NUMBER
        if option == "volume":
            low, high = AUDIO_VOLUME_RANGE
            # A whole number of at most 6 characters (int() refuses very long digit runs).
            if chunk.kind == NUMBER and "." not in text and len(text) <= 6 \
                    and low <= int(text) <= high:
                return int(text)
            percent = _PERCENT_RE.fullmatch(text) if chunk.kind == OTHER else None
            if percent is not None:
                self.error("E151", "percent", percent.group(1))
            else:
                self.error("E151", "range", f'"{text}"' if quoted else text)
            return None
        if option == "from":
            if chunk.kind == WORD and text == "current":
                return "current"
            low, high = FROM_RANGE
        else:
            low, high = AUDIO_FADE_RANGE
        if chunk.kind == NUMBER:
            number = float(text) + 0.0               # -0 is 0.0
            if low <= number <= high:
                return number
            self.error("E150", "range", option, text)
            return None
        form = "units" if chunk.kind != TEXT and _UNITS_RE.fullmatch(text) else "other"
        self.error("E150", form, option, text)
        return None

    def finish(self, colon: bool) -> bool:
        if colon:
            self.error("E146", "colon", self.word)
            return False
        return True


def _start(raw: RawStatement, ctx: ParseContext) -> tuple[_Line, bool] | None:
    if raw.pending or any(t.unclosed for t in raw.tokens):
        return None                              # the reader's error (E52, E54, …) is first
    chunks, colon = _chunks(raw)
    return _Line(raw, ctx, chunks), colon


def _seconds(given: dict[str, object], option: str) -> float | None:
    value = given.get(option)
    return value if isinstance(value, float) else None


def _volume(given: dict[str, object]) -> int:
    value = given.get("volume", 100)
    return value if isinstance(value, int) else 100


def parse_play(raw: RawStatement, ctx: ParseContext) -> PlayAudio | None:
    started = _start(raw, ctx)
    if started is None:
        return None
    line, colon = started
    channel = line.channel_word()
    if channel is None:
        return None
    rest = line.chunks[1:]
    file = line.file(rest)
    if file is None:
        return None
    given = line.options(rest[1:], f'"{file}"', "file")
    if given is None or not line.finish(colon):
        return None
    start = given.get("from")
    return PlayAudio(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                     channel="music" if channel == "music" else "sound", audio_file=file,
                     loop="loop" in given if channel == "sound" else "once" not in given,
                     volume=_volume(given), fadein=_seconds(given, "fadein"),
                     fadeout=_seconds(given, "fadeout"), restart="restart" in given,
                     start="current" if start == "current" else _seconds(given, "from"))


def parse_queue(raw: RawStatement, ctx: ParseContext) -> QueueMusic | None:
    started = _start(raw, ctx)
    if started is None:
        return None
    line, colon = started
    if line.channel_word() is None:
        return None
    rest = line.chunks[1:]
    file = line.file(rest)
    if file is None:
        return None
    given = line.options(rest[1:], f'"{file}"', "file")
    if given is None or not line.finish(colon):
        return None
    return QueueMusic(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                      audio_file=file, loop="once" not in given, volume=_volume(given),
                      fadein=_seconds(given, "fadein"))


def parse_stop(raw: RawStatement, ctx: ParseContext) -> StopAudio | None:
    started = _start(raw, ctx)
    if started is None:
        return None
    line, colon = started
    channel = line.channel_word()
    if channel is None:
        return None
    rest = line.chunks[1:]
    if channel != "sound":
        if rest and rest[0].kind == TEXT:
            ctx.error("E148", "stop_file", channel)
            return None
        file = ""
    else:
        found = line.file(rest, optional=True)
        if found is None:
            return None
        file = found
    options = rest[1:] if file else rest
    given = line.options(options, f'"{file}"' if file else f"stop {channel}",
                         "file" if file else "channel")
    if given is None or not line.finish(colon):
        return None
    return StopAudio(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                     channel=channel,  # type: ignore[arg-type]  # one of STATEMENT_CHANNELS
                     audio_file=file or None, fadeout=_seconds(given, "fadeout"))


def parse_voice(raw: RawStatement, ctx: ParseContext) -> Voice | None:
    started = _start(raw, ctx)
    if started is None:
        return None
    line, colon = started
    file = line.file(line.chunks)
    if file is None:
        return None
    if line.options(line.chunks[1:], f'"{file}"', "file") is None or not line.finish(colon):
        return None
    return Voice(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                 audio_file=file)


for _spec in (
    StatementSpec(word="play", placement="story", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_play),
    StatementSpec(word="queue", placement="story", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_queue),
    StatementSpec(word="stop", placement="story", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_stop),
    StatementSpec(word="voice", placement="story", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_voice),
):
    register(_spec)
del _spec

__all__ = ["AUDIO_FOLDER", "AUDIO_NODES", "FROM_RANGE", "OPTION_WORDS", "PLAYABLE_EXTS",
           "PlayAudio", "QueueMusic", "STATEMENT_OPTIONS", "StopAudio", "Voice", "audio_ref",
           "file_problem", "is_playable", "parse_play", "parse_queue", "parse_stop",
           "parse_voice", "suffix"]

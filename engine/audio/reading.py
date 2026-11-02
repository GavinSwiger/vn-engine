"""Reading an audio file, and the audio log's once-per-path cap (F08 ``04-technical.md`` §7.4,
§8, §12; ``02-script.md`` §5.4 W26, W29).

Why this module exists: every audio file is read the same way, through
``GamePaths.read_file("audio/<file>", max_bytes)`` on the main thread, and sniffed before any
decode, and a missing, blocked, huge, or broken file plays as silence with one log line, never
an exception (PR-F08-15, 16). Each message is logged once per path per session, for at most
``AUDIO_LOG_PATHS_MAX`` paths; after that one summary WARNING, and nothing more (as F01's
``AssetManager._problem``, SEC-F01-05). Content strings go through ``echo()``.

F08 step 4 reads effects (``read_sound``); step 5 music (``read_music``: 64 MB, no length
check; the backend passes the extension as SDL's type hint) with the W29 form of a missing
restored track; step 6 voice lines (``read_sound`` with ``what="voice"``; a restored line's
missing voice is W29); step 7 restored effects, and W29 for a restored file whose extension
the engine can't play (a saved state's paths were never checked at load). A missing file's
did-you-mean is F01's (``AssetMissing.suggestion``, ``04`` §7.4). F06 step 2: blips are read
like effects (``what="blip"``), and W49 is the long pitched blip's text.
"""

import logging
from collections import OrderedDict
from typing import Final

from engine.audio.limits import (AUDIO_LOG_PATHS_MAX, FAILED_FILES_MAX, MUSIC_MAX_BYTES,
                                 SOUND_MAX_BYTES, SOUND_MAX_SECONDS)
from engine.audio.sniff import FORMAT_NAMES, Sniffed, declared_seconds, sniff
from engine.core.errors import (AssetMissing, AssetNotFile, AssetRefError, AssetTooLarge,
                                AssetUnreadable)
from engine.core.logsetup import get_logger
from engine.core.paths import GamePaths
from engine.core.redact import echo

AUDIO_FOLDER: Final = "audio/"
MSG_TOO_MANY_AUDIO_PROBLEMS: Final = ("Too many audio problems in this session — further audio "
                                      "warnings and errors are not logged")

_log = get_logger("audio")


def suffix(file: str) -> str:
    """The lower-cased extension of the last segment (``script/audio.py``'s ``suffix``)."""
    name = file.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


# --- W26 texts (02 §5.4; the forms 02 leaves open are drafts, 07 I-14, 06 G3/G4) ------------

def w26_missing(file: str, suggestion: str | None = None) -> str:
    text = f"{echo(AUDIO_FOLDER + file)} is missing, so it plays as silence."
    if suggestion is not None:
        text += f' Did you mean "{echo(suggestion)}"?'
    return text


def w26_unreadable(file: str) -> str:
    return (f"{echo(AUDIO_FOLDER + file)} couldn't be read, so it plays as silence. Check that "
            f"another program isn't locking it.")


_A_FORMATS: Final = frozenset((".flac", ".wav"))      # "a FLAC", "a WAV"; "an Ogg Vorbis", …


def w26_not_really(file: str) -> str:
    ext = suffix(file)
    article = "a" if ext in _A_FORMATS else "an"
    return (f"{echo(AUDIO_FOLDER + file)} can't be played: it is damaged or isn't really "
            f"{article} {FORMAT_NAMES.get(ext, ext)} file. Export it again as {echo(ext)}.")


def w26_too_large(file: str, max_bytes: int) -> str:                    # draft (G3)
    return (f"{echo(AUDIO_FOLDER + file)} is larger than {max_bytes // (1 << 20)} MB, so it "
            f"plays as silence. Export it again in a smaller file.")


def w26_too_long(file: str) -> str:                                     # draft (G3)
    return (f"{echo(AUDIO_FOLDER + file)} is longer than {SOUND_MAX_SECONDS // 60} minutes, "
            f"so it plays as silence. Effects and voice lines can be at most "
            f"{SOUND_MAX_SECONDS // 60} minutes long.")


def w49_long_blip(file: str, seconds: float) -> str:
    """W49 (F06 ``SPEC.md`` §3; area ``audio``, once per path): a blip with ``blip_pitch``
    whose file is longer than 0.5 s plays unpitched. The text is ``script/messages.py``'s
    W49, which ``audio`` can't import (ADR-0002)."""
    return (f"{echo(AUDIO_FOLDER + file)} is {seconds:.1f} seconds long, so it plays without "
            f"blip_pitch. Blips with blip_pitch must be at most 0.5 seconds; trim the file to "
            f"one short sound.")


def w29_missing(file: str, what: str) -> str:
    """W29's first form: a restored game names a file that is missing."""
    return (f"A restored game plays {echo(AUDIO_FOLDER + file)}, which is missing, so the "
            f"{what} is silent.")


def w29_unplayable(file: str, what: str) -> str:                       # draft (06 G4)
    """W29 for a restored file whose extension the engine can't play (``bgm/x.mid``)."""
    return (f"A restored game plays {echo(AUDIO_FOLDER + file)}, which isn't a kind of file "
            f"the engine can play, so the {what} is silent.")


def w29_blocked(error: AssetRefError, what: str) -> str:
    """F01's blocked-path text + ``, so the <what> is silent.`` (W29's second form)."""
    return f"{error.message}, so the {what} is silent."


class AudioLog:
    """The audio log area (``vn.audio``): each (message kind, path) once per session, at
    most ``AUDIO_LOG_PATHS_MAX`` paths, then one summary WARNING and nothing more."""

    def __init__(self, logger: logging.Logger = _log, *,
                 max_paths: int = AUDIO_LOG_PATHS_MAX) -> None:
        self._logger = logger
        self._max_paths = max_paths
        self._paths: set[str] = set()
        self._logged: set[tuple[str, str]] = set()
        self._capped = False

    def problem(self, kind: str, file: str, message: str, *, code: str | None = "W26",
                level: int = logging.WARNING) -> None:
        """Log ``message`` unless this ``kind`` was already logged for ``file``."""
        key = (kind, file)
        if key in self._logged:
            return
        if file not in self._paths:
            if len(self._paths) >= self._max_paths:
                if not self._capped:
                    self._capped = True
                    self._logger.warning("%s", MSG_TOO_MANY_AUDIO_PROBLEMS)
                return
            self._paths.add(file)
        self._logged.add(key)
        extra = {"code": code} if code is not None else None
        self._logger.log(level, "%s", message, extra=extra)


class AudioReader:
    """Reads and sniffs audio files for the service (main thread only)."""

    def __init__(self, paths: GamePaths | None, log: AudioLog) -> None:
        self.paths = paths
        self.log = log
        self._failed: OrderedDict[str, None] = OrderedDict()

    def failed(self, file: str) -> bool:
        """True if ``file`` was too large, too long, or not what its extension says this
        session: it is not read again. A missing or unreadable file is read again (cheap,
        and it may appear); its message is still logged only once."""
        return file in self._failed

    def mark_failed(self, file: str) -> None:
        self._failed[file] = None
        self._failed.move_to_end(file)
        while len(self._failed) > FAILED_FILES_MAX:
            self._failed.popitem(last=False)

    def read_sound(self, file: str, *, what: str = "effect",
                   restored: bool = False) -> Sniffed | None:
        """§7.4 for an effect or voice line: the sniffed bytes of ``audio/<file>``, or None
        (silence) after logging the reason once. An extension the engine can't play is
        silent with no message here (W23 was given at load), except in a restored state
        (W29). ``what`` names it in W29 (``effect``, ``voice``); ``restored``: a missing
        file gets W29."""
        if not self._playable(file, what, restored):
            return None
        sniffed = self._read(file, SOUND_MAX_BYTES, what, restored=restored)
        if sniffed is None:
            return None
        seconds = declared_seconds(sniffed)
        if seconds is not None and seconds > SOUND_MAX_SECONDS:
            self.log.problem("long", file, w26_too_long(file))
            self.mark_failed(file)
            return None
        return sniffed

    def read_music(self, file: str, *, restored: bool = False) -> Sniffed | None:
        """§7.4 for a music track: the sniffed bytes of ``audio/<file>`` (at most
        ``MUSIC_MAX_BYTES``; music is streamed, so no length check), or None (silence)
        after logging the reason once. ``restored``: a missing file gets W29."""
        if not self._playable(file, "music", restored):
            return None
        return self._read(file, MUSIC_MAX_BYTES, "music", restored=restored)

    def _playable(self, file: str, what: str, restored: bool) -> bool:
        """Whether to read ``file`` at all: not when it failed before, nor when its
        extension isn't one the engine plays. A script's own unplayable name was W23 at
        load; a restored state's was never checked, so it is W29 here (AC-F08-39)."""
        if self.failed(file):
            return False
        if suffix(file) in FORMAT_NAMES:
            return True
        if restored:
            self.log.problem("unplayable", file, w29_unplayable(file, what), code="W29")
        return False

    def _read(self, file: str, max_bytes: int, what: str, *,
              restored: bool = False) -> Sniffed | None:
        ref = AUDIO_FOLDER + file
        log = self.log
        try:
            if self.paths is None:            # no game folder: nothing exists
                raise AssetMissing(ref, None)
            data = self.paths.read_file(ref, max_bytes=max_bytes)
        except AssetMissing as error:
            if restored:
                log.problem("missing", file, w29_missing(file, what), code="W29")
                return None
            suggestion = error.suggestion
            if suggestion is not None and suggestion.startswith(AUDIO_FOLDER):
                suggestion = suggestion[len(AUDIO_FOLDER):]
            log.problem("missing", file, w26_missing(file, suggestion))
            return None
        except AssetRefError as error:
            log.problem("blocked", file, w29_blocked(error, what), code="W29",
                        level=logging.ERROR)
            return None
        except AssetTooLarge:
            log.problem("large", file, w26_too_large(file, max_bytes))
            self.mark_failed(file)
            return None
        except (AssetNotFile, AssetUnreadable):
            log.problem("unreadable", file, w26_unreadable(file))
            return None
        sniffed = sniff(data, suffix(file))
        if sniffed is None:
            log.problem("damaged", file, w26_not_really(file))
            self.mark_failed(file)
        return sniffed


__all__ = ["AUDIO_FOLDER", "AudioLog", "AudioReader", "MSG_TOO_MANY_AUDIO_PROBLEMS", "suffix",
           "w26_missing", "w26_not_really", "w26_too_large", "w26_too_long", "w26_unreadable",
           "w29_blocked", "w29_missing", "w29_unplayable", "w49_long_blip"]

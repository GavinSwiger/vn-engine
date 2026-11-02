"""The launch audio file check: W21, W22, W25, and W31's launch form (F08 ``04-technical.md``
§6.4 with ``07`` I-7; ``02-script.md`` §5.3, SR-F08-04, 18, 23; PR-F08-17; AC-F08-06).

Why this module exists: a misspelled audio file isn't an error anywhere (it plays as
silence, PR-F08-16), so without this check the author would only notice the silence. Once
per launch, ``AudioFileCheck`` looks up every file named by ``play``, ``queue``,
``stop sound "<file>"``, and ``voice`` (F07: a menu's own ``voice`` too), and each
``[audio.loop_start]`` key, and reports what's missing. F06: ``blips`` adds the
``(file, define)`` of each ``define``d ``Character`` with ``blip``; a missing one is W21 at
the define, counted with the music and sound files and looked up first. They are
warnings: the game always starts. It is ``LaunchJob``'s phase after F04's stage check (clean defines only, I-7); the
app gives it ``AudioFiles`` built on its ``GamePaths``, and headless runs give none, so it
is skipped there.

Where it looks: ``GamePaths.list_dir``, which is ``resolve`` plus its cached listing of one
folder (``04`` §2: the launch index is ``GamePaths.resolve``'s listing cache). Each folder
holding a named file is listed once; a file exists when its name is among the listed files.
No file is opened and ``walk_files`` is never used. Not a ``resolve`` per file: measured on
Windows 11 with 5,000 files in one folder, a ``resolve`` of an existing file takes about
0.2 ms (a strict realpath each), and F01's did-you-mean (difflib, cutoff 0.8) about 40 ms
for one near miss, which can't be sliced. So the did-you-mean follows F01's rule segment by
segment (the exact name, else a case-only difference, else the closest name; folders for
the folders, files for the last segment), with F02's distance through ``SuggestPool``, in
steps like F04's W12. A case-only difference gives W21's case form.

Passes (``step()`` does one unit and returns True when done; the result doesn't depend on
the slicing):

1. collect: ``AUDIO_CHECK_CHUNK`` statements per step, in reading order. Files whose
   extension the engine can't play were W23 at load and are left out (they play as silence
   with no second message, ``04`` §6.2).
2. look up: at most ``AUDIO_CHECK_REFS`` distinct refs per step, or one new folder listing
   (a step of its own): the music and sound files in order of first use, then the voices,
   then the ``[audio.loop_start]`` keys in config order.
3. format: one kept record per step; a did-you-mean pauses (yields) while it is found,
   a new folder listing or ``SUGGEST_STEP_WORK`` table rows at a time.

Records, in this order: W21 (one per missing music or sound file, at its first use, counting
the other lines that use it), the one W22 (the first ``W22_LINES`` missing voice files in
order of first use, then ``…and N more.``), then per loop key W25 (no such file) or W31 (a
file that isn't ``.ogg``/``.opus``). At most ``SCRIPT_AUDIO_WARN_LIMIT`` W21/W25/W31
records are kept, then one W20s line counting the rest (the load check's cap and summary).
Logged by ``app/loading.py`` in the ``script`` area (``04`` §6.4).

The texts are here, not in ``script/messages.py``, while F07 owns that file; they move there
unchanged. The forms ``02`` gives only by example are drafts (``06`` G4): W21's
no-suggestion and ``stop sound`` forms and where ``(also on N other lines)`` goes (last, as
AC-F08-06 reads), W22's line separator (a new line) and its did-you-mean on a case-only
difference, and W25's case and no-suggestion forms (W21's).

Pure (TR-F03-05): no file, clock, or randomness; listings come through ``AudioFiles``.
"""

from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import islice

from engine.core.errors import AssetRefError
from engine.core.paths import DirListing
from engine.core.redact import truncate
from engine.runtime.images import ImageSource
from engine.script.audio import PLAYABLE_EXTS, PlayAudio, QueueMusic, StopAudio, Voice, suffix
from engine.script.diagnostics import ScriptWarning
from engine.script.limits import SCRIPT_AUDIO_WARN_LIMIT, SCRIPT_MESSAGE_MAX_CHARS
from engine.script.messages import format_message, show
from engine.script.suggest import SuggestPool

AUDIO_CHECK_CHUNK = 1_000       # statements per step of the collect pass (about 2 ms)
AUDIO_CHECK_REFS = 1_000        # refs looked up per step (AC-F08-06: at most 2,000)
W22_LINES = 5                   # missing voice files named in W22
LOOP_EXTS = frozenset((".ogg", ".opus"))       # loop points work only in these (C4)
AUDIO_DIR = "audio"
AUDIO_CHECK_CODES = frozenset(("W21", "W22", "W25", "W31", "W20s"))   # logged in ``script``

ListDir = Callable[[str], DirListing | None]

_COLLECT, _ENTRIES, _LOOK_UP, _FORMAT, _DONE = range(5)
_SOUND, _VOICE, _LOOP = range(3)


@dataclass(frozen=True)
class AudioFiles:
    """The check's view of the game: ``list_dir(ref)`` lists one folder (``GamePaths.
    list_dir``: None if missing or not a folder; may raise ``AssetRefError``), and
    ``loop_keys`` are the ``[audio.loop_start]`` keys in config order. ``from_files``
    builds it from game-relative refs (tests and tools)."""
    list_dir: ListDir
    loop_keys: tuple[str, ...] = ()

    @classmethod
    def from_files(cls, refs: Iterable[str], loop_keys: Iterable[str] = ()) -> "AudioFiles":
        return cls(ImageSource.from_files(refs).list_dir, tuple(loop_keys))


@dataclass(slots=True)
class _Use:
    """A file's first use and how many statements use it."""
    stmt: object
    count: int = 1


@dataclass(slots=True)
class _Folder:
    files: frozenset[str]
    dirs: frozenset[str]
    pools: dict[bool, SuggestPool]


class AudioFileCheck:
    """``step()`` does one unit of work and returns True when done; ``warnings`` is then
    final (module docstring)."""

    def __init__(self, program: object, files: AudioFiles,
                 blips: Iterable[tuple[str, object]] = ()) -> None:
        self.program = program
        self.files = files
        self.warnings: tuple[ScriptWarning, ...] = ()
        self._statements: Iterator[object] = program.iter_statements()  # type: ignore[attr-defined]
        self._pass = _COLLECT
        self._sounds: dict[str, _Use] = {}              # first-use order
        self._voices: dict[str, _Use] = {}
        self._entries: list[tuple[int, str, _Use | None]] = []
        self._at = 0
        self._folders: dict[str, _Folder | None] = {}   # "audio/…" → listing (None: none)
        self._records: list[tuple[str, str, _Use | None]] = []   # kept W21, W25, W31
        self._count = 0                                 # every W21, W25, W31
        self._voice_missing: list[tuple[str, _Use]] = []         # the first W22_LINES
        self._voice_count = 0
        self._order: list[tuple[str, str, _Use | None]] = []     # records to format
        self._done: list[ScriptWarning] = []
        self._formatting: Generator[None, None, ScriptWarning] | None = None
        for file, define in blips:                      # F06: before the story's files
            _use(self._sounds, file, define)

    def step(self) -> bool:
        if self._pass == _COLLECT:
            seen = 0
            for stmt in islice(self._statements, AUDIO_CHECK_CHUNK):
                self._collect(stmt)
                seen += 1
            if seen < AUDIO_CHECK_CHUNK:
                self._pass = _ENTRIES
            return False
        if self._pass == _ENTRIES:
            self._entries = [(_SOUND, f, u) for f, u in self._sounds.items()]
            self._entries += [(_VOICE, f, u) for f, u in self._voices.items()]
            self._entries += [(_LOOP, key, None) for key in self.files.loop_keys]
            self._pass = _LOOK_UP
            return False
        if self._pass == _LOOK_UP:
            if self._look_up_step():
                self._order = self._records[:]
                if self._voice_count:
                    self._order.insert(self._w21_kept(), ("W22", "", None))
                self._pass = _FORMAT
            return False
        if self._pass == _FORMAT:
            at = len(self._done)
            if at < len(self._order):
                if self._formatting is None:
                    self._formatting = self._iter_format(*self._order[at])
                try:
                    next(self._formatting)
                except StopIteration as stop:
                    self._formatting = None
                    self._done.append(stop.value)
                return False
            more = self._count - len(self._records)
            if more > 0:
                self._done.append(ScriptWarning(format_message("W20s", (f"{more:,}",)),
                                                code="W20s"))
            self.warnings = tuple(self._done)
            self._pass = _DONE
        return True

    def run(self) -> tuple[ScriptWarning, ...]:
        """The check to the end in one go (tests and tools)."""
        while not self.step():
            pass
        return self.warnings

    # --- Pass 1: collect --------------------------------------------------------------------

    def _collect(self, stmt: object) -> None:
        if isinstance(stmt, (PlayAudio, QueueMusic, StopAudio)):
            if stmt.audio_file is not None:
                _use(self._sounds, stmt.audio_file, stmt)
        elif isinstance(stmt, Voice):
            _use(self._voices, stmt.audio_file, stmt)
        voice = getattr(stmt, "voice", None)            # F07: a menu's own voice line
        if isinstance(voice, Voice):
            _use(self._voices, voice.audio_file, voice)

    # --- Pass 2: look up --------------------------------------------------------------------

    def _look_up_step(self) -> bool:
        """At most ``AUDIO_CHECK_REFS`` refs whose folder is listed, or one new listing;
        True when every ref is looked up."""
        entries = self._entries
        done = 0
        while self._at < len(entries) and done < AUDIO_CHECK_REFS:
            kind, file, use = entries[self._at]
            folder, _, name = f"{AUDIO_DIR}/{file}".rpartition("/")
            if folder not in self._folders:
                if done == 0:
                    self._list(folder)
                return False
            self._look_up(kind, file, use, folder, name)
            self._at += 1
            done += 1
        return self._at >= len(entries)

    def _look_up(self, kind: int, file: str, use: _Use | None, folder: str, name: str) -> None:
        listed = self._folders[folder]
        exists = listed is not None and name in listed.files
        if kind == _VOICE:
            if not exists:
                self._voice_count += 1
                if len(self._voice_missing) < W22_LINES:
                    assert use is not None
                    self._voice_missing.append((file, use))
        elif kind == _SOUND:
            if not exists:
                self._add("W21", file, use)
        elif not exists:
            self._add("W25", file, None)
        elif suffix(file) not in LOOP_EXTS:
            self._add("W31", file, None)

    def _add(self, code: str, file: str, use: _Use | None) -> None:
        self._count += 1
        if len(self._records) < SCRIPT_AUDIO_WARN_LIMIT:
            self._records.append((code, file, use))

    def _w21_kept(self) -> int:
        return sum(1 for code, _, _ in self._records if code == "W21")

    def _list(self, folder: str) -> None:
        """One folder's listing, kept for the rest of the check."""
        try:
            listing = self.files.list_dir(folder)
        except (AssetRefError, OSError):
            listing = None
        self._folders[folder] = None if listing is None else _Folder(
            frozenset(listing.files), frozenset(listing.dirs), {})

    # --- Pass 3: the texts of the kept records ------------------------------------------------

    def _iter_format(self, code: str, file: str,
                     use: _Use | None) -> Generator[None, None, ScriptWarning]:
        if code == "W22":
            lines = []
            for voice, first in self._voice_missing:
                suggestion = yield from self._iter_suggest(voice)
                stmt = first.stmt
                lines.append((voice, stmt.file.ref,  # type: ignore[attr-defined]
                              stmt.line, suggestion))  # type: ignore[attr-defined]
            return ScriptWarning(w22_text(lines, self._voice_count - len(lines)), code="W22")
        if code == "W31":
            return ScriptWarning(w31_text(file), code="W31")
        suggestion = yield from self._iter_suggest(file)
        if code == "W25":
            return ScriptWarning(w25_text(file, suggestion), code="W25")
        assert use is not None
        stmt = use.stmt
        message = w21_text(file, suggestion, stops=isinstance(stmt, StopAudio),
                           others=use.count - 1)
        return ScriptWarning(message, code="W21", file=stmt.file.ref,  # type: ignore[attr-defined]
                             line=stmt.line)  # type: ignore[attr-defined]

    def _iter_suggest(self, file: str) -> Generator[None, None, str | None]:
        """F01's rule segment by segment (module docstring): the file under ``audio/`` the
        author probably meant, relative to ``audio/``, or None. A folder not listed yet is
        listed in a step of its own."""
        folder = AUDIO_DIR
        walked: list[str] = []
        segments = file.split("/")
        for index, segment in enumerate(segments):
            last = index == len(segments) - 1
            if folder not in self._folders:
                yield
                self._list(folder)
                yield
            listed = self._folders[folder]
            if listed is None:
                return None
            if segment in (listed.files if last else listed.dirs):
                name: str | None = segment
            else:
                pool = listed.pools.get(last)
                if pool is None:
                    pool = listed.pools[last] = SuggestPool(listed.files if last
                                                            else listed.dirs)
                name = yield from pool.iter_suggest(segment)
                if name is None:
                    return None
            walked.append(name)
            folder = f"{folder}/{name}"
        found = "/".join(walked)
        return None if found == file else found


def _use(uses: dict[str, _Use], file: str, stmt: object) -> None:
    """Count one statement using ``file`` (playable extensions only: W23 covers the rest)."""
    if suffix(file) not in PLAYABLE_EXTS:
        return
    use = uses.get(file)
    if use is None:
        uses[file] = _Use(stmt)
    else:
        use.count += 1


def audio_file_check(program: object, files: AudioFiles) -> tuple[ScriptWarning, ...]:
    """``AudioFileCheck`` run to the end in one go."""
    return AudioFileCheck(program, files).run()


# --- Texts (02 §5.3; drafts where 02 gives a form only by example, module docstring) --------

_ADD_THE_FILE = "Add the file, or check the spelling."


def _fix(file: str, suggestion: str | None) -> str:
    """What to do: the did-you-mean, W21's case form, or "Add the file"."""
    if suggestion is None:
        return _ADD_THE_FILE
    if suggestion.casefold() == file.casefold():
        return f'Paths match files exactly: write "{show(suggestion)}".'
    return f'Did you mean "{show(suggestion)}"?'


def w21_text(file: str, suggestion: str | None = None, *, stops: bool = False,
             others: int = 0) -> str:
    """W21: a missing music or sound file; ``stops`` for ``stop sound "<file>"``; ``others``
    counts the other lines using the file."""
    then = "this stops nothing" if stops else "it will be silent"
    text = f"there is no file {show(f'{AUDIO_DIR}/{file}')}, so {then}. {_fix(file, suggestion)}"
    if others:
        text += f" (also on {others:,} other line{'' if others == 1 else 's'})"
    return truncate(text, SCRIPT_MESSAGE_MAX_CHARS)


def w22_text(lines: Sequence[tuple[str, str, int, str | None]], more: int = 0) -> str:
    """W22: ``lines`` are (file, script ref, line, suggestion) of the first missing voice
    files; ``more`` counts the rest. Each line is cut on its own."""
    out = ["Some voice files don't exist, so those lines have no voice:"]
    for file, ref, line, suggestion in lines:
        text = f"{show(f'{AUDIO_DIR}/{file}')} ({show(ref)}, line {line})"
        if suggestion is not None:
            text += f' Did you mean "{show(suggestion)}"?'
        out.append(truncate(text, SCRIPT_MESSAGE_MAX_CHARS))
    if more:
        out.append(f"…and {more:,} more.")
    return "\n".join(out)


def w25_text(key: str, suggestion: str | None = None) -> str:
    """W25: a ``[audio.loop_start]`` key naming no file."""
    return truncate(f'config.toml: [audio.loop_start] names "{show(key)}", which doesn\'t '
                    f"exist. {_fix(key, suggestion)}", SCRIPT_MESSAGE_MAX_CHARS)


def w31_text(key: str) -> str:
    """W31's launch form: a loop point for a file that can't take one."""
    return truncate(f'config.toml: [audio.loop_start] gives "{show(key)}" a loop point, but '
                    "loop points work only in .ogg and .opus files, so it loops from the "
                    "start. Convert it to .ogg.", SCRIPT_MESSAGE_MAX_CHARS)


__all__ = ["AUDIO_CHECK_CHUNK", "AUDIO_CHECK_CODES", "AUDIO_CHECK_REFS", "AudioFileCheck",
           "AudioFiles", "W22_LINES", "audio_file_check", "w21_text", "w22_text", "w25_text",
           "w31_text"]

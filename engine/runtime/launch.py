"""The launch phase: build the namespace and set every ``define`` (F03 ``04-technical.md``
§5.2, §7.6).

Why this module exists: defines are evaluated once per launch, after a clean load and
before the title screen, in slices the loading screen can spread over frames. Every define
is evaluated even after a failure, so the error count is exact, and the speakers are then
checked to be characters. The phases are an ordered list that F04 extends (image scan,
stage check), I-5: with an image source, phase 4 (``ImageScan``) and phase 5
(``StageCheck``, the warnings W10–W16, F04 ``04-technical.md`` §7.2) run after the speaker
check, and only when no define failed. F09 C5 adds its launch errors (E190, E191, E194)
through phase 5's ``errors`` and its W60 (missing ``Mask`` files, checked with the image
source's ``locate`` when it is the game folder) through its warnings. F08 step 8 (I-7): with
``audio`` (``AudioFiles``, given by the app only, so headless runs skip it), phase 6 (``AudioFileCheck``, the warnings W21, W22, W25,
W31, ``engine/runtime/audio_check.py``) follows the stage check on the same terms; F06
gives it the blip files of the ``define``d characters.

A define's error is at the line of its outermost frame in the define's own code (a continued
define names the exact line, SR-F03-29), carries its source line (launch errors are reported
like load errors, F02 §7.10.1–2), and takes its text from ``engine/script/messages.py``.

F12 (step 3a; its ``04-technical.md`` §7.4 step 8): the launch runs on the session's
``PersistentStore`` (``persistent=``; an empty in-memory one when None). The store is locked
while each define is evaluated, so any use of ``persistent`` there is E185, the first rule
of phase 2. **Phase 2b** follows the defines: ``set_known`` with the names the program
mentions, then each ``default persistent.<name>`` in reading order, evaluated under the
guard and stored by ``set_default`` (only if the name has no stored value). One that uses a
failed define, or reads a persistent default that failed, is skipped silently; a failure is
the E85 family (or E180–E183) with the prefix ``default persistent.<name> couldn't be set: ``.
F32 then gives ``persistent.playthrough`` its built-in launch value 0 when no author default
did (``set_builtin_default``). In dev runs, phase 2b ends with **W56** for each ``persistent.<name>`` read that nothing
writes, defaults, or stores (F19's views aside), at its first use, with a did-you-mean;
those records come first in ``LaunchResult.warnings`` (log area ``persist``).
"""

import ast
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from engine.core.logsetup import get_logger
from engine.runtime.character import Character, CharacterOptionError
from engine.runtime.audio_check import AudioFileCheck, AudioFiles
from engine.runtime.dice import DiceNotReady
from engine.runtime.errors import (StoryError, error_line, first_setting_line, map_exception,
                                   prefix_text, timeout_error, where)
from engine.runtime.persistent import PersistentInDefine, PersistentStore
from engine.runtime.guard import NO_GUARD, AuthorCodeGuard
from engine.runtime.images import ImageIndex, ImageScan, ImageSource
from engine.runtime.limits import LAUNCH_MAX_ERRORS, SPEAKER_CHECK_CHUNK
from engine.runtime.modules import ModuleRefused
from engine.runtime.stage_check import StageCheck
from engine.runtime.namespace import build_namespace, dice_core, persistent_store, running_slot
from engine.runtime.values import kind_words
from engine.script.clockshow import picture_warnings
from engine.script.diagnostics import ScriptError, ScriptWarning
from engine.script.messages import format_message
from engine.script.nodes import Define, PersistentDefault
from engine.script import hotbar as hotbar_mod
from engine.script.program import Program
from engine.script.routes import PERSISTENT_VIEWS
from engine.script.suggest import suggest

Phase = Callable[[], bool]              # one unit of work; True when the phase is done


@dataclass(frozen=True)
class LaunchResult:
    namespace: dict | None                          # None when there are errors
    errors: tuple[ScriptError, ...]                 # first 50: define order, then speakers
    error_count: int
    images: ImageIndex | None = None                # F04 phase 4; None with no image source
    # F12 phase 2b (dev): W56 records in reading order (area ``persist``); then F04 phase 5:
    # W10b, W10, W11, W12b, then W12–W16 in reading order; at most 100 records, then one
    # W10s summary (area ``stage``); then F08 phase 6: W21, W22, W25, W31, and their W20s
    # summary (area ``script``). The caller logs them in this order.
    warnings: tuple[ScriptWarning, ...] = ()


class LaunchJob:
    """``step()`` does one unit of work and returns True when done; ``result`` is then
    set. Results never depend on how the work is sliced."""

    def __init__(self, program: Program, *, guard: AuthorCodeGuard = NO_GUARD, dev: bool = False,
                 log: logging.Logger | None = None,
                 game_has: Callable[[str], bool] = lambda ref: False,
                 images: ImageSource | None = None, game_root: Path | None = None,
                 persistent: PersistentStore | None = None,
                 audio: AudioFiles | None = None) -> None:
        self.program = program
        self.persistent = persistent                    # F12; set by phase 1 when None
        self.guard = guard
        self.dev = dev
        self.log = log if log is not None else get_logger("runtime")
        self.game_has = game_has
        self.images = images                            # F04 (ImageScan inputs, I-7)
        self.game_root = game_root
        self.G: dict | None = None
        self.failed: set[str] = set()
        self._errors: list[ScriptError] = []
        self._error_count = 0
        self._define_at = 0
        self._speakers = list(program.speakers.items())
        self._speaker_at = 0
        self._defines = {d.name: d for d in program.defines}
        self._persistent_at = 0                         # F12 phase 2b
        self._persistent_failed: set[str] = set()
        self._persist_warnings: tuple[ScriptWarning, ...] = ()
        # I-5: an ordered phase list (phases 1-3, F12's 2b). F04 appends its image scan and
        # stage check (phases 4 and 5) to ``clean_phases``, which run after them only when
        # no define failed (§7.6).
        self.phases: list[Phase] = [self._phase_namespace, self._phase_defines,
                                    self._phase_persistent, self._phase_speakers]
        self.clean_phases: list[Phase] = []
        self._scan: ImageScan | None = None
        self._index: ImageIndex | None = None
        self._check: StageCheck | None = None
        self._warnings: tuple[ScriptWarning, ...] = ()
        if images is not None:                          # F04 phases 4 and 5
            self.clean_phases += [self._phase_images, self._phase_stage]
        self.audio = audio                              # F08 phase 6 (I-7); None headless
        self._audio_check: AudioFileCheck | None = None
        self._audio_warnings: tuple[ScriptWarning, ...] = ()
        if audio is not None:
            self.clean_phases.append(self._phase_audio)
        self._phase = 0
        self._result: LaunchResult | None = None

    @property
    def result(self) -> LaunchResult:
        if self._result is None:
            raise AssertionError("the launch is not done; call step() until it is")
        return self._result

    def step(self) -> bool:
        if self._result is not None:
            return True
        # ``failed`` is final once phase 2 is done, so the list is the same from then on.
        phases = self.phases if self.failed else [*self.phases, *self.clean_phases]
        if self._phase < len(phases):
            if phases[self._phase]():
                self._phase += 1
            if self._phase < len(phases):
                return False
        ok = self._error_count == 0
        self._result = LaunchResult(namespace=self.G if ok else None,
                                    errors=tuple(self._errors), error_count=self._error_count,
                                    images=self._index,
                                    warnings=(self._persist_warnings + self._warnings
                                              + self._audio_warnings))
        return True

    def _add(self, error: ScriptError) -> None:
        self._error_count += 1
        if len(self._errors) < LAUNCH_MAX_ERRORS:
            self._errors.append(error)

    # --- Phases ---------------------------------------------------------------------

    def _phase_namespace(self) -> bool:
        self.G = build_namespace(self.program, dev=self.dev, log=self.log,
                                 game_has=self.game_has, game_root=self.game_root,
                                 persistent=self.persistent)
        self.persistent = persistent_store(self.G)
        core = dice_core(self.G)
        if core is not None:
            core.ready = False
        return True

    def _phase_defines(self) -> bool:
        defines = self.program.defines
        if self._define_at >= len(defines):
            return True
        define = defines[self._define_at]
        self._define_at += 1
        self._set_define(define)
        return self._define_at >= len(defines)

    def _phase_persistent(self) -> bool:
        """F12 phase 2b: one persistent default per call, then W56 (dev)."""
        store = self.persistent
        assert store is not None
        program = self.program
        defaults = program.persistent_defaults
        if self._persistent_at == 0:
            store.set_known(set(program.persistent_reads) | program.persistent_writes
                            | program.persistent_default_names)
        if self._persistent_at < len(defaults):
            default = defaults[self._persistent_at]
            self._persistent_at += 1
            self._set_persistent_default(default)
            if self._persistent_at < len(defaults):
                return False
        # F32 (C5, 07 I-11): the built-in ``persistent.playthrough``, after the author's
        # defaults (one of those wins) and before W56 (so reading it never warns).
        store.set_builtin_default("playthrough", 0)
        if self.dev:
            self._persist_warnings = tuple(self._w56(store))
        return True

    def _set_persistent_default(self, default: PersistentDefault) -> None:
        """Evaluate one ``default persistent.<name>`` and keep its launch value
        (``set_default`` stores it only if the name has no value)."""
        piece = default.value
        names = piece.code.co_names if piece.code is not None else ()
        if piece.names & self.failed or (
                "persistent" in names and self._persistent_failed.intersection(names)):
            self._persistent_failed.add(default.name)   # dependants skipped silently
            return
        G = self.G
        guard = self.guard
        store = self.persistent
        assert G is not None and store is not None
        running = running_slot(G)
        if running is not None:
            running.set(default.file.ref, piece)
        try:
            guard.enter()
            try:
                value = eval(piece.code, G)
            finally:
                guard.exit()
            store.set_default(default.name, value)
        except KeyboardInterrupt as e:
            if not guard.consume_fired():
                raise
            self._add(timeout_error(default, e, prefix=default, program=self.program))
            self._persistent_failed.add(default.name)
        except BaseException as e:
            self._add(map_exception(e, default, prefix=default, names=G, program=self.program,
                                    guard=guard))
            self._persistent_failed.add(default.name)

    def _w56(self, store: PersistentStore) -> list[ScriptWarning]:
        """W56 for each ``persistent.<name>`` read that no line writes or deletes, no
        default declares, and the store doesn't hold, at its first use (reading order).
        F19's views (``PERSISTENT_VIEWS``) are left out: they are registered later, when the
        interpreter is built; they are in the did-you-mean pool (AC-F19-08)."""
        program = self.program
        known = program.persistent_writes | program.persistent_default_names | store.names()
        pool = sorted(known | PERSISTENT_VIEWS)
        out = []
        for name, (ref, line) in program.persistent_reads.items():
            if name in known or name in PERSISTENT_VIEWS:
                continue
            out.append(ScriptWarning(format_message("W56", (name, suggest(name, pool))),
                                     code="W56", file=ref, line=line))
        return out

    def _phase_speakers(self) -> bool:
        G = self.G
        end = min(self._speaker_at + SPEAKER_CHECK_CHUNK, len(self._speakers))
        for name, say in self._speakers[self._speaker_at:end]:
            define = self._defines.get(name)
            if define is None or name in self.failed:
                continue
            value = G.get(name)
            if not isinstance(value, Character):
                self._add(_speaker_error(define, value, say))
        self._speaker_at = end
        return end >= len(self._speakers)

    def _phase_images(self) -> bool:
        """F04 phase 4 (F04 ``04-technical.md`` §7.1): one directory per call."""
        if self._scan is None:
            assert self.images is not None
            self._scan = ImageScan(self.program, self.images)
        if not self._scan.step():
            return False
        self._index = self._scan.result
        return True

    def _phase_stage(self) -> bool:
        """F04 phase 5 (§7.2): ``STAGE_CHECK_CHUNK`` statements, or one text, per call."""
        if self._check is None:
            assert self.G is not None and self._index is not None
            source = self.images
            assert source is not None
            self._check = StageCheck(self.program, self.G, self._index,
                                     locate=source.locate if source.game_folder else None)
        if not self._check.step():
            return False
        self._warnings = self._check.warnings + tuple(picture_warnings(   # F63 round 2:
            self.program.iter_statements(), self._index.tags))                # W304
        for error in self._check.errors:                # F09 C5
            self._add(error)
        self._warnings += tuple(hotbar_mod.picture_warnings(  # F64 round 2: W309
            self.program.iter_statements(), self._index.tags))
        return True

    def _phase_audio(self) -> bool:
        """F08 phase 6 (F08 ``04-technical.md`` §6.4, I-7): one step of the file check."""
        if self._audio_check is None:
            assert self.audio is not None
            self._audio_check = AudioFileCheck(self.program, self.audio, self._blips())
        if not self._audio_check.step():
            return False
        self._audio_warnings = self._audio_check.warnings
        return True

    def _blips(self) -> list[tuple[str, Define]]:
        """F06: ``(file, define)`` of each ``define``d ``Character`` with ``blip``, at the
        define that made it (a define naming another's character adds nothing)."""
        G = self.G
        assert G is not None
        out = []
        for define in self.program.defines:
            value = G.get(define.name)
            if (isinstance(value, Character) and value.blip is not None
                    and value.define_name == define.name):
                out.append((value.blip.file, define))
        return out

    # --- One define (§7.6 phase 2) ---------------------------------------------------

    def _set_define(self, define: Define) -> None:
        if define.value.names & self.failed:
            self.failed.add(define.name)                # dependants skipped silently
            return
        G = self.G
        guard = self.guard
        store = self.persistent
        assert store is not None
        running = running_slot(G)
        if running is not None:
            running.set(define.file.ref, define.value)
        try:
            guard.enter()
            store.begin_defines()                       # F12: any persistent use is E185
            try:
                value = G[define.name] = eval(define.value.code, G)
            finally:
                store.end_defines()
                guard.exit()
            if isinstance(value, Character):
                value._named(define.name)
        except KeyboardInterrupt as e:
            if not guard.consume_fired():
                raise
            self._add(timeout_error(define, e, prefix=define, program=self.program))
            self.failed.add(define.name)
        except BaseException as e:
            self._add(self._define_error(define, e))
            self.failed.add(define.name)

    def _define_error(self, define: Define, e: BaseException) -> StoryError:
        """The first matching rule of §7.6 phase 2 (F12: E185 comes first)."""
        if isinstance(e, PersistentInDefine):                         # F12 rule 0 (E185)
            return map_exception(e, define, prefix=define, names=self.G,
                                 program=self.program, guard=self.guard)
        at = where(define, error_line(e, define))
        if isinstance(e, CharacterOptionError):                       # rule 1
            return StoryError(e.message, code=e.code, **at)
        name = getattr(e, "name", None) if isinstance(e, NameError) else None
        name = name if type(name) is str else None
        if name is not None:                                          # rule 2 (SR-F03-12, 14)
            argument = _character_argument(define, name)
            if argument == "name":
                return StoryError(format_message("E75e", ("", name)), code="E75e", **at)
            if argument == "name_from":
                return StoryError(format_message("E75g"), code="E75g", **at)
        head = prefix_text(define)
        if isinstance(e, DiceNotReady):                               # rule 3
            return StoryError(head + format_message("E85k", (define.name,)), code="E85k", **at)
        if name is not None:                                          # rule 4
            set_at = None
            if name not in self.program.default_names:
                found = first_setting_line(self.program, name)
                set_at = None if found is None else (found[0].file.ref, found[1])
            if name in self.program.default_names or set_at is not None:
                return StoryError(head + format_message("E85l", (define.name, name, set_at)),
                                  code="E85l", **at)
        if isinstance(e, ModuleRefused):                              # rule 5
            return StoryError(head + e.message, code=e.code, **at)
        return map_exception(e, define, prefix=define, names=self.G,   # rule 6
                             program=self.program, guard=self.guard)


def _character_argument(define: Define, name: str) -> str | None:
    """Rule 2: ``"name"`` when ``name`` is written bare as the first positional argument of
    a ``Character(...)`` call in the define's value, ``"name_from"`` when it is the value of
    its ``name_from=`` keyword, else None. The AST is parsed only now, on this failure path."""
    piece = define.value
    try:
        tree = ast.parse(piece.source, mode=piece.mode)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Character"):
            continue
        if node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == name:
            return "name"
        for keyword in node.keywords:
            if (keyword.arg == "name_from" and isinstance(keyword.value, ast.Name)
                    and keyword.value.id == name):
                return "name_from"
    return None


def _speaker_error(define: Define, value: object, say) -> StoryError:
    """E75 at the define's line, naming the first line the speaker speaks."""
    text = value if type(value) is str else None
    message = format_message("E75", (define.name, kind_words(value), text,
                                     (say.file.ref, say.line)))
    return StoryError(message, code="E75", **where(define))


def run_launch(program: Program, **kwargs: object) -> LaunchResult:
    """A ``LaunchJob`` run to the end in one go (headless and tests)."""
    job = LaunchJob(program, **kwargs)  # type: ignore[arg-type]
    while not job.step():
        pass
    return job.result


__all__ = ["LaunchJob", "LaunchResult", "Phase", "run_launch"]

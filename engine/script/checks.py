"""The whole-game checks (F02 ``04-technical.md`` §7.6.3, §7.6.4; F44 C2 step 4b).

They run once every file is read, on what parsing collected (§7.6.2), in this order:

1. E25/E47: one error per duplicated label or define name, at its **second** place, naming
   all the others. F04: E133 for a second ``image`` declaration of a name, at the second
   place, naming the first (F04 ``04-technical.md`` §6.3). Then F04's E119 texts get the
   speaker's image tag where the defines tell it for sure (``_e119_tags``). F09 (C10):
   E198 at each ``define`` of a built-in transition's name (``cut``, ``dissolve``,
   ``fade``). F18: E220 at a chapter name's second ``chapter``, naming the first, and E224
   (whole game) past ``CHAPTERS_MAX`` chapter lines. F22: E231 at a meter name's second
   declaration, naming the first, and E235 (whole game) past ``METERS_MAX`` meters.
2. Deferred no-text lines: E71 (a defined name), E30a (close to a statement word), else E30b.
3. E26: no ``start`` label (an erroneous ``label start`` line still counts).
4. E43: one error per jump/call target that is no label, at its first use, with the other
   uses. Variant: a case-insensitive suggestion; else "not included" when the **lazy scan**
   of the ``.vns`` files that were not included finds the label; else a close name; else
   plain. The scan runs at most once per load, and only if some missing label has no
   case-insensitive suggestion.
   4b. The start options (``startcheck.py``): E26b for a ``--start`` label that is no label
   (E43's variants, sharing its scan), E26c for ``--set`` names.
5. E70: one error per speaker that is not defined, at its first use, with the other uses.
6. Define order (Kahn's algorithm, ready heap keyed by reading order) and E48/E48b, when no
   define has an error of its own.
   6b. F03 (``04-technical.md`` §3.2): E47b for a second ``default`` of a name, at its
   second place; E47c for a name that is both a define and a default, at whichever comes
   second; then the default order (step 6's algorithm over the defaults, E48/E48b with
   ``default`` in place of ``define``), when no default has an error of its own. Defines
   are all set before any default, so only uses of other defaults order them.
   F12 (``04-technical.md`` §6): E184 at a name's second ``default persistent.<name>``,
   naming the first.
   6c. F03 (``04-technical.md`` §6.2, ``bindings.py``): what each ``$`` line and condition
   may set (E88, E87, E62, E63; one per piece) and W05. Runs even when a file couldn't be
   read (each piece is checked on its own). F12: the same pass collects the
   ``persistent.<name>`` reads and writes of every piece and value (``RootUses``), which
   the ``Program`` gets as ``persistent_reads`` and ``persistent_writes``. F22: the same pass
   gives E234 and E233 (``points.<name>`` and ``points`` lines, against the declared meters).
   F19 (``04-technical.md`` §6.3): the same pass gives E245 for a write or change of
   ``persistent.endings`` or ``persistent.routes``, after E234 and before E233.
   6d. F05 (``04-technical.md`` §6.3, 07 G3/G6): W42 for each ``{var}`` name that no
   ``default`` or ``define`` sets, at its first use (LC, the tag's ``{``), with a
   did-you-mean among the defaults and defines; the first ``SCRIPT_W42_LIMIT`` names, then
   one summary line (W42s). Every run, like the other load warnings; skipped when a file
   couldn't be read.
   6e. F29 (``04-technical.md`` §6.2): W185 (dev loads only) for each outermost ``{glitch}``
   with more than 40 medium or large non-space graphemes (``Collected.long_glitches``, from
   the tag parser), at its ``{``, in reading order. The technical design calls this "step
   6c"; 6c and 6d were taken.
   6f. F51 (``04-technical.md`` §7.1 step 4): W257 (dev loads only) for each timed menu whose
   choices take longer to read than its time limit (``Collected.timed_menus``): ``c`` the
   shown characters of every choice (tags removed, ``{var=x}`` as its name), ``r =
   ceil(c / 15)``; it warns at the menu line when the time is under ``r``.
   6g. F59 (its SPEC §4): E233 at each choice ``check`` whose meter no ``points`` line
   declares (``Collected.choice_checks``), with F22's did-you-mean.
   6h. F62: ``points.rank("<meter>")`` uses (``meterranks.py``): E233, E416, W290.
   6i. F64: item counts and the purse (``itemcounts.py``): E439, E440, E441, W305-W307.
   6i. F62 round 2: ``show meter`` / ``hide meter`` (``showmeter.py``): E233, W291–W293.
   6j. F63: ``clock`` lines and ``clock.<value>`` uses (``clock.py``): E431–E434,
   W300–W303.
   6k. F64 round 2: ``[hotbar] items`` against the usable items (``hotbar.py``): W308.
   6l. First-game fix (2026-11-06): W320 for a remembered variable's name used without
   ``persistent.`` (``remembered.py``).
7. W04 (SEC-F02-08 (b), I-9): a label or define name mixing Latin with Greek or Cyrillic
   letters, at the place it is defined; the first ``SCRIPT_W04_LIMIT`` names, then one
   summary line.
8. F08 (``04-technical.md`` §6.2, ``audio_checks.py``): each ``voice`` is attached to the
   line below it (``Say.voice``, before identities), with W20 when there is none; W23 for
   each file the engine can't play; one W24 for looping MP3s. F14 (``04`` §6.2,
   ``rollback.py``): first, each ``rollback fixed`` marks the menu right below it
   (``Menu.fixed``), with E204 when there is none. F20 (``04-technical.md`` §6.2,
   ``flowchart.iter_attach_marks``): then each ``flowchart`` line: E261 for a scene mark
   that isn't its label's first statement, E262 for a node mark with nothing it can mark,
   E264 for a ``forget`` label that doesn't exist (did-you-mean over the labels; skipped when
   a file couldn't be read). ``CheckOutput.flow_marks`` holds the marks by target.
9. F19 (``04-technical.md`` §6.2, ``_iter_routes``): W130 (dev load) at the first ``ending``
   of a block that has lines after it, once per block; E241 at the second ending of a name,
   then at the second declaration of a route, naming the first (include order, then line);
   E246 (whole game) past ``ENDINGS_MAX`` endings or ``ROUTES_MAX`` routes; E243 for a route
   that names no label (did-you-mean over the labels) or an ``until`` name that is no
   ending; E244 for a ``lock``/``unlock`` name that is no route or ending of its kind (both
   skipped when a file couldn't be read); E245 at a ``default persistent.endings`` or
   ``routes``. ``Program.endings``/``routes`` are built by ``program.py`` from the same nodes.
10. F21 (``04-technical.md`` §6.2, ``_iter_codex``; 07 I-14): E251 at the second
   declaration of an entry name (across tips and items), naming the first, and at the first
   declaration that puts the other kind in a category, naming the category's first place;
   W140 (dev load) once per category text that differs from an earlier one only in
   capitals or spaces; E254 (whole game) past ``TIPS_MAX`` tips, ``ITEMS_MAX`` items, or
   ``CATEGORIES_MAX`` categories (each kind's default counts); E253 for a ``lock``/``unlock
   tip|item`` name that is no entry (did-you-mean over that kind's names) or one of the
   other kind (skipped when a file couldn't be read); W142 (dev load) for each tip that no
   ``unlock tip`` line names. ``Program.codex`` is built by ``program.py``.
11. F23 (``04-technical.md`` §5.3, ``_iter_minigames``): per ``minigame`` line, one error, the
   first of: E270 for a name no plugin registers (did-you-mean over the registered names,
   capitals included; else the first ``MINIGAME_LIST_ITEMS`` names in code-point order, then
   "and N more"); E271 for an argument the plugin doesn't declare (in written order), then
   for the required arguments not given, then for ``skippable`` without a skipped outcome;
   E270 for an ``into`` target that is a define, an engine name, or no default
   (did-you-mean over the defaults). ``CheckInput.minigames`` None (read-only tools) skips the
   signature checks; the target checks are skipped when a file couldn't be read.
12. F31 (``04-technical.md`` §5.2, ``_iter_meta_files``): per ``file`` line in reading order,
   E312 for an ``into`` target that is a define, an engine name, or no default (did-you-mean
   over the defaults; skipped when a file couldn't be read, F23's rule); E313 at the first
   ``file write`` without text of each name whose original ``files/<name>`` isn't a regular
   file in the game (``missing``) or is over ``META_ORIGINAL_MAX_BYTES`` (``large``), by
   ``GamePaths.file_size`` (a stat: no content is read); E314 (whole game) at the first name
   past ``META_NAMES_MAX`` distinct names. ``Program.meta_files`` is built by ``program.py``.
13. F34 (``04-technical.md`` §3, §7.1, ``_iter_gallery``): E343 at a picture's second place in
   the gallery (entry or version, include order, then line), naming the first, and (whole
   game) past ``GALLERY_MAX`` entries; E345 for a ``lock``/``unlock gallery`` picture that is
   no gallery picture (did-you-mean over them; skipped when a file couldn't be read); W226
   (dev load) once per gallery picture that no ``scene``/``show`` names, no dialogue line's
   speaker tag and words build, and no ``unlock gallery`` line names. ``Program.gallery`` is
   built by ``program.py``.
14. F35 (``SPEC.md`` §3, ``_iter_tracks``): E337 at a track's second declaration of a name,
   naming the first, else at the second track of a file (as written), naming the first's
   track, and (whole game) past ``TRACKS_MAX`` tracks; E338 for an ``until`` name that is no
   ending (did-you-mean over the endings; skipped when a file couldn't be read); in dev loads
   W220 for a track whose file isn't in ``audio/`` (its folder listed once by
   ``GamePaths.list_dir``, a did-you-mean over that folder's files) and W221 for a
   default-rule track whose file no ``play music``/``queue music`` line plays.
   ``Program.tracks`` is built by ``program.py``.
15. F36 (``04-technical.md`` §3, ``_iter_replays``): E349 at a scene's second replay (include
   order, then line), naming the first, and (whole game) past ``REPLAYS_MAX`` replays; then,
   skipped when a file couldn't be read, E351 for a replay whose scene or ``to`` is no label
   (did-you-mean over the labels) and for a ``lock``/``unlock replay`` line naming no declared
   replay (did-you-mean over them), and E352 for a starting value whose name no ``default``
   makes (a ``define`` too). ``Program.replays`` is built by ``program.py``.
16. F37 (``SPEC.md`` §3, ``_iter_achievements``): E340 at an achievement's second
   declaration (include order, then line), naming the first, and (whole game) past
   ``ACHIEVEMENTS_MAX`` achievements or ``WHEN_MAX`` with ``when``; then, skipped when a file
   couldn't be read, E340 for an ``unlock achievement`` line naming no declared achievement
   (did-you-mean over them); in dev loads W224 for an achievement with no ``when`` that no
   ``unlock achievement`` line names. ``Program.achievements`` is built by ``program.py``.

Steps 3–5 are skipped when a file couldn't be read (``checks_skipped``, SR-F02-69); after a
story limit (``limit_hit``) only step 1 runs. Errors go to the sink; did-you-mean
suggestions are computed only for the errors that are reported (``LazyDiagnostic``). The
job yields every ``IDENTITY_YIELD_ITEMS`` items and between steps (§7.9). Nothing here
recurses (SEC-F02-05).
"""

import ast
import heapq
import math
import re
from collections import deque
from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from engine.core.constants import META_NAMES_MAX, META_ORIGINAL_MAX_BYTES, META_ORIGINALS_DIR
from engine.core.errors import AssetRefError, EngineError
from engine.core.minigame_types import REQUIRED, MinigameSig
from engine.core.paths import DirListing, GamePaths
from engine.script import (bindings, choicecheck, choicepresent, itemcounts, limits,
                           meterranks, renamed, showmeter)
from engine.script.achievements import (ACHIEVEMENTS_MAX, WHEN_MAX, WORD_ACHIEVEMENT,
                                        AchievementDecl)
from engine.script.audio import AUDIO_FOLDER, PlayAudio, QueueMusic, audio_ref
from engine.script.audio_checks import iter_attach_voices
from engine.script.codex import CATEGORIES_MAX as CODEX_CATEGORIES_MAX
from engine.script.codex import ITEMS_MAX as CODEX_ITEMS_MAX
from engine.script.codex import KINDS as CODEX_KINDS
from engine.script.codex import TIPS_MAX as CODEX_TIPS_MAX
from engine.script.codex import WORD_ITEM, WORD_TIP, CodexEntryDecl, CodexLock
from engine.script.default import PERSISTENT
from engine.script.diagnostics import Diagnostic, DiagnosticSink, ScriptWarning
from engine.script.identity import walk_block
from engine.script.effects import BUILTIN_TRANSITION_NAMES
from engine.script.limits import IDENTITY_YIELD_ITEMS
from engine.script.messages import MINIGAME_LIST_ITEMS, format_message, mixed_script
from engine.script.flowchart import MarkTargets, iter_attach_marks
from engine.script.gallery import GALLERY_MAX, WORD_GALLERY, GalleryDecl
from engine.script.metafiles import WRITE, MetaFile
from engine.script.minigame import Minigame
from engine.script.musicroom import TRACKS_MAX, TrackDecl
from engine.script.nodes import (Default, Define, Label, Node, PersistentDefault, Say,
                                 ScriptFile)
from engine.script.points import METERS_MAX
from engine.script.replay import REPLAYS_MAX, WORD_REPLAY, ReplayDecl
from engine.script.rollback import iter_attach_fixed
from engine.script.routes import (ENDINGS_MAX, PERSISTENT_VIEWS, ROUTES_MAX, Ending, Lock,
                                  RouteDecl)
from engine.script.source import decode_script
from engine.script.stage import Scene, Show
from engine.script.startcheck import START_LABEL, check_start
from engine.script.statements import Collected, Uses, resolve_no_text
from engine.script.suggest import max_distance, suggest
from engine.script.texttags import NameMark, Span, VarMark
from engine.script.words import ENGINE_NAMES, canonical_name, is_image_word

# §7.6.2: label and define names salvaged from a file's text (an E01a file, and the lazy
# scan of the files that were not included).
SALVAGE_RE = re.compile(r"^label[ \t]+(\w+)[ \t]*:|^define[ \t]+(\w+)[ \t]*=", re.MULTILINE)

Place = tuple[ScriptFile, int]
MessagePlace = tuple[str, int]


@dataclass(slots=True)
class CheckInput:
    """What the whole-game checks get from the loader (``04`` §7.6.2–7.6.4).

    ``checks_skipped``: a file couldn't be read, so E26, E43 (with E26b/E26c), and E70 must
    not run. ``limit_hit``: a story limit stopped reading, so only E25/E47 run.
    ``unincluded``: the ``.vns`` refs under ``script/`` that were not loaded (contained,
    code-point sorted), for the lazy "not included" scan, which reads them with
    ``paths.read_file`` and ignores read problems. ``start`` and ``start_names``: the
    ``--start`` label and the ``--set`` names (F44 C2), checked as step 4b. ``dev`` (F19):
    a dev run's load, which gives W130. ``minigames`` (F23): the registered minigames'
    signatures, or None to skip step 11's signature checks."""

    paths: GamePaths
    sink: DiagnosticSink
    collected: Collected
    files: tuple[ScriptFile, ...]
    nodes: tuple[Node, ...]
    checks_skipped: bool
    limit_hit: bool
    unincluded: tuple[str, ...]
    start: str | None = None
    start_names: tuple[str, ...] = ()
    dev: bool = True
    minigames: Mapping[str, MinigameSig] | None = None
    meter_config: Any = None        # F62 round 2: LoadOptions.meter_config (W291, W292)


@dataclass(slots=True)
class CheckOutput:
    """``defines``: the evaluation order (§7.6.4), None for reading order (when the order
    couldn't be found; the load then has errors). ``defaults``: the same for F03's
    defaults. ``warnings``: F03's W05s, then W42 records and their summary line (F05), then
    W04's (I-9), then F08's W20/W23 records, their summary line, and W24. ``uses``: the
    bindings pass's root uses (F12's ``persistent`` reads and writes). ``flow_marks`` (F20):
    each ``flowchart`` mark with its target, in reading order (F20 s2 keys them by sid)."""

    defines: list[Define] | None = None
    defaults: list[Default] | None = None
    warnings: list[ScriptWarning] = field(default_factory=list)
    uses: bindings.RootUses = field(default_factory=bindings.RootUses)
    flow_marks: MarkTargets = field(default_factory=list)

    @property
    def persistent_reads(self) -> dict[str, tuple[str, int]]:
        """F12: each ``persistent.<name>`` read's first use, ``(file ref, line)``."""
        return self.uses.reads_of(PERSISTENT)

    @property
    def persistent_writes(self) -> frozenset[str]:
        """F12: the ``persistent.<name>`` names set or deleted anywhere."""
        return self.uses.writes_of(PERSISTENT)


@dataclass(slots=True)
class LazyDiagnostic(Diagnostic):
    """A diagnostic whose args (with their did-you-mean search) are built only when its text
    is, which happens only for the reported errors (§7.6.3)."""

    build: Callable[[], tuple] | None = None

    def message(self) -> str:
        if self.build is not None:
            self.args = self.build()
            self.build = None
        return format_message(self.code, self.args)


# --- Did-you-mean over many names ------------------------------------------------------

class _Names:
    """Candidate names for ``suggest``, indexed once by case-folded form (the
    case-insensitive match, smallest by code point) and by length (the |Δlen| ≤ k
    prefilter), so each suggestion looks at a few names only."""

    __slots__ = ("_names", "_folded", "_by_length")

    def __init__(self, names: Iterable[str]) -> None:
        self._names = [n for n in names if len(n) <= limits.SCRIPT_SUGGEST_MAX_NAME]
        self._folded: dict[str, str] | None = None
        self._by_length: dict[int, list[str]] = {}

    def iter_index(self) -> Generator[None, None, None]:
        if self._folded is not None:
            return
        folded: dict[str, str] = {}
        by_length = self._by_length
        for count, name in enumerate(self._names, 1):
            key = name.casefold()
            known = folded.get(key)
            if known is None or name < known:
                folded[key] = name
            by_length.setdefault(len(name), []).append(name)
            if count % IDENTITY_YIELD_ITEMS == 0:
                yield
        self._folded = folded

    def _index(self) -> dict[str, str]:
        if self._folded is None:
            for _ in self.iter_index():
                pass
        assert self._folded is not None
        return self._folded

    def case_match(self, name: str) -> str | None:
        """The candidate equal to ``name`` ignoring case (SR-F02-70's first rule), or None."""
        if len(name) > limits.SCRIPT_SUGGEST_MAX_NAME:
            return None
        found = self._index().get(name.casefold())
        return None if found == name else found

    def suggest(self, name: str) -> str | None:
        """``suggest(name, names)``, with the same result."""
        if len(name) > limits.SCRIPT_SUGGEST_MAX_NAME:
            return None
        found = self.case_match(name)
        if found is not None:
            return found
        k = max_distance(name)
        by_length = self._by_length
        pool = [c for size in range(len(name) - k, len(name) + k + 1)
                for c in by_length.get(size, ())]
        return suggest(name, pool)


def _message_places(places: Sequence[Place], limit: int) -> tuple[MessagePlace, ...]:
    return tuple((file.ref, line) for file, line in places[:limit])


# --- Step 1: duplicates (E25, E47) -----------------------------------------------------

def _iter_duplicates(sink: DiagnosticSink, table: Mapping[str, list[Place]],
                     code: str) -> Generator[None, None, None]:
    shown = limits.SCRIPT_MESSAGE_LIST_ITEMS
    for count, (name, places) in enumerate(table.items(), 1):
        if len(places) > 1:
            file, line = places[1]
            others = [places[0], *places[2:]]
            sink.add(Diagnostic(code, file, line, None,
                                (name, _message_places(others, shown),
                                 max(0, len(others) - shown))))
        if count % IDENTITY_YIELD_ITEMS == 0:
            yield


def _iter_image_duplicates(sink: DiagnosticSink,
                           table: Mapping[str, list[Place]]) -> Generator[None, None, None]:
    """F04 E133: one error per image name declared more than once, at its second place."""
    for count, (name, places) in enumerate(table.items(), 1):
        if len(places) > 1:
            (first, first_line), (file, line) = places[0], places[1]
            sink.add(Diagnostic("E133", file, line, None, (name, (first.ref, first_line))))
        if count % IDENTITY_YIELD_ITEMS == 0:
            yield


def _iter_chapters(sink: DiagnosticSink,
                   table: Mapping[str, list[Place]]) -> Generator[None, None, None]:
    """F18: E220 at the second ``chapter`` of a name, naming the first; then E224 (whole
    game) when the story has more than ``CHAPTERS_MAX`` chapter lines."""
    total = 0
    for count, (name, places) in enumerate(table.items(), 1):
        total += len(places)
        if len(places) > 1:
            (first, first_line), (file, line) = places[0], places[1]
            sink.add(Diagnostic("E220", file, line, None, (name, (first.ref, first_line))))
        if count % IDENTITY_YIELD_ITEMS == 0:
            yield
    if total > limits.CHAPTERS_MAX:
        sink.add(Diagnostic("E224", args=(total, limits.CHAPTERS_MAX)))


def _iter_meters(sink: DiagnosticSink,
                 table: Mapping[str, list[Place]]) -> Generator[None, None, None]:
    """F22: E231 at the second declaration of a meter name, naming the first; then E235
    (whole game) when the story declares more than ``METERS_MAX`` meters."""
    for count, (name, places) in enumerate(table.items(), 1):
        if len(places) > 1:
            (first, first_line), (file, line) = places[0], places[1]
            sink.add(Diagnostic("E231", file, line, None, (name, (first.ref, first_line))))
        if count % IDENTITY_YIELD_ITEMS == 0:
            yield
    if len(table) > METERS_MAX:
        sink.add(Diagnostic("E235", args=(len(table), METERS_MAX)))


def _choice_check_meters(sink: DiagnosticSink, collected: Collected) -> None:
    """F59 step 6g: E233 at a choice ``check`` naming an undeclared meter."""
    meters = collected.meter_defs
    for file, check, source in collected.choice_checks:
        if check.meter not in meters:
            sink.add(Diagnostic("E233", file, check.line, check.column,
                                (check.meter, suggest(check.meter, meters)),
                                source_line=source, stmt=check.line))


def _builtin_transition_defines(sink: DiagnosticSink,
                                 table: Mapping[str, list[Place]]) -> None:
    """F09 E198 (SR-F09-08): a ``define`` can't take a built-in transition's name. One
    error at each such define."""
    for name in BUILTIN_TRANSITION_NAMES:
        for file, line in table.get(name, ()):
            sink.add(Diagnostic("E198", file, line, None, (name,)))


# --- F04 E119: the speaker's image tag in the hint -------------------------------------------

def character_tag(define: Define | None) -> str | None:
    """The image tag a define gives its character, when the value alone tells it for sure
    (F04 07 I-12): ``Character(...)`` with no ``image_tag`` (the define name), or with
    ``image_tag="<word>"``. None for anything else (``**options``, a computed value, a
    malformed tag, which is E135 at launch)."""
    if define is None:
        return None
    try:
        tree = ast.parse(define.value.source, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    call = tree.body
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "Character"):
        return None
    tag: str | None = define.name
    for keyword in call.keywords:
        if keyword.arg is None:
            return None
        if keyword.arg == "image_tag":
            value = keyword.value
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)
                    and is_image_word(value.value)):
                return None
            tag = canonical_name(value.value)
    return tag


def _e119_tags(inp: CheckInput) -> None:
    """Give each reported E119 the speaker's image tag when ``character_tag`` can tell it, so
    its hint reads ``Put show <tag> at left on the line above.``; otherwise the hint names no
    tag (E119 is found while parsing, before any define is known)."""
    found = [diag for diag in inp.sink.kept()
             if diag.code == "E119" and len(diag.args) == 4 and diag.args[2] is None]
    if not found:
        return
    defines: dict[str, Define] = {}
    for node in inp.nodes:
        if isinstance(node, Define):
            defines.setdefault(node.name, node)
    for diag in found:
        word, part, _, speaker = diag.args
        tag = character_tag(defines.get(speaker))
        if tag is not None:
            diag.args = (word, part, tag, speaker)


# --- Steps 3–5: labels, targets, start options, speakers ---------------------------------

class _Labels:
    """Labels and soft labels (an erroneous line that looks like a label, SR-F02-69)."""

    __slots__ = ("defs", "soft", "names")

    def __init__(self, collected: Collected) -> None:
        self.defs = collected.label_defs
        self.soft = collected.soft_labels
        self.names = _Names([*self.defs, *(n for n in self.soft if n not in self.defs)])

    def __contains__(self, name: object) -> bool:
        return name in self.defs or name in self.soft

    def place(self, name: str) -> Place:
        places = self.defs.get(name)
        return places[0] if places else self.soft[name]


def _missing_start(sink: DiagnosticSink,
                   labels: _Labels) -> Generator[None, None, None]:
    """E26 (game-wide), with a suggestion from the labels."""
    if START_LABEL in labels:
        return
    yield from labels.names.iter_index()
    found = labels.names.suggest(START_LABEL)
    if found is None:
        sink.add(Diagnostic("E26"))
        return
    file, line = labels.place(found)
    sink.add(Diagnostic("E26", args=(found, (file.ref, line))))


def _iter_scan(paths: GamePaths, refs: Sequence[str],
               wanted: set[str]) -> Generator[None, None, dict[str, str]]:
    """The lazy scan: the first not-included file (code-point order) holding ``label
    <name>:`` for each wanted name. Each file ≤ 16 MB, all together ≤
    ``SCRIPT_UNINCLUDED_SCAN_MAX_BYTES``; read problems are ignored."""
    found: dict[str, str] = {}
    budget = limits.SCRIPT_UNINCLUDED_SCAN_MAX_BYTES
    for ref in sorted(refs):
        if budget <= 0 or len(found) == len(wanted):
            break
        try:
            data = paths.read_file(ref, max_bytes=min(limits.SCRIPT_FILE_MAX_BYTES, budget))
        except EngineError:
            yield
            continue
        budget -= len(data)
        text = decode_script(ref, data).text
        del data
        if text is not None:
            for match in SALVAGE_RE.finditer(text):
                label = match.group(1)
                if label is None:
                    continue
                name = canonical_name(label)
                if name in wanted and name not in found:
                    found[name] = ref
        yield
    return found


class _LabelVariant:
    """E43's variant for a missing label, shared by E26b: (suggestion, defined_in)."""

    __slots__ = ("labels", "found")

    def __init__(self, labels: _Labels) -> None:
        self.labels = labels
        self.found: dict[str, str] = {}

    def __call__(self, name: str) -> tuple[str | None, str | None]:
        names = self.labels.names
        close = names.case_match(name)
        if close is not None:
            return close, None
        defined_in = self.found.get(name)
        if defined_in is not None:
            return None, defined_in
        return names.suggest(name), None


def _uses_args(uses: Uses) -> tuple[ScriptFile, int, tuple[MessagePlace, ...], int]:
    """First use, the other kept uses (for the message), and how many more there are."""
    file, line = uses.places[0]
    others = _message_places(uses.places[1:], limits.SCRIPT_MESSAGE_LIST_ITEMS)
    return file, line, others, uses.count - 1 - len(others)


def _iter_targets(inp: CheckInput, labels: _Labels) -> Generator[None, None, None]:
    """E43 and step 4b (E26b, E26c), with at most one lazy scan."""
    collected = inp.collected
    sink = inp.sink
    missing: list[tuple[str, Uses]] = []
    for count, (name, uses) in enumerate(collected.targets.items(), 1):
        if name not in labels:
            missing.append((name, uses))
        if count % IDENTITY_YIELD_ITEMS == 0:
            yield
    start = canonical_name(inp.start) if inp.start is not None else None
    start_missing = start is not None and start != START_LABEL and start not in labels
    variant = _LabelVariant(labels)
    if missing or start_missing:
        yield from labels.names.iter_index()
        wanted = {name for name, _ in missing if labels.names.case_match(name) is None}
        if start_missing and labels.names.case_match(start) is None:  # type: ignore[arg-type]
            wanted.add(start)  # type: ignore[arg-type]
        if wanted:
            variant.found = yield from _iter_scan(inp.paths, inp.unincluded, wanted)
    for name, uses in missing:
        file, line, others, more = _uses_args(uses)
        here = file.ref

        def build(name: str = name, here: str = here, others: tuple = others,
                  more: int = more) -> tuple:
            return (name, *variant(name), here, others, more)

        sink.add(LazyDiagnostic("E43", file, line, None, build=build))
    yield

    def missing_label(name: str) -> Diagnostic:
        return LazyDiagnostic("E26b", build=lambda: (name, *variant(name)))

    for diag in check_start(inp.start, inp.start_names, labels=labels,
                            default_names=collected.default_defs,
                            define_names=collected.define_defs, missing_label=missing_label):
        sink.add(diag)


def _iter_speakers(inp: CheckInput) -> Generator[None, None, None]:
    """E70, with a suggestion among the define names."""
    collected = inp.collected
    defined = collected.define_defs
    names = _Names(defined)
    for count, (name, uses) in enumerate(collected.speakers.items(), 1):
        if name not in defined:
            file, line, others, more = _uses_args(uses)

            def build(name: str = name, here: str = file.ref, others: tuple = others,
                      more: int = more) -> tuple:
                return (name, names.suggest(name), here, others, more)

            inp.sink.add(LazyDiagnostic("E70", file, line, None, build=build))
        if count % IDENTITY_YIELD_ITEMS == 0:
            yield


# --- Step 6: define order (§7.6.4) -------------------------------------------------------

def _iter_sccs(nodes: Sequence[int],
               edges: Sequence[Sequence[int]]) -> Generator[None, None, list[list[int]]]:
    """Tarjan's strongly connected components of the subgraph on ``nodes`` (an explicit
    stack, no recursion). ``edges[v]`` may name nodes outside ``nodes``; they are ignored."""
    inside = set(nodes)
    index: dict[int, int] = {}
    low: dict[int, int] = {}
    on_stack: set[int] = set()
    stack: list[int] = []
    components: list[list[int]] = []
    steps = 0
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = len(index)
        stack.append(root)
        on_stack.add(root)
        work = [(root, 0)]
        while work:
            steps += 1
            if steps % IDENTITY_YIELD_ITEMS == 0:
                yield
            v, i = work[-1]
            out = edges[v]
            if i < len(out):
                work[-1] = (v, i + 1)
                w = out[i]
                if w not in inside:
                    continue
                if w not in index:
                    index[w] = low[w] = len(index)
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, 0))
                elif w in on_stack:
                    low[v] = min(low[v], index[w])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
            if low[v] == index[v]:
                component = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    component.append(w)
                    if w == v:
                        break
                components.append(component)
    return components


def _shortest_cycle(start: int, members: set[int],
                    edges: Sequence[Sequence[int]]) -> list[int]:
    """A shortest cycle from ``start`` back to it inside ``members`` (BFS; neighbours in
    reading order), without repeating ``start`` at the end."""
    previous: dict[int, int | None] = {start: None}
    queue = deque([start])
    last: int | None = None
    while queue and last is None:
        v = queue.popleft()
        for w in edges[v]:
            if w == start:
                last = v
                break
            if w in members and w not in previous:
                previous[w] = v
                queue.append(w)
    assert last is not None
    cycle: list[int] = []
    node: int | None = last
    while node is not None:
        cycle.append(node)
        node = previous[node]
    cycle.reverse()
    return cycle


def _iter_define_order(inp: CheckInput) -> Generator[None, None, list[Define] | None]:
    """``Program.defines``: a define comes after every define its value uses, else in
    reading order. On a cycle: E48 (or E48b for a define using itself) and None."""
    return (yield from _iter_order(inp, Define, inp.collected.define_defs, "define"))


def _iter_order(inp: CheckInput, node_type: type, defined: Mapping[str, list[Place]],
                word: str) -> Generator[None, None, list | None]:
    """The evaluation order of the ``node_type`` declarations (``define``, F03 ``default``)
    among themselves (§7.6.4); E48/E48b name ``word`` (an extra argument for ``default``
    only, so F02's messages keep their args)."""
    defines = [node for node in inp.nodes if isinstance(node, node_type)]
    extra = () if word == "define" else (word,)
    if len(defined) != len(defines) or \
            sum(len(places) for places in defined.values()) != len(defines):
        return None                                    # some define has its own error
    position = {node.name: i for i, node in enumerate(defines)}
    uses: list[list[int]] = []
    users: list[list[int]] = [[] for _ in defines]
    for i, node in enumerate(defines):
        needed = sorted({position[n] for n in node.value.names if n in position})
        uses.append(needed)
        for j in needed:
            users[j].append(i)
        if (i + 1) % IDENTITY_YIELD_ITEMS == 0:
            yield
    waiting = [len(needed) for needed in uses]
    ready = [i for i, count in enumerate(waiting) if count == 0]
    heapq.heapify(ready)
    order: list[Define] = []
    while ready:
        i = heapq.heappop(ready)
        order.append(defines[i])
        for k in users[i]:
            waiting[k] -= 1
            if waiting[k] == 0:
                heapq.heappush(ready, k)
        if len(order) % IDENTITY_YIELD_ITEMS == 0:
            yield
    if len(order) == len(defines):
        return order
    left = [i for i, count in enumerate(waiting) if count > 0]
    components = yield from _iter_sccs(left, uses)
    cycles = sorted((min(c), c) for c in components if len(c) > 1 or c[0] in uses[c[0]])
    shown = limits.SCRIPT_MESSAGE_LIST_ITEMS
    for first, component in cycles:
        cycle = _shortest_cycle(first, set(component), uses)
        node = defines[first]
        if len(cycle) == 1:
            inp.sink.add(Diagnostic("E48b", node.file, node.line, None, (node.name, *extra)))
            continue
        others = [(defines[i].file.ref, defines[i].line) for i in cycle[1:]]
        inp.sink.add(Diagnostic("E48", node.file, node.line, None,
                                (tuple(defines[i].name for i in cycle),
                                 tuple(others[:shown]), max(0, len(others) - shown),
                                 *extra)))
    return None


# --- Step 6b: defaults (F03) --------------------------------------------------------------

def _reading_key(place: Place) -> tuple[int, int]:
    return place[0].order, place[1]


def _iter_default_names(inp: CheckInput) -> Generator[None, None, None]:
    """E47b at a name's second ``default``; E47c where a name's first define and first
    default meet, at the later of the two."""
    collected = inp.collected
    defines = collected.define_defs
    sink = inp.sink
    for count, (name, places) in enumerate(collected.default_defs.items(), 1):
        if len(places) > 1:
            file, line = places[1]
            sink.add(Diagnostic("E47b", file, line, None,
                                (name, (places[0][0].ref, places[0][1]))))
        define_places = defines.get(name)
        if define_places:
            define, default = define_places[0], places[0]
            define_first = _reading_key(define) < _reading_key(default)
            first, (file, line) = (define, default) if define_first else (default, define)
            sink.add(Diagnostic("E47c", file, line, None,
                                (name, (first[0].ref, first[1]), define_first)))
        if count % IDENTITY_YIELD_ITEMS == 0:
            yield


def _iter_persistent_defaults(inp: CheckInput) -> Generator[None, None, None]:
    """F12 E184 (third form) at a name's second ``default persistent.<name>``, naming the
    first (reading order)."""
    first: dict[str, Place] = {}
    reported: set[str] = set()
    for count, node in enumerate(inp.nodes, 1):
        if isinstance(node, PersistentDefault):
            place = first.setdefault(node.name, (node.file, node.line))
            if place != (node.file, node.line) and node.name not in reported:
                reported.add(node.name)
                inp.sink.add(Diagnostic("E184", node.file, node.line, None,
                                        ("duplicate", node.name, (place[0].ref, place[1]))))
        if count % IDENTITY_YIELD_ITEMS == 0:
            yield


# --- Step 6c: W42 (F05) --------------------------------------------------------------------

def _iter_w42(collected: Collected) -> Generator[None, None, list[ScriptWarning]]:
    """W42 for each ``{var}`` name no default or define sets, at its first use in reading
    order; past ``SCRIPT_W42_LIMIT``, one W42s line."""
    defined = collected.define_defs
    defaults = collected.default_defs
    found: list[tuple[int, int, int, str, ScriptFile]] = []
    for count, (name, (file, line, column)) in enumerate(collected.var_uses.items(), 1):
        if name not in defined and name not in defaults:
            found.append((file.order, line, column, name, file))
        if count % IDENTITY_YIELD_ITEMS == 0:
            yield
    if not found:
        return []
    found.sort(key=lambda item: item[:3])
    names = _Names([*defined, *defaults])
    yield from names.iter_index()
    cap = limits.SCRIPT_W42_LIMIT
    warnings = []
    for _, line, column, name, file in found[:cap]:
        args = (name, names.suggest(name))
        warnings.append(ScriptWarning(format_message("W42", args), code="W42", file=file.ref,
                                      line=line, column=column))
    if len(found) > cap:
        warnings.append(ScriptWarning(format_message("W42s", (f"{len(found) - cap:,}",)),
                                      code="W42s"))
    return warnings


# --- Step 6e: W185 (F29) ------------------------------------------------------------------

def _w185(collected: Collected) -> list[ScriptWarning]:
    """W185 (dev loads) for each long outermost ``{glitch}`` the parser counted, at its ``{``,
    in reading order. Uncapped: each needs 41 authored characters (F29 04 §6.2)."""
    found = sorted(collected.long_glitches, key=lambda item: (item[0].order, item[1], item[2]))
    return [ScriptWarning(format_message("W185", (count, strength)), code="W185",
                          file=file.ref, line=line, column=column)
            for file, line, column, count, strength in found]


# --- Step 6f: W257 (F51) -----------------------------------------------------------------

W257_CHARS_PER_SECOND: Final = 15                   # F51 01 §5: reading speed for W257


def _shown_chars(body) -> int:
    """A choice's shown characters: its spans, ``{var=x}`` and ``{username=x}`` as their
    names (the fallback word as ``username``)."""
    count = 0
    for piece in body.pieces:
        if isinstance(piece, Span):
            count += len(piece.text)
        elif isinstance(piece, VarMark):
            count += len(piece.name)
        elif isinstance(piece, NameMark):
            count += len(piece.var or "username")
    return count


def _w257(collected: Collected) -> list[ScriptWarning]:
    """W257 (dev loads) for each timed menu whose choices read longer than its time, at its
    line, in reading order."""
    warnings: list[ScriptWarning] = []
    for menu in sorted(collected.timed_menus, key=lambda m: (m.file.order, m.line)):
        chars = sum(_shown_chars(choice.body) for choice in menu.choices)
        read = math.ceil(chars / W257_CHARS_PER_SECOND)
        if menu.time is not None and menu.time < read:
            warnings.append(ScriptWarning(format_message("W257", (menu.time_text, chars, read)),
                                          code="W257", file=menu.file.ref, line=menu.line))
    return warnings


# --- Step 7: W04 --------------------------------------------------------------------------

def _iter_w04(collected: Collected) -> Generator[None, None, list[ScriptWarning]]:
    """W04 for each label or define name mixing Latin with Greek or Cyrillic letters, at its
    first place, in reading order; past ``SCRIPT_W04_LIMIT``, one W04s line."""
    found: list[tuple[int, int, str, str, str]] = []
    count = 0
    for table in (collected.label_defs, collected.define_defs):
        for name, places in table.items():
            count += 1
            if count % IDENTITY_YIELD_ITEMS == 0:
                yield
            if name.isascii():
                continue
            script = mixed_script(name)
            if script is not None:
                file, line = places[0]
                found.append((file.order, line, name, script, file.ref))
    found.sort()
    cap = limits.SCRIPT_W04_LIMIT
    warnings = [ScriptWarning(format_message("W04", (name, script)), code="W04", file=ref,
                              line=line)
                for _, line, name, script, ref in found[:cap]]
    if len(found) > cap:
        warnings.append(ScriptWarning(format_message("W04s", (len(found) - cap,)),
                                      code="W04s"))
    return warnings


# --- Step 9: routes and endings (F19) ----------------------------------------------------------

def _w130_endings(label: Label) -> list[Ending]:
    """The first ``Ending`` of each block of ``label`` that has a statement after it (W130),
    in line order. Iterative: nesting depth costs no recursion."""
    found: list[Ending] = []
    stack: list[tuple] = [label.block]
    while stack:
        block = stack.pop()
        for index, stmt in enumerate(block):
            if isinstance(stmt, Ending):
                if index + 1 < len(block):
                    found.append(stmt)
                break
        for stmt in block:
            stack.extend(stmt.blocks())
    found.sort(key=lambda stmt: stmt.line)
    return found


def _iter_routes(inp: CheckInput, labels: "_Labels | None"
                 ) -> Generator[None, None, list[ScriptWarning]]:
    """Step 9 (module docstring). ``labels`` is None when a file couldn't be read: the name
    checks (E243's label and until forms, E244's) are skipped then."""
    sink = inp.sink
    endings: dict[str, list[Ending]] = {}
    locks: list[Lock] = []
    warnings: list[ScriptWarning] = []
    count = 0
    for node in inp.nodes:
        if not isinstance(node, Label):
            continue
        for stmt, _ in walk_block(node.block):
            if isinstance(stmt, Ending):
                endings.setdefault(stmt.name, []).append(stmt)
            elif isinstance(stmt, Lock) and stmt.kind in ("route", "ending"):  # F34: rows of
                locks.append(stmt)                       # their own (gallery) are checked there
            count += 1
            if count % IDENTITY_YIELD_ITEMS == 0:
                yield
        if inp.dev:
            for stmt in _w130_endings(node):
                warnings.append(ScriptWarning(format_message("W130"), code="W130",
                                              file=stmt.file.ref, line=stmt.line))
    routes: dict[str, list[RouteDecl]] = {}
    for node in inp.nodes:
        if isinstance(node, RouteDecl):
            routes.setdefault(node.name, []).append(node)
    for kind, table in (("ending", endings), ("route", routes)):
        for name, nodes in table.items():
            if len(nodes) > 1:
                first, second = nodes[0], nodes[1]
                sink.add(Diagnostic("E241", second.file, second.line, None,
                                    (kind, name, (first.file.ref, first.line))))
    yield
    ending_total = sum(len(nodes) for nodes in endings.values())
    route_total = sum(len(nodes) for nodes in routes.values())
    if ending_total > ENDINGS_MAX:
        sink.add(Diagnostic("E246", args=("ending", ending_total, ENDINGS_MAX)))
    if route_total > ROUTES_MAX:
        sink.add(Diagnostic("E246", args=("route", route_total, ROUTES_MAX)))
    if labels is not None:
        names = {"ending": _Names(endings), "route": _Names(routes)}
        if routes:
            yield from labels.names.iter_index()
        for decls in routes.values():
            for decl in decls:
                if decl.name not in labels:
                    sink.add(LazyDiagnostic(
                        "E243", decl.file, decl.line, None,
                        build=lambda name=decl.name: ("label", name,
                                                      labels.names.suggest(name))))
                    continue
                missing = next((n for n in decl.until if n not in endings), None)
                if missing is not None:
                    sink.add(LazyDiagnostic(
                        "E243", decl.file, decl.line, None,
                        build=lambda name=missing: ("until", name,
                                                    names["ending"].suggest(name))))
        for lock in locks:
            table = routes if lock.kind == "route" else endings
            if lock.name not in table:
                sink.add(LazyDiagnostic(
                    "E244", lock.file, lock.line, None,
                    build=lambda lock=lock: (lock.kind, lock.name,
                                             names[lock.kind].suggest(lock.name))))
    for node in inp.nodes:
        if isinstance(node, PersistentDefault) and node.name in PERSISTENT_VIEWS:
            sink.add(Diagnostic("E245", node.file, node.line, None, ("default", node.name)))
    return warnings


# --- Step 10: the codex (F21) -------------------------------------------------------------------

def _category_key(text: str) -> str:
    """W140's comparison: case-folded, whitespace runs as one space."""
    return " ".join(text.casefold().split())


def _iter_codex(inp: CheckInput, labels: "_Labels | None"
                ) -> Generator[None, None, list[ScriptWarning]]:
    """Step 10 (module docstring). ``labels`` is None when a file couldn't be read: E253 is
    skipped then, like F19's name checks."""
    sink = inp.sink
    decls = [node for node in inp.nodes if isinstance(node, CodexEntryDecl)]
    locks: list[CodexLock] = []
    count = 0
    for node in inp.nodes:
        if not isinstance(node, Label):
            continue
        for stmt, _ in walk_block(node.block):
            if isinstance(stmt, CodexLock):
                locks.append(stmt)
            count += 1
            if count % IDENTITY_YIELD_ITEMS == 0:
                yield
    if not decls and not locks:
        return []
    found: list[tuple[int, int, ScriptWarning]] = []

    def warn(code: str, decl: CodexEntryDecl, args: tuple) -> None:
        found.append((decl.file.order, decl.line, ScriptWarning(
            format_message(code, args), code=code, file=decl.file.ref, line=decl.line)))

    entries: dict[str, CodexEntryDecl] = {}
    categories: dict[tuple[str, str | None], CodexEntryDecl] = {}
    texts: dict[str, CodexEntryDecl] = {}           # author category text → first place
    folded: dict[str, CodexEntryDecl] = {}          # W140's key → first place
    totals = {kind: 0 for kind in CODEX_KINDS}
    for decl in decls:
        totals[decl.kind] += 1
        first = entries.setdefault(decl.name, decl)
        if first is not decl:
            sink.add(Diagnostic("E251", decl.file, decl.line, None,
                                ("twice", decl.name, (first.file.ref, first.line))))
        key = (decl.kind, decl.category)
        if key in categories:
            continue
        categories[key] = decl
        text = decl.category
        if text is None:
            continue
        other = texts.setdefault(text, decl)
        if other is not decl:
            sink.add(Diagnostic("E251", decl.file, decl.line, None,
                                ("mixed", text, decl.kind, other.kind,
                                 (other.file.ref, other.line))))
            continue
        near = folded.setdefault(_category_key(text), decl)
        if near is not decl and inp.dev:
            warn("W140", decl, (text, near.category, (near.file.ref, near.line)))
    yield
    for kind, limit in ((WORD_TIP, CODEX_TIPS_MAX), (WORD_ITEM, CODEX_ITEMS_MAX)):
        if totals[kind] > limit:
            sink.add(Diagnostic("E254", args=(kind, totals[kind], limit)))
    if len(categories) > CODEX_CATEGORIES_MAX:
        sink.add(Diagnostic("E254", args=("categories", len(categories),
                                          CODEX_CATEGORIES_MAX)))
    if labels is not None:
        names = {kind: _Names(n for n, d in entries.items() if d.kind == kind)
                 for kind in CODEX_KINDS}
        for lock in locks:
            decl = entries.get(lock.name)
            if decl is None:
                sink.add(LazyDiagnostic(
                    "E253", lock.file, lock.line, None,
                    build=lambda lock=lock: ("unknown", lock.kind, lock.name,
                                             names[lock.kind].suggest(lock.name))))
            elif decl.kind != lock.kind:
                verb = "unlock" if lock.unlock else "lock"
                sink.add(Diagnostic("E253", lock.file, lock.line, None,
                                    ("kind", lock.name, decl.kind, lock.kind, verb)))
    if inp.dev:
        unlocked = {lock.name for lock in locks if lock.unlock and lock.kind == WORD_TIP}
        for name, decl in entries.items():
            if decl.kind == WORD_TIP and name not in unlocked:
                warn("W142", decl, (name,))
    found.sort(key=lambda item: item[:2])
    return [warning for _, _, warning in found]


# --- Step 11: minigames (F23) -------------------------------------------------------------

def _minigame_signature(stmt: Minigame, sigs: Mapping[str, MinigameSig]
                        ) -> Diagnostic | None:
    """E270's unknown name, or E271's load forms, for one line (step 11)."""
    def at(code: str, args: tuple = (), build: Callable[[], tuple] | None = None
           ) -> Diagnostic:
        return LazyDiagnostic(code, stmt.file, stmt.line, None, args, stmt=stmt.line,
                              build=build)

    name = stmt.name
    sig = sigs.get(name)
    if sig is None:
        def unknown() -> tuple:
            found = suggest(name, sigs)
            listed = sorted(sigs)
            shown = MINIGAME_LIST_ITEMS
            return ("unknown", name, found, tuple(listed[:shown]), max(0, len(listed) - shown))
        return at("E270", build=unknown)
    declared = tuple(arg.name for arg in sig.args)
    for arg in stmt.args:
        if arg.name not in declared:
            return at("E271", build=lambda arg=arg: (
                "unknown", name, arg.name, suggest(arg.name, declared), declared,
                f"{arg.name}={arg.value.source}"))
    written = {arg.name for arg in stmt.args}
    missing = tuple(spec.name for spec in sig.args
                    if spec.default is REQUIRED and spec.name not in written)
    if missing:
        return at("E271", ("missing", name, missing))
    if stmt.skippable and sig.skipped is None:
        return at("E271", ("skippable_none", name))
    return None


def _minigame_target(stmt: Minigame, collected: Collected,
                     defaults: _Names) -> Diagnostic | None:
    """E270 for the ``into`` target: a define, an engine name, or no default (step 11)."""
    target = stmt.target
    if target is None or target in collected.default_defs:
        return None
    if target in collected.define_defs:
        args: tuple = ("define", target)
    elif target in ENGINE_NAMES:
        args = ("engine", target)
    else:
        return LazyDiagnostic("E270", stmt.file, stmt.line, None, stmt=stmt.line,
                              build=lambda: ("no_default", target, defaults.suggest(target)))
    return Diagnostic("E270", stmt.file, stmt.line, None, args, stmt=stmt.line)


def _iter_minigames(inp: CheckInput) -> Generator[None, None, None]:
    """Step 11 (module docstring)."""
    sigs = inp.minigames
    collected = inp.collected
    defaults = _Names(collected.default_defs)
    count = 0
    for node in inp.nodes:
        if not isinstance(node, Label):
            continue
        for stmt, _ in walk_block(node.block):
            count += 1
            if count % IDENTITY_YIELD_ITEMS == 0:
                yield
            if not isinstance(stmt, Minigame):
                continue
            problem = None if sigs is None else _minigame_signature(stmt, sigs)
            if problem is None and not inp.checks_skipped:
                problem = _minigame_target(stmt, collected, defaults)
            if problem is not None:
                inp.sink.add(problem)


# --- Step 12: meta files (F31) ------------------------------------------------------------

def _meta_target(stmt: MetaFile, collected: Collected,
                 defaults: _Names) -> Diagnostic | None:
    """E312 for the ``into`` target: a define, an engine name, or no default (step 12)."""
    target = stmt.target
    if target is None or target in collected.default_defs:
        return None
    if target in collected.define_defs:
        args: tuple = ("define", target)
    elif target in ENGINE_NAMES:
        args = ("engine", target)
    else:
        return LazyDiagnostic("E312", stmt.file, stmt.line, None, stmt=stmt.line,
                              build=lambda: ("no_default", target, defaults.suggest(target)))
    return Diagnostic("E312", stmt.file, stmt.line, None, args, stmt=stmt.line)


def _meta_original(stmt: MetaFile, paths: GamePaths) -> Diagnostic | None:
    """E313 for a copied name's original (step 12): one stat, never a read."""
    try:
        size = paths.file_size(f"{META_ORIGINALS_DIR}/{stmt.name}")
    except (EngineError, AssetRefError):
        args: tuple = ("missing", stmt.name)
    else:
        if size <= META_ORIGINAL_MAX_BYTES:
            return None
        args = ("large", stmt.name, size, META_ORIGINAL_MAX_BYTES)
    return Diagnostic("E313", stmt.file, stmt.line, None, args, stmt=stmt.line)


def _iter_meta_files(inp: CheckInput) -> Generator[None, None, None]:
    """Step 12 (module docstring)."""
    collected = inp.collected
    defaults = _Names(collected.default_defs)
    names: set[str] = set()
    copied: set[str] = set()
    first_over: tuple[str, str, int] | None = None
    count = 0
    for node in inp.nodes:
        if not isinstance(node, Label):
            continue
        for stmt, _ in walk_block(node.block):
            count += 1
            if count % IDENTITY_YIELD_ITEMS == 0:
                yield
            if not isinstance(stmt, MetaFile):
                continue
            if stmt.name not in names:
                names.add(stmt.name)
                if len(names) > META_NAMES_MAX and first_over is None:
                    first_over = (stmt.name, stmt.file.ref, stmt.line)
            problem = None
            if stmt.verb == WRITE and stmt.text is None and stmt.name not in copied:
                copied.add(stmt.name)
                problem = _meta_original(stmt, inp.paths)
            if problem is None and not inp.checks_skipped:
                problem = _meta_target(stmt, collected, defaults)
            if problem is not None:
                inp.sink.add(problem)
    if first_over is not None:                       # the count is known only at the end
        inp.sink.add(Diagnostic("E314", args=(len(names), *first_over)))


# --- Step 13: the gallery (F34) ----------------------------------------------------------------

def _iter_gallery(inp: CheckInput, labels: "_Labels | None"
                  ) -> Generator[None, None, list[ScriptWarning]]:
    """Step 13 (module docstring). ``labels`` is None when a file couldn't be read: E345 is
    skipped then, like F21's E253."""
    sink = inp.sink
    decls = [node for node in inp.nodes if isinstance(node, GalleryDecl)]
    locks: list[Lock] = []
    shown: set[str] = set()                         # names a scene, show, or dialogue look puts up
    looks: list[Say] = []
    count = 0
    for node in inp.nodes:
        if not isinstance(node, Label):
            continue
        for stmt, _ in walk_block(node.block):
            if isinstance(stmt, Lock) and stmt.kind == WORD_GALLERY:
                locks.append(stmt)
            elif isinstance(stmt, (Scene, Show)) and stmt.image is not None:
                shown.add(stmt.image)
            elif isinstance(stmt, Say) and stmt.speaker is not None and stmt.attributes:
                looks.append(stmt)
            count += 1
            if count % IDENTITY_YIELD_ITEMS == 0:
                yield
    if not decls and not locks:
        return []
    first: dict[str, tuple[ScriptFile, int]] = {}
    for decl in sorted(decls, key=lambda d: (d.file.order, d.line)):
        for picture, line in decl.places():
            place = first.setdefault(picture, (decl.file, line))
            if place != (decl.file, line):
                sink.add(Diagnostic("E343", decl.file, line, None,
                                    ("twice", picture, (place[0].ref, place[1]))))
    if len(decls) > GALLERY_MAX:
        sink.add(Diagnostic("E343", args=("many", len(decls), GALLERY_MAX)))
    yield
    if labels is not None:
        names = _Names(first)
        for lock in locks:
            if lock.name not in first:
                sink.add(LazyDiagnostic(
                    "E345", lock.file, lock.line, None,
                    build=lambda lock=lock: (lock.name, names.suggest(lock.name))))
    if not inp.dev:
        return []
    defines = {node.name: node for node in inp.nodes if isinstance(node, Define)}
    tags: dict[str, str] = {}
    for say in looks:
        speaker = say.speaker
        if speaker not in tags:                     # an unknown tag: the speaker's own name
            tags[speaker] = character_tag(defines.get(speaker)) or speaker
        shown.add(" ".join((tags[speaker], *say.attributes)))
    shown.update(lock.name for lock in locks if lock.unlock)
    warnings: list[ScriptWarning] = []
    for decl in sorted(decls, key=lambda d: (d.file.order, d.line)):
        for picture, line in decl.places():
            if picture not in shown and first.get(picture) == (decl.file, line):
                warnings.append(ScriptWarning(format_message("W226", (picture,)), code="W226",
                                              file=decl.file.ref, line=line))
    return warnings


# --- Step 14: the music room (F35) -------------------------------------------------------------

def _missing_audio(paths: GamePaths, file: str,
                   listings: dict[str, DirListing | None]) -> tuple[bool, str | None]:
    """W220's lookup: whether ``audio/<file>`` is a file in the game (its folder listed once,
    by ``GamePaths.list_dir``; nothing is opened), and a did-you-mean for a missing one (a
    close file name in the same folder)."""
    folder, _, name = audio_ref(file).rpartition("/")
    if folder not in listings:
        try:
            listings[folder] = paths.list_dir(folder)
        except (AssetRefError, EngineError, OSError):
            listings[folder] = None
    listing = listings[folder]
    if listing is not None and name in listing.files:
        return False, None
    if listing is None:
        return True, None
    found = _Names(listing.files).suggest(name)
    if found is None:
        return True, None
    inside = folder[len(AUDIO_FOLDER):]
    return True, f"{inside}/{found}" if inside else found


def _iter_tracks(inp: CheckInput, labels: "_Labels | None"
                 ) -> Generator[None, None, list[ScriptWarning]]:
    """Step 14 (module docstring). ``labels`` is None when a file couldn't be read: E338 is
    skipped then, like F19's E243."""
    sink = inp.sink
    decls = [node for node in inp.nodes if isinstance(node, TrackDecl)]
    if not decls:
        return []
    endings: set[str] = set()
    played: set[str] = set()                        # audio refs a play/queue music line starts
    count = 0
    for node in inp.nodes:
        if not isinstance(node, Label):
            continue
        for stmt, _ in walk_block(node.block):
            if isinstance(stmt, Ending):
                endings.add(stmt.name)
            elif isinstance(stmt, PlayAudio) and stmt.channel == "music":
                played.add(audio_ref(stmt.audio_file))
            elif isinstance(stmt, QueueMusic):
                played.add(audio_ref(stmt.audio_file))
            count += 1
            if count % IDENTITY_YIELD_ITEMS == 0:
                yield
    names: dict[str, TrackDecl] = {}
    files: dict[str, TrackDecl] = {}
    for decl in decls:
        first = names.setdefault(decl.name, decl)
        if first is not decl:
            sink.add(Diagnostic("E337", decl.file, decl.line, None,
                                ("twice", decl.name, (first.file.ref, first.line))))
            continue
        other = files.setdefault(audio_ref(decl.audio_file), decl)
        if other is not decl:
            sink.add(Diagnostic("E337", decl.file, decl.line, None,
                                ("file", other.name, decl.name, decl.audio_file)))
    if len(decls) > TRACKS_MAX:
        sink.add(Diagnostic("E337", args=("many", len(decls), TRACKS_MAX)))
    yield
    if labels is not None:
        known = _Names(endings)
        for decl in decls:
            missing = next((n for n in decl.until if n not in endings), None)
            if missing is not None:
                sink.add(LazyDiagnostic(
                    "E338", decl.file, decl.line, None,
                    build=lambda name=missing: (name, known.suggest(name))))
    if not inp.dev:
        return []
    warnings: list[ScriptWarning] = []
    listings: dict[str, DirListing | None] = {}
    for decl in decls:
        missing_file, suggestion = _missing_audio(inp.paths, decl.audio_file, listings)
        if missing_file:
            warnings.append(ScriptWarning(
                format_message("W220", (decl.name, decl.audio_file, suggestion)), code="W220",
                file=decl.file.ref, line=decl.line))
        if not decl.always_open and not decl.until and audio_ref(decl.audio_file) not in played:
            warnings.append(ScriptWarning(
                format_message("W221", (decl.name, decl.audio_file)), code="W221",
                file=decl.file.ref, line=decl.line))
    return warnings


def _w317(inp: CheckInput) -> list[ScriptWarning]:
    """F65 round 3, dev loads: each ``[device.<look>] arrive_sound`` that names no file in
    ``audio/`` (``_missing_audio``, W220's lookup), at the table's config.toml line."""
    devices = getattr(inp.meter_config, "device", None)
    if not inp.dev or not devices:
        return []
    warnings: list[ScriptWarning] = []
    listings: dict[str, DirListing | None] = {}
    for look, table in devices.items():
        file = getattr(table, "arrive_sound", None)
        if not file:
            continue
        missing, suggestion = _missing_audio(inp.paths, file, listings)
        if missing:
            warnings.append(ScriptWarning(format_message("W317", (look, file, suggestion)),
                                          code="W317", file="config.toml",
                                          line=getattr(table, "line", None)))
    return warnings


# --- Step 15: scene replays (F36) --------------------------------------------------------------

def _iter_replays(inp: CheckInput, labels: "_Labels | None") -> Generator[None, None, None]:
    """Step 15 (module docstring). ``labels`` is None when a file couldn't be read: E351 and
    E352 are skipped then, like F19's E243."""
    sink = inp.sink
    decls = [node for node in inp.nodes if isinstance(node, ReplayDecl)]
    locks: list[Lock] = []
    count = 0
    for node in inp.nodes:
        if not isinstance(node, Label):
            continue
        for stmt, _ in walk_block(node.block):
            if isinstance(stmt, Lock) and stmt.kind == WORD_REPLAY:
                locks.append(stmt)
            count += 1
            if count % IDENTITY_YIELD_ITEMS == 0:
                yield
    if not decls and not locks:
        return
    first: dict[str, ReplayDecl] = {}
    for decl in sorted(decls, key=lambda d: (d.file.order, d.line)):
        other = first.setdefault(decl.label, decl)
        if other is not decl:
            sink.add(Diagnostic("E349", decl.file, decl.line, None,
                                ("twice", decl.label, (other.file.ref, other.line))))
    if len(decls) > REPLAYS_MAX:
        sink.add(Diagnostic("E349", args=("many", len(decls), REPLAYS_MAX)))
    yield
    if labels is None:
        return
    yield from labels.names.iter_index()
    defaults = inp.collected.default_defs
    for decl in decls:
        missing = next((name for name in (decl.label, decl.to)
                        if name is not None and name not in labels), None)
        if missing is not None:
            sink.add(LazyDiagnostic(
                "E351", decl.file, decl.line, None,
                build=lambda name=missing: ("scene", name, labels.names.suggest(name))))
        for (name, _), line in zip(decl.values, decl.value_lines):
            if name not in defaults:
                sink.add(Diagnostic("E352", decl.file, line, None, ("variable", name)))
    names = _Names(first)
    for lock in locks:
        if lock.name not in first:
            sink.add(LazyDiagnostic(
                "E351", lock.file, lock.line, None,
                build=lambda lock=lock: ("replay", lock.name, names.suggest(lock.name))))


# --- Step 16: achievements (F37) ---------------------------------------------------------------

def _iter_achievements(inp: CheckInput, labels: "_Labels | None"
                       ) -> Generator[None, None, list[ScriptWarning]]:
    """Step 16 (module docstring). ``labels`` is None when a file couldn't be read: the
    unknown-name E340 and W224 are skipped then, like F19's E243."""
    sink = inp.sink
    decls = [node for node in inp.nodes if isinstance(node, AchievementDecl)]
    locks: list[Lock] = []
    count = 0
    for node in inp.nodes:
        if not isinstance(node, Label):
            continue
        for stmt, _ in walk_block(node.block):
            if isinstance(stmt, Lock) and stmt.kind == WORD_ACHIEVEMENT:
                locks.append(stmt)
            count += 1
            if count % IDENTITY_YIELD_ITEMS == 0:
                yield
    if not decls and not locks:
        return []
    first: dict[str, AchievementDecl] = {}
    for decl in sorted(decls, key=lambda d: (d.file.order, d.line)):
        other = first.setdefault(decl.name, decl)
        if other is not decl:
            sink.add(Diagnostic("E340", decl.file, decl.line, None,
                                ("twice", decl.name, (other.file.ref, other.line))))
    if len(decls) > ACHIEVEMENTS_MAX:
        sink.add(Diagnostic("E340", args=("many", len(decls), ACHIEVEMENTS_MAX)))
    automatic = sum(1 for decl in decls if decl.when is not None)
    if automatic > WHEN_MAX:
        sink.add(Diagnostic("E340", args=("when", automatic, WHEN_MAX)))
    yield
    if labels is None:
        return []
    names = _Names(first)
    for lock in locks:
        if lock.name not in first:
            sink.add(LazyDiagnostic(
                "E340", lock.file, lock.line, None,
                build=lambda lock=lock: ("unknown", lock.name, names.suggest(lock.name))))
    if not inp.dev:
        return []
    given = {lock.name for lock in locks}
    return [ScriptWarning(format_message("W224", (decl.name,)), code="W224",
                          file=decl.file.ref, line=decl.line)
            for decl in first.values() if decl.when is None and decl.name not in given]


# --- The checks ---------------------------------------------------------------------------

def iter_checks(inp: CheckInput) -> Generator[None, None, CheckOutput]:
    """Run the whole-game checks (module docstring) in slices; the loader runs this with
    ``yield from``."""
    out = CheckOutput()
    collected = inp.collected
    sink = inp.sink
    yield from _iter_duplicates(sink, collected.label_defs, "E25")
    yield from _iter_duplicates(sink, collected.define_defs, "E47")
    yield from _iter_image_duplicates(sink, collected.image_defs)
    yield from _iter_chapters(sink, collected.chapter_defs)          # F18
    yield from _iter_meters(sink, collected.meter_defs)               # F22
    _choice_check_meters(sink, collected)                             # F59
    _builtin_transition_defines(sink, collected.define_defs)          # F09
    _e119_tags(inp)
    if inp.limit_hit:
        return out
    yield
    for count, item in enumerate(collected.no_text, 1):
        sink.add(resolve_no_text(item, collected.define_defs))
        if count % IDENTITY_YIELD_ITEMS == 0:
            yield
    yield
    labels: _Labels | None = None
    if not inp.checks_skipped:
        labels = _Labels(collected)
        yield from _missing_start(sink, labels)
        yield from _iter_targets(inp, labels)
        yield
        yield from _iter_speakers(inp)
        yield
    out.defines = yield from _iter_define_order(inp)
    yield
    yield from _iter_default_names(inp)
    out.defaults = yield from _iter_order(inp, Default, collected.default_defs, "default")
    yield from _iter_persistent_defaults(inp)                         # F12
    yield
    out.warnings = yield from bindings.iter_check_all(
        bindings.iter_pieces(inp.nodes, values=True),
        bindings.Defines.from_nodes(collected.define_defs, inp.nodes), sink.add,
        uses=out.uses, meters=frozenset(collected.meter_defs))      # F22: E233, E234
    out.warnings += renamed.codex_warnings(out.uses.reads_of("codex"))  # v1: W323
    out.warnings += meterranks.check_story(inp.nodes, sink.add)     # F62: E233, E416, W290
    out.warnings += itemcounts.check_story(inp.nodes, sink.add)     # F64: E439-E441, W305-W307
    out.warnings += showmeter.check_story(inp.nodes, sink.add,      # F62 round 2: E233,
                                          inp.meter_config)         # W291–W293
    from engine.script import clock as clock_checks                 # F63 (imports us)
    out.warnings += clock_checks.check_story(inp.nodes, sink.add,   # E431–E434,
                                             inp.meter_config)      # W300–W303
    out.warnings += choicecheck.check_story(inp.nodes)              # F59: W294 (retry)
    out.warnings += choicepresent.check_story(inp.nodes, sink.add)  # F64: E447, W310
    from engine.script import hotbar as hotbar_checks               # F64 round 2: W308
    out.warnings += hotbar_checks.check_story(inp.nodes, inp.meter_config)
    from engine.script import inbox as inbox_checks                 # F65 round 2: E450-
    out.warnings += inbox_checks.check_story(inp.nodes, sink.add,   # E452, W311
                                             inp.meter_config)
    out.warnings += _w317(inp)                                      # F65 round 3
    out.warnings += renamed.config_warnings(inp.meter_config)       # v1: W323
    from engine.script import remembered                            # W320: plain names
    out.warnings += remembered.check_story(inp.nodes, collected.define_defs,
                                           collected.default_defs)
    yield
    if not inp.checks_skipped:
        out.warnings += yield from _iter_w42(collected)
        yield
    if inp.dev:
        out.warnings += _w185(collected)                                # F29
        out.warnings += _w257(collected)                                # F51
    out.warnings += yield from _iter_w04(collected)
    yield
    yield from iter_attach_fixed(inp.nodes, sink)                    # F14: E204
    out.flow_marks = yield from iter_attach_marks(                    # F20: E261, E262, E264
        inp.nodes, sink, labels, None if labels is None else labels.names.suggest)
    out.warnings += yield from iter_attach_voices(inp.nodes)
    yield
    out.warnings += yield from _iter_routes(inp, labels)              # F19
    yield
    out.warnings += yield from _iter_codex(inp, labels)               # F21
    yield
    yield from _iter_minigames(inp)                                   # F23
    yield
    yield from _iter_meta_files(inp)                                  # F31
    yield
    out.warnings += yield from _iter_gallery(inp, labels)             # F34
    yield
    out.warnings += yield from _iter_tracks(inp, labels)              # F35
    yield
    yield from _iter_replays(inp, labels)                             # F36
    yield
    out.warnings += yield from _iter_achievements(inp, labels)        # F37
    return out


__all__ = ["CheckInput", "CheckOutput", "LazyDiagnostic", "SALVAGE_RE", "character_tag",
           "iter_checks"]

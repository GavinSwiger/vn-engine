"""The launch image check: the stage warnings W10–W16 (F04 ``04-technical.md`` §7.2 phase 5,
§6.3; ``02-script.md`` §5.3; PR-F04-02, 04, 24; SR-F04-01, 03, 05, 16, 21, 23, 25).

Why this module exists: a misspelled image name, an expression word with no picture, or a
``behind`` naming a sprite no ``show`` puts on stage would otherwise show up only as a
placeholder (or nothing) when the player reaches the line. ``StageCheck`` finds them once
per launch, after the image scan (``LaunchJob`` phase 4) and only when every define was set,
so the author reads them all in the log before playing. They are warnings: the game always
launches.

Two passes over the statements in reading order, ``STAGE_CHECK_CHUNK`` statements per
``step()`` (the loading screen spreads them over frames), then the kept records are
formatted one per step, a W12's did-you-mean over up to 20,000 image names in as many steps
as it needs (``SuggestPool.iter_suggest``: a few ms each; F04 step 9):

1. collect: ``show_tags`` (the tag of every ``show``) and ``as_map`` (tag given with
   ``as`` → the first words of the images shown under it);
2. check: ``scene``/``show`` image names (W12), dialogue-line words (W12 or W13), ``behind``
   (W16), and (F09) each ``with`` through ``TransitionCheck`` (E190, E191, E194's launch
   form); then (F21, SR-F21-04) the ``image`` of each codex entry (``Program.codex``),
   checked as a ``show`` name but with no tag form, since the page shows that one picture
   (W12 at the declaration's line); then (F34, PR-F34-06) each picture of each gallery entry
   (``Program.gallery``: the entry picture, then its versions), likewise, once per picture
   at the entry's line; then (F36, PR-F36-07) each scene replay's declared ``image``
   (``Program.replays``), likewise; when the pass ends, W60 for each ``Mask`` file ``locate`` can't
   find.

Record order (§7.2, AC-F04-41): the scan stop line W10b (F04 07 I-10: its own record,
first), the one W10 record, each W11, each W12b, then the statement warnings in reading
order (the codex entries after the labels' statements), then F09's W60s (define order). At most ``STAGE_WARN_MAX`` records are kept, then
one W10s summary line; the cap
counts every record here, the scan stop line included, and never run-time W15 (I-9, G5).

F09 C5 retires W14: the launch errors E190, E191, and E194 come from the ``with`` clauses the
check pass visits, in reading order, and ``errors`` is added to the launch's errors by
``LaunchJob``. ``locate`` (the game folder's; None headless) finds the ``Mask`` files.

Pure (TR-F03-05): no file, directory, clock, or randomness; the index and the namespace are
given.
"""

from collections.abc import Generator, Iterator, Mapping
from dataclasses import dataclass
from itertools import chain, islice

from engine.runtime.character import Character
from engine.runtime.images import IMAGES_DIR, ImageFile, ImageIndex, name_of
from engine.runtime.limits import (IMAGE_SCAN_MAX_FILES, STAGE_CHECK_CHUNK, STAGE_W10_MAX_LINES,
                                   STAGE_WARN_MAX)
from engine.runtime.stage import first_word, speaker_tag
from engine.runtime.transitions import Locate, TransitionCheck
from engine.script.codex import CodexEntry
from engine.script.diagnostics import ScriptError, ScriptWarning
from engine.script.gallery import GalleryEntry
from engine.script.messages import format_message, w10_text
from engine.script.nodes import Say
from engine.script.replay import ReplayEntry
from engine.script.stage import Scene, Show
from engine.script.suggest import SuggestPool, suggest

_COLLECT, _CHECK, _FORMAT, _DONE = range(4)


@dataclass(slots=True)
class _Record:
    """One warning before its text is made: ``node`` gives the place (None: a whole-game
    G warning), ``args`` what the text needs."""
    code: str
    node: object | None
    args: tuple


class StageCheck:
    """``step()`` does one unit of work and returns True when done; ``warnings`` (and the
    F09 ``errors``) are then final. The result doesn't depend on how the work is sliced."""

    def __init__(self, program: object, G: Mapping[str, object], index: ImageIndex, *,
                 locate: Locate | None = None) -> None:
        self.program = program
        self.G = G
        self.index = index
        self.warnings: tuple[ScriptWarning, ...] = ()
        self.errors: tuple[ScriptError, ...] = ()       # F09 C5: E190, E191, E194
        self.show_tags: set[str] = set()
        self.as_map: dict[str, set[str]] = {}
        self._statements: Iterator[object] = program.iter_statements()  # type: ignore[attr-defined]
        self._pass = _COLLECT
        self._records: list[_Record] = []               # the first STAGE_WARN_MAX
        self._count = 0                                 # every record
        self._transitions = TransitionCheck(program, G, locate=locate)     # F09
        self._done: list[ScriptWarning] = []
        self._names: SuggestPool | None = None          # W12's did-you-mean, made once
        self._formatting: Generator[None, None, ScriptWarning] | None = None
        self._index_records()

    def step(self) -> bool:
        if self._pass == _COLLECT:
            if self._each_statement(self._collect):
                self._pass = _CHECK
                self._statements = chain(  # F21, F34, F36: codex, gallery, replay pictures
                    self.program.iter_statements(),  # type: ignore[attr-defined]
                    getattr(self.program, "codex", ()),
                    getattr(self.program, "gallery", ()),
                    getattr(self.program, "replays", ()))
            return False
        if self._pass == _CHECK:
            if self._each_statement(self._check):
                self.errors = tuple(self._transitions.errors)              # F09 C5
                for define, args in self._transitions.missing_masks():    # F09 W60
                    self._add("W60", define, *args)
                self._pass = _FORMAT
            return False
        if self._pass == _FORMAT:
            at = len(self._done)
            if at < len(self._records):
                if self._formatting is None:
                    self._formatting = self._iter_format(self._records[at])
                try:
                    next(self._formatting)
                except StopIteration as stop:
                    self._formatting = None
                    self._done.append(stop.value)
                return False
            more = self._count - len(self._records)
            if more > 0:
                self._done.append(ScriptWarning(format_message("W10s", (more,)), code="W10s"))
            self.warnings = tuple(self._done)
            self._pass = _DONE
        return True

    def run(self) -> tuple[ScriptWarning, ...]:
        """The check to the end in one go (tests and tools)."""
        while not self.step():
            pass
        return self.warnings

    # --- Records ----------------------------------------------------------------------------

    def _add(self, code: str, node: object | None, *args: object) -> None:
        self._count += 1
        if len(self._records) < STAGE_WARN_MAX:
            self._records.append(_Record(code, node, args))

    def _index_records(self) -> None:
        """What the scan found, first: W10b, W10, W11, W12b (§7.2)."""
        index = self.index
        if index.truncated:
            self._add("W10b", None)
        if index.problems:
            self._add("W10", None)
        for duplicate in index.duplicates:
            self._add("W11", None, duplicate.name, duplicate.used, duplicate.other)
        for missing in index.declared_missing:
            self._add("W12b", missing.declaration, missing.name, missing.ref, missing.suggestion)

    def _each_statement(self, visit) -> bool:
        """Visit the next ``STAGE_CHECK_CHUNK`` statements; True when there are no more."""
        seen = 0
        for stmt in islice(self._statements, STAGE_CHECK_CHUNK):
            visit(stmt)
            seen += 1
        return seen < STAGE_CHECK_CHUNK

    # --- Pass 1: collect --------------------------------------------------------------------

    def _collect(self, stmt: object) -> None:
        if isinstance(stmt, Show):
            self.show_tags.add(stmt.tag or first_word(stmt.image))
            if stmt.tag is not None:
                self.as_map.setdefault(stmt.tag, set()).add(first_word(stmt.image))

    # --- Pass 2: check ----------------------------------------------------------------------

    def _check(self, stmt: object) -> None:
        if isinstance(stmt, Scene):
            if stmt.image is not None:
                self._check_image(stmt, stmt.image)
        elif isinstance(stmt, Show):
            self._check_image(stmt, stmt.image)
            if stmt.behind is not None and stmt.behind not in self.show_tags:
                self._add("W16", stmt, stmt.behind)
        elif isinstance(stmt, Say):
            if stmt.speaker is not None and stmt.attributes:
                self._check_words(stmt)
        elif isinstance(stmt, CodexEntry):
            if stmt.image is not None and stmt.image not in self.index.names:
                self._add("W12", stmt, stmt.image)       # F21: the page shows this name
            return
        elif isinstance(stmt, GalleryEntry):             # F34: the tiles and the viewer
            for name in stmt.pictures:
                if name not in self.index.names:
                    self._add("W12", stmt, name)
            return
        elif isinstance(stmt, ReplayEntry):              # F36: the Scenes tile's picture
            if stmt.image is not None and stmt.image not in self.index.names:
                self._add("W12", stmt, stmt.image)
            return
        self._transitions.visit(stmt)                    # F09: E190, E191, E194

    def _check_image(self, stmt: object, name: str) -> None:
        """SR-F04-03: a name the index has, or one word that is a tag (SR-F04-11 keeps the
        sprite's image; ``show girl_a`` for a tag given with ``as``)."""
        if name in self.index.names:
            return
        if " " not in name and (name in self.index.tags or name in self.as_map):
            return
        self._add("W12", stmt, name)

    def _check_words(self, stmt: Say) -> None:
        """SR-F04-21: the speaker's tag plus the words names an image, directly or for a
        tag shown with ``as`` (``show student neutral as kaito``, then ``kaito angry``)."""
        speaker = stmt.speaker
        character = self.G.get(speaker)  # type: ignore[arg-type]
        if not isinstance(character, Character):
            return                                      # the speaker check reports it
        tag = speaker_tag(character, speaker)  # type: ignore[arg-type]
        words = " ".join(stmt.attributes)
        names = self.index.names
        shown_as = sorted(self.as_map.get(tag, ()))
        if f"{tag} {words}" in names or any(f"{t} {words}" in names for t in shown_as):
            return
        if tag in self.index.tags:
            self._add("W12", stmt, f"{tag} {words}")
        elif shown_as:
            # The sprite tagged ``tag`` shows ``shown_as`` images, so the picture the line
            # asks for is named from that tag (drafted; 06 AC-F04-40 asserts the code).
            self._add("W12", stmt, f"{shown_as[0]} {words}")
        else:
            self._add("W13", stmt, speaker, words, character.image_tag)

    # --- Pass 3: the texts of the kept records -------------------------------------------------

    def _iter_format(self, record: _Record) -> Generator[None, None, ScriptWarning]:
        """The record's warning as the return value; a W12 pauses (yields) while its
        did-you-mean is found, the others don't."""
        code, args = record.code, record.args
        if code == "W10b":
            message = format_message("W10b", (IMAGE_SCAN_MAX_FILES,))
        elif code == "W10":
            problems = self.index.problems
            shown = [(p.ref, p.reason, p.word, p.rename, p.folder)
                     for p in problems[:STAGE_W10_MAX_LINES]]
            message = w10_text(shown, len(problems) - len(shown))
        elif code == "W12":
            message = format_message("W12", (yield from self._iter_w12_args(args[0])))
        elif code == "W16":
            message = format_message("W16", (args[0], suggest(args[0], self.show_tags)))
        else:                                           # W11, W12b, W13, F09 W60
            message = format_message(code, args)
        node = record.node
        file = getattr(node, "file", None)
        if file is None:
            return ScriptWarning(message, code=code)
        ref = file if isinstance(file, str) else file.ref   # a CodexEntry keeps the ref
        return ScriptWarning(message, code=code, file=ref, line=node.line)  # type: ignore[union-attr]

    def _iter_w12_args(self, name: str) -> Generator[None, None, tuple]:
        if self._names is None:
            self._names = SuggestPool(self.index.names)
        match = yield from self._names.iter_suggest(name)
        if match is None:
            return (name,)
        if match.casefold() == name.casefold():
            return (name, match, self._rename(name, match))
        return (name, match)

    def _rename(self, name: str, match: str) -> tuple[str, str, bool] | None:
        """W12's case form: the file (or folder) under ``images/`` that gives ``match``, and
        what to rename it to so it gives ``name``; None when ``match`` isn't from such a file
        (a declaration), so the text is a plain did-you-mean."""
        image = self.index.get(match)
        if not isinstance(image, ImageFile) or not image.ref.startswith(IMAGES_DIR + "/"):
            return None
        ref = image.ref
        if name_of(ref)[0] != match:
            return None
        written, found = name.split(" "), match.split(" ")
        if len(written) != len(found):
            return None
        at = next(i for i, (a, b) in enumerate(zip(written, found)) if a != b)
        parts = ref.split("/")
        if at == len(found) - 1:
            return ref, written[at] + ref[ref.rfind("."):], False
        return "/".join(parts[:at + 2]), written[at], True


def stage_check(program: object, G: Mapping[str, object], index: ImageIndex, *,
                locate: Locate | None = None) -> tuple[ScriptWarning, ...]:
    """``StageCheck`` run to the end in one go (tests and tools)."""
    return StageCheck(program, G, index, locate=locate).run()


__all__ = ["StageCheck", "stage_check"]

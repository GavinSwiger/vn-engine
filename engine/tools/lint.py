"""The script linter's rules (F41 ``04-technical.md`` §7.2; P2): scenes nothing reaches and
things nothing uses, as **findings** W237–W242.

Why this module exists: the check child (``tools/check.py``) already knows every declared
thing (its names rows) and every use (its ``*_use`` rows, widened by F41 P1). What's left is
a pure comparison: a declared thing with no use row, and a label no ``jump``, ``call`` or
choice reaches from a starting point. One rule set feeds both views: the check child sends
the findings to Studio as names rows (``unreached``, ``unused_*``; Database ▸ Clean up) and
the ``lint`` CLI prints them as ``source: "lint"`` items (P3).

- **Starts** (decision 7): ``start`` and every scene replay's label (F36). ``reached`` walks
  every ``LabelLink`` of every label (``labelgraph.block_links``), with no cap: lint must be
  complete.
- **Used** means a use row names it, so Database's "Used in N lines" and lint agree by
  construction (AC-F41-08). Pictures compare without case. A character also counts its
  ``define_use`` rows (``define h = make_hana()`` reads as a plain define), and a define its
  ``transition_use`` rows (decision 9).
- **Never listed** (PR-F41-04): built-in positions and transitions (never defines), the
  engine's ``black``, ``narrator``, files outside ``images/`` and ``audio/`` (no index or
  audio name comes from them), and backup-looking pictures and sounds (decision 6:
  ``is_backup_name``).
- ``show hana`` with no look uses only the picture named exactly ``hana`` (F04 PR-F04-07:
  "it shows the image named exactly hana"), which is what P1's rows already count.

Pure: reads its inputs, never runs author code. The one read is the meters' ``points``
lines (``MeterSpec`` has no place), through ``paths`` and only when a meter is unused.

Imports ``core``, ``script`` and ``runtime`` only, never ``tools.check`` (check imports
lint; ``tests/test_import_rules.py``).
"""

import ast
import re
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from engine.core.config import KeyLocator
from engine.core.config_schema import Config
from engine.core.constants import BUILTIN_POSITIONS, CONFIG_FILENAME
from engine.core.paths import GamePaths
from engine.runtime.character import Character
from engine.runtime.images import BLACK, ImageFile, ImageIndex
from engine.runtime.transitions import CONSTRUCTORS, TransitionDef
from engine.script.labelgraph import LabelLink, block_links
from engine.script.limits import SCRIPT_FILE_MAX_BYTES
from engine.script.messages import format_message
from engine.script.nodes import Define
from engine.script.program import Program

START: Final = "start"
NARRATOR: Final = "narrator"
IMAGES_PREFIX: Final = "images/"
AUDIO_PREFIX: Final = "audio/"

# Each finding kind (a names row kind on Studio's wire, 04 §7.3 step 3) → its code and, for
# W242, the kind word its text names.
LINT_KINDS: Final[Mapping[str, tuple[str, str | None]]] = {
    "unreached": ("W237", None),
    "unused_character": ("W238", None),
    "unused_picture": ("W239", None),
    "unused_sound": ("W240", None),
    "unused_variable": ("W241", None),
    "unused_define": ("W242", "define"),
    "unused_transition": ("W242", "transition"),
    "unused_position": ("W242", "position"),
    "unused_meter": ("W242", "meter"),
}

# Decision 6: a backup is a file whose stem ends in "~" or that holds "copy" or "backup" as a
# whole run of letters (W02's "old" and "draft" are left out: "bg old_park" is a picture).
_BACKUP_WORDS: Final = frozenset(("copy", "backup"))
_LETTER_RUN = re.compile(r"[^\W\d_]+")
_POINTS_LINE = re.compile(r"points[ \t]+(.*)")
_IDENTIFIER = re.compile(r"[^\W\d]\w*")
_POINTS_STOP = frozenset(("to", "start"))

NameRow = tuple[str, str | None, int | None]


@dataclass(frozen=True, slots=True)
class Finding:
    """One W237–W242 finding: ``kind`` (a ``LINT_KINDS`` key), the thing's ``name``, its
    place (``file`` ref or None, ``line`` or None) and the message ``args``."""

    code: str
    kind: str
    name: str
    file: str | None
    line: int | None
    args: tuple[str, ...]

    @property
    def text(self) -> str:
        return format_message(self.code, self.args)

    @property
    def row(self) -> NameRow:
        """The names row the check child sends under ``kind``."""
        return (self.name, self.file, self.line)


def is_backup_name(ref: str) -> bool:
    """True for a backup-looking picture or sound file (decision 6)."""
    name = ref.rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    if stem.endswith("~") or name.endswith("~"):
        return True
    return any(run in _BACKUP_WORDS for run in _LETTER_RUN.findall(name.casefold()))


def reached(links: Iterable[LabelLink], starts: Iterable[str]) -> frozenset[str]:
    """Every label a chain of links reaches from ``starts`` (the starts included)."""
    leads: dict[str, list[str]] = {}
    for link in links:
        leads.setdefault(link.src, []).append(link.dst)
    seen = set(starts)
    todo = deque(seen)
    while todo:
        for dst in leads.get(todo.popleft(), ()):
            if dst not in seen:
                seen.add(dst)
                todo.append(dst)
    return frozenset(seen)


def starts_of(program: Program) -> tuple[str, ...]:
    """``start``, then each scene replay's label (decision 7), each once."""
    return tuple(dict.fromkeys((START, *(replay.label for replay in program.replays))))


def _names(uses: Mapping[str, Iterable[object]], *kinds: str) -> set[str]:
    """The names of ``kinds``' use rows (tuples, or rows with ``name``)."""
    found: set[str] = set()
    for kind in kinds:
        for row in uses.get(kind, ()):
            name = row[0] if isinstance(row, tuple) else getattr(row, "name", None)
            if isinstance(name, str):
                found.add(name)
    return found


def _place(node: object) -> tuple[str | None, int | None]:
    file = getattr(node, "file", None)
    return getattr(file, "ref", file if isinstance(file, str) else None), \
        getattr(node, "line", None)


def _literal_call(define: Define) -> str | None:
    """The callee's name when a define's value is a plain ``Name(...)`` call (read, never
    run), else None."""
    try:
        tree = ast.parse(define.value.source.strip(), mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    body = tree.body
    if isinstance(body, ast.Call) and isinstance(body.func, ast.Name):
        return body.func.id
    return None


def _unreached(program: Program) -> list[Finding]:
    links = (link for name, label in program.labels.items()
             for link in block_links(name, label.block))
    seen = reached(links, starts_of(program))
    return [Finding("W237", "unreached", name, *_place(label), (name,))
            for name, label in program.labels.items() if name not in seen]


def _defines(program: Program, namespace: Mapping[str, object] | None,
             uses: Mapping[str, Iterable[object]]) -> list[Finding]:
    """W238 (only with a namespace) and W242's ``define``/``transition``."""
    spoken = _names(uses, "character_use", "define_use")
    named = _names(uses, "define_use", "transition_use")
    out: list[Finding] = []
    for define in program.defines:
        name = define.name
        if name == NARRATOR:
            continue
        value = namespace.get(name) if namespace is not None else None
        callee = _literal_call(define)
        if isinstance(value, Character) or (value is None and callee == "Character"):
            if namespace is not None and isinstance(value, Character) and name not in spoken:
                out.append(Finding("W238", "unused_character", name, *_place(define),
                                   (name,)))
            continue
        if name in named:
            continue
        transition = isinstance(value, TransitionDef) or (
            namespace is None and callee in CONSTRUCTORS)
        kind = "transition" if transition else "define"
        out.append(Finding("W242", f"unused_{kind}", name, *_place(define), (kind, name)))
    return out


def _pictures(program: Program, index: ImageIndex,
              uses: Mapping[str, Iterable[object]]) -> list[Finding]:
    """W239: every index name but ``black``; a declared one at its ``image`` line, a file
    in ``images/`` at the file (backups left out); one finding per name without case."""
    used = {name.casefold() for name in _names(uses, "image_use")}
    declared = program.images or {}
    seen: set[str] = set()
    out: list[Finding] = []
    for name, image in index.items():
        folded = name.casefold()
        if name == BLACK or folded in used or folded in seen:
            continue
        decl = declared.get(name)
        if decl is not None:
            file, line = _place(decl)
        elif isinstance(image, ImageFile) and image.ref.startswith(IMAGES_PREFIX) \
                and not is_backup_name(image.ref):
            file, line = image.ref, None
        else:
            continue
        seen.add(folded)
        out.append(Finding("W239", "unused_picture", name, file, line, (name,)))
    return out


def _sounds(audio_refs: Iterable[str], uses: Mapping[str, Iterable[object]]) -> list[Finding]:
    """W240: each file under ``audio/`` (named relative to it), backups left out."""
    used = {name.removeprefix(AUDIO_PREFIX) for name in _names(uses, "audio_use")}
    out: list[Finding] = []
    for ref in dict.fromkeys(audio_refs):
        ref = ref.removeprefix(AUDIO_PREFIX)
        if ref in used or is_backup_name(ref):
            continue
        out.append(Finding("W240", "unused_sound", ref, AUDIO_PREFIX + ref, None, (ref,)))
    return out


def _variables(program: Program, uses: Mapping[str, Iterable[object]]) -> list[Finding]:
    """W241: each story variable (``default``; persistent ones are separate)."""
    used = _names(uses, "variable_use")
    return [Finding("W241", "unused_variable", d.name, *_place(d), (d.name,))
            for d in program.defaults if d.name not in used]


def _positions(config: Config, uses: Mapping[str, Iterable[object]],
               config_text: str | None) -> list[Finding]:
    """W242 ``position``: the author's ``[stage.positions]`` (not left, center, right), at
    its config.toml line."""
    used = _names(uses, "position_use")
    locator = KeyLocator(config_text) if config_text is not None else None
    out: list[Finding] = []
    for name in config.stage.positions:
        if name in BUILTIN_POSITIONS or name in used:
            continue
        line = None
        if locator is not None:
            line = locator.line_of("stage", "positions", name) \
                or locator.line_of("stage", "positions")
        out.append(Finding("W242", "unused_position", name, CONFIG_FILENAME, line,
                           ("position", name)))
    return out


def _points_names(text: str) -> list[str]:
    """The meter names of a ``points a b 0 to 10 start 3`` line's rest."""
    names: list[str] = []
    words = text.split("#", 1)[0].split()
    for index, word in enumerate(words):
        if word in _POINTS_STOP or _IDENTIFIER.fullmatch(word) is None:
            break
        if word == "ranks" and words[index + 1:index + 2] \
                and words[index + 1].startswith('"'):        # F62: ranks "Friend" 4 (ADR-0010)
            break
        names.append(word)
    return names


def meter_places(program: Program, paths: GamePaths,
                 wanted: Iterable[str]) -> dict[str, tuple[str, int]]:
    """Each ``wanted`` meter's ``points`` line ``(ref, line)``, read from the story's files
    through ``paths`` (an unreadable file gives no place)."""
    left = set(wanted)
    found: dict[str, tuple[str, int]] = {}
    for script in program.files:
        if not left:
            break
        try:
            text = paths.read_file(script.ref, max_bytes=SCRIPT_FILE_MAX_BYTES).decode(
                "utf-8-sig")
        except Exception:                                # no place, never a failed lint
            continue
        for number, line in enumerate(text.splitlines(), 1):
            match = _POINTS_LINE.match(line)
            if match is None:
                continue
            for name in _points_names(match.group(1)):
                if name in left:
                    left.discard(name)
                    found[name] = (script.ref, number)
    return found


def _meters(program: Program, paths: GamePaths | None,
            uses: Mapping[str, Iterable[object]]) -> list[Finding]:
    """W242 ``meter``: each declared meter no ``points`` change or ``points.<name>`` names."""
    used = _names(uses, "meter_use")
    unused = [spec.name for spec in program.meters if spec.name not in used]
    if not unused:
        return []
    places = meter_places(program, paths, unused) if paths is not None else {}
    return [Finding("W242", "unused_meter", name, *places.get(name, (None, None)),
                    ("meter", name)) for name in unused]


def _key(finding: Finding) -> tuple[str, str, int, str]:
    return (finding.code, finding.file or "", finding.line or 0, finding.name)


def findings(program: Program, config: Config, paths: GamePaths | None, index: ImageIndex,
             audio_refs: Iterable[str], namespace: Mapping[str, object] | None,
             uses: Mapping[str, Iterable[object]],
             config_text: str | None) -> tuple[Finding, ...]:
    """Every W237–W242 finding of a story that loaded, sorted by code, file, line, name.

    ``index`` is the image index the use rows were counted against, ``audio_refs`` the
    files under ``audio/`` (relative to it), ``namespace`` the launch's values (None under
    ``--no-launch``: no W238, and a define is a transition only when its value is a literal
    ``Dissolve``/``Fade``/``Mask`` call), ``uses`` the check's ``*_use`` rows by kind, and
    ``config_text`` config.toml's text (None: positions get no line)."""
    found = [*_unreached(program), *_defines(program, namespace, uses),
             *_pictures(program, index, uses), *_sounds(audio_refs, uses),
             *_variables(program, uses), *_positions(config, uses, config_text),
             *_meters(program, paths, uses)]
    return tuple(sorted(found, key=_key))


def rows_by_kind(found: Iterable[Finding], *, characters: bool = True
                 ) -> dict[str, list[NameRow]]:
    """The names rows of ``found``: every ``LINT_KINDS`` kind (empty when nothing), but
    ``unused_character`` only when ``characters`` (a full check, PR-F41-01)."""
    rows: dict[str, list[NameRow]] = {kind: [] for kind in LINT_KINDS
                                      if characters or kind != "unused_character"}
    for finding in found:
        if finding.kind in rows:
            rows[finding.kind].append(finding.row)
    return rows


__all__ = ["Finding", "LINT_KINDS", "findings", "is_backup_name", "meter_places", "reached",
           "rows_by_kind", "starts_of"]

"""``show meter`` / ``hide meter``: a meter on screen (F62 round 2, specs/F62-visible-meters).

Why this module exists: meters (F22) are saved and checked but players never see them. A
story shows one in the status corner with ``show meter hana`` and takes it away with ``hide
meter hana``; how it looks (bar, number, hearts, pips, dial), where, and its label come from
``[meter.<name>]`` in config.toml, then the kit (``kits.meter_look``).

**Positional words** (ADR-0010 rule 2). ``meter`` is no new statement word: it is a word only
right after ``show`` or ``hide``, and only when what it needs follows.

- ``show meter <name>…`` is the meter form when one or more words follow ``meter`` and none
  is a sprite modifier (``at``, ``as``, ``with``…) or a number. Otherwise the line shows the
  picture whose tag is ``meter``, as before (``show meter``, ``show meter hana at left``).
  W293 points out ``show meter hana with dissolve``, where the author meant the meter.
- ``hide meter <name>…`` is the meter form whenever anything follows ``meter``: ``hide`` takes
  one tag, so that line was an error before. ``hide meter`` alone hides the sprite ``meter``.
- ``meter`` stays a valid name for a variable, character, picture or meter.

Several names may follow (``show meter hana sanity``), in the order they stack.

**Checks.** Parse: E417 (something other than names after ``meter``), E418 (a name twice, or
more than ``NAMES_MAX``). Whole game (``check_story``): E233 for a name no ``points`` line
declares (did-you-mean); W291 for a ``[meter.<name>]`` table naming no meter; W292 for a
meter shown with a look that needs a range (bar, hearts, pips, dial) when its ``points`` line
gave none (it is drawn as a number); W293 as above.

``MeterShow`` is not a checkpoint and not part of the voice's look-past set; story map and
reach treat it as a plain statement (it never branches). At run time it changes
``GameState.points``'s shown list (``runtime/points.py``), so saves and rollback restore it.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from engine.core.constants import CONFIG_FILENAME
from engine.script.diagnostics import Diagnostic, ScriptWarning
from engine.script.identity import walk_block
from engine.script.messages import format_message
from engine.script.nodes import Label, Node, Statement
from engine.script.statements import ParseContext
from engine.script.suggest import suggest
from engine.script.words import canonical_name, is_name

WORD_METER: Final = "meter"
NAMES_MAX: Final = 8                    # names on one show/hide meter line
# Looks that draw a share of the range; a meter with no range is drawn as a number.
RANGED_LOOKS: Final = frozenset(("bar", "hearts", "pips", "dial"))


@dataclass(slots=True, kw_only=True)
class MeterShow(Statement):
    """``show meter <name>…`` (``shown`` True) or ``hide meter <name>…`` (False). ``names`` are
    canonical, in the order written. Not a checkpoint."""

    names: tuple[str, ...]
    shown: bool

    def identity_key(self) -> tuple[str, ...]:
        return ("meter", "show" if self.shown else "hide", *self.names)


# --- Parsing (called from stage.parse_show / parse_hide) ------------------------------------

def is_meter_line(word: str, chunks: list[Any], is_word: str, is_number: str) -> bool:
    """Whether a ``show``/``hide`` line whose chunks after the word are ``chunks`` is the
    meter form (module docstring). ``is_word`` and ``is_number`` are stage.py's chunk kinds."""
    if len(chunks) < 2 or chunks[0].kind != is_word or chunks[0].text != WORD_METER:
        return False
    if word == "hide":
        return True
    return not any(c.is_modifier() or c.kind == is_number for c in chunks[1:])


def parse_meter_line(raw: Any, ctx: ParseContext, word: str, chunks: list[Any], colon: bool,
                     is_word: str) -> MeterShow | None:
    """The ``MeterShow`` of a line ``is_meter_line`` accepted, or None with E417/E418."""
    names: list[str] = []
    for chunk in chunks[1:]:
        if chunk.is_modifier():
            ctx.error("E417", "modifier", word, chunk.text)
            return None
        name = canonical_name(chunk.text) if chunk.kind == is_word else ""
        if not name or not is_name(name):
            ctx.error("E417", "name", word, chunk.text)
            return None
        if name in names:
            ctx.error("E418", "twice", word, name)
            return None
        names.append(name)
    if len(names) > NAMES_MAX:
        ctx.error("E418", "many", word, NAMES_MAX)
        return None
    if colon:
        ctx.error("E417", "colon", word, "")
        return None
    return MeterShow(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                     names=tuple(names), shown=word == "show")


# --- Whole-game checks -----------------------------------------------------------------------

def meter_specs(nodes: Iterable[Node]) -> dict[str, Any]:
    """Every declared meter → its ``PointsDecl`` (the first, if declared twice: E231)."""
    from engine.script.points import PointsDecl     # points.py imports stage.py, which imports us
    out: dict[str, Any] = {}
    for node in nodes:
        if isinstance(node, PointsDecl):
            for name in node.names:
                out.setdefault(name, node)
    return out


def _statements(nodes: Iterable[Node]) -> Iterable[Statement]:
    for node in nodes:
        if isinstance(node, Label):
            for stmt, _ in walk_block(node.block):
                yield stmt


def check_story(nodes: Iterable[Node], add: Callable[[Diagnostic], object],
                looks: Any = None) -> list[ScriptWarning]:
    """E233 to ``add``; W291–W293 returned. ``looks`` is the config (for
    ``kits.meter_look`` and ``config.meter``), or None (tools without one: W291 and W292 are
    skipped)."""
    from engine.core.kits import meter_look
    from engine.script.stage import Show
    nodes = list(nodes)
    meters = meter_specs(nodes)
    known = tuple(meters)
    warnings: list[ScriptWarning] = []
    ranged_warned: set[str] = set()
    for stmt in _statements(nodes):
        if isinstance(stmt, MeterShow):
            for name in stmt.names:
                if name not in meters:
                    add(Diagnostic("E233", stmt.file, stmt.line, None,
                                   (name, suggest(name, known)), stmt=stmt.line))
                    break
                if (stmt.shown and looks is not None and name not in ranged_warned
                        and not meters[name].ranged):
                    look = meter_look(looks, name)[0]
                    if look in RANGED_LOOKS:
                        ranged_warned.add(name)
                        warnings.append(ScriptWarning(
                            format_message("W292", (name, look)), code="W292",
                            file=stmt.file.ref, line=stmt.line))
        elif isinstance(stmt, Show):
            words = stmt.image.split(" ")
            if words[0] == WORD_METER and len(words) > 1 and words[1] in meters:
                warnings.append(ScriptWarning(format_message("W293", (stmt.image,)),
                                              code="W293", file=stmt.file.ref,
                                              line=stmt.line))
    tables: Mapping[str, Any] = getattr(looks, "meter", None) or {}
    for name, table in tables.items():
        if name not in meters:
            warnings.append(ScriptWarning(
                format_message("W291", (name, suggest(name, known))), code="W291",
                file=CONFIG_FILENAME, line=getattr(table, "line", None)))
    return warnings


__all__ = ["MeterShow", "NAMES_MAX", "RANGED_LOOKS", "WORD_METER", "check_story",
           "is_meter_line", "meter_specs", "parse_meter_line"]

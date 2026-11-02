"""Transitions in the runtime: the define constructors, the spec a ``with`` sends, and the
launch check (F09 ``04-technical.md`` §3, §4.2, §5.2, §5.3; SR-F09-02, 07, 08; E190, E191,
E194's launch form, E199, W60).

Why this module exists: a ``with`` names a built-in (``cut``, ``dissolve``, ``fade``) or a
define made with ``Dissolve``, ``Fade``, or ``Mask``. What the name means is known only
after the defines are set, so the launch checks every ``with`` once (``TransitionCheck``,
in F04's phase 5) and the runtime merges the clause over its transition into one immutable
``TransitionSpec`` per statement (``spec_for``, memoized on the interpreter). The spec
holds names, numbers, and colors only: a ``None`` length or color is the ``[effects]`` /
``[theme.effects]`` default, resolved by the presentation, so headless output never
depends on ``config.toml``.

The constructors run inside F03's define evaluation, under the guard; a bad argument is
E199 at the define (``TransitionArgError``, an ``AuthorRefusal`` without the define prefix).
A ``TransitionDef`` is never story state: ``freeze`` refuses it (E85e). ``Mask``'s file is
the only content path: ``check_ref`` and the image suffixes here, the launch's ``locate``
(W60), and later ``AssetManager.image`` (F09 step 3).

Pure (TR-F03-05): no file, clock, or randomness; ``locate`` is injected.
"""

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from engine.core.constants import (COLOR_WORDS, IMAGE_SUFFIXES, MASK_SOFT_RANGE,
                                   TRANSITION_SECONDS_RANGE, VALUE_ECHO_MAX_CHARS)
from engine.core.errors import AssetRefError
from engine.core.paths import REASON_OUTSIDE, check_ref
from engine.core.redact import echo
from engine.runtime.character import Character
from engine.runtime.errors import AuthorRefusal, StoryError, where
from engine.runtime.values import kind_words, register_kind
from engine.script.diagnostics import ScriptWarning
from engine.script.effects import BUILTIN_TRANSITION_NAMES, WithClause
from engine.script.messages import TRANSITION_LIST_MAX, format_message
from engine.script.nodes import Statement
from engine.script.suggest import suggest

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter

Locate = Callable[[str], tuple[bool, str | None]]

_MISSING = object()
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


# --- Values (04 §3) ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TransitionDef:
    """A define's value (``Dissolve``, ``Fade``, ``Mask``). ``seconds`` None follows
    ``[effects]``; ``color`` (fade) ``#RRGGBB`` or None for ``[theme.effects] fade_color``;
    ``mask`` (mask) a game-relative image ref."""

    kind: str                       # "dissolve" | "fade" | "mask" | "glitch" (F28)
    seconds: float | None
    color: str | None = None
    mask: str | None = None
    soft: float = 0.1
    reverse: bool = False
    direction: str | None = None    # Could: wipes


@dataclass(frozen=True, slots=True)
class TransitionSpec:
    """One ``with``, its overrides applied (04 §3): ``kind`` a ``KINDS`` key, ``name`` as
    written, ``sid`` the ``with`` statement's (W61, W62). ``calm`` and ``flashes`` are F28's
    seam: the built-ins are calm and don't flash."""

    kind: str
    name: str
    sid: str
    seconds: float | None
    color: str | None
    mask: str | None
    soft: float
    reverse: bool
    direction: str | None
    calm: bool = True
    flashes: bool = False


register_kind(TransitionDef, "a transition")

# The built-ins (SR-F09-02): ``cut`` is no transition (None); the others take the config's
# length and color. F28 (04 §5.2, 07 I-10): ``glitch``'s length is ``[effects] glitch``,
# resolved by the presentation, and its kind is ``render/transitions.KINDS["glitch"]``.
BUILTIN_TRANSITIONS: Final[Mapping[str, TransitionDef | None]] = MappingProxyType({
    "cut": None,
    "dissolve": TransitionDef("dissolve", None),
    "fade": TransitionDef("fade", None),
    "glitch": TransitionDef("glitch", None),
})
assert tuple(BUILTIN_TRANSITIONS) == BUILTIN_TRANSITION_NAMES

# A kind's ``(calm, flashes)`` (F28 04 §5.2, 07 I-3): a kind that isn't calm plays as a
# dissolve under reduced effects; one that flashes counts toward the flash limit when it
# plays as itself under 1 s (W182 when refused). Any other kind is calm and doesn't flash.
KIND_FLAGS: Final[Mapping[str, tuple[bool, bool]]] = MappingProxyType({"glitch": (False, True)})


# --- Constructors (SR-F09-07; E199) ------------------------------------------------------------

class TransitionArgError(AuthorRefusal):
    """A refused constructor argument: E199 at the define, without the define prefix."""

    prefixed = False


def _shown(value: object) -> str:
    """A refused argument in words: numbers and True/False as written, text in quotes,
    anything else by its kind (SR-F03-33)."""
    t = type(value)
    if value is None or t is bool or t is int or t is float:
        return echo(repr(value), VALUE_ECHO_MAX_CHARS)
    if t is str:
        return '"' + echo(value, VALUE_ECHO_MAX_CHARS) + '"'          # type: ignore[arg-type]
    return kind_words(value)


def _refuse(form: str, *args: object) -> TransitionArgError:
    return TransitionArgError.of("E199", form, *args)


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)       # type: ignore[arg-type]


def _seconds(constructor: str, seconds: object) -> float | None:
    if seconds is None:
        return None
    low, high = TRANSITION_SECONDS_RANGE
    if not _number(seconds) or not low <= seconds <= high:            # type: ignore[operator]
        raise _refuse("seconds", constructor, _shown(seconds))
    return float(seconds)                                             # type: ignore[arg-type]


def color_value(value: object) -> str | None:
    """``#RRGGBB`` (upper case) for a color word or a ``"#RRGGBB"`` text, else None."""
    if type(value) is not str:
        return None
    if value in COLOR_WORDS:
        return COLOR_WORDS[value]
    if len(value) == 7 and value[0] == "#" and _HEX_DIGITS.issuperset(value[1:]):
        return value.upper()
    return None


def Dissolve(seconds: object = None) -> TransitionDef:               # noqa: N802 (engine name)
    """``define slow = Dissolve(1.5)``: a crossfade; no length follows ``[effects]``."""
    return TransitionDef("dissolve", _seconds("Dissolve", seconds))


def Fade(seconds: object = None, color: object = None) -> TransitionDef:  # noqa: N802
    """``define white_fade = Fade(0.6, color="#ffffff")``: through a color (a color word or
    ``"#RRGGBB"``; none follows ``[theme.effects] fade_color``)."""
    length = _seconds("Fade", seconds)
    shade = None
    if color is not None:
        shade = color_value(color)
        if shade is None:
            raise _refuse("color", _shown(color))
    return TransitionDef("fade", length, color=shade)


def Mask(file: object = None, seconds: object = None, soft: object = 0.1,  # noqa: N802
         reverse: object = False) -> TransitionDef:
    """``define lantern = Mask("masks/iris.png", 1.2)``: the new picture appears where the
    grayscale image is dark first (``reverse``: light first), with a ``soft`` edge (a
    fraction 0–0.5). ``file`` is a path from the game folder, like ``image``'s."""
    if type(file) is not str:
        raise _refuse("file")
    try:
        check_ref(file)
    except AssetRefError as exc:
        raise _refuse("path", file, None if exc.reason == REASON_OUTSIDE else exc.reason) \
            from None
    if not file.lower().endswith(IMAGE_SUFFIXES):
        raise _refuse("type", file)
    length = _seconds("Mask", seconds)
    low, high = MASK_SOFT_RANGE
    if not _number(soft) or not low <= soft <= high:                  # type: ignore[operator]
        raise _refuse("soft", _shown(soft))
    if type(reverse) is not bool:
        raise _refuse("reverse", _shown(reverse))
    return TransitionDef("mask", length, mask=file, soft=float(soft),  # type: ignore[arg-type]
                         reverse=reverse)


# The names ``build_namespace`` binds in G (``Transition`` stays reserved and unbound, F28).
CONSTRUCTORS: Final[Mapping[str, Callable[..., TransitionDef]]] = MappingProxyType(
    {"Dissolve": Dissolve, "Fade": Fade, "Mask": Mask})


# --- What a name means (04 §5.2) ----------------------------------------------------------------

def defined_transitions(G: Mapping[str, object], names: Iterable[str]) -> list[str]:
    """The define names among ``names`` whose value in ``G`` is a transition, in code-point
    order (E190's suggestion pool and list)."""
    return sorted(n for n in names if type(G.get(n)) is TransitionDef)


def _kind_of(value: object) -> str:
    """E191's kind words: SR-F03-33's, with ``Character`` named as the author writes it."""
    return "a Character" if isinstance(value, Character) else kind_words(value)


def clause_problem(clause: WithClause, stmt: Statement, G: Mapping[str, object],
                   defined: Callable[[], list[str]]) -> StoryError | None:
    """The launch error of one ``with`` (E190, E191, E194's launch form), at ``stmt``, or
    None. ``defined`` gives the transition define names (built only for an E190)."""
    name = clause.name
    if name in BUILTIN_TRANSITIONS:
        return None                     # a color on a built-in other than fade is E194 at load
    value = G.get(name, _MISSING)
    if value is _MISSING:
        names = defined()
        match = suggest(name, [*BUILTIN_TRANSITION_NAMES, *names])
        if match is not None:
            args: tuple = (name, match)
        else:
            shown = names[:TRANSITION_LIST_MAX]
            args = (name, None, tuple(shown), len(names) - len(shown))
        return StoryError(format_message("E190", args), code="E190", **where(stmt))
    if type(value) is not TransitionDef:
        return StoryError(format_message("E191", (name, _kind_of(value))), code="E191",
                          **where(stmt))
    if clause.color is not None and value.kind != "fade":
        return StoryError(format_message("E194", ("launch", name, value.kind)), code="E194",
                          **where(stmt))
    return None


def spec_for(interp: "Interpreter", clause: WithClause, sid: str) -> TransitionSpec | None:
    """The ``TransitionSpec`` of the ``with`` of statement ``sid`` (04 §5.3), memoized per
    sid on the interpreter (``transition_specs``; defines never change during a run). None
    is a cut: ``cut``, or a resolved length of exactly 0. A name the launch check would
    refuse (only without phase 5) raises its launch error here, at run time."""
    memo = interp.transition_specs
    if sid in memo:
        return memo[sid]
    spec = _spec(interp, clause, sid)
    memo[sid] = spec
    return spec


def _spec(interp: "Interpreter", clause: WithClause, sid: str) -> TransitionSpec | None:
    name = clause.name
    if name in BUILTIN_TRANSITIONS:
        base = BUILTIN_TRANSITIONS[name]
    else:
        value = interp.G.get(name, _MISSING)
        if type(value) is not TransitionDef or (clause.color is not None
                                                and value.kind != "fade"):
            stmt = interp.program.get(sid)
            assert stmt is not None
            error = clause_problem(clause, stmt, interp.G, lambda: defined_transitions(
                interp.G, interp.program.define_names))
            assert error is not None
            raise error
        base = value
    if base is None:
        return None
    seconds = clause.seconds if clause.seconds is not None else base.seconds
    if seconds == 0:
        return None
    calm, flashes = KIND_FLAGS.get(base.kind, (True, False))
    return TransitionSpec(kind=base.kind, name=name, sid=sid, seconds=seconds,
                          color=clause.color if clause.color is not None else base.color,
                          mask=base.mask, soft=base.soft, reverse=base.reverse,
                          direction=base.direction, calm=calm, flashes=flashes)


# --- The launch check (04 §5.2; F04 phase 5) --------------------------------------------------

class TransitionCheck:
    """``visit`` each statement in reading order (F04's ``StageCheck`` check pass does):
    each ``with`` that the launch refuses adds its error to ``errors``. ``missing_masks``
    then gives W60's records: each distinct ``Mask`` file of a define (define order) that
    ``locate`` can't find, with its define and the suggestion. With no ``locate`` (headless
    runs) there are none, as F08 skips its file check."""

    def __init__(self, program: object, G: Mapping[str, object], *,
                 locate: Locate | None = None) -> None:
        self.program = program
        self.G = G
        self.locate = locate
        self.errors: list[StoryError] = []
        self._defined: list[str] | None = None

    def defined(self) -> list[str]:
        if self._defined is None:
            self._defined = defined_transitions(
                self.G, self.program.define_names)                # type: ignore[attr-defined]
        return self._defined

    def visit(self, stmt: object) -> None:
        clause = getattr(stmt, "with_clause", None)
        if clause is None:
            return
        error = clause_problem(clause, stmt, self.G, self.defined)  # type: ignore[arg-type]
        if error is not None:
            self.errors.append(error)

    def missing_masks(self) -> list[tuple[Statement, tuple[str, str, str | None]]]:
        """``(define, (file, define name, suggestion))`` for W60, define order."""
        locate = self.locate
        if locate is None:
            return []
        out = []
        seen: set[str] = set()
        for define in self.program.defines:                         # type: ignore[attr-defined]
            value = self.G.get(define.name)
            if type(value) is not TransitionDef or value.mask is None or value.mask in seen:
                continue
            seen.add(value.mask)
            exists, suggestion = locate(value.mask)
            if not exists:
                out.append((define, (value.mask, define.name, suggestion)))
        return out


def check_transitions(program: object, G: Mapping[str, object], *,
                      locate: Locate | None = None
                      ) -> tuple[list[StoryError], list[ScriptWarning]]:
    """The whole launch check in one go (tests and tools): E190, E191, E194 in reading
    order, then W60 (only with ``locate``)."""
    check = TransitionCheck(program, G, locate=locate)
    for stmt in program.iter_statements():                          # type: ignore[attr-defined]
        check.visit(stmt)
    warnings = [ScriptWarning(format_message("W60", args), code="W60", file=define.file.ref,
                              line=define.line)
                for define, args in check.missing_masks()]
    return check.errors, warnings


def transition_failed_text(name: str, error_type: str) -> str:
    """W62, built-in form (07 I-9; no code transitions before F28): the presentation logs it
    (``render/stage.py``, with the ``with`` statement's location in front) when a kind fails
    to draw. The text is ``script/messages.py``'s."""
    return format_message("W62", (name, error_type))


def flash_refused_text() -> str:
    """W61, ``flash`` form: the flash was not drawn (06 AC-F09-36; ``script/messages.py``)."""
    return format_message("W61", ("flash",))


def fade_refused_text() -> str:
    """W61, fade form: a fade under 1 s played as a dissolve (``script/messages.py``)."""
    return format_message("W61", ("fade",))


__all__ = ["BUILTIN_TRANSITIONS", "CONSTRUCTORS", "Dissolve", "Fade", "KIND_FLAGS", "Locate",
           "Mask", "TransitionArgError", "TransitionCheck", "TransitionDef", "TransitionSpec",
           "check_transitions", "clause_problem", "color_value", "defined_transitions",
           "fade_refused_text", "flash_refused_text", "spec_for", "transition_failed_text"]

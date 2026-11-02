"""NVL mode at run time: the mode and the page record (F17 ``04-technical.md`` §4, §5.2,
§7.1, §10; ``07-architecture-review.md`` A1–A3, I-3–I-6).

Why this module exists: full-screen text keeps a **page record**, the lines shown since the
last page reset, as they were shown, so a load, a rollback, or a hot reload rebuilds the page
the player saw. The record is a display record (architecture "Display records", F17 07 A1):
resolved text, never parsed as markup, never re-resolved, never read by story logic, and
bounded when recorded. It lives in ``GameState.nvl`` (``NvlState``), so saves carry it and a
restore or rollback brings it back with no extra work.

- ``run_nvl`` is the ``Nvl`` executor (04 §7.1): ``nvl on`` in ADV, ``nvl clear`` in NVL, and
  ``nvl off`` in NVL change the state, clear ``kept_line``, and hold ``NvlPage(on)``; the
  other cases change nothing and hold nothing (TR-F17-06). Not a checkpoint.
- ``record_line`` is ``take_checkpoint`` step 2b: in NVL, the checkpoint's one ``Say`` (a
  line, or a menu's question) is added (``line_of``); past ``NVL_PAGE_MAX`` lines the oldest
  drops, and dev runs log **W102** once per run. Restore presenters never take checkpoints,
  so nothing is recorded twice.
- ``on_pick`` is F07's ``on_choose`` seam: a pick in NVL starts a new, empty page.
- ``line_of`` builds an ``NvlLine`` from a ``Say`` (``plain()``, speed reset, equal
  neighbours merged, then the caps: ``NVL_SPANS_MAX`` spans and ``NVL_TEXT_MAX`` code points,
  cut with "…"; the name at ``NVL_NAME_MAX``), so a checkpoint never holds what ``from_json``
  refuses. The presentation (F17 step 2) uses the same ``line_of`` (I-5).

Shared, never copied per line: ``add`` builds one tuple of at most ``NVL_PAGE_MAX``
references; earlier lines are the same objects in every snapshot (TR-F17-05).

Saved (04 §4): ``to_json``/``from_json`` are ``GameState``'s ``nvl`` key, always written and
optional on read (absent: ``EMPTY_NVL``). ``from_json`` checks counts first, then exact keys,
types, and ranges; sids are checked by type and length only, never resolved. Anything else is
``StateInvalid("nvl")``, never echoing the input. F29 (``07`` §2.1, I-1): a span's style may
carry ``"effect"``, one of the nine ``kind:strength`` strings, written last and only when set;
``STATE_FORMAT`` stays 1 (a pre-F29 engine reports such a save DAMAGED: span keys are an exact
set, and downgrades aren't supported). F30 (``04`` §4.2, ``07`` I-3): a ``{username}`` span is
recorded flagged (``plain(names=True)``: its text is the fallback word, never merged with a
neighbour) and writes ``"username": true`` after ``"effect"``; only ``true`` is read back.

``NvlLine`` is ``runtime/commands.py``'s (07 I-4) and is not re-exported here. Layering (as
``history.py``): ``state.py`` imports this module, so ``StateInvalid`` is imported only when
raised and the interpreter only for annotations. Pure: no file, clock, or randomness; no
pygame.
"""

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from engine.runtime.commands import NvlLine, NvlPage, Say, Span, Style, TextEffect
from engine.runtime.limits import POSITION_MAX_CHARS
from engine.script.diagnostics import ScriptWarning
from engine.script.messages import format_message
from engine.script.nvl import Nvl
from engine.script.texttags import EFFECT_KINDS, STRENGTHS

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.script.nodes import Statement

NVL_PAGE_MAX: Final = 32               # PR-F17-09: lines kept since the last page reset
NVL_TEXT_MAX: Final = 12_000           # code points of span text per line (C2, D4)
NVL_SPANS_MAX: Final = 4_000           # spans per line (C2, D4)
NVL_NAME_MAX: Final = 200              # a line's name, as F13's
ELLIPSIS: Final = "…"
SIZE_RANGE: Final = (0.5, 2.0)         # Style.size, as {size} (F05 SR-F05-06)

_KEYS: Final = frozenset(("on", "page"))
_LINE_KEYS: Final = frozenset(("sid", "name", "color", "spans"))
_SPAN_KEYS: Final = frozenset(("text", "bold", "italic", "color", "size", "effect",
                               "username"))         # F30
# F29 (07 I-1): the nine saved effect values, each read back as its one shared TextEffect.
_EFFECTS: Final = {effect.key(): effect for effect in
                   (TextEffect(kind, strength) for kind in EFFECT_KINDS for strength in STRENGTHS)}
EFFECT_KEYS: Final = frozenset(_EFFECTS)
_COLOR: Final = re.compile(r"#[0-9A-Fa-f]{6}")
_SURROGATE_PAIR: Final = re.compile("[\ud800-\udbff][\udc00-\udfff]")


@dataclass(frozen=True, slots=True)
class NvlState:
    """``GameState.nvl``: the text mode (``on``: full-screen text) and the page record,
    oldest first, at most ``NVL_PAGE_MAX`` lines; ``page`` is ``()`` whenever ``on`` is
    False. Compares by value; tuple comparison short-circuits on shared lines."""

    on: bool = False
    page: tuple[NvlLine, ...] = ()

    def add(self, line: NvlLine) -> "tuple[NvlState, bool]":
        """``line`` appended (one new tuple of references), and whether the oldest line
        was dropped to keep ``NVL_PAGE_MAX``."""
        assert self.on, "NvlState.add in ADV"
        page = self.page + (line,)
        if len(page) > NVL_PAGE_MAX:
            return NvlState(True, page[len(page) - NVL_PAGE_MAX:]), True
        return NvlState(True, page), False

    def to_json(self) -> dict[str, object]:
        """``{"on": bool, "page": [{"sid", "name", "color", "spans": [{"text", ...}]}]}``,
        fresh plain values (always written). A span writes only its non-default style keys:
        ``bold``/``italic`` (``true`` only), ``color``, ``size`` (not 1.0), ``effect`` (F29,
        when set, last)."""
        return {"on": self.on, "page": [_line_json(line) for line in self.page]}

    @staticmethod
    def from_json(obj: object) -> "NvlState":
        """Validate an untrusted saved ``nvl`` value (04 §4, §8 item 4): at most
        ``NVL_PAGE_MAX`` lines and ``NVL_SPANS_MAX`` spans per line (counted before anything
        is built), exact key sets and types (a ``str`` subclass is refused), ``on`` False
        only with an empty page, a sid of at most 1,024 characters, a name of at most
        ``NVL_NAME_MAX``, ``color`` null or ``#RRGGBB``, non-empty span texts of at most
        ``NVL_TEXT_MAX`` code points in all, and only non-default style keys (``effect``: one
        of the nine ``kind:strength`` strings). Raises
        ``StateInvalid("nvl")`` only; its text never holds any part of the input."""
        try:
            return _from_json(obj)
        except _Invalid:
            pass
        except Exception:                   # defensive: the contract is StateInvalid only
            pass
        from engine.runtime.state import StateInvalid   # state.py imports this module
        raise StateInvalid("nvl") from None

    def save_problem(self) -> str | None:
        """F11 C11 for this field: ``nvl`` if ``from_json`` would refuse this value's JSON
        or read it back different (only a hand-built state: ``line_of`` keeps every limit),
        ``lone_surrogate`` if a name or span text holds a lone high surrogate right before a
        lone low one (JSON reads the two back as one character); else None. Runs only at
        save time, never per checkpoint (07 I-6)."""
        try:
            back = _from_json(self.to_json())
        except Exception:                   # _Invalid, or a hand-built value of a wrong type
            return "nvl"
        if back != self:
            return "nvl"
        texts = [line.name for line in self.page]
        texts += [span.text for line in self.page for span in line.spans]
        joined = " ".join(texts)            # a space never forms a pair between two texts
        if not joined.isascii() and _SURROGATE_PAIR.search(joined):
            return "lone_surrogate"
        return None


EMPTY_NVL: Final = NvlState()


# --- Recording (04 §4 line_of; 07 I-5) ----------------------------------------------------------

def _cut(text: str, limit: int) -> str:
    """``text`` at most ``limit`` code points: longer ends in "…" (F07's ``cut``)."""
    return text if len(text) <= limit else text[:limit - 1] + ELLIPSIS


def _capped(spans: list[Span]) -> list[Span]:
    """``spans`` within ``NVL_SPANS_MAX`` spans and ``NVL_TEXT_MAX`` code points in all; the
    last kept span of a cut line ends with "…" (C2)."""
    if len(spans) > NVL_SPANS_MAX:
        spans = spans[:NVL_SPANS_MAX]
        last = spans[-1]
        spans[-1] = Span(last.text + ELLIPSIS, last.style)
    total = 0
    for index, span in enumerate(spans):
        size = len(span.text)
        if total + size > NVL_TEXT_MAX:
            keep = NVL_TEXT_MAX - total
            if keep >= 1:                   # cut inside this span
                return spans[:index] + [Span(span.text[:keep - 1] + ELLIPSIS, span.style)]
            prev = spans[index - 1]         # the span before ends right at the limit
            return spans[:index - 1] + [Span(prev.text[:-1] + ELLIPSIS, prev.style)]
        total += size
    return spans


def line_of(say: Say, spans: Iterable[Span] | None = None) -> NvlLine:
    """``say``'s line as recorded: ``spans`` (``say.body.plain()`` unless the caller has it,
    I-6) with ``speed`` reset to 1.0 and equal-style neighbours merged *after* the reset
    (I-5), empty texts left out, then capped (``_capped``); the name as shown (None: ``""``)
    cut at ``NVL_NAME_MAX``; ``name_color`` when it is ``#RRGGBB``, else None. F30 (07 I-3):
    a line with a ``{username}`` span is read with ``plain(names=True)`` instead (a second
    call), and a flagged span is never merged."""
    if spans is None or _has_name(say):
        spans = say.body.plain(names=True)
    merged: list[Span] = []
    for span in spans:
        text = span.text
        if not text:
            continue
        style = span.style
        if style.speed != 1.0:
            style = replace(style, speed=1.0)
            span = Span(text, style)
        if merged and merged[-1].style == style and not style.username:
            merged[-1] = Span(merged[-1].text + text, style)
        else:
            merged.append(span)
    color = say.name_color
    if type(color) is not str or _COLOR.fullmatch(color) is None:
        color = None
    return NvlLine(say.sid, _cut(say.name or "", NVL_NAME_MAX), color, tuple(_capped(merged)))


def _has_name(say: Say) -> bool:
    """F30: whether ``say``'s body holds a flagged ``{username}`` span."""
    return any(type(piece) is Span and piece.style.username for piece in say.body.pieces)


# --- The statement, step 2b, and a pick (04 §7.1) ------------------------------------------------

def _set(interp: "Interpreter", state: NvlState) -> None:
    """A page reset or mode change: the state, no kept line (architecture: a statement that
    empties the textbox clears it), and the held ``NvlPage`` (lines () live)."""
    interp.nvl = state
    interp.kept_line = None
    interp._hold(NvlPage(state.on))


def run_nvl(interp: "Interpreter", stmt: Nvl) -> "Step":
    """``nvl on|off|clear`` (04 §7.1's table). Only a change holds ``NvlPage``: ``on`` in
    NVL, ``off`` or ``clear`` in ADV, and ``clear`` of an empty page change nothing."""
    from engine.runtime.interpreter import Step         # below the interpreter (docstring)
    nvl = interp.nvl
    action = stmt.action
    if action == "on":
        if not nvl.on:
            _set(interp, NvlState(True, ()))
    elif action == "off":
        if nvl.on:
            _set(interp, EMPTY_NVL)
    elif nvl.on and nvl.page:                           # clear
        _set(interp, NvlState(True, ()))
    return Step.CONTINUE


def record_line(interp: "Interpreter", say: Say | None, stmt: "Statement", *,
                spans: Iterable[Span] | None = None) -> None:
    """``take_checkpoint`` step 2b (after F13's 2a, before the snapshot): in NVL, ``say`` (the
    checkpoint's one line, or a menu's question) joins the page record; ``spans`` is its
    ``plain()`` when 2a already has it (I-6). When the oldest line drops, dev runs log W102
    (area ``runtime``, at ``stmt``'s line) once per run."""
    nvl = interp.nvl
    if say is None or not nvl.on:
        return
    interp.nvl, dropped = nvl.add(line_of(say, spans))
    if dropped and interp.dev and not interp._w102_logged:
        interp._w102_logged = True
        text = format_message("W102", (NVL_PAGE_MAX + 1,))
        warning = ScriptWarning(text, code="W102", file=stmt.file.ref, line=stmt.line)
        interp.log.warning("%s", warning.format())


def on_pick(interp: "Interpreter") -> None:
    """F07's ``on_choose``, after F13's ``add_pick``: a pick in NVL starts a new, empty page
    (``NvlPage(True)``, released with the next line's burst) and clears ``kept_line``."""
    nvl = interp.nvl
    if not nvl.on:
        return
    if nvl.page:
        _set(interp, NvlState(True, ()))
    else:
        interp.kept_line = None


# --- The JSON form (04 §4) -----------------------------------------------------------------------

def _line_json(line: NvlLine) -> dict[str, object]:
    return {"sid": line.sid, "name": line.name, "color": line.color,
            "spans": [_span_json(span) for span in line.spans]}


def _span_json(span: Span) -> dict[str, object]:
    out: dict[str, object] = {"text": span.text}
    style = span.style
    if style.bold:
        out["bold"] = True
    if style.italic:
        out["italic"] = True
    if style.color is not None:
        out["color"] = style.color
    if style.size != 1.0:
        out["size"] = style.size
    if style.effect is not None:            # F29: last, so effect-free records stay byte-equal
        out["effect"] = style.effect.key()
    if style.username:                      # F30: after effect, only when set
        out["username"] = True
    return out


class _Invalid(Exception):
    pass


def _from_json(obj: object) -> NvlState:
    if type(obj) is not dict or obj.keys() != _KEYS:
        raise _Invalid
    on, raw = obj["on"], obj["page"]
    if type(on) is not bool or type(raw) is not list or len(raw) > NVL_PAGE_MAX:
        raise _Invalid
    if raw and not on:
        raise _Invalid
    for entry in raw:                       # shapes and counts first, before any value is read
        if type(entry) is not dict or entry.keys() != _LINE_KEYS:
            raise _Invalid
        spans = entry["spans"]
        if type(spans) is not list or len(spans) > NVL_SPANS_MAX:
            raise _Invalid
    return NvlState(on, tuple(_line(entry) for entry in raw))


def _line(entry: dict) -> NvlLine:
    sid, name, color = entry["sid"], entry["name"], entry["color"]
    if type(sid) is not str or len(sid) > POSITION_MAX_CHARS:
        raise _Invalid
    if type(name) is not str or len(name) > NVL_NAME_MAX:
        raise _Invalid
    if color is not None and (type(color) is not str or _COLOR.fullmatch(color) is None):
        raise _Invalid
    raw = entry["spans"]
    for span in raw:
        if type(span) is not dict or "text" not in span or not span.keys() <= _SPAN_KEYS:
            raise _Invalid
    total = 0
    spans: list[Span] = []
    for span in raw:
        text = span["text"]
        if type(text) is not str or not text:
            raise _Invalid
        total += len(text)
        if total > NVL_TEXT_MAX:
            raise _Invalid
        spans.append(Span(text, _style(span)))
    return NvlLine(sid, name, color, tuple(spans))


def _style(span: dict) -> Style:
    """A span's style from its optional keys: ``bold``/``italic`` only ``true``, ``color``
    ``#RRGGBB``, ``size`` a finite number in ``SIZE_RANGE`` other than 1.0, ``effect`` (F29)
    an exact ``str`` among ``EFFECT_KEYS``, ``username`` (F30) only ``true``."""
    bold = italic = False
    if "bold" in span:
        if span["bold"] is not True:
            raise _Invalid
        bold = True
    if "italic" in span:
        if span["italic"] is not True:
            raise _Invalid
        italic = True
    color = span.get("color")
    if "color" in span and (type(color) is not str or _COLOR.fullmatch(color) is None):
        raise _Invalid
    size = 1.0
    if "size" in span:
        value = span["size"]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise _Invalid
        if not SIZE_RANGE[0] <= value <= SIZE_RANGE[1] or value == 1.0:
            raise _Invalid
        size = float(value)
    effect = None
    if "effect" in span:
        value = span["effect"]
        if type(value) is not str or value not in EFFECT_KEYS:
            raise _Invalid
        effect = _EFFECTS[value]
    username = "username" in span
    if username and span["username"] is not True:
        raise _Invalid
    return Style(bold=bold, italic=italic, color=color, size=size, effect=effect,
                 username=username)


__all__ = ["EFFECT_KEYS", "ELLIPSIS", "EMPTY_NVL", "NVL_NAME_MAX", "NVL_PAGE_MAX", "NVL_SPANS_MAX",
           "NVL_TEXT_MAX", "NvlState", "line_of", "on_pick", "record_line", "run_nvl"]

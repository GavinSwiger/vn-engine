"""Glitch effects at run time (F28 ``04-technical.md`` §3, §4.1, §6.1–§6.3; ``07`` I-12, I-17;
run code W184).

Why this module exists: an ``effect`` line changes what the stage looks like, but only the
*lasting* glitches (``on`` until ``off``) are story state. Bursts are timing, which the
presentation owns. So the runtime keeps two things:

- **The lasting set** (``GameState.glitch``, ``GlitchState``): the ``GlitchEntry``s that are
  on, in canonical order (tear, colorshift, static, then jitter by tag), at most
  ``GLITCH_ENTRIES_MAX``. Runtime-held like ``stage``: ``interp.glitch`` is the live set,
  ``take_checkpoint`` stores it, restore commits the saved one, new game empties it. JSON
  ``{"on": [{"kind", "size"}, {"kind": "jitter", "tag", "size"}, …]}``, always written,
  optional on read (``EMPTY_GLITCH``); anything else is ``StateInvalid("glitch")``, never
  echoed. A saved jitter whose sprite isn't on the saved stage is dropped (``on_stage``).
- **The pending moment** (``interp.pending_glitch``, runtime-only): the bursts to start and
  the bursts to end first, each by ``(kind, jitter tag)``; the newest instruction for a key
  wins (PR-F28-04).

``run_effect`` is the ``Effect`` executor (one step, never a checkpoint). ``flush`` runs last
in ``flush_stage`` (07 I-17), after ``[Flash]``: it holds one ``Glitch`` when the lasting set
differs from the one last sent or something is pending, and empties the moment. ``hide`` and
``scene`` prune jitter through ``sprite_left`` and ``scene_cleared``. Sizes and lengths of
None are ``[effects]`` defaults, resolved by the presentation, so headless runs never depend
on ``config.toml``.

Dev runs log W184 (area ``runtime``) once per statement when ``effect jitter <tag>`` names a
sprite that isn't on the stage (at most ``GLITCH_WARNED_MAX`` statements); nothing jitters.
``effect jitter <tag> off`` for an absent tag is silent (D6). W182 and W183 are the
presentation's (``glitch_refused_text``, ``glitch_failed_text``).

Layering (04 §2): ``runtime/stage.py`` imports this module, so it imports nothing from
``stage`` at load time (the saved-tag check and ``STAGE_MAX_SPRITES`` are ``limits``',
07 I-12). Pure: no file, clock, or randomness.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from engine.core.constants import GLITCH_KINDS, GLITCH_SIZES
from engine.runtime.commands import Glitch, GlitchBurst, GlitchKey
from engine.runtime.limits import STAGE_MAX_SPRITES, saved_tag_ok
from engine.runtime.values import Value
from engine.script.diagnostics import ScriptWarning
from engine.script.glitch import JITTER, Effect
from engine.script.messages import format_message

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.runtime.stage import StageState

GLITCH_ENTRIES_MAX: Final = 3 + STAGE_MAX_SPRITES        # 259: three kinds, one jitter a sprite
GLITCH_WARNED_MAX: Final = 1_000                         # W184 statements per session
# ``effect off``: every F28 kind ends (``("jitter", None)``: every jitter), in this order.
ALL_STOPS: Final[tuple[GlitchKey, ...]] = tuple((kind, None) for kind in GLITCH_KINDS)
_ORDER: Final = {kind: i for i, kind in enumerate(GLITCH_KINDS)}
_PLAIN_KEYS: Final = frozenset(("kind", "size"))
_JITTER_KEYS: Final = frozenset(("kind", "tag", "size"))


# --- The lasting set (04 §3, §4.1) ----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class GlitchEntry:
    """One lasting glitch: ``kind`` one of ``GLITCH_KINDS``; ``size`` None (``[effects]
    glitch_size``) or one of ``GLITCH_SIZES``; ``tag`` the jittered sprite (jitter only)."""

    kind: str
    size: str | None
    tag: str | None = None

    def to_json(self) -> dict[str, Value]:
        if self.kind == JITTER:
            return {"kind": self.kind, "tag": self.tag, "size": self.size}
        return {"kind": self.kind, "size": self.size}


def _key(entry: GlitchEntry) -> tuple[int, str]:
    return _ORDER[entry.kind], entry.tag or ""


def _canonical(entries: list[GlitchEntry]) -> tuple[GlitchEntry, ...]:
    return tuple(sorted(entries, key=_key))


@dataclass(frozen=True, slots=True)
class GlitchState:
    """``GameState.glitch``: the lasting glitches, canonical (module docstring). Built only by
    its own methods and ``from_json``."""

    on: tuple[GlitchEntry, ...] = ()

    def __post_init__(self) -> None:
        assert list(self.on) == sorted(self.on, key=_key), "GlitchState not canonical"

    def with_entry(self, entry: GlitchEntry) -> "GlitchState":
        """The set with ``entry`` on, replacing the same ``(kind, tag)``."""
        same = (entry.kind, entry.tag)
        kept = [e for e in self.on if (e.kind, e.tag) != same]
        return GlitchState(_canonical(kept + [entry]))

    def _keep(self, keep) -> "GlitchState":
        kept = tuple(e for e in self.on if keep(e))
        if len(kept) == len(self.on):
            return self
        return GlitchState(kept) if kept else EMPTY_GLITCH

    def without(self, kind: str, tag: str | None) -> "GlitchState":
        return self._keep(lambda e: (e.kind, e.tag) != (kind, tag))

    def without_tag(self, tag: str) -> "GlitchState":
        """``hide``: the sprite's jitter goes."""
        return self._keep(lambda e: e.tag != tag)

    def without_jitter(self) -> "GlitchState":
        """``scene``: every jitter goes."""
        return self._keep(lambda e: e.kind != JITTER)

    def on_stage(self, stage: "StageState") -> "GlitchState":
        """Without the jitters of tags that aren't on ``stage``."""
        tags = {sprite.tag for sprite in stage.sprites}
        return self._keep(lambda e: e.kind != JITTER or e.tag in tags)

    def to_json(self) -> dict[str, Value]:
        return {"on": [entry.to_json() for entry in self.on]}

    @staticmethod
    def from_json(obj: object) -> "GlitchState":
        """Validate untrusted ``obj`` (04 §6.3): exactly ``{"on": [...]}``, at most
        ``GLITCH_ENTRIES_MAX`` entries, each with exactly ``kind`` and ``size`` (and ``tag``
        exactly for jitter, by F04's ``saved_tag_ok``), no ``(kind, tag)`` twice. Sorted
        into canonical order; anything else is ``StateInvalid("glitch")``, never echoing the
        input."""
        from engine.runtime.state import StateInvalid   # state.py imports this module
        if type(obj) is not dict or obj.keys() != {"on"}:
            raise StateInvalid("glitch")
        raw = obj["on"]
        if type(raw) is not list or len(raw) > GLITCH_ENTRIES_MAX:
            raise StateInvalid("glitch")
        entries: list[GlitchEntry] = []
        seen: set[tuple[str, str | None]] = set()
        for item in raw:
            if type(item) is not dict:
                raise StateInvalid("glitch")
            kind = item.get("kind")
            if type(kind) is not str or kind not in _ORDER:
                raise StateInvalid("glitch")
            if item.keys() != (_JITTER_KEYS if kind == JITTER else _PLAIN_KEYS):
                raise StateInvalid("glitch")
            size = item["size"]
            if size is not None and (type(size) is not str or size not in GLITCH_SIZES):
                raise StateInvalid("glitch")
            tag = item.get("tag")
            if kind == JITTER and not saved_tag_ok(tag):
                raise StateInvalid("glitch")
            if (kind, tag) in seen:
                raise StateInvalid("glitch")
            seen.add((kind, tag))
            entries.append(GlitchEntry(kind, size, tag))
        return GlitchState(_canonical(entries)) if entries else EMPTY_GLITCH


EMPTY_GLITCH: Final = GlitchState()


# --- The pending moment (04 §3, §6.1) -------------------------------------------------------

@dataclass(slots=True)
class PendingGlitch:
    """What the next moment sends besides the lasting set (runtime-only, neutral at every
    checkpoint): ``stops``, an ordered set of keys whose bursts end first, and ``bursts`` to
    start, by key, in run order."""

    stops: dict[GlitchKey, None] = field(default_factory=dict)
    bursts: dict[GlitchKey, GlitchBurst] = field(default_factory=dict)

    def clear(self) -> None:
        self.stops.clear()
        self.bursts.clear()


def _continue() -> "Step":
    from engine.runtime.interpreter import Step         # below the interpreter (docstring)
    return Step.CONTINUE


def run_effect(interp: "Interpreter", stmt: Effect) -> "Step":
    """The ``Effect`` executor (04 §6.1): ``effect off`` ends every F28 glitch; a burst is
    pending until the next moment; ``on``/``off`` change the lasting set and end any running
    burst of the key. A jitter of a sprite that isn't on the stage does nothing (W184 in dev
    runs, unless ``off``)."""
    pending = interp.pending_glitch
    if stmt.kind is None:                                   # effect off
        interp.glitch = EMPTY_GLITCH
        pending.bursts.clear()
        pending.stops = dict.fromkeys(ALL_STOPS)
        return _continue()
    tag = stmt.tag
    if stmt.kind == JITTER and interp.stage.index_of(tag) is None:   # type: ignore[arg-type]
        if stmt.action != "off":
            _warn_absent(interp, stmt)
        return _continue()
    key = (stmt.kind, tag)
    pending.bursts.pop(key, None)                           # the newest instruction wins
    if stmt.action == "burst":
        pending.bursts[key] = GlitchBurst(stmt.kind, tag, stmt.size, stmt.seconds, stmt.sid)
        return _continue()
    pending.stops.pop(key, None)
    pending.stops[key] = None
    if stmt.action == "on":
        interp.glitch = interp.glitch.with_entry(GlitchEntry(stmt.kind, stmt.size, tag))
    else:
        interp.glitch = interp.glitch.without(stmt.kind, tag)
    return _continue()


def _warn_absent(interp: "Interpreter", stmt: Effect) -> None:
    """W184 (dev runs), once per statement, at most ``GLITCH_WARNED_MAX`` statements."""
    warned = interp.glitch_warned
    if not interp.dev or stmt.sid in warned or len(warned) >= GLITCH_WARNED_MAX:
        return
    warned.add(stmt.sid)
    tags = tuple(sprite.tag for sprite in interp.stage.sprites)
    text = format_message("W184", (stmt.tag, tags))
    warning = ScriptWarning(text, code="W184", file=stmt.file.ref, line=stmt.line)
    interp.log.warning("%s", warning.format())


def flush(interp: "Interpreter") -> None:
    """The end of ``flush_stage`` (04 §6.2): hold ``Glitch(lasting, stops, bursts)`` when the
    lasting set differs from the one last sent or something is pending; then the moment is
    empty."""
    pending = interp.pending_glitch
    glitch = interp.glitch
    if glitch == interp._glitch_shown and not pending.stops and not pending.bursts:
        return
    interp._hold(Glitch(glitch, tuple(pending.stops), tuple(pending.bursts.values())))
    interp._glitch_shown = glitch
    pending.clear()


def sprite_left(interp: "Interpreter", tag: str) -> None:
    """``hide <tag>``: the sprite's lasting jitter and its pending burst go."""
    interp.glitch = interp.glitch.without_tag(tag)
    interp.pending_glitch.bursts.pop((JITTER, tag), None)


def scene_cleared(interp: "Interpreter") -> None:
    """``scene``: every lasting jitter and every pending jitter burst go."""
    interp.glitch = interp.glitch.without_jitter()
    bursts = interp.pending_glitch.bursts
    for key in [k for k in bursts if k[0] == JITTER]:
        del bursts[key]


# --- Presentation texts (W182, W183; ``render`` can't import ``script``) -------------------------

def glitch_refused_text(form: str = "burst") -> str:
    """W182: a burst (``burst``) or a ``with glitch`` (``transition``) refused by the flash
    limit."""
    return format_message("W182", (form,))


def glitch_failed_text(kind: str, error_type: str) -> str:
    """W183: a kind that failed to draw is off for the rest of the run."""
    return format_message("W183", (kind, error_type))


__all__ = ["ALL_STOPS", "EMPTY_GLITCH", "GLITCH_ENTRIES_MAX", "GLITCH_WARNED_MAX",
           "GlitchEntry", "GlitchState", "PendingGlitch", "flush", "glitch_failed_text",
           "glitch_refused_text", "run_effect", "scene_cleared", "sprite_left"]

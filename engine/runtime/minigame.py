"""Minigames at run time (F23 ``04-technical.md`` §3, §4.2, §5.4, §7.1, §7.2, §7.5, §9; ``07``
I-1, I-6, I-7, I-12, I-13; F24 A2; F25 A5).

Why this module exists: a ``minigame`` line hands the story to a plugin and takes one result
back. It is a **checkpoint, like F07's menu** (04 §7.1): the executor evaluates the arguments
in written order, runs the plugin's ``check_args`` (``run_check``), draws a 64-bit seed (always
two PCG32 outputs, so later ``dice`` don't depend on the outcome), records the wait in
``GameState.minigame``, and takes the checkpoint with ``StartMinigame``. A save, a load, or a
rollback landing re-presents it from its snapshot (same arguments and seed) and evaluates
nothing. The runtime holds no plugin object: only ``MinigameSig`` (``core``), whose ``check``
and ``outcome`` callables are the plugin's own code, always called inside one guard entry.

- ``MinigameWait``/``MinigameState`` (``GameState.minigame``): ``{"waiting": null | {"name",
  "args", "seed"}}``, always written, optional on read (``EMPTY_MINIGAME``). ``from_json``
  takes untrusted data (SEC-F23-05(a)): exact keys, ``PLUGIN_NAME_RE``, at most
  ``ARGS_MAX`` argument names (story-variable names, ASCII, ≤ 64), values by the variables'
  rule (``freeze_untrusted``, sharing the state's 2,000,000-member budget), ``seed`` an exact
  ``int`` in range. Anything else is ``StateInvalid("minigame")``, never echoed.
- ``run_minigame`` (the executor), ``present_minigame`` (the presenter: changes no
  interpreter field, 07 I-7(a)), ``minigame_position_ok`` (restore step 2, ``check_only``
  too: the saved name registered, saved names declared, required ones present, then the
  plugin's ``check_args`` on the effective arguments, the saved ones plus each optional
  name's **current** default; a refusal is POSITION_NOT_FOUND, never fatal). A full restore
  of the same ``GameState`` object at the same position reuses that verdict (07 I-6).
- ``on_minigame_done`` accepts one ``MinigameDone`` per ``run`` and hands ``apply`` to
  ``interp.defer`` (never applied inside ``post``, F18 I-3); ``apply`` freezes the result
  (E276), applies the changes in order through ``interp.points``/``interp.codex`` (F22's
  E236, F21's E253 texts; E276's change form), stores the result in the ``into`` variable,
  and sets F14's wall for ``rollback fixed`` (``Minigame.fixed``).
- ``on_minigame_used`` and the ``minigame_used`` pause (``ROLLBACK_PAUSES``, appended at
  import): after a used input back is refused and forward ignored. ``Minigame`` joins F14's
  ``CHAIN_STOPS`` here: a forward chain lands on it and presents it, live.
- ``story_names`` (F24 A2, F25 A5): the declared meters, items, tips, and item categories,
  built once per interpreter; ``StartMinigame.names`` is that one object.
- ``headless_outcome`` (F24 A2): headless with no ``finish`` input, the plugin's
  ``outcome_for("test", …)`` in one guard entry, else the static test outcome.
- ``plugin_failure``: E275's text for an exception from plugin code, built inside the guard
  entry (the plugin file and line from the deepest ``<minigames/…>`` frame, Python's own
  text only when SR-F03-32 lets it through). s4's host builds its E275 the same way.

Interpreter fields (04 §3): ``minigames`` (the launch's signatures), and runtime-only
``minigame_wait`` (goes into the snapshot at a ``Minigame``), ``minigame_run`` (counts up at
every start and every reset, so a late event never matches), ``minigame_accepted``, and
``minigame_used``; the reset helper (``Interpreter._reset_runtime``) commits the restored wait
and clears the flags for new game, restore, and F14's landings (07 I-7).

Layering (as ``menu.py``): ``state.py`` holds a ``MinigameState``, so this module sits below
the interpreter and imports ``state``, the interpreter, and ``codex`` only inside functions.
Pure (TR-F03-05): no file, clock, or randomness of its own; the seed is the story's PCG32.
Log area ``plugin`` (04 §1.1).
"""

import keyword
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType, TracebackType
from typing import TYPE_CHECKING, Final

from engine.core.logsetup import get_logger
from engine.core.minigame_types import (ARGS_MAX, PLUGIN_NAME_RE, REQUIRED, CodexChange,
                                        MeterChange, MinigameSig, Outcome, StoryNames)
from engine.core.redact import echo
from engine.runtime import limits
from engine.runtime.commands import (MeterView, MinigameBase, MinigameDone, MinigameUsed,
                                     StartMinigame)
from engine.runtime.errors import StoryError, python_text_allowed, short_value, where
from engine.runtime.rollback import CHAIN_STOPS, ROLLBACK_PAUSES
from engine.runtime.values import (KEY, KIND, TOO_DEEP, Unsaveable, Value, freeze,
                                   freeze_untrusted, kind_words, new_item_budget, plain_copy,
                                   same_value)
from engine.script.messages import format_message
from engine.script.minigame import Minigame
from engine.script.suggest import suggest

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.runtime.state import GameState

ARG_NAME_MAX: Final = 64                    # code points of a saved argument name
SEED_LIMIT: Final = 1 << 64                 # 0 <= seed < 2**64
AMOUNT_MAX: Final = 1_000_000_000           # |amount| of one requested meter change
REASON_MAX: Final = 200                     # a check_args refusal, cleaned and cut (SEC-F23-07)
PYTHON_TEXT_MAX: Final = 120                # Python's text in E275 (echo, 04 §7.6)
UNKNOWN_LIST_ITEMS: Final = 8               # E270's run form lists 8 names, then "and N more"
ITEM_KIND: Final = "item"
TIP_KIND: Final = "tip"

_log = get_logger("plugin")

_ARG_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}", re.ASCII)   # a story variable's name
_WAIT_KEYS: Final = frozenset(("name", "args", "seed"))
_OPS: Final = frozenset(("+=", "-=", "="))
_VERBS: Final = {"give": (ITEM_KIND, "unlock"), "take": (ITEM_KIND, "lock"),
                 "unlock_tip": (TIP_KIND, "unlock")}
_REMOVED: Final = frozenset(("Cc", "Cf", "Zl", "Zp"))
_ZWJ: Final = "‍"
_REPLACEMENT: Final = "�"


# --- The state (04 §3, §9) ----------------------------------------------------------------------

@dataclass(frozen=True, slots=True, eq=False)
class MinigameWait:
    """The minigame a checkpoint waits at: the plugin's name, the arguments (a read-only
    mapping of frozen values, in declaration order), and the seed of the plugin's own
    ``Pcg32``. Equality is by name, seed, and the arguments' names in order and values by
    exact type (F03's rule)."""

    name: str
    args: Mapping[str, Value]
    seed: int

    def __eq__(self, other: object) -> bool:
        if type(other) is not MinigameWait:
            return NotImplemented
        a, b = self.args, other.args
        return (self.name == other.name and self.seed == other.seed
                and list(a) == list(b) and all(same_value(a[k], b[k]) for k in a))

    def __hash__(self) -> int:
        return hash((self.name, self.seed, tuple(self.args)))

    def to_json(self) -> dict[str, object]:
        return {"name": self.name, "args": {k: plain_copy(v) for k, v in self.args.items()},
                "seed": self.seed}


@dataclass(frozen=True, slots=True)
class MinigameState:
    """``GameState.minigame``: ``waiting`` is set only in a checkpoint at a ``Minigame``."""

    waiting: MinigameWait | None = None

    def to_json(self) -> dict[str, object]:
        """``{"waiting": null | {"name", "args", "seed"}}``, fresh plain values (always
        written, 04 §3)."""
        return {"waiting": None if self.waiting is None else self.waiting.to_json()}

    @staticmethod
    def from_json(obj: object, budget: list[int] | None = None) -> "MinigameState":
        """Validate an untrusted saved ``minigame`` value (SEC-F23-05(a)). ``budget`` is the
        state's member budget (shared with the variables); a fresh one when None. Raises
        ``StateInvalid("minigame")`` only, never echoing the input. Positions, the plugin, and
        its ``check_args`` are matched only at restore (``minigame_position_ok``)."""
        try:
            return _state_from_json(obj, new_item_budget() if budget is None else budget)
        except Exception:                   # _Invalid, Unsaveable, or anything defensive
            pass
        from engine.runtime.state import StateInvalid   # state.py imports this module
        raise StateInvalid("minigame") from None

    def save_problem(self) -> str | None:
        """F11 C11 for this field's shape: ``minigame`` if ``from_json`` would refuse it
        (only a hand-built state: the executor keeps every limit). The argument values join
        the variables' walk in ``GameState.save_problem`` (members, nesting, surrogates)."""
        waiting = self.waiting
        if waiting is None:
            return None
        try:
            _wait_shape(waiting.name, waiting.args, waiting.seed)
        except Exception:
            return "minigame"
        return None

    def values(self) -> list[object]:
        """The argument values, for ``GameState.save_problem``'s member count (04 §3)."""
        return [] if self.waiting is None else list(self.waiting.args.values())


EMPTY_MINIGAME: Final = MinigameState()


class _Invalid(Exception):
    pass


def _wait_shape(name: object, args: object, seed: object) -> None:
    """The name, the argument names, and the seed of a saved wait; raises ``_Invalid``."""
    if type(name) is not str or PLUGIN_NAME_RE.fullmatch(name) is None:
        raise _Invalid
    if not isinstance(args, Mapping) or len(args) > ARGS_MAX:
        raise _Invalid
    for key in args:
        if (type(key) is not str or _ARG_NAME.fullmatch(key) is None
                or keyword.iskeyword(key)):
            raise _Invalid
    if type(seed) is not int or not 0 <= seed < SEED_LIMIT:
        raise _Invalid


def _state_from_json(obj: object, budget: list[int]) -> MinigameState:
    if type(obj) is not dict or obj.keys() != {"waiting"}:
        raise _Invalid
    raw = obj["waiting"]
    if raw is None:
        return EMPTY_MINIGAME
    if type(raw) is not dict or raw.keys() != _WAIT_KEYS:
        raise _Invalid
    name, args, seed = raw["name"], raw["args"], raw["seed"]
    if type(args) is not dict:
        raise _Invalid
    _wait_shape(name, args, seed)
    values = {key: freeze_untrusted(value, budget) for key, value in args.items()}
    return MinigameState(MinigameWait(name, MappingProxyType(values), seed))


def thaw(args: Mapping[str, Value]) -> dict:
    """A plain, unshared copy of frozen arguments: what plugin code gets (PR-F23-03)."""
    return {k: plain_copy(v) for k, v in args.items()}


# --- The story's names (F24 A2, F25 A5) ----------------------------------------------------------

def story_names(interp: "Interpreter") -> StoryNames:
    """The declared meters, items, and tips, each in declaration order, and the item
    categories (F21's first-declaration order, items in declaration order, key the author's
    text or ``"codex_items"``). Built once per interpreter (F24 ``07`` I-3)."""
    names = interp._story_names
    if names is None:
        index = interp.codex.index
        categories = []
        for category in index.categories:
            if category.kind != ITEM_KIND:
                continue
            key = category.text if category.text is not None else category.word
            categories.append((key, tuple(e.name for e in index.items
                                          if e.category is category)))
        names = interp._story_names = StoryNames(
            meters=tuple(interp.points.names()), items=tuple(e.name for e in index.items),
            tips=tuple(e.name for e in index.tips), item_categories=tuple(categories))
    return names


def start_command(interp: "Interpreter", m: Minigame, wait: MinigameWait, *, run: int,
                  restored: bool) -> StartMinigame:
    """``StartMinigame`` for ``wait`` at ``m``: ``MinigameBase`` from the story's meters
    (declared, in order), held items, and unlocked tips as they are now."""
    points = interp.points
    meters = tuple(MeterView(name, points.get(name), points.spec(name).low,
                             points.spec(name).high) for name in points.names())
    base = MinigameBase(meters, interp.codex.items(), interp.codex.tips())
    return StartMinigame(m.sid, run, wait.name, wait.args, wait.seed, base, m.skippable,
                         restored, story_names(interp))


# --- Plugin code (one guard entry each; SEC-F23-06, -07) ----------------------------------------

def clean_text(text: str, limit: int) -> str:
    """SEC-F23-07 (F11's save-text rule): lone surrogates become U+FFFD; ``Cc``, ``Cf``
    (except ZWJ), ``Zl``, and ``Zp`` are removed; cut to ``limit`` code points."""
    kept: list[str] = []
    for char in text:
        if len(kept) >= limit:
            break
        category = unicodedata.category(char)
        if category == "Cs":
            kept.append(_REPLACEMENT)
        elif category in _REMOVED and char != _ZWJ:
            continue
        else:
            kept.append(char)
    return "".join(kept)


def _plugin_file(sig: MinigameSig | None) -> str | None:
    """The plugin's game-relative source for messages; None for a bundled one ("engine")."""
    if sig is None or sig.source == "engine":
        return None
    return sig.source


def _plugin_line(tb: TracebackType | None) -> tuple[str | None, int | None]:
    """The deepest frame whose file is a plugin's (``<minigames/…>``, ADR-0009)."""
    found: tuple[str | None, int | None] = (None, None)
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename
        if filename.startswith("<minigames/") and filename.endswith(">"):
            found = (filename[1:-1], tb.tb_lineno)
        tb = tb.tb_next
    return found


def plugin_file(sig: MinigameSig | None) -> str | None:
    """The plugin's game-relative source for messages; None for a bundled one (s4's host)."""
    return _plugin_file(sig)


def plugin_line(tb: TracebackType | None) -> tuple[str | None, int | None]:
    """The deepest ``<minigames/…>`` frame's file and line (s4's host)."""
    return _plugin_line(tb)


def plugin_failure(game: str, sig: MinigameSig | None, e: BaseException) -> str:
    """E275's ``raised`` text for ``e`` from plugin code. Call it **inside** the guard entry
    (04 §7.6): ``str(e)`` is plugin code too. The file and line are the deepest plugin
    frame's (else the plugin's source); Python's text only when SR-F03-32 lets it through,
    through ``echo()``. A bundled minigame names no file."""
    file = _plugin_file(sig)
    line = None
    if file is not None:
        found, found_line = _plugin_line(e.__traceback__)
        if found is not None:
            file, line = found, found_line
    text = None
    try:
        raw = str(e)
        if type(raw) is str and raw and python_text_allowed(raw):
            text = echo(raw, PYTHON_TEXT_MAX)
    except KeyboardInterrupt:               # the watchdog (or Ctrl+C): the caller decides
        raise
    except BaseException:                   # noqa: BLE001 (a broken __str__: no text)
        text = None
    return format_message("E275", ("raised", game, file, line, text))


@dataclass(frozen=True, slots=True)
class Verdict:
    """``run_check``'s answer: ``ok``; else ``refusal`` (the plugin's cleaned reason) or
    ``error`` (E275's text: a value that isn't text or None, an exception, the watchdog)."""

    ok: bool
    refusal: str | None = None
    error: str | None = None


_OK: Final = Verdict(True)


def _guarded(interp: "Interpreter", game: str, sig: MinigameSig, what: str,
             call: Callable[[], object], convert: Callable[[object], Verdict]) -> Verdict:
    """One guard entry around ``call`` and ``convert`` (every conversion and every failure
    text is built before ``guard.exit()``, SEC-F23-06). The watchdog gives E275's ``stuck``
    form; a real Ctrl+C (the guard didn't fire) propagates."""
    guard = interp.guard
    interp.author_calls += 1                # F12 I-1: every guard entry (07 I-6)
    interrupted = False
    guard.enter()
    try:
        try:
            verdict = convert(call())
        except KeyboardInterrupt:
            interrupted = True
            verdict = _OK
        except BaseException as e:          # noqa: BLE001 (SystemExit included: E275)
            try:
                verdict = Verdict(False, error=plugin_failure(game, sig, e))
            except KeyboardInterrupt:
                interrupted = True
                verdict = _OK
    finally:
        guard.exit()
    if interrupted:
        if not guard.consume_fired():
            raise KeyboardInterrupt
        return Verdict(False, error=format_message("E275", (
            "stuck", game, what, limits.AUTHOR_CODE_LIMIT_S, _plugin_file(sig))))
    return verdict


def run_check(interp: "Interpreter", sig: MinigameSig, args: Mapping[str, Value]) -> Verdict:
    """04 §5.4: the plugin's ``check_args`` (and, API 1.1, ``check_story``) on a plain copy
    of ``args``, in one guard entry. None is OK; an exact ``str`` is a refusal, cleaned and
    cut to 200 code points inside the guard; anything else, an exception, or the watchdog is
    an error (E275)."""
    check = sig.check
    if check is None:
        return _OK

    def convert(value: object) -> Verdict:
        if value is None:
            return _OK
        if type(value) is str:
            return Verdict(False, refusal=clean_text(value, REASON_MAX))
        return Verdict(False, error=format_message("E275", (
            "value", sig.name, "check_args", kind_words(value), _plugin_file(sig))))

    names = story_names(interp)
    return _guarded(interp, sig.name, sig, "check_args",
                    lambda: check(thaw(args), names), convert)


def headless_outcome(interp: "Interpreter", m: Minigame) -> Outcome | None:
    """Headless with no ``finish`` input (04 §5.4, F24 A2): ``outcome_for("test", …)`` in
    one guard entry when the plugin has it (a raise, the watchdog, or a value it refuses is
    E275 at ``m``), its non-None outcome; else the static test outcome (None: E279 is the
    caller's)."""
    sig = interp.minigames.get(m.name)
    wait = interp.minigame_wait
    if sig is None or wait is None:
        return None
    hook = sig.outcome
    if hook is not None:
        found: list[Outcome | None] = [None]

        def convert(value: object) -> Verdict:
            if value is None:
                return _OK
            kind = kind_words(value)
            if type(value) is Outcome and type(value.changes) is tuple and all(
                    type(c) in (MeterChange, CodexChange) for c in value.changes):
                try:
                    found[0] = Outcome(freeze(value.result), value.changes)
                    return _OK
                except Unsaveable as e:
                    kind = "an outcome whose result can't be saved (" + (
                        kind_words(e.value) if e.reason == KIND else e.reason) + ")"
            return Verdict(False, error=format_message("E275", (
                "value", sig.name, "outcome_for", kind, _plugin_file(sig))))

        names = story_names(interp)
        verdict = _guarded(interp, sig.name, sig, "outcome_for",
                           lambda: hook("test", thaw(wait.args), names), convert)
        if not verdict.ok:
            raise StoryError(verdict.error or "", code="E275", **where(m))
        if found[0] is not None:
            return found[0]
    return sig.test


# --- Reaching a minigame (04 §5.4) -----------------------------------------------------------

def _unknown(interp: "Interpreter", m: Minigame) -> StoryError:
    """E270 at ``m``: no plugin registers the name (the load's checks were skipped)."""
    sigs = interp.minigames
    listed = sorted(sigs)
    args = ("unknown", m.name, suggest(m.name, listed), tuple(listed[:UNKNOWN_LIST_ITEMS]),
            max(0, len(listed) - UNKNOWN_LIST_ITEMS))
    return StoryError(format_message("E270", args), code="E270", **where(m))


def run_minigame(interp: "Interpreter", m: Minigame) -> "Step":
    """Steps 1–7 of 04 §5.4: the signature (E270), each written argument in written order
    (the E85 family with "the argument <name>", then E272 for a value that can't be saved),
    the arguments in declaration order (defaults filled), the plugin's check (E272's plugin
    form, E275), the seed (two outputs, no author code), then the checkpoint."""
    from engine.runtime.interpreter import Step         # below the interpreter
    sig = interp.minigames.get(m.name)
    if sig is None:                                     # 1.
        raise _unknown(interp, m)
    declared = {spec.name: spec for spec in sig.args}
    written: dict[str, Value] = {}
    for arg in m.args:                                  # 2.
        if arg.name not in declared:                    # (the load's checks were skipped)
            names = tuple(declared)
            raise StoryError(format_message("E271", (
                "unknown", m.name, arg.name, suggest(arg.name, names), names,
                f"{arg.name}={arg.value.source}")), code="E271", **where(m))
        interp.running.set(m.file.ref, arg.value)
        value = interp._eval(arg.value.code)
        try:
            written[arg.name] = freeze(value)
        except Unsaveable as e:
            raise _e272_value(arg.name, e, m) from None
    args: dict[str, Value] = {}
    missing = []
    for spec in sig.args:                               # 3.
        if spec.name in written:
            args[spec.name] = written[spec.name]
        elif spec.default is REQUIRED:
            missing.append(spec.name)
        else:
            args[spec.name] = plain_copy(spec.default)  # type: ignore[arg-type]
    if missing:
        raise StoryError(format_message("E271", ("missing", m.name, tuple(missing))),
                         code="E271", **where(m))
    frozen_args = MappingProxyType(args)
    verdict = run_check(interp, sig, frozen_args)       # 4.
    if verdict.error is not None:
        raise StoryError(verdict.error, code="E275", **where(m))
    if verdict.refusal is not None:
        if len(m.args) == 1:
            arg = m.args[0]
            text = format_message("E272", ("plugin", m.name, arg.name, arg.value.source,
                                           verdict.refusal))
        else:
            text = format_message("E272", ("plugin_all", m.name, verdict.refusal))
        raise StoryError(text, code="E272", **where(m))
    core = interp.core
    seed = core.next32() << 32 | core.next32()          # 5. (no author code)
    wait = MinigameWait(m.name, frozen_args, seed)
    interp.minigame_wait = wait                         # 6.
    interp.minigame_run += 1
    interp.minigame_accepted = interp.minigame_used = False
    interp.kept_line = None
    cmd = start_command(interp, m, wait, run=interp.minigame_run, restored=False)
    interp.take_checkpoint(m, cmd)                      # 7. (_snapshot adds the wait)
    return Step.WAIT


def _e272_value(name: str, e: Unsaveable, m: Minigame) -> StoryError:
    """E272's value form: E85e's text with "the argument <name>" as the subject (F03's
    ``unsaveable_message`` reading of the reason, path, kind, and key)."""
    path = e.path_text(name) if e.reason != TOO_DEEP and e.path else None
    detail = ""
    if e.reason == KEY and (e.value is None or type(e.value) in (bool, int, float)):
        detail = short_value(e.value)
    kind = kind_words(e.value) if e.reason == KIND else ""
    return StoryError(format_message("E272", ("value", name, e.reason, path, kind, detail)),
                      code="E272", **where(m))


# --- Restore (04 §5.4 "Restore"; 07 I-6, I-7) ----------------------------------------------

def _effective(interp: "Interpreter", m: Minigame, state: "GameState") -> MinigameWait | None:
    """The wait a restore at ``m`` would commit, or None: the saved name is ``m``'s and
    registered, every saved name is declared, every required one is saved; the arguments
    are the saved values plus each missing optional name's **current** default, in
    declaration order; then the plugin's check (a refusal or an error: None)."""
    waiting = getattr(getattr(state, "minigame", None), "waiting", None)
    if type(waiting) is not MinigameWait or waiting.name != m.name:
        return None
    sig = interp.minigames.get(m.name)
    if sig is None:
        return None
    saved = waiting.args
    declared = {spec.name for spec in sig.args}
    if not declared.issuperset(saved):
        return None
    args: dict[str, Value] = {}
    for spec in sig.args:
        if spec.name in saved:
            args[spec.name] = saved[spec.name]
        elif spec.default is REQUIRED:
            return None
        else:
            args[spec.name] = plain_copy(spec.default)  # type: ignore[arg-type]
    frozen_args = MappingProxyType(args)
    if not run_check(interp, sig, frozen_args).ok:
        return None
    return MinigameWait(m.name, frozen_args, waiting.seed)


def minigame_position_ok(interp: "Interpreter", m: Minigame, state: "GameState") -> bool:
    """Restore step 2 for a ``Minigame`` (also ``check_only``): ``_effective`` found a wait.
    Changes no story state; the plugin's ``check_args`` (side-effect free by the guide) runs
    in one guard entry, at most once per restore attempt of one state object (07 I-6)."""
    cached = interp._minigame_checked
    if cached is not None and cached[0] is state and cached[1] is m:
        return cached[2] is not None
    wait = _effective(interp, m, state)
    interp._minigame_checked = (state, m, wait)
    return wait is not None


def restored_state(interp: "Interpreter", pos: object, state: "GameState") -> MinigameState:
    """Restore step 4's ``minigame`` field: the effective wait at a ``Minigame`` position
    (from step 2's verdict), else ``EMPTY_MINIGAME`` (a ``waiting`` elsewhere is never
    presented, 07 §2.2(b))."""
    if type(pos) is not Minigame:
        return EMPTY_MINIGAME
    cached = interp._minigame_checked
    if cached is not None and cached[0] is state and cached[1] is pos and cached[2] is not None:
        return MinigameState(cached[2])
    wait = _effective(interp, pos, state)
    return EMPTY_MINIGAME if wait is None else MinigameState(wait)


def snapshot_state(interp: "Interpreter", stmt: object) -> MinigameState:
    """``_snapshot``'s live ``minigame`` field: the wait at a ``Minigame``, else empty."""
    wait = interp.minigame_wait
    if wait is None or type(stmt) is not Minigame:
        return EMPTY_MINIGAME
    return MinigameState(wait)


def present_minigame(interp: "Interpreter", m: Minigame, state: "GameState") -> StartMinigame:
    """Restore step 7 / F14's landing: ``StartMinigame(restored=True)`` with the effective
    wait (a restore) or the snapshot's (a landing), evaluating nothing. Changes no
    interpreter field: the command carries ``minigame_run + 1``, which the reset helper
    commits (07 I-7(a))."""
    cached = interp._minigame_checked
    if cached is not None and cached[0] is state and cached[1] is m and cached[2] is not None:
        wait = cached[2]
    else:
        wait = state.minigame.waiting
    assert wait is not None, "a minigame position without a wait"
    return start_command(interp, m, wait, run=interp.minigame_run + 1, restored=True)


# --- The result (04 §5.4) -----------------------------------------------------------------------

def _matches(interp: "Interpreter", ev: MinigameDone | MinigameUsed) -> Minigame | None:
    """The waiting minigame ``ev`` is for, or None (stale, early, another sid, accepted)."""
    from engine.runtime.interpreter import Status       # below the interpreter
    current = interp.current
    if (interp.status is not Status.WAITING or interp.waiting_for is not None
            or type(current) is not Minigame or interp.minigame_accepted
            or type(ev.sid) is not str or ev.sid != current.sid
            or type(ev.run) is not int or ev.run != interp.minigame_run):
        return None
    return current


def on_minigame_done(interp: "Interpreter", ev: MinigameDone) -> None:
    """Accept ``ev`` once (TR-F23-04): the apply step runs as ``run()``'s next step
    (``defer``, under its error mapping), never here."""
    from engine.runtime.interpreter import Status       # below the interpreter
    m = _matches(interp, ev)
    if m is None:
        _log.debug("MinigameDone ignored: no minigame waits for it (a stale or repeated "
                   "result).")
        return
    interp.minigame_accepted = True
    interp.defer(lambda i: apply(i, m, ev))
    interp.status = Status.RUNNING


def on_minigame_used(interp: "Interpreter", ev: MinigameUsed) -> None:
    """The player used an input in the waiting minigame (04 §7.5): back is refused there."""
    if _matches(interp, ev) is None:
        _log.debug("MinigameUsed ignored: no minigame waits for it.")
        return
    interp.minigame_used = True


def minigame_used(interp: "Interpreter") -> bool:
    """F14's pause (07 I-13, A2): a used input at the minigame the story waits at (or has
    just accepted)."""
    from engine.runtime.interpreter import Status       # below the interpreter
    return (interp.minigame_used and type(interp.current) is Minigame
            and interp.status in (Status.WAITING, Status.RUNNING))


def _change_error(m: Minigame, file: str | None, problem: str, meter: str = "",
                  shown: str = "") -> StoryError:
    return StoryError(format_message("E276", ("change", m.name, problem, meter, shown, file)),
                      code="E276", **where(m))


def _checked_changes(interp: "Interpreter", m: Minigame, changes: object,
                     file: str | None) -> list[MeterChange | CodexChange]:
    """Every change's shape and name, before any applies (04 §5.4 step 2): E276's change
    form; F22's E236 and F21's E253 texts for a name the story doesn't declare."""
    if type(changes) is not tuple:
        raise _change_error(m, file, "kind")
    points, index = interp.points, interp.codex.index
    out: list[MeterChange | CodexChange] = []
    for change in changes:
        if type(change) is MeterChange:
            name, amount = change.name, change.amount
            if type(name) is not str:
                raise _change_error(m, file, "name")
            if type(change.op) is not str or change.op not in _OPS:
                raise _change_error(m, file, "kind")
            if type(amount) is not int or abs(amount) > AMOUNT_MAX:
                raise _change_error(m, file, "amount", name, repr(amount)[:40])
            if name not in points.names():
                text = format_message("E236", ("unknown", name, suggest(name, points.names())))
                raise StoryError(text, code="E236", **where(m))
        elif type(change) is CodexChange:
            name, verb = change.name, change.verb
            if type(name) is not str:
                raise _change_error(m, file, "name")
            if type(verb) is not str or verb not in _VERBS:
                raise _change_error(m, file, "kind")
            kind, word = _VERBS[verb]
            entry = index.get(name)
            if entry is None:
                text = format_message("E253", ("unknown", kind, name, index.suggest(name, kind)))
                raise StoryError(text, code="E253", **where(m))
            if entry.kind != kind:
                text = format_message("E253", ("kind", name, entry.kind, kind, word))
                raise StoryError(text, code="E253", **where(m))
        else:
            raise _change_error(m, file, "kind")
        out.append(change)
    return out


def e276_result(game: str, e: Unsaveable, target: str | None, file: str | None) -> str:
    """E276's result form for a result ``freeze`` refused (``apply`` and s4's host, which
    checks a plugin's ``finish`` value inside the call)."""
    kind = kind_words(e.value) if e.reason == KIND else ""
    return format_message("E276", ("result", game, e.reason, kind, target, file))


def apply(interp: "Interpreter", m: Minigame, ev: MinigameDone) -> "Step":
    """The accepted outcome (SR-F23-07), as ``run()``'s deferred step: (1) the result frozen
    (E276); (2) the changes checked, then applied in order (``Points``, ``Codex``: tips are
    the store's, ``CodexAdded`` held in change order); (3) ``G[target]``; (4) F14's wall for
    ``rollback fixed``; (5) no wait. Then the successor."""
    from engine.runtime.interpreter import Step         # below the interpreter
    sig = interp.minigames.get(m.name)
    file = _plugin_file(sig)
    try:
        result = freeze(ev.result)                      # 1.
    except Unsaveable as e:
        kind = kind_words(e.value) if e.reason == KIND else ""
        raise StoryError(format_message("E276", ("result", m.name, e.reason, kind, m.target,
                                                 file)), code="E276", **where(m)) from None
    changes = _checked_changes(interp, m, ev.changes, file)
    points, codex = interp.points, interp.codex
    for change in changes:                              # 2.
        if type(change) is MeterChange:
            points.change(change.name, change.op, change.amount)
        elif change.verb == "give":                     # type: ignore[union-attr]
            codex.give(change.name)
        elif change.verb == "take":                     # type: ignore[union-attr]
            codex.take(change.name)
        else:
            codex.unlock_tip(change.name)
    if m.target is not None:                            # 3.
        interp.G[m.target] = result
    if m.fixed:                                         # 4. (F14 A3, D2)
        interp.timeline.block_pending = True
    interp.minigame_wait = None                         # 5.
    return Step.CONTINUE


# --- The ledger (04 §7.3; s4) ------------------------------------------------------------------

CHANGES_MAX: Final = 1_000                  # requests one session may make (04 §4.2)


class RequestError(Exception):
    """A plugin request the ledger refused (04 §7.3 step 1–2): ``code`` (E236, E253, or
    E275) and the final text. The host reports it at the plugin's line (P prefix)."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(text)
        self.code = code
        self.text = text


def e275_request(form: str, game: str, detail: str = "") -> str:
    """E275's request forms (F23 ``06`` G2 drafts, in ``messages.py``): ``many`` (over
    ``CHANGES_MAX`` changes) and ``subclass`` (a name that isn't exactly ``str``)."""
    if form == "many":
        return format_message("E275", ("many", game, CHANGES_MAX))
    return format_message("E275", ("subclass", game, detail))


def e277_text(game: str, seconds: float, file: str | None, line: int | None) -> str:
    """E277 (02 §4.1; the text is in ``messages.py``): the watchdog stopped a plugin call
    while the minigame played. A bundled minigame (``file`` None) names no file."""
    return format_message("E277", (game, seconds, file, line))


def entry_check(index: object) -> Callable[[str, str], None]:
    """F21's own name check over a ``CodexIndex`` (``check_entry`` of the ledger): an
    undeclared name raises ``UnknownEntry`` (with the closest name of ``kind``), a name of
    the other kind ``WrongKind``."""
    from engine.runtime.codex import UnknownEntry, WrongKind   # codex imports commands

    def check(name: str, kind: str) -> None:
        entry = index.get(name)                                # type: ignore[attr-defined]
        if entry is None:
            raise UnknownEntry(name, kind, index.suggest(name, kind))   # type: ignore[attr-defined]
        if entry.kind != kind:
            raise WrongKind(entry.name, entry.kind, kind)
    return check


class MinigameLedger:
    """One session's requested changes and the preview the plugin reads (04 §7.3, PR-F23-15
    to 17). Pure: built from ``StartMinigame.base``; ``check_meter(name)`` is F22's check
    (raises ``UnknownMeter``), ``check_entry(name, kind)`` F21's (``UnknownEntry``,
    ``WrongKind``). A request converts its arguments (exact ``str`` names, exact ``int``
    amounts within ±10⁹), checks the name, appends to ``changes`` (at most 1,000), then
    updates the preview: meters clamp like ``Points.change``, ``give`` appends, ``take``
    removes, ``unlock_tip`` adds. The runtime re-applies ``changes`` through the real
    ``Points``/``Codex`` at acceptance; nothing here touches the story."""

    def __init__(self, base: MinigameBase, *, check_meter: Callable[[str], object],
                 check_entry: Callable[[str, str], object], game: str = "") -> None:
        self._specs = {m.name: (m.low, m.high) for m in base.meters}
        self._names = tuple(m.name for m in base.meters)
        self._values = {m.name: m.value for m in base.meters}
        self._items = list(base.items)
        self._tips = list(base.tips)
        self._check_meter = check_meter
        self._check_entry = check_entry
        self._game = game
        self._changes: list[MeterChange | CodexChange] = []

    @property
    def changes(self) -> tuple[MeterChange | CodexChange, ...]:
        return tuple(self._changes)

    # Reads (the preview) ------------------------------------------------------------------

    def meters(self) -> tuple[str, ...]:
        return self._names

    def meter(self, name: object) -> int:
        self._meter_name(name)
        return self._values[name]                                    # type: ignore[index]

    def highest(self) -> str:
        """The highest meter (ties: the first declared), as ``Points.highest()``."""
        if not self._names:
            raise RequestError("E236", format_message("E236", ("none",)))
        best = self._names[0]
        for name in self._names[1:]:
            if self._values[name] > self._values[best]:
                best = name
        return best

    def items(self) -> tuple[str, ...]:
        return tuple(self._items)

    def tips(self) -> tuple[str, ...]:
        return tuple(self._tips)

    def has(self, kind: object, name: object = None) -> bool:
        """``has(name)``: a held item or unlocked tip; ``has(kind, name)``: of that kind."""
        if name is None:
            return kind in self._items or kind in self._tips
        if kind == ITEM_KIND:
            return name in self._items
        if kind == TIP_KIND:
            return name in self._tips
        return False

    # Requests -----------------------------------------------------------------------------

    def add(self, name: object, n: object) -> int:
        return self._meter_request(name, "+=", n)

    def set(self, name: object, n: object) -> int:
        return self._meter_request(name, "=", n)

    def give(self, name: object) -> None:
        self._codex_request("give", name)
        if name not in self._items:
            self._items.append(name)                                 # type: ignore[arg-type]

    def take(self, name: object) -> None:
        self._codex_request("take", name)
        if name in self._items:
            self._items.remove(name)                                 # type: ignore[arg-type]

    def unlock_tip(self, name: object) -> None:
        self._codex_request("unlock_tip", name)
        if name not in self._tips:
            self._tips.append(name)                                  # type: ignore[arg-type]

    # Internals ------------------------------------------------------------------------------

    def _text_name(self, name: object) -> str:
        if type(name) is not str:
            raise RequestError("E275", e275_request("subclass", self._game,
                                                    _kind_name(name)))
        return name

    def _meter_name(self, name: object) -> str:
        name = self._text_name(name)
        from engine.runtime.points import UnknownMeter              # below the interpreter
        try:
            self._check_meter(name)
        except UnknownMeter as e:
            raise RequestError("E236", str(e)) from None
        if name not in self._specs:                                  # declared after start?
            raise RequestError("E236", format_message("E236", ("unknown", name,
                                                               suggest(name, self._names))))
        return name

    def _append(self, change: MeterChange | CodexChange) -> None:
        if len(self._changes) >= CHANGES_MAX:
            raise RequestError("E275", e275_request("many", self._game))
        self._changes.append(change)

    def _meter_request(self, name: object, op: str, n: object) -> int:
        text = self._text_name(name)
        if type(n) is not int or abs(n) > AMOUNT_MAX:
            shown = short_value(n) if type(n) in (bool, int, float) else kind_words(n)
            raise RequestError("E236", format_message("E236", (
                "amount", text, shown, kind_words(n))))
        self._meter_name(text)
        self._append(MeterChange(text, op, n))                       # type: ignore[arg-type]
        low, high = self._specs[text]
        old = self._values[text]
        wanted = old + n if op == "+=" else old - n if op == "-=" else n
        value = low if wanted < low else high if wanted > high else wanted
        self._values[text] = value
        return value

    def _codex_request(self, verb: str, name: object) -> None:
        text = self._text_name(name)
        kind, word = _VERBS[verb]
        from engine.runtime.codex import UnknownEntry, WrongKind    # below the interpreter
        try:
            self._check_entry(text, kind)
        except UnknownEntry as e:
            raise RequestError("E253", format_message("E253", (
                "unknown", kind, text, e.suggestion))) from None
        except WrongKind as e:
            raise RequestError("E253", format_message("E253", (
                "kind", text, e.kind, kind, word))) from None
        self._append(CodexChange(verb, text))                        # type: ignore[arg-type]


def codex_error_text(e: Exception) -> str:
    """F21's E253 text for an ``UnknownEntry`` or ``WrongKind`` a plugin call raised (A9's
    ``title``: E275 with E253's text)."""
    from engine.runtime.codex import WrongKind                  # below the interpreter
    if isinstance(e, WrongKind):
        return format_message("E253", ("kind", e.name, e.kind, e.wanted, "unlock"))
    return format_message("E253", ("unknown", getattr(e, "kind", ITEM_KIND),
                                   getattr(e, "name", ""), getattr(e, "suggestion", None)))


def _kind_name(value: object) -> str:
    """A refused name's kind for E275's subclass form: the class name for a ``str``
    subclass (no plugin method runs), else F03's kind words."""
    if isinstance(value, str):
        return f"a {type(value).__name__}, which is a kind of text"
    return kind_words(value)


# --- F14 (A1, A2: registered once, at import) ----------------------------------------------------

ROLLBACK_PAUSES.append(minigame_used)
CHAIN_STOPS.add(Minigame)


__all__ = ["AMOUNT_MAX", "ARG_NAME_MAX", "CHANGES_MAX", "EMPTY_MINIGAME", "MinigameLedger",
           "MinigameState", "MinigameWait", "REASON_MAX", "RequestError", "SEED_LIMIT",
           "Verdict", "apply", "clean_text", "codex_error_text", "e275_request", "e276_result",
           "e277_text", "entry_check", "headless_outcome", "minigame_position_ok",
           "minigame_used", "on_minigame_done", "on_minigame_used", "plugin_failure",
           "plugin_file", "plugin_line", "present_minigame", "restored_state", "run_check",
           "run_minigame", "snapshot_state", "start_command", "story_names", "thaw"]

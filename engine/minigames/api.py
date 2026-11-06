"""The public minigame plugin API, version 1.5 (F23 ``04`` §4.3; ADR-0009).

Why this module exists: a plugin in ``game/minigames/`` subclasses ``Minigame``, declares
its name, arguments, and outcomes as class attributes, and calls ``register(cls)``. Plugins
are trusted code (invariant 9 (d)), but what crosses into the engine is checked:
``register`` runs inside the loader's guard and **copies** every declaration as exact
built-ins (``freeze`` for defaults and outcomes), so no plugin ``__str__``, ``__hash__``,
property, or subclass runs later outside the guard, and changing the class after
``register`` changes nothing (SEC-F23-06).

A plugin's story effects are ``Outcome(result, changes)``: the result goes into the
``into`` variable and the changes are made with ``add_points``, ``set_points``, ``give``,
``take``, and ``unlock_tip``.

API 1.1 (F24 A1; F23 I-19) adds two optional hooks, used only when a plugin declares
``api = "1.1"`` or later: ``check_story(args, story)`` (refuse arguments that don't fit the
story's declared names) and ``outcome_for(kind, args, story)`` (a test or skipped outcome
that depends on the arguments). ``story`` is ``StoryNames``; ``closest`` is the engine's
did-you-mean rule for a reason text.

API 1.2 (F37 §5.3) adds ``register_achievement_hook(hook)``: a game's one achievement
platform hook (``achievement_hook.py``), an object with ``unlocked(name)`` and, optionally,
``started(unlocked)``. A plugin file that only registers a hook loads (no W161).

API 1.3 (F50) adds ``ctx.settings.timing_assist`` and ``ctx.settings.timed(seconds)``.

API 1.4 (F52) adds ``TextField``: a one-line text widget for ``ctx.scope`` (typing, IME,
paste, limits, a dot mask, letter cells and a bare prompt line, and the engine's on-screen
keyboard for gamepads). Under API 1.4 or later the engine owns SDL text input: it is on only
while a ``TextField`` is focused, and the plugin never sees raw ``TEXTINPUT`` (the host's
router gives text and editing keys to the focused field before ``handle_event``). A plugin
below 1.4 keeps text input on while it is on top, as before (F52 07 I-9).

API 1.5 (F64 round 2) adds item counts, the one narrow way a minigame reads and changes how
many of an item the player holds: ``ctx.codex.count(name)`` (the preview's count, 0 when
none), ``ctx.codex.most(name)`` (the most a player can hold; 1 for an item declared without
``count``), ``ctx.codex.give(name, n)`` / ``ctx.codex.take(name, n)`` and the outcome helpers
``give(name, n)`` / ``take(name, n)``, with ``n`` an exact ``int`` from 1 to 999,999 (default
1, so every older call is unchanged), and ``ctx.codex.money_word()`` (the bag's money word:
``[codex] money_word``, else the genre kit's, else the money item's title; "" with no money
item). ``ctx.story.money`` names the item marked ``money`` and ``ctx.story.prices`` lists each
item's ``price``. The same rules as every other change (SR-F23): exact ``str`` names that the
story declares as items (E253), an exact ``int`` amount in range (else E275 with E436's text),
at most 1,000 requests a session, and nothing reaches the story until the minigame finishes:
the runtime re-applies the changes through ``unlock item``/``lock item``'s own rules (up to
the item's most, never below 0), so a save, a load, rollback and Skip Game stay exact.
"""

import keyword
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar

from engine.core.minigame_types import (
    API_VERSION,
    ARGS_MAX,
    PLUGIN_NAME_RE,
    REQUIRED,
    ArgSpec,
    Change,
    CodexChange,
    MeterChange,
    MinigameSig,
    Outcome,
    StoryNames,
)
from engine.minigames import messages
from engine.minigames.achievement_hook import AchievementHook
from engine.minigames.context import Context, MinigameThreadError, PlayerSettings
from engine.minigames.registry import DeclarationError, PluginClass, Registry
from engine.runtime.errors import suggest
from engine.runtime.values import BIG_INT, INF, KEY, KIND, NAN, Unsaveable, freeze, kind_words
from engine.ui.builtin.codex_page import CodexFilter, PickAction   # F25 A6: codex_view's types
from engine.ui.notice import clean_text
from engine.ui.textfield import TextField                         # API 1.4 (F52)

if TYPE_CHECKING:
    from engine.ui.input import UiEvent
    from engine.ui.nav import Nav

TITLE_MAX = 200                      # SEC-F23-07: heading and title, code points
AMOUNT_MAX = 1_000_000_000           # SEC-F23-06: |amount| of a meter change
COUNT_MAX = 999_999                  # API 1.5: n of one give or take (ITEM_COUNT_MAX)
# Story variable names (no leading "_"): the saved form (``runtime/minigame.py``,
# SEC-F23-05(a)) refuses any other, so a declared one could never be restored (F23 s2).
_ARG_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}", re.ASCII)
_API_RE = re.compile(r"(\d{1,4})(?:\.(\d{1,4}))?", re.ASCII)
_METER_OPS = ("+=", "-=", "=")
_CODEX_VERBS = ("give", "take", "unlock_tip")

TokenDecl = str | int | float | bool            # a token's default; checked at install (§7.9)


class Arg:
    """An argument declaration: ``Arg()`` is required, ``Arg(default=v)`` optional."""

    __slots__ = ("default",)

    def __init__(self, default: object = REQUIRED) -> None:
        self.default = default

    def __repr__(self) -> str:
        return "Arg()" if self.default is REQUIRED else f"Arg(default={self.default!r})"


@dataclass(frozen=True, slots=True)
class PluginEvent:
    """One input for ``handle_event``: F10's event and its navigation meaning (``nav``
    from a ``NavReader`` with Esc removed and Backspace as Back), or None."""
    ui: "UiEvent"
    nav: "Nav | None"


class Minigame:
    """Base class of every minigame. Subclass it, set ``name``, and call ``register``."""

    name: ClassVar[str]                              # PLUGIN_NAME_RE; no default
    title: ClassVar[str] = ""                        # "" → name; [words.plugin.<name>] wins
    api: ClassVar[str] = "1.0"
    args: ClassVar[Mapping[str, Arg]] = {}
    test_outcome: ClassVar[Outcome | None] = None
    skipped_outcome: ClassVar[Outcome | None] = None
    over_stage: ClassVar[bool] = False
    tokens: ClassVar[Mapping[str, TokenDecl]] = {}
    words: ClassVar[Mapping[str, str]] = {}

    def check_args(self, args: dict) -> str | None:
        """Refuse arguments (a save can choose them): return a reason, or None. Runs on a
        fresh instance that is never started, and must have no side effects."""
        return None

    def check_story(self, args: dict, story: StoryNames) -> str | None:
        """API 1.1: refuse arguments that don't fit the story (a meter, item, or tip name
        that isn't declared). Runs only after ``check_args`` returned None, on the same
        fresh instance; no side effects."""
        return None

    def outcome_for(self, kind: str, args: dict, story: StoryNames) -> Outcome | None:
        """API 1.1: the ``"test"`` or ``"skipped"`` outcome for these arguments, or None for
        the declared ``test_outcome``/``skipped_outcome``. Runs on a fresh instance that is
        never started; no side effects."""
        return None

    def start(self, ctx: Context) -> None:
        pass

    def handle_event(self, ev: PluginEvent) -> bool:
        return False

    def update(self, dt: float) -> None:
        pass

    def draw(self, canvas: Any) -> None:
        pass

    def layout(self, area: Any) -> None:
        pass

    def settings_changed(self, s: Any) -> None:
        pass


# --- Changes -------------------------------------------------------------------------------

def add_points(name: str, n: int) -> MeterChange:
    return MeterChange(name, "+=", n)


def set_points(name: str, n: int) -> MeterChange:
    return MeterChange(name, "=", n)


def give(name: str, n: int = 1) -> CodexChange:
    """Give ``n`` of item ``name`` (API 1.5: ``n`` from 1 to 999,999; 1 before)."""
    return CodexChange("give", name, n)


def take(name: str, n: int = 1) -> CodexChange:
    """Take ``n`` of item ``name`` (API 1.5: ``n`` from 1 to 999,999; 1 before)."""
    return CodexChange("take", name, n)


def unlock_tip(name: str) -> CodexChange:
    return CodexChange("unlock_tip", name)


def closest(written: str, names: Iterable[str]) -> str | None:
    """The engine's one did-you-mean suggestion for ``written`` among ``names`` (SR-F02-70:
    a case-insensitive match, else the nearest name within 1 or 2 edits), or None. For a
    reason text such as ``Did you mean "sayori"?``. Names that aren't text are skipped."""
    if type(written) is not str:
        return None
    return suggest(written, [n for n in names if type(n) is str])


# --- register ---------------------------------------------------------------------------------

_registry: Registry | None = None      # set by the loader while units run


def _set_registry(registry: Registry | None) -> None:
    global _registry
    _registry = registry


_MISSING = object()


def _declared(cls: type, name: str) -> object:
    """The class attribute as written (no descriptor runs): the first class in the MRO
    whose namespace has ``name``."""
    for klass in cls.__mro__:
        namespace = vars(klass)
        if name in namespace:
            return namespace[name]
    return _MISSING


def _plugin_place() -> tuple[str | None, int | None]:
    """The innermost plugin frame calling ``register`` (file ``minigames/…``, line)."""
    frame = sys._getframe(2)
    while frame is not None:
        filename = frame.f_code.co_filename
        if filename.startswith("<minigames/") and filename.endswith(">"):
            return filename[1:-1], frame.f_lineno
        frame = frame.f_back
    return None, None


def _unsaveable(subject: str, exc: Unsaveable) -> str:
    if exc.reason == KIND:
        holds = kind_words(exc.value)
        advice = ("Use a list instead." if holds == "a set" else
                  "A value can be text, a number, True, False, None, a list, or a dictionary "
                  "with text keys.")
    elif exc.reason == KEY:
        holds, advice = "a dictionary with a key that isn't text", "Use text keys."
    elif exc.reason == NAN:
        holds, advice = '"not a number" (nan)', "Check the calculation that set it."
    elif exc.reason == INF:
        holds, advice = "infinity (inf)", "Check the calculation that set it."
    elif exc.reason == BIG_INT:
        holds = "a whole number with more than 4,300 digits"
        advice = "Check the calculation that set it."
    else:
        holds, advice = "values nested more than 100 levels deep", "Nest them less deeply."
    return messages.e273_unsaveable(subject, holds, advice)


def _frozen(value: object, subject: str) -> object:
    try:
        return freeze(value)
    except Unsaveable as exc:
        raise DeclarationError(_unsaveable(subject, exc)) from None
    except RecursionError:
        raise DeclarationError(messages.e273_unsaveable(
            subject, "values nested more than 100 levels deep", "Nest them less deeply.")) \
            from None


def _change(change: object, subject: str) -> Change:
    t = type(change)
    if t is MeterChange:
        name, op, amount = change.name, change.op, change.amount   # type: ignore[union-attr]
        if (type(name) is str and type(op) is str and op in _METER_OPS
                and type(amount) is int and -AMOUNT_MAX <= amount <= AMOUNT_MAX):
            return MeterChange(name, op, amount)                    # type: ignore[arg-type]
    elif t is CodexChange:
        verb, name = change.verb, change.name                       # type: ignore[union-attr]
        n = change.amount                                           # type: ignore[union-attr]
        if (type(verb) is str and verb in _CODEX_VERBS and type(name) is str
                and type(n) is int and 1 <= n <= COUNT_MAX
                and (n == 1 or verb != "unlock_tip")):
            return CodexChange(verb, name, n)                       # type: ignore[arg-type]
    raise DeclarationError(messages.e273_bad_change(subject))


def _outcome(value: object, subject: str, what: str) -> Outcome | None:
    if value is None:
        return None
    if type(value) is not Outcome:
        raise DeclarationError(messages.e273_not_plain(what, "an Outcome or None"))
    result = _frozen(value.result, subject)                         # type: ignore[union-attr]
    changes = value.changes                                         # type: ignore[union-attr]
    if type(changes) is not tuple:
        raise DeclarationError(messages.e273_bad_change(subject))
    return Outcome(result, tuple(_change(c, subject) for c in changes))


def _text(value: object, what: str) -> str:
    if type(value) is not str:
        raise DeclarationError(messages.e273_not_plain(what))
    return value


def _plain_dict(value: object, what: str, values: tuple[type, ...]) -> dict:
    if type(value) is not dict:
        raise DeclarationError(messages.e273_not_plain(what, "a dictionary"))
    out = {}
    for key, item in list(value.items()):
        if type(key) is not str or type(item) not in values:
            raise DeclarationError(messages.e273_not_plain(what, "a dictionary"))
        out[key] = item
    return out


def _api(value: object, unit: str) -> str:
    text = _text(value, "api")
    match = _API_RE.fullmatch(text)
    if match is None:
        raise DeclarationError(messages.e273_bad_api(text))
    major, minor = int(match.group(1)), int(match.group(2) or 0)
    if major != API_VERSION[0]:
        raise DeclarationError(messages.e273_other_major(unit, major), whole=True)
    if minor > API_VERSION[1]:
        raise DeclarationError(messages.e278_newer_minor(unit, f"{major}.{minor}"),
                               code="E278", whole=True)
    return f"{major}.{minor}"


def _args(value: object) -> tuple[ArgSpec, ...]:
    if type(value) is not dict:
        raise DeclarationError(messages.e273_not_plain("args", "a dictionary"))
    items = list(value.items())
    if len(items) > ARGS_MAX:
        raise DeclarationError(messages.e273_too_many_args(len(items), ARGS_MAX))
    specs = []
    for key, arg in items:
        if (type(key) is not str or _ARG_NAME_RE.fullmatch(key) is None
                or keyword.iskeyword(key)):
            raise DeclarationError(messages.e273_bad_arg_name(key))
        if type(arg) is not Arg:
            raise DeclarationError(messages.e273_not_plain(f"the argument {key}",
                                                           "Arg() or Arg(default=…)"))
        default = arg.default
        if default is not REQUIRED:
            default = _frozen(default, f"the default of {key}")
        specs.append(ArgSpec(key, default))
    return tuple(specs)


def _check_with_fresh_instance(cls: type, story_hook: bool, args: dict,
                               story: StoryNames) -> object:
    """``MinigameSig.check``: ``check_args`` on a fresh, never-started instance, created
    inside the caller's guard entry (F23 ``07`` I-10); then, if it returned None and the
    plugin uses API 1.1's hook, ``check_story`` on the same instance (F24 A1)."""
    game = cls()
    reason = game.check_args(args)
    if reason is None and story_hook:
        return game.check_story(args, story)
    return reason


_KIND_SUBJECTS = {"test": ("the test outcome", "outcome_for"),
                  "skipped": ("the skipped outcome", "outcome_for")}


def _outcome_with_fresh_instance(cls: type, kind: str, args: dict,
                                 story: StoryNames) -> Outcome | None:
    """``MinigameSig.outcome``: ``outcome_for`` on a fresh, never-started instance, its value
    copied by the declared-outcome rules (exact built-ins, frozen). A refused value raises
    ``DeclarationError``, which the caller's guard reports as E275 (F24 ``07`` §2.1)."""
    subject, what = _KIND_SUBJECTS[kind]
    return _outcome(cls().outcome_for(kind, args, story), subject, what)


def _overrides(cls: type, hook: str) -> bool:
    return _declared(cls, hook) is not Minigame.__dict__[hook]


def declarations(cls: object, unit: str) -> PluginClass:
    """Copy and check ``cls``'s declarations (§7.10 step 7). Raises DeclarationError."""
    if not (isinstance(cls, type) and issubclass(cls, Minigame)):
        raise DeclarationError(messages.e273_not_a_class(kind_words(cls)))
    name = _declared(cls, "name")
    if name is _MISSING:
        raise DeclarationError(messages.E273_NO_NAME)
    name = _text(name, "name")
    if PLUGIN_NAME_RE.fullmatch(name) is None:
        raise DeclarationError(messages.e273_bad_name(name))
    title = clean_text(_text(_declared(cls, "title"), "title"), TITLE_MAX) or name
    api = _api(_declared(cls, "api"), unit)
    args = _args(_declared(cls, "args"))
    test = _outcome(_declared(cls, "test_outcome"), "the test outcome", "test_outcome")
    skipped = _outcome(_declared(cls, "skipped_outcome"), "the skipped outcome",
                       "skipped_outcome")
    over_stage = _declared(cls, "over_stage")
    if type(over_stage) is not bool:
        raise DeclarationError(messages.e273_not_plain("over_stage", "True or False"))
    tokens = _plain_dict(_declared(cls, "tokens"), "tokens", (str, int, float, bool))
    words = _plain_dict(_declared(cls, "words"), "words", (str,))
    # API 1.1's hooks count only when the plugin declares 1.1 or later, so a 1.0 plugin's
    # own methods with these names are never called (TR-F23-09).
    hooks = int(api.split(".")[1]) >= 1
    story_hook = hooks and _overrides(cls, "check_story")
    check = None
    if _overrides(cls, "check_args") or story_hook:
        check = partial(_check_with_fresh_instance, cls, story_hook)
    outcome = None
    if hooks and _overrides(cls, "outcome_for"):
        outcome = partial(_outcome_with_fresh_instance, cls)
    sig = MinigameSig(name=name, title=title, source=unit, args=args, test=test,
                      skipped=skipped, check=check, outcome=outcome)
    return PluginClass(sig=sig, cls=cls, unit=unit, api=api, over_stage=over_stage,
                       tokens=tokens, words=words)


def register(cls):
    """Register a minigame class (usable as a decorator). Works only while plugins load."""
    registry = _registry
    collector = registry.active() if registry is not None else None
    if collector is None:
        raise RuntimeError("register() works only while minigame plugins load")
    try:
        entry = declarations(cls, collector.unit)
    except DeclarationError as error:
        error.file, error.line = _plugin_place()
        collector.errors.append(error)
        raise
    registry.collect(entry)                                   # type: ignore[union-attr]
    return cls


def _hook_method(hook: object, name: str) -> object:
    """``hook.<name>`` if it is callable, else None (a property that raises counts as
    missing; it runs here, inside the loader's guard)."""
    try:
        method = getattr(hook, name, None)
    except Exception:
        return None
    return method if callable(method) else None


def register_achievement_hook(hook: object) -> object:
    """API 1.2 (F37 §5.3): register the game's achievement platform hook, an object (not a
    class) with an ``unlocked(name)`` method and, optionally, ``started(unlocked)``. Its
    methods are looked up now, once. One per game: a second call is refused (E273). Works
    only while plugins load. Returns ``hook``."""
    registry = _registry
    collector = registry.active() if registry is not None else None
    if collector is None:
        raise RuntimeError("register_achievement_hook() works only while minigame plugins load")
    try:
        unlocked = None if isinstance(hook, type) else _hook_method(hook, "unlocked")
        if unlocked is None:
            raise DeclarationError(messages.E273_HOOK_SHAPE)
        if registry.hook_taken():                             # type: ignore[union-attr]
            raise DeclarationError(messages.E273_HOOK_TWICE)
        started = _hook_method(hook, "started")
    except DeclarationError as error:
        error.file, error.line = _plugin_place()
        collector.errors.append(error)
        raise
    collector.achievement_hook = AchievementHook(collector.unit, unlocked,  # type: ignore
                                                 started)                   # type: ignore
    return hook


__all__ = ["API_VERSION", "Arg", "COUNT_MAX", "CodexChange", "CodexFilter", "Context", "MeterChange",
           "Minigame", "MinigameThreadError", "Outcome", "PickAction", "PlayerSettings",
           "PluginEvent", "StoryNames", "TextField", "TokenDecl", "add_points", "closest",
           "give", "register", "register_achievement_hook", "set_points", "take", "unlock_tip"]

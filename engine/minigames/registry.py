"""The minigame registry and the plugin load errors (F23 ``04`` §7.10 steps 7–9).

Why this module exists: ``register`` (author code, inside the loader's guard) must put each
plugin class somewhere that only the loader controls, so a unit that fails leaves nothing
registered and two units can't silently share a name (E274). The registry is filled once per
launch by ``PluginLoadJob`` and then read: ``signatures()`` gives the runtime and the script
checks plain ``MinigameSig`` values, and the host looks up a ``PluginClass`` by name.

Names in scripts and saves are registry keys only, never file names (SEC-F23-04 (a)).
"""

import keyword
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType

from engine.core.errors import UserFacingError
from engine.core.minigame_types import PLUGIN_NAME_RE, MinigameSig
from engine.minigames import messages
from engine.minigames.achievement_hook import AchievementHook

MAX_REGISTRATIONS = 256
ENGINE_SOURCE = "engine"

# Windows device names (``paths.check_ref``'s set; the ones the ASCII rule can match).
_RESERVED = frozenset({"con", "prn", "aux", "nul"}
                      | {f"com{d}" for d in range(10)} | {f"lpt{d}" for d in range(10)})


def name_problem(name: str) -> str | None:
    """SEC-F23-02 for a unit stem or a name inside a package: None when ``name``
    fullmatches ``PLUGIN_NAME_RE``, isn't a Python keyword, and isn't a Windows device name
    (on every OS); else "bad" (the pattern) or "reserved"."""
    if type(name) is not str or PLUGIN_NAME_RE.fullmatch(name) is None:
        return "bad"
    if keyword.iskeyword(name) or name in _RESERVED:
        return "reserved"
    return None


class PluginLoadError(UserFacingError):
    """One plugin problem found while loading (E273, E274, E278). P forms carry the plugin
    file (game-relative, ``minigames/x.py``) and line; G forms name the file in the message.
    The plugin phase (s3b) shows them in one group, never mixed with script errors.
    ``logged`` is True once the loader has logged the error with its traceback, so the phase
    doesn't log it again."""

    def __init__(self, message: str, *, code: str, file: str | None = None,
                 line: int | None = None) -> None:
        super().__init__(message, file=file, line=line)
        self.code = code
        self.logged = False


class DeclarationError(Exception):
    """Raised by ``register`` when a class declaration can't be copied (E273 declaration
    forms, E278). ``whole`` messages name the file themselves (no line prefix)."""

    def __init__(self, message: str, *, code: str = "E273", whole: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.whole = whole
        self.file: str | None = None
        self.line: int | None = None


class RegistrationBound(Exception):
    """More than ``MAX_REGISTRATIONS`` registrations: E273 G, nothing more loads."""


@dataclass(frozen=True)
class PluginClass:
    """A registered minigame: its signature and the copied declarations. ``cls`` is the
    author's class; the host instantiates it (inside the guard) when a minigame starts."""
    sig: MinigameSig
    cls: type
    unit: str                            # "minigames/x.py", "minigames/x/", or "engine"
    api: str                             # "1.0" or "1.1" (declared, normalized)
    over_stage: bool
    tokens: Mapping[str, object]
    words: Mapping[str, str]

    @property
    def name(self) -> str:
        return self.sig.name

    @property
    def bundled(self) -> bool:
        return self.unit == ENGINE_SOURCE


@dataclass
class Collector:
    """What one unit registers while its top level runs. Committed only if the unit ran to
    the end with no declaration error (one caught by the plugin still counts).
    ``achievement_hook`` (F37, API 1.2): the hook it registered, if any."""
    unit: str
    entries: list[PluginClass] = field(default_factory=list)
    errors: list[DeclarationError] = field(default_factory=list)
    achievement_hook: AchievementHook | None = None


@dataclass(frozen=True)
class AddOutcome:
    error: PluginLoadError | None = None
    replaced: PluginClass | None = None      # a bundled minigame this entry replaced


class Registry:
    """Minigames by name, filled by the loader. ``main_thread`` is the thread the loader
    ran on; every API object checks calls against it (SEC-F23-11). ``achievement_hook``
    (F37): the one committed hook, or None."""

    def __init__(self, *, main_thread: int) -> None:
        self.main_thread = main_thread
        self.achievement_hook: AchievementHook | None = None
        self._entries: dict[str, PluginClass] = {}
        self._count = 0
        self._active: Collector | None = None
        self.bound_hit = False

    # --- Reading --------------------------------------------------------------------------

    def get(self, name: str) -> PluginClass | None:
        return self._entries.get(name) if type(name) is str else None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def entries(self) -> tuple[PluginClass, ...]:
        return tuple(self._entries[name] for name in sorted(self._entries))

    def signatures(self) -> Mapping[str, MinigameSig]:
        """Read-only ``{name: MinigameSig}`` in name order (``LoadOptions.minigames``,
        ``Interpreter(minigames=)``, ``run_headless``)."""
        return MappingProxyType({name: self._entries[name].sig for name in sorted(self._entries)})

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    # --- Filling (the loader) -----------------------------------------------------------

    @contextmanager
    def collecting(self, unit: str) -> Iterator[Collector]:
        """``register`` calls made inside go to the returned collector."""
        if self._active is not None:
            raise RuntimeError("one unit at a time")
        collector = Collector(unit)
        self._active = collector
        try:
            yield collector
        finally:
            self._active = None

    def active(self) -> Collector | None:
        return self._active

    def collect(self, entry: PluginClass) -> None:
        """Called by ``register`` (inside the guard)."""
        collector = self._active
        if collector is None:
            raise RuntimeError("register() works only while minigame plugins load")
        if self._count + len(collector.entries) >= MAX_REGISTRATIONS:
            self.bound_hit = True
            raise RegistrationBound(messages.E273_BOUND_REGISTRATIONS)
        collector.entries.append(entry)

    def commit(self, collector: Collector) -> list[AddOutcome]:
        """Add a finished unit's registrations in the order made, and its hook."""
        if collector.achievement_hook is not None:
            self.achievement_hook = collector.achievement_hook
        return [self.add(entry) for entry in collector.entries]

    def hook_taken(self) -> bool:
        """A hook is registered: committed, or by the unit running now."""
        active = self._active
        return self.achievement_hook is not None or (
            active is not None and active.achievement_hook is not None)

    def add(self, entry: PluginClass) -> AddOutcome:
        """§7.10 step 8: two game units with one name → E274 (the first stays); a game unit
        named like a bundled minigame replaces it (the caller logs W160 and the INFO)."""
        self._count += 1
        old = self._entries.get(entry.name)
        if old is None:
            self._entries[entry.name] = entry
            return AddOutcome()
        if old.bundled and not entry.bundled:
            self._entries[entry.name] = entry
            return AddOutcome(replaced=old)
        error = PluginLoadError(
            messages.e274_two_plugins(entry.name, old.unit, entry.unit), code="E274")
        return AddOutcome(error=error)


__all__ = ["MAX_REGISTRATIONS", "AddOutcome", "Collector", "DeclarationError", "PluginClass",
           "PluginLoadError", "RegistrationBound", "Registry", "name_problem"]

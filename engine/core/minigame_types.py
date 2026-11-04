"""Frozen plain data shared by ``script``, ``runtime``, and ``minigames`` (F23 ``04`` §3).

Why this module exists: a minigame's signature (its name, arguments, and test and skipped
outcomes) is needed by the script checks (``script`` imports only ``core``), by the runtime
(arguments, results, changes), and by the plugin loader and host. Keeping the types here
lets all three share them without an import between them (F23 ``07`` finding 2). No logic.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

API_VERSION: Final = (1, 3)          # 1.1: check_story, outcome_for (F24 A1; F23 I-19)
#                                      1.2: register_achievement_hook (F37 §5.3)
#                                      1.3: PlayerSettings.timing_assist, timed (F50)
# Plugin unit stems, names inside a package, and minigame names (SEC-F23-02). Use
# ``fullmatch`` only: ``match`` with ``$`` would accept a trailing newline.
PLUGIN_NAME_RE: Final = re.compile(r"[a-z][a-z0-9_]{0,39}", re.ASCII)
ARGS_MAX: Final = 32                 # declared arguments per minigame


class _Required:
    """The ``REQUIRED`` sentinel: an argument with no default. Never saved."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "REQUIRED"

    def __reduce__(self) -> str:
        return "REQUIRED"


REQUIRED: Final = _Required()


@dataclass(frozen=True, slots=True)
class ArgSpec:
    name: str
    default: object                  # REQUIRED or a frozen value


@dataclass(frozen=True, slots=True)
class MeterChange:
    name: str
    op: Literal["+=", "-=", "="]
    amount: int


@dataclass(frozen=True, slots=True)
class CodexChange:
    verb: Literal["give", "take", "unlock_tip"]
    name: str


Change = MeterChange | CodexChange


@dataclass(frozen=True, slots=True)
class Outcome:
    result: object
    changes: tuple[Change, ...] = ()     # exact built-ins only


@dataclass(frozen=True, slots=True)
class StoryNames:
    """The story's declared names, each in declaration order (F24 A1; F23 ``04`` §3): what
    ``check_story`` and ``outcome_for`` see. Built once per interpreter by the runtime
    (F24 ``07`` I-3). Declared, not held: an item no one holds is still listed.

    ``item_categories`` (F25 A5; joins API 1.1 with no bump, SPEC I-20): one entry per item
    category, ``(category key, item names)``, categories in F21's first-declaration order
    and items in declaration order. The key is the author's text, or ``"codex_items"`` for
    the default item category: the keys ``CodexFilter.categories`` takes. Tips are never
    listed. Last, with a default, so ``StoryNames((), (), ())`` still builds."""
    meters: tuple[str, ...]
    items: tuple[str, ...]
    tips: tuple[str, ...]
    item_categories: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class MinigameSig:
    name: str
    title: str
    source: str                          # "minigames/x.py", "minigames/x/", or "engine"
    args: tuple[ArgSpec, ...]            # declaration order, ≤ ARGS_MAX
    test: Outcome | None
    skipped: Outcome | None
    # The plugin's check_args, then (API ≥ 1.1) check_story, on one fresh instance (author
    # code; the caller's guard entry). Returns a reason, None, or anything else (E275).
    check: Callable[[dict, StoryNames], object] | None
    # API ≥ 1.1: outcome_for(kind, args, story) on a fresh instance, converted as a declared
    # outcome; None falls back to ``test``/``skipped``. Raises on a refused value.
    outcome: Callable[[str, dict, StoryNames], Outcome | None] | None = None


__all__ = ["API_VERSION", "ARGS_MAX", "PLUGIN_NAME_RE", "REQUIRED", "ArgSpec", "Change",
           "CodexChange", "MeterChange", "MinigameSig", "Outcome", "StoryNames"]

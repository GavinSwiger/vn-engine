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

from engine.core.codexkinds import page_kinds

API_VERSION: Final = (1, 5)          # 1.1: check_story, outcome_for (F24 A1; F23 I-19)
#                                      1.2: register_achievement_hook (F37 §5.3)
#                                      1.3: PlayerSettings.timing_assist, timed (F50)
#                                      1.4: TextField (F52)
#                                      1.5: item counts (F64 round 2: count, most, n)
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
    """``give``/``take`` an item (``amount`` of it: F64 round 2, 1 to 999,999; 1 before), or
    ``unlock_tip`` (``amount`` always 1)."""
    verb: Literal["give", "take", "unlock_tip"]
    name: str
    amount: int = 1


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
    # F55 (additive, like ``item_categories``): one entry per tip category, ``(category key,
    # tip names)``; the key is the author's text, or ``"codex_tips"`` for the default one.
    tip_categories: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # F64 round 2 (additive): the item marked ``money`` (None: no purse), and each item
    # declared with ``price <n>``, ``(name, price)`` in declaration order.
    money: str | None = None
    prices: tuple[tuple[str, int], ...] = ()


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


# --- ctx.codex_view's two types (F25 A6; v1 S14) ----------------------------------------------
# Here, not in ``ui/builtin/codex_page`` (which re-exports them), so the minigame API names no
# screen module. API 1.5 is unchanged: same names, fields and defaults.

CODEX_PAGE_KINDS: Final = frozenset(k.name for k in page_kinds("codex"))   # tips and items


@dataclass(frozen=True)
class CodexFilter:
    """Which entries a view lists. ``categories``: author texts, or ``"codex_tips"`` /
    ``"codex_items"`` for a kind's default category; None: all."""

    kinds: frozenset[str] = CODEX_PAGE_KINDS
    categories: frozenset[str] | None = None


@dataclass(frozen=True)
class PickAction:
    """The pick button: its text (from the host's words) and what a pick calls."""

    word: str
    on_pick: Callable[[str], None]


__all__ = ["API_VERSION", "ARGS_MAX", "CODEX_PAGE_KINDS", "PLUGIN_NAME_RE", "REQUIRED",
           "ArgSpec", "Change", "CodexChange", "CodexFilter", "MeterChange", "MinigameSig",
           "Outcome", "PickAction", "StoryNames"]

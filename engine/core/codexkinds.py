"""Codex kinds: one page per kind on one store (F65 round 1, "Codex kinds"; plan:
specs/skins-contract.md, "Phases 2-4").

Why this module exists: the codex started with two kinds of entry, tips and items, and the
skins plan adds more (chats now; contacts, goals, thoughts and profiles later). Each one is
the same mechanic: entries the player collects, listed on a page with an unread mark and a
detail panel. So a kind is a small **description** registered here, not new plumbing: the
runtime keeps its entries in the codex's one store (``runtime/codex.Codex``: tips in the
persistent store, everything else in ``GameState.items``), and ``ui/builtin/codex_page``
lists any kind from its description.

The API:

- ``CodexKind(name, page, tab_word, ...)``: one kind.

  - ``name``: the kind's id, ``CodexEntry.kind``, and, for a ``declared`` kind, the script's
    key word after ``lock``/``unlock`` (``lock tip lanterns "Paper Lanterns"``).
  - ``page``: the page that lists it, which is also its ``[words]`` key (the heading and the
    game-menu button) and its menu id: ``"codex"`` for tips and items, ``"inbox"`` for chats.
  - ``tab_word``: the ``[words]`` key of its default tab (entries that name no category).
  - ``kit_title``: ``(section, key)`` of the kit field that names the page when the author
    left ``[words] <page>`` at its default (``("messages", "title")``: "Messages",
    "Letters"); None: the ``[words]`` word only. ``kits.kit_words`` collects them.
  - ``shows``: which fields its detail and rows show, from ``FIELDS``: ``"picture"``,
    ``"category"`` (its own tabs), ``"count"`` ("×3" on a row), ``"body"`` (paragraphs).
  - ``order``: how its rows are listed: ``"declared"`` (declaration order; locked ones as
    ``???`` under ``[codex] show_locked``), ``"obtained"`` (the order the player got them),
    ``"newest"`` (newest first).
  - ``declared``: the author declares its entries in a script (``lock tip|item``); False
    for a kind the story fills in as it plays (chats).
  - ``kept``: kept across playthroughs (tips: the persistent store) rather than saved with
    this playthrough (``GameState``).
  - ``on_title``: also listed by the page the title screen opens (tips only).

- ``register_codex_kind(kind)``: add a kind (again with the same name replaces it, so a
  reload is harmless); ``codex_kind(name)``, ``codex_kinds()`` (registration order: the
  order rows are made in), ``page_kinds(page)``, ``declared_kinds()``, ``page_of(name)``.
- ``TIP``, ``ITEM``, ``CHAT``: the built-in kinds, registered on import.

Adding a kind is: a description here, its entries in ``Codex`` (its ``listed`` order and
read marks), and a page (``ui/builtin/kind_page.KindPage(port, page)`` plus one game-menu
id in ``ui/menus.DEFAULT_ORDER``). Pure data; imports nothing of the engine.
"""

from dataclasses import dataclass, field
from typing import Final

ORDER_DECLARED: Final = "declared"
ORDER_OBTAINED: Final = "obtained"
ORDER_NEWEST: Final = "newest"
ORDERS: Final = frozenset({ORDER_DECLARED, ORDER_OBTAINED, ORDER_NEWEST})
FIELDS: Final = frozenset({"picture", "category", "count", "body"})


@dataclass(frozen=True, slots=True)
class CodexKind:
    """One kind of codex entry (module docstring)."""

    name: str
    page: str
    tab_word: str
    kit_title: tuple[str, str] | None = None
    shows: frozenset[str] = field(default=frozenset({"picture", "category", "body"}))
    order: str = ORDER_DECLARED
    declared: bool = True
    kept: bool = False
    on_title: bool = False

    def __post_init__(self) -> None:
        if self.order not in ORDERS:
            raise ValueError(f"unknown codex kind order {self.order!r}")
        if not self.shows <= FIELDS:
            raise ValueError(f"unknown codex kind fields {sorted(self.shows - FIELDS)}")


_KINDS: dict[str, CodexKind] = {}


def register_codex_kind(kind: CodexKind) -> CodexKind:
    """Add ``kind`` (module docstring); returns it."""
    _KINDS[kind.name] = kind
    return kind


def codex_kind(name: str) -> CodexKind | None:
    return _KINDS.get(name)


def codex_kinds() -> tuple[CodexKind, ...]:
    """Every kind, in registration order."""
    return tuple(_KINDS.values())


def page_kinds(page: str) -> tuple[CodexKind, ...]:
    """The kinds listed on ``page``, in registration order."""
    return tuple(k for k in _KINDS.values() if k.page == page)


def declared_kinds() -> tuple[CodexKind, ...]:
    """The kinds a script declares (``lock <name> ...``)."""
    return tuple(k for k in _KINDS.values() if k.declared)


def page_of(name: str) -> str | None:
    """The page that lists kind ``name``, or None."""
    kind = _KINDS.get(name)
    return kind.page if kind is not None else None


TIP: Final = register_codex_kind(CodexKind(
    "tip", "codex", "codex_tips", kept=True, on_title=True))
ITEM: Final = register_codex_kind(CodexKind(
    "item", "codex", "codex_items", shows=frozenset({"picture", "category", "count", "body"}),
    order=ORDER_OBTAINED))
CHAT: Final = register_codex_kind(CodexKind(            # F65: a finished phone chat
    "chat", "inbox", "inbox", kit_title=("messages", "title"), shows=frozenset({"body"}),
    order=ORDER_NEWEST, declared=False))


__all__ = ["CHAT", "FIELDS", "ITEM", "ORDERS", "ORDER_DECLARED", "ORDER_NEWEST",
           "ORDER_OBTAINED", "TIP", "CodexKind", "codex_kind", "codex_kinds", "declared_kinds",
           "page_kinds", "page_of", "register_codex_kind"]

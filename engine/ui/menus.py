"""Menu entries: the id table, the registry, pages, and run-time overrides (F10 ``04`` §5.4,
§7.11; ``07`` "The entry registry and overrides").

Why this module exists: the title, the game menu, and the quick menu show buttons that
later features add (Load, Save, Settings, History, Skip, ...), and F32 changes labels and
title art from a script. None of them may edit F10's screens. So:

- ``DEFAULT_ORDER`` is the one table of menu ids, like ``KINDS``. An id is also its
  ``[words]`` key and its name in ``[title]``/``[quick_menu] entries``. A feature adds an id
  (with its ``WordsConfig`` field) only through its review. ``help`` is reserved (deferred).
- ``MenuRegistry.add(menu, MenuEntry(...))`` is called only from a feature's ``install_*``,
  once per id and menu. Screens call ``shown(menu)`` every time they open and read labels
  (``Words.get``) on every draw.
- ``UiOverrides`` is presentation-only state (labels and hidden entries): never saved by F10
  and never read by the runtime. F32's looks (``ui/looks.py``) are the run-time title art,
  music, and words: ``Words``' override hook asks ``UiOverrides`` first, then the look, and
  ``MenuRegistry.title_entries`` gives the playthrough look's title buttons (F32 ``04`` §6.4;
  its unused title-look setters were removed, main decision 2).

Pure Python: no display, no pygame.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol

from engine.core.config_schema import ValueProblem, word_fields

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.ui.focus import Box, FocusGroup, FocusScope
    from engine.ui.input import UiEvent
    from engine.ui.nav import InputKind, Nav
    from engine.ui.paint import Painter
    from engine.ui.shell import GameShell
    from engine.ui.widgets import Widget

MenuName = Literal["title", "game", "quick"]

DEFAULT_ORDER: Final[dict[str, tuple[str, ...]]] = {
    "title": ("new_game", "load", "flowchart", "settings", "extras", "codex", "help", "quit"),
    "game": ("return", "skip_minigame", "history", "codex", "flowchart", "save", "load",
             "settings", "help", "main_menu", "quit"),
    "quick": ("back", "history", "skip", "auto", "save", "q_save", "q_load", "settings",
              "hide", "menu"),
}
# Ids a menu shows only when the author lists them (F21 07 I-2): where ``order()`` falls back
# to ``DEFAULT_ORDER`` (no list, an empty one, or one naming no registered button), these are
# left out. ``add``, ``registered``, and W66 don't change. An id joins only through review.
# F20's ``flowchart`` is not one (03 "Entries", 06 D4): its title entry is a main path, kept
# off a first run's title by its own rule (a jumpable node).
OPT_IN: Final[dict[str, frozenset[str]]] = {"title": frozenset({"codex"})}
# What W66 calls a button of each menu ("isn't a title-screen button").
MENU_NOUNS: Final[dict[str, str]] = {"title": "title-screen button",
                                     "game": "game-menu button",
                                     "quick": "quick-menu button"}


def _always() -> bool:
    return True


@dataclass(frozen=True)
class EntryContext:
    """What an entry's ``action`` gets: the shell and the kind of input that activated it."""
    shell: "GameShell"
    by: "InputKind"


@dataclass(frozen=True)
class MenuEntry:
    """One button of one menu. ``id`` is also its ``[words]`` key and its ``entries`` name."""
    id: str
    action: Callable[[EntryContext], None] | None = None
    page: "Callable[[PageHost], MenuPage] | None" = None      # title/game: a content page
    enabled: Callable[[], bool] = _always
    visible: Callable[[], bool] = _always                     # e.g. Extras once unlocked
    on: Callable[[], bool] | None = None                      # on/off entries (F15)


class MenuPage(Protocol):
    """A page shown in the game menu's body slot (F11 Save/Load, F13 History, F16
    Settings). Pages are content of the game menu, not screens (step 7). A page subclasses
    ``MenuPageBase``, which gives every optional method its default."""

    heading: str                                              # a [words] key
    nav_extras: frozenset[str]

    def build(self, host: "PageHost", body: "Box") -> "list[FocusGroup]": ...

    def update(self, dt: float) -> None: ...

    def draw(self, canvas: "Canvas", p: "Painter") -> None: ...

    def back(self) -> bool: ...                               # True: handled Back itself

    def closed(self) -> None: ...

    def on_nav(self, d: "Nav") -> bool: ...

    def on_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool: ...

    def default_widget(self) -> "Widget | None": ...


class MenuPageBase:
    """The base of every page (F16 ``07`` I-12, with F11 C1's ``default_widget``): each
    optional method has its default here, so hosts call them unconditionally (no
    ``hasattr``).

    - ``back()`` False: the host closes the page (True: the page handled Back itself).
    - ``closed()``: the page left the menu (another entry, Back, or the menu closed).
    - ``on_nav(d)``: Page Up / Page Down that the focused widget didn't use (F16 conflict
      5; sidebar buttons never use them; F11's Save and Load pages change page with them).
      True: used; a held key then repeats through ``on_nav``.
    - ``on_mouse(kind, pos, *, notches)``: F16 conflict 5. A button-1 press inside the body
      slot on no focusable widget (``"down"``; True: the page took the press and then gets
      its ``"drag"`` and ``"up"``), and the wheel inside the body slot that the widget under
      the pointer didn't use (``"wheel"``). False here.
    - ``default_widget()`` (C1): the widget a title page opened by keys or a click focuses,
      and Right from the sidebar enters when the page has no last-focused widget. None: the
      first page widget in Tab order (a title page: Return).
    - ``nav_extras``: the ``NavReader`` extras the page wants while open (F11's pages:
      ``"shoulders"`` and ``"delete"``).
    - ``on_event(event)`` (F20): a raw event the open page may take first; False here."""

    heading: str = ""                                         # a [words] key
    nav_extras: frozenset[str] = frozenset()

    def build(self, host: "PageHost", body: "Box") -> "list[FocusGroup]":
        return []

    def update(self, dt: float) -> None:
        pass

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        pass

    def back(self) -> bool:
        return False

    def closed(self) -> None:
        pass

    def on_nav(self, d: "Nav") -> bool:
        return False

    def on_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        return False

    def default_widget(self) -> "Widget | None":
        return None

    def on_event(self, event: "UiEvent") -> bool:
        """F20: a raw event, before the menu reads it (inputs F10's reader doesn't map: the
        flowchart's ``+``/``-`` zoom, gamepad north and west, the right stick, a modified or
        horizontal wheel). True: used, and the menu does nothing else with it."""
        return False


class PageHost(Protocol):
    """What a page may use of the screen hosting it (step 7's ``GameMenuScreen``).
    ``scope`` (F16 conflict 6) is the screen's ``FocusScope``, read-only: a page reads what
    is focused and how, and may focus its own widgets (F16's Page Up / Page Down)."""

    shell: "GameShell"
    painter: "Painter"

    @property
    def scope(self) -> "FocusScope": ...

    def rebuild(self) -> None: ...

    def close_menu(self) -> None: ...


class UiOverrides:
    """Run-time presentation changes (F32). ``None`` given to a setter removes that override,
    so the config value shows again. ``revision`` increases on every change; screens re-read
    when it moves."""

    def __init__(self) -> None:
        self.revision = 0
        self._words: dict[str, str] = {}
        self._hidden: dict[tuple[str, str], bool] = {}

    # -- setters --

    def set_word(self, key: str, text: str | None) -> None:
        """Show ``text`` for the word ``key`` (checked as ``[words] key`` is)."""
        fields = word_fields()
        if key not in fields:
            raise ValueError(f"no word named {key!r}")
        if text is None:
            self._words.pop(key, None)
        else:
            validator = fields[key].metadata["validator"]
            try:
                validator.check(text)
            except ValueProblem:
                raise ValueError(f"[words] {key} must be {validator.expected}") from None
            self._words[key] = text
        self.revision += 1

    def set_hidden(self, menu: str, entry_id: str, hidden: bool | None) -> None:
        """Hide (True) or show (False) one entry; None removes the override."""
        if menu not in DEFAULT_ORDER or entry_id not in DEFAULT_ORDER[menu]:
            raise ValueError(f"{entry_id!r} is not an entry of the {menu!r} menu")
        if hidden is None:
            self._hidden.pop((menu, entry_id), None)
        else:
            self._hidden[(menu, entry_id)] = bool(hidden)
        self.revision += 1

    def clear(self) -> None:
        """Every override removed: config labels and entries return."""
        self._words.clear()
        self._hidden.clear()
        self.revision += 1

    # -- reads --

    def word(self, key: str) -> str | None:
        return self._words.get(key)

    def hidden(self, menu: str, entry_id: str) -> bool | None:
        return self._hidden.get((menu, entry_id))


class MenuRegistry:
    """The entries of the three menus. ``entries`` maps a menu to the author's list
    (``[title] entries``, ``[quick_menu] entries``; None or empty: ``DEFAULT_ORDER``).
    ``title_entries`` (F32 ``04`` §6.4) is the current playthrough look's
    ``title_entries``; when it gives a list, the title shows that list instead."""

    def __init__(self, *, entries: Mapping[str, Sequence[str] | None] | None = None,
                 overrides: UiOverrides | None = None) -> None:
        self._entries: dict[str, dict[str, MenuEntry]] = {menu: {} for menu in DEFAULT_ORDER}
        self._author = dict(entries or {})
        self.overrides = overrides if overrides is not None else UiOverrides()
        self.title_entries: Callable[[], tuple[str, ...] | None] | None = None

    def add(self, menu: MenuName, entry: MenuEntry) -> None:
        """Register ``entry`` for ``menu`` (at install time). An id that isn't in
        ``DEFAULT_ORDER[menu]``, or one already registered, is a programming error."""
        assert menu in DEFAULT_ORDER, f"unknown menu {menu!r}"
        assert entry.id in DEFAULT_ORDER[menu], \
            f"{entry.id!r} is not an id of the {menu!r} menu (DEFAULT_ORDER)"
        assert entry.id not in self._entries[menu], \
            f"{entry.id!r} is already registered for the {menu!r} menu"
        self._entries[menu][entry.id] = entry

    def registered(self, menu: str) -> list[str]:
        """The registered ids of ``menu`` in default order."""
        found = self._entries[menu]
        return [entry_id for entry_id in DEFAULT_ORDER[menu] if entry_id in found]

    def entry(self, menu: str, entry_id: str) -> MenuEntry | None:
        return self._entries[menu].get(entry_id)

    def author_list(self, menu: str) -> tuple[str, ...] | None:
        """The author's ``entries`` for ``menu`` as written (None: not set); for the title,
        the playthrough look's ``title_entries`` when it has them (F32)."""
        if menu == "title" and self.title_entries is not None:
            look = self.title_entries()
            if look is not None:
                return tuple(look)
        return self.config_list(menu)

    def config_list(self, menu: str) -> tuple[str, ...] | None:
        """The config's ``entries`` for ``menu`` (no look), as written; None: not set."""
        found = self._author.get(menu)
        return None if found is None else tuple(found)

    def order(self, menu: str) -> tuple[str, ...]:
        """The author's list if set and naming at least one registered id, else
        ``DEFAULT_ORDER[menu]`` without ``OPT_IN[menu]`` (§7.11; an empty list, or one naming
        no button of the menu, is one W66 in its empty-list form and shows the defaults,
        AC-F10-27; F21 07 I-2: the title's Codex only when listed)."""
        author = self.author_list(menu)
        if author and any(entry_id in self._entries[menu] for entry_id in author):
            return author
        opt_in = OPT_IN.get(menu)
        if opt_in:
            return tuple(entry_id for entry_id in DEFAULT_ORDER[menu] if entry_id not in opt_in)
        return DEFAULT_ORDER[menu]

    def shown(self, menu: str) -> list[MenuEntry]:
        """The entries a screen shows now: in ``order(menu)``, registered, not hidden by
        ``overrides``, and ``visible()``."""
        found = self._entries[menu]
        shown = []
        for entry_id in self.order(menu):
            entry = found.get(entry_id)
            if entry is None or self.overrides.hidden(menu, entry_id) is True:
                continue
            if entry.visible():
                shown.append(entry)
        return shown


def join_names(names: Sequence[str]) -> str:
    """W66's list of names: "a", "a and b", "a, b, and c" (G7 draft)."""
    if not names:
        return "none"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


__all__ = ["DEFAULT_ORDER", "MENU_NOUNS", "OPT_IN", "EntryContext", "MenuEntry",
           "MenuName",
           "MenuPage", "MenuPageBase", "MenuRegistry", "PageHost", "UiOverrides", "join_names"]

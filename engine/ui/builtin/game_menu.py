"""``GameMenuScreen`` and ``GameMenuKeys``: the in-game menu (F10 ``03`` "Game menu",
UI-F10-09; ``04`` §7.7.3).

Why this module exists: the player leaves the story for Return, Main Menu, Quit, and the
pages later features add (History, Save, Load, Settings, Help) from one place, over the
frozen scene (PR-F10-28 to 31). The menu is a ``MenuScreen``, so it holds the story (it is
not ``in_game``) and takes mouse, keys, and gamepad the same way as every F10 screen.

- **Look.** The scene captured once and dimmed (``menu.dim_*``, ``CapturedBackdrop`` with
  the scene kept for F11's thumbnails, ``scene_picture()``); the sidebar panel (24, 24,
  336×672) holding ``shell.menus.shown("game")`` as a centred column
  (``layouts.sidebar_layout``). The content panel (384, 24, 872×672) shows only while a page
  is open, with the page's heading at (416, 56) and its body slot (416, 112, 808×552).
- **Pages** (``MenuPage``, F11 Save/Load, F13 History, F16 Settings) are content of this
  screen, not screens: one backdrop and one Back path. Opening one is 0 ms; its entry shows
  *selected*. Right from the sidebar enters the page (its last-focused widget, else its
  ``default_widget()`` (F11 C1), else its first); Left from the page's leftmost widget returns
  to the selected entry. Page Up / Page Down that no widget used go to the page's ``on_nav``
  (F16 conflict 5) and repeat while held; a press on no focusable widget and a wheel no
  widget used, inside the body slot, go to its ``on_mouse`` (a press it takes brings its
  drag and up); the page's ``nav_extras`` set the reader's extras (F11: the bumpers and the
  delete keys). Pages subclass ``MenuPageBase`` (F16 I-12). The screen is the pages'
  ``PageHost``; its ``scope`` is the one ``FocusScope`` (F16 conflict 6).
- **Back** (Esc, right click, east): a page whose ``back()`` returns True keeps it; else the
  page closes (focus on its entry); with no page the menu closes. Start closes it. Return
  closes it. Shift+F3 opens the widget sampler in dev runs.
- **From the title** (``GameShell.open_title_page``, F11 Load and F16 Settings) the same
  screen shows over the title: the sidebar is Return and the title's page entries, the
  page is open, and Back closes the whole screen. It has no scene picture. Opened by keys or
  a click it focuses the page's default widget, not Return (C1); Start does nothing there.
- **Extras** (F34, ``GameShell.open_extras``): the same title-page screen with ``menu =
  "extras"``: the sidebar is Return and the shown pages of the ``extras`` menu (Gallery,
  Endings, Scenes, Music room, Achievements, in that fixed order).
- **During a replay** (F36): a button's word is ``shell.entry_word(id)``, so Main Menu reads
  ``replay_end`` ("End Replay"); the shell's ``session_hidden`` leaves out Save, Load and
  Flowchart.

``GameMenuKeys`` is the ``InGameOverlay`` that opens the menu (Esc without Ctrl/Alt/Meta,
right click in the canvas, gamepad east or Start). It is hosted by the in-game line screen
(F05's ``TextboxScreen``, through ``add_overlay``) and
consumes those inputs, so F05's own handling never sees them. The shell opens the menu only
in mode GAME and when no menu is open (``GameShell.open_game_menu``).
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

import pygame

from engine.render.canvas import Canvas
from engine.ui.backdrop import CapturedBackdrop
from engine.ui.focus import Box, FocusGroup, move_target, reading_key
from engine.ui.input import UiEvent
from engine.ui.layouts import CONTENT_PANEL, SIDEBAR, SidebarLayout, sidebar_layout
from engine.ui.menu_screen import MenuScreen, Phase
from engine.ui.menus import EntryContext, MenuEntry, MenuPage, badged
from engine.ui.nav import InputKind, Nav, NavReader
from engine.ui.paint import Painter
from engine.ui.widgets import Button, Widget

if TYPE_CHECKING:
    from engine.ui.shell import GameShell


class GameMenuScreen(MenuScreen):
    """The game menu (or, with ``title_page``, a page opened from the title). It is also the
    ``PageHost`` of its pages."""

    def __init__(self, shell: "GameShell", *, by: InputKind,
                 title_page: str | None = None, menu: str = "title") -> None:
        self.from_title = title_page is not None
        self.menu = menu                     # from the title: whose pages fill the sidebar
        cfg = shell.theme.cfg
        backdrop = CapturedBackdrop(shell.assets, cfg.menu.dim_color, cfg.menu.dim_opacity,
                                    keep_scene=not self.from_title)
        self._buttons: dict[str, Button] = {}
        self.entries: list[MenuEntry] = []
        self.buttons: list[Button] = []
        self.sidebar = FocusGroup([], column=True)
        self.layout: SidebarLayout | None = None
        self.page: MenuPage | None = None
        self.page_id: str | None = None
        self.page_groups: list[FocusGroup] = []
        self._page_focus: Widget | None = None
        self._seen_revision = shell.overrides.revision
        self.on_closed: Callable[[], None] | None = None     # F65: open inbox's wait
        super().__init__(shell, by=by, backdrop=backdrop)
        self.scope.on_edge = self._edge
        if title_page is not None:
            self.open_page(title_page)
            # C1: a title page opened by keys or a click focuses the page's default widget
            # (not Return); drawn focused only for keys.
            target = self.page.default_widget() if self.page is not None else None
            if self.scope.can_focus(target):
                assert target is not None
                self.scope.focus(target, by, sound=False, visible=by is InputKind.KEYS)

    @property
    def game_shell(self) -> "GameShell":
        return self.shell                                    # type: ignore[return-value]

    # -- PageHost --

    def rebuild(self) -> None:
        """Lay out the sidebar and the open page again (F16 text size)."""
        self.build()

    def close_menu(self) -> None:
        """Close this menu (F11: a load from inside the game menu closes it first)."""
        self.close()

    # -- F11, F16, F39 --

    def scene_picture(self) -> pygame.Surface | None:
        """The frozen scene under the menu, undimmed, in device pixels of the viewport (F11
        thumbnails, PR-F10-31); None before the first draw and from the title."""
        if self.from_title or self.backdrop is None:
            return None
        return self.backdrop.scene_picture()

    def refresh_backdrop(self) -> None:
        """Recapture the scene on the next frame (F16 text size, F39 reload)."""
        if self.backdrop is not None:
            self.backdrop.invalidate()

    # -- layout --

    def _shown(self) -> list[MenuEntry]:
        shell = self.game_shell
        if not self.from_title:
            return shell.menus.shown("game")
        back = MenuEntry("return", action=lambda ctx: self.close())
        return [back, *(e for e in shell.menus.shown(self.menu) if e.page is not None)]

    def build(self) -> None:
        cfg = self.shell.theme.cfg
        self.entries = self._shown()
        self.layout = sidebar_layout(len(self.entries), scale=self.painter.text_scale(),
                                     text_size=cfg.button.text_size, height=cfg.button.height,
                                     width=cfg.menu.button_width, gap=cfg.button.gap)
        buttons = []
        for entry, box in zip(self.entries, self.layout.buttons, strict=True):
            button = self._buttons.get(entry.id)
            if button is None:
                button = self._buttons[entry.id] = self._button(entry)
            button.box = box
            buttons.append(button)
        self.buttons = buttons
        self.sidebar = FocusGroup(buttons, column=True)
        self.scope.default_widget = buttons[0] if buttons else None
        page = self.page
        if page is not None:
            self.page_groups = list(page.build(self, self.layout.body))
            if self.from_title:
                # C1: from the title the first key press focuses the page, not Return.
                default = page.default_widget()
                if default is not None:
                    self.scope.default_widget = default
        self.reader.extras = page.nav_extras if page is not None else frozenset()
        self.scope.set_groups([self.sidebar, *self.page_groups])
        self.revision += 1

    def _button(self, entry: MenuEntry) -> Button:
        # F36: the shell's ``entry_word`` (Main Menu reads "End Replay" during a replay); a
        # bare ``MenuShell`` (test rigs) has only its words.
        word = getattr(self.shell, "entry_word", self.shell.words.get)
        return Button(lambda: badged(word(entry.id), entry), lambda: self._activate(entry),
                      enabled=entry.enabled, on=entry.on,
                      selected=lambda: self.page_id == entry.id)

    def button(self, entry_id: str) -> Button | None:
        """The sidebar button of ``entry_id`` while it is shown."""
        found = self._buttons.get(entry_id)
        return found if found in self.buttons else None

    def layer_box(self) -> Box:
        if self.page is None:
            return SIDEBAR
        return Box(SIDEBAR.x, SIDEBAR.y, CONTENT_PANEL.right - SIDEBAR.x, SIDEBAR.h)

    # -- entries and pages --

    def _activate(self, entry: MenuEntry) -> None:
        if entry.page is not None:
            self.open_page(entry.id)
        elif entry.action is not None:
            entry.action(EntryContext(self.game_shell, self.input_kind))

    def open_page(self, entry_id: str) -> None:
        """Show ``entry_id``'s page in the body slot (0 ms); its entry shows selected."""
        entry = next((e for e in self.entries if e.id == entry_id), None)
        assert entry is not None and entry.page is not None, \
            f"{entry_id!r} is not a page entry of this menu"
        if self.page_id == entry_id:
            return
        if self.page is not None:
            self._drop_page()
        self.page = entry.page(self)
        self.page_id = entry_id
        self._page_focus = None
        self.build()

    def close_page(self, *, by: InputKind = InputKind.KEYS) -> None:
        """Close the open page: no content panel, focus on its sidebar entry (drawn focused
        only for keys)."""
        if self.page is None:
            return
        button = self.button(self.page_id or "")
        self._drop_page()
        self.build()
        if button is not None and self.scope.can_focus(button):
            self.scope.focus(button, by, sound=False, visible=by is InputKind.KEYS)

    def _drop_page(self) -> None:
        page, self.page = self.page, None
        self.page_id = None
        self.page_groups = []
        self._page_focus = None
        if page is not None:
            page.closed()

    def _page_widgets(self) -> list[Widget]:
        return [w for g in self.page_groups for w in g.widgets]

    def _edge(self, d: Nav, group: FocusGroup) -> bool:
        """Called when a move finds nothing inside ``group``. The sidebar wraps Up/Down in
        itself and enters the open page on Right (its last-focused widget, else its first);
        a page moves among its own groups, and Left from its leftmost widget returns to the
        selected entry. A move never jumps between sidebar and page any other way."""
        scope = self.scope
        cur = scope.focused
        if cur is None:
            return False
        if group is self.sidebar:
            if d is Nav.RIGHT:
                return self._enter_page()
            members = sorted(group.focusable(), key=lambda w: reading_key(w.box))
            if d in (Nav.UP, Nav.DOWN) and members:
                target = members[0] if d is Nav.DOWN else members[-1]
                if target is not cur:
                    scope.focus(target, InputKind.KEYS)
            return True
        others = [w for g in self.page_groups if g is not group for w in g.focusable()]
        index = move_target(cur.box, [w.box for w in others], d)
        if index is not None:
            return scope.focus(others[index], InputKind.KEYS)
        if d is Nav.LEFT:
            self._page_focus = cur
            button = self.button(self.page_id or "")
            if button is not None:
                scope.focus(button, InputKind.KEYS)
        return True

    def _enter_page(self) -> bool:
        """Right from the sidebar: the page's last-focused widget, else its default widget
        (C1), else its first in Tab order."""
        scope = self.scope
        target = self._page_focus if scope.can_focus(self._page_focus) else None
        if target is None and self.page is not None:
            default = self.page.default_widget()
            target = default if scope.can_focus(default) else None
        if target is None:
            page_widgets = self._page_widgets()
            order = [w for w in scope.tab_order() if w in page_widgets]
            target = order[0] if order else None
        return target is not None and scope.focus(target, InputKind.KEYS)

    # -- input --

    def handle_event(self, event: UiEvent) -> bool:
        """F20: an open page sees each event first (``MenuPageBase.on_event``) once the menu
        is open; one it uses goes no further."""
        page = self.page
        if page is not None and self.phase is Phase.OPEN and page.on_event(event):
            if event.type in (pygame.KEYDOWN, pygame.CONTROLLERBUTTONDOWN):
                self.input_kind = InputKind.KEYS
                self.shell.cursor.show(False)
            return True
        return super().handle_event(event)

    def back(self) -> None:
        page = self.page
        if page is not None:
            if page.back():
                return
            if not self.from_title:
                self.close_page(by=self.input_kind)
                return
        self.close()

    def on_start(self) -> None:
        """Gamepad Start closes the game menu; over the title it does nothing (F11 03-ui)."""
        if not self.from_title:
            self.close()

    def unused_nav(self, nav: Nav) -> bool:
        """Page Up / Page Down the focused widget didn't use go to the open page (F16
        conflict 5; F11: the previous / next page). Sidebar buttons never use them, so they
        reach the page wherever focus is."""
        page = self.page
        if page is None or nav not in (Nav.PAGE_UP, Nav.PAGE_DOWN):
            return False
        return page.on_nav(nav)

    def unused_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        """A press on no focusable widget, or a wheel no widget used, inside the body slot
        goes to the open page (F16 conflict 5); a press it takes brings its drag and up."""
        page = self.page
        if page is None or self.layout is None:
            return False
        if kind in ("down", "wheel") and not self.layout.body.contains(pos):
            return False
        return page.on_mouse(kind, pos, notches=notches)

    def on_sampler(self) -> None:
        if self.shell.dev:
            from engine.ui.builtin.sampler import SamplerScreen

            self.push_child(SamplerScreen(self.shell, by=InputKind.KEYS))

    # -- frame --

    def on_update(self, dt: float) -> None:
        overrides = self.game_shell.overrides
        if overrides.revision != self._seen_revision:
            self._seen_revision = overrides.revision
            self.build()                                   # F32: hidden entries, labels
        focused = self.scope.focused
        if focused is not None and focused in self._page_widgets():
            self._page_focus = focused
        if self.page is not None:
            self.page.update(dt)

    def on_exit(self) -> None:
        super().on_exit()
        if self.page is not None:
            self._drop_page()
        done, self.on_closed = self.on_closed, None
        if done is not None:
            done()

    def draw_content(self, p: Painter) -> None:
        assert self.layout is not None
        p.panel(self.layout.panel)
        page = self.page
        if page is not None:
            p.panel(self.layout.content)
            p.heading(self.shell.words.get(page.heading), self.layout.heading)
            page.draw(p.canvas, p)
        self.draw_widgets(p)


class GameMenuKeys:
    """The in-game overlay that opens the game menu (C5): Esc (no Ctrl/Alt/Meta) and gamepad
    east or Start by keys (Return focused), right click in the canvas by mouse (nothing
    focused). Those inputs are consumed; everything else passes to the host."""

    def __init__(self, shell: "GameShell") -> None:
        self.shell = shell
        self.reader = NavReader()

    def handle_event(self, event: UiEvent, *, box_shown: bool) -> bool:
        nav = self.reader.read(event, dev=False)
        if nav not in (Nav.BACK, Nav.START):
            return False
        mouse = event.type == pygame.MOUSEBUTTONDOWN
        self.shell.open_game_menu(InputKind.MOUSE if mouse else InputKind.KEYS)
        return True

    def update(self, dt: float, *, frozen: bool) -> None:
        pass

    def draw(self, canvas: Canvas, *, box_shown: bool) -> None:
        pass


__all__ = ["GameMenuKeys", "GameMenuScreen"]

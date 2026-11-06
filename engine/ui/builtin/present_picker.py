"""``PresentScreen``: the item picker a menu's ``present:`` option opens (F64
SPEC-present; F21's ``CodexView`` in pick mode, as F25 presents evidence).

Why this module exists: at a menu with ``present:`` the player may show any item they hold.
The picker is F21's list (items only, with the detail pane and its pick button), so the bag
looks and works the same everywhere; this screen is its host over the menu.

- **Look.** The scene under it captured and dimmed (``menu.dim_*``, as the game menu); one
  panel the size of the game menu's content panel, centred: the heading (the
  ``present_choice`` word without its "…") at the top, the ``CodexView`` in the body, and
  Back under it at the left.
- **Input.** F10's, as every ``MenuScreen``: the view's own keys, Page Up / Page Down and a
  wheel the widgets didn't use go to the view. Back (the button, Esc, right click, east)
  closes the picker and the menu waits again; nothing in the story changes. The pick button
  (``present_pick``) closes it and then calls ``on_pick(item)``.
- **The menu under it** is not top while the picker is open, so its guard and a timed
  menu's countdown wait (as under the game menu).
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from engine.ui.backdrop import CapturedBackdrop
from engine.ui.builtin.codex_page import CodexFilter, CodexView, PickAction
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import CANVAS_W, PAGE_BODY, PAGE_HEADING, button_height
from engine.ui.menu_screen import MenuScreen
from engine.ui.nav import InputKind, Nav
from engine.ui.widgets import Button

if TYPE_CHECKING:
    from engine.ui.builtin.codex_page import CodexPort
    from engine.ui.paint import Painter

PANEL_W: Final = 872                       # the game menu's content panel
PANEL: Final = Box((CANVAS_W - PANEL_W) // 2, 24, PANEL_W, 672)
_SHIFT: Final = PANEL.x - 384              # the content panel's offsets, moved to the centre
HEADING_POS: Final = (PAGE_HEADING[0] + _SHIFT, PAGE_HEADING[1])
BODY: Final = Box(PAGE_BODY.x + _SHIFT, PAGE_BODY.y, PAGE_BODY.w, PAGE_BODY.h)
BACK_W: Final = 200
GAP: Final = 16
ITEM_KIND: Final = frozenset({"item"})


def heading_text(word: str) -> str:
    """The ``present_choice`` word as a heading: a trailing "…" or "..." dropped."""
    text = word.rstrip()
    for tail in ("…", "..."):
        if text.endswith(tail):
            text = text[:-len(tail)].rstrip()
    return text or word


class PresentScreen(MenuScreen):
    """The item picker over a menu. ``port`` is the codex's ``CodexPort``; ``on_pick`` gets
    the picked item's name after the screen has gone."""

    def __init__(self, shell, port: "CodexPort", on_pick: Callable[[str], None], *,
                 by: InputKind) -> None:
        self.on_pick = on_pick
        words = shell.words
        self.view = CodexView(port, ui=shell, filter=CodexFilter(kinds=ITEM_KIND),
                              pick=PickAction(words.get("present_pick"), self._picked),
                              scope=lambda: self.scope)
        self.back_button = Button(lambda: words.get("back"), self.back)
        self.view_box = BODY
        cfg = shell.theme.cfg
        backdrop = CapturedBackdrop(shell.assets, cfg.menu.dim_color, cfg.menu.dim_opacity,
                                    keep_scene=False)
        super().__init__(shell, by=by, backdrop=backdrop)

    # -- layout --

    def build(self) -> None:
        cfg = self.shell.theme.cfg
        scale = self.painter.text_scale()
        bh = button_height(cfg.button.text_size, scale=scale, minimum=cfg.button.height)
        self.view_box = Box(BODY.x, BODY.y, BODY.w, BODY.h - bh - GAP)
        self.back_button.box = Box(BODY.x, BODY.bottom - bh, BACK_W, bh)
        groups = self.view.build(self.view_box, scale)
        listed = self.view.default_widget()
        # Back joins the entry list's group, so Down from the last row reaches it.
        joined = [FocusGroup([*group.widgets, self.back_button], column=group.column)
                  if listed is not None and listed in group.widgets else group
                  for group in groups]
        if listed is None:
            joined.append(FocusGroup([self.back_button]))
        self.scope.set_groups(joined)
        self.scope.default_widget = listed or self.back_button
        self.revision += 1

    def layer_box(self) -> Box:
        return PANEL

    # -- actions --

    def _picked(self, name: str) -> None:
        self.close(then=lambda: self.on_pick(name))

    def unused_nav(self, nav: Nav) -> bool:
        if nav not in (Nav.PAGE_UP, Nav.PAGE_DOWN):
            return False
        return self.view.on_nav(nav)

    def unused_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        if kind in ("down", "wheel") and not self.view_box.contains(pos):
            return False
        return self.view.on_mouse(kind, pos, notches=notches)

    # -- frame --

    def on_update(self, dt: float) -> None:
        self.view.update(dt)
        if self.view.groups_changed:
            self.build()

    def draw_content(self, p: "Painter") -> None:
        p.panel(PANEL)
        p.heading(heading_text(self.shell.words.get("present_choice")), HEADING_POS)
        self.view.draw(p.canvas, p)
        self.draw_widgets(p)


__all__ = ["PANEL", "PresentScreen", "heading_text"]

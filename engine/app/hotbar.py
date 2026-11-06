"""``install_hotbar``: the hotbar in the status corner and every way to use an item (F64
round 2, specs/F64-items/SPEC.md "Round 2: Use and the hotbar").

Why this module exists: the runtime decides whether an item may be used and runs its scene
(``runtime/itemuse.py``), but the player asks from two places: the bag's Use button and the
hotbar's slots (number keys, a click, a gamepad). ``ItemUser`` is the one door for both, and
``Hotbar`` keeps the corner in line with ``show hotbar``.

- **ItemUser.request(name, by)**: the runtime's rule (``itemuse.why_not``) plus the app's own:
  the line must be shown in full (``line_ready``: not typing, not stopped at a ``{w}``, not
  a page with more after it). Refused: a short notice ("Not now", ``[words] use_not_now``)
  when the item has a scene but this isn't the moment; nothing for an empty slot. Allowed:
  the game menu closes (the bag's Use) and ``UseItem(name, line)`` goes to the story.
- **The slots** (``slots``): ``[hotbar] items`` slot by slot when set (canonical names; a
  name that is no item stays an empty slot: W308 said so at load), else the held items that
  have a Use scene in bag order, up to ``[hotbar] slots``. A slot whose item isn't held is
  empty. Each slot shows the item's picture (its ``image``), its title's letters otherwise,
  and a counted item's count.
- **Hotbar** is a corner source (``StatusCorner.add_source``), as ``MeterCorner``: once a
  frame it adds the item while ``codex.bar_shown()`` (fading in) and removes it otherwise;
  ``reset`` (a shell in-game reset: New Game, the title, after a load) drops it at once so
  the next frame refills it as a cut. Place: ``[hotbar] place``, else bottom left.
- **HotbarKeys** (an ``InGameOverlay`` on the textbox, so it sees input only while an
  in-game screen is on top, never under a menu): keys 1 to 8 and the keypad's use slot n
  while the hotbar is on screen; a left click on a slot uses it (and never advances the
  line); on a gamepad, X picks the slots (the first is ringed), left and right move, A uses
  the ringed slot, B or X leaves. While the slots are picked they take the gamepad's A, so a
  slot is never used by accident.

Reduce motion: the corner's fades are cuts (F61); the hotbar adds no motion of its own.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Final

import pygame

from engine.core.kits import hotbar_word
from engine.render.typewriter import TypeState
from engine.runtime import itemuse
from engine.runtime.interpreter import Status
from engine.runtime.itemuse import UseItem
from engine.runtime.character import canonical_name     # via runtime (07 I-7)
from engine.ui.hotbaritem import HotbarItem, HotbarSlot
from engine.ui.input import UiEvent
from engine.ui.nav import InputKind
from engine.ui.statuscorner import reserved_areas

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.app.codex import AppCodexPort
    from engine.render.canvas import Canvas
    from engine.runtime.interpreter import Interpreter

KEY: Final = ("hotbar",)                    # the corner key
DEFAULT_PLACE: Final = "bottom_left"
NUMBER_KEYS: Final = {**{getattr(pygame, f"K_{n}"): n for n in range(1, 9)},
                      **{getattr(pygame, f"K_KP{n}"): n for n in range(1, 9)}}
_BLOCKING_MODS: Final = pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META


def line_ready(textbox: object) -> bool:
    """The app's half of the rule: the waiting line is shown in full (or there is no text
    box to ask)."""
    typer = getattr(textbox, "typer", None)
    if typer is None or getattr(textbox, "line", None) is None:
        return True
    return typer.state is TypeState.COMPLETE


class ItemUser:
    """The one door for using an item (module docstring). ``interp`` gives the live
    interpreter (F39's reload is followed)."""

    def __init__(self, app: "App", interp: Callable[[], "Interpreter"]) -> None:
        self.app = app
        self.interp = interp

    def _textbox(self) -> object:
        return getattr(getattr(self.app, "shell", None), "ports", None) and \
            self.app.shell.ports.textbox

    def has_use(self, name: str) -> bool:
        """``name`` is an item with a Use scene (the bag shows its Use button)."""
        return itemuse.scene_of(self.interp(), name) is not None

    def can_use(self, name: str) -> bool:
        """``name`` can be used right now (the bag's Use button is enabled)."""
        return itemuse.why_not(self.interp(), name) is None and line_ready(self._textbox())

    def request(self, name: str, by: InputKind = InputKind.KEYS) -> bool:
        """Use ``name`` if the rule allows (module docstring); True when the use was sent."""
        interp = self.interp()
        reason = itemuse.why_not(interp, name)
        if reason is None and not line_ready(self._textbox()):
            reason = itemuse.NOT_NOW
        shell = getattr(self.app, "shell", None)
        if reason is not None:
            if reason == itemuse.NOT_NOW and shell is not None:
                shell.notify(shell.words.get("use_not_now"))
            return False
        if shell is not None:
            shell.close_game_menu()
        self.app.story.post(UseItem(name, interp.current.sid))   # type: ignore[union-attr]
        return True


class Hotbar:
    """The hotbar's side of the corner and its slots (module docstring)."""

    def __init__(self, app: "App", interp: Callable[[], "Interpreter"], user: ItemUser,
                 port: "AppCodexPort") -> None:
        self.app = app
        self.interp = interp
        self.user = user
        self.port = port
        self.focus: int | None = None           # the gamepad's ringed slot
        self.item = HotbarItem(self.slots, focus=lambda: self.focus)
        self._cut = True

    @property
    def corner(self):
        return self.app.shell.corner

    def place(self) -> str:
        place = getattr(self.app.config.hotbar, "place", None)
        return place if isinstance(place, str) else DEFAULT_PLACE

    def names(self) -> tuple[str | None, ...]:
        """What each slot holds now (None: empty), ``[hotbar] slots`` of them."""
        cfg = self.app.config.hotbar
        n = cfg.slots
        interp = self.interp()
        if cfg.items:
            wanted = [canonical_name(name) for name in cfg.items[:n]]
            names = [name if interp.codex.index.is_item(name) and interp.codex.has(name)
                     else None for name in wanted]
        else:
            names = list(itemuse.usable_items(interp)[:n])
        return tuple(names + [None] * (n - len(names)))

    def slots(self) -> tuple[HotbarSlot, ...]:
        interp = self.interp()
        index = interp.codex.index
        out = []
        for i, name in enumerate(self.names()):
            entry = index.get(name) if name is not None else None
            if entry is None:
                out.append(HotbarSlot(str(i + 1)))
                continue
            picture = self.port.picture(entry.image) if entry.image is not None else None
            count = interp.codex.count(entry.name) if entry.counted else None
            out.append(HotbarSlot(str(i + 1), entry.name, entry.title, count, picture))
        return tuple(out)

    def slot_of(self, name: str) -> int | None:
        """The 1-based slot ``name`` sits in, or None (the bag's hint)."""
        if not self.shown():
            return None
        names = self.names()
        return names.index(name) + 1 if name in names else None

    def word(self) -> str:
        """The hotbar's name: ``[hotbar] word``, else the kit's, else ``[words] hotbar``."""
        return hotbar_word(self.app.config) or self.app.shell.words.get("hotbar")

    def shown(self) -> bool:
        interp = self.interp()
        return interp.status is not Status.IDLE and interp.codex.bar_shown()

    def on_screen(self) -> bool:
        """The hotbar is drawn now: shown, the corner is (in game, box shown), and it fits
        its corner (in NVL the column may leave no room: then only the bag's Use works)."""
        shell = self.app.shell
        if not (self.shown() and KEY in shell.corner.keys() and shell.corner_shown()):
            return False
        reserved = reserved_areas(shell.ports.textbox, getattr(shell, "quick_menu", None))
        return KEY not in shell.corner.overflow(reserved)     # it fits its corner

    def use_slot(self, index: int, by: InputKind) -> bool:
        """Use slot ``index`` (0-based); an empty slot does nothing."""
        names = self.names()
        if not 0 <= index < len(names) or names[index] is None:
            return False
        return self.user.request(names[index], by)   # type: ignore[arg-type]

    def sync(self) -> None:
        corner, cut = self.corner, self._cut
        self._cut = False
        present = KEY in corner.keys()
        if self.shown():
            if not present or corner.item(KEY) is not self.item:
                corner.set_item(KEY, self.place(), self.item, fade=not cut)
        else:
            self.focus = None
            if present:
                corner.remove_item(KEY, fade=not cut)

    def reset(self) -> None:
        """A shell in-game reset: drop the hotbar at once; the next frame refills it."""
        if KEY in self.corner.keys():
            self.corner.remove_item(KEY, fade=False)
        self.focus = None
        self._cut = True


class HotbarKeys:
    """The ``InGameOverlay`` for the hotbar's input (module docstring)."""

    def __init__(self, hotbar: Hotbar) -> None:
        self.hotbar = hotbar

    def handle_event(self, event: UiEvent, *, box_shown: bool) -> bool:
        hotbar = self.hotbar
        if not box_shown or not hotbar.on_screen():
            hotbar.focus = None
            return False
        raw = event.raw
        kind = raw.type
        if kind == pygame.KEYDOWN:
            n = NUMBER_KEYS.get(getattr(raw, "key", None))
            if n is None or getattr(raw, "mod", 0) & _BLOCKING_MODS \
                    or getattr(raw, "repeat", False):
                return False
            if n > len(hotbar.names()):
                return False
            hotbar.use_slot(n - 1, InputKind.KEYS)
            return True
        if kind == pygame.MOUSEBUTTONDOWN and getattr(raw, "button", 0) == 1:
            pos = event.canvas_pos
            if not event.in_canvas or pos is None:
                return False
            for i, box in enumerate(hotbar.item.boxes):
                if box.x <= pos[0] < box.right and box.y <= pos[1] < box.bottom:
                    hotbar.use_slot(i, InputKind.MOUSE)
                    return True                     # a slot click never advances
            return False
        if kind == pygame.CONTROLLERBUTTONDOWN:
            return self._pad(getattr(raw, "button", -1))
        return False

    def _pad(self, button: int) -> bool:
        hotbar = self.hotbar
        n = len(hotbar.names())
        if hotbar.focus is None:
            if button == pygame.CONTROLLER_BUTTON_X and n:
                hotbar.focus = 0
                return True
            return False
        if button in (pygame.CONTROLLER_BUTTON_X, pygame.CONTROLLER_BUTTON_B):
            hotbar.focus = None
        elif button == pygame.CONTROLLER_BUTTON_DPAD_LEFT:
            hotbar.focus = (hotbar.focus - 1) % n
        elif button == pygame.CONTROLLER_BUTTON_DPAD_RIGHT:
            hotbar.focus = (hotbar.focus + 1) % n
        elif button == pygame.CONTROLLER_BUTTON_A:
            index = hotbar.focus
            if hotbar.use_slot(index, InputKind.KEYS):
                hotbar.focus = None
        return True                                 # the slots take the pad while picked

    def update(self, dt: float, *, frozen: bool) -> None:
        pass

    def draw(self, canvas: "Canvas", *, box_shown: bool) -> None:
        pass


def install_hotbar(app: "App", interp: Callable[[], "Interpreter"],
                   port: "AppCodexPort") -> tuple[ItemUser, Hotbar | None]:
    """Every launch: the item user; with a shell and its corner, the hotbar's corner source,
    its in-game reset and its keys on the text box."""
    user = ItemUser(app, interp)
    shell = getattr(app, "shell", None)
    corner = getattr(shell, "corner", None)
    if corner is None:
        return user, None
    hotbar = Hotbar(app, interp, user, port)
    corner.add_source(hotbar.sync)
    shell.add_in_game_reset(hotbar.reset)
    textbox = shell.ports.textbox
    if textbox is not None:
        textbox.add_overlay(HotbarKeys(hotbar))
    return user, hotbar


__all__ = ["DEFAULT_PLACE", "Hotbar", "HotbarKeys", "ItemUser", "KEY", "NUMBER_KEYS",
           "install_hotbar", "line_ready"]

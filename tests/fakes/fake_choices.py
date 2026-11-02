"""Fake choices (F10 ``06`` §0.4) standing in for F07 until it is built.

``FakeChoiceController`` is what F07's ``ChoiceController`` offers F10: ``set_floor(fn)``
(C6, I-3), ``close()`` (I-8's reset), and ``show()`` pushing one ``FakeChoiceScreen`` above
the textbox. The screen is ``in_game`` with F07's three buttons at AC-F07-24's positions
(x 240–1040, tops 130, 201, 272, 59 tall). Per C7 it returns False for a left press outside
its buttons, every release, and motion; per C8 its hidden state is ``textbox.hidden``, read
every time (no private copy): while hidden a left press, Enter, or Space only shows it again
(``set_hidden(False)``), and H hides it with the box. A pick records ``chosen`` (F07's
``Choose``) and closes the screen. Down/Up move a key focus; Enter picks it.
"""

import pygame

from engine.ui.focus import Box
from engine.ui.input import UiEvent
from engine.ui.screen import Screen

BUTTONS = (Box(240, 130, 800, 59), Box(240, 201, 800, 59), Box(240, 272, 800, 59))
KEYS = ("c1", "c2", "c3")
NORMAL = (0x40, 0x60, 0x80)
FOCUSED = (0x80, 0x40, 0x60)


class FakeChoiceScreen(Screen):
    opaque = False
    in_game = True

    def __init__(self, controller: "FakeChoiceController") -> None:
        self.controller = controller
        self.focus: int | None = None
        self.floor_at_open = controller.floor()

    @property
    def textbox(self):
        return self.controller.textbox

    @property
    def hidden(self) -> bool:
        return bool(self.textbox.hidden)                  # C8: read every time

    def _hit(self, pos) -> int | None:
        for index, box in enumerate(BUTTONS):
            if box.contains(pos):
                return index
        return None

    def handle_event(self, event: UiEvent) -> bool:
        raw = event.raw
        kind = raw.type
        if self.hidden:
            shows = (kind == pygame.MOUSEBUTTONDOWN and getattr(raw, "button", 0) == 1
                     and event.in_canvas) or (
                kind == pygame.KEYDOWN and raw.key in (pygame.K_RETURN, pygame.K_SPACE,
                                                       pygame.K_h))
            if shows:
                self.textbox.set_hidden(False)
                return True
            return False
        if kind == pygame.MOUSEMOTION and event.in_canvas and event.canvas_pos is not None:
            index = self._hit(event.canvas_pos)
            if index is not None:
                self.focus = index
            return False                                  # C7: motion goes on
        if kind == pygame.MOUSEBUTTONDOWN and getattr(raw, "button", 0) == 1:
            if not event.in_canvas or event.canvas_pos is None:
                return False
            index = self._hit(event.canvas_pos)
            if index is None:
                return False                              # C7: off the buttons goes on
            self.controller.pick(index)
            return True
        if kind == pygame.KEYDOWN:
            if raw.key == pygame.K_DOWN:
                self.focus = 0 if self.focus is None else (self.focus + 1) % len(BUTTONS)
                return True
            if raw.key == pygame.K_UP:
                self.focus = len(BUTTONS) - 1 if self.focus is None \
                    else (self.focus - 1) % len(BUTTONS)
                return True
            if raw.key in (pygame.K_RETURN, pygame.K_SPACE):
                if self.focus is None:
                    self.focus = 0
                else:
                    self.controller.pick(self.focus)
                return True
            if raw.key == pygame.K_h:
                self.textbox.set_hidden(True)
                return True
        return False                                      # releases, Esc, right click, wheel

    def draw(self, canvas) -> None:
        if self.hidden:
            return
        for index, box in enumerate(BUTTONS):
            canvas.fill(FOCUSED if index == self.focus else NORMAL,
                        (box.x, box.y, box.w, box.h))


class FakeChoiceController:
    """``app.choices`` for tests: the F07 seams F10 uses."""

    def __init__(self, app) -> None:
        self.app = app
        self.textbox = app.textbox
        self.floor = lambda: 704
        self.floor_set = 0
        self.screen: FakeChoiceScreen | None = None
        self.chosen: list[str] = []
        self.closes = 0

    def set_floor(self, fn) -> None:
        self.floor = fn
        self.floor_set += 1

    def show(self) -> FakeChoiceScreen:
        self.close()
        self.screen = FakeChoiceScreen(self)
        self.app.screens.push(self.screen)
        return self.screen

    def pick(self, index: int) -> None:
        self.chosen.append(KEYS[index])
        self.close()

    def close(self) -> None:
        self.closes += 1
        screen, self.screen = self.screen, None
        if screen is not None:
            self.app.screens.remove(screen)


__all__ = ["BUTTONS", "FOCUSED", "KEYS", "NORMAL", "FakeChoiceController", "FakeChoiceScreen"]

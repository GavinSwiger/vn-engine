"""``UiEvent``: a pygame event as screens see it, with the mouse position in canvas units.

Why this module exists: screens lay out everything in canvas units (PR-F01-21), so the
mouse position they receive must be in canvas units too, and a click in a letterbox bar
must be recognizable (PR-F01-24). ``engine/app/input.py`` builds these from raw pygame
events; screens (F10 menus, F05 text box) only ever read them.
"""

from dataclasses import dataclass

import pygame


@dataclass(frozen=True)
class UiEvent:
    raw: "pygame.event.Event"
    canvas_pos: tuple[int, int] | None    # set for MOUSEMOTION/BUTTONDOWN/BUTTONUP/MOUSEWHEEL
    in_canvas: bool                       # False for positions inside the letterbox bars

    @property
    def type(self) -> int:
        """The raw event's type (``pygame.KEYDOWN``, …)."""
        return self.raw.type

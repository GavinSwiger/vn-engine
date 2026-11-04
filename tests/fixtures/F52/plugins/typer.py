"""F52's test plugins: Typer (API 1.4, a ``TextField`` and an OK button in ``ctx.scope``) and
OldTyper (API 1.3, reads ``TEXTINPUT`` itself, as a plugin made before F52 would). Both record
every event ``handle_event`` sees in ``seen`` (raw event types)."""

import pygame

from engine.minigames.api import Minigame, Outcome, TextField, register
from engine.ui.focus import Box, FocusGroup
from engine.ui.widgets import Button


@register
class Typer(Minigame):
    name = "typer"
    api = "1.4"
    test_outcome = Outcome("test")

    def start(self, ctx):
        self.ctx = ctx
        self.seen = []
        self.changes = []
        self.field = TextField(max_length=20, placeholder="Name", on_change=self.changes.append,
                               on_submit=ctx.finish)
        self.ok = Button(lambda: "OK", lambda: ctx.finish("ok"))
        ctx.scope.set_groups([FocusGroup([self.field, self.ok], column=True)])
        ctx.scope.set_default(self.field)

    def layout(self, area):
        self.field.box = Box(area.x + 100, area.y + 100, 600, 56)
        self.ok.box = Box(area.x + 100, area.y + 200, 200, 56)

    def handle_event(self, ev):
        self.seen.append(ev.ui.raw.type)
        return False


@register
class OldTyper(Minigame):
    name = "oldtyper"
    api = "1.3"
    test_outcome = Outcome("test")

    def start(self, ctx):
        self.ctx = ctx
        self.seen = []
        self.text = ""

    def handle_event(self, ev):
        self.seen.append(ev.ui.raw.type)
        if ev.ui.raw.type == pygame.TEXTINPUT:
            self.text += ev.ui.raw.text
            return True
        return False

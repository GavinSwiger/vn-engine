"""The Bare plugin (F23 06 §5): only a name and a handle_event that finishes with 1."""

from engine.minigames.api import Minigame, register


@register
class Bare(Minigame):
    name = "bare"

    def start(self, ctx):
        self.ctx = ctx

    def handle_event(self, ev):
        self.ctx.finish(1)
        return True

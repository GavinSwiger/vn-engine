"""Lantern memory: turn over two lanterns at a time and find the pairs.

The example game's minigame plugin, and the one docs/minigames.md walks through
("Writing a minigame"). In the script:

    minigame lantern_memory pairs=6 into turns

The result is the number of turns the player took. Clearing the board also gives Hana
one point.
"""

from engine.minigames.api import Arg, Minigame, Outcome, add_points, register
from engine.ui.focus import Box, FocusGroup
from engine.ui.widgets import Button

PICTURES = ["Moon", "Crane", "Fish", "Star", "Bell", "Kite", "Fan", "Drum"]
COLUMNS = 4
CARD_W, CARD_H, GAP = 200, 110, 24


@register
class LanternMemory(Minigame):
    name = "lantern_memory"
    title = "Lantern Memory"
    args = {"pairs": Arg(), "hints": Arg(default=False)}
    test_outcome = Outcome(9, (add_points("hana", 1),))
    words = {"hint": "Find the matching lanterns."}

    def check_args(self, args):
        pairs = args["pairs"]
        if type(pairs) is not int or not 2 <= pairs <= len(PICTURES):
            return f"pairs must be a whole number from 2 to {len(PICTURES)}"
        if type(args["hints"]) is not bool:
            return "hints must be True or False"
        return None

    def start(self, ctx):
        self.ctx = ctx
        self.cards = ctx.random.shuffle(PICTURES[:ctx.args["pairs"]] * 2)
        self.up = []                  # the one or two cards turned face up this turn
        self.found = set()            # the cards already matched
        self.turns = 0
        self.buttons = [Button(lambda i=i: self.face(i), lambda i=i: self.pick(i))
                        for i in range(len(self.cards))]
        self.layout(ctx.area)
        ctx.scope.set_groups([FocusGroup(self.buttons)])
        ctx.scope.set_default(self.buttons[0])
        ctx.heading(True)
        self.show_hint()

    def layout(self, area):
        rows = (len(self.cards) + COLUMNS - 1) // COLUMNS
        left = area.x + (area.w - (COLUMNS * CARD_W + (COLUMNS - 1) * GAP)) / 2
        top = area.y + (area.h - (rows * CARD_H + (rows - 1) * GAP)) / 2
        for i, button in enumerate(self.buttons):
            row, column = divmod(i, COLUMNS)
            button.box = Box(left + column * (CARD_W + GAP), top + row * (CARD_H + GAP),
                             CARD_W, CARD_H)

    def face(self, i):
        return self.cards[i] if i in self.found or i in self.up else "?"

    def pick(self, i):
        if i in self.found or i in self.up:
            return
        if len(self.up) == 2:         # the last two didn't match: turn them back down
            self.up = []
        self.up.append(i)
        if len(self.up) == 2:
            self.turns += 1
            first, second = self.up
            if self.cards[first] == self.cards[second]:
                self.found.update(self.up)
                self.up = []
        if len(self.found) == len(self.cards):
            self.ctx.points.add("hana", 1)
            self.ctx.finish(self.turns)
            return
        self.show_hint()

    def show_hint(self):
        hint = self.ctx.words.mine("hint")
        if self.ctx.args["hints"]:
            left = (len(self.cards) - len(self.found)) // 2
            hint += f" Pairs left: {left}. Turns: {self.turns}."
        self.ctx.hint(hint)

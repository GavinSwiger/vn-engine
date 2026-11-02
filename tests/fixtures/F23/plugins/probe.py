"""The Probe plugin (F23 06 §5): the real plugin form of SIGS' ``probe``.

Step 3a built its declarations; step 4 adds the ``behavior`` object the host tests drive,
reached through the registry (``registry.get("probe").cls.behavior``): which inputs it
uses, where it raises (line 88) or loops (line 120), requests to make, when to finish and
with what, ``grid`` mode (4 F10 buttons, 2×2, each finishing with its index), and a
used-input counter drawn as digits. It records every call and the summed ``dt``.
"""

from engine.minigames.api import Arg, Minigame, Outcome, add_points, register
from engine.render.text import FontSpec
from engine.ui.focus import Box, FocusGroup
from engine.ui.widgets import Button


class Behavior:
    """What the Probe does; tests set fields, then start a session."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.calls = []            # (method, argument)
        self.dt = 0.0
        self.use_all = False       # handle_event uses every event
        self.use = set()           # event types or Navs it uses
        self.raise_in = None       # a method name: ZeroDivisionError at line 88
        self.loop_in = None        # a method name: while True at line 120
        self.requests = []         # (handle, method, args) made in start
        self.heading = None        # heading text (True: the display title)
        self.hint = None
        self.cue = None
        self.grid = False
        self.counter = 0           # used presses, drawn as digits
        self.on_start = None       # fn(ctx), after the rest of start
        self.on_event = None       # fn(ctx, ev) -> used, instead of the use rules
        self.ctx = None
        self.area = None
        self.buttons = []


behavior = Behavior()


def hook(name):
    if behavior.raise_in == name:
        boom()
    if behavior.loop_in == name:
        spin()


#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
def boom():
    return 1 / 0                          # line 88: AC-F23-44


#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
def spin():
    while True:                           # line 120: AC-F23-45
        pass


@register
class Probe(Minigame):
    name = "probe"
    title = "Probe game"
    args = {"pairs": Arg(), "hints": Arg(default=False), "label": Arg(default="")}
    test_outcome = Outcome(9, (add_points("hana", 1),))
    skipped_outcome = Outcome("skipped")
    tokens = {"card.back_color": "#203040"}
    words = {"hint": "Find the pairs"}

    def check_args(self, args):
        if type(args.get("pairs")) is not int or not 1 <= args["pairs"] <= 12:
            return "pairs must be a whole number from 1 to 12"
        return None

    def start(self, ctx):
        b = behavior
        b.calls.append(("start", None))
        b.ctx = ctx
        hook("start")
        if b.heading is not None:
            ctx.heading(True, None if b.heading is True else b.heading)
        if b.hint is not None:
            ctx.hint(b.hint)
        if b.cue is not None:
            ctx.cue_point(b.cue)
        if b.grid:
            b.buttons = [Button(lambda i=i: f"B{i}", lambda i=i: ctx.finish(i),
                                box=Box(380 + (i % 2) * 280, 250 + (i // 2) * 120, 240, 80))
                         for i in range(4)]
            ctx.scope.set_groups([FocusGroup(b.buttons)])
            ctx.scope.set_default(b.buttons[0])
        for handle, method, args in b.requests:
            getattr(getattr(ctx, handle), method)(*args)
        if b.on_start is not None:
            b.on_start(ctx)

    def handle_event(self, ev):
        b = behavior
        b.calls.append(("handle_event", ev))
        hook("handle_event")
        if b.on_event is not None:
            return b.on_event(b.ctx, ev)
        used = b.use_all or ev.ui.type in b.use or (ev.nav is not None and ev.nav in b.use)
        if used:
            b.counter += 1
        return used

    def update(self, dt):
        behavior.calls.append(("update", dt))
        behavior.dt += dt
        hook("update")

    def draw(self, canvas):
        behavior.calls.append(("draw", None))
        hook("draw")
        canvas.draw_text(str(behavior.counter), FontSpec(None, 48), (0, 0, 0), (640, 200),
                         anchor="center")

    def layout(self, area):
        behavior.calls.append(("layout", area))
        behavior.area = area
        hook("layout")

    def settings_changed(self, s):
        behavior.calls.append(("settings_changed", s))
        hook("settings_changed")

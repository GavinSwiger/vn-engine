"""``ask_text`` (F52 ``01`` §5, §6.7, §8): the bundled minigame that asks the player to type an
answer, such as their name, so an author can do it with no code.

```
minigame ask_text prompt="What's your name?" max_length=12 allowed="name" into player_name
```

- **Screen** (§6.7): a ``panel.*`` panel centred at (640, 300), 760 wide, padding 32: the
  question (panel text, at most 3 lines), 24 below it the field (696 wide, an API 1.4
  ``TextField``) and its note, then OK, right-aligned, 24 below. The heading is off; the
  hint bar shows ``hint``. The field is the default widget, so it is focused (and SDL text
  input is on) at once, whatever input opened the minigame.
- **Answer.** Enter or OK finishes with the text trimmed at both ends; an empty answer
  without ``can_be_empty`` shows the ``empty`` note and waits. ``hide`` draws dots.
- **Rules** (refusals, outcomes, trimming) are ``ask_rules``'. The answer is never logged;
  it reaches the story only as the result (PR-F52-11). Not skippable: the story needs it.

Presentation-only: nothing here is saved. A save while typing loads back with ``default``,
and rollback before the line asks again (F23's checkpoint).
Imports: ``ask_rules``, ``engine.minigames.api``, and F10's public widget kit only.
"""

import dataclasses
from typing import TYPE_CHECKING, Final

from engine.minigames.api import Arg, Minigame, Outcome, StoryNames, TextField
from engine.minigames.bundled import ask_rules as rules
from engine.render.text import text_width
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import button_height, pitch, wrap_text
from engine.ui.widgets import Button

if TYPE_CHECKING:
    from engine.minigames.api import Context, PlayerSettings
    from engine.render.canvas import Canvas

# [words.plugin.ask_text] (§8).
WORDS: Final = {
    "title": "Your answer",
    "prompt": "Type your answer.",
    "placeholder": "Type here",
    "ok": "OK",
    "empty": "Type something first.",
    "hint": "Type, then press Enter. With a controller, press A for the keyboard.",
}

CENTER: Final = (640, 300)
PANEL_W: Final = 760
PAD: Final = 32
GAP: Final = 24
FIELD_W: Final = 696
PROMPT_LINES: Final = 3
FIELD_TEXT: Final = 28              # the field and OK at [theme.button]'s default size
PANEL_TEXT: Final = 28
OK_MIN_W: Final = 160
OK_PAD: Final = 64


class AskText(Minigame):
    name = "ask_text"
    title = "Your answer"
    api = "1.4"
    over_stage = True
    args = {key: Arg(default=value) for key, value in rules.DEFAULTS.items()}
    test_outcome = Outcome(rules.TEST_TEXT)
    skipped_outcome = None
    words = WORDS

    # -- API 1.1 hooks (fresh, never-started instances) --

    def check_args(self, args: dict) -> str | None:
        return rules.problem(args)

    def outcome_for(self, kind: str, args: dict, story: StoryNames) -> Outcome | None:
        return rules.fixed_outcome(kind, args)

    # -- the session --

    def start(self, ctx: "Context") -> None:
        self.ctx = ctx
        args = {**rules.DEFAULTS, **dict(ctx.args)}
        words = ctx.words
        self.prompt = args["prompt"] if args["prompt"] is not None else words.mine("prompt")
        self.can_be_empty = bool(args["can_be_empty"])
        self.scale = float(ctx.settings.text_scale)
        self.field = TextField(text=args["default"] or "", max_length=args["max_length"],
                               allowed=args["allowed"], mask=args["hide"],
                               placeholder=words.mine("placeholder"), on_submit=self._answer)
        self.ok = Button(lambda: words.mine("ok"), self._answer)
        self.lines: list[str] = [self.prompt]
        self.panel = Box(0, 0, 0, 0)
        self._laid: tuple | None = None
        ctx.scope.set_groups([FocusGroup([self.field, self.ok])])
        ctx.scope.set_default(self.field)
        ctx.heading(False)
        ctx.hint(words.mine("hint"))
        self._layout(None)

    def settings_changed(self, s: "PlayerSettings") -> None:
        self.scale = float(s.text_scale)
        self._layout(None)

    def layout(self, area) -> None:
        self._layout(None)

    def _answer(self, *_ignored: object) -> None:
        answer = rules.result_of(self.field.text)
        if not answer and not self.can_be_empty:
            self.field.show_note(self.ctx.words.mine("empty"))
            return
        self.ctx.finish(answer)

    # -- layout and drawing --

    def _sizes(self) -> tuple[int, int, int]:
        s = self.scale
        panel = max(1, round(PANEL_TEXT * s))
        field = max(1, round(FIELD_TEXT * s))
        return panel, field, button_height(FIELD_TEXT, scale=s)

    def _layout(self, canvas: "Canvas | None") -> None:
        """The panel, the question's lines, the field and OK (§6.7)."""
        size, field_size, ok_h = self._sizes()
        if canvas is not None:
            font = self.ctx.font(None, size)

            def measure(text: str, at: int) -> float:
                handle = canvas.font_handle(dataclasses.replace(font, size=at), at)
                return float(text_width(handle.font, text))
            key = (self.prompt, size, field_size)
            if key == self._laid:
                return
            self._laid = key
            lines = wrap_text(self.prompt, FIELD_W, size, measure)
            ok_w = max(OK_MIN_W, measure(self.ctx.words.mine("ok"), field_size) + OK_PAD)
        else:
            self._laid = None                          # measured again at the next draw
            per_line = max(1, int(FIELD_W / (size * 0.5)))
            lines = [self.prompt[i:i + per_line] for i in range(0, len(self.prompt), per_line)]
            ok_w = OK_MIN_W
        self.lines = lines[:PROMPT_LINES] or [""]
        field_h = max(56, pitch(field_size) + 16)
        prompt_h = len(self.lines) * pitch(size)
        height = PAD + prompt_h + GAP + field_h + GAP + ok_h + PAD
        cx, cy = CENTER
        self.panel = Box(cx - PANEL_W / 2, cy - height / 2, PANEL_W, height)
        x = self.panel.x + PAD
        y = self.panel.y + PAD + prompt_h + GAP
        self.field.box = Box(x, y, FIELD_W, field_h)
        y += field_h + GAP
        self.ok.box = Box(self.panel.right - PAD - ok_w, y, ok_w, ok_h)

    def draw(self, canvas: "Canvas") -> None:
        self._layout(canvas)
        p = self.ctx.painter
        p.panel(self.panel)
        size = self._sizes()[0]
        font = self.ctx.font(None, size)
        color = self.ctx.theme.get("panel.text_color")
        step = pitch(size)
        y = self.panel.y + PAD
        for line in self.lines:
            canvas.draw_text(line, font, color, (self.panel.x + PAD, y))
            y += step


__all__ = ["AskText", "WORDS"]

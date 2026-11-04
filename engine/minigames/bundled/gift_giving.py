"""Gift giving (F54): a bundled minigame where the player gives a character an item they hold.
A gift table (characters × items) gives each gift a reaction, a meter change and a line.

Every rule is in ``gift_rules``; this module is the session (F54 SPEC §4.1, §5):

- **The picker.** F21's codex view of the held items (in ``categories``, if given), laid out
  as F25's picker, with **Give** as its pick word. **Not now** (with ``leave``) joins the
  list's focus group, as F25's Back does; Backspace, right click and gamepad B are Not now
  too. Not now finishes with None and changes nothing.
- **The card.** Give shows the speaker, the line and the verdict ("Hana loved it."), with
  Continue (focused by keys). An empty line and an empty verdict word skip the card.
- **The end.** Only at Continue (or Give, with no card): the item is taken when ``use_up``,
  ``to``'s meter changes by the gift's points when they aren't 0, and the result is the
  reaction word or the item's name (``result``). Skip Game and an abandoned run change
  nothing (F23's ledger).
- **Nothing to give.** With no held item the picker can show, a panel says ``nothing`` with
  Continue (shown even with ``leave=False``); the result is None; W285 in dev, once per text.
- **Look.** ``panel.*``, ``button.*`` and the codex view's tokens only; no motion of its own;
  no timing.

Presentation-only: a restore starts the picker again; nothing was taken or added.
"""

import dataclasses
from typing import TYPE_CHECKING, Any, Final

from engine.minigames.api import (Arg, CodexFilter, Minigame, Outcome, PickAction, PluginEvent,
                                  StoryNames)
from engine.minigames.bundled import gift_rules as rules
from engine.minigames.bundled.rule_text import fill
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import button_height, pitch, scaled
from engine.ui.nav import InputKind, Nav
from engine.ui.widgets import Button

if TYPE_CHECKING:
    from engine.minigames.api import Context, PlayerSettings
    from engine.render.canvas import Canvas

OWN: Final = "plugin.gift_giving."

# [theme.plugin.gift_giving] (SPEC §4.1).
TOKENS = {
    "line.text_size": rules.LINE_TEXT[0],
    "give_sound": "",
}

# [words.plugin.gift_giving] (SPEC §4.1). {name} is the speaker.
WORDS = {
    "title": "Gift",
    "hint": "Choose a gift for {name}.",
    "give": "Give",
    "not_now": "Not now",
    "nothing": "You have nothing to give.",
    "continue": "Continue",
    "loved": "{name} loved it.",
    "liked": "{name} liked it.",
    "neutral": "{name} accepted it.",
    "disliked": "{name} didn't like it.",
}

PICK, CARD, NOTHING = "pick", "card", "nothing"
WARN_MAX: Final = 100
_WARNED: set[str] = set()             # W285 texts logged this process (dev only)


class GiftGiving(Minigame):
    name = "gift_giving"
    title = "Gift"
    api = "1.1"
    over_stage = True
    args = {key: (Arg() if key in rules.REQUIRED else Arg(default=value))
            for key, value in rules.DEFAULTS.items()}
    # The static outcomes gate skippable (E271) and E279; outcome_for gives the real ones.
    test_outcome = Outcome(None)
    skipped_outcome = Outcome(None)
    tokens = TOKENS
    words = WORDS

    def check_args(self, args: dict) -> str | None:
        return rules.problem(args)

    def check_story(self, args: dict, story: StoryNames) -> str | None:
        return rules.story_problem(args, story)

    def outcome_for(self, kind: str, args: dict, story: StoryNames) -> Outcome | None:
        return rules.fixed_outcome(args)

    # -- the session --

    def start(self, ctx: "Context") -> None:
        self.ctx = ctx
        a = {**rules.DEFAULTS, **ctx.args}
        self.table = rules.parse(a)
        self.to: str = a["to"]
        self.speaker = rules.speaker_of(a)
        self.categories = a["categories"]
        self.use_up: bool = a["use_up"]
        self.leave: bool = a["leave"]
        self.result_kind: str = a["result"]
        self.word = {key: ctx.words.mine(key) for key in WORDS}
        mine = ctx.theme.mine
        self.line_size = rules.clamp_size(mine("line.text_size"), *rules.LINE_TEXT)
        self.give_sound = mine("give_sound")
        self.item: str | None = None
        self.gift: rules.Gift | None = None
        self.done = False
        self.last_kind = InputKind.MOUSE
        self.area = ctx.area
        self.view: Any = None
        self.picker: rules.PickerLayout | None = None
        self.card: Any = None
        self._lay_key: tuple | None = None
        self.not_now = Button(lambda: self.word["not_now"], self._not_now)
        self.continue_button = Button(lambda: self.word["continue"], self._continue)
        ctx.heading(True)
        ctx.hint(fill(self.word["hint"], name=self.speaker))
        shown = rules.givable(ctx.codex.items(), self.categories, ctx.story)
        if not shown:
            self.mode = NOTHING
            ctx.scope.set_groups([FocusGroup([self.continue_button])])
            ctx.scope.set_default(self.continue_button)
            if ctx.dev:
                text = rules.w285_text(self.to)
                if text not in _WARNED and len(_WARNED) < WARN_MAX:
                    _WARNED.add(text)
                    ctx.log.warning("%s", text, extra={"code": "W285"})
            return
        self.mode = PICK
        cats = None if self.categories is None else frozenset(self.categories)
        self.view = ctx.codex_view(filter=CodexFilter(kinds=frozenset({"item"}),
                                                      categories=cats),
                                   pick=PickAction(self.word["give"], self._picked))
        self._build_picker()

    def _build_picker(self) -> None:
        """Lay the picker out in the area, build the view, and join Not now to the list's
        group (F25's Back); focus by keys goes to the view's default widget."""
        ctx = self.ctx
        scale = ctx.painter.text_scale()
        lay = self.picker = rules.picker_layout((self.area.x, self.area.y, self.area.w,
                                                 self.area.h), button_h=button_height(scale=scale))
        self.not_now.box = Box(*lay.back)
        groups = self.view.build(Box(*lay.view), scale)
        listed = self.view.default_widget()
        extra = [self.not_now] if self.leave else []
        joined = [FocusGroup([*g.widgets, *extra], column=g.column)
                  if listed is not None and listed in g.widgets else g for g in groups]
        if listed is None and extra:
            joined.append(FocusGroup(extra))
        ctx.scope.set_groups(joined)
        target = listed or (self.not_now if self.leave else None)
        ctx.scope.set_default(target)
        self._lay_key = self._key()

    def _key(self) -> tuple:
        a = self.area
        return (a.x, a.y, a.w, a.h, self.ctx.painter.text_scale())

    # -- input --

    def handle_event(self, ev: PluginEvent) -> bool:
        ui = ev.ui
        if ui.canvas_pos is not None:
            self.last_kind = InputKind.MOUSE
        elif ev.nav is not None:
            self.last_kind = InputKind.KEYS
        if self.done:
            return False
        if self.mode == PICK and ev.nav is Nav.BACK and self.leave:
            self._not_now()
            return True
        return False

    def _picked(self, name: str) -> None:
        """Give: the card, or (no line and an empty verdict word) the end at once."""
        if self.done or self.mode != PICK:
            return
        self.item = name
        self.gift = rules.reaction_for(self.table, self.to, name)
        if type(self.give_sound) is str and self.give_sound:
            self.ctx.play_ui(OWN + "give_sound")
        if self.gift.line is None and not self.verdict():
            self._finish_gift()
            return
        self.mode = CARD
        self.view = None
        scope = self.ctx.scope
        scope.set_groups([FocusGroup([self.continue_button])])
        scope.set_default(self.continue_button)
        self._lay_key = None

    def verdict(self) -> str:
        if self.gift is None:
            return ""
        return fill(self.word[self.gift.reaction], name=self.speaker)

    def _not_now(self) -> None:
        if not self.done and self.mode == PICK:
            self._end(None)

    def _continue(self) -> None:
        if self.mode == CARD:
            self._finish_gift()
        elif self.mode == NOTHING:
            self._end(None)

    def _finish_gift(self) -> None:
        if self.done or self.item is None or self.gift is None:
            return
        if self.use_up:
            self.ctx.codex.take(self.item)
        if self.gift.points:
            self.ctx.points.add(self.to, self.gift.points)
        self._end(self.gift.reaction if self.result_kind == "reaction" else self.item)

    def _end(self, result: object) -> None:
        self.done = True
        self.ctx.finish(result)

    def update(self, dt: float) -> None:
        if self.mode == PICK and self.view is not None and not self.done:
            self.view.update(dt)
            if self.view.groups_changed:
                self._lay_key = None

    # -- settings and layout --

    def settings_changed(self, s: "PlayerSettings") -> None:
        self._lay_key = None

    def layout(self, area) -> None:
        self.area = area
        self._lay_key = None

    def _settle(self, canvas: "Canvas") -> None:
        if self._lay_key == self._key():
            return
        if self.mode == PICK:
            self._build_picker()
            return
        p = self.ctx.painter
        scale = p.text_scale()
        heading, panel = p.style("panel.heading"), p.style("panel")
        width = rules.CARD_W - 2 * rules.CARD_PAD
        if self.mode == NOTHING:
            text, px = self.word["nothing"], scaled(self.line_size, scale)
            name_h, verdict_h = 0, 0
        else:
            text = self.gift.line if self.gift is not None and self.gift.line else ""
            px = scaled(self.line_size, scale)
            name_h = pitch(p.scaled_size(heading.font.size))
            verdict_h = pitch(scaled(rules.VERDICT_TEXT, scale)) if self.verdict() else 0
        font = dataclasses.replace(panel.font, size=px)
        lines = len(canvas.layout_lines(text, font, width, rules.LINES_MAX)) if text else 0
        self.card = rules.card_layout((self.area.x, self.area.y, self.area.w, self.area.h),
                                      name_h=name_h, line_h=lines * pitch(px),
                                      verdict_h=verdict_h, button_h=button_height(scale=scale))
        self.card_line = (text, px)
        self.continue_button.box = Box(*self.card.cont)
        self._lay_key = self._key()

    # -- drawing --

    def draw(self, canvas: "Canvas") -> None:
        self._settle(canvas)
        p = self.ctx.painter
        if self.mode == PICK:
            if self.picker is not None and self.view is not None:
                p.panel(Box(*self.picker.backing))
                self.view.draw(canvas, p)
            return
        card = self.card
        p.panel(Box(*card.panel))
        heading, panel = p.style("panel.heading"), p.style("panel")
        if self.mode == CARD:
            x, y, w, _h = card.name
            canvas.draw_text(self.speaker, dataclasses.replace(
                heading.font, size=p.scaled_size(heading.font.size)), heading.text_color,
                (x, y), max_width=w, max_lines=1)
        text, px = self.card_line
        if text:
            x, y, w, _h = card.line
            canvas.draw_text(text, dataclasses.replace(panel.font, size=px), panel.text_color,
                             (x, y), max_width=w, max_lines=rules.LINES_MAX)
        verdict = self.verdict() if self.mode == CARD else ""
        if verdict:
            x, y, w, _h = card.verdict
            canvas.draw_text(verdict, dataclasses.replace(
                panel.font, size=p.scaled_size(rules.VERDICT_TEXT)), panel.text_color,
                (x, y), max_width=w, max_lines=1)


__all__ = ["GiftGiving", "TOKENS", "WORDS"]

"""Hand game (F53): a bundled rock-paper-scissors match against a character who may cheat.
The result is ``"won"``, ``"lost"`` or ``"draw"``.

Every rule is in ``hand_rules``; this module is the session (F53 ``01`` §4.3, ``04`` §3.4):

- **A round.** At its start the game calls ``ctx.random.pick`` exactly once, in every mode,
  before the player picks (so a reload replays the same hands). Rock, Paper and Scissors are
  one focus group (Rock first for keys); her card shows "?" until the reveal.
- **The reveal.** Both cards show and ``reveal_sound`` plays. In ``cheat``, when her fair hand
  would lose, 0.6 s later it switches to the winning hand with a ±6, 0.2 s shake (a cut under
  Reduce motion) and the ``switched`` caption; no buttons show meanwhile. ``sly`` shows the
  winning hand at once, with no caption.
- **After a round.** The score and the round caption update; the scope becomes Next round,
  or, when the match is over (no rounds left, or a lead bigger than the rounds left),
  Continue with the result word as a second caption line. Continue is ``ctx.finish``.
- **Pictures.** ``hand.rock_image`` and friends (none by default) replace the hand words,
  scaled down (never up) to fit the card; a missing picture shows the word.
- **Look.** Colors from ``panel.*`` and ``button.*`` only (every scheme applies).

Presentation-only: a restore starts the match again with the same seed.
"""

import dataclasses
from typing import TYPE_CHECKING, Any, Final

from engine.minigames.api import Arg, Minigame, Outcome, PluginEvent, StoryNames
from engine.minigames.bundled import hand_rules as rules
from engine.minigames.bundled.rule_text import fill
from engine.render.frames import FrameSpec
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import button_height, pitch, scaled
from engine.ui.paint import fit_label
from engine.ui.widgets import Button

if TYPE_CHECKING:
    from engine.minigames.api import Context, PlayerSettings
    from engine.render.canvas import Canvas
    from engine.ui.paint import Painter

OWN: Final = "plugin.hand_game."

# [theme.plugin.hand_game] (01 §4.4): a size, a sound and three pictures (none by default).
TOKENS = {
    "hand.text_size": rules.HAND_TEXT[0],
    "hand.rock_image": "",
    "hand.paper_image": "",
    "hand.scissors_image": "",
    "reveal_sound": "",
}

# [words.plugin.hand_game] (01 §4.5).
WORDS = {
    "title": "Rock, Paper, Scissors",
    "hint": "Pick a hand.",
    "rock": "Rock",
    "paper": "Paper",
    "scissors": "Scissors",
    "you": "You",
    "round": "Round {n} of {total}",
    "score": "You {you} – {them} {name}",
    "win_round": "You win this round.",
    "lose_round": "{name} wins this round.",
    "draw_round": "A draw.",
    "switched": "{name} switched hands!",
    "next": "Next round",
    "won": "You won!",
    "lost": "You lost.",
    "draw": "It's a draw.",
    "continue": "Continue",
}

PICK, SWITCH, RESULT = "pick", "switch", "result"
_ROUND_WORDS: Final = {"win": "win_round", "lose": "lose_round", "draw": "draw_round"}


class HandGame(Minigame):
    name = "hand_game"
    title = "Rock, Paper, Scissors"
    api = "1.1"
    over_stage = True
    args = {key: (Arg() if key in rules.REQUIRED else Arg(default=value))
            for key, value in rules.DEFAULTS.items()}
    test_outcome = Outcome("won")
    skipped_outcome = Outcome("draw")
    tokens = TOKENS
    words = WORDS

    def check_args(self, args: dict) -> str | None:
        return rules.problem(args)

    def outcome_for(self, kind: str, args: dict, story: StoryNames) -> Outcome | None:
        return rules.fixed_outcome(kind, args)

    # -- the session --

    def start(self, ctx: "Context") -> None:
        self.ctx = ctx
        a = {**rules.DEFAULTS, **ctx.args}
        self.opponent: str = a["opponent"]
        self.rounds: int = a["rounds"]
        self.mode: str = a["mode"]
        self.word = {key: ctx.words.mine(key) for key in WORDS}
        self.score = rules.Score()
        self.round_no = 0
        self.fair_hands: list[str] = []
        self.player: str | None = None
        self.her: rules.Hand | None = None
        self.shown: str | None = None                 # her card, as shown now
        self.captions: list[str] = []
        self.switch_left = 0.0
        self.shake_t: float | None = None
        self.done = False
        self.reduce = bool(ctx.settings.reduce_motion)
        mine = ctx.theme.mine
        self.hand_size = rules.clamp_size(mine("hand.text_size"), *rules.HAND_TEXT)
        self.reveal_sound = mine("reveal_sound")
        self.pictures: dict[str, Any] = {}
        for hand in rules.HANDS:
            ref = mine(f"hand.{hand}_image")
            image = ctx.gui_image(ref) if type(ref) is str and ref else None
            if image is not None and not getattr(image, "is_placeholder", True):
                self.pictures[hand] = image
        self.hand_buttons = [Button((lambda h=h: self.word[h]), (lambda h=h: self.pick(h)))
                             for h in rules.HANDS]
        self.next_button = Button(lambda: self.word["next"], self._next)
        self.continue_button = Button(lambda: self.word["continue"], self._continue)
        self.area = ctx.area
        self.lay: Any = None
        self._lay_key: tuple | None = None
        self._fitted: dict[tuple, Any] = {}
        ctx.heading(True)
        ctx.hint(self.word["hint"])
        self._round_start()

    def _round_start(self) -> None:
        self.round_no += 1
        fair = self.ctx.random.pick(list(rules.HANDS))
        self.fair_hands.append(fair)
        self.player = self.her = self.shown = None
        self.captions = []
        self.phase = PICK
        scope = self.ctx.scope
        scope.set_groups([FocusGroup(list(self.hand_buttons))])
        scope.set_default(self.hand_buttons[0])

    def pick(self, hand: str) -> None:
        """The player's hand: the reveal, then the switch (cheat) or the round's end."""
        if self.phase != PICK or self.done:
            return
        self.player = hand
        self.her = rules.her_hand(self.mode, self.fair_hands[-1], hand, self.score, self.rounds)
        self.shown = self.her.shown
        if type(self.reveal_sound) is str and self.reveal_sound:
            self.ctx.play_ui(OWN + "reveal_sound")
        if self.her.switched:
            self.phase = SWITCH
            self.switch_left = rules.SWITCH_S
            self.ctx.scope.set_groups([])
            return
        self._end_round()

    def _end_round(self) -> None:
        assert self.player is not None and self.her is not None
        result = rules.outcome(self.player, self.her.final)
        self.score = self.score.after(result)
        line = fill(self.word[_ROUND_WORDS[result]], name=self.opponent)
        if self.her.switched:
            line = fill(self.word["switched"], name=self.opponent) + " " + line
        self.captions = [line]
        scope = self.ctx.scope
        self.phase = RESULT
        if rules.finished(self.score, self.rounds):
            self.captions.append(self.word[rules.result_of(self.score)])
            scope.set_groups([FocusGroup([self.continue_button])])
            scope.set_default(self.continue_button)
        else:
            scope.set_groups([FocusGroup([self.next_button])])
            scope.set_default(self.next_button)

    def _next(self) -> None:
        if self.phase == RESULT and not rules.finished(self.score, self.rounds):
            self._round_start()

    def _continue(self) -> None:
        if self.phase == RESULT and not self.done:
            self.done = True
            self.ctx.finish(rules.result_of(self.score))

    def handle_event(self, ev: PluginEvent) -> bool:
        return False                                  # F10 routing does it all

    def update(self, dt: float) -> None:
        dt = max(0.0, float(dt))
        if self.shake_t is not None:
            self.shake_t += dt
            if self.shake_t >= rules.SHAKE_S:
                self.shake_t = None
        if self.phase == SWITCH:
            self.switch_left -= dt
            if self.switch_left <= rules.EPSILON:
                assert self.her is not None
                self.shown = self.her.final
                self.shake_t = None if self.reduce else 0.0
                self._end_round()

    # -- what shows --

    def score_text(self) -> str:
        return fill(self.word["score"], you=self.score.wins, them=self.score.losses,
                    name=self.opponent)

    def round_text(self) -> str:
        return fill(self.word["round"], n=self.round_no, total=self.rounds)

    def face(self, hand: str | None) -> Any:
        """What a card shows: "?" before the reveal, the hand's picture, or its word."""
        if hand is None:
            return "?"
        return self.pictures.get(hand) or self.word[hand]

    def shake(self) -> float:
        if self.reduce or self.shake_t is None:
            return 0.0
        return rules.shake_offset(self.shake_t)

    # -- settings and layout --

    def settings_changed(self, s: "PlayerSettings") -> None:
        self.reduce = bool(s.reduce_motion)
        if self.reduce:
            self.shake_t = None
        self._lay_key = None

    def layout(self, area) -> None:
        self.area = area
        self._lay_key = None

    def settle(self) -> Any:
        p = self.ctx.painter
        scale = p.text_scale()
        a = self.area
        key = (a.x, a.y, a.w, a.h, scale)
        if key == self._lay_key and self.lay is not None:
            return self.lay
        bh = button_height(scale=scale)
        lay = rules.hand_layout((a.x, a.y, a.w, a.h),
                                score_h=pitch(scaled(rules.SCORE_TEXT, scale)),
                                caption_h=2 * pitch(scaled(rules.CAPTION_TEXT, scale)),
                                button_h=bh)
        for button, box in zip(self.hand_buttons, lay.hands):
            button.box = Box(*box)
        self.next_button.box = self.continue_button.box = Box(*lay.single)
        self.lay, self._lay_key = lay, key
        self._fitted.clear()
        return lay

    # -- drawing --

    def draw(self, canvas: "Canvas") -> None:
        lay = self.settle()
        p = self.ctx.painter
        heading, panel = p.style("panel.heading"), p.style("panel")
        sx, sy, sw, sh = lay.score
        self._line(canvas, p, self.score_text(), Box(sx, sy, sw * 0.6, sh), heading,
                   rules.SCORE_TEXT, heading.text_color, anchor="midleft")
        self._line(canvas, p, self.round_text(), Box(sx + sw * 0.6, sy, sw * 0.4, sh), panel,
                   rules.ROUND_TEXT, panel.text_color, anchor="midright")
        self._card(canvas, p, Box(*lay.cards[0]), self.word["you"], self.player)
        her = Box(*lay.cards[1]).moved(self.shake())
        self._card(canvas, p, her, self.opponent, self.shown)
        cx, cy, cw, ch = lay.caption
        line_h = ch / 2
        for i, text in enumerate(self.captions[:2]):
            self._line(canvas, p, text, Box(cx, cy + i * line_h, cw, line_h), panel,
                       rules.CAPTION_TEXT, panel.text_color)

    def _line(self, canvas: "Canvas", p: "Painter", text: str, box: Box, style: Any, size: int,
              color: Any, *, anchor: str = "center") -> None:
        """One line fitted to ``box`` (steps down by 2, not below 24, then "…")."""
        px = p.scaled_size(size)
        key = (text, style.font, px, box.w)
        fit = self._fitted.get(key)
        if fit is None:
            fit = self._fitted[key] = fit_label(
                text, lambda s: canvas.font_handle(style.font, s).font, px, box.w,
                min_size=min(24, px))
        if not fit.text:
            return
        x = {"midleft": box.x, "midright": box.right}.get(anchor, box.center[0])
        canvas.draw_text(fit.text, dataclasses.replace(style.font, size=fit.size), color,
                         (x, box.center[1]), anchor=anchor)       # type: ignore[arg-type]

    def _card(self, canvas: "Canvas", p: "Painter", box: Box, name: str,
              hand: str | None) -> None:
        p.panel(box)
        heading, button = p.style("panel.heading"), p.style("button")
        pad = rules.CARD_PAD
        name_h = pitch(p.scaled_size(rules.NAME_TEXT))
        self._line(canvas, p, name, Box(box.x + pad, box.y + pad, box.w - 2 * pad, name_h),
                   heading, rules.NAME_TEXT, heading.text_color)
        inner = Box(box.x + pad, box.y + pad + name_h, box.w - 2 * pad,
                    box.h - 2 * pad - name_h)
        face = self.face(hand)
        if isinstance(face, str):
            self._line(canvas, p, face, inner, button, self.hand_size,
                       p.style("panel").text_color)
            return
        w, h = face.size
        k = min(1.0, inner.w / max(1, w), inner.h / max(1, h))
        fw, fh = w * k, h * k
        spec = FrameSpec(p.style("panel").text_color, slice_width=0)
        p.shape(Box(inner.center[0] - fw / 2, inner.center[1] - fh / 2, fw, fh), spec,
                image=face)


__all__ = ["HandGame", "TOKENS", "WORDS"]

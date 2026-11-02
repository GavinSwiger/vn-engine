"""The poem game (F24): a bundled minigame where the player builds a poem word by word and
the words' scores raise the story's meters.

Step F24-1 built the declarations and the three API 1.1 hooks; every rule they use is in
``poem_rules``. Step F24-3 adds the playable session (F24 ``04`` §6):

- ``start`` parses the checked arguments, draws the first page with one
  ``ctx.random.shuffle``, and puts one ``WordSlot`` per page position in ``ctx.scope`` (two
  column groups: Up/Down wrap in a column, Left/Right cross, Tab reads down the left column
  and then the right).
- **Lazy layout.** ``layout``, ``settings_changed``, and a page change only set flags;
  ``draw`` lays the page out (``poem_rules.page_layout``) and fits the words
  (``fit_label``) when something changed, then draws the page, its margin and rules, and
  the counter. The host draws the slots after ``draw`` (F23 A4); ``WordSlot.draw`` draws
  F10's row look and the fitted word.
- **Picks.** A slot's activation adds the word's scores, takes the next page, and keeps the
  slot objects, so focus stays on the same slot. A pick within 200 ms of a page change is
  ignored (PR-F24-16). The host plays ``button.activate_sound`` for every activation
  (F24 ``07`` I-5, Q-b), so the game plays none. After the last pick, one
  ``ctx.points.add`` per scoring meter, then ``ctx.finish``.

Presentation-only: nothing here is saved; a restore starts again at ``0 / N`` with the same
first page (the seed and the arguments are F23's).

Imports (AC-F24-01): ``poem_rules``, ``engine.minigames.api``, and F10's public widget kit
(``engine.ui.focus``, ``engine.ui.widgets``, ``engine.ui.paint``) only.
"""

import math
from typing import TYPE_CHECKING

from engine.minigames.api import Arg, Minigame, Outcome, StoryNames
from engine.minigames.bundled import poem_rules
from engine.ui.focus import Box, FocusGroup
from engine.ui.paint import FrameSpec, fit_label
from engine.ui.widgets import Look, Widget

if TYPE_CHECKING:
    from engine.minigames.api import Context, PlayerSettings
    from engine.render.canvas import Canvas
    from engine.ui.paint import Fit, Painter

# [theme.plugin.poem_game.<element>] (F24 04 §12; the ranges are clamped in start, C3).
# page.turn_sound arrives with the Could step F24-5.
TOKENS = {
    "page.paper_image": "",
    "page.fill_color": "#FFFDF6",
    "page.rule_color": "#C9D8EE",
    "page.margin_color": "#E8A0A0",
    "page.max_width": 800,
    "word.text_font": "ui.text_font",
    "word.text_size": 32,
    "word.text_color": "#3A2E39",
    "counter.text_size": 28,
    "counter.text_color": "plugin.poem_game.word.text_color",
}

MAX_WIDTH_RANGE = (560, 1232)
WORD_SIZE_RANGE = (24, 48)
COUNTER_SIZE_RANGE = (24, 40)
WORD_MIN_SIZE, WORD_STEP = 24, 2         # ui-system §7: step down by 2, not below 24, then "…"
SLOT_PAD_X = 48                          # a slot is the word + 48 wide …
SLOT_GAP_X = 16                          # … and at most the column − 16
MARGIN_WIDTH = 2
RULE_WIDTH = 1
_TOKEN_PREFIX = "plugin.poem_game."
_FONT_ENDS = (".ttf", ".otf", ".ttc")

RGB = tuple[int, int, int]


def _hex(text: str) -> RGB | None:
    """``#RRGGBB`` (or ``#RRGGBBAA``, its alpha ignored) as an RGB tuple, else None."""
    if len(text) not in (7, 9) or text[0] != "#":
        return None
    try:
        return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))     # type: ignore[return-value]
    except ValueError:
        return None


_DEFAULT_RGB = {key: _hex(value) for key, value in TOKENS.items()
                if type(value) is str and _hex(value) is not None}


class WordSlot(Widget):
    """One page position; reused for every page, so focus stays on it across a pick."""

    def __init__(self, game: "PoemGame", index: int) -> None:
        super().__init__()
        self.game = game
        self.index = index

    def activate(self) -> None:
        self.game._pick(self.index)

    def draw(self, p: "Painter", look: Look) -> None:
        self.game._draw_slot(self, p, look)


class PoemGame(Minigame):
    name = "poem_game"
    title = "Poem"
    api = "1.1"
    over_stage = False
    args = {"words": Arg(), **{key: Arg(default=value)
                               for key, value in poem_rules.DEFAULTS.items()}}
    # The static outcomes gate skippable (E271) and E279; outcome_for gives the real ones.
    test_outcome = Outcome(None)
    skipped_outcome = Outcome(None)
    tokens = TOKENS
    words = {"title": "Poem", "hint": "Pick a word for your poem."}

    # -- API 1.1 hooks (fresh, never-started instances) --

    def check_args(self, args: dict) -> str | None:
        return poem_rules.problem(args)

    def check_story(self, args: dict, story: StoryNames) -> str | None:
        return poem_rules.meter_problem(args, story.meters)

    def outcome_for(self, kind: str, args: dict, story: StoryNames) -> Outcome | None:
        return poem_rules.fixed_outcome(kind, poem_rules.parse(args), story.meters)

    # -- the session (04 §6) --

    def start(self, ctx: "Context") -> None:
        self.ctx = ctx
        poem = self.poem = poem_rules.parse(ctx.args)
        self.meters = poem_rules.named_meters(poem, ctx.points.names())
        self.totals = dict.fromkeys(self.meters, 0)
        self.remaining = list(range(len(poem.entries)))
        self.picked: list[int] = []
        self.since_change = math.inf
        self.done = False
        # The host draws the opening picture before any update, after its first focus; the
        # slots draw at rest until the first update, so that picture has no marker.
        self.opened = False
        self.page = poem_rules.new_page(self.remaining, poem.page_words, ctx.random.shuffle)
        self.slots = [WordSlot(self, i) for i in range(poem.page_words)]
        rows = math.ceil(poem.page_words / 2)
        ctx.scope.set_groups([FocusGroup(self.slots[:rows], column=True),
                              FocusGroup(self.slots[rows:], column=True)])
        ctx.scope.set_default(self.slots[0])
        ctx.heading(False)
        ctx.hint(ctx.words.mine("hint"))
        self._read_tokens()
        settings = ctx.settings
        self.scale = float(settings.text_scale)
        self.reduce = bool(settings.reduce_motion)
        self.area = ctx.area
        self.lay: poem_rules.PageLayout | None = None
        self.fits: list["Fit"] = []
        self.layout_dirty = True
        self.fits_dirty = True

    def handle_event(self, ev) -> bool:
        return False                   # the host routes Nav and the pointer to the slots

    def update(self, dt: float) -> None:
        self.opened = True
        self.since_change += dt

    def layout(self, area) -> None:
        self.area = area
        self.layout_dirty = True

    def settings_changed(self, s: "PlayerSettings") -> None:
        self.reduce = bool(s.reduce_motion)
        scale = float(s.text_scale)
        if scale != self.scale:
            self.scale = scale
            self.layout_dirty = True

    def draw(self, canvas: "Canvas") -> None:
        self._settle(canvas)
        lay = self.lay
        assert lay is not None
        page = Box(*lay.page)
        if self.paper is not None:
            self.ctx.painter.shape(page, FrameSpec(self.fill_color, slice_width=0),
                                   image=self.paper)
        else:
            canvas.fill(self.fill_color, lay.page)
            rule_x = lay.margin_x + MARGIN_WIDTH
            rule_w = page.right - rule_x
            for y in lay.rules:
                canvas.fill(self.rule_color, (rule_x, y, rule_w, RULE_WIDTH))
            canvas.fill(self.margin_color, (lay.margin_x, page.y, MARGIN_WIDTH, page.h))
        canvas.draw_text(f"{len(self.picked)} / {self.poem.rounds}", self.counter_font,
                         self.counter_color, lay.counter_at, anchor="topright")

    # -- picks (04 §6.2, §6.3) --

    def _pick(self, index: int) -> None:
        if self.done or poem_rules.pick_ignored(self.since_change):
            return
        entry = self.page[index]
        self.picked.append(entry)
        self.remaining.remove(entry)
        for name, points in self.poem.entries[entry].scores:
            self.totals[name] += points
        if len(self.picked) == self.poem.rounds:
            self.done = True           # the page stays: the last frame shows N / N
            self._finish()
            return
        self.page = poem_rules.new_page(self.remaining, self.poem.page_words,
                                        self.ctx.random.shuffle)
        self.since_change = 0.0
        self.fits_dirty = True

    def _finish(self) -> None:
        poem, ctx = self.poem, self.ctx
        if poem.to_points:
            for name in self.meters:
                if self.totals[name] > 0:
                    ctx.points.add(name, self.totals[name])
        ctx.finish(poem_rules.result_of(poem, self.picked, self.totals))

    # -- tokens (04 §6.1 step 7, §12) --

    def _read_tokens(self) -> None:
        mine = self.ctx.theme.mine
        self.fill_color = self._color("page.fill_color")
        self.rule_color = self._color("page.rule_color")
        self.margin_color = self._color("page.margin_color")
        self.word_color = self._color("word.text_color")
        self.counter_color = self._color("counter.text_color", self.word_color)
        self.max_width = poem_rules.clamp_size(mine("page.max_width"), *MAX_WIDTH_RANGE,
                                               TOKENS["page.max_width"])
        self.word_size = poem_rules.clamp_size(mine("word.text_size"), *WORD_SIZE_RANGE,
                                               TOKENS["word.text_size"])
        self.counter_size = poem_rules.clamp_size(mine("counter.text_size"),
                                                  *COUNTER_SIZE_RANGE,
                                                  TOKENS["counter.text_size"])
        self.font_ref = self._font_ref(mine("word.text_font"))
        ref = mine("page.paper_image")
        paper = self.ctx.gui_image(ref) if type(ref) is str and ref else None
        # A missing or unusable image is the asset manager's placeholder (logged once by
        # it): the drawn page instead, never the checkerboard (04 §7 item 6).
        self.paper = None if paper is None or getattr(paper, "is_placeholder", True) \
            else paper

    def _color(self, key: str, fallback: RGB | None = None) -> RGB:
        """A color token: an RGB triple, ``#RRGGBB``, or a reference to another token
        (``plugin.poem_game.word.text_color`` or an engine token); else its default."""
        default = fallback if fallback is not None else _DEFAULT_RGB[key]
        value = self.ctx.theme.mine(key)
        for _ in range(4):                        # references, at most a few deep
            if type(value) in (tuple, list) and len(value) == 3 \
                    and all(type(c) is int and 0 <= c <= 255 for c in value):
                return tuple(value)                                    # type: ignore[return-value]
            if type(value) is not str:
                return default
            rgb = _hex(value)
            if rgb is not None:
                return rgb
            try:
                if value.startswith(_TOKEN_PREFIX):
                    value = self.ctx.theme.mine(value[len(_TOKEN_PREFIX):])
                else:
                    value = self.ctx.theme.get(value)
            except KeyError:
                return default
        return default

    def _font_ref(self, value: object) -> str | None:
        """``word.text_font``: a font file, or a token naming one (``ui.text_font``, the
        default: the theme's UI face, which ``ctx.font(None, …)`` gives)."""
        if type(value) is not str or not value or value == "ui.text_font":
            return None
        if value.lower().endswith(_FONT_ENDS):
            return value
        try:
            found = self.ctx.theme.get(value)
        except KeyError:
            return None
        return found if type(found) is str and found else None

    # -- layout and fit (04 §6.5) --

    def _font(self, size: int):
        return self.ctx.font(self.font_ref, size)

    def _settle(self, canvas: "Canvas") -> None:
        """Lay out and fit whatever changed since the last draw."""
        if self.layout_dirty:
            self.layout_dirty = False
            self.fits_dirty = True
            word_px = poem_rules.scaled(self.word_size, self.scale)
            counter_px = poem_rules.scaled(self.counter_size, self.scale)
            self.word_px = word_px
            self.counter_font = self.ctx.font(None, counter_px)
            a = self.area
            self.lay = poem_rules.page_layout(
                (a.x, a.y, a.w, a.h), max_width=self.max_width, n=self.poem.page_words,
                pitch=poem_rules.line_pitch(word_px),
                counter_h=poem_rules.line_pitch(counter_px))
        if not self.fits_dirty:
            return
        self.fits_dirty = False
        lay = self.lay
        assert lay is not None

        def font_at(size: int):
            return canvas.font_handle(self._font(size), size).font

        self.fits = []
        for slot, entry, cell in zip(self.slots, self.page, lay.cells):
            fit = fit_label(self.poem.entries[entry].word, font_at, self.word_px,
                            lay.label_width, min_size=min(WORD_MIN_SIZE, self.word_px),
                            step=WORD_STEP)
            self.fits.append(fit)
            width = font_at(fit.size).size(fit.text)[0] if fit.text else 0
            cx, cy, cw, ch = cell
            w = min(cw - SLOT_GAP_X, width + SLOT_PAD_X)
            slot.box = Box(cx + (cw - w) / 2, cy, w, ch)

    def _draw_slot(self, slot: WordSlot, p: "Painter", look: Look) -> None:
        """F10's row look (no frame at rest; the button's focused or pressed fill, border,
        and marker otherwise), then the word centered at its fitted size (UI-F24-02)."""
        if not self.opened:
            look = Look("normal")         # the opening picture shows no focus (UI-F24-06)
        p.widget_frame(slot.box, "list", look)
        if slot.index >= len(self.fits):
            return
        fit = self.fits[slot.index]
        if not fit.text:
            return
        color = self.word_color if look.state == "normal" \
            else p.style("list", look.state).text_color
        p.canvas.draw_text(fit.text, self._font(fit.size), color, slot.box.center,
                           anchor="center")


__all__ = ["TOKENS", "PoemGame", "WordSlot"]

"""The shop (F64 round 2; proposal I-12): a bundled minigame where the player buys items with
the story's money. ``minigame shop stock=stall_stock into bought``.

Every rule is in ``shop_rules``; this module is the session:

- **The panel.** The money the player holds at the top right ("Coins ×30": the bag's money
  word, ``ctx.codex.money_word()``), the stock as a list (each row: the item's title, "×2"
  when the player holds some, "3 left" or "Sold out" when the stock has a number, the price
  as "5 Coins", "1 Coin" or "Free"), a message line, and **Buy**, **Put back** and **Leave**.
- **Buy** buys one of the selected row: the price is taken from the money and one item is
  added, through API 1.5's counts (``ctx.codex.take(money, price)``, ``give(item)``), so the
  panel shows the new money and count at once. When it can't, the message says why (sold
  out, not enough money, can't carry more) and nothing changes. **Put back** undoes the last
  Buy (the item goes back, the money comes back), so a slip costs nothing.
- **The end.** Leave (also Backspace, right click, gamepad B) finishes with what was bought,
  ``{"tea": 2}`` (``{}`` for nothing). Only then do the changes reach the story (F23's
  ledger); Skip Game and an abandoned visit change nothing and give ``{}``.
- **Input.** Mouse: a click selects a row, Buy buys it. Keys and gamepad: Up/Down choose a
  row, Enter/A goes to Buy, and Buy can be pressed again to buy more.
- **Look.** ``panel``, ``list`` and ``button`` tokens only (every scheme); no motion of its
  own (Reduce motion changes nothing); no timing.

Presentation-only: a load or rollback starts the visit again; nothing was bought.
"""

from typing import TYPE_CHECKING, Final

from engine.minigames.api import Arg, Minigame, Outcome, PluginEvent, StoryNames
from engine.minigames.bundled import shop_rules as rules
from engine.minigames.bundled.rule_text import fill
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import button_height, list_row_height, pitch
from engine.ui.nav import InputKind, Nav
from engine.ui.widgets import Button, ListRow, Look, ScrollList

if TYPE_CHECKING:
    from engine.minigames.api import Context, PlayerSettings
    from engine.render.canvas import Canvas
    from engine.ui.paint import Painter

OWN: Final = "plugin.shop."
ROW_PAD: Final = 16                   # a row's text inset from its sides

# [theme.plugin.shop]
TOKENS = {"buy_sound": ""}

# [words.plugin.shop]. {item} is an item's title, {money} the money word, {n} a number.
WORDS = {
    "title": "Shop",
    "hint": "Choose something, then Buy.",
    "buy": "Buy",
    "put_back": "Put back",
    "leave": "Leave",
    "price": "{n} {money}",
    "free": "Free",
    "left": "{n} left",
    "sold_out": "Sold out",
    "gone": "{item} is sold out.",
    "bought": "Bought {item}.",
    "returned": "Put {item} back.",
    "short": "Not enough {money}.",
    "full": "You can't carry more {item}.",
    "enough": "That's all for this visit.",
}

# What the message says when Buy can't happen (``rules.why_not``).
_SAYS: Final = {rules.SOLD_OUT: "gone", rules.SHORT: "short", rules.FULL: "full",
                rules.ENOUGH: "enough"}


class _StockList(ScrollList):
    """The stock: a key move or a click selects a row (hovering doesn't); activating a row
    by keys goes on to Buy."""

    def __init__(self, shop: "Shop") -> None:
        self.shop = shop
        super().__init__(shop._rows, shop._row_activated, draw_row=shop._draw_row)

    def on_nav(self, d: Nav) -> bool:
        used = super().on_nav(d)
        if used:
            self.shop.select(self.focus_row)
        return used

    def on_mouse(self, kind, pos, *, notches: int = 0) -> bool:
        used = super().on_mouse(kind, pos, notches=notches)
        if kind == "down" and self.pressed_row is not None:
            self.shop.select(self.pressed_row)
        return used


class Shop(Minigame):
    name = "shop"
    title = "Shop"
    api = "1.5"
    over_stage = True
    args = {key: (Arg() if key in rules.REQUIRED else Arg(default=value))
            for key, value in rules.DEFAULTS.items()}
    test_outcome = Outcome({})
    skipped_outcome = Outcome({})
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
        self.offers = rules.parse(a, ctx.story)
        self.money = rules.money_of(a, ctx.story)
        self.word = {key: ctx.words.mine(key) for key in WORDS}
        self.money_word = ctx.codex.money_word() or self._title(self.money)
        self.titles = {o.item: self._title(o.item) for o in self.offers}
        self.buy_sound = ctx.theme.mine("buy_sound")
        self.bought: dict[str, int] = {}
        self.history: list[int] = []                    # rows bought, for Put back
        self.actions = 0
        self.selected = 0
        self.message = ""
        self.done = False
        self.last_kind = InputKind.MOUSE
        self.area = ctx.area
        self.lay: rules.ShopLayout | None = None
        self._lay_key: tuple | None = None
        self.list = _StockList(self)
        self.buy_button = Button(lambda: self.word["buy"], self.buy)
        self.put_back_button = Button(lambda: self.word["put_back"], self.put_back,
                                      enabled=lambda: bool(self.history) and not self.done)
        self.leave_button = Button(lambda: self.word["leave"], self.leave)
        ctx.heading(True, a["name"])
        ctx.hint(self.word["hint"])
        self._settle()

    def _title(self, name: str) -> str:
        try:
            return str(self.ctx.codex.title(name))
        except Exception:                            # noqa: BLE001 (checked at start)
            return name

    # -- reading the preview --

    def held(self, item: str) -> int:
        return self.ctx.codex.count(item)

    def purse(self) -> int:
        return self.ctx.codex.count(self.money)

    def reason(self, index: int) -> str | None:
        """Why row ``index`` can't be bought now (``rules.why_not``), or None."""
        offer = self.offers[index]
        codex = self.ctx.codex
        return rules.why_not(offer, bought=self.bought.get(offer.item, 0), money=self.purse(),
                             held=codex.count(offer.item), most=codex.most(offer.item),
                             actions=self.actions)

    def price_text(self, offer: rules.Offer) -> str:
        if offer.price == 0:
            return self.word["free"]
        return fill(self.word["price"], n=f"{offer.price:,}",
                    money=rules.money_for(offer.price, self.money_word))

    def stock_text(self, offer: rules.Offer) -> str:
        if offer.stock is None:
            return ""
        left = offer.stock - self.bought.get(offer.item, 0)
        return self.word["sold_out"] if left <= 0 else fill(self.word["left"], n=f"{left:,}")

    def row_title(self, offer: rules.Offer) -> str:
        held = self.held(offer.item)
        title = self.titles[offer.item]
        return f"{title} ×{held:,}" if held > 0 and self.ctx.codex.most(offer.item) > 1 \
            else title

    # -- actions --

    def select(self, index: int) -> None:
        """Row ``index`` is the one Buy buys; the list's focus follows it."""
        if not 0 <= index < len(self.offers):
            return
        if index != self.selected:
            self.selected = index
            self.message = ""
        if self.list.focus_row != index:
            self.list.focus_index(index)

    def _row_activated(self, index: int) -> None:
        """A click selects the row; Enter or A on it also goes on to Buy."""
        self.select(index)
        if not self.done and self.last_kind is InputKind.KEYS:
            self.ctx.scope.focus(self.buy_button, InputKind.KEYS)

    def buy(self) -> None:
        if self.done:
            return
        offer = self.offers[self.selected]
        why = self.reason(self.selected)
        if why is not None:
            self.message = fill(self.word[_SAYS[why]], item=self.titles[offer.item],
                                money=self.money_word)
            return
        codex = self.ctx.codex
        if offer.price:
            codex.take(self.money, offer.price)
        codex.give(offer.item)
        self.bought[offer.item] = self.bought.get(offer.item, 0) + 1
        self.history.append(self.selected)
        self.actions += 1
        self.message = fill(self.word["bought"], item=self.titles[offer.item])
        if type(self.buy_sound) is str and self.buy_sound:
            self.ctx.play_ui(OWN + "buy_sound")

    def put_back(self) -> None:
        if self.done or not self.history:
            return
        if self.actions >= rules.ACTIONS_MAX:
            self.message = self.word["enough"]
            return
        offer = self.offers[self.history.pop()]
        codex = self.ctx.codex
        codex.take(offer.item)
        if offer.price:
            codex.give(self.money, offer.price)
        self.bought[offer.item] -= 1
        self.actions += 1
        self.message = fill(self.word["returned"], item=self.titles[offer.item])

    def leave(self) -> None:
        if not self.done:
            self.done = True
            self.ctx.finish(rules.bought_result(self.bought))

    # -- input --

    def handle_event(self, ev: PluginEvent) -> bool:
        if ev.ui.canvas_pos is not None:
            self.last_kind = InputKind.MOUSE
        elif ev.nav is not None:
            self.last_kind = InputKind.KEYS
        if self.done:
            return False
        if ev.nav is Nav.BACK:
            self.leave()
            return True
        return False

    # -- settings and layout --

    def settings_changed(self, s: "PlayerSettings") -> None:
        self._lay_key = None

    def layout(self, area) -> None:
        self.area = area
        self._lay_key = None

    def _key(self) -> tuple:
        a = self.area
        return (a.x, a.y, a.w, a.h, self.ctx.painter.text_scale())

    def _settle(self) -> None:
        if self._lay_key == self._key():
            return
        p = self.ctx.painter
        scale = p.text_scale()
        row_h = list_row_height(scale=scale)
        line_h = pitch(p.scaled_size(p.style("panel").font.size))
        a = self.area
        lay = self.lay = rules.shop_layout((a.x, a.y, a.w, a.h), rows=len(self.offers),
                                           row_h=row_h, line_h=line_h,
                                           button_h=button_height(scale=scale))
        self.list.row_height = row_h
        self.list.box = Box(*lay.list)
        self.buy_button.box = Box(*lay.buy)
        self.put_back_button.box = Box(*lay.put_back)
        self.leave_button.box = Box(*lay.leave)
        scope = self.ctx.scope
        focused = scope.focused
        scope.set_groups([FocusGroup([self.list]),
                          FocusGroup([self.buy_button, self.put_back_button,
                                      self.leave_button])])
        scope.set_default(self.list)
        if focused is not None:
            scope.focus(focused, InputKind.KEYS, sound=False)
        self.list.focus_index(self.list.focus_row)
        self._lay_key = self._key()

    def update(self, dt: float) -> None:
        if not self.done:
            self._settle()

    # -- drawing --

    def _rows(self) -> list[ListRow]:
        return [ListRow(self.titles[o.item]) for o in self.offers]

    def _draw_row(self, p: "Painter", index: int, box: Box, look: Look) -> None:
        if not 0 <= index < len(self.offers):
            return
        offer = self.offers[index]
        if index == self.selected:
            p.widget_frame(box, "list", Look(look.state, None, True), marker=False)
        why = self.reason(index)
        dim = why in (rules.SOLD_OUT, rules.SHORT, rules.FULL)
        state = "disabled" if dim else "normal"
        cy = box.y + box.h / 2
        title, stock, price = rules.columns(box.x + ROW_PAD, box.w - 2 * ROW_PAD)
        p.text(self.row_title(offer), (title[0], cy), area="list", anchor="midleft",
               max_width=max(1.0, title[2] - ROW_PAD))
        text = self.stock_text(offer)
        if text:
            p.text(text, (stock[0], cy), area="list", state=state, anchor="midleft",
                   max_width=max(1.0, stock[2] - ROW_PAD))
        p.text(self.price_text(offer), (price[0] + price[2], cy), area="list", state=state,
               anchor="midright", max_width=price[2])

    def draw(self, canvas: "Canvas") -> None:
        self._settle()
        lay = self.lay
        if lay is None:
            return
        p = self.ctx.painter
        p.panel(Box(*lay.panel))
        x, y, w, h = lay.purse
        p.text(f"{self.money_word} ×{self.purse():,}", (x + w, y + h / 2), area="panel",
               anchor="midright", max_width=w)
        if self.message:
            x, y, w, h = lay.message
            p.text(self.message, (x, y + h / 2), area="panel", anchor="midleft", max_width=w)


__all__ = ["Shop", "TOKENS", "WORDS"]

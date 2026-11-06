"""The shop's pure rules (F64 round 2; proposal I-12 "Shop minigame").

Why this module exists: the stock table's checks, the prices it ends up with, what Buy may do
and the panel's layout can all be decided without a window, so the hooks and the session
share one copy and Studio's mirror (``minigamedata``, ADR-0008) is tested against it:

- **The stock.** ``stock`` is a dictionary of item names, in the order the shop lists them.
  Each value is the price, or ``[price, how many]``: ``5`` (5 each, any number), ``[5, 3]``
  (3 in stock this visit), ``None`` or ``[None, 3]`` (the item's own ``price`` from its
  ``lock item`` line). Prices are whole numbers from 0 (free) to 999,999; how many is 1 to
  999, or ``None`` for any number.
- **Checks.** ``problem(args)``: S1-S8 (``check_args``), the first problem only, never
  raising, never changing ``args``. ``story_problem(args, story)``: S9-S12 (``check_story``)
  against the declared items, the money item and the declared prices.
- **Play.** ``parse(args, story)`` gives the ``Offer`` rows; ``why_not`` says why Buy can't
  happen now (``None``: it can).
- **Outcomes.** ``fixed_outcome``: test and skipped buy nothing (``{}``), no changes.
- **Look.** ``shop_layout``: the panel, the purse strip, the list, the message line and the
  three buttons.

Pure: no clock, no randomness, no I/O. Imports only ``engine.minigames.api``,
``bundled.rule_text`` and the stdlib.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from engine.minigames.api import COUNT_MAX, Outcome, StoryNames, closest
from engine.minigames.bundled.rule_text import kind_words, quoted, text_problem, value_echo

ROWS_MAX: Final = 40                  # items in one stock
PRICE_MAX: Final = COUNT_MAX          # 999,999, as an item's price
STOCK_MAX: Final = 999                # how many of one item this visit
NAME_MAX: Final = 40                  # the shop's name (the heading)
ACTIONS_MAX: Final = 400              # Buy and Put back in one visit (2 ledger requests each)
NAME_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}", re.ASCII)
DEFAULTS: Final = {"stock": None, "money": None, "name": None}
REQUIRED: Final = ("stock",)
EXAMPLE: Final = '{"tea": 5, "matches": [1, 10]}'

# Why Buy can't happen (``why_not``); the session's words say each one.
SOLD_OUT, SHORT, FULL, ENOUGH = "sold_out", "short", "full", "enough"

Rect = tuple[float, float, float, float]


# --- The checks (S1-S8) ----------------------------------------------------------------------

def _name(key: object) -> bool:
    return type(key) is str and NAME_RE.fullmatch(key) is not None


def _price_problem(where: str, price: object) -> str | None:
    if price is None:
        return None
    if type(price) is not int or not 0 <= price <= PRICE_MAX:
        return (f"{where} costs {value_echo(price)}; a price is a whole number from 0 to "
                f"{PRICE_MAX:,}, or None for the item's own price.")
    return None


def _row_problem(item: str, row: object) -> str | None:
    where = f"{quoted(item)} in stock"
    if type(row) is list:                                                        # S5
        if len(row) != 2:
            return (f"{where} must be a price, or a list of the price and how many, such as "
                    f"[5, 3], but it has {len(row)} parts.")
        found = _price_problem(where, row[0])                                    # S6
        if found is not None:
            return found
        many = row[1]
        if many is not None and (type(many) is not int or not 1 <= many <= STOCK_MAX):
            return (f"{where} has {value_echo(many)} for sale; how many is a whole number "
                    f"from 1 to {STOCK_MAX}, or None for any number.")           # S7
        return None
    if row is None or type(row) is int:
        return _price_problem(where, row)                                        # S6
    return (f"{where} must be a price, such as 5, or a list of the price and how many, such "
            f"as [5, 3], but it is {kind_words(row)}.")                          # S5


def problem(args: dict) -> str | None:
    """The first refused argument's reason (S1-S8), or None."""
    stock = args.get("stock")
    if type(stock) is not dict:                                                  # S1
        return (f"stock must be a dictionary of items and prices, such as {EXAMPLE}, but it "
                f"is {kind_words(stock)}.")
    if not 1 <= len(stock) <= ROWS_MAX:                                          # S2
        return f"stock has {len(stock)} items; a shop sells 1 to {ROWS_MAX}."
    for item, row in stock.items():
        if not _name(item):                                                      # S3
            shown = value_echo(item) if type(item) is str else quoted(str(item))
            return f"{shown} in stock can't be an item name; write an item's name."
        found = _row_problem(item, row)
        if found is not None:
            return found
    money = args.get("money")                                                    # S4
    if money is not None and not _name(money):
        return f"money must be an item's name, such as \"coin\", or None, not {value_echo(money)}."
    return text_problem("name", args.get("name"), NAME_MAX)                     # S8


def _price_of(row: object) -> object:
    return row[0] if type(row) is list else row


def story_problem(args: dict, story: StoryNames) -> str | None:
    """S9-S12 against the story's declared names, or None. Meant for arguments that pass
    ``problem``; never raises for others."""
    stock = args.get("stock")
    if type(stock) is not dict:
        return None
    for item in stock:                                                           # S9
        if type(item) is str and item not in story.items:
            hint = closest(item, story.items)
            return (f"stock names the item {quoted(item)}, but there is no item named "
                    f"{quoted(item)}." + (f' Did you mean "{hint}"?' if hint is not None else ""))
    money = args.get("money")
    if money is None:                                                            # S10
        money = story.money
        if money is None:
            return ("the shop needs money, but no item is the money. Add money to an item's "
                    'line, e.g. lock item coin "Coins" money, or name one with money="coin".')
    elif money not in story.items:
        hint = closest(money, story.items)
        return (f"money names the item {quoted(str(money))}, but there is no item named "
                f"{quoted(str(money))}." + (f' Did you mean "{hint}"?' if hint is not None else ""))
    if money in stock:                                                           # S11
        return f"{quoted(str(money))} is the money, so the shop can't sell it."
    prices = dict(story.prices)
    for item, row in stock.items():                                              # S12
        if _price_of(row) is None and item not in prices:
            return (f"{quoted(str(item))} has no price: write one in stock, e.g. "
                    f'"{item}": 5, or add price 5 to its lock item line.')
    return None


# --- Play ------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Offer:
    """One row of the shop: the item, its price, and how many are for sale this visit
    (None: any number)."""
    item: str
    price: int
    stock: int | None


def money_of(args: dict, story: StoryNames) -> str:
    """The item the shop takes as money: ``money``, else the story's money item."""
    money = args.get("money")
    return money if type(money) is str else str(story.money)


def parse(args: dict, story: StoryNames) -> tuple[Offer, ...]:
    """The checked ``stock`` as ``Offer`` rows, in written order."""
    prices = dict(story.prices)
    out = []
    for item, row in args["stock"].items():
        price, many = (row[0], row[1]) if type(row) is list else (row, None)
        out.append(Offer(item, prices.get(item, 0) if price is None else price, many))
    return tuple(out)


def why_not(offer: Offer, *, bought: int, money: int, held: int, most: int,
            actions: int) -> str | None:
    """Why Buy can't happen now, or None: the visit's stock is gone (``SOLD_OUT``), the
    player can't pay (``SHORT``), can't carry more (``FULL``), or the visit has used its
    actions (``ENOUGH``)."""
    if offer.stock is not None and bought >= offer.stock:
        return SOLD_OUT
    if held >= most:
        return FULL
    if money < offer.price:
        return SHORT
    if actions >= ACTIONS_MAX:
        return ENOUGH
    return None


def fixed_outcome(args: dict) -> Outcome:
    """Test and skipped: nothing bought (``{}``), nothing changed."""
    return Outcome({})


def bought_result(bought: Mapping[str, int]) -> dict[str, int]:
    """The result: each item bought this visit and how many, in the order first bought;
    items put back to none are left out."""
    return {item: n for item, n in bought.items() if n > 0}


# --- Look ------------------------------------------------------------------------------------

PANEL_W, PAD, GAP = 960, 24, 12
MARGIN: Final = 48                    # the panel keeps this far from the area's sides
BUTTON_W: Final = 200
VISIBLE_MAX: Final = 8                # list rows shown before it scrolls
PRICE_SHARE, STOCK_SHARE = 0.22, 0.18  # of the row's width, from the right


@dataclass(frozen=True, slots=True)
class ShopLayout:
    panel: Rect
    purse: Rect
    list: Rect
    message: Rect
    buy: Rect
    put_back: Rect
    leave: Rect


def shop_layout(area: Sequence[float], *, rows: int, row_h: float, line_h: float,
                button_h: float) -> ShopLayout:
    """The panel centered in ``area``: the purse strip (one line), the list (up to
    ``VISIBLE_MAX`` rows, fewer when the area is short), the message line, and Buy, Put back
    and Leave in a row, centered."""
    ax, ay, aw, ah = (float(v) for v in area)
    w = min(float(PANEL_W), aw - 2 * MARGIN)
    fixed = 2 * PAD + line_h + GAP + GAP + line_h + GAP + button_h
    room = max(row_h, ah - 2 * PAD - fixed)
    shown = max(1, min(rows, VISIBLE_MAX, int(room // row_h)))
    h = fixed + shown * row_h
    x, y = ax + (aw - w) / 2, ay + max(0.0, (ah - h) / 2)
    inner_x, inner_w = x + PAD, w - 2 * PAD
    top = y + PAD
    purse = (inner_x, top, inner_w, line_h)
    top += line_h + GAP
    listed = (inner_x, top, inner_w, shown * row_h)
    top += shown * row_h + GAP
    message = (inner_x, top, inner_w, line_h)
    top += line_h + GAP
    bw = min(float(BUTTON_W), (inner_w - 2 * GAP) / 3)
    left = inner_x + (inner_w - (3 * bw + 2 * GAP)) / 2
    buy = (left, top, bw, button_h)
    put_back = (left + bw + GAP, top, bw, button_h)
    leave = (left + 2 * (bw + GAP), top, bw, button_h)
    return ShopLayout((x, y, w, h), purse, listed, message, buy, put_back, leave)


def columns(x: float, w: float) -> tuple[Rect, Rect, Rect]:
    """A row's title, stock and price columns (x, width as rects with no height): the title
    takes what the stock and price leave."""
    price_w, stock_w = w * PRICE_SHARE, w * STOCK_SHARE
    title_w = w - price_w - stock_w
    return ((x, 0.0, title_w, 0.0), (x + title_w, 0.0, stock_w, 0.0),
            (x + title_w + stock_w, 0.0, price_w, 0.0))


__all__ = ["ACTIONS_MAX", "DEFAULTS", "ENOUGH", "FULL", "Offer", "PRICE_MAX", "REQUIRED",
           "ROWS_MAX", "SHORT", "SOLD_OUT", "STOCK_MAX", "ShopLayout", "bought_result",
           "columns", "fixed_outcome", "money_of", "parse", "problem", "shop_layout",
           "story_problem", "why_not"]

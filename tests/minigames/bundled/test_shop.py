"""F64 round 2: the shop (``minigame shop``) and API 1.5's item counts. Rules (every refusal,
prices, why Buy can't), the session on Host U (Buy, Put back, Leave, what changes and when,
Skip Game, each input kind, every scheme, 150 % text) and the ledger's counts against the real
codex."""

import dataclasses
import random
import re
from pathlib import Path
from types import MappingProxyType

import pygame
import pytest

from engine.core.minigame_types import CodexChange, Outcome, StoryNames
from engine.minigames import api
from engine.minigames.bundled import shop_rules as rules
from engine.minigames.bundled.shop import WORDS, Shop
from engine.runtime.codex import READ_KIND, TIP_KIND, Codex, CodexIndex
from engine.runtime.commands import MeterView, MinigameBase, StartMinigame
from engine.runtime.minigame import MinigameLedger, RequestError, entry_check
from engine.runtime.persistent import PersistentStore
from engine.script.codex import CodexCategory, CodexEntry
from tests.minigames.bundled.quick_host import done_after, pad, tap, world

REPO = Path(__file__).resolve().parents[3]
ITEMS = CodexCategory("item", None, "codex_items")
TIPS = CodexCategory("tip", None, "codex_tips")


def _entry(name, title, *, cap=1, money=False, price=None, kind="item"):
    return CodexEntry(name, kind, title, ITEMS if kind == "item" else TIPS, None, (), "s",
                      "script/main.vns", 1, cap=cap, counted=cap > 1, money=money, price=price)


INDEX = CodexIndex((_entry("coin", "Coins", cap=999, money=True),
                    _entry("tea", "Jasmine Tea", cap=9, price=5),
                    _entry("matches", "Matches", cap=99),
                    _entry("lantern", "Red Lantern"),
                    _entry("moon", "The Moon", kind="tip")), (ITEMS, TIPS))
NAMES = StoryNames((), ("coin", "tea", "matches", "lantern"), ("moon",),
                   (("codex_items", ("coin", "tea", "matches", "lantern")),),
                   money="coin", prices=(("tea", 5),))
STOCK = {"tea": None, "matches": [1, 2], "lantern": 20}
ARGS = {**rules.DEFAULTS, "stock": STOCK}


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


# --- Rules ----------------------------------------------------------------------------------

@pytest.mark.parametrize("args, said", [
    ({"stock": [1]}, "stock must be a dictionary of items and prices"),
    ({"stock": {}}, "stock has 0 items; a shop sells 1 to 40."),
    ({"stock": {"bad name": 1}}, "can't be an item name"),
    ({"stock": {"tea": "5"}}, 'must be a price, such as 5, or a list'),
    ({"stock": {"tea": [5]}}, "but it has 1 parts."),
    ({"stock": {"tea": -1}}, "costs -1; a price is a whole number from 0 to 999,999"),
    ({"stock": {"tea": [5, 0]}}, "has 0 for sale; how many is a whole number from 1 to 999"),
    ({"stock": {"tea": True}}, "must be a price"),
    ({"stock": {"tea": 1}, "money": 3}, "money must be an item's name"),
    ({"stock": {"tea": 1}, "name": ""}, "name"),
])
def test_every_refusal(args, said):
    found = rules.problem({**rules.DEFAULTS, **args})
    assert found is not None and said in found, found


@pytest.mark.parametrize("args, story, said", [
    ({"stock": {"tee": 1}}, NAMES, 'there is no item named "tee". Did you mean "tea"?'),
    ({"stock": {"tea": 1}}, dataclasses.replace(NAMES, money=None), "no item is the money"),
    ({"stock": {"tea": 1}, "money": "coins"}, NAMES, 'Did you mean "coin"?'),
    ({"stock": {"coin": 1}}, NAMES, "is the money, so the shop can't sell it"),
    ({"stock": {"matches": None}}, NAMES, '"matches" has no price'),
])
def test_story_refusals(args, story, said):
    a = {**rules.DEFAULTS, **args}
    assert rules.problem(a) is None
    found = rules.story_problem(a, story)
    assert found is not None and said in found, found


def test_prices_and_why_not():
    assert rules.problem(ARGS) is None and rules.story_problem(ARGS, NAMES) is None
    offers = rules.parse(ARGS, NAMES)
    assert offers == (rules.Offer("tea", 5, None), rules.Offer("matches", 1, 2),
                      rules.Offer("lantern", 20, None))
    tea, matches, _ = offers
    ok = dict(bought=0, money=10, held=0, most=9, actions=0)
    assert rules.why_not(tea, **ok) is None
    assert rules.why_not(tea, **{**ok, "money": 4}) == rules.SHORT
    assert rules.why_not(tea, **{**ok, "held": 9}) == rules.FULL
    assert rules.why_not(matches, **{**ok, "bought": 2}) == rules.SOLD_OUT
    assert rules.why_not(tea, **{**ok, "actions": rules.ACTIONS_MAX}) == rules.ENOUGH
    assert rules.fixed_outcome(ARGS) == Outcome({})
    assert rules.bought_result({"tea": 2, "matches": 0}) == {"tea": 2}


# --- The session ---------------------------------------------------------------------------

def shop_world(game, **kwargs):
    w = world(game, Shop, **kwargs)
    w.ports.index = lambda: INDEX
    w.ports.check_entry = entry_check(INDEX)
    w.ports.money_word = lambda: "Coins"
    return w


def open_shop(w, *, held=(("coin", 30),), args=None, skippable=False):
    w.posted.clear()
    items = tuple(n for n, _ in held)
    counts = tuple(c for _, c in held)
    base = MinigameBase((), items, (), counts)
    cmd = StartMinigame("main.vns:9", 1, "shop", MappingProxyType(dict(args or ARGS)), 7, base,
                        skippable, True, NAMES)
    w.host.start(cmd)
    assert not w.fatal, [f.format() for f in w.fatal]
    w.frame()
    return w.session.plugin


def test_buy_put_back_and_leave(game):
    w = shop_world(game)
    g = open_shop(w)
    assert [g.row_title(o) for o in g.offers] == ["Jasmine Tea", "Matches", "Red Lantern"]
    assert [g.price_text(o) for o in g.offers] == ["5 Coins", "1 Coins", "20 Coins"]
    assert [g.stock_text(o) for o in g.offers] == ["", "2 left", ""]
    assert g.purse() == 30 and w.session.hint_text == WORDS["hint"]
    g.buy()                                                    # tea, 5
    g.buy()
    assert (g.purse(), g.held("tea"), g.message) == (20, 2, "Bought Jasmine Tea.")
    assert g.row_title(g.offers[0]) == "Jasmine Tea ×2"
    g.select(1)
    g.buy()
    g.buy()
    assert g.stock_text(g.offers[1]) == "Sold out"
    g.buy()
    assert g.message == "Matches is sold out."
    assert g.held("matches") == 2 and g.purse() == 18
    g.select(2)
    g.buy()                                                    # lantern, 20 > 18
    assert g.message == "Not enough Coins." and g.held("lantern") == 0
    g.put_back()                                               # the last: one match
    assert (g.purse(), g.held("matches"), g.message) == (19, 1, "Put Matches back.")
    assert w.session.ledger.changes[-2:] == (CodexChange("take", "matches"),
                                             CodexChange("give", "coin", 1))
    w.ui.click(g.leave_button.box.center)
    done = done_after(w)
    assert done.result == {"tea": 2, "matches": 1}
    assert done.changes[:2] == (CodexChange("take", "coin", 5), CodexChange("give", "tea"))


def test_full_free_and_plain_items(game):
    w = shop_world(game)
    g = open_shop(w, held=(("coin", 100), ("lantern", 1), ("tea", 8)),
                  args={**ARGS, "stock": {"tea": 0, "lantern": 1}})
    assert g.price_text(g.offers[0]) == "Free"
    g.buy()
    assert g.held("tea") == 9 and g.purse() == 100            # free: no money taken
    g.buy()
    assert g.message == "You can't carry more Jasmine Tea."
    g.select(1)
    g.buy()
    assert g.message == "You can't carry more Red Lantern."   # a plain item: one at most
    assert g.row_title(g.offers[1]) == "Red Lantern"           # no "×1" for a plain item


def test_skip_back_and_abandon_change_nothing(game):
    w = shop_world(game)
    g = open_shop(w, skippable=True)
    g.buy()
    w.host.skip(w.session)
    done = done_after(w)
    assert (done.result, done.changes) == ({}, ())
    g = open_shop(w)
    g.buy()
    w.frame(*tap(pygame.K_BACKSPACE))                          # Back leaves, with what's bought
    assert done_after(w).result == {"tea": 1}
    g = open_shop(w)
    g.buy()
    w.host.abandon()
    assert w.done() == []


@pytest.mark.parametrize("how", ["keys", "pad", "mouse"])
def test_each_input_kind(game, how):
    w = shop_world(game)
    g = open_shop(w)
    if how == "mouse":
        w.ui.click(g.list.row_box(1).center)
        assert g.selected == 1
        w.ui.click(g.buy_button.box.center)
    else:
        def press(name):
            w.frame(*(tap(name) if how == "keys" else pad(name)))
        down = pygame.K_DOWN if how == "keys" else pygame.CONTROLLER_BUTTON_DPAD_DOWN
        act = pygame.K_RETURN if how == "keys" else pygame.CONTROLLER_BUTTON_A
        scope = w.session.scope
        if scope.focused is None:
            press(down)
        assert scope.focused is g.list
        press(down)
        assert g.selected == 1
        press(act)                                             # on to Buy
        assert scope.focused is g.buy_button
        press(act)
    assert g.held("matches") == 1 and g.purse() == 29
    w.ui.click(g.leave_button.box.center)
    assert done_after(w).result == {"matches": 1}


_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\b|\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)")


def test_every_scheme_and_large_text(game, tmp_path):
    from engine.core.config import load_config
    from engine.core.paths import GamePaths
    from engine.core.schemes import SCHEMES
    from engine.minigames.tables import PluginTables
    for module in ("shop.py", "shop_rules.py"):
        text = (REPO / "engine" / "minigames" / "bundled" / module).read_text(encoding="utf-8")
        assert not _COLOR.findall(text), module
    assert len(SCHEMES) == 28
    for scheme in SCHEMES:
        root = tmp_path / scheme
        root.mkdir()
        (root / "config.toml").write_text(f'[theme]\npreset = "{scheme}"\n', encoding="utf-8")
        config = load_config(GamePaths.for_game(root)).config
        tables = PluginTables(config.theme.plugin, config.words.plugin, config.theme, dev=True)
        w = shop_world(game, config=config, tables=tables, cfg=config.theme)
        g = open_shop(w)
        g.buy()
        w.frames(2)
        assert not w.fatal, scheme
        normal = w.shell.painter.style("list", "normal").text_color
        dim = w.shell.painter.style("list", "disabled").text_color
        panel = w.shell.painter.style("panel", "normal")
        assert normal != dim or scheme, scheme
        assert panel.text_color is not None
    w = shop_world(game, reduce_motion=True)
    w.shell.painter.set_text_scale(lambda: 1.5)
    g = open_shop(w, args={**ARGS, "stock": {f"tea": 1, **{k: 1 for k in ("matches", "lantern")}}})
    w.frames(2)
    area = w.session.area
    x, y, pw, ph = g.lay.panel
    assert not w.fatal
    assert area.y <= y and y + ph <= area.bottom and area.x <= x and x + pw <= area.right


def test_registration_and_docs():
    from engine.minigames.bundled import BUNDLED, Terminal
    assert BUNDLED.index(Shop) == BUNDLED.index(Terminal) + 1
    entry = api.declarations(Shop, "engine")
    assert entry.api == "1.5" and [a.name for a in entry.sig.args] == ["stock", "money", "name"]
    docs = (REPO / "docs" / "script-language.md").read_text(encoding="utf-8")
    assert "minigame shop stock=" in docs


# --- API 1.5: the ledger's counts against the real codex ------------------------------------

def _ledger(held=(("coin", 30),)):
    base = MinigameBase((), tuple(n for n, _ in held), (), tuple(c for _, c in held))
    return MinigameLedger(base, check_meter=lambda n: None, check_entry=entry_check(INDEX),
                          game="probe", cap=lambda n: INDEX.get(n).cap)


def test_ledger_counts_and_refusals():
    led = _ledger()
    assert led.count("coin") == 30 and led.most("coin") == 999 and led.count("tea") == 0
    led.give("coin", 980)
    assert led.count("coin") == 999                            # stops at the most
    led.take("coin", 1000)
    assert led.count("coin") == 0 and "coin" not in led.items()
    led.give("lantern", 3)
    assert led.count("lantern") == 1                           # a plain item holds one
    for bad in (0, -1, True, 1.5, 1_000_000, "2"):
        with pytest.raises(RequestError) as e:
            led.give("tea", bad)
        assert e.value.code == "E275" and "a whole number from 1 to 999,999" in e.value.text
    with pytest.raises(RequestError) as e:
        led.count("moon")
    assert e.value.code == "E253"
    with pytest.raises(RequestError) as e:
        led.most("tee")
    assert e.value.code == "E253" and "tea" in e.value.text
    assert api.give("tea", 3) == CodexChange("give", "tea", 3)
    assert api.declarations  # outcomes copy the amount; a bad one is refused
    from engine.minigames.registry import DeclarationError
    assert api._change(api.take("tea", 2), "x") == CodexChange("take", "tea", 2)
    for bad in (CodexChange("give", "tea", 0), CodexChange("unlock_tip", "moon", 2),
                CodexChange("take", "tea", True)):
        with pytest.raises(DeclarationError):
            api._change(bad, "x")


def test_ledger_preview_equals_the_codex():
    rng = random.Random(64)
    names = ("coin", "tea", "matches", "lantern")
    for _ in range(30):
        led = _ledger((("coin", 30), ("tea", 2)))
        for _ in range(rng.randint(0, 40)):
            name, n = rng.choice(names), rng.choice((1, 1, 2, 5, 50, 999_999))
            (led.give if rng.random() < 0.5 else led.take)(name, n)
        store = PersistentStore(identity_scheme=1)
        store.register_kind(TIP_KIND, known=INDEX.is_tip, revocable=True)
        store.register_kind(READ_KIND, known=INDEX.has)
        codex = Codex(INDEX, store, lambda cmd: None)
        codex.give("coin", 30)
        codex.give("tea", 2)
        for change in led.changes:
            getattr(codex, change.verb)(change.name, change.amount)
        assert codex.items() == led.items()
        assert [codex.count(n) for n in names] == [led.count(n) for n in names]

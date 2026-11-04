"""F54 step S1: Gift giving (``gift_giving``): AC-F54-01 (every refusal), 02 (reactions and
outcomes), 03 (the picker, the card, the result), 04 (what changes, and when), 05 (Not now,
nothing to give, W285), 06 (no card) and 07 (each input kind, six schemes, no color
literal). AC-F54-12 (docs) is in ``test_quick_games``'s neighbour, the registration step."""

import logging
import re
from pathlib import Path

import pygame
import pytest

from engine.core.minigame_types import CodexChange, MeterChange, Outcome
from engine.minigames import api
from engine.minigames.bundled import gift_giving as gg
from engine.minigames.bundled import gift_rules as rules
from engine.minigames.bundled.gift_giving import WORDS, GiftGiving
from engine.minigames.bundled.gift_rules import NEUTRAL, Gift
from tests.minigames.bundled.quick_host import H, done_after, open_game, pad, tap, world
from tests.minigames.host_u import NAMES

REPO = Path(__file__).resolve().parents[3]
GIFTS = {"hana": {"*": ["neutral", 0, "Oh. Thank you."],
                  "paper_lantern": ["loved", 3, "You kept it all this time?"],
                  "coin": ["liked", 1]},
         "daichi": {"coin": ["disliked", -1, "I have three of these."]}}
BASE = {**rules.DEFAULTS, "gifts": GIFTS, "to": "hana"}
HELD = ("paper_lantern", "coin")


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def give(w, *, items=HELD, **args):
    g = open_game(w, "gift_giving", {**BASE, **args}, items=items)
    w.frame()
    return g


def view_of(g):
    return g.view._target


def listed(g) -> list[list[str]]:
    return [[r.entry.name for r in tab.rows] for tab in view_of(g).tabs]


def pick_by_mouse(w, g, name: str) -> None:
    view = view_of(g)
    index = [r.entry.name for r in view.tabs[view.tab].rows].index(name)
    w.ui.click(view.list.row_box(index).center)
    w.ui.click(view.pick_button.box.center)


# --- AC-F54-01 ---------------------------------------------------------------------------------

def _with(**changes) -> dict:
    return {**BASE, **changes}


REASONS = [
    (_with(gifts=[1]), 'gifts must be a dictionary of characters and their gifts, such as '
     '{"hana": {"red_lantern": ["loved", 3]}}, but it is a list.'),
    (_with(gifts={}), "gifts has 0 characters; it can have 1 to 32."),
    (_with(gifts={f"c{n}": {} for n in range(33)}), "gifts has 33 characters; it can have 1 "
     "to 32."),
    (_with(gifts={"Hana Li": {}}), '"Hana Li" can\'t be a character in gifts; write it as points '
     "names a meter: letters, digits, and _."),
    (_with(gifts={"hana": ["loved"]}), 'the gifts for "hana" must be a dictionary of items and '
     "reactions, but they are a list."),
    (_with(gifts={"hana": {f"i{n}": ["liked", 1] for n in range(201)}}), '"hana" has 201 gifts; '
     "a character can have up to 200."),
    (_with(gifts={"hana": {"red lantern": ["liked", 1]}}), '"red lantern" in the gifts for '
     '"hana" can\'t be an item name; write an item\'s name, or "*" for any other gift.'),
    (_with(gifts={"hana": {"coin": "liked"}}), 'the gift "coin" for "hana" must be a list such '
     'as ["loved", 3, "Thank you!"], but it is text.'),
    (_with(gifts={"hana": {"coin": ["liked"]}}), 'the gift "coin" for "hana" must be a list such '
     'as ["loved", 3, "Thank you!"], but it has 1 parts.'),
    (_with(gifts={"hana": {"coin": ["lovd", 1]}}), 'the gift "coin" for "hana" has the reaction '
     '"lovd"; a reaction is "loved", "liked", "neutral", or "disliked". Did you mean "loved"?'),
    (_with(gifts={"hana": {"coin": ["liked", 11]}}), 'the gift "coin" for "hana" gives 11 '
     "points; points are a whole number from -10 to 10."),
    (_with(gifts={"hana": {"coin": ["liked", 1, ""]}}), 'the line for "coin" (hana) is empty; '
     "it is 1 to 160 characters on one line."),
    (_with(gifts={"hana": {"coin": ["liked", 1, 5]}}), 'the line for "coin" (hana) must be text '
     "in quotes, but it is a whole number."),
    (_with(to="hanna"), 'to must be one of the characters in gifts ("hana", "daichi"), but it '
     'is "hanna". Did you mean "hana"?'),
    (_with(gifts={k: {} for k in ("alpha", "beta", "gamma", "delta", "eps")}, to="zed"),
     'to must be one of the characters in gifts ("alpha", "beta", "gamma", and 2 more), but it '
     'is "zed".'),
    (_with(speaker=""), "speaker is empty; it is 1 to 24 characters on one line."),
    (_with(categories="Gifts"), 'categories must be a list of 1 to 24 item category names, such '
     'as ["Gifts"], or None, but it is text.'),
    (_with(categories=[]), 'categories must be a list of 1 to 24 item category names, such as '
     '["Gifts"], or None, but it is a list.'),
    (_with(categories=["Gifts", " x"]), "category 2 in categories starts or ends with a space. "
     "Remove the space."),
    (_with(use_up=1), "use_up must be True or False, but it is 1."),
    (_with(leave="no"), 'leave must be True or False, but it is "no".'),
    (_with(result="items"), 'result must be "reaction" or "item", but it is "items". Did you '
     'mean "item"?'),
]
STORY_REASONS = [
    (_with(gifts={"hana": {"paper_lanter": ["loved", 3]}}), 'the gifts for "hana" name the item '
     '"paper_lanter", but there is no item named "paper_lanter". Did you mean "paper_lantern"?'),
    (_with(), 'the gifts for "daichi" give points, but there is no meter named "daichi". Declare '
     "it with points daichi, or set its points to 0."),
    (_with(gifts={"hana": {"coin": ["liked", 0]}, "daichi": {"coin": ["liked", 0]}},
           categories=["codex_item"]), 'there is no item category "codex_item". Did you mean '
     '"codex_items"?'),
]


def test_ac_f54_01_every_refusal():
    for args, reason in REASONS:
        before = repr(args)
        assert GiftGiving().check_args(args) == reason, reason
        assert repr(args) == before
    entry = api.declarations(GiftGiving, "engine")
    for args, reason in STORY_REASONS:
        assert GiftGiving().check_args(args) is None, reason
        assert entry.sig.check(args, NAMES) == reason
    ok = _with(gifts={"hana": GIFTS["hana"]})
    assert entry.sig.check(ok, NAMES) is None
    assert entry.sig.check({**ok, "categories": ["codex_items"]}, NAMES) is None
    # The first problem, characters and items in written order.
    assert GiftGiving().check_args(_with(gifts={"hana": {"coin": ["x", 99]}, "b c": {}})) \
        .startswith('the gift "coin" for "hana" has the reaction')
    assert GiftGiving().check_args(_with(to=None, speaker=5)).startswith("to must be")


# --- AC-F54-02 ---------------------------------------------------------------------------------

def test_ac_f54_02_reactions_and_outcomes():
    table = rules.parse(BASE)
    assert rules.reaction_for(table, "hana", "paper_lantern") == Gift(
        "loved", 3, "You kept it all this time?")
    assert rules.reaction_for(table, "hana", "coin") == Gift("liked", 1, None)
    assert rules.reaction_for(table, "hana", "umbrella") == Gift("neutral", 0, "Oh. Thank you.")
    assert rules.reaction_for(table, "daichi", "umbrella") == NEUTRAL == Gift("neutral", 0, None)
    sig = api.declarations(GiftGiving, "engine").sig
    for kind in ("test", "skipped"):
        assert sig.outcome(kind, BASE, NAMES) == Outcome("neutral")
        assert sig.outcome(kind, {**BASE, "result": "item"}, NAMES) == Outcome(None)


# --- AC-F54-03 ---------------------------------------------------------------------------------

def test_ac_f54_03_picker_card_and_result(game):
    w = world(game, GiftGiving)
    g = give(w, items=("coin",))
    assert listed(g) == [["coin"]]                             # only what the player holds
    assert view_of(g).pick_button.label() == "Give"
    assert w.session.hint_text == "Choose a gift for Hana."
    g = give(w)
    assert listed(g) == [["paper_lantern", "coin"]]
    g = give(w, categories=["codex_items"])
    assert listed(g) == [["paper_lantern", "coin"]]
    pick_by_mouse(w, g, "paper_lantern")
    assert g.mode == "card" and g.speaker == "Hana"            # to, capitalised
    assert g.card_line[0] == "You kept it all this time?" and g.verdict() == "Hana loved it."
    assert w.session.scope.widgets() == [g.continue_button]
    w.ui.click(g.continue_button.box.center)
    assert done_after(w).result == "loved"
    g = give(w, result="item", speaker="Miss Hana")
    pick_by_mouse(w, g, "coin")
    assert g.speaker == "Miss Hana" and g.verdict() == "Miss Hana liked it."
    assert g.card_line[0] == ""                                # no line: the verdict only
    w.ui.click(g.continue_button.box.center)
    assert done_after(w).result == "coin"


# --- AC-F54-04 ---------------------------------------------------------------------------------

def test_ac_f54_04_changes_on_finish_only(game):
    w = world(game, GiftGiving)
    g = give(w)
    pick_by_mouse(w, g, "paper_lantern")
    assert w.session.ledger.changes == ()                      # the card: nothing yet
    w.ui.click(g.continue_button.box.center)
    done = done_after(w)
    assert set(done.changes) == {CodexChange("take", "paper_lantern"),
                                 MeterChange("hana", "+=", 3)}
    g = give(w, use_up=False, gifts={"hana": {"coin": ["liked", 0, "Nice."]}})
    pick_by_mouse(w, g, "coin")
    w.ui.click(g.continue_button.box.center)
    assert done_after(w).changes == ()                         # kept; 0 points: no change
    # Not now, Skip Game and an abandoned run change nothing.
    g = give(w)
    w.ui.click(g.not_now.box.center)
    assert done_after(w).changes == ()
    g = open_game(w, "gift_giving", BASE, items=HELD, skippable=True)
    w.frame()
    pick_by_mouse(w, g, "paper_lantern")
    w.host.skip(w.session)
    done = done_after(w)
    assert (done.result, done.changes) == ("neutral", ())
    g = give(w)
    pick_by_mouse(w, g, "paper_lantern")
    w.host.abandon()
    assert w.done() == []


# --- AC-F54-05 ---------------------------------------------------------------------------------

W285 = ('gift_giving to "hana": the player holds no item the picker can show, so the game says '
        '"You have nothing to give." and the result is None.')


def test_ac_f54_05_not_now_and_nothing(game, caplog):
    caplog.set_level(logging.DEBUG)
    gg._WARNED.clear()
    w = world(game, GiftGiving)
    g = give(w)
    assert g.not_now.label() == "Not now" and g.not_now in w.session.scope.widgets()
    w.frame(*tap(pygame.K_BACKSPACE))
    assert done_after(w).result is None
    g = give(w, leave=False)
    assert g.not_now not in w.session.scope.widgets()
    w.frame(*tap(pygame.K_BACKSPACE))
    assert g.finishes == []
    for leave in (True, False):
        g = give(w, items=(), leave=leave)
        assert g.mode == "nothing" and w.session.scope.widgets() == [g.continue_button]
        assert g.card_line == (WORDS["nothing"], 28)
        w.frame(*tap(pygame.K_RETURN))
        assert done_after(w).result is None
    warned = [r.getMessage() for r in caplog.records if getattr(r, "code", None) == "W285"]
    assert warned == [W285]                                    # once per text
    gg._WARNED.clear()
    caplog.clear()
    w = world(game, GiftGiving, dev=False)
    give(w, items=())
    assert [r for r in caplog.records if getattr(r, "code", None) == "W285"] == []


# --- AC-F54-06 ---------------------------------------------------------------------------------

def test_ac_f54_06_no_card(game):
    """An empty verdict word and no line: Give finishes at once. (F23's word table keeps the
    default for an empty ``[words.plugin]`` value, so the session's word is set directly.)"""
    w = world(game, GiftGiving)
    g = give(w)
    g.word["liked"] = ""
    pick_by_mouse(w, g, "coin")                                # no line, verdict word ""
    assert g.finishes == ["liked"] and g.mode == "pick"
    assert set(done_after(w).changes) == {CodexChange("take", "coin"),
                                          MeterChange("hana", "+=", 1)}
    g = give(w)
    g.word["loved"] = ""
    pick_by_mouse(w, g, "paper_lantern")                       # a line: the card shows
    assert g.mode == "card" and g.verdict() == ""


# --- AC-F54-07 ---------------------------------------------------------------------------------

def _keys(w, how, name):
    w.frame(*(tap(name) if how == "keys" else pad(name)))


@pytest.mark.parametrize("how", ["keys", "pad", "mouse"])
def test_ac_f54_07_each_input_kind(game, how):
    w = world(game, GiftGiving)
    down = pygame.K_DOWN if how == "keys" else pygame.CONTROLLER_BUTTON_DPAD_DOWN
    act = pygame.K_RETURN if how == "keys" else pygame.CONTROLLER_BUTTON_A
    g = give(w)
    if how == "mouse":
        pick_by_mouse(w, g, "coin")
        w.ui.click(g.continue_button.box.center)
    else:
        scope = w.session.scope
        if scope.focused is None:
            _keys(w, how, down)                                # first focus: the list
        assert scope.focused is view_of(g).list
        _keys(w, how, down)                                    # the second row: coin
        assert view_of(g).selected == "coin"
        _keys(w, how, act)                                     # to Give
        assert scope.focused is view_of(g).pick_button
        _keys(w, how, act)                                     # Give
        assert g.mode == "card"
        if scope.focused is None:
            _keys(w, how, down)
        _keys(w, how, act)                                     # Continue
    assert done_after(w).result == "liked"
    g = give(w)
    if how == "mouse":
        w.ui.click(g.not_now.box.center)
    else:
        scope = w.session.scope
        for _ in range(4):
            if scope.focused is g.not_now:
                break
            _keys(w, how, down)
        assert scope.focused is g.not_now
        _keys(w, how, act)
    assert done_after(w).result is None


_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\b|\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)")


def test_ac_f54_07_schemes_and_colors(game, tmp_path):
    from engine.core.config import load_config
    from engine.core.paths import GamePaths
    from engine.core.schemes import SCHEMES
    from engine.minigames.tables import PluginTables
    text = (REPO / "engine" / "minigames" / "bundled" / "gift_giving.py").read_text(
        encoding="utf-8")
    assert not _COLOR.findall(text)
    for scheme in SCHEMES:
        root = tmp_path / scheme
        root.mkdir()
        (root / "config.toml").write_text(f'[theme]\npreset = "{scheme}"\n', encoding="utf-8")
        config = load_config(GamePaths.for_game(root)).config
        tables = PluginTables(config.theme.plugin, config.words.plugin, config.theme, dev=True)
        w = world(game, GiftGiving, config=config, tables=tables, cfg=config.theme)
        g = give(w)
        w.frame(*tap(pygame.K_DOWN))
        assert w.session.scope.focused is not None and w.session.scope.visible
        pick_by_mouse(w, g, "coin")
        w.frames(2)
        assert g.mode == "card" and not w.fatal, scheme
    w = world(game, GiftGiving)                                # 150 % text: still fits
    w.shell.painter.set_text_scale(lambda: 1.5)
    g = give(w)
    w.frames(2)
    pick_by_mouse(w, g, "paper_lantern")
    w.frames(2)
    area = w.session.area
    x, y, cw, ch = g.card.panel
    assert g.mode == "card" and not w.fatal
    assert area.y <= y and y + ch <= area.bottom and area.x <= x and x + cw <= area.right

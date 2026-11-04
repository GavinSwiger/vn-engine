"""F53 step P3: Hand game (``hand_game``): AC-F53-23 (fair hands from ``ctx.random``), 24
(``kind`` always ends "won"), 25 (``cheat`` and ``sly``), 26 (the early end, result words,
Continue) and 27 (hand pictures)."""

import itertools

import pygame
import pytest

from engine.core.paths import GamePaths
from engine.minigames.bundled import hand_rules as rules
from engine.minigames.bundled.hand_game import WORDS, HandGame
from engine.minigames.bundled.hand_rules import Score, beats, her_hand, loses_to, outcome
from engine.render.canvas import Canvas
from tests.minigames.bundled.quick_host import done_after, open_game, world
from tests.render.conftest import make_assets


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def match(w, **args):
    g = open_game(w, "hand_game", {**rules.DEFAULTS, "opponent": "Hana", **args})
    w.frame()
    return g


def press(w, button):
    w.ui.click(button.box.center)


def play(w, g, choose) -> None:
    """Rounds until Continue shows; ``choose(fair)`` gives the player's hand."""
    while g.continue_button not in w.session.scope.widgets():
        press(w, g.hand_buttons[rules.HANDS.index(choose(g.fair_hands[-1]))])
        w.frames(40)
        if g.next_button in w.session.scope.widgets():
            press(w, g.next_button)


# --- AC-F53-23 ---------------------------------------------------------------------------------

def test_ac_f53_23_fair_hands_from_ctx_random(game):
    w = world(game, HandGame)
    g = match(w, rounds=9)
    assert len(g.fair_hands) == 1 and g.shown is None          # drawn before the pick
    play(w, g, lambda fair: fair)                              # draws only: all 9 rounds
    first = list(g.fair_hands)
    assert len(first) == 9 and set(first) <= set(rules.HANDS)
    g = match(w, rounds=9)                                     # a restore: same seed
    play(w, g, lambda fair: fair)
    assert g.fair_hands == first
    for mode in ("kind", "cheat", "sly"):                      # one pick per round, any mode
        g = match(w, rounds=9, mode=mode)
        press(w, g.hand_buttons[0])
        w.frames(40)
        press(w, g.next_button)
        assert g.fair_hands == first[:2], mode


# --- AC-F53-24 ---------------------------------------------------------------------------------

@pytest.mark.parametrize("rounds", [1, 3, 9])
def test_ac_f53_24_kind_always_wins(rounds):
    for player in rules.HANDS:
        for fairs in itertools.product(rules.HANDS, repeat=rounds):
            score = Score()
            for fair in fairs:
                her = her_hand("kind", fair, player, score, rounds)
                assert not her.switched
                score = score.after(outcome(player, her.final))
                if rules.finished(score, rounds):
                    break
            assert rules.result_of(score) == "won", (player, fairs)


# --- AC-F53-25 ---------------------------------------------------------------------------------

def test_ac_f53_25_cheat_and_sly(game):
    for player, fair in itertools.product(rules.HANDS, repeat=2):
        cheat = her_hand("cheat", fair, player, Score(), 3)
        sly = her_hand("sly", fair, player, Score(), 3)
        assert outcome(player, cheat.final) != "win" and outcome(player, sly.final) != "win"
        assert not sly.switched and cheat.shown == fair
        if outcome(player, fair) != "win":                     # her fair hand doesn't lose
            assert cheat == sly == rules.Hand(fair, fair)
        else:
            assert cheat.switched and cheat.final == sly.final == beats(player)
    w = world(game, HandGame)
    g = match(w, mode="cheat")
    fair = g.fair_hands[-1]
    press(w, g.hand_buttons[rules.HANDS.index(beats(fair))])   # her fair hand would lose
    assert g.shown == fair and g.phase == "switch" and w.session.scope.widgets() == []
    w.frames(34)                                               # the click's frame + 34 < 0.6 s
    assert g.shown == fair
    w.frames(2)
    assert g.shown == beats(beats(fair)) and g.shake_t is not None
    assert g.captions == ["Hana switched hands! Hana wins this round."]
    assert g.score == Score(losses=1)
    g = match(w, mode="sly")
    fair = g.fair_hands[-1]
    press(w, g.hand_buttons[rules.HANDS.index(beats(fair))])
    assert g.shown == beats(beats(fair)) and g.phase == "result"
    assert g.captions == ["Hana wins this round."]
    g = match(w, mode="cheat")                                 # her fair hand wins: no switch
    fair = g.fair_hands[-1]
    press(w, g.hand_buttons[rules.HANDS.index(loses_to(fair))])
    assert g.shown == fair and g.phase == "result" and g.captions == ["Hana wins this round."]


# --- AC-F53-26 ---------------------------------------------------------------------------------

def test_ac_f53_26_early_end_and_results(game):
    assert rules.finished(Score(wins=2), 3) and not rules.finished(Score(wins=1), 3)
    assert rules.finished(Score(wins=1, losses=1, draws=1), 3)
    assert not rules.finished(Score(wins=1, losses=1), 3)
    assert [rules.result_of(s) for s in (Score(2, 1), Score(0, 1), Score(1, 1, 1))] == [
        "won", "lost", "draw"]
    assert rules.fixed_outcome("test", {"mode": "cheat"}).result == "lost"
    assert rules.fixed_outcome("test", {"mode": "kind"}).result == "won"
    assert rules.fixed_outcome("skipped", {"mode": "sly"}).result == "draw"
    w = world(game, HandGame)
    for choose, word, rounds_played in ((beats, "won", 2), (loses_to, "lost", 2),
                                        (lambda f: f, "draw", 3)):
        g = match(w)
        play(w, g, choose)
        assert g.round_no == rounds_played
        assert g.captions[-1] == WORDS[word]
        assert g.round_text() == f"Round {rounds_played} of 3"
        press(w, g.continue_button)
        assert g.finishes == [word]
        assert done_after(w).result == word
    g = match(w)
    play(w, g, beats)
    assert g.score_text() == "You 2 – 0 Hana"


# --- AC-F53-27 ---------------------------------------------------------------------------------

def test_ac_f53_27_hand_pictures(game, tmp_path):
    from engine.core.config import load_config
    from engine.minigames.tables import PluginTables
    (game / "gui").mkdir()
    picture = pygame.Surface((600, 400))
    picture.fill((10, 200, 10))
    pygame.image.save(picture, str(game / "gui" / "rock.png"))
    (game / "config.toml").write_text(
        '[theme.plugin.hand_game.hand]\nrock_image = "gui/rock.png"\n'
        'paper_image = "gui/missing.png"\n', encoding="utf-8")
    config = load_config(GamePaths.for_game(game)).config
    tables = PluginTables(config.theme.plugin, config.words.plugin, config.theme, dev=True)
    w = world(game, HandGame, config=config, tables=tables, cfg=config.theme)
    assets = make_assets(GamePaths.for_game(game))
    w.shell.assets = assets
    w.ui.canvas = Canvas(assets)
    g = match(w, rounds=3)
    assert set(g.pictures) == {"rock"}
    assert g.face("rock") is g.pictures["rock"]
    assert g.face("paper") == "Paper" and g.face("scissors") == "Scissors"   # missing: word
    assert g.face(None) == "?"
    press(w, g.hand_buttons[0])                                # the player shows rock
    w.frame()
    card = g.lay.cards[0]
    inner_center = (card[0] + card[2] / 2, card[1] + (card[3] + 16 + 34) / 2)
    r, gr, b = w.ui.px(*inner_center)                          # scaled down into the card
    assert abs(r - 10) <= 2 and abs(gr - 200) <= 2 and abs(b - 10) <= 2

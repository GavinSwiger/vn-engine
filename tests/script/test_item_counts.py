"""F64 round 1 at load: ``count``/``money`` on item declarations, amounts on ``unlock|lock
item``, and the whole-game checks (E436-E441, W305-W307; specs/F64-items/SPEC.md)."""

import pytest

from engine.core.paths import GamePaths
from engine.script.codex import ITEM_COUNT_MAX, CodexLock
from engine.script.identity import walk_block
from engine.script.loader import load_story
from tests.runtime.effects_story import write_game


def _load(tmp_path, top="", lines=()):
    body = "".join("    " + line + "\n" for line in lines) or '    "x"\n'
    root = write_game(tmp_path, f'{top}label start:\n{body}')
    return load_story(GamePaths(root.resolve()))


def _codes(result):
    return [e.code for e in result.errors]


def _warned(result):
    return [w for w in result.warnings if w.code != "W142"]     # lore: no unlock tip line


def _decls(result):
    return {d.name: d for d in result.program.codex}


@pytest.mark.parametrize("line, cap, counted, money", [
    ('lock item coin "Coins" in "Purse" count 0 to 999 money', 999, True, True),
    ('lock item coin "Coins" count', ITEM_COUNT_MAX, True, False),
    ('lock item coin "Coins" count 50', 50, True, False),
    ('lock item coin "Coins" money', ITEM_COUNT_MAX, True, True),
    ('lock item coin "Coins" money count 9 in "Purse"', 9, True, True),
    ('lock item coin "Coins" image coin bag count 5', 5, True, False),
    ('lock item coin "Coins" in "Purse"', 1, False, False),
])
def test_declarations(tmp_path, line, cap, counted, money):
    result = _load(tmp_path, line + "\n", ["unlock item coin"])
    assert not result.errors, [e.format() for e in result.errors]
    entry = _decls(result)["coin"]
    assert (entry.cap, entry.counted, entry.money) == (cap, counted, money)


@pytest.mark.parametrize("line, code, start", [
    ('lock tip coin "Coins" count', "E437", "tip coin can't have a count"),
    ('lock tip coin "Coins" money', "E437", "tip coin can't be the money"),
    ('lock item coin "Coins" count 5 to 9', "E438", "a count always starts at 0"),
    ('lock item coin "Coins" count 0 to', "E438", "count 0 to needs the most"),
    ('lock item coin "Coins" count 0 to 2000000', "E438", "the most of coin a player can"),
    ('lock item coin "Coins" count 0', "E438", "the most of coin"),
    ('lock item coin "Coins" count 3 count 4', "E250", 'this line has "count 4" left over'),
])
def test_declaration_errors(tmp_path, line, code, start):
    result = _load(tmp_path, line + "\n")
    assert _codes(result)[:1] == [code]
    assert result.errors[0].message.startswith(start), result.errors[0].message


TOP = 'lock item coin "Coins" count 0 to 999 money\nlock item key "Key"\nlock tip lore "Lore"\n'


def test_amounts(tmp_path):
    result = _load(tmp_path, TOP, ["unlock item coin 30", "lock item coin 5", "unlock item key",
                                   "unlock tip lore"])
    assert not result.errors, [e.format() for e in result.errors]
    locks = [s for s, _ in walk_block(result.program.labels["start"].block)
             if isinstance(s, CodexLock)]
    assert [(s.unlock, s.name, s.amount, s.written) for s in locks] == [
        (True, "coin", 30, True), (False, "coin", 5, True), (True, "key", 1, False),
        (True, "lore", 1, False)]
    # A plain line keeps F21's identity (its save position); a written amount joins it.
    assert locks[2].identity_key() == ("unlock", "item", "key")
    assert locks[0].identity_key() == ("unlock", "item", "coin", "30")


@pytest.mark.parametrize("line, start", [
    ("unlock item coin 0", 'the amount in unlock item coin is a whole number from 1 to'),
    ("unlock item coin -5", "the amount in unlock item coin"),
    ("lock item coin 2.5", "the amount in lock item coin"),
    ("lock item coin all", 'lock item coin takes a number after the name, but found "all"'),
    ("unlock tip lore 2", "a tip is given or forgotten all at once"),
])
def test_amount_errors(tmp_path, line, start):
    result = _load(tmp_path, TOP, [line])
    assert _codes(result)[:1] == ["E436"]
    assert result.errors[0].message.startswith(start), result.errors[0].message


def test_amount_error_says_how_to_take(tmp_path):
    message = _load(tmp_path, TOP, ["unlock item coin -5"]).errors[0].message
    assert message.endswith("To take some away, write lock item coin 5.")


def test_two_money_items(tmp_path):
    result = _load(tmp_path, TOP + 'lock item gold "Gold" money\n')
    assert _codes(result) == ["E439"]
    assert "gold and coin" in result.errors[0].message


@pytest.mark.parametrize("line, code, start", [
    ('if items.count("coinz") > 1:', "E440", 'there is no item named "coinz". Did you mean'),
    ('if codex.count("lore") > 1:', "E440", '"lore" is a tip, not an item'),
    ('if items.count(3) > 1:', "E440", "items.count needs an item's name in quotes"),
    ('if items.total > 1:', "E441", "there is no items.total."),
])
def test_count_reads_are_checked(tmp_path, line, code, start):
    result = _load(tmp_path, TOP, [line, '    "x"'])
    assert _codes(result) == [code]
    assert result.errors[0].message.startswith(start), result.errors[0].message


def test_count_reads_that_are_fine(tmp_path):
    result = _load(tmp_path, TOP, ['if items.count("coin") > 1 and codex.count("key"):',
                                   '    "x"', '$ n = items.count("coin")'])
    assert not result.errors and [w.code for w in _warned(result)] == ["W323"]  # codex.count


def test_a_story_variable_named_items(tmp_path):
    result = _load(tmp_path, TOP + "default items = []\n",
                   ['$ items.append("x")', 'if items.count("coin") > 0:', '    "x"'])
    assert not result.errors
    assert [w.code for w in _warned(result)] == ["W306"]
    assert "Rename your variable" in _warned(result)[0].message


def test_amount_warnings(tmp_path):
    result = _load(tmp_path, TOP.replace("999", "50"),
                   ["unlock item key 3", "unlock item coin 60", "unlock item coin 50"])
    assert not result.errors
    assert [w.code for w in _warned(result)] == ["W305", "W307"]
    assert _warned(result)[1].message.startswith("coin holds at most 50")

"""F64 round 2: ``price <n>`` on item declarations (the shop's default price), at load and in
Studio's reading and writing of the line."""

import pytest

from engine.core.paths import GamePaths
from engine.script.loader import load_story
from engine.tools.editor import declarations as dec
from tests.runtime.effects_story import write_game


def _load(tmp_path, top):
    root = write_game(tmp_path, f'{top}label start:\n    "x"\n')
    return load_story(GamePaths(root.resolve()))


@pytest.mark.parametrize("line, price", [
    ('lock item tea "Jasmine Tea" price 5', 5),
    ('lock item tea "Jasmine Tea" in "Things" price 0 count 9', 0),
    ('lock item tea "Jasmine Tea" image tea cup price 12', 12),
    ('lock item tea "Jasmine Tea"', None),
])
def test_price_declared(tmp_path, line, price):
    result = _load(tmp_path, line + "\n")
    assert not result.errors
    entry = next(e for e in result.program.codex if e.name == "tea")
    assert entry.price == price


@pytest.mark.parametrize("line, code, said", [
    ('lock tip tea "Tea" price 5', "E437", "can't have a price"),
    ('lock item tea "Tea" price', "E438", "found nothing"),
    ('lock item tea "Tea" price -1', "E438", "the price of tea"),
    ('lock item tea "Tea" price 1000000', "E438", "0 to 999,999"),
])
def test_price_refused(tmp_path, line, code, said):
    result = _load(tmp_path, line + "\n")
    assert [e.code for e in result.errors][:1] == [code]
    assert said in result.errors[0].message


def test_studio_reads_and_writes_price():
    line = 'lock item tea "Tea" in "Things" count 0 to 9 price 5'
    values = dec._codex_read(line.split()[3:], [])
    assert values is not None and values["price"] == 5 and values["count"] == 9
    assert dec.codex_lines("item", "tea", values)[0] == line
    assert dec.codex_lines("item", "tea", {**values, "price": None})[0] == \
        'lock item tea "Tea" in "Things" count 0 to 9'
    assert not dec.codex_ok({**values, "price": -1})

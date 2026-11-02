"""Saved stages for AC-F04-19 and AC-F04-23 (F04 ``06-acceptance.md`` §5.3). Stdlib only.

- ``valid_stages(count, seed)``: ``StageState`` values any story could reach (backgrounds or
  none, up to 12 sprites in draw order, every kind of position, ``int`` and ``float``
  numbers at the range edges), for the JSON round trip (TR-F04-02).
- ``mutations(bases, count, seed)``: stage JSON objects, each a base with one to three
  mutations (type swaps, range edges, key drops and additions, duplicate tags, order breaks,
  long and odd strings), for the hostile-save fuzz (TR-F04-02, 04 §9.1).

Deterministic for a seed.
"""

import copy
import random

from engine.runtime.stage import SpriteState, StageState

WORDS = ("hana", "daichi", "stall", "bg", "river_night", "dusk", "happy", "sad", "x1", "Ünï",
         "ハナ", "a_b", "Z")
POSITIONS = ("left", "center", "right", "stall_spot", "no_such_place", "hana_close")
EDGE_NUMBERS = (-1280, 2560, 0, 400, 400.5, -1280.0, 2560.0, 1e-9, 1059.99)
EDGE_ZOOMS = (0.25, 4.0, 1.0, 1.5, 2.0, 3.999)
EDGE_LAYERS = (-100, 100, 0, 10, -1)

HOSTILE = [None, True, False, 0, 1, -1, 1.0, float("nan"), float("inf"), float("-inf"), "",
           " ", "a  b", "a b c d e f", "../x.png", "images/hana.png", "zoom", "call", "show",
           "le ft", "x" * 101, "x " * 300, "a\x00b", "\ud800", [], [1, 2, 3], [True],
           [float("nan")], [3000], [-1281], {}, {"tag": "x"}, 10**4300, 257, 101, -101, 0.2,
           4.01, "1", "on"]


def _name(rng: random.Random, words: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(words))


def _position(rng: random.Random):
    kind = rng.randrange(3)
    if kind == 0:
        return rng.choice(POSITIONS)
    if kind == 1:
        return (rng.choice(EDGE_NUMBERS),)
    return (rng.choice(EDGE_NUMBERS), rng.choice(EDGE_NUMBERS))


def valid_stages(count: int = 200, seed: int = 1) -> list[StageState]:
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        background = None if rng.random() < 0.2 else _name(rng, rng.randint(1, 5))
        tags = rng.sample([f"t{i}" for i in range(40)] + list(WORDS), rng.randint(0, 12))
        layers = sorted(rng.choice(EDGE_LAYERS) for _ in tags)
        sprites = tuple(
            SpriteState(tag, _name(rng, rng.randint(1, 5)), _position(rng), layer,
                        float(rng.choice(EDGE_ZOOMS)), rng.random() < 0.5)
            for tag, layer in zip(tags, layers))
        out.append(StageState(background, sprites))
    return out


def _mutate(obj: dict, rng: random.Random) -> None:
    sprites = obj["sprites"]
    kind = rng.randrange(9)
    if kind == 0:                                           # swap a stage key's value
        obj[rng.choice(("background", "sprites"))] = rng.choice(HOSTILE)
    elif kind == 1:                                         # drop or add a stage key
        if rng.random() < 0.5:
            obj.pop(rng.choice(("background", "sprites")), None)
        else:
            obj[rng.choice(("x", "Background", "stage", ""))] = rng.choice(HOSTILE)
    elif not sprites:
        sprites.append(rng.choice(HOSTILE))
    elif kind in (2, 3, 4):                                 # a sprite field: type or range
        entry = rng.choice(sprites)
        if type(entry) is dict:
            key = rng.choice(("tag", "image", "at", "layer", "zoom", "flip"))
            entry[key] = rng.choice(HOSTILE)
    elif kind == 5:                                         # drop or add a sprite key
        entry = rng.choice(sprites)
        if type(entry) is dict:
            if rng.random() < 0.5 and entry:
                entry.pop(rng.choice(sorted(entry)))
            else:
                entry[rng.choice(("extra", "Tag", "x"))] = 1
    elif kind == 6:                                         # a duplicate tag
        sprites.append(copy.deepcopy(rng.choice(sprites)))
    elif kind == 7:                                         # break the layer order
        entry = rng.choice(sprites)
        if type(entry) is dict:
            entry["layer"] = rng.choice((-100, 100, 50))
            sprites.reverse()
    else:                                                   # too many sprites
        while len(sprites) < 257:
            sprites.append(copy.deepcopy(sprites[0]))


def mutations(bases: list[dict], count: int, seed: int = 1):
    """``count`` mutated copies of the stage JSON ``bases`` (one to three mutations each)."""
    rng = random.Random(seed)
    for _ in range(count):
        obj = copy.deepcopy(rng.choice(bases))
        for _ in range(rng.randint(1, 3)):
            if type(obj) is dict and type(obj.get("sprites")) is list:
                _mutate(obj, rng)
            elif type(obj) is dict:
                obj["sprites"] = rng.choice(HOSTILE)
        yield obj

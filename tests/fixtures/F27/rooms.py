"""F27's room fixtures (``06-acceptance.md`` §5): Story R, Template R's rooms read from
``template/script/rooms.vns`` (one source: the ``define``s the headless tests load), the attic's
stages (§0.2), the fixture images, a seeded room generator, the bound room, and the stuck
rooms for W179's cap.

The ``define`` values in ``rooms.vns`` are Python literals (``True``), so each is read with
``ast.literal_eval``.
"""

import ast
import copy
import random
from pathlib import Path

from engine.core.minigame_types import StoryNames

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template"
IMAGES = HERE / "images"
ITEMS = ("rusty_key", "string", "magnet", "magnet_string", "door_key")
TITLES = {"rusty_key": "Rusty Key", "string": "String", "magnet": "Magnet",
          "magnet_string": "Magnet on a String", "door_key": "Door Key",
          "lanterns": "Paper Lanterns"}
STORY = StoryNames(meters=(), items=ITEMS, tips=("lanterns",),
                   item_categories=(("codex_items", ITEMS),))


def _rooms() -> dict[str, dict]:
    text = (TEMPLATE / "script" / "rooms.vns").read_text(encoding="utf-8")
    found: dict[str, dict] = {}
    for chunk in text.split("define ")[1:]:
        name, _, body = chunk.partition(" = ")
        found[name.strip()] = ast.literal_eval(body.strip())
    return found


ROOMS = _rooms()


def room(name: str = "attic") -> dict:
    """A deep copy of a Template R room."""
    return copy.deepcopy(ROOMS[name])


# §0.2's stages of the attic: (gone, held, shown).
S3_G = ("hook", "drawer", "magnet", "string")
S4_G = (*S3_G, "vent")
S5_G = (*S4_G, "glint", "door")
STAGES = {
    "S0": ((), (), ("window", "hook", "drawer", "string", "vent", "door")),
    "S1": (("hook",), ("rusty_key",), ("window", "drawer", "string", "vent", "door")),
    "S2": (("hook", "drawer"), (), ("window", "magnet", "string", "vent", "door")),
    "S3": (S3_G, ("magnet", "string"), ("window", "vent", "door")),
    "S4": (S4_G, ("magnet_string",), ("window", "glint", "door")),
    "S5": (S5_G, (), ("window", "out")),
}


def stage(name: str) -> tuple[dict, tuple[str, ...]]:
    """(args, held) of the attic at a stage."""
    gone, held, _ = STAGES[name]
    return {"room": room(), "state": {"gone": list(gone)} if gone else None}, held


def image_file(name: str) -> str:
    """The game-relative file of a fixture image name (``bg attic`` → ``images/bg attic.png``);
    a missing name (``attic nope``) gives the asset manager's placeholder."""
    return f"images/{name}.png"


def random_room(rng: random.Random, n: int) -> dict:
    """A valid room of ``n`` plain hotspots (2–12) at random places and sizes, the last an
    exit (layout-only rows: no take, use, or after)."""
    spots = {}
    for i in range(n):
        w, h = rng.randint(32, 300), rng.randint(32, 300)
        spots[f"s{i}"] = {"rect": [rng.randint(0, 1280 - w), rng.randint(0, 720 - h), w, h],
                          "label": f"Spot {i}"}
    spots[f"s{n - 1}"]["exit"] = True
    return {"background": "bg attic", "hotspots": spots}


def bound_room() -> dict:
    """The bounds (AC-F27-25): 40 hotspots with 8 use names each (one exit), 40 recipes."""
    spots = {f"s{i}": {"rect": [i * 30, 100, 32, 32], "label": f"Spot {i}",
                       "use": [f"i{i}_{j}" for j in range(8)]} for i in range(39)}
    spots["out"] = {"rect": [1200, 600, 40, 40], "label": "Door", "exit": True}
    combine = {f"m{k}": [f"a{k}", f"b{k}"] for k in range(40)}
    return {"background": "bg attic", "hotspots": spots, "combine": combine}


def bound_names() -> StoryNames:
    items = tuple(sorted({n for s in bound_room()["hotspots"].values()
                          for n in s.get("use", ())}
                         | {n for k in range(40) for n in (f"m{k}", f"a{k}", f"b{k}")}))
    return StoryNames((), items, ())


def stuck_room(n: int) -> dict:
    """Room S with a distinct background: ``n`` gives a distinct W179 text."""
    r = room("room_s")
    r["background"] = f"bg stuck {n}"
    return r


__all__ = ["IMAGES", "ITEMS", "ROOMS", "STAGES", "STORY", "TEMPLATE", "TITLES", "bound_names",
           "bound_room", "image_file", "random_room", "room", "stage", "stuck_room"]

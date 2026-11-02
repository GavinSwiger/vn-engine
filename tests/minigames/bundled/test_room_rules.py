"""F27-1: the puzzle room's rules and declarations (F27 ``06``: AC-F27-01, 02, 04, 05, 06,
16, 17; with the unit rows of AC-F27-20 and 21, whose texts this module produces).

Direct calls into ``room_rules`` (harness "Rules") with Story R and the base args (design
§5.2's attic, ``state=None``). The refusal and warning texts are F27 ``01`` §5.3–§5.4's drafts
and ``04`` §5.1's † forms as this module words them: a narrative-designer rewording updates
these tables, not the ACs. The session rows (AC-F27-08 onward) are F27-3's.
"""

import ast
import copy
import random
import re
import sys
from pathlib import Path

import pytest

from engine.core.graphemes import graphemes
from engine.core.minigame_types import REQUIRED, ArgSpec, Outcome, StoryNames
from engine.minigames import api, bundled, messages
from engine.minigames.bundled import room_rules
from engine.minigames.bundled.phone_chat import PhoneChat
from engine.minigames.bundled.puzzle_room import PuzzleRoom
from engine.minigames.bundled.room_rules import (
    Caption,
    Finish,
    activate,
    combine_pair,
    cover_box,
    fit_box,
    fixed_outcome,
    known_gone,
    parse,
    picker_layout,
    problem,
    put_away_label,
    reach,
    result_of,
    ring_rects,
    room_layout,
    run_gone,
    shown,
    story_problem,
    tag_box,
    w179_text,
    w180_texts,
)
from engine.ui import layouts
from tests.fakes.fixed_font import FixedFont
from tests.minigames.conftest import plugin, write

REPO = Path(__file__).resolve().parents[3]
BUNDLED_DIR = Path(bundled.__file__).parent
SIG = api.declarations(PuzzleRoom, "engine").sig
S = StoryNames(meters=(), items=("rusty_key", "string", "magnet", "magnet_string", "door_key"),
               tips=("lanterns",))
ATTIC = {
    "background": "bg attic",
    "hotspots": {
        "window": {"rect": [880, 90, 220, 260], "label": "Window",
                   "look": "Snow, as far as you can see."},
        "hook": {"rect": [140, 300, 64, 96], "label": "Coat hook", "take": "rusty_key",
                 "image": "attic key"},
        "drawer": {"rect": [520, 420, 200, 90], "label": "Desk drawer", "use": "rusty_key",
                   "look": "Locked.", "nope": "It doesn't fit."},
        "magnet": {"rect": [590, 440, 60, 50], "label": "Magnet", "after": "drawer",
                   "take": "magnet", "image": "attic magnet"},
        "string": {"rect": [300, 520, 80, 60], "label": "Ball of string", "take": "string"},
        "vent": {"rect": [1000, 560, 160, 100], "label": "Vent", "use": "magnet_string",
                 "look": "Something glints down there."},
        "glint": {"rect": [1040, 580, 80, 60], "label": "Key", "after": "vent",
                  "take": "door_key"},
        "door": {"rect": [40, 120, 180, 420], "label": "Door", "use": "door_key",
                 "look": "Locked tight."},
        "out": {"rect": [40, 120, 180, 420], "label": "Door", "after": "door", "exit": True},
    },
    "combine": {"magnet_string": ["magnet", "string"]},
}
ORDER = list(ATTIC["hotspots"])
# 06 §0.2's stages: (G, H, shown).
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


def attic(*, spots: dict | None = None, drop: tuple = (), **top) -> dict:
    """The attic, deep-copied, with ``spots`` merged per hotspot (a value of None removes a
    field; a non-dict value replaces the hotspot), ``drop`` hotspots removed, and ``top``
    keys replaced (``...`` removes one)."""
    room = copy.deepcopy(ATTIC)
    for key, fields in (spots or {}).items():
        if type(fields) is not dict or key not in room["hotspots"]:
            room["hotspots"][key] = fields
            continue
        for field, value in fields.items():
            if value is None:
                room["hotspots"][key].pop(field, None)
            else:
                room["hotspots"][key][field] = value
    for key in drop:
        del room["hotspots"][key]
    for key, value in top.items():
        if value is ...:
            room.pop(key, None)
        else:
            room[key] = value
    return room


def base(room: object = None, state: object = None) -> dict:
    return {"room": attic() if room is None else room, "state": state}


def check(args: dict, story: StoryNames = S) -> str | None:
    return problem(args) or story_problem(args, story)


def _ordered(v: object) -> object:
    if type(v) is dict:
        return [(k, _ordered(x)) for k, x in v.items()]
    if type(v) is list:
        return [_ordered(x) for x in v]
    return v


def m20(text: str, size: int) -> float:
    return FixedFont(size).size(text)[0]


def ten(text: str, size: int) -> float:
    """06 AC-F27-16's fake measure: 10 per code point."""
    return 10 * len(text)


# --- AC-F27-01: declarations, imports, and codes --------------------------------------------

def _imports(path: Path) -> set[str]:
    """Imports outside ``if TYPE_CHECKING:``."""
    found: set[str] = set()

    def visit(nodes):
        for node in nodes:
            if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING":
                continue
            if isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                found.add(node.module)
            for field in ("body", "orelse", "handlers", "finalbody"):
                visit(getattr(node, field, []) or [])

    visit(ast.parse(path.read_text(encoding="utf-8")).body)
    return found


def test_ac_f27_01_declarations_imports_and_codes(game, load):
    # BUNDLED: PuzzleRoom once, after PhoneChat, from one import line (F25 07 I-8).
    tree = ast.parse((BUNDLED_DIR / "__init__.py").read_text(encoding="utf-8"))
    modules = [n.module for n in tree.body if isinstance(n, ast.ImportFrom)]
    assert modules.count("engine.minigames.bundled.puzzle_room") == 1
    assert bundled.BUNDLED.count(PuzzleRoom) == 1
    assert bundled.BUNDLED.index(PhoneChat) < bundled.BUNDLED.index(PuzzleRoom)
    # The signature.
    entry = api.declarations(PuzzleRoom, "engine")
    assert (SIG.name, SIG.title, entry.api, entry.over_stage) == (
        "puzzle_room", "Puzzle Room", "1.1", False)
    assert SIG.args == (ArgSpec("room", REQUIRED), ArgSpec("state", None))
    assert SIG.test == SIG.skipped == Outcome(None)
    assert PuzzleRoom.test_outcome == PuzzleRoom.skipped_outcome == Outcome(None)
    assert SIG.check is not None and SIG.outcome is not None
    assert SIG.check(base(), S) is None
    assert SIG.check(base(state=[]), S) == problem(base(state=[])) is not None
    bad_take = base(attic(spots={"hook": {"take": "rusty_kye"}}))
    assert SIG.check(bad_take, S) == story_problem(bad_take, S) is not None
    assert entry.tokens == {"spot.ring_color": "#FFFFFF", "spot.ring_shadow_color": "#1A1A1A"}
    assert entry.words == {
        "title": "Puzzle Room", "hint": "Look around. Pick an item in Items to use it.",
        "hint_using": "Choose where to use {item}, or combine it in Items.",
        "hint_using_only": "Choose where to use {item}.",
        "hint_picker": "Choose an item to use.",
        "hint_combine": "Choose an item to combine with {item}.", "items": "Items",
        "back": "Back", "use": "Use", "combine": "Combine", "put_away": "Put away {item}",
        "need_item": "You need something for this.", "no_use": "That doesn't work.",
        "no_combine": "Those don't go together."}
    # The ast scan (PR-F27-01).
    stdlib = set(sys.stdlib_module_names) - {"random", "time"}
    rules_ok = {"engine.minigames.api", "engine.minigames.bundled.rule_text",
                "engine.core.constants"}            # CANVAS_SIZE (AC-F01-48)
    kit = {"engine.minigames.bundled", "engine.minigames.bundled.room_rules",
           "engine.ui.focus", "engine.ui.widgets", "engine.ui.paint", "engine.ui.nav",
           "engine.ui.layouts", "engine.render.frames"}
    banned = re.compile(r"(random|time)$|engine\.(runtime|script|persist|app)\b|"
                        r"engine\.minigames\.(host|loader|registry|context)\b")
    for name, allowed in (("room_rules", rules_ok), ("puzzle_room", rules_ok | kit)):
        found = _imports(BUNDLED_DIR / f"{name}.py")
        assert {m for m in found if m.split(".")[0] not in stdlib} <= allowed, name
        assert not [m for m in found if banned.match(m)], name
    # The spare codes are unused; CODES.md lists F27's block.
    for name in ("room_rules", "puzzle_room"):
        text = (BUNDLED_DIR / f"{name}.py").read_text(encoding="utf-8")
        assert not re.search(r"E29[1-3]|W181", text), name
    codes_file = REPO / "specs" / "CODES.md"   # specs/ is kept out of the repository
    if codes_file.exists():
        codes = codes_file.read_text(encoding="utf-8")
        assert re.search(r"F27 Puzzle room \| E291–E293 \| W179–W181", codes)
    # AC-F23-21's replacement row against the real BUNDLED.
    write(game, "minigames/my_room.py", plugin("puzzle_room"))
    loaded = load(game)
    assert loaded.result.ok and loaded.names.count("puzzle_room") == 1
    assert loaded.result.registry.get("puzzle_room").unit == "minigames/my_room.py"
    assert loaded.warnings("W160") == [messages.w160_replaces("minigames/my_room.py",
                                                              "puzzle_room")]
    assert load(game, dev=False).warnings() == []


# --- AC-F27-02: R1–R14 ---------------------------------------------------------------------

def _random_value(rng: random.Random, depth: int = 0) -> object:
    roll = rng.randrange(9 if depth < 3 else 6)
    if roll == 0:
        return rng.choice([0, 1, -1, 32, 40, 41, 1280, 10**30, rng.randint(-10**6, 10**6)])
    if roll == 1:
        return rng.choice([0.0, 1.5, -2.25, 1e300])
    if roll == 2:
        return rng.choice([True, False, None])
    if roll in (3, 4):
        alphabet = "aZ_ !\n​‍‮ß中hookdrawerout"
        return "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 70)))
    if roll == 5:
        return rng.choice(["hook", "drawer", "window", "out", "rusty_key", "magnet", "gone"])
    if roll == 6:
        return [_random_value(rng, depth + 1) for _ in range(rng.choice([0, 1, 2, 4, 9, 41]))]
    if roll == 7:
        keys = [*room_rules.FIELDS, *room_rules.ROOM_KEYS, "gone", "x", "1a"]
        return {rng.choice(keys): _random_value(rng, depth + 1)
                for _ in range(rng.randrange(0, 6))}
    return {k: _random_value(rng, depth + 1) for k in rng.sample(ORDER, 2)}


def _hostile_room(rng: random.Random) -> object:
    """A random value, or the attic with one random field, hotspot, or room key replaced."""
    roll = rng.randrange(4)
    if roll == 0:
        return _random_value(rng)
    room = attic()
    if roll == 1:
        spot = room["hotspots"][rng.choice(ORDER)]
        spot[rng.choice([*room_rules.FIELDS, "takes"])] = _random_value(rng)
    elif roll == 2:
        room["hotspots"][rng.choice([*ORDER, "x", "1a"])] = _random_value(rng)
    else:
        room[rng.choice([*room_rules.ROOM_KEYS, "hotspot"])] = _random_value(rng)
    return room


def test_ac_f27_02_the_checks():
    r1 = 'room must be a dictionary with "background" and "hotspots", but it is '
    image = "an image name is 1 to 64 characters on one line."
    r3 = "hotspots must be a dictionary of 1 to 40 hotspots, but it "
    r3n = "can't be a hotspot name; use letters, digits, and _, starting with a letter."
    r5 = ('the rect of "hook" must be [x, y, width, height] in whole numbers, at least 32 × 32 '
          "and inside 1280 × 720, but it is ")
    label = "a label is 1 to 40 characters on one line."
    caption = "a caption is 1 to 80 characters on one line."
    r7 = "; a hotspot does one of take, use, or exit."
    r7b = "; a hotspot that takes or leaves ends the run at once, so it has no look."
    r8 = 'the use of "drawer" must be an item name or a list of 1 to 8 item names, but it is '
    r11 = 'the exit of "out" must be True or False, but it is '
    r11b = 'room has no hotspot with "exit": True, so it can\'t be left.'
    r12 = ('combine must map each made item to two different items, e.g. {"magnet_string": '
           '["magnet", "string"]}, with at most 40 recipes.')
    r13 = "state must be None or the room's last result"
    r13g = f'{r13}, whose "gone" is a list of up to 40 hotspot names, but its "gone" is '
    cycle = 'hotspot "drawer" comes after itself, so it can never be shown.'
    x30 = "x" * 30 + "…"
    plain = {"rect": [0, 0, 32, 32], "label": "Spot"}
    forty = {f"s{i}": dict(plain) for i in range(39)} | {"out": {**plain, "exit": True}}
    many = {f"m{i}": [f"a{i}", f"b{i}"] for i in range(40)}
    no_exit = {"out": {"exit": None}}
    rows = [
        # R1
        *[(base(v), r1 + end) for v, end in (
            ([], "a list."), ("attic", "text."), (3, "a whole number."))],
        ({"room": None, "state": None}, r1 + "None."),
        (base(attic(hotspot={})), 'room has "hotspot", which isn\'t background, hotspots, or '
                                  'combine. Did you mean "hotspots"?'),
        (base(attic(zzz=1)), 'room has "zzz", which isn\'t background, hotspots, or combine.'),
        (base(attic(hotspots=...)), 'room has no "hotspots".'),
        (base(attic(background=...)), 'room has no "background".'),
        # R2
        (base(attic(background=3)), 'background must be an image name such as "bg attic", but '
                                    "it is 3."),
        (base(attic(background="")), f"background is empty; {image}"),
        (base(attic(background="   ")), f"background is empty; {image}"),
        (base(attic(background="b" * 65)), f"background is 65 characters long; {image}"),
        (base(attic(background="bg\nattic")), f"background has a line break; {image}"),
        (base(attic(background=" bg attic")), "background starts or ends with a space. "
                                              "Remove the space."),
        (base(attic(background="bg​attic")), f"background has a hidden character; {image}"),
        (base(attic(background="b" * 64)), None),
        # R3
        (base(attic(hotspots={})), r3 + "has 0."),
        (base(attic(hotspots={f"s{i}": dict(plain) for i in range(41)})), r3 + "has 41."),
        (base(attic(hotspots=[])), r3 + "is a list."),
        (base(attic(hotspots=forty)), None),
        *[(base(attic(spots={k: dict(plain)})), f"{shown} {r3n}") for k, shown in (
            ("coat hook", '"coat hook"'), ("1hook", '"1hook"'), ("a" * 33, f'"{"a" * 30}…"'),
            (3, "3"))],
        (base(attic(spots={"a" * 32: dict(plain)})), None),
        # R4
        (base(attic(spots={"hook": 3})), 'hotspot "hook" must be a dictionary of fields, but '
                                         "it is 3."),
        (base(attic(spots={"hook": {"takes": "x"}})),
         'hotspot "hook" has "takes", which isn\'t a hotspot field. Did you mean "take"?'),
        (base(attic(spots={"hook": {"rect": None}})), 'hotspot "hook" has no "rect".'),
        (base(attic(spots={"hook": {"label": None}})), 'hotspot "hook" has no "label".'),
        # R5
        *[(base(attic(spots={"hook": {"rect": v}})), f"{r5}{shown}.") for v, shown in (
            ([140, 300], "[140, 300]"), ([140, 300, 64.0, 96], "[140, 300, 64.0, 96]"),
            ([True, 300, 64, 96], "[True, 300, 64, 96]"),
            ([140, 300, 31, 96], "[140, 300, 31, 96]"),
            ([-1, 0, 32, 32], "[-1, 0, 32, 32]"), ([1249, 0, 32, 32], "[1249, 0, 32, 32]"),
            ([0, 689, 32, 32], "[0, 689, 32, 32]"))],
        (base(attic(spots={"hook": {"rect": [0, 0, 32, 32]}})), None),
        (base(attic(spots={"hook": {"rect": [1248, 688, 32, 32]}})), None),
        # R6
        (base(attic(spots={"hook": {"label": ""}})), f'the label of "hook" is empty; {label}'),
        (base(attic(spots={"hook": {"label": "L" * 41}})),
         f'the label of "hook" is 41 characters long; {label}'),
        (base(attic(spots={"hook": {"label": 3}})),
         f'the label of "hook" is a whole number, not text; {label}'),
        (base(attic(spots={"hook": {"label": "Coat\nhook"}})),
         f'the label of "hook" has a line break; {label}'),
        (base(attic(spots={"hook": {"label": " Coat hook"}})),
         'the label of "hook" starts or ends with a space. Remove the space.'),
        *[(base(attic(spots={"hook": {"label": v}})), None)
          for v in ("L" * 40, "中" * 40, "\U0001F469‍\U0001F4BB")],
        (base(attic(spots={"window": {"look": "l" * 81}})),
         f'the look of "window" is 81 characters long; {caption}'),
        (base(attic(spots={"window": {"look": "l" * 80}})), None),
        (base(attic(spots={"drawer": {"nope": "n" * 81}})),
         f'the nope of "drawer" is 81 characters long; {caption}'),
        # R7
        (base(attic(spots={"drawer": {"take": "magnet"}})),
         f'hotspot "drawer" has both take and use{r7}'),
        (base(attic(spots={"hook": {"exit": True}})), f'hotspot "hook" has both take and exit{r7}'),
        (base(attic(spots={"door": {"exit": True}})), f'hotspot "door" has both use and exit{r7}'),
        (base(attic(spots={"hook": {"look": "A hook."}})),
         f'hotspot "hook" has both look and take{r7b}'),
        (base(attic(spots={"out": {"look": "Out."}})),
         f'hotspot "out" has both look and exit{r7b}'),
        (base(attic(spots={"window": {"nope": "No."}})),
         'hotspot "window" has nope but no use; nope is the caption for a wrong item, so it '
         "needs use."),
        (base(attic(spots={"hook": {"exit": False}})), None),
        # R8
        (base(attic(spots={"hook": {"take": 3}})),
         'the take of "hook" must be an item name, but it is 3.'),
        (base(attic(spots={"hook": {"take": ["rusty_key"]}})),
         "the take of \"hook\" must be an item name, but it is ['rusty_key']."),
        (base(attic(spots={"drawer": {"use": 3}})), r8 + "3."),
        (base(attic(spots={"drawer": {"use": []}})), r8 + "[]."),
        (base(attic(spots={"drawer": {"use": ["rusty_key"] * 9}})),
         r8 + "['rusty_key', 'rusty_key', 'ru…."),
        (base(attic(spots={"drawer": {"use": [3]}})), r8 + "[3]."),
        (base(attic(spots={"drawer": {"use": ["rusty_key"] * 8}})), None),
        # R9
        (base(attic(spots={"magnet": {"after": "drawr"}})),
         'hotspot "magnet" comes after "drawr", which isn\'t in hotspots. Did you mean '
         '"drawer"?'),
        (base(attic(spots={"magnet": {"after": 3}})),
         'hotspot "magnet" comes after 3, which isn\'t in hotspots.'),
        (base(attic(spots={"magnet": {"after": "window"}})),
         'hotspot "magnet" comes after "window", which has no take or use, so it is never '
         "spent."),
        # R9′
        (base(attic(spots={"drawer": {"after": "drawer"}})), cycle),
        (base(attic(spots={"drawer": {"after": "vent"}, "vent": {"after": "drawer"}})),
         'hotspots "drawer" and "vent" come after each other, so neither can be shown.'),
        # R10
        (base(attic(spots={"hook": {"image": True}})),
         'the image of "hook" must be an image name such as "attic key", but it is True.'),
        (base(attic(spots={"hook": {"image": ""}})), f'the image of "hook" is empty; {image}'),
        (base(attic(spots={"hook": {"image": "i" * 65}})),
         f'the image of "hook" is 65 characters long; {image}'),
        (base(attic(spots={"hook": {"image": "i" * 64}})), None),
        # R11
        (base(attic(spots={"out": {"exit": "yes"}})), r11 + '"yes".'),
        (base(attic(spots={"out": {"exit": 1}})), r11 + "1."),
        (base(attic(spots={"out": {"exit": 0}})), r11 + "0."),
        (base(attic(spots=no_exit)), r11b),
        # R12
        *[(base(attic(combine=v)), r12) for v in (
            [], {"m": "a"}, {"m": ["a"]}, {"m": ["a", "a"]}, {"m": ["a", 3]},
            {f"m{i}": [f"a{i}", f"b{i}"] for i in range(41)})],
        (base(attic(combine={"magnet": ["magnet", "string"]})),
         'combine makes "magnet" from itself.'),
        (base(attic(combine={"x": ["magnet", "string"], "y": ["string", "magnet"]})),
         'combine lists "magnet" and "string" twice.'),
        (base(attic(combine={})), None),
        # R13
        (base(state=[]), f"{r13}, but it is a list."),
        (base(state="x"), f"{r13}, but it is text."),
        (base(state={}), f'{r13}, but it has no "gone".'),
        (base(state={"gone": "hook"}), r13g + '"hook".'),
        (base(state={"gone": [3]}), r13g + "[3]."),
        (base(state={"gone": ["hook"] * 41}), r13g + "['hook', 'hook', 'hook', 'hook…."),
        (base(state={"gone": []}), None),
        (base(state={"gone": ["zzz"], "action": 3}), None),
        (base(state={"gone": ["hook"] * 40}), None),
        # R14
        (base(attic(spots={"hook": {"take": "rusty_kye"}})),
         'the take of "hook" is "rusty_kye", but there is no item named "rusty_kye". Did you '
         'mean "rusty_key"?'),
        (base(attic(spots={"hook": {"take": "lanterns"}})),
         'the take of "hook" is "lanterns", which is a tip; only items can be held.'),
        (base(attic(spots={"drawer": {"use": ["rusty_key", "zzz"]}})),
         'the use of "drawer" is "zzz", but there is no item named "zzz".'),
        (base(attic(combine={"magnet_strng": ["magnet", "string"]})),
         'combine makes "magnet_strng", but there is no item named "magnet_strng". Did you '
         'mean "magnet_string"?'),
        (base(attic(combine={"magnet_string": ["magnet", "strin"]})),
         'the recipe for "magnet_string" uses "strin", but there is no item named "strin". '
         'Did you mean "string"?'),
        # Order
        ({"room": [], "state": []}, r1 + "a list."),
        (base(attic(background=3, spots={"hook": {"rect": [140, 300]}})),
         'background must be an image name such as "bg attic", but it is 3.'),
        (base(attic(hotspots={**{f"s{i}": dict(plain) for i in range(40)},
                              "hook": {"rect": [140, 300], "label": "Hook"}})), r3 + "has 41."),
        (base(attic(spots={"hook": {"rect": [140, 300]}, "drawer": {"takes": 1}})),
         r5 + "[140, 300]."),
        (base(attic(spots={"hook": {"rect": [140, 300], "takes": 1}})),
         'hotspot "hook" has "takes", which isn\'t a hotspot field. Did you mean "take"?'),
        (base(attic(spots={"hook": {"label": "", "exit": True}})),
         f'the label of "hook" is empty; {label}'),
        (base(attic(spots={"hook": {"image": ""}, **no_exit})),
         f'the image of "hook" is empty; {image}'),
        (base(attic(spots={"drawer": {"after": "drawer"}, **no_exit})), cycle),
        (base(attic(spots=no_exit, combine=[])), r11b),
        (base(attic(combine=[]), state=[]), r12),
        (base(attic(spots={"hook": {"take": "rusty_kye"}}), state=[]),
         f"{r13}, but it is a list."),
        (base(attic(spots={"drawer": {"use": "zzz"}},
                    combine={"magnet_string": ["magnet", "yyy"]})),
         'the use of "drawer" is "zzz", but there is no item named "zzz".'),
        # Echo cuts
        (base(attic(spots={"hook": {"x" * 40: 1}})),
         f'hotspot "hook" has "{x30}", which isn\'t a hotspot field.'),
        (base(attic(spots={"magnet": {"after": "x" * 40}})),
         f'hotspot "magnet" comes after "{x30}", which isn\'t in hotspots.'),
    ]
    for i, (args, expected) in enumerate(rows):
        found = check(args)
        assert found == expected, (i, found)
        assert found is None or len(found) <= 200, i
    assert problem(base(attic(combine=many))) is None       # 40 recipes (names undeclared)
    # Hostile values: a str or None, never raises, args unchanged, the same answer twice.
    rng = random.Random(27)
    for name in ("room", "state"):
        for _ in range(300):
            value = _hostile_room(rng) if name == "room" else _random_value(rng)
            args = base(**{name: value}) if name == "state" else {"room": value,
                                                                  "state": None}
            before = _ordered(copy.deepcopy(args))
            answers = [(problem(args), story_problem(args, S)) for _ in range(2)]
            assert answers[0] == answers[1]
            assert all(a is None or (type(a) is str and len(a) <= 200) for a in answers[0])
            assert _ordered(args) == before


# --- AC-F27-04: parsing, the shown set, and gone ------------------------------------------

ITEMS = ("rusty_key", "string", "magnet", "magnet_string", "door_key", "lamp", "rope")


def _valid_room(rng: random.Random) -> dict:
    """A seeded room that passes R1–R13: 2–12 hotspots of every kind, ``after`` only to an
    earlier spendable hotspot (no cycle), one exit or more, and a few recipes."""
    spots: dict = {}
    for i in range(rng.randint(2, 12)):
        kind = rng.choice(["look", "take", "use", "plain", "exit"])
        f: dict = {"rect": [rng.randrange(0, 1200), rng.randrange(0, 640), 40, 40],
                   "label": f"Spot {i}"}
        if kind == "look":
            f["look"] = "A look."
        elif kind == "take":
            f["take"] = rng.choice(ITEMS)
        elif kind == "use":
            f["use"] = rng.sample(ITEMS, rng.randint(1, 3))
            if rng.random() < 0.5:
                f["nope"] = "No."
            if rng.random() < 0.5:
                f["look"] = "Locked."
        elif kind == "exit":
            f["exit"] = True
        earlier = [k for k, g in spots.items() if "take" in g or "use" in g]
        if earlier and rng.random() < 0.4:
            f["after"] = rng.choice(earlier)
        spots[f"s{i}"] = f
    spots["out"] = {"rect": [0, 0, 32, 32], "label": "Out", "exit": True}
    pairs = [(a, b) for a in ITEMS for b in ITEMS if a < b]
    combine = {}
    for a, b in rng.sample(pairs, rng.randint(0, 4)):
        made = rng.choice([x for x in ITEMS if x not in (a, b)])
        if made not in combine:
            combine[made] = [a, b]
    return {"background": "bg room", "hotspots": spots, "combine": combine}


def _results(room, gone, held):
    """Every ``Finish`` ``activate`` returns from the shown set, and every recipe result."""
    for key in shown(room, gone, held):
        for selected in (None, *held):
            step = activate(room, key, selected, gone)
            if isinstance(step, Finish):
                yield step.result
    for made, _ in room.combine:
        yield result_of(room, "combine", None, made, gone)


def test_ac_f27_04_parsing_shown_and_gone():
    room = parse(attic())
    assert [s.key for s in room.spots] == ORDER and room.first_exit == "out"
    assert room.combine == (("magnet_string", frozenset({"magnet", "string"})),)
    assert room.spot("drawer").use == ("rusty_key",)
    window = room.spot("window")
    assert (window.use, window.exit, window.after) == ((), False, None)
    assert room.spot("hook").rect == (140, 300, 64, 96) and room.spot("out").exit is True
    # known_gone.
    for state, expected in ((None, ()), ({"gone": []}, ()),
                            ({"gone": ["drawer", "hook"]}, ("hook", "drawer")),
                            ({"gone": ["hook", "hook"]}, ("hook",)),
                            ({"gone": ["zzz", "window", "out", "hook"]}, ("hook",))):
        assert known_gone(room, state) == expected, state
    # shown: every stage; a take held from the story; an after on that held take (07 I-8).
    for name, (gone, held, expected) in STAGES.items():
        assert shown(room, gone, held) == expected, name
    assert shown(room, (), ("rusty_key",)) == STAGES["S1"][2]
    peg = parse(attic(spots={"peg": {"rect": [300, 300, 40, 40], "label": "Peg",
                                     "after": "hook", "look": "A bare peg."}}))
    assert "peg" in shown(peg, (), ("rusty_key",)) and "peg" not in shown(peg, (), ())
    # The project's G6 decision: a held take is reported as gone.
    assert run_gone(room, None, ("rusty_key",)) == ("hook",)
    assert run_gone(room, {"gone": ["drawer"]}, ("rusty_key", "magnet")) == (
        "hook", "drawer", "magnet")
    exit_step = activate(room, "out", None, run_gone(room, {"gone": list(S5_G)}, ("magnet",)))
    assert exit_step.result["gone"] == list(S5_G)
    use = activate(room, "drawer", "rusty_key", run_gone(room, None, ("rusty_key",)))
    assert use.result["gone"] == ["hook", "drawer"]
    # result_of (key order asserted).
    take = result_of(room, "take", "hook", "rusty_key", (), spent="hook")
    assert take == {"action": "take", "hotspot": "hook", "item": "rusty_key", "gone": ["hook"]}
    assert list(take) == ["action", "hotspot", "item", "gone"]
    assert result_of(room, "use", "drawer", "rusty_key", ("hook",), spent="drawer")["gone"] \
        == ["hook", "drawer"]
    assert result_of(room, "combine", None, "magnet_string", S3_G) == {
        "action": "combine", "hotspot": None, "item": "magnet_string", "gone": list(S3_G)}
    assert result_of(room, "exit", "out", None, S5_G) == {
        "action": "exit", "hotspot": "out", "item": None, "gone": list(S5_G)}
    # TR-F27-06 over 200 seeded rooms with random state and held sets.
    rng = random.Random(6)
    for _ in range(200):
        raw = _valid_room(rng)
        assert problem({"room": raw, "state": None}) is None
        room = parse(raw)
        keys = [s.key for s in room.spots]
        spendable = [s.key for s in room.spots if s.spendable]
        state = {"gone": rng.sample([*keys, "zzz"], rng.randint(0, len(keys)))}
        held = tuple(rng.sample(ITEMS, rng.randint(0, 3)))
        gone = run_gone(room, state, held)
        for result in _results(room, gone, held):
            assert list(result) == ["action", "hotspot", "item", "gone"]
            assert result["gone"] == [k for k in spendable if k in result["gone"]]
            assert len(set(result["gone"])) == len(result["gone"])
            assert known_gone(room, result) == tuple(result["gone"])
            assert all(v is None or type(v) is str for k, v in result.items() if k != "gone")
            assert all(type(k) is str for k in result["gone"])


# --- AC-F27-05: activation and combine ------------------------------------------------------

def test_ac_f27_05_activation_and_combine():
    raw = attic(spots={"photo": {"rect": [300, 100, 64, 64], "label": "Photo"},
                       "box": {"rect": [400, 100, 64, 64], "label": "Box", "use": "string"}})
    room = parse(raw)
    before = copy.deepcopy(room)
    take = Finish(result_of(room, "take", "hook", "rusty_key", (), spent="hook"),
                  give="rusty_key")
    rows = [
        (("window", None), Caption("Snow, as far as you can see.", None)),
        (("hook", None), take),
        (("drawer", None), Caption("Locked.", None)),
        (("box", None), Caption(None, "need_item")),
        (("out", None), Finish({"action": "exit", "hotspot": "out", "item": None,
                                "gone": []}, None)),
        (("photo", None), Finish({"action": "click", "hotspot": "photo", "item": None,
                                  "gone": []}, None)),
        (("drawer", "rusty_key"), Finish({"action": "use", "hotspot": "drawer",
                                          "item": "rusty_key", "gone": ["drawer"]}, None)),
        (("drawer", "string"), Caption("It doesn't fit.", None)),
        (("door", "rusty_key"), Caption(None, "no_use")),
        *[((key, "rusty_key"), Caption(None, "no_use"))
          for key in ("window", "hook", "out", "photo")],
    ]
    for (key, selected), expected in rows:
        for _ in range(2):
            assert activate(room, key, selected, ()) == expected, key
    vent = parse(attic(spots={"vent": {"use": ["magnet_string", "magnet"]}}))
    step = activate(vent, "vent", "magnet", ("hook",))
    assert isinstance(step, Finish) and step.result["action"] == "use"
    assert step.result["gone"] == ["hook", "vent"] and step.give is None
    # combine_pair: order ignored; a non-pair, a doubled item, and a room without combine.
    for a, b, expected in (("magnet", "string", "magnet_string"),
                           ("string", "magnet", "magnet_string"), ("magnet", "magnet", None),
                           ("magnet", "rusty_key", None)):
        assert combine_pair(room, a, b) == combine_pair(room, a, b) == expected
    bare = parse(attic(combine=...))
    assert bare.combine == () and combine_pair(bare, "magnet", "string") is None
    assert room == before and raw == attic(spots={
        "photo": {"rect": [300, 100, 64, 64], "label": "Photo"},
        "box": {"rect": [400, 100, 64, 64], "label": "Box", "use": "string"}})


# --- AC-F27-06: fixed outcomes ----------------------------------------------------------------

def test_ac_f27_06_fixed_outcomes():
    leave = {"action": "exit", "hotspot": "out", "item": None, "gone": []}
    two = {"background": "bg x", "hotspots": {
        "t": {"rect": [0, 0, 32, 32], "label": "T", "take": "rusty_key"},
        "a": {"rect": [100, 0, 32, 32], "label": "A", "after": "t", "exit": True},
        "b": {"rect": [200, 0, 32, 32], "label": "B", "exit": True}}}
    for args, expected in (
            (base(), Outcome(leave, ())),
            (base(state={"gone": ["drawer", "zzz", "hook"]}),
             Outcome({**leave, "gone": ["hook", "drawer"]}, ())),
            ({"room": two, "state": None},
             Outcome({**leave, "hotspot": "a"}, ()))):
        assert SIG.outcome("test", args, S) == SIG.outcome("skipped", args, S) == expected
        room = parse(args["room"])
        assert fixed_outcome(room, known_gone(room, args["state"])) == expected
    assert "a" not in shown(parse(two), (), ())
    with pytest.raises(ValueError):
        PuzzleRoom().outcome_for("other", base(), S)
    rng = random.Random(11)
    for _ in range(200):
        args = {"room": _valid_room(rng), "state": None}
        out = SIG.outcome("test", args, S)
        assert out is not None and out == SIG.outcome("skipped", args, S)
        assert out.changes == () and out.result["action"] == "exit"
        assert out.result["hotspot"] == parse(args["room"]).first_exit
    assert PuzzleRoom.test_outcome == PuzzleRoom.skipped_outcome == Outcome(None)


# --- AC-F27-16: layout numbers ----------------------------------------------------------------

AREA_100 = (24, 24, 1232, 598)
AREA_150 = (24, 24, 1232, 532)


def _area(box) -> int:
    return box[2] * box[3]


def _meets(a, b) -> bool:
    return (a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3]
            and b[1] < a[1] + a[3])


def test_ac_f27_16_layout_numbers():
    lay = room_layout(AREA_100, button_h=50, put_away_w=228)
    assert (lay.items, lay.put_away, lay.row) == (
        (24, 24, 200, 50), (240, 24, 228, 50), (24, 24, 696, 50))
    lay = room_layout(AREA_150, button_h=75, put_away_w=200)
    assert (lay.items, lay.row) == ((24, 24, 200, 75), (24, 24, 696, 75))
    for area, bh, view in ((AREA_100, 56, (236, 40, 808, 566)),
                           (AREA_150, 75, (236, 40, 808, 500))):
        pick = picker_layout(area, button_h=bh)
        bottom = area[1] + area[3]
        assert pick.backing == (220, 24, 840, area[3]) and pick.view == view
        assert pick.back == (24, bottom - bh, 180, bh)
    # put_away_label: only the title is cut (F10's cut_to_width, passed in).
    cut = layouts.cut_to_width
    word = "Put away {item}"
    assert put_away_label(word, "Rusty Key", size=28, measure=ten, cut_to_width=cut) == (
        "Put away Rusty Key", 228)
    assert put_away_label(word, "K", size=28, measure=ten, cut_to_width=cut) == (
        "Put away K", 200)
    label, w = put_away_label(word, "T" * 40, size=28, measure=ten, cut_to_width=cut)
    assert label.startswith("Put away T") and label.endswith("…") and w == 480
    assert ten(label, 28) <= 432
    label, w = put_away_label("{item} weglegen", "T" * 40, size=28, measure=ten,
                              cut_to_width=cut)
    assert label.endswith("… weglegen") and label.startswith("TTT") and w == 480
    assert ten(label, 28) <= 432
    # tag_box: above, below, below, inside; clamped at the area's sides.
    drawer, window, door = (520, 420, 200, 90), (880, 90, 220, 260), (40, 120, 180, 420)
    assert tag_box(drawer, 134, 40, row_bottom=74, area=AREA_100) == (553, 365, 134, 40)
    assert tag_box(window, 84, 40, row_bottom=74, area=AREA_100) == (948, 365, 84, 40)
    assert tag_box(door, 64, 40, row_bottom=74, area=AREA_100) == (98, 555, 64, 40)
    assert tag_box(door, 64, 52, row_bottom=99, area=AREA_150) == (98, 121, 64, 52)
    assert tag_box((1200, 300, 56, 40), 424, 40, row_bottom=74, area=AREA_100)[:2] == (832, 245)
    assert tag_box((24, 300, 40, 40), 224, 40, row_bottom=74, area=AREA_100)[:2] == (24, 245)
    # The ring: 4 color and 4 shadow rects, disjoint, filling the two bands exactly.
    color, shadow = ring_rects(drawer)
    assert len(color) == len(shadow) == 4
    rects = [*color, *shadow]
    assert not any(_meets(a, b) for i, a in enumerate(rects) for b in rects[i + 1:])
    assert sum(map(_area, shadow)) == 1208 and sum(map(_area, color)) == 1872
    assert all(516 <= r[0] and r[0] + r[2] <= 724 and 416 <= r[1] and r[1] + r[3] <= 514
               and not _meets(r, (518, 418, 204, 94)) for r in shadow)
    assert all(513 <= r[0] and r[0] + r[2] <= 727 and 413 <= r[1] and r[1] + r[3] <= 517
               and not _meets(r, (516, 416, 208, 98)) for r in color)
    # Images: fitted (never cropped) and F04's cover.
    hook = (140, 300, 64, 96)
    assert fit_box((64, 32), hook) == (140, 332, 64, 32)
    assert fit_box((128, 192), hook) == (140, 300, 64, 96)
    assert fit_box((200, 50), drawer) == (520, 440, 200, 50)
    assert cover_box((1280, 720)) == cover_box((1920, 1080)) == (0, 0, 1280, 720)
    assert cover_box((1000, 1000)) == (0, -280, 1280, 1280)


# --- AC-F27-17: fit from 100% to 150% -------------------------------------------------------

def wide(text: str, size: int) -> float:
    """A face whose every glyph is 1.6 em (07 G5's bound for a 40-code-point label)."""
    return len(graphemes(text)) * 1.6 * size


def test_ac_f27_17_fit_from_100_to_150():
    one, two = "Look around.", " ".join(["around"] * 30)
    corners = [(0, 0, 32, 32), (1248, 0, 32, 32), (0, 688, 32, 32), (1248, 688, 32, 32)]
    spots = [(s["rect"], s["label"]) for s in ATTIC["hotspots"].values()]
    spots += [(r, "Corner") for r in corners]
    labels = [("W" * 40, m20), ("W" * 40, wide), ("中" * 20, wide), ("a" * 40, m20)]
    cases = 0
    for scale in (1.0, 1.25, 1.5):
        bh, bs, ts = (layouts.button_height(scale=scale), layouts.scaled(28, scale),
                      layouts.scaled(24, scale))
        for hint in (one, two):
            frame = layouts.minigame_frame(scale, heading=None, hint=hint, measure=m20)
            area, band = frame.content, frame.hint
            if hint is two and scale == 1.5:
                assert len(frame.hint_lines) == 2 and area.bottom == 556
            for title in (None, "K", "T" * 40):
                cases += 1
                width = 0
                if title is not None:
                    label, width = put_away_label("Put away {item}", title, size=bs,
                                                  measure=m20,
                                                  cut_to_width=layouts.cut_to_width)
                    assert label.startswith("Put away ")
                    assert label == f"Put away {title}" or (
                        label.endswith("…") and title.startswith(label[9:-1]))
                lay = room_layout(area, button_h=bh, put_away_w=width or 200)
                boxes = [lay.items] + ([lay.put_away] if title else [])
                for box in boxes:
                    assert area.x <= box[0] and box[0] + box[2] <= area.right
                    assert area.y <= box[1] and box[1] + box[3] <= area.bottom
                assert not _meets(lay.items, lay.put_away)
                assert lay.put_away[0] + lay.put_away[2] <= area.x + 696
                row_bottom = lay.row[1] + lay.row[3]
                tags = [(rect, text, m20) for rect, text in spots]
                tags += [(spots[0][0], text, measure) for text, measure in labels]
                for rect, text, measure in tags:
                    lines = layouts.wrap_text(text, area.w - 24, ts, measure)
                    assert "".join(lines).replace(" ", "") == text.replace(" ", "")
                    w = max(measure(line, ts) for line in lines) + 24
                    h = len(lines) * layouts.pitch(ts) + 12
                    tag = tag_box(rect, w, h, row_bottom=row_bottom, area=area)
                    assert area.x <= tag[0] and tag[0] + tag[2] <= area.right, (rect, text)
                    assert area.y <= tag[1] and tag[1] + tag[3] <= area.bottom, (rect, text)
                    assert tag[1] >= row_bottom + 8
                    assert not _meets(tag, lay.row)
                    assert not _meets(tag, (band.x, band.y, band.w, band.h))
                    if measure is wide and scale == 1.5 and text[0] == "W":
                        assert len(lines) == 2
                pick = picker_layout(area, button_h=bh)
                assert pick.view[2] >= 640 and pick.view[3] >= 400
                assert not _meets(pick.back, pick.backing)
    assert cases == 18


# --- AC-F27-20 and 21, unit rows: W179 and W180's texts (the logging is F27-3's) -------------

def test_ac_f27_20_w179_unit_rows():
    room = parse(attic())
    for name, (gone, held, _) in STAGES.items():
        assert w179_text(room, gone, held) is None, name
    stuck = parse(attic(drop=("hook",)))
    assert w179_text(stuck, (), ()) == (
        'puzzle_room in "bg attic" can\'t be left: nothing the player has or can find works '
        "on drawer (rusty_key), vent (magnet_string), door (door_key). Give the player one of "
        "those items, or change the room.")
    assert w179_text(stuck, (), ("rusty_key",)) is None
    more = parse(attic(drop=("hook",), spots={
        "safe": {"rect": [300, 100, 64, 64], "label": "Safe", "use": "gold"},
        "chest": {"rect": [400, 100, 64, 64], "label": "Chest", "use": "gold"}}))
    assert "door (door_key), and 2 more. Give" in w179_text(more, (), ())
    plain = {"rect": [0, 0, 32, 32], "label": "X"}
    pair = parse({"background": "bg", "hotspots": {
        "key": {**plain, "use": ["a", "b"]}, "out": {**plain, "after": "key", "exit": True}}})
    assert "works on key (a, b). Give" in w179_text(pair, (), ())
    held = parse({"background": "bg", "hotspots": {
        "t": {**plain, "take": "x"}, "out": {**plain, "after": "t", "exit": True}}})
    assert w179_text(held, (), ("x",)) is None
    assert reach(held, (), ("x",))[0] == frozenset({"t"})
    chain = {"s0": {**plain, "take": "i0"}}
    chain |= {f"s{i}": {**plain, "take": f"i{i}", "after": f"s{i - 1}"} for i in range(1, 39)}
    chain["out"] = {**plain, "after": "s38", "exit": True}
    bound = {"background": "bg", "hotspots": chain,
             "combine": {f"m{i}": [f"i{i}", f"i{i + 1}"] for i in range(38)}
             | {"m38": ["m0", "m1"], "m39": ["m38", "m2"]}}
    assert problem({"room": bound, "state": None}) is None
    spent, items = reach(parse(bound), (), ())          # asserts ≤ 81 passes
    assert len(spent) == 39 and {"m38", "m39"} <= items
    assert w179_text(parse(bound), (), ()) is None


def test_ac_f27_21_w180_unit_rows():
    def frame(scale, hint):
        return layouts.minigame_frame(scale, heading=None, hint=hint, measure=m20).content

    one, two = "Look around.", " ".join(["around"] * 30)
    room = parse(attic(spots={
        "rug": {"rect": [40, 24, 300, 40], "label": "Rug"},
        "mat": {"rect": [300, 560, 200, 100], "label": "Mat"},
        "half": {"rect": [24, 24, 100, 112], "label": "Half"}}))
    keys = ("rug", "mat", "half")
    text = ('puzzle_room in "bg attic": the hotspot "rug" is mostly under the Items row or the '
            "hint at this text size. Move it, or make it bigger.")
    area = frame(1.0, one)
    row = room_layout(area, button_h=56, put_away_w=200).row
    assert w180_texts(room, keys, row=row, area=area) == (text,)
    assert room_rules.hint_band(area)[1] == 638                       # 4,400 of 20,000
    big = frame(1.5, two)
    row = room_layout(big, button_h=75, put_away_w=200).row
    warned = w180_texts(room, keys, row=row, area=big)
    assert [t.split('"')[3] for t in warned] == ["rug", "mat", "half"]
    assert [t.split('"')[3] for t in w180_texts(room, ("mat",), row=row, area=big)] == [
        "mat"]                                              # hidden spots are never checked

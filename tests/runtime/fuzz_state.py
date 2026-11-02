"""Mutated ``GameState`` JSON objects for AC-F03-64 (06-acceptance §5.5). Stdlib only.

``mutations(bases, count, seed, inflate=False)`` yields ``count`` objects, each a base with
one to three mutations: delete or add keys, swap types, substitute §9.1 hostile values,
truncate or lengthen strings, nest up to 150 levels, and (``inflate``, ``slow`` only) grow
counts up to the caps + 1. Deterministic for a seed.

F07 (AC-F07-16): ``CHOICE_ROWS``, the hostile ``choices`` values of ``06`` §1.3's table, each
a function of a base ``choices`` object (one pick and a waiting menu) returning the
mutated value; ``CHOICE_KINDS`` names one row of each kind (the default run), the rest are
``slow``. The hostile values and the inflate caps include F07's (sid and key shapes, the
pick, text, question, and choice caps).

F13 (AC-F13-04): ``HISTORY_ROWS``, hostile ``history`` values, each a function of
``history_base()`` (a named line, an unnamed line, a choice); ``HISTORY_KINDS`` names one
row of each kind (the default run), the rest are ``slow``. The inflate caps include F13's
(entries, text, name).

F23 (AC-F23-50, 05 group E): ``MINIGAME_ROWS``, hostile ``minigame`` values, each a function
of ``minigame_base()`` (a wait at ``probe`` with one argument); ``MINIGAME_KINDS`` names one
row of each kind (the default run), the rest are ``slow``. Every row is ``StateInvalid``.

F20 (AC-F20-15): ``FLOW_ROWS``, hostile ``flow`` values (``flow_base()`` is a valid path of
three keys); every row is ``StateInvalid("flow")``, all in the default run (they are tiny).
"""

import copy
import json
import random

from engine.runtime import history as history_limits
from engine.runtime import limits
from engine.runtime import menu as menu_limits

STR_MAX = 1_100_000      # a lengthened string stops here (past every cap; never gigabytes)
NODES_MAX = 1_000_000    # nodes one mutation looks at (shared inflated members repeat)
SCALARS = [None, True, False, 0, 1, -1, 1.0, -0.0, "", "x", "1", 2**64, -(2**63)]


def _nested(levels: int) -> list:
    v: list = []
    for _ in range(levels - 1):
        v = [v]
    return v


def hostile_values() -> list:
    return [
        "\ud800", "ZZMARK", "x" * 1025, "a\x00b", "../../ZZMARK", "C:/x", "-1",
        "8F3A5C0E12D4B7A9", "8f3a5c0e12d4b7a", "8f3a5c0e12d4b7a90", "define:hana",
        float("nan"), float("inf"), float("-inf"), 10**4300, 10**4300 - 1,
        _nested(101), _nested(150), (1, 2), {1: 2}, {"ZZMARK"}, [True], [1.0], [-1],
        {"sid": 5}, {"sid": "x", "at": ["x", [0]], "extra": 1}, ["x"],
        "__builtins__", "dice", "Character", "_x", "a b", "class", "ﬁx",
        # F07: near-miss sids and choice keys (ADR-0006 shapes)
        "start/ZZMARK", "ZZMARK/0123456789ab", "0123456789AB", "0123456789ab~0",
        "start/0123456789ab~", "/0123456789ab", "0123456789ab ",
    ]


def _nodes(obj) -> list[tuple[int, object, object]]:
    """Every node of a JSON-like tree in pre-order, as ``(parent index, key, node)`` (the
    root's parent is -1). Iterative and linear: a huge member nested 150 levels deep costs
    its size, not its size times its depth. Inflated lists repeat one member, so a tree can
    share nodes; the walk stops after ``NODES_MAX`` (a mutation then lands in the first
    ones)."""
    out: list[tuple[int, object, object]] = []
    stack: list[tuple[int, object, object]] = [(-1, None, obj)]
    while stack and len(out) < NODES_MAX:
        entry = stack.pop()
        index = len(out)
        out.append(entry)
        node = entry[2]
        if type(node) is dict:
            stack.extend((index, k, v) for k, v in reversed(node.items()))
        elif type(node) is list:
            stack.extend((index, i, node[i]) for i in range(len(node) - 1, -1, -1))
    return out


def _path(nodes: list, index: int) -> tuple:
    path = []
    while index > 0:
        parent, key, _ = nodes[index]
        path.append(key)
        index = parent
    return tuple(reversed(path))


def _get(obj, path):
    for p in path:
        obj = obj[p]
    return obj


def _replace(obj, path, value):
    if not path:
        return value
    _get(obj, path[:-1])[path[-1]] = value
    return obj


def _mutate(obj, rng: random.Random, inflate: bool):
    nodes = _nodes(obj)
    index = rng.choice(range(len(nodes)))
    path, node = _path(nodes, index), nodes[index][2]
    op = rng.randrange(8 if inflate else 7)
    if op == 0 and type(node) is dict and node:          # delete a key
        del node[rng.choice(list(node))]
    elif op == 1 and type(node) is dict:                 # add a key
        node[rng.choice(["ZZMARK", "voice", "extra", "format", "a", "_x", "x" * 300])] = \
            rng.choice(SCALARS)
    elif op == 2:                                        # swap the type
        obj = _replace(obj, path, rng.choice(SCALARS + [[], {}]))
    elif op == 3:                                        # a §9.1 hostile value
        obj = _replace(obj, path, rng.choice(hostile_values()))
    elif op == 4 and type(node) is str:                  # truncate or lengthen
        cut = rng.randrange(len(node) + 1)
        obj = _replace(obj, path, node[:cut] if rng.random() < 0.5
                       else (node + node[cut:] * rng.randrange(1, 300))[:STR_MAX])
    elif op == 5:                                        # nest up to 150 levels
        value = node
        for _ in range(rng.randrange(1, 151)):
            value = [value] if rng.random() < 0.5 else {"k": value}
        obj = _replace(obj, path, value)
    elif op == 6 and type(node) is list and node:        # duplicate list items
        node.extend(copy.deepcopy(node[: rng.randrange(1, len(node) + 1)]))
    elif op == 7:                                        # inflate to a cap + 1
        cap = rng.choice([limits.CALL_DEPTH_MAX, limits.HINT_MAX_PATH,
                          limits.STATE_MAX_NAMES, limits.POSITION_MAX_CHARS,
                          menu_limits.PICKS_MAX, menu_limits.PICK_TEXT_MAX,       # F07
                          menu_limits.PICK_QUESTION_MAX, menu_limits.MENU_CHOICES_MAX,
                          history_limits.HISTORY_MAX, history_limits.TEXT_MAX,      # F13
                          history_limits.NAME_MAX])
        if type(node) is list:
            node.extend([node[0] if node else 0] * (cap + 1 - len(node)))
        elif type(node) is dict:
            for i in range(cap + 1 - len(node)):
                node[f"v{i}"] = i
        elif type(node) is str:
            obj = _replace(obj, path, ((node or "x") * (cap // max(len(node), 1) + 1))[:cap + 1])
    else:
        obj = _replace(obj, path, rng.choice(SCALARS))
    return obj


def mutations(bases: list[dict], count: int, seed: int, inflate: bool = False):
    rng = random.Random(seed)
    texts = [json.dumps(b) for b in bases]
    for _ in range(count):
        obj = json.loads(rng.choice(texts))
        for _ in range(rng.randrange(1, 4)):
            obj = _mutate(obj, rng, inflate)
        yield obj


# --- F07: hostile ``choices`` (AC-F07-16) ----------------------------------------------------------

def _key(i: int) -> str:
    """A well-shaped choice key that no menu has."""
    return f"{i:012x}"


def _pick(base: dict) -> dict:
    return base["picks"][0]


def _set(path: tuple, value):
    """A row: ``value`` at ``path`` in the base (``picks`` index 0 for a pick field)."""
    def build(base: dict):
        return _replace(base, path, copy.deepcopy(value))
    return build


def _drop(path: tuple):
    def build(base: dict):
        del _get(base, path[:-1])[path[-1]]
        return base
    return build


def _with(path: tuple, fn):
    """A row: ``fn(node at path)`` (a fresh copy) at ``path``."""
    def build(base: dict):
        return _replace(base, path, fn(_get(base, path)))
    return build


def _choice_rows() -> dict[str, tuple[str, object]]:
    rows: dict[str, tuple[str, object]] = {}
    # shape: not an object; a missing or extra key
    for name, value in (("[]", []), ("null", None), ("ZZMARK", "ZZMARK")):
        rows[f"choices {name}"] = ("shape", _set((), value))
    rows["no picks"] = ("shape", _drop(("picks",)))
    rows["no waiting"] = ("shape", _drop(("waiting",)))
    rows["extra key ZZMARK"] = ("shape", _set(("ZZMARK",), 1))
    # pick: a missing or extra key; a field of the wrong type
    for field in ("menu", "choice", "text", "question"):
        rows[f"pick without {field}"] = ("pick", _drop(("picks", 0, field)))
    rows["pick extra key ZZMARK"] = ("pick", _set(("picks", 0, "ZZMARK"), "ZZMARK"))
    rows["pick ZZMARK"] = ("pick", _set(("picks", 0), "ZZMARK"))
    rows["picks ZZMARK"] = ("pick", _set(("picks",), "ZZMARK"))
    for field in ("text", "menu", "choice"):
        for name, value in (("1", 1), ("null", None), ("true", True),
                            ('["ZZMARK"]', ["ZZMARK"])):
            rows[f"pick {field} {name}"] = ("pick", _set(("picks", 0, field), value))
    rows["pick question 1"] = ("pick", _set(("picks", 0, "question"), 1))
    # position: F03 9.1's rules and ADR-0006's shapes for sids and keys
    for field in ("menu", "choice"):
        rows[f"pick {field} 300 characters"] = ("position",
                                                 _set(("picks", 0, field), "x" * 300))
        rows[f"pick {field} ZZMARK"] = ("position", _set(("picks", 0, field), "ZZMARK"))
    rows["pick menu 1,025 characters"] = ("position", _with(
        ("picks", 0, "menu"), lambda sid: "a" * (1_025 - len(sid.split("/")[1]) - 1) + "/"
        + sid.split("/")[1]))
    rows["pick choice ~0"] = ("position", _set(("picks", 0, "choice"), "0123456789ab~0"))
    rows["kept ZZMARK"] = ("position", _set(("waiting", "kept"), "ZZMARK"))
    rows["pickable ZZMARK"] = ("position", _set(("waiting", "pickable"), ["ZZMARK"]))
    # size: the caps + 1
    rows["10,001 picks"] = ("size", _with(("picks",), lambda picks: picks * (
        menu_limits.PICKS_MAX // len(picks) + 1)))
    rows["text 1,001"] = ("size", _set(("picks", 0, "text"), "t" * 1_001))
    rows["question 2,001"] = ("size", _set(("picks", 0, "question"), "q" * 2_001))
    # keys: pickable 1-6, locked 0-5, unique, disjoint; kept a sid or null
    rows["pickable empty"] = ("keys", _set(("waiting", "pickable"), []))
    rows["pickable 7"] = ("keys", _set(("waiting", "pickable"), [_key(i) for i in range(7)]))
    rows["locked 6"] = ("keys", _set(("waiting", "locked"), [_key(i) for i in range(6)]))
    rows["pickable twice"] = ("keys", _with(("waiting", "pickable"),
                                            lambda keys: keys + keys[:1]))
    rows["locked twice"] = ("keys", _set(("waiting", "locked"), [_key(1), _key(1)]))
    rows["a key in both"] = ("keys", lambda base: _replace(
        base, ("waiting", "locked"), list(base["waiting"]["pickable"][:1])))
    rows["seven in all"] = ("keys", _set(("waiting", "locked"), [_key(i) for i in range(5)]))
    rows["kept 1"] = ("keys", _set(("waiting", "kept"), 1))
    rows["waiting ZZMARK"] = ("keys", _set(("waiting",), "ZZMARK"))
    return rows


CHOICE_ROWS = _choice_rows()
CHOICE_KINDS = ("shape", "pick", "position", "size", "keys")


def choice_rows(*, everything: bool) -> list[str]:
    """Row names: the first of each kind, or (``everything``) all of them."""
    if everything:
        return list(CHOICE_ROWS)
    firsts = {}
    for name, (kind, _) in CHOICE_ROWS.items():
        firsts.setdefault(kind, name)
    return [firsts[kind] for kind in CHOICE_KINDS]


def choice_row(name: str, base: dict):
    """Row ``name`` applied to a deep copy of the base ``choices`` object."""
    return CHOICE_ROWS[name][1](copy.deepcopy(base))


# --- F13: hostile ``history`` (AC-F13-04) -------------------------------------------------------

SID_A = "start/0123456789ab"
SID_B = "start/0123456789ab~2"


class Text(str):
    """A ``str`` subclass (never from ``json.loads``; a hand-built value must still be
    refused)."""


def history_base() -> dict:
    """A valid ``history`` object: a named line, an unnamed line, and a choice."""
    return {"entries": [
        {"kind": "line", "sid": SID_A, "name": "Hana", "text": "A crane!\nGood choice."},
        {"kind": "line", "sid": SID_B, "name": "", "text": "The river glows."},
        {"kind": "choice", "sid": SID_A, "name": "", "text": "The paper crane"}]}


def _history_rows() -> dict[str, tuple[str, object]]:
    rows: dict[str, tuple[str, object]] = {}
    # shape: not an object; a missing or extra key; entries not a list
    rows["history []"] = ("shape", _set((), []))
    rows["history null"] = ("shape", _set((), None))
    rows["no entries"] = ("shape", _drop(("entries",)))
    rows["extra key ZZMARK"] = ("shape", _set(("ZZMARK",), 1))
    rows["entries ZZMARK"] = ("shape", _set(("entries",), "ZZMARK"))
    rows["entries {}"] = ("shape", _set(("entries",), {}))
    # entry: not an object; a missing or extra key; a field of the wrong type
    rows["entry ZZMARK"] = ("entry", _set(("entries", 0), "ZZMARK"))
    for field in ("kind", "sid", "name", "text"):
        rows[f"entry without {field}"] = ("entry", _drop(("entries", 0, field)))
    rows["entry extra key ZZMARK"] = ("entry", _set(("entries", 0, "ZZMARK"), "ZZMARK"))
    rows["entry extra key voice"] = ("entry", _set(("entries", 0, "voice"), "v.ogg"))
    for field in ("kind", "sid", "name", "text"):
        for name, value in (("1", 1), ("null", None), ("true", True),
                            ('["ZZMARK"]', ["ZZMARK"])):
            rows[f"entry {field} {name}"] = ("entry", _set(("entries", 0, field), value))
    for field in ("kind", "sid", "name", "text"):
        rows[f"entry {field} str subclass"] = ("entry", _with(
            ("entries", 0, field), Text))
    # kind: only "line" and "choice"
    for value in ("x", "Line", "line ", "", "ZZMARK"):
        rows[f"kind {value!r}"] = ("kind", _set(("entries", 0, "kind"), value))
    # sid: F03 9.1's position rule and ADR-0006's shape
    for value in ("ZZMARK", "start/ZZMARK", "start/0123456789AB", "start/0123456789ab~0",
                  "/0123456789ab", "start/0123456789ab ", ""):
        rows[f"sid {value!r}"] = ("sid", _set(("entries", 0, "sid"), value))
    rows["sid 1,025 characters"] = ("sid", _set(
        ("entries", 0, "sid"), "a" * (1_025 - 13) + "/0123456789ab"))
    # value: the limits on a name and a text
    rows["named choice"] = ("value", _set(("entries", 2, "name"), "Hana"))
    rows["name 201"] = ("value", _set(("entries", 0, "name"), "n" * 201))
    rows["text empty"] = ("value", _set(("entries", 0, "text"), ""))
    rows["text 2,001"] = ("value", _set(("entries", 0, "text"), "t" * 2_001))
    rows["choice text empty"] = ("value", _set(("entries", 2, "text"), ""))
    # size: 251 entries (counted before anything is built)
    rows["251 entries"] = ("size", _with(("entries",), lambda entries: (
        entries * (history_limits.HISTORY_MAX // len(entries) + 1))[:251]))
    rows["251 broken entries"] = ("size", _set(("entries",), ["ZZMARK"] * 251))
    return rows


HISTORY_ROWS = _history_rows()
HISTORY_KINDS = ("shape", "entry", "kind", "sid", "value", "size")


def history_rows(*, everything: bool) -> list[str]:
    """Row names: the first of each kind, or (``everything``) all of them."""
    if everything:
        return list(HISTORY_ROWS)
    firsts = {}
    for name, (kind, _) in HISTORY_ROWS.items():
        firsts.setdefault(kind, name)
    return [firsts[kind] for kind in HISTORY_KINDS]


def history_row(name: str):
    """Row ``name`` applied to a fresh ``history_base()``."""
    return HISTORY_ROWS[name][1](history_base())


# --- F23: hostile ``minigame`` (AC-F23-50, 05 group E) ----------------------------------------------

def minigame_base() -> dict:
    """A valid ``minigame`` object: a wait at ``probe`` with one argument."""
    return {"waiting": {"name": "probe", "args": {"pairs": 6}, "seed": 12345}}


def _minigame_rows() -> dict[str, tuple[str, object]]:
    rows: dict[str, tuple[str, object]] = {}
    # shape: waiting a list; an extra or missing key
    rows["waiting a list"] = ("shape", _set(("waiting",), ["probe"]))
    rows["minigame null"] = ("shape", _set((), None))
    rows["extra key ZZMARK"] = ("shape", _set(("ZZMARK",), 1))
    rows["waiting extra key ZZMARK"] = ("shape", _set(("waiting", "ZZMARK"), 1))
    rows["waiting without seed"] = ("shape", _drop(("waiting", "seed")))
    # name: PLUGIN_NAME_RE, fullmatch only
    for label, value in (("empty", ""), ("65 characters", "a" * 65), ("41 characters", "a" * 41),
                         ("../x", "../x"), ("Lantern", "Lantern"), ("a newline", "a\n"),
                         ("a lone surrogate", "\ud800"), ("1", 1), ("null", None)):
        rows[f"name {label}"] = ("name", _set(("waiting", "name"), value))
    # args: an object of at most 32 story-variable names, values by the variables' rule
    rows["args a list"] = ("args", _set(("waiting", "args"), [6]))
    rows["args 33 keys"] = ("args", _set(("waiting", "args"),
                                         {f"a{i}": i for i in range(33)}))
    rows["arg __class__"] = ("args", _set(("waiting", "args"), {"__class__": 1}))
    rows["arg 2nd"] = ("args", _set(("waiting", "args"), {"2nd": 1}))
    rows["arg class"] = ("args", _set(("waiting", "args"), {"class": 1}))
    rows["arg 65 characters"] = ("args", _set(("waiting", "args"), {"a" * 65: 1}))
    rows["value 101 deep"] = ("args", _set(("waiting", "args", "pairs"), _nested(101)))
    rows["value 4,301 digits"] = ("args", _set(("waiting", "args", "pairs"), 10**4300))
    rows["value NaN"] = ("args", _set(("waiting", "args", "pairs"), float("nan")))
    rows["value a set"] = ("args", _set(("waiting", "args", "pairs"), {"ZZMARK"}))
    # seed: an exact int, 0 <= seed < 2**64
    for value in (-1, 2**64, 1.0, "1", True, None):
        rows[f"seed {value!r}"] = ("seed", _set(("waiting", "seed"), value))
    return rows


MINIGAME_ROWS = _minigame_rows()
MINIGAME_KINDS = ("shape", "name", "args", "seed")


def minigame_rows(*, everything: bool) -> list[str]:
    """Row names: the first of each kind, or (``everything``) all of them."""
    if everything:
        return list(MINIGAME_ROWS)
    firsts = {}
    for name, (kind, _) in MINIGAME_ROWS.items():
        firsts.setdefault(kind, name)
    return [firsts[kind] for kind in MINIGAME_KINDS]


def minigame_row(name: str):
    """Row ``name`` applied to a fresh ``minigame_base()``."""
    return MINIGAME_ROWS[name][1](minigame_base())


# --- F20: hostile ``flow`` (AC-F20-15, TR-F20-02) ------------------------------------------------

FLOW_KEY = "0123456789abcdef"           # a well-formed 16-hex key no graph has


def flow_base() -> dict:
    """A valid ``flow`` object: a path of three keys."""
    return {"path": [FLOW_KEY, "fedcba9876543210", FLOW_KEY]}


# Every row is ``StateInvalid("flow")``; each holds ZZMARK-free text the error never echoes.
FLOW_ROWS: dict[str, object] = {
    "path a string": {"path": "x"},
    "extra key": {"path": [], "ZZMARK": 1},
    "no path": {},
    "1,001 entries": {"path": [FLOW_KEY] * 1_001},
    "15 hex": {"path": ["0123456789abcde"]},
    "17 hex": {"path": ["0123456789abcdef0"]},
    "uppercase hex": {"path": ["0123456789ABCDEF"]},
    "a number": {"path": [1]},
    "null entry": {"path": [None]},
    "flow null": None,
    "path null": {"path": None},
    "not hex": {"path": ["zzzzzzzzzzzzzzzz"]},
    "a newline": {"path": ["0123456789abcde\n"]},
}

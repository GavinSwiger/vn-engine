"""The F20 hostile node-file corpus (``05-security.md`` §5 groups A, B, E; ``06-acceptance.md``
§0.4, §5).

``hostile/nodes/manifest.toml`` has one row per input. Group E rows are bytes: a ``like`` row
applies an F11 hostile save row's recipe (``gen_hostile_saves.build``) to the node file, and a
``gen`` row names a node generator below. Group A rows are entries and group B rows names; the
test makes those (they need links and the folder). Every input is built at run time from an
engine-written node file, deterministic for a seed. Write the small byte rows out for review
with::

    .venv/Scripts/python tests/persist/gen_hostile_nodes.py --seed 1 --out <folder>
"""

import argparse
import random
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

if __package__ in (None, ""):                         # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.persist import nodestates  # noqa: E402
from engine.runtime.flowchart import FlowState  # noqa: E402
from engine.runtime.state import GameState  # noqa: E402
from engine.script.flowgraph import node_key  # noqa: E402
from tests.persist import gen_hostile_saves  # noqa: E402
from tests.persist import save_support as ss  # noqa: E402
from tests.persist.gen_hostile_saves import Sparse  # noqa: E402

HOSTILE = Path(__file__).resolve().parent / "hostile" / "nodes"
MANIFEST = HOSTILE / "manifest.toml"
NODE_ID = "scene:stall"
OTHER_ID = "chapter:river"
GAME_ID = "f20-template"
SPECIAL = {"@null": None, "@surrogate": "\ud800"}


def load_manifest() -> list[dict]:
    with open(MANIFEST, "rb") as f:
        return tomllib.load(f)["row"]


def save_rows() -> dict[str, dict]:
    """F11's hostile save rows by id (the ``like`` rows' recipes)."""
    return {row["id"]: row for row in gen_hostile_saves.load_manifest()}


def node_state(node_id: str = NODE_ID, *, path: tuple[str, ...] | None = None,
               state: GameState | None = None) -> GameState:
    """F11's P8 checkpoint (or ``state``) reached at ``node_id``: its flow path ends with the
    node's key (or is ``path``)."""
    base = ss.p8_state() if state is None else state
    keys = (node_key(node_id),) if path is None else path
    return replace(base, flow=FlowState(keys))


def encode(state: GameState, node_id: str = NODE_ID, game: str | None = GAME_ID) -> bytes:
    """A node file's bytes written by ``NodeEncoder``."""
    result = nodestates.NodeEncoder(state, node_id=node_id, game=game).run()
    assert not isinstance(result, nodestates.TooLarge), result
    return b"".join(result)


_BASE: dict[str, bytes] = {}


def base() -> bytes:
    """The engine-written node file of ``scene:stall`` (P8 with the node's key)."""
    if "base" not in _BASE:
        _BASE["base"] = encode(node_state())
    return _BASE["base"]


def _value(value: object) -> object:
    return SPECIAL.get(value, value) if isinstance(value, str) else value


def _replace_once(data: bytes, old: bytes, new: bytes) -> bytes:
    assert data.count(old) >= 1, old
    return data.replace(old, new, 1)


def _gen(rng: random.Random, row: dict) -> bytes | Sparse:
    if "like" in row:
        return gen_hostile_saves.build(save_rows()[row["like"]], data=base(), state=node_state())
    node = base()
    name = row["gen"]
    if name == "valid":
        return node
    if name == "meta":
        return ss.with_meta(node, **{row["key"]: _value(row["value"])})
    if name == "meta2":
        return ss.with_meta(node, **{row["key"]: _value(row["value"]),
                                     row["key2"]: _value(row["value2"])})
    if name == "meta_text":
        return ss.with_meta(node, **{row["key"]: row["char"] * row["chars"]})
    if name == "meta_drop":
        return ss.with_meta(node, drop=(row["key"],))
    if name == "meta_extra":
        return ss.with_meta(node, extra=1)
    if name == "meta_raw":
        return _replace_once(node, row["old"].encode("utf-8"), row["new"].encode("utf-8"))
    if name == "dup_vnnode":
        return b'{"vnnode":1,' + node[1:]
    if name == "vnsave_meta":                       # a save's meta key instead of vnnode
        return _replace_once(node, b'{"vnnode":1,', b'{"vnsave":1,')
    if name == "newer_garbage":
        junk = bytes(rng.randrange(256) for _ in range(40)).replace(b"\n", b"?")
        return b'{"vnnode":2,' + junk + b"\n" + b"\x00garbage\n" * 3
    if name == "newer_faults":                      # vnnode 2 with an extra key and bad lengths
        data = ss.with_meta(node, vnnode=2, extra=1, state=1)
        return data + b"junk"
    if name == "node_id":                           # a whole file for its own long id
        node_id = row["char"] * row["chars"]
        return encode(node_state(node_id), node_id)
    if name == "line2":
        return ss.with_line2(node, row["text"].encode("ascii"))
    if name == "line2_jpeg":
        return ss.with_line2(node, gen_hostile_saves._jpeg_line(gen_hostile_saves.thumb_jpeg()))
    if name == "path":
        keys = {"none": (), "other": (node_key(OTHER_ID),)}[row["at"]]
        return encode(node_state(path=keys))
    raise KeyError(name)


def build(row: dict, seed: int = 1) -> bytes | Sparse:
    """The bytes of one group E row (deterministic for ``seed`` and the row id)."""
    return _gen(random.Random(f"{seed}:{row['id']}"), row)


def read_kwargs(row: dict) -> dict:
    """``read_node``'s arguments for a group E row: the node and the reader's game id."""
    game = row.get("game_id", GAME_ID)
    node_id = row["char"] * row["chars"] if row.get("gen") == "node_id" else NODE_ID
    return {"node_id": node_id, "game_id": None if game == "none" else game}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for row in load_manifest():
        if row["group"] != "E" or row["tier"] != "default":
            continue
        data = build(row, args.seed)
        if isinstance(data, bytes) and len(data) <= 1 << 20:
            (args.out / f"{row['id']}.vnnode").write_bytes(data)
            print(row["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["GAME_ID", "HOSTILE", "MANIFEST", "NODE_ID", "OTHER_ID", "base", "build", "encode",
           "load_manifest", "node_state", "read_kwargs", "save_rows"]

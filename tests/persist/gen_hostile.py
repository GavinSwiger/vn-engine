"""The F12 hostile corpus (``05-security.md`` §5 groups A–C; ``06-acceptance.md`` §0.2, §5).

``hostile/manifest.toml`` has one row per input: ``gen`` names a generator below; rows with
a ``file`` are committed under ``hostile/`` (small inputs); the rest (big inputs, sparse
files) are built at run time in ``tmp_path`` and never committed. Regenerate the committed
files with::

    .venv/Scripts/python tests/persist/gen_hostile.py --seed 1

Generators are deterministic for a seed. Sizes come from ``engine.persist.limits`` (real
values), so a test that patches a limit must not use the B-group generators.
"""

import argparse
import copy
import json
import random
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):                         # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.persist import limits  # noqa: E402
from engine.persist.fileformat import count_structure  # noqa: E402

HOSTILE = Path(__file__).resolve().parent / "hostile"
MANIFEST = HOSTILE / "manifest.toml"
MIB = 1 << 20

GOOD = {"format": 1, "identity_scheme": 1, "values": {"good": 1},
        "seen": {"good": "0123456789ab"}, "chosen": {"good/0123456789ab": "0123456789ab"},
        "unlocks": {"good": ["a"]}}
GOOD_MENU = "good/0123456789ab"


@dataclass(frozen=True)
class Sparse:
    """A file of ``size`` bytes made with ``truncate`` (no data written)."""

    size: int


def load_manifest() -> list[dict]:
    with open(MANIFEST, "rb") as f:
        return tomllib.load(f)["row"]


def dumps(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def good(**sections: dict) -> dict:
    """GOOD with entries added to some sections (``values={...}``) or keys replaced
    (``top={...}``)."""
    out = copy.deepcopy(GOOD)
    for name, extra in sections.items():
        if name == "top":
            out.update(extra)
        else:
            out[name].update(extra)
    return out


def with_raw(raw: bytes) -> bytes:
    """GOOD with ``values.x`` set to the raw JSON text ``raw``."""
    return dumps(good(values={"x": "@@"})).replace(b'"@@"', raw)


def nested(levels: int) -> list:
    v: list = []
    for _ in range(levels - 1):
        v = [v]
    return v


# --- Group B shapes ----------------------------------------------------------------------------

_SHAPE_ITEMS = {"dicts": b"{}", "lists": b"[]", "floats": b"0.5"}
_TAIL = b',"seen":{},"chosen":{},"unlocks":{}}'
_HEAD = b'{"format":1,"identity_scheme":1,"values":'


def shape_file(shape: str, *, count: int | None = None, size: int | None = None) -> bytes:
    """``values.a = [{},{},…]`` (dicts), ``[[],…]`` (lists), ``[0.5,…]`` (floats),
    ``values = {"n0000000":1,…}`` (names), or ``seen = {"l0000000":"<key>",…}`` (labels), with exactly ``count`` pre-scan bytes, or about
    ``size`` bytes (≤ ``size``)."""
    if shape in ("names", "labels"):
        if shape == "names":
            head, tail = _HEAD + b"{", b"}" + _TAIL
            item = lambda i: b'"n%07d":1' % i                  # noqa: E731
        else:                                                    # many one-key seen labels
            head, tail = _HEAD + b'{},"seen":{', b'},"chosen":{},"unlocks":{}}'
            item = lambda i: b'"l%07d":"%012x"' % (i, i)       # noqa: E731
        per = 2                                                  # one ':' and one ','
        filler = lambda k: b'"p":"' + b":" * (k - 2) + b'"'   # noqa: E731  (adds k)
    else:
        head, tail = _HEAD + b'{"a":[', b"]}" + _TAIL
        unit = _SHAPE_ITEMS[shape]
        item, per = (lambda i: unit), count_structure(unit) + 1
        filler = lambda k: b'"' + b":" * (k - 1) + b'"'       # noqa: E731  (adds k)
    base = count_structure(head + tail)
    if count is not None:
        n = max(0, (count - base + 1) // per - 1)
        rest = count - (base + n * per - (1 if n else 0))
        parts = [item(i) for i in range(n)]
        if rest:
            parts.append(filler(rest if n else rest + 1))   # no comma before a lone item
        data = head + b",".join(parts) + tail
        assert count_structure(data) == count, (count_structure(data), count)
        return data
    assert size is not None
    width = len(item(0)) + 1
    n = (size - len(head) - len(tail)) // width
    return head + b",".join(item(i) for i in range(n)) + tail


def nonascii_file(size: int) -> bytes:
    """A valid file of exactly ``size`` bytes whose value ``big`` is UTF-8 text."""
    base = good(values={"big": ""})
    text = json.dumps(base, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    room = size - len(text)
    chars = "\u00e9" * (room // 2) + "x" * (room % 2)
    data = json.dumps(good(values={"big": chars}), ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    assert len(data) == size and not data.isascii()
    return data


def string_file(size: int) -> bytes:
    """A valid ASCII file of exactly ``size`` bytes (one long string value)."""
    room = size - len(dumps(good(values={"big": ""})))
    return dumps(good(values={"big": "x" * room}))


# --- Generators ----------------------------------------------------------------------------------

def _gen(rng: random.Random, row: dict) -> bytes | Sparse:
    name = row["gen"]
    fixed: dict[str, Callable[[], bytes | Sparse]] = {
        # Group A: syntax and top level
        "empty": lambda: b"",
        "open_brace": lambda: b"{",
        "bom": lambda: b"\xef\xbb\xbf" + dumps(GOOD),
        "utf16": lambda: dumps(GOOD).decode("ascii").encode("utf-16"),
        "latin1_byte": lambda: dumps(good(values={"x": "cafX"})).replace(b"cafX", b"caf\xe9"),
        "nan": lambda: with_raw(b"NaN"),
        "infinity": lambda: with_raw(b"Infinity"),
        "neg_infinity": lambda: with_raw(b"-Infinity"),
        "dup_top": lambda: b'{"format":1,' + dumps(GOOD)[1:],
        "dup_nested": lambda: with_raw(b'{"k":1,"k":2}'),
        "deep_lists": lambda: with_raw(b"[" * row["levels"] + b"]" * row["levels"]),
        "digits": lambda: with_raw(b"1" * row["digits"]),
        "top_list": lambda: b"[]",
        "format": lambda: dumps(good(top={"format": row["value"]})),
        "format_float": lambda: dumps(GOOD).replace(b'"format":1,', b'"format":1.0,'),
        "format_missing": lambda: dumps({k: v for k, v in GOOD.items() if k != "format"}),
        "extra_key": lambda: dumps(good(top={"format": row.get("format", 1), "stats": {}})),
        "values_list": lambda: dumps(good(top={"values": []})),
        "scheme": lambda: dumps(good(top={"identity_scheme": row["value"]})),
        "surrogate": lambda: dumps(good(values={"s": "\ud800"})),
        # Group B: size and the pre-scan
        "shape_over": lambda: shape_file(row["shape"], count=limits.PRESCAN_MAX + 1),
        "shape_at": lambda: shape_file(row["shape"], count=limits.PRESCAN_MAX),
        "shape_32mib": lambda: shape_file(row["shape"], size=limits.FILE_MAX_BYTES),
        "sparse": lambda: Sparse(limits.FILE_MAX_BYTES + 1 if row["size"] == "over"
                                 else 4 << 30),
        "string_over": lambda: string_file(32 * MIB + 60),
        "nonascii_over": lambda: nonascii_file(limits.NON_ASCII_MAX_BYTES + 1),
        "nonascii_at": lambda: nonascii_file(limits.NON_ASCII_MAX_BYTES),
        # Group C: bad entries
        "value_name": lambda: dumps(good(values={row["name"]: 1})),
        "long_name": lambda: dumps(good(values={"a" * row["chars"]: 1})),
        "many_names": lambda: dumps(good(values={
            f"{rng.choice('jkm')}{i}": i for i in range(row["names"] - 1)})),
        "deep_value": lambda: dumps(good(values={"x": nested(row["levels"])})),
        "members": lambda: dumps(good(values={"x": [0] * row["members"]})),
        "seen_text": lambda: dumps(good(seen={"bad": row["text"]})),
        "seen_label": lambda: dumps(good(seen={row["label"]: "0123456789ab"})),
        "long_label": lambda: dumps(good(seen={"l" * row["chars"]: "0123456789ab"})),
        "long_menu": lambda: dumps(good(chosen={
            "l" * (row["chars"] - 13) + "/0123456789ab": "0123456789ab"})),
        "long_kind": lambda: dumps(good(unlocks={"k" * row["chars"]: ["a"]})),
        "many_kinds": lambda: dumps(good(unlocks={f"k{i}": ["a"]
                                                  for i in range(row["kinds"] - 1)})),
        "unlock_dup": lambda: dumps(good(unlocks={"cg": ["a", "a"]})),
    }
    return fixed[name]()


def build(row: dict, seed: int = 1) -> bytes | Sparse:
    """The input of one manifest row (deterministic for ``seed`` and the row id)."""
    return _gen(random.Random(f"{seed}:{row['id']}"), row)


def write_committed(seed: int = 1) -> list[Path]:
    written = []
    for row in load_manifest():
        if "file" in row:
            data = build(row, seed)
            assert isinstance(data, bytes)
            path = HOSTILE / row["file"]
            path.write_bytes(data)
            written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    for path in write_committed(args.seed):
        print(path.relative_to(HOSTILE.parent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

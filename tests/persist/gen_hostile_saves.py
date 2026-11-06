"""The F11 hostile save corpus (``05-security.md`` §5 groups A–D; ``06-acceptance.md`` §0.2,
§5; ``04-technical.md`` §11's nine shapes).

``hostile/saves/manifest.toml`` has one row per input; ``gen`` names a generator below. Every
input is built from a P8 save (``save_support``) at run time, deterministic for a seed, so
nothing goes stale when F03's state JSON gains a field. Write the small rows out for review
with::

    .venv/Scripts/python tests/persist/gen_hostile_saves.py --seed 1 --out <folder>

Sizes come from ``engine.persist.limits`` when the row is built, so a test that patches a
limit gets inputs at the patched bound (AC-F11-62's 1/8 rows).

F20 (``gen_hostile_nodes.py``) builds the same shapes over a node file: ``build(row,
data=<node bytes>, state=<its GameState>)`` applies a row's recipe to those bytes and builds
state lines from that state instead of P8 (the recipes only use line 1's JSON, the declared
lengths, and lines 2 and 3, so they work on any three-line file).
"""

import argparse
import random
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):                         # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.persist import limits, saves  # noqa: E402
from tests.persist import save_support as ss  # noqa: E402

HOSTILE = Path(__file__).resolve().parent / "hostile" / "saves"
MANIFEST = HOSTILE / "manifest.toml"
SHAPES = ("zeros", "floats", "dicts", "lists", "long_keys", "e_acute", "astral", "big_ints",
          "short_strings")


@dataclass(frozen=True)
class Sparse:
    """A file of ``size`` bytes made with ``truncate`` (no data written)."""

    size: int


def load_manifest() -> list[dict]:
    with open(MANIFEST, "rb") as f:
        return tomllib.load(f)["row"]


_BASE: dict[str, bytes] = {}


def base(thumb: bool = True) -> bytes:
    """The P8 save, with the engine's own flat thumbnail (or ``{"jpeg":null}``)."""
    key = "thumb" if thumb else "plain"
    if key not in _BASE:
        jpeg = None
        if thumb:
            from tests.fakes import jpegs                 # pygame's encoder
            jpeg = jpegs.engine_jpeg("flat")
        _BASE[key] = ss.make_save(jpeg=jpeg)
    return _BASE[key]


def thumb_jpeg() -> bytes:
    from tests.fakes import jpegs
    return jpegs.engine_jpeg("flat")


# --- The nine shapes (04 §11) ------------------------------------------------------------------

_UNITS = {                      # list items: (bytes, structure bytes of one item)
    "zeros": (b"0", 0),
    "floats": (b"0.5", 0),
    "dicts": (b'{"a":0}', 2),
    "lists": (b"[]", 1),
    "big_ints": (b"9" * 4_300, 0),
    "short_strings": (b'"ab"', 0),
}
_STRING_UNITS = {"e_acute": b"\\u00e9", "astral": b"\\ud83c\\udf38"}


def shape_line(shape: str, *, max_bytes: int | None = None,
               max_structure: int | None = None, state=None) -> bytes:
    """A P8 (or ``state``'s) state line (no ``\\n``) whose ``variables.v`` holds ``shape``,
    filled to the byte cap (line 3 with its ``\\n`` ≤ ``max_bytes``) or the pre-scan bound
    (≤ ``max_structure``), whichever comes first. Defaults: the current limits."""
    max_bytes = limits.STATE_MAX_BYTES if max_bytes is None else max_bytes
    max_structure = limits.SAVE_PRESCAN_MAX if max_structure is None else max_structure
    head, tail = ss.state_line(b"@@", state).split(b"@@")
    head += b'{"v":'
    tail = b"}" + tail
    room = max_bytes - 1 - len(head) - len(tail)
    struct_room = max_structure - saves.count_structure(head + tail)
    if shape in _STRING_UNITS:
        unit = _STRING_UNITS[shape]
        value = b'"' + unit * ((room - 2) // len(unit)) + b'"'
    elif shape == "long_keys":                     # {"k000…0":0,…}: 40-character keys
        width, per = len(b'"k%039d":0' % 0) + 1, 2
        n = max(1, min((room - 1) // width, (struct_room - 1 + 1) // per))
        value = b"{" + b",".join(b'"k%039d":0' % i for i in range(n)) + b"}"
    else:
        unit, item_structure = _UNITS[shape]
        width, per = len(unit) + 1, item_structure + 1
        n = max(1, min((room - 1) // width, struct_room // per))
        value = b"[" + b",".join([unit] * n) + b"]"
    line = head + value + tail
    assert len(line) + 1 <= max_bytes and saves.count_structure(line) <= max_structure, shape
    return line


def shape_save(shape: str, *, data: bytes | None = None, state=None, **bounds: int) -> bytes:
    return ss.with_line3(base() if data is None else data,
                         shape_line(shape, state=state, **bounds))


# --- Rows ----------------------------------------------------------------------------------------

def _replace_once(data: bytes, old: bytes, new: bytes) -> bytes:
    assert data.count(old) >= 1, old
    return data.replace(old, new, 1)


def _cut(where: str, data: bytes) -> bytes:
    first, second, third = ss.lines(data)
    at = {"line1": len(first) // 2, "after1": len(first),
          "line2": len(first) + len(second) // 2, "after2": len(first) + len(second),
          "line3": len(first) + len(second) + len(third) // 2, "last": len(data) - 1}[where]
    return data[:at]


def _declared(key: str, value: int, data: bytes) -> bytes:
    obj = ss.meta(data)
    obj[key] = value
    return ss.dumps_meta(obj) + b"".join(ss.lines(data)[1:])


def _length_delta(key: str, delta: int, data: bytes) -> bytes:
    obj = ss.meta(data)
    obj[key] += delta
    return ss.dumps_meta(obj) + b"".join(ss.lines(data)[1:])


def _line2_newline(data: bytes) -> bytes:
    first, second, third = ss.lines(data)
    at = len(second) // 2
    return first + second[:at] + b"\n" + second[at + 1:] + third


def _boundary(line: int, data: bytes) -> bytes:
    data = bytearray(data)
    first, second, _ = ss.lines(bytes(data))
    at = len(first) + len(second) - 1 if line == 2 else len(data) - 1
    data[at] = ord("x")
    return bytes(data)


def _line2(text: bytes) -> bytes:
    return ss.with_line2(base(), text)


def _jpeg_line(jpeg: bytes) -> bytes:
    import base64
    return b'{"jpeg":"' + base64.b64encode(jpeg) + b'"}\n'


def _thumb_row(kind: str) -> bytes:
    from tests.fakes import jpegs
    good = thumb_jpeg()
    if kind == "valid":
        return base()
    if kind == "svg_repro":
        return _line2(_jpeg_line(jpegs.svg_confusion()))
    if kind == "null":
        return base(thumb=False)
    if kind == "null_space":
        return _line2(b'{"jpeg": null}\n')
    if kind == "no_eoi":
        return _line2(_jpeg_line(good[:-2]))
    if kind == "size_321":
        return _line2(_jpeg_line(jpegs.engine_jpeg("flat", (321, 180))))
    encoded = _jpeg_line(good)
    if kind == "whitespace":
        return _line2(encoded[:20] + b" " + encoded[21:])
    if kind == "urlsafe":
        body = encoded[9:-3].replace(b"+", b"-").replace(b"/", b"_")
        if body == encoded[9:-3]:
            body = b"-_" + body[2:]
        return _line2(b'{"jpeg":"' + body + b'"}\n')
    if kind == "bad_padding":                      # one "=" too many
        return _line2(encoded[:-3] + b'="}\n')
    raise KeyError(kind)


def _gen(rng: random.Random, row: dict, data: bytes | None = None,
         state=None) -> bytes | Sparse:
    name = row["gen"]
    p8 = base() if data is None else data
    fixed: dict[str, Callable[[], bytes | Sparse]] = {
        # Group A: the meta line (AC-F11-08)
        "raw": lambda: row["text"].encode("ascii"),
        "line1_no_newline": lambda: b"{" + b" " * (limits.META_MAX - 1) + b"}",
        "line1_nonascii": lambda: _replace_once(p8, b"The wind picks up.", b"The wind pick\xe9 up."),
        "bom": lambda: b"\xef\xbb\xbf" + p8,
        "meta": lambda: ss.with_meta(p8, **{row["key"]: row["value"]}),
        "meta_raw": lambda: _replace_once(p8, row["old"].encode(), row["new"].encode()),
        "meta_digits": lambda: _replace_once(p8, b'"saved_at":1793567040',
                                             b'"saved_at":' + b"1" * row["digits"]),
        "meta_text": lambda: ss.with_meta(p8, **{row["key"]: row["char"] * row["chars"]}),
        "meta_drop": lambda: ss.with_meta(p8, drop=(row["key"],)),
        "meta_extra": lambda: ss.with_meta(p8, extra=1),
        "dup_vnsave": lambda: b'{"vnsave":1,' + p8[1:],
        "nested_line1": lambda: ss.with_line1(p8, b"[" * row["levels"] + b"\n"),
        "newer_garbage": lambda: (b'{"vnsave":3,' + bytes(rng.randrange(256) for _ in range(40))
                                  .replace(b"\n", b"?") + b"\n" + b"\x00garbage\n" * 3),
        # Group B: sizes (AC-F11-09)
        "length_delta": lambda: _length_delta(row["key"], row["delta"], p8),
        "cut": lambda: _cut(row["where"], p8),
        "crlf": lambda: p8.replace(b"\n", b"\r\n"),
        "junk": lambda: p8 + b"x",
        "declared": lambda: _declared(row["key"], row["value"], p8),
        "sparse": lambda: Sparse(limits.SAVE_FILE_MAX + 1 if row["size"] == "over" else 4 << 30),
        "grow": lambda: p8,                        # the test appends a byte mid-read
        "line2_newline": lambda: _line2_newline(p8),
        "boundary": lambda: _boundary(row["line"], p8),
        # Group C: the thumbnail line, head only (AC-F11-18, 19 byte half)
        "thumb": lambda: _thumb_row(row["kind"]),
        "thumb_on": lambda: ss.with_meta(p8, **{row["key"]: row["value"]}),
        # Group D: the state line (AC-F11-10)
        "state_raw": lambda: ss.with_line3(p8, ss.state_line(row["variables"].encode(), state)),
        "state_structure": lambda: ss.with_line3(p8, _structure_line(row["count"], state)),
        "state_nested": lambda: ss.with_line3(
            p8, ss.state_line(b'{"v":' + b"[" * row["levels"] + b"]" * row["levels"] + b"}",
                              state)),
        "state_digits": lambda: ss.with_line3(p8, ss.state_line(b'{"v":' + b"7" * row["digits"]
                                                                + b"}", state)),
        "state_nonascii": lambda: ss.with_line3(p8, ss.state_line('{"v":"café"}'
                                                                  .encode("utf-8"), state)),
        "state_top": lambda: ss.with_line3(p8, _top_line(state, **row.get("edit", {}))),
        "shape": lambda: shape_save(row["shape"], data=p8, state=state,
                                    **_scaled(row.get("scale", 1))),
    }
    return fixed[name]()


def _scaled(scale: int) -> dict:
    return {"max_bytes": limits.STATE_MAX_BYTES // scale,
            "max_structure": limits.SAVE_PRESCAN_MAX // scale}


def _structure_line(count: int, state=None) -> bytes:
    """A P8 (or ``state``'s) state line with exactly ``count`` structure bytes: ``v`` a list
    of ``k`` empty lists (2k − 1 bytes) and ``w`` a string of colons for the rest."""
    have = saves.count_structure(ss.state_line(b'{"v":[],"w":""}', state))
    k = max(0, (count - have + 1) // 2)
    rest = count - have - max(0, 2 * k - 1)
    value = b"[" + b",".join([b"[]"] * k) + b"]"
    line = ss.state_line(b'{"v":' + value + b',"w":"' + b":" * rest + b'"}', state)
    assert saves.count_structure(line) == count, (saves.count_structure(line), count)
    return line


def _top_line(state=None, **edit: object) -> bytes:
    obj = (ss.p8_state() if state is None else state).to_json()
    obj.update(edit)
    return ss.state_json_line(obj)


def build(row: dict, seed: int = 1, *, data: bytes | None = None,
          state=None) -> bytes | Sparse:
    """The input of one manifest row (deterministic for ``seed`` and the row id). ``data``
    and ``state``: another three-line file and its state to apply the recipe to (F20)."""
    return _gen(random.Random(f"{seed}:{row['id']}"), row, data, state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for row in load_manifest():
        if row["tier"] != "default":
            continue
        data = build(row, args.seed)
        if isinstance(data, bytes) and len(data) <= 1 << 20:
            (args.out / f"{row['id']}.vnsave").write_bytes(data)
            print(row["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["HOSTILE", "MANIFEST", "SHAPES", "Sparse", "base", "build", "load_manifest",
           "shape_line", "shape_save"]

"""Mutated save files for AC-F11-12 (the mutation corpus; ``04`` §15). Stdlib only.

``mutations(bases, count, seed)`` yields ``count`` byte strings, each a base with one to
three mutations: byte flips, truncation, splices from another base, declared-length edits,
thumbnail edits, meta-value edits, nesting and big numbers in line 3, and swapped structural
bytes. Deterministic for a seed.
"""

import json
import random

STRUCTURE = b'{}[],:"\\ \n'
META_VALUES = [b"0", b"-1", b"1", b"2", b"9007199254740992", b"9007199254740993", b"1e3",
               b"true", b"null", b'""', b'"x"', b"[]", b"{}", b"1.0", b"9" * 4_301]
INSERTS = [b"NaN", b"-Infinity", b"1e999", b"9" * 4_301, b"\xe9", b"\xef\xbb\xbf",
           b'"\\ud800"', b"\r", b"\n", b"null", b"[]", b"{}", b'"ZZMARK"', b"\x00",
           b"<svg width='16384'>", b"\xff\xd8\xff"]


def _bounds(data: bytes) -> tuple[int, int]:
    """The ends of lines 1 and 2 (or the data's end)."""
    first = data.find(b"\n")
    second = data.find(b"\n", first + 1) if first >= 0 else -1
    end = len(data)
    return (first if first >= 0 else end), (second if second >= 0 else end)


def _flip(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    if data:
        i = rng.randrange(len(data))
        data[i] = rng.choice((data[i] ^ (1 << rng.randrange(8)), rng.randrange(256)))


def _structure(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    if data:
        data[rng.randrange(len(data))] = rng.choice(STRUCTURE)


def _truncate(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    del data[rng.randint(0, len(data)):]


def _splice(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    other = rng.choice(bases)
    a = rng.randint(0, len(other))
    b = rng.randint(a, min(len(other), a + 300))
    at = rng.randint(0, len(data))
    data[at:at + rng.randint(0, 40)] = other[a:b]


def _swap_line(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    """Line 2 or 3 taken whole from another base (lengths now wrong or right by luck)."""
    other = rng.choice(bases)
    o1, o2 = _bounds(other)
    d1, d2 = _bounds(bytes(data))
    if rng.random() < 0.5:
        data[d1 + 1:d2 + 1] = other[o1 + 1:o2 + 1]
    else:
        data[d2 + 1:] = other[o2 + 1:]


def _meta_value(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    """One meta value replaced by a hostile one (the declared lengths stay)."""
    end1, _ = _bounds(bytes(data))
    line = bytes(data[:end1])
    try:
        obj = json.loads(line)
    except (ValueError, RecursionError):
        return
    if type(obj) is not dict or not obj:
        return
    key = rng.choice(sorted(obj))
    old = b'"' + key.encode() + b'":' + json.dumps(obj[key]).encode()
    at = line.find(old)
    if at >= 0:
        new = b'"' + key.encode() + b'":' + rng.choice(META_VALUES)
        data[at:at + len(old)] = new


def _length(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    """``thumb`` or ``state`` declared ± a little, or set to fit after another edit."""
    end1, _ = _bounds(bytes(data))
    try:
        obj = json.loads(bytes(data[:end1]))
    except (ValueError, RecursionError):
        return
    if type(obj) is not dict or "thumb" not in obj or "state" not in obj:
        return
    key = rng.choice(("thumb", "state"))
    if type(obj["thumb"]) is not int or type(obj["state"]) is not int:
        return
    if rng.random() < 0.5:
        obj[key] += rng.choice((-2, -1, 1, 2, 1000))
    else:                                             # repair the equation (a "fixed up" edit)
        rest = len(data) - end1 - 1
        obj[key] = rest - obj["thumb" if key == "state" else "state"]
    data[:end1] = json.dumps(obj, separators=(",", ":")).encode()


def _thumbnail(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    """A byte of line 2 (the base64 or its frame) changed, lengths kept."""
    end1, end2 = _bounds(bytes(data))
    if end2 - end1 > 2:
        i = rng.randrange(end1 + 1, end2)
        data[i] = rng.choice(b"AZaz09+/=- \"{}\\\x00\xff")


def _nest(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    _, end2 = _bounds(bytes(data))
    depth = rng.choice((2, 101, 1_000, 5_000, 20_000))
    at = rng.randint(min(end2 + 1, len(data)), len(data))
    data[at:at] = b"[" * depth + b"0" + b"]" * depth


def _insert(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    at = rng.randint(0, len(data))
    data[at:at] = rng.choice(INSERTS)


MUTATORS = (_flip, _structure, _truncate, _splice, _swap_line, _meta_value, _length,
            _thumbnail, _nest, _insert)


def mutations(bases: list[bytes], count: int, seed: int):
    rng = random.Random(seed)
    for _ in range(count):
        data = bytearray(rng.choice(bases))
        for _ in range(rng.randint(1, 3)):
            rng.choice(MUTATORS)(rng, data, bases)
        yield bytes(data)

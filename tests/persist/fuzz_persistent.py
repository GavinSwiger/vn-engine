"""Mutated ``persistent.json`` files for AC-F12-26 (TR-F12-04). Stdlib only.

``mutations(bases, count, seed)`` yields ``count`` byte strings, each a base with one to
three mutations: byte flips, truncation, splices from another base, deep nesting, huge
numbers, duplicated or removed spans, and swapped structural bytes. Deterministic for a
seed.
"""

import random

STRUCTURE = b'{}[],:"\\ '
INSERTS = [b"NaN", b"-Infinity", b"1e999", b"-0", b"9" * 5_000, b"1" * 4_301, b"\xe9",
           b"\xef\xbb\xbf", b"\xed\xa0\x80", b'"\\ud800"', b"null", b"true", b"[]", b"{}",
           b'"a b"', b'"__class__"', b'"~0"', b'"3FA9C2D81B07"', b'"ZZMARK"', b"\x00"]


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
    b = rng.randint(a, min(len(other), a + 200))
    at = rng.randint(0, len(data))
    data[at:at] = other[a:b]


def _cut(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    if data:
        a = rng.randrange(len(data))
        del data[a:a + rng.randint(1, 40)]


def _duplicate(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    if data:
        a = rng.randrange(len(data))
        b = min(len(data), a + rng.randint(1, 60))
        data[b:b] = data[a:b]


def _nest(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    depth = rng.choice((2, 99, 100, 101, 150, 1_000, 5_000))
    at = rng.randint(0, len(data))
    data[at:at] = b"[" * depth + b"0" + b"]" * depth


def _insert(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    at = rng.randint(0, len(data))
    data[at:at] = rng.choice(INSERTS)


def _number(rng: random.Random, data: bytearray, bases: list[bytes]) -> None:
    digits = [i for i, c in enumerate(data) if 48 <= c <= 57]
    if digits:
        at = rng.choice(digits)
        data[at:at + 1] = rng.choice((b"9" * rng.choice((20, 4_300, 4_301, 20_000)),
                                      b"1e308", b"1.5", b"-1", b"00"))


MUTATORS = (_flip, _structure, _truncate, _splice, _cut, _duplicate, _nest, _insert, _number)


def mutations(bases: list[bytes], count: int, seed: int):
    rng = random.Random(seed)
    for _ in range(count):
        data = bytearray(rng.choice(bases))
        for _ in range(rng.randint(1, 3)):
            rng.choice(MUTATORS)(rng, data, bases)
        yield bytes(data)

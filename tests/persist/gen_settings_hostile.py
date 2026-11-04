"""The F16 settings fixtures and hostile inputs (``06-acceptance.md`` §0.3, §5; AC-F16-05).

``FIXTURES`` are the small committed files of ``tests/fixtures/F16/files/``. Regenerate them
with::

    .venv/Scripts/python tests/persist/gen_settings_hostile.py --seed 1

``hostile_inputs(seed, count, full=...)`` builds the seeded fuzz in memory (never
committed): random bytes, byte-mutated §4 examples, deep nesting, wide objects, and long
numbers. The default tier (``full=False``) uses each limit's smallest crossing input
(1,001 nesting levels, 21-digit numbers) and small sizes; ``full=True`` uses full sizes up
to ``MAX_FILE_BYTES`` (64 KiB of nesting, 8,000 keys, 5,000-digit numbers). Every input is
at most ``MAX_FILE_BYTES`` bytes. Deterministic for a seed.
"""

import argparse
import json
import random
import sys
from collections.abc import Callable
from pathlib import Path

if __package__ in (None, ""):                         # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.core.settings_schema import KEYS, MAX_FILE_BYTES, MAX_INT_DIGITS  # noqa: E402

FILES = Path(__file__).resolve().parents[1] / "fixtures" / "F16" / "files"
MAX_DEPTH = 1000

# 04 §4's example, byte for byte as ``encode_settings`` writes it.
EXAMPLE = (b'{\n  "format": 5,\n  "values": {\n    "music_volume": 40,\n'
           b'    "reduce_motion": true,\n    "text_size_pct": 130,\n'
           b'    "window_size": [1280, 720]\n  }\n}\n')
EXAMPLE_VALUES = {"music_volume": 40, "reduce_motion": True, "text_size_pct": 130,
                  "window_size": (1280, 720)}

# One out-of-range value per key (AC-F16-31's 18 W71 lines; F33 added warning_seen, F30 its
# two keys, F43 language, F50 timing_assist: 22 lines).
EVERY_BAD = {
    "text_cps": 5, "text_size_pct": 400, "auto_scale_pct": 24, "auto_wait_voice": "yes",
    "skip_all": 1, "master_volume": -1, "music_volume": 101, "sound_volume": None,
    "voice_volume": 12345678, "text_blips": {}, "voice_sustain": [], "audio_unfocused": 0,
    "audio_minimized": "no", "mono": 1.5, "fullscreen": "true", "reduce_motion": "yes",
    "window_size": [1, 2], "warning_seen": 1001, "username_use": 3, "crash_label": "on",
    "language": "Japanese", "timing_assist": 3,
}
MARK = "ZZMARK"


def dumps(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=True, indent=2).encode("ascii")


def _marker() -> bytes:
    """``ZZMARK`` in string values, in unknown key names, and next to a 30-digit run."""
    values = {"text_cps": f"{MARK} qauser7 {MARK}", f"{MARK}_key": 1,
              f"{MARK}{MARK}{MARK}": f"{MARK}", "reduce_motion": [MARK],
              "music_volume": "@@"}
    return dumps({"format": 1, "values": values}).replace(
        b'"@@"', b"123456789012345678901234567890")


FIXTURES: dict[str, Callable[[], bytes]] = {
    "valid.json": lambda: EXAMPLE,
    "bad_brace.json": lambda: b"{",
    "bom.json": lambda: b"\xef\xbb\xbf" + EXAMPLE,
    "newer.json": lambda: dumps({"format": 6, "values": {"music_volume": 40, "new_key": 1}}),
    "mixed.json": lambda: dumps({"format": 1, "values": {"text_cps": 40, "music_volume": 400,
                                                          "foo": 1, "bar": 2}}),
    "every_bad.json": lambda: dumps({"format": 1, "values": EVERY_BAD}),
    "marker.json": _marker,
}


# --- Hostile inputs ---------------------------------------------------------------------------

def _random_bytes(rng: random.Random, full: bool) -> bytes:
    size = rng.randint(0, MAX_FILE_BYTES if full else 256)
    return rng.randbytes(size)


def _mutated(rng: random.Random, full: bool) -> bytes:
    data = bytearray(EXAMPLE)
    for _ in range(rng.randint(1, 40 if full else 8)):
        op = rng.randrange(3)
        at = rng.randrange(len(data) + 1)
        if op == 0 and data:
            data[min(at, len(data) - 1)] = rng.randrange(256)
        elif op == 1:
            data[at:at] = bytes([rng.choice(b'{}[]",:0123456789-.eEtrufalsn \\')])
        elif data:
            del data[min(at, len(data) - 1)]
    return bytes(data)


def _deep(rng: random.Random, full: bool) -> bytes:
    levels = rng.randint(MAX_DEPTH + 1, MAX_FILE_BYTES // 2) if full else MAX_DEPTH + 1
    opener, closer = rng.choice(((b"[", b"]"), (b'{"a":', b"}")))
    budget = MAX_FILE_BYTES - 64                         # room for the wrapper below
    if (len(opener) + 1) * levels + 1 > budget:
        levels = (budget - 1) // (len(opener) + 1)
    where = rng.randrange(3)
    inner = opener * levels + b"1" + closer * levels
    if where == 0:
        return inner
    if where == 1:
        return b'{"format": 1, "values": {"text_cps": ' + inner + b"}}"
    return opener * levels                             # unclosed


_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def short_names(count: int) -> list[str]:
    """``count`` distinct names of two or three characters (8,000 fit in 64 KiB)."""
    two = [a + b for a in _ALPHABET for b in _ALPHABET]
    three = (a + b + c for a in _ALPHABET for b in _ALPHABET for c in _ALPHABET)
    names = two[:count]
    names.extend(next(three) for _ in range(count - len(names)))
    return names


def _wide(rng: random.Random, full: bool) -> bytes:
    count = 8000 if full else rng.randint(18, 200)
    values: dict[str, object] = {key: rng.choice((0, 1, True, None, 50, "x", [], {}, 640))
                                 for key in KEYS}
    for name in short_names(count):
        values[name] = rng.randrange(10)
    data = json.dumps({"format": rng.choice((1, 2)), "values": values},
                      separators=(",", ":")).encode("ascii")
    assert len(data) <= MAX_FILE_BYTES
    return data


def _long_number(rng: random.Random, full: bool) -> bytes:
    digits = rng.randint(MAX_INT_DIGITS + 1, 5000) if full else MAX_INT_DIGITS + 1
    number = ("-" if rng.random() < 0.3 else "") + "9" * digits
    key = rng.choice(list(KEYS) + ["format"])
    if key == "format":
        return f'{{"format": {number}, "values": {{}}}}'.encode("ascii")
    return f'{{"format": 1, "values": {{"{key}": {number}}}}}'.encode("ascii")


KINDS: tuple[Callable[[random.Random, bool], bytes], ...] = (
    _random_bytes, _mutated, _deep, _wide, _long_number)


def hostile_inputs(seed: int = 1, count: int = 200, *, full: bool = False) -> list[bytes]:
    """``count`` inputs, the kinds in turn, each at most ``MAX_FILE_BYTES`` bytes."""
    rng = random.Random(f"settings:{seed}:{full}")
    out = []
    for i in range(count):
        data = KINDS[i % len(KINDS)](rng, full)
        assert len(data) <= MAX_FILE_BYTES
        out.append(data)
    return out


def worst_cases() -> dict[str, bytes]:
    """Full-size worst cases for the time guards (AC-F16-05 ``slow``/``perf``)."""
    wide = {name: 7 for name in short_names(8000)}
    return {
        "random 64 KiB": random.Random(1).randbytes(MAX_FILE_BYTES),
        "nesting 64 KiB": b"[" * MAX_FILE_BYTES,
        "nesting closed": b"[" * (MAX_FILE_BYTES // 2) + b"]" * (MAX_FILE_BYTES // 2),
        "objects 64 KiB": b'{"a":' * (MAX_FILE_BYTES // 5),
        "8000 keys": json.dumps({"format": 1, "values": wide},
                                separators=(",", ":")).encode("ascii"),
        "5000 digits": b'{"format": 1, "values": {"music_volume": ' + b"9" * 5000 + b"}}",
        "escaped quotes": (b'{"format": 1, "values": {"x": "' + b'\\"' * 30_000 + b'", "y": '
                           + b"[" * 1001 + b"]" * 1001 + b"}}"),
        "unclosed quotes": b'"' + b'\\"' * 32_000,
    }


def write_fixtures() -> list[Path]:
    FILES.mkdir(parents=True, exist_ok=True)
    written = []
    for name, make in FIXTURES.items():
        path = FILES / name
        path.write_bytes(make())
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.parse_args(argv)
    for path in write_fixtures():
        print(path.relative_to(FILES.parents[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

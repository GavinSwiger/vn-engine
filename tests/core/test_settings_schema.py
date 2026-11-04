"""F16 key table (``04`` §4, §5.1, §12; ``07`` G4, G6, I-6, I-7): AC-F16-01 (key checks and
W71 fills) and AC-F16-02 (effective text size), plus the ``KEYS``/``FORMAT`` snapshot and the
import rule of AC-F16-33 that concern this module."""

import ast
import random
import re
from pathlib import Path

import pytest

from engine.core import settings_schema
from engine.core.settings_schema import (
    FORMAT,
    KEYS,
    LANGUAGE_CODE_MAX,
    BoolKey,
    IntKey,
    LanguageKey,
    LongNumber,
    Problem,
    SizeKey,
    check,
    effective_text_size,
    found_word,
    is_language_code,
)
from tests.fakes.username import no_real_username  # noqa: F401  (name guard, AC-F30-07)

VOLUMES = ("master_volume", "music_volume", "sound_volume", "voice_volume")
BOOLS = ("auto_wait_voice", "skip_all", "text_blips", "voice_sustain", "audio_unfocused",
         "audio_minimized", "mono", "fullscreen", "reduce_motion")
FIXED_WORDS = {"true", "false", "a long number", "a decimal number", "text", "a list",
               "an object", "null", "a value"}
DIGITS_RE = re.compile(r"-?\d{1,7}", re.ASCII)


def found(key: str, value: object) -> str:
    problem = check(key, value)
    assert problem is not None, (key, value)
    assert problem.key == key
    return problem.found


# --- AC-F16-01 --------------------------------------------------------------------------------

def test_ac_f16_01_key_table_checks_and_found_words():
    """AC-F16-01: the 22 keys (F33's ``warning_seen``, F30's two, F43's ``language``, F50's ``timing_assist`` last), each key's range/type checks, the must phrases, and that the
    found word is only digits or a fixed word."""
    assert list(KEYS) == [
        "text_cps", "text_size_pct", "auto_scale_pct", "auto_wait_voice", "skip_all",
        "master_volume", "music_volume", "sound_volume", "voice_volume", "text_blips",
        "voice_sustain", "audio_unfocused", "audio_minimized", "mono", "fullscreen",
        "reduce_motion", "window_size", "warning_seen", "username_use", "crash_label",
        "language", "timing_assist"]
    assert KEYS["text_cps"] == IntKey(10, 200, zero=True)
    assert KEYS["text_size_pct"] == IntKey(100, 150)
    assert KEYS["auto_scale_pct"] == IntKey(25, 400)
    for key in VOLUMES:
        assert KEYS[key] == IntKey(0, 100)
    for key in BOOLS:
        assert KEYS[key] == BoolKey()
    assert KEYS["window_size"] == SizeKey((640, 7680), (360, 4320))
    with pytest.raises(TypeError):
        KEYS["new_key"] = BoolKey()                       # type: ignore[index]
    with pytest.raises(ValueError):                       # unknown key: programmer error
        check("foo", 1)

    # text_cps, text_size_pct, auto_scale_pct
    for value in (0, 10, 40, 200):
        assert check("text_cps", value) is None
    for value, word in [(5, "5"), (9, "9"), (201, "201"), (-1, "-1"), (True, "true"),
                        (False, "false"), (40.0, "a decimal number")]:
        assert found("text_cps", value) == word
    for value in (100, 150):
        assert check("text_size_pct", value) is None
    assert found("text_size_pct", 99) == "99"
    assert found("text_size_pct", 151) == "151"
    assert found("text_size_pct", "130") == "text"
    for value in (25, 400):
        assert check("auto_scale_pct", value) is None
    assert found("auto_scale_pct", 24) == "24"
    assert found("auto_scale_pct", 401) == "401"

    # volumes and bools
    for key in VOLUMES:
        assert check(key, 0) is None and check(key, 100) is None
        for value, word in [(-1, "-1"), (101, "101"), (None, "null"),
                            (12345678, "a long number"), (9999999, "9999999"),
                            (-999999, "-999999"), (-1_000_000, "a long number"),  # 07 I-5 / G4
                            (10 ** 19, "a long number"), (LongNumber(), "a long number")]:
            assert found(key, value) == word, (key, value)
    for key in BOOLS:
        assert check(key, True) is None and check(key, False) is None
        for value, word in [(1, "1"), (0, "0"), ({}, "an object"), ([], "a list"),
                            ("yes", "text")]:
            assert found(key, value) == word, (key, value)

    # window_size
    for value in ([640, 360], [7680, 4320], (1280, 720)):
        assert check("window_size", value) is None
    for value in ([639, 360], [640, 4321], [1280], [1280, 720, 1], [1280.0, 720], [1, 2],
                  [True, 720], (1280,), []):
        assert found("window_size", value) == "a list"            # 07 G4
    assert found("window_size", "1280x720") == "text"
    assert found("window_size", {"w": 1280}) == "an object"
    assert found("window_size", 1280) == "1280"

    # must phrases
    assert check("text_cps", 5) == Problem("text_cps", "0 or a whole number from 10 to 200", "5")
    assert check("text_size_pct", 400) == Problem(
        "text_size_pct", "a whole number from 100 to 150", "400")
    assert check("auto_scale_pct", 1).must == "a whole number from 25 to 400"
    for key in VOLUMES:
        assert check(key, 101).must == "a whole number from 0 to 100"
    for key in BOOLS:
        assert check(key, "yes").must == "true or false"
    assert check("window_size", [1, 2]).must == (
        "a list of two whole numbers, 640 to 7680 and 360 to 4320")

    # found word is only digits (<= 7 chars) or a fixed word
    rng = random.Random(1)
    samples: list[object] = [None, True, False, 0.5, float("inf"), float("nan"), "ZZMARK" * 9,
                             "", [], [1, 2], {}, {"ZZMARK": 1}, (1, 2), LongNumber(), object(),
                             10 ** 4000, -(10 ** 4000)]
    samples += [rng.randint(-(10 ** 21), 10 ** 21) for _ in range(500)]
    samples += [rng.randint(-10 ** 7, 10 ** 7) for _ in range(500)]
    for value in samples:
        word = found_word(value)
        assert word in FIXED_WORDS or DIGITS_RE.fullmatch(word), (value, word)
        assert len(word) <= 7 or word in FIXED_WORDS


# --- AC-F16-02 --------------------------------------------------------------------------------

def test_ac_f16_02_effective_text_size():
    """AC-F16-02: the table rows, then every base 20-48 x pct 100-150 rounds half up, cap 48."""
    from decimal import ROUND_HALF_UP, Decimal
    for base, pct, size in [(28, 100, 28), (28, 110, 31), (28, 130, 36), (28, 150, 42),
                            (25, 110, 28), (35, 150, 48), (40, 130, 48), (48, 100, 48)]:
        assert effective_text_size(base, pct) == size, (base, pct)
    for base in range(20, 49):
        for pct in range(100, 151):
            exact = (Decimal(base) * pct / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            assert effective_text_size(base, pct) == min(48, int(exact))


# --- AC-F16-33 (this module's rows): FORMAT pinned to KEYS; imports ---------------------------

# Adding a key bumps FORMAT and adds a row here (07 G6, I-7); a key is never removed or
# retyped.
KEYS_BY_FORMAT = {
    1: {
        "text_cps": ("int", 10, 200, True), "text_size_pct": ("int", 100, 150, False),
        "auto_scale_pct": ("int", 25, 400, False), "auto_wait_voice": ("bool",),
        "skip_all": ("bool",), "master_volume": ("int", 0, 100, False),
        "music_volume": ("int", 0, 100, False), "sound_volume": ("int", 0, 100, False),
        "voice_volume": ("int", 0, 100, False), "text_blips": ("bool",),
        "voice_sustain": ("bool",), "audio_unfocused": ("bool",),
        "audio_minimized": ("bool",), "mono": ("bool",), "fullscreen": ("bool",),
        "reduce_motion": ("bool",), "window_size": ("size", 640, 7680, 360, 4320),
    },
}
KEYS_BY_FORMAT[2] = {**KEYS_BY_FORMAT[1], "warning_seen": ("int", 1, 1000, True)}   # F33
KEYS_BY_FORMAT[3] = {**KEYS_BY_FORMAT[2], "username_use": ("int", 0, 2, False),      # F30
                     "crash_label": ("bool",)}
KEYS_BY_FORMAT[4] = {**KEYS_BY_FORMAT[3], "language": ("language", 12)}             # F43
KEYS_BY_FORMAT[5] = {**KEYS_BY_FORMAT[4], "timing_assist": ("int", 0, 2, False)}    # F50


def _snapshot() -> dict[str, tuple]:
    out: dict[str, tuple] = {}
    for key, spec in KEYS.items():
        if isinstance(spec, IntKey):
            out[key] = ("int", spec.lo, spec.hi, spec.zero)
        elif isinstance(spec, BoolKey):
            out[key] = ("bool",)
        elif isinstance(spec, LanguageKey):
            out[key] = ("language", LANGUAGE_CODE_MAX)
        else:
            out[key] = ("size", *spec.w, *spec.h)
    return out


def test_keys_snapshot_is_pinned_to_format():
    assert FORMAT == max(KEYS_BY_FORMAT), "FORMAT changed without a KEYS_BY_FORMAT row"
    assert _snapshot() == KEYS_BY_FORMAT[FORMAT], "a key changed: bump FORMAT (07 G6)"
    for older in range(1, FORMAT):                       # never removed or retyped (I-7)
        for key, row in KEYS_BY_FORMAT[older].items():
            assert KEYS_BY_FORMAT[FORMAT].get(key) == row


def test_schema_imports_nothing_from_engine():
    tree = ast.parse(Path(settings_schema.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0 and not node.module.startswith("engine")
            assert node.module.split(".")[0] not in ("pickle", "marshal", "importlib")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("engine")
                assert alias.name.split(".")[0] not in ("pickle", "marshal", "importlib")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("eval", "exec")

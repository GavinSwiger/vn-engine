"""F43's settings key (``04`` §7.3, §8.4, §10; ``07`` I-10): AC-F43-10, ``language`` keeps
a valid code and refuses anything else without echoing it; ``FORMAT`` 4; a format-3 file
still reads. Plus the code pattern's agreement with ``core/langtags.py``."""

import json

import pytest

from engine.core.settings_schema import (
    FORMAT,
    LANGUAGE_CODE_MAX,
    LANGUAGE_NOT_CHOSEN,
    check,
    is_language_code,
)
from engine.persist.settings_file import Outcome, encode_settings, parse_settings
from tests.fakes.username import no_real_username  # noqa: F401  (name guard, AC-F30-07)

VALID = ["ja", "en", "yue", "pt-BR", "zh-Hans", "zh-Hant", "es-419", "sr-Latn", "abc-12345678"]
REFUSED = ["", "j", "JA", "Ja", "jpan", "ja-", "ja-B", "pt_BR", "pt-BR-x", "zh-Hans-CN",
           "abc-123456789", "ja\n", " ja", "ja ", "日本", "ja-日本", "ｊａ", "ZZMARKZZMARK",
           "ja-ZZMARKZZM"]
NOT_TEXT = [(1, "1"), (True, "true"), (None, "null"), (["ja"], "a list"),
            ({"ja": 1}, "an object"), (1.5, "a decimal number")]


def test_ac_f43_10_language_setting():
    """AC-F43-10: valid codes kept (ASCII, the code pattern, at most 12 characters); every
    other value refused as W71 with a fixed found word; ``FORMAT`` 4 writes and reads it;
    a format-3 file reads as current with ``language`` absent (not chosen)."""
    assert FORMAT >= 4 and LANGUAGE_CODE_MAX == 12
    for code in VALID:
        assert check("language", code) is None and is_language_code(code), code
        assert len(code) <= LANGUAGE_CODE_MAX
        data = encode_settings({"language": code, "music_volume": 40})
        data.decode("ascii")
        assert json.loads(data) == {"format": FORMAT,
                                    "values": {"language": code, "music_volume": 40}}
        assert parse_settings(data).values == {"music_volume": 40, "language": code}
    for value in REFUSED:
        problem = check("language", value)
        assert problem is not None and not is_language_code(value), value
        assert (problem.must, problem.found) == (
            "a language code such as ja, pt-BR or zh-Hans", "text"), value
        with pytest.raises(ValueError):
            encode_settings({"language": value})
    for value, word in NOT_TEXT:
        assert check("language", value).found == word, value

    # A refused value in the file: W71's fills never hold its text.
    marker = json.dumps({"format": 4, "values": {"language": "ZZMARK" * 2, "mono": True}})
    loaded = parse_settings(marker.encode("ascii"))
    assert loaded.outcome is Outcome.OK and loaded.values == {"mono": True}
    [problem] = loaded.problems
    assert problem.key == "language" and "ZZMARK" not in repr(problem)

    # Format 3 (F30's file, as tests/fakes/first_launch.py writes it) reads as current.
    old = parse_settings(json.dumps({"format": 3, "values": {"username_use": 2}}).encode())
    assert old.outcome is Outcome.OK and old.writable and old.problems == ()
    assert dict(old.values) == {"username_use": 2} and "language" not in old.values
    # ... and a format-3 file holding a code (a downgrade-then-upgrade) keeps it.
    assert parse_settings(b'{"format": 3, "values": {"language": "ja"}}').values == {
        "language": "ja"}
    # A format after FORMAT is newer: W73, known keys used, never written.
    newer = parse_settings(b'{"format": 6, "values": {"language": "ko"}}')
    assert newer.outcome is Outcome.NEWER and newer.values == {"language": "ko"}

    # The effective default is "not chosen", so Reset clears a stored language (W4 then
    # re-runs the first-launch rule).
    from engine.app.settings import config_defaults
    from engine.core.config_schema import Config
    assert config_defaults(Config())["language"] == LANGUAGE_NOT_CHOSEN == ""
    assert check("language", LANGUAGE_NOT_CHOSEN) is not None          # never stored


def test_language_pattern_agrees_with_langtags():
    """``settings_schema`` imports nothing from ``engine``, so it keeps its own copy of the
    code pattern; it must agree with ``core/langtags.py`` (F43-P1) on every row."""
    langtags = pytest.importorskip("engine.core.langtags")
    for value in VALID + REFUSED:
        assert langtags.is_language_code(value) == is_language_code(value), value

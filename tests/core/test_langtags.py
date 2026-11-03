"""F43 P1: language codes, the built-in names, and the first-launch match (``core/langtags``).

AC-F43-16; the code check and the built-in table as plain unit tests.
"""

import pytest

from engine.core.langtags import (
    BUILTIN_LANGUAGES,
    english_name,
    first_language,
    is_language_code,
    own_name,
    system_subtags,
)

# --- AC-F43-16: first launch: exact tag, language only, zh-CN/zh-TW, else the original ------

GAME = ("ja", "pt", "pt-BR", "zh-Hans", "zh-Hant", "sr-Latn", "fr")

FIRST_LAUNCH = [
    # system tag, shown, mode, expected (None = the original)
    ("ja", GAME, "system", "ja"),                        # exact
    ("ja-JP", GAME, "system", "ja"),                     # language only
    ("pt-BR", GAME, "system", "pt-BR"),                  # exact beats language only
    ("pt-br", GAME, "system", "pt-BR"),                  # case ignored, shown spelling kept
    ("pt_BR.UTF-8", GAME, "system", "pt-BR"),            # POSIX LANG form
    ("pt-PT", GAME, "system", "pt"),                     # PR-F43-09: pt-PT → pt
    ("pt-PT", ("pt-BR",), "system", "pt-BR"),            # another variety of the language
    ("zh-CN", GAME, "system", "zh-Hans"),                # PR-F43-09 mapping
    ("zh-TW", GAME, "system", "zh-Hant"),
    ("zh-HK", GAME, "system", "zh-Hant"),
    ("zh_SG", GAME, "system", "zh-Hans"),
    ("zh-Hant-CN", GAME, "system", "zh-Hant"),           # a script subtag beats the region
    ("zh-Hans", GAME, "system", "zh-Hans"),              # Windows' tag
    ("zh-TW", ("zh-Hans",), "system", None),             # never the other script
    ("zh-CN", ("zh-CN", "zh-Hans"), "system", "zh-CN"),  # an exact file wins
    ("sr-Latn-RS", GAME, "system", "sr-Latn"),           # language + one subtag
    ("de-DE", GAME, "system", None),                     # not translated: the original
    ("en-US", GAME, "system", None),                     # the original's own language
    ("fr-CA@euro", GAME, "system", "fr"),
    ("C", GAME, "system", None),                         # no language
    ("C.UTF-8", GAME, "system", None),
    ("POSIX", GAME, "system", None),
    ("", GAME, "system", None),
    (None, GAME, "system", None),                        # no system language (macOS app)
    ("日本語", GAME, "system", None),                     # not a tag
    ("ja-" + "x" * 70, GAME, "system", None),            # too long
    ("ja", (), "system", None),                          # one language only
    ("ja", GAME, "source", None),                        # first = "source"
    ("ja", GAME, "ask", None),                           # ask: the original, then the pick
]


@pytest.mark.parametrize("tag, shown, mode, expected", FIRST_LAUNCH)
def test_ac_f43_16_first_launch_language(tag, shown, mode, expected):
    assert first_language(tag, shown, mode) == expected


# --- PR-F43-01 code check, built-in names (unit) ---------------------------------------------

CODES = [
    ("ja", True), ("pt-BR", True), ("zh-Hans", True), ("es-419", True), ("fil", True),
    ("pt-br", True), ("zh-Hant12", True), ("abc-abcdefgh", True),
    ("j", False), ("jpan", False), ("JA", False), ("Ja", False), ("pt-B", False),
    ("pt-", False), ("pt_BR", False), ("zh-Hant-TW", False), ("abc-abcdefghi", False),
    ("ja\n", False), (" ja", False), ("ｊａ", False), ("", False), (None, False), (12, False),
    ("../x", False), ("ja.po", False),
]


@pytest.mark.parametrize("code, ok", CODES)
def test_language_code_check(code, ok):
    assert is_language_code(code) is ok


def test_builtin_table_and_names():
    codes = [row.code for row in BUILTIN_LANGUAGES]
    assert len(BUILTIN_LANGUAGES) == 40 and len(set(codes)) == 40
    assert all(is_language_code(code) for code in codes)
    assert all(row.english and row.own and row.sample for row in BUILTIN_LANGUAGES)
    assert own_name("ja") == "日本語" and english_name("ja") == "Japanese"
    assert own_name("zh-Hans") == "简体中文"
    assert english_name("zh-Hans") == "Chinese (Simplified)"
    assert own_name("pt-br") == "Português (Brasil)"         # case-folded lookup
    assert own_name("tlh") == "tlh" and english_name("tlh") == "tlh"   # not built in
    assert system_subtags("zh_Hant_TW.UTF-8") == ("zh", "hant", "tw")

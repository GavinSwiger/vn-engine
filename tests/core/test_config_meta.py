"""F30 step 1 — AC-F30-04: ``[meta]`` (``username``, ``username_fallback``) and F30's eight
``[words]`` keys (``04`` §9; SEC-F30-10 (b); ``07`` I-9, I-13). A bad value is one F01
``ConfigError`` in the loader's form and the default is kept; a blank fake-crash hint or
label follows the usual word rule (W65 at install time, the default kept)."""

from engine.core.config_schema import Config, MetaConfig, WordsConfig, key_doc
from engine.ui.theme import Words, resolve_words, w65_text
from tests.fakes.username import no_real_username  # noqa: F401  (name guard, AC-F30-07)

LINE2 = "config.toml, line 2: "
FALLBACK_MUST = ("[meta] username_fallback must be plain text of 1 to 32 characters, with no "
                 "control characters, but found ")
HINT_MUST = ("must be one line of plain text, 1 to 120 characters, because the fake crash "
             "screen ")
WORD_DEFAULTS = {
    "fake_crash_message": "Something went wrong.",
    "fake_crash_hint": "Press Esc or Enter to continue",
    "fake_crash_label": "This is part of the story.",
    "settings_username": "Use my computer's user name",
    "settings_crash_label": "Label fake error screens",
    "ask_username": "This game can show your computer's user name in the story. It is never "
                    "saved or sent anywhere. Allow it?",
    "ask_username_yes": "Allow",
    "ask_username_no": "Don't allow",
}


class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, fmt, *args, **kwargs):
        self.lines.append(fmt % args)


def test_ac_f30_04_meta_and_the_eight_words(load):
    # No rows: the defaults, each key described for Studio's config Help (07 I-14).
    assert Config().meta == MetaConfig(username=False, username_fallback="friend")
    words = Words(WordsConfig())
    assert {key: words.get(key) for key in WORD_DEFAULTS} == WORD_DEFAULTS
    assert key_doc("meta", "") and key_doc("meta", "username") \
        and key_doc("meta", "username_fallback")
    assert all(key_doc("words", key) for key in WORD_DEFAULTS)

    # Accepted values.
    for rows, expected in [
        ('[meta]\nusername = true\nusername_fallback = "' + "a" * 32 + '"\n',
         MetaConfig(True, "a" * 32)),
        ('[meta]\nusername_fallback = "pal"\n', MetaConfig(False, "pal")),
    ]:
        result = load(rows)
        assert result.errors == [] and result.config.meta == expected, rows
    for key in ("fake_crash_hint", "fake_crash_label"):
        for value in ("a" * 120, "Press any key", "{b}Esc{/b}"):
            result = load(f'[words]\n{key} = "{value}"\n')
            assert result.errors == [] and getattr(result.config.words, key) == value

    # Refused values: one error each, exact text, the default kept.
    rows = [
        ('[meta]\nusername = "yes"\n',
         LINE2 + '[meta] username must be true or false, but found the text "yes"'),
        ('[meta]\nusername_fallback = ""\n', LINE2 + FALLBACK_MUST + 'the text ""'),
        ('[meta]\nusername_fallback = "   "\n', LINE2 + FALLBACK_MUST + 'the text "   "'),
        ('[meta]\nusername_fallback = "' + "a" * 33 + '"\n',
         LINE2 + FALLBACK_MUST + 'the text "' + "a" * 33 + '"'),
        ('[meta]\nusername_fallback = "fr\\u0001"\n',
         LINE2 + FALLBACK_MUST + 'the text "fr\\x01"'),
        ('[meta]\nusername_fallback = "fr\\u200eend"\n',
         LINE2 + FALLBACK_MUST + 'the text "fr‎end"'),
    ]
    for key, why in (("fake_crash_hint", "always shows it"),
                     ("fake_crash_label", "shows it when the player turns the label on")):
        must = f"{LINE2}[words] {key} {HINT_MUST}{why}, but it "
        rows += [
            (f'[words]\n{key} = "a\\nb"\n', must + "has 2 lines."),
            (f'[words]\n{key} = "a\\u2028b\\u2029c"\n', must + "has 3 lines."),
            (f'[words]\n{key} = "a\\r\\nb"\n', must + "has 2 lines."),
            (f'[words]\n{key} = "' + "a" * 121 + '"\n', must + "has 121 characters."),
            (f'[words]\n{key} = "bell\\u0007"\n', must + "has a control character."),
            (f'[words]\n{key} = "rlo\\u202e"\n', must + "has a control character."),
            (f"[words]\n{key} = 5\n",
             f"{LINE2}[words] {key} {HINT_MUST}{why}, but found 5"),
        ]
    for data, message in rows:
        result = load(data)
        assert [e.format() for e in result.errors] == [message], data
        assert result.config.meta == MetaConfig(), data
        assert result.config.words == WordsConfig(), data

    # A blank hint or label: W65, the default kept (07 I-9).
    for key in ("fake_crash_hint", "fake_crash_label"):
        for value in ("", "   "):
            result = load(f'[words]\n{key} = "{value}"\n')
            assert result.errors == [], (key, value)
            log = _Log()
            words = resolve_words(result.config.words, log=log)
            assert log.lines == [w65_text(key, WORD_DEFAULTS[key])]
            assert words.get(key) == WORD_DEFAULTS[key]

    # A misspelled key: F01's warning with the suggestion.
    result = load("[meta]\nusernam = true\n")
    assert result.errors == []
    assert result.warnings == [
        'config.toml, line 2: unknown key [meta] usernam — did you mean "username"?']

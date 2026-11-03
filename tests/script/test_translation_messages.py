"""F43 W0: the ten translation texts W247–W256 (``engine/script/messages.py``) against their
``cases.toml`` rows (``time = "translate"``: data, never the script load's), each formatted
with the place it is raised with (01 §5.4)."""

from engine.script.diagnostics import ScriptWarning
from engine.script.messages import format_message
from tests.script.message_cases import load_cases

_PO = "translations/ja.po"

# Each row's arguments and the warning's file and line, by the id's form
# (``F43-<ac>-<code>[-<form>]``). W247, W253 and W254 name their file; W248–W251 get a place.
_FORMS = {
    "W253-bad_name": (("bad_name", "japanese.po", "japanese"), "translations/japanese.po", None),
    "W253-original": (("original", "en.po", "en"), "translations/en.po", None),
    "W253-too_many": (("too_many", "zu.po"), "translations/zu.po", None),
    "W247-utf8": (("utf8", "ja.po", "Japanese"), _PO, None),
    "W247-large": (("large", "ja.po", "Japanese"), _PO, None),
    "W247-entries": (("entries", "ja.po", "Japanese"), _PO, None),
    "W248-quote": (("quote",), _PO, 120),
    "W248-no_msgstr": (("no_msgstr",), _PO, 120),
    "W248-twice": (("twice", "start.3"), _PO, 120),
    "W248-long": (("long", 2000), _PO, 120),
    "W248-unsupported": (("unsupported",), _PO, 120),
    "W249": ((format_message("E161", ("open",)),), _PO, 120),
    "W250": (("score",), _PO, 120),
    "W251": (("name",), _PO, 120),
    "W255": (("English",), None, None),
    "W252": (("Japanese", "ja", 37, "日本語は"), None, None),
    "W254": (("ar.po",), "translations/ar.po", None),
    "W256": (("Japanese", 12, 3), None, None),
}


def test_w0_every_translation_text_matches_its_row():
    rows = {c.id.split("-", 2)[2]: c for c in load_cases() if c.feature == "F43"}
    assert set(rows) == set(_FORMS)
    assert {row.code for row in rows.values()} == {f"W{n}" for n in range(247, 257)}
    for form, (args, file, line) in _FORMS.items():
        row = rows[form]
        assert row.time == "translate" and not row.runnable, form
        text = format_message(row.code, args)
        warning = ScriptWarning(text, code=row.code, file=file, line=line)
        assert warning.format() == row.expect["exact"], form
    # The forms the table leaves open: one or few characters, one count, several names.
    assert format_message("W252", ("Thai", "th", 1, "ก")).startswith(
        "Thai: 1 character can't be drawn by any of the game's fonts (ก), so it shows as a box.")
    assert "(日, 本 and 語), so" in format_message("W252", ("Japanese", "ja", 3, "日本語"))
    assert format_message("W256", ("Japanese", 0, 1)) == \
        "Japanese: 1 text changed since it was translated."
    assert format_message("W256", ("Japanese", 1, 0)) == \
        "Japanese: 1 text isn't translated yet (players see the original)."
    assert format_message("W250", (("score", "lives"),)).startswith(
        "the translation uses {score} and {lives}, which")
    # Text from the file is shown safely; an unknown form reads as the unsupported entry.
    assert format_message("W248", ("twice", "a‮b")).startswith('the key "a\\u202eb"')
    assert format_message("W248", ("plural",)) == \
        "this kind of entry isn't supported, so this entry is skipped."

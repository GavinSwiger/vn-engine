"""F41 L1: the six lint texts W237–W242 (``engine/script/messages.py``) against their
``cases.toml`` rows (``time = "lint"``: data, never the load's): AC-F41-05."""

from engine.script.messages import format_message
from tests.script.message_cases import load_cases

# Each row's arguments, by the id's form (``F41-05-<code>[-<kind>]``).
_ARGS = {
    "W237": ("old_ending",),
    "W238": ("kenji",),
    "W239": ("hana sad_blink1",),
    "W240": ("music/old_theme.ogg",),
    "W241": ("lantern_count",),
    "W242-define": ("define", "max_tries"),
    "W242-transition": ("transition", "slow_fade"),
    "W242-position": ("position", "far_left"),
    "W242-meter": ("meter", "trust"),
}


def test_ac05_the_six_lint_texts_match_their_rows():
    rows = {c.id.removeprefix("F41-05-"): c for c in load_cases() if c.feature == "F41"}
    assert set(rows) == set(_ARGS)
    assert {row.code for row in rows.values()} == {f"W{n}" for n in range(237, 243)}
    for form, args in _ARGS.items():
        row = rows[form]
        assert row.time == "lint" and not row.runnable, form
        assert format_message(row.code, args) == row.expect["exact"], form
    # A kind W242 doesn't know reads as a define; names are shown like any script name.
    assert format_message("W242", ("other", "x")) == 'define "x" is defined but never used.'
    assert format_message("W239", ("bg‮park",)) == \
        'picture "bg\\u202epark" isn\'t shown anywhere in the story.'

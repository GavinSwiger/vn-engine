"""F59 checks on choices in Studio (SPEC §5): AC-F59-08 (the Choice form reads and writes a
check; Events rows; the Check dialog's words and odds) and AC-F59-09 (the badge's color)."""

from dataclasses import replace

import engine.script  # noqa: F401  registers every statement
from engine.core.config_schema import ChoiceTheme
from engine.render.choices import rgb_hex
from engine.runtime.commands import ShownChoice, Span, Style, TaggedText
from engine.tools.editor import checkdialog, forms
from engine.tools.editor.forms import (CHECK_FAILURE, CHECK_LINES, CHECK_REMOVE_TEXT,
                                       CHECK_SUCCESS, ChoiceItem, ChoiceValues, choice_lines,
                                       choice_patches, choice_problems, read_choice, rows)
from engine.tools.editor.scenes import parse_chunk
from engine.ui.builtin.choice_screen import with_badge

SCENE = '''label t:
    menu:
        "Pick the lock" check logic hard:
            success:
                "It clicks."
            failure:
                "It holds."
        "Leave":
            jump hall
'''


def _read(text: str = SCENE):
    read = parse_chunk("script/t.vns", text, positions=frozenset())
    assert read is not None and read.error is None, read
    return read, text.split("\n")[:-1]


def _apply(lines, patches):
    out = list(lines)
    for patch in sorted(patches, key=lambda p: p.first, reverse=True):
        out[patch.first - 1:patch.last] = patch.lines
    return out


def test_ac08_read_and_events_rows():
    read, lines = _read()
    pick, leave = read_choice(read, 0).choices
    assert (pick.check, pick.had_check, pick.in_text) == ("logic hard", True, True)
    assert forms.choice_summary(pick) == CHECK_LINES
    assert (leave.check, leave.goes) == ("", "hall")
    texts = [(row.depth, row.word, row.summary) for row in rows(read, lines)]
    assert texts[1] == (1, '"Pick the lock"', "check logic hard")
    assert (2, CHECK_SUCCESS, "") in texts and (2, CHECK_FAILURE, "") in texts
    assert texts.index((2, CHECK_SUCCESS, "")) < texts.index((2, CHECK_FAILURE, ""))


def test_ac08_writes_new_changed_wrapped_and_refuses_removal():
    read, lines = _read()
    old = read_choice(read, 0)
    pick, leave = old.choices
    # A new menu with a checked option.
    new = ChoiceValues(choices=(ChoiceItem("Bluff", goes="hall", check="empathy 7"),))
    assert choice_lines(new, "    ", "    ") == [
        "    menu:", '        "Bluff" check empathy 7:', "            success:",
        "                jump hall", "            failure:", "                $ pass"]
    # A changed difficulty patches the header only.
    harder = replace(old, choices=(replace(pick, check="logic legendary"), leave))
    after = _apply(lines, choice_patches(read, 0, lines, harder))
    assert after[2] == '        "Pick the lock" check logic legendary:' and after[3:] == lines[3:]
    # A check added to a plain option wraps its lines under success:.
    checked = replace(old, choices=(pick, replace(leave, check="logic easy")))
    after = _apply(lines, choice_patches(read, 0, lines, checked))
    assert after[7:] == ['        "Leave" check logic easy:', "            success:",
                         "                jump hall", "            failure:",
                         "                $ pass"]
    again = parse_chunk("script/t.vns", "\n".join(after) + "\n", positions=frozenset())
    assert again is not None and again.error is None
    # Removing a check is refused, in the form's problem line too.
    gone = replace(old, choices=(replace(pick, check=""), leave))
    assert choice_patches(read, 0, lines, gone) == CHECK_REMOVE_TEXT
    assert choice_problems(gone) == CHECK_REMOVE_TEXT
    assert choice_problems(replace(old, choices=(replace(pick, check="logic"), leave))) == \
        forms.CHECK_BAD_TEXT
    assert choice_problems(old) is None


def test_ac08_check_dialog_words_and_odds():
    assert checkdialog.check_label("") == checkdialog.NO_CHECK
    assert checkdialog.check_label("street_smarts hard") == "Street smarts · Hard"
    assert checkdialog.difficulty_written("medium (10)") == "medium"
    assert checkdialog.difficulty_written(" 9 ") == "9"
    assert checkdialog.odds_line("logic", "hard (12)") == (
        "Odds when logic is 0: 3% · 2: 17% · 4: 42% · 6: 72% · 8: 92% · 10: 97%")
    assert checkdialog.odds_line("", "hard") == checkdialog.odds_line("logic", "tough") == ""


def test_ac09_badge_draws_first_in_the_marker_color():
    theme = ChoiceTheme()
    body = TaggedText((Span("Pick the lock", Style()),))
    shown = with_badge(ShownChoice("k", body, False, "[Logic · Hard · 28%]"), theme)
    assert shown.pieces[0] == Span("[Logic · Hard · 28%] ",
                                   Style(color=rgb_hex(theme.marker.fill_color)))
    assert shown.pieces[1:] == body.pieces
    locked = with_badge(ShownChoice("k", body, True, "[Logic · Hard · 28%]"), theme)
    assert locked.pieces[0].style.color is None                     # the locked text color
    assert with_badge(ShownChoice("k", body, False), theme) is body

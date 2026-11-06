"""F59 retry checks in Studio: the Choice form reads and writes ``retry``, Events rows show it,
and the Check dialog's "Can retry after the stat changes" option."""

import tkinter as tk
from dataclasses import replace

import pytest

import engine.script  # noqa: F401  registers every statement
from engine.tools.editor import checkdialog
from engine.tools.editor.forms import (ChoiceItem, ChoiceValues, check_ok, choice_lines,
                                       choice_patches, choice_problems, read_choice, rows)
from engine.tools.editor.scenes import parse_chunk

SCENE = '''label t:
    menu:
        "You're scared." check empathy 7 retry:
            success:
                "Of the river."
            failure:
                "He looks away."
        "Pick the lock" check logic hard:
            success:
                "It clicks."
            failure:
                "It holds."
'''


def _read():
    read = parse_chunk("script/t.vns", SCENE, positions=frozenset())
    assert read is not None and read.error is None, read
    return read, SCENE.split("\n")[:-1]


def _apply(lines, patches):
    out = list(lines)
    for patch in sorted(patches, key=lambda p: p.first, reverse=True):
        out[patch.first - 1:patch.last] = patch.lines
    return out


def test_read_and_events_rows_show_retry():
    read, lines = _read()
    scared, lock = read_choice(read, 0).choices
    assert (scared.check, lock.check) == ("empathy 7 retry", "logic hard")
    summaries = [row.summary for row in rows(read, lines) if row.word.startswith('"')]
    assert summaries == ["check empathy 7 retry", "check logic hard"]


def test_write_add_and_drop_retry():
    read, lines = _read()
    old = read_choice(read, 0)
    scared, lock = old.choices
    on = replace(old, choices=(scared, replace(lock, check="logic hard retry")))
    after = _apply(lines, choice_patches(read, 0, lines, on))
    assert after[7] == '        "Pick the lock" check logic hard retry:'
    off = replace(old, choices=(replace(scared, check="empathy 7"), lock))
    after = _apply(lines, choice_patches(read, 0, lines, off))
    assert after[2] == '        "You\'re scared." check empathy 7:' and after[3:] == lines[3:]
    new = ChoiceValues(choices=(ChoiceItem("Bluff", check="empathy 7 retry"),))
    assert choice_lines(new, "", "    ")[1] == '    "Bluff" check empathy 7 retry:'
    assert check_ok("empathy 7 retry") and not check_ok("empathy 7 again")
    assert not check_ok("empathy retry")
    assert choice_problems(on) is None


def test_dialog_words():
    assert checkdialog.check_label("logic hard retry") == "Logic · Hard · retry"
    assert checkdialog.check_label("logic hard again") == checkdialog.NO_CHECK
    assert checkdialog.check_value("logic", "hard (12)", True) == "logic hard retry"
    assert checkdialog.check_value("logic", "hard (12)", False) == "logic hard"
    assert checkdialog.check_value("", "", True) == ""
    assert checkdialog.RETRY == "Can retry after the stat changes"


@pytest.mark.tk
def test_the_dialog_reads_and_writes_retry():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        dialog = checkdialog.CheckDialog(root, "empathy 7 retry", ["empathy", "logic"])
        assert dialog.retry.get() is True and dialog.value() == "empathy 7 retry"
        dialog.retry.set(False)
        assert dialog.value() == "empathy 7"
        plain = checkdialog.CheckDialog(root, "logic hard", ["empathy", "logic"])
        assert plain.retry.get() is False
        plain.retry.set(True)
        plain._pick(0)
        assert plain.result == "logic hard retry"
        dialog.dialog.destroy()
    finally:
        root.destroy()

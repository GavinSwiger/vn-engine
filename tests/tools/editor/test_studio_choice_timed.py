"""F51 step W4, the Choice form's Time limit section (``01`` §7.1): AC-F51-27 (its texts,
the disabled state, the default pick, the ``n. "text"`` list, the three problem texts, OK
disabled while one shows). Tk, in a real Studio window on the sample game."""

import pytest

from engine.tools.editor import formdialogs, forms
from engine.tools.editor.forms import ChoiceItem, ChoiceValues

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import helper, sample_game  # noqa: E402,F401,I001
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk


def _card(dialog) -> str:
    return dialog.card.get("1.0", "end-1c")


def _disabled(widget) -> bool:
    return widget.instate(["disabled"])


def test_ac27_time_limit_section(studio, tmp_path, helper):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    names = ed.win.story.names()
    values = ChoiceValues("", "", "Say something!", (
        ChoiceItem("I love you too.", old=0), ChoiceItem("I need to think.", old=1),
        ChoiceItem("..." + "x" * 40, old=2), ChoiceItem("Kiss", "trust > 2", old=3)))
    d = formdialogs.ChoiceDialog(ed.root, values, names=names)
    ed.root.update()
    # Texts and the unticked state.
    assert (formdialogs.TIME_LIMIT, formdialogs.GIVE_THE_PLAYER, formdialogs.SECONDS,
            formdialogs.TIMEOUT_PICK) == ("Time limit", "Give the player", "seconds",
                                         "When time runs out, pick")
    assert str(d.timed_box.cget("text")) == "Give the player"
    assert not d.timed.get() and d.seconds.get() == "5"
    assert _disabled(d.seconds_box) and _disabled(d.timeout_box)
    assert list(d.timeout_box.cget("values")) == [
        '1. "I love you too."', '2. "I need to think."', '3. "...' + "x" * 26 + '…"',
        '4. "Kiss"']
    assert _card(d).splitlines()[0] == "menu:"
    # Ticking: enabled, and the last option with no condition is picked.
    d.timed.set(True)
    ed.root.update()
    assert not _disabled(d.seconds_box) and not _disabled(d.timeout_box)
    assert d.timeout_var.get().startswith('3. "...')
    assert _card(d).splitlines()[0] == "menu time 5:"
    assert '"' + "..." + "x" * 40 + '" timeout:' in _card(d)
    assert d.problem.cget("text") == "" and not _disabled(d.buttons[0])
    # The three problems, each disabling OK.
    d.timeout_var.set('4. "Kiss"')                          # has a condition
    assert d.problem.cget("text") == forms.TIMEOUT_CONDITION_TEXT == (
        'The option chosen when time runs out can\'t have an "Only show when" condition. '
        "Clear its condition, or pick another option.")
    assert _disabled(d.buttons[0])
    d.timeout_var.set('2. "I need to think."')
    assert d.problem.cget("text") == "" and not _disabled(d.buttons[0])
    d.seconds.set("61")
    assert d.problem.cget("text") == forms.TIME_RANGE_TEXT == "The time limit is 1 to 60 seconds."
    assert _disabled(d.buttons[0])
    d._pick(0)
    assert d.result is None and d.dialog.winfo_exists()      # OK waits
    d.seconds.set("7.50")
    assert d.problem.cget("text") == "" and _card(d).splitlines()[0] == "menu time 7.5:"
    d.chosen = 1                                             # reorder: the pick follows
    d.move(-1)
    assert d.timeout_var.get() == '1. "I need to think."'
    d.chosen = 0
    d.remove()                                               # removing it clears the pick
    assert d.timeout_var.get() == ""
    assert d.problem.cget("text") == forms.TIMEOUT_PICK_TEXT == (
        "Pick the option to choose when time runs out.")
    assert _disabled(d.buttons[0])
    d.timeout_var.set('1. "I love you too."')
    d._pick(0)
    assert d.result is not None and d.result.time == "7.5"
    assert [item.timeout for item in d.result.choices] == [True, False, False]
    # A timed menu read back keeps its number as written; unticking drops the marks.
    timed = ChoiceValues(choices=(ChoiceItem("Go", old=0), ChoiceItem("...", old=1,
                                                                      timeout=True)),
                         time="2.50")
    again = formdialogs.ChoiceDialog(ed.root, timed, names=names)
    ed.root.update()
    assert again.timed.get() and again.timeout_var.get() == '2. "..."'
    assert again.values() == timed
    again.timed.set(False)
    assert again.values().time == "" and not any(i.timeout for i in again.values().choices)
    assert _disabled(again.seconds_box)
    again._pick(1)

"""F59 retry (white) checks, the script side: ``check <meter> <difficulty> retry`` parses (with
and without ``if``), its E408 forms, and W294 for a retry check on a meter nothing changes."""

from engine.script.choicecheck import badge, check_code
from engine.script.messages import format_message
from tests.runtime.menu_story import load_text

STORY = '''define hana = Character("Hana")
points logic empathy 0 to 10 start 3
default met = True
label start:
    menu:
        "You're scared of something." check empathy 7 retry:
            success:
                hana "...Of the river."
            failure:
                "He looks away."
        "The gate." check logic 9 retry if met:
            success:
                hana "How?"
            failure:
                hana "No."
        "Train.":
            points empathy += 1
'''


def _choices(result):
    return result.program.labels["start"].block[0].choices


def test_retry_parses_with_and_without_if(tmp_path):
    result = load_text(tmp_path, STORY)
    assert not result.errors, [e.format() for e in result.errors]
    scared, gate, train = _choices(result)
    assert (scared.check.meter, scared.check.difficulty, scared.check.retry) == (
        "empathy", 7, True)
    assert gate.check.retry and gate.condition.source == "met"
    assert train.check is None
    plain = load_text(tmp_path, STORY.replace(" 7 retry:", " 7:"))
    assert _choices(plain)[0].check.retry is False
    assert _choices(plain)[0].key == scared.key               # retry isn't in the key
    assert check_code("empathy", "7", True) == "check empathy 7 retry"


def test_w294_a_retry_check_on_a_meter_nothing_changes(tmp_path):
    result = load_text(tmp_path, STORY)
    w294 = [(w.code, w.line) for w in result.warnings if w.code == "W294"]
    assert w294 == [("W294", 11)]                            # logic: no line changes it
    assert format_message("W294", ("logic",)).startswith(
        "this check can be retried once logic changes, but no line changes logic")
    changed = STORY.replace("            points empathy += 1\n",
                            "            points empathy += 1\n            $ points.add(\"logic\", 1)\n")
    assert not [w for w in load_text(tmp_path, changed).warnings if w.code == "W294"]


def test_the_waiting_badge():
    assert badge("empathy", 3, 7, waiting=True) == (
        "[Empathy · Trivial · Retry once Empathy changes]")

"""The launch phase's error rules (F03 ``04-technical.md`` §7.6 phase 2 and the 50-error cap).

ACs: AC-F03-29 (launch errors are collected), AC-F03-30 (the helper row; the message rows are
``cases.toml`` rows run by ``test_messages_f03.py``), AC-F03-46's define row (also a row).
The app half of AC-F03-29 (the error screen, a load error first) is in
``tests/app/test_story_driver.py``.
"""

import pytest

from engine.runtime.commands import StoryFailed
from engine.runtime.headless import run_headless
from engine.runtime.launch import LaunchJob, run_launch
from engine.script.diagnostics import ScriptErrorGroup
from tests.runtime.story import advance, load_files, load_r, start
from tests.script.helpers import template_r

E100_10 = "…and 10 more problems. Fix these and launch again."


def load_r2(root, R2: str, *, S: str | None = None, T: str | None = None):
    """R with line 2 replaced."""
    return load_files(root, {"main.vns": template_r(S=S, T=T, replace={2: R2})})


# --- AC-F03-29 — launch errors are collected --------------------------------------------------

def test_ac_f03_29_fifty_of_sixty_errors_in_order(tmp_path):
    program = load_r(tmp_path, T="⏎".join(f"define d{k} = 1 / 0" for k in range(60)))
    result = run_launch(program)
    assert result.namespace is None and result.error_count == 60
    assert len(result.errors) == 50
    assert [e.line for e in result.errors] == list(range(11, 61))
    assert [e.code for e in result.errors] == ["E85g"] * 50
    assert all(e.format().startswith(f"script/main.vns, line {11 + k}: define d{k} couldn't "
                                     "be set: this divides by zero.")
               for k, e in enumerate(result.errors))
    commands = run_headless(program, seed=42)
    assert len(commands) == 1 and type(commands[0]) is StoryFailed
    group = commands[0].error
    assert type(group) is ScriptErrorGroup and group.total == 60
    text = group.format()
    assert text.startswith("The script has 60 problems:")
    assert text.split("\n\n")[-1] == E100_10


def test_ac_f03_29_dependants_are_skipped_silently(tmp_path):
    program = load_r(tmp_path, T="define a = 1 / 0⏎define b = a + 1⏎define c = b * 2⏎"
                                 "define e = 1 / 0")
    result = run_launch(program)
    assert result.error_count == 2
    assert [(e.code, e.line) for e in result.errors] == [("E85g", 11), ("E85g", 14)]
    assert [e.message.split(" couldn't")[0] for e in result.errors] == ["define a", "define e"]


def test_ac_f03_29_defines_come_before_speakers(tmp_path):
    result = run_launch(load_r2(tmp_path, 'define daichi = "Daichi"', S='daichi "Yo."',
                                T="define e = 1 / 0"))
    assert [(e.code, e.line) for e in result.errors] == [("E85g", 11), ("E75", 2)]


def test_ac_f03_29_later_phases_run_only_after_clean_defines(tmp_path):
    calls = []

    def phase4():
        calls.append("image scan")
        return True

    def phase5():
        calls.append("stage check")
        return True

    for T, expected in (("define e = 1 / 0", []), (None, ["image scan", "stage check"])):
        calls.clear()
        job = LaunchJob(load_r(tmp_path / str(len(expected)), T=T))
        job.clean_phases += [phase4, phase5]
        while not job.step():
            pass
        assert calls == expected
        assert job.result.images is None and job.result.warnings == ()


def test_ac_f03_29_a_failing_speaker_check_still_runs_later_phases(tmp_path):
    """§7.6: phases 4 and 5 are skipped only when a define failed."""
    calls = []
    job = LaunchJob(load_r2(tmp_path, 'define daichi = "Daichi"', S='daichi "Yo."'))
    job.clean_phases.append(lambda: calls.append(1) or True)
    while not job.step():
        pass
    assert job.result.error_count == 1 and calls == [1]


def test_launch_errors_carry_their_source_line(tmp_path):
    """Launch errors are reported like load errors (F02 §7.10.1–2): the source line of the
    error's own line, rebuilt from the program."""
    result = run_launch(load_r(tmp_path, T="define rate = (1 +⏎[4]1 / 0)"))
    (error,) = result.errors
    assert (error.line, error.source_line) == (12, "1 / 0)")
    group = ScriptErrorGroup(result.errors, result.error_count)
    assert group.format().endswith("define rate couldn't be set: this divides by zero. Check "
                                   "the number you divide by first, e.g. if days > 0:.\n"
                                   "    1 / 0)")


# --- AC-F03-30 — the define helper that uses story variables and dice -------------------------

def test_ac_f03_30_a_helper_runs_once_the_game_has_started(tmp_path):
    program = load_r(tmp_path, S="$ x = bonus()",
                     T="define bonus = lambda: trust * 2 + dice.roll(0, 0)")
    interp = start(program)
    advance(interp)                                         # past "Start.", runs line 8
    assert interp.G["x"] == 0


# --- §7.6 rule order: Character arguments before E85l (07 G4) ----------------------------------

@pytest.mark.parametrize("R1, code", [
    ("define hana = Character(hana_name)", "E75e"),          # a default, written bare
    ('define hana = Character(name_from=hana_name, color="#e8a0b4")', "E75g"),
    ('define hana = Character(name_from=trust)', "E75g"),
], ids=["name-is-a-default", "name_from-default", "name_from-other-default"])
def test_character_arguments_come_before_e85l(tmp_path, R1, code):
    program = load_files(tmp_path, {"main.vns": template_r(replace={1: R1})})
    (error,) = run_launch(program).errors
    assert (error.code, error.line) == (code, 1)


def test_a_bare_name_elsewhere_in_the_define_is_e85l(tmp_path):
    result = run_launch(load_r(tmp_path, T='define c = Character("A" if trust else "B")'))
    assert [e.code for e in result.errors] == ["E85l"]


def test_a_name_no_line_sets_is_e85b(tmp_path):
    result = run_launch(load_r(tmp_path, T="define c = Character(Nobody)⏎define d = nobody2"))
    assert [e.code for e in result.errors] == ["E75e", "E85b"]
    assert result.errors[1].message == ("define d couldn't be set: there is no variable named "
                                        '"nobody2". Check the spelling, or add a default for '
                                        "it at the top level, e.g. default nobody2 = 0.")


def test_e85l_names_the_first_dollar_line_in_reading_order(tmp_path):
    main = template_r(S="call side", T="define bonus = luck2 * 2⏎include \"side.vns\"")
    program = load_files(tmp_path, {
        "main.vns": main, "side.vns": "label side:\n    $ luck2 = 3\n    return\n"})
    (error,) = run_launch(program).errors
    assert error.code == "E85l"
    assert "set by a $ line (script/side.vns, line 2)" in error.message

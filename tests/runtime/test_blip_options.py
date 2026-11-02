"""F06 step 1 — the blip options of ``Character`` and ``Say.blip``.

ACs: AC-F06-01 (the ``cases.toml`` rows with ``feature = "F06"``, each played as a define
and as a ``$`` line, with the same text), AC-F06-02 (``Say.blip``; the windowed half is
F05's AC-F05-43 run over the example game, which gets blips in F06 step 3), AC-F06-11
(W21 for a ``define``d character's missing blip file).
"""

from dataclasses import replace

from engine.runtime.audio_check import AudioFiles
from engine.runtime.commands import BlipSpec, Say, StoryFailed
from engine.runtime.headless import run_headless
from engine.runtime.launch import run_launch
from tests.runtime.story import load_files
from tests.script import message_cases

CASES = [c for c in message_cases.load_cases() if c.feature == "F06"]


def _outcome(errors) -> message_cases.Outcome:
    return message_cases.Outcome(list(errors), (), len(errors), False)


def test_ac_f06_01_cases(tmp_path):
    """Each row's define (launch, line 9), then ``$ Character(…)`` on line 7 (run)."""
    assert CASES
    for case in CASES:
        as_line = replace(case, edit={"D": case.edit["T"].replace("define t =", "$", 1)},
                          where="-" if case.where == "-" else "7")
        program = load_files(tmp_path / case.id / "a",
                             {"main.vns": message_cases.main_text(case)})
        message_cases.check_case(case, _outcome(run_launch(program).errors))
        program = load_files(tmp_path / case.id / "b",
                             {"main.vns": message_cases.main_text(as_line)})
        failed = [c.error for c in run_headless(program, seed=42) if type(c) is StoryFailed]
        message_cases.check_case(as_line, _outcome(failed))


def test_ac_f06_02_say_blip_is_the_speakers(tmp_path):
    program = load_files(tmp_path, {"main.vns": (
        'define hana = Character("Hana", blip="blips/hana.ogg")\n'
        'define daichi = Character("Daichi", blip="low.wav", blip_every=3, blip_pitch=0.1, '
        "blip_volume=70)\n"
        'define plain = Character("Plain")\n'
        "label start:\n"
        '    hana "A."\n'
        '    daichi "B."\n'
        '    plain "C."\n'
        '    "D."\n')})
    blips = [c.blip for c in run_headless(program, seed=42) if type(c) is Say]
    assert blips == [BlipSpec("blips/hana.ogg", 2, 0.0, 100), BlipSpec("low.wav", 3, 0.1, 70),
                     None, None]


def test_ac_f06_11_missing_blip_file_is_w21_at_its_define(tmp_path):
    program = load_files(tmp_path, {"main.vns": (
        'define hana = Character("Hana", blip="blips/hanna.ogg")\n'
        "define again = hana\n"                         # the same character: no second W21
        "label start:\n"
        '    hana "A."\n')})
    def warnings(*files):
        return run_launch(program, audio=AudioFiles.from_files(files)).warnings

    (w21,) = warnings("audio/blips/hana.ogg")
    assert (w21.code, w21.file, w21.line) == ("W21", "script/main.vns", 1)
    assert w21.message.endswith('Did you mean "blips/hana.ogg"?')
    assert warnings("audio/blips/hanna.ogg") == ()
    assert run_launch(program).warnings == ()           # headless: no audio check

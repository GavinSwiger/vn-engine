"""The F03 launch and run rows of ``tests/fixtures/F02/messages/cases.toml`` (06 §0.4, §4):
each row writes template R with its edit, loads it clean, plays it with
``run_headless(seed=42)``, and checks the error at ``where`` with its exact text (or the
"contains"/"starts" forms where G10 leaves the text open). Load rows run in
``tests/script/test_messages.py``.

ACs (message tables): AC-F03-16, 19, 20, 21, 26, 27, 40, 45, 47 (step 7); 30, 32, 33, 35,
36, 38, 46 (step 8); the E45 and E45b texts of 11 and 12 (step 10). AC-F03-51 (step 11):
the ten mistakes of ``tests/fixtures/F03/seeded/``, each with its code, file, and line, and
the same message shape. Every message also has
AC-F02-38's shape (line form, no banned word or exception class name, no path; G8, G9:
lower case, or ``Character`` as the author writes it; E45b starts with its count, ``1,000
calls``) and no ``(set at`` clause (G11). A launch row "launch fails with" (06 §0.5): the
launch has no namespace, and ``run_headless`` returns exactly one ``StoryFailed`` holding
the group.
"""

import re
import tempfile
from pathlib import Path

import pytest

from engine.runtime.commands import Say, StoryFailed
from engine.runtime.headless import run_headless
from engine.runtime.launch import run_launch
from engine.script.diagnostics import ScriptErrorGroup
from engine.script.messages import TEMPLATES
from tests.fakes.banned_words import BANNED_ANY, BANNED_CASED
from tests.runtime.story import load_files
from tests.script import message_cases
from tests.script.message_cases import Outcome

CASES = [c for c in message_cases.load_cases() if c.feature == "F03" and c.time != "load"]
RUN_CODES = ("E85", "E85b", "E85c", "E85d", "E85e", "E85f", "E85g", "E85i", "E85j",
             "E85n", "E75h", "E45", "E45b")            # E85h retired by F12 (AC-F03-26)
LAUNCH_CODES = ("E75", "E75b", "E75c", "E75d", "E75e", "E75f", "E75g", "E85k", "E85l", "E89",
                "E89b", "E89c")

_LINE_RE = re.compile(r"^script/\S.*\.vns, line [1-9][0-9]*: ([a-z\"]|[1-9][0-9,]* |Character )")
_PATH_RE = re.compile(r"[A-Za-z]:[\\/]|\\\\|\.py\b|File \"")


def play(case) -> tuple[list, Outcome]:
    """The commands of the case's run, and its errors as an ``Outcome``."""
    with tempfile.TemporaryDirectory() as tmp:
        text = message_cases.main_text(case)
        assert isinstance(text, str)
        program = load_files(Path(tmp), {"main.vns": text})
        commands = run_headless(program, seed=42)
        if case.time == "launch":
            launch = run_launch(program)
            assert (launch.namespace is None) == (case.code != "-")
    failed = [c for c in commands if type(c) is StoryFailed]
    if not failed:
        return commands, Outcome([], (), 0, False)
    error = failed[-1].error
    if isinstance(error, ScriptErrorGroup):
        return commands, Outcome(list(error.errors), (), error.total, False)
    return commands, Outcome([error], (), 1, False)


def test_rows_cover_every_run_and_launch_code():
    assert {c.code for c in CASES if c.time == "run"} >= set(RUN_CODES)
    assert {c.code for c in CASES if c.time == "launch"} >= set(LAUNCH_CODES)
    assert all(code in TEMPLATES for code in RUN_CODES + LAUNCH_CODES + ("E85m",))
    assert {c.ac for c in CASES} >= {f"AC-F03-{n}" for n in
                                      ("16", "19", "20", "21", "27", "40", "45", "47",
                                       "30", "32", "33", "35", "36", "38", "46",
                                       "11", "12")}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_case(case):
    commands, outcome = play(case)
    message_cases.check_case(case, outcome)
    if case.code == "-":
        assert not [c for c in commands if type(c) is StoryFailed]
        return
    # "Fails with X at N" (06 §0.5): StoryFailed is the last command and nothing follows.
    assert type(commands[-1]) is StoryFailed
    assert [type(c) for c in commands].count(StoryFailed) == 1
    error = commands[-1].error
    if case.time == "launch":
        assert len(commands) == 1 and type(error) is ScriptErrorGroup
        (error,) = error.errors
    text = error.format()
    assert _LINE_RE.match(text), text
    assert "(set at" not in text                                        # G11
    assert not BANNED_CASED.search(text) and not BANNED_ANY.search(text), text
    assert not set(re.findall(r"\w+", text)) & message_cases_exceptions(), text
    assert not _PATH_RE.search(text), text
    assert "\n" not in text and "Traceback" not in text
    if case.time == "run" and case.where.isdigit() and int(case.where) == 11:
        assert not [c for c in commands if type(c) is Say]              # a failing default


def message_cases_exceptions() -> set[str]:
    import builtins
    return {name for name, value in vars(builtins).items()
            if isinstance(value, type) and issubclass(value, BaseException)}


# --- AC-F03-51: the ten seeded mistakes (06 §5.3 ``seeded/``) ----------------------------------

SEEDED = Path(__file__).resolve().parents[1] / "fixtures" / "F03" / "seeded"
SEEDED_ERRORS = {
    # folder: (code, file, line, a part of the message that tells the variant)
    "misspelled_variable": ("E85b", "script/main.vns", 4, 'Did you mean "trust"?'),
    "used_before_set": ("E85b", "script/ch3.vns", 3,
                        "yet. It is set by a $ line (script/ch3.vns, line 7)"),
    "assign_define": ("E87", "script/main.vns", 4, "is set by define"),
    "unsaveable_value": ("E85e", "script/main.vns", 3, "holds a set"),
    "speaker_not_character": ("E75", "script/main.vns", 1, "not a character"),
    "bad_character_option": ("E75b", "script/main.vns", 1, 'Did you mean "color"?'),
    "endless_jump_loop": ("E45", "script/main.vns", 7, '"shop" and "street"'),
    "runaway_call": ("E45b", "script/main.vns", 7, 'called label "chat"'),
    "text_plus_number": ("E85d", "script/main.vns", 4, "adds text and a whole number"),
    "divide_by_zero": ("E85g", "script/main.vns", 5, "divides by zero"),
}


def seeded_error(root: Path, name: str):
    """The one error of a seeded folder: from the load, else from the headless run (a launch
    error comes as a group holding one error)."""
    import shutil

    from engine.core.paths import GamePaths
    from engine.script import load_story

    shutil.copytree(SEEDED / name, root / "script")
    result = load_story(GamePaths(root.resolve()))
    if result.program is None:
        assert len(result.errors) == 1, [e.format() for e in result.errors]
        return result.errors[0]
    commands = run_headless(result.program, seed=42)
    assert type(commands[-1]) is StoryFailed
    error = commands[-1].error
    if isinstance(error, ScriptErrorGroup):
        assert len(error.errors) == 1, error.format()
        (error,) = error.errors
    return error


def test_ac51_the_seeded_folders_are_the_ten_mistakes():
    assert sorted(p.name for p in SEEDED.iterdir()) == sorted(SEEDED_ERRORS)


@pytest.mark.parametrize("name", sorted(SEEDED_ERRORS))
def test_ac51_seeded_mistakes(tmp_path, name):
    code, file, line, part = SEEDED_ERRORS[name]
    error = seeded_error(tmp_path, name)
    assert (error.code, error.file, error.line) == (code, file, line), error.format()
    text = error.format()
    assert part in text, text
    assert _LINE_RE.match(text), text
    assert not BANNED_CASED.search(text) and not BANNED_ANY.search(text), text
    assert not set(re.findall(r"\w+", text)) & message_cases_exceptions(), text
    assert not _PATH_RE.search(text), text
    assert not re.search(r"[\x00-\x1f\x7f-\x9f]", text), text
    assert not any(row.startswith("Traceback") for row in text.splitlines())

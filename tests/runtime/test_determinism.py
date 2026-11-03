"""F03 step 14 — determinism (``06-acceptance.md`` §1.10, §5.6; TR-F03-02, TR-F03-06).

ACs: AC-F03-66 (slicing never changes the story: the app driver with a fake clock and
``RUN_CHUNK_STEPS`` 1, 64, and unlimited, against ``run_headless``) and AC-F03-67 (the same
seed gives byte-identical canonical JSON under ``PYTHONHASHSEED`` 0, 1, and ``random``,
equal to the committed goldens in ``tests/fixtures/F03/goldens/`` and ``dice_golden.json``).
Also the committed v1 saves of AC-F03-65 (``goldens/patch_v1_saves.json``), so a change to
the identity scheme or the save shape fails here, not only in a test that makes its saves
with the same code it checks.

Tiers (test-review-F03.md): the default run plays the example game and the corpus's small
parts (``flow/``, ``vars/``, ``lanterns/``), which together use every statement kind the
realistic part does, and checks them against their entries in the goldens. The realistic
part (about 4,400 lines) runs in ``slow``: AC-F03-66 through the driver, and AC-F03-67's
whole-corpus subprocesses, which compare the golden files byte for byte.

Goldens are committed at the first green run on Windows and must not change. When a change
to the example game, the corpus generator, or a command's fields is meant to change them,
rewrite them with ``python -m tests.runtime.corpus --write-goldens --work <empty folder>``
and say so in the review.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine.app import story as app_story
from engine.app.story import RuntimeStoryDriver
from engine.runtime import limits
from engine.runtime.commands import (Advance, Choose, MinigameDone, Say, ShowMenu,
                                     StartMinigame, StoryWait, WaitDone)
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.minigame import headless_outcome
from engine.runtime.state import GameState
from engine.runtime.values import same_value
from tests.runtime import corpus
from tests.runtime.story import checkpoints, launched, load_fixture, start, texts

REPO = Path(__file__).resolve().parents[2]
SEED = 7


# --- AC-F03-66 — slicing never changes the story ----------------------------------------------

class StepClock:
    """A fake clock: every read moves ``step`` seconds."""

    def __init__(self, step: float) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def answer(driver: RuntimeStoryDriver, cmd) -> bool:
    """Answer a line with ``Advance`` and a menu (F07, the example game) with its first
    unlocked choice, as Space does in the window; True when ``cmd`` was a line. A story wait
    (F09, F18) ends at once, as headless ends it, and a minigame (F24-4: the example's poem)
    with its test outcome, as headless with no ``finish``."""
    if isinstance(cmd, StoryWait):                     # F30's FakeCrash is one too
        driver.post(WaitDone(cmd.wait_id))
        return False
    if type(cmd) is StartMinigame:
        outcome = headless_outcome(driver.interp, driver.interp.current)
        assert outcome is not None, cmd
        driver.post(MinigameDone(cmd.sid, cmd.run, outcome.result, outcome.changes))
        return False
    if type(cmd) is Say:
        driver.post(Advance(cmd.sid))
        return True
    if type(cmd) is ShowMenu:
        driver.post(Choose(cmd.sid, next(c.key for c in cmd.choices if not c.locked)))
    return False


def drive(program, images, *, chunk: int, clock, monkeypatch) -> list:
    """Play through ``RuntimeStoryDriver`` frame by frame, answering every line (and menu)."""
    monkeypatch.setattr(app_story, "RUN_CHUNK_STEPS", chunk)
    driver = RuntimeStoryDriver(corpus.launched(program, images), clock=clock, fixed_seed=SEED)
    driver.new_game()
    out: list = []
    for _ in range(1_000_000):
        cmds = driver.pump()
        out.extend(cmds)
        for cmd in cmds:
            answer(driver, cmd)
        if driver.status in (Status.ENDED, Status.FAILED) and not cmds:
            return out
    raise AssertionError("the story did not end")


def check_slicing(name, program, images, monkeypatch) -> None:
    # chunk 1 and 64 with a slice that ends after every chunk (the most cuts), and an
    # unlimited slice (a deadline that never passes: the clock stands still).
    configs = [(1, StepClock(limits.RUN_SLICE_S)), (64, StepClock(limits.RUN_SLICE_S)),
               (64, StepClock(0.0))]
    inputs = corpus.play(program, SEED, images).inputs           # F07: the first choices
    expected = run_headless(program, seed=SEED, image_files=images, inputs=inputs,
                            minigames=corpus.example_minigames())
    assert type(expected[-1]).__name__ == "StoryEnded", name
    for chunk, clock in configs:
        got = drive(program, images, chunk=chunk, clock=clock, monkeypatch=monkeypatch)
        assert got == expected, (name, chunk, clock.step)


def test_ac_f03_66_slicing_never_changes_the_story(small_parts, monkeypatch):
    """The example game and the corpus's small parts (the realistic part: ``slow``)."""
    check_slicing("example", corpus.example_program(), corpus.example_images(), monkeypatch)
    for name, program in small_parts.items():
        check_slicing(name, program, (), monkeypatch)


@pytest.mark.slow
def test_ac_f03_66_slicing_never_changes_the_realistic_corpus(realistic_part, monkeypatch):
    check_slicing("realistic", realistic_part, (), monkeypatch)


def test_slicing_really_cuts_the_story(monkeypatch):
    """The chunk-1 run of the example gives the driver back control between steps: more
    pumps than lines, or AC-F03-66 would compare the same run three times."""
    monkeypatch.setattr(app_story, "RUN_CHUNK_STEPS", 1)
    program, images = corpus.example_program(), corpus.example_images()
    driver = RuntimeStoryDriver(corpus.launched(program, images),
                                clock=StepClock(limits.RUN_SLICE_S), fixed_seed=SEED)
    driver.new_game()
    pumps = lines = empty = 0
    while driver.status not in (Status.ENDED, Status.FAILED):
        cmds = driver.pump()
        pumps += 1
        empty += not cmds
        for cmd in cmds:
            lines += answer(driver, cmd)
    assert empty > lines > 0


# --- AC-F03-67 — same seed, same story, on every OS --------------------------------------------

HASH_SEEDS = ("0", "1", "random")


def _documents(tmp_path: Path, *, small: bool) -> list[dict[str, str]]:
    """``python -m tests.runtime.corpus`` under each of ``HASH_SEEDS``, the three processes
    at once; their documents, in that order."""
    runs = []
    for hash_seed in HASH_SEEDS:
        out = tmp_path / f"docs-{hash_seed}.json"
        args = [sys.executable, "-m", "tests.runtime.corpus",
                "--work", str(tmp_path / f"work-{hash_seed}"), "--out", str(out)]
        env = dict(os.environ, PYTHONHASHSEED=hash_seed)
        runs.append((out, subprocess.Popen([*args, *(["--small"] if small else [])], cwd=REPO,
                                           env=env, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True)))
    docs = []
    for out, child in runs:
        _, err = child.communicate(timeout=240)
        assert child.returncode == 0, err[-3000:]
        docs.append(json.loads(out.read_text(encoding="ascii")))
    return docs


def _golden(name: str) -> str:
    golden = corpus.GOLDENS / name
    assert golden.is_file(), f"commit tests/fixtures/F03/goldens/{name} (§5.6)"
    return golden.read_bytes().decode("ascii")


def _check_dice(docs: dict[str, str]) -> None:
    """AC-F03-41's call script; also TR-F03-06's dice half (test_dice.py has no subprocess
    of its own)."""
    committed = json.loads((corpus.FIXTURES / "dice_golden.json").read_text(encoding="utf-8"))
    assert corpus.dumps(committed) == docs["dice_golden.json"]


def test_ac_f03_67_same_seed_same_story_under_any_hash_seed(tmp_path):
    """The example game, the corpus's small parts, and the dice call script, each hash seed
    in its own process: equal to each other and to the goldens (the small parts' entries of
    ``commands_corpus.json``). The whole golden files: ``slow``, below."""
    runs = _documents(tmp_path, small=True)
    assert runs[0] == runs[1] == runs[2]
    docs = runs[0]
    assert docs["commands_example.json"] == _golden("commands_example.json")
    whole = _golden("commands_corpus.json")
    golden = json.loads(whole)
    assert corpus.dumps(golden) == whole              # so a slice of it compares byte for byte
    assert docs["commands_corpus.json"] == corpus.dumps({k: golden[k] for k in corpus.SMALL})
    _check_dice(docs)


@pytest.mark.slow
def test_ac_f03_67_the_whole_corpus_under_any_hash_seed(tmp_path):
    runs = _documents(tmp_path, small=False)
    assert runs[0] == runs[1] == runs[2]
    docs = runs[0]
    for name in ("commands_example.json", "commands_corpus.json"):
        assert docs[name] == _golden(name), name
    _check_dice(docs)


def test_goldens_cover_what_they_should():
    example = json.loads(corpus.GOLDENS.joinpath("commands_example.json").read_text("ascii"))
    assert sorted(example["seeds"]) == [str(s) for s in corpus.EXAMPLE_SEEDS]
    for run in example["seeds"].values():
        assert run["commands"][-1] == {"type": "StoryEnded"}
        assert run["final"]["status"] == "ENDED"
    fortunes = {run["final"]["variables"]["fortune"] for run in example["seeds"].values()}
    assert len(fortunes) >= 2                     # the seeds take different dice branches
    whole = json.loads(corpus.GOLDENS.joinpath("commands_corpus.json").read_text("ascii"))
    assert sorted(whole) == ["flow", "lanterns", "realistic", "vars"]
    assert whole["realistic"]["commands"]["count"] > 4000
    assert all(part["final"]["status"] == "ENDED" for part in whole.values())


# --- AC-F03-65 — committed v1 saves still load after a patch -----------------------------------

V1_SAVES = corpus.GOLDENS / "patch_v1_saves.json"


def _v1_saves(tmp_path: Path) -> list[str]:
    v1 = load_fixture(tmp_path / "v1", "patch/v1")
    return [json.dumps(s.to_json(), ensure_ascii=True, sort_keys=True)
            for s in checkpoints(start(v1))]


def test_ac_f03_65_v1_saves_are_the_committed_ones(tmp_path):
    """The saves today's engine makes from ``patch/v1/`` hold the committed ones: the same
    identities, positions, call stacks, variables, and dice. A later feature may add a key
    with a default (``07`` §2.6: ``format`` stays 1), so only the committed keys are
    compared."""
    committed = json.loads(V1_SAVES.read_text(encoding="ascii"))
    assert len(committed) == 5
    today = [json.loads(text) for text in _v1_saves(tmp_path)]
    assert len(today) == 5
    for old, new in zip(committed, today):
        assert {key: new.get(key) for key in old} == old


def test_ac_f03_65_committed_v1_saves_load_into_v2(tmp_path):
    committed = json.loads(V1_SAVES.read_text(encoding="ascii"))
    v2 = load_fixture(tmp_path / "v2", "patch/v2")
    for data in committed:
        interp = launched(v2)
        assert interp.restore(GameState.from_json(data)).result is RestoreResult.OK
        for name, value in {"gift": "lantern", "petals": 3, "luck": 0.5}.items():
            assert same_value(interp.G[name], value)
        commands = interp.take_commands(1 << 30)
        while interp.status is Status.WAITING:
            interp.post(Advance(interp.current.sid))
            interp.run(10_000)
            commands += interp.take_commands(1 << 30)
        assert texts(commands)[-1] == "Six." and interp.status is Status.ENDED


if __name__ == "__main__":                       # write patch_v1_saves.json once
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        saves = [json.loads(text) for text in _v1_saves(Path(tmp))]
    V1_SAVES.write_text(json.dumps(saves, ensure_ascii=True, sort_keys=True, indent=1) + "\n",
                        encoding="ascii", newline="\n")

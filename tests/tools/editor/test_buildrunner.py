"""F42 P6: Studio's build models (``buildmodel``, ``buildrunner``) with a fake build child.

AC-F42-19's Studio half (``07`` I-7): after Cancel, only this build's staging folder is
deleted, and only after the build's processes exited."""

import json
import os
import threading
import time
from pathlib import Path

import pytest

from engine.core.editorreport import REPORT_MARKER
from engine.tools.build import texts, tree
from engine.tools.editor import buildmodel, buildrunner
from engine.tools.editor.buildrunner import BuildState
from tests.core.test_safefile import link_dir

FOLDER = "Paper Lanterns 0.1.0 Windows"


def line(event: str, **fields) -> bytes:
    data = {"v": 1, "event": event, **fields}
    return REPORT_MARKER + json.dumps(data, separators=(",", ":")).encode("ascii") + b"\n"


class PipeProc:
    """A fake build child whose stdout stays open until it is killed or ends."""

    pid = 777

    def __init__(self) -> None:
        r, self._w = os.pipe()
        self.stdout = os.fdopen(r, "rb")
        self.returncode = None
        self.argv = None

    def write(self, data: bytes) -> None:
        os.write(self._w, data)

    def end(self, code: int) -> None:
        if self.returncode is None:
            self.returncode = code
            os.close(self._w)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


def until(runner, predicate, timeout=5.0):
    events = []
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        events += runner.poll()
        if predicate(events):
            return events
        time.sleep(0.01)
    raise AssertionError(events)


def staging_with_marker(save_to: Path, name: str) -> Path:
    path = save_to / name
    path.mkdir()
    (path / tree.STAGING_MARKER).write_bytes(tree.STAGING_MARKER_BYTES)
    (path / "b").mkdir()
    (path / "b" / "partial.bin").write_bytes(b"x")
    return path


def test_ac_f42_19_cancel_removes_only_its_staging_after_the_tree_exited(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    save_to = tmp_path / "builds"
    save_to.mkdir()
    own = staging_with_marker(save_to, f".{FOLDER}.building-0123abcd")
    other = staging_with_marker(save_to, ".Other 1 Windows.building-0123abcd")
    unmarked = save_to / f".{FOLDER}.building-feedbeef"
    unmarked.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / tree.STAGING_MARKER).write_bytes(b"x")
    link_dir(save_to / f".{FOLDER}.building-0000aaaa", outside)

    # The checks, one by one: bare STAGING_RE name for this folder, a real folder directly
    # in Studio's own Save to, holding the marker.
    assert buildrunner.cancel_target(save_to, FOLDER, own.name) == own
    for bad in (other.name, unmarked.name, f".{FOLDER}.building-0000aaaa",
                f"../builds/{own.name}", str(own), None, "", f"{own.name}/b"):
        assert buildrunner.cancel_target(save_to, FOLDER, bad) is None, bad

    proc = PipeProc()
    order = []

    def kill_tree(p):
        order.append(("kill", p.poll()))
        p.end(1)

    def remove_tree(path):
        order.append(("remove", proc.poll(), path))
        return tree.remove_tree(path)

    def popen(argv, **kwargs):
        proc.argv = argv
        return proc

    runner = buildrunner.BuildRunner(game, popen=popen, kill_tree=kill_tree,
                                     remove_tree=remove_tree)
    assert [e.state for e in runner.start(save_to, FOLDER, zip=True, replace=False)] == \
        [BuildState.STARTED]
    assert proc.argv[-4:] == ["--out", str(save_to), "--zip", "--report-to-editor"]
    proc.write(line("build_step", i=1, m=6, key="check", files=None, bytes=None,
                    staging=None))
    proc.write(line("build_step", i=2, m=6, key="copy", files=3, bytes=10, staging=own.name))
    until(runner, lambda ev: any(e.step and e.step.key == "copy" for e in ev))
    runner.cancel()
    assert runner.stopping and runner.running
    events = until(runner, lambda ev: any(e.state is BuildState.CANCELLED for e in ev))
    assert events[-1].left is None and not runner.running and not runner.stopping
    assert order == [("kill", None), ("remove", 1, own)]            # removed after exit
    assert not own.exists()
    assert other.exists() and unmarked.exists() and (outside / tree.STAGING_MARKER).exists()
    assert buildmodel.cancelled_text(save_to) == \
        "Build stopped. Nothing in builds was changed."

    # A staging name that isn't this build's is never deleted, even when the event says so.
    proc2 = PipeProc()
    runner = buildrunner.BuildRunner(game, popen=lambda argv, **kw: proc2,
                                     kill_tree=lambda p: p.end(1), remove_tree=remove_tree)
    runner.start(save_to, FOLDER, zip=False, replace=False)
    proc2.write(line("build_step", i=2, m=5, key="copy", files=1, bytes=1,
                     staging=other.name))
    until(runner, lambda ev: any(e.state is BuildState.STEP for e in ev))
    order.clear()
    runner.cancel()
    until(runner, lambda ev: any(e.state is BuildState.CANCELLED for e in ev))
    assert order == [] and other.exists()


def test_build_runner_steps_check_and_done(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    proc = PipeProc()
    clock = [100.0]
    runner = buildrunner.BuildRunner(game, popen=lambda argv, **kw: proc,
                                     clock=lambda: clock[0])
    runner.start(tmp_path / "builds", FOLDER, zip=False, replace=True, serial=7)
    progress = runner.progress
    assert progress.counter_text() == "Step 1 of 5" and progress.fraction == 0
    item = {"severity": "warning", "code": "W1", "source": "load", "text": "unused",
            "file": "script/a.vns", "line": 2, "column": None}
    proc.write(line("build_step", i=1, m=5, key="check", files=None, bytes=None,
                    staging=None))
    proc.write(line("problems", items=[item]))
    proc.write(line("done", loaded=True, problems=1, seconds=0.5))
    proc.write(b"stray output\n")
    proc.write(line("build_step", i=3, m=5, key="pack", files=None, bytes=None,
                    staging=None))
    events = until(runner, lambda ev: sum(e.state is BuildState.STEP for e in ev) == 2)
    check = next(e.check for e in events if e.state is BuildState.CHECK)
    assert check.serial == 7 and [p.text for p in check.problems] == ["unused"]
    clock[0] = 141.0
    assert progress.counter_text() == "Step 3 of 5" and progress.slow
    assert progress.elapsed_text(clock[0]) == "0:41" and progress.fraction == 2 / 5
    assert [r.status for r in progress.rows()] == ["done", "done", "running", "waiting",
                                                    "waiting"]
    proc.write(line("build_done", folder=FOLDER, exe="Paper Lanterns.exe", files=1214,
                    bytes=96 << 20, zip=None, zip_bytes=None, warnings=2,
                    left_out=[["saves", "test-run data from your PC; players get their own"]],
                    left_out_total=3, long_paths=0, long_path_example=None))
    proc.end(0)
    events = until(runner, lambda ev: not runner.running)
    done = next(e.done for e in events if e.state is BuildState.DONE)
    shown = buildmodel.finished_texts(done)
    assert shown.folder_line == f"{FOLDER} — 96 MB, 1,214 files" and shown.zip_line is None
    assert shown.share == (f"Send players the whole {FOLDER} folder. "
                           "They open Paper Lanterns.exe inside it.")
    assert shown.warnings == "Built with 2 warnings. They're listed in Problems."
    assert shown.left_out == "3 files were left out."
    assert progress.fraction == 1 and progress.elapsed_text(clock[0]) == ""

    # A failure and a crash.
    proc = PipeProc()
    runner = buildrunner.BuildRunner(game, popen=lambda argv, **kw: proc)
    runner.start(tmp_path / "builds", FOLDER, zip=True, replace=False)
    proc.write(line("build_failed", code="B_ERRORS", values={"n": 1}, details=[]))
    proc.end(1)
    events = until(runner, lambda ev: not runner.running)
    failure = next(e.failure for e in events if e.state is BuildState.FAILED)
    assert failure.texts() == ("Your game has 1 error, so it can't be built yet.",
                               "They're listed in Problems. Fix them and build again.", ())
    proc = PipeProc()
    runner = buildrunner.BuildRunner(game, popen=lambda argv, **kw: proc)
    runner.start(tmp_path / "builds", FOLDER, zip=True, replace=False)
    proc.write(REPORT_MARKER + b'{"v":1,"event":"build_failed","code":"B_NOPE"}\n')
    proc.end(1)
    events = until(runner, lambda ev: not runner.running)
    assert [e.state for e in events] == [BuildState.CRASHED] and events[0].exit_code == 1


def test_build_model_fields_plan_and_replace(tmp_path):
    game = tmp_path / "Lanterns"
    game.mkdir()
    text = ('# My game\n[game]\ntitle = "Paper Lanterns"\nversion = "0.1.0"\n'
            '# id = "x"\n\n[window]\nwidth = 1280')
    fields = buildmodel.initial_fields(text, game)
    assert fields == buildmodel.BuildFields("Paper Lanterns", "0.1.0", "", None,
                                            str(tmp_path / "builds"), True)
    problems = buildmodel.field_messages(fields, game)
    assert problems == {"id": texts.FIELD_MESSAGES["NO_ID"]}
    assert buildmodel.use_slug_text(fields.title) == "Use paper-lanterns"
    assert buildmodel.makes_hint(fields) == f"Makes: {FOLDER}"
    assert buildmodel.name_hint(fields) == "Shown on the window. Game file: Paper Lanterns.exe"

    (game / "gui").mkdir()
    (game / "gui" / "tiny.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x08\x00\x00\x00\x08\x08\x06\x00\x00\x00")
    bad = buildmodel.BuildFields("Paper Lanterns", "0.1.0", "paper-lanterns", "gui/tiny.png",
                                 str(game / "out"), True)
    assert set(buildmodel.field_messages(bad, game)) == {"icon", "save_to"}
    assert buildmodel.field_messages(bad, game)["save_to"] == \
        "The build can't be saved inside the game folder."

    wanted = buildmodel.BuildFields('Lan"terns', "0.2.0", "paper-lanterns", None,
                                    str(tmp_path / "builds"), True)
    plan = buildmodel.config_plan(text, wanted)
    assert plan.verify({"config.toml": text})
    assert not plan.verify({"config.toml": text.replace("0.1.0", "0.1.1")})
    assert plan.plan.title == buildmodel.PLAN_TITLE and len(plan.plan.files[0].edits) == 1
    assert [c[:2] for c in plan.changed] == [("game", "title"), ("game", "version"),
                                             ("game", "id")]
    new = plan.new_text(text)
    assert new == ('# My game\n[game]\ntitle = "Lan\\"terns"\nversion = "0.2.0"\n'
                        'id = "paper-lanterns"\n\n[window]\nwidth = 1280')
    assert buildmodel.config_plan(new, wanted) is None
    assert buildmodel.id_changed_text("old-id", "paper-lanterns") == (
        "You changed the Game ID from old-id to paper-lanterns. Players of your earlier "
        "build won't see their saves in this one.")

    save_to = tmp_path / "builds"
    (save_to / FOLDER / "_internal").mkdir(parents=True)
    assert buildmodel.replace_question(save_to, FOLDER, with_zip=True) is None   # not a build
    (save_to / FOLDER / "_internal" / "vn-build.json").write_bytes(tree.marker_bytes(
        engine="0.1.0", app_id="paper-lanterns", version="0.1.0", built="2026"))
    assert buildmodel.replace_question(save_to, FOLDER, with_zip=False) == \
        f'Replace the earlier build "{FOLDER}"? The old folder will be deleted.'
    assert buildmodel.open_targets(save_to, FOLDER, "Paper Lanterns.exe") == \
        (save_to / FOLDER, save_to / FOLDER / "Paper Lanterns.exe")
    argv = buildmodel.build_argv(game, save_to, zip=True, replace=True)
    assert argv[1:5] == ["-E", "-B", "-m", "engine"] and argv[-3:] == [
        "--zip", "--replace", "--report-to-editor"]

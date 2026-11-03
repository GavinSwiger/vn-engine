"""F47 P2-F: Try it (``01-design.md`` PR-F47-20; ``04-technical.md`` §7.5; AC-F47-30).

AC-F47-30: Try it runs the line in a game window over the row's stage and writes nothing to
the game folder. The Studio half runs with a fake runner (the argv and stdin it would send,
and a failure shown under the button); the game half is one real ``run --try-stdin`` child
under SDL's dummy drivers that plays a dissolve and exits 0, leaving the game folder as it
was."""

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine.app import cli, trystory
from engine.tools.editor import files, forms, stageat, trywiring
from engine.tools.editor.preview import PreviewEvent, PreviewState, editor_report

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import apply_check, open_database  # noqa: E402
from tests.tools.editor.test_studio_database_p2 import button  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

REPO = Path(__file__).resolve().parents[3]
MAIN_REF = "script/main.vns"


class FakeRunner:
    """Stands in for ``trywiring.TryRunner``: records each play; ``poll`` hands out queued
    events."""

    def __init__(self) -> None:
        self.played: list[tuple[list[str], bytes]] = []
        self.queued: list[PreviewEvent] = []

    def play(self, argv, data: bytes) -> None:
        self.played.append((list(argv), data))

    def poll(self) -> list[PreviewEvent]:
        events, self.queued = self.queued, []
        return events

    def stop(self) -> None:
        pass


def snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    """Every file and folder under ``folder`` with its size and modification time."""
    out = {}
    for path in sorted(folder.rglob("*")):
        stat = path.stat()
        out[path.relative_to(folder).as_posix()] = (stat.st_size if path.is_file() else -1,
                                                    stat.st_mtime_ns)
    return out


@pytest.mark.tk
def test_ac_f47_30_try_it_plays_the_line_over_the_rows_stage(studio, tmp_path):  # noqa: F811
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    database = game / "script" / "database.vns"
    database.write_text(database.read_text("utf-8") + "\ndefine slow = Dissolve(1.5)\n",
                        "utf-8")
    ed = studio(game, mapped=True)
    win = ed.win
    apply_check(ed, game)
    fake = FakeRunner()
    win.__dict__["try_it"] = trywiring.TryIt(win, runner=fake)

    # The Database's Transitions: Try it plays the form's values onto the first background.
    db = open_database(ed, "transition")
    db.select("x:slow")
    ed.root.update()
    button(db.form_frame, "Try it").invoke()
    argv, data = fake.played[-1]
    assert argv == [sys.executable, "-m", "engine", "run", str(game), "--report-to-editor",
                    "--try-stdin"]
    assert data.decode() == "scene\nscene bg bridge_night with dissolve 1.5\npause 2\n"
    # A failure shows under the button, without the throwaway label's place.
    fake.queued.append(PreviewEvent(PreviewState.DIDNT_START, editor_report(
        "script/main.vns, line 99: there is no picture called bg nowhere.")))
    win._poll_preview()
    assert db.form.fields["try_note"].cget("text") == \
        "Couldn't try it: there is no picture called bg nowhere."

    # An effect form: Shake over the stage at the selected Events row (two characters up).
    win.story.show(MAIN_REF, "start")
    row = win.story.row_at(23)                  # daichi "Only once. Well, twice."
    win.story.view.select(row, notify=False)
    from engine.tools.editor.formassets import WindowAssets
    from engine.tools.editor.formdialogs import FormDialog
    dialog = FormDialog(ed.root, forms.form_by_key("shake"), {"seconds": "0.5"}, names={},
                        assets=WindowAssets(win))
    assert dialog.try_button is not None
    dialog.try_button.invoke()
    _argv, data = fake.played[-1]
    assert data.decode().split("\n") == [
        "scene bg river_dusk", "show hana happy at left", "show daichi smile at right",
        stageat.STAGE_BEAT, "shake 0.5", "pause 2", ""]
    dialog.dialog.destroy()
    # A form without an effect has no Try it.
    say = FormDialog(ed.root, forms.form_by_key("music"), {}, names={},
                     assets=WindowAssets(win))
    assert say.try_button is None
    say.dialog.destroy()


def test_ac_f47_30_real_try_run_plays_a_dissolve_and_writes_nothing(tmp_path, monkeypatch):
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    before = snapshot(game)
    lines = stageat.transition_entry_lines(
        "slow", {"kind": "dissolve", "seconds": 0.3}, "bg river_dusk")
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    done = subprocess.run([sys.executable, "-m", "engine", "run", str(game),
                           "--report-to-editor", "--try-stdin"],
                          input=trywiring.try_bytes(lines), capture_output=True, cwd=REPO,
                          env=env, timeout=120)
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-2000:]
    assert b'"event":"started"' in done.stdout
    assert snapshot(game) == before             # no logs, saves, settings or persistent

    # Usage errors come before anything loads (exit 2).
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"\n")))
    for argv in (["--try-stdin"], ["--try-stdin", "--start", "start"],
                 ["--try-stdin", "--release"]):
        with pytest.raises(SystemExit) as stop:
            cli.main(["run", str(game), *argv])
        assert stop.value.code == 2
    assert trystory.parse_try_text(b"x" * (trystory.TRY_MAX_BYTES + 1)) == \
        trystory.TRY_TOO_LONG

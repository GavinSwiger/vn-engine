"""F32 step 6: Run ▸ "Preview title as playthrough…" (``06-acceptance.md`` AC-F32-23;
``04`` §6.8, 07 G8). The game runner is faked (``test_studio_playbar.FakeGame``)."""

import shutil
import sys
from pathlib import Path

import pytest

from engine.tools.editor.preview import PreviewState, preview_argv
from engine.tools.editor.runwiring import NO_PLAYTHROUGHS, PLAYTHROUGH_ASK, PLAYTHROUGH_MENU
from tests.tools.editor.test_studio_playbar import fake_game
from tests.tools.editor.test_studio_window import studio  # noqa: F401  (fixture)

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.tk

TEMPLATE = Path(__file__).resolve().parents[2] / "fixtures" / "F32" / "template"


def _game(tmp_path: Path, name: str, extra: str = "", *, tables: bool = True) -> Path:
    game = tmp_path / name
    shutil.copytree(TEMPLATE, game)
    config = game / "config.toml"
    text = config.read_text(encoding="utf-8")
    if not tables:
        text = text[:text.index("[playthrough.2]")]
    config.write_text(text + extra, encoding="utf-8")
    return game


def _run_entry(win) -> None:
    win.run_menu.invoke(win.run_menu.index(PLAYTHROUGH_MENU))


def test_ac_f32_23_preview_title_as_playthrough(studio, tmp_path):
    game = _game(tmp_path, "u", '\n[playthrough.5.words]\nnew_game = "Five"\n')
    ed = studio(game)
    win = ed.win
    runner = fake_game(win)
    ed.answers.append(1)                                    # the chooser: "5"
    _run_entry(win)
    assert ed.dialogs[-1] == ("ask", PLAYTHROUGH_ASK, ("2", "5", "Cancel"), 2, 0)
    assert runner.argvs == [preview_argv(game, None, [], extra=("--playthrough", "5"))]
    assert runner.argvs[0][-2:] == ["--playthrough", "5"]
    assert preview_argv(game, None, []) == [sys.executable, "-m", "engine", "run", str(game),
                                            "--report-to-editor"]
    ed.answers.append(2)                                    # Cancel starts nothing
    _run_entry(win)
    assert len(runner.argvs) == 1

    bare = studio(_game(tmp_path, "bare", tables=False))
    bare_runner = fake_game(bare.win)
    _run_entry(bare.win)
    assert bare.dialogs[-1] == ("info", NO_PLAYTHROUGHS) and bare_runner.argvs == []

    broken = studio(_game(tmp_path, "broken", "\n[playthrough.2.words]\nnew_game = 7\n"))
    broken_runner = fake_game(broken.win)
    shown = len(broken.dialogs)
    _run_entry(broken.win)
    assert len(broken.dialogs) == shown and broken_runner.argvs == []     # no chooser
    assert broken.win.preview_state is PreviewState.DIDNT_START
    view = broken.win._panel_view
    assert view[0] == "report" and any("config.toml" in item.text for item in view[1].items)

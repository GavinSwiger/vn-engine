"""F32 step 6: ``run --playthrough N`` (``06-acceptance.md`` AC-F32-22; ``04`` §6.8).

App A (F12's in-process launch, ``scripted_app``): the CLI parsed and the game started in
this process. The preview reads persistent data as usual, keeps it in memory, and sets
``persistent.playthrough`` to N before the launch look is chosen.
"""

import os

import pytest

from engine.app import cli
from engine.persist.location import FILE_NAME
from engine.persist.sync import MEMORY
from tests.app.test_persistence_app import FESTIVALS, _festivals_file, game_of, once_ready

pytestmark = pytest.mark.display

LOOK_2 = '\n[playthrough.2.words]\nnew_game = "Again?"\n'


@pytest.mark.parametrize("stored", [True, False], ids=["file", "no-file"])
def test_ac_f32_22_run_playthrough_n(tmp_path, user_roots, scripted_app, capsys, stored):
    """``run --playthrough 2`` plays in look 2 with persistent data in memory: the story's
    ``$ persistent.x = 1`` changes neither the file's bytes nor its time, and no file is
    made when there was none. ``--release`` refuses it; 100, -1 and ``two`` are usage
    errors whose line ends with the G7 text."""
    game = game_of(tmp_path, FESTIVALS, config="\n[textbox]\ncps = 0\n" + LOOK_2)
    path = game / "persistent" / FILE_NAME
    if stored:
        data = _festivals_file(game)
        stamp = os.stat(path).st_mtime_ns
    found = {}
    once_ready(scripted_app, lambda app: found.update(
        mode=app.persist.mode, look=app.shell.looks.key, x=app.persist.store.peek("x"),
        playthrough=app.persist.store.peek("playthrough"),
        festivals=app.persist.store.peek("festivals"),
        words=app.shell.looks.current().words.get("new_game"),
        preview=app.playthrough_preview))
    scripted_app.quit_frame = 40
    assert cli.main(["run", str(game), "--playthrough", "2"]) == 0
    assert found == {"mode": MEMORY, "look": (2, None), "x": 1, "playthrough": 2,
                     "festivals": 2 if stored else 0, "words": "Again?", "preview": 2}
    if stored:
        assert path.read_bytes() == data and os.stat(path).st_mtime_ns == stamp
    else:
        assert not path.exists()

    with pytest.raises(SystemExit) as refused:
        cli.main(["run", str(game), "--playthrough", "2", "--release"])
    assert refused.value.code == 2
    assert "--playthrough is only available in dev runs" in capsys.readouterr().err
    for bad in ("100", "-1", "two"):
        with pytest.raises(SystemExit) as error:
            cli.main(["run", str(game), f"--playthrough={bad}"])
        assert error.value.code == 2
        last = capsys.readouterr().err.strip().splitlines()[-1]
        assert last.endswith(cli.PLAYTHROUGH_NEEDS_NUMBER), (bad, last)

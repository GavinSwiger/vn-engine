"""Studio's "game beside Studio" (proposal 2.3, snap): the hidden dev-only ``run
--window-size=W,H`` beside F39's ``--window-at``. The launch is in process (``scripted_app``)."""

import pytest

from engine.app import bootstrap, cli
from engine.core.constants import MIN_WINDOW_SIZE
from tests.app.test_hot_reload_wiring import make_game
from tests.fakes.spy_window import SpyWindow


def test_window_size_is_checked_dev_only_and_hidden(tmp_path, capsys, monkeypatch,
                                                    scripted_app):
    game = make_game(tmp_path)
    launched: list[dict] = []
    monkeypatch.setattr(bootstrap, "launch",
                        lambda game_dir, **kwargs: launched.append(kwargs) or 0)

    def usage(*args: str) -> str:
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["run", str(game), *args])
        assert exit_info.value.code == 2
        return capsys.readouterr().err.strip().splitlines()[-1]

    assert cli.main(["run", str(game), "--window-at=-900,40", "--window-size=960,540"]) == 0
    assert (launched[-1]["window_at"], launched[-1]["window_size"]) == ((-900, 40), (960, 540))
    assert cli.main(["run", str(game)]) == 0
    assert launched[-1]["window_size"] is None
    assert usage("--release", "--window-size=960,540").endswith(
        "error: --window-size is only available in dev runs")
    for bad in ("0,540", "960,0", "-960,540", "100001,1", "960", "1,2,3", "a,b", " 9,9", ""):
        assert usage(f"--window-size={bad}").endswith(
            "error: --window-size needs two whole numbers above 0, like 960,540"), bad
    with pytest.raises(SystemExit):
        cli.main(["run", "--help"])
    assert "window-size" not in capsys.readouterr().out


def test_window_size_opens_the_window_there_never_below_the_minimum(tmp_path, scripted_app):
    game = make_game(tmp_path)
    for asked, opened in (((700, 400), (700, 400)), ((300, 200), MIN_WINDOW_SIZE)):
        SpyWindow.log.clear()
        assert bootstrap.launch(game, release=False, bench_seconds=None,
                                log_level_override=None, pygame_warning=None,
                                window_at=(30, 40), window_size=asked) == 0
        create = next(kwargs for kind, kwargs in SpyWindow.log if kind == "create")
        assert tuple(create["size"]) == opened and tuple(create["position"]) == (30, 40)

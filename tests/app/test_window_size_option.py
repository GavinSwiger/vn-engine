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


# --- The docked game (proposal 2.3): --window-borderless and the ``window`` message ---------

def test_window_borderless_is_dev_only_hidden_and_reaches_the_window(tmp_path, capsys,
                                                                     monkeypatch, scripted_app):
    game = make_game(tmp_path)
    launched: list[dict] = []
    real_launch = bootstrap.launch
    monkeypatch.setattr(bootstrap, "launch",
                        lambda game_dir, **kwargs: launched.append(kwargs) or 0)
    assert cli.main(["run", str(game), "--window-borderless"]) == 0
    assert launched[-1]["borderless"] is True
    assert cli.main(["run", str(game)]) == 0 and launched[-1]["borderless"] is False
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["run", str(game), "--release", "--window-borderless"])
    assert exit_info.value.code == 2
    assert capsys.readouterr().err.strip().endswith(
        "error: --window-borderless is only available in dev runs")
    with pytest.raises(SystemExit):
        cli.main(["run", "--help"])
    assert "borderless" not in capsys.readouterr().out
    monkeypatch.setattr(bootstrap, "launch", real_launch)
    SpyWindow.log.clear()
    assert bootstrap.launch(game, release=False, bench_seconds=None, log_level_override=None,
                            pygame_warning=None, borderless=True) == 0
    create = next(kwargs for kind, kwargs in SpyWindow.log if kind == "create")
    assert create["borderless"] is True


def test_the_window_message_is_checked_and_moves_a_windowed_window():
    from engine.app.hot_reload import WindowMove, handle_messages, parse_message

    good = b'{"v":1,"msg":"window","at":[-900,40],"size":[960,540]}'
    assert parse_message(good) == WindowMove(-900, 40, 960, 540)
    for bad in (b'{"v":1,"msg":"window","at":[1,2],"size":[0,5]}',
                b'{"v":1,"msg":"window","at":[1,2,3],"size":[5,5]}',
                b'{"v":1,"msg":"window","at":[1,true],"size":[5,5]}',
                b'{"v":1,"msg":"window","at":[1,2],"size":[5,5],"x":1}',
                b'{"v":1,"msg":"window","at":[100001,2],"size":[5,5]}'):
        assert parse_message(bad) is None, bad
    moved, reloads = [], []
    first, last = WindowMove(1, 2, 300, 200), WindowMove(5, 6, 700, 400)
    assert handle_messages([first, last], error_mode=True, notify=lambda t, k: None,
                           reload=lambda: reloads.append(1), move=moved.append) is False
    assert moved == [last] and reloads == []           # the frame's last move, error mode too


def test_move_to_follows_unless_fullscreen_or_maximized():
    import pygame

    from engine.render.window import GameWindow

    pygame.init()
    window = GameWindow(title="t", size=(800, 600), resizable=True, start_fullscreen=False,
                        letterbox_color=(0, 0, 0), initial_size_for_restore=(800, 600),
                        borderless=True)
    try:
        assert window.move_to((40, 50), (700, 400))
        assert window.position == (40, 50) and window.size == (700, 400)
        assert window.move_to((0, 0), (10, 10)) and window.size == MIN_WINDOW_SIZE
        window.maximized = True
        assert not window.move_to((90, 90), (700, 400)) and window.position == (0, 0)
    finally:
        window.destroy()

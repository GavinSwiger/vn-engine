"""Proposal 2.3 (snap): the game opens beside Studio (``gamebeside``, ``runwiring``).
``place_game`` is checked with numbers; the window part with a fake game runner and the
screen measures patched, so nothing moves on the real desktop."""

import json

import pytest

from engine.tools.editor import gamebeside, uiprefs
from engine.tools.editor.gamebeside import Placement, Rect, place_game
from engine.tools.editor.preview import PreviewEvent, PreviewState
from tests.tools.editor.test_studio_playbar import fake_game
from tests.tools.editor.test_studio_window import studio  # noqa: F401  (fixture)
from tests.tools.f45_games import studio as make_game

WORK = Rect(0, 0, 2560, 1400)                   # a 2560×1440 screen less its taskbar
GAME = (1280, 720)


def test_room_on_the_right_first_then_the_left_at_its_own_size_or_smaller():
    spot = place_game(Rect(0, 0, 1200, 1000), WORK, GAME, caption=30, gap=8, share=False)
    assert spot == Placement(Rect(1208, 30, 1280, 720))          # its own size, level
    assert spot.argv() == ["--window-at=1208,30", "--window-size=1280,720"]
    narrow = place_game(Rect(0, 100, 1800, 900), WORK, GAME, caption=30, gap=8, share=False)
    assert narrow.game == Rect(1808, 130, 752, 423)                # smaller, same shape
    left = place_game(Rect(1500, 0, 1060, 900), WORK, GAME, caption=30, gap=8, share=False)
    assert left.game == Rect(1500 - 8 - 1280, 30, 1280, 720)
    second = Rect(-1920, 0, 1920, 1040)                          # a monitor left of the main
    spot = place_game(Rect(-1920, 0, 900, 800), second, GAME, caption=30, gap=8, share=False)
    assert spot.game.x == -1012 and spot.game.right <= 0


def test_no_room_shares_the_screen_only_when_ticked():
    full = Rect(0, 0, 2560, 1400)                                # maximized
    assert place_game(full, WORK, GAME, caption=30, gap=8, share=False) is None
    spot = place_game(full, WORK, GAME, caption=30, gap=8, share=True)
    assert spot.game == Rect(2560 - 1152, 30, 1152, 648)         # 45 % of the width
    assert spot.studio == Rect(0, 30, 2560 - 1152 - 8, 1370)
    small = Rect(0, 0, 1024, 728)                                # too small to share
    assert place_game(small, small, GAME, caption=30, gap=8, share=True) is None


def test_play_places_the_game_and_studio_makes_room_and_gives_it_back(studio, tmp_path,
                                                                      monkeypatch):
    monkeypatch.setattr(gamebeside, "PLACES", True)
    ed = studio(make_game(tmp_path), mapped=True)
    win = ed.win
    game = fake_game(win)
    moves: list = []
    monkeypatch.setattr(gamebeside, "work_area", lambda root: WORK)
    monkeypatch.setattr(gamebeside, "studio_rect", lambda root, caption: Rect(0, 0, 1200, 900))
    monkeypatch.setattr(gamebeside, "caption_of", lambda root, scale: 30)
    monkeypatch.setattr(gamebeside, "make_room",
                        lambda root, area: moves.append(("room", area)) or "zoomed")
    monkeypatch.setattr(gamebeside, "give_back",
                        lambda root, before: moves.append(("back", before)))
    monkeypatch.setattr(win, "_game_size", lambda: GAME)

    win.play_from_start()                           # room on the right: placed, right
    argv = game.argvs[-1]                           # after --report-to-editor
    at = argv.index("--report-to-editor")
    assert argv[at + 1:at + 3] == ["--window-at=1208,30", "--window-size=1280,720"]
    assert moves == []

    menu = win.play_bar.menu                        # ▾ and Run: the switch, off at first
    assert menu.entrycget("end", "label") == gamebeside.MENU == "Game beside Studio"
    assert not win.game_beside.get()
    checks = [str(win.run_menu.entrycget(i, "label"))
              for i in range(win.run_menu.index("end") + 1)
              if win.run_menu.type(i) == "checkbutton"]
    assert gamebeside.MENU in checks

    monkeypatch.setattr(gamebeside, "studio_rect", lambda root, caption: WORK)   # maximized
    win.apply_events([PreviewEvent(PreviewState.CLOSED)])
    win.play_from_start()                           # no room, not ticked: as it always was
    assert not any(a.startswith("--window") for a in game.argvs[-1]) and moves == []
    menu.invoke("end")                              # tick it: remembered for this person
    assert win.game_beside.get() and uiprefs.load()["game_beside"] is True
    state = tmp_path / "my_game" / ".studio" / "studio.json"      # not in the game's file
    assert not state.exists() or "game_beside" not in json.loads(state.read_text("utf-8"))

    win.apply_events([PreviewEvent(PreviewState.CLOSED)])
    monkeypatch.setattr(win.root, "geometry", lambda *a: "as made")
    win.play_from_start()                           # Studio makes room; the game on the right
    assert moves == [("room", Rect(0, 30, 2560 - 1152 - 8, 1370))]
    assert "--window-at=1408,30" in game.argvs[-1]
    assert win._room_before == ("zoomed", "as made")
    win.apply_events([PreviewEvent(PreviewState.RUNNING)])      # still running: kept
    assert len(moves) == 1
    win.apply_events([PreviewEvent(PreviewState.CLOSED)])       # the game ended: back
    assert moves[-1] == ("back", "zoomed")
    assert studio(make_game(tmp_path, "again")).win.game_beside.get()   # every game


def test_make_room_and_give_back_on_a_real_window():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        root.withdraw()
        root.geometry("400x300+50+60")
        root.update_idletasks()
        before = gamebeside.make_room(root, Rect(10, 40, 320, 200))
        root.update_idletasks()
        assert root.geometry().startswith("320x200")
        assert before.startswith("400x300")
        gamebeside.give_back(root, before)
        root.update_idletasks()
        assert root.geometry().startswith("400x300")
    finally:
        root.destroy()

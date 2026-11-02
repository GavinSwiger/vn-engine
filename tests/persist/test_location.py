"""AC-F12-27: where the file lives, its display form, and the only names created there."""

import sys

import pytest

from engine.core import safefile
from engine.core.paths import user_data_dir
from engine.persist import location
from engine.persist.location import display_file, is_engine_name, persistent_root


def test_dev_root_is_beside_the_game(tmp_path, user_roots):
    game = tmp_path / "qauser7" / "game"
    root = persistent_root(game_root=game, release=False, app_id=None)
    assert root == game / "persistent"
    assert display_file(root, game_root=game) == "<game>/persistent/persistent.json"


def test_release_root_and_missing_id(user_roots):
    root = persistent_root(game_root=user_roots.home / "game", release=True,
                           app_id="paper-lanterns")
    assert root == user_data_dir("paper-lanterns") / "persistent"
    assert persistent_root(game_root=user_roots.home, release=True, app_id=None) is None
    assert persistent_root(game_root=user_roots.home, release=True, app_id="Bad Id") is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows display form")
def test_display_form_windows(user_roots):
    root = persistent_root(game_root=user_roots.home, release=True, app_id="paper-lanterns")
    assert display_file(root, game_root=None) == \
        r"%APPDATA%\vn-engine\paper-lanterns\persistent\persistent.json"


def test_display_form_macos(user_roots, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    root = persistent_root(game_root=user_roots.home, release=True, app_id="paper-lanterns")
    assert display_file(root, game_root=None) == \
        "~/Library/Application Support/vn-engine/paper-lanterns/persistent/persistent.json"


def test_display_form_linux(user_roots, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/xdg/qauser7/data")
    root = persistent_root(game_root=user_roots.home, release=True, app_id="paper-lanterns")
    assert display_file(root, game_root=None) == \
        "$XDG_DATA_HOME/vn-engine/paper-lanterns/persistent/persistent.json"


def test_only_three_names():
    assert (location.FILE_NAME, location.BAD_NAME) == ("persistent.json", "persistent.bad.json")
    temp = safefile.temp_name(location.FILE_NAME, safefile.temp_token())
    assert is_engine_name(temp) and is_engine_name("persistent.json")
    assert is_engine_name("persistent.bad.json")
    for other in (".persistent.json.XYZ.tmp", ".persistent.json.deadbeef0.tmp", "x.json",
                  "persistent.json.bak"):
        assert not is_engine_name(other)

"""F42 P4: ``.studio/build.json`` (AC-F42-39's build.json rows; SEC-F42-08, PR-F42-21)."""

import json
import os

from engine.tools.editor import buildprefs
from engine.tools.editor.buildprefs import BuildPrefs, read_prefs, write_prefs


def _plant(game, doc):
    (game / ".studio").mkdir(parents=True, exist_ok=True)
    data = doc if isinstance(doc, bytes) else json.dumps(doc).encode("utf-8")
    (game / ".studio" / "build.json").write_bytes(data)


def test_ac_f42_39_build_json_is_a_checked_suggestion_without_home_paths(tmp_path,
                                                                         monkeypatch):
    game = tmp_path / "Paper Lanterns"
    game.mkdir()
    default = tmp_path / "builds"
    assert read_prefs(game) == BuildPrefs()
    assert buildprefs.save_to_or_default(game, read_prefs(game)) == default

    # Remembered: relative to the game folder, no absolute path in the file.
    assert write_prefs(game, BuildPrefs(save_to=default, zip=False, last_id="paper-lanterns"))
    data = (game / ".studio" / "build.json").read_bytes()
    assert json.loads(data) == {"save_to": "../builds", "zip": False,
                                "last_id": "paper-lanterns"}
    assert str(tmp_path).encode() not in data
    assert read_prefs(game) == BuildPrefs(default, False, "paper-lanterns")

    # 10 MB, wrong types, Save to in or around the game, a home path: ignored.
    _plant(game, b'{"zip": false, "pad": "' + b"x" * (10 << 20) + b'"}')
    assert read_prefs(game) == BuildPrefs()
    _plant(game, {"save_to": 5, "zip": "no", "last_id": "Bad ID!"})
    assert read_prefs(game) == BuildPrefs()
    for inside in (".", "sub/builds", "..", str(game), str(game / "out"), "C:builds"):
        _plant(game, {"save_to": inside})
        assert read_prefs(game).save_to is None, inside
    home_path = "C:\\Users\\Priya\\builds" if os.name == "nt" else "/home/priya/builds"
    _plant(game, {"save_to": home_path, "zip": False})
    assert read_prefs(game) == BuildPrefs(None, False, None)

    # Another volume under home: not stored at all; a plain absolute path is kept.
    def other_drive(path, start=None):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(buildprefs.os.path, "relpath", other_drive)
    assert buildprefs.stored_save_to(tmp_path / "builds", game) is None   # tmp is under home
    plain = "D:\\Games\\builds" if os.name == "nt" else "/srv/games/builds"
    assert buildprefs.stored_save_to(type(game)(plain), game) == plain

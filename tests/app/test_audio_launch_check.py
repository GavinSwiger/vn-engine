"""F08 step 8 in the App: ``app/loading.py`` gives the launch its ``AudioFiles`` (``GamePaths.
list_dir`` and the ``[audio.loop_start]`` keys, I-7), and the warnings are logged in the
``script`` area while the game starts (AC-F08-06's App half). Launches use ``scripted_app``,
whose session gives every launch a ``FakeMixer`` (no test opens a sound device)."""

import re
from pathlib import Path

import pytest

from engine.app import bootstrap
from tests.fakes.fake_mixer import ogg_bytes

pytestmark = pytest.mark.display

TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} ")


def make_game(root: Path, script: str, config: str = "") -> Path:
    (root / "script").mkdir(parents=True)
    (root / "config.toml").write_text('[game]\nid = "f08-step8"\n\n[title]\nenabled = false\n'
                                      + config, encoding="utf-8")
    (root / "script" / "main.vns").write_text(script, encoding="utf-8")
    for file, seconds in (("bgm/festival.ogg", 4.0), ("sfx/door.ogg", 0.5),
                          ("voice/hana_014.ogg", 1.5)):
        path = root / "audio" / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(ogg_bytes(seconds, salt=file.encode()))
    return root


def records(log_file: Path) -> list[tuple[str, str, str]]:
    """(level, area, first line) of each record of the session log."""
    return [(line[24:31].strip(), line[32:39].strip(), line[40:])
            for line in log_file.read_text(encoding="utf-8").splitlines()
            if TIMESTAMP.match(line)]


def test_ac_f08_06_the_warnings_reach_the_script_log_and_the_game_starts(
        tmp_path, scripted_app, user_roots):
    game = make_game(tmp_path / "game",
                     'label start:\n'
                     '    play music "bgm/festval.ogg"\n'
                     '    voice "voice/hana_14.ogg"\n'
                     '    "Hi."\n'
                     '    play sound "sfx/door.ogg"\n'
                     '    "Bye."\n    return\n',
                     config='[audio.loop_start]\n"bgm/festval.ogg" = 8.0\n')
    scripted_app.quit_frame = 30
    seen = {}
    scripted_app.at(25, lambda app: seen.update(story=app.story is not None,
                                                error=app.error_mode))
    assert bootstrap.launch(game, release=False, bench_seconds=None, log_level_override=None,
                            pygame_warning=None) == 0
    assert seen == {"story": True, "error": False}
    found = [(level, area, text) for level, area, text in records(game / "logs" / "latest.log")
             if area == "script" and level == "WARNING"]
    assert found == [
        ("WARNING", "script", "script/main.vns, line 2: there is no file audio/bgm/festval.ogg, "
                              'so it will be silent. Did you mean "bgm/festival.ogg"?'),
        # The log keeps one record per line: W22's line break is written as a backslash-n.
        ("WARNING", "script", "Some voice files don't exist, so those lines have no voice:\\n"
                              "audio/voice/hana_14.ogg (script/main.vns, line 3) Did you mean "
                              '"voice/hana_014.ogg"?'),
        ("WARNING", "script", 'config.toml: [audio.loop_start] names "bgm/festval.ogg", which '
                              "doesn't exist. Did you mean \"bgm/festival.ogg\"?"),
    ]

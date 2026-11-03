"""F32 step 6 — the example game's looks (``06`` AC-F32-27): ``game/config.toml`` has a
``[playthrough.2]`` title look and one ``[style.<name>]``; the bonus scene uses that style
(``ui style dark`` … ``ui style off``) with a ``#`` comment above its first use. A ``--dev``
launch plays through the scene with no warning (no W67, W206, or W207), the text box in the
style while it is on; a copy whose persistent data holds ``playthrough`` 2 opens on the
look-2 title. The real ``game/`` folders are never touched (the copies leave them out)."""

import json
import logging
import re
import shutil

import pytest

from engine.persist.location import FILE_NAME
from engine.ui.shell import Mode
from tests.app.test_metafiles_app import advance_to
from tests.app.test_metafiles_example import _copy
from tests.app.test_saves_service import launch, play, unthreaded
from tests.fakes.first_launch import answer_name_question
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)
from tests.runtime.stage_story import EXAMPLE

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def test_ac_f32_27_the_example_game_looks(tmp_path, scripted_app, unthreaded, caplog,
                                          user_roots):
    config = (EXAMPLE / "config.toml").read_text(encoding="utf-8")
    assert re.search(r"^\[playthrough\.2\.", config, re.M)
    styles = set(re.findall(r"^\[style\.([a-z_0-9]+)\.", config, re.M))
    assert len(styles) == 1
    style = styles.pop()
    lines = (EXAMPLE / "script" / "bonus.vns").read_text(encoding="utf-8").splitlines()
    on = next(n for n, line in enumerate(lines) if line.strip() == f"ui style {style}")
    off = next(n for n, line in enumerate(lines) if line.strip() == "ui style off")
    assert on < off and lines[on - 1].strip().startswith("#")

    game = _copy(tmp_path / "scene")
    answer_name_question(game)

    def scene(app, out):
        yield from advance_to(app, "...Huh. Did I just")
        out["during"] = app.shell.looks.key
        yield from advance_to(app, "Never mind. A new game")       # after ui style off
        out["after"] = app.shell.looks.key

    with caplog.at_level(logging.DEBUG, logger="vn"):
        out = play(scripted_app, scene, last=4000)
        assert launch(game) == 0                                   # a --dev launch
    assert out.get("done"), out
    assert _warnings(caplog) == []
    assert out["during"] == (None, style) and out["after"] == (None, None)

    # App U with stored 2: a copy with the title on opens it in look 2.
    caplog.clear()
    titled = tmp_path / "titled" / "game"
    shutil.copytree(EXAMPLE, titled, ignore=shutil.ignore_patterns(
        "logs", "saves", "persistent", "settings", "characters", "__pycache__"))
    answer_name_question(titled)
    (titled / "persistent").mkdir()
    (titled / "persistent" / FILE_NAME).write_text(json.dumps(
        {"format": 1, "identity_scheme": 1, "values": {"playthrough": 2}, "seen": {},
         "chosen": {}, "unlocks": {}}), encoding="utf-8")

    def title(app, out):
        while app.shell is None or app.shell.looks is None or app.shell.mode is not Mode.TITLE:
            yield
        out["look"] = app.shell.looks.key
        out["new_game"] = app.shell.looks.current().words.get("new_game")
        out["music"] = app.shell.theme.cfg.title.music

    with caplog.at_level(logging.DEBUG, logger="vn"):
        out = play(scripted_app, title, last=600)
        assert launch(titled) == 0
    assert out.get("done"), out
    assert _warnings(caplog) == []
    assert out["look"] == (2, None) and out["new_game"] == "Walk the festival again"
    assert out["music"] == "bgm/bridge_night.wav"

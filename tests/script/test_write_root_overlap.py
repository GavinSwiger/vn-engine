"""F31 step 1 — SEC-F02-11 still covers every write root (``06`` AC-F31-03; SEC-F31-03(b),
TR-F31-09; ``04`` §6.2): ``check_ref`` now refuses write roots, so the loader's overlap
check finds them through ``GamePaths.write_root``."""

import os
import sys
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script.loader import load_story
from engine.script.messages import format_message
from tests.script.conftest import write_tree
from tests.script.helpers import template


def _dir_link(link: Path, target: Path) -> None:
    """A directory symlink, or on Windows a junction when symlinks aren't permitted."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError) as exc:
        reason = exc
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        return
    pytest.skip(f"directory links are not permitted here: {reason}")


@pytest.mark.parametrize("root_name", ["characters", "saves", "persistent", "logs"])
def test_ac_f31_03_overlap_check_covers_every_write_root(root_name, tmp_path):
    game = tmp_path / "game"
    write_tree(game, {f"{root_name}/main.vns": template()})
    _dir_link(game / "script", game / root_name)
    result = load_story(GamePaths(game.resolve()))
    assert result.program is None
    assert [e.code for e in result.errors] == ["E08e"]
    assert format_message("E08e", (root_name,)) in result.errors[0].format()

    paths = GamePaths(game.resolve())
    assert paths.write_root(root_name) == (game / root_name).resolve()
    other = "settings"
    assert paths.write_root(other) is None                     # missing
    for bad in ("images", "../x", "Characters", "script"):
        with pytest.raises(ValueError):
            paths.write_root(bad)

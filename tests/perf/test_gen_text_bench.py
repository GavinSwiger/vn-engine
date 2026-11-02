"""F05 step 7 — ``gen_text_bench.py`` (``06-acceptance.md`` §5): the two typing bench games
launch warning-free, and every bench line fills exactly one page of three lines at text size
28 with the bundled faces, with one bold, one italic, and one colored run and one name tab.
AC-F05-44 and 45 (step 9) run these games on the reference machine."""

import os

import pygame
import pytest

from engine.app.text_check import TextLaunchCheck
from engine.core.config import load_config
from engine.core.config_schema import TextboxTheme
from engine.core.paths import GamePaths
from engine.render.textlayout import BUNDLED_FACES, LineLayout
from engine.runtime.launch import run_launch
from engine.script import LoadOptions, load_story
from tests.perf import gen_text_bench as gen
from tests.render.conftest import make_assets


@pytest.fixture(autouse=True)
def fonts_ready():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    yield
    pygame.quit()


def test_the_bench_games(tmp_path):
    folders = gen.generate(tmp_path / "text_bench", seed=1, scale=8)
    assert [f.name for f in folders] == ["cps40", "cps1000"]
    scripts = {(f / "script" / "main.vns").read_text(encoding="utf-8") for f in folders}
    assert len(scripts) == 1
    for folder, cps in zip(folders, gen.CPS):
        paths = GamePaths.for_game(folder)
        config = load_config(paths)
        assert config.config.textbox.cps == cps and config.warnings == []
        result = load_story(paths, LoadOptions(position_names=frozenset(
            config.config.stage.positions)))
        assert result.errors == () and result.warnings == ()
        launch = run_launch(result.program)
        assert launch.namespace is not None
        check = TextLaunchCheck(result.program, launch.namespace, assets=make_assets(paths),
                                faces=BUNDLED_FACES, theme=TextboxTheme())
        assert check.run() == ()                         # no W40, no W41
        lines = [s for s in result.program.iter_statements() if check.checks_line(s)]
        assert len(lines) == gen.LINES
        for stmt in lines:
            assert stmt.speaker in gen.stage.TAGS
            assert all(tag in stmt.text for tag in ("{b}", "{i}", "{color=#9a1c14}"))
            layout = LineLayout(check.resolve(stmt), check.ctx)
            assert layout.all_pages() == 1 and len(layout.page(0).lines) == 3, stmt.text

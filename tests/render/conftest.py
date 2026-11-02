"""Shared setup for presentation tests: pygame initialized, asset managers, game folders."""

import shutil
from pathlib import Path

import pygame
import pytest

from engine.core.constants import MB
from engine.core.paths import GamePaths
from engine.core.timing import GameTime
from engine.render.assets import AssetManager

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "F01"
GAMES = FIXTURES / "games"


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def copy_game(name: str, dest: Path) -> Path:
    """Copy fixture ``games/<name>`` to ``dest`` (tests never touch the committed files)."""
    shutil.copytree(GAMES / name, dest)
    return dest


@pytest.fixture
def assets_game(tmp_path) -> GamePaths:
    return GamePaths.for_game(copy_game("assets", tmp_path / "assets"))


def make_assets(paths: GamePaths | None, *, cache_mb: int = 512, scale_filter: str = "smooth",
                budget_bytes: int | None = None,
                format_source=lambda: pygame.Surface((1, 1))) -> AssetManager:
    return AssetManager(paths, budget_bytes=budget_bytes if budget_bytes is not None
                        else cache_mb * MB, scale_filter=scale_filter, time=GameTime(),
                        format_source=format_source)


@pytest.fixture
def assets(assets_game) -> AssetManager:
    return make_assets(assets_game)


def asset_lines(caplog) -> list[tuple[str, str]]:
    """(level, message) of every record in area ``assets``."""
    return [(r.levelname, r.getMessage()) for r in caplog.records if r.name == "vn.assets"]

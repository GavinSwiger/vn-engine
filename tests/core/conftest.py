"""Helpers for the core tests: build a game folder around a ``config.toml`` and load it."""

import itertools
from collections.abc import Callable
from pathlib import Path

import pytest

from engine.core.config import load_config
from engine.core.config_schema import ConfigResult
from engine.core.paths import GamePaths
from tests.fixtures.F01 import config_fixtures

ConfigLoader = Callable[[bytes | str], ConfigResult]


def fixture_bytes(name: str) -> bytes:
    """A committed config fixture from tests/fixtures/F01/config/."""
    return (config_fixtures.CONFIG_DIR / name).read_bytes()


def value_bytes(name: str) -> bytes:
    """A committed one-value fixture from tests/fixtures/F01/config/values/."""
    return (config_fixtures.VALUES_DIR / name).read_bytes()


@pytest.fixture
def make_game(tmp_path) -> Callable[[bytes | str | None], GamePaths]:
    """Create a fresh game folder holding ``data`` as config.toml (None: no config)."""
    counter = itertools.count()

    def make(data: bytes | str | None) -> GamePaths:
        root: Path = tmp_path / f"game{next(counter)}"
        root.mkdir()
        if data is not None:
            raw = data.encode("utf-8") if isinstance(data, str) else data
            (root / "config.toml").write_bytes(raw)
        return GamePaths.for_game(root)

    return make


@pytest.fixture
def load(make_game) -> ConfigLoader:
    """Load ``data`` as a game's config.toml and return the ConfigResult."""

    def load_data(data: bytes | str) -> ConfigResult:
        return load_config(make_game(data))

    return load_data

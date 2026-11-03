"""F32 step 6: Studio completion for ``ui`` lines (``06-acceptance.md`` AC-F32-24).

F45's candidates over the check child's name rows (``NAME_SOURCES``) for Template U, and a
config with no ``[style]`` tables."""

from pathlib import Path

import engine.script  # noqa: F401  registers every statement and the docs table
from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.tools.check import NAME_SOURCES, CheckContext
from engine.tools.editor.assist import candidates, completion_context
from engine.tools.editor.checker import NameEntry

TEMPLATE = Path(__file__).resolve().parents[2] / "fixtures" / "F32" / "template"


def _names(game: Path) -> dict:
    paths = GamePaths.for_game(game)
    ctx = CheckContext(paths=paths, config=load_config(paths).config, program=None)
    return {kind: tuple(NameEntry(row[0]) for row in NAME_SOURCES[kind](ctx))
            for kind in ("ui", "style")}


def _offered(line: str, names: dict) -> list[str]:
    ctx = completion_context(line, len(line))
    return [] if ctx is None else [c.text for c in candidates(ctx, names)]


def test_ac_f32_24_studio_completion(tmp_path):
    assert "style" in NAME_SOURCES and "ui" in NAME_SOURCES
    names = _names(TEMPLATE)
    assert _offered("    ui ", names) == ["delete", "loading", "saving", "style"]
    assert _offered("    ui style ", names) == ["ashes", "calm", "off"]
    assert _offered("    ui saving ", names) == ["off", "on"]
    assert _offered("    ui loading ", names) == ["off", "on"]
    assert _offered("    ui delete ", names) == ["saves"]
    assert _offered("    ui saving o", names) == ["off", "on"]
    assert _offered('    ui saving off "No', names) == []

    bare = tmp_path / "bare"
    (bare / "script").mkdir(parents=True)
    (bare / "script" / "main.vns").write_text('label start:\n    "Hi."\n', encoding="utf-8")
    (bare / "config.toml").write_text('[game]\ntitle = "Bare"\n', encoding="utf-8")
    assert _offered("    ui style ", _names(bare)) == ["off"]

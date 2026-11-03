"""F31 step 5 — the example game's bonus scene in the real app (``06`` AC-F31-27): **App M**
(in-process ``launch()``, hidden window, fake clock, unthreaded writer) on a copy of ``game/``
at ``tmp_path/aiko/game``; the player clicks through instead of waiting for auto-advance.
The real ``game/characters/`` is never touched (the copy leaves it out; AC-F31-07's guard)."""

import logging
import re
import shutil
from pathlib import Path

import pytest

from tests.app.test_metafiles_app import advance_to
from tests.app.test_saves_service import launch, play, unthreaded

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]

REPO = Path(__file__).resolve().parents[2]
VERBS = ('file write "hana.chr"', 'file write "read_me.txt" "', 'file delete "hana.chr"',
         'file exists "hana.chr" into ')


def _copy(tmp_path: Path) -> Path:
    game = tmp_path / "aiko" / "game"
    shutil.copytree(REPO / "game", game, ignore=shutil.ignore_patterns(
        "logs", "saves", "persistent", "settings", "characters", "__pycache__"))
    config = game / "config.toml"                 # straight into the story, no quit save
    text = config.read_text(encoding="utf-8").replace(
        "[saves]\n", "[saves]\nautosave_quit = false\n", 1)
    config.write_text(text + "\n[title]\nenabled = false\n", encoding="utf-8")
    return game


def test_ac_f31_27_the_example_bonus_scene(tmp_path, scripted_app, unthreaded, caplog,
                                           user_roots):
    game = _copy(tmp_path)
    lines = (game / "script" / "bonus.vns").read_text(encoding="utf-8").splitlines()
    for verb in VERBS:
        first = next(n for n, line in enumerate(lines) if line.strip().startswith(verb))
        assert lines[first - 1].strip().startswith("#"), verb
    original = (game / "files" / "hana.chr").read_bytes()
    assert len(original) <= 4 << 20 and not (game / "files" / "read_me.txt").exists()
    root = game / "characters"

    def scene(app, out):
        yield from advance_to(app, "Oh, and I left something")
        out["written"] = {p.name: p.read_bytes() for p in root.iterdir()}
        yield from advance_to(app, "...Huh. Did I just disappear")
        out["deleted"] = sorted(p.name for p in root.iterdir())
        yield from advance_to(app, "Never mind. A new game")

    with caplog.at_level(logging.DEBUG, logger="vn"):
        out = play(scripted_app, scene, last=4000)
        assert launch(game) == 0                                       # a --dev launch
    assert out.get("done"), out
    note = out["written"]["read_me.txt"].decode("utf-8")
    assert out["written"]["hana.chr"] == original and note.startswith("If you're reading")
    assert out["deleted"] == ["read_me.txt"]
    assert sorted(p.name for p in root.iterdir()) == ["read_me.txt"]   # the note stays
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []

    # A second New Game, played past the write, puts hana.chr back.
    def again(app, out):
        yield from advance_to(app, "Oh, and I left something")
        out["restored"] = (root / "hana.chr").read_bytes()

    out = play(scripted_app, again, last=4000)
    assert launch(game) == 0
    assert out["restored"] == original
    assert re.search(r"^\s+call hana_file$",
                     (game / "script" / "main.vns").read_text(encoding="utf-8"), re.M)

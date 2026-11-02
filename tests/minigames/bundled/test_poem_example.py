"""F24-4: the example game's poem (F24 ``06``: AC-F24-20). AC-F24-19 (the docs) is in
``tests/test_docs.py``; AC-F24-22 (frame and pick time) is ``tests/perf/test_poem_perf.py``.

*Paper Lanterns* writes a wish on the lantern before it goes on the water
(``game/script/routes/daichi.vns``, ``lantern_release``): ``define wish_words``, then
``minigame poem_game words=wish_words rounds=3 page_words=6 into wish_for`` and a branch on
who liked it. Only runs that buy a lantern reach it (seeds 1, 2, 3, and 5 of the goldens).
"""

import logging
import re
from pathlib import Path

import pygame
import pytest

from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.minigames.tables import PluginTables
from engine.runtime.commands import StartMinigame, StoryEnded
from engine.runtime.headless import run_headless
from engine.runtime.points import Points
from engine.script.points import MeterSpec
from engine.ui.nav import InputKind
from tests.minigames.bundled import test_poem_session as session
from tests.render.conftest import make_assets
from tests.runtime import corpus
from tests.runtime.stage_story import EXAMPLE, example_minigames, load_example

H = session.H


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def _scene() -> tuple[str, str, str]:
    """The example's one poem line: (the list's name, the ``into`` variable, its file)."""
    found = []
    for path in sorted((EXAMPLE / "script").rglob("*.vns")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"^\s+minigame poem_game words=(\w+) .*into (\w+)$", text, re.M):
            found.append((m.group(1), m.group(2), text))
    assert len(found) == 1, found
    return found[0]


def test_ac20_the_example_scene(caplog):
    # The scene: a define word list, the minigame line with into, a branch on the result.
    words, into, text = _scene()
    assert re.search(rf"^define {words} = \{{$", text, re.M)
    after = text[text.index(f"into {into}"):]
    assert re.search(rf"^\s+if {into} == \"\w+\":$", after, re.M)
    # Headless, seeds 1–5 with the goldens' picks (AC-F23-62's run): every run ends, the poem
    # is reached, and nothing is logged at WARNING or above.
    result = load_example()
    assert result.errors == () and result.warnings == ()
    images = corpus.example_images()
    reached = 0
    caplog.set_level(logging.DEBUG)
    for seed in corpus.EXAMPLE_SEEDS:
        inputs = corpus.example_inputs(seed, corpus.EXAMPLE_PICKS[seed])
        commands = run_headless(result.program, seed=seed, image_files=images, inputs=inputs,
                                dev=True, show_locked=True, minigames=example_minigames())
        assert commands[-1] == StoryEnded(), seed
        reached += any(type(c) is StartMinigame and c.name == "poem_game" for c in commands)
    assert reached == 4 and _warnings(caplog) == []
    # Host P with the example's config and theme plays the example's own poem to the end by
    # keyboard, with no warning.
    caplog.clear()
    commands = run_headless(result.program, seed=1, image_files=images,
                            inputs=corpus.example_inputs(1, corpus.EXAMPLE_PICKS[1]),
                            minigames=example_minigames())
    start = next(c for c in commands if type(c) is StartMinigame and c.name == "poem_game")
    assert set(start.names.meters) == {"hana", "daichi", "credibility"}   # F25-4's meter too
    paths = GamePaths.for_game(Path(EXAMPLE).resolve())
    config = load_config(paths)
    assert config.errors == []
    cfg = config.config
    tables = PluginTables(cfg.theme.plugin, cfg.words.plugin, cfg.theme, dev=True)
    tables.check([session.ENTRY])
    pygame.init()
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(session, "POINTS", Points(tuple(
                MeterSpec(m.name, m.low, m.high, 0, True) for m in start.base.meters)))
            w = session.HostP(assets=make_assets(paths), config=cfg, tables=tables)
        w.shell.stack.last_input = InputKind.KEYS
        w.host.start(start)
        for _ in range(60):                                 # the opening dissolve
            w.frame()
            if w.session.phase is session.Phase.RUNNING:
                break
        g = w.game
        assert w.focused() == 0                             # reached by a key
        for turn in range(g.poem.rounds):
            w.frame(H.key(pygame.K_RETURN))
            assert len(g.picked) == turn + 1
            w.frames(session.GAP)
        w.frames(60)                                        # the closing dissolve
    finally:
        pygame.quit()
    assert w.fatal == [] and len(w.done()) == 1
    assert w.done()[0].result in ("hana", "daichi", None)
    assert _warnings(caplog) == []

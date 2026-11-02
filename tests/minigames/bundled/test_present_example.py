"""F25-4: the example game's cross-examination (F25 ``06``: AC-F25-22). AC-F25-21 (the docs)
is in ``tests/test_docs.py``; AC-F25-25 (sounds) in ``test_present_session.py``.

*Paper Lanterns* questions Hana on the bridge (``game/script/routes/daichi.vns``,
``hana_testimony``): ``define hana_says`` and ``hana_slips``, then
``minigame present_evidence … at=hana_at into hana_shown`` in 01 §5.2's loop. The Festival
Map Hana draws in the prologue answers the ``train`` statement. Every run crosses the bridge,
so every seed of the goldens reaches it.
"""

import logging
import re
from pathlib import Path

import pygame

from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.minigames.host import Phase
from engine.minigames.tables import PluginTables
from engine.runtime.codex import CodexIndex
from engine.runtime.commands import StartMinigame, StoryEnded
from engine.runtime.headless import run_headless
from engine.ui.nav import InputKind
from tests.minigames.bundled import test_present_session as session
from tests.render.conftest import make_assets
from tests.runtime import corpus
from tests.runtime.stage_story import EXAMPLE, example_minigames, load_example

WIN = {"action": "present", "statement": "train", "evidence": "festival_map", "correct": True}


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def _scene() -> tuple[str, str, str, str]:
    """The example's one cross-examination: (testimony, answer, the ``into`` variable, its
    file's text)."""
    found = []
    for path in sorted((EXAMPLE / "script").rglob("*.vns")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"^\s+minigame present_evidence .*testimony=(\w+) answer=(\w+) "
                             r".*at=(\w+) into (\w+)$", text, re.M):
            assert m.group(3) != m.group(4)
            found.append((m.group(1), m.group(2), m.group(4), text))
    assert len(found) == 1, found
    return found[0]


def test_ac22_the_example_scene(caplog):
    # 01 §5.2's loop: define'd testimony and answer, the line, a branch on "correct", and a
    # jump back to the line's label.
    testimony, answer, into, text = _scene()
    assert re.search(rf"^define {testimony} = \{{$", text, re.M)
    assert re.search(rf"^define {answer} = \{{", text, re.M)
    after = text[text.index(f"into {into}"):]
    assert re.search(rf"^\s+if {into}\[\"correct\"\]:$", after, re.M)
    label = re.findall(r"^label (\w+):$", text[:text.index(f"into {into}")], re.M)[-1]
    assert f"jump {label}" in after.split("\nlabel ")[0]
    # Headless, seeds 1–5 with the goldens' picks (AC-F23-62's run): every run ends, passes
    # through the scene, and logs nothing at WARNING or above.
    result = load_example()
    assert result.errors == () and result.warnings == ()
    images = corpus.example_images()
    caplog.set_level(logging.DEBUG)
    starts = {}
    for seed in corpus.EXAMPLE_SEEDS:
        inputs = corpus.example_inputs(seed, corpus.EXAMPLE_PICKS[seed])
        commands = run_headless(result.program, seed=seed, image_files=images, inputs=inputs,
                                dev=True, show_locked=True, minigames=example_minigames())
        assert commands[-1] == StoryEnded(), seed
        starts[seed] = [c for c in commands if type(c) is StartMinigame
                        and c.name == "present_evidence"]
    assert all(len(found) == 1 for found in starts.values()) and _warnings(caplog) == []
    # Host E with the example's config, theme, assets, and codex opens seed 1's scene and
    # wins by keyboard (Next, Present, the Festival Map row, the pick), with no warning
    # (W162 included: the host is in dev).
    (start,) = starts[1]
    paths = GamePaths.for_game(Path(EXAMPLE).resolve())
    config = load_config(paths)
    assert config.errors == []
    cfg = config.config
    tables = PluginTables(cfg.theme.plugin, cfg.words.plugin, cfg.theme, dev=True)
    tables.check([session.ENTRY])
    meter = next(m for m in start.base.meters if m.name == "credibility")
    pygame.init()
    try:
        w = session.HostE(config=cfg, tables=tables, assets=make_assets(paths),
                          index=CodexIndex.build(result.program), meter=(meter.low, meter.high))
        g = w.open(cmd=start, by=InputKind.KEYS, frame=False)
        for _ in range(60):                                 # the opening dissolve
            w.frame()
            if w.session.phase is Phase.RUNNING:
                break
        assert w.focused() is g.press and w.count() == "1 / 3"
        for keys in (session.RIGHT, session.RIGHT, session.ENTER, session.LEFT,
                     session.ENTER):
            w.frame(*keys)
        view = session.raw_view(g)
        assert g.mode == "picker"
        row = [r.entry.name for r in view.rows()].index("festival_map")
        for keys in [session.DOWN] * row + [session.ENTER, session.ENTER]:
            w.frame(*keys)
        session.run_closing(w)
    finally:
        pygame.quit()
    assert w.fatal == [] and g.finishes == [WIN]
    assert [d.result for d in w.done()] == [WIN] and w.done()[0].changes == ()
    assert _warnings(caplog) == []

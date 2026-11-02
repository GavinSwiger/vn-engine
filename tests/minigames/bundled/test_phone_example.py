"""F26-4: the example game's phone chat (F26 ``06``: AC-F26-23). AC-F26-22 (the docs) is in
``tests/test_docs.py``.

*Paper Lanterns* has Hana text the player after the walk home (``game/script/endings.vns``,
``river_end``): ``define hana_texts``, then
``minigame phone_chat chat=hana_texts contact="Hana" time="10:32 PM" into hana_replies`` and
a branch on the replies. Only runs that walk Hana home reach it (seeds 1, 3, 4, and 5 of the
goldens; seed 2 stays for the festival).
"""

import logging
import re
from pathlib import Path

import pygame

from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.minigames.bundled import phone_chat
from engine.minigames.host import Phase as HostPhase
from engine.minigames.tables import PluginTables
from engine.runtime.commands import StartMinigame, StoryEnded
from engine.runtime.headless import run_headless
from tests.minigames.bundled import test_phone_session as session
from tests.minigames.host_u import HostU, load_plugins
from tests.runtime import corpus
from tests.runtime.stage_story import EXAMPLE, example_minigames, load_example


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def _scene() -> tuple[str, str, str]:
    """The example's one phone chat: (the chat's name, the ``into`` variable, its file)."""
    found = []
    for path in sorted((EXAMPLE / "script").rglob("*.vns")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"^\s+minigame phone_chat chat=(\w+) contact=\".+\" .*into (\w+)$",
                             text, re.M):
            found.append((m.group(1), m.group(2), text))
    assert len(found) == 1, found
    return found[0]


def test_ac_f26_23_the_example_scene(game, caplog):
    # The scene: a define chat, the minigame line with into, an if on the result.
    chat, into, text = _scene()
    assert re.search(rf"^define {chat} = \[$", text, re.M)
    after = text[text.index(f"into {into}"):]
    assert re.search(rf"^\s+if {into}\[\"\w+\"\] == \"ignore\":$", after, re.M)
    # Headless, seeds 1–5 with the goldens' picks (AC-F23-62's run): every run ends, and
    # nothing is logged at WARNING or above.
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
                        and c.name == "phone_chat"]
    assert [seed for seed, found in starts.items() if found] == [1, 3, 4, 5]
    assert _warnings(caplog) == []
    # Host C with the example's config and theme opens seed 1's chat and plays it to the end
    # by keyboard (Enter hurries each wait and picks the first reply), with no warning.
    (start,) = starts[1]
    config = load_config(GamePaths.for_game(Path(EXAMPLE).resolve()))
    assert config.errors == [] and config.warnings == []
    cfg = config.config
    registry = load_plugins(game)
    tables = PluginTables(cfg.theme.plugin, cfg.words.plugin, cfg.theme, dev=True)
    tables.check(registry.entries())
    phone_chat._WARNED.clear()
    pygame.init()
    try:
        w = HostU(game, registry=registry, config=cfg, tables=tables)
        g = session.open_chat(w, cmd=start)
        for _ in range(60):                                 # the opening dissolve
            w.frame()
            if w.session.phase is HostPhase.RUNNING:
                break
        enter = lambda g: (session.ENTER,)                  # noqa: E731
        session._play(w, g, lambda g: session.ENTER, {"frame": enter, "train": enter,
                                                      None: enter})
        w.frames(60)                                        # the closing dissolve
    finally:
        pygame.quit()
        phone_chat._WARNED.clear()
    assert w.fatal == [] and g.finishes == [{"frame": "keep", "train": "station"}]
    assert [d.result for d in w.done()] == [{"frame": "keep", "train": "station"}]
    assert _warnings(caplog) == []

"""F27-4: the example game's puzzle room (F27 ``06``: AC-F27-24). AC-F27-23 (the docs) is in
``tests/test_docs.py``.

*Paper Lanterns* sends the player into the stall keeper's shed after the lantern stall
(``game/script/chapter1.vns``, ``festival_shed`` and ``shed_room``): ``define shed``, then
``minigame puzzle_room skippable room=shed state=shed_state into shed_state`` in the
``state`` loop, with a reaction to the chest's use. Every run passes the riverbank, so every
seed of the goldens reaches it. The nail sits right of the door, so it gets its own clicks
(in the design's attic the hook lies inside the door's rect, and the door gets them).
"""

import logging
import re
from pathlib import Path

import pygame

from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.minigames.bundled import puzzle_room
from engine.minigames.host import Phase
from engine.minigames.tables import PluginTables
from engine.runtime.codex import CodexIndex
from engine.runtime.commands import StartMinigame, StoryEnded
from engine.runtime.headless import run_headless
from engine.ui.nav import InputKind
from tests.fixtures.F27 import rooms
from tests.minigames.bundled import test_room_session as session
from tests.minigames.bundled.room_host import ENTER, ENTRY, HostR, click
from tests.runtime import corpus
from tests.runtime.stage_story import EXAMPLE, example_minigames, load_example

EXIT = {"action": "exit", "hotspot": "door", "item": None, "gone": []}
TAKE = {"action": "take", "hotspot": "nail", "item": "shed_key", "gone": ["nail"]}


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def _scene() -> tuple[str, str, str]:
    """The example's one room: (the room's name, the ``into`` variable, its file's text)."""
    found = []
    for path in sorted((EXAMPLE / "script").rglob("*.vns")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"^\s+minigame puzzle_room .*room=(\w+) state=(\w+) into (\w+)$",
                             text, re.M):
            assert m.group(2) == m.group(3)
            found.append((m.group(1), m.group(3), text))
    assert len(found) == 1, found
    return found[0]


def _session(w: HostR, start: StartMinigame, by: InputKind):
    g = w.open(None, cmd=start, by=by, frame=False)
    for _ in range(60):                                     # the opening dissolve
        w.frame()
        if w.session.phase is Phase.RUNNING:
            break
    return g


def _closing(w: HostR) -> None:
    for _ in range(60):
        if w.done():
            return
        w.frame()


def test_ac_f27_24_the_example_room(caplog, monkeypatch):
    # The scene: a define room, the state loop (state= and into the same variable, a jump
    # back to the line's label), and a reaction to a use.
    room, into, text = _scene()
    assert re.search(rf"^define {room} = \{{$", text, re.M)
    after = text[text.index(f"into {into}"):]
    label = re.findall(r"^label (\w+):$", text[:text.index(f"into {into}")], re.M)[-1]
    assert f"jump {label}" in after.split("\nlabel ")[0]
    assert re.search(rf'^\s+if {into}\["hotspot"\] == "\w+":\n\s+"', after, re.M)
    # Its images are in game/images.
    images = corpus.example_images()
    for name in ("bg festival_shed", "shed key", "shed candles"):
        assert f"images/{name.replace(' ', '/')}.png" in images, name
    # Headless, seeds 1–5 with the goldens' picks (AC-F23-62's run): every run ends, passes
    # through the room once (it leaves by the door), and logs nothing at WARNING or above.
    result = load_example()
    assert result.errors == () and result.warnings == ()
    caplog.set_level(logging.DEBUG)
    starts = {}
    for seed in corpus.EXAMPLE_SEEDS:
        inputs = corpus.example_inputs(seed, corpus.EXAMPLE_PICKS[seed])
        commands = run_headless(result.program, seed=seed, image_files=images, inputs=inputs,
                                dev=True, show_locked=True, minigames=example_minigames())
        assert commands[-1] == StoryEnded(), seed
        starts[seed] = [c for c in commands if type(c) is StartMinigame
                        and c.name == "puzzle_room"]
    assert all(len(found) == 1 for found in starts.values()) and _warnings(caplog) == []
    # Host R with the example's config, theme, images, and codex opens seed 1's room and
    # leaves by the door by keyboard, at 100% and at 150%, with no warning (W179, W180, and
    # W162 included: the host is in dev). By mouse, a click on the nail takes the key.
    (start,) = starts[1]
    paths = GamePaths.for_game(Path(EXAMPLE).resolve())
    config = load_config(paths)
    assert config.errors == [] and config.warnings == []
    cfg = config.config
    tables = PluginTables(cfg.theme.plugin, cfg.words.plugin, cfg.theme, dev=True)
    tables.check([ENTRY])
    monkeypatch.setattr(rooms, "HERE", paths.root)                # Host R reads game/
    monkeypatch.setattr(rooms, "image_file", lambda n: f"images/{n.replace(' ', '/')}.png")
    puzzle_room._WARNED.clear()
    pygame.init()
    try:
        w = HostR(config=cfg, tables=tables, index=CodexIndex.build(result.program))
        for scale in (1.0, 1.5):
            w.shell.painter.set_text_scale(lambda: scale)
            g = _session(w, start, InputKind.KEYS)
            assert w.images[0] == "bg festival_shed" and "shed key" in w.images
            for step in session.path_to(w, session.spot(g, "door")):
                w.frame(*session.ARROWS["keys"][step])
            assert session.focus(w) == "door", scale
            w.frame(*ENTER)
            _closing(w)
            assert w.fatal == [] and g.finishes == [EXIT], scale
            assert [d.result for d in w.done()] == [EXIT], scale
        w.shell.painter.set_text_scale(lambda: 1.0)
        g = _session(w, start, InputKind.MOUSE)
        x, y, wd, ht = session.spot(g, "nail").spot.rect
        w.frame(*click((x + wd // 2, y + ht // 2)))
        _closing(w)
    finally:
        pygame.quit()
        puzzle_room._WARNED.clear()
    assert w.fatal == [] and g.finishes == [TAKE]
    assert _warnings(caplog) == []

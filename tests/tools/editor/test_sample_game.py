"""F47 P1-G: the sample story and New game's "Start from" choice (``01-design.md`` PR-F47-25,
§6.4; ``04-technical.md`` §3.3; AC-F47-24).

One test: New game with the default template makes the sample (``engine/data/sample/``, copied
file for file with ``config.toml`` filled in), whose in-process check reports nothing (no
problem, no warning) and whose story plays headless to each of its two endings; its pictures
and sounds are the example game's own files; "empty" makes today's F45 starter."""

import hashlib
import tomllib
from pathlib import Path

from engine.core.paths import GamePaths, slugify
from engine.runtime.commands import PlayMusic, ShowMenu, StoryEnded
from engine.runtime.headless import run_headless
from engine.runtime.persistent import PersistentStore
from engine.script.loader import load_story
from engine.tools.editor import files, studiostate
from tests.tools.f45_games import result_of, run_job, tree

REPO = Path(__file__).resolve().parents[3]
SAMPLE = REPO / "engine" / "data" / "sample"
STARTER = REPO / "engine" / "data" / "starter"
SAMPLE_MAX_BYTES = 768 * 1024           # "a few hundred KB"

# Each sample picture or sound → the example game file it is a copy of (decision 2).
FROM_EXAMPLE = {
    "images/bg/river_dusk.png": "images/bg/river_dusk.png",
    "images/bg/bridge_night.png": "images/bg/bridge_night.png",
    "images/hana/happy.png": "images/hana/happy.png",
    "images/hana/sad.png": "images/hana/sad.png",
    "images/hana/happy_talk1.png": "images/hana/happy_talk1.png",       # F38 frames
    "images/hana/sad_blink1.png": "images/hana/sad_blink1.png",
    "images/hana/sad_talk1.png": "images/hana/sad_talk1.png",
    "images/daichi/smile.png": "images/daichi/smile.png",
    "images/daichi/grin.png": "images/daichi/grin.png",
    "audio/music/lantern_walk.wav": "audio/bgm/lantern_walk.wav",
    "audio/sound/chime.wav": "audio/sfx/chime.wav",
    "audio/blips/hana.wav": "audio/blips/hana.wav",
    "audio/blips/daichi.wav": "audio/blips/daichi.wav",
}


def _play(game: Path, pick: int) -> tuple[list, tuple[str, ...]]:
    story = load_story(GamePaths.for_game(game))
    assert not story.errors and not story.warnings
    images = [p.relative_to(game).as_posix() for p in (game / "images").rglob("*.png")]
    store = PersistentStore(identity_scheme=story.program.identity_scheme)
    # A first run stops at the one menu; the second answers its lines, then picks.
    first = run_headless(story.program, seed=1, image_files=images, persistent=store)
    lines = sum(1 for c in first if type(c).__name__ == "Say")
    assert isinstance(first[-1], ShowMenu)
    store = PersistentStore(identity_scheme=story.program.identity_scheme)
    commands = run_headless(story.program, seed=1, image_files=images, persistent=store,
                            inputs=["advance"] * lines + [f"choose {pick}"])
    return commands, store.unlocked("ending")


def test_ac_f47_24_new_game_sample_and_empty(tmp_path):
    name = "Rin's Lanterns"
    game = tmp_path / name
    assert files.new_game(game) == game.absolute()          # the default is the sample

    # Copied file for file; config.toml filled in from the folder name, as the starter's.
    made = {ref: data for ref, data in tree(game).items() if data is not None}
    expected = files.template_files(files.TEMPLATE_SAMPLE, name)
    assert set(made) == set(expected) | {"config.toml", ".studio/studio.json"}
    assert all(made[ref] == data for ref, data in expected.items())
    shipped = {p.relative_to(SAMPLE).as_posix() for p in SAMPLE.rglob("*") if p.is_file()}
    assert shipped - {"config.toml.in"} == set(expected) - {"config.toml"}
    config = tomllib.loads(made["config.toml"].decode("utf-8"))
    assert config["game"] == {"id": slugify(name), "title": name, "version": "0.1.0"}
    assert studiostate.read_state(game) == studiostate.StudioState(guide_open=True,
                                                                   sample=True)

    # Small, and every picture and sound is the example game's own (CC0 audio, its art).
    assert sum(len(d) for d in expected.values()) <= SAMPLE_MAX_BYTES
    media = {ref for ref in expected if ref.startswith(("images/", "audio/"))}
    assert media == set(FROM_EXAMPLE)
    for ref, source in FROM_EXAMPLE.items():
        assert made[ref] == (REPO / "game" / source).read_bytes(), ref
        digest = hashlib.sha256(made[ref]).hexdigest()
        assert f"File: {ref}\n" in made["LICENSES.txt"].decode() and digest in made[
            "LICENSES.txt"].decode(), ref
    main = made["script/main.vns"].decode("utf-8")
    assert main.splitlines()[6] == 'include "database.vns"'
    assert made["script/database.vns"].decode().startswith(
        "# Made in Studio's Database. You can also edit it by hand.\n")

    # The headless check (load and launch) reports nothing at all.
    events = run_job(GamePaths.for_game(game))
    assert [e for e in events if e["event"] == "problems"] == []
    done = events[-1]
    assert done["event"] == "done" and done["loaded"] and done["problems"] == 0
    names = {kind: {e.name for e in entries}
             for kind, entries in result_of(events).names.items()}
    assert names["character"] == {"hana", "daichi"}
    assert names["ending"] == {"lantern", "next_year"}
    assert {"bg river_dusk", "bg bridge_night", "hana happy", "daichi grin"} <= names["image"]

    # It plays to the end both ways: music, a choice, and an ending each.
    for pick, ending in ((1, "lantern"), (2, "next_year")):
        commands, endings = _play(game, pick)
        assert isinstance(commands[-1], StoryEnded), pick
        assert endings == (ending,)
        assert any(isinstance(c, PlayMusic) for c in commands)

    # "empty" is today's starter: config.toml and script/main.vns, the group folders, and
    # Studio's state (the Guide open, not a sample game).
    empty = tmp_path / "empty game"
    assert files.new_game(empty, template=files.TEMPLATE_EMPTY) == empty.absolute()
    got = {ref: data for ref, data in tree(empty).items() if data is not None}
    assert got == {"config.toml": files.starter_config("empty game"),
                   "script/main.vns": (STARTER / "script" / "main.vns").read_bytes(),
                   ".studio/studio.json": studiostate.encode_state(
                       studiostate.StudioState(guide_open=True))}
    assert {ref for ref, data in tree(empty).items() if data is None} == {
        ".studio", *(g.folder for g in files.ASSET_GROUPS)}
    assert [key for key, _ in files.TEMPLATES] == [files.TEMPLATE_SAMPLE,
                                                   files.TEMPLATE_EMPTY]

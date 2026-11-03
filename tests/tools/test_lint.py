"""F41 P2: the linter's rules (``engine/tools/lint.py``; F41 ``04-technical.md`` §7.2).

Each game runs as the check child will (P3): config, load, launch (or not), P1's use rows
(``tools/check.py``), then ``lint.findings``. Tables: AC-F41-02 (scenes not reached),
AC-F41-04 (never listed), AC-F41-06 (W238 only in full checks; every other rule in both),
and the example and sample games (no findings: nothing in them is unused or unreached)."""

import shutil
from pathlib import Path

import pytest

from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.runtime.gamesources import audio_files, game_has, image_source
from engine.runtime.launch import LaunchJob
from engine.script import LoadOptions, load_story
from engine.script.flowgraph import FlowOptions
from engine.tools import check as ck
from engine.tools import lint
from engine.tools.editor import cleanup
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)

REPO = Path(__file__).resolve().parents[2]
STUDIO = REPO / "tests" / "fixtures" / "F45" / "games" / "studio"
PNG = (STUDIO / "images" / "bg" / "room.png").read_bytes()
OGG = (STUDIO / "audio" / "bgm" / "theme.ogg").read_bytes()
MAIN = "script/main.vns"


def _game(root: Path, script: str, *, config: str = "", files: tuple[str, ...] = ()) -> Path:
    """A game folder: config.toml, script/main.vns, and ``files`` (``.png`` and ``.ogg``
    get real bytes)."""
    game = root / "game"
    (game / "script").mkdir(parents=True)
    (game / "config.toml").write_text('[game]\ntitle = "T"\n' + config, encoding="utf-8")
    (game / "script" / "main.vns").write_text(script, encoding="utf-8")
    for ref in files:
        path = game / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(OGG if ref.endswith(".ogg") else PNG)
    return game


def _lint(game: Path, *, launch: bool = True) -> tuple[lint.Finding, ...]:
    paths = GamePaths.for_game(game)
    config = load_config(paths).config
    loaded = load_story(paths, LoadOptions(
        collect_todos=True, position_names=frozenset(config.stage.positions),
        flowchart=FlowOptions.from_config(config.flowchart),
        username_fallback=config.meta.username_fallback,
        style_names=frozenset(config.style)))
    assert not loaded.errors, loaded.errors
    program = loaded.program
    result = namespace = None
    if launch:
        job = LaunchJob(program, dev=True, game_has=game_has(paths),
                        images=image_source(paths), game_root=paths.root, persistent=None,
                        audio=audio_files(paths, config.audio.loop_start))
        while not job.step():
            pass
        assert not job.result.errors, job.result.errors
        result, namespace = job.result, job.G
    ctx = ck.CheckContext(paths, config, program, result, namespace)
    audio = [name for name, _file, _line in ck._audio_names(ctx)]
    return lint.findings(program, config, paths, ck._index_of(ctx), audio, namespace,
                         ck._story_uses(ctx), ck._config_text(ctx))


def _rows(found: tuple[lint.Finding, ...], *codes: str) -> list[tuple]:
    return [(f.code, f.name, f.file, f.line) for f in found if not codes or f.code in codes]


# --- AC-F41-02: scenes not reached ----------------------------------------------------------

GRAPHS = {
    "start only": ("label start:\n    \"Hi.\"\n", []),
    "jump": ("label start:\n    jump a\nlabel a:\n    \"A.\"\nlabel b:\n    \"B.\"\n",
             [("b", 5)]),
    "call": ("label start:\n    call a\n    \"Back.\"\nlabel a:\n    return\n"
             "label b:\n    return\n", [("b", 6)]),
    "choice": ("label start:\n    menu:\n        \"Go\":\n            jump a\n"
               "        \"Stay\":\n            \"You stay.\"\nlabel a:\n    \"A.\"\n"
               "label b:\n    \"B.\"\n", [("b", 9)]),
    "chain through an unreached label": (
        "label start:\n    \"Hi.\"\nlabel old:\n    call older\n    jump oldest\n"
        "label older:\n    return\nlabel oldest:\n    \"Z.\"\n",
        [("old", 3), ("older", 6), ("oldest", 8)]),
    "replay scene is a start": (
        "lock replay epi \"Epilogue\"\nlabel start:\n    \"Hi.\"\nlabel epi:\n    jump epi2\n"
        "label epi2:\n    \"E.\"\nlabel lost:\n    \"L.\"\n", [("lost", 8)]),
    "start reached again": ("label start:\n    jump a\nlabel a:\n    jump start\n", []),
}


@pytest.mark.parametrize("name", list(GRAPHS))
def test_ac_f41_02_scenes_not_reached(tmp_path, name):
    """AC-F41-02: W237 lists exactly the labels no jump, call or choice reaches from start or
    a scene replay's label, at their label lines; start is never listed."""
    script, expected = GRAPHS[name]
    found = _lint(_game(tmp_path, script), launch=False)
    assert [(n, line) for code, n, file, line in _rows(found, "W237")] == expected
    assert all(f.file == MAIN and f.kind == "unreached" for f in found if f.code == "W237")


# --- AC-F41-04: never listed ----------------------------------------------------------------

NEVER = """\
define hana = Character("Hana")
label start:
    scene bg room with dissolve
    show hana happy at left
    "Narration."
    hana "Hi."
"""
NEVER_CONFIG = "[stage.positions]\nleft = 300\n"
NEVER_FILES = ("images/bg/room.png", "images/hana/happy.png",
               "images/bg/room_copy.png", "images/bg/park_backup.png",   # backups
               "images/bg/old_park.png",                                 # not a backup word
               "audio/bgm/theme.ogg", "audio/bgm/theme~.ogg", "audio/bgm/theme copy.ogg",
               "gui/button.png", "fonts/logo.png", "minigames/art.png", "files/note.png",
               "masks/iris.png", "gui/click.ogg", "files/song.ogg")


def test_ac_f41_04_never_listed(tmp_path):
    """AC-F41-04: built-in positions (center, right, and left even when config.toml moves it)
    and transitions, ``black``, ``narrator``, files outside ``images/`` and ``audio/``, and
    backup pictures and sounds are never listed. ``bg old_park`` is (decision 6), and
    ``theme.ogg`` is, since nothing plays it."""
    found = _lint(_game(tmp_path, NEVER, config=NEVER_CONFIG, files=NEVER_FILES))
    assert _rows(found) == [
        ("W239", "bg old_park", "images/bg/old_park.png", None),
        ("W240", "bgm/theme.ogg", "audio/bgm/theme.ogg", None),
    ]
    assert [lint.is_backup_name(ref) for ref in (
        "a/b~.png", "room_copy.png", "Backup2.ogg", "x.ogg~", "old_park.png", "draft.png",
        "copyright.png")] == [True, True, True, True, False, False, False]


# --- AC-F41-06: W238 only in full checks ----------------------------------------------------

EVERY = """\
define hana = Character("Hana")
define kenji = Character("Kenji")
define slow = Dissolve(0.5)
define quick = Fade(0.2)
define max_tries = 3
define shown_tries = 2
default trust = 0
default lantern_count = 0
points courage 0 to 10
points spare daichi_m 0 to 5 start 2
label start:
    scene bg room with slow
    show hana happy at far
    hana "Hi {var=shown_tries}."
    $ trust += 1
    points courage += 1
"""
EVERY_CONFIG = "[stage.positions]\nfar = 100\nnear = [300, 600]\n"
EVERY_FILES = ("images/bg/room.png", "images/bg/sky.png", "images/hana/happy.png",
               "audio/music/old_theme.ogg")
EVERY_FOUND = [
    ("W239", "bg sky", "images/bg/sky.png", None),
    ("W240", "music/old_theme.ogg", "audio/music/old_theme.ogg", None),
    ("W241", "lantern_count", MAIN, 8),
    ("W242", "near", "config.toml", 5),
    ("W242", "quick", MAIN, 4),
    ("W242", "max_tries", MAIN, 5),
    ("W242", "daichi_m", MAIN, 10),
    ("W242", "spare", MAIN, 10),
]


@pytest.mark.parametrize("launch", [True, False], ids=["full", "no-launch"])
def test_ac_f41_06_characters_only_in_full_checks(tmp_path, launch):
    """AC-F41-06: a full check gives W238 for the character nothing names; ``--no-launch``
    gives every other code the same (one unused thing of each other kind, each at its
    declaration or file), and its names rows leave ``unused_character`` out."""
    found = _lint(_game(tmp_path, EVERY, config=EVERY_CONFIG, files=EVERY_FILES),
                  launch=launch)
    w238 = [("W238", "kenji", MAIN, 2)] if launch else []
    assert _rows(found) == w238 + EVERY_FOUND
    assert {f.name: f.args[0] for f in found if f.code == "W242"} == {
        "near": "position", "quick": "transition", "max_tries": "define",
        "daichi_m": "meter", "spare": "meter"}
    rows = lint.rows_by_kind(found, characters=launch)
    assert ("unused_character" in rows) is launch
    assert set(rows) | {"unused_character"} == set(lint.LINT_KINDS)
    # Clean up's kind table is lint's (Studio can't import tools.lint).
    assert {kind: (info.code, info.word) for kind, info in cleanup.KINDS.items()} \
        == dict(lint.LINT_KINDS)


# --- The example game and the sample game: nothing to clean up --------------------------------

@pytest.mark.parametrize("which", ["example", "sample"])
def test_example_and_sample_games_have_no_findings(tmp_path, which):
    """The example game (``game/``) and F47's sample game (``engine/data/starter``) give no
    findings in a full check: every scene is reached and everything declared is used (the
    nine false "unused" entries of 01 §2 stay fixed; P3's AC-F41-14 pins the CLI output)."""
    if which == "example":
        game = REPO / "game"
    else:
        game = tmp_path / "starter"
        shutil.copytree(REPO / "engine" / "data" / "starter", game)
        (game / "config.toml.in").rename(game / "config.toml")
    assert _rows(_lint(game)) == []

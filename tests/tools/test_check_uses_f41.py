"""F41 P1: the check's use rows count every kind of use (F41 ``04-technical.md`` §7.1;
AC-F41-07), so Database's "Used in N lines" stops calling used things "Not used yet".

The table test runs one fixture through the wire (``launch=False`` and a full check: the
rows are syntactic, so both agree). The example game's test pins its "used" verdicts to a
reviewed list: the nine false "Not used yet" entries the design measured (01 §2) are used,
and the only names left without a use row are the built-ins (``black``, ``center``), which
are never unused by rule (PR-F41-04)."""

import re
import shutil
from pathlib import Path

import pytest

from engine.core.constants import BUILTIN_POSITIONS
from engine.runtime.images import BLACK
from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from tests.tools.f45_games import check, studio

EXAMPLE = Path(__file__).resolve().parents[2] / "game"
MAIN = "script/main.vns"

SCRIPT = """\
define hana = Character("Hana", image_tag="girl")
define slow = Dissolve(0.5)
define colors = ["red", "blue"]
define shed = {"background": "bg room", "sound": "audio/sfx/click.ogg", "hotspots": {"k": {"rect": [0, 0, 9, 9], "label": "K", "take": "key", "image": "Props Key"}}}
define spare = 3
define picks = spare + 1
default trust = 0
default result = None
default start_name = ""
default seen = trust
lock gallery cg one "One":
    cg one_alt
lock item key "Key" image items key
lock replay bonus "Bonus" image bg sky:
    start_name = "Hana"
lock achievement fan "Fan" "A fan." image icons fan when trust > 1 and colors
lock track theme "Theme" file "bgm/theme.ogg" open
label start:
    scene bg room with slow
    hana happy "Hi, {var=colors}."
    $ trust = len(colors)
    minigame puzzle_room room=shed into result
    jump bonus
label bonus:
    "The end."
"""
CONFIG = """\
[game]
title = "My Game"

[title]
music = "bgm/two.ogg"

[notes]
cover = "BG Photo"
"""
PICTURES = ("cg/one", "cg/one_alt", "items/key", "icons/fan", "props/key", "girl/happy",
            "girl/happy_blink1", "girl/sad", "girl/sad_blink1")
SOUNDS = ("sfx/click.ogg", "bgm/two.ogg", "sfx/spare.ogg")


def _game(tmp_path: Path) -> Path:
    game = studio(tmp_path)
    picture = (game / "images" / "hana" / "happy.png").read_bytes()
    for name in PICTURES:
        path = game / "images" / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(picture)
    sound = (game / "audio" / "bgm" / "theme.ogg").read_bytes()
    for name in SOUNDS:
        path = game / "audio" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(sound)
    (game / "script" / "main.vns").write_text(SCRIPT, encoding="utf-8")
    (game / "config.toml").write_text(CONFIG, encoding="utf-8")
    return game


@pytest.mark.parametrize("launch", [False, True], ids=["no-launch", "launch"])
def test_ac07_use_rows_count_every_kind_of_use(tmp_path, launch):
    """AC-F41-07: gallery entries and versions, codex pictures, replay pictures, minigame
    picture and sound arguments (through the define they name), F38 frames of used looks,
    config text values, ``define_use``, replay starting values, achievement icons and
    ``when`` code, tracks, ``into``, and Say words through ``image_tag``."""
    result = check(_game(tmp_path), launch=launch)
    names = result.names
    assert result.loaded and not [p for p in result.problems if p.severity == "error"]

    def pictures(name: str) -> tuple:
        return db.use_places(names, db.BACKGROUND, name)

    assert pictures("cg one") == pictures("cg one_alt") == ((MAIN, 11),)   # gallery + version
    assert pictures("items key") == ((MAIN, 13),)                       # codex picture
    assert pictures("bg sky") == ((MAIN, 14),)                          # replay picture
    assert pictures("icons fan") == ((MAIN, 16),)                       # achievement icon
    assert pictures("props key") == ((MAIN, 22),)                       # minigame, via shed
    assert pictures("bg room") == ((MAIN, 19), (MAIN, 22))              # scene + minigame
    # The gallery's "never shows" line reads only the lines that show it on stage.
    texts = {MAIN: SCRIPT}
    assert db.story_places(names, texts, db.BACKGROUND, "cg one") == ()
    assert db.story_places(names, texts, db.BACKGROUND, "BG Room") == ((MAIN, 19), (MAIN, 22))
    assert db.story_places(names, texts, db.BACKGROUND, "bg photo") == ()   # config only
    assert pictures("girl happy") == ((MAIN, 20),)                      # Say via image_tag
    assert pictures("hana happy") == ()                                 # not the define name
    assert pictures("girl happy_blink1") == ((MAIN, 20),)               # frame of a used look
    assert pictures("girl sad_blink1") == ()                            # frame of an unused one
    assert pictures("bg photo") == (("config.toml", 8),)                # config value, any case

    def sounds(name: str) -> tuple:
        return db.use_places(names, db.SOUND, name)

    assert sounds("bgm/theme.ogg") == ((MAIN, 17),)                     # music-room track
    assert sounds("sfx/click.ogg") == ((MAIN, 22),)                     # minigame, "audio/…"
    assert sounds("bgm/two.ogg") == (("config.toml", 5),)               # config value
    assert sounds("sfx/spare.ogg") == ()
    # The music room's "never played" line: a track's own line doesn't play it.
    assert db.story_places(names, texts, db.SOUND, "bgm/theme.ogg") == ()

    def variable(name: str) -> tuple:
        return db.use_places(names, dec.VARIABLE, name)

    assert variable("result") == ((MAIN, 22),)                          # minigame into
    assert variable("start_name") == ((MAIN, 14),)                      # replay start value
    assert variable("trust") == ((MAIN, 21), (MAIN, 10), (MAIN, 16))    # code, default, when
    assert variable("seen") == ()                                       # its own default

    defines = {(row.name, row.file, row.line) for row in names["define_use"]}
    assert defines == {("colors", MAIN, 20), ("colors", MAIN, 21), ("colors", MAIN, 16),
                       ("shed", MAIN, 22), ("spare", MAIN, 6)}          # not picks, own name
    assert db.use_places(names, dec.TRANSITION, "slow") == ((MAIN, 19),)
    assert db.use_places(names, dec.CHARACTER, "hana") == ((MAIN, 20),)
    assert [(row.name, row.file, row.line) for row in names["replay_scene"]] == [
        ("bonus", MAIN, 14)]
    assert all(row.file is not None for kind in ("define_use", "replay_scene")
               for row in names[kind])


class _Row:
    def __init__(self, name: str, file: str | None, line: int | None) -> None:
        self.name, self.file, self.line = name, file, line


def test_ac07_transitions_count_define_uses():
    """F41 decision 9: a transition's Database count also takes ``define_use`` rows (a
    transition made by a function reads as a plain define), distinct lines across both."""
    rows = {"transition_use": [_Row("fade_in", MAIN, 4)],
            "define_use": [_Row("fade_in", MAIN, 7), _Row("fade_in", MAIN, 4)]}
    assert db.use_places(rows, dec.TRANSITION, "fade_in") == ((MAIN, 4), (MAIN, 7))
    assert db.use_places(rows, dec.VARIABLE, "fade_in") == ()


# The example game's reviewed verdicts (AC-F41-07). The nine names the F41 design measured
# as falsely "Not used yet" (01 §2), each with the places that now use it.
EXAMPLE_FALSE_UNUSED = {
    "bg festival_shed": (("script/chapter1.vns", 172), (MAIN, 147)),   # minigame room, replay
    "shed candles": (("script/chapter1.vns", 172),),                   # minigame room hotspot
    "shed key": (("script/chapter1.vns", 172),),                       # minigame room hotspot
    "items lantern": ((MAIN, 101), (MAIN, 176)),                       # codex item, achievement
    "hana sad_blink1": (("script/chapter1.vns", 26), ("script/chapter1.vns", 49),
                        ("script/endings.vns", 26)),                   # F38 frames of hana sad
    "hana sad_talk1": (("script/chapter1.vns", 26), ("script/chapter1.vns", 49),
                       ("script/endings.vns", 26)),
}
# Only the built-ins have no use row, and they are never "unused" (PR-F41-04).
EXAMPLE_NO_USE_ROW = {"image": ["black"], "position": ["center"]}


def _unused(names: db.Names, kind: str, use: str, fold: bool = False) -> list[str]:
    def key(name: str) -> str:
        return name.casefold() if fold else name
    used = {key(row.name) for row in names.get(use, ())}
    return sorted({row.name for row in names.get(kind, ()) if key(row.name) not in used})


def test_ac07_example_game_uses_match_the_reviewed_list():
    """AC-F41-07 on the example game: every picture, sound, variable, character, defined
    transition, position, meter and define has a use row except the built-ins, and the
    design's nine false "Not used yet" entries now say where they are used."""
    names = check(EXAMPLE).names
    no_use = {kind: found for kind, found in (
        ("image", _unused(names, "image", "image_use", fold=True)),
        ("audio", _unused(names, "audio", "audio_use")),
        ("variable", _unused(names, "variable", "variable_use")),
        ("character", _unused(names, "character", "character_use")),
        ("transition", [n for n in _unused(names, "transition", "transition_use")
                        if any(r.name == n and r.file for r in names["transition"])]),
        ("position", _unused(names, "position", "position_use")),
        ("meter", _unused(names, "meter", "meter_use"))) if found}
    assert no_use == EXAMPLE_NO_USE_ROW
    assert no_use["image"] == [BLACK] and set(no_use["position"]) <= set(BUILTIN_POSITIONS)
    for name, places in EXAMPLE_FALSE_UNUSED.items():
        assert db.use_places(names, db.BACKGROUND, name) == places, name
    # Talking frames share their look's lines (hana happy_talk1 is hana happy's frame).
    happy = db.use_places(names, db.BACKGROUND, "hana happy")
    assert happy and db.use_places(names, db.BACKGROUND, "hana happy_talk1") == happy
    # Every define is named somewhere (a character speaks, a transition plays, the rest
    # are minigame data or code).
    defines = {name for path in sorted((EXAMPLE / "script").rglob("*.vns"))
               for name in re.findall(r"(?m)^define (\w+)", path.read_text("utf-8"))}
    used = {row.name for kind in ("character_use", "transition_use", "define_use")
            for row in names[kind]}
    assert defines and defines <= used, sorted(defines - used)
    assert [row.name for row in names["replay_scene"]] == [
        "bridge", "shed_room", "river_end", "festival_end", "promise"]


def test_ac07_builtin_positions_say_built_in(tmp_path):
    """F41 decision 7: a built-in position nothing uses says "Built-in" in the Database
    form (not "Not used yet"); a used one keeps its count, an author's keeps "Not used
    yet"."""
    game = studio(tmp_path)
    (game / "script" / "main.vns").write_text(
        "label start:\n    show hana happy at left\n", encoding="utf-8")
    names = check(game, launch=False).names
    entries = {e.name: e.used_text for e in db.position_entries(
        "[stage.positions]\nby_the_rail = 560\n", names)}
    assert entries == {"left": "Used in 1 line", "center": db.BUILT_IN,
                       "right": db.BUILT_IN, "by_the_rail": db.NOT_USED}


def test_ac07_no_config_or_audio_still_counts(tmp_path):
    """A game without config.toml values or ``audio/`` still gets its script rows (the
    config and audio inputs are optional; a broken config.toml counts nothing)."""
    game = studio(tmp_path)
    shutil.rmtree(game / "audio")
    (game / "config.toml").write_text("[title\nmusic = 'x'\n", encoding="utf-8")
    (game / "script" / "main.vns").write_text(
        "label start:\n    scene bg room\n", encoding="utf-8")
    names = check(game, launch=False).names
    assert db.use_places(names, db.BACKGROUND, "bg room") == ((MAIN, 2),)
    assert all(row.file != "config.toml" for kind in ("image_use", "audio_use")
               for row in names.get(kind, ()))

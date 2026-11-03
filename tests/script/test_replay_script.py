"""F36 W1: scene replays' script side (``script/replay.py``, ``program.py``, ``checks.py``):
AC-F36-01 (the parsed declaration: scene, title, image, ``to``, starting values, script order;
``replay`` and ``to`` stay names; the in-label lines are F19's ``Lock``), AC-F36-03 (E349's
over-500 form; its twice form is a row of ``tests/fixtures/F02/messages/cases.toml``, as are
every E348, E350, E351 and E352 text: AC-F36-02, 04, 05, 06) and AC-F36-14 (the tile
picture ``build_replays`` finds)."""

from engine.script import LoadOptions, load_story
from engine.script.identity import walk_block
from engine.script.routes import Lock
from tests.runtime.menu_story import write_game

REPLAYS = ('lock replay festival "The {{Festival}"\n'
           'include "extras.vns"\n'
           'lock replay river "By the River" image cg river to fireworks:\n'
           '    coins = 3\n'
           '    player_name = "Aiko"  # the name the scene needs\n'
           '    brave = True\n'
           '    luck = -0.5\n'
           '    met = None\n')
EXTRAS = 'lock  replay  stall   "The Stall"  to  festival\n'


def test_ac01_replay_declarations_and_names_still_free(tmp_path):
    story = (REPLAYS + "default coins = 0\ndefault player_name = \"\"\ndefault brave = False\n"
             "default luck = 0.0\ndefault met = 1\ndefault replay = 1\ndefault to = 2\n"
             "label start:\n    $ replay += to\n    unlock replay river\n    jump festival\n"
             "label festival:\n    lock replay festival\n    return\n"
             "label river:\n    return\nlabel fireworks:\n    return\n"
             "label stall:\n    return\n")
    root = tmp_path / "g"
    paths = write_game(root, story)
    (root / "script" / "extras.vns").write_text(EXTRAS, encoding="utf-8")
    result = load_story(paths, LoadOptions(dev=False))
    assert result.errors == (), [e.format() for e in result.errors]
    rows = [(r.label, r.title, r.image, r.to, r.values, r.sid, r.file, r.line)
            for r in result.program.replays]
    assert rows == [                                      # reading order (includes after)
        ("festival", "The {Festival}", None, None, (), "replay:festival", "script/main.vns", 1),
        ("river", "By the River", "cg river", "fireworks",
         (("coins", 3), ("player_name", "Aiko"), ("brave", True), ("luck", -0.5),
          ("met", None)), "replay:river", "script/main.vns", 3),
        ("stall", "The Stall", None, "festival", (), "replay:stall", "script/extras.vns", 1)]
    assert [type(v) for _, v in result.program.replays[1].values] == [int, str, bool, float,
                                                                       type(None)]
    # The in-label lines are F19's Lock nodes, so F19's run_lock executes them.
    locks = [(s.kind, s.name, s.unlock) for label in result.program.labels.values()
             for s, _ in walk_block(label.block) if isinstance(s, Lock)]
    assert locks == [("replay", "river", True), ("replay", "festival", False)]


def test_ac03_more_than_500_replays(tmp_path):
    labels = "".join(f"label s{i}:\n    return\n" for i in range(501))
    many = "".join(f'lock replay s{i} "S"\n' for i in range(501))
    result = load_story(write_game(tmp_path / "many", many + "label start:\n    return\n"
                                   + labels), LoadOptions(dev=False))
    assert [e.format() for e in result.errors] == [
        "this story has 501 replays; the engine allows 500."]
    fine = "".join(f'lock replay s{i} "S"\n' for i in range(500))
    assert load_story(write_game(tmp_path / "fine", fine + "label start:\n    return\n"
                                 + labels), LoadOptions(dev=False)).errors == ()


def test_ac14_tile_picture(tmp_path):
    story = ('lock replay drawn "Drawn" image cg festival\n'     # image wins; kept as declared
             'lock replay nested "Nested"\n'
             'lock replay plain "Plain"\n'
             'lock replay none "None"\n'
             "label start:\n    return\n"
             "label drawn:\n    scene bg night\n    return\n"
             "label nested:\n    show hana\n    if True:\n        scene bg river\n"
             "    scene bg day\n    return\n"
             "label plain:\n    scene\n    scene bg dusk with dissolve\n    return\n"
             "label none:\n    call plain\n    show hana\n    return\n")
    result = load_story(write_game(tmp_path / "g", story), LoadOptions(dev=False))
    assert result.errors == (), [e.format() for e in result.errors]
    assert [(r.label, r.image, r.tile_picture) for r in result.program.replays] == [
        ("drawn", "cg festival", "bg night"),        # the page shows image first (P2)
        ("nested", None, "bg river"),                # the label's own lines, nested ones too
        ("plain", None, "bg dusk"),                  # a scene with no picture is passed over
        ("none", None, None)]                        # a called label isn't looked into

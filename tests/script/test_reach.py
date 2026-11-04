"""What a scene needs before the story can get there (``script/reach.py``): ways in with
their conditions, the lines that set what they read, and scenes no playthrough reaches."""

import textwrap

from engine.core.paths import GamePaths
from engine.script.loader import load_story
from engine.script.reach import analyze
from engine.tools.check import reach_rows
from engine.tools.lint import starts_of

STORY = """\
default has_key = False
default trust = 0

label start:
    menu:
        "Go to the shed":
            jump shed
        "Go to the river":
            jump river

label shed:
    $ has_key = True
    $ trust += 1
    jump hallway

label river:
    jump hallway

label hallway:
    menu:
        "Unlock the door" if has_key:
            jump vault
        "Walk on":
            jump yard

label yard:
    $ has_key = False
    if has_key:
        jump secret
    elif trust >= 5:
        jump friend
    else:
        jump hallway

label vault:
    return

label secret:
    return

label friend:
    return
"""


def _program(tmp_path, text=STORY):
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "main.vns").write_text(textwrap.dedent(text), encoding="utf-8")
    result = load_story(GamePaths.for_game(tmp_path))
    assert result.program is not None
    return result.program


def test_needs_setters_and_blocked_scenes(tmp_path):
    program = _program(tmp_path)
    found = analyze(program, starts_of(program))
    vault = found["vault"]
    assert vault.blocked is None
    assert [(w.src, w.choice, w.needs, w.possible) for w in vault.ways] == [
        ("hallway", "Unlock the door", ("has_key",), True)]
    assert {(s.scene, s.text) for s in vault.setters} == {
        (None, "default has_key = False"), ("shed", "has_key = True"),
        ("yard", "has_key = False")}
    secret = found["secret"]
    assert secret.blocked == ("No playthrough can reach this scene. From yard, it needs "
                              "has_key, but has_key is always False there.")
    assert not secret.ways[0].possible
    friend = found["friend"]                # an elif needs every earlier branch false
    assert friend.ways[0].needs == ("not has_key", "trust >= 5")
    assert friend.blocked is not None and "trust is only 0 or 1 there" in friend.blocked
    assert "hallway" in found and found["hallway"].blocked is None   # else: no condition
    assert "start" not in found and "shed" not in found


def test_what_it_cant_follow_counts_as_possible(tmp_path):
    program = _program(tmp_path, """\
        default has_key = False

        label start:
            $ has_key = compute()
            if has_key:
                jump vault
            $ items.append("x")
            if "x" in items:
                jump shed
            return

        label vault:
            return

        label shed:
            return
        """)
    found = analyze(program, starts_of(program))
    assert found["vault"].blocked is None and found["vault"].ways[0].possible
    assert found["shed"].blocked is None


def test_a_call_makes_what_the_called_scene_sets_unknown(tmp_path):
    program = _program(tmp_path, """\
        default door = "shut"

        label start:
            call open_it
            if door == "open":
                jump inside
            return

        label open_it:
            $ door = "open"
            return

        label inside:
            return
        """)
    assert analyze(program, starts_of(program))["inside"].blocked is None


def test_the_check_rows(tmp_path):
    program = _program(tmp_path)
    rows = reach_rows(program)
    kinds = {(scene, kind) for scene, kind, *_ in rows}
    assert ("secret", "blocked") in kinds and ("vault", "way") in kinds
    assert ("vault", "set") in kinds and ("vault", "blocked") not in kinds
    way = next(r for r in rows if r[0] == "vault" and r[1] == "way")
    assert way[2] == 'From hallway ("Unlock the door"): needs has_key'
    assert way[3] == "script/main.vns" and isinstance(way[4], int)

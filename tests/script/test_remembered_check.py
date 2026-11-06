"""First-game fix (2026-11-06): W320, a remembered variable's name used without
``persistent.`` (``engine/script/remembered.py``), found by the load so ``engine check``,
``engine lint`` and Studio's Problems list it with file and line."""

from engine.script.loader import LoadOptions, load_story
from tests.runtime.menu_story import write_game

DATABASE = "default persistent.knows_recipe = False\ndefault coins = 0\n"
STORY = '''include "database.vns"

label start:
    menu:
        "Ask about the recipe" if knows_recipe:
            "She smiles."
        "Leave":
            $ knows_recipe = True
    $ coins = sum(knows_recipe for knows_recipe in [1, 2])
    $ bonus = (lambda knows_recipe: knows_recipe)(1)
    if persistent.knows_recipe and coins:
        "Remembered."
    $ knows_recipe += 1
    "End."
'''


def _warnings(root, story=STORY, database=DATABASE):
    paths = write_game(root, story)
    (root / "script" / "database.vns").write_text(database, encoding="utf-8")
    loaded = load_story(paths, LoadOptions())
    assert not loaded.errors, loaded.errors
    return [w for w in loaded.warnings if w.code == "W320"]


def test_plain_uses_of_a_remembered_name_warn_at_each_line(tmp_path):
    found = _warnings(tmp_path)
    assert [(w.file, w.line) for w in found] == [
        ("script/main.vns", 5), ("script/main.vns", 8), ("script/main.vns", 13)]
    read, sets, change = (w.message for w in found)
    assert read == ("knows_recipe is remembered across playthroughs (default "
                    "persistent.knows_recipe, script/database.vns, line 1), so write "
                    "persistent.knows_recipe here. Plain knows_recipe is a different variable "
                    "that nothing gives a value, so the story stops when this line reads it.")
    assert sets.endswith("Plain knows_recipe is a different variable, so this line leaves "
                         "the remembered value as it was.")
    assert change.endswith("so the story stops when this line reads it.")     # += reads


def test_no_warning_when_the_plain_name_is_its_own_variable(tmp_path):
    assert _warnings(tmp_path, database=DATABASE + "default knows_recipe = 0\n") == []
    fixed = STORY.replace("if knows_recipe", "if persistent.knows_recipe").replace(
        "$ knows_recipe", "$ persistent.knows_recipe")
    assert _warnings(tmp_path / "fixed", story=fixed) == []

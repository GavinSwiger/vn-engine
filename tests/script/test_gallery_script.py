"""F34 W1: the gallery's script side (``script/gallery.py``, ``program.py``, ``checks.py``):
AC-F34-01, 03 (the over-500 form and a cross-file twice; the message rows of AC-F34-02 to
05 are in ``tests/fixtures/F02/messages/cases.toml``), and 14 (``cg`` is no longer reserved)."""

from engine.core.paths import GamePaths
from engine.runtime.images import ImageSource
from engine.runtime.launch import run_launch
from engine.script import LoadOptions, load_story
from engine.script.routes import Lock
from tests.runtime.menu_story import write_game
from tests.runtime.story import load_files


def test_ac01_declarations_in_script_order(tmp_path):
    program = load_files(tmp_path / "g", {
        "main.vns": ('lock gallery cg river "By the River":\n'
                     "    cg river_smile\n"
                     "    cg  river_close\n"
                     'include "extra.vns"\n'
                     'lock gallery cg festival "{{Festival} Night"\n'
                     "label start:\n"
                     "    unlock gallery cg river_close\n"
                     "    lock gallery cg festival\n"),
        "extra.vns": 'lock gallery bg lanterns "Lanterns"\n'})
    entries = [(e.picture, e.title, e.versions, e.file, e.line, e.sid) for e in program.gallery]
    assert entries == [
        ("cg river", "By the River", ("cg river_smile", "cg river_close"), "script/main.vns", 1,
         "gallery:cg river"),
        ("cg festival", "{Festival} Night", (), "script/main.vns", 5, "gallery:cg festival"),
        ("bg lanterns", "Lanterns", (), "script/extra.vns", 1, "gallery:bg lanterns")]
    assert dict(program.gallery_pictures) == {
        "cg river": "cg river", "cg river_smile": "cg river", "cg river_close": "cg river",
        "cg festival": "cg festival", "bg lanterns": "bg lanterns"}
    locks = [(s.unlock, s.kind, s.name) for s in program.statements_in("start")]
    assert locks == [(True, "gallery", "cg river_close"), (False, "gallery", "cg festival")]
    assert all(type(s) is Lock for s in program.statements_in("start"))


def test_ac03_twice_across_files_and_over_500(tmp_path):
    root = tmp_path / "twice"
    write_game(root, 'lock gallery cg river "R":\n    cg smile\ninclude "b.vns"\n'
                     "label start:\n    return\n")
    (root / "script" / "b.vns").write_text('lock gallery cg smile "S"\n', encoding="utf-8")
    result = load_story(GamePaths(root.resolve()))
    assert [e.format() for e in result.errors] == [
        'script/b.vns, line 1: the picture "cg smile" is in the gallery twice: here and at '
        "script/main.vns, line 2. Give each picture one place in the gallery."]
    many = "".join(f'lock gallery cg p{i} "P"\n' for i in range(501))
    result = load_story(write_game(tmp_path / "many", many + "label start:\n    return\n"))
    assert [e.format() for e in result.errors] == [
        "this story has 501 gallery pictures; the engine allows 500."]
    fine = "".join(f'lock gallery cg p{i} "P"\n' for i in range(500))
    assert load_story(write_game(tmp_path / "fine", fine + "label start:\n    return\n")
                      ).errors == ()


def test_ac14_cg_is_a_name_again(tmp_path):
    story = ('default cg = 1\nlock gallery cg festival "Festival Night"\nlabel start:\n'
             '    scene cg festival\n    $ cg += 1\n    "The lanterns rise."\n')
    result = load_story(write_game(tmp_path / "g", story), LoadOptions(dev=True))
    assert result.errors == () and result.warnings == (), (result.errors, result.warnings)
    launch = run_launch(result.program, dev=True,
                        images=ImageSource.from_files(("images/cg/festival.png",)))
    assert launch.namespace is not None and launch.warnings == (), launch.warnings
    assert "cg" in result.program.default_names
    assert next(result.program.statements_in("start")).image == "cg festival"

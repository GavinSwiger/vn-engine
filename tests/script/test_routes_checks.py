"""F19 step 1 — the whole-game checks for routes and endings (``checks.py``'s
``_iter_routes``, ``bindings.py``'s E245): AC-F19-05's include and count rows, AC-F19-06's
use kinds, AC-F19-07's W130 counts and release load. The message rows of AC-F19-03 to 07
are in ``tests/fixtures/F02/messages/cases.toml``. AC-F19-06's "Run R ends" rows are in
``tests/runtime/test_endings_story.py`` (they need F19 step 3's executors).
"""

import pytest

from engine.core.paths import GamePaths
from engine.script import bindings
from engine.script.loader import LoadOptions, load_story
from engine.script.routes import register_words
from engine.script.statements import scoped_registry
from tests.script.helpers import parse_text, template_e


@pytest.fixture
def words():
    with scoped_registry():
        register_words()
        yield


def _load(root, files: dict[str, str], *, dev: bool = True):
    script = root / "script"
    script.mkdir(parents=True)
    for name, text in files.items():
        (script / name).write_text(text, encoding="utf-8")
    return load_story(GamePaths(root.resolve()), LoadOptions(dev=dev))


def _errors(result) -> list[tuple]:
    return [(e.code, e.file, e.line, e.message) for e in result.errors]


def test_ac05_duplicates_across_includes_and_counts(words, tmp_path):
    a = 'label a_path:\n    "A."\n    ending good "Good"\nlabel a_menu:\n    menu:\n' \
        '        "Go":\n            ending a2 "A2"\n'
    b = 'label b_path:\n    "B."\n    "B2."\nlabel b_end:\n    ending good "Again"\n' \
        'label b_menu:\n    menu:\n        "Go":\n            ending b2 "B2"\n'
    main = 'include "a.vns"\ninclude "b.vns"\nlock route a_path "A"\nlock route b_path "B"\n' \
           'label start:\n    jump a_path\n'
    result = _load(tmp_path / "includes", {"main.vns": main, "a.vns": a, "b.vns": b})
    assert _errors(result) == [("E241", "script/b.vns", 5, 'there are two endings named "good": '
                                "here and at script/a.vns, line 3. Give each ending its own "
                                "name.")]
    ok = _load(tmp_path / "ok", {"main.vns": main, "a.vns": a,
                                 "b.vns": b.replace('good "Again"', 'b1 "B1"')})
    assert ok.errors == ()
    assert [e.name for e in ok.program.endings] == ["good", "a2", "b1", "b2"]
    for count in (1000, 1001):
        endings = "".join(f'    ending e{i} "T"\n' for i in range(count))
        found = _load(tmp_path / f"endings{count}", {"main.vns": f"label start:\n{endings}"},
                      dev=False)
        assert _errors(found) == ([] if count == 1000 else [
            ("E246", None, None, "this story has 1,001 endings; the engine allows 1,000.")])
        routes = "".join(f'label r{i}:\n    return\nlock route r{i} "R"\n' for i in range(count))
        found = _load(tmp_path / f"routes{count}",
                      {"main.vns": f'label start:\n    return\n{routes}'})
        assert _errors(found) == ([] if count == 1000 else [
            ("E246", None, None, "this story has 1,001 routes; the engine allows 1,000.")])


def test_ac06_view_changes_are_e245_and_not_writes(words):
    mutators = sorted(bindings.MUTATORS)
    assert len(mutators) == 14
    for name in mutators:
        parsed = parse_text(template_e(S=f"$ persistent.endings.{name}()"))
        found = bindings.check_all(parsed.nodes, parsed.ctx.collected.define_defs)
        assert [(e.code, e.line, e.args) for e in found.errors] == [
            ("E245", 7, ("change", "endings"))], name
    # A change isn't a write (F12's RootUses ignores CHANGE); the inner read stays a read.
    parsed = parse_text(template_e(S='$ persistent.flowers.append("rose")⏎[4]'
                                     '$ persistent.flowers[0] = "x"⏎[4]'
                                     '$ seen = persistent.endings'))
    found = bindings.check_all(parsed.nodes, parsed.ctx.collected.define_defs)
    assert found.errors == []
    assert found.uses.writes_of("persistent") == frozenset()
    assert set(found.uses.reads_of("persistent")) == {"flowers", "endings"}
    # An alias or getattr changes only a copy: no error at load.
    for row in ('$ e = persistent.endings⏎[4]$ e.append("x")',
                '$ getattr(persistent, "endings").append("x")'):
        parsed = parse_text(template_e(S=row))
        assert bindings.check_all(parsed.nodes, parsed.ctx.collected.define_defs).errors == []


W130_TEXT = ("the lines after this ending never run, because ending ends the story. Move them "
             "above the ending or into another label.")


def test_ac07_w130_once_per_block_and_dev_only(words, tmp_path):
    rows = [
        (None, []),
        ('ending early "Early"', [7]),
        ('if trust > 0:⏎[8]ending early "Early"⏎[8]"Never."', [8]),
        ('menu:⏎[8]"Go":⏎[12]ending early "E"⏎[8]"Stay":⏎[12]"Ok."', []),
    ]
    for number, (row, lines) in enumerate(rows):
        result = _load(tmp_path / f"dev{number}", {"main.vns": template_e(S=row)})
        assert result.errors == (), row
        found = [(w.code, w.file, w.line, w.message) for w in result.warnings]
        assert found == [("W130", "script/main.vns", line, W130_TEXT) for line in lines], row
    release = _load(tmp_path / "release", {"main.vns": template_e(S='ending early "Early"')},
                    dev=False)
    assert release.errors == () and release.warnings == ()

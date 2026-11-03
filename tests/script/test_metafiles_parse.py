"""F31 step 2: the ``file`` statement's parse and load messages (06 AC-F31-08, AC-F31-09).

``file`` registers at import only from F31 s3, so every test here calls
``metafiles.register_words()`` inside ``statements.scoped_registry()`` (06 §9 step 2). The
message rows themselves are in ``tests/fixtures/F02/messages/cases.toml`` (``feature =
"F31"``) and run with every other row in ``test_messages.py``; AC-F31-09's test checks that
they cover every form and that the run-time rows match ``messages.py``.
"""

import ast
import dataclasses
import shutil
import tomllib
from pathlib import Path

from engine.core.paths import GamePaths
from engine.runtime.commands import Say
from engine.runtime.headless import run_headless
from engine.script import metafiles
from engine.script.loader import LoadOptions, load_story
from engine.script.messages import format_message
from engine.script.metafiles import MetaFile, name_problem
from engine.script.statement_docs import all_docs
from engine.script.statements import get_spec, register, registered_words, scoped_registry
from tests.script import message_cases
from tests.script.helpers import parse_text

F31 = Path(__file__).resolve().parents[1] / "fixtures" / "F31"
HEAD = ('define hana = Character("Hana")\ndefault hana_here = True\ndefault answer = None\n'
        'label start:\n    "W0"\n')


def _parse(line: str):
    """One line at line 6 inside ``label start:`` of AC-F31-08's game."""
    return parse_text(HEAD + "    " + line + '\n    "End."\n')


def _file_nodes(parsed) -> list[MetaFile]:
    return [s for s in parsed.nodes[-1].block if isinstance(s, MetaFile)]


def _load(tmp_path: Path, main: str, more: str | None = None):
    game = tmp_path / "game"
    (game / "script").mkdir(parents=True)
    (game / "files").mkdir()
    (game / "files" / "hana.chr").write_bytes(b"HANA")
    if more is not None:
        (game / "script" / "more.vns").write_text(more, encoding="utf-8")
    (game / "script" / "main.vns").write_text(main, encoding="utf-8")
    return load_story(GamePaths(game.resolve()), LoadOptions(dev=True))


def test_ac08_the_four_forms_parse(tmp_path):
    assert get_spec("file") is None                       # not registered at import (s2)
    with scoped_registry():
        metafiles.register_words()
        words, docs = registered_words(), all_docs()
        metafiles.register_words()                        # a repeat changes nothing
        assert registered_words() == words and all_docs() == docs
        assert sum(doc.key == "file" for doc in docs) == 4

        rows = [
            ('file write "hana.chr"', ("write", "hana.chr", None, None)),
            ('file write "read_me.txt" "a\\nb \\"q\\" \\\\ {b} {{"',
             ("write", "read_me.txt", 'a\nb "q" \\ {b} {{', None)),
            ('file write "a.txt" ""', ("write", "a.txt", "", None)),
            ('file write "a.txt" "a\tb"', ("write", "a.txt", "a\tb", None)),
            ('file write "a.txt" "a‮b"', ("write", "a.txt", "a‮b", None)),
            ('file write "a.txt" "' + "a" * 7_999 + '\n        ' + "b" * 8_000 + '"',
             ("write", "a.txt", "a" * 7_999 + " " + "b" * 8_000, None)),
            ('file delete "hana.chr"', ("delete", "hana.chr", None, None)),
            ('file exists "hana.chr" into hana_here', ("exists", "hana.chr", None, "hana_here")),
            ('file read "answer.txt" into answer', ("read", "answer.txt", None, "answer")),
        ]
        for line, want in rows:
            parsed = _parse(line)
            assert parsed.errors == [], (line[:60], parsed.messages)
            (node,) = _file_nodes(parsed)
            assert (node.verb, node.name, node.text, node.target) == want, line[:60]
            assert node.line == 6
        assert len(rows[5][1][2]) == 16_000

        # Identity: the text isn't in it, so two texts for one name share a sid.
        one, two = (_file_nodes(_parse(f'file write "a.txt" "{t}"'))[0] for t in ("x", "y"))
        assert one.identity_key() == two.identity_key() == ("file", "write", "a.txt")

        # Program.meta_files across included files; voice before a file line is no W20.
        main = (HEAD.replace("label start:", 'include "more.vns"\nlabel start:')
                + '    voice "v/a.ogg"\n    file write "hana.chr"\n    hana "Hi."\n'
                '    call more\n')
        more = ('label more:\n    file exists "x.txt" into hana_here\n'
                '    file read "answer.txt" into answer\n    file delete "hana.chr"\n'
                '    return\n')
        result = _load(tmp_path, main, more)
        assert result.errors == (), [e.format() for e in result.errors]
        assert "W20" not in {w.code for w in result.warnings}
        assert result.program.meta_files == frozenset(("hana.chr", "x.txt", "answer.txt"))
        say = next(s for s in result.program.labels["start"].block
                   if type(s).__name__ == "Say" and s.speaker == "hana")
        assert say.voice == "v/a.ogg"

        # The verbs and into stay usable as names: they load and run.
        names = "\n".join(f"default {n} = 1" for n in ("write", "delete", "exists", "read",
                                                         "into"))
        main = (f'{names}\nlabel start:\n    $ read += 1\n'
                '    if read == 2 and write + delete + exists + into == 4:\n'
                '        "Fine."\n')
        shutil.rmtree(tmp_path / "game")
        result = _load(tmp_path, main)
        assert result.errors == (), [e.format() for e in result.errors]
        said = [c.text for c in run_headless(result.program, seed=1) if isinstance(c, Say)]
        assert said == ["Fine."]

    # The module touches no file system (04 §5.1): no os, pathlib, io, or engine.meta.
    tree = ast.parse(Path(metafiles.__file__).read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module or "" for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom)}
    for name in imported:
        assert name.split(".")[0] not in ("os", "pathlib", "io"), name
        assert not name.startswith("engine.meta"), name


# Run-time rows (data until F31 s3/s4): the args each id names.
_RUN_ARGS = {
    "W196": (), "W197": (), "W199": (),
    **{f"W198-{form}-{verb}": (form, verb, "hana.chr" if verb == "delete" else "note.txt")
       for form, verb in (("full", "write"), ("permission", "delete"),
                          ("folder_at_name", "write"), ("original_missing", "write"),
                          ("original_large", "write"), ("busy", "delete"), ("other", "write"))},
    **{f"W200-{form}": (form, "answer.txt")
       for form in ("large", "utf8", "not_file", "hard_link")},
}
# Every load form of 04 §11, told apart by words only its text has.
_LOAD_FORMS = {
    "E309": {"needs": "needs", "unknown": "isn't a file word", "left": "left over",
             "block": "doesn't take a block"},
    "E310": {"slash": ("has a /", "has a \\"), "capitals": "capital letters",
             "ending": ("ends in", "doesn't end in"), "reserved": "Windows keeps",
             "long": "before the dot, but",
             "chars": ("nothing before the dot", "starts with", "than one dot", '" in it.'),
             "variable": "not a variable"},
    "E311": {"long": "can be at most"},   # ``control`` can't come from a script (G6): below
    "E312": {"needs": "needs into", "one_name": "into takes one", "no_default": "no default",
             "define": "set by define", "engine": "the engine uses"},
    "E313": {"missing": "no such file", "large": "an original can be at most"},
    "E314": {None: "meta file names"},
    "E315": {None: "works only on .txt"},
}


def _form_of(code: str, message: str) -> str | None:
    found = [form for form, words in _LOAD_FORMS[code].items()
             if any(w in message for w in ((words,) if isinstance(words, str) else words))]
    assert len(found) == 1, (code, message, found)
    return found[0]


def test_ac09_load_errors_e309_to_e312_and_e315():
    cases = [c for c in message_cases.load_cases() if c.feature == "F31"]
    runnable = [c for c in cases if c.runnable]

    # Every load form has a golden row (expected.txt), each with its code at line 6.
    golden = message_cases.EXPECTED_PATH.read_text(encoding="utf-8")
    seen: dict[str, set] = {code: set() for code in _LOAD_FORMS}
    for case in runnable:
        block = golden.split(f"[{case.id}]\n", 1)[1].split("\n\n", 1)[0]
        assert "(loads)" not in block, case.id
        if case.code in seen:
            text = case.expect["exact"]
            seen[case.code].add(_form_of(case.code, text))
            assert text in block, case.id
            if case.code != "E314":
                assert block.startswith("script/main.vns, line 6: "), case.id
    assert {code: set(forms) for code, forms in _LOAD_FORMS.items()} == seen
    assert any(c.code == "E03" and "U+0007" in c.expect["exact"] for c in runnable)  # G6

    # Every run form has a data row that matches messages.py.
    rows = {c.id.removeprefix("F31-09-"): c for c in cases if c.time == "run"}
    assert set(rows) == set(_RUN_ARGS)
    for key, args in _RUN_ARGS.items():
        assert format_message(rows[key].code, args) == rows[key].expect["exact"], key
        assert "node" not in rows[key].expect["exact"].lower()

    # Group A: each refused names.toml row a .vns string can hold gives E310 with its form.
    names = tomllib.loads((F31 / "names.toml").read_text(encoding="utf-8"))["row"]
    with scoped_registry():
        metafiles.register_words()
        for row in names:
            name = row["name"]
            if not row["in_vns"]:
                continue
            assert name_problem(name) == (row["e310_form"] or None), name
            escaped = name.replace("\\", "\\\\").replace('"', '\\"')
            parsed = _parse(f'file write "{escaped}"')
            if row["accepted"]:
                assert parsed.errors == [] and _file_nodes(parsed)[0].name == name, name
            else:
                assert parsed.codes == ["E310"], (name, parsed.messages)
                assert parsed.errors[0].message == format_message(
                    "E310", (row["e310_form"], name)), name

    # E311 ``control`` (a defence, G6): a STRING token holding U+0007 reaches parse_file.
    def poisoned(raw, ctx):
        raw.tokens[3].text = "ab"
        return metafiles.parse_file(raw, ctx)

    with scoped_registry():
        register(dataclasses.replace(metafiles.SPEC, parse=poisoned))
        parsed = _parse('file write "read_me.txt" "x"')
    assert parsed.codes == ["E311"]
    assert parsed.errors[0].message == format_message("E311", ("control", "read_me.txt", ""))
    assert "U+0007" in parsed.errors[0].message

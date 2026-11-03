"""F31 step 5 in Studio (``06`` AC-F31-29, AC-F31-30; F45 AC-F45-72): the four ``file`` help
rows, the check child's ``meta_file`` and ``meta_file_use`` kinds, verb and quoted-name
completion, the Outline's "Meta files" section, and the ``files/`` asset group with its
``meta`` validator."""

from pathlib import Path

import engine.script  # noqa: F401  registers every statement and the docs table
from engine.core.constants import META_ORIGINAL_MAX_BYTES, WRITE_ROOT_DIRNAMES
from engine.core.paths import GamePaths
from engine.script.assetgroups import ASSET_GROUPS
from engine.script.statement_docs import docs_for
from engine.tools.check import NAME_SOURCES
from engine.tools.editor import files
from engine.tools.editor.assist import auto_open, candidates, completion_context
from engine.tools.editor.outline import outline
from tests.tools.f45_games import check as run_check
from tests.tools.f45_games import studio as studio_s

LINES = ['    file write "hana.chr"\n', '    file write "read_me.txt" "Hi."\n',
         '    file delete "hana.chr"\n', '    file exists "hana.chr" into hana_here\n']


def _complete(line: str, names: dict) -> list[str]:
    ctx = completion_context(line, len(line))
    return [] if ctx is None else [c.text for c in candidates(ctx, names)]


def test_ac_f31_29_help_completion_and_outline(tmp_path):
    docs = docs_for("file")
    assert [d.syntax.split()[:2] for d in docs] == [
        ["file", "write"], ["file", "delete"], ["file", "exists"], ["file", "read"]]
    assert {(d.docs, d.names) for d in docs} == {("Meta files", ("meta_file",))}
    assert {"meta_file", "meta_file_use"} <= set(NAME_SOURCES)

    # The check child: names from file lines and files/ (Hana.chr and x.png aren't names).
    game = studio_s(tmp_path)
    (game / "files").mkdir()
    for name in ("hana.chr", "Hana.chr", "x.png", "spare.txt"):
        (game / "files" / name).write_bytes(b"HANA")
    main = game / "script" / "main.vns"
    text = main.read_text(encoding="utf-8")
    main.write_text(text.replace("label start:\n", "default hana_here = False\nlabel start:\n"
                                 + "".join(LINES), 1), encoding="utf-8", newline="\n")
    start = text[:text.index("label start:\n")].count("\n") + 2      # the line after label
    names = dict(run_check(game, launch=False).names)
    assert sorted(e.name for e in names["meta_file"]) == ["hana.chr", "read_me.txt",
                                                          "spare.txt"]
    assert [(e.name, e.file, e.line) for e in names["meta_file_use"]] == [
        (name, "script/main.vns", start + 1 + n)
        for n, name in enumerate(["hana.chr", "read_me.txt", "hana.chr", "hana.chr"])]

    # Completion: the verbs after "file ", meta file names inside the quotes only.
    plain = {kind: [(e.name, e.file, e.line) for e in rows] for kind, rows in names.items()}
    assert _complete("    file ", plain) == ["delete", "exists", "read", "write"]
    assert auto_open("    file ", len("    file "))
    assert _complete("    file de", plain) == ["delete"]
    assert _complete('    file delete "', plain) == ["hana.chr", "read_me.txt", "spare.txt"]
    assert _complete('    file delete "h', plain) == ["hana.chr"]
    assert _complete("    file delete ", plain) == []
    assert _complete('    file exists "hana.chr" into ', plain) == []

    # The Outline: each name with its lines, an unused original marked; rows open lines.
    (section,) = [r for r in outline(plain) if r.text.startswith("Meta files")]
    assert section.text == "Meta files (3)"
    assert [(r.text, [(c.file, c.line) for c in r.children]) for r in section.children] == [
        ("hana.chr (3)", [("script/main.vns", start + 1), ("script/main.vns", start + 3),
                          ("script/main.vns", start + 4)]),
        ("read_me.txt (1)", [("script/main.vns", start + 2)]),
        ("spare.txt (not used)", [])]
    opened = main.read_text(encoding="utf-8").splitlines()
    assert opened[section.children[0].children[1].line - 1] == LINES[2].rstrip("\n")


def test_ac_f31_30_the_files_asset_group(tmp_path):
    group = ASSET_GROUPS[-1]
    assert (group.key, group.folder, group.title, group.suffixes, group.kind) == (
        "files", "files", "Meta files", (".chr", ".txt"), "meta")
    assert group.max_bytes is META_ORIGINAL_MAX_BYTES
    assert not {g.folder.casefold() for g in ASSET_GROUPS} & {
        name.casefold() for name in WRITE_ROOT_DIRNAMES}       # characters, saves, ..., logs
    assert files.meta_problem("hana.chr") is None
    for name in ("Hana.chr", "con.txt", "x.png", "a" * 33 + ".chr"):
        assert files.meta_problem(name) is not None, name
    assert files.meta_problem("Hana.chr")[1] == "hana.chr"              # offered as the fix

    # Adding to the group in Studio: a good name is added, a bad one refused or offered.
    game = studio_s(tmp_path)
    paths = GamePaths.for_game(game)
    source = tmp_path / "picked"
    source.mkdir()
    for name in ("hana.chr", "Hana2.chr", "con.txt"):
        (source / name).write_bytes(b"HANA")
    plans = {p.label: p for p in files.plan_add(
        paths, "files", "files", [source / n for n in ("hana.chr", "Hana2.chr", "con.txt")])}
    assert plans["hana.chr"].ok
    assert plans["Hana2.chr"].offer == "hana2.chr"
    assert plans["con.txt"].refusal is not None and "on Windows" in plans["con.txt"].refusal
    assert files.run_add(paths, plans["hana.chr"], "new").ref == "files/hana.chr"
    assert (game / "files" / "hana.chr").read_bytes() == b"HANA"
    tree = files.project_tree(GamePaths.for_game(game))
    meta = next(g for g in tree.groups if g.group == "files")
    assert [(c.name, c.ref) for c in meta.children] == [("hana.chr", "files/hana.chr")]
    assert Path(game / "characters").exists() is False

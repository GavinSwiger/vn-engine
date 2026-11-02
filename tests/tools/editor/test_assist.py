"""Studio's completion, Insert, and Help, pure half (F45 ``06-acceptance.md`` AC-F45-37..41
unit rows; ``04-technical.md`` §7.6). No Tk: the popup, the menu, and the Help pane are step
5's window tests, which needn't repeat what these cover."""

import shutil
from dataclasses import dataclass, replace
from pathlib import Path

import engine.script  # noqa: F401  registers every statement and the docs table
from engine.core.paths import GamePaths
from engine.script import load_story, statement_docs
from engine.script.statement_docs import GROUPS, StatementDoc, all_docs, docs_for, register_doc
from engine.script.statements import get_spec, scoped_registry
from engine.tools.editor.assist import (
    COMPLETION_MAX, NO_HELP, accept, auto_open, candidates, completion_context, help_for,
    help_sections, insert_menu, insert_text)

DOCGAME = Path(__file__).resolve().parents[2] / "fixtures" / "docgame"


@dataclass(frozen=True, slots=True)
class NameEntry:
    """The check child's name row (``checker.NameEntry``'s shape, 04 §4.2), kept local so
    these tests don't depend on step 2's module."""

    name: str
    file: str | None = None
    line: int | None = None


# AC-F45-37's name index N, in the check child's shape (NameEntry rows per kind).
N = {
    "label": tuple(NameEntry(n) for n in ("start", "club", "bridge", "Bridge_old", "river")),
    "image": tuple(NameEntry(n) for n in ("hana happy", "hana smile", "bg room")),
    "character": (NameEntry("hana"),),
    "transition": (NameEntry("dissolve"), NameEntry("fade")),
    "position": (NameEntry("left"), NameEntry("right")),
    "audio": (NameEntry("audio/bgm/theme.ogg"),),
}


def complete(line: str, names=N) -> tuple[list[str], int | None]:
    ctx = completion_context(line, len(line))
    if ctx is None:
        return [], None
    return [c.text for c in candidates(ctx, names)], ctx.start


def test_ac_f45_37_completion_candidates(monkeypatch):
    rows = [
        # line, first candidates, replaced from column ([] / None: no completion)
        ("jum", ["jump"], 0),
        ("    jump b", ["bridge", "Bridge_old"], 9),
        ("    jump B", ["Bridge_old", "bridge"], 9),
        ("    show hana sm", ["hana smile"], 9),
        ("    show hana happy with di", ["dissolve"], 25),
        ("    show hana happy at le", ["left"], 23),
        ('    play music "audio/b', ["audio/bgm/theme.ogg"], 16),
        ("    zzz q", [], None),
        ('    "Hello th', [], None),
    ]
    for line, first, start in rows:
        texts, got_start = complete(line)
        assert (texts[:len(first)], got_start) == (first, start), line
        assert bool(texts) is bool(first), line

    # A new word's doc completes its own name kind with no Studio change.
    monkeypatch.setattr(statement_docs, "STATEMENT_WORDS",
                        statement_docs.STATEMENT_WORDS | {"zzmeter"})
    with scoped_registry():
        register_doc(StatementDoc("zzmeter", "Meter test", "Logic", "zzmeter <meter>",
                                  "A test word.", "zzmeter trust", None, "F45",
                                  fields=("trust",), names=("meter",)))
        assert complete("    zzmeter tr", {**N, "meter": (NameEntry("trust"),)}) == (
            ["trust"], 12)

    # 20,000 labels give 200 rows, in order.
    many = {"label": tuple(NameEntry(f"l{i:05d}") for i in range(20_000))}
    rows_ = candidates(completion_context("    jump l", 10), many)
    assert len(rows_) == COMPLETION_MAX == 200
    assert (rows_[0].text, rows_[-1].text) == ("l00000", "l00199")


def test_completion_paths_the_ac_table_misses():
    """Audio dropped outside quotes, the last modifier winning, spaced image prefixes, wire
    rows as entries, a cursor inside the line, and a huge line."""
    for line, kinds in [("    play mu", None), ("    jump \"x", None), ("    pause 1", None),
                        ("    show hana at left with fa", ("transition",)),
                        ('    stop music "bgm/', ("audio",))]:
        ctx = completion_context(line, len(line))
        assert (None if ctx is None else ctx.kinds) == kinds, line
    ctx = completion_context("    show  hana   sm", 19)
    assert (ctx.prefix, ctx.start) == ("hana sm", 10)
    wire = {"label": [("Alpha", "script/a.vns", 3), ["alpha", None, None], "ALPHA2", 7]}
    assert [c.text for c in candidates(completion_context("jump al", 7), wire)] == [
        "alpha", "Alpha", "ALPHA2"]
    line = "    jump bridge  # later"
    ctx = completion_context(line, 10)
    assert accept(line, ctx, candidates(ctx, N)[1]) == ("    jump Bridge_oldridge  # later", 19)
    huge = '    play music "' + "a" * 2_000_000                    # one huge word: none
    assert completion_context(huge, len(huge)) is None
    huge = "    show " + "a " * 1_000_000 + "b"                      # a huge image span
    assert completion_context(huge, len(huge)).start == len(huge) - 1


def test_ac_f45_38_accepting_a_row():
    """The pure half of the list: Down then Enter takes the second row; typing ``r`` keeps
    ``bridge`` first. The popup itself is the window's test."""
    line = "    jump b"
    ctx = completion_context(line, len(line))
    assert accept(line, ctx, candidates(ctx, N)[1]) == ("    jump Bridge_old", 19)
    assert complete("    jump br")[0][0] == "bridge"


def test_ac_f45_39_the_list_opens_by_itself():
    rows = [("    jump ", True), ("    show hana happy with ", True), ("    scene ", True),
            ('    "Hi ', False), ("    pause ", False), ("    play ", False),
            ("    jump bridge ", False), ("    show hana ", False), ("    ", False)]
    for line, opens in rows:
        assert auto_open(line, len(line)) is opens, line


def _two_space(text: str) -> str:
    out = []
    for line in text.split("\n"):
        body = line.lstrip(" ")
        out.append("  " * ((len(line) - len(body)) // 4) + body)
    return "\n".join(out)


def _top_level(doc: StatementDoc) -> bool:
    spec = get_spec(doc.key)
    return (spec is not None and spec.placement == "top") or doc.group == "Declarations"


def test_ac_f45_40_insert(tmp_path):
    # The menu: GROUPS order, registration order, insert=True only.
    menu = insert_menu()
    assert [g for g, _ in menu] == [
        g for g in GROUPS if any(d.group == g and d.insert for d in all_docs())]
    for group, docs in menu:
        assert list(docs) == [d for d in all_docs() if d.group == group and d.insert]
    keys = {d.key for _, docs in menu for d in docs}
    assert {"dialogue", "narration", "$"} <= keys and not keys & {"elif", "else"}

    # The menu doc at a cursor line `    "Hi."` in a 4-space, a 2-space and a tab file.
    for indent, unit in (("    ", "    "), ("    ", "  "), ("\t", "\t")):
        text, (start, end) = insert_text(docs_for("menu")[0], indent, unit)
        assert text.split("\n") == [
            indent + "menu:", indent + unit + '"Go to the river":',
            indent + unit * 2 + "jump river", indent + unit + '"Stay here":',
            indent + unit * 2 + '"You stay a while."'], repr(unit)
        assert (start, text[start:end]) == (text.index("Go to"), "Go to the river")

    # Every insert=True doc in a 2-space copy of the doc game loads with no problem.
    root = tmp_path / "game"
    shutil.copytree(DOCGAME, root)
    for vns in (root / "script").glob("*.vns"):
        vns.write_bytes(_two_space(vns.read_bytes().decode("utf-8")).encode("utf-8"))
    main = root / "script" / "main.vns"
    top = [insert_text(d, "", "  ")[0] for d in all_docs() if d.insert and _top_level(d)]
    # F20's ``flowchart scene`` must be its label's first line (E-code), so it goes first.
    story = [insert_text(d, "  ", "  ")[0] for d in sorted(
        (d for d in all_docs() if d.insert and not _top_level(d)),
        key=lambda d: not d.syntax.startswith("flowchart scene"))]
    text = main.read_bytes().decode("utf-8").replace(
        "label start:\n", "label start:\n" + "\n".join(story) + "\n", 1)
    main.write_bytes(("\n".join(top) + "\n" + text).encode("utf-8"))
    result = load_story(GamePaths(root.resolve()))
    assert [e.format() for e in result.errors] + [w.format() for w in result.warnings] == []


def test_ac_f45_41_help():
    play_music, play_sound = docs_for("play")
    rows = [("    jump river", docs_for("jump")[0]), ('    play music "a.ogg"', play_music),
            ('    play sound "a.ogg"', play_sound), ('hana "Hi."', docs_for("dialogue")[0]),
            ('    hana happy "Yes!"', docs_for("dialogue")[0]),
            ('"Hi."', docs_for("narration")[0]), ("$ x = 1", docs_for("$")[0]),
            ("    else:", docs_for("else")[0]), ("# note", None), ("", None), ("zzz", None)]
    for line, doc in rows:
        assert help_for(line) is doc, line
    jump = docs_for("jump")[0]
    assert help_sections(jump) == (
        ("title", jump.title), ("syntax", jump.syntax), ("summary", jump.summary),
        ("example", jump.example), ("docs", "Docs: jump"))
    # A doc whose docs step is pending (07 I-4) has no Docs line. Built here, so the test
    # doesn't depend on which keys are still pending (``shake`` was, until F09's docs step).
    assert "docs" not in dict(help_sections(replace(jump, docs=None)))
    assert help_sections(None) == (("none", NO_HELP),) and NO_HELP == "No help for this line."

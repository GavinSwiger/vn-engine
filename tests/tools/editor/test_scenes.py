"""Studio's scene index, pure half (F46 ``06-acceptance.md`` AC-F46-01, AC-F46-02;
``04-technical.md`` §6.1, §6.2; ``07`` I-1 to I-4). No Tk: the 0.5 s follow on the map is
step 1b's window test."""

from pathlib import Path

import pytest

import engine.script  # noqa: F401  registers every statement
from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.script import LoadOptions, load_story
from engine.script.diagnostics import DiagnosticSink
from engine.script.identity import walk_block
from engine.script.labelgraph import block_links, label_links
from engine.script.nodes import ScriptFile
from engine.script.parser import parse_file
from engine.script.source import decode_script, normalize_line_ends
from engine.script.statements import ParseContext
from engine.tools.editor import scenes
from engine.tools.editor.checker import NameEntry
from engine.tools.editor.scenes import Span, chunks, parse_chunk, reindex

ROOT = Path(__file__).resolve().parents[3]
L = ROOT / "tests" / "fixtures" / "F46" / "games" / "lanterns"
MAIN = (L / "script" / "main.vns").read_text(encoding="utf-8")
CH2 = (L / "script" / "ch2.vns").read_text(encoding="utf-8")


def _lines(text: str, first: int, last: int) -> str:
    """Absolute lines ``first``..``last`` as one chunk with a final break."""
    return "\n".join(text.split("\n")[first - 1:last]) + "\n"


def _replace(text: str, number: int, *new: str) -> str:
    lines = text.split("\n")
    lines[number - 1:number] = list(new)
    return "\n".join(lines)


def test_ac_f46_01_chunks_and_spans():
    assert chunks(MAIN) == [("start", 6, 11), ("festival", 12, 15)]
    assert chunks(CH2) == [("stall", 1, 10), ("river", 11, 17)]
    # An indented label line starts no chunk; lines above the first label belong to none.
    assert chunks(_replace(MAIN, 13, "    label inner:", '    "The lanterns were lit."')) \
        == [("start", 6, 11), ("festival", 12, 16)]

    start = parse_chunk("script/main.vns", _lines(MAIN, 6, 11))
    scene = start.statements[0]
    assert (type(scene.node).__name__, scene.head, scene.unit) == (
        "Scene", Span(3, 3), Span(2, 3))
    assert start.last + 6 - 1 == 10                     # main 10, the trailing blank dropped

    stall = parse_chunk("script/ch2.vns", _lines(CH2, 1, 10))
    menu = stall.statements[0]
    first_choice = next(b for b in stall.blocks if b.owner == (0,) and b.branch == 0)
    assert (first_choice.head, first_choice.span) == (Span(3, 3), Span(3, 5))
    assert menu.span == Span(2, 7)
    # A deeper comment after ch2 7 joins "Just look"'s span (and the menu's), not $ pass's.
    deeper = parse_chunk("script/ch2.vns", _lines(
        _replace(CH2, 7, "            $ pass", "            # then nothing"), 1, 11))
    look = next(b for b in deeper.blocks if b.owner == (0,) and b.branch == 1)
    assert (look.span, deeper.statements[0].span) == (Span(6, 8), Span(2, 8))
    assert deeper.statements[3].span == Span(7, 7)
    # A say whose quote continues onto a more-indented line has a two-line head.
    wrapped = parse_chunk("script/ch2.vns", _lines(
        _replace(CH2, 8, '    "You walk past', '        the stall."'), 1, 11))
    say = wrapped.statements[4]
    assert (type(say.node).__name__, say.head, say.span) == ("Say", Span(8, 9), Span(8, 9))

    # Equal chunk text gives an equal digest; a changed line changes only its chunk's.
    moved = reindex(None, "script/ch2.vns", "# a note\n\n" + CH2, 0, checked=None)
    before = reindex(None, "script/ch2.vns", CH2, 0, checked=None)
    assert moved.digests == before.digests
    assert moved.starts == {("stall", 0): 3, ("river", 0): 13}
    after = reindex(before, "script/ch2.vns", _replace(CH2, 13, '    hana "Hello!"'), 1,
                    checked=before.checked)
    assert after.digests[("stall", 0)] == before.digests[("stall", 0)]
    assert after.digests[("river", 0)] != before.digests[("river", 0)]


def _text(root: Path, ref: str) -> str:
    decoded = decode_script(ref, (root / ref).read_bytes())
    assert decoded.text is not None, ref
    return normalize_line_ends(decoded.text)


def _keys(block) -> list[tuple]:
    return [(stmt.identity_key(), stmt.sid, path) for stmt, path in walk_block(block)]


@pytest.mark.parametrize("root", [ROOT / "game", ROOT / "tests" / "fixtures" / "docgame", L],
                         ids=["game", "docgame", "lanterns"])
def test_ac_f46_02_a_chunk_reads_as_the_loader_reads_it(root, monkeypatch):
    positions = frozenset(load_config(GamePaths.for_game(root)).config.stage.positions.keys())
    result = load_story(GamePaths.for_game(root), LoadOptions(position_names=positions))
    assert result.program is not None, [e.format() for e in result.errors]
    program = result.program
    seen = set()
    for file in program.files:
        text = _text(root, file.ref)
        for name, first, last in chunks(text):
            read = parse_chunk(file.ref, _lines(text, first, last), positions=positions)
            assert read is not None and read.error is None, (file.ref, name, read)
            label = program.labels[name]
            assert label.file.ref == file.ref and label.line == first
            assert [(s.node.identity_key(), s.node.sid, s.path) for s in read.statements] \
                == _keys(label.block), name
            assert [(k.src, k.dst, k.kind, k.file, k.line + first - 1, k.choice,
                     k.conditional) for k in read.links] \
                == [(k.src, k.dst, k.kind, k.file, k.line, k.choice, k.conditional)
                    for k in block_links(name, label.block)], name
            seen.add(name)
    assert seen == set(program.labels)
    if root != L:
        return

    # ch2 9 becomes "    jump": stall reads F02's first error; river's read is untouched.
    ch2 = _text(root, "script/ch2.vns")
    old = reindex(None, "script/ch2.vns", ch2, 0, checked=None, want={"stall", "river"},
                  positions=positions)
    broken = _replace(ch2, 9, "    jump")
    ctx = ParseContext(sink=DiagnosticSink())
    parse_file(ScriptFile("script/ch2.vns", "ch2.vns", 0), broken, ctx)
    first_error = ctx.sink.kept()[0]
    parsed = []
    real = scenes.parse_chunk
    monkeypatch.setattr(scenes, "parse_chunk",
                        lambda ref, chunk, **kw: parsed.append(chunk[6:11]) or real(ref, chunk,
                                                                                   **kw))
    new = reindex(old, "script/ch2.vns", broken, 1, checked=old.checked, positions=positions)
    assert parsed == ["stall"]
    assert new.reads[("stall", 0)].error == (9, first_error.message()) \
        and first_error.line == 9
    assert new.reads[("river", 0)] is old.reads[("river", 0)]
    assert new.good[("stall", 0)] is old.reads[("stall", 0)]
    assert scenes.out_of_date([new]) == {"stall"}
    # The map's lists: the child's for main (not indexed), ch2's from the index, and stall
    # keeps its last good links at their lines.
    labels = [NameEntry(n, lab.file.ref, lab.line) for n, lab in program.labels.items()]
    links, _ = label_links(program, limit=100)
    shown_labels, shown_links = scenes.map_data(labels, links, {"script/ch2.vns": new})
    assert (shown_labels, shown_links) == (labels, list(links))

    # 07 I-4: new position names re-parse a reused chunk; a parser crash becomes an error.
    parsed.clear()
    reindex(new, "script/ch2.vns", broken, 2, checked=old.checked, want={"river"},
            positions=positions | {"far"})
    assert parsed == ["stall", "river"]
    monkeypatch.setattr(scenes, "parse_file", lambda *a: (_ for _ in ()).throw(RecursionError))
    crashed = real("script/ch2.vns", _lines(ch2, 11, 17))
    assert crashed.error == (1, scenes.format_message("E86", ("exec",)))
    monkeypatch.undo()
    # I-2: a chunk over the cap isn't parsed. I-3: a duplicated label keeps both chunks.
    monkeypatch.setattr(scenes, "SCENE_PARSE_MAX_LINES", 5)
    assert real("script/ch2.vns", _lines(ch2, 11, 17)).error == (1, scenes.SCENE_TOO_LONG)
    twice = reindex(None, "script/ch2.vns", ch2 + "label stall:\n    return\n", 0, checked=None)
    assert list(twice.starts) == [("stall", 0), ("river", 0), ("stall", 1)]
    assert scenes.duplicates([], {"script/ch2.vns": twice}) == {
        "stall": (("script/ch2.vns", 1), ("script/ch2.vns", 18))}

"""F43 matching (PR-F43-03; ``04`` §7.2): AC-F43-04, rules 1–4 over real script edits, as a
case table: each row loads an old script, translates every text ("T:" + original), edits
the script, and matches the old entries to the new texts."""

import itertools
from pathlib import Path

from engine.core.paths import GamePaths
from engine.script.loader import LoadOptions, load_story
from engine.script.translatekeys import SourceText, TextKind, source_texts
from engine.script.translatematch import (
    CANDIDATES_MAX,
    COMPARE_CHARS,
    Entry,
    MatchResult,
    Status,
    match,
)

_dirs = itertools.count()

FESTIVAL = '''define hana = Character("Hana")
label start:
    jump festival
label festival:
    "The lanterns are already lit."
    hana "He said you'd get lost at least twice."
    "The river was quiet."
    menu:
        hana "Which way?"
        "Over the bridge":
            "We crossed."
        "Along the bank":
            "We walked."
    "..."
    "..."
'''


def _texts(root: Path, script: str) -> tuple[SourceText, ...]:
    folder = root / f"g{next(_dirs)}"
    (folder / "script").mkdir(parents=True)
    (folder / "script" / "main.vns").write_text(script, encoding="utf-8")
    result = load_story(GamePaths(folder.resolve()), LoadOptions())
    assert result.program is not None and result.errors == (), result.errors
    return source_texts(result.program)


def _translated(texts) -> list[Entry]:
    return [Entry(t.key, t.original, "T:" + t.original, who=t.who) for t in texts]


def _status(result: MatchResult, original: str) -> tuple:
    [row] = [r for r in result.rows if r.source.original == original]
    return row.status, row.translation, row.was, row.rule


def test_ac_f43_04_matching_rules(tmp_path):
    """AC-F43-04: typo fix → Changed with Was; insert → New; delete → Unused; restore → back;
    scene rename → status kept; ``~2`` duplicates in order; reworded choice; reworded
    question; speaker change; similarity floor; a word's changed original; rule 3's caps."""
    old = _texts(tmp_path, FESTIVAL)
    entries = _translated(old)
    lost = "He said you'd get lost at least twice."
    D, C, N = Status.DONE, Status.CHANGED, Status.NEW

    cases = [
        # (name, edit, [(original, (status, translation, was, rule))], unused originals)
        ("typo fix", (lost, "He said you'd get lost twice."),
         [("He said you'd get lost twice.", (C, "T:" + lost, lost, 3)),
          ("The river was quiet.", (D, "T:The river was quiet.", None, 1))], []),
        ("insert", ('    "The river was quiet."\n',
                    '    "The river was quiet."\n    "A dog barked twice in the dark."\n'),
         [("A dog barked twice in the dark.", (N, "", None, 4))], []),
        ("delete", ('    "The river was quiet."\n', ""), [], ["The river was quiet."]),
        ("scene rename", ("festival", "fair"),
         [(lost, (D, "T:" + lost, None, 2)),
          ("Over the bridge", (D, "T:Over the bridge", None, 2))], []),
        ("reworded choice", ('"Along the bank"', '"Along the river bank"'),
         [("Along the river bank", (C, "T:Along the bank", "Along the bank", 3))], []),
        ("reworded question", ("Which way?", "Which way now?"),
         [("Which way now?", (C, "T:Which way?", "Which way?", 3)),
          ("Over the bridge", (D, "T:Over the bridge", None, 2))], []),
        ("speaker change", ('hana "He said', '"He said'),
         [(lost, (N, "", None, 4))], [lost]),
        # Off its neighbours, similarity decides (at least 50 %): the unlike line is New.
        ("similarity", ('    "The river was quiet."\n',
                        '    "Zzz."\n    "The river was very quiet."\n'),
         [("Zzz.", (N, "", None, 4)), ("The river was very quiet.",
          (C, "T:The river was quiet.", "The river was quiet.", 3))], []),
        # Between its neighbours, the line takes the entry however it was reworded.
        ("neighbours", ('"The river was quiet."', '"Nothing moved on the water."'),
         [("Nothing moved on the water.",
           (C, "T:The river was quiet.", "The river was quiet.", 3))], []),
    ]
    for name, (before, after), expect, unused in cases:
        assert before in FESTIVAL, name
        new = _texts(tmp_path, FESTIVAL.replace(before, after))
        result = match(new, entries)
        for original, want in expect:
            assert _status(result, original) == want, (name, original)
        assert sorted(entries[e].original for e in result.unused) == sorted(unused), name
        assert len(result.rows) == len(new) and all(r.translation or not r.shown
                                                    for r in result.rows), name

    # Delete, then restore: Unused, then back by rule 1 with its translation.
    deleted = match(_texts(tmp_path, FESTIVAL.replace('    "The river was quiet."\n', "")),
                    entries)
    assert [entries[e].original for e in deleted.unused] == ["The river was quiet."]
    restored = match(old, entries)
    assert restored.unused == () and all(r.rule == 1 and r.status is D for r in restored.rows)
    assert not any(r.updated for r in restored.rows)

    # `~2` duplicates, translated differently, keep their order through a scene rename.
    dupes = [r.source for r in restored.rows if r.source.original == "..."]
    assert [d.key.endswith("~2") for d in dupes] == [False, True]
    entries2 = [Entry(e.key, e.original, "T1" if e.key == dupes[0].key else "T2", who=e.who)
                if e.original == "..." else e for e in entries]
    renamed = match(_texts(tmp_path, FESTIVAL.replace("festival", "fair")), entries2)
    assert [r.translation for r in renamed.rows if r.source.original == "..."] == ["T1", "T2"]
    assert all(r.updated for r in renamed.rows if r.rule == 2)

    # A Changed entry keeps its first Was through a rename (status kept by rule 2) and
    # through a second edit (rule 3).
    fuzzy = [Entry(e.key, "He said you'd get lost twice.", e.translation, True, lost, e.who)
             if e.original == lost else e for e in entries]
    fixed = FESTIVAL.replace(lost, "He said you'd get lost twice.")
    assert _status(match(_texts(tmp_path, fixed.replace("festival", "fair")), fuzzy),
                   "He said you'd get lost twice.") == (C, "T:" + lost, lost, 2)
    assert _status(match(_texts(tmp_path, fixed.replace("twice.", "twice!")), fuzzy),
                   "He said you'd get lost twice!") == (C, "T:" + lost, lost, 3)

    # Rule 1 on a non-script key: a changed stored original → Changed with Was; an
    # untranslated entry stays New; the key never moves to a script text (families).
    word = SourceText("word:back", TextKind.WORD, "Go back", "word")
    line = SourceText("start/aaaaaaaaaaaa", TextKind.LINE, "Back", "start")
    result = match([word, line], [Entry("word:back", "Back", "Zurück"),
                                  Entry("word:gone", "Back", "Zurück")])
    assert _status(result, "Go back") == (C, "Zurück", "Back", 1)
    assert _status(result, "Back") == (N, "", None, 4) and result.unused == (1,)
    assert match([word], [Entry("word:back", "Back")]).rows[0].status is N

    # Rule 3's caps: only the first 64 candidates (file order) are compared, and only the
    # first 1,000 tag-stripped characters.
    near = SourceText("s/new", TextKind.LINE, "The lantern floats away", "s")
    far = [Entry(f"s/{i:03}", f"zzzz {i}", "T") for i in range(CANDIDATES_MAX)]
    good = Entry("s/good", "The lanterns float away", "T:good")
    assert match([near], far + [good]).rows[0].status is N
    assert match([near], far[1:] + [good]).rows[0].translation == "T:good"
    long_a = SourceText("s/a", TextKind.LINE, "x" * COMPARE_CHARS + "a" * 3000, "s")
    long_b = Entry("s/b", "{b}" + "x" * COMPARE_CHARS + "{/b}" + "b" * 3000, "T:long")
    assert match([long_a], [long_b]).rows[0].translation == "T:long"

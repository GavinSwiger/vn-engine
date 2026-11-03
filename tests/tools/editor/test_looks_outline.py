"""F32 step 6: Studio's Outline "Looks" group and the story map's "deletes saves" note
(``specs/F32-dynamic-ui/06-acceptance.md`` AC-F32-25).

On ``tests/fixtures/F32/walk/`` (Template U's config.toml with the walk script), through the
check child's name rows (``style``, ``style_use``, ``playthrough``, ``ui_delete``)."""

from pathlib import Path

import engine.script  # noqa: F401  registers every statement and the docs table
from engine.tools.editor.outline import DELETES_SAVES, NOT_USED, outline
from engine.tools.editor.storymap import MARK_DELETES_SAVES, label_notes, layout
from tests.tools.f45_games import check

WALK = Path(__file__).resolve().parents[2] / "fixtures" / "F32" / "walk"
MAIN = "script/main.vns"


def _tree(row) -> tuple:
    return (row.text, row.file, row.line, tuple(_tree(c) for c in row.children))


def test_ac_f32_25_outline_looks_and_the_deletes_saves_map_note(tmp_path):
    names = check(WALK, launch=False).names
    rows = outline(names)
    looks = rows[-1]
    assert _tree(looks) == ("Looks (4)", None, None, (
        ("style ashes (1)", None, None, (("ui style ashes", MAIN, 5, ()),)),
        (f"style calm {NOT_USED}", None, None, ()),
        ("playthrough 2", "config.toml", 7, ()),
        (f"ui delete saves: {DELETES_SAVES}", MAIN, 15, ())))

    notes = label_notes(names["label"], names)
    assert notes["start"].deletes_saves
    box = layout([], names["label"], notes=notes).boxes[0]
    assert box.name == "start" and MARK_DELETES_SAVES in box.marks

    # No styles, no playthrough tables, no wipe: no Looks group, no note.
    bare = tmp_path / "bare"
    (bare / "script").mkdir(parents=True)
    (bare / "script" / "main.vns").write_text('label start:\n    "Hi."\n', encoding="utf-8")
    (bare / "config.toml").write_text('[game]\ntitle = "Bare"\n', encoding="utf-8")
    plain = check(bare, launch=False).names
    assert not any(row.text.startswith("Looks") for row in outline(plain))
    assert not any(n.deletes_saves for n in label_notes(plain["label"], plain).values())

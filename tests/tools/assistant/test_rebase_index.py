"""F58: ``edits.rebase`` reuses the editor's ``SceneIndex`` digests (main-session ruling on
P0's ``rebase`` row, 04 changelog). With an index of the live text it gives exactly what
the digest-everything path gives, preamble edits included."""

from engine.tools.assistant import edits
from engine.tools.editor import scenes
from tests.tools.assistant.assist_games import pane, studio

CH2 = "script/ch2.vns"
NOTE = "# Chapter two"


def _change(old: str, new: str) -> dict:
    return {"file": CH2, "old_text": old, "new_text": new}


def test_f58_rebase_with_a_scene_index_matches_the_full_digest(tmp_path):
    game = studio(tmp_path)
    text = NOTE + "\n" + (game / "script" / "ch2.vns").read_text(encoding="utf-8").rstrip("\n")
    body = edits.propose(pane(game, {CH2: text}),
                         {"summary": "s", "changes": [_change("The river.", "The wide river.")]},
                         check=False).files[0]
    top = edits.propose(pane(game, {CH2: text}),
                        {"summary": "s", "changes": [_change(NOTE, NOTE + " (draft)")]},
                        check=False).files[0]
    assert top.touched == ((None,),) and top.preamble is not None
    moved = text.replace("label club:", 'label intro:\n    "Hi."\nlabel club:')
    lives = [text, moved, "# a note\n" + text, text.replace("The river.", "The stream."),
             text.replace("label river:", "label river:\n    pause 1"), text + "\n"]
    for file in (body, top):
        for live in lives:
            index = scenes.reindex(None, CH2, live, 1, checked=None)
            assert edits.rebase(file, live, index=index) == edits.rebase(file, live), live
    index = scenes.reindex(None, CH2, moved, 1, checked=None)
    assert edits.rebase(body, moved, index=index) is not None
    assert edits.rebase(top, moved, index=index) is not None
    noted = "# a note\n" + text
    assert edits.rebase(top, noted, index=scenes.reindex(None, CH2, noted, 1,
                                                          checked=None)) is None

"""F48 step S5: ``apply_edit`` and ``undo_apply`` (AC-F48-17, 23, 25; 04 §7.4; SEC-F48-02,
SEC-F48-03; AB-03, AB-05; ADR-0008 Amendment 5 as accepted in 07 I-5)."""

import os
import shutil


from engine.tools.assistant import diskapply
from engine.tools.assistant.diskapply import (
    GONE, NOTHING_TO_UNDO, PROPOSALS_KEPT, ProposalStore, UNDO_CHANGED)
from engine.tools.assistant.tools import MODE_MCP, ToolBox
from tests.tools.assistant.assist_games import disk, studio, tree
from tests.tools.editor.conftest import link_dir, try_link_file

CH2 = "script/ch2.vns"
MAIN = "script/main.vns"


def box_for(game, workspace=None) -> tuple[ToolBox, ProposalStore]:
    workspace = workspace or disk(game)
    store = ProposalStore(workspace)
    return ToolBox(workspace, MODE_MCP, writer=store), store


def propose(box: ToolBox, *changes: tuple[str, str, str]) -> str:
    """The id of a proposal of ``changes`` (file, old_text, new_text)."""
    shown = box.call("propose_edit", {"summary": "s", "changes": [
        {"file": f, "old_text": old, "new_text": new} for f, old, new in changes]})
    assert not shown.is_error, shown.text
    return shown.text.split("\n")[1].removeprefix("id: ")


def apply(box: ToolBox, found: str):
    return box.call("apply_edit", {"id": found})


# --- AC-F48-17: new refs, and a folder swapped for a junction ---------------------------------

def test_ac17_bad_new_refs_and_a_junctioned_script_folder_are_refused(tmp_path):
    game = studio(tmp_path)
    box, _ = box_for(game)
    (game / "script" / "sub").mkdir()
    rows = {"script/con.vns": "`con.vns` can't be used as a file name",
            "script/a.vns.": "`a.vns.` can't be used as a file name",
            "script/x:y.vns": "`x:y.vns` can't be used as a file name",
            "script/evil\u202egnp.vns": "`evil\\u202egnp.vns` can't be used as a file name",
            "script/CH2.vns": "`script/CH2.vns` already exists.",
            "script/sub/../ch9.vns": "`ch9.vns` can't be used as a file name",
            "script/later/x.vns": "`script/later/` can't be found."}
    for ref, text in rows.items():
        shown = box.call("propose_edit", {"summary": "s", "changes": [
            {"file": ref, "old_text": "", "new_text": "label x:\n"}]})
        assert shown.is_error and shown.text.startswith(text), (ref, shown.text)
    assert not (game / "script" / "later").exists()
    # script/ swapped for a junction between propose and apply: nothing is written anywhere.
    edit = propose(box, (CH2, "jump river", "jump bridge"))
    made = propose(box, ("script/fresh.vns", "", 'label fresh:\n    "New."\n'))
    outside = tmp_path / "outside"
    shutil.copytree(game / "script", outside)
    before = tree(outside)
    os.rename(game / "script", tmp_path / "script_moved")
    link_dir(game / "script", outside)
    for found in (edit, made):
        refused = apply(box, found)
        assert refused.is_error and refused.text == (
            "`script/` is a link or not a folder, so Studio won't add files there."), \
            refused.text
    assert tree(outside) == before


# --- AC-F48-23: what apply writes, and when it writes nothing ---------------------------------

def test_ac23_apply_writes_exactly_and_refuses_stale_linked_used_or_evicted_ids(tmp_path):
    game = studio(tmp_path)
    box, store = box_for(game)
    main = game / "script" / "main.vns"
    old = main.read_bytes().replace(b"\n", b"\r\n")
    main.write_bytes(b"\xef\xbb\xbf" + old)
    found = propose(box, (MAIN, "    jump bridge", "    jump river"))
    assert apply(box, found).text == (
        "Wrote script/main.vns. undo_apply undoes it while those files stay as written.")
    assert main.read_bytes() == b"\xef\xbb\xbf" + old.replace(b"jump bridge", b"jump river")
    assert not [p for p in (game / "script").iterdir() if p.name.endswith(".tmp")]
    # The same id twice, and an id from another session.
    assert apply(box, found).text == GONE
    other_box, _ = box_for(game)
    stranger = propose(other_box, (CH2, "jump river", "jump bridge"))
    assert apply(box, stranger).text == GONE
    assert box.call("apply_edit", {"id": 7}).text == GONE
    # Edited on disk after the proposal: nothing is written.
    ch2 = game / "script" / "ch2.vns"
    found = propose(box, (CH2, "jump river", "jump bridge"))
    edited = ch2.read_bytes().replace(b"You stay.", b"You stay here.")
    ch2.write_bytes(edited)
    refused = apply(box, found)
    assert refused.is_error and refused.text.startswith("script/ch2.vns changed after")
    assert ch2.read_bytes() == edited
    # Replaced by a link to a sentinel: refused, the sentinel untouched.
    found = propose(box, (CH2, "jump river", "jump bridge"))
    sentinel = tmp_path / "sentinel.vns"
    sentinel.write_bytes(edited)
    ch2.unlink()
    if not try_link_file(ch2, sentinel):
        (tmp_path / "sentinel_dir").mkdir()
        link_dir(ch2, tmp_path / "sentinel_dir")
    refused = apply(box, found)
    assert refused.is_error and refused.text == (
        "`script/ch2.vns` is a link or not a regular file, so Studio won't change it.")
    assert sentinel.read_bytes() == edited
    # The 51st proposal evicts the first.
    game2 = studio(tmp_path, "second")
    box2, _ = box_for(game2)
    ids = [propose(box2, (CH2, "jump river", f"jump r{n}")) for n in range(PROPOSALS_KEPT + 1)]
    assert apply(box2, ids[0]).text == GONE
    assert not apply(box2, ids[1]).is_error


def test_ac23_a_failure_after_a_write_names_the_files_written(tmp_path, monkeypatch):
    game = studio(tmp_path)
    box, _ = box_for(game)
    found = propose(box, (MAIN, "    jump bridge", "    jump river"),
                    (CH2, '"The river."', '"The wide river."'))
    real = diskapply.safefile.write_atomic
    calls = []

    def second_fails(target, pieces, **kwargs):
        calls.append(target)
        if len(calls) == 2:
            raise PermissionError(13, "locked")
        return real(target, pieces, **kwargs)
    monkeypatch.setattr(diskapply.safefile, "write_atomic", second_fails)
    shown = apply(box, found)
    assert shown.is_error and shown.text == (
        "Wrote script/main.vns, then stopped: Couldn't change `script/ch2.vns`: the file is "
        "read-only or locked.")
    assert b"jump river" in (game / "script" / "main.vns").read_bytes()
    assert b"The wide river" not in (game / "script" / "ch2.vns").read_bytes()


# --- AC-F48-25: undo_apply --------------------------------------------------------------------

def test_ac25_undo_restores_bytes_and_removes_created_files_only_while_unchanged(tmp_path):
    game = studio(tmp_path)
    box, _ = box_for(game)
    before = tree(game)
    assert box.call("undo_apply", {}).text == NOTHING_TO_UNDO
    found = propose(box, (MAIN, 'include "ch2.vns"', 'include "ch2.vns"\ninclude "ch3.vns"'),
                    ("script/ch3.vns", "", 'label three:\n    "Three."\n'))
    assert not apply(box, found).is_error
    new = game / "script" / "ch3.vns"
    assert new.read_bytes() == b'label three:\n    "Three."\n'
    assert box.call("undo_apply", {}).text == "Undid the change to script/main.vns, script/ch3.vns."
    assert tree(game) == before
    # Refused once a file changed: nothing is restored or removed.
    found = propose(box, (MAIN, 'include "ch2.vns"', 'include "ch2.vns"\ninclude "ch3.vns"'),
                    ("script/ch3.vns", "", 'label three:\n    "Three."\n'))
    assert not apply(box, found).is_error
    new.write_bytes(b'label three:\n    "Changed by the author."\n')
    main = (game / "script" / "main.vns").read_bytes()
    refused = box.call("undo_apply", {})
    assert refused.is_error and refused.text == UNDO_CHANGED.format(file="script/ch3.vns")
    assert new.exists() and (game / "script" / "main.vns").read_bytes() == main
    assert box.call("undo_apply", {"all": True}).is_error


def test_apply_creates_files_only_in_a_folder_that_still_exists(tmp_path):
    game = studio(tmp_path)
    box, _ = box_for(game)
    found = propose(box, ("script/fresh.vns", "", "label fresh:\n    return\n"))
    shutil.rmtree(game / "script")
    refused = apply(box, found)
    assert refused.is_error and refused.text == "`script/` can't be found."
    assert not (game / "script").exists()                 # new_script never made it

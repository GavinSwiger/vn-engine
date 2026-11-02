"""Editor documents, headless: exact-bytes round trips, line-local edits, atomic saves,
containment at save time, read-only opens (F44 ``04`` §7.2, TR-F44-03, TR-F44-04, I-1, I-2,
I-13). The unit rows of AC-F44-14, AC-F44-16, AC-F44-17; the open half of AC-F44-15."""

import dataclasses
import errno
import os
import re
import stat
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script.diagnostics import ScriptError
from engine.script.messages import format_message
from engine.script.source import LineCursor, decode_script
from engine.tools.editor import document
from engine.tools.editor.document import (
    CANT_READ,
    OUTSIDE_AT_OPEN,
    OUTSIDE_AT_SAVE,
    SaveError,
    ScriptDocument,
    encode,
    list_scripts,
    open_document,
    save,
)
from tests.fixtures.F44.byte_variants import BOM, VARIANTS
from tests.tools.editor.conftest import files_under, link_dir, link_file

_LINE = re.compile(rb"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
LONG = [name for name, data in VARIANTS.items() if data.count(b"label") and len(
    _LINE.findall(data)) >= 6]


def split_keep(data: bytes) -> list[tuple[bytes, bytes]]:
    """(line, ending) pairs of file bytes, BOM removed."""
    if data.startswith(BOM):
        data = data[len(BOM):]
    pairs = []
    for piece in _LINE.findall(data):
        body = piece.rstrip(b"\r\n")
        pairs.append((body, piece[len(body):]))
    return pairs


def f02_line_count(data: bytes) -> int:
    cursor = LineCursor(decode_script("script/x.vns", data).text)
    while cursor.next() is not None:
        pass
    return cursor.lines_read


def editor_line_count(doc: ScriptDocument, data: bytes) -> int:
    """Lines a Text widget holds after inserting doc.text, counted like F02 (an empty file
    has none)."""
    body = data[len(BOM):] if data.startswith(BOM) else data
    return 0 if not body else doc.text.count("\n") + 1


def opened(game: Path, ref: str) -> ScriptDocument:
    doc = open_document(GamePaths.for_game(game), ref)
    assert isinstance(doc, ScriptDocument), doc
    return doc


def put(game: Path, ref: str, data: bytes) -> Path:
    path = game / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def temp_files(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.name.endswith(".tmp"))


# --- AC-F44-14: saving changes only the edits ------------------------------------------------

def test_unedited_text_encodes_to_the_original_bytes_and_counts_lines_like_f02(route_game):
    for name, data in VARIANTS.items():
        put(route_game, f"script/{name}.vns", data)
        doc = opened(route_game, f"script/{name}.vns")
        assert encode(doc, doc.text) == data, name
        assert "\r" not in doc.text and not doc.text.startswith("﻿"), name
        assert editor_line_count(doc, data) == f02_line_count(data), name


def test_replace_insert_and_delete_change_only_their_lines(route_game):
    for name in LONG:
        data = VARIANTS[name]
        put(route_game, f"script/{name}.vns", data)
        doc = opened(route_game, f"script/{name}.vns")
        before = split_keep(data)
        # Replacing a word changes only that line, which keeps its own ending.
        lines = doc.text.split("\n")
        lines[2] = lines[2] + " edited"
        out = split_keep(encode(doc, "\n".join(lines)))
        assert out == [*before[:2], (before[2][0] + b" edited", before[2][1]), *before[3:]], name
        assert encode(doc, "\n".join(lines)).startswith(BOM) == data.startswith(BOM), name
        # An inserted line uses the dominant ending.
        lines = doc.text.split("\n")
        lines.insert(3, '    "New line."')
        expected = before[:3] + [(b'    "New line."', doc.newline.encode())] + before[3:]
        assert split_keep(encode(doc, "\n".join(lines))) == expected, name
        # Deleting a line leaves the others.
        lines = doc.text.split("\n")
        del lines[2]
        assert split_keep(encode(doc, "\n".join(lines))) == before[:2] + before[3:], name


def test_mixed_endings_are_kept_per_line(route_game):
    put(route_game, "script/V4.vns", VARIANTS["V4"])
    doc = opened(route_game, "script/V4.vns")
    assert doc.mixed and doc.final_newline
    assert doc.newline == "\r\n"            # a three-way tie goes to the first seen (line 1)
    endings = [ending for _, ending in split_keep(VARIANTS["V4"])]
    assert endings == [{0: b"\n", 1: b"\r\n", 2: b"\r"}[i % 3] for i in range(1, 13)]


def test_edit_then_undo_then_save_gives_the_original_bytes(route_game):
    path = put(route_game, "script/V4.vns", VARIANTS["V4"])
    doc = opened(route_game, "script/V4.vns")
    original = doc.text
    lines = original.split("\n")
    lines[5] = "    changed"
    lines.insert(8, "    added")
    save(doc, "\n".join(lines))
    save(doc, original)                     # the undo, saved
    assert path.read_bytes() == VARIANTS["V4"]


def test_non_bmp_characters_are_written_as_utf8(route_game):
    path = put(route_game, "script/emoji.vns", b'"a"\n')
    doc = opened(route_game, "script/emoji.vns")
    joined = encode(doc, '"\U0001F600"')
    paired = encode(doc, '"😀"')   # Tk 8.6 may return a surrogate pair
    assert joined == paired == b'"\xf0\x9f\x98\x80"\n'
    assert b"\xed\xa0" not in paired and b"\xed\xb0" not in paired
    save(doc, '"😀"')
    assert path.read_bytes() == b'"\xf0\x9f\x98\x80"\n'


def test_a_lone_surrogate_is_refused_and_the_file_is_unchanged(route_game):
    path = route_game / "script/chapter2.vns"
    before = path.read_bytes()
    doc = opened(route_game, "script/chapter2.vns")
    with pytest.raises(SaveError) as caught:
        encode(doc, '"\ud83d"')
    assert "contains a character that can't be saved as UTF-8" in caught.value.message
    with pytest.raises(SaveError):
        save(doc, doc.text + "\ud83d")
    assert path.read_bytes() == before
    assert temp_files(path.parent) == []


def test_stray_carriage_returns_become_line_breaks(route_game):
    put(route_game, "script/crlf.vns", b"a\r\nb\r\n")
    doc = opened(route_game, "script/crlf.vns")
    assert encode(doc, "a\r\nx\ry") == b"a\r\nx\r\ny\r\n"


# --- Open (04 §7.2 Open, UI-F44-12; the open half of AC-F44-15) ------------------------------

def test_open_records_how_the_file_was_written(route_game):
    put(route_game, "script/V2.vns", VARIANTS["V2"])
    doc = opened(route_game, "script/V2.vns")
    assert (doc.bom, doc.newline, doc.final_newline, doc.mixed) == (True, "\r\n", False, False)
    assert doc.old_lines is None and doc.old_endings is None
    assert not doc.dirty
    st = os.stat(route_game / "script/V2.vns")
    assert doc.stamp == (st.st_mtime_ns, st.st_size)
    assert doc.real_path == (route_game / "script/V2.vns").resolve()
    assert doc.text.split("\n")[0] == "label start:"


def test_invalid_utf8_opens_read_only_with_f02s_message(route_game):
    put(route_game, "script/chapter2.vns", b"a\nb\nc\nbad \xff byte\ne\n")
    err = open_document(GamePaths.for_game(route_game), "script/chapter2.vns")
    assert isinstance(err, ScriptError) and err.code == "E01a"
    assert err.format() == f"script/chapter2.vns, line 4: {format_message('E01a')}"
    assert err.source_line == "bad � byte"


def test_a_file_over_16_mib_opens_read_only(route_game):
    path = route_game / "script/chapter2.vns"
    with open(path, "wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    err = open_document(GamePaths.for_game(route_game), "script/chapter2.vns")
    assert isinstance(err, ScriptError) and err.code == "E05"
    assert err.format() == format_message("E05", ("script/chapter2.vns",))


@pytest.mark.parametrize("data, code, args", [
    (b"\xff\xfel\x00", "E01b", ("script/chapter2.vns", "UTF-16")),
    (b"\x89PNG\r\n\x1a\nrest", "E02", ("script/chapter2.vns",)),
])
def test_other_encodings_and_binaries_open_read_only(route_game, data, code, args):
    put(route_game, "script/chapter2.vns", data)
    err = open_document(GamePaths.for_game(route_game), "script/chapter2.vns")
    assert isinstance(err, ScriptError) and err.code == code
    assert err.format() == format_message(code, args)


def test_a_missing_file_opens_read_only(route_game):
    err = open_document(GamePaths.for_game(route_game), "script/gone.vns")
    assert isinstance(err, ScriptError)
    assert err.format() == CANT_READ.format(ref="script/gone.vns")


def test_a_file_reached_through_a_link_out_of_script_opens_read_only(route_game, outside):
    (outside / "x.vns").write_bytes(b'"x"\n')
    link_dir(route_game / "script" / "ext", outside)
    err = open_document(GamePaths.for_game(route_game), "script/ext/x.vns")
    assert isinstance(err, ScriptError) and err.format() == OUTSIDE_AT_OPEN


def test_a_file_linked_from_script_to_elsewhere_in_the_game_opens_read_only(route_game):
    (route_game / "elsewhere").mkdir()
    (route_game / "elsewhere" / "x.vns").write_bytes(b'"x"\n')
    link_dir(route_game / "script" / "ext", route_game / "elsewhere")
    err = open_document(GamePaths.for_game(route_game), "script/ext/x.vns")
    assert isinstance(err, ScriptError) and err.format() == OUTSIDE_AT_OPEN


def test_only_vns_files_under_script_are_opened(route_game):
    paths = GamePaths.for_game(route_game)
    for ref in ("config.toml", "script/notes.txt", "game/main.vns"):
        with pytest.raises(ValueError):
            open_document(paths, ref)


# --- File order (I-13) ---------------------------------------------------------------------

def test_files_are_listed_main_first_then_case_folded(route_game, outside):
    put(route_game, "script/Zeta.vns", b"")
    put(route_game, "script/alpha.vns", b"")
    put(route_game, "script/notes.txt", b"")
    (outside / "x.vns").write_bytes(b"")
    assert list_scripts(GamePaths.for_game(route_game)) == [
        "script/main.vns", "script/alpha.vns", "script/chapter2.vns", "script/chapter3.vns",
        "script/routes/hana.vns", "script/Zeta.vns"]


def test_links_out_of_script_are_not_listed(route_game, outside):
    (outside / "x.vns").write_bytes(b"")
    link_dir(route_game / "script" / "ext", outside)
    refs = list_scripts(GamePaths.for_game(route_game))
    assert refs == ["script/main.vns", "script/chapter2.vns", "script/chapter3.vns",
                    "script/routes/hana.vns"]


def test_no_script_folder_lists_nothing(tmp_path):
    (tmp_path / "empty_game").mkdir()
    assert list_scripts(GamePaths.for_game(tmp_path / "empty_game")) == []


# --- AC-F44-16: saves are atomic, and failures lose nothing ----------------------------------

def test_a_successful_save_writes_encode_and_leaves_no_temp_file(route_game):
    path = route_game / "script/chapter2.vns"
    if os.name == "posix":
        os.chmod(path, 0o640)
    doc = opened(route_game, "script/chapter2.vns")
    doc.dirty = True
    text = doc.text.replace("Done.", "Done!")
    save(doc, text)
    assert path.read_bytes() == encode(doc, text)
    assert temp_files(path.parent) == []
    assert doc.dirty is False
    st = os.stat(path)
    assert doc.stamp == (st.st_mtime_ns, st.st_size)
    if os.name == "posix":
        assert stat.S_IMODE(st.st_mode) == 0o640


def _fail(code: int):
    def raiser(*_args, **_kwargs):
        raise OSError(code, os.strerror(code))
    return raiser


@pytest.mark.parametrize("where, code, reason", [
    ("_write_all", errno.ENOSPC, "the disk is full."),
    ("replace", errno.EACCES, "the file is read-only or locked."),
    ("fsync", errno.EIO, "the system reported an error."),
])
def test_a_failed_save_keeps_the_original_and_leaves_no_temp_file(
        route_game, monkeypatch, where, code, reason):
    path = route_game / "script/chapter2.vns"
    before = path.read_bytes()
    doc = opened(route_game, "script/chapter2.vns")
    doc.dirty = True
    stamp = doc.stamp
    target = document if where == "_write_all" else document.os
    monkeypatch.setattr(target, where, _fail(code))
    with pytest.raises(SaveError) as caught:
        save(doc, doc.text + "\nmore")
    monkeypatch.undo()
    assert caught.value.message == f"Couldn't save `script/chapter2.vns`: {reason}"
    assert str(route_game) not in caught.value.message
    assert path.read_bytes() == before
    assert temp_files(path.parent) == []
    assert doc.dirty is True and doc.stamp == stamp


def test_a_read_only_file_is_refused(route_game):
    path = route_game / "script/chapter2.vns"
    before = path.read_bytes()
    doc = opened(route_game, "script/chapter2.vns")
    os.chmod(path, stat.S_IREAD)
    try:
        if os.access(path, os.W_OK):
            pytest.skip("running with rights that ignore read-only files")
        with pytest.raises(SaveError) as caught:
            save(doc, doc.text + "\nmore")
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    assert caught.value.message == "Couldn't save `script/chapter2.vns`: the file is read-only."
    assert path.read_bytes() == before
    assert temp_files(path.parent) == []


# --- AC-F44-17: writes stay inside the real script/ folder (unit rows) -----------------------

@pytest.mark.parametrize("where", ["images", "outside"])
def test_save_refuses_a_target_outside_script(route_game, outside, where):
    # Row 1 as amended by F45 (A-17): config.toml is saved only through open_config.
    target = route_game / "images" / "a.vns" if where == "images" else outside / "a.vns"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(b'"a"\n')
    before = target.read_bytes()
    doc = opened(route_game, "script/chapter2.vns")
    doc = dataclasses.replace(doc, real_path=target.resolve())
    with pytest.raises(SaveError) as caught:
        save(doc, "changed")
    assert caught.value.reason == OUTSIDE_AT_SAVE
    assert target.read_bytes() == before
    assert temp_files(target.parent) == []


def test_a_folder_swapped_for_a_link_after_open_is_not_written(route_game, outside):
    (outside / "hana.vns").write_bytes(b"outside\n")
    doc = opened(route_game, "script/routes/hana.vns")
    routes = route_game / "script" / "routes"
    routes.rename(route_game / "script" / "routes_old")
    link_dir(routes, outside)
    with pytest.raises(SaveError) as caught:
        save(doc, doc.text + "\nmore")
    assert caught.value.message == f"Couldn't save `script/routes/hana.vns`: {OUTSIDE_AT_SAVE}"
    assert (outside / "hana.vns").read_bytes() == b"outside\n"
    assert files_under(outside) == {"hana.vns"}


def test_a_file_swapped_for_a_symlink_after_open_is_not_written(route_game, outside):
    (outside / "c2.vns").write_bytes(b"outside\n")
    doc = opened(route_game, "script/chapter2.vns")
    path = route_game / "script" / "chapter2.vns"
    path.rename(route_game / "script" / "chapter2.old")
    link_file(path, outside / "c2.vns")
    with pytest.raises(SaveError) as caught:
        save(doc, doc.text + "\nmore")
    assert caught.value.reason == OUTSIDE_AT_SAVE
    assert (outside / "c2.vns").read_bytes() == b"outside\n"
    assert files_under(outside) == {"c2.vns"}
    assert os.path.islink(path)


def test_a_planted_link_at_the_temp_name_is_never_followed(route_game, outside, monkeypatch):
    path = route_game / "script" / "chapter2.vns"
    before = path.read_bytes()
    doc = opened(route_game, "script/chapter2.vns")
    link_file(route_game / "script" / ".chapter2.vns.deadbeef.tmp", outside / "t")
    monkeypatch.setattr(document, "_temp_token", lambda: "deadbeef")
    with pytest.raises(SaveError):
        save(doc, doc.text + "\nmore")
    assert not (outside / "t").exists()
    assert files_under(outside) == set()
    assert path.read_bytes() == before


def test_a_planted_directory_link_at_the_temp_name_is_never_followed(
        route_game, outside, monkeypatch):
    path = route_game / "script" / "chapter2.vns"
    before = path.read_bytes()
    doc = opened(route_game, "script/chapter2.vns")
    link_dir(route_game / "script" / ".chapter2.vns.deadbeef.tmp", outside)
    monkeypatch.setattr(document, "_temp_token", lambda: "deadbeef")
    with pytest.raises(SaveError):
        save(doc, doc.text + "\nmore")
    assert files_under(outside) == set()
    assert path.read_bytes() == before


def test_a_file_swapped_for_a_directory_link_is_not_written(route_game, outside):
    doc = opened(route_game, "script/chapter2.vns")
    path = route_game / "script" / "chapter2.vns"
    path.rename(route_game / "script" / "chapter2.old")
    link_dir(path, outside)
    with pytest.raises(SaveError) as caught:
        save(doc, doc.text + "\nmore")
    assert caught.value.reason == OUTSIDE_AT_SAVE
    assert files_under(outside) == set()


def test_a_taken_temp_name_is_retried_with_another(route_game, monkeypatch):
    path = route_game / "script" / "chapter2.vns"
    planted = route_game / "script" / ".chapter2.vns.deadbeef.tmp"
    planted.write_bytes(b"planted")
    tokens = iter(["deadbeef", "deadbeef", "0badf00d"])
    monkeypatch.setattr(document, "_temp_token", lambda: next(tokens))
    doc = opened(route_game, "script/chapter2.vns")
    save(doc, "new text")
    assert path.read_bytes() == b"new text\n"
    assert planted.read_bytes() == b"planted"
    assert temp_files(path.parent) == [planted.name]


def test_a_file_deleted_after_open_is_not_recreated(route_game):
    path = route_game / "script" / "chapter2.vns"
    doc = opened(route_game, "script/chapter2.vns")
    path.unlink()
    with pytest.raises(SaveError):
        save(doc, "text")
    assert not path.exists()
    assert temp_files(path.parent) == []

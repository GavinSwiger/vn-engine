"""F31 step 1 — the writer's ``meta`` owner (``06`` AC-F31-06; PR-F31-03, -07, -09;
TR-F31-04; ``04`` §6.4 Writer; ``07`` I-1, I-2): ``FileRemove`` for ``meta`` only, a missing
root never created by a delete, the dev folder rule in every run, and ``drop_queued``.

Link rows run where the OS allows: symlinks need a privilege on Windows (skipped without
it); junctions are Windows only (directory symlinks elsewhere)."""

import os
import re
import sys
import threading
from pathlib import Path

import pytest

from engine.core import safefile
from engine.core.paths import META_NAME_RE
from engine.core.safefile import RemoveKind
from engine.persist.writer import (COULDNT_WRITE, FOLDER_IS_LINK, META, SAVE, STOPPED_DETAIL,
                                   Failed, FileRemove, FileRemoved, FileWrite, FileWritten)
from tests.persist.writer_support import JOIN_TIMEOUT_S, writers  # noqa: F401  (fixture)

WINDOWS = sys.platform == "win32"
SLOT_RE = re.compile(r"[0-9]\.vnsave", re.ASCII)


def _dir_link(link: Path, target: Path) -> None:
    """A junction on Windows, else a directory symlink."""
    if WINDOWS:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        return
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks are not permitted here: {exc}")


def _file_symlink(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks are not permitted here: {exc}")


def _tree(folder: Path) -> dict[str, bytes | None]:
    return {p.relative_to(folder).as_posix(): (p.read_bytes() if p.is_file() else None)
            for p in sorted(folder.rglob("*"))}


ROWS = ["remove_root_missing", "remove_regular", "remove_file_symlink", "remove_dir_link",
        "remove_real_folder", "remove_none", "remove_root_junction", "remove_from_save",
        "write_release_root_junction", "write_release_via_link", "write_root_made",
        "write_parent_missing", "drop_queued"]


@pytest.mark.parametrize("row", ROWS)
def test_ac_f31_06_writer_owner_meta(row, tmp_path, writers, monkeypatch):  # noqa: F811
    base = tmp_path.resolve()
    game = base / "game"
    game.mkdir()
    root = game / "characters"
    outside = base / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_bytes(b"keep")
    (outside / "secret.txt").write_bytes(b"secret")
    saves = game / "saves"
    saves.mkdir()
    (saves / "1.vnsave").write_bytes(b"save")
    w = writers(threaded=(row == "drop_queued"))
    meta = w.client(META, root=root, names=META_NAME_RE)
    save = w.client(SAVE, root=saves, names=SLOT_RE)
    outside_before = _tree(outside)

    def run(client, job):
        client.submit(job)
        [result] = client.take()
        return result

    if row == "remove_root_missing":
        result = run(meta, FileRemove(root, "hana.chr", token=4))
        assert result == FileRemoved(4, RemoveKind.MISSING)
        assert not root.exists()
    elif row.startswith("remove_") and row not in ("remove_root_junction", "remove_from_save"):
        root.mkdir()
        entry = root / "hana.chr"
        expected = RemoveKind.REMOVED
        if row == "remove_regular":
            entry.write_bytes(b"x")
        elif row == "remove_file_symlink":
            _file_symlink(entry, outside / "secret.txt")
        elif row == "remove_dir_link":
            _dir_link(entry, outside)
        elif row == "remove_real_folder":
            entry.mkdir()
            (entry / "inner.txt").write_bytes(b"inner")
            expected = RemoveKind.NOT_FILE_OR_LINK
        else:
            expected = RemoveKind.MISSING
        assert run(meta, FileRemove(root, "hana.chr", token=7)) == FileRemoved(7, expected)
        if row == "remove_real_folder":
            assert (entry / "inner.txt").read_bytes() == b"inner"
        else:
            assert not os.path.lexists(entry)
    elif row == "remove_root_junction":
        target = outside / "Documents"
        target.mkdir()
        (target / "hana.chr").write_bytes(b"theirs")
        _dir_link(root, target)
        result = run(meta, FileRemove(root, "hana.chr", token=2))
        assert result == Failed(FOLDER_IS_LINK, "", 2)
        assert (target / "hana.chr").read_bytes() == b"theirs"
        (target / "hana.chr").unlink()
        target.rmdir()
    elif row == "remove_from_save":
        result = run(save, FileRemove(saves, "1.vnsave", token=3))
        assert isinstance(result, Failed) and result.reason == COULDNT_WRITE
        assert (saves / "1.vnsave").read_bytes() == b"save"
    elif row == "write_release_root_junction":
        target = outside / "Documents"
        target.mkdir()
        _dir_link(root, target)
        result = run(meta, FileWrite(root, "hana.chr", (b"new",), release=False, token=5))
        assert result == Failed(FOLDER_IS_LINK, "", 5)
        assert list(target.iterdir()) == []
        target.rmdir()
    elif row == "write_release_via_link":
        # A release-flagged meta job still uses the dev rule: a root reached through a
        # link above it is refused (TR-F31-04), where a release root would pass.
        root.mkdir()
        linked = base / "linked_game"
        _dir_link(linked, game)
        w2 = writers(threaded=False)
        via = w2.client(META, root=linked / "characters", names=META_NAME_RE)
        result = run(via, FileWrite(linked / "characters", "hana.chr", (b"new",), release=True))
        assert result == Failed(FOLDER_IS_LINK, "", 0)
        assert list(root.iterdir()) == []
    elif row in ("write_root_made", "write_parent_missing"):
        made: list[str] = []
        real_mkdir = os.mkdir
        monkeypatch.setattr(os, "mkdir",
                            lambda p, *a, **k: made.append(str(p)) or real_mkdir(p, *a, **k))
        if row == "write_root_made":
            result = run(meta, FileWrite(root, "hana.chr", (b"HANA",), token=1))
            assert isinstance(result, FileWritten) and result.token == 1
            assert made == [str(root)]
            assert (root / "hana.chr").read_bytes() == b"HANA"
        else:
            deep = base / "gone" / "characters"
            w3 = writers(threaded=False)
            far = w3.client(META, root=deep, names=META_NAME_RE)
            result = run(far, FileWrite(deep, "hana.chr", (b"HANA",)))
            assert isinstance(result, Failed)
            assert not (base / "gone").exists()
    else:                                                # drop_queued
        root.mkdir()
        started: list[str] = []
        entered, go = threading.Event(), threading.Event()
        writers.release(go.set)
        real_write = safefile.write_atomic

        def write_atomic(target, pieces, **kwargs):
            started.append(Path(target).name)
            if len(started) == 1:
                entered.set()
                go.wait(JOIN_TIMEOUT_S)
            return real_write(target, pieces, **kwargs)

        monkeypatch.setattr(safefile, "write_atomic", write_atomic)
        meta.submit(FileWrite(root, "a.txt", (b"a",), token=1))
        assert entered.wait(JOIN_TIMEOUT_S)
        meta.submit(FileWrite(root, "b.txt", (b"b",), token=2))
        save.submit(FileWrite(saves, "2.vnsave", (b"s",), token=9))
        meta.submit(FileRemove(root, "c.txt", token=3))
        meta.submit(FileWrite(root, "d.txt", (b"d",), token=4))
        meta.drop_queued()
        assert meta.take() == [Failed(COULDNT_WRITE, STOPPED_DETAIL, t) for t in (2, 3, 4)]
        assert meta.in_flight == 1 and save.in_flight == 1
        go.set()
        [first] = meta.wait(w.now() + JOIN_TIMEOUT_S)
        assert isinstance(first, FileWritten) and first.token == 1
        [kept] = save.wait(w.now() + JOIN_TIMEOUT_S)
        assert isinstance(kept, FileWritten) and kept.token == 9
        assert started == ["a.txt", "2.vnsave"]          # the dropped jobs never started
        assert sorted(p.name for p in root.iterdir()) == ["a.txt"]
    assert _tree(outside) == outside_before

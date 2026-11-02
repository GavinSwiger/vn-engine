"""``safefile.remove_file`` and ``remove_stale_temps(target_pattern=)`` (F11 C15, ``04``
§7.1 step 4, §7.7 Delete; SEC-F11-08 (a), (b); abuse group F, the entry rows).

``remove_file`` removes the entry itself: a regular file or file link by ``os.unlink``, a
Windows directory link or junction by ``os.rmdir`` on the entry; never a link's target,
never recursively, never a real folder. Faults are injected by patching ``os`` calls inside
``engine.core.safefile`` within a ``monkeypatch.context()``. Symlink rows skip where
symlinks aren't permitted; Windows uses junctions for directory links."""

import ast
import errno
import os
import re
import stat
import time

import pytest

from engine.core import safefile
from engine.core.safefile import (
    RemoveKind,
    remove_file,
    remove_stale_temps,
    temp_name_pattern,
)
from tests.core.test_safefile import SAFEFILE_PATH, Patched, fail_on, link_dir, symlink

NAME = "quick-1.vnsave"
# Stand-in for F11's SLOT_NAME_RE (persist/saves.py arrives in F11 step 3).
SLOT_NAME_RE = re.compile(r"(?:quick|auto)-[1-6]\.vnsave|page(?:[1-9]\d?|100)-[1-6]\.vnsave")


@pytest.fixture
def base(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def outside(base):
    folder = base / "outside"
    folder.mkdir()
    (folder / "keep.txt").write_bytes(b"AikoSecret")
    (folder / "sub").mkdir()
    (folder / "sub" / "deep.txt").write_bytes(b"x")
    return folder


def _snapshot(folder) -> dict[str, bytes]:
    found = {}
    for root, _dirs, files in os.walk(folder):
        for name in files:
            path = os.path.join(root, name)
            with open(path, "rb") as handle:
                found[os.path.relpath(path, folder)] = handle.read()
    return found


class Spy:
    """Records calls to ``os.unlink`` and ``os.rmdir`` (then makes them)."""

    def __init__(self, patch) -> None:
        self.calls: list[tuple[str, str]] = []
        for name in ("unlink", "rmdir"):
            real = getattr(os, name)
            patch.setattr(safefile.os, name, self._wrap(name, real))

    def _wrap(self, name, real):
        def call(path, *args, **kwargs):
            self.calls.append((name, os.fspath(path)))
            return real(path, *args, **kwargs)
        return call


# --- The outcomes are W83's reason words ------------------------------------------------------

def test_the_failure_values_are_the_w83_reasons():
    assert RemoveKind.NOT_FILE_OR_LINK.value == "not a file or link"
    assert RemoveKind.NO_PERMISSION.value == "no permission"
    assert RemoveKind.FAILED.value == "couldn't remove"
    assert RemoveKind.REMOVED.gone and RemoveKind.MISSING.gone
    assert not any(kind.gone for kind in (RemoveKind.NOT_FILE_OR_LINK,
                                          RemoveKind.NO_PERMISSION, RemoveKind.FAILED))


# --- Entries ---------------------------------------------------------------------------------

def test_a_regular_file_is_unlinked_and_nothing_else_changes(base, monkeypatch):
    (base / NAME).write_bytes(b"save")
    (base / "quick-2.vnsave").write_bytes(b"other")
    with monkeypatch.context() as patch:
        spy = Spy(patch)
        assert remove_file(base / NAME) is RemoveKind.REMOVED
    assert spy.calls == [("unlink", os.fspath(base / NAME))]
    assert sorted(os.listdir(base)) == ["quick-2.vnsave"]


def test_a_missing_entry_is_missing(base):
    assert remove_file(base / NAME) is RemoveKind.MISSING
    assert remove_file(base / "nope" / NAME) is RemoveKind.MISSING


@pytest.mark.parametrize("filled", [False, True])
def test_a_real_folder_is_refused_and_kept(base, monkeypatch, filled):
    folder = base / NAME
    folder.mkdir()
    if filled:
        (folder / "inner.txt").write_bytes(b"x")
    with monkeypatch.context() as patch:
        spy = Spy(patch)
        assert remove_file(folder) is RemoveKind.NOT_FILE_OR_LINK
    assert spy.calls == []
    assert folder.is_dir() and (not filled or (folder / "inner.txt").exists())


def test_a_directory_link_is_removed_never_its_target(base, outside, monkeypatch):
    before = _snapshot(outside)
    link_dir(base / NAME, outside)
    with monkeypatch.context() as patch:
        spy = Spy(patch)
        assert remove_file(base / NAME) is RemoveKind.REMOVED
    assert not os.path.lexists(base / NAME)
    assert _snapshot(outside) == before and (outside / "sub").is_dir()
    expected = "rmdir" if os.name == "nt" else "unlink"
    assert spy.calls == [(expected, os.fspath(base / NAME))]


def test_a_file_symlink_is_removed_never_its_target(base, outside):
    symlink(base / NAME, outside / "keep.txt")
    assert remove_file(base / NAME) is RemoveKind.REMOVED
    assert not os.path.lexists(base / NAME)
    assert (outside / "keep.txt").read_bytes() == b"AikoSecret"


def test_a_directory_symlink_is_removed_never_its_target(base, outside):
    before = _snapshot(outside)
    symlink(base / NAME, outside, directory=True)
    assert remove_file(base / NAME) is RemoveKind.REMOVED
    assert not os.path.lexists(base / NAME)
    assert _snapshot(outside) == before


def test_a_hard_link_to_an_outside_file_removes_only_the_slot_name(base, outside):
    try:
        os.link(outside / "keep.txt", base / NAME)
    except OSError as exc:
        pytest.skip(f"hard links not permitted here: {exc}")
    assert remove_file(base / NAME) is RemoveKind.REMOVED
    assert (outside / "keep.txt").read_bytes() == b"AikoSecret"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX-only")
def test_a_fifo_is_refused(base):
    os.mkfifo(base / NAME)
    assert remove_file(base / NAME) is RemoveKind.NOT_FILE_OR_LINK
    assert os.path.lexists(base / NAME)


# Entry kinds by a patched lstat, so every platform's dispatch is checked here.
_LINK = stat.S_IFLNK | 0o777
_DIR = stat.S_IFDIR | 0o777
_SYMLINK_TAG = getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C)
_JUNCTION_TAG = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
_CLOUD_TAG = 0x9000001A                         # IO_REPARSE_TAG_CLOUD: not a link
_REPARSE = 0x400
_DIRECTORY = 0x10


@pytest.mark.parametrize("label,mode,attributes,tag,expected", [
    ("file symlink", _LINK, _REPARSE, _SYMLINK_TAG, "unlink"),
    ("directory symlink", _LINK, _REPARSE | _DIRECTORY, _SYMLINK_TAG,
     "rmdir" if os.name == "nt" else "unlink"),
    ("junction", _DIR, _REPARSE | _DIRECTORY, _JUNCTION_TAG,
     "rmdir" if os.name == "nt" else "unlink"),
    ("cloud folder (not a link)", _DIR, _REPARSE | _DIRECTORY, _CLOUD_TAG, None),
    ("real folder", _DIR, _DIRECTORY, 0, None),
    ("device", stat.S_IFCHR | 0o666, 0, 0, None),
    ("socket", stat.S_IFSOCK | 0o666, 0, 0, None),
    ("regular", stat.S_IFREG | 0o644, 0, 0, "unlink"),
])
def test_dispatch_by_entry_kind(base, monkeypatch, label, mode, attributes, tag, expected):
    (base / NAME).write_bytes(b"x")
    real = os.lstat
    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "lstat", lambda p: Patched(
            real(p), st_mode=mode, st_file_attributes=attributes, st_reparse_tag=tag))
        patch.setattr(safefile.os, "unlink", lambda p: calls.append("unlink"))
        patch.setattr(safefile.os, "rmdir", lambda p: calls.append("rmdir"))
        result = remove_file(base / NAME)
    if expected is None:
        assert result is RemoveKind.NOT_FILE_OR_LINK, label
        assert calls == [], label
    else:
        assert result is RemoveKind.REMOVED, label
        assert calls == [expected], label


# --- Faults ----------------------------------------------------------------------------------

@pytest.mark.parametrize("call,code,expected", [
    ("lstat", errno.EACCES, RemoveKind.NO_PERMISSION),
    ("lstat", errno.EIO, RemoveKind.FAILED),
    ("lstat", errno.ENAMETOOLONG, RemoveKind.FAILED),
    ("unlink", errno.EACCES, RemoveKind.NO_PERMISSION),
    ("unlink", errno.EPERM, RemoveKind.NO_PERMISSION),
    ("unlink", errno.EBUSY, RemoveKind.FAILED),
    ("unlink", errno.EIO, RemoveKind.FAILED),
    ("unlink", errno.EROFS, RemoveKind.FAILED),
    ("unlink", errno.ENOENT, RemoveKind.MISSING),          # raced away: nothing left
    ("unlink", errno.EISDIR, RemoveKind.FAILED),           # swapped for a folder
])
def test_file_faults_never_raise_and_keep_the_file(base, monkeypatch, call, code, expected):
    (base / NAME).write_bytes(b"save")
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, call, fail_on(getattr(os, call), 1, code))
        assert remove_file(base / NAME) is expected
    assert (base / NAME).read_bytes() == b"save"


@pytest.mark.parametrize("code,expected", [
    (errno.EACCES, RemoveKind.NO_PERMISSION),
    (errno.ENOTEMPTY, RemoveKind.FAILED),                  # swapped for a real folder
    (errno.ENOTDIR, RemoveKind.FAILED),
    (errno.ENOENT, RemoveKind.MISSING),
])
def test_directory_link_faults_never_raise_and_keep_the_target(base, outside, monkeypatch,
                                                               code, expected):
    before = _snapshot(outside)
    link_dir(base / NAME, outside)
    name = "rmdir" if os.name == "nt" else "unlink"
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, name, fail_on(getattr(os, name), 1, code))
        assert remove_file(base / NAME) is expected
    assert os.path.lexists(base / NAME)
    assert _snapshot(outside) == before


@pytest.mark.skipif(os.name != "nt", reason="read-only files refuse deletion on Windows only")
def test_a_read_only_file_on_windows_is_no_permission(base):
    path = base / NAME
    path.write_bytes(b"save")
    os.chmod(path, stat.S_IREAD)
    try:
        assert remove_file(path) is RemoveKind.NO_PERMISSION
        assert path.read_bytes() == b"save"
    finally:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


@pytest.mark.skipif(os.name != "nt", reason="an open file blocks deletion on Windows only")
def test_a_file_held_open_without_delete_sharing_is_not_removed(base):
    import _winapi
    path = base / NAME
    path.write_bytes(b"save")
    handle = _winapi.CreateFile(str(path), _winapi.GENERIC_READ, 0, 0,
                                _winapi.OPEN_EXISTING, 0, 0)
    try:
        assert remove_file(path) is RemoveKind.NO_PERMISSION
    finally:
        _winapi.CloseHandle(handle)
    assert path.read_bytes() == b"save"


def test_a_nul_in_the_path_is_failed(base):
    assert remove_file(base / "a\0b") is RemoveKind.FAILED


# --- Never recursive: no shutil, no walk ------------------------------------------------------

def test_safefile_never_removes_recursively():
    tree = ast.parse(SAFEFILE_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    assert "shutil" not in imported
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not attributes & {"rmtree", "removedirs", "walk", "rglob"}


# --- SEC-F11-08 (b): remove_stale_temps(target_pattern=) --------------------------------------

def _old(path, when: float) -> None:
    os.utime(path, (when, when))


def test_temp_name_pattern_for_one_name_is_f12s():
    pattern = temp_name_pattern("persistent.json")
    assert pattern.fullmatch(".persistent.json.deadbeef.tmp")
    for name in (".persistent.json.DEADBEEF.tmp", ".persistentXjson.deadbeef.tmp",
                 ".persistent.json.deadbeef.tmp.x", ".persistent.json.deadbee.tmp"):
        assert not pattern.fullmatch(name), name


@pytest.mark.parametrize("target", [SLOT_NAME_RE, SLOT_NAME_RE.pattern])
def test_temp_name_pattern_for_slot_names(target):
    pattern = temp_name_pattern(target_pattern=target)
    for name in (".quick-1.vnsave.0000000a.tmp", ".auto-6.vnsave.deadbeef.tmp",
                 ".page1-1.vnsave.01234567.tmp", ".page100-6.vnsave.89abcdef.tmp"):
        assert pattern.fullmatch(name), name
    for name in (".QUICK-1.vnsave.0000000a.tmp", ".page0-1.vnsave.0000000a.tmp",
                 ".page101-1.vnsave.0000000a.tmp", ".page03-1.vnsave.0000000a.tmp",
                 ".quick-1.vnsave.bak.0000000a.tmp", ".quick-7.vnsave.0000000a.tmp",
                 ".quick-1.vnsave.0000000A.tmp", ".quick-1.vnsave.0000000a.tmp.x",
                 "quick-1.vnsave", ".quick-1.vnsave.tmp", ".persistent.json.0000000a.tmp",
                 ".page١-1.vnsave.0000000a.tmp",       # an Arabic-Indic digit (re.ASCII)
                 ".quick-1.vnsave.0000000a.tmp\n"):
        assert not pattern.fullmatch(name), name


def test_temp_name_pattern_needs_exactly_one_target():
    with pytest.raises(TypeError):
        temp_name_pattern()
    with pytest.raises(TypeError):
        temp_name_pattern("a", target_pattern="b")
    with pytest.raises(TypeError):
        remove_stale_temps("folder")


def test_stale_slot_temps_are_removed_and_nothing_else(base, outside):
    when = time.time() - 3600
    stale = [".quick-1.vnsave.0000000a.tmp", ".page12-3.vnsave.deadbeef.tmp",
             ".auto-2.vnsave.00000001.tmp"]
    kept = [NAME, "quick-2.vnsave",          # (case variants: the pattern test; NTFS folds case)
            ".page0-1.vnsave.0000000a.tmp", ".page101-1.vnsave.0000000a.tmp",
            ".page03-1.vnsave.0000000a.tmp", ".quick-1.vnsave.bak.0000000a.tmp",
            ".persistent.json.0000000a.tmp", ".quick-1.vnsave.0000000a.tmp.x", "notes.txt"]
    for name in stale + kept:
        (base / name).write_bytes(b"x")
        _old(base / name, when)
    young = base / ".quick-3.vnsave.0000000b.tmp"
    young.write_bytes(b"x")
    (base / ".quick-4.vnsave.0000000c.tmp").mkdir()            # a folder at a temp name
    link_dir(base / ".quick-5.vnsave.0000000d.tmp", outside)   # a link at a temp name
    before = _snapshot(outside)
    assert remove_stale_temps(base, target_pattern=SLOT_NAME_RE) == 3
    for name in stale:
        assert not (base / name).exists(), name
    for name in kept:
        assert (base / name).exists(), name
    assert young.exists()
    assert (base / ".quick-4.vnsave.0000000c.tmp").is_dir()
    assert os.path.lexists(base / ".quick-5.vnsave.0000000d.tmp")
    assert _snapshot(outside) == before


def test_the_pattern_keeps_sec_f12_13s_caps(base):
    when = time.time() - 3600
    for i in range(20):
        path = base / f".page{i + 1}-1.vnsave.{i:08x}.tmp"
        path.write_bytes(b"x")
        _old(path, when)
    assert remove_stale_temps(base, target_pattern=SLOT_NAME_RE) == 16
    assert len([n for n in os.listdir(base) if n.endswith(".tmp")]) == 4


def test_the_name_form_still_works_positionally(base):
    path = base / ".persistent.json.0000000a.tmp"
    path.write_bytes(b"x")
    _old(path, time.time() - 3600)
    assert remove_stale_temps(base, "persistent.json") == 1

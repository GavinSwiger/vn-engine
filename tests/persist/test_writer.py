"""The writer's jobs (F12 checklist step 4; ``04`` §7.5 writer, §18.1; ADR-0007 "one writer,
several owners"; SEC-F12-06, -09(b)): stamped writes, ``Changed`` reads, plain file writes,
reasons, retries, temp files, the folder re-check, redacted details, and the synchronous
fallback.

AC-F12-34 and AC-F12-37 moved to step 5 (``07`` I-8): they run these paths through
``PersistentSync`` (which logs W52). Here the writer is driven directly through its owner
clients, in both modes (``threaded`` parameter), with a fake ``sleep``."""

import ast
import errno
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

from engine.core import safefile
from engine.core.safefile import ReadKind, Stamp
from engine.persist import writer as writer_mod
from engine.persist.writer import (COULDNT_WRITE, DETAIL_MAX_CHARS, DISK_FULL, FOLDER_IS_LINK,
                                   NO_PERMISSION, PERSIST, REASONS, SETTINGS, Changed, Failed,
                                   FileWrite, FileWritten, Writer, WriteRequest, Written,
                                   reason_for)
from tests.persist.writer_support import (NEW, OLD, FakeSleep, WriteSpy, base, fail_when,  # noqa: F401
                                          game, is_temp, link_dir, oserror, outside, root,
                                          temps, tree, writers)

NAME = "persistent.json"
WRITER_PATH = Path(writer_mod.__file__)
FAR_S = 10.0


@pytest.fixture(params=[False, True], ids=["sync", "threaded"])
def threaded(request) -> bool:
    return request.param


@pytest.fixture
def sleep() -> FakeSleep:
    return FakeSleep()


@pytest.fixture
def writer(writers, threaded, sleep) -> Writer:
    return writers(threaded=threaded, sleep=sleep)


@pytest.fixture
def persist(writer, root):
    return writer.client(PERSIST, root=root, names=frozenset({NAME}))


@pytest.fixture
def settings_root(game) -> Path:
    folder = game / "settings"
    folder.mkdir()
    (folder / "settings.json").write_bytes(OLD)
    return folder


@pytest.fixture
def settings(writer, settings_root):
    return writer.client(SETTINGS, root=settings_root, names=frozenset({"settings.json"}))


def run(client, job):
    """Submit one job and wait (real time, bounded) for its one result."""
    client.submit(job)
    results = client.wait(time.monotonic() + FAR_S)
    assert len(results) == 1, results
    assert client.pending == 0 and client.in_flight == 0
    return results[0]


def stamp_of(path: Path) -> Stamp:
    return Stamp.of(os.stat(path))


def request(root: Path, data: bytes = NEW, *, expected=None, check=True, version=1,
            release=False) -> WriteRequest:
    return WriteRequest(root, (data,), expected, check, version, release)


# --- Stamped writes (§7.5 steps 2–4) ----------------------------------------------------------

def test_a_stamped_write_with_the_expected_stamp_is_written(persist, root):
    result = run(persist, request(root, expected=stamp_of(root / NAME), version=5))
    assert isinstance(result, Written) and result.version == 5
    assert result.stamp == stamp_of(root / NAME)
    assert (root / NAME).read_bytes() == NEW
    assert temps(root) == []
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(root / NAME).st_mode) == 0o600


def test_pieces_are_written_in_order(persist, root):
    result = run(persist, WriteRequest(root, (b'{"a":', b"1", b"}"), None, False, 2))
    assert isinstance(result, Written)
    assert (root / NAME).read_bytes() == b'{"a":1}'


def test_a_missing_target_is_written_whatever_the_expected_stamp(persist, root):
    old = stamp_of(root / NAME)
    (root / NAME).unlink()
    result = run(persist, request(root, expected=old))
    assert isinstance(result, Written)
    assert (root / NAME).read_bytes() == NEW


def test_a_missing_folder_is_created_and_written(writers, sleep, game):
    folder = game / "persistent"
    client = writers(threaded=True, sleep=sleep).client(PERSIST, root=folder,
                                                         names=frozenset({NAME}))
    result = run(client, request(folder, expected=None))
    assert isinstance(result, Written)
    assert (folder / NAME).read_bytes() == NEW


def test_a_changed_target_is_read_and_not_written(persist, root, monkeypatch):
    spy = WriteSpy()
    with monkeypatch.context() as patch:
        patch.setattr(safefile, "write_atomic", spy)
        result = run(persist, request(root, expected=Stamp(1, 2, 3)))
    assert result == Changed(stamp_of(root / NAME), OLD, ReadKind.OK)
    assert result.read.ok and result.read.data == OLD
    assert spy.names == []
    assert (root / NAME).read_bytes() == OLD and temps(root) == []


def test_a_target_created_by_someone_else_is_changed(persist, root):
    result = run(persist, request(root, expected=None))
    assert isinstance(result, Changed) and result.data == OLD
    assert (root / NAME).read_bytes() == OLD


def test_a_replace_between_fsync_and_replace_gives_changed(persist, root, monkeypatch):
    """SEC-F12-06(c): another copy replaces the file after our fsync; our temp is removed
    and its bytes stay intact."""
    other = b'{"other":3}'
    real_fsync = os.fsync
    done = []

    def fsync_then_other_copy_writes(fd):
        real_fsync(fd)
        if not done:
            done.append(True)
            side = root / "side.bin"
            side.write_bytes(other)
            os.replace(side, root / NAME)

    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "fsync", fsync_then_other_copy_writes)
        result = run(persist, request(root, expected=stamp_of(root / NAME)))
    assert isinstance(result, Changed)
    assert result.data == other and result.stamp == stamp_of(root / NAME)
    assert (root / NAME).read_bytes() == other
    assert temps(root) == []


def test_a_target_deleted_before_the_replace_is_written_as_missing(persist, root, monkeypatch):
    real_fsync = os.fsync
    done = []

    def fsync_then_delete(fd):
        real_fsync(fd)
        if not done:
            done.append(True)
            (root / NAME).unlink()

    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "fsync", fsync_then_delete)
        result = run(persist, request(root, expected=stamp_of(root / NAME)))
    assert isinstance(result, Written)
    assert (root / NAME).read_bytes() == NEW and temps(root) == []


def test_without_check_the_target_is_overwritten(persist, root):
    result = run(persist, request(root, expected=Stamp(1, 2, 3), check=False))
    assert isinstance(result, Written)
    assert (root / NAME).read_bytes() == NEW


def test_an_unreadable_changed_target_is_read_three_times(persist, root, sleep, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "read",
                      fail_when(os.read, lambda *_: True, oserror(errno.EIO)))
        result = run(persist, request(root, expected=Stamp(1, 2, 3)))
    assert result == Changed(None, None, ReadKind.UNREADABLE)
    assert sleep == [0.05, 0.05]
    assert (root / NAME).read_bytes() == OLD and temps(root) == []


def test_a_read_that_fails_once_is_retried(persist, root, sleep, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "read",
                      fail_when(os.read, lambda *_: True, oserror(errno.EIO), times=1))
        result = run(persist, request(root, expected=Stamp(1, 2, 3)))
    assert isinstance(result, Changed) and result.data == OLD
    assert sleep == [0.05]


def test_a_changed_target_that_is_not_a_regular_file_is_never_opened(persist, root, monkeypatch):
    (root / NAME).unlink()
    (root / NAME).mkdir()
    opened = []
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "open",
                      fail_when(os.open, lambda p, *_: opened.append(Path(p).name) or False,
                                oserror(errno.EIO)))
        result = run(persist, request(root, expected=None))
    assert isinstance(result, Changed) and result.kind is ReadKind.NOT_REGULAR
    assert result.data is None and result.stamp is not None
    assert NAME not in opened
    assert (root / NAME).is_dir() and temps(root) == []


# --- Plain file writes (FileWrite) ------------------------------------------------------------

def test_a_file_write_is_written_and_returns_its_token(settings, settings_root):
    result = run(settings, FileWrite(settings_root, "settings.json", (b"ab", b"cd"), token=7))
    assert result == FileWritten(7, stamp_of(settings_root / "settings.json"))
    assert (settings_root / "settings.json").read_bytes() == b"abcd"
    assert temps(settings_root) == []


def test_a_file_write_creates_only_its_root(writers, sleep, game):
    folder = game / "settings"
    client = writers(threaded=False, sleep=sleep).client(SETTINGS, root=folder,
                                                          names=frozenset({"settings.json"}))
    result = run(client, FileWrite(folder, "settings.json", (NEW,), token=1))
    assert isinstance(result, FileWritten)
    assert sorted(os.listdir(game)) == ["settings"]
    assert os.listdir(folder) == ["settings.json"]


def test_a_file_write_never_checks_the_stamp(settings, settings_root):
    """Last writer wins (F16 design §4): an outside change is simply replaced."""
    (settings_root / "settings.json").write_bytes(b"edited by hand")
    result = run(settings, FileWrite(settings_root, "settings.json", (NEW,)))
    assert isinstance(result, FileWritten)
    assert (settings_root / "settings.json").read_bytes() == NEW


# --- Faults: reasons, retries, no temp left (§7.5 step 3; AC-F12-34's writer half) -------------

def _replace_fails():
    return PermissionError(errno.EACCES, "sharing violation")


FAULTS = [
    # id, os call, predicate, exception, reason
    ("ENOSPC-write", "write", lambda *_: True, oserror(errno.ENOSPC), DISK_FULL),
    ("EACCES-temp-open", "open", is_temp, oserror(errno.EACCES), NO_PERMISSION),
    ("EPERM-temp-open", "open", is_temp, oserror(errno.EPERM), NO_PERMISSION),
    ("EROFS-temp-open", "open", is_temp, oserror(errno.EROFS), NO_PERMISSION),
    ("PermissionError-replace-x3", "replace", lambda *_: True, _replace_fails, NO_PERMISSION),
    ("EIO-fsync", "fsync", lambda *_: True, oserror(errno.EIO), COULDNT_WRITE),
    ("rename-EXDEV", "replace", lambda *_: True, oserror(errno.EXDEV), COULDNT_WRITE),
    ("RuntimeError-write", "write", lambda *_: True, lambda: RuntimeError("boom"),
     COULDNT_WRITE),
]


@pytest.fixture(params=["request", "file"])
def target_job(request, persist, settings, root, settings_root):
    """(client, job, target) for each job kind; both targets hold OLD."""
    if request.param == "request":
        return persist, request_for(root), root / NAME
    return settings, FileWrite(settings_root, "settings.json", (NEW,), token=3), \
        settings_root / "settings.json"


def request_for(root: Path) -> WriteRequest:
    return request(root, expected=stamp_of(root / NAME))


@pytest.mark.parametrize("call, when, exc, reason", [f[1:] for f in FAULTS],
                         ids=[f[0] for f in FAULTS])
def test_a_fault_fails_with_its_reason_and_leaves_old(target_job, sleep, monkeypatch,
                                                       call, when, exc, reason):
    client, job, target = target_job
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, call, fail_when(getattr(os, call), when, exc))
        result = run(client, job)
    assert isinstance(result, Failed)
    assert result.reason == reason and result.reason in REASONS
    assert result.token == getattr(job, "token", 0)
    assert "Traceback" in result.detail
    assert target.read_bytes() == OLD
    assert temps(target.parent) == []
    if call == "replace" and reason == NO_PERMISSION:
        assert sleep == [0.05, 0.05]


def test_a_runtime_error_detail_names_it(persist, root, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "write",
                      fail_when(os.write, lambda *_: True, lambda: RuntimeError("boom")))
        result = run(persist, request_for(root))
    assert result.reason == COULDNT_WRITE
    assert "RuntimeError: boom" in result.detail


def test_permission_error_on_replace_twice_then_success(persist, root, sleep, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "replace",
                      fail_when(os.replace, lambda *_: True, _replace_fails, times=2))
        result = run(persist, request_for(root))
    assert isinstance(result, Written)
    assert sleep == [0.05, 0.05]
    assert (root / NAME).read_bytes() == NEW and temps(root) == []


def test_after_a_fault_the_next_job_is_written(persist, root, writer, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "write",
                      fail_when(os.write, lambda *_: True, oserror(errno.ENOSPC), times=1))
        first = run(persist, request_for(root))
        second = run(persist, request_for(root))
    assert first.reason == DISK_FULL
    assert isinstance(second, Written) and (root / NAME).read_bytes() == NEW
    assert not writer.threaded or writer.alive


def test_reason_mapping():
    assert reason_for(OSError(errno.ENOSPC, "x")) == DISK_FULL
    for code in (errno.EACCES, errno.EPERM, errno.EROFS):
        assert reason_for(OSError(code, "x")) == NO_PERMISSION
    assert reason_for(PermissionError("sharing violation")) == NO_PERMISSION
    for exc in (OSError(errno.EIO, "x"), OSError("no errno"), RuntimeError("x"),
                FileExistsError(errno.EEXIST, "no free temp file name")):
        assert reason_for(exc) == COULDNT_WRITE


def test_all_temp_names_taken_fails_and_leaves_the_target(persist, root, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "open",
                      fail_when(os.open, is_temp, lambda: FileExistsError(errno.EEXIST, "x")))
        result = run(persist, request_for(root))
    assert result.reason == COULDNT_WRITE
    assert (root / NAME).read_bytes() == OLD and temps(root) == []


# --- The folder (SEC-F12-06b; F16 04 §5.3) ----------------------------------------------------

def test_a_root_that_is_a_link_fails_and_nothing_is_created_outside(writers, sleep, game,
                                                                   outside, threaded):
    target = outside / "p"
    target.mkdir()
    folder = game / "persistent"
    link_dir(folder, target)
    client = writers(threaded=threaded, sleep=sleep).client(PERSIST, root=folder,
                                                             names=frozenset({NAME}))
    result = run(client, request(folder, expected=None))
    assert result.reason == FOLDER_IS_LINK
    assert os.listdir(target) == []


def test_a_root_swapped_to_a_link_between_two_writes(persist, root, outside):
    first = run(persist, request_for(root))
    assert isinstance(first, Written)
    (root / NAME).unlink()
    root.rmdir()
    target = outside / "p"
    target.mkdir()
    link_dir(root, target)
    second = run(persist, request(root, expected=first.stamp))
    assert second.reason == FOLDER_IS_LINK
    assert os.listdir(target) == []


def test_a_file_in_the_roots_place_is_refused(writers, sleep, game):
    folder = game / "persistent"
    folder.write_bytes(b"not a folder")
    client = writers(threaded=False, sleep=sleep).client(PERSIST, root=folder,
                                                          names=frozenset({NAME}))
    assert run(client, request(folder, expected=None)).reason == FOLDER_IS_LINK
    assert folder.read_bytes() == b"not a folder"


def test_a_root_that_cant_be_created_is_no_permission(writers, sleep, game):
    folder = game / "missing-parent" / "persistent"
    client = writers(threaded=False, sleep=sleep).client(PERSIST, root=folder,
                                                          names=frozenset({NAME}))
    before = tree(game)
    assert run(client, request(folder, expected=None)).reason == NO_PERMISSION
    assert tree(game) == before


def test_a_dev_root_under_a_linked_parent_is_a_link_but_release_follows_it(writers, sleep,
                                                                          base, outside):
    real_game = outside / "g"
    (real_game / "persistent").mkdir(parents=True)
    linked = base / "linked-game"
    link_dir(linked, real_game)
    folder = linked / "persistent"
    writer = writers(threaded=False, sleep=sleep)
    client = writer.client(PERSIST, root=folder, names=frozenset({NAME}))
    assert run(client, request(folder, expected=None)).reason == FOLDER_IS_LINK
    assert os.listdir(real_game / "persistent") == []
    result = run(client, request(folder, expected=None, release=True))
    assert isinstance(result, Written)
    assert (real_game / "persistent" / NAME).read_bytes() == NEW


# --- Details are redacted and bounded (SEC-F12-09b) -------------------------------------------

def test_an_oserror_detail_goes_through_the_redactor(persist, root, monkeypatch):
    """The OSError text holds the full path (marker ``ZZMARK``); only redacted text leaves."""
    seen = []

    def redact(text):
        seen.append(text)
        return text.replace("ZZMARK", "<redacted>")

    with monkeypatch.context() as patch:
        patch.setattr(writer_mod, "redact", redact)
        patch.setattr(safefile.os, "open",
                      fail_when(os.open, is_temp,
                                oserror(errno.EACCES, str(root / "ZZMARK" / "x.tmp"))))
        result = run(persist, request_for(root))
    assert result.reason == NO_PERMISSION
    assert len(seen) == 1 and "ZZMARK" in seen[0]
    assert "ZZMARK" not in result.detail and "<redacted>" in result.detail


def test_a_detail_is_cut_to_its_limit(persist, root, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "write",
                      fail_when(os.write, lambda *_: True, lambda: RuntimeError("x" * 10_000)))
        result = run(persist, request_for(root))
    assert len(result.detail) == DETAIL_MAX_CHARS and result.detail.endswith("…")


# --- Jobs are frozen bytes and paths ----------------------------------------------------------

@pytest.mark.parametrize("make", [
    lambda r: WriteRequest(r, [NEW], None, True, 1),
    lambda r: WriteRequest(r, (bytearray(NEW),), None, True, 1),
    lambda r: WriteRequest(r, ("text",), None, True, 1),
    lambda r: WriteRequest(str(r), (NEW,), None, True, 1),
    lambda r: WriteRequest(r, (NEW,), (1, 2, 3), True, 1),
    lambda r: WriteRequest(r, (NEW,), None, 1, 1),
    lambda r: WriteRequest(r, (NEW,), None, True, 1, release=None),
    lambda r: FileWrite(r, "settings.json", (memoryview(NEW),)),
    lambda r: FileWrite(r, Path("settings.json"), (NEW,)),
    lambda r: FileWrite(r, "settings.json", (NEW,), token="1"),
], ids=["list", "bytearray", "str-piece", "str-folder", "tuple-stamp", "int-check",
        "none-release", "memoryview", "path-name", "str-token"])
def test_a_job_takes_only_frozen_bytes_and_paths(root, make):
    with pytest.raises(TypeError):
        make(root)


def test_jobs_are_frozen(root):
    job = request(root)
    with pytest.raises(AttributeError):
        job.pieces = (b"x",)


def test_submit_takes_only_jobs(persist, root):
    with pytest.raises(TypeError):
        persist.submit((root, NEW))
    assert persist.pending == 0


# --- Threads and the synchronous fallback (ADR-0007) ------------------------------------------

def test_the_thread_starts_on_the_first_submit_and_writes_off_the_main_thread(
        writers, sleep, root, monkeypatch):
    writer = writers(threaded=True, sleep=sleep)
    client = writer.client(PERSIST, root=root, names=frozenset({NAME}))
    assert not writer.started and threading.active_count() >= 1
    spy = WriteSpy()
    with monkeypatch.context() as patch:
        patch.setattr(safefile, "write_atomic", spy)
        result = run(client, request_for(root))
    assert isinstance(result, Written)
    assert writer.started and writer.alive
    assert writer._thread.daemon and writer._thread.name == "vn-writer"
    assert spy.threads == [writer._thread.ident]
    assert threading.main_thread().ident not in spy.threads


def test_sync_mode_writes_inside_submit_on_the_callers_thread(writers, sleep, root, monkeypatch):
    writer = writers(threaded=False, sleep=sleep)
    client = writer.client(PERSIST, root=root, names=frozenset({NAME}))
    spy = WriteSpy()
    with monkeypatch.context() as patch:
        patch.setattr(safefile, "write_atomic", spy)
        client.submit(request_for(root))
        assert client.in_flight == 0 and client.pending == 1
    assert spy.threads == [threading.get_ident()]
    assert not writer.started
    [result] = client.take()
    assert isinstance(result, Written) and client.take() == []


def test_writer_threaded_flag_is_read_when_the_writer_is_built(monkeypatch):
    assert Writer().threaded is writer_mod.WRITER_THREADED is True
    with monkeypatch.context() as patch:
        patch.setattr(writer_mod, "WRITER_THREADED", False)
        built = Writer()
        assert Writer(threaded=True).threaded is True
    assert built.threaded is False


# --- What the module may do (ADR-0007; AC-F12-43's writer half) --------------------------------

def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            names.add(node.module)
    return names


def test_the_writer_never_logs_and_imports_only_what_it_needs():
    imported = _imports(WRITER_PATH)
    top = {name.split(".")[0] for name in imported}
    assert top - {"engine"} <= sys.stdlib_module_names
    engine = {name for name in imported if name.startswith("engine")}
    assert engine <= {"engine.core", "engine.core.redact", "engine.core.safefile",
                      "engine.persist", "engine.persist.location"}
    assert not top & {"logging", "pygame", "pickle", "marshal", "shelve", "importlib",
                      "ctypes", "subprocess", "shutil"}
    assert "engine.core.logsetup" not in imported
    tree = ast.parse(WRITER_PATH.read_text(encoding="utf-8"))
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not called & {"print", "eval", "exec", "compile", "__import__", "open"}


def test_only_the_writer_imports_threading_in_persist():
    folder = WRITER_PATH.parent
    for path in sorted(folder.glob("*.py")):
        top = {name.split(".")[0] for name in _imports(path)}
        has = bool(top & {"threading", "queue", "_thread"})
        assert has == (path.name == "writer.py"), path.name

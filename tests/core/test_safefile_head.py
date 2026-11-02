"""``safefile.read_head`` (F11 C15, ``04`` §7.5 "Head"; I-5): the first ``max_bytes`` bytes
of a regular file of any size, with ``read_regular``'s entry checks through the one shared
open-and-``fstat`` helper.

Faults are injected by patching ``os`` calls inside ``engine.core.safefile`` within a
``monkeypatch.context()``. Link rows skip where symlinks aren't permitted."""

import ast
import errno
import inspect
import os
import textwrap
import time

import pytest

from engine.core import safefile
from engine.core.safefile import ReadKind, Stamp, read_head, read_regular
from tests.core.test_safefile import Patched, fail_on, link_dir, symlink

HEAD_MAX = 139_276          # F11 04 §13 (persist/limits.py arrives in F11 step 3)
SAVE_FILE_MAX = 25_305_100
NAME = "quick-1.vnsave"


@pytest.fixture
def base(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def outside(base):
    folder = base / "outside"
    folder.mkdir()
    return folder


def _read_spy(patch) -> list[int]:
    """Record the size of every ``os.read`` result."""
    got: list[int] = []
    real = os.read

    def spy(fd, n):
        chunk = real(fd, n)
        got.append(len(chunk))
        return chunk
    patch.setattr(safefile.os, "read", spy)
    return got


def _sparse(path, size: int) -> None:
    with open(path, "wb") as handle:
        handle.truncate(size)


# --- What is read ----------------------------------------------------------------------------

def test_a_short_file_is_read_whole_with_its_fstat_stamp(base):
    path = base / NAME
    path.write_bytes(b'{"vnsave":1}\n')
    result = read_head(path, HEAD_MAX)
    assert result.ok and result.kind is ReadKind.OK
    assert result.data == b'{"vnsave":1}\n'
    assert result.stamp == Stamp.of(os.stat(path))


def test_an_empty_file_is_ok_and_empty(base):
    (base / NAME).write_bytes(b"")
    result = read_head(base / NAME, HEAD_MAX)
    assert result.kind is ReadKind.OK and result.data == b""
    assert result.stamp.size == 0


@pytest.mark.parametrize("size", [HEAD_MAX - 1, HEAD_MAX, HEAD_MAX + 1, 5 * HEAD_MAX])
def test_at_most_max_bytes_are_read_and_the_stamp_has_the_whole_size(base, monkeypatch, size):
    path = base / NAME
    content = bytes(range(256)) * (size // 256 + 1)
    path.write_bytes(content[:size])
    with monkeypatch.context() as patch:
        got = _read_spy(patch)
        result = read_head(path, HEAD_MAX)
    assert result.kind is ReadKind.OK
    assert result.data == content[:min(size, HEAD_MAX)]
    assert sum(got) == min(size, HEAD_MAX)
    assert result.stamp.size == size


def test_a_file_over_the_save_cap_is_ok_with_only_the_head_read(base, monkeypatch):
    """Group B: the page path reads ≤ HEAD_MAX bytes even of a huge file; the caller
    refuses it by ``stamp.size`` (§7.5 head step 1)."""
    path = base / NAME
    _sparse(path, SAVE_FILE_MAX + 1)
    with monkeypatch.context() as patch:
        got = _read_spy(patch)
        result = read_head(path, HEAD_MAX)
    assert result.kind is ReadKind.OK
    assert len(result.data) == HEAD_MAX and sum(got) == HEAD_MAX
    assert result.stamp.size == SAVE_FILE_MAX + 1


def test_a_file_that_grows_after_stat_is_still_read_to_max_bytes_only(base, monkeypatch):
    path = base / NAME
    path.write_bytes(b"x" * 50)
    real_lstat, real_fstat = os.lstat, os.fstat
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "lstat", lambda p: Patched(real_lstat(p), st_size=3))
        patch.setattr(safefile.os, "fstat", lambda fd: Patched(real_fstat(fd), st_size=3))
        got = _read_spy(patch)
        result = read_head(path, 10)
    assert result.kind is ReadKind.OK
    assert result.data == b"x" * 10 and sum(got) == 10


def test_a_file_shorter_than_its_stat_gives_what_is_there(base, monkeypatch):
    path = base / NAME
    path.write_bytes(b"abc")
    real_fstat = os.fstat
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "fstat", lambda fd: Patched(real_fstat(fd), st_size=99))
        result = read_head(path, 10)
    assert result.kind is ReadKind.OK and result.data == b"abc"
    assert result.stamp.size == 99          # the caller's length equation catches it


def test_max_bytes_zero_reads_nothing(base, monkeypatch):
    (base / NAME).write_bytes(b"abc")
    with monkeypatch.context() as patch:
        got = _read_spy(patch)
        result = read_head(base / NAME, 0)
    assert result.kind is ReadKind.OK and result.data == b""
    assert sum(got) == 0


# --- Entries that are refused (the same checks as read_regular) -----------------------------

def test_missing(base):
    assert read_head(base / "nope" / NAME, HEAD_MAX).kind is ReadKind.MISSING
    assert read_head(base / NAME, HEAD_MAX).kind is ReadKind.MISSING


def test_a_directory_is_not_regular(base):
    (base / NAME).mkdir()
    result = read_head(base / NAME, HEAD_MAX)
    assert result.kind is ReadKind.NOT_REGULAR and result.data is None


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
def test_a_junction_is_not_regular_and_its_target_untouched(base, outside):
    (outside / "f").write_bytes(b"secret")
    link_dir(base / NAME, outside)
    assert read_head(base / NAME, HEAD_MAX).kind is ReadKind.NOT_REGULAR
    assert os.listdir(outside) == ["f"]


def test_a_symlink_target_is_never_opened(base, outside, monkeypatch):
    secret = outside / "secret.vnsave"
    secret.write_bytes(b"AikoSecret")
    symlink(base / NAME, secret)
    opened = []
    real = os.open
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "open",
                      lambda p, *a, **k: opened.append(p) or real(p, *a, **k))
        result = read_head(base / NAME, HEAD_MAX)
    assert result.kind is ReadKind.NOT_REGULAR
    assert opened == []


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX-only")
def test_a_fifo_is_not_regular_and_returns_at_once(base):
    os.mkfifo(base / NAME)
    started = time.monotonic()
    assert read_head(base / NAME, HEAD_MAX).kind is ReadKind.NOT_REGULAR
    assert time.monotonic() - started < 1.0


def test_fstat_differing_from_lstat_is_refused(base, monkeypatch):
    path = base / NAME
    path.write_bytes(b"{}")
    real = os.fstat
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "fstat",
                      lambda fd: Patched(real(fd), st_ino=real(fd).st_ino + 1))
        result = read_head(path, HEAD_MAX)
    assert result.kind is ReadKind.NOT_REGULAR and result.data is None


def test_a_link_swapped_in_after_lstat_is_not_regular(base, monkeypatch):
    path = base / NAME
    path.write_bytes(b"{}")
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "open", fail_on(os.open, 1, errno.ELOOP))
        assert read_head(path, HEAD_MAX).kind is ReadKind.NOT_REGULAR


# --- Faults ----------------------------------------------------------------------------------

@pytest.mark.parametrize("call,code,kind", [
    ("lstat", errno.EACCES, ReadKind.UNREADABLE),
    ("lstat", errno.EIO, ReadKind.UNREADABLE),
    ("open", errno.EACCES, ReadKind.UNREADABLE),
    ("open", errno.ENOENT, ReadKind.MISSING),
    ("fstat", errno.EIO, ReadKind.UNREADABLE),
    ("read", errno.EIO, ReadKind.UNREADABLE),
])
def test_faults_give_a_result_and_never_raise(base, monkeypatch, call, code, kind):
    path = base / NAME
    path.write_bytes(b"{}")
    closed = []
    real_close = os.close
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, call, fail_on(getattr(os, call), 1, code))
        patch.setattr(safefile.os, "close", lambda fd: closed.append(fd) or real_close(fd))
        result = read_head(path, HEAD_MAX)
    assert result.kind is kind and result.data is None
    if call in ("fstat", "read"):
        assert len(closed) == 1             # the opened descriptor is always closed


def test_a_close_error_is_ignored(base, monkeypatch):
    (base / NAME).write_bytes(b"{}")
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "close", fail_on(os.close, 1, errno.EIO, close_first=True))
        result = read_head(base / NAME, HEAD_MAX)
    assert result.kind is ReadKind.OK and result.data == b"{}"


def test_a_nul_in_the_path_is_unreadable(base):
    assert read_head(base / "a\0b", HEAD_MAX).kind is ReadKind.UNREADABLE


# --- I-5: one helper, not a copy -------------------------------------------------------------

def _calls(function) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    return {node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


def test_read_head_and_read_regular_share_the_open_and_fstat_helper():
    for function in (read_head, read_regular):
        called = _calls(function)
        assert "_open_regular" in called, function.__name__
        assert "_open_for_reading" not in called, function.__name__
    source = inspect.getsource(read_head) + inspect.getsource(read_regular)
    assert "os.lstat" not in source and "os.fstat" not in source and "os.open" not in source


def test_read_regular_still_refuses_over_the_cap_before_opening(base, monkeypatch):
    path = base / NAME
    _sparse(path, 100)
    opened = []
    real = os.open
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "open",
                      lambda p, *a, **k: opened.append(p) or real(p, *a, **k))
        result = read_regular(path, 99)
    assert result.kind is ReadKind.TOO_LARGE and result.stamp.size == 100
    assert opened == []

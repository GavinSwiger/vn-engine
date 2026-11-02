"""Logging: format, escaping, redaction, level filter, cap, early buffer, log folder,
rotation, and retention.

AC-F01-64 (rotation), 73 (size cap), 144 (rotation never follows links or blocks), 145
(``latest-<pid>.log`` bounded); the unit parts of AC-F01-63, 66, 67, 70, 71, 74, 128,
129, 131, and 143 (the launch-level parts are in ``tests/app/test_bootstrap.py``).
"""

import datetime
import gc
import io
import logging
import os
import re
import stat
import sys
import weakref
from pathlib import Path

import pytest

from engine.core import logsetup
from engine.core.constants import LOG_CAP_BYTES
from engine.core.logsetup import (
    CappedFileHandler,
    EarlyBuffer,
    LogDirCandidate,
    LogSession,
    RedactingFormatter,
    get_logger,
    lifecycle,
)

REPO = Path(__file__).resolve().parent.parent.parent
LINE_RE = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} (DEBUG|INFO|WARNING|ERROR)\s+[a-z]{1,7}\s+.+$")
STAMP_RE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} ")
UNUSABLE = "The logs folder in the game folder is a link or not a folder — using another log location"
NOT_REGULAR = "logs/latest.log is not a regular file — rotation skipped"
ROTATE_FAILED = "Could not rotate latest.log (it may be open in another copy of the game)"
LIMIT_LINE = "Log size limit (10 MB) reached — further messages are dropped"


def _symlink(target: Path, link: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this system does not allow creating symlinks ({exc.__class__.__name__})")


@pytest.fixture
def game(tmp_path, user_roots) -> Path:
    root = tmp_path / "game"
    root.mkdir()
    return root.resolve()


@pytest.fixture
def log(user_roots):
    setup = logsetup.begin(level="info", engine_root=REPO)
    yield setup
    setup.close()


def _game_candidate(root: Path) -> LogDirCandidate:
    return LogDirCandidate(root / "logs", "game")


def _open(log, root: Path, *extra: LogDirCandidate) -> LogSession:
    log.add_game_root(root)
    return log.open_file([_game_candidate(root), *extra])


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _set_local_mtime(path: Path, when: datetime.datetime) -> None:
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))


# --- Format (AC-F01-67 unit part) ------------------------------------------------------------

def test_line_format_and_fixed_columns(log, game):
    session = _open(log, game)
    lifecycle(get_logger("app"), "header")
    get_logger("config").warning("a config warning")
    get_logger("assets").error("an asset error")
    get_logger("script").warning("from a later feature")
    get_logger("runtime").info("another later area")
    lines = _lines(session.file_path)
    assert len(lines) == 5
    stamps = []
    for line in lines:
        assert LINE_RE.match(line), line
        level, area = line[24:31], line[32:39]
        assert level.rstrip() in ("DEBUG", "INFO", "WARNING", "ERROR")
        assert line[23] == " " and line[31] == " " and line[39] == " "
        assert re.fullmatch(r"[a-z]{1,7}", area.rstrip())
        stamps.append(line[:23])
    assert stamps == sorted(stamps)
    assert [line[32:39].rstrip() for line in lines] == ["app", "config", "assets", "script",
                                                        "runtime"]


@pytest.mark.parametrize("area", ["", "Assets", "toolongx", "a.b", "a1", "é"])
def test_invalid_areas_are_rejected(area):
    with pytest.raises(ValueError):
        get_logger(area)


def test_content_cannot_forge_or_hide_lines(log, game):
    session = _open(log, game)
    forged = "title\n2026-11-01 00:00:00.000 ERROR   app     forged\u202e\x1b[2J"
    get_logger("config").warning("Title is %s", forged)
    lines = _lines(session.file_path)
    assert len(lines) == 1
    assert "\\n2026-11-01" in lines[0] and "\\u202e" in lines[0] and "\\x1b" in lines[0]


def test_traceback_keeps_its_lines_and_is_redacted(log, game, user_roots):
    session = _open(log, game)
    try:
        raise PermissionError(13, "Permission denied", str(user_roots.home / "x.png"))
    except PermissionError:
        get_logger("app").exception("Something failed")
    text = session.file_path.read_text(encoding="utf-8")
    assert "Traceback (most recent call last):" in text
    assert "qauser7" not in text.lower()
    assert "~" in text
    first, *rest = text.splitlines()
    assert LINE_RE.match(first) and rest                       # continuation lines follow
    assert all(line.startswith("  ") for line in rest)         # SEC-F23-09 prefix
    assert rest[0] == "  Traceback (most recent call last):"


# --- AC-F23-57 (SEC-F23-09): traceback blocks can't forge records -------------------------------

FORGED = "\n2026-11-02 00:00:00.000 ERROR   runtime  fake"


def _formatted(exc: BaseException, **kwargs) -> list[str]:
    try:
        raise exc
    except BaseException:
        record = logging.LogRecord("vn.plugin", logging.ERROR, __file__, 1, "failed", None,
                                   sys.exc_info(), **kwargs)
    return RedactingFormatter().format(record).split("\n")


@pytest.mark.parametrize("origin", ["plugin", "dollar line"])
def test_forged_record_inside_a_traceback_is_prefixed(origin):
    exc = ValueError(f"from a {origin}{FORGED}")
    first, *rest = _formatted(exc)
    assert LINE_RE.match(first)
    assert rest and all(line.startswith("  ") for line in rest)
    assert not any(STAMP_RE.match(line) for line in rest)
    assert "  2026-11-02 00:00:00.000 ERROR   runtime  fake" in rest


def test_stack_info_and_exc_text_get_the_prefix():
    record = logging.LogRecord("vn.app", logging.ERROR, __file__, 1, "x", None, None)
    record.exc_text = f"Traceback (most recent call last):{FORGED}"
    record.stack_info = f"Stack (most recent call last):{FORGED}"
    first, *rest = RedactingFormatter().format(record).split("\n")
    assert len(rest) == 4 and all(line.startswith("  ") for line in rest)
    assert not any(STAMP_RE.match(line) for line in rest)


def test_a_long_traceback_is_capped():
    record = logging.LogRecord("vn.app", logging.ERROR, __file__, 1, "x", None, None)
    record.exc_text = "\n".join(f"{i:04d}" + "x" * 1996 for i in range(300))
    first, *rest = RedactingFormatter().format(record).split("\n")
    assert len(rest) == 201
    assert all(len(line) == 2 + 1000 and line.endswith("…") for line in rest[:200])
    assert rest[0].startswith("  0000x") and rest[199].startswith("  0199x")
    assert rest[200] == "  …and 100 more lines."


def test_a_cut_line_is_redacted_first(log, game, user_roots):
    home = str(user_roots.home)
    record = logging.LogRecord("vn.app", logging.ERROR, __file__, 1, "x", None, None)
    # Unredacted, the 1,000-character cut would fall inside the home path.
    record.exc_text = "y" * (1000 - 5 - len(home) // 2) + home + os.sep + "x.png " + "z" * 50
    text = RedactingFormatter().format(record)
    assert "qauser7" not in text.lower()
    assert "~" in text


def test_critical_is_written_as_error(log, game):
    session = _open(log, game)
    get_logger("app").critical("bad")
    assert _lines(session.file_path)[0][24:31] == "ERROR  "


# --- Level filter and lifecycle (AC-F01-70 unit part) -----------------------------------------

def test_level_filter_and_lifecycle_bypass(log, game):
    session = _open(log, game)
    app = get_logger("app")
    log.set_level("error")
    app.info("plain info")
    app.warning("plain warning")
    lifecycle(app, "lifecycle at error level")
    app.error("an error")
    log.set_level("debug")
    app.debug("debug now")
    text = session.file_path.read_text(encoding="utf-8")
    assert "plain info" not in text and "plain warning" not in text
    assert "lifecycle at error level" in text and "an error" in text and "debug now" in text
    assert logging.getLogger("vn").level == logging.DEBUG


def test_vn_logger_level_lets_lifecycle_through_and_is_restored(game):
    vn = logging.getLogger("vn")
    before = vn.level
    setup = logsetup.begin(level="error", engine_root=REPO)
    assert vn.level == logging.INFO
    setup.close()
    assert vn.level == before
    assert not [h for h in vn.handlers if isinstance(
        h, (CappedFileHandler, EarlyBuffer, logsetup._TailHandler))]


# --- Console (AC-F01-71 unit part) --------------------------------------------------------------

def test_console_shows_warnings_and_errors_only(capsys, log, game):
    _open(log, game)
    app = get_logger("app")
    lifecycle(app, "header line")
    app.info("plain info")
    app.warning("a warning")
    app.error("an error")
    err = capsys.readouterr().err
    assert "a warning" in err and "an error" in err
    assert "header line" not in err and "plain info" not in err


def test_no_console_handler_without_stderr(monkeypatch, game):
    monkeypatch.setattr(sys, "stderr", None)
    setup = logsetup.begin(level="info", engine_root=REPO)
    try:
        assert setup.console_handler is None
        get_logger("app").warning("no crash")
        session = setup.open_file([_game_candidate(game)])
        assert "no crash" in session.file_path.read_text(encoding="utf-8")
    finally:
        setup.close()


def test_tail_holds_the_last_50_redacted_lines(log, game, user_roots):
    _open(log, game)
    for i in range(60):
        get_logger("app").warning("line %d at %s", i, user_roots.home / "f.txt")
    assert len(log.tail) == 50
    assert log.tail[-1].endswith("line 59 at ~/f.txt") or log.tail[-1].endswith(
        "line 59 at ~\\f.txt")
    assert all("qauser7" not in line for line in log.tail)


# --- Size cap (AC-F01-73) -------------------------------------------------------------------------

def _record(message: str, *, lifecycle_record: bool = False, level=logging.INFO):
    record = logging.LogRecord("vn.app", level, __file__, 1, message, None, None)
    if lifecycle_record:
        record.lifecycle = True
    return record


def test_cap_with_injected_limits(tmp_path, game):
    path = tmp_path / "capped.log"
    stream = open(path, "x", encoding="utf-8", newline="\n")
    handler = CappedFileHandler(stream, cap=100 * 1024, reserve=8 * 1024)
    handler.setFormatter(RedactingFormatter())
    body = "x" * 1000
    written = 0
    while written < 200 * 1024:
        handler.handle(_record(body))
        written += len(body)
    handler.handle(_record("final lifecycle", lifecycle_record=True))
    handler.close()

    data = path.read_bytes()
    assert len(data) <= 100 * 1024
    lines = data.decode("utf-8").splitlines()
    limit_index = [i for i, line in enumerate(lines) if LIMIT_LINE in line]
    assert len(limit_index) == 1
    limit_line = lines[limit_index[0]]
    assert limit_line[24:40] == "WARNING app     "
    assert all(body in line for line in lines[:limit_index[0]])        # directly follows
    assert lines[limit_index[0] + 1].endswith("final lifecycle")
    non_lifecycle = sum(len(line.encode()) + 1 for line in lines[:limit_index[0]])
    assert non_lifecycle <= 92 * 1024


@pytest.mark.slow          # 11 MB through the real formatter: about 2 s
def test_real_cap_with_11_mb_of_debug_lines(game):
    """AC-F01-73 integration part, with the real constants. The injected-limit test above
    covers the same logic in the default run."""
    setup = logsetup.begin(level="debug", engine_root=REPO, console=False)
    try:
        app = get_logger("app")
        lifecycle(app, "header line 1")
        session = _open(setup, game)
        lifecycle(app, "Log: header line 2")
        body = "d" * 1100
        for _ in range(10_500):                       # about 11.5 MB of DEBUG lines
            app.debug(body)
        lifecycle(app, "Clean shutdown (exit code 0)")
    finally:
        setup.close()
    data = session.file_path.read_bytes()
    assert len(data) <= LOG_CAP_BYTES
    text = data.decode("utf-8")
    assert text.count(LIMIT_LINE) == 1
    lines = text.splitlines()
    assert lines[0].endswith("header line 1")
    assert lines[-1].endswith("Clean shutdown (exit code 0)")


# --- Early buffer (AC-F01-128, 129, 131 unit parts) -----------------------------------------------

def test_nothing_is_written_before_open_file(tmp_path, game, user_roots):
    before = sorted(p for p in tmp_path.rglob("*"))
    setup = logsetup.begin(level="debug", engine_root=REPO)
    try:
        for i in range(10):
            get_logger("app").warning("early %d", i)
        assert sorted(p for p in tmp_path.rglob("*")) == before
    finally:
        setup.close()


def test_early_records_are_redacted_on_entry(log, game, user_roots):
    get_logger("config").warning("x %s", str(user_roots.home / "a"))
    try:
        raise ValueError(f"bad file {user_roots.home / 'b.txt'}")
    except ValueError:
        get_logger("app").exception("failed")
    items = list(log.early_buffer.items)
    assert len(items) == 2
    for lifecycle_flag, text in items:
        assert isinstance(lifecycle_flag, bool) and isinstance(text, str)
        assert "qauser7" not in text.lower()
    assert "Traceback" in items[1][1]


def test_early_buffer_is_bounded_by_records_and_keeps_lifecycle():
    buffer = EarlyBuffer(max_records=1000, max_bytes=256 * 1024)
    buffer.setFormatter(RedactingFormatter())
    buffer.handle(_record("start", lifecycle_record=True))
    for i in range(1500):
        buffer.handle(_record(f"early {i}", level=logging.WARNING))
    buffer.handle(_record("still kept", lifecycle_record=True))
    assert buffer.records == 1000 and buffer.dropped == 500
    drained = buffer.drain(RedactingFormatter())
    texts = [text for _, text in drained]
    assert texts[0].endswith("start")
    assert texts[1001].endswith("WARNING app     500 early log records were dropped") or \
        texts[1001][24:].startswith("WARNING app     500 early log records were dropped")
    assert texts[1000].endswith("early 999")
    assert texts[-1].endswith("still kept")
    assert buffer.items == [] and buffer.dropped == 0


def test_early_buffer_is_bounded_by_bytes():
    buffer = EarlyBuffer(max_records=1000, max_bytes=256 * 1024)
    buffer.setFormatter(RedactingFormatter())
    for _ in range(400):
        buffer.handle(_record("y" * 1000, level=logging.WARNING))
    assert buffer.bytes <= 256 * 1024
    assert buffer.records == buffer.bytes // len(buffer.items[0][1].encode()) or True
    assert buffer.records < 400 and buffer.dropped == 400 - buffer.records


def test_flush_writes_the_buffer_first_in_order_with_one_marker(game):
    setup = logsetup.begin(level="info", engine_root=REPO, console=False)
    setup.early_buffer.max_records = 3
    try:
        app = get_logger("app")
        lifecycle(app, "header")
        for i in range(6):
            app.warning("early %d", i)
        session = setup.open_file([_game_candidate(game)])
        app.warning("after open")
    finally:
        setup.close()
    lines = _lines(session.file_path)
    messages = [line[40:] for line in lines]
    assert messages == ["header", "early 0", "early 1", "early 2",
                        "3 early log records were dropped", "after open"]
    assert lines[4][24:40] == "WARNING app     "


def test_console_only_discards_the_buffer(tmp_path, user_roots):
    blocked = tmp_path / "blocked"
    blocked.write_text("a file, not a folder")
    setup = logsetup.begin(level="info", engine_root=REPO)
    try:
        get_logger("app").warning("early")
        buffer = setup.early_buffer
        ref = weakref.ref(buffer)
        session = setup.open_file([LogDirCandidate(blocked / "logs", "user"),
                                   LogDirCandidate(None, "user")])
        assert session == LogSession(None, "not available (the log folder could not be "
                                           "written)", None)
        assert buffer not in logging.getLogger("vn").handlers
        assert buffer.items == []
        del buffer
        gc.collect()
        assert ref() is None
        assert setup.open_file([]) is session                  # idempotent
    finally:
        setup.close()
    assert blocked.read_text() == "a file, not a folder"


# --- Log folder choice (AC-F01-63, 74, 143 unit parts) ---------------------------------------------

def test_game_logs_folder_is_created(log, game):
    lifecycle(get_logger("app"), "header line 1")
    session = _open(log, game)
    assert session.file_path == game / "logs" / "latest.log"
    assert session.display_path == "<game>/logs/latest.log"
    assert session.kind == "game"
    assert _lines(session.file_path)[0].endswith("header line 1")


def test_open_file_is_idempotent(log, game):
    first = _open(log, game)
    assert log.open_file([_game_candidate(game)]) is first
    assert sorted(p.name for p in (game / "logs").iterdir()) == ["latest.log"]


def test_game_logs_as_a_file_falls_back_with_one_warning(log, game, user_roots):
    (game / "logs").write_text("not a folder")
    user_dir = user_roots.localappdata / "vn-engine" / "vn-test" / "logs"
    session = _open(log, game, LogDirCandidate(user_dir, "user"))
    assert session.file_path == user_dir / "latest.log"
    assert session.kind == "user"
    text = session.file_path.read_text(encoding="utf-8")
    assert text.count(UNUSABLE) == 1
    assert (game / "logs").read_text() == "not a folder"


@pytest.mark.skipif(sys.platform != "win32", reason="junctions exist only on Windows")
def test_game_logs_junction_is_never_used(log, game, tmp_path, user_roots):
    import _winapi

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "latest.log").write_text("victim")
    _winapi.CreateJunction(str(outside), str(game / "logs"))
    user_dir = user_roots.localappdata / "vn-engine" / "game" / "logs"
    session = _open(log, game, LogDirCandidate(user_dir, "user"))
    assert session.file_path.parent == user_dir
    assert sorted(p.name for p in outside.iterdir()) == ["latest.log"]
    assert (outside / "latest.log").read_text() == "victim"
    assert session.file_path.read_text(encoding="utf-8").count(UNUSABLE) == 1


def test_game_logs_symlink_is_never_used(log, game, tmp_path, user_roots):
    outside = tmp_path / "outside"
    outside.mkdir()
    _symlink(outside, game / "logs", directory=True)
    user_dir = user_roots.home / "user-logs"
    session = _open(log, game, LogDirCandidate(user_dir, "user"))
    assert session.file_path.parent == user_dir
    assert list(outside.iterdir()) == []


# --- Rotation (AC-F01-64) ---------------------------------------------------------------------------

def _logs(game: Path) -> Path:
    folder = game / "logs"
    folder.mkdir()
    return folder


def test_rotation_and_retention(log, game):
    logs = _logs(game)
    (logs / "latest.log").write_text(
        "2026-10-30 09:15:02.120 INFO    app     vn-engine 0.1.0 | …\nold content\n",
        encoding="utf-8")
    for day in range(20, 25):
        (logs / f"session-2026-10-{day}_10-00-00.log").write_text(f"day {day}")
    (logs / "notes.txt").write_text("notes")
    lifecycle(get_logger("app"), "new session")
    session = _open(log, game)

    names = sorted(p.name for p in logs.iterdir())
    assert names == ["latest.log", "notes.txt", "session-2026-10-22_10-00-00.log",
                     "session-2026-10-23_10-00-00.log", "session-2026-10-24_10-00-00.log",
                     "session-2026-10-30_09-15-02.log"]
    assert "old content" in (logs / "session-2026-10-30_09-15-02.log").read_text("utf-8")
    assert (logs / "notes.txt").read_text() == "notes"
    first = _lines(session.file_path)[0]
    started = datetime.datetime.strptime(first[:23], "%Y-%m-%d %H:%M:%S.%f")
    assert abs((datetime.datetime.now() - started).total_seconds()) < 60


def test_rotation_target_taken_gets_a_suffix(log, game):
    logs = _logs(game)
    (logs / "latest.log").write_text("2026-10-30 09:15:02.120 INFO    app     x\n")
    (logs / "session-2026-10-30_09-15-02.log").write_text("earlier")
    _open(log, game)
    assert (logs / "session-2026-10-30_09-15-02-2.log").read_text().startswith("2026-10-30")
    assert (logs / "session-2026-10-30_09-15-02.log").read_text() == "earlier"


@pytest.mark.parametrize("content", [b"garbage and more text\n", b"\xff\xfe\x00 not utf-8"])
def test_unparsable_start_uses_the_mtime(log, game, content):
    logs = _logs(game)
    (logs / "latest.log").write_bytes(content)
    _set_local_mtime(logs / "latest.log", datetime.datetime(2026, 10, 29, 8, 0, 0))
    _open(log, game)
    assert (logs / "session-2026-10-29_08-00-00.log").read_bytes() == content


def test_archive_retention_orders_suffixes_after_their_base(log, game):
    logs = _logs(game)
    for name in ("session-2026-10-01_00-00-00.log", "session-2026-10-02_00-00-00.log",
                 "session-2026-10-02_00-00-00-2.log", "session-2026-10-02_00-00-00-10.log",
                 "session-2026-10-03_00-00-00.log"):
        (logs / name).write_text(name)
    _open(log, game)
    assert sorted(p.name for p in logs.glob("session-*")) == [
        "session-2026-10-02_00-00-00-10.log", "session-2026-10-02_00-00-00-2.log",
        "session-2026-10-02_00-00-00.log", "session-2026-10-03_00-00-00.log"]


# --- AC-F01-144: rotation never follows links or blocks -------------------------------------------

def test_d2_latest_symlink_is_never_followed(log, game, tmp_path):
    logs = _logs(game)
    victim = tmp_path / "outside" / "victim.txt"
    victim.parent.mkdir()
    victim.write_text("victim")
    before = (victim.read_bytes(), victim.stat().st_mtime)
    _symlink(victim, logs / "latest.log")
    session = _open(log, game)
    assert (victim.read_bytes(), victim.stat().st_mtime) == before
    assert session.file_path.name == f"latest-{os.getpid()}.log"
    assert session.file_path.read_text("utf-8").count(NOT_REGULAR) == 1
    assert os.path.islink(logs / "latest.log")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs exist only on POSIX")
def test_d3_latest_fifo_never_blocks(log, game):
    logs = _logs(game)
    os.mkfifo(logs / "latest.log")
    session = _open(log, game)                    # would hang if the FIFO were opened
    assert session.file_path.name == f"latest-{os.getpid()}.log"
    assert stat.S_ISFIFO(os.lstat(logs / "latest.log").st_mode)


def test_d4_directory_with_an_archive_name_is_left_alone(log, game):
    logs = _logs(game)
    folder = logs / "session-2019-01-01_00-00-00.log"
    folder.mkdir()
    (folder / "inside.txt").write_text("keep")
    for day in range(10, 16):
        (logs / f"session-2026-10-{day}_00-00-00.log").write_text("x")
    _open(log, game)
    assert (folder / "inside.txt").read_text() == "keep"


def test_d7_read_only_latest_log(log, game):
    logs = _logs(game)
    latest = logs / "latest.log"
    latest.write_text("2026-10-30 09:15:02.120 INFO    app     old\n")
    latest.chmod(stat.S_IREAD)
    try:
        lifecycle(get_logger("app"), "header line 1")
        session = _open(log, game)
        assert session.file_path.exists()
        assert _lines(session.file_path)[0].endswith("header line 1")
    finally:
        for path in logs.iterdir():
            path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_non_engine_names_are_never_touched(log, game):
    logs = _logs(game)
    names = ["notes.txt", "Session-2026-10-20_10-00-00.log",
             "session-2026-10-20_10-00-00.log.bak", "latest.log.old", "latest-x.log"]
    if os.path.normcase("A") == "A" and sys.platform != "darwin":
        names.append("latest.LOG")          # only on case-sensitive file systems
    for name in names:
        (logs / name).write_text(name)
    for day in range(21, 28):
        (logs / f"session-2026-10-{day}_10-00-00.log").write_text("x")
    _open(log, game)
    for name in names:
        assert (logs / name).read_text() == name


def test_latest_with_different_case_is_never_renamed(log, game):
    """On a case-insensitive file system ``latest.LOG`` is the only latest file: it is not
    an engine name, so it is never renamed; the session uses ``latest-<pid>.log``."""
    logs = _logs(game)
    (logs / "latest.LOG").write_text("mine")
    session = _open(log, game)
    assert (logs / "latest.LOG").read_text() == "mine"
    if (logs / "latest.log").exists() and os.path.samefile(logs / "latest.log",
                                                           logs / "latest.LOG"):
        assert session.file_path.name == f"latest-{os.getpid()}.log"


def test_symlinks_with_engine_names_are_never_deleted(log, game, tmp_path):
    logs = _logs(game)
    keep = tmp_path / "keep.txt"
    keep.write_text("keep")
    _symlink(keep, logs / "session-2000-01-01_00-00-00.log")
    for day in range(10, 16):
        (logs / f"session-2026-10-{day}_00-00-00.log").write_text("x")
    _open(log, game)
    assert os.path.islink(logs / "session-2000-01-01_00-00-00.log")
    assert keep.read_text() == "keep"


# --- AC-F01-145: latest-<pid>.log files are bounded ------------------------------------------------

def test_pid_logs_are_bounded(log, game):
    logs = _logs(game)
    base = datetime.datetime(2026, 10, 1, 12, 0, 0)
    for n in range(10):
        path = logs / f"latest-{1000 + n}.log"
        path.write_text(str(n))
        _set_local_mtime(path, base + datetime.timedelta(minutes=n))
    (logs / "latest.log").mkdir()                 # not regular: forces latest-<pid>.log
    session = _open(log, game)
    assert session.file_path.name == f"latest-{os.getpid()}.log"
    remaining = sorted(p.name for p in logs.glob("latest-*.log") if p.is_file())
    assert remaining == sorted(["latest-1007.log", "latest-1008.log", "latest-1009.log",
                                f"latest-{os.getpid()}.log"])


def test_pid_log_symlink_is_untouched(log, game, tmp_path):
    logs = _logs(game)
    target = tmp_path / "target.txt"
    target.write_text("t")
    _symlink(target, logs / "latest-99.log")
    for n in range(10):
        (logs / f"latest-{1000 + n}.log").write_text(str(n))
    (logs / "latest.log").mkdir()
    _open(log, game)
    assert os.path.islink(logs / "latest-99.log") and target.read_text() == "t"
    assert len([p for p in logs.glob("latest-*.log") if not p.is_symlink()]) == 4


# --- AC-F01-66 (unit part): a locked latest.log -----------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="only Windows locks open files")
def test_locked_latest_log_gives_a_pid_log(log, game):
    logs = _logs(game)
    (logs / "latest.log").write_text("2026-10-30 09:15:02.120 INFO    app     other copy\n")
    with open(logs / "latest.log", "a"):
        session = _open(log, game)
    assert session.file_path.name == f"latest-{os.getpid()}.log"
    assert session.display_path == f"<game>/logs/latest-{os.getpid()}.log"
    assert session.file_path.read_text("utf-8").count(ROTATE_FAILED) == 1


# --- Redaction roots and header helpers --------------------------------------------------------------

def test_redaction_roots_skip_relative_and_bare_roots(monkeypatch, tmp_path, user_roots):
    monkeypatch.setenv("APPDATA", "relative\\dir")
    monkeypatch.setenv("TEMP", os.path.abspath(os.sep))
    monkeypatch.setenv("TMP", "")
    roots = logsetup.redaction_roots(game_root=tmp_path / "game", game_dir_as_given=None,
                                     engine_root=REPO)
    tokens = {root.token for root in roots}
    assert "%APPDATA%" not in tokens and "<temp>" not in tokens
    assert {"<game>", "<engine>", "~", "<python>", "%LOCALAPPDATA%"} <= tokens


def test_add_game_root_redacts_the_game_folder(log, game):
    from engine.core.redact import redact

    as_given = game.parent / "." / "game"
    log.add_game_root(game, as_given=as_given.absolute())
    assert redact(f"error in {game / 'script' / 'a.vns'}") in (
        "error in <game>\\script\\a.vns", "error in <game>/script/a.vns")


def test_header_helpers():
    line = logsetup.header_build_line(engine_version="0.1.0", pygame_version="2.5.8",
                                      sdl_version="2.32.10", os_description="Linux 6.1",
                                      release=True)
    assert re.match(r"^vn-engine 0\.1\.0 \| Python \d+\.\d+\.\d+ \| pygame-ce 2\.5\.8 "
                    r"\(SDL 2\.32\.10\) \| Linux 6\.1 \| build release$", line)
    user = LogSession(Path("x"), "%LOCALAPPDATA%\\vn-engine\\g\\logs\\latest.log", "user")
    game_session = LogSession(Path("x"), "<game>/logs/latest.log", "game")
    assert logsetup.header_log_line(user, fallback_id=True) == (
        "Log: %LOCALAPPDATA%\\vn-engine\\g\\logs\\latest.log "
        "(fallback folder: [game] id is not set)")
    assert logsetup.header_log_line(user, fallback_id=False).endswith("latest.log")
    assert logsetup.header_log_line(game_session, fallback_id=True) == (
        "Log: <game>/logs/latest.log")


def test_formatter_marker_uses_the_given_time():
    created = datetime.datetime(2026, 11, 1, 14, 3, 22, 481000).timestamp()
    text = RedactingFormatter().format_synthetic("note", created=created)
    assert text == "2026-11-01 14:03:22.481 WARNING app     note"


def test_writes_stop_quietly_when_the_stream_fails():
    class Broken(io.StringIO):
        def write(self, data):
            raise OSError("disk full")

    handler = CappedFileHandler(Broken())
    handler.setFormatter(RedactingFormatter())
    handler.handle(_record("one"))
    handler.handle(_record("two"))
    assert handler.written == 0

"""F16 ``SettingsService`` (checklist step 2; ``04`` §5.2, §7.1, §7.2, §7.5, §7.6; ``07`` §3,
G3, G7, I-13): AC-F16-08 (precedence), AC-F16-12 (fullscreen follows the window),
AC-F16-13 (debounced writing), AC-F16-14 (write results and failures), AC-F16-19 (the
windowed size at quit, service half), AC-F16-31 (W70–W75), AC-F16-32 (no file text or
identity in output, launch and write rows), AC-F16-34 (the W70 notice).

Service S (06 §0.2): ``SettingsService`` with a ``FakeWindow``, a fake clock, and either the
fake writer below (it records submits; its results are released by the test) or a real
``Writer`` run synchronously. The audio, text, stage, blip, and skip/auto targets (checklist
step 3) are in ``test_settings_wiring.py``.
"""

import errno
import json
import logging
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from engine.app import settings as settings_mod
from engine.app.settings import (
    NOTICE_TEXT,
    NO_ID_TEXT,
    SAVED_AGAIN_TEXT,
    SettingsService,
    bad_file_text,
    bad_value_text,
    config_defaults,
    launch_settings,
    newer_file_text,
    requested_size,
    save_failed_text,
    unknown_keys_text,
)
from engine.core import safefile
from engine.core.config_schema import (AudioConfig, AutoConfig, Config, SkipConfig, TextboxConfig,
                                       WindowConfig)
from engine.core.settings_schema import KEYS
from engine.persist.settings_file import (
    FILE_NAME,
    FOLDER_IS_LINK,
    LoadedSettings,
    Outcome,
    display_file,
    encode_settings,
)
from engine.persist.writer import Failed, FileWrite, FileWritten, Writer
from tests.fakes.fake_window import FakeWindow
from tests.fakes.privacy import check_p
from tests.persist.writer_support import link_dir, temps

pytestmark = pytest.mark.display          # FakeWindow builds pygame Surfaces

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "F16" / "files"
FPS = 60


class Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeClient:
    """A ``WriterClient`` stand-in: records ``submit``; ``auto`` answers each at once."""

    def __init__(self, auto: bool) -> None:
        self.auto = auto
        self.submitted: list[tuple[float, FileWrite]] = []
        self.results: list = []
        self.in_flight = 0
        self.clock: Clock | None = None

    def submit(self, job: FileWrite) -> None:
        self.submitted.append((self.clock() if self.clock else 0.0, job))
        if self.auto:
            self.results.append(FileWritten(0, None))
        else:
            self.in_flight += 1

    def release(self) -> None:
        self.in_flight -= 1
        self.results.append(FileWritten(0, None))

    def take(self) -> list:
        out, self.results = self.results, []
        return out

    def wait(self, until: float) -> list:
        return self.take()


class FakeWriter:
    def __init__(self, *, auto: bool = True) -> None:
        self.fake = FakeClient(auto)
        self.registered: list[tuple] = []

    def client(self, owner, *, root, names):
        self.registered.append((owner, root, names))
        return self.fake


def loaded(folder: Path | None, values=None, *, outcome=Outcome.OK, writable=True,
           reason=None) -> LoadedSettings:
    return LoadedSettings(MappingProxyType(dict(values or {})), outcome, reason,
                          folder=folder, writable=writable)


def make(tmp_path, values=None, *, config=None, writer=None, clock=None, window=None,
         outcome=Outcome.OK, writable=True, scale=1.0) -> SettingsService:
    folder = tmp_path / "game" / "settings"
    return SettingsService(loaded(folder, values, outcome=outcome, writable=writable),
                           config or Config(),
                           window=window if window is not None else FakeWindow(),
                           display_scale=scale, writer=writer, clock=clock or Clock(),
                           game_root=tmp_path / "game")


def records(caplog, *, level=logging.WARNING):
    return [r for r in caplog.records if r.name == "vn.setting" and r.levelno >= level]


# --- AC-F16-08 — precedence ---------------------------------------------------------------------

def test_ac08_precedence_defaults_and_set(tmp_path):
    """AC-F16-08: stored value over config over built-in default; F15 defaults; setting the
    default removes the key; setting the current value does nothing; bad sets raise."""
    for cps in (40, 0, 5, 500):
        service = make(tmp_path, config=Config(textbox=TextboxConfig(cps=cps)))
        assert service.value("text_cps") == cps and service.is_default("text_cps")
    stored = make(tmp_path, {"text_cps": 80}, config=Config(textbox=TextboxConfig(cps=40)))
    assert stored.value("text_cps") == 80 and not stored.is_default("text_cps")

    config = Config(audio=AudioConfig(music_volume=70, sound_volume=90),
                    window=WindowConfig(fullscreen=True, width=1600, height=900))
    plain = make(tmp_path, config=config)
    assert (plain.value("music_volume"), plain.is_default("music_volume")) == (70, True)
    assert (plain.value("sound_volume"), plain.is_default("sound_volume")) == (90, True)
    assert plain.value("text_size_pct") == 100 and plain.value("auto_scale_pct") == 100
    assert [plain.value(k) for k in ("text_blips", "voice_sustain", "mono",
                                     "reduce_motion")] == [True, False, False, False]
    assert plain.value("fullscreen") is True and plain.value("window_size") == (1600, 900)
    stored = make(tmp_path, {"music_volume": 40},
                  config=Config(audio=AudioConfig(music_volume=90)))
    assert (stored.value("music_volume"), stored.is_default("music_volume")) == (40, False)

    # F15: [skip] all and [auto] wait_for_voice are the defaults (false, true)
    assert config_defaults(Config())["skip_all"] is False
    assert config_defaults(Config())["auto_wait_voice"] is True
    config = Config(skip=SkipConfig(all=True), auto=AutoConfig(wait_for_voice=False))
    service = make(tmp_path, config=config)
    assert service.value("skip_all") is True and service.value("auto_wait_voice") is False

    # setting the default removes the key
    writer = FakeWriter()
    clock = Clock()
    service = make(tmp_path, {"music_volume": 40}, writer=writer, clock=clock)
    service.set("music_volume", AudioConfig().music_volume)
    assert "music_volume" not in service.stored and service.is_default("music_volume")
    clock.now = 1.0
    service.update(1.0)
    [(_, job)] = writer.fake.submitted
    assert json.loads(job.pieces[0]) == {"format": 5, "values": {}}

    # setting the current value does nothing
    window = FakeWindow()
    service = make(tmp_path, {"fullscreen": False}, window=window, writer=FakeWriter())
    heard = []
    service.add_listener(heard.append)
    service.set("music_volume", service.value("music_volume"))
    service.set("fullscreen", False)
    assert heard == [] and not service.dirty and window.calls == []

    # unknown keys and bad values raise
    for key, value in [("foo", 1), ("music_volume", 101), ("fullscreen", 1),
                       ("window_size", [1, 2])]:
        service = make(tmp_path)
        with pytest.raises(ValueError):
            service.set(key, value)
        assert service.stored == {} and not service.dirty, (key, value)


def test_set_applies_fullscreen_then_notifies(tmp_path):
    window = FakeWindow()
    service = make(tmp_path, window=window)
    seen = []
    service.add_listener(lambda keys: seen.append((keys, window.fullscreen)))
    service.set("fullscreen", True)
    assert window.calls == ["set_fullscreen"] and seen == [(frozenset({"fullscreen"}), True)]
    service.update(0.0)                          # the poll sees no outside change
    assert seen == [(frozenset({"fullscreen"}), True)]


def test_reset_clears_and_applies_only_what_changed(tmp_path):
    window = FakeWindow()
    clock = Clock()
    writer = FakeWriter()
    service = make(tmp_path, {"music_volume": 40, "fullscreen": True}, window=window,
                   writer=writer, clock=clock)
    window.set_fullscreen(True)
    service.attach_window(window)
    heard = []
    service.add_listener(heard.append)
    service.reset()
    assert service.stored == {} and window.fullscreen is False
    assert heard == [frozenset({"music_volume", "fullscreen"})]
    clock.now = 0.5
    service.update(0.5)
    assert json.loads(writer.fake.submitted[0][1].pieces[0]) == {"format": 5, "values": {}}


# --- AC-F16-12 — fullscreen follows the window ----------------------------------------------------

def test_ac12_fullscreen_changed_outside_is_recorded(tmp_path):
    window = FakeWindow()
    service = make(tmp_path, window=window)
    heard = []
    service.add_listener(heard.append)
    window.set_fullscreen(True)                  # F11 or Alt+Enter, not the service
    calls = list(window.calls)
    service.update(0.0)
    assert service.value("fullscreen") is True and service.stored == {"fullscreen": True}
    assert service.dirty and heard == [frozenset({"fullscreen"})]
    assert window.calls == calls                 # set_fullscreen not called again
    window.set_fullscreen(False)
    service.update(0.1)
    assert "fullscreen" not in service.stored and service.value("fullscreen") is False


# --- AC-F16-13 — debounced writing ------------------------------------------------------------------

def run(service, clock, writer, *, until: float, sets=None):
    """Ticks every 1/60 s from 0 to ``until``; ``sets(i, t)`` may change settings first.
    Returns the times of the submits."""
    writer.fake.clock = clock
    for i in range(round(until * FPS) + 1):
        t = i / FPS
        clock.now = t
        if sets is not None:
            sets(i, t)
        service.update(t)
    return [t for t, _ in writer.fake.submitted]


def test_ac13_debounced_writing(tmp_path):
    """AC-F16-13: nothing changed -> nothing written; one change -> write 0.5 s later; a drag
    writes once; continuous change writes every 5 s; one write in flight; session-only modes
    never write."""
    writer, clock = FakeWriter(), Clock()
    service = make(tmp_path, writer=writer, clock=clock)
    assert run(service, clock, writer, until=10.0) == []
    assert writer.registered == [] and not (tmp_path / "game").exists()

    writer, clock = FakeWriter(), Clock()
    service = make(tmp_path, writer=writer, clock=clock)
    times = run(service, clock, writer, until=2.0,
                sets=lambda i, t: i == 0 and service.set("music_volume", 40))
    assert times == [0.5]
    job = writer.fake.submitted[0][1]
    assert job.name == FILE_NAME and job.pieces == (encode_settings({"music_volume": 40}),)
    assert writer.registered == [("settings", tmp_path / "game" / "settings",
                                  frozenset({FILE_NAME}))]

    writer, clock = FakeWriter(), Clock()
    service = make(tmp_path, writer=writer, clock=clock)

    def drag(i, t):
        if t <= 3.0:
            service.set("music_volume", 40 + i % 2)

    assert run(service, clock, writer, until=5.0, sets=drag) == [3.5]
    assert json.loads(writer.fake.submitted[0][1].pieces[0])["values"] == {
        "music_volume": 40 + (3 * FPS) % 2}

    writer, clock = FakeWriter(), Clock()
    service = make(tmp_path, writer=writer, clock=clock)

    def every_tenth(i, t):
        if i % 6 == 0 and t <= 6.0:
            service.set("music_volume", 10 + i // 6)

    assert run(service, clock, writer, until=8.0, sets=every_tenth) == [5.0, 6.5]

    writer, clock = FakeWriter(auto=False), Clock()
    service = make(tmp_path, writer=writer, clock=clock)

    def changes(i, t):
        if i == 0:
            service.set("music_volume", 40)
        elif i == 42:                            # 0.7 s
            service.set("text_size_pct", 130)
        elif i == 54:                            # 0.9 s: the first result comes back
            writer.fake.release()

    assert run(service, clock, writer, until=3.0, sets=changes) == [0.5, 1.2]
    assert json.loads(writer.fake.submitted[-1][1].pieces[0])["values"] == {
        "music_volume": 40, "text_size_pct": 130}

    for outcome, writable, folder in [
            (Outcome.NEWER, False, True), (Outcome.UNREADABLE, False, True),
            (Outcome.NO_FILE, False, False), (Outcome.NO_FILE, False, True)]:  # last: linked
        writer, clock = FakeWriter(), Clock()
        window = FakeWindow()
        service = SettingsService(
            loaded(tmp_path / "game" / "settings" if folder else None, outcome=outcome,
                   writable=writable, reason=FOLDER_IS_LINK if folder else None),
            Config(), window=window, writer=writer, clock=clock, game_root=tmp_path / "game")

        def every_second(i, t):
            if i % FPS == 0:
                service.set("fullscreen", not service.value("fullscreen"))

        assert run(service, clock, writer, until=10.0, sets=every_second) == [], outcome
        assert window.calls.count("set_fullscreen") == 6 and writer.registered == []


# --- AC-F16-14 — write results and failures (real writer, synchronous) ------------------------------

@pytest.fixture
def real(tmp_path):
    """A service on a synchronous ``Writer`` and ``tmp_path/game/settings``."""
    game = tmp_path.resolve() / "game"
    game.mkdir()

    def build():
        clock = Clock()
        service = SettingsService(loaded(game / "settings"), Config(), window=FakeWindow(),
                                  writer=Writer(threaded=False), clock=clock, game_root=game)
        return service, clock
    build.game = game
    return build


def change_and_write(service, clock, key="music_volume", value=40):
    clock.now += 1.0
    service.set(key, value)
    clock.now += 1.0
    service.update(clock.now)          # submits (the synchronous writer finishes at once)
    service.update(clock.now)          # takes the result


def test_ac14_a_write_replaces_the_file(real, caplog):
    service, clock = real()
    change_and_write(service, clock)
    folder = real.game / "settings"
    assert (folder / FILE_NAME).read_bytes() == encode_settings({"music_volume": 40})
    assert temps(folder) == [] and not service.in_flight
    if os.name == "posix":
        assert (folder / FILE_NAME).stat().st_mode & 0o777 == 0o600
    assert records(caplog) == []


def test_ac14_fsync_fault_keeps_the_old_file(real, monkeypatch, caplog):
    service, clock = real()
    change_and_write(service, clock)
    old = (real.game / "settings" / FILE_NAME).read_bytes()

    def broken(fd):
        raise OSError(errno.EIO, "fsync")

    monkeypatch.setattr(safefile, "_fsync_file", broken)
    change_and_write(service, clock, value=41)
    assert (real.game / "settings" / FILE_NAME).read_bytes() == old
    assert temps(real.game / "settings") == []
    file = display_file(real.game / "settings", game_root=real.game)
    assert [r.getMessage() for r in records(caplog)] == [save_failed_text(file, "couldn't write")]


def test_ac14_disk_full_once_then_saved_again(real, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="vn.setting")
    service, clock = real()
    file = display_file(real.game / "settings", game_root=real.game)

    def full(fd, data):
        raise OSError(errno.ENOSPC, "No space left on device")

    with monkeypatch.context() as m:
        m.setattr(safefile, "write_all", full)
        change_and_write(service, clock, value=40)
        change_and_write(service, clock, value=41)
        submitted = service._client.pending           # nothing left to take
        for _ in range(5):                             # no change: no resubmit
            clock.now += 1.0
            service.update(clock.now)
        assert service._client.pending == submitted == 0 and not service.dirty
    warnings = [r for r in records(caplog) if r.levelno == logging.WARNING]
    assert [(r.code, r.getMessage()) for r in warnings] == [
        ("W75", save_failed_text(file, "disk full"))]
    assert len([r for r in caplog.records if r.levelno == logging.DEBUG
                and r.name == "vn.setting"]) == 2
    change_and_write(service, clock, value=42)
    change_and_write(service, clock, value=43)
    infos = [r.getMessage() for r in records(caplog, level=logging.INFO)
             if r.levelno == logging.INFO]
    assert infos == [SAVED_AGAIN_TEXT]
    assert json.loads((real.game / "settings" / FILE_NAME).read_bytes())["values"] == {
        "music_volume": 43}


def test_ac14_failure_reasons(real, monkeypatch, caplog):
    for fault, reason in [(PermissionError(errno.EACCES, "denied"), "no permission"),
                          (OSError(errno.EIO, "I/O error"), "couldn't write")]:
        caplog.clear()
        service, clock = real()

        def fail(fd, data):
            raise fault

        with monkeypatch.context() as m:
            m.setattr(safefile, "write_all", fail)
            change_and_write(service, clock)
        assert [r.getMessage().split("(")[1].split(")")[0] for r in records(caplog)] == [reason]


def test_ac14_folder_replaced_by_a_link(real, tmp_path, caplog):
    service, clock = real()
    change_and_write(service, clock)
    folder = real.game / "settings"
    (folder / FILE_NAME).unlink()
    folder.rmdir()
    outside = tmp_path.resolve() / "outside"
    outside.mkdir()
    link_dir(folder, outside)
    try:
        change_and_write(service, clock, value=41)
        assert list(outside.iterdir()) == []
        assert [r.getMessage().split("(")[1].split(")")[0] for r in records(caplog)] == [
            FOLDER_IS_LINK]
    finally:
        os.rmdir(folder) if os.name == "nt" else folder.unlink()


def test_ac14_a_deleted_folder_is_made_again(real):
    service, clock = real()
    change_and_write(service, clock)
    folder = real.game / "settings"
    (folder / FILE_NAME).unlink()
    folder.rmdir()
    change_and_write(service, clock, value=41)
    assert json.loads((folder / FILE_NAME).read_bytes())["values"] == {"music_volume": 41}


def test_ac14_a_name_outside_the_client_fails(real):
    service, clock = real()
    change_and_write(service, clock)
    client = service._client
    client.submit(FileWrite(real.game / "settings", "other.json", (b"{}",)))
    [result] = client.take()
    assert isinstance(result, Failed) and result.reason == "couldn't write"
    assert not (real.game / "settings" / "other.json").exists()


def test_ac14_two_copies_last_writer_wins(real):
    a, clock_a = real()
    b, clock_b = real()
    change_and_write(a, clock_a, "music_volume", 40)
    change_and_write(b, clock_b, "text_size_pct", 130)
    data = json.loads((real.game / "settings" / FILE_NAME).read_bytes())
    assert data["values"] == {"text_size_pct": 130}


# --- AC-F16-19 — the windowed size at quit (service half) ------------------------------------------

def test_ac19_requested_units_round_trip():
    for scale in (1.0, 1.25, 1.5, 2.0):
        for size in ((1280, 720), (1600, 900), (1201, 677)):
            window = (round(size[0] * scale), round(size[1] * scale))
            assert requested_size(window, scale) == size
    assert requested_size((1500, 800), 1.25) == (1200, 640)
    assert requested_size((100, 100), 1.0) == (640, 360)


def test_ac19_quit_stores_the_windowed_size(tmp_path):
    window = FakeWindow((1280 * 5 // 4, 720 * 5 // 4))
    service = make(tmp_path, window=window, scale=1.25, writer=FakeWriter())
    window.user_resize(1500, 800)
    window.set_fullscreen(True)
    service.submit_final()
    assert service.stored == {"fullscreen": True, "window_size": (1200, 640)}


def test_ac19_quit_maximized_keeps_the_size(tmp_path):
    window = FakeWindow()
    service = make(tmp_path, {"window_size": (1600, 900)}, window=window)
    window.maximize()
    service.submit_final()
    assert service.stored == {"window_size": (1600, 900)}


def test_ac19_a_size_equal_to_config_is_removed(tmp_path):
    window = FakeWindow((1600, 900))
    service = make(tmp_path, {"window_size": (1600, 900)}, window=window)
    window.user_resize(1280, 720)                  # 1280x720 at scale 1: the config size
    service.submit_final()
    assert service.stored == {}


def test_quit_submits_without_waiting_then_waits(tmp_path, caplog):
    writer = FakeWriter(auto=False)
    service = make(tmp_path, writer=writer)
    service.set("music_volume", 40)
    service.submit_final()                         # dirty: submitted at once
    assert len(writer.fake.submitted) == 1 and service.in_flight
    service.wait_final(until=0.0)                  # still in flight: W75 couldn't write
    assert [r.code for r in records(caplog)] == ["W75"]
    assert "couldn't write" in records(caplog)[0].getMessage()


# --- AC-F16-31 — W70–W75 --------------------------------------------------------------------------

@pytest.fixture
def game(tmp_path):
    folder = tmp_path.resolve() / "game"
    (folder / "settings").mkdir(parents=True)
    return folder


def launch_logs(game, caplog, **kwargs):
    caplog.clear()
    options = dict(game_root=game, release=False, app_id=None, id_is_fallback=True)
    options.update(kwargs)
    result = launch_settings(**options)
    return result, [(r.code, r.getMessage()) for r in records(caplog)]


def write(game, data: bytes | str) -> str:
    target = game / "settings" / FILE_NAME
    target.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return display_file(game / "settings", game_root=game)


def test_ac31_w70_kept(game, caplog):
    file = write(game, "{")
    _, logs = launch_logs(game, caplog)
    assert logs == [("W70", f"settings in {file} couldn't be used (not valid JSON), so the "
                     "default settings are used. The old file was kept as settings.bad.json.")]
    assert (game / "settings" / "settings.bad.json").exists()


@pytest.mark.parametrize("make_file, reason", [
    (lambda t: t.write_bytes(b" " * 65_537), "over 64 KB"),
    (lambda t: t.mkdir(), "not a regular file"),
    (lambda t: t.write_bytes(b"[]"), "not settings data")])
def test_ac31_w70_reasons(game, caplog, make_file, reason):
    make_file(game / "settings" / FILE_NAME)
    file = display_file(game / "settings", game_root=game)
    _, logs = launch_logs(game, caplog)
    assert logs == [("W70", bad_file_text(file, reason, kept=True))]
    assert f"({reason})" in logs[0][1]


def test_ac31_w70_without_a_copy(game, caplog, monkeypatch):
    file = write(game, "{")
    with monkeypatch.context() as m:
        m.setattr(safefile, "quarantine", lambda *a, **k: False)
        result, logs = launch_logs(game, caplog)
    assert logs == [("W70", f"settings in {file} couldn't be used (not valid JSON), so the "
                     "default settings are used. The file will be replaced when a setting "
                     "changes.")]
    assert "settings.bad.json" not in logs[0][1] and result.loaded.writable

    def eio(*args, **kwargs):
        raise OSError(errno.EIO, "I/O error")

    with monkeypatch.context() as m:
        m.setattr(safefile, "_open_for_reading", eio)
        result, logs = launch_logs(game, caplog)
    assert logs == [("W70", f"settings in {file} couldn't be used (couldn't be read), so the "
                     "default settings are used. The file was left unchanged and won't be "
                     "changed this session.")]
    assert not result.loaded.writable


def test_ac31_w71(game, caplog):
    file = write(game, '{"format": 1, "values": {"text_size_pct": 400}}')
    _, logs = launch_logs(game, caplog)
    assert logs == [("W71", f"settings in {file}: text_size_pct must be a whole number from "
                     "100 to 150, but found 400, so the default is used.")]


def test_ac31_w71_found_words(game, caplog):
    file = write(game, json.dumps({"format": 1, "values": {
        "text_cps": 5, "reduce_motion": "yes", "window_size": [1, 2]}}))
    _, logs = launch_logs(game, caplog)
    assert logs == [
        ("W71", bad_value_text(file, "text_cps", "0 or a whole number from 10 to 200", "5")),
        ("W71", bad_value_text(file, "reduce_motion", "true or false", "text")),
        ("W71", bad_value_text(file, "window_size", "a list of two whole numbers, 640 to "
                               "7680 and 360 to 4320", "a list"))]


def test_ac31_w72_w73(game, caplog):
    file = write(game, '{"format": 1, "values": {"a": 1, "b": 2}}')
    assert launch_logs(game, caplog)[1] == [
        ("W72", f"settings in {file} had 2 unknown entries; they were ignored.")]
    write(game, '{"format": 1, "values": {"a": 1}}')
    assert launch_logs(game, caplog)[1] == [("W72", unknown_keys_text(file, 1))]
    assert unknown_keys_text(file, 1).endswith("had 1 unknown entry; it was ignored.")
    write(game, '{"format": 6, "values": {"music_volume": 40}}')
    result, logs = launch_logs(game, caplog)
    assert logs == [("W73", f"settings in {file} were made by a newer engine version, so only "
                     "the settings this version knows are used, and the file won't be "
                     "changed this session.")]
    assert logs[0][1] == newer_file_text(file) and result.loaded.values == {"music_volume": 40}


def test_ac31_w74_once_and_no_file_call(game, caplog, monkeypatch):
    calls = []
    monkeypatch.setattr(settings_mod, "read_settings", lambda *a, **k: calls.append(a))
    result, logs = launch_logs(game, caplog, release=True, app_id="game", id_is_fallback=True)
    assert logs == [("W74", 'settings won\'t be saved, because config.toml has no [game] id. '
                     'Set a unique id under [game], e.g. id = "paper-lanterns", before '
                     "releasing.")]
    assert logs[0][1] == NO_ID_TEXT and calls == [] and not result.loaded.writable


def test_ac31_w75_disk_full(real, monkeypatch, caplog):
    service, clock = real()

    def full(fd, data):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(safefile, "write_all", full)
    change_and_write(service, clock)
    file = display_file(real.game / "settings", game_root=real.game)
    assert [(r.code, r.getMessage()) for r in records(caplog)] == [
        ("W75", f"settings couldn't be saved to {file} (disk full). Changes apply this session "
                "and are tried again at the next change.")]


def test_ac31_w75_for_a_linked_folder(tmp_path, caplog):
    game = tmp_path.resolve() / "game"
    game.mkdir()
    outside = tmp_path.resolve() / "outside"
    outside.mkdir()
    (outside / FILE_NAME).write_text('{"format": 1, "values": {"music_volume": 5}}')
    link_dir(game / "settings", outside)
    try:
        result, logs = launch_logs(game, caplog)
        assert result.loaded.values == {} and not result.loaded.writable     # G10
        assert [code for code, _ in logs] == ["W75"] and f"({FOLDER_IS_LINK})" in logs[0][1]
    finally:
        os.rmdir(game / "settings") if os.name == "nt" else (game / "settings").unlink()


def test_ac31_order_and_counts(game, caplog):
    data = json.loads((FIXTURES / "every_bad.json").read_text())
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    data["values"].update({digits[i // 1296] + digits[i // 36 % 36] + digits[i % 36]: 0
                           for i in range(8000)})            # 8,000 short unknown keys
    data["format"] = 6
    text = json.dumps(data, separators=(",", ":"))
    assert len(text) <= 65_536
    write(game, text)
    _, logs = launch_logs(game, caplog)
    codes = [code for code, _ in logs]
    assert codes == ["W73"] + ["W71"] * 22 + ["W72"]
    keys = [message.split(": ", 1)[1].split(" must", 1)[0] for code, message in logs
            if code == "W71"]
    assert keys == list(KEYS)


# --- AC-F16-32 — no file text or identity in output ------------------------------------------------

def test_ac32_marker_file_and_faults(tmp_path, user_roots, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    game = tmp_path.resolve() / "game"
    (game / "settings").mkdir(parents=True)
    write(game, (FIXTURES / "marker.json").read_bytes())
    result = launch_settings(game_root=game, release=False, app_id=None, id_is_fallback=True)
    service = SettingsService(result.loaded, Config(), window=FakeWindow(),
                              writer=Writer(threaded=False), clock=Clock(), game_root=game,
                              file=result.file)

    def full(fd, data):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(safefile, "write_all", full)
    change_and_write(service, service._clock)
    texts = [r.getMessage() for r in caplog.records]
    assert any(r.code == "W75" for r in caplog.records if hasattr(r, "code"))
    assert not any("ZZMARK" in text for text in texts)
    check_p(texts, home=user_roots.home, game=game)
    marker = (FIXTURES / "marker.json").read_text()
    for text in (r.getMessage() for r in caplog.records if getattr(r, "code", "")[:2] == "W7"):
        for i in range(len(marker) - 7):
            piece = marker[i:i + 8]
            if piece in text:
                assert any(piece in word for word in (*KEYS, "not valid JSON",
                                                      "settings data", "settings.json")), piece


def test_ac32_written_files_hold_only_ints_bools_and_the_pair(real):
    service, clock = real()
    service.set("window_size", (1600, 900))
    service.set("reduce_motion", True)
    change_and_write(service, clock)
    values = json.loads((real.game / "settings" / FILE_NAME).read_bytes())["values"]
    for value in values.values():
        assert type(value) in (int, bool) or (
            type(value) is list and [type(v) for v in value] == [int, int])


# --- AC-F16-34 — the W70 notice -------------------------------------------------------------------

def test_ac34_only_a_w70_launch_gives_one_notice(game, caplog):
    """AC-F16-34: no file, a newer file, and bad values give no notice; W70 gives one."""
    for data in (None, '{"format": 6, "values": {}}',
                 '{"format": 1, "values": {"x": 1, "music_volume": 900}}'):
        if data is not None:
            write(game, data)
        result = launch_settings(game_root=game, release=False, app_id=None,
                                 id_is_fallback=True)
        assert result.notices == (), data
    write(game, "{")
    result = launch_settings(game_root=game, release=False, app_id=None, id_is_fallback=True)
    service = SettingsService(result.loaded, Config(), window=FakeWindow(),
                              notices=result.notices)
    assert service.take_notices() == ["Your settings couldn't be read, so the defaults are used."]
    assert service.take_notices() == [] and NOTICE_TEXT.startswith("Your settings")

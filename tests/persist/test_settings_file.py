"""F16 ``settings.json`` (``04`` §4, §5.1, §7.1, §8; ``07`` G3, G10, I-7, I-9, I-10):
AC-F16-03 (encode round trip), AC-F16-04 (parse outcomes), AC-F16-05 (hostile inputs never
raise), AC-F16-06 (the launch read on disk), and the folder helpers.

File rows use ``tmp_path/game/settings/``; ``tmp_path/outside/`` holds files whose SHA-256
every row re-checks, and every row checks that nothing appeared outside the settings folder.
Faults are injected by patching ``os`` calls inside ``engine.core.safefile``."""

import errno
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

import pytest

from engine.core import constants, safefile
from engine.core.paths import user_data_dir
from engine.core.settings_schema import KEYS, MAX_FILE_BYTES, BoolKey, IntKey, check
from engine.persist import location, settings_file
from engine.persist.settings_file import (
    BAD_NAME,
    FILE_NAME,
    FOLDER_IS_LINK,
    NOT_REGULAR,
    NOT_SETTINGS,
    NOT_VALID_JSON,
    OVER_CAP,
    UNREADABLE,
    LoadedSettings,
    Outcome,
    display_file,
    encode_settings,
    is_engine_name,
    parse_settings,
    read_settings,
    settings_root,
)
from tests.persist import gen_settings_hostile as gen
from tests.persist.gen_settings_hostile import EXAMPLE, EXAMPLE_VALUES

FILES = gen.FILES


# --- Helpers ----------------------------------------------------------------------------------

def link_dir(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows, a symlink elsewhere; skips if not allowed."""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory links not permitted here: {exc}")


def symlink(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks not permitted here: {exc}")


def fail_on(real, n: int, code: int):
    """A stand-in for ``real`` that raises ``OSError(code)`` from its n-th call on (n=0:
    never)."""
    calls = [0]

    def call(*args, **kwargs):
        calls[0] += 1
        if n and calls[0] >= n:
            raise OSError(code, os.strerror(code))
        return real(*args, **kwargs)
    return call


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class World:
    """``base/game/settings`` and ``base/outside`` (two files); ``check()`` asserts the
    outside hashes are unchanged and that nothing outside the settings folder changed."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.game = base / "game"
        self.game.mkdir()
        self.folder = self.game / "settings"
        self.file = self.folder / FILE_NAME
        self.bad = self.folder / BAD_NAME
        self.outside = base / "outside"
        self.outside.mkdir()
        (self.outside / "secret.json").write_bytes(EXAMPLE)
        (self.outside / "notes.txt").write_bytes(b"ZZMARK qauser7")
        self.hashes = self._hashes()
        self.entries = self._entries()

    def _hashes(self) -> dict[str, str]:
        return {p.name: sha(p) for p in sorted(self.outside.iterdir())}

    def _entries(self) -> set[str]:
        out = set()
        for root, dirs, names in os.walk(self.base, followlinks=False):
            here = Path(root)
            if here == self.folder or self.folder in here.parents:
                dirs[:] = []
                continue
            for name in dirs + names:
                path = here / name
                if path != self.folder:
                    out.add(str(path.relative_to(self.base)))
        return out

    def write(self, data: bytes) -> None:
        self.folder.mkdir(exist_ok=True)
        self.file.write_bytes(data)

    def names(self) -> list[str]:
        return sorted(os.listdir(self.folder))

    def check(self) -> None:
        assert self._hashes() == self.hashes
        assert self._entries() == self.entries


@pytest.fixture
def world(tmp_path) -> World:
    # By its real path: macOS reaches temp folders through /var -> /private, and a dev folder
    # must be its own real path.
    return World(tmp_path.resolve())


def random_values(rng: random.Random) -> dict:
    out: dict = {}
    for key, spec in KEYS.items():
        if rng.random() < 0.5:
            continue
        if isinstance(spec, BoolKey):
            out[key] = rng.random() < 0.5
        elif isinstance(spec, IntKey):
            out[key] = 0 if spec.zero and rng.random() < 0.2 else rng.randint(spec.lo, spec.hi)
        elif key == "language":                                     # F43: a code
            out[key] = rng.choice(("ja", "pt-BR", "zh-Hans", "es-419"))
        else:
            out[key] = (rng.randint(*spec.w), rng.randint(*spec.h))
    return out


# --- Folder helpers (07 I-10; AC-F16-07's root rows) ------------------------------------------

def test_settings_root_dev_release_and_none(tmp_path, user_roots):
    game = tmp_path / "game"
    assert settings_root(game_root=game, release=False, app_id=None) == game / "settings"
    assert settings_root(game_root=game, release=True, app_id="paper-lanterns") == \
        user_data_dir("paper-lanterns") / "settings"
    assert settings_root(game_root=game, release=True, app_id=None) is None
    assert settings_root(game_root=game, release=True, app_id="Bad Id") is None
    assert display_file(game / "settings", game_root=game) == "<game>/settings/settings.json"


def test_user_root_is_the_one_helper(tmp_path, user_roots):
    game = tmp_path / "game"
    for release, app_id in ((False, None), (True, "paper-lanterns"), (True, None)):
        assert location.persistent_root(game_root=game, release=release, app_id=app_id) == \
            location.user_root("persistent", game_root=game, release=release, app_id=app_id)
    assert location.display_file(game / "persistent", game_root=game) == \
        "<game>/persistent/persistent.json"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows display form")
def test_display_form_windows(tmp_path, user_roots):
    root = settings_root(game_root=tmp_path, release=True, app_id="paper-lanterns")
    assert display_file(root, game_root=None) == \
        r"%APPDATA%\vn-engine\paper-lanterns\settings\settings.json"


def test_save_dirnames_has_settings_and_only_three_names():
    assert "settings" in constants.SAVE_DIRNAMES
    assert settings_file.FOLDER_NAME == "settings"
    assert (FILE_NAME, BAD_NAME) == ("settings.json", "settings.bad.json")
    assert settings_file.LOG_AREA == "setting"
    assert is_engine_name(safefile.temp_name(FILE_NAME, safefile.temp_token()))
    for name in (FILE_NAME, BAD_NAME):
        assert is_engine_name(name)
    for other in (".settings.json.XYZ.tmp", ".settings.json.deadbeef0.tmp", "notes.txt",
                  "settings.json.bak", "persistent.json"):
        assert not is_engine_name(other)


def test_committed_fixtures_match_the_generator():
    for name, make in gen.FIXTURES.items():
        assert (FILES / name).read_bytes() == make(), name


# --- AC-F16-03 --------------------------------------------------------------------------------

def _ordered_pairs(data: bytes) -> list[list[str]]:
    orders: list[list[str]] = []

    def hook(pairs):
        orders.append([k for k, _ in pairs])
        return dict(pairs)
    json.loads(data, object_pairs_hook=hook)
    return orders


def _assert_round_trip(values: dict) -> None:
    data = encode_settings(values)
    assert data.isascii() and all(b < 0x80 for b in data)
    for order in _ordered_pairs(data):
        assert order == sorted(order)
    loaded = parse_settings(data)
    assert loaded.outcome is Outcome.OK and loaded.writable
    assert dict(loaded.values) == values
    assert loaded.problems == () and loaded.unknown == 0


def test_ac_f16_03_example_encodes_to_the_04_4_text():
    data = encode_settings(EXAMPLE_VALUES)
    assert data == EXAMPLE
    assert data == (FILES / "valid.json").read_bytes()
    lines = data.decode("ascii").splitlines()
    assert lines[1] == '  "format": 5,' and lines[3] == '    "music_volume": 40,'   # indent=2
    assert _ordered_pairs(data) == [
        ["music_volume", "reduce_motion", "text_size_pct", "window_size"],
        ["format", "values"]]
    _assert_round_trip(EXAMPLE_VALUES)
    assert encode_settings({**EXAMPLE_VALUES, "window_size": [1280, 720]}) == EXAMPLE


def test_ac_f16_03_empty_values():
    data = encode_settings({})
    assert json.loads(data) == {"format": 5, "values": {}}
    assert parse_settings(data).outcome is Outcome.OK


def test_ac_f16_03_encode_refuses_what_check_refuses():
    for values in ({"foo": 1}, {"music_volume": 101}, {"mono": 1}, {"window_size": [1, 2]}):
        with pytest.raises(ValueError):
            encode_settings(values)


def _fuzz_round_trip(count: int) -> None:
    rng = random.Random(1)
    for _ in range(count):
        _assert_round_trip(random_values(rng))


def test_ac_f16_03_fuzz_default():
    _fuzz_round_trip(50)


@pytest.mark.slow
def test_ac_f16_03_fuzz_slow():
    _fuzz_round_trip(2000)


# --- AC-F16-04 --------------------------------------------------------------------------------

def dumps(obj) -> bytes:
    return json.dumps(obj).encode("ascii")


BAD_ROWS = [
    (b"", NOT_VALID_JSON), (b"{", NOT_VALID_JSON), (b"\xff", NOT_VALID_JSON),
    (b"\xef\xbb\xbf" + EXAMPLE, NOT_VALID_JSON),
    (b'{"format": 1, "format": 1, "values": {}}', NOT_VALID_JSON),
    (b'{"format": 1, "values": {"music_volume": NaN}}', NOT_VALID_JSON),
    (b'{"format": 1, "values": {"music_volume": -Infinity}}', NOT_VALID_JSON),
    (b"[" * 1001, NOT_VALID_JSON),
    (b"[" * 1001 + b"]" * 1001, NOT_VALID_JSON),
    (b'{"format": 1, "values": {"x": ' + b"[" * 1001 + b"]" * 1001 + b"}}", NOT_VALID_JSON),
    (b"[]", NOT_SETTINGS), (b"1", NOT_SETTINGS), (b'"x"', NOT_SETTINGS),
    (b'{"values": {}}', NOT_SETTINGS),
    (b'{"format": "1", "values": {}}', NOT_SETTINGS),
    (b'{"format": true, "values": {}}', NOT_SETTINGS),
    (b'{"format": 1.0, "values": {}}', NOT_SETTINGS),
    (b'{"format": 0, "values": {}}', NOT_SETTINGS),
    (b'{"format": -1, "values": {}}', NOT_SETTINGS),
    (b'{"format": ' + b"1" * 21 + b', "values": {}}', NOT_SETTINGS),
    (b'{"format": 1, "values": {}, "extra": 1}', NOT_SETTINGS),
    (b'{"format": 1, "values": []}', NOT_SETTINGS),
    (b'{"format": 1}', NOT_SETTINGS),
    (b"[" * 1000 + b"]" * 1000, NOT_SETTINGS),                    # 1,000 levels parse
]


def test_ac_f16_04_parse_outcomes(monkeypatch):
    """AC-F16-04: every BAD row, the BOM fixture, the example, mixed values, long numbers,
    problems in KEYS order, NEWER shapes, older formats, and the size cap."""
    for n, (data, reason) in enumerate(BAD_ROWS):
        loaded = parse_settings(data)
        assert loaded.outcome is Outcome.BAD and loaded.bad_reason == reason, n
        assert dict(loaded.values) == {} and loaded.problems == () and loaded.unknown == 0, n
        assert loaded.writable, n
    assert parse_settings((FILES / "bom.json").read_bytes()).bad_reason == NOT_VALID_JSON

    loaded = parse_settings(EXAMPLE)
    assert (loaded.outcome, loaded.bad_reason, loaded.writable) == (Outcome.OK, None, True)
    assert dict(loaded.values) == EXAMPLE_VALUES
    assert loaded.values["window_size"] == (1280, 720)
    assert loaded.problems == () and loaded.unknown == 0

    loaded = parse_settings((FILES / "mixed.json").read_bytes())
    assert loaded.outcome is Outcome.OK and loaded.writable
    assert dict(loaded.values) == {"text_cps": 40}
    assert [(p.key, p.found) for p in loaded.problems] == [("music_volume", "400")]
    assert loaded.unknown == 2

    data = (b'{"format": 1, "values": {"music_volume": ' + b"9" * 5000
            + b', "mono": 1e999}}')
    loaded = parse_settings(data)
    assert loaded.outcome is Outcome.OK and dict(loaded.values) == {}
    assert [(p.key, p.found) for p in loaded.problems] == [
        ("music_volume", "a long number"), ("mono", "a decimal number")]
    # 20 digits still parse as a number; 21 become the marker.
    twenty = parse_settings(b'{"format": 1, "values": {"music_volume": ' + b"9" * 20 + b"}}")
    assert twenty.problems[0].found == "a long number"
    neg = parse_settings(b'{"format": 1, "values": {"music_volume": -' + b"9" * 21 + b"}}")
    assert neg.problems[0].found == "a long number"

    loaded = parse_settings((FILES / "every_bad.json").read_bytes())
    assert loaded.outcome is Outcome.OK and dict(loaded.values) == {}
    assert [p.key for p in loaded.problems] == list(KEYS)
    assert [p.found for p in loaded.problems] == [
        "5", "400", "24", "text", "1", "-1", "101", "null", "a long number", "an object",
        "a list", "0", "text", "a decimal number", "text", "text", "a list", "1001", "3",
        "text", "text", "3"]

    loaded = parse_settings((FILES / "newer.json").read_bytes())
    assert loaded.outcome is Outcome.NEWER and not loaded.writable
    assert dict(loaded.values) == {"music_volume": 40}
    assert loaded.problems == () and loaded.unknown == 1
    for data, values in [
            (b'{"format": 6, "values": {"music_volume": 40}, "extra": 1}', {"music_volume": 40}),
            (b'{"format": 6, "values": "x"}', {}),
            (b'{"format": 6}', {}),
            (b'{"format": ' + b"9" * 20 + b', "values": {"mono": true}}', {"mono": True})]:
        loaded = parse_settings(data)
        assert loaded.outcome is Outcome.NEWER and not loaded.writable, data
        assert dict(loaded.values) == values and loaded.problems == (), data

    data = EXAMPLE + b" " * (MAX_FILE_BYTES + 1 - len(EXAMPLE))
    assert parse_settings(data).bad_reason == OVER_CAP
    assert parse_settings(data[:-1]).outcome is Outcome.OK

    # 07 I-7: with FORMAT 2, a format 1 file is OK and writable.
    monkeypatch.setattr(settings_file, "FORMAT", 2)
    for version in (1, 2):
        loaded = parse_settings(dumps({"format": version, "values": {"music_volume": 40}}))
        assert loaded.outcome is Outcome.OK and loaded.writable
        assert dict(loaded.values) == {"music_volume": 40}
    assert parse_settings(dumps({"format": 1, "values": {}, "x": 1})).outcome is Outcome.BAD
    assert parse_settings(dumps({"format": 3, "values": {}})).outcome is Outcome.NEWER
    assert json.loads(encode_settings({}))["format"] == 2


# --- AC-F16-05 --------------------------------------------------------------------------------

def _assert_sane(loaded: LoadedSettings) -> None:
    assert isinstance(loaded, LoadedSettings)
    assert isinstance(loaded.outcome, Outcome)
    for key, value in loaded.values.items():
        assert check(key, value) is None
    keys = [p.key for p in loaded.problems]
    assert len(keys) == len(set(keys))
    assert set(keys).isdisjoint(loaded.values)


def test_ac_f16_05_hostile_inputs_default_tier():
    """AC-F16-05 (default tier): 200 hostile inputs, the nesting crossing sizes, and the
    quote worst cases stay linear. Full size and timing: the slow and perf tests below."""
    inputs = gen.hostile_inputs(1, 200, full=False)
    assert len(inputs) == 200
    for data in inputs:
        _assert_sane(parse_settings(data))
    assert parse_settings(b'{"a":' * 1001 + b"1" + b"}" * 1001).bad_reason == NOT_VALID_JSON
    # A 1,001-deep value inside a string is text, not nesting. (The 1,000/1,001-deep list
    # rows are in BAD_ROWS for AC-F16-04.)
    inside = dumps({"format": 1, "values": {"x": "[" * 2000}})
    assert parse_settings(inside).outcome is Outcome.OK
    for data in (gen.worst_cases()["escaped quotes"], gen.worst_cases()["unclosed quotes"]):
        start = time.perf_counter()
        _assert_sane(parse_settings(data))
        assert time.perf_counter() - start < 1.0


def _worst_case_times() -> dict[str, float]:
    times = {}
    for name, data in gen.worst_cases().items():
        assert len(data) <= MAX_FILE_BYTES, name
        best = float("inf")
        for _ in range(3):
            start = time.perf_counter()
            loaded = parse_settings(data)
            best = min(best, time.perf_counter() - start)
        _assert_sane(loaded)
        times[name] = best
    return times


@pytest.mark.slow
def test_ac_f16_05_hostile_full_size():
    inputs = gen.hostile_inputs(1, 2000, full=True)
    for data in inputs:
        assert len(data) <= MAX_FILE_BYTES
        _assert_sane(parse_settings(data))
    for name, seconds in _worst_case_times().items():
        assert seconds <= 0.100, (name, seconds)


@pytest.mark.perf
def test_ac_f16_05_perf_worst_cases():
    for name, seconds in _worst_case_times().items():
        assert seconds <= 0.030, (name, seconds)


# --- AC-F16-06 --------------------------------------------------------------------------------

def test_ac_f16_06_no_folder(world):
    loaded = read_settings(world.folder)
    assert (loaded.outcome, loaded.writable, loaded.folder) == (Outcome.MISSING, True,
                                                                world.folder)
    assert dict(loaded.values) == {}
    assert not world.folder.exists()
    world.check()


def test_ac_f16_06_folder_without_file(world):
    world.folder.mkdir()
    loaded = read_settings(world.folder)
    assert (loaded.outcome, loaded.writable) == (Outcome.MISSING, True)
    assert world.names() == []
    world.check()


def test_ac_f16_06_example(world):
    world.write(EXAMPLE)
    before = world.file.stat()
    loaded = read_settings(world.folder)
    assert (loaded.outcome, loaded.writable) == (Outcome.OK, True)
    assert dict(loaded.values) == EXAMPLE_VALUES
    assert world.file.read_bytes() == EXAMPLE
    assert world.file.stat().st_mtime_ns == before.st_mtime_ns
    assert world.names() == [FILE_NAME]
    world.check()


def test_ac_f16_06_brace_is_quarantined(world):
    world.write(b"{")
    loaded = read_settings(world.folder)
    assert (loaded.outcome, loaded.bad_reason, loaded.writable) == (
        Outcome.BAD, NOT_VALID_JSON, True)
    assert loaded.quarantined
    assert world.bad.read_bytes() == b"{"
    assert world.names() == [BAD_NAME]
    world.check()


def test_ac_f16_06_brace_replaces_an_older_bad_file(world):
    world.write(b"{")
    world.bad.write_bytes(b"older damaged file")
    loaded = read_settings(world.folder)
    assert loaded.outcome is Outcome.BAD and loaded.quarantined
    assert world.bad.read_bytes() == b"{"
    assert world.names() == [BAD_NAME]
    world.check()


def test_ac_f16_06_over_the_cap(world):
    world.write(b" " * (MAX_FILE_BYTES + 1))
    loaded = read_settings(world.folder)
    assert (loaded.outcome, loaded.bad_reason, loaded.writable) == (Outcome.BAD, OVER_CAP,
                                                                    True)
    assert world.names() == [BAD_NAME]
    assert world.bad.stat().st_size == MAX_FILE_BYTES + 1
    world.check()


def test_ac_f16_06_exactly_the_cap(world):
    data = EXAMPLE + b" " * (MAX_FILE_BYTES - len(EXAMPLE))
    world.write(data)
    loaded = read_settings(world.folder)
    assert loaded.outcome is Outcome.OK and dict(loaded.values) == EXAMPLE_VALUES
    assert world.file.read_bytes() == data
    world.check()


def test_ac_f16_06_directory_is_renamed(world):
    world.file.mkdir(parents=True)
    (world.file / "inner.txt").write_bytes(b"x")
    loaded = read_settings(world.folder)
    assert (loaded.outcome, loaded.bad_reason, loaded.writable) == (Outcome.BAD, NOT_REGULAR,
                                                                    True)
    assert loaded.quarantined
    assert world.bad.is_dir() and (world.bad / "inner.txt").read_bytes() == b"x"
    assert not world.file.exists()
    world.check()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX-only")
def test_ac_f16_06_fifo_returns_at_once(world):
    world.folder.mkdir()
    os.mkfifo(world.file)
    start = time.monotonic()
    loaded = read_settings(world.folder)
    assert time.monotonic() - start < 1.0
    assert (loaded.outcome, loaded.bad_reason) == (Outcome.BAD, NOT_REGULAR)
    assert world.names() == [BAD_NAME]
    world.check()


def test_ac_f16_06_symlink_to_outside_is_renamed_not_followed(world):
    world.folder.mkdir()
    symlink(world.file, world.outside / "secret.json")
    loaded = read_settings(world.folder)
    assert (loaded.outcome, loaded.bad_reason) == (Outcome.BAD, NOT_REGULAR)
    assert dict(loaded.values) == {}
    assert world.bad.is_symlink() and not world.file.exists()
    world.check()


def test_ac_f16_06_directory_link_to_outside_is_renamed_not_followed(world):
    world.folder.mkdir()
    link_dir(world.file, world.outside)
    loaded = read_settings(world.folder)
    assert (loaded.outcome, loaded.bad_reason) == (Outcome.BAD, NOT_REGULAR)
    assert loaded.quarantined
    assert not os.path.lexists(world.file) and os.path.lexists(world.bad)
    world.check()


def test_ac_f16_06_eio_on_read_is_unreadable(world, monkeypatch):
    world.write(EXAMPLE)
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "read", fail_on(os.read, 1, errno.EIO))
        loaded = read_settings(world.folder)
    assert (loaded.outcome, loaded.bad_reason, loaded.writable) == (
        Outcome.UNREADABLE, UNREADABLE, False)
    assert dict(loaded.values) == {} and not loaded.quarantined
    assert world.names() == [FILE_NAME] and world.file.read_bytes() == EXAMPLE
    world.check()


def test_ac_f16_06_failed_rename_leaves_the_file_writable(world, monkeypatch):
    world.write(b"{")
    world.bad.write_bytes(b"older")
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "replace", fail_on(os.replace, 1, errno.EACCES))
        loaded = read_settings(world.folder)
    assert (loaded.outcome, loaded.bad_reason, loaded.writable) == (
        Outcome.BAD, NOT_VALID_JSON, True)
    assert not loaded.quarantined
    assert world.file.read_bytes() == b"{"
    world.check()


def test_ac_f16_06_linked_dev_folder_is_never_read(world, monkeypatch):
    real = world.base / "real"
    real.mkdir()
    (real / FILE_NAME).write_bytes(EXAMPLE)
    link_dir(world.folder, real)
    world.entries = world._entries() | {"real", f"real{os.sep}{FILE_NAME}"}
    calls = []
    with monkeypatch.context() as patch:
        for name in ("read_regular", "remove_stale_temps", "quarantine"):
            patch.setattr(safefile, name, lambda *a, _n=name, **k: calls.append(_n))
        loaded = read_settings(world.folder)
    assert (loaded.outcome, loaded.bad_reason, loaded.writable) == (
        Outcome.NO_FILE, FOLDER_IS_LINK, False)
    assert dict(loaded.values) == {} and calls == []
    assert (real / FILE_NAME).read_bytes() == EXAMPLE
    assert os.listdir(real) == [FILE_NAME]
    world.check()


def test_ac_f16_06_stale_temps_removed_notes_kept(world):
    world.folder.mkdir()
    old = time.time() - 3600
    for token in ("0123abcd", "deadbeef", "00000000"):
        temp = world.folder / safefile.temp_name(FILE_NAME, token)
        temp.write_bytes(b"partial")
        os.utime(temp, (old, old))
    (world.folder / "notes.txt").write_bytes(b"keep me")
    loaded = read_settings(world.folder)
    assert loaded.outcome is Outcome.MISSING and loaded.writable
    assert world.names() == ["notes.txt"]
    world.check()


def test_release_folder_under_a_linked_parent_is_used(world):
    real_home = world.base / "real_home"
    (real_home / "vn-engine" / "my-game" / "settings").mkdir(parents=True)
    (real_home / "vn-engine" / "my-game" / "settings" / FILE_NAME).write_bytes(EXAMPLE)
    link_dir(world.base / "home", real_home)
    folder = world.base / "home" / "vn-engine" / "my-game" / "settings"
    assert read_settings(folder, release=True).outcome is Outcome.OK
    assert read_settings(folder, release=False).outcome is Outcome.NO_FILE


def test_no_file_result():
    loaded = LoadedSettings.no_file(settings_file.NO_PERMISSION)
    assert (loaded.outcome, loaded.bad_reason, loaded.writable) == (
        Outcome.NO_FILE, "no permission", False)
    assert dict(loaded.values) == {}

"""Game-folder containment, the contained reader, app ids, per-user folders, display forms.

AC-F01-99 (bad refs rejected without file access), AC-F01-125 (one app-id validator,
always-valid fallback), plus the containment-before-listing walk (SEC-F01-01..03, abuse
A5, A7–A9), ``read_file`` limits, and the ADR-0003 folder rules used by later steps.
"""

import builtins
import contextlib
import io
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

from engine.core import paths
from engine.core.errors import (
    AssetMissing,
    AssetNotFile,
    AssetRefError,
    AssetTooLarge,
    UserFacingError,
)
from engine.core.paths import (
    GamePaths,
    check_ref,
    display_path,
    is_valid_app_id,
    slugify,
    user_data_dir,
    user_log_dir,
)

SLASH_REASON = ("paths must stay inside the game folder and use forward slashes, "
                "e.g. images/bg/club.png")

FILE_SYSTEM_CALLS = [
    (builtins, "open"), (io, "open"), (os, "open"), (Path, "open"), (Path, "read_bytes"),
    (os, "stat"), (os, "lstat"), (os, "scandir"), (os, "listdir"), (Path, "resolve"),
]


@contextlib.contextmanager
def no_file_system_access():
    spy = mock.Mock(side_effect=AssertionError("file-system call"))
    with contextlib.ExitStack() as stack:
        for target, name in FILE_SYSTEM_CALLS:
            stack.enter_context(mock.patch.object(target, name, spy))
        yield spy
    spy.assert_not_called()


@pytest.fixture
def game(tmp_path) -> GamePaths:
    root = tmp_path / "game"
    (root / "images" / "bg").mkdir(parents=True)
    (root / "images" / "bg" / "club.png").write_bytes(b"club")
    (root / "images" / "a.png").write_bytes(b"a")
    (root / "images" / "dir.png").mkdir()
    (root / "config.toml").write_text("[game]\n", encoding="utf-8")
    return GamePaths.for_game(root)


def make_dir_link(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows (no privilege needed), else a symlink."""
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        return
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create directory symlinks here: {exc}")


def make_file_symlink(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create file symlinks here (needs a privilege on Windows): {exc}")


# --- AC-F01-99: syntax rules, no file access ----------------------------------------------

REJECTED = [
    ("", "paths can't be empty"),
    *[(ref, SLASH_REASON) for ref in [
        "../x.png", "images/../../x.png", "images/./a.png", "./a.png", "/etc/passwd",
        "C:x.png", "C:/Windows/win.ini", "\\\\server\\share\\a.png", "images\\bg.png",
        "a//b.png", "images/", "~/a.png", "a.png:stream"]],
    ("images/con.png", '"con" is a reserved file name on Windows'),
    ("images/CON", '"CON" is a reserved file name on Windows'),
    ("CON/x.png", '"CON" is a reserved file name on Windows'),
    ("images/con .png", '"con" is a reserved file name on Windows'),
    ("images/Nul.txt.png", '"Nul" is a reserved file name on Windows'),
    ("AUX/x.png", '"AUX" is a reserved file name on Windows'),
    ("images/AUX", '"AUX" is a reserved file name on Windows'),
    ("images/COM1.png", '"COM1" is a reserved file name on Windows'),
    ("images/COM¹.png", '"COM¹" is a reserved file name on Windows'),
    ("images/LPT0.png", '"LPT0" is a reserved file name on Windows'),
    ("images/CONIN$", '"CONIN$" is a reserved file name on Windows'),
    *[(ref, "file and folder names can't end with a dot or a space") for ref in [
        "images/bg.png.", "images/bg.png ", "images/x./a.png", "images/old /bg.png"]],
    *[(ref, "paths can't contain control characters") for ref in [
        "a.png\x00.txt", "images/a\x01.png", "images/a\tb.png",
        "images/a\n2026-11-01 00:00:00.000 ERROR app forged.png",
        "images/\x1b[31mred.png", "images/a\x7f.png", "../a\tb.png"]],
    ("x" * 1025, "paths can be at most 1,024 characters long"),
    ("images/" + "s" * 256, "each file or folder name can be at most 255 characters long"),
]

ESCAPED = {
    "a.png\x00.txt": "a.png\\x00.txt",
    "images/a\x01.png": "images/a\\x01.png",
    "images/a\tb.png": "images/a\\tb.png",
    "images/a\n2026-11-01 00:00:00.000 ERROR app forged.png":
        "images/a\\n2026-11-01 00:00:00.000 ERROR app forged.png",
    "images/\x1b[31mred.png": "images/\\x1b[31mred.png",
    "images/a\x7f.png": "images/a\\x7f.png",
    "../a\tb.png": "../a\\tb.png",
    "x" * 1025: "x" * 119 + "…",
    "images/" + "s" * 256: ("images/" + "s" * 256)[:119] + "…",
}


@pytest.mark.parametrize("ref, reason", REJECTED)
def test_bad_refs_are_rejected_without_file_access(game, ref, reason):
    shown = ESCAPED.get(ref, ref)
    start = time.perf_counter()
    with no_file_system_access():
        with pytest.raises(AssetRefError) as raised:
            game.resolve(ref)
    assert time.perf_counter() - start < 1.0
    assert str(raised.value) == f'Asset path "{shown}" is not allowed: {reason}'
    assert raised.value.reason == reason
    assert raised.value.ref == ref
    assert "\n" not in str(raised.value)


def test_5_mb_ref_is_rejected_quickly_without_file_access(game):
    ref = "a" * 5_000_000
    start = time.perf_counter()
    with no_file_system_access():
        with pytest.raises(AssetRefError) as raised:
            game.resolve(ref)
    assert time.perf_counter() - start < 1.0
    assert str(raised.value) == ('Asset path "' + "a" * 119 + '…" is not allowed: '
                                 "paths can be at most 1,024 characters long")


def test_check_ref_alone_needs_no_game_folder():
    with no_file_system_access():
        check_ref("images/bg/club.png")
        with pytest.raises(AssetRefError):
            check_ref("../x.png")


def _ref_of_length_1024() -> str:
    ref = "/".join(["s" * 255] * 3 + ["s" * 254, "s"])
    assert len(ref) == 1024
    return ref


LOOKALIKES = [
    _ref_of_length_1024(), "images/console.png", "images/com10.png", "images/lpt.png",
    "images/nul1.png", "images/．．/x.png", "images/%2e%2e/x.png", "..%2fx.png",
    "images∕..∕x.png", "images／x.png",
]


@pytest.mark.parametrize("ref", LOOKALIKES)
def test_lookalikes_pass_the_syntax_check_and_are_missing(game, ref):
    check_ref(ref)
    listed: list[str] = []
    real_scandir = os.scandir

    def scandir_spy(path):
        listed.append(str(path))
        return real_scandir(path)

    with mock.patch.object(os, "scandir", scandir_spy):
        with pytest.raises(AssetMissing):
            game.resolve(ref)
    assert all(Path(p).is_relative_to(game.root) for p in listed)


# --- The walk: case, suggestions, Unicode -------------------------------------------------

def test_resolve_returns_the_real_contained_path(game):
    assert game.resolve("images/bg/club.png") == game.root / "images" / "bg" / "club.png"
    assert game.read_file("images/bg/club.png", max_bytes=100) == b"club"


def test_case_mismatch_is_missing_with_a_corrected_suggestion(game):
    with pytest.raises(AssetMissing) as raised:
        game.resolve("images/BG/Club.png")
    assert raised.value.suggestion == "images/bg/club.png"
    assert str(raised.value) == ("images/BG/Club.png not found — did you mean "
                                 "images/bg/club.png?")


def test_missing_file_gets_a_close_match(game):
    with pytest.raises(AssetMissing) as raised:
        game.resolve("images/bg/clb.png")
    assert raised.value.suggestion == "images/bg/club.png"


def test_missing_file_without_a_close_match(game):
    with pytest.raises(AssetMissing) as raised:
        game.resolve("images/bg/zzzzzzzz.png")
    assert raised.value.suggestion is None
    assert str(raised.value) == "images/bg/zzzzzzzz.png not found"


def test_file_used_as_a_folder_is_missing(game):
    with pytest.raises(AssetMissing):
        game.resolve("images/a.png/x.png")


def test_unicode_folders_and_names(tmp_path):
    root = tmp_path / "My Games" / "José" / "マイゲーム"
    (root / "images" / "背景").mkdir(parents=True)
    (root / "images" / "背景" / "é.png").write_bytes(b"png")
    game = GamePaths.for_game(root)
    assert game.read_file("images/背景/é.png", max_bytes=10) == b"png"


def test_listings_are_cached_until_invalidated(game):
    with pytest.raises(AssetMissing):
        game.resolve("images/new.png")
    (game.root / "images" / "new.png").write_bytes(b"n")
    with pytest.raises(AssetMissing):
        game.resolve("images/new.png")
    game.invalidate_listings()
    assert game.resolve("images/new.png").name == "new.png"


# --- Containment before listing (SEC-F01-01..03; abuse A7–A9) -----------------------------

@pytest.fixture
def outside(tmp_path) -> Path:
    folder = tmp_path / "outside"
    folder.mkdir()
    (folder / "secret.png").write_bytes(b"secret")
    (folder / "taxes_2025.png").write_bytes(b"taxes")
    return folder


def test_directory_link_out_of_the_root_is_rejected_without_listing_it(game, outside):
    make_dir_link(game.root / "images" / "ext", outside)
    listed: list[str] = []
    real_scandir = os.scandir

    def scandir_spy(path):
        listed.append(str(path))
        return real_scandir(path)

    with mock.patch.object(os, "scandir", scandir_spy):
        with pytest.raises(AssetRefError) as raised:
            game.resolve("images/ext/taxes.png")
    assert str(raised.value) == f'Asset path "images/ext/taxes.png" is not allowed: {SLASH_REASON}'
    assert "taxes_2025" not in str(raised.value)
    assert not any(Path(p).resolve().is_relative_to(outside.resolve()) for p in listed)


def test_link_to_a_sibling_folder_with_the_root_name_is_rejected(game, tmp_path):
    evil = tmp_path / "game-evil"
    evil.mkdir()
    (evil / "x.png").write_bytes(b"x")
    make_dir_link(game.root / "images" / "sib", evil)
    with pytest.raises(AssetRefError):
        game.resolve("images/sib/x.png")


def test_file_symlink_out_of_the_root_is_rejected_and_never_read(game, tmp_path):
    secret_dir = tmp_path / "qauser7"
    secret_dir.mkdir()
    (secret_dir / "secret.png").write_bytes(b"secret")
    make_file_symlink(game.root / "images" / "out.png", secret_dir / "secret.png")
    opened = mock.Mock(side_effect=AssertionError("opened"))
    with mock.patch.object(paths, "_open_regular", opened):
        with pytest.raises(AssetRefError) as raised:
            game.read_file("images/out.png", max_bytes=100)
    text = str(raised.value)
    assert text == f'Asset path "images/out.png" is not allowed: {SLASH_REASON}'
    assert "qauser7" not in text and "secret" not in text


def test_link_inside_the_root_resolves_normally(game):
    make_dir_link(game.root / "alias", game.root / "images" / "bg")
    real = game.resolve("alias/club.png")
    assert real.is_relative_to(game.root)
    assert game.read_file("alias/club.png", max_bytes=100) == b"club"


def test_linked_game_root_works(tmp_path, game):
    link = tmp_path / "linked-game"
    make_dir_link(link, game.root)
    linked = GamePaths.for_game(link)
    assert linked.root == game.root
    assert linked.read_file("images/a.png", max_bytes=10) == b"a"


# --- read_file ----------------------------------------------------------------------------

def test_folder_is_not_a_file(game):
    with pytest.raises(AssetNotFile) as raised:
        game.read_file("images/dir.png", max_bytes=100)
    assert str(raised.value) == "images/dir.png is not a file"


def test_too_large_file_is_never_opened(game):
    opened = mock.Mock(side_effect=AssertionError("opened"))
    with mock.patch.object(paths, "_open_regular", opened):
        with pytest.raises(AssetTooLarge):
            game.read_file("images/bg/club.png", max_bytes=3)


def test_read_stops_after_max_bytes_plus_one(game, monkeypatch):
    """Even if the size reported by stat is wrong, at most max_bytes + 1 bytes are read."""
    (game.root / "big.bin").write_bytes(b"x" * 1000)
    real_stat = os.stat
    real_open = paths._open_regular
    read_sizes: list[int] = []

    def small_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if Path(path).name == "big.bin":
            fields = list(result)
            fields[6] = 10                       # st_size
            return os.stat_result(fields)
        return result

    class CountingStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size=-1):
            data = self.stream.read(size)
            read_sizes.append(len(data))
            return data

    monkeypatch.setattr(os, "stat", small_stat)
    monkeypatch.setattr(paths, "_open_regular", lambda p: CountingStream(real_open(p)))
    with pytest.raises(AssetTooLarge):
        game.read_file("big.bin", max_bytes=100)
    assert sum(read_sizes) <= 101


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs exist only on POSIX")
def test_fifo_is_not_a_file_and_is_never_opened(game):
    os.mkfifo(game.root / "pipe.png")
    start = time.perf_counter()
    with pytest.raises(AssetNotFile):
        game.read_file("pipe.png", max_bytes=100)
    assert time.perf_counter() - start < 5


# --- GamePaths.for_game -------------------------------------------------------------------

@pytest.fixture
def fake_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "qauser7"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def test_missing_game_folder_is_shown_under_home(fake_home):
    with pytest.raises(UserFacingError) as raised:
        GamePaths.for_game(fake_home / "Desktop" / "nope")
    assert raised.value.format() == (
        'Can\'t find the game folder "~/Desktop/nope". Check that the folder exists, '
        "or run: python -m engine run <folder>")


def test_file_instead_of_game_folder(fake_home):
    (fake_home / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(UserFacingError) as raised:
        GamePaths.for_game(fake_home / "notes.txt")
    assert raised.value.format() == (
        '"~/notes.txt" is a file, not a folder. Check that the folder exists, '
        "or run: python -m engine run <folder>")


# --- AC-F01-125: app ids ------------------------------------------------------------------

VALID_IDS = ["my-vn", "a", "0", "a-", "con-game", "nul1", "a" * 40]
INVALID_IDS = ["../x", "a/b", "CON", "con", "lpt9", "A", "My-VN", " a", "abc ", "-abc",
               "Paper Lanterns", "", "abc\n", "a" * 41, "ｍｙ-ｖｎ", "my\u2010vn",
               "my-vn\u200b", "٣", 5, True, ["my-vn"], {"a": 1}, "a\\b", "COM1", None]


@pytest.mark.parametrize("value", VALID_IDS)
def test_valid_app_ids(value):
    assert is_valid_app_id(value)


@pytest.mark.parametrize("value", INVALID_IDS)
def test_invalid_app_ids(value):
    assert not is_valid_app_id(value)


@pytest.mark.parametrize("name, slug", [
    ("CON", "con-game"), ("nul", "nul-game"), ("Com1", "com1-game"), ("..", "game"),
    (".", "game"), ("", "game"), ("💀", "game"), ("マイゲーム", "game"),
    ("a" * 200, "a" * 40), ("My Game!", "my-game"), ("My Visual Novel!", "my-visual-novel"),
    ("game", "game"), ("Café Ünïcode", "cafe-unicode"), ("a" * 39 + "-b", "a" * 39)])
def test_slugify(name, slug):
    assert slugify(name) == slug
    assert is_valid_app_id(slug)


@pytest.mark.parametrize("app_id", ["../x", "a/b", "a\\b", "con", "COM1", "A", "", "abc\n",
                                    "-abc", "a" * 41])
@pytest.mark.parametrize("function", [user_data_dir, user_log_dir])
def test_user_dirs_reject_invalid_ids(function, app_id):
    with pytest.raises(ValueError):
        function(app_id)


# --- Per-user folders (ADR-0003 §3, SEC-F01-17) -------------------------------------------

def test_linux_folders(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    default = fake_home / ".local" / "share" / "vn-engine" / "my-vn"
    for value in ("data", ""):
        monkeypatch.setenv("XDG_DATA_HOME", value)
        assert user_data_dir("my-vn") == default
        assert user_log_dir("my-vn") == default / "logs"
    monkeypatch.delenv("XDG_DATA_HOME")
    assert user_data_dir("my-vn") == default
    monkeypatch.setenv("XDG_DATA_HOME", "/srv/data")
    assert user_data_dir("my-vn") == Path("/srv/data") / "vn-engine" / "my-vn"
    assert user_log_dir("my-vn") == Path("/srv/data") / "vn-engine" / "my-vn" / "logs"


def test_macos_folders(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    expected = fake_home / "Library" / "Application Support" / "vn-engine" / "my-vn"
    assert user_data_dir("my-vn") == expected
    assert user_log_dir("my-vn") == expected / "logs"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows paths")
def test_windows_folders(tmp_path, monkeypatch):
    roaming, local = tmp_path / "Roaming", tmp_path / "Local"
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert user_data_dir("my-vn") == roaming / "vn-engine" / "my-vn"
    assert user_log_dir("my-vn") == local / "vn-engine" / "my-vn" / "logs"
    monkeypatch.setenv("LOCALAPPDATA", r"\\srv\share\Local")
    assert str(user_log_dir("my-vn")) == r"\\srv\share\Local\vn-engine\my-vn\logs"


@pytest.mark.parametrize("value", [None, "", "relative\\dir", "\\rooted-no-drive"])
def test_windows_unusable_environment_means_not_writable(value, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.chdir(tmp_path)
    for name in ("APPDATA", "LOCALAPPDATA"):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert user_data_dir("my-vn") is None
    assert user_log_dir("my-vn") is None
    assert list(tmp_path.iterdir()) == []


def test_no_home_means_not_writable(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(paths, "home_dir", lambda: None)
    assert user_data_dir("my-vn") is None
    assert user_log_dir("my-vn") is None


# --- display_path (§7.10.6) ---------------------------------------------------------------

def test_display_game_form(tmp_path):
    root = tmp_path / "game"
    assert display_path(root / "logs" / "latest.log", game_root=root) == "<game>/logs/latest.log"


def test_display_home_form(fake_home):
    assert display_path(fake_home / "Desktop" / "nope", game_root=None) == "~/Desktop/nope"


def test_display_game_beats_home(fake_home):
    root = fake_home / "projects" / "game"
    assert display_path(root / "logs" / "latest.log", game_root=root) == "<game>/logs/latest.log"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows environment forms")
def test_display_localappdata_beats_home(fake_home, monkeypatch):
    local = fake_home / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(fake_home / "AppData" / "Roaming"))
    log = user_log_dir("my-vn") / "latest.log"
    assert display_path(log, game_root=None) == r"%LOCALAPPDATA%\vn-engine\my-vn\logs\latest.log"
    data = user_data_dir("my-vn") / "saves"
    assert display_path(data, game_root=None) == r"%APPDATA%\vn-engine\my-vn\saves"


def test_display_xdg_form(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    xdg = fake_home / "data"
    monkeypatch.setenv("XDG_DATA_HOME", xdg.as_posix() if os.name == "posix" else "/xdg")
    base = xdg if os.name == "posix" else Path("/xdg")
    assert display_path(base / "vn-engine" / "my-vn" / "logs" / "latest.log",
                        game_root=None) == "$XDG_DATA_HOME/vn-engine/my-vn/logs/latest.log"


def test_display_other_paths_are_redacted(fake_home):
    if sys.platform == "win32":
        other = Path(r"Z:\Users\alice\x.log")
        assert display_path(other, game_root=None) == r"Z:\Users\<user>\x.log"
    else:
        other = Path("/home/alice/x.log")
        assert display_path(other, game_root=None) == "/home/<user>/x.log"


def test_home_dir_is_absolute_or_none(monkeypatch):
    home = paths.home_dir()
    assert home is None or home.is_absolute()

    def broken():
        raise RuntimeError("no home")

    monkeypatch.setattr(Path, "home", staticmethod(broken))
    assert paths.home_dir() is None


def test_engine_locations(monkeypatch, tmp_path):
    repo = Path(__file__).resolve().parent.parent.parent
    assert paths.engine_root() == repo
    assert paths.engine_data_dir() == repo / "engine" / "data"
    assert paths.is_frozen() is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.is_frozen() is True
    assert paths.engine_root() == tmp_path


# --- bounded reads never reserve the whole limit -------------------------------------------

def test_read_bounded_asks_only_for_the_stat_size_plus_one():
    import io
    from engine.core.paths import _read_bounded

    class Spy(io.BytesIO):
        def __init__(self, data):
            super().__init__(data)
            self.requests = []

        def read(self, n=-1):
            self.requests.append(n)
            return super().read(n)

    stream = Spy(b"x" * 10)
    assert _read_bounded(stream, 10, 256 * 1024 * 1024 + 1) == b"x" * 10
    assert stream.requests == [11]
    grown = Spy(b"y" * 3_000_000)                    # grew after stat reported 10 bytes
    data = _read_bounded(grown, 10, 2_000_001)
    assert len(data) == 2_000_001
    assert max(grown.requests) <= 1 << 20


# --- the cached root comparison is the same as Path.is_relative_to ---------------------------

def test_contains_matches_is_relative_to(tmp_path):
    root = tmp_path / "Game"
    (root / "images").mkdir(parents=True)
    paths = GamePaths.for_game(root)
    candidates = [paths.root, paths.root / "images", paths.root / "images" / "a.png",
                  paths.root.parent, paths.root.parent / "Game-evil" / "x.png",
                  paths.root.parent / "Gam", paths.root.parent / "Game2",
                  Path(str(paths.root).upper()) / "x.png", Path(paths.root.anchor)]
    for candidate in candidates:
        assert paths.contains(candidate) == candidate.is_relative_to(paths.root), candidate


def test_repeated_misses_reuse_the_suggestion(tmp_path, monkeypatch):
    root = tmp_path / "game"
    (root / "images").mkdir(parents=True)
    (root / "images" / "club.png").write_bytes(b"x")
    game_paths = GamePaths.for_game(root)
    calls = []
    real = paths.difflib.get_close_matches
    monkeypatch.setattr(paths.difflib, "get_close_matches",
                        lambda *a, **k: calls.append(a) or real(*a, **k))
    for _ in range(3):
        with pytest.raises(AssetMissing) as info:
            game_paths.resolve("images/clob.png")
        assert info.value.suggestion == "images/club.png"
    assert len(calls) == 1

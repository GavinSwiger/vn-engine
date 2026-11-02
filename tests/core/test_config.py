"""Loading config.toml: defaults, accepted values, file-level errors, parser hardening.

AC-F01-09, 10, 16, 123, 133; the unit parts of AC-F01-12, 13, 14, 132, 134 (their
error-screen parts need Step 8).
"""

import logging
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

from engine.core import paths
from engine.core.config import load_config
from engine.core.config_schema import (
    Config,
    EngineConfig,
    GameConfig,
    WindowConfig,
)
from engine.core.constants import CONFIG_MAX_BYTES, MB
from engine.core.errors import ConfigError
from tests.core.conftest import fixture_bytes, value_bytes
from tests.fixtures.F01 import config_fixtures as cf

ID_PHRASE = ('1 to 40 characters, each a lower-case letter a-z, a digit 0-9, or "-", '
             'starting with a letter or digit, and not a reserved name such as "con"')
NOT_UTF8 = "config.toml is not saved as UTF-8 text. Save it as UTF-8 in your editor."


def only_error(result) -> ConfigError:
    assert len(result.errors) == 1, [e.format() for e in result.errors]
    return result.errors[0]


# --- AC-F01-09: missing or empty config ---------------------------------------------------

def test_missing_config_gives_defaults_and_one_warning(make_game):
    result = load_config(make_game(None))
    assert result.errors == []
    assert result.warnings == ["config.toml not found — using default settings"]
    assert result.loaded is False
    assert_defaults(result.config)


def test_empty_config_gives_defaults_and_no_warning(load):
    result = load(b"")
    assert result.errors == [] and result.warnings == []
    assert result.loaded is True
    assert_defaults(result.config)


def assert_defaults(config: Config) -> None:
    game, window, engine = config.game, config.window, config.engine
    assert (game.title, game.version, game.id) == ("Untitled Visual Novel", "0.0.0", None)
    assert (window.width, window.height) == (1280, 720)
    assert window.fullscreen is False and window.resizable is True
    assert window.icon is None
    assert window.letterbox_color == (0, 0, 0)
    assert window.scale_filter == "smooth"
    assert window.integer_scale is False
    assert (engine.fps, engine.cache_mb, engine.log_level) == (60, 512, "info")
    assert config == Config(GameConfig(), WindowConfig(), EngineConfig())


def test_wrongly_cased_config_name_is_missing_with_a_suggestion(make_game):
    game = make_game(None)
    (game.root / "Config.toml").write_text('[game]\ntitle = "x"\n', encoding="utf-8")
    result = load_config(game)
    assert result.errors == []
    assert result.warnings == [
        "config.toml not found — did you mean Config.toml? Using default settings"]
    assert result.config.game.title == "Untitled Visual Novel"


# --- AC-F01-10: every allowed value is accepted -------------------------------------------

ACCEPTED = [
    ("ok_width_640.toml", "window", "width", 640),
    ("ok_width_7680.toml", "window", "width", 7680),
    ("ok_height_360.toml", "window", "height", 360),
    ("ok_height_4320.toml", "window", "height", 4320),
    ("ok_fps_30.toml", "engine", "fps", 30),
    ("ok_fps_240.toml", "engine", "fps", 240),
    ("ok_cache_mb_64.toml", "engine", "cache_mb", 64),
    ("ok_cache_mb_8192.toml", "engine", "cache_mb", 8192),
    ("ok_fullscreen_true.toml", "window", "fullscreen", True),
    ("ok_fullscreen_false.toml", "window", "fullscreen", False),
    ("ok_resizable_true.toml", "window", "resizable", True),
    ("ok_resizable_false.toml", "window", "resizable", False),
    ("ok_integer_scale_true.toml", "window", "integer_scale", True),
    ("ok_integer_scale_false.toml", "window", "integer_scale", False),
    ("ok_letterbox_color.toml", "window", "letterbox_color", (26, 43, 60)),
    ("ok_scale_filter_smooth.toml", "window", "scale_filter", "smooth"),
    ("ok_scale_filter_pixel.toml", "window", "scale_filter", "pixel"),
    ("ok_log_level_debug.toml", "engine", "log_level", "debug"),
    ("ok_log_level_info.toml", "engine", "log_level", "info"),
    ("ok_log_level_warning.toml", "engine", "log_level", "warning"),
    ("ok_log_level_error.toml", "engine", "log_level", "error"),
    ("ok_title_cjk.toml", "game", "title", "文芸部"),
    ("ok_version_empty.toml", "game", "version", ""),
    ("ok_version_beta.toml", "game", "version", "1.0-beta+3"),
    ("ok_icon.toml", "window", "icon", "gui/lantern.png"),
    ("ok_id_my_vn.toml", "game", "id", "my-vn"),
    ("ok_id_a.toml", "game", "id", "a"),
    ("ok_id_0.toml", "game", "id", "0"),
    ("ok_id_a_dash.toml", "game", "id", "a-"),
    ("ok_id_con_game.toml", "game", "id", "con-game"),
    ("ok_id_nul1.toml", "game", "id", "nul1"),
    ("ok_id_40.toml", "game", "id", "a" * 40),
]


@pytest.mark.parametrize("name, section, key, expected", ACCEPTED)
def test_allowed_values_are_applied(load, name, section, key, expected):
    result = load(value_bytes(name))
    assert result.errors == [] and result.warnings == []
    assert result.loaded is True
    assert getattr(getattr(result.config, section), key) == expected


def test_full_valid_config_loads_every_key(load):
    result = load(
        '[game]\ntitle = "Paper Lanterns"\nversion = "0.1.0"\nid = "paper-lanterns"\n'
        '[window]\nwidth = 1920\nheight = 1080\nfullscreen = true\nresizable = false\n'
        'icon = "gui/lantern.png"\nletterbox_color = "#123456"\nscale_filter = "pixel"\n'
        'integer_scale = true\n[engine]\nfps = 144\ncache_mb = 1024\nlog_level = "debug"\n')
    assert result.errors == [] and result.warnings == [] and result.loaded
    assert result.config == Config(
        GameConfig("Paper Lanterns", "0.1.0", "paper-lanterns"),
        WindowConfig(1920, 1080, True, False, "gui/lantern.png", (0x12, 0x34, 0x56),
                     "pixel", True),
        EngineConfig(144, 1024, "debug"))


# --- AC-F01-123: invalid [game] id ---------------------------------------------------------

INVALID_IDS = [
    ("id_dotdot.toml", 'the text "../x"'),
    ("id_slash.toml", 'the text "a/b"'),
    ("id_con_upper.toml", 'the text "CON"'),
    ("id_con.toml", 'the text "con"'),
    ("id_lpt9.toml", 'the text "lpt9"'),
    ("id_upper_a.toml", 'the text "A"'),
    ("id_mixed_case.toml", 'the text "My-VN"'),
    ("id_leading_space.toml", 'the text " a"'),
    ("id_trailing_space.toml", 'the text "abc "'),
    ("id_leading_dash.toml", 'the text "-abc"'),
    ("id_title.toml", 'the text "Paper Lanterns"'),
    ("id_empty.toml", 'the text ""'),
    ("id_newline.toml", 'the text "abc\\n"'),
    ("id_41.toml", 'the text "' + "a" * 39 + '…"'),
    ("id_fullwidth.toml", 'the text "ｍｙ-ｖｎ"'),
    ("id_unicode_hyphen.toml", 'the text "my‐vn"'),
    ("id_zero_width.toml", 'the text "my-vn​"'),
    ("id_arabic_digit.toml", 'the text "٣"'),
    ("id_int.toml", "5"),
    ("id_bool.toml", "true"),
    ("id_list.toml", "a list"),
    ("id_table.toml", "a section"),
]


@pytest.mark.parametrize("name, description", INVALID_IDS)
def test_invalid_game_id_is_a_config_error(load, name, description):
    result = load(value_bytes(name))
    error = only_error(result)
    text = error.format()
    assert text == f"config.toml, line 2: [game] id must be {ID_PHRASE}, but found {description}"
    assert "Remove the quotes." not in text
    assert "\n" not in text
    assert result.config.game.id is None
    assert result.loaded is False


# --- AC-F01-13 (unit), AC-F01-12/14 (unit): all errors, valid parts kept ------------------

def test_all_errors_are_reported_in_line_order(load):
    result = load(fixture_bytes("type_errors.toml"))
    assert [e.line for e in result.errors] == [5, 6, 7, 8, 10]
    assert [e.format() for e in result.errors] == [
        'config.toml, line 5: [window] width must be a whole number from 640 to 7680, '
        'but found the text "big"',
        "config.toml, line 6: [window] height must be a whole number from 360 to 4320, "
        "but found true",
        'config.toml, line 7: [window] fullscreen must be true or false, but found the '
        'text "true". Remove the quotes.',
        'config.toml, line 8: [window] letterbox_color must be a color written as '
        '"#RRGGBB", for example "#000000", but found the text "red"',
        "config.toml, line 10: [engine] fps must be a whole number from 30 to 240, "
        "but found 300",
    ]
    assert all("\n" not in e.format() for e in result.errors)
    assert result.config.game.title == "Paper Lanterns"


def test_valid_part_of_a_broken_config_is_kept(load):
    result = load(fixture_bytes("walkthrough_step3.toml"))
    assert only_error(result).format() == (
        "config.toml, line 8: [window] width must be a whole number from 640 to 7680, "
        'but found the text "1920". Remove the quotes.')
    assert result.loaded is False
    config = result.config
    assert (config.game.title, config.game.version) == ("Paper Lanterns", "0.1.0")
    assert config.window.fullscreen is True
    assert config.window.icon == "gui/lantern.png"
    assert config.window.width == 1280                  # the invalid value's default


# --- AC-F01-16: encoding ------------------------------------------------------------------

def test_utf8_bom_is_accepted(load):
    result = load(fixture_bytes("bom.toml"))
    assert result.errors == [] and result.config.game.title == "BOM Game"


@pytest.mark.parametrize("name", ["latin1.toml", "utf16.toml"])
def test_non_utf8_file_is_one_error(load, name):
    error = only_error(load(fixture_bytes(name)))
    assert error.file == "config.toml"
    assert error.line is None
    assert error.format() == NOT_UTF8                   # the file is named once (I-2)


# --- AC-F01-132 (unit): read only inside the game folder ----------------------------------

OUTSIDE = ("config.toml points to a place outside the game folder, which is not allowed. "
           "Replace it with a normal file.")
NOT_A_FILE = "config.toml is not a normal file. Replace it with a text file."


def _spy_opens(monkeypatch) -> list[Path]:
    opened: list[Path] = []
    real_open = paths._open_regular

    def spy(path):
        opened.append(Path(path))
        return real_open(path)

    monkeypatch.setattr(paths, "_open_regular", spy)
    return opened


def test_config_symlink_out_of_the_folder_is_never_read(make_game, tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "config.toml").write_text('[game]\ntitle = "Leaked"\n', encoding="utf-8")
    game = make_game(None)
    try:
        os.symlink(outside / "config.toml", game.root / "config.toml")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create file symlinks here: {exc}")
    opened = _spy_opens(monkeypatch)
    result = load_config(game)
    assert only_error(result).format() == OUTSIDE
    assert result.config.game.title != "Leaked"
    assert opened == []


def test_config_link_to_an_outside_folder_is_rejected(make_game, tmp_path, monkeypatch):
    outside = tmp_path / "outside-dir"
    outside.mkdir()
    game = make_game(None)
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(outside), str(game.root / "config.toml"))
    else:
        os.symlink(outside, game.root / "config.toml", target_is_directory=True)
    opened = _spy_opens(monkeypatch)
    result = load_config(game)
    error = only_error(result)
    assert error.format() == OUTSIDE
    assert str(tmp_path) not in error.format()
    assert opened == []


def test_config_folder_is_not_a_file(make_game):
    game = make_game(None)
    (game.root / "config.toml").mkdir()
    assert only_error(load_config(game)).format() == NOT_A_FILE


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs exist only on POSIX")
def test_config_fifo_is_never_opened(make_game, monkeypatch):
    game = make_game(None)
    os.mkfifo(game.root / "config.toml")
    opened = _spy_opens(monkeypatch)
    start = time.perf_counter()
    assert only_error(load_config(game)).format() == NOT_A_FILE
    assert time.perf_counter() - start < 5
    assert opened == []


def test_unreadable_config(make_game, monkeypatch):
    game = make_game('[game]\ntitle = "x"\n')

    def refuse(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(paths, "_open_regular", refuse)
    error = only_error(load_config(game))
    assert error.format() == ("config.toml could not be read. Check that it is not open in "
                              "another program and that you may read it.")
    assert "Permission denied" not in error.format()


# --- AC-F01-133: size limit ----------------------------------------------------------------

TOO_LARGE = "config.toml is larger than 1 MB. Check that you opened the right file."


def _count_reads(monkeypatch) -> list[int]:
    sizes: list[int] = []
    real_open = paths._open_regular

    class Counting:
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
            sizes.append(len(data))
            return data

    monkeypatch.setattr(paths, "_open_regular", lambda path: Counting(real_open(path)))
    return sizes


def test_config_over_1_mb_is_an_error_and_is_not_read_past_the_limit(load, monkeypatch):
    sizes = _count_reads(monkeypatch)
    error = only_error(load(cf.generated_huge(2 * MB)))
    assert error.format() == TOO_LARGE
    assert sum(sizes) <= CONFIG_MAX_BYTES + 1


def test_config_of_exactly_1_mb_loads(load, monkeypatch):
    sizes = _count_reads(monkeypatch)
    result = load(cf.generated_huge(1_048_576))
    assert result.errors == [] and result.loaded
    assert sum(sizes) <= CONFIG_MAX_BYTES + 1


def test_config_one_byte_over_1_mb_is_an_error(load):
    assert only_error(load(cf.generated_huge(1_048_577))).format() == TOO_LARGE


def test_size_limit_holds_when_the_reported_size_is_wrong(make_game, monkeypatch):
    """If the file grows after stat, the read still stops at 1 MiB + 1 byte."""
    game = make_game(cf.generated_huge(2 * MB))
    real_stat = os.stat

    def shrunk_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if Path(path).name == "config.toml":
            fields = list(result)
            fields[6] = 100
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(os, "stat", shrunk_stat)
    sizes = _count_reads(monkeypatch)
    assert only_error(load_config(game)).format() == TOO_LARGE
    assert sum(sizes) <= CONFIG_MAX_BYTES + 1


# --- AC-F01-134 (unit): parser failures become config errors ------------------------------

TOO_DEEP = 'config.toml is nested too deeply (too many "[" or "{" inside each other)'
VALUE_TOO_LARGE = ("config.toml contains a value that is too large to read, such as a "
                   "number with thousands of digits")


@pytest.mark.parametrize("data, expected", [
    (cf.generated_deep_arrays(), TOO_DEEP),
    (cf.generated_deep_tables(), TOO_DEEP),
    (cf.generated_bigint(), VALUE_TOO_LARGE),
    (fixture_bytes("nul_in_string.toml"),
     "config.toml, line 2, column 11: this text contains a character that is not "
     "allowed (U+0000)"),
    (fixture_bytes("utf16.toml"), NOT_UTF8),
])
def test_parser_failures_become_one_config_error(load, data, expected, capsys, caplog):
    start = time.perf_counter()
    with caplog.at_level(logging.INFO, logger="vn"):
        result = load(data)
    assert time.perf_counter() - start < 2.0
    assert only_error(result).format() == expected
    assert result.loaded is False
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err and "Traceback" not in captured.out
    assert caplog.records == []                         # nothing above DEBUG


@pytest.mark.parametrize("data", [cf.generated_deep_arrays(), cf.generated_bigint()])
def test_parser_traceback_goes_to_debug_only(load, data, caplog):
    with caplog.at_level(logging.DEBUG, logger="vn"):
        load(data)
    assert [r.levelno for r in caplog.records] == [logging.DEBUG]
    assert caplog.records[0].exc_info is not None


def test_memory_error_becomes_a_config_error(load):
    with mock.patch("tomllib.loads", side_effect=MemoryError):
        error = only_error(load('[game]\ntitle = "x"\n'))
    assert error.format() == "config.toml is too large or complex to read"

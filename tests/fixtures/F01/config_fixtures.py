"""The F01 config fixtures (06-acceptance.md §5.2–5.4), defined in one place.

Small fixtures are committed under ``tests/fixtures/F01/config/``; run this file to
regenerate them (``python tests/fixtures/F01/config_fixtures.py``).
``tests/core/test_config_fixtures.py`` checks that the committed files match these
definitions byte for byte. Fixtures the QA table marks "Generated" are large, so tests build
them in ``tmp_path`` with the ``generated_*`` functions instead of committing them.
"""

from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent / "config"
VALUES_DIR = CONFIG_DIR / "values"

FILES: dict[str, bytes] = {
    # §5.2 valid and warning cases
    "walkthrough_step2.toml": (
        b'[game]\ntitle = "Paper Lanterns"\nversion = "0.1.0"\n\n'
        b'[window]\nfulscreen = true\nicon = "gui/lantern.png"\n'),
    "walkthrough_step3.toml": (
        b'[game]\ntitle = "Paper Lanterns"\nversion = "0.1.0"\n\n'
        b'[window]\nfullscreen = true\nicon = "gui/lantern.png"\nwidth = "1920"\n'),
    "type_errors.toml": (
        b'[game]\ntitle = "Paper Lanterns"\nversion = "0.1.0"\n[window]\nwidth = "big"\n'
        b'height = true\nfullscreen = "true"\nletterbox_color = "red"\n[engine]\nfps = 300\n'),
    "unknown_section.toml": b"[windw]\nwidth = 1280\n",
    "unknown_key_nomatch.toml": b"[engine]\nzzzz = 1\n",
    "toplevel_key.toml": b'title = "x"\n',
    "bom.toml": b'\xef\xbb\xbf[game]\ntitle = "BOM Game"\n',
    "latin1.toml": b'[game]\ntitle = "Caf\xe9"\n',
    "utf16.toml": b"\xff\xfe" + '[game]\ntitle = "x"\n'.encode("utf-16-le"),
    "long_title.toml": ('[game]\ntitle = "' + ("Long title " * 46)[:500] + '"\n').encode(),
    "long_word_title.toml": ('[game]\ntitle = "' + "W" * 200 + '"\n').encode(),
    "long_version.toml": ('[game]\nversion = "' + "9" * 200 + '"\n').encode(),
    "emoji_rtl_title.toml": '[game]\ntitle = "📖 مرحبا 文芸部"\n'.encode(),
    "forged_title.toml": (
        b'[game]\ntitle = "Paper\\n2026-11-01 00:00:00.000 ERROR   app     forged"\n'),
    "bidi_title.toml": b'[game]\ntitle = "abc\\u202Edef"\n',
    "dev_key.toml": b"[engine]\ndev = true\n",
    # §5.3 line-number fixtures
    "dotted_key.toml": b"# comment\nwindow.width = 5\n",
    "inline_table.toml": b'# settings\nwindow = { width = 5 }\n[game]\ntitle = "x"\n',
    "multiline_then_key.toml": (
        b'[game]\ntitle = """Paper\n[window]\nLanterns"""\n[window]\nwidth = 5\n'),
    "array_of_tables.toml": b'[window]\nwidth = 1280\n\n[[window.extra]]\nname = "x"\n',
    # §5.4 syntax and parser fixtures
    "syntax_invalid_value.toml": b'# comment\n[game]\nversion = "0.1.0"\ntitle = My Game\n',
    "crlf_invalid_value.toml": (
        b'# comment\r\n[game]\r\nversion = "0.1.0"\r\ntitle = My Game\r\n'),
    "syntax_missing_equals.toml": b'[game]\ntitle "x"\n',
    "syntax_unclosed_array.toml": b'[game]\ntitle = ["a", "b"\nversion = "1"\n',
    "syntax_duplicate_key.toml": b"[window]\nwidth = 1280\nwidth = 1920\n",
    "syntax_duplicate_table.toml": b"[window]\nwidth = 1280\n[window]\n",
    "syntax_unterminated_string.toml": b'[game]\ntitle = "Paper Lanterns\nversion = "0.1.0"\n',
    "syntax_invalid_statement.toml": b'[game]\n!title = "x"\n',
    "syntax_other.toml": b"[game\n",
    "syntax_eof.toml": b"[game]\ntitle =",
    "nul_in_string.toml": b'[game]\ntitle = "a\x00b"\n',
}

# values/*.toml: the section header on line 1 and one key on line 2
# (AC-F01-10, 11, 123, 135). Name → (section, line 2 as written in TOML).
VALUE_LINES: dict[str, tuple[str, str]] = {
    # AC-F01-10: accepted values
    "ok_width_640.toml": ("window", "width = 640"),
    "ok_width_7680.toml": ("window", "width = 7680"),
    "ok_height_360.toml": ("window", "height = 360"),
    "ok_height_4320.toml": ("window", "height = 4320"),
    "ok_fps_30.toml": ("engine", "fps = 30"),
    "ok_fps_240.toml": ("engine", "fps = 240"),
    "ok_cache_mb_64.toml": ("engine", "cache_mb = 64"),
    "ok_cache_mb_8192.toml": ("engine", "cache_mb = 8192"),
    "ok_fullscreen_true.toml": ("window", "fullscreen = true"),
    "ok_fullscreen_false.toml": ("window", "fullscreen = false"),
    "ok_resizable_true.toml": ("window", "resizable = true"),
    "ok_resizable_false.toml": ("window", "resizable = false"),
    "ok_integer_scale_true.toml": ("window", "integer_scale = true"),
    "ok_integer_scale_false.toml": ("window", "integer_scale = false"),
    "ok_letterbox_color.toml": ("window", 'letterbox_color = "#1a2B3c"'),
    "ok_scale_filter_smooth.toml": ("window", 'scale_filter = "smooth"'),
    "ok_scale_filter_pixel.toml": ("window", 'scale_filter = "pixel"'),
    "ok_log_level_debug.toml": ("engine", 'log_level = "debug"'),
    "ok_log_level_info.toml": ("engine", 'log_level = "info"'),
    "ok_log_level_warning.toml": ("engine", 'log_level = "warning"'),
    "ok_log_level_error.toml": ("engine", 'log_level = "error"'),
    "ok_title_cjk.toml": ("game", 'title = "文芸部"'),
    "ok_version_empty.toml": ("game", 'version = ""'),
    "ok_version_beta.toml": ("game", 'version = "1.0-beta+3"'),
    "ok_icon.toml": ("window", 'icon = "gui/lantern.png"'),
    "ok_id_my_vn.toml": ("game", 'id = "my-vn"'),
    "ok_id_a.toml": ("game", 'id = "a"'),
    "ok_id_0.toml": ("game", 'id = "0"'),
    "ok_id_a_dash.toml": ("game", 'id = "a-"'),
    "ok_id_con_game.toml": ("game", 'id = "con-game"'),
    "ok_id_nul1.toml": ("game", 'id = "nul1"'),
    "ok_id_40.toml": ("game", 'id = "' + "a" * 40 + '"'),
    # AC-F01-11: wrong type or out of range
    "bad_width_text.toml": ("window", 'width = "big"'),
    "bad_width_quoted_number.toml": ("window", 'width = "1920"'),
    "bad_width_bool.toml": ("window", "width = true"),
    "bad_width_float.toml": ("window", "width = 1280.0"),
    "bad_width_639.toml": ("window", "width = 639"),
    "bad_width_7681.toml": ("window", "width = 7681"),
    "bad_height_359.toml": ("window", "height = 359"),
    "bad_height_4321.toml": ("window", "height = 4321"),
    "bad_fps_29.toml": ("engine", "fps = 29"),
    "bad_fps_241.toml": ("engine", "fps = 241"),
    "bad_fps_quoted.toml": ("engine", 'fps = "60"'),
    "bad_cache_mb_63.toml": ("engine", "cache_mb = 63"),
    "bad_cache_mb_8193.toml": ("engine", "cache_mb = 8193"),
    "bad_width_list.toml": ("window", "width = [1]"),
    "bad_width_table.toml": ("window", "width = { a = 1 }"),
    "bad_width_date.toml": ("window", "width = 1979-05-27"),
    "bad_fullscreen_quoted.toml": ("window", 'fullscreen = "true"'),
    "bad_fullscreen_yes.toml": ("window", 'fullscreen = "yes"'),
    "bad_fullscreen_1.toml": ("window", "fullscreen = 1"),
    "bad_letterbox_red.toml": ("window", 'letterbox_color = "red"'),
    "bad_letterbox_short.toml": ("window", 'letterbox_color = "#12345"'),
    "bad_letterbox_nonhex.toml": ("window", 'letterbox_color = "#GGGGGG"'),
    "bad_scale_filter.toml": ("window", 'scale_filter = "nearest"'),
    "bad_log_level_verbose.toml": ("engine", 'log_level = "verbose"'),
    "bad_log_level_upper.toml": ("engine", 'log_level = "INFO"'),
    "bad_title_empty.toml": ("game", 'title = ""'),
    "bad_title_blank.toml": ("game", 'title = "   "'),
    "bad_title_int.toml": ("game", "title = 5"),
    "bad_version_float.toml": ("game", "version = 1.0"),
    "bad_icon_int.toml": ("window", "icon = 5"),
    "bad_icon_bool.toml": ("window", "icon = true"),
    "bad_scale_filter_long.toml": ("window", 'scale_filter = "' + "x" * 50 + '"'),
    "bad_width_quoted_key.toml": ("window", '"width" = "big"'),
    # AC-F01-123: invalid [game] id
    "id_dotdot.toml": ("game", 'id = "../x"'),
    "id_slash.toml": ("game", 'id = "a/b"'),
    "id_con_upper.toml": ("game", 'id = "CON"'),
    "id_con.toml": ("game", 'id = "con"'),
    "id_lpt9.toml": ("game", 'id = "lpt9"'),
    "id_upper_a.toml": ("game", 'id = "A"'),
    "id_mixed_case.toml": ("game", 'id = "My-VN"'),
    "id_leading_space.toml": ("game", 'id = " a"'),
    "id_trailing_space.toml": ("game", 'id = "abc "'),
    "id_leading_dash.toml": ("game", 'id = "-abc"'),
    "id_title.toml": ("game", 'id = "Paper Lanterns"'),
    "id_empty.toml": ("game", 'id = ""'),
    "id_newline.toml": ("game", 'id = "abc\\n"'),
    "id_41.toml": ("game", 'id = "' + "a" * 41 + '"'),
    "id_fullwidth.toml": ("game", 'id = "ｍｙ-ｖｎ"'),
    "id_unicode_hyphen.toml": ("game", 'id = "my‐vn"'),
    "id_zero_width.toml": ("game", 'id = "my-vn​"'),
    "id_arabic_digit.toml": ("game", 'id = "٣"'),
    "id_int.toml": ("game", "id = 5"),
    "id_bool.toml": ("game", "id = true"),
    "id_list.toml": ("game", 'id = ["my-vn"]'),
    "id_table.toml": ("game", "id = { a = 1 }"),
    # AC-F01-135: short messages and safe hints
    "long_quoted_number.toml": ("window", 'width = "' + "9" * 5000 + '"'),
    "long_number.toml": ("window", "width = " + "9" * 4000),
    "fps_inf.toml": ("engine", "fps = inf"),
    "fps_nan.toml": ("engine", "fps = nan"),
    "fps_1e400.toml": ("engine", "fps = 1e400"),
    "width_minus_zero.toml": ("window", "width = -0"),
    "width_quoted_20.toml": ("window", 'width = "00000000000000001920"'),
    "width_quoted_21.toml": ("window", 'width = "000000000000000001920"'),
    "width_quoted_out_of_range.toml": ("window", 'width = "99999"'),
}


def value_file(name: str) -> bytes:
    section, line = VALUE_LINES[name]
    return f"[{section}]\n{line}\n".encode("utf-8")


# --- Generated fixtures (built by tests in tmp_path) --------------------------------------

def generated_many_unknown_keys() -> bytes:
    """``[game]`` then 60,000 lines ``k00001 = 1`` … ``k60000 = 1`` (under 1 MiB)."""
    return ("[game]\n" + "".join(f"k{n:05d} = 1\n" for n in range(1, 60_001))).encode()


def generated_long_unknown_key() -> bytes:
    return ("[game]\n" + "k" * 100_000 + " = 1\n").encode()


def generated_longline_multistring() -> bytes:
    return ('[game]\nnote = """[' + " " * 100_000 + '\n"""\n[engine]\nzzzz = 1\n').encode()


def generated_deep_arrays() -> bytes:
    return ("[game]\ntitle = " + "[" * 10_000 + "]" * 10_000 + "\n").encode()


def generated_deep_tables() -> bytes:
    return ("[game]\nx = " + "{a = " * 2_000 + "1" + "}" * 2_000 + "\n").encode()


def generated_bigint() -> bytes:
    return ("[window]\nwidth = " + "9" * 5_000 + "\n").encode()


def generated_huge(size: int) -> bytes:
    """Valid TOML (``[game]`` then ``# `` comment lines) of exactly ``size`` bytes."""
    head = b"[game]\n"
    line = b"# " + b"x" * 97 + b"\n"              # 100 bytes
    body_size = size - len(head)
    full, rest = divmod(body_size, len(line))
    tail = b"" if rest == 0 else (b"#" + b"x" * (rest - 2) + b"\n" if rest >= 2 else b"\n")
    data = head + line * full + tail
    assert len(data) == size, (len(data), size)
    return data


def write_all() -> None:
    """Write every committed fixture file."""
    VALUES_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in FILES.items():
        (CONFIG_DIR / name).write_bytes(data)
    for name in VALUE_LINES:
        (VALUES_DIR / name).write_bytes(value_file(name))


if __name__ == "__main__":
    write_all()

"""Redaction, escaping, truncation, and echo (SEC-F01-09, 10, 11).

AC-F01-149 (every path form, no OS call), plus the escape table and the
redact-before-truncate rule.
"""

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

from engine.core import redact as redact_module
from engine.core.redact import (
    Redactor,
    RedactRoot,
    echo,
    escape_controls,
    install,
    redact,
    truncate,
)

NO_ROOTS = Redactor((), home_name=None, case_insensitive=True)
TEMP_ROOT = Redactor([RedactRoot("<temp>", r"C:\Users\ALICEB~1\AppData\Local\Temp")],
                     home_name=None, case_insensitive=True)
QA_ROOTS = Redactor([RedactRoot("~", r"C:\Users\qa"),
                     RedactRoot("%LOCALAPPDATA%", r"C:\Users\qa\AppData\Local")],
                    home_name=None, case_insensitive=True)
SHORT_HOME = Redactor([RedactRoot("~", r"C:\Users\Al")], home_name=None,
                      case_insensitive=True)
HOME_NAME = Redactor((), home_name="zzhome", case_insensitive=False)

# AC-F01-149 table: (redactor, input, expected output)
CASES = [
    (NO_ROOTS, r"C:\Users\ALICEB~1\AppData\Local\Temp\x.tmp",
     r"C:\Users\<user>\AppData\Local\Temp\x.tmp"),
    (NO_ROOTS, r"C:\\Users\\ALICEB~1\\x", r"C:\\Users\\<user>\\x"),
    (NO_ROOTS, r"\\?\C:\Users\Alice Bobson\x", r"\\?\C:\Users\<user>\x"),
    (NO_ROOTS, "/home/alice/x", "/home/<user>/x"),
    (NO_ROOTS, "/Users/alice/x", "/Users/<user>/x"),
    (NO_ROOTS, r"C:\Users\Public\x", r"C:\Users\Public\x"),
    (NO_ROOTS, r"C:\Users\Default\x", r"C:\Users\Default\x"),
    (TEMP_ROOT, r"C:\Users\ALICEB~1\AppData\Local\Temp\x.tmp", r"<temp>\x.tmp"),
    (QA_ROOTS, r"C:\Users\qa\AppData\Local\vn-engine\x", r"%LOCALAPPDATA%\vn-engine\x"),
    (QA_ROOTS, "C:/Users/qa/x", "~/x"),
    (QA_ROOTS, r"C:\\Users\\qa\\x", r"~\\x"),
    (QA_ROOTS, r"\\?\C:\Users\qa\x", r"~\x"),
    (QA_ROOTS, r"c:\users\QA\x", r"~\x"),
    (HOME_NAME, "/data/zzhome/venv/x", "/data/<user>/venv/x"),
]


@pytest.mark.parametrize("redactor, text, expected", CASES)
def test_redactor_forms(redactor, text, expected):
    assert redactor(text) == expected


def test_root_never_matches_inside_a_longer_segment():
    out = SHORT_HOME(r"C:\Users\Alice\x")
    assert "~ice" not in out
    assert "Alice" not in out          # the profile-segment rule still applies


def test_redactor_makes_no_os_call(monkeypatch):
    """AC-F01-149: string-only; runs with ctypes unavailable and no file-system call."""
    monkeypatch.setitem(sys.modules, "ctypes", None)
    forbidden = mock.Mock(side_effect=AssertionError("OS call during redaction"))
    with mock.patch.object(os, "stat", forbidden), \
            mock.patch.object(os, "lstat", forbidden), \
            mock.patch.object(os, "scandir", forbidden), \
            mock.patch.object(os, "listdir", forbidden), \
            mock.patch.object(Path, "home", forbidden), \
            mock.patch.object(Path, "resolve", forbidden), \
            mock.patch.object(type(os.environ), "get", forbidden):
        for redactor, text, expected in CASES:
            assert redactor(text) == expected
        SHORT_HOME(r"C:\Users\Alice\x")
    forbidden.assert_not_called()


def test_longest_root_wins_whatever_the_order_given():
    roots = [RedactRoot("~", "/home/qa"), RedactRoot("$XDG_DATA_HOME", "/home/qa/.data"),
             RedactRoot("<game>", "/home/qa/.data/games/vn")]
    redactor = Redactor(roots, home_name="qa", case_insensitive=False)
    assert redactor("/home/qa/.data/games/vn/script/a.vns") == "<game>/script/a.vns"
    assert redactor("/home/qa/.data/x") == "$XDG_DATA_HOME/x"
    assert redactor("/home/qa/x") == "~/x"


def test_case_sensitive_roots_on_posix():
    redactor = Redactor([RedactRoot("~", "/home/qa")], home_name=None,
                        case_insensitive=False)
    assert redactor("/home/qa/x") == "~/x"
    # A different case is not the root; the profile rule still hides the user segment.
    assert redactor("/HOME/QA/x") == "/HOME/<user>/x"


def test_repr_form_of_an_os_error_is_redacted():
    """Abuse E1: Windows OSError text doubles the backslashes."""
    home = r"C:\Users\Alice"
    redactor = Redactor([RedactRoot("~", home)], home_name="Alice", case_insensitive=True)
    error = PermissionError(13, "Permission denied", home + r"\x.png")
    text = repr(str(error))
    assert "Alice" not in redactor(str(error))
    assert "Alice" not in redactor(text)


def test_profile_rule_after_quotes_and_assignment():
    assert NO_ROOTS("path='/home/bob/x'") == "path='/home/<user>/x'"
    assert NO_ROOTS("HOME=/home/bob") == "HOME=/home/<user>"
    # /home/ inside another path is not a profile container.
    assert NO_ROOTS("/data/home/bob/x") == "/data/home/bob/x"


def test_documents_and_settings_container():
    assert NO_ROOTS(r"C:\Documents and Settings\bob\x") == \
        r"C:\Documents and Settings\<user>\x"
    assert NO_ROOTS(r"C:\Documents and Settings\All Users\x") == \
        r"C:\Documents and Settings\All Users\x"


def test_bare_drive_and_filesystem_roots_are_ignored():
    redactor = Redactor([RedactRoot("<temp>", "C:\\"), RedactRoot("<game>", "/")],
                        home_name=None, case_insensitive=True)
    assert redactor(r"C:\x\y") == r"C:\x\y"
    assert redactor("/x/y") == "/x/y"


def test_home_name_kept_names_are_never_redacted():
    redactor = Redactor((), home_name="Public", case_insensitive=True)
    assert redactor(r"D:\Public\x") == r"D:\Public\x"


def test_redact_before_install_applies_profile_rule():
    redact_module._installed = None
    assert redact("/home/alice/x") == "/home/<user>/x"


def test_install_replaces_the_redactor():
    install(Redactor([RedactRoot("<game>", "/srv/games/vn")], home_name=None,
                     case_insensitive=False))
    assert redact("/srv/games/vn/images/a.png") == "<game>/images/a.png"


# --- escape_controls ----------------------------------------------------------------------

@pytest.mark.parametrize("char, shown", [
    ("\t", "\\t"), ("\n", "\\n"), ("\r", "\\r"), ("\x00", "\\x00"), ("\x01", "\\x01"),
    ("\x1b", "\\x1b"), ("\x7f", "\\x7f"), ("\x85", "\\x85"), ("\x9f", "\\x9f"),
    ("\u2028", "\\u2028"), ("\u2029", "\\u2029"), ("\u202a", "\\u202a"),
    ("\u202e", "\\u202e"), ("\u2066", "\\u2066"), ("\u2069", "\\u2069")])
def test_escape_table(char, shown):
    assert escape_controls(f"a{char}b") == f"a{shown}b"


def test_escape_keeps_ordinary_text_and_is_idempotent():
    text = "文芸部 Café \x1b[31m\n\u202e"
    once = escape_controls(text)
    assert escape_controls(once) == once
    assert escape_controls("Литература 📖 \\x") == "Литература 📖 \\x"


def test_escape_can_keep_newlines():
    assert escape_controls("a\nb\tc", allow_newline=True) == "a\nb\\tc"


def test_forged_log_line_stays_one_line():
    forged = "images/a\n2026-11-01 00:00:00.000 ERROR app forged.png"
    assert "\n" not in escape_controls(forged)


# --- truncate and echo --------------------------------------------------------------------

def test_truncate():
    assert truncate("abc", 3) == "abc"
    assert truncate("abcd", 3) == "ab…"
    assert len(truncate("x" * 500, 120)) == 120
    assert truncate("x" * 500, 120).endswith("…")


def test_echo_limits():
    assert echo("x" * 119) == "x" * 119
    assert echo("x" * 121) == "x" * 119 + "…"
    assert echo("y" * 50, 40) == "y" * 39 + "…"


def test_echo_redacts_before_truncating():
    """Abuse E6: a cut through the user name must not leave part of it behind."""
    root = r"D:\work\Alexandra\venv"
    install(Redactor([RedactRoot("<python>", root)], home_name=None, case_insensitive=True))
    text = "x" * 100 + root + r"\lib\site.py"
    out = echo(text)
    assert len(out) <= 120
    assert "Alex" not in out
    assert out.startswith("x" * 100 + "<python>")


def test_echo_escapes_controls():
    assert echo("a\nb") == "a\\nb"


def test_echo_of_a_5_mb_string_is_fast():
    import time
    start = time.perf_counter()
    out = echo("a" * 5_000_000)
    assert time.perf_counter() - start < 1.0
    assert out == "a" * 119 + "…"

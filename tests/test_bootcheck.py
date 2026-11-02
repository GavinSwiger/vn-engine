"""Boot checks: Python and pygame-ce problems give one plain paragraph and exit 1.

AC-F01-07, AC-F01-08 (TR-F01-03).
"""

import ast
import logging
import sys
import types
from pathlib import Path

import pytest

from engine import _bootcheck
from engine.app import cli

REPO = Path(__file__).resolve().parent.parent


def _assert_one_paragraph(text: str) -> None:
    assert "Traceback" not in text
    assert text.strip(), "expected a message on stderr"
    assert "\n" not in text.strip(), "expected a single paragraph"


# --- AC-F01-07: Python too old ------------------------------------------------------------

def test_old_python_exits_1_with_one_paragraph(monkeypatch, capsys):
    monkeypatch.setattr(sys, "version_info", (3, 10, 4, "final", 0))
    with pytest.raises(SystemExit) as exit_info:
        _bootcheck.check_python()
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    _assert_one_paragraph(err)
    assert "3.10.4" in err and "3.12" in err
    assert err.strip() == ("vn-engine needs Python 3.12 or newer. You are running Python "
                           "3.10.4. Install Python 3.12+ from python.org and run the "
                           "command again.")


def test_current_python_passes(capsys):
    _bootcheck.check_python()
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("relative", [
    "engine/_bootcheck.py", "main.py", "engine/__init__.py", "engine/__main__.py"])
def test_entry_code_parses_on_python_3_6(relative):
    """The code that runs before the version check must parse on old Pythons."""
    source = (REPO / relative).read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 6))


# --- AC-F01-08: pygame problems -----------------------------------------------------------

def _fake_pygame(**attributes) -> types.ModuleType:
    module = types.ModuleType("pygame")
    for name, value in attributes.items():
        setattr(module, name, value)
    return module


def test_missing_pygame(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "pygame", None)      # makes `import pygame` fail
    with pytest.raises(SystemExit) as exit_info:
        _bootcheck.check_pygame()
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    _assert_one_paragraph(err)
    assert "pip install pygame-ce" in err


def test_original_pygame(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "pygame", _fake_pygame(vernum=(2, 6, 1)))
    with pytest.raises(SystemExit) as exit_info:
        _bootcheck.check_pygame()
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    _assert_one_paragraph(err)
    assert "pip uninstall pygame" in err and "pip install pygame-ce" in err


def test_pygame_ce_too_old(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "pygame", _fake_pygame(IS_CE=True, vernum=(2, 5, 1)))
    with pytest.raises(SystemExit) as exit_info:
        _bootcheck.check_pygame()
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    _assert_one_paragraph(err)
    assert "pip install" in err and "pygame-ce" in err and "2.5.1" in err


def test_supported_pygame_ce_gives_no_warning(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "pygame", _fake_pygame(IS_CE=True, vernum=(2, 5, 2)))
    assert _bootcheck.check_pygame() is None
    assert capsys.readouterr().err == ""


def test_installed_pygame_ce_passes():
    """The pygame-ce in this environment is within the supported range."""
    assert _bootcheck.check_pygame() is None


def _check_with_fake_2_6(monkeypatch):
    """The real check, run against a fake pygame-ce 2.6.0; the real pygame is back in
    sys.modules afterwards (the window and the loop need it)."""
    real_check = _bootcheck.check_pygame

    def check():
        with monkeypatch.context() as patch:
            patch.setitem(sys.modules, "pygame", _fake_pygame(IS_CE=True, vernum=(2, 6, 0)))
            return real_check()

    return check


@pytest.mark.display
def test_pygame_ce_2_6_warns_and_startup_continues(monkeypatch, capsys, caplog, tmp_path,
                                                   user_roots, scripted_app):
    check = _check_with_fake_2_6(monkeypatch)
    warning = check()
    assert warning is not None and "2.6.0" in warning
    assert capsys.readouterr().err == ""

    # Startup continues, and the warning is logged exactly once on the vn.app logger and
    # in the session log.
    monkeypatch.setattr(_bootcheck, "check_pygame", check)
    game = tmp_path / "game"
    game.mkdir()
    (game / "config.toml").write_text("", encoding="utf-8")      # no config warning
    (game / "script").mkdir()                                     # no W01 (F02 I-16)
    (game / "script" / "main.vns").write_text('label start:\n    "Hi."\n', encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="vn"):
        assert cli.main(["run", str(game)]) == 0
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].name == "vn.app" and "2.6.0" in warnings[0].getMessage()
    log_lines = (game / "logs" / "latest.log").read_text(encoding="utf-8").splitlines()
    warning_lines = [line for line in log_lines if line[24:31] == "WARNING"]
    assert len(warning_lines) == 1 and "pygame-ce 2.6.0" in warning_lines[0]

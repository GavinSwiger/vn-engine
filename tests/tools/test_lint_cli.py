"""F41 W1: ``python -m engine lint [GAME_DIR] [--json] [--strict]`` through ``cli.main`` and
``engine/__main__``'s ``_lint`` (``04`` §16 W1). AC-F41-10 (text output), AC-F41-11 (JSON),
AC-F41-12 (exit codes), AC-F41-13 (writes nothing; the author's ``print`` stays out, one real
subprocess), AC-F41-15 (dev runs only; the built exe's list is in
``tests/tools/build/test_real_build.py``)."""

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from engine import __main__ as entry
from engine.app import cli
from engine.core.errors import UserFacingError
from engine.core.paths import GamePaths, engine_root
from engine.tools import check as ck
from tests.tools.f45_games import edit_line, studio, tree

ITEM_KEYS = ["severity", "code", "source", "text", "file", "line", "column"]


class _Buffer:
    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> None:
        self.data += data

    def flush(self) -> None:
        pass


def _lint(monkeypatch, *args: str) -> tuple[int, bytes]:
    """``python -m engine lint ARGS`` in process: its output stream is a buffer."""
    out = _Buffer()
    monkeypatch.setattr(ck, "_isolate_stdout", lambda: out)
    monkeypatch.setattr(ck, "_quiet_logs", lambda: None)
    monkeypatch.setattr("sys.dont_write_bytecode", True)
    code = cli.main(["lint", *args], linter=entry._lint)
    return code, out.data


def _clean(tmp_path: Path, name: str = "clean") -> Path:
    """A game with nothing to report."""
    game = tmp_path / name
    (game / "script").mkdir(parents=True)
    (game / "config.toml").write_text('[game]\ntitle = "Clean"\n', encoding="utf-8")
    (game / "script" / "main.vns").write_text('label start:\n    "Hi."\n', encoding="utf-8")
    return game


def _notes_and_warnings(tmp_path: Path, name: str = "my_game") -> Path:
    """F45's game S with a config warning (no code), a TODO note in ch2.vns, and
    S's own lint warnings (an unreached label, unused pictures, sound, variable)."""
    game = studio(tmp_path, name)
    (game / "config.toml").write_bytes(b'[game]\ntitle = "My Game"\ntitel = "x"\n')
    ch2 = game / "script" / "ch2.vns"
    ch2.write_bytes(b"# TODO tidy\n" + ch2.read_bytes())
    return game


# --- AC-F41-10: text output -------------------------------------------------------------------

def test_ac_f41_10_text_output(tmp_path, monkeypatch):
    """AC-F41-10: one line per item, ``{file}:{line}:{column}: {severity} {code}: {text}``
    with missing parts dropped (no column, no line, no code), game-wide items without a
    file, ``/`` paths relative to the game folder, the words error / warning / info, and a
    summary with singular and plural forms."""
    code, data = _lint(monkeypatch, str(_notes_and_warnings(tmp_path)))
    lines = data.decode("utf-8").splitlines()
    assert code == 0
    assert lines[0] == ("config.toml:3: warning: unknown key [game] titel — did you mean "
                        '"title"?')
    assert lines[1] == "script/ch2.vns:1: info TODO: TODO tidy"
    assert lines[2].startswith('script/ch2.vns:13: warning W237: nothing leads to label "side"')
    assert ("images/bg/photo.jpg: warning W239: picture \"bg photo\" isn't shown anywhere in "
            "the story.") in lines
    assert lines[-1] == "0 errors, 6 warnings, 1 note."
    assert len(lines) == 8

    game = studio(tmp_path, "column")
    edit_line(game / "script" / "main.vns", 6, '    hana "Hi.')
    code, data = _lint(monkeypatch, str(game))
    assert code == 1
    assert data.decode("utf-8").splitlines() == [
        'script/main.vns:6:10: error E54: this quote is never closed. Add " at the end of '
        "the text.", "1 error, 0 warnings, 0 notes."]

    game = _clean(tmp_path, "no_start")
    (game / "script" / "main.vns").write_text('label begin:\n    "Hi."\n', encoding="utf-8")
    code, data = _lint(monkeypatch, str(game))
    assert code == 1
    assert data.decode("utf-8").splitlines() == [
        'error E26: The story has no label named "start". Add label start: to '
        "script/main.vns. The story begins there.", "1 error, 0 warnings, 0 notes."]


# --- AC-F41-11: JSON output -------------------------------------------------------------------

def test_ac_f41_11_json_output(tmp_path, monkeypatch):
    """AC-F41-11: ``--json`` prints one ASCII JSON document ``{v, items, errors, warnings,
    notes, more}``; every item has the one item shape; past 1,000 items only the first
    1,000 are shown, the counts cover them all and ``more`` says how many weren't shown."""
    code, data = _lint(monkeypatch, str(_notes_and_warnings(tmp_path)), "--json")
    assert code == 0 and data.isascii() and data.count(b"\n") == 1 and data.endswith(b"\n")
    doc = json.loads(data)
    assert list(doc) == ["v", "items", "errors", "warnings", "notes", "more"]
    assert (doc["v"], doc["errors"], doc["warnings"], doc["notes"], doc["more"]) == (
        1, 0, 6, 1, 0)
    assert all(list(item) == ITEM_KEYS for item in doc["items"])
    assert doc["items"][0] == {"severity": "warning", "code": "", "source": "config",
                               "text": 'unknown key [game] titel — did you mean "title"?',
                               "file": "config.toml", "line": 3, "column": None}
    assert {item["source"] for item in doc["items"][2:]} == {"lint"}

    many = _notes_and_warnings(tmp_path, "many")
    main = many / "script" / "main.vns"
    main.write_bytes(main.read_bytes() + b"".join(b"default spare%d = 0\n" % n
                                                  for n in range(1100)))
    code, data = _lint(monkeypatch, str(many), "--json")
    doc = json.loads(data)
    assert code == 0 and data.isascii()
    assert len(doc["items"]) == 1000
    assert (doc["errors"], doc["warnings"], doc["notes"]) == (0, 6 + 1100, 1)
    assert doc["more"] == 1 + 6 + 1100 - 1000


# --- AC-F41-12: exit codes --------------------------------------------------------------------

def test_ac_f41_12_exit_codes(tmp_path, monkeypatch, capsys):
    """AC-F41-12: clean 0; warnings only 0; warnings with ``--strict`` 1; errors 1 (with or
    without ``--strict``); a folder that isn't a game 2, with the text ``run`` gives."""
    clean = str(_clean(tmp_path))
    assert _lint(monkeypatch, clean) == (0, b"0 errors, 0 warnings, 0 notes.\n")
    assert _lint(monkeypatch, clean, "--strict")[0] == 0
    warned = str(_notes_and_warnings(tmp_path))
    assert _lint(monkeypatch, warned)[0] == 0
    assert _lint(monkeypatch, warned, "--strict")[0] == 1
    assert _lint(monkeypatch, warned, "--strict", "--json")[0] == 1
    broken = studio(tmp_path, "broken")
    edit_line(broken / "script" / "main.vns", 8, "    jump bridg")
    assert _lint(monkeypatch, str(broken))[0] == 1
    assert _lint(monkeypatch, str(broken), "--json", "--strict")[0] == 1
    capsys.readouterr()
    missing = tmp_path / "nope"
    assert _lint(monkeypatch, str(missing)) == (2, b"")
    with pytest.raises(UserFacingError) as run_error:
        GamePaths.for_game(missing)
    assert capsys.readouterr().err == f"{run_error.value.message}\n"


# --- AC-F41-13: writes nothing, print stays out -----------------------------------------------

def test_ac_f41_13_lint_writes_nothing_and_print_stays_out(tmp_path, user_roots):
    """AC-F41-13: the real ``python -m engine lint`` writes nothing in the game folder or
    the user folders (no logs, saves, persistent data, ``__pycache__``), and an author's
    ``print`` in a define doesn't reach stdout."""
    game = studio(tmp_path)
    edit_line(game / "script" / "main.vns", 3, "define said = print('AUTHOR-PRINT')\n"
                                               "default trust = said")
    before = tree(user_roots.home.parent)
    proc = subprocess.run([sys.executable, "-m", "engine", "lint", str(game), "--json"],
                          capture_output=True, timeout=60, cwd=str(engine_root()))
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert b"AUTHOR-PRINT" not in proc.stdout
    doc = json.loads(proc.stdout)
    assert doc["errors"] == 0 and doc["warnings"] > 0
    assert tree(user_roots.home.parent) == before


# --- AC-F41-15: dev runs only -----------------------------------------------------------------

def test_ac_f41_15_lint_is_dev_only(tmp_path, monkeypatch, capsys):
    """AC-F41-15: ``lint --release`` is a usage error ``lint is only available in dev
    runs`` (exit 2); a frozen parser has no ``lint``; ``GAME_DIR`` defaults to
    ``<repo>/game`` and a relative one resolves against the CWD; ``_lint`` imports
    ``tools.check`` only when called."""
    calls = []

    def linter(game_dir, **kwargs):
        calls.append((game_dir, kwargs))
        return 0

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["lint", "--release"], linter=linter)
    assert exit_info.value.code == 2
    assert capsys.readouterr().err.rstrip().endswith("error: lint is only available in "
                                                     "dev runs")
    assert cli.LINT_DEV_ONLY == "lint is only available in dev runs"
    monkeypatch.chdir(tmp_path)
    assert cli.main(["lint"], linter=linter) == 0
    assert cli.main(["lint", "mygame", "--json", "--strict"], linter=linter) == 0
    assert calls == [(engine_root() / "game", {"as_json": False, "strict": False}),
                     (tmp_path / "mygame", {"as_json": True, "strict": True})]
    stub = types.ModuleType("engine.tools.check")
    stub.lint_command = lambda game_dir, **kw: calls.append((game_dir, kw)) or 7
    monkeypatch.setitem(sys.modules, "engine.tools.check", stub)
    assert entry._lint(tmp_path, as_json=True, strict=False) == 7
    assert calls.pop() == (tmp_path, {"as_json": True, "strict": False})
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["lint"], linter=linter)
    assert exit_info.value.code == 2
    assert "invalid choice: 'lint'" in capsys.readouterr().err
    assert len(calls) == 2

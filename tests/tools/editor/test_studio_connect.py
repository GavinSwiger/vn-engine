"""F48 step W2: Help ▸ Connect an AI app… (``01-design.md`` §6.5, PR-F48-13; ``04`` §3.2;
SEC-F48-08): AC-F48-28. The snippets are built from Studio's interpreter, the engine folder
and the game folder; every form uses ``-P`` and ``PYTHONPATH`` = the engine folder only;
unticking the write box adds ``--read-only``; Copy copies each; nothing is logged. One
copied setup is started as an app would start it, to show it really serves."""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine.core.paths import engine_root
from engine.tools.editor import connectdialog as cd
from tests.tools.f45_games import studio as make_game

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401  (fixture)

PYTHON = Path("C:/Program Files/Python312/python.exe")
ENGINE = Path("D:/My Games/vn-engine")
GAME = Path("D:/My Games/Lantern Night")


def test_snippets_follow_01_section_6_5():
    shown = cd.snippets(PYTHON, ENGINE, GAME, windows=True)
    assert shown.server == "vn-lantern-night"
    assert shown.claude_code == (
        f'claude mcp add --scope user vn-lantern-night -e PYTHONPATH="{ENGINE}" "--" "{PYTHON}" -P -m engine '
        f'assist-mcp "{GAME}"')
    assert json.loads(shown.claude_desktop) == {"mcpServers": {"vn-lantern-night": {
        "command": str(PYTHON), "args": ["-P", "-m", "engine", "assist-mcp", str(GAME)],
        "env": {"PYTHONPATH": str(ENGINE)}}}}
    assert shown.other == (f"Command: {PYTHON}\n"
                           f'Arguments: -P -m engine assist-mcp "{GAME}"\n'
                           f"Environment: PYTHONPATH={ENGINE}")
    read_only = cd.snippets(PYTHON, ENGINE, GAME, write=False, windows=True)
    assert read_only.claude_code == shown.claude_code + " --read-only"
    assert json.loads(read_only.claude_desktop)["mcpServers"]["vn-lantern-night"]["args"][-1] \
        == "--read-only"
    assert read_only.other.splitlines()[1] == f'Arguments: -P -m engine assist-mcp "{GAME}" ' \
                                              "--read-only"
    # A POSIX shell would expand $ inside double quotes: such a path is single-quoted there.
    assert cd.quoted("/home/a$b/game", windows=False) == "'/home/a$b/game'"
    assert cd.quoted("/home/a b/game", windows=False) == '"/home/a b/game"'
    assert cd.server_name(Path("x/!!")) == "vn-game"


def test_the_copied_desktop_setup_serves_the_game(tmp_path):
    """The Claude Desktop setup, started as the app starts it (its command, its args, its env
    and nothing else from PYTHON*), answers ``initialize`` with only JSON on stdout."""
    game = make_game(tmp_path)
    setup = json.loads(cd.snippets(sys.executable, engine_root(), game,
                                   write=False).claude_desktop)
    server = setup["mcpServers"]["vn-my-game"]
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("PYTHON")} | server["env"]
    proc = subprocess.run(
        [server["command"], *server["args"]], cwd=str(tmp_path), env=env, timeout=120,
        input=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
              b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n', capture_output=True)
    assert proc.returncode == 0, proc.stderr[-2000:]
    first, listed = (json.loads(line) for line in proc.stdout.splitlines())
    assert first["result"]["serverInfo"]["name"] == "vn-engine"
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert "read_script" in names and "apply_edit" not in names        # --read-only


@pytest.mark.tk
def test_ac_f48_28_connect_an_ai_app(studio, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    game = make_game(tmp_path)
    ed = studio(game, mapped=True)
    caplog.clear()                                  # from here on: the dialog's lifetime
    menu = ed.win.help_menu
    menu.invoke(menu.index(cd.MENU))
    ed.root.update()
    dialog = ed.win.connect_dialog
    assert dialog is not None and dialog.alive and dialog.dialog.winfo_viewable()
    assert dialog.dialog.title() == cd.TITLE
    assert bool(dialog.write.get()) is True                         # ticked at first
    want = cd.snippets(sys.executable, engine_root(), game)
    assert dialog.texts() == want.all()
    for text in (want.claude_code, want.other):
        assert " -P -m engine assist-mcp " in text and f"PYTHONPATH={engine_root()}" in \
            text.replace('"', "") and str(game) in text and sys.executable in text
    assert json.loads(want.claude_desktop)["mcpServers"]["vn-my-game"] == {
        "command": sys.executable, "args": ["-P", "-m", "engine", "assist-mcp", str(game)],
        "env": {"PYTHONPATH": str(engine_root())}}
    assert not any("--read-only" in text for text in want.all())
    assert len(dialog.copies) == 3
    for index, button in enumerate(dialog.copies):
        assert button.cget("text") == cd.COPY
        button.invoke()
        assert ed.root.clipboard_get() == want.all()[index]
    # Every box shows its whole text (no line hidden below the box).
    for code in dialog.codes:
        shown = code.count("1.0", "end", "displaylines", "update")
        lines = shown[0] if isinstance(shown, tuple) else shown
        assert int(code.cget("height")) >= lines
    # Unticking adds --read-only to all three, and Copy copies that.
    dialog.write_box.invoke()
    ed.root.update()
    read_only = cd.snippets(sys.executable, engine_root(), game, write=False)
    assert dialog.texts() == read_only.all()
    assert all("--read-only" in text for text in dialog.texts())
    dialog.copies[0].invoke()
    assert ed.root.clipboard_get() == read_only.claude_code
    # The menu again raises the open dialog; Esc closes it.
    menu.invoke(menu.index(cd.MENU))
    assert ed.win.connect_dialog is dialog
    dialog.dialog.event_generate("<Escape>")
    ed.root.update()
    assert not dialog.alive and ed.win.connect_dialog is None
    # Full paths appear only in the dialog: nothing was logged.
    logged = "\n".join(record.getMessage() for record in caplog.records)
    for path in (str(game), str(engine_root()), sys.executable):
        assert path not in logged
    assert not [r for r in caplog.records if r.pathname.endswith("connectdialog.py")]


def test_set_up_claude_code_runs_claude_without_a_shell(tmp_path):
    calls = []

    class Done:
        returncode, stdout, stderr = 0, b"", b""

    def run(argv, **kwargs):
        calls.append(argv)
        return Done()

    game = tmp_path / "Lantern Night"
    ok, text = cd.setup_claude_code("py", "eng", game, which=lambda _n: "/bin/claude", run=run)
    assert ok and text == cd.CODE_DONE
    assert calls[0] == ["/bin/claude", "mcp", "remove", "--scope", "user", "vn-lantern-night"]
    assert calls[1] == ["/bin/claude", "mcp", "add", "--scope", "user", "vn-lantern-night",
                        "-e", "PYTHONPATH=eng", "--", "py", "-P", "-m", "engine",
                        "assist-mcp", str(game)]
    assert cd.setup_claude_code("py", "eng", game, which=lambda _n: None, run=run) == (
        False, cd.CODE_MISSING)
    # A .cmd launcher goes through cmd.exe: a folder name it would read is refused.
    assert cd.setup_claude_code("py", "eng", tmp_path / "a&b", which=lambda _n: "c.cmd",
                                run=run) == (False, cd.CODE_UNSAFE)

    class Failed:
        returncode, stdout, stderr = 1, b"", b"some detail\nError: no can do\n"

    ok, text = cd.setup_claude_code("py", "eng", game, which=lambda _n: "claude",
                                    run=lambda argv, **kw: Failed())
    assert not ok and text == cd.CODE_FAILED.format(reason="Error: no can do")


def test_set_up_claude_desktop_keeps_the_rest_of_its_settings(tmp_path):
    config = tmp_path / cd.DESKTOP_CONFIG
    config.write_text('{"theme": "dark", "mcpServers": {"other": {"command": "x"}}}',
                      encoding="utf-8")
    game = tmp_path / "My Game"
    assert cd.setup_claude_desktop("py", "eng", game, write=False, path=config) == (
        True, cd.DESKTOP_DONE)
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["theme"] == "dark" and data["mcpServers"]["other"] == {"command": "x"}
    assert data["mcpServers"]["vn-my-game"] == {
        "command": "py", "args": ["-P", "-m", "engine", "assist-mcp", str(game), "--read-only"],
        "env": {"PYTHONPATH": "eng"}}
    assert json.loads((tmp_path / (cd.DESKTOP_CONFIG + ".bak")).read_text())["theme"] == "dark"
    # A file that isn't JSON is left alone; no folder means Claude Desktop isn't installed.
    config.write_text("{oops", encoding="utf-8")
    ok, text = cd.setup_claude_desktop("py", "eng", game, path=config)
    assert not ok and cd.DESKTOP_BAD_FILE in text and config.read_text() == "{oops"
    assert cd.desktop_config_path({"APPDATA": str(tmp_path / "none")}, "win32") is None
    (tmp_path / "Roaming" / "Claude").mkdir(parents=True)
    assert cd.desktop_config_path({"APPDATA": str(tmp_path / "Roaming")}, "win32") == \
        tmp_path / "Roaming" / "Claude" / cd.DESKTOP_CONFIG
    assert cd.desktop_config_path({}, "linux") is None

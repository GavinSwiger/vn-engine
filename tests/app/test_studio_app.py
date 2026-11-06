"""The Studio app (``vn-engine Studio.exe``, ``scripts/build_studio.py``): its editor-build
marker, the child command lines that start the app itself instead of Python, and the games
folder in Documents. A player build (a built game) must never become an editor build (I-15).
"""

import importlib.abc
import importlib.machinery
import sys
from pathlib import Path

import pytest

from engine import __main__ as entry
from engine.app import cli
from engine.core import childcmd, paths
from engine.tools.editor import buildmodel, checker, connectdialog, files, gamesfolder, \
    helperrunner, preview, trywiring

REPO = Path(__file__).resolve().parent.parent.parent


class _MarkerFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serves the marker module from memory, as the app's frozen archive does."""

    def __init__(self, value: object) -> None:
        self.value = value

    def find_spec(self, name, path=None, target=None):
        if name != paths.EDITOR_BUILD_MODULE:
            return None
        return importlib.machinery.ModuleSpec(name, self)

    def create_module(self, spec):
        return None

    def exec_module(self, module) -> None:
        module.EDITOR_BUILD = self.value


def _frozen(monkeypatch, folder: Path, exe: str) -> Path:
    (folder / "_internal").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(folder / "_internal"), raising=False)
    monkeypatch.setattr(sys, "executable", str(folder / exe))
    monkeypatch.delitem(sys.modules, paths.EDITOR_BUILD_MODULE, raising=False)
    return folder


def _marker(monkeypatch, value: object = paths.EDITOR_BUILD_VALUE) -> None:
    monkeypatch.setattr(sys, "meta_path", [_MarkerFinder(value), *sys.meta_path])


@pytest.fixture
def studio_app(monkeypatch, tmp_path):
    """The Studio app as its exe sees itself: frozen, the marker in its archive."""
    folder = _frozen(monkeypatch, tmp_path / "vn-engine Studio", "vn-engine Studio.exe")
    _marker(monkeypatch)
    yield folder
    sys.modules.pop(paths.EDITOR_BUILD_MODULE, None)


@pytest.fixture
def player_build(monkeypatch, tmp_path):
    """A built game: frozen, no marker."""
    folder = _frozen(monkeypatch, tmp_path / "Lanterns", "Lanterns.exe")
    yield folder
    sys.modules.pop(paths.EDITOR_BUILD_MODULE, None)


@pytest.fixture
def launched(monkeypatch):
    calls: list[dict] = []

    def fake_launch(game_dir, **kwargs):
        calls.append({"game_dir": game_dir, **kwargs})
        return 0

    monkeypatch.setattr(cli, "_launch", fake_launch)
    monkeypatch.setattr(cli._bootcheck, "check_pygame", lambda: None)
    return calls


# --- The marker ----------------------------------------------------------------------------

def test_dev_run_is_not_an_editor_build(monkeypatch):
    _marker(monkeypatch)                     # even with the marker importable
    monkeypatch.delattr(sys, "frozen", raising=False)
    try:
        assert paths.is_editor_build() is False
        assert paths.player_runtime_dir() is None
    finally:
        sys.modules.pop(paths.EDITOR_BUILD_MODULE, None)


def test_player_build_is_not_an_editor_build(player_build):
    assert paths.is_editor_build() is False
    assert cli.editor_prelude() is False
    assert entry.studio_app_main([]) == 2
    assert entry.studio_app_main(["--child", "edit"]) == 2


def test_studio_app_is_an_editor_build(studio_app):
    assert paths.is_editor_build() is True


def test_marker_with_another_value_is_refused(player_build, monkeypatch):
    _marker(monkeypatch, value=True)
    assert paths.is_editor_build() is False


def test_loose_marker_file_is_refused(player_build, monkeypatch):
    """A ``vn_studio_build.py`` dropped beside a built game's exe or in its ``_internal``
    loads through a file loader: it never makes the game an editor build."""
    internal = player_build / "_internal"
    (internal / f"{paths.EDITOR_BUILD_MODULE}.py").write_text(
        f"EDITOR_BUILD = {paths.EDITOR_BUILD_VALUE!r}\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(internal))
    assert paths.is_editor_build() is False


def test_marker_is_nowhere_in_the_repository():
    """The marker exists only in the Studio app's staging folder, so the player build (which
    bundles the ``engine`` package and ``main.py``) can't pick it up."""
    name = f"{paths.EDITOR_BUILD_MODULE}.py"
    assert not any(REPO.glob(name)) and not any((REPO / "engine").rglob(name))


def test_player_runtime_dir(studio_app):
    assert paths.player_runtime_dir() is None
    (studio_app / paths.PLAYER_RUNTIME_DIRNAME).mkdir()
    assert paths.player_runtime_dir() == studio_app / "player"


# --- The CLI: a player build refuses dev tools, the Studio app keeps them --------------------

def test_player_build_parser_refuses_every_dev_tool(player_build, launched, capsys):
    for command in ("edit", "check", "helper", "build", "lint", "assist-mcp"):
        with pytest.raises(SystemExit) as exit_info:
            entry.main([command])
        assert exit_info.value.code == 2
        assert f"invalid choice: '{command}'" in capsys.readouterr().err
    assert entry.main(["run", str(player_build)]) == 0
    assert launched[-1]["release"] is True and launched[-1]["console"] is None


def test_studio_app_child_is_a_dev_run(studio_app, launched, monkeypatch, tmp_path):
    """``vn-engine Studio.exe --child run …`` is ``python -m engine run …``: a dev run with
    the console, line reports and start options."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    assert entry.studio_app_main(["--child", "run", str(tmp_path), "--report-to-editor",
                                  "--start", "intro"]) == 0
    call = launched[-1]
    assert call["game_dir"] == tmp_path and call["release"] is False
    assert call["editor_report"] is True and call["start"].label == "intro"
    assert call["console"] is entry._console
    assert sys.dont_write_bytecode is True


def test_studio_app_child_runs_dev_tools(studio_app, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "path", list(sys.path))
    seen = []
    monkeypatch.setattr(entry, "_lint", lambda game_dir, **kw: seen.append((game_dir, kw)) or 3)
    assert entry.studio_app_main(["--child", "lint", str(tmp_path), "--json"]) == 3
    assert seen == [(tmp_path, {"as_json": True, "strict": False})]


def test_studio_app_opens_studio_without_child(studio_app, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "path", list(sys.path))
    opened = []
    monkeypatch.setattr(entry, "_edit", lambda game_dir: opened.append(game_dir) or 0)
    monkeypatch.setattr(gamesfolder, "start_folder", lambda: tmp_path / "Paper Lanterns")
    assert entry.studio_app_main([]) == 0
    assert entry.studio_app_main([str(tmp_path / "mine")]) == 0
    assert opened == [tmp_path / "Paper Lanterns", tmp_path / "mine"]
    assert entry.studio_app_main(["--bogus"]) == 2


def test_child_switch_matches():
    assert entry.CHILD_SWITCH == childcmd.CHILD_SWITCH


# --- Child command lines -------------------------------------------------------------------

def test_engine_argv_dev_and_app(monkeypatch, tmp_path):
    assert childcmd.engine_argv("check", "g", python_flags=("-B",)) == [
        sys.executable, "-B", "-m", "engine", "check", "g"]
    with pytest.raises(ValueError):
        childcmd.engine_argv("run", python_flags=("-c",))
    folder = _frozen(monkeypatch, tmp_path / "app", "vn-engine Studio.exe")
    _marker(monkeypatch)
    try:
        exe = str(folder / "vn-engine Studio.exe")
        assert childcmd.engine_argv("check", "g", python_flags=("-B",)) == [
            exe, "--child", "check", "g"]
        assert childcmd.server_prefix(("-P",)) == ["--child"]
    finally:
        sys.modules.pop(paths.EDITOR_BUILD_MODULE, None)


def test_studio_children_start_the_app(studio_app, tmp_path):
    """Play, Update, try-it, the check job, the helper, Build game, New game's window and
    the MCP server all start ``vn-engine Studio.exe --child …`` in the app."""
    exe = str(studio_app / "vn-engine Studio.exe")
    game = tmp_path / "g"
    head = [exe, "--child"]
    argvs = [preview.preview_argv(game, "intro", []), trywiring.try_argv(game),
             checker.check_argv(game), helperrunner.helper_argv(game),
             buildmodel.build_argv(game, tmp_path / "b", zip=True, replace=False),
             files.studio_argv(game)]
    for argv in argvs:
        assert argv[:2] == head and "-m" not in argv and "-B" not in argv
    assert [argv[2] for argv in argvs] == ["run", "run", "check", "helper", "build", "edit"]
    assert preview.preview_argv(game, "intro", [])[3:] == [str(game), "--report-to-editor",
                                                          "--start", "intro"]
    assert connectdialog.server_args(game) == ["--child", "assist-mcp", str(game)]
    snippet = connectdialog.snippets(exe, tmp_path, game).other
    assert "Arguments: --child assist-mcp" in snippet


def test_dev_children_start_python():
    game = Path("g")
    assert checker.check_argv(game)[:5] == [sys.executable, "-B", "-m", "engine", "check"]
    assert buildmodel.build_argv(game, Path("b"), zip=False, replace=False)[:6] == [
        sys.executable, "-E", "-B", "-m", "engine", "build"]
    assert connectdialog.server_args(game) == ["-P", "-m", "engine", "assist-mcp", "g"]


# --- The games folder ----------------------------------------------------------------------

def _source_game(root: Path) -> Path:
    for ref in ("config.toml", "script/main.vns", "minigames/hook.py", "logs/x.log",
                "saves/1.save", ".studio/studio.json", "minigames/__pycache__/hook.pyc",
                "images/bg/a.png"):
        (root / ref).parent.mkdir(parents=True, exist_ok=True)
        (root / ref).write_text(ref, encoding="utf-8")
    return root


def test_copy_example_leaves_out_run_files(tmp_path):
    source = _source_game(tmp_path / "game")
    target = tmp_path / "games" / "Paper Lanterns"
    gamesfolder.copy_example(target, source=source)
    copied = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
    assert copied == ["config.toml", "images/bg/a.png", "minigames/hook.py",
                      "script/main.vns"]
    assert [p.name for p in target.parent.iterdir()] == ["Paper Lanterns"]


def test_start_folder_copies_paper_lanterns_once(monkeypatch, tmp_path):
    source = _source_game(tmp_path / "game")
    games = tmp_path / "Documents" / "vn-engine"
    monkeypatch.setattr(gamesfolder, "games_dir", lambda: games)
    monkeypatch.setattr(gamesfolder, "studio_user_dir", lambda: None)
    monkeypatch.setattr(gamesfolder, "example_game_dir", lambda: source)
    first = gamesfolder.start_folder()
    assert first == games / "Paper Lanterns" and (first / "script" / "main.vns").is_file()
    (first / "script" / "main.vns").write_text("mine", encoding="utf-8")
    assert gamesfolder.start_folder() == first
    assert (first / "script" / "main.vns").read_text(encoding="utf-8") == "mine"


def test_start_folder_without_documents(monkeypatch):
    monkeypatch.setattr(gamesfolder, "games_dir", lambda: None)
    monkeypatch.setattr(gamesfolder, "studio_user_dir", lambda: None)
    with pytest.raises(LookupError):
        gamesfolder.start_folder()


def test_last_game_is_remembered_in_the_app_only(monkeypatch, tmp_path):
    user = tmp_path / "studio"
    user.mkdir()
    game = _source_game(tmp_path / "Mine")
    monkeypatch.setattr(gamesfolder, "studio_user_dir", lambda: user)
    gamesfolder.remember_game(game)                 # a dev run: nothing written
    assert not (user / gamesfolder.LAST_GAME_FILE).exists()
    monkeypatch.setattr(gamesfolder, "is_editor_build", lambda: True)
    gamesfolder.remember_game(game)
    assert gamesfolder.last_game() == game
    assert gamesfolder.start_folder() == game
    (user / gamesfolder.LAST_GAME_FILE).write_text(str(tmp_path / "gone"), encoding="utf-8")
    assert gamesfolder.last_game() is None


def test_games_folder_is_documents_vn_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "documents_dir", lambda: tmp_path / "Docs")
    assert paths.games_dir() == tmp_path / "Docs" / "vn-engine"
    assert paths.default_games_dir() is None            # dev run: the dialog's default
    monkeypatch.setattr(paths, "is_editor_build", lambda: True)
    assert paths.default_games_dir() is None            # not made yet
    (tmp_path / "Docs" / "vn-engine").mkdir(parents=True)
    assert paths.default_games_dir() == tmp_path / "Docs" / "vn-engine"


def test_documents_dir_is_absolute():
    found = paths.documents_dir()
    assert found is None or found.is_absolute()

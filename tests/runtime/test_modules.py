"""``module(name)`` (F03 ``04-technical.md`` §7.9; SR-F03-23, 24; TR-F03-10).

ACs: AC-F03-38 (the planted-module rows, the ``game_has`` and ``find_spec`` spies, audit spy
A, and the failing-import unit row; the name rows are ``cases.toml`` rows run by
``test_messages_f03.py``). TR-F03-10: the game folder, the working directory, and the engine
are refused; ``math``, ``os.path``, and an installed package are accepted.

Every planted ``helpers.py`` is ``tests/fixtures/F03/modules/helpers.py``: importing it writes
``ZZMARK.txt`` in the working directory and raises ``SystemExit``.
"""

import importlib.util
import math
import os
import os.path
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from engine.app.loading import game_has
from engine.core.paths import GamePaths
from engine.runtime import modules
from engine.runtime.launch import run_launch
from engine.runtime.modules import ModuleRefused, make_module
from tests.runtime.story import FIXTURES, load_r

ROOT = Path(__file__).resolve().parents[2]
HELPERS = FIXTURES / "modules" / "helpers.py"

GAME_FOLDER = ("define helpers couldn't be set: \"helpers\" is a file in the game folder, and "
               "module can only use modules that come with Python or are installed. Write "
               "small helpers in a define with lambda instead.")
ELSEWHERE = ("define helpers couldn't be set: \"helpers\" doesn't come with Python and isn't "
             "installed, so module can't use it. Use a module that comes with Python, such as "
             "\"math\".")


@pytest.fixture
def places(tmp_path, monkeypatch):
    """A game root, a working directory outside it, and a spare folder; the test runs in the
    working directory. Checks afterwards that no planted module ran."""
    game, cwd, spare = tmp_path / "game", tmp_path / "cwd", tmp_path / "spare"
    for folder in (game, cwd, spare):
        folder.mkdir()
    monkeypatch.chdir(cwd)
    assert importlib.util.find_spec("helpers") is None
    yield game, cwd, spare
    assert "helpers" not in sys.modules
    for folder in (game, cwd, spare, ROOT):
        assert not (folder / "ZZMARK.txt").exists()


def plant(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HELPERS, path)


def launch_helpers(game: Path, spy: list | None = None):
    """Launch R in ``game`` with ``define helpers = module("helpers")`` through the app's
    ``game_has``; returns the one error."""
    program = load_r(game, T='define helpers = module("helpers")')
    paths = GamePaths(game.resolve())
    has = game_has(paths)
    if spy is not None:
        real = has

        def has(ref: str) -> bool:
            spy.append(("game_has", ref))
            return real(ref)
    result = run_launch(program, game_has=has, game_root=paths.root)
    assert result.namespace is None and result.error_count == 1
    (error,) = result.errors
    assert (error.code, error.line) == ("E89c", 11)
    return error


# --- AC-F03-38 — refused modules --------------------------------------------------------------

@pytest.mark.parametrize("ref", ["helpers.py", "script/helpers.py", "helpers/__init__.py"])
def test_ac_f03_38_a_module_in_the_game_folder(places, ref):
    game, _, _ = places
    plant(game / ref)
    assert launch_helpers(game).message == GAME_FOLDER


def test_ac_f03_38_the_game_folder_found_on_sys_path(places, monkeypatch):
    """When the game root itself is on ``sys.path``, the origin check names the game folder."""
    game, _, _ = places
    plant(game / "helpers.py")
    monkeypatch.syspath_prepend(str(game))
    assert launch_helpers(game).message == GAME_FOLDER


@pytest.mark.parametrize("where", ["cwd", "sys.path"])
def test_ac_f03_38_a_module_elsewhere(places, monkeypatch, where):
    game, cwd, spare = places
    folder = cwd if where == "cwd" else spare
    plant(folder / "helpers.py")
    monkeypatch.syspath_prepend(str(folder))
    assert importlib.util.find_spec("helpers") is not None
    assert launch_helpers(game).message == ELSEWHERE


def test_ac_f03_38_game_has_is_asked_only_when_find_spec_finds_nothing(places, monkeypatch):
    game, cwd, _ = places
    plant(game / "helpers.py")
    calls: list = []
    real_find_spec = importlib.util.find_spec

    def find_spec(name, *args):
        spec = real_find_spec(name, *args)
        calls.append(("find_spec", name, spec is None))
        return spec

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)
    launch_helpers(game, calls)
    assert calls == [("find_spec", "helpers", True), ("game_has", "helpers.py")]
    # Found by find_spec (here: in the working directory): game_has is never asked.
    calls.clear()
    plant(cwd / "helpers.py")
    monkeypatch.syspath_prepend(str(cwd))
    assert launch_helpers(game, calls).message == ELSEWHERE
    assert calls == [("find_spec", "helpers", False)]
    # Nothing anywhere: all three places are asked, then E89.
    calls.clear()
    module = make_module(lambda ref: calls.append(("game_has", ref)) or False)
    with pytest.raises(ModuleRefused) as caught:
        module("zzqx")
    assert caught.value.code == "E89"
    assert calls == [("find_spec", "zzqx", True), ("game_has", "zzqx.py"),
                     ("game_has", "zzqx/__init__.py"), ("game_has", "script/zzqx.py")]
    calls.clear()
    assert module("math") is math and calls == [("find_spec", "math", False)]


AUDIT = textwrap.dedent("""
    import os, sys
    from pathlib import Path
    from engine.app.loading import game_has
    from engine.core.paths import GamePaths
    from engine.runtime.modules import ModuleRefused, make_module

    paths = GamePaths(Path(sys.argv[1]).resolve())
    root = os.path.normcase(str(paths.root))
    module = make_module(game_has(paths), game_root=paths.root)
    state = {"on": False, "opens": [], "events": 0}

    def hook(event, args):
        if not state["on"]:
            return
        state["events"] += 1
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            path = os.path.normcase(os.path.abspath(os.fsdecode(args[0])))
            if path == root or path.startswith(root + os.sep):
                state["opens"].append(path)

    sys.addaudithook(hook)
    for name in ("helpers", "math", "os.path", "zzqx", "maths", "engine", "main", "json"):
        state["on"] = True
        try:
            module(name)
        except ModuleRefused:
            pass
        finally:
            state["on"] = False
    print(len(state["opens"]), state["events"] > 0, "helpers" in sys.modules)
""")


def test_ac_f03_38_no_file_under_the_game_root_is_opened(tmp_path):
    """Audit spy A: during every ``module()`` call, no ``open`` event under the game root."""
    game = tmp_path / "game"
    plant(game / "helpers.py")
    plant(game / "script" / "helpers.py")
    plant(game / "helpers" / "__init__.py")
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYGAME_HIDE_SUPPORT_PROMPT="1")
    out = subprocess.run([sys.executable, "-c", AUDIT, str(game)], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "0 True False"
    assert not (tmp_path / "ZZMARK.txt").exists()


def test_ac_f03_38_a_module_that_fails_while_importing(tmp_path, monkeypatch):
    """Unit: with the allowed roots patched to a temp folder holding ``boom.py``, the import's
    own failure is E85 family at the define."""
    folder = tmp_path / "allowed"
    folder.mkdir()
    (folder / "boom.py").write_text('raise ValueError("boom")\n', encoding="utf-8")
    monkeypatch.setattr(modules, "allowed_roots", lambda: [folder.resolve()])
    monkeypatch.syspath_prepend(str(folder))
    result = run_launch(load_r(tmp_path / "game", T='define b = module("boom")'))
    (error,) = result.errors
    assert error.code == "E85" and error.line == 11
    assert error.message.startswith("define b couldn't be set: ")
    assert error.message == ("define b couldn't be set: this value stopped with an error: "
                             "boom. Check the values this line uses; the log has the details.")
    assert "boom" not in sys.modules


# --- TR-F03-10 — what is accepted ---------------------------------------------------------------

def test_tr_f03_10_python_and_installed_packages_are_accepted():
    module = make_module()
    assert module("math") is math
    assert module("os.path") is os.path
    pluggy = module("pluggy")                 # installed in the test environment
    assert pluggy.__name__ == "pluggy"
    assert module("json.decoder").__name__ == "json.decoder"


@pytest.mark.parametrize("name, code", [
    ("engine.app", "E89c"), ("main", "E89c"), ("engine", "E89c"), ("tests", "E89c"),
    ("x" * 201, "E89"), ("os.", "E89"), ("1abc", "E89"), ("os.nothing_here", "E89"),
])
def test_tr_f03_10_refused(name, code):
    with pytest.raises(ModuleRefused) as caught:
        make_module()(name)
    assert caught.value.code == code


@pytest.mark.parametrize("args", [(5,), (), ("math", "os"), (b"math",)])
def test_e89b_the_name_must_be_text(args):
    with pytest.raises(ModuleRefused) as caught:
        make_module()(*args)
    assert caught.value.code == "E89b"


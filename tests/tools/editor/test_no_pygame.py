"""AC-F44-33 (a), TR-F44-01: the editor process never loads pygame or the game's runtime.

In a fresh process (one subprocess, I-16): parse ``python -m engine edit R`` through
``cli.main`` with ``engine/__main__.py``'s real handler, with ``run_editor`` replaced by one
that imports ``engine.tools.editor`` and builds the window on game R on a withdrawn root.
Afterwards ``pygame`` and every ``engine.app*`` module except ``engine.app.cli`` (the one
module the editor process takes from ``app``, ADR-0008), and every ``engine.render*``,
``engine.ui*``, ``engine.audio*``, and ``engine.runtime*`` module, are absent.

AC-F45-47 re-runs it on Studio W (game S, a fake check runner) after a fake ``DONE``, Ctrl+2,
the ``room.png`` preview and a completion, with ``engine.tools.check`` banned as well, and
checks that ``pyproject.toml``'s dependencies are still F44's. AC-F46-45 adds, in the same
child: the Events tab, an Events action, a rename across files, a moved box and the layout
file's write, and checks F46's Studio modules were loaded.
"""

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.tk

REPO = Path(__file__).resolve().parent.parent.parent.parent

CHILD = r"""
import sys
import tkinter

try:
    root = tkinter.Tk()
except tkinter.TclError:
    print("NO-DISPLAY")
    sys.exit(0)
root.destroy()

import engine.__main__ as engine_main
import engine.tools.editor as editor_package
from engine.app import cli

built = []


def build_window(game_dir):
    from engine.core.paths import GamePaths
    from engine.tools.editor.window import EditorWindow

    root = tkinter.Tk()
    root.withdraw()
    built.append(EditorWindow(root, GamePaths.for_game(game_dir)))
    root.update_idletasks()
    root.destroy()
    return 0


editor_package.run_editor = build_window
assert cli.main(["edit", sys.argv[1]], editor=engine_main._edit) == 0
assert len(built) == 1
banned = ("engine.render", "engine.ui", "engine.audio", "engine.runtime")
found = sorted(name for name in sys.modules
               if name.split(".")[0] == "pygame"
               or (name.startswith("engine.app") and name not in ("engine.app",
                                                                  "engine.app.cli"))
               or name.startswith(banned))
print(found)
"""


def test_ac33a_the_editor_process_loads_no_pygame(route_game):
    result = subprocess.run([sys.executable, "-c", CHILD, str(route_game)], cwd=REPO,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    if result.stdout.strip() == "NO-DISPLAY":
        pytest.skip("no display for Tk")
    assert result.stdout.strip() == "[]"


STUDIO_CHILD = r"""
import sys
import tkinter

try:
    root = tkinter.Tk()
except tkinter.TclError:
    print("NO-DISPLAY")
    sys.exit(0)
root.destroy()

import engine.__main__ as engine_main
import engine.tools.editor as editor_package
from engine.app import cli

done = []


class FakeChecks:
    def request(self, overlay, serial, *, launch):
        pass

    def poll(self):
        return []

    def stop(self):
        pass


def build_window(game_dir):
    from engine.core.paths import GamePaths
    from engine.script.labelgraph import LabelLink
    from engine.tools.editor.checker import (CheckEvent, CheckResult, CheckState,
                                             NameEntry)
    from engine.tools.editor.window import EditorWindow

    root = tkinter.Tk()
    root.withdraw()
    win = EditorWindow(root, GamePaths.for_game(game_dir), check_runner=FakeChecks())
    labels = tuple(NameEntry(name, file, line) for name, file, line in (
        ("start", "script/main.vns", 4), ("club", "script/ch2.vns", 1),
        ("bridge", "script/ch2.vns", 8), ("river", "script/ch2.vns", 10)))
    links = (LabelLink("start", "club", "call", "script/main.vns", 7),
             LabelLink("start", "bridge", "jump", "script/main.vns", 8),
             LabelLink("club", "river", "menu", "script/ch2.vns", 4))
    result = CheckResult(problems=(), problem_total=0,
                         names={"label": labels, "image": (NameEntry("hana happy"),)},
                         links=links, loaded=True, serial=win.edit_serial, seconds=0.1)
    win.apply_check_events([CheckEvent(CheckState.DONE, result.serial, result)])
    win.show_tab(1)                                       # Ctrl+2's handler
    root.update()
    assert win.story_map.layout is not None and win.story_map.layout.boxes
    win.tree.selection_set("images/bg/room.png")          # the asset preview
    win.tree.focus("images/bg/room.png")
    root.update()
    assert win.current_tab() == "asset"
    win.tree.selection_set("script/main.vns")
    win.tree.focus("script/main.vns")
    root.update()
    win.text.insert("end-1c", "\n    jump b")
    win.text.mark_set("insert", "end-1c")
    win.complete()                                        # Ctrl+Space's handler
    root.update()
    assert win.popup.is_open
    win.close_completion()

    # AC-F46-45: Events open, an Events action and a rename applied, a box moved, and the
    # layout file written.
    import engine.tools.editor.mapwiring as map_module     # rename_scene's dialogs
    view = win.story_map
    win.side_tab = "events"
    win.open_label_beside(view.layout.boxes[view.layout.index_of("river")])
    root.update()
    assert win.story is not None and win.story.rows
    win.story.move(0, 1)
    map_module.ask_text = lambda *args, **kwargs: ("river bank", True)
    map_module.ask = lambda *args, **kwargs: 0
    view.focus_box(view.layout.index_of("river"))
    assert win.rename_scene() is not None
    view.move_to(view.layout.index_of("club"), (300, 300))
    win.save_layout()
    assert (game_dir / ".studio" / "storymap.json").is_file()
    for name in ("scenes", "forms", "eventsview", "scriptedit", "formdialogs",
                 "layoutfile", "storyeditor", "studiolook", "fileactions", "checkwiring",
                 "runwiring", "mapwiring", "studiomenus", "editorkeys", "playbar",
                 "guidepane", "guide", "studiostate"):
        assert "engine.tools.editor." + name in sys.modules, name
    done.append(win)
    root.destroy()
    return 0


editor_package.run_editor = build_window
assert cli.main(["edit", sys.argv[1]], editor=engine_main._edit) == 0
assert len(done) == 1
banned = ("engine.render", "engine.ui", "engine.audio", "engine.runtime", "engine.tools.check")
found = sorted(name for name in sys.modules
               if name.split(".")[0] == "pygame"
               or (name.startswith("engine.app") and name not in ("engine.app",
                                                                  "engine.app.cli"))
               or name.startswith(banned))
print(found)
"""

# The runtime dependencies F44 shipped with (pygame-ce only; Tk is stdlib): F45 adds none
# (PR-F45-23).
F44_DEPENDENCIES = ["pygame-ce>=2.5.2,<2.6"]


def test_ac_f45_47_studio_loads_no_pygame_after_use(studio_game):
    result = subprocess.run([sys.executable, "-c", STUDIO_CHILD, str(studio_game)], cwd=REPO,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    if result.stdout.strip() == "NO-DISPLAY":
        pytest.skip("no display for Tk")
    assert result.stdout.strip() == "[]"


def test_ac_f45_47_no_dependency_added():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["dependencies"] == F44_DEPENDENCIES

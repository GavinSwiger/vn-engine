"""F40 W1: the developer console wired into the game (``specs/F40-dev-console/04-technical.md``
§1, §3, §7.1, §7.5, §7.6). AC-F40-01, -02, -03, -05, -11, -12, -24, -26, -29, -35 (AC-F40-04
and the real build's needle scan are in ``tests/tools/build/test_real_build.py``).

The launches are in process (``scripted_app``: fake frame clock, hidden window) with the
console factory ``engine/__main__.py`` passes; Studio's stdin is fed through F39's ``Feed``."""

import ast
import functools
import io
import json
import time
from pathlib import Path

import pygame
import pytest

from engine import __main__ as entry
from engine.app import bootstrap, cli
from engine.app.text_check import contrast_ratio
from engine.core.editorreport import REPORT_MARKER
from engine.core.startvalues import StartOptions
from engine.tools.console import install_console, panel, texts
from engine.tools.console.console import DevConsole
from engine.tools.console.model import Tab
from engine.tools.editor.preview import CONSOLE
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.shell import Mode
from tests.app.test_hot_reload_wiring import Child, Feed, reload
from tests.app.test_saves_service import at_line, line_text, play, wait
from tests.fakes.loop import post_key

pytestmark = pytest.mark.display

REPO = Path(__file__).resolve().parents[2]
CONFIG = """[game]
id = "f40-lantern"
title = "Lantern Test"
version = "1.0"

[saves]
autosave_quit = false
"""
SCRIPT = """\
image bg sky = "#a0a0ff"
default trust = 0
default met = False
label start:
    scene bg sky
    "L1"
    "L2"
    call side
    "L3"
    return
label side:
    "S1"
    "S2"
    return
label garden:
    "G1"
    "G2"
"""


def make_game(tmp_path: Path) -> Path:
    root = tmp_path / "game"
    (root / "script").mkdir(parents=True)
    (root / "config.toml").write_text(CONFIG, encoding="utf-8")
    (root / "script" / "main.vns").write_text(SCRIPT, encoding="utf-8")
    return root


def launch(session, game: Path, script, *, title: bool = False, release: bool = False,
           console=install_console, editor_report: bool = False, last: int = 500) -> dict:
    out = play(session, script, last=last)
    out["code"] = bootstrap.launch(
        game, release=release, bench_seconds=None, log_level_override=None,
        pygame_warning=None, editor_report=editor_report, console=console,
        start=None if title else StartOptions(label="start"))
    assert out["done"], out
    return out


def text(value: str) -> None:
    pygame.event.post(pygame.event.Event(pygame.TEXTINPUT, text=value))


def press(key: int, mod: int = 0):
    post_key(key, mod)
    yield
    yield


def jump_by_keys(label: str):
    """The Jump tab, its filter, Enter (the first row matching ``label``)."""
    yield from press(pygame.K_2, pygame.KMOD_CTRL)
    text(label)
    yield
    yield from press(pygame.K_RETURN)


def advance_to(app, line: str):
    for _ in range(300):
        if at_line(app, line):
            return
        post_key(pygame.K_SPACE)
        yield
        yield
    raise AssertionError(f"never reached {line!r}: at {line_text(app)!r}")


def answers(out: bytes) -> list[dict]:
    marker = REPORT_MARKER.encode("ascii") if isinstance(REPORT_MARKER, str) else REPORT_MARKER
    found = []
    for raw in out.splitlines():
        if raw.startswith(marker):
            data = json.loads(raw[len(marker):].strip())
            if data.get("event") == "console":
                found.append(data)
    return found


def message(do: str, **fields: str) -> bytes:
    return json.dumps({"v": 1, "msg": "console", "do": do, **fields},
                      separators=(",", ":")).encode("ascii") + b"\n"


# --- AC-F40-01 — F12 opens; Esc and F12 close; it reopens as it was ---------------------------

def test_ac_f40_01_f12_opens_esc_and_f12_close_and_it_reopens_as_left(
        tmp_path, scripted_app, user_roots):
    def script(app, out):
        yield from wait(lambda: at_line(app, "L1"))
        console = app.console
        out["type"] = type(console)
        yield from press(pygame.K_F12)
        out["opened"] = console.open
        yield from press(pygame.K_2, pygame.KMOD_CTRL)
        text("gar")
        yield
        yield from press(pygame.K_ESCAPE)
        out["after_esc"] = console.open
        yield from press(pygame.K_F12)
        model = console._model
        out["reopened"] = (console.open, model.tab, model.filters[Tab.JUMP].text)
        yield from press(pygame.K_F12)
        out["after_f12"] = console.open

    out = launch(scripted_app, make_game(tmp_path), script)
    assert out["type"] is DevConsole
    assert out["opened"] is True
    assert out["after_esc"] is False
    assert out["reopened"] == (True, Tab.JUMP, "gar")
    assert out["after_f12"] is False


# --- AC-F40-02 — nothing in a --release run -----------------------------------------------------

def test_ac_f40_02_f12_does_nothing_in_a_release_run(tmp_path, scripted_app, user_roots,
                                                      monkeypatch):
    made = []

    def factory(app):
        made.append(app)
        return install_console(app)

    def script(app, out):
        yield from wait(lambda: at_line(app, "L1"))
        before = list(app.screens)
        yield from press(pygame.K_F12)
        out["slot"] = app.console
        out["same"] = list(app.screens) == before and at_line(app, "L1")

    out = launch(scripted_app, make_game(tmp_path), script, release=True, console=factory)
    assert made == [] and out["slot"] is None and out["same"]
    logs = [p for p in user_roots.home.parent.rglob("*.log")]
    assert logs and not [p for p in logs if "console" in p.read_text(encoding="utf-8")]
    # The CLI drops the factory for --release.
    launched = []
    monkeypatch.setattr(cli, "_launch", lambda game_dir, **kw: launched.append(kw) or 0)
    assert cli.main(["run", "--release"], console=factory) == 0
    assert launched[-1]["console"] is None


# --- AC-F40-03 — app never imports the console; __main__ hands it in only in dev -----------------

def test_ac_f40_03_app_never_imports_the_console_and_main_hands_it_in_dev_only(monkeypatch):
    def imports(path: Path) -> list[tuple[str, str]]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                found.append((node.module, ""))
            elif isinstance(node, ast.Import):
                found += [(alias.name, "") for alias in node.names]
        return found

    for path in (REPO / "engine" / "app").rglob("*.py"):
        assert not [m for m, _ in imports(path) if m.startswith("engine.tools")], path
    main = ast.parse((REPO / "engine" / "__main__.py").read_text(encoding="utf-8"))
    owners = [fn.name for fn in main.body if isinstance(fn, ast.FunctionDef)
              for node in ast.walk(fn)
              if isinstance(node, ast.ImportFrom) and node.module == "engine.tools.console"]
    assert owners == ["_console"]
    launched = []
    monkeypatch.setattr(cli, "_launch", lambda game_dir, **kw: launched.append(kw) or 0)
    assert cli.main(["run"], console=entry._console) == 0
    assert launched[-1]["console"] is entry._console
    assert cli.main(["run", "--release"], console=entry._console) == 0
    assert launched[-1]["console"] is None
    assert cli.launcher_main([]) == 0                          # main.py: never a console
    assert launched[-1]["console"] is None


# --- AC-F40-05 — modal: the game's input does nothing; skip and auto stop ------------------------

def test_ac_f40_05_open_console_blocks_game_input_and_stops_skip_and_auto(
        tmp_path, scripted_app, user_roots):
    def script(app, out):
        yield from wait(lambda: at_line(app, "L1"))
        skip_auto = app.skip_auto
        skip_auto.set_auto(True)
        yield from press(pygame.K_F12)
        out["auto"] = skip_auto.auto
        out["skipping"] = skip_auto.skipping
        for key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_LCTRL, pygame.K_a,
                    pygame.K_s, pygame.K_h, pygame.K_F5):
            yield from press(key)
        pygame.event.post(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1, flipped=False))
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(5, 5)))
        for _ in range(20):
            yield
        out["held"] = (line_text(app), app.screens.top is app.textbox, app.console.open,
                       skip_auto.auto)
        yield from press(pygame.K_F12)
        yield from advance_to(app, "L2")

    out = launch(scripted_app, make_game(tmp_path), script)
    assert out["auto"] is False and out["skipping"] is False
    assert out["held"] == ("L1", True, True, False)


# --- AC-F40-11 — Jump in a game ---------------------------------------------------------------

def test_ac_f40_11_jump_clears_the_call_stack_and_keeps_the_story_state(
        tmp_path, scripted_app, user_roots):
    def script(app, out):
        yield from advance_to(app, "S1")
        interp = app.story.interp
        out["stack_before"] = len(interp.call_stack)
        out["before"] = (dict(interp.G), interp.stage, interp.audio)
        yield from press(pygame.K_F12)
        yield from jump_by_keys("garden")
        yield from wait(lambda: line_text(app) == "G1")
        yield
        out["after"] = (dict(interp.G), interp.stage, interp.audio)
        out["stack_after"] = len(interp.call_stack)
        out["header"] = app.console._model.header
        out["open"] = app.console.open
        yield from press(pygame.K_F12)
        yield from advance_to(app, "G2")

    out = launch(scripted_app, make_game(tmp_path), script)
    assert out["stack_before"] == 1 and out["stack_after"] == 0
    assert out["after"] == out["before"]
    assert out["open"] is True and "garden" in out["header"]


# --- AC-F40-12 — Jump on the title starts a new game there ------------------------------------

def test_ac_f40_12_jump_on_the_title_starts_a_new_game_at_the_label(
        tmp_path, scripted_app, user_roots):
    def script(app, out):
        yield from wait(lambda: app.shell is not None and app.shell.mode is Mode.TITLE
                        and any(isinstance(s, TitleScreen) for s in app.screens))
        for _ in range(5):
            yield
        yield from press(pygame.K_F12)
        out["header"] = app.console._model.header
        yield from jump_by_keys("garden")
        yield from wait(lambda: line_text(app) == "G1")
        interp = app.story.interp
        out["game"] = (app.shell.mode, interp.G.get("trust"), interp.G.get("met"),
                       any(isinstance(s, TitleScreen) for s in app.screens),
                       interp.start)

    out = launch(scripted_app, make_game(tmp_path), script, title=True)
    assert out["header"] == texts.HEADER_NO_STORY
    assert out["game"] == (Mode.GAME, 0, False, False, None)


# --- AC-F40-24 — the panel's look; never in a thumbnail -----------------------------------------

def test_ac_f40_24_panel_geometry_colors_and_never_in_a_thumbnail(
        tmp_path, scripted_app, user_roots):
    assert panel.PANEL == (64, 48, 1152, 480) and panel.BORDER == 2 and panel.ROW_H == 32
    assert panel.PANEL_COLOR == (0x14, 0x14, 0x14, 242)
    base = panel.PANEL_COLOR[:3]
    # 01 §6.1's ratios are a little high (16.2, 7.0, 7.5 and 10.5 by WCAG's formula); every
    # pair still meets AAA's 7:1.
    assert contrast_ratio(panel.TEXT_COLOR, base) >= 16
    assert contrast_ratio(panel.SECONDARY_COLOR, base) >= 7
    assert contrast_ratio(panel.ERROR_COLOR, base) >= 7
    assert contrast_ratio(panel.TEXT_COLOR, panel.SELECTED_COLOR) >= 10

    def script(app, out):
        yield from wait(lambda: at_line(app, "L1"))
        yield from press(pygame.K_F12)
        out["open"] = app.console.open
        app.shell.capture_scene(lambda picture: out.setdefault("picture", picture))
        yield
        yield

    out = launch(scripted_app, make_game(tmp_path), script)
    assert out["open"] is True
    picture = out["picture"]
    assert picture is not None
    r, g, b, *_ = picture.get_at((160, 72))                      # the panel's middle
    assert (r, g, b) == (0xA0, 0xA0, 0xFF)                       # the scene, no console


# --- AC-F40-26 — Studio's console messages -------------------------------------------------------

def test_ac_f40_26_stdin_console_messages_act_and_answer_once(
        tmp_path, scripted_app, user_roots, monkeypatch, capsysbinary):
    feed = Feed()
    stdin = io.BufferedReader(feed)
    monkeypatch.setattr(bootstrap, "_editor_input", lambda: stdin)

    def settle(n: int = 30):
        for _ in range(n):
            time.sleep(0.005)
            yield

    def script(app, out):
        yield from wait(lambda: at_line(app, "L1"))
        feed.send(message("open"))
        yield from settle()
        out["opened"] = app.console.open
        feed.send(b'{"v":1,"msg":"console","do":"set","name":"trust"}\n')       # malformed
        feed.send(message("set", name="trust", value="'" + "x" * 5000 + "'"))  # over 4 KiB
        feed.send(message("set", name="trust", value="5"))
        yield from settle()
        out["trust"] = app.story.interp.G["trust"]
        feed.send(message("jump", label="garden"))
        yield from wait(lambda: line_text(app) == "G1")
        yield from settle()
        feed.send(message("values"))
        yield from settle()

    capsysbinary.readouterr()
    try:
        out = launch(scripted_app, make_game(tmp_path), script, editor_report=True)
    finally:
        feed.end()
    got = answers(capsysbinary.readouterr().out)
    assert out["opened"] is True and out["trust"] == 5
    assert [(a["do"], a["ok"]) for a in got] == [("open", True), ("set", True),
                                                 ("jump", True), ("values", True)]
    assert got[1]["text"] == "trust is now 5." and got[2]["text"] == "Jumped to garden."
    assert got[3]["story"] is True and ["trust", "5"] in got[3]["values"]


# --- AC-F40-29 — F39 reload keeps a console change; the console is closed after ----------------

def test_ac_f40_29_reload_after_a_console_set_resumes_with_the_value(
        tmp_path, user_roots, scripted_app, monkeypatch, capsysbinary):
    monkeypatch.setattr(bootstrap, "launch",
                        functools.partial(bootstrap.launch, console=install_console))
    game = make_game(tmp_path)
    old = Child(scripted_app, monkeypatch, capsysbinary, game, start=True)

    def set_then_reload(app, child):
        yield from wait(lambda: at_line(app, "L1"))
        yield from press(pygame.K_F12)
        child.feed.send(message("set", name="trust", value="7"))
        for _ in range(40):
            time.sleep(0.005)
            yield
        child.was_open = app.console.open
        yield from reload(app, child)

    old.run(set_then_reload)
    assert old.code == 0 and old.was_open
    assert [kind for kind in old.kinds()][-1] == "state"
    assert [p.text for k, p in old.events if k == CONSOLE] == ["trust is now 7."]
    frame = old.frame()
    from engine.tools.editor import hotreload as studio

    argv, stdin = studio.restart(["python", "-m", "engine", "run", str(game),
                                  "--report-to-editor"], frame)
    new = Child(scripted_app, monkeypatch, capsysbinary, game, frame=stdin)

    def resumed(app, child):
        yield from wait(lambda: line_text(app) == "L1")
        child.trust = app.story.interp.G["trust"]
        child.console = (app.console is not None, app.console.open)
        app.request_quit(force=True)
        yield

    new.run(resumed)
    assert new.code == 0
    assert new.trust == 7 and new.console == (True, False)


# --- AC-F40-35 — release absence ---------------------------------------------------------------

class Recorder:
    """A filled slot that records every call."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def holds_story(self) -> bool:
        self.calls.append("holds_story")
        return True

    def key(self, event) -> bool:
        self.calls.append("key")
        return True

    def frame(self) -> None:
        self.calls.append("frame")

    def draw(self, canvas) -> None:
        self.calls.append("draw")

    def studio(self, request) -> None:
        self.calls.append("studio")


def test_ac_f40_35_console_absent_unless_dev_and_filled(
        tmp_path, scripted_app, user_roots, monkeypatch, capsysbinary):
    # The needle and the console classes live only under engine/tools/.
    needle = "One line of Python, like a $ line"
    for path in (REPO / "engine").rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith("engine/tools/"):
            continue
        body = path.read_text(encoding="utf-8")
        assert needle not in body and "class DevConsole" not in body, rel
        assert "class ConsoleModel" not in body and "class ConsolePanel" not in body, rel
    assert needle in texts.CODE_HINT

    feed = Feed()
    stdin = io.BufferedReader(feed)
    monkeypatch.setattr(bootstrap, "_editor_input", lambda: stdin)
    recorder = Recorder()

    def script(app, out):
        yield from wait(lambda: at_line(app, "L1"))
        app.console = recorder                         # a release App with a filled slot
        for do, fields in (("open", {}), ("values", {}), ("set", {"name": "trust",
                                                                    "value": "3"}),
                           ("jump", {"label": "garden"})):
            feed.send(message(do, **fields))
        yield from press(pygame.K_F12)
        for _ in range(30):
            time.sleep(0.005)
            yield
        out["trust"] = app.story.interp.G["trust"]
        app.console = None
        yield from advance_to(app, "L2")

    capsysbinary.readouterr()
    try:
        out = launch(scripted_app, make_game(tmp_path), script, release=True,
                     editor_report=True, console=None)
    finally:
        feed.end()
    assert recorder.calls == [] and out["trust"] == 0
    assert answers(capsysbinary.readouterr().out) == []
    logs = list(user_roots.home.parent.rglob("*.log"))
    assert logs and not [p for p in logs if "onsole" in p.read_text(encoding="utf-8")]

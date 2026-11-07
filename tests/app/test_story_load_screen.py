"""The story load inside the frame loop (F02 checklist step 10; 04-technical.md §5.3, §7.9).

AC-F02-43 (script errors on the error screen), 44 (script text on every channel: rows F1–F3;
F4's seeded corpus is checked message by message in ``tests/script``), 62 (a clean story
launches to the placeholder; no story gives W01), 63 (the window keeps responding while
loading), 65 (the bench starts after loading), 66 (imports and file access).

Launches run in-process on a fake clock (``scripted_app``); the loader keeps its real clock,
so its slices are real 50 ms slices. AC-63's frame intervals need real time, so that test
drives an ``App`` with a ``FakeWindow`` and the real frame limiter.
"""

import ast
import gc
import math
import re
import shutil
import sys
import time
from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap
from engine.app.app import App
from engine.app.loading import StoryLoadScreen, story_load_screen
from engine.app.text_check import TextLaunchCheck
from engine.core.config_schema import Config
from engine.core.constants import MB
from engine.core.paths import GamePaths
from engine.core.timing import BenchRecorder, GameTime
from engine.render.assets import AssetManager
from engine.script import ScriptErrorGroup, StoryLoader, load_story
from engine.script.program import Program
from engine.ui.builtin.error import ErrorScreen
from engine.ui.builtin.placeholder import PlaceholderScreen
from engine.ui.builtin.title_screen import TitleScreen
from tests.fakes.fake_window import FakeWindow
from tests.fakes.first_launch import answer_name_question
from tests.fakes.loop import post_key, post_quit
from tests.fakes.privacy import capture_channels, check_p
from tests.fakes.spy_window import SpyWindow
from tests.script.conftest import load_gen_corpus

pytestmark = pytest.mark.display

REPO = Path(__file__).resolve().parent.parent.parent
F02 = REPO / "tests" / "fixtures" / "F02"
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} ")
W01 = "No story found: script/main.vns doesn't exist."
CONFIG = '[game]\ntitle = "Paper Lanterns"\nversion = "0.1.0"\n'

PRIYA_STEP4 = (
    "The script has 3 problems:\n"
    "\n"
    "script/chapter1.vns, line 3, column 10: this line uses curly quotes “ ” around the text. "
    'Put the text between straight quotes "like this". Curly quotes inside the text are fine.\n'
    "        hana “You came!”\n"
    "\n"
    'script/chapter1.vns, line 4: "jmup" is not a statement. Did you mean "jump"?\n'
    "        jmup bridge\n"
    "\n"
    'script/chapter1.vns, line 5: no character named "hnaa". Did you mean "hana"?\n'
    '        hnaa "Hi."')


@pytest.fixture
def session(scripted_app):
    scripted_app.quit_frame = 12
    return scripted_app


@pytest.fixture
def channels(monkeypatch):
    with capture_channels(monkeypatch) as found:
        yield found


@pytest.fixture(scope="module")
def corpus_50k(tmp_path_factory) -> Path:
    """The 50,000-word corpus of 06 §5.10 (a game root holding ``script/``)."""
    out = tmp_path_factory.mktemp("corpus") / "c50k"
    load_gen_corpus().main(["--words", "50000", "--files", "10", "--seed", "1",
                            "--out", str(out)])
    return out


def launch(game: Path, *, bench: float | None = None, release: bool = False) -> int:
    return bootstrap.launch(game, release=release, bench_seconds=bench,
                            log_level_override=None, pygame_warning=None)


# F10 step 6: these tests are about loading and playing the story, so their games skip
# F10's title (PR-F10-27): launch starts the first game at once, as before the title
# existed, and the story's end quits. ``title=True`` keeps the title.
NO_TITLE = "[title]\nenabled = false\n"


def make_game(parent: Path, script: dict[str, str] | Path | None, *,
              name: str = "game", title: bool = False) -> Path:
    """A game folder with ``config.toml`` and ``script/`` (files, a folder to copy, or
    None for no ``script/``). Without ``title`` the config turns F10's title off."""
    root = parent / name
    root.mkdir(parents=True)
    (root / "config.toml").write_text(CONFIG if title else CONFIG + NO_TITLE,
                                      encoding="utf-8")
    if isinstance(script, Path):
        shutil.copytree(script, root / "script")
    elif script is not None:
        for ref, text in script.items():
            path = root / "script" / ref
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    return root


def copy_example(dest: Path) -> Path:
    game = Path(shutil.copytree(REPO / "game", dest,
                                ignore=shutil.ignore_patterns("logs", "persistent",
                                                              "settings", "characters")))
    answer_name_question(game)               # F30 s6: no first-launch name question
    return game


def records(log_file: Path) -> list[tuple[str, str, str]]:
    return [(line[24:31].strip(), line[32:39].strip(), line[40:])
            for line in log_file.read_text(encoding="utf-8").splitlines()
            if TIMESTAMP.match(line)]


def frame_of(session) -> int:
    return session.limiters[-1].frame if session.limiters else 0


# --- AC-F02-62: a clean story launches to the placeholder --------------------------------------

def test_ac62_clean_story_launches_to_the_placeholder(tmp_path, user_roots, session):
    game = copy_example(tmp_path / "game")
    drawn, built, reads = [], [], []
    real_draw = StoryLoadScreen.draw
    real_build = bootstrap.build_initial_screens
    real_read = GamePaths.read_file

    def draw(self, canvas):
        real_draw(self, canvas)
        width, height = canvas.surface.get_size()
        drawn.append((frame_of(session), self.app.loading, [type(s) for s in self.app.screens],
                      tuple(canvas.surface.get_at((width // 2, height // 2)))[:3]))

    def build(app):
        built.append(frame_of(session))
        return real_build(app)

    def read_file(self, ref, **kwargs):
        reads.append((frame_of(session), ref))
        return real_read(self, ref, **kwargs)

    session.quit_frame = 70
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(StoryLoadScreen, "draw", draw)
        mp.setattr(bootstrap, "build_initial_screens", build)
        mp.setattr(GamePaths, "read_file", read_file)
        assert launch(game) == 0
    app = session.apps[-1]
    assert drawn[0] == (1, True, [StoryLoadScreen], (0, 0, 0))
    assert isinstance(app.program, Program)
    assert app.loading is False
    assert len(built) == 1
    # F10 step 6: a clean story now shows F10's title (AC-F03-70 as amended by F10, G13).
    assert [type(s) for s in app.screens] == [TitleScreen]
    loaded = [r for r in records(game / "logs" / "latest.log") if r[2].startswith("Loaded story:")]
    assert len(loaded) == 1 and loaded[0][:2] == ("INFO", "script")
    script_reads = [(frame, ref) for frame, ref in reads if ref.startswith("script/")]
    assert {ref for _, ref in script_reads} == {"script/main.vns", "script/chapter1.vns",
                                                "script/routes/daichi.vns",
                                                "script/endings.vns",
                                                "script/bonus.vns"}      # F31 s5
    # Nothing reads the story again while the 60 or more frames after loading run.
    assert max(frame for frame, _ in script_reads) <= built[0] <= 10
    assert not [r for r in records(game / "logs" / "latest.log")
                if r[0] in ("WARNING", "ERROR")]


def test_ac62_no_story_shows_the_placeholder_with_w01(tmp_path, user_roots, session):
    game = make_game(tmp_path, None)
    assert launch(game) == 0
    app = session.apps[-1]
    assert [type(s) for s in app.screens] == [PlaceholderScreen]
    assert app.program is None and app.loading is False
    problems = [r for r in records(game / "logs" / "latest.log") if r[0] in ("WARNING", "ERROR")]
    assert problems == [("WARNING", "script", W01)]


# --- AC-F02-43: script errors on the error screen ----------------------------------------------

def test_ac43_script_errors_on_the_error_screen(tmp_path, user_roots, session, channels, capfd):
    game = make_game(tmp_path, F02 / "walkthrough" / "priya_step4")
    built = []
    session.quit_frame = 10_000
    session.at(5, lambda app: post_key(pygame.K_c))
    session.at(6, lambda app: post_key(pygame.K_ESCAPE))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(bootstrap, "build_initial_screens", lambda app: built.append(app) or [])
        assert launch(game) == 1
    app = session.apps[-1]
    assert frame_of(session) == 6                       # Esc closed it, not a quit
    assert isinstance(app.screens.top, ErrorScreen) and len(app.screens) == 1
    assert app.program is None and app.loading is False
    assert built == []
    assert app.screens.top.message == PRIYA_STEP4
    texts = [c.text for c in channels.draws]
    assert not [t for t in texts if "^" in t]
    # F01's error screen fits about 9 wrapped lines and cuts the rest with a notice that
    # points to the log; what it draws is the start of the text, word-wrapped.
    def words(text: str) -> str:
        return " ".join(text.split())

    message_draws = [t for t in texts if t.startswith("The script has 3 problems:")]
    assert message_draws
    assert words(PRIYA_STEP4).startswith(words(message_draws[-1]))
    assert len(words(message_draws[-1])) > len(words(PRIYA_STEP4.split("\n\n")[1]))
    # Every line is in the copied details (C) and in the log.
    assert len(channels.clipboard) == 1
    for line in PRIYA_STEP4.splitlines():
        assert line in channels.clipboard[0], line
    log = (game / "logs" / "latest.log").read_text(encoding="utf-8")
    assert "Traceback" not in log and "Traceback" not in capfd.readouterr().err
    errors = [m for level, area, m in records(game / "logs" / "latest.log")
              if level == "ERROR" and area == "script"]
    assert errors[0].startswith("script/chapter1.vns, line 3, column 10: this line uses curly")
    assert errors[1:3] == ["        hana “You came!”", "    " + " " * 9 + "^"]
    assert records(game / "logs" / "latest.log")[-1][2] == "Clean shutdown (exit code 1)"


def test_ac43_one_problem_and_sixty_problems(tmp_path):
    one = make_game(tmp_path, {"main.vns": 'label start:\n    jmup bridge\n'}, name="one")
    text = ScriptErrorGroup.from_result(load_story(GamePaths.for_game(one))).format()
    assert text.startswith("The script has 1 problem:\n\n")
    many = make_game(tmp_path, {"main.vns": "label start:\n" + "    jmup x\n" * 60},
                     name="many")
    text = ScriptErrorGroup.from_result(load_story(GamePaths.for_game(many))).format()
    assert text.startswith("The script has 60 problems:")
    assert text.endswith("\n\n…and 10 more problems. Fix these and launch again.")


# --- AC-F02-44: script text in output is escaped, redacted, and bounded ------------------------

CLEAN_STORY = 'label start:\n    "Hi."\n    return\n'


def _all_channels(channels, capfd, game: Path) -> list[str]:
    texts = channels.texts() + [capfd.readouterr().err]
    texts += [p.read_text(encoding="utf-8", errors="replace") for p in game.rglob("*.log")]
    return texts


def test_ac44_f1_file_names_are_escaped(tmp_path, user_roots, session, channels, capfd):
    files = {"main.vns": CLEAN_STORY, "a\u202eb.vns": CLEAN_STORY}
    if sys.platform != "win32":
        files["\x1b[31mx.vns"] = CLEAN_STORY
    game = make_game(tmp_path, files)
    assert launch(game) == 0
    w02 = [m for level, area, m in records(game / "logs" / "latest.log")
           if level == "WARNING" and area == "script"]
    assert len(w02) == len(files) - 1
    assert any("script/a\\u202eb.vns is not included" in m for m in w02)
    if sys.platform != "win32":
        assert any("script/\\x1b[31mx.vns is not included" in m for m in w02)
    for text in _all_channels(channels, capfd, game):
        assert "\u202e" not in text and "\x1b" not in text


def test_ac44_f2_long_names_are_bounded(tmp_path, user_roots, session, channels, capfd):
    long = "l" + "o" * 8999
    wrong = "l" + "o" * 8998 + "x"
    name = "v" + "a" * 4999
    places = "label dup:\n    return\n" * 500
    calls = "    call missing\n" * 500
    main = (f'label start:\n    jump {wrong}\n    $ from __future__ import {name}\n{calls}    return\n'
            f"label {long}:\n    return\nlabel {long}:\n    return\n{places}")
    game = make_game(tmp_path, {"main.vns": main})
    session.at(5, lambda app: post_key(pygame.K_c))
    assert launch(game) == 1
    screen = session.apps[-1].screens.top
    assert isinstance(screen, ErrorScreen)
    group = ScriptErrorGroup.from_result(load_story(GamePaths.for_game(game)))
    codes = {error.code for error in group.errors}
    assert {"E25", "E43", "E80"} <= codes, codes
    for error in group.errors:
        assert len(error.format()) <= 1000, error.code
    for code, name in (("E25", '"dup"'), ("E43", '"missing"')):
        text = next(e.format() for e in group.errors if e.code == code and name in e.format())
        assert re.search(r"and [\d,]+ more", text), text
    assert len(channels.clipboard) == 1
    for text in _all_channels(channels, capfd, game):
        assert "o" * 121 not in text and "a" * 121 not in text
    assert any("o" * 100 + "…" in text for text in channels.texts())


def test_ac44_f3_paths_in_source_lines_are_redacted(tmp_path, user_roots, session, channels,
                                                    capfd):
    home = user_roots.home
    secret = str(home / "x")
    line = "    $ x = " + " " * 102 + 'r"' + secret + '" +)'
    assert line.index(secret) + 1 == 115
    game = make_game(home, {"main.vns": f"label start:\n{line}\n    return\n"}, name="My Game")
    session.at(5, lambda app: post_key(pygame.K_c))
    assert launch(game) == 1
    texts = _all_channels(channels, capfd, game)
    assert len(channels.clipboard) == 1
    assert any("~" + sep + "x" in text for text in texts for sep in "\\/")
    check_p(texts, home=home, game=game)
    for text in texts:
        lowered = text.lower()
        for size in range(3, 8):
            assert "qauser7"[:size] not in lowered and "qauser7"[-size:] not in lowered


# --- AC-F02-63: the window keeps responding while loading --------------------------------------

def _loading_app(game: Path, window: FakeWindow) -> App:
    """An App on the real clock and frame limiter with a story load on its stack."""
    paths = GamePaths.for_game(game)
    assets = AssetManager(paths, budget_bytes=64 * MB, scale_filter="smooth", time=GameTime(),
                          format_source=window.framebuffer)
    app = App(config=Config(), paths=paths, window=window, assets=assets, log=None, dev=True,
              bench_seconds=None)
    app.screens.replace_all([story_load_screen(
        app, paths, on_ready=lambda a: [PlaceholderScreen(title="t", engine_version="0")])])
    return app


AC63_RUNS = 3                        # runs allowed before a frame over 0.1 s fails AC-63


def _responsive_load(corpus: Path) -> None:
    """AC-63: every frame interval while loading ``corpus`` is ≤ 0.1 s (real clock).

    A wall-clock max on a shared machine (``pytest -n``) can catch the OS taking the CPU
    away: a slice ends a step past its 50 ms (the story's installs and F30's scan are sliced
    since, so no frame does a whole-story walk on top of a full slice), and a step slowed by
    preemption puts a frame over. A run over 0.1 s is run again from scratch, up to
    ``AC63_RUNS`` in all, and every run is held to the same 0.1 s; a real overrun (a slice
    that ignores its budget, unsliced work in a frame) fails every run."""
    worst: list[float] = []
    for _ in range(AC63_RUNS):
        worst.append(_responsive_run(corpus))
        if worst[-1] <= 0.1:
            break
    assert worst[-1] <= 0.1, worst


def _responsive_run(corpus: Path) -> float:
    """One fresh load of ``corpus`` (F11 pressed in frame 2); returns the longest frame
    interval."""
    # A launch starts from a fresh process with a small heap. Here the heap holds whatever
    # earlier tests and the in-process corpus generator left, and a full collection already
    # due from that would land in some loading frame (150–200 ms at 1,000,000 words, since
    # it also scans the objects loaded so far). Collect first so the run starts as a launch
    # does; the loader itself pauses the collector inside its slices (F02 Step 11).
    gc.collect()
    pygame.init()
    pygame.event.clear()
    try:
        window = FakeWindow()
        app = _loading_app(corpus, window)
        starts: list[float] = []
        seen: dict[str, object] = {}
        real_wait = app._limiter.wait

        def wait() -> float:
            start = real_wait()
            starts.append(start)
            if len(starts) == 2:
                seen["loading_at_f11"] = app.loading
                post_key(pygame.K_F11)
            if not app.loading and "quit" not in seen:
                seen["quit"] = len(starts)
                post_quit()
            return start

        app._limiter.wait = wait
        assert app.run() == 0
    finally:
        pygame.quit()
    assert seen["loading_at_f11"] is True
    assert window.calls.count("set_fullscreen") == 1
    assert isinstance(app.program, Program)
    intervals = [b - a for a, b in zip(starts, starts[1:])]
    assert len(intervals) >= 3, intervals
    return max(intervals)


def test_ac63_frames_keep_coming_while_loading(corpus_50k):
    _responsive_load(corpus_50k)


@pytest.mark.slow
def test_ac63_one_million_words(tmp_path):
    out = tmp_path / "c1m"
    load_gen_corpus().main(["--words", "1000000", "--files", "100", "--seed", "1",
                            "--out", str(out)])
    _responsive_load(out)


def test_ac63_quit_and_f11_during_loading(tmp_path, user_roots, session, corpus_50k):
    game = make_game(tmp_path, corpus_50k / "script")
    seen = {}

    def mid_load(app):
        seen["loading"] = app.loading
        seen["posted"] = time.perf_counter()
        post_key(pygame.K_F11)
        post_quit()

    session.quit_frame = 10_000
    session.at(2, mid_load)
    assert launch(game) == 0
    assert time.perf_counter() - seen["posted"] < 1.0
    assert seen["loading"] is True
    assert ("set_fullscreen", True) in SpyWindow.log
    assert records(game / "logs" / "latest.log")[-1] == ("INFO", "app",
                                                         "Clean shutdown (exit code 0)")


# --- AC-F02-65: the bench starts after loading -------------------------------------------------

def test_ac65_bench_starts_after_loading(tmp_path, user_roots, session, corpus_50k):
    game = make_game(tmp_path, corpus_50k / "script")
    slices, created = [], []
    real_step = StoryLoader.step
    real_init = BenchRecorder.__init__

    last_slice_at = []

    def step(self, budget_s):
        slices.append(frame_of(session))
        last_slice_at.append(session.limiters[-1].clock.now)
        if len(slices) < 40:
            real_step(self, 0.0)
            return False
        return real_step(self, math.inf)

    def init(self, **kwargs):
        created.append((frame_of(session), session.apps[-1].loading, kwargs["start"]))
        real_init(self, **kwargs)

    checked = []                                   # F05: the dev text check's frames
    real_check = TextLaunchCheck.step

    def check_step(self):
        checked.append(frame_of(session))
        return real_check(self)

    session.quit_frame = 10_000
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(StoryLoader, "step", step)
        mp.setattr(BenchRecorder, "__init__", init)
        mp.setattr(TextLaunchCheck, "step", check_step)
        assert launch(game, bench=1.0) == 0
    # Frame 1 presents black, frames 2–41 run the 40 slices, then (dev) F05's text check
    # runs in what is left of frame 41 and its own slices; the frame after its last starts
    # the bench.
    assert slices == list(range(2, 42))
    assert checked[0] >= 41
    assert [(frame, loading) for frame, loading, _ in created] == [(checked[-1] + 1, False)]
    bench = [m for _, _, m in records(game / "logs" / "latest.log") if m.startswith("Bench ")]
    assert len(bench) == 5
    measured = float(re.search(r"measured (\d+\.\d\d) s", bench[0]).group(1))
    assert 0.98 <= measured <= 1.05 and "warm-up 5.00 s excluded" in bench[0]
    # The warm-up (and so the measured second) starts after the frame of the last slice.
    assert created[0][2] > last_slice_at[-1]
    assert isinstance(session.apps[-1].program, Program)


# --- AC-F02-66: imports and file access -------------------------------------------------------

# The AC's list, plus the writes and checks that tests/script/test_script_imports.py scanned
# for before it was merged here (test-review-F02.md).
FILE_CALLS = {"open", "scandir", "listdir", "walk", "stat", "glob", "iterdir", "rglob",
              "read_text", "read_bytes", "write_text", "write_bytes", "fopen", "mkdir",
              "unlink", "remove", "rename", "exists", "is_file", "is_dir"}
FILE_MODULES = {"glob", "io", "os", "linecache", "tokenize", "pathlib", "shutil", "tempfile",
                "fileinput"}
# F23 SR-F23-02 splits minigame arguments with Python's own tokenizer (project decision,
# 2026-11-02). Only generate_tokens over a string is used; tokenize.open is still caught by
# the FILE_CALLS attribute check below.
ALLOWED = {("minigame.py", "tokenize")}


def _imported(tree: ast.AST, *, skip_type_checking: bool) -> list[tuple[int, str]]:
    """(line, module) of every import, leaving out ``if TYPE_CHECKING:`` blocks if asked."""
    skipped: set[int] = set()
    if skip_type_checking:
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
                skipped |= {id(inner) for stmt in node.body for inner in ast.walk(stmt)}
    found = []
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "engine":
                found.extend((node.lineno, f"engine.{alias.name}") for alias in node.names)
            else:
                found.append((node.lineno, node.module))
    return found


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_ac66_only_loading_imports_engine_script():
    engine = REPO / "engine"
    importers = []
    for path in sorted((engine / "app").rglob("*.py")):
        for _, name in _imported(_tree(path), skip_type_checking=True):
            if name == "engine.script" or name.startswith("engine.script."):
                importers.append(path.name)
    assert sorted(set(importers)) == ["loading.py"]
    for package in ("render", "ui", "audio", "persist"):
        for path in sorted((engine / package).rglob("*.py")):
            for line, name in _imported(_tree(path), skip_type_checking=False):
                assert not name.startswith("engine.script"), (path.name, line)


def test_ac66_script_package_uses_only_core_and_no_file_api():
    for path in sorted((REPO / "engine" / "script").rglob("*.py")):
        tree = _tree(path)
        for line, name in _imported(tree, skip_type_checking=False):
            assert not name.startswith("pygame"), (path.name, line)
            if name.startswith("engine."):
                assert name.startswith(("engine.core", "engine.script")), (path.name, line)
            if (path.name, name) not in ALLOWED:
                assert name.split(".")[0] not in FILE_MODULES, (path.name, line, name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in FILE_CALLS, (path.name, node.lineno)
            if isinstance(node, ast.Attribute) and node.attr in FILE_CALLS:
                # ast.walk is fine; os.walk is not.
                if node.attr == "walk" and ast.unparse(node.value) != "os":
                    continue
                assert False, (path.name, node.lineno, node.attr)


# --- v1 perf review: F05's dev text check runs after the title ---------------------------------

def test_the_dev_text_check_runs_after_the_title(tmp_path, user_roots, session, corpus_50k):
    game = make_game(tmp_path, corpus_50k / "script")
    checked: list[tuple[int, bool]] = []
    real_check = TextLaunchCheck.step

    def check_step(self):
        app = session.apps[-1]
        checked.append((frame_of(session), app.loading))
        return real_check(self)

    session.quit_frame = 10_000
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(TextLaunchCheck, "step", check_step)
        assert launch(game, bench=1.0) == 0
    # Every step runs once the load screen has handed over (loading over).
    assert checked and all(loading is False for _, loading in checked)

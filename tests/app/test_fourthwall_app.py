"""F30 step 4 in the window: the title bar and the fake crash (``04`` §6.1, §6.2; ``05``
SEC-F30-05, -09, -10; ``07`` I-6, I-11). AC-F30-17, 19, 20, 21, 22, 23, 24 (AC-F30-18, the
page's look, is in ``tests/ui/test_fake_crash.py``).

Every run is App A (``tests/fakes/text_app.Session``: the real ``App`` on a ``FakeWindow``,
fake 1/60 s frames, ``install_story``, lines shown at once) on a Template W-like game
(``06`` §0.3) in ``tmp_path``. The script generator runs at the start of each frame, before
its events, so a key posted at frame f is read in frame f. **c** is the crash's first drawn
frame: the screen is pushed by that frame's pump and drawn in it.

Frame counts are ± 1 (``06`` §0.3): the 0.5 s guard counts drawn, focused time from the
first update after frame c, so the first continue that works is read at c + 31 (the input
of frame c + 30 comes before that frame's update). The player's name is step 5: here every
``{username}`` shows its fallback word.
"""

import logging

import pygame
import pytest

from engine.app.fourthwall import display_title
from engine.runtime.commands import WaitDone, WindowTitle
from engine.ui.builtin.fake_crash import FakeCrashScreen
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.nav import InputKind
from tests.fakes.text_app import Session, make_text_game
from tests.fakes.username import no_real_username  # noqa: F401  (name guard, AC-F30-07)

pytestmark = pytest.mark.display

GAME_ID = "f30-template"
CONFIG = (f'[game]\nid = "{GAME_ID}"\ntitle = "Paper Test"\nversion = "1.0"\n\n'
          "[textbox]\ncps = 0\n\n[saves]\nautosave_quit = false\n")
L5, L7 = "Hello.", "I know who you are, {username}."   # the line's source text

@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def template_w(S: str) -> str:
    """Template W (06 §0.3) with S (``⏎`` separates statements) on line 6."""
    s = "".join(f"    {line}\n" for line in S.split("⏎"))
    return ('define hana = Character("Hana")\n'
            'image bg room = "#c8c8c8"\n'
            "label start:\n"
            "    scene bg room\n"
            f'    hana "{L5}"\n'
            f"{s}"
            '    hana "I know who you are, {username}."\n'
            '    hana "Goodbye."\n'
            '    "End."\n')


def game(tmp_path, name: str, script: str, *, config: str = "", title: bool = False):
    root = make_text_game(tmp_path / name, script=script)
    (root / "config.toml").write_text(("" if title else "[title]\nenabled = false\n")
                                      + CONFIG + config, encoding="utf-8")
    return root


def crash_up(s: Session) -> FakeCrashScreen | None:
    top = s.app.screens.top
    return top if isinstance(top, FakeCrashScreen) else None


def to_crash(s: Session):
    """Space every 6 frames (lines) until a crash is on top; returns c."""
    n = 0
    while crash_up(s) is None:
        if n % 6 == 0 and s.line_text() is not None and s.app.stage_screen.wait_kind is None:
            s.key(pygame.K_SPACE)
        n += 1
        yield
    return s.frame - 1


def to_frame(s: Session, frame: int):
    while s.frame < frame:
        yield


def spy_posts(s: Session) -> list:
    """Every ``WaitDone`` the story receives from now on, with its frame."""
    story = s.app.story
    real, seen = story.post, []

    def post(event):
        if isinstance(event, WaitDone):
            seen.append((s.frame, event.wait_id))
        real(event)

    story.post = post
    return seen


def spy_commands(s: Session) -> list:
    router = s.app.router
    real, seen = router.dispatch, []

    def dispatch(command):
        seen.append(command)
        real(command)

    router.dispatch = dispatch
    return seen


def pad(button: int) -> None:
    pygame.event.post(pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, button=button,
                                         instance_id=0))


# --- AC-F30-17 -----------------------------------------------------------------------------------

def test_ac_f30_17_the_window_title_on_screen(tmp_path, monkeypatch, caplog):
    script = ('define hana = Character("Hana")\nlabel start:\n    "Start."\n'
              '    effect window_title "TitleMarkQ"\n    hana "Here."\n    "Morning came."\n'
              '    ending lantern "Lantern End" "Morning"\n')
    root = game(tmp_path, "w", script, title=True)
    s = Session(root)
    calls: list[tuple[int, str]] = []
    real = type(s.app).set_title
    monkeypatch.setattr(type(s.app), "set_title",
                        lambda app, title: (calls.append((s.frame, title)), real(app, title)))
    out: dict = {}

    def title_ready():
        top = s.app.screens.top
        return isinstance(top, TitleScreen) and top.in_t >= 1.0 and not top.leaving

    def script_(s: Session):
        yield from s.until(title_ready)
        shell = s.app.shell
        out["launch"] = list(calls)
        shell.start_new_game()
        yield from s.until_line("Start.")
        assert calls[-1][1] == "Paper Test"                    # New Game: the game's title
        commands = spy_commands(s)
        s.key(pygame.K_SPACE)
        yield from s.until_line("Here.")
        frame = next(s.frame - 1 for c in commands if isinstance(c, WindowTitle))
        assert calls[-1] == (frame, "TitleMarkQ")             # the frame of the burst
        assert s.window.title == "TitleMarkQ"
        out["cp"] = s.app.story.checkpoint()
        before = len(calls)
        shell.open_game_menu(InputKind.KEYS)                  # a menu over the story
        for _ in range(5):
            yield
        shell.close_game_menu()
        for _ in range(30):
            yield
        assert len(calls) == before
        shell.return_to_title()
        yield from s.until(lambda: isinstance(s.app.screens.top, TitleScreen))
        assert s.window.title == "Paper Test"                  # before its first frame
        yield from s.until(title_ready)
        assert s.app.saves.load_state(out["cp"], origin="title", by=InputKind.KEYS)
        assert s.window.title == "Paper Test"                  # the load's reset ...
        yield
        assert s.window.title == "TitleMarkQ"                  # ... then the restore burst
        yield from s.until_line("Here.")
        n = 0
        while not title_ready():                               # the ending card, the end
            if n % 6 == 0 and s.line_text() is not None:
                s.key(pygame.K_SPACE)
            n += 1
            yield
        out["end"] = [t for _, t in calls]
        assert s.window.title == "Paper Test"

    with caplog.at_level(logging.DEBUG):
        s.play(script_, last=1500)
    assert set(t for _, t in out["launch"]) <= {"Paper Test"}
    assert out["end"][-3:] == ["TitleMarkQ", "Paper Test", "Paper Test"]   # card, then end
    # The title is cleaned where it is applied; nothing raises.
    for raw in ("a‮b", "a b", "a\u0085b", "a\u0007b", "\ud800", "\udcff"):
        shown = display_title(raw)
        assert len(shown) == len(raw) and all(
            ch == "�" for ch in shown if ch not in "ab"), repr(raw)
    assert display_title("x" * 300) == "x" * 100
    # Nothing writes or logs the script's title.
    assert not [r for r in caplog.records if "TitleMarkQ" in r.getMessage()]
    for path in root.rglob("*"):
        if path.is_file() and path.suffix != ".vns":
            assert b"TitleMarkQ" not in path.read_bytes(), path


# --- AC-F30-19 -----------------------------------------------------------------------------------

def _ignored_keys() -> None:
    """F5, F9, PageUp, the wheel, H, Tab, A, Ctrl, and a click on the letterbox side."""
    for key in (pygame.K_F5, pygame.K_F9, pygame.K_PAGEUP, pygame.K_h, pygame.K_TAB,
                pygame.K_a, pygame.K_LCTRL):
        Session.key(key)
    Session.event(pygame.MOUSEWHEEL, x=0, y=1, flipped=False, precise_x=0.0, precise_y=1.0,
                  touch=False, which=0)
    Session.mouse((640, 360), button=4)
    Session.mouse((1300, 100))                        # outside the canvas


def test_ac_f30_19_input_the_guard_the_continue_inputs_and_nothing_else(tmp_path):
    inputs = [("enter", lambda: Session.key(pygame.K_RETURN)),
              ("keypad enter", lambda: Session.key(pygame.K_KP_ENTER)),
              ("space", lambda: Session.key(pygame.K_SPACE)),
              ("esc", lambda: Session.key(pygame.K_ESCAPE)),
              ("pad a", lambda: pad(pygame.CONTROLLER_BUTTON_A)),
              ("pad b", lambda: pad(pygame.CONTROLLER_BUTTON_B)),
              ("left click", lambda: Session.mouse((640, 360), button=1)),
              ("right click", lambda: Session.mouse((640, 360), button=3))]
    root = game(tmp_path, "w", template_w("⏎".join(["effect crash"] * len(inputs))),
                config='[words]\nfake_crash_hint = "Do not close this window"\n')
    s = Session(root)
    out: dict = {"screens": set(), "notices": []}

    def watch():
        out["screens"].update(type(x).__name__ for x in s.app.screens)
        if crash_up(s) is not None:
            out["notices"].extend(v.text for v in s.app.shell.notices.views())

    def script(s: Session):
        posts = None
        for i, (name, continue_) in enumerate(inputs):
            if posts is None:
                yield from s.until(lambda: s.app.story is not None)
                posts = spy_posts(s)
            c = yield from to_crash(s)
            screen = crash_up(s)
            ready = c + 31                                  # c + 30, ± 1 (module docstring)
            for f in range(c + 1, c + 30 + 1):              # everything during the guard
                yield from to_frame(s, f)
                watch()
                if name == "enter":
                    s.key(pygame.K_RETURN)                  # on every guard frame
                if f == c + 5:
                    _ignored_keys()
                if name == "keypad enter" and f == c + 5:
                    s.event(pygame.WINDOWFOCUSLOST)         # 60 frames unfocused
                if name == "space" and f == c + 10:
                    s.key(pygame.K_RETURN)                  # held from c + 10 ...
                if name == "esc" and f == c + 10:
                    s.app.shell.notify("NoticeMark")
            if name == "keypad enter":
                yield from to_frame(s, c + 65)
                s.event(pygame.WINDOWFOCUSGAINED)
                ready = c + 65 + 26                         # 4 frames before, 26 after
                yield from to_frame(s, ready - 1)
                s.key(pygame.K_KP_ENTER)                    # one frame early: ignored
            if name == "space":
                yield from to_frame(s, c + 40)
                s.key_up(pygame.K_RETURN)                   # ... released at c + 40
                ready = c + 41
            yield from to_frame(s, ready)
            assert crash_up(s) is screen and not posts, (name, s.frame - c)
            continue_()
            yield
            assert crash_up(s) is not screen, name          # gone in that frame
            assert [f for f, _ in posts] == [ready], (name, posts)
            posts.clear()
        for _ in range(5):
            yield
        out["line"] = s.line_text()
        out["skip_auto"] = (s.app.skip_auto.skipping, s.app.skip_auto.auto)

    s.play(script, last=1500)
    # Nothing else happened: no menu, question, history, save, load, rollback, skip, auto.
    assert out["screens"] <= {"StageScreen", "TextboxScreen", "FakeCrashScreen"}
    assert out["line"] == L7, out["line"]
    assert out["skip_auto"] == (False, False) and out["notices"] == []
    assert not (root / "saves").exists() or not list((root / "saves").glob("*.vnsave"))


# --- AC-F30-20 .. 24 (written in step 5; lean where noted) ---------------------------------------

class _Persist:
    """A stand-in for F12's ``PersistentSync``: counts ``flush_now``; ``fail`` raises."""

    def __init__(self, s: Session) -> None:
        self.s, self.flushes, self.fail = s, [], None

    def flush_now(self, until=None):
        self.flushes.append(self.s.frame)
        if self.fail is not None:
            raise self.fail
        return True

    def __getattr__(self, name):
        return lambda *a, **k: None


def _persist_after_load(s: Session):
    """Install a ``_Persist`` once the load screen has handed over; returns it.

    Not as soon as the story exists: the load screen still warms the real sync's encoder
    after ``install_story`` (``_after_launch``), in what is left of the launch frame's real
    50 ms slice. On a busy machine that slice is used up and the warm-up runs in the next
    frame, on the stand-in (``None + float``: the load fails and the script never ends)."""
    yield from s.until(lambda: s.app.story is not None and not s.app.loading)
    s.app.persist = persist = _Persist(s)
    return persist


def _gray(s: Session) -> int:
    return s.px(10, 10)[0]


def test_ac_f30_20_still_with_one_cut_or_a_300_ms_fade(tmp_path):
    bg, page = 0xC8, 0x14
    for reduce in (False, True):
        root = game(tmp_path, f"r{reduce}", template_w("effect crash"),
                    config="[effects]\nreduce = true\n" if reduce else "")
        s = Session(root)
        out: dict = {}

        def script(s: Session):
            frames: list[tuple[int, int, bytes]] = []
            n = 0
            while crash_up(s) is None:
                if n % 6 == 0 and s.line_text() is not None \
                        and s.app.stage_screen.wait_kind is None:
                    s.key(pygame.K_SPACE)
                n += 1
                frames.append((s.frame - 1, _gray(s), s.snapshot()))
                yield
            c = s.frame - 1
            out["before"] = frames[-1][1]                    # frame c - 1: the story
            shots = {}
            for f in range(c, c + 61):
                yield from to_frame(s, f + 1)
                shots[f] = (_gray(s), s.snapshot())
            out["shots"] = {f - c: v for f, v in shots.items()}
            s.key(pygame.K_RETURN)
            after = []
            for _ in range(20):
                yield
                after.append(_gray(s))
            out["after"] = after
            out["line"] = s.line_text()

        s.play(script, last=900)
        shots = out["shots"]
        assert out["before"] == bg, reduce
        if not reduce:
            assert shots[0][0] == page                       # frame c: the full page
            assert len({shot for _, shot in shots.values()}) == 1   # c .. c + 60 identical
            assert out["after"][0] == bg                     # one cut back, no blend
        else:
            mid = (bg + page) / 2
            assert any(abs(shots[k][0] - mid) <= 0.03 * (bg - page) + 1 for k in (8, 9, 10)), \
                [shots[k][0] for k in range(0, 20)]
            assert len({shots[k][1] for k in range(19, 61)}) == 1   # opaque and still
            assert shots[19][0] == page
            assert out["after"][0] < bg and out["after"][-1] == bg   # an 18-frame fall
        assert out["line"] == L7


def test_ac_f30_21_honest_and_escapable(tmp_path, monkeypatch):
    # Lean: 120 shown frames (not 600) with input spam and 60 frames unfocused; the quit row
    # asks the shell's guard directly (the quit Auto save's picture is AC-F30-22's
    # capture_scene row).
    calls: list[str] = []
    for owner, name in ((pygame.display, "message_box"), (pygame.mouse, "set_visible"),
                        (pygame.mouse, "set_cursor"), (pygame.display, "set_mode")):
        real = getattr(owner, name)
        monkeypatch.setattr(owner, name, lambda *a, _n=name, _r=real, **k:
                            (calls.append(_n), _r(*a, **k))[1])
    root = game(tmp_path, "w", template_w("effect crash"))
    s = Session(root)
    out: dict = {}
    titles: list[str] = []
    real_title = type(s.app).set_title
    monkeypatch.setattr(type(s.app), "set_title",
                        lambda app, t: (titles.append(t), real_title(app, t)))

    def script(s: Session):
        c = yield from to_crash(s)
        calls.clear()
        titles.clear()
        screen = crash_up(s)
        out["widgets"] = [a for a in ("widgets", "scope", "focus") if getattr(screen, a, None)]
        s.event(pygame.WINDOWFOCUSLOST)
        for f in range(c + 1, c + 121):
            yield from to_frame(s, f)
            if f % 3 == 0:
                _ignored_keys()
            if f == c + 60:
                s.event(pygame.WINDOWFOCUSGAINED)
        out["calls"], out["titles"] = list(calls), list(titles)
        shell = s.app.shell
        out["quit"] = shell.quit_guard()
        out["stack"] = [type(x).__name__ for x in s.app.screens]

    s.play(script, last=900)
    assert out["widgets"] == []
    assert out["calls"] == [] and out["titles"] == []
    assert out["quit"] is True                               # no quit question: quits now
    assert "ConfirmScreen" not in out["stack"] and out["stack"][-1] == "FakeCrashScreen"


def test_ac_f30_22_a_wait_never_a_step(tmp_path, caplog):
    root = game(tmp_path, "w", template_w("effect crash"))
    s = Session(root)
    out: dict = {}

    def script(s: Session):
        persist = yield from _persist_after_load(s)
        persist.fail = OSError("disk")                      # one DEBUG line; the page shows
        c = yield from to_crash(s)
        out["flush"] = (list(persist.flushes), c, crash_up(s) is not None)
        saves, shell = s.app.saves, s.app.shell
        out["can_save"] = (saves.can_save(), saves.can_save(quitting=True))
        got = []
        shell.capture_scene(got.append)
        for _ in range(3):
            yield
        out["capture"] = got
        s.app.skip_auto.set_auto(True)                       # auto: the screen stays
        for _ in range(120):
            yield
        out["auto"] = crash_up(s) is not None
        s.app.skip_auto.set_auto(False)
        # A real error during the crash: the real ErrorScreen and the game's title.
        s.app.show_fatal_error(RuntimeError("engine broke"))
        yield
        out["error"] = (type(s.app.screens.top).__name__, crash_up(s), s.window.title)

    with caplog.at_level(logging.DEBUG):
        s.play(script, last=1500)
    flushes, c, shown = out["flush"]
    assert len(flushes) == 1 and flushes[0] <= c and shown
    assert out["can_save"] == (False, True) and out["capture"] in ([], [None])
    assert out["auto"]
    assert len([r for r in caplog.records if "before the fake crash" in r.getMessage()
                and r.levelno == logging.DEBUG]) == 1
    assert out["error"] == ("ErrorScreen", None, "Paper Test")

    # Skip held through the crash: no screen, no flush; then a New Game by the driver while
    # a crash shows removes it in that frame.
    root = game(tmp_path, "skip", template_w("effect crash"),
                config="[skip]\nall = true\n")
    s = Session(root)
    out = {"crash_frames": 0}

    def script(s: Session):
        persist = yield from _persist_after_load(s)
        yield from s.until_line("Hello.")
        s.app.skip_auto.start_skip()
        for _ in range(120):
            yield
            out["crash_frames"] += crash_up(s) is not None
            if s.line_text() == "Goodbye.":
                break
        out["skip"] = (list(persist.flushes), s.line_text())
        s.app.skip_auto.stop_skip()
        s.app.shell._new_game_cut()                    # the driver's New Game
        yield from s.until_line("Hello.")
        c = yield from to_crash(s)
        yield from to_frame(s, c + 10)
        s.app.shell._new_game_cut()
        yield
        out["new_game"] = crash_up(s) is None

    s.play(script, last=1500)
    assert out["crash_frames"] == 0
    assert out["skip"][0] == [] and out["skip"][1] in (L7, "Goodbye.", "End.")
    assert out["new_game"]


def test_ac_f30_23_windowed_equals_headless(tmp_path):
    # Lean: defaults and reduce on, every crash continued by Space (the click wait), seed 7;
    # the crash inside a menu branch and the skip and auto runs of the row are not run.
    from tests.app.test_windowed_equals_headless import windowed
    from tests.runtime.corpus import canon
    from tests.runtime.effects_story import load_game
    from engine.runtime.headless import run_headless
    script = ('define hana = Character("Hana")\n'
              'image bg room = "#c8c8c8"\n'
              "label start:\n"
              "    scene bg room\n"
              '    effect window_title "She is here"\n'
              '    hana "I know who you are, {username}."\n'
              '    effect crash "Hi {username}"\n'
              "    effect crash\n"
              "    effect window_title off\n"
              '    "Morning came."\n')
    for config in ("", "[effects]\nreduce = true\n"):
        root = game(tmp_path, f"a{len(config)}", script, config=config)
        expected = canon(run_headless(load_game(root), seed=7))
        assert canon(windowed(root, click_through=False)) == expected, config


def test_ac_f30_24_crash_text_stays_on_the_canvas(tmp_path, monkeypatch, caplog):
    from engine.app import fourthwall as fourthwall_module
    from engine.app.settings import SettingsService
    from engine.persist.settings_file import LoadedSettings, Outcome
    from engine.runtime.commands import FakeCrash
    from engine.ui.builtin import error_look
    from tests.fakes.draw_spy import spy_draw_text
    from tests.fakes.username import reader
    import ast
    from pathlib import Path

    monkeypatch.setattr(fourthwall_module, "read_login_name", reader())
    root = game(tmp_path, "w", template_w('effect crash "Hi {username}, CrashMark"'),
                config="[meta]\nusername = true\n")
    s = Session(root)
    s.app.settings = SettingsService(LoadedSettings({"username_use": 2}, Outcome.OK),
                                     s.app.config)
    out: dict = {}

    def script(s: Session):
        yield from s.until(lambda: s.app.story is not None)
        commands = spy_commands(s)
        yield from to_crash(s)
        out["message"] = crash_up(s).message
        body = next(c for c in commands if isinstance(c, FakeCrash)).body
        out["body"] = [sp.text for sp in body.plain(names=True) if sp.style.username]
        out["repr"] = repr(body)

        real_draw_page = error_look.draw_page

        def boom(*a, **k):                                   # once: ErrorScreen draws it too
            monkeypatch.setattr(error_look, "draw_page", real_draw_page)
            raise pygame.error("boom")

        monkeypatch.setattr(error_look, "draw_page", boom)
        crash_up(s)._page = None                             # the page is built again
        for _ in range(3):
            yield
        with monkeypatch.context() as patch, spy_draw_text(patch) as draws:
            yield
            yield
        out["error"] = (type(s.app.screens.top).__name__, [d.text for d in draws],
                        s.window.title)

    with caplog.at_level(logging.DEBUG):
        s.play(script, last=900)
    assert out["message"] == "Hi Zq9Name, CrashMark"
    assert out["body"] == ["friend"] and "zq9name" not in out["repr"].lower()
    name, texts, title = out["error"]
    assert name == "ErrorScreen" and title == "Paper Test"
    assert texts and not [t for t in texts if "CrashMark" in t or "zq9name" in t.lower()]
    # Check Z: no log record and no file under the game folder holds the name.
    assert not [r for r in caplog.records if "zq9name" in r.getMessage().lower()
                or "zq9name" in (r.exc_text or "").lower()]
    for path in root.rglob("*"):
        if path.is_file():
            assert b"zq9name" not in path.read_bytes().lower(), path
    # Static: the crash page never reaches the clipboard or the real error screen's code.
    ui = Path(__file__).resolve().parents[2] / "engine" / "ui" / "builtin"
    tree = ast.parse((ui / "fake_crash.py").read_text(encoding="utf-8"))
    imported = {f"{n.module}.{a.name}" for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) for a in n.names} | {
        n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert "engine.ui.builtin.error_look" in imported
    assert "engine.ui.builtin.error" not in imported and "pygame.scrap" not in imported
    writers = sorted(p.name for p in (ui.parent.parent).rglob("*.py")
                     if "scrap.put" in p.read_text(encoding="utf-8"))
    assert writers == ["error.py"], writers

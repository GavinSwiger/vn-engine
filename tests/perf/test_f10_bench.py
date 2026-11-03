"""F10 step 9 — menus at 60 fps (``04-technical.md`` §11, §15 "Perf"; ``06-acceptance.md``
§1.13): AC-F10-68 (``perf``), the timing row of AC-F10-67 (CI), and CI guards for the loop.

The harness is F04's (``stage_bench_harness.py``), subclassed: ``MenuBenchHarness`` plays the
loop of AC-F10-68 on a copy of the example game ``game/`` (title art, logo, music, button
frame) with keys only, over and over:

    title (fully faded in) → Down, Return (New Game) → the first line → Esc (game menu)
    → 60 steady frames → Quit (focused through the scope) and Return → the quit question
    → Esc (No) → Shift+F3 (the sampler) → its 100-row list focused, Down once per frame for
    100 frames (one row per frame) → Esc → Main Menu and Return → Left, Return (Yes) → the
    black fade → the title fading in → again.

Each frame gets one **kind** from what its top screen drew (spies on ``MenuScreen.draw``,
``TitleScreen.draw``, ``BlackFadeScreen.draw``, and ``CapturedBackdrop._store``), by
priority: ``capture`` (a backdrop copied) > ``fade`` (a menu or question fading, `04` §11's
fade B) > ``black fade`` > ``title fade`` (in from black, or out on New Game) > ``sampler``
> ``confirm`` > ``menu`` (a steady game-menu frame) > ``title`` > ``game``. A frame's work is
``App.recent.last_work_ms()``, read at the next frame's start.

**CI guards (every run, in process, ``scripted_app``, fake clock, 1920×1080):** one short
loop (20 steady frames, 30 list rows, shorter fades) reaches every phase in order with no
warning; each menu and question open copies its backdrop exactly once; the list moves one
row per frame and scrolls; and AC-F10-67's timing row: the median draw time of a steady
game-menu frame on the CI runner is ≤ 5 ms (a loose limit; the reference numbers are the
``perf`` runs').

**Reference runs (``perf``; the ADR-0005 machine or a stand-in with integrated graphics and a
PassMark single-thread score ≤ 2,000, never CI).** Close other apps, mains power, "Balanced"
plan, a 1920×1080 display at 100%, then (Windows, from the project root)::

    set SDL_VIDEODRIVER=windows
    set VN_PERF=1
    set VN_PASSMARK_ST=<the machine's PassMark single-thread score>
    .venv/Scripts/python -m pytest tests/perf/test_f10_bench.py -m perf -s -v

(``SDL_VIDEODRIVER=x11`` or ``cocoa`` elsewhere; the tests fail under the dummy driver.)
AC-F10-68 is two 600 s runs, 1280×720 windowed and 1920×1080 fullscreen (about 21 minutes;
the fullscreen one takes the screen), each on a temporary copy of ``game/``. Attach the
printed lines (machine, versions, the five bench lines, and p50/p99 per frame kind next to
`04` §11's estimates) to the F10 test report. If fade frames fail, F10 I-12's pre-approved
fallback applies. ``VN_BENCH_SECONDS=N`` shortens the runs for a trial; such a run is not a
result.
"""

import contextlib
import math
import os
import shutil
import statistics
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pygame
import pytest

from engine.app.app import App
from engine.core.constants import BENCH_WARMUP_S
from engine.ui.backdrop import CapturedBackdrop
from engine.ui.builtin.black_fade import BlackFadeScreen
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.sampler import SamplerScreen
from engine.ui.builtin.textbox_screen import TextboxScreen
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.menu_screen import MenuScreen, Phase
from engine.ui.nav import InputKind
from tests.perf.stage_bench_harness import (StageBenchHarness, bench_launch, machine_lines,
                                            parse_bench, scripted_play)
from tests.fakes.first_launch import answer_name_question
from tests.script.load_process import cpu_name

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "game"
WORK_P99_MAX_MS = 16.00                  # ADR-0005, also fade frames and every capture frame
LONG_PCT_MAX = 0.50
MEASURED_TOLERANCE_S = 0.05
CI_MENU_DRAW_MEDIAN_MAX_MS = 5.0         # AC-F10-67's timing row, on a CI runner
STALL_S = 10.0                           # a phase that doesn't move on for this long fails
# 04 §11's estimates for the reference machine (ms), printed beside the measured kinds.
ESTIMATES = {"menu": 3.0, "fade": 14.0, "capture": 9.3, "sampler": 2.5, "title fade": 4.8}
KINDS = ("capture", "fade", "black fade", "title fade", "sampler", "confirm", "menu", "title",
         "game")                         # by priority, highest first


def frame_kind(tags: set[str]) -> str:
    """The kind of a frame from what its top screen drew (``KINDS`` order)."""
    return next((kind for kind in KINDS if kind in tags), "game")


def p99(values: list[float]) -> float:
    """Nearest rank, as the engine's bench lines: sorted(xs)[ceil(0.99 n) − 1]."""
    ordered = sorted(values)
    return ordered[math.ceil(0.99 * len(ordered)) - 1]


def _key(key: int, mod: int = 0) -> None:
    """One press and its release (no hold, so no key repeat)."""
    for kind in (pygame.KEYDOWN, pygame.KEYUP):
        pygame.event.post(pygame.event.Event(kind, key=key, mod=mod, unicode="", scancode=0))


# --- the harness -----------------------------------------------------------------------------

@dataclass
class MenuBenchHarness(StageBenchHarness):
    """F04's harness playing AC-F10-68's loop with keys. ``steady`` and ``rows`` are the
    steady game-menu frames and the list rows per cycle; ``line_wait_s`` the time on the first
    line before Esc."""

    advance_s: float | None = None
    steady: int = 60
    rows: int = 100
    line_wait_s: float = 0.3
    kinds: list[str] = field(default_factory=list)          # [i]: frame i's kind
    work_ms: list[float] = field(default_factory=list)      # [i]: frame i's work
    menu_draw_ms: list[float] = field(default_factory=list)  # steady game-menu draws
    phases: list[str] = field(default_factory=list)         # every phase entered, in order
    opens: int = 0                                          # game menus and questions opened
    captures: list[str] = field(default_factory=list)       # the phase of each capture
    list_moves: list[tuple[int, float]] = field(default_factory=list)   # (focus row, scroll)
    cycles: int = 0
    stalled: str | None = None
    app: App | None = None
    _phase: str = "title"
    _since: float = 0.0
    _count: int = 0
    _tags: set[str] = field(default_factory=set)
    _draw_ms: float = 0.0

    # -- per frame --

    def on_frame(self, app: App, now: float) -> None:
        self.app = app
        if self.frames:                           # the frame that just ended
            self.kinds.append(frame_kind(self._tags))
            self.work_ms.append(app.recent.last_work_ms())
            if self.kinds[-1] == "menu":
                self.menu_draw_ms.append(self._draw_ms)
        self._tags = set()
        self._draw_ms = 0.0
        super().on_frame(app, now)
        if self.story_started is None or self.stalled is not None:
            return
        if not self.phases:                       # the bench starts on the title
            self._go("title", now)
        if now - self._since > STALL_S:
            self.stalled = f"{self._phase} for {STALL_S:.0f} s"
            app.request_quit(force=True)
            return
        getattr(self, "_" + self._phase.replace(" ", "_"))(app, now)

    def tag(self, kind: str, draw_ms: float = 0.0) -> None:
        self._tags.add(kind)
        self._draw_ms += draw_ms

    def _go(self, phase: str, now: float) -> None:
        self._phase, self._since, self._count = phase, now, 0
        self.phases.append(phase)

    # -- the loop, one phase per method --

    def _title(self, app: App, now: float) -> None:
        top = app.screens.top
        if isinstance(top, TitleScreen) and top.in_t >= 1.0 and not top.leaving:
            _key(pygame.K_DOWN)                   # the first input focuses New Game
            self._go("new game", now)

    def _new_game(self, app: App, now: float) -> None:
        _key(pygame.K_RETURN)
        self._go("starting", now)

    def _starting(self, app: App, now: float) -> None:
        top = app.screens.top
        stage = getattr(app, "stage_screen", None)
        if stage is not None and stage.wait_kind is not None:
            stage.press()                          # F18's prologue card, as Space ends it
            return
        if isinstance(top, TextboxScreen) and top.line is not None:
            if self._count == 0:
                self._since = now
            self._count += 1
            if now - self._since >= self.line_wait_s:
                _key(pygame.K_ESCAPE)
                self.opens += 1
                self._go("menu opening", now)

    def _menu_opening(self, app: App, now: float) -> None:
        top = app.screens.top
        if isinstance(top, GameMenuScreen) and top.phase is Phase.OPEN:
            self._go("menu steady", now)

    def _menu_steady(self, app: App, now: float) -> None:
        self._count += 1
        if self._count > self.steady:
            self._activate(app, "quit")
            self.opens += 1
            self._go("question", now)

    def _question(self, app: App, now: float) -> None:
        top = app.screens.top
        if isinstance(top, ConfirmScreen) and top.phase is Phase.OPEN:
            _key(pygame.K_ESCAPE)                 # No
            self._go("question closing", now)

    def _question_closing(self, app: App, now: float) -> None:
        top = app.screens.top
        if isinstance(top, GameMenuScreen) and top.phase is Phase.OPEN:
            _key(pygame.K_F3, pygame.KMOD_LSHIFT)
            self._go("sampler opening", now)

    def _sampler_opening(self, app: App, now: float) -> None:
        top = app.screens.top
        if isinstance(top, SamplerScreen):
            top.scope.focus(top.list, InputKind.KEYS, sound=False)
            top.list.focus_index(0)
            self._go("sampler", now)

    def _sampler(self, app: App, now: float) -> None:
        top = app.screens.top
        assert isinstance(top, SamplerScreen)
        if self._count:
            self.list_moves.append((top.list.focus_row, top.list.scroll))
        if self._count < self.rows - 1:
            _key(pygame.K_DOWN)
            self._count += 1
        else:
            _key(pygame.K_ESCAPE)
            self._go("sampler closing", now)

    def _sampler_closing(self, app: App, now: float) -> None:
        top = app.screens.top
        if isinstance(top, GameMenuScreen) and top.phase is Phase.OPEN:
            self._activate(app, "main_menu")
            self.opens += 1
            self._go("main menu", now)

    def _main_menu(self, app: App, now: float) -> None:
        top = app.screens.top
        if isinstance(top, ConfirmScreen) and top.phase is Phase.OPEN:
            _key(pygame.K_LEFT)
            self._go("yes", now)

    def _yes(self, app: App, now: float) -> None:
        _key(pygame.K_RETURN)
        self._go("ending", now)

    def _ending(self, app: App, now: float) -> None:
        if isinstance(app.screens.top, TitleScreen):
            self.cycles += 1
            self._go("title", now)

    @staticmethod
    def _activate(app: App, entry_id: str) -> None:
        """Focus a game-menu entry by keys (the scope; the order of entries is the
        registry's) and press Return."""
        menu = app.screens.top
        assert isinstance(menu, GameMenuScreen)
        button = menu.button(entry_id)
        assert button is not None, entry_id
        menu.scope.focus(button, InputKind.KEYS, sound=False)
        _key(pygame.K_RETURN)

    # -- the report --

    def measured(self) -> list[tuple[str, float]]:
        """(kind, work ms) of the frames after the bench's warm-up (the bench starts with the
        title, the first frame not loading)."""
        if self.story_started is None:
            return []
        start = self.story_started + BENCH_WARMUP_S
        return [(kind, ms) for kind, ms, at in zip(self.kinds, self.work_ms, self.frames)
                if at >= start]

    def by_kind(self) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for kind, ms in self.measured():
            out.setdefault(kind, []).append(ms)
        return out


@contextlib.contextmanager
def spy_menus(harness: MenuBenchHarness, mp) -> Iterator[None]:
    """Tag each frame with what its top screen drew (and time the draw)."""
    real_menu, real_title = MenuScreen.draw, TitleScreen.draw
    real_black, real_store = BlackFadeScreen.draw, CapturedBackdrop._store

    def is_top(screen) -> bool:
        return harness.app is not None and harness.app.screens.top is screen

    def menu_draw(self, canvas):
        fading = self.alpha < 1.0
        started = time.perf_counter()
        real_menu(self, canvas)
        ms = (time.perf_counter() - started) * 1000.0
        if is_top(self):
            kind = ("fade" if fading else "sampler" if isinstance(self, SamplerScreen)
                    else "confirm" if isinstance(self, ConfirmScreen)
                    else "menu" if isinstance(self, GameMenuScreen) else "game")
            harness.tag(kind, ms)

    def title_draw(self, canvas):
        real_title(self, canvas)
        if is_top(self):
            harness.tag("title fade" if self.darkness > 0 else "title")

    def black_draw(self, canvas):
        real_black(self, canvas)
        if is_top(self):
            harness.tag("black fade")

    def store(self, *args, **kwargs):
        real_store(self, *args, **kwargs)
        harness.captures.append(harness._phase)
        harness.tag("capture")

    mp.setattr(MenuScreen, "draw", menu_draw)
    mp.setattr(TitleScreen, "draw", title_draw)
    mp.setattr(BlackFadeScreen, "draw", black_draw)
    mp.setattr(CapturedBackdrop, "_store", store)
    yield


def copy_example(dest: Path, *, extra: str = "") -> Path:
    """``game/`` without its logs and persistent data, with ``extra`` appended to its
    ``config.toml`` (new tables only; the example's own tables stay)."""
    root = Path(shutil.copytree(EXAMPLE, dest, ignore=shutil.ignore_patterns("logs",
                                                                            "persistent",
                                                                            "characters")))
    if extra:
        with (root / "config.toml").open("a", encoding="utf-8", newline="\n") as f:
            f.write("\n" + extra + "\n")
    answer_name_question(root)               # F30 s6: no first-launch name question
    return root


def window_config(game: Path, *, fullscreen: bool, size: tuple[int, int]) -> None:
    """Set ``[window]`` in the copy's ``config.toml`` (its commented defaults)."""
    path = game / "config.toml"
    text = path.read_text(encoding="utf-8")
    for old, new in (("# width = 1280", f"width = {size[0]}"),
                     ("# height = 720", f"height = {size[1]}"),
                     ("# fullscreen = false", f"fullscreen = {str(fullscreen).lower()}")):
        assert old in text, old
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8", newline="\n")


# --- CI guards ------------------------------------------------------------------------------

def test_frame_kinds_follow_their_priority():
    assert frame_kind(set()) == "game"
    assert frame_kind({"menu", "capture"}) == "capture"
    assert frame_kind({"fade", "title fade"}) == "fade"
    assert frame_kind({"sampler", "menu"}) == "sampler"
    assert frame_kind({"title"}) == "title"
    assert p99([float(v) for v in range(1, 101)]) == 99.0


@pytest.mark.display
def test_the_loop_on_the_example_game(tmp_path, user_roots, scripted_app):
    """One cycle of AC-F10-68's loop at 1920×1080 on the CI runner: every phase in order, no
    warning, one capture per open, one list row per frame, and AC-F10-67's timing row."""
    game = copy_example(tmp_path / "game", extra="[theme.ui]\nfade_ms = 50")
    text = (game / "config.toml").read_text(encoding="utf-8")
    (game / "config.toml").write_text(text.replace(                 # a shorter title fade-in
        'music = "bgm/lantern_walk.wav"', 'music = "bgm/lantern_walk.wav"\nfade_in_ms = 100'),
        encoding="utf-8", newline="\n")
    # The dummy display's work area is smaller than 1920×1080, so the window is sized in
    # frame 1, while the story loads (its 200 ms resize settle ends before the title).
    scripted_app.at(1, lambda app: setattr(app.window._window, "size", (1920, 1080)))
    sizes: list = []
    scripted_app.at(120, lambda app: sizes.append(app.window.framebuffer().get_size()))
    harness = MenuBenchHarness(steady=20, rows=30, line_wait_s=0.1)
    with pytest.MonkeyPatch.context() as mp, spy_menus(harness, mp):
        code = scripted_play(scripted_app, game, harness, frames=170)
    assert code == 0
    assert harness.stalled is None and harness.warnings == []
    assert sizes == [(1920, 1080)]
    assert harness.cycles >= 1, harness.phases
    cycle = harness.phases[:harness.phases.index("title", 1)]
    assert cycle == ["title", "new game", "starting", "menu opening", "menu steady",
                     "question", "question closing", "sampler opening", "sampler",
                     "sampler closing", "main menu", "yes", "ending"]
    for kind in ("title fade", "title", "game", "capture", "fade", "menu", "confirm",
                 "sampler", "black fade"):
        assert kind in harness.kinds, kind
    # One capture per open: the game menu, the quit question, Main Menu's question (the
    # session's closing quit may ask once more at the end).
    assert harness.captures[:3] == ["menu opening", "question", "main menu"]
    first = harness.list_moves[:29]                        # the first cycle's sampler
    assert [row for row, _ in first] == list(range(1, 30))     # one row per frame
    scrolls = [scroll for _, scroll in first]
    assert scrolls[-1] > 0 and scrolls == sorted(scrolls)
    assert sum(1 for a, b in zip(scrolls, scrolls[1:]) if b > a) >= 20
    assert len(harness.menu_draw_ms) >= 20
    assert statistics.median(harness.menu_draw_ms) <= CI_MENU_DRAW_MEDIAN_MAX_MS


# --- AC-F10-68 (perf) ------------------------------------------------------------------------

def _ms(values: list[float]) -> str:
    if not values:
        return "none"
    ordered = sorted(values)
    return (f"{len(ordered)} frames | ms p50 {ordered[len(ordered) // 2]:.3f} | "
            f"p99 {p99(ordered):.3f} | max {ordered[-1]:.3f}")


def _report(title: str, harness: MenuBenchHarness) -> None:
    print(f"\n== {title}")
    for line in machine_lines(cpu_name(), os.environ.get("VN_PASSMARK_ST"), harness.driver):
        print(line)
    for line in harness.bench_lines:
        print(line)
    print(f"Cycles: {harness.cycles} | menus and questions opened: {harness.opens} | "
          f"captures: {len(harness.captures)}")
    kinds = harness.by_kind()
    for kind in KINDS:
        estimate = ESTIMATES.get(kind)
        note = f" (estimate {estimate:.1f} ms)" if estimate is not None else ""
        print(f"  {kind:10}: {_ms(kinds.get(kind, []))}{note}")


@pytest.mark.perf
@pytest.mark.parametrize("fullscreen", [False, True], ids=["1280x720-windowed",
                                                           "1920x1080-fullscreen"])
def test_ac_f10_68_menus_at_60_fps(tmp_path, real_display, user_roots, fullscreen):
    seconds = float(os.environ.get("VN_BENCH_SECONDS", "600"))
    game = copy_example(tmp_path / "game")
    size = (1920, 1080) if fullscreen else (1280, 720)
    window_config(game, fullscreen=fullscreen, size=size)
    harness = MenuBenchHarness()
    with pytest.MonkeyPatch.context() as mp, spy_menus(harness, mp):
        code = bench_launch(game, harness, seconds=seconds)
    _report(f"AC-F10-68 {'1920x1080 fullscreen' if fullscreen else '1280x720 windowed'} "
            f"({seconds:.0f} s)", harness)
    assert code == 0 and harness.warnings == [] and harness.stalled is None
    bench = parse_bench(harness.bench_lines)
    if fullscreen:
        assert bench["mode"] == "fullscreen" and bench["framebuffer"] == (1920, 1080)
    else:
        assert bench["mode"] == "windowed" and bench["window"] == (1280, 720)
    assert abs(bench["measured_s"] - seconds) <= MEASURED_TOLERANCE_S
    assert harness.cycles >= 2
    assert bench["cap_holds"]
    assert bench["work_p99"] <= WORK_P99_MAX_MS
    assert bench["long_pct"] <= LONG_PCT_MAX
    kinds = harness.by_kind()
    assert kinds.get("fade") and p99(kinds["fade"]) <= WORK_P99_MAX_MS
    assert kinds.get("capture") and max(kinds["capture"]) <= WORK_P99_MAX_MS

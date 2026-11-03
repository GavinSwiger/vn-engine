"""F32 step 5: in-game styles on the text box (``06-acceptance.md`` AC-F32-18, 19, 21; ``04``
§6.5, §11; TR-F32-03, TR-F32-04).

``StyleRig`` is the step-4 ``LookRig`` launch order with F07's choices: ``install_textbox``,
``install_choices``, ``install_ui``, ``install_looks`` (as ``install_story`` does) over
Template U's styles (``calm``'s nine-slice is F10's generated ``gui/button.png``). The
textbox is the only screen; ``UiStyle`` goes through the App's router, as the story's
command would. Frames are ``UiHarness`` frames (1280×720, 1/60 s).
"""

import builtins
import io
import shutil
from pathlib import Path

import pygame
import pytest

from engine.app.choices import install_choices
from engine.app.looks import install_looks
from engine.app.menus import install_ui
from engine.app.settings import LoadedSettings, SettingsService
from engine.app.text_check import composite, install_textbox
from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.render import effects as effects_mod
from engine.render.assets import Face
from engine.render.nvl import NvlView
from engine.render.textbox import TextboxView, hex_rgb
from engine.runtime.commands import NvlPage, UiStyle
from engine.ui import looks as looks_mod
from engine.ui.builtin import nvl_page as nvl_page_mod
from engine.ui.builtin.nvl_page import NvlPresenter
from engine.ui.builtin.textbox_screen import TextSettings
from engine.ui.menu_screen import CursorKeeper
from tests.fakes.fx_text import FxSpy, say
from tests.fakes.ui_shell import UiHarness
from tests.render.conftest import make_assets
from tests.ui.test_title import make_game
from tests.ui.test_title_playthrough import FakeInterp, LookApp

pytestmark = pytest.mark.display

REPO = Path(__file__).resolve().parents[2]
FONT = REPO / "tests" / "fixtures" / "F01" / "games" / "assets" / "fonts" / "test.ttf"

STYLES = ('[theme.textbox]\nfill_color = "#202830"\n'
          '[style.ashes.theme.textbox]\nfill_color = "#1E1A1C"\ntext_color = "#EDE3E8"\n'
          'border_color = "#5A3848"\ntext_size = 30\n'
          '[style.ashes.words]\nsave = "Keep"\nsaving_off = "Not now."\n'
          '[style.calm.theme.textbox]\nframe_image = "gui/button.png"\n'
          '[style.calm.theme.choice]\nfill_color = "#334455"\n')
BASE_FILL = hex_rgb("#202830")
ASHES_FILL = hex_rgb("#1E1A1C")
ASHES_BORDER = hex_rgb("#5A3848")
L6 = "Still here, and this line is long enough to keep typing for a while yet."


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    yield
    pygame.quit()


class StyleRig:
    """A launch with F32's looks, the textbox on screen."""

    def __init__(self, tmp_path: Path, extra: str = "", *, styles: str = STYLES) -> None:
        root = make_game(tmp_path, styles + extra, art=True)
        (root / "fonts").mkdir(exist_ok=True)
        shutil.copy(FONT, root / "fonts" / "test.ttf")
        paths = GamePaths.for_game(root)
        loaded = load_config(paths)
        assert not loaded.errors, [e.format() for e in loaded.errors]
        self.paths = paths
        self.assets = make_assets(paths)
        self.app = LookApp(loaded.config, self.assets, dev=True)
        self.textbox = install_textbox(self.app)
        self.choices = install_choices(self.app, self.textbox)
        self.shell = install_ui(self.app)
        self.shell.cursor = CursorKeeper(lambda visible: None)
        self.looks = install_looks(self.app, FakeInterp({"playthrough": 0}))
        self.h = UiHarness(self.shell)
        self.app.screens.replace_all([self.textbox])

    def style(self, name: str | None) -> None:
        self.app.router.dispatch(UiStyle(name))

    def show(self, text: str, sid: str = "main/6", **kw) -> None:
        self.textbox.show(say(text, sid, effects=False, **kw))

    def frame(self):
        return self.h.frame()

    def px(self, x: float, y: float):
        return self.h.px(x, y)

    def box(self) -> tuple[float, float, float, float]:
        return self.textbox.geometry.box

    def fill_px(self):
        x, y, w, h = self.box()
        return self.px(x + w - 12, y + h - 12)

    def border_px(self):
        x, y, w, h = self.box()
        return self.px(x + w / 2, y + 0.5)


def close(a, b, tol: int = 2) -> bool:
    return all(abs(int(p) - int(q)) <= tol for p, q in zip(a, b))


def drawn(fill, opacity: float = 0.80):
    return composite(fill, opacity, (0, 0, 0))


# --- AC-F32-18 — the textbox switches at once, text at the next line ----------------------

def test_ac_f32_18_textbox_switches_at_once_text_at_next_line(tmp_path, monkeypatch):
    admitted: list = []
    real_admit = effects_mod.FlashLimiter.admit
    monkeypatch.setattr(effects_mod.FlashLimiter, "admit",
                        lambda self, *a, **k: admitted.append(1) or real_admit(self, *a, **k))
    rig = StyleRig(tmp_path / "s")
    control = StyleRig(tmp_path / "c")
    for r in (rig, control):
        r.textbox.settings = TextSettings(cps=40)
        r.show(L6)
    seen: list = []
    for n in range(1, 11):
        if n == 10:
            rig.style("ashes")
        rig.frame()
        control.frame()
        seen.append(rig.fill_px())
    # Frame 9 the base fill; frame 10 the style's fill and border; no blend frame.
    assert close(seen[8], drawn(BASE_FILL)) and close(seen[9], drawn(ASHES_FILL)), seen[8:]
    assert close(rig.border_px(), ASHES_BORDER), rig.border_px()
    # L6's glyphs: the same colors and the same count shown per frame until it ends (D1).
    tb, ctl = rig.textbox, control.textbox
    while ctl.typer.shown < len(L6) - 1:
        assert tb.typer.shown == ctl.typer.shown
        assert tb.layout.ctx.base_color == ctl.layout.ctx.base_color
        assert tb.layout.ctx.text_size == ctl.layout.ctx.text_size
        rig.frame()
        control.frame()
    # The next line: text #EDE3E8 at size 30.
    rig.show("End.", "main/7")
    rig.frame()
    assert tb.layout.ctx.base_color.upper() == "#EDE3E8" and tb.layout.ctx.text_size == 30
    # calm at frame 10: gui/button.png's nine-slice from frame 10.
    calm = StyleRig(tmp_path / "calm")
    calm.show(L6)
    calm.h.frames(9)
    before = calm.fill_px()
    calm.style("calm")
    calm.frame()
    assert calm.textbox.view.frame == "gui/button.png"
    assert not close(calm.fill_px(), before, 4), (before, calm.fill_px())
    # A rollback landing from L6 under ashes to line 4 (before the style): the burst's
    # UiStyle(None), then the restored line; the landing frame draws the base fill.
    rig.style(None)
    rig.textbox.show(say("Hello.", "main/4", effects=False, restored=True))
    rig.frame()
    assert close(rig.fill_px(), drawn(BASE_FILL)), rig.fill_px()
    # An F29 {shake} line switched at frame 10: the same offsets as the control; colors at
    # the next line.
    spy = FxSpy(monkeypatch)
    shaken = StyleRig(tmp_path / "fx")
    calm_ctl = StyleRig(tmp_path / "fxc")
    poses: dict[str, list] = {"s": [], "c": []}
    for key, r in (("s", shaken), ("c", calm_ctl)):
        r.textbox.show(say("{shake}Shaking words.{/shake}", "main/6"))
        for n in range(1, 16):
            if key == "s" and n == 10:
                r.style("ashes")
            r.frame()
            got = spy.take()
            poses[key].append(None if got is None else [pos for _s, pos in got])
    assert poses["s"] == poses["c"]
    assert shaken.textbox.layout.ctx.base_color == calm_ctl.textbox.layout.ctx.base_color
    shaken.show("Next.", "main/7")
    assert shaken.textbox.layout.ctx.base_color.upper() == "#EDE3E8"
    assert admitted == []                                  # a switch is no flash


# --- AC-F32-19 — sizes, NVL, and no wasted work --------------------------------------------

def test_ac_f32_19_sizes_nvl_and_no_wasted_work(tmp_path, monkeypatch):
    rig = StyleRig(tmp_path / "a")
    tb = rig.textbox
    rig.style("ashes")
    rows = [(100, 30), (130, 39), (150, 45)]
    for pct, size in rows:
        tb.settings = TextSettings(text_size_pct=pct)
        rig.show("Next line.")
        assert tb.layout.ctx.text_size == size, pct
        assert tb.text_scale() == tb.text_size() / tb.box_theme.text_size
    # A style's 40 at 150 %: 48 (F16's cap, D7).
    big = StyleRig(tmp_path / "b", styles=STYLES.replace("text_size = 30", "text_size = 40"))
    big.style("ashes")
    big.textbox.settings = TextSettings(text_size_pct=150)
    big.show("Big.")
    assert big.textbox.layout.ctx.text_size == 48
    # No style, base 28 at 150 %: 42 (unchanged).
    base = StyleRig(tmp_path / "c")
    base.textbox.settings = TextSettings(text_size_pct=150)
    base.show("Base.")
    assert base.textbox.layout.ctx.text_size == 42
    # Settings: app/settings.py passes the percent; 130 % while ashes is current → 39 from
    # the next line.
    service = SettingsService(LoadedSettings({}, None), rig.app.config)       # type: ignore
    service.set("text_size_pct", 130)
    assert service.text_settings().text_size_pct == 130
    tb.settings = service.text_settings()
    assert tb.layout.ctx.text_size == 45                   # the shown line keeps its size
    rig.show("After the change.")
    assert tb.layout.ctx.text_size == 39

    # NVL with 3 rows: a switch changes the panel fill in that frame; the next show plans
    # once and clears the heights cache.
    nvl = StyleRig(tmp_path / "n", '[style.ashes.theme.nvl]\nfill_color = "#401020"\n'
                   'fill_opacity = 1.0\n')
    t = nvl.textbox
    t.show_nvl(NvlPage(True))
    for i in range(3):
        nvl.show(f"Row {i}.", f"main/{i}")
    nvl.frame()
    assert len(t.nvl.plan.rows) == 3
    corner = nvl.px(4, 4)
    nvl.style("ashes")
    nvl.frame()
    assert close(nvl.px(4, 4), hex_rgb("#401020")) and corner != nvl.px(4, 4)
    plans, clears = [], []
    real_plan, real_clear = nvl_page_mod.plan_from, nvl_page_mod.clear_heights
    monkeypatch.setattr(nvl_page_mod, "plan_from",
                        lambda *a, **k: plans.append(1) or real_plan(*a, **k))
    monkeypatch.setattr(nvl_page_mod, "clear_heights",
                        lambda: clears.append(1) or real_clear())
    nvl.show("Row 3.", "main/3")
    assert plans == [1] and clears == [1]

    # Spies: 120 frames with no switch build no Look, no part, and call no restyle; one
    # switch gives exactly one restyle per view.
    counts = {"look": 0, "part": 0, "view": 0, "nvl_view": 0, "presenter": 0}

    def counting(key, fn):
        def wrapped(*a, **k):
            counts[key] += 1
            return fn(*a, **k)
        return wrapped

    monkeypatch.setattr(looks_mod.Looks, "_build", counting("look", looks_mod.Looks._build))
    looks = rig.looks
    looks._builders = {k: counting("part", v) for k, v in looks._builders.items()}
    real_restyle = TextboxView.restyle

    def view_restyle(self, *a, **k):
        if self is rig.textbox.view:                       # not the NVL view's line view
            counts["view"] += 1
        return real_restyle(self, *a, **k)

    monkeypatch.setattr(TextboxView, "restyle", view_restyle)
    monkeypatch.setattr(NvlView, "restyle", counting("nvl_view", NvlView.restyle))
    monkeypatch.setattr(NvlPresenter, "restyle", counting("presenter", NvlPresenter.restyle))
    rig.h.frames(120)
    assert counts == {"look": 0, "part": 0, "view": 0, "nvl_view": 0, "presenter": 0}
    rig.style("calm")
    rig.h.frames(5)
    rig.show("A line in calm.")
    rig.h.frames(5)
    assert counts["view"] == counts["nvl_view"] == counts["presenter"] == 1, counts

# --- AC-F32-21 — no file read in the switch frame --------------------------------------------

class ReadCounter:
    """Counts ``GamePaths.read_file`` calls and file opens."""

    def __init__(self, monkeypatch) -> None:
        self.reads: list[str] = []
        real_read, real_open, real_io_open = GamePaths.read_file, builtins.open, io.open

        inside: list[int] = []

        def read_file(paths, ref, **kwargs):
            self.reads.append(ref)
            inside.append(1)
            try:
                return real_read(paths, ref, **kwargs)
            finally:
                inside.pop()

        def spy_open(file, *a, **k):
            if not inside:                                 # read_file's own open: one read
                self.reads.append(str(file))
            return real_open(file, *a, **k)

        monkeypatch.setattr(GamePaths, "read_file", read_file)
        monkeypatch.setattr(builtins, "open", spy_open)
        monkeypatch.setattr(io, "open", spy_open)
        del real_io_open

    def take(self) -> list[str]:
        out, self.reads = self.reads, []
        return out


def test_ac_f32_21_no_file_read_in_the_switch_frame(tmp_path, monkeypatch):
    extra = ('[style.dusk.theme.textbox]\nfill_color = "#1E1A1C"\n'
             'frame_image = "gui/button.png"\ntext_font = "fonts/test.ttf"\n'
             '[style.dusk.theme.choice]\nfill_color = "#334455"\n')
    rig = StyleRig(tmp_path / "s", extra)
    rig.show(L6)
    rig.h.frames(3)
    counter = ReadCounter(monkeypatch)
    rig.style("dusk")                                      # handled and drawn: one frame
    rig.frame()
    assert counter.take() == []
    rig.show("The next line.", "main/7")                  # its layout: at most the font
    rig.frame()
    assert set(counter.take()) <= {"fonts/test.ttf"}
    assert rig.textbox.faces.faces[Face.REGULAR].ref == "fonts/test.ttf"
    # The title with stored 2: the _choose() frame opens nothing; the look's picture is read
    # at most once, during the launch (the load screen), never in a title frame.
    from tests.ui.test_title_playthrough import LookRig
    LOOK2 = ('[playthrough.2.theme.title]\nbackground_image = "gui/title_bg.png"\n')
    counter.take()
    title = LookRig(tmp_path / "t", LOOK2, playthrough=2)
    launch = [r for r in counter.take() if r.endswith("title_bg.png")]
    assert len(launch) <= 1
    title.frame()
    assert counter.take() == []
    title.shell._choose()
    title.frames(30)                                       # the fade-in
    assert [r for r in counter.take() if r.endswith("title_bg.png")] == []

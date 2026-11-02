"""F09 step 4 — shake, flash, the flash limit, and reduced effects in App A (``06-acceptance.md``
§0.2: the real ``App`` on a ``FakeWindow``, a fake clock of exactly 1/60 s per frame, the game
started through ``install_story``, input injected as pygame events). The stage is probed at
(640, 100), above F05's box; the band a shake uncovers at (8, 100).

Frame rule: a ``Shake``/``Flash`` arrives in the burst of its line, so the frame its line
arrives in (``Play.arrival``) is the effect's t = 0, the frame glyph 0 is drawn in.

AC-F09-33, 34, 36, 37.
"""

import logging
import zlib
from pathlib import Path

import pygame
import pytest

from engine.render.effects import EffectSettings
from engine.ui.screen import Screen
from tests.fakes.privacy import check_p
from tests.fakes.text_app import Session, make_text_game
from tests.fixtures.F04 import gen_images as gen

pytestmark = pytest.mark.display

EMBER, SEA, BLACK = (200, 40, 0), (0, 80, 240), (0, 0, 0)
WHITE = (255, 255, 255)
PROBE, BAND = (640, 100), (8, 100)
HEAD = ('image bg ember = "#c82800"\nimage bg sea = "#0050f0"\n'
        'define hana = Character("Hana")\ndefine lantern = Mask("masks/iris.png", 0.4)\n'
        'label start:\n    scene bg ember\n')
INSTANT = "[textbox]\ncps = 0\n"
OPAQUE_BOX = "[theme.textbox]\nfill_opacity = 1.0\n"
CORNER = 16                                              # the box's rounded corners, inset


class Play:
    """One App A session of ``HEAD`` + ``body``. Each line is pressed ``hold`` frames after
    it arrives (``holds`` per line text overrides it). Every presented frame is recorded:
    the probe, the band, the line, ``shown_count()``, and, for the names in ``crc``, a CRC of
    the frame (``whole``), of the stage above the box (``stage``), and of the box inside its
    rounded corners (``box``). The CRCs cost time, so they are opt-in. A line still typing
    when pressed (F05 completes it) is pressed again 3 frames later."""

    def __init__(self, root: Path, body: str, config: str = "", *, hold: int = 18,
                 holds: dict[str, int] | None = None, size=(1280, 720),
                 setup=None, each=None, crc: tuple[str, ...] = ()) -> None:
        self.root = make_text_game(root, script=HEAD + body, config=config)
        gen.write(self.root, {gen.ref_of("hana happy"): gen.block(300, 600, (0, 255, 0))})
        self.s = Session(self.root, size=size)
        self.hold, self.holds = hold, holds or {}
        self.setup, self.each, self.crc = setup, each, crc
        self.frames: list[dict] = []
        self.arrival: dict[str, int] = {}             # line text → frame it arrived in

    def run(self) -> "Play":
        def script(s: Session):
            yield from s.until(lambda: s.app.stage_screen is not None
                               and s.textbox is not None)
            if self.setup is not None:
                self.setup(self)
            last, pressed, pressed_at = None, None, 0
            for _ in range(1500):
                yield
                self._record()
                line = s.line_text()
                if line is not None and line != last:
                    self.arrival[line] = s.frame - 1
                    last = line
                if line == "End.":
                    return
                if self.each is not None:
                    self.each(self)
                f = s.frame - 1
                if line is not None and (pressed != line or f - pressed_at >= 3) and \
                        f - self.arrival[line] >= self.holds.get(line, self.hold) - 1:
                    s.key(pygame.K_SPACE)
                    pressed, pressed_at = line, f
                elif s.app.stage_screen.wait_kind == "click":
                    s.key(pygame.K_SPACE)
            raise AssertionError("End. not reached")

        self.s.play(script)
        return self

    def _record(self) -> None:
        s = self.s
        fb = s.fb
        k = fb.get_width() / 1280                        # probes in 1280×720 pixels
        record = {"frame": s.frame - 1, "px": s.px(round(PROBE[0] * k), round(PROBE[1] * k)),
                  "band": s.px(round(BAND[0] * k), round(BAND[1] * k)),
                  "line": s.line_text(), "shown": s.textbox.shown_count()}
        if self.crc:
            x, y, w, h = (round(v * k) for v in s.textbox.geometry.box)     # canvas units
            raw = fb.get_buffer().raw                    # rows are contiguous: no conversion
            for name in self.crc:
                if name == "box":
                    box = fb.subsurface((x + CORNER, y + CORNER, w - 2 * CORNER, h - 2 * CORNER))
                    record[name] = zlib.crc32(pygame.image.tobytes(box, "RGB"))
                else:
                    record[name] = zlib.crc32(raw if name == "whole" else
                                              memoryview(raw)[:y * fb.get_pitch()])
        self.frames.append(record)

    def at(self, frame: int) -> dict:
        return next(f for f in self.frames if f["frame"] == frame)

    def px(self, frame: int) -> tuple[int, int, int]:
        return self.at(frame)["px"]

    def since(self, line: str) -> list[dict]:
        """The frames from the arrival of ``line`` on (relative frame 0 first)."""
        start = self.arrival[line]
        return [f for f in self.frames if f["frame"] >= start]


def near(a, b, tol: int = 2) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def w61(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "code", None) == "W61"]


# --- AC-F09-34 — flash on screen ----------------------------------------------------------------

FLASH_ROWS = [  # (flash, config, T, first, mid)
    ("flash", "", 0.3, WHITE, (228, 148, 128)),
    ("flash red", "", 0.3, (255, 0, 0), (228, 20, 0)),
    ('flash "#ffe08a" 0.6', "", 0.6, (255, 224, 138), (228, 132, 69)),
    ("flash", '[theme.effects]\nflash_color = "#000000"\n', 0.3, BLACK, (100, 20, 0)),
    ("flash", "[effects]\nflash = 0.6\n", 0.6, WHITE, (228, 148, 128)),
]


def test_ac_f09_34_flash_on_screen(tmp_path):
    for number, (flash, config, T, first, mid) in enumerate(FLASH_ROWS):
        p = Play(tmp_path / str(number), f'    {flash}\n    hana "A."\n    "End."\n', config,
                 hold=60).run()
        n = p.arrival["A."]
        assert p.at(n)["shown"] >= 1, flash              # glyph 0's frame
        assert p.px(n) == first, (flash, config)
        assert near(p.px(n + round(30 * T)), mid), (flash, config)
        assert all(p.px(f) == EMBER for f in range(n + round(60 * T), n + 60)), (flash, config)


def test_ac_f09_34_the_box_and_typing_are_untouched_and_a_flash_rides_a_transition(tmp_path):
    body = '    flash\n    hana "A long line typed."\n    "B."\n    "End."\n'
    flash = Play(tmp_path / "f", body, OPAQUE_BOX, hold=40, crc=("box",)).run()
    control = Play(tmp_path / "c", body.replace("    flash\n", ""), OPAQUE_BOX, hold=40,
                   crc=("box",)).run()
    assert [(f["box"], f["shown"]) for f in flash.frames] == \
        [(f["box"], f["shown"]) for f in control.frames]
    assert flash.px(flash.arrival["A long line typed."]) == WHITE

    p = Play(tmp_path / "t", '    "A."\n    flash 0.6\n    scene bg sea with dissolve 1.0\n'
                             '    "End."\n').run()
    n = p.arrival["A."] + 18                             # the press: the burst arrives
    assert p.px(n - 1) == EMBER and p.px(n) == WHITE     # the transition's first frame
    assert p.s.app.stage_screen is not None


def test_ac_f09_34_restore_on_enter_and_drop_effects_remove_it(tmp_path):
    for how in ("restore", "on_enter", "drop_effects"):
        def each(p: Play, how=how):
            screen = p.s.app.stage_screen
            if p.s.line_text() == "A." and p.s.frame - 1 == p.arrival["A."] + 3:
                if how == "restore":
                    p.s.app.story.restore(p.s.app.story.checkpoint())
                elif how == "on_enter":
                    screen.on_enter()
                else:
                    screen.drop_effects()

        p = Play(tmp_path / how, '    flash 2.0\n    "A."\n    "End."\n', hold=30,
                 each=each).run()
        n = p.arrival["A."]
        assert p.px(n + 3) != EMBER and p.px(n + 4) == EMBER, how


# --- AC-F09-33 — shake on screen ----------------------------------------------------------------

EDGE_Y = 400                                             # a row through hana, above the box


def _track_edge(p: Play) -> None:
    """hana's left edge on row ``EDGE_Y`` (her green block at ``left``), per frame."""
    fb = p.s.fb
    row = [tuple(fb.get_at((x, EDGE_Y)))[:3] for x in range(0, 640, 2)]
    green = next((i * 2 for i, c in enumerate(row) if c == (0, 255, 0)), None)
    p.edges[p.s.frame - 1] = green


def test_ac_f09_33_shake_on_screen(tmp_path):
    body = ('    show hana happy at left\n    shake large horizontal 1.0\n    hana "Boom."\n'
            '    "Next."\n    "End."\n')
    runs = {}
    for name, text in (("shake", body), ("control", body.replace(
            "    shake large horizontal 1.0\n", ""))):
        p = Play(tmp_path / name, text, OPAQUE_BOX, hold=12, holds={"Next.": 70},
                 each=_track_edge, crc=("box", "whole"))
        p.edges = {}
        runs[name] = p.run()
    shake, control = runs["shake"], runs["control"]
    n = shake.arrival["Boom."]
    assert n == control.arrival["Boom."]
    assert shake.at(n)["shown"] >= 1
    assert shake.edges[n] == control.edges[n] + 24      # (+24, 0) units at 1280×720
    assert shake.at(n)["band"] == BLACK and control.at(n)["band"] == EMBER
    assert [(f["box"], f["shown"]) for f in shake.frames] == \
        [(f["box"], f["shown"]) for f in control.frames]
    assert shake.arrival["Next."] == n + 12              # advanced at 0.2 s...
    assert shake.edges[n + 13] != control.edges[n + 13]  # ...the shake goes on under it
    late = [f["frame"] for f in shake.frames if f["frame"] >= n + 60]
    assert late and all(shake.at(f)["whole"] == control.at(f)["whole"] for f in late)


def test_ac_f09_33_at_1080p_during_a_transition_and_frozen(tmp_path):
    def band(p: Play):
        p.bands[p.s.frame - 1] = next(x for x in range(60)
                                      if tuple(p.s.fb.get_at((x, 150)))[:3] == EMBER)

    p = Play(tmp_path / "hd", '    "Go."\n    shake large horizontal\n    "A."\n    "End."\n',
             size=(1920, 1080), hold=4, each=band)
    p.bands = {}
    p.run()
    assert abs(p.bands[p.arrival["A."]] - 36) <= 1

    p = Play(tmp_path / "t", '    "A."\n    shake large horizontal 1.0\n'
                             '    scene bg sea with dissolve 1.0\n    "End."\n').run()
    mid = p.arrival["A."] + 18 + 30                      # the dissolve's middle
    assert p.at(mid)["band"] == BLACK and p.px(mid) not in (EMBER, SEA)

    class Menu(Screen):
        opaque = False

    menu = Menu()

    def each(p: Play):
        s = p.s
        f = s.frame - 1
        n = p.arrival.get("A.")
        if n is not None and f == n + 5:
            s.app.screens.push(menu)
        if n is not None and f == n + 65:
            s.app.screens.remove(menu)
            s.app.stage_screen.drop_effects()

    p = Play(tmp_path / "frozen", '    shake large horizontal 1.0\n    "A."\n    "End."\n',
             INSTANT, holds={"A.": 80}, each=each, crc=("stage",)).run()
    n = p.arrival["A."]
    frozen = {p.at(f)["stage"] for f in range(n + 6, n + 66)}
    rest = p.at(n + 66)["stage"]                         # at rest in the next frame
    assert len(frozen) == 1 and rest not in frozen and rest == p.at(n + 70)["stage"]


# --- AC-F09-36 — the flash limit in play (W61) ------------------------------------------------

def test_ac_f09_36_strobe(tmp_path, caplog):
    body = "".join(f'    flash 0.1\n    "{n}."\n' for n in range(1, 7)) + '    "End."\n'
    with caplog.at_level(logging.WARNING):
        p = Play(tmp_path / "g", body, INSTANT).run()
    drawn = [p.px(p.arrival[f"{n}."]) == WHITE for n in range(1, 7)]
    assert drawn == [True, True, True, False, True, True]
    assert p.px(p.arrival["4."]) == EMBER
    [record] = w61(caplog)
    assert record.getMessage() == (
        "script/main.vns, line 13: the flash from this line wasn't shown, because the game "
        "shows at most 3 flashes a second to protect players who are sensitive to flashing.")
    check_p([record.getMessage()], home=Path.home(), game=p.root)


def test_ac_f09_36_a_short_fade_over_the_limit_plays_as_a_dissolve(tmp_path, caplog):
    body = ("".join(f'    flash 0.1\n    "{n}."\n' for n in range(1, 4))
            + '    scene bg sea with fade 0.5\n    "4."\n    "End."\n')
    with caplog.at_level(logging.WARNING):
        p = Play(tmp_path / "g", body, INSTANT).run()
    between = [f["px"] for f in p.frames if p.arrival["3."] + 18 < f["frame"] < p.arrival["4."]]
    assert any(near(px, (100, 60, 120)) for px in between)
    assert all(sum(px) > 150 for px in between)          # never dark: not a fade
    [record] = w61(caplog)
    assert record.getMessage() == (
        "script/main.vns, line 13: the fade from this line played as a dissolve, because the "
        "game shows at most 3 flashes a second to protect players who are sensitive to "
        "flashing.")


def test_ac_f09_36_what_never_counts(tmp_path, caplog):
    admits: list[float] = []

    def setup(p: Play):
        limiter = p.s.app.stage_screen.limiter
        real = limiter.admit

        def admit(now, *, reduced):
            admits.append(now)
            return real(now, reduced=reduced)

        limiter.admit = admit

    body = ("    scene bg sea with fade 1.0\n    scene bg ember with fade 1.0\n"
            "    scene bg sea with fade 1.0\n    scene bg ember with fade 1.0\n"
            '    "A."\n    scene bg sea with dissolve 0.2\n    scene bg ember with lantern 0.2\n'
            '    scene bg sea with cut\n    "B."\n    "End."\n')
    with caplog.at_level(logging.WARNING):
        p = Play(tmp_path / "g", body, INSTANT, setup=setup).run()
    dark = [f["frame"] for f in p.frames if f["frame"] < p.arrival["A."] and f["px"] == BLACK]
    assert len(dark) >= 4                                # four real fades
    assert admits == [] and w61(caplog) == []

    # Clicked-through short fades give their count back: none of these is refused.
    def click(p: Play):
        run = p.s.app.stage_screen.view._run
        if run is not None and run.running and run.clock > 0:
            p.s.key(pygame.K_SPACE)                      # its 2nd RUNNING frame

    body = "".join(f"    scene bg {'sea' if i % 2 == 0 else 'ember'} with fade 0.5\n"
                   for i in range(6)) + '    "End."\n'
    with caplog.at_level(logging.WARNING):
        Play(tmp_path / "c", body, INSTANT, each=click).run()
    assert w61(caplog) == []


# --- AC-F09-37 — reduced effects ------------------------------------------------------------

def _reduced(mode: str) -> tuple[str, object]:
    if mode == "config":
        return "[effects]\nreduce = true\n", None

    def setup(p: Play):
        p.s.app.stage_screen.settings = EffectSettings(reduce=True)

    return "", setup


TRANSITIONS = ('    "Go."\n    shake large\n    "S."\n    scene bg sea with cut\n    "C."\n'
               '    scene bg ember with dissolve\n    "D."\n    scene bg sea with fade 0.5\n'
               '    "F."\n    scene bg ember with lantern\n    "L."\n    "End."\n')


@pytest.mark.parametrize("mode", ["config", pytest.param("settings", marks=pytest.mark.slow)])
def test_ac_f09_37_no_shake_and_the_same_transitions(tmp_path, mode):
    """Both reduce sources stay in the default run through the soft-flash test below; this
    test's settings row is in the slow tier."""
    config, setup = _reduced(mode)
    small = {"size": (640, 360), "crc": ("stage",)}      # pixels compared, not probed
    reduced = Play(tmp_path / "r", TRANSITIONS, INSTANT + config, setup=setup, **small).run()
    control = Play(tmp_path / "c", TRANSITIONS.replace("    shake large\n", ""), INSTANT,
                   **small).run()
    assert [f["stage"] for f in reduced.frames] == [f["stage"] for f in control.frames]


@pytest.mark.parametrize("mode", ["config", "settings"])
def test_ac_f09_37_a_soft_flash_once_a_second(tmp_path, mode, caplog):
    config, setup = _reduced(mode)
    body = ('    "Go."\n    flash\n    "A."\n    flash 1.0\n    "B."\n    flash\n    "C."\n'
            '    flash\n    "D."\n    "End."\n')
    with caplog.at_level(logging.WARNING):
        p = Play(tmp_path / "g", body, INSTANT + config,
                 holds={"Go.": 4, "A.": 62, "B.": 150, "C.": 30, "D.": 40}, setup=setup).run()
    a = p.arrival["A."]
    assert p.px(a) == EMBER                              # w starts at 0
    assert near(p.px(a + 9), (214, 94, 64)) and near(p.px(a + 18), (228, 148, 128))
    assert all(p.px(f)[0] <= 230 for f in range(a, a + 60))       # never above w = 0.5
    assert all(p.px(f) == EMBER for f in range(a + 36, a + 60))
    b = p.arrival["B."]
    assert near(p.px(b + 60), (228, 148, 128)) and p.px(b + 120) == EMBER
    c, d = p.arrival["C."], p.arrival["D."]
    assert d - c <= 31                                   # 0.5 s apart
    assert near(p.px(c + 9), (214, 94, 64))
    assert all(p.px(f) == EMBER for f in range(c + 36, d + 30))   # D.'s flash not drawn
    assert w61(caplog) == []

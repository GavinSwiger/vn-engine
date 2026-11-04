"""F05 step 6 — ``install_textbox``: faces, the frame check, W43 and W45 (AC-F05-10), reads only
through the game folder (AC-F05-38, the textbox part), game-relative refs in the warnings
(AC-F05-39, the W43 part), and the contrast function (AC-F05-27's ratios, UI-F05-05).

Stand-ins for ``06`` §5's Lora fixture faces: copies of the bundled Noto Sans files under the
Lora names (any three readable faces of one family exercise the same resolution), and
``fonts/Lora.ttf`` 512 seeded random bytes. The games are run in App A
(``tests/fakes/text_app.py``) and also played one line.
"""

import logging
import os
import random
import shutil
import subprocess
import time
from pathlib import Path

import pygame
import pytest

from engine.app.loading import StoryLoadScreen
from engine.app.text_check import (
    TextLaunchCheck,
    box_contrast,
    composite,
    contrast_ratio,
    resolve_faces,
)
from engine.core.config_schema import TextboxTheme
from engine.core.paths import GamePaths
from engine.render.assets import Face, Synth
from engine.render.textlayout import BUNDLED_FACES, FaceSource, LineLayout, count_pages
from engine.render.typewriter import TypeState
from engine.runtime.commands import StoryEnded
from engine.runtime.headless import run_headless
from engine.runtime.launch import run_launch
from engine.script import LoadOptions, load_story as _load_story
from engine.script.messages import format_message
from tests.fakes.text_app import Session, make_text_game
from tests.fakes.username import no_real_username, reader  # noqa: F401  (name guard)
from tests.fixtures.F05.gen_text_corpus import write_game as write_corpus
from tests.render.conftest import make_assets

REPO = Path(__file__).resolve().parents[2]
FONTS = REPO / "engine" / "data" / "fonts"
EXAMPLE = REPO / "game"


def load_story(paths: GamePaths):
    """``load_story`` with the game's ``[stage.positions]`` names, as bootstrap loads it."""
    from engine.core.config import load_config
    positions = frozenset(load_config(paths).config.stage.positions)
    return _load_story(paths, LoadOptions(position_names=positions))

pytestmark = pytest.mark.display


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def lora_game(tmp_path: Path, config: str = "") -> Path:
    root = make_text_game(tmp_path / "game", S="x {b}b{/b} {i}i{/i}",
                          config="[theme.textbox]\n" + config if config else "")
    fonts = root / "fonts"
    fonts.mkdir()
    shutil.copy(FONTS / "NotoSans-Regular.ttf", fonts / "Lora-Regular.ttf")
    shutil.copy(FONTS / "NotoSans-Bold.ttf", fonts / "Lora-Bold.ttf")
    shutil.copy(FONTS / "NotoSans-Italic.ttf", fonts / "Lora-Italic.ttf")
    (fonts / "Lora.ttf").write_bytes(random.Random(5).randbytes(512))
    return root


def text_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.name == "vn.text" and r.levelno == logging.WARNING]


def play_one_line(root: Path):
    s = Session(root)

    def script(s):
        yield from s.until(lambda: s.textbox is not None and s.textbox.typer is not None
                           and s.textbox.typer.state is TypeState.COMPLETE)
        yield

    assert s.play(script) == 0
    return s


R, B, I, BI = Face.REGULAR, Face.BOLD, Face.ITALIC, Face.BOLD_ITALIC
LR, LB, LI = "fonts/Lora-Regular.ttf", "fonts/Lora-Bold.ttf", "fonts/Lora-Italic.ttf"
W45_BOLD = ("config.toml: [theme.textbox] text_font is set but bold_font isn't, so bold text "
            "is made by thickening your font. Add bold_font for a real bold face.")
W45_ITALIC = ("config.toml: [theme.textbox] text_font is set but italic_font isn't, so italic "
              "text is made by slanting your font. Add italic_font for a real italic face.")
BUNDLED = {f: FaceSource(None, f) for f in Face}


@pytest.mark.parametrize("config, warnings, faces", [
    ("", [], BUNDLED),
    ('text_font = "fonts/Lora-Regulr.ttf"',
     ['config.toml: [theme.textbox] text_font "fonts/Lora-Regulr.ttf" doesn\'t exist, so the '
      'built-in font is used. Did you mean "fonts/Lora-Regular.ttf"?'], BUNDLED),
    ('text_font = "fonts/Lora.ttf"',
     ['config.toml: [theme.textbox] text_font "fonts/Lora.ttf" couldn\'t be read as a font, '
      'so the built-in font is used. Export it again as .ttf or .otf.'], BUNDLED),
    (f'text_font = "{LR}"', [W45_BOLD, W45_ITALIC],
     {R: FaceSource(LR, R), B: FaceSource(LR, B, Synth.BOLD), I: FaceSource(LR, I, Synth.ITALIC),
      BI: FaceSource(LR, BI, Synth.BOLD_ITALIC)}),
    (f'text_font = "{LR}"\nbold_font = "{LB}"\nitalic_font = "{LI}"', [],
     {R: FaceSource(LR, R), B: FaceSource(LB, B), I: FaceSource(LI, I),
      BI: FaceSource(LB, BI, Synth.ITALIC)}),
    (f'text_font = "{LR}"\nbold_font = "fonts/nope.ttf"', ["W43", W45_ITALIC],
     {R: FaceSource(LR, R), B: FaceSource(LR, B, Synth.BOLD), I: FaceSource(LR, I, Synth.ITALIC),
      BI: FaceSource(LR, BI, Synth.BOLD_ITALIC)}),
], ids=["none", "missing", "unreadable", "lora-only", "lora-three", "nope-bold"])
def test_ac10_faces_and_warnings(tmp_path, caplog, config, warnings, faces):
    root = lora_game(tmp_path, config)
    requests = []
    with caplog.at_level(logging.WARNING):
        s = Session(root)
        real_font = s.assets.font

        def font(ref, size_px, *, bundled=Face.REGULAR, synth=Synth.NONE):
            requests.append((ref, bundled))
            return real_font(ref, size_px, bundled=bundled, synth=synth)

        s.assets.font = font

        def script(s):
            yield from s.until(lambda: s.textbox is not None and s.textbox.typer is not None
                               and s.textbox.typer.state is TypeState.COMPLETE)
            yield

        assert s.play(script) == 0
    got = text_warnings(caplog)
    if warnings and warnings[0] == "W43":            # G4 (I-8): code only, W43 alone for bold
        assert got[0].startswith('config.toml: [theme.textbox] bold_font "fonts/nope.ttf"')
        assert "made by thickening your text_font" in got[0]
        assert got[1:] == warnings[1:]
    else:
        assert got == warnings
    assert dict(s.app.textbox.faces.faces) == faces
    if "text_font" in config and faces is not BUNDLED:  # never a bundled styled face
        assert not [r for r in requests if r[0] is None and r[1] is not Face.REGULAR]


def test_ac10_a_missing_frame_draws_the_box(tmp_path, caplog):
    root = make_text_game(tmp_path / "game", S="x",
                          config='[theme.textbox]\nframe_image = "gui/textbox.png"\n')
    with caplog.at_level(logging.WARNING):
        s = play_one_line(root)
    assert text_warnings(caplog) == [
        'config.toml: [theme.textbox] frame_image "gui/textbox.png" doesn\'t exist, so the '
        'drawn box is used.']
    assert s.app.textbox.view.frame is None
    assert s.px(640, 504) == (0xF0, 0xA0, 0xC0)
    assert not [r for r in caplog.records if r.name == "vn.assets"]   # one warning only


def test_resolve_faces_without_a_game_folder_is_bundled():
    warnings = []
    faces = resolve_faces(TextboxTheme(), make_assets(None), warnings.append)
    assert dict(faces.faces) == BUNDLED and warnings == []

# --- AC-F05-38, 39 — reads through the game folder; refs in the warnings -----------------------

def test_ac38_fonts_and_frames_are_read_through_the_game_folder(tmp_path, monkeypatch, caplog):
    root = lora_game(tmp_path, f'text_font = "{LR}"\nbold_font = "{LB}"\n'
                               'frame_image = "gui/textbox.png"')
    (root / "gui").mkdir()
    shutil.copy(REPO / "engine" / "data" / "icon.png", root / "gui" / "textbox.png")
    reads = []
    real = GamePaths.read_file

    def read_file(self, ref, *, max_bytes):
        reads.append(ref)
        return real(self, ref, max_bytes=max_bytes)

    monkeypatch.setattr(GamePaths, "read_file", read_file)
    opened = []
    real_open = open

    def spy_open(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spy_open)
    with caplog.at_level(logging.WARNING):
        play_one_line(root)
    assert LR in reads and LB in reads and "gui/textbox.png" in reads
    game = str(root.resolve())
    for name in opened:
        path = str(Path(name).resolve())
        assert path.startswith(game) or path.startswith(str(FONTS.resolve())) \
            or "python" in path.lower() or "site-packages" in path.lower(), path


def test_ac39_w43_shows_game_relative_refs(tmp_path, caplog):
    root = lora_game(tmp_path, 'text_font = "fonts/Lora-Regulr.ttf"')
    with caplog.at_level(logging.WARNING):
        play_one_line(root)
    for message in text_warnings(caplog):
        assert str(tmp_path) not in message and "fonts/Lora-Regulr.ttf" in message


# --- The contrast function (I-6): UI-F05-05's table, AC-F05-27's ratios ----------------------------

TEXT, FILL, NAME, NAME_FILL = (0x3D, 0x2B, 0x36), (0xFF, 0xF4, 0xF8), (0xA0, 0x28, 0x60), \
    (0xFF, 0xE6, 0xF0)


def test_contrast_of_the_default_palette():
    assert composite(FILL, 0.80, (0, 0, 0)) == (0xCC, 0xC3, 0xC6)
    assert composite(FILL, 0.80, (255, 255, 255)) == (0xFF, 0xF6, 0xF9)
    assert round(contrast_ratio(TEXT, (0xCC, 0xC3, 0xC6)), 1) == 7.6
    assert round(contrast_ratio(TEXT, (0xFF, 0xF6, 0xF9)), 1) == 12.4
    assert round(contrast_ratio(NAME, NAME_FILL), 1) == 6.0
    assert contrast_ratio(NAME, (0xCC, 0xC3, 0xC6)) >= 4.1 - 0.05
    ratio, backdrop = box_contrast(TEXT, FILL, 0.80)
    assert backdrop == "black" and round(ratio, 1) == 7.6
    for color in ((0x9A, 0x1C, 0x14), (0x1E, 0x4A, 0x9C)):          # the docs' tag colors
        assert contrast_ratio(color, (0xCC, 0xC3, 0xC6)) >= 4.5
    assert contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)


def test_ac27_readable_over_any_backdrop(tmp_path):
    """The box fill probed on screen over black, white, grey, and noise backdrops."""
    results = {}
    for name, color in [("black", "#000000"), ("white", "#FFFFFF"), ("grey", "#808080")]:
        root = make_text_game(tmp_path / name, D=f'scene back⏎    "{"l" * 20}"',
                              T=f'image back = "{color}"')
        s = play_one_line(root)
        fill = s.px(150, 600)
        ink = min((s.px(x, y) for y in range(536, 568) for x in range(180, 330)), key=sum)
        results[name] = (contrast_ratio(TEXT, fill), ink, contrast_ratio(NAME, fill))
    assert results["black"][0] >= 7.5 and results["white"][0] >= 12.3
    assert results["grey"][0] >= 7.5
    for ratio, ink, indicator in results.values():
        assert all(abs(a - b) <= 2 for a, b in zip(ink, TEXT)), ink
        assert indicator >= 4.0


# --- F05 step 7: the dev launch checks (W40, W40b, W41, W44) -----------------------------------

def launch_warnings(root: Path, caplog, *, dev: bool = True) -> list[str]:
    """Every WARNING (or worse) record of an App A launch of ``root``, up to the frame after
    the load screen hands over."""
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        s = Session(root, dev=dev)

        def script(s):
            yield from s.until(lambda: s.app.story is not None and not s.app.loading)
            yield

        assert s.play(script) == 0
    # F12 and F11: a release run of a game with no [game] id also gives W53 and W80 (not
    # text warnings).
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
            and getattr(r, "code", None) not in ("W53", "W80")]


def w40(boxes: int, size: int, line: int = 7) -> str:
    clicks = "once" if boxes == 2 else f"{boxes - 1} times"
    return (f"script/main.vns, line {line}: this line needs {boxes} text boxes at text size "
            f"{size}, so the player clicks {clicks} partway through. To choose where it "
            "breaks, split it into two lines.")


FOUR = "a\\nb\\nc\\nd"
SIZE_20 = "[theme.textbox]\ntext_size = 20\n"


@pytest.mark.parametrize("game, expected", [
    (dict(S="a\\nb\\nc"), []),
    (dict(S=FOUR), [w40(2, 28)]),
    (dict(S="a\\nb\\nc\\nd\\ne\\nf\\ng"), [w40(3, 28)]),
    (dict(S=FOUR, config=SIZE_20), []),
    (dict(S="a\\nb\\nc\\nd\\ne", config=SIZE_20), [w40(2, 20)]),
    (dict(S="a\\nb\\n{var=v}", T='default v = "' + "x " * 100 + '"'), [w40(2, 28)]),
    (dict(S="a\\nb\\n{var=v}", T='default v = "c"'), []),
    (dict(D="⏎    ".join([f'"{FOUR}"'] * 25)),
     [w40(2, 28, line) for line in range(7, 27)]
     + ["…and 5 more lines need more than one text box."]),
], ids=["three", "four", "seven", "four-at-20", "five-at-20", "long-var", "short-var", "25"])
def test_ac33_lines_that_need_more_than_one_box(tmp_path, caplog, game, expected):
    root = make_text_game(tmp_path / "game", **game)
    assert launch_warnings(root, caplog) == expected


def test_ac33_release_runs_skip_the_check(tmp_path, caplog):
    root = make_text_game(tmp_path / "game", S=FOUR)
    assert launch_warnings(root, caplog, dev=False) == []


def plain_thought(root: Path) -> Path:
    """Template X with line 3's thought made plain: its ``#1e4a9c`` passes only on the
    default box, so rows that change the box would also warn about it."""
    main = root / "script" / "main.vns"
    lines = main.read_text(encoding="utf-8").split("\n")
    assert lines[2].startswith("define thought")
    lines[2] = 'define thought = Character("", text_italic=True)'
    main.write_text("\n".join(lines), encoding="utf-8")
    return root


DARK = '[theme.textbox]\nfill_color = "#3a2a3f"\nfill_opacity = 0.85\ntext_color = "#fff4f8"\n'
W41_GREY = ("script/main.vns, line 9: grey's name color #a0a0a0 is hard to read on the name "
            "plate (2.2:1; names need at least 3:1). Pick a color further from the plate's "
            "#ffe6f0.")
W41_T2 = ("script/main.vns, line 9: t2's text_color #b0a0b0 is hard to read on the text box "
          "(3.3:1 over a white picture; text needs at least 4.5:1). Pick a lighter color, or "
          "raise fill_opacity under [theme.textbox] in config.toml.")
W44_LOW = ("config.toml: [theme.textbox] text_color #d0c0c8 on fill_color #3a2a3f at "
           "fill_opacity 0.4 gives 1.3:1 over a white picture; text needs at least 4.5:1. "
           "Raise fill_opacity or pick colors further apart.")


@pytest.mark.parametrize("T, config, expected", [
    ('define grey = Character("Grey", color="#a0a0a0")', "", [W41_GREY]),
    ('define ok = Character("Ok", color="#808080")', "", []),
    ('define t2 = Character("", text_color="#b0a0b0")', DARK, [W41_T2]),
    ('define t2 = Character("", text_color="#c0c0c0")', DARK, []),
    ("", '[theme.textbox]\ntext_color = "#d0c0c8"\nfill_color = "#3a2a3f"\n'
         "fill_opacity = 0.4\n", [W44_LOW]),
    ("", "[theme.textbox]\nfill_opacity = 0.6\n", ["gives 4.3:1 over a black picture"]),
    ("", "[theme.textbox]\nfill_opacity = 0.62\n", []),
], ids=["grey", "ok", "t2", "t2-ok", "w44", "w44-0.6", "w44-0.62"])
def test_ac34_hard_to_read_colors(tmp_path, caplog, T, config, expected):
    root = plain_thought(make_text_game(tmp_path / "game", T=T, config=config))
    got = launch_warnings(root, caplog)
    if expected and expected[0].startswith("gives"):            # G1: "contains"
        assert len(got) == 1 and expected[0] in got[0] and got[0].startswith("config.toml: ")
    else:
        assert got == expected
    assert launch_warnings(root, caplog, dev=False) == []        # release: none


@pytest.mark.parametrize("text, box, backdrop, shade", [
    ("#b0a0b0", "#3a2a3f", "white", "lighter"),     # light text on a dark box
    ("#b0a0b0", "#3a2a3f", "black", "lighter"),
    ("#606060", "#ffe6f0", "black", "darker"),      # dark text on a light box
    ("#606060", "#ffe6f0", "white", "darker"),
])
def test_ac34_w41_direction_follows_text_against_box(text, box, backdrop, shade):
    """W41's advice moves the text away from the box: "darker" when the text is darker
    than the box's fill, else "lighter", whichever picture is the worse one."""
    message = format_message("W41", ("text", "t2", text, 3.3, backdrop, box))
    assert f"Pick a {shade} color," in message


def test_template_and_default_colors_pass(tmp_path, caplog):
    """06 §0.4: the template launches in dev with no warning (its colors pass W41)."""
    assert launch_warnings(make_text_game(tmp_path / "game", S="x"), caplog) == []


def test_w41_once_per_character_and_not_for_a_plate_that_never_shows(tmp_path, caplog):
    root = make_text_game(tmp_path / "game", T='define pale = Character("", color="#f4d0dc")⏎'
                          'define a = Character("A", color="#f4d0dc")⏎define b = a')
    got = launch_warnings(root, caplog)
    assert len(got) == 1 and got[0].startswith("script/main.vns, line 10: a's name color")


def test_ac40_a_thousand_overflowing_lines_give_21_records(tmp_path, caplog):
    root = make_text_game(tmp_path / "game", D="⏎    ".join([f'"{FOUR}"'] * 1000))
    got = launch_warnings(root, caplog)
    assert len(got) == 21 and got[:20] == [w40(2, 28, line) for line in range(7, 27)]
    assert got[20] == "…and 980 more lines need more than one text box."


def test_the_speaker_style_and_values_are_measured(tmp_path, caplog):
    """W40 measures the speaker's italic face, a define's value, and a number."""
    check = launched_check(make_text_game(
        tmp_path / "game", D='thought "{var=w} {var=n} {var=f} {var=gone}"',
        T='define w = "word"⏎define n = 12⏎define f = [1]'))
    say = next(s for s in check.program.iter_statements() if check.checks_line(s))
    body = check.resolve(say)
    assert [(p.text, p.style.italic, p.style.color) for p in body.pieces] == [
        ("word 12  ", True, "#1e4a9c")]


# --- AC-F05-41: no author code runs in the check -----------------------------------------------

def launched_check(root: Path, *, size: int = 28) -> TextLaunchCheck:
    """The text check of ``root``'s story, launched headless with the bundled faces."""
    paths = GamePaths.for_game(root)
    program = load_story(paths).program
    assert program is not None
    launch = run_launch(program)
    assert launch.namespace is not None, launch.errors
    return TextLaunchCheck(program, launch.namespace, assets=make_assets(paths),
                           faces=BUNDLED_FACES, theme=TextboxTheme(text_size=size))


def test_ac41_the_check_runs_no_author_code(tmp_path, monkeypatch):
    root = make_text_game(tmp_path / "game", S="a\\nb\\n{var=v}",
                          T="default v = __import__('os').system('x')")
    calls = []
    monkeypatch.setattr(os, "system", lambda *args: calls.append(args) or 0)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: calls.append(args))
    check = launched_check(root)
    assert check.run() == ()
    assert check.shown("v") == "" and calls == []


# --- AC-F05-14: the page count agrees everywhere ------------------------------------------------

def assert_pages_agree(check: TextLaunchCheck) -> int:
    """Every line of ``check``'s story: ``count_pages`` equals the layout, and the fast path
    says "one page" only when the layout does. Returns how often the fast path was taken."""
    fast = 0
    for stmt in check.program.iter_statements():
        if not check.checks_line(stmt):
            continue
        body = check.resolve(stmt)
        pages = LineLayout(body, check.ctx).all_pages()
        assert count_pages(body, check.ctx) == pages
        if check.fast_one_page(body):
            fast += 1
            assert pages == 1, stmt.text
        assert check.pages(body) == pages
    return fast


@pytest.mark.parametrize("size", [20, 28, 48])
def test_ac14_the_example_game(size):
    assert assert_pages_agree(launched_check(EXAMPLE, size=size)) > 5


@pytest.mark.parametrize("lines", [50, pytest.param(2000, marks=pytest.mark.slow)])
def test_ac14_the_text_corpus(tmp_path, lines):
    root = write_corpus(tmp_path / "corpus", seed=1, lines=lines)
    for size in (20, 28, 48):
        assert assert_pages_agree(launched_check(root, size=size)) > 0


@pytest.mark.slow                            # 2,000 lines of up to 10,000 characters: ~4 s
def test_ac33_the_check_runs_in_slices_while_loading(tmp_path, caplog):
    root = write_corpus(tmp_path / "corpus", seed=1, lines=2000)
    steps: list[bool] = []
    real_step = TextLaunchCheck.step
    frames: list[float] = []
    real_update = StoryLoadScreen.update

    def step(self):
        steps.append(app.loading)
        return real_step(self)

    def update(self, dt, *, is_top):
        before = len(steps)
        started = time.perf_counter()
        real_update(self, dt, is_top=is_top)
        if len(steps) > before:
            frames.append(time.perf_counter() - started)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(TextLaunchCheck, "step", step)
        mp.setattr(StoryLoadScreen, "update", update)
        with caplog.at_level(logging.WARNING):
            s = Session(root)
            app = s.app

            def script(s):
                yield from s.until(lambda: s.app.story is not None and not s.app.loading)

            assert s.play(script) == 0
    assert len(frames) > 5 and all(steps)
    assert max(frames) <= 0.1, max(frames)
    w40s = [r for r in caplog.records if r.name == "vn.text"]
    assert len(w40s) == 21 and "more lines need more than one text box" in w40s[-1].getMessage()


# --- AC-F05-47: the example game is warning-free --------------------------------------------------

def test_ac47_the_example_game_launches_without_warnings(tmp_path, caplog):
    root = tmp_path / "game"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("logs", "characters", "persistent", "saves", "settings"))
    assert launch_warnings(root, caplog) == []
    caplog.clear()
    program = load_story(GamePaths.for_game(root)).program
    images = tuple(sorted(p.relative_to(root).as_posix()
                          for p in (root / "images").rglob("*") if p.is_file()))
    from tests.runtime.corpus import EXAMPLE_PICKS, example_minigames, play
    with caplog.at_level(logging.DEBUG):
        for seed in range(1, 6):                    # run R, seeds 1..5; F07: every choice
            inputs = play(program, seed, images, EXAMPLE_PICKS[seed]).inputs
            commands = run_headless(program, seed=seed, image_files=images, dev=True,
                                    inputs=inputs, minigames=example_minigames())
            assert commands[-1] == StoryEnded(), seed
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


# --- F30 step 5: AC-F30-34 (W189), AC-F30-35 (W190) ----------------------------------------------

def _f30_logs(tmp_path, monkeypatch, caplog, script: str, *, offer: bool, dev: bool = True):
    from engine.app import fourthwall
    monkeypatch.setattr(fourthwall, "read_login_name", reader())
    root = make_text_game(tmp_path / f"g{offer}{dev}", script=script,
                          config=f"[meta]\nusername = {'true' if offer else 'false'}\n")
    s = Session(root, dev=dev)
    caplog.clear()

    def run(s: Session):
        yield from s.until(lambda: s.line_text() is not None)
        for _ in range(30):
            yield

    with caplog.at_level(logging.DEBUG):
        s.play(run, last=600)
    return [(r.name.rsplit(".", 1)[-1], r.getMessage()) for r in caplog.records
            if r.levelno >= logging.WARNING]


def test_ac_f30_34_w189_the_offer_is_off(tmp_path, monkeypatch, caplog):
    lines = ['define hana = Character("Hana")', "label start:"] + ['    "Plain."'] * 28
    for n in (7, 12, 15, 20, 30):
        lines[n - 1] = '    hana "Hi, {username}."'
    script = "\n".join(lines) + "\n"
    logs = _f30_logs(tmp_path, monkeypatch, caplog, script, offer=False)
    w189 = [(area, m) for area, m in logs if "username" in m]
    assert len(w189) == 2, w189
    assert w189[0][0] == "text" and "line 7: this line uses {username}, but [meta] username " \
        'is off in config.toml, so every player sees "friend". Set username = true under ' \
        "[meta] to let players choose." in w189[0][1]
    assert w189[1] == ("text", "…and 4 more lines use {username}.")
    assert not [m for _, m in _f30_logs(tmp_path, monkeypatch, caplog, script, offer=False,
                                        dev=False) if "username" in m]
    assert not [m for _, m in _f30_logs(tmp_path, monkeypatch, caplog, script, offer=True)
                if "{username}" in m]


def test_ac_f30_35_w190_identity_in_dollar_code(tmp_path, monkeypatch, caplog):
    lines = ["init:", "label start:"] + ['    "Plain."'] * 14
    lines[0] = "define hana = Character(\"Hana\")"
    lines[8] = "    $ me = getpass.getuser() if False else 'x'"
    lines[11] = "    $ env = 'os.environ' and len(str(os.environ)) if False else 0"
    lines[14] = '    $ k = "USERNAME"'
    script = "\n".join(lines) + "\n"
    logs = _f30_logs(tmp_path, monkeypatch, caplog, script, offer=True)
    w190 = [(area, m) for area, m in logs if "reads the computer's user name" in m
            or "read identity" in m]
    assert len(w190) == 2, logs
    assert w190[0][0] == "script" and "line 9: this Python code reads the computer's user " \
        "name or environment." in w190[0][1]
    assert w190[1] == ("script", "…and 2 more lines read identity.")
    assert not [m for _, m in _f30_logs(tmp_path, monkeypatch, caplog, script, offer=True,
                                        dev=False) if "identity" in m or "user name" in m]


def test_ac_f30_34_35_the_scan_runs_in_the_check_slices(tmp_path, monkeypatch):
    """AC-F02-63 with F30: W189/W190's scan walks nothing when the check is made (a
    1,000,000-word story took a 0.5 s frame), runs in ``TextLaunchCheck.step``s after the
    line walk, and finds what the one-go scan finds, in the same order."""
    from engine.app import text_check
    from engine.script.program import Program
    root = tmp_path / "g"
    (root / "script").mkdir(parents=True)
    (root / "script" / "main.vns").write_text(
        'define hana = Character("Hana")\ndefault env = "LOGNAME"\nlabel start:\n'
        '    hana "Hi, {username}."\n    $ me = "getpass"\n    "Plain."\n'
        '    "{username}!"\n    $ k = "USERNAME"\n', encoding="utf-8")
    check = launched_check(root)
    program = check.program
    walks = []
    real_walk = Program.iter_statements
    monkeypatch.setattr(Program, "iter_statements",
                        lambda self: walks.append(1) or real_walk(self))
    monkeypatch.setattr(text_check, "FOURTHWALL_CHUNK", 1)
    check.wall = text_check.FourthWallScan(program, offered=False, fallback="friend")
    assert walks == [] and check.fourthwall == ()
    steps = 0
    while not check.step():
        steps += 1
    assert steps > 10 and check.wall is None
    assert check.fourthwall == text_check.fourthwall_warnings(program, offered=False,
                                                              fallback="friend")
    assert [(area, m.split(": ")[0]) for area, m in check.fourthwall] == [
        ("text", "script/main.vns, line 4"), ("text", "…and 1 more lines use {username}."),
        ("script", "script/main.vns, line 2"), ("script", "…and 2 more lines read identity.")]

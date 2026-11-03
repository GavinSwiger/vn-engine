"""F43 P7: per-character font fallback (``render/fontchain``; 04 §7.4, PR-F43-13).
AC-F43-20 (the chain half; the error screen's Noto Sans Regular is W2's) and review I-14."""

import re
from pathlib import Path

import pygame

from engine.core.fontcmap import Coverage, read_coverage
from engine.core.paths import engine_data_dir
from engine.render.fontchain import ChainFont

FONTS = engine_data_dir() / "fonts"
ENGINE = Path(__file__).resolve().parents[2] / "engine"
RED = (255, 0, 0)


def _font(name: str, size: int = 24) -> pygame.font.Font:
    return pygame.font.Font(FONTS / name, size)


# --- AC-F43-20: each character draws with the first chain font that has it, ending in the
# bundled Noto Sans's box -----------------------------------------------------------------------

def test_chain_order_per_character_ending_in_the_box():
    primary = _font("NotoSans-Regular.ttf")
    second = _font("NotoSans-Bold.ttf")
    third = _font("NotoSans-Italic.ttf")
    noto = _font("NotoSans-Regular.ttf")
    loads = []

    def load_second():
        loads.append("second")
        # é, "e" + combining acute, Greek small letters; also "a", which the primary wins.
        return second, Coverage.from_ranges([(0xE9, 0xE9), (0x301, 0x301), (0x3B1, 0x3C9),
                                             (ord("a"), ord("a")), (ord("e"), ord("e"))])

    def load_third():
        loads.append("third")
        # Greek too (the second wins it) and Cyrillic small letters.
        return third, Coverage.from_ranges([(0x3B1, 0x3C9), (0x430, 0x44F)])

    noto_coverage = read_coverage((FONTS / "NotoSans-Regular.ttf").read_bytes())
    assert noto_coverage is not None and not noto_coverage.has(ord("漢"))
    chain = ChainFont([(primary, Coverage.from_ranges([(0x20, 0x7E)])), load_second,
                       lambda: None,                       # an unusable font: skipped
                       load_third, (noto, noto_coverage)])
    names = {id(primary): "primary", id(second): "second", id(third): "third",
             id(noto): "noto"}

    def runs(text):
        return [(names[id(font)], piece) for font, piece in chain.runs(text)]

    # ASCII on a primary with printable ASCII: one run, and no fallback is read.
    assert runs("Hi, a!") == [("primary", "Hi, a!")]
    assert loads == [] and chain.size("Hi, a!") == primary.size("Hi, a!")
    # First font that has each grapheme, in chain order; "e" + U+0301 stays one grapheme
    # (the primary lacks the mark, so the second, which has both, draws it); nothing has
    # 漢, so the last font draws its box.
    assert runs("café αж é 漢!") == [
        ("primary", "caf"), ("second", "é"), ("primary", " "), ("second", "α"),
        ("third", "ж"), ("primary", " "), ("second", "é"), ("primary", " "),
        ("noto", "漢"), ("primary", "!")]
    assert loads == ["second", "third"] and chain.loaded == 4
    assert runs("café αж 漢!") == [                      # no marks: per character, same picks
        ("primary", "caf"), ("second", "é"), ("primary", " "), ("second", "α"),
        ("third", "ж"), ("primary", " "), ("noto", "漢"), ("primary", "!")]

    # Measuring and drawing: runs side by side, on the primary's height and baseline.
    text = "a漢b"
    widths = [primary.size("a")[0], noto.size("漢")[0], primary.size("b")[0]]
    assert chain.size(text) == (sum(widths), primary.get_height())
    assert len(chain.metrics(text)) == 3 and chain.metrics(text)[1] == noto.metrics("漢")[0]
    surface = chain.render(text, True, RED)
    assert surface.get_size() == chain.size(text)
    box = noto.render("漢", True, RED)
    box_part = surface.subsurface((widths[0], 0, widths[1], box.get_height()))
    assert pygame.image.tobytes(box_part, "RGBA") == pygame.image.tobytes(box, "RGBA")
    plain = chain.render(text, False, RED, (0, 0, 40))
    assert plain.get_size() == chain.size(text) and plain.get_at((0, 0)) == (0, 0, 40, 255)


# --- Review I-14: ChainFont has every Font method and attribute the engine calls -------------

# A Font name used on any receiver whose name says "font" (``font.size``, ``layout.font
# .get_linesize``, ``font_at(n).size``). Names only fonts have count on any receiver
# (``handle.get_linesize()``, ``ref.get_ascent()``); Surface and others share the rest.
_FONT_RECEIVER = re.compile(r"(?i)\b\w*font\w*(?:\([^()\n]*\))?\.([A-Za-z_]\w*)\b")
_ANY_RECEIVER = re.compile(r"\.([A-Za-z_]\w*)\b")
_SHARED_NAMES = {"size", "render", "name", "bold", "italic", "align", "outline", "underline",
                 "strikethrough", "point_size", "get_height"}


def _font_names_used() -> dict[str, str]:
    """Font attribute name → the first place engine code uses it. Studio (Tk fonts) and
    this module itself are left out."""
    font_names = {name for name in dir(pygame.font.Font) if not name.startswith("_")}
    distinctive = font_names - _SHARED_NAMES
    used: dict[str, str] = {}
    for path in sorted(ENGINE.rglob("*.py")):
        rel = path.relative_to(ENGINE).as_posix()
        if rel.startswith("tools/editor/") or rel == "render/fontchain.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            names = {m.group(1) for m in _FONT_RECEIVER.finditer(line)} & font_names
            names |= {m.group(1) for m in _ANY_RECEIVER.finditer(line)} & distinctive
            for name in names:
                used.setdefault(name, f"engine/{rel}:{number}")
    return used


def test_chain_font_has_every_font_method_the_engine_uses():
    used = _font_names_used()
    # The scan works: it finds the calls text layout and the minigame API are known to make.
    assert {"size", "render", "metrics", "get_linesize", "get_ascent", "get_descent"} <= set(used)
    missing = {name: where for name, where in used.items() if not hasattr(ChainFont, name)}
    assert missing == {}, f"ChainFont lacks Font names the engine uses: {missing}"
    # Same kind: a method stays a method, an attribute stays an attribute.
    wrong_kind = {name for name in used
                  if callable(getattr(pygame.font.Font, name))
                  != callable(getattr(ChainFont, name))}
    assert wrong_kind == set()

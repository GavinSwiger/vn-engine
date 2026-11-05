"""Palettes in, color schemes out (2026-11-05): the formats other tools write
(``palette.read_palette``), a palette's roles (``derive_roles``), the genre schemes built
from them, and ``[theme.scheme]`` laid over a preset."""

import struct

import pytest

from engine.app.ui_contrast import LOOK_PAIRS, PAIRS, pair_ratios
from engine.core import palette
from engine.core.palette import PaletteError, contrast, derive_roles, read_palette
from engine.core.schemes import ROLES, SCHEMES, custom_colors, scheme_colors

F49 = ("sakura", "pocket", "amber", "synthwave", "vaporwave", "groovy")
GENRES = ("neon_vice", "high_fantasy", "grimdark", "gothic", "noir", "paper", "blood_moon",
          "cyberpunk", "rose_garden", "starship", "brass", "seaside", "enchanted_forest",
          "frost", "harvest", "royal", "sepia", "cotton_candy", "eldritch", "witching_hour",
          "wasteland", "cozy_cafe")
FIVE = ("#264653", "#2A9D8F", "#E9C46A", "#F4A261", "#E76F51")


def _ase(*colors: tuple[bytes, tuple[float, ...]]) -> bytes:
    blocks = b""
    for model, values in colors:
        name = "c\0".encode("utf-16-be")
        body = struct.pack(">H", 2) + name + model + struct.pack(f">{len(values)}f", *values)
        body += struct.pack(">H", 2)
        blocks += struct.pack(">HI", 1, len(body)) + body
    group = struct.pack(">HI", 0xC001, 4) + b"\0\0\0\0"
    return b"ASEF" + struct.pack(">HHI", 1, 0, len(colors) + 1) + group + blocks


def test_read_palette_reads_what_other_tools_write():
    expected = tuple(FIVE)
    # Coolors link, a Lospec .hex file, a pasted list, CSS.
    assert read_palette("https://coolors.co/264653-2a9d8f-e9c46a-f4a261-e76f51") == expected
    assert read_palette("264653\n2a9d8f\ne9c46a\nf4a261\ne76f51\n") == expected
    assert read_palette("#264653, #2A9D8F #E9C46A;#F4A261 #e76f51 #264653") == expected
    assert read_palette(":root { --a: #fff; --b: rgb(38, 70, 83); --c: #11223380; }") == (
        "#FFFFFF", "#264653", "#112233")
    assert read_palette("facade decade #000000") == ("#000000",)   # hex words aren't colors
    # GIMP .gpl, JASC .pal, Paint.NET .txt.
    gpl = "GIMP Palette\nName: Five\nColumns: 5\n# from Lospec\n38 70 83\tDeep\n42 157 143\n"
    assert read_palette(gpl) == FIVE[:2]
    assert read_palette("JASC-PAL\r\n0100\r\n2\r\n38 70 83\r\n42 157 143\r\n") == FIVE[:2]
    assert read_palette(";paint.net Palette File\n;Colors: 2\nFF264653\nFF2A9D8F\n") == FIVE[:2]
    # Photoshop .act and Adobe .ase.
    act = bytes([38, 70, 83, 42, 157, 143]) + bytes(762) + struct.pack(">HH", 2, 0xFFFF)
    assert read_palette(act) == FIVE[:2]
    ase = _ase((b"RGB ", (38 / 255, 70 / 255, 83 / 255)), (b"CMYK", (0, 0, 0, 1)),
               (b"Gray", (1.0,)), (b"LAB ", (50.0, 0.0, 0.0)))
    assert read_palette(ase) == ("#264653", "#000000", "#FFFFFF")
    for bad, text in (("no colors here", palette.NOTHING), (b"ASEF\0\1\0\0\0\0\0\5", palette.BAD_ASE),
                      (b"#000000" * 200_000, palette.TOO_BIG)):
        with pytest.raises(PaletteError) as caught:
            read_palette(bad)
        assert caught.value.text == text
    assert len(read_palette(" ".join(f"#{n:06X}" for n in range(1000)))) == palette.MAX_COLORS


@pytest.mark.parametrize("colors", [FIVE, ("#000000", "#FFFFFF"), ("#7F7F7F",),
                                    ("#FFD1DC", "#FFE5B4", "#E0BBE4", "#B5EAD7"),
                                    ("#0B0B0B", "#141414", "#1E1E1E", "#E10600")])
def test_derived_roles_meet_w67_on_every_fill(colors):
    for dark in (None, True, False):
        found = derive_roles(colors, dark)
        roles = found.roles
        assert list(roles) == list(ROLES)
        fills = [roles[r] for r in ("fill", "soft", "focus", "pressed")]
        assert all(contrast(roles["text"], f) >= 4.5 for f in fills)
        assert contrast(roles["accent"], roles["fill"]) >= 4.5
        assert contrast(roles["muted"], roles["fill"]) >= 4.5
        assert all(contrast(roles[r], f) >= 3 for r in ("accent", "accent2")
                   for f in fills[2:])
        if dark is not None:
            assert found.dark is dark


def test_derive_picks_the_way_with_more_contrast_and_the_liveliest_accent():
    # Coolors' five: a dark scheme on its deep teal, accents from its warm and green colors.
    found = derive_roles(FIVE)
    assert found.dark is True and found.roles["fill"] == "#1B313A"
    assert found.roles["border"] == "#2A9D8F" and found.roles["accent"] == "#F6B079"
    # Near-blacks and one red: white text, the red as the accent (made lighter to read).
    night = derive_roles(("#0B0B0B", "#141414", "#1E1E1E", "#E10600"))
    assert night.dark is True and night.roles["fill"] == "#0B0B0B"
    assert night.roles["text"] == "#FFFFFF" and night.roles["accent"] == "#ED6A66"
    # A mid-tone background is darkened (or lightened) until text reads on it.
    assert derive_roles(("#7F7F7F",), dark=True).roles["fill"] == "#2C2C2C"
    with pytest.raises(PaletteError):
        derive_roles(())


def test_genre_schemes_follow_f49_and_meet_w67(load):
    assert tuple(SCHEMES) == F49 + GENRES
    for id_ in GENRES:
        cfg = load(f'[theme]\npreset = "{id_}"\n').config.theme
        for pair in PAIRS + LOOK_PAIRS:
            worst = min(pair_ratios(cfg, pair))
            assert worst >= pair.minimum - 0.05, (id_, pair.fg, pair.bg, worst)


def test_theme_scheme_replaces_roles_over_the_preset(load):
    rgb = palette.rgb_of
    amber = SCHEMES["amber"].colors
    result = load('[theme]\npreset = "amber"\n[theme.scheme]\nname = "Mine"\n'
                  'accent = "#112233"\nfill = "#FAFAFA"\n')
    assert result.errors == [] and result.warnings == []
    theme = result.config.theme
    assert theme.panel.fill_color == rgb("#FAFAFA")
    assert theme.slider.fill_color == rgb("#112233")
    assert theme.panel.text_color == rgb(amber["text"])          # the preset's other roles
    assert theme.scheme.name == "Mine"
    # No preset: over Sakura's roles, without Sakura's single-token extras.
    plain = load('[theme.scheme]\naccent = "#112233"\n').config.theme
    assert plain.slider.fill_color == rgb("#112233")
    assert plain.flowchart.fill_color == rgb(SCHEMES["sakura"].colors["fill"])
    # The author's own [theme] keys still win; a wrong role is the walk's error.
    mine = load('[theme.scheme]\nfill = "#000000"\n[theme.panel]\nfill_color = "#123456"\n')
    assert mine.config.theme.panel.fill_color == rgb("#123456")
    bad = load('[theme.scheme]\nfill = "black"\n')
    assert len(bad.errors) == 1 and "[theme.scheme] fill" in bad.errors[0].format()
    assert custom_colors("amber", {}) == scheme_colors("amber")

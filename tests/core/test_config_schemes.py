"""F49 step S1: the color-scheme registry and ``[theme] preset`` / ``[style.<name>.theme]
preset`` in config (F49 SPEC §3, §5; AC-F49-01, 02, 03, 05, 06, 07; 07 I-7)."""

import ast
import dataclasses
import re
from pathlib import Path
from types import MappingProxyType

import pytest

from engine.app.ui_contrast import LOOK_PAIRS, PAIRS, contrast_warnings
from engine.core import schemes
from engine.core.config_schema import SchemeName, Table, ThemeConfig, config_fields
from engine.core.schemes import (FOLLOWING_TOKENS, NEUTRAL_TOKENS, ROLE_TOKENS, ROLES,
                                 SCHEMES, scheme, scheme_colors)
from engine.render.nvllayout import nvl_look
from engine.ui.looks import Looks
from engine.ui.menus import UiOverrides
from engine.ui.theme import plain_theme

# §3.1, the user's exact values (D1), columns in ``ROLES`` order.
TABLE = """
sakura | Sakura | #FFF4F8 | #3D2B36 | #F0A0C0 | #A02860 | #A02860 | #FFE6F0 | #FFD6E8 | #FFC2DC | #6E5E68 | #C8B8C2 | #7E5C74
pocket | Pocket LCD | #9BBC0F | #0F380F | #306230 | #0F380F | #0F380F | #8BAC0F | #C4D96A | #8BAC0F | #244A24 | #8BAC0F | #306230
amber | Amber Terminal | #140C02 | #FFB000 | #9A6800 | #FFCC00 | #FFCC00 | #2A1A04 | #3A2604 | #4A3006 | #B07A14 | #3A2604 | #9A6800
synthwave | Synthwave Sunset | #262335 | #F2E9FF | #CA7CD8 | #FF68A8 | #64CFF7 | #34294F | #3D2E5C | #4A3570 | #9A90B4 | #4A3F66 | #5A4A7A
vaporwave | Vaporwave Dream | #FBE6F8 | #3A2B5C | #9F63C4 | #674AB3 | #137566 | #C6F5F2 | #C6F5F2 | #A8EDE6 | #6E5E82 | #D8C8E8 | #9F63C4
groovy | Groovy '70s | #F3E6C8 | #3B2416 | #D08A1E | #9E3A12 | #2F6F6A | #F2D49B | #F2D49B | #E8C07A | #6E5848 | #D9C9A8 | #8A6A4A
"""
ROWS = [[cell.strip() for cell in line.split("|")] for line in TABLE.strip().splitlines()]


def rgb(hex_color: str) -> tuple[int, int, int]:
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))


def token(cfg: object, path: str) -> object:
    for part in path.split("."):
        cfg = getattr(cfg, part)
    return cfg


def theme_leaves(cls: type = ThemeConfig, prefix: str = "") -> dict[str, dataclasses.Field]:
    out: dict[str, dataclasses.Field] = {}
    for key, found in config_fields(cls).items():
        validator = found.metadata["validator"]
        if isinstance(validator, Table):
            out.update(theme_leaves(validator.cls, f"{prefix}{key}."))
        else:
            out[prefix + key] = found
    return out


# --- AC-F49-01 — the registry --------------------------------------------------------------------

def test_ac_f49_01_registry_holds_the_six_schemes_exactly():
    # F49's six first, exactly; 2026-11-05's genre schemes after (``test_palette``).
    assert [row[0] for row in ROWS] == list(SCHEMES)[:6]
    assert len(ROLES) == 11
    for id_, name, *colors in ROWS:
        found = scheme(id_)
        assert found is SCHEMES[id_] and found.id == id_ and found.name == name
        assert dict(found.colors) == dict(zip(ROLES, colors))
        assert re.fullmatch(r"[a-z][a-z0-9_]{0,31}", id_) and len(name) <= 24
    assert scheme("Amber") is None and scheme("nope") is None
    # 07 I-7: read-only, so config code can't change the registry.
    assert isinstance(SCHEMES, MappingProxyType) and isinstance(ROLE_TOKENS, MappingProxyType)
    for found in SCHEMES.values():
        assert isinstance(found.colors, MappingProxyType)
        assert isinstance(found.extra, MappingProxyType)
        with pytest.raises(dataclasses.FrozenInstanceError):
            found.name = "x"                                          # type: ignore[misc]
    assert isinstance(scheme_colors("amber"), MappingProxyType)
    with pytest.raises(TypeError):
        scheme_colors("amber")["panel.fill_color"] = "#000000"        # type: ignore[index]
    with pytest.raises(KeyError):
        scheme_colors("neon")
    # Studio's choice labels come from the registry.
    names = SchemeName()
    assert names.options == tuple(SCHEMES) and dict(names.labels) == {
        id_: found.name for id_, found in SCHEMES.items()}
    assert all(dict(names.labels)[row[0]] == row[1] for row in ROWS)
    # Pure data: the registry imports nothing from the engine.
    tree = ast.parse(Path(schemes.__file__).read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(name.startswith("engine") for name in imported)


# --- AC-F49-02 — every color token is in exactly one group ------------------------------------

def test_ac_f49_02_every_color_token_is_in_one_group():
    colors = {path: f for path, f in theme_leaves().items() if path.endswith("_color")}
    mapped = [path for paths in ROLE_TOKENS.values() for path in paths]
    groups = mapped + list(FOLLOWING_TOKENS) + list(NEUTRAL_TOKENS)
    assert sorted(groups) == sorted(colors)                       # each exactly once
    assert (len(mapped), len(FOLLOWING_TOKENS), len(NEUTRAL_TOKENS)) == (64, 25, 6)  # F51 +2, F52 +5
    assert set(ROLE_TOKENS) == set(ROLES)
    for path in FOLLOWING_TOKENS:
        assert token(ThemeConfig(), path) is None, path
    for found in SCHEMES.values():
        assert set(found.extra) <= set(mapped), found.id
        assert set(scheme_colors(found.id)) == set(mapped)


# --- AC-F49-03 — Sakura is the engine defaults ---------------------------------------------------

def test_ac_f49_03_sakura_equals_the_engine_defaults(load):
    default = ThemeConfig()
    for path, value in scheme_colors("sakura").items():
        assert token(default, path) == rgb(value), path
    result = load('[theme]\npreset = "sakura"\n')
    assert result.errors == [] and result.warnings == []
    assert dataclasses.replace(result.config.theme, preset=None) == default
    assert contrast_warnings(plain_theme(result.config.theme), pairs=PAIRS + LOOK_PAIRS) == []


# --- AC-F49-05 — [theme] preset ------------------------------------------------------------------

def test_ac_f49_05_theme_preset_sets_the_mapped_tokens(load):
    amber = SCHEMES["amber"].colors
    result = load('[theme]\npreset = "amber"\n')
    assert result.errors == [] and result.warnings == []
    theme = result.config.theme
    assert theme.preset == "amber"
    assert theme.textbox.fill_color == rgb(amber["fill"]) == theme.panel.fill_color
    assert theme.textbox.text_color == rgb(amber["text"]) == theme.panel.text_color
    assert theme.textbox.border_color == rgb(amber["border"]) == theme.panel.border_color
    assert theme.textbox.name_tab.text_color == rgb(amber["accent"])
    assert theme.panel.heading.text_color == rgb(amber["accent"])
    for path, value in scheme_colors("amber").items():
        assert token(theme, path) == rgb(value), path
    # Following tokens keep following: NVL draws amber's text box.
    assert theme.nvl.fill_color is None
    assert (nvl_look(theme).fill_color, nvl_look(theme).text_color) == (
        rgb(amber["fill"]), rgb(amber["text"]))
    # Neutral tokens, fonts, sizes and opacities stay the engine's.
    default = ThemeConfig()
    colored = set(scheme_colors("amber")) | {"preset"}
    for path in theme_leaves():
        if path not in colored:
            assert token(theme, path) == token(default, path), path
    for path in NEUTRAL_TOKENS:
        assert token(theme, path) == token(default, path)
    # The author's own color wins; every spelling of the key gives the same config.
    own = '[theme.textbox]\nfill_color = "#FFFFFF"\n'
    spellings = ['[theme]\npreset = "amber"\n' + own,
                 own + '[theme]\npreset = "amber"\n',
                 'theme.preset = "amber"\n' + own,
                 '[theme]\npreset = "amber"\ntextbox.fill_color = "#FFFFFF"\n',
                 '[theme]\npreset = "amber"\ntextbox = { fill_color = "#FFFFFF" }\n']
    configs = []
    for text in spellings:
        found = load(text)
        assert found.errors == [] and found.warnings == [], text
        configs.append(found.config.theme)
    assert configs[0].textbox.fill_color == (255, 255, 255)
    assert configs[0].textbox.text_color == rgb(amber["text"])
    assert all(cfg == configs[0] for cfg in configs)
    # A path that meets a value that isn't a table: the walk's usual error, nothing else.
    bad = load('[theme]\npreset = "amber"\ntextbox = 3\n')
    assert [e.format() for e in bad.errors] == [
        "config.toml, line 3: [theme] textbox must be a section, but found 3"]
    assert bad.config.theme.panel.fill_color == rgb(amber["fill"])


# --- AC-F49-06 — an unknown or wrong preset ------------------------------------------------------

SCHEME_LIST = ", ".join(f'"{id_}"' for id_ in SCHEMES)


@pytest.mark.parametrize("label, prefix", [("[theme] preset", "[theme]\n\n"),
                                           ("[style.term.theme] preset",
                                            "[style.term.theme]\n\n")])
def test_ac_f49_06_unknown_and_wrong_presets(load, label, prefix):
    def run(value: str):
        return load(f"{prefix}preset = {value}\n")

    result = run('"amberr"')
    assert result.errors == [] and result.warnings == [
        f'config.toml, line 3: unknown color scheme "amberr" in {label} — did you mean '
        '"amber"?']
    assert run('"Amber"').warnings[0].endswith('— did you mean "amber"?')
    neon = run('"neon"')
    assert neon.errors == [] and neon.warnings == [
        f'config.toml, line 3: unknown color scheme "neon" in {label}. Use one of '
        f'{SCHEME_LIST}.']
    for found in (result, neon):
        assert found.config.theme == ThemeConfig()
        assert all(table.tokens == {} and table.preset is None
                   for table in found.config.style.values())
    wrong = run("3")
    assert [e.format() for e in wrong.errors] == [
        f"config.toml, line 3: {label} must be one of {SCHEME_LIST}, but found 3"]
    assert wrong.warnings == [] and wrong.config.theme.preset is None
    # The author's text is shown through echo(): controls escaped.
    assert "\\x1b" in run('"x\\u001b"').warnings[0]


# --- AC-F49-07 — a style's scheme ----------------------------------------------------------------

def test_ac_f49_07_a_style_scheme_over_the_base_scheme(load):
    result = load('[theme]\npreset = "sakura"\n[theme.textbox]\nfill_color = "#ABCDEF"\n'
                  '[style.term.theme]\npreset = "amber"\ntextbox.fill_color = "#000000"\n')
    assert result.errors == [] and result.warnings == []
    cfg = result.config
    table = cfg.style["term"]
    assert table.preset == "amber"
    assert not any(path.startswith("title.") for path in table.tokens)
    looks = Looks(plain_theme(cfg.theme), styles=cfg.style, playthroughs=cfg.playthrough,
                  overrides=UiOverrides(), image=lambda ref: None)
    base = looks.current().theme
    amber = SCHEMES["amber"].colors
    looks.set_style("term")
    theme = looks.current().theme.cfg
    assert theme.textbox.fill_color == (0, 0, 0)                          # the style's own
    assert theme.panel.fill_color == rgb(amber["fill"])                   # its scheme
    assert theme.button.focused.fill_color == rgb(amber["focus"])
    assert theme.button.text_color == rgb(amber["text"])
    assert theme.title == cfg.theme.title                                 # base title tokens
    looks.set_style(None)
    assert looks.current().theme is base
    assert base.cfg.textbox.fill_color == (0xAB, 0xCD, 0xEF)
    # A playthrough table can't name a scheme: F32's area error.
    play = load('[playthrough.2.theme]\npreset = "amber"\n')
    assert [e.format() for e in play.errors] == [
        "config.toml, line 2: [playthrough.2.theme.preset] isn't something a playthrough "
        "look can change. It can change title; use a style for the rest."]


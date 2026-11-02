"""F32 step 1: ``ui/looks.py``, the layers, choosing, and the cache (F32 ``06-acceptance.md``
AC-F32-04; ``04`` §4.1, §6.3; TR-F32-02; 07 I-2, I-6)."""

import ast
import dataclasses
import logging
from pathlib import Path

import pytest

from engine.core.config import load_config
from engine.core.config_schema import ThemeConfig, config_fields
from engine.core.paths import GamePaths
from engine.render.nvllayout import nvl_look
from engine.ui.looks import Looks, apply_tokens
from engine.ui.menus import UiOverrides
from engine.ui.theme import plain_theme

REPO = Path(__file__).parents[2]
TEMPLATE_U = (REPO / "tests" / "fixtures" / "F32" / "template" / "config.toml").read_text(
    encoding="utf-8")


def config(tmp_path):
    """Template U with ``[playthrough.0]`` and ``[playthrough.2.words] save = "Store"``."""
    text = TEMPLATE_U.replace('menu = "Pause"\n', 'menu = "Pause"\nsave = "Store"\n')
    (tmp_path / "config.toml").write_text(text + "[playthrough.0]\n", encoding="utf-8")
    result = load_config(GamePaths.for_game(tmp_path))
    assert result.errors == [] and result.warnings == []
    return result.config


def make(cfg, overrides=None, playthroughs=None):
    return Looks(plain_theme(cfg.theme), styles=cfg.style,
                 playthroughs=cfg.playthrough if playthroughs is None else playthroughs,
                 overrides=overrides or UiOverrides(), image=lambda ref: None)


def test_ac_f32_04_layers_choosing_and_the_cache(tmp_path, caplog):
    cfg = config(tmp_path)
    looks = make(cfg)
    base = looks.current()
    assert looks.key == (None, None) and base.theme is looks.base and looks.revision == 0

    # Choosing: the largest table N ≤ the number; the style is kept.
    keys = []
    for number in (5, 2, 1, -1):
        looks.choose(number)
        keys.append(looks.key[0])
    assert keys == [2, 2, 0, None]
    only_two = make(cfg, playthroughs={2: cfg.playthrough[2]})
    only_two.choose(1)
    assert only_two.key == (None, None) and only_two.revision == 0
    looks.set_style("ashes")
    looks.choose(2)
    assert looks.key == (2, "ashes")
    with caplog.at_level(logging.DEBUG, logger="vn.ui"):
        looks.set_style("nope")
    assert looks.key == (2, None)
    assert [r.levelno for r in caplog.records if r.name == "vn.ui"] == [logging.DEBUG]

    # Revision: +1 per key change, none for the same key; an earlier key is the cached Look.
    looks = make(cfg)
    base = looks.current()
    looks.choose(2)
    two = looks.current()
    assert looks.revision == 1
    looks.choose(2)
    assert looks.revision == 1
    looks.set_style("ashes")
    looks.set_style(None)
    assert looks.revision == 3 and looks.current() is two
    looks.choose(-1)
    assert looks.current() is base and looks.revision == 4

    # Parts: built once per Look; an unknown name is a programming error.
    built = []
    looks.add_part("textbox", lambda theme: built.append(theme) or object())
    looks.choose(2)
    looks.set_style("ashes")
    assert looks.part("textbox") is looks.part("textbox") and len(built) == 1
    assert built[0] is looks.current().theme.cfg
    with pytest.raises(AssertionError):
        looks.part("x")

    # Words: overrides, then the style, then the playthrough look, then None ([words]).
    overrides = UiOverrides()
    looks = make(cfg, overrides)
    looks.choose(2)
    looks.set_style("ashes")
    overrides.set_word("save", "O")
    assert looks.word("save") == "O"
    overrides.set_word("save", None)
    assert looks.word("save") == "Keep"
    looks.set_style(None)
    assert looks.word("save") == "Store"
    looks.choose(-1)
    assert looks.key == (None, None) and looks.word("save") is None

    # Title entries: the playthrough look's list.
    looks.choose(2)
    assert looks.title_entries() == ("new_game", "settings", "quit")
    looks.choose(-1)
    assert looks.title_entries() is None

    # The layers' theme: the style's and the playthrough's tokens over [theme].
    looks.choose(2)
    looks.set_style("ashes")
    theme = looks.current().theme.cfg
    assert theme.textbox.fill_color == (0x1E, 0x1A, 0x1C) and theme.textbox.text_size == 30
    assert theme.title.background_image == "gui/title_ashes.png"
    assert theme.title.music == "title_quiet.ogg"

    # apply_tokens: nothing → the same config; one token → only its table is rebuilt.
    base_cfg = cfg.theme
    assert apply_tokens(base_cfg, {}) is base_cfg
    color = (1, 2, 3)
    changed = apply_tokens(base_cfg, {"textbox.fill_color": color})
    assert changed.textbox == dataclasses.replace(base_cfg.textbox, fill_color=color)
    assert [name for name in config_fields(ThemeConfig)
            if getattr(changed, name) is not getattr(base_cfg, name)] == ["textbox"]
    assert nvl_look(changed).fill_color == color
    own = dataclasses.replace(base_cfg, nvl=dataclasses.replace(base_cfg.nvl,
                                                                fill_color=(9, 9, 9)))
    assert nvl_look(apply_tokens(own, {"textbox.fill_color": color})).fill_color == (9, 9, 9)
    with pytest.raises(AssertionError):
        apply_tokens(base_cfg, {"textbox.nope": 1})

    # ui/looks.py itself imports no pygame and nothing from engine.app (07 I-6).
    tree = ast.parse((REPO / "engine" / "ui" / "looks.py").read_text(encoding="utf-8"))
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
             for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [n for n in names if n.split(".")[0] == "pygame" or n.startswith("engine.app")]

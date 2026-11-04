"""F58 P4: the glow and preview tokens, Reduce motion's OS read and ``studio.json`` keys
(``01-design.md`` AC-F58-37, §6.2, §6.4; ADR-0008 Amendment 6 §1, §4; ``07`` I-11). No Tk."""

import ast
from pathlib import Path

from engine.tools.editor import studiostate, theme
from engine.tools.editor.studiostate import StudioState, decode_state, encode_state

ENGINE = Path(__file__).resolve().parents[3] / "engine"


def test_ac_f58_37_glow_and_preview_tokens_meet_3_to_1():
    expected = {"map.changed": "#89D185", "map.preview": "#4FC1FF",
                "map.previewRemove": "#F48771"}
    pairs = {(fg, bg): low for fg, bg, low in theme.CONTRAST_PAIRS}
    for token, value in expected.items():
        assert theme.THEME[token].upper() == value
        for background in ("editor.background", "map.box"):      # surface, raised
            assert pairs[(token, background)] == theme.GRAPHIC_MIN
            assert theme.contrast(theme.THEME[token], theme.THEME[background]) >= 3.0
    assert theme.blend("#89D185", "#000000", 1.0) == "#89D185"
    assert theme.blend("#89D185", "#3C3C3C", 0.0) == "#3C3C3C"


def test_f58_p4_os_reduce_motion_is_confined_and_falls_back():
    """07 I-11: the SPI call and ``/usr/bin/defaults`` appear only in ``os_reduce_motion``,
    whose ``ctypes``/``subprocess``/``procs`` imports are function-level."""
    source = (ENGINE / "tools" / "editor" / "theme.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    reader = funcs["os_reduce_motion"]
    inside = set(range(reader.lineno, reader.end_lineno + 1))
    for node in ast.walk(tree):
        text = None
        if isinstance(node, ast.Attribute) and node.attr == "SystemParametersInfoW":
            text = node.attr
        elif isinstance(node, ast.Name) and node.id in ("_DEFAULTS",
                                                        "SPI_GETCLIENTAREAANIMATION"):
            text = node.id
        if text is not None and isinstance(node.ctx, ast.Load):
            assert node.lineno in inside, (text, node.lineno)
    top_imports = {alias.name for node in tree.body if isinstance(node, ast.Import)
                   for alias in node.names}
    top_imports |= {node.module for node in tree.body if isinstance(node, ast.ImportFrom)}
    assert not top_imports & {"ctypes", "subprocess", "engine.tools.build.procs",
                              "engine.tools.build"}
    for path in ENGINE.rglob("*.py"):
        if path.name == "theme.py" and path.parent.name == "editor":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "SPI_GETCLIENTAREAANIMATION" not in text and "universalaccess" not in text, path
    assert theme.os_reduce_motion("linux") is False
    assert isinstance(theme.os_reduce_motion(), bool)


def test_f58_p4_studio_json_motion_keys():
    assert {"follow_changes", "reduce_motion"} <= studiostate.OPTIONAL_KEYS
    assert b"follow_changes" not in encode_state(StudioState())      # written only when true
    data = encode_state(StudioState(follow_changes=True, reduce_motion=True))
    assert decode_state(data) == StudioState(follow_changes=True, reduce_motion=True)
    assert decode_state(b'{"guide_open": true, "reduce_motion": "yes"}') == \
        StudioState(guide_open=True)                                   # strict booleans

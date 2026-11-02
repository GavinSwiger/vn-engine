"""F20 s1 — AC-F20-05: ``[flowchart]`` (F20 ``02-script.md`` §3.6, SR-F20-13; ``04`` §13). A
bad value is one F01 ``ConfigError`` and the default is kept; an unknown key warns.

F20 s2: ``FlowOptions.from_config`` (what ``app/loading.py`` and ``vn check`` pass as
``LoadOptions.flowchart``); with ``enabled = false`` the load builds no graph
(``program.flowgraph`` is None) and gives no E265 or W150–W153, while E260–E264 still report
(AC-F20-03's rows, ``test_flowchart_marks.py``). The run-loop row is in
``tests/runtime/test_flow_arrivals.py``."""

from engine.core.config import load_config
from engine.core.config_schema import SECTIONS, Config, FlowchartConfig
from engine.script import limits, load_story
from engine.script.flowgraph import FlowOptions
from engine.script.loader import LoadOptions
from tests.script.helpers import template_l

LINE2 = "config.toml, line 2: "


def test_ac_f20_05_flowchart_config(load, make_game, monkeypatch):
    assert Config().flowchart == FlowchartConfig(enabled=True, menus="branching",
                                                 unvisited="mystery", jump=True)
    assert SECTIONS["flowchart"] is FlowchartConfig
    result = load('[flowchart]\nenabled = false\nmenus = "marked"\nunvisited = "hidden"\n'
                  "jump = false\n")
    assert result.errors == [] and result.config.flowchart == FlowchartConfig(
        False, "marked", "hidden", False)
    assert load('[flowchart]\nmenus = "all"\n').config.flowchart.menus == "all"
    for text, key in (('menus = "some"', "menus"), ("unvisited = 3", "unvisited"),
                      ('jump = "no"', "jump"), ("enabled = 1", "enabled")):
        result = load(f"[flowchart]\n{text}\n")
        assert len(result.errors) == 1, text
        assert result.errors[0].format().startswith(LINE2 + f"[flowchart] {key} ")
        assert result.config.flowchart == FlowchartConfig()
    result = load("[flowchart]\nmenu = \"all\"\n")
    assert result.errors == [] and any("menu" in w for w in result.warnings)
    # F20 s2: the load's options come from the table.
    assert FlowOptions.from_config(FlowchartConfig()) == FlowOptions()
    assert FlowOptions.from_config(FlowchartConfig(False, "marked", "hidden", False)) == \
        FlowOptions(enabled=False, menus="marked", unvisited="hidden", jump=False)
    # enabled = false: no graph, no W150 (an unreachable scene) and no E265 (a node limit
    # of 1); with it on, both appear.
    script = template_l(T='label old:⏎[4]flowchart scene "Old"⏎[4]"Bye."')

    def run(table: str):
        paths = make_game(f'[game]\nid = "f20"\n[flowchart]\n{table}\n')
        (paths.root / "script").mkdir()
        (paths.root / "script" / "main.vns").write_bytes(script.encode("utf-8"))
        config = load_config(paths).config
        return load_story(paths, LoadOptions(dev=True, flowchart=FlowOptions.from_config(
            config.flowchart)))

    on = run("enabled = true")
    assert on.program.flowgraph is not None and [w.code for w in on.warnings] == ["W150"]
    off = run("enabled = false")
    assert off.errors == () and off.warnings == () and off.program.flowgraph is None
    monkeypatch.setattr(limits, "FLOW_NODES_MAX", 1)
    assert [e.code for e in run("enabled = true").errors] == ["E265"]
    off = run("enabled = false")
    assert off.errors == () and off.program is not None and off.program.flowgraph is None


# --- AC-F20-65 — theme, words, and contrast (F20 s8) ----------------------------------------

def test_ac_f20_65_theme_words_and_contrast(load):
    from engine.app.ui_contrast import PAIRS, contrast_warnings, pair_ratios
    from engine.core.config_schema import ThemeConfig, WordsConfig
    from engine.tools.editor.config_help import section_paths
    from engine.ui.builtin.flowchart_page import flow_color
    from engine.ui.theme import plain_theme

    cfg = ThemeConfig()
    f = cfg.flowchart
    assert (f.fill_color, f.text_size, f.node.width, f.node.fill_color, f.node.border_color,
            f.edge.line_color, f.edge.line_width, f.path.line_width) == (
        (0xFF, 0xFA, 0xFC), 24, 240, (0xFF, 0xE6, 0xF0), (0x7E, 0x5C, 0x74),
        (0x7E, 0x5C, 0x74), 3, 6)
    follows = {"flowchart.node.text_color": cfg.panel.text_color,
               "flowchart.gate.fill_color": f.fill_color,
               "flowchart.unknown.text_color": cfg.button.disabled.text_color,
               "flowchart.path.line_color": cfg.button.marker.fill_color,
               "flowchart.here.fill_color": cfg.save.newest.fill_color,
               "flowchart.here.text_color": cfg.save.newest.text_color}
    assert {k: flow_color(cfg, k) for k in follows} == follows
    assert all(getattr(f, kind).frame_image is None
               for kind in ("start", "chapter", "choice", "scene", "ending", "gate"))
    for text in ("text_size = 40", "[theme.flowchart.node]\nwidth = 100"):
        head = "[theme.flowchart]\n" if not text.startswith("[") else ""
        result = load(head + text + "\n")
        assert result.errors or result.warnings, text
        assert result.config.theme.flowchart == ThemeConfig().flowchart
    assert load('[theme.flowchart.here]\nfill_color = "#102030"\n').config.theme.flowchart \
        .here.fill_color == (0x10, 0x20, 0x30)
    # Words: every key of 01, 03, and 04 with its default; an author value replaces it.
    words = WordsConfig()
    assert {k: getattr(words, k) for k in (
        "flowchart", "flowchart_jump", "flowchart_choice", "flowchart_start",
        "flowchart_unknown", "flowchart_here", "flowchart_var", "flowchart_no_jump",
        "flowchart_route", "flowchart_confirm_autosave")} == {
        "flowchart": "Flowchart", "flowchart_jump": "Jump", "flowchart_choice": "Choice",
        "flowchart_start": "Start", "flowchart_unknown": "???",
        "flowchart_here": "You are here", "flowchart_var": "…",
        "flowchart_no_jump": "You can't jump to this point.",
        "flowchart_route": "Locked route", "flowchart_confirm_autosave": "Jump to this point?"}
    assert words.flowchart_confirm.startswith("Jump to this point? Unsaved")
    assert words.flowchart_changed == "This part of the story has changed."
    assert words.flowchart_no_state == "Reach this point again to jump here."
    assert load('[words]\nflowchart_jump = "Go"\n').config.words.flowchart_jump == "Go"
    # Contrast: 03's ratios for the defaults; W67 names an author's pale ??? color.
    ratios = {(p.fg, p.bg): min(pair_ratios(cfg, p)) for p in PAIRS
              if p.fg.startswith("flowchart")}
    assert ratios[("flowchart.unknown.text_color", "flowchart.fill_color")] >= 5.8
    assert ratios[("flowchart.here.text_color", "flowchart.here.fill_color")] >= 7.0
    assert all(r >= p.minimum for p in PAIRS if p.fg.startswith("flowchart")
               for r in [min(pair_ratios(cfg, p))])
    assert not [w for w in contrast_warnings(plain_theme(cfg)) if "flowchart" in w]
    pale = load('[theme.flowchart.unknown]\ntext_color = "#DDDDDD"\n').config.theme
    found = [w for w in contrast_warnings(plain_theme(pale)) if "flowchart" in w]
    assert found and all("#DDDDDD" in w for w in found)
    # F45 Studio: the config Help offers the new tables.
    assert {"theme.flowchart", "theme.flowchart.here"} <= set(section_paths())

"""F48 step S4: the read tools, ``run_check`` and the workspaces (AC-F48-06, 08 to 12;
04 §3.1, §7.1, §7.7; SEC-F48-05, SEC-F48-09; 01 §7.1, §7.2, §4.4)."""

import json
import shutil
import time
from pathlib import Path

import pytest

from engine.core import redact
from engine.core.paths import GamePaths
from engine.tools.assistant import workspace as ws_module
from engine.tools.assistant.textout import HITS_MAX
from engine.tools.assistant.tools import (
    MODE_MCP, MODE_PANE, MODE_READ_ONLY, TOOL_SPECS, ToolBox, specs_for)
from engine.tools.assistant.workspace import CHECK_DIDNT_FINISH, REASON_TIMEOUT
from engine.tools.editor.checker import CheckState, NameEntry
from tests.tools.assistant.assist_games import (
    FakeRunner, disk, item, pane, result, studio)

CHANGE = {"summary": "s", "changes": [{"file": "script/ch2.vns", "old_text": "jump river",
                                       "new_text": "jump bridge"}]}


class Writer:
    def __init__(self) -> None:
        self.kept: list = []

    def keep(self, proposal) -> str:
        self.kept.append(proposal)
        return f"p{len(self.kept)}"

    def apply(self, args):
        raise AssertionError("not here")

    undo = apply


# --- AC-F48-06: no absolute path or user name in any output ----------------------------------

def test_ac06_no_tool_output_holds_the_game_path_or_user_name(tmp_path, monkeypatch):
    home = tmp_path / "users" / "zelda_quill"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(redact, "_installed", redact._installed)     # restored afterwards
    game = studio(home / "Documents", "my game")
    root = str(GamePaths.for_game(game).root)
    leak = item("E99", "script/ch2.vns", 3, f"Couldn't read {root}\\script\\x.vns "
                f"or {Path(root).as_posix()}/script/y.vns")
    names = {"label": [NameEntry("club", "script/ch2.vns", 1)],
             "character": [NameEntry("hana", "script/main.vns", 2)]}
    workspace = disk(game, FakeRunner(result(leak, names=names)))
    ws_module.install_redaction(workspace.paths)
    box = ToolBox(workspace, MODE_MCP, writer=Writer())
    calls = {"language_reference": {}, "language_docs": {"topic": "menu"},
             "project_summary": {}, "list_files": {}, "read_script": {"file": "script/ch2.vns"},
             "search_scripts": {"text": "the"}, "story_map": {}, "scene": {"label": "club"},
             "names": {"kind": "character"}, "lookup": {"kind": "character", "name": "hana"},
             "game_settings": {}, "run_check": {}, "propose_edit": CHANGE,
             "apply_edit": {"id": "nope"}, "undo_apply": {}}
    assert set(calls) == {spec["name"] for spec in TOOL_SPECS}
    for name, args in calls.items():
        if name in ("apply_edit", "undo_apply"):
            continue                                  # S5's writer (test_diskapply)
        text = box.call(name, args).text
        for needle in (root, Path(root).as_posix(), "zelda_quill", str(home)):
            assert needle not in text, (name, text)
    assert "<game>" in box.call("run_check", {}).text


# --- AC-F48-08: read_script reads the editor text in Studio, disk in MCP ----------------------

def test_ac08_read_script_ranges_header_and_next_hint_from_editor_or_disk(tmp_path):
    game = studio(tmp_path)
    lines = [f'    "Line {n}."' for n in range(1, 1001)]
    (game / "script" / "long.vns").write_text("label long:\n" + "\n".join(lines) + "\n",
                                              encoding="utf-8")
    mcp = ToolBox(disk(game), MODE_READ_ONLY)
    first = mcp.call("read_script", {"file": "script/long.vns"})
    rows = first.text.split("\n")
    assert rows[0] == "script/long.vns has 1,001 lines."
    assert rows[1] == "script/long.vns, lines 1–800:"
    assert rows[2] == "  1 label long:" and rows[801] == '800     "Line 799."'
    assert rows[-1] == "Lines 801–1001 are next: read_script with first_line 801."
    assert first.sent.ranges == (("script/long.vns", 1, 800),)
    tail = mcp.call("read_script", {"file": "script/long.vns", "first_line": 990,
                                    "last_line": 5000}).text.split("\n")
    assert tail[1] == "script/long.vns, lines 990–1001:" and tail[-1].startswith("1001 ")
    config = mcp.call("read_script", {"file": "config.toml"})
    assert 'title = "My Game"' in config.text and config.sent.config
    # The pane reads what the author sees, unsaved text included; MCP reads disk.
    edited = (game / "script" / "ch2.vns").read_text(encoding="utf-8").rstrip("\n") \
        .replace("The river.", "The wide river.")
    studio_box = ToolBox(pane(game, {"script/ch2.vns": edited}), MODE_PANE)
    assert '11     "The wide river."' in studio_box.call(
        "read_script", {"file": "script/ch2.vns"}).text
    assert '11     "The river."' in mcp.call("read_script", {"file": "script/ch2.vns"}).text
    assert mcp.call("read_script", {"file": "script/ch2.vns", "first_line": "2"}).is_error


# --- AC-F48-09: literal search, hits and cap --------------------------------------------------

def test_ac09_search_is_literal_capped_and_fast(tmp_path):
    game = studio(tmp_path)
    body = "\n".join(f'    "Echo {n}."' for n in range(300))
    (game / "script" / "echo.vns").write_text(f"label echo:\n{body}\n", encoding="utf-8")
    big = ["label big:"] + ['    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaab"'] * 15_000
    big.insert(7_000, '    "find (a+)+$ here"')
    (game / "script" / "big.vns").write_text("\n".join(big) + "\n", encoding="utf-8")
    assert (game / "script" / "big.vns").stat().st_size > 1_000_000
    box = ToolBox(disk(game), MODE_READ_ONLY)
    hits = box.call("search_scripts", {"text": "echo "}).text.split("\n")
    assert hits[0] == "300 matching lines."
    assert hits[1] == "script/echo.vns, matching lines:" and hits[2] == '  2     "Echo 0."'
    assert len(hits[2:-1]) == HITS_MAX and all('"Echo ' in row for row in hits[2:-1])
    assert hits[-1] == "…and 100 more"
    assert "0 matching lines." in box.call("search_scripts",
                                           {"text": "echo ", "match_case": True}).text
    start = time.perf_counter()
    found = box.call("search_scripts", {"text": "(a+)+$"})
    assert time.perf_counter() - start < 1.0
    assert found.text.split("\n")[:3] == ["1 matching line.", "script/big.vns, matching lines:",
                                          '7001     "find (a+)+$ here"']
    for bad in ({"text": "x" * 201}, {"text": ""}, {"text": "a", "match_case": 1}, {}):
        assert box.call("search_scripts", bad).is_error


# --- AC-F48-10: map, scene, names and lookup agree with the check child -----------------------

def test_ac10_story_tools_agree_with_the_check_childs_names_and_graph(tmp_path):
    game = studio(tmp_path)
    workspace = disk(game, "real")
    box = ToolBox(workspace, MODE_READ_ONLY)
    checked = workspace.last_check().result
    assert checked is not None and checked.links
    story = box.call("story_map", {}).text
    for entry in checked.names["label"]:
        assert f"{entry.name}: {entry.file} line {entry.line}" in story
    for link in checked.links:
        assert f"{link.src} → {link.dst} ({link.kind}" in story
    assert "Scenes nothing reaches: side" in story
    club = box.call("scene", {"label": "club"}).text.split("\n")
    assert club[0] == "script/ch2.vns, lines 1–7:" and club[1] == "1 label club:"
    assert "start → club (call) at script/main.vns line 7" in club
    assert "club → river (menu, choice Go to the river) at script/ch2.vns line 4" in club
    names = box.call("names", {"kind": "character"}).text
    assert "hana: script/main.vns line 2, used 1 time" in names
    hana = box.call("lookup", {"kind": "character", "name": "hana"}).text.split("\n")
    assert hana[0] == "character hana: declared at script/main.vns line 2"
    assert "script/main.vns line 6" in hana and 'name: "Hana"' in hana
    assert box.call("lookup", {"kind": "character", "name": "../hana"}).is_error
    assert box.call("scene", {"label": "nowhere"}).is_error


# --- AC-F48-11: game_settings -----------------------------------------------------------------

def test_ac11_game_settings_lists_set_keys_with_default_and_help(tmp_path):
    game = studio(tmp_path)
    (game / "config.toml").write_text(
        '[game]\ntitle = "Lanterns"\nversion = "1.2"\n\n[textbox]\nmystery_key = 3\n',
        encoding="utf-8")
    box = ToolBox(disk(game), MODE_READ_ONLY)
    shown = box.call("game_settings", {})
    rows = shown.text.split("\n")
    assert rows[0] == "Set keys (3):"
    assert rows[1] == ('[game] title = "Lanterns" (default "Untitled Visual Novel"): '
                       "the game's name: the window title and the title screen")
    assert rows[2].startswith('[game] version = "1.2" (default ')
    assert rows[3] == "[textbox] mystery_key = 3 (not a key the engine knows)"
    assert shown.sent.config
    one = box.call("game_settings", {"section": "textbox"}).text.split("\n")
    assert one == ["Set keys (1):", "[textbox] mystery_key = 3 (not a key the engine knows)"]
    assert box.call("game_settings", {"section": "Game"}).is_error


# --- AC-F48-12: run_check, failures, and arming ------------------------------------------------

def test_ac12_run_check_problems_lint_failures_and_arming(tmp_path):
    game = studio(tmp_path)
    box = ToolBox(disk(game, "real"), MODE_READ_ONLY)
    clean = box.call("run_check", {}).text.split("\n")
    assert clean[0] == "Checked: no problems."
    assert "Not used or not reached (lint):" in clean        # lint runs on a story that loads
    assert "W237 Scene: side (script/ch2.vns line 12)" in clean
    assert "W241 Variable: trust (script/main.vns line 3)" in clean
    ch2 = game / "script" / "ch2.vns"
    ch2.write_text(ch2.read_text(encoding="utf-8").replace("jump river", "jump rivr"),
                   encoding="utf-8")
    real = box.call("run_check", {}).text.split("\n")
    assert real[0] == "Checked: 1 error, 0 warnings."
    assert real[1] == ('error E43 script/ch2.vns line 4 (load): there is no label named '
                       '"rivr". Did you mean "river"?')
    assert box.call("run_check", {}).sent.problems == 1
    # A timeout or a crash gives 01 §4.4's text.
    timeout = ToolBox(disk(game, FakeRunner(state=CheckState.TIMEOUT)), MODE_MCP)
    assert timeout.call("run_check", {}).text == CHECK_DIDNT_FINISH.format(
        reason=REASON_TIMEOUT)
    crash = ToolBox(disk(game, FakeRunner(state=CheckState.CRASHED, exit_code=2)), MODE_MCP)
    assert crash.call("run_check", {}).text == (
        "The check didn't finish (it stopped with exit code 2), so problems are unknown.")
    # The pane's checks launch only once the window is armed; nothing the model calls arms it.
    for armed in (False, True):
        runner = FakeRunner()
        box = ToolBox(pane(game, armed=armed, runner=runner), MODE_PANE)
        box.call("run_check", {})
        box.call("propose_edit", CHANGE)
        assert runner.requests and all(launch is armed for _, launch in runner.requests)
    unarmed = ToolBox(pane(game, runner=FakeRunner()), MODE_PANE).call("run_check", {}).text
    assert "hasn't played, saved or checked the game in this window yet" in unarmed


def test_tool_specs_are_engine_text_and_modes_filter_the_writers():
    assert [s["name"] for s in specs_for(MODE_PANE)] == [
        s["name"] for s in TOOL_SPECS if s["name"] not in ("apply_edit", "undo_apply")]
    assert specs_for(MODE_READ_ONLY) == specs_for(MODE_PANE)
    assert json.dumps(specs_for(MODE_MCP)) == json.dumps(list(TOOL_SPECS))
    with pytest.raises(ValueError):
        specs_for("other")


def test_check_service_caches_base_checks_by_overlay_and_stamp(tmp_path):
    game = studio(tmp_path)
    runner = FakeRunner()
    workspace = disk(game, runner)
    workspace.base_check()
    workspace.base_check()
    assert len(runner.requests) == 1
    workspace.base_check(launch=False)
    assert len(runner.requests) == 2
    shutil.copy(game / "script" / "ch2.vns", game / "script" / "ch3.vns")
    workspace.base_check()
    assert len(runner.requests) == 3

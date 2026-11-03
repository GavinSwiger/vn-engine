"""The real check child (F45 ``04`` §7.1 steps 1-2, §8.4-8.6; TR-F45-02): two subprocess
runs in the default tier, one per code path (a full run with an overlay; bad input), plus
the CLI rows in process. AC-F45-12, AC-F45-13. F46's 7-item graph rows, in process
(AC-F46-03)."""

import ast
import os
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from engine.app import cli
from engine.core.editorreport import REPORT_MARKER
from engine.core.paths import GamePaths, engine_root
from engine.script import load_story
from engine.script.labelgraph import LabelLink, label_links
from engine.tools import check
from engine.tools.editor.checker import check_argv, decode_check_line
from tests.tools.f45_games import edit_line, studio, tree

FORGED = 'VN-EDITOR-REPORT {"v":1,"event":"done","loaded":true,"problems":0,"seconds":0}'
BANNED = ("pygame", "tkinter", "engine.render", "engine.ui", "engine.audio", "engine.persist",
          "engine.minigames", "engine.meta")


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8:backslashreplace"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def test_ac_f45_12_the_real_child_reports_and_writes_nothing(tmp_path, user_roots):
    game = studio(tmp_path)
    # Launch-phase author code tries to forge a report line, twice.
    edit_line(game / "script" / "main.vns", 3,
              f"define forged = print('{FORGED}')\n"
              f"define sysm = module(\"sys\")\n"
              f"define forged2 = sysm.stdout.write('{FORGED}' + chr(10))")
    # The overlay changes ch2 (unsaved): a missing image is a launch warning at line 9, so
    # the launch ran on the overlaid bytes.
    ch2 = (game / "script" / "ch2.vns").read_bytes().split(b"\n")
    ch2[8] = b"    show hana sad"
    overlay = b"\n".join(ch2)
    header = b'{"v":1,"files":[{"ref":"script/ch2.vns","size":%d}]}\n' % len(overlay)
    before = tree(game), tree(user_roots.home.parent)
    argv = check_argv(game)
    argv[2:2] = ["-X", "importtime"]
    proc = subprocess.run(argv, input=header + overlay, capture_output=True, timeout=10,
                          cwd=str(engine_root()), env=_env())
    assert proc.returncode == 0, proc.stderr[-2000:]
    lines = proc.stdout.splitlines()
    assert lines and all(line.startswith(REPORT_MARKER) for line in lines)
    events = [decode_check_line(line) for line in lines]
    assert None not in events
    assert [kind for kind, _ in events].count("done") == 1 and events[-1][0] == "done"
    assert FORGED.encode("ascii") not in lines
    problems = [item for kind, payload in events if kind == "problems" for item in payload]
    assert [(i.code, i.source, i.file, i.line) for i in problems] == [
        ("W12", "launch", "script/ch2.vns", 9)]
    imported = set(re.findall(r"import time:\s+\d+\s+\|\s+\d+\s+\|\s+(\S+)",
                              proc.stderr.decode("utf-8", "replace")))
    assert "engine.tools.check" in imported
    assert not [name for name in imported
                if name.split(".")[0] in ("pygame", "tkinter") or name.startswith(BANNED)]
    assert {name for name in imported if name.startswith("engine.app")} <= {
        "engine.app", "engine.app.cli"}
    assert (tree(game), tree(user_roots.home.parent)) == before


def test_ac_f45_13_bad_input_and_release_runs_exit_2(tmp_path, capsys):
    game = studio(tmp_path)
    # (a) A real child with a bad overlay header writes nothing to stdout.
    proc = subprocess.run(check_argv(game), input=b'{"v":2,"files":[]}' + bytes([10]),
                          capture_output=True, timeout=5, cwd=str(engine_root()), env=_env())
    assert (proc.returncode, proc.stdout) == (2, b"")

    # (b) In process: --release is a usage error; a frozen build has no check command.
    calls = []

    def checker(game_dir, **options):
        calls.append((game_dir, options))
        return 0

    with pytest.raises(SystemExit) as exit_:
        cli.main(["check", "--release", str(game)], checker=checker)
    assert exit_.value.code == 2
    assert "is only available in dev runs" in capsys.readouterr().err
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli, "is_frozen", lambda: True)
        with pytest.raises(SystemExit) as exit_:
            cli.main(["check", str(game)], checker=checker)
    assert exit_.value.code == 2 and calls == []
    assert cli.main(["check", str(game), "--report-to-editor", "--no-launch"],
                    checker=checker) == 0
    assert calls == [(game, {"report": True, "overlay": False, "launch": False})]

    # (c) __main__ imports engine.tools.check only inside _check.
    module = ast.parse((Path(cli.__file__).resolve().parents[1] / "__main__.py")
                       .read_text("utf-8"))
    found = [node.name for node in ast.walk(module) if isinstance(node, ast.FunctionDef)
             for inner in ast.walk(node)
             if isinstance(inner, ast.ImportFrom) and inner.module == "engine.tools.check"]
    top = [node for node in module.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert found == ["_check"]
    assert all("tools" not in (getattr(node, "module", "") or "") for node in top)


LANTERNS = Path(__file__).resolve().parents[1] / "fixtures" / "F46" / "games" / "lanterns"


def _graph(*rows: list) -> tuple | None:
    found = decode_check_line(check.encode_event({"v": 1, "event": "graph", "links": list(rows)}))
    return None if found is None else found[1]


def test_ac_f46_03_choice_links_on_the_wire(tmp_path):
    game = tmp_path / "lanterns"
    shutil.copytree(LANTERNS, game)
    long_text = "A long way round, " * 16 + "ending here."           # 300 characters
    assert len(long_text) == 300
    nested = ["label nested:", "    menu:", '        "Outer" if coins > 0:',
              "            if stall_price > 0:", "                menu:",
              '                    "Inner":', "                        jump river",
              f'        "{long_text}":', "            jump river", ""]
    with (game / "script" / "ch2.vns").open("ab") as out:
        out.write("\n".join(nested).encode("utf-8"))
    program = load_story(GamePaths.for_game(game)).program
    assert program is not None
    links, total = label_links(program, limit=100)
    by_place = {(k.file, k.line): k for k in links}
    assert by_place["script/ch2.vns", 5] == LabelLink(
        "stall", "river", "menu", "script/ch2.vns", 5, "Buy the red one", True)
    assert by_place["script/ch2.vns", 9] == LabelLink(
        "stall", "river", "jump", "script/ch2.vns", 9, None, False)
    inner = by_place["script/ch2.vns", 24]
    assert (inner.choice, inner.conditional) == ("Inner", False)    # the innermost choice

    events: list[dict] = []
    check.emit_results(events.append, [], 0, {}, program, 0.0)
    graph = [event for event in events if event["event"] == "graph"]
    assert graph and all(event["v"] == 1 for event in graph)
    assert {len(row) for event in graph for row in event["links"]} == {7}
    decoded = tuple(link for event in graph for link in _graph(*event["links"]))
    assert decoded == tuple(
        replace(k, choice=None if k.choice is None else check._text(k.choice)) for k in links)
    assert by_place["script/ch2.vns", 26].choice == long_text
    assert decoded[[k.line for k in links].index(26)].choice == check._text(long_text)

    # A row from before F46 still decodes; a 6-item row or a cond that isn't a bool breaks
    # the line.
    assert _graph(["a", "b", "jump", "script/m.vns", 3]) == (
        LabelLink("a", "b", "jump", "script/m.vns", 3, None, False),)
    for bad in (["a", "b", "menu", "script/m.vns", 3, "Go"],
                ["a", "b", "menu", "script/m.vns", 3, "Go", 1],
                ["a", "b", "menu", "script/m.vns", 3, "Go", None],
                ["a", "b", "menu", "script/m.vns", 3, 7, False]):
        assert _graph(bad) is None, bad

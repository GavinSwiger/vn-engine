"""F20 s2 — the flowchart's graph (F20 ``06-acceptance.md`` AC-F20-06 to 13; ``04-technical.md``
§4, §7.1; ``07`` I-1, I-13; F45 ``07`` I-11).

Harness **Graph G** (06 §0.3): a script written as ``script/main.vns`` in ``tmp_path``, loaded
with ``LoadOptions(flowchart=FlowOptions(...))``, then ``program.flowgraph``. Template L's
golden is ``tests/fixtures/F20/graph_lanterns.txt``; AC-F20-08's and 09's snippets are
``tests/fixtures/F20/snippets.toml``. The rows of AC-F20-10, 11, and 12 that read the
persistent store (``chart_records``: visited, ``???``, contracted gates, a ``{var}``'s value
at run time) are in ``tests/runtime/test_chart_records.py`` and ``test_flow_arrivals.py``;
here are their graph halves.

Regenerate the golden only after reviewing the change::

    .venv/Scripts/python -m tests.script.test_flowgraph --write
"""

import hashlib
import logging
import os
import random
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.runtime import limits as runtime_limits
from engine.script import flowgraph, limits, load_story
from engine.script.diagnostics import DiagnosticSink
from engine.script.flowgraph import (FLOW_RULES, OPAQUE, CallSucc, FlowGraph, FlowGraphJob,
                                     FlowOptions, Walk, box_text, node_key, plain_title,
                                     show_text)
from engine.script.labelgraph import LINK_RULES
from engine.script.loader import LoadOptions, LoadResult
from engine.script.nodes import PythonLine
from engine.script.program import Program
from tests.script.helpers import F20_TEMPLATE, template_l
from tests.script.test_messages import CASES

F20 = F20_TEMPLATE.parents[2]
GOLDEN = F20 / "graph_lanterns.txt"
SNIPPETS = tomllib.loads((F20 / "snippets.toml").read_text(encoding="utf-8"))["snippet"]


def load(root: Path, text: str, *, dev: bool = False, **options) -> LoadResult:
    """Graph G: ``text`` as ``script/main.vns`` under ``root``."""
    (root / "script").mkdir(parents=True, exist_ok=True)
    (root / "script" / "main.vns").write_bytes(text.encode("utf-8"))
    return load_story(GamePaths(root.resolve()),
                      LoadOptions(dev=dev, flowchart=FlowOptions(**options)))


def graph_of(root: Path, text: str, **options) -> tuple[Program, FlowGraph]:
    result = load(root, text, **options)
    assert result.program is not None, [e.format() for e in result.errors]
    assert result.program.flowgraph is not None
    return result.program, result.program.flowgraph


def short(program: Program, graph: FlowGraph, index: int) -> str:
    """A node's name in the snippets: ``M<line>`` for a menu, else its id without kind."""
    node = graph.nodes[index]
    if node.kind == "choice":
        return f"M{program.get(node.anchor).line}"
    if node.kind in ("gate", "start"):
        return node.id
    return node.id.split(":", 1)[1]


def edge_rows(program: Program, graph: FlowGraph) -> list[list[str]]:
    return [[short(program, graph, e.src), short(program, graph, e.dst),
             *(show_text(t) for t in e.texts)] for e in graph.edges]


def dump(program: Program, graph: FlowGraph) -> str:
    """The golden form: one line per node, then one per edge."""
    def name(index: int | None) -> str:
        return "-" if index is None else graph.nodes[index].id

    lines = []
    for node in graph.nodes:
        line = program.get(node.anchor).line if node.anchor else "-"
        flags = "".join(("H" if node.hidden else "-", "J" if node.no_jump else "-"))
        lines.append(f"node {node.id} kind={node.kind} key={node.key} anchor_line={line} "
                     f"label={node.label} chapter={name(node.chapter)} route={name(node.route)} "
                     f"order={node.order} flags={flags} text={show_text(box_text(node))!r}")
    for edge in graph.edges:
        texts = [show_text(t) for t in edge.texts]
        lines.append(f"edge {name(edge.src)} -> {name(edge.dst)} choices={len(edge.choices)} "
                     f"texts={texts} record={edge.record}")
    return "\n".join(lines) + "\n"


def lanterns(root: Path, **options) -> tuple[Program, FlowGraph]:
    return graph_of(root, F20_TEMPLATE.read_text(encoding="utf-8"), **options)


def warnings_of(result: LoadResult) -> list[tuple[str, int | None, str]]:
    return [(w.code, w.line, w.message) for w in result.warnings if w.code.startswith("W15")]


# --- AC-F20-06: dev warnings W150–W153 ----------------------------------------------------------

def test_ac_f20_06_dev_warnings(tmp_path, monkeypatch):
    # The scene, chapter/ending/menu, W152, and W153 rows are cases.toml rows (exact text and
    # line, dev loads; test_messages.py runs them); each is there.
    ids = {c.id for c in CASES if c.ac == "AC-F20-06"}
    for row in ("F20-06-W150-scene", "F20-06-W150-kinds", "F20-06-W152", "F20-06-no-W152",
                "F20-06-W153"):
        assert row in ids or any(i.startswith(row + "-") for i in ids), row
    # Template L: no W150–W153 (only literal targets exist, so no W151).
    result = load(tmp_path / "l", F20_TEMPLATE.read_text(encoding="utf-8"), dev=True)
    assert result.program is not None and warnings_of(result) == []
    # Each warning once, on a dev load; a release load gives none.
    text = template_l(T='label old_ending:⏎[4]flowchart scene "Old Ending"⏎[4]"Bye."'
                        '⏎label tidy:⏎[4]flowchart forget tidy')
    dev = load(tmp_path / "dev", text, dev=True)
    assert [(c, line) for c, line, _ in warnings_of(dev)] == [("W150", 42), ("W153", 45)]
    release = load(tmp_path / "release", text, dev=False)
    assert release.program is not None and warnings_of(release) == []
    # W151: a statement type registered OPAQUE draws no edge out of it.
    monkeypatch.setitem(FLOW_RULES, PythonLine, OPAQUE)
    opaque = 'label start:\n    chapter c1 "One"\n    $ x = 1\n    chapter c2 "Two"\n'
    result = load(tmp_path / "opaque", opaque, dev=True)
    graph = result.program.flowgraph
    assert graph.edges == ()
    assert [(c, line) for c, line, _ in warnings_of(result)] == [("W151", 3), ("W150", 4)]


# --- AC-F20-07: Template L's graph, and determinism ---------------------------------------------

def test_ac_f20_07_template_graph_and_determinism(tmp_path):
    program, graph = lanterns(tmp_path)
    assert dump(program, graph) == GOLDEN.read_text(encoding="utf-8"), (
        "regenerate with: .venv/Scripts/python -m tests.script.test_flowgraph --write")
    ids = [n.id for n in graph.nodes]
    m21 = next(n.id for n in graph.nodes if n.kind == "choice")
    assert ids == ["start", "chapter:festival", "scene:stall", m21, "chapter:river",
                   "ending:sad", "chapter:shrine", "ending:good", "gate:promise",
                   "scene:promise", "ending:true"]
    assert edge_rows(program, graph) == [
        ["start", "festival"], ["festival", "stall"], ["stall", "M21"],
        ["M21", "river", "By the river"], ["M21", "shrine", "From the shrine steps"],
        ["M21", "gate:promise", "Wait at the bridge"], ["river", "sad"], ["shrine", "good"],
        ["gate:promise", "promise"], ["promise", "true"]]
    lines = {n.id: program.get(n.anchor).line for n in graph.nodes if n.anchor}
    assert (lines["chapter:festival"], lines["scene:stall"], lines[m21]) == (7, 11, 21)
    assert lines["gate:promise"] == lines["scene:promise"] == 37
    assert graph.anchors[program.get(graph.nodes[graph.by_id["scene:promise"]].anchor).sid] \
        == (graph.by_id["scene:promise"],)                          # gates aren't anchors
    chapter = {n.id: n.chapter for n in graph.nodes}
    assert chapter["chapter:festival"] is None
    assert chapter["chapter:river"] == graph.by_id["chapter:festival"]
    assert chapter["ending:sad"] == graph.by_id["chapter:river"]
    assert all(n.key == node_key(n.id) and len(n.key) == 16 for n in graph.nodes)
    assert node_key("start") == hashlib.blake2b(b"start", digest_size=8).hexdigest()
    assert all(not graph.out[i] for i, n in enumerate(graph.nodes) if n.kind == "ending")
    # TR-F20-01: 20 random slice schedules (1 work unit per step up to unlimited).
    rng = random.Random(20)
    for _ in range(20):
        job = FlowGraphJob(program, FlowOptions(), DiagnosticSink())
        while True:
            job.units = rng.choice((1, 2, 7, 50, 2_000, 10**9))
            if job.step():
                break
        assert job.result == graph


# --- AC-F20-08: edges through the script --------------------------------------------------------

@pytest.mark.parametrize("snippet", [s for s in SNIPPETS if s["ac"] == "AC-F20-08"],
                         ids=lambda s: s["id"])
def test_ac_f20_08_edges_through_the_script(tmp_path, snippet):
    program, graph = graph_of(tmp_path, snippet["script"])
    assert ("start" in graph.by_id) is snippet["start"]
    assert edge_rows(program, graph) == snippet["edges"]


def test_ac_f20_08_opaque_and_rules_agree_with_label_links(tmp_path, monkeypatch):
    # F45 07 I-11: Jump and Call name a label in FLOW_RULES as in labelgraph.LINK_RULES.
    assert set(LINK_RULES) == {"jump", "call"}
    program, _ = lanterns(tmp_path)
    stmts = list(program.iter_statements())
    index = {s.sid: i for i, s in enumerate(stmts)}
    walk = Walk(stmts, index, [-1] * len(stmts), program.labels)
    for word, (node_type, target) in LINK_RULES.items():
        rule = FLOW_RULES[node_type]
        for stmt in (s for s in stmts if type(s) is node_type):
            (succ,) = rule(stmt, walk)
            named = succ.target if isinstance(succ, CallSucc) else succ.label
            assert named == target(stmt), (word, stmt.line)
    # The OPAQUE row (AC-F20-06's statement) draws no edge from it.
    monkeypatch.setitem(FLOW_RULES, PythonLine, OPAQUE)
    program, graph = graph_of(tmp_path / "o", 'label start:\n    chapter c1 "One"\n'
                                              '    $ x = 1\n    chapter c2 "Two"\n')
    assert graph.out[graph.by_id["chapter:c1"]] == ()


# --- AC-F20-09: which menus are nodes -----------------------------------------------------------

def test_ac_f20_09_which_menus_are_nodes(tmp_path):
    texts = {s["id"]: s["script"] for s in SNIPPETS}
    for snippet in (s for s in SNIPPETS if s["ac"] == "AC-F20-09"):
        script = snippet["script"]
        if script.startswith("<"):
            script = texts[script[1:-1]]
        root = tmp_path / snippet["id"]
        program, graph = graph_of(root, script, menus=snippet.get("menus", "branching"))
        names = [short(program, graph, i) for i in range(len(graph.nodes))]
        assert names == snippet["nodes"], snippet["id"]
        if "edges" in snippet:
            assert edge_rows(program, graph) == snippet["edges"], snippet["id"]
    # Under "all", Template L gains M13: stall → M13 → M21 with both choices.
    program, graph = lanterns(tmp_path / "all", menus="all")
    rows = edge_rows(program, graph)
    assert ["stall", "M13"] in rows and ["M13", "M21", "Buy the red one", "Just look"] in rows
    assert ["stall", "M21"] not in rows


# --- AC-F20-10: titles and text on the chart ----------------------------------------------------

TITLES = '''define hana = Character("Hana")
default player_name = "Aiko"
default name = "Aiko"
default coins = 0
label start:
    hana "Hello."
    chapter festival "Chapter 2" "The Lantern Festival"
    flowchart
    menu:
        "Give {var=player_name} the {b}red{/b} lantern" if coins > 3:
            chapter c1 "Only a title"
        "Use {{braces}":
            ending sad "Sad End" "Paper Ashes"
    flowchart
    menu:
        hana "Where to, {var=name}?"
        "A":
            chapter c3 "C"
        "B":
            ending good "Good"
    flowchart
    menu:
        "{color=#ff0000}Run{/color}{i}!{/i}":
            "a"
        "Walk":
            "b"
    flowchart "Where should we watch the lanterns?"
    menu:
        hana "{color=#ff0000}Run{/color}{pause=0.5}{speed=10}!"
        "X":
            "x"
        "Y":
            "y"
'''


def test_ac_f20_10_titles_and_text(tmp_path):
    program, graph = graph_of(tmp_path, TITLES)

    def text(node_id: str, **words) -> str:
        node = graph.nodes[graph.by_id[node_id]]
        empty = {"start": "Start", "choice": "Choice"}.get(node.kind, "")
        return show_text(box_text(node), empty=empty, **words)

    menus = [n for n in graph.nodes if n.kind == "choice"]
    assert len(menus) == 4
    edge_texts = {show_text(t) for e in graph.edges for t in e.texts}
    assert {"Give … the red lantern", "Use {braces}", "Run!"} <= edge_texts
    give = next(t for e in graph.edges for t in e.texts if show_text(t).startswith("Give"))
    assert give == ("Give ", None, " the red lantern")
    assert show_text(give, var="~") == "Give ~ the red lantern"        # [words] flowchart_var
    assert text(menus[0].id) == "Choice" and menus[0].title == ()      # untitled, no question
    assert text(menus[1].id) == "Where to, …?"                          # no speaker name
    assert text(menus[3].id) == "Where should we watch the lanterns?"   # the mark's title
    assert text("start") == "Start" and graph.nodes[0].title == ()
    assert text("chapter:festival") == "Chapter 2: The Lantern Festival"
    assert text("chapter:c1") == "Only a title"
    sad = graph.nodes[graph.by_id["ending:sad"]]
    assert text("ending:sad") == "Sad End: Paper Ashes"
    assert (sad.heading, sad.title) == ("Sad End", ("Paper Ashes",))   # panel: heading, title
    # A choice's condition never shows; a question line's tags drop too.
    assert not any("coins" in show_text(t) for e in graph.edges for t in e.texts)
    question = program.get(menus[3].anchor).question
    assert show_text(plain_title(question.body)) == "Run!"


# --- AC-F20-11: node identity across patches -----------------------------------------------------

def test_ac_f20_11_identity_across_patches(tmp_path):
    def ids(text: str, name: str) -> dict[str, str]:
        _, graph = graph_of(tmp_path / name, text)
        return {n.id: n.key for n in graph.nodes}

    base = ids(template_l(), "base")
    m21 = next(i for i in base if i.startswith("menu:"))
    for name, patch in (("retitle", {20: '    flowchart "Elsewhere?" hidden no jump'}),
                        ("remove", {20: "    # no mark"}),
                        ("flag", {20: '    flowchart "Where should we watch the lanterns?"'
                                      " hidden"})):
        assert ids(template_l(replace=patch), name) == base, name      # same ids and keys
    question = ids(template_l(replace={21: '    menu:⏎[8]hana "Where now?"'}), "question")
    assert m21 not in question and len([i for i in question if i.startswith("menu:")]) == 1
    renamed = ids(template_l(replace={9: "    jump booth", 10: "label booth:"}), "renamed")
    assert "scene:booth" in renamed and "scene:stall" not in renamed
    assert {i: k for i, k in renamed.items() if i not in ("scene:stall", "scene:booth")
            and not i.startswith("menu:")} == {i: k for i, k in base.items()
                                               if i != "scene:stall" and not i.startswith("menu:")}
    # Label river and its chapter deleted (the Sad End kept, so the route still loads).
    gone_text = template_l(replace={23: "            jump sad_end", 28: "label sad_end:",
                                    29: "    # gone", 30: "    # gone"})
    gone = load(tmp_path / "gone", gone_text, dev=True)
    assert gone.errors == () and warnings_of(gone) == []
    assert "chapter:river" not in {n.id for n in gone.program.flowgraph.nodes}
    inserted = ids(template_l(S='"Daichi waves from the stall."⏎[4]"A new line."'), "inserted")
    assert inserted["scene:stall"] == base["scene:stall"]
    assert node_key("scene:stall") == base["scene:stall"]


# --- AC-F20-12: locked routes and gates (graph half) -------------------------------------------

def test_ac_f20_12_routes_and_gates(tmp_path):
    _, graph = lanterns(tmp_path)
    gate = graph.by_id["gate:promise"]
    members = sorted(n.id for n in graph.nodes if n.route == gate)
    assert members == ["ending:true", "scene:promise"]
    assert graph.nodes[gate].no_jump and not graph.nodes[gate].hidden
    # Gate edges carry records (P + S: one in from M21 is a choice edge, one out).
    records = [graph.edges[e].record for e in graph.out[gate]]
    assert records == [graph.nodes[gate].key + graph.nodes[graph.by_id["scene:promise"]].key]
    assert records[0] in graph.records
    assert graph.nodes[graph.by_id["scene:promise"]].hidden


# --- AC-F20-13: graph limits ----------------------------------------------------------------------

def _limits_script(targets: int = 10, endings: int = 10, extra_branch: bool = False) -> str:
    """10 hubs × ``targets`` chapters (one edge each), ``endings`` lone endings, 2 gates."""
    lines = ['lock route g1 "G1"', 'lock route g2 "G2"', "default v = 0",
             "label start:", "    jump h1"]
    for h in range(1, 11):
        lines += [f"label h{h}:", f'    chapter h{h} "H{h}"']
        for t in range(1, targets + 1):
            word = "if" if t == 1 else "elif"
            lines += [f"    {word} v == {t}:", f"        jump t{t}"]
        if extra_branch and h == 1:
            lines += ["    elif v == 99:", "        jump e1"]
    for t in range(1, targets + 1):
        lines += [f"label t{t}:", f'    chapter t{t} "T{t}"']
    for e in range(1, endings + 1):
        lines += [f"label e{e}:", f'    ending e{e} "E{e}"']
    lines += ["label g1:", '    "One."', "label g2:", '    "Two."']
    return "\n".join(lines) + "\n"


def test_ac_f20_13_graph_limits(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(limits, "FLOW_NODES_MAX", 30)
    monkeypatch.setattr(limits, "FLOW_EDGES_MAX", 100)
    _, graph = graph_of(tmp_path / "fits", _limits_script())
    kinds = [n.kind for n in graph.nodes]
    assert (len(kinds) - kinds.count("gate"), kinds.count("gate"), len(graph.edges)) == (30, 2,
                                                                                         100)
    for name, text, form, count, limit in (
            ("nodes", _limits_script(endings=11), "nodes", 31, 30),
            ("edges", _limits_script(extra_branch=True), "paths", 101, 100)):
        result = load(tmp_path / name, text)
        assert result.program is None and [e.code for e in result.errors] == ["E265"]
        assert result.errors[0].message == flowgraph.format_message("E265", (form, count,
                                                                             limit))
        assert result.errors[0].line is None and result.errors[0].file is None
    off = load(tmp_path / "off", _limits_script(endings=11), enabled=False)
    assert off.program is not None and off.program.flowgraph is None and off.errors == ()
    # A key collision drops the later node with one INFO record.
    real = flowgraph.node_key
    monkeypatch.setattr(flowgraph, "node_key",
                        lambda i: real("chapter:t1" if i == "chapter:t2" else i))
    with caplog.at_level(logging.INFO, logger="vn.script"):
        _, graph = graph_of(tmp_path / "collide", _limits_script())
    assert "chapter:t1" in graph.by_id and "chapter:t2" not in graph.by_id
    assert len([r for r in caplog.records if "chapter:t2" in r.getMessage()]) == 1
    # The name-count bound is F12's (runtime UNLOCK_NAMES_MAX); script keeps its own copy.
    assert limits.FLOW_NAMES_MAX == runtime_limits.UNLOCK_NAMES_MAX


@pytest.mark.slow
def test_ac_f20_07_same_graph_under_other_hash_seeds():
    """AC-F20-07's slow row: two processes with PYTHONHASHSEED 1 and 2 print the golden."""
    golden = GOLDEN.read_text(encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONIOENCODING": "utf-8"}
        out = subprocess.run([sys.executable, "-m", "tests.script.test_flowgraph", "--print"],
                             cwd=root, env=env, capture_output=True, timeout=120, check=True)
        assert out.stdout.decode("utf-8").replace("\r\n", "\n") == golden, seed


def main() -> None:
    import tempfile

    if not {"--write", "--print"} & set(sys.argv):
        raise SystemExit("usage: python -m tests.script.test_flowgraph --write | --print")
    with tempfile.TemporaryDirectory() as tmp:
        program, graph = lanterns(Path(tmp))
        text = dump(program, graph)
    if "--write" in sys.argv:
        GOLDEN.write_bytes(text.encode("utf-8"))
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()

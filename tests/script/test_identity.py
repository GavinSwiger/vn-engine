"""Stable statement identity and ``Program`` (F02 checklist step 8; ``04-technical.md`` §4.2,
§7.8; ADR-0006).

AC-F02-56 (format and golden values), AC-F02-57 (identities survive edits elsewhere),
AC-F02-59 (lookups never trust their input), and the parts of AC-F02-58 and AC-F02-60 that
need no loader. ``load_dir`` below copies a fixture folder into a temporary game folder and
runs the real loader (``StoryLoader``, step 6), whose last phase builds the ``Program``
(``iter_build_program``). AC-F02-68's ``compat/`` corpus is ``test_compat.py`` (step 11);
the tests below cover the same rules on generated labels and on ``lanterns/``.
"""

import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script.identity import (
    IDENTITY_SCHEME,
    IDENTITY_YIELD_ITEMS,
    assign,
    declaration_sid,
    register_declaration,
    statement_hash,
    walk_block,
)
from engine.script import identity
from engine.script.nodes import (
    Call,
    Define,
    If,
    Include,
    Jump,
    Label,
    Node,
    PyCode,
    PythonLine,
    Say,
    ScriptFile,
)
from engine.script.program import (
    LoadStats,
    Program,
    StmtLocation,
    build_program,
    iter_build_program,
)
from engine.script.loader import StoryLoader
from tests.script.helpers import FIXTURES, parse_text, template

ROOT = Path(__file__).resolve().parents[2]
LANTERNS = FIXTURES / "lanterns"
EDITS = FIXTURES / "lanterns-edits"
EXPECTED = FIXTURES / "lanterns.expected.json"
SID_RE = re.compile(r"^[^/]+/[0-9a-f]{12}(~[2-9]|~[1-9][0-9]+)?$")


# --- Loading a fixture through the real loader ------------------------------------------

def load_dir(root: Path, overrides: dict[str, str] | None = None) -> tuple[Program, list[Node]]:
    """Load a fixture story (``root`` holds ``main.vns`` and its includes) with
    ``load_story``'s ``StoryLoader``. ``overrides`` replaces a file's text. The story must
    load with no errors. Returns the ``Program`` and every top-level node in reading
    order."""
    with tempfile.TemporaryDirectory() as tmp:
        game = Path(tmp) / "game"
        shutil.copytree(root, game / "script")
        for rel, text in (overrides or {}).items():
            (game / "script" / rel).write_bytes(text.encode("utf-8"))
        loader = StoryLoader(GamePaths(game.resolve()))
        while not loader.step(math.inf):
            pass
    result = loader.result
    errors = [error.format() for error in result.errors]
    assert errors == [] and result.program is not None, errors
    return result.program, list(loader.nodes)


def sid_list(program: Program) -> list[str]:
    """Every sid reachable from a ``Program`` (labels, their statements, defines) in reading
    order: by file order, line, and column. This is ``lanterns.expected.json``."""
    nodes: list[Node] = list(program.defines)
    for label in program.labels.values():
        nodes.append(label)
        nodes.extend(program.statements_in(label.name))
    nodes.sort(key=lambda n: (n.file.order, n.line, n.column))
    return [node.sid for node in nodes]


def lanterns_sid_list() -> list[str]:
    return sid_list(load_dir(LANTERNS)[0])


def by_label(program: Program) -> dict[str, list[str]]:
    return {name: [s.sid for s in program.statements_in(name)] for name in program.labels}


def statement_sids(program: Program) -> set[str]:
    return {stmt.sid for stmt in program.iter_statements()}


@pytest.fixture(scope="module")
def lanterns() -> Program:
    return load_dir(LANTERNS)[0]


def _find(program: Program, label: str, kind: type, predicate=lambda s: True):
    found = [s for s in program.statements_in(label) if isinstance(s, kind) and predicate(s)]
    assert len(found) == 1, found
    return found[0]


# --- AC-F02-56 ---------------------------------------------------------------------------

def test_scheme_is_1():
    assert IDENTITY_SCHEME == 1
    assert identity.IDENTITY_SALT == "v1"


def test_hash_is_blake2b_6_bytes_of_the_salted_key():
    key = ("say", "hana", "Hi.")
    expected = hashlib.blake2b("v1\x1fsay\x1fhana\x1fHi.".encode("utf-8"),
                               digest_size=6).hexdigest()
    assert statement_hash(key) == expected
    assert re.fullmatch(r"[0-9a-f]{12}", expected)


def test_golden_values(lanterns):
    p = lanterns
    assert p.identity_scheme == 1
    assert _find(p, "start", PythonLine, lambda s: s.py.source == "trust = 1").sid == \
        "start/c65985b8a1e9"
    narration = _find(p, "riverbank", Say, lambda s: s.speaker is None)
    assert (narration.line, narration.end_line) == (2, 3)
    assert narration.sid == "riverbank/2444a8da9af1"
    assert _find(p, "riverbank", Say, lambda s: s.line == 4).sid == "riverbank/a0aae32c2d50"
    assert _find(p, "riverbank", Call).sid == "riverbank/d26e015c8dde"
    assert _find(p, "riverbank", If).sid == "riverbank/bb8832503b9b"
    assert _find(p, "riverbank", Jump).sid == "riverbank/ed2d7bd70e2c"
    assert [s.sid for s in p.statements_in("lantern_stall")][-1] == "lantern_stall/7892f6c9ce50"


def test_declaration_identities():
    program, nodes = load_dir(LANTERNS)
    assert program.label("riverbank").sid == "riverbank"
    assert [d.sid for d in program.defines] == ["define:hana", "define:daichi"]
    includes = [n.sid for n in nodes if isinstance(n, Include)]
    assert includes == ["include:chapter1.vns", "include:routes/daichi.vns"]
    for sid in ("riverbank", "define:hana", "include:chapter1.vns"):
        assert program.get(sid) is None
        assert program.location(sid) is None


def test_every_statement_sid_has_the_format_and_is_unique(lanterns):
    sids = [s.sid for s in lanterns.iter_statements()]
    assert len(sids) == len(set(sids)) == lanterns.stats.statements == 21
    for stmt in lanterns.iter_statements():
        assert SID_RE.match(stmt.sid), stmt.sid
        assert stmt.sid.startswith(stmt.label + "/")


def test_sid_list_matches_the_committed_file(lanterns):
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert sid_list(lanterns) == expected
    assert b"\r" not in EXPECTED.read_bytes()


@pytest.mark.parametrize("seed", ["0", "12345"])
def test_sid_list_is_the_same_in_another_process(seed):
    code = ("import json; from tests.script.test_identity import lanterns_sid_list; "
            "print(json.dumps(lanterns_sid_list()))")
    env = dict(os.environ, PYTHONHASHSEED=seed)
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
                         text=True, timeout=60, check=True).stdout
    assert json.loads(out) == json.loads(EXPECTED.read_text(encoding="utf-8"))


def test_identical_lines_get_a_counter():
    parsed = parse_text(template(S='hana "Hi."⏎[4]hana "Hi."'))
    file = parsed.nodes[0].file
    program = build_program([file], parsed.nodes)
    h = statement_hash(("say", "hana", "Hi."))
    sids = [s.sid for s in program.statements_in("start")]
    assert sids[1:3] == [f"start/{h}", f"start/{h}~2"]


def test_counter_counts_in_pre_order_across_branches():
    text = template(S='if x:⏎[8]hana "Hi."⏎[4]else:⏎[8]hana "Hi."⏎[4]hana "Hi."')
    text = "define x = 1\n" + text
    parsed = parse_text(text)
    program = build_program([parsed.nodes[0].file], parsed.nodes)
    h = statement_hash(("say", "hana", "Hi."))
    says = [s for s in program.statements_in("start") if s.identity_key()[2:] == ("Hi.",)]
    assert [s.sid for s in says] == [f"start/{h}", f"start/{h}~2", f"start/{h}~3"]
    assert [s.path for s in says] == [(1, 0, 0), (1, 1, 0), (2,)]


# --- AC-F02-57 ---------------------------------------------------------------------------

def _edit(name: str, overrides: dict[str, str] | None = None) -> Program:
    return load_dir(EDITS / name, overrides)[0]


def test_edit_a_line_added_elsewhere(lanterns):
    edited = by_label(_edit("a"))
    for name in ("start", "riverbank", "bridge"):
        assert edited[name] == by_label(lanterns)[name]
    assert len(edited["lantern_stall"]) == len(by_label(lanterns)["lantern_stall"]) + 1


def test_edit_b_label_moved_file_renamed_includes_swapped(lanterns):
    edited, nodes = load_dir(EDITS / "b")
    assert [f.ref for f in edited.files] == ["script/main.vns", "script/routes/daichi.vns",
                                             "script/ch1.vns"]
    assert edited.label("lantern_stall").file.ref == "script/routes/daichi.vns"
    assert by_label(edited) == by_label(lanterns)
    assert {n.sid for n in nodes if isinstance(n, Include)} == {
        "include:ch1.vns", "include:routes/daichi.vns"}


def test_edit_c_insert_and_delete_in_the_same_label(lanterns):
    before = by_label(lanterns)["riverbank"]
    after = by_label(_edit("c"))["riverbank"]
    new = statement_hash(("say", "", "New line."))
    assert after[0] == before[0]
    assert after[1] == f"riverbank/{new}" and after[1] not in before
    assert [s for s in before if s != "riverbank/d26e015c8dde"] == after[:1] + after[2:]


def test_edit_d_layout_attributes_comments_and_nesting_keep_every_sid(lanterns):
    edited = _edit("d")
    assert statement_sids(edited) == statement_sids(lanterns)
    assert sid_list(edited) != [] and set(sid_list(edited)) == set(sid_list(lanterns))
    moved = edited.get("riverbank/4e4d6a715d04")
    assert isinstance(moved, PythonLine) and len(moved.path) == 1
    assert lanterns.location("riverbank/4e4d6a715d04").path == (3, 0, 1)


def test_edit_e_text_change_changes_only_that_sid(lanterns):
    before, after = statement_sids(lanterns), statement_sids(_edit("e"))
    assert before - after == {"riverbank/a0aae32c2d50"}
    assert len(after - before) == 1


def test_edit_f_target_condition_and_code_change_those_sids(lanterns):
    before, after = statement_sids(lanterns), statement_sids(_edit("f"))
    assert before - after == {"start/c65985b8a1e9", "riverbank/bb8832503b9b",
                              "riverbank/ed2d7bd70e2c"}
    assert len(after - before) == 3


def test_edit_g_label_rename_changes_its_statements(lanterns):
    before, after = by_label(lanterns), by_label(_edit("g"))
    assert "riverbank" not in after
    assert after["river"] == ["river/" + s.split("/", 1)[1] for s in before["riverbank"]]
    assert after["lantern_stall"] == before["lantern_stall"]
    assert after["bridge"] == before["bridge"]
    # The jump into the renamed label changed its target, so (ADR-0006) its sid changes.
    changed = [(a, b) for a, b in zip(before["start"], after["start"]) if a != b]
    assert changed == [("start/db4469bc2b56",
                        "start/" + statement_hash(("jump", "river")))]


def test_edit_h_move_a_line_to_another_label(lanterns):
    before, after = statement_sids(lanterns), statement_sids(_edit("h"))
    assert before - after == {"riverbank/a0aae32c2d50"}
    assert after - before == {"lantern_stall/a0aae32c2d50"}


def test_edit_i_identical_lines_shift_only_their_counter():
    three_text = (EDITS / "i" / "chapter1.vns").read_text(encoding="utf-8")
    two_text = three_text.replace('    hana "Hi."\n', "", 1)
    two = by_label(_edit("i", {"chapter1.vns": two_text}))
    three = by_label(_edit("i"))
    h = "riverbank/" + statement_hash(("say", "hana", "Hi."))
    assert [s for s in two["riverbank"] if s.startswith(h)] == [h, h + "~2"]
    assert [s for s in three["riverbank"] if s.startswith(h)] == [h, h + "~2", h + "~3"]
    assert set(sum(three.values(), [])) - set(sum(two.values(), [])) == {h + "~3"}
    assert [s for s in two["riverbank"] if not s.startswith(h)] == \
        [s for s in three["riverbank"] if not s.startswith(h)]


def test_edit_j_full_width_speaker_keeps_the_sid(lanterns):
    edited = _edit("j")
    say = edited.get("riverbank/a0aae32c2d50")
    assert isinstance(say, Say) and say.speaker == "hana"
    assert by_label(edited) == by_label(lanterns)


# --- AC-F02-58 (stand-in until gen_corpus.py, step 6) ------------------------------------

def _story(lines: list[str]) -> Program:
    text = 'define hana = Character("Hana")\nlabel start:\n' + "".join(
        f"    {line}\n" for line in lines) + "    return\n"
    parsed = parse_text(text)
    assert parsed.errors == [], parsed.messages
    return build_program([parsed.nodes[0].file], parsed.nodes)


def test_inserting_20_lines_keeps_every_other_identity():
    rng = random.Random(1)
    lines = [rng.choice(['hana "Line {}."', '"Narration {}."', "$ x_{} = 1"]).format(i % 150)
             for i in range(600)]                         # repeats: ~n sequences included
    original = _story(lines)
    edited_lines = list(lines)
    for k in range(20):
        edited_lines.insert(rng.randrange(len(edited_lines) + 1), f'"Inserted {k}."')
    edited = _story(edited_lines)
    old = list(original.statements_in("start"))
    new = list(edited.statements_in("start"))
    inserted = [s for s in new if isinstance(s, Say) and s.text.startswith("Inserted")]
    kept = [s for s in new if s not in inserted]
    assert len(inserted) == 20 and len(kept) == len(old)
    assert [s.sid for s in kept] == [s.sid for s in old]
    assert not {s.sid for s in inserted} & {s.sid for s in old}


# --- AC-F02-59 ---------------------------------------------------------------------------

_BIG = "x" * (10 * 1024 * 1024)
G1 = [None, 5, 1.5, True, [], {}, ["x"], "", "/", "\ud800", _BIG]


def _timed(call):
    start = time.perf_counter()
    result = call()
    if isinstance(result, types.GeneratorType) or hasattr(result, "__next__"):
        result = list(result)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.05, elapsed
    return result


def _all_lookups(p: Program, value: object):
    return [
        _timed(lambda: p.get(value)),
        _timed(lambda: p.location(value)),
        _timed(lambda: p.label(value)),
        _timed(lambda: p.at(value, (0,))),
        _timed(lambda: p.at("riverbank", value)),
        _timed(lambda: p.at(value, value)),
        _timed(lambda: p.statements_in(value)),
    ]


@pytest.mark.parametrize("value", G1, ids=lambda v: repr(v)[:20])
def test_g1_junk_input(lanterns, value):
    assert all(r is None or r == [] for r in _all_lookups(lanterns, value))


@pytest.mark.parametrize("value", ["riverbank", "define:hana", "include:chapter1.vns"])
def test_g2_declarations_are_not_statements(lanterns, value):
    assert _timed(lambda: lanterns.get(value)) is None
    assert _timed(lambda: lanterns.location(value)) is None


@pytest.mark.parametrize("suffix", ["~0", "~1", "~02", "~٣", "~" + "9" * 5000])
def test_g3_counter_is_never_parsed(lanterns, suffix):
    sid = "riverbank/a0aae32c2d50"
    assert lanterns.get(sid) is not None
    assert _timed(lambda: lanterns.get(sid + suffix)) is None
    assert _timed(lambda: lanterns.location(sid + suffix)) is None


@pytest.mark.parametrize("label, path", [
    ("riverbank", (-1,)), ("riverbank", (True,)), ("riverbank", (1.0,)),
    ("riverbank", ("0",)), ("riverbank", (0, 99, 0)), ("riverbank", (0,) * 100000),
    ("riverbank", (1, 0, 0)), ("riverbank", (3, 0)), ("riverbank", (3, 9, 0)),
    ("riverbank", (3, 0, 9)), ("riverbank", (99,)), ("riverbank", (2 ** 100,)),
    ("riverbank", ()), ("riverbank", [3, True, 0]), ("riverbank", range(1)),
    (5, (0,)), ("nope", (0,)),
], ids=lambda v: repr(v)[:20])
def test_g4_bad_paths(lanterns, label, path):
    assert _timed(lambda: lanterns.at(label, path)) is None


def test_exact_identities_and_locations_return_their_node(lanterns):
    count = 0
    for stmt in lanterns.iter_statements():
        count += 1
        assert lanterns.get(stmt.sid) is stmt
        location = lanterns.location(stmt.sid)
        assert location == StmtLocation(stmt.label, stmt.path)
        assert lanterns.at(location.label, location.path) is stmt
        assert lanterns.at(location.label, list(location.path)) is stmt
        assert not isinstance(lanterns.get(stmt.sid), (Label, Define, Include))
    assert count == 21
    assert lanterns.at("riverbank", (3, 2, 1)).speaker == "daichi"
    assert lanterns.label("bridge") is lanterns.labels["bridge"]


def test_lookups_reject_str_subclasses(lanterns):
    class S(str):
        pass
    assert lanterns.get(S("riverbank/a0aae32c2d50")) is None
    assert lanterns.label(S("riverbank")) is None


# --- AC-F02-60 (on lanterns/; the example game, compat/, and the corpus come later) -------

def _code_objects(code: types.CodeType):
    yield code
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from _code_objects(const)


def _pieces(program: Program):
    for define in program.defines:
        yield define.value
    for stmt in program.iter_statements():
        if isinstance(stmt, PythonLine):
            yield stmt.py
        elif isinstance(stmt, If):
            yield from (b.condition for b in stmt.branches if b.condition is not None)


def test_what_f03_can_rely_on(lanterns):
    p = lanterns
    defined = {d.name for d in p.defines}
    pieces = list(_pieces(p))
    assert len(pieces) == 2 + 4 + 3          # defines, $ lines, conditions
    for stmt in p.iter_statements():
        if isinstance(stmt, Say):
            assert stmt.speaker is None or stmt.speaker in defined
        if isinstance(stmt, (Jump, Call)):
            assert stmt.target in p.labels
        if isinstance(stmt, If):
            keywords = [b.keyword for b in stmt.branches]
            assert keywords[0] == "if" and "if" not in keywords[1:]
            assert keywords.count("else") <= 1 and "else" not in keywords[:-1]
    for py in pieces:
        assert isinstance(py, PyCode) and isinstance(py.code, types.CodeType)
        file = _file_of(p, py)
        for code in _code_objects(py.code):
            assert code.co_filename == f"<{file.ref}>"
    nodes = [*p.defines, *p.labels.values(), *p.iter_statements()]
    for node in nodes:
        assert isinstance(node.file, ScriptFile)
        assert 1 <= node.line <= node.end_line and node.column >= 1
    with pytest.raises(TypeError):
        p.labels["x"] = p.labels["start"]  # type: ignore[index]
    with pytest.raises(AttributeError):
        p.labels = {}  # type: ignore[misc]
    assert isinstance(p.files, tuple) and isinstance(p.defines, tuple)


def _file_of(program: Program, py: PyCode) -> ScriptFile:
    for define in program.defines:
        if define.value is py:
            return define.file
    for stmt in program.iter_statements():
        if isinstance(stmt, PythonLine) and stmt.py is py:
            return stmt.file
        if isinstance(stmt, If) and any(b.condition is py for b in stmt.branches):
            return stmt.file
    raise AssertionError(py)


def test_nested_code_objects_name_the_script_file():
    parsed = parse_text(template(S="$ f = lambda: [y for y in (lambda: (1,))()]"))
    program = build_program([parsed.nodes[0].file], parsed.nodes)
    stmt = program.at("start", (1,))
    names = {c.co_filename for c in _code_objects(stmt.py.code)}
    assert len(list(_code_objects(stmt.py.code))) >= 3
    assert names == {"<script/main.vns>"}


# --- Program and the builder --------------------------------------------------------------

def test_stats_and_reading_order(lanterns):
    assert lanterns.stats.files == 3 and lanterns.stats.labels == 4
    assert lanterns.stats.statements == 21
    words = sum(len(s.text.split()) for s in lanterns.iter_statements() if isinstance(s, Say))
    assert lanterns.stats.words == words == 82
    assert list(lanterns.labels) == ["start", "riverbank", "lantern_stall", "bridge"]
    assert [f.order for f in lanterns.files] == [0, 1, 2]


def test_statements_in_is_pre_order(lanterns):
    stall = list(lanterns.statements_in("lantern_stall"))
    assert [type(s).__name__ for s in stall] == ["Say", "If", "PythonLine", "Return"]
    assert [s.path for s in stall] == [(0,), (1,), (1, 0, 0), (2,)]
    assert list(lanterns.iter_statements())[0].sid == "start/c65985b8a1e9"


def test_seconds_use_the_given_clock():
    parsed = parse_text(template())
    ticks = iter([12.5])
    program = build_program([parsed.nodes[0].file], parsed.nodes, started=10.0,
                            clock=lambda: next(ticks))
    assert program.stats.seconds == 2.5
    assert build_program([parsed.nodes[0].file], parse_text(template()).nodes).stats == \
        LoadStats(files=1, labels=2, statements=3, words=1, seconds=0.0)


def test_defines_keep_the_given_order():
    parsed = parse_text(template())
    defines = [n for n in parsed.nodes if isinstance(n, Define)][::-1]
    program = build_program([parsed.nodes[0].file], parsed.nodes, defines=defines)
    assert [d.name for d in program.defines] == ["daichi", "hana"]


def test_sliced_build_yields_and_gives_the_same_program():
    lines = [f'"Line {i}."' for i in range(2 * IDENTITY_YIELD_ITEMS + 10)]
    text = "label start:\n" + "".join(f"    {line}\n" for line in lines) + "    return\n"
    parsed_a, parsed_b = parse_text(text), parse_text(text)
    whole = build_program([parsed_a.nodes[0].file], parsed_a.nodes)
    job = iter_build_program([parsed_b.nodes[0].file], parsed_b.nodes)
    yields = 0
    while True:
        try:
            next(job)
            yields += 1
        except StopIteration as stop:
            sliced = stop.value
            break
    assert yields >= 4                          # 2 in assign, 2 in the index
    assert [s.sid for s in sliced.iter_statements()] == \
        [s.sid for s in whole.iter_statements()]
    assert sliced.stats.statements == len(lines) + 1


def test_program_built_directly_indexes_its_statements(lanterns):
    copy = Program(files=lanterns.files, labels=dict(lanterns.labels),
                   defines=lanterns.defines, stats=lanterns.stats)
    assert copy.get("riverbank/a0aae32c2d50") is lanterns.get("riverbank/a0aae32c2d50")
    assert copy.identity_scheme == IDENTITY_SCHEME
    with pytest.raises(TypeError):
        copy.labels["x"] = None  # type: ignore[index]


def test_deep_nesting_walks_without_recursion():
    depth = 49                                  # the label block is the 1st of 50
    rows = ["define x = 1", "label start:"]
    for d in range(depth):
        rows.append("    " * (d + 1) + "if x:")
    rows.append("    " * (depth + 1) + '"Deep."')
    parsed = parse_text("\n".join(rows) + "\n")
    assert parsed.errors == [], parsed.messages
    program = build_program([parsed.nodes[0].file], parsed.nodes)
    deep = list(program.statements_in("start"))[-1]
    assert isinstance(deep, Say) and deep.path == (0,) + (0, 0) * depth
    assert program.at("start", deep.path) is deep
    assert [s for s, _ in walk_block(program.labels["start"].block)][-1] is deep


def test_declarations_of_later_features_register(monkeypatch):
    class Fake(Node):
        __slots__ = ("name",)

    monkeypatch.setitem(identity._DECLARATIONS, Fake, lambda node: "fake:" + node.name)
    file = ScriptFile("script/main.vns", "main.vns", 0)
    node = Fake(file=file, line=1, end_line=1, column=1)
    node.name = "n"
    assign([node])
    assert node.sid == "fake:n" and declaration_sid(node) == "fake:n"
    with pytest.raises(ValueError):
        register_declaration(Say, lambda node: "x")
    with pytest.raises(ValueError):
        register_declaration(Label, lambda node: "x")

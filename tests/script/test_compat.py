"""The compatibility corpus (F02 checklist step 11; 06-acceptance.md §5.8): AC-F02-68.

``tests/fixtures/F02/compat/`` holds ``main.vns`` (LF), ``part.vns`` (CRLF with a BOM), and
``tabs/t.vns`` (tab-indented): about 125 lines using every F02 construct and the accepted edges
of AC-F02-13–16, 18, 21, 24, 27, 28, and 31. ``compat/expected.json`` is its program dump
(06 §0.5), committed once. The test never rewrites it: changing it needs a major version
(PR-F02-27). The reviewed command that wrote it is::

    .venv/Scripts/python -m tests.script.test_compat --write

The dump holds every node of the ``Program`` (files, defines, labels and their statements):
kind, file ref, line, end_line, column, fields, and sid. It leaves out what isn't F02's
language: ``Say.body`` (F05's parse of ``text``, which the dump already holds), ``Say.voice``
(F08's voice file, attached from a ``voice`` line, which F02's language has not), and the
compiled ``PyCode.code`` / ``comment_free`` (derived from ``source``).

Now that the corpus exists, the ACs whose earlier steps used a stand-in for it run on it here
too: AC-F02-15 (whitespace variants), AC-F02-16 (re-indented copies), AC-F02-30 (a test-only
spec for unbuilt words), and AC-F02-61 (the same result however the load is sliced).
"""

import json
import math
import random
import re
import shutil
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script import LoadOptions, StoryLoader, load_story
from engine.script.lexer import TAIL_SCRIPT
from engine.script.nodes import ScriptFile, norm
from engine.script.program import Program
from engine.script.statements import StatementSpec, register, registered_words, scoped_registry
from engine.script.words import STATEMENT_WORDS
from tests.script.helpers import FIXTURES

COMPAT = FIXTURES / "compat"
EXPECTED = COMPAT / "expected.json"
FILES = ("main.vns", "part.vns", "tabs/t.vns")
# Not part of the F02 language contract (module docstring).
_LEFT_OUT = frozenset(("body", "code", "comment_free", "voice"))


def _plain(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, frozenset):
        return sorted(value)
    if isinstance(value, ScriptFile):
        return value.ref
    if is_dataclass(value):
        out: dict[str, object] = {"kind": type(value).__name__}
        for f in fields(value):
            if f.name not in _LEFT_OUT:
                out[f.name] = _plain(getattr(value, f.name))
        return out
    return value


def program_dump(program: Program, *, positions: bool = True) -> str:
    """The program dump of 06 §0.5: canonical JSON, ``sort_keys``, ``ensure_ascii=False``, LF.
    Without ``positions``, line, end_line, and column are dropped ("same program ignoring
    positions"), and so is the line layout of bracket-continued Python: ``PyCode.source``
    keeps one code line per physical line, blank and indented as written (AC-F02-31), so it
    is compared whitespace-normalized as ADR-0006 does (``nodes.norm``)."""
    data = {
        "identity_scheme": program.identity_scheme,
        "files": _plain(program.files),
        "defines": _plain(program.defines),
        "labels": _plain(list(program.labels.values())),
    }
    if not positions:
        data = _drop_positions(data)
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1) + "\n"


def _drop_positions(value: object) -> object:
    if isinstance(value, list):
        return [_drop_positions(item) for item in value]
    if isinstance(value, dict):
        out = {k: _drop_positions(v) for k, v in value.items()
               if k not in ("line", "end_line", "column")}
        if out.get("kind") == "PyCode":
            out["source"] = norm(out["source"])
        return out
    return value


def _files(source: Path = COMPAT) -> dict[str, bytes]:
    return {name: (source / name).read_bytes() for name in FILES}


def _game(root: Path, files: dict[str, bytes]) -> GamePaths:
    for name, data in files.items():
        path = root / "script" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return GamePaths(root.resolve())


def load_compat(root: Path, files: dict[str, bytes] | None = None) -> Program:
    """Load the corpus (or edited copies of its files) from a game folder under ``root``;
    it must load clean (06 §0.5)."""
    result = load_story(_game(root, files if files is not None else _files()))
    assert result.errors == (), [e.format() for e in result.errors]
    assert result.warnings == (), [w.format() for w in result.warnings]
    assert not result.checks_skipped and not result.no_story
    assert result.program is not None
    return result.program


# --- AC-F02-68 ---------------------------------------------------------------------------

def test_ac68_the_corpus_has_its_committed_shape():
    main, part, tabs = (_files()[name] for name in FILES)
    assert b"\r" not in main and not main.startswith(b"\xef\xbb\xbf")
    assert part.startswith(b"\xef\xbb\xbf") and part.count(b"\r\n") == part.count(b"\n")
    assert all(line.startswith((b"\t", b"#", b"label")) or not line
               for line in tabs.split(b"\n"))
    assert 100 <= sum(data.count(b"\n") for data in (main, part, tabs)) <= 200


def test_ac68_program_dump_equals_expected_json(tmp_path):
    program = load_compat(tmp_path)
    assert program_dump(program).encode("utf-8") == EXPECTED.read_bytes(), (
        "the compat/ program dump changed: that needs a major version (PR-F02-27)")


def test_ac68_the_dump_covers_every_f02_construct(tmp_path):
    text = program_dump(load_compat(tmp_path))
    for kind in ("Label", "Define", "Say", "PythonLine", "If", "IfBranch", "Jump", "Call",
                 "Return", "PyCode"):
        assert f'"kind": "{kind}"' in text, kind
    data = json.loads(text)
    assert data["files"] == ["script/main.vns", "script/part.vns", "script/tabs/t.vns"]
    assert "mio" in {d["name"] for d in data["defines"]}               # NFKC (SR-F02-34)
    assert "始まり" in {label["name"] for label in data["labels"]}
    assert re.search(r'"attributes": \[\s*"a",\s*"b",\s*"c",\s*"2b"\s*\]', text)


def _test_spec(word: str) -> StatementSpec:
    return StatementSpec(word=word, placement="story", takes_block=False, tail=TAIL_SCRIPT,
                         parse=lambda raw, ctx: None)


def test_ac68_registering_every_unbuilt_word_leaves_the_dump_unchanged(tmp_path):
    expected = EXPECTED.read_bytes()
    with scoped_registry():
        unbuilt = sorted(STATEMENT_WORDS - registered_words())
        assert unbuilt                                    # later features still to come
        for word in unbuilt:
            register(_test_spec(word))
        program = load_compat(tmp_path)
    assert program_dump(program).encode("utf-8") == expected


# --- AC-F02-15 and AC-F02-16 on the corpus ------------------------------------------------

def _decoded() -> dict[str, str]:
    """The corpus as text (BOM dropped, line ends LF)."""
    return {name: data.decode("utf-8-sig").replace("\r\n", "\n")
            for name, data in _files().items()}


def _encoded(texts: dict[str, str]) -> dict[str, bytes]:
    return {name: text.encode("utf-8") for name, text in texts.items()}


def _each_line(text: str, change) -> str:
    return "\n".join(change(line) for line in text.split("\n"))


WHITESPACE_VARIANTS = {
    "blank-after-each": lambda t: "\n\n".join(t.split("\n")),
    "trailing-space": lambda t: _each_line(t, lambda line: line + " \t " if line else line),
    "whitespace-lines": lambda t: _each_line(t, lambda line: line + "\n  \t\u3000"),
    "no-final-break": lambda t: t.rstrip("\n"),
    "extra-breaks": lambda t: t + "\n" * 5,
}


@pytest.mark.parametrize("variant", list(WHITESPACE_VARIANTS))
def test_ac15_whitespace_never_changes_the_program(tmp_path, variant):
    original = program_dump(load_compat(tmp_path / "a"), positions=False)
    change = WHITESPACE_VARIANTS[variant]
    texts = {name: change(text) for name, text in _decoded().items()}
    changed = program_dump(load_compat(tmp_path / "b", _encoded(texts)), positions=False)
    assert changed == original


def test_ac15_an_empty_included_file_changes_nothing(tmp_path):
    original = program_dump(load_compat(tmp_path / "a"), positions=False)
    texts = _decoded()
    texts["main.vns"] = texts["main.vns"].replace('include "tabs/t.vns"\n',
                                                  'include "tabs/t.vns"\ninclude "empty.vns"\n')
    files = _encoded(texts) | {"empty.vns": b""}
    changed = json.loads(program_dump(load_compat(tmp_path / "b", files), positions=False))
    assert changed.pop("files")[-1] == "script/empty.vns"
    expected = json.loads(original)
    expected.pop("files")
    assert changed == expected


# ``label narrow:`` has mixed widths: body 2 spaces, the if's block 7, the else's block 3.
_NARROW_LEVELS = {2: 1, 3: 2, 7: 2}


def _reindent(text: str, unit: str, *, tabs: bool) -> str:
    """Each level of indentation (4 spaces, or a tab in the tab file; other space widths by
    ``_NARROW_LEVELS``, else rounded down) becomes ``unit``, so every line keeps its depth. Lines
    holding only whitespace stay as they are."""

    def fix(line: str) -> str:
        body = line.lstrip(" \t\u3000")
        if not body:
            return line
        lead = line[:len(line) - len(body)]
        if tabs:
            levels = len(lead) if set(lead) <= {"\t"} else None
        elif set(lead) <= {" "}:
            levels = _NARROW_LEVELS.get(len(lead), len(lead) // 4)
        else:
            levels = None
        return line if levels is None else unit * levels + body

    return _each_line(text, fix)


@pytest.mark.parametrize("unit", [" ", "  ", "   ", " " * 8, "\t"],
                         ids=["1", "2", "3", "8", "tab"])
def test_ac16_any_indentation_width_gives_the_same_program(tmp_path, unit):
    original = program_dump(load_compat(tmp_path / "a"), positions=False)
    texts = {name: _reindent(text, unit, tabs=name.startswith("tabs/"))
             for name, text in _decoded().items()}
    changed = program_dump(load_compat(tmp_path / "b", _encoded(texts)), positions=False)
    assert changed == original


# --- AC-F02-30 and AC-F02-61 on the corpus ------------------------------------------------

def test_ac30_a_spec_for_window_parses_window_and_leaves_the_dump_unchanged(tmp_path):
    """AC-F02-30 with ``window`` (``nvl`` until F17 built it)."""
    seen = []

    def parse(raw, ctx):
        seen.append(raw.word)
        return None

    with scoped_registry():
        register(StatementSpec(word="window", placement="story", takes_block=False,
                               tail=TAIL_SCRIPT, parse=parse))
        program = load_compat(tmp_path / "a")
        texts = _decoded()
        texts["tabs/t.vns"] = texts["tabs/t.vns"].replace("\treturn", "\twindow show\n\treturn")
        load_story(_game(tmp_path / "b", _encoded(texts)))
    assert program_dump(program).encode("utf-8") == EXPECTED.read_bytes()
    assert seen == ["window"]


def test_ac61_the_corpus_gives_the_same_result_however_sliced(tmp_path):
    paths = _game(tmp_path, _files())
    rng = random.Random(11)
    dumps, counts = [], []
    for budget in (lambda: math.inf, lambda: 0.0, lambda: rng.uniform(0, 0.002)):
        loader = StoryLoader(paths, LoadOptions(collect_todos=True))
        steps = 1
        while not loader.step(budget()):
            steps += 1
        assert loader.result.program is not None
        dumps.append(program_dump(loader.result.program))
        counts.append(steps)
    assert dumps[0] == dumps[1] == dumps[2]
    assert counts[0] == 1 and counts[1] > 5


# --- The reviewed command that wrote expected.json ----------------------------------------

def _write_expected() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "game"
        shutil.copytree(COMPAT, root / "script", ignore=shutil.ignore_patterns("*.json"))
        result = load_story(GamePaths(root.resolve()))
        assert result.program is not None and not result.errors and not result.warnings
        EXPECTED.write_bytes(program_dump(result.program).encode("utf-8"))
    print(f"wrote {EXPECTED}")


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        raise SystemExit("usage: python -m tests.script.test_compat --write")
    _write_expected()

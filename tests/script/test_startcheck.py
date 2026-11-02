"""The start-option checks (F44 C2: ``startcheck.py`` as F02 checks step 4b; F44
``04-technical.md`` §5.1; AC-F44's E26b/E26c rows as far as F02 can run them).

``LoadOptions.start`` carries the ``--start`` label. The ``--set`` names arrive with F44 step
1 (``StartOptions``); until then they are injected into ``CheckInput.start_names`` here. F02
has no ``default`` statement (F03), so every ``--set`` name that isn't a define gets the "no
default" variant in a load; the did-you-mean among defaults is tested on ``check_start``.
"""

from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script import loader as loader_module
from engine.script.checks import CheckInput, iter_checks
from engine.script.diagnostics import Diagnostic, DiagnosticSink
from engine.script.loader import LoadOptions, LoadResult, load_story
from engine.script.messages import format_message
from engine.script.nodes import ScriptFile
from engine.script.startcheck import check_start
from engine.script.statements import Collected, Uses
from tests.script.helpers import template

MAIN = "script/main.vns"
CLUB = template(T="label club_poem:⏎[4]return")


class SpyPaths(GamePaths):
    reads: list[str]

    def read_file(self, ref: str, *, max_bytes: int) -> bytes:
        self.reads.append(ref)
        return super().read_file(ref, max_bytes=max_bytes)


def make_game(root: Path, files: dict[str, str]) -> SpyPaths:
    for name, text in files.items():
        path = root / "script" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    paths = SpyPaths(root.resolve())
    object.__setattr__(paths, "reads", [])
    return paths


def load(paths: GamePaths, start: str | None = None) -> LoadResult:
    return load_story(paths, LoadOptions(start=start))


def codes(result: LoadResult) -> list[str]:
    return [error.code for error in result.errors]


@pytest.fixture
def set_names(monkeypatch):
    """``set_names(["a", "b"])``: the next loads check these ``--set`` names."""

    def install(names: list[str]) -> None:
        real = loader_module.iter_checks

        def with_names(inp: CheckInput):
            inp.start_names = tuple(names)
            return real(inp)

        monkeypatch.setattr(loader_module, "iter_checks", with_names)

    return install


# --- check_start -------------------------------------------------------------------------

def missing(name: str) -> Diagnostic:
    return Diagnostic("E26b", args=(name,))


def test_check_start_label():
    run = lambda label: check_start(label, (), labels={"club_poem"}, default_names=(),
                                    define_names={}, missing_label=missing)
    assert run(None) == [] and run("club_poem") == []
    assert run("start") == []                               # E26 covers a missing start
    found = run("ｚｚｚ")                                     # compared in canonical form
    assert [(d.code, d.args) for d in found] == [("E26b", ("zzz",))]
    assert found[0].file is None and found[0].line is None


def test_check_start_set_names_in_order():
    found = check_start(None, ["sayo_point", "wish_cost", "sayo_points", "nobody"],
                        labels=(), default_names=("sayo_points", "trust"),
                        define_names={"wish_cost", "sayori"}, missing_label=missing)
    assert [(d.code, d.args) for d in found] == [
        ("E26c", ("sayo_point", False, "sayo_points")),
        ("E26c", ("wish_cost", True)),
        ("E26c", ("nobody", False, None))]
    texts = [d.message() for d in found]
    assert texts[0] == ('"sayo_point" has no default, so --set can\'t give it a start value. '
                        'Did you mean "sayo_points"?')
    assert all(word in texts[1] for word in ("wish_cost", "define", "default"))
    assert "nobody" in texts[2] and "Did you mean" not in texts[2]


# --- E26b through a load -----------------------------------------------------------------------

def test_existing_start_label_loads(tmp_path):
    result = load(make_game(tmp_path, {"main.vns": CLUB}), "club_poem")
    assert result.errors == () and result.program is not None


@pytest.mark.parametrize("label,expected", [
    ("club_poen", 'There is no label named "club_poen" to start at (--start). Did you mean '
                  '"club_poem"?'),
    ("Club_Poem", 'There is no label named "Club_Poem" to start at (--start). Did you mean '
                  '"club_poem"?'),
    ("zzz", 'There is no label named "zzz" to start at (--start). Check the spelling, or add '
            "that label."),
])
def test_e26b_variants(tmp_path, label, expected):
    result = load(make_game(tmp_path, {"main.vns": CLUB}), label)
    assert codes(result) == ["E26b"]
    error = result.errors[0]
    assert error.message == expected and error.file is None and error.line is None


def test_e26b_not_included(tmp_path):
    paths = make_game(tmp_path, {"main.vns": CLUB,
                                 "chapter3.vns": "label late_scene:\n    return\n"})
    result = load(paths, "late_scene")
    assert codes(result) == ["E26b"]
    assert result.errors[0].message == (
        'There is no label named "late_scene" to start at (--start). It is defined in '
        'script/chapter3.vns, which is not included. Add include "chapter3.vns".')


def test_e26b_and_e43_share_one_scan(tmp_path):
    paths = make_game(tmp_path, {"main.vns": template(S="jump late_two"),
                                 "chapter3.vns": "label late_scene:\n    return\n"
                                                 "label late_two:\n    return\n"})
    result = load(paths, "late_scene")
    assert codes(result) == ["E43", "E26b"]
    assert all("script/chapter3.vns, which is not included" in e.message
               for e in result.errors)
    assert paths.reads == [MAIN, "script/chapter3.vns"]


def test_e26b_alone_reads_no_file_for_a_case_match(tmp_path):
    paths = make_game(tmp_path, {"main.vns": CLUB, "other.vns": "label x:\n"})
    result = load(paths, "CLUB_POEM")
    assert codes(result) == ["E26b"] and paths.reads == [MAIN]


def test_e26_still_applies(tmp_path):
    paths = make_game(tmp_path, {"main.vns": template(replace={3: "label begin:"},
                                                      T="label club_poem:⏎[4]return")})
    assert codes(load(paths, "club_poem")) == ["E26"]
    assert codes(load(paths, "zzz")) == ["E26", "E26b"]


# --- E26c and the order -----------------------------------------------------------------------

def test_error_order_e43_then_e26b_then_e26c(tmp_path, set_names):
    set_names(["sayo_point", "hana"])
    paths = make_game(tmp_path, {"main.vns": template(replace={6: "    jump nowhere"},
                                                      T="label club_poem:⏎[4]return")})
    result = load(paths, "zzz")
    assert codes(result) == ["E43", "E26b", "E26c", "E26c"]
    assert result.errors[0].line == 6
    assert "sayo_point" in result.errors[2].message and "default" in result.errors[2].message
    define = result.errors[3].message
    assert all(word in define for word in ('"hana"', "define", "default"))


def test_set_names_alone(tmp_path, set_names):
    set_names(["nobody"])
    result = load(make_game(tmp_path, {"main.vns": CLUB}))
    assert codes(result) == ["E26c"]
    assert "Did you mean" not in result.errors[0].message


# --- Skipped whenever E43 is ------------------------------------------------------------------

def test_skipped_after_a_file_that_cannot_be_read(tmp_path, set_names):
    set_names(["nobody"])
    paths = make_game(tmp_path, {"main.vns": template(T='include "missing.vns"')})
    result = load(paths, "zzz")
    assert codes(result) == ["E91"] and result.checks_skipped


def test_skipped_after_a_story_limit():
    collected = Collected()
    file = ScriptFile(MAIN, "main.vns", 0)
    collected.targets["nowhere"] = Uses([(file, 5)], 1)
    sink = DiagnosticSink()
    job = iter_checks(CheckInput(paths=None, sink=sink, collected=collected,  # type: ignore
                                 files=(), nodes=(), checks_skipped=False, limit_hit=True,
                                 unincluded=(), start="zzz", start_names=("nobody",)))
    for _ in job:
        pass
    assert sink.error_count == 0


def test_texts_follow_the_message_rules():
    for args in (("x", "y"), ("x", None, "script/c.vns"), ("x",)):
        text = format_message("E26b", args)
        assert text.startswith("There is no label named") and len(text) <= 1000
    for args in (("x", True), ("x", False, "y"), ("x", False)):
        text = format_message("E26c", args)
        assert "--set" in text and text.endswith((".", "?"))

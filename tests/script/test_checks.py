"""The whole-game checks (F02 checklist step 7; ``04-technical.md`` §7.6.3, §7.6.4).

AC-F02-23 (E25, E26), 26 (E43 and TR-F02-07's lazy scan), 27 (E70, E71, and the loading
rows), 29 (E47, E48, E48b, TR-F02-10's define order), and 47 (look-alike letters, W04 with
its 21-name case). Each message row also runs as a ``messages/cases.toml`` case; the tests
here cover the rest of each AC and the check rules (skipping, slicing, laziness).
"""

import random
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script import limits
from engine.script import checks as checks_module
from engine.script.checks import CheckInput, LazyDiagnostic, _Names, iter_checks
from engine.script.diagnostics import DiagnosticSink
from engine.script.loader import LoadResult, StoryLoader, load_story
from engine.script.nodes import ScriptFile
from engine.script.statements import Collected, Uses
from engine.script.suggest import suggest
from tests.script.helpers import template

MAIN = "script/main.vns"


# --- Helpers -----------------------------------------------------------------------------

class SpyPaths(GamePaths):
    """``read_file`` records every ref it is asked for (TR-F02-07)."""

    reads: list[str]

    def read_file(self, ref: str, *, max_bytes: int) -> bytes:
        self.reads.append(ref)
        return super().read_file(ref, max_bytes=max_bytes)


def spy(root: Path) -> SpyPaths:
    paths = SpyPaths(root.resolve())
    object.__setattr__(paths, "reads", [])
    return paths


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / "script" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def load(game, files: dict[str, str]) -> LoadResult:
    return load_story(game(files))


def codes(result: LoadResult) -> list[str]:
    return [error.code for error in result.errors]


def messages(result: LoadResult) -> list[str]:
    return [error.message for error in result.errors]


def warnings(result: LoadResult, code: str | None = None) -> list[str]:
    return [w.format() for w in result.warnings if code is None or w.code == code]


def loads(result: LoadResult) -> None:
    """06 §0.5 "loads clean"."""
    assert result.program is not None, [e.format() for e in result.errors]
    assert result.errors == () and result.warnings == (), warnings(result)


def run_checks(collected: Collected, *, checks_skipped: bool = False,
               limit_hit: bool = False) -> tuple[DiagnosticSink, checks_module.CheckOutput]:
    sink = DiagnosticSink()
    job = iter_checks(CheckInput(paths=None, sink=sink, collected=collected,  # type: ignore
                                 files=(), nodes=(), checks_skipped=checks_skipped,
                                 limit_hit=limit_hit, unincluded=()))
    while True:
        try:
            next(job)
        except StopIteration as stop:
            return sink, stop.value


F_MAIN = ScriptFile(MAIN, "main.vns", 0)
F_B = ScriptFile("script/b.vns", "b.vns", 1)


def uses(*places: tuple[ScriptFile, int]) -> Uses:
    found = Uses()
    for place in places:
        found.add(place)
    return found


# --- AC-F02-23: E25 and E26 ----------------------------------------------------------------

def test_ac23_e25_is_at_the_second_place_and_names_every_other(game):
    result = load(game, {
        "main.vns": template(T='include "b.vns"⏎include "c.vns"⏎include "d.vns"⏎'
                               'include "e.vns"⏎include "f.vns"'),
        **{f"{n}.vns": "label bridge:\n    return\n" for n in "bcdef"}})
    assert codes(result) == ["E25"]
    error = result.errors[0]
    assert (error.file, error.line) == ("script/b.vns", 1)
    assert error.message == (
        'there are other labels named "bridge" in script/main.vns, line 7, script/c.vns, '
        "line 1, script/d.vns, line 1, and 2 more places. Rename all but one.")


def test_ac23_erroneous_start_label_still_counts(game):
    result = load(game, {"main.vns": template(replace={3: "label start"})})
    assert codes(result) == ["E21"]                      # no E26 (SR-F02-69)


def test_ac23_e26_suggests_a_close_label_with_its_place(game):
    result = load(game, {"main.vns": template(replace={3: "label strat:"})})
    assert codes(result) == ["E26"]
    assert result.errors[0].message == (
        'The story has no label named "start". Did you mean "strat" (script/main.vns, '
        "line 3)?")
    assert result.errors[0].file is None and result.errors[0].line is None


def test_ac23_e26_is_not_skipped_by_a_parse_error_elsewhere(game):
    result = load(game, {"main.vns": template(replace={3: "label begin:"}, S="jmup x")})
    assert codes(result) == ["E30a", "E26"]


# --- AC-F02-26: E43 ------------------------------------------------------------------------

def test_ac26_erroneous_label_still_counts_as_a_target(game):
    result = load(game, {"main.vns": template(T='label rooftop: "x"⏎[4]return',
                                              S="jump rooftop")})
    assert codes(result) == ["E22"]


def test_ac26_one_error_per_name_at_its_first_use(game):
    result = load(game, {"main.vns": template(S="jump nowhere⏎[4]call nowhere⏎[4]jump x")})
    assert codes(result) == ["E43", "E43"]
    first, second = result.errors
    assert (first.line, second.line) == (5, 7)
    assert first.message == ('there is no label named "nowhere". It is also used at line 6. '
                             "Check the spelling, or add that label.")


def test_ac26_e43_message_stays_short(game):
    lines = "⏎".join("[4]jump nowhere" for _ in range(40))
    result = load(game, {"main.vns": template(T="label extra:⏎" + lines)})
    text = result.errors[0].format()
    assert "and 36 more places" in text and len(result.errors[0].message) <= 1000


def test_ac26_no_e43_reads_no_unincluded_file(tmp_path):
    root = write(tmp_path, {"main.vns": template(), "chapter3.vns": "label chapter3:\n"})
    paths = spy(root)
    result = load_story(paths)
    assert codes(result) == [] and warnings(result, "W02")
    assert paths.reads == [MAIN]


def test_ac26_case_insensitive_e43_reads_no_unincluded_file(tmp_path):
    root = write(tmp_path, {"main.vns": template(S="call Bridge"),
                            "chapter3.vns": "label Bridge2:\n"})
    paths = spy(root)
    result = load_story(paths)
    assert codes(result) == ["E43"] and paths.reads == [MAIN]


def test_ac26_not_included_reads_each_file_once_and_never_a_huge_one(tmp_path, opened):
    root = write(tmp_path, {"main.vns": template(S="jump chapter3⏎[4]jump chapter4"),
                            "chapter3.vns": "label chapter3:\n    return\n",
                            "a_other.vns": "# nothing\n"})
    huge = root / "script" / "big.vns"
    with open(huge, "wb") as stream:                       # sparse: st_size only
        stream.truncate(limits.SCRIPT_FILE_MAX_BYTES + 1)
    paths = spy(root)
    with opened() as events:
        result = load_story(paths)
    assert codes(result) == ["E43", "E43"]
    assert "is defined in script/chapter3.vns, which is not included" in messages(result)[0]
    assert messages(result)[1] == ('there is no label named "chapter4". Check the spelling, '
                                   "or add that label.")
    assert paths.reads.count("script/chapter3.vns") == 1
    assert sorted(paths.reads) == sorted([MAIN, "script/a_other.vns", "script/big.vns",
                                          "script/chapter3.vns"])
    assert not any(e == "open" and Path(p).name == "big.vns" for e, p in events)


def test_ac26_scan_ignores_read_problems_and_stops_at_its_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "SCRIPT_UNINCLUDED_SCAN_MAX_BYTES", 40)
    root = write(tmp_path, {"main.vns": template(S="jump late"),
                            "a.vns": "# " + "x" * 30 + "\n",
                            "b.vns": "label late:\n    return\n"})
    (root / "script" / "a_bad.vns").write_bytes(b"\xff\xfe\x00\x00")
    result = load_story(GamePaths(root.resolve()))
    # a.vns uses 33 of the 40 bytes, so b.vns (23 bytes) is not read: plain E43.
    assert messages(result) == ['there is no label named "late". Check the spelling, or add '
                                "that label."]


def test_ac26_scan_finds_a_label_in_a_non_utf8_file(tmp_path):
    root = write(tmp_path, {"main.vns": template(S="jump late")})
    (root / "script" / "b.vns").write_bytes(b"# caf\xe9\nlabel late:\n    return\n")
    result = load_story(GamePaths(root.resolve()))
    assert "It is defined in script/b.vns, which is not included." in messages(result)[0]


# --- AC-F02-27: speakers ---------------------------------------------------------------------

@pytest.mark.parametrize("files", [
    {"main.vns": template(S='kaito "Hi"', T='include "c.vns"'),
     "c.vns": 'define kaito = Character("K")\n'},
    {"main.vns": template(S='ｈａｎａ "Hi"')},
    {"main.vns": template(S='hana a b c d "Hi"')},
], ids=["defined-in-include", "fullwidth", "four-attributes"])
def test_ac27_loading_rows(game, files):
    loads(load(game, files))


def test_ac27_bad_define_gives_only_its_own_error(game):
    result = load(game, {"main.vns": template(T="define kaito = (1", S='kaito "Hi"')})
    assert codes(result) == ["E82"]


def test_ac27_e71_needs_the_name_defined_anywhere(game):
    result = load(game, {"main.vns": template(S="kaito Hello there.", T='include "c.vns"'),
                         "c.vns": 'define kaito = Character("K")\n'})
    assert codes(result) == ["E71"]
    assert messages(result) == ['kaito\'s line has no text in quotes. Put the text in '
                                'straight quotes: kaito "Hello there."']


# --- AC-F02-29: define order and cycles --------------------------------------------------------

def test_ac29_define_order_tr10(game):
    result = load(game, {"main.vns": template(T='define a = b + 1⏎include "d.vns"'),
                         "d.vns": "define b = 2\ndefine c = 3\n"})
    program = result.program
    assert program is not None, [e.format() for e in result.errors]
    names = [d.name for d in program.defines]
    assert names == ["hana", "daichi", "b", "a", "c"]
    for i, define in enumerate(program.defines):
        assert all(names.index(n) < i for n in define.value.names if n in names)


def test_ac29_define_order_follows_chains_and_reading_order(game):
    result = load(game, {"main.vns": template(
        T="define z = y + x⏎define y = x⏎define x = w⏎define w = 1⏎define v = 2")})
    assert [d.name for d in result.program.defines] == [
        "hana", "daichi", "w", "x", "y", "z", "v"]


def test_ac29_long_cycle_lists_three_links_and_more(game):
    result = load(game, {"main.vns": template(
        T="define a = b⏎define b = c⏎define c = d⏎define d = e⏎define e = a")})
    assert codes(result) == ["E48"]
    assert result.errors[0].message == (
        "define a uses b, b uses c, c uses d, and 2 more (script/main.vns, line 10, "
        "script/main.vns, line 11, script/main.vns, line 12, and 1 more place), so none of "
        "them can be set first. Change one so it doesn't use the others.")


def test_ac29_shortest_cycle_and_one_error_per_cycle_group(game):
    # a, b, c, d form one group; the shortest way from a back to a is a → d → a.
    result = load(game, {"main.vns": template(
        T="define a = b + d⏎define b = c⏎define c = a⏎define d = a⏎define user = a⏎"
          "define p = q⏎define q = p⏎define s = s")})
    assert codes(result) == ["E48", "E48", "E48b"]
    first, second, third = result.errors
    assert first.line == 9 and "define a uses d, and d uses a (script/main.vns, line 12)" \
        in first.message
    assert second.line == 14 and "define p uses q, and q uses p" in second.message
    assert third.line == 16 and third.message.startswith("define s uses itself")


def test_ac29_no_define_order_when_a_define_has_its_own_error(game):
    result = load(game, {"main.vns": template(T="define a = b⏎define b = a⏎define c = (1")})
    assert codes(result) == ["E82"]
    result = load(game, {"main.vns": template(T="define a = b⏎define b = a⏎define a = 1")})
    assert codes(result) == ["E47"]


def test_ac29_e47_at_the_second_place_naming_all_others(game):
    result = load(game, {"main.vns": template(
        T='define hana = 1⏎define hana = 2⏎include "b.vns"'),
        "b.vns": "define hana = 3\n"})
    assert codes(result) == ["E47"]
    error = result.errors[0]
    assert (error.file, error.line) == (MAIN, 9)
    assert error.message == ('"hana" is also defined in script/main.vns, line 1, '
                             "script/main.vns, line 10, and script/b.vns, line 1. Remove or "
                             "rename all but one.")


# --- AC-F02-47: look-alike letters and W04 -----------------------------------------------------

def test_ac47_w04_for_labels_and_defines_at_their_first_place(game):
    result = load(game, {"main.vns": template(
        T="label lοve:⏎[4]return⏎define hаna2 = 1⏎label привет:⏎[4]return⏎"
          "define 日本 = 1⏎define café = 1")})
    assert codes(result) == []
    assert warnings(result) == [
        'script/main.vns, line 9: the name "l\\u03bfve" mixes Latin and Greek letters, so it '
        "can look like another name. Type every letter in one alphabet.",
        'script/main.vns, line 11: the name "h\\u0430na2" mixes Latin and Cyrillic letters, so '
        "it can look like another name. Type every letter in one alphabet."]
    assert result.program is not None


def test_ac47_w04_cap_is_20_records_and_one_summary(game):
    defines = "⏎".join(f"define hаna{i} = 1" for i in range(1, 26))
    result = load(game, {"main.vns": template(T=defines)})
    found = [w.code for w in result.warnings]
    assert found == ["W04"] * limits.SCRIPT_W04_LIMIT + ["W04s"]
    assert result.warnings[-1].format() == "…and 5 more names mix alphabets."
    assert result.warnings[0].line == 9 and result.warnings[19].line == 28


def test_ac47_w04_is_logged_with_errors_too(game):
    result = load(game, {"main.vns": template(T="define hаna = 1", S="jump nowhere")})
    assert codes(result) == ["E43"] and [w.code for w in result.warnings] == ["W04"]


def test_ac47_lookalike_e43_and_e70(game):
    result = load(game, {"main.vns": template(S="jump bridgе⏎[4]hаna \"Hi\"")})
    assert codes(result) == ["E43", "E70"]
    assert messages(result)[0].endswith(
        'Did you mean "bridge"? "bridge" has e where "bridg\\u0435" has U+0435 CYRILLIC SMALL '
        "LETTER IE.")
    assert 'Did you mean "hana"?' in messages(result)[1]


# --- Skipping and story limits -----------------------------------------------------------------

def test_unreadable_file_skips_e26_e43_e70_but_not_duplicates(game):
    result = load(game, {"main.vns": template(
        replace={3: "label begin:"}, S='jump nowhere⏎[4]kaito "Hi"',
        T='include "missing.vns"⏎define hana = 2')})
    assert codes(result) == ["E91", "E47"]
    assert result.checks_skipped


def test_limit_hit_runs_only_duplicates():
    collected = Collected()
    collected.label_defs["bridge"] = [(F_MAIN, 7), (F_B, 1)]
    collected.define_defs["xа"] = [(F_MAIN, 1)]
    collected.targets["nowhere"] = uses((F_MAIN, 5))
    collected.speakers["kaito"] = uses((F_MAIN, 6))
    sink, out = run_checks(collected, limit_hit=True)
    assert [d.code for d in sink.kept()] == ["E25"]
    assert out.warnings == [] and out.defines is None


def test_checks_skipped_still_runs_define_order_and_w04():
    collected = Collected()
    collected.define_defs["xа"] = [(F_MAIN, 1)]
    collected.targets["nowhere"] = uses((F_MAIN, 5))
    sink, out = run_checks(collected, checks_skipped=True)
    assert sink.error_count == 0
    assert [w.code for w in out.warnings] == ["W04"]
    assert out.defines is None              # a define name with no Define node: no order


# --- Laziness and slicing ------------------------------------------------------------------------

def test_suggestions_are_built_only_for_reported_errors(game, monkeypatch):
    calls: list[str] = []

    def counting(written, candidates):
        calls.append(written)
        return suggest(written, candidates)

    monkeypatch.setattr(checks_module, "suggest", counting)
    lines = "⏎".join(f"[4]jump nowhere_{i:03}⏎[4]zed{i:03} \"x\"" for i in range(60))
    result = load(game, {"main.vns": template(T="label extra:⏎" + lines)})
    assert result.error_count == 120 and len(result.errors) == limits.SCRIPT_MAX_ERRORS
    assert len(calls) == limits.SCRIPT_MAX_ERRORS
    assert all(isinstance(e.message, str) for e in result.errors)


def test_lazy_diagnostic_builds_its_args_once():
    count = []

    def build():
        count.append(1)
        return ("nowhere",)

    diag = LazyDiagnostic("E43", F_MAIN, 5, build=build)
    assert diag.message() == diag.to_error().message
    assert len(count) == 1 and diag.args == ("nowhere",)


def test_names_index_gives_the_same_suggestions_as_suggest():
    rng = random.Random(7)
    letters = "abcdeABß_"
    names = sorted({"".join(rng.choice(letters) for _ in range(rng.randrange(1, 9)))
                    for _ in range(400)})
    index = _Names(names)
    for _ in range(200):
        written = "".join(rng.choice(letters) for _ in range(rng.randrange(1, 10)))
        if written in names:
            continue
        assert index.suggest(written) == suggest(written, names), written


def test_checks_yield_in_long_loops_and_give_the_same_result(tmp_path):
    lines = "⏎".join(f"[4]jump t{i}" for i in range(2 * 2_000 + 5))
    root = write(tmp_path, {"main.vns": template(T="label extra:⏎" + lines)})
    loader = StoryLoader(GamePaths(root.resolve()))
    steps = 0
    while not loader.step(0.0):
        steps += 1
    once = load_story(GamePaths(root.resolve()))
    assert [e.format() for e in loader.result.errors] == [e.format() for e in once.errors]
    assert loader.result.error_count == once.error_count == 4005
    assert steps > 4


def test_identity_yield_items_is_shared():
    from engine.script import identity
    assert identity.IDENTITY_YIELD_ITEMS == limits.IDENTITY_YIELD_ITEMS == 2_000
    assert checks_module.IDENTITY_YIELD_ITEMS is limits.IDENTITY_YIELD_ITEMS

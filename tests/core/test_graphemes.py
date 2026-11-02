"""``core.graphemes``: simplified extended grapheme clusters (F05 §7.1, I-14).

AC-F05-11. Code points are written as escapes so every row is unambiguous.
"""

import ast
import sys
import time
from itertools import islice
from pathlib import Path

import pytest

from engine.core import graphemes as graphemes_module
from engine.core.graphemes import MAX_CLUSTER_CODE_POINTS, graphemes, iter_graphemes

MODULE_PATH = Path(graphemes_module.__file__)

ACUTE = "́"
ZWJ = "‍"
VS16 = "️"
THUMBS_MEDIUM = "\U0001F44D\U0001F3FD"                                    # 👍🏽
FAMILY = "\U0001F468‍\U0001F469‍\U0001F467"                      # 👨‍👩‍👧
ENGLAND = "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"  # 🏴 tags
VICTORY = "✌️"                                                   # ✌️
JP = "\U0001F1EF\U0001F1F5"                                                # 🇯🇵
KR = "\U0001F1F0\U0001F1F7"                                                # 🇰🇷


# --- AC-F05-11 ----------------------------------------------------------------------------

@pytest.mark.parametrize("text, clusters", [
    ("e" + ACUTE, ["e" + ACUTE]),
    ("é", ["é"]),
    (THUMBS_MEDIUM, [THUMBS_MEDIUM]),
    (FAMILY, [FAMILY]),
    (ENGLAND, [ENGLAND]),
    (VICTORY, [VICTORY]),
    (JP, [JP]),
    (JP + "\U0001F1F0", [JP, "\U0001F1F0"]),            # the lone indicator alone
    ("한", ["한"]),     # Hangul L V T
    ("a\nb", ["a", "\n", "b"]),
    ("a b", ["a", " ", "b"]),
    ("日本語", ["日", "本", "語"]),
    ("مرحبا", ["م", "ر", "ح", "ب", "ا"]),
], ids=["e+acute", "e-acute", "thumbs-tone", "family-zwj", "england-tags", "victory-vs16",
        "flag", "flag+lone", "hangul-lvt", "newline", "space", "cjk", "arabic"])
def test_ac_f05_11_clusters(text, clusters):
    assert graphemes(text) == clusters


def test_ac_f05_11_mark_runs_are_cut_at_32_code_points():
    clusters = graphemes("a" + ACUTE * 100)
    assert [len(cluster) for cluster in clusters] == [32, 32, 32, 5]
    assert clusters[0] == "a" + ACUTE * 31
    assert MAX_CLUSTER_CODE_POINTS == 32


def test_ac_f05_11_module_imports_only_the_standard_library():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports"
            imported.add(node.module.split(".")[0])
    assert imported, "the scan found the imports"
    assert imported <= sys.stdlib_module_names, imported - sys.stdlib_module_names


def _is_literal(node: ast.AST) -> bool:
    if isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_literal(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return all(_is_literal(part) for part in [*node.keys, *node.values] if part is not None)
    return False


def test_no_tables_are_built_at_import():
    """I-14: module level holds only imports, literal constants, and functions."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue                                        # the docstring
        assert isinstance(node, (ast.Assign, ast.AnnAssign)), ast.dump(node)
        assert node.value is not None and _is_literal(node.value), ast.unparse(node)


# --- Edge cases ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, clusters", [
    ("", []),
    (ACUTE, [ACUTE]),                                         # a mark with no base
    (ACUTE * 2 + "a", [ACUTE * 2, "a"]),
    ("\n" + ACUTE, ["\n", ACUTE]),                            # controls take no marks
    ("a" + ACUTE + "\n", ["a" + ACUTE, "\n"]),
    ("\r\n", ["\r", "\n"]),                                   # every control is alone
    ("a\tb", ["a", "\t", "b"]),
    ("a " + ACUTE, ["a", " ", ACUTE]),              # line separator (Zl)
    ("a b", ["a", " ", "b"]),                       # paragraph separator (Zp)
    ("\x00\x7f", ["\x00", "\x7f"]),
    ("a" + ZWJ, ["a" + ZWJ]),                                 # trailing ZWJ
    ("a" + ZWJ + "\n", ["a" + ZWJ, "\n"]),                    # ZWJ never joins a control
    ("a" + ZWJ + "b", ["a" + ZWJ + "b"]),                     # simplified: joins any next
    (ZWJ + "a", [ZWJ + "a"]),
    ("\U0001F469\U0001F3FD‍\U0001F4BB", ["\U0001F469\U0001F3FD‍\U0001F4BB"]),
    ("1️⃣", ["1️⃣"]),                     # keycap: VS16 + Me
    ("a⃝", ["a⃝"]),                                 # enclosing mark (Me)
    ("का", ["का"]),                       # spacing mark (Mc)
    ("a\U000E0100", ["a\U000E0100"]),                         # ideographic VS (Mn)
    ("a\U0001F3FB", ["a\U0001F3FB"]),                         # modifier after any base
    ("\U0001F3FB", ["\U0001F3FB"]),
    (JP + KR, [JP, KR]),
    (JP + JP + "\U0001F1EF", [JP, JP, "\U0001F1EF"]),
    ("\U0001F1EF" + ACUTE + "\U0001F1F5", ["\U0001F1EF" + ACUTE, "\U0001F1F5"]),
    ("ᄀ가", ["ᄀ가"]),           # L L V
    ("각", ["각"]),                       # LV T
    ("가ᅡᆨ", ["가ᅡᆨ"]),           # LV V T
    ("각ᆨᆨ", ["각ᆨᆨ"]),           # LVT T T
    ("각ᅡ", ["각", "ᅡ"]),                   # LVT then V breaks
    ("ᆨᄀ", ["ᆨ", "ᄀ"]),                   # T then L breaks
    ("가가", ["가", "가"]),                   # two syllables
    ("ᄀ" + ACUTE + "ᅡ", ["ᄀ" + ACUTE, "ᅡ"]),   # a mark ends the jamo run
    ("ꥠힰퟋ", ["ꥠힰퟋ"]),           # extended jamo blocks
    ("ab", ["a", "b"]),
    ("\ud800a", ["\ud800", "a"]),                             # a lone surrogate is a base
], ids=repr)
def test_edge_clusters(text, clusters):
    assert graphemes(text) == clusters


@pytest.mark.parametrize("text, sizes", [
    ("a" + ACUTE * 31, [32]),
    ("a" + ACUTE * 32, [32, 1]),
    (ACUTE * 64, [32, 32]),
    (("\U0001F468" + ZWJ) * 20, [32, 8]),                     # a ZWJ chain is cut too
    ("a" + ACUTE * 31 + "\n" + ACUTE, [32, 1, 1]),
], ids=["31-marks", "32-marks", "64-marks-no-base", "zwj-chain", "cut-then-newline"])
def test_cluster_size_cap(text, sizes):
    assert [len(cluster) for cluster in graphemes(text)] == sizes


SAMPLES = [
    "Hello, world!", "a" + ACUTE * 100 + "b", FAMILY * 5 + ENGLAND + JP * 3 + "\U0001F1EF",
    "한각ᄀ" * 4, "日本語\nمرحبا\r\n\t" + ZWJ * 40,
    "".join(chr(code) for code in range(0x2F0, 0x380)),
]


@pytest.mark.parametrize("text", SAMPLES, ids=range(len(SAMPLES)))
def test_clusters_rebuild_the_text_and_stay_bounded(text):
    clusters = graphemes(text)
    assert "".join(clusters) == text
    assert all(1 <= len(cluster) <= MAX_CLUSTER_CODE_POINTS for cluster in clusters)
    assert list(iter_graphemes(text)) == clusters


def test_iteration_is_lazy_for_the_var_cut():
    """The ``{var}`` cut takes 200 graphemes of a 1,000,000-character value (04 §8)."""
    text = "x" * 1_000_000
    start = time.perf_counter()
    first = list(islice(iter_graphemes(text), 200))
    assert time.perf_counter() - start < 0.05
    assert first == ["x"] * 200

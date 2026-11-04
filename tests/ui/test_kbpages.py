"""F52 step P2: the on-screen keyboard's pages (``ui/kbpages.py``): AC-F52-20."""

import pytest

from engine.ui.kbpages import PAGE_KEYS, pages_for


def every(_ch: str) -> bool:
    return True


def labels(pages) -> list[str]:
    return [p.label for p in pages]


@pytest.mark.parametrize(("language", "allowed", "case", "expected"), [
    ("en", "any", None, ["ABC", "abc", "123", "ÀÉ", "àé"]),
    ("pt-BR", "any", None, ["ABC", "abc", "123", "ÀÉ", "àé"]),
    ("ru", "any", None, ["АБВ", "абв", "ABC", "abc", "123"]),
    ("uk", "name", None, ["АБВ", "абв", "ABC", "abc", "123"]),
    ("el", "any", None, ["ΑΒΓ", "αβγ", "ABC", "abc", "123"]),
    ("ja", "any", None, ["あ1", "あ2", "あ3", "ア1", "ア2", "ア3", "ABC", "abc", "123"]),
    ("en", "digits", None, ["123"]),                     # empty pages are dropped
    ("en", "letters", "upper", ["ABC", "ÀÉ"]),            # the other case's pages go
    ("ru", "letters", "lower", ["абв", "abc"]),
    ("en", "XYZ", None, ["XYZ"]),                        # an explicit string: its own pages
])
def test_ac_f52_20_pages(language, allowed, case, expected):
    pages = pages_for(language, allowed, case, every)
    assert labels(pages) == expected
    assert all(0 < len(p.keys) <= PAGE_KEYS for p in pages)


def test_ac_f52_20_page_contents():
    en = {p.label: p.keys for p in pages_for("en", "any", None, every)}
    assert en["ABC"] == tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ.,'-")
    assert len(en["123"]) == 40 and en["123"][:10] == tuple("0123456789")
    assert "Œ" in en["ÀÉ"] and "Ÿ" in en["ÀÉ"] and "×" not in en["ÀÉ"] and len(en["ÀÉ"]) == 32
    assert {"ß", "œ", "ÿ"} <= set(en["àé"]) and "÷" not in en["àé"]
    ru = {p.label: p.keys for p in pages_for("ru", "any", None, every)}
    assert ru["АБВ"][0] == "А" and "Ё" in ru["АБВ"] and len(ru["АБВ"]) == 33
    el = {p.label: p.keys for p in pages_for("el", "any", None, every)}
    assert len(el["ΑΒΓ"]) == 24 and "ς" in el["αβγ"]
    ja = {p.label: p.keys for p in pages_for("ja", "any", None, every)}
    assert ja["あ1"][:5] == tuple("あいうえお") and "ー" in ja["あ3"]
    assert ja["ア1"][:5] == tuple("アイウエオ") and "ー" in ja["ア3"]
    # Filtered by allowed: name keeps letters and ' - . but not 123's other marks.
    name = {p.label: p.keys for p in pages_for("en", "name", None, every)}
    assert set(name["123"]) == set("'-.")
    # An explicit string of 45 characters: two pages, labelled by their first three.
    alphabet = "".join(chr(0x4E00 + i) for i in range(45))
    pages = pages_for("en", alphabet, None, every)
    assert labels(pages) == [alphabet[:3], alphabet[40:43]]
    assert [len(p.keys) for p in pages] == [40, 5]
    # Filtered by what a font draws; a page left empty is dropped.
    pages = pages_for("ru", "any", None, lambda ch: not "Ѐ" <= ch <= "ӿ")
    assert labels(pages) == ["ABC", "abc", "123"]

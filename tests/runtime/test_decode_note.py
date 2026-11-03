"""F31 s3 — ``decode_note`` (F31 ``06-acceptance.md`` AC-F31-14; ``04`` §6.5; SEC-F31-05(a);
TR-F31-08; ``05`` group D)."""

import pytest

from engine.core.constants import META_READ_MAX_CHARS
from engine.runtime.metafiles import decode_note

ROWS = [
    (b"\xff", None),
    (b"\xc0\xaf", None),                                   # overlong "/"
    (b"\xed\xa0\x80", None),                               # an encoded surrogate
    (b"\xff\xfey\x00", None),                              # UTF-16 with BOM
    (b"", ""),
    (b"\xef\xbb\xbf", ""),
    (b"\xef\xbb\xbfyes", "yes"),
    (b"a\r\nb\rc", "a\nb\nc"),
    ("a b c".encode(), "a\nb\nc"),
    ("é".encode(), "é"),
    (b"a\x00b\x07c\td", "abc\td"),
    ("a‮b‍c".encode(), "abc"),
    ("a﻿b".encode(), "ab"),
    (b"a" * 2_001, "a" * 2_000),
    ("{b}x{/b} {{ {answer} [name]".encode(), "{b}x{/b} {{ {answer} [name]"),
    ("عائشة".encode(), "عائشة"),
    ("漢字".encode(), "漢字"),
]


@pytest.mark.parametrize("data, want", ROWS + [(b"a" + "́".encode() * 8_192, None)])
def test_ac_f31_14_decode_note(data, want):
    got = decode_note(data)
    if want is None and data.startswith(b"a\xcc\x81"):      # a + 16 KiB of U+0301
        assert got is not None and len(got) <= META_READ_MAX_CHARS
        assert got[0] == "á"
    else:
        assert got == want

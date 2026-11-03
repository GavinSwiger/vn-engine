"""F43 P3: reading and writing ``translations/<code>.po`` (``engine/script/po.py``).

AC-F43-02 (round trip of what the writer wrote, every field, byte for byte) and AC-F43-03
(W247 for files not read at all; W248 per bad entry with the rest used), plus a
100,000-entry timing smoke (``04`` §4 Q2 measured about 380 ms; no real-clock assert).
"""

import random
import time
from dataclasses import replace

from engine.core.constants import MB
from engine.script.messages import format_message
from engine.script.po import (
    PO_MAX_BYTES,
    PO_MAX_ENTRIES,
    PO_MAX_TEXT,
    PoEntry,
    PoFile,
    header_for,
    read_po,
    write_po,
)

REF = "translations/ja.po"

_FULL = PoEntry("festival/3", "He said you'd get lost at least twice.", "迷子になるって。",
                changed=True, was="He said you'd get lost.", who="hana",
                notes=("Hana · festival",), refs=("script/festival.vns:42",),
                comments=("check the tone", ""))
_ROUND_TRIP = {
    "every field": (header_for("ja"), (_FULL,), ("Japanese translation",)),
    "new and done": (header_for("ja"), (
        PoEntry("start/1", "The river was quiet.", ""),
        PoEntry("start/2", "Hello.", "こんにちは。", who="hana")), ()),
    "obsolete with was": (None, (
        PoEntry("old/1", "Gone.", "消えた。", changed=True, was="Gone!", obsolete=True,
                notes=("Narration · old",), comments=("keep?",)),
        PoEntry("old/2", "Line\ntwo", "", obsolete=True)), ()),
    "multi-line and escapes": (header_for("pt-BR"), (
        PoEntry("a/1", 'She said "hi"\\n\nthen left\n', 'Ela disse "oi"\tdepois\r'),
        PoEntry("a/2", "\n\n", "x\n"),
        PoEntry("a/3", "ctl \x00\x01\x1b\x7f end", "tab\there"),
        PoEntry("a/4", "{b}bold{/b} {{ {var=name}", "{b}太字{/b} {{ {var=name}")), ()),
    "keys and text of every family": (header_for("zh-Hans"), (
        PoEntry("start/2~2#over_the_bridge", "Over the bridge", "过桥"),
        PoEntry("word:ok@dark", "OK", "好"),
        PoEntry("value:???", "???", "？？？"),
        PoEntry("tip:lanterns:2", "", "", refs=("", "a b c")),
        PoEntry("game:title", "ゲーム", "游戏 \u202e\u2028 😀", notes=("",))), ()),
    "empty file": (None, (), ()),
    "header only": ("", (), ()),
}

# A file another tool wrote: other spellings read the same, and its canonical rewrite is
# stable.
_FOREIGN = (
    '\ufeff# header note\r\n'
    'msgid ""\r\n'
    'msgstr "Language: ja\\n"\r\n'
    '"Plural-Forms: nplurals=1; plural=0;\\n"\r\n'
    '\r\n'
    '#: a.vns:1 a.vns:2\r\n'
    '#, fuzzy, c-format\r\n'
    '#| msgctxt "old/1"\r\n'
    '#| msgid "Was "\r\n'
    '#| "here"\r\n'
    '  msgctxt "start/1"\r\n'
    'msgid "Hel"\r\n'
    '"lo \\x41\\101\\q"\r\n'
    'msgstr"やあ"\r\n'
    '#.vn-who: hana\r\n'
    'msgctxt "start/2"\r\n'
    'msgid "Bye"\r\n'
    'msgstr ""\r\n'
    '"またね"\r\n').encode("utf-8")


def _lean(entry: PoEntry) -> PoEntry:
    return replace(entry, was=None, notes=(), refs=(), comments=())


def test_ac_f43_02_round_trip_byte_for_byte():
    for name, (header, entries, header_comments) in _ROUND_TRIP.items():
        po = PoFile(header, entries, header_comments)
        data = write_po(po)
        assert data == write_po(header=header, entries=entries,
                                header_comments=header_comments), name
        back = read_po(data, REF)
        assert back.problems == () and back.unreadable is None, (name, back.problems)
        assert (back.header, back.entries, back.header_comments) == \
            (header, entries, header_comments), name
        assert write_po(back) == data, name
        lean = read_po(data, REF, lean=True)
        assert lean.entries == tuple(_lean(e) for e in entries), name
        assert [e.who for e in lean.entries] == [e.who for e in entries], name
        assert not data.startswith(b"\xef\xbb\xbf") and b"\r\n" not in data, name
        assert data == b"" or data.endswith(b"\n") and not data.endswith(b"\n\n"), name
    # The line an entry starts on (W248–W251's place) takes no part in equality.
    data = write_po(PoFile(header_for("ja"), (_FULL,)))
    entry = read_po(data, REF).entries[0]
    assert data.decode().split("\n")[entry.line - 1] == 'msgctxt "festival/3"'
    assert entry.changed and entry.was and entry.who == "hana"
    # The canonical layout, as Poedit and gettext read it.
    assert data.decode().split("\n\n")[1] == (
        "# check the tone\n#\n#. Hana · festival\n#. vn-who: hana\n"
        "#: script/festival.vns:42\n#, fuzzy\n#| msgid \"He said you'd get lost.\"\n"
        "msgctxt \"festival/3\"\nmsgid \"He said you'd get lost at least twice.\"\n"
        "msgstr \"迷子になるって。\"\n")
    # Another tool's spellings (CRLF, BOM, flags, continuation lines, escapes) read the
    # same; their canonical rewrite is stable.
    foreign = read_po(_FOREIGN, REF)
    assert foreign.problems == ()
    assert foreign.header_comments == ("header note",)
    assert foreign.language == "ja"
    first, second = foreign.entries
    assert (first.key, first.original, first.translation) == ("start/1", "Hello AA\\q", "やあ")
    assert first.changed and first.was == "Was here" and first.refs == ("a.vns:1 a.vns:2",)
    assert (second.who, second.translation, second.changed) == ("hana", "またね", False)
    canonical = write_po(foreign)
    assert write_po(read_po(canonical, REF)) == canonical
    # Line breaks in one-line fields are written as spaces (the file stays well formed).
    odd = PoEntry("k", "o", "t", who="a\nb", notes=("x\r\ny",), comments=("c\rd",))
    assert read_po(write_po(PoFile(None, (odd,))), REF).entries[0] == \
        replace(odd, who="a b", notes=("x y",), comments=("c d",))


def _entry(key: str, original: str = "Hi.", translation: str = "やあ。") -> str:
    return f'msgctxt "{key}"\nmsgid "{original}"\nmsgstr "{translation}"\n'


def _w248(form: str, line: int, *detail: object) -> tuple:
    return ("W248", (form, *detail), line)


# Each body sits after a good entry (lines 1–3, then a blank line 4) and before another
# good one; ``want`` is W248's (code, args, line) list; the good entries are always used
# (``_ALSO``: good entries inside a body).
_BAD = {
    "unclosed quote": ('msgctxt "b/1"\nmsgid "Hi.\nmsgstr "x"\n', [_w248("quote", 6)]),
    "text after the quote": ('msgctxt "b/1"\nmsgid "Hi." x\nmsgstr "x"\n',
                             [_w248("quote", 6)]),
    "escaped closing quote": ('msgctxt "b/1"\nmsgid "Hi.\\"\nmsgstr "x"\n',
                              [_w248("quote", 6)]),
    "quote in a continuation": ('msgctxt "b/1"\nmsgid ""\n"a\nmsgstr "x"\n',
                                [_w248("quote", 7)]),
    "no msgstr": ('msgctxt "b/1"\nmsgid "Hi."\n', [_w248("no_msgstr", 5)]),
    "no msgstr, next entry at once": ('msgctxt "b/1"\nmsgid "Hi."\nmsgctxt "b/2"\n'
                                      'msgid "x"\nmsgstr "y"\n', [_w248("no_msgstr", 5)]),
    "key twice": (_entry("a/1"), [_w248("twice", 5, "a/1")]),
    "key twice, obsolete": ('#~ msgctxt "a/1"\n#~ msgid "Hi."\n#~ msgstr "x"\n',
                            [_w248("twice", 5, "a/1")]),
    "plural": ('msgctxt "b/1"\nmsgid "apple"\nmsgid_plural "apples"\nmsgstr[0] "x"\n'
               'msgstr[1] "y"\n', [_w248("unsupported", 5)]),
    "unknown keyword": ('msgctxt "b/1"\nmsgid "Hi."\nmsgfoo "x"\nmsgstr "y"\n',
                        [_w248("unsupported", 5)]),
    "no msgctxt": ('msgid "Hi."\nmsgstr "x"\n', [_w248("unsupported", 5)]),
    "no msgid": ('msgctxt "b/1"\nmsgstr "x"\n', [_w248("unsupported", 5)]),
    "msgstr twice": ('msgctxt "b/1"\nmsgid "Hi."\nmsgstr "x"\nmsgstr "y"\n',
                     [_w248("unsupported", 5)]),
    "stray string": ('"floating"\n', [_w248("unsupported", 5)]),
    "garbage lines": ("this is not a po file\nnor this\n", [_w248("unsupported", 5)]),
    "two bad entries": ('msgctxt "b/1"\nmsgid "x\n\nmsgctxt "b/2"\nmsgid "y"\n',
                        [_w248("quote", 6), _w248("no_msgstr", 8)]),
    "a second empty-msgid entry": ('msgid ""\nmsgstr "Language: fr\\n"\n',
                                   [_w248("unsupported", 5)]),
}


_ALSO = {"no msgstr, next entry at once": ["b/2"]}


def test_ac_f43_03_hostile_files_warn_and_keep_the_rest():
    # W248: each bad entry is skipped with its line; the entries around it are used.
    for name, (body, want) in _BAD.items():
        text = _entry("a/1") + "\n" + body + "\n" + _entry("z/9")
        po = read_po(text.encode("utf-8"), REF)
        assert [(p.code, p.args, p.line) for p in po.problems] == want, name
        assert [e.key for e in po.entries] == ["a/1", *_ALSO.get(name, ()), "z/9"], name
        for problem in po.problems:
            assert problem.warning(REF).format().startswith(
                f"{REF}, line {problem.line}: "), name
    # W247: the whole file shows the original (no header, no entries), one warning, no line.
    good = _entry("a/1").encode()
    over = "".join(_entry(f"k/{i}", "a", "b") + "\n" for i in range(PO_MAX_ENTRIES + 1))
    at_cap = "".join(_entry(f"k/{i}", "a", "b") + "\n" for i in range(PO_MAX_ENTRIES))
    cases = {
        "utf8": [b"\xff\xfe" + good, good + b"\x80", "é".encode("latin-1"),
                 "\ud800".encode("utf-8", "surrogatepass"), "x".encode("utf-16")],
        "large": [b"#" * (PO_MAX_BYTES + 1)],
        "entries": [over.encode()],
    }
    for form, datas in cases.items():
        for data in datas:
            po = read_po(data, REF, language="Japanese")
            assert po.unreadable == form and po.entries == () and po.header is None, form
            assert [(p.code, p.args, p.line) for p in po.problems] == \
                [("W247", (form, "ja.po", "Japanese"), None)], form
            assert po.problems[0].warning(REF).format() == format_message(
                "W247", (form, "ja.po", "Japanese")), form
    assert read_po(b"#" * PO_MAX_BYTES, REF).unreadable is None
    po = read_po(at_cap.encode(), REF, lean=True)
    assert po.unreadable is None and len(po.entries) == PO_MAX_ENTRIES
    assert read_po(good, "translations/pt-BR.po").problems == ()
    assert read_po(b"\xff", "translations/pt-BR.po").problems[0].args[1:] == \
        ("pt-BR.po", "pt-BR")
    # The caps are the numbers W247's text shows.
    assert PO_MAX_TEXT == f"{PO_MAX_BYTES // MB} MB" and PO_MAX_ENTRIES == 100_000
    # Never raises: random bytes and random PO-ish lines.
    rng = random.Random(4243)
    pieces = ['msgctxt "', 'msgid "', 'msgstr "', '"', "\\", "#~ ", "#| ", "#. ", "#, fuzzy",
              "\n", "\n\n", "msgstr[0] ", "x", "é", "\r", " "]
    for _ in range(300):
        read_po(bytes(rng.randrange(256) for _ in range(rng.randrange(64))), REF)
        text = "".join(rng.choice(pieces) for _ in range(rng.randrange(80)))
        for lean in (False, True):
            po = read_po(text.encode(), REF, lean=lean)
            assert len({e.key for e in po.entries}) == len(po.entries)
            write_po(po)
    assert read_po("not bytes", REF).unreadable == "utf8"           # type: ignore[arg-type]


def test_po_100000_entries_timing_smoke():
    """04 §4 Q2: about 380 ms for 100,000 entries (lean). Printed, not asserted."""
    entries = tuple(PoEntry(f"start/{i}", f"Line {i} of the story.", f"物語の{i}行目。",
                            changed=i % 7 == 0, who="hana" if i % 2 else "",
                            notes=("Hana · start",), refs=(f"script/a.vns:{i}",))
                    for i in range(PO_MAX_ENTRIES))
    data = write_po(PoFile(header_for("ja"), entries))
    started = time.perf_counter()
    po = read_po(data, REF, lean=True)
    lean_ms = (time.perf_counter() - started) * 1000
    assert len(po.entries) == PO_MAX_ENTRIES and po.problems == ()
    print(f"\nF43 P3: read {len(data) / MB:.1f} MB, {PO_MAX_ENTRIES:,} entries, lean, "
          f"in {lean_ms:.0f} ms")

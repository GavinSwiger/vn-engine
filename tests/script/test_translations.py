"""F43 P6: the game's translation lookup table (``engine/script/translations.py``).

AC-F43-01 (which files in ``translations/`` are languages; W253), AC-F43-06 (Done and Changed
show the translation; New, skipped, refused and unreadable show the original; never blank)
and AC-F43-17 (``show = false`` hides a language in release runs only), as case tables, plus
the switch's slicing (``07`` I-13) with a fake clock: every unit returns to the caller, and
the sliced parse gives the whole-file read's entries, lines and problems.
"""

import pytest

from engine.core.errors import AssetTooLarge
from engine.script.po import read_po
from engine.script.translatekeys import SourceText, TextKind
from engine.script.translations import (
    MAX_LANGUAGES,
    ReadJob,
    TextTable,
    discover,
    read_language,
    shown_languages,
)

# --- AC-F43-01 ---------------------------------------------------------------------------

_MANY = [f"x{chr(97 + i // 26)}{chr(97 + i % 26)}.po" for i in range(MAX_LANGUAGES + 1)]

# names in translations/, original → (languages used, W253 (form, file) in name order)
_DISCOVER = {
    "valid tags": (["ja.po", "pt-BR.po", "zh-Hans.po", "es-419.po"], "en",
                   ["es-419", "ja", "pt-BR", "zh-Hans"], []),
    "bad names": (["japanese.po", "JA.po", "j.po", "ja_JP.po", "ja-.po", "ja.po"], "en",
                  ["ja"], [("bad_name", "JA.po"), ("bad_name", "j.po"),
                           ("bad_name", "ja-.po"), ("bad_name", "ja_JP.po"),
                           ("bad_name", "japanese.po")]),
    "the original's code": (["en.po", "ja.po"], "en", ["ja"], [("original", "en.po")]),
    "the original, another case": (["pt-br.po"], "pt-BR", [], [("original", "pt-br.po")]),
    "other files are ignored": (["README.txt", "ja.po.bak", "ja.po", "notes"], "en", ["ja"],
                                []),
    "a 33rd file": (_MANY, "en", [n[:-3] for n in _MANY[:MAX_LANGUAGES]],
                    [("too_many", _MANY[MAX_LANGUAGES])]),
    "no files": ([], "en", [], []),
}


@pytest.mark.parametrize("names, original, codes, w253", _DISCOVER.values(), ids=_DISCOVER)
def test_ac01_files_in_translations_are_languages_or_w253(names, original, codes, w253):
    found = discover(reversed(names), original)
    assert list(found.codes) == codes
    assert [(p.args[0], p.args[1]) for p in found.problems] == w253
    for warning, (form, file) in zip(found.warnings(), w253):
        assert warning.code == "W253" and warning.file == f"translations/{file}"
        assert warning.line is None and f"translations/{file} isn't used" in str(warning)


# --- AC-F43-06 ---------------------------------------------------------------------------

def _src(key, kind, original, who="", limit=None):
    return SourceText(key, kind, original, key.partition("/")[0], who, None, limit)


SOURCES = (
    _src("start/1", TextKind.LINE, "The lanterns are lit."),
    _src("start/2", TextKind.LINE, "He said you'd get lost.", "hana"),
    _src("start/3", TextKind.LINE, "The river was quiet."),
    _src("start/4", TextKind.QUESTION, "Which way?"),
    _src("start/4#left", TextKind.CHOICE, "Left"),
    _src("start/4#right", TextKind.CHOICE, "Right, {score} points"),
    _src("start/5", TextKind.LINE, "Hi {name}."),
    _src("start/6", TextKind.LINE, "Short."),
    _src("start/7", TextKind.LINE, "Hello."),
    _src("name:hana", TextKind.NAME, "Hana", "hana", 40),
    _src("word:ok", TextKind.WORD, "OK", "", 40),
    _src("chapter:one:title", TextKind.TITLE, "The Festival", "", 80),
    _src("value:???", TextKind.VALUE, "???"),
)

PO = '''msgid ""
msgstr ""
"Language: ja\\n"

msgctxt "start/1"
msgid "The lanterns are lit."
msgstr "提灯が灯っている。"

#. vn-who: hana
#, fuzzy
msgctxt "start/2"
msgid "He said you'd get lost."
msgstr "迷子になるって。"

msgctxt "start/3"
msgid "The river was quiet."
msgstr ""

msgctxt "start/4"
msgid "Which way?"
msgstr "{bold}どっち{/bold}?"

msgctxt "start/4#left"
msgid "Left"
msgstr "左"

msgctxt "start/4#right"
msgid "Right, {score} points"
msgstr "右、{score}点 {coins}"

msgctxt "start/5"
msgid "Hi {name}."
msgstr "やあ。"

msgctxt "start/6"
msgid "Short."
msgstr "短い。"

msgctxt "start/7"
msgid "Hello.
msgstr "こんにちは。"

msgctxt "name:hana"
msgid "Hana"
msgstr "{b}花{/b}"

msgctxt "word:ok"
msgid "Okay"
msgstr "了解"

msgctxt "chapter:one:title"
msgid "The Festival"
msgstr "祭り"

msgctxt "value:???"
msgid "???"
msgstr "？？？"

#~ msgctxt "old/1"
#~ msgid "Gone."
#~ msgstr "消えた。"
'''

# lookup → (shown, warning codes that lookup raises)
_SHOWN = {
    "Done line": (lambda t: t.line("start/1"), "提灯が灯っている。", []),
    "Changed (fuzzy) shows the old translation": (lambda t: t.line("start/2"), "迷子になるって。",
                                                  []),
    "typo fix: a word's original changed": (lambda t: t.word("ok"), "了解", []),
    "Done choice": (lambda t: t.choice("start/4", "left"), "左", []),
    "Done title": (lambda t: t.title("chapter:one:title"), "祭り", []),
    "Done variable text": (lambda t: t.value("???"), "？？？", []),
    "W251 note: used (dev)": (lambda t: t.line("start/5"), "やあ。", ["W251"]),
    "New: the original": (lambda t: t.line("start/3"), None, []),
    "skipped (W248 at load): the original": (lambda t: t.line("start/7"), None, []),
    "refused W249 (tag), once": (lambda t: t.line("start/4"), None, ["W249"]),
    "refused W250 (extra var)": (lambda t: t.choice("start/4", "right"), None, ["W250"]),
    "refused W249 (name with tags)": (lambda t: t.name("hana"), None, ["W249"]),
    "refused W248 (longer than the cap)": (lambda t: t.line("start/6"), None, ["W248"]),
    "Unused: never shown": (lambda t: t.text("old/1"), None, []),
    "unknown key": (lambda t: t.line("nowhere/1"), None, []),
}

_LIMITED = tuple(s if s.key != "start/6" else _src("start/6", TextKind.LINE, "Short.", limit=2)
                 for s in SOURCES)


@pytest.mark.parametrize("dev", [True, False], ids=["dev", "release"])
@pytest.mark.parametrize("lookup, shown, codes", _SHOWN.values(), ids=_SHOWN)
def test_ac06_done_and_changed_show_the_rest_show_the_original(lookup, shown, codes, dev):
    result = read_language("ja", "ja.po", PO.encode("utf-8"), _LIMITED, dev=dev)
    assert [(w.code, w.file, w.line) for w in result.warnings] == [
        ("W248", "translations/ja.po", 41)]                     # start/7's quote, at load
    table = result.table
    raised = []
    table.warn = raised.append
    assert lookup(table) == shown
    assert lookup(table) == shown                               # memoized, warned once
    want = [c for c in codes if dev or c != "W251"]
    assert [w.code for w in raised] == want
    assert all(w.file == "translations/ja.po" and w.line for w in raised)
    # Never blank: a lookup is a translation or None, for every key.
    assert all(table.text(s.key) != "" for s in _LIMITED)


@pytest.mark.parametrize("read, form", [
    (lambda: b"msgctxt \"start/1\"\nmsgid \"x\"\nmsgstr \"\xff\"\n", "utf8"),
    (lambda: (_ for _ in ()).throw(AssetTooLarge("translations/ja.po", 1)), "large"),
], ids=["not UTF-8", "too large"])
def test_ac06_an_unreadable_file_shows_originals_only(read, form):
    result = ReadJob("ja", "ja.po", read, SOURCES).run()
    assert result.table.unreadable == form and len(result.table) == 0
    assert result.table.line("start/1") is None
    assert [(w.code, w.file, w.line) for w in result.warnings] == [
        ("W247", "translations/ja.po", None)]
    assert "so Japanese shows the original text" in str(result.warnings[0])


# --- AC-F43-17 ---------------------------------------------------------------------------

_SHOW = {
    "release hides show = false": (True, ["ja", "ko", "fr"], {"ko": False, "fr": True},
                                   ["ja", "fr"]),
    "dev keeps every language": (False, ["ja", "ko"], {"ko": False}, ["ja", "ko"]),
    "no section: shown": (True, ["ja"], {}, ["ja"]),
    "all hidden": (True, ["ja", "ko"], {"ja": False, "ko": False}, []),
}


@pytest.mark.parametrize("release, codes, show, want", _SHOW.values(), ids=_SHOW)
def test_ac17_show_false_hides_a_language_in_release_runs_only(release, codes, show, want):
    assert list(shown_languages(codes, show, release=release)) == want


# --- Slicing (07 I-13; ADR-0005 F43 amendment) -------------------------------------------

class _Clock:
    """Each read moves time on by one tick."""

    def __init__(self) -> None:
        self.now = 0.0
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        self.now += 1.0
        return self.now


def _big_po(n: int) -> str:
    out = ['msgid ""\nmsgstr "Language: ja\\n"\n']
    for i in range(n):
        if i % 97 == 5:
            out.append(f'msgctxt "s/{i}"\nmsgid "Line {i}\nmsgstr "x"\n')     # W248 quote
        elif i % 113 == 7:
            out.append(f'msgctxt "s/{i - 300}"\nmsgid "again"\nmsgstr "x"\n')  # W248 twice
        else:
            fuzzy = "#, fuzzy\n" if i % 5 == 0 else ""
            out.append(f'#. vn-who: hana\n{fuzzy}msgctxt "s/{i}"\nmsgid "Line {i}."\n'
                       f'msgstr "行{i}。"\n')
    return "\r\n".join("\n".join(out).split("\n"))                          # CRLF lines


def test_switch_runs_in_slices_and_the_sliced_parse_is_the_whole_file_read():
    n = 2_000
    data = _big_po(n).encode("utf-8")
    sources = tuple(_src(f"s/{i}", TextKind.LINE, f"Line {i}.", "hana") for i in range(n))
    clock = _Clock()
    job = ReadJob("ja", "ja.po", lambda: data, sources, dev=True, clock=clock,
                  chunk_chars=4_096)
    slices = 0
    while not job.run_for(clock() + 2):        # two ticks: at most two units per slice
        slices += 1
        before = job.steps
        assert slices < 10_000
    sliced = job.result
    assert job.steps > 20 and slices > 10      # the parse alone is many units

    whole = ReadJob("ja", "ja.po", lambda: data, sources, chunk_chars=len(data) * 2).run()
    po = read_po(data, "translations/ja.po", lean=True)
    assert sliced.problems == whole.problems == po.problems
    assert sliced.entries == whole.entries == len(po.entries)
    assert sliced.table._pending == whole.table._pending
    assert len(sliced.table) == sum(1 for i in range(n) if i % 97 != 5 and i % 113 != 7)

    # The dev sweep checks in slices too, and leaves nothing unchecked.
    table = sliced.table
    sweeps = 0
    while not table.sweep(clock() + 1, clock):
        sweeps += 1
    assert sweeps > 10 and table.unchecked == 0
    assert table.line("s/1") == "行1。"
    del before

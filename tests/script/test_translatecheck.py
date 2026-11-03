"""F43 P5: checking a translation as its kind (``engine/script/translatecheck.py``).

AC-F43-07 (per-kind checks: W249 with the script's own tag message, choice rules, titles
refuse tags, length limits), AC-F43-08 (W250 for an extra ``{var}``/``{username}``; with
W251's note for a left-out one) and AC-F43-23 (W254 once per file), as case tables.
"""

import enum

from engine.script.messages import format_message
from engine.script.po import PoProblem
from engine.script.translatecheck import (
    EntryCheck,
    check_entry,
    has_rtl,
    missing_chars,
    rtl_warning,
    shown_text,
)
from tests.script.helpers import one_error
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)

REF = "translations/ja.po"


class _Kind(enum.Enum):
    """Stands in for ``translatekeys.TextKind`` (``check_entry`` reads ``.value``)."""

    LINE = "line"
    CHOICE = "choice"


def _say(text: str) -> str:
    return one_error(f'label start:\n    "{text}"\n').message


def _choice(text: str) -> str:
    return one_error(f'label start:\n    menu:\n        "{text}":\n            "x"\n').message


# (kind, key, original, translation, limit) → None (used, no problem) or the W248/W249
# problem's args. W249 carries the message the same mistake gets in a script line.
_KINDS = {
    "line: good tags": (("line", "s/1", "Hi {b}there{/b}.", "{i}やあ{/i}。", 300), None),
    "line: unclosed": (("line", "s/1", "Hi.", "やあ{b", None), ("W249", _say("Hi {b"))),
    "line: unknown tag": (("line", "s/1", "Hi.", "{bold}やあ{/bold}", None),
                          ("W249", _say("{bold}Hi{/bold}"))),
    "line: closes nothing": (("line", "s/1", "Hi.", "やあ{/i}", None), ("W249", _say("Hi{/i}"))),
    "line: bad number": (("line", "s/1", "Hi.", "{pause=50}やあ", None),
                         ("W249", _say("{pause=50}Hi"))),
    "line: F29 effect inside another": (("line", "s/1", "Hi.", "{shake}{wave}や{/wave}{/shake}",
                                         None),
                                        ("W249", _say("{shake}{wave}H{/wave}{/shake}"))),
    "line: {next} not last": (("line", "s/1", "Hi.", "{next}やあ", None),
                              ("W249", _say("{next}Hi"))),
    "question: tag rules as a line": (("question", "s/4", "Which?", "{size=9}どっち", None),
                                      ("W249", _say("{size=9}Which"))),
    "line: {username} is fine": (("line", "s/1", "Hi {username}.", "{username}、やあ", None),
                                 None),
    "choice: good tags": (("choice", "s/4#go", "Go", "{b}行く{/b}", None), None),
    "choice: {pause}": (("choice", "s/4#go", "Go", "行く{pause}", None),
                        ("W249", _choice("Go{pause}"))),
    "choice: effect": (("choice", "s/4#go", "Go", "{wave}行く{/wave}", None),
                       ("W249", _choice("{wave}Go{/wave}"))),
    "choice: {username}": (("choice", "s/4#go", "Go", "{username}", None),
                           ("W249", _choice("{username}"))),
    "chapter title: tag": (("title", "chapter:one:title", "Fest", "{b}祭り{/b}", 120),
                           ("W249", format_message("E222", ("tags",)))),
    "chapter title: {username}": (("title", "chapter:one:heading", "One", "{username}", 60),
                                  ("W249", format_message("E302", ("title_card",)))),
    "ending title: tag": (("title", "ending:good:title", "Good", "{i}良い", None),
                          ("W249", format_message("E242", ("tags", "ending")))),
    "route title: tag": (("title", "route:hana", "Hana", "{color=#ff0000}花", None),
                         ("W249", format_message("E242", ("tags", "route")))),
    "tip title: tag": (("title", "tip:lanterns:title", "Lanterns", "{var=x}", None),
                       ("W249", format_message("E252", ("tags", "tip")))),
    "codex category: tag": (("title", "codex:category:People", "People", "{b}人", None),
                            ("W249", format_message("E252", ("tags", "tip")))),
    "gallery title: tag": (("title", "gallery:cg a", "A", "{b}A", None),
                           ("W249", format_message("E344", ("tags",)))),
    "track title: tag": (("title", "track:theme", "Theme", "{b}曲", None),
                         ("W249", format_message("E336", ("tags",)))),
    "replay title: tag": (("title", "replay:fest", "Fest", "{b}祭", None),
                          ("W249", format_message("E350", ("tags",)))),
    "achievement description: tag": (("title", "achievement:a:description", "A", "{b}A", None),
                                     ("W249", format_message("E339", ("tags",)))),
    "flowchart title: tag": (("title", "flowchart:s/1", "Start", "{var=x}", None),
                             ("W249", format_message("E263", ("tags",)))),
    "title: plain braces show as written": (("title", "chapter:one:title", "Fest",
                                             "{祭り} {{", None), None),
    "codex paragraph: allowed tags": (("title", "tip:lanterns:2", "Lit.", "{b}灯{/b}", 2000),
                                      None),
    "codex paragraph: {pause}": (("title", "item:key:1", "Old.", "古い{pause}", 2000),
                                 ("W249", format_message("E252", ("tag", "pause", "item")))),
    "codex paragraph: bad tag": (("title", "tip:lanterns:2", "Lit.", "灯{b", 2000),
                                 ("W249", _say("Lit{b"))),
    "name: braces": (("name", "name:hana", "Hana", "{b}花{/b}", 24),
                     ("W249", format_message("E169", ("{b}花{/b}",)))),
    "name: {username}": (("name", "name:hana", "Hana", "{username}", 24),
                         ("W249", format_message("E302", ("name",)))),
    "window title: tag": (("effect", "s/9", "Hello?", "{username}?", 120),
                          ("W249", format_message("E300", ("tags",)))),
    "window title: plain": (("effect", "s/9", "Hello?", "もしもし{", 120), None),
    "word: shown as written": (("word", "word:ok", "OK", "{b}", 24), None),
    "value: shown as written": (("value", "value:???", "???", "{var=x}", None), None),
    "game title: shown as written": (("game", "game:title", "Game", "{b}ゲーム", None), None),
    "line: at the cap": (("line", "s/1", "Hi.", "あ" * 10, 10), None),
    "line: over the cap": (("line", "s/1", "Hi.", "あ" * 11, 10), ("W248", "long", 10)),
    "name: over the cap": (("name", "name:hana", "Hana", "x" * 25, 24), ("W248", "long", 24)),
    "word: over the cap": (("word", "word:ok", "OK", "x" * 25, 24), ("W248", "long", 24)),
}


def test_ac_f43_07_each_kind_is_checked_as_its_kind():
    for name, ((kind, key, original, translation, limit), want) in _KINDS.items():
        result = check_entry(kind, original, translation, key=key, limit=limit, line=120)
        if want is None:
            assert result == EntryCheck(True), (name, result)
            continue
        code, *args = want
        assert result == EntryCheck(False, (PoProblem(code, tuple(args), 120),)), name
        text = result.problems[0].warning(REF).format()
        assert text.startswith(f"{REF}, line 120: ") and text.endswith(
            "so the original text is shown." if code == "W249" else "so this entry is skipped."
        ), name
    # An empty translation is New: not shown, nothing to report. Kinds may be TextKind.
    assert check_entry("line", "Hi.", "") == EntryCheck(False)
    assert check_entry(_Kind.CHOICE, "Go", "{pause}行く").problems[0].code == "W249"
    assert check_entry(_Kind.LINE, "Go", "行く") == EntryCheck(True)
    # Never raises, whatever the text.
    for text in ("{", "}", "{{", "{=}", "{/}", "{" * 60, "{b}" * 60, "\x00{\ud800}", "{var=}"):
        for kind in ("line", "question", "choice", "title", "name", "effect", "word", "x"):
            check_entry(kind, text, text, key="tip:a:1")
            check_entry(kind, "Hi.", text, key="chapter:a:title")


# (kind, original, translation) → None (used, no note), ("W250", names) refused, or
# ("W251", names) used with the note. Names are listed without braces.
_VARS = {
    "same vars": (("line", "Hi {var=name}, {var=score}.", "{var=score}{var=name}やあ"), None),
    "extra var": (("line", "Hi.", "やあ{var=score}"), ("W250", "score")),
    "extra vars": (("line", "Hi {var=name}.", "{var=score}{var=lives}{var=name}"),
                   ("W250", ("score", "lives"))),
    "extra {username}": (("line", "Hi.", "やあ{username}"), ("W250", "username")),
    "extra {username=var}": (("line", "Hi.", "{username=hana_name}"), ("W250", "hana_name")),
    "{username=var} matches {var=var}": (("line", "Hi {var=hana_name}.", "{username=hana_name}"),
                                         None),
    "a shown brace is no var": (("line", "{{var=score}} pts", "{var=score}点"),
                                ("W250", "score")),
    "extra var in a choice": (("choice", "Go", "{var=place}へ"), ("W250", "place")),
    "extra var in a question": (("question", "Which?", "{var=x}?"), ("W250", "x")),
    "left out var": (("line", "Hi {var=name}.", "やあ。"), ("W251", "name")),
    "left out vars": (("line", "{username}: {var=a} {var=b}", "{var=b}"),
                      ("W251", ("username", "a"))),
    "extra beats left out": (("line", "Hi {var=name}.", "{var=score}"), ("W250", "score")),
    "duplicates count once": (("line", "{var=a}{var=a}", "{var=a}"), None),
    "titles don't check vars": (("word", "OK", "{var=x}"), None),
}


def test_ac_f43_08_extra_vars_refuse_and_left_out_vars_note():
    for name, ((kind, original, translation), want) in _VARS.items():
        result = check_entry(kind, original, translation, line=120)
        if want is None:
            assert result == EntryCheck(True), (name, result)
            continue
        code, names = want
        assert result == EntryCheck(code == "W251", (PoProblem(code, (names,), 120),)), \
            (name, result)
        shown = names if isinstance(names, tuple) else (names,)
        text = result.problems[0].warning(REF).format()
        assert text.startswith(f"{REF}, line 120: the translation "), name
        assert all(f"{{{n}}}" in text for n in shown), name
    problem = check_entry("line", "Hi.", "やあ{var=score}", line=120).problems[0]
    assert problem.warning(REF).format() == (
        f"{REF}, line 120: the translation uses {{score}}, which the original doesn't, so the "
        "original text is shown.")


_RTL = {
    "مرحبا": True,                     # Arabic
    "שלום": True,                      # Hebrew
    "नमस्ते": True,                      # Devanagari (joined)
    "สวัสดี": True,                     # Thai
    "ﷲ": True,                         # Arabic presentation form
    "𞤀": True,                         # Adlam
    "日本語のテキスト": False,
    "Olá, café, ñ, Ελληνικά, Русский": False,
    "한국어 😀 \ufeff": False,
    "": False,
}


def test_ac_f43_23_rtl_letters_warn_once_per_file():
    for text, want in _RTL.items():
        assert has_rtl(text) is want, text
        assert has_rtl(f"abc {text} def") is want, text
    # Once per file, however many translations have such letters; none: no warning.
    problem = rtl_warning("ar.po", ["Hi", "مرحبا", "שלום", "مرحبا"])
    assert problem == PoProblem("W254", ("ar.po",), None)
    assert problem.warning("translations/ar.po").format() == (
        "translations/ar.po has right-to-left or joined letters, which the engine can't draw "
        "correctly yet.")
    assert rtl_warning("ja.po", ["日本語", "", "かな"]) is None
    assert rtl_warning("ja.po", iter(())) is None
    # W252's characters: tags aside, each distinct grapheme once, first three in text order.
    assert shown_text("{b}日本{/b}{{語}") == "日本{語}"
    count, first = missing_chars(["{b}日本{/b} 日", "語ab", "é\u0301x"], lambda g: g.isascii())
    assert (count, first) == (4, ("日", "本", "語"))

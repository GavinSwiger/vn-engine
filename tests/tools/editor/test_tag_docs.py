"""Studio's text tag help, pure half (F45 ``06-acceptance.md`` AC-F45-56..58; 2026-11-02,
user: keep Studio updated). The window rows are in ``test_studio_assist_window.py``, the
coloring rows (AC-F45-59) in ``test_syntax.py``."""

import re
from pathlib import Path

from engine.script.tag_docs import TAG_DOCS, TAG_DOCS_HEADING, tag_doc, tag_names
from engine.script.texttags import STYLE_TAGS, TAGS, parse
from engine.tools.editor.assist import (
    CLOSE_TAG_KIND, TAG_KIND, Candidate, accept, auto_open, candidates, completion_context,
    help_sections, tag_help)

LANGUAGE = Path(__file__).resolve().parents[3] / "docs" / "script-language.md"


def test_ac_f45_56_one_row_per_engine_tag():
    names = [row.name for row in TAG_DOCS]
    assert len(names) == len(set(names))
    assert set(names) == TAGS, "a text tag without a tag_docs row, or a row for no tag"
    assert re.search(rf"^### {TAG_DOCS_HEADING}$", LANGUAGE.read_text(encoding="utf-8"),
                     re.MULTILINE)
    for row in TAG_DOCS:
        assert row.syntax.startswith("{" + row.name) and row.summary, row.name
        assert "\n" not in row.summary and "\n" not in row.example, row.name
        assert row.closes is (row.name in STYLE_TAGS)
        assert tag_doc(row.name) is row
        problems: list = []
        text = re.fullmatch(r'\w+ "(.*)"', row.example).group(1)
        assert parse(text, lambda at: (1, at + 1), problems.append) is not None, row.name
        assert problems == [], row.name


def test_ac_f45_57_tag_completion():
    def offered(line: str) -> list[tuple[str, str]] | None:
        ctx = completion_context(line, len(line))
        return None if ctx is None else [(c.text, c.kind) for c in candidates(ctx, {})]

    every = sorted(tag_names())
    assert offered('    hana "Hi {') == [(n, TAG_KIND) for n in every]
    assert offered('    "Hi {') == [(n, TAG_KIND) for n in every]          # narration
    assert offered('    hana "Hi {co') == [("color", TAG_KIND)]
    assert offered('    hana "{b}Hi {/') == [("b", CLOSE_TAG_KIND)]
    assert offered('    hana "{b}{i}x{/i} {/') == [("b", CLOSE_TAG_KIND)]  # innermost open
    assert offered('    hana "{b}x{/b} {/') is None                      # nothing open
    assert offered('    hana "{pause} {/') is None                       # pause never closes
    for line in ('    hana "Hi {{', '    hana "{color=#', '    hana "{b}x', '    hana {',
                 '    hana "x" {'):
        assert completion_context(line, len(line)) is None, line
    for line in ('    play music "a{', "    jump {"):                      # not text
        assert completion_context(line, len(line)).kinds != (TAG_KIND,), line

    line = '    hana "Hi {sp'
    ctx = completion_context(line, len(line))
    assert accept(line + '"', ctx, Candidate("speed", TAG_KIND)) == ('    hana "Hi {speed"', 19)
    assert auto_open('    hana "Hi {', 14) and auto_open('    hana "{b}x{/', 16)
    assert not auto_open('    hana "Hi {{', 15) and not auto_open('    jump {', 10)


def test_ac_f45_58_tag_help():
    line = '    hana "The {color=#9a1c14}lantern{/color} {pause} moved."'
    open_at, close_at, pause_at = line.index("{c"), line.index("{/"), line.index("{p")
    color, pause = tag_doc("color"), tag_doc("pause")
    for column, expected in ((open_at, None), (open_at + 1, color), (open_at + 3, color),
                             (line.index("}l"), color), (line.index("}l") + 1, None),
                             (close_at + 2, color), (pause_at + 6, pause),
                             (pause_at + 7, None), (len(line), None)):
        assert tag_help(line, column) is expected, column
    assert tag_help('    hana "{zzz} x"', 11) is None                     # no such tag
    assert tag_help('    hana "{{b} x"', 12) is None                      # a literal brace
    assert tag_help("    jump {b}", 10) is None                           # not text
    assert tag_help('    hana "Hi {speed=', 19) is tag_doc("speed")      # still typing
    assert help_sections(color) == (
        ("title", "Text tag {color}"), ("syntax", color.syntax), ("summary", color.summary),
        ("example", color.example), ("docs", f"Docs: {TAG_DOCS_HEADING}"))

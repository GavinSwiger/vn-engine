"""AC-F02-73: the language reference's Python warning and reserved-word table."""

import re
from pathlib import Path

from engine.script.words import STATEMENT_WORDS

DOC = Path(__file__).resolve().parents[2] / "docs" / "script-language.md"
# Reserved words whose table row a later docs step writes (word → that step; it removes the
# word). F32's ``ui`` was reserved in F32 s2 while docs/ was another builder's.
ROWS_PENDING = {"ui": "F32 s6"}


def _section(text: str, title: str) -> str:
    """The ``## <n>. <title>`` section (section numbers change as the reference grows)."""
    heading = re.search(rf"^## \d+\. {re.escape(title)}\s*$", text, re.M)
    assert heading is not None, title
    following = re.search(r"^## ", text[heading.end():], re.M)
    end = heading.end() + following.start() if following else len(text)
    return text[heading.start():end]


def test_python_warning_block():
    text = DOC.read_text(encoding="utf-8")
    warning = next(block for block in re.findall(r"(?:^>.*\n)+", text, re.M)
                   if "Warning" in block and "real Python" in block)
    flat = " ".join(line.lstrip("> ").strip() for line in warning.splitlines())
    assert "`$` lines" in flat and "conditions" in flat and "`define` values" in flat
    assert "run real Python" in flat
    assert "every launch, before the title screen" in flat


def test_reserved_words_table_equals_statement_words():
    section = _section(DOC.read_text(encoding="utf-8"), "Reserved words")
    table = "\n".join(line for line in section.splitlines() if line.startswith("|"))
    first_column = [row.split("|")[1] for row in table.splitlines()[2:]]
    words = set(re.findall(r"`([a-z]+)`", "\n".join(first_column)))
    assert words == STATEMENT_WORDS - set(ROWS_PENDING)


# --- AC-F03-81 — the language reference covers F03 -----------------------------------------------

F03_SECTIONS = ("Story variables", "Characters", "Random numbers", "Python modules",
                "Run-time errors")
# AC-F03-45's codes, and E45, E45b, E85e, E85m.
RUN_CODES = ("E85d", "E85g", "E85", "E85c", "E85i", "E45", "E45b", "E85e", "E85m")


def test_ac_f03_81_f03_sections_are_built():
    text = DOC.read_text(encoding="utf-8")
    assert "(proposed, F03)" not in text
    for title in F03_SECTIONS:
        section = _section(text, title)
        heading = section.splitlines()
        # No marker on the section itself (F05's rows inside keep theirs until F05).
        assert not heading[1].startswith("**(proposed"), title


def test_ac_f03_81_default_is_recommended_for_every_changed_variable():
    statements = _section(DOC.read_text(encoding="utf-8"), "Statements")
    default = statements[statements.index("### default"):statements.index("### $")]
    assert "Use a `default` for every variable your story changes." in default


def test_ac_f03_81_random_numbers_say_what_does_not_replay():
    section = _section(DOC.read_text(encoding="utf-8"), "Random numbers")
    flat = " ".join(line.lstrip("> ").strip() for line in section.splitlines())
    assert "`random`" in flat and "`time`" in flat and "don't replay" in flat
    warning = " ".join(line.lstrip("> ").strip() for line in section.splitlines()
                       if line.startswith(">"))
    assert "Warning" in warning and "real Python" in warning
    assert "`$` lines" in warning and "conditions" in warning and "`define` values" in warning


def test_ac_f03_81_namespace_and_shared_lists():
    section = _section(DOC.read_text(encoding="utf-8"), "Story variables")
    names = section[section.index("**What Python can see:**"):]
    names = names[:names.index("\n\n")]
    for name in ("story variables", "defined names", "`Character`", "`dice`", "`module`",
                 "`persistent`", "built-ins"):
        assert name in names, name
    flat = " ".join(section.split())
    assert "share one list" in flat and "separate, equal lists" in flat
    assert "A defined list changed by a `$` line isn't saved" in flat


def test_ac_f03_81_run_time_errors_list_every_code():
    section = _section(DOC.read_text(encoding="utf-8"), "Run-time errors")
    codes = {row.split("|")[1].strip() for row in section.splitlines()
             if row.startswith("| E")}
    assert set(RUN_CODES) <= codes, set(RUN_CODES) - codes

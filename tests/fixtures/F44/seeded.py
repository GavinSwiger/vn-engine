"""The ``seeded/`` games of F44 ``06-acceptance.md`` §4: ten copies of game R, each with one
load mistake that names a file and a line (AC-F44-29's "10 of 10").

Built in code from R (``tests/tools/editor/conftest.py`` ``R_SCRIPTS``), like
``byte_variants.py``, so a checkout's newline conversion can't change them. ``SEEDED`` maps
each mistake's name to ``(ref, line, new_text, expected)``: line ``line`` of ``script/<ref>``
becomes ``new_text``, and ``expected`` is ``(file, line)`` of the error F02 reports for it.
``seeded_scripts(name)`` gives R's files with that one change. Standard library only.
"""

from tests.tools.editor.conftest import R_SCRIPTS

# name: (file under script/, line, the new line, (reported file, reported line))
SEEDED: dict[str, tuple[str, int, str, tuple[str, int]]] = {
    "missing_quote": ("chapter2.vns", 11, '        sayori "It\'s {b}nice{/b}.',
                      ("script/chapter2.vns", 11)),
    "misspelled_statement": ("main.vns", 7, "    jmup club_poem", ("script/main.vns", 7)),
    "unknown_label": ("main.vns", 7, "    jump club_poen", ("script/main.vns", 7)),
    "duplicate_label": ("routes/hana.vns", 1, "label club_poem:",
                        ("script/routes/hana.vns", 1)),
    "bad_escape": ("chapter2.vns", 12, '    "Done.\\q"', ("script/chapter2.vns", 12)),
    "invisible_character": ("main.vns", 6, '    ​"Opening line."', ("script/main.vns", 6)),
    "if_without_colon": ("chapter2.vns", 8, "    if sayo_points >= 1",
                         ("script/chapter2.vns", 8)),
    "mixed_indent": ("chapter2.vns", 12, '\t"Done."', ("script/chapter2.vns", 12)),
    "missing_include": ("main.vns", 2, 'include "missing.vns"', ("script/main.vns", 2)),
    "mistake_in_a_route": ("routes/hana.vns", 2, "    jmup x", ("script/routes/hana.vns", 2)),
}


def seeded_scripts(name: str) -> dict[str, str]:
    """R's script files with mistake ``name`` in place."""
    ref, line, new_text, _ = SEEDED[name]
    scripts = dict(R_SCRIPTS)
    lines = scripts[ref].split("\n")
    lines[line - 1] = new_text
    scripts[ref] = "\n".join(lines)
    return scripts

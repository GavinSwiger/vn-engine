"""F47 W9, pure half: the Meta file (``file``, F31) and Game UI (``ui``, F32) forms read and
write every shape of their docs, and every ``file``/``ui`` line in the example game and the
docs becomes a form row that writes itself back (the round-trip rows); the Styles &
playthrough looks model (``settingsmodel``) lists, builds and creates look tables. No Tk;
the Tk halves are ``test_studio_files_ui.py``."""

import re
from pathlib import Path

import pytest

import engine.script  # noqa: F401  registers every statement
from engine.script.statement_docs import all_docs
from engine.tools.editor import forms, forms_files_ui as W9, settingsmodel as sm, tomlpatch
from engine.tools.editor.forms import form_by_key, form_for_doc
from tests.tools.editor.test_forms_more import _check, _rows, _scripts

ROOT = Path(__file__).resolve().parents[3]
_LINE = re.compile(r'^\s+((?:file (?:write|delete|exists|read) "|ui (?:style|saving|loading|'
                   r"delete) ).*?)\s*$")
FILE_BLANK = {"action": "", "name": "", "text": "", "into": ""}
UI_BLANK = {"action": "", "style": "", "reason": ""}


def _found_lines() -> list[str]:
    """Every ``file``/``ui`` line of the example game's scripts and of docs/*.md, and the
    statement docs' examples."""
    out: list[str] = []
    sources = [*sorted((ROOT / "game").rglob("*.vns")), *sorted((ROOT / "docs").glob("*.md"))]
    for path in sources:
        for text in path.read_text(encoding="utf-8").splitlines():
            match = _LINE.match(text)
            if match and not match.group(1).startswith(("file:", "ui:")):
                out.append(match.group(1).split("  #")[0])
    for doc in all_docs():
        if doc.key in ("file", "ui"):
            out += [line for line in doc.example.splitlines()
                    if line.startswith(("file ", "ui "))]
    return list(dict.fromkeys(out))


def test_w9_every_file_and_ui_line_in_the_game_and_docs_round_trips():
    lines = _found_lines()
    assert any(line.startswith("file write") for line in lines)        # the bonus scene
    assert {"ui style ashes", "ui delete saves"} <= set(lines)          # the docs' examples
    read, got = _rows(*lines)
    for line, row in zip(lines, got):
        assert row.form in (W9.FILE_FORM, W9.UI_FORM), line
        assert form_by_key(row.form).write(row.values) == line, line


def test_w9_meta_file_rows():
    _check([
        ("file", 'file write "hana.chr"',
         {"action": "write", "name": "hana.chr"},
         "Write meta file  hana.chr · a copy of files/hana.chr"),
        ("file", 'file write "read_me.txt" "Hi {name}.\\nBye \\"x\\""',
         {"action": "write", "name": "read_me.txt", "text": 'Hi {name}.\nBye "x"'},
         'Write meta file  read_me.txt · Hi {name}. Bye "x"'),
        ("file", 'file delete "hana.chr"', {"action": "delete", "name": "hana.chr"},
         "Delete meta file  hana.chr"),
        ("file", 'file exists "hana.chr" into hana_here',
         {"action": "check exists", "name": "hana.chr", "into": "hana_here"},
         "Check meta file  hana.chr → hana_here"),
        ("file", 'file read "answer.txt" into answer',
         {"action": "read", "name": "answer.txt", "into": "answer"},
         "Read meta file  answer.txt → answer"),
    ], FILE_BLANK)
    _scripts('file write "a.txt" ""')                  # empty text: the form copies
    form = form_by_key("file")
    assert W9.file_problem({"action": "write", "name": "Hana.chr"}) == W9.NAME_RULE
    assert W9.file_problem({"action": "read", "name": "hana.chr"}) == W9.READ_TXT_ONLY
    assert W9.file_problem({"action": "read", "name": "a.txt"}) is None
    with pytest.raises(ValueError):
        form.write({**FILE_BLANK, "action": "check exists", "name": "a.txt"})   # no into
    for doc in all_docs():
        if doc.key == "file":
            assert form_for_doc(doc) is form
    assert W9.new_values("file", 'file read "<name>" into <variable>') == {"action": "read"}


def test_w9_game_ui_rows_and_looks_model():
    _check([
        ("ui", "ui style ashes", {"action": "style", "style": "ashes"}, "UI style  ashes"),
        ("ui", "ui style off", {"action": "style", "style": "off"},
         "UI style  off: the normal look"),
        ("ui", 'ui saving off "Nothing {{left} to \\"keep\\"."',
         {"action": "saving off", "reason": 'Nothing {left} to "keep".'},
         'Stop saving  Nothing {left} to "keep".'),
        ("ui", "ui saving off", {"action": "saving off"}, "Stop saving  the game's own words"),
        ("ui", "ui saving on", {"action": "saving on"}, "Allow saving"),
        ("ui", 'ui loading off "Not now."', {"action": "loading off", "reason": "Not now."},
         "Stop loading  Not now."),
        ("ui", "ui loading on", {"action": "loading on"}, "Allow loading"),
        ("ui", "ui delete saves", {"action": "delete all saves"}, "Delete all saves"),
    ], UI_BLANK)
    assert W9.ui_problem({"action": "saving off", "reason": "x" * 201}) == W9.REASON_LONG
    assert W9.new_values("ui", 'ui loading off ["<reason>"]|on') == {"action": "loading off"}
    assert not {"file", "ui"} & set(forms.TEXT_ONLY)

    # The Looks page's model: tables in the file, one look's fields, a new look's key.
    text = ('[game]\ntitle = "x"\n\n[style.ashes.theme.textbox]\nfill_color = "#1E1A1C"\n'
            '[style.Bad]\n[playthrough.10.words]\nnew_game = "Again?"\n'
            '[playthrough.2.theme.title]\nfill_top_color = "#000000"\n')
    assert sm.looks(text) == (("style", "ashes"), ("playthrough", "2"), ("playthrough", "10"))
    assert sm.style_names(text) == ("ashes",)
    page = sm.look_page("style", "ashes")
    paths = {f.path for f in page.fields}
    assert {"style.ashes.theme.textbox.fill_color", "style.ashes.theme.choice.text_color",
            "style.ashes.theme.nvl.fill_color", "style.ashes.theme.quick_menu.fill_color",
            "style.ashes.words.saving_off"} <= paths
    assert not any(".theme.title" in p for p in paths)                 # not a style area
    assert {f.default_text for f in page.fields} == {sm.LOOK_UNSET}
    found = sm.values(text)
    fill = next(f for f in page.fields if f.path == "style.ashes.theme.textbox.fill_color")
    assert fill.current(found) == "#1E1A1C" and sm.is_look(fill)
    title = {f.path for f in sm.look_page("playthrough", "2").fields}
    assert {"playthrough.2.title_entries", "playthrough.2.theme.title.fill_top_color",
            "playthrough.2.words.new_game"} <= title
    assert sm.new_look_problem("style", "ashes", text) == sm.LOOK_TAKEN.format(
        what="a style", name="ashes")
    for bad in ("Ashes", "off", "2x", "label"):
        assert sm.new_look_problem("style", bad, text) == sm.STYLE_NAME_RULE, bad
    assert sm.new_look_problem("playthrough", "100", text) == sm.PLAYTHROUGH_RULE
    assert sm.new_look_problem("style", "river", text) is None
    section, key, value = sm.new_look_change("style", "river", found)
    plan = tomlpatch.plan_set(text, section, key, value)
    assert isinstance(plan, tomlpatch.TomlPlan) and plan.edits[0].lines[-3:] == (
        "[style.river.theme.textbox]", 'fill_color = "#FFF4F8"', "")     # the end kept
    assert sm.text_only("playthrough.<N>.title_entries") is None
    assert sm.on_looks_page("playthrough.<N>.title_entries")

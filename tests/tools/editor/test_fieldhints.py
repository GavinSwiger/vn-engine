"""Every Studio field explains itself (F47 ``01-design.md`` P3 "help on every field";
``04-technical.md`` P3-D: AC-F47-54). Pure: no Tk window (the Database modules are read as
source, not run)."""

import ast
import dataclasses
from pathlib import Path

import engine.script  # noqa: F401  registers every statement
from engine.tools.editor import dbmodel, fieldhints, forms, settingsmodel, settingsview

EDITOR = Path(__file__).resolve().parents[3] / "engine" / "tools" / "editor"


def _plain(text: str) -> bool:
    """A sentence for a person: words, a full stop, no code quoting."""
    return bool(text.strip()) and text.rstrip().endswith((".", "?")) and "`" not in text


def _database_rows(name: str) -> list[tuple[str, str, list[str]]]:
    """(function, the tips' form, its ``grid.row`` labels) for each ``FormGrid`` in module
    ``name``; a grid with no ``tips`` gives the form ""."""
    tree = ast.parse((EDITOR / name).read_text(encoding="utf-8"))
    consts = {target.id: node.value.value for node in tree.body
              if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
              and isinstance(node.value.value, str)
              for target in node.targets if isinstance(target, ast.Name)}
    found = []
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef):
            continue
        grids = [call for call in ast.walk(func) if isinstance(call, ast.Call)
                 and isinstance(call.func, ast.Name) and call.func.id == "FormGrid"]
        if not grids:
            continue
        assert len(grids) == 1, func.name
        form = ""
        for keyword in grids[0].keywords:
            if keyword.arg == "tips":
                arg = keyword.value.args[0]
                owner = {"db": dbmodel, "fieldhints": fieldhints}[arg.value.id]
                form = getattr(owner, arg.attr)
        labels = []
        for call in ast.walk(func):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                    and call.func.attr == "row" and isinstance(call.func.value, ast.Name) \
                    and call.func.value.id == "grid":
                first = call.args[0]
                labels.append(first.value if isinstance(first, ast.Constant)
                              else consts[first.id])
        found.append((func.name, form, labels))
    return found


def test_ac_f47_54_every_field_has_a_plain_hint():
    """AC-F47-54: every field of every command form (``forms.all_forms()``, the Choice
    form's own fields too), every Database form row and every Game settings field has a
    plain-language hint; the form and Database ones are their labels' tooltips."""
    # Command forms.
    seen = 0
    for form in forms.all_forms():
        for field in form.fields:
            hint = fieldhints.form_hint(form.key, field.key)
            assert _plain(hint) and hint != field.label, (form.key, field.key, hint)
            seen += 1
    assert seen > 80
    assert fieldhints.form_hint("rollback", "what") != fieldhints.COMMON.get("what")
    assert fieldhints.form_hint("no such form", "no such field") == ""
    choice = {f.name for f in dataclasses.fields(forms.ChoiceValues)} \
        | {f.name for f in dataclasses.fields(forms.ChoiceItem)}
    assert set(fieldhints.CHOICE_HINTS) == choice - {"choices", "in_text", "old", "had_check"}
    assert all(_plain(hint) for hint in fieldhints.CHOICE_HINTS.values())
    assert fieldhints.CHOICE_FORM == forms.CHOICE_FORM
    assert fieldhints.form_hint(forms.CHOICE_FORM, "goes") == fieldhints.CHOICE_HINTS["goes"]
    # The Database: every FormGrid passes its form's tips, and each row's label has one.
    grids = _database_rows("database.py") + _database_rows("dbmore.py")
    assert len(grids) >= 10
    forms_seen = set()
    for name, form, labels in grids:
        assert form, f"{name}: FormGrid has no tips"
        tips = fieldhints.database_tips(form)
        forms_seen.add(form)
        for label in labels:
            assert _plain(tips.get(label, "")), (name, label)
    assert forms_seen == set(fieldhints.DATABASE)
    assert {*dbmodel.CATEGORIES, *dbmodel.P2_CATEGORIES} - {dbmodel.CATEGORY_CHAPTER} \
        <= forms_seen
    assert fieldhints.database_tips(dbmodel.CATEGORY_CHAPTER) \
        is fieldhints.database_tips(dbmodel.CATEGORY_ENDING)
    # Game settings: each key's doc, shown under its field.
    fields = list(settingsmodel.fields_by_path().values())
    assert len(fields) > 300
    for page in settingsmodel.pages():
        fields += page.fields
    for field in fields:
        assert field.help.strip(), field.path
        assert _plain(settingsview.field_hint(field)), field.path

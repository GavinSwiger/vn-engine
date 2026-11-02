"""F32 step 2: the ``ui`` Insert and Help rows (``06-acceptance.md`` AC-F32-07; 06 §4 names
``tests/studio/``, which doesn't exist: Studio's tests live here).

``ui`` registers at import from F32 s3; until then its docs come with ``ui.register_words()``
inside ``scoped_registry()`` (F19 07 I-5), so the rows are checked here rather than by
AC-F45-03's sweep over the registered docs."""

import engine.script  # noqa: F401  registers every statement and the docs table
from engine.script import ui
from engine.script.statement_docs import docs_for
from engine.script.statements import scoped_registry
from engine.tools.editor.assist import completion_context, help_for, insert_menu
from tests.tools.test_statement_examples import problems_of


def test_ac_f32_07_insert_and_help_rows(tmp_path):
    with scoped_registry():
        ui.register_words()
        docs = docs_for("ui")
        assert [d.syntax.split(" <")[0].split(" [")[0] for d in docs] == [
            "ui style", "ui saving off", "ui loading off", "ui delete saves"]
        assert ui.HEADING == "Dynamic UI" and all(d.docs is None for d in docs)   # s6 sets it
        menu = dict(insert_menu())
        for n, doc in enumerate(docs):
            assert doc.syntax and doc.example and doc.feature == "F32"
            assert problems_of(tmp_path / f"game{n}", doc) == [], doc.syntax    # E320 checked
            assert doc in menu[doc.group]
            assert help_for("    " + doc.example.split("\n")[-1]) is doc
        # 07 I-10: F45's slot rule offers the ui words, then style names after "ui style".
        assert completion_context("    ui ", 7).kinds == ("ui",)
        assert completion_context("    ui style a", 14).kinds == ("style",)

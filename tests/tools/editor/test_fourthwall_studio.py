"""F30 step 6 in Studio (``06`` AC-F30-39; F45 AC-F45-73): the two ``effect`` help rows
(``effect window_title`` and ``effect crash``) link to "Fourth-wall tricks" and name the
``glitch`` kind, the ``{username}`` tag row links there too, and typing ``effect `` offers
``window_title`` and ``crash`` with F28's kinds. The examples' load-and-launch run is
AC-F45-03's (``tests/tools/test_statement_examples.py``), the tag example's parse AC-F45-56's
(``test_tag_docs.py``)."""

from pathlib import Path

import engine.script  # noqa: F401  registers every statement and the docs table
from engine.script.fourthwall import DOCS, HEADING
from engine.script.statement_docs import docs_for
from engine.script.tag_docs import tag_doc
from engine.tools.check import NAME_SOURCES
from engine.tools.editor.assist import candidates, completion_context
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)

LANGUAGE = Path(__file__).resolve().parents[3] / "docs" / "script-language.md"


def _complete(line: str, names: dict) -> list[str]:
    ctx = completion_context(line, len(line))
    return [] if ctx is None else [c.text for c in candidates(ctx, names)]


def test_ac_f30_39_studio_help_rows_and_kind_completion():
    text = LANGUAGE.read_text(encoding="utf-8")
    assert f"### {HEADING}" in text and f"## 25. {HEADING}" in text
    rows = [d for d in docs_for("effect") if d.feature == "F30"]
    assert rows == list(DOCS)
    assert [d.syntax.split()[:2] for d in rows] == [["effect", "window_title"],
                                                     ["effect", "crash"]]
    assert {(d.docs, d.names, d.group) for d in rows} == {(HEADING, ("glitch",), "Effects")}
    assert tag_doc("username").docs == HEADING

    kinds = {"glitch": list(NAME_SOURCES["glitch"](None))}
    offered = _complete("    effect ", kinds)
    assert {"window_title", "crash", "tear", "colorshift", "static", "jitter",
            "off"} == set(offered)
    assert _complete("    effect wi", kinds) == ["window_title"]
    assert _complete("    effect cr", kinds) == ["crash"]

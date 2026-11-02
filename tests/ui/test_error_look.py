"""F30 step 1 — AC-F30-05: the real error screen is unchanged by the ``error_look`` lift
(``04`` §6.5, UI-F30-01). Probe R (``tests/fixtures/F30/error_probes.json``) was recorded by
``gen_error_probes.py`` from the pre-F30 ``ErrorScreen`` at 1280x720 and 640x360, for a short
message, AC-F01-79's 5,000-character message, and a 500-character title. F01's own
error-screen tests (AC-F01-76 to 83, 153) run unchanged in ``test_error_screen.py`` and
``tests/app/test_error_mode.py``."""

import ast
import contextlib
import json
import sys
from pathlib import Path

import pytest

from engine.render.canvas import Canvas
from engine.ui.builtin import error_look
from tests.fixtures.F30.gen_error_probes import PROBES, call_record, record

pytestmark = pytest.mark.display

ENGINE = Path(__file__).resolve().parents[2] / "engine"


def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_ac_f30_05_error_screen_unchanged_by_the_lift(monkeypatch):
    stored = json.loads(PROBES.read_text(encoding="utf-8"))
    if sys.platform not in stored:
        pytest.skip(f"no Probe R recorded for {sys.platform} (run gen_error_probes on it)")
    expected = stored[sys.platform]

    @contextlib.contextmanager
    def recorder(calls):
        real = Canvas.draw_text

        def draw_text(self, text, font, color, pos, **options):
            calls.append(call_record(text, font, color, pos, options))
            return real(self, text, font, color, pos, **options)

        with monkeypatch.context() as patch:
            patch.setattr(Canvas, "draw_text", draw_text)
            yield

    now = json.loads(json.dumps(record(recorder), ensure_ascii=False))
    assert sorted(now) == sorted(expected)
    for case, want in expected.items():
        assert now[case]["calls"] == want["calls"], case        # string, font, pos, color
        assert len(want["probes"]) == 32
        for got, probe in zip(now[case]["probes"], want["probes"], strict=True):
            assert (got["x"], got["y"]) == (probe["x"], probe["y"]), case
            assert all(abs(a - b) <= 2 for a, b in zip(got["rgb"], probe["rgb"])), \
                (case, probe, got)

    # The shared look: the details line, and no route to the real screen or the clipboard.
    assert error_look.title_line("T", "1.0") == '"T" version 1.0'
    look = _imports(ENGINE / "ui" / "builtin" / "error_look.py")
    assert not [n for n in look if n.startswith("engine.ui.builtin.error")
                and not n.startswith("engine.ui.builtin.error_look")]
    assert "scrap" not in (ENGINE / "ui" / "builtin" / "error_look.py").read_text("utf-8")
    fake_crash = ENGINE / "ui" / "builtin" / "fake_crash.py"     # F30 step 4 (TR-F30-03)
    if fake_crash.exists():
        names = _imports(fake_crash)
        assert "engine.ui.builtin.error" not in names
        assert "engine.ui.builtin.error.ErrorScreen" not in names
        assert "scrap" not in fake_crash.read_text(encoding="utf-8")

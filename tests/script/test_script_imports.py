"""TR-F02-01 for ``engine/script`` (checklist step 1): importing it loads no pygame.

The static rules (imports only ``engine.core``, no pygame import, no file API) are AC-F02-66's
AST scan in ``tests/app/test_story_load_screen.py`` and the ADR-0002 table in
``tests/test_import_rules.py``; this file's copies of them were merged there
(test-review-F02.md). This one checks a real import.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_importing_engine_script_does_not_load_pygame():
    code = ("import sys, engine.script, engine.script.parser, engine.script.pycheck; "
            "assert 'pygame' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)

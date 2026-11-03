"""F42 P3: the plugin import scan (AC-F42-10; ``07`` I-4)."""

from engine.tools.build.plugins import PluginImport, scan_imports


def test_ac_f42_10_import_scan_collects_stdlib_and_stops_on_a_foreign_import(tmp_path):
    game = tmp_path / "game"
    plugins = game / "minigames"
    (plugins / "cards").mkdir(parents=True)
    sentinel = tmp_path / "ran.txt"
    (plugins / "dice.py").write_text(
        "import json, xml.etree.ElementTree\n"
        "from email import mime\n"
        "from os import path\n"
        "import engine.minigames.api\n"
        "from . import helper\n"
        "import cards\n"
        "from _vn_minigames.cards import deal\n"
        f"open({str(sentinel)!r}, 'w').write('ran')\n"
        "raise SystemExit(3)\n", encoding="utf-8")
    (plugins / "cards" / "__init__.py").write_text("from .rules import deal\nimport random\n",
                                                   encoding="utf-8")
    (plugins / ".hidden.py").write_text("import numpy\n", encoding="utf-8")
    (plugins / "__pycache__").mkdir()
    (plugins / "__pycache__" / "old.py").write_text("import numpy\n", encoding="utf-8")
    (plugins / "broken.py").write_text("def (:\n", encoding="utf-8")

    scan = scan_imports(game)
    assert scan.foreign is None
    assert {"json", "xml", "xml.etree", "xml.etree.ElementTree", "email", "email.mime", "os",
            "random"} <= set(scan.modules)
    assert not {"os.path", "engine", "cards", "_vn_minigames"} & set(scan.modules)
    assert scan.skipped == ("broken.py",)          # the check step reports it
    assert not sentinel.exists()                   # no plugin code ran

    (plugins / "cards" / "deal.py").write_text(
        "import random\n\ntry:\n    import numpy as np\nexcept ImportError:\n    np = None\n",
        encoding="utf-8")
    assert scan_imports(game).foreign == PluginImport("cards/deal.py", "numpy", 4)

    (plugins / "cards" / "deal.py").write_text("import tkinter\n", encoding="utf-8")
    assert scan_imports(game).foreign == PluginImport("cards/deal.py", "tkinter", 1)
    assert scan_imports(tmp_path / "no-game").modules == ()

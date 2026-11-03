"""The script language and parser (F02): ``.vns`` files in, an immutable ``Program`` out.

Headless: nothing in this package imports pygame, and from ``engine.*`` it imports only
``engine.core`` (ADR-0002). Feature modules that register statements are imported here, one
explicit line each (no discovery).
"""

from engine.script import statements  # noqa: F401  F02: label, define, include, jump, …
from engine.script import default  # noqa: F401,E402  F03: default
from engine.script import stage  # noqa: F401,E402  F04: scene, show, hide, image
from engine.script import effects  # noqa: F401,E402  F09: shake, flash, pause
from engine.script import audio  # noqa: F401,E402  F08: play, queue, stop, voice
from engine.script import menu  # noqa: F401,E402  F07: menu
from engine.script import chapter  # noqa: F401,E402  F18: chapter
from engine.script import points  # noqa: F401,E402  F22: points
from engine.script import rollback  # noqa: F401,E402  F14: rollback
from engine.script import nvl  # noqa: F401,E402  F17: nvl
from engine.script import routes  # noqa: F401,E402  F19: ending, lock, unlock
from engine.script import codex  # noqa: F401,E402  F21: lock/unlock tip|item rows
from engine.script import gallery  # noqa: F401,E402  F34: lock/unlock gallery row
from engine.script import musicroom  # noqa: F401,E402  F35: lock track row
from engine.script import replay  # noqa: F401,E402  F36: lock/unlock replay row
from engine.script import minigame  # noqa: F401,E402  F23: minigame
from engine.script import flowchart  # noqa: F401,E402  F20: flowchart
from engine.script import glitch  # noqa: F401,E402  F28: effect (registered from F28 s3)
from engine.script import ui  # noqa: F401,E402  F32: ui (registered from F32 s3)
from engine.script import metafiles  # noqa: F401,E402  F31: file (registered from F31 s3)
from engine.script import docs_table  # noqa: F401,E402  F45: docs for the words above
from engine.script.diagnostics import ScriptErrorGroup  # noqa: E402
from engine.script.loader import LoadOptions, LoadResult, StoryLoader, load_story  # noqa: E402
from engine.script.report import report_load_result  # noqa: E402

__all__ = ["LoadOptions", "LoadResult", "ScriptErrorGroup", "StoryLoader", "load_story",
           "report_load_result"]

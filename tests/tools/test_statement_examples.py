"""Every ``StatementDoc.example`` loads and launches cleanly (F45 ``06-acceptance.md``
AC-F45-03, TR-F45-01).

Each example goes into a copy of ``tests/fixtures/docgame/``: top-level ones (a ``"top"``
statement, or a doc in the Declarations group, such as ``points``'s declare form) above the
first line of ``script/main.vns``, the rest right after ``label start:``. The story is loaded
with ``load_story`` and launched in process as ``app/loading.py`` builds the job (image scan,
stage check, audio file check), with 0 errors and 0 warnings expected. The load gets the doc
game's ``[style]`` names as the app passes them (F32 07 I-9), so ``ui style``'s E320 runs.
"""

import dataclasses
import shutil
from pathlib import Path

import pytest

import engine.script  # noqa: F401  registers every statement and the docs table
from engine.core.config import load_config
from engine.core.errors import AssetMissing, AssetRefError
from engine.core.paths import GamePaths
from engine.runtime.audio_check import AudioFiles
from engine.runtime.images import ImageSource
from engine.runtime.launch import run_launch
from engine.script import LoadOptions, load_story
from engine.script.statement_docs import StatementDoc, all_docs, docs_for
from engine.script.statements import get_spec

DOCGAME = Path(__file__).resolve().parents[1] / "fixtures" / "docgame"
START = "label start:\n"


def _cases() -> list:
    cases, seen = [], {}
    for doc in all_docs():
        n = seen[doc.key] = seen.get(doc.key, -1) + 1
        cases.append(pytest.param(doc, id=f"{doc.key}-{n}"))
    return cases


def _top_level(doc: StatementDoc) -> bool:
    spec = get_spec(doc.key)
    return (spec is not None and spec.placement == "top") or doc.group == "Declarations"


def _images(paths: GamePaths) -> ImageSource:
    def locate(ref: str) -> tuple[bool, str | None]:
        try:
            return paths.resolve(ref).is_file(), None
        except AssetMissing as e:
            return False, e.suggestion
        except (AssetRefError, OSError):
            return False, None

    return ImageSource(paths.list_dir, locate)


def problems_of(root: Path, doc: StatementDoc) -> list[str]:
    """Load and launch ``doc``'s example in a copy of the doc game at ``root``."""
    shutil.copytree(DOCGAME, root)
    main = root / "script" / "main.vns"
    text = main.read_bytes().decode("utf-8")
    assert START in text
    if _top_level(doc):
        text = doc.example + "\n" + text
    else:
        story = "".join(f"    {line}\n" for line in doc.example.split("\n"))
        text = text.replace(START, START + story, 1)
    main.write_bytes(text.encode("utf-8"))
    paths = GamePaths(root.resolve())
    config = load_config(paths)
    assert not config.errors, config.errors
    result = load_story(paths, LoadOptions(style_names=frozenset(config.config.style)))
    found = [e.format() for e in result.errors] + [w.format() for w in result.warnings]
    if result.program is None:
        return found or ["no program"]
    launch = run_launch(result.program, dev=True, images=_images(paths),
                        audio=AudioFiles(paths.list_dir, ()))
    return found + [e.format() for e in launch.errors] + [w.format() for w in launch.warnings]


@pytest.mark.parametrize("doc", _cases())
def test_ac_f45_03_every_example_loads_and_launches_cleanly(tmp_path, doc):
    assert not doc.fields or doc.fields[0] in doc.example
    assert problems_of(tmp_path / "game", doc) == []


def test_ac_f45_03_the_harness_sees_a_bad_example(tmp_path):
    """A guard on the harness itself: a missing image is a launch warning."""
    bad = dataclasses.replace(docs_for("show")[0], example="show hana grin", fields=())
    assert len(problems_of(tmp_path / "game", bad)) == 1

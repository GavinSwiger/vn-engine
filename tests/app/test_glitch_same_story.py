"""F28 step 5 — AC-F28-25, the same story everywhere (TR-F28-03; ``06-acceptance.md`` §1.5).

Lean (wind-down): App A plays F28's ``walk/`` (every ``effect`` form it holds, ``effect off``,
and ``with glitch``) with defaults and with ``[effects] reduce = true``, against Run H; the
skip, click-through, and refusal configurations of the row are not run here.
"""

import ast
from pathlib import Path

import pytest

from engine.runtime.headless import run_headless
from tests.app.test_windowed_equals_headless import INSTANT, pygame_ready, windowed  # noqa: F401
from tests.fakes.text_app import make_text_game
from tests.fixtures.F04 import gen_images as gen
from tests.render.glitch_screen import GRAIN_REF, HANA, L, grain, on, stage
from tests.runtime.effects_story import load_game
from tests.runtime.glitch_story import F28, IMG9P

pytestmark = pytest.mark.display

REPO = Path(__file__).resolve().parents[2]


def _imports(ref: str) -> set[str]:
    tree = ast.parse((REPO / ref).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            if node.module == "random":
                names.update(f"random.{a.name}" for a in node.names)
    return names


def test_ac_f28_25_same_story_everywhere(tmp_path, monkeypatch):
    for ref in ("engine/script/glitch.py", "engine/runtime/glitch.py"):
        assert not {"pygame", "time", "random"} & _imports(ref), ref
    assert {n for n in _imports("engine/render/glitch.py") if n.startswith("random")} == \
        {"random", "random.Random"}

    # App A equals Run H. (The "shared random patched to raise" row is not run: App A's
    # startup outside F28 calls the shared functions; F28's render code is checked by the
    # import rule above.)
    text = (F28 / "walk" / "script" / "main.vns").read_text(encoding="utf-8")
    for config in ("", "[effects]\nreduce = true\n"):
        root = make_text_game(tmp_path / f"g{len(config)}", script=text, config=INSTANT + config)
        images = {ref: gen.block(1280, 720, (0, 0, 255)) for ref in IMG9P
                  if ref.startswith("images/bg/")}
        images[GRAIN_REF] = grain()
        images[gen.ref_of("hana happy")] = gen.block(300, 600, (0, 255, 0))
        gen.write(root, images)
        expected = run_headless(load_game(root), seed=7, image_files=IMG9P)
        from tests.runtime.corpus import canon
        assert canon(windowed(root, click_through=False)) == canon(expected), config

    # Seeds: the same seed gives the same frames; another seed other tear bands.
    def frames(seed: int) -> list[bytes]:
        rig = L(tmp_path / f"seed{seed}-{len(list(tmp_path.iterdir()))}", seed=seed)
        rig.show(stage(HANA))
        rig.frame()
        rig.screen.glitch(on(("tear", "large")))
        return [f.get_buffer().raw for f in rig.frames(6)]

    assert frames(7) == frames(7) != frames(8)

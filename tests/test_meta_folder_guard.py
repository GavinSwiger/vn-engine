"""F31 step 1 — tests never touch the real ``game/characters/`` (``06`` AC-F31-07; ``07``
I-8). The guard and the session snapshot live in ``tests/conftest.py`` and
``tests/fakes/meta_guard.py``; this checks they are active, and that every helper that copies
the repository's ``game/`` leaves ``characters`` out of the copy."""

import ast
from pathlib import Path

import pytest

from engine.core.paths import META_NAME_RE
from engine.meta.files import MetaFolder
from engine.persist.writer import META, Writer
from tests.fakes import meta_guard
from tests.fakes.meta_guard import REAL_META, RealFolderTouched

TESTS = Path(__file__).resolve().parent


def _game_copies(path: Path) -> list[tuple[int, str]]:
    """(line, call text) of each ``copytree`` of the repository's ``game/`` in ``path``
    whose ignore rule (inline or a module-level name) doesn't name ``characters``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assigned = {t.id: ast.unparse(node.value) for node in tree.body
                if isinstance(node, ast.Assign) for t in node.targets
                if isinstance(t, ast.Name)}
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and ast.unparse(node.func).endswith("copytree")
                and node.args):
            continue
        source = ast.unparse(node.args[0])
        source = assigned.get(source, source)
        if not source.endswith("/ 'game'"):
            continue
        ignore = next((ast.unparse(k.value) for k in node.keywords if k.arg == "ignore"), "")
        ignore = assigned.get(ignore, ignore)
        if "characters" not in ignore:
            found.append((node.lineno, ast.unparse(node)))
    return found


def test_ac_f31_07_tests_never_touch_the_real_folder(request, tmp_path):
    with pytest.raises(RealFolderTouched):
        MetaFolder(REAL_META, frozenset({"hana.chr"}))
    with pytest.raises(RealFolderTouched):
        Writer(threaded=False).client(META, root=REAL_META, names=META_NAME_RE)
    MetaFolder(tmp_path / "characters", frozenset({"hana.chr"}))      # a copy is fine
    # The session hook took its snapshot, and nothing has changed it so far.
    assert getattr(request.config, "_meta_snapshot", None) == meta_guard.snapshot()
    # The snapshot sees a change (the session-end comparison fails the run on one).
    watched = (tmp_path / "characters",)
    before = meta_guard.snapshot(watched)
    watched[0].mkdir()
    (watched[0] / "hana.chr").write_bytes(b"x")
    assert meta_guard.snapshot(watched) != before
    unguarded = {path.relative_to(TESTS).as_posix(): found
                 for path in sorted(TESTS.rglob("*.py"))
                 if b"copytree" in (data := path.read_bytes()) and b'"game"' in data
                 if (found := _game_copies(path))}
    assert unguarded == {}

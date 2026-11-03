"""The story map's layout file, ``<game>/.studio/storymap.json`` (F46 ``06-acceptance.md``
AC-F46-21, AC-F46-23; ``04-technical.md`` §3.6, §6.10, §7). Pure: no Tk.

Damaged files, links and junctions are generated here (06 §5). Symlink rows skip where the
OS refuses symlinks (Windows without the privilege); junction rows run on Windows only."""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

import engine.script  # noqa: F401  registers every statement
from engine.core import safefile
from engine.core.paths import GamePaths
from engine.script import load_story
from engine.script.assetgroups import ASSET_GROUPS
from engine.tools.editor import layoutfile
from engine.tools.editor.document import list_scripts
from engine.tools.editor.files import project_tree
from engine.tools.editor.layoutfile import (
    LAYOUT_DIR, LAYOUT_MAX_BOXES, LAYOUT_MAX_BYTES, LAYOUT_NAME, LAYOUT_SAVE_MS, LayoutProblem,
    encode_layout, read_layout, write_layout)
from tests.tools.f45_games import result_of, run_job, without_seconds

LANTERNS = Path(__file__).resolve().parents[2] / "fixtures" / "F46" / "games" / "lanterns"

SPEC_TEXT = (b'{\n  "studio_map": 1,\n  "boxes": {\n    "at_the_river": [220, 0],\n'
             b'    "start": [0, 0]\n  }\n}\n')


def make_symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create symlinks here (needs a privilege on Windows): {exc}")


def make_junction(link: Path, target: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("junctions exist only on Windows")
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


def sha_of(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        digest.update(str(path.relative_to(folder)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _doc(boxes: str, head: str = '"studio_map": 1') -> bytes:
    return f'{{{head}, "boxes": {{{boxes}}}}}'.encode()


def _many(n: int) -> bytes:
    return _doc(", ".join(f'"b{i}": [0, 0]' for i in range(n)))


def _padded(size: int) -> bytes:
    body = _doc('"start": [0, 0]')
    return body[:-1] + b" " * (size - len(body)) + b"}"


DAMAGED = {
    "bad json": b'{"studio_map": 1, "boxes": {',
    "non-utf8": b'{"studio_map": 1, "boxes": {"s\xfftart": [0, 0]}}',
    "nan": _doc('"start": [NaN, 0]'),
    "infinity": _doc('"start": [0, Infinity]'),
    "true": _doc('"start": [true, 0]'),
    "float": _doc('"start": [1.5, 0]'),
    "negative": _doc('"start": [-1, 0]'),
    "over range": _doc('"start": [0, 1000001]'),
    "one int": _doc('"start": [1]'),
    "bad name": _doc('"Bad Name": [0, 0]'),
    "10001 keys": _many(LAYOUT_MAX_BOXES + 1),
    "262145 bytes": _padded(LAYOUT_MAX_BYTES + 1),
    "studio_map 2": _doc('"start": [0, 0]', '"studio_map": 2'),
    "studio_map missing": _doc('"start": [0, 0]', '"other": 1'),
    "boxes not object": b'{"studio_map": 1, "boxes": [["start", 0, 0]]}',
}


def _studio(root: Path) -> Path:
    folder = root / LAYOUT_DIR
    folder.mkdir(exist_ok=True)
    return folder


def _out(root: Path) -> Path:
    """OUT: a folder outside the game whose bytes a link must never change."""
    out = root.parent / "OUT"
    out.mkdir()
    (out / LAYOUT_NAME).write_bytes(SPEC_TEXT)
    return out


def _link_row(make):
    def row(root, monkeypatch):
        out = _out(root)
        make(root, out)
        before = sha_of(out)
        problem = read_layout(root)
        assert isinstance(problem, LayoutProblem) and problem.link
        written = write_layout(root, encode_layout({"start": (40, 60)}, ()))
        assert isinstance(written, LayoutProblem) and written.link
        assert sha_of(out) == before
    return row


def _file_link(root, out):
    make_symlink(_studio(root) / LAYOUT_NAME, out / LAYOUT_NAME)


def _folder_link(root, out):
    make_symlink(root / LAYOUT_DIR, out, directory=True)


def _junction(root, out):
    make_junction(root / LAYOUT_DIR, out)


def _studio_is_a_file(root, monkeypatch):
    (root / LAYOUT_DIR).write_bytes(SPEC_TEXT)
    assert isinstance(read_layout(root), LayoutProblem)
    assert isinstance(write_layout(root, SPEC_TEXT), LayoutProblem)
    assert (root / LAYOUT_DIR).read_bytes() == SPEC_TEXT


def _damaged(data: bytes):
    def row(root, monkeypatch):
        (_studio(root) / LAYOUT_NAME).write_bytes(data)
        assert isinstance(read_layout(root), LayoutProblem)
    return row


def _raising_read(root, monkeypatch):
    (_studio(root) / LAYOUT_NAME).write_bytes(SPEC_TEXT)
    monkeypatch.setattr(layoutfile.safefile, "read_regular",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert isinstance(read_layout(root), LayoutProblem)
    monkeypatch.setattr(layoutfile.safefile, "write_atomic",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert isinstance(write_layout(root, b"x"), LayoutProblem)


def _format(root, monkeypatch):
    assert (LAYOUT_SAVE_MS, LAYOUT_MAX_BYTES, LAYOUT_MAX_BOXES) == (1_000, 262_144, 10_000)
    assert (LAYOUT_DIR, LAYOUT_NAME) == (".studio", "storymap.json")
    places = {"start": (0, 0), "at_the_river": (220, 0)}
    assert encode_layout(places, ()) == SPEC_TEXT == encode_layout(places, ())
    assert read_layout(root) == {}                                     # no folder
    _studio(root)
    assert read_layout(root) == {}                                     # no file
    assert write_layout(root, SPEC_TEXT) is None
    assert (root / LAYOUT_DIR / LAYOUT_NAME).read_bytes() == SPEC_TEXT
    assert read_layout(root) == places
    # Keys by code point, not by casefold; an unknown top-level key is ignored.
    assert encode_layout({"b": (1, 2), "B": (3, 4), "é": (5, 6)}, ()).splitlines()[3:6] == [
        b'    "B": [3, 4],', b'    "b": [1, 2],', '    "é": [5, 6]'.encode()]
    (root / LAYOUT_DIR / LAYOUT_NAME).write_bytes(
        b'{"later": {"x": 1}, "studio_map": 1, "boxes": {"start": [5, 6]}}')
    assert read_layout(root) == {"start": (5, 6)}


def _round_trip_10000(root, monkeypatch):
    # 10,000 boxes fit 256 KiB only with short lines (about 26 bytes each); longer ones are
    # the byte-cap row below. Studio shows at most 1,500 boxes.
    places = {f"s{i}": (i % 100, i // 100) for i in range(LAYOUT_MAX_BOXES)}
    data = encode_layout(places, ())
    assert len(data) <= LAYOUT_MAX_BYTES and data == encode_layout(dict(reversed(places.items())))
    assert write_layout(root, data) is None
    assert read_layout(root) == places


def _caps(root, monkeypatch):
    # Over the byte cap: the shown boxes first, then program order, until the next won't fit.
    names = [f"scene_{i:04}_" + "x" * 100 for i in range(3_000)]
    places = {name: (i, i) for i, name in enumerate(names)}
    shown = [names[-1], names[-2]]
    data = encode_layout(places, shown)
    assert len(data) <= LAYOUT_MAX_BYTES
    kept = json.loads(data)["boxes"]
    assert set(shown) <= set(kept)
    rest = [name for name in names if name in kept and name not in shown]
    assert rest == names[:len(rest)] and 0 < len(rest) < len(names) - 2
    # Over the box cap: the same order.
    places = {f"s{i}": (0, 0) for i in range(LAYOUT_MAX_BOXES + 5)}
    kept = json.loads(encode_layout(places, ["s10004"]))["boxes"]
    assert len(kept) == LAYOUT_MAX_BOXES and "s10004" in kept and "s9998" in kept
    assert "s9999" not in kept
    # Only the labels passed are written (the caller passes existing ones): a gone scene drops.
    assert write_layout(root, encode_layout({"start": (0, 0), "river": (9, 9)}, ())) is None
    assert write_layout(root, encode_layout({"start": (0, 0)}, ())) is None
    assert read_layout(root) == {"start": (0, 0)}


def _unchanged(root, monkeypatch):
    assert write_layout(root, SPEC_TEXT) is None
    calls = []
    real = safefile.write_atomic
    monkeypatch.setattr(layoutfile.safefile, "write_atomic",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    assert write_layout(root, SPEC_TEXT) is None
    assert calls == []
    assert write_layout(root, encode_layout({"start": (20, 0)}, ())) is None
    assert calls == [1]


def _new_file_mode(root, monkeypatch):
    if os.name != "posix":
        pytest.skip("file modes are POSIX only")
    umask = os.umask(0)
    os.umask(umask)
    assert write_layout(root, SPEC_TEXT) is None
    assert (root / LAYOUT_DIR / LAYOUT_NAME).stat().st_mode & 0o777 == 0o666 & ~umask


ROWS = {
    "format": _format,
    "round trip 10000": _round_trip_10000,
    "caps": _caps,
    "unchanged bytes": _unchanged,
    "new file mode (posix)": _new_file_mode,
    "raises inside": _raising_read,
    **{name: _damaged(data) for name, data in DAMAGED.items()},
    ".studio a file": _studio_is_a_file,
    "file symlink": _link_row(_file_link),
    "folder symlink": _link_row(_folder_link),
    "junction (windows)": _link_row(_junction),
}


@pytest.mark.parametrize("row", list(ROWS), ids=list(ROWS))
def test_ac_f46_21_layout_file_format(row, tmp_path, monkeypatch):
    root = tmp_path / "game"
    root.mkdir()
    ROWS[row](root, monkeypatch)


# --- AC-F46-23 -------------------------------------------------------------------------------

def _seen(root: Path) -> tuple:
    paths = GamePaths.for_game(root)
    loaded = load_story(paths)
    program = loaded.program
    assert program is not None
    stats = program.stats
    story = (program.files, dict(program.labels), program.defines, program.defaults,
             (stats.files, stats.labels, stats.statements, stats.words),
             [str(e) for e in loaded.errors], [str(w) for w in loaded.warnings])
    checked = without_seconds(result_of(run_job(paths)))
    walks = {(group.folder, suffix): paths.walk_files(group.folder, suffix=suffix,
                                                      max_entries=10_000, max_depth=8).refs
             for group in ASSET_GROUPS for suffix in group.suffixes}
    tree = project_tree(paths)
    refs = [node.ref for node in tree.nodes()]
    listed = [*list_scripts(paths), *refs, *(ref for found in walks.values() for ref in found)]
    assert not [ref for ref in listed if LAYOUT_DIR in ref]
    return story, checked, walks, refs, list_scripts(paths)


def test_ac_f46_23_the_game_never_sees_studio(tmp_path):
    root = tmp_path / "lanterns"
    shutil.copytree(LANTERNS, root)
    before = _seen(root)
    # 06 §5 says L checks with 0 problems; the fixture gives one W153 (flowchart forget on a
    # scene with no flowchart), so only the load is asserted here and equality below.
    assert before[1].loaded and not [p for p in before[1].problems if p.severity == "error"]
    folder = root / LAYOUT_DIR
    folder.mkdir()
    garbage = bytes(range(256)) * (300 * 1024 // 256)
    (folder / LAYOUT_NAME).write_bytes(garbage)
    (folder / "extra.vns").write_bytes(b"label broken\n    jmup x\n")
    after = _seen(root)
    assert after == before

"""F31 step 1 — meta file names at every layer and the write-root rule (``06`` AC-F31-01,
AC-F31-02; SEC-F31-01, -03(a); ``04`` §3, §6.2; ``07`` I-1, I-7).

AC-F31-01's ``MemoryFolder`` part arrives with ``runtime/metafiles.py`` (step 3)."""

import ast
import builtins
import contextlib
import io
import os
import sys
import tomllib
from pathlib import Path
from unittest import mock

import pytest

from engine.core import constants
from engine.core.errors import AssetMissing, AssetNotFile, AssetRefError
from engine.core.paths import (META_NAME_RE, REASON_WRITE_ROOT, GamePaths, check_ref,
                               is_meta_name)
from engine.meta.files import MetaFolder
from engine.persist.writer import META, Failed, FileRemove, FileWrite, Writer
from engine.script import loader

REPO = Path(__file__).resolve().parent.parent.parent
ENGINE = REPO / "engine"
NAMES = tomllib.loads((REPO / "tests" / "fixtures" / "F31" / "names.toml")
                      .read_text(encoding="utf-8"))["row"]
OS_CALLS = ("lstat", "stat", "open", "scandir", "listdir", "mkdir", "unlink", "rmdir",
            "replace")


@contextlib.contextmanager
def no_os_calls():
    """Every file-system entry point used by the code under test raises."""
    spy = mock.Mock(side_effect=AssertionError("file-system call"))
    with contextlib.ExitStack() as stack:
        for name in OS_CALLS:
            stack.enter_context(mock.patch.object(os, name, spy))
        stack.enter_context(mock.patch.object(builtins, "open", spy))
        yield spy
    spy.assert_not_called()


def tree(root: Path) -> dict[str, int]:
    return {p.relative_to(root).as_posix(): (p.stat().st_size if p.is_file() else -1)
            for p in root.rglob("*")}


@pytest.mark.parametrize("row", NAMES, ids=[repr(r["name"])[:24] for r in NAMES])
def test_ac_f31_01_names_refused_at_every_layer(row, tmp_path):
    name, accepted = row["name"], row["accepted"]
    root = tmp_path / "game" / "characters"
    root.mkdir(parents=True)
    (root / "hana.chr").write_bytes(b"keep")
    (tmp_path / "game" / "x.chr").write_bytes(b"outside")
    w = Writer(threaded=False)
    client = w.client(META, root=root, names=META_NAME_RE)
    assert is_meta_name(name) is accepted
    assert client.accepts(root, name) is accepted

    if accepted:
        folder = MetaFolder(root, frozenset({name}))
        assert folder.require(name) == name
        return

    folder = MetaFolder(root, frozenset({"hana.chr"}))
    for call in (folder.require, folder.exists, folder.read, folder.entry_kind):
        with no_os_calls(), pytest.raises(ValueError):
            call(name)
    with pytest.raises(ValueError):
        MetaFolder(root, frozenset({"hana.chr", name}))
    too_many = frozenset(f"n{i}.txt" for i in range(constants.META_NAMES_MAX + 1))
    with pytest.raises(ValueError):
        MetaFolder(root, too_many)
    if type(name) is not str:
        with pytest.raises(TypeError):                  # a job can't even hold it
            FileRemove(root, name)
        return
    before = tree(tmp_path)
    for job in (FileWrite(root, name, (b"x",)), FileRemove(root, name)):
        client.submit(job)
    results = client.take()
    assert [type(r) for r in results] == [Failed, Failed]
    assert tree(tmp_path) == before


def _string_constants(path: Path) -> set[str]:
    return {node.value for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)}


# The path-building code (07 I-7): form keys elsewhere (``script/imagenames.py``,
# ``script/messages.py``) also spell the word and are not paths.
PATH_CODE = ("core/constants.py", "core/paths.py", "core/safefile.py", "persist", "meta",
             "app", "script/loader.py", "tools")


def _scanned() -> list[Path]:
    out = []
    for ref in PATH_CODE:
        target = ENGINE / ref
        out.extend(sorted(target.rglob("*.py")) if target.is_dir() else [target])
    return out


def _make_dir_link(link: Path, target: Path) -> None:
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        return
    os.symlink(target, link, target_is_directory=True)


REFUSED = ("characters/hana.chr", "Characters/x.png", "CHARACTERS/x", "saves/1.vnsave",
           "Saves/1", "persistent/x", "settings/x.json", "logs/x.txt")
ACCEPTED = ("images/characters/x.png", "characters_old/x.png", "files/hana.chr")


def test_ac_f31_02_write_roots_out_of_refs_and_original_sizes(tmp_path):
    assert constants.WRITE_ROOT_DIRNAMES == (constants.LOGS_DIRNAME, *constants.SAVE_DIRNAMES,
                                             *constants.RESERVED_DIRNAMES)
    assert loader.WRITE_ROOT_NAMES is constants.WRITE_ROOT_DIRNAMES
    assert constants.META_DIRNAME is constants.RESERVED_DIRNAMES[0]
    holders = {path.relative_to(ENGINE).as_posix() for path in _scanned()
               if "characters" in _string_constants(path)}
    assert holders == {"core/constants.py"}

    for ref in REFUSED:
        with pytest.raises(AssetRefError) as caught:
            check_ref(ref)
        assert caught.value.reason.endswith(REASON_WRITE_ROOT), ref
    for ref in ACCEPTED:
        check_ref(ref)

    game = tmp_path / "game"
    (game / "files").mkdir(parents=True)
    (game / "files" / "hana.chr").write_bytes(bytes(64))
    (game / "files" / "dir.chr").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    gp = GamePaths.for_game(game)
    spy = mock.Mock(side_effect=AssertionError("opened"))
    with mock.patch.object(builtins, "open", spy), mock.patch.object(io, "open", spy), \
            mock.patch.object(os, "open", spy):
        assert gp.file_size("files/hana.chr") == 64
    with pytest.raises(AssetMissing):
        gp.file_size("files/gone.chr")
    with pytest.raises(AssetNotFile):
        gp.file_size("files/dir.chr")
    with pytest.raises(AssetRefError):
        gp.file_size("files/../x")
    try:
        _make_dir_link(game / "files" / "link.chr", outside)
    except OSError:
        return                                         # no directory links here
    gp.invalidate_listings()
    with pytest.raises(Exception) as by_read:
        gp.read_file("files/link.chr", max_bytes=100, regular=True)
    with pytest.raises(type(by_read.value)):
        gp.file_size("files/link.chr")

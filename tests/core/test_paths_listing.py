"""Contained directory listing (F02 Step 2: ``GamePaths.list_dir`` / ``walk_files``,
AC-F02-67, TR-F02-02) and the cached resolved folders of F01 I-11 (AC-F01-140).

Directory links are junctions on Windows (no privilege needed), symlinks elsewhere; file
symlinks are skipped where the platform doesn't permit them.
"""

import builtins
import contextlib
import io
import os
from pathlib import Path
from unittest import mock

import pytest

from engine.core import paths
from engine.core.errors import AssetMissing, AssetRefError
from engine.core.paths import REASON_OUTSIDE, DirListing, GamePaths, WalkResult
from tests.core.test_paths import make_dir_link, make_file_symlink

WALK = {"suffix": ".vns", "max_entries": 10_000, "max_depth": 32}
ALL_VNS = ("script/B.vns", "script/a.vns", "script/sub/c.vns", "script/é.vns")


@pytest.fixture
def outside(tmp_path) -> Path:
    folder = tmp_path / "outside"
    folder.mkdir()
    (folder / "s.vns").write_text("secret", encoding="utf-8")
    (folder / "taxes_2025.vns").write_text("taxes", encoding="utf-8")
    return folder


@pytest.fixture
def story(tmp_path, outside) -> GamePaths:
    """The AC-F02-67 game folder. ``s.vns`` (a file link out) exists only where file
    symlinks are permitted; ``ext`` (folder link out) and ``loop`` (→ script) always."""
    script = tmp_path / "game" / "script"
    (script / "sub").mkdir(parents=True)
    for name in ("B.vns", "a.vns", "é.vns", "X.VNS", "sub/c.vns"):
        (script / name).write_text("label start:\n", encoding="utf-8")
    with contextlib.suppress(pytest.skip.Exception):
        make_file_symlink(script / "s.vns", outside / "s.vns")
    make_dir_link(script / "ext", outside)
    make_dir_link(script / "loop", script)
    return GamePaths.for_game(tmp_path / "game")


@contextlib.contextmanager
def scandir_spy():
    listed: list[Path] = []
    real_scandir = os.scandir

    def spy(path):
        listed.append(Path(path))
        return real_scandir(path)

    with mock.patch.object(os, "scandir", spy):
        yield listed


@contextlib.contextmanager
def no_open():
    spy = mock.Mock(side_effect=AssertionError("a file was opened"))
    with contextlib.ExitStack() as stack:
        for target in (builtins, io, os):
            stack.enter_context(mock.patch.object(target, "open", spy))
        stack.enter_context(mock.patch.object(paths, "_open_regular", spy))
        yield
    spy.assert_not_called()


def under(path: Path, folder: Path) -> bool:
    return path.resolve().is_relative_to(folder.resolve())


# --- list_dir (AC-F02-67) ---------------------------------------------------------------------

def test_list_dir_is_code_point_sorted_and_omits_outside_links(story, outside):
    with scandir_spy() as listed:
        listing = story.list_dir("script")
    assert listing == DirListing(files=("B.vns", "X.VNS", "a.vns", "é.vns"),
                                 dirs=("loop", "sub"))
    assert not any(under(p, outside) for p in listed)


def test_list_dir_of_a_file_or_a_missing_path_is_none(story):
    assert story.list_dir("script/a.vns") is None
    assert story.list_dir("script/nope") is None
    assert story.list_dir("nope/deeper") is None
    assert story.list_dir("Script") is None            # case mismatch counts as missing


@pytest.mark.parametrize("ref", ["../x", "script/../x", "/script", "script\\sub"])
def test_list_dir_of_a_bad_ref_raises(story, ref):
    with pytest.raises(AssetRefError) as raised:
        story.list_dir(ref)
    assert raised.value.reason == REASON_OUTSIDE


def test_list_dir_of_a_link_out_raises_without_listing_it(story, outside):
    with scandir_spy() as listed:
        with pytest.raises(AssetRefError) as raised:
            story.list_dir("script/ext")
    assert raised.value.reason == REASON_OUTSIDE
    assert "taxes" not in str(raised.value)
    assert not any(under(p, outside) for p in listed)


def test_list_dir_through_a_link_inside_the_root(story):
    assert story.list_dir("script/loop") == story.list_dir("script")
    assert story.list_dir("script/loop/sub") == DirListing(files=("c.vns",), dirs=())


def test_new_files_appear_only_after_invalidate_listings(story):
    before = story.list_dir("script/sub")
    (story.root / "script" / "sub" / "d.vns").write_text("", encoding="utf-8")
    assert story.list_dir("script/sub") == before
    assert story.walk_files("script", **WALK).refs == ALL_VNS
    story.invalidate_listings()
    assert story.list_dir("script/sub").files == ("c.vns", "d.vns")
    assert "script/sub/d.vns" in story.walk_files("script", **WALK).refs


def test_no_escape_reason_is_exported():
    assert not hasattr(paths, "ESCAPE_REASON")         # I-1: REASON_OUTSIDE is reused


# --- walk_files (AC-F02-67) -------------------------------------------------------------------

def test_walk_finds_suffix_matches_case_exactly_and_opens_no_file(story, outside):
    with scandir_spy() as listed, no_open():
        result = story.walk_files("script", **WALK)
    assert result == WalkResult(refs=ALL_VNS, truncated=False)
    assert not any(under(p, outside) for p in listed)


def test_walk_visits_each_real_directory_once(story):
    with scandir_spy() as listed:
        story.walk_files("script", **WALK)
    real = [os.path.normcase(str(p.resolve())) for p in listed]
    assert len(real) == len(set(real))
    script = story.root / "script"
    assert sorted(real) == sorted(os.path.normcase(str(p))
                                  for p in (story.root, script, script / "sub"))


def test_walk_stops_at_max_entries(story):
    # script/ in code-point order: B.vns, X.VNS, a.vns, loop, sub, é.vns; then sub/c.vns.
    assert story.walk_files("script", suffix=".vns", max_entries=3, max_depth=32) == \
        WalkResult(refs=("script/B.vns", "script/a.vns"), truncated=True)
    assert story.walk_files("script", suffix=".vns", max_entries=7, max_depth=32) == \
        WalkResult(refs=ALL_VNS, truncated=False)
    assert story.walk_files("script", suffix=".vns", max_entries=6, max_depth=32) == \
        WalkResult(refs=("script/B.vns", "script/a.vns", "script/é.vns"), truncated=True)


def test_walk_max_depth_zero_skips_subfolders(story):
    assert story.walk_files("script", suffix=".vns", max_entries=10_000, max_depth=0) == \
        WalkResult(refs=("script/B.vns", "script/a.vns", "script/é.vns"), truncated=False)


def test_walk_of_a_missing_folder_or_a_file_is_empty(story):
    assert story.walk_files("nope", **WALK) == WalkResult((), False)
    assert story.walk_files("script/a.vns", **WALK) == WalkResult((), False)
    with pytest.raises(AssetRefError):
        story.walk_files("script/ext", **WALK)
    with pytest.raises(AssetRefError):
        story.walk_files("../script", **WALK)


def test_walk_follows_a_link_to_an_unvisited_folder_inside_the_root(story):
    other = story.root / "other"
    (other / "deep").mkdir(parents=True)
    (other / "deep" / "d.vns").write_text("", encoding="utf-8")
    make_dir_link(story.root / "script" / "alias", other)
    make_dir_link(other / "deep" / "back", story.root / "script")     # a longer loop
    story.invalidate_listings()
    assert story.walk_files("script", **WALK).refs == (
        "script/B.vns", "script/a.vns", "script/alias/deep/d.vns", "script/sub/c.vns",
        "script/é.vns")


def test_file_link_out_of_the_root_is_never_named(tmp_path, outside):
    script = tmp_path / "game" / "script"
    script.mkdir(parents=True)
    make_file_symlink(script / "s.vns", outside / "s.vns")             # skips if not permitted
    make_file_symlink(script / "in.vns", script / "s.vns")             # in → s → outside
    (script / "ok.vns").write_text("", encoding="utf-8")
    game = GamePaths.for_game(tmp_path / "game")
    assert game.list_dir("script") == DirListing(files=("ok.vns",), dirs=())
    assert game.walk_files("script", **WALK).refs == ("script/ok.vns",)


# --- F01 I-11: walked folders are resolved once per listing lifetime (AC-F01-140) ----------

@contextlib.contextmanager
def resolve_spy():
    resolved: list[Path] = []
    real_resolve = Path.resolve

    def spy(self, *args, **kwargs):
        resolved.append(self)
        return real_resolve(self, *args, **kwargs)

    with mock.patch.object(Path, "resolve", spy):
        yield resolved


@pytest.fixture
def nested(tmp_path) -> GamePaths:
    folder = tmp_path / "game" / "images" / "real"
    folder.mkdir(parents=True)
    (folder / "x.png").write_bytes(b"inside")
    return GamePaths.for_game(tmp_path / "game")


def test_walked_folders_are_resolved_once_until_invalidated(nested):
    with resolve_spy() as resolved:
        nested.resolve("images/real/x.png")
    assert [p.name for p in resolved] == ["images", "real", "x.png"]
    for _ in range(3):
        with resolve_spy() as resolved:
            assert nested.resolve("images/real/x.png").name == "x.png"
        assert [p.name for p in resolved] == ["x.png"]          # the final target, always
        with resolve_spy() as resolved, pytest.raises(AssetMissing):
            nested.resolve("images/real/missing.png")
        assert resolved == []
    nested.invalidate_listings()
    with resolve_spy() as resolved:
        nested.resolve("images/real/x.png")
    assert [p.name for p in resolved] == ["images", "real", "x.png"]


@pytest.mark.parametrize("swapped", ["images", "images/real"])
def test_a_cached_folder_swapped_for_a_link_out_cannot_escape(nested, tmp_path, swapped):
    """A cached folder is a real path whose own listing is cached with it, so using it lists
    nothing new; the final target is still resolved strictly, which follows a link put in
    place of any cached folder, and the containment check then rejects it."""
    assert nested.read_file("images/real/x.png", max_bytes=100) == b"inside"
    evil = tmp_path / "evil"
    (evil / "real").mkdir(parents=True)
    (evil / "x.png").write_bytes(b"secret")
    (evil / "real" / "x.png").write_bytes(b"secret")
    victim = nested.root / swapped
    victim.rename(victim.with_name(victim.name + "-old"))
    make_dir_link(victim, evil)
    with scandir_spy() as listed, no_open():
        with pytest.raises(AssetRefError) as raised:
            nested.read_file("images/real/x.png", max_bytes=100)
        with pytest.raises(AssetRefError):
            nested.list_dir(swapped)
    assert raised.value.reason == REASON_OUTSIDE
    assert not any(under(p, evil) for p in listed)


def test_a_cached_folder_that_disappears_is_missing(nested):
    nested.resolve("images/real/x.png")
    (nested.root / "images" / "real" / "x.png").unlink()
    (nested.root / "images" / "real").rmdir()
    with pytest.raises(AssetMissing):
        nested.read_file("images/real/x.png", max_bytes=100)

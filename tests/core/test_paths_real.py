"""F23 C5 (``07`` §2.1, I-5): ``GamePaths.real_dir``, ``list_real``, and
``read_file(regular=True)`` — the real-entry reads the plugin loader uses (SEC-F23-01).

Links are refused wherever they point, inside the game folder included; FIFOs and devices are
left out; a reparse point that resolves to its own path (a cloud placeholder) counts as a
real entry. Symlink rows skip where the machine can't make symlinks; junction rows run on
Windows; FIFO rows on POSIX.
"""

import os
import sys
from pathlib import Path

import pytest

from engine.core import paths
from engine.core.errors import AssetNotFile, AssetRefError
from engine.core.paths import DirListing, GamePaths, NotReal, RealDir


def make_junction(link: Path, target: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("junctions exist only on Windows")
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


def make_symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create symlinks here (needs a privilege on Windows): {exc}")


@pytest.fixture
def root(tmp_path) -> Path:
    game = tmp_path / "game"
    (game / "minigames" / "pkg").mkdir(parents=True)
    (game / "minigames" / "a.py").write_bytes(b"A = 1\n")
    (game / "minigames" / "pkg" / "__init__.py").write_bytes(b"")
    (game / "saves").mkdir()
    (game / "saves" / "evil.py").write_bytes(b"EVIL = 1\n")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "evil.py").write_bytes(b"EVIL = 1\n")
    return game.resolve()


def test_real_dir_of_a_real_folder(root):
    found = GamePaths.for_game(root).real_dir("minigames")
    assert found == RealDir("minigames", root / "minigames")
    assert GamePaths.for_game(root).real_dir("minigames/pkg") == \
        RealDir("minigames/pkg", root / "minigames" / "pkg")


def test_real_dir_missing_file_and_case_variant(root):
    game = GamePaths.for_game(root)
    assert game.real_dir("nothing") == NotReal("missing")
    assert game.real_dir("minigames/a.py") == NotReal("not_dir")
    (root / "minigames").rename(root / "Minigames")
    game = GamePaths.for_game(root)
    assert game.real_dir("minigames") == NotReal("missing", "Minigames")
    with pytest.raises(AssetRefError):
        game.real_dir("../x")


@pytest.mark.parametrize("target", ["outside", "saves"])
def test_real_dir_refuses_a_junction_wherever_it_points(root, target):
    (root / "minigames").rename(root / "real_minigames")
    where = root.parent / "outside" if target == "outside" else root / "saves"
    make_junction(root / "minigames", where)
    game = GamePaths.for_game(root)
    assert game.real_dir("minigames") == NotReal("link")
    assert game.list_real("minigames") is None
    if target == "saves":
        assert game.list_dir("minigames") is not None      # resolve accepts a contained link


def test_real_dir_refuses_a_directory_symlink(root):
    make_symlink(root / "linked", root / "saves", directory=True)
    assert GamePaths.for_game(root).real_dir("linked") == NotReal("link")


def test_list_real_leaves_out_links_and_names_them_only(root):
    make_junction(root / "minigames" / "jpkg", root / "saves")
    game = GamePaths.for_game(root)
    listing = game.list_real("minigames")
    assert listing == DirListing(files=("a.py",), dirs=("pkg",), omitted=("jpkg",))
    assert game.list_dir("minigames").dirs == ("jpkg", "pkg")       # list_dir follows it
    assert game.list_real("minigames") is listing                   # cached
    game.invalidate_listings()
    assert game.list_real("minigames") == listing and game.list_real("minigames") is not listing


def test_list_real_leaves_out_file_symlinks_inside_and_outside(root):
    make_symlink(root / "minigames" / "x.py", root / "saves" / "evil.py")
    make_symlink(root / "minigames" / "y.py", root.parent / "outside" / "evil.py")
    listing = GamePaths.for_game(root).list_real("minigames")
    assert listing.files == ("a.py",) and listing.omitted == ("x.py", "y.py")
    assert listing.special == ()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs exist only on POSIX")
def test_list_real_leaves_out_a_fifo(root):
    os.mkfifo(root / "minigames" / "x.py")
    game = GamePaths.for_game(root)
    listing = game.list_real("minigames")
    assert listing.omitted == ("x.py",) and listing.special == ("x.py",)
    assert "x.py" in game.list_dir("minigames").files                # unchanged for list_dir


def test_a_special_entry_is_left_out_by_kind(root, monkeypatch):
    """The FIFO/device row on every OS: the listing records the entry as _SPECIAL."""
    real_kind = paths._entry_kind
    monkeypatch.setattr(paths, "_entry_kind", lambda e: paths._SPECIAL if e.name == "a.py"
                        else real_kind(e))
    game = GamePaths.for_game(root)
    listing = game.list_real("minigames")
    assert listing.files == () and listing.omitted == ("a.py",) and listing.special == ("a.py",)
    assert game.list_dir("minigames").files == ("a.py",)


def test_a_reparse_point_resolving_to_itself_counts_as_real(root, monkeypatch):
    """A mocked cloud placeholder (OneDrive, dedup): a _LINK entry whose real path is its own."""
    real_kind = paths._entry_kind
    monkeypatch.setattr(paths, "_entry_kind",
                        lambda e: paths._LINK if e.name in ("a.py", "minigames", "pkg")
                        else real_kind(e))
    game = GamePaths.for_game(root)
    assert isinstance(game.real_dir("minigames"), RealDir)
    assert game.list_real("minigames") == DirListing(files=("a.py",), dirs=("pkg",))
    assert game.read_file("minigames/a.py", max_bytes=100, regular=True) == b"A = 1\n"


def test_read_file_regular_refuses_a_link_swapped_in_after_listing(root):
    game = GamePaths.for_game(root)
    assert game.list_real("minigames").dirs == ("pkg",)
    (root / "minigames" / "pkg" / "__init__.py").unlink()
    (root / "minigames" / "pkg").rmdir()
    make_junction(root / "minigames" / "pkg", root / "saves")         # contained target
    with pytest.raises(AssetNotFile):
        game.read_file("minigames/pkg", max_bytes=100, regular=True)


def test_read_file_regular_refuses_a_contained_file_symlink(root):
    make_symlink(root / "minigames" / "x.py", root / "saves" / "evil.py")
    game = GamePaths.for_game(root)
    assert game.read_file("minigames/x.py", max_bytes=100) == b"EVIL = 1\n"   # default
    with pytest.raises(AssetNotFile):
        game.read_file("minigames/x.py", max_bytes=100, regular=True)


def test_read_file_regular_reads_a_hard_link(root):
    """A hard link loads (accepted residual, ADR-0009)."""
    try:
        os.link(root.parent / "outside" / "evil.py", root / "minigames" / "h.py")
    except OSError as exc:
        pytest.skip(f"cannot create hard links here: {exc}")
    game = GamePaths.for_game(root)
    assert "h.py" in game.list_real("minigames").files
    assert game.read_file("minigames/h.py", max_bytes=100, regular=True) == b"EVIL = 1\n"


def test_read_file_regular_refuses_a_parent_folder_swapped_for_a_link(root):
    game = GamePaths.for_game(root)
    assert game.list_real("minigames/pkg").files == ("__init__.py",)
    os.replace(root / "minigames" / "pkg", root / "moved")
    make_junction(root / "minigames" / "pkg", root / "moved")        # contained target
    assert game.read_file("minigames/pkg/__init__.py", max_bytes=100) == b""
    with pytest.raises(AssetNotFile):
        game.read_file("minigames/pkg/__init__.py", max_bytes=100, regular=True)

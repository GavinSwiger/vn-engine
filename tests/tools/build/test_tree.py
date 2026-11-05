"""F42 P2: the copy walk, left-out rules, containment, and replacing an earlier build
(AC-F42-08, -09, -20, -35, -37; SEC-F42-06, -07).

Directory links are junctions on Windows and symlinks elsewhere; symlink rows skip where
the machine doesn't allow them (``tests.core.test_safefile``'s helpers)."""

import json
import os
import zipfile
from pathlib import Path

import pytest

from engine.core import safefile
from engine.tools.build import rules, texts, tree
from engine.tools.build.texts import BuildStopped
from tests.core.test_safefile import link_dir, symlink

SENTINEL = b"SENTINEL-F42-outside"
SUPERSCRIPT_ONE = chr(0xB9)


def put(root: Path, ref: str, data: bytes | None = None) -> Path:
    """A file (``data``) or folder (``data`` None, or a ref ending in ``/``) under ``root``."""
    path = root.joinpath(*ref.rstrip("/").split("/"))
    if data is None:
        path.mkdir(parents=True, exist_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path


def files_under(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def left(result: tree.CopyResult) -> dict[str, str]:
    return {item.ref: item.key for item in result.left_out}


@pytest.fixture
def game(tmp_path) -> Path:
    root = tmp_path / "game"
    root.mkdir()
    return root


@pytest.fixture
def outside(tmp_path) -> Path:
    folder = tmp_path / "outside"
    folder.mkdir()
    (folder / "secret.png").write_bytes(SENTINEL)
    return folder


def copy(game: Path, tmp_path: Path) -> tuple[tree.CopyResult, Path]:
    dest = tmp_path / "dest"
    return tree.copy_game(game, dest), dest


# --- AC-F42-08: each left-out row and reason; the rest byte-identical ------------------------

LEFT_OUT_ROWS = {
    "logs/": texts.LEFT_OUT_TESTDATA,
    "Saves/": texts.LEFT_OUT_TESTDATA,                    # casefold at the top level
    "persistent/": texts.LEFT_OUT_TESTDATA,
    "SETTINGS/": texts.LEFT_OUT_TESTDATA,
    "characters/": texts.LEFT_OUT_CHARACTERS,
    ".studio/": texts.LEFT_OUT_HIDDEN,
    "images/.secret.png": texts.LEFT_OUT_HIDDEN,
    ".git/": texts.LEFT_OUT_HIDDEN,
    "minigames/__pycache__/": texts.LEFT_OUT_SYSTEM,
    "images/Thumbs.db": texts.LEFT_OUT_SYSTEM,
    "desktop.ini": texts.LEFT_OUT_SYSTEM,
    "AGENTS.md": texts.LEFT_OUT_AGENT,                   # 2026-11-04: notes for AI apps
    "claude.md": texts.LEFT_OUT_AGENT,
    "minigames/a.pyc": texts.LEFT_OUT_COMPILED,
    "minigames/pkg/fast.pyd": texts.LEFT_OUT_COMPILED,
    "minigames/data.json": texts.LEFT_OUT_UNUSED,
}
KEPT = ["config.toml", "script/start.vns", "images/bg/club.png", "images/saves/x.png",
        "audio/theme.ogg", "gui/box.png", "fonts/a.ttf", "files/note.txt",
        "characters.txt", "minigames/a.py", "minigames/pkg/__init__.py", "notes/todo.md",
        "notes/AGENTS.md",                               # only the top-level one is left out
        "minigames/pkg/sub/deep.py", "saves.png"]
REASON_TEXTS = {
    texts.LEFT_OUT_TESTDATA: "test-run data from your PC; players get their own",
    texts.LEFT_OUT_CHARACTERS: ("written by the game while it runs; the originals ship "
                                "from files/"),
    texts.LEFT_OUT_HIDDEN: "hidden file or folder",
    texts.LEFT_OUT_SYSTEM: "made by Windows or Python, not part of the game",
    texts.LEFT_OUT_COMPILED: "compiled code; the game uses the .py files",
    texts.LEFT_OUT_AGENT: "notes for AI apps that help you make the game, not part of it",
}


def test_ac_f42_08_left_out_rows_and_the_rest_copied_byte_identical(game, tmp_path):
    for ref in LEFT_OUT_ROWS:
        put(game, ref, None if ref.endswith("/") else b"left")
    put(game, "logs/x.log", b"log")
    put(game, ".studio/build.json", b"{}")
    put(game, "minigames/__pycache__/a.cpython-312.pyc", b"pyc")
    for i, ref in enumerate(KEPT):
        put(game, ref, f"kept {i} ".encode() + bytes(range(256)))
    before = files_under(game)
    result, dest = copy(game, tmp_path)
    assert left(result) == {ref.rstrip("/"): key for ref, key in LEFT_OUT_ROWS.items()}
    assert files_under(dest) == {ref: before[ref] for ref in KEPT}
    assert files_under(game) == before                               # the source is unchanged
    assert (result.files, result.bytes) == (len(KEPT), sum(len(before[r]) for r in KEPT))
    reasons = {item.ref: item.reason for item in result.left_out}
    for ref, key in LEFT_OUT_ROWS.items():
        ref = ref.rstrip("/")
        if ref == ".studio":
            assert reasons[ref] == "Studio's own files"
        elif key == texts.LEFT_OUT_UNUSED:
            assert reasons[ref] == ("the game can't use this file here "
                                    "(Minigames takes .py files)")
        else:
            assert reasons[ref] == REASON_TEXTS[key], ref
    assert {item.line for item in result.left_out} >= {"logs — " + REASON_TEXTS[
        texts.LEFT_OUT_TESTDATA]}
    scanned = tree.prescan(game)
    assert (scanned.files, scanned.bytes, left(scanned)) == (result.files, result.bytes,
                                                             left(result))


# --- AC-F42-09: links and junctions are neither followed nor copied ---------------------------

@pytest.mark.parametrize("where, kind", [
    ("script", "dir"), ("images/old", "dir"), ("images/deep/er/old", "dir"),
    ("images/file.png", "file"), ("audio/x/sym", "symdir"),
])
def test_ac_f42_09_links_and_junctions_are_left_out_with_left_out_link(
        game, outside, tmp_path, where, kind):
    put(game, "images/deep/er/keep.png", b"keep")
    put(game, "audio/x/keep.ogg", b"keep")
    link = game.joinpath(*where.split("/"))
    link.parent.mkdir(parents=True, exist_ok=True)
    if kind == "dir":
        link_dir(link, outside)
    elif kind == "symdir":
        symlink(link, outside, directory=True)
    else:
        symlink(link, outside / "secret.png")
    result, dest = copy(game, tmp_path)
    assert left(result) == {where: texts.LEFT_OUT_LINK}
    assert [item.reason for item in result.left_out] == [
        "a link or shortcut; builds copy only real files and folders"]
    assert not dest.joinpath(*where.split("/")).exists()
    assert SENTINEL not in b"".join(files_under(dest).values())
    assert set(files_under(dest)) == {"images/deep/er/keep.png", "audio/x/keep.ogg"}
    assert os.listdir(outside) == ["secret.png"]


# --- AC-F42-20: Save to inside the game folder, or containing it ------------------------------

def test_ac_f42_20_save_to_inside_or_containing_the_game_is_out_inside(tmp_path):
    game = put(tmp_path, "projects/game/")
    rows = [
        (game / "builds", True),                  # Save to inside the game folder
        (game, True),                             # the game folder itself
        (tmp_path / "projects", True),            # Save to containing the game (reverse)
        (tmp_path, True),
        (tmp_path / "projects" / "builds", False),
        (tmp_path / "projects" / "game2", False),
        (tmp_path / "projects" / "gamex" / "builds", False),
    ]
    for save_to, out_inside in rows:
        either = tree.real_inside(save_to, game) or tree.real_inside(game, save_to)
        assert either is out_inside, save_to
    if os.name == "nt":
        upper = Path(str(game).upper()) / "Builds"
        assert tree.real_inside(upper, game)                         # normcase
    message, fix = texts.failure("B_OUT_INSIDE", game="game")
    assert message == "The build can't be saved inside the game folder."
    assert fix == "Choose a folder outside game, like the builds folder next to it."


# --- AC-F42-35: D3 unusable files left out, license and read-me files kept --------------------

def test_ac_f42_35_unusable_asset_files_left_out_license_files_kept(game, tmp_path):
    rows = {
        "images/hana.psd": "the game can't use this file here "
                           "(Images takes .png, .jpg, .jpeg, .webp files)",
        "images/sub/sketch.kra": "the game can't use this file here "
                                 "(Images takes .png, .jpg, .jpeg, .webp files)",
        "audio/theme.mid": "the game can't use this file here "
                           "(Audio takes .flac, .mp3, .ogg, .opus, .wav files)",
        "script/plan.txt": "the game can't use this file here (Script takes .vns files)",
        "images/noext": "the game can't use this file here "
                        "(Images takes .png, .jpg, .jpeg, .webp files)",
    }
    kept = ["images/LICENSE.txt", "images/hana.PNG", "images/Licence", "audio/README.md",
            "audio/credits.txt", "script/COPYING", "script/a.vns", "gui/mock.psd",
            "fonts/OFL.txt", "files/x.psd", "notes/x.psd"]
    for ref in [*rows, *kept]:
        put(game, ref, ref.encode())
    result, dest = copy(game, tmp_path)
    assert {item.ref: (item.key, item.reason) for item in result.left_out} == {
        ref: (texts.LEFT_OUT_UNUSED, reason) for ref, reason in rows.items()}
    assert sorted(files_under(dest)) == sorted(kept)


# --- AC-F42-37: copy and delete abuse cases (05 §6) -------------------------------------------

def _make_build(save_to: Path, folder: str, *, marker: bytes | None = None) -> Path:
    build = save_to / folder
    put(build, "Game.exe", b"exe")
    put(build, "game/script/a.vns", b"old")
    data = marker if marker is not None else tree.marker_bytes(
        engine="0.1", app_id="g", version="1", built="2026-11-02")
    put(build, "_internal/vn-build.json", data)
    return build


def _stage(tmp_path: Path, save_to: Path, folder: str) -> tuple[tree.Staging, Path]:
    staging = tree.make_staging(save_to, folder)
    new = put(staging.path, f"out/{folder}/")
    put(new, "Game.exe", b"new")
    put(new, "_internal/vn-build.json", tree.marker_bytes(engine="0.1", app_id="g",
                                                          version="1", built="x"))
    return staging, new


def _row_link_not_followed(game, outside, tmp_path, monkeypatch):
    link_dir(game / "script", outside)
    put(game, "images/", None)
    link_dir(game / "images" / "old", outside)
    result, dest = copy(game, tmp_path)
    assert left(result) == {"script": texts.LEFT_OUT_LINK, "images/old": texts.LEFT_OUT_LINK}
    assert all(SENTINEL not in path.read_bytes() for path in dest.rglob("*") if path.is_file())


def _row_swapped_mid_copy(game, outside, tmp_path, monkeypatch):
    put(game, "images/a.png", b"original")
    other = put(tmp_path, "other.png", SENTINEL)
    real_open = safefile.open_regular

    def swap_then_open(path):
        if path.name == "a.png":
            os.replace(other, path)                     # a new file at the listed name
        return real_open(path)

    monkeypatch.setattr(safefile, "open_regular", swap_then_open)
    with pytest.raises(BuildStopped) as stopped:
        copy(game, tmp_path)
    assert (stopped.value.key, stopped.value.values) == ("B_COPY_FAILED", {"ref": "images/a.png"})
    assert texts.failure("B_COPY_FAILED", ref="images/a.png")[0] == (
        "images/a.png couldn't be copied: it was moved, deleted, or is open in another program.")


def _row_growing(game, outside, tmp_path, monkeypatch):
    put(game, "audio/a.ogg", b"x" * 1000)
    real_open = safefile.open_regular

    def open_then_grow(path):
        opened = real_open(path)
        with open(path, "ab") as stream:
            stream.write(b"more")
        return opened

    monkeypatch.setattr(safefile, "open_regular", open_then_grow)
    with pytest.raises(BuildStopped) as stopped:
        copy(game, tmp_path)
    assert stopped.value.key == "B_COPY_FAILED"


def _row_hard_link(game, outside, tmp_path, monkeypatch):
    first = put(game, "images/a.png", b"shared")
    os.link(first, game / "images" / "b.png")
    result, dest = copy(game, tmp_path)
    assert files_under(dest) == {"images/a.png": b"shared", "images/b.png": b"shared"}
    assert [os.stat(dest / "images" / n).st_nlink for n in ("a.png", "b.png")] == [1, 1]


def _row_bad_windows_names(game, outside, tmp_path, monkeypatch):
    names = ["CON", f"com{SUPERSCRIPT_ONE}.png", "a.png.", "b "]
    prefix = "\\\\?\\" if os.name == "nt" else ""
    put(game, "images/", None)
    made = [Path(prefix + str(game / "images" / name)) for name in names]
    try:
        for path in made:
            with open(path, "wb") as stream:
                stream.write(b"x")
        put(game, "images/ok.png", b"ok")
        result, dest = copy(game, tmp_path)
        assert left(result) == {f"images/{n}": texts.LEFT_OUT_BAD_NAME for n in names}
        assert result.left_out[0].reason == ("Windows can't use this name. "
                                             "Rename it to include it.")
        assert os.listdir(dest / "images") == ["ok.png"]
    finally:
        for path in made:
            if os.path.lexists(path):
                os.unlink(path)


def _row_out_inside_through_junctions(game, outside, tmp_path, monkeypatch):
    link_dir(tmp_path / "save_link", game)                     # Save to → into the game
    assert tree.real_inside(tmp_path / "save_link" / "builds", game)
    save_to = put(tmp_path, "builds/")
    real_game = put(save_to, "real_game/")
    link_dir(tmp_path / "game_alias", real_game)               # the game, via a junction
    assert tree.real_inside(tmp_path / "game_alias", save_to)
    assert not tree.real_inside(game, save_to) and not tree.real_inside(save_to, game)


def _row_replace_keeps_junction_target(game, outside, tmp_path, monkeypatch):
    save_to = put(tmp_path, "builds/")
    old = _make_build(save_to, "G 1 Windows")
    link_dir(old / "game" / "images", outside)
    staging, new = _stage(tmp_path, save_to, "G 1 Windows")
    installed = tree.install_build(save_to, "G 1 Windows", new)
    assert installed.left == () and installed.folder == save_to / "G 1 Windows"
    assert (save_to / "G 1 Windows" / "Game.exe").read_bytes() == b"new"
    assert (outside / "secret.png").read_bytes() == SENTINEL
    assert staging.remove() is None
    assert sorted(os.listdir(save_to)) == ["G 1 Windows"]


def _bad_marker_cases(save_to: Path, outside: Path) -> list[tuple[str, object]]:
    def folder_marker(build):
        (build / "_internal" / "vn-build.json").unlink()
        (build / "_internal" / "vn-build.json").mkdir()

    def big(build):
        (build / "_internal" / "vn-build.json").write_bytes(b" " * 5000 + b"{}")

    def bad_json(build):
        (build / "_internal" / "vn-build.json").write_bytes(b"{format: 1")

    def wrong_format(build):
        (build / "_internal" / "vn-build.json").write_bytes(json.dumps(
            {"format": True, "engine": "", "id": "", "version": "", "built": ""}).encode())

    def internal_junction(build):
        real = put(outside, "internal/")
        put(real, "vn-build.json", tree.marker_bytes(engine="", app_id="", version="",
                                                     built=""))
        for path in (build / "_internal").iterdir():
            path.unlink()
        (build / "_internal").rmdir()
        link_dir(build / "_internal", real)

    def no_marker(build):
        (build / "_internal" / "vn-build.json").unlink()

    return [("folder", folder_marker), ("5 KiB", big), ("bad JSON", bad_json),
            ("format", wrong_format), ("_internal junction", internal_junction),
            ("none", no_marker)]


def _row_bad_markers(game, outside, tmp_path, monkeypatch):
    for label, spoil in _bad_marker_cases(tmp_path, outside):
        save_to = put(tmp_path, f"b-{label}/")
        old = _make_build(save_to, "G 1 Windows")
        spoil(old)
        before = sorted(p.relative_to(save_to).as_posix() for p in save_to.rglob("*"))
        staging, new = _stage(tmp_path, save_to, "G 1 Windows")
        with pytest.raises(BuildStopped) as stopped:
            tree.install_build(save_to, "G 1 Windows", new)
        assert stopped.value.key == "B_NAME_TAKEN", label
        assert stopped.value.values == {"folder": "G 1 Windows", "save_to": f"b-{label}"}
        assert staging.remove() is None
        assert sorted(p.relative_to(save_to).as_posix() for p in save_to.rglob("*")) == before


def _row_marker_symlink(game, outside, tmp_path, monkeypatch):
    save_to = put(tmp_path, "builds/")
    old = _make_build(save_to, "G 1 Windows")
    real = put(outside, "vn-build.json", tree.marker_bytes(engine="", app_id="", version="",
                                                           built=""))
    (old / "_internal" / "vn-build.json").unlink()
    symlink(old / "_internal" / "vn-build.json", real)
    assert not tree.is_earlier_build(old)
    with pytest.raises(BuildStopped):
        tree.find_earlier_build(save_to, "G 1 Windows", with_zip=False)


def _row_zip_without_marker(game, outside, tmp_path, monkeypatch):
    save_to = put(tmp_path, "builds/")
    with zipfile.ZipFile(save_to / "G 1 Windows.zip", "w") as archive:
        archive.writestr("G 1 Windows/Game.exe", b"x")
    with zipfile.ZipFile(save_to / "H 1 Windows.zip", "w") as archive:
        archive.writestr("H 1 Windows/_internal/vn-build.json", b"{}")
    assert not tree.zip_is_earlier_build(save_to / "G 1 Windows.zip", "G 1 Windows")
    assert tree.zip_is_earlier_build(save_to / "H 1 Windows.zip", "H 1 Windows")
    assert not tree.zip_is_earlier_build(save_to / "H 1 Windows.zip", "G 1 Windows")
    (save_to / "junk.zip").write_bytes(b"PK\x05\x06" + b"\xff" * 18)
    assert not tree.zip_is_earlier_build(save_to / "junk.zip", "junk")
    staging, new = _stage(tmp_path, save_to, "G 1 Windows")
    with pytest.raises(BuildStopped) as stopped:
        tree.install_build(save_to, "G 1 Windows", new, new.parent / "G 1 Windows.zip")
    assert stopped.value.values["folder"] == "G 1 Windows.zip"
    # No zip this time: a non-build at the zip name is left alone.
    assert tree.install_build(save_to, "G 1 Windows", new).zip is None
    assert (save_to / "G 1 Windows.zip").exists() and staging.remove() is None


def _row_old_exe_open(game, outside, tmp_path, monkeypatch):
    save_to = put(tmp_path, "builds/")
    old = _make_build(save_to, "G 1 Windows")
    staging, new = _stage(tmp_path, save_to, "G 1 Windows")
    if os.name != "nt":                         # POSIX renames an open folder; refuse it here
        real_rename = os.rename

        def refuse(source, target):
            if Path(source) == old:
                raise PermissionError(13, "in use")
            return real_rename(source, target)

        monkeypatch.setattr(tree.os, "rename", refuse)
    with open(old / "Game.exe", "rb"):
        with pytest.raises(BuildStopped) as stopped:
            tree.install_build(save_to, "G 1 Windows", new)
    assert stopped.value.key == "B_IN_USE"
    assert (old / "Game.exe").read_bytes() == b"exe" and tree.is_earlier_build(old)
    assert (new / "Game.exe").read_bytes() == b"new"
    assert staging.remove() is None and sorted(os.listdir(save_to)) == ["G 1 Windows"]


def _row_caps_during_walk(game, outside, tmp_path, monkeypatch):
    save_to = put(tmp_path, "builds/")
    for i in range(5):
        put(game, f"images/{i}.png", b"x")
    monkeypatch.setattr(tree, "MAX_ENTRIES", 7)
    assert tree.prescan(game).files == 5                        # 6 entries: within the cap
    put(game, "images/5.png", b"x")
    put(game, "images/6.png", b"x")                             # appear after the pre-scan
    for cap, value, reason in (("MAX_ENTRIES", 7, "more than 50,000 files"),
                               ("MAX_DEPTH", 1, "folders more than 32 deep"),
                               ("MAX_BYTES", 6, "more than 8 GB")):
        monkeypatch.setattr(tree, "MAX_ENTRIES", 50_000)
        monkeypatch.setattr(tree, cap, value)
        if cap == "MAX_DEPTH":
            put(game, "images/sub/", None)
        staging = tree.make_staging(save_to, "G 1 Windows")
        with pytest.raises(BuildStopped) as stopped:
            tree.copy_game(game, put(staging.path, "out/") / "game")
        assert stopped.value.key == "B_TOO_BIG" and stopped.value.values == {"reason": reason}
        assert staging.remove() is None and os.listdir(save_to) == []


def _row_stale_sweep(game, outside, tmp_path, monkeypatch):
    save_to = put(tmp_path, "builds/")
    running = tree.make_staging(save_to, "G 1 Windows")
    stale = tree.make_staging(save_to, "G 1 Windows")
    stale.release()
    link_dir(stale.path / "linked", outside)
    old = _make_build(save_to, ".G 1 Windows.old-0123abcd")
    put(save_to, ".x.building-0123abcd/")                       # no marker: not ours
    put(save_to, ".y.old-0123abcd/")                            # not a build: not ours
    keep = sorted(os.listdir(save_to))
    assert tree.sweep_stale(save_to) == []                      # nothing older than 60 s
    later = tree.time.time() + 3600
    removed = tree.sweep_stale(save_to, now=later)
    expected = {stale.name, old.name} if os.name == "nt" else {stale.name, old.name,
                                                               running.name}
    assert set(removed) == expected
    assert sorted(os.listdir(save_to)) == sorted(set(keep) - expected)
    assert (outside / "secret.png").read_bytes() == SENTINEL
    assert running.remove() is None


ABUSE_ROWS = {
    "link not followed, no sentinel byte": _row_link_not_followed,
    "file swapped mid-copy": _row_swapped_mid_copy,
    "file growing": _row_growing,
    "hard link copied as content": _row_hard_link,
    "unsafe Windows names": _row_bad_windows_names,
    "B_OUT_INSIDE through junctions": _row_out_inside_through_junctions,
    "replace keeps a junction's target": _row_replace_keeps_junction_target,
    "bad marker": _row_bad_markers,
    "marker a symlink": _row_marker_symlink,
    "zip without the marker entry": _row_zip_without_marker,
    "old build's exe open": _row_old_exe_open,
    "caps during the walk": _row_caps_during_walk,
    "stale staging and asides swept": _row_stale_sweep,
}


@pytest.mark.parametrize("row", ABUSE_ROWS)
def test_ac_f42_37_copy_and_delete_abuse_cases(row, game, outside, tmp_path, monkeypatch):
    ABUSE_ROWS[row](game, outside, tmp_path, monkeypatch)


def test_rules_and_tree_use_only_public_names():
    """07 I-3: no private cross-module imports in the shared build modules."""
    for module in (rules, tree):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "paths._" not in source and "safefile._" not in source
        assert "import _" not in source and "import (_" not in source

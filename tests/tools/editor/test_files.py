"""Studio's file operations without Tk (F45 ``04`` §7.4, §7.5, §8; ``06`` AC-F45-16..18,
20..28; TR-F45-05; ADR-0008 Amendment 1).

One test per AC; table rows run in a loop on fresh copies of game S. Junction rows run on
Windows; file-symlink rows run where the OS allows symlinks and are passed over otherwise;
FIFO and device rows run on POSIX."""

import dataclasses
import errno
import hashlib
import os
import re
import shutil
import stat
import sys
import threading
import tomllib
from pathlib import Path

import pytest

from engine.core import safefile
from engine.core.config import load_config
from engine.core.constants import ASSET_MAX_BYTES, IMAGE_MAX_PIXELS, IMAGE_MAX_SIDE
from engine.core.paths import GamePaths, slugify
from engine.script.assetgroups import ASSET_GROUPS, MINIGAME_FILE_MAX_BYTES, MUSIC_MAX_BYTES
from engine.script.imagenames import word_problem
from engine.script.limits import SCRIPT_FILE_MAX_BYTES
from engine.script.loader import load_story
from engine.tools.editor import document, files
from tests.tools.editor.conftest import S_SCRIPTS, link_dir, ogg, png, try_link_file

POSIX = os.name == "posix"
TEMP = re.compile(r"\..+\.[0-9a-f]{8}\.tmp")


def S(tmp_path: Path, studio_game: Path, name: str) -> Path:
    """A fresh copy of game S for one row."""
    game = tmp_path / "rows" / name / "my_game"
    shutil.copytree(studio_game, game)
    return game


def paths_of(game: Path) -> GamePaths:
    return GamePaths.for_game(game)


def no_temp(*folders: Path) -> bool:
    return not any(TEMP.fullmatch(name) for folder in folders
                   for _root, dirs, names in os.walk(folder) for name in dirs + names)


def sha(folder: Path) -> dict[str, str]:
    found = {}
    for root, dirs, names in os.walk(folder):
        for name in names:
            path = Path(root, name)
            found[str(path.relative_to(folder))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def source(folder: Path, name: str, data: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    return path


def add(game: Path, key: str, folder: str, src: Path, choice: str = "new",
        name: str | None = None) -> files.AddOutcome:
    paths = paths_of(game)
    plan = files.plan_add(paths, key, folder, [src])[0]
    if name is not None:
        plan = files.rename_plan(paths, plan, name)
    return files.run_add(paths, plan, choice)


# --- AC-F45-16: the project panel ----------------------------------------------------------

def test_ac16_project_tree_lists_what_the_engine_reads(tmp_path, studio_game, outside,
                                                        monkeypatch):
    game = S(tmp_path, studio_game, "s")
    tree = files.project_tree(paths_of(game))
    assert [(g.name, g.count) for g in tree.groups] == [
        ("Script", 2), ("Images", 3), ("Audio", 1), ("GUI", 1), ("Fonts", 0),
        ("Minigames", 0)]                       # sky.gif isn't an IMAGE_SUFFIXES file
    assert tree.config.ref == "config.toml"
    assert tree.file_refs("script") == ["script/main.vns", "script/ch2.vns"]
    assert tree.find("images/hana/happy.png").image_name == "hana happy"

    (game / "images" / "readme.txt").write_text("x")
    source(outside, "a.png", png(1, 1))
    link_dir(game / "images" / "ext", outside)
    deep = game / "images"
    for depth in range(1, 10):
        deep = deep / f"d{depth}"
        source(deep, "x.png", png(1, 1))
    linked = try_link_file(game / "images" / "hana" / "alias.png",
                           game / "images" / "bg" / "room.png")
    paths = paths_of(game)
    refs = {node.ref for node in files.project_tree(paths).nodes()}
    assert "images/readme.txt" not in refs
    assert not any(ref.startswith("images/ext") for ref in refs)
    eight = "images/" + "/".join(f"d{n}" for n in range(1, 9))
    assert f"{eight}/x.png" in refs and f"{eight}/d9/x.png" not in refs
    if linked:
        listed = "alias.png" in paths.list_dir("images/hana").files
        assert ("images/hana/alias.png" in refs) == listed

    crowded = S(tmp_path, studio_game, "crowded")
    for number in range(21):
        source(crowded / "images" / "many", f"f{number:02}.png", png(1, 1))
    shutil.rmtree(crowded / "images" / "bg")
    shutil.rmtree(crowded / "images" / "hana")
    monkeypatch.setattr(files, "TREE_MAX_ENTRIES", 20)
    tree = files.project_tree(paths_of(crowded))
    assert len(tree.find("images/many").children) == 20 and tree.truncated


# --- AC-F45-17: planning an add ------------------------------------------------------------

def test_ac17_plan_add_reads_no_content(tmp_path, studio_game, monkeypatch):
    game = S(tmp_path, studio_game, "s")
    src = tmp_path / "src"
    sources = {name: source(src, name, data) for name, data in (
        ("room2.png", png(5, 5)), ("Hana Smile.png", png(3, 3)), ("花.png", png(1, 1)),
        ("notes.txt", b"n"), ("Song.OGG", ogg()), ("a.ttf", b"font"),
        ("ch3.vns", b"label ch3:\n"), ("game.py", b"x = 1\n"))}
    opened: list[str] = []
    real_open = os.open
    monkeypatch.setattr(os, "open", lambda p, *a, **k: (opened.append(str(p)),
                                                         real_open(p, *a, **k))[1])
    paths = paths_of(game)

    def plan(name, key, folder):
        return files.plan_add(paths, key, folder, [sources[name]])[0]

    room2 = plan("room2.png", "images", "images/bg")
    assert room2.ok and room2.name == "room2.png" and room2.image_name == "bg room2"
    hana = plan("Hana Smile.png", "images", "images/hana")
    assert hana.problem == ("`Hana Smile.png` can't be an image name (spaces). "
                            "Use `hana_smile.png`?")
    assert files.rename_plan(paths, hana, hana.offer).show_line == \
        "In the script: show hana hana_smile"
    smile = files.rename_plan(paths, hana, "smile.png")
    assert smile.ok and smile.show_line == "In the script: show hana smile"
    flower = plan("花.png", "images", "images/hana")
    fix = word_problem("花")
    if fix is None:
        assert flower.ok
    elif fix[1] is None:
        assert flower.refusal is not None
    else:
        assert flower.offer == fix[1].lower() + ".png"
    assert plan("notes.txt", "images", "images").refusal == \
        "`notes.txt`: Images takes PNG, JPEG, or WebP files."
    for name, key, folder in (("Song.OGG", "audio", "audio/bgm"), ("a.ttf", "fonts", "fonts"),
                              ("ch3.vns", "script", "script")):
        assert plan(name, key, folder).ok, name
    code = plan("game.py", "minigames", "minigames")
    assert code.ok and code.note == files.TRUST
    assert not [p for p in opened if str(src) in p]

    if try_link_file(src / "link.png", sources["room2.png"]):
        outcome = add(game, "images", "images/bg", src / "link.png")
        written = game / "images" / "bg" / "link.png"
        assert outcome.ref == "images/bg/link.png"
        assert stat.S_ISREG(os.lstat(written).st_mode)
        assert written.read_bytes() == png(5, 5)


# --- AC-F45-18: running an add -------------------------------------------------------------

def test_ac18_run_add_checks_content_and_never_overwrites_silently(tmp_path, studio_game):
    src = tmp_path / "src"
    refused = [
        ("wide.png", png(IMAGE_MAX_SIDE + 1, 1), "images", "images/bg"),
        ("many_px.png", png(8001, 8001), "images", "images/bg"),
        ("x.ogg", b"ID3\x04" + bytes(64), "audio", "audio/bgm"),
        ("midi.ogg", b"MThd" + bytes(64), "audio", "audio/bgm"),
        ("bad.vns", b"label a:\n    \"\xff\"\n", "script", "script"),
        ("bad.py", "é = 1\n".encode("latin-1"), "minigames", "minigames"),
    ]
    assert 8001 <= IMAGE_MAX_SIDE and 8001 * 8001 > IMAGE_MAX_PIXELS
    for name, data, key, folder in refused:
        game = S(tmp_path, studio_game, name)
        before = sha(game)
        outcome = add(game, key, folder, source(src, name, data))
        assert outcome.ref is None and outcome.reason, name
        assert sha(game) == before and no_temp(game), name
    game = S(tmp_path, studio_game, "bad.vns check")
    reason = add(game, "script", "script", src / "bad.vns").reason
    assert "isn't saved as UTF-8" in reason

    game = S(tmp_path, studio_game, "ok")
    assert add(game, "fonts", "fonts", source(src, "any.ttf", os.urandom(64))).ref == \
        "fonts/any.ttf"
    modules = set(sys.modules)
    assert add(game, "minigames", "minigames", source(src, "game.py", b"x = 1\n")).ref
    folder = game / "minigames"
    assert stat.S_ISDIR(os.lstat(folder).st_mode) and not os.path.isjunction(folder)
    assert set(sys.modules) == modules
    if POSIX:
        mask = os.umask(0)
        os.umask(mask)
        assert stat.S_IMODE(os.stat(folder / "game.py").st_mode) == 0o666 & ~mask

    happy = game / "images" / "hana" / "happy.png"
    original = happy.read_bytes()
    new = source(src, "happy.png", png(7, 7))
    assert add(game, "images", "images/hana", new, "keep_both").ref == \
        "images/hana/happy_2.png"
    assert add(game, "images", "images/hana", new, "keep_both").ref == \
        "images/hana/happy_3.png"
    assert happy.read_bytes() == original
    if POSIX:
        os.chmod(happy, 0o640)
    assert add(game, "images", "images/hana", new, "replace").ref == "images/hana/happy.png"
    assert happy.read_bytes() == png(7, 7)
    if POSIX:
        assert stat.S_IMODE(os.stat(happy).st_mode) == 0o640

    paths = paths_of(game)
    plan = files.plan_add(paths, "images", "images/hana", [source(src, "happy.png",
                                                                   png(8, 8))])[0]
    happy.write_bytes(b"another writer" * 10)
    outcome = files.run_add(paths, plan, "replace")
    assert outcome.ref is None and "changed on disk" in outcome.reason
    assert happy.read_bytes() == b"another writer" * 10

    picks = [source(src, n, png(2, 2)) for n in ("p1.png", "p2.png", "p3.png")]
    picks.append(source(src, "notes.txt", b"n"))
    outcomes = [files.run_add(paths, p, "new")
                for p in files.plan_add(paths, "images", "images/bg", picks)]
    assert files.add_summary(outcomes) == (
        "Added 3 files.\n1 file wasn't added:\n"
        "`notes.txt`: Images takes PNG, JPEG, or WebP files.")
    assert no_temp(game)


# --- AC-F45-20: new script file ------------------------------------------------------------

def test_ac20_new_script(tmp_path, studio_game):
    game = S(tmp_path, studio_game, "s")
    (game / "script" / "routes").mkdir()
    paths = paths_of(game)
    assert files.new_script(paths, "script", "ch3.vns") == "script/ch3.vns"
    assert (game / "script" / "ch3.vns").read_bytes() == b"label ch3:\n"
    assert files.new_script(paths, "script/routes", "kai.vns") == "script/routes/kai.vns"
    assert (game / "script" / "routes" / "kai.vns").read_bytes() == b"label kai:\n"
    rows = {
        "ch2.vns": "`script/ch2.vns` already exists.",
        "ch3.txt": "`ch3.txt`: Script takes .vns files.",
        "ch-2.vns": "`ch-2` can't be a label name. Use `ch_2`.",
        "../x.vns": None,
        "con.vns": None,
    }
    for name, text in rows.items():
        result = files.new_script(paths, "script", name)
        assert isinstance(result, files.Refusal), name
        assert text is None or result.text == text, (name, result.text)
    assert (game / "script" / "ch2.vns").read_text() == S_SCRIPTS["ch2.vns"]
    assert sorted(p.name for p in (game / "script").iterdir()) == [
        "ch2.vns", "ch3.vns", "main.vns", "routes"]


# --- AC-F45-21: rename and delete ----------------------------------------------------------

def test_ac21_rename_and_delete(tmp_path, studio_game, monkeypatch):
    game = S(tmp_path, studio_game, "s")
    paths = paths_of(game)
    happy = (game / "images" / "hana" / "happy.png").read_bytes()
    assert files.rename_file(paths, "images/hana/happy.png", "smile.png") == \
        "images/hana/smile.png"
    assert (game / "images" / "hana" / "smile.png").read_bytes() == happy
    assert not (game / "images" / "hana" / "happy.png").exists()
    for ref, name in (("images/hana/smile.png", "../bg/x.png"),
                      ("images/hana/smile.png", "sub/x.png"),
                      ("images/hana/smile.png", "Sad Face.png"),
                      ("script/ch2.vns", "ch2.txt"),
                      ("script/main.vns", "start.vns"), ("config.toml", "c.toml"),
                      ("images/bg", "bg2")):
        assert isinstance(files.rename_file(paths, ref, name), files.Refusal), (ref, name)
    assert files.rename_file(paths, "script/main.vns", "x.vns").text == files.MAIN_FIXED

    assert files.delete_file(paths, "images/bg/room.png") is None
    assert not (game / "images" / "bg" / "room.png").exists()
    for ref in ("script/main.vns", "config.toml"):
        assert isinstance(files.delete_file(paths, ref), files.Refusal)
    for kind in safefile.RemoveKind:
        if kind is safefile.RemoveKind.REMOVED:
            continue
        monkeypatch.setattr(files.safefile, "remove_file", lambda _path, k=kind: k)
        assert isinstance(files.delete_file(paths, "images/bg/photo.jpg"), files.Refusal)
    assert (game / "images" / "bg" / "photo.jpg").exists()

    # The open record keeps its unsaved text when retargeted (the window part: AC-19's test).
    doc = document.open_document(paths, "script/ch2.vns")
    assert files.rename_file(paths, "script/ch2.vns", "ch4.vns") == "script/ch4.vns"
    document.retarget(doc, paths, "script/ch4.vns")
    document.save(doc, "# edited\n" + S_SCRIPTS["ch2.vns"].rstrip("\n"))
    assert (game / "script" / "ch4.vns").read_text().startswith("# edited")


# --- AC-F45-22: containment, links and junctions --------------------------------------------

def test_ac22_writes_never_leave_the_real_group_folders(tmp_path, studio_game, outside,
                                                        monkeypatch):
    src = source(tmp_path / "src", "new.png", png(2, 2))
    source(outside, "h.png", b"outside")
    source(outside, "c.toml", b'[game]\ntitle = "Out"\n')
    before = sha(outside)
    c1 = "`images/` is a link or not a folder, so Studio won't add files there."

    def check(game: Path) -> None:
        assert sha(outside) == before and no_temp(game, outside)

    game = S(tmp_path, studio_game, "images junction")
    shutil.rmtree(game / "images")
    link_dir(game / "images", outside)
    assert add(game, "images", "images", src).reason == c1
    check(game)

    game = S(tmp_path, studio_game, "images to gui")
    shutil.rmtree(game / "images")
    link_dir(game / "images", game / "gui")
    assert add(game, "images", "images", src).reason == c1
    assert sorted(os.listdir(game / "gui")) == ["button.png"]

    game = S(tmp_path, studio_game, "images is a file")
    shutil.rmtree(game / "images")
    (game / "images").write_bytes(b"x")
    assert add(game, "images", "images", src).reason == c1

    game = S(tmp_path, studio_game, "swapped")
    paths = paths_of(game)
    plan = files.plan_add(paths, "images", "images/hana", [src])[0]
    shutil.rmtree(game / "images" / "hana")
    link_dir(game / "images" / "hana", outside)
    assert files.run_add(paths, plan, "new").ref is None
    check(game)

    for target in (outside / "h.png", None):
        game = S(tmp_path, studio_game, f"file link {target is None}")
        room = game / "images" / "bg" / "room.png"
        link = game / "images" / "hana" / ("happy.png" if target else "alias.png")
        if target:
            link.unlink()
        if not try_link_file(link, target or room):
            continue
        paths = paths_of(game)
        ref = f"images/hana/{link.name}"
        replace = files.run_add(paths, files.plan_add(
            paths, "images", "images/hana", [source(tmp_path / "s2", link.name,
                                                    png(9, 9))])[0], "replace")
        assert replace.ref is None
        assert isinstance(files.rename_file(paths, ref, "other.png"), files.Refusal)
        assert isinstance(files.delete_file(paths, ref), files.Refusal)
        assert os.path.islink(link) and room.read_bytes() == png(400, 300)
        check(game)

    game = S(tmp_path, studio_game, "planted temp")
    monkeypatch.setattr(files, "_temp_token", lambda: "deadbeef")
    planted = game / "images" / "hana" / ".happy.png.deadbeef.tmp"
    planted_dir = outside / "tdir"
    planted_dir.mkdir()
    if not try_link_file(planted, outside / "t"):
        link_dir(planted, planted_dir)              # Windows without symlinks: a junction
    happy = (game / "images" / "hana" / "happy.png").read_bytes()
    replace = files.run_add(paths_of(game), files.plan_add(
        paths_of(game), "images", "images/hana", [source(tmp_path / "s3", "happy.png",
                                                         png(6, 6))])[0], "replace")
    assert replace.ref is None                      # every try met the planted name
    assert (game / "images" / "hana" / "happy.png").read_bytes() == happy
    assert not (outside / "t").exists() and os.listdir(planted_dir) == []
    monkeypatch.undo()

    game = S(tmp_path, studio_game, "routes junction")
    link_dir(game / "script" / "routes", outside)
    assert isinstance(files.new_script(paths_of(game), "script/routes", "kai.vns"),
                      files.Refusal)
    assert not (outside / "kai.vns").exists()

    game = S(tmp_path, studio_game, "config link")
    (game / "config.toml").unlink()
    if try_link_file(game / "config.toml", outside / "c.toml"):
        assert isinstance(document.open_config(paths_of(game)), document.ScriptError)
    check(game)


# --- AC-F45-23 / TR-F45-05: rename never replaces ------------------------------------------

def test_ac23_rename_never_replaces(tmp_path, studio_game, monkeypatch):
    game = S(tmp_path, studio_game, "race")
    hana = game / "images" / "hana"
    happy = (hana / "happy.png").read_bytes()
    monkeypatch.setattr(files, "_before_act", lambda: (hana / "smile.png").write_bytes(b"B"))
    assert isinstance(files.rename_file(paths_of(game), "images/hana/happy.png",
                                        "smile.png"), files.Refusal)
    assert (hana / "happy.png").read_bytes() == happy and (hana / "smile.png").read_bytes() == b"B"
    monkeypatch.undo()

    if POSIX:
        def no_link(*_a, **_k):
            raise OSError(errno.EPERM, "no hard links")

        for racing in (True, False):
            game = S(tmp_path, studio_game, f"eperm {racing}")
            hana = game / "images" / "hana"
            monkeypatch.setattr(files.os, "link", no_link)
            if racing:
                monkeypatch.setattr(files, "_before_act",
                                    lambda h=hana: (h / "smile.png").write_bytes(b"B"))
            result = files.rename_file(paths_of(game), "images/hana/happy.png", "smile.png")
            assert isinstance(result, files.Refusal) == racing
            assert (hana / "smile.png").read_bytes() == (b"B" if racing else happy)
            monkeypatch.undo()

    game = S(tmp_path, studio_game, "case")
    paths = paths_of(game)
    assert files.rename_file(paths, "images/hana/happy.png", "Happy.png") == \
        "images/hana/Happy.png"
    paths.invalidate_listings()
    assert paths.list_dir("images/hana").files == ("Happy.png",)


# --- AC-F45-24: sources can't hang Studio or exhaust memory --------------------------------

def test_ac24_bad_sources_are_refused_quickly(tmp_path, studio_game):
    game = S(tmp_path, studio_game, "s")
    paths = paths_of(game)
    src = tmp_path / "src"
    (src / "folder.png").mkdir(parents=True)
    rows = [(src / "folder.png", "images", "images")]
    if POSIX:
        os.mkfifo(src / "fifo.png")
        os.symlink(src / "fifo.png", src / "tofifo.png")
        rows += [(src / "fifo.png", "images", "images"), (Path("/dev/zero"), "images", "images"),
                 (src / "tofifo.png", "images", "images")]

    def timed(action):
        box: list = []
        thread = threading.Thread(target=lambda: box.append(action()), daemon=True)
        thread.start()
        thread.join(1.0)
        assert box, "took over 1 s"
        return box[0]

    for path, key, folder in rows:
        plan = timed(lambda: files.plan_add(paths, key, folder, [path])[0])
        assert plan.refusal == f"`{path.name}` is not a regular file.", path
        assert timed(lambda: files.run_add(paths, plan, "new")).ref is None

    caps = {"images": ASSET_MAX_BYTES, "audio": MUSIC_MAX_BYTES,
            "minigames": MINIGAME_FILE_MAX_BYTES, "script": SCRIPT_FILE_MAX_BYTES}
    suffix = {"images": ".png", "audio": ".ogg", "minigames": ".py", "script": ".vns"}
    for key, cap in caps.items():
        group = files.group_by_key(key)
        if not POSIX:                   # NTFS fills a truncated file: cross a patched cap
            group = dataclasses.replace(group, max_bytes=4096)
            cap = group.max_bytes
        big = src / f"big{suffix[key]}"
        with open(big, "wb") as stream:
            stream.truncate(cap + 1)
        plan = files.plan_add(paths, group, key, [big])[0]
        assert plan.refusal is not None and "too large" in plan.refusal, key
        big.unlink()

    grow = source(src, "grow.py", b"#" * MINIGAME_FILE_MAX_BYTES)
    plan = files.plan_add(paths, "minigames", "minigames", [grow])[0]
    assert plan.ok
    with open(grow, "ab") as stream:
        stream.write(b"#" * 10)
    outcome = files.run_add(paths, plan, "new")
    assert outcome.ref is None and "too large" in outcome.reason


# --- AC-F45-25: name clashes ignore case on every OS ----------------------------------------

def test_ac25_clashes_ignore_case(tmp_path, studio_game):
    src = source(tmp_path / "src", "happy.png", png(3, 3))
    game = S(tmp_path, studio_game, "upper")
    hana = game / "images" / "hana"
    (hana / "happy.png").rename(hana / "Happy.png")
    plan = files.plan_add(paths_of(game), "images", "images/hana", [src])[0]
    assert plan.clash == "Happy.png"
    assert files.run_add(paths_of(game), plan, "keep_both").ref == "images/hana/happy_2.png"
    assert files.run_add(paths_of(game), plan, "replace").ref == "images/hana/Happy.png"
    assert sorted(os.listdir(hana)) == ["Happy.png", "happy_2.png"]

    game = S(tmp_path, studio_game, "second")
    (game / "images" / "hana" / "happy_2.PNG").write_bytes(png(1, 1))
    assert add(game, "images", "images/hana", src, "keep_both").ref == "images/hana/happy_3.png"
    assert isinstance(files.new_script(paths_of(game), "script", "CH2.vns"), files.Refusal)
    (game / "images" / "hana" / "smile.png").write_bytes(png(1, 1))
    assert isinstance(files.rename_file(paths_of(game), "images/hana/happy.png", "SMILE.png"),
                      files.Refusal)


# --- AC-F45-26: locked files and a missing game folder --------------------------------------

def test_ac26_locked_files_and_a_missing_game(tmp_path, studio_game, monkeypatch):
    src = source(tmp_path / "src", "happy.png", png(3, 3))
    errors = [PermissionError(errno.EACCES, "x"), OSError(errno.EACCES, "x"),
              OSError(errno.EPERM, "x"), OSError(errno.EROFS, "x")]
    for number, error in enumerate(errors):
        game = S(tmp_path, studio_game, f"e{number}")
        before = sha(game)
        paths = paths_of(game)

        def fail(*_a, e=error, **_k):
            raise e

        plan = files.plan_add(paths, "images", "images/hana", [src])[0]
        with monkeypatch.context() as patch:
            patch.setattr(safefile.os, "replace", fail)
            outcome = files.run_add(paths, plan, "replace")
        assert outcome.reason == ("Couldn't replace `images/hana/happy.png`: the file is "
                                  "read-only or locked.")
        with monkeypatch.context() as patch:
            patch.setattr(files.os, "rename", fail)
            patch.setattr(files.os, "link", fail)
            assert files.rename_file(paths, "images/hana/happy.png", "x.png").text == (
                "Couldn't rename `images/hana/happy.png`: the file is read-only or locked.")
        with monkeypatch.context() as patch:
            patch.setattr(safefile.os, "unlink", fail)
            assert files.delete_file(paths, "images/hana/happy.png").text == (
                "Couldn't delete `images/hana/happy.png`: the file is read-only or locked.")
        assert sha(game) == before and no_temp(game), error

    if os.name == "nt":
        game = S(tmp_path, studio_game, "real lock")
        paths = paths_of(game)
        with open(game / "images" / "hana" / "happy.png", "rb"):
            assert "read-only or locked" in files.rename_file(
                paths, "images/hana/happy.png", "x.png").text
            assert "read-only or locked" in files.delete_file(
                paths, "images/hana/happy.png").text
        assert (game / "images" / "hana" / "happy.png").exists()

    game = S(tmp_path, studio_game, "gone")
    paths = paths_of(game)
    shutil.rmtree(game)
    assert files.project_tree(paths) == files.Refusal(files.GAME_GONE)
    assert files.plan_add(paths, "images", "images", [src])[0].refusal == files.GAME_GONE
    for result in (files.new_script(paths, "script", "x.vns"),
                   files.rename_file(paths, "script/ch2.vns", "y.vns"),
                   files.delete_file(paths, "script/ch2.vns")):
        assert result == files.Refusal(files.GAME_GONE)
    assert not game.exists()


# --- AC-F45-27: config.toml in the editor --------------------------------------------------

def test_ac27_config_toml_saves_exactly(tmp_path, studio_game):
    game = S(tmp_path, studio_game, "s")
    original = b'[game]\r\ntitle = "My Game"\r\nversion = "1"\r\n'
    (game / "config.toml").write_bytes(original)
    doc = document.open_config(paths_of(game))
    assert isinstance(doc, document.ScriptDocument) and doc.config
    text = doc.text
    assert document.encode(doc, text) == original
    document.save(doc, text.replace("My Game", "Our Game"))
    assert (game / "config.toml").read_bytes() == original.replace(b"My Game", b"Our Game")
    assert no_temp(game)


# --- AC-F45-28: new game -------------------------------------------------------------------

def test_ac28_new_game_from_the_starter(tmp_path, monkeypatch):
    name = "Hana's Day ö"
    for folder in (tmp_path / "new" / name, tmp_path / "empty" / name):
        folder.parent.mkdir()
        if "empty" in str(folder.parent):
            folder.mkdir()
        assert files.new_game(folder) == folder.absolute()
        config = tomllib.loads((folder / "config.toml").read_text(encoding="utf-8"))
        assert config["game"] == {"id": slugify(name), "title": name, "version": "0.1.0"}
        main = (folder / "script" / "main.vns").read_text().splitlines()
        assert main[0] == "label start:" and len(main) == 3
        for group in ASSET_GROUPS:
            assert (folder / group.folder).is_dir() and not os.path.isjunction(
                folder / group.folder)
        paths = GamePaths.for_game(folder)
        loaded = load_config(paths)
        assert not loaded.errors and not loaded.warnings
        story = load_story(paths)
        assert not story.errors and not story.warnings

    full = tmp_path / "full"
    full.mkdir()
    (full / "x").write_text("x")
    a_file = tmp_path / "file"
    a_file.write_text("x")
    empty = tmp_path / "target"
    empty.mkdir()
    junction = tmp_path / "junction"
    link_dir(junction, empty)
    for folder in (full, a_file, tmp_path / "no" / "parent", junction):
        before = sorted(os.listdir(tmp_path))
        assert isinstance(files.new_game(folder), files.Refusal), folder
        assert sorted(os.listdir(tmp_path)) == before
    assert os.listdir(empty) == []

    window = pytest.importorskip("engine.tools.editor.window")
    calls = []
    monkeypatch.setattr(window.subprocess, "Popen", lambda argv, **kw: calls.append(argv))
    window.launch_studio(tmp_path / "new" / name)
    assert calls == [[sys.executable, "-m", "engine", "edit", str(tmp_path / "new" / name)]]

"""F48 step S1: ``core/paths.studio_user_dir`` and ``is_plain_name`` (04 §3.3, §7.5;
ADR-0003 §3, §5; 07 I-9; SEC-F48-02). Studio's per-user folder is made 0700, is used only
when it is a real folder, and never belongs to a game; a plain name holds no Cc, Cf, Cs, Zl
or Zp character."""

import os
import stat
import sys
import time
from pathlib import Path

import pytest

from engine.core import paths
from engine.core.paths import (
    STUDIO_DIR_NAME,
    is_plain_name,
    is_valid_app_id,
    studio_user_dir,
)
from tests.tools.editor.conftest import link_dir


@pytest.fixture
def fake_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "qauser7"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return home


def test_studio_folder_is_no_games_folder():
    assert STUDIO_DIR_NAME == "_studio"
    assert not is_valid_app_id(STUDIO_DIR_NAME)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows folders")
def test_windows_roaming_and_local_folders(tmp_path, monkeypatch):
    roaming, local = tmp_path / "Roaming", tmp_path / "Local"
    roaming.mkdir()
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))           # missing: made with its parents
    assert studio_user_dir() == roaming / "vn-engine" / "_studio"
    assert studio_user_dir(local=True) == local / "vn-engine" / "_studio"
    assert (roaming / "vn-engine" / "_studio").is_dir()
    assert (local / "vn-engine" / "_studio").is_dir()
    for value in ("", "relative\\dir", "\\rooted-no-drive"):
        monkeypatch.setenv("APPDATA", value)
        assert studio_user_dir() is None
    monkeypatch.delenv("LOCALAPPDATA")
    assert studio_user_dir(local=True) is None


def test_linux_folder(fake_home, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    expected = fake_home / ".local" / "share" / "vn-engine" / "_studio"
    assert studio_user_dir() == expected == studio_user_dir(local=True)
    assert expected.is_dir()
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(expected).st_mode) == 0o700
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
        assert studio_user_dir() == xdg / "vn-engine" / "_studio"
    monkeypatch.setenv("XDG_DATA_HOME", "relative/data")       # not absolute: the default
    assert studio_user_dir() == expected


def test_macos_folder(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    expected = fake_home / "Library" / "Application Support" / "vn-engine" / "_studio"
    assert studio_user_dir() == expected == studio_user_dir(local=True)
    assert expected.is_dir()


def test_no_home_means_no_folder(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(paths, "home_dir", lambda: None)
    assert studio_user_dir() is None


def test_i9_the_folder_must_be_real(fake_home, monkeypatch, tmp_path):
    """07 I-9: None unless ``_studio`` is a real folder: a link (or junction) there, or a
    file, gives None and nothing is written through it."""
    monkeypatch.setattr(sys, "platform", "linux")
    parent = fake_home / ".local" / "share" / "vn-engine"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link_dir(parent / "_studio", outside)
    assert studio_user_dir() is None
    assert list(outside.iterdir()) == []
    os.rmdir(parent / "_studio") if os.name == "nt" else os.unlink(parent / "_studio")
    (parent / "_studio").write_bytes(b"x")
    assert studio_user_dir() is None


def test_a_link_above_the_root_only_locates_it(fake_home, monkeypatch, tmp_path):
    """ADR-0003 §5: a link at or above the per-user root (``vn-engine`` moved elsewhere) is
    followed; only ``_studio`` itself must be real."""
    monkeypatch.setattr(sys, "platform", "linux")
    share = fake_home / ".local" / "share"
    share.mkdir(parents=True)
    moved = tmp_path / "moved"
    moved.mkdir()
    link_dir(share / "vn-engine", moved)
    assert studio_user_dir() == share / "vn-engine" / "_studio"
    assert (moved / "_studio").is_dir()


def test_i9_stale_temps_are_cleaned(fake_home, monkeypatch):
    """07 I-9 (ADR-0003 §5): stale temps of Studio's own files over 60 s old go; young ones,
    other names, and the files themselves stay."""
    monkeypatch.setattr(sys, "platform", "linux")
    folder = studio_user_dir()
    old = time.time() - 120
    stale = [".assistant.json.0123abcd.tmp", ".key-0123456789abcdef.txt.89abcdef.tmp"]
    kept = [".assistant.json.fedcba98.tmp", ".notes.txt.0123abcd.tmp", "assistant.json",
            ".key-short.txt.0123abcd.tmp"]
    for name in stale + kept:
        (folder / name).write_bytes(b"x")
    for name in stale + kept[1:]:
        os.utime(folder / name, (old, old))
    assert studio_user_dir() == folder
    assert sorted(p.name for p in folder.iterdir()) == sorted(kept)


@pytest.mark.parametrize("name", [
    "ch1.vns", "script/route a/ch2.vns", "日本語.vns", "café.vns", "a b.vns"])
def test_plain_names(name):
    assert is_plain_name(name)


@pytest.mark.parametrize("name", [
    "a\x00.vns", "a\t.vns", "a\x85.vns", "a\x9f.vns",           # Cc, C1 included
    "a​.vns", "a‏.vns", "‮gnp.vns", "a⁦.vns", "a﻿.vns",   # Cf
    "a\ud800.vns",                                                # Cs
    "a .vns", "a .vns",                                 # Zl, Zp
    None, 5, b"a.vns", ["a.vns"]])
def test_names_that_arent_plain(name):
    assert not is_plain_name(name)

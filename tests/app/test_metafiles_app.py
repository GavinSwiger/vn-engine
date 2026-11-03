"""F31 s4 in the real app — **App M** (06 §0.3: in-process ``launch()``, hidden window, fake
clock, unthreaded writer unless stated, game copy at ``tmp_path/aiko/game``): AC-F31-17
(windowed equals headless, on disk), AC-F31-22 (who touches the disk, and when), and AC-F31-23
(names and fixed words only). The step 4 milestone: the windowed game writes and deletes
``<game>/characters/hana.chr``.
"""

import errno
import logging
import os
import shutil
import sys
from pathlib import Path

import pygame
import pytest

from engine.app.dispatch import CommandRouter
from engine.app.metafiles import DiskFolder
from engine.core import safefile
from engine.core.paths import GamePaths
from engine.persist.writer import META, Failed, FileRemove, FileWrite, Writer
from engine.runtime.commands import MetaDelete, MetaWrite, Say
from engine.runtime.metafiles import MemoryFolder
from engine.ui.builtin.error import ErrorScreen
from tests.app.test_saves_service import launch, line_text, play, unthreaded, wait
from tests.fakes.loop import post_key
from tests.runtime.metafiles_story import F31, HANA, fixture, run_h

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]

NOTE = "Line one\nNoteMark7 {b}x{/b} {{".encode("utf-8")
PLAY = "\n[title]\nenabled = false\n\n[saves]\nautosave_quit = false\n"


def game_copy(tmp_path: Path, name: str = "walk", script: str | None = None) -> Path:
    """``tests/fixtures/F31/<name>/`` at ``tmp_path/aiko/game`` (06 §0.3), playing at once."""
    game = tmp_path / "aiko" / "game"
    shutil.copytree(F31 / name, game)
    with (game / "config.toml").open("a", encoding="utf-8") as config:
        config.write(PLAY)
    if script is not None:
        (game / "script" / "main.vns").write_text(script, encoding="utf-8")
    return game


@pytest.fixture
def spies(monkeypatch):
    """Every command the router dispatches, and every meta writer job submitted."""
    seen: dict[str, list] = {"commands": [], "jobs": []}
    real_dispatch, real_submit = CommandRouter.dispatch, Writer._submit

    def dispatch(self, command):
        seen["commands"].append(command)
        return real_dispatch(self, command)

    def submit(self, client, job):
        if client.owner == META:
            seen["jobs"].append(job)
        return real_submit(self, client, job)
    monkeypatch.setattr(CommandRouter, "dispatch", dispatch)
    monkeypatch.setattr(Writer, "_submit", submit)
    return seen


def advance_to(app, prefix: str):
    while not (line_text(app) or "").startswith(prefix):
        post_key(pygame.K_SPACE)
        yield
        yield


def _story(commands: list) -> list:
    """The story's own commands: lines (text and wait ids) and the meta records."""
    return [(type(c).__name__, getattr(c, "sid", None), getattr(c, "text", None))
            if type(c) is Say else c for c in commands if type(c) in (Say, MetaWrite, MetaDelete)]


def _warnings(caplog, area: str = "vn.runtime") -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING and r.name == area]


# --- AC-F31-17 ----------------------------------------------------------------------------------

def test_ac_f31_17_on_disk_windowed_equals_headless(tmp_path, scripted_app, unthreaded, spies,
                                                    caplog, user_roots):
    game = game_copy(tmp_path)
    root = game / "characters"

    def script(app, out):
        yield from advance_to(app, "W1")                              # after line 7
        out["w1"] = {p.name: p.read_bytes() for p in root.iterdir()}
        yield from advance_to(app, "W5")
        out["disk"] = app.metafiles is not None and type(app.metafiles) is DiskFolder

    with caplog.at_level(logging.DEBUG, logger="vn"):
        out = play(scripted_app, script)
        assert launch(game) == 0
    headless = run_h(fixture("walk"), files=MemoryFolder(originals={"hana.chr": HANA}))
    assert _story(spies["commands"]) == _story(headless)
    assert out["disk"] and out["w1"] == {"hana.chr": HANA, "read_me.txt": NOTE}
    assert sorted(p.name for p in root.iterdir()) == ["read_me.txt"]   # no temp
    assert (root / "read_me.txt").read_bytes() == NOTE
    assert _warnings(caplog) == []

    # A release launch gives the same; read_me.txt pre-filled with 1 KiB of z is replaced.
    (root / "read_me.txt").write_bytes(b"z" * 1024)
    spies["commands"].clear()
    spies["jobs"].clear()
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="vn"):
        play(scripted_app, script)
        assert launch(game, release=True) == 0
    assert _story(spies["commands"]) == _story(headless)
    assert sorted(p.name for p in root.iterdir()) == ["read_me.txt"]
    assert (root / "read_me.txt").read_bytes() == NOTE
    assert len(spies["jobs"]) == 4 and all(j.release is False for j in spies["jobs"])
    assert [type(j) for j in spies["jobs"]] == [FileWrite, FileWrite, FileRemove, FileRemove]


# --- AC-F31-22 ----------------------------------------------------------------------------------

def _by_engine() -> bool:
    """The call isn't the test suite's own folder guard (``tests/fakes/meta_guard.py``)."""
    frame = sys._getframe(2)
    while frame is not None:
        if frame.f_code.co_filename.endswith("meta_guard.py"):
            return False
        frame = frame.f_back
    return True


class _PathRecorder:
    """TR-F31-03's os recorder, on every thread: each path call under ``root``, and any
    call on the root itself but the load's ``realpath`` (SEC-F02-11's overlap check)."""

    NAMES = ("stat", "lstat", "open", "listdir", "scandir", "replace", "remove", "unlink",
             "mkdir", "rename", "rmdir", "utime")

    def __init__(self, monkeypatch, root: Path) -> None:
        self.calls: list[str] = []
        key = os.path.normcase(str(root))

        def wrap(real, name):
            def spy_call(*args, **kwargs):
                if args and isinstance(args[0], (str, os.PathLike)) and _by_engine():
                    path = os.path.normcase(os.fspath(args[0]))
                    if path.startswith(key + os.sep):
                        self.calls.append(f"{name} {path[len(key):]}")
                    elif path == key and name != "realpath":    # F02's write-root overlap
                        self.calls.append(f"{name} <root>")    # check resolves the root
                return real(*args, **kwargs)
            return spy_call
        for name in self.NAMES:
            monkeypatch.setattr(os, name, wrap(getattr(os, name), name))
        monkeypatch.setattr(os.path, "realpath", wrap(os.path.realpath, "realpath"))
        import builtins
        monkeypatch.setattr(builtins, "open", wrap(builtins.open, "open()"))


def test_ac_f31_22_who_touches_the_disk_and_when(tmp_path, scripted_app, unthreaded, spies,
                                                 monkeypatch, user_roots):
    game = game_copy(tmp_path)
    root = game.resolve() / "characters"
    root.mkdir()
    (root / "hana.chr").write_bytes(b"mine")
    (root / "junk.txt").write_bytes(b"junk")
    built: list[object] = []
    real_init = DiskFolder.__init__

    def init(self, *args, **kwargs):
        built.append(self)
        real_init(self, *args, **kwargs)
    monkeypatch.setattr(DiskFolder, "__init__", init)

    # Run H and the in-process check: no DiskFolder, no call; file exists gives False.
    recorder = _PathRecorder(monkeypatch, root)
    from tests.runtime.effects_story import load_game
    program = load_game(game)
    commands = run_h(program)
    assert MetaWrite("hana.chr") in commands                         # written, in memory
    assert MemoryFolder().exists("hana.chr") is False                 # the disk's isn't seen
    from engine.tools.check import CheckJob                         # vn check, in process
    events: list[dict] = []
    CheckJob(GamePaths(game.resolve()), events.append).run()
    assert events and events[-1].get("type", events[-1].get("event")) is not None
    assert built == [] and recorder.calls == []

    # App M: launch, play up to W0, quit: nothing under characters/, no cleanup.
    def to_w0(app, out):
        yield from wait(lambda: (line_text(app) or "").startswith("W0"))
        out["client"] = META in app.writer._clients
    out = play(scripted_app, to_w0)
    assert launch(game) == 0
    assert out["client"] and len(built) == 1 and recorder.calls == []
    assert sorted(p.name for p in root.iterdir()) == ["hana.chr", "junk.txt"]

    # nofile/: no file line → no meta client.
    nofile = tmp_path / "nofile"
    nofile.mkdir()
    plain = game_copy(nofile, script='label start:\n    "N0"\n    return\n')

    def to_n0(app, out):
        yield from wait(lambda: line_text(app) == "N0")
        out["client"] = META in app.writer._clients
        out["metafiles"] = app.metafiles
    out = play(scripted_app, to_n0)
    assert launch(plain) == 0
    assert out == {"done": True, "frame": out["frame"], "client": False, "metafiles": None}


# --- AC-F31-23 ----------------------------------------------------------------------------------

PRIVACY = '''define hana = Character("Hana")
default answer = None
default here = False
label start:
    "P0"
    file write "hana.chr" "ok"
    file write "full.txt" "NoteMark7 full"
    file write "perm.txt" "NoteMark7 perm"
    file delete "gone.chr"
    file write "big.chr"
    file read "big.txt" into answer
    file read "linked.txt" into answer
    file read "answer.txt" into answer
    if answer.endswith("yes"):
        "P1 yes {var=answer}"
    else:
        "P1 no"
    file exists "hana.chr" into here
    "P2"
'''


def test_ac_f31_23_names_and_fixed_words_only(tmp_path, scripted_app, unthreaded, monkeypatch,
                                              caplog, capfd, user_roots):
    game = game_copy(tmp_path, script=PRIVACY)
    (game / "files" / "big.chr").write_bytes(b"original")
    root = game / "characters"
    root.mkdir()
    (root / "answer.txt").write_bytes(b"NoteMark7 yes")
    (root / "big.txt").write_bytes(b"b" * 16_385)
    (root / "gone.chr").mkdir()                                       # folder_at_name
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"NoteMark7 secret")
    os.link(outside / "secret.txt", root / "linked.txt")
    real_write = safefile.write_atomic

    def write_atomic(target, pieces, **kw):                           # the fault seam
        codes = {"full.txt": errno.ENOSPC, "perm.txt": errno.EACCES}
        code = codes.get(Path(target).name)
        if code is not None:
            raise OSError(code, f"{Path(target).resolve()} NoteMark7")
        return real_write(target, pieces, **kw)
    monkeypatch.setattr(safefile, "write_atomic", write_atomic)

    # Failed.detail for owner meta is never read (an access-recording descriptor).
    slot = Failed.__dict__["detail"]
    read_ids: list[int] = []

    class Recording:
        def __get__(self, obj, owner=None):
            if obj is not None:
                read_ids.append(id(obj))
            return slot.__get__(obj, owner)

        def __set__(self, obj, value):
            slot.__set__(obj, value)
    monkeypatch.setattr(Failed, "detail", Recording())
    meta_results: list[int] = []
    real_result = DiskFolder._result

    def result(self, res):
        meta_results.append(id(res))
        return real_result(self, res)
    monkeypatch.setattr(DiskFolder, "_result", result)

    def script(app, out):
        yield from wait(lambda: line_text(app) == "P0")
        (game / "files" / "big.chr").unlink()                         # original_missing
        yield from advance_to(app, "P1")
        out["p1"] = line_text(app)
        # W196: characters/ becomes a file before the last check.
        root.rename(game / "moved")
        root.write_bytes(b"x")
        yield from advance_to(app, "P2")
        out["error"] = any(isinstance(s, ErrorScreen) for s in app.screens._stack) \
            if hasattr(app.screens, "_stack") else isinstance(app.screens.top, ErrorScreen)
        out["reprs"] = [repr(app.metafiles), repr(app.metafiles.folder),
                        repr(app.story.interp.files), repr(MemoryFolder()),
                        repr(MetaWrite("hana.chr")), repr(MetaDelete("hana.chr"))]

    with caplog.at_level(logging.DEBUG, logger="vn"):
        out = play(scripted_app, script)
        assert launch(game) == 0
    found = _warnings(caplog)
    shown = "<game>/characters/"
    assert out["p1"].startswith("P1 yes") and out["error"] is False
    assert any("full" in w or "disk is full" in w for w in found), found
    want = {"full.txt": "the disk is full", "perm.txt": "no permission",
            "gone.chr": "isn't a file", "big.chr": "files/ is gone"}
    for name, words in want.items():
        assert any(f"{shown}{name}" in w and words in w for w in found), (name, found)
    assert any('"big.txt"' in w for w in found) and any('"linked.txt"' in w for w in found)
    assert any(w.startswith(shown.rstrip("/")) and "isn't a real folder" in w for w in found)
    texts = [r.getMessage() for r in caplog.records]
    logs = [p.read_text(encoding="utf-8", errors="replace")
            for p in (game / "logs").rglob("*") if p.is_file()]
    std = capfd.readouterr()
    absolute = str(tmp_path.resolve())
    for text in texts + logs + [std.out, std.err]:
        assert "NoteMark7" not in text and "aiko" not in text and absolute not in text, text[:300]
    for text in out["reprs"]:
        assert "aiko" not in text and "\\" not in text and "NoteMark7" not in text, text
    assert not set(read_ids) & set(meta_results)
    assert (outside / "secret.txt").read_bytes() == b"NoteMark7 secret"

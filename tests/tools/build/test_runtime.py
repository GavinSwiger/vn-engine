"""F66: the player runtime: copying it into a build, which runtime a build uses (Studio's
bundled one, the developer cache, or none yet; ``player``), and making one (``runtime``,
PyInstaller faked)."""

import json
import os
from pathlib import Path

import pytest

from engine.core import paths
from engine.tools.build import player, procs, runtime, spec
from tests.tools.build.test_command import FakeProc, make_fake_runtime


def tree_of(folder: Path) -> dict[str, bytes | None]:
    return {p.relative_to(folder).as_posix(): (p.read_bytes() if p.is_file() else None)
            for p in sorted(folder.rglob("*"))}


def test_copy_runtime_renames_the_exe_and_leaves_out_meta_and_network(tmp_path):
    source = make_fake_runtime(tmp_path / "runtime")
    (source / "_internal" / "libcrypto-3.dll").write_bytes(b"ssl")
    (source / "_internal" / "engine" / "data").mkdir(parents=True)
    (source / "_internal" / "engine" / "data" / "icon.png").write_bytes(b"png")
    plain, network = tmp_path / "plain", tmp_path / "network"
    for dest in (plain, network):
        (dest / "game").mkdir(parents=True)
        (dest / "game" / "config.toml").write_bytes(b"[game]")

    runtime.copy_runtime(source, plain, "My Game.exe", keep_network=False)
    runtime.copy_runtime(source, network, "My Game.exe", keep_network=True)

    got = tree_of(plain)
    assert got["My Game.exe"] == b"MZ fake exe" and got["game/config.toml"] == b"[game]"
    assert "player.exe" not in got and player.META_NAME not in got
    assert got["_internal/engine/data/icon.png"] == b"png"
    assert got["licenses/vn-engine.txt"] == b"x\r\n"
    assert "_internal/_ssl.pyd" not in got and "_internal/libcrypto-3.dll" not in got
    assert got["_internal/pygame/SDL2.dll"] == b"dll"
    assert set(tree_of(network)) - set(got) == {"_internal/_ssl.pyd",
                                                "_internal/libcrypto-3.dll"}
    with pytest.raises(FileExistsError):                      # never over existing files
        runtime.copy_runtime(source, plain, "My Game.exe", keep_network=False)


def test_read_meta_needs_the_whole_shape(tmp_path):
    folder = make_fake_runtime(tmp_path / "runtime")
    assert player.read_meta(folder)["key"] == "k"
    (folder / player.META_NAME).write_text('{"format": 99, "key": "k"}', encoding="utf-8")
    assert player.read_meta(folder) is None
    other = make_fake_runtime(tmp_path / "other")
    (other / "player.exe").unlink()
    assert player.read_meta(other) is None
    assert player.read_meta(tmp_path / "missing") is None


@pytest.fixture
def cache(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "cache"
    monkeypatch.setattr(player, "cache_root", lambda: root)
    monkeypatch.setattr(player, "runtime_key", lambda root=None: "ab" * 32)
    return root


def test_the_runtime_a_build_uses(tmp_path, monkeypatch, cache):
    pyinstaller = [procs.ToolStatus("B_NO_TOOL")]
    monkeypatch.setattr(procs, "tool_status", lambda: pyinstaller[0])
    monkeypatch.delattr(paths, "player_runtime_dir", raising=False)

    # Developer install, nothing cached: PyInstaller decides (it makes the runtime first).
    assert player.find_runtime() is None
    assert player.tool_status().key == "B_NO_TOOL" and player.can_install_tool()
    pyinstaller[0] = procs.ToolStatus(None, procs.PYINSTALLER_VERSION)
    assert player.tool_status().ok

    # A cached runtime for this engine: ready without PyInstaller; another key's isn't used.
    pyinstaller[0] = procs.ToolStatus("B_NO_TOOL")
    stale = make_fake_runtime(cache / ("cd" * 16))
    assert player.find_runtime() is None
    cached = make_fake_runtime(cache / ("ab" * 16))
    (cached / player.META_NAME).write_text(json.dumps(
        {"format": player.RUNTIME_FORMAT, "key": "ab" * 32}), encoding="utf-8")
    assert player.find_runtime() == cached and player.tool_status().ok
    assert stale.is_dir()

    # Studio's app: its bundled player wins; Install build tool is never offered.
    bundled = make_fake_runtime(tmp_path / "Studio" / "player")
    monkeypatch.setattr(paths, "player_runtime_dir", lambda: bundled, raising=False)
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    assert player.find_runtime() == bundled and player.tool_status().ok
    assert not player.can_install_tool()
    assert runtime.ensure_runtime(scratch=tmp_path) == bundled

    # Studio's app without its player: B_NO_RUNTIME, and nothing is built.
    monkeypatch.setattr(paths, "player_runtime_dir", lambda: None, raising=False)
    assert player.find_runtime() is None
    assert player.tool_status().key == player.NO_RUNTIME
    assert not player.can_install_tool()
    with pytest.raises(runtime.RuntimeBuildError):
        runtime.ensure_runtime(scratch=tmp_path)


def test_ensure_runtime_builds_once_into_the_cache_and_prunes(tmp_path, monkeypatch, cache):
    monkeypatch.delattr(paths, "player_runtime_dir", raising=False)
    built: list[Path] = []

    def fake_build(out_dir, *, popen=None, started=None, root=None):
        built.append(out_dir)
        make_fake_runtime(out_dir)
        (out_dir / player.META_NAME).write_text(json.dumps(
            {"format": player.RUNTIME_FORMAT, "key": "ab" * 32}), encoding="utf-8")
        return out_dir

    monkeypatch.setattr(runtime, "build_player_runtime", fake_build)
    old = make_fake_runtime(cache / ("cd" * 16))               # an older engine's runtime
    (cache / "notes").mkdir()                                  # not a runtime: kept
    first = runtime.ensure_runtime(scratch=tmp_path)
    assert first == cache / ("ab" * 16) and len(built) == 1
    assert built[0].parent == cache and built[0].name.startswith(".")
    assert not old.exists() and (cache / "notes").is_dir()
    assert runtime.ensure_runtime(scratch=tmp_path) == first and len(built) == 1

    # No cache folder: made in the caller's scratch folder, every time.
    monkeypatch.setattr(player, "cache_root", lambda: None)
    scratch = tmp_path / "staging"
    scratch.mkdir()
    assert runtime.ensure_runtime(scratch=scratch) == scratch / player.CACHE_DIR


def test_build_player_runtime_with_a_fake_packer(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "_engine_ico", lambda: b"ICO")
    calls = []

    def popen(argv, **kwargs):
        calls.append(argv)
        assert kwargs["shell"] is False and kwargs["cwd"] == str(paths.engine_root())
        assert not {k.upper() for k in kwargs["env"]} & procs.PROVIDER_KEY_VARS
        work = Path(argv[argv.index("--distpath") + 1]).parent
        app = work / procs.DIST_DIR / spec.COLLECT_NAME
        (app / "_internal").mkdir(parents=True)
        (app / runtime.PLAYER_EXE).write_bytes(b"MZ")
        (app / "_internal" / "python312.dll").write_bytes(b"dll")
        return FakeProc([b"INFO: done"], 0)

    started = []
    out = runtime.build_player_runtime(tmp_path / "player", popen=popen,
                                       started=started.append)
    assert out == tmp_path / "player" and len(started) == 1
    assert calls[0][1:5] == ["-E", "-B", "-m", "PyInstaller"]
    meta = player.read_meta(out)
    assert meta["key"] == player.runtime_key() and meta["exe"] == runtime.PLAYER_EXE
    assert {"vn-engine.txt", "Python.txt", "PyInstaller.txt"} <= set(os.listdir(out / "licenses"))
    assert sorted(os.listdir(tmp_path)) == ["player"]          # the work folder is gone

    # A failed PyInstaller run: its lines, nothing left behind.
    def failing(argv, **kwargs):
        return FakeProc([b"ERROR: boom"], 1)

    with pytest.raises(runtime.RuntimeBuildError) as raised:
        runtime.build_player_runtime(tmp_path / "again", popen=failing)
    assert raised.value.lines == ["ERROR: boom"]
    assert sorted(os.listdir(tmp_path)) == ["player"]
    with pytest.raises(FileExistsError):                        # never into a full folder
        runtime.build_player_runtime(out, popen=popen)


def test_runtime_key_follows_what_the_runtime_is_made_of(tmp_path):
    root = tmp_path / "repo"
    for ref, data in {"main.py": "x", "engine/__init__.py": "", "engine/core/a.py": "a",
                      "engine/tools/build/spec.py": "s", "engine/tools/editor/e.py": "e",
                      "engine/data/icon.png": "i", "engine/data/fonts/f.ttf": "f",
                      "engine/data/sample/s.vns": "s"}.items():
        (root / ref).parent.mkdir(parents=True, exist_ok=True)
        (root / ref).write_text(data, encoding="utf-8")
    key = player.runtime_key(root)
    for ref in ("engine/tools/editor/e.py", "engine/data/sample/s.vns"):   # not shipped
        (root / ref).write_text("changed", encoding="utf-8")
        assert player.runtime_key(root) == key
    for ref in ("engine/core/a.py", "engine/tools/build/spec.py", "main.py",
                "engine/data/fonts/f.ttf"):
        (root / ref).write_text("changed " + ref, encoding="utf-8")
        assert player.runtime_key(root) != key
        key = player.runtime_key(root)


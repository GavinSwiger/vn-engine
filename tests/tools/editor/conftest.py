"""Shared fixtures for the editor's headless tests: game R of F44 ``06-acceptance.md`` §4,
built in ``tmp_path``, an ``outside`` folder beside it, and link helpers.

Under pytest-xdist every ``tk``-marked test gets ``xdist_group("tk")``, so ``--dist
loadgroup`` runs them all on one worker, one at a time: two Tk windows on different workers
compete for the keyboard focus, and focus-dependent tests then fail at random. This mirrors
``tests/audio/mixer/conftest.py``'s ``mixer`` group (with its pytest 9.2 node-id rename)."""

import os
from pathlib import Path

import pytest


@pytest.hookimpl(tryfirst=True)                  # before xdist's loadgroup reads the marks
def pytest_collection_modifyitems(config, items):
    """``xdist_group("tk")`` on every ``tk``-marked test (a session hook: it sees all
    collected items, not only this folder's). Grouping only; nothing is skipped here."""
    if not config.pluginmanager.hasplugin("xdist"):
        return                                   # the mark is xdist's (unknown without it)
    group = pytest.mark.xdist_group("tk")
    loadgroup = config.getvalue("loadgroup") if hasattr(config.option, "loadgroup") else False
    for item in items:
        if item.get_closest_marker("tk") and not item.get_closest_marker("xdist_group"):
            item.add_marker(group)
            if loadgroup and "@" not in item.nodeid and hasattr(item, "_id"):
                # xdist 3.8 groups by renaming ``item._nodeid`` to ``<id>@<group>``; pytest 9.2
                # derives ``nodeid`` from ``item._id``, so that rename has no effect and the
                # group is silently ignored. Do xdist's rename the pytest 9 way.
                item._id = type(item._id).parse(f"{item.nodeid}@tk")

R_SCRIPTS: dict[str, str] = {
    "main.vns": (
        'include "chapter2.vns"\n'
        'include "routes/hana.vns"\n'
        'define sayori = Character("Sayori", color="#f4a6c6")\n'
        "default trust = 0\n"
        "label start:\n"
        '    "Opening line."\n'
        "    jump club_poem\n"),
    "chapter2.vns": (
        "default sayo_points = 0\n"
        "default max_pts = sayo_points + 3\n"
        "default seen = []\n"
        "define wish_cost = 3\n"
        "# Chapter 2\n"
        "label club_poem:\n"
        '    $ seen.append("poem")\n'
        "    if sayo_points >= 1:\n"
        '        sayori "You wrote a poem? Let me see!"\n'
        "    else:\n"
        '        sayori "It\'s {b}nice{/b}."\n'
        '    "Done."\n'),
    "routes/hana.vns": 'label hana_route:\n    "Hana\'s route."\n',
    "chapter3.vns": 'label late_scene:\n    "Late."\n',
}


@pytest.fixture(autouse=True)
def _game_opens_where_it_always_did(monkeypatch):
    """Play in tests adds no "beside Studio" spot and never moves Studio (proposal 2.3);
    ``test_studio_gamebeside`` turns it back on."""
    from engine.tools.editor import gamebeside
    monkeypatch.setattr(gamebeside, "PLACES", False)


@pytest.fixture
def route_game(tmp_path) -> Path:
    """Game R: ``<tmp>/my_game`` with its four scripts (UTF-8, LF, no BOM)."""
    game = tmp_path / "my_game"
    script = game / "script"
    for ref, text in R_SCRIPTS.items():
        path = script / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    (game / "config.toml").write_bytes(b'[game]\ntitle = "My Game"\n')
    return game


@pytest.fixture
def outside(tmp_path) -> Path:
    """``<tmp>/outside``, a folder beside the game."""
    folder = tmp_path / "outside"
    folder.mkdir()
    return folder


def link_dir(link: Path, target: Path) -> None:
    """A directory link at ``link``: a junction on Windows, a symlink elsewhere. Skips the
    test where the system doesn't allow it."""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory links not permitted here: {exc}")


def link_file(link: Path, target: Path) -> None:
    """A file symlink at ``link``; skips the test where symlinks aren't permitted."""
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlinks not permitted here: {exc}")


def files_under(folder: Path) -> set[str]:
    """Every entry under ``folder``, as paths relative to it (links not followed)."""
    found = set()
    for root, dirs, files in os.walk(folder):
        for name in dirs + files:
            found.add(os.path.relpath(os.path.join(root, name), folder).replace(os.sep, "/"))
    return found


# --- F45 game S (F45 ``06`` §5), built in ``tmp_path`` --------------------------------------

S_SCRIPTS: dict[str, str] = {
    "main.vns": ('include "ch2.vns"\n'
                 'define hana = Character("Hana")\n'
                 "default trust = 0\n"
                 "label start:\n"
                 "    show hana happy\n"
                 '    hana "Hi."\n'
                 "    call club\n"
                 "    jump bridge\n"),
    "ch2.vns": ("label club:\n"
                "    menu:\n"
                '        "Go to the river":\n'
                "            jump river\n"
                '        "Stay":\n'
                '            "You stay."\n'
                "    return\n"
                "label bridge:\n"
                '    "The bridge."\n'
                "label river:\n"
                '    "The river."\n'
                "label side:\n"
                '    "Unreached."\n'),
}


def png(width: int, height: int) -> bytes:
    """A PNG signature and IHDR declaring ``width``×``height`` (headers only: enough for
    ``image_dimensions``)."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")


def ogg() -> bytes:
    """The smallest bytes F08's sniff takes as Ogg Vorbis: one page whose first packet
    starts ``\x01vorbis``."""
    packet = b"\x01vorbis" + bytes(22)
    return (b"OggS" + bytes([0, 2]) + bytes(8) + bytes(4) + bytes(4) + bytes(4)
            + bytes([1, len(packet)]) + packet)


@pytest.fixture
def studio_game(tmp_path) -> Path:
    """Game S: ``<tmp>/my_game`` with two scripts, four images (one GIF), one song, one GUI
    image, an empty ``fonts/`` and no ``minigames/``."""
    game = tmp_path / "my_game"
    files = {f"script/{name}": text.encode("utf-8") for name, text in S_SCRIPTS.items()}
    files.update({
        "config.toml": b'[game]\ntitle = "My Game"\n',
        "images/hana/happy.png": png(2, 2),
        "images/bg/room.png": png(400, 300),
        "images/bg/sky.gif": b"GIF89a\x0a\x00\x0a\x00\x00\x00\x00;",
        "images/bg/photo.jpg": b"\xff\xd8\xff\xd9",
        "audio/bgm/theme.ogg": ogg(),
        "gui/button.png": png(4, 4),
    })
    for ref, data in files.items():
        path = game / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (game / "fonts").mkdir()
    return game


def try_link_file(link: Path, target: Path) -> bool:
    """A file symlink, or False where the system doesn't allow one (that row is skipped)."""
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        return False
    return True


# window.py's split (F47 04 §3.4): a name tests patch may live in any of Studio's modules.
STUDIO_MODULES = ("window", "fileactions", "checkwiring", "runwiring", "mapwiring", "database",
                  "dbcleanup",
                  "animpanel",
                  "dbmore", "dbmeters", "dbgallery", "dbextras", "dbreplays", "dbachievements", "dbcontacts", "studiomenus", "editorkeys", "settingsview",
                  "editormenu", "paletteimport")


def patch_studio(monkeypatch, name: str, value) -> None:
    """``monkeypatch.setattr`` ``name`` in every Studio module that has it (a dialog
    function, a constant, a module); at least one must."""
    import importlib
    found = False
    for module_name in STUDIO_MODULES:
        module = importlib.import_module(f"engine.tools.editor.{module_name}")
        if hasattr(module, name):
            monkeypatch.setattr(module, name, value)
            found = True
    assert found, f"no Studio module has {name!r}"

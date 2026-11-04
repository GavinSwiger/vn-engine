"""F48 step S3: the overlay can add a file (04 §7.3; SEC-F48-02; 05 §10 "§7.3", AB-03's
child rows; 07 §2.3). A header entry with ``"new": true`` (``v`` stays 1) names a file that
doesn't exist yet: ``read_overlay`` allows at most 8 plain ``script/….vns`` refs,
``check_added`` re-checks SEC-F48-02 in the child, and ``OverlayPaths`` serves the file from
memory and lists it. Nothing touches disk, and a new file never stands in for an existing
one. Studio today never sends ``new``: ``encode_overlay(files)`` is byte-identical."""

import io
import json
import os
import subprocess

import pytest

from engine.core.editorreport import OVERLAY_MAX_NEW
from engine.core.errors import AssetTooLarge
from engine.core.paths import GamePaths, engine_root
from engine.script.limits import SCRIPT_FILE_MAX_BYTES
from engine.tools.check import Overlay, OverlayError, OverlayPaths, read_overlay
from engine.tools.editor.checker import check_argv, decode_check_line, encode_overlay
from tests.tools.editor.conftest import link_dir
from tests.tools.f45_games import result_of, run_job, studio, tree

SIDE = b'label aside:\n    "Aside."\n    jump nowhere\n'


class Counting(io.BytesIO):
    """A stream that counts every byte it gives."""

    given = 0

    def read(self, size=-1):
        data = super().read(size)
        self.given += len(data)
        return data

    def readline(self, size=-1):
        data = super().readline(size)
        self.given += len(data)
        return data


def header(files: list[dict]) -> bytes:
    return json.dumps({"v": 1, "files": files}).encode("ascii") + b"\n"


def new(ref: str, size: int = 0, flag: object = True) -> dict:
    return {"ref": ref, "size": size, "new": flag}


# --- encode_overlay and read_overlay ----------------------------------------------------------

def test_without_added_the_overlay_is_unchanged():
    data = b"label x:\n"
    assert encode_overlay([("script/ch2.vns", data)]) == (
        b'{"v":1,"files":[{"ref":"script/ch2.vns","size":9}]}\n' + data)
    assert encode_overlay([("script/ch2.vns", data)], added=()) == \
        encode_overlay([("script/ch2.vns", data)])
    read = read_overlay(io.BytesIO(encode_overlay([("script/ch2.vns", data)])))
    assert read == {"script/ch2.vns": data} and read.added == frozenset()


def test_added_files_round_trip():
    files = [("script/main.vns", b'include "side.vns"\n'), ("script/side.vns", SIDE),
             ("config.toml", b"[game]\n")]
    data = encode_overlay(files, added=("script/side.vns",))
    assert data.split(b"\n", 1)[0] == (
        b'{"v":1,"files":[{"ref":"script/main.vns","size":19},'
        b'{"ref":"script/side.vns","size":43,"new":true},{"ref":"config.toml","size":7}]}')
    read = read_overlay(Counting(data))
    assert isinstance(read, Overlay) and read == dict(files)
    assert read.added == {"script/side.vns"}

    # At most OVERLAY_MAX_NEW new files; an added ref must be one of the files.
    many = [(f"script/n{i}.vns", b"") for i in range(OVERLAY_MAX_NEW + 1)]
    assert encode_overlay(many, added=[ref for ref, _ in many[:-1]]) is not None
    assert encode_overlay(many, added=[ref for ref, _ in many]) is None
    with pytest.raises(ValueError):
        encode_overlay(files, added=("script/other.vns",))


BAD_NEW = [
    [new("script/a.vns", flag=False)],
    [new("script/a.vns", flag=1)],
    [new("script/a.vns", flag="true")],
    [new("script/a.vns", flag=None)],
    [new("config.toml")],
    [new("script/\u202egnp.vns")],                    # Cf: bidi override
    [new("script/a\u200b.vns")],                      # Cf: zero width
    [new("script/a\x85.vns")],                        # Cc: C1, which check_ref allows
    [new("script/a\u2028.vns")],                      # Zl
    [new("script/con.vns")],                          # check_ref: a device name
    [new("script/a.vns.")],                           # check_ref: trailing dot
    [new("script/x:y.vns")],                          # check_ref: a colon
    [new("images/a.vns")],
    [new(f"script/n{i}.vns") for i in range(OVERLAY_MAX_NEW + 1)],
]


@pytest.mark.parametrize("files", BAD_NEW)
def test_bad_new_entries_are_refused_before_the_body(files):
    data = header(files)
    stream = Counting(data + b"x" * 10)
    with pytest.raises(OverlayError):
        read_overlay(stream)
    assert stream.given <= len(data)


# --- check_added: SEC-F48-02 again in the child (AB-03) ----------------------------------------

def _overlay(game, added: dict[str, bytes], changed: dict[str, bytes] | None = None
             ) -> OverlayPaths:
    """``added`` as new files, plus ``changed`` existing ones."""
    return OverlayPaths(GamePaths.for_game(game).root, overlay={**(changed or {}), **added},
                        added=frozenset(added))


def test_ab_03_check_added_refuses(tmp_path):
    game = studio(tmp_path)
    script = game / "script"
    (script / "sub").mkdir()
    (script / "sub" / "Taken.vns").write_bytes(b"label taken:\n")
    inside = game / "images" / "bg"
    link_dir(script / "linked", inside)              # a contained junction: still refused
    outside = tmp_path / "outside"
    outside.mkdir()
    link_dir(script / "sub" / "away.vns", outside)   # a link takes its name
    before = tree(game), tree(outside)
    refused = [
        {"script/ch2.vns": SIDE},                        # exists: never stands in for it
        {"script/CH2.vns": SIDE},                        # a case clash
        {"script/sub/taken.vns": SIDE},
        {"script/sub/away.vns": SIDE},
        {"script/nope/x.vns": SIDE},                     # a folder new_script wouldn't make
        {"script/ch2.vns/x.vns": SIDE},                  # the parent is a file
        {"script/linked/x.vns": SIDE},                   # the parent is a link
        {"script/a.vns": SIDE, "script/A.vns": SIDE},    # two new files, one name
        {"images/x.vns": SIDE},                          # not under script/
        {"script/\u202egnp.vns": SIDE},
    ]
    for added in refused:
        with pytest.raises(OverlayError):
            _overlay(game, added).check_added()
    # An added ref that isn't in the overlay at all.
    with pytest.raises(OverlayError):
        OverlayPaths(GamePaths.for_game(game).root, overlay={},
                     added=frozenset({"script/a.vns"})).check_added()
    _overlay(game, {"script/side.vns": SIDE, "script/sub/two.vns": b""}).check_added()
    assert (tree(game), tree(outside)) == before


def test_a_new_file_is_served_from_memory_and_listed(tmp_path):
    game = studio(tmp_path)
    before = tree(game)
    paths = _overlay(game, {"script/side.vns": SIDE})
    paths.check_added()
    real = paths.resolve("script/side.vns")
    assert real == paths.resolve("script") / "side.vns" and not os.path.lexists(real)
    assert paths.read_file("script/side.vns", max_bytes=SCRIPT_FILE_MAX_BYTES) == SIDE
    assert paths.read_file("script/side.vns", max_bytes=1 << 20, regular=True) == SIDE
    with pytest.raises(AssetTooLarge):
        paths.read_file("script/side.vns", max_bytes=len(SIDE) - 1)
    assert paths.file_size("script/side.vns") == len(SIDE)
    assert paths.list_dir("script").files == ("ch2.vns", "main.vns", "side.vns")
    assert paths.list_dir("script/side.vns") is None
    assert GamePaths.for_game(game).list_dir("script").files == ("ch2.vns", "main.vns")
    walk = paths.walk_files("script", suffix=".vns", max_entries=100, max_depth=4)
    assert walk.refs == ("script/ch2.vns", "script/main.vns", "script/side.vns")
    assert tree(game) == before


def test_a_new_file_checks_through_its_include_and_disk_is_unchanged(tmp_path):
    game = studio(tmp_path)
    main = (game / "script" / "main.vns").read_bytes()
    before = tree(game)
    reached = _overlay(game, {"script/side.vns": SIDE}, {"script/main.vns": main.replace(
        b'include "ch2.vns"\n', b'include "ch2.vns"\ninclude "side.vns"\n')})
    reached.check_added()
    result = result_of(run_job(reached, launch=False))
    assert [(i.code, i.file, i.line) for i in result.problems] == [("E43", "script/side.vns", 3)]

    # Not included: never loaded, and reported as not included (W02).
    alone = _overlay(game, {"script/side.vns": SIDE})
    result = result_of(run_job(alone, launch=False))
    assert not [i for i in result.problems if i.code == "E43"]
    assert [i.text for i in result.problems if i.code == "W02"] == [
        'script/side.vns is not included, so it is not part of the game. '
        'Add include "side.vns" to a file that is.']
    assert tree(game) == before


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8:backslashreplace"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def test_the_real_child_adds_a_file_or_exits_2(tmp_path):
    """The child: a good new file is checked (exit 0, its problem reported); a new file that
    exists exits 2 with nothing on stdout. Disk is unchanged either way."""
    game = studio(tmp_path)
    main = (game / "script" / "main.vns").read_bytes().replace(
        b'include "ch2.vns"\n', b'include "ch2.vns"\ninclude "side.vns"\n')
    before = tree(game)
    argv = check_argv(game, launch=False)
    good = encode_overlay([("script/main.vns", main), ("script/side.vns", SIDE)],
                          added=("script/side.vns",))
    proc = subprocess.run(argv, input=good, capture_output=True, timeout=20,
                          cwd=str(engine_root()), env=_env())
    assert proc.returncode == 0, proc.stderr[-2000:]
    events = [decode_check_line(line) for line in proc.stdout.splitlines()]
    problems = [item for kind, payload in events if kind == "problems" for item in payload]
    assert ("E43", "script/side.vns", 3) in {(i.code, i.file, i.line) for i in problems}

    bad = encode_overlay([("script/ch2.vns", SIDE)], added=("script/ch2.vns",))
    proc = subprocess.run(argv, input=bad, capture_output=True, timeout=20,
                          cwd=str(engine_root()), env=_env())
    assert (proc.returncode, proc.stdout) == (2, b"")
    assert b"taken" in proc.stderr
    assert tree(game) == before

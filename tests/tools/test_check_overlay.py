"""The stdin overlay (F45 ``04`` §4.3, §7.1 step 2, §7.3; TR-F45-04): ``read_overlay``'s
limits on a counting stream, ``OverlayPaths``' errors, ``encode_overlay``, and an overlay
checking like the saved file. AC-F45-10, AC-F45-11."""

import io
import json
import os

import pytest

from engine.core.constants import CONFIG_MAX_BYTES
from engine.core.editorreport import OVERLAY_HEADER_MAX, OVERLAY_MAX_BYTES, OVERLAY_READ_CHUNK
from engine.core.paths import GamePaths
from engine.script.limits import SCRIPT_FILE_MAX_BYTES
from engine.tools.check import OverlayError, OverlayPaths, read_overlay
from engine.tools.editor import checker
from engine.tools.editor.checker import encode_overlay
from tests.tools.editor.conftest import link_dir
from tests.tools.f45_games import (
    check,
    result_of,
    run_job,
    studio,
    without_seconds,
)

MiB = 1 << 20


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


def header(files: list[dict], v: int = 1) -> bytes:
    return json.dumps({"v": v, "files": files}).encode("ascii") + b"\n"


def entry(ref: str, size: object) -> dict:
    return {"ref": ref, "size": size}


def assert_refused(data: bytes, most: int) -> None:
    stream = Counting(data)
    with pytest.raises(OverlayError):
        read_overlay(stream)
    assert stream.given <= most


# --- AC-F45-10: overlay limits -------------------------------------------------------------

BAD_HEADERS = [
    header([], v=2),
    header([entry(f"script/f{i}.vns", 0) for i in range(65)]),
    header([entry("script/a.vns", "5")]),
    header([entry("script/a.vns", -1)]),
    header([entry("script/a.vns", True)]),
    header([entry("../x.vns", 0)]),
    header([entry("script/a.txt", 0)]),
    header([entry("images/a.png", 0)]),
    header([entry("SCRIPT/ch2.vns", 0)]),
    header([entry("script/a.vns", 0), entry("script/a.vns", 0)]),
    header([entry("script/a.vns", SCRIPT_FILE_MAX_BYTES + 1)]),
    header([entry("config.toml", CONFIG_MAX_BYTES + 1)]),
    # Declared only: 4 x 16 MiB + 1 is one byte past OVERLAY_MAX_BYTES; no body is sent.
    header([entry(f"script/f{i}.vns", SCRIPT_FILE_MAX_BYTES) for i in range(4)]
           + [entry("script/last.vns", 1)]),
    b'{"v":1,"files":[]' + bytes([10]),
    b'\xff\n',
]


def test_ac_f45_10_overlay_limits(tmp_path):
    assert_refused(b"x" * (OVERLAY_HEADER_MAX + 1) + b"\n{}", OVERLAY_HEADER_MAX + 1)
    assert 4 * SCRIPT_FILE_MAX_BYTES + 1 > OVERLAY_MAX_BYTES
    for data in BAD_HEADERS:
        assert_refused(data + b"x" * 10, len(data))
    head = header([entry("script/a.vns", 3 * MiB)])
    assert_refused(head + b"a" * (3 * MiB - 1), len(head) + 3 * MiB)
    assert_refused(head + b"a" * (3 * MiB + 1), len(head) + 3 * MiB + OVERLAY_READ_CHUNK)

    # OverlayPaths raises what disk raises: a ref not on disk, one through a link to OUT, and
    # one in the wrong case.
    game = studio(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.vns").write_bytes(b"label x:\n")
    link_dir(game / "script" / "routes", outside)
    refs = ("script/new.vns", "script/routes/x.vns", "script/CH2.vns")
    paths = GamePaths.for_game(game)
    overlay = OverlayPaths(paths.root, overlay={ref: b"label y:\n" for ref in refs})
    for ref in refs:
        with pytest.raises(Exception) as disk:
            paths.read_file(ref, max_bytes=SCRIPT_FILE_MAX_BYTES)
        with pytest.raises(Exception) as served:
            overlay.read_file(ref, max_bytes=SCRIPT_FILE_MAX_BYTES)
        assert (type(served.value), str(served.value)) == (type(disk.value), str(disk.value))

    # encode_overlay: what read_overlay reads back, and None past the caps.
    files = [("script/ch2.vns", "label x:\n    \"日\"\n".encode("utf-8")),
             ("config.toml", b"[game]\n")]
    assert read_overlay(Counting(encode_overlay(files))) == dict(files)
    assert encode_overlay([(f"script/f{i}.vns", b"") for i in range(65)]) is None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(checker, "OVERLAY_MAX_BYTES", 1024)
        assert encode_overlay([("script/a.vns", b"a" * 1024)]) is not None
        assert encode_overlay([("script/a.vns", b"a" * 1000), ("script/b.vns", b"b" * 25)]) \
            is None


@pytest.mark.slow
def test_ac_f45_10_a_real_64_mib_plus_1_total_is_refused():
    files = [entry(f"script/f{i}.vns", SCRIPT_FILE_MAX_BYTES) for i in range(4)]
    files.append(entry("config.toml", 1))
    head = header(files)
    assert_refused(head + b"a" * (OVERLAY_MAX_BYTES + 1), len(head))
    assert encode_overlay([(f"script/f{i}.vns", b"a" * SCRIPT_FILE_MAX_BYTES)
                           for i in range(4)] + [("config.toml", b"a")]) is None


# --- AC-F45-11: an overlay checks like the saved file ---------------------------------------

def test_ac_f45_11_an_overlay_checks_like_the_saved_file(tmp_path):
    game = studio(tmp_path, "s")
    ch2 = game / "script" / "ch2.vns"
    lines = ch2.read_bytes().split(b"\n")
    lines[8] = b"    jump bridg"
    b = b"\n".join(lines)
    before = (ch2.read_bytes(), os.stat(ch2).st_mtime_ns)
    overlaid = result_of(run_job(OverlayPaths(GamePaths.for_game(game).root,
                                              overlay={"script/ch2.vns": b})))
    saved_game = studio(tmp_path, "saved")
    (saved_game / "script" / "ch2.vns").write_bytes(b)
    saved = check(saved_game)
    assert without_seconds(overlaid) == without_seconds(saved)
    assert [i.code for i in overlaid.problems] == ["E43"]
    assert (ch2.read_bytes(), os.stat(ch2).st_mtime_ns) == before

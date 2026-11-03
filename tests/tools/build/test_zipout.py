"""F42 P3: the build's zip (AC-F42-30; SEC-F42-11's names)."""

import zipfile

import pytest

from engine.tools.build.zipout import ZipNameError, check_entry_name, write_zip

TOP = "Paper Lanterns 0.1.0 Windows"


def test_ac_f42_30_zip_has_one_top_folder_utf8_names_deflate_and_reads_back(tmp_path):
    folder = tmp_path / "staging" / TOP
    files = {"Paper Lanterns.exe": b"MZ" + bytes(500),
             "_internal/python312.dll": b"dll" * 1000,
             "game/script/ché.vns": "label start:\n    \"Hé.\"\n".encode("utf-8"),
             "README.txt": b"Paper Lanterns 0.1.0\r\n"}
    for ref, data in files.items():
        (folder / ref).parent.mkdir(parents=True, exist_ok=True)
        (folder / ref).write_bytes(data)
    (folder / "game" / "empty").mkdir()
    target = tmp_path / "staging" / f"{TOP}.zip"

    assert write_zip(folder, target) == (len(files), sum(map(len, files.values())))
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert archive.comment == b""
        infos = archive.infolist()
        assert {info.filename.split("/")[0] for info in infos} == {TOP}
        assert f"{TOP}/game/empty/" in archive.namelist()
        for info in infos:
            assert "\\" not in info.filename and ".." not in info.filename.split("/")
            assert info.extra == b""
            if not info.is_dir():
                assert info.compress_type == zipfile.ZIP_DEFLATED
                assert archive.read(info) == files[info.filename[len(TOP) + 1:]]
        assert archive.getinfo(f"{TOP}/game/script/ché.vns").flag_bits & 0x800

    with pytest.raises(FileExistsError):                  # never overwrites
        write_zip(folder, target)
    for bad in ("a/../b", "/a", "a\\b", "C:/a", "a/\x07b", "a//b", "./a"):
        with pytest.raises(ZipNameError):
            check_entry_name(bad)

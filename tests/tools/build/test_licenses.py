"""F42 P3: ``licenses/`` contents (PR-F42-14; the unit half of AC-F42-22, whose real-build
half is P8's). Fails when a pygame-ce bump adds a DLL without a notice (04 §17)."""

from engine.tools.build import licenses


def test_pr_f42_14_every_bundled_dll_has_a_notice_and_licenses_are_collected(tmp_path):
    installed = licenses.installed_pygame_dir()
    dlls = licenses.bundled_dlls(installed)
    if installed is not None and (installed / "SDL2.dll").exists():
        assert dlls                                       # the Windows wheel ships DLLs
    assert [dll for dll in dlls if dll.casefold() not in licenses.DLL_NOTICES] == []
    for name in {*licenses.DLL_NOTICES.values(), licenses.ENGINE_NOTICE, "Python.txt",
                 "pygame-ce.txt", "PyInstaller.txt"}:
        assert (licenses.NOTICES_DIR / name).is_file(), name

    notices = licenses.collect_notices()
    assert notices.unknown_dlls == ()
    by_name = {notice.name: notice.data for notice in notices.files}
    assert {"vn-engine.txt", "Python.txt", "pygame-ce.txt", "PyInstaller.txt",
            "OFL.txt"} <= set(by_name)
    assert b"All rights reserved." in by_name["vn-engine.txt"]
    assert b"PYTHON SOFTWARE FOUNDATION LICENSE" in by_name["Python.txt"]
    if dlls:
        assert b"GNU LESSER GENERAL PUBLIC LICENSE" in by_name["pygame-ce.txt"]
        assert "SDL2.txt" in by_name and "libwebp.txt" in by_name
    for data in by_name.values():
        assert b"\n" not in data.replace(b"\r\n", b"")    # CRLF only

    (tmp_path / "pygame").mkdir()
    (tmp_path / "pygame" / "libnew-1.dll").write_bytes(b"")
    (tmp_path / "python312.dll").write_bytes(b"")          # Python's own: Python.txt
    found = licenses.collect_notices([tmp_path, tmp_path / "pygame"])
    assert found.unknown_dlls == ("libnew-1.dll",)
    assert "SDL2.txt" not in {notice.name for notice in found.files}

    licenses.write_notices(tmp_path / "licenses", notices)
    assert sorted(p.name for p in (tmp_path / "licenses").iterdir()) == sorted(by_name)

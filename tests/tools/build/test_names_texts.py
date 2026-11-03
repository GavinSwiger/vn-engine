"""F42 P1: build names, field messages and the players' read-me (AC-F42-15, -29, -36;
SEC-F42-12, -15; ``07`` I-1)."""

from pathlib import Path

import pytest

from engine.tools.build import names, texts

# --- AC-F42-15: field messages and Use <slug> ------------------------------------------------

NO_NAME = texts.FIELD_MESSAGES[texts.NO_NAME]
BAD_VERSION = texts.FIELD_MESSAGES[texts.BAD_VERSION]
NO_ID = texts.FIELD_MESSAGES[texts.NO_ID]
BAD_ID = texts.FIELD_MESSAGES[texts.BAD_ID]

FIELD_ROWS = [
    # (title, version, id) → field → text
    (("Paper Lanterns", "0.1.0", "paper-lanterns"), {}),
    (("", "1.0", "x"), {"name": "Give your game a name."}),
    (("  \u200b\u202e ", "1.0", "x"), {"name": NO_NAME}),
    (("Game", "", "x"), {"version": BAD_VERSION}),
    (("Game", "1.0.", "x"), {"version": BAD_VERSION}),
    (("Game", "1.0 ", "x"), {"version": BAD_VERSION}),
    (("Game", "-1", "x"), {"version": BAD_VERSION}),
    (("Game", "1/2", "x"), {"version": BAD_VERSION}),
    (("Game", "1" * 33, "x"), {"version": BAD_VERSION}),
    (("Game", "1.2-beta", "x"), {}),
    (("Game", "1.2 rc+3_b", "x"), {}),
    (("Game", "1", ""), {"id": "Every game needs an ID before it's built. "
                               "Players' saves are kept in a folder named after it."}),
    (("Game", "1", "Paper"), {"id": BAD_ID}),
    (("Game", "1", "-paper"), {"id": BAD_ID}),
    (("Game", "1", "a" * 41), {"id": BAD_ID}),
    (("Game", "1", "com1"), {"id": "com1 is a reserved name on Windows. Try com1-game."}),
    (("Game", "1", "nul"), {"id": "nul is a reserved name on Windows. Try nul-game."}),
    (("", "", ""), {"name": NO_NAME, "version": BAD_VERSION, "id": NO_ID}),
]


def test_ac_f42_15_field_messages_and_use_slug():
    for (title, version, app_id), expected in FIELD_ROWS:
        assert names.field_problems(title, version, app_id) == expected, (title, version, app_id)
    assert BAD_ID == ("Use 1 to 40 lowercase letters, digits and dashes, starting with a letter "
                      "or digit, like paper-lanterns.")
    for title, slug in (("Paper Lanterns", "paper-lanterns"), ("", "game"), ("CON", "con-game"),
                        ("Café Ümlaut!", "cafe-umlaut"), ("ひかり", "game")):
        assert names.use_slug(title) == slug
        assert names.use_slug_text(title) == f"Use {slug}"
        assert names.field_problems("t", "1", slug) == {}


# --- AC-F42-29: README.txt --------------------------------------------------------------------

README = (
    "Paper Lanterns 0.1.0\r\n"
    "\r\n"
    "To play, open Paper Lanterns.exe. Keep the game and _internal folders next to it.\r\n"
    "Unzip the game into a folder you can write to, like Documents or Desktop.\r\n"
    "\r\n"
    'If Windows says "Windows protected your PC", click More info, then Run anyway. '
    "Only do this if you got the game from a place you trust.\r\n"
    "\r\n"
    "Saves and settings: %APPDATA%\\vn-engine\\paper-lanterns\r\n"
    "Logs (useful in bug reports): %LOCALAPPDATA%\\vn-engine\\paper-lanterns\\logs\r\n"
    "\r\n"
    "Made with vn-engine. Licenses are in the licenses folder.\r\n"
)


def test_ac_f42_29_readme_text_crlf_and_no_author_paths(tmp_path):
    text = texts.readme_text(name="Paper Lanterns", version="0.1.0", exe="Paper Lanterns.exe",
                             app_id="paper-lanterns")
    assert text == README
    data = texts.readme_bytes(name="Paper Lanterns", version="0.1.0",
                              exe="Paper Lanterns.exe", app_id="paper-lanterns")
    assert data == README.encode("utf-8") and not data.startswith(b"\xef\xbb\xbf")
    assert data.count(b"\n") == data.count(b"\r\n") == 11
    for needle in (str(Path.home()), Path.home().name, str(tmp_path), str(Path.cwd())):
        assert needle not in text
    # A title can't add lines or hide text (one line per value; SEC-F42-12's characters).
    odd = texts.readme_text(name="A\r\nB\u202e\x07", version="1", exe="A.exe", app_id="a")
    assert odd.splitlines()[0] == "A  B 1" and odd.count("\r\n") == 11
    assert texts.SMARTSCREEN.endswith(" Only do this if you got the game from a place you "
                                      "trust.")


# --- AC-F42-36: name and version cleaning ----------------------------------------------------

CLEAN_ROWS = [
    ("Paper Lanterns", "Paper Lanterns"),
    ('a<b>c:d"e/f\\g|h?i*j', "abcdefghij"),
    ("  Lots   of\tspace  ", "Lots of space"),
    ("Trailing dots...", "Trailing dots"),
    ("Trailing . . ", "Trailing"),
    ("...Leading", "Leading"),
    ("Bell\x07 and\nline", "Bell and line"),
    ("Lanterns\u202egnp.exe", "Lanternsgnp.exe"),                  # SEC-F42-12 (T8)
    ("Zero\u200bwidth\u2066iso\u2069", "Zerowidthiso"),
    ("Cafe\u0301", "Café"),                                        # NFC
    ("CON", "paper"),
    ("con.Game", "paper"),
    ("com¹", "paper"),
    ("LPT9 . x", "paper"),
    ("Console", "Console"),
    ("", "paper"),
    ("<>:", "paper"),
    ("x" * 70, "x" * 60),
    ("y" * 59 + "q\u0301" * 3, "y" * 59),                          # never inside a grapheme
    ("z" * 59 + " tail", "z" * 59),                                # no trailing space after the cut
]

FILE_VERSIONS = [("1.2-beta", "1.2.0.0"), ("0.1.0", "0.1.0.0"), ("beta", "0.0.0.0"),
                 ("2", "2.0.0.0"), ("1.2.3.4.5", "1.2.3.4"), ("70000.1", "65535.1.0.0"),
                 ("1..2", "1.0.0.0"), ("007.08", "7.8.0.0")]


def test_ac_f42_36_name_and_version_cleaning():
    for title, expected in CLEAN_ROWS:
        assert names.clean_name(title, "paper") == expected, repr(title)
    assert names.clean_name("CON", "Bad Id") == "game"
    assert names.folder_name("Paper Lanterns", "0.1.0", "paper") == "Paper Lanterns 0.1.0 Windows"
    assert names.folder_name("CON", "1.2-beta", "paper") == "paper 1.2-beta Windows"
    assert names.folder_name("Game", "1.0\u202e.", "g") == "Game 1.0 Windows"
    assert names.zip_name("Game 1 Windows") == "Game 1 Windows.zip"
    for title, exe in (("Paper Lanterns", "Paper Lanterns.exe"), ("Game.exe", "Game.exe"),
                       ("Lanterns\u202egnp.exe", "Lanternsgnp.exe"), (".exe", "exe.exe"),
                       ("..exe .exe", "exe.exe"), ("CON.exe", "paper.exe"), ("nul.EXE", "paper.exe")):
        assert names.exe_name(title, "paper") == exe, title
    for version, expected in FILE_VERSIONS:
        assert names.file_version(version) == expected, version
    for version in ("1.0", "1.2-beta", "A", "1 2", "1+x_y"):
        assert names.check_version(version) is None, version
    for version in ("", ".1", "1.", "1 ", "é", "1\u202e", "a" * 33):
        assert names.check_version(version) == texts.BAD_VERSION, version
    for title in ("Paper Lanterns", "x" * 80 + "\u202e", "CON", "a/b:c"):
        for name in (names.folder_name(title, "1.0", "p"), names.exe_name(title, "p")):
            assert not any(ch in name for ch in '<>:"/\\|?*\u202e') and name == name.strip(" ")

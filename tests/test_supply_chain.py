"""Pinned and traceable third-party inputs (SEC-F01-22, TR-F01-74).

AC-F01-165: CI installs exact, hashed packages. AC-F01-164: the bundled font's provenance
record and hash (ADR-0004). AC-F05-42: the four bundled faces, one File:/SHA-256: pair each,
and no unlisted font file (ADR-0004 amendment, F05 I-18).
"""

import hashlib
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HASH_RE = re.compile(r"--hash=sha256:[0-9a-f]{64}")


def requirement_entries() -> list[str]:
    """Logical lines of requirements-ci.txt: continuations joined, comments dropped."""
    text = (REPO / "requirements-ci.txt").read_text(encoding="utf-8")
    entries, current = [], ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("--hash") \
            else raw.rstrip()
        if not line.strip():
            continue
        if line.endswith("\\"):
            current += line[:-1] + " "
            continue
        entries.append((current + line).strip())
        current = ""
    assert current == "", "dangling line continuation"
    return entries


def test_every_requirement_is_pinned_with_a_hash():
    entries = requirement_entries()
    assert entries
    for entry in entries:
        spec = entry.split("--hash", 1)[0].split(";", 1)[0].strip()
        assert re.fullmatch(r"[A-Za-z0-9_.\-]+==[A-Za-z0-9_.+\-]+", spec), entry
        assert HASH_RE.search(entry), entry
        for token in entry.split():
            if token.startswith("--hash"):
                assert HASH_RE.fullmatch(token), token


def test_engine_and_test_runner_are_listed():
    names = {entry.split("==", 1)[0].strip().lower() for entry in requirement_entries()}
    assert {"pygame-ce", "pytest"} <= names


def test_pinned_pygame_ce_is_in_the_supported_range():
    for entry in requirement_entries():
        if entry.lower().startswith("pygame-ce=="):
            version = tuple(int(p) for p in entry.split("==")[1].split()[0].split("."))
            assert (2, 5, 2) <= version < (2, 6)
            return
    raise AssertionError("pygame-ce is not pinned")


def test_ci_installs_with_require_hashes():
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pip install --require-hashes -r requirements-ci.txt" in workflow
    assert 'pytest -m "not perf and not manual"' in workflow
    for runner in ("windows-latest", "macos-latest", "ubuntu-latest"):
        assert runner in workflow
    assert '"3.12"' in workflow


def test_pyproject_keeps_the_development_range():
    import tomllib
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["requires-python"] == ">=3.12"
    assert project["dependencies"] == ["pygame-ce>=2.5.2,<2.6"]


# --- AC-F01-164, AC-F05-42: bundled font provenance -----------------------------------------

FONTS = REPO / "engine" / "data" / "fonts"
FONT_SUFFIXES = (".ttf", ".otf", ".ttc", ".woff", ".woff2")
FACES = ("NotoSans-Regular.ttf", "NotoSans-Bold.ttf", "NotoSans-Italic.ttf",
         "NotoSans-BoldItalic.ttf")


def source_record(text: str | None = None) -> dict[str, str]:
    """The shared "Key: value" lines (first occurrence wins)."""
    if text is None:
        text = (FONTS / "SOURCE.txt").read_text(encoding="utf-8")
    record = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and value.strip():
            record.setdefault(key.strip(), value.strip())
    return record


def file_hashes(text: str | None = None) -> dict[str, str]:
    """File name -> SHA-256 from the ``File:``/``SHA-256:`` pairs (F05 I-18). A ``File:``
    without a following ``SHA-256:`` line, or a name listed twice, fails."""
    if text is None:
        text = (FONTS / "SOURCE.txt").read_text(encoding="utf-8")
    pairs: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not sep:
            continue
        if key == "File":
            assert current is None, f"File: {current} has no SHA-256: line"
            assert value not in pairs, f"File: {value} is listed twice"
            current = value
        elif key == "SHA-256" and current is not None:
            pairs[current] = value
            current = None
    assert current is None, f"File: {current} has no SHA-256: line"
    return pairs


def check_fonts_folder(folder: Path, source_text: str) -> None:
    """Every listed hash matches its file, and every font file is listed."""
    pairs = file_hashes(source_text)
    for name, expected in pairs.items():
        assert re.fullmatch(r"[0-9a-f]{64}", expected), name
        digest = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        assert digest == expected, f"{name}: SHA-256 {digest} does not match SOURCE.txt"
    for path in folder.iterdir():
        if path.suffix.lower() in FONT_SUFFIXES:
            assert path.name in pairs, f"{path.name} has no File:/SHA-256: entry in SOURCE.txt"


def test_source_txt_names_url_version_and_hash():
    record = source_record()
    assert record["Source URL"].startswith("https://")
    assert re.search(r"v\d+\.\d+", record["Release version"])
    assert re.fullmatch(r"[0-9a-f]{64}", record["SHA-256"])


def test_bundled_font_matches_its_recorded_hash():
    digest = hashlib.sha256((FONTS / "NotoSans-Regular.ttf").read_bytes()).hexdigest()
    assert digest == file_hashes()["NotoSans-Regular.ttf"]


def test_the_four_faces_are_bundled_and_listed():
    """AC-F05-42: the three F05 faces sit next to Regular, each with a File:/SHA-256: pair,
    all from Regular's release."""
    pairs = file_hashes()
    for name in FACES:
        assert (FONTS / name).is_file(), name
        assert name in pairs, name
    record = source_record()
    assert record["Release version"].startswith("NotoSans-v2.015")
    assert record["Source URL"].endswith("/NotoSans-v2.015/NotoSans-v2.015.zip")
    assert "NotoSans/hinted/ttf/" in record["Path in the release archive"]


def test_every_bundled_font_matches_its_hash_and_is_listed():
    check_fonts_folder(FONTS, (FONTS / "SOURCE.txt").read_text(encoding="utf-8"))


def copy_fonts(tmp_path: Path) -> Path:
    folder = tmp_path / "fonts"
    folder.mkdir()
    for path in FONTS.iterdir():
        if path.is_file():
            (folder / path.name).write_bytes(path.read_bytes())
    return folder


@pytest.mark.parametrize("name", FACES)
def test_a_changed_byte_fails_the_check(tmp_path, name):
    """AC-F05-42: the check fails when any byte of any face changes."""
    folder = copy_fonts(tmp_path)
    source = (folder / "SOURCE.txt").read_text(encoding="utf-8")
    check_fonts_folder(folder, source)                  # the copy passes as it is
    data = bytearray((folder / name).read_bytes())
    data[len(data) // 2] ^= 0x01
    (folder / name).write_bytes(bytes(data))
    with pytest.raises(AssertionError, match=name):
        check_fonts_folder(folder, source)


def test_an_unlisted_font_file_fails_the_check(tmp_path):
    """ADR-0004 amendment (F05 I-18): a font file with no SOURCE.txt entry fails."""
    folder = copy_fonts(tmp_path)
    source = (folder / "SOURCE.txt").read_text(encoding="utf-8")
    (folder / "Extra.otf").write_bytes(b"x")
    with pytest.raises(AssertionError, match="Extra.otf has no File:/SHA-256: entry"):
        check_fonts_folder(folder, source)


def test_a_file_entry_without_a_hash_fails():
    with pytest.raises(AssertionError, match="Bold.ttf has no SHA-256"):
        file_hashes("File: NotoSans-Bold.ttf\nFile: NotoSans-Italic.ttf\nSHA-256: " + "0" * 64)


def test_license_is_bundled():
    text = (FONTS / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in text

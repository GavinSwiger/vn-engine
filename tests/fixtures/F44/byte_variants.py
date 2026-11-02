"""The byte variants V1–V10 of F44 ``06-acceptance.md`` §4 (``bytes/``), built in code so
their exact line endings can't be changed by a checkout's newline conversion.

Each is about 12 lines with a ``label`` and dialogue. ``VARIANTS`` maps the name to the
file's bytes; ``write_variants(folder)`` writes ``V1.vns``…``V10.vns`` into ``folder``.
Standard library only; imports nothing from ``engine``.
"""

from pathlib import Path

BOM = b"\xef\xbb\xbf"

_LINES = [
    "label start:",
    '    "Opening line."',
    '    sayori "Hello there."',
    "    $ points += 1  # note",
    "    if points >= 1:",
    '        "You have a point."',
    "    else:",
    '        "No points yet."',
    "# a comment",
    '    hana "Bye."',
    "    jump next_scene",
    "label next_scene:",
]

_WIDE_LINES = [
    "label start:",
    '    "😀 Smile."',
    '    sayori "日本語のテキスト。"',
    '    "مرحبا بالعالم"',
    '    "שלום עולם"',
    '    "Café and naïve."',
    '    hana "🎉🎉 {b}Party{/b} 😀"',
    "    $ points += 1",
    '    "Ünïcödé ✓"',
    "    jump next_scene",
    "label next_scene:",
    '    "𝄞 clef."',
]


def _join(lines: list[str], ending: str, final: bool) -> bytes:
    text = ending.join(lines) + (ending if final else "")
    return text.encode("utf-8")


def _mixed(lines: list[str]) -> bytes:
    """Line i (1-based) ends LF, CRLF, or CR as i mod 3 is 0, 1, or 2; final break."""
    endings = {0: "\n", 1: "\r\n", 2: "\r"}
    return "".join(line + endings[i % 3] for i, line in enumerate(lines, 1)).encode("utf-8")


VARIANTS: dict[str, bytes] = {
    "V1": _join(_LINES, "\n", True),                        # LF, final break
    "V2": BOM + _join(_LINES, "\r\n", False),               # CRLF with BOM, no final break
    "V3": _join(_LINES, "\r", True),                        # CR
    "V4": _mixed(_LINES),                                   # mixed, final break
    "V5": _join([line.replace("    ", "\t") for line in _LINES], "\n", True),  # tabs
    "V6": _join(_WIDE_LINES, "\n", True),                   # emoji, CJK, RTL, combining
    "V7": b"",                                              # 0 bytes
    "V8": BOM,                                              # BOM only
    "V9": b"label start:",                                  # one line, no break
    "V10": b'label start:\n    "Text."\n\n\n',             # text then \n\n\n
}


def write_variants(folder: Path) -> dict[str, Path]:
    """Write every variant as ``<name>.vns`` into ``folder``; returns name → path."""
    folder.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, data in VARIANTS.items():
        path = folder / f"{name}.vns"
        path.write_bytes(data)
        written[name] = path
    return written

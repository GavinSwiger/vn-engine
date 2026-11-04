"""F58's story-map bench games (``04-technical.md`` §16 P0; from the main session's
``mapbench.py``). Stdlib and engine only, deterministic.

Each scene is nine lines: its label, two lines of dialogue, and a two-choice menu whose
choices jump to the next and the previous scene (a ring), then a blank line. Scene ``i`` is
``s{i}``; its label line is ``9·i + 1`` of its file and its jumps are lines ``9·i + 6`` and
``9·i + 8``. With ``start=True`` scene 0 is named ``start`` (columns by distance); without it,
as in ``mapbench.py``, nothing is reached and every box shares one column.

- ``script(n)``: the text of ``n`` scenes (``first`` numbers them from another index).
- ``labels(n, files)`` / ``links(n, files)``: the check child's ``NameEntry`` and
  ``LabelLink`` rows for the same scenes spread over ``files`` files.
- ``write_game(root, n, files)``: a game folder whose ``script/`` holds the scenes in one
  file (``files=1``, the worst case: one file holds every scene) or spread evenly over
  ``files`` files.
"""

from pathlib import Path

from engine.script.labelgraph import LabelLink
from engine.tools.editor.checker import NameEntry

SCENE_LINES = 9
MAIN = "script/main.vns"


def name(i: int, n: int, *, start: bool = False) -> str:
    i %= n
    return "start" if start and i == 0 else f"s{i}"


def script(n: int, *, first: int = 0, count: int | None = None, start: bool = False,
           total: int | None = None) -> str:
    """Scenes ``first`` .. ``first + count - 1`` of an ``n``-scene ring (``total`` defaults
    to ``n``), as one file's text with a final line break."""
    total = total or n
    count = n if count is None else count
    out: list[str] = []
    for i in range(first, first + count):
        out += [f"label {name(i, total, start=start)}:",
                f'    "Scene {i} line one."', f'    "Scene {i} line two."', "    menu:",
                '        "Go on":', f"            jump {name(i + 1, total, start=start)}",
                '        "Go back":', f"            jump {name(i - 1, total, start=start)}", ""]
    return "\n".join(out) + "\n"


def file_of(i: int, n: int, files: int) -> tuple[str, int]:
    """Scene ``i``'s ref and its index within that file."""
    if files <= 1:
        return MAIN, i
    per = -(-n // files)
    return f"script/scenes/f{i // per:04}.vns", i % per


def labels(n: int, files: int = 1, *, start: bool = False) -> list[NameEntry]:
    rows = []
    for i in range(n):
        ref, k = file_of(i, n, files)
        rows.append(NameEntry(name(i, n, start=start), ref, SCENE_LINES * k + 1))
    return rows


def links(n: int, files: int = 1, *, start: bool = False) -> list[LabelLink]:
    rows = []
    for i in range(n):
        ref, k = file_of(i, n, files)
        for j, d in enumerate((1, -1)):
            rows.append(LabelLink(name(i, n, start=start), name(i + d, n, start=start), "menu",
                                  ref, SCENE_LINES * k + 6 + 2 * j,
                                  "Go on" if d == 1 else "Go back"))
    return rows


def write_game(root: Path, n: int, files: int = 1, *, start: bool = False) -> Path:
    """``root`` as a game: ``config.toml`` and the scenes under ``script/``."""
    script_dir = root / "script"
    script_dir.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_bytes(b'[game]\ntitle = "Map bench"\n')
    if files <= 1:
        (script_dir / "main.vns").write_bytes(script(n, start=start).encode())
        return root
    per = -(-n // files)
    (script_dir / "scenes").mkdir(exist_ok=True)
    refs = []
    for f in range(files):
        lo = f * per
        if lo >= n:
            break
        ref = f"script/scenes/f{f:04}.vns"
        refs.append(ref)
        (root / ref).write_bytes(script(n, first=lo, count=min(per, n - lo), start=start,
                                        total=n).encode())
    head = [f'include "{ref.removeprefix("script/")}"' for ref in refs]
    (script_dir / "main.vns").write_bytes(("\n".join(head) + "\n").encode())
    return root


def big_text(size: int) -> str:
    """Whole scenes, at most ``size`` bytes in all (a large file for the watch's caps)."""
    one = len(script(1, first=10 ** 6, total=10 ** 7).encode())     # the longest scenes
    n = max(1, size // one)
    text = script(n, start=True)
    while len(text.encode()) > size and n > 1:
        n = n * 99 // 100
        text = script(n, start=True)
    return text


__all__ = ["MAIN", "SCENE_LINES", "big_text", "file_of", "labels", "links", "name", "script",
           "write_game"]

"""Studio's **Try it** run: ``python -m engine run GAME --try-stdin`` (F47 ``04-technical.md``
§7.5, PR-F47-20, AC-F47-30).

Why this module exists: Try it plays one form's line in a small game window over the
row's stage, and nothing of the author's game may change because of it. The game loads as
usual (config, pictures, plugins, every ``define`` and ``default``, so the line's names
work), but the story starts at a throwaway label built from the lines Studio sent on stdin,
and the run is isolated:

- the label (``TRY_LABEL``) reaches the loader through ``TryPaths``, which serves
  ``script/main.vns`` with the label appended (in memory; the file isn't touched);
- persistent data stays in memory (as ``--no-persistent``), the player's settings aren't
  read (config defaults), no log file is opened (console only), and there are no saves and
  no meta files (``App.try_run``: ``install_saves`` and ``install_metafiles`` skip the
  disk), so nothing is written in the game folder or the per-user folders;
- the story's end quits at once (``try_screens``), so the window closes itself after the
  lines' last ``pause``.

Imports only ``engine.core`` and the standard library at import time (``cli`` imports it
before pygame may load).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from engine.core.paths import GamePaths

# Names starting with _ are the engine's (E63), so the label is a plain name an author is
# unlikely to write.
TRY_LABEL = "studio_try_it"
TRY_MAX_BYTES = 64 * 1024               # what --try-stdin reads at most
TRY_MAX_LINES = 200
MAIN_REF = "script/main.vns"
INDENT = "    "
WINDOW_TITLE = "Try it - {title}"
WINDOW_SHARE = 0.5                      # of the game's window size, each side

TRY_TOO_LONG = f"--try-stdin takes at most {TRY_MAX_LINES} lines ({TRY_MAX_BYTES // 1024} KB)"
TRY_NOT_TEXT = "--try-stdin needs UTF-8 script lines on stdin"
TRY_EMPTY = "--try-stdin needs at least one script line on stdin"
TRY_WITH_START = "--try-stdin can't be used with --start or --resume-from-editor"


def parse_try_text(data: bytes) -> tuple[str, ...] | str:
    """stdin's bytes as the label's body lines (blank lines dropped, trailing blanks cut),
    or the usage error. A tab or a control character other than a line end is refused."""
    if len(data) > TRY_MAX_BYTES:
        return TRY_TOO_LONG
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return TRY_NOT_TEXT
    lines = tuple(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")
                  if line.strip())
    if any(ch < " " for line in lines for ch in line):
        return TRY_NOT_TEXT
    if not lines:
        return TRY_EMPTY
    if len(lines) > TRY_MAX_LINES:
        return TRY_TOO_LONG
    return lines


def label_text(lines: Sequence[str]) -> str:
    """The throwaway label: ``label studio_try_it:`` and each line indented once (a line's
    own indentation is kept under it)."""
    body = "".join(f"{INDENT}{line}\n" for line in lines)
    return f"\n\nlabel {TRY_LABEL}:\n{body}"


@dataclass(frozen=True)
class TryPaths(GamePaths):
    """``GamePaths`` that serves ``script/main.vns`` with the try label appended. Every
    other read, and every check on ``main.vns`` itself, is the disk's; nothing is written."""

    tail: bytes = b""

    @classmethod
    def over(cls, paths: GamePaths, lines: Sequence[str]) -> "TryPaths":
        return cls(paths.root, tail=label_text(lines).encode("utf-8"))

    def read_file(self, ref: str, *, max_bytes: int, regular: bool = False) -> bytes:
        if ref != MAIN_REF:
            return super().read_file(ref, max_bytes=max_bytes, regular=regular)
        data = super().read_file(ref, max_bytes=max(0, max_bytes - len(self.tail)),
                                 regular=regular)
        return data + self.tail


def try_size(size: tuple[int, int]) -> tuple[int, int]:
    """The small window's requested size: half the game's, each side."""
    return max(1, round(size[0] * WINDOW_SHARE)), max(1, round(size[1] * WINDOW_SHARE))


def try_screens(app: object) -> list:
    """``on_ready`` of a try run: the story's end quits at once (no title, no question),
    then the usual first screens, which start the label at once (it is ``app.start``)."""
    from engine.app.bootstrap import build_initial_screens
    from engine.runtime.commands import StoryEnded

    router = app.router                                         # type: ignore[attr-defined]
    router.unregister(StoryEnded)
    router.register(StoryEnded, lambda _cmd: app.request_quit(force=True))  # type: ignore[attr-defined]
    return build_initial_screens(app)

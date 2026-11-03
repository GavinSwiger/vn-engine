"""The Outline tab's rows: the story's chapters, endings, routes, codex entries, meters,
minigames, flowchart scenes, and meta files (2026-11-02, user: keep Studio updated;
AC-F45-54, 60, 72).

Pure Python, no Tk. ``outline(names)`` reads only the check child's name index (the last good
check's ``names`` events), so nothing runs before the first Preview, Save, or Check (F45 O-1).
Each ``Row`` has the text shown and the place Enter or a double-click jumps to (None: no
place, such as a meter or a bundled minigame).

- **Routes** list their ``until`` endings: ``route_until`` rows sit at their route's line.
- **Codex** groups tips and items by category: ``category`` rows sit at their entry's line.
- **Minigames** are the ones the story uses (``minigame_use``), each line once.
- **Flowchart** lists the chart's nodes in chart order (``flowchart_node``, F20 s9: kind,
  title, ``hidden`` and ``no jump``), each at its point's line; with no graph (an older check
  child, or ``[flowchart] enabled = false``), the scene titles (``flowchart_scene``).
- **Meta files** (F31) lists each name the story's ``file`` lines use (``meta_file_use``),
  with one row per line; an original in ``files/`` that no line uses shows ``(not used)``.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

NO_OUTLINE: Final = "No outline yet. It is read from the last check that loaded the script."
SECTIONS: Final = ("Chapters", "Endings", "Routes", "Codex", "Meters", "Minigames",
                   "Flowchart", "Meta files")
NOT_USED: Final = "(not used)"
UNCATEGORIZED: Final = "(no category)"


@dataclass(frozen=True, slots=True)
class Row:
    """One tree row: ``text``, its place (``file``, ``line``), and nested ``children``."""

    text: str
    file: str | None = None
    line: int | None = None
    children: tuple["Row", ...] = ()


def _rows(entries: Iterable[object]) -> list[tuple[str, str | None, int | None]]:
    out = []
    for entry in entries:
        if isinstance(entry, str):
            out.append((entry, None, None))
        elif hasattr(entry, "name"):
            out.append((entry.name, getattr(entry, "file", None), getattr(entry, "line", None)))
        else:
            name, file, line = tuple(entry)[:3]  # type: ignore[call-overload]
            out.append((name, file, line))
    return out


def _section(title: str, children: list[Row]) -> Row:
    return Row(f"{title} ({len(children)})", children=tuple(children))


def outline(names: Mapping[str, Iterable[object]]) -> tuple[Row, ...]:
    """The tree for ``names`` (kind → entries), one section per ``SECTIONS`` entry."""
    get = lambda kind: _rows(names.get(kind, ()))  # noqa: E731
    endings = {name: (file, line) for name, file, line in get("ending")}

    chapters = [Row(name, file, line) for name, file, line in get("chapter")]
    ending_rows = [Row(name, file, line) for name, file, line in get("ending")]

    until: dict[tuple[str | None, int | None], list[str]] = {}
    for name, file, line in get("route_until"):
        until.setdefault((file, line), []).append(name)
    routes = []
    for name, file, line in get("route"):
        opens = until.get((file, line), [])
        kids = tuple(Row(f"until {e}", *endings.get(e, (None, None))) for e in opens)
        routes.append(Row(name, file, line, kids))

    category: dict[tuple[str | None, int | None], str] = {
        (file, line): name for name, file, line in get("category")}
    groups: dict[str, list[Row]] = {}
    for kind in ("tip", "item"):
        for name, file, line in get(kind):
            title = category.get((file, line)) or UNCATEGORIZED
            groups.setdefault(title, []).append(Row(f"{kind} {name}", file, line))
    codex = [Row(f"{title} ({len(rows)})", children=tuple(rows))
             for title, rows in groups.items()]

    meters = [Row(name, file, line) for name, file, line in get("meter")]
    seen: set[tuple[str, str | None, int | None]] = set()
    games = []
    for row in get("minigame_use"):
        if row not in seen:
            seen.add(row)
            games.append(Row(row[0], row[1], row[2]))

    lines: dict[str, list[Row]] = {}
    for name, file, line in get("meta_file_use"):
        lines.setdefault(name, []).append(Row(name, file, line))
    for name, _file, _line in get("meta_file"):
        lines.setdefault(name, [])
    meta = [Row(f"{name} ({len(rows)})", children=tuple(rows)) if rows
            else Row(f"{name} {NOT_USED}") for name, rows in lines.items()]

    return (_section("Chapters", chapters), _section("Endings", ending_rows),
            _section("Routes", routes), Row(f"Codex ({sum(len(g) for g in groups.values())})",
                                            children=tuple(codex)),
            _section("Meters", meters), _section("Minigames", games),
            _section("Flowchart", [Row(name, file, line) for name, file, line in
                                   get("flowchart_node") or get("flowchart_scene")]),
            _section("Meta files", meta))


__all__ = ["NOT_USED", "NO_OUTLINE", "Row", "SECTIONS", "UNCATEGORIZED", "outline"]

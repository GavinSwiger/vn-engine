"""The assistant's tools: their fixed descriptions and the code behind each (F48
``04-technical.md`` §3.1, §7.1; 01 §7.1, §7.2, PR-F48-02, PR-F48-04 to -08, PR-F48-10;
``05-security.md`` SEC-F48-01, SEC-F48-05, SEC-F48-09).

Why this module exists: MCP and the pane offer the model the same tools, and what a model
reads about them is part of what it obeys. So ``TOOL_SPECS`` (names, one-line descriptions,
JSON schemas, MCP annotations) is engine text, byte-identical for every game (SEC-F48-09 (c)),
and every tool answers through ``textout``'s two forms: numbered-line blocks under a fixed
header, and one-line escaped strings.

- ``TOOL_SPECS``: 01 §7.1's table in a fixed order. Reads, ``run_check`` and
  ``propose_edit`` (which writes nothing) carry ``readOnlyHint``; ``apply_edit`` and
  ``undo_apply`` carry ``destructiveHint`` (PR-F48-10), and only ``MODE_MCP`` offers them
  (``specs_for``): the pane and ``--read-only`` never do.
- ``ToolBox(workspace, mode).call(name, args)`` → ``ToolText``. Every selector is an exact
  member of an engine-built set (``refs``); a refused call (``ToolError``) is an error
  result, never an exception. The workspace says where text comes from (disk or the pane's
  snapshot) and whether checks may launch.
- ``writer`` (MCP only, ``diskapply``'s store) keeps a proposal under an id and runs
  ``apply_edit``/``undo_apply``; ``on_proposal`` (pane) receives each proposal to show as a
  card, whose contents come from the plan, never from model text (SEC-F48-20).

Imports ``engine.core``, ``engine.script``, the pure editor modules ``cleanup``,
``config_help``, ``declarations`` and ``document``, and its own package.
"""

import json
import logging
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Final, Protocol

from engine.script.assetgroups import ASSET_GROUPS, CONFIG_REF
from engine.tools.assistant import edits
from engine.tools.assistant.reference import (
    build_reference, doc_section, doc_topic_names, doc_topics)
from engine.tools.assistant.refs import (
    RefTable, ToolError, check_keys, flag_arg, int_arg, one_line, select, shown_value,
    text_arg)
from engine.tools.assistant.textout import (
    ARROWS_MAX, HITS_MAX, NAMES_MAX, PROBLEMS_MAX, READ_MAX_LINES, SEARCH_TEXT_MAX_CHARS,
    TOOL_TEXT_MAX_CHARS, USES_MAX, TextOut, ToolText, line_width,
    numbered_line)
from engine.tools.assistant.workspace import CheckRun, Workspace
from engine.tools.editor import declarations as dec
from engine.tools.editor.cleanup import KINDS as LINT_KINDS
from engine.tools.editor.config_help import key_help
from engine.tools.editor.scenes import chunks

log = logging.getLogger("vn.assistant")

MODE_MCP: Final = "mcp"                 # every tool, apply_edit and undo_apply included
MODE_READ_ONLY: Final = "read_only"     # assist-mcp --read-only
MODE_PANE: Final = "pane"               # Studio's pane: a card instead of an id
MODES: Final = (MODE_MCP, MODE_READ_ONLY, MODE_PANE)
WRITE_TOOLS: Final = ("apply_edit", "undo_apply")

# --- Texts ----------------------------------------------------------------------------------

UNKNOWN_TOOL: Final = "There is no tool {name}."
TOOL_FAILED: Final = "That tool failed inside the engine. Try again, or try another tool."
NO_WRITER: Final = "This server can't change files."
READ_ONLY_NOTE: Final = "This server is read-only, so the change can't be applied here."
NOT_LOADED: Final = "The story didn't load, so there is no map. run_check shows why."
SCENE_MOVED: Final = "The scene {label} isn't in {file} now. Run run_check, then try again."
EMPTY_SEARCH: Final = "text must not be empty."
NOT_CHECKED_NAMES: Final = "No names yet: the last check didn't finish."
UNTITLED: Final = "Untitled Visual Novel"
START_SCENE: Final = "start"
WITHOUT_CODE: Final = "Checked without running the game's Python code (--no-launch)."
NOT_ARMED: Final = ("Checked without running the game's Python code, because the author "
                    "hasn't played, saved or checked the game in this window yet.")


# --- TOOL_SPECS (01 §7.1; byte-identical for every game) ------------------------------------

def _schema(properties: Mapping[str, Mapping[str, object]] | None = None,
            required: Sequence[str] = ()) -> dict:
    schema: dict = {"type": "object", "properties": dict(properties or {}),
                    "additionalProperties": False}
    if required:
        schema["required"] = list(required)
    return schema


_READ: Final = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
                "openWorldHint": False}
_WRITE: Final = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False,
                 "openWorldHint": False}
_REF = {"type": "string", "maxLength": 1024}


def _spec(name: str, description: str, schema: dict, annotations: Mapping[str, bool]) -> dict:
    return {"name": name, "description": description, "inputSchema": schema,
            "annotations": dict(annotations)}


TOOL_SPECS: Final[tuple[dict, ...]] = (
    _spec("language_reference",
          "The vn-engine script language: every statement with syntax, meaning and an "
          "example, and the text tags. Read it before writing script.", _schema(), _READ),
    _spec("language_docs",
          "One section of the script language guide, by topic (a statement word or a "
          "heading); an unknown topic lists the topics.",
          _schema({"topic": _REF}, ("topic",)), _READ),
    _spec("project_summary",
          "The game at a glance: title, start scene, script files with line counts, how "
          "many scenes, characters, pictures and sounds, and the last check's totals.",
          _schema(), _READ),
    _spec("list_files",
          "The game's files with sizes, for one group (script, images, audio, gui, fonts, "
          "minigames, files) or all of them.",
          _schema({"group": _REF}), _READ),
    _spec("read_script",
          "Numbered lines of a script file or config.toml, at most 800 at a time; "
          "first_line and last_line pick the range.",
          _schema({"file": _REF, "first_line": {"type": "integer"},
                   "last_line": {"type": "integer"}}, ("file",)), _READ),
    _spec("search_scripts",
          "Lines of the script files that hold some text (plain text, not a pattern), "
          "at most 200.",
          _schema({"text": {"type": "string", "maxLength": SEARCH_TEXT_MAX_CHARS},
                   "match_case": {"type": "boolean"}}, ("text",)), _READ),
    _spec("story_map",
          "Every scene with its file and line, the arrows between scenes (jump, call, "
          "choice) and the scenes nothing reaches.", _schema(), _READ),
    _spec("scene",
          "One scene's numbered lines and the arrows into and out of it.",
          _schema({"label": _REF}, ("label",)), _READ),
    _spec("names",
          "The kinds of names the game has (characters, pictures, sounds, variables, …) "
          "with counts; with kind, that kind's names and where each is declared.",
          _schema({"kind": _REF}), _READ),
    _spec("lookup",
          "Where one name is declared, the lines that use it, and its declared values.",
          _schema({"kind": _REF, "name": _REF}, ("kind", "name")), _READ),
    _spec("game_settings",
          "The config.toml keys the game sets, each with its value, default and meaning; "
          "section picks one section.", _schema({"section": _REF}), _READ),
    _spec("run_check",
          "Check the whole game as Studio does: problems with file and line, and things "
          "nothing uses.", _schema(), _READ),
    _spec("propose_edit",
          "Propose a change to script files: each change replaces old_text, which must "
          "occur exactly once in file, with new_text; an empty old_text on a new "
          "script/….vns file creates it. Returns the diff and the problems it adds or "
          "fixes. Nothing is written.",
          _schema({"summary": {"type": "string", "maxLength": edits.SUMMARY_MAX_CHARS},
                   "changes": {"type": "array", "minItems": 1, "maxItems": edits.CHANGES_MAX,
                               "items": _schema({"file": _REF,
                                                 "old_text": {"type": "string"},
                                                 "new_text": {"type": "string"}},
                                                ("file", "old_text", "new_text"))}},
                  ("summary", "changes")), _READ),
    _spec("apply_edit",
          "Write a proposed change to disk, by the id propose_edit gave, if the files are "
          "unchanged since. Each id works once.",
          _schema({"id": {"type": "string", "maxLength": 64}}, ("id",)), _WRITE),
    _spec("undo_apply",
          "Undo the last applied change, while its files still hold exactly what it "
          "wrote.", _schema(), _WRITE),
)


def specs_for(mode: str) -> tuple[dict, ...]:
    """The tools offered in ``mode``, as fresh copies (callers may serialize them)."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    return tuple(json.loads(json.dumps(spec)) for spec in TOOL_SPECS
                 if mode == MODE_MCP or spec["name"] not in WRITE_TOOLS)


# --- The writer seam (diskapply) ------------------------------------------------------------

class Writer(Protocol):
    def keep(self, proposal: edits.Proposal) -> str: ...

    def apply(self, args: object) -> ToolText: ...

    def undo(self, args: object) -> ToolText: ...


# --- Small helpers --------------------------------------------------------------------------

def _size_text(size: int) -> str:
    if size < 1024:
        return f"{size:,} bytes"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _place(file: str | None, line: int | None) -> str:
    if file is None:
        return "no file"
    return f"{one_line(file)} line {line}" if line is not None else one_line(file)


def _plural(count: int, word: str) -> str:
    return f"{count:,} {word}" if count == 1 else f"{count:,} {word}s"


def _totals(run: CheckRun) -> str:
    result = run.result
    assert result is not None
    errors = sum(1 for p in result.problems if p.severity == "error")
    warnings = sum(1 for p in result.problems if p.severity == "warning")
    if result.problem_total == 0:
        return "no problems"
    shown = f"{_plural(errors, 'error')}, {_plural(warnings, 'warning')}"
    if result.problem_total > len(result.problems):
        shown += f" ({result.problem_total:,} problems in all)"
    return shown


def _rows_by_name(rows: Iterable[object], name: str) -> list[object]:
    return [row for row in rows if getattr(row, "name", None) == name]


# Name kind → the check's use kinds counting its uses (dbmodel's table, by check kind).
USE_KINDS: Final[Mapping[str, tuple[str, ...]]] = {
    "character": ("character_use",), "image": ("image_use",), "audio": ("audio_use",),
    "variable": ("variable_use",), "meter": ("meter_use",), "tip": ("codex_use",),
    "item": ("codex_use",), "route": ("route_use",),
    "transition": ("transition_use", "define_use"), "position": ("position_use",),
    "ending": ("route_until",), "style": ("style_use",), "minigame": ("minigame_use",),
    "meta_file": ("meta_file_use",)}


# --- The tools ------------------------------------------------------------------------------

class ToolBox:
    """The tools over one ``Workspace`` in one mode (``MODE_MCP``, ``MODE_READ_ONLY``,
    ``MODE_PANE``)."""

    def __init__(self, workspace: Workspace, mode: str = MODE_MCP, *,
                 writer: Writer | None = None,
                 on_proposal: Callable[[edits.Proposal], None] | None = None) -> None:
        self.specs = specs_for(mode)
        self.ws = workspace
        self.mode = mode
        self.writer = writer
        self.on_proposal = on_proposal
        handlers: dict[str, Callable[[object], ToolText]] = {
            "language_reference": self._language_reference,
            "language_docs": self._language_docs,
            "project_summary": self._project_summary,
            "list_files": self._list_files,
            "read_script": self._read_script,
            "search_scripts": self._search_scripts,
            "story_map": self._story_map,
            "scene": self._scene,
            "names": self._names,
            "lookup": self._lookup,
            "game_settings": self._game_settings,
            "run_check": self._run_check,
            "propose_edit": self._propose_edit,
            "apply_edit": self._apply_edit,
            "undo_apply": self._undo_apply,
        }
        self._handlers = {spec["name"]: handlers[spec["name"]] for spec in self.specs}

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._handlers)

    def call(self, name: object, args: object) -> ToolText:
        """Run tool ``name``. A refusal or an unknown tool is an error result."""
        handler = self._handlers.get(name) if type(name) is str else None   # type: ignore[arg-type]
        if handler is None:
            return ToolText.error(UNKNOWN_TOOL.format(name=shown_value(name)))
        try:
            return handler(args)
        except ToolError as exc:
            return ToolText.error(exc.text)
        except Exception as exc:       # a tool bug must not end the server or the chat
            log.warning("tool %s failed: %s", name, type(exc).__name__)
            return ToolText.error(TOOL_FAILED)

    # -- reference ---------------------------------------------------------------------------

    def _language_reference(self, args: object) -> ToolText:
        check_keys(args)
        out = TextOut()
        out.line(build_reference())
        return out.result()

    def _language_docs(self, args: object) -> ToolText:
        args = check_keys(args, ("topic",))
        topics = doc_topics()
        topic = select(args["topic"], doc_topic_names(), listing=topics, noun="Topics")
        out = TextOut()
        out.line(doc_section(topic) or "")
        return out.result()

    # -- the game ----------------------------------------------------------------------------

    def _config(self, table: RefTable) -> dict:
        if not table.config:
            return {}
        try:
            data = tomllib.loads(self.ws.read(CONFIG_REF).text)
        except (ToolError, tomllib.TOMLDecodeError, RecursionError):
            return {}
        return data

    def _project_summary(self, args: object) -> ToolText:
        check_keys(args)
        table = self.ws.table()
        run = self.ws.last_check()
        out = TextOut()
        game = self._config(table).get("game")
        title = game.get("title") if isinstance(game, dict) else None
        out.echo("Title: ", title if type(title) is str else UNTITLED)
        out.record_config()
        out.line(f"Start scene: {START_SCENE}")
        out.line(f"Script files ({len(table.scripts):,}):")
        rows = []
        for ref in table.scripts[:NAMES_MAX]:
            try:
                text = self.ws.read(ref).text
                count = text.count("\n") + 1 if text else 0
                rows.append(f"{one_line(ref)}: {_plural(count, 'line')}")
            except ToolError as exc:
                rows.append(f"{one_line(ref)}: {exc.text}")
        out.rows(rows, NAMES_MAX, len(table.scripts))
        out.record_names()
        if run.result is None:
            out.line(run.failure_text)
            return out.result()
        result = run.result
        counts = []
        for kind, word in (("label", "scene"), ("character", "character"),
                           ("image", "picture"), ("audio", "sound")):
            total = result.name_totals.get(kind, len(result.names.get(kind, ())))
            counts.append(_plural(total, word))
        out.line(", ".join(counts) + ".")
        out.line(f"Last check: {_totals(run)}.")
        if not run.launch:
            out.line(self._no_launch_text())
        return out.result()

    def _no_launch_text(self) -> str:
        return NOT_ARMED if self.mode == MODE_PANE else WITHOUT_CODE

    def _list_files(self, args: object) -> ToolText:
        args = check_keys(args, (), ("group",))
        table = self.ws.table()
        keys = (table.group(args["group"]),) if "group" in args else table.group_keys
        out = TextOut()
        for key in keys:
            group = next(g for g in ASSET_GROUPS if g.key == key)
            listing = table.group_listing(key)
            out.line(f"{group.title} ({group.folder}/): {_plural(len(listing.refs), 'file')}")
            rows = []
            for ref in listing.refs[:NAMES_MAX]:
                try:
                    size = _size_text(self.ws.paths.file_size(ref))
                except Exception:              # gone or not a regular file since the listing
                    size = "size unknown"
                rows.append(f"{one_line(ref)} ({size})")
            out.rows(rows, NAMES_MAX, len(listing.refs))
            if listing.truncated:
                out.line("The folder has more files than Studio lists.")
        out.record_names()
        return out.result()

    def _read_script(self, args: object) -> ToolText:
        args = check_keys(args, ("file",), ("first_line", "last_line"))
        ref = self.ws.table().file(args["file"])
        lines = self.ws.read(ref).lines
        total = 0 if lines == [""] else len(lines)
        first = int_arg(args, "first_line", default=1, low=1, high=max(total, 1))
        last = int_arg(args, "last_line", default=first + READ_MAX_LINES - 1, low=first,
                       high=max(total, first))
        last = min(last, first + READ_MAX_LINES - 1, total)
        # Keep the block and the closing lines inside the result's cap.
        budget = TOOL_TEXT_MAX_CHARS - 400
        width = line_width(last)
        for number in range(first, last + 1):
            budget -= len(numbered_line(number, lines[number - 1], width)) + 1
            if budget < 0:
                last = max(first, number - 1)
                break
        out = TextOut()
        out.line(f"{one_line(ref)} has {_plural(total, 'line')}.")
        if total:
            out.block(ref, lines[first - 1:last], first)
        if last < total:
            out.line(f"Lines {last + 1}–{min(total, last + READ_MAX_LINES)} are next: "
                     f"read_script with first_line {last + 1}.")
        return out.result()

    def _search_scripts(self, args: object) -> ToolText:
        args = check_keys(args, ("text",), ("match_case",))
        needle = text_arg(args, "text", limit=SEARCH_TEXT_MAX_CHARS)
        match_case = flag_arg(args, "match_case", default=False)
        if not needle:
            raise ToolError(EMPTY_SEARCH)
        if not match_case:
            needle = needle.casefold()
        table = self.ws.table()
        found: list[tuple[str, list[tuple[int, str]]]] = []
        total = kept = 0
        for ref in table.scripts:
            try:
                lines = self.ws.read(ref).lines
            except ToolError:
                continue
            hits: list[tuple[int, str]] = []
            for number, line in enumerate(lines, 1):
                if needle in (line if match_case else line.casefold()):
                    total += 1
                    if kept < HITS_MAX:
                        hits.append((number, line))
                        kept += 1
            if hits:
                found.append((ref, hits))
        out = TextOut()
        out.line(f"{_plural(total, 'matching line')}.")
        for ref, hits in found:
            out.line(f"{one_line(ref)}, matching lines:")
            width = line_width(hits[-1][0])
            for number, line in hits:
                if out.line(numbered_line(number, line, width)):
                    out.record_range(ref, number, number)
        if total > kept:
            out.line(f"…and {total - kept:,} more")
        return out.result()

    # -- the story ---------------------------------------------------------------------------

    def _checked(self) -> CheckRun:
        run = self.ws.last_check()
        if run.result is None:
            raise ToolError(run.failure_text)
        return run

    def _story_map(self, args: object) -> ToolText:
        check_keys(args)
        result = self._checked().result
        assert result is not None
        if result.links is None:
            return ToolText(NOT_LOADED)
        out = TextOut()
        scenes = result.names.get("label", ())
        total = result.name_totals.get("label", len(scenes))
        out.line(f"Scenes ({total:,}):")
        out.rows((f"{one_line(e.name)}: {_place(e.file, e.line)}" for e in scenes),
                 NAMES_MAX, total)
        out.line(f"Arrows ({result.link_total:,}):")
        out.rows((self._arrow(link) for link in result.links), ARROWS_MAX, result.link_total)
        unreached = result.names.get("unreached", ())
        if unreached:
            out.line("Scenes nothing reaches: "
                     + ", ".join(one_line(e.name) for e in unreached[:NAMES_MAX]))
        return out.result()

    @staticmethod
    def _arrow(link: object) -> str:
        parts = [link.kind]                                     # type: ignore[attr-defined]
        if link.choice is not None:                             # type: ignore[attr-defined]
            parts.append("choice " + one_line(link.choice))     # type: ignore[attr-defined]
        if link.conditional:                                    # type: ignore[attr-defined]
            parts.append("conditional")
        return (f"{one_line(link.src)} → {one_line(link.dst)} ({', '.join(parts)}) "  # type: ignore[attr-defined]
                f"at {_place(link.file, link.line)}")                                  # type: ignore[attr-defined]

    def _scene(self, args: object) -> ToolText:
        args = check_keys(args, ("label",))
        table = self.ws.table(names=True)
        label = table.label(args["label"])
        result = self._checked().result
        assert result is not None
        entry = next(e for e in result.names.get("label", ()) if e.name == label)
        shown = one_line(entry.file or "")
        if entry.file is None or not table.is_script(entry.file):
            raise ToolError(SCENE_MOVED.format(label=one_line(label), file=shown))
        lines = self.ws.read(entry.file).lines
        span = next(((first, last) for name, first, last in chunks("\n".join(lines))
                     if name == label), None)
        if span is None:
            raise ToolError(SCENE_MOVED.format(label=one_line(label), file=shown))
        first, last = span
        while last > first and not lines[last - 1].strip():
            last -= 1
        cut = min(last, first + READ_MAX_LINES - 1)
        out = TextOut()
        out.block(entry.file, lines[first - 1:cut], first)
        if cut < last:
            out.line(f"The scene goes on to line {last}: read_script with first_line "
                     f"{cut + 1}.")
        links = result.links or ()
        into = [self._arrow(link) for link in links if link.dst == label]
        out_of = [self._arrow(link) for link in links if link.src == label]
        out.line(f"Arrows in ({len(into):,}):")
        out.rows(into, USES_MAX)
        out.line(f"Arrows out ({len(out_of):,}):")
        out.rows(out_of, USES_MAX)
        return out.result()

    def _names(self, args: object) -> ToolText:
        args = check_keys(args, (), ("kind",))
        table = self.ws.table(names=True)
        result = self._checked().result
        assert result is not None
        out = TextOut()
        out.record_names()
        if "kind" not in args:
            out.line("Name kinds (from the last check):")
            out.rows((f"{one_line(kind)}: {result.name_totals.get(kind, len(entries)):,}"
                      for kind, entries in result.names.items()), NAMES_MAX)
            return out.result()
        kind = table.kind(args["kind"])
        entries = result.names.get(kind, ())
        uses = [row for use in USE_KINDS.get(kind, (f"{kind}_use",))
                for row in result.names.get(use, ())]
        counts: dict[str, int] = {}
        for row in uses:
            counts[row.name] = counts.get(row.name, 0) + 1
        total = result.name_totals.get(kind, len(entries))
        out.line(f"{one_line(kind)} ({total:,}):")
        rows = []
        for entry in entries:
            row = f"{one_line(entry.name)}: {_place(entry.file, entry.line)}"
            if uses:
                row += f", used {_plural(counts.get(entry.name, 0), 'time')}"
            rows.append(row)
        out.rows(rows, NAMES_MAX, total)
        return out.result()

    def _lookup(self, args: object) -> ToolText:
        args = check_keys(args, ("kind", "name"))
        table = self.ws.table(names=True)
        name = table.name(args["kind"], args["name"])
        kind = table.kind(args["kind"])
        result = self._checked().result
        assert result is not None
        out = TextOut()
        entry = _rows_by_name(result.names.get(kind, ()), name)[0]
        out.line(f"{one_line(kind)} {one_line(name)}: declared at "
                 f"{_place(entry.file, entry.line)}")         # type: ignore[attr-defined]
        if kind == "label":
            places = [self._arrow(link) for link in (result.links or ()) if link.dst == name]
        else:
            places = [_place(row.file, row.line)               # type: ignore[attr-defined]
                      for use in USE_KINDS.get(kind, (f"{kind}_use",))
                      for row in _rows_by_name(result.names.get(use, ()), name)]
        out.line(f"Used in {_plural(len(places), 'place')}:")
        out.rows(places, USES_MAX)
        values = self._values(table, entry, name)
        if values:
            out.line("Values:")
            out.rows(values, NAMES_MAX)
        out.record_names()
        return out.result()

    def _values(self, table: RefTable, entry: object, name: str) -> list[str]:
        """F47's form values of the declaration at ``entry``'s place, when a reader reads it."""
        ref, line = getattr(entry, "file", None), getattr(entry, "line", None)
        if not table.is_script(ref):
            return []
        try:
            text = self.ws.read(ref).text                       # type: ignore[arg-type]
        except ToolError:
            return []
        for decl in dec.scan({ref: text}):                      # type: ignore[dict-item]
            if decl.name == name and decl.first == line and decl.values is not None:
                return [f"{one_line(str(key))}: {one_line(_shown(value))}"
                        for key, value in decl.values.items()]
        return []

    def _game_settings(self, args: object) -> ToolText:
        args = check_keys(args, (), ("section",))
        table = self.ws.table()
        data = self._config(table)
        found: list[tuple[str, str, object]] = []
        stack: list[tuple[str, dict]] = [(name, value) for name, value in reversed(data.items())
                                         if isinstance(value, dict)]
        while stack:
            path, values = stack.pop()
            inner = []
            for key, value in values.items():
                if isinstance(value, dict):
                    inner.append((f"{path}.{key}", value))
                else:
                    found.append((path, key, value))
            stack.extend(reversed(inner))
        sections = list(dict.fromkeys(path for path, _, _ in found))
        if "section" in args:
            wanted = select(args["section"], frozenset(sections), listing=sections,
                            noun="Sections")
            found = [row for row in found if row[0] == wanted]
        out = TextOut()
        out.record_config()
        if not table.config:
            out.line("The game has no config.toml, so every setting is its default.")
            return out.result()
        out.line(f"Set keys ({len(found):,}):")
        out.rows((self._setting(path, key, value) for path, key, value in found), NAMES_MAX,
                 len(found))
        return out.result()

    @staticmethod
    def _setting(section: str, key: str, value: object) -> str:
        doc = key_help(section, key)
        row = f"[{one_line(section)}] {one_line(key)} = {one_line(_shown(value))}"
        if doc is None:
            return row + " (not a key the engine knows)"
        marker = "   # default"
        default = doc.example.split(" = ", 1)[1][:-len(marker)] \
            if doc.example.endswith(marker) and " = " in doc.example else None
        if default is not None:
            row += f" (default {one_line(default)})"
        return row + f": {one_line(doc.summary)}"

    def _run_check(self, args: object) -> ToolText:
        check_keys(args)
        run = self.ws.base_check()
        if run.result is None:
            return ToolText(run.failure_text)
        result = run.result
        out = TextOut()
        out.line(f"Checked: {_totals(run)}.")
        if not run.launch:
            out.line(self._no_launch_text())
        shown = out.rows((self._problem(item) for item in result.problems), PROBLEMS_MAX,
                         result.problem_total)
        out.record_problems(shown)
        lint = [(kind, row) for kind in LINT_KINDS for row in result.names.get(kind, ())]
        if lint:
            out.line("Not used or not reached (lint):")
            out.rows((f"{LINT_KINDS[kind].code} {LINT_KINDS[kind].kind_line}: "
                      f"{one_line(row.name)} ({_place(row.file, row.line)})"
                      for kind, row in lint), PROBLEMS_MAX)
            out.record_names()
        return out.result()

    @staticmethod
    def _problem(item: object) -> str:
        place = _place(item.file, item.line)                      # type: ignore[attr-defined]
        if item.column is not None and item.line is not None:     # type: ignore[attr-defined]
            place += f", column {item.column}"                    # type: ignore[attr-defined]
        code = f" {item.code}" if item.code else ""               # type: ignore[attr-defined]
        return (f"{item.severity}{code} {place} ({item.source}): "  # type: ignore[attr-defined]
                f"{one_line(item.text)}")                         # type: ignore[attr-defined]

    # -- edits -------------------------------------------------------------------------------

    def _propose_edit(self, args: object) -> ToolText:
        proposal = edits.propose(self.ws, args)
        if self.on_proposal is not None:
            self.on_proposal(proposal)
        if self.mode == MODE_PANE:
            return edits.render(proposal, card=True)
        if self.mode == MODE_MCP and self.writer is not None:
            return edits.render(proposal, id=self.writer.keep(proposal))
        shown = edits.render(proposal)
        return ToolText(shown.text + "\n" + READ_ONLY_NOTE, shown.sent)

    def _apply_edit(self, args: object) -> ToolText:
        if self.writer is None:
            return ToolText.error(NO_WRITER)
        return self.writer.apply(args)

    def _undo_apply(self, args: object) -> ToolText:
        if self.writer is None:
            return ToolText.error(NO_WRITER)
        return self.writer.undo(args)


def _shown(value: object) -> str:
    """A config or declaration value as text (TOML-like; never ``repr`` of an object)."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return type(value).__name__


__all__ = ["MODES", "MODE_MCP", "MODE_PANE", "MODE_READ_ONLY", "READ_ONLY_NOTE", "TOOL_FAILED",
           "TOOL_SPECS", "ToolBox", "UNKNOWN_TOOL", "USE_KINDS", "WRITE_TOOLS", "Writer",
           "specs_for"]

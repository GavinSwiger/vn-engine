"""The Build dialog's model: field checks, hints, the ``config.toml`` plan, the child's command
line, and every text the dialog's views show (F42 ``04-technical.md`` §3.2, §7.6; ``01`` §6;
PR-F42-09, -10, -13, -21; ``07`` I-6, I-11).

Why this module exists: the dialog (``builddialog.py``, W2) should only lay out widgets. What
a field's message is, what ``Makes:`` says, which ``config.toml`` lines change on **Build**,
whether to ask ``REPLACE_ASK``, and the Finished/Failed views' words are decided here, in pure
Python, so they are tested without Tk and match the CLI (both read ``tools/build/texts``).

- ``BuildFields`` / ``initial_fields``: the dialog's values, from the editor's
  ``config.toml`` text and ``.studio/build.json`` (``buildprefs``).
- ``field_messages``: field (``name``, ``version``, ``id``, ``icon``, ``save_to``) → message;
  **Build** is on only when it is empty (``can_build``). ``name_hint``, ``makes_hint``,
  ``use_slug_text``, ``id_changed_text``.
- ``config_plan(text, fields)``: the changed ``[game] title``/``version``/``id`` and
  ``[window] icon`` (``None`` → removed, **Use default**) as **one** plan
  (``tomlpatch.plan_changes``) for ``win.apply_plan(plan.plan, plan.verify)`` (one undo
  step); ``verify`` is ``tomlpatch.verify``'s strict parse-back (``07`` I-8, SEC-F42-13).
- ``replace_question``: ``REPLACE_ASK``'s text when an earlier build is at the computed name
  (Studio then passes ``--replace``), else None (a non-build there is the child's
  ``B_NAME_TAKEN``).
- ``build_argv``: ``python -E -B -m engine build GAME --out X [--zip] [--replace]
  --report-to-editor``.
- ``finished_texts`` / ``failed_texts`` / ``cancelled_text`` / ``head_text``: the views'
  words from ``buildrunner``'s events.
- ``open_targets``: **Open folder** / **Run the game** use Studio's own computed
  ``<Save to>/<folder>`` after ``is_earlier_build``, never a path from an event (I-11).

Pure Python: no Tk, no pygame. Imports ``core``, the shared ``tools.build`` modules and its own
package.
"""

import os
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from engine.core.constants import CONFIG_FILENAME
from engine.core.errors import EngineError
from engine.core.imageheader import image_dimensions
from engine.core.paths import GamePaths, check_ref, engine_root
from engine.tools.build import names, texts, tree
from engine.tools.editor import buildprefs, tomlpatch
from engine.tools.editor.scriptedit import Plan, Refuse, apply_lines

FIELD_ICON: Final = "icon"
FIELD_SAVE_TO: Final = "save_to"
PLAN_TITLE: Final = "Game details for the build"
ICON_MAX_BYTES: Final = 16 << 20
ICON_MIN_SIDE: Final = 16
_DEFAULTS: Final = {"title": "Untitled Visual Novel", "version": "0.0.0"}   # config_schema's


@dataclass(frozen=True, slots=True)
class BuildFields:
    """The dialog's values. ``icon`` None means the engine icon (no ``[window] icon``);
    ``save_to`` is the entry's text."""
    title: str
    version: str
    app_id: str
    icon: str | None
    save_to: str
    zip: bool = True


def _config_values(text: str) -> dict[str, object]:
    try:
        doc = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return {}
    game = doc.get("game") if isinstance(doc.get("game"), dict) else {}
    window = doc.get("window") if isinstance(doc.get("window"), dict) else {}
    return {"title": game.get("title"), "version": game.get("version"),
            "id": game.get("id"), "icon": window.get("icon")}


def initial_fields(config_text: str, game_root: Path,
                   prefs: buildprefs.BuildPrefs | None = None) -> BuildFields:
    """The dialog's first values: ``config.toml``'s (as the editor holds it; a key that is
    missing or not a string gets the engine's default) and the remembered *Save to* and zip
    choice (default ``<game parent>/builds``, zip on)."""
    values = _config_values(config_text)
    prefs = prefs if prefs is not None else buildprefs.read_prefs(game_root)

    def text(key: str, default: str) -> str:
        value = values.get(key)
        return value if isinstance(value, str) else default

    icon = values.get("icon")
    return BuildFields(
        title=text("title", _DEFAULTS["title"]), version=text("version", _DEFAULTS["version"]),
        app_id=text("id", ""), icon=icon if isinstance(icon, str) and icon else None,
        save_to=str(buildprefs.save_to_or_default(game_root, prefs)), zip=prefs.zip)


# --- Field checks and hints (01 §6.1, §6.3) ----------------------------------------------------

def icon_problem(game_root: Path, ref: str | None) -> str | None:
    """``BAD_ICON``'s text unless ``ref`` is None (the engine icon) or a PNG in the game
    folder of at least 16×16 (read from its header; no decoding)."""
    if ref is None:
        return None
    bad = texts.FIELD_MESSAGES[texts.BAD_ICON]
    try:
        check_ref(ref)
        data = GamePaths.for_game(Path(game_root)).read_file(ref, max_bytes=ICON_MAX_BYTES,
                                                             regular=True)
    except (EngineError, OSError, ValueError):
        return bad
    found = image_dimensions(data)
    if found is None or found[0] != "png" or min(found[1], found[2]) < ICON_MIN_SIDE:
        return bad
    return None


def save_to_path(game_root: Path, save_to: str) -> Path | None:
    """The *Save to* entry as an absolute folder (relative text is taken from the game
    folder's parent, where the default lives), or None when empty."""
    text = save_to.strip()
    if not text:
        return None
    path = Path(os.path.expanduser(text))
    if not path.is_absolute():
        path = Path(os.path.abspath(game_root)).parent / path
    return Path(os.path.abspath(path))


def save_to_problem(game_root: Path, save_to: str, *, root: Path | None = None) -> str | None:
    """Empty → ``SAVE_TO_EMPTY``; inside the game folder, holding it, or inside
    ``<engine root>/engine`` → ``B_OUT_INSIDE``'s message (the child checks again)."""
    path = save_to_path(game_root, save_to)
    if path is None:
        return texts.SAVE_TO_EMPTY
    game = Path(game_root)
    engine_code = (root if root is not None else engine_root()) / "engine"
    if tree.real_inside(path, game) or tree.real_inside(game, path) \
            or tree.real_inside(path, engine_code):
        return texts.failure("B_OUT_INSIDE", game=game.name)[0]
    return None


def field_messages(fields: BuildFields, game_root: Path, *,
                   root: Path | None = None) -> dict[str, str]:
    """Every field with a problem → its message (it replaces the field's hint)."""
    problems = names.field_problems(fields.title, fields.version, fields.app_id)
    icon = icon_problem(game_root, fields.icon)
    if icon is not None:
        problems[FIELD_ICON] = icon
    save_to = save_to_problem(game_root, fields.save_to, root=root)
    if save_to is not None:
        problems[FIELD_SAVE_TO] = save_to
    return problems


def can_build(fields: BuildFields, game_root: Path, *, root: Path | None = None) -> bool:
    return not field_messages(fields, game_root, root=root)


def folder_of(fields: BuildFields) -> str:
    return names.folder_name(fields.title, fields.version, fields.app_id)


def exe_of(fields: BuildFields) -> str:
    return names.exe_name(fields.title, fields.app_id)


def name_hint(fields: BuildFields) -> str:
    return texts.NAME_HINT.format(exe=exe_of(fields))


def makes_hint(fields: BuildFields) -> str:
    return texts.MAKES.format(folder=folder_of(fields))


def use_slug_text(title: str) -> str:
    return names.use_slug_text(title)


def id_changed_text(last_id: str | None, app_id: str) -> str | None:
    """``ID_CHANGED`` when the remembered last built ID differs from a valid new one."""
    if not last_id or not app_id or last_id == app_id or names.check_id(app_id) is not None:
        return None
    return texts.ID_CHANGED.format(old=last_id, new=app_id)


def head_text(fields: BuildFields) -> str:
    return texts.HEAD.format(name=names.clean_name(fields.title, fields.app_id),
                             version=fields.version)


# --- config.toml (04 §7.6; SEC-F42-13) ---------------------------------------------------------

@dataclass(frozen=True)
class ConfigPlan:
    """The dialog's changed details as one ``tomlpatch`` plan (``plan_changes``): ``plan``
    for ``win.apply_plan(config.plan, config.verify)`` (one undo step); ``toml`` the
    ``TomlPlan``; ``changed`` its ``(section, key, value)`` changes (value None: removed)."""
    toml: tomlpatch.TomlPlan

    @property
    def plan(self) -> Plan:
        return self.toml.as_plan()

    @property
    def changed(self) -> tuple[tuple[str, str, object], ...]:
        return self.toml.changes

    def new_text(self, text: str) -> str:
        return "\n".join(apply_lines(text.split("\n"), self.toml.edits))

    def verify(self, texts_by_ref: Mapping[str, str]) -> bool:
        """For ``win.apply_plan``: ``tomlpatch.verify`` on the live ``config.toml`` text
        (guards, then the strict parse-back of ``07`` I-8)."""
        text = texts_by_ref.get(CONFIG_FILENAME)
        return text is not None and tomlpatch.verify(self.toml, text)


def _wanted(fields: BuildFields) -> list[tuple[str, str, object]]:
    return [("game", "title", fields.title), ("game", "version", fields.version),
            ("game", "id", fields.app_id), ("window", "icon", fields.icon)]


def config_plan(text: str, fields: BuildFields) -> ConfigPlan | Refuse | None:
    """The plan writing ``fields``' changed details into editor ``text`` (LF, no final
    break) with ``tomlpatch.plan_changes``, a ``Refuse`` (nothing is written; the dialog
    shows its text), or None when nothing changed."""
    planned = tomlpatch.plan_changes(text, _wanted(fields), title=PLAN_TITLE)
    if planned is None or isinstance(planned, Refuse):
        return planned
    return ConfigPlan(planned)


# --- Starting, replacing, and the views' texts --------------------------------------------------

def build_argv(game_root: Path, save_to: Path, *, zip: bool, replace: bool) -> list[str]:
    """The build child's command line (``procs.spawn`` starts it)."""
    return [sys.executable, "-E", "-B", "-m", "engine", "build", str(game_root),
            "--out", str(save_to), *(["--zip"] if zip else []),
            *(["--replace"] if replace else []), "--report-to-editor"]


def replace_question(save_to: Path, folder: str, *, with_zip: bool) -> str | None:
    """``REPLACE_ASK`` when an earlier build (or its zip) is at the computed name; None when
    the name is free or holds something else (the child reports ``B_NAME_TAKEN``)."""
    try:
        earlier = tree.find_earlier_build(save_to, folder, with_zip=with_zip)
    except texts.BuildStopped:
        return None
    if earlier is None:
        return None
    return texts.replace_ask(folder, earlier.zip)


@dataclass(frozen=True)
class FinishedTexts:
    done: str
    folder_line: str
    zip_line: str | None
    share: str
    smartscreen: str
    warnings: str | None
    left_out: str | None
    left_out_lines: tuple[str, ...]
    long_paths: str | None


def finished_texts(done) -> FinishedTexts:
    """The Finished view from a ``buildrunner.BuildDone``."""
    with_zip = done.zip is not None
    return FinishedTexts(
        done=texts.DONE,
        folder_line=texts.DONE_FOLDER.format(folder=done.folder,
                                             size=texts.format_size(done.bytes),
                                             files=texts.format_count(done.files)),
        zip_line=texts.DONE_ZIP.format(zip=done.zip, size=texts.format_size(done.zip_bytes or 0))
        if with_zip else None,
        share=texts.share_text(done.exe, done.folder, with_zip),
        smartscreen=texts.SMARTSCREEN,
        warnings=texts.warnings_text(done.warnings) if done.warnings else None,
        left_out=texts.left_out_text(done.left_out_total) if done.left_out_total else None,
        left_out_lines=tuple(texts.left_out_line(ref, reason) for ref, reason in done.left_out),
        long_paths=texts.LONG_PATHS.format(n=texts.format_count(done.long_paths),
                                           ref=done.long_path_example)
        if done.long_paths else None)


def failed_texts(failure) -> tuple[str, str, tuple[str, ...]]:
    """(message, fix, details) from a ``buildrunner.BuildFailure``; a value the child left
    out shows as its ``{placeholder}`` rather than breaking the view."""
    message, fix = texts.FAILURES.get(failure.code, texts.FAILURES["B_CRASHED"])
    values = _Lenient({key: texts.format_count(value) if type(value) is int else value
                       for key, value in failure.values.items()})
    if failure.code == "B_ERRORS" and failure.values.get("n") == 1:
        message = texts.B_ERRORS_ONE
    return message.format_map(values), fix.format_map(values), tuple(failure.details)


class _Lenient(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def cancelled_text(save_to: Path) -> str:
    return texts.CANCELLED.format(save_to=Path(save_to).name)


def open_targets(save_to: Path, folder: str, exe: str) -> tuple[Path, Path] | None:
    """(build folder, exe) for **Open folder** / **Run the game**: Studio's own computed
    ``<Save to>/<folder>``, only when it is an earlier build by the marker test (I-11)."""
    target = Path(save_to) / folder
    if not tree.is_earlier_build(target):
        return None
    return target, target / exe


__all__ = ["BuildFields", "ConfigPlan", "FIELD_ICON", "FIELD_SAVE_TO", "FinishedTexts",
           "build_argv", "can_build", "cancelled_text", "config_plan", "exe_of",
           "failed_texts", "field_messages", "finished_texts", "folder_of", "head_text",
           "icon_problem", "id_changed_text", "initial_fields", "makes_hint", "name_hint",
           "open_targets", "replace_question", "save_to_path", "save_to_problem",
           "use_slug_text"]

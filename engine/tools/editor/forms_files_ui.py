"""Studio's Meta file and Game UI forms (F47 W9; design §4.5, PR-F47-19; AC-F47-47, 48).

Why this module exists: F31's ``file`` lines and F32's ``ui`` lines were script-only rows; a
non-programmer now writes them with a form. Both are ordinary ``forms.CommandForm``s that
``forms.all_forms()`` adds (it imports this module inside the function, as this one imports
``forms``), so the Events gate keeps a row only when the form writes back what it read.

- **Meta file** (``file write|delete|exists|read "<name>" …``): what to do (``FILE_ACTIONS``:
  write, delete, check exists, read), the file name (picked from the originals in
  ``files/`` and the names the story already uses: the ``meta_file`` kind), the text a
  write puts in it (empty: a copy of ``files/<name>``), and "Result goes to" (a variable)
  for check exists and read. The text is written as typed (F31 keeps its braces), quoted by
  ``forms.quote``. ``problem`` says why a name or a read can't be written (E310's rule, and
  E315: only a ``.txt`` file can be read).
- **Game UI** (``ui style <name>|off``, ``ui saving|loading off ["reason"]|on``,
  ``ui delete saves``): one pick per line shape (``UI_ACTIONS``), the style (the config's
  ``[style.<name>]`` names, or ``off`` for the normal look) and the reason the Save or Load
  page shows. A reason is shown text, so a ``{`` typed in the form is written ``{{`` (F32's
  SR-F32-04, as Ending's card texts). Studio asks before inserting Delete all saves
  (``CONFIRM_DELETE``, ``formdialogs``).

Pure: no Tk.
"""

from collections.abc import Mapping
from typing import Final

from engine.core.constants import UI_REASON_MAX
from engine.script.metafiles import MetaFile, name_problem
from engine.script.nodes import Statement
from engine.script.ui import UiStatement
from engine.script.words import canonical_name
from engine.tools.editor.forms import CommandForm, Field, Values, _dot, _one_line, _tokens, quote
from engine.tools.editor.forms_more import _card_text, _unquote

# --- Meta file (F31) -------------------------------------------------------------------------

FILE_FORM: Final = "file"
FILE_ACTIONS: Final = ("write", "delete", "check exists", "read")
_VERBS: Final = dict(zip(FILE_ACTIONS, ("write", "delete", "exists", "read"), strict=True))
_FILE_WORDS: Final = {"write": "Write meta file", "delete": "Delete meta file",
                      "check exists": "Check meta file", "read": "Read meta file"}
COPY_ORIGINAL: Final = "a copy of files/{name}"
INTO_LABEL: Final = "Result goes to"
TEXT_LABEL: Final = "Text (empty: copy the original)"
NAME_RULE: Final = ("A meta file name is lowercase letters, digits, - or _ (up to 32), then "
                    ".chr or .txt.")
READ_TXT_ONLY: Final = "Only a .txt file can be read into a variable."
NEEDS_INTO: Final = "Pick the variable the result goes to."


def _file_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, MetaFile) or not tokens or len(tokens) < 3 \
            or tokens[:2] != ["file", node.verb] or tokens[2] != quote(node.name):
        return None
    action = next(a for a, verb in _VERBS.items() if verb == node.verb)
    values = {"action": action, "name": node.name, "text": "", "into": ""}
    rest = tokens[3:]
    if node.verb == "write":
        if node.text is None:
            return values if not rest else None
        if len(rest) != 1 or _unquote(rest[0]) != node.text or quote(node.text) != rest[0]:
            return None
        return {**values, "text": node.text}
    if node.verb == "delete":
        return values if not rest else None
    if len(rest) != 2 or rest[0] != "into" or canonical_name(rest[1]) != node.target:
        return None
    return {**values, "into": rest[1]}


def _file_action(values: Values) -> str:
    action = values.get("action") or FILE_ACTIONS[0]
    if action not in _VERBS:
        raise ValueError(f"no meta file action {action!r}")
    return action


def file_problem(values: Values) -> str | None:
    """Why the Meta file form can't write its line yet, or None."""
    name = values.get("name", "").strip()
    if not name:
        return None                                 # the preview just stays empty
    if name_problem(name) is not None:
        return NAME_RULE
    action = values.get("action") or FILE_ACTIONS[0]
    if action == "read" and not name.endswith(".txt"):
        return READ_TXT_ONLY
    return None


def _file_write(values: Values) -> str:
    action = _file_action(values)
    name = values["name"].strip()
    if not name or file_problem(values) is not None:
        raise ValueError(name)
    line = f"file {_VERBS[action]} {quote(name)}"
    if action == "write":
        text = values.get("text", "")
        return f"{line} {quote(text)}" if text else line
    if action == "delete":
        return line
    into = values.get("into", "").strip()
    if not into:
        raise ValueError(NEEDS_INTO)
    return f"{line} into {into}"


def _file_summary(values: Values) -> str:
    action = values.get("action") or FILE_ACTIONS[0]
    name = values.get("name", "")
    if action == "write":
        text = values.get("text", "")
        return _dot(name, _one_line(text) if text else COPY_ORIGINAL.format(name=name))
    if action == "delete":
        return name
    return f"{name} → {values.get('into', '')}"


# --- Game UI (F32) ---------------------------------------------------------------------------

UI_FORM: Final = "ui"
UI_ACTIONS: Final = ("style", "saving off", "saving on", "loading off", "loading on",
                     "delete all saves")
_UI_WORDS: Final = {"style": "UI style", "saving off": "Stop saving",
                    "saving on": "Allow saving", "loading off": "Stop loading",
                    "loading on": "Allow loading", "delete all saves": "Delete all saves"}
STYLE_OFF: Final = "off"
NORMAL_LOOK: Final = "off: the normal look"
OWN_WORDS: Final = "the game's own words"
REASON_LABEL: Final = "Reason shown (optional)"
REASON_LONG: Final = f"A reason can be at most {UI_REASON_MAX} characters."
CONFIRM_DELETE: Final = ("This line deletes every save of the player's game, auto-saves "
                         "included, when the story reaches it. Insert it?")
CONFIRM_BUTTONS: Final = ("Delete all saves", "Cancel")


def _ui_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, UiStatement) or not tokens or len(tokens) < 3 \
            or tokens[:2] != ["ui", node.form]:
        return None
    values = {"action": "", "style": "", "reason": ""}
    if node.form == "style":
        if len(tokens) != 3 or (node.style or STYLE_OFF) != tokens[2]:
            return None
        return {**values, "action": "style", "style": tokens[2]}
    if node.form == "delete":
        return {**values, "action": "delete all saves"} if tokens[2:] == ["saves"] else None
    switch = "on" if node.on else "off"
    if tokens[2] != switch:
        return None
    action = f"{node.form} {switch}"
    rest = tokens[3:]
    if not rest:
        return {**values, "action": action} if node.reason is None else None
    if node.on or node.reason is None or rest != [_card_text(node.reason)]:
        return None
    return {**values, "action": action, "reason": node.reason}


def ui_problem(values: Values) -> str | None:
    """Why the Game UI form can't write its line yet, or None."""
    action = values.get("action") or UI_ACTIONS[0]
    if action.endswith(" off") and len(values.get("reason", "")) > UI_REASON_MAX:
        return REASON_LONG
    return None


def _ui_write(values: Values) -> str:
    action = values.get("action") or UI_ACTIONS[0]
    if action not in UI_ACTIONS:
        raise ValueError(f"no ui action {action!r}")
    if action == "style":
        style = values.get("style", "").strip()
        if not style:
            raise ValueError("pick a style")
        return f"ui style {style}"
    if action == "delete all saves":
        return "ui delete saves"
    if ui_problem(values) is not None:
        raise ValueError(action)
    reason = values.get("reason", "")
    if action.endswith(" off") and reason:
        return f"ui {action} {_card_text(reason)}"
    return f"ui {action}"


def _ui_summary(values: Values) -> str:
    action = values.get("action") or UI_ACTIONS[0]
    if action == "style":
        style = values.get("style", "")
        return NORMAL_LOOK if style == STYLE_OFF else style
    if action.endswith(" off"):
        return _one_line(values.get("reason", "")) or OWN_WORDS
    return ""


# --- The forms -------------------------------------------------------------------------------

FORMS: tuple[CommandForm, ...] = (
    CommandForm(
        FILE_FORM, "Meta file", "Meta file",
        (("file", "file write"), ("file", "file delete"), ("file", "file exists"),
         ("file", "file read")), MetaFile,
        (Field("action", "What to do", "pick", options=FILE_ACTIONS),
         Field("name", "File name", "name", "meta_file"),
         Field("text", TEXT_LABEL, "text", optional=True),
         Field("into", INTO_LABEL, "name", "variable", optional=True)),
        _file_read, _file_write, _file_summary,
        lambda v: _FILE_WORDS.get(v.get("action") or FILE_ACTIONS[0], "Meta file")),
    CommandForm(
        UI_FORM, "Game UI", "Game UI",
        (("ui", "ui style"), ("ui", "ui saving"), ("ui", "ui loading"), ("ui", "ui delete")),
        UiStatement,
        (Field("action", "What to change", "pick", options=UI_ACTIONS),
         Field("style", "Style", "name", "style", optional=True),
         Field("reason", REASON_LABEL, "text", optional=True)),
        _ui_read, _ui_write, _ui_summary,
        lambda v: _UI_WORDS.get(v.get("action") or UI_ACTIONS[0], "Game UI")),
)

# The dialog's per-form rules (``formdialogs``): which fields each pick shows, why OK waits,
# and the pick that asks before it is inserted.
SWITCHED: Final[Mapping[str, tuple[str, Mapping[str, tuple[str, ...]]]]] = {
    FILE_FORM: ("action", {"write": ("text",), "delete": (), "check exists": ("into",),
                           "read": ("into",)}),
    UI_FORM: ("action", {"style": ("style",), "saving off": ("reason",), "saving on": (),
                         "loading off": ("reason",), "loading on": (),
                         "delete all saves": ()}),
}
PROBLEMS: Final = {FILE_FORM: file_problem, UI_FORM: ui_problem}
CONFIRM: Final = {UI_FORM: ("action", "delete all saves", CONFIRM_DELETE, CONFIRM_BUTTONS)}


def new_values(form_key: str, doc_syntax: str) -> dict[str, str] | None:
    """A new row's pick from the Insert entry it came from (``file read …`` starts at read,
    ``ui loading …`` at loading off), or None for another form."""
    words = doc_syntax.split()
    if form_key == FILE_FORM and len(words) > 1:
        action = next((a for a, verb in _VERBS.items() if verb == words[1]), None)
        return {"action": action} if action else None
    if form_key == UI_FORM and len(words) > 1:
        found = {"style": "style", "saving": "saving off", "loading": "loading off",
                 "delete": "delete all saves"}.get(words[1])
        return {"action": found} if found else None
    return None


__all__ = ["CONFIRM", "CONFIRM_BUTTONS", "CONFIRM_DELETE", "COPY_ORIGINAL", "FILE_ACTIONS",
           "FILE_FORM", "FORMS", "INTO_LABEL", "NAME_RULE", "NEEDS_INTO", "NORMAL_LOOK",
           "OWN_WORDS", "PROBLEMS", "READ_TXT_ONLY", "REASON_LABEL", "REASON_LONG", "STYLE_OFF",
           "SWITCHED", "TEXT_LABEL", "UI_ACTIONS", "UI_FORM", "file_problem", "new_values",
           "ui_problem"]

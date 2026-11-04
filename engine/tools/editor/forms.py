"""Studio's command forms and Events rows (F46 ``04-technical.md`` §3.3, §4, §6.7; design
§6.2, §6.4).

Why this module exists: the Events tab shows a scene as one row per statement, and a form can
rewrite a row's line. The ``.vns`` text stays the only truth, so a form must give back exactly
what it read, or the row stays a plain Script row. Pure: no Tk.

- ``FORMS`` sits beside F45's statement docs: each ``CommandForm`` names the docs it covers
  (``form_for_doc``), and ``TEXT_ONLY`` maps each doc that inserts its example as text to
  the reason shown to authors (PR-F46-24, PR-F47-06; ``missing_forms`` is the completeness
  check). ``all_forms()`` adds F47's forms (``forms_more.FORMS``: Ending, Transition, Shake
  screen, …) and the Choice form; lookups and rows use it.
- ``read(node, code)`` gives a form's values (strings as written, so ``pause 1`` stays ``1``)
  or None when the line holds anything the form can't (``behind``, ``zoom``, a colour,
  ``volume``, …). ``write(values)`` gives one code line, ``summary(values)`` the row text.
- The gate (§6.7.2): ``rows`` writes every candidate into one probe text, parses it once, and
  keeps a form row only if the probe node's ``shape`` equals the original's (and, for a
  one-line head, the written line equals the code with whitespace collapsed outside quotes:
  TR-F46-01). Anything else is a Script row.
- The Choice form (§6.7.4) reads the parsed ``Menu`` (``read_choice``) and writes raw line
  patches (``choice_patches``): the menu is never regenerated, so its comments and ``voice``
  line survive.
  F51: its time limit (``ChoiceValues.time``, ``ChoiceItem.timeout``) patches only the
  ``menu`` line and the choice headers it changes; ``choice_problems`` is the form's problem
  line, ``default_timeout`` the option ticking the box picks.

Lines here are chunk-relative, as ``scenes`` gives them: ``lines[k - 1]`` is chunk line ``k``
(the label line is 1).
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import Final, Literal

from engine.core.constants import BUILTIN_POSITIONS
from engine.script.audio import PlayAudio, StopAudio
from engine.script.diagnostics import DiagnosticSink
from engine.script.effects import Pause
from engine.script.menu import MENU_MAX_CHOICES, Menu
from engine.script.nodes import (
    Call, If, Jump, Label, PythonLine, Return, Say, ScriptFile, Statement)
from engine.script.parser import parse_file
from engine.script.points import PointsChange
from engine.script.stage import Hide, Scene, Show
from engine.script.statement_docs import StatementDoc, all_docs
from engine.script.statements import ParseContext
from engine.tools.editor import conditions, scenes
from engine.tools.editor.scenes import SceneRead, Span

Values = Mapping[str, str]

CHOICE_FORM: Final = "menu"            # the multi-line Choice form (§6.7.4)
PROBE_LABEL: Final = "studio_probe"
PROBE_INDENT: Final = "    "
END_WORD: Final = "◆"
NOTHING: Final = "(nothing)"
NO_QUESTION: Final = "(no question)"
MORE_TEXT: Final = "{n} more lines. Open the text to see them."
CHOICE_LIMIT_TEXT: Final = f"A choice can have at most {MENU_MAX_CHOICES} options."
CHOICE_EMPTY_TEXT: Final = "A choice needs at least one option."
IN_TEXT: Final = "(lines in the text)"     # a choice block the form can't hold
CONTINUES: Final = "continues here"
# F51 (01 §7): the Choice form's time limit.
TIMEOUT_SUMMARY: Final = "when time runs out"
TIME_DEFAULT: Final = "5"
TIME_RE: Final = re.compile(r"[0-9]+(?:\.[0-9]+)?")       # SR-F51-01 (script/menu.py)
TIMEOUT_PICK_TEXT: Final = "Pick the option to choose when time runs out."
TIMEOUT_CONDITION_TEXT: Final = (
    'The option chosen when time runs out can\'t have an "Only show when" condition. Clear '
    "its condition, or pick another option.")
TIME_RANGE_TEXT: Final = "The time limit is 1 to 60 seconds."

# Why a doc inserts its example as text, with no form (PR-F46-24, PR-F47-06), shown to
# authors in the Insert picker. ``TEXT_ONLY_REASONS``: F47 §4.8's, word for word.
PYTHON_CODE_REASON: Final = "Python code: for things the forms can't do."
PYTHON_VALUES_REASON: Final = (
    "Python values: use the Database for characters, transitions and minigame data.")
INCLUDE_REASON: Final = "Studio adds these when you make script files."
STORY_MAP_REASON: Final = "Made on the Story map / part of Show character."
PLUGIN_REASON: Final = "Plugin code is written in Python (docs/minigames.md)."
TEXT_ONLY_REASONS: Final = (PYTHON_CODE_REASON, PYTHON_VALUES_REASON, INCLUDE_REASON,
                            STORY_MAP_REASON, PLUGIN_REASON)
# Not in §4.8 (F47 P2-A): declarations the Database writes, and statements whose form is a
# later F47 step (none left: W8 dropped ``minigame``, ``minigamedata.FORM``; W9 ``file`` and
# ``ui``, ``forms_files_ui``; P3-C ``flowchart`` and ``rollback``, ``forms_more``).
DATABASE_REASON: Final = (
    "Made in the Database: variables, pictures, meters, codex entries and routes.")
NO_FORM_YET_REASON: Final = "No form for this yet: it goes in as a script line."

# Doc key → its reason, for the key's docs with no form. ``points`` is the declaration
# (``points <name> +=`` has the Change meter form); ``lock``'s are the route and codex
# declarations (``lock route|ending``/``lock tip|item <name>`` have the Lock form: P2-B).
# ``missing_forms`` fails on a key with an empty reason.
TEXT_ONLY: Final[Mapping[str, str]] = MappingProxyType({
    "at": STORY_MAP_REASON, "label": STORY_MAP_REASON,
    "define": PYTHON_VALUES_REASON, "include": INCLUDE_REASON,
    **dict.fromkeys(("default", "image", "points", "lock"), DATABASE_REASON)})
# A doc in this group is a top-level declaration, never an Events row: it has no form.
DECLARATIONS_GROUP: Final = "Declarations"

_SHAPE_SKIP: Final = frozenset(("file", "line", "end_line", "column", "sid", "label", "path",
                                "code", "comment_free", "block"))
_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[^\s"]+', re.DOTALL)
_NUMBER = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)")
_NAME = re.compile(r"[^\W\d]\w*")
_LITERAL = re.compile(r'-?\d+(?:\.\d+)?|"(?:[^"\\\n]|\\.)*"|True|False')
_SET = re.compile(rf"\$ ({_NAME.pattern}) (=|\+=|-=) ({_LITERAL.pattern})")
_POINTS = re.compile(r"points (\S+) (\+=|-=|=) (-?\d+)")
_IF_HEAD = re.compile(r"(if|elif)[ \t]+(.+?)[ \t]*:", re.DOTALL)
_ELSE_HEAD = re.compile(r"else[ \t]*:")


# --- Data -------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Field:
    """One form field. ``name_kind``: the F45 name kind its picker offers. ``shown``: a pick's
    plain words, one per option (the list shows these; the values keep the script words)."""

    key: str
    label: str
    kind: Literal["text", "name", "number", "pick", "flag", "scene"]
    name_kind: str | None = None
    options: tuple[str, ...] = ()
    optional: bool = False
    shown: tuple[str, ...] = ()

    def shown_for(self, option: str) -> str:
        """The plain words the list shows for ``option`` (the option itself without any)."""
        if self.shown and option in self.options:
            return self.shown[self.options.index(option)]
        return option

    def option_for(self, shown: str) -> str:
        """The script word for the plain words ``shown`` (``shown`` itself without any)."""
        if self.shown and shown in self.shown:
            return self.options[self.shown.index(shown)]
        return shown


@dataclass(frozen=True, slots=True)
class CommandForm:
    """One form. ``docs``: (doc key, syntax prefix) pairs it covers; ``words`` gives the row
    word when it depends on the values (Say/Narration, Music/Stop music)."""

    key: str
    title: str
    word: str
    docs: tuple[tuple[str, str], ...]
    node: type[Statement] | tuple[type[Statement], ...]
    fields: tuple[Field, ...]
    read: Callable[[Statement, str], dict[str, str] | None]
    write: Callable[[Values], str]
    summary: Callable[[Values], str]
    words: Callable[[Values], str] | None = None

    def row_word(self, values: Values) -> str:
        return self.word if self.words is None else self.words(values)


@dataclass(frozen=True, slots=True)
class Row:
    """One Events row. ``kind``: ``stmt`` (statement ``stmt``), ``header`` (a choice or an
    ``elif``/``else`` branch of statement ``stmt``, heading block ``block``), ``end`` (the ◆
    ending block ``block``; ``stmt`` None) or ``more`` (the row-cap line). ``form`` None: a
    Script row (or ◆, ``(nothing)``, the cap line)."""

    stmt: int | None
    block: int
    depth: int
    word: str
    summary: str
    form: str | None
    values: Mapping[str, str] | None
    kind: Literal["stmt", "header", "end", "more"] = "stmt"

    @property
    def text(self) -> str:
        return f"{self.word}  {self.summary}" if self.summary else self.word


@dataclass(frozen=True, slots=True)
class ChoiceItem:
    """One choice in the Choice form. ``goes``: a scene, or None for "continues here";
    ``in_text``: its block is neither, so the form keeps it as is (read-only). ``old``: the
    index of the choice it was read from (None: new). ``timeout`` (F51): the option time
    running out picks (written only while the menu has a ``time``)."""

    text: str
    condition: str = ""
    goes: str | None = None
    in_text: bool = False
    old: int | None = None
    timeout: bool = False


@dataclass(frozen=True, slots=True)
class ChoiceValues:
    """The Choice form's values; ``question`` "" means no question. ``time`` (F51): the time
    limit in seconds as written (``menu time 5:``), "" for none."""

    speaker: str = ""
    look: str = ""
    question: str = ""
    choices: tuple[ChoiceItem, ...] = ()
    time: str = ""


@dataclass(frozen=True, slots=True)
class Patch:
    """Replace chunk lines ``first``..``last`` with ``lines`` (``last = first - 1``
    inserts before ``first``)."""

    first: int
    last: int
    lines: tuple[str, ...]


# --- Text helpers -----------------------------------------------------------------------------

def quote(text: str) -> str:
    """``text`` as script quoted text: ``"…"``, escaping ``\\``, ``"`` and a newline."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _comment_at(line: str, quote_char: str | None) -> tuple[int | None, str | None]:
    """The index of the first ``#`` outside a string, and the string still open at the end."""
    i, n = 0, len(line)
    while i < n:
        char = line[i]
        if quote_char is not None:
            if char == "\\":
                i += 2
                continue
            if char == quote_char:
                quote_char = None
        elif char in "\"'":
            quote_char = char
        elif char == "#":
            return i, None
        i += 1
    return None, quote_char


def code_of(lines: Sequence[str]) -> tuple[str, str]:
    """A head's code (its indent and comments removed; continuation lines joined with
    ``\\n``) and its trailing comment with the spaces before it (``"  # first line"``)."""
    bodies: list[str] = []
    comment = ""
    open_quote: str | None = None
    for line in lines:
        cut, open_quote = _comment_at(line, open_quote)
        if cut is None:
            bodies.append(line.rstrip())
            continue
        body = line[:cut].rstrip()
        bodies.append(body)
        comment = line[len(body):].rstrip()
    return "\n".join(bodies).strip(), comment


def _collapse(code: str) -> str:
    """``code`` with whitespace runs outside ``"…"`` collapsed to one space."""
    out: list[str] = []
    for match in re.finditer(r'"(?:[^"\\]|\\.)*"|[^"]+|"', code, re.DOTALL):
        piece = match.group()
        out.append(piece if piece.startswith('"') and len(piece) > 1 else _pad(piece))
    return "".join(out).strip()


def _pad(piece: str) -> str:
    """Whitespace-collapsed, keeping one space at either end that had any."""
    inner = " ".join(piece.split())
    if not inner:
        return " " if piece else ""
    return (" " if piece[0].isspace() else "") + inner + (" " if piece[-1].isspace() else "")


def _tokens(code: str) -> list[str] | None:
    """Words and quoted strings (kept with their quotes); None if anything else is left."""
    found = _TOKEN.findall(code)
    rest = _TOKEN.sub(" ", code)
    return found if not rest.strip() else None


def _one_line(text: str) -> str:
    return " ".join(text.split())


CONDITION_CHARS = 32        # a choice row's condition, then "…" (step 5: shown, not hidden)


def condition_words(source: str) -> str:
    """A condition for an Events row: in words when the condition builder reads it
    ("coins is at least 1 and ending sad seen"), else as written on one line."""
    found = conditions.read(source)
    if found is not None and found.rows:
        return conditions.summary(found)
    return _one_line(source)


def _condition(source: str) -> str:
    """A conditional choice's row summary: ``if`` and its condition (in words when the
    builder reads it), cut at 32 characters."""
    text = condition_words(source)
    if len(text) > CONDITION_CHARS:
        text = text[:CONDITION_CHARS - 1].rstrip() + "…"
    return f"if {text}"


def _secs(value: str) -> str:
    try:
        return f"{float(value):g} s"
    except ValueError:
        return f"{value} s"


def _join(*parts: str) -> str:
    return " ".join(part for part in parts if part)


def _dot(*parts: str) -> str:
    return " · ".join(part for part in parts if part)


# --- Shared tails: ``at``, ``with`` -----------------------------------------------------------

def _tail(tokens: Sequence[str], node, *, allow_at: bool) -> dict[str, str] | None:
    """``[at <position>] [with <transition> [<seconds>]]`` read against ``node``."""
    values = {"position": "", "transition": "", "seconds": ""}
    i = 0
    if allow_at and i < len(tokens) and tokens[i] == "at":
        if i + 1 >= len(tokens) or tokens[i + 1].startswith('"'):
            return None
        values["position"] = tokens[i + 1]
        i += 2
    clause = getattr(node, "with_clause", None)
    if i < len(tokens) and tokens[i] == "with":
        if clause is None or clause.color is not None or i + 1 >= len(tokens):
            return None
        values["transition"] = tokens[i + 1]
        i += 2
        if i < len(tokens):
            if _NUMBER.fullmatch(tokens[i]) is None or clause.seconds is None:
                return None
            values["seconds"] = tokens[i]
            i += 1
    elif clause is not None:
        return None
    return values if i == len(tokens) else None


def _write_tail(values: Values, *, allow_at: bool) -> str:
    out = []
    if allow_at and values.get("position"):
        out.append(f"at {values['position']}")
    if values.get("transition"):
        out.append(_join("with", values["transition"], values.get("seconds", "")))
    return " ".join(out)


def _transition(values: Values) -> str:
    if not values.get("transition"):
        return ""
    seconds = values.get("seconds", "")
    return _join(values["transition"], _secs(seconds) if seconds else "")


# --- The forms --------------------------------------------------------------------------------

def _say_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Say) or not tokens or not tokens[-1].startswith('"'):
        return None
    words = tokens[:-1]
    if any(word.startswith('"') for word in words):
        return None
    if node.speaker is None:
        return None if words else {"speaker": "", "look": "", "text": node.text}
    if not words or tuple(words[1:]) != tuple(node.attributes):
        return None
    return {"speaker": words[0], "look": " ".join(words[1:]), "text": node.text}


def _say_write(values: Values) -> str:
    speaker = values.get("speaker", "")
    return _join(speaker, values.get("look", "") if speaker else "", quote(values["text"]))


def _say_summary(values: Values) -> str:
    text = _one_line(values["text"])
    speaker, look = values.get("speaker", ""), values.get("look", "")
    if not speaker:
        return text
    return f"{speaker} ({look}): {text}" if look else f"{speaker}: {text}"


def _show_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Show) or not tokens or tokens[0] != "show":
        return None
    if (node.tag, node.behind, node.layer, node.zoom, node.flip) != (None,) * 5:
        return None
    image = node.image.split()
    if tokens[1:1 + len(image)] != image:
        return None
    tail = _tail(tokens[1 + len(image):], node, allow_at=True)
    if tail is None or (node.at is None) != (not tail["position"]):
        return None
    return {"character": image[0], "look": " ".join(image[1:]), **tail}


def _show_write(values: Values) -> str:
    return _join("show", values["character"], values.get("look", ""),
                 _write_tail(values, allow_at=True))


def _show_summary(values: Values) -> str:
    return _dot(_join(values["character"], values.get("look", "")), values.get("position", ""),
                _transition(values))


def _hide_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Hide) or not tokens or tokens[:2] != ["hide", node.tag]:
        return None
    tail = _tail(tokens[2:], node, allow_at=False)
    if tail is None:
        return None
    return {"character": node.tag, "transition": tail["transition"],
            "seconds": tail["seconds"]}


def _hide_write(values: Values) -> str:
    return _join("hide", values["character"], _write_tail(values, allow_at=False))


def _hide_summary(values: Values) -> str:
    return _dot(values["character"], _transition(values))


def _scene_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Scene) or not tokens or tokens[0] != "scene":
        return None
    image = node.image.split() if node.image else []
    if tokens[1:1 + len(image)] != image:
        return None
    tail = _tail(tokens[1 + len(image):], node, allow_at=False)
    if tail is None:
        return None
    return {"image": " ".join(image), "transition": tail["transition"],
            "seconds": tail["seconds"]}


def _scene_write(values: Values) -> str:
    return _join("scene", values.get("image", ""), _write_tail(values, allow_at=False))


def _scene_summary(values: Values) -> str:
    return _dot(values.get("image", ""), _transition(values))


def _music_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not tokens:
        return None
    if isinstance(node, StopAudio):
        if node.channel != "music" or node.audio_file is not None:
            return None
        if tokens == ["stop", "music"] and node.fadeout is None:
            return {"action": "stop", "file": "", "fade": ""}
        if len(tokens) == 4 and tokens[:3] == ["stop", "music", "fadeout"] \
                and node.fadeout is not None and _NUMBER.fullmatch(tokens[3]):
            return {"action": "stop", "file": "", "fade": tokens[3]}
        return None
    if not isinstance(node, PlayAudio) or node.channel != "music" or not node.loop \
            or (node.volume, node.fadeout, node.restart, node.start) != (100, None, False, None):
        return None
    if tokens[:2] != ["play", "music"] or len(tokens) < 3 or tokens[2] != quote(node.audio_file):
        return None
    fade = ""
    if len(tokens) == 5 and tokens[3] == "fadein" and _NUMBER.fullmatch(tokens[4]):
        fade = tokens[4]
    elif len(tokens) != 3:
        return None
    if (node.fadein is None) != (not fade):
        return None
    return {"action": "play", "file": node.audio_file, "fade": fade}


def _music_write(values: Values) -> str:
    fade = values.get("fade", "")
    if values.get("action") == "stop":
        return _join("stop music", f"fadeout {fade}" if fade else "")
    return _join("play music", quote(values["file"]), f"fadein {fade}" if fade else "")


def _music_summary(values: Values) -> str:
    fade = values.get("fade", "")
    if values.get("action") == "stop":
        return f"fade out {_secs(fade)}" if fade else ""
    return _dot(values["file"], f"fade in {_secs(fade)}" if fade else "")


def _sound_read(node: Statement, code: str) -> dict[str, str] | None:
    if not isinstance(node, PlayAudio) or node.channel != "sound" or node.loop \
            or (node.volume, node.fadein, node.fadeout, node.restart, node.start) \
            != (100, None, None, False, None):
        return None
    if _tokens(code) != ["play", "sound", quote(node.audio_file)]:
        return None
    return {"file": node.audio_file}


def _target_read(word: str, kind: type[Statement]
                 ) -> Callable[[Statement, str], dict[str, str] | None]:
    def read(node: Statement, code: str) -> dict[str, str] | None:
        tokens = _tokens(code)
        if not isinstance(node, kind) or tokens is None or len(tokens) != 2 \
                or tokens[0] != word or tokens[1].startswith('"'):
            return None
        return {"scene": tokens[1]}
    return read


def _return_read(node: Statement, code: str) -> dict[str, str] | None:
    return {} if isinstance(node, Return) and _tokens(code) == ["return"] else None


def _pause_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Pause) or not tokens or tokens[0] != "pause" or len(tokens) > 2:
        return None
    if len(tokens) == 1:
        return {"seconds": ""} if node.seconds is None else None
    if _NUMBER.fullmatch(tokens[1]) is None or node.seconds is None:
        return None
    return {"seconds": tokens[1]}


def _set_read(node: Statement, code: str) -> dict[str, str] | None:
    if not isinstance(node, PythonLine):
        return None
    match = _SET.fullmatch(_collapse(code))
    if match is None:
        return None
    return {"name": match.group(1), "op": match.group(2), "value": match.group(3)}


def _points_read(node: Statement, code: str) -> dict[str, str] | None:
    if not isinstance(node, PointsChange):
        return None
    match = _POINTS.fullmatch(_collapse(code))
    if match is None:
        return None
    return {"meter": match.group(1), "op": match.group(2), "amount": match.group(3)}


def _if_read(node: Statement, code: str) -> dict[str, str] | None:
    """One header of an if-chain (``code``: that header's code)."""
    if not isinstance(node, If):
        return None
    if _ELSE_HEAD.fullmatch(code):
        return {"keyword": "else", "condition": ""}
    match = _IF_HEAD.fullmatch(code)
    if match is None or "\n" in match.group(2):
        return None
    return {"keyword": match.group(1), "condition": match.group(2)}


def _if_write(values: Values) -> str:
    keyword = values.get("keyword", "if")
    return "else:" if keyword == "else" else f"{keyword} {values['condition']}:"


_IF_WORDS: Final = {"if": "If", "elif": "Else if", "else": "Else"}

_TRANSITION_FIELDS: Final = (
    Field("transition", "Transition", "name", "transition", optional=True),
    Field("seconds", "Seconds", "number", optional=True))

FORMS: tuple[CommandForm, ...] = (
    CommandForm(
        "say", "Say", "Say", (("dialogue", ""), ("narration", "")), Say,
        (Field("speaker", "Speaker", "name", "character", optional=True),
         Field("look", "Look", "text", optional=True),
         Field("text", "Text", "text")),
        _say_read, _say_write, _say_summary,
        lambda v: "Say" if v.get("speaker") else "Narration"),
    CommandForm(
        "show", "Show character", "Show character", (("show", ""),), Show,
        (Field("character", "Character", "name", "sprite"),
         Field("look", "Look", "text", optional=True),
         Field("position", "Where", "name", "position", optional=True), *_TRANSITION_FIELDS),
        _show_read, _show_write, _show_summary),
    CommandForm(
        "hide", "Hide character", "Hide character", (("hide", ""),), Hide,
        (Field("character", "Character", "name", "sprite"), *_TRANSITION_FIELDS),
        _hide_read, _hide_write, _hide_summary),
    CommandForm(
        "scene", "Background", "Background", (("scene", ""),), Scene,
        (Field("image", "Background", "name", "image", optional=True), *_TRANSITION_FIELDS),
        _scene_read, _scene_write, _scene_summary),
    CommandForm(
        "music", "Music", "Music", (("play", "play music"), ("stop", "")),
        (PlayAudio, StopAudio),
        (Field("action", "Music", "pick", options=("play", "stop")),
         Field("file", "File", "name", "audio", optional=True),
         Field("fade", "Fade (seconds)", "number", optional=True)),
        _music_read, _music_write, _music_summary,
        lambda v: "Stop music" if v.get("action") == "stop" else "Music"),
    CommandForm(
        "sound", "Sound", "Sound", (("play", "play sound"),), PlayAudio,
        (Field("file", "File", "name", "audio"),),
        _sound_read, lambda v: f"play sound {quote(v['file'])}", lambda v: v["file"]),
    CommandForm(
        "jump", "Go to scene", "Go to scene", (("jump", ""),), Jump,
        (Field("scene", "Scene", "scene", "label"),),
        _target_read("jump", Jump), lambda v: f"jump {v['scene']}", lambda v: v["scene"]),
    CommandForm(
        "call", "Visit scene", "Visit scene", (("call", ""),), Call,
        (Field("scene", "Scene", "scene", "label"),),
        _target_read("call", Call), lambda v: f"call {v['scene']}", lambda v: v["scene"]),
    CommandForm(
        "return", "Return", "Return", (("return", ""),), Return, (),
        _return_read, lambda v: "return", lambda v: ""),
    CommandForm(
        "pause", "Wait", "Wait", (("pause", ""),), Pause,
        (Field("seconds", "Seconds", "number", optional=True),),
        _pause_read, lambda v: _join("pause", v.get("seconds", "")),
        lambda v: _secs(v["seconds"]) if v.get("seconds") else ""),
    # Should (PR-F46-22)
    CommandForm(
        "set", "Set variable", "Set variable", (("$", ""),), PythonLine,
        (Field("name", "Variable", "text"),
         Field("op", "Change", "pick", options=("=", "+=", "-=")),
         Field("value", "Value", "text")),
        _set_read, lambda v: f"$ {v['name']} {v['op']} {v['value']}",
        lambda v: f"{v['name']} {v['op']} {v['value']}"),
    CommandForm(
        "points", "Change meter", "Change meter", (("points", "points <name> +="),),
        PointsChange,
        (Field("meter", "Meter", "name", "meter"),
         Field("op", "Change", "pick", options=("+=", "-=", "=")),
         Field("amount", "Amount", "number")),
        _points_read, lambda v: f"points {v['meter']} {v['op']} {v['amount']}",
        lambda v: f"{v['meter']} {v['op']} {v['amount']}"),
    CommandForm(
        "if", "If", "If", (("if", ""), ("elif", ""), ("else", "")), If,
        (Field("keyword", "Branch", "pick", options=("if", "elif", "else")),
         Field("condition", "Condition", "text", optional=True)),
        _if_read, _if_write, lambda v: condition_words(v.get("condition", "")),
        lambda v: _IF_WORDS.get(v.get("keyword", "if"), "If")),
)


def _no_write(values: Values) -> str:
    raise ValueError("the Choice form writes line patches: use choice_patches")


CHOICE: Final = CommandForm(
    CHOICE_FORM, "Choice", "Choice", (("menu", ""),), Menu, (),
    lambda node, code: None, _no_write,
    lambda v: v.get("question", "") or NO_QUESTION)


def _line_forms() -> tuple[CommandForm, ...]:
    """F46's one-line forms, then F47's (``forms_more``, ``minigamedata``'s Minigame row and
    W9's Meta file and Game UI, ``forms_files_ui``; imported here, as they import us)."""
    from engine.tools.editor import forms_files_ui, forms_more, minigamedata
    return (*FORMS, *forms_more.FORMS, minigamedata.FORM, *forms_files_ui.FORMS,
            minigamedata.ASK_NAME)                              # F52: Ask for a name…


def all_forms() -> tuple[CommandForm, ...]:
    """Every form: F46's ``FORMS``, the Choice form and F47's ``forms_more.FORMS``."""
    return (*_line_forms(), CHOICE)


def form_by_key(key: str) -> CommandForm | None:
    return next((form for form in all_forms() if form.key == key), None)


def form_for_doc(doc: StatementDoc) -> CommandForm | None:
    """The form that inserts ``doc`` (the Choice form for ``menu``), or None (always for a
    ``DECLARATIONS_GROUP`` doc: ``lock tip|item <name> "title"`` starts like the Lock form's
    ``lock tip|item <name>``)."""
    if doc.group == DECLARATIONS_GROUP:
        return None
    for form in all_forms():
        for key, prefix in form.docs:
            if doc.key == key and doc.syntax.startswith(prefix):
                return form
    return None


def missing_forms() -> list[str]:
    """Keys of ``insert=True`` docs with neither a form nor a ``TEXT_ONLY`` reason (an empty
    reason counts as none)."""
    return [doc.key for doc in all_docs()
            if doc.insert and not TEXT_ONLY.get(doc.key) and form_for_doc(doc) is None]


def insert_lines(form: CommandForm, values: Values | ChoiceValues, indent: str,
                 unit: str) -> list[str]:
    """The lines a new row of ``form`` inserts at ``indent`` (``unit``: one nesting step):
    an ``if`` gets a ``$ pass`` block, a Choice its whole menu."""
    if isinstance(values, ChoiceValues):
        return choice_lines(values, indent, unit)
    line = indent + form.write(values)
    if form.key == "if":
        return [line, indent + unit + "$ pass"]
    return [line]


# --- Shape and the probe (§6.7.2) -------------------------------------------------------------

_PLAIN: Final = (str, int, float, bool, type(None))
_SHAPE_FIELDS: dict[type, tuple[str, ...] | None] = {}     # a type's compared fields


def shape(value: object) -> object:
    """A node's fields compared recursively, without places, ids, blocks and compiled code."""
    kind = type(value)
    if kind in _PLAIN:
        return value
    try:
        names = _SHAPE_FIELDS[kind]
    except KeyError:
        names = _SHAPE_FIELDS[kind] = (
            tuple(f.name for f in fields(value) if f.name not in _SHAPE_SKIP)  # type: ignore[arg-type]
            if is_dataclass(value) and not isinstance(value, type) else None)
    if names is not None:
        return (kind.__name__, tuple((name, shape(getattr(value, name))) for name in names))
    if isinstance(value, (tuple, list)):
        return tuple(shape(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, shape(item)) for key, item in value.items()))
    return value


def _probe(ref: str, groups: Sequence[Sequence[str]], positions: frozenset[str]
           ) -> list[Statement | None] | None:
    """Parse the groups (each one statement's lines, written at depth 1) as one probe text:
    each group's top-level node, or None when the probe text has any error."""
    text = [f"label {PROBE_LABEL}:"]
    starts = []
    for group in groups:
        starts.append(len(text) + 1)
        text.extend(group)
    ctx = ParseContext(sink=DiagnosticSink(limit=scenes.SINK_LIMIT),
                       position_names=frozenset(BUILTIN_POSITIONS) | positions)
    try:
        nodes = parse_file(ScriptFile(ref, ref.removeprefix("script/"), 0),
                           "\n".join(text) + "\n", ctx)
    except (RecursionError, MemoryError):
        return None
    if ctx.sink.kept():
        return None
    label = next((n for n in nodes if isinstance(n, Label) and n.name == PROBE_LABEL), None)
    if label is None:
        return None
    by_line = {stmt.line: stmt for stmt in label.block}
    return [by_line.get(start) for start in starts]


# --- Rows (§6.7.1) ----------------------------------------------------------------------------

@dataclass(slots=True)
class _Candidate:
    form: CommandForm
    node: Statement
    values: list[dict[str, str]]       # one per header (an if-chain: one per branch)
    group: list[str]                   # probe lines
    ok: bool = False


def _forms_for(node: Statement) -> list[CommandForm]:
    return [form for form in _line_forms() if isinstance(node, form.node)]


def _head_code(lines: Sequence[str], head: Span) -> tuple[str, str]:
    return code_of(lines[head.first - 1:head.last])


def _candidate(node: Statement, heads: Sequence[Span], lines: Sequence[str]
               ) -> _Candidate | None:
    """The first form whose ``read`` takes every head of ``node`` and writes it back."""
    for form in _forms_for(node):
        values: list[dict[str, str]] = []
        for head in heads:
            code, _ = _head_code(lines, head)
            got = form.read(node, code)
            if got is None:
                break
            written = form.write(got)
            if "\n" in written or "\r" in written:
                break
            if head.first == head.last and _collapse(written) != _collapse(code):
                break
            values.append(got)
        else:
            if isinstance(node, If):
                group = []
                for value in values:
                    group.append(PROBE_INDENT + form.write(value))
                    group.append(PROBE_INDENT * 2 + "$ pass")
            else:
                group = [PROBE_INDENT + form.write(values[0])]
            return _Candidate(form, node, values, group)
    return None


def _is_pass(node: Statement) -> bool:
    return isinstance(node, PythonLine) and node.py.source.strip() == "pass"


def rows(scene: SceneRead, lines: Sequence[str], *, positions: frozenset[str] = frozenset()
         ) -> list[Row]:
    """The Events rows of ``scene`` (``lines``: its chunk's lines), at most
    ``scenes.SCENE_ROW_CAP`` and then the "N more lines" row."""
    if scene.error is not None or not scene.blocks:
        return []
    block_at = {(b.owner, b.branch): i for i, b in enumerate(scene.blocks)}

    def branches(stmt: int) -> list[int]:
        path = scene.statements[stmt].path
        out, b = [], 0
        while (path, b) in block_at:
            out.append(block_at[(path, b)])
            b += 1
        return out

    # Candidates, then one probe for all of them.
    candidates: dict[int, _Candidate] = {}
    for index, read in enumerate(scene.statements):
        node = read.node
        if isinstance(node, Menu) or _is_pass(node):
            continue
        heads = [read.head]
        if isinstance(node, If):
            heads = [scene.blocks[b].head or read.head for b in branches(index)]
        found = _candidate(node, heads, lines)
        if found is not None:
            candidates[index] = found
    order = list(candidates)
    probed = _probe(scene.ref, [candidates[i].group for i in order], positions)
    if probed is None:                 # an error somewhere: probe each one alone
        probed = []
        for i in order:
            alone = _probe(scene.ref, [candidates[i].group], positions)
            probed.append(None if alone is None else alone[0])
    for i, node in zip(order, probed):
        candidates[i].ok = node is not None and shape(node) == shape(candidates[i].node)

    out: list[Row] = []

    def script_row(stmt: int, block: int, depth: int, head: Span,
                   kind: Literal["stmt", "header"] = "stmt") -> Row:
        code, _ = _head_code(lines, head)
        return Row(stmt, block, depth, "Script", _one_line(code), None, None, kind)

    def form_row(stmt: int, block: int, depth: int, found: _Candidate, branch: int,
                 kind: Literal["stmt", "header"] = "stmt") -> Row:
        values = found.values[branch]
        return Row(stmt, block, depth, found.form.row_word(values), found.form.summary(values),
                   found.form.key, values, kind)

    # Pre-order with a task stack: ("block", block, depth, member position),
    # ("choice", menu, block, depth, choice) or ("branch", if, block, depth, branch).
    tasks: list[tuple] = [("block", block_at[(None, 0)], 0, 0)]
    while tasks:
        task = tasks.pop()
        if task[0] == "choice":
            _, index, block, depth, choice = task
            summary = "" if choice.condition is None else _condition(choice.condition.source)
            if choice.timeout:                                  # F51 (01 §7.2)
                summary = TIMEOUT_SUMMARY
            out.append(Row(index, block, depth, f'"{_one_line(choice.text)}"', summary,
                           CHOICE_FORM, None, "header"))
            continue
        if task[0] == "branch":
            _, index, block, depth, n = task
            found = candidates.get(index)
            if found is not None and found.ok:
                out.append(form_row(index, block, depth, found, n, "header"))
            else:
                head = scene.blocks[block].head or scene.statements[index].head
                out.append(script_row(index, block, depth, head, "header"))
            continue
        _, block, depth, at = task
        members = scene.blocks[block].members
        if at >= len(members):
            out.append(Row(None, block, depth, END_WORD, "", None, None, "end"))
            continue
        tasks.append(("block", block, depth, at + 1))
        index = members[at]
        read = scene.statements[index]
        node = read.node
        found = candidates.get(index)
        found = found if found is not None and found.ok else None
        children: list[tuple] = []
        if isinstance(node, Menu):
            question = node.question
            summary = NO_QUESTION if question is None else _say_summary(
                {"speaker": question.speaker or "", "look": " ".join(question.attributes),
                 "text": question.text})
            if node.time is not None:                           # F51 (01 §7.2, 07 I-8)
                summary += time_summary(node.time_text)
            out.append(Row(index, block, depth, CHOICE.word, summary, CHOICE_FORM, None))
            for b, choice in zip(branches(index), node.choices):
                children += [("choice", index, b, depth + 1, choice), ("block", b, depth + 2, 0)]
        elif isinstance(node, If):
            out.append(form_row(index, block, depth, found, 0) if found is not None
                       else script_row(index, block, depth, read.head))
            for n, b in enumerate(branches(index)):
                if n:
                    children.append(("branch", index, b, depth, n))
                children.append(("block", b, depth + 1, 0))
        elif _is_pass(node):
            out.append(Row(index, block, depth, NOTHING, "", None, None))
        elif found is not None:
            out.append(form_row(index, block, depth, found, 0))
        else:
            out.append(script_row(index, block, depth, read.head))
        tasks.extend(reversed(children))
    return _capped(out)


def _capped(out: list[Row]) -> list[Row]:
    cap = scenes.SCENE_ROW_CAP
    if len(out) <= cap:
        return out
    hidden = sum(1 for row in out[cap:] if row.kind != "end")
    return out[:cap] + [Row(None, -1, 0, MORE_TEXT.format(n=hidden), "", None, None, "more")]


# --- The Choice form (§6.7.4) -----------------------------------------------------------------

def _indent(line: str) -> str:
    return line[:len(line) - len(line.lstrip(" \t"))]


def _choice_blocks(scene: SceneRead, stmt: int) -> list[int]:
    path = scene.statements[stmt].path
    found = [(b.branch, i) for i, b in enumerate(scene.blocks) if b.owner == path]
    return [i for _, i in sorted(found)]


def _goes(scene: SceneRead, members: Sequence[int]) -> tuple[str | None, bool]:
    """(scene, in_text) of a choice block: a last-member ``jump``, a lone ``$ pass``, or
    anything else (read-only)."""
    if members:
        last = scene.statements[members[-1]].node
        if isinstance(last, Jump):
            return last.target, False
    if len(members) == 1 and _is_pass(scene.statements[members[0]].node):
        return None, False
    return None, True


def read_choice(scene: SceneRead, stmt: int) -> ChoiceValues | None:
    """The Choice form's values for the menu at ``scene.statements[stmt]``."""
    node = scene.statements[stmt].node
    if not isinstance(node, Menu):
        return None
    items = []
    for n, (choice, block) in enumerate(zip(node.choices, _choice_blocks(scene, stmt))):
        goes, in_text = _goes(scene, scene.blocks[block].members)
        condition = "" if choice.condition is None else choice.condition.source
        items.append(ChoiceItem(choice.text, condition, goes, in_text, n,
                                timeout=choice.timeout))
    question = node.question
    time = node.time_text if node.time is not None else ""
    if question is None:
        return ChoiceValues(choices=tuple(items), time=time)
    return ChoiceValues(question.speaker or "", " ".join(question.attributes), question.text,
                        tuple(items), time)


def choice_summary(item: ChoiceItem) -> str:
    """Where a choice goes, as the form shows it."""
    if item.in_text:
        return IN_TEXT
    return CONTINUES if item.goes is None else item.goes


# --- F51: the time limit (01 §7.1) ---------------------------------------------------------------

def time_summary(time_text: str) -> str:
    """The menu row's ending: `` · 5 seconds``, `` · 1 second`` (07 I-8)."""
    try:
        one = float(time_text) == 1
    except ValueError:
        one = False
    return f" · {time_text} second" if one else f" · {time_text} seconds"


def time_ok(time: str) -> bool:
    """Whether ``time`` is a time limit the script takes: a number from 1 to 60."""
    return TIME_RE.fullmatch(time) is not None and 1 <= float(time) <= 60


def default_timeout(values: ChoiceValues) -> int | None:
    """The option ticking "Give the player" picks first: the last one with no condition."""
    for index in range(len(values.choices) - 1, -1, -1):
        if not values.choices[index].condition:
            return index
    return None


def choice_problems(values: ChoiceValues) -> str | None:
    """The form's problem line for the time limit (OK is disabled while one shows), or None.
    Untimed: none (a ``timeout`` mark is dropped when written)."""
    if not values.time:
        return None
    marked = [item for item in values.choices if item.timeout]
    if not marked:
        return TIMEOUT_PICK_TEXT
    if any(item.condition for item in marked):
        return TIMEOUT_CONDITION_TEXT
    if not time_ok(values.time):
        return TIME_RANGE_TEXT
    return None


def _menu_code(time: str) -> str:
    return f"menu time {time}:" if time else "menu:"


def _header_code(item: ChoiceItem, timed: bool = False) -> str:
    condition = f" if {item.condition}" if item.condition else ""
    marker = " timeout" if timed and item.timeout else ""
    return f"{quote(item.text)}{marker}{condition}:"


def _target_code(goes: str | None) -> str:
    return "$ pass" if goes is None else f"jump {goes}"


def choice_lines(values: ChoiceValues, indent: str, unit: str) -> list[str]:
    """A new menu at ``indent`` (Insert…). F51: ``menu time N:`` and the ``timeout`` mark."""
    timed = bool(values.time)
    out = [indent + _menu_code(values.time)]
    inner = indent + unit
    if values.question:
        out.append(inner + _say_write({"speaker": values.speaker, "look": values.look,
                                       "text": values.question}))
    for item in values.choices:
        out += [inner + _header_code(item, timed), inner + unit + _target_code(item.goes)]
    return out


def _apply(lines: Sequence[str], first: int, patches: Sequence[Patch]) -> list[str]:
    """``lines`` (chunk lines from ``first``) with ``patches`` applied."""
    out = list(lines)
    for patch in sorted(patches, key=lambda p: p.first, reverse=True):
        out[patch.first - first:patch.last - first + 1] = patch.lines
    return out


def _merge(patches: list[Patch]) -> list[Patch]:
    """Sorted, with an insert folded into the edit that starts where it inserts."""
    patches.sort(key=lambda p: (p.first, p.last >= p.first))
    out: list[Patch] = []
    for patch in patches:
        if out and out[-1].last == out[-1].first - 1 and out[-1].first == patch.first:
            insert = out.pop()
            patch = Patch(patch.first, patch.last, insert.lines + patch.lines)
        out.append(patch)
    return out


def choice_patches(scene: SceneRead, stmt: int, lines: Sequence[str], new: ChoiceValues,
                   *, unit: str = "    ") -> list[Patch] | str:
    """The line patches that turn the menu at ``scene.statements[stmt]`` into ``new``
    (chunk-relative, sorted, non-overlapping; empty when nothing changed), or a refusal
    text. Only the question line, changed choice headers, the managed ``jump``/``$ pass``
    lines and added or removed choices are written; reordered choices swap whole units
    verbatim. ``ChoiceItem.old`` ties a choice to the one it was read as (None: new).
    ``unit``: the file's nesting step, used only when no choice block shows one."""
    old = read_choice(scene, stmt)
    if old is None:
        return []
    if len(new.choices) > MENU_MAX_CHOICES:
        return CHOICE_LIMIT_TEXT
    if not new.choices:
        return CHOICE_EMPTY_TEXT
    read = scene.statements[stmt]
    menu = read.node
    assert isinstance(menu, Menu)
    blocks = [scene.blocks[i] for i in _choice_blocks(scene, stmt)]
    heads = [b.head for b in blocks if b.head is not None]
    choice_indent = _indent(lines[heads[0].first - 1]) if heads else read.indent + unit
    block_indent = next((b.indent for b in blocks if b.indent), choice_indent + unit)
    patches: list[Patch] = []
    timed = bool(new.time)

    # F51: the menu line (``menu:`` ↔ ``menu time 5:``), its comment kept.
    if old.time != new.time:
        head = read.head
        _, comment = code_of(lines[head.first - 1:head.last])
        patches.append(Patch(head.first, head.last,
                             (_indent(lines[head.first - 1]) + _menu_code(new.time) + comment,)))

    # The question.
    if (old.speaker, old.look, old.question) != (new.speaker, new.look, new.question):
        written = _say_write({"speaker": new.speaker, "look": new.look,
                              "text": new.question}) if new.question else None
        question = menu.question
        if question is not None:
            _, comment = code_of(lines[question.line - 1:question.end_line])
            indent = _indent(lines[question.line - 1])
            patches.append(Patch(question.line, question.end_line,
                                 () if written is None else (indent + written + comment,)))
        elif written is not None:
            after = read.head.last
            if menu.voice is not None:
                after = max(after, menu.voice.end_line)
            patches.append(Patch(after + 1, after, (choice_indent + written,)))

    def in_place(i: int, item: ChoiceItem) -> list[Patch]:
        """Patches that make old choice ``i`` read ``item`` where it stands."""
        block, was = blocks[i], old.choices[i]
        out: list[Patch] = []
        head = block.head
        marked = timed and item.timeout
        if head is not None and (item.text, item.condition, marked) != (
                was.text, was.condition, bool(old.time) and was.timeout):
            _, comment = code_of(lines[head.first - 1:head.last])
            indent = _indent(lines[head.first - 1])
            out.append(Patch(head.first, head.last,
                             (indent + _header_code(item, timed) + comment,)))
        if was.in_text or item.in_text or item.goes == was.goes:
            return out
        members = block.members
        last = scene.statements[members[-1]]
        _, comment = code_of(lines[last.head.first - 1:last.head.last])
        if item.goes is None and len(members) > 1:        # drop the jump, keep the rest
            out.append(Patch(last.span.first, last.span.last, ()))
        else:
            out.append(Patch(last.head.first, last.head.last,
                             (last.indent + _target_code(item.goes) + comment,)))
        return out

    # The choices: the kept ones fill the old units' places in their new order.
    olds = [item.old for item in new.choices if item.old is not None]
    if len(set(olds)) != len(olds) or any(not 0 <= i < len(blocks) for i in olds):
        raise ValueError("ChoiceItem.old must name each old choice at most once")
    kept = [item for item in new.choices if item.old is not None]
    slot_of: dict[int, int] = {}                          # old index → the place it fills
    for slot, item in zip(sorted(olds), kept):
        source = item.old
        assert source is not None
        slot_of[source] = slot
        if source == slot:
            patches += in_place(slot, item)
            continue
        unit_span = blocks[source].unit
        assert unit_span is not None
        body = _apply(lines[unit_span.first - 1:unit_span.last], unit_span.first,
                      in_place(source, item))
        target = blocks[slot].unit
        assert target is not None
        patches.append(Patch(target.first, target.last, tuple(body)))
    for i, block in enumerate(blocks):
        if i not in slot_of and block.span is not None:
            patches.append(Patch(block.span.first, block.span.last, ()))

    # New choices go after the place of the choice before them (or before the first one).
    first_unit = blocks[0].unit.first if blocks and blocks[0].unit else read.span.last + 1
    anchor = first_unit
    pending: list[str] = []
    for item in new.choices:
        if item.old is None:
            pending += [choice_indent + _header_code(item, timed),
                        block_indent + _target_code(item.goes)]
            continue
        if pending:
            patches.append(Patch(anchor, anchor - 1, tuple(pending)))
            pending = []
        place = blocks[slot_of[item.old]].unit
        anchor = (place.last if place is not None else anchor - 1) + 1
    if pending:
        patches.append(Patch(anchor, anchor - 1, tuple(pending)))
    return _merge(patches)


__all__ = ["CHOICE", "CHOICE_EMPTY_TEXT", "CHOICE_FORM", "CHOICE_LIMIT_TEXT", "CONTINUES",
           "ChoiceItem", "ChoiceValues", "CommandForm", "END_WORD", "FORMS", "Field", "IN_TEXT",
           "MORE_TEXT", "NOTHING", "NO_QUESTION", "Patch", "Row", "TEXT_ONLY",
           "TEXT_ONLY_REASONS", "DATABASE_REASON", "DECLARATIONS_GROUP", "NO_FORM_YET_REASON",
           "all_forms",
           "choice_lines",
           "choice_patches", "choice_summary", "code_of", "form_by_key", "form_for_doc",
           "insert_lines", "missing_forms", "quote", "read_choice", "rows", "shape",
           "TIMEOUT_CONDITION_TEXT", "TIMEOUT_PICK_TEXT", "TIMEOUT_SUMMARY", "TIME_DEFAULT",
           "TIME_RANGE_TEXT", "choice_problems", "default_timeout", "time_ok", "time_summary"]

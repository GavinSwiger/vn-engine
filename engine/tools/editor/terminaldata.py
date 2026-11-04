"""Studio's Terminal data sets (F56 ``04`` §2, P2): the model, reading, writing, and the checks.

Why this module exists: an author edits a terminal's commands in Studio's Database ▸ Minigame
data ▸ Terminals, and the result is a ``define`` the game reads (01 §5). Studio never imports
the minigame code (ADR-0008), so the data checks of ``bundled/terminal_rules`` are mirrored
here word for word; ``test_minigamedata``/``test_terminaldata`` compare the two case by case.

- ``TerminalCommand`` / ``TerminalData``: one row, and the whole set.
- ``read(value)``: a ``define``'s literal value as a model, or None when it isn't the shape
  (Studio then shows it as script).
- ``value_of`` (defaults left out) and ``define_lines`` (one key per line, one command per
  line, the closing brackets indented: docs/minigames.md's layout).
- ``problem(data)``: 01 §5's data sentences, in §5's order.
- ``starter()``: + New's terminal (Q2): "Type help to see what you can do.", ``>``, and one
  listed command ``hello`` → "Hello.".

Stdlib only, plus ``engine.script.suggest`` (the engine's did-you-mean rule).
"""

import json
import unicodedata
from dataclasses import dataclass, replace
from typing import Final

from engine.script.suggest import suggest

ROWS_MAX: Final = 100
COMMAND_MAX: Final = 40
ALSO_MAX: Final = 8
REPLY_MAX: Final = 2_000
WELCOME_MAX: Final = 2_000
PROMPT_MAX: Final = 12
LINE_TEXT_MAX: Final = 300
PASSWORD_MAX: Final = 40
BUILTINS: Final = ("help", "clear", "exit")
ENDS: Final = ("goal", "out")
INDENT: Final = "    "
ROW_ORDER: Final = ("command", "also", "help", "after", "password", "known_from", "unlock",
                    "ends", "reply")
TOP_ORDER: Final = ("welcome", "prompt", "unknown", "not_yet", "commands")
_KINDS: Final = {dict: "a dictionary", list: "a list", str: "text", int: "a whole number",
                 float: "a decimal number"}


@dataclass(frozen=True)
class TerminalCommand:
    command: str
    also: tuple[str, ...] = ()
    reply: str = ""
    help: bool | str = True
    after: str | None = None
    password: str | None = None
    known_from: str | None = None
    unlock: str | None = None
    ends: str | None = None


@dataclass(frozen=True)
class TerminalData:
    commands: tuple[TerminalCommand, ...] = ()
    welcome: str = ""
    prompt: str = ">"
    unknown: str | None = None
    not_yet: str | None = None

    def with_command(self, index: int, command: TerminalCommand) -> "TerminalData":
        rows = list(self.commands)
        rows[index] = command
        return replace(self, commands=tuple(rows))


def normalize(line: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", line).casefold().split())


def starter() -> TerminalData:
    """+ New's terminal (F56 04 Q2, accepted)."""
    return TerminalData((TerminalCommand("hello", reply="Hello."),),
                        welcome="Type help to see what you can do.", prompt=">")


# --- Reading ---------------------------------------------------------------------------------------

def _text_or_none(value: object) -> bool:
    return value is None or type(value) is str


def read(value: object) -> TerminalData | None:
    """A ``define``'s value as a terminal, or None (another shape: shown as script)."""
    if type(value) is not dict or type(value.get("commands")) is not list:
        return None
    if any(k not in TOP_ORDER for k in value):
        return None
    rows = []
    for row in value["commands"]:
        if type(row) is not dict or type(row.get("command")) is not str:
            return None
        if any(k not in ROW_ORDER for k in row):
            return None
        also = row.get("also", [])
        helped = row.get("help", True)
        if type(also) is not list or not all(type(a) is str for a in also) \
                or not (type(helped) is bool or type(helped) is str) \
                or not all(_text_or_none(row.get(k)) for k in
                           ("after", "password", "known_from", "unlock", "ends")) \
                or type(row.get("reply", "")) is not str:
            return None
        rows.append(TerminalCommand(row["command"], tuple(also), row.get("reply", ""), helped,
                                    row.get("after"), row.get("password"),
                                    row.get("known_from"), row.get("unlock"), row.get("ends")))
    welcome, prompt = value.get("welcome", ""), value.get("prompt", ">")
    if type(welcome) is not str or type(prompt) is not str \
            or not _text_or_none(value.get("unknown")) \
            or not _text_or_none(value.get("not_yet")):
        return None
    return TerminalData(tuple(rows), welcome, prompt, value.get("unknown"),
                        value.get("not_yet"))


# --- Writing ---------------------------------------------------------------------------------------

def _row_value(c: TerminalCommand) -> dict:
    out: dict = {"command": c.command}
    if c.also:
        out["also"] = list(c.also)
    if c.help is not True:
        out["help"] = c.help
    for key in ("after", "password", "known_from", "unlock", "ends"):
        if getattr(c, key) is not None:
            out[key] = getattr(c, key)
    if c.reply:
        out["reply"] = c.reply
    return out


def value_of(data: TerminalData) -> dict:
    """The literal value, defaults left out."""
    out: dict = {}
    if data.welcome:
        out["welcome"] = data.welcome
    if data.prompt != ">":
        out["prompt"] = data.prompt
    for key in ("unknown", "not_yet"):
        if getattr(data, key) is not None:
            out[key] = getattr(data, key)
    out["commands"] = [_row_value(c) for c in data.commands]
    return out


def _lit(value: object) -> str:
    if value is None or type(value) is bool:
        return repr(value)
    if type(value) is list:
        return "[" + ", ".join(_lit(v) for v in value) + "]"
    if type(value) is dict:
        return "{" + ", ".join(f"{json.dumps(k, ensure_ascii=False)}: {_lit(v)}"
                               for k, v in value.items()) + "}"
    return json.dumps(value, ensure_ascii=False)


def define_lines(name: str, data: TerminalData) -> list[str]:
    """``define <name> = {`` with one key per line and one command per line (01 §5)."""
    value = value_of(data)
    out = [f"define {name} = {{"]
    for key, item in value.items():
        if key != "commands":
            out.append(f"{INDENT}{json.dumps(key)}: {_lit(item)},")
    out.append(f'{INDENT}"commands": [')
    for row in value["commands"]:
        out.append(f"{INDENT * 2}{_lit(row)},")
    out.append(f"{INDENT}],")
    out.append(f"{INDENT}}}")
    return out


# --- Checks (01 §5's data sentences, mirrored from terminal_rules) ------------------------------

def _kind_words(v: object) -> str:
    if type(v) is bool or v is None:
        return repr(v)
    return _KINDS.get(type(v), f"a Python object ({type(v).__name__})")


def _echo(v: object) -> str:
    if type(v) is str:
        cut = v if len(v) <= 30 else v[:30] + "…"
        return f'"{cut}"'
    text = repr(v)
    return text if len(text) <= 30 else text[:30] + "…"


def _one_line(text: object, lo: int, hi: int) -> bool:
    return type(text) is str and lo <= len(text) <= hi and "\n" not in text \
        and "\r" not in text


def _length_words(text: object) -> str:
    if type(text) is not str:
        return f"it is {_kind_words(text)}"
    if text == "":
        return "it is empty"
    if "\n" in text or "\r" in text:
        return "it has more than one line"
    return f"it has {len(text):,}"


def problem_value(data: object) -> str | None:
    """``terminal_rules.problem``'s data sentences for a literal ``data`` value, or None."""
    if type(data) is not dict:
        return ('data must be a dictionary with "commands", like the example in '
                f"docs/minigames.md, not {_kind_words(data)}.")
    rows = data.get("commands") if type(data.get("commands")) is list else None
    if rows is None:
        return ('data must be a dictionary with "commands", like the example in '
                'docs/minigames.md, not a dictionary without a list of "commands".')
    if not 1 <= len(rows) <= ROWS_MAX:
        return f"the terminal needs 1 to 100 commands, but it has {len(rows)}."
    for n, row in enumerate(rows, start=1):
        if type(row) is not dict:
            return f'command {n} must be a dictionary with "command", not {_kind_words(row)}.'
        command = row.get("command")
        if not _one_line(command, 1, COMMAND_MAX):
            return (f"command {n} must be 1 to 40 characters on one line, but "
                    f"{_length_words(command)}.")
        also = row.get("also", [])
        if type(also) is not list or not all(_one_line(a, 1, COMMAND_MAX) for a in also):
            return (f'the other ways to type "{command}" must be a list of texts of 1 to 40 '
                    "characters on one line.")
    seen: dict[str, str] = {}
    for n, row in enumerate(rows, start=1):
        for where, words in ((f"command {n}", row["command"]),
                             *((f"command {n}'s also", a) for a in row.get("also", []))):
            key = normalize(words)
            if key in seen:
                return (f'"{words}" is used twice ({seen[key]}, and {where}). Each command '
                        "needs its own words.")
            seen[key] = where
    for n, row in enumerate(rows, start=1):
        for words in (row["command"], *row.get("also", [])):
            if normalize(words) in BUILTINS:
                return (f'"{normalize(words)}" is built into the terminal, so command {n} '
                        "can't use it. Pick other words.")
    for row in rows:
        also = row.get("also", [])
        if len(also) > ALSO_MAX:
            return (f'"{row["command"]}" can have at most 8 other ways to type it, but it has '
                    f"{len(also)}.")
    for row in rows:
        reply = row.get("reply", "")
        if type(reply) is not str:
            return f'the reply of "{row["command"]}" must be text, not {_kind_words(reply)}.'
        if len(reply) > REPLY_MAX:
            return (f'the reply of "{row["command"]}" can be at most 2,000 characters, but it '
                    f"has {len(reply):,}.")
    prompt = data.get("prompt", ">")
    if not _one_line(prompt, 1, PROMPT_MAX):
        if type(prompt) is str and len(prompt) > PROMPT_MAX:
            return f"prompt can be at most 12 characters, but it has {len(prompt)}."
        return f"prompt must be 1 to 12 characters on one line, but {_length_words(prompt)}."
    for key, most in (("welcome", WELCOME_MAX), ("unknown", LINE_TEXT_MAX),
                      ("not_yet", LINE_TEXT_MAX)):
        value = data.get(key)
        if value is None:
            continue
        if type(value) is not str:
            return f"{key} must be text, not {_kind_words(value)}."
        if len(value) > most:
            return f"{key} can be at most {most:,} characters, but it has {len(value):,}."
    by_word = {normalize(row["command"]): row for row in rows}
    names = [row["command"] for row in rows]
    for row in rows:
        after = row.get("after")
        if after is None:
            continue
        if type(after) is not str or normalize(after) not in by_word:
            text = (f'"{row["command"]}" works only after {_echo(after)}, which isn\'t a '
                    "command.")
            near = suggest(after, names) if type(after) is str else None
            return text + (f' Did you mean "{near}"?' if near is not None else "")
    for row in rows:
        seen_rows: list[dict] = []
        current: dict | None = row
        while current is not None and current.get("after") is not None:
            if any(current is s for s in seen_rows):
                if current is row:
                    a = seen_rows[0]
                    if len(seen_rows) == 1:
                        return f'"{a["command"]}" works only after itself, so it can never run.'
                    b = seen_rows[1]
                    rest = "so neither can ever run" if len(seen_rows) == 2 \
                        else "so none of them can ever run"
                    return (f'"{a["command"]}" works only after "{b["command"]}", and '
                            f'"{b["command"]}" only after '
                            f'"{by_word[normalize(b["after"])]["command"]}", {rest}.')
                break
            seen_rows.append(current)
            current = by_word.get(normalize(current["after"]))
    for row in rows:
        password = row.get("password")
        if password is not None and not (_one_line(password, 1, PASSWORD_MAX)
                                         and password == password.strip()):
            return (f'the password of "{row["command"]}" must be 1 to 40 characters with no '
                    "space at either end.")
        if row.get("known_from") is not None and password is None:
            return f'"{row["command"]}" has a tip for its password but no password.'
    for row in rows:
        ends = row.get("ends")
        if ends is not None and ends not in ENDS:
            return (f'ends of "{row["command"]}" must be "goal", "out" or None, not '
                    f"{_echo(ends)}.")
    for row in rows:
        helped = row.get("help", True)
        if type(helped) is not bool and (type(helped) is not str or helped == ""):
            return (f'help of "{row["command"]}" must be True, False or a tip\'s name, not '
                    f"{_echo(helped)}.")
    return None


def problem(data: TerminalData) -> str | None:
    """The model's problem (``problem_value`` of ``value_of``)."""
    return problem_value(value_of(data))


__all__ = ["TerminalCommand", "TerminalData", "define_lines", "normalize", "problem",
           "problem_value", "read", "starter", "value_of"]

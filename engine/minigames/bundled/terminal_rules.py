"""The terminal's pure rules (F56 ``01`` §4–§8, ``04`` §3).

Why this module exists: everything about ``terminal`` that needs no window lives here, so it
is tested directly and shared by the hooks (``check_args``, ``check_story``, ``outcome_for``)
and the session (``terminal``):

- **Checks** (``problem``, ``story_problem``): §5's refusal texts, in §5's order.
- ``parse(args) → Terminal``; ``normalize`` (NFKC, case-folded, inner white space one space,
  ends trimmed): a typed line matches a command or one of its ``also`` lines.
- ``Session``: the state machine (04 §3.1): COMMAND and PASSWORD modes, ``after`` gates,
  password gates (opened once a session, a hint after every third wrong answer), tips
  unlocked through the injected ``unlock``, ``help``/``clear``/``exit``, the unknown line
  with did-you-mean among listed commands only, the "stuck" line after three unknown lines in
  a row, the end (``ends``), ``tried`` and history (≤ 100 each; passwords never).
- ``help_lines``, ``command_choices``, ``result``, ``fixed_outcome``, and W273/W274/W275's
  texts.

Pure: no clock, no randomness, no I/O. Imports only the API and ``rule_text``.
"""

import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final

from engine.minigames.api import Outcome, StoryNames, closest, unlock_tip
from engine.minigames.bundled.rule_text import kind_words, value_echo

ROWS_MAX: Final = 100
COMMAND_MAX: Final = 40
ALSO_MAX: Final = 8
REPLY_MAX: Final = 2_000
WELCOME_MAX: Final = 2_000
PROMPT_MAX: Final = 12
LINE_TEXT_MAX: Final = 300            # unknown, not_yet
PASSWORD_MAX: Final = 40
TYPED_MAX: Final = 80                 # the prompt line's max_length
TRIED_MAX: Final = 100
HISTORY_MAX: Final = 100
WRONG_EVERY: Final = 3
STUCK_AFTER: Final = 3
OUTPUT_MAX: Final = 500               # wrapped lines kept on screen
RESULTS: Final = ("reached", "details")
SCREENS: Final = ("game", "dark")
ENDS: Final = ("goal", "out")
BUILTINS: Final = ("help", "clear", "exit")
DEFAULTS: Final = {"result": "reached", "screen": "game", "hide_passwords": True}
ROW_KEYS: Final = ("command", "also", "reply", "help", "after", "password", "known_from",
                   "unlock", "ends")
_LISTED: Final = 10

ECHO, PLAIN, SYSTEM = "echo", "plain", "system"

# [words.plugin.terminal] (§8), final.
WORDS: Final = {
    "title": "Computer",
    "hint": "Type a command and press Enter. Commands lists what you know.",
    "help": "help", "clear": "clear", "exit": "exit",
    "help_heading": "Commands you know:", "help_also": "Also:",
    "help_none": "You don't know any commands yet.",
    "unknown": "Unknown command.",
    "did_you_mean": "Did you mean:",
    "stuck": "Not sure what to type? Commands lists what you know.",
    "not_yet": "You can't do that yet.",
    "password_prompt": "Password:",
    "wrong_password": "Wrong password.",
    "cancelled": "Cancelled.",
    "password_hint": "Someone must have written it down somewhere.",
    "password_hint_known": "You know this one. It's under Commands.",
    "commands": "Commands", "commands_heading": "Commands you know",
    "password_from": "Password from:",
    "no_password": "You don't know a password for this.",
    "close": "Close", "leave": "Leave",
    "confirm_leave": "Step away from the computer?",
    "continue": "Continue", "more_below": "More below",
}


def normalize(line: str) -> str:
    """NFKC, case-folded, every run of white space one space, the ends trimmed."""
    return " ".join(unicodedata.normalize("NFKC", line).casefold().split())


def _one_line(text: object, lo: int, hi: int) -> bool:
    return type(text) is str and lo <= len(text) <= hi and "\n" not in text \
        and "\r" not in text


def _length_words(text: object) -> str:
    if type(text) is not str:
        return f"it is {kind_words(text)}"
    if text == "":
        return "it is empty"
    if "\n" in text or "\r" in text:
        return "it has more than one line"
    return f"it has {len(text):,}"


# --- Checks (§5) -------------------------------------------------------------------------------

def _rows(data: object) -> list | None:
    if type(data) is dict and type(data.get("commands")) is list:
        return data["commands"]
    return None


def problem(args: dict) -> str | None:
    """The first refused argument's reason (§5's texts, in their order), or None."""
    data = args.get("data")
    if type(data) is not dict:
        return ('data must be a dictionary with "commands", like the example in '
                f"docs/minigames.md, not {kind_words(data)}.")
    rows = _rows(data)
    if rows is None:
        return ('data must be a dictionary with "commands", like the example in '
                'docs/minigames.md, not a dictionary without a list of "commands".')
    if not 1 <= len(rows) <= ROWS_MAX:
        return f"the terminal needs 1 to 100 commands, but it has {len(rows)}."
    for n, row in enumerate(rows, start=1):
        if type(row) is not dict:
            return f"command {n} must be a dictionary with \"command\", not {kind_words(row)}."
        command = row.get("command")
        if not _one_line(command, 1, COMMAND_MAX):
            return (f"command {n} must be 1 to 40 characters on one line, but "
                    f"{_length_words(command)}.")
        also = row.get("also", [])
        if type(also) is not list or not all(_one_line(a, 1, COMMAND_MAX) for a in also):
            return (f"the other ways to type \"{command}\" must be a list of texts of 1 to 40 "
                    "characters on one line.")
    seen: dict[str, str] = {}
    for n, row in enumerate(rows, start=1):
        command = row["command"]
        for where, words in ((f"command {n}", command),
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
            return f'the reply of "{row["command"]}" must be text, not {kind_words(reply)}.'
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
            return f"{key} must be text, not {kind_words(value)}."
        if len(value) > most:
            return f"{key} can be at most {most:,} characters, but it has {len(value):,}."
    by_word = {normalize(row["command"]): row for row in rows}
    names = [row["command"] for row in rows]
    for row in rows:
        after = row.get("after")
        if after is None:
            continue
        if type(after) is not str or normalize(after) not in by_word:
            text = (f'"{row["command"]}" works only after {value_echo(after)}, which isn\'t a '
                    "command.")
            near = closest(after, names) if type(after) is str else None
            return text + (f' Did you mean "{near}"?' if near is not None else "")
    loop = _first_loop(rows, by_word)
    if loop is not None:
        a, b, size = loop
        if size == 1:
            return f'"{a["command"]}" works only after itself, so it can never run.'
        rest = "so neither can ever run" if size == 2 else "so none of them can ever run"
        return (f'"{a["command"]}" works only after "{b["command"]}", and "{b["command"]}" '
                f'only after "{by_word[normalize(b["after"])]["command"]}", {rest}.')
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
                    f"{value_echo(ends)}.")
    for row in rows:
        helped = row.get("help", True)
        if type(helped) is not bool and (type(helped) is not str or helped == ""):
            return f'help of "{row["command"]}" must be True, False or a tip\'s name, not ' \
                   f"{value_echo(helped)}."
        for key in ("known_from", "unlock"):
            value = row.get(key)
            if value is not None and (type(value) is not str or value == ""):
                return f'{key} of "{row["command"]}" must be a tip\'s name or None, not ' \
                       f"{value_echo(value)}."
    result = args.get("result", DEFAULTS["result"])
    if result not in RESULTS or type(result) is not str:
        text = f'result must be "reached" or "details", not {value_echo(result)}.'
        near = closest(result, RESULTS) if type(result) is str else None
        return text + (f' Did you mean "{near}"?' if near is not None else "")
    screen = args.get("screen", DEFAULTS["screen"])
    if screen not in SCREENS or type(screen) is not str:
        return f'screen must be "game" or "dark", not {value_echo(screen)}.'
    hide = args.get("hide_passwords", DEFAULTS["hide_passwords"])
    if type(hide) is not bool:
        return f"hide_passwords must be True or False, not {value_echo(hide)}."
    return None


def _first_loop(rows: list, by_word: dict) -> tuple[dict, dict, int] | None:
    """The first ``after`` loop in table order: (first row, the row it waits on, size)."""
    for row in rows:
        seen: list[dict] = []
        current = row
        while current is not None and current.get("after") is not None:
            if any(current is s for s in seen):
                if current is row:
                    loop = seen
                    return loop[0], loop[1] if len(loop) > 1 else loop[0], len(loop)
                break
            seen.append(current)
            current = by_word.get(normalize(current["after"]))
    return None


def story_problem(args: dict, story: StoryNames) -> str | None:
    """Every tip name (``help`` as a name, ``known_from``, ``unlock``) against the story."""
    rows = _rows(args.get("data")) or []
    for row in rows:
        for value in (row.get("help"), row.get("known_from"), row.get("unlock")):
            if type(value) is str and value and value not in story.tips:
                near = closest(value, story.tips)
                return (f'"{row["command"]}" names the tip "{value}", which isn\'t a declared '
                        "tip." + (f' Did you mean "{near}"?' if near is not None else ""))
    return None


# --- The terminal -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Row:
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
class Terminal:
    rows: tuple[Row, ...]
    welcome: str = ""
    prompt: str = ">"
    unknown: str | None = None
    not_yet: str | None = None

    def words(self) -> dict[str, int]:
        """Normalized words → row index (commands and their ``also``)."""
        out: dict[str, int] = {}
        for i, row in enumerate(self.rows):
            for w in (row.command, *row.also):
                out.setdefault(normalize(w), i)
        return out

    def index_of(self, command: str | None) -> int | None:
        if command is None:
            return None
        key = normalize(command)
        return next((i for i, r in enumerate(self.rows) if normalize(r.command) == key), None)


def parse(args: dict) -> Terminal:
    """The checked ``data`` (``problem`` returned None) as a ``Terminal``."""
    data = args["data"]
    rows = tuple(Row(command=r["command"], also=tuple(r.get("also", [])),
                     reply=r.get("reply", ""), help=r.get("help", True), after=r.get("after"),
                     password=r.get("password"), known_from=r.get("known_from"),
                     unlock=r.get("unlock"), ends=r.get("ends")) for r in data["commands"])
    return Terminal(rows, welcome=data.get("welcome") or "", prompt=data.get("prompt", ">"),
                    unknown=data.get("unknown"), not_yet=data.get("not_yet"))


def listed(t: Terminal, has_tip: Callable[[str], bool]) -> list[Row]:
    """The rows help lists now, in table order (PR-F56-08)."""
    return [r for r in t.rows if r.help is True or (type(r.help) is str and has_tip(r.help))]


@dataclass
class Submitted:
    """What one Enter did: the lines to add (text, style), and what the screen does next."""
    lines: list[tuple[str, str]] = field(default_factory=list)
    clear: bool = False
    confirm: bool = False
    ended: bool = False
    error: bool = False


class Session:
    """One visit's state (04 §3.1). ``words``: the words of the built-ins and texts
    (``[words.plugin.terminal]``); ``has_tip``, ``unlock`` and ``tip_title`` are injected."""

    def __init__(self, t: Terminal, words: dict[str, str], *,
                 has_tip: Callable[[str], bool], unlock: Callable[[str], object],
                 tip_title: Callable[[str], str] = str, hide_passwords: bool = True) -> None:
        self.t = t
        self.words = words
        self.has_tip = has_tip
        self.unlock = unlock
        self.tip_title = tip_title
        self.hide = hide_passwords
        self.table = t.words()
        self.ran: set[int] = set()
        self.opened: set[int] = set()
        self.wrong: dict[int, int] = {}
        self.unknown_streak = 0
        self.password_row: int | None = None
        self.ended: tuple[bool, int] | None = None
        self.tried: list[str] = []
        self.history: list[str] = []

    # -- the prompt --

    @property
    def mode(self) -> str:
        return "password" if self.password_row is not None else "command"

    def prompt(self) -> str:
        return self.words["password_prompt"] if self.mode == "password" else self.t.prompt

    def builtin(self, line: str) -> str | None:
        """Which built-in ``line`` (normalized) is: matched against the current words first,
        so a renamed built-in wins over a command with the same words (Q1)."""
        for key in BUILTINS:
            if line == normalize(self.words[key]):
                return key
        return None

    # -- one Enter --

    def submit(self, raw: str) -> Submitted:
        if self.ended is not None:
            return Submitted()
        if self.mode == "password":
            return self._password(raw)
        out = Submitted()
        line = normalize(raw)
        out.lines.append((f"{self.t.prompt} {raw}", ECHO))
        if not line:
            return out
        if len(self.tried) < TRIED_MAX:
            self.tried.append(line)
        self.history = (self.history + [raw])[-HISTORY_MAX:]
        built = self.builtin(line)
        if built == "help":
            self.unknown_streak = 0
            out.lines.extend((text, PLAIN) for text in self.help_lines())
            return out
        if built == "clear":
            self.unknown_streak = 0
            out.clear = True
            return out
        if built == "exit":
            self.unknown_streak = 0
            out.confirm = True
            return out
        index = self.table.get(line)
        if index is None:
            return self._unknown(line, out)
        self.unknown_streak = 0
        return self._command(index, out)

    def _unknown(self, line: str, out: Submitted) -> Submitted:
        out.error = True
        out.lines.append((self.t.unknown or self.words["unknown"], SYSTEM))
        choices = [normalize(r.command) for r in listed(self.t, self.has_tip)]
        choices += [normalize(self.words[k]) for k in BUILTINS]
        near = closest(line, choices)
        if near is not None:
            out.lines.append((f"{self.words['did_you_mean']} {near}", SYSTEM))
        self.unknown_streak += 1
        if self.unknown_streak % STUCK_AFTER == 0:
            out.lines.append((self.words["stuck"], SYSTEM))
        return out

    def _command(self, index: int, out: Submitted) -> Submitted:
        row = self.t.rows[index]
        after = self.t.index_of(row.after)
        if after is not None and after not in self.ran:
            out.error = True
            out.lines.append((self.t.not_yet or self.words["not_yet"], SYSTEM))
            return out
        if row.password is not None and index not in self.opened:
            self.password_row = index
            return out
        return self._run(index, out)

    def _run(self, index: int, out: Submitted) -> Submitted:
        row = self.t.rows[index]
        if row.reply:
            out.lines.extend((line, PLAIN) for line in row.reply.split("\n"))
        if row.unlock is not None:
            self.unlock(row.unlock)
        self.ran.add(index)
        if row.ends is not None:
            self.ended = (row.ends == "goal", index)
            out.ended = True
        return out

    def _password(self, raw: str) -> Submitted:
        out = Submitted()
        index = self.password_row
        assert index is not None
        row = self.t.rows[index]
        shown = "•" * len(raw) if self.hide else raw
        out.lines.append((f"{self.words['password_prompt']} {shown}", ECHO))
        if not raw.strip():
            self.password_row = None
            out.lines.append((self.words["cancelled"], SYSTEM))
            return out
        if normalize(raw) == normalize(row.password or ""):
            self.password_row = None
            self.opened.add(index)
            return self._run(index, out)
        out.error = True
        out.lines.append((self.words["wrong_password"], SYSTEM))
        self.wrong[index] = self.wrong.get(index, 0) + 1
        if self.wrong[index] % WRONG_EVERY == 0:
            known = row.known_from is not None and self.has_tip(row.known_from)
            out.lines.append((self.words["password_hint_known" if known
                                         else "password_hint"], SYSTEM))
        return out

    # -- lists --

    def help_lines(self) -> list[str]:
        rows = listed(self.t, self.has_tip)
        lines = [self.words["help_heading"]]
        lines += [f"  {r.command}" for r in rows] if rows else []
        if not rows:
            lines = [self.words["help_none"]]
        lines.append(f"{self.words['help_also']} "
                     + ", ".join(self.words[k] for k in BUILTINS))
        return lines

    def command_choices(self) -> list[tuple[str, str | None]]:
        """The Commands list: (shown, text put in the field; None: a disabled row)."""
        if self.mode == "password":
            row = self.t.rows[self.password_row]                 # type: ignore[index]
            if row.known_from is not None and self.has_tip(row.known_from):
                return [(f"{self.words['password_from']} {self.tip_title(row.known_from)}",
                         row.password)]
            return [(self.words["no_password"], None)]
        return [(r.command, r.command) for r in listed(self.t, self.has_tip)]

    def result(self, kind: str) -> object:
        reached = bool(self.ended and self.ended[0])
        if kind == "reached":
            return reached
        ended_by = self.t.rows[self.ended[1]].command if self.ended else None
        return {"reached": reached, "ended_by": ended_by, "tried": list(self.tried)}


def fixed_outcome(args: dict) -> Outcome:
    """Test and skipped (PR-F56-11): the first goal command (reached, its words tried, its
    tip); with none, not reached."""
    t = parse(args)
    kind = args.get("result", DEFAULTS["result"])
    goal = next((r for r in t.rows if r.ends == "goal"), None)
    if goal is None:
        return Outcome(False if kind == "reached" else
                       {"reached": False, "ended_by": None, "tried": []})
    changes = (unlock_tip(goal.unlock),) if goal.unlock is not None else ()
    if kind == "reached":
        return Outcome(True, changes)
    return Outcome({"reached": True, "ended_by": goal.command,
                    "tried": [normalize(goal.command)]}, changes)


# --- Warnings ---------------------------------------------------------------------------------

def data_chars(t: Terminal) -> str:
    """Every character the terminal can show (for W273)."""
    parts = [t.welcome, t.prompt, t.unknown or "", t.not_yet or ""]
    for r in t.rows:
        parts += [r.command, r.reply, *r.also]
    seen: list[str] = []
    for ch in "".join(parts):
        if not ch.isspace() and ch not in seen:
            seen.append(ch)
    return "".join(seen)


def w273_text(chars: Sequence[str]) -> str:
    count = len(chars)
    shown = ", ".join(chars[:_LISTED]) + (", …" if count > _LISTED else "")
    noun = "character" if count == 1 else "characters"
    return (f"terminal: the screen's font can't draw {count} {noun} of this terminal "
            f"({shown}), so they would show as boxes. Set [theme.plugin.terminal] text_font to "
            "a font that has them, or change the text.")


W274_TEXT: Final = ("terminal: help lists no command at the start, so players can only guess. "
                    'Set "In help" to Always on at least one command.')


def w274_needed(t: Terminal, has_tip: Callable[[str], bool]) -> bool:
    return not listed(t, has_tip)


def w275_texts(t: Terminal, words: dict[str, str]) -> list[str]:
    """Q1: a command (or also) whose words equal a renamed built-in's: the built-in wins."""
    out = []
    for n, row in enumerate(t.rows, start=1):
        for w in (row.command, *row.also):
            for key in BUILTINS:
                renamed = normalize(words[key])
                if renamed != key and normalize(w) == renamed:
                    out.append(f'terminal: command {n} uses "{w}", which '
                               f"[words.plugin.terminal] {key} also uses, so typing it runs "
                               f"{key}. Rename one of them.")
    return out


__all__ = ["BUILTINS", "DEFAULTS", "ECHO", "WORDS", "PLAIN", "SYSTEM", "Row", "Session", "Submitted",
           "Terminal", "W274_TEXT", "data_chars", "fixed_outcome", "listed", "normalize",
           "parse", "problem", "story_problem", "w273_text", "w274_needed", "w275_texts"]

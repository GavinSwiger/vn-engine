"""F56 step P1: the terminal's rules (``bundled/terminal_rules.py``): AC-F56-01, 02, 03, 04,
05, 09, 10, 11, 12, 23, 26, 27, and the rule texts of AC-F56-13 (through E272 in
``test_terminal.py``)."""

import pytest

from engine.minigames.api import Outcome, StoryNames, unlock_tip
from engine.minigames.bundled import terminal_rules as rules
from engine.minigames.bundled.terminal_rules import WORDS

LIBRARY = {
    "welcome": "KUROSAWA HIGH LIBRARY TERMINAL\nType help to see what you can do.",
    "prompt": "A:\\>",
    "unknown": "Bad command or file name.",
    "not_yet": "Access denied. Log in first.",
    "commands": [
        {"command": "dir", "reply": "DIARY.TXT    GRADES.DAT    README.TXT"},
        {"command": "type readme.txt", "also": ["read readme.txt"], "help": False,
         "reply": "Library hours: 8:00 to 17:00."},
        {"command": "login", "password": "lantern", "known_from": "hana_password",
         "reply": "Welcome back, H. Sato."},
        {"command": "type diary.txt", "after": "login", "unlock": "hana_diary",
         "help": "hana_password",
         "reply": "June 3. They'll find out about the grades. I have to delete them."},
        {"command": "del grades.dat", "after": "login", "help": False, "ends": "goal",
         "reply": "1 file deleted."},
    ],
}
STORY = StoryNames((), (), ("hana_password", "hana_diary"))
WORDS_NOW = {k: v for k, v in WORDS.items()}


def session(held=(), data=LIBRARY, hide=True):
    unlocked: list[str] = []
    tips = set(held)

    def unlock(name):
        unlocked.append(name)
        tips.add(name)

    s = rules.Session(rules.parse({"data": data}), WORDS_NOW, has_tip=tips.__contains__,
                      unlock=unlock, tip_title={"hana_password": "Hana's notebook"}.get,
                      hide_passwords=hide)
    return s, unlocked


def texts(sub):
    return [t for t, _ in sub.lines]


# --- AC-F56-01: matching normalizes ---------------------------------------------------------

@pytest.mark.parametrize("typed", ["dir", "DIR", "  Dir ", "ｄｉｒ", "Read  README.txt"])
def test_ac_f56_01_matching(typed):
    s, _ = session()
    out = s.submit(typed)
    assert out.lines[0] == (f"A:\\> {typed}", "echo")
    assert out.lines[1][1] == "plain" and not out.error


# --- AC-F56-02: a run prints, unlocks, marks ------------------------------------------------

def test_ac_f56_02_run():
    s, unlocked = session(held=("hana_password",))
    s.ran.add(2)                                         # logged in
    out = s.submit("type diary.txt")
    assert texts(out) == ["A:\\> type diary.txt",
                          "June 3. They'll find out about the grades. I have to delete them."]
    assert unlocked == ["hana_diary"] and 3 in s.ran


# --- AC-F56-03: after -------------------------------------------------------------------------

def test_ac_f56_03_after():
    s, _ = session()
    assert texts(s.submit("type diary.txt"))[1] == "Access denied. Log in first."
    s.submit("login")
    s.submit("lantern")
    assert texts(s.submit("type diary.txt"))[1].startswith("June 3.")


# --- AC-F56-04: passwords ---------------------------------------------------------------------

@pytest.mark.parametrize(("answer", "line", "opened"), [
    ("lantern", "Welcome back, H. Sato.", True),
    ("LANTERN", "Welcome back, H. Sato.", True),            # capitals ignored
    ("lanturn", "Wrong password.", False),
    ("", "Cancelled.", False),
])
def test_ac_f56_04_passwords(answer, line, opened):
    s, _ = session()
    out = s.submit("login")
    assert s.mode == "password" and s.prompt() == "Password:" and len(out.lines) == 1
    out = s.submit(answer)
    assert out.lines[0] == ("Password: " + "•" * len(answer), "echo")
    assert texts(out)[1] == line and (2 in s.opened) is opened
    if opened:
        assert texts(s.submit("login"))[1:] == ["Welcome back, H. Sato."]   # asked once


# --- AC-F56-05: the hint after every third wrong answer ---------------------------------------

def test_ac_f56_05_password_hints():
    for held, hint in (((), "Someone must have written it down somewhere."),
                       (("hana_password",), "You know this one. It's under Commands.")):
        s, _ = session(held=held)
        s.submit("login")
        seen = [texts(s.submit("no"))[1:] for _ in range(6)]
        assert seen == [["Wrong password."]] * 2 + [["Wrong password.", hint]] \
            + [["Wrong password."]] * 2 + [["Wrong password.", hint]]


# --- AC-F56-09: help ----------------------------------------------------------------------------

def test_ac_f56_09_help():
    s, unlocked = session()
    assert s.help_lines() == ["Commands you know:", "  dir", "  login",
                              "Also: help, clear, exit"]
    s, _ = session(held=("hana_password",))
    assert "  type diary.txt" in s.help_lines()
    # A tip unlocked this session counts.
    data = {"commands": [{"command": "a", "unlock": "t1"},
                         {"command": "b", "help": "t1"}]}
    s, unlocked = session(data=data)
    s.submit("a")
    assert s.help_lines()[1:3] == ["  a", "  b"]
    s, _ = session(data={"commands": [{"command": "a", "help": False}]})
    assert s.help_lines() == ["You don't know any commands yet.", "Also: help, clear, exit"]


# --- AC-F56-10: unknown lines, did-you-mean, stuck ---------------------------------------------

def test_ac_f56_10_unknown():
    s, _ = session()
    out = s.submit("dri")
    assert texts(out)[1:] == ["Bad command or file name.", "Did you mean: dir"] and out.error
    assert texts(s.submit("del grades.dta"))[1:] == ["Bad command or file name."]   # secret
    out = s.submit("zzz")
    assert texts(out)[1:] == ["Bad command or file name.",
                              "Not sure what to type? Commands lists what you know."]
    assert texts(s.submit("hlep"))[2] == "Did you mean: help"
    s.submit("dir")                                       # a match resets the streak
    assert s.unknown_streak == 0


# --- AC-F56-11: the result -----------------------------------------------------------------------

def test_ac_f56_11_result():
    s, _ = session()
    for line in ("dir", "", "  DIR ", "login", "lantern", "del grades.dat"):
        s.submit(line)
    assert s.result("reached") is True
    assert s.result("details") == {"reached": True, "ended_by": "del grades.dat",
                                   "tried": ["dir", "dir", "login", "del grades.dat"]}
    s, _ = session()
    for n in range(120):
        s.submit(f"x{n}")
    assert len(s.result("details")["tried"]) == 100 and s.result("reached") is False


# --- AC-F56-12: test and skipped outcomes ---------------------------------------------------------

def test_ac_f56_12_outcomes():
    assert rules.fixed_outcome({"data": LIBRARY}) == Outcome(True)
    with_tip = {"commands": [{"command": "go", "ends": "goal", "unlock": "t"}]}
    assert rules.fixed_outcome({"data": with_tip, "result": "details"}) == Outcome(
        {"reached": True, "ended_by": "go", "tried": ["go"]}, (unlock_tip("t"),))
    no_goal = {"commands": [{"command": "go", "ends": "out"}]}
    assert rules.fixed_outcome({"data": no_goal}) == Outcome(False)
    assert rules.fixed_outcome({"data": no_goal, "result": "details"}) == Outcome(
        {"reached": False, "ended_by": None, "tried": []})


# --- AC-F56-13's texts (and AC-F56-29's table, shared with Studio) -------------------------------

def row(**more):
    return {"command": "dir", **more}


REFUSALS = [
    ([], 'data must be a dictionary with "commands", like the example in docs/minigames.md, '
         "not a list."),
    ({"commands": []}, "the terminal needs 1 to 100 commands, but it has 0."),
    ({"commands": [row(), row(command="x"), {"command": "y" * 52}]},
     "command 3 must be 1 to 40 characters on one line, but it has 52."),
    ({"commands": [row(), {"command": "open diary"}, row(command="a"), row(command="b"),
                   row(command="c", also=["Open  Diary"])]},
     '"Open  Diary" is used twice (command 2, and command 5\'s also). Each command needs its '
     "own words."),
    ({"commands": [row(), row(command="a"), row(command="b"), row(command="Help")]},
     '"help" is built into the terminal, so command 4 can\'t use it. Pick other words.'),
    ({"commands": [row(also=[f"d{i}" for i in range(10)])]},
     '"dir" can have at most 8 other ways to type it, but it has 10.'),
    ({"commands": [row(reply="x" * 2400)]},
     'the reply of "dir" can be at most 2,000 characters, but it has 2,400.'),
    ({"prompt": "x" * 20, "commands": [row()]},
     "prompt can be at most 12 characters, but it has 20."),
    ({"welcome": "x" * 2001, "commands": [row()]},
     "welcome can be at most 2,000 characters, but it has 2,001."),
    ({"unknown": "x" * 301, "commands": [row()]},
     "unknown can be at most 300 characters, but it has 301."),
    ({"commands": [row(command="login"), row(command="type diary.txt", after="logn")]},
     '"type diary.txt" works only after "logn", which isn\'t a command. Did you mean '
     '"login"?'),
    ({"commands": [row(command="a", after="b"), row(command="b", after="a")]},
     '"a" works only after "b", and "b" only after "a", so neither can ever run.'),
    ({"commands": [row(command="login", password=" lantern")]},
     'the password of "login" must be 1 to 40 characters with no space at either end.'),
    ({"commands": [row(command="login", known_from="t")]},
     '"login" has a tip for its password but no password.'),
    ({"commands": [row(command="logout", ends="yes")]},
     'ends of "logout" must be "goal", "out" or None, not "yes".'),
    ({"commands": [row(help=3)]}, 'help of "dir" must be True, False or a tip\'s name, not 3.'),
]


@pytest.mark.parametrize(("data", "reason"), REFUSALS)
def test_ac_f56_13_texts(data, reason):
    assert rules.problem({"data": data}) == reason
    assert rules.problem({"data": LIBRARY}) is None
    assert rules.problem({"data": LIBRARY, "result": "detail"}) == (
        'result must be "reached" or "details", not "detail". Did you mean "details"?')
    assert rules.problem({"data": LIBRARY, "screen": "black"}) == (
        'screen must be "game" or "dark", not "black".')
    assert rules.problem({"data": LIBRARY, "hide_passwords": "yes"}) == (
        'hide_passwords must be True or False, not "yes".')
    bad = {"commands": [row(command="login", password="x", known_from="hana_pasword")]}
    assert rules.story_problem({"data": bad}, StoryNames((), (), ("hana_password",))) == (
        '"login" names the tip "hana_pasword", which isn\'t a declared tip. Did you mean '
        '"hana_password"?')
    assert rules.story_problem({"data": LIBRARY}, STORY) is None


# --- AC-F56-23: full-width text from an IME matches -------------------------------------------

def test_ac_f56_23_full_width():
    s, _ = session()
    assert texts(s.submit("ＤＩＲ"))[1] == "DIARY.TXT    GRADES.DAT    README.TXT"
    assert rules.normalize("ｔｙｐｅ　ｒｅａｄｍｅ．ｔｘｔ") == "type readme.txt"


# --- AC-F56-26: W274, W273 (texts; once and dev only in test_terminal.py) ------------------------

def test_ac_f56_26_warning_texts():
    t = rules.parse({"data": LIBRARY})
    assert not rules.w274_needed(t, lambda name: False)
    secret = rules.parse({"data": {"commands": [row(help=False), row(command="a", help="t")]}})
    assert rules.w274_needed(secret, lambda name: False)
    assert not rules.w274_needed(secret, lambda name: name == "t")
    assert rules.W274_TEXT == ("terminal: help lists no command at the start, so players can "
                               'only guess. Set "In help" to Always on at least one command.')
    assert rules.w273_text(["ж", "ш", "щ"]) == (
        "terminal: the screen's font can't draw 3 characters of this terminal (ж, ш, щ), so "
        "they would show as boxes. Set [theme.plugin.terminal] text_font to a font that has "
        "them, or change the text.")
    renamed = {**WORDS_NOW, "help": "aide"}
    t = rules.parse({"data": {"commands": [row(), row(command="a"), row(command="b"),
                                           row(command="aide")]}})
    assert rules.w275_texts(t, renamed) == [
        'terminal: command 4 uses "aide", which [words.plugin.terminal] help also uses, so '
        "typing it runs help. Rename one of them."]
    s = rules.Session(t, renamed, has_tip=lambda n: False, unlock=lambda n: None)
    assert s.submit("aide").lines[1][0] == "Commands you know:"      # the built-in wins


# --- AC-F56-27: words and help's layout -----------------------------------------------------------

def test_ac_f56_27_words():
    assert WORDS == {
        "title": "Computer",
        "hint": "Type a command and press Enter. Commands lists what you know.",
        "help": "help", "clear": "clear", "exit": "exit",
        "help_heading": "Commands you know:", "help_also": "Also:",
        "help_none": "You don't know any commands yet.", "unknown": "Unknown command.",
        "did_you_mean": "Did you mean:",
        "stuck": "Not sure what to type? Commands lists what you know.",
        "not_yet": "You can't do that yet.", "password_prompt": "Password:",
        "wrong_password": "Wrong password.", "cancelled": "Cancelled.",
        "password_hint": "Someone must have written it down somewhere.",
        "password_hint_known": "You know this one. It's under Commands.",
        "commands": "Commands", "commands_heading": "Commands you know",
        "password_from": "Password from:", "no_password": "You don't know a password for this.",
        "close": "Close", "leave": "Leave", "confirm_leave": "Step away from the computer?",
        "continue": "Continue", "more_below": "More below"}
    s, _ = session(data={"commands": [{"command": "a"}, {"command": "b"}]})
    assert s.help_lines() == ["Commands you know:", "  a", "  b", "Also: help, clear, exit"]
    s, _ = session(held=("hana_password",))
    s.submit("login")
    assert s.command_choices() == [("Password from: Hana's notebook", "lantern")]
    s, _ = session()
    s.submit("login")
    assert s.command_choices() == [("You don't know a password for this.", None)]

"""F47's command forms, pure half (F47 ``01-design.md`` §4.5, §4.8, PR-F47-06, PR-F47-19;
``04-technical.md`` P2-A: AC-F47-27, 28, 29, 31; P2-B: 32, 33). No Tk.

Each table row is a line, the values its form reads, and the Events row text. The row must
come from ``forms.rows`` (so it passed the gate), write back the same line, and parse back
to the same shape; the "stays a Script row" lists are shapes the form can't write back."""

from collections.abc import Mapping

import pytest

import engine.script  # noqa: F401  registers every statement
from engine.script.statement_docs import all_docs
from engine.tools.editor import forms, forms_more
from engine.tools.editor.forms import form_by_key, form_for_doc, missing_forms, rows, shape
from engine.tools.editor.scenes import parse_chunk


def _rows(*body: str):
    text = "label t:\n" + "".join(f"    {line}\n" for line in body)
    read = parse_chunk("script/t.vns", text)
    assert read is not None and read.error is None, (body, read)
    return read, rows(read, text.split("\n")[:-1])


def _check(table, blank: Mapping[str, str]) -> None:
    """Every (key, line, values, text) row reads, writes back and parses to the same shape."""
    read, got = _rows(*(line for _, line, _, _ in table))
    for (key, line, values, text), row in zip(table, got):
        want = {**blank, **values} if blank is not None else values
        assert (row.form, row.values, row.text) == (key, want, text), line
        form = form_by_key(key)
        assert form.write(want) == line, line
        again = parse_chunk("script/t.vns", f"label t:\n    {line}\n")
        assert shape(again.statements[0].node) == shape(read.statements[row.stmt].node), line


def _scripts(*body: str) -> None:
    _, got = _rows(*body)
    assert [row.form for row in got[:-1]] == [None] * len(body), [r.text for r in got]


def _docs(key: str, prefix: str = ""):
    return [d for d in all_docs() if d.key == key and d.syntax.startswith(prefix)]


# --- AC-F47-27 --------------------------------------------------------------------------------

def test_ac_f47_27_text_only_is_a_reason_map(monkeypatch):
    """AC-F47-27: ``TEXT_ONLY`` maps key → reason; every insert doc has a form or a non-empty
    reason; the reasons are §4.8's (plus the Database and not-yet reasons, each only on its
    own keys, until P2-B/W9/P3 add those forms)."""
    assert forms.TEXT_ONLY_REASONS == (
        "Python code: for things the forms can't do.",
        "Python values: use the Database for characters, transitions and minigame data.",
        "Studio adds these when you make script files.",
        "Made on the Story map / part of Show character.",
        "Plugin code is written in Python (docs/minigames.md).")
    text_only = forms.TEXT_ONLY
    assert isinstance(text_only, Mapping) and "define" in text_only
    assert all(isinstance(reason, str) and reason.strip() for reason in text_only.values())
    allowed = {**dict.fromkeys(("default", "image", "points", "lock"), forms.DATABASE_REASON),
               **dict.fromkeys(("minigame", "file", "ui", "flowchart", "rollback"),
                               forms.NO_FORM_YET_REASON)}
    for key, reason in text_only.items():
        assert reason in forms.TEXT_ONLY_REASONS or allowed.get(key) == reason, key
    assert missing_forms() == []
    for doc in all_docs():
        if doc.insert:
            assert form_for_doc(doc) is not None or text_only.get(doc.key), doc.key
    # P2-A's and P2-B's statements left the map (``lock`` keeps its declarations' reason).
    assert not {"with", "shake", "flash", "effect", "queue", "voice", "chapter", "nvl",
                "unlock"} & set(text_only)
    # An empty reason is no reason.
    monkeypatch.setattr(forms, "TEXT_ONLY", {**text_only, "define": ""})
    assert missing_forms() == ["define"]


# --- AC-F47-28 --------------------------------------------------------------------------------

STAGE = {"image": "", "character": "", "look": "", "position": "", "seconds": "",
         "colour": ""}


def test_ac_f47_28_transition_shake_and_flash_forms():
    """AC-F47-28: Transition (a stage line's ``with`` and its colour), Shake screen and Flash
    read and write every shape; Insert's Transition, Shake and Flash open them."""
    assert form_for_doc(_docs("with")[0]) is form_by_key("transition")
    assert form_for_doc(_docs("shake")[0]) is form_by_key("shake")
    assert form_for_doc(_docs("flash")[0]) is form_by_key("flash")
    # A coloured fade only F47's Transition holds (F46's forms read the rest first).
    _check([
        ("transition", 'scene bg river with fade 0.4 "#ffe08a"',
         {"change": "background", "image": "bg river", "transition": "fade", "seconds": "0.4",
          "colour": "#ffe08a"}, "Transition  bg river · fade 0.4 s #ffe08a"),
        ("transition", "scene with fade black",
         {"change": "background", "transition": "fade", "colour": "black"},
         "Transition  fade black"),
        ("transition", "show hana happy at left with fade 2 white",
         {"change": "show", "character": "hana", "look": "happy", "position": "left",
          "transition": "fade", "seconds": "2", "colour": "white"},
         "Transition  show hana happy · left · fade 2 s white"),
        ("transition", "hide hana with fade red",
         {"change": "hide", "character": "hana", "transition": "fade", "colour": "red"},
         "Transition  hide hana · fade red"),
    ], STAGE)
    # Every other ``with`` shape: the Transition form writes it, and it reads back as F46's
    # Background, Show character or Hide character row.
    transition = form_by_key("transition")
    table = [
        ("scene", "scene bg river with dissolve",
         {"change": "background", "image": "bg river", "transition": "dissolve"}),
        ("show", "show hana at right with fade 1.5",
         {"change": "show", "character": "hana", "position": "right", "transition": "fade",
          "seconds": "1.5"}),
        ("hide", "hide hana with cut", {"change": "hide", "character": "hana",
                                        "transition": "cut"})]
    read, got = _rows(*(line for _, line, _ in table))
    for (key, line, values), row in zip(table, got):
        assert transition.write({**STAGE, **values}) == line
        assert row.form == key and transition.read(read.statements[row.stmt].node, line) is None
    # A colour on a transition that takes none is never written.
    assert transition.write({**STAGE, "change": "background", "image": "bg x",
                             "transition": "dissolve", "colour": "white"}) \
        == "scene bg x with dissolve"

    blank = {"size": "", "direction": "", "seconds": ""}
    _check([
        ("shake", "shake", {}, "Shake screen"),
        ("shake", "shake large", {"size": "large"}, "Shake screen  large"),
        ("shake", "shake vertical", {"direction": "vertical"}, "Shake screen  vertical"),
        ("shake", "shake 2.0", {"seconds": "2.0"}, "Shake screen  2 s"),
        ("shake", "shake small horizontal 2.0",
         {"size": "small", "direction": "horizontal", "seconds": "2.0"},
         "Shake screen  small · horizontal · 2 s"),
    ], blank)
    _check([
        ("flash", "flash", {"colour": "", "seconds": ""}, "Flash"),
        ("flash", "flash red", {"colour": "red", "seconds": ""}, "Flash  red"),
        ("flash", "flash 0.6", {"colour": "", "seconds": "0.6"}, "Flash  0.6 s"),
        ("flash", 'flash "#ffe08a" 0.6', {"colour": "#ffe08a", "seconds": "0.6"},
         "Flash  #ffe08a · 0.6 s"),
    ], None)
    _scripts("shake 2.0 large", "flash 0.3 white", 'scene bg x with fade "#ffe08a" 0.4')


# --- AC-F47-29 --------------------------------------------------------------------------------

def test_ac_f47_29_glitch_jitter_stop_title_and_crash_forms():
    """AC-F47-29: Glitch, Jitter character, Stop effects, Window title and Fake crash read and
    write every shape; each ``effect`` doc opens its own form."""
    for prefix, key in (("effect <glitch>", "glitch"), ("effect jitter", "jitter"),
                        ("effect window_title", "window_title"), ("effect crash", "crash")):
        assert [form_for_doc(d) for d in _docs("effect", prefix)] == [form_by_key(key)], prefix
    how = {"size": "", "action": "burst", "seconds": ""}
    _check([
        ("glitch", "effect tear", {"glitch": "tear"}, "Glitch  tear"),
        ("glitch", "effect tear large 0.3",
         {"glitch": "tear", "size": "large", "seconds": "0.3"}, "Glitch  tear · large · 0.3 s"),
        ("glitch", "effect colorshift 2", {"glitch": "colorshift", "seconds": "2"},
         "Glitch  colorshift · 2 s"),
        ("glitch", "effect static small on",
         {"glitch": "static", "size": "small", "action": "on"}, "Glitch  static · small · on"),
        ("glitch", "effect static off", {"glitch": "static", "action": "off"},
         "Glitch  static · off"),
        ("jitter", "effect jitter hana", {"character": "hana"}, "Jitter character  hana"),
        ("jitter", "effect jitter hana medium 1.0",
         {"character": "hana", "size": "medium", "seconds": "1.0"},
         "Jitter character  hana · medium · 1 s"),
        ("jitter", "effect jitter hana on", {"character": "hana", "action": "on"},
         "Jitter character  hana · on"),
        ("jitter", "effect jitter hana off", {"character": "hana", "action": "off"},
         "Jitter character  hana · off"),
    ], how)
    # ``off`` drops a size and a length, ``on`` a length: the line always loads.
    glitch = form_by_key("glitch")
    assert glitch.write({"glitch": "tear", "size": "large", "action": "off",
                         "seconds": "2"}) == "effect tear off"
    assert glitch.write({"glitch": "tear", "size": "large", "action": "on",
                         "seconds": "2"}) == "effect tear large on"
    _check([
        ("effect_off", "effect off", {}, "Stop effects"),
        ("window_title", 'effect window_title "She is still here"',
         {"action": "set", "title": "She is still here"}, "Window title  She is still here"),
        ("window_title", 'effect window_title "Say {{hi} \\"x\\""',
         {"action": "set", "title": 'Say {hi} "x"'}, 'Window title  Say {hi} "x"'),
        ("window_title", 'effect window_title ""', {"action": "set", "title": ""},
         "Window title"),
        ("window_title", "effect window_title off", {"action": "off", "title": ""},
         "Window title  the game's own title"),
        ("crash", "effect crash", {"message": ""}, "Fake crash  the game's own message"),
        ("crash", 'effect crash "LanternError: {username} is \\"gone\\"\\nBye"',
         {"message": 'LanternError: {username} is "gone"\nBye'},
         'Fake crash  LanternError: {username} is "gone" Bye'),
    ], None)
    assert "{username}" == form_by_key("crash").write(
        {"message": "{username}"}).split('"')[1]
    _scripts("effect tear 0.3 large", 'effect crash ""')


# --- AC-F47-31 --------------------------------------------------------------------------------

def test_ac_f47_31_voice_play_next_and_stop_forms():
    """AC-F47-31: Voice (and Stop voice), Play next (``queue``), Stop sound read and write;
    Insert's Voice and Queue music open them, and F46's Music and Sound keep their lines."""
    assert form_for_doc(_docs("voice")[0]) is form_by_key("voice")
    assert form_for_doc(_docs("queue")[0]) is form_by_key("queue")
    assert form_for_doc(_docs("stop")[0]) is form_by_key("music")
    _check([
        ("voice", 'voice "voice/hana_014.ogg"',
         {"action": "play", "file": "voice/hana_014.ogg", "fade": ""},
         "Voice  voice/hana_014.ogg"),
        ("voice", "stop voice", {"action": "stop", "file": "", "fade": ""}, "Stop voice"),
        ("voice", "stop voice fadeout 1.0", {"action": "stop", "file": "", "fade": "1.0"},
         "Stop voice  fade out 1 s"),
        ("queue", 'queue music "bgm/shrine.ogg"', {"file": "bgm/shrine.ogg", "fade": ""},
         "Play next  bgm/shrine.ogg"),
        ("queue", 'queue music "bgm/shrine.ogg" fadein 2',
         {"file": "bgm/shrine.ogg", "fade": "2"}, "Play next  bgm/shrine.ogg · fade in 2 s"),
        ("stop_sound", "stop sound", {"file": "", "fade": ""}, "Stop sound  every sound"),
        ("stop_sound", "stop sound fadeout 1", {"file": "", "fade": "1"},
         "Stop sound  every sound · fade out 1 s"),
        ("stop_sound", 'stop sound "sfx/crowd.ogg"', {"file": "sfx/crowd.ogg", "fade": ""},
         "Stop sound  sfx/crowd.ogg"),
        ("stop_sound", 'stop sound "sfx/crowd.ogg" fadeout 1.5',
         {"file": "sfx/crowd.ogg", "fade": "1.5"}, "Stop sound  sfx/crowd.ogg · fade out 1.5 s"),
        ("music", "stop music fadeout 2.0", {"action": "stop", "file": "", "fade": "2.0"},
         "Stop music  fade out 2 s"),
        ("sound", 'play sound "sfx/bell.ogg"', {"file": "sfx/bell.ogg"}, "Sound  sfx/bell.ogg"),
    ], None)
    _scripts('queue music "a.ogg" once', 'queue music "a.ogg" volume 40',
             'queue music "a.ogg" fadein 2 once')


# --- AC-F47-32 --------------------------------------------------------------------------------

def test_ac_f47_32_full_screen_text_and_chapter_forms():
    """AC-F47-32: Full-screen text (Start / New page / End) and Chapter (heading, title, card
    seconds, transition, fade colour; the name made from the title) read and write every
    shape; Insert's ``nvl`` and ``chapter`` open them."""
    assert form_for_doc(_docs("nvl")[0]) is form_by_key("nvl")
    assert form_for_doc(_docs("chapter")[0]) is form_by_key("chapter")
    _check([
        ("nvl", "nvl on", {"page": "start"}, "Full-screen text  start"),
        ("nvl", "nvl clear", {"page": "new page"}, "Full-screen text  new page"),
        ("nvl", "nvl off", {"page": "end"}, "Full-screen text  end"),
    ], None)
    blank = {"name": "", "heading": "", "title": "", "hold": "", "transition": "",
             "seconds": "", "colour": ""}
    _check([
        ("chapter", 'chapter prologue "Prologue"', {"name": "prologue", "title": "Prologue"},
         "Chapter  Prologue"),
        ("chapter", 'chapter festival "Chapter 2" "The Lantern Festival"',
         {"name": "festival", "heading": "Chapter 2", "title": "The Lantern Festival"},
         "Chapter  Chapter 2: The Lantern Festival"),
        ("chapter", 'chapter river "Chapter 3" "By the River" 5 with dissolve 1.5',
         {"name": "river", "heading": "Chapter 3", "title": "By the River", "hold": "5",
          "transition": "dissolve", "seconds": "1.5"},
         "Chapter  Chapter 3: By the River · 5 s · dissolve 1.5 s"),
        ("chapter", 'chapter quiet "Quiet" 0', {"name": "quiet", "title": "Quiet", "hold": "0"},
         "Chapter  Quiet · no card"),
        ("chapter", 'chapter dusk "Dusk" with fade 2 "#ffe08a"',
         {"name": "dusk", "title": "Dusk", "transition": "fade", "seconds": "2",
          "colour": "#ffe08a"}, "Chapter  Dusk · fade 2 s #ffe08a"),
        ("chapter", "chapter dawn \"Dawn\" with fade white",
         {"name": "dawn", "title": "Dawn", "transition": "fade", "colour": "white"},
         "Chapter  Dawn · fade white"),
        ("chapter", 'chapter wave "Say \\"hi\\" {{wave}"',
         {"name": "wave", "title": 'Say "hi" {wave}'}, 'Chapter  Say "hi" {wave}'),
    ], blank)
    # An empty name is made from the title; a colour on a transition that takes none, or
    # with no transition, is never written.
    chapter = form_by_key("chapter")
    assert chapter.write({**blank, "title": "The Old Footbridge", "hold": "4"}) \
        == 'chapter the_old_footbridge "The Old Footbridge" 4'
    assert chapter.write({**blank, "name": "x", "title": "T", "transition": "dissolve",
                          "colour": "red"}) == 'chapter x "T" with dissolve'
    assert chapter.write({**blank, "name": "x", "title": "T", "colour": "red"}) \
        == 'chapter x "T"'
    taken = ("chapter_2", "the_end", "the_end_2")
    for title, name in (("Chapter 2", "chapter_2_2"), ("The End!", "the_end_3"),
                        ("2 Days Later", "chapter_2_days_later"), ("If", "chapter_if"),
                        ("…", "untitled"), ("Ça va – été", "ça_va_été"),
                        ("x" * 80, "x" * 64)):
        assert forms_more.chapter_name(title, taken) == name, title
    _scripts('chapter x "T" with fade black 1')


# --- AC-F47-33 --------------------------------------------------------------------------------

def test_ac_f47_33_lock_and_unlock_forms():
    """AC-F47-33: Lock and Unlock cover route, ending, tip and item (each with its own name
    picker; no ``unlock ending``); Insert's in-label ``lock``/``unlock`` docs open them, and
    the route and codex declarations stay the Database's."""
    lock, unlock = form_by_key("lock"), form_by_key("unlock")
    for doc in _docs("lock") + _docs("unlock"):
        want = None if doc.group == "Declarations" else form_by_key(doc.key)
        assert form_for_doc(doc) is want, doc.syntax
    assert forms.TEXT_ONLY["lock"] == forms.DATABASE_REASON
    assert [(f.key, f.name_kind) for f in lock.fields[1:]] == [
        ("route", "route"), ("ending", "ending"), ("tip", "tip"), ("item", "item")]
    assert lock.fields[0].options == ("route", "ending", "tip", "item")
    assert unlock.fields[0].options == ("route", "tip", "item")
    _check([
        ("lock", "lock route promise", {"what": "route", "route": "promise"},
         "Lock route  promise"),
        ("lock", "lock ending sad", {"what": "ending", "ending": "sad"}, "Forget ending  sad"),
        ("lock", "lock tip lanterns", {"what": "tip", "tip": "lanterns"},
         "Forget tip  lanterns"),
        ("lock", "lock item red_lantern", {"what": "item", "item": "red_lantern"},
         "Take item  red_lantern"),
    ], {"route": "", "ending": "", "tip": "", "item": ""})
    _check([
        ("unlock", "unlock route promise", {"what": "route", "route": "promise"},
         "Unlock route  promise"),
        ("unlock", "unlock tip lanterns", {"what": "tip", "tip": "lanterns"},
         "Give tip  lanterns"),
        ("unlock", "unlock item red_lantern", {"what": "item", "item": "red_lantern"},
         "Give item  red_lantern"),
    ], {"route": "", "tip": "", "item": ""})
    with pytest.raises(ValueError):
        unlock.write({"what": "ending", "ending": "sad"})

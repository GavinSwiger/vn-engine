"""Studio's edit engine (F46 ``06-acceptance.md`` AC-F46-11, 12, 17, 28-31, 34, 35, 38, 40,
41; ``04-technical.md`` §3.2, §6.3-§6.7; TR-F46-02, 03, 08). Pure: no Tk. ``StoryEditor.act``
(guard, apply, status) is the Tk step's; here ``verify`` is the gate it calls."""

import dataclasses
import re
from collections import namedtuple
from operator import attrgetter
from pathlib import Path

import pytest

import engine.script  # noqa: F401  registers every statement
from engine.core.paths import GamePaths
from engine.script.labelgraph import LINK_RULES
from engine.script.statement_docs import all_docs
from engine.tools.editor import scriptedit as se
from engine.tools.editor.document import ScriptDocument, encode, open_document
from engine.tools.editor.files import label_problem
from engine.tools.editor.scenes import SceneRead, parse_chunk
from engine.tools.editor.scriptedit import (
    Ask, Plan, Refuse, apply_lines, block_of, plan_add_arrow, plan_choice_text,
    plan_delete_arrow, plan_delete_row, plan_delete_scene, plan_form, plan_insert, plan_move,
    plan_new_scene, plan_rename, plan_retarget, rename_hits, verify)
from engine.tools.editor.syntax import indent_unit

ROOT = Path(__file__).resolve().parents[3]
L = ROOT / "tests" / "fixtures" / "F46" / "games" / "lanterns"
MAIN_REF, CH2_REF = "script/main.vns", "script/ch2.vns"
MAIN = (L / "script" / "main.vns").read_text(encoding="utf-8")
CH2 = (L / "script" / "ch2.vns").read_text(encoding="utf-8")
U = "    "
BOM = b"\xef\xbb\xbf"

Row = namedtuple("Row", "stmt block form", defaults=(None,))


def _lines(text: str) -> list[str]:
    """The editor's lines for file text: a final break ends the last line."""
    lines = text.split("\n")
    if len(lines) > 1 and lines[-1] == "":
        lines.pop()
    return lines


def _at(lines: list[str], label: str, ref: str = MAIN_REF) -> tuple[SceneRead, list[str], int]:
    for name, first, _, chunk in se._chunk_texts(lines):
        if name == label:
            read = parse_chunk(ref, chunk)
            assert read is not None
            return read, lines, first
    raise AssertionError(label)


def _scene(text: str, label: str = "s", ref: str = MAIN_REF):
    return _at(_lines(text), label, ref)


def _run(plan, texts: dict[str, list[str]]) -> dict[str, list[str]]:
    """``plan`` verified, then applied: ref → lines after."""
    assert isinstance(plan, Plan), plan
    assert verify(plan, {ref: "\n".join(lines) for ref, lines in texts.items()})
    out = dict(texts)
    for file_plan in plan.files:
        out[file_plan.ref] = apply_lines(texts[file_plan.ref], file_plan.edits)
    return out


def _one(plan, lines: list[str], ref: str = MAIN_REF) -> list[str]:
    return _run(plan, {ref: lines})[ref]


def _stmt(scene: SceneRead, start: int, line: int) -> int:
    """The statement whose head starts at absolute ``line``."""
    return next(i for i, s in enumerate(scene.statements) if s.head.first + start - 1 == line)


def _row(scene: SceneRead, start: int, line: int) -> Row:
    i = _stmt(scene, start, line)
    return Row(i, block_of(scene, i))


def _header_row(scene: SceneRead, start: int, line: int) -> Row:
    """A choice / branch header row at absolute ``line``."""
    b = next(i for i, blk in enumerate(scene.blocks)
             if blk.head is not None and blk.head.first + start - 1 == line)
    owner = scene.blocks[b].owner
    return Row(next(i for i, s in enumerate(scene.statements) if s.path == owner), b)


# --- AC-F46-11 ---------------------------------------------------------------------------------

def _variant(text: str, kind: str) -> bytes:
    if kind == "tabs":
        text = "\n".join(re.sub(r"^((?:    )+)", lambda m: "\t" * (len(m.group(1)) // 4), line)
                         for line in text.split("\n"))
    if kind == "crlf":
        return text.replace("\n", "\r\n").encode()
    if kind == "mixed":
        parts = text.split("\n")
        return "".join(p + ("\r\n" if i % 2 else "\n") if i < len(parts) - 1 else p
                       for i, p in enumerate(parts)).encode()
    if kind == "bom":
        return BOM + text.encode()
    if kind == "nofinal":
        return text.rstrip("\n").encode()
    return text.encode()


def _hits(texts, old):
    return {ref: rename_hits(ref, "\n".join(lines), old) for ref, lines in texts.items()}


ACTIONS = {
    "add arrow": lambda t, u: plan_add_arrow(*_at(t[MAIN_REF], "festival"), "river", u),
    "make a choice": lambda t, u: plan_add_arrow(*_at(t[MAIN_REF], "start"), "river", u,
                                                 choice=True),
    "delete arrow": lambda t, u: plan_delete_arrow(*_at(t[MAIN_REF], "festival"), "stall",
                                                   "call"),
    "retarget": lambda t, u: plan_retarget(*_at(t[MAIN_REF], "start"), "festival", "river",
                                           "jump"),
    "choice text": lambda t, u: plan_choice_text(*_at(t[CH2_REF], "stall", CH2_REF), (0, 0),
                                                 'Buy "red"'),
    "new scene": lambda t, u: plan_new_scene(t[MAIN_REF], MAIN_REF, "at_the_river", u, None),
    "delete scene": lambda t, u: plan_delete_scene(*_at(t[MAIN_REF], "festival"),
                                                   confirm=True),
    "rename": lambda t, u: plan_rename(_hits(t, "festival"), "festival", "fair", confirm=True),
    "insert": lambda t, u: plan_insert(*(a := _at(t[MAIN_REF], "festival")),
                                       _row(a[0], a[2], 14), ["scene bg room with fade"]),
    "form": lambda t, u: plan_form(*(a := _at(t[MAIN_REF], "start")), _row(a[0], a[2], 9),
                                   'hana happy "Hello!"'),
    "move": lambda t, u: plan_move(*(a := _at(t[MAIN_REF], "start")), _row(a[0], a[2], 9), -1),
    "delete row": lambda t, u: plan_delete_row(*(a := _at(t[MAIN_REF], "festival")),
                                               _row(a[0], a[2], 14)),
}


def _check_bytes(before: bytes, after: bytes, doc: ScriptDocument, edits, kind: str,
                 last_line: str) -> None:
    assert after.startswith(BOM) == before.startswith(BOM)
    if last_line:   # (a scene deleted at the end leaves the blank line above it last)
        assert after.endswith((b"\n", b"\r")) == before.endswith((b"\n", b"\r"))
    old = before.removeprefix(BOM).splitlines(keepends=True)
    new = after.removeprefix(BOM).splitlines(keepends=True)
    if not last_line and not doc.final_newline:
        new.append(b"")                          # an empty last line has no bytes
    ordered = sorted(edits, key=attrgetter("first"))
    touched = {n for e in ordered for n in range(e.first, e.last + 1)}

    def shift(at: int) -> int:
        return sum(len(e.lines) - (e.last - e.first + 1) for e in ordered if e.last < at)

    for i in range(1, len(old) + 1):
        if i in touched:
            continue
        j = i + shift(i)
        got = new[j - 1]
        if got != old[i - 1]:      # only the break of a last line (no final break) moves
            assert kind == "nofinal" and (i == len(old) or j == len(new))
            assert got.rstrip(b"\r\n") == old[i - 1].rstrip(b"\r\n")
    newline = doc.newline.encode()
    for n, e in enumerate(ordered):
        before_e = sum(len(x.lines) - (x.last - x.first + 1) for x in ordered[:n])
        for k, text in enumerate(e.lines):
            j = e.first + before_e + k
            got = new[j - 1]
            if j < len(new) and kind != "mixed":
                assert got[len(got.rstrip(b"\r\n")):] == newline
            lead = text[:len(text) - len(text.lstrip(" \t"))]
            assert (" " not in lead) if kind == "tabs" else ("\t" not in lead)


@pytest.mark.parametrize("kind", ["lf", "crlf", "mixed", "bom", "tabs", "nofinal"])
def test_ac_f46_11_only_planned_lines_change(tmp_path, kind):
    game = tmp_path / "game"
    (game / "script").mkdir(parents=True)
    (game / "config.toml").write_bytes((L / "config.toml").read_bytes())
    raw = {MAIN_REF: _variant(MAIN, kind), CH2_REF: _variant(CH2, kind)}
    docs: dict[str, ScriptDocument] = {}
    for ref, data in raw.items():
        (game / ref).write_bytes(data)
        doc = open_document(GamePaths.for_game(game), ref)
        assert isinstance(doc, ScriptDocument), doc
        docs[ref] = doc
    texts = {ref: doc.text.split("\n") for ref, doc in docs.items()}
    unit = indent_unit(docs[MAIN_REF].text)
    assert unit == ("\t" if kind == "tabs" else U)
    for name, action in ACTIONS.items():
        plan = action(texts, unit)
        assert isinstance(plan, Plan), (name, plan)
        after = _run(plan, texts)
        for file_plan in plan.files:
            ref = file_plan.ref
            data = encode(docs[ref], "\n".join(after[ref]))
            _check_bytes(raw[ref], data, docs[ref], file_plan.edits, kind, after[ref][-1])
        if name == "form":
            line = after[MAIN_REF][8]
            assert line == ("\t" if kind == "tabs" else U) + 'hana happy "Hello!"  # first line'

    # A 2-line say becomes one line; a form closed unchanged plans nothing.
    lines = _lines('label s:\n    hana "One\n        two."  # note\n    return\n')
    scene, _, start = _at(lines, "s")
    row = _row(scene, start, 2)
    plan = plan_form(scene, lines, start, row, 'hana "One two."')
    assert _one(plan, lines) == ["label s:", '    hana "One two."  # note', "    return"]
    lines = _lines(MAIN)
    scene, _, start = _at(lines, "start")
    row = _row(scene, start, 9)
    assert plan_form(scene, lines, start, row, 'hana happy "Welcome to the festival!"') is None

    class Unchanged:
        @staticmethod
        def read(node, code):
            return {"text": node.text}

        @staticmethod
        def write(values):
            return f'hana happy "{values["text"]}"'
    assert plan_form(scene, lines, start, row, {"text": "Welcome to the festival!"},
                     form=Unchanged) is None
    plan = plan_form(scene, lines, start, row, {"text": "Hi!"}, form=Unchanged)
    assert _one(plan, lines)[8] == '    hana happy "Hi!"  # first line'
    forms = se._forms()
    if forms is not None:               # forms.py's real rows and Say form
        say = next(r for r in forms.rows(scene, lines[start - 1:]) if r.form == "say")
        assert plan_form(scene, lines, start, say, say.values) is None
        plan = plan_form(scene, lines, start, say, {**say.values, "text": "Hi!"})
        assert _one(plan, lines)[8] == '    hana happy "Hi!"  # first line'


# --- AC-F46-12 ---------------------------------------------------------------------------------

def test_ac_f46_12_failed_check_writes_nothing(monkeypatch):
    assert se.UNSAFE == "Studio couldn't make this change safely. Change it in the text."
    lines = _lines(MAIN)
    texts = {MAIN_REF: "\n".join(lines)}
    scene, _, start = _at(lines, "start")

    class DropsQuote:                               # the Say form's write, broken
        @staticmethod
        def write(values):
            return f'hana happy "{values["text"]}'
    plan = plan_form(scene, lines, start, _row(scene, start, 9), {"text": "Hi"},
                     form=DropsQuote)
    assert isinstance(plan, Plan) and not verify(plan, texts)
    forms = se._forms()
    if forms is not None:               # the real Say form, its write patched
        say = forms.form_by_key("say")
        broken = dataclasses.replace(say, write=lambda values: say.write(values)[:-1])
        plan = plan_form(scene, lines, start, _row(scene, start, 9),
                         {"speaker": "hana", "look": "happy", "text": "Hi"}, form=broken)
        assert isinstance(plan, Plan) and not verify(plan, texts)

    monkeypatch.setattr(se, "_go_line", lambda indent, target: f"{indent}jump rivr")
    plan = plan_add_arrow(*_at(lines, "festival"), "river", U)
    assert isinstance(plan, Plan) and not verify(plan, texts)
    # A guard that no longer matches the text (typed since the plan) fails too.
    monkeypatch.undo()
    plan = plan_add_arrow(*_at(lines, "festival"), "river", U)
    assert verify(plan, texts)
    typed = list(lines)
    typed[12] = '    "The lanterns glowed."'
    assert not verify(plan, {MAIN_REF: "\n".join(typed)})


# --- AC-F46-17 ---------------------------------------------------------------------------------

IF_SCENE = ('label s:\n    "a"\n    if coins > 0:\n        "b"\n    elif coins < 0:\n'
            '        "c"\n    else:\n        "d"\n    "e"\n')


def test_ac_f46_17_move_and_delete_rows():
    main, ch2 = _lines(MAIN), _lines(CH2)
    # 1. start's Say, Alt+Up: past the scene line and its comment.
    scene, _, start = _at(main, "start")
    after = _one(plan_move(scene, main, start, _row(scene, start, 9), -1), main)
    assert after[6:9] == [main[8], "    # Mia arrives", "    scene bg room with dissolve"]
    # 2. Just look, Alt+Up: its unit before Buy the red one's.
    stall, _, s0 = _at(ch2, "stall", CH2_REF)
    after = _one(plan_move(stall, ch2, s0, _header_row(stall, s0, 6), -1), ch2, CH2_REF)
    assert after[2:7] == ch2[5:7] + ch2[2:5]
    # 3. $ stall = "visited", Alt+Down: ch2 14 and 15 swapped verbatim.
    river, _, r0 = _at(ch2, "river", CH2_REF)
    after = _one(plan_move(river, ch2, r0, _row(river, r0, 14), 1), ch2, CH2_REF)
    assert after[13:15] == [ch2[14], ch2[13]] and after[:13] == ch2[:13]
    # 4. festival's call stall, Delete: no Ask.
    fest, _, f0 = _at(main, "festival")
    after = _one(plan_delete_row(fest, main, f0, _row(fest, f0, 14)), main)
    assert after == main[:13] + main[14:]
    # 5. A block's only row becomes $ pass at its indent.
    lines = _lines('label s:\n    menu:\n        "Stay":\n            "You stay."\n'
                   '        "Go":\n            jump s\n')
    s, _, s1 = _at(lines, "s")
    after = _one(plan_delete_row(s, lines, s1, _row(s, s1, 4)), lines)
    assert after[3] == "            $ pass" and len(after) == len(lines)
    # 6. stall's Choice row: Ask, then ch2 2-7 go.
    ask = plan_delete_row(stall, ch2, s0, _row(stall, s0, 2))
    assert ask == Ask("This row has 5 lines inside it. Delete them all?", ("Delete", "Cancel"),
                      1, 1)
    after = _one(plan_delete_row(stall, ch2, s0, _row(stall, s0, 2), confirm=True), ch2, CH2_REF)
    assert after == ch2[:1] + ch2[7:]
    # 7. An elif row doesn't move; 8. an if row moves with all its branches.
    lines = _lines(IF_SCENE)
    s, _, s1 = _at(lines, "s")
    assert plan_move(s, lines, s1, _header_row(s, s1, 5), -1) is None
    after = _one(plan_move(s, lines, s1, _header_row(s, s1, 3), 1), lines)
    assert after == lines[:2] + [lines[8]] + lines[2:8]
    # 9. The block's edges: nothing written, a status.
    assert plan_move(scene, main, start, _row(scene, start, 8), -1) == Refuse("Already at the top.")
    assert plan_move(scene, main, start, _row(scene, start, 10), 1) \
        == Refuse("Already at the bottom.")


# --- AC-F46-28 ---------------------------------------------------------------------------------

def _menu(n: int) -> str:
    return "label s:\n    menu:\n" + "".join(
        f'        "C{i}":\n            jump t{i}\n' for i in range(n))


def test_ac_f46_28_adding_an_arrow():
    main, ch2 = _lines(MAIN), _lines(CH2)
    # festival ends with return: it is replaced, and the status says so.
    plan = plan_add_arrow(*_at(main, "festival"), "river", U)
    assert plan.status == "Replaced 'return' with 'go to `river`'."
    assert _one(plan, main)[14] == "    jump river"
    # start ends with a top-level jump: Make a choice.
    ask = plan_add_arrow(*_at(main, "start"), "river", U)
    assert ask == Ask("`start` already goes to `festival`. Turn this into a choice?",
                      ("Make a choice", "Cancel"), 1, 0)
    plan = plan_add_arrow(*_at(main, "start"), "river", U, choice=True)
    assert plan.then == ("choice_text", "river")
    assert _one(plan, main)[9:15] == [
        "    menu:", '        "Go to festival":', "            jump festival",
        '        "Go to river":', "            jump river", ""]
    # river, its return deleted, to itself: a loop after ch2 16.
    cut = ch2[:16]
    after = _one(plan_add_arrow(*_at(cut, "river", CH2_REF), "river", U), cut, CH2_REF)
    assert after == cut + ["    jump river"]
    # A narration line; an if block; a menu that falls through: jump after it.
    for text in ('label s:\n    "x"\n', 'label s:\n    if c:\n        "x"\n',
                 'label s:\n    menu:\n        "A":\n            jump t\n'
                 '        "B":\n            "x"\n'):
        lines = _lines(text)
        assert _one(plan_add_arrow(*_at(lines, "s"), "river", U), lines) \
            == lines + ["    jump river"]
    # A menu whose every choice ends in a jump gains a choice, at its own indents.
    lines = _lines(_menu(2))
    plan = plan_add_arrow(*_at(lines, "s"), "river", U)
    assert _one(plan, lines) == lines + ['        "Go to river":', "            jump river"]
    lines = _lines(_menu(6))
    assert plan_add_arrow(*_at(lines, "s"), "river", U) \
        == Refuse("A choice can have at most 6 options.")


# --- AC-F46-29 ---------------------------------------------------------------------------------

def test_ac_f46_29_deleting_an_arrow():
    main, ch2 = _lines(MAIN), _lines(CH2)
    assert _one(plan_delete_arrow(*_at(main, "festival"), "stall", "call"), main) \
        == main[:13] + main[14:]
    stall = _at(ch2, "stall", CH2_REF)
    assert _one(plan_delete_arrow(*stall, "river", "jump"), ch2, CH2_REF) == ch2[:8] + ch2[9:]
    assert plan_delete_arrow(*stall, "river", "menu") == Ask(
        'Delete the choice "Buy the red one" and its 3 lines?', ("Delete", "Cancel"), 1, 1)
    assert _one(plan_delete_arrow(*stall, "river", "menu", confirm=True), ch2, CH2_REF) \
        == ch2[:2] + ch2[5:]
    # A choice whose block is only the jump: no Ask.
    lines = _lines('label s:\n    menu:\n        "A":\n            jump river\n'
                   '        "B":\n            jump t\n')
    assert _one(plan_delete_arrow(*_at(lines, "s"), "river", "menu"), lines) \
        == lines[:2] + lines[4:]
    # A menu's last choice, the menu has a question: Ask, then the whole menu.
    lines = _lines('label s:\n    "x"\n    menu:\n        hana "Where?"\n'
                   '        "A":\n            jump river\n')
    assert isinstance(plan_delete_arrow(*_at(lines, "s"), "river", "menu"), Ask)
    assert _one(plan_delete_arrow(*_at(lines, "s"), "river", "menu", confirm=True), lines) \
        == lines[:2]
    # Inside an if; from two lines; emptying a choice or the scene: refused.
    lines = _lines('label s:\n    "x"\n    if c:\n        jump river\n')
    assert plan_delete_arrow(*_at(lines, "s"), "river", "jump") == Refuse(
        "This arrow comes from a line inside an 'if'. Change it in the text.", (MAIN_REF, 4))
    lines = _lines('label s:\n    if c:\n        "x"\n    jump river\n    jump river\n')
    assert plan_delete_arrow(*_at(lines, "s"), "river", "jump") \
        == Refuse("This arrow comes from 2 lines. Change them in the text.")
    lines = _lines('label s:\n    menu:\n        "A":\n            call stall\n')
    assert plan_delete_arrow(*_at(lines, "s"), "stall", "call").text == (
        "Deleting this arrow would leave the choice with nothing in it. "
        "Delete the choice instead.")
    lines = _lines("label s:\n    jump river\n")
    assert plan_delete_arrow(*_at(lines, "s"), "river", "jump").text == (
        "Deleting this arrow would leave the scene with nothing in it. "
        "Delete the scene instead.")


# --- AC-F46-30 ---------------------------------------------------------------------------------

@pytest.mark.parametrize(("path", "text", "line"), [
    ((0, 0), 'Buy "red"', '        "Buy \\"red\\"" if coins > 0:'),
    ((0, 1), "back\\slash", '        "back\\\\slash":'),
    ((0, 1), "one\ntwo", '        "one\\ntwo":'),
    ((0, 1), "赤いのを買う 🏮", '        "赤いのを買う 🏮":'),
    ((0, 0), "Buy the red one", None),
])
def test_ac_f46_30_choice_text(path, text, line):
    ch2 = _lines(CH2)
    plan = plan_choice_text(*_at(ch2, "stall", CH2_REF), path, text)
    if line is None:
        assert plan is None
        return
    number = 3 if path == (0, 0) else 6
    after = _one(plan, ch2, CH2_REF)
    assert after[number - 1] == line
    assert after[:number - 1] + after[number:] == ch2[:number - 1] + ch2[number:]


# --- AC-F46-31 ---------------------------------------------------------------------------------

def test_ac_f46_31_new_scene():
    main = _lines(MAIN)
    tail = ["", "label at_the_river:", '    "(Write what happens in this scene.)"']
    plan = plan_new_scene(main, MAIN_REF, "at_the_river", U, (213, 87))
    assert _one(plan, main) == main + tail
    assert dict(plan.places) == {"at_the_river": (220, 80)}
    assert plan.files[0].select == (len(main) + 3, 5, 5 + len(se.PLACEHOLDER))
    blank = main + [""]
    assert _one(plan_new_scene(blank, MAIN_REF, "at_the_river", U, None), blank) \
        == main + tail
    tabs = [line.replace(U, "\t") for line in main]
    assert _one(plan_new_scene(tabs, MAIN_REF, "at_the_river", "\t", None), tabs)[-1] \
        == '\t"(Write what happens in this scene.)"'
    # With no click, the caller's place_free spot (on the grid) is kept.
    assert dict(plan_new_scene(main, MAIN_REF, "x", U, (240, 0)).places) == {"x": (240, 0)}
    assert plan_new_scene(main, MAIN_REF, "river", U, None, taken={"river"}) \
        == Refuse("There is already a scene named `river`.")
    assert plan_new_scene(main, MAIN_REF, "2nd", U, None) == Refuse(label_problem("2nd"))


# --- AC-F46-34 ---------------------------------------------------------------------------------

BANNED = re.compile(r"(?<![\w$])(label|jump|call|menu|pause|define|default|node)(?!\w)|\$",
                    re.IGNORECASE)


def test_ac_f46_34_plain_words():
    texts = [value for name, value in vars(se).items()
             if name.isupper() and isinstance(value, str) and name != "START"
             and name != "THEN_CHOICE_TEXT"]
    main, ch2 = _lines(MAIN), _lines(CH2)
    texts += [plan_add_arrow(*_at(main, "festival"), "river", U).status,
              plan_delete_scene(*_at(ch2, "river", CH2_REF), arrows=2).text,
              plan_rename(_hits({MAIN_REF: main, CH2_REF: ch2}, "stall"), "stall", "x").text]
    for action in ACTIONS.values():
        texts.append(action({MAIN_REF: main, CH2_REF: ch2}, U).title)
    # Step 5: the Story and context menus, the toolbar, the dialogs and the empty states.
    from engine.tools.editor import eventsview, formdialogs, views, window
    texts += [value for name, value in vars(window).items()
              if name.startswith("STORY_") or name in ("CHOICE_STATUS", "NO_SCRIPT_FOR_SCENE")]
    texts += [views.NEW_SCENE_BUTTON, views.TIDY_UP, views.START_ONLY_TITLE,
              views.START_ONLY_HINT, views.START_ONLY_BUTTON, eventsview.NO_SCENE,
              eventsview.NO_SCENE_TITLE]
    texts += [value for name, value in vars(formdialogs).items() if name.isupper()
              and isinstance(value, str) and name.startswith(("SCENE", "NEW_SCENE",
                                                               "PICK_SCENE", "NO_SCENES"))]
    assert len(texts) > 40
    for text in texts:
        assert not BANNED.search(re.sub(r"`[^`]*`", "", text)), text


# --- AC-F46-35 ---------------------------------------------------------------------------------

def test_ac_f46_35_dialog_defaults():
    main, ch2 = _lines(MAIN), _lines(CH2)
    stall = _at(ch2, "stall", CH2_REF)
    lines = _lines('label s:\n    "x"\n    menu:\n        hana "Where?"\n'
                   '        "A":\n            jump river\n')
    asks = [plan_delete_row(*stall, _row(stall[0], stall[2], 2)),               # 17
            plan_add_arrow(*_at(main, "start"), "river", U),                    # 28
            plan_delete_arrow(*stall, "river", "menu"),                         # 29
            plan_delete_arrow(*_at(lines, "s"), "river", "menu"),
            plan_rename(_hits({MAIN_REF: main, CH2_REF: ch2}, "stall"), "stall", "x"),  # 38
            plan_delete_scene(*_at(ch2, "river", CH2_REF), arrows=2)]           # 40
    for ask in asks:
        assert isinstance(ask, Ask), ask
        assert ask.buttons[ask.escape] == "Cancel"
        assert ask.buttons[ask.default] not in ("Delete", "Rename")


# --- AC-F46-38 ---------------------------------------------------------------------------------

def test_ac_f46_38_rename():
    main, ch2 = _lines(MAIN), _lines(CH2)
    texts = {MAIN_REF: main, CH2_REF: ch2}
    ask = plan_rename(_hits(texts, "stall"), "stall", "lantern_stall", texts=texts)
    assert ask == Ask(
        "Rename `stall` to `lantern_stall`? 2 lines that go to it change too. "
        "Python code that names it doesn't. (2 places, first `ch2.vns`, line 14) "
        "Saves made inside this scene will start it from the beginning.",
        ("Rename", "Cancel"), 1, 1)
    plan = plan_rename(_hits(texts, "stall"), "stall", "lantern_stall", texts=texts,
                       place=(40, 60), confirm=True)
    assert dict(plan.places) == {"stall": None, "lantern_stall": (40, 60)}
    after = _run(plan, texts)
    changed = {(ref, n + 1) for ref in texts for n, (a, b) in
               enumerate(zip(texts[ref], after[ref], strict=True)) if a != b}
    assert changed == {(MAIN_REF, 14), (CH2_REF, 1), (CH2_REF, 16)}
    assert (after[MAIN_REF][13], after[CH2_REF][0], after[CH2_REF][15]) == (
        "    call lantern_stall", "label lantern_stall:", "    flowchart forget lantern_stall")
    # festival: no Python mention, so no Python sentence.
    ask = plan_rename(_hits(texts, "festival"), "festival", "fair", texts=texts)
    assert ask.text == ("Rename `festival` to `fair`? 1 line that goes to it changes too. "
                        "Saves made inside this scene will start it from the beginning.")
    # A name inside a Python string is counted and never changed (G6).
    g6 = {MAIN_REF: main, CH2_REF: ch2[:14] + ['    $ notes = ["stall"]'] + ch2[15:]}
    assert plan_rename(_hits(g6, "stall"), "stall", "lantern_stall", texts=g6).text \
        == plan_rename(_hits(texts, "stall"), "stall", "lantern_stall", texts=texts).text
    after = _run(plan_rename(_hits(g6, "stall"), "stall", "lantern_stall", confirm=True), g6)
    assert after[CH2_REF][14] == '    $ notes = ["stall"]'
    # start keeps its name; a hit file that doesn't parse or is read-only refuses it all.
    assert plan_rename(_hits(texts, "start"), "start", "begin") \
        == Refuse("The story starts at `start`, so it keeps its name.")
    broken = {MAIN_REF: main, CH2_REF: ch2[:8] + ["    jump"] + ch2[9:]}
    refused = plan_rename(_hits(broken, "stall"), "stall", "lantern_stall", confirm=True)
    assert refused == Refuse("Fix the problem in `ch2.vns`, line 9 first.", (CH2_REF, 9))
    reason = "the file is read-only."
    assert plan_rename(_hits(texts, "stall"), "stall", "lantern_stall", confirm=True,
                       locked={CH2_REF: reason}) == Refuse(reason)
    # Every doc naming a scene has a RENAME_SLOTS row or is label itself (TR-F46-08).
    slot_words = {node_type.__name__.lower() for node_type in se.RENAME_SLOTS}
    assert {word for word, _ in LINK_RULES.items()} <= slot_words
    for doc in all_docs():
        if "label" in doc.names:
            assert doc.key == "label" or doc.key in slot_words, doc.key


# --- AC-F46-40 ---------------------------------------------------------------------------------

def test_ac_f46_40_delete_scene():
    ch2 = _lines(CH2)
    river = _at(ch2, "river", CH2_REF)
    assert plan_delete_scene(*river, arrows=2) == Ask(
        "Delete the scene `river` and its 7 lines? 2 arrows lead here; those lines will show "
        "an error until you change them.", ("Delete", "Cancel"), 1, 1)
    plan = plan_delete_scene(*river, arrows=2, confirm=True)
    assert _one(plan, ch2, CH2_REF) == ch2[:10]
    assert dict(plan.places) == {"river": None}
    lines = _lines('label a:\n    "x"\n\nlabel b:\n    "y"\n\ndefine z = 1\nlabel c:\n'
                   '    "w"\n')
    after = _one(plan_delete_scene(*_at(lines, "b"), confirm=True), lines)
    assert after == ["label a:", '    "x"', "", "define z = 1", "label c:", '    "w"']
    assert plan_delete_scene(*_at(_lines(MAIN), "start")) \
        == Refuse("The start scene can't be deleted. It's where the story begins.")


# --- AC-F46-41 ---------------------------------------------------------------------------------

@pytest.mark.parametrize(("kind", "line", "text"), [
    ("jump", 9, "    jump festival"), ("menu", 5, "            jump festival")])
def test_ac_f46_41_change_target(kind, line, text):
    ch2 = _lines(CH2)
    after = _one(plan_retarget(*_at(ch2, "stall", CH2_REF), "river", "festival", kind), ch2,
                 CH2_REF)
    assert after == ch2[:line - 1] + [text] + ch2[line:]

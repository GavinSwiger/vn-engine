"""F47 P2-D: the Database's P2 declaration kinds (``declarations``, ``declplan``,
``dbmodel``; AC-F47-36, 37, 39, 41, and the pure parts of AC-F47-38 and 40, whose Tk parts are
W7's). Pure: no Tk. Every plan goes through ``verify_decl``, which re-parses the written lines
with the real parser, as the window's ``apply_plan`` does."""

import inspect

import pytest

from engine.runtime import transitions as runtime_transitions
from engine.script.diagnostics import DiagnosticSink
from engine.script.nodes import ScriptFile
from engine.script.parser import parse_file
from engine.script.statements import ParseContext
from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan as dp
from engine.tools.editor import tomlpatch
from engine.tools.editor.scriptedit import Refuse, apply_lines

MAIN = 'include "database.vns"\nlabel start:\n    "Hi."'


def _apply(plan: dp.DeclPlan, texts: dict[str, str]) -> dict[str, str]:
    """What the window does: verify against the live texts, then apply each file plan."""
    assert dp.verify_decl(plan, texts)
    out = dict(texts)
    for file_plan in plan.plan.files:
        out[file_plan.ref] = "\n".join(apply_lines(out[file_plan.ref].split("\n"),
                                                   file_plan.edits))
    return out


def _db(*lines: str) -> dict[str, str]:
    return {"script/main.vns": MAIN, dp.DATABASE_REF: "\n".join((dp.DATABASE_HEADER, *lines))}


def _of(texts: dict[str, str], kind: str) -> list[dec.Decl]:
    return [d for d in dec.scan(texts) if d.kind == kind]


def _parses(lines: tuple[str, ...]) -> bool:
    ctx = ParseContext(sink=DiagnosticSink(limit=100))
    text = "label studio_try:\n" + "\n".join("    " + line for line in lines)
    parse_file(ScriptFile("script/t.vns", "t.vns", 0), text, ctx)
    return not [d for d in ctx.sink.kept() if d.code.startswith("E")]


# --- AC-F47-36: Meters ------------------------------------------------------------------------

METERS = [
    ("points hana daichi 0 to 10", [("hana", (0, 10, None)), ("daichi", (0, 10, None))]),
    ("points courage 0 to 100 start 50  # brave", [("courage", (0, 100, 50))]),
    ("points debt -5 to 5", [("debt", (-5, 5, None))]),
    ("points luck start 3", [("luck", (None, None, 3))]),
    ("points mood", [("mood", (None, None, None))]),
    # Anything the form can't hold (or the parser refuses): Edit as script.
    ("points x 0 to 10 start 20", [("x", None)]),
    ("points x 1.5 to 3", [("x", None)]),
    ("points x 10 to 0", [("x", None)]),
    ("points a a", [("a", None), ("a", None)]),
]


@pytest.mark.parametrize("line, want", METERS, ids=range(len(METERS)))
def test_ac36_meters(line, want):
    """AC-F47-36: Meters read and write ``points`` declarations: one entry per name (a shared
    line keeps the others when one is edited or deleted), lowest/highest/start, only
    non-default parts written; names follow the meter rules in their own namespace."""
    texts = _db(line)
    found = _of(texts, dec.METER)
    got = [(d.name, None if d.values is None else
            tuple(d.values[k] for k in dec.METER_KEYS)) for d in found]
    assert got == want
    decl = found[0]
    if decl.values is None:
        assert dp.plan_edit(decl, {"low": 0, "high": 5, "start": None}, texts) == Refuse(
            dp.COMPLEX)
        return
    code = line.split("  #")[0]
    if len(found) == 1:
        assert dec.line_for(dec.METER, decl.name, decl.values) == code       # round trip
    # Edit: lowest, highest and start; a shared line keeps the other names and the comment.
    new = {"low": -3, "high": 7, "start": 2}
    after = _apply(dp.plan_edit(decl, new, texts), texts)
    lines = after[dp.DATABASE_REF].split("\n")[1:]
    mine = f"points {decl.name} -3 to 7 start 2"
    if decl.group:
        others = [n for n in decl.group if n != decl.name]
        assert lines == [code.replace(f" {decl.name}", "", 1), mine]
        assert [d.name for d in _of(after, dec.METER)] == [*others, decl.name]
    else:
        assert lines == [mine + line[len(code):]]
    assert dec.find(dec.scan(after), dec.METER, decl.name).values == new
    # Start at the engine's own start is not written; nothing to change is None.
    assert dec.meter_line(["m"], {"low": 2, "high": 9, "start": 2}) == "points m 2 to 9"
    assert dp.plan_edit(decl, decl.values, texts) is None
    with pytest.raises(ValueError):
        dec.meter_line(["m"], {"low": 0, "high": 10, "start": 11})
    # Delete: the line goes, or keeps the other names.
    gone = _apply(dp.plan_delete(decl, texts), texts)
    assert [d.name for d in _of(gone, dec.METER)] == [n for n in decl.group if n != decl.name]
    # New: into database.vns after the last meter; a character may share the name.
    with_char = dict(texts, **{dp.DATABASE_REF: texts[dp.DATABASE_REF]
                               + '\ndefine rin = Character("Rin")'})
    added = _apply(dp.plan_new(dec.METER, "rin", {"low": 0, "high": 3, "start": None},
                               with_char), with_char)
    assert added[dp.DATABASE_REF].split("\n")[1:] == [line, "points rin 0 to 3",
                                                      'define rin = Character("Rin")']
    assert dp.plan_new(dec.METER, decl.name, {}, texts) == Refuse(
        dp.NAME_CLASH.format(name=decl.name))
    assert dec.script_name("Start", (), dec.METER) == "start_2"
    entries = db.meter_entries(dec.scan(texts), {"meter_use": []})
    assert {e.name for e in entries} == {d.name for d in found} and all(e.editable for e in entries)


# --- AC-F47-37: Codex -------------------------------------------------------------------------

CODEX = [
    (['lock tip lanterns "Paper Lanterns" in "Festival":',
      '    "Lanterns are folded from {i}washi{/i}."', "",
      '    "Each carries one \\"wish\\"."'],
     dec.TIP, "lanterns", {"title": "Paper Lanterns", "category": "Festival", "image": None,
                           "text": ("Lanterns are folded from {i}washi{/i}.",
                                    'Each carries one "wish".')}),
    (['lock tip river_god "The River God"  # legend'],
     dec.TIP, "river_god", {"title": "The River God", "category": None, "image": None,
                            "text": ()}),
    (['lock item red_lantern "Red {{Lantern}" in "Things" image items red_lantern:',
      '    "Bought at the stall."'],
     dec.ITEM, "red_lantern", {"title": "Red {Lantern}", "category": "Things",
                               "image": "items red_lantern", "text": ("Bought at the stall.",)}),
    # Edit as script: a comment in the text, a tag in a title, two strings on a line.
    (['lock tip t "T":', "    # note", '    "One."'], dec.TIP, "t", None),
    (['lock tip t "{b}T{/b}"'], dec.TIP, "t", None),
    (['lock tip t "T":', '    "One." "Two."'], dec.TIP, "t", None),
]


@pytest.mark.parametrize("lines, kind, name, values", CODEX, ids=range(len(CODEX)))
def test_ac37_codex(lines, kind, name, values):
    """AC-F47-37: Codex tips and items read and write, with title, category, picture and text
    lines (one indented quoted paragraph each); an edit rewrites the whole block keeping the
    head's comment; Tips / Items switches the kind; Delete removes the block."""
    texts = _db(*lines, "points after")
    found = _of(texts, kind)
    assert [(d.name, d.first, d.last, d.values) for d in found] == [
        (name, 2, 1 + len(lines), values)]
    assert [d.name for d in _of(texts, dec.METER)] == ["after"]      # the block ended
    decl = found[0]
    if values is None:
        assert dp.plan_edit(decl, {}, texts) == Refuse(dp.COMPLEX)
        return
    comment = "  # legend" if "# legend" in lines[0] else ""
    assert dec.lines_for(kind, name, values) == tuple(
        line.replace(comment, "") for line in lines if line)          # round trip
    new = {**values, "category": "Lore", "text": ("First.", "Second {b}bold{/b}.")}
    plan = dp.plan_edit(decl, new, texts, kind=dec.ITEM if kind == dec.TIP else dec.TIP)
    after = _apply(plan, texts)
    other = dec.ITEM if kind == dec.TIP else dec.TIP
    title = dec.written_text(values["title"])
    image = f" image {values['image']}" if values["image"] else ""
    assert after[dp.DATABASE_REF].split("\n")[1:] == [
        f'lock {other} {name} "{title}" in "Lore"{image}:{comment}',
        '    "First."', '    "Second {b}bold{/b}."', "points after"]
    assert dec.find(dec.scan(after), other, name).values == new
    gone = _apply(dp.plan_delete(decl, texts), texts)
    assert gone[dp.DATABASE_REF].split("\n")[1:] == ["points after"]
    # New entries go after the last of their kind; tips and items share names.
    plan = dp.plan_new(dec.TIP, "bridge", {"title": "The Bridge", "category": None,
                                           "image": None, "text": ("Old.",)}, texts)
    added = _apply(plan, texts)[dp.DATABASE_REF].split("\n")
    assert added[-3:] == ['lock tip bridge "The Bridge":', '    "Old."', "points after"] \
        if kind == dec.TIP else added[-2:] == ['lock tip bridge "The Bridge":', '    "Old."']
    assert isinstance(dp.plan_new(other, name, values, texts), Refuse)          # one namespace
    assert isinstance(dp.plan_new(dec.TIP, "x", {**values, "title": " "}, texts), Refuse)
    entries = db.codex_entries(dec.scan(texts), {})
    assert [e.shown for e in entries[kind]] == [values["title"]]
    assert db.codex_categories(dec.scan(texts), {}) == (
        (values["category"],) if values["category"] else ())


# --- AC-F47-38 (unit part; the Tk lists are W7's): routes, endings, chapters -----------------

def test_ac38_routes_endings_chapters_model():
    """AC-F47-38 (unit): Routes read and write ``lock route … until …``; Endings and Chapters
    list their rows (``declarations.marks``) with a place for Go to."""
    story = ('label start:\n    chapter festival "Chapter 2" "The {{Lantern} Festival"\n'
             '    ending sad "Sad End"\n    ending good "Good" "The End" 5 with fade\n')
    texts = {**_db('lock route promise "Hana\'s Promise" until sad, good  # true route'),
             "script/main.vns": MAIN + "\n" + story}
    route = _of(texts, dec.ROUTE)[0]
    assert route.values == {"title": "Hana's Promise", "until": ("sad", "good")}
    plan = dp.plan_edit(route, {"title": "Promise", "until": ("good",)}, texts)
    after = _apply(plan, texts)
    assert after[dp.DATABASE_REF].split("\n")[1] == (
        'lock route promise "Promise" until good  # true route')
    assert dec.route_line("r", {"title": "R", "until": ()}) == 'lock route r "R"'
    with pytest.raises(ValueError):
        dec.route_line("r", {"title": "R", "until": ("a", "a")})
    marks = dec.marks(texts)
    assert [(m.kind, m.name, m.place, m.values) for m in marks] == [
        (dec.CHAPTER, "festival", ("script/main.vns", 5),
         {"heading": "Chapter 2", "title": "The {Lantern} Festival"}),
        (dec.ENDING, "sad", ("script/main.vns", 6), {"heading": None, "title": "Sad End"}),
        (dec.ENDING, "good", ("script/main.vns", 7), {"heading": "Good", "title": "The End"})]

    class Row:
        def __init__(self, name, file=None, line=None):
            self.name, self.file, self.line = name, file, line
    names = {"route_until": [Row("sad", dp.DATABASE_REF, 2), Row("good", dp.DATABASE_REF, 2)],
             "ending": [Row("bad", "script/x.vns", 3)], "route_use": [Row("promise", "a", 9)]}
    endings = db.ending_entries(marks, names)
    assert [(e.shown, e.uses, e.editable, e.place) for e in endings] == [
        ("bad", 0, False, ("script/x.vns", 3)), ("Sad End", 1, False, ("script/main.vns", 6)),
        ("The End", 1, False, ("script/main.vns", 7))]
    assert db.ending_names(marks, names) == ("bad", "good", "sad")
    assert [e.name for e in db.chapter_entries(marks, names)] == ["festival"]
    routes = db.route_entries(dec.scan(texts), names)
    assert [(e.shown, e.uses, e.editable) for e in routes] == [("Hana's Promise", 1, True)]
    assert db.delete_refusal(routes[0]) == (
        "Hana's Promise is used in 1 line, so it can't be deleted yet.")


# --- AC-F47-39: Transitions -------------------------------------------------------------------

TRANSITIONS = [
    ("Dissolve(1.5)", {"kind": dec.DISSOLVE, "seconds": 1.5}, 'dissolve 1.5'),
    ("Dissolve()", {"kind": dec.DISSOLVE}, "dissolve"),
    ("Dissolve(seconds=2)", {"kind": dec.DISSOLVE, "seconds": 2}, "dissolve 2"),
    ('Fade(0.6, color="#ffffff")', {"kind": dec.FADE, "seconds": 0.6, "color": "#ffffff"},
     'fade 0.6 "#ffffff"'),
    ('Fade(color="red")', {"kind": dec.FADE, "color": "red"}, "fade red"),
    ('Mask("masks/glow.png", 1.2)', {"kind": dec.MASK, "file": "masks/glow.png",
                                     "seconds": 1.2}, "lantern"),
    ('Mask("masks/glow.png", 1.2, soft=0.25, reverse=True)',
     {"kind": dec.MASK, "file": "masks/glow.png", "seconds": 1.2, "soft": 0.25,
      "reverse": True}, "lantern"),
    # Edit as script: out of range, a bad colour or file, an expression, too many arguments.
    ("Dissolve(45)", None, None),
    ('Fade(0.5, color="pink")', None, None),
    ('Mask("masks/glow.gif")', None, None),
    ('Mask("../glow.png")', None, None),
    ("Dissolve(slow)", None, None),
    ("Dissolve(1, 2)", None, None),
]


@pytest.mark.parametrize("call, want, clause", TRANSITIONS, ids=range(len(TRANSITIONS)))
def test_ac39_transitions(call, want, clause):
    """AC-F47-39: Transitions read and write Dissolve, Fade and Mask defines (only the kind's
    non-default arguments, the runtime's own defaults), with Try it lines that parse."""
    assert dec.TRANSITION_DEFAULTS["soft"] == inspect.signature(
        runtime_transitions.Mask).parameters["soft"].default
    texts = _db(f"define lantern = {call}  # glow")
    decl = _of(texts, dec.TRANSITION)[0]
    if want is None:
        assert decl.values is None
        assert dp.plan_edit(decl, {"kind": dec.DISSOLVE}, texts) == Refuse(dp.COMPLEX)
        return
    values = {"kind": want["kind"], **dec.TRANSITION_DEFAULTS, **want}
    assert decl.values == values
    written = dec.transition_call(values)
    made = eval(written, dict(runtime_transitions.CONSTRUCTORS))     # the runtime takes it
    assert made.kind == values["kind"]
    if "=" not in call or "soft" in call:                    # positional forms: same text
        assert written == call
    # Try it: the built-ins play unsaved values; a Mask plays its saved name.
    assert dec.transition_with("lantern", values) == clause
    lines = dec.transition_try_lines("lantern", values, "bg park")
    assert lines[1] == f"scene bg park with {clause}" and _parses(lines)
    # Edit: switch kinds; only the new kind's arguments are written; the comment stays.
    plan = dp.plan_edit(decl, {**values, "kind": dec.FADE, "seconds": 2.0, "color": "black"},
                        texts)
    after = _apply(plan, texts)
    assert after[dp.DATABASE_REF].split("\n")[1] == (
        'define lantern = Fade(2.0, color="black")  # glow')
    assert dp.plan_new(dec.TRANSITION, "fade", values, texts) == Refuse(
        dp.BAD_NAME.format(name="fade"))
    assert dec.script_name("Dissolve", (), dec.TRANSITION) == "dissolve_2"
    entries = db.transition_entries(dec.scan(texts), {"transition_use": []})
    assert [(e.name, e.editable) for e in entries] == [("lantern", True)]


# --- AC-F47-40 (pure part; the canvas is W7's): positions -------------------------------------

def test_ac40_positions_model():
    """AC-F47-40 (pure): Positions list the built-ins and ``[stage.positions]``; a drag
    writes x (or ``[x, y]`` off the bottom edge) with ``tomlpatch``; Delete removes it."""
    config = '[game]\ntitle = "T"\n\n[stage.positions]\nby_the_rail = 560  # rail\n'
    rows = {e.name: e.values for e in db.position_entries(config, {})}
    assert rows["by_the_rail"] == {"x": 560.0, "y": 720.0, "builtin": False, "written": True}
    assert rows["left"] == {"x": 320.0, "y": 720.0, "builtin": True, "written": False}
    moved = dp.plan_position(config, "by_the_rail", 600.5, 700)
    text = "\n".join(apply_lines(config.split("\n"), moved.edits))
    assert "by_the_rail = [600.5, 700]  # rail" in text and tomlpatch.verify(moved, config)
    added = dp.plan_position(text, "close", 400, 720, taken=("left", "by_the_rail"))
    text = "\n".join(apply_lines(text.split("\n"), added.edits))
    assert {e.name: (e.values["x"], e.values["y"]) for e in db.position_entries(text, {})}[
        "close"] == (400.0, 720.0)
    assert dp.plan_position(text, "Left", 1, 720, taken=("left",)) == Refuse(
        dp.NAME_CLASH.format(name="Left"))
    assert dp.plan_position(text, "show", 1, 720) == Refuse(dp.BAD_NAME.format(name="show"))
    assert isinstance(dp.plan_position(text, "far", 9999, 720), Refuse)
    gone = dp.plan_position_remove(text, "close")
    assert "close" not in "\n".join(apply_lines(text.split("\n"), gone.edits))
    assert db.position_entries("[stage", {}) is None


# --- AC-F47-41: Remembered across playthroughs ------------------------------------------------

REMEMBERED = [
    ("default persistent.seen_intro = False", {"kind": dec.YES_NO, "value": False}),
    ("default persistent.best = 0  # score", {"kind": dec.NUMBER, "value": 0}),
    ('default persistent.nick = "Lan"', {"kind": dec.TEXT, "value": "Lan"}),
    ("default persistent.bag = []", None),
]


@pytest.mark.parametrize("line, values", REMEMBERED, ids=range(len(REMEMBERED)))
def test_ac41_remembered_variables(line, values):
    """AC-F47-41: "Remembered across playthroughs" writes ``default persistent.<n>``: new,
    switched on and off for an existing variable (its own namespace), and read back."""
    texts = _db(line, "default trust = 0")
    decl = _of(texts, dec.PERSISTENT)[0]
    assert decl.values == values
    if values is None:
        assert dp.plan_edit(decl, {"kind": dec.NUMBER, "value": 1}, texts) == Refuse(
            dp.COMPLEX)
        return
    assert dec.line_for(dec.PERSISTENT, decl.name, values) == line.split("  #")[0]
    # Off: back to a story variable, same line, comment kept.
    off = _apply(dp.plan_edit(decl, values, texts, kind=dec.VARIABLE), texts)
    assert off[dp.DATABASE_REF].split("\n")[1] == line.replace("persistent.", "")
    # On: a story variable becomes remembered.
    trust = dec.find(dec.scan(texts), dec.VARIABLE, "trust")
    on = _apply(dp.plan_edit(trust, trust.values, texts, kind=dec.PERSISTENT), texts)
    assert on[dp.DATABASE_REF].split("\n")[2] == "default persistent.trust = 0"
    # New: a remembered variable may share a story variable's name, not an engine view's.
    new = _apply(dp.plan_new(dec.PERSISTENT, "trust", {"kind": dec.NUMBER, "value": 1}, texts),
                 texts)
    assert "default persistent.trust = 1" in new[dp.DATABASE_REF].split("\n")
    assert dp.plan_new(dec.PERSISTENT, "endings", values, texts) == Refuse(
        dp.BAD_NAME.format(name="endings"))
    assert isinstance(dp.plan_new(dec.PERSISTENT, decl.name, values, texts), Refuse)
    assert dp.plan_edit(decl, values, texts, kind=dec.METER) == Refuse(dp.SWAP_REFUSED)
    remembered = db.remembered_entries(dec.scan(texts), {})
    assert [(e.name, e.editable) for e in remembered] == [(decl.name, True)]
    assert db.REMEMBERED == "Remembered across playthroughs"

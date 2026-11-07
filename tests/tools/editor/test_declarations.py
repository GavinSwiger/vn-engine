"""F47 P1-B: the Database's declaration readers, writers and plans (``declarations``,
``declplan``; AC-F47-05, 06, 08, 14). Pure: no Tk. The Tk tab is W2/W3's (AC-F47-04, 07);
here ``verify_decl`` is the gate the window's ``apply_plan`` calls."""

import dataclasses

import pytest

from engine.runtime import character as runtime_character
from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan as dp
from engine.tools.editor.dbmodel import Entry
from engine.tools.editor.scriptedit import STALE, Refuse, apply_lines

DEFAULTS = dict(dec.OPTION_DEFAULTS)


def _apply(plan: dp.DeclPlan, texts: dict[str, str]) -> dict[str, str]:
    """What the window does: verify against the live texts, then apply each file plan."""
    assert dp.verify_decl(plan, texts)
    out = dict(texts)
    for file_plan in plan.plan.files:
        out[file_plan.ref] = "\n".join(apply_lines(out[file_plan.ref].split("\n"),
                                                   file_plan.edits))
    return out


def test_character_options_match_the_runtime():
    """04 §17: Studio's own option table is the runtime's, in the same (doc) order, with the
    runtime's defaults (``BlipSpec``)."""
    assert [name for name, _ in dec.CHARACTER_OPTIONS] == list(
        runtime_character.CHARACTER_OPTIONS)
    blip = {f.name: f.default for f in dataclasses.fields(runtime_character.BlipSpec)}
    assert (DEFAULTS["blip_every"], DEFAULTS["blip_pitch"], DEFAULTS["blip_volume"]) == (
        blip["every"], blip["spread"], blip["volume"])
    made = runtime_character.Character("Rin", {})
    assert DEFAULTS["color"] is made.color is None and made.blip is None


READS = [
    ('define rin = Character("Rin")', {"name": "Rin"}),
    ('define rin = Character("Rin", color="#e06c9f", text_italic=True)  # hi',
     {"name": "Rin", "color": "#e06c9f", "text_italic": True}),
    ('define hana = Character(name_from="hana_name", blip="blips/h.wav", blip_pitch=0.1)',
     {"name": None, "name_from": "hana_name", "blip": "blips/h.wav", "blip_pitch": 0.1}),
    ('define d = Character("Dai\\"chi", blip="b.ogg", blip_every=3, blip_volume=70,\n'
     '    image_tag="daichi", text_color="#1e4a9c")',
     {"name": 'Dai"chi', "blip": "b.ogg", "blip_every": 3, "blip_volume": 70,
      "image_tag": "daichi", "text_color": "#1e4a9c"}),
    ('define n = Character("")', {"name": ""}),
    # Expressions and anything the form can't hold: Edit as script.
    ("define rin = Character(name)", None),
    ('define rin = Character("Rin", color=pick())', None),
    ('define rin = Character("Rin", size=3)', None),
    ('define rin = Character("Rin", **opts)', None),
    ('define rin = Character("Rin", name_from="x")', None),
    ('define rin = Character("Rin", text_italic="yes")', None),
    ('define rin = Character("A", "B")', None),
]


@pytest.mark.parametrize("line, want", READS, ids=range(len(READS)))
def test_ac05_character_reader(line, want):
    """AC-F47-05: literal Character(...) options read into form values (every option, the
    rest at their defaults); expression forms read as Edit as script (values None)."""
    text = "# top\n" + line + "\nlabel start:\n    rin \"Hi\""
    found = [d for d in dec.scan({"script/a.vns": text}) if d.kind == dec.CHARACTER]
    assert len(found) == 1
    decl = found[0]
    assert (decl.ref, decl.first, decl.last) == ("script/a.vns", 2, 1 + line.count("\n") + 1)
    if want is None:
        assert decl.values is None
    else:
        assert decl.values == {**DEFAULTS, **want}


def test_ac06_character_writer_and_edit():
    """AC-F47-06: the writer writes only non-default options in doc order; an edit rewrites
    only the declaring line(s) and keeps the trailing comment; the plan is stale-safe."""
    values = {**DEFAULTS, "name": "Rin", "blip_volume": 80, "color": "#e06c9f",
              "blip": "blips/rin.ogg", "blip_every": 2, "text_italic": False}
    assert dec.line_for(dec.CHARACTER, "rin", values) == (
        'define rin = Character("Rin", color="#e06c9f", blip="blips/rin.ogg", blip_volume=80)')
    assert dec.character_call({"name": None, "name_from": "who"}) == 'Character(name_from="who")'
    with pytest.raises(ValueError):
        dec.line_for(dec.CHARACTER, "rin", {**values, "blip_pitch": float("nan")})

    main = ("# Characters\n"
            'define rin = Character("Rin",\n    color="#e06c9f")   # the lead\n'
            "default trust = 0\n"
            "label start:\n"
            '    rin "Hi"')
    texts = {"script/main.vns": main}
    decl = dec.find(dec.scan(texts), dec.CHARACTER, "rin")
    new = {**decl.values, "text_italic": True, "color": "#112233"}
    plan = dp.plan_edit(decl, new, texts)
    assert isinstance(plan, dp.DeclPlan) and len(plan.plan.files) == 1
    after = _apply(plan, texts)["script/main.vns"].split("\n")
    old = main.split("\n")
    assert after == [old[0],
                     'define rin = Character("Rin", color="#112233", text_italic=True)'
                     "   # the lead", *old[3:]]
    assert dec.find(dec.scan({"script/main.vns": "\n".join(after)}),
                    dec.CHARACTER, "rin").values == new
    assert dp.plan_edit(decl, decl.values, texts) is None                 # nothing to write
    # Stale: the line changed after planning → verify fails; a stale decl is refused.
    typed = {"script/main.vns": main.replace("the lead", "the hero")}
    assert not dp.verify_decl(plan, typed)
    assert dp.plan_edit(decl, new, {"script/main.vns": "\n" + main}) == Refuse(STALE)
    # A form can't edit an expression: Edit as script.
    expr = {"script/a.vns": "define e = Character(name)"}
    assert dp.plan_edit(dec.scan(expr)[0], {}, expr) == Refuse(dp.COMPLEX)
    # Delete removes exactly the declaring lines.
    gone = _apply(dp.plan_delete(decl, texts), texts)["script/main.vns"]
    assert gone.split("\n") == [old[0], *old[3:]]


def test_ac07_new_declarations_go_to_database_vns():
    """AC-F47-07's plan (the Tk step applies it): the first new declaration creates
    ``script/database.vns`` (header only) and includes it in main.vns once; later ones go
    after the last of their kind there; a name clash is refused with §6.4's text."""
    main = '# My game\ninclude "chapter1.vns"\nlabel start:\n    "Hi."'
    texts = {"script/main.vns": main, "script/chapter1.vns": "label ch1:\n    return"}
    plan = dp.plan_new(dec.CHARACTER, "rin", {"name": "Rin"}, texts)
    assert plan.create == dp.DATABASE_REF and dp.DATABASE_TEXT == dp.DATABASE_HEADER + "\n"
    assert dp.DATABASE_HEADER == "# Made in Studio's Database. You can also edit it by hand."
    assert [f.ref for f in plan.plan.files] == [dp.DATABASE_REF, "script/main.vns"]
    texts[dp.DATABASE_REF] = dp.DATABASE_HEADER          # created; its editor text
    texts = _apply(plan, texts)
    assert texts[dp.DATABASE_REF] == dp.DATABASE_HEADER + '\ndefine rin = Character("Rin")'
    assert texts["script/main.vns"].split("\n")[1:3] == [
        'include "chapter1.vns"', 'include "database.vns"']
    plan = dp.plan_new(dec.VARIABLE, "trust", {"kind": dec.NUMBER, "value": 0}, texts)
    texts = _apply(plan, texts)
    plan = dp.plan_new(dec.CHARACTER, "kai", {"name": "Kai"}, texts)
    assert plan.create is None and len(plan.plan.files) == 1           # include only once
    texts = _apply(plan, texts)
    assert texts[dp.DATABASE_REF].split("\n")[1:] == [
        'define rin = Character("Rin")', 'define kai = Character("Kai")', "default trust = 0"]
    clash = dp.plan_new(dec.VARIABLE, "Rin", {"kind": dec.TEXT, "value": ""}, texts)
    assert clash == Refuse("There's already something called Rin. Pick another name.")
    assert isinstance(dp.plan_new(dec.VARIABLE, "label", {"kind": dec.TEXT, "value": ""},
                                  texts), Refuse)
    # Stale: database.vns grew after planning.
    plan = dp.plan_new(dec.COLOR, "bg dusk", {"color": "#203040"}, texts)
    grown = dict(texts, **{dp.DATABASE_REF: texts[dp.DATABASE_REF] + "\n# more"})
    assert dp.verify_decl(plan, texts) and not dp.verify_decl(plan, grown)


@pytest.mark.parametrize("shown, taken, kind, want", [
    ("Rin", (), dec.CHARACTER, "rin"),
    ("Mary Jane-Watson!", (), dec.CHARACTER, "mary_jane_watson"),
    ("Zoë", (), dec.CHARACTER, "zoë"),
    ("Rin", ("rin",), dec.CHARACTER, "rin_2"),
    ("Rin", ("RIN", "rin_2"), dec.CHARACTER, "rin_3"),
    ("Show", (), dec.CHARACTER, "show_2"),                 # a statement word
    ("If", (), dec.CHARACTER, "if_2"),                     # a Python keyword
    ("Narrator", (), dec.CHARACTER, "narrator_2"),         # an engine name
    ("At", (), dec.CHARACTER, "at_2"),                     # a modifier word
    ("2B", (), dec.CHARACTER, "character_2b"),
    ("???", (), dec.CHARACTER, "character"),
    ("Trust level", ("trust_level",), dec.VARIABLE, "trust_level_2"),
    ("Dusk sky", ("bg dusk_sky",), dec.COLOR, "bg dusk_sky_2"),
])
def test_ac08_script_names(shown, taken, kind, want):
    """AC-F47-08: script names from shown names (slug), a clash or reserved word gets _2,
    _3…; the name is editable only while the entry is unused."""
    assert dec.script_name(shown, taken, kind) == want
    assert not dec.name_problem(want, kind)
    unused = Entry(kind, want, shown, None, True, 0)
    assert unused.name_editable
    assert not dataclasses.replace(unused, uses=1).name_editable
    assert not dataclasses.replace(unused, editable=False).name_editable


VARIABLES = [
    ("default trust = 0", {"kind": dec.NUMBER, "value": 0}),
    ("default speed = -1.5", {"kind": dec.NUMBER, "value": -1.5}),
    ('default nick = "Lan \\"Lantern\\""', {"kind": dec.TEXT, "value": 'Lan "Lantern"'}),
    ("default met = False  # set in ch1", {"kind": dec.YES_NO, "value": False}),
    ("default met = True", {"kind": dec.YES_NO, "value": True}),
]


@pytest.mark.parametrize("line, values", VARIABLES, ids=range(len(VARIABLES)))
def test_ac14_variables(line, values):
    """AC-F47-14: Variables read and write ``default`` for Number, Text and Yes-No; anything
    else is Edit as script; Set variable and If pick from ``variable_names``."""
    from engine.tools.editor.dbmodel import variable_names
    texts = {"script/main.vns": f"{line}\ndefault bag = []\ndefault persistent.seen = 0"}
    decls = dec.scan(texts)
    assert [(d.kind, d.name) for d in decls] == [
        (dec.VARIABLE, decls[0].name), (dec.VARIABLE, "bag"), (dec.PERSISTENT, "seen")]
    assert decls[0].values == values and decls[1].values is None
    code = line.split("  #")[0]
    assert dec.line_for(dec.VARIABLE, decls[0].name, values) == code
    assert variable_names(decls, {"variable": ()}) == tuple(sorted((decls[0].name, "bag")))
    flipped = {"kind": dec.TEXT, "value": "x"}
    plan = dp.plan_edit(decls[0], flipped, texts)
    after = _apply(plan, texts)
    assert dec.scan(after)[0].values == flipped
    with pytest.raises(ValueError):
        dec.line_for(dec.VARIABLE, "x", {"kind": dec.YES_NO, "value": 1})


def test_one_scan_per_script_text(monkeypatch):
    """v1 finding 4: a long script's statements and declarations are read once per text
    (by digest) and shared; a changed text is read again; each caller gets its own lists;
    ``memo_texts`` answers once per set of texts."""
    from engine.tools.editor import contactmodel, dbmodel

    body = "".join(f'define m{i} = ["Hi {i}."]\n' for i in range(200))
    text = 'define hana = Character("Hana")\n' + body
    assert len(text) >= dec.SCAN_CACHE_MIN_CHARS
    calls: list[int] = []
    real = dec._statements
    monkeypatch.setattr(dec, "_statements", lambda t: (calls.append(1), real(t))[1])
    texts = {"script/main.vns": text}
    first = dec.scan(texts)
    assert dec.scan(dict(texts)) == first and len(calls) == 1
    lines = next(iter(dec.statements(text)))[2]
    lines.append("changed by a caller")
    assert next(iter(dec.statements(text)))[2] == ['define hana = Character("Hana")']
    assert len(calls) == 1
    changed = {"script/main.vns": text.replace("Hana", "Hanako")}
    assert dec.find(dec.scan(changed), dec.CHARACTER, "hana").values[dec.NAME] == "Hanako"
    assert len(calls) == 2
    assert dbmodel.include_order(texts) is dbmodel.include_order(dict(texts))
    assert contactmodel._defines(texts) is contactmodel._defines(dict(texts))
    assert contactmodel._defines(changed) is not contactmodel._defines(texts)

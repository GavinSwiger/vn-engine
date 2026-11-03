"""Studio's command forms and Events rows, pure half (F46 ``06-acceptance.md`` AC-F46-06, 07,
08, 10, 14, 15, 19; ``04-technical.md`` §3.3, §6.7; TR-F46-01). No Tk."""

from dataclasses import replace
from pathlib import Path

import engine.script  # noqa: F401  registers every statement
from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.script import statement_docs
from engine.script.statement_docs import StatementDoc, all_docs, register_doc
from engine.script.statements import scoped_registry
from engine.tools.editor import forms, scenes
from engine.tools.editor.forms import (
    CHOICE_FORM, CHOICE_LIMIT_TEXT, ChoiceItem, ChoiceValues, Patch, choice_patches, code_of,
    form_by_key, form_for_doc, missing_forms, quote, read_choice, rows)
from engine.tools.editor.scenes import chunks, parse_chunk

ROOT = Path(__file__).resolve().parents[3]
L = ROOT / "tests" / "fixtures" / "F46" / "games" / "lanterns" / "script"
MAIN = (L / "main.vns").read_text(encoding="utf-8")
CH2 = (L / "ch2.vns").read_text(encoding="utf-8")


def _scene(text: str, name: str, positions: frozenset[str] = frozenset()):
    """``name``'s chunk of ``text``: its read and its lines (chunk line k is lines[k - 1])."""
    all_lines = text.split("\n")
    for label, first, last in chunks(text):
        if label == name:
            chunk = "\n".join(all_lines[first - 1:last]) + "\n"
            read = parse_chunk("script/t.vns", chunk, positions=positions)
            assert read is not None and read.error is None, read
            return read, chunk.split("\n")[:-1]
    raise AssertionError(name)


def _inline(*body: str):
    return _scene("label t:\n" + "".join(f"    {line}\n" for line in body), "t")


def _texts(text: str, name: str) -> list[tuple[int, str]]:
    read, lines = _scene(text, name)
    return [(row.depth, row.text) for row in rows(read, lines)]


def _head(read, row):
    if row.kind == "header":
        return read.blocks[row.block].head
    return read.statements[row.stmt].head


def _apply(lines: list[str], patches) -> list[str]:
    out = list(lines)
    for patch in sorted(patches, key=lambda p: p.first, reverse=True):
        out[patch.first - 1:patch.last] = patch.lines
    return out


def test_event_rows(monkeypatch):
    """AC-F46-06."""
    assert _texts(MAIN, "start") == [
        (0, "Background  bg room · dissolve"), (0, "Say  hana (happy): Welcome to the festival!"),
        (0, "Go to scene  festival"), (0, "◆")]
    assert _texts(CH2, "stall") == [
        (0, "Choice  (no question)"),
        (1, '"Buy the red one"  if coins is more than 0'),
        (2, "Script  $ coins = max(0, coins - 1)"), (2, "Go to scene  river"), (2, "◆"),
        (1, '"Just look"'),
        (2, "(nothing)"), (2, "◆"),
        (0, "Narration  You walk past the stall."), (0, "Go to scene  river"), (0, "◆")]

    read, lines = _inline("menu:", '    hana "Which one?"', '    "A":', "        jump x")
    assert rows(read, lines)[0].text == "Choice  hana: Which one?"

    read, lines = _inline("if coins >= 2:", '    "Two."', "elif coins == 1:", '    "One."',
                          "else:", '    "None."')
    got = [(row.depth, row.text, row.kind) for row in rows(read, lines)]
    assert got == [
        (0, "If  coins is at least 2", "stmt"), (1, "Narration  Two.", "stmt"), (1, "◆", "end"),
        (0, "Else if  coins is 1", "header"), (1, "Narration  One.", "stmt"), (1, "◆", "end"),
        (0, "Else", "header"), (1, "Narration  None.", "stmt"), (1, "◆", "end"),
        (0, "◆", "end")]

    assert scenes.SCENE_ROW_CAP == 2_000
    monkeypatch.setattr(scenes, "SCENE_ROW_CAP", 5)
    read, lines = _inline(*(f'"Line {n}."' for n in range(7)))
    got = [row.text for row in rows(read, lines)]
    assert got == [f"Narration  Line {n}." for n in range(5)] + [
        "2 more lines. Open the text to see them."]


def test_script_rows_form_gate(monkeypatch):
    """AC-F46-07."""
    table = [
        ("show hana happy at left with dissolve", "show"),
        ("show daichi at 760 behind hana", None),
        ("show hana happy zoom 1.3", None),
        ("show lantern_girl as girl_a at 900 flip on", None),
        ('play sound "sfx/rain.ogg" volume 40 loop', None),     # F47's Sound: loop first
        ('scene bg river_dusk with fade "#ffe08a" 0.4', None),   # F47's Transition: 0.4 first
        ("$ coins = max(0, coins - 1)", None),
        ("flowchart no jump hidden", None),                      # F47's mark: hidden first
        ("pause 1", "pause"),
    ]
    read, lines = _inline(*(line for line, _ in table))
    got = rows(read, lines)
    assert [(row.form, row.word == "Script") for row in got[:-1]] == [
        (form, form is None) for _, form in table]
    assert got[-2].values == {"seconds": "1"}
    assert form_by_key("pause").write(got[-2].values) == "pause 1"

    # One probe text per rows() call.
    calls = []
    real = forms.parse_file

    def spy(*args, **kwargs):
        calls.append(args[1])
        return real(*args, **kwargs)

    monkeypatch.setattr(forms, "parse_file", spy)
    rows(read, lines)
    assert len(calls) == 1 and calls[0].startswith(f"label {forms.PROBE_LABEL}:")

    # A read that drops ``with …`` makes the written line differ: a Script row.
    show = form_by_key("show")

    def drop_with(node, code):
        values = forms._show_read(node, code)
        return None if values is None else {**values, "transition": "", "seconds": ""}

    patched = tuple(replace(f, read=drop_with) if f is show else f for f in forms.FORMS)
    monkeypatch.setattr(forms, "FORMS", patched)
    assert rows(read, lines)[0].text == "Script  show hana happy at left with dissolve"


def _form_rows(read, lines, positions=frozenset()):
    return [row for row in rows(read, lines, positions=positions)
            if row.form not in (None, CHOICE_FORM)]


def _probe_shape_equal(read, lines, row, positions=frozenset()) -> bool:
    form = form_by_key(row.form)
    node = read.statements[row.stmt].node
    written = form.write(row.values)
    body = [f"    {written}"]
    if row.form == "if":
        if row.kind == "header":
            return True                           # the If row's probe covers its headers
        body = []
        owner = read.statements[row.stmt].path
        for block in (b for b in read.blocks if b.owner == owner):
            code, _ = code_of(lines[block.head.first - 1:block.head.last])
            body += [f"    {code}", "        $ pass"]
    probe = parse_chunk("script/t.vns", "label probe:\n" + "\n".join(body) + "\n",
                        positions=positions)
    return probe.error is None and forms.shape(probe.statements[0].node) == forms.shape(node)


def test_round_trip():
    """AC-F46-08, TR-F46-01."""
    checked = 0
    for doc in all_docs():
        body = "".join(f"    {line}\n" for line in doc.example.split("\n"))
        read = parse_chunk("script/t.vns", "label t:\n" + body)
        if read is None or read.error is not None:
            continue                              # top-level examples (label, define, …)
        lines = ("label t:\n" + body).split("\n")[:-1]
        for row in _form_rows(read, lines):
            code, _ = code_of(lines[_head(read, row).first - 1:_head(read, row).last])
            assert form_by_key(row.form).write(row.values) == code, doc.key
            assert _probe_shape_equal(read, lines, row), doc.key
            checked += 1
    assert checked >= 15

    game = 0
    positions = frozenset(
        load_config(GamePaths.for_game(ROOT / "game")).config.stage.positions.keys())
    for path in sorted((ROOT / "game" / "script").rglob("*.vns")):
        text = path.read_text(encoding="utf-8")
        all_lines = text.split("\n")
        for _, first, last in chunks(text):
            chunk = "\n".join(all_lines[first - 1:last]) + "\n"
            read = parse_chunk("script/g.vns", chunk, positions=positions)
            assert read is not None and read.error is None, (path, first)
            lines = chunk.split("\n")[:-1]
            for row in _form_rows(read, lines, positions):
                head = _head(read, row)
                code, _ = code_of(lines[head.first - 1:head.last])
                written = form_by_key(row.form).write(row.values)
                if head.first == head.last:
                    assert forms._collapse(written) == forms._collapse(code), (path, code)
                assert _probe_shape_equal(read, lines, row, positions), (path, code)
                game += 1
    assert game >= 20

    say = form_by_key("say")
    for text in ['She said "hi".', "C:\\lanterns\\", "two\nlines", "赤い提灯", "🏮", "مرحبا",
                 'all \\ " \n of them']:
        values = {"speaker": "hana", "look": "", "text": text}
        read, lines = _inline(say.write(values))
        assert rows(read, lines)[0].values == values, text
    assert quote('a"b\\c\nd') == '"a\\"b\\\\c\\nd"'
    assert code_of(['    hana "a # b"  # note']) == ('hana "a # b"', "  # note")


def test_form_registry_complete(monkeypatch):
    """AC-F46-10."""
    assert missing_forms() == []
    for doc in all_docs():
        if doc.insert:
            assert form_for_doc(doc) is not None or doc.key in forms.TEXT_ONLY, doc.key
    monkeypatch.setattr(statement_docs, "STATEMENT_WORDS",
                        statement_docs.STATEMENT_WORDS | {"zzword"})
    with scoped_registry():
        register_doc(StatementDoc("zzword", "Test word", "Logic", "zzword", "A test word.",
                                  "zzword", None, "F46"))
        assert missing_forms() == ["zzword"]
    assert missing_forms() == []


def test_v1_forms():
    """AC-F46-14."""
    table = [
        ("say", {"speaker": "hana", "look": "happy", "text": "You came!"},
         'hana happy "You came!"', "Say  hana (happy): You came!"),
        ("say", {"speaker": "", "look": "", "text": "The lanterns were lit."},
         '"The lanterns were lit."', "Narration  The lanterns were lit."),
        ("show", {"character": "hana", "look": "happy", "position": "left",
                  "transition": "dissolve", "seconds": ""},
         "show hana happy at left with dissolve", "Show character  hana happy · left · dissolve"),
        ("hide", {"character": "hana", "transition": "", "seconds": ""}, "hide hana",
         "Hide character  hana"),
        ("scene", {"image": "bg river", "transition": "dissolve", "seconds": ""},
         "scene bg river with dissolve", "Background  bg river · dissolve"),
        ("music", {"action": "play", "file": "bgm/fest.ogg", "fade": "2.0"},
         'play music "bgm/fest.ogg" fadein 2.0', "Music  bgm/fest.ogg · fade in 2 s"),
        ("music", {"action": "stop", "file": "", "fade": ""}, "stop music", "Stop music"),
        ("sound", {"file": "sfx/bell.ogg"}, 'play sound "sfx/bell.ogg"', "Sound  sfx/bell.ogg"),
        ("jump", {"scene": "river"}, "jump river", "Go to scene  river"),
        ("call", {"scene": "stall"}, "call stall", "Visit scene  stall"),
        ("return", {}, "return", "Return"),
        ("pause", {"seconds": "1.0"}, "pause 1.0", "Wait  1 s"),
    ]
    read, lines = _inline(*(line for _, _, line, _ in table))
    got = rows(read, lines)
    for (key, values, line, text), row in zip(table, got):
        form = form_by_key(key)
        assert form.write(values) == line
        word = form.row_word(values)
        assert (f"{word}  {form.summary(values)}" if form.summary(values) else word) == text
        assert (row.form, row.values, row.text) == (key, values, text), line

    kinds = {(form.key, field.key): field.name_kind for form in forms.FORMS
             for field in form.fields if field.kind in ("name", "scene")}
    assert kinds == {
        ("say", "speaker"): "character", ("show", "character"): "sprite",
        ("show", "position"): "position", ("show", "transition"): "transition",
        ("hide", "character"): "sprite", ("hide", "transition"): "transition",
        ("scene", "image"): "image", ("scene", "transition"): "transition",
        ("music", "file"): "audio", ("sound", "file"): "audio",
        ("jump", "scene"): "label", ("call", "scene"): "label", ("points", "meter"): "meter"}


STALL_VOICE = """label stall:
    menu:
        voice "voice/q.ogg"
        hana "Which one?"
        "Buy the red one" if coins>0:
            $ coins = max(0, coins - 1)
            jump river
        # pick one
        "Just look":
            $ pass
    "You walk past the stall."
    jump river
"""


def _with(values: ChoiceValues, **changes) -> ChoiceValues:
    return replace(values, **changes)


def test_choice_form():
    """AC-F46-15."""
    read, lines = _scene(CH2, "stall")
    old = read_choice(read, 0)
    buy, look = old.choices
    assert (old.question, old.speaker) == ("", "")
    assert buy == ChoiceItem("Buy the red one", "coins > 0", "river", False, 0)
    assert look == ChoiceItem("Just look", "", None, False, 1)
    assert forms.choice_summary(look) == "continues here"

    stay, stay_lines = _scene(CH2.replace("            $ pass", '            "You stay."'), "stall")
    assert read_choice(stay, 0).choices[1].in_text
    assert forms.choice_summary(read_choice(stay, 0).choices[1]) == "(lines in the text)"

    ask = ChoiceItem("Ask the price", goes="festival")
    table = [
        (_with(old, choices=(buy, replace(look, goes="festival"))),
         [Patch(7, 7, ("            jump festival",))]),
        (_with(old, speaker="hana", question="Which one?"),
         [Patch(3, 2, ('        hana "Which one?"',))]),
        (_with(old, choices=(buy, look, ask)),
         [Patch(8, 7, ('        "Ask the price":', "            jump festival"))]),
        (_with(old, choices=(buy,)), [Patch(6, 7, ())]),
        (_with(old, choices=(look, buy)),
         [Patch(3, 5, tuple(lines[5:7])), Patch(6, 7, tuple(lines[2:5]))]),
        (old, []),
    ]
    for new, want in table:
        assert choice_patches(read, 0, lines, new) == want, new

    # The comment between the choices, the voice line and ``coins>0`` survive every change.
    read, lines = _scene(STALL_VOICE, "stall")
    old = read_choice(read, 0)
    buy, look = old.choices
    assert (old.speaker, old.question, buy.condition) == ("hana", "Which one?", "coins>0")
    for new in (_with(old, choices=(buy, replace(look, goes="festival"))),
                _with(old, speaker="", question="Pick one."),
                _with(old, speaker="", question=""),
                _with(old, choices=(buy, look, ask)), _with(old, choices=(buy,)),
                _with(old, choices=(look, buy)), _with(old, choices=(ask, buy, look))):
        after = _apply(lines, choice_patches(read, 0, lines, new))
        text = "\n".join(after) + "\n"
        assert "        # pick one" in after and '        voice "voice/q.ogg"' in after, new
        assert '"Buy the red one" if coins>0:' in text, new
        again = parse_chunk("script/t.vns", text)
        assert again.error is None, (new, text)
        assert read_choice(again, 0).choices == tuple(
            replace(item, old=n) for n, item in enumerate(new.choices)), new

    many = tuple(ChoiceItem(f"C{n}", goes="river") for n in range(7))
    assert choice_patches(read, 0, lines, _with(old, choices=many)) == CHOICE_LIMIT_TEXT
    assert CHOICE_LIMIT_TEXT == "A choice can have at most 6 options."


def test_should_forms():
    """AC-F46-19."""
    set_form, points, if_form = form_by_key("set"), form_by_key("points"), form_by_key("if")
    sets = [{"name": "coins", "op": "+=", "value": "1"},
            {"name": "name", "op": "=", "value": '"Mia"'},
            {"name": "met", "op": "=", "value": "True"}]
    meter = {"meter": "daichi", "op": "+=", "amount": "1"}
    heads = [{"keyword": "if", "condition": "coins>=2"},
             {"keyword": "elif", "condition": 'name == "Mia"'},
             {"keyword": "else", "condition": ""}]
    assert [set_form.write(v) for v in sets] == ["$ coins += 1", '$ name = "Mia"', "$ met = True"]
    assert points.write(meter) == "points daichi += 1"
    assert [if_form.write(v) for v in heads] == [
        "if coins>=2:", 'elif name == "Mia":', "else:"]

    body = [set_form.write(v) for v in sets] + [points.write(meter),
                                                "$ coins = max(0, coins - 1)"]
    body += [if_form.write(heads[0]), "    $ pass", if_form.write(heads[1]), "    $ pass",
             if_form.write(heads[2]), "    $ pass"]
    read, lines = _inline(*body)
    got = [row for row in rows(read, lines) if row.kind != "end" and row.word != "(nothing)"]
    assert [(row.form, row.values) for row in got] == (
        [("set", v) for v in sets] + [("points", meter), (None, None)]
        + [("if", v) for v in heads])
    assert [row.text for row in got[-3:]] == ["If  coins is at least 2", "Else if  name is Mia",
                                              "Else"]
    for row in got:
        if row.form is not None:
            code, _ = code_of(lines[_head(read, row).first - 1:_head(read, row).last])
            assert form_by_key(row.form).write(row.values) == code
            assert _probe_shape_equal(read, lines, row)

    # A choice's "Only show when".
    read, lines = _scene(CH2, "stall")
    old = read_choice(read, 0)
    new = _with(old, choices=(old.choices[0], replace(old.choices[1], condition="coins > 5")))
    assert choice_patches(read, 0, lines, new) == [
        Patch(6, 6, ('        "Just look" if coins > 5:',))]


# --- F47 P1-H: the Ending form ------------------------------------------------------------------

def test_ac_f47_23_ending_form_reads_and_writes_every_shape():
    """AC-F47-23: every ``ending <name> ["heading"] "title" [seconds] [with ...]`` shape reads
    into the form and writes back as written; shapes it can't hold stay Script rows."""
    ending = form_by_key("ending")
    doc = next(d for d in all_docs() if d.key == "ending")
    assert form_for_doc(doc) is ending and "ending" not in forms.TEXT_ONLY
    assert ending in forms.all_forms() and ending not in forms.FORMS     # F46's tuple kept
    assert [f.key for f in ending.fields] == ["name", "heading", "title", "hold",
                                              "transition", "seconds"]
    blank = {"heading": "", "hold": "", "transition": "", "seconds": ""}
    table = [
        ('ending good "The Lantern Festival"', {"name": "good", "title": "The Lantern Festival"},
         "Ending  good · The Lantern Festival"),
        ('ending good "Good End" "The Lantern Festival"',
         {"name": "good", "heading": "Good End", "title": "The Lantern Festival"},
         "Ending  good · Good End: The Lantern Festival"),
        ('ending good "T" 5', {"name": "good", "title": "T", "hold": "5"},
         "Ending  good · T · 5 s"),
        ('ending good "H" "T" 0', {"name": "good", "heading": "H", "title": "T", "hold": "0"},
         "Ending  good · H: T · no card"),
        ('ending good "T" with dissolve', {"name": "good", "title": "T",
                                           "transition": "dissolve"},
         "Ending  good · T · dissolve"),
        ('ending good "H" "T" 2.5 with fade 1.5',
         {"name": "good", "heading": "H", "title": "T", "hold": "2.5", "transition": "fade",
          "seconds": "1.5"}, "Ending  good · H: T · 2.5 s · fade 1.5 s"),
        ('ending good "Say \\"hi\\" {{wave}"', {"name": "good", "title": 'Say "hi" {wave}'},
         'Ending  good · Say "hi" {wave}'),
    ]
    for code, values, text in table:
        want = {**blank, **values}
        read, lines = _inline(code)
        row = rows(read, lines)[0]
        assert (row.form, row.values, row.text) == ("ending", want, text), code
        assert ending.write(want) == code
        assert _probe_shape_equal(read, lines, row), code
    # Extra spaces are only spacing (TR-F46-01); a colour `with` the form can't write stays a
    # Script row.
    read, lines = _inline('ending  good "T"   5')
    assert rows(read, lines)[0].values == {**blank, "name": "good", "title": "T", "hold": "5"}
    read, lines = _inline('ending good "T" with fade 0.4 "#ffe08a"')
    assert rows(read, lines)[0].form is None
    # Insert writes one line at the row's indent.
    assert forms.insert_lines(ending, {**blank, "name": "next_year", "title": "Next Year"},
                              "    ", "    ") == ['    ending next_year "Next Year"']

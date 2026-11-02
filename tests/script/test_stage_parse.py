"""F04 step 2 (``04-technical.md`` §6.1, §6.3; ``02-script.md`` §3.2–3.8, §5.1): the stage
statements, E119 on dialogue lines, E133, ``Program.images``, ``LoadOptions.position_names``,
and the word re-exports. AC: AC-F04-38 (its rows are the ``feature = "F04"`` rows of
``tests/fixtures/F02/messages/cases.toml``, run here as well as by ``test_messages.py``)."""

from types import MappingProxyType

import pytest

from engine.core import constants
from engine.core.constants import BUILTIN_POSITIONS
from engine.script import words
from engine.script.checks import character_tag
from engine.script.identity import statement_hash
from engine.script.loader import LoadOptions, load_story
from engine.script.nodes import Define, PyCode, Say, ScriptFile
from engine.script.effects import WithClause
from engine.script.stage import At, Hide, ImageDecl, Scene, Show
from tests.script import message_cases
from tests.script.helpers import parse_text, template_s

# The load rows (AC-F04-38). Launch rows (AC-F04-39) run in tests/runtime (E135:
# test_stage_burst.py; W10–W16 with step 6).
F04_CASES = [case for case in message_cases.load_cases()
             if case.feature == "F04" and case.time == "load"]


# --- AC-F04-38: the load error table -------------------------------------------------------------

def test_every_ac_f04_38_row_is_a_case():
    assert {case.ac for case in F04_CASES} == {"AC-F04-38"}
    codes = {case.code for case in F04_CASES}
    assert codes == {"-", "E110", "E111", "E112", "E113", "E114", "E115", "E116", "E117",
                     "E118", "E119", "E120", "E121", "E122", "E123", "E124", "E125", "E126",
                     "E127", "E130", "E131", "E132", "E133"}
    assert all(case.runnable and case.needs == "load" for case in F04_CASES)


@pytest.mark.parametrize("case", F04_CASES, ids=lambda case: case.id)
def test_ac_f04_38(case):
    message_cases.check_case(case, message_cases.run_case(case))


# --- Nodes ---------------------------------------------------------------------------------------

def _load(game, *, S=None, T=None, positions=("stall_spot",)):
    paths = game({"main.vns": template_s(S=S, T=T)})
    names = [*BUILTIN_POSITIONS, *positions]
    return load_story(paths, LoadOptions(position_names=names))


def _line6(result):
    assert result.errors == (), [e.format() for e in result.errors]
    return result.program.labels["start"].block[2]


_PLACE = dict(file=ScriptFile("script/main.vns", "main.vns", 0), line=6, end_line=6, column=5)


def _node(kind, **fields):
    return kind(**_PLACE, **fields)


@pytest.mark.parametrize("row,expected", [
    ("show hana", _node(Show, image="hana")),
    ("show hana happy at left as h2 layer 3 zoom 1.5 flip on with dissolve",
     _node(Show, image="hana happy", tag="h2", at=At(name="left"), layer=3, zoom=1.5,
           flip=True, with_clause=WithClause("dissolve", None, None, 6, 60))),
    ("show hana at -1280 2560", _node(Show, image="hana", at=At(x=-1280, y=2560))),
    ("show hana at 400", _node(Show, image="hana", at=At(x=400))),
    ("show hana at 2560.0 0.5", _node(Show, image="hana", at=At(x=2560.0, y=0.5))),
    ("show hana at stall_spot", _node(Show, image="hana", at=At(name="stall_spot"))),
    ("show witness behind desk", _node(Show, image="witness", behind="desk")),
    ("show hana layer -100 zoom 4 flip off",
     _node(Show, image="hana", layer=-100, zoom=4.0, flip=False)),
    ("show a b c d e", _node(Show, image="a b c d e")),
    ("show 2b", _node(Show, image="2b")),
    ("show hana with fade 0.5",                     # F09: arguments parsed at load
     _node(Show, image="hana", with_clause=WithClause("fade", 0.5, None, 6, 15))),
    ("scene", _node(Scene, image=None)),
    ("scene bg bridge with dissolve",
     _node(Scene, image="bg bridge", with_clause=WithClause("dissolve", None, None, 6, 21))),
    ("hide hana", _node(Hide, tag="hana")),
    ("hide hana with fade",
     _node(Hide, tag="hana", with_clause=WithClause("fade", None, None, 6, 15))),
])
def test_stage_nodes(game, row, expected):
    node = _line6(_load(game, S=row))
    assert type(node) is type(expected)
    for name in type(expected).__dataclass_fields__:
        if name in ("sid", "label", "path"):
            continue
        assert getattr(node, name) == getattr(expected, name), name


def test_number_types_are_as_written(game):
    node = _line6(_load(game, S="show hana at 400 680.0 zoom 2"))
    assert type(node.at.x) is int and type(node.at.y) is float
    assert type(node.zoom) is float and type(node.layer) is type(None)


def test_identity_keys_leave_out_the_modifiers():
    assert _node(Show, image="hana happy", tag="h2", layer=3).identity_key() == \
        ("show", "hana happy", "h2")
    assert _node(Show, image="hana").identity_key() == ("show", "hana", "")
    assert _node(Scene, image=None).identity_key() == ("scene", "")
    assert _node(Hide, tag="hana", with_clause=WithClause("x", 1.0, None, 1, 1)).identity_key() == \
        ("hide", "hana")


def test_sids_and_lookups(game):
    result = _load(game, S="show hana at left", T='image bg dusk = "#2b2140"')
    program = result.program
    node = program.labels["start"].block[2]
    assert node.sid == "start/" + statement_hash(("show", "hana", ""))
    assert program.get(node.sid) is node
    assert program.get("image:bg dusk") is None


# --- image and Program.images --------------------------------------------------------------------

def test_program_images_in_reading_order(game):
    paths = game({"main.vns": template_s(T='image bg dusk = "#2B2140"⏎include "b.vns"⏎'
                                           'image hana festival = "art/Hana.WEBP"'),
                  "b.vns": 'image black = "#101010"\n'})
    result = load_story(paths)
    assert result.errors == ()
    images = result.program.images
    assert isinstance(images, MappingProxyType)
    assert list(images) == ["bg dusk", "hana festival", "black"]
    dusk = images["bg dusk"]
    assert isinstance(dusk, ImageDecl) and dusk.color == (0x2B, 0x21, 0x40) and dusk.ref is None
    assert dusk.sid == "image:bg dusk" and dusk.line == 8
    assert images["hana festival"].ref == "art/Hana.WEBP"
    assert images["hana festival"].color is None
    assert images["black"].file.ref == "script/b.vns"


def test_program_images_default_is_empty(game):
    program = _load(game).program
    assert dict(program.images) == {}


def test_e133_names_the_first_place_once_per_name(game):
    paths = game({"main.vns": template_s(T='image bg dusk = "#2b2140"⏎include "b.vns"'),
                  "b.vns": 'image bg dusk = "#000000"\nimage bg dusk = "#111111"\n'})
    result = load_story(paths)
    assert [(e.code, e.file, e.line) for e in result.errors] == [("E133", "script/b.vns", 1)]
    assert result.errors[0].message == ('there is already an image "bg dusk" declared in '
                                        "script/main.vns, line 8. Remove or rename one.")


@pytest.mark.parametrize("row,code", [
    ('image bg x = "art/x.png" "y"', "E131"),
    ('image = "#000000"', "E131"),
    ('image bg x =', "E131"),
    ('image bg x = art/x.png', "E131"),
    ('image bg x = "/art/x.png"', "E132"),
    ('image bg x = "art\\\\x.png"', "E132"),
    ('image bg x = "art/x"', "E132"),
    ('image bg x = "#12345g"', "E132"),
    ('image bg-x = "#123456"', "E127"),
    ('image bg call = "#123456"', "E127"),
])
def test_image_declaration_errors(game, row, code):
    result = _load(game, T=row)
    assert [(e.code, e.line) for e in result.errors] == [(code, 8)]


def test_e132_other_reasons_use_f01s_text(game):
    result = _load(game, T='image bg x = "art/x.png."')
    assert result.errors[0].message == ('can\'t use "art/x.png.": file and folder names can\'t '
                                        "end with a dot or a space.")


# --- More load errors (drafted texts the table leaves open, F04 06 G4) ---------------------------

@pytest.mark.parametrize("row,code,message", [
    ("show hana as h2 x", "E110", 'this line has "x" left over after as h2. as takes one tag.'),
    ("show hana layer 2 3", "E110",
     'this line has "3" left over after layer 2. layer takes one number.'),
    ("show hana zoom 2 3", "E110",
     'this line has "3" left over after zoom 2. zoom takes one number.'),
    ("show hana flip on off", "E110",
     'this line has "off" left over after flip on. flip takes on or off.'),
    ("show hana behind desk x", "E110",
     'this line has "x" left over after behind desk. behind takes one tag.'),
    ("show hana at 400 left", "E110", 'this line has "left" left over after at 400. at takes '
                                       "one position name, or one or two numbers."),
    ("scene bg:", "E110", "scene doesn't start a block. Remove the :."),
    ("hide hana:", "E110", "hide doesn't start a block. Remove the :."),
    ("scene bg with fade at left", "E111", "scene doesn't take at, because a background "
                                           "always fills the screen. To place a picture, use "
                                           "show."),
    ("hide with fade", "E112", "hide needs the tag of a sprite, e.g. hide hana."),
    ("show hana zoom", "E113", "zoom needs a number after it, e.g. zoom 1.5."),
    ("show hana at zoom 2", "E113", "at needs a position after it, e.g. at left."),
    ("show hana with at left", "E113", "with needs a transition after it, e.g. with dissolve."),
    ("hide hana zoom 2", "E116", "hide doesn't take zoom. To change a sprite, use show."),
    ("hide hana happy with fade", "E116",
     "hide takes only the tag: write hide hana, not hide hana happy."),
    ("scene bg/river_night.png", "E117", '"bg/river_night.png" is a file, not an image '
                                         "name. Write the name made from it: scene bg "
                                         "river_night."),
    ("show images/hana/happy.png", "E117", '"images/hana/happy.png" is a file, not an image '
                                           "name. Write the name made from it: show hana "
                                           "happy."),
    ('scene "bg bridge"', "E117", "image names aren't written in quotes. Write scene bg "
                                  "bridge."),
    ("show hana layer ten", "E123", 'layer takes a whole number from -100 to 100, e.g. '
                                    'layer 10, but this has "ten".'),
    ("show hana zoom big", "E124", 'zoom takes a number from 0.25 to 4, e.g. zoom 1.5 (1 is '
                                   'normal size), but this has "big".'),
    ("show student as call", "E127", '"call" is a statement word, so it can\'t be a tag.'),
    ("show student as Zoom", "E127", '"Zoom" is a word show uses, so it can\'t be a tag.'),
    ("show student as st-b", "E127", '"st-b" can\'t be a tag. Tags use letters, digits, and '
                                     "_, e.g. st_b."),
    ("hide hana-x", "E127", '"hana-x" can\'t be a tag. Tags use letters, digits, and _, '
                            "e.g. hana_x."),
    ("show hana At left", "E127", '"At" is a statement word, so it can\'t be part of an '
                                  "image name."),
])
def test_drafted_load_errors(game, row, code, message):
    result = _load(game, S=row)
    assert [(e.code, e.line, e.message) for e in result.errors] == [(code, 6, message)]


def test_position_names_come_from_the_load_options(game):
    assert _line6(_load(game, S="show hana at spot", positions=("spot",))).at == At(name="spot")
    result = _load(game, S="show hana at stall_spot", positions=())
    assert [e.code for e in result.errors] == ["E120"]
    assert LoadOptions().position_names == frozenset(BUILTIN_POSITIONS)
    assert LoadOptions(position_names=["a", "b"]).position_names == frozenset({"a", "b"})


# --- E119 (row 5b of SR-F02-41) and the speaker's tag (F04 07 I-12, 06 G3) -------------------

E119_HEAD = '"{}" can\'t go on a dialogue line; only expression words can.'


@pytest.mark.parametrize("row,word,hint", [
    ('d at left "Hi."', "at", "Put show daichi at left on the line above."),
    ('hana pout layer 2 "Hi."', "layer", "Put show hana layer 2 on the line above."),
    ('hana zoom 2 flip on "Hi."', "zoom", "Put show hana zoom 2 flip on on the line above."),
    ('hana as h2 "Hi."', "as", "Put show hana as h2 on the line above."),
    ('hana behind stall "Hi."', "behind", "Put show hana behind stall on the line above."),
    ('hana with dissolve "Hi."', "with", "Put show hana with dissolve on the line above."),
    ('kaito at left "Hi."', "at", "Put at left on a show line above."),          # undefined
])
def test_e119_names_a_tag_only_when_certain(game, row, word, hint):
    result = _load(game, S=row)
    assert [(e.code, e.line, e.column) for e in result.errors] == [("E119", 6, None)]
    assert result.errors[0].message == f"{E119_HEAD.format(word)} {hint}"


@pytest.mark.parametrize("value,tag", [
    ('Character("Hana")', "hana"),
    ('Character("Daichi", image_tag="daichi")', "daichi"),
    ('Character("Daichi", color="#fff", image_tag="dai")', "dai"),
    ('Character("Daichi", image_tag="daichi grin")', None),
    ('Character("Daichi", image_tag=5)', None),
    ('Character("Daichi", **opts)', None),
    ('make_character("Daichi")', None),
    ('"Daichi"', None),
])
def test_character_tag(value, tag):
    define = Define(file=ScriptFile("script/main.vns", "main.vns", 0), line=1, end_line=1,
                    column=1, name="hana",
                    value=PyCode(source=value, line=1, column=1, mode="eval"))
    assert character_tag(define) == tag
    assert character_tag(None) is None


def test_e119_without_the_whole_game_checks_names_no_tag():
    parsed = parse_text(template_s(S='hana at left "Hi."'))
    assert parsed.errors[0].message == f"{E119_HEAD.format('at')} Put at left on a show line above."


@pytest.mark.parametrize("row", ['layer "Hi."', 'zoom "Hi."', 'flip "Hi."'])
def test_stage_words_stay_speakers(game, row):
    """F04 07 I-4: ``layer``, ``zoom``, ``flip`` are valid speaker and define names."""
    word = row.split()[0]
    paths = game({"main.vns": template_s(S=row, replace={1: f'define {word} = Character("X")'})})
    result = load_story(paths)
    assert result.errors == ()
    say = result.program.labels["start"].block[2]
    assert isinstance(say, Say) and say.speaker == word


def test_expression_words_still_load(game):
    say = _line6(_load(game, S='hana pout "You\'re late!"'))
    assert isinstance(say, Say) and say.attributes == ("pout",)


# --- Words (F04 07 I-4, I-5) --------------------------------------------------------------------

def test_words_reexports_core_sets():
    assert words.STATEMENT_WORDS is constants.STATEMENT_WORDS
    assert words.STAGE_WORDS is constants.STAGE_WORDS
    assert words.MODIFIER_WORDS == frozenset({"at", "as", "behind"})
    assert words.SHOW_MODIFIER_WORDS == frozenset(
        {"at", "as", "behind", "with", "layer", "zoom", "flip"})


@pytest.mark.parametrize("word,ok", [
    ("hana", True), ("2b", True), ("hana_happy", True), ("ｈａｎａ", True), ("é", True),
    ("zoom", False), ("Zoom", False), ("call", False), ("SCENE", False), ("hana-happy", False),
    ("a.b", False), ("", False), ("a b", False),
])
def test_is_image_word(word, ok):
    assert words.is_image_word(word) is ok

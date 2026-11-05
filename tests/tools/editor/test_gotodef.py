"""Go to definition (2026-11-04): what the name under the cursor is, in the author's words,
and where it is made (``gotodef.target_at``)."""

from engine.tools.editor.checker import NameEntry
from engine.tools.editor.gotodef import NOTHING, Target, target_at

NAMES = {
    "label": (NameEntry("start", "script/main.vns", 4), NameEntry("market", "script/b.vns", 9)),
    "character": (NameEntry("amara", "script/database.vns", 8),),
    "variable": (("sent_lantern", "script/database.vns", 12), ("persistent.seen", "x.vns", 2)),
    "transition": (NameEntry("slowfade", "script/fx.vns", 3), NameEntry("fade")),
    "position": (NameEntry("far_left", "script/fx.vns", 5),),
    "image": (NameEntry("bg dawn", "script/fx.vns", 7), NameEntry("amara happy")),
    "audio": (NameEntry("music/walk.ogg"),),
}
REFS = {"amara happy": "images/amara/happy.png", "amara sad": "images/amara/sad.png",
        "bg river": "images/bg/river.png"}


def at(line: str, word: str, *, nth: int = 0, here=None) -> Target | None:
    column = -1
    for _ in range(nth + 1):
        column = line.index(word, column + 1)
    return target_at(line, column + 1, NAMES, REFS, here=here)


def test_names_go_to_their_line_in_words_the_author_knows():
    assert at("    jump market", "market") == Target("Go to scene market", "script/b.vns", 9)
    assert at("    call start", "start") == Target("Go to scene start", "script/main.vns", 4)
    assert at('    amara "Hi."', "amara") == Target("Go to character amara",
                                                     "script/database.vns", 8)
    assert at("    if sent_lantern:", "sent_lantern").text == "Go to variable sent_lantern"
    assert at("    $ persistent.seen = True", "persistent").line == 2
    assert at('    "Go" if sent_lantern:', "sent_lantern").ref == "script/database.vns"


def test_pictures_and_modifiers_on_stage_lines():
    show = "    show amara happy at far_left with slowfade"
    # A picture without an ``image`` line opens its file in the File preview.
    assert at(show, "happy") == at(show, "amara") == Target(
        "Show picture amara happy", "images/amara/happy.png")
    assert at(show, "far_left") == Target("Go to position far_left", "script/fx.vns", 5)
    assert at(show, "slowfade") == Target("Go to transition slowfade", "script/fx.vns", 3)
    assert at(show, "with") is None
    assert at("    scene bg dawn", "dawn") == Target("Go to picture bg dawn", "script/fx.vns", 7)
    assert at("    scene bg river with fade", "river").ref == "images/bg/river.png"
    assert at("    scene bg river with fade", "fade") is None      # built in: nowhere to go
    assert at("    hide amara", "amara") == Target("Show picture amara",
                                                    "images/amara/happy.png")
    # ``amara sad "…"``: the attribute is her picture; her name is the character.
    assert at('    amara sad "Oh."', "sad").ref == "images/amara/sad.png"
    assert at('    amara sad "Oh."', "amara").text == "Go to character amara"


def test_sounds_unknown_names_notes_and_the_same_line():
    assert at('    play music "music/walk.ogg"', "walk") == Target(
        "Show sound music/walk.ogg", "audio/music/walk.ogg")
    assert at('    play music "music/none.ogg"', "none") is None
    assert at('    amara "jump market"', "market") is None         # words in a line of text
    assert at("    # jump market", "market") is None
    assert at("    jump nowhere", "nowhere") is None
    assert at("label market:", "market", here=("script/b.vns", 9)) is None
    assert at("    ", " ") is None
    assert NOTHING == "Go to definition"

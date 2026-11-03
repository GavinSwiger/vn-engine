"""F35 S2: the music room's script side (``script/musicroom.py``, ``program.py``, ``checks.py``):
AC-F35-01 (the parsed forms; ``track``, ``open`` and ``until`` stay names, while ``file`` has been
F31's statement word since before F35; every E336/E338 text is a row of
``tests/fixtures/F02/messages/cases.toml``) and AC-F35-02 (E337's over-200 form, W220's
did-you-mean, W221 only for the default rule and only in dev; E337's other forms are rows)."""

from engine.core.paths import GamePaths
from engine.script import LoadOptions, load_story
from tests.runtime.menu_story import write_game

TRACKS = ('lock track main_theme "Main Theme" file "music/main_theme.ogg" open\n'
          'include "db.vns"\n'
          'lock track credits "{{Paper} Lanterns" file "music/credits.ogg" until true, good, true\n')
DB = 'lock  track festival   "Festival Night"  file  "music/festival.ogg"\n'


def test_ac01_track_declarations_and_names_still_free(tmp_path):
    story = (TRACKS + "default track = 1\ndefault until = 2\ndefault open = 3\n"
             "label start:\n    $ track += until + open\n"
             '    play music "music/festival.ogg"\n'
             '    "Track {var=track}."\n'
             "    if track > 3:\n        ending true \"True\"\n"
             '    ending good "Good"\n')
    root = tmp_path / "g"
    paths = write_game(root, story)
    (root / "script" / "db.vns").write_text(DB, encoding="utf-8")
    result = load_story(paths, LoadOptions(dev=False))
    assert result.errors == (), [e.format() for e in result.errors]
    rows = [(t.name, t.title, t.file, t.open, t.until, t.sid, t.script, t.line)
            for t in result.program.tracks]
    assert rows == [                                      # reading order (includes after)
        ("main_theme", "Main Theme", "music/main_theme.ogg", True, (), "track:main_theme",
         "script/main.vns", 1),
        ("credits", "{Paper} Lanterns", "music/credits.ogg", False, ("true", "good"),
         "track:credits", "script/main.vns", 3),
        ("festival", "Festival Night", "music/festival.ogg", False, (), "track:festival",
         "script/db.vns", 1)]
    # runtime/musicroom.py reads the same values (its TrackDeclLike).
    from engine.runtime.musicroom import TrackIndex
    index = TrackIndex.build(result.program)
    assert [(t.name, t.rule) for t in index] == [
        ("main_theme", "open"), ("credits", "until"), ("festival", "heard")]


def test_ac02_whole_game_checks(tmp_path):
    many = "".join(f'lock track t{i} "T" file "music/t{i}.ogg" open\n' for i in range(201))
    result = load_story(write_game(tmp_path / "many", many + "label start:\n    return\n"),
                        LoadOptions(dev=False))
    assert [e.format() for e in result.errors] == [
        "this story has 201 music-room tracks; the engine allows 200."]
    fine = "".join(f'lock track t{i} "T" file "music/t{i}.ogg" open\n' for i in range(200))
    assert load_story(write_game(tmp_path / "fine", fine + "label start:\n    return\n"),
                      LoadOptions(dev=False)).errors == ()

    story = ('lock track heard "Heard" file "music/festval.ogg"\n'       # W220 (+ suggestion), W221
             'lock track played "Played" file "music/festival.ogg"\n'    # played: no warning
             'lock track queued "Queued" file "loop.ogg"\n'              # queued: no warning
             'lock track always "Always" file "music/none.ogg" open\n'   # W220 only, no W221
             'lock track later "Later" file "music/main_theme.ogg" until good\n'
             "label start:\n"
             '    play music "music/festival.ogg"\n'
             '    queue music "loop.ogg"\n'
             '    play sound "music/main_theme.ogg"\n'                   # a sound isn't heard
             '    ending good "Good"\n')
    root = tmp_path / "w"
    write_game(root, story)
    for ref in ("music/festival.ogg", "music/main_theme.ogg", "loop.ogg"):
        (root / "audio" / ref).parent.mkdir(parents=True, exist_ok=True)
        (root / "audio" / ref).write_bytes(b"")
    dev = load_story(GamePaths(root.resolve()), LoadOptions(dev=True))
    assert dev.errors == ()
    assert [(w.code, w.line, w.message) for w in dev.warnings if w.code in ("W220", "W221")] == [
        ("W220", 1, 'track heard plays "music/festval.ogg", but there is no such file in '
                    'audio/. Did you mean "music/festival.ogg"?'),
        ("W221", 1, 'track heard opens when the story plays "music/festval.ogg", but no play '
                    "music or queue music line plays it, so players never get it. Add open or "
                    "until, or play it in the story."),
        ("W220", 4, 'track always plays "music/none.ogg", but there is no such file in audio/.')]
    release = load_story(GamePaths(root.resolve()), LoadOptions(dev=False))
    assert release.errors == () and not [w for w in release.warnings
                                         if w.code in ("W220", "W221")]

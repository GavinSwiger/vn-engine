"""F43 translation keys (``01`` §5.1, §5.2; ``04`` §3): AC-F43-05, keys for every §5.1 Must
kind from a sample program and config (the shipped example, *Paper Lanterns*)."""

from pathlib import Path

import pytest

from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.script.loader import LoadOptions, load_story
from engine.script.translatekeys import (
    GAME_TITLE,
    SourceText,
    TextKind,
    choice_key,
    is_script_key,
    key_scene,
    source_texts,
    word_key,
)

GAME = Path(__file__).resolve().parents[2] / "game"


@pytest.fixture(scope="module")
def example():
    paths = GamePaths.for_game(GAME)
    config = load_config(paths).config
    options = LoadOptions(position_names=frozenset(config.stage.positions)
                          | {"left", "center", "right"}, style_names=frozenset(config.style))
    result = load_story(paths, options)
    assert result.program is not None and result.errors == ()
    return result.program, config


def _one(texts: tuple[SourceText, ...], key: str) -> SourceText:
    [found] = [t for t in texts if t.key == key]
    return found


def test_ac_f43_05_keys_for_every_must_kind(example):
    """AC-F43-05: lines (sids), questions (menu sid), choices (``<menu sid>#<key>``), names,
    words (with style/playthrough layers), titles and game texts; §5.2 order; keys unique;
    scene/who as rule 3 reads them."""
    program, config = example
    texts = source_texts(program, config)
    keys = [t.key for t in texts]
    assert len(keys) == len(set(keys))

    # Story lines: the Say sid, the original as written, the speaker's define name.
    say = next(s for s in program.iter_statements() if type(s).__name__ == "Say"
               and s.speaker == "daichi")
    row = _one(texts, say.sid)
    assert (row.kind, row.original, row.who, row.scene) == (
        TextKind.LINE, say.text, "daichi", say.label)
    assert row.ref == f"{say.file.ref}:{say.line}"
    # Questions and choices.
    menu = next(s for s in program.iter_statements() if type(s).__name__ == "Menu"
                and s.question is not None)
    question = _one(texts, menu.sid)
    assert (question.kind, question.original) == (TextKind.QUESTION, menu.question.text)
    for choice in menu.choices:
        row = _one(texts, choice_key(menu.sid, choice.key))
        assert (row.kind, row.original, row.scene) == (TextKind.CHOICE, choice.text, menu.label)
        assert row.key == f"{menu.sid}#{choice.key}"

    table = [   # (key, kind, original)
        ("name:daichi", TextKind.NAME, "Daichi"),
        ("word:new_game", TextKind.WORD, config.words.new_game),
        ("chapter:riverbank:heading", TextKind.TITLE, "Chapter 1"),
        ("chapter:riverbank:title", TextKind.TITLE, "Wishes on the Water"),
        ("ending:sad:heading", TextKind.TITLE, "Sad End"),
        ("ending:good:title", TextKind.TITLE, "The Lantern Festival"),
        ("tip:lanterns:title", TextKind.TITLE, "Paper Lanterns"),
        ("item:lantern:title", TextKind.TITLE, "Paper Lantern"),
        ("codex:category:Festival", TextKind.TITLE, "Festival"),
        ("track:lantern_walk", TextKind.TITLE, "Lantern Walk"),
        ("replay:bridge", TextKind.TITLE, "The Old Footbridge"),
        ("achievement:set_adrift:title", TextKind.TITLE, "Set Adrift"),
        ("achievement:set_adrift:description", TextKind.TITLE,
         "Send a paper lantern down the river."),
        ("value:???", TextKind.VALUE, "???"),            # default hana_name = "???"
        (GAME_TITLE, TextKind.GAME, config.game.title),
    ]
    for key, kind, original in table:
        row = _one(texts, key)
        assert (row.kind, row.original) == (kind, original), key
    assert any(k.startswith("route:") for k in keys)
    assert any(k.startswith("gallery:") for k in keys)
    assert any(k.startswith("flowchart:") for k in keys)
    tip = _one(texts, "tip:lanterns:1")                  # paragraph 1, plain text
    assert tip.kind is TextKind.TITLE and tip.original and "{" not in tip.original
    # name_from and empty Character names have no name key.
    assert "name:hana" not in keys and "name:thought" not in keys
    # Every [words] key, then the playthrough layer's own keys.
    from engine.core.config_schema import word_fields
    assert {word_key(k) for k, f in word_fields().items() if f.default} <= set(keys)  # money: ""
    for number, look in config.playthrough.items():
        for key in look.words:
            assert word_key(key, playthrough=number) in keys
    assert word_key("x", style="dark") == "word:x@dark"

    # §5.2 order: script texts first, then names/values, words, titles, game.
    rank = {TextKind.LINE: 0, TextKind.QUESTION: 0, TextKind.CHOICE: 0, TextKind.EFFECT: 0,
            TextKind.NAME: 1, TextKind.WORD: 2, TextKind.TITLE: 3, TextKind.GAME: 4}
    ranks = [rank[t.kind] for t in texts if t.kind is not TextKind.VALUE]
    assert ranks == sorted(ranks)
    assert keys.index(menu.sid) + 1 == keys.index(choice_key(menu.sid, menu.choices[0].key))
    # Scene and who as rule 3 groups them; script keys are the sids.
    for t in texts:
        assert key_scene(t.key) == t.scene, t.key
        assert is_script_key(t.key) == (t.kind in (TextKind.LINE, TextKind.QUESTION,
                                                   TextKind.CHOICE, TextKind.EFFECT)), t.key
        assert t.limit is None or len(t.original) <= t.limit, t.key
    # No config: script and titles only.
    bare = source_texts(program)
    assert not any(t.kind in (TextKind.WORD, TextKind.GAME) for t in bare)
    assert [t.key for t in bare if t.kind is TextKind.LINE] == [
        t.key for t in texts if t.kind is TextKind.LINE]

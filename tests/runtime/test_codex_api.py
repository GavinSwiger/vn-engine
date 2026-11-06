"""F21 step 2 — the codex API (``runtime/codex.py``): AC-F21-14 (``CodexIndex``, ``Codex``) and
the unit parts of AC-F21-11 (TR-F21-02: fresh lists) and AC-F21-12 (the ``codex`` value)."""

import pytest

from engine.core.paths import GamePaths
from engine.runtime.codex import (Codex, CodexIndex, CodexNoAttr, CodexNotStarted,
                                  CodexReadOnly, CodexReader, UnknownEntry, WrongKind, install)
from engine.runtime.state import EMPTY_ITEMS
from engine.runtime.values import freeze
from engine.script import load_story
from engine.script.codex import CodexCategory
from engine.script.loader import LoadOptions
from tests.runtime.codex_story import CA, launched, load_c, store_with
from tests.script.helpers import template_c


def _without_river_god(root):
    script = root / "script"
    script.mkdir(parents=True)
    text = template_c().replace('lock tip river_god "The River God" in "Legends"\n', "")
    (script / "main.vns").write_text(text, encoding="utf-8")
    result = load_story(GamePaths(root.resolve()), LoadOptions(dev=False))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def test_ac14_the_index_and_the_codex_api(tmp_path):
    program = load_c(tmp_path / "c")
    index = CodexIndex.build(program)
    assert [e.name for e in index.tips] == ["lanterns", "river_god"]
    assert [e.name for e in index.items] == ["red_lantern", "brass_key"]
    assert index.categories == (CodexCategory("tip", "Festival", None),
                                CodexCategory("tip", "Legends", None),
                                CodexCategory("item", "Things", None),
                                CodexCategory("item", None, "codex_items"))
    lanterns = index.get("lanterns")
    assert (lanterns.title, lanterns.category.text, len(lanterns.paragraphs), lanterns.sid,
            lanterns.file, lanterns.line) == ("Paper Lanterns", "Festival", 2,
                                              "codex:lanterns", "script/main.vns", 2)
    assert index.get("nope") is None and len(index) == 4
    assert [(index.has(n), index.is_tip(n), index.is_item(n))
            for n in ("lanterns", "brass_key", "nope", 3)] == [
        (True, True, False), (True, False, True), (False, False, False), (False, False, False)]
    assert index.suggest("lantern", "tip") == "lanterns"
    assert index.suggest("lantern", "item") is None

    store = store_with()
    interp = launched(program, store)
    codex: Codex = interp.codex
    assert codex.index.tips == index.tips
    assert [codex.give("brass_key"), codex.give("brass_key")] == [True, False]
    assert [codex.take("brass_key"), codex.take("brass_key")] == [True, False]
    assert [codex.unlock_tip("lanterns"), codex.unlock_tip("lanterns")] == [True, False]
    assert [codex.relock_tip("lanterns"), codex.relock_tip("lanterns")] == [True, False]
    assert interp._held == [CA("item", "brass_key"), CA("tip", "lanterns")]
    with pytest.raises(WrongKind):
        codex.give("lanterns")
    with pytest.raises(WrongKind):
        codex.unlock_tip("brass_key")
    with pytest.raises(UnknownEntry) as caught:
        codex.give("nope")
    assert caught.value.suggestion is None and caught.value.kind == "item"
    with pytest.raises(UnknownEntry) as caught:
        codex.give("brass_ky")
    assert caught.value.suggestion == "brass_key"
    codex.unlock_tip("lanterns")
    codex.give("red_lantern")
    assert [codex.has(n) for n in ("lanterns", "red_lantern", "river_god", "nope")] == [
        True, True, False, False]
    assert [codex.mark_read("lanterns"), codex.mark_read("lanterns")] == [True, False]
    assert codex.is_read("lanterns") and not codex.is_read("river_god")
    version = store.version
    assert codex.mark_read("nope") is False and store.version == version
    state = codex.state()
    assert codex.state() is state and state.held == ("red_lantern",)
    codex.give("brass_key")
    assert codex.state() is not state and codex.state().held == ("red_lantern", "brass_key")
    codex.new_game()
    assert codex.state() is EMPTY_ITEMS and codex.items() == ()
    tip, read = store._kinds["tip"], store._kinds["codex_read"]
    assert tip.revocable and tip.known == codex.index.is_tip
    assert not read.revocable and read.known == codex.index.has

    # F39: install again with a program that drops river_god (no ValueError).
    two = store_with(t=("lanterns", "river_god"))
    again = launched(program, two)
    assert again.codex.tips() == ("lanterns", "river_god")
    again.program = _without_river_god(tmp_path / "f")
    assert install(again).tips() == ("lanterns",)


def test_ac11_reads_are_fresh_lists(tmp_path):
    """TR-F21-02 (unit): for each state, every read is a new ``list`` that ``freeze``
    accepts, and changing it changes no later read."""
    program = load_c(tmp_path / "c")
    for t, items in (((), ()), (("lanterns",), ()), ((), ("brass_key", "red_lantern"))):
        interp = launched(program, store_with(t=t))
        for name in items:
            interp.codex.give(name)
        reader = interp.G["codex"]
        for attr in ("tips", "items"):
            first, second = getattr(reader, attr), getattr(reader, attr)
            assert type(first) is list and first is not second and first == second
            assert freeze(first) == first
            first.append("x")
            assert getattr(reader, attr) == second
        assert reader.tips == list(t) and reader.items == list(items)


def test_ac12_the_codex_value(tmp_path):
    reader = CodexReader()
    assert dir(reader) == ["count", "items", "tips"] and repr(reader) == "<codex>"
    for name in ("tips", "items", "zzz"):
        with pytest.raises(CodexNotStarted) as caught:
            getattr(reader, name)
        assert caught.value.code == "E256"
    assert "holds tips only" in str(CodexNotStarted("tips"))
    assert "holds items only" in str(CodexNotStarted("items"))
    interp = launched(load_c(tmp_path / "c"))
    reader = interp.G["codex"]
    assert type(reader) is CodexReader and isinstance(reader, CodexReader)
    assert not hasattr(reader, "zzz") and hasattr(reader, "tips")
    with pytest.raises(CodexNoAttr) as caught:
        reader.itmes  # noqa: B018
    assert caught.value.message == ('there is no codex.itmes. Did you mean "items"? codex has '
                                    "tips, items, and count.")
    with pytest.raises(CodexReadOnly) as caught:
        reader.items = []
    assert caught.value.message == "Python can't change codex.items. Use unlock item and lock item."
    with pytest.raises(CodexReadOnly):
        del reader.tips
    assert reader.items == []

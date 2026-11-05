"""What a connected agent learns and changes beyond the script (2026-11-04):
``settings_reference`` (every setting), ``engine_docs`` (the other guides), and
``propose_settings`` (config.toml by section and key, through Game settings' writer), applied
and undone on disk."""

import re

from engine.tools.assistant import edits, reference
from engine.tools.assistant.diskapply import ProposalStore
from engine.tools.assistant.edits import propose_settings, rebase, verify_file
from engine.tools.assistant.refs import ToolError
from engine.tools.assistant.tools import MODE_MCP, ToolBox
from tests.tools.assistant.assist_games import FakeRunner, disk
from tests.tools.f45_games import studio

import pytest


def _box(game):
    ws = disk(game, FakeRunner())
    return ToolBox(ws, MODE_MCP, writer=ProposalStore(ws)), ws


def test_settings_reference_sections_keys_and_search(tmp_path):
    game = studio(tmp_path)
    (game / "config.toml").write_text('[game]\ntitle = "My Game"\n[window]\nwidth = 1600\n',
                                      encoding="utf-8")
    box, _ws = _box(game)
    sections = box.call("settings_reference", {}).text
    assert "[window] (8 keys): the game window" in sections and "[theme.textbox]" in sections
    window = box.call("settings_reference", {"section": "window"}).text
    assert ("[window] width: the window's starting width in pixels. Accepts a whole number "
            "from 640 to 7680; default 1280; this game: 1600") in window
    found = box.call("settings_reference", {"search": "text speed"}).text
    assert "[textbox] cps: the text speed" in found
    assert 'default "#FFF4F8"' in box.call("settings_reference",
                                           {"search": "button fill color"}).text
    assert "No setting matches" in box.call("settings_reference", {"search": "zzqq"}).text
    assert "Sections:" in box.call("settings_reference", {"section": "nope"}).text


def test_engine_docs_lists_guides_topics_and_sections(tmp_path):
    box, _ws = _box(studio(tmp_path))
    guides = box.call("engine_docs", {}).text
    for name in reference.GUIDE_NAMES:
        assert f"{name}: " in guides
    topics = box.call("engine_docs", {"guide": "meta-files"}).text
    assert "4. Test it" in topics
    section = box.call("engine_docs", {"guide": "meta-files", "topic": "4. Test it"}).text
    assert section.startswith("4. Test it") or "Test it" in section.split("\n")[0]
    assert "Guides:" in box.call("engine_docs", {"guide": "nope"}).text
    assert box.call("engine_docs", {"topic": "x"}).is_error


def test_engine_guides_match_studios_help_menu():
    from engine.tools.editor.guides import GUIDES as MENU
    assert [file for _name, file, _about in reference.GUIDES] == [file for _t, file in MENU]


def test_propose_settings_refuses_what_game_settings_would(tmp_path):
    _box_, ws = _box(studio(tmp_path))
    for changes, text in (
            ([{"section": "window", "key": "width", "value": 99999}],
             "[window] width must be a whole number from 640 to 7680."),
            ([{"section": "window", "key": "nope", "value": 1}],
             "[window] nope isn't a config.toml setting."),
            ([{"section": "window", "key": "width"}], "value"),
            ([], edits.SETTINGS_SHAPE)):
        with pytest.raises(ToolError) as caught:
            propose_settings(ws, {"summary": "x", "changes": changes}, check=False)
        assert text in caught.value.text
    # propose_edit points at propose_settings for config.toml.
    with pytest.raises(ToolError) as caught:
        edits.propose(ws, {"summary": "x", "changes": [
            {"file": "config.toml", "old_text": "a", "new_text": "b"}]}, check=False)
    assert "propose_settings" in caught.value.text


def test_propose_apply_and_undo_settings_on_disk(tmp_path):
    game = studio(tmp_path)
    config = game / "config.toml"
    config.write_bytes(b'[game]\r\ntitle = "My Game"\r\n\r\n[window]\r\n# width = 1280\r\n')
    before = config.read_bytes()
    box, ws = _box(game)
    out = box.call("propose_settings", {"summary": "Wider, faster", "changes": [
        {"section": "window", "key": "width", "value": 1600},
        {"section": "textbox", "key": "cps", "value": 80}]}).text
    assert "+5 width = 1600" in out and "+8 cps = 80" in out and "-5 # width" in out
    found = re.search(r"id: (\S+)", out).group(1)
    assert "Wrote config.toml" in box.call("apply_edit", {"id": found}).text
    after = config.read_bytes()
    assert b"width = 1600\r\n" in after and b"[textbox]\r\ncps = 80" in after   # CRLF kept
    assert b"# width" not in after                      # the commented key became the key
    assert "Undid" in box.call("undo_apply", {}).text
    assert config.read_bytes() == before
    # A file changed after the proposal is never written over.
    proposal = propose_settings(ws, {"summary": "x", "changes": [
        {"section": "window", "key": "width", "value": 1600}]}, check=False)
    config.write_bytes(before + b"height = 900\r\n")
    assert rebase(proposal.files[0], config.read_text(encoding="utf-8")) is None
    assert not verify_file(proposal.files[0], "[window]\nwidth = 2\n")
    kept = box.writer.keep(proposal)
    assert "changed" in box.call("apply_edit", {"id": kept}).text.lower()
    assert b"width = 1600" not in config.read_bytes()

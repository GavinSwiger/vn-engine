"""F65 round 3 in Studio: Database ▸ Contacts (proposal I-09 "Studio contacts and devices"):
``lock contact`` read and written by the form, the messages under a contact (opened in the
phone-chat step editor), rename everywhere, Delete refused while a send line uses it, and
the live preview."""

from pathlib import Path

import pytest

from engine.tools.editor import contactmodel as cm
from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan, declrename, files
from engine.tools.editor import devicemodel as dm
from engine.tools.editor import minigamedata as mg
from engine.tools.editor.scriptedit import apply_lines

DB_REF = declplan.DATABASE_REF
MAIN = "script/main.vns"

STORY = {
    MAIN: 'include "database.vns"\n\nlabel start:\n    "Morning."\n'
          '    send hello from hana\n    send hello from hana on phone  # again\n'
          'label later:\n    send letter2 from hana\n    send hello from ren\n'
          '    if inbox.reply("hello") == "yes":\n        $ said = inbox.reply(\'hello\')\n'
          '    "hello"\n    $ later_reply = inbox.reply("hello_2")\n',
    DB_REF: 'lock contact hana "Hana" on pigeon image hana portrait\n'
            'lock contact ren "Ren"\n'
            'define hello = ["Hi there", {"me": "Hello!"}, {"time": "Day 2"}, {"Kai": "Hey"}]\n'
            'define letter2 = "One text."\n'
            'define hana_draft = ["Not sent yet."]\n'
            'define hana_name = "???"\n'
            'define other = ["Not hers."]\n'}


def test_contact_lines_read_and_write_back():
    found = {d.name: d for d in dec.scan({DB_REF: STORY[DB_REF]}) if d.kind == dec.CONTACT}
    assert found["hana"].values == {"title": "Hana", "device": "pigeon",
                                    "image": "hana portrait"}
    assert found["ren"].values == {"title": "Ren", "device": None, "image": None}
    for decl in found.values():
        assert dec.contact_line(decl.name, decl.values) == STORY[DB_REF].split(
            "\n")[decl.first - 1]
    odd = dec.scan({DB_REF: 'lock contact a "A" on fax\nlock contact b "B" image x on phone '
                            'on radio\nlock contact c "C" image a b on mind\n'})
    assert [(d.name, d.values) for d in odd] == [
        ("a", None), ("b", None),
        ("c", {"title": "C", "device": "mind", "image": "a b"})]
    assert dec.contact_line("d", {"title": "Dr {x}", "device": None, "image": None}) == \
        'lock contact d "Dr {{x}"'
    assert not dec.contact_ok({"title": "  two  spaces", "device": None, "image": None})
    assert not dec.contact_ok({"title": "x" * 41, "device": None, "image": None})
    assert dec.script_name("Hana Mori", set(), dec.CONTACT) == "hana_mori"
    assert dec.script_name("Hana", {"hana"}, dec.CONTACT) == "hana_2"
    # Contacts have names of their own: a character called hana doesn't take it.
    assert dec.taken_names(dec.scan({DB_REF: 'define hana = Character("Hana")'}),
                           dec.CONTACT) == frozenset()


def test_plan_new_edit_delete_contact():
    texts = {MAIN: 'include "database.vns"\nlabel start:\n    "Hi."\n',
             DB_REF: declplan.DATABASE_HEADER}
    plan = declplan.plan_new(dec.CONTACT, "hana", {"title": "Hana", "device": None,
                                                   "image": None}, texts)
    assert isinstance(plan, declplan.DeclPlan) and plan.plan.title == "Add contact hana"
    after = "\n".join(apply_lines(texts[DB_REF].split("\n"), plan.plan.files[0].edits))
    assert declplan.verify_decl(plan, texts)
    assert after.endswith('lock contact hana "Hana"')
    decl = dec.find(dec.scan({DB_REF: after}), dec.CONTACT, "hana")
    edit = declplan.plan_edit(decl, {**decl.values, "device": "letters",
                                     "image": "hana smile"}, {**texts, DB_REF: after})
    assert isinstance(edit, declplan.DeclPlan)
    assert edit.plan.files[0].edits[0].lines == (
        'lock contact hana "Hana" on letters image hana smile',)


def test_send_lines_entries_and_messages():
    sends = cm.send_lines(STORY)
    assert [(s.message, s.contact, s.device, s.scene, s.line) for s in sends] == [
        ("hello", "hana", None, "start", 5), ("hello", "hana", "phone", "start", 6),
        ("letter2", "hana", None, "later", 8), ("hello", "ren", None, "later", 9)]
    entries = cm.contact_entries(dec.scan(STORY), STORY, sends)
    assert [(e.name, e.shown, e.uses) for e in entries] == [("hana", "Hana", 3),
                                                            ("ren", "Ren", 1)]
    messages = cm.messages_of("hana", STORY, sends)
    assert [(m.name, len(m.sends)) for m in messages] == [
        ("hello", 2), ("letter2", 1), ("hana_draft", 0)]
    assert cm.first_text(messages[0].value) == "Hi there"
    assert cm.where_text(sends[2]) == "scene later, main.vns line 8"
    assert cm.refusal("Hana", sends[:3]).startswith(
        "Hana sends messages from 3 lines (scene start, main.vns line 5; ")
    assert cm.refusal("Ren", ()) is None
    # A message of one text opens in the step editor as one line from the contact.
    ds = cm.message_set(STORY, "letter2")
    assert ds.kind == mg.CHAT and ds.model == (mg.Step(mg.FROM_CONTACT, "One text."),)
    assert cm.message_set(STORY, "nope") is None
    assert cm.message_name("hana", "Letter 3", {"hana_letter_3"}) == "hana_letter_3_2"


def test_device_looks_and_preview():
    fantasy = {"theme.kit": "fantasy"}
    assert cm.look_choices(fantasy)[0] == (None, "Game default (Pigeon post, from the Fantasy kit)")
    assert cm.look_choices({})[0] == (None, "Game default (Phone, with no kit)")
    assert [v for v, _ in cm.look_choices({})[1:]] == list(dec.CONTACT_LOOKS)
    assert cm.arrives_text("pigeon", "Hana") == (
        "Arrives as: “A pigeon lands on the sill with a note from Hana.”")
    sends = cm.send_lines(STORY)
    messages = cm.messages_of("hana", STORY, sends)
    seen = cm.preview({}, "Hana", {"device": "pigeon"}, messages, sends)
    assert (seen.look, seen.letter, seen.lines) == ("pigeon", True,
                                                    (("them", "Hana", "One text."),))
    assert seen.caption == "Newest: letter2, sent in later"
    # The newest send of hello is "on phone": that look wins for the preview.
    only_hello = [m for m in messages if m.name == "hello"]
    seen = cm.preview({}, "Hana", {"device": "pigeon"}, only_hello, sends)
    assert seen.look == "phone" and not seen.letter
    assert seen.lines == (("them", "Hana", "Hi there"), ("me", "", "Hello!"),
                          ("time", "", "Day 2"), ("them", "Kai", "Hey"))
    empty = cm.preview(fantasy, "Ren", {"device": None}, [], sends)
    assert (empty.look, empty.lines, empty.caption) == ("pigeon", (), cm.NO_MESSAGES)


def test_default_look_is_the_games_device_and_says_where_it_comes_from():
    # As the game picks it (kits.device_look): the kit's device, else a phone; the name is
    # the one the game shows ([device.<look>] name wins).
    horror = {"theme.kit": "horror"}
    look = dm.default_look(horror)
    assert look == "mind" and cm.default_look(horror) == ("mind", "Horror")
    assert cm.look_of(horror, {"device": None}) == look
    named = {"theme.kit": "fantasy", "device.pigeon.name": "Rookery"}
    assert cm.default_text(named) == "Game default (Rookery, from the Fantasy kit)"
    assert cm.default_look({"theme.kit": "nope"}) == ("phone", None)


def test_preview_uses_the_devices_page_preview_of_the_look():
    sends = cm.send_lines(STORY)
    messages = cm.messages_of("hana", STORY, sends)
    seen = cm.preview({}, "Hana", {"device": "pigeon"}, messages, sends)
    want = dm.preview({}, "pigeon", "Hana", (("", "One text."),), day="")
    assert seen.device == want
    assert seen.device.signature == "— Hana" and seen.device.header == "Arrived by pigeon"
    assert seen.device.notice == "A pigeon lands on the sill with a note from Hana."
    hello = [m for m in messages if m.name == "hello"]
    seen = cm.preview({}, "Hana", {"device": "terminal"}, hello, sends)
    assert seen.device.look == "phone"                     # the newest send says on phone
    assert seen.device.lines == (("Hana", "Hi there"), (dm.SAMPLE_ME, "Hello!"),
                                 ("", "Day 2"), ("Kai", "Hey"))
    terminal = cm.preview({}, "Ren", {"device": "terminal"}, [], sends)
    assert terminal.device.look == "terminal" and terminal.device.lines == ()
    assert terminal.device.colors == dm.palette({}, "terminal")


def test_rename_contact_and_message_follow_send_lines():
    texts = {k: v for k, v in STORY.items()}
    ask = declrename.plan_rename(dec.CONTACT, "hana", "mori", texts)
    assert ask.text.startswith("Rename `hana` to `mori`? 4 places in 2 files will change.")
    plan = declrename.plan_rename(dec.CONTACT, "hana", "mori", texts, confirm=True)
    assert isinstance(plan, declrename.RenamePlan)
    after = {fp.ref: "\n".join(apply_lines(texts[fp.ref].split("\n"), fp.edits))
             for fp in plan.plan.files}
    assert declrename.verify_rename(plan, texts)
    assert "    send hello from mori on phone  # again" in after[MAIN]
    assert "    send hello from ren" in after[MAIN]
    assert after[DB_REF].startswith('lock contact mori "Hana" on pigeon')
    # A message (a data set) renamed: its send lines follow.
    plan = declrename.plan_rename(declrename.DATA, "hello", "greeting", texts, confirm=True)
    after = {fp.ref: "\n".join(apply_lines(texts[fp.ref].split("\n"), fp.edits))
             for fp in plan.plan.files}
    assert after[MAIN].count("send greeting from") == 3
    assert after[DB_REF].count("define greeting = [") == 1
    # ... and the replies it waits for: inbox.reply("hello") in a condition or a $ line,
    # with either quote; not a line of dialogue or another message's name.
    assert '    if inbox.reply("greeting") == "yes":' in after[MAIN]
    assert "        $ said = inbox.reply('greeting')" in after[MAIN]
    assert '    "hello"' in after[MAIN] and 'inbox.reply("hello_2")' in after[MAIN]


tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from engine.tools.editor import dbcontacts  # noqa: E402
from tests.tools.editor.test_studio_database import open_database, text_of  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401


def _tags(canvas) -> set[str]:
    return {t for item in canvas.find_all() for t in canvas.gettags(item)}


def _texts(canvas, tag: str) -> list[str]:
    return [canvas.itemcget(i, "text") for i in canvas.find_withtag(tag)]


def _game(tmp_path: Path) -> Path:
    game = files.new_game(tmp_path / "letters")
    assert isinstance(game, Path)
    config = game / "config.toml"
    config.write_text(config.read_text("utf-8").rstrip("\n") + '\n\n[theme]\nkit = "fantasy"\n',
                      "utf-8")
    pictures = game / "images" / "hana"
    pictures.mkdir(parents=True, exist_ok=True)
    (pictures / "portrait.png").write_bytes(_png())
    return game


def _png() -> bytes:
    """A 1 x 1 picture."""
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c4944415478"
        "9c63f8dfe00000044101c00cd1ed910000000049454e44ae426082")


@pytest.mark.tk
def test_contacts_page_new_contact_fields_messages_and_delete(studio, tmp_path, monkeypatch):
    opened: list[dbcontacts.MessageDialog] = []
    monkeypatch.setattr(dbcontacts.MessageDialog, "run", lambda self: opened.append(self))
    game = _game(tmp_path)
    ed = studio(game, mapped=True)
    db = open_database(ed, "contact")
    assert db.counts()["contact"] == 0
    # + New: the name players see, one line in database.vns.
    ed.answers.append("Hana")
    db.new_entry()
    ed.root.update()
    assert text_of(ed, DB_REF).endswith('lock contact hana "Hana"')
    assert db.selected_row().iid == "ct:hana"
    f = db.form.fields
    assert f["look"].box.get() == "Game default (Pigeon post, from the Fantasy kit)"
    # The preview is the Devices page's drawing of the look: a pigeon's note.
    assert {"look:pigeon", "notice", "panel", "message", "header"} <= _tags(f["preview"])
    assert _texts(f["preview"], "notice_text") == [
        "A pigeon lands on the sill with a note from Hana."]
    f["look"].pick("phone")
    ed.root.update()
    assert text_of(ed, DB_REF).endswith('lock contact hana "Hana" on phone')
    f = db.form.fields
    assert "look:phone" in _tags(f["preview"]) and "signature" not in _tags(f["preview"])
    f["image"].pick("hana portrait")
    ed.root.update()
    assert text_of(ed, DB_REF).endswith('lock contact hana "Hana" on phone image hana portrait')
    # + New message: a define with one line, opened in the step editor.
    ed.answers.append("message 1")
    name = db.new_message(db.selected_row().entry)
    ed.root.update()
    assert name == "hana_message_1" and opened
    assert 'define hana_message_1 = [\n    "Hey! Are you there?",\n' in text_of(ed, DB_REF)
    editor = opened[-1].editor
    assert editor is not None and editor.kind == mg.CHAT
    editor.changed((mg.Step(mg.FROM_CONTACT, "Meet me at the bridge."),
                    mg.Step(mg.FROM_ME, "On my way.")))
    opened[-1].close()
    ed.root.update()
    assert "Meet me at the bridge." in text_of(ed, DB_REF)
    f = db.form.fields
    assert _texts(f["preview"], "line") == ["Hana: Meet me at the bridge.", "You: On my way."]
    assert f["preview_caption"].cget("text") == "Not sent yet: hana_message_1"
    # Sent from a scene: the Delete refuses and says where.
    main = ed.win.record_for(MAIN).widget
    main.insert("end", "\nlabel morning:\n    send hana_message_1 from hana\n")
    db.refresh(select="ct:hana")
    ed.root.update()
    assert db.form.fields["preview_caption"].cget("text") == (
        "Newest: hana_message_1, sent in morning")
    ed.answers.append(1)                                              # OK
    assert db.delete_contact(db.selected_row().entry) is False
    assert ed.dialogs[-1][1].startswith("Hana sends messages from 1 line (scene morning, "
                                        "main.vns line ")
    assert 'lock contact hana' in text_of(ed, DB_REF)

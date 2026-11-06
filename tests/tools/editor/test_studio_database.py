"""F47 W2/W3: Studio's Database tab (``01-design.md`` §4.3, §6.2, §6.4; ``04-technical.md``
§3.2, §7.1; AC-F47-04, 07, 09, 10, 11, 12).

One test per AC, on copies of the F47 sample game (``engine/data/sample/``, via
``files.new_game``), the empty starter and the F46 lanterns fixture, all in ``tmp_path``.
The helper child is a recording fake except in AC-F47-12, which runs Studio and the real
helper child in a fresh process (no pygame in Studio's process)."""

import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan, files
from engine.tools.editor.checker import CheckEvent, CheckState
from engine.tools.editor.helperrunner import HelperReply
from tests.tools.editor.conftest import png
from tests.tools.f45_games import check

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_window import studio, wait_adding  # noqa: E402,F401

pytestmark = pytest.mark.tk

REPO = Path(__file__).resolve().parents[3]
LANTERNS = REPO / "tests" / "fixtures" / "F46" / "games" / "lanterns"
DB_REF = declplan.DATABASE_REF


class FakeHelper:
    """A ``HelperRunnerLike`` that records requests; replies are queued by the test."""

    def __init__(self, game_dir) -> None:
        self.sent: list[tuple] = []
        self.replies: list[HelperReply] = []
        self.serial = 0

    def still(self, kind, width, config):
        self.serial += 1
        return self.serial

    def thumb(self, ref, size, stamp=None):
        self.sent.append(("thumb", ref))
        return None

    def play(self, ref):
        self.serial += 1
        self.sent.append(("play", ref))
        return self.serial

    def stop_sound(self):
        self.serial += 1
        self.sent.append(("stop",))
        return self.serial

    def poll(self):
        out, self.replies = self.replies, []
        return out

    def stop(self):
        pass


@pytest.fixture
def helper(monkeypatch):
    made: list[FakeHelper] = []

    def make(game_dir):
        made.append(FakeHelper(game_dir))
        return made[-1]

    from engine.tools.editor import helperhub
    monkeypatch.setattr(helperhub, "make_runner", make)
    return made


def sample_game(tmp_path: Path) -> Path:
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    return game


def apply_check(ed, game: Path) -> None:
    """The headless check's result, applied as Studio applies a finished check."""
    result = replace(check(game), serial=ed.win.edit_serial)
    ed.win.apply_check_events([CheckEvent(CheckState.DONE, result.serial, result)])
    ed.root.update()


def open_database(ed, category: str):
    ed.root.update()
    ed.win.show_tab(ed.win.tab_index("database"))
    db = ed.win.database
    db.select_category(category)
    ed.root.update()
    return db


def text_of(ed, ref: str) -> str:
    return ed.win.files[ref].widget.get("1.0", "end-1c")


def commit(field, text: str) -> None:
    """Type ``text`` into an entry or spinbox field and press Enter."""
    field.var.set(text)
    field._done()


def test_ac_f47_04_database_tab_categories_counts_empty_states_uses_and_search(
        studio, tmp_path):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    win = ed.win
    ed.root.update()
    ed.press(ed.text, "<Control-Key-3>")       # the user's tab order: Database is third
    assert win.current_tab() == "database"
    assert ed.tab_strip.words()[:3] == ["Editor", "Story map", "Database"]
    db = win.database
    assert [db.cat_tree.item(k, "text") for k in db.cat_tree.get_children()] == [
        "Characters", "Pictures", "Gallery", "Sounds", "Music room", "Variables", "Meters",
        "Codex", "Contacts", "Endings & routes", "Scene replays", "Achievements", "Chapters",
        "Transitions", "Positions", "Minigame data", "Character files", "Clean up"]   # P1
    # (F34's Gallery, F35's Music room), P2 (F31's Character files, F65's Contacts), F41's
    # Clean up last
    # 9 pictures: the sample's 6 looks and backgrounds plus Hana's 3 F38 frames.
    assert db.counts() == {"character": 2, "picture": 9, "gallery": 0, "sound": 4,
                           "music_room": 0, "variable": 1,
                           "meter": 0, "codex": 0, "contact": 0, "ending": 2, "replay": 0,
                           "achievement": 0, "chapter": 0,
                           "transition": 0, "position": 3, "meta_file": 0, "cleanup": 0}
    assert [r.text for r in db.visible_rows()] == ["Daichi", "Hana"]

    # Used in N lines from the check; Show uses lists the lines; Delete is refused.
    apply_check(ed, game)
    db.select("c:hana")
    row = db.selected_row()
    assert row.detail == "5 lines"
    ed.answers.append(0)                        # Show uses
    db.delete_selected()
    assert ed.dialogs[-1][:3] == ("ask", "Hana is used in 5 lines, so it can't be deleted yet.",
                                  ("Show uses", "OK"))
    paragraphs = win.panel_paragraphs()
    assert "Hana is used in 5 lines:" in paragraphs
    assert any(p.startswith("script/main.vns:21: hana ") for p in paragraphs)
    assert DB_REF in win.refs and 'define hana' in (game / DB_REF).read_text("utf-8")

    # Search keeps matching rows (by shown or script name).
    db.set_search("dai")
    assert [r.text for r in db.visible_rows()] == ["Daichi"]
    db.set_search("zzz")
    assert db.visible_rows() == []
    db.set_search("")

    # An empty game: every category shows design §6.4's empty state with + New.
    blank = files.new_game(tmp_path / "blank", template=files.TEMPLATE_EMPTY)
    ed2 = studio(blank, mapped=True)
    db2 = open_database(ed2, "character")
    assert {k: v for k, v in db2.counts().items() if k != "position"} == dict.fromkeys(
        ("character", "picture", "gallery", "sound", "music_room", "variable", "meter", "codex",
         "contact", "ending",
         "replay", "achievement", "chapter", "transition", "meta_file", "cleanup"), 0)
    for category, things in (("character", "characters"), ("picture", "pictures"),
                             ("sound", "sounds"), ("variable", "variables")):
        db2.select_category(category)
        ed2.root.update()
        assert db2.empty.shown, category
        assert db2.empty.title.cget("text") == f"No {things} yet"
        assert db2.empty.hint.cget("text") == "Add one with + New."
        assert db2.empty.button.cget("text") == "+ New"


def test_ac_f47_07_first_declaration_makes_database_vns_and_one_include(studio, tmp_path):
    game = files.new_game(tmp_path / "blank", template=files.TEMPLATE_EMPTY)
    main_before = (game / "script" / "main.vns").read_text("utf-8")
    ed = studio(game)
    db = open_database(ed, "character")
    ed.answers.append("Rin")
    db.new_entry()
    # First-game fix: the Database saves the files it changed.
    assert text_of(ed, DB_REF) == (declplan.DATABASE_HEADER
                                   + '\ndefine rin = Character("Rin", color="#e06c9f")')
    assert text_of(ed, files.MAIN_REF) == 'include "database.vns"\n' + main_before.rstrip("\n")
    assert (game / DB_REF).read_text("utf-8").rstrip("\n") == text_of(ed, DB_REF)
    assert (game / files.MAIN_REF).read_text("utf-8").rstrip("\n") == text_of(ed,
                                                                               files.MAIN_REF)
    assert not ed.win.files[DB_REF].dirty and not ed.win.files[files.MAIN_REF].dirty
    assert db.selected_row().text == "Rin"
    assert ed.dialogs == [("text", "Name of the new character, as players will see it:", "",
                           None, None)]

    ed.answers.append("Kai")                    # the include is added once only
    db.new_entry()
    assert text_of(ed, files.MAIN_REF).count('include "database.vns"') == 1
    assert text_of(ed, DB_REF).endswith('define kai = Character("Kai", color="#4f8fd8")')

    # One undo step per file per action.
    ed.win.files[DB_REF].widget.edit_undo()
    ed.win.files[DB_REF].widget.edit_undo()
    assert text_of(ed, DB_REF) == declplan.DATABASE_HEADER
    ed.win.files[files.MAIN_REF].widget.edit_undo()
    assert text_of(ed, files.MAIN_REF) == main_before.rstrip("\n")


def test_ac_f47_09_looks_gallery_with_thumbnails_and_add_looks(studio, tmp_path, outside,
                                                               helper):
    game = sample_game(tmp_path)
    ed = studio(game)
    db = open_database(ed, "character")
    db.select("c:hana")
    # F38: the sample's blink and talking frames aren't looks; a look with them "moves".
    assert [label.removesuffix(" (moves)") for label in db.gallery.labels()] == [
        "happy", "sad"]
    assert set(db.gallery.images) == {"images/hana/happy.png", "images/hana/sad.png"}
    assert all(image.width() <= 96 and image.height() <= 96
               for image in db.gallery.images.values())

    ed.answers.append("Rin")
    db.new_entry()
    assert db.gallery.labels() == []            # "No looks yet…"
    assert not (game / "images" / "rin").exists()
    source = outside / "Rin Smile.png"
    source.write_bytes(png(8, 8))
    ed.picked[:] = [source]
    ed.answers.append("smile.png")              # F45's fixed-name question
    entry = db.selected_row().entry
    db.add_looks(entry)
    wait_adding(ed)
    asked = [d for d in ed.dialogs if d[0] == "text"][-1]
    assert asked[2] == "rin_smile.png"          # the fixed name offered
    assert (game / "images" / "rin" / "smile.png").read_bytes() == png(8, 8)
    assert ed.dialogs[-1] == ("info", "Added 1 file.")
    ed.root.update()
    assert db.selected_row().text == "Rin" and db.gallery.labels() == ["smile"]


def test_ac_f47_10_blip_fields_write_blip_options_and_play(studio, tmp_path, helper):
    game = sample_game(tmp_path)
    ed = studio(game)
    db = open_database(ed, "character")
    db.select("c:hana")
    fields = db.form.fields
    fields["blip"].pick("blips/daichi.wav")
    line = text_of(ed, DB_REF).split("\n")[7]
    assert line == ('define hana = Character("Hana", color="#b03070", '
                    'blip="blips/daichi.wav", blip_pitch=0.1)')
    commit(db.form.fields["every"], "4")
    commit(db.form.fields["volume"], "250")     # clamped to 100: the default, not written
    commit(db.form.fields["pitch"], "0.25")
    assert text_of(ed, DB_REF).split("\n")[7] == (
        'define hana = Character("Hana", color="#b03070", blip="blips/daichi.wav", '
        'blip_every=4, blip_pitch=0.25)')

    picker = db.form.fields["blip"]
    picker.play_button.invoke()
    assert helper[0].sent[-1] == ("play", "audio/blips/daichi.wav")
    assert picker.play_button.cget("text") == "■"
    picker.play_button.invoke()                 # ■ stops it
    assert helper[0].sent[-1] == ("stop",)
    assert picker.play_button.cget("text") == "▶"

    db.form.fields["blip"].pick(None)           # no blip: its tuning goes too
    assert text_of(ed, DB_REF).split("\n")[7] == 'define hana = Character("Hana", color="#b03070")'
    assert all(not db.form.fields[n].spin.instate(["!disabled"])
               for n in ("every", "pitch", "volume"))


def test_ac_f47_11_pictures_backgrounds_looks_add_and_colour(studio, tmp_path, outside,
                                                             monkeypatch, helper):
    assert dec.line_for(dec.COLOR, "bg night_sky", {"color": "#102040"}) == \
        'image bg night_sky = "#102040"'
    game = shutil.copytree(LANTERNS, tmp_path / "lanterns")
    ed = studio(game)
    db = open_database(ed, "picture")
    assert [(r.text, r.entry is None) for r in db.visible_rows()] == [
        ("Backgrounds", True), ("river", False), ("room", False),
        ("Hana's looks", True), ("happy", False)]
    db.select("g:bg")
    assert db.gallery.labels() == ["river", "room"]

    source = outside / "market.png"
    source.write_bytes(png(16, 9))
    ed.picked[:] = [source]
    db.add_pictures("bg")
    wait_adding(ed)
    assert (game / "images" / "bg" / "market.png").is_file()
    ed.root.update()
    assert "market" in [r.text for r in db.visible_rows()]

    from engine.tools.editor import fieldwidgets
    monkeypatch.setattr(fieldwidgets, "ask_color", lambda parent, initial: "#102040")
    ed.answers.append("Night sky")
    db.new_color()
    assert text_of(ed, DB_REF).endswith('image bg night_sky = "#102040"')
    assert text_of(ed, "script/main.vns").startswith('include "ch2.vns"\ninclude "database.vns"')
    row = db.selected_row()
    assert row.iid == "k:bg night_sky" and row.text == "night_sky (colour)"
    db.form.fields["color"].var.set("#aa2200")
    db.form.fields["color"]._typed()
    assert text_of(ed, DB_REF).endswith('image bg night_sky = "#aa2200"')


AC12_CHILD = r"""
import os
import sys
import time
import tkinter

try:
    root = tkinter.Tk()
except tkinter.TclError:
    print("NO-DISPLAY")
    sys.exit(0)
root.destroy()

from pathlib import Path

from engine.core.paths import GamePaths
from engine.tools.editor import helperhub
from engine.tools.editor.window import EditorWindow


class FakeChecks:
    def request(self, overlay, serial, *, launch):
        pass

    def poll(self):
        return []

    def stop(self):
        pass


sent = []
real = helperhub.make_runner


def spy(game_dir):
    runner = real(game_dir)
    for op in ("play", "stop_sound"):
        method = getattr(runner, op)
        setattr(runner, op, lambda *a, _m=method, _op=op: (sent.append((_op, *a)), _m(*a))[1])
    return runner


helperhub.make_runner = spy
root = tkinter.Tk()
root.withdraw()
win = EditorWindow(root, GamePaths.for_game(Path(sys.argv[1])), check_runner=FakeChecks())
root.update()
win.show_tab(win.tab_index("database"))
db = win.database
db.select_category("sound")
root.update()
groups = [r.text for r in db.visible_rows() if r.entry is None]
assert groups == ["Music", "Sound effects", "Voices", "Blips"], groups
replies = []


def wait(pred, seconds=60):
    end = time.monotonic() + seconds
    while not pred() and time.monotonic() < end:
        root.update()
        time.sleep(0.02)
    assert pred()


db.select("s:sound/chime.wav")
db.play_button.invoke()
hub = helperhub.hub_for(win)
hub.listen(replies.append)
wait(lambda: any(r.op == "play" for r in replies))
first = next(r for r in replies if r.op == "play")
assert win.helper_hub.runner.process.pid != os.getpid()
still_playing = hub.playing is not None
db.select("s:blips/hana.wav")                    # another row: the first sound stops
assert sent[-1] == ("stop_sound",) or not still_playing, sent
db.play_button.invoke()
assert hub.playing == "audio/blips/hana.wav" and db.play_button.cget("text") == "■ Stop"
assert [s for s in sent if s[0] == "play"] == [("play", "audio/sound/chime.wav"),
                                               ("play", "audio/blips/hana.wav")]
win.select_tab("editor")                          # switching tab stops it
root.update()
assert hub.playing is None and sent[-1] == ("stop_sound",), sent
win.select_tab("database")
root.update()
db.select("s:sound/broken.wav")
replies.clear()
db.play_button.invoke()
wait(lambda: any(r.op == "play" for r in replies))
assert not replies[-1].ok
assert db.sound_label.cget("text").startswith("This sound can't be played: "), \
    db.sound_label.cget("text")
print("FIRST", first.ok, first.reason)
win.close()
banned = ("engine.render", "engine.ui", "engine.audio", "engine.runtime")
found = sorted(name for name in sys.modules
               if name.split(".")[0] == "pygame" or name.startswith(banned))
print(found)
"""


def test_ac_f47_12_sounds_by_folder_play_one_at_a_time_through_the_helper(tmp_path):
    game = sample_game(tmp_path)
    (game / "audio" / "sound" / "broken.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVEjunk")
    result = subprocess.run([sys.executable, "-c", AC12_CHILD, str(game)], cwd=REPO,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    if result.stdout.strip() == "NO-DISPLAY":
        pytest.skip("no display for Tk")
    lines = result.stdout.strip().splitlines()
    assert lines[0].startswith("FIRST ")            # a real reply from the helper child
    assert lines[-1] == "[]"                         # no pygame in Studio's process


def test_ac_f47_52_rename_everywhere_on_a_used_character(studio, tmp_path):
    """P3-B: Rename… on a used character asks once with the count, then every line that
    uses it follows; its pictures stay (``image_tag``); one undo step per file."""
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    apply_check(ed, game)
    db = open_database(ed, "character")
    db.select("c:hana")
    ed.root.update()
    buttons = [w for w in _descendants(db.form_frame) if isinstance(w, tk.ttk.Button)
               and str(w.cget("text")) == "Rename…"]
    assert buttons                                  # shown though Hana is used
    main_before = text_of(ed, "script/main.vns")
    ed.answers[:] = ["hanako", 0]                   # the new name, then Rename
    buttons[0].invoke()
    ed.root.update()
    assert ed.dialogs[-2][:3] == ("text", "New script name for Hana:", "hana")
    assert ed.dialogs[-1][:3] == (
        "ask", "Rename `hana` to `hanako`? 6 places in 2 files will change. "
               "Its pictures stay in images/hana/.", ("Rename", "Cancel"))
    main, database = text_of(ed, "script/main.vns"), text_of(ed, DB_REF)
    assert 'define hanako = Character("Hana", color="#b03070", blip="blips/hana.wav", ' \
           'blip_pitch=0.1, image_tag="hana")' in database
    assert '    hanako "You came!' in main and '            hanako sad "Oh.' in main
    assert "    show hana happy at left with dissolve" in main      # the picture's name
    assert "hana " not in main.replace("show hana", "")
    assert db.selected_row().entry.name == "hanako"
    assert (game / "script/main.vns").read_text("utf-8").removesuffix("\n") == main
    for ref in ("script/main.vns", DB_REF):          # one Ctrl+Z per file undoes it
        ed.win.files[ref].widget.edit_undo()
    assert text_of(ed, "script/main.vns") == main_before
    assert "define hana = " in text_of(ed, DB_REF)


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)

"""F38 step 3: blinking and talking in Studio (``SPEC.md`` §4; AC-F38-10..13).

One test per AC. AC-F38-10..12 run Studio's Database tab on a copy of the F47 sample game
(``files.new_game``) with frame pictures beside ``images/hana/happy.png``; the helper
child is the recording fake of ``test_studio_database``. AC-F38-13 is pure (Game settings'
rows, ``section_values``, ``dbmodel.looks_of``)."""

import time
from pathlib import Path

import pytest

from engine.script.messages import show
from engine.tools.editor import dbmodel as db
from engine.tools.editor import settingsmodel as sm
from tests.tools.editor.conftest import png
from tests.tools.editor.test_studio_database import (  # noqa: F401  (fixtures)
    helper, open_database, sample_game, studio)
from tests.tools.editor.test_studio_window import wait_adding

HANA = Path("images") / "hana"
HAPPY = "images/hana/happy.png"
SAD = "images/hana/sad.png"


def ref(name: str) -> str:
    return f"images/hana/{name}"


def frames(game: Path, *names: str, size: tuple[int, int] | None = None) -> None:
    """Frame files beside happy.png: copies of it (decodable, same size), or header-only
    PNGs of ``size``."""
    happy = (game / HAPPY).read_bytes()
    for name in names:
        (game / HANA / name).write_bytes(happy if size is None else png(*size))


def set_config(game: Path, text: str) -> None:
    with open(game / "config.toml", "a", encoding="utf-8") as out:
        out.write("\n" + text)


@pytest.fixture
def hana(studio, tmp_path, helper):
    """``(ed, pane, game)`` → Database ▸ Characters ▸ Hana; call after making files."""
    game = sample_game(tmp_path)
    for old in (game / HANA).iterdir():          # the sample's own frames: each test makes its own
        if "_blink" in old.name or "_talk" in old.name:
            old.unlink()

    def start():
        ed = studio(game)
        pane = open_database(ed, "character")
        pane.select("c:hana")
        return ed, pane

    return game, start


def pump(ed, until, seconds: float = 4.0) -> None:
    end = time.monotonic() + seconds
    while not until() and time.monotonic() < end:
        ed.root.update()
        time.sleep(0.005)
    assert until()


@pytest.mark.tk
def test_ac_f38_10_gallery_hides_frames_labels_moves_and_panel_shows_texts(hana):
    from engine.tools.editor import animpanel
    from engine.tools.editor.database import DELETE_FILE_ASK
    from engine.tools.editor.formassets import WindowAssets
    game, start = hana
    frames(game, "happy_blink2.png", "happy_blink1.png")
    frames(game, "happy_talk.png", size=(8, 8))             # another size: the hint
    frames(game, "smile_blink1.png")                         # no smile look: a look
    ed, pane = start()
    assert pane.gallery.labels() == ["happy (moves)", "sad", "smile_blink1"]
    panel = pane.anim_panel
    assert panel.caption_text == "Blinking and talking"
    assert panel.pick.cget("text") == "Click a look to set up blinking and talking."
    assert panel.pick.grid_info() and not panel.left.grid_info()

    pane.gallery._choose(HAPPY)                              # one click
    assert panel.caption_text == "Blinking and talking: happy"
    assert not panel.pick.grid_info() and panel.left.grid_info()
    blink, talk = panel.rows["blink"], panel.rows["talk"]
    assert blink.gallery.items == [(ref("happy_blink1.png"), "blink1"),
                                   (ref("happy_blink2.png"), "blink2")]
    assert talk.gallery.items == [(ref("happy_talk.png"), "talk")]
    assert blink.title.cget("text") == "Blink frames"
    assert talk.title.cget("text") == "Talking frames"
    assert blink.hint.cget("text") == ("Pictures of happy with the eyes closed (or half "
                                       "closed, then closed). Hana blinks every few seconds.")
    assert talk.hint.cget("text") == ("Pictures of happy with the mouth open. The mouth "
                                      "moves while Hana's lines type.")
    assert panel.tip.cget("text") == (
        "A frame is a copy of happy.png with only the eyes or mouth changed, the same size. "
        "Files named happy_blink1, happy_talk1, … are found by themselves.")
    assert [label.cget("text") for label in talk.size_hints] == [
        "happy_talk.png is 8×8, but happy is 400×680, so the game won't use it. Frames "
        "must be the same size as their look."]
    assert blink.size_hints == []
    assert (blink.add.cget("text"), talk.add.cget("text")) == (
        "+ Add blink frame…", "+ Add talking frame…")
    assert str(blink.remove.cget("state")) == "disabled"     # nothing selected yet
    assert not panel.off.grid_info()
    assert blink.gallery.empty_text == "None yet"
    assert animpanel.DELETE_FILE_ASK == DELETE_FILE_ASK

    pane.gallery._choose(SAD)                                # sad: no frames
    assert panel.caption_text == "Blinking and talking: sad"
    assert blink.gallery.items == [] and talk.gallery.items == []
    assert str(panel.play_buttons["blink"].cget("state")) == "disabled"

    set_config(game, "[animation]\nenabled = false\n")       # Game settings: off
    panel.sync_hints()
    assert panel.off.grid_info() and panel.off.cget("text") == (
        "Sprite animation is turned off in Game settings ▸ Effects & comfort.")
    # F47 Events pickers: frames aren't looks (07 I-10).
    assert tuple(WindowAssets(ed.win).looks("hana")) == ("happy", "sad", "smile_blink1")


@pytest.mark.tk
def test_ac_f38_11_add_frame_saves_next_name_remove_deletes_after_ask_nine_disable(
        hana, outside):
    game, start = hana
    frames(game, "happy_talk.png")                           # unnumbered counts as 0
    ed, pane = start()
    pane.gallery._choose(HAPPY)
    source = outside / "Eyes Closed.PNG"
    source.write_bytes((game / HAPPY).read_bytes())
    for kind, made in (("blink", "happy_blink1.png"), ("blink", "happy_blink2.png"),
                       ("talk", "happy_talk1.png")):
        ed.picked[:] = [source, outside / "ignored.png"]     # one picture only
        pane.anim_panel.add_frame(kind)
        wait_adding(ed)
        assert (game / HANA / made).read_bytes() == source.read_bytes(), made
        assert ed.dialogs[-1] == ("info", "Added 1 file.")
        ed.root.update()
        panel = pane.anim_panel                              # the form was rebuilt
        assert panel.look is not None and panel.look.ref == HAPPY   # still on happy
        assert pane.gallery.selected == HAPPY
    assert [k for k, _l in panel.rows["blink"].gallery.items] == [
        ref("happy_blink1.png"), ref("happy_blink2.png")]
    assert [k for k, _l in panel.rows["talk"].gallery.items] == [
        ref("happy_talk.png"), ref("happy_talk1.png")]
    assert not [d for d in ed.dialogs if d[0] == "text"]     # no name question

    blink = panel.rows["blink"]
    blink.gallery._choose(ref("happy_blink2.png"))
    assert str(blink.remove.cget("state")) == "normal"
    ask = ("ask", f"Delete {show(ref('happy_blink2.png'))} from the game folder? This "
           "can't be undone.", ("Delete", "Cancel"), 1, 1)
    ed.answers.append(1)                                     # Cancel
    blink.remove.invoke()
    assert ed.dialogs[-1] == ask and (game / HANA / "happy_blink2.png").is_file()
    ed.answers.append(0)                                     # Delete
    blink.remove.invoke()
    assert ed.dialogs[-1] == ask and not (game / HANA / "happy_blink2.png").exists()
    ed.root.update()
    assert [k for k, _l in pane.anim_panel.rows["blink"].gallery.items] == [
        ref("happy_blink1.png")]

    frames(game, "happy_blink9.png")                         # 9 used: full
    ed.win.refresh_project()
    pane.refresh()
    ed.root.update()
    blink = pane.anim_panel.rows["blink"]
    assert str(blink.add.cget("state")) == "disabled"
    assert blink.full.grid_info() and blink.full.cget("text") == (
        "A look can have up to 9 blink frames.")
    assert str(pane.anim_panel.rows["talk"].add.cget("state")) == "normal"


@pytest.mark.tk
def test_ac_f38_12_play_swaps_previews_in_cycle_order_at_config_timings_and_stops(hana):
    game, start = hana
    frames(game, "happy_blink1.png", "happy_blink2.png", "happy_talk1.png")
    set_config(game, "[animation]\nblink_frame = 0.05\ntalk_frame = 0.04\n")
    ed, pane = start()
    pane.gallery._choose(HAPPY)
    panel = pane.anim_panel
    button = panel.play_buttons["blink"]
    assert button.cget("text") == "▶ Blink"
    button.invoke()
    assert button.cget("text") == "■ Stop" and panel.step_ms == 50
    assert panel.steps == ["hana happy_blink1", "hana happy_blink2", "hana happy_blink1",
                           "hana happy"]
    first = pane.previews.get(ref("happy_blink1.png"))
    assert first is not None and str(panel.preview.cget("image")) == str(first)
    pump(ed, lambda: panel.playing is None)
    assert panel.played == panel.steps and panel.shown_name == "hana happy"
    assert str(panel.preview.cget("image")) == str(pane.previews.get(HAPPY))
    assert button.cget("text") == "▶ Blink"

    talk = panel.play_buttons["talk"]
    talk.invoke()                                            # talking loops for 2 s
    assert talk.cget("text") == "■ Stop" and panel.step_ms == 40
    assert panel.steps == ["hana happy_talk1", "hana happy"] * 25
    talk.invoke()                                            # ■ Stop
    assert panel.playing is None and talk.cget("text") == "▶ Talk"
    assert panel.shown_name == "hana happy"

    talk.invoke()
    pane.gallery._choose(SAD)                                # another look stops it
    assert panel.playing is None and panel._after is None
    pane.gallery._choose(HAPPY)
    panel.play_buttons["talk"].invoke()
    ed.win.show_tab(ed.win.tab_index("editor"))              # another tab stops it
    ed.root.update()
    assert panel.playing is None and panel._after is None


def test_ac_f38_13_game_settings_sprite_animation_row_and_looks_of_omits_frames():
    from engine.tools.editor.forms import missing_forms
    effects = sm.page("effects")
    titles = [s.title for s in effects.sections]
    assert titles.index("Sprite animation") == titles.index("Effect colors") + 1
    section = effects.sections[titles.index("Sprite animation")]
    assert [(f.path, f.label) for f in section.fields] == [
        ("animation.enabled", "Blinking and talking sprites"),
        ("animation.blink_every", "Blink about every (seconds)"),
        ("animation.blink_frame", "Seconds per blink frame"),
        ("animation.talk_frame", "Seconds per talking frame")]
    assert [f.kind for f in section.fields] == ["toggle", "number", "number", "number"]
    # Settings key coverage and the forms registry still hold.
    for key in sm.all_keys():
        assert key in sm.fields_by_path() or sm.text_only(key) or sm.on_looks_page(key), key
    assert missing_forms() == []
    # The look panel's timings: config.toml's accepted values, else the defaults.
    defaults = {"enabled": True, "blink_every": 4.0, "blink_frame": 0.08, "talk_frame": 0.1}
    assert sm.section_values("animation", None) == defaults
    assert sm.section_values("animation", "[animation\n") == defaults
    assert sm.section_values("animation", "[animation]\nenabled = false\nblink_frame = 9\n"
                             "talk_frame = 0.2\n") == {**defaults, "enabled": False,
                                                       "talk_frame": 0.2}
    # dbmodel.looks_of (the Events pickers' rule) leaves frames out.
    rows =[type("Row", (), {"name": n, "file": None, "line": None})()
            for n in ("hana happy", "hana happy_blink1", "hana happy_talk", "hana sad",
                      "hana smile_blink1", "hana happy_blink10", "rin happy_blink1")]
    names = {"image": rows}
    assert db.looks_of("hana", names) == ("happy", "happy_blink10", "sad", "smile_blink1")
    assert db.looks_in("Hana", ["hana happy", "hana happy_blink1"]) == ("happy",)
    assert db.looks_in("hana", ["hana happy", "hana happy_blink1"],
                       not_pictures={"hana happy_blink1"}) == ("happy", "happy_blink1")

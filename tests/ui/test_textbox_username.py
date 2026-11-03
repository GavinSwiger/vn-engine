"""F30 step 5 — the name on screen: AC-F30-26 (textbox, NVL, crash), AC-F30-27 (who may
read, W188), AC-F30-32 (``name_drawn`` and the capture paths), AC-F30-33 (forced leaks are
redacted). ``04`` §6.3, §6.4, §6.6; SEC-F30-01, 03, 04, 06.

App runs are App A (``tests/fakes/text_app.Session``) with F16's real ``SettingsService``
(no writer) set on the App before launch and Reader Z swapped in for
``engine.app.fourthwall.read_login_name`` (the name guard is on: a real read fails the
test). Read counting and W188 use ``FourthWall`` on a stand-in App (no window).
"""

import logging
from dataclasses import replace
from types import SimpleNamespace

import pygame
import pytest

from engine.app import fourthwall as fourthwall_module
from engine.app.fourthwall import FourthWall
from engine.app.settings import SettingsService
from engine.core import redact
from engine.core.config_schema import Config
from engine.persist.settings_file import LoadedSettings, Outcome
from engine.render.typewriter import TypeState
from engine.runtime.commands import Span, Style, TaggedText
from engine.ui.builtin.fake_crash import FakeCrashScreen, crash_text
from tests.fakes.text_app import Session, make_text_game
from tests.fakes.username import Z, no_real_username, reader  # noqa: F401  (name guard)

pytestmark = pytest.mark.display

L7 = "I know who you are, {username}."
SCRIPT = ('define hana = Character("Hana")\n'
          'image bg room = "#c8c8c8"\n'
          "label start:\n"
          "    scene bg room\n"
          '    hana "Hello."\n'
          f'    hana "{L7}"\n'
          '    effect crash "Hi {username}"\n'
          '    "End."\n')


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def session(tmp_path, monkeypatch, *, offer: bool = True, use: int = 2, read=None):
    root = make_text_game(tmp_path / "g", script=SCRIPT,
                          config=("[textbox]\ncps = 0\n\n[saves]\nautosave_quit = false\n"
                                  f"\n[meta]\nusername = {'true' if offer else 'false'}\n"))
    read = read or reader(Z)
    monkeypatch.setattr(fourthwall_module, "read_login_name", read)
    s = Session(root)
    s.app.settings = SettingsService(LoadedSettings({"username_use": use}, Outcome.OK),
                                     s.app.config)
    return s, read


def drawn_text(textbox) -> str:
    layout = textbox.layout
    return "".join(g.text for k in range(layout.all_pages()) for line in layout.page(k).lines
                   for g in line.glyphs)


def stand_in(*, offer=True, use=2, start=None, fallback="friend", read=None):
    base = Config()
    config = replace(base, meta=replace(base.meta, username=offer,
                                        username_fallback=fallback))
    settings = SettingsService(LoadedSettings({"username_use": use} if use else {},
                                              Outcome.OK), config)
    wall = FourthWall(SimpleNamespace(config=config, settings=settings, start=start,
                                      textbox=None))
    read = read or reader(Z)
    wall.wire_name(read)
    settings.add_listener(wall.settings_changed)
    return wall, settings, read


# --- AC-F30-26 -----------------------------------------------------------------------------------

def test_ac_f30_26_the_name_in_the_textbox_nvl_and_the_crash(tmp_path, monkeypatch):
    s, read = session(tmp_path, monkeypatch)
    out: dict = {}

    def script(s: Session):
        yield from s.until_line("Hello.")
        out["reads_at_hello"] = read.calls
        s.key(pygame.K_SPACE)
        yield from s.until_line(L7)
        tb = s.textbox
        out["l7"] = (drawn_text(tb), tb.layout.has_name, tb.name_drawn(), read.calls)
        out["record"] = [sp.text for sp in tb.line.body.pieces if sp.style.username]
        posted, said = len(s.posted), len(s.said)
        s.app.settings.set("username_use", 1)                # the row turned off
        yield
        out["off"] = (drawn_text(tb), tb.typer.state is TypeState.COMPLETE,
                      len(s.posted) - posted, len(s.said) - said, tb.name_drawn())
        s.app.settings.set("username_use", 2)                # on again
        yield
        out["on"] = (drawn_text(tb), read.calls)
        s.key(pygame.K_SPACE)
        yield from s.until(lambda: isinstance(s.app.screens.top, FakeCrashScreen))
        out["crash"] = s.app.screens.top.message

    s.play(script, last=900)
    assert out["reads_at_hello"] == 0                        # not at launch
    assert out["l7"] == ("I know who you are, Zq9Name.", True, True, 1)
    assert out["record"] == ["friend"]                       # Say (and history) keep friend
    assert out["off"] == ("I know who you are, friend.", True, 0, 0, False)
    assert out["on"] == ("I know who you are, Zq9Name.", 2)
    assert out["crash"] == "Hi Zq9Name"
    # The crash with the row off draws the fallback, never <user>.
    hi = TaggedText((Span("Hi ", Style()), Span("friend", Style(username=True))))
    assert crash_text(hi, None, "x") == "Hi friend"

    # [meta] username = false: the fallback everywhere, no read.
    s2, read2 = session(tmp_path / "off", monkeypatch, offer=False)
    seen: dict = {}

    def script2(s: Session):
        yield from s.until_line("Hello.")
        s.key(pygame.K_SPACE)
        yield from s.until_line(L7)
        seen["l7"] = drawn_text(s.textbox)

    s2.play(script2, last=600)
    assert seen["l7"] == "I know who you are, friend." and read2.calls == 0


def test_ac_f30_26_nvl_page_lays_out_again(tmp_path, monkeypatch):
    # walk-nvl/: the name on row 1 of 3, the row turned off: the page draws friend.
    script = SCRIPT.replace('    hana "Hello."\n', '    nvl on\n    hana "Hello."\n').replace(
        '    effect crash "Hi {username}"\n', '    "Two."\n    "Three."\n')
    root = make_text_game(tmp_path / "nvl", script=script,
                          config="[textbox]\ncps = 0\n\n[meta]\nusername = true\n")
    monkeypatch.setattr(fourthwall_module, "read_login_name", reader(Z))
    s = Session(root)
    s.app.settings = SettingsService(LoadedSettings({"username_use": 2}, Outcome.OK),
                                     s.app.config)
    out: dict = {}

    def row1(tb) -> str:
        nvl = tb.nvl
        page = nvl.settled_page(nvl.plan.rows[1])
        return "".join(g.text for line in page.lines for g in line.glyphs)

    def script_(s: Session):
        yield from s.until_line("Hello.")
        for text in (L7, "Two.", "Three."):
            s.key(pygame.K_SPACE)
            yield from s.until_line(text)
        tb = s.textbox
        out["before"] = (row1(tb), tb.name_drawn())
        s.app.settings.set("username_use", 1)
        yield
        out["after"] = (row1(tb), tb.name_drawn())

    s.play(script_, last=900)
    assert out["before"] == ("I know who you are, Zq9Name.", True)
    assert out["after"] == ("I know who you are, friend.", False)


# --- AC-F30-27 -----------------------------------------------------------------------------------

def test_ac_f30_27_who_may_read_and_w188(caplog):
    for offer, use in ((False, 2), (True, 0), (True, 1)):
        wall, _, read = stand_in(offer=offer, use=use)
        assert wall.name_source() is None and read.calls == 0, (offer, use)
    wall, _, read = stand_in()
    assert [wall.name_source() for _ in range(50)] == [Z] * 50 and read.calls == 1
    wall, _, read = stand_in(start=object())                  # F44 start options
    assert wall.source is None and wall.name_source() is None and read.calls == 0
    # Unreadable: W188 once, naming only the fallback word.
    for bad in (None, "", OSError("Zq9Name")):
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            wall, settings, read = stand_in(read=reader(bad))
            assert wall.name_source() is None
            settings.set("username_use", 1)
            settings.set("username_use", 2)
            assert wall.name_source() is None and read.calls == 2
        w188 = [r.getMessage() for r in caplog.records if "couldn't be read" in r.getMessage()]
        assert w188 == ["the computer's user name couldn't be read, so {username} shows "
                        '"friend" this session.'], (bad, w188)
        assert not [r for r in caplog.records if "zq9name" in r.getMessage().lower()
                    or (r.exc_text or "").lower().count("zq9name")]
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        wall, _, _ = stand_in(fallback="pal", read=reader(None))
        wall.name_source()
    assert '"pal"' in caplog.records[-1].getMessage()


# --- AC-F30-32 -----------------------------------------------------------------------------------

@pytest.mark.skip(reason="F30 s5: needs GameShell.clean_capture / scene_wanted / _clean in "
                         "ui/shell.py (held by another builder); the textbox seam "
                         "(set_clean_capture, name_drawn) is built and wired when it exists")
def test_ac_f30_32_name_drawn_and_every_capture_path():
    pass


# --- AC-F30-33 -----------------------------------------------------------------------------------

def test_ac_f30_33_forced_leaks_are_redacted():
    # Thin: every output channel (log file, stderr, LogSession.tail, the ErrorScreen and its
    # clipboard text) goes through redact() (F01); here: the session term it applies.
    wall, settings, _ = stand_in()
    assert wall.name_source() == Z
    assert redact.redact("I know who you are, Zq9Name.") == "I know who you are, <user>."
    assert redact.redact("zq9name and ZQ9NAME") == "<user> and <user>"
    assert redact.redact("Zq9Namely") == "Zq9Namely"                  # whole word only
    settings.set("username_use", 1)                                   # forget()
    assert redact._session_term is None
    assert redact.redact("Zq9Name") == "Zq9Name"
    wall, _, _ = stand_in(read=reader("Al"))                          # 2 graphemes: no term
    assert wall.name_source() == "Al" and redact._session_term is None

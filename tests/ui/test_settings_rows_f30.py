"""F30 step 5 — AC-F30-28 (the setting and its row) and AC-F30-29 (only the player can
consent, SEC-F30-07). F16's real ``SettingsService`` (no writer) and a ``SettingsPage`` built
over it; the name's wiring is ``app/fourthwall.py``'s ``FourthWall`` on a stand-in App."""

import ast
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from engine.app.fourthwall import FourthWall, UsernameGate
from engine.app.settings import SettingsService
from engine.core.config_schema import Config, WordsConfig
from engine.core.settings_schema import FORMAT, KEYS, IntKey
from engine.persist.settings_file import LoadedSettings, Outcome, encode_settings, \
    parse_settings
from engine.ui.builtin.settings_page import SettingsPage
from engine.ui.theme import Words
from tests.fakes.username import Z, no_real_username, reader  # noqa: F401  (name guard)

ENGINE = Path(__file__).resolve().parents[2] / "engine"


def config(offer: bool, **extra) -> Config:
    base = Config()
    return replace(base, meta=replace(base.meta, username=offer), **extra)


def service(offer: bool = True, values: dict | None = None) -> SettingsService:
    return SettingsService(LoadedSettings(values or {}, Outcome.OK), config(offer))


def page(settings: SettingsService, *, title: bool) -> SettingsPage:
    host = SimpleNamespace(shell=SimpleNamespace(words=Words(WordsConfig())))
    return SettingsPage(host, settings, title=title)


def wired(settings: SettingsService, read=None, *, crash: bool = False) -> FourthWall:
    """``install_fourthwall``'s name wiring on a stand-in App (no window, no story)."""
    app = SimpleNamespace(config=settings.config, settings=settings, start=None,
                          textbox=None)
    wall = FourthWall(app)
    wall.wire_name(read or reader(Z))
    settings.add_listener(wall.settings_changed)
    offered = bool(settings.config.meta.username)
    settings.row_rules["settings_username"] = lambda: offered
    settings.row_rules["settings_crash_label"] = lambda: crash
    return wall


def test_ac_f30_28_the_setting_and_its_row():
    assert KEYS["username_use"] == IntKey(0, 2) and FORMAT >= 3
    s = service()
    assert s.value("username_use") == 0 and s.value("crash_label") is False
    # Older files (F33's format 2, F16's format 1) read with their values kept.
    for version in (1, 2):
        loaded = parse_settings(json.dumps({"format": version,
                                            "values": {"music_volume": 40}}).encode())
        assert loaded.outcome is Outcome.OK and dict(loaded.values) == {"music_volume": 40}
    # The row: in the Data group, before Reset, on both pages, iff [meta] username.
    for title in (True, False):
        s = service()
        assert "settings_username" not in page(s, title=title).widgets   # no rule yet
        wired(s)
        words = list(page(s, title=title).widgets)
        assert words.index("settings_username") == words.index("reset_settings") - 1
        off = service(offer=False)
        wired(off)
        assert "settings_username" not in page(off, title=title).widgets
    # On iff 2; toggling writes 2, then 1; the file holds only that number.
    s = service()
    read = reader(Z)
    wall = wired(s, read)
    row = page(s, title=False).widgets["settings_username"]
    assert row.get() is False
    row.set(True)
    assert (s.value("username_use"), row.get()) == (2, True)
    assert wall.name() == Z and read.calls == 1
    row.set(False)
    assert s.value("username_use") == 1 and wall.name() is None
    assert json.loads(encode_settings(s.stored)) == {"format": FORMAT,
                                                     "values": {"username_use": 1}}
    # Reset: 0, the name forgotten (the next draw is the fallback), no read until a new
    # opt-in, and the question is due at the next launch (a new session's gate).
    row.set(True)
    assert wall.name() == Z and read.calls == 2
    s.reset()
    assert s.value("username_use") == 0 and wall.name() is None and read.calls == 2
    app = SimpleNamespace(config=s.config, settings=s, start=None)
    assert UsernameGate(app).due()


def test_ac_f30_29_only_the_player_can_consent():
    # Refused stored values load as 0 (W71) and the question is due.
    for bad in (3, -1, "2", True, 2.0, None):
        data = json.dumps({"format": 3, "values": {"username_use": bad}}).encode()
        loaded = parse_settings(data)
        assert "username_use" not in loaded.values, bad
        assert [p.key for p in loaded.problems] == ["username_use"], bad
        s = SettingsService(loaded, config(True))
        assert s.value("username_use") == 0
        assert UsernameGate(SimpleNamespace(config=s.config, settings=s, start=None)).due()
    # No config key feeds the defaults: whatever [meta] and [settings] say, 0 and False.
    for offer in (True, False):
        s = service(offer)
        assert (s.defaults["username_use"], s.defaults["crash_label"]) == (0, False)
    assert not hasattr(Config().meta, "username_use")
    assert not hasattr(Config().meta, "crash_label")
    # Start options never consent (and never ask).
    s = service()
    app = SimpleNamespace(config=s.config, settings=s, start=object())
    assert not UsernameGate(app).due()
    wall = FourthWall(SimpleNamespace(config=s.config, settings=s, start=object(),
                                      textbox=None))
    wall.wire_name(reader(Z))
    s.set("username_use", 2)
    assert wall.source is None and wall.name_source() is None

    # AST scan: `username_use` is written only by the Settings row, the gate's answer,
    # and Reset (which clears every key).
    writers = []
    for path in sorted(ENGINE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "username_use" not in text:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "set" and node.args \
                    and isinstance(node.args[0], ast.Constant) \
                    and node.args[0].value == "username_use":
                writers.append(path.relative_to(ENGINE).as_posix())
    assert sorted(writers) == ["app/fourthwall.py"], writers
    source = (ENGINE / "ui/builtin/settings_page.py").read_text(encoding="utf-8")
    assert "port.set(key, 2 if on else 1)" in source

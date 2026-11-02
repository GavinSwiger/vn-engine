"""F33 — AC-F33-02 (``WarningGate.due``), AC-F33-03 (the ``warning_seen`` settings key),
and AC-F33-09 (W193) (F33 ``SPEC.md`` PR-F33-02, 03, 05; ``07`` I-1, I-3, I-5, I-6). No
window: the gate runs on fake settings or a real ``SettingsService`` without one; W193
measures with the bundled fonts on an ``AssetManager`` without a game folder."""

import logging
from types import MappingProxyType

import pygame
import pytest

from engine.app.content_warning import WarningGate, check_fit, large_text_layout, w193_text
from engine.app.settings import SettingsService
from engine.core.config_schema import Config, ContentWarningConfig
from engine.core.settings_schema import FORMAT, KEYS, IntKey, check
from engine.persist.settings_file import LoadedSettings, Outcome, encode_settings, \
    parse_settings
from engine.ui.builtin.settings_page import GROUPS
from engine.ui.theme import Words, plain_theme
from tests.render.conftest import make_assets


class FakeSettings:
    def __init__(self, seen: int = 0) -> None:
        self.stored = {"warning_seen": seen} if seen else {}
        self.sets: list[tuple[str, int]] = []

    def value(self, key):
        return self.stored.get(key, 0)

    def set(self, key, value):
        self.sets.append((key, value))
        self.stored[key] = value


def gate(show: str, *, version: int = 1, seen: int = 0, settings: object = "fake",
         skip: bool = False) -> WarningGate:
    service = FakeSettings(seen) if settings == "fake" else settings
    return WarningGate(ContentWarningConfig(show, "Text.", version), lambda: service,
                       skip=skip)


def service_from(values: dict, outcome: Outcome = Outcome.OK, *,
                 writable: bool = True) -> SettingsService:
    loaded = LoadedSettings(MappingProxyType(values), outcome, writable=writable)
    return SettingsService(loaded, Config())


# --- AC-F33-02 --------------------------------------------------------------------------------

def test_ac_f33_02_due():
    assert gate("never").due() is False
    for seen in (0, 1, 5):
        assert gate("always", seen=seen).due() is True, seen
    for version in (1, 3):
        for seen in (0, 1, 3):
            assert gate("once", version=version, seen=seen).due() is (seen != version), \
                (version, seen)
    assert gate("once", seen=3, version=2).due() is True          # lower than stored: shown
    for show in ("once", "always"):
        assert gate(show, skip=True).due() is False               # start options
    assert gate("once", settings=None).due() is True              # no settings service
    # I-1: once asked, not due again this session (return to title, F39 reload).
    g = gate("always")
    assert g.due() is True and g.due() is False
    # I-3: session-only settings (W74, unreadable: nothing stored) show it; a newer file's
    # stored value counts, and Continue's value stays in memory (not written).
    assert gate("once", settings=service_from({}, Outcome.NO_FILE, writable=False)).due()
    newer = service_from({"warning_seen": 3}, Outcome.NEWER, writable=False)
    assert gate("once", version=3, settings=newer).due() is False
    g = gate("once", version=4, settings=newer)
    assert g.due() is True
    g.acknowledge()
    assert newer.value("warning_seen") == 4 and not newer.writable
    # acknowledge: "once" stores its version; "always" and "never" store nothing.
    for show, sets in (("once", [("warning_seen", 7)]), ("always", []), ("never", [])):
        fake = FakeSettings()
        WarningGate(ContentWarningConfig(show, "T", 7), lambda f=fake: f, skip=False) \
            .acknowledge()
        assert fake.sets == sets, show


# --- AC-F33-03 --------------------------------------------------------------------------------

def test_ac_f33_03_settings_key():
    assert FORMAT == 2 and list(KEYS)[-1] == "warning_seen"
    assert KEYS["warning_seen"] == IntKey(1, 1000, zero=True)
    for value in (0, 1, 1000):
        assert check("warning_seen", value) is None, value
    for value, found in ((1001, "1001"), (-1, "-1"), (True, "true"), ("1", "text")):
        problem = check("warning_seen", value)
        assert problem is not None and problem.found == found, value
        assert problem.must == "0 or a whole number from 1 to 1000"
    # W71 through the reader, and a format-1 file reads as current (and stays writable).
    loaded = parse_settings(b'{"format": 2, "values": {"warning_seen": 1001}}')
    assert [(p.key, p.found) for p in loaded.problems] == [("warning_seen", "1001")]
    loaded = parse_settings(b'{"format": 1, "values": {"warning_seen": 2, "mono": true}}')
    assert loaded.outcome is Outcome.OK and loaded.writable
    assert dict(loaded.values) == {"warning_seen": 2, "mono": True}
    assert b'"format": 2' in encode_settings({"warning_seen": 2})
    # Not on the Settings page; Reset clears it (so the warning shows at the next launch).
    assert "warning_seen" not in {row[1] for _, rows in GROUPS for row in rows}
    service = service_from({"warning_seen": 3, "music_volume": 40})
    assert service.value("warning_seen") == 3 and service.defaults["warning_seen"] == 0
    service.reset()
    assert service.value("warning_seen") == 0 and service.stored == {}


# --- AC-F33-09 --------------------------------------------------------------------------------

LONG = " ".join(f"word{i % 97:02d}" for i in range(250))[:1500]
SHORT = ("This game is not suitable for children or those who are easily disturbed. It "
         "contains scenes of self-harm and psychological horror. Please take care.")[:200]


@pytest.fixture
def fonts():
    pygame.font.init()
    yield
    pygame.font.quit()


def test_ac_f33_09_w193(caplog, fonts):
    assert len(LONG) == 1500 and len(SHORT) <= 200
    assets = make_assets(None)

    def run(show: str, text: str, *, dev: bool = True) -> list[str]:
        config = Config(content_warning=ContentWarningConfig(show, text))
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="vn.ui"):
            check_fit(config, plain_theme(config.theme), Words(config.words), assets, dev=dev)
        return [r.getMessage() for r in caplog.records if getattr(r, "code", "") == "W193"]

    config = Config(content_warning=ContentWarningConfig("once", LONG))
    layout = large_text_layout(config, plain_theme(config.theme), Words(config.words), assets)
    assert layout.overflow
    assert (layout.lines_needed, layout.lines_fit, layout.chars_fit) == (43, 5, 160)
    message = w193_text(43, 5, 160)
    assert message == ("config.toml: [content_warning] text needs 43 lines at 150% text size "
                       "but 5 fit, so players with large text must scroll to read it. About "
                       "160 characters fit without scrolling.")
    assert run("once", LONG) == [message]
    assert run("always", LONG) == [message]
    assert run("once", SHORT) == []
    assert run("once", LONG, dev=False) == []
    assert run("never", LONG) == []

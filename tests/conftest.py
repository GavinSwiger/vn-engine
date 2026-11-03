"""Shared pytest setup for the engine tests.

``display`` tests use pygame under SDL's dummy video driver, so they need no real screen
(04-technical.md §14.2). The driver is set before any test imports pygame, only if the
caller has not chosen one (set ``SDL_VIDEODRIVER`` yourself to run ``perf`` tests on a real
display).

``SDL_DIRECTINPUT_ENABLED=0`` skips SDL's DirectInput joystick scan on Windows, which costs
about 0.15 s on every ``pygame.init()`` (the engine uses no joysticks). Subprocess launches
inherit it. It roughly halves the F01 default run (test-review-F01.md).

``slow`` and ``perf`` tests anywhere under ``tests/`` are skipped unless ``VN_SLOW=1`` /
``VN_PERF=1`` is set or ``-m`` names the marker (pyproject markers; F02/F03 06 §0.3), so a
bare ``pytest`` and CI's ``-m "not perf and not manual"`` run neither (test-review-F02.md).
"""

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_DIRECTINPUT_ENABLED", "0")
# F08: no test needs a sound device. ``pygame.init()`` and F08's ``PygameMixer`` open SDL's
# dummy audio driver (subprocess launches inherit it); unit tests use ``FakeMixer``.
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


def pytest_collection_modifyitems(config, items):
    # Reference runs (AC-F04-48 is four 600 s runs) and human checks have no time limit.
    for item in items:
        if item.get_closest_marker("perf") or item.get_closest_marker("manual"):
            item.add_marker(pytest.mark.timeout(0))
    marks = config.getoption("-m") or ""
    for mark, env in (("slow", "VN_SLOW"), ("perf", "VN_PERF")):
        if os.environ.get(env) == "1" or mark in marks:
            continue
        skip = pytest.mark.skip(reason=f"{mark}: set {env}=1 or use -m {mark}")
        for item in items:
            # A real marker (also from ``pytest.param(marks=…)``), not ``item.keywords``,
            # which holds folder names such as ``perf``.
            if item.get_closest_marker(mark):
                item.add_marker(skip)


def pytest_sessionstart(session):
    """F31 AC-F31-07: remember the real ``game/characters/`` and ``game/files/``."""
    from tests.fakes import meta_guard

    session.config._meta_snapshot = meta_guard.snapshot()


def pytest_sessionfinish(session, exitstatus):
    """F31 AC-F31-07: fail the run if a test changed the real meta folders."""
    from tests.fakes import meta_guard

    before = getattr(session.config, "_meta_snapshot", None)
    if before is None or meta_guard.snapshot() == before:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line("F31 folder guard: a test changed game/characters/ or game/files/",
                            red=True)
    session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(autouse=True, scope="session")
def _meta_folder_guard():
    """F31 AC-F31-07: ``MetaFolder`` and writer clients never take the real
    ``game/characters`` as their root (``tests/fakes/meta_guard.py``)."""
    from tests.fakes import meta_guard

    patcher = pytest.MonkeyPatch()
    meta_guard.install(patcher)
    yield
    patcher.undo()


@pytest.fixture(autouse=True)
def _restore_installed_redactor():
    """Tests may install a redactor; put the previous one back afterwards."""
    from engine.core import redact

    saved = redact._installed, redact._session_term
    yield
    redact._installed, redact._session_term = saved


class UserRoots:
    """The per-user roots of 06-acceptance §0.5, all under ``tmp_path``. The home folder
    is the sentinel user ``qauser7``."""

    def __init__(self, tmp_path):
        self.home = tmp_path / "qauser7"
        self.appdata = self.home / "AppData" / "Roaming"
        self.localappdata = self.home / "AppData" / "Local"
        self.temp = tmp_path / "temp"
        for folder in (self.home, self.appdata, self.localappdata, self.temp):
            folder.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def user_roots(tmp_path, monkeypatch) -> UserRoots:
    """Point HOME, USERPROFILE, APPDATA, LOCALAPPDATA, TEMP, and TMP at folders under
    ``tmp_path`` (XDG_DATA_HOME unset), so nothing reaches the real profile."""
    roots = UserRoots(tmp_path)
    monkeypatch.setenv("HOME", str(roots.home))
    monkeypatch.setenv("USERPROFILE", str(roots.home))
    monkeypatch.setenv("APPDATA", str(roots.appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(roots.localappdata))
    monkeypatch.setenv("TEMP", str(roots.temp))
    monkeypatch.setenv("TMP", str(roots.temp))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return roots


@pytest.fixture(autouse=True)
def _close_log_setup():
    """A test that begins logging and fails midway must not leave handlers attached."""
    yield
    from engine.core import logsetup

    if logsetup._active is not None:
        logsetup._active.close()


class MessageBoxes(list):
    """The (title, text, kwargs) of every ``pygame.display.message_box`` call. Set
    ``error`` to make the next calls raise it."""

    error: BaseException | None = None


@pytest.fixture(autouse=True)
def message_boxes(monkeypatch) -> MessageBoxes:
    """``message_box`` is modal: on Windows SDL shows a real dialog even under the dummy
    driver, and a test would hang. Every test gets a recorder instead."""
    import pygame

    calls = MessageBoxes()

    def message_box(title, message=None, *args, **kwargs):
        calls.append((title, message, kwargs))
        if calls.error is not None:
            raise calls.error
        return 0

    monkeypatch.setattr(pygame.display, "message_box", message_box)
    return calls


@pytest.fixture
def scripted_app(monkeypatch):
    """An in-process ``launch()`` runs a few scripted frames and quits, with its window
    hidden (``tests/fakes/session.py``)."""
    from tests.fakes.session import scripted_session

    with scripted_session(monkeypatch) as session:
        yield session

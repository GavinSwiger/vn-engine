"""engine/app/platform.py: narrow, fail-safe OS queries (AC-F01-152, abuse G1–G3).

Mocked ``ctypes`` everywhere (``sys.platform`` patched to ``win32``); real calls on Windows.
"""

import ctypes
import logging
import re
import sys

import pytest

from engine.app import platform as osinfo

ENTRY = re.compile(r"^\d+x\d+ @ (\d+%|n/a)$")


class FakeFunction:
    """A foreign function that insists on declared argtypes/restype before any call."""

    def __init__(self, name, behavior):
        self.name = name
        self.behavior = behavior
        self.declared = set()
        self.calls = 0

    def __setattr__(self, key, value):
        if key in ("argtypes", "restype"):
            self.declared.add(key)
        object.__setattr__(self, key, value)

    def __call__(self, *args):
        assert self.declared == {"argtypes", "restype"}, f"{self.name} called undeclared"
        self.calls += 1
        return self.behavior(*args)


class FakeDll:
    def __init__(self, name, functions):
        self.name = name
        self.functions = {key: FakeFunction(key, value) for key, value in functions.items()}

    def __getattr__(self, name):
        try:
            return self.functions[name]
        except KeyError:
            raise AttributeError(name) from None


def _work_area(_action, _param, rect_ref, _flags):
    rect = rect_ref._obj
    rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1366, 728
    return 1


def _enum(_hdc, _clip, callback, _data):
    for handle in (1, 2):
        callback(handle, None, None, 0)
    return 1


def _monitor_info(handle, info_ref):
    info = info_ref._obj
    width = 2560 if handle == 1 else 1920
    height = 1440 if handle == 1 else 1080
    info.rcMonitor.left, info.rcMonitor.top = 0, 0
    info.rcMonitor.right, info.rcMonitor.bottom = width, height
    return 1


def _dpi_for_monitor(handle, _kind, dpi_x_ref, dpi_y_ref):
    dpi_x_ref._obj.value = 144 if handle == 1 else 96
    dpi_y_ref._obj.value = dpi_x_ref._obj.value
    return 0


class Mocks:
    def __init__(self):
        self.loads = []
        self.user32 = {"GetDpiForSystem": lambda: 144, "SystemParametersInfoW": _work_area,
                       "EnumDisplayMonitors": _enum, "GetMonitorInfoW": _monitor_info}
        self.shcore = {"GetDpiForMonitor": _dpi_for_monitor}
        self.shcore_error = False
        self.dlls = []

    def win_dll(self, name, *args, **kwargs):
        self.loads.append((name, args, kwargs))
        if name == "shcore" and self.shcore_error:
            raise OSError("cannot load")
        dll = FakeDll(name, self.user32 if name == "user32" else self.shcore)
        self.dlls.append(dll)
        return dll


class WindllSpy:
    accessed = False

    def __getattr__(self, name):
        WindllSpy.accessed = True
        raise AssertionError("ctypes.windll must never be used")


@pytest.fixture
def mocks(monkeypatch):
    mocks = Mocks()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", mocks.win_dll, raising=False)
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: pytest.fail("CDLL used"))
    monkeypatch.setattr(ctypes, "windll", WindllSpy(), raising=False)
    if not hasattr(ctypes, "WINFUNCTYPE"):
        monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)
    monkeypatch.setattr(osinfo, "_noted", set())
    WindllSpy.accessed = False
    return mocks


def _assert_narrow_loads(mocks):
    assert mocks.loads
    for name, args, kwargs in mocks.loads:
        assert name in ("user32", "shcore")
        assert kwargs == {"winmode": 0x00000800} and args == ()
    assert not WindllSpy.accessed


def test_results_from_the_windows_calls(mocks):
    assert osinfo.system_display_scale() == 1.5
    assert osinfo.primary_work_area() == (1366, 728)
    assert osinfo.displays_info() == ["2560x1440 @ 150%", "1920x1080 @ 100%"]
    _assert_narrow_loads(mocks)
    used = [fn for dll in mocks.dlls for fn in dll.functions.values() if fn.calls]
    assert {fn.name for fn in used} == {"GetDpiForSystem", "SystemParametersInfoW",
                                        "EnumDisplayMonitors", "GetMonitorInfoW",
                                        "GetDpiForMonitor"}


def test_failures_give_neutral_defaults_with_one_debug_line_each(mocks, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="vn")
    del mocks.user32["GetDpiForSystem"]                    # AttributeError
    mocks.user32["SystemParametersInfoW"] = lambda *args: 0
    mocks.shcore_error = True
    monkeypatch.setattr(osinfo, "_desktop_sizes", lambda: [(1920, 1080)])
    for _ in range(3):
        assert osinfo.system_display_scale() == 1.0
        assert osinfo.primary_work_area() is None
        entries = osinfo.displays_info()
        assert entries and all(entry.endswith("@ n/a") for entry in entries)
    debug = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(debug) == len(set(debug)) == 3
    assert all(r.levelno == logging.DEBUG for r in caplog.records)
    _assert_narrow_loads(mocks)


def test_zero_dpi_and_a_failing_user32_load(mocks, monkeypatch):
    mocks.user32["GetDpiForSystem"] = lambda: 0
    assert osinfo.system_display_scale() == 1.0

    def no_dll(*args, **kwargs):
        raise OSError("blocked")

    monkeypatch.setattr(ctypes, "WinDLL", no_dll)
    monkeypatch.setattr(osinfo, "_desktop_sizes", lambda: [(1280, 800)])
    assert osinfo.system_display_scale() == 1.0
    assert osinfo.primary_work_area() is None
    assert osinfo.displays_info() == ["1280x800 @ n/a"]


def test_other_platforms_never_touch_ctypes(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: pytest.fail("WinDLL used"),
                        raising=False)
    monkeypatch.setattr(osinfo, "_desktop_sizes", lambda: [(1920, 1080), (1280, 1024)])
    assert osinfo.system_display_scale() == 1.0
    assert osinfo.primary_work_area() is None
    assert osinfo.displays_info() == ["1920x1080 @ n/a", "1280x1024 @ n/a"]


def test_os_description_has_no_host_or_user_name():
    import getpass
    import socket
    text = osinfo.os_description()
    assert text
    assert socket.gethostname().lower() not in text.lower()
    assert getpass.getuser().lower() not in text.lower()


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows API calls")
def test_real_windows_calls():
    assert osinfo.system_display_scale() >= 1.0
    work = osinfo.primary_work_area()
    assert work is not None and work[0] > 0 and work[1] > 0
    entries = osinfo.displays_info()
    assert entries and all(ENTRY.match(entry) for entry in entries)
    assert not any(entry.endswith("n/a") for entry in entries)

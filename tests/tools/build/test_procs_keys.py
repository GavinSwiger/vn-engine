"""F48 step S1: provider key variables never reach a child (SEC-F48-22; 07 I-4; 04 §3.3).
``procs.child_env`` and ``procs.without_keys`` drop ``PROVIDER_KEY_VARS`` in any letter
case, and Studio's check, preview and helper children get an environment without them."""

import os
import time
from pathlib import Path

import pytest

from engine.tools.build import procs
from engine.tools.editor.checker import CheckRunner
from engine.tools.editor.helperrunner import HelperRunner
from engine.tools.editor.preview import PreviewRunner

KEY = "sk-ant-api03-" + "k" * 40


def test_provider_key_vars():
    assert procs.PROVIDER_KEY_VARS == {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}


def test_without_keys_and_child_env_drop_the_keys_in_any_case():
    base = {"ANTHROPIC_API_KEY": KEY, "openai_api_key": KEY, "Anthropic_Api_Key": KEY,
            "PYTHONPATH": "x", "PATH": "/bin", "ANTHROPIC_API_KEY_X": "kept",
            "MY_OPENAI_API_KEY": "kept"}
    assert procs.without_keys(base) == {"PYTHONPATH": "x", "PATH": "/bin",
                                        "ANTHROPIC_API_KEY_X": "kept",
                                        "MY_OPENAI_API_KEY": "kept"}
    assert procs.child_env(base) == {"PATH": "/bin", "ANTHROPIC_API_KEY_X": "kept",
                                     "MY_OPENAI_API_KEY": "kept"}
    assert base["ANTHROPIC_API_KEY"] == KEY                     # a copy; base unchanged


@pytest.fixture
def keyed_environ(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.setenv("VN_F48_KEPT", "1")


def _assert_keyless(env: dict[str, str]) -> None:
    assert env["VN_F48_KEPT"] == "1"
    assert not {k.upper() for k in env} & procs.PROVIDER_KEY_VARS
    assert KEY not in env.values()


def test_build_spawn_has_no_keys(keyed_environ):
    calls = []
    procs.spawn(["python", "-E", "x"], popen=lambda argv, **kw: calls.append(kw))
    _assert_keyless(calls[0]["env"])


def _record(seen: list[dict]):
    def popen(argv, **kwargs):
        seen.append(kwargs)
        raise OSError(2, "No such file")
    return popen


def _poll_until(runner, seen: list[dict]) -> None:
    deadline = time.monotonic() + 5
    while not seen and time.monotonic() < deadline:
        runner.poll()
        time.sleep(0.01)
    assert seen


def test_studio_children_have_no_keys(keyed_environ, tmp_path):
    """Check, preview and helper children (SEC-F48-22): ``without_keys`` env; ``PYTHON*``
    variables they set stay."""
    checked: list[dict] = []
    check = CheckRunner(Path("game"), popen=_record(checked))
    check.request(None, 1, launch=False)
    _poll_until(check, checked)

    previewed: list[dict] = []
    preview = PreviewRunner(popen=_record(previewed))
    preview.start(["x"])
    preview.poll()

    helped: list[dict] = []
    helper = HelperRunner(tmp_path, popen=_record(helped))
    helper.still("textbox", 640, None)
    _poll_until(helper, helped)
    helper.stop()

    for kwargs in (checked[0], previewed[0], helped[0]):
        _assert_keyless(kwargs["env"])
        assert kwargs["env"]["PYTHONIOENCODING"]
    assert os.environ["ANTHROPIC_API_KEY"] == KEY               # Studio's own env unchanged

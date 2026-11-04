"""F48 step S7: per-user assistant settings and consent (04 §7.5, §10; 05 SEC-F48-17,
-21; ADR-0003): AC-F48-36 (AB-18) and the consent store AC-F48-32 relies on."""

import json
import os
from pathlib import Path

import pytest

from engine.core import paths, safefile
from engine.tools.assistant import keystore as ks
from engine.tools.assistant import prefs as pf

ANT_ORIGIN = ks.FIXED_ORIGINS[ks.ANTHROPIC]


@pytest.fixture
def user_dir(tmp_path, monkeypatch) -> Path:
    """``studio_user_dir()`` under ``tmp_path`` (roaming base = ``APPDATA``/XDG/home)."""
    monkeypatch.setattr(paths, "_data_base", lambda *, windows_var="APPDATA":
                        tmp_path / windows_var)
    folder = paths.studio_user_dir()
    assert folder is not None
    return folder


def write(folder: Path, data) -> None:
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    (folder / pf.PREFS_NAME).write_bytes(raw)


def test_defaults_and_a_round_trip(user_dir):
    assert pf.load() == pf.Prefs()
    prefs = pf.Prefs()
    assert prefs.provider == "anthropic" and prefs.model() == "claude-sonnet-5-5"
    assert prefs.steps == 12 and prefs.token_limit == 500_000
    assert prefs.address == "http://localhost:11434/v1"
    changed = pf.Prefs(provider=ks.COMPATIBLE, address="http://localhost:1234/v1",
                       steps=50, token_limit=10_000).with_model(ks.COMPATIBLE, "qwen2.5:7b")
    changed = changed.with_env(ks.OPENAI, True)
    assert pf.save(changed)
    assert pf.load() == changed and pf.load(user_dir) == changed
    assert [p.name for p in user_dir.iterdir()] == [pf.PREFS_NAME]          # no temp left
    with pytest.raises(ValueError):
        changed.with_env(ks.COMPATIBLE, True)
    with pytest.raises(ValueError):
        changed.with_model("gemini", "x")


def test_consent_is_per_provider_and_origin(user_dir):
    assert not pf.load().consented(ks.ANTHROPIC, ANT_ORIGIN)
    granted = pf.grant_consent(ks.ANTHROPIC, ANT_ORIGIN)
    assert granted.consented(ks.ANTHROPIC, ANT_ORIGIN)
    again = pf.load()
    assert again.consented(ks.ANTHROPIC, ANT_ORIGIN)
    assert not again.consented(ks.OPENAI, ANT_ORIGIN)
    assert not again.consented(ks.COMPATIBLE, "http://localhost:11434")
    local = pf.grant_consent(ks.COMPATIBLE, "http://localhost:11434")
    assert local.consented(ks.COMPATIBLE, "http://localhost:11434")
    assert not local.consented(ks.COMPATIBLE, "http://localhost:1234")
    many = pf.Prefs()
    for port in range(1000, 1000 + pf.CONSENT_MAX + 5):
        many = many.with_consent(ks.COMPATIBLE, f"http://localhost:{port}")
    assert len(many.consent) == pf.CONSENT_MAX
    assert many.consented(ks.COMPATIBLE, f"http://localhost:{1000 + pf.CONSENT_MAX + 4}")
    assert not many.consented(ks.COMPATIBLE, "http://localhost:1000")
    with pytest.raises(ValueError):
        many.with_consent(ks.ANTHROPIC, "not an origin")


# --- AC-F48-36 (AB-18) --------------------------------------------------------------------------

def test_ac_f48_36_a_game_folder_can_not_set_anything(user_dir, tmp_path):
    game = tmp_path / "game"
    (game / ".studio").mkdir(parents=True)
    planted = {"v": 1, "provider": "compatible", "address": "http://evil:80/v1",
               "models": {"compatible": "evil"}, "consent": [["compatible", "http://evil:80"]]}
    (game / ".studio" / "assistant.json").write_text(json.dumps(planted), encoding="utf-8")
    (game / "config.toml").write_text('[assistant]\nprovider = "compatible"\n'
                                      'base_url = "http://evil"\napi_key = "sk-ant-planted"\n',
                                      encoding="utf-8")
    old = os.getcwd()
    os.chdir(game)
    try:
        assert pf.load() == pf.Prefs()
    finally:
        os.chdir(old)
    # A key saved for one origin is never found for another (SEC-F48-16).
    assert ks.slot_for(ks.COMPATIBLE, "http://evil:80") != ks.slot_for(
        ks.COMPATIBLE, "http://localhost:11434")


@pytest.mark.parametrize("data", [
    b"{" + b" " * (10 * 1024 * 1024) + b"}",                               # 10 MB
    b"\xff\xfe not json", b"[]", b"null", b'{"v": 2, "provider": "openai"}',
    b'{"v": "1", "provider": "openai"}', b'{"v": true, "provider": "openai"}',
    b'{"v": 1, "provider": "openai", "provider": "compatible"}',            # duplicate key
    b"[" * 100_000,
], ids=["10MB", "bytes", "list", "null", "newer", "v-text", "v-bool", "duplicate", "deep"])
def test_ac_f48_36_a_bad_or_newer_file_gives_defaults_and_is_left_alone(data, user_dir):
    write(user_dir, data)
    assert pf.load() == pf.Prefs()
    assert (user_dir / pf.PREFS_NAME).read_bytes() == data                  # not rewritten


def test_ac_f48_36_wrong_types_take_each_fields_default(user_dir):
    write(user_dir, {"v": 1, "provider": "evil", "base_url": "http://evil",
                     "models": {"anthropic": "bad model\nX-Evil: 1", "openai": 5,
                                "evil": "x", "compatible": "llama3.1:8b"},
                     "address": "http://local‮host:11434", "steps": 51,
                     "token_limit": True, "consent": [["anthropic", ANT_ORIGIN],
                                                      ["evil", "http://x:1"], "junk",
                                                      ["openai", "not an origin"]],
                     "env": ["compatible", "openai", 3]})
    loaded = pf.load()
    assert loaded.provider == "anthropic" and loaded.address == pf.DEFAULT_ADDRESS
    assert loaded.model(ks.ANTHROPIC) == "claude-sonnet-5-5"
    assert loaded.model(ks.OPENAI) == pf.DEFAULT_MODELS[ks.OPENAI]
    assert loaded.model(ks.COMPATIBLE) == "llama3.1:8b" and "evil" not in loaded.models
    assert loaded.steps == 12 and loaded.token_limit == 500_000
    assert loaded.consent == (("anthropic", ANT_ORIGIN),) and loaded.env == frozenset()
    write(user_dir, {"v": 1, "steps": 0, "token_limit": 9_999, "address": 7})
    assert pf.load() == pf.Prefs()
    write(user_dir, {"v": 1, "steps": 1, "token_limit": 10_000_000, "env": ["openai"]})
    assert (pf.load().steps, pf.load().token_limit, pf.load().env) == (1, 10_000_000,
                                                                      {"openai"})


def test_ac_f48_36_links_are_never_followed_and_no_folder_saves_nothing(user_dir, tmp_path,
                                                                        monkeypatch):
    from tests.core.test_safefile import link_dir

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link_dir(user_dir / pf.PREFS_NAME, elsewhere)
    assert pf.load() == pf.Prefs()
    assert not pf.save(pf.Prefs(steps=3)) or not os.listdir(elsewhere)
    monkeypatch.setattr(paths, "_data_base", lambda *, windows_var="APPDATA": None)
    assert pf.load() == pf.Prefs() and pf.save(pf.Prefs()) is False


def test_a_stale_temp_is_removed_when_the_folder_is_opened(user_dir):
    stale = user_dir / safefile.temp_name(pf.PREFS_NAME, "0123abcd")
    stale.write_bytes(b"{}")
    old = stale.stat().st_mtime - 3600
    os.utime(stale, (old, old))
    assert paths.studio_user_dir() == user_dir
    assert not stale.exists()

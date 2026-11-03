"""File ▸ Open game… and Help ▸ Guides (user feedback 2026-11-03): an existing game opens in
its own Studio, a folder that isn't a game is refused with what to choose instead, and every
guide the Help menu names is a page in ``docs/``."""
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("tkinter")

from engine.tools.editor import fileactions, guides  # noqa: E402

REPO = Path(__file__).resolve().parents[3]


def _open(monkeypatch, current: Path, picked: Path | None) -> tuple[list, list]:
    launched: list = []
    errors: list = []
    monkeypatch.setattr(fileactions, "ask_game_folder", lambda _root: picked)
    monkeypatch.setattr(fileactions, "launch_studio", launched.append)
    monkeypatch.setattr(fileactions, "show_error", lambda _root, text: errors.append(text))
    window = SimpleNamespace(closed=False, root=None, paths=SimpleNamespace(root=current))
    fileactions.FileActions.open_game(window)
    return launched, errors


def _game(folder: Path) -> Path:
    (folder / "script").mkdir(parents=True)
    (folder / "script" / "main.vns").write_text('label start:\n    "Hi."\n', encoding="utf-8")
    return folder


def test_open_game_launches_another_game(tmp_path, monkeypatch):
    other = _game(tmp_path / "other")
    launched, errors = _open(monkeypatch, _game(tmp_path / "here"), other)
    assert launched == [other] and errors == []


def test_open_game_refuses_a_folder_without_a_script_folder(tmp_path, monkeypatch):
    plain = tmp_path / "Pictures"
    plain.mkdir()
    launched, errors = _open(monkeypatch, _game(tmp_path / "here"), plain)
    assert launched == []
    assert errors == [fileactions.OPEN_NOT_GAME.format(name="Pictures")]
    assert "File ▸ New game…" in errors[0]


def test_open_game_ignores_cancel_and_the_game_already_open(tmp_path, monkeypatch):
    here = _game(tmp_path / "here")
    assert _open(monkeypatch, here, None) == ([], [])
    assert _open(monkeypatch, here, here) == ([], [])


def test_every_guide_is_a_docs_page_and_opens(monkeypatch):
    opened: list[Path] = []
    monkeypatch.setattr(guides, "open_path", opened.append)
    for title, name in guides.GUIDES:
        assert (REPO / "docs" / name).is_file(), name
        assert guides.open_guide(title, name) is None
    assert [p.name for p in opened] == [name for _t, name in guides.GUIDES]


def test_a_missing_guide_or_viewer_says_what_to_do(monkeypatch):
    assert guides.open_guide("Nope", "nope.md") == guides.GUIDE_MISSING.format(title="Nope")

    def no_viewer(_path):
        raise OSError("no app for .md")

    monkeypatch.setattr(guides, "open_path", no_viewer)
    assert "docs/script-language.md" in guides.open_guide("Script language",
                                                          "script-language.md")


def test_example_story_points_at_the_guides_menu():
    main = (REPO / "game" / "script" / "main.vns").read_text(encoding="utf-8")
    assert "Help ▸ Guides ▸ Script language" in main
    labels = {title for title, _name in guides.GUIDES}
    assert {"Script language", "Minigames"} <= labels

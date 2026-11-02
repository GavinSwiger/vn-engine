"""``install_history``: F13's history page wired into one launch (F13 ``SPEC.md`` §5;
``07-architecture-review.md`` I-4, I-6).

Why this module exists: ``ui`` never imports ``engine.app`` or reads the interpreter, so the
page gets its data as ``HistoryPorts``: the live ``interp.history`` entries (a pick made
before an F09 wait shows), each entry's voice file (``runtime.history.voice_of`` over the
current ``Program``, the same field ``run_menu`` uses for a question's ``PlayVoice``), and
F08's ``App.audio`` (None: no voice icons and no replay). It registers the game menu's
History page and the quick menu's History (``register_history``); the title has none.

``install_story`` calls it once per launch (windowed only), after ``install_ui`` and before
``shell.check_entries()`` (I-6). This module never imports ``engine.script`` (I-4).
"""

from typing import TYPE_CHECKING

from engine.runtime.history import voice_of
from engine.ui.builtin.history_page import HistoryPorts, register_history

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.history import HistoryEntry


def install_history(app: "App") -> HistoryPorts:
    """Register F13's entries on ``app.shell`` (set by ``install_ui``) and return the ports."""
    shell = app.shell
    assert shell is not None, "install_history runs after install_ui"
    story = app.story

    def entries() -> "tuple[HistoryEntry, ...]":
        return story.interp.history.entries              # type: ignore[union-attr]

    def voice_for(sid: str) -> str | None:
        return voice_of(story.interp.program, sid)        # type: ignore[union-attr]

    ports = HistoryPorts(entries, voice_for, getattr(app, "audio", None))
    register_history(shell, ports)
    return ports


__all__ = ["install_history"]

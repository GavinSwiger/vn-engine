"""F33's content warning on the App side: whether it is due, its "seen" record, and W193
(F33 ``SPEC.md`` PR-F33-02, 03, 05; ``07-architecture-review.md`` I-1, I-3, I-5, I-6).

Why this module exists: the shell (``ui``) never imports ``engine.app``, so the decision
"show the warning now?" and the write of F16's ``warning_seen`` reach it as one port,
``ShellPorts.content_warning`` (``ui/shell.py: WarningPort``), built here by
``install_ui``.

- **Due** (``WarningGate.due``), asked once per session (I-1: after the first call it is
  False for the rest of the session, so a return to the title or F39's reload never shows
  it again): ``"never"`` → no; F44 start options (``--start``, ``--set``: Studio's "play
  from here") → no; ``"always"`` → yes; ``"once"`` → yes unless the player's settings hold
  ``warning_seen == version`` (``!=``, so a lowered version shows it too). Without a
  settings service (a fake App) a "once" warning shows. The service is read at call time
  (``App.settings``); a session-only one (W74, an unreadable file) holds nothing, so the
  warning shows; a newer file (W73) still gives its stored value (I-3).
- **Acknowledge** (Continue): ``settings.set("warning_seen", version)`` for ``"once"`` only
  (I-6); F16's debounce writes the file. Quit and closing the window store nothing.
- **W193** (``check_fit``, dev runs, area ``ui``, from ``install_ui``): the warning's text
  needs scrolling at the largest text size (Text size 150%), measured with the same
  ``warning_layout`` the screen uses (I-5).
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from engine.core.logsetup import get_logger
from engine.core.settings_schema import effective_text_size
from engine.ui.builtin.content_warning import LARGE_TEXT_PCT, WarningLayout, \
    themed_warning_layout

if TYPE_CHECKING:
    from engine.core.config_schema import Config, ContentWarningConfig
    from engine.render.assets import AssetManager
    from engine.ui.theme import UiTheme, Words

SEEN_KEY = "warning_seen"


class SettingsLike(Protocol):
    """What the gate uses of F16's ``SettingsService``."""

    def value(self, key: str) -> object: ...

    def set(self, key: str, value: int) -> None: ...


class WarningGate:
    """``ShellPorts.content_warning`` (``WarningPort``): ``due()`` and ``acknowledge()``.
    ``settings()`` returns ``App.settings`` (or None) when called; ``skip`` is True in a
    run with start options."""

    def __init__(self, config: "ContentWarningConfig",
                 settings: Callable[[], SettingsLike | None], *, skip: bool) -> None:
        self.config = config
        self._settings = settings
        self.skip = skip
        self.checked = False

    def due(self) -> bool:
        """PR-F33-02, 03: True at most once per session (I-1)."""
        if self.checked:
            return False
        self.checked = True
        show = self.config.show
        if show == "never" or self.skip:
            return False
        if show == "always":
            return True
        settings = self._settings()
        if settings is None:
            return True
        return settings.value(SEEN_KEY) != self.config.version

    def acknowledge(self) -> None:
        """Continue: a "once" warning stores its ``version`` (``"always"`` stores nothing)."""
        if self.config.show != "once":
            return
        settings = self._settings()
        if settings is not None:
            settings.set(SEEN_KEY, self.config.version)


# --- W193 (PR-F33-05) -------------------------------------------------------------------------

def w193_text(needed: int, fit: int, chars: int) -> str:
    """W193 (SPEC §3; drafted by the F33 designer, for vn-narrative-designer)."""
    return (f"config.toml: [content_warning] text needs {needed} lines at 150% text size but "
            f"{fit} fit, so players with large text must scroll to read it. About {chars} "
            "characters fit without scrolling.")


def large_text_scale(config: "Config") -> float:
    """The menus' text scale at Text size 150% (F16: the effective textbox size ÷ its
    base, as ``install_settings_ui`` sets it)."""
    base = config.theme.textbox.text_size
    return effective_text_size(base, LARGE_TEXT_PCT) / base


def large_text_layout(config: "Config", theme: "UiTheme", words: "Words",
                      assets: "AssetManager") -> WarningLayout:
    """The warning's layout at Text size 150% (W193, AC-F33-09)."""
    return themed_warning_layout(config.content_warning.text, theme, words, assets,
                                 scale=large_text_scale(config))


def check_fit(config: "Config", theme: "UiTheme", words: "Words", assets: "AssetManager", *,
              dev: bool, log: logging.Logger | None = None) -> bool:
    """W193 in a dev run with a warning that can show, when its text overflows the panel at
    150%. True when it was logged."""
    if not dev or config.content_warning.show == "never":
        return False
    layout = large_text_layout(config, theme, words, assets)
    if not layout.overflow:
        return False
    log = log if log is not None else get_logger("ui")
    log.warning("%s", w193_text(layout.lines_needed, layout.lines_fit, layout.chars_fit),
                extra={"code": "W193"})
    return True


__all__ = ["SEEN_KEY", "SettingsLike", "WarningGate", "check_fit", "large_text_layout",
           "large_text_scale", "w193_text"]

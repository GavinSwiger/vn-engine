"""The player's settings in the App: the launch read, ``SettingsService`` (``App.settings``),
its writes, and the window size kept across launches (F16 ``04-technical.md`` §5.2, §7.1,
§7.2, §7.3, §7.5, §7.6, §7.8; ``07`` §3, G3, G9, G10, I-11, I-13, I-14; checklist steps 2
and 3).

Why this module exists: settings are the player's, not the story's. They must be in place
before the window opens (fullscreen and size, bootstrap steps 12–13) and before the first
frame, survive a relaunch, and never stall a frame or stop the game when the file is
damaged or can't be written (PR-F16-12, 13, 20–24).

- **Launch** (bootstrap step 10b, after the log opens, before the window size is chosen):
  ``launch_settings`` reads ``settings.json`` once (``persist/settings_file.py``) and logs
  W70–W75 in the design's order. A release run without ``[game] id`` (W74), no usable
  folder (W75), a linked folder (W75; nothing read, G10), an unreadable file (W70), or a
  newer file (W73) keeps settings for the session only.
- **Precedence** (§7.2): ``value(key)`` is the player's stored value, else the config
  default. ``stored`` holds only the keys the player changed; setting a key back to its
  default removes it, so the setting follows ``config.toml`` again (TR-F16-04).
- **Applying** (§5.5, §7.3): each key belongs to one target group, pushed once per change
  with the current effective values: the window (``set_fullscreen``), F08's audio
  (``set_volumes``, ``set_background``, ``set_voice_sustain``, ``set_mono``), F05's
  ``TextSettings``, F09's ``EffectSettings`` (``drop_effects()`` when the effective reduce
  turns on, never at attach: G9), F06's blips (``set_enabled``), and F15's
  ``SkipAutoSettings``. ``attach_audio`` (bootstrap step 17, before any sound) and
  ``attach_story`` (``install_settings_ui``, I-11) push every group once. A target that
  doesn't exist (headless, a fake App) is skipped; ``stored`` still changes.
- **Writing** (§7.5): ``update(now)`` runs in the App's frame slot (every mode, minimized
  wakes included, I-14). It polls ``window.fullscreen`` (F11, Alt+Enter, and the OS count
  as player changes), takes the writer's results, and submits a ``FileWrite`` to
  ``App.writer`` (owner ``settings``) 0.5 s after the last change, or after 5 s of
  continuous change, with at most one write in flight. A failure logs W75 once per
  session and is retried only at the next change.
- **Quit** (§7.6, §7.8, ``07`` §3): ``submit_final`` stores the windowed size (in requested
  units, step 12's display scale) and submits a pending write without waiting;
  ``wait_final(until)`` waits on the one writer deadline (W75 ``couldn't write`` past it).

Headless runs build no service (``App.settings`` stays None). This module never reads the
file's text into a message: warnings name the file by its display path and give fixed
words or ``found_word`` values only (TR-F16-03).
"""

import logging
import math
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from engine.core.logsetup import get_logger
from engine.core.settings_schema import KEYS, SizeKey, Value, check, effective_text_size
from engine.persist.settings_file import (
    BAD_NAME,
    FILE_NAME,
    LOG_AREA,
    NO_PERMISSION,
    LoadedSettings,
    Outcome,
    display_file,
    encode_settings,
    read_settings,
    settings_root,
)
from engine.persist.sync import READ_ONLY
from engine.persist.writer import COULDNT_WRITE, SETTINGS, Failed, FileWrite, FileWritten

if TYPE_CHECKING:
    from engine.core.config_schema import Config
    from engine.persist.writer import Writer, WriterClient
    from engine.render.window import WindowPort
    from engine.ui.builtin.skip_auto import SkipAutoSettings
    from engine.ui.builtin.textbox_screen import TextSettings

WRITE_QUIET_S: Final = 0.5          # a write 0.5 s after the last change (PR-F16-20)
WRITE_MAX_DIRTY_S: Final = 5.0      # ...or after 5 s of continuous change
NAMES: Final = frozenset({FILE_NAME})

# --- Texts (design §5, 07 G3, G7, I-13; area ``setting``) ---------------------------------------

SAVED_AGAIN_TEXT: Final = "settings saved again"
NOTICE_TEXT: Final = "Your settings couldn't be read, so the defaults are used."   # I-13
NO_ID_TEXT: Final = ("settings won't be saved, because config.toml has no [game] id. Set a "
                     'unique id under [game], e.g. id = "paper-lanterns", before releasing.')
FALLBACK_FILE: Final = FILE_NAME    # <file> when there is no folder (W75 "no permission")


def bad_file_text(file: str, reason: str, *, kept: bool, unreadable: bool = False) -> str:
    """W70. ``kept``: the entry was moved to ``settings.bad.json``. Without a copy (07 G3):
    an unreadable file is left alone and not written this session; a damaged file whose
    rename failed is replaced at the next change."""
    start = f"settings in {file} couldn't be used ({reason}), so the default settings are used."
    if kept:
        return f"{start} The old file was kept as {BAD_NAME}."
    if unreadable:
        return f"{start} The file was left unchanged and won't be changed this session."
    return f"{start} The file will be replaced when a setting changes."


def bad_value_text(file: str, key: str, must: str, found: str) -> str:
    """W71."""
    return (f"settings in {file}: {key} must be {must}, but found {found}, so the default "
            "is used.")


def unknown_keys_text(file: str, count: int) -> str:
    """W72 (07 G7's singular form)."""
    if count == 1:
        return f"settings in {file} had 1 unknown entry; it was ignored."
    return f"settings in {file} had {count} unknown entries; they were ignored."


def newer_file_text(file: str) -> str:
    """W73."""
    return (f"settings in {file} were made by a newer engine version, so only the settings "
            "this version knows are used, and the file won't be changed this session.")


def save_failed_text(file: str, reason: str) -> str:
    """W75 (reasons as W52: ``no permission``, ``disk full``, ``the folder is a link``,
    ``couldn't write``)."""
    return (f"settings couldn't be saved to {file} ({reason}). Changes apply this session "
            "and are tried again at the next change.")


def _logger() -> logging.Logger:
    return get_logger(LOG_AREA)


# --- Launch (bootstrap step 10b, 04 §7.1) --------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SettingsLaunch:
    """Step 10b's result: the read, ``<file>`` for messages, and the W70 notice (I-13)."""

    loaded: LoadedSettings
    file: str
    notices: tuple[str, ...] = ()

    @classmethod
    def skipped(cls) -> "SettingsLaunch":
        """Nothing read: defaults, session only."""
        return cls(LoadedSettings.no_file(), FALLBACK_FILE)


def launch_settings(*, game_root: Path | None, release: bool, app_id: str | None,
                    id_is_fallback: bool, skip: bool = False,
                    log: logging.Logger | None = None) -> SettingsLaunch:
    """§7.1: read ``settings.json`` once and log W70–W75. ``skip`` (a fatal startup error,
    or no game folder) reads nothing and logs nothing. Never raises ``OSError``."""
    log = log if log is not None else _logger()
    if skip or (game_root is None and not release):
        return SettingsLaunch.skipped()
    if release and (id_is_fallback or app_id is None):
        log.warning("%s", NO_ID_TEXT, extra={"code": "W74"})          # step 1: no file call
        return SettingsLaunch.skipped()
    folder = settings_root(game_root=game_root, release=release,      # type: ignore[arg-type]
                           app_id=app_id)
    if folder is None:                                                 # step 2
        log.warning("%s", save_failed_text(FALLBACK_FILE, NO_PERMISSION),
                    extra={"code": "W75"})
        return SettingsLaunch(LoadedSettings.no_file(NO_PERMISSION), FALLBACK_FILE)
    file = display_file(folder, game_root=game_root)
    loaded = read_settings(folder, release=release)                    # steps 3-7
    return SettingsLaunch(loaded, file, log_launch(loaded, file, log))


def log_launch(loaded: LoadedSettings, file: str, log: logging.Logger) -> tuple[str, ...]:
    """§7.1 step 8: W70 or W73 (or W75 for a linked folder), then W71 in ``KEYS`` order,
    then W72. Returns the notices (I-13: one for W70)."""
    notices: list[str] = []
    outcome = loaded.outcome
    if outcome is Outcome.BAD or outcome is Outcome.UNREADABLE:
        text = bad_file_text(file, loaded.bad_reason or "", kept=loaded.quarantined,
                             unreadable=outcome is Outcome.UNREADABLE)
        log.warning("%s", text, extra={"code": "W70"})
        notices.append(NOTICE_TEXT)
    elif outcome is Outcome.NEWER:
        log.warning("%s", newer_file_text(file), extra={"code": "W73"})
    elif outcome is Outcome.NO_FILE and loaded.bad_reason is not None:
        log.warning("%s", save_failed_text(file, loaded.bad_reason), extra={"code": "W75"})
    for problem in loaded.problems:
        log.warning("%s", bad_value_text(file, problem.key, problem.must, problem.found),
                    extra={"code": "W71"})
    if loaded.unknown:
        log.warning("%s", unknown_keys_text(file, loaded.unknown), extra={"code": "W72"})
    return tuple(notices)


def config_defaults(config: "Config") -> dict[str, Value]:
    """§7.2: every key's default, built from ``config.toml`` (stored → config → engine)."""
    window = config.window
    audio = config.audio
    return {
        "text_cps": config.textbox.cps,
        "text_size_pct": 100,
        "auto_scale_pct": 100,
        "auto_wait_voice": config.auto.wait_for_voice,
        "skip_all": config.skip.all,
        "master_volume": audio.master_volume,
        "music_volume": audio.music_volume,
        "sound_volume": audio.sound_volume,
        "voice_volume": audio.voice_volume,
        "text_blips": True,
        "voice_sustain": False,
        "audio_unfocused": audio.play_unfocused,
        "audio_minimized": audio.play_minimized,
        "mono": False,
        "fullscreen": window.fullscreen,
        "reduce_motion": False,
        "window_size": (window.width, window.height),
        "warning_seen": 0,          # F33: no apply group, not on the page; Reset clears it
    }


def effects_reduce(config: "Config") -> bool:
    """``[effects] reduce``, the config half of the effective reduce (F09 07 I-6); F09's
    ``StageScreen.settings`` starts from it (``install_stage``). A config stand-in without
    the section reads False."""
    return bool(getattr(getattr(config, "effects", None), "reduce", False))


def launch_value(loaded: LoadedSettings, config: "Config", key: str) -> Value:
    """A key's effective value before the service exists (steps 12–13)."""
    if key in loaded.values:
        return loaded.values[key]
    return config_defaults(config)[key]


def round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def requested_size(window_size: tuple[int, int], display_scale: float) -> tuple[int, int]:
    """§7.6: a window size (window units) in requested units (÷ step 12's display scale,
    rounded half up), clamped to ``window_size``'s ranges."""
    spec = KEYS["window_size"]
    assert isinstance(spec, SizeKey)
    scale = display_scale if display_scale > 0 else 1.0
    w = min(max(round_half_up(window_size[0] / scale), spec.w[0]), spec.w[1])
    h = min(max(round_half_up(window_size[1] / scale), spec.h[0]), spec.h[1])
    return w, h


# --- The service ---------------------------------------------------------------------------------

Listener = Callable[[frozenset[str]], None]

# §7.3: each key's target group (``window_size`` has none: next launch only).
VOLUME_KEYS: Final = ("master_volume", "music_volume", "sound_volume", "voice_volume")
BACKGROUND_KEYS: Final = ("audio_unfocused", "audio_minimized")
TEXT_KEYS: Final = frozenset({"text_cps", "text_size_pct", "reduce_motion"})
SKIP_AUTO_KEYS: Final = frozenset({"skip_all", "auto_scale_pct", "auto_wait_voice"})
AUDIO_GROUPS: Final = ("volumes", "background", "sustain", "mono")
STORY_GROUPS: Final = ("text", "effects", "blips", "skip_auto")


class SettingsService:
    """``App.settings`` (04 §5.2). Main thread only.

    ``writer`` is ``App.writer``: the service registers its client (owner ``settings``,
    ``{"settings.json"}``) on the first write, so a session that never writes registers
    nothing. ``clock`` times the debounce of changes made through ``set``/``reset`` (the
    App's clock, the same as ``update``'s ``now``)."""

    def __init__(self, loaded: LoadedSettings, config: "Config", *,
                 window: "WindowPort | None" = None, display_scale: float = 1.0,
                 writer: "Writer | None" = None,
                 clock: Callable[[], float] = time.perf_counter,
                 log: logging.Logger | None = None, game_root: Path | None = None,
                 release: bool = False, file: str | None = None,
                 notices: Iterable[str] = ()) -> None:
        self.config = config
        self.defaults: Mapping[str, Value] = config_defaults(config)
        self.stored: dict[str, Value] = dict(loaded.values)
        self.outcome = loaded.outcome
        self.folder = loaded.folder
        self.writable = loaded.writable and loaded.folder is not None
        self.release = release
        self.display_scale = display_scale if display_scale > 0 else 1.0
        self.file = file if file is not None else (
            display_file(loaded.folder, game_root=game_root) if loaded.folder is not None
            else FALLBACK_FILE)
        self.log = log if log is not None else _logger()
        self.window: "WindowPort | None" = None
        self.persist: object | None = None   # App.persist (Delete progress; attach_story)
        # §5.5 targets: None until attached (and always None headless or on a fake App).
        self.audio: object | None = None     # App.audio (F08)
        self.textbox: object | None = None   # TextboxScreen (F05): ``settings``
        self.stage: object | None = None     # StageScreen (F09): ``settings``, ``drop_effects``
        self.blips: object | None = None     # BlipPlayer (F06): ``set_enabled``
        self.skip_auto: object | None = None  # App.skip_auto (F15): ``settings``
        self.shell: object | None = None     # GameShell (F10)
        self._reduce_pushed: bool | None = None   # the effective reduce last given the stage
        self._launch_windowed: tuple[int, int] | None = None
        self._writer = writer
        self._client: "WriterClient | None" = None
        self._clock = clock
        self._dirty_since: float | None = None
        self._last_change = 0.0
        self._in_flight = False
        self._failed_logged = False
        self._saved_again_logged = False
        self._failing = False
        self._quit_logged = False
        self._seen_fullscreen = False
        self._listeners: list[Listener] = []
        self._notices: list[str] = list(notices)
        if window is not None:
            self.attach_window(window)

    # --- SettingsPort (read by the page and later features) ---

    def value(self, key: str) -> Value:
        """The effective value: the player's, else the config default."""
        if key in self.stored:
            return self.stored[key]
        return self.defaults[key]

    def is_default(self, key: str) -> bool:
        return key not in self.stored

    def set(self, key: str, value: Value) -> None:
        """Change a setting (``ValueError`` for an unknown key or a value ``check``
        refuses). Equal to the default: the key is removed (follows config again). No
        effect when the effective value doesn't change."""
        value = self._checked(key, value)
        if not self._record(key, value, self._clock()):
            return
        self._apply(frozenset({key}))
        self._notify(frozenset({key}))

    def reset(self) -> None:
        """Reset settings (§7.3): every key follows config again; the file is rewritten."""
        before = {key: self.value(key) for key in KEYS}
        self.stored = {}
        self._mark_dirty(self._clock())
        changed = frozenset(key for key in KEYS if self.value(key) != before[key])
        if changed:
            self._apply(changed)
            self._notify(changed)

    def locked(self, key: str) -> bool:
        """``reduce_motion`` is locked on while ``[effects] reduce`` is set (§7.2)."""
        return key == "reduce_motion" and effects_reduce(self.config)

    def effective_reduce(self) -> bool:
        """``[effects] reduce`` OR the player's value (§7.2)."""
        return effects_reduce(self.config) or bool(self.value("reduce_motion"))

    def progress(self) -> str:
        """The Delete progress row (§7.7; shown on the title page only): ``"disabled"``
        without persistent data or when it is READ_ONLY (F12 W51: the file wouldn't
        change), else ``"enabled"``."""
        persist = self.persist
        if persist is None or getattr(persist, "mode", None) is READ_ONLY:
            return "disabled"
        return "enabled"

    def delete_progress(self) -> None:
        """Delete progress → Yes: F12's ``PersistentStore.reset()`` (saves and settings are
        untouched); F12's own ``update`` writes it in WRITABLE mode."""
        if self.progress() == "enabled":
            self.persist.store.reset()                         # type: ignore[union-attr]

    def add_listener(self, fn: Listener) -> None:
        """``fn(changed_keys)`` after each change is applied (PR-F16-25)."""
        self._listeners.append(fn)

    def take_notices(self) -> list[str]:
        """The launch's W70 notice, once (I-13; ``app/menus.py`` ``NOTICE_SOURCES``)."""
        notices, self._notices = self._notices, []
        return notices

    @property
    def dirty(self) -> bool:
        return self._dirty_since is not None

    @property
    def in_flight(self) -> bool:
        return self._in_flight

    # --- Wiring ---

    def attach_window(self, window: "WindowPort") -> None:
        """The game window (bootstrap step 17): its mode is the starting point of the
        fullscreen poll (step 13 opened it in the stored mode)."""
        self.window = window
        self._seen_fullscreen = bool(window.fullscreen)
        windowed = getattr(window, "windowed_size", None)
        self._launch_windowed = windowed() if windowed is not None else None

    def attach_audio(self, audio: object | None) -> None:
        """``App.audio`` (bootstrap step 17, right after it is built, before any sound):
        volumes, background, and sustain once; ``set_mono`` only when mono is on (the
        device opened in stereo). None (no audio service) keeps nothing."""
        self.audio = audio
        if audio is None:
            return
        self._push("volumes")
        self._push("background")
        self._push("sustain")
        if self.value("mono"):
            self._push("mono")

    def attach_story(self, *, textbox: object | None = None, stage: object | None = None,
                     blips: object | None = None, skip_auto: object | None = None,
                     shell: object | None = None, persist: object | None = None) -> None:
        """The launch's in-game objects (``install_settings_ui``, I-11): each story group
        is pushed once. ``drop_effects()`` is not called here, even with reduce on (G9).
        Not re-run on a reload (F39): the objects persist."""
        self.textbox = textbox
        self.stage = stage
        self.blips = blips
        self.skip_auto = skip_auto
        self.shell = shell
        self.persist = persist
        self._reduce_pushed = None
        for group in STORY_GROUPS:
            self._push(group, attach=True)

    # --- The frame slot (§7.5) ---

    def update(self, now: float) -> None:
        """Every frame and minimized wake, error mode included (I-14)."""
        self._poll_fullscreen(now)
        self._take_results()
        if self._due(now):
            self._submit()

    # --- Quit (§7.6, §7.8) ---

    def submit_final(self) -> None:
        """Before ``persist.close``: the last fullscreen change, the windowed size, then the
        pending write, submitted without waiting. The windowed size is stored only when the
        player resized the window this session (it differs from the size it opened with),
        so a size fitted to a smaller screen never replaces the stored one."""
        self._poll_fullscreen(self._clock())
        window = self.window
        windowed = getattr(window, "windowed_size", None) if window is not None else None
        size = windowed() if windowed is not None else None
        if size is not None and size != self._launch_windowed:
            request = requested_size(size, self.display_scale)
            if request != self.value("window_size"):
                self.set("window_size", request)
        self._take_results()
        if self.writable and self.dirty:
            self._submit()

    def wait_final(self, until: float) -> None:
        """After ``persist.close``: wait for the settings write until the one quit deadline
        (the writer's clock). Past it, W75 ``couldn't write``; the writer abandons the
        write, which can leave only its temp file."""
        client = self._client
        if client is None or not self._in_flight:
            return
        for result in client.wait(until):
            self._handle(result)
        if client.in_flight and not self._quit_logged:
            self._quit_logged = True
            self.log.warning("%s", save_failed_text(self.file, COULDNT_WRITE),
                             extra={"code": "W75"})

    # --- Internals ---

    @staticmethod
    def _checked(key: str, value: object) -> Value:
        if key not in KEYS:
            raise ValueError(f"unknown setting {key!r}")
        if type(value) is list:
            value = tuple(value)
        if check(key, value) is not None:
            raise ValueError(f"not a valid value for the setting {key!r}")
        return value                                    # type: ignore[return-value]

    def _record(self, key: str, value: Value, now: float) -> bool:
        """Store ``value`` for ``key`` (removed when it equals the default) and mark the file
        dirty; False when the effective value doesn't change."""
        if value == self.value(key) and type(value) is type(self.value(key)):
            return False
        if value == self.defaults[key] and type(value) is type(self.defaults[key]):
            self.stored.pop(key, None)
        else:
            self.stored[key] = value
        self._mark_dirty(now)
        return True

    def _mark_dirty(self, now: float) -> None:
        if self._dirty_since is None:
            self._dirty_since = now
        self._last_change = now

    def _apply(self, keys: frozenset[str]) -> None:
        """§7.3: push each changed key's target group once, every argument the current
        effective value."""
        window = self.window
        if "fullscreen" in keys and window is not None:
            window.set_fullscreen(bool(self.value("fullscreen")))
            self._seen_fullscreen = bool(window.fullscreen)
        if not keys.isdisjoint(VOLUME_KEYS):
            self._push("volumes")
        if not keys.isdisjoint(BACKGROUND_KEYS):
            self._push("background")
        if "voice_sustain" in keys:
            self._push("sustain")
        if "mono" in keys:
            self._push("mono")
        if not keys.isdisjoint(TEXT_KEYS):
            self._push("text")
        if "reduce_motion" in keys:
            self._push("effects")
        if "text_blips" in keys:
            self._push("blips")
        if not keys.isdisjoint(SKIP_AUTO_KEYS):
            self._push("skip_auto")

    def _push(self, group: str, *, attach: bool = False) -> None:
        """One group to its target (§5.5); skipped when the target doesn't exist."""
        value = self.value
        audio: Any = self.audio
        if group in AUDIO_GROUPS:
            if audio is None:
                return
            if group == "volumes":
                audio.set_volumes(*(int(value(k)) for k in VOLUME_KEYS))
            elif group == "background":
                audio.set_background(*(bool(value(k)) for k in BACKGROUND_KEYS))
            elif group == "sustain":
                audio.set_voice_sustain(bool(value("voice_sustain")))
            else:
                audio.set_mono(bool(value("mono")))
        elif group == "text":
            textbox: Any = self.textbox
            if textbox is not None:
                textbox.settings = self.text_settings()
        elif group == "effects":
            self._push_effects(attach=attach)
        elif group == "blips":
            blips: Any = self.blips
            if blips is not None:
                blips.set_enabled(bool(value("text_blips")))
        elif group == "skip_auto":
            skip_auto: Any = self.skip_auto
            if skip_auto is not None:
                skip_auto.settings = self.skip_auto_settings()

    def _push_effects(self, *, attach: bool) -> None:
        """F09's ``EffectSettings``, replaced whole when the effective reduce changes (a
        player value under a config lock changes nothing); a False→True change after
        attach drops the shake and flash in play, after the assignment (G9)."""
        stage: Any = self.stage
        if stage is None:
            return
        from engine.render.effects import EffectSettings

        reduce = self.effective_reduce()
        before = self._reduce_pushed
        if reduce == before:
            return
        stage.settings = EffectSettings(reduce=reduce)
        self._reduce_pushed = reduce
        if reduce and before is False and not attach:
            stage.drop_effects()

    def text_settings(self) -> "TextSettings":
        """F05's ``TextSettings`` (§5.5): ``cps`` the stored speed (None: config; stored 0
        is Instant, G8), the text size from the config size and Text size, and the
        effective reduce."""
        from engine.ui.builtin.textbox_screen import TextSettings

        cps = self.stored.get("text_cps")
        pct = self.value("text_size_pct")
        assert type(pct) is int
        return TextSettings(cps=cps if type(cps) is int and cps > 0 else None,
                            instant=cps == 0,
                            text_size=effective_text_size(
                                self.config.theme.textbox.text_size, pct),
                            reduce_motion=self.effective_reduce())

    def skip_auto_settings(self) -> "SkipAutoSettings":
        """F15's ``SkipAutoSettings`` (I-8): the player's stored values, None = config;
        Auto-advance wait is a wait slider, so ``auto_scale = pct / 100``."""
        from engine.ui.builtin.skip_auto import SkipAutoSettings

        stored = self.stored
        pct = stored.get("auto_scale_pct")
        skip_all = stored.get("skip_all")
        wait_voice = stored.get("auto_wait_voice")
        return SkipAutoSettings(
            skip_all=None if skip_all is None else bool(skip_all),
            auto_scale=pct / 100 if type(pct) is int else None,
            auto_wait_voice=None if wait_voice is None else bool(wait_voice))

    def _notify(self, keys: frozenset[str]) -> None:
        for listener in tuple(self._listeners):
            listener(keys)

    def _poll_fullscreen(self, now: float) -> None:
        """§7.5 step 1: a mode change made outside the service (F11, Alt+Enter, the OS) is
        recorded as the player's choice, without calling ``set_fullscreen`` again."""
        window = self.window
        if window is None:
            return
        fullscreen = bool(window.fullscreen)
        if fullscreen == self._seen_fullscreen:
            return
        self._seen_fullscreen = fullscreen
        if self._record("fullscreen", fullscreen, now):
            self._notify(frozenset({"fullscreen"}))

    def _due(self, now: float) -> bool:
        since = self._dirty_since
        if not self.writable or since is None or self._in_flight:
            return False
        return now - self._last_change >= WRITE_QUIET_S or now - since >= WRITE_MAX_DIRTY_S

    def _submit(self) -> None:
        client = self._ensure_client()
        if client is None or self.folder is None:
            self._dirty_since = None
            return
        data = encode_settings(self.stored)
        self._dirty_since = None
        self._in_flight = True
        client.submit(FileWrite(self.folder, FILE_NAME, (data,), release=self.release))

    def _ensure_client(self) -> "WriterClient | None":
        if self._client is None and self._writer is not None and self.folder is not None:
            self._client = self._writer.client(SETTINGS, root=self.folder, names=NAMES)
        return self._client

    def _take_results(self) -> None:
        client = self._client
        if client is None:
            return
        for result in client.take():
            self._handle(result)

    def _handle(self, result: object) -> None:
        """§7.5 step 2. A failure keeps the file clean: it is retried at the next change."""
        self._in_flight = False
        if isinstance(result, FileWritten):
            if self._failing and not self._saved_again_logged:
                self._saved_again_logged = True
                self.log.info("%s", SAVED_AGAIN_TEXT)
            self._failing = False
        elif isinstance(result, Failed):
            self._failing = True
            if result.detail:
                self.log.debug("The settings write failed: %s", result.detail)
            if not self._failed_logged:
                self._failed_logged = True
                self.log.warning("%s", save_failed_text(self.file, result.reason),
                                 extra={"code": "W75"})


def install_settings(app: object, launch: SettingsLaunch, *, display_scale: float,
                     game_root: Path | None, release: bool) -> SettingsService:
    """Bootstrap step 17: ``App.settings`` on the App's window, writer, and clock."""
    service = SettingsService(launch.loaded, app.config,              # type: ignore[attr-defined]
                              window=app.window,                      # type: ignore[attr-defined]
                              display_scale=display_scale,
                              writer=getattr(app, "writer", None),
                              clock=app.clock,                        # type: ignore[attr-defined]
                              game_root=game_root, release=release, file=launch.file,
                              notices=launch.notices)
    app.settings = service                                            # type: ignore[attr-defined]
    return service


def install_settings_ui(app: object) -> None:
    """F16 checklist steps 3–4 (``07`` I-11, I-13): ``attach_story`` on the launch's
    textbox, stage, blips, ``App.skip_auto``, shell, and ``App.persist``, so every story
    setting is in place before the first story frame; the Settings page in the title, game,
    and quick menus over ``App.settings``; the shell painter's text scale follows Text size
    (``effective_text_size(base, pct) ÷ base``, F16 conflict 12), so every menu lays out
    again at once; Delete progress reaches ``App.persist``; the launch's W70 notice goes to
    the notice layer (``notice_settings_default``). ``install_story`` runs it after the
    other entry installs, before ``check_entries()``. Nothing without a shell or a service
    (headless runs, a fake App)."""
    from engine.app.menus import forward_launch_notices
    from engine.ui.builtin.settings_page import register_settings

    service = getattr(app, "settings", None)
    shell = getattr(app, "shell", None)
    if not isinstance(service, SettingsService) or shell is None:
        return
    service.attach_story(textbox=getattr(app, "textbox", None),
                         stage=getattr(app, "stage_screen", None),
                         blips=getattr(app, "blips", None),
                         skip_auto=getattr(app, "skip_auto", None),
                         shell=shell, persist=getattr(app, "persist", None))
    base = service.config.theme.textbox.text_size

    def text_scale() -> float:
        pct = service.value("text_size_pct")
        assert type(pct) is int
        return effective_text_size(base, pct) / base

    shell.painter.set_text_scale(text_scale)
    register_settings(shell, service)                              # type: ignore[arg-type]
    forward_launch_notices(app, shell)                             # type: ignore[arg-type]


__all__ = ["NOTICE_TEXT", "NO_ID_TEXT",
           "SAVED_AGAIN_TEXT", "SettingsLaunch", "SettingsService", "WRITE_MAX_DIRTY_S",
           "WRITE_QUIET_S", "bad_file_text", "bad_value_text", "config_defaults",
           "effects_reduce", "install_settings", "install_settings_ui", "launch_settings",
           "launch_value",
           "log_launch", "newer_file_text", "requested_size", "save_failed_text",
           "unknown_keys_text"]

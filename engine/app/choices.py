"""``install_choices``: F07's menus wired into one launch (F07 ``04-technical.md`` §3.1, §5.5,
§12, §13; F10 ``07`` I-3, I-8; F07 ``07`` I-5, I-8, I-11).

Why this module exists: ``ui`` never imports ``engine.app``, so the ``ChoiceController``
gets the App-side things it needs injected: the stack, the textbox, the assets, the theme,
``post``, which sends ``Choose`` to whatever ``app.story`` is at that moment (a test may
wrap the driver's ``post``), and ``play``, which plays a sound through whatever
``app.audio`` is then (``AudioService.play_ui``, F08's UI pool). ``install_story`` calls
this once per launch, after ``install_textbox`` and before ``install_ui``, which hands the
controller F10's choice floor (``app.choices.set_floor``); F10's ``reset_in_game`` calls
``app.choices.close()``.

Registers ``ShowMenu → ChoiceController.show`` and the controller's say listener
(``on_say``: any ``Say`` closes an open menu). The ``[theme.choice]`` files are checked once
here, so a broken one costs one warning and never a checkerboard or a failed play:

- ``text_font``: a usable font becomes the regular face; bold and italic stay the
  textbox's (design §6.4). Unusable: **W43** (``[theme.choice]`` form), the textbox's font.
- ``frame_image``, ``focused.frame_image``: unusable is **W43**, and that state draws the
  button.
- ``focus_sound``, ``pick_sound``: a file that doesn't exist under ``audio/`` is **W48**
  (dev and release, 07 I-5), with ``GamePaths``' did-you-mean, and that sound never plays.
  F51: ``timer.tick_sound`` the same way.
- F51 (07 I-5): the controller's ``timing_level`` reads ``app.settings``' ``timing_assist``
  every frame (Normal without a settings service) and ``window_focused`` reads
  ``app.focused``, so ``ui`` never reaches ``app``.
- Dev only, **W44** (``[theme.choice]`` form): ``text_color`` under 4.5:1 on its fill over a
  pure black or white picture (the focused fill is checked when the normal one passes), and
  ``locked.text_color`` on the locked fill. A state with a frame image isn't checked.

W43 and W44 keep F05's log area (``text``); W48 is ``choice`` (07 I-11). Then the one-line
normal and focused shapes are pre-rendered at the current scale (``04`` §7.8).
"""

from typing import TYPE_CHECKING, Final

from engine.app.text_check import TEXT_MIN_RATIO, box_contrast
from engine.core.errors import AssetMissing, AssetRefError
from engine.core.logsetup import get_logger
from engine.render.assets import Face
from engine.render.choices import ChoiceStackView, rgb_hex
from engine.render.textlayout import LINE_PITCH, FaceSet, FaceSource
from engine.runtime.commands import ShowMenu
# Through runtime: only loading.py of engine.app imports engine.script (AC-F02-66).
from engine.runtime.errors import format_message
from engine.ui.builtin.choice_screen import ChoiceController, ChoiceLook

if TYPE_CHECKING:
    from collections.abc import Callable

    from engine.app.app import App
    from collections.abc import Mapping

    from engine.core.config_schema import ChoiceTheme, ThemeConfig
    from engine.render.assets import AssetManager
    from engine.ui.builtin.textbox_screen import TextboxScreen

AUDIO_FOLDER: Final = "audio/"

_text_log = get_logger("text")           # W43, W44 keep F05's area (07 I-11)
_log = get_logger("choice")              # W48


def install_choices(app: "App", textbox: "TextboxScreen") -> ChoiceController:
    """Build the launch's ``ChoiceController``, keep it on ``app.choices``, and register
    its ``ShowMenu`` handler and say listener (module docstring for the checks)."""
    config = app.config
    theme = config.theme.choice
    assets = app.assets

    def warn(message: str) -> None:
        _text_log.warning("%s", message)

    faces = choice_faces(theme, textbox.faces, assets, warn)
    frame = _checked_image(assets, "frame_image", theme.frame_image, warn)
    focused_frame = _checked_image(assets, "focused.frame_image", theme.focused.frame_image,
                                   warn)
    if app.dev:
        for message in choice_colors_warnings(theme, frame=frame, focused_frame=focused_frame):
            warn(message)
    sounds = {key: _checked_sound(app, key, getattr(theme, key))
              for key in ("focus_sound", "pick_sound")}
    tick = _checked_sound(app, "timer.tick_sound", theme.timer.tick_sound)    # F51: W48
    view = ChoiceStackView(assets, theme, frame=frame, focused_frame=focused_frame)
    controller = ChoiceController(app.screens, textbox, theme=theme, assets=assets,
                                  faces=faces, base_text_size=config.theme.textbox.text_size,
                                  post=lambda event: _post(app, event), view=view,
                                  play=lambda file: _play(app, file),
                                  focus_sound=sounds["focus_sound"],
                                  pick_sound=sounds["pick_sound"], tick_sound=tick,
                                  timing_level=lambda: timing_level(app),
                                  window_focused=lambda: bool(getattr(app, "focused", True)))
    app.choices = controller                                 # type: ignore[attr-defined]
    app.router.register(ShowMenu, controller.show)
    textbox.add_say_listener(controller.on_say)
    viewport = getattr(app, "viewport", None)
    if viewport is not None:
        size = controller.text_size()
        view.prerender(min(viewport.scale_x, viewport.scale_y),
                       round(LINE_PITCH * size) + theme.top_padding + theme.bottom_padding)
    return controller


def choice_faces(theme: "ChoiceTheme", textbox_faces: FaceSet, assets: "AssetManager",
                 warn: "Callable[[str], None]") -> FaceSet:
    """The choices' ``FaceSet``: the textbox's, with a usable ``choice.text_font`` as the
    regular face (W43 for an unusable one)."""
    ref = theme.text_font
    if ref is None:
        return textbox_faces
    problem = assets.check(ref, "font")
    if problem is not None:
        warn(format_message("W43", ("text_font", ref, problem.kind, problem.suggestion, False,
                                    "choice")))
        return textbox_faces
    faces = dict(textbox_faces.faces)
    faces[Face.REGULAR] = FaceSource(ref, Face.REGULAR)
    return FaceSet(faces)


def choice_look(cfg: "ThemeConfig", textbox_faces: FaceSet,
                usable: "Callable[[str, str], bool]",
                base_sounds: "Mapping[str, tuple[str | None, str | None]]") -> ChoiceLook:
    """F32's ``"choice"`` part of a look's ``cfg`` (04 §6.2 step 3, §6.5): pure, no warning
    and no file read. ``textbox_faces`` are the look's textbox faces; ``usable(ref, kind)``
    is ``LookChecks.usable``. ``base_sounds`` maps each sound key to ``([theme.choice]'s
    token, the token that passed W48)``: a look that keeps the base token gets the checked
    one; a style's own sound plays as set (F08's line if missing, 04 §6.2 step 1)."""
    theme = cfg.choice
    faces = textbox_faces
    ref = theme.text_font
    if ref is not None and usable(ref, "font"):
        table = dict(textbox_faces.faces)
        table[Face.REGULAR] = FaceSource(ref, Face.REGULAR)
        faces = FaceSet(table)

    def image(ref: str | None) -> str | None:
        return ref if ref is not None and usable(ref, "image") else None

    def sound(key: str, token: str | None) -> str | None:
        base, checked = base_sounds.get(key, (None, None))
        return checked if token == base else token

    return ChoiceLook(theme, faces, cfg.textbox.text_size, image(theme.frame_image),
                      image(theme.focused.frame_image),
                      sound("focus_sound", theme.focus_sound),
                      sound("pick_sound", theme.pick_sound),
                      sound("tick_sound", theme.timer.tick_sound))           # F51


def _checked_image(assets: "AssetManager", key: str, ref: str | None,
                   warn: "Callable[[str], None]") -> str | None:
    if ref is None:
        return None
    problem = assets.check(ref, "image")
    if problem is None:
        return ref
    warn(format_message("W43", (key, ref, problem.kind, problem.suggestion, False, "choice")))
    return None


def choice_colors_warnings(theme: "ChoiceTheme", *, frame: str | None | object = ...,
                           focused_frame: str | None | object = ...) -> list[str]:
    """W44 for ``[theme.choice]`` (dev): the normal text on its fill (else on the focused
    fill), and the locked text on its fill. A state drawn from a frame image is skipped;
    ``frame``/``focused_frame`` are the checked images (default: the theme's refs), so a
    missing frame's drawn button is checked."""
    if frame is ...:
        frame = theme.frame_image
    if focused_frame is ...:
        focused_frame = theme.focused.frame_image
    out: list[str] = []
    checks = []
    if frame is None:
        checks.append(("fill_color", theme.fill_color))
    if focused_frame is None:
        checks.append(("focused.fill_color", theme.focused.fill_color))
    for fill_key, fill in checks:
        ratio, backdrop = box_contrast(theme.text_color, fill, theme.fill_opacity)
        if ratio < TEXT_MIN_RATIO:
            out.append(format_message("W44", (
                rgb_hex(theme.text_color), rgb_hex(fill), theme.fill_opacity, ratio, backdrop,
                "choice", "text_color", fill_key, "fill_opacity")))
            break                                            # one W44 per text color
    if frame is None:
        locked = theme.locked
        ratio, backdrop = box_contrast(locked.text_color, theme.fill_color,
                                       locked.fill_opacity)
        if ratio < TEXT_MIN_RATIO:
            out.append(format_message("W44", (
                rgb_hex(locked.text_color), rgb_hex(theme.fill_color), locked.fill_opacity,
                ratio, backdrop, "choice", "locked.text_color", "fill_color",
                "locked.fill_opacity")))
    return out


def _checked_sound(app: "App", key: str, file: str | None) -> str | None:
    """``file`` if it exists under ``audio/`` (or there is no game folder to look in), else
    W48 and None (no sound plays)."""
    if file is None:
        return None
    paths = getattr(app, "paths", None)
    if paths is None:
        return file
    try:
        paths.resolve(AUDIO_FOLDER + file)
    except AssetMissing as error:
        suggestion = error.suggestion
        if suggestion is not None and suggestion.startswith(AUDIO_FOLDER):
            suggestion = suggestion[len(AUDIO_FOLDER):]
        else:
            suggestion = None
        _log.warning("%s", format_message("W48", (key, file, suggestion)))
        return None
    except AssetRefError:
        return None                       # refused by the config check already (AudioRef)
    return file


def timing_level(app: "App") -> int:
    """F51 (04 §3): the player's Timing assist as the stored int, read every frame; Normal
    (0) without a settings service or with anything unexpected."""
    settings = getattr(app, "settings", None)
    if settings is None:
        return 0
    try:
        value = settings.value("timing_assist")
    except (KeyError, ValueError):
        return 0
    return value if type(value) is int else 0


def _post(app: "App", event: object) -> None:
    story = app.story
    if story is not None:
        story.post(event)


def _play(app: "App", file: str) -> None:
    audio = getattr(app, "audio", None)
    if audio is not None:
        audio.play_ui(file)


__all__ = ["choice_colors_warnings", "choice_faces", "choice_look", "install_choices",
           "timing_level"]

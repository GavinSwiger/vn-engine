"""The textbox install and the text launch checks (F05 ``04-technical.md`` §7.6, §7.8).

Why this module exists: the textbox's fonts and frame come from ``config.toml`` and may be
missing or broken. ``install_textbox`` checks each once per launch, warns the author with
F05's own messages (W43 for an unusable file, W45 for a style made from the author's font),
builds the ``FaceSet`` layout and drawing share, and wires the launch's one
``TextboxScreen`` (I-16) as the ``Say`` handler (F17: and the ``NvlPage`` handler, with its
``NvlView``; ``install_nvl`` adds F17's in-game reset). Checked faces that fail count as
unset, so ``AssetManager.font`` is never asked for them and logs no second warning (I-5).

Faces (§7.6), ``custom`` = a usable ``text_font``:

| Face | Not configured, ``custom`` | Not configured, otherwise |
|---|---|---|
| Regular | — | Noto Sans Regular |
| Bold | Regular + ``Synth.BOLD`` (W45) | Noto Sans Bold |
| Italic | Regular + ``Synth.ITALIC`` (W45) | Noto Sans Italic |
| Bold Italic | the resolved Bold + ``Synth.ITALIC`` (no warning) | Noto Sans Bold Italic |

The contrast function (WCAG 2.x, I-6) serves W41, W44 (``TextLaunchCheck``, F05 step 7),
and the UI-F05-05 tests: colors are blended in sRGB as drawn, per channel
``round(fg × a + bg × (1 − a))``, and pure black and pure white bound every backdrop.

Dev runs only (§7.8): ``install_textbox`` warns W44 when ``[theme.textbox]`` text on its own
box is hard to read, and ``TextLaunchCheck`` runs after the launch phase, in the story load
screen's slices with ``App.loading`` True:

1. **W41** per define holding a ``Character`` (the define that made it, so an alias doesn't
   warn twice): a name ``color`` under 3:1 on the name plate, a ``text_color`` under 4.5:1 on
   the box over a pure black or pure white picture (the worse one is named).
2. **W40** per dialogue or narration line that needs more than one text box at the configured
   font and size. Each ``{var}`` is measured as its ``default``'s literal (``ast.literal_eval``,
   never ``eval``) or its ``define``'s value, when that is text or a number, else as "" (I-3:
   exact ``str``/``int``/``float`` only, so no author method runs). The speaker's
   ``text_color``/``text_italic`` apply as on screen. Fast path: no line break, no size tag,
   and the whole text no wider than the text area in the widest face present: one page
   (taken only when a page holds at least two lines, so a kerning difference can't hide a
   second page). Else ``LineLayout``, the layout the textbox uses. After 20 records, one
   W40b counts the rest.

3. F07 (``04`` §6.5, 07 I-9): a menu's question is checked as a line (W40 at its line), and
   each choice that needs more than one line at ``[theme.choice] text_size`` (never F16's
   setting) and the configured text width gets **W47** at the choice's line, in the 2-line
   or the "cut with …" form. ``{var}`` is measured as for W40. After 20 W47 records, one
   summary line counts the rest (``W47_MAX_CHOICES``, like W40's cap; F07 step 5).

F17 (``04`` §7.6, SR-F17-06, 07 I-8, I-11), dev runs too:

- **W100, theme form**: ``[theme.nvl]`` ``text_color`` under 4.5:1, ``name.text_color`` and
  ``indicator.fill_color`` under 3:1, on the panel composited over black and white (the
  lower is named). One record per cause, reported only when the walk saw an ``nvl on``:
  the NVL colors follow ``[theme.textbox]``'s, so a dark text box would otherwise warn
  about a panel a story never shows (04 §7.6 put it in ``install_textbox``; see the F17
  step 5 report).
- **Mode by file order**: the walk keeps one mode per label. It starts in the textbox's mode
  at each label (``Statement.label`` changes) and follows each ``nvl on``/``nvl off`` in
  ``iter_statements()`` order, nested blocks included; jumps and calls are not followed.
  ``Nvl`` is recognised through ``runtime/nvl.py`` (``app`` reaches ``engine.script`` only
  through ``loading.py``).
- **W101** replaces W40 for a line in full-screen mode (dialogue, narration, a menu's
  question): its pages at ``nvl.text_size`` in the NVL text area, less one name row when
  the speaker has a name. After 20, one W101s counts the rest.
- **W100, character form** (step 1, beside W41): a ``Character``'s name ``color`` under 3:1
  on the panel, at the ``define``'s line; kept, and reported only when the walk saw an
  ``nvl on``.

Records are logged in this order when the check ends: W41, W100 (theme, then characters),
W40, W40b, W101, W101s in area ``text``, then W47 in area ``choice``.
"""

import ast
import random
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from itertools import islice
from typing import TYPE_CHECKING, Final

from engine.core.config_schema import ChoiceTheme, ThemeConfig
from engine.core.errors import UserFacingError
from engine.core.logsetup import get_logger
from engine.render.assets import AssetManager, Face, Synth
from engine.render.choices import MIN_TEXT_WIDTH
from engine.render.nvl import NvlView
from engine.render.nvllayout import NvlLook, line_context, nvl_look, nvl_metrics
from engine.render.textbox import TextboxView, box_geometry, hex_rgb, rgb_hex
from engine.render.textlayout import (LINE_PITCH, FaceSet, FaceSource, LayoutContext,
                                      LineLayout, count_pages, face_for, render_safe)
from engine.runtime.character import Character
from engine.runtime.commands import NameMark, NvlPage, Say, Span, Style, TaggedText, VarMark
# Through runtime: only loading.py of engine.app imports engine.script (AC-F02-66).
from engine.runtime.errors import format_message
from engine.runtime.nvl import Nvl                 # F17 07 I-8: the statement, through runtime
from engine.runtime.text import format_value
from engine.ui.blips import BlipPlayer
from engine.ui.builtin.textbox_screen import TextboxScreen

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.core.config_schema import TextboxTheme

RGB = tuple[int, int, int]
BLACK: RGB = (0, 0, 0)
WHITE: RGB = (255, 255, 255)

NAME_MIN_RATIO: Final = 3.0               # SR-F05-24: names (24 units and up)
TEXT_MIN_RATIO: Final = 4.5               # SR-F05-24, 27: body text
TEXT_CHECK_CHUNK: Final = 200             # defines or statements per step (§7.8)
TEXT_CHECK_CHARS: Final = 10_000          # and at most about this much line text per step
W40_MAX_LINES: Final = 20                 # W40 records, then one W40b (SR-F05-28)
W47_MAX_CHOICES: Final = 20               # W47 records, then one summary line (as W40)
W101_MAX_LINES: Final = 20                # F17: W101 records, then one W101s (as W40)

_log = get_logger("text")
_choice_log = get_logger("choice")        # F07 W47 (07 I-11)


# --- Contrast (UI-F05-05, W41, W44) -----------------------------------------------------------

def _channel(c: int) -> float:
    s = c / 255
    return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4


def relative_luminance(color: RGB) -> float:
    r, g, b = color
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(a: RGB, b: RGB) -> float:
    """WCAG 2.x contrast of two opaque colors (1.0 to 21.0)."""
    high, low = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def composite(fg: RGB, opacity: float, bg: RGB) -> RGB:
    """``fg`` at ``opacity`` over ``bg``, per channel in sRGB as drawn."""
    return tuple(round(f * opacity + b * (1 - opacity)) for f, b in zip(fg, bg))  # type: ignore


def box_contrast(text: RGB, fill: RGB, opacity: float) -> tuple[float, str]:
    """The worse contrast of ``text`` on the box composited over pure black and over pure
    white, and that backdrop's word (``"black"`` or ``"white"``)."""
    over_black = contrast_ratio(text, composite(fill, opacity, BLACK))
    over_white = contrast_ratio(text, composite(fill, opacity, WHITE))
    return (over_black, "black") if over_black <= over_white else (over_white, "white")


# --- Faces (§7.6) -------------------------------------------------------------------------------

def resolve_faces(theme: "TextboxTheme", assets: AssetManager,
                  warn: Callable[[str], None]) -> FaceSet:
    """The textbox ``FaceSet`` of ``[theme.textbox]``, warning W43 and W45 through ``warn``."""

    def usable(key: str, ref: str | None, made_from_text_font: bool) -> str | None:
        if ref is None:
            return None
        problem = assets.check(ref, "font")
        if problem is None:
            return ref
        warn(format_message("W43", (key, ref, problem.kind, problem.suggestion,
                                    made_from_text_font)))
        return None

    custom = usable("text_font", theme.text_font, False)
    made = custom is not None
    bold = usable("bold_font", theme.bold_font, made)
    italic = usable("italic_font", theme.italic_font, made)
    bold_italic = usable("bold_italic_font", theme.bold_italic_font, made)
    faces: dict[Face, FaceSource] = {Face.REGULAR: FaceSource(custom, Face.REGULAR)}
    if bold is not None:
        faces[Face.BOLD] = FaceSource(bold, Face.BOLD)
    elif custom is not None:
        faces[Face.BOLD] = FaceSource(custom, Face.BOLD, Synth.BOLD)
        if theme.bold_font is None:                    # W45 only for an unset face (G4)
            warn(format_message("W45", ("bold",)))
    else:
        faces[Face.BOLD] = FaceSource(None, Face.BOLD)
    if italic is not None:
        faces[Face.ITALIC] = FaceSource(italic, Face.ITALIC)
    elif custom is not None:
        faces[Face.ITALIC] = FaceSource(custom, Face.ITALIC, Synth.ITALIC)
        if theme.italic_font is None:
            warn(format_message("W45", ("italic",)))
    else:
        faces[Face.ITALIC] = FaceSource(None, Face.ITALIC)
    if bold_italic is not None:
        faces[Face.BOLD_ITALIC] = FaceSource(bold_italic, Face.BOLD_ITALIC)
    elif custom is not None:
        if bold is not None:
            faces[Face.BOLD_ITALIC] = FaceSource(bold, Face.BOLD_ITALIC, Synth.ITALIC)
        else:
            faces[Face.BOLD_ITALIC] = FaceSource(custom, Face.BOLD_ITALIC, Synth.BOLD_ITALIC)
    else:
        faces[Face.BOLD_ITALIC] = FaceSource(None, Face.BOLD_ITALIC)
    return FaceSet(faces)


def _checked_image(assets: AssetManager, key: str, ref: str | None,
                   warn: Callable[[str], None]) -> str | None:
    """``ref`` if it loads as an image, else None (W43: the drawn look is used)."""
    if ref is None:
        return None
    problem = assets.check(ref, "image")
    if problem is None:
        return ref
    warn(format_message("W43", (key, ref, problem.kind, problem.suggestion)))
    return None


# --- Install (§7.8, C2 (e)) -----------------------------------------------------------------------

def install_textbox(app: "App") -> TextboxScreen:
    """Once per launch, from ``install_story``: resolve the faces (W43, W45) and the frame
    (W43), build the launch's one ``TextboxScreen`` with F17's ``NvlView``, keep it on
    ``app.textbox``, and register ``Say → TextboxScreen.show``, ``NvlPage →
    TextboxScreen.show_nvl`` (F17), and F06's blips (``install_blips``). Preloads the four
    faces at the configured text size."""
    config = app.config
    theme = config.theme.textbox
    assets = app.assets

    def warn(message: str) -> None:
        _log.warning("%s", message)

    faces = resolve_faces(theme, assets, warn)
    frame = _checked_image(assets, "frame_image", theme.frame_image, warn)
    if app.dev:                                              # W44 (SR-F05-27)
        w44 = box_colors_warning(theme)
        if w44 is not None:
            warn(w44)
    name_face = faces.faces[Face.BOLD]
    name_font = theme.name_tab.text_font
    if name_font is not None:
        problem = assets.check(name_font, "font")
        if problem is None:
            name_face = FaceSource(name_font, Face.BOLD)
        else:
            warn(format_message("W43", ("name_tab.text_font", name_font, problem.kind,
                                        problem.suggestion)))
    # The tab frame and indicator images (opened by F10) fall back like F01's images: one
    # log line from the asset manager, and the drawn shape instead of a placeholder.
    tab_frame = _image_or_none(assets, theme.name_tab.frame_image)
    line_image = _image_or_none(assets, theme.indicator.line_image)
    page_image = _image_or_none(assets, theme.indicator.page_image)
    view = TextboxView(assets, theme, name_face, frame=frame, tab_frame=tab_frame,
                       line_image=line_image, page_image=page_image)
    for source in faces.faces.values():
        assets.font(source.ref, theme.text_size, bundled=source.bundled, synth=source.synth)
    nvl_view = NvlView.for_textbox(view, nvl_look(config.theme), faces)        # F17
    screen = TextboxScreen(app, config, view, faces, nvl_view=nvl_view)
    app.textbox = screen
    app.router.register(Say, screen.show)
    app.router.register(NvlPage, screen.show_nvl)                            # F17
    install_blips(app, screen)
    return screen


def install_nvl(app: "App") -> None:
    """F17 (``04`` §5.4; F14 ``07`` A6, F17 ``07`` I-7): the textbox's ``reset_nvl`` as an
    in-game reset, so New Game, the way to the title, and a load start in ADV. Called by
    ``install_story`` after F15's ``install_skip_auto``, so it runs after F15's reset.
    Nothing without a shell or a textbox (an App wired by hand)."""
    shell = getattr(app, "shell", None)
    textbox = getattr(app, "textbox", None)
    if shell is None or textbox is None:
        return
    shell.add_in_game_reset(textbox.reset_nvl)


def install_blips(app: "App", screen: TextboxScreen) -> BlipPlayer | None:
    """F06 (SPEC §5): when ``app.audio`` exists, one ``BlipPlayer`` (the App's clock, its own
    ``random.Random()``) listens to ``screen``'s lines and typing, kept on ``app.blips`` for
    F16's ``set_enabled``; else ``app.blips`` is None (headless, Apps wired by hand). The
    clock is read when a blip is due, not here (stand-in Apps of the UI tests have none)."""
    audio = getattr(app, "audio", None)
    player = None if audio is None else BlipPlayer(audio, lambda: app.clock(),
                                                   random.Random())
    app.blips = player                                       # type: ignore[attr-defined]
    if player is not None:
        screen.add_say_listener(player.on_say)
        screen.add_listener(player)
    return player


def _image_or_none(assets: AssetManager, ref: str | None) -> str | None:
    if ref is None:
        return None
    return None if assets.image(ref).is_placeholder else ref


# --- Dev launch checks (§7.8) ----------------------------------------------------------------

def box_colors_warning(theme: "TextboxTheme") -> str | None:
    """W44: ``[theme.textbox] text_color`` on its own box, or None when it reads at 4.5:1."""
    ratio, backdrop = box_contrast(theme.text_color, theme.fill_color, theme.fill_opacity)
    if ratio >= TEXT_MIN_RATIO:
        return None
    return format_message("W44", (rgb_hex(theme.text_color), rgb_hex(theme.fill_color),
                                  theme.fill_opacity, ratio, backdrop))


def _hex_upper(color: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*color)


# F17 W100's theme form: each [theme.nvl] key, its color in the look, and the ratio it needs.
_NVL_COLOR_KEYS: Final = (("text_color", "text_color", TEXT_MIN_RATIO),
                          ("name.text_color", "name_color", NAME_MIN_RATIO),
                          ("indicator.fill_color", "indicator_color", NAME_MIN_RATIO))


def nvl_colors_warnings(look: NvlLook) -> list[str]:
    """F17 W100, theme form (``04`` §7.6): each ``[theme.nvl]`` color under its ratio on the
    panel (``fill_color`` at ``fill_opacity``) over a black or a white picture, one record
    per cause, naming the picture with the lower ratio."""
    out = []
    for key, attribute, need in _NVL_COLOR_KEYS:
        color = getattr(look, attribute)
        ratio, backdrop = box_contrast(color, look.fill_color, look.fill_opacity)
        if ratio < need:
            out.append(format_message("W100", ("theme", key, _hex_upper(color), ratio,
                                               backdrop, _hex_upper(look.fill_color),
                                               look.fill_opacity)))
    return out


def nvl_character_warning(who: str, c: Character, look: NvlLook) -> str | None:
    """F17 W100, character form: ``c``'s name ``color`` under 3:1 on the NVL panel (only
    when it has a name row: a name, or ``name_from``), without the place; else None."""
    color = c.color
    if type(color) is not str or not (c.name_from is not None or c.name):
        return None
    ratio, _ = box_contrast(hex_rgb(color), look.fill_color, look.fill_opacity)
    if ratio >= NAME_MIN_RATIO:
        return None
    return format_message("W100", ("character", who, color, ratio))


def character_warnings(who: str, c: Character, theme: "TextboxTheme") -> list[str]:
    """W41 for one ``Character``, without the place: its name color on the plate (only when
    it has a plate: a name, or ``name_from``) and its ``text_color`` on the box."""
    out = []
    color = c.color
    if type(color) is str and (c.name_from is not None or c.name):
        tab = theme.name_tab
        ratio, _ = box_contrast(hex_rgb(color), tab.fill_color, tab.fill_opacity)
        if ratio < NAME_MIN_RATIO:
            out.append(format_message("W41", ("name", who, color, ratio,
                                              rgb_hex(tab.fill_color))))
    text_color = c.options.get("text_color")
    if type(text_color) is str:
        ratio, backdrop = box_contrast(hex_rgb(text_color), theme.fill_color,
                                       theme.fill_opacity)
        if ratio < TEXT_MIN_RATIO:
            out.append(format_message("W41", ("text", who, text_color, ratio, backdrop,
                                              rgb_hex(theme.fill_color))))
    return out


_DEFINES, _LINES, _DONE = range(3)
_UNSET = object()


class TextLaunchCheck:
    """W41, W40, and W40b of one launch (§7.8), with F17's W100 character form and W101. ``step()`` does at most
    ``TEXT_CHECK_CHUNK`` defines or statements, ending early once it has measured
    ``TEXT_CHECK_CHARS`` characters of line text (one 10,000-character line takes 10 to
    25 ms), and returns True when done; ``warnings``
    (the log texts, places included) are then final. Results don't depend on the slicing.

    ``program`` is the loaded story (its ``defines``, ``defaults``, ``define_names``, and
    ``iter_statements()``), ``G`` the launch namespace; ``assets`` and ``faces`` measure as
    the textbox does (``install_textbox``'s ``FaceSet``). ``nvl`` is the full-screen look
    (``nvl_look``; default: the one ``[theme.textbox]`` alone gives)."""

    def __init__(self, program: object, G: Mapping[str, object], *, assets: object,
                 faces: FaceSet, theme: "TextboxTheme",
                 choice_theme: ChoiceTheme | None = None,
                 choice_faces: FaceSet | None = None, nvl: NvlLook | None = None) -> None:
        self.program = program
        self.G = G
        self.theme = theme
        size = theme.text_size
        geometry = box_geometry(theme, size)
        self.text_size = size
        self.ctx = LayoutContext(assets, faces, size, rgb_hex(theme.text_color),
                                 geometry.area[2], geometry.area[3])
        # The fast path may be off by a few units, so it needs room for a second line.
        self._fast = geometry.area[3] >= 2 * geometry.pitch
        # F07 W47: one line per page at the configured choice size and text width (I-9).
        choice = choice_theme if choice_theme is not None else ChoiceTheme()
        self.choice_size = choice.text_size if choice.text_size is not None else size
        width = max(MIN_TEXT_WIDTH, choice.width - 2 * choice.side_padding)
        self.choice_ctx = LayoutContext(
            assets, choice_faces if choice_faces is not None else faces, self.choice_size,
            rgb_hex(choice.text_color), width, round(LINE_PITCH * self.choice_size))
        # F17: the full-screen text area at nvl.text_size, with and without a name row.
        self.nvl = nvl if nvl is not None else nvl_look(ThemeConfig(textbox=theme))
        metrics = nvl_metrics(self.nvl, 1.0)
        self.nvl_size = metrics.size
        self.nvl_ctx = {named: line_context(assets, faces, self.nvl, metrics, named)
                        for named in (False, True)}
        self.warnings: tuple[str, ...] = ()
        self._found: list[str] = []
        self._w100: list[str] = []            # F17 character form, kept until the walk ends
        self._w101: list[str] = []
        self._w101_more = 0
        self._label: object = _UNSET          # the walk's label, and its mode (SR-F17-06)
        self._full_screen = False
        self._saw_nvl = False
        self._w40: list[str] = []
        self._w47: list[str] = []
        self._w47_more = 0
        self._text_count = 0                  # warnings[:n] log in area text, the rest choice
        self._more = 0
        self._phase = _DEFINES
        self._defines: Iterator = iter(program.defines)            # type: ignore[attr-defined]
        self._statements: Iterator = program.iter_statements()     # type: ignore[attr-defined]
        self._defaults = {d.name: d for d in program.defaults}    # type: ignore[attr-defined]
        self._define_names = frozenset(program.define_names)      # type: ignore[attr-defined]
        self._shown: dict[str, str] = {}

    # -- driving --

    def step(self) -> bool:
        if self._phase == _DEFINES:
            seen = 0
            for define in islice(self._defines, TEXT_CHECK_CHUNK):
                self._check_define(define)
                seen += 1
            if seen < TEXT_CHECK_CHUNK:
                self._phase = _LINES
            return False
        if self._phase == _LINES:
            seen = chars = 0
            for stmt in self._statements:
                label = getattr(stmt, "label", None)
                if label != self._label:                # each label starts in the textbox
                    self._label, self._full_screen = label, False
                if type(stmt) is Nvl:
                    if stmt.action != "clear":
                        self._full_screen = stmt.action == "on"
                        self._saw_nvl = self._saw_nvl or self._full_screen
                elif self.checks_line(stmt):
                    self._check_line(stmt)
                    chars += len(stmt.text)                     # type: ignore[attr-defined]
                elif _is_menu(stmt):
                    chars += self._check_menu(stmt)
                seen += 1
                if seen == TEXT_CHECK_CHUNK or chars >= TEXT_CHECK_CHARS:
                    return False
            w100 = nvl_colors_warnings(self.nvl) + self._w100 if self._saw_nvl else []
            out = self._found + w100 + self._w40
            if self._more:
                out.append(format_message("W40b", (self._more,)))
            out += self._w101
            if self._w101_more:
                out.append(format_message("W101s", (self._w101_more,)))
            self._text_count = len(out)
            w47 = self._w47 + ([w47_more(self._w47_more)] if self._w47_more else [])
            self.warnings = tuple(out + w47)
            self._phase = _DONE
        return True

    def run(self) -> tuple[str, ...]:
        """The check to the end in one go (tests and tools)."""
        while not self.step():
            pass
        return self.warnings

    def log(self) -> None:
        """W41, W40, W40b in area ``text``, then W47 in area ``choice`` (F07 07 I-11)."""
        for index, text in enumerate(self.warnings):
            (_log if index < self._text_count else _choice_log).warning("%s", text)

    # -- F07: menus (W40 on the question, W47 per choice) --

    def _check_menu(self, menu: object) -> int:
        """The question as a line (W40 at its line), then W47 for each choice that needs
        more than one line at ``choice.text_size`` (dev launches only, as this check).
        Returns the characters measured."""
        chars = 0
        question = getattr(menu, "question", None)
        if question is not None and self.checks_line(question):
            self._check_line(question)
            chars += len(question.text)
        for choice in menu.choices:                                 # type: ignore[attr-defined]
            body = getattr(choice, "body", None)
            if type(body) is not TaggedText:
                continue
            chars += len(getattr(choice, "text", ""))
            lines = self.choice_lines(self.resolve_body(body, None))
            if lines <= 1:
                continue
            if len(self._w47) < W47_MAX_CHOICES:
                self._w47.append(_placed_at(format_message("W47", (lines, self.choice_size)),
                                            menu, getattr(choice, "line", None)))
            else:
                self._w47_more += 1
        return chars

    def choice_lines(self, body: TaggedText) -> int:
        """The lines a resolved choice ``body`` needs at the configured choice size and text
        width (the layout ``ChoiceLayout`` uses, one line per page)."""
        return count_pages(body, self.choice_ctx)

    # -- W41 --

    def _check_define(self, define: object) -> None:
        name = define.name                                          # type: ignore[attr-defined]
        c = self.G.get(name)
        if type(c) is not Character or c.define_name != name:      # the define that made it
            return
        for message in character_warnings(name, c, self.theme):
            self._found.append(_placed(message, define))
        w100 = nvl_character_warning(name, c, self.nvl)
        if w100 is not None:
            self._w100.append(_placed(w100, define))

    # -- W40 --

    @staticmethod
    def checks_line(stmt: object) -> bool:
        """Whether ``stmt`` is a line the textbox or the full-screen page shows (dialogue
        or narration); the walk's mode picks W40 or W101 (F17)."""
        return (type(getattr(stmt, "body", None)) is TaggedText and hasattr(stmt, "speaker")
                and type(getattr(stmt, "text", None)) is str)

    def _check_line(self, stmt: object) -> None:
        body = self.resolve(stmt)
        if self._full_screen:
            self._check_nvl_line(stmt, body)
            return
        if len(self._w40) < W40_MAX_LINES:
            pages = self.pages(body)
            if pages > 1:
                self._w40.append(_placed(format_message("W40", (pages, self.text_size)), stmt))
        elif not self._one_page(body):
            self._more += 1

    def _check_nvl_line(self, stmt: object, body: TaggedText) -> None:
        """F17 W101: a full-screen line that needs more than one page."""
        ctx = self.nvl_ctx[self.named(getattr(stmt, "speaker", None))]
        if len(self._w101) < W101_MAX_LINES:
            pages = self.pages(body, ctx)
            if pages > 1:
                self._w101.append(_placed(format_message("W101", (pages, self.nvl_size)),
                                          stmt))
        elif not (self.fast_one_page(body, ctx) or LineLayout(body, ctx).is_last(0)):
            self._w101_more += 1

    def named(self, speaker: object) -> bool:
        """Whether a line by ``speaker`` gets a name row on the full-screen page: its
        ``Character`` has a name, or ``name_from``."""
        c = self.G.get(speaker) if type(speaker) is str else None
        return type(c) is Character and (c.name_from is not None or bool(c.name))

    def pages(self, body: TaggedText, ctx: LayoutContext | None = None) -> int:
        """The page count of a resolved ``body`` at the configured size (or in ``ctx``): 1
        by the fast path, else the full layout's."""
        ctx = self.ctx if ctx is None else ctx
        if self.fast_one_page(body, ctx):
            return 1
        return LineLayout(body, ctx).all_pages()

    def _one_page(self, body: TaggedText) -> bool:
        return self.fast_one_page(body) or LineLayout(body, self.ctx).is_last(0)

    def fast_one_page(self, body: TaggedText, ctx: LayoutContext | None = None) -> bool:
        """The fast path: True only when ``body`` surely fits one page (of ``ctx``, default
        the textbox's); False means "lay it out"."""
        if ctx is None:
            ctx = self.ctx
            if not self._fast:
                return False
        elif ctx.height < 2 * round(LINE_PITCH * ctx.text_size):
            return False
        parts: list[str] = []
        faces: set[Face] = set()
        for piece in body.pieces:
            if type(piece) is Span:
                style = piece.style
                if style.size != 1.0 or "\n" in piece.text:
                    return False
                parts.append(piece.text)
                faces.add(face_for(style.bold, style.italic))
        if not parts:
            return True
        text = render_safe("".join(parts))
        limit = ctx.width
        return all(self._width(face, text, ctx) <= limit for face in faces)

    @staticmethod
    def _width(face: Face, text: str, ctx: LayoutContext) -> int:
        source = ctx.faces.faces[face]
        font = ctx.assets.font(source.ref, ctx.text_size, bundled=source.bundled,
                               synth=source.synth).font
        return font.size(text)[0]

    def resolve(self, stmt: object) -> TaggedText:
        """``stmt``'s body as the check measures it: ``{var}`` as its default's literal or
        its define's value (else ""), and the speaker's ``text_color``/``text_italic``."""
        return self.resolve_body(stmt.body,                         # type: ignore[attr-defined]
                                 getattr(stmt, "speaker", None))

    def resolve_body(self, body: TaggedText, speaker: object) -> TaggedText:
        """``resolve`` for a body and its speaker (None: narration or a choice)."""
        c = self.G.get(speaker) if type(speaker) is str else None
        color: str | None = None
        italic = False
        if type(c) is Character:
            written = c.options.get("text_color")
            color = written.lower() if type(written) is str else None
            italic = c.options.get("text_italic") is True
        pieces = body.pieces
        if color is None and not italic and not any(type(p) in (VarMark, NameMark)
                                                     for p in pieces):
            return body
        out: list = []
        for piece in pieces:
            kind = type(piece)
            if kind is VarMark:
                text = self.shown(piece.name)
                if not text:
                    continue
                piece, kind = Span(text, piece.style), Span
            elif kind is NameMark:      # F30: measured as the fallback word (or its variable)
                text = getattr(self.program, "username_fallback", "") if piece.var is None                     else self.shown(piece.var)
                out.append(Span(text, replace(_based(piece.style, color, italic),
                                              username=True)))
                continue
            if kind is Span:
                style = _based(piece.style, color, italic)
                last = out[-1] if out else None
                if type(last) is Span and last.style == style:
                    out[-1] = Span(last.text + piece.text, style)
                else:
                    out.append(Span(piece.text, style))
            else:
                out.append(piece)
        return TaggedText(tuple(out), body.auto_next)

    def shown(self, name: str) -> str:
        """The text a ``{var=name}`` is measured as (cached per name)."""
        text = self._shown.get(name)
        if text is None:
            value: object = _UNSET
            default = self._defaults.get(name)
            if default is not None:
                try:
                    value = ast.literal_eval(default.value.source)
                except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                    value = _UNSET
            elif name in self._define_names:
                value = self.G.get(name, _UNSET)
            shown = None if value is _UNSET else format_value(value)
            text = self._shown[name] = shown or ""
        return text


def w47_more(count: int) -> str:
    """The one line after ``W47_MAX_CHOICES`` W47 records, in W40b's shape. The text lives
    here until F02's ``messages.py`` gains a ``W47b`` template (its owner's file)."""
    return f"…and {count:,} more choices need more than one line."


def _based(style: Style, color: str | None, italic: bool) -> Style:
    if color is not None and style.color is None:
        style = replace(style, color=color)
    if italic and not style.italic:
        style = replace(style, italic=True)
    return style


def _placed(message: str, node: object) -> str:
    """``script/main.vns, line 7: <message>`` (F02's L prefix)."""
    return _placed_at(message, node, getattr(node, "line", None))


def _placed_at(message: str, node: object, line: int | None) -> str:
    """``message`` at ``line`` of ``node``'s file (a choice's line in its menu's file)."""
    file = getattr(node, "file", None)
    return UserFacingError(message, file=getattr(file, "ref", None), line=line).format()


def _is_menu(stmt: object) -> bool:
    """F07's ``Menu`` (duck-typed: ``engine.app`` reaches ``engine.script`` only through
    ``loading.py``): a ``choices`` tuple and a ``question`` slot."""
    return type(getattr(stmt, "choices", None)) is tuple and hasattr(stmt, "question")


def text_launch_check(app: "App", program: object, G: Mapping[str, object]
                      ) -> TextLaunchCheck | None:
    """The launch's check, made after ``install_story`` (dev runs only; None otherwise or
    with no textbox). W47 measures with the choices' faces (``app.choices``)."""
    textbox = getattr(app, "textbox", None)
    if not app.dev or textbox is None:
        return None
    choices = getattr(app, "choices", None)
    return TextLaunchCheck(program, G, assets=app.assets, faces=textbox.faces,
                           theme=app.config.theme.textbox,
                           choice_theme=app.config.theme.choice,
                           choice_faces=getattr(choices, "faces", None),
                           nvl=nvl_look(app.config.theme))


__all__ = ["NAME_MIN_RATIO", "TEXT_CHECK_CHARS", "TEXT_CHECK_CHUNK", "TEXT_MIN_RATIO", "W40_MAX_LINES",
           "W47_MAX_CHOICES", "W101_MAX_LINES", "TextLaunchCheck", "box_colors_warning", "box_contrast",
           "character_warnings", "composite", "contrast_ratio", "install_blips", "install_nvl", "install_textbox",
           "nvl_character_warning", "nvl_colors_warnings", "relative_luminance", "resolve_faces",
           "text_launch_check", "w47_more"]

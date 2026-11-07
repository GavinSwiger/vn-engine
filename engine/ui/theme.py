"""The resolved UI theme: tokens → paint styles, UI faces, frame images, and words.

Why this module exists: every F10 screen reads its look from ``[theme.*]`` and its text from
``[words]`` (PR-F10-14 to 18), but those values need one pass at ``install_ui`` before they can
be drawn: fonts and images are checked once, a bad one falls back to the drawn look or the
text box font with one warning (W64), an empty word keeps its default (W65), and in dev runs a
word that its button has to cut is reported (W68) (F10 ``04`` §7.10 steps 1–3 and 5). The
result is immutable for the launch:

- ``UiTheme`` is the painter's ``StyleSource``: ``style(area, state)`` turns the tokens of an
  area (``panel``, ``button``, ``toggle``, ``slider``, ``list``, …) into a ``PaintStyle``.
- The UI ``FaceSet`` uses ``ui.text_font`` / ``ui.bold_font`` and falls back to the textbox's
  faces (F05), which fall back to bundled Noto Sans. Headings and title text use the bold
  face (a bundled ``Face.BOLD`` when no font is set).
- ``Words`` gives a word by key: an override (F32's ``UiOverrides``, step 6), else the
  configured word, else the default.

Warnings go to log area ``ui`` with their code in ``extra``, once per cause. Their texts are
03-ui "Warnings"; forms 03-ui leaves open are drafted here (G1, G7) for the narrative
designer's review. Every config value in a message passes through ``echo()``.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from engine.core.config_schema import Config, ThemeConfig, WordsConfig, word_fields
from engine.core.logsetup import get_logger
from engine.core.redact import echo
from engine.render.frames import FrameSpec
from engine.render.text import Face, FontSpec, Synth, text_width
from engine.render.textlayout import BUNDLED_FACES, FaceSet, FaceSource
from engine.ui.layouts import (
    CONFIRM_BUTTON_MAX,
    Measure,
    QuickMenuLayout,
    confirm_message_width,
    fit_message,
    quick_menu_layout,
)
from engine.ui.paint import PaintStyle, fit_label

if TYPE_CHECKING:
    from engine.render.assets import AssetManager, AssetProblem, ImageRef

_log = get_logger("ui")

RGB = tuple[int, int, int]

# Frame images per drawn state: name → (theme table, key). The name is also the
# ``UiTheme.frames`` key.
FRAME_TOKENS: Final[dict[str, tuple[str, str]]] = {
    "panel": ("panel", "frame_image"),
    "button": ("button", "frame_image"),
    "button.focused": ("button.focused", "frame_image"),
    "button.pressed": ("button.pressed", "frame_image"),
    "button.selected": ("button.selected", "frame_image"),
    "button.disabled": ("button.disabled", "frame_image"),
    "quick_menu": ("quick_menu", "frame_image"),
    "notice": ("notice", "frame_image"),                # F11
    "save.no_picture": ("save", "no_picture_image"),    # F11: a missing thumbnail's art
    "rollback.mark": ("rollback.mark", "image"),        # F14: the limit mark's picture
    # F20: a visited chart box's picture, per kind (none or unusable: the drawn shape).
    **{f"flowchart.{kind}": (f"flowchart.{kind}", "frame_image")
       for kind in ("start", "chapter", "choice", "scene", "ending", "gate")},
}
ROW_AREAS: Final = ("toggle", "slider", "list")   # rows: no frame at rest, button's focus look

# What a drawn frame stands in for, in W64's "so the drawn … is used".
_FRAME_NOUNS = {"panel": "panel", "button": "button", "quick_menu": "quick menu",
                "notice": "notice", "save": "\"No picture\" placeholder",
                "rollback": "limit mark",                          # F14 (draft)
                "flowchart": "chart box"}                          # F20 (draft)
# W68: where a word is drawn → the token that widens it (None: none can).
_WIDEN = {"title": "[theme.title] button_width", "game": "[theme.menu] button_width",
          "confirm": None, "quick": None}
_PLACE = {"title": "its button", "game": "its button", "confirm": "its button",
          "quick": "the quick menu"}
# W65's example value per key (G7: the example is built from the key; new_game keeps 03-ui's).
_W65_EXAMPLES = {"new_game": "Begin"}

# F10's own entries (04 §7.11), the words W68 checks until the registry (step 6) passes the
# shown entries of each menu.
F10_ENTRY_WORDS: Final[dict[str, tuple[str, ...]]] = {
    "title": ("new_game", "quit"),
    "game": ("return", "main_menu", "quit"),
    "quick": ("hide", "menu"),
}


# --- Words -------------------------------------------------------------------------------------

class Words:
    """Words by key (``[words]`` key = menu id, F10 ``07`` "registry"). ``override(key)`` (F32's
    ``UiOverrides``) wins when it returns a string; else the configured word; a blank configured
    word was already replaced by its default (W65). F65: ``kit`` (``kits.kit_words``) gives the
    device's or kit's word for a key the author didn't write ("Messages" for ``inbox``). v1:
    a word the author writes wins even when it equals the default (``WordsConfig.set_keys``;
    a value other than the default counts as written too)."""

    def __init__(self, config: WordsConfig | None = None, *,
                 override: Callable[[str], str | None] | None = None,
                 kit: Mapping[str, str] | None = None) -> None:
        config = config if config is not None else WordsConfig()
        fields = word_fields()
        self._words: dict[str, str] = {}
        written = getattr(config, "set_keys", frozenset())
        for key, f in fields.items():
            value = getattr(config, f.name)
            if (key in written or value != f.default) and value.strip():
                self._words[key] = value
            elif kit and kit.get(key):
                self._words[key] = kit[key]
            else:
                self._words[key] = f.default
        self.override = override

    def get(self, key: str) -> str:
        """The word for ``key``. An unknown key is a programming error (KeyError)."""
        if self.override is not None:
            found = self.override(key)
            if found is not None:
                return found
        return self._words[key]

    def keys(self) -> list[str]:
        return list(self._words)


def resolve_words(config: WordsConfig, *, log=_log,
                  kit: Mapping[str, str] | None = None) -> Words:
    """``Words`` from ``[words]``; each empty or blank word is W65 and keeps its default (or
    the kit's, F65). A word whose default is empty (``money``: the money item's own title)
    may be left empty."""
    for key, f in word_fields().items():
        if f.default.strip() and not getattr(config, f.name).strip():
            log.warning("%s", w65_text(key, f.default), extra={"code": "W65"})
    return Words(config, kit=kit)


# --- The theme ---------------------------------------------------------------------------------

def font_spec(source: FaceSource, size: int) -> FontSpec:
    """The ``FontSpec`` that draws ``source`` at ``size``."""
    return FontSpec(source.ref, size, source.bundled, source.synth)


def measure_with(assets: "AssetManager", font: FontSpec) -> Measure:
    """A ``layouts.Measure`` (text, size → width) with ``font``'s face at reference size."""
    def measure(text: str, size: int) -> float:
        handle = assets.font(font.ref, size, bundled=font.bundled, synth=font.synth)
        return text_width(handle.font, text)
    return measure


@dataclass(frozen=True)
class UiTheme:
    """The F10 look for one launch (F10 ``04`` §4). Implements ``paint.StyleSource``."""

    cfg: ThemeConfig
    faces: FaceSet = BUNDLED_FACES                         # REGULAR/BOLD/ITALIC/BOLD_ITALIC
    frames: Mapping[str, "ImageRef | None"] = field(default_factory=dict)
    logo: "ImageRef | None" = None
    background: "ImageRef | None" = None
    _styles: dict = field(default_factory=dict, compare=False, repr=False)

    # -- fonts --

    def font(self, size: int, *, bold: bool = False, italic: bool = False) -> FontSpec:
        return font_spec(self.faces.for_style(bold, italic), size)

    @property
    def fade_s(self) -> float:
        return self.cfg.ui.fade_ms / 1000.0

    # -- StyleSource --

    def style(self, area: str, state: str) -> PaintStyle:
        key = (area, state)
        found = self._styles.get(key)
        if found is None:
            found = self._styles[key] = self._build_style(area, state)
        return found

    def _build_style(self, area: str, state: str) -> PaintStyle:
        c = self.cfg
        b = c.button
        marker = b.marker.fill_color
        if area == "panel":
            p = c.panel
            return PaintStyle(
                frame=FrameSpec(p.fill_color, p.fill_opacity, p.border_color, p.border_width,
                                p.corner_radius, p.frame_slice_width),
                image=self.frames.get("panel"), font=self.font(p.text_size),
                text_color=p.text_color, marker_color=marker)
        if area == "panel.heading":
            h = c.panel.heading
            return PaintStyle(font=self.font(h.text_size, bold=True), text_color=h.text_color,
                              marker_color=marker)
        if area in ("button", *ROW_AREAS):
            return self._widget_style(area, state)
        if area == "text_entry":                                       # F52
            return self._text_entry_style(state)
        if area == "list.empty":
            return PaintStyle(font=self.font(c.panel.text_size),
                              text_color=c.list.empty.text_color, marker_color=marker)
        return PaintStyle(font=self.font(c.panel.text_size), text_color=c.panel.text_color,
                          marker_color=marker)

    def _button_frame(self, state: str) -> FrameSpec:
        b = self.cfg.button
        fill, border, width = b.fill_color, b.border_color, b.border_width
        if state == "focused":
            fill, border, width = b.focused.fill_color, b.focused.border_color, \
                b.focused.border_width
        elif state == "pressed":
            fill, border, width = b.pressed.fill_color, b.focused.border_color, \
                b.focused.border_width
        elif state == "selected":
            fill = b.focused.fill_color
        elif state == "disabled":
            width = b.disabled.border_width
        return FrameSpec(fill, b.fill_opacity, border, width, b.corner_radius,
                         b.frame_slice_width)

    def _widget_style(self, area: str, state: str) -> PaintStyle:
        c = self.cfg
        b = c.button
        disabled = state == "disabled"
        if area == "button":
            frame: FrameSpec | None = self._button_frame(state)
            image = self.frames.get("button" if state == "normal" else f"button.{state}")
            size, color = b.text_size, b.text_color
            colors: dict[str, RGB] = {}
        else:
            # Row widgets: no fill or border at rest; the focused look is the button's.
            frame = self._button_frame(state) if state in ("focused", "pressed") else None
            image = None
            size, color = c.panel.text_size, c.panel.text_color
            colors = self._row_colors(area)
        return PaintStyle(
            frame=frame, image=image,
            font=self.font(size, italic=disabled and area == "list"),
            text_color=b.disabled.text_color if disabled else color,
            marker_color=b.marker.fill_color, side_padding=b.side_padding,
            colors=colors)

    def _text_entry_style(self, state: str) -> PaintStyle:
        """F52 (01 §6.1, §6.4): a text field's box, text, placeholder, caret and border. At
        rest the field's own fill and border; focused and pressed F10's focused frame;
        disabled no border and muted text."""
        b = self.cfg.button
        t = {key: text_entry_token(self.cfg, f"text_entry.{key}") for key in TEXT_ENTRY_KEYS}
        if state in ("focused", "pressed"):
            frame = self._button_frame(state)
            frame = FrameSpec(frame.fill_color, t["fill_opacity"], frame.border_color,
                              frame.border_width, b.corner_radius, b.frame_slice_width)
        else:
            width = 0 if state == "disabled" else b.border_width
            frame = FrameSpec(t["fill_color"], t["fill_opacity"], t["border_color"], width,
                              b.corner_radius, b.frame_slice_width)
        text = t["placeholder_color"] if state == "disabled" else t["text_color"]
        return PaintStyle(frame=frame, font=self.font(t["text_size"]), text_color=text,
                          marker_color=b.marker.fill_color, side_padding=b.side_padding,
                          colors={"placeholder": t["placeholder_color"],
                                  "caret": t["caret_color"], "border": t["border_color"]})

    def _row_colors(self, area: str) -> dict[str, RGB]:
        c = self.cfg
        disabled_track = c.button.disabled.track_color
        if area == "toggle":
            return {"track": c.toggle.track_color, "on_track": c.toggle.on.track_color,
                    "on_knob": c.toggle.on.knob_color, "disabled_track": disabled_track}
        if area == "slider":
            s = c.slider
            return {"track": s.track_color, "fill": s.fill_color, "thumb": s.thumb_color,
                    "thumb_border": s.thumb_border_color, "disabled_track": disabled_track}
        lst = c.list
        return {"divider": lst.divider_color, "scrollbar": lst.scrollbar_color,
                "scrollbar_track": lst.scrollbar_track_color, "empty": lst.empty.text_color}

    # -- layouts with this theme's tokens --

    def quick_menu_layout(self, labels: Sequence[str], measure: Measure, *,
                          scale: float = 1.0) -> QuickMenuLayout:
        """``layouts.quick_menu_layout`` with ``[theme.quick_menu]`` and the strip below the
        textbox, ``textbox.bottom_gap`` (I-4)."""
        q = self.cfg.quick_menu
        return quick_menu_layout(labels, measure, scale=scale, text_size=q.text_size,
                                 side_padding=q.side_padding, bottom_gap=q.bottom_gap,
                                 strip=self.cfg.textbox.bottom_gap)


# F52 (01 §6.4, 07 I-8): ``[theme.text_entry]`` tokens follow these when unset.
TEXT_ENTRY_FOLLOWS: Final[dict[str, str]] = {
    "text_entry.fill_color": "button.fill_color",
    "text_entry.fill_opacity": "button.fill_opacity",
    "text_entry.border_color": "button.border_color",
    "text_entry.text_color": "button.text_color",
    "text_entry.text_size": "button.text_size",
    "text_entry.placeholder_color": "button.disabled.text_color",
    "text_entry.caret_color": "button.marker.fill_color",
}
TEXT_ENTRY_KEYS: Final = tuple(path.split(".", 1)[1] for path in TEXT_ENTRY_FOLLOWS)


def text_entry_token(cfg: ThemeConfig, path: str) -> object:
    """A ``text_entry.*`` token with its follow resolved (``TEXT_ENTRY_FOLLOWS``)."""
    node: object = cfg
    for part in path.split("."):
        node = getattr(node, part)
    follows = TEXT_ENTRY_FOLLOWS.get(path)
    if node is None and follows is not None:
        return text_entry_token(cfg, follows)
    return node


def plain_theme(cfg: ThemeConfig | None = None, *, faces: FaceSet = BUNDLED_FACES) -> UiTheme:
    """A theme with no file checks (no frames, logo, or background): tools and tests."""
    return UiTheme(cfg if cfg is not None else ThemeConfig(), faces)


# --- Resolution (install time) -----------------------------------------------------------------

def _token(cfg: ThemeConfig, table: str, key: str) -> object:
    node: object = cfg
    for part in table.split("."):
        node = getattr(node, part)
    return getattr(node, key)


class _Once:
    """Logs each (code, cause) once."""

    def __init__(self, log) -> None:
        self.log = log
        self.seen: set[tuple[str, str]] = set()

    def warn(self, code: str, cause: str, text: str) -> None:
        if (code, cause) in self.seen:
            return
        self.seen.add((code, cause))
        self.log.warning("%s", text, extra={"code": code})


def resolve_theme(config: Config, assets: "AssetManager", *,
                  textbox_faces: FaceSet = BUNDLED_FACES, log=_log) -> UiTheme:
    """F10 ``04`` §7.10 steps 1–2: check the UI fonts and every UI image once (``assets.check``
    logs nothing, so W64 is the only line), fall back with W64, and load the good images."""
    cfg = config.theme
    once = _Once(log)
    ui = cfg.ui

    def checked_font(key: str) -> str | None:
        ref = getattr(ui, key)
        if ref is None:
            return None
        problem = assets.check(ref, "font")
        if problem is None:
            return ref
        once.warn("W64", f"ui.{key}", w64_text("ui", key, ref, problem))
        return None

    text_font, bold_font = checked_font("text_font"), checked_font("bold_font")
    faces = ui_faces(text_font, bold_font, textbox_faces)

    def checked_image(table: str, key: str) -> "ImageRef | None":
        ref = _token(cfg, table, key)
        if ref is None:
            return None
        problem = assets.check(ref, "image")
        if problem is not None:
            once.warn("W64", f"{table}.{key}", w64_text(table, key, ref, problem))
            return None
        image = assets.image(ref)
        return None if image.is_placeholder else image

    frames = {name: checked_image(table, key) for name, (table, key) in FRAME_TOKENS.items()}
    logo = checked_image("title", "logo_image")
    background = checked_image("title", "background_image")
    return UiTheme(cfg, faces, frames, logo, background)


def ui_faces(text_font: str | None, bold_font: str | None,
             textbox_faces: FaceSet = BUNDLED_FACES) -> FaceSet:
    """The UI ``FaceSet``: usable ``ui.text_font``/``ui.bold_font`` (already checked), else the
    textbox's faces (F05's, which fall back to bundled Noto Sans). Italic styles of an author
    font are synthesized, as F05 does (W45 is the textbox's)."""
    tb = textbox_faces.faces
    regular = FaceSource(text_font, Face.REGULAR) if text_font else tb[Face.REGULAR]
    bold = FaceSource(bold_font, Face.BOLD) if bold_font else tb[Face.BOLD]
    italic = FaceSource(text_font, Face.ITALIC, Synth.ITALIC) if text_font else tb[Face.ITALIC]
    if bold_font:
        bold_italic = FaceSource(bold_font, Face.BOLD_ITALIC, Synth.ITALIC)
    elif text_font:
        bold_italic = FaceSource(text_font, Face.BOLD_ITALIC, Synth.BOLD_ITALIC)
    else:
        bold_italic = tb[Face.BOLD_ITALIC]
    return FaceSet({Face.REGULAR: regular, Face.BOLD: bold, Face.ITALIC: italic,
                    Face.BOLD_ITALIC: bold_italic})


# --- W68: words their buttons cut (dev) --------------------------------------------------------

@dataclass(frozen=True)
class LabelCut:
    """One word a fit rule cuts: where (``"title"``, ``"game"``, ``"confirm"``, ``"quick"``),
    the size it was measured at, and the text as drawn."""
    key: str
    place: str
    size: int
    text: str
    shown: str


def label_cuts(theme: UiTheme, words: Words, assets: "AssetManager", *,
               menus: Mapping[str, Iterable[str]] = F10_ENTRY_WORDS) -> list[LabelCut]:
    """Every word that a fit rule ends with "…" at the configured sizes and widths (scale
    1.0): title and sidebar labels (painter's fit, ``fit_label``), Yes/No at the widest
    confirm button, the confirm messages, and the quick-menu labels. ``menus`` maps
    ``"title"``/``"game"``/``"quick"`` to the word keys shown there."""
    c = theme.cfg
    b = c.button
    label_font = theme.font(b.text_size)

    def font_at(size: int):
        return assets.font(label_font.ref, size, bundled=label_font.bundled,
                           synth=label_font.synth).font

    cuts: list[LabelCut] = []

    def check_label(place: str, key: str, width: float) -> None:
        text = words.get(key)
        fit = fit_label(text, font_at, b.text_size, width)
        if fit.truncated:
            cuts.append(LabelCut(key, place, b.text_size, text, fit.text))

    for key in menus.get("title", ()):
        check_label("title", key, c.title.button_width - 2 * b.side_padding)
    for key in menus.get("game", ()):
        check_label("game", key, c.menu.button_width - 2 * b.side_padding)
    for key in ("yes", "no"):
        check_label("confirm", key, CONFIRM_BUTTON_MAX - 2 * b.side_padding)
    message_measure = measure_with(assets, theme.font(c.panel.text_size))
    for key in ("confirm_main_menu", "confirm_quit"):
        text = words.get(key)
        fit = fit_message(text, confirm_message_width(c.confirm.width), c.panel.text_size,
                          message_measure)
        if fit.truncated:
            cuts.append(LabelCut(key, "message", c.panel.text_size, text, fit.lines[-1]))
    quick = list(menus.get("quick", ()))
    if quick:
        q_measure = measure_with(assets, theme.font(c.quick_menu.text_size))
        layout = theme.quick_menu_layout([words.get(k) for k in quick], q_measure)
        for key, item in zip(quick, layout.items, strict=True):
            text = words.get(key)
            if item.label != text:
                cuts.append(LabelCut(key, "quick", layout.text_size, text, item.label))
    return cuts


def warn_label_cuts(theme: UiTheme, words: Words, assets: "AssetManager", *, dev: bool,
                    menus: Mapping[str, Iterable[str]] = F10_ENTRY_WORDS,
                    log=_log) -> list[LabelCut]:
    """W68 (dev only, F10 ``04`` §7.10 step 5) for each ``label_cuts`` row, once per key and
    place. Returns the cuts (empty when not ``dev``)."""
    if not dev:
        return []
    cuts = label_cuts(theme, words, assets, menus=menus)
    once = _Once(log)
    for cut in cuts:
        once.warn("W68", f"{cut.place}.{cut.key}", w68_text(cut))
    return cuts


# --- Message texts (03-ui "Warnings") ----------------------------------------------------------

def _head(table: str, key: str, ref: str) -> str:
    return f'config.toml: [theme.{table}] {key} "{echo(ref)}"'


def w64_text(table: str, key: str, ref: str, problem: "AssetProblem") -> str:
    """W64: a UI font or image that can't be used, and what is used instead."""
    if key in ("text_font", "bold_font"):
        result, kind = "so the text box font is used.", "font"
    elif key == "logo_image":
        result, kind = "so the game's title is shown as text.", "image"
    elif key == "background_image" and table == "minigame":
        result, kind = "so the gradient is used.", "image"                    # F23 draft
    elif key == "background_image":
        result, kind = "so the plain title background is used.", "image"      # G1 draft
    else:
        noun = _FRAME_NOUNS.get(table.split(".")[0], "frame")
        result, kind = f"so the drawn {noun} is used.", "image"
    head = _head(table, key, ref)
    if problem.kind == "unreadable":
        return f"{head} couldn't be read as {'a font' if kind == 'font' else 'an image'}, {result}"
    text = f"{head} doesn't exist, {result}"
    if problem.suggestion is not None:
        text += f' Did you mean "{echo(problem.suggestion)}"?'
    return text


def w65_text(key: str, default: str) -> str:
    """W65: an empty word keeps its default."""
    example = _W65_EXAMPLES.get(key, default)
    return (f'config.toml: [words] {key} is empty, so "{echo(default)}" is shown. Write the '
            f'words to show, e.g. {key} = "{echo(example)}".')


def w68_text(cut: LabelCut) -> str:
    """W68: a word its button (or the dialog, or the quick menu) cuts with "…"."""
    head = f'config.toml: [words] {cut.key} "{echo(cut.text)}"'
    if cut.place == "message":
        return (f"{head} doesn't fit the dialog at text size {cut.size}, so it ends as "
                f'"{echo(cut.shown)}". Use fewer words, or widen the dialog with '
                "[theme.confirm] width.")
    widen = _WIDEN.get(cut.place)
    advice = "Use fewer words." if widen is None else \
        f"Use fewer words, or widen the button with {widen}."
    return (f"{head} doesn't fit {_PLACE.get(cut.place, 'its button')} at text size "
            f'{cut.size}, so it shows as "{echo(cut.shown)}". {advice}')


__all__ = ["F10_ENTRY_WORDS", "FRAME_TOKENS", "LabelCut", "TEXT_ENTRY_FOLLOWS", "UiTheme",
           "Words", "font_spec", "text_entry_token",
           "label_cuts", "measure_with", "plain_theme", "resolve_theme", "resolve_words",
           "ui_faces", "w64_text", "w65_text", "w68_text", "warn_label_cuts"]

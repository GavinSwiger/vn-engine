"""``install_chapters``: F18's chapter cards and chapter saves wired into one launch (F18
``SPEC.md`` §5; ``07-architecture-review.md`` I-5, I-6, I-8).

Why this module exists: the runtime holds a ``ChapterStarted`` and puts the card in
``ShowStage.card``, but ``render`` and ``ui`` never import ``app`` and the runtime never reads
config, so the app joins them here, once per launch, after ``install_saves``:

- The painter: a ``CardPainter`` built from ``[theme.chapter]`` (fonts: the token's own
  ``text_font``, else ``ui.text_font`` for the heading and ``ui.bold_font`` for the title,
  through F10's ``UiTheme`` faces) goes on ``app.stage_screen.view.card_painter``. F49
  (07 I-1): its style follows the shell's current look (a style's color scheme sets
  ``chapter.*``), re-derived once per look change with the same checked fonts.
- ``ChapterStarted`` → F11's ``request_autosave()`` with ``[chapter] autosave`` (true): one
  Auto save at the next new checkpoint (I-6). The handler is always registered (the router
  raises on a command with none).
- ``[chapter] name_saves = false`` clears F11's chapter provider, so saves describe their
  line; true keeps ``install_saves``'s ``ChapterIndex.save_label`` provider.
- W111 (dev runs, at launch, area ``ui``, I-8): a card text color under 4.5:1 on the card's
  fill (over black and over white when ``fill_opacity`` < 1). W64's form for a chapter font
  that can't be used (drafted here).

The story's chapters are ``interp.chapters`` (F20 reads them there); this module imports no
``engine.script`` (I-5).
"""

import math
from typing import TYPE_CHECKING, Final

from engine.app.text_check import BLACK, WHITE, composite, contrast_ratio
from engine.core.config_schema import ChapterTheme
from engine.core.logsetup import get_logger
from engine.core.redact import echo
from engine.render.text import FontSpec
from engine.runtime.commands import ChapterStarted
from engine.ui.builtin.title_card import CardPainter, CardStyle
from engine.ui.theme import plain_theme

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.render.assets import AssetProblem
    from engine.ui.theme import UiTheme

_log = get_logger("ui")

RGB = tuple[int, int, int]
MIN_CONTRAST: Final = 4.5             # W111: both card texts


def card_style(cfg: ChapterTheme, theme: "UiTheme", *, fonts: dict[str, str | None]
               ) -> CardStyle:
    """``[theme.chapter]`` as a ``CardStyle``. ``fonts`` holds the usable ``text_font`` of
    ``"heading"`` and ``"title"`` (None: the UI face, regular and bold)."""
    heading, title = cfg.heading, cfg.title
    heading_ref, title_ref = fonts.get("heading"), fonts.get("title")
    return CardStyle(
        fill_color=cfg.fill_color, fill_opacity=cfg.fill_opacity,
        heading_font=(FontSpec(heading_ref, heading.text_size) if heading_ref
                      else theme.font(heading.text_size)),
        heading_color=heading.text_color,
        title_font=(FontSpec(title_ref, title.text_size) if title_ref
                    else theme.font(title.text_size, bold=True)),
        title_color=title.text_color, gap=cfg.gap, max_width=cfg.max_width)


# --- W111: card contrast (dev, launch) -----------------------------------------------------------

def card_ratio(cfg: ChapterTheme, part: str) -> float:
    """The worse contrast of ``part``'s (``"heading"``, ``"title"``) text color on the card:
    the opaque fill, or the fill at ``fill_opacity`` over pure black and over pure white."""
    color: RGB = getattr(cfg, part).text_color
    if cfg.fill_opacity >= 1.0:
        return contrast_ratio(color, cfg.fill_color)
    return min(contrast_ratio(color, composite(cfg.fill_color, cfg.fill_opacity, backdrop))
               for backdrop in (BLACK, WHITE))


def w111_text(part: str, color: RGB, ratio: float) -> str:
    """W111 (SPEC §3), the ratio floored to one decimal as W67's."""
    hex_color = "#{:02X}{:02X}{:02X}".format(*color)
    floored = math.floor(ratio * 10 + 1e-9) / 10
    return (f'config.toml: [theme.chapter] {part}.text_color "{hex_color}" has a contrast of '
            f"{floored:.1f}:1 on the chapter card, under {MIN_CONTRAST:g}:1, so players may "
            "not read it.")


def contrast_warnings(cfg: ChapterTheme) -> list[str]:
    """W111's text for the heading and the title, in that order, when under 4.5:1."""
    out = []
    for part in ("heading", "title"):
        ratio = card_ratio(cfg, part)
        if ratio < MIN_CONTRAST:
            out.append(w111_text(part, getattr(cfg, part).text_color, ratio))
    return out


def w64_chapter_text(part: str, ref: str, problem: "AssetProblem") -> str:
    """W64's form for ``[theme.chapter.<part>] text_font`` (drafted here, F18)."""
    face = "bold " if part == "title" else ""
    head = f'config.toml: [theme.chapter.{part}] text_font "{echo(ref)}"'
    result = f"so the menus' {face}font is used."
    if problem.kind == "unreadable":
        return f"{head} couldn't be read as a font, {result}"
    text = f"{head} doesn't exist, {result}"
    if problem.suggestion is not None:
        text += f' Did you mean "{echo(problem.suggestion)}"?'
    return text


# --- the install ---------------------------------------------------------------------------------

def _usable_fonts(app: "App", cfg: ChapterTheme, log) -> dict[str, str | None]:
    assets = getattr(app, "assets", None)
    fonts: dict[str, str | None] = {}
    for part in ("heading", "title"):
        ref = getattr(cfg, part).text_font
        if ref is None or assets is None:
            fonts[part] = None
            continue
        problem = assets.check(ref, "font")
        if problem is not None:
            log.warning("%s", w64_chapter_text(part, ref, problem), extra={"code": "W64"})
            ref = None
        fonts[part] = ref
    return fonts


def install_chapters(app: "App", *, log=_log) -> CardPainter | None:
    """Once per launch, after ``install_saves``: register ``ChapterStarted``, set the card
    painter on the stage (None without one: an App wired by hand), apply ``name_saves``,
    and log W111 in dev runs."""
    config = app.config
    saves = getattr(app, "saves", None)
    autosave = config.chapter.autosave

    def started(cmd: ChapterStarted) -> None:
        if autosave and saves is not None:
            saves.request_autosave()

    app.router.register(ChapterStarted, started)
    if saves is not None and not config.chapter.name_saves:
        saves.set_chapter_provider(None)
    cfg = config.theme.chapter
    if app.dev:
        for text in contrast_warnings(cfg):
            log.warning("%s", text, extra={"code": "W111"})
    stage = getattr(app, "stage_screen", None)
    if stage is None:
        return None
    shell = getattr(app, "shell", None)
    theme = shell.theme if shell is not None else plain_theme(config.theme)
    fonts = _usable_fonts(app, cfg, log)
    painter = CardPainter(card_style(cfg, theme, fonts=fonts), dev=app.dev)
    stage.view.card_painter = painter
    if shell is not None:
        shell.add_look_listener(
            lambda look: painter.restyle(card_style(look.cfg.chapter, look, fonts=fonts)))
    return painter


__all__ = ["MIN_CONTRAST", "card_ratio", "card_style", "contrast_warnings",
           "install_chapters", "w111_text", "w64_chapter_text"]

"""``ConfirmScreen``: the one Yes/No dialog (F10 ``03`` "Confirm dialog", UI-F10-11).

Why this module exists: returning to the title, quitting, and F11's overwrite, delete, and
load questions all ask the same way, so there is one dialog (F10 ``07`` "Overlap and reuse").
It is a modal ``MenuScreen`` over everything below, which it captures once and dims again at
``confirm.dim_opacity`` (``CapturedBackdrop`` without the scene kept, ``04`` §7.6).

Layout (``layouts.confirm_layout``): a ``confirm.width`` panel centred on the canvas; the
message wrapped at width − 96, at most 6 lines, then smaller text (by 2, not below 24), then
"…" (``layouts.fit_message``); Yes left and No right, 32 apart, 32 below the message. One
group, not a column, so Left/Right move between Yes and No without wrapping. No is the
default. Back means No; Start does nothing; clicks outside the panel do nothing. Yes and No
close the dialog first and run their callback after it has left the stack. With
``yes_cuts`` (the shell's Main Menu and Quit questions) Yes removes the dialog at once, with
no closing fade, because its answer takes the whole picture away in that frame (a fade to
black, or the exit; ``04`` §7.7.4 step 2).
"""

from collections.abc import Callable

from engine.ui.backdrop import CapturedBackdrop
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import (
    ConfirmLayout,
    MessageFit,
    confirm_layout,
    confirm_message_width,
    fit_message,
    scaled,
)
from engine.ui.menu_screen import MenuScreen, MenuShell
from engine.ui.nav import InputKind
from engine.ui.paint import Painter
from engine.ui.theme import measure_with
from engine.ui.widgets import Button


class ConfirmScreen(MenuScreen):
    """A Yes/No question. ``message`` is the text shown (a ``[words]`` value or a feature's
    own); ``yes``/``no`` are the ``[words]`` keys of the two labels."""

    def __init__(self, shell: MenuShell, message: str, on_yes: Callable[[], None],
                 on_no: Callable[[], None] | None = None, *, yes: str = "yes",
                 no: str = "no", by: InputKind, fade: bool = True,
                 yes_cuts: bool = False) -> None:
        self.message = message
        self.yes_cuts = yes_cuts
        self.on_yes = on_yes
        self.on_no = on_no
        self.yes_key = yes
        self.no_key = no
        cfg = shell.theme.cfg
        words = shell.words
        self.yes_button = Button(lambda: words.get(yes), self._choose_yes)
        self.no_button = Button(lambda: words.get(no), self._choose_no)
        self.layout: ConfirmLayout | None = None
        self.fit: MessageFit | None = None
        backdrop = CapturedBackdrop(shell.assets, cfg.menu.dim_color, cfg.confirm.dim_opacity,
                                    keep_scene=False)
        super().__init__(shell, by=by, fade=fade, backdrop=backdrop)

    def on_enter(self) -> None:
        others = [s for s in self.shell.stack if isinstance(s, ConfirmScreen) and s is not self]
        assert not others, "only one confirm dialog may be open at a time"

    # -- layout --

    def build(self) -> None:
        theme = self.shell.theme
        cfg = theme.cfg
        scale = self.painter.text_scale()
        message_size = scaled(cfg.panel.text_size, scale)
        self.fit = fit_message(self.message, confirm_message_width(cfg.confirm.width),
                               message_size, measure_with(self.shell.assets,
                                                          theme.font(message_size)))
        label_size = scaled(cfg.button.text_size, scale)
        label_measure = measure_with(self.shell.assets, theme.font(label_size))
        words = self.shell.words
        self.layout = confirm_layout(
            len(self.fit.lines), message_size=self.fit.size, scale=scale,
            text_size=cfg.button.text_size, height=cfg.button.height, width=cfg.confirm.width,
            yes_label_width=label_measure(words.get(self.yes_key), label_size),
            no_label_width=label_measure(words.get(self.no_key), label_size),
            button_width=cfg.confirm.button_width)
        self.yes_button.box = self.layout.yes
        self.no_button.box = self.layout.no
        self.scope.set_groups([FocusGroup([self.yes_button, self.no_button])])
        self.scope.default_widget = self.no_button
        self.revision += 1

    def layer_box(self) -> Box:
        assert self.layout is not None
        return self.layout.panel

    # -- actions --

    def _choose_yes(self) -> None:
        if self.yes_cuts:
            self.fade_s = 0.0                     # removed in this frame, then on_yes
        self.close(then=self.on_yes)

    def _choose_no(self) -> None:
        self.close(then=self.on_no)

    def back(self) -> None:
        self._choose_no()

    # -- drawing --

    def draw_content(self, p: Painter) -> None:
        assert self.layout is not None and self.fit is not None
        layout, fit = self.layout, self.fit
        cfg = self.shell.theme.cfg
        p.panel(layout.panel)
        font = self.shell.theme.font(fit.size)
        cx = layout.panel.x + layout.panel.w / 2
        for index, line in enumerate(fit.lines):
            if line:
                p.canvas.draw_text(line, font, cfg.panel.text_color,
                                   (cx, layout.message.y + index * layout.message_pitch),
                                   anchor="midtop")
        self.draw_widgets(p)


__all__ = ["ConfirmScreen"]

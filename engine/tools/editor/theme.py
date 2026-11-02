"""Studio's colors in one place: VS Code's Dark+ (F44 ``03-ui.md`` §1.2, §6; F45 ``01-design.md``
§6, all amended 2026-11-02, user: VS Code dark).

``THEME`` maps a token name (VS Code's own where there is one) to a ``#RRGGBB`` color. Every
module of the editor reads its colors from here, so another palette (a light theme as a
setting) is one more dict. ``CONTRAST_PAIRS`` lists every text-on-background pair the window
draws, with the ratio it must reach (4.5:1 for text, 3:1 for markers' surroundings, focus
rings and link lines); ``tests`` check them all.

Dark+ colors nudged lighter for contrast (03 §7): comments ``#6A9955`` -> ``#74A160`` (4.5:1
on the current-line highlight). Selected text is drawn in the plain text color, since no
Dark+ syntax color reaches 4.5:1 on the selection ``#264F78``.

``style_ttk(root)`` switches ttk to ``clam`` (the native Windows theme ignores colors) and
styles every ttk widget the editor uses. ``tkinter`` is imported only inside the functions
that need it, so ``syntax`` (which reads the syntax colors) stays importable without Tk.
"""

import sys

THEME: dict[str, str] = {
    # The editor and its gutter.
    "editor.background": "#1E1E1E",
    "editor.foreground": "#D4D4D4",
    "editor.selection": "#264F78",
    "editor.inactiveSelection": "#3A3D41",
    "editor.cursor": "#AEAFAD",
    "editor.lineHighlight": "#2A2D2E",
    "editor.jumpHighlight": "#322E16",
    "gutter.background": "#1E1E1E",
    "gutter.foreground": "#858585",
    "gutter.activeForeground": "#C6C6C6",
    "marker.error": "#F14C4C",
    "marker.warning": "#CCA700",
    # Syntax (Dark+).
    "syntax.comment": "#74A160",
    "syntax.keyword": "#569CD6",
    "syntax.label": "#DCDCAA",
    "syntax.speaker": "#4EC9B0",
    "syntax.quote": "#CE9178",
    "syntax.textTag": "#C586C0",
    "syntax.python": "#9CDCFE",
    # Workbench.
    "foreground": "#CCCCCC",                # UI text: labels, the tree, tabs
    "muted": "#9D9D9D",                     # hints, read-only messages, kind words
    "link": "#4DAAFC",
    "focusBorder": "#007FD4",
    "border": "#3C3C3C",
    "sideBar.background": "#252526",
    "sideBarTitle.foreground": "#BBBBBB",
    "panel.background": "#1E1E1E",
    "panelTitle.background": "#252526",
    "panelTitle.foreground": "#E7E7E7",
    "sash": "#252526",
    "tab.activeBackground": "#1E1E1E",
    "tab.activeForeground": "#FFFFFF",
    "tab.inactiveBackground": "#2D2D2D",
    "tab.inactiveForeground": "#969696",
    "tab.barBackground": "#252526",
    "list.activeSelection": "#04395E",
    "list.activeSelectionForeground": "#FFFFFF",
    "list.inactiveSelection": "#37373D",
    "button.background": "#0E639C",
    "button.hoverBackground": "#1177BB",
    "button.foreground": "#FFFFFF",
    "button.secondaryBackground": "#3A3D41",
    "button.secondaryHoverBackground": "#45494E",
    "button.disabledBackground": "#2D2D30",
    "button.disabledForeground": "#808080",
    "input.background": "#3C3C3C",
    "input.foreground": "#CCCCCC",
    "scrollbar.thumb": "#424242",
    "scrollbar.thumbHover": "#4F4F4F",
    "widget.background": "#252526",         # the completion list and the dialogs
    "widget.border": "#454545",
    "statusBar.background": "#007ACC",
    "statusBar.foreground": "#FFFFFF",
    "statusBar.hoverBackground": "#0069B3",
    # Story map.
    "map.box": "#252526",
    "map.boxBorder": "#3C3C3C",
    "map.ring": "#007FD4",
    "map.link": "#808080",
    "map.ending": "#C586C0",                # an ending label's double border (2026-11-02)
    "map.chapter": "#DCDCAA",               # a box's chapter name
    "map.minigame": "#4EC9B0",              # a box's minigame tag
}

TEXT_MIN = 4.5                              # WCAG AA for text
GRAPHIC_MIN = 3.0                           # focus rings, link lines (WCAG 1.4.11)

# (foreground token, background token, minimum ratio): every pair the window draws.
_TEXT_BACKGROUNDS = ("editor.background", "editor.lineHighlight", "editor.jumpHighlight")
_SYNTAX = ("editor.foreground", "syntax.comment", "syntax.keyword", "syntax.label",
           "syntax.speaker", "syntax.quote", "syntax.textTag", "syntax.python")
CONTRAST_PAIRS: tuple[tuple[str, str, float], ...] = (
    *((fg, bg, TEXT_MIN) for fg in _SYNTAX for bg in _TEXT_BACKGROUNDS),
    ("editor.foreground", "editor.selection", TEXT_MIN),            # selected text
    ("editor.foreground", "editor.inactiveSelection", TEXT_MIN),
    ("editor.foreground", "input.background", TEXT_MIN),            # start values
    ("editor.foreground", "list.activeSelection", TEXT_MIN),        # chosen problem row
    ("link", "panel.background", TEXT_MIN),
    ("link", "list.activeSelection", TEXT_MIN),
    ("muted", "editor.background", TEXT_MIN),
    ("muted", "sideBar.background", TEXT_MIN),
    ("muted", "widget.background", TEXT_MIN),
    ("muted", "map.box", TEXT_MIN),
    ("gutter.foreground", "gutter.background", TEXT_MIN),
    ("gutter.activeForeground", "gutter.background", TEXT_MIN),
    ("marker.error", "gutter.background", TEXT_MIN),                # letters E and W
    ("marker.warning", "gutter.background", TEXT_MIN),
    ("foreground", "editor.background", TEXT_MIN),
    ("foreground", "sideBar.background", TEXT_MIN),
    ("foreground", "widget.background", TEXT_MIN),
    ("foreground", "input.background", TEXT_MIN),
    ("foreground", "list.inactiveSelection", TEXT_MIN),
    ("list.activeSelectionForeground", "list.activeSelection", TEXT_MIN),
    ("sideBarTitle.foreground", "sideBar.background", TEXT_MIN),
    ("panelTitle.foreground", "panelTitle.background", TEXT_MIN),
    ("tab.activeForeground", "tab.activeBackground", TEXT_MIN),
    ("tab.inactiveForeground", "tab.inactiveBackground", TEXT_MIN),
    ("button.foreground", "button.background", TEXT_MIN),
    ("button.foreground", "button.hoverBackground", TEXT_MIN),
    ("button.foreground", "button.secondaryBackground", TEXT_MIN),
    ("button.foreground", "button.secondaryHoverBackground", TEXT_MIN),
    ("statusBar.foreground", "statusBar.background", TEXT_MIN),
    ("statusBar.foreground", "statusBar.hoverBackground", TEXT_MIN),
    ("editor.foreground", "map.box", TEXT_MIN),                     # a box's label name
    ("focusBorder", "editor.background", GRAPHIC_MIN),
    ("focusBorder", "sideBar.background", GRAPHIC_MIN),
    ("focusBorder", "widget.background", GRAPHIC_MIN),
    ("map.ring", "editor.background", GRAPHIC_MIN),
    ("map.link", "editor.background", GRAPHIC_MIN),
    ("map.ending", "editor.background", GRAPHIC_MIN),
    ("map.chapter", "map.box", TEXT_MIN),
    ("map.minigame", "editor.background", TEXT_MIN),
)

STATUS_BAR_PX = 22                          # at 100 % scaling (96 dpi)


def luminance(color: str) -> float:
    """WCAG relative luminance of ``#RRGGBB``."""
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two ``#RRGGBB`` colors (1.0 to 21.0)."""
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def scale_of(root: object) -> float:
    """Screen pixels per CSS pixel: 1.0 at 96 dpi, 1.5 at 150 % (when Tk knows the DPI)."""
    try:
        return max(1.0, float(root.winfo_fpixels("1i")) / 96.0)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001  (a missing display: draw at 100 %)
        return 1.0


def style_ttk(root: object) -> list[object]:
    """Switch ttk to ``clam`` on ``root`` and style every ttk widget Studio uses (frames,
    labels, buttons, the tree, the notebook, scrollbars, entries, check boxes, combo boxes),
    plus the classic widgets' option defaults (menus, the combo box's drop-down list).
    Returns the fonts the styles name: keep them, or Tk deletes them."""
    from tkinter import font as tkfont
    from tkinter import ttk

    t = THEME
    scale = scale_of(root)
    style = ttk.Style(root)
    style.theme_use("clam")
    ui = tkfont.nametofont("TkDefaultFont", root=root)  # type: ignore[arg-type]
    linespace = ui.metrics("linespace")
    bg, fg = t["editor.background"], t["foreground"]
    style.configure(".", background=bg, foreground=fg, fieldbackground=t["input.background"],
                    bordercolor=t["border"], lightcolor=bg, darkcolor=bg,
                    troughcolor=bg, selectbackground=t["editor.selection"],
                    selectforeground=t["list.activeSelectionForeground"],
                    insertcolor=t["editor.cursor"], focuscolor=t["focusBorder"])
    style.map(".", background=[("disabled", bg)],
              foreground=[("disabled", t["button.disabledForeground"])],
              selectbackground=[("!focus", t["editor.inactiveSelection"])],
              selectforeground=[("!focus", t["editor.foreground"])])
    for name, back in (("TFrame", bg), ("Side.TFrame", t["sideBar.background"]),
                       ("Header.TFrame", t["panelTitle.background"]),
                       ("Dialog.TFrame", t["widget.background"])):
        style.configure(name, background=back, bordercolor=back, lightcolor=back,
                        darkcolor=back)
    style.configure("Focus.TFrame", borderwidth=1, relief="solid",
                    bordercolor=t["focusBorder"], lightcolor=t["focusBorder"],
                    darkcolor=t["focusBorder"])
    style.configure("Pane.TFrame", borderwidth=1, relief="solid", bordercolor=bg,
                    lightcolor=bg, darkcolor=bg)
    header_font = tkfont.Font(root=root, family=ui.actual("family"),  # type: ignore[arg-type]
                              size=max(1, int(ui.actual("size")) - 1), weight="bold")
    style.configure("TLabel", background=bg, foreground=fg)
    style.configure("Side.TLabel", background=t["sideBar.background"], foreground=fg)
    style.configure("SideTitle.TLabel", background=t["sideBar.background"],
                    foreground=t["sideBarTitle.foreground"], font=header_font)
    style.configure("Header.TLabel", background=t["panelTitle.background"],
                    foreground=t["panelTitle.foreground"], font=header_font)
    style.configure("Dialog.TLabel", background=t["widget.background"], foreground=fg)

    # Buttons: primary blue, secondary gray; a solid white focus ring inside the border.
    pad = (round(10 * scale), round(3 * scale))
    for name, back, hover in (
            ("TButton", t["button.background"], t["button.hoverBackground"]),
            ("Secondary.TButton", t["button.secondaryBackground"],
             t["button.secondaryHoverBackground"])):
        style.configure(name, background=back, foreground=t["button.foreground"],
                        bordercolor=back, lightcolor=back, darkcolor=back, relief="flat",
                        padding=pad, focuscolor=t["button.foreground"], focusthickness=1,
                        focussolid=1, anchor="center")
        style.map(name,
                  background=[("disabled", t["button.disabledBackground"]),
                              ("pressed", back), ("active", hover)],
                  bordercolor=[("disabled", t["button.disabledBackground"]),
                               ("active", hover)],
                  lightcolor=[("disabled", t["button.disabledBackground"]),
                              ("active", hover)],
                  darkcolor=[("disabled", t["button.disabledBackground"]), ("active", hover)],
                  foreground=[("disabled", t["button.disabledForeground"])])

    # The project tree.
    side = t["sideBar.background"]
    style.configure("Treeview", background=side, fieldbackground=side, foreground=fg,
                    bordercolor=side, lightcolor=side, darkcolor=side,
                    rowheight=max(round(22 * scale), linespace + 4))
    style.map("Treeview",
              background=[("selected", "focus", t["list.activeSelection"]),
                          ("selected", "!focus", t["list.inactiveSelection"])],
              foreground=[("selected", "focus", t["list.activeSelectionForeground"]),
                          ("selected", "!focus", fg)],
              bordercolor=[("focus", t["focusBorder"])],
              lightcolor=[("focus", t["focusBorder"])])
    style.configure("Treeitem.indicator", foreground=fg)
    style.configure("Treeview.Item", foreground=fg)

    # Notebook tabs.
    bar = t["tab.barBackground"]
    style.configure("TNotebook", background=bar, bordercolor=bar, lightcolor=bg, darkcolor=bg,
                    tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab", background=t["tab.inactiveBackground"],
                    foreground=t["tab.inactiveForeground"], bordercolor=bar,
                    lightcolor=t["tab.inactiveBackground"],
                    padding=(round(12 * scale), round(4 * scale)))
    style.map("TNotebook.Tab",
              background=[("selected", t["tab.activeBackground"])],
              foreground=[("selected", t["tab.activeForeground"])],
              lightcolor=[("selected", t["tab.activeBackground"])],
              padding=[("selected", (round(12 * scale), round(4 * scale)))],
              expand=[("selected", (0, 0, 0, 0))])

    # Scrollbars: a thumb in a trough, no arrows (VS Code's).
    thick = round(12 * scale)
    for orient, sticky in (("Vertical", "ns"), ("Horizontal", "we")):
        layout = [(f"{orient}.Scrollbar.trough", {"sticky": sticky, "children": [
            (f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})]
        for prefix, trough in (("", bg), ("Side.", side)):
            name = f"{prefix}{orient}.TScrollbar"
            style.layout(name, layout)
            style.configure(name, troughcolor=trough, background=t["scrollbar.thumb"],
                            bordercolor=trough, lightcolor=t["scrollbar.thumb"],
                            darkcolor=t["scrollbar.thumb"], arrowsize=thick, gripcount=0,
                            relief="flat")
            style.map(name, background=[("active", t["scrollbar.thumbHover"])],
                      lightcolor=[("active", t["scrollbar.thumbHover"])],
                      darkcolor=[("active", t["scrollbar.thumbHover"])])

    # Inputs: the dialogs' entry and check box, the story map's file filter.
    field = t["input.background"]
    style.configure("TEntry", fieldbackground=field, foreground=t["input.foreground"],
                    bordercolor=field, lightcolor=field, darkcolor=field,
                    insertcolor=t["editor.cursor"], padding=round(3 * scale))
    style.map("TEntry", bordercolor=[("focus", t["focusBorder"])],
              lightcolor=[("focus", t["focusBorder"])])
    style.configure("TCombobox", fieldbackground=field, background=field,
                    foreground=t["input.foreground"], bordercolor=field, lightcolor=field,
                    darkcolor=field, arrowcolor=fg, arrowsize=round(12 * scale))
    style.map("TCombobox",
              fieldbackground=[("readonly", field)], background=[("active", field)],
              foreground=[("readonly", t["input.foreground"])],
              bordercolor=[("focus", t["focusBorder"])],
              lightcolor=[("focus", t["focusBorder"])],
              selectbackground=[("readonly", "focus", t["list.activeSelection"]),
                                ("readonly", field)],
              selectforeground=[("readonly", "focus", t["list.activeSelectionForeground"]),
                                ("readonly", t["input.foreground"])])
    for name, back in (("TCheckbutton", bg), ("Dialog.TCheckbutton", t["widget.background"])):
        style.configure(name, background=back, foreground=fg, indicatorbackground=field,
                        indicatorforeground=t["list.activeSelectionForeground"],
                        upperbordercolor=t["widget.border"],
                        lowerbordercolor=t["widget.border"], focuscolor=fg)
        style.map(name, background=[("active", back)],
                  indicatorbackground=[("pressed", field), ("selected", field)])

    # Classic widgets' defaults: menus (where the platform lets Tk color them) and the
    # combo box's drop-down list.
    widget_bg = t["widget.background"]
    for pattern, value in (
            ("*Menu.background", widget_bg), ("*Menu.foreground", fg),
            ("*Menu.activeBackground", t["list.activeSelection"]),
            ("*Menu.activeForeground", t["list.activeSelectionForeground"]),
            ("*Menu.selectColor", fg), ("*Menu.disabledForeground",
                                        t["button.disabledForeground"]),
            ("*Menu.relief", "flat"), ("*Menu.activeBorderWidth", 0),
            ("*TCombobox*Listbox.background", widget_bg),
            ("*TCombobox*Listbox.foreground", fg),
            ("*TCombobox*Listbox.selectBackground", t["list.activeSelection"]),
            ("*TCombobox*Listbox.selectForeground", t["list.activeSelectionForeground"])):
        root.option_add(pattern, value)  # type: ignore[attr-defined]
    return [header_font]


def dark_title_bar(window: object) -> None:
    """Ask Windows 10/11 for a dark title bar on ``window`` (DWM's immersive dark mode).
    Nothing happens elsewhere or when the call fails."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        window.update_idletasks()  # type: ignore[attr-defined]
        hwnd = int(window.wm_frame(), 16)  # type: ignore[attr-defined]
        value = ctypes.c_int(1)
        for attribute in (20, 19):          # DWMWA_USE_IMMERSIVE_DARK_MODE (and pre-20H1)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                return
    except Exception:  # noqa: BLE001  (cosmetic only)
        return


__all__ = ["CONTRAST_PAIRS", "GRAPHIC_MIN", "STATUS_BAR_PX", "TEXT_MIN", "THEME", "contrast",
           "dark_title_bar", "luminance", "scale_of", "style_ttk"]

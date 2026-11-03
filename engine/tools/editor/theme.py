"""Studio's look in one place: VS Code's Dark Modern (F44 ``03-ui.md`` §1.2, §6; F45 ``01-design.md``
§6; F45 ``08-visual-refresh.md`` §3-§5, user 2026-11-02: D1-D5).

``ROLES`` names each color by its role (``surface``, ``chrome``, ``accent`` …, ``08`` §3);
F46 reuses them. ``THEME`` maps a token name (VS Code's own where there is one) to one role's
``#RRGGBB``. Every module of the editor reads its colors from here, so another palette (a
light theme as a setting) is one more dict. ``CONTRAST_PAIRS`` lists every text-on-background
pair the window draws, with the ratio it must reach (4.5:1 for text, 3:1 for markers'
surroundings, focus rings and link lines); ``tests`` check them all. The editor's own colors
(syntax, gutter, selection, line highlights) are frozen (``08`` §2).

Dark+ colors nudged lighter for contrast (03 §7): comments ``#6A9955`` -> ``#74A160`` (4.5:1
on the current-line highlight). Selected text is drawn in the plain text color, since no
Dark+ syntax color reaches 4.5:1 on the selection ``#264F78``.

``make_fonts(root, scale)`` picks each family from a per-platform stack (never Courier New)
and builds the type scale of ``08`` §4 in pixels times ``scale``. ``style_ttk(root)``
switches ttk to ``clam`` (the native Windows theme ignores colors) and styles every ttk
widget the editor uses. ``declare_dpi_awareness`` runs before the first Tk window on
Windows. ``tkinter`` is imported only inside the functions that need it, so ``syntax``
(which reads the syntax colors) stays importable without Tk.
"""

import sys

# --- Roles (08 §3, dark only) ---------------------------------------------------------------

ROLES: dict[str, str] = {
    "surface": "#1E1E1E",               # editor, map canvas, Asset, Outline, active tab
    "chrome": "#181818",                # side bar, Problems, Help, tabs, menu and status bar
    "raised": "#2B2B2B",                # map boxes, cards
    "overlay": "#252526",               # dialogs, drop-downs, completion
    "overlayBorder": "#454545",
    "input": "#313131",
    "border": "#3C3C3C",                # 1 px edge of inputs and boxes
    "divider": "#2B2B2B",               # the line above the status bar, separators
    "text": "#CCCCCC",
    "textStrong": "#E7E7E7",
    "muted": "#9D9D9D",
    "disabled": "#808080",
    "disabledFill": "#2D2D30",
    "accent": "#0078D4",                # D3: Windows blue
    "accentHover": "#026EC1",
    "accentPressed": "#005A9E",
    "onAccent": "#FFFFFF",
    "secondary": "#313131",
    "secondaryHover": "#3C3C3C",
    "secondaryPressed": "#454545",
    "hover": "#2A2D2E",                 # rows, ghost buttons, menu-bar and status items
    "selection": "#04395E",
    "selectionInactive": "#37373D",
    "focus": "#007FD4",
    "error": "#F14C4C",
    "warning": "#CCA700",
    "info": "#3794FF",
    "success": "#89D185",
    "link": "#4DAAFC",
    "scrollThumb": "#424242",
    "scrollThumbHover": "#4F4F4F",
    "scrollThumbPressed": "#5A5A5A",
}
_R = ROLES

THEME: dict[str, str] = {
    # The editor and its gutter (frozen, 08 §2).
    "editor.background": _R["surface"],
    "editor.foreground": "#D4D4D4",
    "editor.selection": "#264F78",
    "editor.inactiveSelection": "#3A3D41",
    "editor.cursor": "#AEAFAD",
    "editor.lineHighlight": "#2A2D2E",
    "editor.jumpHighlight": "#322E16",
    "gutter.background": _R["surface"],
    "gutter.foreground": "#858585",
    "gutter.activeForeground": "#C6C6C6",
    "marker.error": _R["error"],
    "marker.warning": _R["warning"],
    "info": _R["info"],
    "success": _R["success"],
    # Syntax (Dark+).
    "syntax.comment": "#74A160",
    "syntax.keyword": "#569CD6",
    "syntax.label": "#DCDCAA",
    "syntax.speaker": "#4EC9B0",
    "syntax.quote": "#CE9178",
    "syntax.textTag": "#C586C0",
    "syntax.python": "#9CDCFE",
    # Workbench.
    "foreground": _R["text"],               # UI text: labels, the tree, tabs
    "strongForeground": _R["textStrong"],   # titles
    "muted": _R["muted"],                   # hints, read-only messages, kind words
    "link": _R["link"],
    "focusBorder": _R["focus"],
    "border": _R["border"],
    "divider": _R["divider"],
    "sideBar.background": _R["chrome"],
    "sideBarTitle.foreground": _R["muted"],
    "panel.background": _R["chrome"],       # Problems and Help
    "panelTitle.background": _R["chrome"],  # no separate strip (08 §7)
    "panelTitle.foreground": _R["muted"],
    "sash": _R["chrome"],
    "tab.activeBackground": _R["surface"],
    "tab.activeForeground": "#FFFFFF",
    "tab.inactiveBackground": _R["chrome"],
    "tab.inactiveForeground": _R["muted"],
    "tab.hoverForeground": _R["text"],
    "tab.barBackground": _R["chrome"],
    "tab.hoverBackground": _R["chrome"],
    "tab.indicator": _R["accent"],          # the active tab's 2 px bar (08 §7)
    "card.background": _R["raised"],        # Help's code cards, the story map's banner
    "list.activeSelection": _R["selection"],
    "list.activeSelectionForeground": "#FFFFFF",
    "list.inactiveSelection": _R["selectionInactive"],
    "list.hoverBackground": _R["hover"],
    "button.background": _R["accent"],
    "button.hoverBackground": _R["accentHover"],
    "button.pressedBackground": _R["accentPressed"],
    "button.foreground": _R["onAccent"],
    "button.secondaryBackground": _R["secondary"],
    "button.secondaryHoverBackground": _R["secondaryHover"],
    "button.secondaryPressedBackground": _R["secondaryPressed"],
    "button.secondaryForeground": _R["text"],
    "button.ghostHoverBackground": _R["hover"],
    "button.disabledBackground": _R["disabledFill"],
    "button.disabledForeground": _R["disabled"],
    "input.background": _R["input"],
    "input.foreground": _R["text"],
    "input.border": _R["border"],
    "checkbox.foreground": _R["textStrong"],
    "scrollbar.thumb": _R["scrollThumb"],
    "scrollbar.thumbHover": _R["scrollThumbHover"],
    "scrollbar.thumbPressed": _R["scrollThumbPressed"],
    "widget.background": _R["overlay"],     # the completion list, the dialogs, drop-downs
    "widget.border": _R["overlayBorder"],
    "menubar.background": _R["chrome"],     # D5: the in-window menu bar
    "menubar.foreground": _R["text"],
    "menubar.hoverBackground": _R["hover"],
    "menubar.openBackground": _R["selection"],
    "statusBar.background": _R["chrome"],   # D1: neutral, with a divider above
    "statusBar.foreground": _R["text"],
    "statusBar.hoverBackground": _R["hover"],
    "statusBar.border": _R["divider"],
    "icon.background": _R["accent"],        # the app icon (08 §7)
    "icon.foreground": _R["onAccent"],
    # Story map.
    "map.box": _R["raised"],
    "map.boxBorder": _R["border"],
    "map.boxHoverBorder": "#616161",
    "map.start": _R["accent"],              # the start box's bar inside its left edge
    "map.ring": _R["focus"],
    "map.link": "#808080",
    "map.ending": "#C586C0",                # an ending label's double border (2026-11-02)
    "map.chapter": "#DCDCAA",               # a box's chapter name
    "map.minigame": "#4EC9B0",              # a box's minigame tag
    "map.chip": _R["raised"],               # F46: a choice arrow's text chip (08 §8)
    "map.chipBorder": _R["border"],
    "map.chipText": _R["muted"],
    "map.chipIf": "#569CD6",                # F46: a conditional choice's "if" (syntax.keyword)
    "map.selected": _R["accent"],           # F46: a selected box or arrow, a drop target and
    "map.handle": _R["muted"],              # the arrow-drag line; the arrow handle (01 §6.1)
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
    ("editor.foreground", "panel.background", TEXT_MIN),            # Problems and Help
    ("editor.foreground", "card.background", TEXT_MIN),             # Help's code cards
    ("foreground", "card.background", TEXT_MIN),                    # the map's banner
    ("marker.warning", "card.background", GRAPHIC_MIN),             # the banner's icon
    ("strongForeground", "widget.background", TEXT_MIN),            # dialogs' code spans
    ("strongForeground", "editor.background", TEXT_MIN),            # empty-state titles
    ("tab.activeForeground", "tab.activeBackground", TEXT_MIN),
    ("tab.inactiveForeground", "tab.inactiveBackground", TEXT_MIN),
    ("tab.indicator", "tab.barBackground", GRAPHIC_MIN),
    ("marker.error", "widget.background", GRAPHIC_MIN),             # dialogs' icons
    ("info", "widget.background", GRAPHIC_MIN),
    ("success", "panel.background", GRAPHIC_MIN),                   # "No problems."
    ("link", "panel.background", TEXT_MIN),
    ("link", "list.activeSelection", TEXT_MIN),
    ("muted", "editor.background", TEXT_MIN),
    ("muted", "sideBar.background", TEXT_MIN),
    ("muted", "panel.background", TEXT_MIN),
    ("muted", "widget.background", TEXT_MIN),
    ("muted", "list.hoverBackground", TEXT_MIN),
    ("muted", "map.box", TEXT_MIN),
    ("map.selected", "editor.background", GRAPHIC_MIN),             # F46: accent on surface
    ("map.selected", "map.box", GRAPHIC_MIN),                       # and on raised
    ("map.handle", "map.box", GRAPHIC_MIN),
    ("gutter.foreground", "gutter.background", TEXT_MIN),
    ("gutter.activeForeground", "gutter.background", TEXT_MIN),
    ("marker.error", "gutter.background", TEXT_MIN),                # letters E and W
    ("marker.warning", "gutter.background", TEXT_MIN),
    ("marker.error", "panel.background", TEXT_MIN),
    ("marker.warning", "panel.background", TEXT_MIN),
    ("foreground", "editor.background", TEXT_MIN),
    ("foreground", "sideBar.background", TEXT_MIN),
    ("foreground", "panel.background", TEXT_MIN),
    ("foreground", "widget.background", TEXT_MIN),
    ("foreground", "input.background", TEXT_MIN),
    ("foreground", "list.inactiveSelection", TEXT_MIN),
    ("foreground", "list.hoverBackground", TEXT_MIN),
    ("strongForeground", "editor.background", TEXT_MIN),
    ("strongForeground", "widget.background", TEXT_MIN),
    ("list.activeSelectionForeground", "list.activeSelection", TEXT_MIN),
    ("sideBarTitle.foreground", "sideBar.background", TEXT_MIN),
    ("panelTitle.foreground", "panelTitle.background", TEXT_MIN),
    ("tab.activeForeground", "tab.activeBackground", TEXT_MIN),
    ("tab.inactiveForeground", "tab.inactiveBackground", TEXT_MIN),
    ("tab.hoverForeground", "tab.inactiveBackground", TEXT_MIN),
    ("button.foreground", "button.background", TEXT_MIN),
    ("button.foreground", "button.hoverBackground", TEXT_MIN),
    ("button.foreground", "button.pressedBackground", TEXT_MIN),
    ("button.secondaryForeground", "button.secondaryBackground", TEXT_MIN),
    ("button.secondaryForeground", "button.secondaryHoverBackground", TEXT_MIN),
    ("button.secondaryForeground", "button.secondaryPressedBackground", TEXT_MIN),
    ("foreground", "button.ghostHoverBackground", TEXT_MIN),
    ("menubar.foreground", "menubar.background", TEXT_MIN),
    ("menubar.foreground", "menubar.hoverBackground", TEXT_MIN),
    ("menubar.foreground", "menubar.openBackground", TEXT_MIN),
    ("statusBar.foreground", "statusBar.background", TEXT_MIN),
    ("statusBar.foreground", "statusBar.hoverBackground", TEXT_MIN),
    ("editor.foreground", "map.box", TEXT_MIN),                     # a box's label name
    ("focusBorder", "editor.background", GRAPHIC_MIN),
    ("focusBorder", "sideBar.background", GRAPHIC_MIN),
    ("focusBorder", "widget.background", GRAPHIC_MIN),
    ("button.background", "sideBar.background", GRAPHIC_MIN),       # the Preview button
    ("map.ring", "editor.background", GRAPHIC_MIN),
    ("map.link", "editor.background", GRAPHIC_MIN),
    ("map.ending", "editor.background", GRAPHIC_MIN),
    ("map.start", "map.box", GRAPHIC_MIN),
    ("map.chapter", "map.box", TEXT_MIN),
    ("map.minigame", "editor.background", TEXT_MIN),
    ("map.chipText", "map.chip", TEXT_MIN),                         # F46 choice chips
    ("map.chipIf", "map.chip", TEXT_MIN),
    ("map.link", "map.chip", GRAPHIC_MIN),
)

STATUS_BAR_PX = 22                          # at 100 % scaling (96 dpi)
MENU_BAR_PX = 28

# --- Type (08 §4) ---------------------------------------------------------------------------

# Each family is the first of its stack that Tk knows; None falls back to Tk's own font.
FONT_STACKS: dict[str, dict[str, tuple[str, ...]]] = {
    "win32": {"ui": ("Segoe UI Variable Text", "Segoe UI"),
              "semibold": ("Segoe UI Variable Text Semibold", "Segoe UI Semibold"),
              "mono": ("Cascadia Mono", "Consolas")},
    "darwin": {"ui": (), "semibold": (), "mono": ("Menlo", "Monaco")},
    "other": {"ui": ("Inter", "Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans"),
              "semibold": (),
              "mono": ("JetBrains Mono", "DejaVu Sans Mono", "Liberation Mono")},
}
# Style -> (px at 100 %, family role). A "semibold" role without a semibold family is bold.
TYPE_SCALE: dict[str, tuple[int, str]] = {
    "title": (15, "semibold"),              # empty-state titles
    "body": (13, "ui"),
    "bodyStrong": (13, "semibold"),
    "small": (12, "ui"),
    "caption": (11, "semibold"),
    "detail": (11, "ui"),                   # the story map's file:line, marks, chapter
    "code": (14, "mono"),
    "codeSmall": (13, "mono"),
}
_NEVER = ("Courier New", "Courier")


def font_families(root: object, platform: str = sys.platform) -> dict[str, tuple[str, str]]:
    """Role (``ui``, ``semibold``, ``mono``) -> (family, weight) on ``root``'s Tk."""
    from tkinter import font as tkfont

    known = set(tkfont.families(root))  # type: ignore[arg-type]
    stacks = FONT_STACKS["win32" if platform == "win32" else
                         "darwin" if platform == "darwin" else "other"]

    def first(role: str) -> str | None:
        return next((name for name in stacks[role] if name in known), None)

    ui = first("ui") or tkfont.nametofont("TkDefaultFont", root=root).actual("family")  # type: ignore[arg-type]
    semibold = first("semibold")
    mono = first("mono") or tkfont.nametofont("TkFixedFont", root=root).actual("family")  # type: ignore[arg-type]
    if mono in _NEVER:
        mono = next((name for name in ("Consolas", "Menlo", "DejaVu Sans Mono") if name in known),
                    mono)
    return {"ui": (ui, "normal"),
            "semibold": (semibold, "normal") if semibold else (ui, "bold"),
            "mono": (mono, "normal")}


def make_fonts(root: object, scale: float = 1.0) -> dict[str, object]:
    """The type scale of ``08`` §4 as ``tkfont.Font`` objects (negative, pixel sizes times
    ``scale``), keyed by style name. Tk's own ``TkDefaultFont``, ``TkTextFont``,
    ``TkMenuFont`` and ``TkHeadingFont`` become ``body``, so every widget without a font of
    its own uses it. Keep the dict: Tk deletes a font nobody holds."""
    from tkinter import font as tkfont

    families = font_families(root)
    fonts: dict[str, object] = {}
    for style, (px, role) in TYPE_SCALE.items():
        family, weight = families[role]
        fonts[style] = tkfont.Font(root=root, family=family,  # type: ignore[arg-type]
                                   size=-max(1, round(px * scale)), weight=weight)
    family, _weight = families["ui"]
    body = -max(1, round(TYPE_SCALE["body"][0] * scale))
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name, root=root).configure(  # type: ignore[arg-type]
                family=family, size=body, weight="normal")
        except Exception:  # noqa: BLE001  (a Tk without that named font)
            pass
    return fonts


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
    """Screen pixels per CSS pixel: 1.0 at 96 dpi, 1.5 at 150 % (Tk knows the real DPI once
    ``declare_dpi_awareness`` ran on Windows)."""
    try:
        return max(1.0, float(root.winfo_fpixels("1i")) / 96.0)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001  (a missing display: draw at 100 %)
        return 1.0


def declare_dpi_awareness(platform: str = sys.platform) -> None:
    """Windows: declare per-monitor DPI awareness before Tk starts (as IDLE declares its
    own), so text is drawn at the screen's real size instead of stretched and blurred at
    125-150 % (``08`` §10). Nothing elsewhere, or when the call fails."""
    if platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
        except (AttributeError, OSError):                   # before Windows 8.1
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001  (cosmetic only)
        return


def style_ttk(root: object, fonts: dict[str, object] | None = None,
              scale: float | None = None) -> list[object]:
    """Switch ttk to ``clam`` on ``root`` and style every ttk widget Studio uses (frames,
    labels, primary/secondary/ghost buttons, the trees, the notebook, scrollbars, entries,
    check boxes, combo boxes), plus the classic widgets' option defaults (menus, the combo
    box's drop-down list). Every size is px at 100 % times ``scale``. Returns the fonts the
    styles name: keep them, or Tk deletes them."""
    from tkinter import ttk

    t = THEME
    scale = scale_of(root) if scale is None else scale
    fonts = fonts if fonts is not None else make_fonts(root, scale)

    def px(value: float) -> int:
        return round(value * scale)

    style = ttk.Style(root)  # type: ignore[arg-type]
    style.theme_use("clam")
    body = fonts["body"]
    linespace = body.metrics("linespace")  # type: ignore[attr-defined]
    bg, fg = t["editor.background"], t["foreground"]
    side, dialog = t["sideBar.background"], t["widget.background"]
    style.configure(".", background=bg, foreground=fg, fieldbackground=t["input.background"],
                    bordercolor=t["border"], lightcolor=bg, darkcolor=bg,
                    troughcolor=bg, selectbackground=t["editor.selection"],
                    selectforeground=t["list.activeSelectionForeground"],
                    insertcolor=t["editor.cursor"], focuscolor=t["focusBorder"], font=body)
    style.map(".", background=[("disabled", bg)],
              foreground=[("disabled", t["button.disabledForeground"])],
              selectbackground=[("!focus", t["editor.inactiveSelection"])],
              selectforeground=[("!focus", t["editor.foreground"])])
    for name, back in (("TFrame", bg), ("Side.TFrame", side),
                       ("Header.TFrame", t["panelTitle.background"]),
                       ("Dialog.TFrame", dialog)):
        style.configure(name, background=back, bordercolor=back, lightcolor=back,
                        darkcolor=back)
    style.configure("Focus.TFrame", borderwidth=1, relief="solid",
                    bordercolor=t["focusBorder"], lightcolor=t["focusBorder"],
                    darkcolor=t["focusBorder"])
    style.configure("Pane.TFrame", borderwidth=1, relief="solid", bordercolor=bg,
                    lightcolor=bg, darkcolor=bg)
    style.configure("TLabel", background=bg, foreground=fg)
    style.configure("Side.TLabel", background=side, foreground=fg)
    style.configure("Dialog.TLabel", background=dialog, foreground=fg)
    # Panel headers: caption, upper-case, muted, on the panel's own tone (no strip).
    style.configure("SideTitle.TLabel", background=side,
                    foreground=t["sideBarTitle.foreground"], font=fonts["caption"])
    style.configure("Header.TLabel", background=t["panelTitle.background"],
                    foreground=t["panelTitle.foreground"], font=fonts["caption"])
    style.configure("Title.TLabel", background=bg, foreground=t["strongForeground"],
                    font=fonts["bodyStrong"])
    style.configure("EmptyTitle.TLabel", background=bg, foreground=t["strongForeground"],
                    font=fonts["title"])
    for name, back in (("Hint.TLabel", bg), ("Side.Hint.TLabel", side),
                       ("Dialog.Hint.TLabel", dialog)):
        style.configure(name, background=back, foreground=t["muted"], font=fonts["small"])

    # Buttons (08 §7): primary (accent), secondary (gray) and ghost (the parent's fill until
    # hovered); 28 high, padding 12×4; a solid inner focus ring in the text color.
    pad = (px(12), px(4))
    disabled_bg, disabled_fg = t["button.disabledBackground"], t["button.disabledForeground"]
    for name, back, hover, pressed, text in (
            ("TButton", t["button.background"], t["button.hoverBackground"],
             t["button.pressedBackground"], t["button.foreground"]),
            ("Secondary.TButton", t["button.secondaryBackground"],
             t["button.secondaryHoverBackground"], t["button.secondaryPressedBackground"],
             t["button.secondaryForeground"]),
            ("Ghost.TButton", bg, t["button.ghostHoverBackground"],
             t["button.secondaryHoverBackground"], fg),
            ("Chrome.Ghost.TButton", side, t["button.ghostHoverBackground"],
             t["button.secondaryHoverBackground"], fg)):
        style.configure(name, background=back, foreground=text, bordercolor=back,
                        lightcolor=back, darkcolor=back, relief="flat", padding=pad,
                        focuscolor=text, focusthickness=1, focussolid=1, anchor="center")
        quiet = bg if name == "Ghost.TButton" else side if name.startswith("Chrome") \
            else disabled_bg
        style.map(name,
                  background=[("disabled", quiet), ("pressed", pressed), ("active", hover)],
                  bordercolor=[("disabled", quiet), ("pressed", pressed), ("active", hover)],
                  lightcolor=[("disabled", quiet), ("pressed", pressed), ("active", hover)],
                  darkcolor=[("disabled", quiet), ("pressed", pressed), ("active", hover)],
                  foreground=[("disabled", disabled_fg)])
    style.configure("Large.TButton", padding=(px(12), px(6)))      # Preview: 32 high
    style.configure("Chrome.Ghost.TButton", padding=(px(8), px(2)))

    # The trees: rows 24 high, muted chevrons; the project's on chrome, the outline's on
    # the surface.
    rowheight = max(px(24), linespace + px(6))
    for name, back in (("Treeview", side), ("Surface.Treeview", bg)):
        style.configure(name, background=back, fieldbackground=back, foreground=fg,
                        bordercolor=back, lightcolor=back, darkcolor=back,
                        rowheight=rowheight, font=body)
        style.map(name,
                  background=[("selected", "focus", t["list.activeSelection"]),
                              ("selected", "!focus", t["list.inactiveSelection"])],
                  foreground=[("selected", "focus", t["list.activeSelectionForeground"]),
                              ("selected", "!focus", fg)],
                  bordercolor=[("focus", t["focusBorder"])],
                  lightcolor=[("focus", t["focusBorder"])])
    style.configure("Treeitem.indicator", foreground=t["muted"])
    style.configure("Treeview.Item", foreground=fg)
    # (08 §6's chevron images wait for P3: this Tk's image elements never see an item's
    # open state, so clam's own muted triangles stay.)

    # Notebook tabs: inactive tabs on the chrome strip in muted text, the active one on the
    # surface in white.
    bar = t["tab.barBackground"]
    tab_pad = (px(12), max(px(7), (px(32) - linespace) // 2))
    style.configure("TNotebook", background=bar, bordercolor=bg, lightcolor=bg, darkcolor=bg,
                    tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab", background=t["tab.inactiveBackground"],
                    foreground=t["tab.inactiveForeground"], bordercolor=bar,
                    lightcolor=t["tab.inactiveBackground"], padding=tab_pad)
    style.map("TNotebook.Tab",
              background=[("selected", t["tab.activeBackground"])],
              foreground=[("selected", t["tab.activeForeground"]),
                          ("active", t["tab.hoverForeground"])],
              lightcolor=[("selected", t["tab.activeBackground"])],
              bordercolor=[("selected", t["tab.activeBackground"])],
              padding=[("selected", tab_pad)],
              expand=[("selected", (0, 0, 0, 0))])

    # The window's notebook hides its own tabs under views.TabStrip (08 §7, P2); select and
    # index still work.
    style.layout("Tabless.TNotebook.Tab", [])
    style.configure("Tabless.TNotebook", background=bg, bordercolor=bg, lightcolor=bg,
                    darkcolor=bg, tabmargins=(0, 0, 0, 0), borderwidth=0)

    # Scrollbars: 10 px, a thumb in a trough of the surface below, no arrows (VS Code's).
    thick = px(10)
    for orient, sticky in (("Vertical", "ns"), ("Horizontal", "we")):
        layout = [(f"{orient}.Scrollbar.trough", {"sticky": sticky, "children": [
            (f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})]
        for prefix, trough in (("", bg), ("Side.", side)):
            name = f"{prefix}{orient}.TScrollbar"
            style.layout(name, layout)
            style.configure(name, troughcolor=trough, background=t["scrollbar.thumb"],
                            bordercolor=trough, lightcolor=t["scrollbar.thumb"],
                            darkcolor=t["scrollbar.thumb"], arrowsize=thick, width=thick,
                            gripcount=0, relief="flat")
            style.map(name, background=[("pressed", t["scrollbar.thumbPressed"]),
                                        ("active", t["scrollbar.thumbHover"])],
                      lightcolor=[("pressed", t["scrollbar.thumbPressed"]),
                                  ("active", t["scrollbar.thumbHover"])],
                      darkcolor=[("pressed", t["scrollbar.thumbPressed"]),
                                 ("active", t["scrollbar.thumbHover"])])

    # Inputs: the input fill inside a 1 px border that turns the focus color when focused
    # (the dialogs' entry, the story map's file filter).
    field, edge = t["input.background"], t["input.border"]
    style.configure("TEntry", fieldbackground=field, foreground=t["input.foreground"],
                    bordercolor=edge, lightcolor=field, darkcolor=field,
                    insertcolor=t["editor.cursor"], padding=(px(8), px(4)))
    style.map("TEntry", bordercolor=[("focus", t["focusBorder"])])
    style.configure("TCombobox", fieldbackground=field, background=field,
                    foreground=t["input.foreground"], bordercolor=edge, lightcolor=field,
                    darkcolor=field, arrowcolor=t["muted"], arrowsize=px(12),
                    padding=(px(8), px(3)))
    style.map("TCombobox",
              fieldbackground=[("readonly", field)], background=[("active", field)],
              foreground=[("readonly", t["input.foreground"])],
              bordercolor=[("focus", t["focusBorder"])],
              arrowcolor=[("active", fg)],
              selectbackground=[("readonly", "focus", t["list.activeSelection"]),
                                ("readonly", field)],
              selectforeground=[("readonly", "focus", t["list.activeSelectionForeground"]),
                                ("readonly", t["input.foreground"])])
    for name, back in (("TCheckbutton", bg), ("Dialog.TCheckbutton", dialog)):
        style.configure(name, background=back, foreground=fg, indicatorbackground=field,
                        indicatorforeground=t["checkbox.foreground"],
                        upperbordercolor=edge, lowerbordercolor=edge,
                        indicatorsize=px(13), indicatormargin=(0, 0, px(8), 0), focuscolor=fg)
        style.map(name, background=[("active", back)],
                  indicatorbackground=[("pressed", field), ("selected", field)],
                  upperbordercolor=[("focus", t["focusBorder"])],
                  lowerbordercolor=[("focus", t["focusBorder"])])

    # Classic widgets' defaults: menus (drop-downs on the overlay) and the combo box's
    # drop-down list.
    widget_bg = t["widget.background"]
    for pattern, value in (
            ("*Menu.background", widget_bg), ("*Menu.foreground", fg),
            ("*Menu.activeBackground", t["list.activeSelection"]),
            ("*Menu.activeForeground", t["list.activeSelectionForeground"]),
            ("*Menu.selectColor", fg), ("*Menu.disabledForeground",
                                        t["button.disabledForeground"]),
            ("*Menu.relief", "flat"), ("*Menu.activeBorderWidth", 0),
            ("*Menu.font", body),
            ("*TCombobox*Listbox.background", widget_bg),
            ("*TCombobox*Listbox.foreground", fg),
            ("*TCombobox*Listbox.font", body),
            ("*TCombobox*Listbox.selectBackground", t["list.activeSelection"]),
            ("*TCombobox*Listbox.selectForeground", t["list.activeSelectionForeground"])):
        root.option_add(pattern, value)  # type: ignore[attr-defined]
    return list(fonts.values())


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


__all__ = ["CONTRAST_PAIRS", "FONT_STACKS", "GRAPHIC_MIN", "MENU_BAR_PX", "ROLES",
           "STATUS_BAR_PX", "TEXT_MIN", "THEME", "TYPE_SCALE", "contrast",
           "dark_title_bar", "declare_dpi_awareness", "font_families", "luminance",
           "make_fonts", "scale_of", "style_ttk"]

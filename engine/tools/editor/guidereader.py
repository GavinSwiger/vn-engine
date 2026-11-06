"""The beginner's guide, ``docs/first-game.md``, read inside Studio: the Guide pane's **Read
more** opens it at the step's own heading.

Why this module exists: the system's viewer for a ``.md`` file can't open at a heading (and
on Windows is often Notepad), so a first-time author following the Guide would have to hunt
through a long page. This window shows the guide as formatted text (headings, lists, bold,
code) and scrolls to the heading asked for; **Open in your viewer** still hands the file to
the system. One window per Studio window, reused; Esc closes it.

``blocks`` (pure) reads the Markdown subset the guide uses into rows of styled runs, which
``GuideReader`` puts in a read-only ``tk.Text``. Imports only the standard library and the
editor's own modules (ADR-0008).
"""

from __future__ import annotations

import re
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from typing import Any, Final

from engine.tools.editor.theme import THEME

READER_TITLE: Final = "Beginner's guide"
OPEN_OUTSIDE: Final = "Open in your viewer"
CLOSE_TEXT: Final = "Close"
MISSING: Final = "The beginner's guide isn't in this copy of vn-engine."
READ_MAX: Final = 1024 * 1024
WIDTH, HEIGHT = 720, 640                # px at 100 %

# Run styles: plain text, bold, italic, inline code; row kinds: h1 h2 h3, a paragraph, a list
# item (its indent level), a code block line, a blank line.
PLAIN, BOLD, ITALIC, CODE = "plain", "bold", "italic", "code"
_INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`|\*([^*\s][^*]*?)\*|\[([^\]]+)\]\([^)]*\)")
_HEAD = re.compile(r"^(#{1,3})[ \t]+(.+?)[ \t]*$")
_ITEM = re.compile(r"^([ \t]*)(?:[-*]|(\d+)\.)[ \t]+(.*)$")


def runs(text: str) -> list[tuple[str, str]]:
    """``text``'s inline Markdown as (text, style) runs; a link keeps only its words."""
    found: list[tuple[str, str]] = []
    at = 0
    for match in _INLINE.finditer(text):
        if match.start() > at:
            found.append((text[at:match.start()], PLAIN))
        bold, code, italic, link = match.groups()
        if bold is not None:
            found.append((bold, BOLD))
        elif code is not None:
            found.append((code, CODE))
        elif italic is not None:
            found.append((italic, ITALIC))
        else:
            found.append((link, PLAIN))
        at = match.end()
    if at < len(text):
        found.append((text[at:], PLAIN))
    return found


def blocks(markdown: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """The guide as rows of (kind, runs): ``h1``-``h3`` (runs: the heading), ``p``, ``li0``
    or ``li1`` (a list item and its level, its marker in the first run), ``pre`` (one code
    line) and ``gap``. A paragraph's or list item's wrapped lines are joined."""
    rows: list[tuple[str, list[tuple[str, str]]]] = []
    fenced = False
    open_kind: str | None = None        # the paragraph or item later lines continue
    text = ""

    def flush() -> None:
        nonlocal open_kind, text
        if open_kind is not None:
            kind, marker = open_kind.split("|", 1)
            rows.append((kind, ([(marker, PLAIN)] if marker else []) + runs(text)))
        open_kind, text = None, ""

    for line in markdown.split("\n"):
        if line.lstrip().startswith("```"):
            flush()
            fenced = not fenced
            continue
        if fenced:
            rows.append(("pre", [(line, CODE)]))
            continue
        if not line.strip():
            flush()
            if rows and rows[-1][0] != "gap":
                rows.append(("gap", []))
            continue
        head = _HEAD.match(line)
        if head is not None:
            flush()
            rows.append((f"h{len(head.group(1))}", [(head.group(2), PLAIN)]))
            continue
        item = _ITEM.match(line)
        if item is not None:
            flush()
            level = 1 if len(item.group(1).expandtabs(4)) >= 2 else 0
            marker = f"{item.group(2)}. " if item.group(2) else "•  "
            open_kind, text = f"li{level}|{marker}", item.group(3).strip()
            continue
        if open_kind is None:
            open_kind, text = "p|", line.strip()
        else:
            text += " " + line.strip()
    flush()
    return rows


class GuideReader:
    """The reader window over ``root`` (made on first ``open``). ``path``: the guide's file;
    ``fonts``: Studio's; ``open_outside``: hands the file to the system's viewer."""

    def __init__(self, root: tk.Misc, path: Path, *, fonts: dict, scale: float,
                 open_outside: Callable[[], object]) -> None:
        self.root, self.path, self.fonts, self.scale = root, path, fonts, scale
        self.open_outside = open_outside
        self.window: tk.Toplevel | None = None
        self.text: tk.Text | None = None
        self.headings: dict[str, str] = {}      # heading text → its mark in the text

    def px(self, value: float) -> int:
        return round(value * self.scale)

    def open(self, heading: str | None = None) -> bool:
        """Show the guide at ``heading`` (None: the top). False when the file can't be read."""
        if self.window is None or not self.window.winfo_exists():
            try:
                with open(self.path, "rb") as handle:
                    markdown = handle.read(READ_MAX).decode("utf-8")
            except (OSError, UnicodeDecodeError):
                return False
            self._build(markdown)
        window, text = self.window, self.text
        assert window is not None and text is not None
        window.deiconify()
        window.lift()
        mark = self.headings.get(heading or "")
        text.yview_moveto(0.0)
        if mark is not None:
            text.update_idletasks()
            text.yview(mark)                    # the heading at the top of the view
        text.focus_set()
        return True

    def close(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        self.window = self.text = None

    def _build(self, markdown: str) -> None:
        px, fonts = self.px, self.fonts
        bg, fg = THEME["editor.background"], THEME["editor.foreground"]
        window = self.window = tk.Toplevel(self.root, background=bg)
        window.title(READER_TITLE)
        window.geometry(f"{px(WIDTH)}x{px(HEIGHT)}")
        window.minsize(px(360), px(240))
        try:
            from engine.tools.editor import appicon
            appicon.apply(window)
        except Exception:  # noqa: BLE001  (no icon is fine)
            pass
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        text = self.text = tk.Text(window, wrap="word", background=bg, foreground=fg,
                                   borderwidth=0, highlightthickness=0, padx=px(24),
                                   pady=px(16), cursor="arrow", insertwidth=0,
                                   font=fonts.get("body"), spacing1=px(2), spacing3=px(2),
                                   selectbackground=THEME["editor.selection"])
        text.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(window, orient="vertical", command=text.yview)
        bar.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=bar.set)
        foot = ttk.Frame(window, padding=(px(12), px(8)))
        foot.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Button(foot, text=CLOSE_TEXT, command=self.close).pack(side="right")
        ttk.Button(foot, text=OPEN_OUTSIDE, style="Secondary.TButton",
                   command=self.open_outside).pack(side="right", padx=(0, px(8)))
        strong = fonts.get("bodyStrong") or fonts.get("body")
        code = fonts.get("codeSmall") or fonts.get("code")
        card = THEME["card.background"]
        text.tag_configure("h1", font=fonts.get("title"), spacing1=px(4), spacing3=px(8),
                           foreground=THEME["strongForeground"])
        text.tag_configure("h2", font=fonts.get("title"), spacing1=px(18), spacing3=px(6),
                           foreground=THEME["strongForeground"])
        text.tag_configure("h3", font=strong, spacing1=px(14), spacing3=px(4),
                           foreground=THEME["strongForeground"])
        text.tag_configure("li0", lmargin1=px(8), lmargin2=px(26))
        text.tag_configure("li1", lmargin1=px(30), lmargin2=px(48))
        text.tag_configure("pre", font=code, background=card, lmargin1=px(12),
                           lmargin2=px(12), spacing1=0, spacing3=0, wrap="none")
        text.tag_configure("gap", font=fonts.get("small"), spacing1=0, spacing3=0)
        text.tag_configure(BOLD, font=strong)
        text.tag_configure(CODE, font=code, background=card)
        text.tag_configure(ITALIC, foreground=THEME["strongForeground"])
        self.headings = {}
        for number, (kind, parts) in enumerate(blocks(markdown)):
            if kind.startswith("h"):
                heading = "".join(part for part, _style in parts)
                mark = f"heading{number}"
                text.mark_set(mark, "end-1c")
                text.mark_gravity(mark, "left")
                self.headings.setdefault(heading, mark)
            for part, style in parts:
                tags = (kind,) if style == PLAIN else (kind, style)
                text.insert("end", part, tags)
            text.insert("end", "\n", (kind,))
        text.configure(state="disabled")
        for key in ("<Escape>",):
            window.bind(key, lambda _e: self.close())
        window.protocol("WM_DELETE_WINDOW", self.close)
        # Keys scroll the read-only text (it takes focus, so the wheel and arrows work).
        text.bind("<Next>", lambda _e: text.yview_scroll(1, "pages"))
        text.bind("<Prior>", lambda _e: text.yview_scroll(-1, "pages"))
        text.bind("<Home>", lambda _e: text.yview_moveto(0.0))
        text.bind("<End>", lambda _e: text.yview_moveto(1.0))


def reader_for(win: Any) -> GuideReader:
    """``win``'s reader (made on first use)."""
    reader = win.__dict__.get("_guide_reader")
    if reader is None:
        from engine.tools.editor import guide, guides
        path = guides.guide_path(guide.GUIDE_DOC)

        def outside() -> None:
            problem = guides.open_guide(guide.DOC_TITLE, guide.GUIDE_DOC)
            if problem is not None:
                from engine.tools.editor.dialogs import show_error
                show_error(win.root, problem)

        reader = win.__dict__["_guide_reader"] = GuideReader(
            win.root, path, fonts=win.fonts, scale=win.scale, open_outside=outside)
    return reader


__all__ = ["BOLD", "CLOSE_TEXT", "CODE", "GuideReader", "ITALIC", "MISSING", "OPEN_OUTSIDE",
           "PLAIN", "READER_TITLE", "blocks", "reader_for", "runs"]

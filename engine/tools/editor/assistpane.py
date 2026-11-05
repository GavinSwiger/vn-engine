"""The Assistant pane's widgets (F48 ``01-design.md`` §6.1, §6.3, §6.6, PR-F48-14, -21, -24,
-27; ``04-technical.md`` §3.2; ``05-security.md`` SEC-F48-20; AC-F48-46, -53).

Why this module exists: the pane is where the author talks with the AI model and sees the
changes it proposes, so what it shows must be exactly what is true. Model text is plain text
(no HTML, no images, no links that open anything but a listed script); every control,
bidi and zero-width character shows as a visible escape; a card's file names, +N −M and
diff lines come from the tool layer's plan (``edits.Proposal``), never from model text::

    AI ASSISTANT                   [New chat] ✕
    Claude · claude-sonnet-5-5               ⚙
    YOU
    Add a choice after the poem.
    ASSISTANT
    Sent: reference, summary, script/ch2.vns lines 1–48, 0 problems
    I'll turn line 15 into a choice.
    · Read the story map
    ┌ Add a choice after the poem ───────────┐
    │ script/ch2.vns  +6 −1                  │
    │  14 sayori "You wrote a poem?"         │
    │ -15 jump club_poem                     │
    │ +15 menu:                              │
    │ No new problems.                       │
    │ [Apply] [Show] [Discard]               │
    └────────────────────────────────────────┘
    ↑ 14,210 (11,800 cached) ↓ 912
    [Ask about your game…              ] [Send]
    This chat: 14,210 tokens

``AssistPane`` only draws and calls back (``assistwiring.AssistWiring`` owns what Send,
Stop and the cards do). ``Card`` is one proposal's card; its Apply, Undo and Ask again
buttons call the window's hooks (``AssistWiring.assist_apply`` and so on).

Imports ``tkinter``, its own package and ``tools.assistant`` (a Tk module: the import-rule
exception).
"""

from __future__ import annotations

import re
import tkinter as tk
from collections.abc import Callable, Collection
from tkinter import ttk
from typing import Any

from engine.tools.assistant import chat as chat_texts
from engine.tools.assistant.edits import (
    CODE_NOTICE,
    NEW_FILE_MARK,
    Proposal,
    ProposalFile,
    check_lines,
)
from engine.tools.assistant.refs import one_line, visible
from engine.tools.editor.connectdialog import MENU as CONNECT_MENU
from engine.tools.editor.theme import THEME
from engine.tools.editor.views import panel_header

# --- Texts (01 §6.1, §6.3, §6.6, final) ---------------------------------------------------------

HEADING = "AI Assistant"                # the header strip shows it upper-case
NEW_CHAT = "New chat"
CLOSE = "✕"
TIP_CLOSE = "Hide the AI Assistant"
SETTINGS = "⚙"
TIP_SETTINGS = "Studio settings ▸ AI"
YOU = "YOU"
ASSISTANT = "ASSISTANT"
PLACEHOLDER = "Ask about your game…"
SEND = "Send"
STOP = "Stop"
EMPTY_TEXT = "Get help writing your game here with an API key (paid by use)."
SET_UP = "Set up AI…"
EMPTY_MCP = ("Have a Claude Pro or Max plan? Use it with Claude Code or Claude Desktop "
             "instead: no API key needed.")
OPEN_SETTINGS = "Open settings"
APPLY = "Apply"
SHOW = "Show"
DISCARD = "Discard"
UNDO = "Undo"
ASK_AGAIN = "Ask again"
SHOW_ALL = "Show all {n} lines"
DISCARDED = "Discarded: {title}"
NEW_FILE_TITLE = "{ref} (new file)"
# §6.3's Apply, Stale, Ask again and Undo texts (W5).
APPLIED = "Applied. Ctrl+Z in the editor undoes it."
APPLIED_MANY = "Applied to {n} files. Undo in each file, or use Undo here."
STALE = "This file changed after the assistant wrote this change, so nothing was changed."
ASK_AGAIN_TEXT = "The file changed. Read it again and propose the change again."
UNDONE = "Undone."
UNDO_REFUSED = "A file changed since, so Undo here can't run. Use Ctrl+Z in the editor."

# --- Look (px at 100 %) ------------------------------------------------------------------------

INSET = 12                              # 08 §7: panel inset
CARD_PAD = 10
CARD_LINES = 12                         # §6.1: the diff folds after 12 lines
CARD_LINES_OPEN = 40                    # an unfolded diff's height; it scrolls past that
TITLE_MAX = 120                         # SEC-F48-20: the card title is cut at 120
INPUT_LINES = 3
INPUT_MAX_LINES = 8
PARTIAL_MAX = 1024                      # a longer unbroken line is committed as it streams
LINK_RE = re.compile(r"(?<![\w./\\:-])((?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.vns):([0-9]{1,7})"
                     r"(?![0-9])")
FENCE = "```"

# Tags in the transcript.
T_SPEAKER, T_BODY, T_CODE, T_META, T_ERROR, T_LINK = (
    "speaker", "body", "code", "meta", "error", "link")


def shown_text(text: str) -> str:
    """Model text as the pane shows it: every Cc, Cf, Cs, Zl and Zp character as a visible
    escape (``refs.visible``), except line breaks and tabs."""
    return "\n".join("\t".join(visible(part) for part in line.split("\t"))
                     for line in text.split("\n"))


def find_links(line: str, listed: Collection[str]) -> list[tuple[int, int, str, int]]:
    """``(start, end, ref, line)`` for each ``file:line`` in ``line`` naming a listed script
    (``script/ch2.vns`` or ``ch2.vns`` for ``script/ch2.vns``). Anything else stays text."""
    found = []
    for match in LINK_RE.finditer(line):
        name, number = match.group(1), int(match.group(2))
        ref = name if name in listed else f"script/{name}" if f"script/{name}" in listed \
            else None
        if ref is not None and number >= 1:
            found.append((match.start(), match.end(), ref, number))
    return found


def card_title(proposal: Proposal) -> str:
    """The model's summary as one escaped line, cut at 120 characters (SEC-F48-20)."""
    return one_line(proposal.summary, TITLE_MAX)


def file_heading(file: ProposalFile) -> str:
    """``script/ch2.vns  +6 −1`` (`` (new file)`` for a new one), from the plan."""
    mark = NEW_FILE_MARK if file.new else ""
    return f"{one_line(file.ref)}{mark}  +{file.added} −{file.removed}"


def first_line(file: ProposalFile) -> int:
    """The first line the change touches (Show's place)."""
    return min((edit.first for edit in file.plan.edits), default=1)


def new_text(file: ProposalFile) -> str:
    """A new file's text, from its plan (one ``LineEdit`` over the empty text)."""
    return "\n".join(line for edit in file.plan.edits for line in edit.lines)


def _styles(root: tk.Misc, fonts: dict) -> None:
    style = ttk.Style(root)
    raised, side = THEME["card.background"], THEME["sideBar.background"]
    style.configure("Card.TFrame", background=raised)
    style.configure("Card.TLabel", background=raised, foreground=THEME["foreground"],
                    font=fonts["body"])
    style.configure("CardTitle.TLabel", background=raised,
                    foreground=THEME["strongForeground"], font=fonts["bodyStrong"])
    style.configure("CardHint.TLabel", background=raised, foreground=THEME["muted"],
                    font=fonts["small"])
    style.configure("CardNotice.TLabel", background=THEME["editor.background"],
                    foreground=THEME["marker.warning"], font=fonts["small"])
    style.configure("Card.Ghost.TButton", background=raised, bordercolor=raised,
                    lightcolor=raised, darkcolor=raised)
    style.map("Card.Ghost.TButton",
              background=[("disabled", raised),
                          ("pressed", THEME["button.secondaryPressedBackground"]),
                          ("active", THEME["button.ghostHoverBackground"])],
              bordercolor=[("disabled", raised), ("active", THEME["button.ghostHoverBackground"])],
              lightcolor=[("disabled", raised), ("active", THEME["button.ghostHoverBackground"])],
              darkcolor=[("disabled", raised), ("active", THEME["button.ghostHoverBackground"])])
    style.configure("Assist.Hint.TLabel", background=side, foreground=THEME["muted"],
                    font=fonts["small"])


class Card:
    """One proposal's card in the transcript (§6.1, §6.3). ``frame`` is embedded in the
    transcript. ``buttons``: Apply, Show, Discard, Undo, Ask again (Undo shows once
    applied, Ask again once stale); ``status`` is §6.3's line ("Applied…", the stale text,
    "Undone.", Undo's refusal); ``state`` is "open", "applied", "stale" or "discarded";
    ``tokens`` are the F46 map-undo tokens ``(ref, OpenFile.changes)`` right after Apply
    (None once Undo can't run) and ``created`` the files Apply created."""

    def __init__(self, pane: "AssistPane", parent: tk.Misc, proposal: Proposal) -> None:
        self.pane = pane
        self.proposal = proposal
        self.state = "open"
        self.tokens: tuple[tuple[str, int], ...] | None = None
        self.created: tuple[str, ...] = ()
        px = pane.px
        fonts = pane.fonts
        self.title = card_title(proposal)
        frame = self.frame = tk.Frame(parent, background=THEME["card.background"],
                                      highlightthickness=1,
                                      highlightbackground=THEME["border"],
                                      highlightcolor=THEME["focusBorder"],
                                      padx=px(CARD_PAD), pady=px(8))
        self.body = ttk.Frame(frame, style="Card.TFrame")
        self.body.pack(fill="x")
        self.title_label = ttk.Label(self.body, text=self.title, style="CardTitle.TLabel",
                                     justify="left")
        self.title_label.pack(anchor="w", fill="x")
        self.files: list[CardFile] = [CardFile(self, f) for f in proposal.files]
        lines = check_lines(proposal)
        self.check_texts = [line for line in lines if line != CODE_NOTICE]
        self.check_labels = []
        for index, line in enumerate(self.check_texts):
            label = ttk.Label(self.body, text=line, justify="left",
                              style="Card.TLabel" if index == 0 else "CardHint.TLabel")
            label.pack(anchor="w", fill="x", pady=(px(6) if index == 0 else 0, 0))
            self.check_labels.append(label)
        self.notice: ttk.Label | None = None
        if proposal.code:                           # §6.3's code notice, above the buttons
            self.notice = ttk.Label(self.body, text=CODE_NOTICE, style="CardNotice.TLabel",
                                    justify="left", padding=(px(6), px(4)))
            self.notice.pack(anchor="w", fill="x", pady=(px(6), 0))
        self.status = ttk.Label(self.body, text="", style="Card.TLabel", justify="left")
        row = self.button_row = ttk.Frame(self.body, style="Card.TFrame")
        row.pack(anchor="w", pady=(px(8), 0))
        self.buttons: dict[str, ttk.Button] = {}
        for label, style, action, shown in (
                (APPLY, "TButton", "apply", True),
                (SHOW, "Secondary.TButton", "show", True),
                (DISCARD, "Card.Ghost.TButton", "discard", True),
                (UNDO, "Secondary.TButton", "undo", False),
                (ASK_AGAIN, "Secondary.TButton", "ask_again", False)):
            button = ttk.Button(row, text=label, style=style,
                                command=lambda a=action: pane.on_card(a, self))
            if shown:
                button.pack(side="left", padx=(0, px(8)))
            for key in ("<Return>", "<KP_Enter>"):
                button.bind(key, lambda _e, b=button: (b.invoke(), "break")[1])
            self.buttons[action] = button
        self.discarded_label = ttk.Label(frame, text=DISCARDED.format(title=self.title),
                                         style="CardHint.TLabel", justify="left")
        # Ctrl+Enter on a focused card applies (§6.1 Keys).
        for widget in self.widgets():
            widget.bind("<Control-Return>", lambda _e: (pane.on_card("apply", self), "break")[1])
            widget.bind("<Control-KP_Enter>",
                        lambda _e: (pane.on_card("apply", self), "break")[1])

    def widgets(self) -> list[tk.Misc]:
        found: list[tk.Misc] = [self.frame]
        stack: list[tk.Misc] = [self.frame]
        while stack:
            for child in stack.pop().winfo_children():
                found.append(child)
                stack.append(child)
        return found

    def fit(self, width: int) -> None:
        """Lay the card out ``width`` px wide (the transcript's width)."""
        inner = max(self.pane.px(120), width - 2 * self.pane.px(CARD_PAD) - 2)
        for label in (self.title_label, *self.check_labels, self.status,
                      self.discarded_label, *([self.notice] if self.notice else [])):
            label.configure(wraplength=inner)
        for file in self.files:
            file.fit(inner)

    def show_status(self, text: str) -> None:
        """The line under the check texts ("Applied…", the stale text, "Undone.")."""
        self.status.configure(text=text)
        if text and not self.status.winfo_manager():
            self.status.pack(anchor="w", fill="x", pady=(self.pane.px(6), 0),
                             before=self.button_row)
        elif not text and self.status.winfo_manager():
            self.status.pack_forget()

    def show_buttons(self, *actions: str) -> None:
        """Show exactly ``actions`` (in the card's order)."""
        for button in self.buttons.values():
            button.pack_forget()
        for action in ("apply", "show", "discard", "undo", "ask_again"):
            if action in actions:
                self.buttons[action].pack(side="left", padx=(0, self.pane.px(8)))

    def discard(self) -> None:
        """**Discard**: the card collapses to "Discarded: {title}" (§6.3)."""
        self.state = "discarded"
        self.body.pack_forget()
        self.discarded_label.pack(anchor="w", fill="x")

    def texts(self) -> list[str]:
        """What the card shows, top to bottom (tests read it)."""
        if self.state == "discarded":
            return [str(self.discarded_label.cget("text"))]
        out = [self.title]
        for file in self.files:
            out.append(file.heading)
            out += file.shown_rows()
            if file.more is not None and file.more.winfo_manager():
                out.append(str(file.more.cget("text")))
        out += self.check_texts
        if self.notice is not None:
            out.append(CODE_NOTICE)
        if self.status.winfo_manager():
            out.append(str(self.status.cget("text")))
        out += [str(b.cget("text")) for b in self.buttons.values() if b.winfo_manager()]
        return out


class CardFile:
    """One file of a card: its heading and its diff (12 lines, then "Show all {n} lines")."""

    def __init__(self, card: Card, file: ProposalFile) -> None:
        self.card = card
        self.file = file
        pane = card.pane
        px = pane.px
        self.rows: tuple[str, ...] = tuple(file.diff)
        self.open = len(self.rows) <= CARD_LINES
        self.heading = file_heading(file)
        self.label = ttk.Label(card.body, text=self.heading, style="CardHint.TLabel")
        self.label.pack(anchor="w", pady=(px(6), px(2)))
        font = pane.fonts["codeSmall"]
        self.text = tk.Text(card.body, height=1, width=40, wrap="none", font=font,
                            background=THEME["editor.background"],
                            foreground=THEME["muted"], borderwidth=0, highlightthickness=0,
                            relief="flat", padx=px(6), pady=px(4), cursor="arrow",
                            selectbackground=THEME["editor.selection"],
                            inactiveselectbackground=THEME["editor.selection"],
                            takefocus=0)
        self.text.tag_configure("add", foreground=THEME["success"])
        self.text.tag_configure("remove", foreground=THEME["marker.error"])
        self.text.tag_configure("context", foreground=THEME["muted"])
        self.text.pack(anchor="w", fill="x")
        self.more: ttk.Button | None = None
        if not self.open:
            self.more = ttk.Button(card.body, text=SHOW_ALL.format(n=len(self.rows)),
                                   style="Card.Ghost.TButton", command=self.unfold)
            self.more.pack(anchor="w")
        self._fill()

    def shown_rows(self) -> list[str]:
        text = self.text.get("1.0", "end-1c")
        return text.split("\n") if text else []

    def _fill(self) -> None:
        rows = self.rows if self.open else self.rows[:CARD_LINES]
        text = self.text
        text.configure(state="normal")
        text.delete("1.0", "end")
        for index, row in enumerate(rows):
            tag = "add" if row.startswith("+") else "remove" if row.startswith("-") \
                else "context"
            text.insert("end", ("\n" if index else "") + row, tag)
        text.configure(state="disabled",
                       height=max(1, min(len(rows), CARD_LINES_OPEN if self.open
                                         else CARD_LINES)))

    def unfold(self) -> None:
        """Show all lines (the box scrolls past ``CARD_LINES_OPEN``)."""
        self.open = True
        if self.more is not None:
            self.more.pack_forget()
        self._fill()

    def fit(self, inner: int) -> None:
        zero = max(1, self.card.pane.fonts["codeSmall"].measure("0"))
        self.text.configure(width=max(10, (inner - 2 * self.card.pane.px(6)) // zero))


class AssistPane:
    """The pane's widgets on ``parent``: ``frame``, the header (``new_chat_button``,
    ``close_button``), ``model_label`` with ``settings_button``, the ``empty`` state, the
    ``transcript``, ``status_label``, the ``input`` box with ``send_button``, and the
    ``footer``. Callbacks: ``on_send()``, ``on_stop()``, ``on_new_chat()``, ``on_close()``,
    ``on_settings()``, ``on_connect()``, ``on_link(ref, line)``, ``on_card(action, card)``;
    ``listed()`` gives the script refs a ``file:line`` may link to."""

    def __init__(self, parent: tk.Misc, *, fonts: dict, scale: float,
                 on_send: Callable[[], object], on_stop: Callable[[], object],
                 on_new_chat: Callable[[], object], on_close: Callable[[], object],
                 on_settings: Callable[[], object], on_connect: Callable[[], object],
                 on_link: Callable[[str, int], object],
                 on_card: Callable[[str, Card], object],
                 listed: Callable[[], Collection[str]]) -> None:
        self.fonts, self.scale = fonts, scale
        self.on_send, self.on_stop, self.on_link, self.on_card = on_send, on_stop, on_link, \
            on_card
        self.on_settings = on_settings
        self.listed = listed
        self.running = False
        self.cards: list[Card] = []
        self._links: dict[str, tuple[str, int]] = {}
        self._link_count = 0
        self._placeholder = False
        # The streaming answer: the raw tail after the last line break, where it starts in
        # the transcript, and whether a code fence is open.
        self._partial = ""
        self._fence = False
        self._answering = False
        self._partial_shown = False
        px = self.px
        _styles(parent, fonts)
        side = THEME["sideBar.background"]
        self.frame = ttk.Frame(parent, style="Side.TFrame")
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(2, weight=1)
        head = panel_header(self.frame, HEADING, scale)
        head.grid(row=0, column=0, sticky="ew")
        from engine.tools.editor.playbar import Tooltip
        self.close_button = ttk.Button(head, text=CLOSE, width=3, command=on_close,
                                       style="Chrome.Ghost.TButton")
        self.close_button.pack(side="right", padx=(0, px(4)))
        Tooltip(self.close_button, TIP_CLOSE, fonts.get("small"))
        self.new_chat_button = ttk.Button(head, text=NEW_CHAT, command=on_new_chat,
                                          style="Chrome.Ghost.TButton")
        self.new_chat_button.pack(side="right")
        line = ttk.Frame(self.frame, style="Side.TFrame", padding=(px(INSET), 0, px(4), 0))
        line.grid(row=1, column=0, sticky="ew")
        self.model_label = ttk.Label(line, text="", style="Assist.Hint.TLabel")
        self.model_label.pack(side="left")
        self.settings_button = ttk.Button(line, text=SETTINGS, width=3, command=on_settings,
                                          style="Chrome.Ghost.TButton")
        self.settings_button.pack(side="right")
        Tooltip(self.settings_button, TIP_SETTINGS, fonts.get("small"))
        # The empty state (§6.6).
        self.empty = ttk.Frame(self.frame, style="Side.TFrame", padding=(px(INSET), px(12)))
        self.empty_text = ttk.Label(self.empty, text=EMPTY_TEXT, style="Side.TLabel",
                                    justify="left", font=fonts.get("body"))
        self.empty_text.pack(anchor="w", fill="x")
        self.set_up_button = ttk.Button(self.empty, text=SET_UP, command=on_settings,
                                        style="Secondary.TButton")
        self.set_up_button.pack(anchor="w", pady=(px(8), px(16)))
        self.empty_mcp = ttk.Label(self.empty, text=EMPTY_MCP, style="Assist.Hint.TLabel",
                                   justify="left")
        self.empty_mcp.pack(anchor="w", fill="x")
        self.connect_button = ttk.Button(self.empty, text=CONNECT_MENU, command=on_connect,
                                         style="Chrome.Ghost.TButton")
        self.connect_button.pack(anchor="w", pady=(px(8), 0))
        # The transcript.
        self.chat = ttk.Frame(self.frame, style="Side.TFrame")
        self.chat.columnconfigure(0, weight=1)
        self.chat.rowconfigure(0, weight=1)
        self.transcript = tk.Text(self.chat, wrap="word", font=fonts["body"], background=side,
                                  foreground=THEME["foreground"], borderwidth=0,
                                  highlightthickness=0, relief="flat", padx=px(INSET),
                                  pady=px(6), cursor="arrow", takefocus=1,
                                  selectbackground=THEME["editor.selection"],
                                  inactiveselectbackground=THEME["editor.inactiveSelection"],
                                  insertwidth=0, state="disabled", width=30, height=10)
        self.transcript.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(self.chat, orient="vertical", command=self.transcript.yview,
                               style="Side.Vertical.TScrollbar")
        scroll.grid(row=0, column=1, sticky="ns")
        self.transcript.configure(yscrollcommand=scroll.set)
        t = self.transcript
        t.tag_configure(T_SPEAKER, font=fonts["caption"], foreground=THEME["muted"],
                        spacing1=px(10), spacing3=px(2))
        t.tag_configure(T_BODY, foreground=THEME["foreground"])
        t.tag_configure(T_CODE, font=fonts["codeSmall"], background=THEME["editor.background"],
                        foreground=THEME["editor.foreground"])
        t.tag_configure(T_META, font=fonts["small"], foreground=THEME["muted"])
        t.tag_configure(T_ERROR, foreground=THEME["marker.error"])
        t.tag_configure(T_LINK, foreground=THEME["link"], underline=True)
        t.tag_bind(T_LINK, "<Enter>", lambda _e: t.configure(cursor="hand2"))
        t.tag_bind(T_LINK, "<Leave>", lambda _e: t.configure(cursor="arrow"))
        t.tag_bind(T_LINK, "<Button-1>", self._link_click)
        t.bind("<Configure>", self._fit, add="+")
        # Status ("Working… (step n)", "Waiting…"), the input and the footer.
        self.status_label = ttk.Label(self.frame, text="", style="Assist.Hint.TLabel",
                                      padding=(px(INSET), px(2)))
        self.status_label.grid(row=3, column=0, sticky="ew")
        row = ttk.Frame(self.frame, style="Side.TFrame", padding=(px(INSET), px(4)))
        row.grid(row=4, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        self.input = tk.Text(row, height=INPUT_LINES, width=20, wrap="word",
                             font=fonts["body"], background=THEME["input.background"],
                             foreground=THEME["input.foreground"],
                             insertbackground=THEME["editor.cursor"], borderwidth=0,
                             highlightthickness=1, highlightbackground=THEME["input.border"],
                             highlightcolor=THEME["focusBorder"], relief="flat",
                             padx=px(8), pady=px(4), undo=True,
                             selectbackground=THEME["editor.selection"])
        self.input.tag_configure("placeholder", foreground=THEME["muted"])
        self.input.grid(row=0, column=0, sticky="ew")
        self.send_button = ttk.Button(row, text=SEND, command=self._send_or_stop,
                                      style="Secondary.TButton")
        self.send_button.grid(row=0, column=1, sticky="se", padx=(px(8), 0))
        for key in ("<Return>", "<KP_Enter>"):
            self.input.bind(key, self._enter)
            self.send_button.bind(key, lambda _e: (self.send_button.invoke(), "break")[1])
        for key in ("<Shift-Return>", "<Shift-KP_Enter>"):
            self.input.bind(key, lambda _e: None)          # a new line (Tk's own insert)
        self.input.bind("<FocusIn>", lambda _e: self._hide_placeholder(), add="+")
        self.input.bind("<FocusOut>", lambda _e: self._show_placeholder(), add="+")
        self.input.bind("<KeyRelease>", lambda _e: self._grow(), add="+")
        for widget in (self.input, self.transcript, self.send_button):
            widget.bind("<Escape>", lambda _e: (on_stop(), "break")[1])
        self.footer = ttk.Label(self.frame, text=chat_texts.chat_total_text(0),
                                style="Assist.Hint.TLabel", padding=(px(INSET), 0, 0, px(6)))
        self.footer.grid(row=5, column=0, sticky="ew")
        self._show_placeholder()
        self.show_empty(True)

    def px(self, value: float) -> int:
        return round(value * self.scale)

    # --- Modes ---------------------------------------------------------------------------------

    def set_empty_reason(self, reason: str | None) -> None:
        """The empty state's words: ``reason`` alone with Set up AI… (the Claude plan's
        Claude Code isn't installed), or None for the API key text and Connect an AI app."""
        self.empty_text.configure(text=reason if reason is not None else EMPTY_TEXT)
        for widget in (self.empty_mcp, self.connect_button):
            if reason is None and not widget.winfo_manager():
                widget.pack(anchor="w", fill="x" if widget is self.empty_mcp else "none",
                            pady=(self.px(8), 0) if widget is self.connect_button else 0)
            elif reason is not None:
                widget.pack_forget()

    def show_empty(self, empty: bool) -> None:
        """The empty state (no key) or the chat. A chat with content stays shown."""
        if empty and self.has_content():
            empty = False
        if empty:
            self.chat.grid_remove()
            self.empty.grid(row=2, column=0, sticky="nsew")
        else:
            self.empty.grid_remove()
            self.chat.grid(row=2, column=0, sticky="nsew")

    def is_empty_state(self) -> bool:
        return bool(self.empty.winfo_manager())

    def has_content(self) -> bool:
        return bool(self.transcript.get("1.0", "end-1c"))

    def set_model_line(self, text: str) -> None:
        self.model_label.configure(text=text)

    def set_running(self, running: bool) -> None:
        """**Send** becomes **Stop** while a request runs."""
        self.running = running
        self.send_button.configure(text=STOP if running else SEND)
        if not running:
            self.status_label.configure(text="")

    def set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def set_total(self, text: str) -> None:
        self.footer.configure(text=text)

    def _fit(self, event: tk.Event) -> None:
        for card in self.cards:
            card.fit(event.width - 2 * self.px(INSET))

    # --- The input -----------------------------------------------------------------------------

    def _send_or_stop(self) -> None:
        if self.running:
            self.on_stop()
        else:
            self.on_send()

    def _enter(self, event: tk.Event) -> str:
        if int(event.state) & 0x1:                         # Shift+Enter: a new line
            return ""
        self._send_or_stop()
        return "break"

    def input_text(self) -> str:
        if self._placeholder:
            return ""
        return self.input.get("1.0", "end-1c")

    def set_input(self, text: str) -> None:
        self._hide_placeholder()
        self.input.delete("1.0", "end")
        self.input.insert("1.0", text)
        self._grow()

    def clear_input(self) -> None:
        self._hide_placeholder()
        self.input.delete("1.0", "end")
        self.input.edit_reset()
        self._grow()
        if self.input.focus_get() is not self.input:
            self._show_placeholder()

    def _show_placeholder(self) -> None:
        if self._placeholder or self.input.get("1.0", "end-1c"):
            return
        try:
            if self.input.focus_get() is self.input:
                return
        except (KeyError, tk.TclError):
            pass
        self._placeholder = True
        self.input.insert("1.0", PLACEHOLDER, "placeholder")

    def _hide_placeholder(self) -> None:
        if self._placeholder:
            self._placeholder = False
            self.input.delete("1.0", "end")

    def _grow(self) -> None:
        """3 lines, growing to 8 with the text (§6.1)."""
        try:
            found = self.input.count("1.0", "end", "displaylines")
        except tk.TclError:
            return
        lines = found[0] if isinstance(found, tuple) else (found or 1)
        height = max(INPUT_LINES, min(INPUT_MAX_LINES, int(lines)))
        if int(self.input.cget("height")) != height:
            self.input.configure(height=height)

    def focus_input(self) -> None:
        self.input.focus_set()

    # --- The transcript ------------------------------------------------------------------------

    # Every write is batched: one Tk ``insert`` per block (Tk takes text/tags pairs), since
    # each Tk call may wait for the GIL while the worker decodes (04 §7.7: ≤ 10 ms a poll).

    def _insert(self, segments: list[tuple[str, tuple[str, ...]]],
                index: str = "end-1c") -> None:
        """``(text, tags)`` pairs at ``index`` in one call (``state`` already normal)."""
        if segments:
            flat: list[object] = []
            for text, tags in segments:
                flat += [text, tags]
            self.transcript.insert(index, *flat)

    def _write(self, text: str, *tags: str) -> None:
        t = self.transcript
        t.configure(state="normal")
        t.insert("end-1c", text, tags)
        t.configure(state="disabled")

    def _scroll(self) -> None:
        self.transcript.see("end")

    def _start_block(self) -> None:
        """A new block starts on its own line."""
        self._end_partial()
        t = self.transcript
        if t.compare("end-1c", "!=", "1.0") and t.get("end-2c", "end-1c") != "\n":
            self._write("\n")

    def start_exchange(self, request: str) -> None:
        """YOU, the author's words, then ASSISTANT and an empty Sent line."""
        self.show_empty(False)
        self._start_block()
        t = self.transcript
        t.configure(state="normal")
        self._insert([(YOU + "\n", (T_SPEAKER,)), (shown_text(request) + "\n", (T_BODY,)),
                      (ASSISTANT + "\n", (T_SPEAKER,))])
        t.mark_set("sent_start", "end-1c")
        t.mark_gravity("sent_start", "left")
        t.insert("end-1c", "\n", T_META)
        t.mark_set("sent_end", "end-2c")
        t.mark_gravity("sent_end", "right")
        t.mark_set("partial", "end-1c")
        t.mark_gravity("partial", "left")
        t.configure(state="disabled")
        self._answering = True
        self._partial = ""
        self._fence = False
        self._scroll()

    def set_sent(self, text: str) -> None:
        """The answer's Sent line, from the tool layer's record (SEC-F48-21)."""
        t = self.transcript
        if not self._answering:
            return
        t.configure(state="normal")
        t.delete("sent_start", "sent_end")
        t.insert("sent_start", one_line(text, 2000), T_META)
        t.configure(state="disabled")

    def sent_line(self) -> str:
        if not self._answering:
            return ""
        return self.transcript.get("sent_start", "sent_end")

    def answer_text(self, delta: str) -> None:
        """Streamed model text: plain text, escapes visible, fenced code in the code font,
        listed ``file:line`` links. Only the unfinished last line is drawn again; a run
        longer than ``PARTIAL_MAX`` without a line break is committed in pieces."""
        if not self._answering:
            return
        t = self.transcript
        raw = (self._partial + delta).replace("\r\n", "\n")
        *lines, tail = raw.split("\n")
        committed: list[tuple[str, tuple[str, ...]]] = []
        for line in lines:
            committed += self._segments(line, newline=True)
        while len(tail) > PARTIAL_MAX:
            committed += self._segments(tail[:PARTIAL_MAX], newline=True, soft=True)
            tail = tail[PARTIAL_MAX:]
        self._partial = tail
        t.configure(state="normal")
        if self._partial_shown:
            t.delete("partial", "end-1c")
        self._insert(committed)
        t.mark_set("partial", "end-1c")
        self._insert(self._segments(tail, newline=False, final=False) if tail else [])
        self._partial_shown = bool(tail)
        t.configure(state="disabled")
        self._scroll()

    def _segments(self, line: str, *, newline: bool, final: bool = True,
                  soft: bool = False) -> list[tuple[str, tuple[str, ...]]]:
        """One line of model text as ``(text, tags)`` pairs. A fence line opens or closes
        code (once it is complete); only committed text gets links (the unfinished line is
        drawn again with the next piece)."""
        fence = line.lstrip().startswith(FENCE)
        code = self._fence or fence
        if fence and final and newline and not soft:
            self._fence = not self._fence
        tag = T_CODE if code else T_BODY
        shown = shown_text(line)
        out: list[tuple[str, tuple[str, ...]]] = []
        at = 0
        for start, end, ref, number in (find_links(shown, self.listed())
                                        if final and not code else []):
            if start > at:
                out.append((shown[at:start], (tag,)))
            name = f"{T_LINK}{self._link_count}"
            self._link_count += 1
            self._links[name] = (ref, number)
            out.append((shown[start:end], (tag, T_LINK, name)))
            at = end
        if at < len(shown):
            out.append((shown[at:], (tag,)))
        if newline:
            out.append(("\n", (tag,)))
        return out

    def _link_click(self, event: tk.Event) -> str | None:
        """A click on a link: its place (one binding for every link)."""
        t = self.transcript
        for name in t.tag_names(t.index(f"@{event.x},{event.y}")):
            if name in self._links:
                self.on_link(*self._links[name])
                return "break"
        return None

    def _end_partial(self) -> None:
        """Close the streaming line before something else is written."""
        if not self._partial:
            return
        t = self.transcript
        partial, self._partial = self._partial, ""
        t.configure(state="normal")
        if self._partial_shown:
            t.delete("partial", "end-1c")
        self._insert(self._segments(partial, newline=True))
        t.mark_set("partial", "end-1c")
        self._partial_shown = False
        t.configure(state="disabled")

    def activity(self, text: str, failed: bool = False) -> None:
        self._start_block()
        self._write("· " + one_line(text, 300) + "\n", T_META)
        self._scroll()

    def add_card(self, proposal: Proposal) -> Card:
        self._start_block()
        t = self.transcript
        card = Card(self, t, proposal)
        self.cards.append(card)
        width = t.winfo_width()
        card.fit((width if width > 1 else self.px(280)) - 2 * self.px(INSET))
        t.configure(state="normal")
        t.window_create("end-1c", window=card.frame, padx=0, pady=self.px(4))
        t.insert("end-1c", "\n")
        t.configure(state="disabled")
        self._scroll()
        return card

    def notice(self, text: str, *, settings: bool = False) -> None:
        """A §6.6 message in the transcript, with [Open settings] when it helps."""
        self.show_empty(False)
        self._start_block()
        self._write(one_line(text, 600) + "\n", T_ERROR)
        if settings:
            button = ttk.Button(self.transcript, text=OPEN_SETTINGS, style="Secondary.TButton",
                                command=self.on_settings)
            self.transcript.configure(state="normal")
            self.transcript.window_create("end-1c", window=button, pady=self.px(2))
            self.transcript.insert("end-1c", "\n")
            self.transcript.configure(state="disabled")
        self._scroll()

    def finish(self, *, stopped: bool, usage: str) -> None:
        """The answer's end: "(stopped)" when stopped, then its usage line."""
        self._start_block()
        t = self.transcript
        t.configure(state="normal")
        self._insert(([(chat_texts.STOPPED_MARK + "\n", (T_META,))] if stopped else [])
                     + [(usage + "\n", (T_META,))])
        t.configure(state="disabled")
        if self._answering:
            t.mark_unset("sent_start", "sent_end", "partial")
        self._answering = False
        self._scroll()

    def clear(self) -> None:
        """New chat: an empty transcript."""
        t = self.transcript
        for card in self.cards:
            card.frame.destroy()
        self.cards.clear()
        t.configure(state="normal")
        t.delete("1.0", "end")
        if self._answering:
            t.mark_unset("sent_start", "sent_end", "partial")
        if self._links:
            t.tag_delete(*self._links)
        self._links.clear()
        for child in t.winfo_children():
            child.destroy()
        t.configure(state="disabled")
        self._partial, self._fence, self._answering = "", False, False
        self._partial_shown = False
        self.status_label.configure(text="")

    def transcript_text(self) -> str:
        return self.transcript.get("1.0", "end-1c")

    def links(self) -> dict[str, tuple[str, int]]:
        """Link tag → (ref, line), for the links shown (tests read it)."""
        return dict(self._links)

    def click_link(self, name: str) -> None:
        ref, line = self._links[name]
        self.on_link(ref, line)

    def texts(self) -> list[str]:
        """The pane's fixed texts as shown (tests read it)."""
        out = [HEADING.upper(), NEW_CHAT, str(self.model_label.cget("text"))]
        if self.is_empty_state():
            out += [str(w.cget("text")) for w in (self.empty_text, self.set_up_button,
                                                    self.empty_mcp, self.connect_button)
                    if w.winfo_manager()]
        out += [str(self.send_button.cget("text")), str(self.footer.cget("text"))]
        return out


def model_line(name: str, model: str) -> str:
    """§6.1: "{name} · {model}" ("Claude · claude-sonnet-5-5")."""
    return f"{name} · {model}" if model else name


__all__ = ["APPLIED", "APPLIED_MANY", "APPLY", "ASK_AGAIN", "ASK_AGAIN_TEXT", "ASSISTANT",
           "AssistPane", "CARD_LINES", "Card", "CardFile", "DISCARD", "DISCARDED", "EMPTY_MCP",
           "EMPTY_TEXT", "HEADING", "NEW_CHAT", "OPEN_SETTINGS", "PLACEHOLDER", "SEND", "SET_UP",
           "SHOW", "SHOW_ALL", "STALE", "STOP", "TITLE_MAX", "UNDO", "UNDONE", "UNDO_REFUSED",
           "YOU", "card_title", "file_heading", "find_links", "first_line", "model_line",
           "new_text", "shown_text"]

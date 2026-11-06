"""Studio's Guide pane, the **Guide checklist** (F47 ``01-design.md`` PR-F47-26, §6.4;
``04-technical.md`` §3.2, §7.4; the walkthrough plan of 2026-11), as the ``GuideWiring``
mixin of ``window.EditorWindow``.

Why this module exists: a first-time author opens Studio on a game made from the sample
story and needs to know what to do next. The Guide lists ``guide.py``'s five chapters, which
follow the beginner's guide (``docs/first-game.md``) part by part::

    GUIDE                                   ✕
    Five chapters that follow the beginner's guide. Each step ticks itself as you work.
    Open the beginner's guide
    ▾ 1. Your first game              2 of 9
      ✓ Play the sample
      ○ Name your game                [Show me]
        Type a title of your own in Game settings ▸ Game title.
        Read more
      …
      Read this part of the guide
    ▸ 2. Make it yours                0 of 8
    ▸ 4. Bigger games (optional)      0 of 9
    …

Chapters collapse; the current chapter (the first neither done nor skipped) opens by itself
when it changes, and a done chapter shows a tick and its done text. Each step ticks itself
from the last good check (``win.on_check_done``) and from what Studio saw happen (``marks``
and endings reached, kept per game in ``studio.json``). The next step to do, or the one
picked (a click on its text, or Tab to its Show me), shows its one-sentence hint and **Read
more**, which opens the guide at that step's heading (``guidereader``). Bigger games is
optional: **Skip this chapter** sets it aside (remembered per game) and **Do it after all**
brings it back.

The pane is a column at the right edge of the window. The Play bar's **? Guide** button and
**Help ▸ Guide checklist** show and hide it (``runwiring.toggle_guide``, which calls
``show_guide``); whether it is open is remembered per game in ``studiostate``. While it is
hidden, checks don't refresh it (a long story would pay for nothing): it refreshes once when
shown.

Imports only the standard library, ``engine.script`` and the editor's own modules
(ADR-0008).
"""

from __future__ import annotations

import time
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import replace
from tkinter import ttk
from typing import Any

from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import guide, icons, studiostate
from engine.tools.editor.checker import CheckResult
from engine.tools.editor.fieldwidgets import ScrollFrame
from engine.tools.editor.guide import GuideChapter, GuideFacts, GuideStep, ShowMe
from engine.tools.editor.theme import THEME
from engine.tools.editor.views import panel_header

GUIDE_HEADING = "Guide"
SHOW_ME = "Show me"
READ_MORE = "Read more"
READ_PART = "Read this part of the guide"
OPEN_DOC = "Open the beginner's guide"
SKIP = "Skip this chapter"
UNSKIP = "Do it after all"
SKIPPED_TEXT = "You skipped this chapter. Its steps are here when you want them."
CLOSE = "✕"
TIP_CLOSE = "Hide the Guide"
INTRO = ("Five chapters that follow the beginner's guide. Each step ticks itself as you "
         "work.")
PROGRESS = "{done} of {total}"
DONE_WORD = "Done"
SKIPPED_WORD = "Skipped"
OPTIONAL = "{title} (optional)"
CHEVRON_OPEN, CHEVRON_SHUT = "▾", "▸"
# Every step's hint, by key (the model's; the plain-words audit reads them here too).
STEP_HINTS: dict[str, str] = {step.key: step.hint for chapter in guide.CHAPTERS
                              for step in chapter.steps}

SHOW_TIP_MS = 4000                      # Show me for Play: how long the tooltip stays
QUIET_MS = 1500                         # after Show me, what it opened doesn't count
GUIDE_WIDTH = 300                       # px at 100 %: the column's first width
GUIDE_MIN_WIDTH = 220
INSET = 12                              # 08 §7: panel inset
ROW_GAP = 6
ICON_PX = 16
INDENT = 12                             # px at 100 %: a chapter's steps under its heading
CONFIG_READ_MAX = 1024 * 1024           # config.toml read for the title (it is far smaller)


def _link(parent: tk.Misc, text: str, command: Callable[[], object]) -> ttk.Button:
    """A quiet text button in the link color (keyboard: Tab, Enter or Space)."""
    button = ttk.Button(parent, text=text, style="Link.Chrome.Ghost.TButton", command=command,
                        cursor="hand2")
    for key in ("<Return>", "<KP_Enter>"):
        button.bind(key, lambda _e: (button.invoke(), "break")[1])
    return button


class GuidePane:
    """The pane's widgets on ``parent``: ``frame``, one ``ChapterBlock`` per chapter
    (``blocks``) and the chapters shown (``chapters``). ``show(chapters)`` redraws it. The
    window's callbacks: ``on_show_me(step)``, ``on_read(section)`` (None: the guide's top),
    ``on_skip(chapter, skipped)`` and ``on_close()``. ``sample``: the game came from the
    sample story (it has the "Play the sample" step)."""

    def __init__(self, parent: tk.Misc, *, fonts: dict, scale: float, sample: bool = False,
                 on_show_me: Callable[[GuideStep], object],
                 on_close: Callable[[], object],
                 on_read: Callable[[str | None], object] = lambda _s: None,
                 on_skip: Callable[[str, bool], object] = lambda _k, _s: None) -> None:
        px = self.px = lambda value: round(value * scale)       # noqa: E731
        self.scale, self.fonts = scale, fonts
        self.on_show_me, self.on_read, self.on_skip = on_show_me, on_read, on_skip
        side = THEME["sideBar.background"]
        style = ttk.Style(parent)
        style.configure("Link.Chrome.Ghost.TButton", foreground=THEME["link"],
                        padding=(px(2), px(1)), anchor="w")
        style.configure("Step.Chrome.Ghost.TButton", padding=(px(6), px(2)))
        style.configure("Step.Secondary.TButton", padding=(px(6), px(2)))
        style.configure("Chapter.Chrome.Ghost.TButton", padding=(px(2), px(4)), anchor="w",
                        font=fonts.get("bodyStrong"), foreground=THEME["strongForeground"])
        self.frame = ttk.Frame(parent, style="Side.TFrame")
        self.frame.columnconfigure(0, weight=1)
        head = panel_header(self.frame, GUIDE_HEADING, scale)
        head.grid(row=0, column=0, sticky="ew")
        self.close_button = ttk.Button(head, text=CLOSE, width=3, command=on_close,
                                       style="Chrome.Ghost.TButton")
        self.close_button.pack(side="right", padx=(0, px(4)))
        from engine.tools.editor.playbar import Tooltip
        Tooltip(self.close_button, TIP_CLOSE, fonts.get("small"))
        # The chapters scroll (with the wheel too) when the pane is short.
        self.scroll = ScrollFrame(self.frame, background=side)
        self.scroll.frame.grid(row=1, column=0, sticky="nsew")
        self.scroll.inner.configure(style="Side.TFrame")
        self.frame.rowconfigure(1, weight=1)
        body = self.body = ttk.Frame(self.scroll.inner, style="Side.TFrame",
                                     padding=(px(INSET), px(4), px(INSET), px(12)))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        self.intro = ttk.Label(body, text=INTRO, style="Side.Hint.TLabel", justify="left")
        self.intro.grid(row=0, column=0, sticky="w")
        self.doc_link = _link(body, OPEN_DOC, lambda: self.on_read(None))
        self.doc_link.grid(row=1, column=0, sticky="w", pady=(px(2), px(6)))
        self._icons = {
            True: icons.photo(self.frame, "success", px(ICON_PX), THEME["success"]),
            False: icons.photo(self.frame, "todo", px(ICON_PX), THEME["muted"]),
        }
        self.blocks: list[ChapterBlock] = []
        for index, spec in enumerate(guide.CHAPTERS):
            block = ChapterBlock(self, body, index, spec, sample=sample)
            block.frame.grid(row=2 + index, column=0, sticky="ew")
            self.blocks.append(block)
        self.chapters: tuple[GuideChapter, ...] = ()
        self.opened: set[str] = set()
        self._current: str | None = None
        self.frame.bind("<Configure>", self._wrap, add="+")

    @property
    def rows(self) -> tuple[GuideStep, ...]:
        """Every step shown, chapter by chapter (tests read the ticks)."""
        return tuple(row for chapter in self.chapters for row in chapter.rows)

    def _wrap(self, event: tk.Event) -> None:
        """Long texts wrap to the column's width."""
        width = max(self.px(80), event.width - 2 * self.px(INSET))
        self.intro.configure(wraplength=width)
        for block in self.blocks:
            block.wrap(width)

    def show(self, chapters: Sequence[GuideChapter]) -> None:
        """Tick and untick each step; the current chapter opens when it changes."""
        chapters = tuple(chapters)
        if chapters == self.chapters:
            return
        self.chapters = chapters
        current = next((c.key for c in chapters if c.current), None)
        if current != self._current:
            self._current = current
            self.opened = {current} if current is not None else set()
        for block, chapter in zip(self.blocks, chapters):
            block.show(chapter, opened=chapter.key in self.opened)

    def toggle(self, key: str) -> None:
        """A chapter's heading clicked: open or close it."""
        self.opened ^= {key}
        for block in self.blocks:
            if block.key == key and block.chapter is not None:
                block.show(block.chapter, opened=key in self.opened)

    def texts(self) -> list[str]:
        """What the pane shows, top to bottom (tests and the plain-words audit read it)."""
        out = [GUIDE_HEADING, INTRO, OPEN_DOC]
        for block in self.blocks:
            out += block.texts()
        return out


class ChapterBlock:
    """One chapter: its heading (a button that opens and closes it, with the tick or the
    count), and when open its done or skipped note, its steps, and its links."""

    def __init__(self, pane: GuidePane, parent: tk.Misc, index: int,
                 spec: guide.ChapterSpec, *, sample: bool) -> None:
        px, fonts = pane.px, pane.fonts
        self.pane, self.key, self.spec = pane, spec.key, spec
        self.chapter: GuideChapter | None = None
        self.opened = False
        self.frame = ttk.Frame(parent, style="Side.TFrame")
        self.frame.columnconfigure(0, weight=1)
        title = OPTIONAL.format(title=spec.title) if spec.optional else spec.title
        self.title = f"{index + 1}. {title}"
        self.head = ttk.Button(self.frame, text=f"{CHEVRON_SHUT} {self.title}",
                               style="Chapter.Chrome.Ghost.TButton",
                               command=lambda: pane.toggle(self.key))
        self.head.grid(row=0, column=0, sticky="ew", pady=(px(4), 0))
        self.count = ttk.Label(self.frame, text="", style="Side.Hint.TLabel", compound="left")
        self.count.grid(row=0, column=1, sticky="e", pady=(px(4), 0))
        self.body = ttk.Frame(self.frame, style="Side.TFrame",
                              padding=(px(INDENT), 0, 0, px(6)))
        self.body.columnconfigure(0, weight=1)
        card = THEME["card.background"]
        self.done_card = tk.Frame(self.body, background=card, padx=px(10), pady=px(8))
        tk.Label(self.done_card, image=pane._icons[True], background=card,
                 borderwidth=0).pack(side="left", anchor="n", padx=(0, px(8)))
        self.done_label = tk.Label(self.done_card, text=spec.done_text, background=card,
                                   foreground=THEME["strongForeground"], justify="left",
                                   anchor="w", font=fonts.get("body"), borderwidth=0)
        self.done_label.pack(side="left", fill="x", expand=True)
        self.skipped_note = ttk.Label(self.body, text=SKIPPED_TEXT, style="Side.Hint.TLabel",
                                      justify="left")
        steps = ttk.Frame(self.body, style="Side.TFrame")
        steps.grid(row=2, column=0, sticky="ew")
        steps.columnconfigure(1, weight=1)
        shown = [step for step in spec.steps if sample or not step.sample_only]
        self.step_rows = [StepRow(self, steps, n, step) for n, step in enumerate(shown)]
        self.selected: str | None = None
        links = ttk.Frame(self.body, style="Side.TFrame")
        links.grid(row=3, column=0, sticky="w", pady=(px(6), 0))
        self.part_link = _link(links, READ_PART, lambda: pane.on_read(spec.section))
        self.part_link.pack(anchor="w")
        self.skip_link: ttk.Button | None = None
        if spec.optional:
            self.skip_link = _link(links, SKIP, self._skip)
            self.skip_link.pack(anchor="w")

    def _skip(self) -> None:
        skipped = bool(self.chapter is not None and self.chapter.skipped)
        self.pane.on_skip(self.key, not skipped)

    def wrap(self, width: int) -> None:
        px = self.pane.px
        inner = width - px(INDENT)                  # the steps' indent under the heading
        self.done_label.configure(wraplength=inner - px(ICON_PX + 28))
        self.skipped_note.configure(wraplength=inner)
        button = max((row.button.winfo_reqwidth() for row in self.step_rows), default=0)
        for row in self.step_rows:
            row.wrap(inner, button)

    def select(self, key: str) -> None:
        """A step picked (its text clicked, or its Show me focused): its hint shows."""
        if self.chapter is not None and key != self.selected:
            self.selected = key
            self._show_steps(self.chapter)

    def show(self, chapter: GuideChapter, *, opened: bool) -> None:
        px = self.pane.px
        changed = self.chapter is None or self.chapter.rows != chapter.rows
        self.chapter, self.opened = chapter, opened
        self.head.configure(text=f"{CHEVRON_OPEN if opened else CHEVRON_SHUT} {self.title}")
        if chapter.done:
            self.count.configure(text=DONE_WORD, image=self.pane._icons[True])
        elif chapter.skipped:
            self.count.configure(text=SKIPPED_WORD, image="")
        else:
            self.count.configure(text=PROGRESS.format(done=chapter.ticked,
                                                      total=len(chapter.rows)), image="")
        if not opened:
            self.body.grid_remove()
            return
        self.body.grid(row=1, column=0, columnspan=2, sticky="ew")
        if chapter.done:
            self.done_card.grid(row=0, column=0, sticky="ew", pady=(px(2), px(8)))
        else:
            self.done_card.grid_remove()
        if chapter.skipped:
            self.skipped_note.grid(row=1, column=0, sticky="w", pady=(0, px(6)))
        else:
            self.skipped_note.grid_remove()
        if self.skip_link is not None:
            if chapter.done:
                self.skip_link.pack_forget()
            else:
                self.skip_link.configure(text=UNSKIP if chapter.skipped else SKIP)
                self.skip_link.pack(anchor="w")
        if changed:                             # a tick moved: the next step is picked
            self.selected = None
        self._show_steps(chapter)

    def _show_steps(self, chapter: GuideChapter) -> None:
        upcoming = next((row.key for row in chapter.rows if not row.done), None)
        picked = self.selected or upcoming
        for widget, row in zip(self.step_rows, chapter.rows):
            widget.show(row, next_up=row.key == upcoming, open_=row.key == picked)

    def texts(self) -> list[str]:
        out = [str(self.head.cget("text")), str(self.count.cget("text"))]
        if not self.opened:
            return out
        if self.done_card.winfo_manager():
            out.append(str(self.done_label.cget("text")))
        if self.skipped_note.winfo_manager():
            out.append(SKIPPED_TEXT)
        for row in self.step_rows:
            out.append(str(row.label.cget("text")))
            if row.hint.winfo_manager():
                out += [str(row.hint.cget("text")), READ_MORE]
        out.append(READ_PART)
        if self.skip_link is not None and self.skip_link.winfo_manager():
            out.append(str(self.skip_link.cget("text")))
        return out


class StepRow:
    """One step: its tick, its text (muted once done), Show me, and while it is the next
    step to do (or picked) its hint and **Read more**. Show me is secondary on the next step
    and a ghost on the rest."""

    def __init__(self, block: ChapterBlock, parent: tk.Misc, index: int,
                 spec: guide.StepSpec) -> None:
        pane = block.pane
        px = pane.px
        self.block, self.key, self.spec = block, spec.key, spec
        self.step: GuideStep | None = None
        top = px(ROW_GAP) if index else 0
        self.icon = ttk.Label(parent, image=pane._icons[False], style="Side.TLabel")
        self.icon.grid(row=2 * index, column=0, sticky="nw", padx=(0, px(8)), pady=(top, 0))
        self.label = ttk.Label(parent, text=spec.text, style="Side.TLabel",
                               font=pane.fonts.get("body"), cursor="hand2")
        self.label.grid(row=2 * index, column=1, sticky="w", pady=(top, 0))
        self.label.bind("<Button-1>", lambda _e: block.select(self.key))
        self.button = ttk.Button(parent, text=SHOW_ME, style="Step.Chrome.Ghost.TButton",
                                 command=self.press)
        self.button.grid(row=2 * index, column=2, sticky="ne", pady=(top, 0))
        for key in ("<Return>", "<KP_Enter>"):
            self.button.bind(key, lambda _e: self._enter())
        self.button.bind("<FocusIn>", lambda _e: block.select(self.key), add="+")
        self.details = ttk.Frame(parent, style="Side.TFrame")
        self.hint = ttk.Label(self.details, text=spec.hint, style="Side.Hint.TLabel",
                              justify="left")
        self.hint.pack(anchor="w")
        self.more = _link(self.details, READ_MORE, lambda: pane.on_read(spec.section))
        self.more.pack(anchor="w")
        self._details_grid = dict(row=2 * index + 1, column=1, columnspan=2, sticky="w",
                                  pady=(px(2), 0))

    def _enter(self) -> str:
        self.press()
        return "break"

    def press(self) -> None:
        if self.step is not None:
            self.block.pane.on_show_me(self.step)

    def wrap(self, width: int, button: int) -> None:
        px = self.block.pane.px
        self.hint.configure(wraplength=width - px(ICON_PX + 8))
        self.label.configure(wraplength=max(px(60), width - px(ICON_PX + 16) - button))

    def show(self, step: GuideStep, *, next_up: bool, open_: bool) -> None:
        self.step = step
        self.icon.configure(image=self.block.pane._icons[step.done])
        self.label.configure(foreground=THEME["muted"] if step.done
                             else THEME["foreground"])
        self.button.configure(style="Step.Secondary.TButton" if next_up
                              else "Step.Chrome.Ghost.TButton")
        if open_:
            self.details.grid(**self._details_grid)
        else:
            self.details.grid_remove()

    @property
    def hint_shown(self) -> bool:
        return bool(self.details.winfo_manager())


def insert_doc(item: str | None) -> Any:
    """The Insert menu's doc for a Guide ``INSERT`` item: its picker title ("Choice",
    "Music", "Go to a day"); the old keys ``choice`` and ``ending`` still work."""
    from engine.tools.editor import assist, forms
    from engine.tools.editor.formdialogs import entry_title
    old = {"choice": forms.CHOICE_FORM, "ending": "ending"}
    for _group, docs in assist.insert_menu():
        for doc in docs:
            if (item in old and doc.key == old[item]) or entry_title(doc) == item:
                return doc
    return None


class GuideWiring:
    """The Guide pane in the window: building it, showing and hiding it, ticking its steps
    after each check and on what Studio sees happen, Show me and Read more."""

    guide_pane: GuidePane
    _guide_facts: GuideFacts | None = None
    _guide_sample = False
    _guide_marks: frozenset[str] = frozenset()
    _guide_reached: frozenset[str] = frozenset()
    _guide_stale = False
    _guide_quiet_until = 0.0

    def _build_guide(self) -> None:
        """Made after the panes; shown when this game's Guide was left open."""
        state = studiostate.read_state(self.paths.root)
        known = state if isinstance(state, studiostate.StudioState) else None
        self._guide_sample = bool(known and known.sample)
        self._guide_marks = frozenset(known.guide if known else ())
        self._guide_reached = frozenset(known.reached if known else ())
        self.guide_pane = GuidePane(self.hpane.master, fonts=self.fonts, scale=self.scale,
                                    sample=self._guide_sample,
                                    on_show_me=self.guide_show_me, on_close=self.toggle_guide,
                                    on_read=self.guide_read, on_skip=self.guide_skip)
        self._guide_facts = None
        self._guide_stale = True
        # First, so the celebrations after it read this check's facts, not the last one's.
        self.on_check_done.insert(0, self.refresh_guide)
        subscribe = getattr(self, "on_game_event", None)     # endings a Play reaches
        if subscribe is not None:
            subscribe(self._guide_game_event)
        self._show_guide_rows()
        if self.guide_shown:
            self.show_guide(True)

    def guide_open(self) -> bool:
        return bool(self.guide_pane.frame.winfo_manager())

    def show_guide(self, shown: bool) -> None:
        """Show or hide the Guide column (the Play bar's ? Guide calls this); a Guide shown
        after checks it missed reads the last one now."""
        self._guide_wanted = shown
        self.dock_apply()
        if shown and self._guide_stale:
            self.refresh_guide()

    def _guide_played(self) -> bool:
        return bool(getattr(self, "_played_marked", False))

    def _config_text(self) -> str | None:
        """``config.toml``'s text: the open document's (unsaved edits too), else the file."""
        record = self.files.get(CONFIG_REF)
        if record is not None and record.editable:
            return record.widget.get("1.0", "end-1c")
        try:
            with open(self.paths.root / CONFIG_REF, "rb") as handle:
                data = handle.read(CONFIG_READ_MAX)
            return data.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def refresh_guide(self, result: CheckResult | None = None) -> None:
        """After a check: what it says was fixed is marked (always: it's cheap), and, while
        the Guide is shown, new facts from it (a check that didn't load keeps the last)."""
        if self.closed:
            return
        result = self.check_result if result is None else result
        if result is not None:
            loaded = result.loaded
            self._set_marks(guide.note_check(
                self._guide_marks, errors=guide.errors_in(result),
                unreachable=bool(guide.unreachable_in(result)) if loaded else None,
                leftovers=guide.leftovers_in(result)))
        if not getattr(self, "_guide_wanted", False):
            self._guide_stale = True                # read when the Guide is shown
            return
        self._guide_stale = False
        from engine.tools.editor.database import script_texts
        facts = guide.facts_from(result, script_texts(self), folder_name=self.game_name,
                                 config_text=self._config_text(),
                                 played=self._guide_played(), marks=self._guide_marks,
                                 reached=self._guide_reached)
        if facts is not None:
            self._guide_facts = facts
        self._show_guide_rows()

    def _set_marks(self, marks: frozenset[str]) -> None:
        if marks == self._guide_marks:
            return
        self._guide_marks = marks
        self.save_studio_state(guide=tuple(sorted(marks)))
        if self._guide_facts is not None:
            self._guide_facts = replace(self._guide_facts, marks=marks)

    def guide_mark(self, mark: str) -> None:
        """Studio saw something happen that a step ticks on (``guide.MARKS``). What Show
        me itself opened doesn't count (the stage it shows at a line, say)."""
        if self.closed or mark in self._guide_marks:
            return
        if mark == guide.STAGE_VIEWED and time.monotonic() < self._guide_quiet_until:
            return
        self._set_marks(self._guide_marks | {mark})
        self._show_guide_rows()

    def _guide_game_event(self, kind: str, data: dict) -> None:
        """A line report from the running game: an ending reached is kept for the Guide."""
        name = data.get("id") if kind == "ending" else None
        if not isinstance(name, str) or not name.isidentifier() or self.closed \
                or name in self._guide_reached:
            return
        self._guide_reached = self._guide_reached | {name}
        self.save_studio_state(reached=tuple(sorted(self._guide_reached)))
        if self._guide_facts is not None:
            self._guide_facts = replace(self._guide_facts, reached=self._guide_reached)
        self._show_guide_rows()

    def guide_played(self) -> None:
        """A Play reached the game window: Play the sample ticks."""
        if self._guide_facts is not None:
            self._guide_facts = replace(self._guide_facts, played=True)
        self._show_guide_rows()

    def guide_skip(self, chapter: str, skipped: bool) -> None:
        """Skip this chapter / Do it after all (an optional chapter; remembered per game)."""
        mark = guide.skip_mark(chapter)
        marks = self._guide_marks | {mark} if skipped else self._guide_marks - {mark}
        self._set_marks(marks)
        self._show_guide_rows()

    def guide_chapters(self) -> tuple[GuideChapter, ...]:
        facts = self._guide_facts or GuideFacts(folder_name=self.game_name,
                                                played=self._guide_played(),
                                                marks=self._guide_marks,
                                                reached=self._guide_reached)
        return guide.chapters(facts, sample=self._guide_sample)

    def guide_rows(self) -> tuple[GuideStep, ...]:
        """The first chapter's steps (its end is the "first game done" milestone)."""
        return self.guide_chapters()[0].rows

    def _show_guide_rows(self) -> None:
        chapters = self.guide_chapters()
        self.guide_pane.show(chapters)
        changed = getattr(self, "guide_chapters_changed", None)    # the celebrations
        if callable(changed) and self._guide_facts is not None:
            changed(chapters)

    # --- Read more -------------------------------------------------------------------------

    def guide_read(self, section: str | None) -> None:
        """Read more: the beginner's guide at ``section`` (None: its top)."""
        if self.closed:
            return
        from engine.tools.editor import guidereader
        guidereader.show_guide(self, heading=section)

    # --- Show me ---------------------------------------------------------------------------

    def guide_show_me(self, step: GuideStep) -> None:
        """Open the place where ``step`` is done, its New button (or form) in focus."""
        if self.closed:
            return
        self._guide_quiet_until = time.monotonic() + QUIET_MS / 1000
        target: ShowMe = step.show_me
        if target.place == guide.SETTINGS:
            self._show_me_settings(target.item)
        elif target.place == guide.DATABASE:
            self._show_me_database(target.item, target.target)
        elif target.place == guide.STORY_MAP:
            if not self._open_scene(target.item or guide.START_LABEL) and target.item:
                self._open_scene(guide.START_LABEL)
        elif target.place == guide.INSERT:
            if self._open_scene(guide.START_LABEL) and self.story is not None:
                doc = insert_doc(target.item)
                self.story.insert(None, doc=doc)
        elif target.place == guide.PLAY:
            self.show_play_button(start=target.item == guide.START_LABEL)
        elif target.place == guide.MENU:
            self._show_me_menu(target.item or "")
        elif target.place == guide.PROBLEMS:
            self.focus_problems()
        elif target.place == guide.UPDATE:
            button = self.play_bar.update_button
            if button.winfo_manager():
                self._flash_tip(button)
            else:
                self.show_play_button()

    def show_play_button(self, *, start: bool = False) -> None:
        """Show me for Play: the ▶ Play button (``start``: its ▾, Play from the start)
        focused, its tooltip shown for 4 s."""
        bar = self.play_bar
        self._flash_tip(bar.more_button if start else bar.play_button)

    def _flash_tip(self, button: Any) -> None:
        button.focus_set()
        tip = getattr(button, "tooltip", None)
        if tip is not None and self.root.winfo_viewable():
            tip.show()
            self.root.after(SHOW_TIP_MS, tip.hide)

    def _show_me_database(self, category: str | None, name: str | None) -> None:
        """A Database category, its New button focused; with ``name``, that entry's form."""
        self.show_tab(self.tab_index("database"))
        database = self.database
        if category is not None:
            database.select_category(category)
        row = None
        if name is not None:
            row = next((r for r in database.rows.get(database.category, ())
                        if r.entry is not None and getattr(r.entry, "name", None) == name),
                       None)
        if row is not None:
            database.select(row.iid)
            focus = getattr(database, "_focus_form", None)
            if callable(focus):
                focus()
            return
        if database.new_button.winfo_manager():
            database.new_button.focus_set()
        else:
            database.list_tree.focus_set()

    def _show_me_menu(self, label: str) -> None:
        """A File menu entry, as if chosen (New script file, Build game…)."""
        menu = self.file_menu
        try:
            end = menu.index("end")
        except tk.TclError:
            return
        for index in range(0 if end is None else end + 1):
            try:
                text = str(menu.entrycget(index, "label"))
            except tk.TclError:
                continue
            if text.rstrip("…") == label.rstrip("…"):
                menu.invoke(index)
                return

    def _show_me_settings(self, page: str | None) -> None:
        """Game settings on ``page``; before that tab exists, ``config.toml``'s title."""
        if any(tab.name == "settings" for tab in self.tabs):
            self.show_tab(self.tab_index("settings"))
            view = getattr(self, "settings", None)
            select = getattr(view, "select_page", None)
            if callable(select) and page is not None:
                select(page)
                focus_form = getattr(view, "_focus_form", None)   # the page's first field
                if callable(focus_form):
                    focus_form()
            return
        text = self._config_text() or ""
        line = next((number for number, row in enumerate(text.split("\n"), start=1)
                     if row.strip().startswith("title")), 1)
        self.jump_to(CONFIG_REF, line)

    def _open_scene(self, name: str) -> bool:
        """The Story map with ``name``'s box opened beside it on the Events list (focused).
        False when there is no such scene (the map shows, focused)."""
        self.show_tab(self.tab_index("map"))
        self.refresh_story_map()
        view = self.story_map
        index = view.layout.index_of(name) if view.layout is not None else None
        if index is None:
            return False
        self.side_tab = "events"
        self.open_label_beside(view.layout.boxes[index])
        rows = self.events_view.rows
        if rows:
            self.events_view.select(len(rows) - 1)
        self.events_view.tree.focus_set()
        return True


__all__ = ["CLOSE", "ChapterBlock", "GUIDE_HEADING", "GUIDE_MIN_WIDTH", "GUIDE_WIDTH",
           "GuidePane", "GuideWiring", "INTRO", "OPEN_DOC", "PROGRESS", "READ_MORE",
           "READ_PART", "SHOW_ME", "SKIP", "STEP_HINTS", "StepRow", "TIP_CLOSE", "UNSKIP",
           "insert_doc"]

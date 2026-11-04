"""Studio's Guide pane, "Your first game" (F47 ``01-design.md`` PR-F47-26, §6.4;
``04-technical.md`` §3.2, §7.4), as the ``GuideWiring`` mixin of ``window.EditorWindow``.

Why this module exists: a first-time author opens Studio on a game made from the sample
story and needs to know what to do next. The Guide lists ``guide.py``'s seven steps; each
ticks itself from the last good check (``win.on_check_done``) and from Play reaching the
game window, and each has **Show me**, which opens the place the step is done in::

    GUIDE                                   ✕
    Your first game               2 of 7 done
    Each step ticks itself as you work.
    ✓ Name your game                [Show me]
    ○ Add a character               [Show me]
      Make a character of your own in the Database.
    …

The pane is a column at the right edge of the window, beside the tabs and the Problems and
Help panels (the bottom strip is too short for seven steps). The Play bar's **? Guide**
button and **Help ▸ Your first game** show and hide it (``runwiring.toggle_guide``, which
calls ``show_guide``); whether it is open is remembered per game in ``studiostate``.

Show me targets (``guide.ShowMe``): Game settings' "game" page (the Game settings tab when
it exists, else ``config.toml``'s title line in the Editor), a Database category with its
**+ New** button focused, the Story map's ``start`` scene opened beside the map on its
Events list, the Insert form for a choice or an ending on that scene, and the ▶ Play button.

Imports only the standard library, ``engine.script`` and the editor's own modules
(ADR-0008).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import replace
from tkinter import ttk
from typing import Any

from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import guide, icons, studiostate
from engine.tools.editor.checker import CheckResult
from engine.tools.editor.fieldwidgets import ScrollFrame
from engine.tools.editor.guide import GuideFacts, GuideStep, ShowMe
from engine.tools.editor.theme import THEME
from engine.tools.editor.views import panel_header

GUIDE_HEADING = "Guide"
SHOW_ME = "Show me"
CLOSE = "✕"
TIP_CLOSE = "Hide the Guide"
INTRO = "Each step ticks itself as you work."
PROGRESS = "{done} of {total} done"
# The muted line under the next step to do: what it means, in plain words.
STEP_HINTS: dict[str, str] = {
    "name": "Give your game a title of its own.",
    "character": "Make a character of your own in the Database.",
    "background": "Add a picture for a place in your story.",
    "scene": "Open the first scene and give it a few lines.",
    "choice": "Let the player pick what happens next.",
    "ending": "Finish your story with an ending card.",
    "play": "Press ▶ Play to see your game run.",
}

GUIDE_WIDTH = 280                       # px at 100 %: the column's first width
GUIDE_MIN_WIDTH = 220
INSET = 12                              # 08 §7: panel inset
ROW_GAP = 6
ICON_PX = 16
CONFIG_READ_MAX = 1024 * 1024           # config.toml read for the title (it is far smaller)


class GuidePane:
    """The pane's widgets on ``parent``: ``frame``, ``rows`` (the steps shown), one
    ``StepRow`` per step (``step_rows``), ``progress``, ``done_card``. ``show(rows)``
    redraws it; ``on_show_me(step)`` and ``on_close()`` are the window's."""

    def __init__(self, parent: tk.Misc, *, fonts: dict, scale: float,
                 on_show_me: Callable[[GuideStep], object],
                 on_close: Callable[[], object]) -> None:
        px = lambda value: round(value * scale)       # noqa: E731
        self.scale = scale
        self.on_show_me = on_show_me
        side = THEME["sideBar.background"]
        self.frame = ttk.Frame(parent, style="Side.TFrame")
        self.frame.columnconfigure(0, weight=1)
        head = panel_header(self.frame, GUIDE_HEADING, scale)
        head.grid(row=0, column=0, sticky="ew")
        self.close_button = ttk.Button(head, text=CLOSE, width=3, command=on_close,
                                       style="Chrome.Ghost.TButton")
        self.close_button.pack(side="right", padx=(0, px(4)))
        from engine.tools.editor.playbar import Tooltip
        Tooltip(self.close_button, TIP_CLOSE, fonts.get("small"))
        # The steps scroll (with the wheel too) when the pane is short, e.g. docked below.
        self.scroll = ScrollFrame(self.frame, background=side)
        self.scroll.frame.grid(row=1, column=0, sticky="nsew")
        self.scroll.inner.configure(style="Side.TFrame")
        self.frame.rowconfigure(1, weight=1)
        body = self.body = ttk.Frame(self.scroll.inner, style="Side.TFrame",
                                     padding=(px(INSET), 0))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        top = ttk.Frame(body, style="Side.TFrame")
        top.grid(row=0, column=0, sticky="ew", pady=(px(4), 0))
        self.title = ttk.Label(top, text=guide.GUIDE_TITLE, style="Side.TLabel",
                               font=fonts.get("bodyStrong"),
                               foreground=THEME["strongForeground"])
        self.title.pack(side="left")
        self.progress = ttk.Label(top, text="", style="Side.Hint.TLabel")
        self.progress.pack(side="right")
        self.intro = ttk.Label(body, text=INTRO, style="Side.Hint.TLabel", justify="left")
        self.intro.grid(row=1, column=0, sticky="w", pady=(px(2), px(8)))
        # All done (§6.4): a raised card with the success tick, above the steps.
        card = THEME["card.background"]
        self.done_card = tk.Frame(body, background=card, padx=px(10), pady=px(8))
        self._done_icon = icons.photo(self.frame, "success", px(ICON_PX), THEME["success"])
        tk.Label(self.done_card, image=self._done_icon, background=card,
                 borderwidth=0).pack(side="left", anchor="n", padx=(0, px(8)))
        self.done_label = tk.Label(self.done_card, text=guide.DONE_TEXT, background=card,
                                   foreground=THEME["strongForeground"], justify="left",
                                   anchor="w", font=fonts.get("body"), borderwidth=0)
        self.done_label.pack(side="left", fill="x", expand=True)
        self._icons = {
            True: icons.photo(self.frame, "success", px(ICON_PX), THEME["success"]),
            False: icons.photo(self.frame, "todo", px(ICON_PX), THEME["muted"]),
        }
        self.step_rows: list[StepRow] = []
        steps_frame = ttk.Frame(body, style="Side.TFrame")
        steps_frame.grid(row=3, column=0, sticky="ew")
        steps_frame.columnconfigure(1, weight=1)
        for index, spec in enumerate(guide.STEPS):
            self.step_rows.append(StepRow(self, steps_frame, index, spec, fonts=fonts,
                                          scale=scale, background=side))
        self.rows: tuple[GuideStep, ...] = ()
        self.frame.bind("<Configure>", self._wrap, add="+")

    def _wrap(self, event: tk.Event) -> None:
        """Long texts wrap to the column's width."""
        px = lambda value: round(value * self.scale)       # noqa: E731
        width = max(px(80), event.width - 2 * px(INSET))
        self.intro.configure(wraplength=width)
        self.done_label.configure(wraplength=width - px(ICON_PX + 28))
        button = max(row.button.winfo_reqwidth() for row in self.step_rows)
        for row in self.step_rows:
            row.hint.configure(wraplength=width - px(ICON_PX + 8))
            row.label.configure(wraplength=max(px(60), width - px(ICON_PX + 12) - button))

    def show(self, rows: Sequence[GuideStep]) -> None:
        """Tick, untick and hint each step; the done card when every step is done."""
        rows = tuple(rows)
        if rows == self.rows:
            return
        self.rows = rows
        done = sum(1 for row in rows if row.done)
        self.progress.configure(text=PROGRESS.format(done=done, total=len(rows)))
        if guide.all_done(rows):
            self.done_card.grid(row=2, column=0, sticky="ew",
                                pady=(0, round(10 * self.scale)))
        else:
            self.done_card.grid_remove()
        upcoming = next((row.key for row in rows if not row.done), None)
        for widget, row in zip(self.step_rows, rows):
            widget.show(row, next_up=row.key == upcoming)

    def texts(self) -> list[str]:
        """What the pane shows, top to bottom (tests and the plain-words audit read it)."""
        out = [GUIDE_HEADING, guide.GUIDE_TITLE, str(self.progress.cget("text")), INTRO]
        if self.done_card.winfo_manager():
            out.append(guide.DONE_TEXT)
        for row in self.step_rows:
            out.append(str(row.label.cget("text")))
            if row.hint.winfo_manager():
                out.append(str(row.hint.cget("text")))
        return out


class StepRow:
    """One step: its tick, its text (muted once done), Show me, and the hint while it is
    the next step to do. Show me is secondary on the next step and a ghost on the rest."""

    def __init__(self, pane: GuidePane, parent: tk.Misc, index: int, spec: guide.StepSpec,
                 *, fonts: dict, scale: float, background: str) -> None:
        px = lambda value: round(value * scale)       # noqa: E731
        self.pane, self.key = pane, spec.key
        self.step: GuideStep | None = None
        top = px(ROW_GAP) if index else 0
        self.icon = ttk.Label(parent, image=pane._icons[False], style="Side.TLabel")
        self.icon.grid(row=2 * index, column=0, sticky="w", padx=(0, px(8)), pady=(top, 0))
        self.label = ttk.Label(parent, text=spec.text, style="Side.TLabel",
                               font=fonts.get("body"))
        self.label.grid(row=2 * index, column=1, sticky="w", pady=(top, 0))
        self.button = ttk.Button(parent, text=SHOW_ME, style="Chrome.Ghost.TButton",
                                 command=self.press)
        self.button.grid(row=2 * index, column=2, sticky="e", pady=(top, 0))
        for key in ("<Return>", "<KP_Enter>"):
            self.button.bind(key, lambda _e: self._enter())
        self.hint = ttk.Label(parent, text=STEP_HINTS[spec.key], style="Side.Hint.TLabel",
                              justify="left")
        self._hint_grid = dict(row=2 * index + 1, column=1, columnspan=2, sticky="w",
                               pady=(px(2), 0))

    def _enter(self) -> str:
        self.press()
        return "break"

    def press(self) -> None:
        if self.step is not None:
            self.pane.on_show_me(self.step)

    def show(self, step: GuideStep, *, next_up: bool) -> None:
        self.step = step
        self.icon.configure(image=self.pane._icons[step.done])
        self.label.configure(foreground=THEME["muted"] if step.done
                             else THEME["foreground"])
        self.button.configure(style="Secondary.TButton" if next_up
                              else "Chrome.Ghost.TButton")
        if next_up:
            self.hint.grid(**self._hint_grid)
        else:
            self.hint.grid_remove()


def insert_doc(item: str | None) -> Any:
    """The Insert menu's doc for a Guide ``INSERT`` item (``choice`` → Menu, ``ending``)."""
    from engine.tools.editor import assist, forms
    key = forms.CHOICE_FORM if item == "choice" else item
    for _group, docs in assist.insert_menu():
        for doc in docs:
            if doc.key == key:
                return doc
    return None


class GuideWiring:
    """The Guide pane in the window: building it, showing and hiding it, ticking its steps
    after each check, and Show me."""

    guide_pane: GuidePane
    _guide_facts: GuideFacts | None = None
    _guide_sample = False

    def _build_guide(self) -> None:
        """Made after the panes; shown when this game's Guide was left open."""
        self.guide_pane = GuidePane(self.hpane.master, fonts=self.fonts, scale=self.scale,
                                    on_show_me=self.guide_show_me, on_close=self.toggle_guide)
        state = studiostate.read_state(self.paths.root)
        self._guide_sample = isinstance(state, studiostate.StudioState) and state.sample
        self._guide_facts = None
        self.on_check_done.append(self.refresh_guide)
        self._show_guide_rows()
        if self.guide_shown:
            self.show_guide(True)

    def guide_open(self) -> bool:
        return bool(self.guide_pane.frame.winfo_manager())

    def show_guide(self, shown: bool) -> None:
        """Show or hide the Guide column (the Play bar's ? Guide calls this)."""
        self._guide_wanted = shown
        self.dock_apply()

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
        """After a check: new facts from it (a check that didn't load keeps the last)."""
        if self.closed:
            return
        result = self.check_result if result is None else result
        from engine.tools.editor import declarations as dec
        from engine.tools.editor.database import script_texts
        texts = script_texts(self)
        facts = guide.facts_from(result, guide.read_scenes(texts),
                                 folder_name=self.game_name,
                                 config_text=self._config_text(),
                                 played=self._guide_played())
        if facts is not None:
            # Characters come from the check's launch phase; until Studio's first Play,
            # Save or Check now, the Database's own reading of the scripts finds them.
            written = frozenset(d.name for d in dec.scan(texts) if d.kind == dec.CHARACTER)
            self._guide_facts = replace(facts, characters=facts.characters | written)
        self._show_guide_rows()

    def guide_played(self) -> None:
        """A Play reached the game window: Play it ticks."""
        if self._guide_facts is not None:
            self._guide_facts = replace(self._guide_facts, played=True)
        self._show_guide_rows()

    def guide_rows(self) -> tuple[GuideStep, ...]:
        facts = self._guide_facts or GuideFacts(folder_name=self.game_name,
                                                played=self._guide_played())
        return guide.steps(facts, sample=self._guide_sample)

    def _show_guide_rows(self) -> None:
        self.guide_pane.show(self.guide_rows())

    # --- Show me ---------------------------------------------------------------------------

    def guide_show_me(self, step: GuideStep) -> None:
        """Open the place where ``step`` is done, its New button (or form) in focus."""
        if self.closed:
            return
        target: ShowMe = step.show_me
        if target.place == guide.SETTINGS:
            self._show_me_settings(target.item)
        elif target.place == guide.DATABASE:
            self.show_tab(self.tab_index("database"))
            database = self.database
            database.select_category(target.item)
            database.new_button.focus_set()
        elif target.place == guide.STORY_MAP:
            self._open_scene(target.item or guide.START_LABEL)
        elif target.place == guide.INSERT:
            if self._open_scene(guide.START_LABEL) and self.story is not None:
                doc = insert_doc(target.item)
                self.story.insert(None, doc=doc)
        elif target.place == guide.PLAY:
            button = self.play_bar.play_button
            button.focus_set()
            tip = getattr(button, "tooltip", None)
            if tip is not None and self.root.winfo_viewable():
                tip.show()
                self.root.after(4000, tip.hide)

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


__all__ = ["CLOSE", "GUIDE_HEADING", "GUIDE_MIN_WIDTH", "GUIDE_WIDTH", "GuidePane",
           "GuideWiring", "INTRO", "PROGRESS", "SHOW_ME", "STEP_HINTS", "StepRow",
           "TIP_CLOSE", "insert_doc"]

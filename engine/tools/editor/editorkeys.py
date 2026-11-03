"""Studio's keys (F44 ``03`` §4, ``04`` §7.6 "Keys"; F45 UI-F45-02), as the ``EditorKeys``
mixin of ``window.EditorWindow``.

``key_table`` lists ``(sequences, action, scope)`` rows: ``EDITOR`` binds on the editor
texts' own bindtag (``VnEditorText``: every file's text and the side editor's peer), ``MAIN``
binds everywhere but acts only in Studio's own window (not in a dialog). The Ctrl+digit rows
come from ``window.TABS``. Also here: Tab order outside the editor, F6 focus cycling, and the
undo, redo, select-all and clipboard handlers.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from engine.tools.editor.builddialog import open_build_dialog
from engine.tools.editor.studiolook import FONT_STEP_PX

EDITOR = "editor"       # bound on the editor texts' bindtag
MAIN = "main"           # bound everywhere; acts only in Studio's own window

KeyRow = tuple[tuple[str, ...], Callable[[tk.Event], "str | None"], str]


class EditorKeys:
    """Key bindings from ``key_table``, focus order and cycling, and the editing keys'
    handlers."""

    # --- Keys (03 §4, §7.6 "Keys") ----------------------------------------------------------

    _editor_bindtag = "VnEditorText"

    def key_table(self) -> list[KeyRow]:
        """``(sequences, handler, scope)`` rows; a handler gets the Tk event and returns
        ``"break"`` to stop Tk's own binding. A sequence this Tk doesn't know is skipped."""
        mod = self.mod
        brk = self._break

        def both(letter: str) -> tuple[str, str]:
            return f"<{mod}-{letter}>", f"<{mod}-{letter.upper()}>"

        rows: list[KeyRow] = [
            (("<Tab>",), lambda e: self._completion_key("accept")
             or self._indent(e.widget, dedent=False), EDITOR),
            (("<Shift-Tab>", "<ISO_Left_Tab>"),
             lambda e: self._indent(e.widget, dedent=True), EDITOR),
            (("<Return>", "<KP_Enter>"),
             lambda e: self._completion_key("accept") or self._newline(e.widget), EDITOR),
            # The completion list (UI-F45-04): the editor keeps the focus, so its keys go
            # here and fall through to the Text bindings while no list is open.
            *(((key,), lambda _e, a=action: self._completion_key(a), EDITOR)
              for key, action in (("<Up>", "up"), ("<Down>", "down"), ("<Prior>", "prior"),
                                  ("<Next>", "next"))),
            ((f"<{mod}-space>",), lambda _e: brk(self.complete), EDITOR),
            (("<KeyPress>",), self._after_key, EDITOR),
            (("<FocusOut>",), self._on_editor_focus_out, EDITOR),
            (both("z"), lambda e: self._undo_or_redo(e), EDITOR),
            (both("y"), lambda e: self._redo(e.widget), EDITOR),
            (both("a"), lambda e: self._select_all(e.widget), EDITOR),
            *((both(letter), lambda e, ev=event: self._clipboard(e.widget, ev), EDITOR)
              for letter, event in (("x", "<<Cut>>"), ("c", "<<Copy>>"), ("v", "<<Paste>>"))),

            (both("s"), lambda _e: brk(self.save_current), MAIN),
            ((f"<{mod}-Shift-S>",), lambda _e: brk(self.save_all), MAIN),
            (both("n"), lambda _e: brk(self.new_script_file), MAIN),
            ((f"<{mod}-Shift-O>",), lambda _e: brk(self.add_files), MAIN),
            # F42: File ▸ Build game… (it does nothing while a build runs).
            ((f"<{mod}-Shift-B>",), lambda _e: brk(open_build_dialog, self), MAIN),
            (both("g"), lambda _e: brk(self.go_to_label), MAIN),
            (("<F7>",), lambda _e: brk(self.check_now), MAIN),
            # Ctrl+1, Ctrl+2, …: one per tab, in ``tabs`` order.
            *(((f"<{mod}-Key-{index + 1}>",), lambda _e, i=index: brk(self.show_tab, i), MAIN)
              for index in range(len(self.tabs))),
            ((f"<{mod}-equal>", f"<{mod}-plus>", f"<{mod}-KP_Add>"),
             lambda _e: brk(self.zoom_view, FONT_STEP_PX), MAIN),
            ((f"<{mod}-minus>", f"<{mod}-KP_Subtract>"),
             lambda _e: brk(self.zoom_view, -FONT_STEP_PX), MAIN),
            ((f"<{mod}-0>", f"<{mod}-KP_0>"), lambda _e: brk(self.zoom_view, 0), MAIN),
            # The Play bar (F47 §6.1): F5 this scene, Shift+F5 from the start, Ctrl+F2 Stop.
            (("<F5>",), lambda _e: brk(self.play_scene), MAIN),
            (("<Shift-F5>",), lambda _e: brk(self.play_from_start), MAIN),
            ((f"<{mod}-F2>",), lambda _e: brk(self.stop_game), MAIN),
            # F39: Ctrl+R updates the running game (the saved files, same place).
            (both("r"), lambda _e: brk(self.update_game), MAIN),
            (("<F6>",), lambda _e: brk(self.cycle_focus, 1), MAIN),
            (("<Shift-F6>",), lambda _e: brk(self.cycle_focus, -1), MAIN),
        ]
        return rows

    def _bind_keys(self) -> None:
        root = self.root
        for sequences, handler, scope in self.key_table():
            for sequence in sequences:
                try:
                    if scope == EDITOR:
                        root.bind_class(self._editor_bindtag, sequence, handler)
                    else:
                        root.bind_all(sequence, lambda e, h=handler: h(e)
                                      if self._in_main(e) else None)
                except tk.TclError:
                    pass                    # a keysym this Tk doesn't know

        # Tab order outside the editor (03 §4; F47): project → editor → ▶ Play → problems
        # → project. Tab in the editor indents instead; the Play bar's other buttons are
        # reached with Left and Right from ▶ Play.
        order: list[Callable[[], tk.Widget]] = [
            lambda: self.tree, lambda: self.text, lambda: self.play_button,
            lambda: self.problems]
        for index, get in enumerate(order):
            if index == 1:
                continue
            widget = get()
            forward, back = order[(index + 1) % len(order)], order[index - 1]
            widget.bind("<Tab>", lambda _e, f=forward: self._move_focus(f()))
            for key in ("<Shift-Tab>", "<ISO_Left_Tab>"):
                try:
                    widget.bind(key, lambda _e, b=back: self._move_focus(b()))
                except tk.TclError:
                    pass
        self._guard_stop_key(self.root)
        for widget in self.play_bar.buttons[1:]:        # the rest of the bar Tabs as ▶ Play
            widget.bind("<Tab>", lambda _e: self._move_focus(self.problems))
            for key in ("<Shift-Tab>", "<ISO_Left_Tab>"):
                try:
                    widget.bind(key, lambda _e: self._move_focus(self.text))
                except tk.TclError:
                    pass
        # The Help pane is reached by F6; Tab from it goes on to the project panel.
        self.help_text.bind("<Tab>", lambda _e: self._move_focus(self.tree))
        for key in ("<Shift-Tab>", "<ISO_Left_Tab>"):
            try:
                self.help_text.bind(key, lambda _e: self._move_focus(self.problems))
            except tk.TclError:
                pass

    def _guard_stop_key(self, widget: tk.Misc) -> None:
        """Ctrl+F2 is Stop everywhere: a widget's own F2 binding (Rename on the map, the
        project tree, the Events list) would also take Ctrl+F2, so each such widget gets
        a Ctrl+F2 binding of its own that stops the game instead."""
        try:
            if "<Key-F2>" in widget.bind():
                widget.bind(f"<{self.mod}-F2>", lambda _e: self._break(self.stop_game))
            children = widget.winfo_children()
        except tk.TclError:
            return
        for child in children:
            self._guard_stop_key(child)

    def _in_main(self, event: tk.Event) -> bool:
        """Global keys act only in the editor's own window, not in a dialog."""
        widget = event.widget
        try:
            return not self.closed and isinstance(widget, tk.Misc) and \
                widget.winfo_toplevel() is self.root
        except (KeyError, tk.TclError):
            return False

    @staticmethod
    def _break(action: Callable[..., object], *args: object) -> str:
        action(*args)
        return "break"

    @staticmethod
    def _move_focus(widget: tk.Widget) -> str:
        widget.focus_set()
        return "break"

    def cycle_focus(self, step: int) -> None:
        """F6 / Shift+F6: Project → Editor area → Play bar → Problems → Help → Project
        (UI-F45-02, amended AC-F44-32 and by F47; the editor area is the current tab's
        widget, then the Story map's side pane's shown page while it is open)."""
        areas: list[tk.Widget] = [self.tree, self._tab_widget()]
        side = self._side_active()
        page = self._side_page_widget()
        if side is not None and page is not None:
            areas.append(page)              # F46: the side pane's shown page
        areas += [self.play_button, self.problems, self.help_text]
        try:
            focus = self.root.focus_get()
        except (KeyError, tk.TclError):
            focus = None
        if focus in self.play_bar.buttons:
            target = self.problems if step > 0 else areas[areas.index(self.play_button) - 1]
        else:
            pages = [self._attr(tab.focus) for tab in self.tabs if tab.name != "editor"]
            if focus in self._editor_widgets() or focus in pages \
                    or focus in self._empty_buttons():
                position = 1
            elif focus in areas:
                position = areas.index(focus)
            else:
                position = 0 if step > 0 else 2     # unknown focus: land in the editor
            target = areas[(position + step) % len(areas)]
        target.focus_set()

    def _empty_buttons(self) -> list[tk.Widget]:
        """The shown empty states' buttons (08 §9): each is its area's focus stop."""
        found = [self._attr(tab.empty).focus_widget() for tab in self.tabs]
        return [widget for widget in found if widget is not None]

    def _tab_widget(self) -> tk.Widget:
        """The widget F6 lands on in the notebook: the current tab's (an empty state's
        button while one shows)."""
        tab = self.tabs[self.notebook.index("current")]
        empty = self._attr(tab.empty).focus_widget()
        if empty is not None:
            return empty
        return self._attr(tab.focus)

    def _undo_or_redo(self, event: tk.Event) -> str:
        """Ctrl+Z is undo, also with Caps Lock (keysym ``Z``); with Shift it is redo."""
        if int(event.state) & 0x1:
            return self._redo(event.widget)
        return self._undo(event.widget)

    def _undo(self, widget: tk.Text) -> str:
        try:
            widget.edit_undo()
        except tk.TclError:
            pass                            # nothing to undo
        return "break"

    def _redo(self, widget: tk.Text) -> str:
        try:
            widget.edit_redo()
        except tk.TclError:
            pass
        return "break"

    @staticmethod
    def _select_all(widget: tk.Text) -> str:
        widget.tag_remove("sel", "1.0", "end")
        widget.tag_add("sel", "1.0", "end-1c")
        return "break"

    @staticmethod
    def _clipboard(widget: tk.Text, virtual: str) -> str:
        widget.event_generate(virtual)
        return "break"

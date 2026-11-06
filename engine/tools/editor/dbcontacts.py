"""The Database's **Contacts** category (F65 round 3, proposal I-09 "Studio contacts and
devices"; plan: specs/skins-contract.md, "Phases 2-4"; docs/database.md "Contacts").

Why this module exists: a pen pal should take a minute to set up without code. In
Database ▸ **Contacts**, **+ New** asks the name players see and writes one ``lock contact``
line into ``database.vns``. The form changes the **Name shown**, the **Device look** (the
game's default first: "Game default (pigeon, from the Fantasy kit)"), the **Picture** (a
thumbnail picker) and the script name (a used contact is renamed everywhere: its
``send … from`` lines follow, ``declrename``). Under it, **Messages**: what the contact
sends (the ``define``\\ s its ``send … from <contact>`` lines name), each with **Write
lines…**, which opens the phone-chat step editor (``minigameview``'s ``ChatEditor``), and
the scenes and lines that send it (each a link). **+ New message** makes a define and
opens the editor. Beside the fields, a live preview draws the contact's newest message in
its device look in the game's colours (a letter signed with the name, or chat bubbles).
Delete is refused while a send line uses the contact, and says where.

``ContactsCategory`` is a mixin of ``database.DatabasePane`` (as ``dbachievements``'s): the
model is ``contactmodel``'s; every write is a ``declplan`` plan through the pane's
``_write``, or a ``minigamedata`` plan through ``MessageStore``, one undo step each.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable, Mapping
from tkinter import ttk
from typing import Any

from engine.core.kits import device_words
from engine.script.inbox import TITLE_MAX
from engine.script.messages import show
from engine.tools.editor import contactmodel as cm
from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan, settingsmodel
from engine.tools.editor import minigamedata as mg
from engine.tools.editor import minigameview as mv
from engine.tools.editor.dbmore import IN_SCRIPT, Row
from engine.tools.editor.dialogs import ask, ask_text, show_error
from engine.tools.editor.fieldwidgets import AssetPicker, ChoiceField, FormGrid, TextField
from engine.tools.editor.schemecards import fit_text
from engine.tools.editor.scriptedit import STALE
from engine.tools.editor.theme import THEME

# --- Texts --------------------------------------------------------------------------------------

CATEGORY = db.CATEGORY_CONTACT
ABOUT_CONTACTS = ("Contacts are the people who write to the player: a pen pal's letters, a "
                  "friend's texts, a voice on the radio. Their messages arrive in the Inbox "
                  "while the story goes on. Click + New to add one.")
NEW_ASK = "Name players see (who the messages are from):"
NEW_OK = "Add"
LABEL_TITLE = "Name shown"
LABEL_LOOK = "Device look"
LABEL_PICTURE = "Picture"
NO_PICTURE = "No picture"
PICTURE_HINT = "Shown beside the arrival notice and in the Inbox."
MESSAGES = "Messages"
NEW_MESSAGE = "+ New message"
NEW_MESSAGE_ASK = "Name of the new message from {title}:"
NEW_MESSAGE_FIRST = {True: "letter {n}", False: "message {n}"}
NO_MESSAGES = ("No messages yet. + New message writes one; then send it from a scene with "
               "Insert ▸ Messages ▸ Send.")
WRITE_LINES = "Write lines…"
SENT_IN = "Sent in"
NOT_SENT = "Not sent yet. Add it to a scene with Insert ▸ Messages ▸ Send, or copy the line:"
COPY = "Copy"
COPIED = "Copied"
NO_DEFINE = "{name} isn't written yet: no define holds it."
NOT_PLAIN = "Written in a way the editor can't show."
EDIT_AS_SCRIPT = db.EDIT_AS_SCRIPT
DIALOG_TITLE = "Message from {title}: {name}"
DIALOG_HINT = ("Lines from {title}, the player's own (Me), and time dividers, in the order "
               "the Inbox shows them.")
SENDS_LINE = "Sends from {lines}"
NOT_SENDING = "Not sending anything yet"
SHOW_USES = db.SHOW_USES
USES_HEAD = "{name} sends messages from {lines}:"
DELETE_ASK = ("Delete {name}? Its line is removed from {ref}; Edit ▸ Undo there brings it "
              "back. Its messages stay.")
DELETE_BUTTONS = ("Delete", "Cancel")
REFUSED_BUTTONS = (SHOW_USES, "OK")
SEND_HINT = "In the script: send <message> from {name}"

# Sizes (px at 100 %).
PREVIEW_W = 240
PREVIEW_H = 168
PAD = 10


def _lines(n: int) -> str:
    return f"{n} line" if n == 1 else f"{n} lines"


class MessageStore(mv.Store):
    """``minigameview.Store`` that also finds a message define the Minigame data list
    doesn't list (only lines of text, or one text): ``contactmodel.message_set``."""

    def find(self, kind: str, name: str) -> mg.DataSet | None:
        found = super().find(kind, name)
        if found is None and kind == mg.CHAT:
            found = cm.message_set(self.texts, name)
        return found


class MessageDialog:
    """A message's lines in the phone-chat step editor, in a modal window."""

    def __init__(self, win: Any, parent: tk.Misc, ds: mg.DataSet, title: str) -> None:
        from engine.tools.editor import dialogs
        self.parent = parent
        self.dialog = dialog = dialogs._dialog(parent)
        dialog.resizable(True, True)
        dialog.title(DIALOG_TITLE.format(title=title, name=ds.name))
        body, _scale = dialogs._body(dialog)
        self.store = MessageStore(win)
        self.store.read()
        self.host = mv.EditorHost(win, dialog, self.store)
        ttk.Label(body, text=DIALOG_HINT.format(title=title), style="Hint.TLabel",
                  wraplength=self.host.px(440), justify="left").pack(
            anchor="w", pady=(0, self.host.px(8)))
        self.editor = mv.editor_for(self.host, body, ds)
        if self.editor is None:
            mv.complex_box(body, win, ds, self.host.px).pack(anchor="w")
        else:
            self.editor.frame.pack(fill="both", expand=True)
        self.buttons = dialogs._buttons(dialog, body, (mv.CLOSE,), lambda _i: self.close())
        dialog.bind("<Escape>", lambda _e: self.close())
        dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.on_close: Callable[[], object] | None = None

    def close(self) -> None:
        if self.editor is not None:
            focused = self.dialog.focus_get()
            if focused is not None:                 # commit a field still being typed in
                focused.event_generate("<FocusOut>")
        self.dialog.destroy()
        if self.on_close is not None:
            self.on_close()

    def run(self) -> None:
        from engine.tools.editor import dialogs
        dialogs._run(self.parent, self.dialog, self.buttons[0])


class ContactPainter:
    """Draws a contact's newest message on ``canvas`` (``contactmodel.ContactPreview``):
    a sheet of paper signed with the name for a letter look, else a device with bubbles.
    Tags: every item ``"contact_preview"`` and ``"look:<look>"``; ``"letter"`` or
    ``"chat"``; each line ``"line:<side>"``; the signature ``"signature"``."""

    def __init__(self, canvas: tk.Canvas, px: Callable[[float], int], font: tkfont.Font,
                 bold: tkfont.Font) -> None:
        self.canvas, self.px, self.font, self.bold = canvas, px, font, bold

    def draw(self, seen: cm.ContactPreview, width: int, height: int) -> None:
        canvas, px = self.canvas, self.px
        canvas.delete("all")
        fill, text, border, accent, soft, track = seen.colors
        base = ("contact_preview", f"look:{seen.look}", "letter" if seen.letter else "chat")
        canvas.create_rectangle(0, 0, width - 1, height - 1, fill=soft,
                                outline=THEME["border"], tags=base)
        inner = (px(PAD), px(PAD), width - px(PAD), height - px(PAD))
        if seen.letter:
            self._letter(seen, base, inner, (fill, text, border, accent, track))
        else:
            self._chat(seen, base, inner, (fill, text, border, accent, track))

    def _text(self, x: int, y: int, words: str, *, width: int, color: str, tags: tuple,
              font: tkfont.Font | None = None, anchor: str = "nw", justify: str = "left"
              ) -> int:
        """Wrapped text at ``(x, y)``; returns its bottom."""
        item = self.canvas.create_text(x, y, anchor=anchor, text=words, width=max(10, width),
                                       fill=color, font=font or self.font, justify=justify,
                                       tags=tags)
        box = self.canvas.bbox(item)
        return box[3] if box else y

    def _letter(self, seen: cm.ContactPreview, base: tuple, inner: tuple[int, int, int, int],
                colors: tuple[str, str, str, str, str]) -> None:
        fill, text, border, accent, track = colors
        px = self.px
        x0, y0, x1, y1 = inner
        self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline=border, tags=base)
        via = fit_text(seen.via, x1 - x0 - px(16), self.font.measure)
        self.canvas.create_text(x0 + px(8), y0 + px(6), anchor="nw", text=via, fill=accent,
                                font=self.font, tags=(*base, "via"))
        y = y0 + px(8) + self.font.metrics("linespace") + px(4)
        bottom = y1 - px(6) - self.font.metrics("linespace")
        if not seen.lines:
            self._text(x0 + px(8), y, cm.NO_MESSAGES, width=x1 - x0 - px(16), color=track,
                       tags=(*base, "empty"))
            return
        for side, name, words in seen.lines:
            if y >= bottom:
                break
            shown = f"[ {words} ]" if side == "ask" else f"Me: {words}" if side == "me" \
                else f"{name}: {words}" if side == "them" and name and name != seen.title \
                else words
            color = track if side == "time" else accent if side == "ask" else text
            y = self._text(x0 + px(8), y, shown, width=x1 - x0 - px(16), color=color,
                           tags=(*base, f"line:{side}")) + px(4)
        self.canvas.create_text(x1 - px(8), y1 - px(6), anchor="se",
                                text=cm.SIGNED.format(name=seen.title), fill=text,
                                font=self.bold, tags=(*base, "signature"))
        self._clip(bottom)

    def _clip(self, bottom: int) -> None:
        """Hide the lines that run past ``bottom`` (the signature stays readable)."""
        for item in self.canvas.find_withtag("contact_preview"):
            box = self.canvas.bbox(item)
            if box and box[3] > bottom and any(t.startswith("line:")
                                               for t in self.canvas.gettags(item)):
                self.canvas.itemconfigure(item, state="hidden")

    def _chat(self, seen: cm.ContactPreview, base: tuple, inner: tuple[int, int, int, int],
              colors: tuple[str, str, str, str, str]) -> None:
        fill, text, border, accent, track = colors
        px = self.px
        x0, y0, x1, y1 = inner
        self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline=border, width=1,
                                     tags=base)
        bar = y0 + self.bold.metrics("linespace") + px(8)
        self.canvas.create_rectangle(x0, y0, x1, bar, fill=accent, outline="", tags=base)
        head = fit_text(f"{seen.title}  ·  {seen.via}", x1 - x0 - px(16), self.bold.measure)
        self.canvas.create_text(x0 + px(8), y0 + px(4), anchor="nw", text=head, fill=fill,
                                font=self.bold, tags=(*base, "via"))
        y = bar + px(6)
        room = x1 - x0 - px(16)
        if not seen.lines:
            self._text(x0 + px(8), y, cm.NO_MESSAGES, width=room, color=track,
                       tags=(*base, "empty"))
            return
        for side, name, words in seen.lines:
            if y >= y1 - px(10):
                break
            tags = (*base, f"line:{side}")
            if side == "time":
                y = self._text((x0 + x1) // 2, y, words, width=room, color=track, tags=tags,
                               anchor="n", justify="center") + px(4)
                continue
            mine = side in ("me", "ask")
            words = f"[ {words} ]" if side == "ask" else words
            if side == "them" and name and name != seen.title:
                words = f"{name}: {words}"
            limit = round(room * 0.78)
            x = x1 - px(8) if mine else x0 + px(8)
            item = self.canvas.create_text(x - px(6) if mine else x + px(6), y + px(3),
                                           anchor="ne" if mine else "nw", text=words,
                                           width=limit, fill=fill if mine else text,
                                           font=self.font, tags=tags)
            box = self.canvas.bbox(item) or (x, y, x, y)
            bubble = self.canvas.create_rectangle(box[0] - px(6), y, box[2] + px(6),
                                                  box[3] + px(3),
                                                  fill=accent if mine else fill,
                                                  outline="" if mine else border, tags=tags)
            self.canvas.tag_lower(bubble, item)
            y = box[3] + px(8)
        self._clip(y1)


class ContactsCategory:
    """Database ▸ Contacts (a mixin of ``database.DatabasePane``)."""

    win: Any
    root: Any
    scale: float
    texts: dict[str, str]
    decls: tuple[dec.Decl, ...]
    rows: dict[str, list[Row]]
    form: Any
    fonts: Any
    thumbs: Any
    category: str
    chosen: dict[str, str | None]
    _px: Callable[[float], int]
    _new_body: Callable[[tuple], tuple[ttk.Frame, Any]]
    _title: Callable[..., ttk.Label]
    _bottom: Callable[..., None]
    _name_row: Callable[..., None]
    _read_only: Callable[..., bool]
    _edit: Callable[..., bool]
    _write: Callable[..., bool]
    _fresh: Callable[[db.Entry], dec.Decl | None]
    _taken: Callable[[str], frozenset[str]]
    _image_names: Callable[[], dict[str, str]]
    _read_texts: Callable[[], dict[str, str]]
    config_text: Callable[[], str | None]
    refresh: Callable[..., None]
    select_category: Callable[[str], None]
    sends: tuple[cm.SendLine, ...] = ()
    last_message_dialog: MessageDialog | None = None

    # --- Rows -------------------------------------------------------------------------------

    def _contact_rows(self) -> list[Row]:
        self.sends = cm.send_lines(self.texts)
        return [Row(f"ct:{e.name}", e.shown, self._contact_short(e), e)
                for e in cm.contact_entries(self.decls, self.texts, self.sends)]

    def _contact_short(self, entry: db.Entry) -> str:
        values = entry.decl.values if entry.decl is not None else None
        if values is None:
            return ""
        look = values.get("device")
        return cm.LOOK_NAMES.get(str(look), "").split(" (")[0] if look else ""

    def _contact_messages(self, entry: db.Entry) -> list[cm.Message]:
        return cm.messages_of(entry.name, self.texts, self.sends)

    def _contact_key(self, entry: db.Entry, shape: tuple) -> tuple:
        """The form is rebuilt when the messages or their send lines change."""
        return shape + tuple((m.name, m.ref, m.first, tuple((s.ref, s.line) for s in m.sends))
                             for m in self._contact_messages(entry))

    def _found(self) -> Mapping[str, object]:
        return settingsmodel.values(self.config_text() or "") or {}

    # --- The form ---------------------------------------------------------------------------

    def _contact_form(self, row: Row, key: tuple) -> None:
        if self._read_only(row, key):
            return
        entry = row.entry
        assert entry is not None and entry.decl is not None and entry.decl.values is not None
        body, form = self._new_body(key)
        title = self._title(body, entry.shown)
        values = dict(entry.decl.values)
        f = form.fields
        state: dict[str, Any] = {"entry": entry}
        top = ttk.Frame(body)
        top.grid(row=1, column=0, sticky="ew")
        grid = FormGrid(top, scale=self.scale)
        grid.frame.grid(row=0, column=0, sticky="nw")
        f["title"] = TextField(grid.frame, str(values["title"]), width=22,
                               check=lambda t: bool(" ".join(t.split())),
                               on_change=lambda v: self._contact_title(state["entry"], str(v)))
        grid.row(LABEL_TITLE, f["title"])
        found = self._found()
        f["look"] = ChoiceField(grid.frame, cm.look_choices(found), values.get("device"),
                                width=30, on_change=lambda v: self._edit(
                                    state["entry"], {"device": v}))
        look_row = grid.row(LABEL_LOOK, f["look"], hint=cm.arrives_text(
            cm.look_of(found, values), str(values["title"])))
        images = self._image_names()

        def thumb(name: str) -> object:
            ref = images.get(name)
            self._preview_ref = ref
            return self.thumbs.get(ref) if ref else None

        f["image"] = AssetPicker(grid.frame, sorted(images, key=str.casefold),
                                 values.get("image"), width=22, none_text=NO_PICTURE,
                                 thumb=thumb, scale=self.scale,
                                 on_change=lambda v: self._edit(state["entry"], {"image": v}))
        grid.row(LABEL_PICTURE, f["image"], hint=PICTURE_HINT)
        self._name_row(grid, form, entry)
        uses = ttk.Frame(grid.frame)
        grid.widget(uses, pady=(6, 0))
        self._sends_line(uses, entry)

        # The preview, beside the fields (under them when the form is narrow).
        side = ttk.Frame(top)
        side.grid(row=0, column=1, sticky="nw", padx=(self._px(20), 0), pady=(self._px(3), 0))
        canvas = tk.Canvas(side, width=self._px(PREVIEW_W), height=self._px(PREVIEW_H),
                           highlightthickness=0, background=THEME["editor.background"])
        canvas.pack()
        caption = ttk.Label(side, style="Hint.TLabel", wraplength=self._px(PREVIEW_W),
                            justify="left")
        caption.pack(anchor="w", pady=(self._px(4), 0))
        family = self.fonts["small"].actual("family") if "small" in self.fonts else "TkDefaultFont"
        size = -max(9, round(11 * self.scale))
        painter = ContactPainter(canvas, self._px,
                                 tkfont.Font(root=canvas, family=family, size=size),
                                 tkfont.Font(root=canvas, family=family, size=size,
                                             weight="bold"))
        f["preview"], f["preview_caption"] = canvas, caption

        def reflow(_event: object = None) -> None:
            room = top.winfo_width()
            need = grid.frame.winfo_reqwidth() + side.winfo_reqwidth() + self._px(20)
            beside = room <= 1 or room >= need
            where = side.grid_info()
            if beside and int(where.get("row", 0)) != 0:
                side.grid(row=0, column=1, padx=(self._px(20), 0), pady=(self._px(3), 0))
            elif not beside and int(where.get("row", 0)) != 1:
                side.grid(row=1, column=0, padx=(0, 0), pady=(self._px(12), 0))

        top.bind("<Configure>", reflow, add="+")

        # Messages.
        box = ttk.Frame(body)
        box.grid(row=2, column=0, sticky="ew", pady=(self._px(18), 0))
        self._messages_box(box, entry, values)
        self._bottom(body, 3, entry, lambda: self.delete_contact(state["entry"]))

        def show_preview(now: db.Entry) -> None:
            vals = now.decl.values if now.decl is not None and now.decl.values else {}
            shown = str(vals.get("title") or now.shown)
            seen = cm.preview(self._found(), shown, vals, self._contact_messages(now),
                              self.sends)
            painter.draw(seen, self._px(PREVIEW_W), self._px(PREVIEW_H))
            caption.configure(text=seen.caption)

        def update(new: Row) -> None:
            now = new.entry
            assert now is not None and now.decl is not None and now.decl.values
            state["entry"] = now
            vals = now.decl.values
            title.configure(text=now.shown)
            f["title"].set(str(vals["title"]))
            found = self._found()
            f["look"].set_choices(cm.look_choices(found))
            f["look"].set(vals.get("device"))
            assert look_row.hint is not None
            look_row.hint.configure(text=cm.arrives_text(cm.look_of(found, vals),
                                                         str(vals["title"])))
            f["image"].set(vals.get("image"))
            if "name" in f:
                f["name"].set(now.name)
            show_preview(now)

        show_preview(entry)
        form.update = update

    def _sends_line(self, parent: ttk.Frame, entry: db.Entry) -> None:
        places = [s for s in self.sends if s.contact == entry.name]
        ttk.Label(parent, text=SENDS_LINE.format(lines=_lines(len(places))) if places
                  else NOT_SENDING).pack(side="left")
        if places:
            ttk.Button(parent, text=SHOW_USES, style="Link.Ghost.TButton", cursor="hand2",
                       command=lambda: self.show_contact_uses(entry)).pack(
                side="left", padx=(self._px(8), 0))

    def _messages_box(self, box: ttk.Frame, entry: db.Entry,
                      values: Mapping[str, object]) -> None:
        px = self._px
        box.columnconfigure(0, weight=1)
        head = ttk.Frame(box)
        head.grid(row=0, column=0, sticky="ew", pady=(0, px(6)))
        ttk.Label(head, text=MESSAGES.upper(), style="Caption.TLabel").pack(side="left")
        ttk.Button(head, text=NEW_MESSAGE, style="Secondary.TButton",
                   command=lambda: self.new_message(entry)).pack(side="right")
        messages = self._contact_messages(entry)
        if not messages:
            ttk.Label(box, text=NO_MESSAGES, style="Hint.TLabel", justify="left",
                      wraplength=px(420)).grid(row=1, column=0, sticky="w")
            return
        strong = self.fonts.get("bodyStrong") if hasattr(self.fonts, "get") else None
        code = self.fonts.get("codeSmall") if hasattr(self.fonts, "get") else None
        for at, message in enumerate(messages, start=1):
            ttk.Separator(box).grid(row=2 * at - 1, column=0, sticky="ew", pady=(px(4), 0))
            card = ttk.Frame(box, padding=(0, px(8)))
            card.grid(row=2 * at, column=0, sticky="ew")
            card.columnconfigure(0, weight=1)
            ttk.Label(card, text=message.name, font=strong).grid(row=0, column=0, sticky="w")
            ttk.Button(card, text=WRITE_LINES, style="Secondary.TButton",
                       command=lambda m=message.name: self.open_message(entry, m)).grid(
                row=0, column=1, sticky="e")
            first = cm.first_text(message.value) if message.value is not None else ""
            note = first if first else NO_DEFINE.format(name=message.name) \
                if message.ref is None else NOT_PLAIN if message.value is None else ""
            if note:
                ttk.Label(card, text=fit_text(note, px(420), tkfont.nametofont(
                    "TkDefaultFont").measure), style="Hint.TLabel", wraplength=px(440)).grid(
                    row=1, column=0, columnspan=2, sticky="w", pady=(px(2), 0))
            where = ttk.Frame(card)
            where.grid(row=2, column=0, columnspan=2, sticky="w", pady=(px(4), 0))
            if message.sends:
                ttk.Label(where, text=SENT_IN + ":").pack(side="left")
                for send in message.sends:
                    ttk.Button(where, text=cm.where_text(send), style="Link.Ghost.TButton",
                               cursor="hand2",
                               command=lambda s=send: self.win.jump_to(s.ref, s.line)).pack(
                        side="left")
            else:
                line = cm.send_text(message.name, entry.name)
                ttk.Label(where, text=NOT_SENT, style="Hint.TLabel", wraplength=px(420),
                          justify="left").pack(anchor="w")
                copy = ttk.Frame(where)
                copy.pack(anchor="w", pady=(px(4), 0))
                ttk.Label(copy, text=line, font=code).pack(side="left")
                done = ttk.Label(copy, text="", style="Hint.TLabel")
                ttk.Button(copy, text=COPY, style="Link.Ghost.TButton", cursor="hand2",
                           command=lambda t=line, d=done: self.copy_line(t, d)).pack(
                    side="left", padx=(px(8), 0))
                done.pack(side="left", padx=(px(4), 0))

    # --- Writes -----------------------------------------------------------------------------

    def _contact_title(self, entry: db.Entry, text: str) -> bool:
        return self._edit(entry, {"title": " ".join(text.split())[:TITLE_MAX]})

    def new_contact(self) -> bool:
        """+ New: the name players see, then one ``lock contact`` line in database.vns."""
        self.texts = self._read_texts()
        taken = self._taken(dec.CONTACT)
        answer = ask_text(self.root, NEW_ASK, "", ok=NEW_OK,
                          hint=lambda shown: IN_SCRIPT.format(
                              line=f"lock contact {dec.script_name(shown, taken, dec.CONTACT)}")
                          if shown.strip() else None)
        if answer is None or not " ".join(answer[0].split()):
            return False
        shown = " ".join(answer[0].split())[:TITLE_MAX]
        name = dec.script_name(shown, taken, dec.CONTACT)
        self.select_category(CATEGORY)
        return self._write(declplan.plan_new(dec.CONTACT, name, {
            "title": shown, "device": None, "image": None}, self.texts), select=f"ct:{name}")

    def copy_line(self, text: str, done: ttk.Label | None = None) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        if done is not None:
            done.configure(text=COPIED)

    def new_message(self, entry: db.Entry) -> str | None:
        """+ New message: a name, then a define with one line in database.vns, opened in
        the phone-chat step editor. Returns its name."""
        store = MessageStore(self.win)
        store.read()
        values = entry.decl.values if entry.decl is not None and entry.decl.values else {}
        title = str(values.get("title") or entry.shown)
        letter = device_words(cm.look_of(self._found(), values)).letter
        taken = set(dec.taken_names(dec.scan(store.texts), dec.DEFINE)) | {
            s.name for s in store.sets}
        count = len(self._contact_messages(entry)) + 1
        answer = ask_text(self.root, NEW_MESSAGE_ASK.format(title=title),
                          NEW_MESSAGE_FIRST[letter].format(n=count), ok=NEW_OK,
                          hint=lambda shown: IN_SCRIPT.format(
                              line=f"define {cm.message_name(entry.name, shown, taken)}")
                          if shown.strip() else None)
        if answer is None or not answer[0].strip():
            return None
        name = cm.message_name(entry.name, answer[0].strip(), taken)
        if not store.create(mg.CHAT, name, cm.new_steps(letter)):
            return None
        self.refresh(select=f"ct:{entry.name}")
        self.open_message(entry, name)
        return name

    def open_message(self, entry: db.Entry, name: str) -> MessageDialog | None:
        """**Write lines…**: the message in the phone-chat step editor; the Database is read
        again when it closes."""
        texts = self._read_texts()
        ds = cm.message_set(texts, name)
        if ds is None:
            show_error(self.root, NO_DEFINE.format(name=name))
            return None
        values = entry.decl.values if entry.decl is not None and entry.decl.values else {}
        dialog = MessageDialog(self.win, self.root, ds, str(values.get("title") or entry.shown))
        dialog.on_close = lambda: self.refresh(select=f"ct:{entry.name}")
        self.last_message_dialog = dialog
        dialog.run()
        return dialog

    # --- Uses and delete --------------------------------------------------------------------

    def show_contact_uses(self, entry: db.Entry) -> None:
        """Show uses: the send lines from the contact, in the Problems panel."""
        from engine.tools.editor.database import UseItem
        from engine.tools.editor.preview import Report
        places = [s for s in self.sends if s.contact == entry.name]
        items = []
        for send in places:
            lines = self.texts.get(send.ref, "").split("\n")
            text = lines[send.line - 1].strip() if 0 < send.line <= len(lines) else ""
            items.append(UseItem(f"{send.ref}:{send.line}: {text}", send.ref, send.line))
        head = USES_HEAD.format(name=entry.shown, lines=_lines(len(places)))
        self.win.show_report(Report("editor", head, tuple(items)))  # type: ignore[arg-type]

    def delete_contact(self, entry: db.Entry) -> bool:
        """Delete, refused while a send line uses the contact (saying where)."""
        self.texts = self._read_texts()
        self.sends = cm.send_lines(self.texts)
        places = [s for s in self.sends if s.contact == entry.name]
        refusal = cm.refusal(entry.shown, places)
        if refusal is not None:
            if ask(self.root, refusal, REFUSED_BUTTONS, escape=1, default=1) == 0:
                self.show_contact_uses(entry)
            return False
        decl = self._fresh(entry)
        if decl is None:
            show_error(self.root, STALE)
            self.refresh()
            return False
        if ask(self.root, DELETE_ASK.format(name=entry.shown, ref=show(decl.ref)),
               DELETE_BUTTONS, escape=1, default=1) != 0:
            return False
        self.chosen[CATEGORY] = None
        return self._write(declplan.plan_delete(decl, self.texts))


__all__ = ["ABOUT_CONTACTS", "CATEGORY", "ContactPainter", "ContactsCategory",
           "MessageDialog", "MessageStore"]

"""The Inbox's message texts (F65 round 2, "Contacts and send" and "Open on cue"; round 3,
"Replies as choices" and "Delays"): load E448–E450 (``script/inbox.py``, parse), E451, E452,
E455, W311–W314 (``inbox.check_story``), run E453 and E454 (``runtime/send.py``). F65's
block is E448–E459 / W311–W316; the trigger core takes from the top down (E459–E457,
W316–W315), this work from the bottom up. ``script/inbox.py`` adds these to
``messages.TEMPLATES`` when it is imported, so ``messages.py`` needs no edit. Every template
formats with no arguments (the message tests call each with its defaults).
"""

from collections.abc import Callable, Sequence

from engine.script.messages import _did_you_mean, show, show_name

LOOKS = ("phone", "letter", "pigeon", "radio", "terminal", "mind")
_SEND = "send invite from hana"
_OPEN = "open inbox or open pigeon"
_CONTACT = 'lock contact hana "Hana"'


def _quoted(text: str) -> str:
    return f'"{show(text)}"'


def _found(found: str) -> str:
    return f"found {_quoted(found)}" if found else "found nothing"


def _looks(looks: Sequence[str] = LOOKS) -> str:
    return ", ".join(looks[:-1]) + " and " + looks[-1]


def _look(found: str, suggestion: str | None) -> str:
    text = f"there is no device look called {_quoted(found)}."
    if suggestion is not None:
        text += " " + _did_you_mean(suggestion, found)
    return text + f" The looks are {_looks()}."


def _e448(form: str = "word", found: str = "", suggestion: str | None = None) -> str:
    """``send``'s shape: ``word`` (ADR-0010 rule 4, no character send), ``speaker`` (the game
    has a character send), ``from`` (no ``from`` after the message), ``contact`` (nothing
    after ``from``), ``quoted`` (a contact in quotes), ``device`` (``on`` and a look this
    engine doesn't have), ``extra``, ``colon``; round 3: ``after`` (no number or unit after
    ``after``), ``count`` (a number out of range; ``suggestion`` the most), ``ask``
    (replies that aren't 1 to 4 short texts; ``found`` says why), ``twice`` (``on``,
    ``after`` or ``ask`` again)."""
    if form == "speaker":
        return ("send is a character here, but this line has no text in quotes. To make send "
                f'speak, write e.g. send "On my way." To deliver a message, write {_SEND}.')
    if form == "from":
        return (f"send {show_name(found)} needs from and a contact after it. Write e.g. "
                f"send {show_name(found)} from hana.")
    if form == "contact":
        return (f"send … from needs a contact's name after it, but {_found(found)}. Write "
                f"e.g. {_SEND}.")
    if form == "quoted":
        return (f"write the contact's name without quotes: send … from {show_name(found)}. "
                f"The name shown in the Inbox comes from the contact's line ({_CONTACT}).")
    if form == "device":
        return _look(found, suggestion) + " Write e.g. send invite from hana on pigeon."
    if form == "after":
        return (f"send … after needs a number and days, parts or scenes, but {_found(found)}. "
                "Write e.g. send invite from hana after 1 day, after 2 parts, or after 2 "
                "scenes.")
    if form == "count":
        return (f"send … after takes a whole number from 1 to {suggestion or 10_000}, but "
                f"found {_quoted(found)}. Write e.g. send invite from hana after 2 days.")
    if form == "ask":
        return (f"send … ask needs 1 to 4 replies in quotes, each 1 to 80 characters on one "
                f"line, all different, but {found or 'found none'}. Write e.g. send invite "
                'from hana ask "I will." "Not this year."')
    if form == "twice":
        return f"send has {show(found)} twice. Keep one."
    if form == "extra":
        return (f"send takes a message, from and a contact, then on and a look, after and a "
                f"delay, or ask and replies, but found {_quoted(found)}. Write e.g. {_SEND}.")
    if form == "colon":
        return ("send takes no colon or block after it. Put the message in a define (define "
                'invite = "See you at the bridge."), then write ' + _SEND + ".")
    text = "send delivers a message to the Inbox and needs the message's name after it"
    if found:
        text += f", but {_found(found)}"
        if suggestion is not None:
            text += ". " + _did_you_mean(suggestion, found)
    return text + f". Write e.g. {_SEND}."


def _e449(form: str = "word", found: str = "", suggestion: str | None = None) -> str:
    """``open``'s shape: ``word`` / ``speaker`` (ADR-0010 rule 4), ``target`` (not inbox or a
    device look), ``extra``, ``colon``."""
    if form == "speaker":
        return ("open is a character here, but this line has no text in quotes. To make open "
                f'speak, write e.g. open "Come in." To open the Inbox, write {_OPEN}.')
    if form == "target":
        text = f"open opens the Inbox, but {_quoted(found)} is not inbox or a device look."
        if suggestion is not None:
            text += " " + _did_you_mean(suggestion, found)
        return text + f" Write {_OPEN} (the looks are {_looks()})."
    if form == "extra":
        return f"open takes one word after it, but found {_quoted(found)}. Write {_OPEN}."
    if form == "colon":
        return f"open takes no colon or block after it. Write {_OPEN}."
    return f"open opens the Inbox and needs inbox or a device look after it. Write {_OPEN}."


def _e450(form: str = "need", found: str = "", extra: object = None,
          suggestion: str | None = None) -> str:
    """A ``lock contact`` line: ``need`` (no name and display name in quotes), ``empty`` /
    ``long`` (the display name; ``extra`` its length) / ``tags``, ``look`` (``on`` and a look
    this engine doesn't have), ``twice`` (``on`` or ``image`` again), ``left`` (something
    else after it), ``colon``, ``unlock`` (``unlock contact``), ``label`` (in a scene),
    ``dup`` (a second contact of that name; ``extra`` the first one's line), ``many``
    (``extra`` the most)."""
    if form == "empty":
        return f"contact {show_name(found)} needs a name to show, e.g. {_CONTACT}."
    if form == "long":
        return (f"contact {show_name(found)}'s shown name is {extra} characters long; the "
                "most is 40.")
    if form == "tags":
        return (f"contact {show_name(found)}'s shown name can't have text tags such as {{b}}; "
                "write it as plain text.")
    if form == "look":
        return _look(found, suggestion) + ' Write e.g. lock contact hana "Hana" on pigeon.'
    if form == "twice":
        return f"lock contact has {show(found)} twice. Keep one."
    if form == "left":
        return (f"lock contact takes a name, the name to show in quotes, on and a device look, "
                f"and image and a picture, but found {_quoted(found)}. Write e.g. "
                f'{_CONTACT} on pigeon image hana portrait.')
    if form == "colon":
        return f"lock contact takes no colon or block after it. Write e.g. {_CONTACT}."
    if form == "unlock":
        return ("contacts are declared with lock contact and never unlocked: a contact's "
                f"thread shows in the Inbox once they send something ({_SEND}).")
    if form == "label":
        return ("lock contact declares a contact, so it goes at the top level of a file, not "
                f"in a scene. Write {_CONTACT} above the labels; in a scene, write {_SEND}.")
    if form == "dup":
        return (f"there is already a contact called {show_name(found)} (line {extra}). Give "
                "each contact its own name.")
    if form == "many":
        return f"this game declares more than {extra} contacts, the most it can have."
    return (f"lock contact needs the contact's name and the name to show in quotes, e.g. "
            f"{_CONTACT}.")


def _e451(name: str = "hnaa", suggestion: str | None = "hana", any_contact: bool = True) -> str:
    text = f"there is no contact called {show_name(name)}."
    if suggestion is not None:
        text += " " + _did_you_mean(suggestion, name)
    if not any_contact:
        return text + (f" Declare it at the top level of a file: lock contact "
                       f'{show_name(name)} "{show(name.capitalize())}".')
    return text + " Use the name from its lock contact line."


def _shape(form: str, message: str, where: object, detail: str) -> str:
    """The forms E452 (load) and E453 (run time) share: what is wrong with the value."""
    head = f"message {show_name(message)}"
    if form == "kind":
        return (f"{head} must be text, or a list of lines like a phone chat's, but it is "
                f"{detail}. Write e.g. define {show_name(message)} = \"See you at the "
                'bridge.", or a list: ["Meet me at the bridge.", "Bring the red one."].')
    if form == "empty":
        return f"{head} is empty. Give it at least one line."
    if form == "steps":
        return f"{head} has {detail} lines; a message has 1 to 200."
    if form == "line":
        return f"line {where} of {head} {detail}"
    if form == "ask":
        return (f"line {where} of {head} asks for a reply, but {detail} Write e.g. "
                '{"ask": ["I will.", "Not this year."]}, or {"ask": "come", "yes": "I '
                'will.", "no": "Not this year."}.')
    if form == "ask_last":
        return (f"line {where} of {head} asks for a reply, but more lines follow it. A "
                "message asks once, at its end: move the ask to the last line.")
    if form == "ask_only":
        return (f"{head} only asks for a reply. Give it a line to answer first, e.g. "
                '["Meet me at the bridge?", {"ask": ["Yes", "No"]}].')
    if form == "step":
        return (f"line {where} of {head} must be text, or a one-key dictionary such as "
                f'{{"me": "On my way."}}, {{"time": "Day 3"}} or {{"Ren": "Hi!"}}, but it is '
                f"{detail}.")
    return f"{head} can't be sent: {detail}"


def _e452(form: str = "unknown", message: str = "invte", where: object = 1,
          detail: str = "", suggestion: str | None = "invite") -> str:
    """Load: ``unknown`` (no define or default of that name), else ``_shape``'s forms."""
    if form == "unknown":
        text = f"there is no define called {show_name(message)} to send."
        if suggestion is not None:
            text += " " + _did_you_mean(suggestion, message)
        return text + (f' Write the message as a define: define {show_name(message)} = '
                       '"See you at the bridge."')
    return _shape(form, message, where, detail)


def _e453(form: str = "missing", message: str = "invite", where: object = 1,
          detail: str = "") -> str:
    """Run time: ``missing`` (no variable of that name now), ``unsaveable``, else
    ``_shape``'s forms."""
    if form == "missing":
        return (f"there is no variable called {show_name(message)} to send. Write the message "
                f"as a define: define {show_name(message)} = \"See you at the bridge.\"")
    if form == "unsaveable":
        return (f"message {show_name(message)} holds something a save can't keep "
                f"({detail}). Use text, or a list of texts.")
    return _shape(form, message, where, detail)


def _e454(form: str = "name", found: str = "a number") -> str:
    """Run time, ``inbox`` in author Python: ``name`` (``reply`` without a message's name
    in quotes; ``found`` what it got), ``write`` (a change to ``inbox``)."""
    if form == "write":
        return ("inbox can be read, not changed: the player's replies change it. Read a reply "
                'with inbox.reply("invite").')
    return (f"inbox.reply needs a message's name in quotes, but it got {found}. Write e.g. "
            'if inbox.reply("invite") == "yes":')


def _e455(message: str = "invite", line: int = 3) -> str:
    return (f"this send line has replies (ask …), but message {show_name(message)} (line "
            f"{line}) asks for a reply too. Keep the replies in one place.")


def _w312(message: str = "invite", days: int = 1, unit: str = "day") -> str:
    """``unit`` is ``day`` or ``part`` (``after N parts``: the clock line is clock next)."""
    words = unit if days == 1 else unit + "s"
    line = "clock next day" if unit == "day" else "clock next"
    return (f"send {show_name(message)} … after {days} {words} waits for the story clock, but "
            "no clock line in this game moves it, so the message never arrives. Add a "
            f"{line} line, or send it after some scenes instead.")


def _w313(message: str = "invte", suggestion: str | None = "invite") -> str:
    text = (f'inbox.reply("{show(message)}") reads the reply to message '
            f"{show_name(message)}, but no send line sends it with replies, so it is always "
            '"".')
    if suggestion is not None:
        text += " " + _did_you_mean(suggestion, message)
    return text


def _w314(message: str = "invite", found: str = "maybe", replies: str = '"yes" or "no"'
          ) -> str:
    return (f'inbox.reply("{show(message)}") is compared with "{show(found)}", which isn\'t '
            f"one of its replies ({replies}), so that is never true. Check the spelling.")


def _w311(look: str = "pigeon") -> str:
    return (f"open {look} opens the Inbox at the newest message that came by {look}, but "
            f"nothing in this game comes by {look}: no send line or contact uses it, and it "
            f"isn't the kit's device. It opens at the newest message instead; write open "
            "inbox to say so.")


TEMPLATES: dict[str, Callable[..., str]] = {
    "E448": _e448, "E449": _e449, "E450": _e450, "E451": _e451, "E452": _e452,
    "E453": _e453, "E454": _e454, "E455": _e455, "W311": _w311, "W312": _w312,
    "W313": _w313, "W314": _w314,
}

__all__ = ["LOOKS", "TEMPLATES"]

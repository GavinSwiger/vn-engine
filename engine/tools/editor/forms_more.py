"""Studio's F47 command forms (F47 ``04-technical.md`` §3.1, §3.3; design §4.5, PR-F47-19).

Why this module exists: F46's ``forms.FORMS`` covers the first statements; F47 adds a form
for the rest, one phase at a time, so a non-programmer never has to type a statement. They
are ordinary ``forms.CommandForm``s: ``forms.all_forms()`` adds ``FORMS`` here to F46's (it
imports this module inside the function, as this one imports ``forms``), and the Events gate
(``forms.rows``) keeps a row only when the form writes back exactly what it read.

- P1: **Ending** (``ending <name> ["heading"] "title" [seconds] [with ...]``, AC-F47-23):
  the ending (picked from the check's ``ending`` names, or a new one), heading, title, how
  long the card stays, and F09's transition. Texts are shown as the player sees them: a
  ``{`` typed in the form is written ``{{`` (F18's card rule), and read back as ``{``.
- P2-A (AC-F47-28, 29, 31), each reading every shape of its doc and writing it back in the
  docs' order (another order is spacing the gate can't keep, so it stays a Script row):
  - **Transition** (the ``with`` doc): a Background, Show or Hide line with its transition,
    seconds and the fade's colour (``white``/``black``/``red`` or ``#rrggbb``). It reads
    only a coloured fade (F46's three forms hold every other ``with`` shape and can't hold a
    colour), and it is Insert's "Transition"; a line it writes with no colour reads back as
    F46's Background, Show character or Hide character row.
  - **Shake screen** (size, direction, seconds) and **Flash** (colour, seconds). An empty
    size, direction or colour is the game's ``[effects]`` default (nothing written).
  - **Glitch** (tear, colorshift, static), **Jitter character** (a sprite): size, then a
    burst of N seconds, ``on`` until stopped, or ``off``; **Stop effects** (``effect off``,
    no doc of its own: the Glitch doc mentions it).
  - **Window title** (set a title, or ``off``: the game's own) and **Fake crash** (the
    message, or none for ``[words] fake_crash_message``). The title is shown text (``{``
    doubled when written, as Ending); the crash message is written text, so its tags
    (``{username}`` from ``CRASH_PLAYER_NAME``, ``{var=…}``) stay as typed.
  - **Voice** (``voice "<file>"``, or Stop voice with an optional fade), **Play next**
    (``queue music "<file>" [fadein <s>]``, Insert's "Queue music") and **Stop sound** (every
    sound, or one file; optional fade; no doc of its own: the ``stop`` doc is Stop music's).
- P2-B (AC-F47-32, 33):
  - **Full-screen text** (``nvl``): start, new page or end (``on``, ``clear``, ``off``).
  - **Chapter** (``chapter <name> ["heading"] "title" [seconds] [with ...]``): Ending's
    fields read the same way (``_card_read``), plus a fade colour as the Transition form's.
    The name is kept as read; an empty one is made from the title (``chapter_name``, which
    the dialog can call with the game's chapter names so a new one is unique).
  - **Lock** and **Unlock** (``lock|unlock route|ending|tip|item <name>`` in a label): what,
    then one name field per kind so each gets its own picker; the row word says what the
    line does ("Give item", "Forget ending", …). There is no ``unlock ending``. F34-W4
    adds **Gallery picture** (``lock|unlock gallery <picture>``: a picture name of up to 5
    words; its picker offers only gallery pictures, with a thumbnail); F36-W4 adds **Scene
    replay** (``lock|unlock replay <scene>``; its picker offers the scene replays); F37-S3
    adds **Achievement** to Unlock only (``unlock achievement <name>``: achievements can't
    be taken back; its picker offers the declared ones). The top-level ``lock``
    declarations are the Database's (``forms.DECLARATIONS_GROUP``).
- P3-C (AC-F47-53), the design's Story map mark and Rollback forms. One form per
  ``flowchart`` doc, named as the game's Flowchart page names it (Insert, the rows and the
  docs agree): **Flowchart scene** (``flowchart scene "title" [hidden] [no jump]``),
  **Flowchart mark** (``flowchart ["title"] [hidden] [no jump]``, above a menu, chapter or
  ending), **Leave off flowchart** (``flowchart omit``) and **Forget flowchart**
  (``flowchart forget [<label>]``). Titles are shown text (``{`` doubled when written, as
  Ending). **Rollback** (``rollback block|off|on|fixed``) picks plain words
  (``ROLLBACK_PICKS``) and its row says what the line does for the player.

Pure: no Tk.
"""

import re
from collections.abc import Collection
from dataclasses import replace
from typing import Final

from engine.core.constants import (
    COLOR_WORDS, GLITCH_KINDS, GLITCH_SIZES, SHAKE_DIRECTIONS, SHAKE_SIZES)
from engine.script.audio import PlayAudio, QueueMusic, StopAudio, Voice
from engine.script.codex import ITEM_COUNT_MAX, CodexLock
from engine.script.effects import Flash, Shake
from engine.script.flowchart import Flowchart
from engine.script.fourthwall import CrashEffect, TitleEffect
from engine.script.glitch import JITTER, Effect
from engine.script.limits import CHAPTER_NAME_MAX
from engine.script.nodes import Chapter, Statement
from engine.script.nvl import Nvl
from engine.script.rollback import Rollback
from engine.script.routes import Ending, Lock
from engine.script.stage import Hide, Scene, Show
from engine.script.words import canonical_name, check_name
from engine.tools.editor.forms import (
    CommandForm, Field, Values, _NUMBER, _dot, _hide_read, _hide_write, _join, _one_line,
    _scene_read, _scene_write, _secs, _show_read, _show_write, _tail, _tokens, _transition,
    _write_tail, quote)

ENDING_NO_CARD: Final = "no card"
GAME_TITLE: Final = "the game's own title"          # Window title off
GAME_MESSAGE: Final = "the game's own message"      # Fake crash with no message
CRASH_PLAYER_NAME: Final = "{username}"             # the Fake crash form's Insert player name
EVERY_SOUND: Final = "every sound"                  # Stop sound with no file
CHANGES: Final = ("background", "show", "hide")     # the Transition form's Change
GLITCHES: Final = tuple(kind for kind in GLITCH_KINDS if kind != JITTER)
HOW_LONG: Final = ("burst", "on", "off")            # Glitch and Jitter character
PAGE_WORDS: Final = ("start", "new page", "end")    # Full-screen text: nvl on, clear, off
_PAGE: Final = dict(zip(PAGE_WORDS, ("on", "clear", "off"), strict=True))
CHAPTER_UNTITLED: Final = "untitled"                # chapter_name for a title with no words
LOCK_WHAT: Final = ("route", "ending", "tip", "item", "gallery", "replay")
# No ``unlock ending``: players reach its line.
# No ``lock achievement`` in a label either: achievements can't be taken back (F37).
UNLOCK_WHAT: Final = ("route", "tip", "item", "gallery", "replay", "achievement")
GALLERY_WHAT: Final = "gallery"                     # F34: its name is a picture (≤ 5 words)
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")
_NO_COLOUR: Final = frozenset(("cut", "dissolve", "glitch"))   # built-ins that take none


def _card_text(text: str) -> str:
    """``text`` as a card line writes it: quoted, with ``{`` doubled."""
    return quote(text.replace("{", "{{"))


def _ending_read(node: Statement, code: str) -> dict[str, str] | None:
    return _card_read(node, code, "ending", Ending)


def _card_read(node: Statement, code: str, word: str, kind: type[Statement],
               colour: bool = False) -> dict[str, str] | None:
    """``<word> <name> ["heading"] "title" [seconds] [with ...]`` (Ending, Chapter) read
    against ``node``; with ``colour``, the ``with`` may end in a fade colour (a "colour" key
    is added)."""
    tokens = _tokens(code)
    if not isinstance(node, kind) or not tokens or len(tokens) < 3 or tokens[0] != word \
            or tokens[1].startswith('"'):
        return None
    found = ""
    clause = getattr(node, "with_clause", None)
    if colour and clause is not None and clause.color is not None:
        found = _colour_read(tokens[-1]) or ""      # _tail takes no colour: strip it
        if not found or _colour_hex(found) != clause.color:
            return None
        tokens = tokens[:-1]
        node = replace(node, with_clause=replace(clause, color=None))
    texts = 2 if node.heading is not None else 1    # type: ignore[attr-defined]
    if not all(token.startswith('"') for token in tokens[2:2 + texts]):
        return None
    heading, title = node.heading, node.title       # type: ignore[attr-defined]
    shown = [heading, title] if heading is not None else [title]
    if [_card_text(text) for text in shown] != tokens[2:2 + texts]:   # escapes we don't write
        return None
    rest = tokens[2 + texts:]
    hold = ""
    seconds = node.seconds                          # type: ignore[attr-defined]
    if rest and _NUMBER.fullmatch(rest[0]):
        if seconds is None:
            return None
        hold, rest = rest[0], rest[1:]
    elif seconds is not None:
        return None
    tail = _tail(rest, node, allow_at=False)
    if tail is None:
        return None
    got = {"name": tokens[1], "heading": heading or "", "title": title,
           "hold": hold, "transition": tail["transition"], "seconds": tail["seconds"]}
    return {**got, "colour": found} if colour else got


def _ending_write(values: Values) -> str:
    heading = values.get("heading", "")
    return _join("ending", values["name"], _card_text(heading) if heading else "",
                 _card_text(values["title"]), values.get("hold", ""),
                 _write_tail(values, allow_at=False))


def _card_hold(values: Values) -> str:
    hold = values.get("hold", "")
    if not hold:
        return ""
    try:
        return ENDING_NO_CARD if float(hold) == 0 else _secs(hold)
    except ValueError:
        return _secs(hold)


def _card_texts(values: Values) -> str:
    title = values.get("title", "")
    heading = values.get("heading", "")
    return f"{heading}: {title}" if heading else title


def _ending_summary(values: Values) -> str:
    return _dot(values.get("name", ""), _card_texts(values), _card_hold(values),
                _transition(values))


# --- Shared bits (P2-A) -----------------------------------------------------------------------

_ESCAPES: Final = {"\\": "\\", '"': '"', "n": "\n"}


def _unquote(token: str) -> str | None:
    """The text of a quoted ``token`` (``forms.quote``'s inverse), or None for an escape
    ``quote`` doesn't write."""
    if len(token) < 2 or token[0] != '"' or token[-1] != '"':
        return None
    out: list[str] = []
    i, end = 1, len(token) - 1
    while i < end:
        char = token[i]
        if char == "\\":
            escaped = _ESCAPES.get(token[i + 1]) if i + 1 < end else None
            if escaped is None:
                return None
            out.append(escaped)
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _colour_read(token: str) -> str | None:
    """A colour as written (``white`` or ``#ffe08a``, quotes dropped), or None."""
    if token in COLOR_WORDS:
        return token
    if len(token) > 2 and token[0] == token[-1] == '"' and _HEX.fullmatch(token[1:-1]):
        return token[1:-1]
    return None


def _colour_hex(colour: str) -> str:
    """The ``#RRGGBB`` the engine loads ``colour`` as."""
    return COLOR_WORDS.get(colour, colour.upper())


def _colour_write(colour: str) -> str:
    colour = colour.strip().strip('"')
    return colour if colour in COLOR_WORDS else quote(colour)


def _fade(rest: list[str], word: str, value: float | None) -> str | None:
    """``[<word> <seconds>]`` (all of ``rest``) read against the node's ``value``: the
    seconds as written, "" for none, or None when it doesn't match."""
    if not rest:
        return "" if value is None else None
    if len(rest) == 2 and rest[0] == word and _NUMBER.fullmatch(rest[1]) and value is not None:
        return rest[1]
    return None


def _faded(word: str, values: Values) -> str:
    fade = values.get("fade", "")
    return f"{word} {fade}" if fade else ""


def _fade_text(word: str, values: Values) -> str:
    fade = values.get("fade", "")
    return f"fade {word} {_secs(fade)}" if fade else ""


# --- Transition, Shake screen, Flash (AC-F47-28) ----------------------------------------------

_STAGE: Final = {Scene: (_scene_read, "background"), Show: (_show_read, "show"),
                 Hide: (_hide_read, "hide")}
_STAGE_WRITE: Final = {"background": _scene_write, "show": _show_write, "hide": _hide_write}


def _transition_read(node: Statement, code: str) -> dict[str, str] | None:
    """A stage line whose ``with`` has a colour: F46's Background, Show and Hide forms hold
    every other ``with`` shape (this form writes those too; they read back as F46's rows)."""
    clause = getattr(node, "with_clause", None)
    found = _STAGE.get(type(node))
    tokens = _tokens(code)
    if clause is None or clause.color is None or found is None or not tokens:
        return None
    colour = _colour_read(tokens[-1]) or ""         # F46's readers take no colour: strip it
    if not colour or _colour_hex(colour) != clause.color:
        return None
    tokens = tokens[:-1]
    node = replace(node, with_clause=replace(clause, color=None))
    read, change = found
    got = read(node, " ".join(tokens))
    if got is None:
        return None
    return {"change": change, "image": "", "character": "", "look": "", "position": "",
            "transition": "", "seconds": "", **got, "colour": colour}


def _transition_write(values: Values) -> str:
    line = _STAGE_WRITE[values.get("change") or CHANGES[0]](values)
    colour, transition = values.get("colour", "").strip(), values.get("transition", "")
    if colour and transition and transition not in _NO_COLOUR:
        line = _join(line, _colour_write(colour))
    return line


def _transition_summary(values: Values) -> str:
    change = values.get("change") or CHANGES[0]
    if change == "show":
        what = _dot(_join("show", values.get("character", ""), values.get("look", "")),
                    values.get("position", ""))
    elif change == "hide":
        what = _join("hide", values.get("character", ""))
    else:
        what = values.get("image", "")
    colour = values.get("colour", "") if values.get("transition") else ""
    return _dot(what, _join(_transition(values), colour))


def _shake_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Shake) or not tokens or tokens[0] != "shake":
        return None
    rest = tokens[1:]
    size = rest.pop(0) if rest and rest[0] in SHAKE_SIZES else ""
    direction = rest.pop(0) if rest and rest[0] in SHAKE_DIRECTIONS else ""
    seconds = rest.pop(0) if rest and _NUMBER.fullmatch(rest[0]) else ""
    if rest or (node.size, node.direction) != (size or None, direction or None) \
            or (node.seconds is None) != (not seconds):
        return None
    return {"size": size, "direction": direction, "seconds": seconds}


def _flash_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Flash) or not tokens or tokens[0] != "flash":
        return None
    rest = tokens[1:]
    colour = (_colour_read(rest[0]) or "") if rest else ""
    if colour:
        rest.pop(0)
    seconds = rest.pop(0) if rest and _NUMBER.fullmatch(rest[0]) else ""
    if rest or node.color != (_colour_hex(colour) if colour else None) \
            or (node.seconds is None) != (not seconds):
        return None
    return {"colour": colour, "seconds": seconds}


def _flash_write(values: Values) -> str:
    colour = values.get("colour", "").strip()
    return _join("flash", _colour_write(colour) if colour else "", values.get("seconds", ""))


def _seconds_text(values: Values) -> str:
    return _secs(values["seconds"]) if values.get("seconds") else ""


# --- Glitch, Jitter character, Stop effects, Window title, Fake crash (AC-F47-29) -------------

def _how_long(rest: list[str], node: Effect) -> dict[str, str] | None:
    """``[size] [<seconds>|on|off]`` (all of ``rest``) read against ``node``."""
    size = rest.pop(0) if rest and rest[0] in GLITCH_SIZES else ""
    action, seconds = HOW_LONG[0], ""
    if rest and rest[0] in HOW_LONG[1:]:
        action = rest.pop(0)
    elif rest and _NUMBER.fullmatch(rest[0]):
        seconds = rest.pop(0)
    if rest or (node.size, node.action) != (size or None, action) \
            or (node.seconds is None) != (not seconds):
        return None
    return {"size": size, "action": action, "seconds": seconds}


def _how_long_write(values: Values) -> str:
    """``off`` alone, ``on`` with no length, or a burst (``off`` with a size or length, and
    ``on`` with a length, don't load: the form never writes them)."""
    action = values.get("action") or HOW_LONG[0]
    if action == "off":
        return "off"
    if action == "on":
        return _join(values.get("size", ""), "on")
    return _join(values.get("size", ""), values.get("seconds", ""))


def _how_long_text(values: Values) -> str:
    action = values.get("action") or HOW_LONG[0]
    if action == "off":
        return "off"
    return _dot(values.get("size", ""), "on" if action == "on" else _seconds_text(values))


def _glitch_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Effect) or not tokens or len(tokens) < 2 \
            or tokens[0] != "effect" or tokens[1] not in GLITCHES or node.kind != tokens[1]:
        return None
    got = _how_long(tokens[2:], node)
    return None if got is None else {"glitch": tokens[1], **got}


def _jitter_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Effect) or not tokens or len(tokens) < 3 \
            or tokens[:2] != ["effect", JITTER] or node.kind != JITTER \
            or tokens[2] != node.tag:
        return None
    got = _how_long(tokens[3:], node)
    return None if got is None else {"character": tokens[2], **got}


def _effect_off_read(node: Statement, code: str) -> dict[str, str] | None:
    if isinstance(node, Effect) and node.kind is None and _tokens(code) == ["effect", "off"]:
        return {}
    return None


def _title_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, TitleEffect) or not tokens or len(tokens) != 3 \
            or tokens[:2] != ["effect", "window_title"]:
        return None
    if node.text is None:
        return {"action": "off", "title": ""} if tokens[2] == "off" else None
    if tokens[2] != _card_text(node.text):
        return None
    return {"action": "set", "title": node.text}


def _title_write(values: Values) -> str:
    if values.get("action") == "off":
        return "effect window_title off"
    return f"effect window_title {_card_text(values.get('title', ''))}"


def _crash_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, CrashEffect) or not tokens or tokens[:2] != ["effect", "crash"]:
        return None
    if len(tokens) == 2:
        return {"message": ""} if node.body is None else None
    message = _unquote(tokens[2]) if len(tokens) == 3 else None
    if message is None or not message or node.body is None:
        return None
    return {"message": message}


def _crash_write(values: Values) -> str:
    message = values.get("message", "")
    return _join("effect crash", quote(message) if message else "")


# --- Voice, Play next, Stop sound (AC-F47-31) -------------------------------------------------

def _voice_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not tokens:
        return None
    if isinstance(node, Voice):
        if tokens != ["voice", quote(node.audio_file)]:
            return None
        return {"action": "play", "file": node.audio_file, "fade": ""}
    if not isinstance(node, StopAudio) or node.channel != "voice" \
            or node.audio_file is not None or tokens[:2] != ["stop", "voice"]:
        return None
    fade = _fade(tokens[2:], "fadeout", node.fadeout)
    return None if fade is None else {"action": "stop", "file": "", "fade": fade}


def _voice_write(values: Values) -> str:
    if values.get("action") == "stop":
        return _join("stop voice", _faded("fadeout", values))
    return f"voice {quote(values['file'])}"


def _voice_summary(values: Values) -> str:
    if values.get("action") == "stop":
        return _fade_text("out", values)
    return values.get("file", "")


def _queue_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, QueueMusic) or not tokens or not node.loop or node.volume != 100 \
            or tokens[:3] != ["queue", "music", quote(node.audio_file)]:
        return None
    fade = _fade(tokens[3:], "fadein", node.fadein)
    return None if fade is None else {"file": node.audio_file, "fade": fade}


def _stop_sound_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, StopAudio) or node.channel != "sound" or not tokens \
            or tokens[:2] != ["stop", "sound"]:
        return None
    rest, file = tokens[2:], ""
    if rest and rest[0].startswith('"'):
        if node.audio_file is None or rest[0] != quote(node.audio_file):
            return None
        file, rest = node.audio_file, rest[1:]
    elif node.audio_file is not None:
        return None
    fade = _fade(rest, "fadeout", node.fadeout)
    return None if fade is None else {"file": file, "fade": fade}


def _stop_sound_write(values: Values) -> str:
    file = values.get("file", "")
    return _join("stop sound", quote(file) if file else "", _faded("fadeout", values))


# --- Full-screen text, Chapter (AC-F47-32) ----------------------------------------------------

def _nvl_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Nvl) or tokens != ["nvl", node.action]:
        return None
    return {"page": next(page for page, action in _PAGE.items() if action == node.action)}


def _nvl_write(values: Values) -> str:
    return f"nvl {_PAGE[values.get('page') or PAGE_WORDS[0]]}"


def chapter_name(title: str, taken: Collection[str] = ()) -> str:
    """A chapter name made from ``title`` (design §4.5: "the name is made from the title"):
    its words in lower case joined by ``_`` ("The Old Footbridge" → ``the_old_footbridge``),
    a valid name (``chapter_`` before one that starts with a digit or is a reserved word,
    ``untitled`` for no words) of at most 64 characters, with ``_2``, ``_3``, … added until
    it isn't in ``taken`` (the game's chapter names)."""
    name = "_".join(re.findall(r"[^\W_]+", title.casefold()))
    if not name:
        name = CHAPTER_UNTITLED
    elif check_name(name) is not None:
        name = f"chapter_{name}"
    name = name[:CHAPTER_NAME_MAX].rstrip("_")
    used = {canonical_name(word) for word in taken}
    base, number = name, 2
    while canonical_name(name) in used:
        end = f"_{number}"
        name = base[:CHAPTER_NAME_MAX - len(end)].rstrip("_") + end
        number += 1
    return name


def _chapter_write(values: Values) -> str:
    heading, title = values.get("heading", ""), values.get("title", "")
    colour, transition = values.get("colour", "").strip(), values.get("transition", "")
    line = _join("chapter", values.get("name", "").strip() or chapter_name(title),
                 _card_text(heading) if heading else "", _card_text(title),
                 values.get("hold", ""), _write_tail(values, allow_at=False))
    if colour and transition and transition not in _NO_COLOUR:
        line = _join(line, _colour_write(colour))
    return line


def _chapter_summary(values: Values) -> str:
    colour = values.get("colour", "") if values.get("transition") else ""
    return _dot(_card_texts(values), _card_hold(values),
                _join(_transition(values), colour))


# --- Lock, Unlock (AC-F47-33) -----------------------------------------------------------------

# The Events row word for each (form, what): plain words for what the line does.
_LOCK_WORDS: Final = {
    ("lock", "route"): "Lock route", ("lock", "ending"): "Forget ending",
    ("lock", "tip"): "Forget tip", ("lock", "item"): "Take item",
    ("unlock", "route"): "Unlock route", ("unlock", "tip"): "Give tip",
    ("unlock", "item"): "Give item",
    ("lock", "gallery"): "Forget gallery picture", ("unlock", "gallery"): "Unlock gallery picture",
    ("lock", "replay"): "Forget scene replay", ("unlock", "replay"): "Unlock scene replay",
    ("unlock", "achievement"): "Unlock achievement"}


def _lock_read(word: str, whats: tuple[str, ...]):
    def read(node: Statement, code: str) -> dict[str, str] | None:
        tokens = _tokens(code)
        size = len(tokens) if getattr(node, "kind", None) == GALLERY_WHAT else 3
        amount = ""
        if isinstance(node, CodexLock) and node.written and tokens and len(tokens) == 4 \
                and tokens[3] == str(node.amount):           # F64: lock|unlock item coin 30
            amount, tokens = tokens[3], tokens[:3]
        if not isinstance(node, (Lock, CodexLock)) or node.unlock != (word == "unlock") \
                or not tokens or not 3 <= len(tokens) == size or tokens[:2] != [word, node.kind] \
                or node.kind not in whats \
                or " ".join(canonical_name(t) for t in tokens[2:]) != node.name:
            return None
        found = {"what": node.kind, **dict.fromkeys(whats, ""),
                 node.kind: " ".join(tokens[2:])}
        if amount:                                           # F64: only a written amount
            found["amount"] = amount
        return found
    return read


def _amount(values: Values) -> str:
    """F64: the How many field as written after an item's name ("" for none or 1)."""
    text = values.get("amount", "").strip()
    if not text or text == "1":
        return ""
    if not text.isdigit() or not 1 <= int(text) <= ITEM_COUNT_MAX:
        raise ValueError(f"how many must be a whole number from 1 to {ITEM_COUNT_MAX:,}")
    return str(int(text))


def _lock_write(word: str, whats: tuple[str, ...]):
    def write(values: Values) -> str:
        what = values.get("what") or whats[0]
        if what not in whats:
            raise ValueError(f"{word} can't take {what!r}")
        line = f"{word} {what} {' '.join(values[what].split())}"
        return _join(line, _amount(values)) if what == "item" else line
    return write


def _lock_summary(whats: tuple[str, ...]):
    def summary(values: Values) -> str:
        what = values.get("what") or whats[0]
        name = values.get(what, "")
        amount = values.get("amount", "").strip() if what == "item" else ""
        return f"{name} ×{amount}" if amount and amount != "1" else name
    return summary


def _lock_form(word: str, title: str, whats: tuple[str, ...],
               docs: tuple[tuple[str, str], ...]) -> CommandForm:
    return CommandForm(
        word, title, title, docs, (Lock, CodexLock),
        (Field("what", "What", "pick", options=whats,
               shown=tuple(_LOCK_LABELS[what] for what in whats)),
         *(Field(what, _LOCK_LABELS[what], "name", what, optional=True) for what in whats),
         *((Field("amount", "How many", "number", optional=True),) if "item" in whats
           else ())),
        _lock_read(word, whats), _lock_write(word, whats), _lock_summary(whats),
        lambda v: _LOCK_WORDS.get((word, v.get("what") or whats[0]), title))


_LOCK_LABELS: Final = {"route": "Route", "ending": "Ending", "tip": "Codex tip",
                       "item": "Item", "gallery": "Gallery picture", "replay": "Scene replay",
                       "achievement": "Achievement"}


# --- Flowchart marks, Rollback (P3-C: AC-F47-53) ----------------------------------------------

MARK_OWN_TITLE: Final = "its own title"             # Flowchart mark with no title
WHOLE_FLOWCHART: Final = "the whole flowchart"      # Forget flowchart with no label
HIDDEN_TEXT: Final = "hidden until reached"
NO_JUMP_TEXT: Final = "no jump"
# Rollback's picks, in the docs' order of ``rollback block|off|on|fixed``.
ROLLBACK_PICKS: Final = ("wall", "turn off", "turn on", "keep the pick")
_ROLLBACK: Final = dict(zip(ROLLBACK_PICKS, ("block", "off", "on", "fixed"), strict=True))
ROLLBACK_TEXTS: Final = {
    "wall": "players can't go back past this line",
    "turn off": "players can't go back from here on",
    "turn on": "players can go back again",
    "keep the pick": "going back through the next choice can't change the pick"}


def _flow_flags(rest: list[str], node: Flowchart) -> dict[str, str] | None:
    """``[hidden] [no jump]`` (all of ``rest``, in the docs' order) read against ``node``."""
    hidden = rest[:1] == ["hidden"]
    rest = rest[1:] if hidden else rest
    no_jump = rest[:2] == ["no", "jump"]
    rest = rest[2:] if no_jump else rest
    if rest or (hidden, no_jump) != (node.hidden, node.no_jump):
        return None
    return {"hidden": "True" if hidden else "", "no_jump": "True" if no_jump else ""}


def _flow_flags_write(values: Values) -> str:
    return _join("hidden" if values.get("hidden") else "",
                 "no jump" if values.get("no_jump") else "")


def _flow_flags_text(values: Values) -> str:
    return _dot(HIDDEN_TEXT if values.get("hidden") else "",
                NO_JUMP_TEXT if values.get("no_jump") else "")


def _flow_scene_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Flowchart) or node.form != "scene" or node.title is None \
            or not tokens or len(tokens) < 3 or tokens[:2] != ["flowchart", "scene"] \
            or tokens[2] != _card_text(node.title):
        return None
    flags = _flow_flags(tokens[3:], node)
    return None if flags is None else {"title": node.title, **flags}


def _flow_mark_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Flowchart) or node.form != "mark" or not tokens \
            or tokens[0] != "flowchart":
        return None
    rest, title = tokens[1:], ""
    if rest and rest[0].startswith('"'):
        if node.title is None or rest[0] != _card_text(node.title):
            return None
        title, rest = node.title, rest[1:]
    elif node.title is not None:
        return None
    flags = _flow_flags(rest, node)
    return None if flags is None else {"title": title, **flags}


def _flow_omit_read(node: Statement, code: str) -> dict[str, str] | None:
    if isinstance(node, Flowchart) and node.form == "omit" \
            and _tokens(code) == ["flowchart", "omit"]:
        return {}
    return None


def _flow_forget_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, Flowchart) or node.form != "forget" or not tokens \
            or tokens[:2] != ["flowchart", "forget"] or len(tokens) > 3:
        return None
    if len(tokens) == 2:
        return {"scene": ""} if node.target is None else None
    if tokens[2].startswith('"') or canonical_name(tokens[2]) != node.target:
        return None
    return {"scene": tokens[2]}


def _flow_mark_write(values: Values) -> str:
    title = values.get("title", "")
    return _join("flowchart", _card_text(title) if title else "", _flow_flags_write(values))


def _rollback_read(node: Statement, code: str) -> dict[str, str] | None:
    if not isinstance(node, Rollback) or _tokens(code) != ["rollback", node.word]:
        return None
    return {"what": next(pick for pick, word in _ROLLBACK.items() if word == node.word)}


def _rollback_write(values: Values) -> str:
    return f"rollback {_ROLLBACK[values.get('what') or ROLLBACK_PICKS[0]]}"


_FLAG_FIELDS: Final = (
    Field("hidden", "Hidden until reached", "flag", optional=True),
    Field("no_jump", "No jump", "flag", optional=True))


# --- Music and Sound with options (P3-C) ------------------------------------------------------
# F46's Music and Sound forms read only the plain lines (their fields are kept as they are).
# These read the lines with options, in the docs' order: ``play music "<file>" [fadein <s>]
# [fadeout <s>] [volume <n>]`` and ``play sound "<file>" [loop] [volume <n>]``. With no
# option set, a line they write reads back as F46's Music or Sound row (as Transition's).

def _audio_options(rest: list[str], node: PlayAudio, fades: tuple[str, ...]
                   ) -> dict[str, str] | None:
    """``[<fade> <s>]… [volume <n>]`` (all of ``rest``) read against ``node``."""
    got: dict[str, str] = {}
    for word in fades:
        value = getattr(node, word)
        if rest[:1] == [word] and len(rest) > 1 and _NUMBER.fullmatch(rest[1]) \
                and value is not None:
            got[word], rest = rest[1], rest[2:]
        elif value is not None:
            return None
        else:
            got[word] = ""
    got["volume"] = ""
    if rest[:1] == ["volume"] and len(rest) > 1 and rest[1].isdigit() \
            and int(rest[1]) == node.volume:
        got["volume"], rest = rest[1], rest[2:]
    elif node.volume != 100:
        return None
    return None if rest else got


def _play_options(values: Values, fades: tuple[str, ...]) -> str:
    parts = [f"{word} {values[word]}" for word in fades if values.get(word, "").strip()]
    volume = values.get("volume", "").strip()
    return _join(*parts, f"volume {volume}" if volume else "")


def _music_more_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, PlayAudio) or node.channel != "music" or not node.loop \
            or node.restart or node.start is not None or not tokens \
            or tokens[:3] != ["play", "music", quote(node.audio_file)]:
        return None
    got = _audio_options(tokens[3:], node, ("fadein", "fadeout"))
    return None if got is None else {"file": node.audio_file, **got}


def _sound_more_read(node: Statement, code: str) -> dict[str, str] | None:
    tokens = _tokens(code)
    if not isinstance(node, PlayAudio) or node.channel != "sound" or node.restart \
            or node.start is not None or not tokens \
            or tokens[:3] != ["play", "sound", quote(node.audio_file)]:
        return None
    rest = tokens[3:]
    loop = rest[:1] == ["loop"]
    if loop != node.loop:
        return None
    got = _audio_options(rest[1:] if loop else rest, node, ("fadein",))
    if got is None or got.pop("fadein"):            # a sound's fade in: a Script row
        return None
    return {"file": node.audio_file, "loop": "True" if loop else "", **got}


def _music_more_summary(values: Values) -> str:
    fadein, fadeout = values.get("fadein", ""), values.get("fadeout", "")
    return _dot(values.get("file", ""), f"fade in {_secs(fadein)}" if fadein else "",
                f"old music fades out {_secs(fadeout)}" if fadeout else "",
                _volume_text(values))


def _volume_text(values: Values) -> str:
    volume = values.get("volume", "")
    return f"volume {volume}%" if volume else ""


_SIZE_PICK: Final = Field("size", "Size", "pick", options=("", *GLITCH_SIZES), optional=True)
_HOW_LONG_FIELDS: Final = (
    _SIZE_PICK,
    Field("action", "How long", "pick", options=HOW_LONG),
    Field("seconds", "Seconds", "number", optional=True))
_SOUND_FILE: Final = Field("file", "File", "name", "audio")


FORMS: tuple[CommandForm, ...] = (
    CommandForm(
        "ending", "Ending", "Ending", (("ending", ""),), Ending,
        (Field("name", "Ending", "name", "ending"),
         Field("heading", "Heading", "text", optional=True),
         Field("title", "Title", "text"),
         Field("hold", "Card seconds", "number", optional=True),
         Field("transition", "Transition", "name", "transition", optional=True),
         Field("seconds", "Transition seconds", "number", optional=True)),
        _ending_read, _ending_write, _ending_summary),
    # P2-A: AC-F47-28
    CommandForm(
        "transition", "Transition", "Transition", (("with", ""),), (Scene, Show, Hide),
        (Field("change", "Change", "pick", options=CHANGES),
         Field("image", "Background", "name", "image", optional=True),
         Field("character", "Character", "name", "sprite", optional=True),
         Field("look", "Look", "text", optional=True),
         Field("position", "Where", "name", "position", optional=True),
         Field("transition", "Transition", "name", "transition"),
         Field("seconds", "Seconds", "number", optional=True),
         Field("colour", "Fade colour", "text", optional=True)),
        _transition_read, _transition_write, _transition_summary),
    CommandForm(
        "shake", "Shake screen", "Shake screen", (("shake", ""),), Shake,
        (Field("size", "Size", "pick", options=("", *SHAKE_SIZES), optional=True),
         Field("direction", "Direction", "pick", options=("", *SHAKE_DIRECTIONS),
               optional=True),
         Field("seconds", "Seconds", "number", optional=True)),
        _shake_read,
        lambda v: _join("shake", v.get("size", ""), v.get("direction", ""),
                        v.get("seconds", "")),
        lambda v: _dot(v.get("size", ""), v.get("direction", ""), _seconds_text(v))),
    CommandForm(
        "flash", "Flash", "Flash", (("flash", ""),), Flash,
        (Field("colour", "Colour", "text", optional=True),
         Field("seconds", "Seconds", "number", optional=True)),
        _flash_read, _flash_write,
        lambda v: _dot(v.get("colour", ""), _seconds_text(v))),
    # AC-F47-29
    CommandForm(
        "glitch", "Glitch", "Glitch", (("effect", "effect <glitch>"),), Effect,
        (Field("glitch", "Glitch", "pick", options=GLITCHES), *_HOW_LONG_FIELDS),
        _glitch_read,
        lambda v: _join("effect", v["glitch"], _how_long_write(v)),
        lambda v: _dot(v.get("glitch", ""), _how_long_text(v))),
    CommandForm(
        "jitter", "Jitter character", "Jitter character", (("effect", "effect jitter"),),
        Effect,
        (Field("character", "Character", "name", "sprite"), *_HOW_LONG_FIELDS),
        _jitter_read,
        lambda v: _join("effect", JITTER, v["character"], _how_long_write(v)),
        lambda v: _dot(v.get("character", ""), _how_long_text(v))),
    CommandForm(
        "effect_off", "Stop effects", "Stop effects", (), Effect, (),
        _effect_off_read, lambda v: "effect off", lambda v: ""),
    CommandForm(
        "window_title", "Window title", "Window title",
        (("effect", "effect window_title"),), TitleEffect,
        (Field("action", "Window title", "pick", options=("set", "off")),
         Field("title", "Title", "text", optional=True)),
        _title_read, _title_write,
        lambda v: GAME_TITLE if v.get("action") == "off" else v.get("title", "")),
    CommandForm(
        "crash", "Fake crash", "Fake crash", (("effect", "effect crash"),), CrashEffect,
        (Field("message", "Message", "text", optional=True),),
        _crash_read, _crash_write,
        lambda v: _one_line(v.get("message", "")) or GAME_MESSAGE),
    # AC-F47-31
    CommandForm(
        "voice", "Voice", "Voice", (("voice", ""),), (Voice, StopAudio),
        (Field("action", "Voice", "pick", options=("play", "stop")),
         replace(_SOUND_FILE, optional=True),
         Field("fade", "Fade out (seconds)", "number", optional=True)),
        _voice_read, _voice_write, _voice_summary,
        lambda v: "Stop voice" if v.get("action") == "stop" else "Voice"),
    CommandForm(
        "queue", "Play next", "Play next", (("queue", ""),), QueueMusic,
        (_SOUND_FILE, Field("fade", "Fade in (seconds)", "number", optional=True)),
        _queue_read,
        lambda v: _join("queue music", quote(v["file"]), _faded("fadein", v)),
        lambda v: _dot(v.get("file", ""), _fade_text("in", v))),
    CommandForm(
        "stop_sound", "Stop sound", "Stop sound", (), StopAudio,
        (replace(_SOUND_FILE, label="Only this file", optional=True),
         Field("fade", "Fade out (seconds)", "number", optional=True)),
        _stop_sound_read, _stop_sound_write,
        lambda v: _dot(v.get("file", "") or EVERY_SOUND, _fade_text("out", v))),
    # P2-B: AC-F47-32
    CommandForm(
        "nvl", "Full-screen text", "Full-screen text", (("nvl", ""),), Nvl,
        (Field("page", "Full-screen text", "pick", options=PAGE_WORDS),),
        _nvl_read, _nvl_write, lambda v: v.get("page") or PAGE_WORDS[0]),
    CommandForm(
        "chapter", "Chapter", "Chapter", (("chapter", ""),), Chapter,
        (Field("heading", "Heading", "text", optional=True),
         Field("title", "Title", "text"),
         Field("hold", "Card seconds", "number", optional=True),
         Field("transition", "Transition", "name", "transition", optional=True),
         Field("seconds", "Transition seconds", "number", optional=True),
         Field("colour", "Fade colour", "text", optional=True),
         Field("name", "Name (made from the title)", "text", optional=True)),
        lambda node, code: _card_read(node, code, "chapter", Chapter, colour=True),
        _chapter_write, _chapter_summary),
    # AC-F47-33. A ``lock`` declaration (route, codex entry) is the Database's: its docs are
    # in the Declarations group, which ``forms.form_for_doc`` never gives a form.
    _lock_form("lock", "Lock", LOCK_WHAT,
               (("lock", "lock route|ending"), ("lock", "lock tip|item"),
                ("lock", "lock gallery"), ("lock", "lock replay"))),
    _lock_form("unlock", "Unlock", UNLOCK_WHAT,
               (("unlock", "unlock route"), ("unlock", "unlock tip|item"),
                ("unlock", "unlock gallery"), ("unlock", "unlock replay"),
                ("unlock", "unlock achievement"))),
    # P3-C: AC-F47-53
    CommandForm(
        "flow_scene", "Flowchart scene", "Flowchart scene",
        (("flowchart", "flowchart scene"),), Flowchart,
        (Field("title", "Title", "text"), *_FLAG_FIELDS),
        _flow_scene_read,
        lambda v: _join("flowchart scene", _card_text(v.get("title", "")),
                        _flow_flags_write(v)),
        lambda v: _dot(v.get("title", ""), _flow_flags_text(v))),
    CommandForm(
        "flow_mark", "Flowchart mark", "Flowchart mark", (("flowchart", "flowchart ["),),
        Flowchart,
        (Field("title", "Title", "text", optional=True), *_FLAG_FIELDS),
        _flow_mark_read, _flow_mark_write,
        lambda v: _dot(v.get("title", "") or MARK_OWN_TITLE, _flow_flags_text(v))),
    CommandForm(
        "flow_omit", "Leave off flowchart", "Leave off flowchart",
        (("flowchart", "flowchart omit"),), Flowchart, (),
        _flow_omit_read, lambda v: "flowchart omit", lambda v: ""),
    CommandForm(
        "flow_forget", "Forget flowchart", "Forget flowchart",
        (("flowchart", "flowchart forget"),), Flowchart,
        (Field("scene", "Only this scene", "scene", "label", optional=True),),
        _flow_forget_read,
        lambda v: _join("flowchart forget", v.get("scene", "").strip()),
        lambda v: v.get("scene", "") or WHOLE_FLOWCHART),
    CommandForm(
        "rollback", "Rollback", "Rollback", (("rollback", ""),), Rollback,
        (Field("what", "Rollback", "pick", options=ROLLBACK_PICKS),),
        _rollback_read, _rollback_write,
        lambda v: ROLLBACK_TEXTS[v.get("what") or ROLLBACK_PICKS[0]]),
    # Music and Sound with options (no docs: Insert opens F46's Music and Sound).
    CommandForm(
        "music_options", "Music", "Music", (), PlayAudio,
        (_SOUND_FILE,
         Field("fadein", "Fade in (seconds)", "number", optional=True),
         Field("fadeout", "Fade out the old music (seconds)", "number", optional=True),
         Field("volume", "Volume (%)", "number", optional=True)),
        _music_more_read,
        lambda v: _join("play music", quote(v["file"]),
                        _play_options(v, ("fadein", "fadeout"))),
        _music_more_summary),
    CommandForm(
        "sound_options", "Sound", "Sound", (), PlayAudio,
        (_SOUND_FILE,
         Field("loop", "Repeat until stopped", "flag", optional=True),
         Field("volume", "Volume (%)", "number", optional=True)),
        _sound_more_read,
        lambda v: _join("play sound", quote(v["file"]), "loop" if v.get("loop") else "",
                        _play_options(v, ())),
        lambda v: _dot(v.get("file", ""), "repeats" if v.get("loop") else "",
                       _volume_text(v))),
)

__all__ = ["CHANGES", "CHAPTER_UNTITLED", "CRASH_PLAYER_NAME", "ENDING_NO_CARD", "EVERY_SOUND",
           "FORMS", "GAME_MESSAGE", "GAME_TITLE", "GLITCHES", "HIDDEN_TEXT", "HOW_LONG",
           "GALLERY_WHAT", "LOCK_WHAT", "MARK_OWN_TITLE", "NO_JUMP_TEXT", "PAGE_WORDS", "ROLLBACK_PICKS",
           "ROLLBACK_TEXTS", "UNLOCK_WHAT", "WHOLE_FLOWCHART", "chapter_name"]

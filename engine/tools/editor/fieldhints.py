"""Every Studio field explains itself (F47 P3-D, AC-F47-54; design §4: "help on every field").

Why this module exists: a form field's label is a word or two ("Look", "Seconds"). Its hint
is the plain-language sentence a new author needs, shown as the field's tooltip. One table
here keeps them in one place, so a test can check that no field is left without one:

- ``form_hint(form_key, field_key)``: a command form's field (``forms.all_forms()``). A
  form's own sentence (``FORM_HINTS``) wins over the shared one for that field key
  (``COMMON``), since "Seconds" means a different thing on Wait and on Shake screen.
- ``CHOICE_HINTS``: the Choice form's own fields (its dialog isn't built from ``Field``s).
- ``database_tips(form)``: label → hint for a Database form
  (``fieldwidgets.FormGrid(tips=…)`` puts each on its row's label).

Game settings' hints come from their keys' docs (``settingsmodel.Field.help``, shown under
the field by ``settingsview.field_hint``), so they are not repeated here. Pure: no Tk.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from engine.tools.editor import dbmodel as db

CHOICE_FORM: Final = "menu"         # ``forms.CHOICE_FORM`` (forms imports nothing from here)

# Field key → its hint on any form that has no sentence of its own for it.
COMMON: Final[Mapping[str, str]] = MappingProxyType({
    "character": "Which character. Pick one from the Database, or type a new name.",
    "look": "The character's look (a picture name such as happy). Empty: the look they have.",
    "position": "Where they stand on the screen (left, center, right, or your own spots).",
    "transition": "How the change appears (dissolve, fade, …). Empty: it happens at once.",
    "seconds": "How long it takes, in seconds. Empty: the usual length.",
    "image": "The picture to show behind everything. Empty: a plain black screen.",
    "file": "The sound file to play, from your game's audio folder.",
    "colour": "A colour word (white, black, red) or a code like #ffe08a.",
    "size": "How strong it is. Empty: the game's usual size.",
    "action": "How long it lasts: a burst of some seconds, on until stopped, or off.",
    "title": "The words players see, as you type them.",
    "heading": "A small line above the title, such as Chapter 2. Empty: none.",
    "hold": "How long the card stays on screen, in seconds. 0: no card. Empty: the usual.",
    "volume": "How loud, from 0 to 100 (%). Empty: full volume.",
    "hidden": "Keep it off the Flowchart page until the player reaches it.",
    "no_jump": "Players can't jump back to it from the Flowchart page.",
    "scene": "The scene (label) to go to.",
})

# Form key → field key → its hint, where the shared one isn't right.
FORM_HINTS: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType({
    "say": {"speaker": "Who says it. Empty: narration, with no name shown.",
            "look": "Change the speaker's look as they say it. Empty: keep their look.",
            "text": "What is said, as players will read it."},
    "show": {"character": "The character to bring on stage, from the Database.",
             "transition": "How they appear (dissolve, …). Empty: at once."},
    "hide": {"character": "The character to take off stage.",
             "transition": "How they leave (dissolve, …). Empty: at once."},
    "scene": {"transition": "How the new background appears. Empty: at once."},
    "music": {"action": "Play a track (it loops), or stop the music playing.",
              "file": "The music file, from your game's audio folder.",
              "fade": "Seconds to fade in (play) or fade out (stop). Empty: no fade."},
    "sound": {"file": "The sound effect to play once, over the music."},
    "jump": {"scene": "The scene the story goes to next. It doesn't come back."},
    "call": {"scene": "The scene to visit. At its Return, the story comes back here."},
    "pause": {"seconds": "How long to wait. Empty: wait until the player clicks."},
    "set": {"name": "The story variable to change (made on the Database's Variables page).",
            "op": "= sets it, += adds to it, -= takes away from it.",
            "value": "The new value or amount: a number, \"text in quotes\", True or False."},
    "points": {"meter": "The meter to change (made on the Database's Meters page).",
               "op": "+= adds, -= takes away, = sets it to the amount.",
               "amount": "A whole number."},
    "if": {"keyword": "if starts a test; elif (else if) and else follow one.",
           "condition": "When the lines below play. Build it with the condition builder."},
    "ending": {"name": "Which ending this is (made on the Database's Endings page, or new).",
               "title": "The ending's name, shown on its card and in the Endings list.",
               "seconds": "How long the transition takes, in seconds."},
    "transition": {"change": "What changes: the background, or a character coming or going.",
                   "image": "The new background (when the change is background).",
                   "character": "The character coming or going.",
                   "transition": "How the change appears (fade, dissolve, …).",
                   "colour": "The colour a fade passes through. Empty: black."},
    "shake": {"size": "How hard the screen shakes. Empty: the game's usual.",
              "direction": "Side to side or up and down. Empty: the game's usual.",
              "seconds": "How long it shakes. Empty: the usual length."},
    "flash": {"colour": "The flash's colour: white, black, red or a code like #ffe08a.",
              "seconds": "How long the flash takes. Empty: the usual length."},
    "glitch": {"glitch": "The kind: tear (torn lines), colorshift or static.",
               "seconds": "With burst: how many seconds it lasts."},
    "jitter": {"character": "The character whose picture jitters.",
               "seconds": "With burst: how many seconds it lasts."},
    "window_title": {"action": "Set a new window title, or go back to the game's own.",
                     "title": "The title shown on the game window."},
    "crash": {"message": "The fake error message. Empty: the game's own (see Button words)."},
    "voice": {"action": "Play a voice line for the next line of text, or stop the voice.",
              "file": "The voice file, from your game's audio folder.",
              "fade": "When stopping: seconds to fade out. Empty: stop at once."},
    "queue": {"file": "The track that plays when the current music ends.",
              "fade": "Seconds it fades in. Empty: no fade."},
    "stop_sound": {"file": "Stop only this sound. Empty: stop every sound.",
                   "fade": "Seconds to fade out. Empty: stop at once."},
    "nvl": {"page": "Start full-screen text, clear it for a new page, or end it."},
    "chapter": {"title": "The chapter's name, shown on its card and the Flowchart page.",
                "seconds": "How long the transition takes, in seconds.",
                "colour": "The colour a fade passes through. Empty: black.",
                "name": "Its name in the script. Empty: made from the title for you."},
    "lock": {"what": "What to lock or take away: a route, an ending, a codex tip, an item, "
                     "a gallery picture or a scene replay.",
             "replay": "The scene replay players forget (its tile in Extras is locked again).",
             "gallery": "The gallery picture players forget (its tile is locked again).",
             "route": "The route to lock (players can't take it until it's unlocked).",
             "ending": "The ending players forget they've reached.",
             "tip": "The codex tip players lose.",
             "item": "The item players lose."},
    "unlock": {"what": "What to open or give: a route, a codex tip, an item, a gallery "
                       "picture or a scene replay.",
               "replay": "The scene that joins the player's Scenes page without being played.",
               "gallery": "The picture that joins the player's gallery without being shown.",
               "route": "The route to open.",
               "tip": "The codex tip players get.",
               "item": "The item players get."},
    "flow_scene": {"title": "The scene's name on the Flowchart page (plain text)."},
    "flow_mark": {"title": "The box's name on the Flowchart page. Empty: the choice's "
                           "question (above a menu) or the chapter's own title."},
    "flow_forget": {"scene": "Forget only the boxes in this scene. Empty: the whole chart."},
    "rollback": {"what": "wall: no going back past here. turn off / turn on: stop or allow "
                         "going back. keep the pick: the next choice can't be changed."},
    "music_options": {"file": "The music file, from your game's audio folder.",
                      "fadein": "Seconds the new track fades in. Empty: the usual.",
                      "fadeout": "Seconds the old music fades out. Empty: the usual.",
                      "volume": "How loud this track plays, from 0 to 100 (%)."},
    "sound_options": {"file": "The sound effect to play, over the music.",
                      "loop": "Repeat it until a Stop sound line (for rain, a river, …).",
                      "volume": "How loud it plays, from 0 to 100 (%)."},
    "file": {"action": "Write a file next to the game, delete it, check it's there, or "
                       "read it.",
             "name": "The file's name, from the Database's Meta files.",
             "text": "What the file says. Empty: a copy of the file's original text.",
             "into": "The story variable that gets the result."},
    "ui": {"action": "What to change in the game's menus: the look, saving or loading.",
           "style": "The style to use (made on Game settings' Styles page).",
           "reason": "Why saving or loading is off, shown to players. Empty: none."},
})

# The Choice form's fields (``formdialogs.ChoiceDialog``).
CHOICE_HINTS: Final[Mapping[str, str]] = MappingProxyType({
    "speaker": "Who asks the question. Empty: narration.",
    "look": "The speaker's look as they ask. Empty: keep their look.",
    "question": "The line shown with the choices. Empty: no question.",
    "text": "The choice's words, as players see them.",
    "condition": "Only show this choice when this is true. Empty: always.",
    "goes": "The scene this choice goes to, or continues here.",
})

# Database form → its label → hint (labels as ``database``/``dbmore`` show them). A form is
# its category's, except ``ROUTE``: routes and endings share the "ending" category.
ROUTE: Final = "route"
_NAME: Final = "The name used for it in your script. Renaming changes every line that uses it."
DATABASE: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType({
    db.CATEGORY_CHARACTER: {
        "Name shown": "The name players see in the name tab when this character speaks.",
        "Name colour": "The colour of the character's name in the name tab.",
        "Text colour": "The colour of the words this character says. Empty: the usual.",
        "Text style": "Show this character's lines in italics (for thoughts, a phone, …).",
        "Sound": "A short blip that plays as their text types out. Empty: none.",
        "Every": "Blip on every this many letters (1 to 10).",
        "Pitch": "How much each blip's pitch varies: 0 (none) to 0.5.",
        "Volume": "Loudness in % of the sound volume (0 to 100).",
    },
    db.CATEGORY_VARIABLE: {
        "Script name": _NAME,
        "Kind": "What it holds: a number, a yes/no, or text.",
        "Starting value": "Its value when a new game starts.",
    },
    db.CATEGORY_PICTURE: {
        "Colour": "A background that is a plain colour instead of a picture file.",
        "Script name": _NAME,
        "File": "The picture file it shows.",
    },
    db.CATEGORY_SOUND: {
        "Folder": "Where the file is: music, sound effects, voice or blips.",
        "File": "The sound file.",
    },
    db.CATEGORY_METER: {
        "Script name": _NAME,
        "Lowest": "The meter never goes below this.",
        "Highest": "The meter never goes above this.",
        "Start": "Its value when a new game starts.",
    },
    db.CATEGORY_CODEX: {
        "Script name": _NAME,
        "Kind": "A tip (something learned) or an item (something carried).",
        "Title": "The name players see in the codex.",
        "Category": "The tab it's listed under in the codex.",
        "Picture": "A picture shown with it in the codex. Empty: none.",
        "Text": "What the codex says about it. One paragraph per line.",
    },
    ROUTE: {
        "Script name": _NAME,
        "Title": "The route's name, shown on its padlock on the Flowchart page.",
        "Starts at": "The scene where the route begins.",
    },
    db.CATEGORY_ENDING: {
        "Heading": "The small line above the ending's title on its card.",
        "Script name": "The name its Ending lines use.",
        "Where": "The script file and line that reaches it.",
    },
    db.CATEGORY_TRANSITION: {
        "Script name": _NAME,
        "Kind": "How the change looks: a fade, a dissolve, a wipe, or a mask picture.",
        "Seconds": "How long it takes, in seconds.",
        "Colour": "The colour a fade passes through.",
        "Mask picture": "A black-and-white picture: the new scene appears dark parts first.",
        "Soft edge": "How soft the mask's edge is, from 0 (sharp) to 1.",
        "Direction": "Play the mask the other way round (light parts first).",
    },
    db.CATEGORY_POSITION: {
        "Script name": _NAME,
        "Across (x)": "0 is the left edge, 1280 the right.",
        "Down (y)": "720 is the bottom edge.",
    },
})


def form_hint(form_key: str, field_key: str) -> str:
    """The hint for ``field_key`` on form ``form_key`` ("" when there is none; the Choice
    form, ``menu``, has ``CHOICE_HINTS``)."""
    if form_key == CHOICE_FORM:
        return CHOICE_HINTS.get(field_key, "")
    own = FORM_HINTS.get(form_key, {})
    return own.get(field_key) or COMMON.get(field_key, "")


def database_tips(category: str) -> Mapping[str, str]:
    """Label → hint for a Database form (``DATABASE``'s key; a chapter shows an ending's
    rows)."""
    return DATABASE.get(db.CATEGORY_ENDING if category == db.CATEGORY_CHAPTER else category,
                        {})


__all__ = ["CHOICE_HINTS", "COMMON", "DATABASE", "FORM_HINTS", "ROUTE", "database_tips",
           "form_hint"]
